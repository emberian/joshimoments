//! Executed, explicitly non-qualifying G0 fault-matrix ledger.
//!
//! Every frozen schedule row is run against a fresh offline state root. The adapter observes one
//! deterministic in-process interruption and then recovers the same state into the complete
//! eighteen-role root evidence bundle. This closes the former map-only gap, but deliberately does
//! not claim that an error injection is an OS process kill, power loss, or panic.

use crate::{
    g0_inspector_smoke::{
        G0InspectorSmokeError, run_g0_inspector_smoke, run_g0_inspector_smoke_with_fault,
    },
    g0_process_fault::arm_process_kill_marker,
    wave5_circulation::Wave5CirculationError,
    wave5_g0::{
        Wave5G0SourceChainFaultPoint, Wave5G0SourcePublicationError,
        run_wave5_g0_source_publication, run_wave5_g0_source_publication_with_chain_fault,
    },
    wave5_g0_fault_map::{G0ExecutableFaultAdapter, fault_adapter},
    wave5_g0_root_evidence::{
        Wave5G0RootEvidenceError, join_reports, recover_interrupted_original_roots,
        run_final_recovery, run_final_recovery_with_fault, run_wave5_g0_root_evidence,
    },
};
use joshi_admission::Sha256Digest;
use joshi_g0_harness::{
    CrashMode, CrashPoint, EvidenceBundle, FakeFaultSchedule, RecoveryInvariant,
};
use joshi_supervisor::SupervisorError;
use serde::Serialize;
use std::{
    collections::BTreeSet,
    fs,
    path::Path,
    process::{Child, Command, ExitStatus, Stdio},
    time::{Duration, Instant},
};
use thiserror::Error;

const CONTRACT: &str = "joshi.wave5.g0_executed_fault_ledger.v1";
const AUTHORITY: &str = "offline_fixture_in_process_fault_evidence_no_kill_qualification";
const EXECUTION_KIND: &str = "deterministic_in_process_error_injection";
const PROCESS_KILL_CONTRACT: &str = "joshi.wave5.g0_process_kill_scenario.v1";
const PROCESS_KILL_LEDGER_CONTRACT: &str = "joshi.wave5.g0_process_kill_ledger.v1";
const PROCESS_KILL_AUTHORITY: &str =
    "offline_fixture_actual_process_kill_single_scenario_no_full_walk_qualification";
const PROCESS_KILL_LEDGER_AUTHORITY: &str =
    "offline_fixture_actual_process_kill_all_mapped_boundaries_no_mixed_mode_qualification";
const PROCESS_KILL_EXECUTION_KIND: &str = "os_process_kill_at_exact_armed_fault_boundary";
const SCHEDULE_BYTES: &[u8] = include_bytes!("../../../fixtures/g0-fault/fake_fault_schedule.json");

/// One actual child-process termination at an exact mapped G0 fault boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct G0ProcessKillScenarioV1 {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub status: &'static str,
    pub schedule_id: String,
    pub schedule_digest: String,
    pub scenario_id: String,
    pub scheduled_crash_mode: CrashMode,
    pub actual_crash_mode: CrashMode,
    pub scheduled_mode_matched: bool,
    pub crash_point: CrashPoint,
    pub adapter_family: String,
    pub adapter_point: String,
    pub execution_kind: &'static str,
    pub boundary_marker_digest: String,
    pub child_terminated_without_success: bool,
    pub recovered_root_report_digest: Option<String>,
    pub recovered_evidence_bundle: Option<EvidenceBundle>,
    pub recovery_error_code: Option<&'static str>,
    pub recovery_error_digest: Option<String>,
    pub expected_invariants: Vec<RecoveryInvariant>,
    pub same_state_recovery_closed: bool,
    pub full_offline_fault_walk: bool,
    pub provider_io: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
    pub disqualifiers: Vec<&'static str>,
}

/// Baseline plus all 36 mapped boundaries executed with actual child-process termination.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct G0ProcessKillLedgerV1 {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub status: &'static str,
    pub schedule_id: String,
    pub schedule_digest: String,
    pub baseline_root_report_digest: String,
    pub baseline_evidence_bundle: EvidenceBundle,
    pub scenario_ledger_digest: String,
    pub scenarios: Vec<G0ProcessKillScenarioV1>,
    pub schedule_scenario_count: u64,
    pub process_kill_scenario_count: u64,
    pub scheduled_mode_match_count: u64,
    pub complete_evidence_bundle_count: u64,
    pub recovery_refusal_count: u64,
    pub every_mapped_boundary_process_killed: bool,
    pub every_process_kill_recovery_accounted: bool,
    pub every_process_kill_recovered_same_state: bool,
    pub mixed_scheduled_modes_fully_executed: bool,
    pub full_offline_fault_walk: bool,
    pub provider_io: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
    pub disqualifiers: Vec<&'static str>,
}

