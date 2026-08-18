use joshi_domain::{StableString, WireU64};

use crate::*;

fn s(value: &str) -> StableString {
    StableString::new(value.to_owned()).expect("stable string")
}

fn candidate(signature: &str, predicate: PredicateOutcome) -> CandidateRecord {
    CandidateRecord {
        signature: s(signature),
        slot: WireU64::new(10),
        finality: Finality::Finalized,
        program_mentioned: true,
        logs_truncated: false,
        failed_transaction: false,
        predicate,
        bytes: WireU64::new(10),
        provider_credits: WireU64::new(1),
        latency_ms: WireU64::new(5),
    }
}

fn reference(signature: &str, predicate: PredicateOutcome) -> ReferenceRecord {
    ReferenceRecord {
        signature: s(signature),
        slot: WireU64::new(10),
        finality: Finality::Finalized,
        hydrated_exact: true,
        failed_transaction: false,
        decode: DecodeOutcome::Decoded,
        predicate,
        bytes: WireU64::new(20),
        provider_credits: WireU64::new(2),
        latency_ms: WireU64::new(7),
    }
}

fn input() -> BakeoffInput {
    BakeoffInput {
        contract: BAKEOFF_CONTRACT.to_owned(),
        schema_version: WireU64::new(BAKEOFF_SCHEMA_VERSION),
        run_id: s("run-1"),
        window: CoverageWindow {
            window_id: s("window-1"),
            lower_slot: WireU64::new(1),
            upper_slot: WireU64::new(20),
        },
        candidate: vec![candidate("a", PredicateOutcome::Match)],
        reference: vec![reference("a", PredicateOutcome::Match)],
        gaps: Vec::new(),
        caps: CostCaps {
            max_candidate_bytes: WireU64::new(100),
            max_reference_bytes: WireU64::new(100),
            max_candidate_credits: WireU64::new(10),
            max_reference_credits: WireU64::new(10),
            max_total_latency_ms: WireU64::new(100),
        },
        thresholds: Thresholds {
            minimum_recall_ppm: WireU64::new(1_000_000),
            minimum_precision_ppm: WireU64::new(1_000_000),
            minimum_parser_yield_ppm: WireU64::new(1_000_000),
            maximum_candidate_gap_count: WireU64::new(0),
            maximum_reference_gap_count: WireU64::new(0),
        },
    }
}

#[test]
fn exact_finalized_decode_qualifies() {
    let result = evaluate(&input()).expect("evaluate");
    assert_eq!(result.disposition, Disposition::SampleOnly);
    assert_eq!(
        result
            .metrics
            .as_ref()
            .expect("metrics")
            .recall
            .parts_per_million
            .get(),
        1_000_000
    );
    result.validate_against(&input()).expect("recompute");
}

#[test]
fn zero_thresholds_and_no_match_are_not_vacuous_qualification() {
    let mut value = input();
    value.candidate[0].predicate = PredicateOutcome::NoMatch;
    value.reference[0].predicate = PredicateOutcome::NoMatch;
    value.thresholds.minimum_recall_ppm = WireU64::new(0);
    value.thresholds.minimum_precision_ppm = WireU64::new(0);
    value.thresholds.minimum_parser_yield_ppm = WireU64::new(0);
    let result = evaluate(&value).expect("evaluate");
    assert_eq!(result.disposition, Disposition::SampleOnly);
    assert_eq!(
        result.qualification,
        BakeoffQualificationV1::UnverifiedSemantic
    );
}

#[test]
fn failed_truncated_and_program_only_records_do_not_become_positives() {
    let mut value = input();
    let mut failed = candidate("failed", PredicateOutcome::Match);
    failed.failed_transaction = true;
    let mut truncated = candidate("truncated", PredicateOutcome::Match);
    truncated.logs_truncated = true;
    let mut mention_only = candidate("mention-only", PredicateOutcome::Unknown);
    mention_only.program_mentioned = true;
    value.candidate = vec![failed, truncated, mention_only];
    value.reference.clear();
    assert_eq!(
        evaluate(&value).expect("evaluate").disposition,
        Disposition::Unavailable
    );
}

#[test]
fn reference_gap_is_unavailable_and_cost_cap_is_refused() {
    let mut value = input();
    value.gaps.push(CoverageGap {
        side: StreamSide::Reference,
        window_id: s("window-1"),
        reason: GapReason::MissingHydration,
        lower_slot: WireU64::new(2),
        upper_slot: WireU64::new(3),
    });
    assert_eq!(
        evaluate(&value).expect("evaluate").disposition,
        Disposition::Unavailable
    );
    value.caps.max_candidate_bytes = WireU64::new(1);
    assert_eq!(
        evaluate(&value).expect("evaluate").disposition,
        Disposition::Refused
    );
}

#[test]
fn finality_correction_and_conflicting_duplicate_are_distinct() {
    let mut value = input();
    let mut processed = reference("a", PredicateOutcome::NoMatch);
    processed.finality = Finality::Processed;
    value.reference = vec![processed, reference("a", PredicateOutcome::Match)];
    let result = evaluate(&value).expect("correction");
    assert_eq!(
        result
            .metrics
            .expect("metrics")
            .counts
            .reference_finality_corrections
            .get(),
        1
    );
    let mut conflict = input();
    let mut other = candidate("a", PredicateOutcome::NoMatch);
    other.bytes = WireU64::new(11);
    conflict.candidate.push(other);
    assert_eq!(evaluate(&conflict), Err(BakeoffError::ConflictingDuplicate));
}
