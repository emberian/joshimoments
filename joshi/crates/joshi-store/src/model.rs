use joshi_domain::{
    AcquisitionId, AssertionId, BatchDigest, ClientSessionId, CommandId, CommitSeq, CoverageId,
    CursorId, OpenVariant, SceneId, SourceId, StableString, UtcTimestamp, ValueDigest, WireU64,
};
use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::PathBuf, time::Duration};

/// Store open mode. Only one `SingleWriter` may exist for a catalog.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StoreMode {
    /// Read/write catalog owner with WAL and FULL durability.
    SingleWriter,
    /// Query-only connection; never applies migrations or writes.
    ReadOnly,
}

/// Filesystem and durability configuration.
#[derive(Clone, Debug)]
pub struct StoreConfig {
    /// Operational `SQLite` catalog path.
    pub catalog_path: PathBuf,
    /// Content-addressed blob root.
    pub blob_root: PathBuf,
    /// Immutable analytical export root.
    pub export_root: PathBuf,
    /// Payloads no larger than this may remain inline when retention permits.
    pub inline_blob_max_bytes: u64,
    /// `SQLite` busy timeout for the one writer and short readers.
    pub busy_timeout: Duration,
    /// Stable local catalog identity included in every durable receipt.
    pub catalog_id: StableString,
    /// Maximum observations accepted atomically.
    pub max_observations_per_batch: usize,
    /// Maximum total raw observation bytes accepted atomically.
    pub max_raw_bytes_per_batch: u64,
}

/// Immutable source-contract registration. It contains fingerprints, never credentials.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SourceRegistration {
    /// Stable source contract identity.
    pub source_id: SourceId,
    /// Source namespace.
    pub namespace: StableString,
    /// Adapter/source contract version.
    pub contract_version: StableString,
    /// Collector build identity.
    pub collector_build: StableString,
    /// Algorithm-qualified digest of non-secret configuration.
    pub configuration_digest: ValueDigest,
}

/// Physical and retention policy for one observation's raw bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationStorage {
    /// SQL-supported retention class.
    pub retention_class: StableString,
    /// Optional exact source content encoding.
    pub content_encoding: Option<StableString>,
    /// Whether policy requires external storage even below the inline threshold.
    pub force_external: bool,
}

/// Durable evidence batch plus physical policies that do not alter evidence semantics.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoreIngestBatch {
    /// One atomic evidence batch.
    pub evidence: DurableIngestBatch,
    /// Storage policy keyed by observation identity string.
    pub observation_storage: BTreeMap<String, ObservationStorage>,
    /// SQL gap severity keyed by gap identity; operational impact is not inferred from cause.
    pub coverage_gap_severity: BTreeMap<String, StableString>,
    /// Wall time at which the writer attempts the durable commit.
    pub committed_at: UtcTimestamp,
    /// Writer/process monotonic domain.
    pub writer_clock_id: StableString,
    /// Canonical unsigned monotonic reading.
    pub committed_mono_ns: u64,
    /// Writer build identity.
    pub writer_build: StableString,
}

/// Whether an idempotency identity advanced durable state.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdempotencyStatus {
    /// New transaction committed.
    Accepted,
    /// Exact batch was already committed.
    Idempotent,
}

/// Receipt returned only after durable commit or exact readback.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DurableReceipt {
    /// Receipt contract discriminator; always `joshi.store.ingest_receipt`.
    pub contract: StableString,
    /// Positive receipt schema version.
    pub schema_version: u64,
    /// Stable local catalog identity, preventing wrong-endpoint acknowledgement.
    pub catalog_id: StableString,
    /// SQL schema identity.
    pub catalog_schema: StableString,
    /// Durable local knowledge order.
    pub commit_seq: CommitSeq,
    /// First durable local knowledge order (equal to `through_commit_seq` for V1).
    pub from_commit_seq: CommitSeq,
    /// Last durable local knowledge order.
    pub through_commit_seq: CommitSeq,
    /// Stable batch idempotency identity.
    pub batch_id: StableString,
    /// Algorithm-qualified canonical batch digest.
    pub batch_digest: BatchDigest,
    /// Digest of logical batch plus normalized storage/privacy/severity policy.
    #[serde(rename = "storeAdmissionDigest")]
    pub admission_digest: ValueDigest,
    /// New commit or exact retry.
    pub status: IdempotencyStatus,
    /// Exact admitted logical and physical closure.
    pub admitted: AdmittedCounts,
    /// Distinct acquisition identities represented by the accepted observations.
    pub acquisition_ids: Vec<AcquisitionId>,
    /// Exact scoped gaps made durable by this transaction.
    pub gap_outcomes: Vec<GapOutcome>,
}