/// Arm one exact child fault boundary and wait for the parent to terminate this process.
///
/// # Errors
///
/// Refuses a baseline/unknown scenario, nonempty state, reused marker, or a fault path that
/// returns instead of parking at its exact requested boundary.
pub async fn run_wave5_g0_process_kill_child(
    state: &Path,
    scenario_id: &str,
    marker: &Path,
) -> Result<(), G0ExecutedFaultLedgerError> {
    require_empty_root(state)?;
    let expected_marker = state
        .parent()
        .ok_or(G0ExecutedFaultLedgerError::UnsafeProcessKillMarker)?
        .join("child-ready");
    if marker != expected_marker {
        return Err(G0ExecutedFaultLedgerError::UnsafeProcessKillMarker);
    }
    let schedule: FakeFaultSchedule = serde_json::from_slice(SCHEDULE_BYTES)?;
    schedule.validate()?;
    let scenario = scheduled_scenario(&schedule, scenario_id)?;
    let point = scenario
        .crash_point
        .ok_or(G0ExecutedFaultLedgerError::BaselineProcessKill)?;
    arm_process_kill_marker(marker)?;
    let adapter = fault_adapter(point);
    let _returned = execute_interruption_and_recoverable_prefix(state, adapter).await?;
    Err(G0ExecutedFaultLedgerError::MissingProcessKillPause)
}

