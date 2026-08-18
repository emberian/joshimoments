use crate::{
    ExportError, Result,
    specs::{TABLE_SPECS, TableSpec},
};
use arrow_array::{
    Array, BinaryArray, BooleanArray, Decimal128Array, Int32Array, Int64Array, RecordBatch,
    StringArray, TimestampMicrosecondArray,
};
use arrow_schema::{DataType, Field, Schema, TimeUnit};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use parquet::{
    arrow::{ArrowWriter, arrow_reader::ParquetRecordBatchReaderBuilder},
    basic::{Compression, ZstdLevel},
    file::properties::{EnabledStatistics, WriterProperties, WriterVersion},
};
use serde::{
    Serialize,
    de::{DeserializeSeed, MapAccess, SeqAccess, Visitor},
};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{
    cmp::Ordering,
    collections::BTreeMap,
    fmt::Write as FmtWrite,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::Arc,
};

const MANIFEST_VERSION: &str = "joshi.analysis.snapshot/v1";
const MAX_MANIFEST_BYTES: u64 = 16 * 1024 * 1024;

/// Public status of the exact snapshot registration.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExportSnapshotStatus {
    /// Newly registered immutable snapshot.
    Accepted,
    /// Exact already-registered snapshot.
    Idempotent,
}

/// Durable public acknowledgement for the typed snapshot boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportSnapshotReceiptV1 {
    contract: &'static str,
    schema_version: u64,
    catalog_id: StableString,
    catalog_schema: StableString,
    snapshot_id: ValueDigest,
    manifest_digest: ValueDigest,
    commit_seq: CommitSeq,
    status: ExportSnapshotStatus,
}

impl ExportSnapshotReceiptV1 {
    /// Constructs a receipt only after storage reports durable registration/readback.
    #[must_use]
    pub fn durable(
        snapshot: &ValidatedExportSnapshotV1,
        commit_seq: CommitSeq,
        status: ExportSnapshotStatus,
    ) -> Self {
        Self {
            contract: "joshi.store.export_snapshot_receipt",
            schema_version: 1,
            catalog_id: snapshot.catalog_id.clone(),
            catalog_schema: snapshot.catalog_schema.clone(),
            snapshot_id: snapshot.snapshot_id.clone(),
            manifest_digest: snapshot.manifest_digest.clone(),
            commit_seq,
            status,
        }
    }

    /// Durable registration commit.
    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }
    /// New registration or exact retry.
    #[must_use]
    pub const fn status(&self) -> ExportSnapshotStatus {
        self.status
    }
}

/// One exact Parquet part proven by the frozen snapshot manifest.
#[derive(Clone, Debug)]
pub struct ValidatedTableArtifactV1 {
    pub(crate) name: StableString,
    pub(crate) export_manifest_id: StableString,
    pub(crate) schema_id: StableString,
    pub(crate) schema_digest: ValueDigest,
    pub(crate) physical_digest: ValueDigest,
    pub(crate) logical_digest: ValueDigest,
    pub(crate) relative_path: PathBuf,
    pub(crate) absolute_path: PathBuf,
    pub(crate) byte_length: u64,
    pub(crate) row_count: u64,
    pub(crate) from_commit_seq: CommitSeq,
    pub(crate) through_commit_seq: CommitSeq,
    pub(crate) ordinal: u64,
}

impl ValidatedTableArtifactV1 {
    /// Frozen table family.
    #[must_use]
    pub fn name(&self) -> &StableString {
        &self.name
    }

    /// Immutable part identity inside the manifest.
    #[must_use]
    pub fn export_manifest_id(&self) -> &StableString {
        &self.export_manifest_id
    }

    /// Accepted Arrow schema identity.
    #[must_use]
    pub fn schema_id(&self) -> &StableString {
        &self.schema_id
    }

    /// Digest of the exact Arrow schema descriptor.
    #[must_use]
    pub fn schema_digest(&self) -> &ValueDigest {
        &self.schema_digest
    }

