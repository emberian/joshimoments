//! Bounded Core witness for the exact fixture-only Wave 6 N00 program registration.

use std::{fs, path::Path, time::Duration};

use joshi_domain::StableString;
use joshi_store::{IdempotencyStatus, SqliteStore, StoreConfig, StoreMode};
use joshi_wave6_registry::SemanticCeilingV1;
use serde::Serialize;
use thiserror::Error;

const REGISTRATION: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
const PROGRAM_ID: &str = "w6-program-fixture-001";
const BATCH_ID: &str = "wave6:program-registration:fixture-001";
const AUTHORITY: &str = "read_record_replay_propose_shadow_only";

/// Machine-readable, non-promoting result of the N00 durable fixture walk.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct Wave6ProgramRegistrationReport {
    pub contract: &'static str,
    pub schema_version: u64,
    pub status: &'static str,
    pub authority: &'static str,
    pub semantic_ceiling: SemanticCeilingV1,
    pub catalog_schema: String,
    pub program_id: String,
    pub registration_digest: String,
    pub document_digest: String,
    pub accepted_commit_seq: String,
    pub first_status: IdempotencyStatus,
    pub retry_status: IdempotencyStatus,
    pub registration_persisted: bool,
    pub restart_reverified: bool,
    pub consumed_wave5_gate_count: &'static str,
    pub provider_units: &'static str,
    pub external_mutation_units: &'static str,
    pub wave5_gates_resolved: bool,
    pub operational_release: bool,
    pub empirical_claim: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

/// Commits, exactly retries and read-only reopens the frozen N00 registration.
///
/// This function performs no provider, network, presentation, wallet, signing, transaction,
/// deployment or external-mutation operation. It never resolves a Wave 5 gate.
///
/// # Errors
///
/// Refuses filesystem, clock, migration, exact-registration, retry or readback failures.
pub fn run_wave6_program_registration(
    state: &Path,
) -> Result<Wave6ProgramRegistrationReport, Wave6RegistrationError> {
    fs::create_dir_all(state)?;
    let store_config = config(state)?;
    let mut store = SqliteStore::open(store_config.clone(), StoreMode::SingleWriter)?;
    let migration = store.migrate(now()?)?;
    if migration.current != 11 {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 registration did not reach V11",
        ));
    }
    let batch_id = StableString::new(BATCH_ID)?;
    let writer_build = StableString::new(format!("joshi-core-{}", env!("CARGO_PKG_VERSION")))?;
    let accepted = store.commit_wave6_program_registration_v1(
        REGISTRATION,
        batch_id.clone(),
        writer_build.clone(),
    )?;
    if !matches!(
        accepted.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) || accepted.catalog_schema.as_str() != "joshi.sqlite.v11"
        || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "first Wave 6 registration returned an impossible receipt",
        ));
    }
    let retry = store.commit_wave6_program_registration_v1(REGISTRATION, batch_id, writer_build)?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.program_id != accepted.program_id
        || retry.registration_digest != accepted.registration_digest
        || retry.document_digest != accepted.document_digest
        || retry.commit_seq != accepted.commit_seq
        || retry.commit_digest != accepted.commit_digest
    {
        return Err(Wave6RegistrationError::Invariant(
            "exact Wave 6 registration retry changed durable identity",
        ));
    }
    drop(store);

    let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly)?;
    let program_id = StableString::new(PROGRAM_ID)?;
    let stored = reopened
        .load_wave6_program_registration_v1(&program_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 registration was absent after restart",
        ))?;
    if stored.program_id != accepted.program_id
        || stored.exact_bytes != REGISTRATION
        || stored.registration_digest != accepted.registration_digest
        || stored.document_digest != accepted.document_digest
        || stored.commit_seq != accepted.commit_seq
        || stored.commit_digest != accepted.commit_digest
        || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 registration changed across read-only reopen",
        ));
    }

    Ok(Wave6ProgramRegistrationReport {
        contract: "joshi.core.wave6_program_registration_report.v1",
        schema_version: 1,
        status: "fixture_only",
        authority: AUTHORITY,
        semantic_ceiling: stored.semantic_ceiling,
        catalog_schema: accepted.catalog_schema.to_string(),
        program_id: stored.program_id.to_string(),
        registration_digest: stored.registration_digest.to_string(),
        document_digest: stored.document_digest.to_string(),
        accepted_commit_seq: stored.commit_seq.get().to_string(),
        first_status: accepted.status,
        retry_status: retry.status,
        registration_persisted: true,
        restart_reverified: true,
        consumed_wave5_gate_count: "0",
        provider_units: "0",
        external_mutation_units: "0",
        wave5_gates_resolved: false,
        operational_release: false,
        empirical_claim: false,
        product_qualified: false,
        live_qualified: false,
    })
}

fn config(root: &Path) -> Result<StoreConfig, Wave6RegistrationError> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-wave6-fixture-registry")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

fn now() -> Result<joshi_domain::UtcTimestamp, Wave6RegistrationError> {
    let nanos = time::OffsetDateTime::now_utc().unix_timestamp_nanos();
    let micros = nanos.div_euclid(1_000) * 1_000;
    joshi_domain::UtcTimestamp::new(
        time::OffsetDateTime::from_unix_timestamp_nanos(micros)
            .map_err(|_| Wave6RegistrationError::Clock)?,
    )
    .map_err(|_| Wave6RegistrationError::Clock)
}

/// Failure to produce the exact, non-promoting registration witness.
#[derive(Debug, Error)]
pub enum Wave6RegistrationError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error("system clock is unavailable")]
    Clock,
    #[error("Wave 6 fixture registration invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_registration_retries_and_reopens_without_operational_claims() {
        let state = tempfile::tempdir().expect("temporary registration state");
        let first =
            run_wave6_program_registration(state.path()).expect("first registration witness");
        assert_eq!(first.status, "fixture_only");
        assert_eq!(first.catalog_schema, "joshi.sqlite.v11");
        assert_eq!(first.first_status, IdempotencyStatus::Accepted);
        assert_eq!(first.retry_status, IdempotencyStatus::Idempotent);
        assert!(first.registration_persisted);
        assert!(first.restart_reverified);
        assert_eq!(first.consumed_wave5_gate_count, "0");
        assert!(!first.wave5_gates_resolved);
        assert!(!first.operational_release);
        assert!(!first.empirical_claim);
        assert!(!first.product_qualified);
        assert!(!first.live_qualified);

        let repeated =
            run_wave6_program_registration(state.path()).expect("repeated registration witness");
        assert_eq!(repeated.first_status, IdempotencyStatus::Idempotent);
        assert_eq!(repeated.retry_status, IdempotencyStatus::Idempotent);
        assert_eq!(repeated.registration_digest, first.registration_digest);
        assert_eq!(repeated.document_digest, first.document_digest);
        assert_eq!(repeated.accepted_commit_seq, first.accepted_commit_seq);
    }
}
