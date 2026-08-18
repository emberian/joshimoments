use crate::{
    BookError, PROBABILITY_SCALE_PPM, Result, SCHEMA_VERSION, SHADOW_ENSEMBLE_CONTRACT,
    ValidatedArtifact, canonical_bytes, digest_bytes,
    model::{
        ClaimDefinitionV1, ClaimOccurrenceV1, DurableOccurrenceCapability,
        DurableProofRequirementV1, DurableSubmissionCapability, DurableSupportCapability,
        EnsembleComponentV1, EpistemicAuthorityV1, EpistemicImplementationStatusV1,
        ForecastPayloadV1, ForecastSubmissionV1, OutcomeProbabilityV1, ShadowEnsembleEligibilityV1,
        ShadowEnsembleV1, SubmissionPhaseV1, SupportCalibrationSummaryV1, SupportMaturityV1,
    },
    validate::{artifact_ref, authority, exact_ref},
};
use joshi_domain::{StableString, UtcTimestamp, WireU64};
use std::collections::BTreeSet;

const AGGREGATION_CONTRACT: &str = "fixed_equal_weight_unique_primary_lineage/v1";

fn invalid<T>(message: impl Into<String>) -> Result<T> {
    Err(BookError::Invalid(message.into()))
}

fn reason(value: &str) -> StableString {
    StableString::new(value).expect("static eligibility reason is valid")
}

fn semantic_reasons(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    support: &ValidatedArtifact<SupportCalibrationSummaryV1>,
    submissions: &[&ValidatedArtifact<ForecastSubmissionV1>],
) -> Vec<StableString> {
    let mut reasons = Vec::new();
    let definition_ref = exact_ref(&definition.value().claim_definition_id, definition);
    let occurrence_ref = exact_ref(&occurrence.value().claim_occurrence_id, occurrence);
    if support.value().maturity != SupportMaturityV1::RepeatedProspectiveSupport
        || support.value().claim_definition != definition_ref
    {
        reasons.push(reason("missing_repeated_exact_definition_support"));
    }
    if support.value().windows.iter().any(|window| {
        window.embargo_through >= occurrence.value().occurrence_information_cutoff
            || window.score_memberships.iter().any(|membership| {
                membership.claim_occurrence == occurrence_ref
                    || membership.outcome_available_at
                        >= occurrence.value().occurrence_information_cutoff
            })
    }) {
        reasons.push(reason("support_uses_current_or_future_outcome"));
    }
    if submissions.len() < 2
        || submissions.len()
            < usize::try_from(
                occurrence
                    .value()
                    .sealed_forecast_journal
                    .required_first_round_count
                    .get(),
            )
            .unwrap_or(usize::MAX)
    {
        reasons.push(reason("insufficient_preregistered_first_round_components"));
    }
    let mut ids = BTreeSet::new();
    let mut lineages = BTreeSet::new();
    for submission in submissions {
        let value = submission.value();
        if value.claim_occurrence != occurrence_ref
            || !matches!(value.phase, SubmissionPhaseV1::FirstRound)
            || !matches!(value.payload, ForecastPayloadV1::Categorical { .. })
        {
            reasons.push(reason(
                "component_not_categorical_first_round_same_occurrence",
            ));
        }
        if !ids.insert(value.submission_id.clone()) {
            reasons.push(reason("duplicate_submission_component"));
        }
        if !lineages.insert(value.lineage.primary_lineage_group.clone()) {
            reasons.push(reason("duplicate_primary_lineage"));
        }
    }
    reasons.sort();
    reasons.dedup();
    reasons
}

/// Checks semantic compatibility while explicitly refusing to upgrade it into eligibility.
///
/// The successful semantic case returns the exact missing durable proofs, not an ensemble.
#[must_use]
pub fn assess_shadow_ensemble_semantics(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    support: &ValidatedArtifact<SupportCalibrationSummaryV1>,
    submissions: &[&ValidatedArtifact<ForecastSubmissionV1>],
) -> ShadowEnsembleEligibilityV1 {
    let reasons = semantic_reasons(definition, occurrence, support, submissions);
    if reasons.is_empty() {
        ShadowEnsembleEligibilityV1::BlockedMissingDurableProof {
            status: EpistemicImplementationStatusV1::ContractDraftFixtureValidated,
            required: vec![
                DurableProofRequirementV1::StoreCommittedOccurrence,
                DurableProofRequirementV1::StoreResolvedFrozenEvidence,
                DurableProofRequirementV1::StoreResolvedCapabilityClosure,
                DurableProofRequirementV1::SealedSubmissionNamespace,
                DurableProofRequirementV1::StoreDerivedVisibilityAndReveal,
                DurableProofRequirementV1::StoreDerivedSupportMembership,
            ],
        }
    } else {
        ShadowEnsembleEligibilityV1::SemanticallyIneligible { reasons }
    }
}

