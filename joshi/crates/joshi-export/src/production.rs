use crate::{
    ExportError, Result, ValidatedTableArtifactV1,
    assertions::provenance_batch,
    coverage::selected_coverage_batches,
    snapshot::{
        logical_table_digest, parse_json_without_duplicate_keys, qualified_sha256,
        qualified_sha256_file, read_parquet, relation_rows, schema_descriptor, sync_directory,
        write_file_durable, write_parquet,
    },
    specs::{G0_TABLE_SPECS, TABLE_SPECS, TableSpec},
};
use arrow_array::{
    Array, ArrayRef, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray,
};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_publication::{parse_cockpit_v2_head, parse_cockpit_v2_publication};
use rusqlite::{Connection, OpenFlags, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::Arc,
};

const APPLICATION_ID: i32 = 0x4a4f_5348;
const SNAPSHOT_V2: &str = "joshi.analysis.snapshot/v2";
const VALIDATION_RECEIPT: &str = "joshi.export.snapshot-validation-receipt/v2";
const MAXIMUM_MANIFEST_BYTES: u64 = 16 * 1024 * 1024;
const MINIMUM_CATALOG_SCHEMA: i64 = 8;
const MAXIMUM_CATALOG_SCHEMA: i64 = 24;
const MIGRATIONS: [(i64, &str, &str); 24] = [
    (
        1,
        "0001_evidence.sql",
        include_str!("../../../schema/migrations/0001_evidence.sql"),
    ),
    (
        2,
        "0002_assertions_coverage.sql",
        include_str!("../../../schema/migrations/0002_assertions_coverage.sql"),
    ),
    (
        3,
        "0003_scenes_commands.sql",
        include_str!("../../../schema/migrations/0003_scenes_commands.sql"),
    ),
    (
        4,
        "0004_operations_exports.sql",
        include_str!("../../../schema/migrations/0004_operations_exports.sql"),
    ),
    (
        5,
        "0005_lossless_contract.sql",
        include_str!("../../../schema/migrations/0005_lossless_contract.sql"),
    ),
    (
        6,
        "0006_optional_acquisition_monotonic.sql",
        include_str!("../../../schema/migrations/0006_optional_acquisition_monotonic.sql"),
    ),
    (
        7,
        "0007_operational_exocortex.sql",
        include_str!("../../../schema/migrations/0007_operational_exocortex.sql"),
    ),
    (
        8,
        "0008_semantic_artifact_durability.sql",
        include_str!("../../../schema/migrations/0008_semantic_artifact_durability.sql"),
    ),
    (
        9,
        "0009_wave5_living_instrument.sql",
        include_str!("../../../schema/migrations/0009_wave5_living_instrument.sql"),
    ),
    (
        10,
        "0010_wave5_g0_store_spine.sql",
        include_str!("../../../schema/migrations/0010_wave5_g0_store_spine.sql"),
    ),
    (
        11,
        "0011_wave6_program_registry.sql",
        include_str!("../../../schema/migrations/0011_wave6_program_registry.sql"),
    ),
    (
        12,
        "0012_wave6_artifact_schemas.sql",
        include_str!("../../../schema/migrations/0012_wave6_artifact_schemas.sql"),
    ),
    (
        13,
        "0013_wave6_fixture_artifacts.sql",
        include_str!("../../../schema/migrations/0013_wave6_fixture_artifacts.sql"),
    ),
    (
        14,
        "0014_wave6_artifact_dag.sql",
        include_str!("../../../schema/migrations/0014_wave6_artifact_dag.sql"),
    ),
    (
        15,
        "0015_wave6_fixture_decisions.sql",
        include_str!("../../../schema/migrations/0015_wave6_fixture_decisions.sql"),
    ),
    (
        16,
        "0016_wave6_campaign_bundle.sql",
        include_str!("../../../schema/migrations/0016_wave6_campaign_bundle.sql"),
    ),
    (
        17,
        "0017_wave6_research_proposal.sql",
        include_str!("../../../schema/migrations/0017_wave6_research_proposal.sql"),
    ),
    (
        18,
        "0018_wave6_research_disposition.sql",
        include_str!("../../../schema/migrations/0018_wave6_research_disposition.sql"),
    ),
    (
        19,
        "0019_wave6_market_atlas_fixture.sql",
        include_str!("../../../schema/migrations/0019_wave6_market_atlas_fixture.sql"),
    ),
    (
        20,
        "0020_wave6_store_input_census.sql",
        include_str!("../../../schema/migrations/0020_wave6_store_input_census.sql"),
    ),
    (
        21,
        "0021_cockpit_v2_browser_presentation.sql",
        include_str!("../../../schema/migrations/0021_cockpit_v2_browser_presentation.sql"),
    ),
    (
        22,
        "0022_wave6_operator_evidence_input.sql",
        include_str!("../../../schema/migrations/0022_wave6_operator_evidence_input.sql"),
    ),
    (
        23,
        "0023_wave5_c1_activation.sql",
        include_str!("../../../schema/migrations/0023_wave5_c1_activation.sql"),
    ),
    (
        24,
        "0024_retire_wave5_c1_activation.sql",
        include_str!("../../../schema/migrations/0024_retire_wave5_c1_activation.sql"),
    ),
];

/// Exact independent Python validator invocation. No shell is involved.
#[derive(Clone, Debug)]
pub struct PythonValidatorV2 {
    /// `uv` executable or an exact equivalent wrapper.
    pub program: PathBuf,
    /// Locked analysis project directory.
    pub analysis_directory: PathBuf,
}

/// One exact imported artifact part readback descriptor.
///
/// This public value is neutral and confers no store authority. A sole-store adapter must resolve
/// it from private state, reopen every path, and retain its own durable qualification.
#[derive(Clone, Debug)]
pub struct G0ImportPartReadbackV1 {
    pub path: PathBuf,
    pub relative_path: StableString,
    pub schema_id: StableString,
    pub schema_digest: ValueDigest,
    pub physical_digest: ValueDigest,
    pub logical_digest: ValueDigest,
    pub primary_key: Vec<StableString>,
    pub byte_length: u64,
    pub row_count: u64,
}

/// Exact imported artifact manifest and all-part readback input.
///
/// Supplying this public DTO does not prove store provenance and never mints a store receipt.
#[derive(Clone, Debug)]
pub struct G0ImportArtifactReadbackV1 {
    pub import_id: StableString,
    pub artifact_id: ValueDigest,
    pub manifest_path: PathBuf,
    pub parts: Vec<G0ImportPartReadbackV1>,
}

/// Catalog-owned immutable read input and explicit publication selection.
#[derive(Clone, Debug)]
pub struct OperationalExportRequestV2 {
    /// Durable, non-changing online-backup catalog path.
    pub catalog_snapshot_path: PathBuf,
    /// Store configuration identity, absent from `SQLite` by design.
    pub catalog_id: StableString,
    /// Exact catalog schema identity.
    pub catalog_schema: StableString,
    /// Closed lower represented commit.
    pub from_commit_seq: CommitSeq,
    /// Closed as-known cutoff.
    pub through_commit_seq: CommitSeq,
    /// Reserved immutable export occurrence identity.
    pub export_request_id: StableString,
    /// Exporter build identity.
    pub producer_build: StableString,
    /// Deterministic store-provided render/publication time.
    pub created_at: UtcTimestamp,
    /// Primary exact projection publication used by the producer vector.
    pub producer_projection_publication_id: StableString,
    /// Sorted neutral exact publication closure already validated by the store adapter.
    pub publications: Vec<OperationalPublicationV2>,
    /// Strictly sorted coverage windows selected for this snapshot.
    pub coverage_window_ids: Vec<StableString>,
    /// Final immutable output directory.
    pub destination: PathBuf,
    /// Independent locked Python semantic validator.
    pub python_validator: PythonValidatorV2,
    /// Required neutral import/CAS readback descriptor whenever the window holds a G0
    /// occurrence closure; absent when it does not.
    pub g0_import_artifact: Option<G0ImportArtifactReadbackV1>,
}

/// Store-validated neutral publication input. It carries exact identities/digests without making
/// `joshi-export` depend on the semantic publication/projection/store graph.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationalPublicationV2 {
    /// Finalized projection publication.
    Projection(ProjectionPublicationInputV2),
    /// Cockpit publication naming one prior projection publication.
    Cockpit(CockpitPublicationInputV2),
}

impl OperationalPublicationV2 {
    fn id(&self) -> &StableString {
        match self {
            Self::Projection(value) => &value.publication_id,
            Self::Cockpit(value) => &value.publication_id,
        }
    }
}

/// Exact neutral projection-publication closure supplied by storage.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProjectionPublicationInputV2 {
    pub publication_id: StableString,
    pub publication_contract: StableString,
    pub publication_digest: ValueDigest,
    /// Digest of the exact serialized publication bytes, distinct from the semantic digest.
    pub publication_bytes_digest: ValueDigest,
    pub projection_id: StableString,
    pub projection_name: StableString,
    pub projection_version: StableString,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub input_closure_digest: ValueDigest,
    pub through_commit_seq: CommitSeq,
    pub published_commit_seq: CommitSeq,
}

