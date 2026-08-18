use joshi_domain::{
    AcquisitionClocks, AcquisitionId, BatchDigest, ObservationId, OpenVariant, RequestFingerprint,
    SourceId, StableString, UtcTimestamp, ValueDigest, WireU64,
};
use joshi_evidence::{
    AcquisitionRecord, DurableIngestBatch, MonotonicReading, ObservationDraft,
    ObservationEventTime, ObservationMetadata, ObservationTiming,
};
use joshi_operational_status::DurableProgressState;
use joshi_store::{
    IdempotencyStatus, ObservationStorage, SourceRegistration, SqliteStore, StoreConfig,
    StoreIngestBatch, StoreMode, Wave5CommitContext, Wave5OperationalRecordKind,
    Wave5OperationalRecordV1, Wave5OperationalState, Wave5RunRegistrationByteBundle,
};
use serde::Serialize;
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeMap, fs, path::Path, str::FromStr, time::Duration};
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

fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 1_024,
        busy_timeout: Duration::from_secs(1),
        catalog_id: stable("catalog:test"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    }
}

fn store() -> (TempDir, SqliteStore) {
    let root = TempDir::new().expect("temporary root");
    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
    let report = store
        .migrate(timestamp("2026-08-18T00:00:00.000000Z"))
        .expect("migrate");
    assert_eq!(report.current, 11);
    (root, store)
}

#[allow(clippy::too_many_lines)]
fn commit_external_observation(store: &mut SqliteStore) {
    let source_id = SourceId::new("backup-source").expect("source id");
    store
        .register_source(&SourceRegistration {
            source_id: source_id.clone(),
            namespace: stable("fixture.backup"),
            contract_version: stable("v1"),
            collector_build: stable("backup-test"),
            configuration_digest: ValueDigest::new(format!("sha256:{}", "0".repeat(64)))
                .expect("configuration digest"),
        })
        .expect("register backup source");
    let committed_at = context(store, "clock:external-observation").committed_at();
    let acquisition = AcquisitionRecord {
        acquisition_id: AcquisitionId::new("backup-acquisition").expect("acquisition id"),
        source_id,
        acquisition_kind: OpenVariant::known("fixture").expect("kind"),
        transport_kind: OpenVariant::known("fixture").expect("transport"),
        parent_acquisition_id: None,
        request_fingerprint: RequestFingerprint::new(format!("sha256:{}", "1".repeat(64)))
            .expect("request fingerprint"),
        contract_version: stable("v1"),
        started_at: committed_at,
        started_monotonic: Some(MonotonicReading {
            clock_id: stable("backup-clock"),
            nanoseconds: WireU64::new(1),
        }),
        source_locator: Some(stable("fixture://backup")),
        source_cursor: None,
        clocks: AcquisitionClocks {
            requested_at: Some(committed_at),
            received_at: committed_at,
            persisted_at: committed_at,
            monotonic_elapsed_ns: Some(WireU64::new(1)),
            monotonic_domain: Some(stable("backup-clock")),
        },
    };
    let observation_id = ObservationId::new("backup-observation").expect("observation id");
    let mut batch = StoreIngestBatch {
        evidence: DurableIngestBatch {
            contract_version: stable("joshi.durable_ingest_batch.v1"),
            batch_id: stable("backup-observation-batch"),
            expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64)))
                .expect("placeholder digest"),
            observations: vec![ObservationDraft {
                acquisition,
                observation: ObservationMetadata {
                    observation_id: observation_id.clone(),
                    acquisition_ordinal: WireU64::new(0),
                    observation_kind: OpenVariant::known("fixture").expect("observation kind"),
                    source_events: Vec::new(),
                    source_variant: OpenVariant::known("fixture.payload").expect("variant"),
                    event_time: ObservationEventTime {
                        status: OpenVariant::known("exact").expect("event status"),
                        lower: Some(
                            UtcTimestamp::new(
                                committed_at.as_datetime() - time::Duration::microseconds(1),
                            )
                            .expect("event lower"),
                        ),
                        upper: Some(committed_at),
                        precision_us: Some(WireU64::new(1)),
                    },
                    chain: None,
                    source_cursor: None,
                    timing: ObservationTiming {
                        received_at: committed_at,
                        received_monotonic: MonotonicReading {
                            clock_id: stable("backup-clock"),
                            nanoseconds: WireU64::new(2),
                        },
                        persisted_at: committed_at,
                        available_at: committed_at,
                    },
                    parse_disposition: OpenVariant::known("decoded").expect("parse disposition"),
                    quality_code: None,
                    media_type: stable("application/octet-stream"),
                },
                payload: vec![7; 2_048],
            }],
            source_events: Vec::new(),
            assertions: Vec::new(),
            coverage_windows: Vec::new(),
            coverage_gaps: Vec::new(),
            coverage_recoveries: Vec::new(),
            cursor_advances: Vec::new(),
        },
        observation_storage: BTreeMap::from([(
            observation_id.to_string(),
            ObservationStorage {
                retention_class: stable("fixture"),
                content_encoding: None,
                force_external: true,
            },
        )]),
        coverage_gap_severity: BTreeMap::new(),
        committed_at,
        writer_clock_id: stable("backup-store-clock"),
        committed_mono_ns: 1,
        writer_build: stable("backup-test"),
    };
    batch.evidence.expected_digest =
        SqliteStore::canonical_batch_digest(&batch.evidence).expect("canonical batch digest");
    store.commit_ingest(&batch).expect("external observation");
}

