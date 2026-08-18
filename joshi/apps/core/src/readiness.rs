use joshi_admission::{
    CompanionReceiptV1, PublicStatus, Sha256Digest, admit_companion, parse_companion,
};
use joshi_domain::{StableString, UtcTimestamp};
use joshi_operator::{OperatorCommandStatus, ValidatedGlassViewV1, ValidatedOperatorCommandV1};
use joshi_store::{
    OperatorCaptureMetadata, SceneSourceMode, SqliteStore, StoreConfig, StoreMode, VerifyDepth,
};
use serde::Serialize;
use std::{path::Path, time::Duration};
use thiserror::Error;

pub const WALKING_MATERIAL: &str = include_str!("../fixtures/companion_walking_material_v1.json");
pub const WALKING_INGRESS_DIGEST: &str =
    "sha256:7b0f6b421ef1edb29932d74cd2ada03acfa6ac227e2503bb7d94dfd97602255b";
const WALKING_VIEW: &str = include_str!("../fixtures/glass_readiness_v1.json");
const WALKING_COMMAND: &str = include_str!("../fixtures/operator_readiness_v1.json");

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OfflineReadinessReport {
    pub contract: &'static str,
    pub schema_version: u64,
    pub authority: &'static str,
    pub catalog_schema: String,
    pub ingress_batch_digest: String,
    pub durable_batch_digest: String,
    pub store_admission_digest: String,
    pub accepted_commit_seq: String,
    pub retry_status: PublicStatus,
    pub acquisition_count: String,
    pub observation_count: String,
    pub assertion_count: String,
    pub coverage_gap_count: String,
    pub scene_id: String,
    pub view_digest: String,
    pub command_digest: String,
    pub command_commit_seq: String,
    pub command_retry_status: OperatorCommandStatus,
    pub store_integrity: String,
    pub reopened: bool,
    pub stream_contract: Option<String>,
}