/// Exact neutral cockpit-publication closure supplied by storage.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CockpitPublicationInputV2 {
    pub publication_id: StableString,
    pub publication_contract: StableString,
    pub publication_digest: ValueDigest,
    /// Digest of the exact cockpit manifest bytes.
    pub manifest_digest: ValueDigest,
    pub scene_id: StableString,
    pub projection_publication_id: StableString,
    /// Semantic digest of the exact referenced projection publication.
    pub projection_publication_digest: ValueDigest,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub query_policy: StableString,
    pub published_commit_seq: CommitSeq,
}

/// Exact validator receipt retained beside durable snapshot registration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ValidationReceiptV2 {
    contract: &'static str,
    schema_version: u16,
    validator: &'static str,
    snapshot_id: ValueDigest,
    manifest_digest: ValueDigest,
    table_count: u64,
    total_row_count: u64,
    receipt_digest: ValueDigest,
}

impl ValidationReceiptV2 {
    /// Validator implementation family.
    #[must_use]
    pub const fn validator(&self) -> &'static str {
        self.validator
    }
    /// Self-derived exact receipt digest.
    #[must_use]
    pub fn receipt_digest(&self) -> &ValueDigest {
        &self.receipt_digest
    }
    /// Exact number of reopened typed relations.
    #[must_use]
    pub const fn table_count(&self) -> u64 {
        self.table_count
    }
    /// Exact number of reopened logical rows across all relations.
    #[must_use]
    pub const fn total_row_count(&self) -> u64 {
        self.total_row_count
    }
}

/// Production snapshot capability returned only after Rust readback, Python validation, and
/// immutable directory installation.
#[derive(Clone, Debug)]
pub struct ValidatedProductionSnapshotV2 {
    root: PathBuf,
    export_request_id: StableString,
    manifest_bytes: Vec<u8>,
    manifest_digest: ValueDigest,
    snapshot_id: ValueDigest,
    catalog_id: StableString,
    catalog_schema: StableString,
    from_commit_seq: CommitSeq,
    through_commit_seq: CommitSeq,
    producer_build: StableString,
    producer_projection: (StableString, StableString),
    publication_ids: Vec<StableString>,
    coverage_window_ids: Vec<StableString>,
    truth_fingerprint: Value,
    tables: Vec<ValidatedTableArtifactV1>,
    rust_validation: ValidationReceiptV2,
    python_validation: ValidationReceiptV2,
}

impl ValidatedProductionSnapshotV2 {
    /// Installed immutable directory.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }
    /// Reserved export-request occurrence fulfilled by this content-derived snapshot.
    #[must_use]
    pub fn export_request_id(&self) -> &StableString {
        &self.export_request_id
    }
    /// Exact canonical manifest bytes.
    #[must_use]
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.manifest_bytes
    }
    /// Digest of the exact manifest bytes.
    #[must_use]
    pub fn manifest_digest(&self) -> &ValueDigest {
        &self.manifest_digest
    }
    /// Snapshot self-identity.
    #[must_use]
    pub fn snapshot_id(&self) -> &ValueDigest {
        &self.snapshot_id
    }
    /// Catalog identity.
    #[must_use]
    pub fn catalog_id(&self) -> &StableString {
        &self.catalog_id
    }
    /// Catalog schema identity.
    #[must_use]
    pub fn catalog_schema(&self) -> &StableString {
        &self.catalog_schema
    }
    /// Closed represented commit range.
    #[must_use]
    pub const fn commit_range(&self) -> (CommitSeq, CommitSeq) {
        (self.from_commit_seq, self.through_commit_seq)
    }
    /// Export producer build.
    #[must_use]
    pub fn producer_build(&self) -> &StableString {
        &self.producer_build
    }
    /// Primary producer projection name and immutable version selected by the request.
    #[must_use]
    pub const fn producer_projection(&self) -> (&StableString, &StableString) {
        (&self.producer_projection.0, &self.producer_projection.1)
    }
    /// Sorted projection and cockpit publication occurrence closure.
    #[must_use]
    pub fn publication_ids(&self) -> &[StableString] {
        &self.publication_ids
    }
    /// Sorted, exact coverage-window selection materialized into the snapshot.
    #[must_use]
    pub fn coverage_window_ids(&self) -> &[StableString] {
        &self.coverage_window_ids
    }
    /// Store-computed evidence/projection/count fingerprint that import must preserve.
    #[must_use]
    pub fn truth_fingerprint(&self) -> &Value {
        &self.truth_fingerprint
    }
    /// Exact frozen closure: fourteen legacy relations, plus ten G0 relations for V10.
    #[must_use]
    pub fn tables(&self) -> &[ValidatedTableArtifactV1] {
        &self.tables
    }
    /// Independent Rust receipt.
    #[must_use]
    pub const fn rust_validation(&self) -> &ValidationReceiptV2 {
        &self.rust_validation
    }
    /// Independent Python receipt.
    #[must_use]
    pub const fn python_validation(&self) -> &ValidationReceiptV2 {
        &self.python_validation
    }
}

#[derive(Clone, Debug)]
struct PublicationClosure {
    manifest_rows: Vec<Value>,
    projections: Vec<ProjectionPublicationInputV2>,
    publication_ids: Vec<StableString>,
}

/// Decides the readback profile the way an independent reader must: from the manifest alone.
///
/// A V10 catalog always carries the G0 occurrence profile, which is what the frozen V10 contract
/// says. Later catalog generations carry it only when the export declared it, and the exact
/// name/cardinality closure below then refuses any partial G0 table set.
fn manifest_declares_g0_profile(version: i64, tables: &[Value]) -> bool {
    if version == 10 {
        return true;
    }
    version > 10
        && tables.iter().any(|table| {
            table["name"]
                .as_str()
                .is_some_and(|name| G0_TABLE_SPECS.iter().any(|spec| spec.name == name))
        })
}

fn table_specs(g0_profile: bool) -> Vec<&'static TableSpec> {
    TABLE_SPECS
        .iter()
        .chain(g0_profile.then_some(G0_TABLE_SPECS).into_iter().flatten())
        .collect()
}

/// Every table whose rows the G0 occurrence profile is the only adapter for.
const G0_OCCURRENCE_TABLES: [(&str, &str); 8] = [
    ("wave5_source_occurrence_v1", "created_commit_seq"),
    ("cockpit_v2_publication_v1", "created_commit_seq"),
    ("scientific_memory_occurrence_v1", "created_commit_seq"),
    ("wave5_run_registration_v1", "created_commit_seq"),
    ("wave5_spool_catalog_binding_v1", "created_commit_seq"),
    ("wave5_operational_record_v1", "created_commit_seq"),
    ("wave5_export_validation_binding_v1", "created_commit_seq"),
    ("wave5_restricted_artifact_v1", "created_commit_seq"),
];

fn table_exists(connection: &Connection, table: &str) -> Result<bool> {
    let count: i64 = connection.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
        params![table],
        |row| row.get(0),
    )?;
    Ok(count == 1)
}

fn rows_in_range(
    connection: &Connection,
    table: &str,
    column: &str,
    from: i64,
    cutoff: i64,
) -> Result<i64> {
    if !table_exists(connection, table)? {
        return Ok(0);
    }
    let sql = format!("SELECT COUNT(*) FROM {table} WHERE {column} BETWEEN ?1 AND ?2");
    Ok(connection.query_row(&sql, params![from, cutoff], |row| row.get(0))?)
}

/// Decides the snapshot profile from what the catalog actually holds in the requested window.
///
/// Before this the profile was keyed on the catalog schema number alone, which made every
/// catalog at V10 or later demand the complete ten-relation G0 occurrence closure and refuse
/// outright when the store held raw evidence and no Wave 5 ceremony. The schema number says what
/// a catalog *can* record; only its rows say what it *did*.
fn g0_occurrences_present(
    connection: &Connection,
    from: CommitSeq,
    cutoff: CommitSeq,
    catalog_version: i64,
) -> Result<bool> {
    if catalog_version < 10 {
        return Ok(false);
    }
    let from = sql_commit(from)?;
    let cutoff = sql_commit(cutoff)?;
    for (table, column) in G0_OCCURRENCE_TABLES {
        if rows_in_range(connection, table, column, from, cutoff)? != 0 {
            return Ok(true);
        }
    }
    Ok(false)
}