/// Exact admitted closure for one atomic ingest batch.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AdmittedCounts {
    /// Distinct acquisition occurrences.
    pub acquisitions: WireU64,
    /// Distinct raw content blobs.
    pub raw_blobs: WireU64,
    /// Total raw payload bytes before content deduplication.
    pub raw_bytes: WireU64,
    /// Observation occurrences.
    pub observations: WireU64,
    /// Typed source events.
    pub source_events: WireU64,
    /// Assertions.
    pub assertions: WireU64,
    /// Positive coverage windows.
    pub coverage_windows: WireU64,
    /// Coverage gaps.
    pub coverage_gaps: WireU64,
    /// Coverage recoveries.
    pub coverage_recoveries: WireU64,
    /// Evidence-backed cursor advances.
    pub cursor_advances: WireU64,
}

/// Exact gap closure echoed to an ingress client before it may dequeue work.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GapOutcome {
    /// Gap occurrence identity.
    pub gap_id: CoverageId,
    /// Exact affected scope.
    pub scope: CoverageScope,
    /// Last trustworthy boundary.
    pub lower: Boundary,
    /// Upper bound known at detection.
    pub upper: Option<Boundary>,
    /// Durable admission disposition.
    pub outcome: StableString,
}

/// One independently scoped cursor justified at a historical knowledge cutoff.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct JustifiedCursor {
    /// Cursor advancement identity.
    pub cursor_id: CursorId,
    /// Full source/family/subject scope; never collapsed to source-wide state.
    pub scope: CoverageScope,
    /// Open-world cursor family.
    pub cursor_kind: OpenVariant,
    /// Exact opaque cursor value.
    pub cursor_value: StableString,
    /// Knowledge commit at which this advancement became durable.
    pub advanced_through: CommitSeq,
}

/// Replay product represented by a scene.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SceneMode {
    /// Exact stored renderer contract that was shown.
    Witnessed,
    /// Named recomputation using only a historical knowledge cutoff.
    KnowledgeCutoff,
    /// Later reconstruction that may include corrections and outcomes.
    Retrospective,
}

/// Allowlisted provenance for an admitted scene occurrence.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SceneSourceMode {
    /// Deterministic fixture or golden.
    Fixture,
    /// Operator-selected candidate outside an automated feed.
    ManualNomination,
    /// Paired browser companion.
    Companion,
    /// Replacement local Glass application.
    Replacement,
    /// Read-only observatory replay.
    Observatory,
}

impl SceneSourceMode {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Fixture => "fixture",
            Self::ManualNomination => "manual_nomination",
            Self::Companion => "companion",
            Self::Replacement => "replacement",
            Self::Observatory => "observatory",
        }
    }
}

/// Server-owned occurrence metadata absent from the frozen exact Glass view contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorCaptureMetadata {
    /// Monotone scene sequence in the exact client session.
    pub client_scene_seq: u64,
    /// UI build that rendered the exact bytes.
    pub ui_build: StableString,
    /// Allowlisted acquisition/presentation route.
    pub source_mode: SceneSourceMode,
    /// Renderer monotonic clock domain (never synthesized from server wall time).
    pub rendered_clock_id: StableString,
    /// Exact renderer monotonic reading.
    pub rendered_mono_ns: u64,
    /// Optional exact screenshot of actual exposure, retained separately from intended policy.
    pub screenshot_bytes: Option<Vec<u8>>,
}

/// One source or projection delivery watermark in a scene.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SceneWatermarkDraft {
    /// Namespace unique within the scene.
    pub namespace: StableString,
    /// Source contract, when this is a source watermark.
    pub source_id: Option<SourceId>,
    /// Projection name/version, when this is a projection watermark.
    pub projection: Option<(StableString, StableString)>,
    /// Highest commit delivered to the renderer.
    pub delivered_commit_seq: CommitSeq,
    /// Optional exact state digest.
    pub state_digest: Option<ValueDigest>,
}

