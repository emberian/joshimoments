use crate::{
    BookError, PROBABILITY_SCALE_PPM, Result, SCHEMA_VERSION, SCORE_ARTIFACT_CONTRACT,
    ValidatedArtifact, canonical_bytes, digest_bytes,
    model::{
        AdjudicationV1, BrierScorePreviewV1, ClaimDefinitionV1, ClaimOccurrenceV1,
        DurableAdjudicationCapability, DurableOccurrenceCapability, DurableSubmissionCapability,
        EpistemicAuthorityV1, EpistemicImplementationStatusV1, ExactLossV1, ForecastPayloadV1,
        ForecastSubmissionV1, IncrementSignV1, OutcomeProbabilityV1, ProperScoreArtifactV1,
        ProperScoreRuleV1, ScoreIncrementV1, ScoreOrientationV1, SubmissionPhaseV1,
    },
    validate::{artifact_ref, exact_ref, resolved_outcome, score_header, sha256},
};
use joshi_domain::{StableString, ValueDigest, WireU64, WireU128};

fn invalid<T>(message: impl Into<String>) -> Result<T> {
    Err(BookError::Invalid(message.into()))
}

fn categorical(value: &ForecastSubmissionV1) -> Result<&[OutcomeProbabilityV1]> {
    match &value.payload {
        ForecastPayloadV1::Categorical { probabilities } => Ok(probabilities),
        ForecastPayloadV1::Abstain { .. }
        | ForecastPayloadV1::Missing { .. }
        | ForecastPayloadV1::Unsupported { .. }
        | ForecastPayloadV1::Refused { .. }
        | ForecastPayloadV1::Qualitative { .. } => {
            invalid("only a categorical distribution may receive a Brier arithmetic preview")
        }
    }
}

fn brier_loss(probabilities: &[OutcomeProbabilityV1], outcome: &StableString) -> Result<u128> {
    probabilities.iter().try_fold(0_u128, |sum, probability| {
        let expected = if &probability.outcome_id == outcome {
            PROBABILITY_SCALE_PPM
        } else {
            0
        };
        let difference = probability.probability_ppm.get().abs_diff(expected);
        let square = u128::from(difference) * u128::from(difference);
        sum.checked_add(square)
            .ok_or_else(|| BookError::Invalid("Brier loss overflow".into()))
    })
}

fn exact_loss(numerator: u128) -> ExactLossV1 {
    ExactLossV1 {
        numerator: WireU128::new(numerator),
        denominator: WireU128::new(u128::from(PROBABILITY_SCALE_PPM).pow(2)),
    }
}

fn increment(candidate: u128, baseline: u128) -> ScoreIncrementV1 {
    let (sign, magnitude) = match baseline.cmp(&candidate) {
        std::cmp::Ordering::Greater => (IncrementSignV1::CandidateBetter, baseline - candidate),
        std::cmp::Ordering::Equal => (IncrementSignV1::Equal, 0),
        std::cmp::Ordering::Less => (IncrementSignV1::CandidateWorse, candidate - baseline),
    };
    ScoreIncrementV1 {
        sign,
        magnitude_numerator: WireU128::new(magnitude),
        denominator: WireU128::new(u128::from(PROBABILITY_SCALE_PPM).pow(2)),
    }
}

fn semantic_preview(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    baseline: Option<&ValidatedArtifact<ForecastSubmissionV1>>,
) -> Result<BrierScorePreviewV1> {
    if definition.value().scoring.rule != ProperScoreRuleV1::BrierCategorical {
        return invalid("the pure arithmetic preview implements only categorical Brier loss");
    }
    let occurrence_ref = exact_ref(&occurrence.value().claim_occurrence_id, occurrence);
    if occurrence.value().claim_definition
        != exact_ref(&definition.value().claim_definition_id, definition)
        || candidate.value().claim_occurrence != occurrence_ref
        || adjudication.value().claim_occurrence != occurrence_ref
        || baseline.is_some_and(|value| value.value().claim_occurrence != occurrence_ref)
    {
        return invalid(
            "definition, occurrence, forecast, baseline, and adjudication must bind exactly",
        );
    }
    let outcome = resolved_outcome(adjudication.value(), &definition.value().scoring)?;
    let candidate_loss = brier_loss(categorical(candidate.value())?, outcome)?;
    let (baseline_loss, baseline_increment) = if let Some(baseline) = baseline {
        let value = brier_loss(categorical(baseline.value())?, outcome)?;
        (
            Some(exact_loss(value)),
            Some(increment(candidate_loss, value)),
        )
    } else {
        (None, None)
    };
    Ok(BrierScorePreviewV1 {
        outcome_id: outcome.clone(),
        candidate_loss: exact_loss(candidate_loss),
        baseline_loss,
        baseline_increment,
        status: EpistemicImplementationStatusV1::ContractDraftFixtureValidated,
    })
}

