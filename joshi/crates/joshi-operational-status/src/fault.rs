use crate::pressure::{DrainAssessment, RecoveryDrainWindowV1, assess_recovery_drain};
use crate::{DegradationStage, HealthReadiness, OperationalError, RecoveryState, Result};
use joshi_domain::{StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

/// Deterministic fault scenario fixture contract.
pub const FAULT_SCENARIO_CONTRACT: &str = "joshi.operational.fault_scenario/v1";
const MAX_FAULT_STEPS: usize = 128;

/// Required Wave 4 fault classes; error text and subject identity are deliberately absent.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FaultKind {
    SourceDisconnect,
    RateLimited,
    AuthenticationRejected,
    MalformedData,
    SchemaDrift,
    DiskPressure,
    QueueRecordsFull,
    QueueBytesFull,
    CoreUnavailable,
    ReplicaUnavailable,
    ReplicaCorrupt,
    ProjectionFailure,
    BrowserDisconnect,
    ClockStep,
}

/// Harness input. Inject and clear are state transitions; drain is a declared recovery interval.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "action",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum FaultActionV1 {
    Inject {
        fault: FaultKind,
        added_backlog_records: WireU64,
        added_backlog_bytes: WireU64,
    },
    Clear {
        fault: FaultKind,
    },
    Drain {
        window: RecoveryDrainWindowV1,
        minimum_drain_to_arrival_ppm: WireU64,
    },
    Verify {},
}

/// State asserted after each fixture step.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FaultExpectationV1 {
    pub readiness: HealthReadiness,
    pub degradation_stage: DegradationStage,
    pub recovery_state: RecoveryState,
    pub open_gap_count: WireU64,
    pub quarantine_count: WireU64,
    pub backlog_records: WireU64,
    pub backlog_bytes: WireU64,
    pub prior_projection_served_stale: bool,
    pub presentation_witnessed: bool,
    pub source_restart_permitted: bool,
}

/// Mutable harness state serialized in the final report.
#[allow(clippy::struct_excessive_bools)] // Independent safety witnesses stay explicit on the wire.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FaultHarnessStateV1 {
    pub readiness: HealthReadiness,
    pub degradation_stage: DegradationStage,
    pub recovery_state: RecoveryState,
    pub open_gap_count: WireU64,
    pub quarantine_count: WireU64,
    pub backlog_records: WireU64,
    pub backlog_bytes: WireU64,
    pub prior_projection_served_stale: bool,
    pub presentation_witnessed: bool,
    pub source_restart_permitted: bool,
    /// Always false. Diagnostics cannot be promoted into durable evidence by this harness.
    pub logs_used_as_evidence: bool,
}

impl FaultHarnessStateV1 {
    fn expectation(&self) -> FaultExpectationV1 {
        FaultExpectationV1 {
            readiness: self.readiness,
            degradation_stage: self.degradation_stage,
            recovery_state: self.recovery_state,
            open_gap_count: self.open_gap_count,
            quarantine_count: self.quarantine_count,
            backlog_records: self.backlog_records,
            backlog_bytes: self.backlog_bytes,
            prior_projection_served_stale: self.prior_projection_served_stale,
            presentation_witnessed: self.presentation_witnessed,
            source_restart_permitted: self.source_restart_permitted,
        }
    }
}

/// One ordered fault transition and its declared expected state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FaultStepV1 {
    pub at: UtcTimestamp,
    pub input: FaultActionV1,
    pub expected: FaultExpectationV1,
}

/// Fixture-driven fault scenario.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FaultScenarioV1 {
    pub contract: String,
    pub scenario_id: StableString,
    pub initial: FaultHarnessStateV1,
    pub steps: Vec<FaultStepV1>,
}

/// Deterministic report retaining every intermediate state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FaultHarnessReportV1 {
    pub scenario_id: StableString,
    pub passed_steps: WireU64,
    pub states: Vec<FaultHarnessStateV1>,
}

