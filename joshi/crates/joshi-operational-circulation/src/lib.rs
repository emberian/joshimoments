//! Read-only proof audit for the Wave 4 operational circulation path.
//!
//! The adapter consumes exact persisted bytes and post-commit public receipts. It cannot open a
//! store, acquire from a provider, choose a subject, grant economic authority, or promote an opaque
//! pre-commit capability into durable truth.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;

use joshi_acquisition_policy::{CensusDenominatorRef, CensusKind, EvidenceKind, EvidenceLink};
use joshi_admission::{
    Sha256Digest,
    operational::{
        AUTHORITY, OperationalStatus, ProjectionPublicationReceiptV1, SourceFactArtifactReceiptV1,
        SpoolCatalogReceiptV1, parse_receipt,
    },
    strict_json,
};
use joshi_attention::{AssertionStatus, EventTimeStatus, SelectedClusterContext};
use joshi_domain::{CommitSeq, StableString};
use joshi_evidence::DurableIngestBatch;
use joshi_market_state::{
    AttentionFact, MARKET_STATE_SNAPSHOT_CONTRACT, MarketStateSnapshotV1, READ_ONLY_AUTHORITY,
};
use joshi_projection::{EffectiveAssertionRef, ProjectionArtifactV1, projection_bytes};
use joshi_publication::{
    ProjectionPublicationReceiptV1 as SemanticProjectionReceipt, ProjectionPublicationV1,
    projection_publication_bytes,
};
use joshi_store::{ProjectionPublicationCapability, SourceFactArtifactCapability, SqliteStore};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use sha2::{Digest as _, Sha256};
use thiserror::Error;

/// Stable report wire contract.
pub const CIRCULATION_REPORT_CONTRACT: &str = "joshi.operational_circulation.report.v1";
/// Exact census denominator artifact contract expected by this adapter.
pub const CENSUS_ARTIFACT_CONTRACT: &str =
    "joshi.source_fact_artifact.acquisition_policy.census_denominator.v1";
/// Exact census input-closure contract expected by this adapter.
pub const CENSUS_INPUT_CLOSURE_CONTRACT: &str =
    "joshi.operational_circulation.census_input_closure.v1";
/// Capability ceiling for every report.
pub const READ_ONLY_NO_EXECUTION: &str = "read_only_no_execution";
const MAX_INPUT_BYTES: usize = 16 * 1024 * 1024;

/// Exact byte strings and optional opaque pre-commit capabilities presented to the audit.
#[derive(Clone, Copy)]
pub struct CirculationInputs<'a> {
    pub source_segment_bytes: &'a [u8],
    pub source_batch_bytes: &'a [u8],
    pub source_policy_bytes: &'a [u8],
    pub source_receipt_bytes: &'a [u8],
    pub census_artifact_bytes: &'a [u8],
    pub census_receipt_bytes: &'a [u8],
    pub selected_cluster_context_bytes: &'a [u8],
    pub market_state_artifact_bytes: &'a [u8],
    pub market_state_receipt_bytes: &'a [u8],
    pub projection_artifact_bytes: &'a [u8],
    pub projection_publication_bytes: &'a [u8],
    pub projection_receipt_bytes: &'a [u8],
    pub census_capability: Option<&'a SourceFactArtifactCapability>,
    pub market_state_capability: Option<&'a SourceFactArtifactCapability>,
    pub publication_capability: Option<&'a ProjectionPublicationCapability>,
}

/// Deterministic census closure whose digest is committed beside the denominator artifact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CensusInputClosureV1 {
    pub contract: StableString,
    pub census_id: StableString,
    pub as_of: joshi_acquisition_policy::AsOfCutoff,
    pub evidence: Vec<EvidenceLink>,
    pub coverage_evidence: Vec<EvidenceLink>,
}

impl CensusInputClosureV1 {
    /// Constructs the exact closure material from a denominator.
    #[must_use]
    pub fn from_denominator(value: &CensusDenominatorRef) -> Self {
        Self {
            contract: stable(CENSUS_INPUT_CLOSURE_CONTRACT),
            census_id: value.census_id.clone(),
            as_of: value.as_of.clone(),
            evidence: value.evidence.clone(),
            coverage_evidence: value.coverage_evidence.clone(),
        }
    }

    /// Returns the schema-ordered compact bytes committed by the source/fact receipt.
    ///
    /// # Errors
    ///
    /// Returns an error only if JSON serialization fails.
    pub fn exact_bytes(&self) -> Result<Vec<u8>, CirculationError> {
        serde_json::to_vec(self).map_err(|error| {
            invalid(
                CirculationErrorCode::CensusReceiptClosure,
                format!("census input closure serialization failed: {error}"),
            )
        })
    }
}

/// Stable, machine-actionable reason an otherwise valid prefix is not a circulation witness.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CirculationBlockerCode {
    CensusMembershipArtifactNotSemanticallyInspectable,
    ProjectionMarketStateArtifactUnreferenced,
    PublicationExactBytesUnbound,
    CapabilityNotSemanticallyInspectable,
}