/// Computes exact arithmetic without creating a score artifact or prospective maturity.
///
/// # Errors
///
/// Refuses cross-occurrence substitution, an inadmissible outcome, or noncategorical payloads.
pub fn preview_brier_score(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    baseline: Option<&ValidatedArtifact<ForecastSubmissionV1>>,
) -> Result<BrierScorePreviewV1> {
    semantic_preview(definition, occurrence, candidate, adjudication, baseline)
}

fn durable_dependencies(
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    candidate_capability: &DurableSubmissionCapability,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    adjudication_capability: &DurableAdjudicationCapability,
    baseline: Option<(
        &ValidatedArtifact<ForecastSubmissionV1>,
        &DurableSubmissionCapability,
    )>,
) -> Result<()> {
    let occurrence_ref = exact_ref(&occurrence.value().claim_occurrence_id, occurrence);
    let candidate_ref = exact_ref(&candidate.value().submission_id, candidate);
    let adjudication_ref = exact_ref(&adjudication.value().adjudication_id, adjudication);
    artifact_ref(
        occurrence_capability.commit_receipt(),
        "occurrenceCapability.commitReceipt",
    )?;
    artifact_ref(
        candidate_capability.commit_receipt(),
        "candidateCapability.commitReceipt",
    )?;
    artifact_ref(
        adjudication_capability.commit_receipt(),
        "adjudicationCapability.commitReceipt",
    )?;
    let frozen_input_digest = digest_bytes(&canonical_bytes(&occurrence.value().frozen_input)?)?;
    let capability_closure_digest =
        digest_bytes(&canonical_bytes(&occurrence.value().capability_closure)?)?;
    if occurrence_capability.occurrence() != &occurrence_ref
        || occurrence_capability.committed_at() != occurrence.value().occurrence_commit_at
        || occurrence_capability.frozen_input_manifest_digest() != &frozen_input_digest
        || occurrence_capability.capability_closure_digest() != &capability_closure_digest
        || candidate_capability.submission() != &candidate_ref
        || candidate_capability.occurrence() != &occurrence_ref
        || candidate_capability.sealed_namespace_id()
            != &occurrence.value().sealed_forecast_journal.namespace_id
        || candidate_capability.committed_at() < candidate.value().submission_production_time
        || candidate_capability.committed_at() > occurrence.value().issue_deadline
        || candidate_capability
            .reveal_at()
            .is_none_or(|at| at < occurrence.value().knowledge_deadline)
        || adjudication_capability.adjudication() != &adjudication_ref
        || adjudication_capability.occurrence() != &occurrence_ref
        || adjudication_capability.committed_at() < adjudication.value().adjudicated_at
    {
        return invalid("opaque durable capabilities do not bind the exact score dependencies");
    }
    durable_submission_visibility(candidate, candidate_capability)?;
    if let Some((baseline, capability)) = baseline {
        artifact_ref(
            capability.commit_receipt(),
            "baselineCapability.commitReceipt",
        )?;
        if capability.submission() != &exact_ref(&baseline.value().submission_id, baseline)
            || capability.occurrence() != &occurrence_ref
            || capability.sealed_namespace_id()
                != &occurrence.value().sealed_forecast_journal.namespace_id
            || capability.committed_at() < baseline.value().submission_production_time
            || capability.committed_at() > occurrence.value().issue_deadline
            || capability
                .reveal_at()
                .is_none_or(|at| at < occurrence.value().knowledge_deadline)
        {
            return invalid("opaque baseline capability does not bind the exact occurrence");
        }
        durable_submission_visibility(baseline, capability)?;
    }
    Ok(())
}