    /// Exact Parquet-file digest.
    #[must_use]
    pub fn physical_digest(&self) -> &ValueDigest {
        &self.physical_digest
    }

    /// Canonical typed-relation digest.
    #[must_use]
    pub fn logical_digest(&self) -> &ValueDigest {
        &self.logical_digest
    }

    /// Direct child path named by the manifest.
    #[must_use]
    pub fn relative_path(&self) -> &Path {
        &self.relative_path
    }

    /// Materialized immutable source path for store installation.
    #[must_use]
    pub fn absolute_path(&self) -> &Path {
        &self.absolute_path
    }

    /// Exact file bytes.
    #[must_use]
    pub const fn byte_length(&self) -> u64 {
        self.byte_length
    }

    /// Exact logical rows.
    #[must_use]
    pub const fn row_count(&self) -> u64 {
        self.row_count
    }

    /// First represented catalog commit.
    #[must_use]
    pub const fn from_commit_seq(&self) -> CommitSeq {
        self.from_commit_seq
    }

    /// Last represented catalog commit.
    #[must_use]
    pub const fn through_commit_seq(&self) -> CommitSeq {
        self.through_commit_seq
    }

    /// Canonical table ordinal.
    #[must_use]
    pub const fn ordinal(&self) -> u64 {
        self.ordinal
    }
}

/// Complete exact snapshot capability accepted by durable storage.
#[derive(Clone, Debug)]
pub struct ValidatedExportSnapshotV1 {
    root: PathBuf,
    manifest_bytes: Vec<u8>,
    manifest_digest: ValueDigest,
    snapshot_id: ValueDigest,
    catalog_id: StableString,
    catalog_schema: StableString,
    from_commit_seq: CommitSeq,
    through_commit_seq: CommitSeq,
    producer_build: StableString,
    projection_name: StableString,
    projection_version: StableString,
    projection_state_digest: ValueDigest,
    tables: Vec<ValidatedTableArtifactV1>,
}

impl ValidatedExportSnapshotV1 {
    /// Final snapshot directory.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Exact canonical manifest bytes, including one trailing newline.
    #[must_use]
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.manifest_bytes
    }

    /// Digest of exact manifest bytes, distinct from snapshot identity.
    #[must_use]
    pub fn manifest_digest(&self) -> &ValueDigest {
        &self.manifest_digest
    }

    /// Snapshot self-identity: SHA-256 of canonical manifest preimage without `snapshot_id`.
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

    /// Closed catalog lower bound.
    #[must_use]
    pub const fn from_commit_seq(&self) -> CommitSeq {
        self.from_commit_seq
    }

    /// Closed catalog upper bound and as-of cutoff.
    #[must_use]
    pub const fn through_commit_seq(&self) -> CommitSeq {
        self.through_commit_seq
    }

    /// Exporter build identity.
    #[must_use]
    pub fn producer_build(&self) -> &StableString {
        &self.producer_build
    }

    /// Projection name.
    #[must_use]
    pub fn projection_name(&self) -> &StableString {
        &self.projection_name
    }

    /// Projection version.
    #[must_use]
    pub fn projection_version(&self) -> &StableString {
        &self.projection_version
    }

    /// Exact projection state digest.
    #[must_use]
    pub fn projection_state_digest(&self) -> &ValueDigest {
        &self.projection_state_digest
    }

    /// All fourteen table parts in frozen contract order.
    #[must_use]
    pub fn tables(&self) -> &[ValidatedTableArtifactV1] {
        &self.tables
    }
}

