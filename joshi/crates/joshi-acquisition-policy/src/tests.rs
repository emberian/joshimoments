use std::{collections::BTreeMap, str::FromStr};

use joshi_domain::{StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    CONTROL_RECEIPT_CONTRACT, CollectorControlReceiptV1, CollectorControlReservationV1,
    ControlReservationExpectation, DegradationReason, HotScopeRecordV1, PolicyDecisionV1,
    PolicyEvaluationV1, PolicyJournal, PressureStage, ResourceSnapshotV1, ScopePresence,
    SourceAvailability, adapt_supervisor_control_reservation, evaluate, pending_control_commands,
    receipt_to_applied,
};

const FIXTURE: &str = include_str!("../../../fixtures/acquisition-policy/deterministic_scope.json");
const EXPECTED: &str = include_str!("../../../fixtures/acquisition-policy/expected_summary.json");

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Scenario {
    journal: Vec<HotScopeRecordV1>,
    evaluation: PolicyEvaluationV1,
    overload_resources: ResourceSnapshotV1,
    adversarial_market_labels: BTreeMap<String, String>,
}

#[derive(Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct DecisionSummary {
    pressure_stage: PressureStage,
    record_kinds: Vec<String>,
    active_intent_ids: Vec<String>,
    absent_intent_ids: Vec<String>,
    retained_census_ids: Vec<String>,
    inactive_model_proposal_intent_ids: Vec<String>,
}

fn scenario() -> Scenario {
    serde_json::from_str(FIXTURE).expect("fixture parses")
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable test value")
}

fn instant(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("test timestamp")
}

fn combined_journal(scenario: &Scenario, decision: &PolicyDecisionV1) -> PolicyJournal {
    let mut records = scenario.journal.clone();
    records.extend(decision.new_records.clone());
    PolicyJournal::new(records).expect("generated records close over fixture journal")
}

fn summary(decision: &PolicyDecisionV1) -> DecisionSummary {
    let mut record_kinds = Vec::new();
    let mut active = Vec::new();
    let mut absent = Vec::new();
    for record in &decision.new_records {
        match record {
            HotScopeRecordV1::Intent(_) => record_kinds.push("intent".to_owned()),
            HotScopeRecordV1::Desired(value) => {
                record_kinds.push("desired".to_owned());
                active.push(value.intent_id.as_str().to_owned());
            }
            HotScopeRecordV1::Applied(_) => record_kinds.push("applied".to_owned()),
            HotScopeRecordV1::Degraded(value) => {
                record_kinds.push("degraded".to_owned());
                if value.effective_scope.is_some() {
                    active.push(value.intent_id.as_str().to_owned());
                } else {
                    absent.push(value.intent_id.as_str().to_owned());
                }
            }
            HotScopeRecordV1::Closed(value) => {
                record_kinds.push("closed".to_owned());
                absent.push(value.intent_id.as_str().to_owned());
            }
        }
    }
    active.sort();
    absent.sort();
    DecisionSummary {
        pressure_stage: decision.pressure_stage,
        record_kinds,
        active_intent_ids: active,
        absent_intent_ids: absent,
        retained_census_ids: decision
            .retained_census_denominators
            .iter()
            .map(|value| value.census_id.as_str().to_owned())
            .collect(),
        inactive_model_proposal_intent_ids: decision
            .inactive_model_proposal_intent_ids
            .iter()
            .map(|value| value.as_str().to_owned())
            .collect(),
    }
}

#[test]
fn fixture_and_emitted_wire_values_contain_no_json_numbers() {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    assert_no_numbers(&fixture);
    let scenario = scenario();
    let journal = PolicyJournal::new(scenario.journal).unwrap();
    let decision = evaluate(&journal, &scenario.evaluation).unwrap();
    assert_no_numbers(&serde_json::to_value(decision).unwrap());
}