/// Runs a no-I/O deterministic fault scenario.
///
/// # Errors
///
/// Refuses duplicated/unknown fault transitions, invalid drain accounting, logs-as-evidence, or
/// any mismatch between the declared and computed state.
pub fn run_fault_scenario(scenario: &FaultScenarioV1) -> Result<FaultHarnessReportV1> {
    if scenario.contract != FAULT_SCENARIO_CONTRACT {
        return Err(OperationalError::Contract {
            expected: FAULT_SCENARIO_CONTRACT,
            received: scenario.contract.clone(),
        });
    }
    if scenario.steps.is_empty() || scenario.steps.len() > MAX_FAULT_STEPS {
        return Err(OperationalError::BoundExceeded {
            field: "faultSteps",
            maximum: u64::try_from(MAX_FAULT_STEPS).unwrap_or(u64::MAX),
        });
    }
    if scenario
        .steps
        .windows(2)
        .any(|pair| pair[0].at >= pair[1].at)
    {
        return Err(OperationalError::Invalid(
            "fault steps must use strictly increasing wall times",
        ));
    }
    if scenario.initial.logs_used_as_evidence {
        return Err(OperationalError::Invalid(
            "logs cannot initialize evidence state",
        ));
    }
    let mut state = scenario.initial.clone();
    let mut active = BTreeSet::new();
    let mut states = Vec::with_capacity(scenario.steps.len());
    for (index, step) in scenario.steps.iter().enumerate() {
        apply(&mut state, &mut active, &step.input)?;
        if state.expectation() != step.expected {
            return Err(OperationalError::FaultExpectation {
                step: index,
                field: "computed state differs from fixture expectation",
            });
        }
        if state.logs_used_as_evidence {
            return Err(OperationalError::Invalid(
                "fault harness cannot derive truth from logs",
            ));
        }
        states.push(state.clone());
    }
    Ok(FaultHarnessReportV1 {
        scenario_id: scenario.scenario_id.clone(),
        passed_steps: WireU64::new(u64::try_from(states.len()).unwrap_or(u64::MAX)),
        states,
    })
}

fn apply(
    state: &mut FaultHarnessStateV1,
    active: &mut BTreeSet<FaultKind>,
    input: &FaultActionV1,
) -> Result<()> {
    match input {
        FaultActionV1::Inject {
            fault,
            added_backlog_records,
            added_backlog_bytes,
        } => {
            if !active.insert(*fault) {
                return Err(OperationalError::Invalid(
                    "fault cannot be injected twice without clearing",
                ));
            }
            state.backlog_records = WireU64::new(
                state
                    .backlog_records
                    .get()
                    .checked_add(added_backlog_records.get())
                    .ok_or(OperationalError::Invalid("fault backlog records overflow"))?,
            );
            state.backlog_bytes = WireU64::new(
                state
                    .backlog_bytes
                    .get()
                    .checked_add(added_backlog_bytes.get())
                    .ok_or(OperationalError::Invalid("fault backlog bytes overflow"))?,
            );
            inject(state, *fault)?;
        }
        FaultActionV1::Clear { fault } => {
            if !active.remove(fault) {
                return Err(OperationalError::Invalid(
                    "fault cannot clear before it is active",
                ));
            }
            state.recovery_state =
                if state.backlog_records.get() > 0 || state.backlog_bytes.get() > 0 {
                    RecoveryState::Draining
                } else {
                    RecoveryState::Verifying
                };
        }
        FaultActionV1::Drain {
            window,
            minimum_drain_to_arrival_ppm,
        } => {
            if state.recovery_state != RecoveryState::Draining
                || state.backlog_records != window.backlog_start_records
                || state.backlog_bytes != window.backlog_start_bytes
            {
                return Err(OperationalError::Invalid(
                    "drain window must start from the active declared recovery backlog",
                ));
            }
            let assessment = assess_recovery_drain(window, *minimum_drain_to_arrival_ppm)?;
            state.backlog_records = window.backlog_end_records;
            state.backlog_bytes = window.backlog_end_bytes;
            state.recovery_state = match assessment {
                DrainAssessment::MeetsTarget
                    if state.backlog_records.get() == 0 && state.backlog_bytes.get() == 0 =>
                {
                    RecoveryState::Verifying
                }
                DrainAssessment::MeetsTarget | DrainAssessment::BelowTarget => {
                    RecoveryState::Draining
                }
                DrainAssessment::NotApplicableNoBacklog => {
                    return Err(OperationalError::Invalid(
                        "fault recovery drain cannot use an empty starting backlog",
                    ));
                }
            };
        }
        FaultActionV1::Verify {} => {
            if !active.is_empty()
                || state.backlog_records.get() != 0
                || state.backlog_bytes.get() != 0
                || state.recovery_state != RecoveryState::Verifying
            {
                return Err(OperationalError::Invalid(
                    "recovery verification requires cleared faults and empty backlog",
                ));
            }
            state.readiness = HealthReadiness::Ready;
            state.degradation_stage = DegradationStage::FullFidelity;
            state.recovery_state = RecoveryState::Recovered;
            state.source_restart_permitted = true;
            state.prior_projection_served_stale = false;
            state.presentation_witnessed = true;
        }
    }
    Ok(())
}

