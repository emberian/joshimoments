//! Sole-store persistence for the exact fixture-only Wave 6 program registration.
//!
//! Durability here does not raise the registry's semantic ceiling. The only accepted V1 program
//! consumes no Wave 5 gate references and retains zero provider/external-mutation budgets.

use crate::{IdempotencyStatus, Result, SqliteStore, StoreError};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_wave6_registry::{
    SemanticCeilingV1, ValidatedProgramRegistration, parse_evaluation_artifact_exact,
    parse_program_registration_exact,
};
use rusqlite::{OptionalExtension as _, Transaction, params};
use sha2::{Digest as _, Sha256};

const MAX_REGISTRATION_BYTES: usize = 512 * 1024;
const MAX_SCHEMA_BYTES: usize = 256 * 1024;
const MAX_FIXTURE_ARTIFACT_BYTES: usize = 512 * 1024;

/// Durable receipt for an exact fixture-only Wave 6 program registration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6ProgramRegistrationReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub program_id: StableString,
    pub registration_digest: ValueDigest,
    pub document_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
    pub status: IdempotencyStatus,
}

/// Exact Wave 6 registration re-parsed and reverified after durable readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6ProgramRegistration {
    pub batch_id: StableString,
    pub program_id: StableString,
    pub exact_bytes: Vec<u8>,
    pub registration_digest: ValueDigest,
    pub document_digest: ValueDigest,
    pub registered_at: UtcTimestamp,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
}

/// Durable receipt for one exact schema named by the frozen Wave 6 registration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6ArtifactSchemaReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub program_id: StableString,
    pub kind_id: StableString,
    pub schema_id: StableString,
    pub schema_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
    pub status: IdempotencyStatus,
}

/// Exact registered schema rehashed and reverified after durable readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6ArtifactSchema {
    pub batch_id: StableString,
    pub program_id: StableString,
    pub kind_id: StableString,
    pub schema_id: StableString,
    pub exact_bytes: Vec<u8>,
    pub schema_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
}

/// Durable byte-retention receipt for one exact fixture-only evaluation artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6FixtureArtifactReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub artifact_id: StableString,
    pub program_id: StableString,
    pub kind_id: StableString,
    pub schema_id: StableString,
    pub content_digest: ValueDigest,
    pub evaluation_digest: ValueDigest,
    pub result_count: u64,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
    pub status: IdempotencyStatus,
}

/// Exact fixture artifact content re-parsed and reverified after durable readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6FixtureArtifact {
    pub batch_id: StableString,
    pub artifact_id: StableString,
    pub program_id: StableString,
    pub kind_id: StableString,
    pub schema_id: StableString,
    pub schema_digest: ValueDigest,
    pub schema_commit_seq: CommitSeq,
    pub exact_bytes: Vec<u8>,
    pub content_digest: ValueDigest,
    pub evaluation_digest: ValueDigest,
    pub result_count: u64,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
}

struct RegistrationRow {
    batch_id: String,
    family_id: String,
    semantic_version: String,
    registration_raw: String,
    document_raw: String,
    bytes: Vec<u8>,
    byte_length: i64,
    source_tree_raw: String,
    build_raw: String,
    environment_raw: String,
    config_raw: String,
    gate_count: i64,
    artifact_count: i64,
    symbol_count: i64,
    compute_units: i64,
    read_units: i64,
    attention_units: i64,
    provider_units: i64,
    external_mutation_units: i64,
    max_artifacts: i64,
    registered_us: i64,
    authority: String,
    semantic_ceiling: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

struct ArtifactSchemaRow {
    batch_id: String,
    schema_id: String,
    schema_raw: String,
    bytes: Vec<u8>,
    byte_length: i64,
    authority: String,
    semantic_ceiling: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

struct FixtureArtifactRow {
    batch_id: String,
    program_id: String,
    kind_id: String,
    schema_id: String,
    schema_raw: String,
    schema_commit_seq: i64,
    content_raw: String,
    evaluation_raw: String,
    bytes: Vec<u8>,
    byte_length: i64,
    result_count: i64,
    semantic_ceiling: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

impl SqliteStore {
    /// Parses and durably registers one exact, fixture-only Wave 6 N00 document.
    ///
    /// The store owns commit time/order. V1 refuses any consumed Wave 5 gate reference rather than
    /// treating a caller reference as resolved authority.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical or oversized bytes, semantic/digest failure, any gate reference,
    /// future fixture time, nonzero provider/external budget, conflicting identity, read-only
    /// state, or failed durable readback.
    pub fn commit_wave6_program_registration_v1(
        &mut self,
        exact_bytes: &[u8],
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6ProgramRegistrationReceipt> {
        if exact_bytes.len() > MAX_REGISTRATION_BYTES {
            return Err(StoreError::InvalidBatch(
                "Wave 6 program registration exceeds the exact-byte limit".into(),
            ));
        }
        let validated = parse_program_registration_exact(exact_bytes)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let value = validated.value();
        if !value.consumed_wave5_gates.is_empty() {
            return Err(StoreError::InvalidBatch(
                "Wave 6 fixture registration cannot consume unresolved Wave 5 gate references"
                    .into(),
            ));
        }
        let program_id = value.program_id.clone();
        let existing_batch: Option<String> = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id
                 FROM wave6_program_registration_v1 registration
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=registration.created_commit_seq
                 WHERE registration.program_id=?1",
                [program_id.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        if existing_batch
            .as_deref()
            .is_some_and(|existing| existing != batch_id.as_str())
        {
            return Err(StoreError::IdentityConflict {
                kind: "Wave 6 program registration",
                identity: program_id.to_string(),
            });
        }

        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        if value.registered_at > context.committed_at() {
            return Err(StoreError::InvalidBatch(
                "Wave 6 fixture registration is future-dated relative to its store commit".into(),
            ));
        }
        let operation_digest = operation_digest(
            &program_id,
            &value.registration_digest,
            validated.document_digest(),
        )?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &program_id,
            validated.document_digest(),
            &operation_digest,
            |tx, seq| insert_registration(tx, seq, &validated),
        )?;
        let stored = self
            .load_wave6_program_registration_v1(&program_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 program registration",
                identity: program_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.exact_bytes != exact_bytes
            || stored.document_digest != *validated.document_digest()
            || stored.registration_digest != value.registration_digest
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 registration readback differs from its exact commit".into(),
            ));
        }
        Ok(Wave6ProgramRegistrationReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            program_id,
            registration_digest: stored.registration_digest,
            document_digest: stored.document_digest,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            semantic_ceiling: stored.semantic_ceiling,
            status: generic.status,
        })
    }