/// One explicit proof limitation. Missing information is never converted to zero or absence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CirculationBlockerV1 {
    pub code: CirculationBlockerCode,
    pub stage: StableString,
    pub detail: StableString,
}

/// Distinct digest domains retained by the audit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DigestDomainsV1 {
    pub source_segment_exact: Sha256Digest,
    pub source_batch_exact: Sha256Digest,
    pub source_batch_logical: Sha256Digest,
    pub source_store_admission: Sha256Digest,
    pub source_receipt_exact: Sha256Digest,
    pub census_artifact_exact: Sha256Digest,
    pub census_input_closure: Sha256Digest,
    pub census_receipt_exact: Sha256Digest,
    pub selected_cluster_context_exact: Sha256Digest,
    pub market_state_artifact_exact: Sha256Digest,
    pub market_state_input_closure: Sha256Digest,
    pub market_state_receipt_exact: Sha256Digest,
    pub projection_artifact_exact: Sha256Digest,
    pub projection_result_semantic: Sha256Digest,
    pub projection_input_closure: Sha256Digest,
    pub publication_semantic: Sha256Digest,
    pub publication_exact: Sha256Digest,
    pub publication_receipt_exact: Sha256Digest,
}

/// Exact catalog and cutoff chain verified before reporting open joins.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct VerifiedPrefixV1 {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub source_commit: CommitSeq,
    pub census_known_through: CommitSeq,
    pub census_commit: CommitSeq,
    pub selected_cluster_context_id: StableString,
    pub market_state_artifact_id: StableString,
    pub market_state_known_through: CommitSeq,
    pub market_state_commit: CommitSeq,
    pub projection_id: StableString,
    pub projection_through: CommitSeq,
    pub publication_id: StableString,
    pub publication_commit: CommitSeq,
    pub digests: DigestDomainsV1,
}

/// A witness is reserved for a future receipt version that closes every currently named blocker.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CirculationWitnessV1 {
    pub contract: StableString,
    pub authority: StableString,
    pub verified: VerifiedPrefixV1,
}

/// Current audit outcome. V1 deliberately emits `blocked` for the open durable joins.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum CirculationOutcomeV1 {
    Witnessed {
        witness: CirculationWitnessV1,
    },
    Blocked {
        contract: StableString,
        authority: StableString,
        verified: VerifiedPrefixV1,
        blockers: Vec<CirculationBlockerV1>,
    },
}

/// Strict refusal categories for malformed, substituted, future-known, or unclosed inputs.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CirculationErrorCode {
    StrictJson,
    NonCanonicalBytes,
    SourceReceiptClosure,
    SourceBatchLogicalDigest,
    SourceCatalogClosure,
    CensusReceiptClosure,
    CensusEvidenceClosure,
    CatalogMismatch,
    CutoffRegression,
    ClusterContextClosure,
    MarketStateClosure,
    ProjectionClosure,
    PublicationClosure,
}

/// One deterministic refusal. It contains no provider data or credential material.
#[derive(Clone, Debug, Eq, Error, PartialEq, Serialize, Deserialize)]
#[error("{code:?}: {detail}")]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CirculationError {
    pub code: CirculationErrorCode,
    pub detail: String,
}

