//! One model-free descriptive reading of an installed Snapshot V2 directory.
//!
//! This computes nothing and estimates nothing. It counts exported provenance rows, partitions
//! them by the two mutually exclusive semantic-key families the listing census writes, and
//! carries the snapshot's own coverage windows, gaps and cutoff alongside the count so the number
//! is never printed without what it is a count of.

use crate::{
    ExportError, Result,
    snapshot::{parse_json_without_duplicate_keys, qualified_sha256, read_parquet},
};
use arrow_array::{Array, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray};
use serde::{Serialize, Serializer};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

/// Semantic-key family for a listed transaction the provider reported with a non-null error.
pub const LANDED_ERROR_FAMILY: &str = "solana.finalized_listing_entry.landed_error";
/// Semantic-key family for a listed transaction the provider reported with a null error.
pub const LANDED_NO_ERROR_FAMILY: &str = "solana.finalized_listing_entry.landed_no_error";

/// One exported coverage window, exactly as the snapshot carries it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CensusWindowV1 {
    pub coverage_window_id: String,
    pub coverage_scope_id: String,
    pub source_id: String,
    pub coverage_kind: String,
    #[serde(serialize_with = "as_text")]
    pub lower_time_us: i64,
    #[serde(serialize_with = "as_text")]
    pub upper_time_us: i64,
}

/// One exported coverage gap, exactly as the snapshot carries it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CensusGapV1 {
    pub coverage_gap_id: String,
    pub coverage_window_id: String,
    pub gap_class: String,
    #[serde(serialize_with = "as_text")]
    pub opened_at_us: i64,
    #[serde(serialize_with = "as_text")]
    pub detected_at_us: i64,
    pub recovered: bool,
}

/// A count, its complete denominator, its coverage, its gaps and its cutoff.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ListingErrorCensusV1 {
    pub contract: String,
    pub snapshot_id: String,
    pub manifest_digest: String,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub from_commit_seq: String,
    pub through_commit_seq: String,
    pub as_of_rendered_at: String,
    pub source_ids: Vec<String>,
    pub subject_addresses: Vec<String>,
    /// Distinct listed transactions the provider reported with a non-null error.
    #[serde(serialize_with = "as_text")]
    pub landed_error_count: u64,
    /// Distinct listed transactions the provider reported with a null error.
    #[serde(serialize_with = "as_text")]
    pub landed_no_error_count: u64,
    /// The complete denominator: distinct listed transactions in the snapshot.
    #[serde(serialize_with = "as_text")]
    pub enumerated_count: u64,
    /// Exported provenance rows, which are evidence edges, not transactions.
    #[serde(serialize_with = "as_text")]
    pub provenance_edge_count: u64,
    #[serde(serialize_with = "as_text")]
    pub corroborated_count: u64,
    pub coverage_windows: Vec<CensusWindowV1>,
    pub coverage_gaps: Vec<CensusGapV1>,
}