    /// Loads, re-parses, and cross-checks one exact Wave 6 fixture registration.
    ///
    /// # Errors
    ///
    /// Refuses changed bytes, divergent scalar columns, invalid commit lineage, or malformed
    /// persisted identities.
    pub fn load_wave6_program_registration_v1(
        &self,
        program_id: &StableString,
    ) -> Result<Option<StoredWave6ProgramRegistration>> {
        let row: Option<RegistrationRow> = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id,registration.program_family_id,
                        registration.semantic_version,registration.registration_semantic_sha256,
                        registration.registration_document_sha256,registration.registration_bytes,
                        registration.registration_byte_length,registration.source_tree_sha256,
                        registration.build_sha256,registration.environment_sha256,
                        registration.config_sha256,registration.consumed_wave5_gate_count,
                        registration.artifact_kind_count,registration.local_symbol_count,
                        registration.compute_units,registration.read_units,
                        registration.attention_units,registration.provider_units,
                        registration.external_mutation_units,registration.max_artifacts,
                        registration.fixture_registered_wall_us,registration.authority,
                        registration.semantic_ceiling,registration.created_commit_seq,
                        commit_row.commit_digest
                 FROM wave6_program_registration_v1 registration
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=registration.created_commit_seq
                 WHERE registration.program_id=?1",
                [program_id.as_str()],
                |row| {
                    Ok(RegistrationRow {
                        batch_id: row.get(0)?,
                        family_id: row.get(1)?,
                        semantic_version: row.get(2)?,
                        registration_raw: row.get(3)?,
                        document_raw: row.get(4)?,
                        bytes: row.get(5)?,
                        byte_length: row.get(6)?,
                        source_tree_raw: row.get(7)?,
                        build_raw: row.get(8)?,
                        environment_raw: row.get(9)?,
                        config_raw: row.get(10)?,
                        gate_count: row.get(11)?,
                        artifact_count: row.get(12)?,
                        symbol_count: row.get(13)?,
                        compute_units: row.get(14)?,
                        read_units: row.get(15)?,
                        attention_units: row.get(16)?,
                        provider_units: row.get(17)?,
                        external_mutation_units: row.get(18)?,
                        max_artifacts: row.get(19)?,
                        registered_us: row.get(20)?,
                        authority: row.get(21)?,
                        semantic_ceiling: row.get(22)?,
                        commit_seq: row.get(23)?,
                        commit_digest_raw: row.get(24)?,
                    })
                },
            )
            .optional()?;
        let Some(row) = row else {
            return Ok(None);
        };
        stored_registration(program_id, row).map(Some)
    }