/// Kill one child parked at an exact G0 boundary, then recover the same state to the root bundle.
///
/// The result is intentionally one-scenario evidence. Even when the frozen row requested a
/// process kill, it cannot promote the unexecuted remainder of the 37-row schedule.
///
/// # Errors
///
/// Refuses a nonempty destination, changed schedule, missing/wrong marker, early child exit,
/// timeout, unsuccessful termination, or incomplete same-state root recovery.
#[allow(clippy::too_many_lines)]
pub async fn run_wave5_g0_process_kill_scenario(
    root: &Path,
    scenario_id: &str,
) -> Result<G0ProcessKillScenarioV1, G0ExecutedFaultLedgerError> {
    require_empty_root(root)?;
    let schedule: FakeFaultSchedule = serde_json::from_slice(SCHEDULE_BYTES)?;
    schedule.validate()?;
    let schedule_digest = schedule.digest()?;
    let scenario = scheduled_scenario(&schedule, scenario_id)?;
    let point = scenario
        .crash_point
        .ok_or(G0ExecutedFaultLedgerError::BaselineProcessKill)?;
    let adapter = fault_adapter(point);
    let family = adapter_family(adapter);
    let point_name = adapter_point(adapter);
    let state = root.join("state");
    let marker = root.join("child-ready");
    let child_binary = std::env::current_exe()?;
    let mut child = KillOnDrop::new(
        Command::new(child_binary)
            .arg("wave5-g0-fault-kill-child")
            .arg("--state")
            .arg(&state)
            .arg("--scenario-id")
            .arg(scenario_id)
            .arg("--marker")
            .arg(&marker)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?,
    );
    let deadline = Instant::now() + Duration::from_mins(3);
    loop {
        if marker.try_exists()? {
            break;
        }
        if let Some(status) = child.try_wait()? {
            return Err(G0ExecutedFaultLedgerError::ChildExitedBeforeBoundary(
                status.to_string(),
            ));
        }
        if Instant::now() >= deadline {
            return Err(G0ExecutedFaultLedgerError::ProcessKillBoundaryTimeout);
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let marker_bytes = fs::read(&marker)?;
    let expected_marker = format!("{family}:{point_name}\n");
    if marker_bytes != expected_marker.as_bytes() {
        return Err(G0ExecutedFaultLedgerError::WrongProcessKillMarker);
    }
    let exit = child.kill_and_wait()?;
    if exit.success() {
        return Err(G0ExecutedFaultLedgerError::ChildExitedSuccessfully);
    }
    fs::remove_file(&marker)?;

    let recovery = recover_same_state(&state, Some(adapter)).await;
    let (
        recovered_root_report_digest,
        recovered_evidence_bundle,
        recovery_error_code,
        recovery_error_digest,
        same_state_recovery_closed,
    ) = match recovery {
        Ok(recovered) => {
            if !recovered.partial_root_evidence_closed
                || recovered.evidence_bundle.items.len() != 18
                || recovered.full_offline_fault_walk
                || recovered.browser_presented
                || recovered.product_qualified
                || recovered.live_qualified
            {
                return Err(G0ExecutedFaultLedgerError::Invariant(
                    "process-kill recovery did not retain its exact partial root ceiling",
                ));
            }
            recovered.evidence_bundle.validate()?;
            (
                Some(Sha256Digest::of_bytes(&serde_json::to_vec(&recovered)?).to_string()),
                Some(recovered.evidence_bundle),
                None,
                None,
                true,
            )
        }
        Err(error) => (
            None,
            None,
            Some("same_state_root_recovery_refused"),
            Some(Sha256Digest::of_bytes(error.to_string().as_bytes()).to_string()),
            false,
        ),
    };
    let mut disqualifiers = vec![
        "single_scenario_does_not_close_the_37_row_schedule",
        "process_kill_does_not_prove_power_loss_or_panic",
        "no_browser_presentation_occurrence",
        "offline_fixture_only",
    ];
    if !same_state_recovery_closed {
        disqualifiers.push("same_state_root_recovery_refused");
    }
    let report = G0ProcessKillScenarioV1 {
        contract: PROCESS_KILL_CONTRACT,
        schema_version: 1,
        authority: PROCESS_KILL_AUTHORITY,
        status: "useful_partial",
        schedule_id: schedule.schedule_id.clone(),
        schedule_digest,
        scenario_id: scenario.scenario_id.clone(),
        scheduled_crash_mode: scenario.crash_mode,
        actual_crash_mode: CrashMode::ProcessKill,
        scheduled_mode_matched: scenario.crash_mode == CrashMode::ProcessKill,
        crash_point: point,
        adapter_family: family.into(),
        adapter_point: point_name,
        execution_kind: PROCESS_KILL_EXECUTION_KIND,
        boundary_marker_digest: Sha256Digest::of_bytes(&marker_bytes).to_string(),
        child_terminated_without_success: true,
        recovered_root_report_digest,
        recovered_evidence_bundle,
        recovery_error_code,
        recovery_error_digest,
        expected_invariants: scenario.expected_invariants.clone(),
        same_state_recovery_closed,
        full_offline_fault_walk: false,
        provider_io: false,
        browser_presented: false,
        product_qualified: false,
        live_qualified: false,
        disqualifiers,
    };
    validate_process_kill_report(&report, &schedule, scenario, &expected_marker)?;
    Ok(report)
}

/// Execute the baseline and every mapped before/after boundary with actual child termination.
///
/// # Errors
///
/// Refuses a nonempty root, changed schedule, any missing child boundary, any unaccounted recovery
/// outcome, or any widening of process-kill evidence into power-loss/panic qualification.
#[allow(clippy::too_many_lines)] // Keep the full frozen-schedule assembly and ceiling visible.
pub async fn run_wave5_g0_process_kill_ledger(
    root: &Path,
) -> Result<G0ProcessKillLedgerV1, G0ExecutedFaultLedgerError> {
    require_empty_root(root)?;
    let schedule: FakeFaultSchedule = serde_json::from_slice(SCHEDULE_BYTES)?;
    schedule.validate()?;
    let schedule_digest = schedule.digest()?;

    let baseline = run_wave5_g0_root_evidence(&root.join("baseline_no_fault")).await?;
    if !baseline.partial_root_evidence_closed
        || baseline.evidence_bundle.items.len() != 18
        || baseline.full_offline_fault_walk
        || baseline.browser_presented
        || baseline.product_qualified
        || baseline.live_qualified
    {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "process-kill baseline did not retain its exact partial root ceiling",
        ));
    }
    baseline.evidence_bundle.validate()?;
    let baseline_root_report_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&baseline)?).to_string();
    let baseline_evidence_bundle = baseline.evidence_bundle;

    let mut scenarios = Vec::with_capacity(schedule.scenarios.len().saturating_sub(1));
    for scheduled in schedule.scenarios.iter().skip(1) {
        scenarios.push(
            run_wave5_g0_process_kill_scenario(
                &root.join(&scheduled.scenario_id),
                &scheduled.scenario_id,
            )
            .await?,
        );
    }
    let scheduled_mode_match_count = u64::try_from(
        scenarios
            .iter()
            .filter(|scenario| scenario.scheduled_mode_matched)
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("scheduled-mode count overflow"))?;
    let complete_evidence_bundle_count = u64::try_from(
        scenarios
            .iter()
            .filter(|scenario| scenario.recovered_evidence_bundle.is_some())
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("evidence count overflow"))?;
    let recovery_refusal_count = u64::try_from(
        scenarios
            .iter()
            .filter(|scenario| scenario.recovery_error_code.is_some())
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("refusal count overflow"))?;
    let every_process_kill_recovered_same_state = scenarios
        .iter()
        .all(|scenario| scenario.same_state_recovery_closed);
    let scenario_ledger_digest = Sha256Digest::of_bytes(&serde_json::to_vec(&(
        &baseline_root_report_digest,
        &baseline_evidence_bundle,
        &scenarios,
    ))?)
    .to_string();
    let report = G0ProcessKillLedgerV1 {
        contract: PROCESS_KILL_LEDGER_CONTRACT,
        schema_version: 1,
        authority: PROCESS_KILL_LEDGER_AUTHORITY,
        status: "useful_partial",
        schedule_id: schedule.schedule_id.clone(),
        schedule_digest,
        baseline_root_report_digest,
        baseline_evidence_bundle,
        scenario_ledger_digest,
        process_kill_scenario_count: u64::try_from(scenarios.len())
            .map_err(|_| G0ExecutedFaultLedgerError::Invariant("scenario count overflow"))?,
        scenarios,
        schedule_scenario_count: u64::try_from(schedule.scenarios.len())
            .map_err(|_| G0ExecutedFaultLedgerError::Invariant("schedule count overflow"))?,
        scheduled_mode_match_count,
        complete_evidence_bundle_count,
        recovery_refusal_count,
        every_mapped_boundary_process_killed: true,
        every_process_kill_recovery_accounted: true,
        every_process_kill_recovered_same_state,
        mixed_scheduled_modes_fully_executed: false,
        full_offline_fault_walk: false,
        provider_io: false,
        browser_presented: false,
        product_qualified: false,
        live_qualified: false,
        disqualifiers: {
            let mut values = vec![
                "process_kill_does_not_prove_power_loss_or_panic",
                "no_browser_presentation_occurrence",
                "offline_fixture_only",
            ];
            if !every_process_kill_recovered_same_state {
                values.push("one_or_more_same_state_root_recoveries_refused");
            }
            values
        },
    };
    validate_process_kill_ledger(&report, &schedule)?;
    Ok(report)
}

struct KillOnDrop(Option<Child>);

impl KillOnDrop {
    const fn new(child: Child) -> Self {
        Self(Some(child))
    }