/// Audits an exact operational path without performing I/O or constructing authority.
///
/// # Errors
///
/// Returns a typed refusal for malformed bytes, digest substitution, invalid point-in-time joins,
/// catalog mismatch, or cutoff regression. Valid but presently unprovable joins are returned as
/// explicit blockers inside [`CirculationOutcomeV1::Blocked`].
#[allow(clippy::too_many_lines)]
pub fn audit_circulation(
    inputs: CirculationInputs<'_>,
) -> Result<CirculationOutcomeV1, CirculationError> {
    let source_receipt: SpoolCatalogReceiptV1 = parse_receipt(inputs.source_receipt_bytes)
        .map_err(|error| {
            invalid(
                CirculationErrorCode::SourceReceiptClosure,
                error.to_string(),
            )
        })?;
    source_receipt
        .exact_segment
        .verify(inputs.source_segment_bytes)
        .map_err(|error| {
            invalid(
                CirculationErrorCode::SourceReceiptClosure,
                error.to_string(),
            )
        })?;
    source_receipt
        .batch
        .exact_batch
        .verify(inputs.source_batch_bytes)
        .map_err(|error| {
            invalid(
                CirculationErrorCode::SourceReceiptClosure,
                error.to_string(),
            )
        })?;
    source_receipt
        .batch
        .exact_policy
        .verify(inputs.source_policy_bytes)
        .map_err(|error| {
            invalid(
                CirculationErrorCode::SourceReceiptClosure,
                error.to_string(),
            )
        })?;
    let source_batch: DurableIngestBatch = parse_strict(inputs.source_batch_bytes)?;
    let logical = SqliteStore::canonical_batch_digest(&source_batch).map_err(|error| {
        invalid(
            CirculationErrorCode::SourceBatchLogicalDigest,
            error.to_string(),
        )
    })?;
    if logical.as_str() != source_batch.expected_digest.as_str()
        || logical.as_str() != source_receipt.batch.logical_batch_digest.as_str()
    {
        return Err(invalid(
            CirculationErrorCode::SourceBatchLogicalDigest,
            "source exact-byte and logical digest domains do not close",
        ));
    }
    validate_public_source_receipt(&source_receipt, &source_batch)?;

    let census: CensusDenominatorRef = parse_canonical(inputs.census_artifact_bytes)?;
    validate_denominator(&census, &source_batch, &source_receipt)?;
    let census_receipt: SourceFactArtifactReceiptV1 = parse_receipt(inputs.census_receipt_bytes)
        .map_err(|error| {
            invalid(
                CirculationErrorCode::CensusReceiptClosure,
                error.to_string(),
            )
        })?;
    let census_closure = CensusInputClosureV1::from_denominator(&census).exact_bytes()?;
    validate_source_fact_receipt(
        &census_receipt,
        census.eligible_membership_artifact_id.as_str(),
        "acquisition_policy",
        CENSUS_ARTIFACT_CONTRACT,
        inputs.census_artifact_bytes,
        &census_closure,
        census.as_of.commit_through.map(joshi_domain::WireU64::get),
    )?;

    let cluster: SelectedClusterContext = parse_canonical(inputs.selected_cluster_context_bytes)?;
    let market: MarketStateSnapshotV1 = parse_canonical(inputs.market_state_artifact_bytes)?;
    let market_closure = serde_json::to_vec(&market.input_closure)
        .map_err(|error| invalid(CirculationErrorCode::MarketStateClosure, error.to_string()))?;
    let market_receipt: SourceFactArtifactReceiptV1 =
        parse_receipt(inputs.market_state_receipt_bytes).map_err(|error| {
            invalid(CirculationErrorCode::MarketStateClosure, error.to_string())
        })?;
    validate_source_fact_receipt(
        &market_receipt,
        market.artifact_id.as_str(),
        "market_state",
        MARKET_STATE_SNAPSHOT_CONTRACT,
        inputs.market_state_artifact_bytes,
        &market_closure,
        Some(market.cut.known_by_commit.get()),
    )?;
    validate_cluster_and_market(&cluster, &market)?;
    validate_market_source_links(&census, &market, &source_batch)?;

    let projection: ProjectionArtifactV1 = parse_canonical(inputs.projection_artifact_bytes)?;
    projection
        .validate()
        .map_err(|error| invalid(CirculationErrorCode::ProjectionClosure, error.to_string()))?;
    let canonical_projection = projection_bytes(&projection)
        .map_err(|error| invalid(CirculationErrorCode::ProjectionClosure, error.to_string()))?;
    if canonical_projection != inputs.projection_artifact_bytes {
        return Err(invalid(
            CirculationErrorCode::NonCanonicalBytes,
            "projection artifact bytes are not the canonical stored bytes",
        ));
    }
    validate_projection_contains_market_inputs(&projection, &market)?;

    let publication: ProjectionPublicationV1 =
        parse_canonical(inputs.projection_publication_bytes)?;
    publication
        .validate()
        .map_err(|error| invalid(CirculationErrorCode::PublicationClosure, error.to_string()))?;
    if projection_publication_bytes(&publication)
        .map_err(|error| invalid(CirculationErrorCode::PublicationClosure, error.to_string()))?
        != inputs.projection_publication_bytes
    {
        return Err(invalid(
            CirculationErrorCode::NonCanonicalBytes,
            "projection publication bytes are not canonical",
        ));
    }
    validate_publication_artifact(&publication, &projection, inputs.projection_artifact_bytes)?;
    let semantic_receipt: SemanticProjectionReceipt =
        strict_json::parse(inputs.projection_receipt_bytes, MAX_INPUT_BYTES).map_err(|error| {
            invalid(CirculationErrorCode::PublicationClosure, error.to_string())
        })?;
    semantic_receipt
        .validate_against(&publication)
        .map_err(|error| invalid(CirculationErrorCode::PublicationClosure, error.to_string()))?;
    let public_receipt: ProjectionPublicationReceiptV1 =
        parse_receipt(inputs.projection_receipt_bytes).map_err(|error| {
            invalid(CirculationErrorCode::PublicationClosure, error.to_string())
        })?;
    validate_publication_receipt_equivalence(&public_receipt, &publication)?;

    let catalog_id = try_stable(
        &source_receipt.catalog_receipt.catalog_id,
        CirculationErrorCode::SourceCatalogClosure,
    )?;
    let catalog_schema = try_stable(
        &source_receipt.catalog_receipt.catalog_schema,
        CirculationErrorCode::SourceCatalogClosure,
    )?;
    for (id, schema) in [
        (&census_receipt.catalog_id, &census_receipt.catalog_schema),
        (&market_receipt.catalog_id, &market_receipt.catalog_schema),
        (&public_receipt.catalog_id, &public_receipt.catalog_schema),
    ] {
        if id != catalog_id.as_str() || schema != catalog_schema.as_str() {
            return Err(invalid(
                CirculationErrorCode::CatalogMismatch,
                "source, source/fact, and publication receipts name different catalogs",
            ));
        }
    }

    let source_commit = commit(&source_receipt.catalog_receipt.commit_seq)?;
    let census_known = commit(&census_receipt.known_through_commit_seq)?;
    let census_commit = commit(&census_receipt.commit_seq)?;
    let market_known = commit(&market_receipt.known_through_commit_seq)?;
    let market_commit = commit(&market_receipt.commit_seq)?;
    let projection_through = projection.input.through_commit_seq;
    let publication_commit = publication.publication_commit_seq;
    if source_commit > census_known
        || census_known >= census_commit
        || census_commit > market_known
        || market_known >= market_commit
        || market_commit > projection_through
        || projection_through >= publication_commit
    {
        return Err(invalid(
            CirculationErrorCode::CutoffRegression,
            "commit cutoffs do not advance source→census→market→projection→publication",
        ));
    }
    let maximum_market_available = market
        .input_closure
        .iter()
        .map(|value| value.available_at)
        .max()
        .ok_or_else(|| {
            invalid(
                CirculationErrorCode::MarketStateClosure,
                "market-state input closure is empty",
            )
        })?;
    if maximum_market_available > market.cut.known_by
        || census.as_of.available_through > market.cut.known_by
    {
        return Err(invalid(
            CirculationErrorCode::CutoffRegression,
            "availableAt knowledge regresses across census and market-state cuts",
        ));
    }

    let mut blockers = vec![
        blocker(
            CirculationBlockerCode::CensusMembershipArtifactNotSemanticallyInspectable,
            "census",
            "CensusDenominatorRef names an eligible-membership artifact but exposes no exact member rows; the selected market subject cannot be proven to be in the denominator",
        ),
        blocker(
            CirculationBlockerCode::ProjectionMarketStateArtifactUnreferenced,
            "projection",
            "the projection closes the market-state inputs and cutoff but does not name the exact market-state artifact id/digest/receipt",
        ),
        blocker(
            CirculationBlockerCode::PublicationExactBytesUnbound,
            "publication",
            "the frozen public receipt echoes publication semantic digest but not exact publication-byte digest and length",
        ),
    ];
    if inputs.census_capability.is_some()
        || inputs.market_state_capability.is_some()
        || inputs.publication_capability.is_some()
    {
        blockers.push(blocker(
            CirculationBlockerCode::CapabilityNotSemanticallyInspectable,
            "durability",
            "opaque pre-commit capability getters cannot substitute for semantic post-commit readback",
        ));
    }
    blockers.sort_by_key(|value| value.code);

    let verified = VerifiedPrefixV1 {
        catalog_id,
        catalog_schema,
        source_commit,
        census_known_through: census_known,
        census_commit,
        selected_cluster_context_id: stable(cluster.cluster_context_id.as_str()),
        market_state_artifact_id: market.artifact_id.clone(),
        market_state_known_through: market_known,
        market_state_commit: market_commit,
        projection_id: projection.projection_id.clone(),
        projection_through,
        publication_id: stable(publication.publication_id.as_str()),
        publication_commit,
        digests: DigestDomainsV1 {
            source_segment_exact: Sha256Digest::of_bytes(inputs.source_segment_bytes),
            source_batch_exact: Sha256Digest::of_bytes(inputs.source_batch_bytes),
            source_batch_logical: parse_sha(logical.as_str())?,
            source_store_admission: source_receipt.batch.store_admission_digest.clone(),
            source_receipt_exact: Sha256Digest::of_bytes(inputs.source_receipt_bytes),
            census_artifact_exact: Sha256Digest::of_bytes(inputs.census_artifact_bytes),
            census_input_closure: Sha256Digest::of_bytes(&census_closure),
            census_receipt_exact: Sha256Digest::of_bytes(inputs.census_receipt_bytes),
            selected_cluster_context_exact: Sha256Digest::of_bytes(
                inputs.selected_cluster_context_bytes,
            ),
            market_state_artifact_exact: Sha256Digest::of_bytes(inputs.market_state_artifact_bytes),
            market_state_input_closure: Sha256Digest::of_bytes(&market_closure),
            market_state_receipt_exact: Sha256Digest::of_bytes(inputs.market_state_receipt_bytes),
            projection_artifact_exact: Sha256Digest::of_bytes(inputs.projection_artifact_bytes),
            projection_result_semantic: parse_sha(projection.result_digest.as_str())?,
            projection_input_closure: Sha256Digest::of_bytes(
                &serde_json::to_vec(&projection.input).map_err(|error| {
                    invalid(CirculationErrorCode::ProjectionClosure, error.to_string())
                })?,
            ),
            publication_semantic: parse_sha(publication.publication_digest.as_str())?,
            publication_exact: Sha256Digest::of_bytes(inputs.projection_publication_bytes),
            publication_receipt_exact: Sha256Digest::of_bytes(inputs.projection_receipt_bytes),
        },
    };
    Ok(CirculationOutcomeV1::Blocked {
        contract: stable(CIRCULATION_REPORT_CONTRACT),
        authority: stable(READ_ONLY_NO_EXECUTION),
        verified,
        blockers,
    })
}