    /// Persists one exact canonical schema whose kind/digest are named by the stored N00 program.
    ///
    /// # Errors
    ///
    /// Refuses an absent program/kind, noncanonical or oversized JSON, a digest mismatch,
    /// conflicting identity, read-only state, or failed exact readback.
    pub fn commit_wave6_artifact_schema_v1(
        &mut self,
        program_id: &StableString,
        kind_id: StableString,
        exact_bytes: &[u8],
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6ArtifactSchemaReceipt> {
        validate_canonical_schema(exact_bytes)?;
        let registration = self
            .load_wave6_program_registration_v1(program_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 program registration",
                identity: program_id.to_string(),
            })?;
        let parsed = parse_program_registration_exact(&registration.exact_bytes)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let kind = parsed
            .value()
            .artifact_kinds
            .iter()
            .find(|candidate| candidate.kind_id == kind_id)
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 registered artifact kind",
                identity: kind_id.to_string(),
            })?;
        let actual_digest = digest_bytes(exact_bytes)?;
        if actual_digest != kind.schema_digest {
            return Err(StoreError::InvalidBatch(
                "Wave 6 schema bytes differ from the digest registered for their kind".into(),
            ));
        }
        let schema_id = kind.schema_id.clone();
        reject_second_schema_batch(self, program_id, &kind_id, &batch_id)?;
        let occurrence_id = schema_occurrence_id(program_id, &kind_id, &schema_id)?;
        let operation_digest =
            schema_operation_digest(program_id, &kind_id, &schema_id, &actual_digest)?;
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &occurrence_id,
            &actual_digest,
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_registered_artifact_schema_v1
                     (program_id,kind_id,schema_id,schema_sha256,schema_bytes,
                      schema_byte_length,authority,semantic_ceiling,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
                    params![
                        program_id.as_str(),
                        kind_id.as_str(),
                        schema_id.as_str(),
                        raw_digest(&actual_digest, "Wave 6 schema digest")?,
                        exact_bytes,
                        sqlite_len(exact_bytes.len(), "Wave 6 schema bytes")?,
                        "read_record_replay_propose_shadow_only",
                        "unverified_semantic_fixture_only",
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_wave6_artifact_schema_v1(program_id, &kind_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 artifact schema",
                identity: kind_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.schema_id != schema_id
            || stored.exact_bytes != exact_bytes
            || stored.schema_digest != actual_digest
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 schema readback differs from its exact commit".into(),
            ));
        }
        Ok(Wave6ArtifactSchemaReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            program_id: program_id.clone(),
            kind_id,
            schema_id,
            schema_digest: stored.schema_digest,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            semantic_ceiling: stored.semantic_ceiling,
            status: generic.status,
        })
    }

    /// Loads and independently rehashes one exact schema registered to the N00 program.
    ///
    /// # Errors
    ///
    /// Refuses changed/noncanonical bytes, divergent registration mapping or malformed commit
    /// lineage.
    pub fn load_wave6_artifact_schema_v1(
        &self,
        program_id: &StableString,
        kind_id: &StableString,
    ) -> Result<Option<StoredWave6ArtifactSchema>> {
        let row: Option<ArtifactSchemaRow> = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id,schema_row.schema_id,schema_row.schema_sha256,
                        schema_row.schema_bytes,schema_row.schema_byte_length,
                        schema_row.authority,schema_row.semantic_ceiling,
                        schema_row.created_commit_seq,commit_row.commit_digest
                 FROM wave6_registered_artifact_schema_v1 schema_row
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=schema_row.created_commit_seq
                 WHERE schema_row.program_id=?1 AND schema_row.kind_id=?2",
                params![program_id.as_str(), kind_id.as_str()],
                |row| {
                    Ok(ArtifactSchemaRow {
                        batch_id: row.get(0)?,
                        schema_id: row.get(1)?,
                        schema_raw: row.get(2)?,
                        bytes: row.get(3)?,
                        byte_length: row.get(4)?,
                        authority: row.get(5)?,
                        semantic_ceiling: row.get(6)?,
                        commit_seq: row.get(7)?,
                        commit_digest_raw: row.get(8)?,
                    })
                },
            )
            .optional()?;
        let Some(row) = row else {
            return Ok(None);
        };
        stored_artifact_schema(self, program_id, kind_id, row).map(Some)
    }

    /// Persists one exact evaluation output under its prior registered kind/schema.
    ///
    /// This receipt proves byte durability only. The content remains fixture-only and has no
    /// information-cutoff, artifact-DAG, Wave 5 gate, empirical, product, or live authority.
    ///
    /// # Errors
    ///
    /// Refuses an absent schema, unsupported or noncanonical artifact bytes, changed fixture
    /// inputs/denominator/self-digest, oversized content, a conflicting identity, read-only state,
    /// exhausted fixture budget, or failed exact readback.
    #[allow(clippy::too_many_lines)] // Keeps parse, atomic append, and exact readback adjacent.
    pub fn commit_wave6_fixture_artifact_v1(
        &mut self,
        program_id: &StableString,
        kind_id: StableString,
        exact_bytes: &[u8],
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6FixtureArtifactReceipt> {
        if exact_bytes.is_empty() || exact_bytes.len() > MAX_FIXTURE_ARTIFACT_BYTES {
            return Err(StoreError::InvalidBatch(
                "Wave 6 fixture artifact is empty or exceeds the exact-byte limit".into(),
            ));
        }
        let schema = self
            .load_wave6_artifact_schema_v1(program_id, &kind_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 artifact schema",
                identity: format!("{}:{}", program_id.as_str(), kind_id.as_str()),
            })?;
        let parsed = parse_evaluation_artifact_exact(&kind_id, &schema.schema_id, exact_bytes)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let content_digest = parsed.content_digest().clone();
        let evaluation_digest = parsed.evaluation_digest().clone();
        let result_count =
            u64::try_from(parsed.value().result_count()).map_err(|_| StoreError::IntegerRange {
                field: "Wave 6 fixture result count",
                value: parsed.value().result_count().to_string(),
            })?;
        let artifact_id = artifact_content_id(program_id, &kind_id, &content_digest)?;
        reject_second_artifact_batch(self, &artifact_id, &batch_id)?;
        let operation_digest = artifact_operation_digest(
            program_id,
            &kind_id,
            &schema.schema_id,
            &schema.schema_digest,
            &content_digest,
            &evaluation_digest,
        )?;
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &artifact_id,
            &content_digest,
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_fixture_artifact_content_v1
                     (artifact_id,program_id,kind_id,schema_id,schema_sha256,
                      schema_created_commit_seq,content_sha256,evaluation_semantic_sha256,
                      artifact_bytes,artifact_byte_length,result_count,semantic_ceiling,
                      created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
                    params![
                        artifact_id.as_str(),
                        program_id.as_str(),
                        kind_id.as_str(),
                        schema.schema_id.as_str(),
                        raw_digest(&schema.schema_digest, "Wave 6 artifact schema digest")?,
                        sqlite_u64(schema.commit_seq.get(), "Wave 6 schema commit")?,
                        raw_digest(&content_digest, "Wave 6 artifact content digest")?,
                        raw_digest(&evaluation_digest, "Wave 6 evaluation digest")?,
                        exact_bytes,
                        sqlite_len(exact_bytes.len(), "Wave 6 artifact bytes")?,
                        sqlite_u64(result_count, "Wave 6 fixture result count")?,
                        "unverified_semantic_fixture_only",
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_wave6_fixture_artifact_v1(&artifact_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 fixture artifact",
                identity: artifact_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.program_id != *program_id
            || stored.kind_id != kind_id
            || stored.schema_id != schema.schema_id
            || stored.schema_digest != schema.schema_digest
            || stored.schema_commit_seq != schema.commit_seq
            || stored.exact_bytes != exact_bytes
            || stored.content_digest != content_digest
            || stored.evaluation_digest != evaluation_digest
            || stored.result_count != result_count
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 fixture artifact readback differs from its exact commit".into(),
            ));
        }
        Ok(Wave6FixtureArtifactReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            artifact_id,
            program_id: program_id.clone(),
            kind_id,
            schema_id: stored.schema_id,
            content_digest: stored.content_digest,
            evaluation_digest: stored.evaluation_digest,
            result_count: stored.result_count,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            semantic_ceiling: stored.semantic_ceiling,
            status: generic.status,
        })
    }

    /// Loads and independently reparses one exact fixture-only evaluation artifact.
    ///
    /// # Errors
    ///
    /// Refuses changed bytes, schema mapping, semantic/physical digest, result count, ceiling or
    /// commit lineage.
    pub fn load_wave6_fixture_artifact_v1(
        &self,
        artifact_id: &StableString,
    ) -> Result<Option<StoredWave6FixtureArtifact>> {
        let row: Option<FixtureArtifactRow> = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id,artifact.program_id,artifact.kind_id,
                        artifact.schema_id,artifact.schema_sha256,
                        artifact.schema_created_commit_seq,artifact.content_sha256,
                        artifact.evaluation_semantic_sha256,artifact.artifact_bytes,
                        artifact.artifact_byte_length,artifact.result_count,
                        artifact.semantic_ceiling,artifact.created_commit_seq,
                        commit_row.commit_digest
                 FROM wave6_fixture_artifact_content_v1 artifact
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=artifact.created_commit_seq
                 WHERE artifact.artifact_id=?1",
                [artifact_id.as_str()],
                |row| {
                    Ok(FixtureArtifactRow {
                        batch_id: row.get(0)?,
                        program_id: row.get(1)?,
                        kind_id: row.get(2)?,
                        schema_id: row.get(3)?,
                        schema_raw: row.get(4)?,
                        schema_commit_seq: row.get(5)?,
                        content_raw: row.get(6)?,
                        evaluation_raw: row.get(7)?,
                        bytes: row.get(8)?,
                        byte_length: row.get(9)?,
                        result_count: row.get(10)?,
                        semantic_ceiling: row.get(11)?,
                        commit_seq: row.get(12)?,
                        commit_digest_raw: row.get(13)?,
                    })
                },
            )
            .optional()?;
        let Some(row) = row else {
            return Ok(None);
        };
        stored_fixture_artifact(self, artifact_id, row).map(Some)
    }
}