/// Query an immutable operational catalog backup at an explicit cutoff, materialize the exact
/// frozen typed relation profile, independently re-read it in Rust, run the locked Python semantic
/// validator, and only then atomically install the snapshot directory.
///
/// V2 intentionally permits presently absent decision-study relations to be valid empty tables.
/// It does not infer decisions from V1/V2 annotations or nullable choices. Scenes are projected
/// directly; choice-sensitive rows require a future exact protocol-decision contract.
///
/// # Errors
///
/// Refuses mutable/symlinked inputs, out-of-range catalog schemas, cutoffs/publications that do
/// not close,
/// malformed exact publication bytes, future rows, schema/logical drift, Python disagreement,
/// destination replacement, or any catalog mutation during the read.
#[allow(clippy::too_many_lines)]
pub fn export_operational_snapshot_v2(
    request: &OperationalExportRequestV2,
) -> Result<ValidatedProductionSnapshotV2> {
    validate_request(request)?;
    let catalog_length = fs::metadata(&request.catalog_snapshot_path)
        .map_err(|error| ExportError::io(&request.catalog_snapshot_path, error))?
        .len();
    if catalog_length > 8 * 1024 * 1024 * 1024 {
        return Err(invalid("catalog snapshot exceeds bounded input"));
    }
    let catalog_digest = qualified_sha256_file(&request.catalog_snapshot_path)?;
    let connection = Connection::open_with_flags(
        &request.catalog_snapshot_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.pragma_update(None, "query_only", true)?;
    let catalog_version = validate_catalog(&connection, request)?;
    let g0_profile = g0_occurrences_present(
        &connection,
        request.from_commit_seq,
        request.through_commit_seq,
        catalog_version,
    )?;
    if g0_profile != request.g0_import_artifact.is_some() {
        return Err(invalid(
            "a G0 occurrence closure in range requires exactly one neutral import artifact readback",
        ));
    }
    refuse_unmapped_operational_facts(
        &connection,
        request.from_commit_seq,
        request.through_commit_seq,
        catalog_version,
    )?;
    let publications = load_publications(&connection, request, g0_profile)?;
    let producer_projection = publications
        .projections
        .iter()
        .find(|value| value.publication_id == request.producer_projection_publication_id)
        .map(|value| {
            (
                value.projection_name.clone(),
                value.projection_version.clone(),
            )
        })
        .ok_or_else(|| invalid("primary producer projection is absent from publication closure"))?;
    let sources = source_as_of(&connection, request.through_commit_seq)?;
    if sources.is_empty() {
        return Err(invalid(
            "operational snapshot requires at least one represented source",
        ));
    }
    let chain = chain_as_of(
        &connection,
        request.from_commit_seq,
        request.through_commit_seq,
    )?;
    let scenes = scene_batch(
        &connection,
        request.from_commit_seq,
        request.through_commit_seq,
    )?;
    let coverage = selected_coverage_batches(
        &connection,
        request.from_commit_seq,
        request.through_commit_seq,
        &request.coverage_window_ids,
    )?;
    let maximum_decision = maximum_scene_clock(&scenes).unwrap_or(request.created_at);
    if maximum_decision > request.created_at {
        return Err(invalid(
            "maximum scene decision availability exceeds snapshot creation",
        ));
    }
    let truth_fingerprint = truth_fingerprint(
        &connection,
        request.from_commit_seq,
        request.through_commit_seq,
        &publications,
    )?;
    let provenance = provenance_batch(
        &connection,
        request.from_commit_seq,
        request.through_commit_seq,
    )?;
    let specs = table_specs(g0_profile);
    let mut relations = relation_batches(&scenes, &provenance, &coverage.windows, &coverage.gaps);
    if g0_profile {
        relations.extend(crate::g0::relation_batches(
            &connection,
            request.from_commit_seq,
            request.through_commit_seq,
            request.g0_import_artifact.as_ref(),
        )?);
    }

    let parent = request
        .destination
        .parent()
        .ok_or_else(|| invalid("destination requires a parent"))?;
    fs::create_dir_all(parent).map_err(|error| ExportError::io(parent, error))?;
    let staging = tempfile::Builder::new()
        .prefix(".joshi-production-export-")
        .tempdir_in(parent)
        .map_err(|error| ExportError::io(parent, error))?;
    let mut table_manifests = Vec::with_capacity(specs.len());
    let mut table_artifacts = Vec::with_capacity(specs.len());
    let mut total_rows = 0_u64;
    for (ordinal, spec) in specs.iter().enumerate() {
        let batches = relations
            .get(spec.name)
            .ok_or_else(|| invalid(format!("missing typed relation {}", spec.name)))?;
        let path_name = format!("{}.parquet", spec.name);
        let staged_path = staging.path().join(&path_name);
        write_parquet(&staged_path, Arc::new(spec.schema()), batches)?;
        let readback = read_parquet(&staged_path)?;
        let expected_schema = spec.schema();
        if readback.first().map(RecordBatch::schema).as_deref() != Some(&expected_schema) {
            return Err(invalid(format!(
                "{} schema changed during Rust readback: expected {expected_schema:?}, got {:?}",
                spec.name,
                readback.first().map(RecordBatch::schema),
            )));
        }
        let logical = logical_table_digest(&readback, spec.primary_key)?;
        let schema_value = schema_descriptor(&spec.schema())?;
        let schema_digest = qualified_sha256(&serde_json::to_vec(&schema_value)?);
        let physical = qualified_sha256_file(&staged_path)?;
        let bytes = fs::metadata(&staged_path)
            .map_err(|error| ExportError::io(&staged_path, error))?
            .len();
        let rows = readback
            .iter()
            .try_fold(0_u64, |sum, batch| {
                sum.checked_add(u64::try_from(batch.num_rows()).ok()?)
                    .or(None)
            })
            .ok_or_else(|| invalid("row count exceeds u64"))?;
        total_rows = total_rows
            .checked_add(rows)
            .ok_or_else(|| invalid("snapshot row count exceeds u64"))?;
        let event_bounds = event_bounds(spec.name, &readback)?;
        let coverage = coverage_manifest(spec.name, &readback)?;
        let export_manifest_id = format!("{}:{}", request.export_request_id, spec.name);
        table_manifests.push(json!({
            "export_manifest_id": export_manifest_id,
            "name": spec.name,
            "path": path_name,
            "schema_id": spec.schema_id,
            "schema": schema_value,
            "schema_digest": schema_digest,
            "physical_digest": physical,
            "logical_digest": logical,
            "byte_length": bytes,
            "row_count": rows,
            "primary_key": spec.primary_key,
            "commit_bounds": {
                "from_commit_seq": request.from_commit_seq.get().to_string(),
                "through_commit_seq": request.through_commit_seq.get().to_string()
            },
            "event_bounds": event_bounds,
            "chain_bounds": Value::Null,
            "coverage": coverage
        }));
        table_artifacts.push(ValidatedTableArtifactV1 {
            name: stable(spec.name)?,
            export_manifest_id: stable(&export_manifest_id)?,
            schema_id: stable(spec.schema_id)?,
            schema_digest: digest(&schema_digest)?,
            physical_digest: digest(&physical)?,
            logical_digest: digest(&logical)?,
            relative_path: PathBuf::from(&path_name),
            absolute_path: request.destination.join(&path_name),
            byte_length: bytes,
            row_count: rows,
            from_commit_seq: request.from_commit_seq,
            through_commit_seq: request.through_commit_seq,
            ordinal: u64::try_from(ordinal).map_err(|_| invalid("table ordinal exceeds u64"))?,
        });
    }
    let producer = publications
        .projections
        .iter()
        .find(|item| item.publication_id == request.producer_projection_publication_id)
        .ok_or_else(|| invalid("producer projection publication is absent"))?;
    let manifest_preimage = json!({
        "manifest_version": SNAPSHOT_V2,
        "created_at": request.created_at.to_string(),
        "producer": {
            "build": request.producer_build,
            "projection_name": producer.projection_name,
            "projection_version": producer.projection_version,
            "projection_state_digest": producer.result_digest,
        },
        "catalog": {
            "catalog_id": request.catalog_id,
            "catalog_schema": request.catalog_schema,
            "from_commit_seq": request.from_commit_seq.get().to_string(),
            "through_commit_seq": request.through_commit_seq.get().to_string(),
            "as_of": {
                "catalog_commit": request.through_commit_seq.get().to_string(),
                "sources": sources,
                "chain": chain,
                "projections": projection_as_of(&publications.projections)?,
                "rendered_at": request.created_at.to_string(),
            }
        },
        "knowledge_mode": "as_known",
        "maximum_decision_available_at": maximum_decision.to_string(),
        "origin": {
            "kind": "operational_store",
            "export_request_id": request.export_request_id,
            "catalog_snapshot_digest": catalog_digest,
            "catalog_snapshot_byte_length": catalog_length.to_string(),
        },
        "publications": publications.manifest_rows,
        "truth_fingerprint": truth_fingerprint,
        "tables": table_manifests,
    });
    let snapshot_id_text = qualified_sha256(&serde_json::to_vec(&manifest_preimage)?);
    let mut manifest = manifest_preimage
        .as_object()
        .cloned()
        .ok_or_else(|| invalid("manifest preimage is not an object"))?;
    manifest.insert(
        "snapshot_id".into(),
        Value::String(snapshot_id_text.clone()),
    );
    let mut manifest_bytes = serde_json::to_vec(&Value::Object(manifest))?;
    manifest_bytes.push(b'\n');
    let manifest_digest_text = qualified_sha256(&manifest_bytes);
    write_file_durable(&staging.path().join("manifest.json"), &manifest_bytes)?;
    sync_directory(staging.path())?;
    let rust_validation = validate_operational_snapshot_v2_directory(staging.path())?;
    let python_validation = run_python_validator(
        &request.python_validator,
        staging.path(),
        &snapshot_id_text,
        &manifest_digest_text,
        total_rows,
        specs.len(),
    )?;
    let catalog_after_length = fs::metadata(&request.catalog_snapshot_path)
        .map_err(|error| ExportError::io(&request.catalog_snapshot_path, error))?
        .len();
    if catalog_after_length != catalog_length
        || qualified_sha256_file(&request.catalog_snapshot_path)? != catalog_digest
    {
        return Err(invalid("catalog snapshot mutated during export"));
    }
    drop(connection);
    fs::rename(staging.path(), &request.destination)
        .map_err(|error| ExportError::io(&request.destination, error))?;
    sync_directory(parent)?;
    let _persisted = staging.keep();
    Ok(ValidatedProductionSnapshotV2 {
        root: request.destination.clone(),
        export_request_id: request.export_request_id.clone(),
        manifest_bytes,
        manifest_digest: digest(&manifest_digest_text)?,
        snapshot_id: digest(&snapshot_id_text)?,
        catalog_id: request.catalog_id.clone(),
        catalog_schema: request.catalog_schema.clone(),
        from_commit_seq: request.from_commit_seq,
        through_commit_seq: request.through_commit_seq,
        producer_build: request.producer_build.clone(),
        producer_projection,
        publication_ids: publications.publication_ids,
        coverage_window_ids: request.coverage_window_ids.clone(),
        truth_fingerprint,
        tables: table_artifacts,
        rust_validation,
        python_validation,
    })
}

/// Independently reopens and validates a complete immutable Snapshot V2 directory.
///
/// This is the restart readback port for the store/root integrator. It reparses the canonical
/// self-hashed manifest and reopens every exact Parquet part; it does not create a store receipt.
///
/// # Errors
///
/// Refuses duplicate/noncanonical manifests, an incomplete V8/V9/V10 table set, unsafe or extra
/// paths, physical/schema/logical/row drift, false bounds/coverage, or inconsistent totals.
#[allow(clippy::too_many_lines)]
pub fn validate_operational_snapshot_v2_directory(root: &Path) -> Result<ValidationReceiptV2> {
    let manifest_path = root.join("manifest.json");
    let metadata = fs::symlink_metadata(&manifest_path)
        .map_err(|error| ExportError::io(&manifest_path, error))?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAXIMUM_MANIFEST_BYTES
    {
        return Err(invalid(
            "snapshot manifest must be a bounded real regular file",
        ));
    }
    let manifest_bytes =
        fs::read(&manifest_path).map_err(|error| ExportError::io(&manifest_path, error))?;
    let manifest = parse_json_without_duplicate_keys(&manifest_bytes)?;
    let mut canonical = serde_json::to_vec(&manifest)?;
    canonical.push(b'\n');
    if canonical != manifest_bytes {
        return Err(invalid(
            "snapshot manifest is not canonical JSON plus one newline",
        ));
    }
    let object = manifest
        .as_object()
        .ok_or_else(|| invalid("snapshot manifest must be an object"))?;
    let expected_head = BTreeSet::from([
        "catalog",
        "created_at",
        "knowledge_mode",
        "manifest_version",
        "maximum_decision_available_at",
        "origin",
        "producer",
        "publications",
        "snapshot_id",
        "tables",
        "truth_fingerprint",
    ]);
    let actual_head = object.keys().map(String::as_str).collect::<BTreeSet<_>>();
    if actual_head != expected_head
        || manifest["manifest_version"] != SNAPSHOT_V2
        || manifest["knowledge_mode"] != "as_known"
    {
        return Err(invalid("snapshot V2 manifest head differs"));
    }
    let snapshot_id = manifest["snapshot_id"]
        .as_str()
        .ok_or_else(|| invalid("snapshot identity is absent"))?;
    let mut preimage = object.clone();
    preimage.remove("snapshot_id");
    if qualified_sha256(&serde_json::to_vec(&Value::Object(preimage))?) != snapshot_id {
        return Err(invalid("snapshot self-identity differs"));
    }
    let catalog_schema = manifest["catalog"]["catalog_schema"]
        .as_str()
        .ok_or_else(|| invalid("catalog schema is absent"))?;
    let version = catalog_schema
        .strip_prefix("joshi.sqlite.v")
        .and_then(|value| value.parse::<i64>().ok())
        .ok_or_else(|| invalid("catalog schema is invalid"))?;
    if !(MINIMUM_CATALOG_SCHEMA..=MAXIMUM_CATALOG_SCHEMA).contains(&version) {
        return Err(invalid("catalog schema is unsupported"));
    }
    let table_values = manifest["tables"]
        .as_array()
        .ok_or_else(|| invalid("snapshot tables must be an array"))?;
    let g0_profile = manifest_declares_g0_profile(version, table_values);
    let specs = table_specs(g0_profile);
    let from_commit_seq = manifest["catalog"]["from_commit_seq"]
        .as_str()
        .ok_or_else(|| invalid("catalog lower commit is absent"))?;
    let through_commit_seq = manifest["catalog"]["through_commit_seq"]
        .as_str()
        .ok_or_else(|| invalid("catalog upper commit is absent"))?;
    let from_commit = parse_manifest_commit(from_commit_seq, "catalog lower commit")?;
    let through_commit = parse_manifest_commit(through_commit_seq, "catalog upper commit")?;
    if from_commit == 0 || from_commit > through_commit {
        return Err(invalid("catalog commit range is invalid"));
    }
    if table_values.len() != specs.len() {
        return Err(invalid(
            "snapshot table set has the wrong exact cardinality",
        ));
    }
    let mut by_name = BTreeMap::new();
    for table in table_values {
        let name = table["name"]
            .as_str()
            .ok_or_else(|| invalid("snapshot table name is absent"))?;
        if by_name.insert(name, table).is_some() {
            return Err(invalid(format!("duplicate snapshot table {name}")));
        }
    }
    let expected_children = specs
        .iter()
        .map(|spec| format!("{}.parquet", spec.name))
        .chain(["manifest.json".to_owned()])
        .collect::<BTreeSet<_>>();
    let actual_children = fs::read_dir(root)
        .map_err(|error| ExportError::io(root, error))?
        .map(|entry| entry.map(|value| value.file_name().to_string_lossy().into_owned()))
        .collect::<std::result::Result<BTreeSet<_>, _>>()
        .map_err(|error| ExportError::io(root, error))?;
    if actual_children != expected_children {
        return Err(invalid(
            "snapshot directory has missing or unmanifested children",
        ));
    }
    let expected_table_keys = BTreeSet::from([
        "byte_length",
        "chain_bounds",
        "commit_bounds",
        "coverage",
        "event_bounds",
        "export_manifest_id",
        "logical_digest",
        "name",
        "path",
        "physical_digest",
        "primary_key",
        "row_count",
        "schema",
        "schema_digest",
        "schema_id",
    ]);
    let mut total_rows = 0_u64;
    let mut g0_rows = BTreeMap::new();
    for spec in &specs {
        let table = by_name
            .get(spec.name)
            .ok_or_else(|| invalid(format!("missing snapshot table {}", spec.name)))?;
        let table_object = table
            .as_object()
            .ok_or_else(|| invalid("snapshot table manifest must be an object"))?;
        if table_object
            .keys()
            .map(String::as_str)
            .collect::<BTreeSet<_>>()
            != expected_table_keys
        {
            return Err(invalid(format!("{} manifest keys differ", spec.name)));
        }
        let path_name = format!("{}.parquet", spec.name);
        if table["path"] != path_name
            || table["schema_id"] != spec.schema_id
            || table["primary_key"] != json!(spec.primary_key)
        {
            return Err(invalid(format!(
                "{} identity/schema path differs",
                spec.name
            )));
        }
        let path = root.join(&path_name);
        let metadata =
            fs::symlink_metadata(&path).map_err(|error| ExportError::io(&path, error))?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(invalid(format!("{} is not a real regular file", spec.name)));
        }
        if table["byte_length"].as_u64() != Some(metadata.len())
            || table["physical_digest"].as_str() != Some(&qualified_sha256_file(&path)?)
        {
            return Err(invalid(format!("{} physical closure differs", spec.name)));
        }
        let batches = read_parquet(&path)?;
        let schema = spec.schema();
        if batches.first().map(RecordBatch::schema).as_deref() != Some(&schema) {
            return Err(invalid(format!("{} Arrow schema differs", spec.name)));
        }
        let descriptor = schema_descriptor(&schema)?;
        if table["schema"] != descriptor
            || table["schema_digest"].as_str()
                != Some(&qualified_sha256(&serde_json::to_vec(&descriptor)?))
            || table["logical_digest"].as_str()
                != Some(&logical_table_digest(&batches, spec.primary_key)?)
        {
            return Err(invalid(format!("{} typed relation differs", spec.name)));
        }
        let rows = batches
            .iter()
            .try_fold(0_u64, |sum, batch| {
                sum.checked_add(u64::try_from(batch.num_rows()).ok()?)
            })
            .ok_or_else(|| invalid("snapshot row count exceeds u64"))?;
        if table["row_count"].as_u64() != Some(rows)
            || table["commit_bounds"]
                != json!({
                    "from_commit_seq": from_commit_seq,
                    "through_commit_seq": through_commit_seq,
                })
            || table["event_bounds"] != event_bounds(spec.name, &batches)?
            || table["coverage"] != coverage_manifest(spec.name, &batches)?
            || !table["chain_bounds"].is_null()
        {
            return Err(invalid(format!(
                "{} row/bounds/coverage differs",
                spec.name
            )));
        }
        for (commit_index, field) in schema.fields().iter().enumerate() {
            if !field.name().ends_with("commit_seq") {
                continue;
            }
            let commits = batches
                .iter()
                .map(|batch| {
                    batch
                        .column(commit_index)
                        .as_any()
                        .downcast_ref::<Int64Array>()
                        .ok_or_else(|| invalid("commit column is not int64"))
                })
                .collect::<Result<Vec<_>>>()?;
            if commits.iter().any(|values| {
                (0..values.len()).any(|index| {
                    !values.is_null(index)
                        && (values.value(index) < from_commit
                            || values.value(index) > through_commit)
                })
            }) {
                return Err(invalid(format!(
                    "{} {} escapes the exact catalog range",
                    spec.name,
                    field.name()
                )));
            }
        }
        total_rows = total_rows
            .checked_add(rows)
            .ok_or_else(|| invalid("snapshot total row count exceeds u64"))?;
        if g0_profile && G0_TABLE_SPECS.iter().any(|g0| g0.name == spec.name) {
            g0_rows.insert(spec.name, relation_rows(&batches)?);
        }
    }
    if g0_profile {
        crate::g0::validate_connected_closure(&g0_rows)?;
        crate::g0::validate_manifest_publication(&g0_rows, &manifest["publications"])?;
    }
    validation_receipt(
        "rust_independent_readback",
        snapshot_id,
        &qualified_sha256(&manifest_bytes),
        u64::try_from(specs.len()).map_err(|_| invalid("table count exceeds u64"))?,
        total_rows,
    )
}

