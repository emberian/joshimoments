use crate::{
    AdmittedCounts, BackupManifest, BlobStore, DurableReceipt, EffectiveAssertion, GapOutcome,
    IdempotencyStatus, JustifiedCursor, MigrationReport, ObservationStorage,
    OperatorCaptureMetadata, PreparedBlob, PreparedExport, ProjectionRegistration, Result,
    SceneMode, SourceRegistration, StoreConfig, StoreError, StoreIngestBatch, StoreMode,
    StoredScene, VerificationReport, VerifyDepth,
    blob::{prepare_export_file, sha256_hex, verify_file},
    migration,
    model::{
        ChoiceMemberDraft, CommandDraft, CommandReceipt, ExportDraft, ExportReceipt,
        ExportSnapshotDraft, SceneCommandBatch, SceneDraft, SceneWatermarkDraft,
    },
};
use joshi_domain::{
    BatchDigest, CommitSeq, OpenVariant, SourceId, StableString, UtcTimestamp, ValueDigest,
    VariantRecognition, WireU64,
};
use joshi_evidence::{
    Boundary, CoverageGap, CoverageRecovery, CoverageWindow, CursorAdvance, DurableIngestBatch,
    ObservationDraft, SourceEventRecord,
};
use joshi_export::{ExportSnapshotReceiptV1, ExportSnapshotStatus, ValidatedExportSnapshotV1};
use joshi_operator::{
    CommandReceiptV1, OperatorCommandStatus, ValidatedGlassViewV1, ValidatedOperatorCommandV1,
};
use rusqlite::{
    Connection, OpenFlags, OptionalExtension, Transaction, TransactionBehavior, params,
};
use serde::Serialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
};

#[cfg(test)]
thread_local! {
    static FAIL_BEFORE_INGEST_COMMIT: std::cell::RefCell<Option<&'static str>> = const {
        std::cell::RefCell::new(None)
    };
}

const INGEST_CONTRACT: &str = "joshi.durable_ingest_batch.v1";
const RECEIPT_CONTRACT: &str = "joshi.store.ingest_receipt";

/// Single `SQLite` catalog connection and immutable artifact roots.
pub struct SqliteStore {
    pub(crate) connection: Connection,
    pub(crate) config: StoreConfig,
    blob_store: BlobStore,
    pub(crate) mode: StoreMode,
    pub(crate) writer_lease: Option<File>,
}

impl SqliteStore {
    /// Opens one catalog using the bundled `SQLite` runtime and fail-closed PRAGMAs.
    ///
    /// # Errors
    ///
    /// Fails for an unsafe runtime, wrong application ID, incompatible mode, or filesystem error.
    pub fn open(config: StoreConfig, mode: StoreMode) -> Result<Self> {
        migration::assert_linked_runtime()?;
        if mode == StoreMode::SingleWriter {
            if let Some(parent) = config.catalog_path.parent() {
                fs::create_dir_all(parent).map_err(|source| StoreError::io(parent, source))?;
            }
            fs::create_dir_all(&config.blob_root)
                .map_err(|source| StoreError::io(&config.blob_root, source))?;
            fs::create_dir_all(&config.export_root)
                .map_err(|source| StoreError::io(&config.export_root, source))?;
        }
        let flags = match mode {
            StoreMode::SingleWriter => {
                OpenFlags::SQLITE_OPEN_READ_WRITE
                    | OpenFlags::SQLITE_OPEN_CREATE
                    | OpenFlags::SQLITE_OPEN_NO_MUTEX
            }
            StoreMode::ReadOnly => {
                OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX
            }
        };
        let writer_lease = if mode == StoreMode::SingleWriter {
            let lease_path = config.catalog_path.with_extension("writer.lock");
            let lease = OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(&lease_path)
                .map_err(|source| StoreError::io(&lease_path, source))?;
            lease
                .try_lock()
                .map_err(|_| StoreError::WriterLeaseUnavailable(lease_path))?;
            Some(lease)
        } else {
            None
        };
        let connection = Connection::open_with_flags(&config.catalog_path, flags)?;
        match mode {
            StoreMode::SingleWriter => migration::configure_writer(&connection)?,
            StoreMode::ReadOnly => migration::configure_reader(&connection)?,
        }
        connection.busy_timeout(config.busy_timeout)?;
        let blob_store = BlobStore::new(&config.blob_root, config.inline_blob_max_bytes);
        Ok(Self {
            connection,
            config,
            blob_store,
            mode,
            writer_lease,
        })
    }

    /// Applies the compiled, forward-only migration ledger.
    ///
    /// # Errors
    ///
    /// Fails in read-only mode, on migration drift, or when `SQLite` rejects a migration.
    pub fn migrate(&mut self, applied_at: UtcTimestamp) -> Result<MigrationReport> {
        self.require_writer()?;
        migration::migrate(
            &mut self.connection,
            positive_timestamp_us(applied_at, "migration applied_at")?,
        )
    }

    /// Applies the forward-only ledger through the Wave 5 V9 baseline and stops before G0 tables.
    ///
    /// This narrow bootstrap boundary exists so one real prior Snapshot V2 export/import can be
    /// committed before the same catalog advances to V10. It never removes a migration and refuses
    /// a catalog that has already advanced beyond V9.
    ///
    /// # Errors
    ///
    /// Fails in read-only mode, on migration drift, after V10, or when `SQLite` rejects a migration.
    pub fn migrate_wave5_baseline_v9(
        &mut self,
        applied_at: UtcTimestamp,
    ) -> Result<MigrationReport> {
        self.require_writer()?;
        migration::migrate_through(
            &mut self.connection,
            positive_timestamp_us(applied_at, "migration applied_at")?,
            9,
        )
    }

    /// Registers a versioned source contract, idempotently for an exact retry.
    ///
    /// # Errors
    ///
    /// Fails when the identity exists with different immutable content.
    pub fn register_source(&self, source: &SourceRegistration) -> Result<IdempotencyStatus> {
        self.require_writer()?;
        let fingerprint = raw_digest(source.configuration_digest.as_str(), "source configuration")?;
        let changed = self.connection.execute(
            "INSERT OR IGNORE INTO source
             (source_id,namespace,source_contract_version,collector_build,configuration_fingerprint)
             VALUES (?1,?2,?3,?4,?5)",
            params![
                source.source_id.as_str(),
                source.namespace.as_str(),
                source.contract_version.as_str(),
                source.collector_build.as_str(),
                fingerprint
            ],
        )?;
        if changed == 1 {
            return Ok(IdempotencyStatus::Accepted);
        }
        let exact: bool = self.connection.query_row(
            "SELECT namespace=?2 AND source_contract_version=?3 AND collector_build=?4
                    AND configuration_fingerprint=?5
             FROM source WHERE source_id=?1",
            params![
                source.source_id.as_str(),
                source.namespace.as_str(),
                source.contract_version.as_str(),
                source.collector_build.as_str(),
                fingerprint
            ],
            |row| row.get(0),
        )?;
        if exact {
            Ok(IdempotencyStatus::Idempotent)
        } else {
            Err(StoreError::IdentityConflict {
                kind: "source",
                identity: source.source_id.to_string(),
            })
        }
    }

    /// Computes and validates canonical logical batch digest material.
    ///
    /// # Errors
    ///
    /// Fails for a wrong contract, non-canonical set ordering, JSON numbers, or digest mismatch.
    pub fn validate_batch_digest(batch: &DurableIngestBatch) -> Result<BatchDigest> {
        let computed = Self::canonical_batch_digest(batch)?;
        if computed != batch.expected_digest {
            return Err(StoreError::InvalidDigest {
                kind: "batch",
                value: format!("expected {}, computed {computed}", batch.expected_digest),
            });
        }
        Ok(computed)
    }