fn validate_canonical_schema(bytes: &[u8]) -> Result<()> {
    if bytes.is_empty() || bytes.len() > MAX_SCHEMA_BYTES {
        return Err(StoreError::InvalidBatch(
            "Wave 6 schema is empty or exceeds the exact-byte limit".into(),
        ));
    }
    let body = bytes.strip_suffix(b"\n").ok_or_else(|| {
        StoreError::InvalidBatch("Wave 6 schema must end in exactly one newline".into())
    })?;
    if body.ends_with(b"\n") {
        return Err(StoreError::InvalidBatch(
            "Wave 6 schema must end in exactly one newline".into(),
        ));
    }
    let value: serde_json::Value = serde_json::from_slice(body)?;
    if !value.is_object() {
        return Err(StoreError::InvalidBatch(
            "Wave 6 schema must be a JSON object".into(),
        ));
    }
    Ok(())
}

fn reject_second_schema_batch(
    store: &SqliteStore,
    program_id: &StableString,
    kind_id: &StableString,
    batch_id: &StableString,
) -> Result<()> {
    let existing: Option<String> = store
        .connection
        .query_row(
            "SELECT commit_row.commit_id
             FROM wave6_registered_artifact_schema_v1 schema_row
             JOIN ingest_commit commit_row
               ON commit_row.commit_seq=schema_row.created_commit_seq
             WHERE schema_row.program_id=?1 AND schema_row.kind_id=?2",
            params![program_id.as_str(), kind_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|value| value != batch_id.as_str())
    {
        return Err(StoreError::IdentityConflict {
            kind: "Wave 6 artifact schema",
            identity: format!("{}:{}", program_id.as_str(), kind_id.as_str()),
        });
    }
    Ok(())
}

fn schema_operation_digest(
    program_id: &StableString,
    kind_id: &StableString,
    schema_id: &StableString,
    schema_digest: &ValueDigest,
) -> Result<ValueDigest> {
    let bytes = serde_json::to_vec(&(
        "joshi.store.wave6_artifact_schema_commit.v1",
        program_id,
        kind_id,
        schema_id,
        schema_digest,
    ))?;
    digest_bytes(&bytes)
}

fn schema_occurrence_id(
    program_id: &StableString,
    kind_id: &StableString,
    schema_id: &StableString,
) -> Result<StableString> {
    let bytes = serde_json::to_vec(&(
        "joshi.store.wave6_artifact_schema_identity.v1",
        program_id,
        kind_id,
        schema_id,
    ))?;
    let digest = digest_bytes(&bytes)?;
    stable(
        &format!(
            "wave6-schema:{}",
            raw_digest(&digest, "Wave 6 schema occurrence digest")?
        ),
        "Wave 6 schema occurrence ID",
    )
}

fn stored_artifact_schema(
    store: &SqliteStore,
    program_id: &StableString,
    kind_id: &StableString,
    row: ArtifactSchemaRow,
) -> Result<StoredWave6ArtifactSchema> {
    validate_canonical_schema(&row.bytes)?;
    let registration = store
        .load_wave6_program_registration_v1(program_id)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 program registration",
            identity: program_id.to_string(),
        })?;
    let parsed = parse_program_registration_exact(&registration.exact_bytes)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let kind = parsed
        .value()
        .artifact_kinds
        .iter()
        .find(|candidate| candidate.kind_id == *kind_id)
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 registered artifact kind",
            identity: kind_id.to_string(),
        })?;
    let actual_digest = digest_bytes(&row.bytes)?;
    if row.schema_id != kind.schema_id.as_str()
        || actual_digest != kind.schema_digest
        || raw_digest(&actual_digest, "Wave 6 schema digest")? != row.schema_raw
        || usize_from_i64(row.byte_length, "Wave 6 schema byte length")? != row.bytes.len()
        || row.authority != "read_record_replay_propose_shadow_only"
        || row.semantic_ceiling != "unverified_semantic_fixture_only"
    {
        return Err(StoreError::InvalidBatch(
            "persisted Wave 6 schema differs from its exact registered mapping".into(),
        ));
    }
    Ok(StoredWave6ArtifactSchema {
        batch_id: stable(&row.batch_id, "Wave 6 schema batch ID")?,
        program_id: program_id.clone(),
        kind_id: kind_id.clone(),
        schema_id: kind.schema_id.clone(),
        exact_bytes: row.bytes,
        schema_digest: actual_digest,
        commit_seq: CommitSeq::new(u64_from_i64(row.commit_seq, "Wave 6 schema commit")?),
        commit_digest: qualified_digest(&row.commit_digest_raw, "Wave 6 schema commit digest")?,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    })
}

