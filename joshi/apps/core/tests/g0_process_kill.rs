use serde_json::Value;
use std::process::Command;

fn run_scenario(state: &std::path::Path, scenario_id: &str) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_joshi-core"))
        .arg("wave5-g0-process-kill-scenario")
        .arg("--state")
        .arg(state)
        .arg("--scenario-id")
        .arg(scenario_id)
        .output()
        .expect("run process-kill parent");
    assert!(
        output.status.success(),
        "process-kill parent failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("process-kill JSON report")
}

fn run_panic_scenario(state: &std::path::Path, scenario_id: &str) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_joshi-core"))
        .arg("wave5-g0-panic-scenario")
        .arg("--state")
        .arg(state)
        .arg("--scenario-id")
        .arg(scenario_id)
        .output()
        .expect("run panic parent");
    assert!(
        output.status.success(),
        "panic parent failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("panic JSON report")
}

#[test]
fn actual_child_kill_before_reservation_recovers_the_same_root() {
    let root = tempfile::tempdir().expect("temporary process-kill root");
    let state = root.path().join("scenario");
    let report = run_scenario(&state, "01_before_pre_io_reservation");

    assert_eq!(report["scheduledCrashMode"], "process_kill");
    assert_eq!(report["actualCrashMode"], "process_kill");
    assert_eq!(report["scheduledModeMatched"], true);
    assert_eq!(report["crashPoint"], "before_pre_io_reservation");
    assert_eq!(report["childTerminatedWithoutSuccess"], true);
    assert_eq!(report["sameStateRecoveryClosed"], true);
    assert_eq!(
        report["recoveredEvidenceBundle"]["items"]
            .as_array()
            .expect("evidence items")
            .len(),
        18
    );
    assert_eq!(report["fullOfflineFaultWalk"], false);
    assert_eq!(report["providerIo"], false);
    assert_eq!(report["productQualified"], false);
    assert_eq!(report["liveQualified"], false);
}

#[test]
fn actual_child_panic_before_store_receipt_recovers_the_same_root() {
    let root = tempfile::tempdir().expect("temporary panic root");
    let state = root.path().join("scenario");
    let report = run_panic_scenario(&state, "03_before_store_receipt");

    assert_eq!(report["scheduledCrashMode"], "panic");
    assert_eq!(report["actualCrashMode"], "panic");
    assert_eq!(report["scheduledModeMatched"], true);
    assert_eq!(report["crashPoint"], "before_store_receipt");
    assert_eq!(
        report["executionKind"],
        "rust_panic_at_exact_durably_marked_fault_boundary"
    );
    assert_eq!(report["childTerminatedWithoutSuccess"], true);
    assert_eq!(report["sameStateRecoveryClosed"], true);
    assert_eq!(
        report["recoveredEvidenceBundle"]["items"]
            .as_array()
            .expect("evidence items")
            .len(),
        18
    );
    assert_eq!(report["fullOfflineFaultWalk"], false);
    assert_eq!(report["providerIo"], false);
    assert_eq!(report["productQualified"], false);
    assert_eq!(report["liveQualified"], false);
}

#[test]
fn panic_runner_refuses_a_nonpanic_schedule_row() {
    let root = tempfile::tempdir().expect("temporary mismatched panic root");
    let state = root.path().join("scenario");
    let output = Command::new(env!("CARGO_BIN_EXE_joshi-core"))
        .arg("wave5-g0-panic-scenario")
        .arg("--state")
        .arg(&state)
        .arg("--scenario-id")
        .arg("01_before_pre_io_reservation")
        .output()
        .expect("run mismatched panic parent");
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("ScheduledCrashModeMismatch"));
}

#[test]
#[ignore = "runs five full root recoveries to exercise every process-kill adapter family"]
fn actual_child_kill_reaches_every_adapter_family() {
    for (scenario_id, expected_family) in [
        ("01_before_pre_io_reservation", "supervisor"),
        ("04_before_catalog_binding", "catalog"),
        ("07_before_publication_prepare", "component"),
        ("10_before_glass_read", "inspector"),
        ("16_before_backup", "final_recovery"),
    ] {
        let root = tempfile::tempdir().expect("temporary adapter-family root");
        let report = run_scenario(&root.path().join("scenario"), scenario_id);
        assert_eq!(report["adapterFamily"], expected_family);
        assert_eq!(report["scheduledModeMatched"], true);
        assert_eq!(report["sameStateRecoveryClosed"], true);
        assert_eq!(report["fullOfflineFaultWalk"], false);
    }
}