/// Rewrites a self-hashed V1 source snapshot through Rust Arrow/Parquet and returns a capability
/// whose exact schema/logical/physical/manifest closure has been recomputed.
///
/// This is the first honest bridge from the existing locked research projection to the Rust store.
/// Production query projection can replace the source reader without changing the output contract.
///
/// # Errors
///
/// Rejects a mutable destination, source hash/schema/logical drift, missing or duplicate table
/// closure, unsupported Arrow types, unsafe paths, and all I/O/Arrow/Parquet failures.
#[allow(clippy::too_many_lines)] // The immutable all-parts commit protocol is intentionally local.
pub fn rewrite_snapshot_v1(source: &Path, destination: &Path) -> Result<ValidatedExportSnapshotV1> {
    if destination.exists() {
        return Err(ExportError::DestinationExists(destination.to_owned()));
    }
    let source_manifest_path = source.join("manifest.json");
    let metadata = fs::symlink_metadata(&source_manifest_path)
        .map_err(|error| ExportError::io(&source_manifest_path, error))?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_MANIFEST_BYTES
    {
        return Err(ExportError::Invalid(
            "source manifest must be a bounded regular file".into(),
        ));
    }
    let source_manifest_bytes = fs::read(&source_manifest_path)
        .map_err(|error| ExportError::io(&source_manifest_path, error))?;
    let mut manifest = parse_json_without_duplicate_keys(&source_manifest_bytes)?;
    validate_manifest_head(&manifest)?;
    validate_snapshot_self_hash(&manifest)?;
    let parent = destination.parent().ok_or_else(|| {
        ExportError::Invalid("snapshot destination must have a parent directory".into())
    })?;
    fs::create_dir_all(parent).map_err(|error| ExportError::io(parent, error))?;
    let staging = tempfile::Builder::new()
        .prefix(".joshi-export-")
        .tempdir_in(parent)
        .map_err(|error| ExportError::io(parent, error))?;

    let tables_value = manifest
        .get_mut("tables")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| ExportError::Invalid("manifest tables must be an array".into()))?;
    if tables_value.len() != TABLE_SPECS.len() {
        return Err(ExportError::Invalid(
            "manifest must close over exactly fourteen V1 tables".into(),
        ));
    }
    let mut by_name = BTreeMap::new();
    for (index, table) in tables_value.iter().enumerate() {
        let name = table
            .get("name")
            .and_then(Value::as_str)
            .ok_or_else(|| ExportError::Invalid("table name is missing".into()))?;
        if by_name.insert(name.to_owned(), index).is_some() {
            return Err(ExportError::Invalid(format!("duplicate table {name}")));
        }
    }
    let mut artifacts = Vec::with_capacity(TABLE_SPECS.len());
    for (ordinal, spec) in TABLE_SPECS.iter().enumerate() {
        let index = *by_name
            .get(spec.name)
            .ok_or_else(|| ExportError::Invalid(format!("missing table {}", spec.name)))?;
        let table = tables_value
            .get_mut(index)
            .and_then(Value::as_object_mut)
            .ok_or_else(|| ExportError::Invalid("table manifest must be an object".into()))?;
        validate_table_manifest(spec, table)?;
        let relative = safe_direct_child(
            table
                .get("path")
                .and_then(Value::as_str)
                .ok_or_else(|| ExportError::Invalid("table path is missing".into()))?,
        )?;
        let source_path = source.join(&relative);
        let expected_physical = table
            .get("physical_digest")
            .and_then(Value::as_str)
            .ok_or_else(|| ExportError::Invalid("physical digest is missing".into()))?;
        if qualified_sha256_file(&source_path)? != expected_physical {
            return Err(ExportError::Invalid(format!(
                "source physical digest mismatch for {}",
                spec.name
            )));
        }
        let batches = read_parquet(&source_path)?;
        let schema = batches
            .first()
            .map(RecordBatch::schema)
            .ok_or_else(|| ExportError::Invalid(format!("{} has no record batch", spec.name)))?;
        let descriptor = schema_descriptor(&schema)?;
        if table.get("schema") != Some(&descriptor) {
            return Err(ExportError::Invalid(format!(
                "Arrow schema differs for {}",
                spec.name
            )));
        }
        let logical = logical_table_digest(&batches, spec.primary_key)?;
        if table.get("logical_digest").and_then(Value::as_str) != Some(logical.as_str()) {
            return Err(ExportError::Invalid(format!(
                "source logical digest mismatch for {}",
                spec.name
            )));
        }
        let schema_digest = qualified_sha256(&canonical_json(&descriptor)?);
        if table.get("schema_digest").and_then(Value::as_str) != Some(schema_digest.as_str()) {
            return Err(ExportError::Invalid(format!(
                "schema digest mismatch for {}",
                spec.name
            )));
        }
        let target_path = staging.path().join(&relative);
        write_parquet(&target_path, schema, &batches)?;
        let written_batches = read_parquet(&target_path)?;
        let written_schema = written_batches
            .first()
            .map(RecordBatch::schema)
            .ok_or_else(|| ExportError::Invalid(format!("{} output has no batch", spec.name)))?;
        if schema_descriptor(&written_schema)? != descriptor
            || logical_table_digest(&written_batches, spec.primary_key)? != logical
        {
            return Err(ExportError::Invalid(format!(
                "Rust Parquet readback differs for {}",
                spec.name
            )));
        }
        let physical = qualified_sha256_file(&target_path)?;
        let byte_length = fs::metadata(&target_path)
            .map_err(|error| ExportError::io(&target_path, error))?
            .len();
        let row_count = written_batches.iter().try_fold(0_u64, |total, batch| {
            u64::try_from(batch.num_rows())
                .ok()
                .and_then(|value| total.checked_add(value))
                .ok_or_else(|| ExportError::Invalid("table row count exceeds u64".into()))
        })?;
        table.insert("physical_digest".into(), Value::String(physical.clone()));
        table.insert("byte_length".into(), Value::from(byte_length));
        table.insert("row_count".into(), Value::from(row_count));
        table.insert("logical_digest".into(), Value::String(logical.clone()));
        table.insert("schema_digest".into(), Value::String(schema_digest.clone()));
        artifacts.push(artifact_from_manifest(
            spec,
            table,
            destination,
            relative,
            byte_length,
            row_count,
            ordinal,
        )?);
    }

    let producer = manifest
        .get_mut("producer")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| ExportError::Invalid("producer must be an object".into()))?;
    producer.insert(
        "build".into(),
        Value::String("joshi-rust-exporter/1".into()),
    );
    manifest
        .as_object_mut()
        .ok_or_else(|| ExportError::Invalid("manifest must be an object".into()))?
        .remove("snapshot_id");
    let snapshot_id_text = qualified_sha256(&canonical_json(&manifest)?);
    manifest
        .as_object_mut()
        .ok_or_else(|| ExportError::Invalid("manifest must be an object".into()))?
        .insert(
            "snapshot_id".into(),
            Value::String(snapshot_id_text.clone()),
        );
    let mut manifest_bytes = canonical_json(&manifest)?;
    manifest_bytes.push(b'\n');
    let manifest_path = staging.path().join("manifest.json");
    write_file_durable(&manifest_path, &manifest_bytes)?;
    sync_directory(staging.path())?;
    fs::rename(staging.path(), destination).map_err(|error| ExportError::io(destination, error))?;
    sync_directory(parent)?;
    // Prevent TempDir cleanup after the directory itself has moved.
    let _persisted = staging.keep();

    let catalog = manifest
        .get("catalog")
        .and_then(Value::as_object)
        .ok_or_else(|| ExportError::Invalid("catalog must be an object".into()))?;
    let producer = manifest
        .get("producer")
        .and_then(Value::as_object)
        .ok_or_else(|| ExportError::Invalid("producer must be an object".into()))?;
    let snapshot_id = digest_value(&snapshot_id_text, "snapshot_id")?;
    Ok(ValidatedExportSnapshotV1 {
        root: destination.to_owned(),
        manifest_digest: digest_value(&qualified_sha256(&manifest_bytes), "manifest digest")?,
        manifest_bytes,
        snapshot_id,
        catalog_id: stable_field(catalog, "catalog_id")?,
        catalog_schema: stable_field(catalog, "catalog_schema")?,
        from_commit_seq: commit_field(catalog, "from_commit_seq")?,
        through_commit_seq: commit_field(catalog, "through_commit_seq")?,
        producer_build: stable_field(producer, "build")?,
        projection_name: stable_field(producer, "projection_name")?,
        projection_version: stable_field(producer, "projection_version")?,
        projection_state_digest: digest_field(producer, "projection_state_digest")?,
        tables: artifacts,
    })
}