fn inject(state: &mut FaultHarnessStateV1, fault: FaultKind) -> Result<()> {
    state.source_restart_permitted = false;
    state.recovery_state = RecoveryState::Pending;
    match fault {
        FaultKind::SourceDisconnect
        | FaultKind::RateLimited
        | FaultKind::AuthenticationRejected => {
            state.readiness = HealthReadiness::Degraded;
            state.degradation_stage = DegradationStage::SocialRefreshSlowed;
            increment(&mut state.open_gap_count, "fault open-gap count overflow")?;
        }
        FaultKind::MalformedData | FaultKind::SchemaDrift => {
            state.readiness = HealthReadiness::Degraded;
            state.degradation_stage = DegradationStage::OptionalMediaDisabled;
            increment(&mut state.open_gap_count, "fault open-gap count overflow")?;
            increment(
                &mut state.quarantine_count,
                "fault quarantine count overflow",
            )?;
        }
        FaultKind::DiskPressure | FaultKind::QueueRecordsFull | FaultKind::QueueBytesFull => {
            state.readiness = HealthReadiness::NotReady;
            state.degradation_stage = DegradationStage::StopBeforeControlReserve;
            increment(&mut state.open_gap_count, "fault open-gap count overflow")?;
        }
        FaultKind::CoreUnavailable => {
            state.readiness = HealthReadiness::Degraded;
            state.degradation_stage = DegradationStage::CensusOnly;
            increment(&mut state.open_gap_count, "fault open-gap count overflow")?;
        }
        FaultKind::ReplicaUnavailable => {
            state.readiness = HealthReadiness::Degraded;
            state.degradation_stage = DegradationStage::OptionalMediaDisabled;
            increment(&mut state.open_gap_count, "fault open-gap count overflow")?;
        }
        FaultKind::ReplicaCorrupt => {
            state.readiness = HealthReadiness::Degraded;
            state.degradation_stage = DegradationStage::OptionalMediaDisabled;
            state.recovery_state = RecoveryState::Verifying;
            increment(&mut state.open_gap_count, "fault open-gap count overflow")?;
            increment(
                &mut state.quarantine_count,
                "fault quarantine count overflow",
            )?;
        }
        FaultKind::ProjectionFailure => {
            state.readiness = HealthReadiness::Degraded;
            state.degradation_stage = DegradationStage::FullFidelity;
            state.prior_projection_served_stale = true;
        }
        FaultKind::BrowserDisconnect => {
            state.readiness = HealthReadiness::Degraded;
            state.degradation_stage = DegradationStage::FullFidelity;
            state.presentation_witnessed = false;
        }
        FaultKind::ClockStep => {
            state.readiness = HealthReadiness::NotReady;
            state.degradation_stage = DegradationStage::CensusOnly;
            state.recovery_state = RecoveryState::Verifying;
            increment(&mut state.open_gap_count, "fault open-gap count overflow")?;
        }
    }
    Ok(())
}

fn increment(value: &mut WireU64, message: &'static str) -> Result<()> {
    *value = WireU64::new(
        value
            .get()
            .checked_add(1)
            .ok_or(OperationalError::Invalid(message))?,
    );
    Ok(())
}
