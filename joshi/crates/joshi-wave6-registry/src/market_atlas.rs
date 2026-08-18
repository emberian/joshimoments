//! Exact caller-fed market-atlas fixture artifact.

use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

use crate::{
    RegistryError, Result, SemanticCeilingV1,
    canonical::{decode_canonical, digest_bytes},
};

/// Registered market-atlas fixture kind.
pub const MARKET_ATLAS_KIND: &str = "market_atlas_fixture";
/// Registered market-atlas snapshot schema.
pub const MARKET_ATLAS_SCHEMA: &str = "joshi.analysis.wave6-market-atlas-snapshot/v1";
const AUTHORITY: &str = "caller_fed_unverified_semantic_fixture_only";
const CLAIM_SCOPE: &str =
    "descriptive_point_in_time_typed_market_atlas_not_scalar_pressure_causal_or_strategy_claim";
const COMPONENT_KINDS: [&str; 6] = [
    "caller_attention",
    "canonical_venue_state",
    "liquidity_topology",
    "mint_lifecycle",
    "portfolio_watch",
    "wallet_cluster_flow",
];

/// One canonical output row from the exact six-stratum fixture cut.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MarketAtlasSnapshotRowV1 {
    pub as_of_commit_seq: String,
    pub atlas_snapshot_digest: ValueDigest,
    pub atlas_snapshot_id: StableString,
    pub available_at: UtcTimestamp,
    pub claim_scope: StableString,
    pub component_id: StableString,
    pub component_kind: StableString,
    pub component_version_id: StableString,
    pub coverage_gap_id: Option<StableString>,
    pub coverage_status: StableString,
    pub coverage_window_id: Option<StableString>,
    pub cut_id: StableString,
    pub input_logical_digest: ValueDigest,
    pub input_snapshot_id: StableString,
    pub knowledge_cutoff: UtcTimestamp,
    pub native_event_id: StableString,
    pub native_payload_digest: ValueDigest,
    pub record_id: StableString,
    pub retracted_at: Option<UtcTimestamp>,
    pub semantic_ceiling: StableString,
    pub source_id: StableString,
    pub source_version_id: StableString,
    pub state_time: UtcTimestamp,
    pub subject_id: StableString,
    pub valid_lower: UtcTimestamp,
    pub valid_upper: UtcTimestamp,
}

/// Exact JSON fixture envelope around one market-atlas snapshot relation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MarketAtlasFixtureArtifactV1 {
    pub artifact_digest: ValueDigest,
    pub as_of_commit_seq: String,
    pub atlas_snapshot_digest: ValueDigest,
    pub atlas_snapshot_id: StableString,
    pub authority: StableString,
    pub claim_scope: StableString,
    pub cut_id: StableString,
    pub input_logical_digest: ValueDigest,
    pub input_snapshot_id: StableString,
    pub knowledge_cutoff: UtcTimestamp,
    pub row_count: String,
    pub rows: Vec<MarketAtlasSnapshotRowV1>,
    pub schema_id: StableString,
    pub state_time: UtcTimestamp,
}

#[derive(Serialize)]
struct MarketAtlasArtifactDigestMaterialV1<'a> {
    as_of_commit_seq: &'a str,
    atlas_snapshot_digest: &'a ValueDigest,
    atlas_snapshot_id: &'a StableString,
    authority: &'a StableString,
    claim_scope: &'a StableString,
    cut_id: &'a StableString,
    input_logical_digest: &'a ValueDigest,
    input_snapshot_id: &'a StableString,
    knowledge_cutoff: UtcTimestamp,
    row_count: &'a str,
    rows: &'a [MarketAtlasSnapshotRowV1],
    schema_id: &'a StableString,
    state_time: UtcTimestamp,
}

#[derive(Serialize)]
struct SnapshotDigestMaterialV1<'a> {
    as_of_commit_seq: u64,
    cut_id: &'a StableString,
    input_snapshot_id: &'a StableString,
    knowledge_cutoff: UtcTimestamp,
    state_time: UtcTimestamp,
}

#[derive(Serialize)]
struct InputSnapshotDigestMaterialV1<'a> {
    contract: &'static str,
    logical_digest: &'a ValueDigest,
}

/// Strict exact-byte result. It carries no store, source, field-release, or market authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedMarketAtlasFixture {
    value: MarketAtlasFixtureArtifactV1,
    exact_bytes: Vec<u8>,
    content_digest: ValueDigest,
}

impl ValidatedMarketAtlasFixture {
    #[must_use]
    pub const fn value(&self) -> &MarketAtlasFixtureArtifactV1 {
        &self.value
    }

    #[must_use]
    pub fn exact_bytes(&self) -> &[u8] {
        &self.exact_bytes
    }

    #[must_use]
    pub const fn content_digest(&self) -> &ValueDigest {
        &self.content_digest
    }

    #[must_use]
    pub const fn semantic_ceiling(&self) -> SemanticCeilingV1 {
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    }
}

/// Parse and validate the canonical six-row market-atlas fixture.
///
/// # Errors
///
/// Refuses noncanonical/unknown fields, a foreign registered schema, malformed clocks or
/// coverage, incomplete/duplicate strata, changed snapshot identity, or either self-digest.
pub fn parse_market_atlas_fixture_exact(
    kind_id: &StableString,
    schema_id: &StableString,
    bytes: &[u8],
) -> Result<ValidatedMarketAtlasFixture> {
    if kind_id.as_str() != MARKET_ATLAS_KIND || schema_id.as_str() != MARKET_ATLAS_SCHEMA {
        return Err(RegistryError::MarketAtlas(
            "unsupported registered market-atlas kind/schema mapping",
        ));
    }
    let value: MarketAtlasFixtureArtifactV1 = decode_canonical(bytes)?;
    validate(&value)?;
    Ok(ValidatedMarketAtlasFixture {
        value,
        exact_bytes: bytes.to_vec(),
        content_digest: digest_bytes(bytes)?,
    })
}