fn durable_submission_visibility(
    submission: &ValidatedArtifact<ForecastSubmissionV1>,
    capability: &DurableSubmissionCapability,
) -> Result<()> {
    match &submission.value().phase {
        SubmissionPhaseV1::FirstRound => {
            if !capability.visible_submission_ids_before_commit().is_empty()
                || !capability.visible_ensemble_ids_before_commit().is_empty()
                || capability.all_first_round_sealed_at().is_none_or(|sealed| {
                    capability.reveal_at().is_none_or(|reveal| sealed > reveal)
                })
            {
                return invalid("opaque first-round capability does not prove sealed blindness");
            }
        }
        SubmissionPhaseV1::Revision {
            visible_parent_submission_ids,
            visible_ensemble_ids,
            ..
        } => {
            if capability.visible_submission_ids_before_commit() != visible_parent_submission_ids
                || capability.visible_ensemble_ids_before_commit() != visible_ensemble_ids
            {
                return invalid("opaque revision capability differs from declared visibility");
            }
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn expected_score(
    score_id: StableString,
    calculation_build_digest: ValueDigest,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    candidate_capability: &DurableSubmissionCapability,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    adjudication_capability: &DurableAdjudicationCapability,
    baseline: Option<(
        &ValidatedArtifact<ForecastSubmissionV1>,
        &DurableSubmissionCapability,
    )>,
) -> Result<ProperScoreArtifactV1> {
    sha256(&calculation_build_digest, "calculationBuildDigest")?;
    durable_dependencies(
        occurrence,
        occurrence_capability,
        candidate,
        candidate_capability,
        adjudication,
        adjudication_capability,
        baseline,
    )?;
    let preview = semantic_preview(
        definition,
        occurrence,
        candidate,
        adjudication,
        baseline.map(|(value, _)| value),
    )?;
    Ok(ProperScoreArtifactV1 {
        contract: StableString::new(SCORE_ARTIFACT_CONTRACT)?,
        schema_version: WireU64::new(SCHEMA_VERSION),
        score_id,
        claim_occurrence: exact_ref(&occurrence.value().claim_occurrence_id, occurrence),
        submission: exact_ref(&candidate.value().submission_id, candidate),
        adjudication: exact_ref(&adjudication.value().adjudication_id, adjudication),
        baseline_submission: baseline
            .map(|(value, _)| exact_ref(&value.value().submission_id, value)),
        scoring_rule: ProperScoreRuleV1::BrierCategorical,
        outcome_id: preview.outcome_id,
        candidate_loss: preview.candidate_loss,
        baseline_loss: preview.baseline_loss,
        baseline_increment: preview.baseline_increment,
        orientation: ScoreOrientationV1::LowerLossBetter,
        calculation_build_digest,
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    })
}

/// Builds a score only from non-publicly-constructible durable store capabilities.
///
/// # Errors
///
/// Refuses missing exact bindings, timing/reveal violations, or nonreproducible arithmetic.
#[allow(clippy::too_many_arguments)]
pub fn build_brier_score(
    score_id: StableString,
    calculation_build_digest: ValueDigest,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    candidate_capability: &DurableSubmissionCapability,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    adjudication_capability: &DurableAdjudicationCapability,
    baseline: Option<(
        &ValidatedArtifact<ForecastSubmissionV1>,
        &DurableSubmissionCapability,
    )>,
) -> Result<ValidatedArtifact<ProperScoreArtifactV1>> {
    let value = expected_score(
        score_id,
        calculation_build_digest,
        definition,
        occurrence,
        occurrence_capability,
        candidate,
        candidate_capability,
        adjudication,
        adjudication_capability,
        baseline,
    )?;
    let bytes = canonical_bytes(&value)?;
    ValidatedArtifact::new(value, bytes)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn score_syntax(
    value: &ProperScoreArtifactV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    candidate_capability: &DurableSubmissionCapability,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    adjudication_capability: &DurableAdjudicationCapability,
    baseline: Option<(
        &ValidatedArtifact<ForecastSubmissionV1>,
        &DurableSubmissionCapability,
    )>,
) -> Result<()> {
    score_header(value)?;
    let expected = expected_score(
        value.score_id.clone(),
        value.calculation_build_digest.clone(),
        definition,
        occurrence,
        occurrence_capability,
        candidate,
        candidate_capability,
        adjudication,
        adjudication_capability,
        baseline,
    )?;
    if value != &expected {
        return invalid("proper-score artifact does not equal exact dependency recomputation");
    }
    Ok(())
}

/// Recomputes a score using the same opaque durable capabilities required to create it.
///
/// # Errors
///
/// Refuses any semantic, durable, or arithmetic mismatch.
#[allow(clippy::too_many_arguments)]
pub fn validate_score_artifact(
    value: ProperScoreArtifactV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &DurableOccurrenceCapability,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    candidate_capability: &DurableSubmissionCapability,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    adjudication_capability: &DurableAdjudicationCapability,
    baseline: Option<(
        &ValidatedArtifact<ForecastSubmissionV1>,
        &DurableSubmissionCapability,
    )>,
) -> Result<ValidatedArtifact<ProperScoreArtifactV1>> {
    score_syntax(
        &value,
        definition,
        occurrence,
        occurrence_capability,
        candidate,
        candidate_capability,
        adjudication,
        adjudication_capability,
        baseline,
    )?;
    let bytes = canonical_bytes(&value)?;
    ValidatedArtifact::new(value, bytes)
}
