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
    wave5_circulation::Wave5CirculationError,
    wave5_g0::{
        Wave5G0SourceChainFaultPoint, Wave5G0SourcePublicationError,
        run_wave5_g0_source_publication, run_wave5_g0_source_publication_with_chain_fault,
    },
    wave5_g0_fault_map::{G0ExecutableFaultAdapter, fault_adapter},
    wave5_g0_root_evidence::{
        Wave5G0RootEvidenceError, join_reports, run_final_recovery, run_final_recovery_with_fault,
        run_wave5_g0_root_evidence,
    },
};
use joshi_admission::Sha256Digest;
use joshi_g0_harness::{
    CrashMode, CrashPoint, EvidenceBundle, FakeFaultSchedule, RecoveryInvariant,
};
use joshi_supervisor::SupervisorError;
use serde::Serialize;
use std::{collections::BTreeSet, fs, path::Path};
use thiserror::Error;

const CONTRACT: &str = "joshi.wave5.g0_executed_fault_ledger.v1";
const AUTHORITY: &str = "offline_fixture_in_process_fault_evidence_no_kill_qualification";
const EXECUTION_KIND: &str = "deterministic_in_process_error_injection";
const SCHEDULE_BYTES: &[u8] = include_bytes!("../../../fixtures/g0-fault/fake_fault_schedule.json");

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