#[test]
fn replay_is_byte_identical_and_matches_golden_summary() {
    let scenario = scenario();
    let journal = PolicyJournal::new(scenario.journal.clone()).unwrap();
    let first = evaluate(&journal, &scenario.evaluation).unwrap();
    let second = evaluate(&journal, &scenario.evaluation).unwrap();
    assert_eq!(
        serde_json::to_vec(&first).unwrap(),
        serde_json::to_vec(&second).unwrap()
    );

    let expected: Value = serde_json::from_str(EXPECTED).unwrap();
    assert_eq!(
        serde_json::to_value(summary(&first)).unwrap(),
        expected["normal"]
    );

    let reconstructed = combined_journal(&scenario, &first);
    assert!(
        evaluate(&reconstructed, &scenario.evaluation)
            .unwrap()
            .new_records
            .is_empty()
    );
}

#[test]
fn overload_retains_denominator_and_does_not_consume_market_labels() {
    let mut scenario = scenario();
    let journal = PolicyJournal::new(scenario.journal.clone()).unwrap();
    let original_evaluation = scenario.evaluation.clone();
    let normal = evaluate(&journal, &scenario.evaluation).unwrap();
    scenario.evaluation.resources = scenario.overload_resources.clone();
    scenario.evaluation.decision_occurrence_id = stable("decision-overload");
    let overloaded = evaluate(&journal, &scenario.evaluation).unwrap();

    let expected: Value = serde_json::from_str(EXPECTED).unwrap();
    assert_eq!(
        serde_json::to_value(summary(&overloaded)).unwrap(),
        expected["overload"]
    );
    assert!(
        overloaded
            .latest_desired_presence
            .values()
            .all(|presence| { *presence == ScopePresence::Absent })
    );
    assert_eq!(
        overloaded.retained_census_denominators[0]
            .eligible_subject_count
            .get(),
        4
    );

    // Labels intentionally live outside PolicyEvaluationV1. Reclassifying hot/losing/cold cannot
    // affect the reducer; only exact justification recency and stable IDs are eligible.
    scenario
        .adversarial_market_labels
        .insert("intent-high".to_owned(), "now_claimed_losing".to_owned());
    assert_eq!(
        serde_json::to_vec(&normal).unwrap(),
        serde_json::to_vec(&evaluate(&journal, &original_evaluation).unwrap()).unwrap()
    );
}

#[test]
fn model_proposal_is_visible_but_never_active() {
    let scenario = scenario();
    let journal = PolicyJournal::new(scenario.journal.clone()).unwrap();
    let decision = evaluate(&journal, &scenario.evaluation).unwrap();
    assert_eq!(
        decision.inactive_model_proposal_intent_ids,
        vec![stable("intent-model")]
    );
    let proposal = decision.new_records.iter().find_map(|record| match record {
        HotScopeRecordV1::Degraded(value) if value.intent_id.as_str() == "intent-model" => {
            Some(value)
        }
        _ => None,
    });
    let proposal = proposal.expect("proposal has explicit nonactivation record");
    assert!(proposal.effective_scope.is_none());
    assert!(
        proposal
            .changes
            .iter()
            .any(|change| { change.reason == DegradationReason::ModelProposalNonactivating })
    );

    let mut invalid = scenario.journal;
    if let HotScopeRecordV1::Intent(intent) = &mut invalid[0]
        && let crate::ActivationAuthority::OperatorAccepted(binding) = &mut intent.activation
    {
        binding.scene_id = stable("different-scene");
    }
    assert!(PolicyJournal::new(invalid).is_err());
}