fn reject_second_artifact_batch(
    store: &SqliteStore,
    artifact_id: &StableString,
    batch_id: &StableString,
) -> Result<()> {
    let existing: Option<String> = store
        .connection
        .query_row(
            "SELECT commit_row.commit_id
             FROM wave6_fixture_artifact_content_v1 artifact
             JOIN ingest_commit commit_row
               ON commit_row.commit_seq=artifact.created_commit_seq
             WHERE artifact.artifact_id=?1",
            [artifact_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|value| value != batch_id.as_str())
    {
        return Err(StoreError::IdentityConflict {
            kind: "Wave 6 fixture artifact",
            identity: artifact_id.to_string(),
        });
    }
    Ok(())
}

fn artifact_content_id(
    program_id: &StableString,
    kind_id: &StableString,
    content_digest: &ValueDigest,
) -> Result<StableString> {
    let bytes = serde_json::to_vec(&(
        "joshi.store.wave6_fixture_artifact_identity.v1",
        program_id,
        kind_id,
        content_digest,
    ))?;
    let digest = digest_bytes(&bytes)?;
    stable(
        &format!(
            "wave6-artifact:{}",
            raw_digest(&digest, "Wave 6 artifact identity digest")?
        ),
        "Wave 6 fixture artifact ID",
    )
}

fn artifact_operation_digest(
    program_id: &StableString,
    kind_id: &StableString,
    schema_id: &StableString,
    schema_digest: &ValueDigest,
    content_digest: &ValueDigest,
    evaluation_digest: &ValueDigest,
) -> Result<ValueDigest> {
    let bytes = serde_json::to_vec(&(
        "joshi.store.wave6_fixture_artifact_commit.v1",
        program_id,
        kind_id,
        schema_id,
        schema_digest,
        content_digest,
        evaluation_digest,
    ))?;
    digest_bytes(&bytes)
}

fn stored_fixture_artifact(
    store: &SqliteStore,
    artifact_id: &StableString,
    row: FixtureArtifactRow,
) -> Result<StoredWave6FixtureArtifact> {
    let program_id = stable(&row.program_id, "Wave 6 artifact program ID")?;
    let kind_id = stable(&row.kind_id, "Wave 6 artifact kind ID")?;
    let schema = store
        .load_wave6_artifact_schema_v1(&program_id, &kind_id)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 artifact schema",
            identity: format!("{}:{}", program_id.as_str(), kind_id.as_str()),
        })?;
    let parsed = parse_evaluation_artifact_exact(&kind_id, &schema.schema_id, &row.bytes)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let expected_id = artifact_content_id(&program_id, &kind_id, parsed.content_digest())?;
    let result_count =
        u64::try_from(parsed.value().result_count()).map_err(|_| StoreError::IntegerRange {
            field: "Wave 6 fixture result count",
            value: parsed.value().result_count().to_string(),
        })?;
    if expected_id != *artifact_id
        || row.schema_id != schema.schema_id.as_str()
        || row.schema_raw != raw_digest(&schema.schema_digest, "Wave 6 artifact schema digest")?
        || u64_from_i64(row.schema_commit_seq, "Wave 6 artifact schema commit")?
            != schema.commit_seq.get()
        || row.content_raw != raw_digest(parsed.content_digest(), "Wave 6 artifact content digest")?
        || row.evaluation_raw != raw_digest(parsed.evaluation_digest(), "Wave 6 evaluation digest")?
        || usize_from_i64(row.byte_length, "Wave 6 artifact byte length")? != row.bytes.len()
        || u64_from_i64(row.result_count, "Wave 6 fixture result count")? != result_count
        || row.semantic_ceiling != "unverified_semantic_fixture_only"
        || row.schema_commit_seq >= row.commit_seq
    {
        return Err(StoreError::InvalidBatch(
            "persisted Wave 6 artifact differs from exact bytes or registered schema".into(),
        ));
    }
    Ok(StoredWave6FixtureArtifact {
        batch_id: stable(&row.batch_id, "Wave 6 artifact batch ID")?,
        artifact_id: artifact_id.clone(),
        program_id,
        kind_id,
        schema_id: schema.schema_id,
        schema_digest: schema.schema_digest,
        schema_commit_seq: schema.commit_seq,
        exact_bytes: row.bytes,
        content_digest: parsed.content_digest().clone(),
        evaluation_digest: parsed.evaluation_digest().clone(),
        result_count,
        commit_seq: CommitSeq::new(u64_from_i64(row.commit_seq, "Wave 6 artifact commit")?),
        commit_digest: qualified_digest(&row.commit_digest_raw, "Wave 6 artifact commit digest")?,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    })
}

fn insert_registration(
    tx: &Transaction<'_>,
    seq: i64,
    validated: &ValidatedProgramRegistration,
) -> Result<()> {
    let value = validated.value();
    tx.execute(
        "INSERT INTO wave6_program_registration_v1
         (program_id,program_family_id,semantic_version,
          registration_semantic_sha256,registration_document_sha256,
          registration_bytes,registration_byte_length,
          source_tree_sha256,build_sha256,environment_sha256,config_sha256,
          consumed_wave5_gate_count,artifact_kind_count,local_symbol_count,
          compute_units,read_units,attention_units,provider_units,
          external_mutation_units,max_artifacts,fixture_registered_wall_us,
          authority,semantic_ceiling,created_commit_seq)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,
                 ?15,?16,?17,?18,?19,?20,?21,?22,?23,?24)",
        params![
            value.program_id.as_str(),
            value.program_family_id.as_str(),
            value.semantic_version.as_str(),
            raw_digest(&value.registration_digest, "registration semantic digest")?,
            raw_digest(validated.document_digest(), "registration document digest")?,
            validated.exact_bytes(),
            sqlite_len(validated.exact_bytes().len(), "registration bytes")?,
            raw_digest(&value.source_tree_digest, "source tree digest")?,
            raw_digest(&value.build_digest, "build digest")?,
            raw_digest(&value.environment_digest, "environment digest")?,
            raw_digest(&value.config_digest, "config digest")?,
            sqlite_len(value.consumed_wave5_gates.len(), "Wave 5 gate count")?,
            sqlite_len(value.artifact_kinds.len(), "artifact kind count")?,
            sqlite_len(value.local_symbols.len(), "local symbol count")?,
            sqlite_u64(value.budgets.compute_units.get(), "compute units")?,
            sqlite_u64(value.budgets.read_units.get(), "read units")?,
            sqlite_u64(value.budgets.attention_units.get(), "attention units")?,
            sqlite_u64(value.budgets.provider_units.get(), "provider units")?,
            sqlite_u64(
                value.budgets.external_mutation_units.get(),
                "external mutation units",
            )?,
            sqlite_u64(value.budgets.max_artifacts.get(), "maximum artifacts")?,
            timestamp_us(value.registered_at, "fixture registeredAt")?,
            "read_record_replay_propose_shadow_only",
            "unverified_semantic_fixture_only",
            seq,
        ],
    )?;
    Ok(())
}