fn first_regular_file(root: &Path) -> Option<std::path::PathBuf> {
    for entry in fs::read_dir(root).ok()? {
        let path = entry.ok()?.path();
        let metadata = fs::symlink_metadata(&path).ok()?;
        if metadata.file_type().is_file() {
            return Some(path);
        }
        if metadata.file_type().is_dir()
            && let Some(value) = first_regular_file(&path)
        {
            return Some(value);
        }
    }
    None
}

#[test]
#[allow(clippy::too_many_lines)]
fn exact_run_bytes_are_durable_idempotent_and_required_by_operational_records() {
    let (root, mut store) = store();
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

    commit_external_observation(&mut store);
    let backup_id = stable("backup:test");
    let backup_catalog = root.path().join("backup/catalog.sqlite");
    let backup_artifacts = root.path().join("backup/artifacts");
    let backup_context = context(&store, "commit:backup");
    let backup = store
        .commit_wave5_g0_backup_v1(
            &backup_id,
            &stable("run:test"),
            &backup_catalog,
            &backup_artifacts,
            &backup_context,
        )
        .expect("artifact-bearing backup");
    assert!(backup.artifact_count > 0);
    let retry = store
        .commit_wave5_g0_backup_v1(
            &backup_id,
            &stable("run:test"),
            &backup_catalog,
            &backup_artifacts,
            &backup_context,
        )
        .expect("exact backup retry");
    assert_eq!(retry.status, IdempotencyStatus::Idempotent);

    fs::rename(
        root.path().join("blobs"),
        root.path().join("blobs-unavailable"),
    )
    .expect("hide original blobs");
    fs::rename(
        root.path().join("exports"),
        root.path().join("exports-unavailable"),
    )
    .expect("hide original exports");
    let restore_id = stable("restore:test");
    let restored_catalog = root.path().join("restored/catalog.sqlite");
    let restored_artifacts = root.path().join("restored/artifacts");
    let restore_context = context(&store, "commit:restore");
    store
        .commit_wave5_g0_backup_restore_v1(
            &restore_id,
            &backup_id,
            &restored_catalog,
            &restored_artifacts,
            &restore_context,
        )
        .expect("restore without original artifact roots");
    drop(store);

    let reopened = SqliteStore::open(config(root.path()), StoreMode::SingleWriter)
        .expect("reopen authority catalog");
    reopened
        .load_wave5_g0_backup_restore_v1(&restore_id)
        .expect("restart exact restore readback")
        .expect("restore occurrence");
    let restored_file = first_regular_file(&restored_artifacts).expect("restored artifact");
    fs::write(&restored_file, b"tampered after restore commit").expect("tamper restored file");
    assert!(
        reopened
            .load_wave5_g0_backup_restore_v1(&restore_id)
            .is_err(),
        "postcommit restored-root tampering must fail exact load"
    );
}
