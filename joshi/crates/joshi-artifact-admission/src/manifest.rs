use crate::{
    ArtifactAdmissionError, CLAIM_SCOPE, DERIVED_ARTIFACT_CONTRACT_V2, DERIVED_AUTHORITY,
    DESCRIPTIVE_ARTIFACT_FAMILY, DISPLAY_CLASS, Result,
    readback::{
        read_chart_samples_part, read_descriptive_part, schema_descriptor,
        validate_descriptive_metrics,
    },
};
use arrow_array::RecordBatch;
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use serde::{
    Deserialize, Serialize,
    de::{DeserializeSeed, MapAccess, SeqAccess, Visitor},
};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
};

const MAX_MANIFEST_BYTES: u64 = 4 * 1024 * 1024;
const MAX_PART_BYTES: u64 = 256 * 1024 * 1024;
const PART_SCHEMA_ID: &str = "joshi.analysis.descriptive-chart-shape/v2";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DerivedManifestV1 {
    manifest_version: String,
    analysis_run_id: String,
    artifact_id: String,
    artifact_family: String,
    authority: String,
    display_class: String,
    claim_scope: String,
    producer: ProducerV1,
    input: InputV1,
    fit: FitV1,
    support: SupportV1,
    uncertainty: UncertaintyV1,
    restrictions: RestrictionsV1,
    artifacts: Vec<ArtifactPartWireV1>,
    determinism: DeterminismV1,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ProducerV1 {
    id: String,
    version: String,
    build_digest: String,
    configuration_digest: String,
    lock_digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct InputV1 {
    source_class: String,
    snapshot_contract: String,
    snapshot_id: String,
    snapshot_manifest_digest: String,
    catalog_commit_seq: String,
    publication_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FitV1 {
    fit_cutoff: String,
    maximum_input_available_at: String,
    policy: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SupportV1 {
    output_rows: String,
    input_rows: String,
    window_ids: Vec<String>,
    gap_ids: Vec<String>,
    observed_inputs: String,
    gap_inputs: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct UncertaintyV1 {
    status: String,
    reason: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
#[allow(clippy::struct_excessive_bools)] // Exact explicit no-authority wire assertions.
struct RestrictionsV1 {
    may_rank_census: bool,
    may_activate_hot_scope: bool,
    may_mutate_observations: bool,
    may_mutate_facts: bool,
    may_mutate_financial_truth: bool,
    economic_authority: EconomicAuthority,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum EconomicAuthority {
    None,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DeterminismV1 {
    canonical_row_order: Vec<String>,
    wall_clock_excluded: bool,
    network_required: bool,
    operational_store_writes: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ArtifactPartWireV1 {
    path: String,
    schema_id: String,
    schema: Value,
    schema_digest: String,
    physical_digest: String,
    logical_digest: String,
    byte_length: String,
    row_count: String,
    primary_key: Vec<String>,
}

/// Exact immutable Parquet part after independent Rust readback.
#[derive(Clone, Debug)]
pub struct ArtifactPartV1 {
    path: PathBuf,
    schema_id: StableString,
    schema_digest: ValueDigest,
    physical_digest: ValueDigest,
    logical_digest: ValueDigest,
    byte_length: u64,
    row_count: u64,
}

/// Exact immutable Parquet descriptor resolved from the sole durable store.
///
/// A filesystem path alone is not an admission boundary. Every field is required so restart
/// readback must agree with the store's persisted schema/logical/physical closure as well as with
/// the untrusted artifact manifest.
#[derive(Clone, Debug)]
pub struct StoreResolvedParquetPartV2 {
    /// Store-resolved immutable object path.
    pub path: PathBuf,
    /// Safe semantic child name retained by the manifest or export registration.
    pub relative_path: StableString,
    /// Exact Arrow schema identity.
    pub schema_id: StableString,
    /// Exact Arrow schema descriptor digest.
    pub schema_digest: ValueDigest,
    /// Exact physical Parquet digest.
    pub physical_digest: ValueDigest,
    /// Canonical typed-relation digest.
    pub logical_digest: ValueDigest,
    /// Exact physical byte length.
    pub byte_length: u64,
    /// Exact logical row count.
    pub row_count: u64,
}

/// Store-resolved chart-sample feature input used to independently reproduce derived metrics.
#[derive(Clone, Debug)]
pub struct StoreResolvedChartSamplesV1 {
    /// Registered input snapshot identity.
    pub snapshot_id: ValueDigest,
    /// Registered exact snapshot-manifest digest.
    pub snapshot_manifest_digest: ValueDigest,
    /// Exact `chart_samples` Parquet part registration and CAS/readback path.
    pub part: StoreResolvedParquetPartV2,
}

impl ArtifactPartV1 {
    /// Absolute immutable artifact path.
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }
    /// Exact schema identity.
    #[must_use]
    pub fn schema_id(&self) -> &StableString {
        &self.schema_id
    }
    /// Exact schema descriptor digest.
    #[must_use]
    pub fn schema_digest(&self) -> &ValueDigest {
        &self.schema_digest
    }
    /// Exact file digest.
    #[must_use]
    pub fn physical_digest(&self) -> &ValueDigest {
        &self.physical_digest
    }
    /// Canonical typed-relation digest.
    #[must_use]
    pub fn logical_digest(&self) -> &ValueDigest {
        &self.logical_digest
    }
    /// Exact file length.
    #[must_use]
    pub const fn byte_length(&self) -> u64 {
        self.byte_length
    }
    /// Exact logical row count.
    #[must_use]
    pub const fn row_count(&self) -> u64 {
        self.row_count
    }
}

/// One independently read descriptive result row.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DescriptiveChartShapeRowV2 {
    /// Scene identity.
    pub scene_id: StableString,
    /// Decision identity.
    pub decision_id: StableString,
    /// Episode identity.
    pub episode_id: StableString,
    /// Candidate identity.
    pub candidate_id: StableString,
    /// Territory identity.
    pub territory_id: StableString,
    /// Exact base-asset identity.
    pub base_asset_id: StableString,
    /// Exact quote-asset identity.
    pub quote_asset_id: StableString,
    /// Decision-time information cutoff.
    pub decision_available_at: UtcTimestamp,
    /// First represented source event.
    pub first_event_time: UtcTimestamp,
    /// Last represented source event.
    pub last_event_time: UtcTimestamp,
    /// Number of expected chart samples.
    pub expected_samples: u64,
    /// Number of observed samples.
    pub observed_samples: u64,
    /// Number of explicit gap samples.
    pub gap_samples: u64,
    /// Exact integer coverage ratio.
    pub coverage_ratio_ppm: u64,
    /// First observed exact base atoms.
    pub start_price_base_atoms: u64,
    /// First observed exact quote atoms.
    pub start_price_quote_atoms: u64,
    /// Last observed exact base atoms.
    pub end_price_base_atoms: u64,
    /// Last observed exact quote atoms.
    pub end_price_quote_atoms: u64,
    /// Exact signed rational change in parts per million.
    pub signed_change_ppm: i64,
    /// Exact rational range in parts per million.
    pub range_ppm: i64,
    /// Exact maximum drawdown in parts per million.
    pub max_drawdown_ppm: i64,
    /// Number of nonzero direction changes.
    pub direction_changes: u64,
    /// Exact per-step path signature.
    pub path_signature: String,
    /// Observed samples in the exposed position state.
    pub exposed_samples: u64,
    /// Observed samples in the flat-watch position state.
    pub flat_watch_samples: u64,
    /// Observed samples in the runner position state.
    pub runner_samples: u64,
    /// Frozen feature transform version.
    pub feature_version: StableString,
    /// Literal descriptive-only claim.
    pub claim_scope: StableString,
}

/// Private-field capability suitable for a store's derived-analysis-only registration method.
#[derive(Clone, Debug)]
pub struct ValidatedDerivedArtifactV2 {
    root: PathBuf,
    analysis_run_id: StableString,
    manifest_bytes: Vec<u8>,
    manifest_digest: ValueDigest,
    artifact_id: ValueDigest,
    snapshot_id: ValueDigest,
    snapshot_manifest_digest: ValueDigest,
    catalog_commit_seq: CommitSeq,
    publication_ids: Vec<StableString>,
    fit_cutoff: UtcTimestamp,
    maximum_input_available_at: UtcTimestamp,
    producer_build_digest: ValueDigest,
    producer_configuration_digest: ValueDigest,
    claim_scope: StableString,
    support: (u64, u64, u64),
    coverage_window_ids: Vec<StableString>,
    coverage_gap_ids: Vec<StableString>,
    uncertainty: (StableString, StableString),
    part: ArtifactPartV1,
    rows: Vec<DescriptiveChartShapeRowV2>,
}

impl ValidatedDerivedArtifactV2 {
    /// Immutable artifact directory.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }
    /// Reserved analysis-run occurrence fulfilled by this content-derived artifact.
    #[must_use]
    pub fn analysis_run_id(&self) -> &StableString {
        &self.analysis_run_id
    }
    /// Exact canonical manifest bytes.
    #[must_use]
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.manifest_bytes
    }
    /// Digest of the exact manifest bytes, including trailing newline.
    #[must_use]
    pub fn manifest_digest(&self) -> &ValueDigest {
        &self.manifest_digest
    }
    /// Self-derived artifact identity.
    #[must_use]
    pub fn artifact_id(&self) -> &ValueDigest {
        &self.artifact_id
    }
    /// Input production snapshot identity.
    #[must_use]
    pub fn snapshot_id(&self) -> &ValueDigest {
        &self.snapshot_id
    }
    /// Exact input snapshot manifest digest.
    #[must_use]
    pub fn snapshot_manifest_digest(&self) -> &ValueDigest {
        &self.snapshot_manifest_digest
    }
    /// Closed store cutoff inherited from the snapshot.
    #[must_use]
    pub const fn catalog_commit_seq(&self) -> CommitSeq {
        self.catalog_commit_seq
    }
    /// Sorted publication closure inherited from the production snapshot.
    #[must_use]
    pub fn publication_ids(&self) -> &[StableString] {
        &self.publication_ids
    }
    /// Frozen fit cutoff.
    #[must_use]
    pub const fn fit_cutoff(&self) -> UtcTimestamp {
        self.fit_cutoff
    }
    /// Maximum input availability proven not later than fit.
    #[must_use]
    pub const fn maximum_input_available_at(&self) -> UtcTimestamp {
        self.maximum_input_available_at
    }
    /// Analysis source/build digest.
    #[must_use]
    pub fn producer_build_digest(&self) -> &ValueDigest {
        &self.producer_build_digest
    }
    /// Analysis configuration digest.
    #[must_use]
    pub fn producer_configuration_digest(&self) -> &ValueDigest {
        &self.producer_configuration_digest
    }
    /// Exact bounded descriptive claim scope admitted from the manifest.
    #[must_use]
    pub fn claim_scope(&self) -> &StableString {
        &self.claim_scope
    }
    /// `(input_rows, observed_inputs, gap_inputs)`.
    #[must_use]
    pub const fn support(&self) -> (u64, u64, u64) {
        self.support
    }
    /// Exact input coverage windows.
    #[must_use]
    pub fn coverage_window_ids(&self) -> &[StableString] {
        &self.coverage_window_ids
    }
    /// Exact input coverage gaps.
    #[must_use]
    pub fn coverage_gap_ids(&self) -> &[StableString] {
        &self.coverage_gap_ids
    }
    /// Exact `(status, reason)` uncertainty closure admitted from the manifest.
    #[must_use]
    pub const fn uncertainty(&self) -> (&StableString, &StableString) {
        (&self.uncertainty.0, &self.uncertainty.1)
    }
    /// Exact Parquet part closure.
    #[must_use]
    pub const fn part(&self) -> &ArtifactPartV1 {
        &self.part
    }
    /// Independently decoded, bounded rows for safe display/readback.
    #[must_use]
    pub fn rows(&self) -> &[DescriptiveChartShapeRowV2] {
        &self.rows
    }
}

/// Validate exact bytes, schema, logical rows, fit/support/coverage closure, and the immutable
/// no-authority ceiling before returning a store-registration capability.
///
/// # Errors
///
/// Refuses fixtures, snapshot V1, absent publication closure, later-known input, altered bytes,
/// unsafe paths, unmanifested files, schema/logical drift, ranking/scope authority, or malformed
/// support and uncertainty.
#[allow(clippy::too_many_lines)]
pub fn validate_derived_artifact_v2(root: &Path) -> Result<ValidatedDerivedArtifactV2> {
    let root_metadata =
        fs::symlink_metadata(root).map_err(|error| ArtifactAdmissionError::io(root, error))?;
    if !root_metadata.file_type().is_dir() || root_metadata.file_type().is_symlink() {
        return Err(invalid("artifact root must be a real directory"));
    }
    let manifest_path = root.join("manifest.json");
    let metadata = fs::symlink_metadata(&manifest_path)
        .map_err(|error| ArtifactAdmissionError::io(&manifest_path, error))?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_MANIFEST_BYTES
    {
        return Err(invalid("manifest must be a bounded regular file"));
    }
    let manifest_bytes = fs::read(&manifest_path)
        .map_err(|error| ArtifactAdmissionError::io(&manifest_path, error))?;
    let manifest = parse_derived_manifest(&manifest_bytes)?;

    let part_wire = manifest
        .artifacts
        .first()
        .ok_or_else(|| invalid("one artifact part is required"))?;
    let relative = safe_direct_child(&part_wire.path)?;
    let part_path = root.join(&relative);
    let part_metadata = fs::symlink_metadata(&part_path)
        .map_err(|error| ArtifactAdmissionError::io(&part_path, error))?;
    if !part_metadata.file_type().is_file()
        || part_metadata.file_type().is_symlink()
        || part_metadata.len() > MAX_PART_BYTES
    {
        return Err(invalid("artifact part must be a bounded regular file"));
    }
    let children = fs::read_dir(root)
        .map_err(|error| ArtifactAdmissionError::io(root, error))?
        .map(|entry| entry.map(|item| item.file_name()))
        .collect::<std::result::Result<BTreeSet<_>, _>>()
        .map_err(|error| ArtifactAdmissionError::io(root, error))?;
    let expected = BTreeSet::from(["manifest.json".into(), relative.as_os_str().to_owned()]);
    if children != expected {
        return Err(invalid("artifact directory contains unmanifested entries"));
    }

    validate_parsed_derived_artifact(manifest_bytes, &manifest, part_path, root.to_owned(), None)
}

/// Validate exact canonical manifest bytes against one store-resolved immutable Parquet part.
///
/// This is the narrow CAS adapter for a sole durable store: the manifest's safe relative part
/// name remains semantic data, while `part_path` is the store-resolved physical object. The same
/// physical bytes establish the digest and feed Arrow/Parquet decoding.
///
/// # Errors
///
/// Refuses an oversized, duplicate-key, noncanonical, or semantically invalid manifest; an unsafe
/// declared part name; a symlink or non-regular/oversized physical part; and any physical digest,
/// Arrow schema, row-count, logical relation, support, cutoff, or authority mismatch.
pub fn validate_derived_artifact_v2_part(
    manifest_bytes: &[u8],
    artifact_part: &StoreResolvedParquetPartV2,
    chart_samples: &StoreResolvedChartSamplesV1,
) -> Result<ValidatedDerivedArtifactV2> {
    if manifest_bytes.len() > usize::try_from(MAX_MANIFEST_BYTES).unwrap_or(usize::MAX) {
        return Err(invalid("manifest exceeds its bounded size"));
    }
    let manifest = parse_derived_manifest(manifest_bytes)?;
    let part_wire = manifest
        .artifacts
        .first()
        .ok_or_else(|| invalid("one artifact part is required"))?;
    safe_direct_child(&part_wire.path)?;
    let root = artifact_part
        .path
        .parent()
        .map_or_else(PathBuf::new, Path::to_path_buf);
    validate_store_part_descriptor(part_wire, artifact_part)?;
    if manifest.input.snapshot_id != chart_samples.snapshot_id.as_str()
        || manifest.input.snapshot_manifest_digest
            != chart_samples.snapshot_manifest_digest.as_str()
        || chart_samples.part.relative_path.as_str() != "chart_samples.parquet"
        || chart_samples.part.schema_id.as_str() != "joshi.analysis.chart-sample/v1"
    {
        return Err(invalid(
            "store-resolved chart input differs from the artifact snapshot closure",
        ));
    }
    validate_parsed_derived_artifact(
        manifest_bytes.to_vec(),
        &manifest,
        artifact_part.path.clone(),
        root,
        Some(chart_samples),
    )
}

fn parse_derived_manifest(manifest_bytes: &[u8]) -> Result<DerivedManifestV1> {
    let value = parse_json_without_duplicate_keys(manifest_bytes)?;
    let mut canonical = serde_json::to_vec(&value)?;
    canonical.push(b'\n');
    if canonical != manifest_bytes {
        return Err(invalid("manifest must be canonical JSON plus one newline"));
    }
    let manifest: DerivedManifestV1 = serde_json::from_value(value.clone())?;
    validate_fixed_semantics(&manifest)?;
    validate_self_identity(&value, &manifest.artifact_id)?;
    Ok(manifest)
}

#[allow(clippy::too_many_lines)]
fn validate_parsed_derived_artifact(
    manifest_bytes: Vec<u8>,
    manifest: &DerivedManifestV1,
    part_path: PathBuf,
    root: PathBuf,
    chart_samples: Option<&StoreResolvedChartSamplesV1>,
) -> Result<ValidatedDerivedArtifactV2> {
    let part_wire = manifest
        .artifacts
        .first()
        .ok_or_else(|| invalid("one artifact part is required"))?;

    let expected_bytes = parse_u64(&part_wire.byte_length, "part byte_length")?;
    let part_metadata = fs::symlink_metadata(&part_path)
        .map_err(|error| ArtifactAdmissionError::io(&part_path, error))?;
    if !part_metadata.file_type().is_file()
        || part_metadata.file_type().is_symlink()
        || part_metadata.len() > MAX_PART_BYTES
    {
        return Err(invalid("artifact part must be a bounded regular file"));
    }
    if expected_bytes != part_metadata.len() {
        return Err(digest_error("part byte length differs"));
    }
    let part_bytes =
        fs::read(&part_path).map_err(|error| ArtifactAdmissionError::io(&part_path, error))?;
    if u64::try_from(part_bytes.len()).ok() != Some(expected_bytes) {
        return Err(digest_error("part changed while being read"));
    }
    let physical = qualified_sha256(&part_bytes);
    if physical != part_wire.physical_digest {
        return Err(digest_error("part physical bytes differ"));
    }
    let (batches, rows, actual_schema_digest, logical_digest) = read_descriptive_part(part_bytes)?;
    validate_part(part_wire, &batches, &actual_schema_digest, &logical_digest)?;
    let row_count = parse_u64(&part_wire.row_count, "part row_count")?;
    if row_count != u64::try_from(rows.len()).map_err(|_| invalid("row count exceeds u64"))? {
        return Err(digest_error("part row count differs"));
    }
    let resolved_support = if rows.is_empty() {
        if let Some(chart_samples) = chart_samples {
            let input = read_store_resolved_chart_samples(chart_samples)?;
            Some(validate_descriptive_metrics(&input, &rows)?)
        } else {
            None
        }
    } else {
        let input = chart_samples.ok_or_else(|| {
            invalid("nonempty derived metrics require a store-resolved chart-sample input")
        })?;
        let input = read_store_resolved_chart_samples(input)?;
        Some(validate_descriptive_metrics(&input, &rows)?)
    };
    let output_rows = parse_u64(&manifest.support.output_rows, "support.output_rows")?;
    let input_rows = parse_u64(&manifest.support.input_rows, "support.input_rows")?;
    let observed = parse_u64(&manifest.support.observed_inputs, "support.observed_inputs")?;
    let gaps = parse_u64(&manifest.support.gap_inputs, "support.gap_inputs")?;
    if output_rows != row_count || observed.checked_add(gaps) != Some(input_rows) {
        return Err(invalid("support counts do not close"));
    }
    canonical_identities(&manifest.support.window_ids, "coverage window IDs", true)?;
    canonical_identities(&manifest.support.gap_ids, "coverage gap IDs", true)?;
    if input_rows > 0 && manifest.support.window_ids.is_empty() {
        return Err(invalid("nonempty input support requires coverage windows"));
    }
    let fit_cutoff = timestamp(&manifest.fit.fit_cutoff, "fit cutoff")?;
    let maximum_input_available_at = timestamp(
        &manifest.fit.maximum_input_available_at,
        "maximum input available at",
    )?;
    if maximum_input_available_at > fit_cutoff {
        return Err(invalid("future-known input exceeds the fit cutoff"));
    }
    if let Some(actual) = resolved_support
        && (actual.input_rows != input_rows
            || actual.observed_inputs != observed
            || actual.gap_inputs != gaps
            || actual.window_ids != manifest.support.window_ids
            || actual.gap_ids != manifest.support.gap_ids
            || actual
                .maximum_available_at
                .is_some_and(|maximum| maximum != maximum_input_available_at))
    {
        return Err(invalid(
            "artifact support differs from the exact store-resolved chart input",
        ));
    }

    Ok(ValidatedDerivedArtifactV2 {
        root,
        analysis_run_id: stable(&manifest.analysis_run_id, "analysis run ID")?,
        manifest_digest: digest(&qualified_sha256(&manifest_bytes), "manifest digest")?,
        manifest_bytes,
        artifact_id: digest(&manifest.artifact_id, "artifact_id")?,
        snapshot_id: digest(&manifest.input.snapshot_id, "snapshot_id")?,
        snapshot_manifest_digest: digest(
            &manifest.input.snapshot_manifest_digest,
            "snapshot manifest digest",
        )?,
        catalog_commit_seq: CommitSeq::new(parse_u64(
            &manifest.input.catalog_commit_seq,
            "catalog commit",
        )?),
        publication_ids: manifest
            .input
            .publication_ids
            .iter()
            .map(|value| stable(value, "publication ID"))
            .collect::<Result<_>>()?,
        fit_cutoff,
        maximum_input_available_at,
        producer_build_digest: digest(&manifest.producer.build_digest, "producer build digest")?,
        producer_configuration_digest: digest(
            &manifest.producer.configuration_digest,
            "producer configuration digest",
        )?,
        claim_scope: stable(&manifest.claim_scope, "claim scope")?,
        support: (input_rows, observed, gaps),
        coverage_window_ids: manifest
            .support
            .window_ids
            .iter()
            .map(|value| stable(value, "coverage window ID"))
            .collect::<Result<_>>()?,
        coverage_gap_ids: manifest
            .support
            .gap_ids
            .iter()
            .map(|value| stable(value, "coverage gap ID"))
            .collect::<Result<_>>()?,
        uncertainty: (
            stable(&manifest.uncertainty.status, "uncertainty status")?,
            stable(&manifest.uncertainty.reason, "uncertainty reason")?,
        ),
        part: ArtifactPartV1 {
            path: part_path,
            schema_id: stable(&part_wire.schema_id, "part schema ID")?,
            schema_digest: digest(&part_wire.schema_digest, "part schema digest")?,
            physical_digest: digest(&part_wire.physical_digest, "part physical digest")?,
            logical_digest: digest(&part_wire.logical_digest, "part logical digest")?,
            byte_length: expected_bytes,
            row_count,
        },
        rows,
    })
}

fn validate_store_part_descriptor(
    wire: &ArtifactPartWireV1,
    value: &StoreResolvedParquetPartV2,
) -> Result<()> {
    if wire.path != value.relative_path.as_str()
        || wire.schema_id != value.schema_id.as_str()
        || wire.schema_digest != value.schema_digest.as_str()
        || wire.physical_digest != value.physical_digest.as_str()
        || wire.logical_digest != value.logical_digest.as_str()
        || parse_u64(&wire.byte_length, "part byte_length")? != value.byte_length
        || parse_u64(&wire.row_count, "part row_count")? != value.row_count
    {
        return Err(invalid(
            "artifact manifest differs from the store-resolved part descriptor",
        ));
    }
    Ok(())
}

fn read_store_resolved_chart_samples(
    value: &StoreResolvedChartSamplesV1,
) -> Result<Vec<crate::readback::ChartSampleRowV1>> {
    let metadata = fs::symlink_metadata(&value.part.path)
        .map_err(|error| ArtifactAdmissionError::io(&value.part.path, error))?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_PART_BYTES
        || metadata.len() != value.part.byte_length
    {
        return Err(invalid(
            "store-resolved chart input is not the declared bounded regular file",
        ));
    }
    let bytes = fs::read(&value.part.path)
        .map_err(|error| ArtifactAdmissionError::io(&value.part.path, error))?;
    if qualified_sha256(&bytes) != value.part.physical_digest.as_str() {
        return Err(digest_error(
            "store-resolved chart input physical bytes differ",
        ));
    }
    let (rows, schema_digest, logical_digest) = read_chart_samples_part(bytes)?;
    if schema_digest != value.part.schema_digest.as_str()
        || logical_digest != value.part.logical_digest.as_str()
        || u64::try_from(rows.len()).ok() != Some(value.part.row_count)
    {
        return Err(digest_error(
            "store-resolved chart input schema, logical relation, or row count differs",
        ));
    }
    Ok(rows)
}

fn validate_fixed_semantics(value: &DerivedManifestV1) -> Result<()> {
    if value.manifest_version != DERIVED_ARTIFACT_CONTRACT_V2
        || value.artifact_family != DESCRIPTIVE_ARTIFACT_FAMILY
        || value.authority != DERIVED_AUTHORITY
        || value.display_class != DISPLAY_CLASS
        || value.claim_scope != CLAIM_SCOPE
    {
        return Err(invalid(
            "unsupported contract, family, authority, display class, or claim scope",
        ));
    }
    if value.analysis_run_id.is_empty() {
        return Err(invalid("analysis run occurrence identity is empty"));
    }
    if value.input.source_class != "operational_store"
        || value.input.snapshot_contract != "joshi.analysis.snapshot/v2"
    {
        return Err(invalid(
            "durable admission requires an operational snapshot V2",
        ));
    }
    canonical_identities(&value.input.publication_ids, "publication IDs", false)?;
    if value.fit.policy != "input_available_at_not_after_fit_cutoff" {
        return Err(invalid("unsupported fit policy"));
    }
    if value.uncertainty.status != "not_estimated"
        || value.uncertainty.reason != "deterministic_descriptive_transform"
    {
        return Err(invalid(
            "descriptive uncertainty must remain explicitly unestimated",
        ));
    }
    let restriction = value.restrictions;
    if restriction.may_rank_census
        || restriction.may_activate_hot_scope
        || restriction.may_mutate_observations
        || restriction.may_mutate_facts
        || restriction.may_mutate_financial_truth
        || restriction.economic_authority != EconomicAuthority::None
    {
        return Err(invalid("artifact exceeds the exact no-authority ceiling"));
    }
    if value.artifacts.len() != 1
        || value.determinism.canonical_row_order != ["scene_id", "episode_id"]
        || !value.determinism.wall_clock_excluded
        || value.determinism.network_required
        || value.determinism.operational_store_writes
    {
        return Err(invalid("artifact part or determinism closure is invalid"));
    }
    for (text, context) in [
        (&value.artifact_id, "artifact_id"),
        (&value.producer.build_digest, "producer build digest"),
        (
            &value.producer.configuration_digest,
            "producer configuration digest",
        ),
        (&value.producer.lock_digest, "producer lock digest"),
        (&value.input.snapshot_id, "snapshot_id"),
        (
            &value.input.snapshot_manifest_digest,
            "snapshot manifest digest",
        ),
    ] {
        digest(text, context)?;
    }
    if value.producer.id.is_empty() || value.producer.version.is_empty() {
        return Err(invalid("producer identity is empty"));
    }
    Ok(())
}

fn validate_self_identity(value: &Value, expected: &str) -> Result<()> {
    let mut preimage = value.clone();
    preimage
        .as_object_mut()
        .ok_or_else(|| invalid("manifest must be an object"))?
        .remove("artifact_id");
    if qualified_sha256(&serde_json::to_vec(&preimage)?) != expected {
        return Err(digest_error("artifact self-identity differs"));
    }
    Ok(())
}

fn validate_part(
    wire: &ArtifactPartWireV1,
    batches: &[RecordBatch],
    schema_digest: &str,
    logical_digest: &str,
) -> Result<()> {
    if wire.schema_id != PART_SCHEMA_ID || wire.primary_key != ["scene_id", "episode_id"] {
        return Err(invalid("part schema identity or primary key differs"));
    }
    let schema = batches
        .first()
        .ok_or_else(|| invalid("part has no record batch"))?
        .schema();
    if wire.schema != schema_descriptor(&schema)? || wire.schema_digest != schema_digest {
        return Err(digest_error("part Arrow schema differs"));
    }
    if wire.logical_digest != logical_digest {
        return Err(digest_error("part logical relation differs"));
    }
    for text in [
        &wire.schema_digest,
        &wire.physical_digest,
        &wire.logical_digest,
    ] {
        digest(text, "part digest")?;
    }
    Ok(())
}

fn canonical_identities(values: &[String], context: &str, allow_empty: bool) -> Result<()> {
    if (!allow_empty && values.is_empty())
        || values.windows(2).any(|window| window[0] >= window[1])
        || values.iter().any(String::is_empty)
    {
        return Err(invalid(format!(
            "{context} must be strictly sorted, unique, and bounded"
        )));
    }
    Ok(())
}

fn timestamp(value: &str, context: &str) -> Result<UtcTimestamp> {
    let parsed = value
        .parse::<UtcTimestamp>()
        .map_err(|error| invalid(format!("invalid {context}: {error}")))?;
    if parsed.to_string() != value {
        return Err(invalid(format!("noncanonical {context}")));
    }
    Ok(parsed)
}

fn parse_u64(value: &str, context: &str) -> Result<u64> {
    let parsed = value
        .parse::<u64>()
        .map_err(|_| invalid(format!("invalid {context}")))?;
    if parsed.to_string() != value {
        return Err(invalid(format!("noncanonical {context}")));
    }
    Ok(parsed)
}

fn stable(value: &str, context: &str) -> Result<StableString> {
    StableString::new(value).map_err(|error| invalid(format!("invalid {context}: {error}")))
}

fn digest(value: &str, context: &str) -> Result<ValueDigest> {
    ValueDigest::new(value).map_err(|error| invalid(format!("invalid {context}: {error}")))
}

fn safe_direct_child(value: &str) -> Result<PathBuf> {
    let path = Path::new(value);
    if value.is_empty()
        || path.is_absolute()
        || path.components().count() != 1
        || matches!(value, "." | "..")
    {
        return Err(invalid("artifact path must be one safe direct child"));
    }
    Ok(path.to_owned())
}

fn qualified_sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}
fn invalid(message: impl Into<String>) -> ArtifactAdmissionError {
    ArtifactAdmissionError::Invalid(message.into())
}
fn digest_error(message: impl Into<String>) -> ArtifactAdmissionError {
    ArtifactAdmissionError::Digest(message.into())
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