    /// Computes canonical V1 logical digest material, excluding only `expected_digest`.
    ///
    /// # Errors
    ///
    /// Fails unless all set-like collections are strictly ordered and values are exact.
    pub fn canonical_batch_digest(batch: &DurableIngestBatch) -> Result<BatchDigest> {
        validate_canonical_batch(batch)?;
        let value = serde_json::to_value(batch)?;
        let mut object = value.as_object().cloned().ok_or_else(|| {
            StoreError::InvalidBatch("durable ingest batch did not serialize as an object".into())
        })?;
        object.remove("expected_digest");
        let bytes = serde_json::to_vec(&object)?;
        BatchDigest::new(format!("sha256:{}", sha256_hex(&bytes)))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))
    }

    /// Atomically appends bounded exact evidence and all cursor/gap closure.
    ///
    /// External blobs are installed and fsynced first. A receipt is returned only after the SQL
    /// transaction commits, or after exact readback of a prior identical batch.
    ///
    /// # Errors
    ///
    /// Fails before mutation for invalid contracts, bounds, policy closure, unsupported SQL
    /// discriminators, conflicting identities, missing evidence, or digest mismatch.
    pub fn commit_ingest(&mut self, batch: &StoreIngestBatch) -> Result<DurableReceipt> {
        self.require_writer()?;
        let logical_digest = Self::validate_batch_digest(&batch.evidence)?;
        positive_timestamp_us(batch.committed_at, "ingest committed_at")?;
        let admitted = self.validate_bounds_and_counts(batch)?;
        validate_policy_closure(batch)?;
        let admission_digest = admission_digest(batch, &logical_digest)?;

        if let Some((commit_seq, existing)) =
            self.existing_commit(batch.evidence.batch_id.as_str())?
        {
            if existing != raw_digest(admission_digest.as_str(), "admission")? {
                return Err(StoreError::IdentityConflict {
                    kind: "ingest batch",
                    identity: batch.evidence.batch_id.to_string(),
                });
            }
            return self.receipt(
                batch,
                logical_digest,
                admission_digest,
                CommitSeq::new(commit_seq),
                admitted,
                IdempotencyStatus::Idempotent,
            );
        }

        preflight_ingest(&self.connection, &self.config, batch)?;
        let prepared = self.prepare_observation_blobs(batch)?;
        for blob in prepared.values() {
            self.blob_store.verify(blob)?;
        }
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let previous_digest: Option<String> = tx
            .query_row(
                "SELECT commit_digest FROM ingest_commit ORDER BY commit_seq DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        tx.execute(
            "INSERT INTO ingest_commit
             (commit_id,commit_class,committed_wall_us,writer_clock_id,committed_mono_ns,
              writer_build,prior_commit_digest,commit_digest)
             VALUES (?1,'ingest',?2,?3,?4,?5,?6,?7)",
            params![
                batch.evidence.batch_id.as_str(),
                positive_timestamp_us(batch.committed_at, "ingest committed_at")?,
                batch.writer_clock_id.as_str(),
                batch.committed_mono_ns.to_string(),
                batch.writer_build.as_str(),
                previous_digest,
                raw_digest(admission_digest.as_str(), "admission")?
            ],
        )?;
        let commit_seq_i64 = tx.last_insert_rowid();
        let commit_seq = CommitSeq::new(as_u64(commit_seq_i64, "commit_seq")?);
        insert_ingest_rows(&tx, batch, &prepared, commit_seq)?;
        verify_contract_sidecars(&tx, commit_seq_i64)?;
        #[cfg(test)]
        if FAIL_BEFORE_INGEST_COMMIT.with(|fail_batch| {
            let should_fail =
                fail_batch.borrow().as_deref() == Some(batch.evidence.batch_id.as_str());
            if should_fail {
                *fail_batch.borrow_mut() = None;
            }
            should_fail
        }) {
            return Err(StoreError::Injected("before ingest commit"));
        }
        tx.commit()?;
        self.receipt(
            batch,
            logical_digest,
            admission_digest,
            commit_seq,
            admitted,
            IdempotencyStatus::Accepted,
        )
    }

    /// Returns effective non-retracted assertion branches at a historical knowledge cutoff.
    ///
    /// # Errors
    ///
    /// Fails for integer overflow, malformed stored JSON/digest, or `SQLite` errors.
    pub fn effective_assertions_as_known(
        &self,
        semantic_key: &str,
        cutoff: CommitSeq,
    ) -> Result<Vec<EffectiveAssertion>> {
        let mut statement = self.connection.prepare(
            "SELECT a.assertion_id,a.semantic_key,a.produced_commit_seq,a.value_json,
                    a.value_sha256,a.supersedes_assertion_id
             FROM assertion a
             WHERE a.semantic_key=?1 AND a.produced_commit_seq<=?2
               AND a.assertion_status<>'retraction'
               AND NOT EXISTS (
                 SELECT 1 FROM assertion later
                 WHERE later.supersedes_assertion_id=a.assertion_id
                   AND later.produced_commit_seq<=?2
               )
             ORDER BY a.produced_commit_seq,a.assertion_id",
        )?;
        let rows = statement.query_map(
            params![semantic_key, sqlite_u64(cutoff.get(), "cutoff")?],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, Option<String>>(5)?,
                ))
            },
        )?;
        let mut result = Vec::new();
        for row in rows {
            let (assertion_id, key, seq, json, digest, supersedes) = row?;
            result.push(EffectiveAssertion {
                assertion_id: joshi_domain::AssertionId::new(assertion_id)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                semantic_key: StableString::new(key)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                produced_commit_seq: CommitSeq::new(as_u64(seq, "produced_commit_seq")?),
                value: serde_json::from_str(&json)?,
                value_digest: ValueDigest::new(format!("sha256:{digest}"))
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                supersedes_assertion_id: supersedes
                    .map(joshi_domain::AssertionId::new)
                    .transpose()
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            });
        }
        Ok(result)
    }

    /// Returns the source cursor justified by committed `CursorAdvance` evidence at `cutoff`.
    /// Descriptive acquisition/observation cursor strings are never consulted.
    ///
    /// # Errors
    ///
    /// Fails on `SQLite` or stored contract corruption.
    pub fn justified_source_cursors_as_known(
        &self,
        source_id: &SourceId,
        cutoff: CommitSeq,
    ) -> Result<Vec<JustifiedCursor>> {
        let mut statement = self.connection.prepare(
            "SELECT c.cursor_id,c.scope_kind,d.scope_family_recognition,d.scope_subject,
                    c.cursor_kind,d.cursor_kind_recognition,c.cursor_value,c.advanced_commit_seq
             FROM source_cursor c JOIN source_cursor_contract d USING(cursor_id)
             WHERE c.source_id=?1 AND c.advanced_commit_seq<=?2
               AND NOT EXISTS (
                 SELECT 1 FROM source_cursor later
                 WHERE later.source_id=c.source_id AND later.scope_kind=c.scope_kind
                   AND later.scope_key=c.scope_key AND later.cursor_kind=c.cursor_kind
                   AND later.advanced_commit_seq<=?2
                   AND (later.advanced_commit_seq>c.advanced_commit_seq
                        OR (later.advanced_commit_seq=c.advanced_commit_seq
                            AND later.cursor_id>c.cursor_id))
               )
             ORDER BY c.scope_kind,c.scope_key,c.cursor_kind,c.cursor_id",
        )?;
        let rows = statement.query_map(
            params![source_id.as_str(), sqlite_u64(cutoff.get(), "cutoff")?],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, Option<String>>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, i64>(7)?,
                ))
            },
        )?;
        let mut result = Vec::new();
        for row in rows {
            let (
                cursor_id,
                family,
                family_recognition,
                subject,
                kind,
                kind_recognition,
                value,
                seq,
            ) = row?;
            result.push(JustifiedCursor {
                cursor_id: joshi_domain::CursorId::new(cursor_id)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                scope: joshi_evidence::CoverageScope {
                    source_id: source_id.clone(),
                    family: stored_variant(family, &family_recognition)?,
                    subject: subject
                        .map(StableString::new)
                        .transpose()
                        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                },
                cursor_kind: stored_variant(kind, &kind_recognition)?,
                cursor_value: StableString::new(value)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                advanced_through: CommitSeq::new(as_u64(seq, "advanced_commit_seq")?),
            });
        }
        Ok(result)
    }

    /// Returns the canonical domain cursor wrapper for glass/as-of DTO construction.
    ///
    /// # Errors
    ///
    /// Fails if stored rows violate the unique full-scope invariant.
    pub fn scoped_source_cursors_as_known(
        &self,
        source_id: &SourceId,
        cutoff: CommitSeq,
    ) -> Result<joshi_domain::ScopedSourceCursors> {
        let cursors = self
            .justified_source_cursors_as_known(source_id, cutoff)?
            .into_iter()
            .map(|cursor| joshi_domain::ScopedSourceCursor {
                family: cursor.scope.family.discriminator,
                subject: cursor.scope.subject,
                cursor_kind: cursor.cursor_kind.discriminator,
                value: cursor.cursor_value,
                advanced_through: cursor.advanced_through,
            })
            .collect();
        joshi_domain::ScopedSourceCursors::new(cursors)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))
    }

    /// Builds a source watermark from represented observations and authoritative scoped cursors.
    /// Acquisition registration and descriptive cursor text are never promoted.
    ///
    /// # Errors
    ///
    /// Fails on stored clock/cursor corruption or `SQLite` errors.
    pub fn source_as_of(
        &self,
        source_id: &SourceId,
        cutoff: CommitSeq,
    ) -> Result<Option<joshi_domain::SourceAsOf>> {
        let represented: (Option<i64>, Option<i64>) = self.connection.query_row(
            "SELECT MAX(commit_seq),MAX(received_wall_us) FROM observation
             WHERE source_id=?1 AND commit_seq<=?2",
            params![source_id.as_str(), sqlite_u64(cutoff.get(), "cutoff")?],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        let (Some(delivered), Some(received)) = represented else {
            return Ok(None);
        };
        let delivered = CommitSeq::new(as_u64(delivered, "source delivered_through")?);
        let cursors = self.scoped_source_cursors_as_known(source_id, delivered)?;
        let received = timestamp_from_us(received, "source received_through")?;
        joshi_domain::SourceAsOf::new(delivered, cursors, Some(received))
            .map(Some)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))
    }

    /// Prepares an immutable analytical artifact under the export root.
    ///
    /// # Errors
    ///
    /// Fails for unsafe paths, conflicting bytes, or filesystem durability errors.
    pub fn prepare_export(&self, relative: &Path, bytes: &[u8]) -> Result<PreparedExport> {
        self.require_writer()?;
        prepare_export_file(&self.config.export_root, relative, bytes)
    }

    /// Registers an immutable rebuildable projection contract.
    ///
    /// # Errors
    ///
    /// Fails when the identity exists with different configuration or schema content.
    pub fn register_projection(
        &self,
        projection: &ProjectionRegistration,
    ) -> Result<IdempotencyStatus> {
        self.require_writer()?;
        let configuration = raw_digest(
            projection.configuration_digest.as_str(),
            "projection configuration",
        )?;
        let schema = raw_digest(projection.schema_digest.as_str(), "projection schema")?;
        let changed = self.connection.execute(
            "INSERT OR IGNORE INTO projection_version
             (projection_name,projection_version,producer_build,configuration_sha256,
              schema_sha256,deterministic) VALUES (?1,?2,?3,?4,?5,?6)",
            params![
                projection.name.as_str(),
                projection.version.as_str(),
                projection.producer_build.as_str(),
                configuration,
                schema,
                i64::from(projection.deterministic)
            ],
        )?;
        if changed == 1 {
            return Ok(IdempotencyStatus::Accepted);
        }
        let exact: bool = self.connection.query_row(
            "SELECT producer_build=?3 AND configuration_sha256=?4 AND schema_sha256=?5
                    AND deterministic=?6
             FROM projection_version WHERE projection_name=?1 AND projection_version=?2",
            params![
                projection.name.as_str(),
                projection.version.as_str(),
                projection.producer_build.as_str(),
                configuration,
                schema,
                i64::from(projection.deterministic)
            ],
            |row| row.get(0),
        )?;
        if exact {
            Ok(IdempotencyStatus::Idempotent)
        } else {
            Err(StoreError::IdentityConflict {
                kind: "projection",
                identity: format!("{}:{}", projection.name, projection.version),
            })
        }
    }

    /// Admits an exact Glass scene and evidence-only operator command through the frozen typed V1
    /// contract. The untyped structural transaction is private to this crate.
    ///
    /// # Errors
    ///
    /// Fails unless every duplicated source cursor, observation reference, projection checkpoint,
    /// cutoff, scene/view binding, and referenced command resolves exactly as known.
    #[allow(clippy::too_many_arguments, clippy::too_many_lines)]
    pub fn commit_operator_v1(
        &mut self,
        command: &ValidatedOperatorCommandV1,
        new_scene: Option<&ValidatedGlassViewV1>,
        capture: &OperatorCaptureMetadata,
        committed_at: UtcTimestamp,
        writer_clock_id: StableString,
        committed_mono_ns: u64,
        writer_build: StableString,
    ) -> Result<CommandReceiptV1> {
        self.require_writer()?;
        if committed_at.as_datetime() < command.issued_at().as_datetime() {
            return Err(StoreError::InvalidBatch(
                "operator command receipt precedes client issue time".into(),
            ));
        }
        let batch_id = StableString::new(format!("operator:{}", command.command_id()))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        if let Some(commit_seq) = self.exact_operator_retry(command)? {
            return Ok(CommandReceiptV1::durable(
                self.config.catalog_id.clone(),
                self.catalog_schema_id()?,
                batch_id,
                command,
                commit_seq,
                OperatorCommandStatus::Idempotent,
            ));
        }

        let owned_existing;
        let view = if let Some(view) = new_scene {
            view
        } else {
            let stored = self.load_scene(command.scene_id())?;
            owned_existing = ValidatedGlassViewV1::parse_exact(
                &stored.view_bytes,
                Some(command.view_digest().as_str()),
            )
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
            &owned_existing
        };
        command
            .validate_against_view(view)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        if command.issued_at().as_datetime() < view.rendered_at().as_datetime() {
            return Err(StoreError::InvalidBatch(
                "operator command issue time precedes its exact rendered scene".into(),
            ));
        }
        if new_scene.is_some()
            && capture.rendered_clock_id == *command.client_clock_id()
            && capture.rendered_mono_ns > command.client_monotonic_ns()
        {
            return Err(StoreError::InvalidBatch(
                "operator command monotonic clock precedes scene render on the same domain".into(),
            ));
        }
        self.validate_glass_view_as_known(view)?;
        for referenced in command.referenced_command_ids() {
            if referenced == command.command_id().as_str()
                || !row_exists(&self.connection, "command", "command_id", referenced)?
            {
                return Err(StoreError::MissingIdentity {
                    kind: "referenced operator command",
                    identity: referenced.to_owned(),
                });
            }
        }

        let scene = if let Some(view) = new_scene {
            if row_exists(
                &self.connection,
                "scene",
                "scene_id",
                view.scene_id().as_str(),
            )? {
                return Err(StoreError::IdentityConflict {
                    kind: "scene",
                    identity: view.scene_id().to_string(),
                });
            }
            let (mode, knowledge_cutoff, outcome_cutoff) = self.scene_mode_and_cutoffs(view)?;
            let mut watermarks =
                Vec::with_capacity(view.sources().len() + view.projections().len());
            for source in view.sources() {
                watermarks.push(SceneWatermarkDraft {
                    namespace: StableString::new(format!("source:{}", source.source_id()))
                        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                    source_id: Some(source.source_id().clone()),
                    projection: None,
                    delivered_commit_seq: source.delivered_through(),
                    state_digest: None,
                });
            }
            for projection in view.projections() {
                watermarks.push(SceneWatermarkDraft {
                    namespace: StableString::new(format!(
                        "projection:{}:{}",
                        projection.name(),
                        projection.version()
                    ))
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                    source_id: None,
                    projection: Some((projection.name().clone(), projection.version().clone())),
                    delivered_commit_seq: view.catalog_commit(),
                    state_digest: Some(projection.state_digest().clone()),
                });
            }
            watermarks.sort_by(|left, right| left.namespace.cmp(&right.namespace));
            let candidate_kind = StableString::new("candidate")
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
            let rendered = StableString::new("rendered")
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
            let choice_members = view
                .choices()
                .iter()
                .map(|choice| ChoiceMemberDraft {
                    set_kind: rendered.clone(),
                    subject_kind: candidate_kind.clone(),
                    subject_key: choice.candidate_id().clone(),
                    source_rank: Some(choice.source_rank()),
                    rendered_ordinal: Some(choice.rendered_ordinal()),
                    evidence_assertion_id: None,
                })
                .collect();
            Some(SceneDraft {
                scene_id: view.scene_id().clone(),
                mode,
                knowledge_cutoff,
                outcome_cutoff,
                basis_scene_id: view.basis_scene_id().cloned(),
                client_session_id: command.client_session_id().clone(),
                client_scene_seq: capture.client_scene_seq,
                ui_build: capture.ui_build.clone(),
                view_contract: StableString::new("joshi.glass.view")
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                view_contract_version: 1,
                source_mode: StableString::new(capture.source_mode.as_str())
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                rendered_at: view.rendered_at(),
                client_clock_id: capture.rendered_clock_id.clone(),
                rendered_mono_ns: capture.rendered_mono_ns,
                view_bytes: view.canonical_bytes().to_vec(),
                screenshot_bytes: capture.screenshot_bytes.clone(),
                watermarks,
                choice_members,
            })
        } else {
            None
        };
        let structural = SceneCommandBatch {
            batch_id: batch_id.clone(),
            scene,
            command: CommandDraft {
                command_id: command.command_id().clone(),
                scene_id: Some(command.scene_id().clone()),
                client_session_id: command.client_session_id().clone(),
                client_command_seq: command.client_command_seq(),
                idempotency_key: command.idempotency_key().clone(),
                command_kind: StableString::new(command.kind().as_str())
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                subject_kind: command.subject().kind().clone(),
                subject_key: command.subject().key().clone(),
                payload_bytes: command.payload_bytes().to_vec(),
                issued_at: command.issued_at(),
                client_clock_id: command.client_clock_id().clone(),
                issued_mono_ns: command.client_monotonic_ns(),
                received_at: committed_at,
            },
            committed_at,
            writer_clock_id,
            committed_mono_ns,
            writer_build,
        };
        let receipt = self.commit_scene_command(&structural)?;
        Ok(CommandReceiptV1::durable(
            self.config.catalog_id.clone(),
            self.catalog_schema_id()?,
            batch_id,
            command,
            receipt.commit_seq,
            match receipt.status {
                IdempotencyStatus::Accepted => OperatorCommandStatus::Accepted,
                IdempotencyStatus::Idempotent => OperatorCommandStatus::Idempotent,
            },
        ))
    }

    /// Installs and registers one capability-checked frozen snapshot fixture. This is deliberately
    /// not a general SQL-to-analysis projection API.
    ///
    /// # Errors
    ///
    /// Fails unless catalog/range/projection checkpoint and every exact file match the capability.
    #[allow(clippy::too_many_lines)]
    pub fn commit_fixture_export_snapshot_v1(
        &mut self,
        snapshot: &ValidatedExportSnapshotV1,
        committed_at: UtcTimestamp,
        writer_build: &StableString,
    ) -> Result<ExportSnapshotReceiptV1> {
        self.require_writer()?;
        if snapshot.catalog_id() != &self.config.catalog_id
            || snapshot.catalog_schema().as_str() != "joshi.store.catalog/v5"
            || snapshot.from_commit_seq().get() == 0
            || snapshot.through_commit_seq() > self.max_commit_seq()?
        {
            return Err(StoreError::InvalidBatch(
                "snapshot catalog identity/schema/range does not match this store".into(),
            ));
        }
        self.require_projection_checkpoint(
            snapshot.projection_name(),
            snapshot.projection_version(),
            snapshot.through_commit_seq(),
            snapshot.projection_state_digest(),
        )?;
        let prefix = snapshot.snapshot_id().as_str();
        let manifest = self.prepare_export(
            &PathBuf::from(prefix).join("manifest.json"),
            snapshot.manifest_bytes(),
        )?;
        if &manifest.digest != snapshot.manifest_digest() {
            return Err(StoreError::InvalidBatch(
                "prepared manifest differs from validated exact bytes".into(),
            ));
        }
        let mut drafts = Vec::with_capacity(snapshot.tables().len());
        let mut prepared = Vec::with_capacity(snapshot.tables().len());
        for table in snapshot.tables() {
            let bytes = fs::read(table.absolute_path())
                .map_err(|source| StoreError::io(table.absolute_path(), source))?;
            let artifact =
                self.prepare_export(&PathBuf::from(prefix).join(table.relative_path()), &bytes)?;
            if &artifact.digest != table.physical_digest()
                || artifact.byte_length != table.byte_length()
            {
                return Err(StoreError::InvalidBatch(format!(
                    "prepared table {} differs from validated artifact",
                    table.name()
                )));
            }
            drafts.push(ExportDraft {
                export_manifest_id: table.export_manifest_id().clone(),
                family: table.name().clone(),
                family_schema_version: 1,
                generation: 1,
                part_ordinal: table.ordinal(),
                projection: (
                    snapshot.projection_name().clone(),
                    snapshot.projection_version().clone(),
                ),
                from_commit_seq: table.from_commit_seq(),
                through_commit_seq: table.through_commit_seq(),
                input_manifest_digest: snapshot.snapshot_id().clone(),
                row_count: table.row_count(),
                format: StableString::new("parquet")
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                compression: StableString::new("zstd")
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                writer_version: snapshot.producer_build().clone(),
                schema_digest: table.schema_digest().clone(),
                retention_class: StableString::new("fixture")
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            });
            prepared.push(artifact);
        }
        let parts = drafts.iter().zip(prepared.iter()).collect::<Vec<_>>();
        let snapshot_draft = ExportSnapshotDraft {
            export_snapshot_id: StableString::new(snapshot.snapshot_id().as_str())
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            contract: StableString::new("joshi.analysis.snapshot/v1")
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            schema_version: 1,
            from_commit_seq: snapshot.from_commit_seq(),
            through_commit_seq: snapshot.through_commit_seq(),
            scene_id: None,
        };
        let receipt = self.register_export_snapshot(
            &snapshot_draft,
            &manifest,
            &parts,
            committed_at,
            writer_build,
        )?;
        Ok(ExportSnapshotReceiptV1::durable(
            snapshot,
            receipt.commit_seq,
            match receipt.status {
                IdempotencyStatus::Accepted => ExportSnapshotStatus::Accepted,
                IdempotencyStatus::Idempotent => ExportSnapshotStatus::Idempotent,
            },
        ))
    }

    #[allow(clippy::too_many_lines)] // Exact retry compares every persisted semantic field locally.
    fn exact_operator_retry(
        &self,
        command: &ValidatedOperatorCommandV1,
    ) -> Result<Option<CommitSeq>> {
        type StoredCommand = (
            i64,
            String,
            String,
            i64,
            String,
            String,
            String,
            String,
            String,
            i64,
            String,
            String,
            String,
        );
        let stored: Option<StoredCommand> = self
            .connection
            .query_row(
                "SELECT c.committed_commit_seq,c.scene_id,c.client_session_id,c.client_command_seq,
                        c.idempotency_key,c.command_kind,c.subject_kind,c.subject_key,
                        c.payload_blob_id,c.issued_wall_us,c.client_clock_id,c.issued_mono_ns,
                        pc.storage_domain
                 FROM command c JOIN command_payload_contract pc USING(command_id)
                 WHERE c.command_id=?1",
                [command.command_id().as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                        row.get(7)?,
                        row.get(8)?,
                        row.get(9)?,
                        row.get(10)?,
                        row.get(11)?,
                        row.get(12)?,
                    ))
                },
            )
            .optional()?;
        let Some((
            commit,
            scene,
            session,
            sequence,
            idempotency,
            kind,
            subject_kind,
            subject_key,
            payload_blob,
            issued,
            clock_id,
            mono_ns,
            payload_domain,
        )) = stored
        else {
            let conflict: Option<String> = self
                .connection
                .query_row(
                    "SELECT command_id FROM command
                 WHERE client_session_id=?1 AND
                       (client_command_seq=?2 OR idempotency_key=?3) LIMIT 1",
                    params![
                        command.client_session_id().as_str(),
                        sqlite_u64(command.client_command_seq(), "client command seq")?,
                        command.idempotency_key().as_str()
                    ],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(identity) = conflict {
                return Err(StoreError::IdentityConflict {
                    kind: "operator command retry key",
                    identity,
                });
            }
            return Ok(None);
        };
        let payload = load_blob_object(
            &self.connection,
            &self.config.blob_root,
            &payload_blob,
            &payload_domain,
        )?;
        let scene_id = joshi_domain::SceneId::new(scene.clone())
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let exact_scene = self.load_scene(&scene_id)?;
        let expected_issued = timestamp_us(command.issued_at(), "command issued_at")?;
        let exact = scene == command.scene_id().as_str()
            && session == command.client_session_id().as_str()
            && as_u64(sequence, "client command seq")? == command.client_command_seq()
            && idempotency == command.idempotency_key().as_str()
            && kind == command.kind().as_str()
            && subject_kind == command.subject().kind().as_str()
            && subject_key == command.subject().key().as_str()
            && payload == command.payload_bytes()
            && issued == expected_issued
            && clock_id == command.client_clock_id().as_str()
            && mono_ns == command.client_monotonic_ns().to_string()
            && sha256_hex(&exact_scene.view_bytes)
                == raw_digest(command.view_digest().as_str(), "operator view")?;
        if !exact {
            return Err(StoreError::IdentityConflict {
                kind: "operator command",
                identity: command.command_id().to_string(),
            });
        }
        Ok(Some(CommitSeq::new(as_u64(commit, "command commit")?)))
    }

    fn validate_glass_view_as_known(&self, view: &ValidatedGlassViewV1) -> Result<()> {
        let max = self.max_commit_seq()?;
        if view.catalog_commit().get() == 0 || view.catalog_commit() > max {
            return Err(StoreError::InvalidBatch(
                "Glass catalog cutoff is not an existing durable commit".into(),
            ));
        }
        for source in view.sources() {
            let actual = self
                .source_as_of(source.source_id(), view.catalog_commit())?
                .ok_or_else(|| StoreError::MissingIdentity {
                    kind: "Glass source as-of",
                    identity: source.source_id().to_string(),
                })?;
            let cursors = actual.cursors().as_slice();
            let exact_cursors = cursors.len() == source.cursors().len()
                && cursors.iter().zip(source.cursors()).all(|(left, right)| {
                    left.family == *right.family()
                        && left.subject.as_ref() == right.subject()
                        && left.cursor_kind.as_str() == right.cursor_kind().as_str()
                        && left.value.as_str() == right.value().as_str()
                        && left.advanced_through == right.advanced_through()
                });
            if actual.delivered_through() != source.delivered_through()
                || actual.received_through() != source.received_through()
                || !exact_cursors
            {
                return Err(StoreError::InvalidBatch(format!(
                    "Glass source watermark does not match as-known catalog state for {} \
                     (expected delivered={}, received={:?}, cursors={}; actual delivered={}, \
                     received={:?}, cursors={})",
                    source.source_id(),
                    source.delivered_through(),
                    source.received_through(),
                    source.cursors().len(),
                    actual.delivered_through(),
                    actual.received_through(),
                    cursors.len()
                )));
            }
        }
        for projection in view.projections() {
            self.require_projection_checkpoint(
                projection.name(),
                projection.version(),
                view.catalog_commit(),
                projection.state_digest(),
            )?;
        }
        for evidence in view.evidence() {
            let expected_observed = evidence
                .observed_at()
                .map(|value| timestamp_us(value, "Glass evidence observedAt"))
                .transpose()?;
            let row: Option<(i64, String, i64, i64, Option<i64>)> = self
                .connection
                .query_row(
                    "SELECT commit_seq,source_id,received_wall_us,available_wall_us,
                        source_event_lower_us
                 FROM observation WHERE observation_id=?1 AND commit_seq<=?2",
                    params![
                        evidence.id().as_str(),
                        sqlite_u64(view.catalog_commit().get(), "Glass catalog cutoff")?
                    ],
                    |row| {
                        Ok((
                            row.get(0)?,
                            row.get(1)?,
                            row.get(2)?,
                            row.get(3)?,
                            row.get(4)?,
                        ))
                    },
                )
                .optional()?;
            let Some((_commit, source, received, available, observed)) = row else {
                return Err(StoreError::MissingIdentity {
                    kind: "Glass evidence observation",
                    identity: evidence.id().to_string(),
                });
            };
            if source != evidence.source_id().as_str()
                || received != timestamp_us(evidence.ingested_at(), "Glass evidence ingestedAt")?
                || available != timestamp_us(evidence.known_at(), "Glass evidence knownAt")?
                || observed != expected_observed
            {
                return Err(StoreError::InvalidBatch(format!(
                    "Glass evidence reference {} does not match durable observation clocks/source",
                    evidence.id()
                )));
            }
        }
        Ok(())
    }

    fn require_projection_checkpoint(
        &self,
        name: &StableString,
        version: &StableString,
        through: CommitSeq,
        state_digest: &ValueDigest,
    ) -> Result<()> {
        let actual: Option<String> = self
            .connection
            .query_row(
                "SELECT output_sha256 FROM projection_checkpoint
             WHERE projection_name=?1 AND projection_version=?2 AND through_commit_seq=?3",
                params![
                    name.as_str(),
                    version.as_str(),
                    sqlite_u64(through.get(), "projection through commit")?
                ],
                |row| row.get(0),
            )
            .optional()?;
        let expected = raw_digest(state_digest.as_str(), "projection state")?;
        if actual.as_deref() == Some(expected) {
            Ok(())
        } else {
            Err(StoreError::MissingIdentity {
                kind: "exact projection checkpoint",
                identity: format!("{name}:{version}@{through}:{state_digest}"),
            })
        }
    }

    fn scene_mode_and_cutoffs(
        &self,
        view: &ValidatedGlassViewV1,
    ) -> Result<(SceneMode, CommitSeq, Option<CommitSeq>)> {
        match view.mode() {
            joshi_operator::GlassMode::Witnessed => {
                Ok((SceneMode::Witnessed, view.catalog_commit(), None))
            }
            joshi_operator::GlassMode::KnowledgeCutoff => {
                Ok((SceneMode::KnowledgeCutoff, view.catalog_commit(), None))
            }
            joshi_operator::GlassMode::Retrospective => {
                let basis = view.basis_scene_id().ok_or_else(|| {
                    StoreError::InvalidBatch("retrospective Glass view lacks basis scene".into())
                })?;
                let knowledge: i64 = self
                    .connection
                    .query_row(
                        "SELECT knowledge_cutoff_commit_seq FROM scene WHERE scene_id=?1",
                        [basis.as_str()],
                        |row| row.get(0),
                    )
                    .optional()?
                    .ok_or_else(|| StoreError::MissingIdentity {
                        kind: "basis scene",
                        identity: basis.to_string(),
                    })?;
                Ok((
                    SceneMode::Retrospective,
                    CommitSeq::new(as_u64(knowledge, "basis knowledge cutoff")?),
                    Some(view.catalog_commit()),
                ))
            }
        }
    }

    /// Atomically records an immutable replay scene and one evidence-only semantic command.
    ///
    /// This boundary cannot represent, queue, sign, or execute an economic/network effect.
    ///
    /// # Errors
    ///
    /// Fails for invalid cutoffs, identity conflicts, artifact failure, or a non-exact retry.
    #[allow(clippy::too_many_lines)] // One transaction is clearer when its complete closure is visible.
    fn commit_scene_command(&mut self, batch: &SceneCommandBatch) -> Result<CommandReceipt> {
        self.require_writer()?;
        positive_timestamp_us(batch.committed_at, "command committed_at")?;
        let encoded = serde_json::to_vec(batch)?;
        let raw = sha256_hex(&encoded);
        let digest = ValueDigest::new(format!("sha256:{raw}"))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        if let Some((seq, existing)) = self.existing_commit(batch.batch_id.as_str())? {
            if existing != raw {
                return Err(StoreError::IdentityConflict {
                    kind: "scene-command batch",
                    identity: batch.batch_id.to_string(),
                });
            }
            return Ok(CommandReceipt {
                batch_id: batch.batch_id.clone(),
                command_id: batch.command.command_id.clone(),
                commit_seq: CommitSeq::new(seq),
                status: IdempotencyStatus::Idempotent,
                digest,
            });
        }
        validate_scene_command_preflight(&self.connection, batch)?;
        let private = StableString::new("operator_private")
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let json_type = StableString::new("application/json")
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let binary_type = StableString::new("application/octet-stream")
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let view = batch
            .scene
            .as_ref()
            .map(|scene| {
                self.blob_store.prepare(
                    &scene.view_bytes,
                    json_type.clone(),
                    None,
                    private.clone(),
                    true,
                )
            })
            .transpose()?;
        let screenshot = batch
            .scene
            .as_ref()
            .and_then(|scene| scene.screenshot_bytes.as_ref())
            .map(|bytes| {
                self.blob_store
                    .prepare(bytes, binary_type.clone(), None, private.clone(), true)
            })
            .transpose()?;
        let payload = self.blob_store.prepare(
            &batch.command.payload_bytes,
            json_type,
            None,
            private,
            true,
        )?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let prior: Option<String> = tx
            .query_row(
                "SELECT commit_digest FROM ingest_commit ORDER BY commit_seq DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        tx.execute(
            "INSERT INTO ingest_commit
             (commit_id,commit_class,committed_wall_us,writer_clock_id,committed_mono_ns,
              writer_build,prior_commit_digest,commit_digest)
             VALUES (?1,'command',?2,?3,?4,?5,?6,?7)",
            params![
                batch.batch_id.as_str(),
                positive_timestamp_us(batch.committed_at, "command committed_at")?,
                batch.writer_clock_id.as_str(),
                batch.committed_mono_ns.to_string(),
                batch.writer_build.as_str(),
                prior,
                raw
            ],
        )?;
        let seq = tx.last_insert_rowid();
        if let Some(view) = &view {
            insert_blob(&tx, view, seq)?;
        }
        if let Some(screenshot) = &screenshot {
            insert_blob(&tx, screenshot, seq)?;
        }
        insert_blob(&tx, &payload, seq)?;
        if let Some(scene) = &batch.scene {
            let view = view
                .as_ref()
                .ok_or_else(|| StoreError::InvalidBatch("scene view was not prepared".into()))?;
            let screenshot_id = screenshot.as_ref().map(|blob| blob.raw_sha256.as_str());
            tx.execute(
                "INSERT INTO scene
                 (scene_id,scene_mode,captured_commit_seq,knowledge_cutoff_commit_seq,
                  outcome_cutoff_commit_seq,basis_scene_id,client_session_id,client_scene_seq,
                  ui_build,view_contract,view_contract_version,source_mode,rendered_wall_us,
                  client_clock_id,rendered_mono_ns,view_blob_id,screenshot_blob_id,view_sha256)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?16)",
                params![
                    scene.scene_id.as_str(),
                    scene_mode(scene.mode),
                    seq,
                    sqlite_u64(scene.knowledge_cutoff.get(), "scene knowledge cutoff")?,
                    scene
                        .outcome_cutoff
                        .map(|value| sqlite_u64(value.get(), "scene outcome cutoff"))
                        .transpose()?,
                    scene
                        .basis_scene_id
                        .as_ref()
                        .map(joshi_domain::SceneId::as_str),
                    scene.client_session_id.as_str(),
                    sqlite_u64(scene.client_scene_seq, "client scene seq")?,
                    scene.ui_build.as_str(),
                    scene.view_contract.as_str(),
                    sqlite_u64(scene.view_contract_version, "view contract version")?,
                    scene.source_mode.as_str(),
                    timestamp_us(scene.rendered_at, "scene rendered_at")?,
                    scene.client_clock_id.as_str(),
                    scene.rendered_mono_ns.to_string(),
                    view.raw_sha256,
                    screenshot_id
                ],
            )?;
            tx.execute(
                "INSERT INTO scene_artifact_contract (scene_id,artifact_role,blob_id,storage_domain)
                 VALUES (?1,'view',?2,?3)",
                params![scene.scene_id.as_str(), view.raw_sha256, view.storage_domain.as_str()],
            )?;
            if let Some(screenshot) = &screenshot {
                tx.execute(
                    "INSERT INTO scene_artifact_contract (scene_id,artifact_role,blob_id,storage_domain)
                     VALUES (?1,'screenshot',?2,?3)",
                    params![scene.scene_id.as_str(), screenshot.raw_sha256, screenshot.storage_domain.as_str()],
                )?;
            }
            for watermark in &scene.watermarks {
                tx.execute(
                    "INSERT INTO scene_watermark
                     (scene_id,watermark_namespace,source_id,projection_name,projection_version,
                      delivered_commit_seq,state_sha256) VALUES (?1,?2,?3,?4,?5,?6,?7)",
                    params![
                        scene.scene_id.as_str(),
                        watermark.namespace.as_str(),
                        watermark.source_id.as_ref().map(SourceId::as_str),
                        watermark.projection.as_ref().map(|value| value.0.as_str()),
                        watermark.projection.as_ref().map(|value| value.1.as_str()),
                        sqlite_u64(watermark.delivered_commit_seq.get(), "scene watermark")?,
                        watermark
                            .state_digest
                            .as_ref()
                            .map(|value| raw_digest(value.as_str(), "scene state"))
                            .transpose()?
                    ],
                )?;
            }
            for member in &scene.choice_members {
                tx.execute(
                    "INSERT INTO scene_choice_member
                     (scene_id,set_kind,subject_kind,subject_key,source_rank,rendered_ordinal,
                      evidence_assertion_id) VALUES (?1,?2,?3,?4,?5,?6,?7)",
                    params![
                        scene.scene_id.as_str(),
                        member.set_kind.as_str(),
                        member.subject_kind.as_str(),
                        member.subject_key.as_str(),
                        member
                            .source_rank
                            .map(|value| sqlite_u64(value, "source rank"))
                            .transpose()?,
                        member
                            .rendered_ordinal
                            .map(|value| sqlite_u64(value, "rendered ordinal"))
                            .transpose()?,
                        member
                            .evidence_assertion_id
                            .as_ref()
                            .map(joshi_domain::AssertionId::as_str)
                    ],
                )?;
            }
        }
        let scene_id = batch
            .scene
            .as_ref()
            .map(|scene| &scene.scene_id)
            .or(batch.command.scene_id.as_ref());
        tx.execute(
            "INSERT INTO command
             (command_id,committed_commit_seq,scene_id,client_session_id,client_command_seq,
              idempotency_key,command_kind,subject_kind,subject_key,payload_blob_id,issued_wall_us,
              client_clock_id,issued_mono_ns,received_wall_us,effect_ceiling,authority_class)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,
                     'observe_only','evidence_only')",
            params![
                batch.command.command_id.as_str(),
                seq,
                scene_id.map(joshi_domain::SceneId::as_str),
                batch.command.client_session_id.as_str(),
                sqlite_u64(batch.command.client_command_seq, "client command seq")?,
                batch.command.idempotency_key.as_str(),
                batch.command.command_kind.as_str(),
                batch.command.subject_kind.as_str(),
                batch.command.subject_key.as_str(),
                payload.raw_sha256,
                timestamp_us(batch.command.issued_at, "command issued_at")?,
                batch.command.client_clock_id.as_str(),
                batch.command.issued_mono_ns.to_string(),
                timestamp_us(batch.command.received_at, "command received_at")?
            ],
        )?;
        tx.execute(
            "INSERT INTO command_payload_contract (command_id,blob_id,storage_domain)
             VALUES (?1,?2,?3)",
            params![
                batch.command.command_id.as_str(),
                payload.raw_sha256,
                payload.storage_domain.as_str()
            ],
        )?;
        tx.commit()?;
        Ok(CommandReceipt {
            batch_id: batch.batch_id.clone(),
            command_id: batch.command.command_id.clone(),
            commit_seq: CommitSeq::new(as_u64(seq, "commit_seq")?),
            status: IdempotencyStatus::Accepted,
            digest,
        })
    }

    /// Loads exact immutable renderer and screenshot bytes for one scene.
    ///
    /// # Errors
    ///
    /// Fails when the scene/artifact is missing, corrupt, or not representable by the public type.
    pub fn load_scene(&self, scene_id: &joshi_domain::SceneId) -> Result<StoredScene> {
        let row = self.connection.query_row(
            "SELECT s.scene_mode,s.knowledge_cutoff_commit_seq,s.outcome_cutoff_commit_seq,
                    s.view_blob_id,s.screenshot_blob_id,
                    va.storage_domain,sa.storage_domain
             FROM scene s
             JOIN scene_artifact_contract va ON va.scene_id=s.scene_id AND va.artifact_role='view'
             LEFT JOIN scene_artifact_contract sa ON sa.scene_id=s.scene_id AND sa.artifact_role='screenshot'
             WHERE s.scene_id=?1",
            [scene_id.as_str()],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?,
                row.get::<_, Option<i64>>(2)?, row.get::<_, String>(3)?,
                row.get::<_, Option<String>>(4)?, row.get::<_, String>(5)?,
                row.get::<_, Option<String>>(6)?)),
        ).optional()?.ok_or_else(|| StoreError::MissingIdentity {
            kind: "scene",
            identity: scene_id.to_string(),
        })?;
        let (mode, knowledge, outcome, view_blob, screenshot_blob, view_domain, screenshot_domain) =
            row;
        let view_bytes = load_blob_object(
            &self.connection,
            &self.config.blob_root,
            &view_blob,
            &view_domain,
        )?;
        let screenshot_bytes = screenshot_blob
            .zip(screenshot_domain)
            .map(|(blob, domain)| {
                load_blob_object(&self.connection, &self.config.blob_root, &blob, &domain)
            })
            .transpose()?;
        Ok(StoredScene {
            scene_id: scene_id.clone(),
            mode: parse_scene_mode(&mode)?,
            knowledge_cutoff: CommitSeq::new(as_u64(knowledge, "knowledge cutoff")?),
            outcome_cutoff: outcome
                .map(|value| as_u64(value, "outcome cutoff").map(CommitSeq::new))
                .transpose()?,
            view_bytes,
            screenshot_bytes,
        })
    }

    /// Atomically registers one immutable manifest and every prepared export part it names.
    ///
    /// # Errors
    ///
    /// Fails unless every exact file is durable, paths/parts are unique, projection versions
    /// exist, and the part closure spans the snapshot's declared commit range.
    #[allow(clippy::too_many_lines)] // Snapshot and every part intentionally share one transaction.
    fn register_export_snapshot(
        &mut self,
        snapshot: &ExportSnapshotDraft,
        manifest: &PreparedExport,
        parts: &[(&ExportDraft, &PreparedExport)],
        committed_at: UtcTimestamp,
        writer_build: &StableString,
    ) -> Result<ExportReceipt> {
        self.require_writer()?;
        if snapshot.schema_version == 0
            || snapshot.from_commit_seq > snapshot.through_commit_seq
            || parts.is_empty()
        {
            return Err(StoreError::InvalidBatch(
                "export snapshot requires a positive version, closed range, and parts".into(),
            ));
        }
        positive_timestamp_us(committed_at, "export committed_at")?;
        let raw_manifest = raw_digest(manifest.digest.as_str(), "export manifest")?;
        verify_file(
            &self.config.export_root.join(&manifest.relative_path),
            raw_manifest,
            manifest.byte_length,
        )?;
        let mut part_ids = BTreeSet::new();
        let mut part_paths = BTreeSet::new();
        for (draft, prepared) in parts {
            if !part_ids.insert(draft.export_manifest_id.as_str())
                || !part_paths.insert(prepared.relative_path.as_path())
                || draft.from_commit_seq > draft.through_commit_seq
                || draft.from_commit_seq < snapshot.from_commit_seq
                || draft.through_commit_seq > snapshot.through_commit_seq
            {
                return Err(StoreError::InvalidBatch(
                    "export parts contain duplicate identity/path or range outside snapshot".into(),
                ));
            }
            let raw = raw_digest(prepared.digest.as_str(), "export part")?;
            verify_file(
                &self.config.export_root.join(&prepared.relative_path),
                raw,
                prepared.byte_length,
            )?;
        }
        let digest_parts = parts
            .iter()
            .map(|(draft, prepared)| {
                (
                    draft,
                    prepared.relative_path.to_string_lossy(),
                    prepared.digest.as_str(),
                    prepared.byte_length,
                )
            })
            .collect::<Vec<_>>();
        let digest_material = serde_json::to_vec(&(
            "joshi.export_registration.v1",
            snapshot,
            manifest.relative_path.to_string_lossy(),
            manifest.digest.as_str(),
            manifest.byte_length,
            digest_parts,
        ))?;
        let commit_digest = sha256_hex(&digest_material);
        let digest = ValueDigest::new(format!("sha256:{commit_digest}"))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        if let Some((seq, existing)) = self.existing_commit(snapshot.export_snapshot_id.as_str())? {
            if existing != commit_digest {
                return Err(StoreError::IdentityConflict {
                    kind: "export snapshot",
                    identity: snapshot.export_snapshot_id.to_string(),
                });
            }
            return Ok(ExportReceipt {
                export_snapshot_id: snapshot.export_snapshot_id.clone(),
                commit_seq: CommitSeq::new(seq),
                status: IdempotencyStatus::Idempotent,
                digest,
            });
        }
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "INSERT INTO ingest_commit
             (commit_id,commit_class,committed_wall_us,writer_clock_id,committed_mono_ns,
              writer_build,prior_commit_digest,commit_digest)
             VALUES (?1,'export',?2,'export', '0',?3,
               (SELECT commit_digest FROM ingest_commit ORDER BY commit_seq DESC LIMIT 1),?4)",
            params![
                snapshot.export_snapshot_id.as_str(),
                positive_timestamp_us(committed_at, "export committed_at")?,
                writer_build.as_str(),
                commit_digest
            ],
        )?;
        let seq = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO export_snapshot
             (export_snapshot_id,contract,schema_version,manifest_relative_path,
              manifest_sha256,manifest_byte_length,from_commit_seq,through_commit_seq,
              scene_id,created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
            params![
                snapshot.export_snapshot_id.as_str(),
                snapshot.contract.as_str(),
                sqlite_u64(snapshot.schema_version, "export snapshot schema version")?,
                manifest.relative_path.to_string_lossy(),
                raw_manifest,
                sqlite_u64(manifest.byte_length, "export manifest byte length")?,
                sqlite_u64(snapshot.from_commit_seq.get(), "snapshot from commit")?,
                sqlite_u64(snapshot.through_commit_seq.get(), "snapshot through commit")?,
                snapshot
                    .scene_id
                    .as_ref()
                    .map(joshi_domain::SceneId::as_str),
                seq
            ],
        )?;
        for (draft, prepared) in parts {
            tx.execute(
                "INSERT INTO export_manifest
             (export_manifest_id,family,family_schema_version,generation,part_ordinal,
              projection_name,projection_version,from_commit_seq,through_commit_seq,
              created_commit_seq,input_manifest_sha256,relative_path,file_sha256,byte_length,
              row_count,format,compression,writer_version,schema_sha256,retention_class)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20)",
                params![
                    draft.export_manifest_id.as_str(),
                    draft.family.as_str(),
                    sqlite_u64(draft.family_schema_version, "family_schema_version")?,
                    sqlite_u64(draft.generation, "generation")?,
                    sqlite_u64(draft.part_ordinal, "part_ordinal")?,
                    draft.projection.0.as_str(),
                    draft.projection.1.as_str(),
                    sqlite_u64(draft.from_commit_seq.get(), "from_commit_seq")?,
                    sqlite_u64(draft.through_commit_seq.get(), "through_commit_seq")?,
                    seq,
                    raw_digest(draft.input_manifest_digest.as_str(), "input manifest")?,
                    prepared.relative_path.to_string_lossy(),
                    raw_digest(prepared.digest.as_str(), "export part")?,
                    sqlite_u64(prepared.byte_length, "export byte_length")?,
                    sqlite_u64(draft.row_count, "export row_count")?,
                    draft.format.as_str(),
                    draft.compression.as_str(),
                    draft.writer_version.as_str(),
                    raw_digest(draft.schema_digest.as_str(), "schema")?,
                    draft.retention_class.as_str()
                ],
            )?;
            tx.execute(
                "INSERT INTO export_snapshot_part (export_snapshot_id,export_manifest_id)
                 VALUES (?1,?2)",
                params![
                    snapshot.export_snapshot_id.as_str(),
                    draft.export_manifest_id.as_str()
                ],
            )?;
        }
        tx.commit()?;
        Ok(ExportReceipt {
            export_snapshot_id: snapshot.export_snapshot_id.clone(),
            commit_seq: CommitSeq::new(as_u64(seq, "commit_seq")?),
            status: IdempotencyStatus::Accepted,
            digest,
        })
    }

    /// Creates a consistent online `SQLite` backup and closes over referenced immutable artifacts.
    ///
    /// # Errors
    ///
    /// Fails if the destination exists, backup fails, or referenced artifacts are missing/corrupt.
    pub fn backup_to(&self, destination: &Path) -> Result<BackupManifest> {
        if destination.exists() {
            return Err(StoreError::RestoreDestinationExists(destination.to_owned()));
        }
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|source| StoreError::io(parent, source))?;
        }
        let mut target = Connection::open(destination)?;
        let backup = rusqlite::backup::Backup::new(&self.connection, &mut target)?;
        backup.run_to_completion(16, std::time::Duration::from_millis(10), None)?;
        drop(backup);
        target.close().map_err(|(_, error)| error)?;
        let catalog_bytes =
            fs::read(destination).map_err(|source| StoreError::io(destination, source))?;
        let max = self.max_commit_seq()?;
        let mut referenced_exports =
            self.referenced_artifacts("export_manifest", "relative_path")?;
        referenced_exports
            .extend(self.referenced_artifacts("export_snapshot", "manifest_relative_path")?);
        referenced_exports.extend(
            self.referenced_artifacts("derived_analysis_artifact_part_v2", "relative_path")?,
        );
        referenced_exports.sort();
        Ok(BackupManifest {
            catalog_path: destination.to_owned(),
            catalog_digest: ValueDigest::new(format!("sha256:{}", sha256_hex(&catalog_bytes)))
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            max_commit_seq: max,
            referenced_blobs: self.referenced_artifacts("blob_object", "relative_path")?,
            referenced_exports,
        })
    }

    /// Restores a catalog backup to a new destination after digest verification.
    ///
    /// # Errors
    ///
    /// Fails on digest mismatch, existing destination, or filesystem error.
    pub fn restore_catalog(
        backup: &BackupManifest,
        destination: &Path,
        expected_catalog_digest: &ValueDigest,
    ) -> Result<()> {
        if destination.exists() {
            return Err(StoreError::RestoreDestinationExists(destination.to_owned()));
        }
        let bytes = fs::read(&backup.catalog_path)
            .map_err(|source| StoreError::io(&backup.catalog_path, source))?;
        let actual = format!("sha256:{}", sha256_hex(&bytes));
        if actual != expected_catalog_digest.as_str() || actual != backup.catalog_digest.as_str() {
            return Err(StoreError::ArtifactVerification {
                path: backup.catalog_path.clone(),
                detail: "backup catalog digest mismatch".into(),
            });
        }
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|source| StoreError::io(parent, source))?;
        }
        fs::copy(&backup.catalog_path, destination)
            .map_err(|source| StoreError::io(destination, source))?;
        Ok(())
    }

    /// Runs catalog and immutable-artifact integrity checks.
    ///
    /// # Errors
    ///
    /// Fails on database corruption or referenced artifact mismatch.
    pub fn verify(&self, depth: VerifyDepth) -> Result<VerificationReport> {
        let pragma = if depth == VerifyDepth::Full {
            "integrity_check"
        } else {
            "quick_check"
        };
        let integrity: String = self
            .connection
            .pragma_query_value(None, pragma, |row| row.get(0))?;
        let foreign_key_defects_i64: i64 = self.connection.query_row(
            "SELECT COUNT(*) FROM pragma_foreign_key_check",
            [],
            |row| row.get(0),
        )?;
        let mut checked = 0_u64;
        if depth == VerifyDepth::Full {
            let mut statement = self.connection.prepare(
                "SELECT relative_path,stored_sha256,stored_length FROM blob_object
                 WHERE storage_mode='external' AND relative_path IS NOT NULL",
            )?;
            let rows = statement.query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            })?;
            for row in rows {
                let (path, digest, len) = row?;
                verify_file(
                    &self.config.blob_root.join(path),
                    &digest,
                    as_u64(len, "stored_length")?,
                )?;
                checked += 1;
            }
            let mut statement = self.connection.prepare(
                "SELECT relative_path,file_sha256,byte_length
                 FROM derived_analysis_artifact_part_v2 ORDER BY import_id,part_ordinal",
            )?;
            let rows = statement.query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            })?;
            for row in rows {
                let (path, digest, len) = row?;
                verify_file(
                    &self.config.export_root.join(path),
                    &digest,
                    as_u64(len, "derived artifact byte length")?,
                )?;
                checked += 1;
            }
        }
        Ok(VerificationReport {
            integrity,
            foreign_key_defects: as_u64(foreign_key_defects_i64, "foreign_key_defects")?,
            external_artifacts_checked: checked,
            max_commit_seq: self.max_commit_seq()?,
        })
    }

    pub(crate) fn require_writer(&self) -> Result<()> {
        if self.mode == StoreMode::SingleWriter && self.writer_lease.is_some() {
            Ok(())
        } else {
            Err(StoreError::InvalidBatch(
                "write attempted through read-only store".into(),
            ))
        }
    }

    fn validate_bounds_and_counts(&self, batch: &StoreIngestBatch) -> Result<AdmittedCounts> {
        if batch.evidence.observations.len() > self.config.max_observations_per_batch {
            return Err(StoreError::InvalidBatch(format!(
                "{} observations exceeds configured maximum {}",
                batch.evidence.observations.len(),
                self.config.max_observations_per_batch
            )));
        }
        let raw_bytes =
            batch
                .evidence
                .observations
                .iter()
                .try_fold(0_u64, |total, observation| {
                    let length = u64::try_from(observation.payload.len()).map_err(|_| {
                        StoreError::IntegerRange {
                            field: "observation payload length",
                            value: observation.payload.len().to_string(),
                        }
                    })?;
                    total
                        .checked_add(length)
                        .ok_or_else(|| StoreError::IntegerRange {
                            field: "batch raw bytes",
                            value: "overflow".into(),
                        })
                })?;
        if raw_bytes > self.config.max_raw_bytes_per_batch {
            return Err(StoreError::InvalidBatch(format!(
                "{raw_bytes} raw bytes exceeds configured maximum {}",
                self.config.max_raw_bytes_per_batch
            )));
        }
        let acquisitions = batch
            .evidence
            .observations
            .iter()
            .map(|draft| draft.acquisition.acquisition_id.as_str())
            .collect::<BTreeSet<_>>()
            .len();
        let raw_blobs = batch
            .evidence
            .observations
            .iter()
            .map(|draft| sha256_hex(&draft.payload))
            .collect::<BTreeSet<_>>()
            .len();
        Ok(AdmittedCounts {
            acquisitions: WireU64::new(count_u64(acquisitions, "acquisitions")?),
            raw_blobs: WireU64::new(count_u64(raw_blobs, "raw_blobs")?),
            raw_bytes: WireU64::new(raw_bytes),
            observations: WireU64::new(count_u64(
                batch.evidence.observations.len(),
                "observations",
            )?),
            source_events: WireU64::new(count_u64(
                batch.evidence.source_events.len(),
                "source_events",
            )?),
            assertions: WireU64::new(count_u64(batch.evidence.assertions.len(), "assertions")?),
            coverage_windows: WireU64::new(count_u64(
                batch.evidence.coverage_windows.len(),
                "coverage_windows",
            )?),
            coverage_gaps: WireU64::new(count_u64(
                batch.evidence.coverage_gaps.len(),
                "coverage_gaps",
            )?),
            coverage_recoveries: WireU64::new(count_u64(
                batch.evidence.coverage_recoveries.len(),
                "coverage_recoveries",
            )?),
            cursor_advances: WireU64::new(count_u64(
                batch.evidence.cursor_advances.len(),
                "cursor_advances",
            )?),
        })
    }

    fn prepare_observation_blobs(
        &self,
        batch: &StoreIngestBatch,
    ) -> Result<BTreeMap<String, PreparedBlob>> {
        let mut result = BTreeMap::new();
        for draft in &batch.evidence.observations {
            let policy = batch
                .observation_storage
                .get(draft.observation.observation_id.as_str())
                .ok_or_else(|| StoreError::MissingIdentity {
                    kind: "observation storage policy",
                    identity: draft.observation.observation_id.to_string(),
                })?;
            let blob = self.blob_store.prepare(
                &draft.payload,
                draft.observation.media_type.clone(),
                policy.content_encoding.clone(),
                policy.retention_class.clone(),
                policy.force_external,
            )?;
            result.insert(draft.observation.observation_id.to_string(), blob);
        }
        Ok(result)
    }

    fn existing_commit(&self, batch_id: &str) -> Result<Option<(u64, String)>> {
        self.connection
            .query_row(
                "SELECT commit_seq,commit_digest FROM ingest_commit WHERE commit_id=?1",
                [batch_id],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?
            .map(|(seq, digest)| Ok((as_u64(seq, "commit_seq")?, digest)))
            .transpose()
    }

    fn receipt(
        &self,
        batch: &StoreIngestBatch,
        logical_digest: BatchDigest,
        admission_digest: ValueDigest,
        commit_seq: CommitSeq,
        admitted: AdmittedCounts,
        status: IdempotencyStatus,
    ) -> Result<DurableReceipt> {
        let mut acquisition_ids = batch
            .evidence
            .observations
            .iter()
            .map(|draft| draft.acquisition.acquisition_id.clone())
            .collect::<Vec<_>>();
        acquisition_ids.sort();
        acquisition_ids.dedup();
        let recorded = StableString::new("recorded")
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let gap_outcomes = batch
            .evidence
            .coverage_gaps
            .iter()
            .map(|gap| GapOutcome {
                gap_id: gap.gap_id.clone(),
                scope: gap.scope.clone(),
                lower: gap.lower.clone(),
                upper: gap.upper.clone(),
                outcome: recorded.clone(),
            })
            .collect();
        Ok(DurableReceipt {
            contract: StableString::new(RECEIPT_CONTRACT)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            schema_version: 1,
            catalog_id: self.config.catalog_id.clone(),
            catalog_schema: self.catalog_schema_id()?,
            commit_seq,
            from_commit_seq: commit_seq,
            through_commit_seq: commit_seq,
            batch_id: batch.evidence.batch_id.clone(),
            batch_digest: logical_digest,
            admission_digest,
            status,
            admitted,
            acquisition_ids,
            gap_outcomes,
        })
    }

    pub(crate) fn max_commit_seq(&self) -> Result<CommitSeq> {
        let max: i64 = self.connection.query_row(
            "SELECT COALESCE(MAX(commit_seq),0) FROM ingest_commit",
            [],
            |row| row.get(0),
        )?;
        Ok(CommitSeq::new(as_u64(max, "max_commit_seq")?))
    }

    pub(crate) fn catalog_schema_id(&self) -> Result<StableString> {
        let version: i64 = self
            .connection
            .pragma_query_value(None, "user_version", |row| row.get(0))?;
        if version <= 0 {
            return Err(StoreError::InvalidBatch(
                "catalog has no applied schema version".into(),
            ));
        }
        StableString::new(format!("joshi.sqlite.v{version}"))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))
    }

    fn referenced_artifacts(
        &self,
        table: &'static str,
        column: &'static str,
    ) -> Result<Vec<(PathBuf, ValueDigest)>> {
        let query = format!("SELECT {column}, file_sha256 FROM {table} WHERE {column} IS NOT NULL");
        let query = match table {
            "blob_object" => {
                format!("SELECT {column}, stored_sha256 FROM {table} WHERE storage_mode='external'")
            }
            "export_snapshot" => {
                format!("SELECT {column}, manifest_sha256 FROM {table} WHERE {column} IS NOT NULL")
            }
            _ => query,
        };
        let mut statement = self.connection.prepare(&query)?;
        let rows = statement.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        let mut result = Vec::new();
        for row in rows {
            let (path, digest) = row?;
            result.push((
                PathBuf::from(path),
                ValueDigest::new(format!("sha256:{digest}"))
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            ));
        }
        Ok(result)
    }
}