fn stored_registration(
    program_id: &StableString,
    row: RegistrationRow,
) -> Result<StoredWave6ProgramRegistration> {
    let validated = parse_program_registration_exact(&row.bytes)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let value = validated.value();
    let registered_us = timestamp_us(value.registered_at, "fixture registeredAt")?;
    if value.program_id != *program_id
        || value.program_family_id.as_str() != row.family_id
        || value.semantic_version.as_str() != row.semantic_version
        || raw_digest(&value.registration_digest, "registration semantic digest")?
            != row.registration_raw
        || raw_digest(validated.document_digest(), "registration document digest")?
            != row.document_raw
        || usize_from_i64(row.byte_length, "registration byte length")? != row.bytes.len()
        || raw_digest(&value.source_tree_digest, "source tree digest")? != row.source_tree_raw
        || raw_digest(&value.build_digest, "build digest")? != row.build_raw
        || raw_digest(&value.environment_digest, "environment digest")? != row.environment_raw
        || raw_digest(&value.config_digest, "config digest")? != row.config_raw
        || usize_from_i64(row.gate_count, "Wave 5 gate count")? != value.consumed_wave5_gates.len()
        || usize_from_i64(row.artifact_count, "artifact kind count")? != value.artifact_kinds.len()
        || usize_from_i64(row.symbol_count, "local symbol count")? != value.local_symbols.len()
        || u64_from_i64(row.compute_units, "compute units")? != value.budgets.compute_units.get()
        || u64_from_i64(row.read_units, "read units")? != value.budgets.read_units.get()
        || u64_from_i64(row.attention_units, "attention units")?
            != value.budgets.attention_units.get()
        || u64_from_i64(row.provider_units, "provider units")? != value.budgets.provider_units.get()
        || u64_from_i64(row.external_mutation_units, "external mutation units")?
            != value.budgets.external_mutation_units.get()
        || u64_from_i64(row.max_artifacts, "maximum artifacts")?
            != value.budgets.max_artifacts.get()
        || registered_us != row.registered_us
        || row.authority != "read_record_replay_propose_shadow_only"
        || row.semantic_ceiling != "unverified_semantic_fixture_only"
    {
        return Err(StoreError::InvalidBatch(
            "persisted Wave 6 registration columns differ from exact bytes".into(),
        ));
    }
    Ok(StoredWave6ProgramRegistration {
        batch_id: stable(&row.batch_id, "Wave 6 registration batch ID")?,
        program_id: program_id.clone(),
        exact_bytes: row.bytes,
        registration_digest: value.registration_digest.clone(),
        document_digest: validated.document_digest().clone(),
        registered_at: value.registered_at,
        commit_seq: CommitSeq::new(u64_from_i64(row.commit_seq, "Wave 6 commit sequence")?),
        commit_digest: qualified_digest(&row.commit_digest_raw, "Wave 6 commit digest")?,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    })
}

fn operation_digest(
    program_id: &StableString,
    registration_digest: &ValueDigest,
    document_digest: &ValueDigest,
) -> Result<ValueDigest> {
    let bytes = serde_json::to_vec(&(
        "joshi.store.wave6_program_registration_commit.v1",
        program_id,
        registration_digest,
        document_digest,
    ))?;
    digest_bytes(&bytes)
}

fn digest_bytes(bytes: &[u8]) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}

fn raw_digest<'a>(value: &'a ValueDigest, field: &'static str) -> Result<&'a str> {
    value
        .as_str()
        .strip_prefix("sha256:")
        .filter(|raw| {
            raw.len() == 64
                && raw
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        })
        .ok_or_else(|| StoreError::InvalidBatch(format!("{field} is not canonical SHA-256")))
}

fn qualified_digest(raw: &str, field: &'static str) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{raw}"))
        .map_err(|error| StoreError::InvalidBatch(format!("{field}: {error}")))
}

fn stable(value: &str, field: &'static str) -> Result<StableString> {
    StableString::new(value.to_owned())
        .map_err(|error| StoreError::InvalidBatch(format!("{field}: {error}")))
}

fn timestamp_us(value: UtcTimestamp, field: &'static str) -> Result<i64> {
    let nanos = value.as_datetime().unix_timestamp_nanos();
    if nanos % 1_000 != 0 {
        return Err(StoreError::TimestampRange { field });
    }
    let micros: i64 = (nanos / 1_000)
        .try_into()
        .map_err(|_| StoreError::TimestampRange { field })?;
    if micros <= 0 {
        return Err(StoreError::TimestampRange { field });
    }
    Ok(micros)
}

