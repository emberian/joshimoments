mod support;

use joshi_supervisor::{FakeProviderSchedule, Supervisor, replay_spool};
use serde::Deserialize;
use std::{fs, process::Command, thread, time::Duration};
use tempfile::TempDir;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Matrix {
    contract: String,
    process_kills: Vec<KillCase>,
    failpoints: Vec<String>,
}

#[derive(Deserialize)]
struct KillCase {
    phase: String,
    expected: String,
}

#[test]
fn real_process_kills_repeat_without_skipping_or_false_cursor_progress() {
    let matrix: Matrix = serde_json::from_str(include_str!(
        "../../../fixtures/supervisor/kill_failpoint_matrix.json"
    ))
    .unwrap();
    assert_eq!(matrix.contract, "joshi.supervisor.kill_failpoint_matrix.v1");
    assert_eq!(matrix.failpoints.len(), 4);
    assert!(
        matrix
            .process_kills
            .iter()
            .all(|case| !case.expected.is_empty())
    );

    for case in matrix.process_kills {
        let root = TempDir::new().unwrap();
        let binary = env!("CARGO_BIN_EXE_joshi-supervisor-kill-child");
        let mut child = Command::new(binary)
            .arg(root.path())
            .arg(&case.phase)
            .spawn()
            .unwrap();
        let marker = root.path().join("child-ready");
        for _ in 0..500 {
            if marker.exists() {
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        assert!(marker.exists(), "child never reached {}", case.phase);
        child.kill().unwrap();
        child.wait().unwrap();
        fs::remove_file(marker).unwrap();

        let mut recovered = Supervisor::open(support::config(root.path())).unwrap();
        recovered.reconcile_startup(support::at()).unwrap();
        let replay = replay_spool(recovered.spool(), &std::collections::BTreeMap::new()).unwrap();
        match case.phase.as_str() {
            "reserved_before_io" | "queued_before_spool" => {
                assert_eq!(replay.evidence_batches, 0);
                assert_eq!(replay.control_entries, 1);
            }
            "locally_durable" => {
                assert_eq!(replay.evidence_batches, 1);
                assert_eq!(replay.control_entries, 0);
            }
            other => panic!("unknown fixture phase {other}"),
        }
        assert!(
            recovered
                .health()
                .unwrap()
                .sources
                .iter()
                .all(|source| { source.pending_reservations == 0 })
        );
    }
}

#[test]
fn checked_in_24h_fixture_is_strict_and_accelerated() {
    let schedule: FakeProviderSchedule = serde_json::from_str(include_str!(
        "../../../fixtures/supervisor/fake_provider_24h.json"
    ))
    .unwrap();
    assert_eq!(schedule.duration_seconds, 86_400);
    assert!(!schedule.realtime);
    schedule.validate().unwrap();
}