    fn try_wait(&mut self) -> std::io::Result<Option<ExitStatus>> {
        let status = self
            .0
            .as_mut()
            .ok_or_else(|| std::io::Error::other("G0 child was already reaped"))?
            .try_wait()?;
        if status.is_some() {
            self.0 = None;
        }
        Ok(status)
    }

    fn kill_and_wait(&mut self) -> std::io::Result<ExitStatus> {
        let mut child = self
            .0
            .take()
            .ok_or_else(|| std::io::Error::other("G0 child was already reaped"))?;
        child.kill()?;
        child.wait()
    }
}

impl Drop for KillOnDrop {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// One frozen scenario, its observed interruption, and its same-state recovered root evidence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct G0ExecutedScenarioV1 {
    pub scenario_id: String,
    pub scheduled_crash_mode: CrashMode,
    pub crash_point: Option<CrashPoint>,
    pub adapter_family: String,
    pub adapter_point: String,
    pub execution_kind: &'static str,
    pub injected_interruption_observed: bool,
    pub injected_error_digest: Option<String>,
    pub recovered_root_report_digest: Option<String>,
    pub recovered_evidence_bundle: Option<EvidenceBundle>,
    pub recovery_error_code: Option<&'static str>,
    pub recovery_error_digest: Option<String>,
    pub expected_invariants: Vec<RecoveryInvariant>,
    pub same_state_recovery_closed: bool,
    pub root_evidence_closed: bool,
    pub full_offline_fault_walk: bool,
}

/// All 37 executed rows. The result stays false until a separate process-termination runner exists.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct G0ExecutedFaultLedgerV1 {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub status: &'static str,
    pub schedule_id: String,
    pub schedule_digest: String,
    pub scenario_ledger_digest: String,
    pub scenarios: Vec<G0ExecutedScenarioV1>,
    pub scenario_count: u64,
    pub baseline_count: u64,
    pub injected_scenario_count: u64,
    pub complete_evidence_bundle_count: u64,
    pub every_frozen_scenario_executed: bool,
    pub every_interruption_recovered_same_state: bool,
    pub full_offline_fault_walk: bool,
    pub provider_io: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
    pub disqualifiers: Vec<&'static str>,
}

/// Execute the exact baseline plus all 36 mapped before/after interruptions on fresh state roots.
///
/// # Errors
///
/// Refuses a nonempty destination, changed schedule, wrong injected error, incomplete recovery,
/// missing evidence role, or any accidental positive qualification.
#[allow(clippy::too_many_lines)]
pub async fn run_wave5_g0_executed_fault_ledger(
    root: &Path,
) -> Result<G0ExecutedFaultLedgerV1, G0ExecutedFaultLedgerError> {
    require_empty_root(root)?;
    let schedule: FakeFaultSchedule = serde_json::from_slice(SCHEDULE_BYTES)?;
    schedule.validate()?;
    let schedule_digest = schedule.digest()?;
    let mut scenarios = Vec::with_capacity(schedule.scenarios.len());

    for scheduled in &schedule.scenarios {
        let state = root.join(&scheduled.scenario_id);
        fs::create_dir(&state)?;
        let (adapter_family, adapter_point, injected_error) = match scheduled.crash_point {
            None => ("baseline", "none".to_owned(), None),
            Some(point) => {
                let adapter = fault_adapter(point);
                let family = adapter_family(adapter);
                let point_name = adapter_point(adapter);
                let error = execute_interruption_and_recoverable_prefix(&state, adapter).await?;
                (family, point_name, Some(error))
            }
        };
        let recovery = recover_same_state(&state, scheduled.crash_point.map(fault_adapter)).await;
        let (
            recovered_root_report_digest,
            recovered_evidence_bundle,
            recovery_error_code,
            recovery_error_digest,
            same_state_recovery_closed,
        ) = match recovery {
            Ok(recovered) => {
                if !recovered.partial_root_evidence_closed
                    || recovered.evidence_bundle.items.len() != 18
                    || recovered.full_offline_fault_walk
                    || recovered.browser_presented
                    || recovered.product_qualified
                    || recovered.live_qualified
                {
                    return Err(G0ExecutedFaultLedgerError::Invariant(
                        "same-state root recovery did not retain its exact partial ceiling",
                    ));
                }
                recovered.evidence_bundle.validate()?;
                (
                    Some(Sha256Digest::of_bytes(&serde_json::to_vec(&recovered)?).to_string()),
                    Some(recovered.evidence_bundle),
                    None,
                    None,
                    true,
                )
            }
            Err(error) if scheduled.crash_point.is_some() => (
                None,
                None,
                Some("same_state_root_recovery_refused"),
                Some(Sha256Digest::of_bytes(error.to_string().as_bytes()).to_string()),
                false,
            ),
            Err(error) => return Err(error),
        };
        let injected_error_digest = injected_error
            .as_deref()
            .map(|error| Sha256Digest::of_bytes(error.as_bytes()).to_string());
        scenarios.push(G0ExecutedScenarioV1 {
            scenario_id: scheduled.scenario_id.clone(),
            scheduled_crash_mode: scheduled.crash_mode,
            crash_point: scheduled.crash_point,
            adapter_family: adapter_family.into(),
            adapter_point,
            execution_kind: EXECUTION_KIND,
            injected_interruption_observed: injected_error.is_some(),
            injected_error_digest,
            recovered_root_report_digest,
            recovered_evidence_bundle,
            recovery_error_code,
            recovery_error_digest,
            expected_invariants: scheduled.expected_invariants.clone(),
            same_state_recovery_closed,
            root_evidence_closed: same_state_recovery_closed,
            full_offline_fault_walk: false,
        });
    }

    let complete_evidence_bundle_count = u64::try_from(
        scenarios
            .iter()
            .filter(|scenario| scenario.recovered_evidence_bundle.is_some())
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("evidence bundle count overflow"))?;
    let every_interruption_recovered_same_state = scenarios
        .iter()
        .skip(1)
        .all(|scenario| scenario.same_state_recovery_closed);
    let mut disqualifiers = vec![
        "scheduled_process_kill_power_loss_and_panic_modes_not_executed",
        "in_process_error_injection_is_not_process_termination",
        "no_browser_presentation_occurrence",
        "offline_fixture_only",
    ];
    if !every_interruption_recovered_same_state {
        disqualifiers.push("one_or_more_same_state_root_recoveries_refused");
    }
    let scenario_ledger_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&scenarios)?).to_string();
    let report = G0ExecutedFaultLedgerV1 {
        contract: CONTRACT,
        schema_version: 1,
        authority: AUTHORITY,
        status: "useful_partial",
        schedule_id: schedule.schedule_id.clone(),
        schedule_digest,
        scenario_ledger_digest,
        scenario_count: u64::try_from(scenarios.len())
            .map_err(|_| G0ExecutedFaultLedgerError::Invariant("scenario count overflow"))?,
        baseline_count: 1,
        injected_scenario_count: 36,
        complete_evidence_bundle_count,
        every_frozen_scenario_executed: true,
        every_interruption_recovered_same_state,
        scenarios,
        full_offline_fault_walk: false,
        provider_io: false,
        browser_presented: false,
        product_qualified: false,
        live_qualified: false,
        disqualifiers,
    };
    validate_report(&report, &schedule)?;
    Ok(report)
}