/// Walk one deterministic source-to-scene-to-command path through a fresh local store.
///
/// # Errors
///
/// Returns an error when any fixture, admission, store, replay, command, or reopen invariant fails.
#[allow(clippy::too_many_lines)] // Keeping the ordered walking assertions together aids auditability.
pub fn run_offline_readiness(
    state: &Path,
    material: &str,
) -> Result<OfflineReadinessReport, ReadinessError> {
    let material = material.trim_end();
    let computed = Sha256Digest::of_bytes(material.as_bytes());
    if computed.as_str() != WALKING_INGRESS_DIGEST {
        return Err(ReadinessError::FixtureDigest {
            expected: WALKING_INGRESS_DIGEST.into(),
            actual: computed.to_string(),
        });
    }
    let request = material.replacen(
        "\"producer\"",
        &format!("\"batchDigest\":\"{computed}\",\"producer\""),
        1,
    );
    let parsed = parse_companion(request.as_bytes())?;
    let committed_at = time("2026-08-16T18:43:00.000000Z")?;
    let admission = admit_companion(parsed, committed_at, 1_000_000, "joshi-readiness-monotonic")?;
    let mut store = SqliteStore::open(config(state)?, StoreMode::SingleWriter)?;
    let migration = store.migrate(committed_at)?;
    let accepted = admission.batch.commit(&mut store)?;
    if accepted.status != PublicStatus::Accepted {
        return Err(ReadinessError::Invariant(
            "fresh catalog did not accept a new batch",
        ));
    }
    let source_receipt = CompanionReceiptV1::from_committed(&admission, &accepted)?;
    let retried = admission.batch.commit(&mut store)?;
    if retried.status != PublicStatus::Idempotent
        || retried.batch_digest != accepted.batch_digest
        || retried.store_admission_digest != accepted.store_admission_digest
    {
        return Err(ReadinessError::Invariant(
            "exact retry did not return the original durable closure",
        ));
    }
    let retry_receipt = CompanionReceiptV1::from_committed(&admission, &retried)?;
    let view = ValidatedGlassViewV1::parse_exact(
        WALKING_VIEW.trim_end().as_bytes(),
        Some("sha256:0a08b01544d41b6ba0e68855142dfaff432582a8f78c17eef3951ca227121313"),
    )?;
    let command = ValidatedOperatorCommandV1::parse_exact(WALKING_COMMAND.trim_end().as_bytes())?;
    let capture = OperatorCaptureMetadata {
        client_scene_seq: 1,
        ui_build: StableString::new("joshi-glass-readiness")?,
        source_mode: SceneSourceMode::Fixture,
        rendered_clock_id: StableString::new("browser-readiness-clock")?,
        rendered_mono_ns: 1_000_000,
        screenshot_bytes: None,
    };
    let command_receipt = store.commit_operator_v1(
        &command,
        Some(&view),
        &capture,
        time("2026-08-16T18:43:03.000000Z")?,
        StableString::new("joshi-readiness-monotonic")?,
        3_000_000,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    if command_receipt.status() != OperatorCommandStatus::Accepted {
        return Err(ReadinessError::Invariant(
            "fresh scene-bound command was not accepted",
        ));
    }
    let command_retry = store.commit_operator_v1(
        &command,
        None,
        &capture,
        time("2026-08-16T18:43:03.000000Z")?,
        StableString::new("joshi-readiness-monotonic")?,
        3_000_001,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    if command_retry.status() != OperatorCommandStatus::Idempotent
        || command_retry.commit_seq() != command_receipt.commit_seq()
    {
        return Err(ReadinessError::Invariant(
            "scene-bound command retry changed durable identity",
        ));
    }
    let loaded_scene = store.load_scene(view.scene_id())?;
    if loaded_scene.view_bytes != view.canonical_bytes() {
        return Err(ReadinessError::Invariant(
            "stored scene bytes differ from exact Glass view",
        ));
    }
    let verify = store.verify(VerifyDepth::Full)?;
    if verify.integrity != "ok" || verify.foreign_key_defects != 0 {
        return Err(ReadinessError::Invariant("full store verification failed"));
    }
    drop(store);
    let reopened = SqliteStore::open(config(state)?, StoreMode::ReadOnly)?;
    let reopen_verify = reopened.verify(VerifyDepth::Quick)?;
    if reopen_verify.integrity != "ok" {
        return Err(ReadinessError::Invariant(
            "reopened catalog verification failed",
        ));
    }
    Ok(OfflineReadinessReport {
        contract: "joshi.offline_readiness",
        schema_version: 1,
        authority: "read_only_no_execution",
        catalog_schema: format!("joshi.sqlite.v{}", migration.current),
        ingress_batch_digest: source_receipt.ingress_batch_digest.to_string(),
        durable_batch_digest: source_receipt.durable_batch_digest.to_string(),
        store_admission_digest: source_receipt.store_admission_digest.to_string(),
        accepted_commit_seq: source_receipt.through_commit_seq,
        retry_status: retry_receipt.status,
        acquisition_count: accepted.admitted.acquisitions,
        observation_count: accepted.admitted.observations,
        assertion_count: accepted.admitted.assertions,
        coverage_gap_count: accepted.admitted.coverage_gaps,
        scene_id: view.scene_id().to_string(),
        view_digest: view.digest().to_string(),
        command_digest: command.command_digest().to_string(),
        command_commit_seq: command_receipt.commit_seq().get().to_string(),
        command_retry_status: command_retry.status(),
        store_integrity: reopen_verify.integrity,
        reopened: true,
        stream_contract: None,
    })
}

fn config(root: &Path) -> Result<StoreConfig, ReadinessError> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-offline-readiness")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

fn time(value: &str) -> Result<UtcTimestamp, ReadinessError> {
    value.parse().map_err(|_| ReadinessError::InvalidTimestamp)
}

#[derive(Debug, Error)]
pub enum ReadinessError {
    #[error(transparent)]
    Admission(#[from] joshi_admission::AdmissionError),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Operator(#[from] joshi_operator::OperatorAdmissionError),
    #[error("walking fixture digest mismatch: expected {expected}, got {actual}")]
    FixtureDigest { expected: String, actual: String },
    #[error("invalid deterministic readiness timestamp")]
    InvalidTimestamp,
    #[error("offline readiness invariant failed: {0}")]
    Invariant(&'static str),
}