#[test]
#[allow(clippy::too_many_lines)] // One continuity narrative covers reserve, apply, restart, close.
fn expiry_closes_and_restart_reconstructs_desired_vs_applied() {
    let scenario = scenario();
    let initial = PolicyJournal::new(scenario.journal.clone()).unwrap();
    let decision = evaluate(&initial, &scenario.evaluation).unwrap();
    let desired_journal = combined_journal(&scenario, &decision);
    let generation = &scenario.evaluation.collector_generations;
    let reservations = reservations_for_latest(&desired_journal, 7);
    let adapter = stable("collector-adapter-v1");
    let commands =
        pending_control_commands(&desired_journal, generation, &reservations, &adapter).unwrap();
    assert_eq!(commands.len(), 2);

    let command = &commands[0];
    let receipt = CollectorControlReceiptV1 {
        contract: stable(CONTROL_RECEIPT_CONTRACT),
        schema_version: WireU64::new(1),
        receipt_id: stable("control-receipt-1"),
        command_id: command.command_id.clone(),
        control_write_reservation_id: command.control_write_reservation_id.clone(),
        supervisor_reservation_digest: command.supervisor_reservation_digest.clone(),
        source_key: command.source_key.clone(),
        operation_key: command.operation_key.clone(),
        generation: command.generation,
        attempt_ordinal: command.attempt_ordinal,
        target_record_id: command.target_record_id.clone(),
        control_bytes_digest: command.bytes_digest().unwrap(),
        adapter_version: command.adapter_version.clone(),
        handed_to_source_adapter_at: instant("2026-08-17T00:11:00.000000Z"),
        provider_acceptance: stable("not_asserted"),
        coverage_status: stable("not_asserted"),
    };
    let mut superseding_evaluation = scenario.evaluation.clone();
    superseding_evaluation.decision_occurrence_id = stable("decision-before-stale-receipt");
    superseding_evaluation.resources = scenario.overload_resources.clone();
    let superseding = evaluate(&desired_journal, &superseding_evaluation).unwrap();
    let mut superseded_records = desired_journal.records().to_vec();
    superseded_records.extend(superseding.new_records);
    let superseded_journal = PolicyJournal::new(superseded_records).unwrap();
    assert!(
        receipt_to_applied(
            &superseded_journal,
            command,
            &receipt,
            stable("stale-applied-record"),
            instant("2026-08-17T00:11:00.000000Z"),
        )
        .is_err()
    );

    let applied = receipt_to_applied(
        &desired_journal,
        command,
        &receipt,
        stable("applied-record-1"),
        instant("2026-08-17T00:11:00.000000Z"),
    )
    .unwrap();
    let mut with_applied = desired_journal.records().to_vec();
    with_applied.push(applied);
    let with_applied = PolicyJournal::new(with_applied).unwrap();
    assert_eq!(
        pending_control_commands(&with_applied, generation, &reservations, &adapter)
            .unwrap()
            .len(),
        1
    );

    let mut restarted_generation = generation.clone();
    restarted_generation[0].generation = WireU64::new(8);
    restarted_generation[0].availability = SourceAvailability::Healthy;
    let restart_reservations = reservations_for_latest(&with_applied, 8);
    assert_eq!(
        pending_control_commands(
            &with_applied,
            &restarted_generation,
            &restart_reservations,
            &adapter,
        )
        .unwrap()
        .len(),
        2
    );

    let mut expiry = scenario.evaluation.clone();
    expiry.decision_occurrence_id = stable("decision-expiry");
    expiry.evaluated_at = instant("2026-08-17T03:00:00.000000Z");
    let closed = evaluate(&initial, &expiry).unwrap();
    assert_eq!(
        closed
            .new_records
            .iter()
            .filter(|record| matches!(record, HotScopeRecordV1::Closed(_)))
            .count(),
        4
    );
    assert_eq!(closed.retained_census_denominators.len(), 1);

    let closed_after_applied = evaluate(&with_applied, &expiry).unwrap();
    let mut closed_records = with_applied.records().to_vec();
    closed_records.extend(closed_after_applied.new_records);
    let closed_journal = PolicyJournal::new(closed_records).unwrap();
    let remove_reservations = reservations_for_latest(&closed_journal, 7);
    let remove_commands =
        pending_control_commands(&closed_journal, generation, &remove_reservations, &adapter)
            .unwrap();
    assert_eq!(remove_commands.len(), 1);
    assert_eq!(
        remove_commands[0].action,
        crate::CollectorControlAction::Remove
    );
}