async fn execute_interruption_and_recoverable_prefix(
    state: &Path,
    adapter: G0ExecutableFaultAdapter,
) -> Result<String, G0ExecutedFaultLedgerError> {
    match adapter {
        G0ExecutableFaultAdapter::Supervisor(point) => {
            match run_wave5_g0_source_publication_with_chain_fault(
                state,
                Some(Wave5G0SourceChainFaultPoint::Supervisor(point)),
            ) {
                Err(Wave5G0SourcePublicationError::Supervisor(SupervisorError::Injected(
                    actual,
                ))) if actual == point => Ok(format!("supervisor:{actual:?}")),
                Err(error) => Err(G0ExecutedFaultLedgerError::UnexpectedInterruption(
                    error.to_string(),
                )),
                Ok(_) => Err(G0ExecutedFaultLedgerError::MissingInterruption),
            }
        }
        G0ExecutableFaultAdapter::Catalog(point) => {
            match run_wave5_g0_source_publication_with_chain_fault(
                state,
                Some(Wave5G0SourceChainFaultPoint::Catalog(point)),
            ) {
                Err(Wave5G0SourcePublicationError::Circulation(
                    Wave5CirculationError::Injected(actual),
                )) if actual == point => Ok(format!("catalog:{actual:?}")),
                Err(error) => Err(G0ExecutedFaultLedgerError::UnexpectedInterruption(
                    error.to_string(),
                )),
                Ok(_) => Err(G0ExecutedFaultLedgerError::MissingInterruption),
            }
        }
        G0ExecutableFaultAdapter::Component(point) => {
            match run_wave5_g0_source_publication_with_chain_fault(
                state,
                Some(Wave5G0SourceChainFaultPoint::Component(point)),
            ) {
                Err(Wave5G0SourcePublicationError::Injected(actual)) if actual == point => {
                    Ok(format!("component:{actual:?}"))
                }
                Err(error) => Err(G0ExecutedFaultLedgerError::UnexpectedInterruption(
                    error.to_string(),
                )),
                Ok(_) => Err(G0ExecutedFaultLedgerError::MissingInterruption),
            }
        }
        G0ExecutableFaultAdapter::Inspector(point) => {
            run_wave5_g0_source_publication(state)?;
            match run_g0_inspector_smoke_with_fault(state, Some(point)).await {
                Err(G0InspectorSmokeError::Injected(actual)) if actual == point => {
                    Ok(format!("inspector:{actual:?}"))
                }
                Err(error) => Err(G0ExecutedFaultLedgerError::UnexpectedInterruption(
                    error.to_string(),
                )),
                Ok(_) => Err(G0ExecutedFaultLedgerError::MissingInterruption),
            }
        }
        G0ExecutableFaultAdapter::FinalRecovery(point) => {
            let component = run_wave5_g0_source_publication(state)?;
            let inspector = run_g0_inspector_smoke(state).await?;
            match run_final_recovery_with_fault(state, &component, &inspector, Some(point)) {
                Err(Wave5G0RootEvidenceError::Injected(actual)) if actual == point => {
                    Ok(format!("final_recovery:{actual:?}"))
                }
                Err(error) => Err(G0ExecutedFaultLedgerError::UnexpectedInterruption(
                    error.to_string(),
                )),
                Ok(_) => Err(G0ExecutedFaultLedgerError::MissingInterruption),
            }
        }
    }
}

