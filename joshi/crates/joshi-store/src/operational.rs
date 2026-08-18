//! Private-capability persistence for Wave 4 immutable operational artifacts.

#![allow(clippy::items_after_statements)]

use crate::{IdempotencyStatus, Result, SqliteStore, StoreError};
use joshi_artifact_admission::{
    DERIVED_ARTIFACT_CONTRACT_V2, DISPLAY_CLASS, ValidatedDerivedArtifactV2,
};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_export::ValidatedProductionSnapshotV2;
use rusqlite::{OptionalExtension, Transaction, TransactionBehavior, params};
use serde::Serialize;
use sha2::{Digest as _, Sha256};
use std::{fs, path::PathBuf};

const AUTHORITY: &str = "read_only_no_execution";
const MAX_ARTIFACT_BYTES: usize = 4 * 1024 * 1024;

/// Writer-owned clock/build material for one operational append.
#[derive(Clone, Debug)]
pub struct OperationalCommitContext {
    batch_id: StableString,
    committed_at: UtcTimestamp,
    writer_clock_id: StableString,
    committed_mono_ns: u64,
    writer_build: StableString,
}

impl OperationalCommitContext {
    #[must_use]
    pub const fn new(
        batch_id: StableString,
        committed_at: UtcTimestamp,
        writer_clock_id: StableString,
        committed_mono_ns: u64,
        writer_build: StableString,
    ) -> Self {
        Self {
            batch_id,
            committed_at,
            writer_clock_id,
            committed_mono_ns,
            writer_build,
        }
    }

    #[must_use]
    pub const fn batch_id(&self) -> &StableString {
        &self.batch_id
    }

    #[must_use]
    pub const fn committed_at(&self) -> UtcTimestamp {
        self.committed_at
    }
}

/// Structural result available only after a durable commit or exact readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationalCommitReceipt {
    catalog_id: StableString,
    catalog_schema: StableString,
    batch_id: StableString,
    occurrence_id: StableString,
    commit_seq: CommitSeq,
    operation_digest: ValueDigest,
    status: IdempotencyStatus,
}

impl OperationalCommitReceipt {
    #[must_use]
    pub const fn catalog_id(&self) -> &StableString {
        &self.catalog_id
    }

    #[must_use]
    pub const fn catalog_schema(&self) -> &StableString {
        &self.catalog_schema
    }

    #[must_use]
    pub const fn batch_id(&self) -> &StableString {
        &self.batch_id
    }

    #[must_use]
    pub const fn occurrence_id(&self) -> &StableString {
        &self.occurrence_id
    }

    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }

    #[must_use]
    pub const fn operation_digest(&self) -> &ValueDigest {
        &self.operation_digest
    }

    #[must_use]
    pub const fn status(&self) -> IdempotencyStatus {
        self.status
    }
}

/// Post-commit closure for one production export occurrence and its content-derived snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionExportCommitReceipt {
    catalog_id: StableString,
    catalog_schema: StableString,
    batch_id: StableString,
    export_request_id: StableString,
    validation_id: StableString,
    snapshot_id: ValueDigest,
    manifest_digest: ValueDigest,
    rust_validation_digest: ValueDigest,
    python_validation_digest: ValueDigest,
    validation_digest: ValueDigest,
    truth_fingerprint: ValueDigest,
    commit_seq: CommitSeq,
    status: IdempotencyStatus,
}

impl ProductionExportCommitReceipt {
    #[must_use]
    pub const fn catalog_id(&self) -> &StableString {
        &self.catalog_id
    }
    #[must_use]
    pub const fn catalog_schema(&self) -> &StableString {
        &self.catalog_schema
    }
    #[must_use]
    pub const fn batch_id(&self) -> &StableString {
        &self.batch_id
    }
    #[must_use]
    pub const fn export_request_id(&self) -> &StableString {
        &self.export_request_id
    }
    #[must_use]
    pub const fn validation_id(&self) -> &StableString {
        &self.validation_id
    }
    #[must_use]
    pub const fn snapshot_id(&self) -> &ValueDigest {
        &self.snapshot_id
    }
    #[must_use]
    pub const fn manifest_digest(&self) -> &ValueDigest {
        &self.manifest_digest
    }
    #[must_use]
    pub const fn rust_validation_digest(&self) -> &ValueDigest {
        &self.rust_validation_digest
    }
    #[must_use]
    pub const fn python_validation_digest(&self) -> &ValueDigest {
        &self.python_validation_digest
    }
    #[must_use]
    pub const fn validation_digest(&self) -> &ValueDigest {
        &self.validation_digest
    }
    #[must_use]
    pub const fn truth_fingerprint(&self) -> &ValueDigest {
        &self.truth_fingerprint
    }
    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }
    #[must_use]
    pub const fn status(&self) -> IdempotencyStatus {
        self.status
    }
}

/// Post-commit closure for one reserved import occurrence and its derived content artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AnalysisArtifactCommitReceipt {
    catalog_id: StableString,
    catalog_schema: StableString,
    batch_id: StableString,
    import_id: StableString,
    export_request_id: StableString,
    analysis_run_id: StableString,
    artifact_id: ValueDigest,
    artifact_contract: StableString,
    artifact_digest: ValueDigest,
    manifest_digest: ValueDigest,
    snapshot_id: ValueDigest,
    snapshot_manifest_digest: ValueDigest,
    claim_scope: StableString,
    truth_fingerprint: ValueDigest,
    commit_seq: CommitSeq,
    status: IdempotencyStatus,
}

impl AnalysisArtifactCommitReceipt {
    #[must_use]
    pub const fn catalog_id(&self) -> &StableString {
        &self.catalog_id
    }
    #[must_use]
    pub const fn catalog_schema(&self) -> &StableString {
        &self.catalog_schema
    }
    #[must_use]
    pub const fn batch_id(&self) -> &StableString {
        &self.batch_id
    }
    #[must_use]
    pub const fn import_id(&self) -> &StableString {
        &self.import_id
    }
    #[must_use]
    pub const fn export_request_id(&self) -> &StableString {
        &self.export_request_id
    }
    #[must_use]
    pub const fn analysis_run_id(&self) -> &StableString {
        &self.analysis_run_id
    }
    #[must_use]
    pub const fn artifact_id(&self) -> &ValueDigest {
        &self.artifact_id
    }
    #[must_use]
    pub const fn artifact_contract(&self) -> &StableString {
        &self.artifact_contract
    }
    #[must_use]
    pub const fn artifact_digest(&self) -> &ValueDigest {
        &self.artifact_digest
    }
    #[must_use]
    pub const fn manifest_digest(&self) -> &ValueDigest {
        &self.manifest_digest
    }
    #[must_use]
    pub const fn snapshot_id(&self) -> &ValueDigest {
        &self.snapshot_id
    }
    #[must_use]
    pub const fn snapshot_manifest_digest(&self) -> &ValueDigest {
        &self.snapshot_manifest_digest
    }
    #[must_use]
    pub const fn claim_scope(&self) -> &StableString {
        &self.claim_scope
    }
    #[must_use]
    pub const fn truth_fingerprint(&self) -> &ValueDigest {
        &self.truth_fingerprint
    }
    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }
    #[must_use]
    pub const fn status(&self) -> IdempotencyStatus {
        self.status
    }
}

/// One immutable derived artifact part loaded and reverified after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredAnalysisArtifactPart {
    pub import_id: StableString,
    pub analysis_run_id: StableString,
    pub artifact_id: ValueDigest,
    pub relative_path: PathBuf,
    pub schema_id: StableString,
    pub schema_digest: ValueDigest,
    pub physical_digest: ValueDigest,
    pub logical_digest: ValueDigest,
    pub byte_length: u64,
    pub row_count: u64,
}

/// Exact protocol registration sealed by the semantic admission layer before store I/O.
#[derive(Clone, Debug)]
pub struct EpisodeProtocolCapability {
    protocol_registration_id: StableString,
    protocol_definition_id: StableString,
    protocol_revision: u64,
    protocol_digest: ValueDigest,
    protocol_bytes: Vec<u8>,
    build_digest: ValueDigest,
    configuration_digest: ValueDigest,
    budget_digest: ValueDigest,
    privacy_digest: ValueDigest,
    duration_us: u64,
    warmup_offset_us: u64,
    choice_deadline_offset_us: u64,
    outcome_horizon_offset_us: u64,
    knowledge_deadline_offset_us: u64,
}

impl EpisodeProtocolCapability {
    /// Seals one already semantically validated exact protocol registration.
    ///
    /// # Errors
    ///
    /// Returns an error for changed bytes, zero identities/timing, or non-frozen timing formulas.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        protocol_registration_id: StableString,
        protocol_definition_id: StableString,
        protocol_revision: u64,
        protocol_digest: ValueDigest,
        protocol_bytes: Vec<u8>,
        build_digest: ValueDigest,
        configuration_digest: ValueDigest,
        budget_digest: ValueDigest,
        privacy_digest: ValueDigest,
        duration_us: u64,
        warmup_offset_us: u64,
        choice_deadline_offset_us: u64,
        outcome_horizon_offset_us: u64,
        knowledge_deadline_offset_us: u64,
    ) -> Result<Self> {
        require_exact_bytes(&protocol_digest, &protocol_bytes, "episode protocol")?;
        if protocol_revision == 0
            || !(1_800_000_000..=5_400_000_000).contains(&duration_us)
            || !duration_us.is_multiple_of(60_000_000)
            || warmup_offset_us != 300_000_000
            || choice_deadline_offset_us != duration_us.saturating_mul(3) / 5
            || outcome_horizon_offset_us != duration_us.saturating_add(1_800_000_000)
            || knowledge_deadline_offset_us != outcome_horizon_offset_us.saturating_add(900_000_000)
        {
            return Err(StoreError::InvalidBatch(
                "episode protocol violates frozen prospective timing".into(),
            ));
        }
        Ok(Self {
            protocol_registration_id,
            protocol_definition_id,
            protocol_revision,
            protocol_digest,
            protocol_bytes,
            build_digest,
            configuration_digest,
            budget_digest,
            privacy_digest,
            duration_us,
            warmup_offset_us,
            choice_deadline_offset_us,
            outcome_horizon_offset_us,
            knowledge_deadline_offset_us,
        })
    }
}