#[allow(clippy::too_many_lines)] // Whole-batch preflight must audit every identity family before CAS.
fn preflight_ingest(
    connection: &Connection,
    config: &StoreConfig,
    batch: &StoreIngestBatch,
) -> Result<()> {
    let observations = &batch.evidence.observations;
    let acquisition_ids = observations
        .iter()
        .map(|value| value.acquisition.acquisition_id.as_str())
        .collect::<BTreeSet<_>>();
    let observation_ids = observations
        .iter()
        .map(|value| value.observation.observation_id.as_str())
        .collect::<BTreeSet<_>>();
    let batch_event_sources = batch
        .evidence
        .source_events
        .iter()
        .map(|value| (value.source_event_id.as_str(), value.source_id.as_str()))
        .collect::<BTreeMap<_, _>>();
    let batch_window_ids = batch
        .evidence
        .coverage_windows
        .iter()
        .map(|value| value.coverage_id.as_str())
        .collect::<BTreeSet<_>>();

    for draft in observations {
        let acquisition = &draft.acquisition;
        require_known_one_of(
            &acquisition.acquisition_kind,
            &["live", "poll", "backfill", "recovery", "manual", "fixture"],
            "acquisition_kind",
        )?;
        require_known_one_of(
            &acquisition.transport_kind,
            &["rpc", "websocket", "http", "browser", "operator", "fixture"],
            "transport_kind",
        )?;
        raw_digest(
            acquisition.request_fingerprint.as_str(),
            "request fingerprint",
        )?;
        positive_timestamp_us(acquisition.started_at, "acquisition started_at")?;
        let requested = acquisition
            .clocks
            .requested_at
            .map(|value| positive_timestamp_us(value, "acquisition requested_at"))
            .transpose()?;
        let received =
            positive_timestamp_us(acquisition.clocks.received_at, "acquisition received_at")?;
        let persisted =
            positive_timestamp_us(acquisition.clocks.persisted_at, "acquisition persisted_at")?;
        if requested.is_some_and(|value| value > received) || persisted < received {
            return Err(StoreError::InvalidBatch(format!(
                "acquisition {} clocks are not causal",
                acquisition.acquisition_id
            )));
        }
        if acquisition.clocks.monotonic_elapsed_ns.is_some()
            != acquisition.clocks.monotonic_domain.is_some()
        {
            return Err(StoreError::InvalidBatch(format!(
                "acquisition {} monotonic duration/domain are not paired",
                acquisition.acquisition_id
            )));
        }
        let source_contract: Option<String> = connection
            .query_row(
                "SELECT source_contract_version FROM source WHERE source_id=?1",
                [acquisition.source_id.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        if source_contract.as_deref() != Some(acquisition.contract_version.as_str()) {
            return Err(StoreError::MissingIdentity {
                kind: "matching source contract",
                identity: acquisition.source_id.to_string(),
            });
        }
        if let Some(parent) = &acquisition.parent_acquisition_id {
            let exists = acquisition_ids.contains(parent.as_str())
                || row_exists(connection, "acquisition", "acquisition_id", parent.as_str())?;
            if !exists {
                return Err(StoreError::MissingIdentity {
                    kind: "parent acquisition",
                    identity: parent.to_string(),
                });
            }
        }
        if row_exists(
            connection,
            "acquisition",
            "acquisition_id",
            acquisition.acquisition_id.as_str(),
        )? {
            return Err(StoreError::IdentityConflict {
                kind: "acquisition",
                identity: acquisition.acquisition_id.to_string(),
            });
        }
        if row_exists(
            connection,
            "observation",
            "observation_id",
            draft.observation.observation_id.as_str(),
        )? {
            return Err(StoreError::IdentityConflict {
                kind: "observation",
                identity: draft.observation.observation_id.to_string(),
            });
        }
        validate_observation_contract(draft)?;
        preflight_blob_policy(connection, config, batch, draft)?;
        for link in &draft.observation.source_events {
            let event_source: Option<String> =
                if let Some(source) = batch_event_sources.get(link.source_event_id.as_str()) {
                    Some((*source).to_owned())
                } else {
                    connection
                        .query_row(
                            "SELECT source_id FROM source_event WHERE source_event_id=?1",
                            [link.source_event_id.as_str()],
                            |row| row.get::<_, String>(0),
                        )
                        .optional()?
                };
            if event_source.as_deref() != Some(acquisition.source_id.as_str()) {
                return Err(StoreError::InvalidBatch(format!(
                    "observation {} links missing or cross-source event {}",
                    draft.observation.observation_id, link.source_event_id
                )));
            }
        }
    }

    for event in &batch.evidence.source_events {
        if !row_exists(connection, "source", "source_id", event.source_id.as_str())? {
            return Err(StoreError::MissingIdentity {
                kind: "source",
                identity: event.source_id.to_string(),
            });
        }
    }
    for assertion in &batch.evidence.assertions {
        positive_timestamp_us(assertion.available_at, "assertion available_at")?;
        if row_exists(
            connection,
            "assertion",
            "assertion_id",
            assertion.assertion_id.as_str(),
        )? {
            return Err(StoreError::IdentityConflict {
                kind: "assertion",
                identity: assertion.assertion_id.to_string(),
            });
        }
        for evidence in &assertion.evidence {
            if !observation_ids.contains(evidence.observation_id.as_str())
                && !row_exists(
                    connection,
                    "observation",
                    "observation_id",
                    evidence.observation_id.as_str(),
                )?
            {
                return Err(StoreError::MissingIdentity {
                    kind: "assertion observation evidence",
                    identity: evidence.observation_id.to_string(),
                });
            }
        }
        for event in &assertion.source_events {
            if !batch_event_sources.contains_key(event.source_event_id.as_str())
                && !row_exists(
                    connection,
                    "source_event",
                    "source_event_id",
                    event.source_event_id.as_str(),
                )?
            {
                return Err(StoreError::MissingIdentity {
                    kind: "assertion source event",
                    identity: event.source_event_id.to_string(),
                });
            }
        }
        for command in &assertion.command_evidence {
            if !row_exists(
                connection,
                "command",
                "command_id",
                command.command_id.as_str(),
            )? {
                return Err(StoreError::MissingIdentity {
                    kind: "assertion command evidence",
                    identity: command.command_id.to_string(),
                });
            }
        }
    }
    for window in &batch.evidence.coverage_windows {
        if row_exists(
            connection,
            "coverage_window",
            "coverage_id",
            window.coverage_id.as_str(),
        )? {
            return Err(StoreError::IdentityConflict {
                kind: "coverage window",
                identity: window.coverage_id.to_string(),
            });
        }
        validate_boundary(&window.lower)?;
        if let Some(upper) = &window.upper {
            validate_boundary(upper)?;
        }
        positive_timestamp_us(window.available_at, "coverage available_at")?;
        coverage_level(window.scope.family.discriminator.as_str())?;
    }
    for gap in &batch.evidence.coverage_gaps {
        if !batch_window_ids.contains(gap.coverage_id.as_str())
            && !row_exists(
                connection,
                "coverage_window",
                "coverage_id",
                gap.coverage_id.as_str(),
            )?
        {
            return Err(StoreError::MissingIdentity {
                kind: "coverage window",
                identity: gap.coverage_id.to_string(),
            });
        }
        validate_boundary(&gap.lower)?;
        if let Some(upper) = &gap.upper {
            validate_boundary(upper)?;
        }
        positive_timestamp_us(gap.detected_at, "gap detected_at")?;
    }
    for recovery in &batch.evidence.coverage_recoveries {
        positive_timestamp_us(recovery.available_at, "recovery available_at")?;
        // Recovery is later knowledge by schema contract; same-batch gap/recovery is rejected.
        if !row_exists(
            connection,
            "coverage_gap",
            "gap_id",
            recovery.gap_id.as_str(),
        )? {
            return Err(StoreError::MissingIdentity {
                kind: "prior coverage gap",
                identity: recovery.gap_id.to_string(),
            });
        }
        if let Some(boundary) = &recovery.recovered_through {
            validate_boundary(boundary)?;
        }
        for evidence in &recovery.evidence {
            if !observation_ids.contains(evidence.as_str())
                && !row_exists(
                    connection,
                    "observation",
                    "observation_id",
                    evidence.as_str(),
                )?
            {
                return Err(StoreError::MissingIdentity {
                    kind: "recovery observation evidence",
                    identity: evidence.to_string(),
                });
            }
        }
    }
    for cursor in &batch.evidence.cursor_advances {
        if !observation_ids.contains(cursor.primary_observation_id.as_str()) {
            return Err(StoreError::InvalidBatch(format!(
                "cursor {} primary observation is not in its atomic batch",
                cursor.cursor_id
            )));
        }
        for evidence in &cursor.evidence {
            if !observation_ids.contains(evidence.as_str()) {
                return Err(StoreError::InvalidBatch(format!(
                    "cursor {} evidence is not in its atomic batch",
                    cursor.cursor_id
                )));
            }
        }
    }
    Ok(())
}

fn preflight_blob_policy(
    connection: &Connection,
    config: &StoreConfig,
    batch: &StoreIngestBatch,
    draft: &ObservationDraft,
) -> Result<()> {
    let policy = batch
        .observation_storage
        .get(draft.observation.observation_id.as_str())
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "observation storage policy",
            identity: draft.observation.observation_id.to_string(),
        })?;
    let length = u64::try_from(draft.payload.len()).map_err(|_| StoreError::IntegerRange {
        field: "blob content length",
        value: draft.payload.len().to_string(),
    })?;
    let external = policy.force_external
        || matches!(
            policy.retention_class.as_str(),
            "social_media" | "app_private" | "operator_private" | "disposable"
        )
        || length > config.inline_blob_max_bytes;
    let digest = sha256_hex(&draft.payload);
    let expected_mode = if external { "external" } else { "inline" };
    let expected_path = external.then(|| {
        format!(
            "{}/sha256/{}/{}/{}.blob",
            policy.retention_class,
            &digest[0..2],
            &digest[2..4],
            digest
        )
    });
    let existing: Option<(String, Option<String>, i64)> = connection
        .query_row(
            "SELECT storage_mode,relative_path,stored_length FROM blob_object
             WHERE blob_id=?1 AND storage_domain=?2",
            params![digest, policy.retention_class.as_str()],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    if let Some((mode, path, stored_length)) = existing
        && (mode != expected_mode
            || path != expected_path
            || as_u64(stored_length, "stored_length")? != length)
    {
        return Err(StoreError::IdentityConflict {
            kind: "blob protection domain",
            identity: format!("sha256:{digest}:{}", policy.retention_class),
        });
    }
    Ok(())
}

fn validate_observation_contract(draft: &ObservationDraft) -> Result<()> {
    let value = &draft.observation;
    require_known_one_of(
        &value.observation_kind,
        &[
            "frame",
            "response",
            "snapshot",
            "poll_result",
            "operator_capture",
            "fixture",
        ],
        "observation_kind",
    )?;
    require_known_one_of(
        &value.event_time.status,
        &["exact", "bounded", "source_missing", "not_applicable"],
        "event_time_status",
    )?;
    require_known_one_of(
        &value.parse_disposition,
        &[
            "pending",
            "decoded",
            "unsupported_variant",
            "malformed",
            "opaque",
        ],
        "parse_disposition",
    )?;
    let received = positive_timestamp_us(value.timing.received_at, "observation received_at")?;
    let persisted = positive_timestamp_us(value.timing.persisted_at, "observation persisted_at")?;
    let available = positive_timestamp_us(value.timing.available_at, "observation available_at")?;
    if received > persisted || persisted > available {
        return Err(StoreError::InvalidBatch(format!(
            "observation {} clocks are not causal",
            value.observation_id
        )));
    }
    match value.event_time.status.discriminator.as_str() {
        "exact" | "bounded" => {
            let lower = timestamp_us(
                value.event_time.lower.ok_or_else(|| {
                    StoreError::InvalidBatch("timed observation lacks lower".into())
                })?,
                "event lower",
            )?;
            let upper = timestamp_us(
                value.event_time.upper.ok_or_else(|| {
                    StoreError::InvalidBatch("timed observation lacks upper".into())
                })?,
                "event upper",
            )?;
            let precision = value
                .event_time
                .precision_us
                .ok_or_else(|| {
                    StoreError::InvalidBatch("timed observation lacks precision".into())
                })?
                .get();
            let width = upper
                .checked_sub(lower)
                .and_then(|value| u64::try_from(value).ok());
            if upper <= lower
                || precision == 0
                || (value.event_time.status.discriminator.as_str() == "exact"
                    && width != Some(precision))
            {
                return Err(StoreError::InvalidBatch(format!(
                    "observation {} has invalid exact/bounded interval",
                    value.observation_id
                )));
            }
        }
        _ if value.event_time.lower.is_some()
            || value.event_time.upper.is_some()
            || value.event_time.precision_us.is_some() =>
        {
            return Err(StoreError::InvalidBatch(format!(
                "observation {} has time values for absent/not-applicable status",
                value.observation_id
            )));
        }
        _ => {}
    }
    if let Some(chain) = &value.chain {
        if let Some(commitment) = &chain.commitment {
            require_known_one_of(
                commitment,
                &["processed", "confirmed", "finalized"],
                "chain commitment",
            )?;
        }
        serde_json::to_string(&chain.instruction_path)?;
    }
    Ok(())
}

fn validate_boundary(boundary: &Boundary) -> Result<()> {
    if let Boundary::Wall { value } = boundary {
        timestamp_us(*value, "coverage boundary")?;
    }
    let encoded = serde_json::to_value(boundary)?;
    if encoded.as_object().is_none() {
        return Err(StoreError::InvalidBatch(
            "coverage boundary is not a tagged object".into(),
        ));
    }
    Ok(())
}

fn row_exists(
    connection: &Connection,
    table: &'static str,
    column: &'static str,
    value: &str,
) -> Result<bool> {
    let sql = format!("SELECT EXISTS(SELECT 1 FROM {table} WHERE {column}=?1)");
    connection
        .query_row(&sql, [value], |row| row.get(0))
        .map_err(Into::into)
}

fn insert_ingest_rows(
    tx: &Transaction<'_>,
    batch: &StoreIngestBatch,
    prepared: &BTreeMap<String, PreparedBlob>,
    commit_seq: CommitSeq,
) -> Result<()> {
    let seq = sqlite_u64(commit_seq.get(), "commit_seq")?;
    let mut acquisitions = BTreeMap::new();
    for observation in &batch.evidence.observations {
        match acquisitions.get(observation.acquisition.acquisition_id.as_str()) {
            Some(existing) if *existing != &observation.acquisition => {
                return Err(StoreError::IdentityConflict {
                    kind: "acquisition within batch",
                    identity: observation.acquisition.acquisition_id.to_string(),
                });
            }
            None => {
                acquisitions.insert(
                    observation.acquisition.acquisition_id.as_str(),
                    &observation.acquisition,
                );
            }
            _ => {}
        }
    }
    for acquisition in acquisitions.values() {
        insert_acquisition(tx, acquisition, seq)?;
    }
    for blob in prepared.values() {
        insert_blob(tx, blob, seq)?;
    }
    for event in &batch.evidence.source_events {
        insert_source_event(tx, event, seq)?;
    }
    for (index, observation) in batch.evidence.observations.iter().enumerate() {
        let blob = prepared
            .get(observation.observation.observation_id.as_str())
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "prepared observation blob",
                identity: observation.observation.observation_id.to_string(),
            })?;
        insert_observation(tx, observation, blob, seq, index)?;
    }
    for assertion in &batch.evidence.assertions {
        insert_assertion(tx, assertion, seq)?;
    }
    for window in &batch.evidence.coverage_windows {
        insert_coverage_window(tx, window, seq)?;
    }
    for gap in &batch.evidence.coverage_gaps {
        let severity = batch
            .coverage_gap_severity
            .get(gap.gap_id.as_str())
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "coverage gap severity",
                identity: gap.gap_id.to_string(),
            })?;
        insert_coverage_gap(tx, gap, severity, seq)?;
    }
    for recovery in &batch.evidence.coverage_recoveries {
        insert_coverage_recovery(tx, recovery, seq)?;
    }
    for cursor in &batch.evidence.cursor_advances {
        insert_cursor(tx, cursor, seq)?;
    }
    Ok(())
}

