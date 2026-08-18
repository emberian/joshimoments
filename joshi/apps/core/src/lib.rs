//! Offline fixture-to-versioned-query runner for the local JOSHI core.

pub mod pairing;
pub mod readiness;
pub mod service;
mod wave5_circulation;
pub mod wave5_g0;
pub mod wave5_readiness;

use joshi_domain::{
    AsOfVector, BlobId, CommitSeq, CoverageId, ObservationId, RetrospectiveView, SceneId,
    StableString, UtcTimestamp, VariantRecognition, ViewBundle, WireU64, WitnessedView,
};
use joshi_evidence::{
    AcquisitionRecord, AssertionDraft, CatalogSnapshot, CoverageGap, CoverageRecovery,
    CoverageWindow, EvidenceDraft, IngestError, IngestLimits, ObservationDraft,
    ObservationMetadata, bounded_ingest,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

/// Default deterministic offline fixture bundled into the binary.
pub const EMBEDDED_FIXTURE: &str = include_str!("fixture.v1.json");

/// Maximum fixture document accepted by the local runner.
pub const MAX_FIXTURE_DOCUMENT_BYTES: usize = 4 * 1024 * 1024;

const FIXTURE_CONTRACT: &str = "joshi.fixture.v1";
const QUERY_CONTRACT: &str = "joshi.core.fixture_query";
const QUERY_VERSION: &str = "1";

/// Versioned input document for deterministic offline replay.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize)]
pub struct FixtureDocument {
    /// Must equal `joshi.fixture.v1`.
    pub contract: StableString,
    /// Scene to which the witnessed cutoff belongs.
    pub witnessed_scene_id: SceneId,
    /// Exact local knowledge cutoff delivered to the witnessed scene.
    pub witnessed_commit: CommitSeq,
    /// Deterministic render time carried in query metadata.
    pub rendered_at: UtcTimestamp,
    /// Named replay build for retrospective provenance.
    pub replay_build: StableString,
    /// Ordered append commands.
    pub records: Vec<FixtureRecord>,
}

/// Closed fixture command set; source payload discriminators remain open-world.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize)]
#[serde(tag = "record_type", rename_all = "snake_case")]
pub enum FixtureRecord {
    /// Acquisition, observation, and exact UTF-8 bytes committed atomically.
    Observation {
        /// Acquisition provenance.
        acquisition: AcquisitionRecord,
        /// Observation provenance.
        observation: Box<ObservationMetadata>,
        /// Exact fixture bytes; no parsing replaces this evidence.
        payload_utf8: String,
    },
    /// Versioned assertion over retained observation IDs.
    Assertion {
        /// Assertion input.
        assertion: AssertionDraft,
    },
    /// Positive scoped coverage claim.
    CoverageWindow {
        /// Coverage input.
        window: CoverageWindow,
    },
    /// Explicit scoped evidence gap.
    CoverageGap {
        /// Gap input.
        gap: CoverageGap,
    },
    /// Later append-only knowledge about gap recovery.
    CoverageRecovery {
        /// Recovery input.
        recovery: CoverageRecovery,
    },
}

impl FixtureRecord {
    fn into_draft(self) -> EvidenceDraft {
        match self {
            Self::Observation {
                acquisition,
                observation,
                payload_utf8,
            } => ObservationDraft {
                acquisition,
                observation: *observation,
                payload: payload_utf8.into_bytes(),
            }
            .into(),
            Self::Assertion { assertion } => EvidenceDraft::Assertion(assertion),
            Self::CoverageWindow { window } => EvidenceDraft::CoverageWindow(window),
            Self::CoverageGap { gap } => EvidenceDraft::CoverageGap(gap),
            Self::CoverageRecovery { recovery } => EvidenceDraft::CoverageRecovery(recovery),
        }
    }
}

/// Small, stable query projection proving the evidence/replay seams.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FixtureSummary {
    /// Highest represented local knowledge order.
    pub catalog_commit: CommitSeq,
    /// Distinct acquisition occurrences.
    pub acquisition_count: WireU64,
    /// Distinct observation occurrences, even when bytes are equal.
    pub observation_count: WireU64,
    /// Distinct exact-content blobs.
    pub distinct_blob_count: WireU64,
    /// Assertion count available to this view.
    pub assertion_count: WireU64,
    /// Visible gap count.
    pub coverage_gap_count: WireU64,
    /// Visible append-only recovery count.
    pub coverage_recovery_count: WireU64,
    /// Stable observation identities in commit order.
    pub observation_ids: Vec<ObservationId>,
    /// Stable content identities in first-seen commit order.
    pub blob_ids: Vec<BlobId>,
    /// Unknown discriminators retained rather than rejected or coerced.
    pub unknown_variants: Vec<StableString>,
    /// Visible gap identities.
    pub coverage_gap_ids: Vec<CoverageId>,
    /// Visible recovery identities.
    pub coverage_recovery_ids: Vec<CoverageId>,
}

