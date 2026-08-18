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

struct SchemaFixture {
    kind_id: &'static str,
    bytes: &'static [u8],
}

struct ArtifactFixture {
    kind_id: &'static str,
    bytes: &'static [u8],
}

/// One exact schema row retained by the Core witness.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6ArtifactSchemaReport {
    pub kind_id: String,
    pub schema_id: String,
    pub schema_digest: String,
    pub commit_seq: String,
}

/// One exact fixture evaluation retained and reparsed by the sole store.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureArtifactReport {
    pub artifact_id: String,
    pub kind_id: String,
    pub schema_id: String,
    pub content_digest: String,
    pub evaluation_digest: String,
    pub result_count: String,
    pub commit_seq: String,
}

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
    pub registered_schema_count: String,
    pub schemas: Vec<Wave6ArtifactSchemaReport>,
    pub schema_catalog_persisted: bool,
    pub schema_catalog_restart_reverified: bool,
    pub fixture_artifact_content_count: String,
    pub fixture_artifacts: Vec<Wave6FixtureArtifactReport>,
    pub fixture_artifact_content_persisted: bool,
    pub fixture_artifact_content_restart_reverified: bool,
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
    if migration.current != 13 {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 registration did not reach V13",
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
    ) || accepted.catalog_schema.as_str() != "joshi.sqlite.v13"
        || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "first Wave 6 registration returned an impossible receipt",
        ));
    }
    let retry =
        store.commit_wave6_program_registration_v1(REGISTRATION, batch_id, writer_build.clone())?;
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
    let schema_reports = commit_schemas(&mut store, &accepted.program_id, &writer_build)?;
    let artifact_reports = commit_artifacts(&mut store, &accepted.program_id, &writer_build)?;
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
    verify_schemas(&reopened, &program_id, &schema_reports)?;
    verify_artifacts(&reopened, &artifact_reports)?;

    Ok(Wave6ProgramRegistrationReport {
        contract: "joshi.core.wave6_program_registration_report.v3",
        schema_version: 3,
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
        registered_schema_count: schema_reports.len().to_string(),
        schemas: schema_reports,
        schema_catalog_persisted: true,
        schema_catalog_restart_reverified: true,
        fixture_artifact_content_count: artifact_reports.len().to_string(),
        fixture_artifacts: artifact_reports,
        fixture_artifact_content_persisted: true,
        fixture_artifact_content_restart_reverified: true,
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

fn commit_schemas(
    store: &mut SqliteStore,
    program_id: &StableString,
    writer_build: &StableString,
) -> Result<Vec<Wave6ArtifactSchemaReport>, Wave6RegistrationError> {
    let mut reports = Vec::with_capacity(schemas().len());
    for fixture in schemas() {
        let kind_id = StableString::new(fixture.kind_id)?;
        let batch_id = StableString::new(format!("wave6:schema:{}", fixture.kind_id))?;
        let accepted = store.commit_wave6_artifact_schema_v1(
            program_id,
            kind_id.clone(),
            fixture.bytes,
            batch_id.clone(),
            writer_build.clone(),
        )?;
        if !matches!(
            accepted.status,
            IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
        ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 schema returned an impossible first receipt",
            ));
        }
        let retry = store.commit_wave6_artifact_schema_v1(
            program_id,
            kind_id,
            fixture.bytes,
            batch_id,
            writer_build.clone(),
        )?;
        if retry.status != IdempotencyStatus::Idempotent
            || retry.kind_id != accepted.kind_id
            || retry.schema_id != accepted.schema_id
            || retry.schema_digest != accepted.schema_digest
            || retry.commit_seq != accepted.commit_seq
            || retry.commit_digest != accepted.commit_digest
        {
            return Err(Wave6RegistrationError::Invariant(
                "exact Wave 6 schema retry changed durable identity",
            ));
        }
        reports.push(Wave6ArtifactSchemaReport {
            kind_id: accepted.kind_id.to_string(),
            schema_id: accepted.schema_id.to_string(),
            schema_digest: accepted.schema_digest.to_string(),
            commit_seq: accepted.commit_seq.get().to_string(),
        });
    }
    Ok(reports)
}

fn verify_schemas(
    store: &SqliteStore,
    program_id: &StableString,
    reports: &[Wave6ArtifactSchemaReport],
) -> Result<(), Wave6RegistrationError> {
    if reports.len() != schemas().len() {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 schema catalog has the wrong cardinality",
        ));
    }
    for (fixture, report) in schemas().into_iter().zip(reports) {
        if fixture.kind_id != report.kind_id {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 schema order changed before restart readback",
            ));
        }
        let kind_id = StableString::new(fixture.kind_id)?;
        let stored = store
            .load_wave6_artifact_schema_v1(program_id, &kind_id)?
            .ok_or(Wave6RegistrationError::Invariant(
                "Wave 6 schema was absent after restart",
            ))?;
        if stored.kind_id.as_str() != report.kind_id
            || stored.schema_id.as_str() != report.schema_id
            || stored.schema_digest.as_str() != report.schema_digest
            || stored.commit_seq.get().to_string() != report.commit_seq
            || stored.exact_bytes != fixture.bytes
            || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 schema changed across read-only reopen",
            ));
        }
    }
    Ok(())
}