fn validate_request(value: &OperationalExportRequestV2) -> Result<()> {
    if value.destination.exists() {
        return Err(ExportError::DestinationExists(value.destination.clone()));
    }
    let Some(version) = value.catalog_schema.as_str().strip_prefix("joshi.sqlite.v") else {
        return Err(invalid("catalog schema or commit range is invalid"));
    };
    let Ok(version) = version.parse::<i64>() else {
        return Err(invalid("catalog schema or commit range is invalid"));
    };
    if !(MINIMUM_CATALOG_SCHEMA..=MAXIMUM_CATALOG_SCHEMA).contains(&version)
        || value.from_commit_seq.get() == 0
        || value.from_commit_seq > value.through_commit_seq
    {
        return Err(invalid("catalog schema or commit range is invalid"));
    }
    if value.publications.is_empty()
        || value
            .publications
            .windows(2)
            .any(|window| window[0].id() >= window[1].id())
    {
        return Err(invalid(
            "publication closure must be strictly sorted and non-empty",
        ));
    }
    if value
        .coverage_window_ids
        .windows(2)
        .any(|window| window[0] >= window[1])
    {
        return Err(invalid(
            "coverage window selection must be strictly sorted and unique",
        ));
    }
    if !value.publications.iter().any(|item| {
        matches!(item,
        OperationalPublicationV2::Projection(projection)
        if projection.publication_id == value.producer_projection_publication_id)
    }) {
        return Err(invalid(
            "producer publication is not in projection publication closure",
        ));
    }
    let metadata = fs::symlink_metadata(&value.catalog_snapshot_path)
        .map_err(|error| ExportError::io(&value.catalog_snapshot_path, error))?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(invalid("catalog snapshot must be a real regular file"));
    }
    Ok(())
}