fn validate_manifest_head(value: &Value) -> Result<()> {
    let object = value
        .as_object()
        .ok_or_else(|| ExportError::Invalid("manifest must be an object".into()))?;
    let required = [
        "catalog",
        "created_at",
        "knowledge_mode",
        "manifest_version",
        "maximum_decision_available_at",
        "producer",
        "snapshot_id",
        "tables",
    ];
    if !required.iter().all(|key| object.contains_key(*key))
        || object
            .keys()
            .any(|key| !required.contains(&key.as_str()) && key != "scene")
    {
        return Err(ExportError::Invalid(
            "manifest top-level key closure differs from V1".into(),
        ));
    }
    if object.get("manifest_version").and_then(Value::as_str) != Some(MANIFEST_VERSION)
        || object.get("knowledge_mode").and_then(Value::as_str) != Some("as_known")
    {
        return Err(ExportError::Invalid(
            "unsupported manifest version or knowledge mode".into(),
        ));
    }
    Ok(())
}

fn validate_snapshot_self_hash(value: &Value) -> Result<()> {
    let expected = value
        .get("snapshot_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ExportError::Invalid("snapshot_id is missing".into()))?;
    let mut preimage = value.clone();
    preimage
        .as_object_mut()
        .ok_or_else(|| ExportError::Invalid("manifest must be an object".into()))?
        .remove("snapshot_id");
    let computed = qualified_sha256(&canonical_json(&preimage)?);
    if expected != computed {
        return Err(ExportError::Invalid(format!(
            "source snapshot_id mismatch: expected {expected}, computed {computed}"
        )));
    }
    Ok(())
}

fn validate_table_manifest(spec: &TableSpec, value: &Map<String, Value>) -> Result<()> {
    if value.get("schema_id").and_then(Value::as_str) != Some(spec.schema_id) {
        return Err(ExportError::Invalid(format!(
            "{} schema ID mismatch",
            spec.name
        )));
    }
    let keys = value
        .get("primary_key")
        .and_then(Value::as_array)
        .ok_or_else(|| ExportError::Invalid(format!("{} primary key missing", spec.name)))?
        .iter()
        .map(Value::as_str)
        .collect::<Option<Vec<_>>>()
        .ok_or_else(|| ExportError::Invalid(format!("{} primary key invalid", spec.name)))?;
    if keys != spec.primary_key {
        return Err(ExportError::Invalid(format!(
            "{} primary key mismatch",
            spec.name
        )));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn artifact_from_manifest(
    spec: &TableSpec,
    value: &Map<String, Value>,
    destination: &Path,
    relative: PathBuf,
    byte_length: u64,
    row_count: u64,
    ordinal: usize,
) -> Result<ValidatedTableArtifactV1> {
    let bounds = value
        .get("commit_bounds")
        .and_then(Value::as_object)
        .ok_or_else(|| ExportError::Invalid(format!("{} commit bounds missing", spec.name)))?;
    Ok(ValidatedTableArtifactV1 {
        name: StableString::new(spec.name)
            .map_err(|error| ExportError::Invalid(error.to_string()))?,
        export_manifest_id: stable_field(value, "export_manifest_id")?,
        schema_id: StableString::new(spec.schema_id)
            .map_err(|error| ExportError::Invalid(error.to_string()))?,
        schema_digest: digest_field(value, "schema_digest")?,
        physical_digest: digest_field(value, "physical_digest")?,
        logical_digest: digest_field(value, "logical_digest")?,
        absolute_path: destination.join(&relative),
        relative_path: relative,
        byte_length,
        row_count,
        from_commit_seq: commit_field(bounds, "from_commit_seq")?,
        through_commit_seq: commit_field(bounds, "through_commit_seq")?,
        ordinal: u64::try_from(ordinal)
            .map_err(|_| ExportError::Invalid("table ordinal exceeds u64".into()))?,
    })
}

pub(crate) fn read_parquet(path: &Path) -> Result<Vec<RecordBatch>> {
    let file = File::open(path).map_err(|error| ExportError::io(path, error))?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file)?;
    let schema = builder.schema().clone();
    let mut batches = builder
        .build()?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(ExportError::Arrow)?;
    if batches.is_empty() {
        batches.push(RecordBatch::new_empty(schema));
    }
    Ok(batches)
}

pub(crate) fn write_parquet(
    path: &Path,
    schema: Arc<Schema>,
    batches: &[RecordBatch],
) -> Result<()> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| ExportError::io(path, error))?;
    let properties = WriterProperties::builder()
        .set_compression(Compression::ZSTD(ZstdLevel::default()))
        .set_dictionary_enabled(false)
        .set_statistics_enabled(EnabledStatistics::Page)
        .set_writer_version(WriterVersion::PARQUET_2_0)
        .build();
    let mut writer = ArrowWriter::try_new(file, schema, Some(properties))?;
    for batch in batches {
        writer.write(batch)?;
    }
    let mut file = writer.into_inner()?;
    file.flush().map_err(|error| ExportError::io(path, error))?;
    file.sync_all()
        .map_err(|error| ExportError::io(path, error))?;
    Ok(())
}

