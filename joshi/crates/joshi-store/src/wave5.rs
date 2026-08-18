//! Wave 5 store-owned authority joins.
//!
//! Every public writer in this module accepts exact canonical bytes and constructs its semantic
//! capability privately, after recomputing byte closures and resolving all prior catalog rows.
//! No caller-supplied Rust struct is accepted as proof.  All records retain the literal
//! `read_only_no_execution` ceiling.

#![allow(clippy::too_many_lines)]

use crate::{
    BlobStore, IdempotencyStatus, ObservationStorage, Result, SqliteStore, StoreError,
    blob::verify_file,
};
use joshi_artifact_admission::{ValidatedDerivedArtifactV2, validate_derived_artifact_v2_part};
use joshi_domain::{CommitSeq, OpenVariant, StableString, UtcTimestamp, ValueDigest};
use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch};
use joshi_surface::DailyUseSurfaceProfileV1;
use rusqlite::{OptionalExtension, Transaction, TransactionBehavior, params};
use serde::{
    Deserialize, Serialize,
    de::{DeserializeOwned, DeserializeSeed, MapAccess, SeqAccess, Visitor},
};
use serde_json::{Map, Value};
use sha2::{Digest as _, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    net::IpAddr,
    sync::{
        OnceLock,
        atomic::{AtomicU64, Ordering},
    },
};

const AUTHORITY: &str = "read_only_no_execution";
const RUN_CONTRACT: &str = "joshi.wave5.run_registration";
const SPOOL_BINDING_CONTRACT: &str = "joshi.wave5.spool_catalog_binding.v1";
const OPERATIONAL_RECORD_CONTRACT: &str = "joshi.wave5.operational_record.v1";
const EXPORT_BINDING_CONTRACT: &str = "joshi.wave5.export_validation_binding.v1";
const RESTRICTED_ARTIFACT_CONTRACT: &str = "joshi.wave5.restricted_artifact_registration.v1";
const SPOOL_RECEIPT_CONTRACT: &str = "joshi.spool.catalog_admission_receipt";
const SPOOL_SEGMENT_CONTRACT: &str = "joshi.spool.segment.v1";
const STORE_RECEIPT_CONTRACT: &str = "joshi.store.ingest_receipt";
const PUMP_POLICY_CONTRACT: &str = "joshi.pump_source.physical_policy.v1";
const BUILD_MANIFEST_CONTRACT: &str = "joshi.wave5.build_manifest";
const SOURCE_TREE_MANIFEST_CONTRACT: &str = "joshi.wave5.source_tree_manifest";
const COLLECTOR_RUNTIME_CONFIG_CONTRACT: &str = "joshi.collector.runtime_config.v1";
const EXECUTION_ACCOUNTING_CONTRACT: &str = "joshi.collector.execution_accounting.v1";
const PRIVACY_POLICY_CONTRACT: &str = "joshi.wave5.privacy_policy";
const DERIVED_ARTIFACT_CONTRACT: &str = "joshi.analysis.derived-artifact/v2";
const DERIVED_ARTIFACT_FAMILY: &str = "descriptive_chart_shape";
const DERIVED_ARTIFACT_AUTHORITY: &str = "derived_analysis_read_only";
const DERIVED_CLAIM_SCOPE: &str = "descriptive_only_not_predictive_or_strategy_claim";
const DERIVED_PART_SCHEMA: &str = "joshi.analysis.descriptive-chart-shape/v2";
const MAX_CONTROL_BYTES: usize = 256 * 1024;
const MAX_INGEST_BATCH_BYTES: usize = 16 * 1024 * 1024;
const MAX_RUN_COMPONENT_BYTES: usize = 128 * 1024;
const MAX_ARTIFACT_BYTES: usize = 64 * 1024 * 1024;
const ARTIFACT_STORAGE_DOMAIN: &str = "public_source";
static WAVE5_MONOTONIC_SEQUENCE: AtomicU64 = AtomicU64::new(0);
static WAVE5_CLOCK_ID: OnceLock<StableString> = OnceLock::new();

/// Writer-owned clock/build material for one Wave 5 append.
#[derive(Clone, Debug)]
pub struct Wave5CommitContext {
    batch_id: StableString,
    committed_at: UtcTimestamp,
    writer_clock_id: StableString,
    committed_mono_ns: u64,
    writer_build: StableString,
}

impl Wave5CommitContext {
    const fn new(
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

    /// Store-owned wall time at which this pending append was created.
    #[must_use]
    pub const fn committed_at(&self) -> UtcTimestamp {
        self.committed_at
    }
}

/// The registration and all six exact components it closes.
///
/// These are byte strings, not caller-asserted parallel semantic fields. The store recomputes
/// every component digest and refuses the registration before I/O if any child differs.
#[derive(Clone, Copy, Debug)]
pub struct Wave5RunRegistrationByteBundle<'a> {
    pub registration: &'a [u8],
    pub build: &'a [u8],
    pub source_tree: &'a [u8],
    pub configuration: &'a [u8],
    pub budget: &'a [u8],
    pub privacy: &'a [u8],
    pub daily_use_surface_profile: &'a [u8],
}

/// Canonical occurrence that binds an exact spool/catalog receipt to one registered run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5SpoolCatalogBindingV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_admission_id: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub receipt_digest: String,
    pub authority: String,
}

/// Finite durable operational event family. Resource samples are not silently promoted here.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Wave5OperationalRecordKind {
    Status,
    Degradation,
    RecoveryStarted,
    RecoveryVerified,
    Stopped,
}

/// Finite state vocabulary retained independently from attained maturity.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Wave5OperationalState {
    Ready,
    Degraded,
    Unavailable,
    Gap,
    Backlogged,
    Stale,
    Recovering,
    Refused,
    Stopped,
}

/// Canonical durable status/degradation/recovery occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5OperationalRecordV1 {
    pub contract: String,
    pub schema_version: u64,
    pub record_id: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub component: String,
    pub kind: Wave5OperationalRecordKind,
    pub state: Wave5OperationalState,
    pub cause: Option<String>,
    pub predecessor_record_id: Option<String>,
    pub evidence_commit_seq: Option<String>,
    pub observed_at: UtcTimestamp,
    pub detail_digest: Option<String>,
    pub authority: String,
}

/// Canonical run binding for one already-durable production export validation occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5ExportValidationBindingV1 {
    pub contract: String,
    pub schema_version: u64,
    pub export_binding_id: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub export_request_id: String,
    pub validation_id: String,
    pub snapshot_id: String,
    pub manifest_digest: String,
    pub rust_validation_digest: String,
    pub python_validation_digest: String,
    pub validation_digest: String,
    pub truth_fingerprint: String,
    pub authority: String,
}

/// Canonical registration of one restricted, immutable analysis artifact occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5RestrictedArtifactRegistrationV1 {
    pub contract: String,
    pub schema_version: u64,
    pub import_id: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub export_binding_id: String,
    pub export_request_id: String,
    pub analysis_run_id: String,
    pub artifact_id: String,
    pub artifact_contract: String,
    pub manifest_digest: String,
    pub snapshot_id: String,
    pub claim_scope: String,
    pub truth_fingerprint: String,
    pub maximum_input_available_at: UtcTimestamp,
    pub authority: String,
}

/// Generic post-commit closure for one Wave 5 occurrence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5CommitReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub occurrence_id: StableString,
    pub exact_document_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub status: IdempotencyStatus,
}

/// Exact run registration loaded and reverified after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave5RunRegistration {
    pub run_registration_id: StableString,
    pub exact_bytes: Vec<u8>,
    pub exact_digest: ValueDigest,
    pub build_bytes: Vec<u8>,
    pub source_tree_bytes: Vec<u8>,
    pub configuration_bytes: Vec<u8>,
    pub budget_bytes: Vec<u8>,
    pub privacy_bytes: Vec<u8>,
    pub daily_surface_profile_bytes: Vec<u8>,
    pub commit_seq: CommitSeq,
}

/// Exact durable operational occurrence re-parsed and re-resolved after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave5OperationalRecord {
    pub record: Wave5OperationalRecordV1,
    pub exact_bytes: Vec<u8>,
    pub exact_digest: ValueDigest,
    pub commit_seq: CommitSeq,
}

/// Exact immutable analysis bytes and occurrence/content identities reverified after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave5RestrictedArtifact {
    pub registration: Wave5RestrictedArtifactRegistrationV1,
    pub registration_bytes: Vec<u8>,
    pub registration_digest: ValueDigest,
    pub manifest_bytes: Vec<u8>,
    pub artifact_bytes: Vec<u8>,
    pub artifact_digest: ValueDigest,
    pub commit_seq: CommitSeq,
}

#[derive(Clone, Debug)]
struct RunCapability {
    document: Wave5RunRegistrationWire,
    bytes: Vec<u8>,
    digest: ValueDigest,
    run_id: StableString,
    build_bytes: Vec<u8>,
    source_tree_bytes: Vec<u8>,
    configuration_bytes: Vec<u8>,
    budget_bytes: Vec<u8>,
    privacy_bytes: Vec<u8>,
    daily_surface_profile_bytes: Vec<u8>,
}

#[derive(Clone, Debug)]
struct SpoolCapability {
    binding: Wave5SpoolCatalogBindingV1,
    binding_bytes: Vec<u8>,
    binding_digest: ValueDigest,
    admission_id: StableString,
    receipt: SpoolCatalogReceiptWire,
    receipt_bytes: Vec<u8>,
    receipt_digest: ValueDigest,
}

#[derive(Clone, Debug)]
struct OperationalCapability {
    document: Wave5OperationalRecordV1,
    bytes: Vec<u8>,
    digest: ValueDigest,
    record_id: StableString,
    evidence_commit: Option<CommitSeq>,
}

#[derive(Clone, Debug)]
struct ExportCapability {
    document: Wave5ExportValidationBindingV1,
    bytes: Vec<u8>,
    digest: ValueDigest,
    binding_id: StableString,
}

#[derive(Clone, Debug)]
struct ArtifactCapability {
    document: Wave5RestrictedArtifactRegistrationV1,
    bytes: Vec<u8>,
    digest: ValueDigest,
    import_id: StableString,
    manifest_bytes: Vec<u8>,
    manifest: DerivedManifestWire,
    artifact_bytes: Vec<u8>,
    artifact_digest: ValueDigest,
}