fn parse_strict<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, CirculationError> {
    strict_json::parse(bytes, MAX_INPUT_BYTES)
        .map_err(|error| invalid(CirculationErrorCode::StrictJson, error.to_string()))
}

fn parse_canonical<T: DeserializeOwned + Serialize>(bytes: &[u8]) -> Result<T, CirculationError> {
    let value: T = parse_strict(bytes)?;
    let canonical = serde_json::to_vec(&value)
        .map_err(|error| invalid(CirculationErrorCode::StrictJson, error.to_string()))?;
    if canonical != bytes {
        return Err(invalid(
            CirculationErrorCode::NonCanonicalBytes,
            "exact semantic artifact is not schema-ordered compact JSON",
        ));
    }
    Ok(value)
}

fn validate_public_source_receipt(
    receipt: &SpoolCatalogReceiptV1,
    batch: &DurableIngestBatch,
) -> Result<(), CirculationError> {
    let public = &receipt.catalog_receipt;
    if public.contract != "joshi.store.ingest_receipt"
        || public.schema_version != 1
        || public.batch_id != batch.batch_id.as_str()
        || StableString::new(public.catalog_id.clone()).is_err()
        || StableString::new(public.catalog_schema.clone()).is_err()
        || matches!(receipt.status, OperationalStatus::Accepted)
            != matches!(public.status, joshi_admission::PublicStatus::Accepted)
    {
        return Err(invalid(
            CirculationErrorCode::SourceCatalogClosure,
            "public store receipt header or batch identity differs",
        ));
    }
    let acquisition_ids = batch
        .observations
        .iter()
        .map(|value| value.acquisition.acquisition_id.as_str().to_owned())
        .collect::<BTreeSet<_>>();
    if public
        .acquisition_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        != acquisition_ids
        || public
            .acquisition_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
    {
        return Err(invalid(
            CirculationErrorCode::SourceCatalogClosure,
            "public store receipt does not close exact acquisition occurrences",
        ));
    }
    let gap_ids = batch
        .coverage_gaps
        .iter()
        .map(|value| value.gap_id.as_str().to_owned())
        .collect::<BTreeSet<_>>();
    if public
        .gap_outcomes
        .iter()
        .map(|value| value.gap_id.clone())
        .collect::<BTreeSet<_>>()
        != gap_ids
        || public
            .gap_outcomes
            .windows(2)
            .any(|pair| pair[0].gap_id >= pair[1].gap_id)
    {
        return Err(invalid(
            CirculationErrorCode::SourceCatalogClosure,
            "public store receipt does not close exact scoped gaps",
        ));
    }
    validate_public_admitted_counts(public, batch, acquisition_ids.len())
}