pub(crate) fn logical_table_digest(
    batches: &[RecordBatch],
    primary_key: &[&str],
) -> Result<String> {
    let schema = batches
        .first()
        .map(RecordBatch::schema)
        .ok_or_else(|| ExportError::Invalid("table has no batches".into()))?;
    let descriptor = schema_descriptor(&schema)?;
    let mut rows = Vec::new();
    for batch in batches {
        if batch.schema() != schema {
            return Err(ExportError::Invalid(
                "record batches disagree on Arrow schema".into(),
            ));
        }
        for row in 0..batch.num_rows() {
            let mut object = Map::new();
            for (column, field) in batch.columns().iter().zip(schema.fields()) {
                object.insert(
                    field.name().clone(),
                    scalar_json(column.as_ref(), field, row)?,
                );
            }
            rows.push(Value::Object(object));
        }
    }
    rows.sort_by(|left, right| compare_rows(left, right, primary_key));
    let mut hasher = Sha256::new();
    hasher.update(canonical_json(&descriptor)?);
    hasher.update(b"\n");
    for row in rows {
        hasher.update(canonical_json(&row)?);
        hasher.update(b"\n");
    }
    Ok(format!("sha256:{:x}", hasher.finalize()))
}

pub(crate) fn relation_rows(batches: &[RecordBatch]) -> Result<Vec<Value>> {
    let schema = batches
        .first()
        .map(RecordBatch::schema)
        .ok_or_else(|| ExportError::Invalid("table has no batches".into()))?;
    let mut rows = Vec::new();
    for batch in batches {
        if batch.schema() != schema {
            return Err(ExportError::Invalid(
                "record batches disagree on Arrow schema".into(),
            ));
        }
        for row in 0..batch.num_rows() {
            let mut object = Map::new();
            for (column, field) in batch.columns().iter().zip(schema.fields()) {
                object.insert(
                    field.name().clone(),
                    scalar_json(column.as_ref(), field, row)?,
                );
            }
            rows.push(Value::Object(object));
        }
    }
    Ok(rows)
}

