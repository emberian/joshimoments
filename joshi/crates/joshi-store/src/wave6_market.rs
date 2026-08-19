//! Sole-store retention for the exact caller-fed Wave 6 market-atlas fixture.
//!
//! Durability here proves exact byte and registered-schema closure only. It does not resolve the
//! caller-fed source identities, coverage, cut, or native payloads and therefore never raises the
//! fixture's unverified semantic ceiling.

use crate::{IdempotencyStatus, Result, SqliteStore, StoreError};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_wave6_registry::{
    MARKET_ATLAS_KIND, SemanticCeilingV1, parse_market_atlas_fixture_exact,
};
use rusqlite::{OptionalExtension as _, params};

use crate::wave6::{
    digest_bytes, qualified_digest, raw_digest, sqlite_len, sqlite_u64, stable, u64_from_i64,
    usize_from_i64,
};

const MAX_MARKET_ATLAS_BYTES: usize = 512 * 1024;
const FIXTURE_AUTHORITY: &str = "caller_fed_unverified_semantic_fixture_only";
const CLAIM_SCOPE: &str =
    "descriptive_point_in_time_typed_market_atlas_not_scalar_pressure_causal_or_strategy_claim";

/// Durable receipt for one exact market-atlas fixture document.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6MarketAtlasFixtureReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub artifact_id: StableString,
    pub program_id: StableString,
    pub schema_id: StableString,
    pub content_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub atlas_snapshot_id: StableString,
    pub atlas_snapshot_digest: ValueDigest,
    pub input_snapshot_id: StableString,
    pub input_logical_digest: ValueDigest,
    pub row_count: u64,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
    pub status: IdempotencyStatus,
}

/// Exact market-atlas fixture re-parsed and cross-checked after durable readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6MarketAtlasFixture {
    pub batch_id: StableString,
    pub artifact_id: StableString,
    pub program_id: StableString,
    pub schema_id: StableString,
    pub schema_digest: ValueDigest,
    pub schema_commit_seq: CommitSeq,
    pub exact_bytes: Vec<u8>,
    pub content_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub atlas_snapshot_id: StableString,
    pub atlas_snapshot_digest: ValueDigest,
    pub input_snapshot_id: StableString,
    pub input_logical_digest: ValueDigest,
    pub cut_id: StableString,
    pub state_time: UtcTimestamp,
    pub knowledge_cutoff: UtcTimestamp,
    pub input_as_of_commit_seq: u64,
    pub row_count: u64,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
}