fn validate_catalog(connection: &Connection, request: &OperationalExportRequestV2) -> Result<i64> {
    let application: i32 =
        connection.pragma_query_value(None, "application_id", |row| row.get(0))?;
    let version: i64 = connection.pragma_query_value(None, "user_version", |row| row.get(0))?;
    let cutoff = i64::try_from(request.through_commit_seq.get())
        .map_err(|_| invalid("cutoff exceeds SQLite i64"))?;
    if application != APPLICATION_ID
        || request.catalog_schema.as_str() != format!("joshi.sqlite.v{version}")
        || !(MINIMUM_CATALOG_SCHEMA..=MAXIMUM_CATALOG_SCHEMA).contains(&version)
    {
        return Err(invalid("catalog application/schema/cutoff closure differs"));
    }
    let exists: i64 = connection.query_row(
        "SELECT COUNT(*) FROM ingest_commit WHERE commit_seq=?1",
        [cutoff],
        |row| row.get(0),
    )?;
    if exists != 1 {
        return Err(invalid("catalog cutoff is not a committed occurrence"));
    }
    let migration_count: i64 =
        connection.query_row("SELECT COUNT(*) FROM schema_migration", [], |row| {
            row.get(0)
        })?;
    if migration_count != version {
        return Err(invalid("catalog migration ledger length differs"));
    }
    for (id, name, sql) in MIGRATIONS
        .into_iter()
        .take(usize::try_from(version).map_err(|_| invalid("catalog schema exceeds usize"))?)
    {
        let stored: (String, String) = connection.query_row(
            "SELECT name,source_sha256 FROM schema_migration WHERE migration_id=?1",
            [id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        if stored.0 != name || stored.1 != format!("{:x}", Sha256::digest(sql.as_bytes())) {
            return Err(invalid(format!(
                "catalog migration {id} differs from compiled source"
            )));
        }
    }
    Ok(version)
}

/// Row families introduced after V10 that no frozen Snapshot V2 relation represents.
///
/// Every one of these is refused when populated inside the window, so raising the accepted
/// catalog schema ceiling can never turn into a silently narrower snapshot.
const UNMAPPED_AFTER_V10: [(&str, &str); 13] = [
    (
        "wave6_program_registration_v1",
        "Wave 6 program registration",
    ),
    (
        "wave6_registered_artifact_schema_v1",
        "Wave 6 registered artifact schema",
    ),
    (
        "wave6_fixture_artifact_content_v1",
        "Wave 6 fixture artifact content",
    ),
    (
        "wave6_fixture_artifact_dag_v1",
        "Wave 6 fixture artifact DAG",
    ),
    (
        "wave6_fixture_decision_ledger_v1",
        "Wave 6 fixture decision ledger",
    ),
    (
        "wave6_fixture_campaign_bundle_v1",
        "Wave 6 fixture campaign bundle",
    ),
    (
        "wave6_fixture_research_proposal_v1",
        "Wave 6 fixture research proposal",
    ),
    (
        "wave6_fixture_research_disposition_v1",
        "Wave 6 fixture research disposition",
    ),
    (
        "wave6_fixture_market_atlas_v1",
        "Wave 6 fixture market atlas",
    ),
    ("wave6_store_input_census_v1", "Wave 6 store input census"),
    (
        "cockpit_v2_browser_presentation_v1",
        "Cockpit V2 browser presentation",
    ),
    (
        "wave6_operator_evidence_input_v1",
        "Wave 6 operator evidence input",
    ),
    ("wave5_c1_activation_v1", "Wave 5 C1 activation"),
];

fn refuse_unmapped_operational_facts(
    connection: &Connection,
    from: CommitSeq,
    cutoff: CommitSeq,
    catalog_version: i64,
) -> Result<()> {
    let from = sql_commit(from)?;
    let cutoff = sql_commit(cutoff)?;
    let mut unmapped = vec![
        ("episode_protocol_v1", "prospective episode protocol"),
        ("episode_launch_v1", "prospective episode launch"),
        ("episode_pairing_session_v1", "prospective pairing session"),
        (
            "operator_prospective_nomination_v1",
            "prospective nomination",
        ),
        ("operator_explicit_abstention_v1", "explicit abstention"),
    ];
    if catalog_version < 10 {
        unmapped.push(("source_fact_artifact", "typed source/fact artifact"));
    }
    if catalog_version > 10 {
        unmapped.extend(UNMAPPED_AFTER_V10);
    }
    for (table, label) in unmapped {
        if rows_in_range(connection, table, "created_commit_seq", from, cutoff)? != 0 {
            return Err(invalid(format!(
                "catalog contains {label} rows without a frozen Snapshot V2 relation adapter"
            )));
        }
    }
    if catalog_version == 9 {
        for (table, label) in [
            ("wave5_run_registration_v1", "Wave 5 run registration"),
            (
                "wave5_spool_catalog_binding_v1",
                "Wave 5 spool/catalog binding",
            ),
            ("wave5_operational_record_v1", "Wave 5 operational record"),
            (
                "wave5_export_validation_binding_v1",
                "Wave 5 export-validation binding",
            ),
            ("wave5_restricted_artifact_v1", "Wave 5 restricted artifact"),
        ] {
            if rows_in_range(connection, table, "created_commit_seq", from, cutoff)? != 0 {
                return Err(invalid(format!(
                    "catalog contains {label} rows without a frozen Snapshot V2 relation adapter"
                )));
            }
        }
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
fn load_publications(
    connection: &Connection,
    request: &OperationalExportRequestV2,
    g0_profile: bool,
) -> Result<PublicationClosure> {
    let from = sql_commit(request.from_commit_seq)?;
    let cutoff = sql_commit(request.through_commit_seq)?;
    let mut projections = Vec::new();
    let mut rows = Vec::new();
    let mut ids = Vec::new();
    for item in &request.publications {
        match item {
            OperationalPublicationV2::Projection(publication) => {
                let stored: (
                    Vec<u8>,
                    Vec<u8>,
                    String,
                    String,
                    String,
                    i64,
                    i64,
                    String,
                    String,
                ) = connection.query_row(
                    "SELECT artifact_bytes,publication_bytes,result_sha256,artifact_sha256,
                            input_closure_sha256,through_commit_seq,created_commit_seq,
                            publication_sha256,publication_bytes_sha256
                     FROM projection_publication WHERE publication_id=?1
                     AND created_commit_seq BETWEEN ?2 AND ?3",
                    params![publication.publication_id.as_str(), from, cutoff],
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
                )?;
                if bare(&publication.result_digest)? != stored.2
                    || bare(&publication.artifact_digest)? != stored.3
                    || bare(&publication.input_closure_digest)? != stored.4
                    || sql_commit(publication.through_commit_seq)? != stored.5
                    || sql_commit(publication.published_commit_seq)? != stored.6
                    || stored.6 > cutoff
                    || bare(&publication.publication_digest)? != stored.7
                    || bare(&publication.publication_bytes_digest)? != stored.8
                    || qualified_sha256(&stored.0) != publication.artifact_digest.as_str()
                    || qualified_sha256(&stored.1) != publication.publication_bytes_digest.as_str()
                {
                    return Err(invalid(format!(
                        "projection publication {} differs from exact stored closure",
                        publication.publication_id
                    )));
                }
                rows.push(json!({
                    "kind":"projection", "publication_id":publication.publication_id,
                    "publication_contract":publication.publication_contract,
                    "publication_digest":publication.publication_digest,
                    "publication_bytes_digest":publication.publication_bytes_digest,
                    "projection_id":publication.projection_id,
                    "projection_name":publication.projection_name, "projection_version":publication.projection_version,
                    "result_digest":publication.result_digest, "artifact_digest":publication.artifact_digest,
                    "input_closure_digest":publication.input_closure_digest,
                    "through_commit_seq":publication.through_commit_seq.get().to_string(),
                    "published_commit_seq":publication.published_commit_seq.get().to_string(),
                    "authority":"read_only_no_execution"
                }));
                ids.push(publication.publication_id.clone());
                projections.push(publication.clone());
            }
            OperationalPublicationV2::Cockpit(publication) => {
                let stored: (
                    Vec<u8>,
                    String,
                    String,
                    String,
                    String,
                    String,
                    String,
                    i64,
                    String,
                    String,
                ) = connection.query_row(
                    "SELECT manifest_bytes,manifest_sha256,cockpit_publication_sha256,
                            projection_publication_id,projection_publication_sha256,
                            projection_result_sha256,projection_artifact_sha256,
                            created_commit_seq,scene_id,query_policy
                     FROM cockpit_publication WHERE cockpit_publication_id=?1
                     AND created_commit_seq BETWEEN ?2 AND ?3",
                    params![publication.publication_id.as_str(), from, cutoff],
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
                        ))
                    },
                )?;
                if bare(&publication.manifest_digest)? != stored.1
                    || bare(&publication.publication_digest)? != stored.2
                    || publication.projection_publication_id.as_str() != stored.3
                    || bare(&publication.projection_publication_digest)? != stored.4
                    || bare(&publication.result_digest)? != stored.5
                    || bare(&publication.artifact_digest)? != stored.6
                    || sql_commit(publication.published_commit_seq)? != stored.7
                    || stored.7 > cutoff
                    || publication.scene_id.as_str() != stored.8
                    || publication.query_policy.as_str() != stored.9
                    || qualified_sha256(&stored.0) != publication.manifest_digest.as_str()
                {
                    return Err(invalid(format!(
                        "cockpit publication {} differs from exact stored closure",
                        publication.publication_id
                    )));
                }
                rows.push(json!({
                    "kind":"cockpit", "publication_id":publication.publication_id,
                    "publication_contract":publication.publication_contract,
                    "publication_digest":publication.publication_digest,
                    "manifest_digest":publication.manifest_digest,
                    "scene_id":publication.scene_id,
                    "projection_publication_id":publication.projection_publication_id,
                    "projection_publication_digest":publication.projection_publication_digest,
                    "result_digest":publication.result_digest, "artifact_digest":publication.artifact_digest,
                    "query_policy":publication.query_policy,
                    "published_commit_seq":publication.published_commit_seq.get().to_string(),
                    "authority":"read_only_no_execution"
                }));
                ids.push(publication.publication_id.clone());
            }
        }
    }
    if g0_profile {
        let mut statement = connection.prepare(
            "SELECT p.publication_id,p.publication_contract,p.publication_sha256,
                    p.publication_bytes_sha256,p.publication_bytes,p.source_occurrence_id,
                    p.semantic_sha256,p.container_sha256,p.checkpoint_sha256,p.through_commit_seq,
                    p.supersedes_publication_id,p.created_commit_seq,h.head_sha256,h.head_bytes,
                    h.supersedes_head_publication_id,h.created_commit_seq,h.authority
             FROM cockpit_v2_publication_v1 p JOIN cockpit_v2_head_v1 h USING(publication_id)
             JOIN cockpit_v2_preparation_v1 prep ON prep.preparation_id=p.preparation_id
                 AND prep.source_occurrence_id=p.source_occurrence_id
             JOIN wave5_source_occurrence_v1 s USING(source_occurrence_id)
             WHERE p.created_commit_seq BETWEEN ?1 AND ?2
               AND h.created_commit_seq BETWEEN ?1 AND ?2
               AND prep.created_commit_seq BETWEEN ?1 AND ?2
               AND s.created_commit_seq BETWEEN ?1 AND ?2
               AND p.through_commit_seq BETWEEN ?1 AND ?2
               AND prep.through_commit_seq BETWEEN ?1 AND ?2
               AND s.known_through_commit_seq BETWEEN ?1 AND ?2
             ORDER BY p.publication_id",
        )?;
        let stored = statement
            .query_map(params![from, cutoff], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, Vec<u8>>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                    row.get::<_, String>(8)?,
                    row.get::<_, i64>(9)?,
                    row.get::<_, Option<String>>(10)?,
                    row.get::<_, i64>(11)?,
                    row.get::<_, String>(12)?,
                    row.get::<_, Vec<u8>>(13)?,
                    row.get::<_, Option<String>>(14)?,
                    row.get::<_, i64>(15)?,
                    row.get::<_, String>(16)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        if stored.is_empty() {
            return Err(invalid("V10 requires a headed Cockpit V2 publication"));
        }
        for value in stored {
            let publication = parse_cockpit_v2_publication(&value.4)
                .map_err(|error| invalid(format!("stored Cockpit V2 publication: {error}")))?;
            let head = parse_cockpit_v2_head(&value.13)
                .map_err(|error| invalid(format!("stored Cockpit V2 head: {error}")))?;
            head.validate_against(&publication)
                .map_err(|error| invalid(format!("stored Cockpit V2 head/body: {error}")))?;
            if format!("{:x}", Sha256::digest(&value.4)) != value.3
                || publication.publication_id.as_str() != value.0.as_str()
                || publication.contract.as_str() != value.1.as_str()
                || publication.publication_digest.as_str() != qualified_raw(&value.2)
                || publication.manifest.semantic_digest.as_str() != qualified_raw(&value.6)
                || publication.manifest.container_digest.as_str() != qualified_raw(&value.7)
                || publication.checkpoint.checkpoint_digest.as_str() != qualified_raw(&value.8)
                || i64::try_from(publication.commit_seq.get()).ok() != Some(value.11)
                || head.head_digest.as_str() != qualified_raw(&value.12)
            {
                return Err(invalid(
                    "stored Cockpit V2 publication/head semantic closure differs",
                ));
            }
            ids.push(stable(&value.0)?);
            rows.push(json!({
                "kind":"cockpit_v2",
                "publication_id":value.0,
                "publication_contract":value.1,
                "publication_digest":qualified_raw(&value.2),
                "publication_bytes_digest":qualified_raw(&value.3),
                "source_occurrence_id":value.5,
                "semantic_digest":qualified_raw(&value.6),
                "container_digest":qualified_raw(&value.7),
                "checkpoint_digest":qualified_raw(&value.8),
                "through_commit_seq":value.9.to_string(),
                "supersedes_publication_id":value.10,
                "publication_commit_seq":value.11.to_string(),
                "head_digest":qualified_raw(&value.12),
                "supersedes_head_publication_id":value.14,
                "published_commit_seq":value.15.to_string(),
                "authority":value.16,
            }));
        }
    }
    rows.sort_by(|left, right| {
        left["publication_id"]
            .as_str()
            .cmp(&right["publication_id"].as_str())
    });
    ids.sort();
    if ids.windows(2).any(|window| window[0] == window[1]) {
        return Err(invalid("publication closure contains a duplicate identity"));
    }
    Ok(PublicationClosure {
        manifest_rows: rows,
        projections,
        publication_ids: ids,
    })
}

/// The as-known source vector at the cutoff.
///
/// This is a knowledge statement about the catalog at `cutoff`, not a row selection, so it is
/// deliberately not narrowed by `from_commit_seq`. Narrowing it made a window that excluded a
/// source's first observations report that source as absent, while the same window still carried
/// that source's assertions and coverage.
fn source_as_of(connection: &Connection, cutoff: CommitSeq) -> Result<Vec<Value>> {
    let mut statement = connection.prepare(
        "SELECT o.source_id,MAX(o.commit_seq),MAX(o.received_wall_us)
         FROM observation o WHERE o.commit_seq BETWEEN ?1 AND ?2
         GROUP BY o.source_id ORDER BY o.source_id",
    )?;
    let from = 1_i64;
    let cutoff = sql_commit(cutoff)?;
    let source_rows = statement.query_map(params![from, cutoff], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, i64>(2)?,
        ))
    })?;
    let mut output = Vec::new();
    for source in source_rows {
        let (source_id, delivered, received) = source?;
        let mut cursor_statement = connection.prepare(
            "SELECT c.scope_kind,cc.scope_subject,c.cursor_kind,c.cursor_value,c.advanced_commit_seq
             FROM source_cursor c JOIN source_cursor_contract cc USING(cursor_id)
             WHERE c.source_id=?1 AND c.advanced_commit_seq BETWEEN ?2 AND ?3 AND NOT EXISTS (
                SELECT 1 FROM source_cursor later WHERE later.source_id=c.source_id
                AND later.scope_kind=c.scope_kind AND later.scope_key=c.scope_key
                AND later.cursor_kind=c.cursor_kind
                AND later.advanced_commit_seq BETWEEN ?2 AND ?3
                AND (later.advanced_commit_seq>c.advanced_commit_seq OR
                     (later.advanced_commit_seq=c.advanced_commit_seq AND later.cursor_id>c.cursor_id)))
             ORDER BY c.scope_kind,COALESCE(cc.scope_subject,''),c.cursor_kind")?;
        let cursors = cursor_statement.query_map(params![source_id, from, cutoff], |row| {
            Ok(json!({"family":row.get::<_,String>(0)?,"subject":row.get::<_,Option<String>>(1)?,
                "cursor_kind":row.get::<_,String>(2)?,"value":row.get::<_,String>(3)?,
                "advanced_through":row.get::<_,i64>(4)?.to_string()}))
        })?.collect::<std::result::Result<Vec<_>,_>>()?;
        output.push(
            json!({"source_id":source_id,"delivered_through":delivered.to_string(),
            "scoped_cursors":cursors,"received_through":timestamp_us(received)?.to_string()}),
        );
    }
    Ok(output)
}