#[allow(clippy::too_many_lines)]
fn validate(value: &MarketAtlasFixtureArtifactV1) -> Result<()> {
    let as_of_commit_seq = parse_count(&value.as_of_commit_seq, "as-of commit sequence")?;
    let row_count = parse_count(&value.row_count, "row count")?;
    if value.schema_id.as_str() != MARKET_ATLAS_SCHEMA
        || value.authority.as_str() != AUTHORITY
        || value.claim_scope.as_str() != CLAIM_SCOPE
        || value.rows.len() != COMPONENT_KINDS.len()
        || row_count != u64::try_from(value.rows.len()).unwrap_or(u64::MAX)
        || as_of_commit_seq == 0
        || value.state_time > value.knowledge_cutoff
        || !value
            .atlas_snapshot_id
            .as_str()
            .strip_prefix("market-atlas-snapshot:")
            .is_some_and(|suffix| {
                value.atlas_snapshot_digest.as_str().strip_prefix("sha256:") == Some(suffix)
            })
        || !value
            .input_snapshot_id
            .as_str()
            .starts_with("market-atlas-input:")
    {
        return Err(RegistryError::MarketAtlas(
            "fixture header, clocks, cardinality, authority, or snapshot identity",
        ));
    }
    let snapshot_digest = digest_bytes(&serde_json::to_vec(&SnapshotDigestMaterialV1 {
        as_of_commit_seq,
        cut_id: &value.cut_id,
        input_snapshot_id: &value.input_snapshot_id,
        knowledge_cutoff: value.knowledge_cutoff,
        state_time: value.state_time,
    })?)?;
    if snapshot_digest != value.atlas_snapshot_digest {
        return Err(RegistryError::MarketAtlas(
            "snapshot semantic digest mismatch",
        ));
    }
    let input_snapshot_digest =
        digest_bytes(&serde_json::to_vec(&InputSnapshotDigestMaterialV1 {
            contract: "joshi.analysis.wave6-market-atlas-input/v1",
            logical_digest: &value.input_logical_digest,
        })?)?;
    if value.input_snapshot_id.as_str()
        != format!(
            "market-atlas-input:{}",
            input_snapshot_digest
                .as_str()
                .strip_prefix("sha256:")
                .unwrap_or_default()
        )
    {
        return Err(RegistryError::MarketAtlas(
            "input snapshot semantic identity mismatch",
        ));
    }

    let mut kinds = BTreeSet::new();
    let mut records = BTreeSet::new();
    for (index, row) in value.rows.iter().enumerate() {
        let row_commit = parse_count(&row.as_of_commit_seq, "row as-of commit sequence")?;
        if row_commit != as_of_commit_seq
            || row.atlas_snapshot_digest != value.atlas_snapshot_digest
            || row.atlas_snapshot_id != value.atlas_snapshot_id
            || row.claim_scope != value.claim_scope
            || row.cut_id != value.cut_id
            || row.input_logical_digest != value.input_logical_digest
            || row.input_snapshot_id != value.input_snapshot_id
            || row.knowledge_cutoff != value.knowledge_cutoff
            || row.semantic_ceiling.as_str() != AUTHORITY
            || row.state_time != value.state_time
            || row.coverage_status.as_str() != "observed"
            || row.coverage_window_id.is_none()
            || row.coverage_gap_id.is_some()
            || row.retracted_at.is_some()
            || row.available_at > row.knowledge_cutoff
            || row.valid_lower > row.state_time
            || row.state_time >= row.valid_upper
            || row.component_kind.as_str() != COMPONENT_KINDS[index]
            || !kinds.insert(row.component_kind.as_str())
            || !records.insert(row.record_id.as_str())
        {
            return Err(RegistryError::MarketAtlas(
                "row closure, coverage, clocks, identity, or uniqueness",
            ));
        }
    }
    if kinds.into_iter().ne(COMPONENT_KINDS) {
        return Err(RegistryError::MarketAtlas("exact six-stratum denominator"));
    }

    let artifact_digest =
        digest_bytes(&serde_json::to_vec(&MarketAtlasArtifactDigestMaterialV1 {
            as_of_commit_seq: &value.as_of_commit_seq,
            atlas_snapshot_digest: &value.atlas_snapshot_digest,
            atlas_snapshot_id: &value.atlas_snapshot_id,
            authority: &value.authority,
            claim_scope: &value.claim_scope,
            cut_id: &value.cut_id,
            input_logical_digest: &value.input_logical_digest,
            input_snapshot_id: &value.input_snapshot_id,
            knowledge_cutoff: value.knowledge_cutoff,
            row_count: &value.row_count,
            rows: &value.rows,
            schema_id: &value.schema_id,
            state_time: value.state_time,
        })?)?;
    if artifact_digest != value.artifact_digest {
        return Err(RegistryError::MarketAtlas(
            "artifact semantic self-digest mismatch",
        ));
    }
    Ok(())
}

fn parse_count(value: &str, field: &'static str) -> Result<u64> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || !value.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(RegistryError::MarketAtlas(field));
    }
    value.parse().map_err(|_| RegistryError::MarketAtlas(field))
}