/// Parses, commits, and queries an offline fixture through a bounded one-writer path.
///
/// # Errors
///
/// Returns an explicit contract, wire, ingress, task, or fixture-bound error without producing a
/// partial query.
pub async fn run_fixture(
    input: &str,
    limits: IngestLimits,
) -> Result<ViewBundle<FixtureSummary>, CoreError> {
    if input.len() > MAX_FIXTURE_DOCUMENT_BYTES {
        return Err(CoreError::FixtureTooLarge {
            actual: input.len(),
            maximum: MAX_FIXTURE_DOCUMENT_BYTES,
        });
    }
    let fixture: FixtureDocument = serde_json::from_str(input)?;
    if fixture.contract.as_str() != FIXTURE_CONTRACT {
        return Err(CoreError::UnsupportedFixtureContract(
            fixture.contract.into_inner(),
        ));
    }

    let (handle, worker) = bounded_ingest(limits);
    let writer_task = tokio::spawn(worker.run());
    for record in fixture.records {
        handle.append(record.into_draft()).await?;
    }
    let full = handle.shutdown().await?;
    let worker_snapshot = writer_task.await?;
    if worker_snapshot != full {
        return Err(CoreError::WriterSnapshotMismatch);
    }

    let witnessed_snapshot = full.at_commit(fixture.witnessed_commit);
    let witnessed_summary = summarize(&witnessed_snapshot)?;
    let retrospective_summary = summarize(&full)?;
    let contract = StableString::new(QUERY_CONTRACT)?;
    let version = StableString::new(QUERY_VERSION)?;

    Ok(ViewBundle {
        witnessed: WitnessedView {
            contract: contract.clone(),
            version: version.clone(),
            scene_id: fixture.witnessed_scene_id,
            as_of: as_of(&witnessed_snapshot, fixture.rendered_at)?,
            witnessed_at: fixture.rendered_at,
            value: witnessed_summary,
        },
        retrospective: RetrospectiveView {
            contract,
            version,
            as_of: as_of(&full, fixture.rendered_at)?,
            replay_build: fixture.replay_build,
            value: retrospective_summary,
        },
    })
}

fn summarize(snapshot: &CatalogSnapshot) -> Result<FixtureSummary, CoreError> {
    let unknown_variants = snapshot
        .observations
        .iter()
        .filter(|record| record.value.source_variant.recognition == VariantRecognition::Unknown)
        .map(|record| record.value.source_variant.discriminator.clone())
        .collect();
    let observation_ids = snapshot
        .observations
        .iter()
        .map(|record| record.value.observation_id.clone())
        .collect();
    let blob_ids = snapshot
        .blobs
        .iter()
        .map(|record| record.value.reference.blob_id.clone())
        .collect();
    let coverage_gap_ids = snapshot
        .coverage_gaps
        .iter()
        .map(|record| record.value.gap_id.clone())
        .collect();
    let coverage_recovery_ids = snapshot
        .coverage_recoveries
        .iter()
        .map(|record| record.value.recovery_id.clone())
        .collect();

    Ok(FixtureSummary {
        catalog_commit: snapshot.commit_seq,
        acquisition_count: wire_len(snapshot.acquisitions.len())?,
        observation_count: wire_len(snapshot.observations.len())?,
        distinct_blob_count: wire_len(snapshot.blobs.len())?,
        assertion_count: wire_len(snapshot.assertions.len())?,
        coverage_gap_count: wire_len(snapshot.coverage_gaps.len())?,
        coverage_recovery_count: wire_len(snapshot.coverage_recoveries.len())?,
        observation_ids,
        blob_ids,
        unknown_variants,
        coverage_gap_ids,
        coverage_recovery_ids,
    })
}