fn chain_as_of(connection: &Connection, from: CommitSeq, cutoff: CommitSeq) -> Result<Value> {
    let value: Option<i64> = connection.query_row(
        "SELECT MAX(chain_slot) FROM observation WHERE commit_seq BETWEEN ?1 AND ?2
         AND chain_commitment='finalized'",
        params![sql_commit(from)?, sql_commit(cutoff)?],
        |row| row.get(0),
    )?;
    Ok(value.map_or(Value::Null, |slot| json!({"cluster":"solana:mainnet-beta","slot":slot.to_string(),"finality":"finalized"})))
}

fn scene_batch(connection: &Connection, from: CommitSeq, cutoff: CommitSeq) -> Result<RecordBatch> {
    let mut statement = connection.prepare(
        "SELECT scene_id,scene_mode,view_contract,view_contract_version,view_sha256,source_mode,
                rendered_wall_us,knowledge_cutoff_commit_seq,captured_commit_seq
         FROM scene WHERE captured_commit_seq BETWEEN ?1 AND ?2
         AND knowledge_cutoff_commit_seq BETWEEN ?1 AND ?2
         AND (outcome_cutoff_commit_seq IS NULL OR outcome_cutoff_commit_seq BETWEEN ?1 AND ?2)
         ORDER BY scene_id",
    )?;
    let rows = statement
        .query_map(params![sql_commit(from)?, sql_commit(cutoff)?], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, i64>(6)?,
                row.get::<_, i64>(7)?,
                row.get::<_, i64>(8)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let strings = |index: usize| -> ArrayRef {
        Arc::new(StringArray::from(
            rows.iter()
                .map(|row| match index {
                    0 => row.0.clone(),
                    1 => row.1.clone(),
                    2 => row.2.clone(),
                    3 => row.3.to_string(),
                    4 => format!("sha256:{}", row.4),
                    5 => row.5.clone(),
                    _ => unreachable!(),
                })
                .collect::<Vec<_>>(),
        ))
    };
    let rendered = rows.iter().map(|row| row.6).collect::<Vec<_>>();
    let arrays: Vec<ArrayRef> = vec![
        strings(0),
        strings(1),
        strings(2),
        strings(3),
        strings(4),
        strings(5),
        Arc::new(TimestampMicrosecondArray::from(rendered.clone()).with_timezone("UTC")),
        Arc::new(TimestampMicrosecondArray::from(rendered).with_timezone("UTC")),
        Arc::new(Int64Array::from(
            rows.iter().map(|row| row.7).collect::<Vec<_>>(),
        )),
        Arc::new(Int64Array::from(
            rows.iter().map(|row| row.8).collect::<Vec<_>>(),
        )),
    ];
    RecordBatch::try_new(Arc::new(TABLE_SPECS[0].schema()), arrays).map_err(ExportError::Arrow)
}

fn relation_batches(
    scenes: &RecordBatch,
    provenance_assertions: &RecordBatch,
    coverage_windows: &RecordBatch,
    coverage_gaps: &RecordBatch,
) -> BTreeMap<&'static str, Vec<RecordBatch>> {
    let mut output = BTreeMap::new();
    for spec in TABLE_SPECS {
        let batch = match spec.name {
            "scenes" => scenes.clone(),
            "provenance_assertions" => provenance_assertions.clone(),
            "coverage_windows" => coverage_windows.clone(),
            "coverage_gaps" => coverage_gaps.clone(),
            _ => RecordBatch::new_empty(Arc::new(spec.schema())),
        };
        output.insert(spec.name, vec![batch]);
    }
    output
}