async fn recover_same_state(
    state: &Path,
    adapter: Option<G0ExecutableFaultAdapter>,
) -> Result<crate::wave5_g0_root_evidence::Wave5G0RootEvidenceReport, G0ExecutedFaultLedgerError> {
    match adapter {
        None
        | Some(
            G0ExecutableFaultAdapter::Supervisor(_)
            | G0ExecutableFaultAdapter::Catalog(_)
            | G0ExecutableFaultAdapter::Component(_),
        ) => Ok(run_wave5_g0_root_evidence(state).await?),
        Some(
            G0ExecutableFaultAdapter::Inspector(_) | G0ExecutableFaultAdapter::FinalRecovery(_),
        ) => {
            recover_interrupted_original_roots(state)?;
            let component = run_wave5_g0_source_publication(state)?;
            let inspector = run_g0_inspector_smoke(state).await?;
            let recovery = run_final_recovery(state, &component, &inspector)?;
            Ok(join_reports(component, inspector, recovery)?)
        }
    }
}

#[allow(clippy::too_many_lines)]
fn validate_report(
    report: &G0ExecutedFaultLedgerV1,
    schedule: &FakeFaultSchedule,
) -> Result<(), G0ExecutedFaultLedgerError> {
    if report.contract != CONTRACT
        || report.schema_version != 1
        || report.authority != AUTHORITY
        || report.status != "useful_partial"
        || report.schedule_id != schedule.schedule_id
        || report.schedule_digest != schedule.digest()?
        || report.scenario_count != 37
        || report.baseline_count != 1
        || report.injected_scenario_count != 36
        || report.complete_evidence_bundle_count == 0
        || report.complete_evidence_bundle_count > 37
        || report.scenarios.len() != schedule.scenarios.len()
        || !report.every_frozen_scenario_executed
        || report.full_offline_fault_walk
        || report.provider_io
        || report.browser_presented
        || report.product_qualified
        || report.live_qualified
        || report.disqualifiers.len() < 4
    {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "executed ledger header or hard-false ceiling changed",
        ));
    }
    let mut ids = BTreeSet::new();
    for (index, (actual, expected)) in report.scenarios.iter().zip(&schedule.scenarios).enumerate()
    {
        if actual.scenario_id != expected.scenario_id
            || actual.scheduled_crash_mode != expected.crash_mode
            || actual.crash_point != expected.crash_point
            || actual.expected_invariants != expected.expected_invariants
            || actual.execution_kind != EXECUTION_KIND
            || actual.full_offline_fault_walk
            || !ids.insert(&actual.scenario_id)
            || (index == 0
                && (actual.injected_interruption_observed
                    || actual.injected_error_digest.is_some()
                    || actual.adapter_family != "baseline"
                    || actual.adapter_point != "none"))
            || (index != 0
                && (!actual.injected_interruption_observed
                    || actual.injected_error_digest.is_none()
                    || actual.adapter_family == "baseline"))
        {
            return Err(G0ExecutedFaultLedgerError::Invariant(
                "scenario ledger differs from the frozen schedule or recovered evidence",
            ));
        }
        if actual.same_state_recovery_closed != actual.root_evidence_closed {
            return Err(G0ExecutedFaultLedgerError::Invariant(
                "same-state and root-evidence recovery flags disagree",
            ));
        }
        match (
            &actual.recovered_root_report_digest,
            &actual.recovered_evidence_bundle,
            actual.recovery_error_code,
            &actual.recovery_error_digest,
        ) {
            (Some(root_digest), Some(bundle), None, None)
                if actual.same_state_recovery_closed && bundle.items.len() == 18 =>
            {
                Sha256Digest::parse(root_digest.clone())?;
                bundle.validate()?;
            }
            (None, None, Some("same_state_root_recovery_refused"), Some(error_digest))
                if !actual.same_state_recovery_closed =>
            {
                Sha256Digest::parse(error_digest.clone())?;
            }
            _ => {
                return Err(G0ExecutedFaultLedgerError::Invariant(
                    "scenario recovery evidence and refusal fields do not form an exact partition",
                ));
            }
        }
        if let Some(digest) = &actual.injected_error_digest {
            Sha256Digest::parse(digest.clone())?;
        }
    }
    let recomputed_complete = u64::try_from(
        report
            .scenarios
            .iter()
            .filter(|scenario| scenario.recovered_evidence_bundle.is_some())
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("evidence bundle count overflow"))?;
    let recomputed_all_recovered = report
        .scenarios
        .iter()
        .skip(1)
        .all(|scenario| scenario.same_state_recovery_closed);
    if report.complete_evidence_bundle_count != recomputed_complete
        || report.every_interruption_recovered_same_state != recomputed_all_recovered
    {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "aggregate recovery counts differ from the exact scenario ledger",
        ));
    }
    let expected_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&report.scenarios)?).to_string();
    if report.scenario_ledger_digest != expected_digest {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "scenario ledger digest differs from the exact scenario array",
        ));
    }
    Ok(())
}