struct MarketAtlasRow {
    batch_id: String,
    program_id: String,
    schema_id: String,
    schema_raw: String,
    schema_commit_seq: i64,
    content_raw: String,
    artifact_raw: String,
    atlas_snapshot_id: String,
    atlas_snapshot_raw: String,
    input_snapshot_id: String,
    input_logical_raw: String,
    cut_id: String,
    state_time: String,
    knowledge_cutoff: String,
    input_as_of_commit_seq: i64,
    bytes: Vec<u8>,
    byte_length: i64,
    row_count: i64,
    authority: String,
    claim_scope: String,
    semantic_ceiling: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

impl SqliteStore {
    /// Parses and durably retains the exact registered caller-fed market-atlas fixture.
    ///
    /// # Errors
    ///
    /// Refuses an absent prior program/schema, unsupported or noncanonical bytes, broken cut,
    /// denominator, identity or digest closure, oversized content, a conflicting batch, read-only
    /// state, exhausted artifact budget, or failed exact readback.
    #[allow(clippy::too_many_lines)]
    pub fn commit_wave6_market_atlas_fixture_v1(
        &mut self,
        program_id: &StableString,
        exact_bytes: &[u8],
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6MarketAtlasFixtureReceipt> {
        if exact_bytes.is_empty() || exact_bytes.len() > MAX_MARKET_ATLAS_BYTES {
            return Err(StoreError::InvalidBatch(
                "Wave 6 market-atlas fixture is empty or exceeds the exact-byte limit".into(),
            ));
        }
        let kind_id = stable(MARKET_ATLAS_KIND, "Wave 6 market-atlas kind")?;
        let schema = self
            .load_wave6_artifact_schema_v1(program_id, &kind_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 market-atlas schema",
                identity: format!("{}:{MARKET_ATLAS_KIND}", program_id.as_str()),
            })?;
        let parsed = parse_market_atlas_fixture_exact(&kind_id, &schema.schema_id, exact_bytes)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let value = parsed.value();
        let content_digest = parsed.content_digest().clone();
        let artifact_id = market_atlas_artifact_id(program_id, &content_digest)?;
        reject_second_market_atlas_batch(self, program_id, &batch_id)?;
        let operation_digest = market_atlas_operation_digest(
            program_id,
            &schema.schema_id,
            &schema.schema_digest,
            &content_digest,
            &value.artifact_digest,
            &value.atlas_snapshot_digest,
        )?;
        let input_as_of_commit_seq =
            value
                .as_of_commit_seq
                .parse::<u64>()
                .map_err(|_| StoreError::IntegerRange {
                    field: "Wave 6 market-atlas input commit sequence",
                    value: value.as_of_commit_seq.clone(),
                })?;
        let row_count = u64::try_from(value.rows.len()).map_err(|_| StoreError::IntegerRange {
            field: "Wave 6 market-atlas row count",
            value: value.rows.len().to_string(),
        })?;
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &artifact_id,
            &content_digest,
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_fixture_market_atlas_v1
                     (artifact_id,program_id,kind_id,schema_id,schema_sha256,
                      schema_created_commit_seq,content_sha256,artifact_semantic_sha256,
                      atlas_snapshot_id,atlas_snapshot_sha256,input_snapshot_id,
                      input_logical_sha256,cut_id,state_time,knowledge_cutoff,
                      input_as_of_commit_seq,artifact_bytes,artifact_byte_length,row_count,
                      authority,claim_scope,semantic_ceiling,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                             ?17,?18,?19,?20,?21,?22,?23)",
                    params![
                        artifact_id.as_str(),
                        program_id.as_str(),
                        MARKET_ATLAS_KIND,
                        schema.schema_id.as_str(),
                        raw_digest(&schema.schema_digest, "Wave 6 market-atlas schema digest")?,
                        sqlite_u64(schema.commit_seq.get(), "Wave 6 market-atlas schema commit")?,
                        raw_digest(&content_digest, "Wave 6 market-atlas content digest")?,
                        raw_digest(
                            &value.artifact_digest,
                            "Wave 6 market-atlas artifact digest"
                        )?,
                        value.atlas_snapshot_id.as_str(),
                        raw_digest(
                            &value.atlas_snapshot_digest,
                            "Wave 6 market-atlas snapshot digest",
                        )?,
                        value.input_snapshot_id.as_str(),
                        raw_digest(
                            &value.input_logical_digest,
                            "Wave 6 market-atlas input digest",
                        )?,
                        value.cut_id.as_str(),
                        value.state_time.to_string(),
                        value.knowledge_cutoff.to_string(),
                        sqlite_u64(
                            input_as_of_commit_seq,
                            "Wave 6 market-atlas input commit sequence",
                        )?,
                        exact_bytes,
                        sqlite_len(exact_bytes.len(), "Wave 6 market-atlas bytes")?,
                        sqlite_u64(row_count, "Wave 6 market-atlas row count")?,
                        FIXTURE_AUTHORITY,
                        CLAIM_SCOPE,
                        "unverified_semantic_fixture_only",
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_wave6_market_atlas_fixture_v1(&artifact_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 market-atlas fixture",
                identity: artifact_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.program_id != *program_id
            || stored.schema_id != schema.schema_id
            || stored.schema_digest != schema.schema_digest
            || stored.schema_commit_seq != schema.commit_seq
            || stored.exact_bytes != exact_bytes
            || stored.content_digest != content_digest
            || stored.artifact_digest != value.artifact_digest
            || stored.atlas_snapshot_id != value.atlas_snapshot_id
            || stored.atlas_snapshot_digest != value.atlas_snapshot_digest
            || stored.input_snapshot_id != value.input_snapshot_id
            || stored.input_logical_digest != value.input_logical_digest
            || stored.row_count != row_count
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 market-atlas readback differs from its exact commit".into(),
            ));
        }
        Ok(Wave6MarketAtlasFixtureReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            artifact_id,
            program_id: program_id.clone(),
            schema_id: stored.schema_id,
            content_digest: stored.content_digest,
            artifact_digest: stored.artifact_digest,
            atlas_snapshot_id: stored.atlas_snapshot_id,
            atlas_snapshot_digest: stored.atlas_snapshot_digest,
            input_snapshot_id: stored.input_snapshot_id,
            input_logical_digest: stored.input_logical_digest,
            row_count: stored.row_count,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            semantic_ceiling: stored.semantic_ceiling,
            status: generic.status,
        })
    }

    /// Loads and independently reparses one exact market-atlas fixture.
    ///
    /// # Errors
    ///
    /// Refuses changed bytes, a missing/changed registered schema, any mismatched normalized
    /// column, changed content or semantic digest, authority widening, or broken commit lineage.
    pub fn load_wave6_market_atlas_fixture_v1(
        &self,
        artifact_id: &StableString,
    ) -> Result<Option<StoredWave6MarketAtlasFixture>> {
        let row: Option<MarketAtlasRow> = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id,artifact.program_id,artifact.schema_id,
                        artifact.schema_sha256,artifact.schema_created_commit_seq,
                        artifact.content_sha256,artifact.artifact_semantic_sha256,
                        artifact.atlas_snapshot_id,artifact.atlas_snapshot_sha256,
                        artifact.input_snapshot_id,artifact.input_logical_sha256,
                        artifact.cut_id,artifact.state_time,artifact.knowledge_cutoff,
                        artifact.input_as_of_commit_seq,artifact.artifact_bytes,
                        artifact.artifact_byte_length,artifact.row_count,artifact.authority,
                        artifact.claim_scope,artifact.semantic_ceiling,artifact.created_commit_seq,
                        commit_row.commit_digest
                 FROM wave6_fixture_market_atlas_v1 artifact
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=artifact.created_commit_seq
                 WHERE artifact.artifact_id=?1",
                [artifact_id.as_str()],
                |row| {
                    Ok(MarketAtlasRow {
                        batch_id: row.get(0)?,
                        program_id: row.get(1)?,
                        schema_id: row.get(2)?,
                        schema_raw: row.get(3)?,
                        schema_commit_seq: row.get(4)?,
                        content_raw: row.get(5)?,
                        artifact_raw: row.get(6)?,
                        atlas_snapshot_id: row.get(7)?,
                        atlas_snapshot_raw: row.get(8)?,
                        input_snapshot_id: row.get(9)?,
                        input_logical_raw: row.get(10)?,
                        cut_id: row.get(11)?,
                        state_time: row.get(12)?,
                        knowledge_cutoff: row.get(13)?,
                        input_as_of_commit_seq: row.get(14)?,
                        bytes: row.get(15)?,
                        byte_length: row.get(16)?,
                        row_count: row.get(17)?,
                        authority: row.get(18)?,
                        claim_scope: row.get(19)?,
                        semantic_ceiling: row.get(20)?,
                        commit_seq: row.get(21)?,
                        commit_digest_raw: row.get(22)?,
                    })
                },
            )
            .optional()?;
        row.map(|row| stored_market_atlas(self, artifact_id, row))
            .transpose()
    }
}