fn maximum_scene_clock(batch: &RecordBatch) -> Option<UtcTimestamp> {
    let index = batch.schema().index_of("decision_available_at").ok()?;
    let values = batch
        .column(index)
        .as_any()
        .downcast_ref::<TimestampMicrosecondArray>()?;
    (0..values.len())
        .map(|index| values.value(index))
        .max()
        .and_then(|value| timestamp_us(value).ok())
}

fn projection_as_of(values: &[ProjectionPublicationInputV2]) -> Result<Vec<Value>> {
    let mut rows = values
        .iter()
        .map(|value| {
            json!({"name":value.projection_name,
        "version":value.projection_version,"state_digest":value.result_digest,
        "delivered_through":value.through_commit_seq.get().to_string()})
        })
        .collect::<Vec<_>>();
    rows.sort_by(|left, right| left["name"].as_str().cmp(&right["name"].as_str()));
    if rows
        .windows(2)
        .any(|window| window[0]["name"] == window[1]["name"])
    {
        return Err(invalid("as-of projection names must be unique"));
    }
    Ok(rows)
}

fn truth_fingerprint(
    connection: &Connection,
    from: CommitSeq,
    cutoff: CommitSeq,
    publications: &PublicationClosure,
) -> Result<Value> {
    let from = sql_commit(from)?;
    let cutoff = sql_commit(cutoff)?;
    let observations: i64 = connection.query_row(
        "SELECT COUNT(*) FROM observation WHERE commit_seq BETWEEN ?1 AND ?2",
        params![from, cutoff],
        |row| row.get(0),
    )?;
    let assertions: i64 = connection.query_row(
        "SELECT COUNT(*) FROM assertion WHERE produced_commit_seq BETWEEN ?1 AND ?2",
        params![from, cutoff],
        |row| row.get(0),
    )?;
    let effects: i64 = connection.query_row("SELECT COUNT(*) FROM assertion WHERE produced_commit_seq BETWEEN ?1 AND ?2 AND assertion_kind LIKE 'wallet_effect%'",params![from, cutoff],|row|row.get(0))?;
    let mut evidence = Sha256::new();
    for sql in [
        "SELECT observation_id||'|'||commit_seq||'|'||blob_id FROM observation WHERE commit_seq BETWEEN ?1 AND ?2 ORDER BY observation_id",
        "SELECT assertion_id||'|'||produced_commit_seq||'|'||value_sha256 FROM assertion WHERE produced_commit_seq BETWEEN ?1 AND ?2 ORDER BY assertion_id",
    ] {
        let mut statement = connection.prepare(sql)?;
        for row in statement.query_map(params![from, cutoff], |row| row.get::<_, String>(0))? {
            evidence.update(row?.as_bytes());
            evidence.update(b"\n");
        }
    }
    let projection_digest = qualified_sha256(&serde_json::to_vec(&publications.manifest_rows)?);
    Ok(
        json!({"evidence_digest":format!("sha256:{:x}",evidence.finalize()),
        "projection_digest":projection_digest,"observation_count":observations.to_string(),
        "assertion_count":assertions.to_string(),"financial_effect_count":effects.to_string()}),
    )
}

