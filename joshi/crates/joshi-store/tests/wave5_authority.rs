use joshi_domain::{StableString, UtcTimestamp};
use joshi_operational_status::DurableProgressState;
use joshi_store::{
    IdempotencyStatus, SqliteStore, StoreConfig, StoreMode, Wave5CommitContext,
    Wave5OperationalRecordKind, Wave5OperationalRecordV1, Wave5OperationalState,
    Wave5RunRegistrationByteBundle,
};
use serde::Serialize;
use sha2::{Digest as _, Sha256};
use std::{str::FromStr, time::Duration};
use tempfile::TempDir;

const AUTHORITY: &str = "read_only_no_execution";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ExactClosure {
    digest: String,
    byte_length: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ExactDocument<'a> {
    document_id: &'a str,
    exact_bytes: ExactClosure,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunRegistration<'a> {
    contract: &'a str,
    schema_version: u64,
    run_id: &'a str,
    build: ExactDocument<'a>,
    source_tree: ExactDocument<'a>,
    configuration: ExactDocument<'a>,
    budget: ExactDocument<'a>,
    privacy: ExactDocument<'a>,
    daily_use_surface_profile: ExactDocument<'a>,
    authority: &'a str,
}

fn timestamp(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("exact timestamp")
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable string")
}

fn digest(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

fn document<'a>(id: &'a str, bytes: &[u8]) -> ExactDocument<'a> {
    ExactDocument {
        document_id: id,
        exact_bytes: ExactClosure {
            digest: digest(bytes),
            byte_length: bytes.len().to_string(),
        },
    }
}

fn context(store: &SqliteStore, id: &str) -> Wave5CommitContext {
    store
        .begin_wave5_commit(stable(id), stable("build:test"))
        .expect("store-owned commit context")
}

fn store() -> (TempDir, SqliteStore) {
    let root = TempDir::new().expect("temporary root");
    let mut store = SqliteStore::open(
        StoreConfig {
            catalog_path: root.path().join("catalog.sqlite"),
            blob_root: root.path().join("blobs"),
            export_root: root.path().join("exports"),
            inline_blob_max_bytes: 1_024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: stable("catalog:test"),
            max_observations_per_batch: 64,
            max_raw_bytes_per_batch: 4 * 1024 * 1024,
        },
        StoreMode::SingleWriter,
    )
    .expect("open store");
    let report = store
        .migrate(timestamp("2026-08-18T00:00:00.000000Z"))
        .expect("migrate");
    assert_eq!(report.current, 9);
    (root, store)
}