fn as_of(snapshot: &CatalogSnapshot, rendered_at: UtcTimestamp) -> Result<AsOfVector, CoreError> {
    let mut projections = BTreeMap::new();
    projections.insert(
        StableString::new(QUERY_CONTRACT)?,
        StableString::new(QUERY_VERSION)?,
    );
    Ok(AsOfVector {
        catalog_commit: snapshot.commit_seq,
        sources: snapshot.source_watermarks(),
        chain: None,
        projections,
        rendered_at,
    })
}

fn wire_len(value: usize) -> Result<WireU64, CoreError> {
    u64::try_from(value)
        .map(WireU64::new)
        .map_err(|_| CoreError::CountOverflow)
}

/// Stable JSON bytes suitable for deterministic fixture comparisons.
///
/// # Errors
///
/// Returns a JSON serialization error if the versioned query cannot be encoded.
pub fn query_json(bundle: &ViewBundle<FixtureSummary>, pretty: bool) -> Result<String, CoreError> {
    if pretty {
        serde_json::to_string_pretty(bundle).map_err(CoreError::Json)
    } else {
        serde_json::to_string(bundle).map_err(CoreError::Json)
    }
}

/// Offline core failure. No network, wallet, or economic-authority errors exist here.
#[derive(Debug, Error)]
pub enum CoreError {
    /// Invalid fixture or output JSON.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// Stable wire value validation failed.
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    /// Bounded ingress rejected or could not acknowledge a record.
    #[error(transparent)]
    Ingest(#[from] IngestError),
    /// Writer task panicked or was cancelled.
    #[error(transparent)]
    WriterTask(#[from] tokio::task::JoinError),
    /// Fixture input exceeds the bounded document size.
    #[error("fixture is {actual} bytes; maximum is {maximum} bytes")]
    FixtureTooLarge {
        /// Actual UTF-8 bytes.
        actual: usize,
        /// Configured hard maximum.
        maximum: usize,
    },
    /// Fixture contract is not supported by this binary.
    #[error("unsupported fixture contract: {0}")]
    UnsupportedFixtureContract(String),
    /// A host collection length could not cross the stable u64 wire boundary.
    #[error("query count cannot be represented as u64")]
    CountOverflow,
    /// Defensive check that worker shutdown returned the same immutable snapshot.
    #[error("writer returned inconsistent shutdown snapshots")]
    WriterSnapshotMismatch,
}

/// Stable set of exact blob identities for callers comparing fixture outcomes.
#[must_use]
pub fn blob_identity_set(summary: &FixtureSummary) -> BTreeSet<BlobId> {
    summary.blob_ids.iter().cloned().collect()
}

#[cfg(test)]
mod tests {
    use super::{EMBEDDED_FIXTURE, query_json, run_fixture};
    use joshi_evidence::IngestLimits;
    use serde_json::Value;
    use sha2::{Digest, Sha256};
    use std::{collections::BTreeSet, fmt::Write as _};

    const GLASS_GOLDEN_TYPESCRIPT: &str = include_str!("../../glass/src/contract/golden.ts");
    const GLASS_JSON_PREFIX: &str = "export const GOLDEN_VIEW_V1_JSON = `";
    const GLASS_JSON_SUFFIX: &str = "`;\n\nexport const GOLDEN_VIEW_V1_DIGEST = \"";

    fn limits() -> IngestLimits {
        IngestLimits::new(2, 1024 * 1024).unwrap_or_else(|_| unreachable!())
    }

    #[tokio::test]
    async fn embedded_fixture_distinguishes_witnessed_from_retrospective() {
        let result = run_fixture(EMBEDDED_FIXTURE, limits()).await;
        assert!(result.is_ok());
        if let Ok(result) = result {
            assert_eq!(result.witnessed.value.observation_count.get(), 2);
            assert_eq!(result.witnessed.value.distinct_blob_count.get(), 1);
            assert_eq!(result.witnessed.value.coverage_recovery_count.get(), 0);
            assert_eq!(result.retrospective.value.observation_count.get(), 3);
            assert_eq!(result.retrospective.value.unknown_variants.len(), 1);
            assert_eq!(result.retrospective.value.assertion_count.get(), 1);
            assert_eq!(result.retrospective.value.coverage_recovery_count.get(), 1);
        }
    }

    #[tokio::test]
    async fn fixture_replay_is_byte_deterministic() {
        let first = run_fixture(EMBEDDED_FIXTURE, limits()).await;
        let second = run_fixture(EMBEDDED_FIXTURE, limits()).await;
        assert!(first.is_ok());
        assert!(second.is_ok());
        if let (Ok(first), Ok(second)) = (first, second) {
            assert_eq!(
                query_json(&first, false).ok(),
                query_json(&second, false).ok()
            );
        }
    }

    #[tokio::test]
    async fn query_integers_are_json_strings() {
        let result = run_fixture(EMBEDDED_FIXTURE, limits()).await;
        assert!(result.is_ok());
        if let Ok(result) = result {
            let json = query_json(&result, false);
            assert!(json.is_ok());
            if let Ok(json) = json {
                assert!(json.contains("\"observation_count\":\"3\""));
                assert!(!json.contains("\"observation_count\":3"));
            }
        }
    }

    fn glass_golden() -> (&'static str, &'static str) {
        let Some((_, after_prefix)) = GLASS_GOLDEN_TYPESCRIPT.split_once(GLASS_JSON_PREFIX) else {
            panic!("glass golden JSON export is missing");
        };
        let Some((json, after_json)) = after_prefix.split_once(GLASS_JSON_SUFFIX) else {
            panic!("glass golden digest export is missing");
        };
        let Some((digest, _)) = after_json.split_once("\";") else {
            panic!("glass golden digest terminator is missing");
        };
        (json, digest)
    }

    #[test]
    fn glass_golden_exact_bytes_match_the_published_sha256() {
        let (json, expected) = glass_golden();
        let digest = Sha256::digest(json.as_bytes());
        let mut actual = String::from("sha256:");
        for byte in digest {
            assert!(write!(&mut actual, "{byte:02x}").is_ok());
        }
        assert_eq!(actual, expected);
        assert_eq!(
            expected,
            "sha256:8cbd045cbf22dd4c908ef84ecc14840d71f846b672c0311f65a2a48cdf8d69ab"
        );
    }

    #[test]
    fn glass_golden_scene_indices_and_watermarks_are_consistent() {
        let (json, _) = glass_golden();
        let parsed = serde_json::from_str::<Value>(json);
        assert!(parsed.is_ok());
        let view = parsed.unwrap_or_else(|_| unreachable!());

        assert_eq!(
            view.pointer("/contract").and_then(Value::as_str),
            Some("joshi.glass.view")
        );
        assert_eq!(
            view.pointer("/mode").and_then(Value::as_str),
            Some("witnessed")
        );
        assert!(view.pointer("/basisSceneId").is_some_and(Value::is_null));

        assert_glass_watermarks(&view);
        assert_glass_references(&view);
    }

    fn assert_glass_watermarks(view: &Value) {
        let catalog_commit = view
            .pointer("/asOf/catalogCommit")
            .and_then(Value::as_str)
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or_else(|| unreachable!());
        let as_of_sources = view
            .pointer("/asOf/sources")
            .and_then(Value::as_array)
            .unwrap_or_else(|| unreachable!());
        let payload_sources = view
            .pointer("/payload/sources")
            .and_then(Value::as_array)
            .unwrap_or_else(|| unreachable!());
        let as_of_source_ids = as_of_sources
            .iter()
            .filter_map(|source| source.get("sourceId").and_then(Value::as_str))
            .collect::<Vec<_>>();
        let payload_source_ids = payload_sources
            .iter()
            .filter_map(|source| source.get("id").and_then(Value::as_str))
            .collect::<Vec<_>>();
        assert_eq!(as_of_source_ids, payload_source_ids);

        for source in as_of_sources {
            let delivered = source
                .get("deliveredThrough")
                .and_then(Value::as_str)
                .and_then(|value| value.parse::<u64>().ok())
                .unwrap_or_else(|| unreachable!());
            assert!(delivered <= catalog_commit);
            let cursors = source
                .get("cursors")
                .and_then(Value::as_array)
                .unwrap_or_else(|| unreachable!());
            let mut previous_scope: Option<String> = None;
            for cursor in cursors {
                let family = cursor
                    .get("family")
                    .and_then(Value::as_str)
                    .unwrap_or_else(|| unreachable!());
                let subject = cursor.get("subject").and_then(Value::as_str).unwrap_or("");
                let kind = cursor
                    .get("cursorKind")
                    .and_then(Value::as_str)
                    .unwrap_or_else(|| unreachable!());
                let scope = format!("{family}\0{subject}\0{kind}");
                assert!(
                    previous_scope
                        .as_ref()
                        .is_none_or(|previous| previous < &scope)
                );
                previous_scope = Some(scope);
                let advanced = cursor
                    .get("advancedThrough")
                    .and_then(Value::as_str)
                    .and_then(|value| value.parse::<u64>().ok())
                    .unwrap_or_else(|| unreachable!());
                assert!(advanced <= delivered);
            }
        }
    }

    fn assert_glass_references(view: &Value) {
        let payload_sources = view
            .pointer("/payload/sources")
            .and_then(Value::as_array)
            .unwrap_or_else(|| unreachable!());
        let payload_source_ids = payload_sources
            .iter()
            .filter_map(|source| source.get("id").and_then(Value::as_str))
            .collect::<Vec<_>>();
        let candidates = view
            .pointer("/payload/candidates")
            .and_then(Value::as_array)
            .unwrap_or_else(|| unreachable!());
        let candidate_ids = candidates
            .iter()
            .filter_map(|candidate| candidate.get("id").and_then(Value::as_str))
            .collect::<BTreeSet<_>>();
        assert_eq!(candidate_ids.len(), candidates.len());
        let episodes = view
            .pointer("/payload/episodes")
            .and_then(Value::as_array)
            .unwrap_or_else(|| unreachable!());
        let episode_ids = episodes
            .iter()
            .filter_map(|episode| episode.get("id").and_then(Value::as_str))
            .collect::<BTreeSet<_>>();
        assert_eq!(episode_ids.len(), episodes.len());
        for candidate in candidates {
            if let Some(episode_id) = candidate.get("episodeId").and_then(Value::as_str) {
                assert!(episode_ids.contains(episode_id));
            }
            let evidence = candidate
                .get("evidence")
                .and_then(Value::as_array)
                .unwrap_or_else(|| unreachable!());
            for reference in evidence {
                let source_id = reference
                    .get("sourceId")
                    .and_then(Value::as_str)
                    .unwrap_or_else(|| unreachable!());
                assert!(payload_source_ids.contains(&source_id));
            }
        }
        for episode in episodes {
            let candidate_id = episode
                .get("candidateId")
                .and_then(Value::as_str)
                .unwrap_or_else(|| unreachable!());
            assert!(candidate_ids.contains(candidate_id));
        }
        let social_events = view
            .pointer("/payload/socialEvents")
            .and_then(Value::as_array)
            .unwrap_or_else(|| unreachable!());
        for event in social_events {
            let candidate_id = event
                .get("candidateId")
                .and_then(Value::as_str)
                .unwrap_or_else(|| unreachable!());
            assert!(candidate_ids.contains(candidate_id));
        }
    }
}