/// Membership in one explicitly named choice-context set.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChoiceMemberDraft {
    /// `eligible`, `surfaced`, `rendered`, `viewport`, `interacted`, or `compared`.
    pub set_kind: StableString,
    /// Typed subject family.
    pub subject_kind: StableString,
    /// Exact subject identity.
    pub subject_key: StableString,
    /// Source rank when supplied.
    pub source_rank: Option<u64>,
    /// Renderer ordinal when supplied.
    pub rendered_ordinal: Option<u64>,
    /// Assertion supporting the member at the scene cutoff.
    pub evidence_assertion_id: Option<AssertionId>,
}

/// Immutable scene input with exact renderer bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SceneDraft {
    /// Stable scene identity.
    pub scene_id: SceneId,
    /// Replay product.
    pub mode: SceneMode,
    /// Global evidence cutoff used by the rendered view.
    pub knowledge_cutoff: CommitSeq,
    /// Later outcome cutoff for retrospective scenes.
    pub outcome_cutoff: Option<CommitSeq>,
    /// Witnessed scene on which a recomputation is based.
    pub basis_scene_id: Option<SceneId>,
    /// UI client session.
    pub client_session_id: ClientSessionId,
    /// Monotone scene sequence in that client.
    pub client_scene_seq: u64,
    /// UI build identity.
    pub ui_build: StableString,
    /// Render DTO contract.
    pub view_contract: StableString,
    /// Positive contract version.
    pub view_contract_version: u64,
    /// Exact product/source mode.
    pub source_mode: StableString,
    /// Render wall time.
    pub rendered_at: UtcTimestamp,
    /// Browser monotonic clock domain.
    pub client_clock_id: StableString,
    /// Browser monotonic reading.
    pub rendered_mono_ns: u64,
    /// Exact serialized renderer DTO.
    pub view_bytes: Vec<u8>,
    /// Optional exact app-only screenshot bytes.
    pub screenshot_bytes: Option<Vec<u8>>,
    /// Scene delivery watermarks.
    pub watermarks: Vec<SceneWatermarkDraft>,
    /// Explicit choice-context memberships.
    pub choice_members: Vec<ChoiceMemberDraft>,
}

/// Evidence-only semantic command.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CommandDraft {
    /// Stable command identity.
    pub command_id: CommandId,
    /// Optional pre-existing scene when a new scene is not part of the batch.
    pub scene_id: Option<SceneId>,
    /// UI client session.
    pub client_session_id: ClientSessionId,
    /// Monotone command sequence in that client.
    pub client_command_seq: u64,
    /// Idempotency identity supplied by the UI.
    pub idempotency_key: StableString,
    /// Stable semantic command kind.
    pub command_kind: StableString,
    /// Typed subject.
    pub subject_kind: StableString,
    /// Exact subject identity.
    pub subject_key: StableString,
    /// Exact serialized command payload.
    pub payload_bytes: Vec<u8>,
    /// Client issue wall time.
    pub issued_at: UtcTimestamp,
    /// Client monotonic clock domain.
    pub client_clock_id: StableString,
    /// Client monotonic reading.
    pub issued_mono_ns: u64,
    /// Server receipt wall time.
    pub received_at: UtcTimestamp,
}

/// Atomic scene plus command commit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SceneCommandBatch {
    /// Stable transaction identity.
    pub batch_id: StableString,
    /// Optional new scene; command may reference it.
    pub scene: Option<SceneDraft>,
    /// Required evidence-only command.
    pub command: CommandDraft,
    /// Wall time at which the writer attempts the durable commit.
    pub committed_at: UtcTimestamp,
    /// Writer monotonic clock domain.
    pub writer_clock_id: StableString,
    /// Writer monotonic reading.
    pub committed_mono_ns: u64,
    /// Writer build identity.
    pub writer_build: StableString,
}

/// Metadata for one immutable analytical export.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ExportDraft {
    /// Stable export-manifest identity.
    pub export_manifest_id: StableString,
    /// Typed family.
    pub family: StableString,
    /// Positive family schema version.
    pub family_schema_version: u64,
    /// Positive immutable generation.
    pub generation: u64,
    /// Part ordinal.
    pub part_ordinal: u64,
    /// Projection name/version.
    pub projection: (StableString, StableString),
    /// Closed input commit range.
    pub from_commit_seq: CommitSeq,
    /// Inclusive final input commit.
    pub through_commit_seq: CommitSeq,
    /// Input manifest digest.
    pub input_manifest_digest: ValueDigest,
    /// Expected row count.
    pub row_count: u64,
    /// `parquet` in production; `fixture_opaque` only in fixtures.
    pub format: StableString,
    /// Compression profile.
    pub compression: StableString,
    /// Writer/version identity.
    pub writer_version: StableString,
    /// Exact schema digest.
    pub schema_digest: ValueDigest,
    /// Retention class.
    pub retention_class: StableString,
}