#[test]
fn strict_budget_and_denominator_closures_refuse_ambiguity() {
    let mut value: Value = serde_json::from_str(FIXTURE).unwrap();
    value["journal"][0]["requestedSources"][0]["budget"]
        .as_object_mut()
        .unwrap()
        .remove("maxPages");
    assert!(serde_json::from_value::<Scenario>(value).is_err());

    let scenario = scenario();
    let mut changed = scenario.journal.clone();
    if let HotScopeRecordV1::Intent(intent) = &mut changed[0] {
        intent.census_denominators[0].kind = crate::CensusKind::ProductBoardParityPassed;
    }
    assert!(PolicyJournal::new(changed).is_err());

    let mut later_reason = scenario.journal.clone();
    if let HotScopeRecordV1::Intent(intent) = &mut later_reason[0] {
        intent.reasons[0].justified_at = instant("2026-08-17T00:04:30.000000Z");
        intent.last_justified_at = intent.reasons[0].justified_at;
    }
    assert!(PolicyJournal::new(later_reason).is_err());

    let mut later_evidence = scenario.journal.clone();
    if let HotScopeRecordV1::Intent(intent) = &mut later_evidence[0] {
        intent.reasons[0].evidence[0].available_at = instant("2026-08-17T00:04:30.000000Z");
    }
    assert!(PolicyJournal::new(later_evidence).is_err());

    let mut later_commit = scenario.journal.clone();
    if let HotScopeRecordV1::Intent(intent) = &mut later_commit[0] {
        intent.census_denominators[0].as_of.commit_through = Some(WireU64::new(41));
    }
    assert!(PolicyJournal::new(later_commit).is_err());

    let mut missing_scene_closure = scenario.journal.clone();
    if let HotScopeRecordV1::Intent(intent) = &mut missing_scene_closure[0] {
        intent.reasons[0]
            .evidence
            .retain(|link| link.kind != crate::EvidenceKind::Scene);
    }
    assert!(PolicyJournal::new(missing_scene_closure).is_err());

    let mut duplicate = scenario.journal;
    duplicate[1].head_mut_for_test().record_id = stable("intent-record-cold");
    assert!(PolicyJournal::new(duplicate).is_err());

    let base: Scenario = serde_json::from_str(FIXTURE).unwrap();
    let journal = PolicyJournal::new(base.journal).unwrap();
    let mut future_resource = base.evaluation;
    future_resource.resources.sampled_at = instant("2026-08-17T00:11:00.000000Z");
    assert!(evaluate(&journal, &future_resource).is_err());
}

#[test]
fn supervisor_reservation_adapter_rejects_wrong_kind_and_ordinal() {
    let target = stable("target-record");
    let expected = ControlReservationExpectation {
        source_key: stable("helius-main"),
        operation_key: stable("mint-hot-observation"),
        generation: WireU64::new(7),
        attempt_ordinal: WireU64::new(9),
        target_record_id: target.clone(),
    };
    let valid = supervisor_reservation_bytes(&target, 7, 9, "control_write");
    assert!(adapt_supervisor_control_reservation(&valid, &expected).is_ok());
    let wrong_kind = supervisor_reservation_bytes(&target, 7, 9, "http_request");
    assert!(adapt_supervisor_control_reservation(&wrong_kind, &expected).is_err());
    let wrong_ordinal = supervisor_reservation_bytes(&target, 7, 8, "control_write");
    assert!(adapt_supervisor_control_reservation(&wrong_ordinal, &expected).is_err());
}

fn reservations_for_latest(
    journal: &PolicyJournal,
    generation: u64,
) -> Vec<CollectorControlReservationV1> {
    crate::policy::all_latest_targets(journal.records())
        .into_iter()
        .enumerate()
        .map(|(index, target)| {
            let (_, source, operation, _, _) = crate::policy::semantic_target(target).unwrap();
            let ordinal = u64::try_from(index).unwrap().saturating_add(1);
            let expectation = ControlReservationExpectation {
                source_key: source.clone(),
                operation_key: operation.clone(),
                generation: WireU64::new(generation),
                attempt_ordinal: WireU64::new(ordinal),
                target_record_id: target.head().record_id.clone(),
            };
            let bytes = supervisor_reservation_bytes(
                &target.head().record_id,
                generation,
                ordinal,
                "control_write",
            );
            adapt_supervisor_control_reservation(&bytes, &expectation).unwrap()
        })
        .collect()
}