/// Exact stored protocol registration plus post-commit occurrence metadata.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredEpisodeProtocol {
    pub protocol_registration_id: StableString,
    pub protocol_definition_id: StableString,
    pub protocol_revision: u64,
    pub protocol_digest: ValueDigest,
    pub protocol_bytes: Vec<u8>,
    pub batch_id: StableString,
    pub commit_seq: CommitSeq,
    pub committed_at: UtcTimestamp,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceFactFamily {
    SourceFact,
    WalletTopology,
    SocialAttention,
    Lifecycle,
    PoolState,
    MarketState,
    AcquisitionPolicy,
}

impl SourceFactFamily {
    const fn as_str(self) -> &'static str {
        match self {
            Self::SourceFact => "source_fact",
            Self::WalletTopology => "wallet_topology",
            Self::SocialAttention => "social_attention",
            Self::Lifecycle => "lifecycle",
            Self::PoolState => "pool_state",
            Self::MarketState => "market_state",
            Self::AcquisitionPolicy => "acquisition_policy",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactProtectionClass {
    PublicIntegrity,
    AuthenticatedPrivate,
}

impl ArtifactProtectionClass {
    const fn as_str(self) -> &'static str {
        match self {
            Self::PublicIntegrity => "public_integrity",
            Self::AuthenticatedPrivate => "authenticated_private",
        }
    }
}

#[derive(Clone, Debug)]
pub struct SourceFactArtifactCapability {
    artifact_id: StableString,
    family: SourceFactFamily,
    contract: StableString,
    schema_version: u64,
    artifact_digest: ValueDigest,
    bytes: Vec<u8>,
    input_closure_digest: ValueDigest,
    known_through: CommitSeq,
    maximum_input_available_at: UtcTimestamp,
    protection_class: ArtifactProtectionClass,
}

impl SourceFactArtifactCapability {
    /// Validates and seals an exact source/fact artifact for the private store boundary.
    ///
    /// # Errors
    ///
    /// Returns an error for wrong byte digest, empty/oversized bytes, or invalid schema/cutoff.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        artifact_id: StableString,
        family: SourceFactFamily,
        contract: StableString,
        schema_version: u64,
        artifact_digest: ValueDigest,
        bytes: Vec<u8>,
        input_closure_digest: ValueDigest,
        known_through: CommitSeq,
        maximum_input_available_at: UtcTimestamp,
        protection_class: ArtifactProtectionClass,
    ) -> Result<Self> {
        require_exact_bytes(&artifact_digest, &bytes, "source/fact artifact")?;
        if schema_version == 0 || known_through.get() == 0 {
            return Err(StoreError::InvalidBatch(
                "source/fact artifact requires positive schema and cutoff".into(),
            ));
        }
        timestamp_us(maximum_input_available_at, "maximum input availability")?;
        Ok(Self {
            artifact_id,
            family,
            contract,
            schema_version,
            artifact_digest,
            bytes,
            input_closure_digest,
            known_through,
            maximum_input_available_at,
            protection_class,
        })
    }

    #[must_use]
    pub const fn artifact_id(&self) -> &StableString {
        &self.artifact_id
    }

    #[must_use]
    pub const fn artifact_digest(&self) -> &ValueDigest {
        &self.artifact_digest
    }

    #[must_use]
    pub const fn input_closure_digest(&self) -> &ValueDigest {
        &self.input_closure_digest
    }

    #[must_use]
    pub const fn known_through(&self) -> CommitSeq {
        self.known_through
    }
}

#[derive(Clone, Debug)]
pub struct ProjectionPublicationCapability {
    publication_id: StableString,
    projection_id: StableString,
    result_digest: ValueDigest,
    artifact_digest: ValueDigest,
    artifact_bytes: Vec<u8>,
    input_closure_digest: ValueDigest,
    publication_digest: ValueDigest,
    publication_bytes_digest: ValueDigest,
    publication_bytes: Vec<u8>,
    through_commit: CommitSeq,
    supersedes_publication_id: Option<StableString>,
}

impl ProjectionPublicationCapability {
    /// Validates distinct result, artifact-byte, publication-semantic, and publication-byte domains.
    ///
    /// # Errors
    ///
    /// Returns an error for wrong exact-byte closure, zero cutoff, or self-supersession.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        publication_id: StableString,
        projection_id: StableString,
        result_digest: ValueDigest,
        artifact_digest: ValueDigest,
        artifact_bytes: Vec<u8>,
        input_closure_digest: ValueDigest,
        publication_digest: ValueDigest,
        publication_bytes_digest: ValueDigest,
        publication_bytes: Vec<u8>,
        through_commit: CommitSeq,
        supersedes_publication_id: Option<StableString>,
    ) -> Result<Self> {
        require_exact_bytes(&artifact_digest, &artifact_bytes, "projection artifact")?;
        require_exact_bytes(
            &publication_bytes_digest,
            &publication_bytes,
            "projection publication bytes",
        )?;
        if through_commit.get() == 0
            || supersedes_publication_id
                .as_ref()
                .is_some_and(|value| value == &publication_id)
        {
            return Err(StoreError::InvalidBatch(
                "projection publication has invalid cutoff or self-supersession".into(),
            ));
        }
        Ok(Self {
            publication_id,
            projection_id,
            result_digest,
            artifact_digest,
            artifact_bytes,
            input_closure_digest,
            publication_digest,
            publication_bytes_digest,
            publication_bytes,
            through_commit,
            supersedes_publication_id,
        })
    }

    #[must_use]
    pub const fn publication_id(&self) -> &StableString {
        &self.publication_id
    }

    #[must_use]
    pub const fn result_digest(&self) -> &ValueDigest {
        &self.result_digest
    }

    #[must_use]
    pub const fn artifact_digest(&self) -> &ValueDigest {
        &self.artifact_digest
    }

    #[must_use]
    pub const fn publication_digest(&self) -> &ValueDigest {
        &self.publication_digest
    }

    #[must_use]
    pub const fn publication_bytes_digest(&self) -> &ValueDigest {
        &self.publication_bytes_digest
    }

    #[must_use]
    pub const fn through_commit(&self) -> CommitSeq {
        self.through_commit
    }
}

#[derive(Clone, Debug)]
pub struct CockpitPublicationCapability {
    cockpit_publication_id: StableString,
    scene_id: StableString,
    projection_publication_id: StableString,
    projection_publication_digest: ValueDigest,
    result_digest: ValueDigest,
    artifact_digest: ValueDigest,
    query_policy: StableString,
    manifest_digest: ValueDigest,
    manifest_bytes: Vec<u8>,
    cockpit_publication_digest: ValueDigest,
    supersedes_cockpit_publication_id: Option<StableString>,
}

impl CockpitPublicationCapability {
    /// Validates an immutable cockpit head and its exact manifest bytes.
    ///
    /// # Errors
    ///
    /// Returns an error for a wrong manifest closure or self-supersession.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        cockpit_publication_id: StableString,
        scene_id: StableString,
        projection_publication_id: StableString,
        projection_publication_digest: ValueDigest,
        result_digest: ValueDigest,
        artifact_digest: ValueDigest,
        query_policy: StableString,
        manifest_digest: ValueDigest,
        manifest_bytes: Vec<u8>,
        cockpit_publication_digest: ValueDigest,
        supersedes_cockpit_publication_id: Option<StableString>,
    ) -> Result<Self> {
        require_exact_bytes(&manifest_digest, &manifest_bytes, "cockpit publication")?;
        if supersedes_cockpit_publication_id
            .as_ref()
            .is_some_and(|value| value == &cockpit_publication_id)
        {
            return Err(StoreError::InvalidBatch(
                "cockpit publication cannot supersede itself".into(),
            ));
        }
        Ok(Self {
            cockpit_publication_id,
            scene_id,
            projection_publication_id,
            projection_publication_digest,
            result_digest,
            artifact_digest,
            query_policy,
            manifest_digest,
            manifest_bytes,
            cockpit_publication_digest,
            supersedes_cockpit_publication_id,
        })
    }

    #[must_use]
    pub const fn cockpit_publication_id(&self) -> &StableString {
        &self.cockpit_publication_id
    }

    #[must_use]
    pub const fn manifest_digest(&self) -> &ValueDigest {
        &self.manifest_digest
    }

    #[must_use]
    pub const fn cockpit_publication_digest(&self) -> &ValueDigest {
        &self.cockpit_publication_digest
    }
}

