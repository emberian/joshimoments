use crate::{
    CaptureAttestation, FactEvidence, FactProtection, MARKET_FACT_CONTRACT, MarketFactPayload,
    MarketFactV1, MarketStream, SocialProductFact, ValidInterval, ValidityBasis,
};
use joshi_attention::{
    AttentionDataset, AttentionEventId, CoverageState, EventTime, EventTimeStatus,
    ExactAttentionInput, ProtectionDomain,
};
use joshi_domain::StableString;
use thiserror::Error;

use crate::AttentionFact;

/// Strict failure adapting the existing attention contract into one stored market fact.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum AttentionAdapterError {
    #[error("attention dataset is invalid: {0}")]
    InvalidDataset(String),
    #[error("attention event is absent from the dataset")]
    MissingEvent,
    #[error("attention event references an absent forcing input")]
    MissingForcingInput,
    #[error("attention event references an absent selected identity")]
    MissingIdentity,
    #[error("attention event references an absent selected territory")]
    MissingTerritory,
    #[error("attention event references an absent selected cluster context")]
    MissingCluster,
    #[error("source event-time bounds are malformed")]
    InvalidEventTime,
    #[error("capture attestation bounds are malformed")]
    InvalidCaptureAttestation,
    #[error("input availability precedes observation")]
    InvalidAvailability,
    #[error("input coverage is internally inconsistent")]
    InvalidCoverage,
    #[error("an identifier could not cross the stable wire boundary: {0}")]
    InvalidIdentity(String),
}

/// Adapts one exact social/product occurrence without widening capture time into object validity.
///
/// # Errors
///
/// Refuses malformed event-time, availability, coverage, or capture bounds.
pub fn adapt_social_input(
    subject_id: StableString,
    input: ExactAttentionInput,
    capture_attestation: Option<CaptureAttestation>,
) -> Result<MarketFactV1, AttentionAdapterError> {
    validate_input(&input)?;
    validate_capture(capture_attestation.as_ref())?;
    let (valid_time, validity_basis) = validity_from_event(&input.event_time)?;
    let evidence = evidence_from_input(&input);
    Ok(MarketFactV1 {
        contract: stable(MARKET_FACT_CONTRACT)?,
        stream: MarketStream::SocialProduct,
        subject_id,
        valid_time,
        validity_basis,
        available_at: input.evidence.available_at,
        available_commit: input.evidence.available_commit,
        capture_attestation,
        chain: None,
        evidence,
        payload: MarketFactPayload::SocialProduct(Box::new(SocialProductFact { input })),
    })
}

/// Extracts one marked event and only the identity/territory/cluster context selected for it.
///
/// # Errors
///
/// Refuses an invalid attention dataset or any broken selected-context reference.
#[allow(clippy::too_many_lines)] // One pass keeps event and selected-context extraction atomic.
pub fn adapt_attention_event(
    subject_id: StableString,
    dataset: &AttentionDataset,
    event_id: &AttentionEventId,
) -> Result<MarketFactV1, AttentionAdapterError> {
    dataset
        .validate()
        .map_err(|error| AttentionAdapterError::InvalidDataset(error.to_string()))?;
    let event = dataset
        .attention_events
        .iter()
        .find(|candidate| candidate.attention_event_id == *event_id)
        .cloned()
        .ok_or(AttentionAdapterError::MissingEvent)?;
    let forcing_input = dataset
        .exact_inputs
        .iter()
        .find(|input| input.input_id == event.forcing_input_id)
        .cloned()
        .ok_or(AttentionAdapterError::MissingForcingInput)?;
    let selected_identity = event
        .caller_identity_version_id
        .as_ref()
        .map(|identity_id| {
            dataset
                .identity_versions
                .iter()
                .find(|identity| identity.identity_version_id == *identity_id)
                .cloned()
                .ok_or(AttentionAdapterError::MissingIdentity)
        })
        .transpose()?;
    let selected_territory = event
        .territory_snapshot_id
        .as_ref()
        .map(|territory_id| {
            dataset
                .territory_snapshots
                .iter()
                .find(|territory| territory.territory_snapshot_id == *territory_id)
                .cloned()
                .ok_or(AttentionAdapterError::MissingTerritory)
        })
        .transpose()?;
    let selected_cluster = event
        .caller_cluster_context_id
        .as_ref()
        .map(|cluster_id| {
            dataset
                .selected_cluster_contexts
                .iter()
                .find(|cluster| cluster.cluster_context_id == *cluster_id)
                .cloned()
                .ok_or(AttentionAdapterError::MissingCluster)
        })
        .transpose()?;
    let response_observations = dataset
        .response_observations
        .iter()
        .filter(|response| {
            dataset.kernel_events.iter().any(|kernel| {
                kernel.kernel_event_id == response.kernel_event_id
                    && kernel.attention_event_id == event.attention_event_id
            })
        })
        .cloned()
        .collect::<Vec<_>>();
    let available_at = response_observations
        .iter()
        .fold(event.available_at, |latest, response| {
            latest
                .max(response.available_at)
                .max(response.analysis_cutoff)
        });
    let available_at = selected_identity.as_ref().map_or(available_at, |identity| {
        available_at.max(identity.knowledge_time.known_from)
    });
    let available_at = selected_territory
        .as_ref()
        .map_or(available_at, |territory| {
            available_at.max(territory.knowledge_time.known_from)
        });
    let available_at = selected_cluster.as_ref().map_or(available_at, |cluster| {
        available_at
            .max(cluster.source_available_at)
            .max(cluster.selected_as_of)
    });
    let available_commit = selected_identity
        .as_ref()
        .map_or(event.available_commit, |identity| {
            event
                .available_commit
                .max(identity.knowledge_time.available_commit)
        });
    let available_commit = selected_territory
        .as_ref()
        .map_or(available_commit, |territory| {
            available_commit.max(territory.knowledge_time.available_commit)
        });
    let available_commit = selected_cluster
        .as_ref()
        .map_or(available_commit, |cluster| {
            available_commit
                .max(cluster.source_available_commit)
                .max(cluster.selected_as_of_commit)
        });
    let (valid_time, validity_basis) = validity_from_event(&event.event_time)?;
    let evidence = evidence_from_input(&forcing_input);
    let response_coverage = event.coverage.clone();
    Ok(MarketFactV1 {
        contract: stable(MARKET_FACT_CONTRACT)?,
        stream: MarketStream::Attention,
        subject_id,
        valid_time,
        validity_basis,
        available_at,
        available_commit,
        capture_attestation: None,
        chain: event.chain_slot.map(|slot| crate::ChainPoint {
            slot,
            // Attention events are marks, not a source of chain-finality authority.
            finality: crate::ChainFinality::Unsupported,
        }),
        evidence,
        payload: MarketFactPayload::Attention(Box::new(AttentionFact {
            event,
            forcing_input,
            selected_identity,
            selected_territory,
            selected_cluster,
            response_observations,
            response_coverage,
        })),
    })
}