/// Reads an installed snapshot directory and counts the listing census it carries.
///
/// # Errors
///
/// Returns an error when the manifest is unreadable, a part is missing or has an unexpected
/// column type, a semantic key is malformed, or one transaction carries both outcome families.
pub fn listing_error_census_v1(root: &Path) -> Result<ListingErrorCensusV1> {
    let manifest_path = root.join("manifest.json");
    let manifest_bytes =
        fs::read(&manifest_path).map_err(|error| ExportError::io(&manifest_path, error))?;
    let manifest: Value = parse_json_without_duplicate_keys(&manifest_bytes)?;
    let manifest_digest = qualified_sha256(&manifest_bytes);

    let provenance = read_parquet(&root.join("provenance_assertions.parquet"))?;
    let mut by_signature: BTreeMap<(String, String), &'static str> = BTreeMap::new();
    let mut edges = 0_u64;
    let mut assertion_edges: BTreeMap<String, u64> = BTreeMap::new();
    let mut source_ids = BTreeSet::new();
    for batch in &provenance {
        let assertion = strings(batch, "source_assertion_id")?;
        let keys = strings(batch, "semantic_key")?;
        let sources = strings(batch, "source_id")?;
        for index in 0..batch.num_rows() {
            edges += 1;
            source_ids.insert(sources.value(index).to_owned());
            *assertion_edges
                .entry(assertion.value(index).to_owned())
                .or_default() += 1;
            let key = keys.value(index);
            let Some((family, subject, signature)) = split_key(key) else {
                continue;
            };
            let class = match family {
                LANDED_ERROR_FAMILY => "error",
                LANDED_NO_ERROR_FAMILY => "no_error",
                _ => continue,
            };
            let identity = (subject.to_owned(), signature.to_owned());
            if by_signature
                .insert(identity, class)
                .is_some_and(|previous| previous != class)
            {
                return Err(ExportError::Invalid(format!(
                    "listed transaction {signature} carries both outcome families"
                )));
            }
        }
    }
    let landed_error_count = by_signature.values().filter(|v| **v == "error").count() as u64;
    let landed_no_error_count = by_signature.values().filter(|v| **v == "no_error").count() as u64;
    let corroborated_count = assertion_edges.values().filter(|count| **count > 1).count() as u64;
    let subject_addresses = by_signature
        .keys()
        .map(|(subject, _)| subject.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();

    let coverage_windows = read_windows(root)?;
    let coverage_gaps = read_gaps(root)?;

    let catalog = &manifest["catalog"];
    Ok(ListingErrorCensusV1 {
        contract: "joshi.export.listing-error-census/v1".to_owned(),
        snapshot_id: text(&manifest["snapshot_id"])?,
        manifest_digest,
        catalog_id: text(&catalog["catalog_id"])?,
        catalog_schema: text(&catalog["catalog_schema"])?,
        from_commit_seq: text(&catalog["from_commit_seq"])?,
        through_commit_seq: text(&catalog["through_commit_seq"])?,
        as_of_rendered_at: text(&catalog["as_of"]["rendered_at"])?,
        source_ids: source_ids.into_iter().collect(),
        subject_addresses,
        landed_error_count,
        landed_no_error_count,
        enumerated_count: landed_error_count + landed_no_error_count,
        provenance_edge_count: edges,
        corroborated_count,
        coverage_windows,
        coverage_gaps,
    })
}

fn read_windows(root: &Path) -> Result<Vec<CensusWindowV1>> {
    let windows_batches = read_parquet(&root.join("coverage_windows.parquet"))?;
    let mut coverage_windows = Vec::new();
    for batch in &windows_batches {
        let ids = strings(batch, "coverage_window_id")?;
        let scopes = strings(batch, "coverage_scope_id")?;
        let sources = strings(batch, "source_id")?;
        let kinds = strings(batch, "coverage_kind")?;
        let lower = timestamps(batch, "lower_time")?;
        let upper = timestamps(batch, "upper_time")?;
        for index in 0..batch.num_rows() {
            coverage_windows.push(CensusWindowV1 {
                coverage_window_id: ids.value(index).to_owned(),
                coverage_scope_id: scopes.value(index).to_owned(),
                source_id: sources.value(index).to_owned(),
                coverage_kind: kinds.value(index).to_owned(),
                lower_time_us: lower.value(index),
                upper_time_us: upper.value(index),
            });
        }
    }
    Ok(coverage_windows)
}

fn read_gaps(root: &Path) -> Result<Vec<CensusGapV1>> {
    let gap_batches = read_parquet(&root.join("coverage_gaps.parquet"))?;
    let mut coverage_gaps = Vec::new();
    for batch in &gap_batches {
        let ids = strings(batch, "coverage_gap_id")?;
        let windows = strings(batch, "coverage_window_id")?;
        let classes = strings(batch, "gap_class")?;
        let opened = timestamps(batch, "opened_at")?;
        let detected = timestamps(batch, "detected_at")?;
        let recovered = timestamps(batch, "recovered_at")?;
        for index in 0..batch.num_rows() {
            coverage_gaps.push(CensusGapV1 {
                coverage_gap_id: ids.value(index).to_owned(),
                coverage_window_id: windows.value(index).to_owned(),
                gap_class: classes.value(index).to_owned(),
                opened_at_us: opened.value(index),
                detected_at_us: detected.value(index),
                recovered: !recovered.is_null(index),
            });
        }
    }
    Ok(coverage_gaps)
}

fn split_key(key: &str) -> Option<(&str, &str, &str)> {
    let mut parts = key.split('/');
    let family = parts.next()?;
    let subject = parts.next()?;
    let signature = parts.next()?;
    if parts.next().is_some() || subject.is_empty() || signature.is_empty() {
        return None;
    }
    Some((family, subject, signature))
}

fn strings<'a>(batch: &'a RecordBatch, field: &str) -> Result<&'a StringArray> {
    let index = batch.schema().index_of(field)?;
    batch
        .column(index)
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| ExportError::Invalid(format!("{field} is not a string column")))
}

fn timestamps<'a>(batch: &'a RecordBatch, field: &str) -> Result<&'a TimestampMicrosecondArray> {
    let index = batch.schema().index_of(field)?;
    batch
        .column(index)
        .as_any()
        .downcast_ref::<TimestampMicrosecondArray>()
        .ok_or_else(|| ExportError::Invalid(format!("{field} is not a timestamp column")))
}

#[allow(dead_code)]
fn integers<'a>(batch: &'a RecordBatch, field: &str) -> Result<&'a Int64Array> {
    let index = batch.schema().index_of(field)?;
    batch
        .column(index)
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| ExportError::Invalid(format!("{field} is not an integer column")))
}

/// Every count and clock crosses the wire as an exact decimal string.
///
/// A JSON number is a float in too many readers, and this payload is compared byte for byte
/// against a second runtime.
fn as_text<T, S>(value: &T, serializer: S) -> std::result::Result<S::Ok, S::Error>
where
    T: std::fmt::Display,
    S: Serializer,
{
    serializer.serialize_str(&value.to_string())
}

fn text(value: &Value) -> Result<String> {
    value
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| ExportError::Invalid("manifest field is not a string".into()))
}