fn validate_public_admitted_counts(
    public: &joshi_admission::PublicStoreReceiptV1,
    batch: &DurableIngestBatch,
    acquisition_count: usize,
) -> Result<(), CirculationError> {
    let raw_bytes = batch
        .observations
        .iter()
        .try_fold(0_u64, |total, value| {
            total.checked_add(u64::try_from(value.payload.len()).ok()?)
        })
        .ok_or_else(|| {
            invalid(
                CirculationErrorCode::SourceCatalogClosure,
                "raw-byte count overflow",
            )
        })?;
    let raw_blobs = batch
        .observations
        .iter()
        .map(|value| Sha256::digest(&value.payload).to_vec())
        .collect::<BTreeSet<_>>()
        .len();
    let expected = [
        (&public.admitted.acquisitions, acquisition_count),
        (&public.admitted.raw_blobs, raw_blobs),
        (&public.admitted.observations, batch.observations.len()),
        (&public.admitted.source_events, batch.source_events.len()),
        (&public.admitted.assertions, batch.assertions.len()),
        (
            &public.admitted.coverage_windows,
            batch.coverage_windows.len(),
        ),
        (&public.admitted.coverage_gaps, batch.coverage_gaps.len()),
        (
            &public.admitted.coverage_recoveries,
            batch.coverage_recoveries.len(),
        ),
        (
            &public.admitted.cursor_advances,
            batch.cursor_advances.len(),
        ),
    ];
    if expected
        .iter()
        .any(|(wire, count)| parse_u64(wire).ok() != u64::try_from(*count).ok())
        || parse_u64(&public.admitted.raw_bytes).ok() != Some(raw_bytes)
    {
        return Err(invalid(
            CirculationErrorCode::SourceCatalogClosure,
            "public admitted counts differ from exact batch closure",
        ));
    }
    Ok(())
}