fn durable_ensemble_dependencies(
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    support: &ValidatedArtifact<SupportCalibrationSummaryV1>,
    support_capability: &DurableSupportCapability,
    submissions: &[&ValidatedArtifact<ForecastSubmissionV1>],
    submission_capabilities: &[&DurableSubmissionCapability],
) -> Result<()> {
    let occurrence_ref = exact_ref(&occurrence.value().claim_occurrence_id, occurrence);
    artifact_ref(
        occurrence_capability.commit_receipt(),
        "occurrenceCapability.commitReceipt",
    )?;
    artifact_ref(
        support_capability.derivation_receipt(),
        "supportCapability.derivationReceipt",
    )?;
    let frozen_input_digest = digest_bytes(&canonical_bytes(&occurrence.value().frozen_input)?)?;
    let capability_closure_digest =
        digest_bytes(&canonical_bytes(&occurrence.value().capability_closure)?)?;
    let latest_embargo = support
        .value()
        .windows
        .iter()
        .map(|window| window.embargo_through)
        .max()
        .ok_or_else(|| BookError::Invalid("repeated support has no evaluation window".into()))?;
    if occurrence_capability.occurrence() != &occurrence_ref
        || occurrence_capability.committed_at() != occurrence.value().occurrence_commit_at
        || occurrence_capability.frozen_input_manifest_digest() != &frozen_input_digest
        || occurrence_capability.capability_closure_digest() != &capability_closure_digest
        || support_capability.summary() != &exact_ref(&support.value().summary_id, support)
        || support_capability.latest_embargo_through() != latest_embargo
        || latest_embargo >= occurrence.value().occurrence_information_cutoff
        || submissions.len() != submission_capabilities.len()
    {
        return invalid("opaque durable capabilities do not bind ensemble dependencies");
    }
    let mut latest_commit = occurrence.value().occurrence_commit_at;
    let mut earliest_reveal: Option<UtcTimestamp> = None;
    let mut all_sealed_at: Option<UtcTimestamp> = None;
    for (submission, capability) in submissions.iter().zip(submission_capabilities) {
        artifact_ref(
            capability.commit_receipt(),
            "submissionCapability.commitReceipt",
        )?;
        if capability.submission() != &exact_ref(&submission.value().submission_id, submission)
            || capability.occurrence() != &occurrence_ref
            || capability.sealed_namespace_id()
                != &occurrence.value().sealed_forecast_journal.namespace_id
            || capability.committed_at() < submission.value().submission_production_time
            || capability.committed_at() > occurrence.value().issue_deadline
            || !capability.visible_submission_ids_before_commit().is_empty()
            || !capability.visible_ensemble_ids_before_commit().is_empty()
        {
            return invalid("opaque submission capability does not bind a timely component");
        }
        let Some(reveal) = capability.reveal_at() else {
            return invalid("all first-round components must have one durable reveal occurrence");
        };
        latest_commit = latest_commit.max(capability.committed_at());
        earliest_reveal = Some(earliest_reveal.map_or(reveal, |current| current.min(reveal)));
        let Some(sealed) = capability.all_first_round_sealed_at() else {
            return invalid("store did not resolve the all-components-sealed boundary");
        };
        if all_sealed_at.is_some_and(|prior| prior != sealed) {
            return invalid("component capabilities disagree on the sealed-set boundary");
        }
        all_sealed_at = Some(sealed);
    }
    if all_sealed_at.is_none_or(|sealed| {
        sealed < latest_commit
            || earliest_reveal.is_none_or(|reveal| {
                sealed > reveal
                    || reveal < occurrence.value().sealed_forecast_journal.reveal_not_before
            })
    }) {
        return invalid("all eligible components must be sealed before any durable reveal");
    }
    Ok(())
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
fn expected_ensemble(
    ensemble_id: StableString,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    support: &ValidatedArtifact<SupportCalibrationSummaryV1>,
    support_capability: &DurableSupportCapability,
    submissions: &[&ValidatedArtifact<ForecastSubmissionV1>],
    submission_capabilities: &[&DurableSubmissionCapability],
) -> Result<ShadowEnsembleV1> {
    if let ShadowEnsembleEligibilityV1::SemanticallyIneligible { reasons } =
        assess_shadow_ensemble_semantics(definition, occurrence, support, submissions)
    {
        return invalid(format!(
            "shadow ensemble is semantically ineligible: {reasons:?}"
        ));
    }
    durable_ensemble_dependencies(
        occurrence,
        occurrence_capability,
        support,
        support_capability,
        submissions,
        submission_capabilities,
    )?;
    let mut ordered = submissions.to_vec();
    ordered.sort_by(|left, right| left.value().submission_id.cmp(&right.value().submission_id));
    let mut totals = vec![0_u128; definition.value().outcome_space.len()];
    for submission in &ordered {
        let ForecastPayloadV1::Categorical { probabilities } = &submission.value().payload else {
            return invalid("semantic preflight admitted a noncategorical member");
        };
        for (total, probability) in totals.iter_mut().zip(probabilities) {
            *total = total
                .checked_add(u128::from(probability.probability_ppm.get()))
                .ok_or_else(|| BookError::Invalid("ensemble probability overflow".into()))?;
        }
    }
    let member_count = u64::try_from(ordered.len())
        .map_err(|_| BookError::Invalid("ensemble member count does not fit u64".into()))?;
    let denominator = u128::from(member_count);
    let mut averaged: Vec<u64> = totals
        .iter()
        .map(|total| {
            u64::try_from(total / denominator)
                .map_err(|_| BookError::Invalid("ensemble mean does not fit ppm".into()))
        })
        .collect::<Result<_>>()?;
    let floor_sum: u64 = averaged.iter().sum();
    let remainder = PROBABILITY_SCALE_PPM
        .checked_sub(floor_sum)
        .ok_or_else(|| BookError::Invalid("ensemble mean exceeds probability scale".into()))?;
    for value in averaged.iter_mut().take(
        usize::try_from(remainder)
            .map_err(|_| BookError::Invalid("rounding remainder does not fit usize".into()))?,
    ) {
        *value += 1;
    }
    let output = definition
        .value()
        .outcome_space
        .iter()
        .zip(averaged)
        .map(|(outcome, probability_ppm)| OutcomeProbabilityV1 {
            outcome_id: outcome.outcome_id.clone(),
            probability_ppm: WireU64::new(probability_ppm),
        })
        .collect();
    let components = ordered
        .iter()
        .map(|submission| EnsembleComponentV1 {
            submission: exact_ref(&submission.value().submission_id, submission),
            primary_lineage_group: submission.value().lineage.primary_lineage_group.clone(),
            weight_numerator: WireU64::new(1),
            weight_denominator: WireU64::new(member_count),
        })
        .collect();
    Ok(ShadowEnsembleV1 {
        contract: StableString::new(SHADOW_ENSEMBLE_CONTRACT)?,
        schema_version: WireU64::new(SCHEMA_VERSION),
        ensemble_id,
        claim_occurrence: exact_ref(&occurrence.value().claim_occurrence_id, occurrence),
        support_summary: exact_ref(&support.value().summary_id, support),
        aggregation_contract: StableString::new(AGGREGATION_CONTRACT)?,
        components,
        effective_lineage_count: WireU64::new(member_count),
        output,
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    })
}

/// Builds a shadow ensemble only when private store-minted capabilities are present.
///
/// # Errors
///
/// Refuses semantic, historical-support, sealing, reveal, or exact-reference failure.
#[allow(clippy::too_many_arguments)]
pub fn evaluate_shadow_ensemble(
    ensemble_id: StableString,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    support: &ValidatedArtifact<SupportCalibrationSummaryV1>,
    support_capability: &DurableSupportCapability,
    submissions: &[&ValidatedArtifact<ForecastSubmissionV1>],
    submission_capabilities: &[&DurableSubmissionCapability],
) -> Result<ValidatedArtifact<ShadowEnsembleV1>> {
    let value = expected_ensemble(
        ensemble_id,
        definition,
        occurrence,
        occurrence_capability,
        support,
        support_capability,
        submissions,
        submission_capabilities,
    )?;
    let bytes = canonical_bytes(&value)?;
    ValidatedArtifact::new(value, bytes)
}

/// Recomputes a supplied ensemble with the same opaque capabilities required to create it.
///
/// # Errors
///
/// Refuses any supplied field that differs from deterministic recomputation.
#[allow(clippy::too_many_arguments)]
pub fn validate_ensemble_artifact(
    value: ShadowEnsembleV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    support: &ValidatedArtifact<SupportCalibrationSummaryV1>,
    support_capability: &DurableSupportCapability,
    submissions: &[&ValidatedArtifact<ForecastSubmissionV1>],
    submission_capabilities: &[&DurableSubmissionCapability],
) -> Result<ValidatedArtifact<ShadowEnsembleV1>> {
    authority(value.authority)?;
    let expected = expected_ensemble(
        value.ensemble_id.clone(),
        definition,
        occurrence,
        occurrence_capability,
        support,
        support_capability,
        submissions,
        submission_capabilities,
    )?;
    if value != expected {
        return invalid("shadow ensemble differs from exact deterministic recomputation");
    }
    let bytes = canonical_bytes(&value)?;
    ValidatedArtifact::new(value, bytes)
}