fn compare_rows(left: &Value, right: &Value, primary_key: &[&str]) -> Ordering {
    for key in primary_key {
        let ordering = compare_scalar(&left[*key], &right[*key]);
        if ordering != Ordering::Equal {
            return ordering;
        }
    }
    Ordering::Equal
}

fn compare_scalar(left: &Value, right: &Value) -> Ordering {
    match (left, right) {
        (Value::String(left), Value::String(right)) => left.cmp(right),
        (Value::Number(left), Value::Number(right)) => left.as_i64().cmp(&right.as_i64()),
        (Value::Bool(left), Value::Bool(right)) => left.cmp(right),
        _ => canonical_json(left)
            .unwrap_or_default()
            .cmp(&canonical_json(right).unwrap_or_default()),
    }
}

fn scalar_json(array: &dyn Array, field: &Field, row: usize) -> Result<Value> {
    if array.is_null(row) {
        return Ok(Value::Null);
    }
    match field.data_type() {
        DataType::Utf8 => Ok(Value::String(
            array
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| ExportError::Invalid("UTF-8 array downcast failed".into()))?
                .value(row)
                .to_owned(),
        )),
        DataType::Binary => {
            let bytes = array
                .as_any()
                .downcast_ref::<BinaryArray>()
                .ok_or_else(|| ExportError::Invalid("binary array downcast failed".into()))?
                .value(row);
            let mut hex = String::with_capacity(bytes.len() * 2);
            for byte in bytes {
                FmtWrite::write_fmt(&mut hex, format_args!("{byte:02x}"))
                    .expect("writing to String is infallible");
            }
            Ok(json!({"bytes_hex": hex}))
        }
        DataType::Int32 => Ok(Value::from(
            array
                .as_any()
                .downcast_ref::<Int32Array>()
                .ok_or_else(|| ExportError::Invalid("int32 array downcast failed".into()))?
                .value(row),
        )),
        DataType::Int64 => Ok(Value::from(
            array
                .as_any()
                .downcast_ref::<Int64Array>()
                .ok_or_else(|| ExportError::Invalid("int64 array downcast failed".into()))?
                .value(row),
        )),
        DataType::Boolean => Ok(Value::Bool(
            array
                .as_any()
                .downcast_ref::<BooleanArray>()
                .ok_or_else(|| ExportError::Invalid("boolean array downcast failed".into()))?
                .value(row),
        )),
        DataType::Timestamp(TimeUnit::Microsecond, timezone)
            if timezone.as_deref() == Some("UTC") =>
        {
            let micros = array
                .as_any()
                .downcast_ref::<TimestampMicrosecondArray>()
                .ok_or_else(|| ExportError::Invalid("timestamp array downcast failed".into()))?
                .value(row);
            Ok(Value::String(timestamp_from_us(micros)?))
        }
        DataType::Decimal128(20, 0) => Ok(Value::String(
            array
                .as_any()
                .downcast_ref::<Decimal128Array>()
                .ok_or_else(|| ExportError::Invalid("decimal array downcast failed".into()))?
                .value(row)
                .to_string(),
        )),
        other => Err(ExportError::Invalid(format!(
            "unsupported snapshot Arrow type {other}"
        ))),
    }
}