fn validate_denominator(
    value: &CensusDenominatorRef,
    batch: &DurableIngestBatch,
    source_receipt: &SpoolCatalogReceiptV1,
) -> Result<(), CirculationError> {
    let Some(commit_cut) = value.as_of.commit_through else {
        return Err(invalid(
            CirculationErrorCode::CensusEvidenceClosure,
            "census denominator has no bounded commit cutoff",
        ));
    };
    if value.eligible_subject_count.get() == 0
        || parse_sha(value.eligible_universe_digest.as_str()).is_err()
    {
        return Err(invalid(
            CirculationErrorCode::CensusEvidenceClosure,
            "census denominator requires a nonempty eligible universe and SHA-256 digest",
        ));
    }
    if value.evidence.is_empty()
        || value.coverage_evidence.is_empty()
        || value.evidence.windows(2).any(|pair| pair[0] >= pair[1])
        || value
            .coverage_evidence
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || value
            .coverage_evidence
            .iter()
            .any(|link| link.kind != EvidenceKind::Coverage)
    {
        return Err(invalid(
            CirculationErrorCode::CensusEvidenceClosure,
            "census evidence and coverage must be nonempty, typed, and sorted",
        ));
    }
    if (value.kind == CensusKind::ProductBoardParityPassed && value.parity_receipt_id.is_none())
        || (value.kind == CensusKind::IndependentChainProvider && value.parity_receipt_id.is_some())
    {
        return Err(invalid(
            CirculationErrorCode::CensusEvidenceClosure,
            "census kind and parity receipt disagree",
        ));
    }
    let source_commit = parse_u64(&source_receipt.catalog_receipt.commit_seq)?;
    if commit_cut.get() < source_commit {
        return Err(invalid(
            CirculationErrorCode::CutoffRegression,
            "census cutoff predates its durable source receipt",
        ));
    }
    for link in value.evidence.iter().chain(&value.coverage_evidence) {
        if link.available_at > value.as_of.available_through
            || link.commit_seq.is_none_or(|commit| commit > commit_cut)
            || link
                .digest
                .as_ref()
                .is_some_and(|digest| parse_sha(digest.as_str()).is_err())
            || !link_resolves(link, batch)
        {
            return Err(invalid(
                CirculationErrorCode::CensusEvidenceClosure,
                "census evidence is absent from the exact source batch or future-known",
            ));
        }
    }
    Ok(())
}

fn link_resolves(link: &EvidenceLink, batch: &DurableIngestBatch) -> bool {
    match link.kind {
        EvidenceKind::Observation => batch
            .observations
            .iter()
            .any(|value| value.observation.observation_id.as_str() == link.id.as_str()),
        EvidenceKind::Assertion => batch
            .assertions
            .iter()
            .any(|value| value.assertion_id.as_str() == link.id.as_str()),
        EvidenceKind::Coverage => {
            batch
                .coverage_windows
                .iter()
                .any(|value| value.coverage_id.as_str() == link.id.as_str())
                || batch
                    .coverage_gaps
                    .iter()
                    .any(|value| value.gap_id.as_str() == link.id.as_str())
        }
        _ => false,
    }
}

#[allow(clippy::too_many_arguments)]
fn validate_source_fact_receipt(
    receipt: &SourceFactArtifactReceiptV1,
    artifact_id: &str,
    family: &str,
    contract: &str,
    artifact_bytes: &[u8],
    input_closure_bytes: &[u8],
    expected_known: Option<u64>,
) -> Result<(), CirculationError> {
    let code = if family == "market_state" {
        CirculationErrorCode::MarketStateClosure
    } else {
        CirculationErrorCode::CensusReceiptClosure
    };
    if receipt.artifact_id != artifact_id
        || receipt.artifact_family != family
        || receipt.artifact_contract != contract
        || receipt.authority != AUTHORITY
        || receipt.artifact_digest != Sha256Digest::of_bytes(artifact_bytes)
        || receipt.input_closure_digest != Sha256Digest::of_bytes(input_closure_bytes)
        || expected_known.is_some_and(|expected| {
            parse_u64(&receipt.known_through_commit_seq).ok() != Some(expected)
        })
        || !matches!(
            receipt.status,
            OperationalStatus::Accepted | OperationalStatus::Idempotent
        )
    {
        return Err(invalid(
            code,
            "source/fact post-commit receipt does not close exact artifact and input bytes",
        ));
    }
    Ok(())
}

fn validate_cluster_and_market(
    cluster: &SelectedClusterContext,
    market: &MarketStateSnapshotV1,
) -> Result<(), CirculationError> {
    if market.contract.as_str() != MARKET_STATE_SNAPSHOT_CONTRACT
        || market.authority.as_str() != READ_ONLY_AUTHORITY
        || market.input_closure.is_empty()
        || market.input_closure.windows(2).any(|pair| {
            (&pair[0].semantic_key, &pair[0].assertion_id)
                >= (&pair[1].semantic_key, &pair[1].assertion_id)
        })
        || market.input_closure.iter().any(|input| {
            input.available_at > market.cut.known_by
                || input.available_commit > market.cut.known_by_commit
                || input.produced_commit > market.cut.known_by_commit
        })
    {
        return Err(invalid(
            CirculationErrorCode::MarketStateClosure,
            "market-state artifact violates contract, ordering, authority, or cut",
        ));
    }
    let nested = market
        .attention
        .iter()
        .filter_map(|selected| {
            (selected.value.selected_cluster.as_ref() == Some(cluster))
                .then_some((selected, &selected.value))
        })
        .collect::<Vec<_>>();
    let [(selected, attention)] = nested.as_slice() else {
        return Err(invalid(
            CirculationErrorCode::ClusterContextClosure,
            "selected cluster context must occur exactly once in the market attention branch",
        ));
    };
    validate_attention_cluster(cluster, attention)?;
    if !market
        .input_closure
        .iter()
        .any(|input| input == &selected.effective)
    {
        return Err(invalid(
            CirculationErrorCode::MarketStateClosure,
            "selected attention fact is absent from the market input closure",
        ));
    }
    Ok(())
}