#[test]
#[allow(clippy::too_many_lines)]
fn exact_run_bytes_are_durable_idempotent_and_required_by_operational_records() {
    let (_root, mut store) = store();
    let source_tree = format!(
        r#"{{"contract":"joshi.wave5.source_tree_manifest","schemaVersion":1,"repositoryId":"joshi","head":{{"kind":"commit","object_id":"{}"}},"dirty":false,"workingTreeDigest":"{}","diffDigest":null,"authority":"{}"}}"#,
        "1".repeat(40),
        digest(b"working-tree"),
        AUTHORITY
    )
    .into_bytes();
    let build = format!(
        r#"{{"contract":"joshi.wave5.build_manifest","schemaVersion":1,"buildId":"build:test","sourceTreeDigest":"{}","rustcVersion":"rustc-test","targetTriple":"test-target","profile":"local_debug","authority":"{}"}}"#,
        digest(&source_tree),
        AUTHORITY
    )
    .into_bytes();
    let configuration = format!(
        r#"{{"contract":"joshi.collector.runtime_config.v1","schemaVersion":1,"planId":"plan:test","planTemplateDigest":"{}","statusEndpoint":{{"address":"127.0.0.1","port":8123}},"providerExecution":"offline_fixture_only","authority":"{}"}}"#,
        digest(b"plan-template"),
        AUTHORITY
    )
    .into_bytes();
    let budget = format!(
        r#"{{"contract":"joshi.collector.execution_accounting.v1","schemaVersion":1,"limits":{{"maximumRequests":2,"maximumPages":1,"maximumIngressBytes":4096,"maximumDurableBytes":4096,"maximumProviderCredits":1,"maximumIngressBytesPerSecond":4096,"maximumElapsedMs":1000,"maximumInFlightAttempts":1,"maximumInFlightElapsedOvershootMs":100}},"authority":"{AUTHORITY}"}}"#,
    )
    .into_bytes();
    let privacy = format!(
        r#"{{"contract":"joshi.wave5.privacy_policy","schemaVersion":1,"policyId":"privacy:test","permittedProtectionClasses":["public_integrity","authenticated_private"],"credentialHandling":"purpose_scoped_handles_only","walletMaterial":"forbidden","exportPrivateMaterial":false,"authority":"{AUTHORITY}"}}"#,
    )
    .into_bytes();
    let surface = include_str!("../../../fixtures/surface/daily_use_surface_profile_v1.json")
        .trim_end()
        .as_bytes()
        .to_vec();
    let components = [build, source_tree, configuration, budget, privacy, surface];
    let registration = RunRegistration {
        contract: "joshi.wave5.run_registration",
        schema_version: 1,
        run_id: "run:test",
        build: document("build:test", &components[0]),
        source_tree: document("source-tree:test", &components[1]),
        configuration: document("configuration:test", &components[2]),
        budget: document("budget:test", &components[3]),
        privacy: document("privacy:test", &components[4]),
        daily_use_surface_profile: document("surface:test", &components[5]),
        authority: AUTHORITY,
    };
    let registration_bytes = serde_json::to_vec(&registration).expect("canonical registration");
    let exact = Wave5RunRegistrationByteBundle {
        registration: &registration_bytes,
        build: &components[0],
        source_tree: &components[1],
        configuration: &components[2],
        budget: &components[3],
        privacy: &components[4],
        daily_use_surface_profile: &components[5],
    };
    let commit = context(&store, "commit:run");
    let accepted = store
        .commit_wave5_run_registration_v1(&exact, &commit)
        .expect("register exact run");
    assert_eq!(accepted.status, IdempotencyStatus::Accepted);
    let retry = store
        .commit_wave5_run_registration_v1(&exact, &commit)
        .expect("retry exact run");
    assert_eq!(retry.status, IdempotencyStatus::Idempotent);

    let loaded = store
        .load_wave5_run_registration_v1(&stable("run:test"))
        .expect("load run")
        .expect("registered run");
    assert_eq!(loaded.exact_bytes, registration_bytes);
    assert_eq!(loaded.build_bytes, components[0]);
    assert_eq!(loaded.daily_surface_profile_bytes, components[5]);
    let status_view = store
        .load_wave5_store_status_view_v1(&stable("run:test"))
        .expect("load store status view");
    let run_progress = status_view
        .durable_progress
        .iter()
        .find(|progress| progress.progress_id.as_str() == "run:run:test")
        .expect("run progress");
    assert_eq!(run_progress.state, DurableProgressState::Committed);
    assert_eq!(run_progress.durable_commit, Some(accepted.commit_seq));
    assert_eq!(
        run_progress
            .content_digest
            .as_ref()
            .map(StableString::as_str),
        Some(accepted.exact_document_digest.as_str())
    );

    let initial_ready_commit = context(&store, "commit:initial-ready");
    let initial_ready = Wave5OperationalRecordV1 {
        contract: "joshi.wave5.operational_record.v1".into(),
        schema_version: 1,
        record_id: "status:initial-ready".into(),
        run_registration_id: "run:test".into(),
        run_registration_digest: accepted.exact_document_digest.to_string(),
        component: "catalog".into(),
        kind: Wave5OperationalRecordKind::Status,
        state: Wave5OperationalState::Ready,
        cause: None,
        predecessor_record_id: None,
        evidence_commit_seq: None,
        observed_at: initial_ready_commit.committed_at(),
        detail_digest: None,
        authority: AUTHORITY.into(),
    };
    assert!(
        store
            .commit_wave5_operational_record_v1(
                &serde_json::to_vec(&initial_ready).expect("initial Ready bytes"),
                &initial_ready_commit,
            )
            .is_err()
    );
    for (record_id, kind, state) in [
        (
            "status:initial-recovering",
            Wave5OperationalRecordKind::Status,
            Wave5OperationalState::Recovering,
        ),
        (
            "status:initial-stopped",
            Wave5OperationalRecordKind::Stopped,
            Wave5OperationalState::Stopped,
        ),
    ] {
        let attempt_commit = context(&store, &format!("commit:{record_id}"));
        let attempt = Wave5OperationalRecordV1 {
            record_id: record_id.into(),
            kind,
            state,
            observed_at: attempt_commit.committed_at(),
            ..initial_ready.clone()
        };
        assert!(
            store
                .commit_wave5_operational_record_v1(
                    &serde_json::to_vec(&attempt).expect("initial escalation bytes"),
                    &attempt_commit,
                )
                .is_err()
        );
    }

    let status_commit = context(&store, "commit:status");
    let status = Wave5OperationalRecordV1 {
        record_id: "status:test".into(),
        state: Wave5OperationalState::Refused,
        observed_at: status_commit.committed_at(),
        ..initial_ready
    };
    let status_bytes = serde_json::to_vec(&status).expect("canonical status");
    let status_receipt = store
        .commit_wave5_operational_record_v1(&status_bytes, &status_commit)
        .expect("run-bound operational record");
    assert_eq!(status_receipt.status, IdempotencyStatus::Accepted);
    let loaded_status = store
        .load_latest_wave5_operational_record_v1(&stable("run:test"), &stable("catalog"))
        .expect("load latest status")
        .expect("durable status");
    assert_eq!(loaded_status.record.record_id, "status:test");
    assert_eq!(loaded_status.exact_bytes, status_bytes);

    let degradation_commit = context(&store, "commit:degradation");
    let degradation = Wave5OperationalRecordV1 {
        record_id: "degradation:test".into(),
        kind: Wave5OperationalRecordKind::Degradation,
        state: Wave5OperationalState::Degraded,
        cause: Some("catalog_unavailable".into()),
        evidence_commit_seq: None,
        observed_at: degradation_commit.committed_at(),
        ..status.clone()
    };
    store
        .commit_wave5_operational_record_v1(
            &serde_json::to_vec(&degradation).expect("degradation bytes"),
            &degradation_commit,
        )
        .expect("durable degradation");
    let bypass_commit = context(&store, "commit:bypass");
    let bypass = Wave5OperationalRecordV1 {
        record_id: "status:bypass".into(),
        kind: Wave5OperationalRecordKind::Status,
        state: Wave5OperationalState::Ready,
        cause: None,
        observed_at: bypass_commit.committed_at(),
        ..status.clone()
    };
    assert!(
        store
            .commit_wave5_operational_record_v1(
                &serde_json::to_vec(&bypass).expect("bypass bytes"),
                &bypass_commit,
            )
            .is_err()
    );
    let backdated_recovery_commit = context(&store, "commit:backdated-recovery");
    let backdated_recovery = Wave5OperationalRecordV1 {
        record_id: "recovery-start:backdated".into(),
        kind: Wave5OperationalRecordKind::RecoveryStarted,
        state: Wave5OperationalState::Recovering,
        cause: None,
        predecessor_record_id: Some(degradation.record_id.clone()),
        evidence_commit_seq: None,
        observed_at: status.observed_at,
        ..status.clone()
    };
    assert!(
        store
            .commit_wave5_operational_record_v1(
                &serde_json::to_vec(&backdated_recovery).expect("backdated recovery bytes"),
                &backdated_recovery_commit,
            )
            .is_err()
    );
    let recovery_commit = context(&store, "commit:recovery-start");
    let recovery_started = Wave5OperationalRecordV1 {
        record_id: "recovery-start:test".into(),
        kind: Wave5OperationalRecordKind::RecoveryStarted,
        state: Wave5OperationalState::Recovering,
        cause: None,
        predecessor_record_id: Some(degradation.record_id.clone()),
        evidence_commit_seq: None,
        observed_at: recovery_commit.committed_at(),
        ..status.clone()
    };
    store
        .commit_wave5_operational_record_v1(
            &serde_json::to_vec(&recovery_started).expect("recovery-start bytes"),
            &recovery_commit,
        )
        .expect("durable recovery start");
    let unproved_commit = context(&store, "commit:unproved-recovery");
    let unproved = Wave5OperationalRecordV1 {
        record_id: "recovery-verified:unproved".into(),
        kind: Wave5OperationalRecordKind::RecoveryVerified,
        state: Wave5OperationalState::Ready,
        cause: None,
        predecessor_record_id: Some(recovery_started.record_id.clone()),
        evidence_commit_seq: None,
        observed_at: unproved_commit.committed_at(),
        detail_digest: None,
        ..status.clone()
    };
    assert!(
        store
            .commit_wave5_operational_record_v1(
                &serde_json::to_vec(&unproved).expect("unproved recovery bytes"),
                &unproved_commit,
            )
            .is_err()
    );

    let mut widened = status;
    widened.record_id = "status:widened".into();
    widened.authority = "execute".into();
    assert!(
        store
            .commit_wave5_operational_record_v1(
                &serde_json::to_vec(&widened).expect("widened bytes"),
                &context(&store, "commit:widened"),
            )
            .is_err()
    );
}