type ExportResolutionRow = (
    String,
    String,
    String,
    String,
    String,
    String,
    Vec<u8>,
    String,
    i64,
);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireStatus {
    Accepted,
    Idempotent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireProtectionClass {
    PublicIntegrity,
    AuthenticatedPrivate,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExactClosureWire {
    digest: String,
    byte_length: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExactRegisteredDocumentWire {
    document_id: String,
    exact_bytes: ExactClosureWire,
}

/// Private parser mirror of the sole public wire authority in `joshi-admission::wave5`.
///
/// The store cannot depend on the admission crate without a dependency cycle. Keeping this type
/// private prevents a second caller-constructible registration authority while still making the
/// store independently reparse and verify the exact persisted bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Wave5RunRegistrationWire {
    contract: String,
    schema_version: u64,
    run_id: String,
    build: ExactRegisteredDocumentWire,
    source_tree: ExactRegisteredDocumentWire,
    configuration: ExactRegisteredDocumentWire,
    budget: ExactRegisteredDocumentWire,
    privacy: ExactRegisteredDocumentWire,
    daily_use_surface_profile: ExactRegisteredDocumentWire,
    authority: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum BuildProfileWire {
    LocalDebug,
    LocalRelease,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BuildManifestWire {
    contract: String,
    schema_version: u64,
    build_id: String,
    source_tree_digest: String,
    rustc_version: String,
    target_triple: String,
    profile: BuildProfileWire,
    authority: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum SourceTreeHeadWire {
    Unborn,
    Commit { object_id: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SourceTreeManifestWire {
    contract: String,
    schema_version: u64,
    repository_id: String,
    head: SourceTreeHeadWire,
    dirty: bool,
    working_tree_digest: String,
    diff_digest: Option<String>,
    authority: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LocalStatusEndpointWire {
    address: IpAddr,
    port: u16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ProviderExecutionModeWire {
    OfflineFixtureOnly,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CollectorRuntimeConfigWire {
    contract: String,
    schema_version: u64,
    plan_id: String,
    plan_template_digest: String,
    status_endpoint: LocalStatusEndpointWire,
    provider_execution: ProviderExecutionModeWire,
    authority: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[allow(clippy::struct_field_names)]
struct RunBudgetLimitsWire {
    maximum_requests: u64,
    maximum_pages: u64,
    maximum_ingress_bytes: u64,
    maximum_durable_bytes: u64,
    maximum_provider_credits: u64,
    maximum_ingress_bytes_per_second: Option<u64>,
    maximum_elapsed_ms: u64,
    maximum_in_flight_attempts: u64,
    maximum_in_flight_elapsed_overshoot_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExecutionAccountingDocumentWire {
    contract: String,
    schema_version: u64,
    limits: RunBudgetLimitsWire,
    authority: String,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum PermittedProtectionClassWire {
    PublicIntegrity,
    AuthenticatedPrivate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum CredentialHandlingWire {
    PurposeScopedHandlesOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WalletMaterialRuleWire {
    Forbidden,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PrivacyPolicyWire {
    contract: String,
    schema_version: u64,
    policy_id: String,
    permitted_protection_classes: Vec<PermittedProtectionClassWire>,
    credential_handling: CredentialHandlingWire,
    wallet_material: WalletMaterialRuleWire,
    export_private_material: bool,
    authority: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SpoolBatchClosureWire {
    batch_id: String,
    exact_batch: ExactClosureWire,
    logical_batch_digest: String,
    exact_policy: ExactClosureWire,
    store_admission_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SegmentByteClosureWire {
    digest: String,
    byte_len: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SegmentExpectedCountsWire {
    acquisitions: u64,
    raw_blobs: u64,
    raw_bytes: u64,
    observations: u64,
    source_events: u64,
    assertions: u64,
    coverage_windows: u64,
    coverage_gaps: u64,
    coverage_recoveries: u64,
    cursor_advances: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SegmentBatchClosureWire {
    batch_id: String,
    logical_digest: String,
    exact_batch: SegmentByteClosureWire,
    policy_contract: String,
    exact_policy: SegmentByteClosureWire,
    admission_digest: Option<String>,
    counts: SegmentExpectedCountsWire,
    acquisition_ids: Vec<String>,
    gap_ids: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SegmentEntryDescriptorWire {
    ordinal: u64,
    kind: String,
    occurrence_id: String,
    exact_entry: SegmentByteClosureWire,
    batch: Option<SegmentBatchClosureWire>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SegmentSourceOccurrenceWire {
    source_id: String,
    acquisition_id: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SegmentCursorCandidateWire<'a> {
    cursor_id: String,
    scope: &'a CoverageScope,
    cursor_kind: &'a OpenVariant,
    cursor_value: &'a StableString,
    acquisition_id: String,
    primary_observation_id: String,
    evidence_observation_ids: Vec<String>,
    predecessor_cursor_id: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SegmentEvidenceBatchEntryWire<'a> {
    closure: &'a SegmentBatchClosureWire,
    exact_batch_bytes: String,
    exact_policy_bytes: String,
    cursor_candidates: Vec<SegmentCursorCandidateWire<'a>>,
}

#[derive(Serialize)]
#[serde(tag = "kind", content = "record", rename_all = "snake_case")]
enum SegmentSpoolEntryWire<'a> {
    EvidenceBatch(SegmentEvidenceBatchEntryWire<'a>),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "class", rename_all = "snake_case", deny_unknown_fields)]
enum SegmentProtectionWire {
    PublicIntegrity,
    AuthenticatedPrivate {
        algorithm: String,
        key_id: String,
        nonce_base64: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SegmentHeaderWire {
    contract: String,
    segment_id: String,
    created_at: UtcTimestamp,
    domain: String,
    protection: SegmentProtectionWire,
    entries: Vec<SegmentEntryDescriptorWire>,
    source_occurrences: Vec<SegmentSourceOccurrenceWire>,
    body: SegmentByteClosureWire,
    sealed_body: SegmentByteClosureWire,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DiskSegmentWire {
    header: SegmentHeaderWire,
    sealed_body_bytes: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PumpPolicyEntryWire {
    retention_class: String,
    content_encoding: Option<String>,
    force_external: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PumpPhysicalPolicyWire {
    contract: String,
    observation_storage: BTreeMap<String, PumpPolicyEntryWire>,
    coverage_gap_severity: BTreeMap<String, String>,
    committed_at: String,
    writer_clock_id: String,
    committed_monotonic_ns: String,
    writer_build: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedManifestWire {
    manifest_version: String,
    analysis_run_id: String,
    artifact_id: String,
    artifact_family: String,
    authority: String,
    display_class: String,
    claim_scope: String,
    producer: DerivedProducerWire,
    input: DerivedInputWire,
    fit: DerivedFitWire,
    support: DerivedSupportWire,
    uncertainty: DerivedUncertaintyWire,
    restrictions: DerivedRestrictionsWire,
    artifacts: Vec<DerivedPartWire>,
    determinism: DerivedDeterminismWire,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedProducerWire {
    id: String,
    version: String,
    build_digest: String,
    configuration_digest: String,
    lock_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedInputWire {
    source_class: String,
    snapshot_contract: String,
    snapshot_id: String,
    snapshot_manifest_digest: String,
    catalog_commit_seq: String,
    publication_ids: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedFitWire {
    fit_cutoff: String,
    maximum_input_available_at: String,
    policy: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedSupportWire {
    output_rows: String,
    input_rows: String,
    window_ids: Vec<String>,
    gap_ids: Vec<String>,
    observed_inputs: String,
    gap_inputs: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedUncertaintyWire {
    status: String,
    reason: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum DerivedEconomicAuthorityWire {
    None,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
#[allow(clippy::struct_excessive_bools)]
struct DerivedRestrictionsWire {
    may_rank_census: bool,
    may_activate_hot_scope: bool,
    may_mutate_observations: bool,
    may_mutate_facts: bool,
    may_mutate_financial_truth: bool,
    economic_authority: DerivedEconomicAuthorityWire,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedPartWire {
    path: String,
    schema_id: String,
    schema: serde_json::Value,
    schema_digest: String,
    physical_digest: String,
    logical_digest: String,
    byte_length: String,
    row_count: String,
    primary_key: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedDeterminismWire {
    canonical_row_order: Vec<String>,
    wall_clock_excluded: bool,
    network_required: bool,
    operational_store_writes: bool,
}

type DurableGapResolution = (
    i64,
    String,
    String,
    String,
    Option<String>,
    String,
    Option<String>,
);

type ArtifactResolution = (
    String,
    String,
    String,
    String,
    i64,
    String,
    String,
    i64,
    i64,
);

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PublicAdmittedCountsWire {
    acquisitions: String,
    raw_blobs: String,
    raw_bytes: String,
    observations: String,
    source_events: String,
    assertions: String,
    coverage_windows: String,
    coverage_gaps: String,
    coverage_recoveries: String,
    cursor_advances: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PublicCoverageScopeWire {
    source_id: String,
    family: OpenVariant,
    subject: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "clock",
    rename_all = "snake_case",
    rename_all_fields = "camelCase"
)]
enum PublicBoundaryWire {
    Wall { value: String },
    Commit { value: String },
    SourceCursor { value: String },
    Unknown { reason: OpenVariant },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PublicGapOutcomeWire {
    gap_id: String,
    scope: PublicCoverageScopeWire,
    lower: PublicBoundaryWire,
    upper: Option<PublicBoundaryWire>,
    outcome: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PublicStoreReceiptWire {
    contract: String,
    schema_version: u64,
    catalog_id: String,
    catalog_schema: String,
    commit_seq: String,
    batch_id: String,
    batch_digest: String,
    store_admission_digest: String,
    status: WireStatus,
    from_commit_seq: String,
    through_commit_seq: String,
    admitted: PublicAdmittedCountsWire,
    acquisition_ids: Vec<String>,
    gap_outcomes: Vec<PublicGapOutcomeWire>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SpoolCatalogReceiptWire {
    contract: String,
    schema_version: u64,
    segment_id: String,
    protection_domain: String,
    protection_class: WireProtectionClass,
    exact_segment: ExactClosureWire,
    batch: SpoolBatchClosureWire,
    catalog_receipt: PublicStoreReceiptWire,
    status: WireStatus,
    authority: String,
}

impl SqliteStore {
    /// Creates opaque writer context from the store clock immediately before an append.
    ///
    /// The caller names the idempotency occurrence and its build, but cannot supply/backdate the
    /// store wall clock or monotonic reading.
    ///
    /// # Errors
    ///
    /// Refuses a read-only store, a clock value that cannot be represented exactly, an invalid
    /// process-clock identity, or exhausted monotonic sequence space.
    pub fn begin_wave5_commit(
        &self,
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave5CommitContext> {
        self.require_writer()?;
        let now = time::OffsetDateTime::now_utc();
        let aligned = now
            .replace_nanosecond((now.nanosecond() / 1_000) * 1_000)
            .map_err(|_| StoreError::TimestampRange {
                field: "Wave 5 store clock",
            })?;
        let committed_at = UtcTimestamp::new(aligned).map_err(|_| StoreError::TimestampRange {
            field: "Wave 5 store clock",
        })?;
        if WAVE5_CLOCK_ID.get().is_none() {
            let candidate = stable(
                &format!(
                    "wave5-store-process:{}:{}",
                    std::process::id(),
                    now.unix_timestamp_nanos()
                ),
                "Wave 5 writer clock ID",
            )?;
            let _ = WAVE5_CLOCK_ID.set(candidate);
        }
        let writer_clock_id = WAVE5_CLOCK_ID.get().cloned().ok_or_else(|| {
            StoreError::InvalidBatch("Wave 5 process clock failed to initialize".into())
        })?;
        let committed_mono_ns = WAVE5_MONOTONIC_SEQUENCE
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |value| {
                value.checked_add(1)
            })
            .map_err(|_| StoreError::IntegerRange {
                field: "Wave 5 monotonic sequence",
                value: u64::MAX.to_string(),
            })?
            .saturating_add(1);
        Ok(Wave5CommitContext::new(
            batch_id,
            committed_at,
            writer_clock_id,
            committed_mono_ns,
            writer_build,
        ))
    }

    /// Parses and durably registers one exact Wave 5 run before provider I/O.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical or changed bytes, unresolved closures, authority widening, a
    /// conflicting occurrence identity, read-only store use, or a failed durable commit.
    pub fn commit_wave5_run_registration_v1(
        &mut self,
        exact: &Wave5RunRegistrationByteBundle<'_>,
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let capability = RunCapability::parse(exact)?;
        let occurrence = capability.run_id.clone();
        let digest = operation_digest(&(
            "joshi.store.wave5_run_registration_commit.v1",
            capability.digest.as_str(),
        ))?;
        self.commit_wave5(
            context,
            "maintenance",
            &occurrence,
            &capability.digest,
            &digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave5_run_registration_v1
                     (run_registration_id,registration_sha256,registration_bytes,
                      registration_byte_length,build_sha256,build_bytes,build_byte_length,
                      source_tree_sha256,source_tree_bytes,source_tree_byte_length,
                      configuration_sha256,configuration_bytes,configuration_byte_length,
                      budget_sha256,budget_bytes,budget_byte_length,
                      privacy_sha256,privacy_bytes,privacy_byte_length,
                      daily_surface_profile_sha256,daily_surface_profile_bytes,
                      daily_surface_profile_byte_length,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                             ?17,?18,?19,?20,?21,?22,?23,?24)",
                    params![
                        capability.run_id.as_str(),
                        raw_digest(&capability.digest, "run registration")?,
                        capability.bytes,
                        sqlite_usize(capability.bytes.len(), "run registration bytes")?,
                        raw_digest_str(
                            &capability.document.build.exact_bytes.digest,
                            "run build",
                        )?,
                        capability.build_bytes,
                        sqlite_usize(capability.build_bytes.len(), "run build bytes")?,
                        raw_digest_str(
                            &capability.document.source_tree.exact_bytes.digest,
                            "run source tree",
                        )?,
                        capability.source_tree_bytes,
                        sqlite_usize(
                            capability.source_tree_bytes.len(),
                            "run source tree bytes",
                        )?,
                        raw_digest_str(
                            &capability.document.configuration.exact_bytes.digest,
                            "run configuration",
                        )?,
                        capability.configuration_bytes,
                        sqlite_usize(
                            capability.configuration_bytes.len(),
                            "run configuration bytes",
                        )?,
                        raw_digest_str(
                            &capability.document.budget.exact_bytes.digest,
                            "run budget",
                        )?,
                        capability.budget_bytes,
                        sqlite_usize(capability.budget_bytes.len(), "run budget bytes")?,
                        raw_digest_str(
                            &capability.document.privacy.exact_bytes.digest,
                            "run privacy",
                        )?,
                        capability.privacy_bytes,
                        sqlite_usize(capability.privacy_bytes.len(), "run privacy bytes")?,
                        raw_digest_str(
                            &capability
                                .document
                                .daily_use_surface_profile
                                .exact_bytes
                                .digest,
                            "daily surface profile",
                        )?,
                        capability.daily_surface_profile_bytes,
                        sqlite_usize(
                            capability.daily_surface_profile_bytes.len(),
                            "daily surface profile bytes",
                        )?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Loads and re-parses exact registered run bytes after restart.
    ///
    /// # Errors
    ///
    /// Refuses malformed or changed persisted bytes, invalid identities/digests, or a catalog
    /// read failure.
    pub fn load_wave5_run_registration_v1(
        &self,
        run_registration_id: &StableString,
    ) -> Result<Option<StoredWave5RunRegistration>> {
        type Row = (
            String,
            Vec<u8>,
            Vec<u8>,
            Vec<u8>,
            Vec<u8>,
            Vec<u8>,
            Vec<u8>,
            Vec<u8>,
            i64,
        );
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT registration_sha256,registration_bytes,build_bytes,source_tree_bytes,
                        configuration_bytes,budget_bytes,privacy_bytes,daily_surface_profile_bytes,
                        created_commit_seq
                 FROM wave5_run_registration_v1 WHERE run_registration_id=?1",
                [run_registration_id.as_str()],
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
        let Some((raw, bytes, build, tree, config, budget, privacy, profile, seq)) = row else {
            return Ok(None);
        };
        let bundle = Wave5RunRegistrationByteBundle {
            registration: &bytes,
            build: &build,
            source_tree: &tree,
            configuration: &config,
            budget: &budget,
            privacy: &privacy,
            daily_use_surface_profile: &profile,
        };
        let parsed = RunCapability::parse(&bundle)?;
        let exact_columns: bool = self.connection.query_row(
            "SELECT build_sha256=?2 AND source_tree_sha256=?3
                    AND configuration_sha256=?4 AND budget_sha256=?5
                    AND privacy_sha256=?6 AND daily_surface_profile_sha256=?7
             FROM wave5_run_registration_v1 WHERE run_registration_id=?1",
            params![
                run_registration_id.as_str(),
                raw_digest_str(&parsed.document.build.exact_bytes.digest, "run build")?,
                raw_digest_str(
                    &parsed.document.source_tree.exact_bytes.digest,
                    "run source tree",
                )?,
                raw_digest_str(
                    &parsed.document.configuration.exact_bytes.digest,
                    "run configuration",
                )?,
                raw_digest_str(&parsed.document.budget.exact_bytes.digest, "run budget")?,
                raw_digest_str(&parsed.document.privacy.exact_bytes.digest, "run privacy")?,
                raw_digest_str(
                    &parsed.document.daily_use_surface_profile.exact_bytes.digest,
                    "daily surface profile",
                )?,
            ],
            |row| row.get(0),
        )?;
        if parsed.run_id != *run_registration_id
            || raw_digest(&parsed.digest, "run")? != raw
            || !exact_columns
        {
            return Err(StoreError::InvalidBatch(
                "persisted Wave 5 run registration closure differs from exact bytes".into(),
            ));
        }
        Ok(Some(StoredWave5RunRegistration {
            run_registration_id: parsed.run_id,
            exact_bytes: bytes,
            exact_digest: parsed.digest,
            build_bytes: build,
            source_tree_bytes: tree,
            configuration_bytes: config,
            budget_bytes: budget,
            privacy_bytes: privacy,
            daily_surface_profile_bytes: profile,
            commit_seq: CommitSeq::new(as_u64(seq, "run commit sequence")?),
        }))
    }

    /// Parses exact spool, batch, policy, receipt and run-binding bytes before durable closure.
    ///
    /// # Errors
    ///
    /// Refuses any exact-byte, logical-batch, catalog-receipt, run, authority, ordering, or
    /// occurrence mismatch, or a failed durable commit.
    #[allow(clippy::too_many_arguments)]
    pub fn commit_wave5_spool_catalog_binding_v1(
        &mut self,
        exact_binding_bytes: &[u8],
        exact_segment_bytes: &[u8],
        exact_batch_bytes: &[u8],
        exact_policy_bytes: &[u8],
        exact_receipt_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let capability = SpoolCapability::parse(
            self,
            exact_binding_bytes,
            exact_segment_bytes,
            exact_batch_bytes,
            exact_policy_bytes,
            exact_receipt_bytes,
        )?;
        let occurrence = capability.admission_id.clone();
        let document_digest = capability.binding_digest.clone();
        let digest = operation_digest(&(
            "joshi.store.wave5_spool_catalog_binding_commit.v1",
            capability.binding_digest.as_str(),
            capability.receipt_digest.as_str(),
        ))?;
        self.commit_wave5(
            context,
            "maintenance",
            &occurrence,
            &document_digest,
            &digest,
            |tx, seq| {
                let store_seq = sqlite_wire_u64(
                    &capability.receipt.catalog_receipt.commit_seq,
                    "store commit sequence",
                )?;
                let segment_sha =
                    raw_digest_str(&capability.receipt.exact_segment.digest, "exact segment")?;
                let exact_batch_sha =
                    raw_digest_str(&capability.receipt.batch.exact_batch.digest, "exact batch")?;
                let exact_policy_sha = raw_digest_str(
                    &capability.receipt.batch.exact_policy.digest,
                    "exact policy",
                )?;
                let logical_sha = raw_digest_str(
                    &capability.receipt.batch.logical_batch_digest,
                    "logical batch",
                )?;
                let admission_sha = raw_digest_str(
                    &capability.receipt.batch.store_admission_digest,
                    "store admission",
                )?;
                let inserted = tx.execute(
                    "INSERT OR IGNORE INTO spool_catalog_admission
                     (segment_id,batch_id,protection_domain,protection_class,segment_sha256,
                      segment_byte_length,exact_batch_sha256,exact_policy_sha256,
                      logical_batch_sha256,store_admission_sha256,store_commit_seq,
                      receipt_sha256,receipt_bytes,receipt_byte_length,recorded_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)",
                    params![
                        capability.receipt.segment_id,
                        capability.receipt.batch.batch_id,
                        capability.receipt.protection_domain,
                        protection_class_str(capability.receipt.protection_class),
                        segment_sha,
                        sqlite_wire_u64(
                            &capability.receipt.exact_segment.byte_length,
                            "segment byte length",
                        )?,
                        exact_batch_sha,
                        exact_policy_sha,
                        logical_sha,
                        admission_sha,
                        store_seq,
                        raw_digest(&capability.receipt_digest, "spool receipt")?,
                        capability.receipt_bytes,
                        sqlite_usize(capability.receipt_bytes.len(), "spool receipt bytes")?,
                        seq,
                    ],
                )?;
                if inserted == 0 {
                    verify_existing_spool_catalog(tx, &capability)?;
                }
                tx.execute(
                    "INSERT INTO wave5_spool_catalog_binding_v1
                     (catalog_admission_id,run_registration_id,run_registration_sha256,
                      segment_id,batch_id,binding_sha256,binding_bytes,binding_byte_length,
                      authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
                    params![
                        capability.admission_id.as_str(),
                        capability.binding.run_registration_id,
                        raw_digest_str(
                            &capability.binding.run_registration_digest,
                            "run registration",
                        )?,
                        capability.receipt.segment_id,
                        capability.receipt.batch.batch_id,
                        raw_digest(&capability.binding_digest, "spool binding")?,
                        capability.binding_bytes,
                        sqlite_usize(capability.binding_bytes.len(), "spool binding bytes")?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Parses and appends one durable operational status/degradation/recovery record.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical bytes, an unknown finite value, an invalid transition, a missing run,
    /// predecessor or evidence commit, future observation time, or a failed durable commit.
    pub fn commit_wave5_operational_record_v1(
        &mut self,
        exact_record_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let capability = OperationalCapability::parse(self, exact_record_bytes, context, None)?;
        let occurrence = capability.record_id.clone();
        let document_digest = capability.digest.clone();
        let digest = operation_digest(&(
            "joshi.store.wave5_operational_record_commit.v1",
            capability.digest.as_str(),
        ))?;
        self.commit_wave5(
            context,
            "maintenance",
            &occurrence,
            &document_digest,
            &digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave5_operational_record_v1
                     (record_id,run_registration_id,run_registration_sha256,component,
                      record_kind,state,cause,predecessor_record_id,evidence_commit_seq,
                      observed_wall_us,detail_sha256,record_sha256,record_bytes,
                      record_byte_length,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)",
                    params![
                        capability.record_id.as_str(),
                        capability.document.run_registration_id,
                        raw_digest_str(
                            &capability.document.run_registration_digest,
                            "run registration",
                        )?,
                        capability.document.component,
                        operational_kind_str(capability.document.kind),
                        operational_state_str(capability.document.state),
                        capability.document.cause,
                        capability.document.predecessor_record_id,
                        capability
                            .evidence_commit
                            .map(|value| sqlite_u64(value.get(), "evidence commit"))
                            .transpose()?,
                        timestamp_us(capability.document.observed_at, "operational observed_at")?,
                        capability
                            .document
                            .detail_digest
                            .as_deref()
                            .map(|value| raw_digest_str(value, "operational detail"))
                            .transpose()?,
                        raw_digest(&capability.digest, "operational record")?,
                        capability.bytes,
                        sqlite_usize(capability.bytes.len(), "operational record bytes")?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Loads and re-resolves one exact operational occurrence after restart.
    ///
    /// # Errors
    ///
    /// Refuses changed/noncanonical bytes, an invalid run/predecessor/evidence closure, a future
    /// observation, malformed persisted fields, or a catalog read failure.
    pub fn load_wave5_operational_record_v1(
        &self,
        record_id: &StableString,
    ) -> Result<Option<StoredWave5OperationalRecord>> {
        type Row = (String, Vec<u8>, i64, i64);
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT r.record_sha256,r.record_bytes,r.created_commit_seq,c.committed_wall_us
                 FROM wave5_operational_record_v1 r
                 JOIN ingest_commit c ON c.commit_seq=r.created_commit_seq
                 WHERE r.record_id=?1",
                [record_id.as_str()],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?;
        let Some((raw, bytes, seq, committed_us)) = row else {
            return Ok(None);
        };
        let context = Wave5CommitContext::new(
            stable("wave5:readback", "readback batch ID")?,
            timestamp_from_us(committed_us, "operational commit time")?,
            stable("wave5:readback-clock", "readback clock ID")?,
            0,
            stable("wave5:readback-build", "readback build ID")?,
        );
        let parsed = OperationalCapability::parse(
            self,
            &bytes,
            &context,
            Some(CommitSeq::new(as_u64(seq, "operational record commit")?)),
        )?;
        if parsed.record_id != *record_id
            || raw_digest(&parsed.digest, "operational record")? != raw
        {
            return Err(StoreError::InvalidBatch(
                "persisted operational occurrence differs from exact record bytes".into(),
            ));
        }
        Ok(Some(StoredWave5OperationalRecord {
            record: parsed.document,
            exact_bytes: bytes,
            exact_digest: parsed.digest,
            commit_seq: CommitSeq::new(as_u64(seq, "operational record commit")?),
        }))
    }

    /// Loads the latest exact operational occurrence for one run/component pair.
    ///
    /// # Errors
    ///
    /// Refuses invalid identities, malformed/changed persisted bytes, broken transition closure,
    /// or a catalog read failure.
    pub fn load_latest_wave5_operational_record_v1(
        &self,
        run_registration_id: &StableString,
        component: &StableString,
    ) -> Result<Option<StoredWave5OperationalRecord>> {
        let record: Option<String> = self
            .connection
            .query_row(
                "SELECT record_id FROM wave5_operational_record_v1
                 WHERE run_registration_id=?1 AND component=?2
                 ORDER BY created_commit_seq DESC LIMIT 1",
                params![run_registration_id.as_str(), component.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        let Some(record) = record else {
            return Ok(None);
        };
        let record_id = stable(&record, "operational record ID")?;
        let loaded = self.load_wave5_operational_record_v1(&record_id)?;
        if loaded.is_none() {
            return Err(StoreError::MissingIdentity {
                kind: "operational record",
                identity: record,
            });
        }
        Ok(loaded)
    }

    /// Parses and run-binds one already-durable production export validation.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical bytes, a missing or changed run/export/validation closure, authority
    /// widening, future ordering, or a failed durable commit.
    pub fn commit_wave5_export_validation_binding_v1(
        &mut self,
        exact_binding_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let capability = ExportCapability::parse(self, exact_binding_bytes)?;
        let occurrence = capability.binding_id.clone();
        let document_digest = capability.digest.clone();
        let digest = operation_digest(&(
            "joshi.store.wave5_export_validation_binding_commit.v1",
            capability.digest.as_str(),
        ))?;
        self.commit_wave5(
            context,
            "export",
            &occurrence,
            &document_digest,
            &digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave5_export_validation_binding_v1
                     (export_binding_id,run_registration_id,run_registration_sha256,
                      export_request_id,validation_id,snapshot_id,binding_sha256,binding_bytes,
                      binding_byte_length,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
                    params![
                        capability.binding_id.as_str(),
                        capability.document.run_registration_id,
                        raw_digest_str(
                            &capability.document.run_registration_digest,
                            "run registration",
                        )?,
                        capability.document.export_request_id,
                        capability.document.validation_id,
                        capability.document.snapshot_id,
                        raw_digest(&capability.digest, "export binding")?,
                        capability.bytes,
                        sqlite_usize(capability.bytes.len(), "export binding bytes")?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Parses, resolves and durably installs a restricted artifact in verified external CAS.
    ///
    /// # Errors
    ///
    /// Refuses changed bytes, collapsed occurrence/content identities, a future or unresolved
    /// input, authority widening, unsafe CAS placement, or a failed durable commit.
    pub fn commit_wave5_restricted_artifact_v1(
        &mut self,
        exact_registration_bytes: &[u8],
        exact_manifest_bytes: &[u8],
        exact_artifact_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let capability = ArtifactCapability::parse(
            self,
            exact_registration_bytes,
            exact_manifest_bytes,
            exact_artifact_bytes,
            context,
        )?;
        let blob_store = BlobStore::new(&self.config.blob_root, self.config.inline_blob_max_bytes);
        let prepared = blob_store.prepare(
            &capability.artifact_bytes,
            stable("application/vnd.apache.parquet", "artifact content type")?,
            None,
            stable(ARTIFACT_STORAGE_DOMAIN, "artifact storage domain")?,
            true,
        )?;
        blob_store.verify(&prepared)?;
        let artifact_path = prepared
            .relative_path
            .as_ref()
            .map(|relative| self.config.blob_root.join(relative))
            .ok_or_else(|| {
                StoreError::InvalidBatch(
                    "restricted artifact did not receive external CAS placement".into(),
                )
            })?;
        validate_artifact_part_capability(&capability, &artifact_path)?;
        let occurrence = capability.import_id.clone();
        let document_digest = capability.digest.clone();
        let digest = operation_digest(&(
            "joshi.store.wave5_restricted_artifact_commit.v1",
            capability.digest.as_str(),
            capability.artifact_digest.as_str(),
        ))?;
        self.commit_wave5(
            context,
            "projection",
            &occurrence,
            &document_digest,
            &digest,
            |tx, seq| {
                insert_prepared_blob(tx, &prepared, seq)?;
                tx.execute(
                    "INSERT INTO wave5_restricted_artifact_v1
                     (import_id,run_registration_id,run_registration_sha256,export_binding_id,
                      export_request_id,analysis_run_id,artifact_id,artifact_contract,
                      manifest_sha256,manifest_bytes,manifest_byte_length,snapshot_id,claim_scope,
                      truth_fingerprint_sha256,maximum_input_available_wall_us,
                      registration_sha256,registration_bytes,registration_byte_length,
                      authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,
                             ?16,?17,?18,?19,?20)",
                    params![
                        capability.import_id.as_str(),
                        capability.document.run_registration_id,
                        raw_digest_str(
                            &capability.document.run_registration_digest,
                            "run registration",
                        )?,
                        capability.document.export_binding_id,
                        capability.document.export_request_id,
                        capability.document.analysis_run_id,
                        capability.document.artifact_id,
                        capability.document.artifact_contract,
                        raw_digest_str(&capability.document.manifest_digest, "artifact manifest",)?,
                        capability.manifest_bytes,
                        sqlite_usize(capability.manifest_bytes.len(), "artifact manifest bytes")?,
                        capability.document.snapshot_id,
                        capability.document.claim_scope,
                        raw_digest_str(
                            &capability.document.truth_fingerprint,
                            "artifact truth fingerprint",
                        )?,
                        timestamp_us(
                            capability.document.maximum_input_available_at,
                            "artifact maximum input availability",
                        )?,
                        raw_digest(&capability.digest, "artifact registration")?,
                        capability.bytes,
                        sqlite_usize(capability.bytes.len(), "artifact registration bytes")?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                tx.execute(
                    "INSERT INTO wave5_restricted_artifact_part_v1
                     (import_id,part_ordinal,blob_id,storage_domain,physical_sha256,byte_length)
                     VALUES (?1,0,?2,?3,?2,?4)",
                    params![
                        capability.import_id.as_str(),
                        prepared.raw_sha256,
                        prepared.storage_domain.as_str(),
                        sqlite_u64(prepared.content_length, "artifact byte length")?,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Loads and re-verifies registration, manifest, CAS placement and exact artifact bytes.
    ///
    /// # Errors
    ///
    /// Refuses missing/changed physical bytes, malformed persisted registration or manifest
    /// closure, non-external placement, invalid identities, or a catalog/filesystem read failure.
    pub fn load_wave5_restricted_artifact_v1(
        &self,
        import_id: &StableString,
    ) -> Result<Option<StoredWave5RestrictedArtifact>> {
        type Row = (
            Vec<u8>,
            String,
            Vec<u8>,
            String,
            String,
            String,
            i64,
            i64,
            i64,
        );
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT a.registration_bytes,a.registration_sha256,a.manifest_bytes,
                        p.blob_id,o.storage_mode,o.relative_path,p.byte_length,
                        a.created_commit_seq,c.committed_wall_us
                 FROM wave5_restricted_artifact_v1 a
                 JOIN wave5_restricted_artifact_part_v1 p ON p.import_id=a.import_id
                 JOIN blob_object o ON o.blob_id=p.blob_id AND o.storage_domain=p.storage_domain
                 JOIN ingest_commit c ON c.commit_seq=a.created_commit_seq
                 WHERE a.import_id=?1 AND p.part_ordinal=0",
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
            registration,
            registration_sha,
            manifest,
            blob_sha,
            mode,
            path,
            length,
            seq,
            committed_us,
        )) = row
        else {
            return Ok(None);
        };
        if mode != "external" {
            return Err(StoreError::InvalidBatch(
                "restricted artifact must remain in external CAS".into(),
            ));
        }
        let parsed = ArtifactCapability::parse_registration_only(&registration, &manifest)?;
        if parsed.import_id != *import_id
            || raw_digest(&parsed.digest, "artifact registration")? != registration_sha
            || raw_digest(&parsed.artifact_digest, "artifact")? != blob_sha
        {
            return Err(StoreError::InvalidBatch(
                "persisted restricted artifact metadata differs from exact registration".into(),
            ));
        }
        let length = as_u64(length, "artifact byte length")?;
        let absolute = self.config.blob_root.join(&path);
        verify_file(&absolute, &blob_sha, length)?;
        let artifact_bytes =
            fs::read(&absolute).map_err(|source| StoreError::io(&absolute, source))?;
        let context = Wave5CommitContext::new(
            stable("wave5:readback", "readback batch ID")?,
            timestamp_from_us(committed_us, "artifact commit time")?,
            stable("wave5:readback-clock", "readback clock ID")?,
            0,
            stable("wave5:readback-build", "readback build ID")?,
        );
        let capability =
            ArtifactCapability::parse(self, &registration, &manifest, &artifact_bytes, &context)?;
        validate_artifact_part_capability(&capability, &absolute)?;
        Ok(Some(StoredWave5RestrictedArtifact {
            registration: capability.document,
            registration_bytes: registration,
            registration_digest: capability.digest,
            manifest_bytes: manifest,
            artifact_bytes,
            artifact_digest: capability.artifact_digest,
            commit_seq: CommitSeq::new(as_u64(seq, "artifact commit sequence")?),
        }))
    }

    fn commit_wave5<F>(
        &mut self,
        context: &Wave5CommitContext,
        commit_class: &'static str,
        occurrence_id: &StableString,
        exact_document_digest: &ValueDigest,
        operation_digest: &ValueDigest,
        insert: F,
    ) -> Result<Wave5CommitReceipt>
    where
        F: FnOnce(&Transaction<'_>, i64) -> Result<()>,
    {
        self.require_writer()?;
        let committed_wall_us = timestamp_us(context.committed_at, "Wave 5 commit time")?;
        let raw_operation = raw_digest(operation_digest, "Wave 5 operation")?;
        if let Some((seq, existing)) = self
            .connection
            .query_row(
                "SELECT commit_seq,commit_digest FROM ingest_commit WHERE commit_id=?1",
                [context.batch_id.as_str()],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?
        {
            if existing != raw_operation {
                return Err(StoreError::IdentityConflict {
                    kind: "Wave 5 commit batch",
                    identity: context.batch_id.to_string(),
                });
            }
            return self.wave5_receipt(
                context,
                occurrence_id,
                exact_document_digest.clone(),
                seq,
                IdempotencyStatus::Idempotent,
            );
        }
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let latest_wall: Option<i64> = tx
            .query_row(
                "SELECT committed_wall_us FROM ingest_commit ORDER BY commit_seq DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        if latest_wall.is_some_and(|prior| committed_wall_us < prior) {
            return Err(StoreError::InvalidBatch(
                "Wave 5 store wall clock regressed behind the durable commit chain".into(),
            ));
        }
        let prior_clock: Option<String> = tx
            .query_row(
                "SELECT committed_mono_ns FROM ingest_commit
                 WHERE writer_clock_id=?1 ORDER BY commit_seq DESC LIMIT 1",
                [context.writer_clock_id.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(prior_mono) = prior_clock
            && context.committed_mono_ns
                <= parse_wire(&prior_mono, "prior Wave 5 monotonic sequence")?
        {
            return Err(StoreError::InvalidBatch(
                "Wave 5 store monotonic sequence did not strictly advance".into(),
            ));
        }
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
                committed_wall_us,
                context.writer_clock_id.as_str(),
                context.committed_mono_ns.to_string(),
                context.writer_build.as_str(),
                prior,
                raw_operation,
            ],
        )?;
        let seq = tx.last_insert_rowid();
        insert(&tx, seq)?;
        tx.commit()?;
        self.wave5_receipt(
            context,
            occurrence_id,
            exact_document_digest.clone(),
            seq,
            IdempotencyStatus::Accepted,
        )
    }

    fn wave5_receipt(
        &self,
        context: &Wave5CommitContext,
        occurrence_id: &StableString,
        exact_document_digest: ValueDigest,
        seq: i64,
        status: IdempotencyStatus,
    ) -> Result<Wave5CommitReceipt> {
        let version: i64 = self
            .connection
            .pragma_query_value(None, "user_version", |row| row.get(0))?;
        Ok(Wave5CommitReceipt {
            catalog_id: self.config.catalog_id.clone(),
            catalog_schema: stable(&format!("joshi.sqlite.v{version}"), "catalog schema")?,
            batch_id: context.batch_id.clone(),
            occurrence_id: occurrence_id.clone(),
            exact_document_digest,
            commit_seq: CommitSeq::new(as_u64(seq, "Wave 5 commit sequence")?),
            status,
        })
    }
}

impl RunCapability {
    fn parse(exact: &Wave5RunRegistrationByteBundle<'_>) -> Result<Self> {
        let document: Wave5RunRegistrationWire =
            parse_canonical(exact.registration, MAX_CONTROL_BYTES, "run")?;
        require_header(&document.contract, document.schema_version, RUN_CONTRACT)?;
        require_authority(&document.authority)?;
        let run_id = stable_ascii(&document.run_id, "run registration ID")?;
        for (declared, bytes, kind) in [
            (&document.build, exact.build, "run build"),
            (&document.source_tree, exact.source_tree, "run source tree"),
            (
                &document.configuration,
                exact.configuration,
                "run configuration",
            ),
            (&document.budget, exact.budget, "run budget"),
            (&document.privacy, exact.privacy, "run privacy"),
            (
                &document.daily_use_surface_profile,
                exact.daily_use_surface_profile,
                "daily surface profile",
            ),
        ] {
            stable_ascii(&declared.document_id, "run component document ID")?;
            if bytes.len() > MAX_RUN_COMPONENT_BYTES
                || verify_closure(&declared.exact_bytes, bytes, kind).is_err()
            {
                return Err(StoreError::InvalidBatch(format!(
                    "{kind} exact bytes do not close the run registration"
                )));
            }
        }
        validate_run_component_semantics(&document, exact)?;
        Ok(Self {
            document,
            bytes: exact.registration.to_vec(),
            digest: bytes_digest(exact.registration)?,
            run_id,
            build_bytes: exact.build.to_vec(),
            source_tree_bytes: exact.source_tree.to_vec(),
            configuration_bytes: exact.configuration.to_vec(),
            budget_bytes: exact.budget.to_vec(),
            privacy_bytes: exact.privacy.to_vec(),
            daily_surface_profile_bytes: exact.daily_use_surface_profile.to_vec(),
        })
    }
}

fn validate_run_component_semantics(
    registration: &Wave5RunRegistrationWire,
    exact: &Wave5RunRegistrationByteBundle<'_>,
) -> Result<()> {
    let source_tree: SourceTreeManifestWire = parse_canonical(
        exact.source_tree,
        MAX_RUN_COMPONENT_BYTES,
        "source-tree manifest",
    )?;
    require_header(
        &source_tree.contract,
        source_tree.schema_version,
        SOURCE_TREE_MANIFEST_CONTRACT,
    )?;
    stable_component(&source_tree.repository_id, "source-tree repository ID")?;
    qualified_digest(&source_tree.working_tree_digest, "working-tree digest")?;
    match &source_tree.head {
        SourceTreeHeadWire::Unborn => {}
        SourceTreeHeadWire::Commit { object_id }
            if matches!(object_id.len(), 40 | 64)
                && object_id.bytes().all(|byte| byte.is_ascii_hexdigit())
                && object_id.bytes().all(|byte| !byte.is_ascii_uppercase()) => {}
        SourceTreeHeadWire::Commit { .. } => {
            return Err(StoreError::InvalidBatch(
                "source-tree head must be a 40- or 64-character lowercase hex object ID".into(),
            ));
        }
    }
    match (source_tree.dirty, source_tree.diff_digest.as_deref()) {
        (true, Some(digest)) => {
            qualified_digest(digest, "source-tree diff")?;
        }
        (false, None) => {}
        _ => {
            return Err(StoreError::InvalidBatch(
                "dirty source-tree state requires exactly one diff digest".into(),
            ));
        }
    }
    require_authority(&source_tree.authority)?;

    let build: BuildManifestWire =
        parse_canonical(exact.build, MAX_RUN_COMPONENT_BYTES, "build manifest")?;
    require_header(
        &build.contract,
        build.schema_version,
        BUILD_MANIFEST_CONTRACT,
    )?;
    stable_component(&build.build_id, "build ID")?;
    stable_component(&build.rustc_version, "Rust compiler version")?;
    stable_component(&build.target_triple, "build target triple")?;
    qualified_digest(&build.source_tree_digest, "build source-tree digest")?;
    if build.source_tree_digest != registration.source_tree.exact_bytes.digest {
        return Err(StoreError::InvalidBatch(
            "build manifest does not close the exact source-tree bytes".into(),
        ));
    }
    require_authority(&build.authority)?;

    let configuration: CollectorRuntimeConfigWire = parse_canonical(
        exact.configuration,
        MAX_RUN_COMPONENT_BYTES,
        "collector runtime configuration",
    )?;
    require_header(
        &configuration.contract,
        configuration.schema_version,
        COLLECTOR_RUNTIME_CONFIG_CONTRACT,
    )?;
    stable_component(&configuration.plan_id, "collector plan ID")?;
    qualified_digest(
        &configuration.plan_template_digest,
        "collector plan-template digest",
    )?;
    if !configuration.status_endpoint.address.is_loopback()
        || configuration.status_endpoint.port == 0
        || configuration.provider_execution != ProviderExecutionModeWire::OfflineFixtureOnly
    {
        return Err(StoreError::InvalidBatch(
            "collector status endpoint must be nonzero and loopback-only".into(),
        ));
    }
    require_authority(&configuration.authority)?;

    let budget: ExecutionAccountingDocumentWire = parse_canonical(
        exact.budget,
        MAX_RUN_COMPONENT_BYTES,
        "execution-accounting document",
    )?;
    require_header(
        &budget.contract,
        budget.schema_version,
        EXECUTION_ACCOUNTING_CONTRACT,
    )?;
    let limits = budget.limits;
    if limits.maximum_requests == 0
        || limits.maximum_ingress_bytes == 0
        || limits.maximum_durable_bytes == 0
        || limits.maximum_elapsed_ms == 0
        || limits.maximum_in_flight_attempts == 0
        || limits.maximum_in_flight_attempts > limits.maximum_requests
        || limits.maximum_in_flight_elapsed_overshoot_ms == 0
        || limits.maximum_in_flight_elapsed_overshoot_ms > limits.maximum_elapsed_ms
        || limits.maximum_ingress_bytes_per_second == Some(0)
    {
        return Err(StoreError::InvalidBatch(
            "execution budget must be finite, positive, and bound in-flight work".into(),
        ));
    }
    require_authority(&budget.authority)?;

    let privacy: PrivacyPolicyWire =
        parse_canonical(exact.privacy, MAX_RUN_COMPONENT_BYTES, "privacy policy")?;
    require_header(
        &privacy.contract,
        privacy.schema_version,
        PRIVACY_POLICY_CONTRACT,
    )?;
    stable_component(&privacy.policy_id, "privacy policy ID")?;
    if privacy.permitted_protection_classes.is_empty()
        || privacy
            .permitted_protection_classes
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || privacy.export_private_material
        || privacy.credential_handling != CredentialHandlingWire::PurposeScopedHandlesOnly
        || privacy.wallet_material != WalletMaterialRuleWire::Forbidden
    {
        return Err(StoreError::InvalidBatch(
            "privacy policy must use a sorted nonempty protection set and forbid private export"
                .into(),
        ));
    }
    require_authority(&privacy.authority)?;

    let surface: DailyUseSurfaceProfileV1 = parse_canonical(
        exact.daily_use_surface_profile,
        MAX_RUN_COMPONENT_BYTES,
        "daily-use surface profile",
    )?;
    surface.validate().map_err(|error| {
        StoreError::InvalidBatch(format!("daily-use surface profile is invalid: {error}"))
    })?;
    if surface.canonical_bytes().map_err(|error| {
        StoreError::InvalidBatch(format!("daily-use surface profile is invalid: {error}"))
    })? != exact.daily_use_surface_profile
    {
        return Err(StoreError::InvalidBatch(
            "daily-use surface profile bytes are not canonical".into(),
        ));
    }
    Ok(())
}

fn stable_component(value: &str, field: &'static str) -> Result<()> {
    if value.is_empty()
        || value.len() > 255
        || value.trim() != value
        || value.chars().any(char::is_control)
    {
        Err(StoreError::InvalidBatch(format!(
            "{field} is not a bounded stable string"
        )))
    } else {
        Ok(())
    }
}

impl SpoolCapability {
    fn parse(
        store: &SqliteStore,
        binding_bytes: &[u8],
        segment_bytes: &[u8],
        batch_bytes: &[u8],
        policy_bytes: &[u8],
        receipt_bytes: &[u8],
    ) -> Result<Self> {
        let binding: Wave5SpoolCatalogBindingV1 =
            parse_canonical(binding_bytes, MAX_CONTROL_BYTES, "spool binding")?;
        require_header(
            &binding.contract,
            binding.schema_version,
            SPOOL_BINDING_CONTRACT,
        )?;
        require_authority(&binding.authority)?;
        let admission_id = stable(&binding.catalog_admission_id, "catalog admission ID")?;
        resolve_run(
            store,
            &binding.run_registration_id,
            &binding.run_registration_digest,
        )?;
        let receipt: SpoolCatalogReceiptWire =
            parse_canonical(receipt_bytes, MAX_CONTROL_BYTES, "spool receipt")?;
        validate_spool_receipt(store, &receipt, segment_bytes, batch_bytes, policy_bytes)?;
        let receipt_digest = bytes_digest(receipt_bytes)?;
        if qualified_digest(&binding.receipt_digest, "spool receipt")? != receipt_digest {
            return Err(StoreError::InvalidBatch(
                "spool binding receipt digest differs from exact receipt bytes".into(),
            ));
        }
        Ok(Self {
            binding,
            binding_bytes: binding_bytes.to_vec(),
            binding_digest: bytes_digest(binding_bytes)?,
            admission_id,
            receipt,
            receipt_bytes: receipt_bytes.to_vec(),
            receipt_digest,
        })
    }
}

impl OperationalCapability {
    fn parse(
        store: &SqliteStore,
        bytes: &[u8],
        context: &Wave5CommitContext,
        persisted_at: Option<CommitSeq>,
    ) -> Result<Self> {
        let document: Wave5OperationalRecordV1 =
            parse_canonical(bytes, MAX_CONTROL_BYTES, "operational record")?;
        require_header(
            &document.contract,
            document.schema_version,
            OPERATIONAL_RECORD_CONTRACT,
        )?;
        require_authority(&document.authority)?;
        let record_id = stable(&document.record_id, "operational record ID")?;
        let digest = bytes_digest(bytes)?;
        let persisted_at = if persisted_at.is_some() {
            persisted_at
        } else {
            let existing: Option<(String, Vec<u8>, i64)> = store
                .connection
                .query_row(
                    "SELECT record_sha256,record_bytes,created_commit_seq
                     FROM wave5_operational_record_v1 WHERE record_id=?1",
                    [record_id.as_str()],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                )
                .optional()?;
            let exact = existing.filter(|(raw, exact, _)| {
                raw_digest(&digest, "operational record").ok() == Some(raw.as_str())
                    && exact == bytes
            });
            exact
                .map(|(_, _, seq)| as_u64(seq, "operational retry commit").map(CommitSeq::new))
                .transpose()?
        };
        stable(&document.component, "operational component")?;
        if !matches!(
            document.component.as_str(),
            "supervisor"
                | "source"
                | "evidence_queue"
                | "spool"
                | "replica"
                | "catalog"
                | "normalizer"
                | "projection"
                | "glass"
                | "export"
                | "analysis"
                | "host"
        ) {
            return Err(StoreError::InvalidBatch(
                "operational component is outside the finite Wave 5 vocabulary".into(),
            ));
        }
        resolve_run(
            store,
            &document.run_registration_id,
            &document.run_registration_digest,
        )?;
        if document.observed_at > context.committed_at {
            return Err(StoreError::InvalidBatch(
                "operational observation cannot be committed before it was observed".into(),
            ));
        }
        if let Some(value) = &document.detail_digest {
            qualified_digest(value, "operational detail")?;
        }
        if let Some(value) = &document.cause {
            stable(value, "operational cause")?;
            if !matches!(
                value.as_str(),
                "source_disconnected"
                    | "rate_limited"
                    | "authentication_rejected"
                    | "schema_drift"
                    | "malformed_evidence"
                    | "queue_pressure"
                    | "spool_pressure"
                    | "disk_floor"
                    | "catalog_unavailable"
                    | "replica_unavailable"
                    | "replica_corrupt"
                    | "projection_stale"
                    | "glass_capture_unavailable"
                    | "export_stale"
                    | "resource_ceiling"
                    | "clock_uncertain"
            ) {
                return Err(StoreError::InvalidBatch(
                    "operational cause is outside the finite Wave 5 vocabulary".into(),
                ));
            }
        }
        let evidence_commit = document
            .evidence_commit_seq
            .as_deref()
            .map(|value| parse_positive_wire(value, "evidence commit").map(CommitSeq::new))
            .transpose()?;
        if !matches!(document.kind, Wave5OperationalRecordKind::RecoveryVerified)
            && (evidence_commit.is_some() || document.detail_digest.is_some())
        {
            return Err(StoreError::InvalidBatch(
                "only a verified recovery may carry durable evidence authority".into(),
            ));
        }
        if let Some(commit) = evidence_commit {
            require_commit(store, commit)?;
            if persisted_at.is_some_and(|cutoff| commit.get() >= cutoff.get()) {
                return Err(StoreError::InvalidBatch(
                    "recovery evidence must precede its operational occurrence".into(),
                ));
            }
            let evidence_wall: i64 = store.connection.query_row(
                "SELECT committed_wall_us FROM ingest_commit WHERE commit_seq=?1",
                [sqlite_u64(commit.get(), "recovery evidence commit")?],
                |row| row.get(0),
            )?;
            let evidence_at = timestamp_from_us(evidence_wall, "recovery evidence time")?;
            if evidence_at > document.observed_at || evidence_at > context.committed_at {
                return Err(StoreError::InvalidBatch(
                    "recovery evidence time must not follow observation or store commit time"
                        .into(),
                ));
            }
        }
        resolve_operational_detail(store, &document, evidence_commit)?;
        validate_operational_predecessor(store, &document, evidence_commit, persisted_at)?;
        Ok(Self {
            document,
            bytes: bytes.to_vec(),
            digest,
            record_id,
            evidence_commit,
        })
    }
}

impl ExportCapability {
    fn parse(store: &SqliteStore, bytes: &[u8]) -> Result<Self> {
        let document: Wave5ExportValidationBindingV1 =
            parse_canonical(bytes, MAX_CONTROL_BYTES, "export validation binding")?;
        require_header(
            &document.contract,
            document.schema_version,
            EXPORT_BINDING_CONTRACT,
        )?;
        require_authority(&document.authority)?;
        let binding_id = stable(&document.export_binding_id, "export binding ID")?;
        let run_seq = resolve_run(
            store,
            &document.run_registration_id,
            &document.run_registration_digest,
        )?;
        let row: Option<ExportResolutionRow> = store
            .connection
            .query_row(
                "SELECT e.validation_id,e.snapshot_id,e.snapshot_manifest_sha256,
                        v.rust_validation_sha256,v.python_validation_sha256,v.validation_sha256,
                        v.validation_bytes,e.truth_fingerprint_sha256,e.created_commit_seq
                 FROM production_export_request_v2 e
                 JOIN export_validation v ON v.validation_id=e.validation_id
                 WHERE e.export_request_id=?1",
                [&document.export_request_id],
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
        let Some(row) = row else {
            return Err(StoreError::MissingIdentity {
                kind: "production export request",
                identity: document.export_request_id.clone(),
            });
        };
        let expected = (
            document.validation_id.as_str(),
            document.snapshot_id.as_str(),
            raw_digest_str(&document.manifest_digest, "export manifest")?,
            raw_digest_str(&document.rust_validation_digest, "Rust validation")?,
            raw_digest_str(&document.python_validation_digest, "Python validation")?,
            raw_digest_str(&document.validation_digest, "export validation")?,
            raw_digest_str(&document.truth_fingerprint, "truth fingerprint")?,
        );
        if (
            row.0.as_str(),
            row.1.as_str(),
            row.2.as_str(),
            row.3.as_str(),
            row.4.as_str(),
            row.5.as_str(),
            row.7.as_str(),
        ) != expected
            || bytes_digest(&row.6)?
                != qualified_digest(&document.validation_digest, "export validation")?
            || as_u64(row.8, "export creation commit")? <= run_seq.get()
        {
            return Err(StoreError::InvalidBatch(
                "export binding does not close the registered run and exact validated snapshot"
                    .into(),
            ));
        }
        Ok(Self {
            document,
            bytes: bytes.to_vec(),
            digest: bytes_digest(bytes)?,
            binding_id,
        })
    }
}

impl ArtifactCapability {
    fn parse(
        store: &SqliteStore,
        registration_bytes: &[u8],
        manifest_bytes: &[u8],
        artifact_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<Self> {
        if artifact_bytes.is_empty() || artifact_bytes.len() > MAX_ARTIFACT_BYTES {
            return Err(StoreError::InvalidBatch(
                "restricted artifact bytes are empty or exceed the Wave 5 bound".into(),
            ));
        }
        let mut value = Self::parse_registration_only(registration_bytes, manifest_bytes)?;
        let actual = bytes_digest(artifact_bytes)?;
        if actual != value.artifact_digest
            || u64::try_from(artifact_bytes.len()).unwrap_or(u64::MAX)
                != parse_wire(
                    &value.manifest.artifacts[0].byte_length,
                    "artifact part byte length",
                )?
        {
            return Err(StoreError::InvalidBatch(
                "artifact part closure differs from exact artifact bytes".into(),
            ));
        }
        validate_artifact_commit_cutoff(&value, context)?;
        resolve_artifact_inputs(store, &value.document, &value.manifest)?;
        value.artifact_bytes = artifact_bytes.to_vec();
        Ok(value)
    }

    fn parse_registration_only(registration_bytes: &[u8], manifest_bytes: &[u8]) -> Result<Self> {
        let document: Wave5RestrictedArtifactRegistrationV1 = parse_canonical(
            registration_bytes,
            MAX_CONTROL_BYTES,
            "restricted artifact registration",
        )?;
        require_header(
            &document.contract,
            document.schema_version,
            RESTRICTED_ARTIFACT_CONTRACT,
        )?;
        require_authority(&document.authority)?;
        let import_id = stable(&document.import_id, "artifact import ID")?;
        stable(&document.analysis_run_id, "analysis run ID")?;
        if document.import_id == document.analysis_run_id
            || document.import_id == document.artifact_id
            || document.analysis_run_id == document.artifact_id
            || document.claim_scope != "descriptive_noncausal"
            || document.artifact_contract != DERIVED_ARTIFACT_CONTRACT
        {
            return Err(StoreError::InvalidBatch(
                "restricted import identities/claim/contract exceed the finite descriptive V2 boundary"
                    .into(),
            ));
        }
        let manifest_digest = qualified_digest(&document.manifest_digest, "artifact manifest")?;
        if bytes_digest(manifest_bytes)? != manifest_digest {
            return Err(StoreError::InvalidBatch(
                "artifact manifest digest differs from exact manifest bytes".into(),
            ));
        }
        let manifest = parse_derived_manifest(manifest_bytes)?;
        let maximum_input_available_at = canonical_timestamp(
            &manifest.fit.maximum_input_available_at,
            "maximum input availability",
        )?;
        if document.analysis_run_id != manifest.analysis_run_id
            || document.artifact_id != manifest.artifact_id
            || document.snapshot_id != manifest.input.snapshot_id
            || document.maximum_input_available_at != maximum_input_available_at
            || document.claim_scope != manifest.display_class
        {
            return Err(StoreError::InvalidBatch(
                "restricted registration differs from its strict derived-artifact manifest".into(),
            ));
        }
        qualified_digest(&document.artifact_id, "artifact ID")?;
        let artifact_digest = qualified_digest(
            &manifest.artifacts[0].physical_digest,
            "artifact part physical digest",
        )?;
        qualified_digest(&document.run_registration_digest, "run registration")?;
        qualified_digest(&document.truth_fingerprint, "truth fingerprint")?;
        Ok(Self {
            document,
            bytes: registration_bytes.to_vec(),
            digest: bytes_digest(registration_bytes)?,
            import_id,
            manifest_bytes: manifest_bytes.to_vec(),
            manifest,
            artifact_bytes: Vec::new(),
            artifact_digest,
        })
    }
}

fn validate_artifact_commit_cutoff(
    capability: &ArtifactCapability,
    context: &Wave5CommitContext,
) -> Result<()> {
    let fit_cutoff =
        canonical_timestamp(&capability.manifest.fit.fit_cutoff, "artifact fit cutoff")?;
    if capability.document.maximum_input_available_at > fit_cutoff
        || fit_cutoff > context.committed_at
    {
        return Err(StoreError::InvalidBatch(
            "artifact input/fit cutoff is later than its store-owned commit time".into(),
        ));
    }
    Ok(())
}

fn validate_artifact_part_capability(
    capability: &ArtifactCapability,
    part_path: &std::path::Path,
) -> Result<()> {
    let validated: ValidatedDerivedArtifactV2 =
        validate_derived_artifact_v2_part(&capability.manifest_bytes, part_path).map_err(
            |error| {
                StoreError::InvalidBatch(format!(
                    "restricted artifact failed independent Parquet validation: {error}"
                ))
            },
        )?;
    if validated.manifest_bytes() != capability.manifest_bytes
        || validated.manifest_digest() != &bytes_digest(&capability.manifest_bytes)?
        || validated.analysis_run_id().as_str() != capability.document.analysis_run_id
        || validated.artifact_id().as_str() != capability.document.artifact_id
        || validated.snapshot_id().as_str() != capability.document.snapshot_id
        || validated.fit_cutoff()
            != canonical_timestamp(&capability.manifest.fit.fit_cutoff, "artifact fit cutoff")?
        || validated.maximum_input_available_at() != capability.document.maximum_input_available_at
        || validated.part().physical_digest() != &capability.artifact_digest
    {
        return Err(StoreError::InvalidBatch(
            "independent Parquet capability differs from the store registration closure".into(),
        ));
    }
    Ok(())
}

fn validate_spool_receipt(
    store: &SqliteStore,
    receipt: &SpoolCatalogReceiptWire,
    segment_bytes: &[u8],
    batch_bytes: &[u8],
    policy_bytes: &[u8],
) -> Result<()> {
    require_header(
        &receipt.contract,
        receipt.schema_version,
        SPOOL_RECEIPT_CONTRACT,
    )?;
    require_authority(&receipt.authority)?;
    stable(&receipt.segment_id, "segment ID")?;
    stable(&receipt.protection_domain, "protection domain")?;
    stable(&receipt.batch.batch_id, "batch ID")?;
    verify_closure(&receipt.exact_segment, segment_bytes, "segment")?;
    verify_closure(&receipt.batch.exact_batch, batch_bytes, "batch")?;
    verify_closure(&receipt.batch.exact_policy, policy_bytes, "policy")?;
    let segment: DiskSegmentWire =
        parse_canonical(segment_bytes, MAX_ARTIFACT_BYTES, "spool segment")?;
    validate_segment_envelope(&segment, receipt)?;
    let batch: DurableIngestBatch = parse_canonical(batch_bytes, MAX_INGEST_BATCH_BYTES, "batch")?;
    let logical = SqliteStore::canonical_batch_digest(&batch)?;
    if batch.batch_id.as_str() != receipt.batch.batch_id
        || logical.as_str() != receipt.batch.logical_batch_digest
        || batch.expected_digest.as_str() != receipt.batch.logical_batch_digest
    {
        return Err(StoreError::InvalidBatch(
            "spool receipt does not close exact logical batch bytes".into(),
        ));
    }
    let catalog = &receipt.catalog_receipt;
    require_header(
        &catalog.contract,
        catalog.schema_version,
        STORE_RECEIPT_CONTRACT,
    )?;
    if receipt.status != catalog.status
        || catalog.catalog_id != store.config.catalog_id.as_str()
        || catalog.batch_id != receipt.batch.batch_id
        || catalog.batch_digest != receipt.batch.logical_batch_digest
        || catalog.store_admission_digest != receipt.batch.store_admission_digest
        || catalog.commit_seq != catalog.from_commit_seq
        || catalog.commit_seq != catalog.through_commit_seq
    {
        return Err(StoreError::InvalidBatch(
            "spool receipt does not close exact catalog receipt".into(),
        ));
    }
    let seq = sqlite_wire_u64(&catalog.commit_seq, "catalog receipt commit")?;
    let stored: Option<(String, String, i64, String, String, String)> = store
        .connection
        .query_row(
            "SELECT commit_id,commit_digest,committed_wall_us,writer_clock_id,
                    committed_mono_ns,writer_build FROM ingest_commit
             WHERE commit_seq=?1 AND commit_class='ingest'",
            [seq],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                ))
            },
        )
        .optional()?;
    let Some((batch_id, admission, committed_wall, writer_clock, committed_mono, writer_build)) =
        stored
    else {
        return Err(StoreError::MissingIdentity {
            kind: "ingest commit",
            identity: catalog.commit_seq.clone(),
        });
    };
    if batch_id != catalog.batch_id
        || admission != raw_digest_str(&catalog.store_admission_digest, "store admission")?
    {
        return Err(StoreError::InvalidBatch(
            "catalog receipt differs from durable ingest commit".into(),
        ));
    }
    let policy = validate_pump_policy(
        store,
        policy_bytes,
        &batch,
        seq,
        committed_wall,
        &writer_clock,
        &committed_mono,
        &writer_build,
    )?;
    if segment.header.created_at
        > canonical_timestamp(&policy.committed_at, "Pump physical-policy commit time")?
    {
        return Err(StoreError::InvalidBatch(
            "spool segment was created after its closed ingest policy".into(),
        ));
    }
    validate_policy_protection(&policy, receipt.protection_class)?;
    let expected_admission = admission_digest_from_policy(&batch, &policy)?;
    if expected_admission.as_str() != receipt.batch.store_admission_digest {
        return Err(StoreError::InvalidBatch(
            "exact physical policy does not derive the durable store admission digest".into(),
        ));
    }
    let expected_counts = derived_counts(&batch)?;
    validate_durable_batch_membership(store, &batch, seq)?;
    if !counts_match_receipt(&expected_counts, &catalog.admitted)? {
        return Err(StoreError::InvalidBatch(
            "catalog receipt counts differ from exact batch or durable rows".into(),
        ));
    }
    let acquisition_ids = batch
        .observations
        .iter()
        .map(|item| item.acquisition.acquisition_id.to_string())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    if catalog.acquisition_ids != acquisition_ids {
        return Err(StoreError::InvalidBatch(
            "catalog receipt acquisition IDs differ from exact batch".into(),
        ));
    }
    validate_gap_outcomes(store, &batch, &policy, &catalog.gap_outcomes, seq)?;
    validate_segment_batch_membership(
        &segment,
        receipt,
        &batch,
        batch_bytes,
        policy_bytes,
        &expected_counts,
    )?;
    Ok(())
}

fn validate_segment_envelope(
    segment: &DiskSegmentWire,
    receipt: &SpoolCatalogReceiptWire,
) -> Result<()> {
    if segment.header.contract != SPOOL_SEGMENT_CONTRACT
        || segment.header.segment_id != receipt.segment_id
        || segment.header.domain != receipt.protection_domain
    {
        return Err(StoreError::InvalidBatch(
            "spool segment header differs from its catalog receipt".into(),
        ));
    }
    stable(&segment.header.segment_id, "segment ID")?;
    stable(&segment.header.domain, "segment protection domain")?;
    qualified_digest(&segment.header.body.digest, "segment plaintext body")?;
    if segment.header.body.byte_len == 0 || segment.header.sealed_body.byte_len == 0 {
        return Err(StoreError::InvalidBatch(
            "spool segment body closures must be nonempty".into(),
        ));
    }
    let sealed = decode_base64(&segment.sealed_body_bytes, "sealed segment body")?;
    verify_segment_closure(&segment.header.sealed_body, &sealed, "sealed segment body")?;
    validate_supported_segment_protection(&segment.header.protection, receipt.protection_class)?;
    if segment.header.body != segment.header.sealed_body {
        return Err(StoreError::InvalidBatch(
            "public-integrity segment body and sealed-body closures differ".into(),
        ));
    }
    Ok(())
}

fn validate_supported_segment_protection(
    protection: &SegmentProtectionWire,
    receipt_class: WireProtectionClass,
) -> Result<()> {
    match (protection, receipt_class) {
        (SegmentProtectionWire::PublicIntegrity, WireProtectionClass::PublicIntegrity) => Ok(()),
        (
            SegmentProtectionWire::AuthenticatedPrivate { .. },
            WireProtectionClass::AuthenticatedPrivate,
        ) => Err(StoreError::InvalidBatch(
            "authenticated-private spool admission is unavailable until the store can verify the AEAD tag and reconstructed plaintext"
                .into(),
        )),
        _ => Err(StoreError::InvalidBatch(
            "segment protection class differs from its receipt".into(),
        )),
    }
}

fn validate_segment_batch_membership(
    segment: &DiskSegmentWire,
    receipt: &SpoolCatalogReceiptWire,
    batch: &DurableIngestBatch,
    batch_bytes: &[u8],
    policy_bytes: &[u8],
    counts: &SegmentExpectedCountsWire,
) -> Result<()> {
    if segment.header.entries.len() != 1 {
        return Err(StoreError::InvalidBatch(
            "Wave 5 spool admission requires one closed batch per segment".into(),
        ));
    }
    let descriptor = &segment.header.entries[0];
    let Some(closure) = &descriptor.batch else {
        return Err(StoreError::InvalidBatch(
            "spool segment omits its exact batch membership closure".into(),
        ));
    };
    qualified_digest(&descriptor.exact_entry.digest, "spool entry")?;
    if descriptor.ordinal != 0
        || descriptor.kind != "evidence_batch"
        || descriptor.occurrence_id != format!("batch:{}", receipt.batch.batch_id)
        || descriptor.exact_entry.byte_len == 0
        || closure.batch_id != receipt.batch.batch_id
        || closure.logical_digest != receipt.batch.logical_batch_digest
        || closure.policy_contract != PUMP_POLICY_CONTRACT
        // The immutable origin segment is sealed before store commit, so it cannot contain the
        // later store-owned admission digest. That digest is bound by the exact catalog receipt
        // and the separately durable CatalogAdmissionAck instead.
        || closure.admission_digest.is_some()
        || closure.counts != *counts
        || closure.exact_batch.digest != receipt.batch.exact_batch.digest
        || closure.exact_batch.byte_len
            != parse_wire(&receipt.batch.exact_batch.byte_length, "exact batch length")?
        || closure.exact_policy.digest != receipt.batch.exact_policy.digest
        || closure.exact_policy.byte_len
            != parse_wire(
                &receipt.batch.exact_policy.byte_length,
                "exact policy length",
            )?
    {
        return Err(StoreError::InvalidBatch(
            "spool segment batch descriptor differs from exact admitted material".into(),
        ));
    }
    let acquisition_ids = batch
        .observations
        .iter()
        .map(|item| item.acquisition.acquisition_id.to_string())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let gap_ids = batch
        .coverage_gaps
        .iter()
        .map(|gap| gap.gap_id.to_string())
        .collect::<Vec<_>>();
    if closure.acquisition_ids != acquisition_ids || closure.gap_ids != gap_ids {
        return Err(StoreError::InvalidBatch(
            "spool descriptor public ID sets differ from exact batch".into(),
        ));
    }
    let source_occurrences = batch
        .observations
        .iter()
        .map(|item| SegmentSourceOccurrenceWire {
            source_id: item.acquisition.source_id.to_string(),
            acquisition_id: item.acquisition.acquisition_id.to_string(),
        })
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    if segment.header.source_occurrences != source_occurrences {
        return Err(StoreError::InvalidBatch(
            "spool source-occurrence membership differs from exact batch".into(),
        ));
    }
    let cursor_candidates = batch
        .cursor_advances
        .iter()
        .map(|cursor| SegmentCursorCandidateWire {
            cursor_id: cursor.cursor_id.to_string(),
            scope: &cursor.scope,
            cursor_kind: &cursor.cursor_kind,
            cursor_value: &cursor.cursor_value,
            acquisition_id: cursor.acquisition_id.to_string(),
            primary_observation_id: cursor.primary_observation_id.to_string(),
            evidence_observation_ids: cursor.evidence.iter().map(ToString::to_string).collect(),
            predecessor_cursor_id: cursor
                .predecessor_cursor_id
                .as_ref()
                .map(ToString::to_string),
        })
        .collect();
    let exact_entry = serde_json::to_vec(&SegmentSpoolEntryWire::EvidenceBatch(
        SegmentEvidenceBatchEntryWire {
            closure,
            exact_batch_bytes: encode_base64(batch_bytes),
            exact_policy_bytes: encode_base64(policy_bytes),
            cursor_candidates,
        },
    ))?;
    verify_segment_closure(&descriptor.exact_entry, &exact_entry, "spool batch entry")?;
    let mut framed = Vec::with_capacity(exact_entry.len().saturating_add(8));
    framed.extend_from_slice(
        &u64::try_from(exact_entry.len())
            .map_err(|_| StoreError::IntegerRange {
                field: "spool entry byte length",
                value: exact_entry.len().to_string(),
            })?
            .to_be_bytes(),
    );
    framed.extend_from_slice(&exact_entry);
    verify_segment_closure(&segment.header.body, &framed, "spool plaintext body")?;
    let sealed = decode_base64(&segment.sealed_body_bytes, "sealed segment body")?;
    match &segment.header.protection {
        SegmentProtectionWire::PublicIntegrity if sealed != framed => {
            return Err(StoreError::InvalidBatch(
                "public spool body differs from its exact reconstructed entry".into(),
            ));
        }
        _ => {}
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_pump_policy(
    store: &SqliteStore,
    policy_bytes: &[u8],
    batch: &DurableIngestBatch,
    commit_seq: i64,
    committed_wall: i64,
    writer_clock: &str,
    committed_mono: &str,
    writer_build: &str,
) -> Result<PumpPhysicalPolicyWire> {
    let policy: PumpPhysicalPolicyWire =
        parse_canonical(policy_bytes, MAX_CONTROL_BYTES, "Pump physical policy")?;
    if policy.contract != PUMP_POLICY_CONTRACT
        || timestamp_us(
            policy
                .committed_at
                .parse()
                .map_err(|_| StoreError::InvalidBatch("invalid policy commit timestamp".into()))?,
            "policy commit timestamp",
        )? != committed_wall
        || policy.writer_clock_id != writer_clock
        || policy.committed_monotonic_ns != committed_mono
        || policy.writer_build != writer_build
    {
        return Err(StoreError::InvalidBatch(
            "exact physical policy does not close the durable ingest writer context".into(),
        ));
    }
    let observation_ids = batch
        .observations
        .iter()
        .map(|item| item.observation.observation_id.to_string())
        .collect::<BTreeSet<_>>();
    if policy
        .observation_storage
        .keys()
        .map(String::as_str)
        .ne(observation_ids.iter().map(String::as_str))
    {
        return Err(StoreError::InvalidBatch(
            "physical policy observation set differs from exact batch".into(),
        ));
    }
    for (observation_id, entry) in &policy.observation_storage {
        if !matches!(
            entry.retention_class.as_str(),
            "public_chain"
                | "public_source"
                | "social_media"
                | "app_private"
                | "operator_private"
                | "fixture"
                | "disposable"
        ) {
            return Err(StoreError::InvalidBatch(
                "physical policy contains an unsupported retention class".into(),
            ));
        }
        let durable: Option<(String, Option<String>)> = store
            .connection
            .query_row(
                "SELECT c.retention_class,c.content_encoding
                 FROM observation o JOIN observation_blob_contract c
                   ON c.observation_id=o.observation_id
                 WHERE o.observation_id=?1 AND o.commit_seq<=?2",
                params![observation_id, commit_seq],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        if durable.as_ref()
            != Some(&(
                entry.retention_class.clone(),
                entry.content_encoding.clone(),
            ))
        {
            return Err(StoreError::InvalidBatch(
                "physical policy differs from durable observation storage".into(),
            ));
        }
    }
    let gap_ids = batch
        .coverage_gaps
        .iter()
        .map(|gap| gap.gap_id.to_string())
        .collect::<BTreeSet<_>>();
    if policy
        .coverage_gap_severity
        .keys()
        .map(String::as_str)
        .ne(gap_ids.iter().map(String::as_str))
    {
        return Err(StoreError::InvalidBatch(
            "physical policy gap set differs from exact batch".into(),
        ));
    }
    Ok(policy)
}

fn admission_digest_from_policy(
    batch: &DurableIngestBatch,
    policy: &PumpPhysicalPolicyWire,
) -> Result<ValueDigest> {
    #[derive(Serialize)]
    struct Material<'a> {
        contract: &'static str,
        logical_batch_digest: &'a str,
        observation_storage: &'a BTreeMap<String, ObservationStorage>,
        coverage_gap_severity: &'a BTreeMap<String, StableString>,
    }
    let observation_storage = policy
        .observation_storage
        .iter()
        .map(|(id, entry)| {
            Ok((
                id.clone(),
                ObservationStorage {
                    retention_class: stable(&entry.retention_class, "retention class")?,
                    content_encoding: entry
                        .content_encoding
                        .as_deref()
                        .map(|value| stable(value, "content encoding"))
                        .transpose()?,
                    force_external: entry.force_external,
                },
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    let coverage_gap_severity = policy
        .coverage_gap_severity
        .iter()
        .map(|(id, severity)| Ok((id.clone(), stable(severity, "coverage gap severity")?)))
        .collect::<Result<BTreeMap<_, _>>>()?;
    let bytes = serde_json::to_vec(&Material {
        contract: "joshi.store.admission.v1",
        logical_batch_digest: batch.expected_digest.as_str(),
        observation_storage: &observation_storage,
        coverage_gap_severity: &coverage_gap_severity,
    })?;
    bytes_digest(&bytes)
}

fn validate_policy_protection(
    policy: &PumpPhysicalPolicyWire,
    protection: WireProtectionClass,
) -> Result<()> {
    let contains_nonpublic = policy.observation_storage.values().any(|entry| {
        !matches!(
            entry.retention_class.as_str(),
            "public_chain" | "public_source" | "fixture"
        )
    });
    if contains_nonpublic && protection != WireProtectionClass::AuthenticatedPrivate {
        return Err(StoreError::InvalidBatch(
            "nonpublic retention policy requires authenticated-private spool protection".into(),
        ));
    }
    Ok(())
}

fn derived_counts(batch: &DurableIngestBatch) -> Result<SegmentExpectedCountsWire> {
    let acquisitions = batch
        .observations
        .iter()
        .map(|item| item.acquisition.acquisition_id.to_string())
        .collect::<BTreeSet<_>>()
        .len();
    let raw_blobs = batch
        .observations
        .iter()
        .map(|item| bytes_digest(&item.payload).map(|digest| digest.to_string()))
        .collect::<Result<BTreeSet<_>>>()?
        .len();
    let raw_bytes = batch.observations.iter().try_fold(0_u64, |sum, item| {
        sum.checked_add(u64::try_from(item.payload.len()).map_err(|_| {
            StoreError::IntegerRange {
                field: "observation payload length",
                value: item.payload.len().to_string(),
            }
        })?)
        .ok_or_else(|| StoreError::IntegerRange {
            field: "batch raw byte sum",
            value: "overflow".into(),
        })
    })?;
    Ok(SegmentExpectedCountsWire {
        acquisitions: count_u64(acquisitions, "acquisitions")?,
        raw_blobs: count_u64(raw_blobs, "raw blobs")?,
        raw_bytes,
        observations: count_u64(batch.observations.len(), "observations")?,
        source_events: count_u64(batch.source_events.len(), "source events")?,
        assertions: count_u64(batch.assertions.len(), "assertions")?,
        coverage_windows: count_u64(batch.coverage_windows.len(), "coverage windows")?,
        coverage_gaps: count_u64(batch.coverage_gaps.len(), "coverage gaps")?,
        coverage_recoveries: count_u64(batch.coverage_recoveries.len(), "coverage recoveries")?,
        cursor_advances: count_u64(batch.cursor_advances.len(), "cursor advances")?,
    })
}

fn validate_durable_batch_membership(
    store: &SqliteStore,
    batch: &DurableIngestBatch,
    maximum_commit_seq: i64,
) -> Result<()> {
    for draft in &batch.observations {
        let observation_id = draft.observation.observation_id.as_str();
        let durable: Option<(i64, i64, String, String, String, i64)> = store
            .connection
            .query_row(
                "SELECT o.commit_seq,a.registered_commit_seq,o.acquisition_id,o.source_id,
                        o.blob_id,b.content_length
                 FROM observation o
                 JOIN acquisition a ON a.acquisition_id=o.acquisition_id
                 JOIN blob b ON b.blob_id=o.blob_id
                 WHERE o.observation_id=?1",
                [observation_id],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )
            .optional()?;
        let Some((observed_seq, acquisition_seq, acquisition_id, source_id, blob_id, byte_len)) =
            durable
        else {
            return Err(StoreError::MissingIdentity {
                kind: "durable observation",
                identity: observation_id.to_owned(),
            });
        };
        let payload_digest = bytes_digest(&draft.payload)?;
        if observed_seq > maximum_commit_seq
            || acquisition_seq > maximum_commit_seq
            || acquisition_id != draft.acquisition.acquisition_id.as_str()
            || source_id != draft.acquisition.source_id.as_str()
            || blob_id != raw_digest_str(payload_digest.as_str(), "observation payload")?
            || as_u64(byte_len, "durable observation byte length")?
                != u64::try_from(draft.payload.len()).map_err(|_| StoreError::IntegerRange {
                    field: "observation payload length",
                    value: draft.payload.len().to_string(),
                })?
        {
            return Err(StoreError::InvalidBatch(
                "durable observation/acquisition/blob closure differs from exact batch".into(),
            ));
        }
    }
    for event in &batch.source_events {
        require_identity_at_or_before(
            store,
            "SELECT identified_commit_seq FROM source_event WHERE source_event_id=?1",
            event.source_event_id.as_str(),
            maximum_commit_seq,
            "durable source event",
        )?;
    }
    for assertion in &batch.assertions {
        require_identity_at_or_before(
            store,
            "SELECT produced_commit_seq FROM assertion WHERE assertion_id=?1",
            assertion.assertion_id.as_str(),
            maximum_commit_seq,
            "durable assertion",
        )?;
    }
    for window in &batch.coverage_windows {
        require_identity_at_or_before(
            store,
            "SELECT opened_commit_seq FROM coverage_window WHERE coverage_id=?1",
            window.coverage_id.as_str(),
            maximum_commit_seq,
            "durable coverage window",
        )?;
    }
    for gap in &batch.coverage_gaps {
        require_identity_at_or_before(
            store,
            "SELECT detected_commit_seq FROM coverage_gap WHERE gap_id=?1",
            gap.gap_id.as_str(),
            maximum_commit_seq,
            "durable coverage gap",
        )?;
    }
    for recovery in &batch.coverage_recoveries {
        require_identity_at_or_before(
            store,
            "SELECT commit_seq FROM coverage_gap_recovery WHERE recovery_id=?1",
            recovery.recovery_id.as_str(),
            maximum_commit_seq,
            "durable coverage recovery",
        )?;
    }
    for cursor in &batch.cursor_advances {
        require_identity_at_or_before(
            store,
            "SELECT advanced_commit_seq FROM source_cursor WHERE cursor_id=?1",
            cursor.cursor_id.as_str(),
            maximum_commit_seq,
            "durable cursor advance",
        )?;
    }
    Ok(())
}

fn require_identity_at_or_before(
    store: &SqliteStore,
    query: &'static str,
    identity: &str,
    maximum_commit_seq: i64,
    kind: &'static str,
) -> Result<()> {
    let sequence: Option<i64> = store
        .connection
        .query_row(query, [identity], |row| row.get(0))
        .optional()?;
    let Some(sequence) = sequence else {
        return Err(StoreError::MissingIdentity {
            kind,
            identity: identity.to_owned(),
        });
    };
    if sequence > maximum_commit_seq {
        return Err(StoreError::InvalidBatch(format!(
            "{kind} is later than the closed catalog receipt"
        )));
    }
    Ok(())
}

fn counts_match_receipt(
    expected: &SegmentExpectedCountsWire,
    actual: &PublicAdmittedCountsWire,
) -> Result<bool> {
    Ok(
        expected.acquisitions == parse_wire(&actual.acquisitions, "acquisitions")?
            && expected.raw_blobs == parse_wire(&actual.raw_blobs, "raw blobs")?
            && expected.raw_bytes == parse_wire(&actual.raw_bytes, "raw bytes")?
            && expected.observations == parse_wire(&actual.observations, "observations")?
            && expected.source_events == parse_wire(&actual.source_events, "source events")?
            && expected.assertions == parse_wire(&actual.assertions, "assertions")?
            && expected.coverage_windows
                == parse_wire(&actual.coverage_windows, "coverage windows")?
            && expected.coverage_gaps == parse_wire(&actual.coverage_gaps, "coverage gaps")?
            && expected.coverage_recoveries
                == parse_wire(&actual.coverage_recoveries, "coverage recoveries")?
            && expected.cursor_advances == parse_wire(&actual.cursor_advances, "cursor advances")?,
    )
}

fn validate_gap_outcomes(
    store: &SqliteStore,
    batch: &DurableIngestBatch,
    policy: &PumpPhysicalPolicyWire,
    outcomes: &[PublicGapOutcomeWire],
    commit_seq: i64,
) -> Result<()> {
    if outcomes.len() != batch.coverage_gaps.len() {
        return Err(StoreError::InvalidBatch(
            "catalog receipt gap count differs from exact batch".into(),
        ));
    }
    for (gap, outcome) in batch.coverage_gaps.iter().zip(outcomes) {
        let expected_scope = public_scope(&gap.scope);
        let expected_lower = public_boundary(&gap.lower);
        let expected_upper = gap.upper.as_ref().map(public_boundary);
        if outcome.gap_id != gap.gap_id.as_str()
            || outcome.scope != expected_scope
            || outcome.lower != expected_lower
            || outcome.upper != expected_upper
            || outcome.outcome != "recorded"
        {
            return Err(StoreError::InvalidBatch(
                "catalog gap outcome differs from exact batch semantics".into(),
            ));
        }
        let durable: Option<DurableGapResolution> = store
            .connection
            .query_row(
                "SELECT g.detected_commit_seq,g.severity,c.scope_source_id,c.scope_family,
                            c.scope_subject,c.lower_boundary_json,c.upper_boundary_json
                     FROM coverage_gap g JOIN coverage_gap_contract c ON c.gap_id=g.gap_id
                     WHERE g.gap_id=?1",
                [gap.gap_id.as_str()],
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
        let Some((seq, severity, source, family, subject, lower, upper)) = durable else {
            return Err(StoreError::MissingIdentity {
                kind: "durable coverage gap",
                identity: gap.gap_id.to_string(),
            });
        };
        if seq > commit_seq
            || policy.coverage_gap_severity.get(gap.gap_id.as_str()) != Some(&severity)
            || source != gap.scope.source_id.as_str()
            || family != gap.scope.family.discriminator.as_str()
            || subject.as_deref() != gap.scope.subject.as_ref().map(StableString::as_str)
            || lower != serde_json::to_string(&gap.lower)?
            || upper != gap.upper.as_ref().map(serde_json::to_string).transpose()?
        {
            return Err(StoreError::InvalidBatch(
                "durable coverage gap differs from exact batch or physical policy".into(),
            ));
        }
    }
    Ok(())
}

fn public_scope(value: &CoverageScope) -> PublicCoverageScopeWire {
    PublicCoverageScopeWire {
        source_id: value.source_id.to_string(),
        family: value.family.clone(),
        subject: value.subject.as_ref().map(ToString::to_string),
    }
}

fn public_boundary(value: &Boundary) -> PublicBoundaryWire {
    match value {
        Boundary::Wall { value } => PublicBoundaryWire::Wall {
            value: value.to_string(),
        },
        Boundary::Commit { value } => PublicBoundaryWire::Commit {
            value: value.get().to_string(),
        },
        Boundary::SourceCursor { value } => PublicBoundaryWire::SourceCursor {
            value: value.to_string(),
        },
        Boundary::Unknown { reason } => PublicBoundaryWire::Unknown {
            reason: reason.clone(),
        },
    }
}

fn verify_segment_closure(
    closure: &SegmentByteClosureWire,
    bytes: &[u8],
    field: &'static str,
) -> Result<()> {
    if closure.byte_len != u64::try_from(bytes.len()).unwrap_or(u64::MAX)
        || qualified_digest(&closure.digest, field)? != bytes_digest(bytes)?
    {
        return Err(StoreError::InvalidBatch(format!(
            "{field} does not match its exact segment closure"
        )));
    }
    Ok(())
}

fn decode_base64(value: &str, field: &'static str) -> Result<Vec<u8>> {
    if !value.len().is_multiple_of(4) || value.bytes().any(|byte| byte.is_ascii_whitespace()) {
        return Err(StoreError::InvalidBatch(format!(
            "{field} is not canonical base64"
        )));
    }
    let mut output = Vec::with_capacity(value.len().saturating_mul(3) / 4);
    let chunks = value.as_bytes().chunks_exact(4);
    let chunk_count = chunks.len();
    for (index, chunk) in chunks.enumerate() {
        let last = index + 1 == chunk_count;
        let a = base64_digit(chunk[0], field)?;
        let b = base64_digit(chunk[1], field)?;
        let c_pad = chunk[2] == b'=';
        let d_pad = chunk[3] == b'=';
        if !last && (c_pad || d_pad) {
            return Err(StoreError::InvalidBatch(format!(
                "{field} is not canonical base64"
            )));
        }
        if c_pad && (!d_pad || b & 0x0f != 0) {
            return Err(StoreError::InvalidBatch(format!(
                "{field} is not canonical base64"
            )));
        }
        if d_pad && !c_pad && base64_digit(chunk[2], field)? & 0x03 != 0 {
            return Err(StoreError::InvalidBatch(format!(
                "{field} is not canonical base64"
            )));
        }
        let c = if c_pad {
            0
        } else {
            base64_digit(chunk[2], field)?
        };
        let d = if d_pad {
            0
        } else {
            base64_digit(chunk[3], field)?
        };
        output.push((a << 2) | (b >> 4));
        if !c_pad {
            output.push((b << 4) | (c >> 2));
        }
        if !d_pad {
            output.push((c << 6) | d);
        }
    }
    Ok(output)
}

fn encode_base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut encoded = String::with_capacity(bytes.len().div_ceil(3).saturating_mul(4));
    for chunk in bytes.chunks(3) {
        let a = chunk[0];
        let b = chunk.get(1).copied().unwrap_or(0);
        let c = chunk.get(2).copied().unwrap_or(0);
        encoded.push(char::from(ALPHABET[usize::from(a >> 2)]));
        encoded.push(char::from(ALPHABET[usize::from((a & 0x03) << 4 | b >> 4)]));
        encoded.push(if chunk.len() > 1 {
            char::from(ALPHABET[usize::from((b & 0x0f) << 2 | c >> 6)])
        } else {
            '='
        });
        encoded.push(if chunk.len() > 2 {
            char::from(ALPHABET[usize::from(c & 0x3f)])
        } else {
            '='
        });
    }
    encoded
}

fn base64_digit(byte: u8, field: &'static str) -> Result<u8> {
    match byte {
        b'A'..=b'Z' => Ok(byte - b'A'),
        b'a'..=b'z' => Ok(byte - b'a' + 26),
        b'0'..=b'9' => Ok(byte - b'0' + 52),
        b'+' => Ok(62),
        b'/' => Ok(63),
        _ => Err(StoreError::InvalidBatch(format!(
            "{field} is not canonical base64"
        ))),
    }
}

fn count_u64(value: usize, field: &'static str) -> Result<u64> {
    u64::try_from(value).map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn validate_operational_predecessor(
    store: &SqliteStore,
    document: &Wave5OperationalRecordV1,
    evidence_commit: Option<CommitSeq>,
    persisted_at: Option<CommitSeq>,
) -> Result<()> {
    let state_matches_kind = match document.kind {
        Wave5OperationalRecordKind::Status => matches!(
            document.state,
            Wave5OperationalState::Ready
                | Wave5OperationalState::Degraded
                | Wave5OperationalState::Unavailable
                | Wave5OperationalState::Gap
                | Wave5OperationalState::Backlogged
                | Wave5OperationalState::Stale
                | Wave5OperationalState::Refused
        ),
        Wave5OperationalRecordKind::Degradation => matches!(
            document.state,
            Wave5OperationalState::Degraded
                | Wave5OperationalState::Unavailable
                | Wave5OperationalState::Gap
                | Wave5OperationalState::Backlogged
                | Wave5OperationalState::Stale
                | Wave5OperationalState::Refused
        ),
        Wave5OperationalRecordKind::RecoveryStarted => {
            document.state == Wave5OperationalState::Recovering
        }
        Wave5OperationalRecordKind::RecoveryVerified => matches!(
            document.state,
            Wave5OperationalState::Ready | Wave5OperationalState::Degraded
        ),
        Wave5OperationalRecordKind::Stopped => document.state == Wave5OperationalState::Stopped,
    };
    if !state_matches_kind {
        return Err(StoreError::InvalidBatch(
            "operational record kind and state are inconsistent".into(),
        ));
    }
    let requires_predecessor = matches!(
        document.kind,
        Wave5OperationalRecordKind::RecoveryStarted | Wave5OperationalRecordKind::RecoveryVerified
    );
    if requires_predecessor != document.predecessor_record_id.is_some() {
        return Err(StoreError::InvalidBatch(
            "recovery records require exactly one predecessor".into(),
        ));
    }
    if matches!(document.kind, Wave5OperationalRecordKind::Degradation) && document.cause.is_none()
    {
        return Err(StoreError::InvalidBatch(
            "degradation record requires a finite cause".into(),
        ));
    }
    if matches!(document.kind, Wave5OperationalRecordKind::RecoveryVerified)
        && (evidence_commit.is_none() || document.detail_digest.is_none())
    {
        return Err(StoreError::InvalidBatch(
            "verified recovery requires a resolved durable evidence commit and detail digest"
                .into(),
        ));
    }
    if matches!(document.kind, Wave5OperationalRecordKind::RecoveryVerified) {
        let evidence = evidence_commit.ok_or_else(|| {
            StoreError::InvalidBatch("verified recovery has no durable evidence commit".into())
        })?;
        validate_recovery_evidence_semantics(store, document, evidence)?;
    }
    let latest: Option<(String, String, String, i64, i64)> = if let Some(cutoff) = persisted_at {
        store
            .connection
            .query_row(
                "SELECT record_id,record_kind,state,created_commit_seq,observed_wall_us
                 FROM wave5_operational_record_v1
                 WHERE run_registration_id=?1 AND component=?2 AND created_commit_seq<?3
                 ORDER BY created_commit_seq DESC LIMIT 1",
                params![
                    document.run_registration_id,
                    document.component,
                    sqlite_u64(cutoff.get(), "operational readback cutoff")?
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
            .optional()?
    } else {
        store
            .connection
            .query_row(
                "SELECT record_id,record_kind,state,created_commit_seq,observed_wall_us
                 FROM wave5_operational_record_v1
                 WHERE run_registration_id=?1 AND component=?2
                 ORDER BY created_commit_seq DESC LIMIT 1",
                params![document.run_registration_id, document.component],
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
            .optional()?
    };
    if let Some((latest_id, latest_kind, latest_state, _, latest_observed_wall)) = &latest {
        if document.observed_at
            < timestamp_from_us(*latest_observed_wall, "latest operational observation")?
        {
            return Err(StoreError::InvalidBatch(
                "operational observations must be monotonic within one run/component".into(),
            ));
        }
        if latest_state == "stopped" {
            return Err(StoreError::InvalidBatch(
                "a stopped operational component is terminal within one run".into(),
            ));
        }
        if matches!(document.kind, Wave5OperationalRecordKind::Status)
            && (latest_state == "recovering"
                || (document.state == Wave5OperationalState::Ready && latest_state != "ready"))
        {
            return Err(StoreError::InvalidBatch(
                "status cannot bypass the recovery transition into ready".into(),
            ));
        }
        if matches!(document.kind, Wave5OperationalRecordKind::RecoveryStarted)
            && (document.predecessor_record_id.as_deref() != Some(latest_id.as_str())
                || !matches!(
                    latest_state.as_str(),
                    "degraded" | "unavailable" | "gap" | "backlogged" | "stale" | "refused"
                )
                || latest_kind == "recovery_started")
        {
            return Err(StoreError::InvalidBatch(
                "recovery must start from the latest degraded component state".into(),
            ));
        }
        if matches!(document.kind, Wave5OperationalRecordKind::RecoveryVerified)
            && (document.predecessor_record_id.as_deref() != Some(latest_id.as_str())
                || latest_kind != "recovery_started")
        {
            return Err(StoreError::InvalidBatch(
                "verified recovery must close the latest recovery-start occurrence".into(),
            ));
        }
    } else if matches!(
        document.kind,
        Wave5OperationalRecordKind::RecoveryStarted
            | Wave5OperationalRecordKind::RecoveryVerified
            | Wave5OperationalRecordKind::Stopped
    ) || matches!(document.kind, Wave5OperationalRecordKind::Status)
        && document.state == Wave5OperationalState::Ready
    {
        return Err(StoreError::InvalidBatch(
            "ready, recovery, or stopped cannot be the first component occurrence".into(),
        ));
    }
    let Some(predecessor) = &document.predecessor_record_id else {
        return Ok(());
    };
    let row: Option<(String, String, String, i64, i64)> = store
        .connection
        .query_row(
            "SELECT run_registration_id,component,record_kind,created_commit_seq,observed_wall_us
             FROM wave5_operational_record_v1 WHERE record_id=?1",
            [predecessor],
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
    let Some((run, component, predecessor_kind, predecessor_seq, predecessor_observed_wall)) = row
    else {
        return Err(StoreError::MissingIdentity {
            kind: "operational predecessor",
            identity: predecessor.clone(),
        });
    };
    if run != document.run_registration_id || component != document.component {
        return Err(StoreError::InvalidBatch(
            "operational predecessor crosses run or component".into(),
        ));
    }
    let predecessor_observed =
        timestamp_from_us(predecessor_observed_wall, "predecessor observation")?;
    if document.observed_at < predecessor_observed {
        return Err(StoreError::InvalidBatch(
            "operational recovery observation predates its predecessor".into(),
        ));
    }
    if matches!(document.kind, Wave5OperationalRecordKind::RecoveryStarted)
        && predecessor_kind != "degradation"
        && predecessor_kind != "status"
    {
        return Err(StoreError::InvalidBatch(
            "recovery-start predecessor is not a status or degradation occurrence".into(),
        ));
    }
    if matches!(document.kind, Wave5OperationalRecordKind::RecoveryVerified)
        && predecessor_kind != "recovery_started"
    {
        return Err(StoreError::InvalidBatch(
            "verified recovery must follow a recovery-start occurrence".into(),
        ));
    }
    if let Some(value) = evidence_commit {
        if value.get() <= as_u64(predecessor_seq, "predecessor")? {
            return Err(StoreError::InvalidBatch(
                "recovery evidence must follow the predecessor record".into(),
            ));
        }
        let evidence_wall: i64 = store.connection.query_row(
            "SELECT committed_wall_us FROM ingest_commit WHERE commit_seq=?1",
            [sqlite_u64(value.get(), "recovery evidence commit")?],
            |row| row.get(0),
        )?;
        if timestamp_from_us(evidence_wall, "recovery evidence time")? < predecessor_observed {
            return Err(StoreError::InvalidBatch(
                "recovery evidence time predates its predecessor observation".into(),
            ));
        }
    }
    Ok(())
}

fn validate_recovery_evidence_semantics(
    store: &SqliteStore,
    document: &Wave5OperationalRecordV1,
    evidence: CommitSeq,
) -> Result<()> {
    let seq = sqlite_u64(evidence.get(), "recovery evidence commit")?;
    let exists: bool = match document.component.as_str() {
        "spool" => store.connection.query_row(
            "SELECT EXISTS(SELECT 1 FROM wave5_spool_catalog_binding_v1
             WHERE created_commit_seq=?1 AND run_registration_id=?2)",
            params![seq, document.run_registration_id],
            |row| row.get(0),
        )?,
        "export" => store.connection.query_row(
            "SELECT EXISTS(SELECT 1 FROM wave5_export_validation_binding_v1
             WHERE created_commit_seq=?1 AND run_registration_id=?2)",
            params![seq, document.run_registration_id],
            |row| row.get(0),
        )?,
        _ => {
            return Err(StoreError::InvalidBatch(
                "component has no same-run finite durable recovery-evidence resolver".into(),
            ));
        }
    };
    if !exists {
        return Err(StoreError::InvalidBatch(
            "recovery evidence commit is not semantically bound to the component".into(),
        ));
    }
    Ok(())
}

fn resolve_operational_detail(
    store: &SqliteStore,
    document: &Wave5OperationalRecordV1,
    evidence_commit: Option<CommitSeq>,
) -> Result<()> {
    let Some(detail) = &document.detail_digest else {
        return Ok(());
    };
    let raw = raw_digest_str(detail, "operational detail")?;
    let resolved: Option<i64> = store
        .connection
        .query_row(
            "SELECT commit_seq FROM ingest_commit WHERE commit_digest=?1",
            [raw],
            |row| row.get(0),
        )
        .optional()?;
    let Some(resolved) = resolved else {
        return Err(StoreError::MissingIdentity {
            kind: "operational detail commit digest",
            identity: detail.clone(),
        });
    };
    let resolved = as_u64(resolved, "detail commit")?;
    if let Some(value) = evidence_commit
        && value.get() != resolved
    {
        return Err(StoreError::InvalidBatch(
            "operational detail digest does not identify its evidence commit".into(),
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
fn parse_derived_manifest(bytes: &[u8]) -> Result<DerivedManifestWire> {
    if bytes.len() > MAX_RUN_COMPONENT_BYTES {
        return Err(StoreError::InvalidBatch(
            "derived-artifact manifest exceeds the finite byte bound".into(),
        ));
    }
    let value = parse_json_without_duplicate_keys(bytes)?;
    let mut canonical = serde_json::to_vec(&value)?;
    canonical.push(b'\n');
    if canonical != bytes {
        return Err(StoreError::InvalidBatch(
            "derived-artifact manifest must be canonical JSON plus one newline".into(),
        ));
    }
    let manifest: DerivedManifestWire = serde_json::from_value(value)?;
    let restrictions = manifest.restrictions;
    if manifest.manifest_version != DERIVED_ARTIFACT_CONTRACT
        || manifest.artifact_family != DERIVED_ARTIFACT_FAMILY
        || manifest.authority != DERIVED_ARTIFACT_AUTHORITY
        || manifest.display_class != "descriptive_noncausal"
        || manifest.claim_scope != DERIVED_CLAIM_SCOPE
        || manifest.input.source_class != "operational_store"
        || manifest.input.snapshot_contract != "joshi.analysis.snapshot/v2"
        || manifest.fit.policy != "input_available_at_not_after_fit_cutoff"
        || manifest.uncertainty.status != "not_estimated"
        || manifest.uncertainty.reason != "deterministic_descriptive_transform"
        || restrictions.may_rank_census
        || restrictions.may_activate_hot_scope
        || restrictions.may_mutate_observations
        || restrictions.may_mutate_facts
        || restrictions.may_mutate_financial_truth
        || restrictions.economic_authority != DerivedEconomicAuthorityWire::None
        || manifest.artifacts.len() != 1
        || manifest.determinism.canonical_row_order != ["scene_id", "episode_id"]
        || !manifest.determinism.wall_clock_excluded
        || manifest.determinism.network_required
        || manifest.determinism.operational_store_writes
    {
        return Err(StoreError::InvalidBatch(
            "derived-artifact manifest exceeds the finite descriptive no-authority contract".into(),
        ));
    }
    stable(&manifest.analysis_run_id, "analysis run ID")?;
    stable_component(&manifest.producer.id, "artifact producer ID")?;
    stable_component(&manifest.producer.version, "artifact producer version")?;
    for (value, field) in [
        (&manifest.artifact_id, "artifact ID"),
        (&manifest.producer.build_digest, "artifact producer build"),
        (
            &manifest.producer.configuration_digest,
            "artifact producer configuration",
        ),
        (&manifest.producer.lock_digest, "artifact producer lock"),
        (&manifest.input.snapshot_id, "artifact input snapshot"),
        (
            &manifest.input.snapshot_manifest_digest,
            "artifact input snapshot manifest",
        ),
    ] {
        qualified_digest(value, field)?;
    }
    require_strict_ids(
        &manifest.input.publication_ids,
        "artifact publication IDs",
        false,
    )?;
    require_strict_ids(
        &manifest.support.window_ids,
        "artifact coverage-window IDs",
        true,
    )?;
    require_strict_ids(&manifest.support.gap_ids, "artifact coverage-gap IDs", true)?;
    let fit_cutoff = canonical_timestamp(&manifest.fit.fit_cutoff, "artifact fit cutoff")?;
    let maximum_input = canonical_timestamp(
        &manifest.fit.maximum_input_available_at,
        "artifact maximum input availability",
    )?;
    let output_rows = parse_wire(&manifest.support.output_rows, "artifact output rows")?;
    let input_rows = parse_wire(&manifest.support.input_rows, "artifact input rows")?;
    let observed = parse_wire(
        &manifest.support.observed_inputs,
        "artifact observed inputs",
    )?;
    let gaps = parse_wire(&manifest.support.gap_inputs, "artifact gap inputs")?;
    let part = &manifest.artifacts[0];
    if maximum_input > fit_cutoff
        || parse_positive_wire(
            &manifest.input.catalog_commit_seq,
            "artifact catalog cutoff",
        )? == 0
        || part.path.is_empty()
        || std::path::Path::new(&part.path).is_absolute()
        || std::path::Path::new(&part.path).components().count() != 1
        || matches!(part.path.as_str(), "." | "..")
        || part.schema_id != DERIVED_PART_SCHEMA
        || part.primary_key != ["scene_id", "episode_id"]
        || parse_wire(&part.row_count, "artifact part row count")? != output_rows
        || parse_positive_wire(&part.byte_length, "artifact part byte length")? == 0
        || observed.checked_add(gaps) != Some(input_rows)
        || (input_rows > 0 && manifest.support.window_ids.is_empty())
    {
        return Err(StoreError::InvalidBatch(
            "derived-artifact fit/part/support closure is invalid".into(),
        ));
    }
    for (value, field) in [
        (&part.schema_digest, "artifact part schema"),
        (&part.physical_digest, "artifact part physical"),
        (&part.logical_digest, "artifact part logical"),
    ] {
        qualified_digest(value, field)?;
    }
    if bytes_digest(&serde_json::to_vec(&part.schema)?)?.as_str() != part.schema_digest {
        return Err(StoreError::InvalidBatch(
            "artifact part schema descriptor digest differs".into(),
        ));
    }
    let mut identity = serde_json::to_value(&manifest)?;
    identity
        .as_object_mut()
        .ok_or_else(|| StoreError::InvalidBatch("artifact manifest is not an object".into()))?
        .remove("artifact_id");
    if bytes_digest(&serde_json::to_vec(&identity)?)?.as_str() != manifest.artifact_id {
        return Err(StoreError::InvalidBatch(
            "artifact self-identity differs from its exact manifest".into(),
        ));
    }
    Ok(manifest)
}

fn parse_json_without_duplicate_keys(bytes: &[u8]) -> Result<Value> {
    struct ExactValue;
    impl<'de> DeserializeSeed<'de> for ExactValue {
        type Value = Value;

        fn deserialize<D>(self, deserializer: D) -> std::result::Result<Value, D::Error>
        where
            D: serde::Deserializer<'de>,
        {
            deserializer.deserialize_any(ExactVisitor)
        }
    }

    struct ExactVisitor;
    impl<'de> Visitor<'de> for ExactVisitor {
        type Value = Value;

        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("JSON without duplicate keys")
        }

        fn visit_bool<E>(self, value: bool) -> std::result::Result<Value, E> {
            Ok(Value::Bool(value))
        }

        fn visit_i64<E>(self, value: i64) -> std::result::Result<Value, E> {
            Ok(Value::Number(value.into()))
        }

        fn visit_u64<E>(self, value: u64) -> std::result::Result<Value, E> {
            Ok(Value::Number(value.into()))
        }

        fn visit_f64<E>(self, value: f64) -> std::result::Result<Value, E>
        where
            E: serde::de::Error,
        {
            serde_json::Number::from_f64(value)
                .map(Value::Number)
                .ok_or_else(|| E::custom("non-finite number"))
        }

        fn visit_str<E>(self, value: &str) -> std::result::Result<Value, E> {
            Ok(Value::String(value.to_owned()))
        }

        fn visit_string<E>(self, value: String) -> std::result::Result<Value, E> {
            Ok(Value::String(value))
        }

        fn visit_none<E>(self) -> std::result::Result<Value, E> {
            Ok(Value::Null)
        }

        fn visit_unit<E>(self) -> std::result::Result<Value, E> {
            Ok(Value::Null)
        }

        fn visit_seq<A>(self, mut sequence: A) -> std::result::Result<Value, A::Error>
        where
            A: SeqAccess<'de>,
        {
            let mut values = Vec::new();
            while let Some(value) = sequence.next_element_seed(ExactValue)? {
                values.push(value);
            }
            Ok(Value::Array(values))
        }

        fn visit_map<A>(self, mut object: A) -> std::result::Result<Value, A::Error>
        where
            A: MapAccess<'de>,
        {
            let mut values = Map::new();
            while let Some(key) = object.next_key::<String>()? {
                if values.contains_key(&key) {
                    return Err(serde::de::Error::custom(format!(
                        "duplicate JSON key {key}"
                    )));
                }
                values.insert(key, object.next_value_seed(ExactValue)?);
            }
            Ok(Value::Object(values))
        }
    }

    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let value = ExactValue.deserialize(&mut deserializer)?;
    deserializer.end()?;
    Ok(value)
}

fn require_strict_ids(values: &[String], field: &'static str, allow_empty: bool) -> Result<()> {
    if (!allow_empty && values.is_empty())
        || values.windows(2).any(|pair| pair[0] >= pair[1])
        || values.iter().any(|value| stable(value, field).is_err())
    {
        Err(StoreError::InvalidBatch(format!(
            "{field} must be strictly ordered and duplicate-free"
        )))
    } else {
        Ok(())
    }
}

fn canonical_timestamp(value: &str, field: &'static str) -> Result<UtcTimestamp> {
    let parsed = value
        .parse::<UtcTimestamp>()
        .map_err(|_| StoreError::InvalidBatch(format!("{field} is not a timestamp")))?;
    if parsed.to_string() != value {
        return Err(StoreError::InvalidBatch(format!(
            "{field} is not canonical"
        )));
    }
    Ok(parsed)
}

fn resolve_artifact_inputs(
    store: &SqliteStore,
    document: &Wave5RestrictedArtifactRegistrationV1,
    manifest: &DerivedManifestWire,
) -> Result<()> {
    let run_seq = resolve_run(
        store,
        &document.run_registration_id,
        &document.run_registration_digest,
    )?;
    let row: Option<ArtifactResolution> = store
        .connection
        .query_row(
            "SELECT b.export_request_id,b.snapshot_id,e.truth_fingerprint_sha256,
                    b.run_registration_id,b.created_commit_seq,s.manifest_relative_path,
                    s.manifest_sha256,s.manifest_byte_length,s.through_commit_seq
             FROM wave5_export_validation_binding_v1 b
             JOIN production_export_request_v2 e ON e.export_request_id=b.export_request_id
             JOIN export_snapshot s ON s.export_snapshot_id=e.snapshot_id
             WHERE b.export_binding_id=?1",
            [&document.export_binding_id],
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
        export_request,
        snapshot,
        truth,
        run,
        binding_seq,
        snapshot_path,
        snapshot_sha,
        snapshot_len,
        cutoff,
    )) = row
    else {
        return Err(StoreError::MissingIdentity {
            kind: "Wave 5 export validation binding",
            identity: document.export_binding_id.clone(),
        });
    };
    if export_request != document.export_request_id
        || snapshot != document.snapshot_id
        || truth != raw_digest_str(&document.truth_fingerprint, "truth fingerprint")?
        || run != document.run_registration_id
        || as_u64(binding_seq, "export binding commit")? <= run_seq.get()
        || manifest.input.snapshot_id != document.snapshot_id
        || raw_digest_str(
            &manifest.input.snapshot_manifest_digest,
            "artifact input snapshot manifest",
        )? != snapshot_sha
        || parse_positive_wire(
            &manifest.input.catalog_commit_seq,
            "artifact catalog cutoff",
        )? != as_u64(cutoff, "snapshot cutoff")?
    {
        return Err(StoreError::InvalidBatch(
            "restricted artifact does not close its exact run-bound export".into(),
        ));
    }
    let snapshot_path = store.config.export_root.join(snapshot_path);
    verify_file(
        &snapshot_path,
        &snapshot_sha,
        as_u64(snapshot_len, "snapshot manifest length")?,
    )?;
    let snapshot_bytes =
        fs::read(&snapshot_path).map_err(|source| StoreError::io(&snapshot_path, source))?;
    let snapshot_value: serde_json::Value = serde_json::from_slice(&snapshot_bytes)?;
    let snapshot_object = snapshot_value.as_object().ok_or_else(|| {
        StoreError::InvalidBatch("validated export manifest is not an object".into())
    })?;
    let snapshot_maximum = snapshot_object
        .get("maximum_decision_available_at")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| {
            StoreError::InvalidBatch("validated export omits maximum decision availability".into())
        })?;
    let trusted_maximum = canonical_timestamp(snapshot_maximum, "export maximum availability")?;
    if document.maximum_input_available_at != trusted_maximum
        || canonical_timestamp(
            &manifest.fit.maximum_input_available_at,
            "artifact maximum input availability",
        )? != trusted_maximum
        || snapshot_object
            .get("snapshot_id")
            .and_then(serde_json::Value::as_str)
            != Some(document.snapshot_id.as_str())
    {
        return Err(StoreError::InvalidBatch(
            "artifact maximum availability/snapshot does not derive from the validated export"
                .into(),
        ));
    }
    let mut statement = store.connection.prepare(
        "SELECT publication_id FROM production_export_publication_v2
         WHERE export_request_id=?1 ORDER BY ordinal",
    )?;
    let publications = statement
        .query_map([&document.export_request_id], |row| row.get::<_, String>(0))?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if publications != manifest.input.publication_ids {
        return Err(StoreError::InvalidBatch(
            "artifact publication inputs differ from the validated export".into(),
        ));
    }
    drop(statement);
    for window in &manifest.support.window_ids {
        let exists: bool = store.connection.query_row(
            "SELECT EXISTS(SELECT 1 FROM coverage_window
             WHERE coverage_id=?1 AND opened_commit_seq<=?2)",
            params![window, cutoff],
            |row| row.get(0),
        )?;
        if !exists {
            return Err(StoreError::MissingIdentity {
                kind: "artifact coverage window",
                identity: window.clone(),
            });
        }
    }
    for gap in &manifest.support.gap_ids {
        let exists: bool = store.connection.query_row(
            "SELECT EXISTS(SELECT 1 FROM coverage_gap
             WHERE gap_id=?1 AND detected_commit_seq<=?2)",
            params![gap, cutoff],
            |row| row.get(0),
        )?;
        if !exists {
            return Err(StoreError::MissingIdentity {
                kind: "artifact coverage gap",
                identity: gap.clone(),
            });
        }
    }
    Ok(())
}

fn resolve_run(store: &SqliteStore, run_id: &str, run_digest: &str) -> Result<CommitSeq> {
    stable(run_id, "run registration ID")?;
    let raw = raw_digest_str(run_digest, "run registration")?;
    let row: Option<(String, i64)> = store
        .connection
        .query_row(
            "SELECT registration_sha256,created_commit_seq
             FROM wave5_run_registration_v1 WHERE run_registration_id=?1",
            [run_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let Some((stored, seq)) = row else {
        return Err(StoreError::MissingIdentity {
            kind: "Wave 5 run registration",
            identity: run_id.to_owned(),
        });
    };
    if stored != raw {
        return Err(StoreError::InvalidBatch(
            "run registration digest differs from exact durable registration".into(),
        ));
    }
    Ok(CommitSeq::new(as_u64(seq, "run registration commit")?))
}

fn require_commit(store: &SqliteStore, commit: CommitSeq) -> Result<()> {
    let exists: bool = store.connection.query_row(
        "SELECT EXISTS(SELECT 1 FROM ingest_commit WHERE commit_seq=?1)",
        [sqlite_u64(commit.get(), "evidence commit")?],
        |row| row.get(0),
    )?;
    if exists {
        Ok(())
    } else {
        Err(StoreError::MissingIdentity {
            kind: "evidence commit",
            identity: commit.get().to_string(),
        })
    }
}

fn verify_existing_spool_catalog(tx: &Transaction<'_>, value: &SpoolCapability) -> Result<()> {
    let exact: bool = tx.query_row(
        "SELECT segment_sha256=?3 AND segment_byte_length=?4
                AND exact_batch_sha256=?5 AND exact_policy_sha256=?6
                AND logical_batch_sha256=?7 AND store_admission_sha256=?8
                AND store_commit_seq=?9 AND receipt_sha256=?10 AND receipt_bytes=?11
         FROM spool_catalog_admission WHERE segment_id=?1 AND batch_id=?2",
        params![
            value.receipt.segment_id,
            value.receipt.batch.batch_id,
            raw_digest_str(&value.receipt.exact_segment.digest, "segment")?,
            sqlite_wire_u64(&value.receipt.exact_segment.byte_length, "segment length")?,
            raw_digest_str(&value.receipt.batch.exact_batch.digest, "batch")?,
            raw_digest_str(&value.receipt.batch.exact_policy.digest, "policy")?,
            raw_digest_str(&value.receipt.batch.logical_batch_digest, "logical batch")?,
            raw_digest_str(&value.receipt.batch.store_admission_digest, "admission")?,
            sqlite_wire_u64(&value.receipt.catalog_receipt.commit_seq, "store commit")?,
            raw_digest(&value.receipt_digest, "receipt")?,
            value.receipt_bytes,
        ],
        |row| row.get(0),
    )?;
    if exact {
        Ok(())
    } else {
        Err(StoreError::IdentityConflict {
            kind: "spool/catalog admission",
            identity: format!(
                "{}/{}",
                value.receipt.segment_id, value.receipt.batch.batch_id
            ),
        })
    }
}

fn insert_prepared_blob(tx: &Transaction<'_>, blob: &crate::PreparedBlob, seq: i64) -> Result<()> {
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
            sqlite_u64(blob.content_length, "artifact blob length")?,
            blob.content_type.as_str(),
            blob.content_encoding.as_ref().map(StableString::as_str),
            blob.retention_class.as_str(),
        ],
    )?;
    if changed == 0 {
        let exact: bool = tx.query_row(
            "SELECT content_length=?2 AND stored_sha256=?1 FROM blob WHERE blob_id=?1",
            params![
                blob.raw_sha256,
                sqlite_u64(blob.content_length, "blob length")?
            ],
            |row| row.get(0),
        )?;
        if !exact {
            return Err(StoreError::IdentityConflict {
                kind: "restricted artifact blob",
                identity: blob.blob_id.to_string(),
            });
        }
    }
    let changed = tx.execute(
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
            sqlite_u64(blob.content_length, "artifact object length")?,
        ],
    )?;
    if changed == 0 {
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
                sqlite_u64(blob.content_length, "artifact object length")?,
            ],
            |row| row.get(0),
        )?;
        if !exact {
            return Err(StoreError::IdentityConflict {
                kind: "restricted artifact CAS object",
                identity: blob.blob_id.to_string(),
            });
        }
    }
    Ok(())
}

fn parse_canonical<T>(bytes: &[u8], maximum: usize, kind: &'static str) -> Result<T>
where
    T: DeserializeOwned + Serialize,
{
    if bytes.is_empty() || bytes.len() > maximum {
        return Err(StoreError::InvalidBatch(format!(
            "{kind} bytes are empty or exceed {maximum}"
        )));
    }
    let value: T = serde_json::from_slice(bytes)?;
    if serde_json::to_vec(&value)? != bytes {
        return Err(StoreError::InvalidBatch(format!(
            "{kind} bytes are not the canonical exact representation"
        )));
    }
    Ok(value)
}

fn require_header(contract: &str, version: u64, expected: &'static str) -> Result<()> {
    if contract == expected && version == 1 {
        Ok(())
    } else {
        Err(StoreError::InvalidBatch(format!(
            "unsupported Wave 5 contract {contract}/v{version}; expected {expected}/v1"
        )))
    }
}

fn require_authority(value: &str) -> Result<()> {
    if value == AUTHORITY {
        Ok(())
    } else {
        Err(StoreError::InvalidBatch(
            "Wave 5 authority must remain read_only_no_execution".into(),
        ))
    }
}

fn verify_closure(closure: &ExactClosureWire, bytes: &[u8], kind: &'static str) -> Result<()> {
    let length = parse_positive_wire(&closure.byte_length, kind)?;
    let actual_length = u64::try_from(bytes.len()).map_err(|_| StoreError::IntegerRange {
        field: kind,
        value: bytes.len().to_string(),
    })?;
    if length != actual_length || qualified_digest(&closure.digest, kind)? != bytes_digest(bytes)? {
        return Err(StoreError::InvalidBatch(format!(
            "{kind} exact byte closure mismatch"
        )));
    }
    Ok(())
}

fn protection_class_str(value: WireProtectionClass) -> &'static str {
    match value {
        WireProtectionClass::PublicIntegrity => "public_integrity",
        WireProtectionClass::AuthenticatedPrivate => "authenticated_private",
    }
}

fn operational_kind_str(value: Wave5OperationalRecordKind) -> &'static str {
    match value {
        Wave5OperationalRecordKind::Status => "status",
        Wave5OperationalRecordKind::Degradation => "degradation",
        Wave5OperationalRecordKind::RecoveryStarted => "recovery_started",
        Wave5OperationalRecordKind::RecoveryVerified => "recovery_verified",
        Wave5OperationalRecordKind::Stopped => "stopped",
    }
}

fn operational_state_str(value: Wave5OperationalState) -> &'static str {
    match value {
        Wave5OperationalState::Ready => "ready",
        Wave5OperationalState::Degraded => "degraded",
        Wave5OperationalState::Unavailable => "unavailable",
        Wave5OperationalState::Gap => "gap",
        Wave5OperationalState::Backlogged => "backlogged",
        Wave5OperationalState::Stale => "stale",
        Wave5OperationalState::Recovering => "recovering",
        Wave5OperationalState::Refused => "refused",
        Wave5OperationalState::Stopped => "stopped",
    }
}

fn bytes_digest(bytes: &[u8]) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}

fn operation_digest(value: &impl Serialize) -> Result<ValueDigest> {
    bytes_digest(&serde_json::to_vec(value)?)
}

fn qualified_digest(value: &str, kind: &'static str) -> Result<ValueDigest> {
    ValueDigest::new(value.to_owned()).map_err(|_| StoreError::InvalidDigest {
        kind,
        value: value.to_owned(),
    })
}

fn raw_digest<'a>(value: &'a ValueDigest, kind: &'static str) -> Result<&'a str> {
    raw_digest_str(value.as_str(), kind)
}

fn raw_digest_str<'a>(value: &'a str, kind: &'static str) -> Result<&'a str> {
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

fn stable(value: &str, kind: &'static str) -> Result<StableString> {
    StableString::new(value.to_owned())
        .map_err(|error| StoreError::InvalidBatch(format!("invalid {kind}: {error}")))
}

fn stable_ascii(value: &str, kind: &'static str) -> Result<StableString> {
    if !value.is_ascii() {
        return Err(StoreError::InvalidBatch(format!(
            "invalid {kind}: value is not ASCII"
        )));
    }
    stable(value, kind)
}

fn parse_positive_wire(value: &str, field: &'static str) -> Result<u64> {
    if value.is_empty()
        || value == "0"
        || value.starts_with('0')
        || value.bytes().any(|byte| !byte.is_ascii_digit())
    {
        return Err(StoreError::InvalidBatch(format!(
            "{field} is not a positive canonical u64"
        )));
    }
    value
        .parse()
        .map_err(|_| StoreError::InvalidBatch(format!("{field} is not a positive canonical u64")))
}

fn parse_wire(value: &str, field: &'static str) -> Result<u64> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || value.bytes().any(|byte| !byte.is_ascii_digit())
    {
        return Err(StoreError::InvalidBatch(format!(
            "{field} is not a canonical u64"
        )));
    }
    value
        .parse()
        .map_err(|_| StoreError::InvalidBatch(format!("{field} is not a canonical u64")))
}

fn sqlite_wire_u64(value: &str, field: &'static str) -> Result<i64> {
    sqlite_u64(parse_positive_wire(value, field)?, field)
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

#[cfg(test)]
mod tests {
    use super::*;

    fn sha(byte: u8) -> String {
        format!("sha256:{}", char::from(byte).to_string().repeat(64))
    }

    fn document(id: &str, bytes: &[u8]) -> ExactRegisteredDocumentWire {
        ExactRegisteredDocumentWire {
            document_id: id.into(),
            exact_bytes: ExactClosureWire {
                digest: bytes_digest(bytes).unwrap().to_string(),
                byte_length: bytes.len().to_string(),
            },
        }
    }

    #[test]
    fn arbitrary_run_component_bytes_are_refused() {
        let components = (*b"abcdef").map(|byte| vec![byte]);
        let exact_record = Wave5RunRegistrationWire {
            contract: RUN_CONTRACT.into(),
            schema_version: 1,
            run_id: "run:test".into(),
            build: document("build:test", &components[0]),
            source_tree: document("tree:test", &components[1]),
            configuration: document("config:test", &components[2]),
            budget: document("budget:test", &components[3]),
            privacy: document("privacy:test", &components[4]),
            daily_use_surface_profile: document("profile:test", &components[5]),
            authority: AUTHORITY.into(),
        };
        let exact = serde_json::to_vec(&exact_record).expect("canonical record");
        let bundle = Wave5RunRegistrationByteBundle {
            registration: &exact,
            build: &components[0],
            source_tree: &components[1],
            configuration: &components[2],
            budget: &components[3],
            privacy: &components[4],
            daily_use_surface_profile: &components[5],
        };
        assert!(RunCapability::parse(&bundle).is_err());
    }

    #[test]
    fn authenticated_private_spool_is_refused_without_aead_verification() {
        let protection = SegmentProtectionWire::AuthenticatedPrivate {
            algorithm: "chacha20_poly1305.v1".into(),
            key_id: "key:test".into(),
            nonce_base64: "AAAAAAAAAAAAAAAA".into(),
        };
        let error = validate_supported_segment_protection(
            &protection,
            WireProtectionClass::AuthenticatedPrivate,
        )
        .expect_err("ciphertext length is not an authentication receipt");
        assert!(error.to_string().contains("AEAD tag"));
    }

    #[test]
    fn artifact_occurrence_and_content_identities_stay_distinct() {
        let manifest = include_bytes!(
            "../../../fixtures/artifact/derived-759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55/manifest.json"
        );
        let parsed_manifest = parse_derived_manifest(manifest).unwrap();
        let record = Wave5RestrictedArtifactRegistrationV1 {
            contract: RESTRICTED_ARTIFACT_CONTRACT.into(),
            schema_version: 1,
            import_id: "import:test".into(),
            run_registration_id: "run:test".into(),
            run_registration_digest: sha(b'a'),
            export_binding_id: "export-binding:test".into(),
            export_request_id: "export-request:test".into(),
            analysis_run_id: parsed_manifest.analysis_run_id.clone(),
            artifact_id: parsed_manifest.artifact_id.clone(),
            artifact_contract: DERIVED_ARTIFACT_CONTRACT.into(),
            manifest_digest: bytes_digest(manifest).unwrap().to_string(),
            snapshot_id: parsed_manifest.input.snapshot_id.clone(),
            claim_scope: "descriptive_noncausal".into(),
            truth_fingerprint: sha(b'c'),
            maximum_input_available_at: parsed_manifest
                .fit
                .maximum_input_available_at
                .parse()
                .unwrap(),
            authority: AUTHORITY.into(),
        };
        let exact = serde_json::to_vec(&record).unwrap();
        let parsed = ArtifactCapability::parse_registration_only(&exact, manifest).unwrap();
        assert_eq!(
            parsed.artifact_digest.as_str(),
            parsed_manifest.artifacts[0].physical_digest
        );
        let before_fit = Wave5CommitContext::new(
            stable("commit:before-fit", "test commit ID").unwrap(),
            "1970-01-01T00:00:01.000000Z".parse().unwrap(),
            stable("clock:test", "test clock ID").unwrap(),
            1,
            stable("build:test", "test build ID").unwrap(),
        );
        assert!(validate_artifact_commit_cutoff(&parsed, &before_fit).is_err());
        let mut collapsed = record;
        collapsed.analysis_run_id = collapsed.import_id.clone();
        assert!(
            ArtifactCapability::parse_registration_only(
                &serde_json::to_vec(&collapsed).unwrap(),
                manifest,
            )
            .is_err()
        );
    }
}