fn reject_second_market_atlas_batch(
    store: &SqliteStore,
    program_id: &StableString,
    batch_id: &StableString,
) -> Result<()> {
    let existing: Option<String> = store
        .connection
        .query_row(
            "SELECT commit_row.commit_id
             FROM wave6_fixture_market_atlas_v1 artifact
             JOIN ingest_commit commit_row
               ON commit_row.commit_seq=artifact.created_commit_seq
             WHERE artifact.program_id=?1 AND artifact.kind_id=?2",
            params![program_id.as_str(), MARKET_ATLAS_KIND],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|value| value != batch_id.as_str())
    {
        return Err(StoreError::IdentityConflict {
            kind: "Wave 6 market-atlas fixture",
            identity: format!("{}:{MARKET_ATLAS_KIND}", program_id.as_str()),
        });
    }
    Ok(())
}

fn market_atlas_artifact_id(
    program_id: &StableString,
    content_digest: &ValueDigest,
) -> Result<StableString> {
    let digest = digest_bytes(&serde_json::to_vec(&(
        "joshi.store.wave6_market_atlas_identity.v1",
        program_id,
        content_digest,
    ))?)?;
    stable(
        &format!(
            "wave6-market-atlas:{}",
            raw_digest(&digest, "Wave 6 market-atlas identity digest")?
        ),
        "Wave 6 market-atlas artifact ID",
    )
}