fn validate_input(input: &ExactAttentionInput) -> Result<(), AttentionAdapterError> {
    if input.evidence.available_at < input.evidence.observed_at {
        return Err(AttentionAdapterError::InvalidAvailability);
    }
    validity_from_event(&input.event_time)?;
    let coverage = &input.evidence.coverage;
    if matches!(coverage.state, CoverageState::Complete) && !coverage.gap_ids.is_empty() {
        return Err(AttentionAdapterError::InvalidCoverage);
    }
    Ok(())
}

fn validate_capture(capture: Option<&CaptureAttestation>) -> Result<(), AttentionAdapterError> {
    if capture.is_some_and(|value| value.started_at >= value.ended_at) {
        return Err(AttentionAdapterError::InvalidCaptureAttestation);
    }
    Ok(())
}

fn validity_from_event(
    event_time: &EventTime,
) -> Result<(Option<ValidInterval>, ValidityBasis), AttentionAdapterError> {
    match event_time.status {
        EventTimeStatus::Exact | EventTimeStatus::Bounded => {
            let (Some(lower), Some(upper)) = (event_time.lower, event_time.upper) else {
                return Err(AttentionAdapterError::InvalidEventTime);
            };
            if lower >= upper {
                return Err(AttentionAdapterError::InvalidEventTime);
            }
            Ok((
                Some(ValidInterval {
                    lower,
                    upper: Some(upper),
                }),
                ValidityBasis::SourceEvent,
            ))
        }
        EventTimeStatus::SourceMissing | EventTimeStatus::NotApplicable => {
            if event_time.lower.is_some()
                || event_time.upper.is_some()
                || event_time.precision_us.is_some()
            {
                return Err(AttentionAdapterError::InvalidEventTime);
            }
            Ok((None, ValidityBasis::CaptureAttestationOnly))
        }
    }
}

fn evidence_from_input(input: &ExactAttentionInput) -> FactEvidence {
    FactEvidence {
        observation_ids: vec![input.evidence.observation_id.clone()],
        source_ids: vec![input.evidence.source_id.clone()],
        coverage_ids: vec![input.evidence.coverage.scope_id.clone()],
        gap_ids: input.evidence.coverage.gap_ids.clone(),
        protection: match input.evidence.protection_domain {
            ProtectionDomain::PublicProtocol | ProtectionDomain::PublicProduct => {
                FactProtection::PublicIntegrity
            }
            ProtectionDomain::AuthenticatedPrivateSocial => FactProtection::AuthenticatedPrivate,
            ProtectionDomain::OperatorPrivate => FactProtection::OperatorPrivate,
            ProtectionDomain::DerivedRestricted => FactProtection::DerivedRestricted,
        },
    }
}

fn stable(value: &str) -> Result<StableString, AttentionAdapterError> {
    StableString::new(value)
        .map_err(|error| AttentionAdapterError::InvalidIdentity(error.to_string()))
}