fn supervisor_reservation_bytes(
    target: &StableString,
    generation: u64,
    attempt_ordinal: u64,
    kind: &str,
) -> Vec<u8> {
    format!(
        concat!(
            "{{\"contract\":\"joshi.supervisor.v1\",",
            "\"reservationId\":\"reservation-{generation}-{attempt_ordinal}\",",
            "\"installationId\":\"installation-fixture\",",
            "\"sourceKey\":\"helius-main\",",
            "\"operationKey\":\"mint-hot-observation\",",
            "\"generation\":{generation},",
            "\"attemptOrdinal\":{attempt_ordinal},",
            "\"kind\":\"{kind}\",",
            "\"scope\":{{\"source_id\":\"policy-control\",",
            "\"family\":{{\"discriminator\":\"hot_lane\",\"recognition\":\"known\"}},",
            "\"subject\":\"{target}\"}},",
            "\"lower\":{{\"clock\":\"wall\",\"value\":\"2026-08-17T00:10:30.000000Z\"}},",
            "\"protection\":{{\"class\":\"public_integrity\",\"domain\":\"public-policy-control\"}},",
            "\"reservedAt\":\"2026-08-17T00:10:30.000000Z\",",
            "\"authority\":\"read_only_no_execution\"}}"
        ),
        generation = generation,
        attempt_ordinal = attempt_ordinal,
        kind = kind,
        target = target.as_str(),
    )
    .into_bytes()
}

trait TestRecordMut {
    fn head_mut_for_test(&mut self) -> &mut crate::PolicyRecordHead;
}

impl TestRecordMut for HotScopeRecordV1 {
    fn head_mut_for_test(&mut self) -> &mut crate::PolicyRecordHead {
        match self {
            Self::Intent(value) => &mut value.head,
            Self::Desired(value) => &mut value.head,
            Self::Applied(value) => &mut value.head,
            Self::Degraded(value) => &mut value.head,
            Self::Closed(value) => &mut value.head,
        }
    }
}

fn assert_no_numbers(value: &Value) {
    match value {
        Value::Array(values) => values.iter().for_each(assert_no_numbers),
        Value::Object(values) => values.values().for_each(assert_no_numbers),
        Value::Number(number) => panic!("unexpected JSON number token: {number}"),
        Value::Null | Value::Bool(_) | Value::String(_) => {}
    }
}

#[test]
fn exactly_one_subject_is_promoted_and_its_ceilings_are_the_reducers_own() {
    let scenario = scenario();
    let journal = PolicyJournal::new(scenario.journal.clone()).unwrap();
    let decision = evaluate(&journal, &scenario.evaluation).unwrap();

    let subject = crate::ScopeSubject {
        kind: crate::SubjectKind::Mint,
        key: stable("mint-high-activity"),
    };
    let terms = crate::promote_one(&decision, &subject).unwrap();
    assert_eq!(terms.contract.as_str(), crate::HOT_LEASE_TERMS_CONTRACT);
    assert_eq!(terms.authority.as_str(), "read_only_no_execution");
    assert_eq!(terms.subject, subject);
    assert_eq!(terms.source_key.as_str(), "helius-main");
    assert_eq!(terms.operation_key.as_str(), "mint-hot-observation");
    assert!(!terms.is_degraded());

    // Every ceiling is the exact budget the reducer emitted, never a local default.
    let scope = decision
        .new_records
        .iter()
        .find_map(|record| match record {
            HotScopeRecordV1::Desired(value) if value.scope.subject == subject => {
                Some(&value.scope)
            }
            _ => None,
        })
        .expect("the subject has a desired scope");
    assert_eq!(terms.max_connections, scope.budget.max_requests);
    assert_eq!(terms.max_frames, scope.budget.max_pages);
    assert_eq!(terms.max_ingress_bytes, scope.budget.max_response_bytes);
    assert_eq!(terms.expires_at, scope.expires_at);
    assert_eq!(terms.opened_at, scenario.evaluation.evaluated_at);
    assert_eq!(
        terms.window_us.get(),
        u64::try_from(
            (scope.expires_at.as_datetime() - scenario.evaluation.evaluated_at.as_datetime())
                .whole_microseconds()
        )
        .unwrap()
    );
    assert_eq!(terms.window_ms(), terms.window_us.get() / 1_000);
    assert_eq!(terms.census_ids.len(), 1);

    // Terms are inert wire values: they round-trip and carry no JSON number tokens.
    let encoded = serde_json::to_value(&terms).unwrap();
    assert_no_numbers(&encoded);
    assert_eq!(
        serde_json::from_value::<crate::HotLeaseTermsV1>(encoded).unwrap(),
        terms
    );
}

