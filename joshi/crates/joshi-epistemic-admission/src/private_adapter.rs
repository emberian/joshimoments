//! In-crate verification used by the future `SQLite` adapter.
//!
//! This module is deliberately not public: moving any constructor or these admission operations
//! across the crate boundary would turn caller assertions into durable authority. It contains no
//! database code and is not exercised as a positive durable path until the store migration and
//! single-writer methods exist.

#![allow(dead_code)]

use crate::{
    EpistemicAdmissionError, Result,
    port::{
        FirstRoundSealReceipt, StoreResolvedClaimOccurrence, StoreResolvedFirstRoundSubmission,
    },
    preflight::UnverifiedSemantic,
};
use joshi_epistemic_book::{
    ArtifactRefV1, ClaimOccurrenceV1, ForecastSubmissionV1, canonical_bytes, digest_bytes,
};
use std::collections::BTreeSet;

fn occurrence_ref(value: &UnverifiedSemantic<ClaimOccurrenceV1>) -> ArtifactRefV1 {
    ArtifactRefV1 {
        occurrence_id: value.artifact().value().claim_occurrence_id.clone(),
        semantic_digest: value.artifact().semantic_digest().clone(),
    }
}

fn submission_ref(value: &UnverifiedSemantic<ForecastSubmissionV1>) -> ArtifactRefV1 {
    ArtifactRefV1 {
        occurrence_id: value.artifact().value().submission_id.clone(),
        semantic_digest: value.artifact().semantic_digest().clone(),
    }
}

/// Checks all exact occurrence receipt bindings before the private adapter returns its durable
/// occurrence capability to `joshi-epistemic-book`.
///
/// # Errors
///
/// Refuses substituted scene/universe/evidence/capabilities, a receipt later than its declared
/// B0 commit, or a missing atomic occurrence receipt.
pub(crate) fn verify_occurrence_receipts(
    occurrence: &UnverifiedSemantic<ClaimOccurrenceV1>,
    resolved: &StoreResolvedClaimOccurrence,
) -> Result<()> {
    let value = occurrence.artifact().value();
    let expected = occurrence_ref(occurrence);
    let manifest_digest = digest_bytes(&canonical_bytes(&value.frozen_input)?)?;
    let capability_digest = digest_bytes(&canonical_bytes(&value.capability_closure)?)?;
    if resolved.scene.scene != value.scene
        || resolved.universe.universe != value.instrumented_universe
        || resolved.evidence.frozen_input != value.frozen_input
        || resolved.evidence.manifest_digest != manifest_digest
        || resolved.cutoff.maximum_input_availability
            != value.frozen_input.maximum_input_availability
        || resolved.cutoff.information_cutoff != value.occurrence_information_cutoff
        || resolved.capabilities.capabilities != value.capability_closure
        || resolved.capabilities.closure_digest != capability_digest
        || resolved.commit.occurrence != expected
        || resolved.commit.committed_at != value.occurrence_commit_at
    {
        return Err(EpistemicAdmissionError::ReceiptBinding);
    }
    if !(resolved.cutoff.maximum_input_availability <= resolved.cutoff.information_cutoff
        && resolved.cutoff.information_cutoff <= resolved.commit.committed_at
        && resolved.commit.committed_at <= value.issue_deadline)
    {
        return Err(EpistemicAdmissionError::Clock);
    }
    Ok(())
}

/// Checks a store-sealed first round. Empty visibility and no prior durable reveal are mandatory;
/// the all-components-sealed/reveal proof is checked later by [`verify_first_round_reveal`].
///
/// # Errors
///
/// Refuses any visibility, namespace substitution, late durable commit, or occurrence mismatch.
pub(crate) fn verify_sealed_first_round_submission(
    occurrence: &UnverifiedSemantic<ClaimOccurrenceV1>,
    submission: &UnverifiedSemantic<ForecastSubmissionV1>,
    resolved: &StoreResolvedFirstRoundSubmission,
) -> Result<()> {
    verify_occurrence_receipts(occurrence, &resolved.occurrence)?;
    let occurrence_value = occurrence.artifact().value();
    let submission_value = submission.artifact().value();
    let expected_occurrence = occurrence_ref(occurrence);
    let expected_submission = submission_ref(submission);
    if resolved.namespace.occurrence != expected_occurrence
        || resolved.namespace.namespace_id != occurrence_value.sealed_forecast_journal.namespace_id
        || resolved.namespace.eligible_forecaster_ids
            != occurrence_value
                .sealed_forecast_journal
                .eligible_first_round_forecaster_ids
        || resolved.namespace.required_first_round_count
            != occurrence_value
                .sealed_forecast_journal
                .required_first_round_count
                .get()
        || resolved.namespace.reveal_not_before
            != occurrence_value.sealed_forecast_journal.reveal_not_before
        || resolved.visibility.occurrence != expected_occurrence
        || resolved.visibility.submission_id != submission_value.submission_id
        || !resolved.visibility.visible_submission_ids.is_empty()
        || !resolved.visibility.visible_ensemble_ids.is_empty()
        || resolved.visibility.reveal_at_before_commit.is_some()
        || resolved.commit.submission != expected_submission
        || resolved.commit.occurrence != expected_occurrence
    {
        return Err(EpistemicAdmissionError::FirstRoundNotBlind);
    }
    if !(occurrence_value.occurrence_commit_at <= submission_value.submission_production_time
        && submission_value.submission_production_time <= resolved.commit.committed_at
        && resolved.commit.committed_at <= occurrence_value.issue_deadline)
    {
        return Err(EpistemicAdmissionError::Clock);
    }
    Ok(())
}

/// Checks the one reveal event after every eligible first-round submission sealed.
///
/// The caller must pass the exact committed components, not merely a count. The private adapter
/// must additionally query that the namespace contains no other eligible first-round identity.
///
/// # Errors
///
/// Refuses cross-occurrence components, an incomplete registered set, or a reveal before seal.
pub(crate) fn verify_first_round_reveal(
    occurrence: &UnverifiedSemantic<ClaimOccurrenceV1>,
    components: &[(
        &UnverifiedSemantic<ForecastSubmissionV1>,
        &StoreResolvedFirstRoundSubmission,
    )],
    seal: &FirstRoundSealReceipt,
) -> Result<()> {
    let expected = occurrence_ref(occurrence);
    let journal = &occurrence.artifact().value().sealed_forecast_journal;
    if components.len() != journal.eligible_first_round_forecaster_ids.len()
        || seal.occurrence != expected
        || seal.reveal_at < journal.reveal_not_before
        || seal.all_eligible_sealed_at > seal.reveal_at
    {
        return Err(EpistemicAdmissionError::RevealBeforeSeal);
    }
    let expected_forecasters = journal
        .eligible_first_round_forecaster_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut observed_forecasters = BTreeSet::new();
    for (submission, component) in components {
        verify_sealed_first_round_submission(occurrence, submission, component)?;
        if component.occurrence.commit.occurrence != expected
            || component.commit.committed_at > seal.all_eligible_sealed_at
        {
            return Err(EpistemicAdmissionError::RevealBeforeSeal);
        }
        observed_forecasters.insert(submission.artifact().value().lineage.forecaster_id.clone());
    }
    if observed_forecasters != expected_forecasters {
        return Err(EpistemicAdmissionError::RevealBeforeSeal);
    }
    Ok(())
}