impl SqliteStore {
    /// Commits one independently validated legacy Snapshot V2 while the catalog is at the V9
    /// bootstrap boundary.
    ///
    /// The snapshot remains bound to its exact V8/V9 source catalog and fourteen-table profile;
    /// this method only supplies the durable occurrence needed before the same store advances to
    /// V10. It cannot commit or retry after that migration.
    ///
    /// # Errors
    ///
    /// Returns an error outside V9, for a non-legacy snapshot, or for any ordinary production
    /// snapshot validation/commit failure.
    pub fn commit_wave5_baseline_export_snapshot_v2(
        &mut self,
        validation_id: &StableString,
        snapshot: &ValidatedProductionSnapshotV2,
        context: &OperationalCommitContext,
    ) -> Result<ProductionExportCommitReceipt> {
        if self.catalog_schema_id()?.as_str() != "joshi.sqlite.v9"
            || !matches!(
                snapshot.catalog_schema().as_str(),
                "joshi.sqlite.v8" | "joshi.sqlite.v9"
            )
            || snapshot.tables().len() != 14
        {
            return Err(StoreError::InvalidBatch(
                "Wave 5 baseline export requires V9 and the exact legacy Snapshot V2 profile"
                    .into(),
            ));
        }
        self.commit_production_export_snapshot_v2(validation_id, snapshot, context)
    }

