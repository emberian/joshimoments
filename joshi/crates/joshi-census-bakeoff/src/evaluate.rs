use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::WireU64;

use crate::{
    BakeoffError, BakeoffInput, BakeoffMetrics, BakeoffQualificationV1, BakeoffResult,
    CandidateRecord, CountSummary, CoverageGap, DecodeOutcome, Disposition, Finality,
    PredicateOutcome, RatioPpm, ReferenceRecord, StreamSide,
};

fn wire(value: u128) -> Result<WireU64, BakeoffError> {
    u64::try_from(value)
        .map(WireU64::new)
        .map_err(|_| BakeoffError::Arithmetic)
}

fn ratio(numerator: u128, denominator: u128) -> Result<RatioPpm, BakeoffError> {
    let scaled = if denominator == 0 {
        0
    } else {
        numerator
            .checked_mul(1_000_000)
            .ok_or(BakeoffError::Arithmetic)?
            .checked_div(denominator)
            .ok_or(BakeoffError::Arithmetic)?
    };
    Ok(RatioPpm {
        numerator: wire(numerator)?,
        denominator: wire(denominator)?,
        parts_per_million: wire(scaled)?,
    })
}

fn finality_rank(value: Finality) -> u8 {
    match value {
        Finality::Processed => 0,
        Finality::Confirmed => 1,
        Finality::Finalized => 2,
    }
}

fn check_slot(input: &BakeoffInput, slot: u64) -> Result<(), BakeoffError> {
    if slot < input.window.lower_slot.get() || slot >= input.window.upper_slot.get() {
        return Err(BakeoffError::InvalidContract(
            "record outside coverage window",
        ));
    }
    Ok(())
}

fn check_gap(input: &BakeoffInput, gap: &CoverageGap) -> Result<(), BakeoffError> {
    if gap.window_id != input.window.window_id
        || gap.lower_slot.get() >= gap.upper_slot.get()
        || gap.lower_slot.get() < input.window.lower_slot.get()
        || gap.upper_slot.get() > input.window.upper_slot.get()
    {
        return Err(BakeoffError::InvalidContract("gap outside coverage window"));
    }
    Ok(())
}

fn duplicate_candidates(
    records: &[CandidateRecord],
) -> Result<(BTreeMap<joshi_domain::StableString, CandidateRecord>, u64), BakeoffError> {
    let mut unique = BTreeMap::new();
    let mut duplicates = 0_u64;
    for record in records {
        if let Some(previous) = unique.get(&record.signature) {
            if previous != record {
                return Err(BakeoffError::ConflictingDuplicate);
            }
            duplicates = duplicates.checked_add(1).ok_or(BakeoffError::Arithmetic)?;
        } else {
            unique.insert(record.signature.clone(), record.clone());
        }
    }
    Ok((unique, duplicates))
}

fn corrected_reference(
    records: &[ReferenceRecord],
) -> Result<(BTreeMap<joshi_domain::StableString, ReferenceRecord>, u64), BakeoffError> {
    let mut unique = BTreeMap::new();
    let mut corrections = 0_u64;
    for record in records {
        match unique.get(&record.signature) {
            None => {
                unique.insert(record.signature.clone(), record.clone());
            }
            Some(previous) if finality_rank(record.finality) > finality_rank(previous.finality) => {
                unique.insert(record.signature.clone(), record.clone());
                corrections = corrections.checked_add(1).ok_or(BakeoffError::Arithmetic)?;
            }
            Some(previous) if record.finality == previous.finality && previous != record => {
                return Err(BakeoffError::ConflictingDuplicate);
            }
            Some(_) => {}
        }
    }
    Ok((unique, corrections))
}

fn refused(input: &BakeoffInput, reason: &'static str) -> BakeoffResult {
    BakeoffResult {
        contract: crate::BAKEOFF_CONTRACT.to_owned(),
        schema_version: WireU64::new(crate::BAKEOFF_SCHEMA_VERSION),
        run_id: input.run_id.clone(),
        window: input.window.clone(),
        disposition: Disposition::Refused,
        qualification: BakeoffQualificationV1::UnverifiedSemantic,
        reason: joshi_domain::StableString::new(reason.to_owned()).expect("static reason"),
        metrics: None,
        candidate_gaps: input
            .gaps
            .iter()
            .filter(|gap| gap.side == StreamSide::Candidate)
            .cloned()
            .collect(),
        reference_gaps: input
            .gaps
            .iter()
            .filter(|gap| gap.side == StreamSide::Reference)
            .cloned()
            .collect(),
    }
}