fn event_bounds(name: &str, batches: &[RecordBatch]) -> Result<Value> {
    let field = match name {
        "scenes" => Some("rendered_at"),
        "territories" => Some("first_available_at"),
        "candidates" => Some("created_at"),
        "candidate_social_assertions" | "chart_samples" | "outcomes" => Some("event_time"),
        "decisions" => Some("decision_available_at"),
        "choice_members" => Some("available_at"),
        "episodes" | "coverage_gaps" => Some("opened_at"),
        "operator_gestures" => Some("issued_at"),
        "operator_interviews" => Some("elicited_at"),
        "provenance_assertions" | "status_occurrences" => Some("observed_at"),
        "coverage_windows" => Some("lower_time"),
        "source_fact_occurrences" | "import_occurrences" => Some("maximum_input_available_at"),
        _ => None,
    };
    let Some(field) = field else {
        return Ok(Value::Null);
    };
    let Some(batch) = batches.first() else {
        return Ok(Value::Null);
    };
    let index = batch.schema().index_of(field)?;
    let array = batch
        .column(index)
        .as_any()
        .downcast_ref::<TimestampMicrosecondArray>()
        .ok_or_else(|| invalid("event bound field is not timestamp"))?;
    let values = (0..array.len())
        .filter(|index| !array.is_null(*index))
        .map(|index| array.value(index))
        .collect::<Vec<_>>();
    if values.is_empty() {
        Ok(Value::Null)
    } else {
        Ok(
            json!({"lower_inclusive":timestamp_us(*values.iter().min().expect("nonempty"))?.to_string(),
        "upper_inclusive":timestamp_us(*values.iter().max().expect("nonempty"))?.to_string()}),
        )
    }
}

fn coverage_manifest(name: &str, batches: &[RecordBatch]) -> Result<Value> {
    let rows = batches.iter().map(RecordBatch::num_rows).sum::<usize>();
    let (observed, explicit_gaps) = if name == "chart_samples" {
        let mut observed = 0;
        let mut gaps = 0;
        for batch in batches {
            let index = batch.schema().index_of("coverage_status")?;
            let values = batch
                .column(index)
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| invalid("chart coverage status is not a string"))?;
            for index in 0..values.len() {
                match values.value(index) {
                    "observed" => observed += 1,
                    "gap" => gaps += 1,
                    _ => return Err(invalid("chart coverage status is unsupported")),
                }
            }
        }
        (observed, gaps)
    } else {
        (rows, 0)
    };
    let identities = |field: &str| -> Result<Vec<String>> {
        let mut values = Vec::new();
        for batch in batches {
            let Ok(index) = batch.schema().index_of(field) else {
                continue;
            };
            let array = batch
                .column(index)
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| invalid(format!("coverage identity {field} is not a string")))?;
            values.extend(
                (0..array.len())
                    .filter(|index| !array.is_null(*index))
                    .map(|index| array.value(index).to_owned()),
            );
        }
        values.sort();
        values.dedup();
        Ok(values)
    };
    Ok(
        json!({"expected_rows":rows,"observed_rows":observed,"explicit_gap_rows":explicit_gaps,
        "coverage_ratio_ppm":if rows==0{Value::Null}else{Value::from(u64::try_from(observed).map_err(|_|invalid("coverage count"))?*1_000_000/u64::try_from(rows).map_err(|_|invalid("coverage count"))?)},
        "coverage_scope_ids":identities("coverage_scope_id")?,
        "coverage_window_ids":identities("coverage_window_id")?,
        "coverage_gap_ids":identities("coverage_gap_id")?}),
    )
}

fn validation_receipt(
    validator: &'static str,
    snapshot_id: &str,
    manifest_digest: &str,
    table_count: u64,
    total_rows: u64,
) -> Result<ValidationReceiptV2> {
    let preimage = json!({"contract":VALIDATION_RECEIPT,"schemaVersion":2,"validator":validator,
        "snapshotId":snapshot_id,"manifestDigest":manifest_digest,"tableCount":table_count,"totalRowCount":total_rows});
    Ok(ValidationReceiptV2 {
        contract: VALIDATION_RECEIPT,
        schema_version: 2,
        validator,
        snapshot_id: digest(snapshot_id)?,
        manifest_digest: digest(manifest_digest)?,
        table_count,
        total_row_count: total_rows,
        receipt_digest: digest(&qualified_sha256(&serde_json::to_vec(&preimage)?))?,
    })
}

#[derive(Deserialize)]
struct PythonReceipt {
    contract: String,
    status: String,
    snapshot_id: String,
    manifest_digest: String,
    manifest_version: String,
    table_count: u64,
    total_row_count: u64,
    knowledge_mode: String,
}
fn run_python_validator(
    validator: &PythonValidatorV2,
    snapshot: &Path,
    snapshot_id: &str,
    manifest_digest: &str,
    total_rows: u64,
    table_count: usize,
) -> Result<ValidationReceiptV2> {
    let output = Command::new(&validator.program)
        .arg("--directory")
        .arg(&validator.analysis_directory)
        .args([
            "run",
            "--locked",
            "--offline",
            "joshi-analysis",
            "validate",
            "--snapshot",
        ])
        .arg(snapshot)
        .output()
        .map_err(|error| ExportError::io(&validator.program, error))?;
    if !output.status.success() {
        return Err(invalid(format!(
            "Python validation failed: {}",
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    let parsed: PythonReceipt = serde_json::from_slice(&output.stdout)?;
    if parsed.contract != "joshi.analysis.snapshot-validation-receipt/v1"
        || parsed.status != "valid"
        || parsed.snapshot_id != snapshot_id
        || parsed.manifest_digest != manifest_digest
        || parsed.manifest_version != SNAPSHOT_V2
        || parsed.table_count != u64::try_from(table_count).map_err(|_| invalid("table count"))?
        || parsed.total_row_count != total_rows
        || parsed.knowledge_mode != "as_known"
    {
        return Err(invalid(
            "Python validation receipt disagrees with Rust closure",
        ));
    }
    validation_receipt(
        "python_semantic_validator",
        snapshot_id,
        manifest_digest,
        parsed.table_count,
        total_rows,
    )
}

fn timestamp_us(value: i64) -> Result<UtcTimestamp> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or_else(|| invalid("timestamp overflow"))?;
    UtcTimestamp::new(
        time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
            .map_err(|error| invalid(error.to_string()))?,
    )
    .map_err(|error| invalid(error.to_string()))
}
fn sql_commit(value: CommitSeq) -> Result<i64> {
    i64::try_from(value.get()).map_err(|_| invalid("commit exceeds SQLite i64"))
}
fn bare(value: &ValueDigest) -> Result<String> {
    value
        .as_str()
        .strip_prefix("sha256:")
        .map(str::to_owned)
        .ok_or_else(|| invalid("digest algorithm is not sha256"))
}
fn qualified_raw(value: &str) -> String {
    format!("sha256:{value}")
}
fn stable(value: &str) -> Result<StableString> {
    StableString::new(value).map_err(|error| invalid(error.to_string()))
}
fn digest(value: &str) -> Result<ValueDigest> {
    ValueDigest::new(value).map_err(|error| invalid(error.to_string()))
}
fn invalid(message: impl Into<String>) -> ExportError {
    ExportError::Invalid(message.into())
}

fn parse_manifest_commit(value: &str, context: &str) -> Result<i64> {
    if value.is_empty()
        || !value.bytes().all(|byte| byte.is_ascii_digit())
        || (value.starts_with('0') && value != "0")
    {
        return Err(invalid(format!("{context} is not canonical")));
    }
    value
        .parse::<i64>()
        .map_err(|_| invalid(format!("{context} exceeds SQLite i64")))
}

#[cfg(test)]
mod tests {
    use super::{
        MAXIMUM_CATALOG_SCHEMA, MIGRATIONS, MINIMUM_CATALOG_SCHEMA, manifest_declares_g0_profile,
        table_specs,
    };
    use serde_json::json;

    #[test]
    fn the_compiled_migration_ledger_reaches_the_accepted_schema_ceiling() {
        // A catalog is refused unless every migration it recorded is one this build compiled in,
        // so the ceiling and the ledger have to move together. When they drifted apart the
        // exporter refused every current-generation store outright.
        assert_eq!(
            usize::try_from(MAXIMUM_CATALOG_SCHEMA).expect("ceiling fits a length"),
            MIGRATIONS.len()
        );
        assert_eq!(MINIMUM_CATALOG_SCHEMA, 8);
        for (index, (id, name, sql)) in MIGRATIONS.into_iter().enumerate() {
            assert_eq!(id, i64::try_from(index).expect("index fits") + 1);
            assert!(
                name.starts_with(&format!("{id:04}_")),
                "{name} is misordered"
            );
            assert!(!sql.is_empty());
        }
    }

    #[test]
    fn the_g0_profile_follows_the_manifest_rather_than_the_schema_number() {
        let v2_only = [json!({"name": "scenes"}), json!({"name": "coverage_gaps"})];
        let with_g0 = [
            json!({"name": "scenes"}),
            json!({"name": "run_occurrences"}),
        ];
        assert!(!manifest_declares_g0_profile(9, &v2_only));
        assert!(!manifest_declares_g0_profile(9, &with_g0));
        // V10 is the frozen twenty-four-table contract and stays that way whatever it declares.
        assert!(manifest_declares_g0_profile(10, &v2_only));
        assert!(!manifest_declares_g0_profile(24, &v2_only));
        assert!(manifest_declares_g0_profile(24, &with_g0));
        assert_eq!(table_specs(false).len(), 14);
        assert_eq!(table_specs(true).len(), 24);
    }
}