    /// Atomically appends one exact, already-validated prospective protocol registration.
    ///
    /// This freezes read-only study timing and exact bytes. It does not create a launch, browser
    /// pairing session, operator choice, or economic power.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid digest/timing closure, identity conflict, integer overflow,
    /// or failed durable commit.
    pub fn commit_episode_protocol_v1(
        &mut self,
        capability: &EpisodeProtocolCapability,
        context: &OperationalCommitContext,
    ) -> Result<OperationalCommitReceipt> {
        let digest = operation_digest(&(
            "joshi.store.episode_protocol_commit.v1",
            capability.protocol_registration_id.as_str(),
            capability.protocol_definition_id.as_str(),
            capability.protocol_revision,
            capability.protocol_digest.as_str(),
            capability.build_digest.as_str(),
            capability.configuration_digest.as_str(),
            capability.budget_digest.as_str(),
            capability.privacy_digest.as_str(),
            capability.duration_us,
            capability.warmup_offset_us,
            capability.choice_deadline_offset_us,
            capability.outcome_horizon_offset_us,
            capability.knowledge_deadline_offset_us,
        ))?;
        self.commit_operational(
            context,
            "command",
            &capability.protocol_registration_id,
            &digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO episode_protocol_v1
                     (protocol_registration_id,protocol_definition_id,protocol_revision,
                      protocol_sha256,protocol_bytes,protocol_byte_length,build_sha256,
                      configuration_sha256,budget_sha256,privacy_sha256,duration_us,
                      warmup_offset_us,choice_deadline_offset_us,outcome_horizon_offset_us,
                      knowledge_deadline_offset_us,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17)",
                    params![
                        capability.protocol_registration_id.as_str(),
                        capability.protocol_definition_id.as_str(),
                        sqlite_u64(capability.protocol_revision, "protocol revision")?,
                        raw_digest(capability.protocol_digest.as_str(), "protocol")?,
                        capability.protocol_bytes,
                        sqlite_usize(capability.protocol_bytes.len(), "protocol byte length")?,
                        raw_digest(capability.build_digest.as_str(), "protocol build")?,
                        raw_digest(
                            capability.configuration_digest.as_str(),
                            "protocol configuration",
                        )?,
                        raw_digest(capability.budget_digest.as_str(), "protocol budget")?,
                        raw_digest(capability.privacy_digest.as_str(), "protocol privacy")?,
                        sqlite_u64(capability.duration_us, "protocol duration")?,
                        sqlite_u64(capability.warmup_offset_us, "protocol warmup")?,
                        sqlite_u64(capability.choice_deadline_offset_us, "protocol choice")?,
                        sqlite_u64(capability.outcome_horizon_offset_us, "protocol outcome")?,
                        sqlite_u64(
                            capability.knowledge_deadline_offset_us,
                            "protocol knowledge"
                        )?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Loads and revalidates the exact retained protocol registration after restart.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed persisted identities, digests, timestamps, or integers.
    pub fn load_episode_protocol_v1(
        &self,
        protocol_registration_id: &StableString,
    ) -> Result<Option<StoredEpisodeProtocol>> {
        type ProtocolRow = (String, i64, String, Vec<u8>, String, i64, i64);
        let row: Option<ProtocolRow> = self
            .connection
            .query_row(
                "SELECT p.protocol_definition_id,p.protocol_revision,p.protocol_sha256,
                        p.protocol_bytes,c.commit_id,p.created_commit_seq,c.committed_wall_us
                 FROM episode_protocol_v1 p
                 JOIN ingest_commit c ON c.commit_seq=p.created_commit_seq
                 WHERE p.protocol_registration_id=?1",
                [protocol_registration_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                    ))
                },
            )
            .optional()?;
        let Some((definition, revision, digest, bytes, batch, seq, committed)) = row else {
            return Ok(None);
        };
        let digest = qualified_raw_digest(&digest, "protocol")?;
        require_exact_bytes(&digest, &bytes, "episode protocol")?;
        Ok(Some(StoredEpisodeProtocol {
            protocol_registration_id: protocol_registration_id.clone(),
            protocol_definition_id: stable_string(definition, "protocol definition ID")?,
            protocol_revision: as_u64(revision, "protocol revision")?,
            protocol_digest: digest,
            protocol_bytes: bytes,
            batch_id: stable_string(batch, "protocol batch ID")?,
            commit_seq: CommitSeq::new(as_u64(seq, "protocol commit sequence")?),
            committed_at: timestamp_from_us(committed, "protocol committed_at")?,
        }))
    }

    /// Atomically appends an already-validated source/fact artifact.
    ///
    /// # Errors
    ///
    /// Returns an error for a future cutoff, identity conflict, invalid capability, or failed commit.
    pub fn commit_source_fact_artifact_v1(
        &mut self,
        capability: &SourceFactArtifactCapability,
        context: &OperationalCommitContext,
    ) -> Result<OperationalCommitReceipt> {
        if capability.known_through > self.max_commit_seq()? {
            return Err(StoreError::InvalidBatch(
                "source/fact artifact cutoff exceeds durable catalog".into(),
            ));
        }
        let digest = operation_digest(&(
            "joshi.store.source_fact_artifact_commit.v1",
            capability.artifact_id.as_str(),
            capability.family.as_str(),
            capability.contract.as_str(),
            capability.schema_version,
            capability.artifact_digest.as_str(),
            capability.input_closure_digest.as_str(),
            capability.known_through.get(),
            capability.maximum_input_available_at.to_string(),
            capability.protection_class.as_str(),
        ))?;
        self.commit_operational(
            context,
            "projection",
            &capability.artifact_id,
            &digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO source_fact_artifact
                     (artifact_id,artifact_family,artifact_contract,artifact_schema_version,
                      artifact_sha256,artifact_bytes,artifact_byte_length,input_closure_sha256,
                      known_through_commit_seq,maximum_input_available_wall_us,protection_class,
                      authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
                    params![
                        capability.artifact_id.as_str(),
                        capability.family.as_str(),
                        capability.contract.as_str(),
                        sqlite_u64(capability.schema_version, "artifact schema version")?,
                        raw_digest(capability.artifact_digest.as_str(), "artifact")?,
                        capability.bytes,
                        sqlite_usize(capability.bytes.len(), "artifact byte length")?,
                        raw_digest(capability.input_closure_digest.as_str(), "input closure")?,
                        sqlite_u64(capability.known_through.get(), "known through")?,
                        timestamp_us(
                            capability.maximum_input_available_at,
                            "maximum input availability",
                        )?,
                        capability.protection_class.as_str(),
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Atomically appends exact projection artifact/publication bytes and their distinct digests.
    ///
    /// # Errors
    ///
    /// Returns an error for a future cutoff, missing references, identity conflict, or failed commit.
    pub fn commit_projection_publication_v1(
        &mut self,
        capability: &ProjectionPublicationCapability,
        context: &OperationalCommitContext,
    ) -> Result<OperationalCommitReceipt> {
        if capability.through_commit > self.max_commit_seq()? {
            return Err(StoreError::InvalidBatch(
                "projection publication cutoff exceeds durable catalog".into(),
            ));
        }
        let digest = operation_digest(&(
            "joshi.store.projection_publication_commit.v1",
            capability.publication_id.as_str(),
            capability.projection_id.as_str(),
            capability.result_digest.as_str(),
            capability.artifact_digest.as_str(),
            capability.input_closure_digest.as_str(),
            capability.publication_digest.as_str(),
            capability.publication_bytes_digest.as_str(),
            capability.through_commit.get(),
            capability
                .supersedes_publication_id
                .as_ref()
                .map(StableString::as_str),
        ))?;
        self.commit_operational(
            context,
            "projection",
            &capability.publication_id,
            &digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO projection_publication
                     (publication_id,projection_id,result_sha256,artifact_sha256,artifact_bytes,
                      artifact_byte_length,input_closure_sha256,publication_sha256,
                      publication_bytes_sha256,
                      publication_bytes,publication_byte_length,through_commit_seq,
                      supersedes_publication_id,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)",
                    params![
                        capability.publication_id.as_str(),
                        capability.projection_id.as_str(),
                        raw_digest(capability.result_digest.as_str(), "result")?,
                        raw_digest(capability.artifact_digest.as_str(), "artifact")?,
                        capability.artifact_bytes,
                        sqlite_usize(capability.artifact_bytes.len(), "artifact byte length")?,
                        raw_digest(capability.input_closure_digest.as_str(), "input closure")?,
                        raw_digest(capability.publication_digest.as_str(), "publication")?,
                        raw_digest(
                            capability.publication_bytes_digest.as_str(),
                            "publication bytes",
                        )?,
                        capability.publication_bytes,
                        sqlite_usize(
                            capability.publication_bytes.len(),
                            "publication byte length",
                        )?,
                        sqlite_u64(capability.through_commit.get(), "publication cutoff")?,
                        capability
                            .supersedes_publication_id
                            .as_ref()
                            .map(StableString::as_str),
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Appends a cockpit head only after its exact scene and projection publication are durable.
    ///
    /// # Errors
    ///
    /// Returns an error for missing/mismatched references, identity conflict, or failed commit.
    pub fn commit_cockpit_publication_v1(
        &mut self,
        capability: &CockpitPublicationCapability,
        context: &OperationalCommitContext,
    ) -> Result<OperationalCommitReceipt> {
        let digest = operation_digest(&(
            "joshi.store.cockpit_publication_commit.v1",
            capability.cockpit_publication_id.as_str(),
            capability.scene_id.as_str(),
            capability.projection_publication_id.as_str(),
            capability.projection_publication_digest.as_str(),
            capability.result_digest.as_str(),
            capability.artifact_digest.as_str(),
            capability.query_policy.as_str(),
            capability.manifest_digest.as_str(),
            capability.cockpit_publication_digest.as_str(),
            capability
                .supersedes_cockpit_publication_id
                .as_ref()
                .map(StableString::as_str),
        ))?;
        self.commit_operational(
            context,
            "projection",
            &capability.cockpit_publication_id,
            &digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO cockpit_publication
                     (cockpit_publication_id,scene_id,projection_publication_id,
                      projection_publication_sha256,projection_result_sha256,
                      projection_artifact_sha256,query_policy,manifest_sha256,
                      cockpit_publication_sha256,manifest_bytes,manifest_byte_length,
                      supersedes_cockpit_publication_id,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)",
                    params![
                        capability.cockpit_publication_id.as_str(),
                        capability.scene_id.as_str(),
                        capability.projection_publication_id.as_str(),
                        raw_digest(
                            capability.projection_publication_digest.as_str(),
                            "projection publication",
                        )?,
                        raw_digest(capability.result_digest.as_str(), "projection result")?,
                        raw_digest(capability.artifact_digest.as_str(), "projection artifact")?,
                        capability.query_policy.as_str(),
                        raw_digest(capability.manifest_digest.as_str(), "cockpit manifest")?,
                        raw_digest(
                            capability.cockpit_publication_digest.as_str(),
                            "cockpit publication",
                        )?,
                        capability.manifest_bytes,
                        sqlite_usize(capability.manifest_bytes.len(), "cockpit manifest length")?,
                        capability
                            .supersedes_cockpit_publication_id
                            .as_ref()
                            .map(StableString::as_str),
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Atomically registers one independently validated production Snapshot V2 with the exact
    /// legacy or V10 table set, preserving the export-request occurrence separately from the
    /// content-derived snapshot identity.
    ///
    /// # Errors
    ///
    /// Returns an error for a foreign/stale catalog closure, missing publication or projection,
    /// changed prepared bytes, identity conflict, or failed durable commit.
    #[allow(clippy::too_many_lines)]
    pub(crate) fn commit_production_export_snapshot_v2(
        &mut self,
        validation_id: &StableString,
        snapshot: &ValidatedProductionSnapshotV2,
        context: &OperationalCommitContext,
    ) -> Result<ProductionExportCommitReceipt> {
        self.require_writer()?;
        let (from_commit, through_commit) = snapshot.commit_range();
        const V10_TABLES: &[(&str, &str)] = &[
            ("scenes", "joshi.analysis.scene/v1"),
            ("territories", "joshi.analysis.territory/v1"),
            ("candidates", "joshi.analysis.candidate/v1"),
            (
                "candidate_social_assertions",
                "joshi.analysis.candidate-social-assertion/v1",
            ),
            ("decisions", "joshi.analysis.decision/v1"),
            ("choice_members", "joshi.analysis.choice-member/v1"),
            ("episodes", "joshi.analysis.episode/v1"),
            ("chart_samples", "joshi.analysis.chart-sample/v1"),
            ("operator_gestures", "joshi.analysis.operator-gesture/v1"),
            (
                "operator_interviews",
                "joshi.analysis.operator-interview/v1",
            ),
            ("outcomes", "joshi.analysis.competing-risk-outcome/v1"),
            (
                "provenance_assertions",
                "joshi.analysis.provenance-assertion/v1",
            ),
            ("coverage_windows", "joshi.analysis.coverage-window/v1"),
            ("coverage_gaps", "joshi.analysis.coverage-gap/v1"),
            (
                "source_fact_occurrences",
                "joshi.analysis.source-fact-occurrence/v1",
            ),
            (
                "publication_occurrences",
                "joshi.analysis.publication-occurrence/v1",
            ),
            ("scene_occurrences", "joshi.analysis.scene-occurrence/v1"),
            ("act_occurrences", "joshi.analysis.act-occurrence/v1"),
            (
                "episode_occurrences",
                "joshi.analysis.episode-occurrence/v1",
            ),
            ("run_occurrences", "joshi.analysis.run-occurrence/v1"),
            (
                "spool_catalog_occurrences",
                "joshi.analysis.spool-catalog-occurrence/v1",
            ),
            ("status_occurrences", "joshi.analysis.status-occurrence/v1"),
            ("export_occurrences", "joshi.analysis.export-occurrence/v1"),
            ("import_occurrences", "joshi.analysis.import-occurrence/v1"),
        ];
        let legacy_tables = &V10_TABLES[..14];
        let expected_tables = match snapshot.catalog_schema().as_str() {
            "joshi.sqlite.v8" | "joshi.sqlite.v9" => legacy_tables,
            "joshi.sqlite.v10" => V10_TABLES,
            _ => &[],
        };
        let exact_tables = snapshot.tables().iter().enumerate().all(|(index, table)| {
            expected_tables.get(index).is_some_and(|(name, schema)| {
                table.name().as_str() == *name
                    && table.schema_id().as_str() == *schema
                    && table.ordinal() == u64::try_from(index).unwrap_or(u64::MAX)
            })
        });
        if snapshot.catalog_id() != &self.config.catalog_id
            || from_commit.get() == 0
            || through_commit > self.max_commit_seq()?
            || expected_tables.is_empty()
            || snapshot.tables().len() != expected_tables.len()
            || !exact_tables
        {
            return Err(StoreError::InvalidBatch(
                "production snapshot catalog/range/table closure differs from this store".into(),
            ));
        }
        for publication_id in snapshot.publication_ids() {
            let query = if snapshot.catalog_schema().as_str() == "joshi.sqlite.v10" {
                "SELECT EXISTS(
                    SELECT 1 FROM projection_publication
                    WHERE publication_id=?1 AND created_commit_seq<=?2
                    UNION ALL
                    SELECT 1 FROM cockpit_publication
                    WHERE cockpit_publication_id=?1 AND created_commit_seq<=?2
                    UNION ALL
                    SELECT 1 FROM cockpit_v2_publication_v1 publication
                    JOIN cockpit_v2_head_v1 head
                      ON head.publication_id=publication.publication_id
                     AND head.source_occurrence_id=publication.source_occurrence_id
                    WHERE publication.publication_id=?1
                      AND publication.created_commit_seq<=?2
                      AND head.created_commit_seq<=?2
                 )"
            } else {
                "SELECT EXISTS(
                    SELECT 1 FROM projection_publication
                    WHERE publication_id=?1 AND created_commit_seq<=?2
                    UNION ALL
                    SELECT 1 FROM cockpit_publication
                    WHERE cockpit_publication_id=?1 AND created_commit_seq<=?2
                 )"
            };
            let exists: bool = self.connection.query_row(
                query,
                params![
                    publication_id.as_str(),
                    sqlite_u64(through_commit.get(), "snapshot publication cutoff")?
                ],
                |row| row.get(0),
            )?;
            if !exists {
                return Err(StoreError::MissingIdentity {
                    kind: "snapshot publication",
                    identity: publication_id.to_string(),
                });
            }
        }
        let prefix = PathBuf::from("production-v2").join(snapshot.snapshot_id().as_str());
        let manifest =
            self.prepare_export(&prefix.join("manifest.json"), snapshot.manifest_bytes())?;
        if &manifest.digest != snapshot.manifest_digest() {
            return Err(StoreError::InvalidBatch(
                "prepared production manifest differs from validated bytes".into(),
            ));
        }
        let mut prepared_parts = Vec::with_capacity(snapshot.tables().len());
        for table in snapshot.tables() {
            let bytes = fs::read(table.absolute_path())
                .map_err(|source| StoreError::io(table.absolute_path(), source))?;
            let prepared = self.prepare_export(&prefix.join(table.relative_path()), &bytes)?;
            if &prepared.digest != table.physical_digest()
                || prepared.byte_length != table.byte_length()
            {
                return Err(StoreError::InvalidBatch(format!(
                    "prepared production table {} differs from validated bytes",
                    table.name()
                )));
            }
            prepared_parts.push(prepared);
        }

        let truth_fingerprint = operation_digest(snapshot.truth_fingerprint())?;
        let export_projection_name = "joshi.production_snapshot_export";
        let export_projection_version = snapshot.producer_build().as_str();
        let export_configuration_digest = operation_digest(&(
            "joshi.production_snapshot_export.configuration.v2",
            snapshot.producer_build().as_str(),
        ))?;
        let export_schema_digest = operation_digest(
            &snapshot
                .tables()
                .iter()
                .map(|table| (table.schema_id().as_str(), table.schema_digest().as_str()))
                .collect::<Vec<_>>(),
        )?;
        let validation_bytes = serde_json::to_vec(&(
            "joshi.store.production_export_validation.v2",
            snapshot.export_request_id().as_str(),
            validation_id.as_str(),
            snapshot.snapshot_id().as_str(),
            snapshot.manifest_digest().as_str(),
            snapshot.rust_validation().receipt_digest().as_str(),
            snapshot.python_validation().receipt_digest().as_str(),
            truth_fingerprint.as_str(),
        ))?;
        let validation_digest = bytes_digest(&validation_bytes)?;
        let table_closure = snapshot
            .tables()
            .iter()
            .zip(&prepared_parts)
            .map(|(table, prepared)| {
                (
                    table.export_manifest_id().as_str(),
                    table.name().as_str(),
                    table.schema_id().as_str(),
                    table.schema_digest().as_str(),
                    table.physical_digest().as_str(),
                    table.logical_digest().as_str(),
                    prepared.relative_path.to_string_lossy().into_owned(),
                    table.byte_length(),
                    table.row_count(),
                    table.ordinal(),
                )
            })
            .collect::<Vec<_>>();
        let operation = operation_digest(&(
            "joshi.store.production_export_commit.v2",
            snapshot.export_request_id().as_str(),
            validation_id.as_str(),
            snapshot.snapshot_id().as_str(),
            snapshot.manifest_digest().as_str(),
            snapshot.publication_ids(),
            truth_fingerprint.as_str(),
            validation_digest.as_str(),
            export_configuration_digest.as_str(),
            export_schema_digest.as_str(),
            table_closure,
        ))?;
        let occurrence_id = snapshot.export_request_id().clone();
        let structural =
            self.commit_operational(context, "export", &occurrence_id, &operation, |tx, seq| {
                tx.execute(
                    "INSERT OR IGNORE INTO projection_version
                     (projection_name,projection_version,producer_build,configuration_sha256,
                      schema_sha256,deterministic) VALUES (?1,?2,?3,?4,?5,1)",
                    params![
                        export_projection_name,
                        export_projection_version,
                        snapshot.producer_build().as_str(),
                        raw_digest(export_configuration_digest.as_str(), "export configuration",)?,
                        raw_digest(export_schema_digest.as_str(), "export schema")?,
                    ],
                )?;
                let exact_projection: bool = tx.query_row(
                    "SELECT producer_build=?3 AND configuration_sha256=?4
                            AND schema_sha256=?5 AND deterministic=1
                     FROM projection_version WHERE projection_name=?1 AND projection_version=?2",
                    params![
                        export_projection_name,
                        export_projection_version,
                        snapshot.producer_build().as_str(),
                        raw_digest(export_configuration_digest.as_str(), "export configuration",)?,
                        raw_digest(export_schema_digest.as_str(), "export schema")?,
                    ],
                    |row| row.get(0),
                )?;
                if !exact_projection {
                    return Err(StoreError::IdentityConflict {
                        kind: "production export projection",
                        identity: format!("{export_projection_name}:{export_projection_version}"),
                    });
                }
                tx.execute(
                    "INSERT INTO export_snapshot
                     (export_snapshot_id,contract,schema_version,manifest_relative_path,
                      manifest_sha256,manifest_byte_length,from_commit_seq,through_commit_seq,
                      scene_id,created_commit_seq)
                     VALUES (?1,'joshi.analysis.snapshot/v2',2,?2,?3,?4,?5,?6,NULL,?7)",
                    params![
                        snapshot.snapshot_id().as_str(),
                        manifest.relative_path.to_string_lossy(),
                        raw_digest(snapshot.manifest_digest().as_str(), "snapshot manifest")?,
                        sqlite_u64(manifest.byte_length, "snapshot manifest length")?,
                        sqlite_u64(from_commit.get(), "snapshot from commit")?,
                        sqlite_u64(through_commit.get(), "snapshot through commit")?,
                        seq,
                    ],
                )?;
                for (table, prepared) in snapshot.tables().iter().zip(&prepared_parts) {
                    tx.execute(
                        "INSERT INTO export_manifest
                         (export_manifest_id,family,family_schema_version,generation,part_ordinal,
                          projection_name,projection_version,from_commit_seq,through_commit_seq,
                          created_commit_seq,input_manifest_sha256,relative_path,file_sha256,
                          byte_length,row_count,format,compression,writer_version,schema_sha256,
                          retention_class)
                         VALUES (?1,?2,1,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,
                                 'parquet','zstd',?15,?16,'public_source')",
                        params![
                            table.export_manifest_id().as_str(),
                            table.name().as_str(),
                            seq,
                            sqlite_u64(table.ordinal(), "table ordinal")?,
                            export_projection_name,
                            export_projection_version,
                            sqlite_u64(table.from_commit_seq().get(), "table from commit")?,
                            sqlite_u64(table.through_commit_seq().get(), "table through commit")?,
                            seq,
                            raw_digest(snapshot.snapshot_id().as_str(), "snapshot identity")?,
                            prepared.relative_path.to_string_lossy(),
                            raw_digest(table.physical_digest().as_str(), "table physical")?,
                            sqlite_u64(table.byte_length(), "table byte length")?,
                            sqlite_u64(table.row_count(), "table row count")?,
                            snapshot.producer_build().as_str(),
                            raw_digest(table.schema_digest().as_str(), "table schema")?,
                        ],
                    )?;
                    tx.execute(
                        "INSERT INTO export_snapshot_part
                         (export_snapshot_id,export_manifest_id) VALUES (?1,?2)",
                        params![
                            snapshot.snapshot_id().as_str(),
                            table.export_manifest_id().as_str()
                        ],
                    )?;
                }
                tx.execute(
                    "INSERT INTO export_validation
                     (validation_id,export_snapshot_id,manifest_sha256,rust_validation_sha256,
                      python_validation_sha256,validation_sha256,validation_bytes,
                      validation_byte_length,validator_build,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
                    params![
                        validation_id.as_str(),
                        snapshot.snapshot_id().as_str(),
                        raw_digest(snapshot.manifest_digest().as_str(), "snapshot manifest")?,
                        raw_digest(
                            snapshot.rust_validation().receipt_digest().as_str(),
                            "Rust validation",
                        )?,
                        raw_digest(
                            snapshot.python_validation().receipt_digest().as_str(),
                            "Python validation",
                        )?,
                        raw_digest(validation_digest.as_str(), "export validation")?,
                        validation_bytes,
                        sqlite_usize(validation_bytes.len(), "validation byte length")?,
                        snapshot.producer_build().as_str(),
                        seq,
                    ],
                )?;
                tx.execute(
                    "INSERT INTO production_export_request_v2
                     (export_request_id,validation_id,snapshot_id,snapshot_manifest_sha256,
                      truth_fingerprint_sha256,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7)",
                    params![
                        snapshot.export_request_id().as_str(),
                        validation_id.as_str(),
                        snapshot.snapshot_id().as_str(),
                        raw_digest(snapshot.manifest_digest().as_str(), "snapshot manifest")?,
                        raw_digest(truth_fingerprint.as_str(), "truth fingerprint")?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                for (ordinal, publication_id) in snapshot.publication_ids().iter().enumerate() {
                    tx.execute(
                        "INSERT INTO production_export_publication_v2
                         (export_request_id,ordinal,publication_id) VALUES (?1,?2,?3)",
                        params![
                            snapshot.export_request_id().as_str(),
                            sqlite_usize(ordinal, "publication ordinal")?,
                            publication_id.as_str(),
                        ],
                    )?;
                }
                Ok(())
            })?;
        Ok(ProductionExportCommitReceipt {
            catalog_id: structural.catalog_id.clone(),
            catalog_schema: structural.catalog_schema.clone(),
            batch_id: structural.batch_id.clone(),
            export_request_id: snapshot.export_request_id().clone(),
            validation_id: validation_id.clone(),
            snapshot_id: snapshot.snapshot_id().clone(),
            manifest_digest: snapshot.manifest_digest().clone(),
            rust_validation_digest: snapshot.rust_validation().receipt_digest().clone(),
            python_validation_digest: snapshot.python_validation().receipt_digest().clone(),
            validation_digest,
            truth_fingerprint,
            commit_seq: structural.commit_seq,
            status: structural.status,
        })
    }

    /// Registers one independently validated derived artifact under its reserved import and
    /// analysis-run occurrences, then exposes restart-safe exact part readback.
    ///
    /// # Errors
    ///
    /// Returns an error for a substituted export occurrence/snapshot, later-known input, changed
    /// immutable part, identity conflict, or failed durable commit.
    #[allow(clippy::too_many_lines)]
    pub fn commit_analysis_artifact_v2(
        &mut self,
        import_id: &StableString,
        expected_export_request_id: &StableString,
        artifact: &ValidatedDerivedArtifactV2,
        context: &OperationalCommitContext,
    ) -> Result<AnalysisArtifactCommitReceipt> {
        self.require_writer()?;
        let export: Option<(String, String, String, i64)> = self
            .connection
            .query_row(
                "SELECT e.snapshot_id,e.snapshot_manifest_sha256,
                        e.truth_fingerprint_sha256,s.through_commit_seq
                 FROM production_export_request_v2 e
                 JOIN export_snapshot s ON s.export_snapshot_id=e.snapshot_id
                 WHERE e.export_request_id=?1",
                [expected_export_request_id.as_str()],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?;
        let Some((snapshot_id, snapshot_manifest, truth_fingerprint, snapshot_cutoff)) = export
        else {
            return Err(StoreError::MissingIdentity {
                kind: "production export request",
                identity: expected_export_request_id.to_string(),
            });
        };
        if snapshot_id != artifact.snapshot_id().as_str()
            || snapshot_manifest
                != raw_digest(
                    artifact.snapshot_manifest_digest().as_str(),
                    "input snapshot manifest",
                )?
            || as_u64(snapshot_cutoff, "snapshot cutoff")? != artifact.catalog_commit_seq().get()
            || artifact.maximum_input_available_at() > artifact.fit_cutoff()
        {
            return Err(StoreError::InvalidBatch(
                "derived artifact does not close the exact validated export snapshot".into(),
            ));
        }
        let mut statement = self.connection.prepare(
            "SELECT publication_id FROM production_export_publication_v2
             WHERE export_request_id=?1 ORDER BY ordinal",
        )?;
        let durable_publications = statement
            .query_map([expected_export_request_id.as_str()], |row| {
                row.get::<_, String>(0)
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        if durable_publications
            .iter()
            .map(String::as_str)
            .ne(artifact.publication_ids().iter().map(StableString::as_str))
        {
            return Err(StoreError::InvalidBatch(
                "derived artifact publication closure differs from its validated snapshot".into(),
            ));
        }
        drop(statement);
        let part_name = artifact
            .part()
            .path()
            .file_name()
            .ok_or_else(|| StoreError::InvalidBatch("artifact part has no file name".into()))?;
        let relative_path = PathBuf::from("analysis-v2")
            .join(import_id.as_str())
            .join(part_name);
        let part_bytes = fs::read(artifact.part().path())
            .map_err(|source| StoreError::io(artifact.part().path(), source))?;
        let prepared = self.prepare_export(&relative_path, &part_bytes)?;
        if &prepared.digest != artifact.part().physical_digest()
            || prepared.byte_length != artifact.part().byte_length()
        {
            return Err(StoreError::InvalidBatch(
                "prepared derived artifact part differs from admitted bytes".into(),
            ));
        }
        let support_digest = operation_digest(&artifact.support())?;
        let coverage_digest =
            operation_digest(&(artifact.coverage_window_ids(), artifact.coverage_gap_ids()))?;
        let uncertainty_digest = operation_digest(&(
            artifact.uncertainty().0.as_str(),
            artifact.uncertainty().1.as_str(),
        ))?;
        let truth_fingerprint = qualified_raw_digest(&truth_fingerprint, "truth fingerprint")?;
        let operation = operation_digest(&(
            "joshi.store.analysis_artifact_commit.v2",
            import_id.as_str(),
            expected_export_request_id.as_str(),
            artifact.analysis_run_id().as_str(),
            artifact.artifact_id().as_str(),
            artifact.manifest_digest().as_str(),
            artifact.snapshot_id().as_str(),
            artifact.snapshot_manifest_digest().as_str(),
            artifact.catalog_commit_seq().get(),
            artifact.claim_scope().as_str(),
            artifact.part().physical_digest().as_str(),
            artifact.part().logical_digest().as_str(),
            truth_fingerprint.as_str(),
        ))?;
        let structural =
            self.commit_operational(context, "projection", import_id, &operation, |tx, seq| {
                tx.execute(
                    "INSERT INTO derived_analysis_artifact
                     (import_id,artifact_id,artifact_contract,artifact_schema_version,
                      artifact_sha256,artifact_byte_length,manifest_sha256,manifest_bytes,
                      manifest_byte_length,input_snapshot_id,input_snapshot_sha256,
                      fit_through_commit_seq,maximum_input_available_wall_us,support_sha256,
                      coverage_sha256,uncertainty_sha256,claim_scope,truth_fingerprint_before,
                      truth_fingerprint_after,authority,created_commit_seq)
                     VALUES (?1,?2,?3,2,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,
                             ?16,?17,?17,?18,?19)",
                    params![
                        import_id.as_str(),
                        artifact.artifact_id().as_str(),
                        DERIVED_ARTIFACT_CONTRACT_V2,
                        raw_digest(artifact.artifact_id().as_str(), "artifact identity")?,
                        sqlite_u64(artifact.part().byte_length(), "artifact byte length")?,
                        raw_digest(artifact.manifest_digest().as_str(), "artifact manifest")?,
                        artifact.manifest_bytes(),
                        sqlite_usize(artifact.manifest_bytes().len(), "artifact manifest length")?,
                        artifact.snapshot_id().as_str(),
                        raw_digest(
                            artifact.snapshot_manifest_digest().as_str(),
                            "input snapshot manifest",
                        )?,
                        sqlite_u64(artifact.catalog_commit_seq().get(), "artifact input cutoff")?,
                        timestamp_us(
                            artifact.maximum_input_available_at(),
                            "artifact maximum input availability",
                        )?,
                        raw_digest(support_digest.as_str(), "artifact support")?,
                        raw_digest(coverage_digest.as_str(), "artifact coverage")?,
                        raw_digest(uncertainty_digest.as_str(), "artifact uncertainty")?,
                        DISPLAY_CLASS,
                        raw_digest(truth_fingerprint.as_str(), "truth fingerprint")?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                tx.execute(
                    "INSERT INTO analysis_artifact_import_v2
                     (import_id,export_request_id,analysis_run_id,snapshot_id,artifact_id,
                      claim_scope,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
                    params![
                        import_id.as_str(),
                        expected_export_request_id.as_str(),
                        artifact.analysis_run_id().as_str(),
                        artifact.snapshot_id().as_str(),
                        artifact.artifact_id().as_str(),
                        artifact.claim_scope().as_str(),
                        AUTHORITY,
                        seq,
                    ],
                )?;
                tx.execute(
                    "INSERT INTO derived_analysis_artifact_part_v2
                     (import_id,part_ordinal,relative_path,schema_id,schema_sha256,file_sha256,
                      logical_sha256,byte_length,row_count,retention_class)
                     VALUES (?1,0,?2,?3,?4,?5,?6,?7,?8,
                             'analysis_derived_public_integrity')",
                    params![
                        import_id.as_str(),
                        prepared.relative_path.to_string_lossy(),
                        artifact.part().schema_id().as_str(),
                        raw_digest(artifact.part().schema_digest().as_str(), "artifact schema")?,
                        raw_digest(artifact.part().physical_digest().as_str(), "artifact part")?,
                        raw_digest(
                            artifact.part().logical_digest().as_str(),
                            "artifact logical"
                        )?,
                        sqlite_u64(artifact.part().byte_length(), "artifact part byte length")?,
                        sqlite_u64(artifact.part().row_count(), "artifact part row count")?,
                    ],
                )?;
                Ok(())
            })?;
        Ok(AnalysisArtifactCommitReceipt {
            catalog_id: structural.catalog_id.clone(),
            catalog_schema: structural.catalog_schema.clone(),
            batch_id: structural.batch_id.clone(),
            import_id: import_id.clone(),
            export_request_id: expected_export_request_id.clone(),
            analysis_run_id: artifact.analysis_run_id().clone(),
            artifact_id: artifact.artifact_id().clone(),
            artifact_contract: stable_string(
                DERIVED_ARTIFACT_CONTRACT_V2.to_owned(),
                "artifact contract",
            )?,
            artifact_digest: artifact.artifact_id().clone(),
            manifest_digest: artifact.manifest_digest().clone(),
            snapshot_id: artifact.snapshot_id().clone(),
            snapshot_manifest_digest: artifact.snapshot_manifest_digest().clone(),
            claim_scope: artifact.claim_scope().clone(),
            truth_fingerprint,
            commit_seq: structural.commit_seq,
            status: structural.status,
        })
    }

    /// Loads and re-verifies the immutable part registered for one exact derived import.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed stored identities/digests or changed/missing part bytes.
    pub fn load_analysis_artifact_part_v2(
        &self,
        import_id: &StableString,
    ) -> Result<Option<StoredAnalysisArtifactPart>> {
        type ArtifactPartRow = (
            String,
            String,
            String,
            String,
            String,
            String,
            String,
            i64,
            i64,
        );
        let row: Option<ArtifactPartRow> = self
            .connection
            .query_row(
                "SELECT i.analysis_run_id,i.artifact_id,p.relative_path,p.schema_id,
                        p.schema_sha256,p.file_sha256,p.logical_sha256,p.byte_length,p.row_count
                 FROM analysis_artifact_import_v2 i
                 JOIN derived_analysis_artifact_part_v2 p ON p.import_id=i.import_id
                 WHERE i.import_id=?1 AND p.part_ordinal=0",
                [import_id.as_str()],
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
                    ))
                },
            )
            .optional()?;
        let Some((
            analysis_run_id,
            artifact_id,
            path,
            schema_id,
            schema,
            physical,
            logical,
            bytes,
            rows,
        )) = row
        else {
            return Ok(None);
        };
        let byte_length = as_u64(bytes, "artifact part byte length")?;
        verify_export_file(&self.config.export_root.join(&path), &physical, byte_length)?;
        Ok(Some(StoredAnalysisArtifactPart {
            import_id: import_id.clone(),
            analysis_run_id: stable_string(analysis_run_id, "analysis run ID")?,
            artifact_id: qualified_raw_digest(&artifact_id, "artifact ID")?,
            relative_path: PathBuf::from(path),
            schema_id: stable_string(schema_id, "artifact schema ID")?,
            schema_digest: qualified_raw_digest(&schema, "artifact schema")?,
            physical_digest: qualified_raw_digest(&physical, "artifact part")?,
            logical_digest: qualified_raw_digest(&logical, "artifact logical")?,
            byte_length,
            row_count: as_u64(rows, "artifact row count")?,
        }))
    }

    fn commit_operational<F>(
        &mut self,
        context: &OperationalCommitContext,
        commit_class: &'static str,
        occurrence_id: &StableString,
        digest: &ValueDigest,
        insert: F,
    ) -> Result<OperationalCommitReceipt>
    where
        F: FnOnce(&Transaction<'_>, i64) -> Result<()>,
    {
        self.require_writer()?;
        let raw = raw_digest(digest.as_str(), "operational commit")?;
        if let Some((seq, existing)) = self
            .connection
            .query_row(
                "SELECT commit_seq,commit_digest FROM ingest_commit WHERE commit_id=?1",
                [context.batch_id.as_str()],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?
        {
            if existing != raw {
                return Err(StoreError::IdentityConflict {
                    kind: "operational batch",
                    identity: context.batch_id.to_string(),
                });
            }
            return self.operational_receipt(
                context,
                occurrence_id,
                CommitSeq::new(as_u64(seq, "commit_seq")?),
                digest.clone(),
                IdempotencyStatus::Idempotent,
            );
        }
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
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
            params![
                context.batch_id.as_str(),
                commit_class,
                timestamp_us(context.committed_at, "operational committed_at")?,
                context.writer_clock_id.as_str(),
                context.committed_mono_ns.to_string(),
                context.writer_build.as_str(),
                prior,
                raw,
            ],
        )?;
        let seq = tx.last_insert_rowid();
        insert(&tx, seq)?;
        tx.commit()?;
        self.operational_receipt(
            context,
            occurrence_id,
            CommitSeq::new(as_u64(seq, "commit_seq")?),
            digest.clone(),
            IdempotencyStatus::Accepted,
        )
    }

    fn operational_receipt(
        &self,
        context: &OperationalCommitContext,
        occurrence_id: &StableString,
        commit_seq: CommitSeq,
        operation_digest: ValueDigest,
        status: IdempotencyStatus,
    ) -> Result<OperationalCommitReceipt> {
        Ok(OperationalCommitReceipt {
            catalog_id: self.config.catalog_id.clone(),
            catalog_schema: self.catalog_schema_id()?,
            batch_id: context.batch_id.clone(),
            occurrence_id: occurrence_id.clone(),
            commit_seq,
            operation_digest,
            status,
        })
    }
}

fn operation_digest(value: &impl Serialize) -> Result<ValueDigest> {
    let bytes = serde_json::to_vec(value)?;
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}

fn bytes_digest(bytes: &[u8]) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}

fn qualified_raw_digest(value: &str, kind: &'static str) -> Result<ValueDigest> {
    let qualified = if value.starts_with("sha256:") {
        value.to_owned()
    } else {
        format!("sha256:{value}")
    };
    ValueDigest::new(qualified).map_err(|_| StoreError::InvalidDigest {
        kind,
        value: value.to_owned(),
    })
}

fn stable_string(value: String, kind: &'static str) -> Result<StableString> {
    StableString::new(value)
        .map_err(|error| StoreError::InvalidBatch(format!("stored {kind} is invalid: {error}")))
}

fn verify_export_file(path: &std::path::Path, raw_sha256: &str, length: u64) -> Result<()> {
    let bytes = fs::read(path).map_err(|source| StoreError::io(path, source))?;
    let actual_length = u64::try_from(bytes.len()).map_err(|_| StoreError::IntegerRange {
        field: "artifact part byte length",
        value: bytes.len().to_string(),
    })?;
    let actual = format!("{:x}", Sha256::digest(&bytes));
    if actual_length == length && actual == raw_sha256 {
        Ok(())
    } else {
        Err(StoreError::ArtifactVerification {
            path: path.to_owned(),
            detail: format!("expected {raw_sha256}/{length}, computed {actual}/{actual_length}"),
        })
    }
}

fn require_exact_bytes(digest: &ValueDigest, bytes: &[u8], kind: &'static str) -> Result<()> {
    if bytes.is_empty() || bytes.len() > MAX_ARTIFACT_BYTES {
        return Err(StoreError::InvalidBatch(format!(
            "{kind} bytes are empty or exceed {MAX_ARTIFACT_BYTES}"
        )));
    }
    let actual = format!("sha256:{:x}", Sha256::digest(bytes));
    if digest.as_str() == actual {
        Ok(())
    } else {
        Err(StoreError::InvalidDigest {
            kind,
            value: format!("expected {digest}, computed {actual}"),
        })
    }
}

fn raw_digest<'a>(value: &'a str, kind: &'static str) -> Result<&'a str> {
    let Some(raw) = value.strip_prefix("sha256:") else {
        return Err(StoreError::InvalidDigest {
            kind,
            value: value.to_owned(),
        });
    };
    if raw.len() == 64
        && raw
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        Ok(raw)
    } else {
        Err(StoreError::InvalidDigest {
            kind,
            value: value.to_owned(),
        })
    }
}

fn timestamp_us(value: UtcTimestamp, field: &'static str) -> Result<i64> {
    let nanos = value.as_datetime().unix_timestamp_nanos();
    if nanos % 1_000 != 0 {
        return Err(StoreError::TimestampRange { field });
    }
    let micros = nanos / 1_000;
    if micros <= 0 {
        return Err(StoreError::TimestampRange { field });
    }
    micros
        .try_into()
        .map_err(|_| StoreError::TimestampRange { field })
}

fn timestamp_from_us(value: i64, field: &'static str) -> Result<UtcTimestamp> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or(StoreError::TimestampRange { field })?;
    let datetime = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|_| StoreError::TimestampRange { field })?;
    UtcTimestamp::new(datetime).map_err(|_| StoreError::TimestampRange { field })
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{StoreConfig, StoreMode};
    use joshi_export::{
        OperationalExportRequestV2, OperationalPublicationV2, ProjectionPublicationInputV2,
        PythonValidatorV2, export_operational_snapshot_v2,
    };
    use std::{path::Path, time::Duration};

    fn stable(value: &str) -> StableString {
        StableString::new(value).expect("test stable string")
    }

    fn digest(value: &str) -> ValueDigest {
        ValueDigest::new(value).expect("test digest")
    }

    fn workspace() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .expect("workspace")
            .to_owned()
    }

    fn config(root: &Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: stable("catalog-publication-test"),
            max_observations_per_batch: 16,
            max_raw_bytes_per_batch: 1024 * 1024,
        }
    }

    fn validated_snapshot(destination: PathBuf) -> ValidatedProductionSnapshotV2 {
        export_operational_snapshot_v2(&OperationalExportRequestV2 {
            catalog_snapshot_path: workspace()
                .join("fixtures/export/operational_catalog_v8.sqlite"),
            catalog_id: stable("catalog-publication-test"),
            catalog_schema: stable("joshi.sqlite.v8"),
            from_commit_seq: CommitSeq::new(1),
            through_commit_seq: CommitSeq::new(13),
            export_request_id: stable("export-production-fixture-001"),
            producer_build: stable("joshi-export-operational-fixture-v2"),
            created_at: "2026-08-17T12:00:00.000000Z"
                .parse::<UtcTimestamp>()
                .expect("timestamp"),
            producer_projection_publication_id: stable("publication-001"),
            coverage_window_ids: vec![stable("cov_export_wall")],
            publications: vec![OperationalPublicationV2::Projection(
                ProjectionPublicationInputV2 {
                    publication_id: stable("publication-001"),
                    publication_contract: stable("joshi.projection_publication"),
                    publication_digest: digest(
                        "sha256:1524b025b3e615358a53ac410600d0c386b6f18a93d9c1e19708ab034f87cb8d",
                    ),
                    publication_bytes_digest: digest(
                        "sha256:3b2019584418c9a521e6bb4434733b70916d30a86a7a1f52621ce7a7e429a8b6",
                    ),
                    projection_id: stable("projection-001"),
                    projection_name: stable("joshi.read_projection"),
                    projection_version: stable("joshi.projection.v1"),
                    result_digest: digest(
                        "sha256:d7c6cbaf0736069a895d126fabeb94ec204bc22285611ba5f5d97098ee34a69b",
                    ),
                    artifact_digest: digest(
                        "sha256:54a044671521c467a312dd1b66853cda14afd8bf3f430fcc2c00919a91e7f583",
                    ),
                    input_closure_digest: digest(
                        "sha256:b57ebaf6f3c0edfbc06f63241a0ec52d9cd6330beedfba7cf8bb545b3b949d9b",
                    ),
                    through_commit_seq: CommitSeq::new(10),
                    published_commit_seq: CommitSeq::new(11),
                },
            )],
            destination,
            python_validator: PythonValidatorV2 {
                program: PathBuf::from("uv"),
                analysis_directory: workspace().join("analysis"),
            },
            g0_import_artifact: None,
        })
        .expect("validated production snapshot")
    }

    #[test]
    fn production_export_occurrence_maps_to_content_and_retries_exactly() {
        let temporary = tempfile::tempdir().expect("temporary root");
        let snapshot = validated_snapshot(temporary.path().join("validated-snapshot"));
        fs::copy(
            workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
            temporary.path().join("catalog.sqlite"),
        )
        .expect("copy catalog");
        let mut store = SqliteStore::open(config(temporary.path()), StoreMode::SingleWriter)
            .expect("open V8 store");
        let context = OperationalCommitContext::new(
            stable("export-store-batch-001"),
            "2026-08-17T12:01:00.000000Z"
                .parse()
                .expect("commit timestamp"),
            stable("store-test-clock"),
            1,
            stable("store-test-build"),
        );
        let validation_id = stable("export-validation-001");
        let accepted = store
            .commit_production_export_snapshot_v2(&validation_id, &snapshot, &context)
            .expect("production export commit");
        assert_eq!(accepted.status(), IdempotencyStatus::Accepted);
        assert_eq!(accepted.commit_seq(), CommitSeq::new(14));
        assert_eq!(accepted.export_request_id(), snapshot.export_request_id());
        assert_eq!(
            accepted.truth_fingerprint(),
            &operation_digest(snapshot.truth_fingerprint()).expect("truth fingerprint")
        );
        let retry = store
            .commit_production_export_snapshot_v2(&validation_id, &snapshot, &context)
            .expect("exact production export retry");
        assert_eq!(retry.status(), IdempotencyStatus::Idempotent);
        assert_eq!(retry.commit_seq(), accepted.commit_seq());
        let closure: (i64, i64, i64) = store
            .connection
            .query_row(
                "SELECT
                    (SELECT COUNT(*) FROM production_export_request_v2),
                    (SELECT COUNT(*) FROM production_export_publication_v2),
                    (SELECT COUNT(*) FROM export_snapshot_part
                     WHERE export_snapshot_id=?1)",
                [snapshot.snapshot_id().as_str()],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .expect("read durable closure");
        assert_eq!(closure, (1, 1, 14));
        joshi_admission_test_receipt(&accepted);
    }

    #[test]
    fn wave5_baseline_snapshot_commits_at_v9_and_refuses_after_v10() {
        let temporary = tempfile::tempdir().expect("temporary root");
        fs::copy(
            workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
            temporary.path().join("catalog.sqlite"),
        )
        .expect("copy V8 catalog");
        let snapshot = validated_snapshot(temporary.path().join("validated-baseline-snapshot"));
        let mut store = SqliteStore::open(config(temporary.path()), StoreMode::SingleWriter)
            .expect("open baseline store");
        let baseline = store
            .migrate_wave5_baseline_v9(
                "2026-08-18T11:59:00.000000Z"
                    .parse()
                    .expect("migration timestamp"),
            )
            .expect("advance fixture to V9");
        assert_eq!(baseline.current, 9);
        let context = OperationalCommitContext::new(
            stable("export-store-baseline-001"),
            "2026-08-18T12:01:00.000000Z"
                .parse()
                .expect("commit timestamp"),
            stable("store-test-clock"),
            1,
            stable("store-test-build"),
        );
        let validation_id = stable("export-validation-baseline-001");
        let accepted = store
            .commit_wave5_baseline_export_snapshot_v2(&validation_id, &snapshot, &context)
            .expect("commit validated V8 snapshot under V9 baseline");
        assert_eq!(accepted.status(), IdempotencyStatus::Accepted);
        assert_eq!(accepted.catalog_schema().as_str(), "joshi.sqlite.v9");

        let current = store
            .migrate(
                "2026-08-18T12:02:00.000000Z"
                    .parse()
                    .expect("V10 timestamp"),
            )
            .expect("advance baseline to V10");
        assert_eq!(current.current, 10);
        assert!(
            store
                .commit_wave5_baseline_export_snapshot_v2(&validation_id, &snapshot, &context)
                .is_err(),
            "V10 cannot use the V9-only baseline commit waist"
        );
    }

    #[test]
    #[allow(clippy::too_many_lines)]
    fn derived_import_preserves_occurrences_and_reverifies_part_after_restart() {
        let temporary = tempfile::tempdir().expect("temporary root");
        fs::copy(
            workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
            temporary.path().join("catalog.sqlite"),
        )
        .expect("copy catalog");
        let artifact = joshi_artifact_admission::validate_derived_artifact_v2(
            &workspace().join(
                "fixtures/artifact/derived-759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55",
            ),
        )
        .expect("validated derived artifact");
        let mut store = SqliteStore::open(config(temporary.path()), StoreMode::SingleWriter)
            .expect("open V8 store");
        let snapshot_manifest = raw_digest(
            artifact.snapshot_manifest_digest().as_str(),
            "test snapshot manifest",
        )
        .expect("raw snapshot manifest digest");
        store
            .connection
            .execute(
                "INSERT INTO ingest_commit
                 (commit_id,commit_class,committed_wall_us,writer_clock_id,committed_mono_ns,
                  writer_build,prior_commit_digest,commit_digest)
                 VALUES ('seed-production-export','export',1786971600000000,'test-clock','1',
                         'test-build',(SELECT commit_digest FROM ingest_commit
                         ORDER BY commit_seq DESC LIMIT 1),?1)",
                ["abababababababababababababababababababababababababababababababab"],
            )
            .expect("seed export commit");
        let seed_seq = store.connection.last_insert_rowid();
        store
            .connection
            .execute(
                "INSERT INTO export_snapshot
             (export_snapshot_id,contract,schema_version,manifest_relative_path,manifest_sha256,
              manifest_byte_length,from_commit_seq,through_commit_seq,scene_id,created_commit_seq)
             VALUES (?1,'joshi.analysis.snapshot/v2',2,'seed/manifest.json',?2,1,1,13,NULL,?3)",
                params![artifact.snapshot_id().as_str(), snapshot_manifest, seed_seq],
            )
            .expect("seed export snapshot");
        store
            .connection
            .execute(
                "INSERT INTO export_validation
             (validation_id,export_snapshot_id,manifest_sha256,rust_validation_sha256,
              python_validation_sha256,validation_sha256,validation_bytes,
              validation_byte_length,validator_build,created_commit_seq)
             VALUES ('seed-validation',?1,?2,?3,?3,?3,x'7b7d',2,'seed-validator',?4)",
                params![
                    artifact.snapshot_id().as_str(),
                    snapshot_manifest,
                    "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
                    seed_seq,
                ],
            )
            .expect("seed export validation");
        store
            .connection
            .execute(
                "INSERT INTO production_export_request_v2
             (export_request_id,validation_id,snapshot_id,snapshot_manifest_sha256,
              truth_fingerprint_sha256,authority,created_commit_seq)
             VALUES ('export-production-fixture-001','seed-validation',?1,?2,?3,
                     'read_only_no_execution',?4)",
                params![
                    artifact.snapshot_id().as_str(),
                    snapshot_manifest,
                    "efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef",
                    seed_seq,
                ],
            )
            .expect("seed export occurrence mapping");
        store
            .connection
            .execute(
                "INSERT INTO production_export_publication_v2
             (export_request_id,ordinal,publication_id)
             VALUES ('export-production-fixture-001',0,'publication-001')",
                [],
            )
            .expect("seed publication closure");

        let context = OperationalCommitContext::new(
            stable("artifact-store-batch-001"),
            "2026-08-17T12:02:00.000000Z"
                .parse()
                .expect("commit timestamp"),
            stable("store-test-clock"),
            2,
            stable("store-test-build"),
        );
        let import_id = stable("artifact-import-001");
        let export_request_id = stable("export-production-fixture-001");
        let accepted = store
            .commit_analysis_artifact_v2(&import_id, &export_request_id, &artifact, &context)
            .expect("analysis artifact commit");
        assert_eq!(accepted.status(), IdempotencyStatus::Accepted);
        assert_eq!(accepted.commit_seq(), CommitSeq::new(15));
        assert_eq!(accepted.analysis_run_id(), artifact.analysis_run_id());
        assert_ne!(
            accepted.analysis_run_id().as_str(),
            accepted.artifact_id().as_str()
        );
        let retry = store
            .commit_analysis_artifact_v2(&import_id, &export_request_id, &artifact, &context)
            .expect("exact artifact retry");
        assert_eq!(retry.status(), IdempotencyStatus::Idempotent);
        drop(store);
        let store = SqliteStore::open(config(temporary.path()), StoreMode::SingleWriter)
            .expect("reopen V8 store");
        let loaded = store
            .load_analysis_artifact_part_v2(&import_id)
            .expect("artifact readback")
            .expect("artifact part");
        assert_eq!(&loaded.analysis_run_id, artifact.analysis_run_id());
        assert_eq!(&loaded.physical_digest, artifact.part().physical_digest());
        fs::write(
            store.config.export_root.join(&loaded.relative_path),
            b"changed",
        )
        .expect("corrupt test part");
        assert!(store.load_analysis_artifact_part_v2(&import_id).is_err());
    }

    fn joshi_admission_test_receipt(value: &ProductionExportCommitReceipt) {
        assert_eq!(value.catalog_schema().as_str(), "joshi.sqlite.v8");
        assert_eq!(value.validation_id().as_str(), "export-validation-001");
        assert_ne!(
            value.export_request_id().as_str(),
            value.snapshot_id().as_str()
        );
    }
}
