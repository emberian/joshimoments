use joshi_domain::{StableString, UtcTimestamp, WireU64};
use joshi_operational_status::{
    DegradationStage, FaultActionV1, FaultExpectationV1, FaultHarnessStateV1, FaultKind,
    FaultScenarioV1, FaultStepV1, HealthReadiness, RecoveryState, run_fault_scenario,
};
use std::str::FromStr;

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable fixture value")
}

fn initial() -> FaultHarnessStateV1 {
    FaultHarnessStateV1 {
        readiness: HealthReadiness::Ready,
        degradation_stage: DegradationStage::FullFidelity,
        recovery_state: RecoveryState::Stable,
        open_gap_count: WireU64::new(0),
        quarantine_count: WireU64::new(0),
        backlog_records: WireU64::new(0),
        backlog_bytes: WireU64::new(0),
        prior_projection_served_stale: false,
        presentation_witnessed: true,
        source_restart_permitted: true,
        logs_used_as_evidence: false,
    }
}

#[test]
fn fixture_proves_saturation_drain_and_verified_restart() {
    let scenario: FaultScenarioV1 = serde_json::from_slice(include_bytes!(
        "../../../fixtures/operational-status/fault_queue_recovery.json"
    ))
    .expect("fault fixture JSON");
    let report = run_fault_scenario(&scenario).expect("fault fixture passes");
    assert_eq!(report.passed_steps.get(), 5);
    let last = report.states.last().expect("final state");
    assert_eq!(last.readiness, HealthReadiness::Ready);
    assert_eq!(last.recovery_state, RecoveryState::Recovered);
    assert_eq!(last.open_gap_count.get(), 1);
    assert!(!last.logs_used_as_evidence);
}

#[test]
fn required_fault_matrix_has_declared_non_silent_effects() {
    let faults = [
        FaultKind::SourceDisconnect,
        FaultKind::RateLimited,
        FaultKind::AuthenticationRejected,
        FaultKind::MalformedData,
        FaultKind::SchemaDrift,
        FaultKind::DiskPressure,
        FaultKind::QueueRecordsFull,
        FaultKind::QueueBytesFull,
        FaultKind::CoreUnavailable,
        FaultKind::ReplicaUnavailable,
        FaultKind::ReplicaCorrupt,
        FaultKind::ProjectionFailure,
        FaultKind::BrowserDisconnect,
        FaultKind::ClockStep,
    ];
    for (index, fault) in faults.into_iter().enumerate() {
        let expected = expected_after(fault);
        let scenario = FaultScenarioV1 {
            contract: "joshi.operational.fault_scenario/v1".to_owned(),
            scenario_id: stable(&format!("fault-scenario:{index}")),
            initial: initial(),
            steps: vec![FaultStepV1 {
                at: UtcTimestamp::from_str("2026-08-17T12:00:01.000000Z").expect("fixture time"),
                input: FaultActionV1::Inject {
                    fault,
                    added_backlog_records: WireU64::new(0),
                    added_backlog_bytes: WireU64::new(0),
                },
                expected,
            }],
        };
        run_fault_scenario(&scenario).expect("declared fault transition");
    }
}

fn expected_after(fault: FaultKind) -> FaultExpectationV1 {
    let mut value = FaultExpectationV1 {
        readiness: HealthReadiness::Degraded,
        degradation_stage: DegradationStage::FullFidelity,
        recovery_state: RecoveryState::Pending,
        open_gap_count: WireU64::new(0),
        quarantine_count: WireU64::new(0),
        backlog_records: WireU64::new(0),
        backlog_bytes: WireU64::new(0),
        prior_projection_served_stale: false,
        presentation_witnessed: true,
        source_restart_permitted: false,
    };
    match fault {
        FaultKind::SourceDisconnect
        | FaultKind::RateLimited
        | FaultKind::AuthenticationRejected => {
            value.degradation_stage = DegradationStage::SocialRefreshSlowed;
            value.open_gap_count = WireU64::new(1);
        }
        FaultKind::MalformedData | FaultKind::SchemaDrift => {
            value.degradation_stage = DegradationStage::OptionalMediaDisabled;
            value.open_gap_count = WireU64::new(1);
            value.quarantine_count = WireU64::new(1);
        }
        FaultKind::DiskPressure | FaultKind::QueueRecordsFull | FaultKind::QueueBytesFull => {
            value.readiness = HealthReadiness::NotReady;
            value.degradation_stage = DegradationStage::StopBeforeControlReserve;
            value.open_gap_count = WireU64::new(1);
        }
        FaultKind::CoreUnavailable => {
            value.degradation_stage = DegradationStage::CensusOnly;
            value.open_gap_count = WireU64::new(1);
        }
        FaultKind::ReplicaUnavailable => {
            value.degradation_stage = DegradationStage::OptionalMediaDisabled;
            value.open_gap_count = WireU64::new(1);
        }
        FaultKind::ReplicaCorrupt => {
            value.degradation_stage = DegradationStage::OptionalMediaDisabled;
            value.recovery_state = RecoveryState::Verifying;
            value.open_gap_count = WireU64::new(1);
            value.quarantine_count = WireU64::new(1);
        }
        FaultKind::ProjectionFailure => value.prior_projection_served_stale = true,
        FaultKind::BrowserDisconnect => value.presentation_witnessed = false,
        FaultKind::ClockStep => {
            value.readiness = HealthReadiness::NotReady;
            value.degradation_stage = DegradationStage::CensusOnly;
            value.recovery_state = RecoveryState::Verifying;
            value.open_gap_count = WireU64::new(1);
        }
    }
    value
}