fn commit_artifacts(
    store: &mut SqliteStore,
    program_id: &StableString,
    writer_build: &StableString,
) -> Result<Vec<Wave6FixtureArtifactReport>, Wave6RegistrationError> {
    let mut reports = Vec::with_capacity(artifacts().len());
    for fixture in artifacts() {
        let kind_id = StableString::new(fixture.kind_id)?;
        let batch_id = StableString::new(format!("wave6:artifact:{}", fixture.kind_id))?;
        let accepted = store.commit_wave6_fixture_artifact_v1(
            program_id,
            kind_id.clone(),
            fixture.bytes,
            batch_id.clone(),
            writer_build.clone(),
        )?;
        if !matches!(
            accepted.status,
            IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
        ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 fixture artifact returned an impossible first receipt",
            ));
        }
        let retry = store.commit_wave6_fixture_artifact_v1(
            program_id,
            kind_id,
            fixture.bytes,
            batch_id,
            writer_build.clone(),
        )?;
        if retry.status != IdempotencyStatus::Idempotent
            || retry.artifact_id != accepted.artifact_id
            || retry.kind_id != accepted.kind_id
            || retry.schema_id != accepted.schema_id
            || retry.content_digest != accepted.content_digest
            || retry.evaluation_digest != accepted.evaluation_digest
            || retry.result_count != accepted.result_count
            || retry.commit_seq != accepted.commit_seq
            || retry.commit_digest != accepted.commit_digest
        {
            return Err(Wave6RegistrationError::Invariant(
                "exact Wave 6 artifact retry changed durable identity",
            ));
        }
        reports.push(Wave6FixtureArtifactReport {
            artifact_id: accepted.artifact_id.to_string(),
            kind_id: accepted.kind_id.to_string(),
            schema_id: accepted.schema_id.to_string(),
            content_digest: accepted.content_digest.to_string(),
            evaluation_digest: accepted.evaluation_digest.to_string(),
            result_count: accepted.result_count.to_string(),
            commit_seq: accepted.commit_seq.get().to_string(),
        });
    }
    Ok(reports)
}

fn verify_artifacts(
    store: &SqliteStore,
    reports: &[Wave6FixtureArtifactReport],
) -> Result<(), Wave6RegistrationError> {
    if reports.len() != artifacts().len() {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture artifact catalog has the wrong cardinality",
        ));
    }
    for (fixture, report) in artifacts().into_iter().zip(reports) {
        if fixture.kind_id != report.kind_id {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 artifact order changed before restart readback",
            ));
        }
        let artifact_id = StableString::new(report.artifact_id.clone())?;
        let stored = store.load_wave6_fixture_artifact_v1(&artifact_id)?.ok_or(
            Wave6RegistrationError::Invariant("Wave 6 fixture artifact was absent after restart"),
        )?;
        if stored.artifact_id.as_str() != report.artifact_id
            || stored.kind_id.as_str() != report.kind_id
            || stored.schema_id.as_str() != report.schema_id
            || stored.content_digest.as_str() != report.content_digest
            || stored.evaluation_digest.as_str() != report.evaluation_digest
            || stored.result_count.to_string() != report.result_count
            || stored.commit_seq.get().to_string() != report.commit_seq
            || stored.exact_bytes != fixture.bytes
            || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 fixture artifact changed across read-only reopen",
            ));
        }
    }
    Ok(())
}

fn schemas() -> [SchemaFixture; 6] {
    [
        SchemaFixture {
            kind_id: "campaign_registration_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/campaign_registration_v1.json"),
        },
        SchemaFixture {
            kind_id: "known_truth_evaluation_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/known_truth_evaluation_v1.json"),
        },
        SchemaFixture {
            kind_id: "market_atlas_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/market_atlas_snapshot_v1.json"),
        },
        SchemaFixture {
            kind_id: "protocol_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/schemas/protocol_known_truth_evaluation_v1.json"
            ),
        },
        SchemaFixture {
            kind_id: "research_proposal_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/research_proposal_v1.json"),
        },
        SchemaFixture {
            kind_id: "structural_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/schemas/structural_known_truth_evaluation_v1.json"
            ),
        },
    ]
}

fn artifacts() -> [ArtifactFixture; 3] {
    [
        ArtifactFixture {
            kind_id: "known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/artifacts/known_truth_evaluation_v1.json"
            ),
        },
        ArtifactFixture {
            kind_id: "protocol_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/artifacts/protocol_known_truth_evaluation_v1.json"
            ),
        },
        ArtifactFixture {
            kind_id: "structural_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/artifacts/structural_known_truth_evaluation_v1.json"
            ),
        },
    ]
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
        assert_eq!(first.catalog_schema, "joshi.sqlite.v13");
        assert_eq!(first.first_status, IdempotencyStatus::Accepted);
        assert_eq!(first.retry_status, IdempotencyStatus::Idempotent);
        assert!(first.registration_persisted);
        assert!(first.restart_reverified);
        assert_eq!(first.registered_schema_count, "6");
        assert_eq!(first.schemas.len(), 6);
        assert!(first.schema_catalog_persisted);
        assert!(first.schema_catalog_restart_reverified);
        assert_eq!(first.fixture_artifact_content_count, "3");
        assert_eq!(first.fixture_artifacts.len(), 3);
        assert!(first.fixture_artifact_content_persisted);
        assert!(first.fixture_artifact_content_restart_reverified);
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
        assert_eq!(repeated.schemas, first.schemas);
        assert_eq!(repeated.fixture_artifacts, first.fixture_artifacts);
    }
}