fn market_atlas_operation_digest(
    program_id: &StableString,
    schema_id: &StableString,
    schema_digest: &ValueDigest,
    content_digest: &ValueDigest,
    artifact_digest: &ValueDigest,
    atlas_snapshot_digest: &ValueDigest,
) -> Result<ValueDigest> {
    digest_bytes(&serde_json::to_vec(&(
        "joshi.store.wave6_market_atlas_commit.v1",
        program_id,
        schema_id,
        schema_digest,
        content_digest,
        artifact_digest,
        atlas_snapshot_digest,
    ))?)
}

#[allow(clippy::too_many_lines)]
fn stored_market_atlas(
    store: &SqliteStore,
    artifact_id: &StableString,
    row: MarketAtlasRow,
) -> Result<StoredWave6MarketAtlasFixture> {
    let program_id = stable(&row.program_id, "Wave 6 market-atlas program ID")?;
    let kind_id = stable(MARKET_ATLAS_KIND, "Wave 6 market-atlas kind")?;
    let schema = store
        .load_wave6_artifact_schema_v1(&program_id, &kind_id)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 market-atlas schema",
            identity: format!("{}:{MARKET_ATLAS_KIND}", program_id.as_str()),
        })?;
    let parsed = parse_market_atlas_fixture_exact(&kind_id, &schema.schema_id, &row.bytes)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let value = parsed.value();
    let expected_id = market_atlas_artifact_id(&program_id, parsed.content_digest())?;
    let input_as_of_commit_seq =
        value
            .as_of_commit_seq
            .parse::<u64>()
            .map_err(|_| StoreError::IntegerRange {
                field: "Wave 6 market-atlas input commit sequence",
                value: value.as_of_commit_seq.clone(),
            })?;
    let row_count = u64::try_from(value.rows.len()).map_err(|_| StoreError::IntegerRange {
        field: "Wave 6 market-atlas row count",
        value: value.rows.len().to_string(),
    })?;
    let commit_seq = u64_from_i64(row.commit_seq, "Wave 6 market-atlas commit sequence")?;
    if expected_id != *artifact_id
        || row.schema_id != schema.schema_id.as_str()
        || row.schema_raw != raw_digest(&schema.schema_digest, "Wave 6 market-atlas schema digest")?
        || u64_from_i64(row.schema_commit_seq, "Wave 6 market-atlas schema commit")?
            != schema.commit_seq.get()
        || row.content_raw != raw_digest(parsed.content_digest(), "market-atlas content digest")?
        || row.artifact_raw != raw_digest(&value.artifact_digest, "market-atlas artifact digest")?
        || row.atlas_snapshot_id != value.atlas_snapshot_id.as_str()
        || row.atlas_snapshot_raw
            != raw_digest(&value.atlas_snapshot_digest, "market-atlas snapshot digest")?
        || row.input_snapshot_id != value.input_snapshot_id.as_str()
        || row.input_logical_raw
            != raw_digest(&value.input_logical_digest, "market-atlas input digest")?
        || row.cut_id != value.cut_id.as_str()
        || row.state_time != value.state_time.to_string()
        || row.knowledge_cutoff != value.knowledge_cutoff.to_string()
        || u64_from_i64(
            row.input_as_of_commit_seq,
            "Wave 6 market-atlas input commit sequence",
        )? != input_as_of_commit_seq
        || usize_from_i64(row.byte_length, "Wave 6 market-atlas byte length")? != row.bytes.len()
        || u64_from_i64(row.row_count, "Wave 6 market-atlas row count")? != row_count
        || row.authority != FIXTURE_AUTHORITY
        || row.claim_scope != CLAIM_SCOPE
        || row.semantic_ceiling != "unverified_semantic_fixture_only"
        || row.schema_commit_seq >= row.commit_seq
    {
        return Err(StoreError::InvalidBatch(
            "persisted Wave 6 market atlas differs from exact bytes or registered schema".into(),
        ));
    }
    Ok(StoredWave6MarketAtlasFixture {
        batch_id: stable(&row.batch_id, "Wave 6 market-atlas batch ID")?,
        artifact_id: artifact_id.clone(),
        program_id,
        schema_id: schema.schema_id,
        schema_digest: schema.schema_digest,
        schema_commit_seq: schema.commit_seq,
        exact_bytes: row.bytes,
        content_digest: parsed.content_digest().clone(),
        artifact_digest: value.artifact_digest.clone(),
        atlas_snapshot_id: value.atlas_snapshot_id.clone(),
        atlas_snapshot_digest: value.atlas_snapshot_digest.clone(),
        input_snapshot_id: value.input_snapshot_id.clone(),
        input_logical_digest: value.input_logical_digest.clone(),
        cut_id: value.cut_id.clone(),
        state_time: value.state_time,
        knowledge_cutoff: value.knowledge_cutoff,
        input_as_of_commit_seq,
        row_count,
        commit_seq: CommitSeq::new(commit_seq),
        commit_digest: qualified_digest(
            &row.commit_digest_raw,
            "Wave 6 market-atlas commit digest",
        )?,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{StoreConfig, StoreMode};
    use std::time::Duration;

    const PROGRAM: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
    const SCHEMA: &[u8] =
        include_bytes!("../../../fixtures/wave6/schemas/market_atlas_snapshot_v1.json");
    const ARTIFACT: &[u8] =
        include_bytes!("../../../fixtures/wave6/artifacts/market_atlas_snapshot_v1.json");

    fn config(root: &std::path::Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(2),
            catalog_id: StableString::new("wave6-market-atlas-test").expect("catalog ID"),
            max_observations_per_batch: 256,
            max_raw_bytes_per_batch: 4 * 1024 * 1024,
        }
    }

    fn prepare(root: &std::path::Path) -> (SqliteStore, StableString, StableString) {
        let mut store =
            SqliteStore::open(config(root), StoreMode::SingleWriter).expect("writer store");
        let migration = store
            .migrate(
                "2026-08-18T19:30:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        assert_eq!(migration.current, 22);
        let build = StableString::new("wave6-market-atlas-store-test").expect("build ID");
        let program = store
            .commit_wave6_program_registration_v1(
                PROGRAM,
                StableString::new("wave6:market-atlas:program").expect("program batch"),
                build.clone(),
            )
            .expect("program registration");
        store
            .commit_wave6_artifact_schema_v1(
                &program.program_id,
                StableString::new(MARKET_ATLAS_KIND).expect("kind"),
                SCHEMA,
                StableString::new("wave6:market-atlas:schema").expect("schema batch"),
                build.clone(),
            )
            .expect("schema registration");
        (store, program.program_id, build)
    }

    #[test]
    fn exact_market_atlas_is_durable_idempotent_and_unverified_after_restart() {
        let root = tempfile::tempdir().expect("temporary store");
        let (mut store, program_id, build) = prepare(root.path());
        let batch = StableString::new("wave6:market-atlas:artifact").expect("batch");
        let accepted = store
            .commit_wave6_market_atlas_fixture_v1(
                &program_id,
                ARTIFACT,
                batch.clone(),
                build.clone(),
            )
            .expect("market-atlas commit");
        assert_eq!(accepted.status, IdempotencyStatus::Accepted);
        assert_eq!(accepted.catalog_schema.as_str(), "joshi.sqlite.v22");
        assert_eq!(accepted.row_count, 6);
        assert_eq!(
            accepted.semantic_ceiling,
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
        let retry = store
            .commit_wave6_market_atlas_fixture_v1(&program_id, ARTIFACT, batch, build)
            .expect("exact retry");
        assert_eq!(retry.status, IdempotencyStatus::Idempotent);
        assert_eq!(retry.commit_seq, accepted.commit_seq);
        assert_eq!(retry.commit_digest, accepted.commit_digest);
        drop(store);

        let reopened =
            SqliteStore::open(config(root.path()), StoreMode::ReadOnly).expect("read-only reopen");
        let stored = reopened
            .load_wave6_market_atlas_fixture_v1(&accepted.artifact_id)
            .expect("market-atlas readback")
            .expect("stored market atlas");
        assert_eq!(stored.exact_bytes, ARTIFACT);
        assert_eq!(stored.content_digest, accepted.content_digest);
        assert_eq!(stored.artifact_digest, accepted.artifact_digest);
        assert_eq!(stored.atlas_snapshot_digest, accepted.atlas_snapshot_digest);
        assert_eq!(stored.input_logical_digest, accepted.input_logical_digest);
        assert_eq!(stored.input_as_of_commit_seq, 4);
        assert_eq!(stored.row_count, 6);
        assert_eq!(stored.commit_digest, accepted.commit_digest);
    }

    #[test]
    fn missing_schema_changed_bytes_and_second_batch_refuse() {
        let missing_root = tempfile::tempdir().expect("missing-schema store");
        let mut missing = SqliteStore::open(config(missing_root.path()), StoreMode::SingleWriter)
            .expect("writer store");
        missing
            .migrate(
                "2026-08-18T19:30:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        let program_id = missing
            .commit_wave6_program_registration_v1(
                PROGRAM,
                StableString::new("wave6:market-atlas:missing-program").expect("program batch"),
                StableString::new("wave6-market-atlas-store-test").expect("build"),
            )
            .expect("program registration")
            .program_id;
        assert!(matches!(
            missing.commit_wave6_market_atlas_fixture_v1(
                &program_id,
                ARTIFACT,
                StableString::new("wave6:market-atlas:missing").expect("batch"),
                StableString::new("wave6-market-atlas-store-test").expect("build"),
            ),
            Err(StoreError::MissingIdentity { .. })
        ));

        let root = tempfile::tempdir().expect("temporary store");
        let (mut store, program_id, build) = prepare(root.path());
        let batch = StableString::new("wave6:market-atlas:artifact").expect("batch");
        store
            .commit_wave6_market_atlas_fixture_v1(&program_id, ARTIFACT, batch, build.clone())
            .expect("market-atlas commit");
        assert!(matches!(
            store.commit_wave6_market_atlas_fixture_v1(
                &program_id,
                ARTIFACT,
                StableString::new("wave6:market-atlas:second-batch").expect("second batch"),
                build.clone(),
            ),
            Err(StoreError::IdentityConflict { .. })
        ));

        let mut changed = ARTIFACT.to_vec();
        let index = changed
            .windows("caller_fed".len())
            .position(|window| window == b"caller_fed")
            .expect("authority marker");
        changed[index] = b'C';
        assert!(matches!(
            store.commit_wave6_market_atlas_fixture_v1(
                &program_id,
                &changed,
                StableString::new("wave6:market-atlas:changed").expect("changed batch"),
                build,
            ),
            Err(StoreError::InvalidBatch(_))
        ));
    }
}