pub(crate) fn schema_descriptor(schema: &Schema) -> Result<Value> {
    let fields = schema
        .fields()
        .iter()
        .map(|field| {
            Ok(json!({
                "name": field.name(),
                "nullable": field.is_nullable(),
                "type": python_type_name(field.data_type())?,
            }))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(json!({ "fields": fields }))
}

fn python_type_name(value: &DataType) -> Result<&'static str> {
    match value {
        DataType::Utf8 => Ok("string"),
        DataType::Binary => Ok("binary"),
        DataType::Int32 => Ok("int32"),
        DataType::Int64 => Ok("int64"),
        DataType::Boolean => Ok("bool"),
        DataType::Timestamp(TimeUnit::Microsecond, timezone)
            if timezone.as_deref() == Some("UTC") =>
        {
            Ok("timestamp[us, tz=UTC]")
        }
        DataType::Decimal128(20, 0) => Ok("decimal128(20, 0)"),
        other => Err(ExportError::Invalid(format!(
            "unsupported snapshot schema type {other}"
        ))),
    }
}

fn timestamp_from_us(value: i64) -> Result<String> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or_else(|| ExportError::Invalid("timestamp exceeds nanosecond range".into()))?;
    let datetime = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|error| ExportError::Invalid(error.to_string()))?;
    UtcTimestamp::new(datetime)
        .map(|value| value.to_string())
        .map_err(|error| ExportError::Invalid(error.to_string()))
}