/// Parent identity for an immutable analytical snapshot manifest and all of its parts.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ExportSnapshotDraft {
    /// Snapshot/commit idempotency identity.
    pub export_snapshot_id: StableString,
    /// Manifest contract discriminator.
    pub contract: StableString,
    /// Positive manifest schema version.
    pub schema_version: u64,
    /// Closed first input commit.
    pub from_commit_seq: CommitSeq,
    /// Closed last input commit.
    pub through_commit_seq: CommitSeq,
    /// Optional witnessed/retrospective scene binding.
    pub scene_id: Option<SceneId>,
}

/// Rebuildable projection contract required before analytical export registration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProjectionRegistration {
    /// Projection family.
    pub name: StableString,
    /// Immutable projection version.
    pub version: StableString,
    /// Producer build.
    pub producer_build: StableString,
    /// Non-secret configuration digest.
    pub configuration_digest: ValueDigest,
    /// Output schema digest.
    pub schema_digest: ValueDigest,
    /// Whether replay is declared deterministic.
    pub deterministic: bool,
}

/// Durable result for one all-files-plus-manifest analytical export snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportReceipt {
    /// Snapshot identity.
    pub export_snapshot_id: StableString,
    /// Commit containing snapshot and every part registration.
    pub commit_seq: CommitSeq,
    /// New commit or exact retry.
    pub status: IdempotencyStatus,
    /// Algorithm-qualified transaction digest.
    pub digest: ValueDigest,
}

/// One effective assertion branch returned by an as-known query.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EffectiveAssertion {
    /// Assertion identity.
    pub assertion_id: AssertionId,
    /// Semantic key.
    pub semantic_key: StableString,
    /// Knowledge commit.
    pub produced_commit_seq: CommitSeq,
    /// Canonical assertion JSON.
    pub value: serde_json::Value,
    /// Value digest.
    pub value_digest: ValueDigest,
    /// Superseded predecessor, if any.
    pub supersedes_assertion_id: Option<AssertionId>,
}

/// Stored scene descriptor and exact referenced bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredScene {
    /// Scene identity.
    pub scene_id: SceneId,
    /// Replay mode.
    pub mode: SceneMode,
    /// Historical knowledge cutoff.
    pub knowledge_cutoff: CommitSeq,
    /// Optional retrospective outcome cutoff.
    pub outcome_cutoff: Option<CommitSeq>,
    /// Exact renderer DTO bytes.
    pub view_bytes: Vec<u8>,
    /// Optional screenshot bytes.
    pub screenshot_bytes: Option<Vec<u8>>,
}

/// Durable result of an evidence-only semantic command commit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CommandReceipt {
    /// Stable scene/command transaction identity.
    pub batch_id: StableString,
    /// Evidence-only command identity.
    pub command_id: CommandId,
    /// Commit containing the scene and command.
    pub commit_seq: CommitSeq,
    /// New commit or exact retry.
    pub status: IdempotencyStatus,
    /// Algorithm-qualified canonical transaction digest.
    pub digest: ValueDigest,
}

/// Verification depth.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VerifyDepth {
    /// Foreign keys, quick check, and recent reference checks.
    Quick,
    /// Full integrity and every referenced external artifact hash.
    Full,
}

/// Store verification result.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct VerificationReport {
    /// `SQLite` integrity result.
    pub integrity: String,
    /// Foreign-key defect count.
    pub foreign_key_defects: u64,
    /// External artifacts verified.
    pub external_artifacts_checked: u64,
    /// Highest catalog commit.
    pub max_commit_seq: CommitSeq,
}

/// Online-backup result and immutable artifact closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct BackupManifest {
    /// Destination `SQLite` snapshot.
    pub catalog_path: PathBuf,
    /// Snapshot file digest.
    pub catalog_digest: ValueDigest,
    /// Highest included commit.
    pub max_commit_seq: CommitSeq,
    /// Referenced external blobs as relative path and digest pairs.
    pub referenced_blobs: Vec<(PathBuf, ValueDigest)>,
    /// Referenced immutable exports as relative path and digest pairs.
    pub referenced_exports: Vec<(PathBuf, ValueDigest)>,
}