fn validate_process_kill_report(
    report: &G0ProcessKillScenarioV1,
    schedule: &FakeFaultSchedule,
    scenario: &joshi_g0_harness::FaultScenario,
    marker: &str,
) -> Result<(), G0ExecutedFaultLedgerError> {
    let mut expected_disqualifiers = vec![
        "single_scenario_does_not_close_the_37_row_schedule",
        "process_kill_does_not_prove_power_loss_or_panic",
        "no_browser_presentation_occurrence",
        "offline_fixture_only",
    ];
    if !report.same_state_recovery_closed {
        expected_disqualifiers.push("same_state_root_recovery_refused");
    }
    if report.contract != PROCESS_KILL_CONTRACT
        || report.schema_version != 1
        || report.authority != PROCESS_KILL_AUTHORITY
        || report.status != "useful_partial"
        || report.schedule_id != schedule.schedule_id
        || report.schedule_digest != schedule.digest()?
        || report.scenario_id != scenario.scenario_id
        || report.scheduled_crash_mode != scenario.crash_mode
        || report.actual_crash_mode != CrashMode::ProcessKill
        || report.scheduled_mode_matched != (scenario.crash_mode == CrashMode::ProcessKill)
        || Some(report.crash_point) != scenario.crash_point
        || report.execution_kind != PROCESS_KILL_EXECUTION_KIND
        || report.boundary_marker_digest != Sha256Digest::of_bytes(marker.as_bytes()).to_string()
        || !report.child_terminated_without_success
        || report.expected_invariants != scenario.expected_invariants
        || report.full_offline_fault_walk
        || report.provider_io
        || report.browser_presented
        || report.product_qualified
        || report.live_qualified
        || report.disqualifiers != expected_disqualifiers
    {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "process-kill scenario report changed or widened its authority",
        ));
    }
    Sha256Digest::parse(report.schedule_digest.clone())?;
    Sha256Digest::parse(report.boundary_marker_digest.clone())?;
    match (
        &report.recovered_root_report_digest,
        &report.recovered_evidence_bundle,
        report.recovery_error_code,
        &report.recovery_error_digest,
    ) {
        (Some(root_digest), Some(bundle), None, None) if report.same_state_recovery_closed => {
            Sha256Digest::parse(root_digest.clone())?;
            bundle.validate()?;
            if bundle.items.len() != 18 {
                return Err(G0ExecutedFaultLedgerError::Invariant(
                    "closed process-kill recovery has incomplete evidence",
                ));
            }
        }
        (None, None, Some("same_state_root_recovery_refused"), Some(error_digest))
            if !report.same_state_recovery_closed =>
        {
            Sha256Digest::parse(error_digest.clone())?;
        }
        _ => {
            return Err(G0ExecutedFaultLedgerError::Invariant(
                "process-kill recovery evidence and refusal do not partition exactly",
            ));
        }
    }
    Ok(())
}

fn validate_process_kill_ledger(
    report: &G0ProcessKillLedgerV1,
    schedule: &FakeFaultSchedule,
) -> Result<(), G0ExecutedFaultLedgerError> {
    let mut expected_disqualifiers = vec![
        "process_kill_does_not_prove_power_loss_or_panic",
        "no_browser_presentation_occurrence",
        "offline_fixture_only",
    ];
    if !report.every_process_kill_recovered_same_state {
        expected_disqualifiers.push("one_or_more_same_state_root_recoveries_refused");
    }
    if report.contract != PROCESS_KILL_LEDGER_CONTRACT
        || report.schema_version != 1
        || report.authority != PROCESS_KILL_LEDGER_AUTHORITY
        || report.status != "useful_partial"
        || report.schedule_id != schedule.schedule_id
        || report.schedule_digest != schedule.digest()?
        || report.schedule_scenario_count != 37
        || report.process_kill_scenario_count != 36
        || report.scenarios.len() != 36
        || report.scheduled_mode_match_count != 12
        || report.complete_evidence_bundle_count + report.recovery_refusal_count != 36
        || !report.every_mapped_boundary_process_killed
        || !report.every_process_kill_recovery_accounted
        || report.mixed_scheduled_modes_fully_executed
        || report.full_offline_fault_walk
        || report.provider_io
        || report.browser_presented
        || report.product_qualified
        || report.live_qualified
        || report.disqualifiers != expected_disqualifiers
        || report.baseline_evidence_bundle.items.len() != 18
    {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "process-kill ledger changed or widened its authority",
        ));
    }
    Sha256Digest::parse(report.baseline_root_report_digest.clone())?;
    Sha256Digest::parse(report.scenario_ledger_digest.clone())?;
    report.baseline_evidence_bundle.validate()?;
    for (actual, expected) in report
        .scenarios
        .iter()
        .zip(schedule.scenarios.iter().skip(1))
    {
        let marker = format!("{}:{}\n", actual.adapter_family, actual.adapter_point);
        validate_process_kill_report(actual, schedule, expected, &marker)?;
    }
    let recomputed_matches = u64::try_from(
        report
            .scenarios
            .iter()
            .filter(|scenario| scenario.scheduled_mode_matched)
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("scheduled-mode count overflow"))?;
    let recomputed_complete = u64::try_from(
        report
            .scenarios
            .iter()
            .filter(|scenario| scenario.recovered_evidence_bundle.is_some())
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("evidence count overflow"))?;
    let recomputed_refused = u64::try_from(
        report
            .scenarios
            .iter()
            .filter(|scenario| scenario.recovery_error_code.is_some())
            .count(),
    )
    .map_err(|_| G0ExecutedFaultLedgerError::Invariant("refusal count overflow"))?;
    let recomputed_all_recovered = report
        .scenarios
        .iter()
        .all(|scenario| scenario.same_state_recovery_closed);
    let recomputed_digest = Sha256Digest::of_bytes(&serde_json::to_vec(&(
        &report.baseline_root_report_digest,
        &report.baseline_evidence_bundle,
        &report.scenarios,
    ))?)
    .to_string();
    if recomputed_matches != report.scheduled_mode_match_count
        || recomputed_complete != report.complete_evidence_bundle_count
        || recomputed_refused != report.recovery_refusal_count
        || recomputed_all_recovered != report.every_process_kill_recovered_same_state
        || recomputed_digest != report.scenario_ledger_digest
    {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "process-kill ledger aggregates differ from exact scenario evidence",
        ));
    }
    Ok(())
}