fn validate_attention_cluster(
    cluster: &SelectedClusterContext,
    attention: &AttentionFact,
) -> Result<(), CirculationError> {
    let event = &attention.event;
    let Some(lower) = event.event_time.lower else {
        return Err(invalid(
            CirculationErrorCode::ClusterContextClosure,
            "cluster-bound event lacks a known event-time lower bound",
        ));
    };
    if !matches!(
        event.event_time.status,
        EventTimeStatus::Exact | EventTimeStatus::Bounded
    ) || cluster.source_status == AssertionStatus::Retracted
        || cluster.cluster_context_id.as_str()
            != event
                .caller_cluster_context_id
                .as_ref()
                .map_or("", |value| value.as_str())
        || cluster.selected_for_attention_event_id != event.attention_event_id
        || cluster.selected_for_event_time != event.event_time
        || cluster.selected_for_chain_slot != event.chain_slot
        || cluster.selected_as_of != event.available_at
        || cluster.selected_as_of_commit != event.available_commit
        || cluster.source_available_at > event.available_at
        || cluster.source_available_commit > event.available_commit
        || lower < cluster.valid_time.lower
        || cluster.valid_time.upper.is_some_and(|upper| lower >= upper)
        || cluster.member_wallet_ids.is_empty()
    {
        return Err(invalid(
            CirculationErrorCode::ClusterContextClosure,
            "cluster is not the exact valid and known context selected for this attention event",
        ));
    }
    let (Some(slots), Some(slot)) = (&cluster.valid_slots, event.chain_slot) else {
        return Err(invalid(
            CirculationErrorCode::ClusterContextClosure,
            "cluster selection requires exact event slot and half-open slot validity",
        ));
    };
    if slot < slots.lower || slots.upper.is_some_and(|upper| slot >= upper) {
        return Err(invalid(
            CirculationErrorCode::ClusterContextClosure,
            "cluster was not slot-valid at the attention event",
        ));
    }
    Ok(())
}

fn validate_market_source_links(
    census: &CensusDenominatorRef,
    market: &MarketStateSnapshotV1,
    source: &DurableIngestBatch,
) -> Result<(), CirculationError> {
    let source_observations = source
        .observations
        .iter()
        .map(|value| value.observation.observation_id.as_str())
        .collect::<BTreeSet<_>>();
    let source_coverage = source
        .coverage_windows
        .iter()
        .map(|value| value.coverage_id.as_str())
        .chain(
            source
                .coverage_gaps
                .iter()
                .map(|value| value.gap_id.as_str()),
        )
        .collect::<BTreeSet<_>>();
    let market_observations = market
        .input_closure
        .iter()
        .flat_map(|value| {
            value
                .evidence
                .observation_ids
                .iter()
                .map(joshi_domain::ObservationId::as_str)
        })
        .collect::<BTreeSet<_>>();
    let market_coverage = market
        .input_closure
        .iter()
        .flat_map(|value| {
            value
                .evidence
                .coverage_ids
                .iter()
                .chain(&value.evidence.gap_ids)
                .map(joshi_domain::CoverageId::as_str)
        })
        .collect::<BTreeSet<_>>();
    if !market_observations.is_subset(&source_observations)
        || !market_coverage.is_subset(&source_coverage)
    {
        return Err(invalid(
            CirculationErrorCode::MarketStateClosure,
            "market-state evidence is absent from the exact durable source batch",
        ));
    }
    for link in census.evidence.iter().chain(&census.coverage_evidence) {
        let retained = match link.kind {
            EvidenceKind::Observation => market_observations.contains(link.id.as_str()),
            EvidenceKind::Coverage => market_coverage.contains(link.id.as_str()),
            _ => false,
        };
        if !retained {
            return Err(invalid(
                CirculationErrorCode::CensusEvidenceClosure,
                "census evidence disappeared from the selected market-state branch",
            ));
        }
    }
    if market
        .attention
        .iter()
        .any(|selected| selected.value.event.mint_id.as_str() != market.subject_id.as_str())
    {
        return Err(invalid(
            CirculationErrorCode::MarketStateClosure,
            "market-state subject differs from its attention-event mint",
        ));
    }
    Ok(())
}