fn insert_acquisition(
    tx: &Transaction<'_>,
    value: &joshi_evidence::AcquisitionRecord,
    seq: i64,
) -> Result<()> {
    require_known_one_of(
        &value.acquisition_kind,
        &["live", "poll", "backfill", "recovery", "manual", "fixture"],
        "acquisition_kind",
    )?;
    require_known_one_of(
        &value.transport_kind,
        &["rpc", "websocket", "http", "browser", "operator", "fixture"],
        "transport_kind",
    )?;
    let source_contract: Option<String> = tx
        .query_row(
            "SELECT source_contract_version FROM source WHERE source_id=?1",
            [value.source_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if source_contract.as_deref() != Some(value.contract_version.as_str()) {
        return Err(StoreError::InvalidBatch(format!(
            "acquisition {} contract does not match registered source",
            value.acquisition_id
        )));
    }
    let started_clock = value
        .started_monotonic
        .as_ref()
        .map(|clock| clock.clock_id.as_str());
    let started_ns = value
        .started_monotonic
        .as_ref()
        .map(|clock| clock.nanoseconds.to_string());
    let changed = tx.execute(
        "INSERT OR IGNORE INTO acquisition
         (acquisition_id,source_id,acquisition_kind,transport_kind,registered_commit_seq,
          parent_acquisition_id,request_fingerprint,started_wall_us,local_clock_id,
          started_mono_ns,source_locator_redacted)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
        params![
            value.acquisition_id.as_str(),
            value.source_id.as_str(),
            value.acquisition_kind.discriminator.as_str(),
            value.transport_kind.discriminator.as_str(),
            seq,
            value
                .parent_acquisition_id
                .as_ref()
                .map(joshi_domain::AcquisitionId::as_str),
            raw_digest(value.request_fingerprint.as_str(), "request fingerprint")?,
            timestamp_us(value.started_at, "acquisition started_at")?,
            started_clock,
            started_ns,
            value.source_locator.as_ref().map(StableString::as_str)
        ],
    )?;
    if changed == 0 {
        return Err(StoreError::IdentityConflict {
            kind: "acquisition",
            identity: value.acquisition_id.to_string(),
        });
    }
    tx.execute(
        "INSERT INTO acquisition_contract
         (acquisition_id,contract_version,acquisition_kind_recognition,
          transport_kind_recognition,requested_wall_us,received_wall_us,persisted_wall_us,
          elapsed_mono_ns,elapsed_clock_id,source_cursor_text)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
        params![
            value.acquisition_id.as_str(),
            value.contract_version.as_str(),
            recognition(&value.acquisition_kind),
            recognition(&value.transport_kind),
            value
                .clocks
                .requested_at
                .map(|time| timestamp_us(time, "requested_at"))
                .transpose()?,
            timestamp_us(value.clocks.received_at, "acquisition received_at")?,
            timestamp_us(value.clocks.persisted_at, "acquisition persisted_at")?,
            value
                .clocks
                .monotonic_elapsed_ns
                .map(|number| number.to_string()),
            value
                .clocks
                .monotonic_domain
                .as_ref()
                .map(StableString::as_str),
            value.source_cursor.as_ref().map(StableString::as_str)
        ],
    )?;
    Ok(())
}

fn insert_blob(tx: &Transaction<'_>, blob: &PreparedBlob, seq: i64) -> Result<()> {
    let changed = tx.execute(
        "INSERT OR IGNORE INTO blob
         (blob_id,created_commit_seq,storage_mode,inline_bytes,relative_path,content_length,
          stored_length,stored_sha256,compression,content_type,content_encoding,retention_class)
         VALUES (?1,?2,?3,?4,?5,?6,?6,?1,'identity',?7,?8,?9)",
        params![
            blob.raw_sha256,
            seq,
            blob.storage_mode(),
            blob.inline_bytes,
            blob.relative_path
                .as_ref()
                .map(|path| path.to_string_lossy()),
            sqlite_u64(blob.content_length, "blob content_length")?,
            blob.content_type.as_str(),
            blob.content_encoding.as_ref().map(StableString::as_str),
            blob.retention_class.as_str()
        ],
    )?;
    if changed == 0 {
        let exact: bool = tx.query_row(
            "SELECT content_length=?2 AND stored_sha256=?1
             FROM blob WHERE blob_id=?1",
            params![
                blob.raw_sha256,
                sqlite_u64(blob.content_length, "blob content_length")?,
            ],
            |row| row.get(0),
        )?;
        if !exact {
            return Err(StoreError::IdentityConflict {
                kind: "blob policy",
                identity: blob.blob_id.to_string(),
            });
        }
    }
    let object_changed = tx.execute(
        "INSERT OR IGNORE INTO blob_object
         (blob_id,storage_domain,storage_mode,inline_bytes,relative_path,stored_length,
          stored_sha256,compression)
         VALUES (?1,?2,?3,?4,?5,?6,?1,'identity')",
        params![
            blob.raw_sha256,
            blob.storage_domain.as_str(),
            blob.storage_mode(),
            blob.inline_bytes,
            blob.relative_path
                .as_ref()
                .map(|path| path.to_string_lossy()),
            sqlite_u64(blob.content_length, "blob stored_length")?
        ],
    )?;
    if object_changed == 0 {
        let exact: bool = tx.query_row(
            "SELECT storage_mode=?3 AND relative_path IS ?4 AND stored_length=?5
                    AND stored_sha256=?1
             FROM blob_object WHERE blob_id=?1 AND storage_domain=?2",
            params![
                blob.raw_sha256,
                blob.storage_domain.as_str(),
                blob.storage_mode(),
                blob.relative_path
                    .as_ref()
                    .map(|path| path.to_string_lossy()),
                sqlite_u64(blob.content_length, "blob stored_length")?
            ],
            |row| row.get(0),
        )?;
        if !exact {
            return Err(StoreError::IdentityConflict {
                kind: "blob protection domain",
                identity: format!("{}:{}", blob.blob_id, blob.storage_domain),
            });
        }
    }
    Ok(())
}

fn insert_source_event(tx: &Transaction<'_>, event: &SourceEventRecord, seq: i64) -> Result<()> {
    let changed = tx.execute(
        "INSERT OR IGNORE INTO source_event
         (source_event_id,source_id,event_namespace,natural_key,identified_commit_seq,source_order_key)
         VALUES (?1,?2,?3,?4,?5,?6)",
        params![
            event.source_event_id.as_str(),
            event.source_id.as_str(),
            event.namespace.as_str(),
            event.natural_key.as_str(),
            seq,
            event.source_order_key.as_ref().map(StableString::as_str)
        ],
    )?;
    if changed == 1 {
        tx.execute(
            "INSERT INTO source_event_contract
             (source_event_id,event_kind,event_kind_recognition) VALUES (?1,?2,?3)",
            params![
                event.source_event_id.as_str(),
                event.event_kind.discriminator.as_str(),
                recognition(&event.event_kind)
            ],
        )?;
        return Ok(());
    }
    let exact: bool = tx.query_row(
        "SELECT se.source_id=?2 AND se.event_namespace=?3 AND se.natural_key=?4
                AND se.source_order_key IS ?5 AND sec.event_kind=?6
                AND sec.event_kind_recognition=?7
         FROM source_event se JOIN source_event_contract sec USING(source_event_id)
         WHERE se.source_event_id=?1",
        params![
            event.source_event_id.as_str(),
            event.source_id.as_str(),
            event.namespace.as_str(),
            event.natural_key.as_str(),
            event.source_order_key.as_ref().map(StableString::as_str),
            event.event_kind.discriminator.as_str(),
            recognition(&event.event_kind)
        ],
        |row| row.get(0),
    )?;
    if exact {
        Ok(())
    } else {
        Err(StoreError::IdentityConflict {
            kind: "source event",
            identity: event.source_event_id.to_string(),
        })
    }
}

#[allow(clippy::too_many_lines)] // Base row and exact sidecars form one indivisible mapping.
fn insert_observation(
    tx: &Transaction<'_>,
    draft: &ObservationDraft,
    blob: &PreparedBlob,
    seq: i64,
    index: usize,
) -> Result<()> {
    let value = &draft.observation;
    require_known_one_of(
        &value.observation_kind,
        &[
            "frame",
            "response",
            "snapshot",
            "poll_result",
            "operator_capture",
            "fixture",
        ],
        "observation_kind",
    )?;
    require_known_one_of(
        &value.event_time.status,
        &["exact", "bounded", "source_missing", "not_applicable"],
        "event_time_status",
    )?;
    require_known_one_of(
        &value.parse_disposition,
        &[
            "pending",
            "decoded",
            "unsupported_variant",
            "malformed",
            "opaque",
        ],
        "parse_disposition",
    )?;
    let (event_lower, event_upper, precision) = match value.event_time.status.discriminator.as_str()
    {
        "exact" | "bounded" => (
            Some(timestamp_us(
                value.event_time.lower.ok_or_else(|| {
                    StoreError::InvalidBatch("timed observation lacks lower".into())
                })?,
                "event lower",
            )?),
            Some(timestamp_us(
                value.event_time.upper.ok_or_else(|| {
                    StoreError::InvalidBatch("timed observation lacks upper".into())
                })?,
                "event upper",
            )?),
            Some(sqlite_u64(
                value
                    .event_time
                    .precision_us
                    .ok_or_else(|| {
                        StoreError::InvalidBatch("timed observation lacks precision".into())
                    })?
                    .get(),
                "event precision",
            )?),
        ),
        _ => (None, None, None),
    };
    let (slot, tx_index, instruction_path, log_index, commitment, commitment_recognition) =
        if let Some(chain) = &value.chain {
            if let Some(commitment) = &chain.commitment {
                require_known_one_of(
                    commitment,
                    &["processed", "confirmed", "finalized"],
                    "chain commitment",
                )?;
            }
            let path = if chain.instruction_path.is_empty() {
                None
            } else {
                Some(serde_json::to_string(&chain.instruction_path)?)
            };
            (
                chain
                    .slot
                    .map(|number| sqlite_u64(number.get(), "chain slot"))
                    .transpose()?,
                chain
                    .transaction_index
                    .map(|number| sqlite_u64(number.get(), "chain tx index"))
                    .transpose()?,
                path,
                chain
                    .log_index
                    .map(|number| sqlite_u64(number.get(), "chain log index"))
                    .transpose()?,
                chain
                    .commitment
                    .as_ref()
                    .map(|variant| variant.discriminator.as_str()),
                chain.commitment.as_ref().map(recognition),
            )
        } else {
            (None, None, None, None, None, None)
        };
    tx.execute(
        "INSERT INTO observation
         (observation_id,commit_seq,intra_commit_seq,acquisition_id,acquisition_ordinal,
          source_id,blob_id,observation_kind,received_wall_us,received_clock_id,received_mono_ns,
          persisted_wall_us,available_wall_us,event_time_status,source_event_lower_us,
          source_event_upper_us,source_time_precision_us,chain_slot,chain_tx_index,
          chain_instruction_path,chain_log_index,chain_commitment,source_cursor_text,
          parse_disposition,quality_code)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,
                 ?18,?19,?20,?21,?22,?23,?24,?25)",
        params![
            value.observation_id.as_str(),
            seq,
            sqlite_usize(index, "intra_commit_seq")?,
            draft.acquisition.acquisition_id.as_str(),
            sqlite_u64(value.acquisition_ordinal.get(), "acquisition ordinal")?,
            draft.acquisition.source_id.as_str(),
            blob.raw_sha256,
            value.observation_kind.discriminator.as_str(),
            timestamp_us(value.timing.received_at, "observation received_at")?,
            value.timing.received_monotonic.clock_id.as_str(),
            value.timing.received_monotonic.nanoseconds.to_string(),
            timestamp_us(value.timing.persisted_at, "observation persisted_at")?,
            timestamp_us(value.timing.available_at, "observation available_at")?,
            value.event_time.status.discriminator.as_str(),
            event_lower,
            event_upper,
            precision,
            slot,
            tx_index,
            instruction_path,
            log_index,
            commitment,
            value.source_cursor.as_ref().map(StableString::as_str),
            value.parse_disposition.discriminator.as_str(),
            value.quality_code.as_ref().map(StableString::as_str)
        ],
    )?;
    tx.execute(
        "INSERT INTO observation_blob_contract
         (observation_id,blob_id,storage_domain,content_type,content_encoding,retention_class)
         VALUES (?1,?2,?3,?4,?5,?6)",
        params![
            value.observation_id.as_str(),
            blob.raw_sha256,
            blob.storage_domain.as_str(),
            blob.content_type.as_str(),
            blob.content_encoding.as_ref().map(StableString::as_str),
            blob.retention_class.as_str()
        ],
    )?;
    tx.execute(
        "INSERT INTO observation_contract
         (observation_id,observation_kind_recognition,source_variant,
          source_variant_recognition,event_time_status_recognition,
          chain_commitment_recognition,parse_disposition_recognition)
         VALUES (?1,?2,?3,?4,?5,?6,?7)",
        params![
            value.observation_id.as_str(),
            recognition(&value.observation_kind),
            value.source_variant.discriminator.as_str(),
            recognition(&value.source_variant),
            recognition(&value.event_time.status),
            commitment_recognition,
            recognition(&value.parse_disposition)
        ],
    )?;
    for link in &value.source_events {
        require_known_one_of(
            &link.relation,
            &["contains", "revision", "mentions"],
            "observation source-event relation",
        )?;
        tx.execute(
            "INSERT INTO observation_source_event
             (observation_id,source_event_id,relation,event_ordinal) VALUES (?1,?2,?3,?4)",
            params![
                value.observation_id.as_str(),
                link.source_event_id.as_str(),
                link.relation.discriminator.as_str(),
                link.event_ordinal
                    .map(|number| sqlite_u64(number.get(), "event ordinal"))
                    .transpose()?
            ],
        )?;
        tx.execute(
            "INSERT INTO observation_source_event_contract
             (observation_id,source_event_id,relation,relation_recognition)
             VALUES (?1,?2,?3,?4)",
            params![
                value.observation_id.as_str(),
                link.source_event_id.as_str(),
                link.relation.discriminator.as_str(),
                recognition(&link.relation)
            ],
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_lines)] // Assertion row and all typed evidence sidecars commit together.
fn insert_assertion(
    tx: &Transaction<'_>,
    value: &joshi_evidence::AssertionDraft,
    seq: i64,
) -> Result<()> {
    require_known_one_of(
        &value.assertion_status,
        &["candidate", "accepted", "unsupported", "retraction"],
        "assertion_status",
    )?;
    require_known_one_of(
        &value.valid_time.status,
        &["exact", "bounded", "unbounded", "not_applicable"],
        "valid_time_status",
    )?;
    reject_json_numbers(&value.extension, "assertion extension")?;
    if !value.extension.is_object() {
        return Err(StoreError::InvalidBatch(
            "assertion extension must be a JSON object".into(),
        ));
    }
    let (lower, upper) = match value.valid_time.status.discriminator.as_str() {
        "exact" | "bounded" => (
            Some(timestamp_us(
                value.valid_time.lower.ok_or_else(|| {
                    StoreError::InvalidBatch("timed assertion lacks lower".into())
                })?,
                "assertion valid lower",
            )?),
            Some(timestamp_us(
                value.valid_time.upper.ok_or_else(|| {
                    StoreError::InvalidBatch("timed assertion lacks upper".into())
                })?,
                "assertion valid upper",
            )?),
        ),
        _ => (None, None),
    };
    let json = serde_json::to_string(&value.extension)?;
    tx.execute(
        "INSERT INTO assertion
         (assertion_id,semantic_key,assertion_kind,producer_id,producer_version,
          produced_commit_seq,produced_wall_us,valid_time_status,valid_lower_us,valid_upper_us,
          assertion_status,value_json,value_sha256,supersedes_assertion_id)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)",
        params![
            value.assertion_id.as_str(),
            value.semantic_key.as_str(),
            value.assertion_kind.discriminator.as_str(),
            value.producer.as_str(),
            value.producer_version.as_str(),
            seq,
            timestamp_us(value.available_at, "assertion available_at")?,
            value.valid_time.status.discriminator.as_str(),
            lower,
            upper,
            value.assertion_status.discriminator.as_str(),
            json,
            raw_digest(value.value_digest.as_str(), "assertion value")?,
            value
                .supersedes_assertion_id
                .as_ref()
                .map(joshi_domain::AssertionId::as_str)
        ],
    )?;
    tx.execute(
        "INSERT INTO assertion_contract
         (assertion_id,assertion_kind_recognition,assertion_status_recognition,
          valid_time_status_recognition,available_wall_us) VALUES (?1,?2,?3,?4,?5)",
        params![
            value.assertion_id.as_str(),
            recognition(&value.assertion_kind),
            recognition(&value.assertion_status),
            recognition(&value.valid_time.status),
            timestamp_us(value.available_at, "assertion available_at")?
        ],
    )?;
    for evidence in &value.evidence {
        require_known_one_of(
            &evidence.role,
            &["decoded_from", "corroborates", "contradicts", "context"],
            "assertion observation role",
        )?;
        tx.execute(
            "INSERT INTO assertion_observation_evidence
             (assertion_id,observation_id,evidence_role) VALUES (?1,?2,?3)",
            params![
                value.assertion_id.as_str(),
                evidence.observation_id.as_str(),
                evidence.role.discriminator.as_str()
            ],
        )?;
        tx.execute(
            "INSERT INTO assertion_observation_evidence_contract
             (assertion_id,observation_id,evidence_role,role_recognition) VALUES (?1,?2,?3,?4)",
            params![
                value.assertion_id.as_str(),
                evidence.observation_id.as_str(),
                evidence.role.discriminator.as_str(),
                recognition(&evidence.role)
            ],
        )?;
    }
    for event in &value.source_events {
        require_known_one_of(
            &event.relation,
            &["claims_about", "reconciles", "context"],
            "assertion source-event relation",
        )?;
        tx.execute(
            "INSERT INTO assertion_source_event (assertion_id,source_event_id,relation) VALUES (?1,?2,?3)",
            params![value.assertion_id.as_str(), event.source_event_id.as_str(), event.relation.discriminator.as_str()],
        )?;
        tx.execute(
            "INSERT INTO assertion_source_event_contract
             (assertion_id,source_event_id,relation,relation_recognition) VALUES (?1,?2,?3,?4)",
            params![
                value.assertion_id.as_str(),
                event.source_event_id.as_str(),
                event.relation.discriminator.as_str(),
                recognition(&event.relation)
            ],
        )?;
    }
    for command in &value.command_evidence {
        require_known_one_of(
            &command.role,
            &[
                "prompted_by",
                "records_intent",
                "records_operator_claim",
                "context",
            ],
            "assertion command role",
        )?;
        tx.execute(
            "INSERT INTO assertion_command_evidence (assertion_id,command_id,evidence_role) VALUES (?1,?2,?3)",
            params![value.assertion_id.as_str(), command.command_id.as_str(), command.role.discriminator.as_str()],
        )?;
        tx.execute(
            "INSERT INTO assertion_command_evidence_contract
             (assertion_id,command_id,evidence_role,role_recognition) VALUES (?1,?2,?3,?4)",
            params![
                value.assertion_id.as_str(),
                command.command_id.as_str(),
                command.role.discriminator.as_str(),
                recognition(&command.role)
            ],
        )?;
    }
    Ok(())
}

fn insert_coverage_window(tx: &Transaction<'_>, value: &CoverageWindow, seq: i64) -> Result<()> {
    let level = coverage_level(value.scope.family.discriminator.as_str())?;
    let scope_key = value
        .scope
        .subject
        .as_ref()
        .map_or("__all__", StableString::as_str);
    let opened = match &value.lower {
        Boundary::Wall { value } => timestamp_us(*value, "coverage lower")?,
        _ => timestamp_us(value.available_at, "coverage available_at")?,
    };
    tx.execute(
        "INSERT INTO coverage_window
         (coverage_id,source_id,scope_kind,scope_key,opened_commit_seq,opened_wall_us,coverage_level)
         VALUES (?1,?2,?3,?4,?5,?6,?7)",
        params![value.coverage_id.as_str(), value.scope.source_id.as_str(),
            value.scope.family.discriminator.as_str(), scope_key, seq, opened, level],
    )?;
    tx.execute(
        "INSERT INTO coverage_event
         (coverage_event_id,coverage_id,commit_seq,event_kind,occurred_wall_us,detail_code)
         VALUES (?1,?2,?3,'opened',?4,?5)",
        params![
            format!("{}:opened", value.coverage_id),
            value.coverage_id.as_str(),
            seq,
            timestamp_us(value.available_at, "coverage available_at")?,
            value.state.discriminator.as_str()
        ],
    )?;
    tx.execute(
        "INSERT INTO coverage_window_contract
         (coverage_id,scope_family_recognition,scope_subject,lower_boundary_json,
          upper_boundary_json,state,state_recognition,available_wall_us)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
        params![
            value.coverage_id.as_str(),
            recognition(&value.scope.family),
            value.scope.subject.as_ref().map(StableString::as_str),
            serde_json::to_string(&value.lower)?,
            value
                .upper
                .as_ref()
                .map(serde_json::to_string)
                .transpose()?,
            value.state.discriminator.as_str(),
            recognition(&value.state),
            timestamp_us(value.available_at, "coverage available_at")?
        ],
    )?;
    Ok(())
}

fn insert_coverage_gap(
    tx: &Transaction<'_>,
    value: &CoverageGap,
    severity: &StableString,
    seq: i64,
) -> Result<()> {
    if !matches!(
        severity.as_str(),
        "degraded" | "scope_stopped" | "source_stopped"
    ) {
        return Err(StoreError::InvalidBatch(format!(
            "unsupported gap severity {severity}"
        )));
    }
    let (lower_locator, upper_locator) = (
        boundary_locator(Some(&value.lower)),
        boundary_locator(value.upper.as_ref()),
    );
    let (event_lower, event_upper) = match (&value.lower, &value.upper) {
        (Boundary::Wall { value: lower }, Some(Boundary::Wall { value: upper })) => (
            Some(timestamp_us(*lower, "gap event lower")?),
            Some(timestamp_us(*upper, "gap event upper")?),
        ),
        _ => (None, None),
    };
    tx.execute(
        "INSERT INTO coverage_gap
         (gap_id,coverage_id,detected_commit_seq,detected_wall_us,cause_code,severity,
          lower_source_locator,upper_source_locator,event_lower_us,event_upper_us)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
        params![
            value.gap_id.as_str(),
            value.coverage_id.as_str(),
            seq,
            timestamp_us(value.detected_at, "gap detected_at")?,
            value.reason.discriminator.as_str(),
            severity.as_str(),
            lower_locator,
            upper_locator,
            event_lower,
            event_upper
        ],
    )?;
    tx.execute(
        "INSERT INTO coverage_gap_contract
         (gap_id,scope_source_id,scope_family,scope_family_recognition,scope_subject,
          lower_boundary_json,upper_boundary_json,reason_recognition)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
        params![
            value.gap_id.as_str(),
            value.scope.source_id.as_str(),
            value.scope.family.discriminator.as_str(),
            recognition(&value.scope.family),
            value.scope.subject.as_ref().map(StableString::as_str),
            serde_json::to_string(&value.lower)?,
            value
                .upper
                .as_ref()
                .map(serde_json::to_string)
                .transpose()?,
            recognition(&value.reason)
        ],
    )?;
    Ok(())
}

fn insert_coverage_recovery(
    tx: &Transaction<'_>,
    value: &CoverageRecovery,
    seq: i64,
) -> Result<()> {
    require_known_one_of(
        &value.status,
        &["partial", "complete", "unrecoverable"],
        "recovery status",
    )?;
    tx.execute(
        "INSERT INTO coverage_gap_recovery
         (recovery_id,gap_id,recovery_acquisition_id,commit_seq,recovery_status,
          recovered_through_locator)
         VALUES (?1,?2,?3,?4,?5,?6)",
        params![
            value.recovery_id.as_str(),
            value.gap_id.as_str(),
            value
                .acquisition_id
                .as_ref()
                .map(joshi_domain::AcquisitionId::as_str),
            seq,
            value.status.discriminator.as_str(),
            boundary_locator(value.recovered_through.as_ref())
        ],
    )?;
    tx.execute(
        "INSERT INTO coverage_recovery_contract
         (recovery_id,status_recognition,recovered_through_json,available_wall_us)
         VALUES (?1,?2,?3,?4)",
        params![
            value.recovery_id.as_str(),
            recognition(&value.status),
            value
                .recovered_through
                .as_ref()
                .map(serde_json::to_string)
                .transpose()?,
            timestamp_us(value.available_at, "recovery available_at")?
        ],
    )?;
    for observation in &value.evidence {
        tx.execute(
            "INSERT INTO coverage_recovery_observation (recovery_id,observation_id) VALUES (?1,?2)",
            params![value.recovery_id.as_str(), observation.as_str()],
        )?;
    }
    Ok(())
}

fn insert_cursor(tx: &Transaction<'_>, value: &CursorAdvance, seq: i64) -> Result<()> {
    if value.evidence.is_empty() || !value.evidence.contains(&value.primary_observation_id) {
        return Err(StoreError::InvalidBatch(format!(
            "cursor {} evidence must contain its primary observation",
            value.cursor_id
        )));
    }
    let scope_key = value
        .scope
        .subject
        .as_ref()
        .map_or("__all__", StableString::as_str);
    tx.execute(
        "INSERT INTO source_cursor
         (cursor_id,source_id,scope_kind,scope_key,cursor_kind,cursor_value,
          advanced_commit_seq,acquisition_id,primary_evidence_observation_id,
          predecessor_cursor_id,evidence_count)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
        params![
            value.cursor_id.as_str(),
            value.scope.source_id.as_str(),
            value.scope.family.discriminator.as_str(),
            scope_key,
            value.cursor_kind.discriminator.as_str(),
            value.cursor_value.as_str(),
            seq,
            value.acquisition_id.as_str(),
            value.primary_observation_id.as_str(),
            value
                .predecessor_cursor_id
                .as_ref()
                .map(joshi_domain::CursorId::as_str),
            sqlite_usize(value.evidence.len(), "cursor evidence_count")?
        ],
    )?;
    tx.execute(
        "INSERT INTO source_cursor_contract
         (cursor_id,scope_family_recognition,scope_subject,cursor_kind_recognition)
         VALUES (?1,?2,?3,?4)",
        params![
            value.cursor_id.as_str(),
            recognition(&value.scope.family),
            value.scope.subject.as_ref().map(StableString::as_str),
            recognition(&value.cursor_kind)
        ],
    )?;
    for observation in &value.evidence {
        tx.execute(
            "INSERT INTO source_cursor_evidence (cursor_id,observation_id) VALUES (?1,?2)",
            params![value.cursor_id.as_str(), observation.as_str()],
        )?;
    }
    Ok(())
}

fn verify_contract_sidecars(tx: &Transaction<'_>, seq: i64) -> Result<()> {
    let missing: i64 = tx.query_row(
        "SELECT
           (SELECT COUNT(*) FROM acquisition a LEFT JOIN acquisition_contract d USING(acquisition_id)
            WHERE a.registered_commit_seq=?1 AND d.acquisition_id IS NULL)
         + (SELECT COUNT(*) FROM observation o LEFT JOIN observation_contract d USING(observation_id)
            WHERE o.commit_seq=?1 AND d.observation_id IS NULL)
         + (SELECT COUNT(*) FROM observation o LEFT JOIN observation_blob_contract d USING(observation_id)
            WHERE o.commit_seq=?1 AND d.observation_id IS NULL)
         + (SELECT COUNT(*) FROM source_event e LEFT JOIN source_event_contract d USING(source_event_id)
            WHERE e.identified_commit_seq=?1 AND d.source_event_id IS NULL)
         + (SELECT COUNT(*) FROM assertion a LEFT JOIN assertion_contract d USING(assertion_id)
            WHERE a.produced_commit_seq=?1 AND d.assertion_id IS NULL)
         + (SELECT COUNT(*) FROM coverage_window w LEFT JOIN coverage_window_contract d USING(coverage_id)
            WHERE w.opened_commit_seq=?1 AND d.coverage_id IS NULL)
         + (SELECT COUNT(*) FROM coverage_gap g LEFT JOIN coverage_gap_contract d USING(gap_id)
            WHERE g.detected_commit_seq=?1 AND d.gap_id IS NULL)
         + (SELECT COUNT(*) FROM coverage_gap_recovery r LEFT JOIN coverage_recovery_contract d USING(recovery_id)
            WHERE r.commit_seq=?1 AND d.recovery_id IS NULL)
         + (SELECT COUNT(*) FROM source_cursor c LEFT JOIN source_cursor_contract d USING(cursor_id)
            WHERE c.advanced_commit_seq=?1 AND d.cursor_id IS NULL)
         + (SELECT COUNT(*) FROM observation_source_event e
            JOIN observation o USING(observation_id)
            LEFT JOIN observation_source_event_contract d
              USING(observation_id,source_event_id,relation)
            WHERE o.commit_seq=?1 AND d.observation_id IS NULL)
         + (SELECT COUNT(*) FROM assertion_observation_evidence e
            JOIN assertion a USING(assertion_id)
            LEFT JOIN assertion_observation_evidence_contract d
              USING(assertion_id,observation_id,evidence_role)
            WHERE a.produced_commit_seq=?1 AND d.assertion_id IS NULL)
         + (SELECT COUNT(*) FROM assertion_source_event e
            JOIN assertion a USING(assertion_id)
            LEFT JOIN assertion_source_event_contract d
              USING(assertion_id,source_event_id,relation)
            WHERE a.produced_commit_seq=?1 AND d.assertion_id IS NULL)
         + (SELECT COUNT(*) FROM assertion_command_evidence e
            JOIN assertion a USING(assertion_id)
            LEFT JOIN assertion_command_evidence_contract d
              USING(assertion_id,command_id,evidence_role)
            WHERE a.produced_commit_seq=?1 AND d.assertion_id IS NULL)",
        [seq],
        |row| row.get(0),
    )?;
    if missing == 0 {
        Ok(())
    } else {
        Err(StoreError::InvalidBatch(format!(
            "commit {seq} has {missing} missing lossless contract sidecars"
        )))
    }
}

fn validate_policy_closure(batch: &StoreIngestBatch) -> Result<()> {
    let observation_ids = batch
        .evidence
        .observations
        .iter()
        .map(|value| value.observation.observation_id.as_str())
        .collect::<BTreeSet<_>>();
    let policy_ids = batch
        .observation_storage
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    if observation_ids != policy_ids {
        return Err(StoreError::InvalidBatch(
            "observation storage policy keys are not exact batch closure".into(),
        ));
    }
    let gap_ids = batch
        .evidence
        .coverage_gaps
        .iter()
        .map(|value| value.gap_id.as_str())
        .collect::<BTreeSet<_>>();
    let severity_ids = batch
        .coverage_gap_severity
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    if gap_ids != severity_ids {
        return Err(StoreError::InvalidBatch(
            "gap severity keys are not exact batch closure".into(),
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_lines)] // Canonical closure audits every set-like nested evidence family.
fn validate_canonical_batch(batch: &DurableIngestBatch) -> Result<()> {
    if batch.contract_version.as_str() != INGEST_CONTRACT {
        return Err(StoreError::InvalidBatch(format!(
            "unsupported ingest contract {}",
            batch.contract_version
        )));
    }
    ensure_sorted_unique(
        batch.observations.iter().map(|value| {
            (
                value.acquisition.acquisition_id.as_str(),
                value.observation.acquisition_ordinal.get(),
                value.observation.observation_id.as_str(),
            )
        }),
        "observations",
    )?;
    ensure_sorted_unique(
        batch
            .source_events
            .iter()
            .map(|value| value.source_event_id.as_str()),
        "source events",
    )?;
    ensure_sorted_unique(
        batch
            .assertions
            .iter()
            .map(|value| value.assertion_id.as_str()),
        "assertions",
    )?;
    ensure_sorted_unique(
        batch
            .coverage_windows
            .iter()
            .map(|value| value.coverage_id.as_str()),
        "coverage windows",
    )?;
    ensure_sorted_unique(
        batch
            .coverage_gaps
            .iter()
            .map(|value| value.gap_id.as_str()),
        "coverage gaps",
    )?;
    ensure_sorted_unique(
        batch
            .coverage_recoveries
            .iter()
            .map(|value| value.recovery_id.as_str()),
        "coverage recoveries",
    )?;
    ensure_sorted_unique(
        batch
            .cursor_advances
            .iter()
            .map(|value| value.cursor_id.as_str()),
        "cursor advances",
    )?;
    for observation in &batch.observations {
        ensure_sorted_unique(
            observation.observation.source_events.iter().map(|link| {
                (
                    link.source_event_id.as_str(),
                    link.relation.discriminator.as_str(),
                )
            }),
            "observation source-event links",
        )?;
    }
    for assertion in &batch.assertions {
        ensure_sorted_unique(
            assertion.evidence.iter().map(|value| {
                (
                    value.observation_id.as_str(),
                    value.role.discriminator.as_str(),
                )
            }),
            "assertion observation evidence",
        )?;
        ensure_sorted_unique(
            assertion.source_events.iter().map(|value| {
                (
                    value.source_event_id.as_str(),
                    value.relation.discriminator.as_str(),
                )
            }),
            "assertion source events",
        )?;
        ensure_sorted_unique(
            assertion
                .command_evidence
                .iter()
                .map(|value| (value.command_id.as_str(), value.role.discriminator.as_str())),
            "assertion command evidence",
        )?;
        reject_json_numbers(&assertion.extension, "assertion extension")?;
        validate_assertion_value_digest(assertion)?;
    }
    for recovery in &batch.coverage_recoveries {
        ensure_sorted_unique(
            recovery
                .evidence
                .iter()
                .map(joshi_domain::ObservationId::as_str),
            "recovery evidence",
        )?;
    }
    for cursor in &batch.cursor_advances {
        ensure_sorted_unique(
            cursor
                .evidence
                .iter()
                .map(joshi_domain::ObservationId::as_str),
            "cursor evidence",
        )?;
    }
    Ok(())
}

#[derive(Serialize)]
struct AssertionValueMaterial<'a> {
    contract: &'static str,
    assertion_kind: &'a OpenVariant,
    producer: &'a StableString,
    producer_version: &'a StableString,
    extension: &'a serde_json::Value,
}

fn validate_assertion_value_digest(value: &joshi_evidence::AssertionDraft) -> Result<()> {
    let encoded = serde_json::to_vec(&AssertionValueMaterial {
        contract: "joshi.assertion_value.v1",
        assertion_kind: &value.assertion_kind,
        producer: &value.producer,
        producer_version: &value.producer_version,
        extension: &value.extension,
    })?;
    let actual = format!("sha256:{}", sha256_hex(&encoded));
    if actual == value.value_digest.as_str() {
        Ok(())
    } else {
        Err(StoreError::InvalidDigest {
            kind: "assertion value",
            value: format!("expected {}, computed {actual}", value.value_digest),
        })
    }
}

fn ensure_sorted_unique<T: Ord>(
    values: impl IntoIterator<Item = T>,
    field: &'static str,
) -> Result<()> {
    let mut previous = None;
    for value in values {
        if previous.as_ref().is_some_and(|prior| prior >= &value) {
            return Err(StoreError::InvalidBatch(format!(
                "{field} must be strictly sorted and duplicate-free"
            )));
        }
        previous = Some(value);
    }
    Ok(())
}

#[derive(Serialize)]
struct AdmissionMaterial<'a> {
    contract: &'static str,
    logical_batch_digest: &'a str,
    observation_storage: &'a BTreeMap<String, ObservationStorage>,
    coverage_gap_severity: &'a BTreeMap<String, StableString>,
}

fn admission_digest(batch: &StoreIngestBatch, logical: &BatchDigest) -> Result<ValueDigest> {
    let material = AdmissionMaterial {
        contract: "joshi.store.admission.v1",
        logical_batch_digest: logical.as_str(),
        observation_storage: &batch.observation_storage,
        coverage_gap_severity: &batch.coverage_gap_severity,
    };
    let encoded = serde_json::to_vec(&material)?;
    ValueDigest::new(format!("sha256:{}", sha256_hex(&encoded)))
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}

fn reject_json_numbers(value: &serde_json::Value, field: &'static str) -> Result<()> {
    match value {
        serde_json::Value::Number(_) => Err(StoreError::InvalidBatch(format!(
            "{field} contains a JSON number; use an exact tagged string/object"
        ))),
        serde_json::Value::Array(values) => {
            for value in values {
                reject_json_numbers(value, field)?;
            }
            Ok(())
        }
        serde_json::Value::Object(values) => {
            for value in values.values() {
                reject_json_numbers(value, field)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

fn require_known_one_of(value: &OpenVariant, allowed: &[&str], field: &'static str) -> Result<()> {
    if value.recognition == VariantRecognition::Known
        && allowed.contains(&value.discriminator.as_str())
    {
        Ok(())
    } else {
        Err(StoreError::InvalidBatch(format!(
            "unsupported {field} {} ({:?})",
            value.discriminator, value.recognition
        )))
    }
}

fn recognition(value: &OpenVariant) -> &'static str {
    match value.recognition {
        VariantRecognition::Known => "known",
        VariantRecognition::Unknown => "unknown",
    }
}

fn stored_variant(discriminator: String, recognition: &str) -> Result<OpenVariant> {
    match recognition {
        "known" => OpenVariant::known(discriminator),
        "unknown" => OpenVariant::unknown(discriminator),
        _ => {
            return Err(StoreError::InvalidBatch(format!(
                "invalid stored variant recognition {recognition}"
            )));
        }
    }
    .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}

fn coverage_level(family: &str) -> Result<&'static str> {
    match family {
        "market_census" | "census" => Ok("census"),
        "hot_lane" | "hot" => Ok("hot"),
        "manual" => Ok("manual"),
        "fixture" => Ok("fixture"),
        _ => Err(StoreError::InvalidBatch(format!(
            "coverage family {family} has no indexed coverage level"
        ))),
    }
}

fn boundary_locator(boundary: Option<&Boundary>) -> Option<&str> {
    match boundary {
        Some(Boundary::SourceCursor { value }) => Some(value.as_str()),
        _ => None,
    }
}

fn timestamp_us(value: UtcTimestamp, field: &'static str) -> Result<i64> {
    let nanos = value.as_datetime().unix_timestamp_nanos();
    if nanos % 1_000 != 0 {
        return Err(StoreError::TimestampRange { field });
    }
    (nanos / 1_000)
        .try_into()
        .map_err(|_| StoreError::TimestampRange { field })
}

fn positive_timestamp_us(value: UtcTimestamp, field: &'static str) -> Result<i64> {
    let value = timestamp_us(value, field)?;
    if value <= 0 {
        return Err(StoreError::TimestampRange { field });
    }
    Ok(value)
}

fn timestamp_from_us(value: i64, field: &'static str) -> Result<UtcTimestamp> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or(StoreError::TimestampRange { field })?;
    let datetime = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|_| StoreError::TimestampRange { field })?;
    UtcTimestamp::new(datetime).map_err(|_| StoreError::TimestampRange { field })
}

fn raw_digest<'a>(value: &'a str, kind: &'static str) -> Result<&'a str> {
    let raw = value
        .strip_prefix("sha256:")
        .ok_or_else(|| StoreError::InvalidDigest {
            kind,
            value: value.to_owned(),
        })?;
    if raw.len() != 64
        || !raw
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(StoreError::InvalidDigest {
            kind,
            value: value.to_owned(),
        });
    }
    Ok(raw)
}

fn sqlite_u64(value: u64, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn sqlite_usize(value: usize, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn as_u64(value: i64, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn count_u64(value: usize, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

#[allow(clippy::too_many_lines)] // Replay mode, cutoffs, watermarks, and choices are one contract.
fn validate_scene_command_preflight(
    connection: &Connection,
    batch: &SceneCommandBatch,
) -> Result<()> {
    positive_timestamp_us(batch.committed_at, "command committed_at")?;
    if row_exists(
        connection,
        "command",
        "command_id",
        batch.command.command_id.as_str(),
    )? {
        return Err(StoreError::IdentityConflict {
            kind: "command",
            identity: batch.command.command_id.to_string(),
        });
    }
    let issued = positive_timestamp_us(batch.command.issued_at, "command issued_at")?;
    let received = positive_timestamp_us(batch.command.received_at, "command received_at")?;
    if received < issued {
        return Err(StoreError::InvalidBatch(
            "command received_at precedes issued_at".into(),
        ));
    }
    if let Some(scene) = &batch.scene {
        if row_exists(connection, "scene", "scene_id", scene.scene_id.as_str())? {
            return Err(StoreError::IdentityConflict {
                kind: "scene",
                identity: scene.scene_id.to_string(),
            });
        }
        if batch
            .command
            .scene_id
            .as_ref()
            .is_some_and(|id| id != &scene.scene_id)
        {
            return Err(StoreError::InvalidBatch(
                "command scene_id differs from atomic scene".into(),
            ));
        }
        if scene.view_contract_version == 0 {
            return Err(StoreError::InvalidBatch(
                "scene view contract version must be positive".into(),
            ));
        }
        if !matches!(
            scene.source_mode.as_str(),
            "fixture" | "manual_nomination" | "companion" | "replacement" | "observatory"
        ) {
            return Err(StoreError::InvalidBatch(format!(
                "unsupported scene source mode {}",
                scene.source_mode
            )));
        }
        let max: i64 = connection.query_row(
            "SELECT COALESCE(MAX(commit_seq),0) FROM ingest_commit",
            [],
            |row| row.get(0),
        )?;
        let max = as_u64(max, "max_commit_seq")?;
        if scene.knowledge_cutoff.get() == 0 || scene.knowledge_cutoff.get() > max {
            return Err(StoreError::InvalidBatch(
                "scene knowledge cutoff is not an existing commit".into(),
            ));
        }
        match scene.mode {
            SceneMode::Witnessed
                if scene.outcome_cutoff.is_some() || scene.basis_scene_id.is_some() =>
            {
                return Err(StoreError::InvalidBatch(
                    "witnessed scene cannot have outcome cutoff or basis".into(),
                ));
            }
            SceneMode::KnowledgeCutoff
                if scene.outcome_cutoff.is_some() || scene.basis_scene_id.is_none() =>
            {
                return Err(StoreError::InvalidBatch(
                    "knowledge-cutoff scene requires basis and no outcome cutoff".into(),
                ));
            }
            SceneMode::Retrospective
                if scene.basis_scene_id.is_none()
                    || scene.outcome_cutoff.is_none()
                    || scene.outcome_cutoff.is_some_and(|value| {
                        value < scene.knowledge_cutoff || value.get() > max
                    }) =>
            {
                return Err(StoreError::InvalidBatch(
                    "retrospective scene has invalid basis/outcome cutoff".into(),
                ));
            }
            _ => {}
        }
        if let Some(basis) = &scene.basis_scene_id
            && !row_exists(connection, "scene", "scene_id", basis.as_str())?
        {
            return Err(StoreError::MissingIdentity {
                kind: "basis scene",
                identity: basis.to_string(),
            });
        }
        positive_timestamp_us(scene.rendered_at, "scene rendered_at")?;
        ensure_sorted_unique(
            scene
                .watermarks
                .iter()
                .map(|value| value.namespace.as_str()),
            "scene watermarks",
        )?;
        ensure_sorted_unique(
            scene.choice_members.iter().map(|value| {
                (
                    value.set_kind.as_str(),
                    value.subject_kind.as_str(),
                    value.subject_key.as_str(),
                )
            }),
            "scene choice members",
        )?;
        for member in &scene.choice_members {
            if !matches!(
                member.set_kind.as_str(),
                "eligible" | "surfaced" | "rendered" | "viewport" | "interacted" | "compared"
            ) {
                return Err(StoreError::InvalidBatch(format!(
                    "unsupported scene choice set {}",
                    member.set_kind
                )));
            }
        }
    } else if let Some(scene_id) = &batch.command.scene_id
        && !row_exists(connection, "scene", "scene_id", scene_id.as_str())?
    {
        return Err(StoreError::MissingIdentity {
            kind: "scene",
            identity: scene_id.to_string(),
        });
    }
    Ok(())
}

fn scene_mode(value: SceneMode) -> &'static str {
    match value {
        SceneMode::Witnessed => "witnessed",
        SceneMode::KnowledgeCutoff => "knowledge_cutoff",
        SceneMode::Retrospective => "retrospective",
    }
}

fn parse_scene_mode(value: &str) -> Result<SceneMode> {
    match value {
        "witnessed" => Ok(SceneMode::Witnessed),
        "knowledge_cutoff" => Ok(SceneMode::KnowledgeCutoff),
        "retrospective" => Ok(SceneMode::Retrospective),
        _ => Err(StoreError::InvalidBatch(format!(
            "invalid stored scene mode {value}"
        ))),
    }
}

fn load_blob_object(
    connection: &Connection,
    root: &Path,
    blob_id: &str,
    storage_domain: &str,
) -> Result<Vec<u8>> {
    let (mode, inline, relative, length, digest): (
        String,
        Option<Vec<u8>>,
        Option<String>,
        i64,
        String,
    ) = connection.query_row(
        "SELECT storage_mode,inline_bytes,relative_path,stored_length,stored_sha256
         FROM blob_object WHERE blob_id=?1 AND storage_domain=?2",
        params![blob_id, storage_domain],
        |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
            ))
        },
    )?;
    let expected_length = as_u64(length, "blob stored_length")?;
    let bytes = match mode.as_str() {
        "inline" => inline
            .ok_or_else(|| StoreError::InvalidBatch("inline blob object lacks bytes".into()))?,
        "external" => {
            let path = relative.ok_or_else(|| {
                StoreError::InvalidBatch("external blob object lacks path".into())
            })?;
            let path = root.join(path);
            verify_file(&path, &digest, expected_length)?;
            fs::read(&path).map_err(|source| StoreError::io(path, source))?
        }
        _ => {
            return Err(StoreError::InvalidBatch(format!(
                "invalid blob storage mode {mode}"
            )));
        }
    };
    let actual_length = u64::try_from(bytes.len()).map_err(|_| StoreError::IntegerRange {
        field: "loaded blob length",
        value: bytes.len().to_string(),
    })?;
    if actual_length != expected_length || sha256_hex(&bytes) != digest {
        return Err(StoreError::ArtifactVerification {
            path: root.to_owned(),
            detail: "loaded blob bytes do not match stored closure".into(),
        });
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::{FAIL_BEFORE_INGEST_COMMIT, SqliteStore};
    use crate::{
        IdempotencyStatus, ObservationStorage, OperatorCaptureMetadata, ProjectionRegistration,
        SceneMode, SceneSourceMode, SourceRegistration, StoreConfig, StoreError, StoreIngestBatch,
        StoreMode, VerifyDepth,
        model::{
            ChoiceMemberDraft, CommandDraft, ExportDraft, ExportSnapshotDraft, SceneCommandBatch,
            SceneDraft,
        },
    };
    use joshi_domain::{
        AcquisitionId, BatchDigest, ClientSessionId, CommandId, CursorId, ObservationId,
        OpenVariant, RequestFingerprint, SceneId, SourceId, StableString, UtcTimestamp,
        ValueDigest, WireU64,
    };
    use joshi_evidence::{
        AcquisitionRecord, CoverageScope, CursorAdvance, DurableIngestBatch, MonotonicReading,
        ObservationDraft, ObservationEventTime, ObservationMetadata, ObservationTiming,
    };
    use joshi_export::{ExportSnapshotStatus, rewrite_snapshot_v1};
    use joshi_operator::{OperatorCommandStatus, ValidatedGlassViewV1, ValidatedOperatorCommandV1};
    use rusqlite::params;
    use std::{collections::BTreeMap, path::Path, time::Duration};

    fn stable(value: &str) -> StableString {
        StableString::new(value).expect("test stable string")
    }

    fn known(value: &str) -> OpenVariant {
        OpenVariant::known(value).expect("test variant")
    }

    fn time(value: &str) -> UtcTimestamp {
        value.parse().expect("test timestamp")
    }

    fn sha_identity() -> String {
        format!("sha256:{}", "0".repeat(64))
    }

    fn config(root: &Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: stable("catalog-test"),
            max_observations_per_batch: 16,
            max_raw_bytes_per_batch: 1024 * 1024,
        }
    }

    fn empty_batch(id: &str) -> StoreIngestBatch {
        let evidence = DurableIngestBatch {
            contract_version: stable("joshi.durable_ingest_batch.v1"),
            batch_id: stable(id),
            expected_digest: BatchDigest::new(sha_identity()).expect("test digest"),
            observations: Vec::new(),
            source_events: Vec::new(),
            assertions: Vec::new(),
            coverage_windows: Vec::new(),
            coverage_gaps: Vec::new(),
            coverage_recoveries: Vec::new(),
            cursor_advances: Vec::new(),
        };
        StoreIngestBatch {
            evidence,
            observation_storage: BTreeMap::new(),
            coverage_gap_severity: BTreeMap::new(),
            committed_at: time("2026-08-16T16:00:00.000000Z"),
            writer_clock_id: stable("writer-clock"),
            committed_mono_ns: 1,
            writer_build: stable("test-writer"),
        }
    }

    fn finalize_digest(batch: &mut StoreIngestBatch) {
        batch.evidence.expected_digest =
            SqliteStore::canonical_batch_digest(&batch.evidence).expect("canonical digest");
    }

    fn open_migrated(root: &Path) -> SqliteStore {
        let mut store =
            SqliteStore::open(config(root), StoreMode::SingleWriter).expect("open test store");
        let report = store
            .migrate(time("2026-08-16T16:00:00.000000Z"))
            .expect("migrate test store");
        assert_eq!(report.current, 10);
        store
    }

    #[test]
    #[allow(clippy::too_many_lines)] // One lifecycle test closes ingest, scene, and export identity.
    fn writer_lease_and_receipt_are_strict_and_idempotent() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let mut store = open_migrated(directory.path());
        assert!(matches!(
            SqliteStore::open(config(directory.path()), StoreMode::SingleWriter),
            Err(StoreError::WriterLeaseUnavailable(_))
        ));
        let mut batch = empty_batch("batch-empty");
        finalize_digest(&mut batch);
        let accepted = store.commit_ingest(&batch).expect("commit batch");
        assert_eq!(accepted.status, IdempotencyStatus::Accepted);
        let retried = store.commit_ingest(&batch).expect("retry batch");
        assert_eq!(retried.status, IdempotencyStatus::Idempotent);
        assert_eq!(accepted.batch_digest, retried.batch_digest);
        let json = serde_json::to_value(&accepted).expect("receipt JSON");
        assert_eq!(json["contract"], "joshi.store.ingest_receipt");
        assert_eq!(json["schemaVersion"], 1);
        assert_eq!(json["catalogSchema"], "joshi.sqlite.v10");
        assert_eq!(json["admitted"]["observations"], "0");
        assert!(json.get("storeAdmissionDigest").is_some());

        let mut conflicting = batch.clone();
        conflicting.observation_storage.insert(
            "not-in-batch".into(),
            ObservationStorage {
                retention_class: stable("fixture"),
                content_encoding: None,
                force_external: false,
            },
        );
        assert!(matches!(
            store.commit_ingest(&conflicting),
            Err(StoreError::InvalidBatch(_))
        ));

        let scene_id = SceneId::new("scene-test").expect("scene id");
        let scene_command = SceneCommandBatch {
            batch_id: stable("batch-scene-command"),
            scene: Some(SceneDraft {
                scene_id: scene_id.clone(),
                mode: SceneMode::Witnessed,
                knowledge_cutoff: accepted.commit_seq,
                outcome_cutoff: None,
                basis_scene_id: None,
                client_session_id: ClientSessionId::new("client-test").expect("client id"),
                client_scene_seq: 1,
                ui_build: stable("ui-test"),
                view_contract: stable("joshi.scene.fixture"),
                view_contract_version: 1,
                source_mode: stable("fixture"),
                rendered_at: time("2026-08-16T16:00:01.000000Z"),
                client_clock_id: stable("client-clock"),
                rendered_mono_ns: 1,
                view_bytes: br#"{"contract":"joshi.scene.fixture"}"#.to_vec(),
                screenshot_bytes: None,
                watermarks: Vec::new(),
                choice_members: vec![ChoiceMemberDraft {
                    set_kind: stable("viewport"),
                    subject_kind: stable("mint"),
                    subject_key: stable("mint-test"),
                    source_rank: Some(0),
                    rendered_ordinal: Some(0),
                    evidence_assertion_id: None,
                }],
            }),
            command: CommandDraft {
                command_id: CommandId::new("command-test").expect("command id"),
                scene_id: Some(scene_id.clone()),
                client_session_id: ClientSessionId::new("client-test").expect("client id"),
                client_command_seq: 1,
                idempotency_key: stable("command-test-key"),
                command_kind: stable("records_operator_claim"),
                subject_kind: stable("mint"),
                subject_key: stable("mint-test"),
                payload_bytes: br#"{"stance":"watch"}"#.to_vec(),
                issued_at: time("2026-08-16T16:00:01.000001Z"),
                client_clock_id: stable("client-clock"),
                issued_mono_ns: 2,
                received_at: time("2026-08-16T16:00:01.000002Z"),
            },
            committed_at: time("2026-08-16T16:00:01.000003Z"),
            writer_clock_id: stable("writer-clock"),
            committed_mono_ns: 2,
            writer_build: stable("test-writer"),
        };
        let command_receipt = store
            .commit_scene_command(&scene_command)
            .expect("commit scene command");
        assert_eq!(command_receipt.status, IdempotencyStatus::Accepted);
        let loaded = store.load_scene(&scene_id).expect("load exact scene");
        assert_eq!(
            loaded.view_bytes,
            scene_command.scene.expect("scene").view_bytes
        );

        store
            .register_projection(&ProjectionRegistration {
                name: stable("fixture.projection"),
                version: stable("v1"),
                producer_build: stable("projection-test"),
                configuration_digest: ValueDigest::new(sha_identity())
                    .expect("configuration digest"),
                schema_digest: ValueDigest::new(sha_identity()).expect("schema digest"),
                deterministic: true,
            })
            .expect("register projection");
        let part = store
            .prepare_export(
                Path::new("snapshot/part.fixture"),
                b"fixture analytical part",
            )
            .expect("prepare export part");
        let manifest = store
            .prepare_export(
                Path::new("snapshot/manifest.json"),
                b"{\"contract\":\"fixture.export\"}",
            )
            .expect("prepare export manifest");
        let part_draft = ExportDraft {
            export_manifest_id: stable("export-part-test"),
            family: stable("fixture_family"),
            family_schema_version: 1,
            generation: 1,
            part_ordinal: 0,
            projection: (stable("fixture.projection"), stable("v1")),
            from_commit_seq: accepted.commit_seq,
            through_commit_seq: command_receipt.commit_seq,
            input_manifest_digest: ValueDigest::new(sha_identity()).expect("input digest"),
            row_count: 1,
            format: stable("fixture_opaque"),
            compression: stable("fixture-none"),
            writer_version: stable("export-test"),
            schema_digest: ValueDigest::new(sha_identity()).expect("schema digest"),
            retention_class: stable("fixture"),
        };
        let snapshot = ExportSnapshotDraft {
            export_snapshot_id: stable("export-snapshot-test"),
            contract: stable("fixture.export"),
            schema_version: 1,
            from_commit_seq: accepted.commit_seq,
            through_commit_seq: command_receipt.commit_seq,
            scene_id: Some(scene_id),
        };
        let export_receipt = store
            .register_export_snapshot(
                &snapshot,
                &manifest,
                &[(&part_draft, &part)],
                time("2026-08-16T16:00:02.000000Z"),
                &stable("export-test"),
            )
            .expect("register export snapshot");
        assert_eq!(export_receipt.status, IdempotencyStatus::Accepted);
    }

    #[test]
    fn crash_before_commit_rolls_back_rows_and_retry_reuses_cas() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let mut store = open_migrated(directory.path());
        store
            .register_source(&source_registration())
            .expect("register source");
        let mut batch = observation_batch(true);
        finalize_digest(&mut batch);
        FAIL_BEFORE_INGEST_COMMIT.with(|failpoint| {
            *failpoint.borrow_mut() = Some("batch-observations");
        });
        assert!(matches!(
            store.commit_ingest(&batch),
            Err(StoreError::Injected("before ingest commit"))
        ));
        let commit_count: i64 = store
            .connection
            .query_row("SELECT COUNT(*) FROM ingest_commit", [], |row| row.get(0))
            .expect("count commits");
        assert_eq!(commit_count, 0);
        let receipt = store.commit_ingest(&batch).expect("retry after crash");
        assert_eq!(receipt.status, IdempotencyStatus::Accepted);
        assert_eq!(receipt.admitted.observations.get(), 4);
        assert_eq!(receipt.admitted.acquisitions.get(), 1);
        assert_eq!(receipt.admitted.raw_blobs.get(), 4);
        let cursors = store
            .justified_source_cursors_as_known(
                &SourceId::new("source-test").expect("source id"),
                receipt.commit_seq,
            )
            .expect("scoped cursors");
        assert_eq!(cursors.len(), 1);
        assert_eq!(cursors[0].cursor_value.as_str(), "cursor-4");
        let verification = store.verify(VerifyDepth::Full).expect("verify store");
        assert_eq!(verification.integrity, "ok");
        assert_eq!(verification.foreign_key_defects, 0);
    }

    #[test]
    fn rejects_wrong_digest_and_invalid_time_interval_before_cas() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let mut store = open_migrated(directory.path());
        store
            .register_source(&source_registration())
            .expect("register source");
        let mut wrong_digest = observation_batch(false);
        assert!(matches!(
            store.commit_ingest(&wrong_digest),
            Err(StoreError::InvalidDigest { kind: "batch", .. })
        ));
        finalize_digest(&mut wrong_digest);
        wrong_digest.evidence.observations[0]
            .observation
            .event_time
            .upper = None;
        finalize_digest(&mut wrong_digest);
        assert!(matches!(
            store.commit_ingest(&wrong_digest),
            Err(StoreError::InvalidBatch(_))
        ));
        assert_eq!(
            std::fs::read_dir(directory.path().join("blobs"))
                .expect("blob root")
                .count(),
            0
        );
    }

    #[test]
    #[allow(clippy::too_many_lines)] // Cross-language view, evidence and receipt closure is one case.
    fn typed_operator_admission_resolves_view_and_retries_exactly() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let mut store = open_migrated(directory.path());
        store
            .register_source(&source_registration())
            .expect("register source");
        let mut evidence = observation_batch(false);
        finalize_digest(&mut evidence);
        let ingest = store
            .commit_ingest(&evidence)
            .expect("commit source evidence");
        assert_eq!(ingest.commit_seq, joshi_domain::CommitSeq::new(1));

        let view_source = extract_ts(
            include_str!("../../../apps/glass/src/contract/golden.ts"),
            "GOLDEN_VIEW_V1_JSON",
        );
        let cursor_block = r#""deliveredThrough":"6","cursors":[{"family":"attention","subject":"census","cursorKind":"epoch","value":"cursor-census-6","advancedThrough":"6"},{"family":"attention","subject":"hot:coin-a","cursorKind":"sequence","value":"cursor-hot-4","advancedThrough":"4"}]"#;
        let view_bytes = view_source
            .replace("source-a", "source-test")
            .replace("\"catalogCommit\":\"7\"", "\"catalogCommit\":\"1\"")
            .replace(
                cursor_block,
                r#""deliveredThrough":"1","cursors":[{"family":"fixture","subject":"test-scope","cursorKind":"page","value":"cursor-4","advancedThrough":"1"}]"#,
            )
            .replace(
                r#""projections":[{"name":"attention","version":"1","stateDigest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]"#,
                r#""projections":[]"#,
            )
            .replace("evidence-a", "observation-0")
            .replace("2026-08-16T18:42:02.000000Z", "2026-08-16T15:59:57.000000Z")
            .replace("2026-08-16T18:42:10.000000Z", "2026-08-16T15:59:58.000000Z")
            .replace("2026-08-16T18:42:12.000000Z", "2026-08-16T15:59:59.000000Z")
            .replace("2026-08-16T18:42:13.000000Z", "2026-08-16T16:00:02.000000Z")
            .replace("2026-08-16T18:42:14.000000Z", "2026-08-16T16:00:02.000002Z")
            .replace(
                "\"receivedThrough\":\"2026-08-16T16:00:02.000002Z\"",
                "\"receivedThrough\":\"2026-08-16T16:00:02.000000Z\"",
            )
            .replace("2026-08-16T18:42:15.000000Z", "2026-08-16T16:00:04.000000Z");
        let view = ValidatedGlassViewV1::parse_exact(view_bytes.as_bytes(), None)
            .expect("parse exact typed view");
        let command_source = extract_ts(
            include_str!("../../../apps/glass/src/operator/golden.ts"),
            "GOLDEN_OPERATOR_COMMAND_V1_JSON",
        );
        let command_bytes = command_source
            .replace(
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                view.digest().as_str(),
            )
            .replace("\"key\":\"radon\"", "\"key\":\"coin-a\"");
        let command = ValidatedOperatorCommandV1::parse_exact(command_bytes.as_bytes())
            .expect("parse exact typed command");
        let capture = OperatorCaptureMetadata {
            client_scene_seq: 1,
            ui_build: stable("glass-test"),
            source_mode: SceneSourceMode::Fixture,
            rendered_clock_id: stable("browser-clock"),
            rendered_mono_ns: 8,
            screenshot_bytes: None,
        };
        let receipt = store
            .commit_operator_v1(
                &command,
                Some(&view),
                &capture,
                time("2026-08-16T18:42:19.000000Z"),
                stable("writer-clock"),
                9,
                stable("test-writer"),
            )
            .expect("admit typed operator command");
        assert_eq!(receipt.status(), OperatorCommandStatus::Accepted);
        let receipt_json = serde_json::to_value(&receipt).expect("operator receipt JSON");
        assert_eq!(receipt_json["contract"], "joshi.store.command_receipt");
        assert_eq!(receipt_json["schemaVersion"], 1);
        assert_eq!(receipt_json["catalogSchema"], "joshi.sqlite.v10");
        assert_eq!(receipt_json["scene"]["sceneId"], "scene-golden-1");
        assert_eq!(receipt_json["scene"]["viewDigest"], view.digest().as_str());
        assert_eq!(
            receipt_json["commandPayloadDigest"],
            command.payload_digest().as_str()
        );
        let retry = store
            .commit_operator_v1(
                &command,
                None,
                &capture,
                time("2026-08-16T18:42:20.000000Z"),
                stable("writer-clock"),
                10,
                stable("test-writer"),
            )
            .expect("exact typed retry");
        assert_eq!(retry.status(), OperatorCommandStatus::Idempotent);
        assert_eq!(retry.commit_seq(), receipt.commit_seq());
        assert_eq!(
            store
                .load_scene(view.scene_id())
                .expect("load typed scene")
                .view_bytes,
            view.canonical_bytes()
        );
    }

    #[test]
    fn acquisition_without_source_monotonic_round_trips_as_null_pair() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let mut store = open_migrated(directory.path());
        store
            .register_source(&source_registration())
            .expect("register source");
        let mut batch = observation_batch(false);
        for observation in &mut batch.evidence.observations {
            observation.acquisition.started_monotonic = None;
        }
        finalize_digest(&mut batch);
        store
            .commit_ingest(&batch)
            .expect("commit acquisition with unavailable monotonic clock");
        let pair: (Option<String>, Option<String>) = store
            .connection
            .query_row(
                "SELECT local_clock_id,started_mono_ns FROM acquisition
                 WHERE acquisition_id='acquisition-test'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .expect("read optional monotonic pair");
        assert_eq!(pair, (None, None));
    }

    #[test]
    fn typed_fixture_export_registers_exact_manifest_and_fourteen_parts() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let mut fixture_config = config(directory.path());
        fixture_config.catalog_id = stable("catalog:joshi:offline-fixture");
        let mut store =
            SqliteStore::open(fixture_config, StoreMode::SingleWriter).expect("open fixture store");
        store
            .migrate(time("2026-08-16T16:00:00.000000Z"))
            .expect("migrate fixture store");
        for sequence in 1..=120_u64 {
            let mut batch = empty_batch(&format!("fixture-commit-{sequence}"));
            finalize_digest(&mut batch);
            let receipt = store.commit_ingest(&batch).expect("fixture commit");
            assert_eq!(receipt.commit_seq, joshi_domain::CommitSeq::new(sequence));
        }
        store
            .register_projection(&ProjectionRegistration {
                name: stable("research_exocortex"),
                version: stable("1"),
                producer_build: stable("fixture-projection"),
                configuration_digest: ValueDigest::new(sha_identity())
                    .expect("configuration digest"),
                schema_digest: ValueDigest::new(sha_identity()).expect("schema digest"),
                deterministic: true,
            })
            .expect("register fixture projection");
        store
            .connection
            .execute(
                "INSERT INTO projection_checkpoint
                 (checkpoint_id,projection_name,projection_version,through_commit_seq,
                  created_commit_seq,input_manifest_sha256,output_sha256)
                 VALUES ('checkpoint:fixture:120','research_exocortex','1',120,120,?1,?2)",
                params![
                    "0".repeat(64),
                    "255981f362f1db9b532f333549dc4e6168b4bd110c8b4c5a3890231bf96b0d4f"
                ],
            )
            .expect("register exact projection checkpoint");
        let generated = directory.path().join("generated-snapshot");
        let snapshot = rewrite_snapshot_v1(
            Path::new(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../analysis/fixtures/snapshot_v1"
            )),
            &generated,
        )
        .expect("rewrite exact snapshot");
        let receipt = store
            .commit_fixture_export_snapshot_v1(
                &snapshot,
                time("2026-08-16T18:01:00.000000Z"),
                &stable("store-export-test"),
            )
            .expect("register typed fixture snapshot");
        assert_eq!(receipt.status(), ExportSnapshotStatus::Accepted);
        let receipt_json = serde_json::to_value(&receipt).expect("export receipt JSON");
        assert_eq!(
            receipt_json["contract"],
            "joshi.store.export_snapshot_receipt"
        );
        assert_eq!(receipt_json["snapshotId"], snapshot.snapshot_id().as_str());
        assert_eq!(
            receipt_json["manifestDigest"],
            snapshot.manifest_digest().as_str()
        );
        let retry = store
            .commit_fixture_export_snapshot_v1(
                &snapshot,
                time("2026-08-16T18:02:00.000000Z"),
                &stable("store-export-test"),
            )
            .expect("retry typed fixture snapshot");
        assert_eq!(retry.status(), ExportSnapshotStatus::Idempotent);
        assert_eq!(retry.commit_seq(), receipt.commit_seq());
        let part_count: i64 = store
            .connection
            .query_row(
                "SELECT COUNT(*) FROM export_snapshot_part WHERE export_snapshot_id=?1",
                [snapshot.snapshot_id().as_str()],
                |row| row.get(0),
            )
            .expect("count snapshot parts");
        assert_eq!(part_count, 14);
    }

    fn extract_ts(source: &str, name: &str) -> String {
        let prefix = format!("export const {name} = `");
        let rest = source.split_once(&prefix).expect("golden prefix").1;
        rest.split_once("`;\n").expect("golden suffix").0.to_owned()
    }

    fn source_registration() -> SourceRegistration {
        SourceRegistration {
            source_id: SourceId::new("source-test").expect("source id"),
            namespace: stable("fixture.test"),
            contract_version: stable("v1"),
            collector_build: stable("collector-test"),
            configuration_digest: ValueDigest::new(sha_identity()).expect("configuration digest"),
        }
    }

    #[allow(clippy::too_many_lines)] // Test fixture spells out every independent clock/status field.
    fn observation_batch(force_external: bool) -> StoreIngestBatch {
        let source_id = SourceId::new("source-test").expect("source id");
        let acquisition = AcquisitionRecord {
            acquisition_id: AcquisitionId::new("acquisition-test").expect("acquisition id"),
            source_id: source_id.clone(),
            acquisition_kind: known("fixture"),
            transport_kind: known("fixture"),
            parent_acquisition_id: None,
            request_fingerprint: RequestFingerprint::new(sha_identity())
                .expect("request fingerprint"),
            contract_version: stable("v1"),
            started_at: time("2026-08-16T16:00:01.000000Z"),
            started_monotonic: Some(MonotonicReading {
                clock_id: stable("source-clock"),
                nanoseconds: WireU64::new(1),
            }),
            source_locator: Some(stable("fixture://test")),
            source_cursor: Some(stable("descriptive-not-authority")),
            clocks: joshi_domain::AcquisitionClocks {
                requested_at: Some(time("2026-08-16T16:00:01.000000Z")),
                received_at: time("2026-08-16T16:00:02.000000Z"),
                persisted_at: time("2026-08-16T16:00:02.000001Z"),
                monotonic_elapsed_ns: Some(WireU64::new(1_000)),
                monotonic_domain: Some(stable("source-clock")),
            },
        };
        let statuses = [
            (
                "exact",
                Some("2026-08-16T15:59:59.000000Z"),
                Some("2026-08-16T15:59:59.000001Z"),
                Some(1),
            ),
            (
                "bounded",
                Some("2026-08-16T15:59:59.000010Z"),
                Some("2026-08-16T15:59:59.000020Z"),
                Some(1),
            ),
            ("source_missing", None, None, None),
            ("not_applicable", None, None, None),
        ];
        let mut observations = Vec::new();
        let mut policies = BTreeMap::new();
        for (ordinal, (status, lower, upper, precision)) in statuses.into_iter().enumerate() {
            let observation_id =
                ObservationId::new(format!("observation-{ordinal}")).expect("observation id");
            policies.insert(
                observation_id.to_string(),
                ObservationStorage {
                    retention_class: stable("fixture"),
                    content_encoding: Some(stable("identity")),
                    force_external,
                },
            );
            observations.push(ObservationDraft {
                acquisition: acquisition.clone(),
                observation: ObservationMetadata {
                    observation_id,
                    acquisition_ordinal: WireU64::new(ordinal as u64),
                    observation_kind: known("fixture"),
                    source_events: Vec::new(),
                    source_variant: if ordinal == 2 {
                        OpenVariant::unknown("provider.future").expect("unknown variant")
                    } else {
                        known("fixture.payload")
                    },
                    event_time: ObservationEventTime {
                        status: known(status),
                        lower: lower.map(time),
                        upper: upper.map(time),
                        precision_us: precision.map(WireU64::new),
                    },
                    chain: None,
                    source_cursor: Some(stable(&format!("descriptive-{ordinal}"))),
                    timing: ObservationTiming {
                        received_at: time("2026-08-16T16:00:02.000000Z"),
                        received_monotonic: MonotonicReading {
                            clock_id: stable("source-clock"),
                            nanoseconds: WireU64::new(2 + ordinal as u64),
                        },
                        persisted_at: time("2026-08-16T16:00:02.000001Z"),
                        available_at: time("2026-08-16T16:00:02.000002Z"),
                    },
                    parse_disposition: if ordinal == 2 {
                        known("unsupported_variant")
                    } else {
                        known("decoded")
                    },
                    quality_code: None,
                    media_type: stable("application/json"),
                },
                payload: format!("{{\"ordinal\":\"{ordinal}\"}}").into_bytes(),
            });
        }
        let cursor = CursorAdvance {
            cursor_id: CursorId::new("cursor-test").expect("cursor id"),
            scope: CoverageScope {
                source_id,
                family: known("fixture"),
                subject: Some(stable("test-scope")),
            },
            cursor_kind: known("page"),
            cursor_value: stable("cursor-4"),
            acquisition_id: acquisition.acquisition_id,
            primary_observation_id: observations[0].observation.observation_id.clone(),
            evidence: vec![observations[0].observation.observation_id.clone()],
            predecessor_cursor_id: None,
        };
        StoreIngestBatch {
            evidence: DurableIngestBatch {
                contract_version: stable("joshi.durable_ingest_batch.v1"),
                batch_id: stable("batch-observations"),
                expected_digest: BatchDigest::new(sha_identity()).expect("batch digest"),
                observations,
                source_events: Vec::new(),
                assertions: Vec::new(),
                coverage_windows: Vec::new(),
                coverage_gaps: Vec::new(),
                coverage_recoveries: Vec::new(),
                cursor_advances: vec![cursor],
            },
            observation_storage: policies,
            coverage_gap_severity: BTreeMap::new(),
            committed_at: time("2026-08-16T16:00:03.000000Z"),
            writer_clock_id: stable("writer-clock"),
            committed_mono_ns: 10,
            writer_build: stable("test-writer"),
        }
    }
}