#[test]
fn a_subject_the_reducer_did_not_activate_is_refused_with_its_reasons() {
    let scenario = scenario();
    let journal = PolicyJournal::new(scenario.journal.clone()).unwrap();
    let decision = evaluate(&journal, &scenario.evaluation).unwrap();

    // The model proposal is visible in the journal but has no active scope.
    let proposal = crate::ScopeSubject {
        kind: crate::SubjectKind::Mint,
        key: stable("mint-model-proposal"),
    };
    let refusal = crate::promote_one(&decision, &proposal).unwrap_err();
    assert!(
        format!("{refusal}").contains("ModelProposalNonactivating"),
        "refusal must name the reducer's own reason: {refusal}"
    );

    // A subject that was never named at all is refused, not defaulted.
    let stranger = crate::ScopeSubject {
        kind: crate::SubjectKind::Mint,
        key: stable("mint-never-considered"),
    };
    assert!(crate::promote_one(&decision, &stranger).is_err());
}

#[test]
fn overload_refuses_every_promotion_while_the_denominator_survives() {
    let mut scenario = scenario();
    let journal = PolicyJournal::new(scenario.journal.clone()).unwrap();
    scenario.evaluation.resources = scenario.overload_resources.clone();
    scenario.evaluation.decision_occurrence_id = stable("decision-overload");
    let overloaded = evaluate(&journal, &scenario.evaluation).unwrap();
    assert!(!crate::pressure_permits_hot_acquisition(
        overloaded.pressure_stage
    ));
    for key in [
        "mint-high-activity",
        "mint-cold-market",
        "mint-losing-market",
        "mint-model-proposal",
    ] {
        let subject = crate::ScopeSubject {
            kind: crate::SubjectKind::Mint,
            key: stable(key),
        };
        assert!(
            crate::promote_one(&overloaded, &subject).is_err(),
            "{key} must not be promoted under overload"
        );
    }
    assert!(!overloaded.retained_census_denominators.is_empty());
}

#[test]
fn a_degraded_but_active_scope_is_promoted_carrying_its_degradations() {
    let mut scenario = scenario();
    // Raise queue record utilization past the 90% shorten-hot-lease threshold without reaching
    // the denominator-only cut, so the reducer keeps the scope active but shortens its expiry.
    let capacity = scenario.evaluation.resources.queue_record_capacity.get();
    let reserve = scenario
        .evaluation
        .resources
        .queue_record_control_reserve
        .get();
    let usable = capacity - reserve;
    scenario.evaluation.resources.queue_records_used = WireU64::new(usable * 95 / 100);
    scenario.evaluation.decision_occurrence_id = stable("decision-shortened");
    let journal = PolicyJournal::new(scenario.journal.clone()).unwrap();
    let decision = evaluate(&journal, &scenario.evaluation).unwrap();
    assert_eq!(decision.pressure_stage, PressureStage::ShortenHotLeases);

    let subject = crate::ScopeSubject {
        kind: crate::SubjectKind::Mint,
        key: stable("mint-high-activity"),
    };
    let terms = crate::promote_one(&decision, &subject).unwrap();
    assert!(terms.is_degraded());
    assert!(
        terms
            .degradations
            .iter()
            .any(|change| change.reason == DegradationReason::HotLeaseShortened)
    );
    // The shortened lease is strictly shorter than the intent's own two-hour interval.
    assert!(terms.expires_at < instant("2026-08-17T02:00:00.000000Z"));
    assert!(terms.window_us.get() > 0);
}