fn validate_projection_contains_market_inputs(
    projection: &ProjectionArtifactV1,
    market: &MarketStateSnapshotV1,
) -> Result<(), CirculationError> {
    for input in &market.input_closure {
        let projected = EffectiveAssertionRef {
            assertion_id: input.assertion_id.clone(),
            semantic_key: input.semantic_key.clone(),
            produced_commit_seq: input.produced_commit,
            value_digest: input.value_digest.clone(),
            supersedes_assertion_id: input.supersedes_assertion_id.clone(),
        };
        if projection
            .input
            .effective_assertions
            .binary_search_by(|candidate| {
                (&candidate.semantic_key, &candidate.assertion_id)
                    .cmp(&(&projected.semantic_key, &projected.assertion_id))
            })
            .ok()
            .and_then(|index| projection.input.effective_assertions.get(index))
            != Some(&projected)
        {
            return Err(invalid(
                CirculationErrorCode::ProjectionClosure,
                "projection does not retain an exact market-state effective input",
            ));
        }
    }
    let market_observations = market
        .input_closure
        .iter()
        .flat_map(|value| value.evidence.observation_ids.iter())
        .collect::<BTreeSet<_>>();
    if market_observations.iter().any(|id| {
        projection
            .input
            .observation_ids
            .binary_search_by(|candidate| candidate.as_str().cmp(id.as_str()))
            .is_err()
    }) {
        return Err(invalid(
            CirculationErrorCode::ProjectionClosure,
            "projection observation closure omits market-state evidence",
        ));
    }
    Ok(())
}

fn validate_publication_artifact(
    publication: &ProjectionPublicationV1,
    projection: &ProjectionArtifactV1,
    projection_bytes: &[u8],
) -> Result<(), CirculationError> {
    if publication.projection_id.as_str() != projection.projection_id.as_str()
        || publication.result_digest != projection.result_digest
        || publication.input != projection.input
        || publication.artifact_digest.as_str() != Sha256Digest::of_bytes(projection_bytes).as_str()
        || publication.artifact_bytes.get()
            != u64::try_from(projection_bytes.len()).unwrap_or(u64::MAX)
    {
        return Err(invalid(
            CirculationErrorCode::PublicationClosure,
            "publication does not close exact projection bytes and semantic input",
        ));
    }
    Ok(())
}

fn validate_publication_receipt_equivalence(
    receipt: &ProjectionPublicationReceiptV1,
    publication: &ProjectionPublicationV1,
) -> Result<(), CirculationError> {
    if receipt.catalog_id != publication.catalog_id.as_str()
        || receipt.catalog_schema != publication.catalog_schema.as_str()
        || receipt.batch_id != publication.batch_id.as_str()
        || receipt.publication_id != publication.publication_id.as_str()
        || receipt.projection_id != publication.projection_id.as_str()
        || receipt.result_digest.as_str() != publication.result_digest.as_str()
        || receipt.artifact_digest.as_str() != publication.artifact_digest.as_str()
        || receipt.input_closure_digest.as_str() != publication.input_closure_digest.as_str()
        || receipt.publication_digest.as_str() != publication.publication_digest.as_str()
        || receipt.through_commit_seq != publication.through_commit_seq.to_string()
        || receipt.commit_seq != publication.publication_commit_seq.to_string()
        || receipt.supersedes_publication_id.as_deref()
            != publication
                .supersedes_publication_id
                .as_ref()
                .map(joshi_publication::ProjectionPublicationId::as_str)
        || receipt.authority != READ_ONLY_NO_EXECUTION
    {
        return Err(invalid(
            CirculationErrorCode::PublicationClosure,
            "public operational receipt differs from semantic publication receipt",
        ));
    }
    Ok(())
}

fn blocker(code: CirculationBlockerCode, stage: &str, detail: &str) -> CirculationBlockerV1 {
    CirculationBlockerV1 {
        code,
        stage: stable(stage),
        detail: stable(detail),
    }
}

fn invalid(code: CirculationErrorCode, detail: impl Into<String>) -> CirculationError {
    CirculationError {
        code,
        detail: detail.into(),
    }
}

fn parse_u64(value: &str) -> Result<u64, CirculationError> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || !value.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(invalid(
            CirculationErrorCode::CutoffRegression,
            format!("non-canonical or out-of-range commit/count {value}"),
        ));
    }
    value.parse().map_err(|_| {
        invalid(
            CirculationErrorCode::CutoffRegression,
            format!("non-canonical or out-of-range commit/count {value}"),
        )
    })
}

fn commit(value: &str) -> Result<CommitSeq, CirculationError> {
    parse_u64(value).map(CommitSeq::new)
}

fn parse_sha(value: &str) -> Result<Sha256Digest, CirculationError> {
    Sha256Digest::parse(value)
        .map_err(|error| invalid(CirculationErrorCode::StrictJson, error.to_string()))
}

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap_or_else(|_| unreachable!("validated/static stable string"))
}

fn try_stable(value: &str, code: CirculationErrorCode) -> Result<StableString, CirculationError> {
    StableString::new(value).map_err(|error| invalid(code, error.to_string()))
}

#[cfg(test)]
mod tests;