/// Evaluates already-retained candidate/reference facts without provider execution.
///
/// Candidate records are filtered to exact predicate results; failed transactions, truncated
/// logs, and program-mention-only observations never become census positives. Reference records
/// are exact only after finalized hydration and pinned decoding. Finality corrections replace a
/// weaker occurrence of the same signature, while conflicting equal-finality occurrences refuse
/// evaluation.
///
/// # Errors
///
/// Returns a contract, duplicate, or integer-arithmetic refusal. Cost caps are represented in the
/// returned result as [`Disposition::Refused`] so the caller can persist the decision.
#[allow(clippy::missing_panics_doc, clippy::too_many_lines)]
pub fn evaluate(input: &BakeoffInput) -> Result<BakeoffResult, BakeoffError> {
    input.validate()?;
    for gap in &input.gaps {
        check_gap(input, gap)?;
    }
    for record in &input.candidate {
        check_slot(input, record.slot.get())?;
    }
    for record in &input.reference {
        check_slot(input, record.slot.get())?;
    }

    let candidate_bytes = input.candidate.iter().try_fold(0_u128, |sum, record| {
        sum.checked_add(u128::from(record.bytes.get()))
            .ok_or(BakeoffError::Arithmetic)
    })?;
    let reference_bytes = input.reference.iter().try_fold(0_u128, |sum, record| {
        sum.checked_add(u128::from(record.bytes.get()))
            .ok_or(BakeoffError::Arithmetic)
    })?;
    let candidate_credits = input.candidate.iter().try_fold(0_u128, |sum, record| {
        sum.checked_add(u128::from(record.provider_credits.get()))
            .ok_or(BakeoffError::Arithmetic)
    })?;
    let reference_credits = input.reference.iter().try_fold(0_u128, |sum, record| {
        sum.checked_add(u128::from(record.provider_credits.get()))
            .ok_or(BakeoffError::Arithmetic)
    })?;
    let candidate_latency = input.candidate.iter().try_fold(0_u128, |sum, record| {
        sum.checked_add(u128::from(record.latency_ms.get()))
            .ok_or(BakeoffError::Arithmetic)
    })?;
    let reference_latency = input.reference.iter().try_fold(0_u128, |sum, record| {
        sum.checked_add(u128::from(record.latency_ms.get()))
            .ok_or(BakeoffError::Arithmetic)
    })?;
    if candidate_bytes > u128::from(input.caps.max_candidate_bytes.get())
        || reference_bytes > u128::from(input.caps.max_reference_bytes.get())
        || candidate_credits > u128::from(input.caps.max_candidate_credits.get())
        || reference_credits > u128::from(input.caps.max_reference_credits.get())
        || candidate_latency
            .checked_add(reference_latency)
            .ok_or(BakeoffError::Arithmetic)?
            > u128::from(input.caps.max_total_latency_ms.get())
    {
        return Ok(refused(input, "cost_cap_exceeded"));
    }

    let (candidates, duplicate_count) = duplicate_candidates(&input.candidate)?;
    let (references, finality_corrections) = corrected_reference(&input.reference)?;
    let candidate_records: Vec<_> = candidates
        .values()
        .filter(|record| {
            record.finality == Finality::Finalized
                && !record.failed_transaction
                && !record.logs_truncated
                && record.predicate != PredicateOutcome::Unknown
                && record.program_mentioned
        })
        .collect();
    let reference_records: Vec<_> = references
        .values()
        .filter(|record| {
            record.finality == Finality::Finalized
                && record.hydrated_exact
                && !record.failed_transaction
                && record.decode == DecodeOutcome::Decoded
                && record.predicate != PredicateOutcome::Unknown
        })
        .collect();
    let candidate_positive: BTreeSet<_> = candidate_records
        .iter()
        .filter(|record| record.predicate == PredicateOutcome::Match)
        .map(|record| record.signature.clone())
        .collect();
    let reference_positive: BTreeSet<_> = reference_records
        .iter()
        .filter(|record| record.predicate == PredicateOutcome::Match)
        .map(|record| record.signature.clone())
        .collect();
    let true_positive = candidate_positive.intersection(&reference_positive).count() as u128;
    let reference_positive_count = reference_positive.len() as u128;
    let candidate_positive_count = candidate_positive.len() as u128;
    let decoded_reference_count = references
        .values()
        .filter(|record| record.finality == Finality::Finalized && record.hydrated_exact)
        .count() as u128;
    let parser_success_count = references
        .values()
        .filter(|record| {
            record.finality == Finality::Finalized
                && record.hydrated_exact
                && record.decode == DecodeOutcome::Decoded
        })
        .count() as u128;
    let candidate_gap_count = input
        .gaps
        .iter()
        .filter(|gap| gap.side == StreamSide::Candidate)
        .count() as u64;
    let reference_gap_count = input
        .gaps
        .iter()
        .filter(|gap| gap.side == StreamSide::Reference)
        .count() as u64;
    let counts = CountSummary {
        candidate_records: wire(input.candidate.len() as u128)?,
        reference_records: wire(input.reference.len() as u128)?,
        candidate_program_mentions: wire(
            input
                .candidate
                .iter()
                .filter(|record| record.program_mentioned)
                .count() as u128,
        )?,
        candidate_truncated: wire(
            input
                .candidate
                .iter()
                .filter(|record| record.logs_truncated)
                .count() as u128,
        )?,
        candidate_failed: wire(
            input
                .candidate
                .iter()
                .filter(|record| record.failed_transaction)
                .count() as u128,
        )?,
        candidate_duplicates: WireU64::new(duplicate_count),
        reference_hydration_missing: wire(
            input
                .reference
                .iter()
                .filter(|record| !record.hydrated_exact)
                .count() as u128,
        )?,
        reference_failed: wire(
            input
                .reference
                .iter()
                .filter(|record| record.failed_transaction)
                .count() as u128,
        )?,
        reference_decode_failures: wire(
            input
                .reference
                .iter()
                .filter(|record| record.decode != DecodeOutcome::Decoded)
                .count() as u128,
        )?,
        reference_finality_corrections: WireU64::new(finality_corrections),
    };
    let metrics = BakeoffMetrics {
        recall: ratio(true_positive, reference_positive_count)?,
        precision: ratio(true_positive, candidate_positive_count)?,
        parser_yield: ratio(parser_success_count, decoded_reference_count)?,
        candidate_latency_ms: ratio(candidate_latency, candidates.len() as u128)?,
        reference_latency_ms: ratio(reference_latency, references.len() as u128)?,
        candidate_bytes: wire(candidate_bytes)?,
        reference_bytes: wire(reference_bytes)?,
        candidate_credits: wire(candidate_credits)?,
        reference_credits: wire(reference_credits)?,
        counts,
    };
    let gaps_ok = candidate_gap_count <= input.thresholds.maximum_candidate_gap_count.get()
        && reference_gap_count <= input.thresholds.maximum_reference_gap_count.get();
    let reference_complete = !reference_records.is_empty();
    let nonvacuous = reference_positive_count > 0 && candidate_positive_count > 0;
    let thresholds_ok = metrics.recall.parts_per_million.get()
        >= input.thresholds.minimum_recall_ppm.get()
        && metrics.precision.parts_per_million.get()
            >= input.thresholds.minimum_precision_ppm.get()
        && metrics.parser_yield.parts_per_million.get()
            >= input.thresholds.minimum_parser_yield_ppm.get();
    let (disposition, reason) = if !reference_complete || !gaps_ok {
        (Disposition::Unavailable, "reference_or_coverage_incomplete")
    } else if thresholds_ok && nonvacuous {
        (
            Disposition::SampleOnly,
            "thresholds_met_but_store_attestation_unavailable",
        )
    } else {
        (Disposition::SampleOnly, "quality_threshold_not_met")
    };
    let result = BakeoffResult {
        contract: crate::BAKEOFF_CONTRACT.to_owned(),
        schema_version: WireU64::new(crate::BAKEOFF_SCHEMA_VERSION),
        run_id: input.run_id.clone(),
        window: input.window.clone(),
        disposition,
        qualification: BakeoffQualificationV1::UnverifiedSemantic,
        reason: joshi_domain::StableString::new(reason.to_owned()).expect("static reason"),
        metrics: Some(metrics),
        candidate_gaps: input
            .gaps
            .iter()
            .filter(|gap| gap.side == StreamSide::Candidate)
            .cloned()
            .collect(),
        reference_gaps: input
            .gaps
            .iter()
            .filter(|gap| gap.side == StreamSide::Reference)
            .cloned()
            .collect(),
    };
    result.validate()?;
    Ok(result)
}