fn scheduled_scenario<'a>(
    schedule: &'a FakeFaultSchedule,
    scenario_id: &str,
) -> Result<&'a joshi_g0_harness::FaultScenario, G0ExecutedFaultLedgerError> {
    schedule
        .scenarios
        .iter()
        .find(|scenario| scenario.scenario_id == scenario_id)
        .ok_or_else(|| G0ExecutedFaultLedgerError::UnknownScenario(scenario_id.to_owned()))
}

fn require_empty_root(root: &Path) -> Result<(), G0ExecutedFaultLedgerError> {
    fs::create_dir_all(root)?;
    if fs::read_dir(root)?.next().transpose()?.is_some() {
        return Err(G0ExecutedFaultLedgerError::Invariant(
            "fault-ledger root must be empty",
        ));
    }
    Ok(())
}

const fn adapter_family(adapter: G0ExecutableFaultAdapter) -> &'static str {
    match adapter {
        G0ExecutableFaultAdapter::Supervisor(_) => "supervisor",
        G0ExecutableFaultAdapter::Catalog(_) => "catalog",
        G0ExecutableFaultAdapter::Component(_) => "component",
        G0ExecutableFaultAdapter::Inspector(_) => "inspector",
        G0ExecutableFaultAdapter::FinalRecovery(_) => "final_recovery",
    }
}

fn adapter_point(adapter: G0ExecutableFaultAdapter) -> String {
    match adapter {
        G0ExecutableFaultAdapter::Supervisor(point) => format!("{point:?}"),
        G0ExecutableFaultAdapter::Catalog(point) => format!("{point:?}"),
        G0ExecutableFaultAdapter::Component(point) => format!("{point:?}"),
        G0ExecutableFaultAdapter::Inspector(point) => format!("{point:?}"),
        G0ExecutableFaultAdapter::FinalRecovery(point) => format!("{point:?}"),
    }
}

#[derive(Debug, Error)]
pub enum G0ExecutedFaultLedgerError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Harness(#[from] joshi_g0_harness::HarnessError),
    #[error(transparent)]
    Digest(#[from] joshi_admission::DigestError),
    #[error(transparent)]
    Component(#[from] Wave5G0SourcePublicationError),
    #[error(transparent)]
    Inspector(#[from] G0InspectorSmokeError),
    #[error(transparent)]
    Root(#[from] Wave5G0RootEvidenceError),
    #[error("expected deterministic G0 interruption was not observed")]
    MissingInterruption,
    #[error("unexpected G0 interruption result: {0}")]
    UnexpectedInterruption(String),
    #[error("unknown frozen G0 fault scenario: {0}")]
    UnknownScenario(String),
    #[error("the baseline has no process-kill boundary")]
    BaselineProcessKill,
    #[error("G0 child returned instead of parking at the process-kill boundary")]
    MissingProcessKillPause,
    #[error("G0 child exited before publishing its process-kill boundary: {0}")]
    ChildExitedBeforeBoundary(String),
    #[error("timed out waiting for the G0 child process-kill boundary")]
    ProcessKillBoundaryTimeout,
    #[error("G0 child published a different process-kill boundary")]
    WrongProcessKillMarker,
    #[error("G0 child marker must be the fixed sibling of its isolated state root")]
    UnsafeProcessKillMarker,
    #[error("G0 child unexpectedly exited successfully after process termination")]
    ChildExitedSuccessfully,
    #[error("G0 executed fault-ledger invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checked_schedule_and_adapter_map_remain_exact() {
        let schedule: FakeFaultSchedule =
            serde_json::from_slice(SCHEDULE_BYTES).expect("checked schedule");
        schedule.validate().expect("valid schedule");
        assert_eq!(schedule.scenarios.len(), 37);
        assert_eq!(
            schedule
                .scenarios
                .iter()
                .skip(1)
                .map(|scenario| adapter_family(fault_adapter(scenario.crash_point.unwrap())))
                .collect::<Vec<_>>()
                .len(),
            36
        );
    }

    #[tokio::test]
    #[ignore = "executes all 37 expensive fresh-state G0 recovery scenarios"]
    async fn executes_every_frozen_scenario_without_promoting_process_loss() {
        let root = tempfile::tempdir().expect("temporary fault-ledger root");
        let state = root.path().join("matrix");
        let report = run_wave5_g0_executed_fault_ledger(&state)
            .await
            .expect("executed matrix");
        assert_eq!(report.scenario_count, 37);
        assert!(report.complete_evidence_bundle_count >= 1);
        assert!(report.every_frozen_scenario_executed);
        assert!(!report.full_offline_fault_walk);
    }
}