fn canonical_json(value: &Value) -> Result<Vec<u8>> {
    serde_json::to_vec(value).map_err(ExportError::Json)
}

pub(crate) fn parse_json_without_duplicate_keys(bytes: &[u8]) -> Result<Value> {
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
            formatter.write_str("JSON without duplicate object keys")
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
                .ok_or_else(|| E::custom("non-finite JSON number"))
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
                        "duplicate JSON object key {key}"
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

pub(crate) fn qualified_sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

pub(crate) fn qualified_sha256_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).map_err(|error| ExportError::io(path, error))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 8 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| ExportError::io(path, error))?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(format!("sha256:{:x}", hasher.finalize()))
}

fn safe_direct_child(value: &str) -> Result<PathBuf> {
    let path = Path::new(value);
    if value.is_empty()
        || path.is_absolute()
        || path.components().count() != 1
        || value == "."
        || value == ".."
    {
        return Err(ExportError::Invalid(format!(
            "unsafe snapshot child path {value}"
        )));
    }
    Ok(path.to_owned())
}

fn stable_field(value: &Map<String, Value>, field: &'static str) -> Result<StableString> {
    let value = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| ExportError::Invalid(format!("missing string {field}")))?;
    StableString::new(value).map_err(|error| ExportError::Invalid(error.to_string()))
}

fn digest_field(value: &Map<String, Value>, field: &'static str) -> Result<ValueDigest> {
    let value = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| ExportError::Invalid(format!("missing digest {field}")))?;
    digest_value(value, field)
}

fn digest_value(value: &str, field: &'static str) -> Result<ValueDigest> {
    ValueDigest::new(value)
        .map_err(|error| ExportError::Invalid(format!("invalid {field}: {error}")))
}

fn commit_field(value: &Map<String, Value>, field: &'static str) -> Result<CommitSeq> {
    let value = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| ExportError::Invalid(format!("missing commit {field}")))?;
    let parsed = value
        .parse::<u64>()
        .map_err(|_| ExportError::Invalid(format!("invalid commit {field}")))?;
    if parsed.to_string() != value {
        return Err(ExportError::Invalid(format!("noncanonical commit {field}")));
    }
    Ok(CommitSeq::new(parsed))
}

pub(crate) fn write_file_durable(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| ExportError::io(path, error))?;
    file.write_all(bytes)
        .map_err(|error| ExportError::io(path, error))?;
    file.sync_all()
        .map_err(|error| ExportError::io(path, error))
}

pub(crate) fn sync_directory(path: &Path) -> Result<()> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| ExportError::io(path, error))
}

#[cfg(test)]
mod tests {
    use super::{parse_json_without_duplicate_keys, rewrite_snapshot_v1};
    use std::path::Path;

    const SOURCE: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../analysis/fixtures/snapshot_v1"
    );

    #[test]
    fn rust_rewrites_all_fourteen_tables_and_self_hashes_manifest() {
        let temp = tempfile::tempdir().expect("temporary export parent");
        let destination = temp.path().join("rust-snapshot");
        let snapshot = rewrite_snapshot_v1(Path::new(SOURCE), &destination)
            .unwrap_or_else(|error| panic!("rewrite snapshot: {error}"));
        assert_eq!(snapshot.tables().len(), 14);
        assert_eq!(snapshot.snapshot_id().as_str().len(), 71);
        assert!(destination.join("manifest.json").is_file());
        assert!(rewrite_snapshot_v1(Path::new(SOURCE), &destination).is_err());
    }

    #[test]
    fn duplicate_manifest_keys_are_rejected_recursively() {
        assert!(parse_json_without_duplicate_keys(br#"{"outer":{"same":1,"same":2}}"#).is_err());
    }
}