fn sqlite_len(value: usize, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn sqlite_u64(value: u64, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn usize_from_i64(value: i64, field: &'static str) -> Result<usize> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn u64_from_i64(value: i64, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{StoreConfig, StoreMode};
    use joshi_wave6_registry::{
        Wave5GateRefV1, Wave5GateV1, Wave6ProgramRegistrationV1, canonical_bytes, digest_bytes,
    };
    use std::time::Duration;

    const REGISTRATION: &[u8] =
        include_bytes!("../../../fixtures/wave6/program_registration_v1.json");

    fn schemas() -> [(&'static str, &'static [u8]); 6] {
        [
            (
                "campaign_registration_fixture",
                include_bytes!("../../../fixtures/wave6/schemas/campaign_registration_v1.json"),
            ),
            (
                "known_truth_evaluation_fixture",
                include_bytes!("../../../fixtures/wave6/schemas/known_truth_evaluation_v1.json"),
            ),
            (
                "market_atlas_fixture",
                include_bytes!("../../../fixtures/wave6/schemas/market_atlas_snapshot_v1.json"),
            ),
            (
                "protocol_known_truth_evaluation_fixture",
                include_bytes!(
                    "../../../fixtures/wave6/schemas/protocol_known_truth_evaluation_v1.json"
                ),
            ),
            (
                "research_proposal_fixture",
                include_bytes!("../../../fixtures/wave6/schemas/research_proposal_v1.json"),
            ),
            (
                "structural_known_truth_evaluation_fixture",
                include_bytes!(
                    "../../../fixtures/wave6/schemas/structural_known_truth_evaluation_v1.json"
                ),
            ),
        ]
    }

    fn artifacts() -> [(&'static str, &'static [u8]); 3] {
        [
            (
                "known_truth_evaluation_fixture",
                include_bytes!("../../../fixtures/wave6/artifacts/known_truth_evaluation_v1.json"),
            ),
            (
                "protocol_known_truth_evaluation_fixture",
                include_bytes!(
                    "../../../fixtures/wave6/artifacts/protocol_known_truth_evaluation_v1.json"
                ),
            ),
            (
                "structural_known_truth_evaluation_fixture",
                include_bytes!(
                    "../../../fixtures/wave6/artifacts/structural_known_truth_evaluation_v1.json"
                ),
            ),
        ]
    }

    fn config(root: &std::path::Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(2),
            catalog_id: StableString::new("wave6-registry-test").expect("catalog ID"),
            max_observations_per_batch: 256,
            max_raw_bytes_per_batch: 4 * 1024 * 1024,
        }
    }

    #[test]
    fn exact_fixture_registration_is_durable_idempotent_and_never_promoted() {
        let root = tempfile::tempdir().expect("temporary store");
        let store_config = config(root.path());
        let mut store =
            SqliteStore::open(store_config.clone(), StoreMode::SingleWriter).expect("writer store");
        let migration = store
            .migrate(
                "2026-08-18T16:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        assert_eq!(migration.current, 13);
        let batch_id =
            StableString::new("wave6:program-registration:fixture-001").expect("batch ID");
        let build = StableString::new("wave6-store-test").expect("build ID");
        let accepted = store
            .commit_wave6_program_registration_v1(REGISTRATION, batch_id.clone(), build.clone())
            .expect("accepted registration");
        assert_eq!(accepted.status, IdempotencyStatus::Accepted);
        assert_eq!(accepted.catalog_schema.as_str(), "joshi.sqlite.v13");
        assert_eq!(
            accepted.semantic_ceiling,
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
        let retry = store
            .commit_wave6_program_registration_v1(REGISTRATION, batch_id, build)
            .expect("idempotent registration");
        assert_eq!(retry.status, IdempotencyStatus::Idempotent);
        assert_eq!(retry.commit_seq, accepted.commit_seq);
        assert_eq!(retry.commit_digest, accepted.commit_digest);
        drop(store);

        let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly).expect("reader store");
        let stored = reopened
            .load_wave6_program_registration_v1(&accepted.program_id)
            .expect("registration readback")
            .expect("registered program");
        assert_eq!(stored.exact_bytes, REGISTRATION);
        assert_eq!(stored.registration_digest, accepted.registration_digest);
        assert_eq!(stored.document_digest, accepted.document_digest);
        assert_eq!(stored.commit_digest, accepted.commit_digest);
        assert_eq!(
            stored.semantic_ceiling,
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
    }

    #[test]
    fn changed_or_second_batch_identity_cannot_replace_program() {
        let root = tempfile::tempdir().expect("temporary store");
        let mut store =
            SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("writer store");
        store
            .migrate(
                "2026-08-18T16:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        let batch_id =
            StableString::new("wave6:program-registration:fixture-001").expect("batch ID");
        let build = StableString::new("wave6-store-test").expect("build ID");
        store
            .commit_wave6_program_registration_v1(REGISTRATION, batch_id.clone(), build.clone())
            .expect("accepted registration");

        let mut changed = REGISTRATION.to_vec();
        let index = changed
            .windows(b"fixture_roundtrip".len())
            .position(|window| window == b"fixture_roundtrip")
            .expect("fixture maturity token");
        changed[index] = b'F';
        assert!(
            store
                .commit_wave6_program_registration_v1(&changed, batch_id, build.clone())
                .is_err()
        );
        assert!(matches!(
            store.commit_wave6_program_registration_v1(
                REGISTRATION,
                StableString::new("wave6:program-registration:second").expect("second batch"),
                build,
            ),
            Err(StoreError::IdentityConflict { .. })
        ));
    }

    #[test]
    fn caller_gate_reference_is_never_treated_as_store_resolution() {
        let root = tempfile::tempdir().expect("temporary store");
        let mut store =
            SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("writer store");
        store
            .migrate(
                "2026-08-18T16:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        let mut value: Wave6ProgramRegistrationV1 =
            serde_json::from_slice(REGISTRATION).expect("registration fixture");
        value.consumed_wave5_gates.push(Wave5GateRefV1 {
            gate: Wave5GateV1::G0RootFaultWitness,
            occurrence_id: StableString::new("caller-authored-g0").expect("occurrence ID"),
            occurrence_digest: ValueDigest::new(format!("sha256:{}", "1".repeat(64)))
                .expect("occurrence digest"),
            evidence_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
        });
        value.registration_digest =
            digest_bytes(&canonical_bytes(&value.digest_material()).expect("digest material"))
                .expect("registration digest");
        let bytes = canonical_bytes(&value).expect("canonical registration");

        assert!(matches!(
            store.commit_wave6_program_registration_v1(
                &bytes,
                StableString::new("wave6:program-registration:forged-gate")
                    .expect("batch ID"),
                StableString::new("wave6-store-test").expect("writer build"),
            ),
            Err(StoreError::InvalidBatch(message))
                if message.contains("cannot consume unresolved Wave 5 gate")
        ));
    }

    #[test]
    fn all_registered_schema_bytes_are_exact_idempotent_and_restart_safe() {
        let root = tempfile::tempdir().expect("temporary store");
        let store_config = config(root.path());
        let mut store =
            SqliteStore::open(store_config.clone(), StoreMode::SingleWriter).expect("writer store");
        store
            .migrate(
                "2026-08-18T16:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        let program_id = StableString::new("w6-program-fixture-001").expect("program ID");
        store
            .commit_wave6_program_registration_v1(
                REGISTRATION,
                StableString::new("wave6:program-registration:fixture-001")
                    .expect("registration batch"),
                StableString::new("wave6-store-test").expect("writer build"),
            )
            .expect("program registration");
        let mut commits = Vec::new();
        for (kind, bytes) in schemas() {
            let kind_id = StableString::new(kind).expect("kind ID");
            let batch_id =
                StableString::new(format!("wave6:schema:{kind}")).expect("schema batch ID");
            let accepted = store
                .commit_wave6_artifact_schema_v1(
                    &program_id,
                    kind_id.clone(),
                    bytes,
                    batch_id.clone(),
                    StableString::new("wave6-store-test").expect("writer build"),
                )
                .unwrap_or_else(|error| panic!("schema commit {kind}: {error}"));
            assert_eq!(accepted.status, IdempotencyStatus::Accepted);
            assert_eq!(accepted.catalog_schema.as_str(), "joshi.sqlite.v13");
            let retry = store
                .commit_wave6_artifact_schema_v1(
                    &program_id,
                    kind_id,
                    bytes,
                    batch_id,
                    StableString::new("wave6-store-test").expect("writer build"),
                )
                .expect("schema retry");
            assert_eq!(retry.status, IdempotencyStatus::Idempotent);
            assert_eq!(retry.commit_seq, accepted.commit_seq);
            assert_eq!(retry.commit_digest, accepted.commit_digest);
            commits.push((kind, bytes, accepted));
        }

        assert!(
            store
                .commit_wave6_artifact_schema_v1(
                    &program_id,
                    StableString::new("campaign_registration_fixture").expect("kind ID"),
                    schemas()[1].1,
                    StableString::new("wave6:schema:wrong-content").expect("batch ID"),
                    StableString::new("wave6-store-test").expect("writer build"),
                )
                .is_err()
        );
        assert!(matches!(
            store.commit_wave6_artifact_schema_v1(
                &program_id,
                StableString::new("campaign_registration_fixture").expect("kind ID"),
                schemas()[0].1,
                StableString::new("wave6:schema:second-batch").expect("batch ID"),
                StableString::new("wave6-store-test").expect("writer build"),
            ),
            Err(StoreError::IdentityConflict { .. })
        ));
        assert!(matches!(
            store.commit_wave6_artifact_schema_v1(
                &program_id,
                StableString::new("invented_schema_kind").expect("kind ID"),
                schemas()[0].1,
                StableString::new("wave6:schema:invented-kind").expect("batch ID"),
                StableString::new("wave6-store-test").expect("writer build"),
            ),
            Err(StoreError::MissingIdentity { .. })
        ));
        drop(store);

        let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly).expect("reader store");
        for (kind, bytes, accepted) in commits {
            let stored = reopened
                .load_wave6_artifact_schema_v1(
                    &program_id,
                    &StableString::new(kind).expect("kind ID"),
                )
                .expect("schema readback")
                .expect("stored schema");
            assert_eq!(stored.exact_bytes, bytes);
            assert_eq!(stored.schema_digest, accepted.schema_digest);
            assert_eq!(stored.commit_digest, accepted.commit_digest);
            assert_eq!(
                stored.semantic_ceiling,
                SemanticCeilingV1::UnverifiedSemanticFixtureOnly
            );
        }
    }

    #[test]
    #[allow(clippy::too_many_lines)] // One lifecycle covers schema, commit, retry, and reopen.
    fn exact_evaluation_artifacts_are_schema_bound_idempotent_and_restart_safe() {
        let root = tempfile::tempdir().expect("temporary store");
        let store_config = config(root.path());
        let mut store =
            SqliteStore::open(store_config.clone(), StoreMode::SingleWriter).expect("writer store");
        store
            .migrate(
                "2026-08-18T16:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        let program_id = StableString::new("w6-program-fixture-001").expect("program ID");
        let writer_build = StableString::new("wave6-store-test").expect("writer build");
        store
            .commit_wave6_program_registration_v1(
                REGISTRATION,
                StableString::new("wave6:program-registration:fixture-001")
                    .expect("registration batch"),
                writer_build.clone(),
            )
            .expect("program registration");
        for (kind, bytes) in schemas() {
            store
                .commit_wave6_artifact_schema_v1(
                    &program_id,
                    StableString::new(kind).expect("kind ID"),
                    bytes,
                    StableString::new(format!("wave6:schema:{kind}")).expect("schema batch"),
                    writer_build.clone(),
                )
                .unwrap_or_else(|error| panic!("schema {kind}: {error}"));
        }

        let mut accepted_artifacts = Vec::new();
        for (kind, bytes) in artifacts() {
            let kind_id = StableString::new(kind).expect("kind ID");
            let batch_id =
                StableString::new(format!("wave6:artifact:{kind}")).expect("artifact batch");
            let accepted = store
                .commit_wave6_fixture_artifact_v1(
                    &program_id,
                    kind_id.clone(),
                    bytes,
                    batch_id.clone(),
                    writer_build.clone(),
                )
                .unwrap_or_else(|error| panic!("artifact {kind}: {error}"));
            assert_eq!(accepted.status, IdempotencyStatus::Accepted);
            assert_eq!(accepted.catalog_schema.as_str(), "joshi.sqlite.v13");
            assert!(accepted.result_count > 0);
            assert_eq!(
                accepted.semantic_ceiling,
                SemanticCeilingV1::UnverifiedSemanticFixtureOnly
            );
            let retry = store
                .commit_wave6_fixture_artifact_v1(
                    &program_id,
                    kind_id,
                    bytes,
                    batch_id,
                    writer_build.clone(),
                )
                .expect("exact artifact retry");
            assert_eq!(retry.status, IdempotencyStatus::Idempotent);
            assert_eq!(retry.artifact_id, accepted.artifact_id);
            assert_eq!(retry.commit_seq, accepted.commit_seq);
            assert_eq!(retry.commit_digest, accepted.commit_digest);
            accepted_artifacts.push((bytes, accepted));
        }

        assert!(
            store
                .commit_wave6_fixture_artifact_v1(
                    &program_id,
                    StableString::new("protocol_known_truth_evaluation_fixture").expect("kind ID"),
                    artifacts()[0].1,
                    StableString::new("wave6:artifact:wrong-kind").expect("batch ID"),
                    writer_build.clone(),
                )
                .is_err()
        );
        let first = &accepted_artifacts[0].1;
        assert!(matches!(
            store.commit_wave6_fixture_artifact_v1(
                &program_id,
                first.kind_id.clone(),
                artifacts()[0].1,
                StableString::new("wave6:artifact:second-batch").expect("batch ID"),
                writer_build,
            ),
            Err(StoreError::IdentityConflict { .. })
        ));
        drop(store);

        let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly).expect("reader store");
        for (bytes, accepted) in accepted_artifacts {
            let stored = reopened
                .load_wave6_fixture_artifact_v1(&accepted.artifact_id)
                .expect("artifact readback")
                .expect("stored artifact");
            assert_eq!(stored.exact_bytes, bytes);
            assert_eq!(stored.content_digest, accepted.content_digest);
            assert_eq!(stored.evaluation_digest, accepted.evaluation_digest);
            assert_eq!(stored.result_count, accepted.result_count);
            assert!(stored.schema_commit_seq < stored.commit_seq);
            assert_eq!(stored.commit_digest, accepted.commit_digest);
        }
    }
}
