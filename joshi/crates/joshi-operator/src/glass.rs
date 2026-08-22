use crate::{OperatorAdmissionError, Result, error::invalid, error::json_error};
use joshi_domain::{CommitSeq, SceneId, SourceId, StableString, UtcTimestamp, ValueDigest};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    str::FromStr,
};

const CONTRACT: &str = "joshi.glass.view";

/// Replay mode carried by an exact Glass view.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GlassMode {
    /// The exact view shown to the operator.
    Witnessed,
    /// A later render constrained to an earlier knowledge cutoff.
    KnowledgeCutoff,
    /// A later render that may expose outcomes.
    Retrospective,
}

/// Source index derived from the exact view, never independently supplied by persistence callers.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlassSourceIndex {
    pub(crate) source_id: SourceId,
    pub(crate) delivered_through: CommitSeq,
    pub(crate) received_through: Option<UtcTimestamp>,
    pub(crate) cursors: Vec<GlassCursorIndex>,
}

impl GlassSourceIndex {
    /// Source identity.
    #[must_use]
    pub fn source_id(&self) -> &SourceId {
        &self.source_id
    }

    /// Highest knowledge commit represented for the source.
    #[must_use]
    pub const fn delivered_through(&self) -> CommitSeq {
        self.delivered_through
    }

    /// Latest represented receive clock.
    #[must_use]
    pub const fn received_through(&self) -> Option<UtcTimestamp> {
        self.received_through
    }

    /// Canonically sorted scoped cursor closure.
    #[must_use]
    pub fn cursors(&self) -> &[GlassCursorIndex] {
        &self.cursors
    }
}

/// One authoritative scoped cursor represented by a Glass source watermark.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlassCursorIndex {
    pub(crate) family: StableString,
    pub(crate) subject: Option<StableString>,
    pub(crate) cursor_kind: StableString,
    pub(crate) value: StableString,
    pub(crate) advanced_through: CommitSeq,
}

impl GlassCursorIndex {
    /// Cursor family.
    #[must_use]
    pub fn family(&self) -> &StableString {
        &self.family
    }

    /// Optional exact scope subject.
    #[must_use]
    pub fn subject(&self) -> Option<&StableString> {
        self.subject.as_ref()
    }

    /// Cursor kind.
    #[must_use]
    pub fn cursor_kind(&self) -> &StableString {
        &self.cursor_kind
    }

    /// Opaque cursor value.
    #[must_use]
    pub fn value(&self) -> &StableString {
        &self.value
    }

    /// Commit that justified the cursor.
    #[must_use]
    pub const fn advanced_through(&self) -> CommitSeq {
        self.advanced_through
    }
}

/// Projection index derived from the exact as-of vector.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlassProjectionIndex {
    pub(crate) name: StableString,
    pub(crate) version: StableString,
    pub(crate) state_digest: ValueDigest,
}

impl GlassProjectionIndex {
    /// Projection name.
    #[must_use]
    pub fn name(&self) -> &StableString {
        &self.name
    }

    /// Projection version.
    #[must_use]
    pub fn version(&self) -> &StableString {
        &self.version
    }

    /// Exact projection state digest.
    #[must_use]
    pub fn state_digest(&self) -> &ValueDigest {
        &self.state_digest
    }
}

/// Candidate occurrence indexed from the exact rendered payload order.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlassChoiceIndex {
    pub(crate) candidate_id: StableString,
    pub(crate) source_rank: Option<u64>,
    pub(crate) rendered_ordinal: u64,
}

/// Exact evidence reference duplicated by the renderer and resolved by durable admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlassEvidenceIndex {
    id: StableString,
    source_id: SourceId,
    evidence_class: StableString,
    observed_at: Option<UtcTimestamp>,
    ingested_at: UtcTimestamp,
    known_at: UtcTimestamp,
}

impl GlassEvidenceIndex {
    /// Evidence/observation identity printed in the view.
    #[must_use]
    pub fn id(&self) -> &StableString {
        &self.id
    }
    /// Source that produced the evidence.
    #[must_use]
    pub fn source_id(&self) -> &SourceId {
        &self.source_id
    }
    /// Frozen Glass evidence class.
    #[must_use]
    pub fn evidence_class(&self) -> &StableString {
        &self.evidence_class
    }
    /// Source event clock, when the source supplied one.
    #[must_use]
    pub const fn observed_at(&self) -> Option<UtcTimestamp> {
        self.observed_at
    }
    /// Acquisition/ingest wall clock printed in the view.
    #[must_use]
    pub const fn ingested_at(&self) -> UtcTimestamp {
        self.ingested_at
    }
    /// Knowledge-availability wall clock printed in the view.
    #[must_use]
    pub const fn known_at(&self) -> UtcTimestamp {
        self.known_at
    }
}

impl GlassChoiceIndex {
    /// Candidate identity.
    #[must_use]
    pub fn candidate_id(&self) -> &StableString {
        &self.candidate_id
    }

    /// Rank printed in the rendered candidate DTO, when the view states one.
    #[must_use]
    pub const fn source_rank(&self) -> Option<u64> {
        self.source_rank
    }

    /// Exact ordinal in the canonical candidate array.
    #[must_use]
    pub const fn rendered_ordinal(&self) -> u64 {
        self.rendered_ordinal
    }
}

/// Exact, semantically closed Glass V1 bytes.
#[derive(Clone, Debug)]
pub struct ValidatedGlassViewV1 {
    wire: GlassViewWire,
    canonical_bytes: Vec<u8>,
    digest: ValueDigest,
    mode: GlassMode,
    scene_id: SceneId,
    basis_scene_id: Option<SceneId>,
    catalog_commit: CommitSeq,
    rendered_at: UtcTimestamp,
    sources: Vec<GlassSourceIndex>,
    projections: Vec<GlassProjectionIndex>,
    choices: Vec<GlassChoiceIndex>,
    evidence: Vec<GlassEvidenceIndex>,
}

impl ValidatedGlassViewV1 {
    /// Parses, semantically validates, re-encodes, and hashes exact canonical Glass view bytes.
    ///
    /// # Errors
    ///
    /// Rejects unknown keys, wrong schemas, numeric/string coercion, noncanonical order or bytes,
    /// internally inconsistent references/watermarks, and a mismatched expected digest. Durable
    /// catalog resolution is a separate store admission step.
    pub fn parse_exact(bytes: &[u8], expected_digest: Option<&str>) -> Result<Self> {
        let wire: GlassViewWire =
            serde_json::from_slice(bytes).map_err(json_error("Glass view V1"))?;
        validate_view(&wire)?;
        let canonical = serde_json::to_vec(&wire).map_err(json_error("Glass view V1"))?;
        if canonical != bytes {
            return Err(OperatorAdmissionError::NonCanonical { contract: CONTRACT });
        }
        let digest_text = qualified_sha256(bytes);
        if let Some(expected) = expected_digest
            && expected != digest_text
        {
            return Err(OperatorAdmissionError::DigestMismatch {
                contract: CONTRACT,
                expected: expected.to_owned(),
                computed: digest_text,
            });
        }
        let digest = ValueDigest::new(digest_text.clone())
            .map_err(|error| invalid("Glass view digest", error.to_string()))?;
        let scene_id = SceneId::new(wire.scene_id.clone())
            .map_err(|error| invalid("Glass sceneId", error.to_string()))?;
        let basis_scene_id = wire
            .basis_scene_id
            .clone()
            .map(SceneId::new)
            .transpose()
            .map_err(|error| invalid("Glass basisSceneId", error.to_string()))?;
        let catalog_commit = CommitSeq::new(parse_wire_u64(
            &wire.as_of.catalog_commit,
            "Glass catalogCommit",
        )?);
        let rendered_at = parse_instant(&wire.as_of.rendered_at, "Glass renderedAt")?;
        let sources = wire
            .as_of
            .sources
            .iter()
            .map(source_index)
            .collect::<Result<Vec<_>>>()?;
        let projections = wire
            .as_of
            .projections
            .iter()
            .map(projection_index)
            .collect::<Result<Vec<_>>>()?;
        let choices = wire
            .payload
            .candidates
            .iter()
            .enumerate()
            .map(|(ordinal, candidate)| {
                Ok(GlassChoiceIndex {
                    candidate_id: StableString::new(candidate.id.clone())
                        .map_err(|error| invalid("candidate id", error.to_string()))?,
                    source_rank: candidate
                        .rank
                        .as_deref()
                        .map(|value| parse_wire_u64(value, "candidate rank"))
                        .transpose()?,
                    rendered_ordinal: u64::try_from(ordinal)
                        .map_err(|_| invalid("candidate ordinal", "exceeds u64"))?,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        let evidence = evidence_indexes(&wire)?;
        Ok(Self {
            mode: parse_mode(&wire.mode)?,
            wire,
            canonical_bytes: canonical,
            digest,
            scene_id,
            basis_scene_id,
            catalog_commit,
            rendered_at,
            sources,
            projections,
            choices,
            evidence,
        })
    }

    /// Exact canonical renderer bytes.
    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    /// SHA-256 of the exact canonical renderer bytes.
    #[must_use]
    pub fn digest(&self) -> &ValueDigest {
        &self.digest
    }

    /// Scene identity carried inside the exact view.
    #[must_use]
    pub fn scene_id(&self) -> &SceneId {
        &self.scene_id
    }

    /// Replay mode.
    #[must_use]
    pub const fn mode(&self) -> GlassMode {
        self.mode
    }

    /// Witnessed basis for recomputed modes.
    #[must_use]
    pub fn basis_scene_id(&self) -> Option<&SceneId> {
        self.basis_scene_id.as_ref()
    }

    /// Exact catalog cutoff.
    #[must_use]
    pub const fn catalog_commit(&self) -> CommitSeq {
        self.catalog_commit
    }

    /// Render wall clock.
    #[must_use]
    pub const fn rendered_at(&self) -> UtcTimestamp {
        self.rendered_at
    }

    /// Source watermark indexes derived from the exact bytes.
    #[must_use]
    pub fn sources(&self) -> &[GlassSourceIndex] {
        &self.sources
    }

    /// Projection indexes derived from the exact bytes.
    #[must_use]
    pub fn projections(&self) -> &[GlassProjectionIndex] {
        &self.projections
    }

    /// Rendered candidate indexes derived from exact payload order.
    #[must_use]
    pub fn choices(&self) -> &[GlassChoiceIndex] {
        &self.choices
    }

    /// Canonically sorted distinct evidence references derived from exact payload bytes.
    #[must_use]
    pub fn evidence(&self) -> &[GlassEvidenceIndex] {
        &self.evidence
    }

    /// Whether the exact view contains a candidate identity.
    #[must_use]
    pub fn contains_candidate(&self, candidate_id: &str) -> bool {
        self.wire
            .payload
            .candidates
            .binary_search_by(|candidate| candidate.id.as_str().cmp(candidate_id))
            .is_ok()
    }
}

fn source_index(source: &SourceAsOfWire) -> Result<GlassSourceIndex> {
    Ok(GlassSourceIndex {
        source_id: SourceId::new(source.source_id.clone())
            .map_err(|error| invalid("Glass sourceId", error.to_string()))?,
        delivered_through: CommitSeq::new(parse_wire_u64(
            &source.delivered_through,
            "source deliveredThrough",
        )?),
        received_through: source
            .received_through
            .as_deref()
            .map(|value| parse_instant(value, "source receivedThrough"))
            .transpose()?,
        cursors: source
            .cursors
            .iter()
            .map(|cursor| {
                Ok(GlassCursorIndex {
                    family: stable_identity(&cursor.family, "cursor family")?,
                    subject: cursor
                        .subject
                        .as_deref()
                        .map(|value| printable_ascii(value, "cursor subject"))
                        .transpose()?,
                    cursor_kind: stable_identity(&cursor.cursor_kind, "cursor kind")?,
                    value: StableString::new(cursor.value.clone())
                        .map_err(|error| invalid("cursor value", error.to_string()))?,
                    advanced_through: CommitSeq::new(parse_wire_u64(
                        &cursor.advanced_through,
                        "cursor advancedThrough",
                    )?),
                })
            })
            .collect::<Result<Vec<_>>>()?,
    })
}

fn projection_index(value: &ProjectionWire) -> Result<GlassProjectionIndex> {
    Ok(GlassProjectionIndex {
        name: stable_identity(&value.name, "projection name")?,
        version: StableString::new(value.version.clone())
            .map_err(|error| invalid("projection version", error.to_string()))?,
        state_digest: ValueDigest::new(value.state_digest.clone())
            .map_err(|error| invalid("projection stateDigest", error.to_string()))?,
    })
}

fn evidence_indexes(view: &GlassViewWire) -> Result<Vec<GlassEvidenceIndex>> {
    let mut by_id = BTreeMap::new();
    for value in view
        .payload
        .candidates
        .iter()
        .flat_map(|candidate| candidate.evidence.iter())
        .chain(
            view.payload
                .social_events
                .iter()
                .map(|event| &event.evidence),
        )
    {
        let indexed = GlassEvidenceIndex {
            id: stable_identity(&value.id, "evidence id")?,
            source_id: SourceId::new(value.source_id.clone())
                .map_err(|error| invalid("evidence sourceId", error.to_string()))?,
            evidence_class: stable_identity(&value.evidence_class, "evidenceClass")?,
            observed_at: value
                .observed_at
                .as_deref()
                .map(|clock| parse_instant(clock, "evidence observedAt"))
                .transpose()?,
            ingested_at: parse_instant(&value.ingested_at, "evidence ingestedAt")?,
            known_at: parse_instant(&value.known_at, "evidence knownAt")?,
        };
        if let Some(prior) = by_id.insert(value.id.clone(), indexed.clone())
            && prior != indexed
        {
            return Err(invalid(
                "evidence reference",
                format!("{} is repeated with different clocks or source", value.id),
            ));
        }
    }
    Ok(by_id.into_values().collect())
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GlassViewWire {
    contract: String,
    schema_version: u64,
    mode: String,
    scene_id: String,
    basis_scene_id: Option<String>,
    as_of: AsOfWire,
    payload: GlassPayloadWire,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AsOfWire {
    catalog_commit: String,
    sources: Vec<SourceAsOfWire>,
    chain: Option<ChainWire>,
    projections: Vec<ProjectionWire>,
    rendered_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SourceAsOfWire {
    source_id: String,
    delivered_through: String,
    cursors: Vec<CursorWire>,
    received_through: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CursorWire {
    family: String,
    subject: Option<String>,
    cursor_kind: String,
    value: String,
    advanced_through: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ChainWire {
    cluster: String,
    slot: String,
    finality: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ProjectionWire {
    name: String,
    version: String,
    state_digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GlassPayloadWire {
    sources: Vec<SourceHealthWire>,
    candidates: Vec<CandidateWire>,
    episodes: Vec<EpisodeWire>,
    social_events: Vec<SocialEventWire>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceRefWire {
    id: String,
    source_id: String,
    field: String,
    evidence_class: String,
    observed_at: Option<String>,
    ingested_at: String,
    known_at: String,
    status: String,
    note: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SourceHealthWire {
    id: String,
    label: String,
    status: String,
    last_observed_at: Option<String>,
    last_ingested_at: Option<String>,
    coverage: String,
    note: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CandleWire {
    time_unix: String,
    known_at: String,
    open: String,
    high: String,
    low: String,
    close: String,
    volume_tokens: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CandidateMetricsWire {
    price_sol: Option<String>,
    market_cap_usd: Option<String>,
    change_5m_bps: Option<String>,
    age_seconds: Option<String>,
    activity: String,
    quote_size_sol: Option<String>,
    executable_exit_sol: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CandidateWire {
    id: String,
    mint: String,
    // Null when the source named the mint but no ticker or display name. A required string
    // forced a placeholder, and a placeholder that reaches a render reads as a real ticker.
    symbol: Option<String>,
    name: Option<String>,
    board: String,
    lifecycle: String,
    first_known_at: String,
    // An event clock. Null when the source supplied none, so a producer no longer has to
    // substitute the knowledge clock and turn "when we found out" into "when it happened".
    last_observed_at: Option<String>,
    // Null means this view states no rank at all.
    rank: Option<String>,
    metrics: CandidateMetricsWire,
    attention_reason: String,
    social_summary: String,
    tags: Vec<String>,
    // Null records no watch state; `false` claims it is not watched.
    watched: Option<bool>,
    episode_id: Option<String>,
    evidence: Vec<EvidenceRefWire>,
    candles: Vec<CandleWire>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SocialEventWire {
    id: String,
    candidate_id: String,
    event_at: String,
    known_at: String,
    kind: String,
    author: Option<String>,
    text: String,
    evidence: EvidenceRefWire,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[allow(clippy::struct_field_names)] // Exact frozen wire names all carry the SOL unit suffix.
// Every figure is optional: for money, "zero" and "not reconciled" are different facts and a
// rendered `0` cannot carry the difference. Two of these were already optional; the split was
// the defect.
struct EpisodeAccountingWire {
    total_spent_sol: Option<String>,
    total_proceeds_sol: Option<String>,
    realized_net_sol: Option<String>,
    remaining_cost_basis_sol: Option<String>,
    executable_liquidation_sol: Option<String>,
    current_exposure_sol: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ClipWire {
    id: String,
    label: String,
    opened_at: String,
    closed_at: Option<String>,
    realized_net_sol: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EpisodeWire {
    id: String,
    candidate_id: String,
    state: String,
    disposition: String,
    latest_note: String,
    opened_at: String,
    last_changed_at: String,
    accounting: EpisodeAccountingWire,
    clips: Vec<ClipWire>,
    next_attention: String,
}

#[allow(clippy::too_many_lines)] // Mirrors every frozen Glass V1 semantic relation in one audit.
fn validate_view(view: &GlassViewWire) -> Result<()> {
    if view.contract != CONTRACT || view.schema_version != 1 {
        return Err(invalid(
            "Glass contract",
            "expected joshi.glass.view schemaVersion 1",
        ));
    }
    stable_identity(&view.scene_id, "sceneId")?;
    if let Some(value) = &view.basis_scene_id {
        stable_identity(value, "basisSceneId")?;
    }
    let mode = parse_mode(&view.mode)?;
    if (mode == GlassMode::Witnessed) != view.basis_scene_id.is_none() {
        return Err(invalid(
            "Glass replay mode",
            "witnessed has no basis; recomputed modes require one",
        ));
    }
    let catalog = parse_wire_u64(&view.as_of.catalog_commit, "catalogCommit")?;
    let rendered_at = parse_instant(&view.as_of.rendered_at, "renderedAt")?;
    if let Some(chain) = &view.as_of.chain {
        nonempty(&chain.cluster, "chain cluster")?;
        parse_wire_u64(&chain.slot, "chain slot")?;
        nonempty(&chain.finality, "chain finality")?;
    }
    ensure_sorted_unique(
        view.as_of
            .sources
            .iter()
            .map(|value| value.source_id.as_str()),
        "asOf sources",
    )?;
    ensure_sorted_unique(
        view.as_of
            .projections
            .iter()
            .map(|value| value.name.as_str()),
        "asOf projections",
    )?;
    for source in &view.as_of.sources {
        stable_identity(&source.source_id, "sourceId")?;
        let delivered = parse_wire_u64(&source.delivered_through, "deliveredThrough")?;
        if delivered > catalog {
            return Err(invalid(
                "source watermark",
                "delivery exceeds catalog cutoff",
            ));
        }
        if let Some(value) = &source.received_through {
            parse_instant(value, "receivedThrough")?;
        }
        let mut prior: Option<String> = None;
        for cursor in &source.cursors {
            stable_identity(&cursor.family, "cursor family")?;
            if let Some(subject) = &cursor.subject {
                printable_ascii(subject, "cursor subject")?;
            }
            stable_identity(&cursor.cursor_kind, "cursorKind")?;
            nonempty(&cursor.value, "cursor value")?;
            if parse_wire_u64(&cursor.advanced_through, "advancedThrough")? > delivered {
                return Err(invalid(
                    "cursor watermark",
                    "advancement exceeds source delivery",
                ));
            }
            let key = format!(
                "{}\0{}\0{}",
                cursor.family,
                cursor.subject.as_deref().unwrap_or(""),
                cursor.cursor_kind
            );
            if prior.as_ref().is_some_and(|value| value >= &key) {
                return Err(invalid(
                    "scoped cursors",
                    "must be strictly sorted and unique",
                ));
            }
            prior = Some(key);
        }
    }
    for projection in &view.as_of.projections {
        stable_identity(&projection.name, "projection name")?;
        nonempty(&projection.version, "projection version")?;
        require_digest(&projection.state_digest, "projection stateDigest")?;
    }

    ensure_sorted_unique(
        view.payload.sources.iter().map(|value| value.id.as_str()),
        "payload sources",
    )?;
    ensure_sorted_unique(
        view.payload
            .candidates
            .iter()
            .map(|value| value.id.as_str()),
        "candidates",
    )?;
    ensure_sorted_unique(
        view.payload.episodes.iter().map(|value| value.id.as_str()),
        "episodes",
    )?;
    ensure_sorted_unique(
        view.payload
            .social_events
            .iter()
            .map(|value| value.id.as_str()),
        "social events",
    )?;
    if view.payload.sources.is_empty() || view.payload.candidates.is_empty() {
        return Err(invalid(
            "Glass payload",
            "sources and candidates must both be non-empty",
        ));
    }
    let as_of_sources = view
        .as_of
        .sources
        .iter()
        .map(|value| value.source_id.as_str())
        .collect::<Vec<_>>();
    let payload_sources = view
        .payload
        .sources
        .iter()
        .map(|value| value.id.as_str())
        .collect::<Vec<_>>();
    if as_of_sources != payload_sources {
        return Err(invalid(
            "Glass source closure",
            "payload health differs from as-of source identities",
        ));
    }
    let source_ids = payload_sources.into_iter().collect::<BTreeSet<_>>();
    for source in &view.payload.sources {
        stable_identity(&source.id, "source health id")?;
        nonempty(&source.label, "source label")?;
        one_of(
            &source.status,
            &["fresh", "degraded", "gap", "fixture", "unknown"],
            "source status",
        )?;
        optional_instant(source.last_observed_at.as_ref(), "lastObservedAt")?;
        optional_instant(source.last_ingested_at.as_ref(), "lastIngestedAt")?;
        nonempty(&source.coverage, "source coverage")?;
        nonempty(&source.note, "source note")?;
    }
    let candidate_ids = view
        .payload
        .candidates
        .iter()
        .map(|value| value.id.as_str())
        .collect::<BTreeSet<_>>();
    let episode_ids = view
        .payload
        .episodes
        .iter()
        .map(|value| value.id.as_str())
        .collect::<BTreeSet<_>>();
    for candidate in &view.payload.candidates {
        validate_candidate(candidate, &source_ids)?;
        if candidate
            .episode_id
            .as_deref()
            .is_some_and(|value| !episode_ids.contains(value))
        {
            return Err(invalid(
                "candidate episodeId",
                "episode is absent from the view",
            ));
        }
    }
    for episode in &view.payload.episodes {
        validate_episode(episode)?;
        if !candidate_ids.contains(episode.candidate_id.as_str()) {
            return Err(invalid(
                "episode candidateId",
                "candidate is absent from the view",
            ));
        }
    }
    for event in &view.payload.social_events {
        stable_identity(&event.id, "social event id")?;
        stable_identity(&event.candidate_id, "social candidateId")?;
        if !candidate_ids.contains(event.candidate_id.as_str()) {
            return Err(invalid(
                "social candidateId",
                "candidate is absent from the view",
            ));
        }
        parse_instant(&event.event_at, "social eventAt")?;
        parse_instant(&event.known_at, "social knownAt")?;
        one_of(
            &event.kind,
            &["post", "reply", "callout", "claim", "community", "gap"],
            "social kind",
        )?;
        if let Some(author) = &event.author {
            nonempty(author, "social author")?;
        }
        nonempty(&event.text, "social text")?;
        validate_evidence(&event.evidence, &source_ids)?;
    }
    validate_temporal_closure(view, rendered_at)?;
    Ok(())
}

fn validate_temporal_closure(view: &GlassViewWire, rendered_at: UtcTimestamp) -> Result<()> {
    let check = |value: &str, field: &'static str| -> Result<()> {
        if parse_instant(value, field)?.as_datetime() > rendered_at.as_datetime() {
            return Err(invalid(
                field,
                "exceeds the scene renderedAt knowledge boundary",
            ));
        }
        Ok(())
    };
    for source in &view.as_of.sources {
        if let Some(value) = &source.received_through {
            check(value, "receivedThrough")?;
        }
    }
    for source in &view.payload.sources {
        if let Some(value) = &source.last_observed_at {
            check(value, "lastObservedAt")?;
        }
        if let Some(value) = &source.last_ingested_at {
            check(value, "lastIngestedAt")?;
        }
    }
    for candidate in &view.payload.candidates {
        check(&candidate.first_known_at, "candidate firstKnownAt")?;
        if let Some(value) = &candidate.last_observed_at {
            check(value, "candidate lastObservedAt")?;
        }
        for evidence in &candidate.evidence {
            if let Some(value) = &evidence.observed_at {
                check(value, "evidence observedAt")?;
            }
            check(&evidence.ingested_at, "evidence ingestedAt")?;
            check(&evidence.known_at, "evidence knownAt")?;
        }
        for candle in &candidate.candles {
            check(&candle.known_at, "candle knownAt")?;
        }
    }
    for event in &view.payload.social_events {
        check(&event.event_at, "social eventAt")?;
        check(&event.known_at, "social knownAt")?;
        if let Some(value) = &event.evidence.observed_at {
            check(value, "evidence observedAt")?;
        }
        check(&event.evidence.ingested_at, "evidence ingestedAt")?;
        check(&event.evidence.known_at, "evidence knownAt")?;
    }
    for episode in &view.payload.episodes {
        check(&episode.opened_at, "episode openedAt")?;
        check(&episode.last_changed_at, "episode lastChangedAt")?;
        for clip in &episode.clips {
            check(&clip.opened_at, "clip openedAt")?;
            if let Some(value) = &clip.closed_at {
                check(value, "clip closedAt")?;
            }
        }
    }
    Ok(())
}

fn validate_candidate(candidate: &CandidateWire, sources: &BTreeSet<&str>) -> Result<()> {
    stable_identity(&candidate.id, "candidate id")?;
    if candidate.mint.len() < 16 {
        return Err(invalid(
            "candidate mint",
            "must contain at least 16 characters",
        ));
    }
    // Absent is null, never "": an empty string would render as a blank that reads like a value.
    if let Some(value) = &candidate.symbol {
        nonempty(value, "candidate symbol")?;
    }
    if let Some(value) = &candidate.name {
        nonempty(value, "candidate name")?;
    }
    one_of(
        &candidate.board,
        &["new", "trending", "live", "callouts", "watch"],
        "candidate board",
    )?;
    one_of(
        &candidate.lifecycle,
        &["bonding", "migrating", "graduated", "unknown"],
        "candidate lifecycle",
    )?;
    let first = parse_instant(&candidate.first_known_at, "candidate firstKnownAt")?;
    // Ordering is only checkable when an observation clock exists. An absent one is not a
    // violation; it is the honest state for a source that supplied no event time.
    if let Some(value) = &candidate.last_observed_at {
        let last = parse_instant(value, "candidate lastObservedAt")?;
        if first.as_datetime() > last.as_datetime() {
            return Err(invalid(
                "candidate clocks",
                "firstKnownAt exceeds lastObservedAt",
            ));
        }
    }
    if let Some(value) = &candidate.rank {
        parse_wire_u64(value, "candidate rank")?;
    }
    optional_decimal(candidate.metrics.price_sol.as_ref(), "priceSol")?;
    optional_decimal(candidate.metrics.market_cap_usd.as_ref(), "marketCapUsd")?;
    optional_integer(candidate.metrics.change_5m_bps.as_ref(), "change5mBps")?;
    if let Some(value) = &candidate.metrics.age_seconds {
        parse_wire_u64(value, "ageSeconds")?;
    }
    one_of(
        &candidate.metrics.activity,
        &["quiet", "building", "two_sided", "bursting", "unknown"],
        "candidate activity",
    )?;
    optional_decimal(candidate.metrics.quote_size_sol.as_ref(), "quoteSizeSol")?;
    optional_decimal(
        candidate.metrics.executable_exit_sol.as_ref(),
        "executableExitSol",
    )?;
    nonempty(&candidate.attention_reason, "attentionReason")?;
    nonempty(&candidate.social_summary, "socialSummary")?;
    for tag in &candidate.tags {
        nonempty(tag, "candidate tag")?;
    }
    if let Some(value) = &candidate.episode_id {
        nonempty(value, "candidate episodeId")?;
    }
    if candidate.evidence.is_empty() {
        return Err(invalid("candidate evidence", "must not be empty"));
    }
    ensure_sorted_unique(
        candidate.evidence.iter().map(|value| value.id.as_str()),
        "candidate evidence",
    )?;
    for evidence in &candidate.evidence {
        validate_evidence(evidence, sources)?;
    }
    // A candidate may carry no price series at all: chain evidence can name a real mint at a real
    // slot without any observed fill, and inventing bars to satisfy a shape would be a market
    // claim the bytes do not support. One sample is still refused, because a single point implies
    // an interval it does not have.
    if candidate.candles.len() == 1 {
        return Err(invalid(
            "candidate candles",
            "must be empty or contain at least two samples",
        ));
    }
    for candle in &candidate.candles {
        validate_unix_seconds(&candle.time_unix)?;
        parse_instant(&candle.known_at, "candle knownAt")?;
        for (field, value) in [
            ("candle open", &candle.open),
            ("candle high", &candle.high),
            ("candle low", &candle.low),
            ("candle close", &candle.close),
            ("candle volumeTokens", &candle.volume_tokens),
        ] {
            validate_decimal(value, field)?;
        }
    }
    Ok(())
}

fn validate_evidence(value: &EvidenceRefWire, sources: &BTreeSet<&str>) -> Result<()> {
    stable_identity(&value.id, "evidence id")?;
    stable_identity(&value.source_id, "evidence sourceId")?;
    if !sources.contains(value.source_id.as_str()) {
        return Err(invalid(
            "evidence sourceId",
            "source is absent from the view",
        ));
    }
    nonempty(&value.field, "evidence field")?;
    one_of(
        &value.evidence_class,
        &["observed", "derived", "attested", "interpreted", "unknown"],
        "evidenceClass",
    )?;
    optional_instant(value.observed_at.as_ref(), "evidence observedAt")?;
    parse_instant(&value.ingested_at, "evidence ingestedAt")?;
    parse_instant(&value.known_at, "evidence knownAt")?;
    one_of(
        &value.status,
        &["available", "stale", "gap", "conflicting", "unobserved"],
        "evidence status",
    )?;
    nonempty(&value.note, "evidence note")
}

fn validate_episode(value: &EpisodeWire) -> Result<()> {
    stable_identity(&value.id, "episode id")?;
    stable_identity(&value.candidate_id, "episode candidateId")?;
    one_of(
        &value.state,
        &[
            "exposed",
            "watching_flat",
            "pending_observation",
            "resolved",
        ],
        "episode state",
    )?;
    nonempty(&value.disposition, "episode disposition")?;
    nonempty(&value.latest_note, "episode latestNote")?;
    parse_instant(&value.opened_at, "episode openedAt")?;
    parse_instant(&value.last_changed_at, "episode lastChangedAt")?;
    for (field, decimal) in [
        ("totalSpentSol", value.accounting.total_spent_sol.as_ref()),
        (
            "totalProceedsSol",
            value.accounting.total_proceeds_sol.as_ref(),
        ),
        ("realizedNetSol", value.accounting.realized_net_sol.as_ref()),
        (
            "remainingCostBasisSol",
            value.accounting.remaining_cost_basis_sol.as_ref(),
        ),
        (
            "executableLiquidationSol",
            value.accounting.executable_liquidation_sol.as_ref(),
        ),
        (
            "currentExposureSol",
            value.accounting.current_exposure_sol.as_ref(),
        ),
    ] {
        if let Some(decimal) = decimal {
            validate_decimal(decimal, field)?;
        }
    }
    ensure_sorted_unique(
        value.clips.iter().map(|clip| clip.id.as_str()),
        "episode clips",
    )?;
    for clip in &value.clips {
        stable_identity(&clip.id, "clip id")?;
        nonempty(&clip.label, "clip label")?;
        parse_instant(&clip.opened_at, "clip openedAt")?;
        optional_instant(clip.closed_at.as_ref(), "clip closedAt")?;
        if let Some(decimal) = &clip.realized_net_sol {
            validate_decimal(decimal, "clip realizedNetSol")?;
        }
    }
    nonempty(&value.next_attention, "episode nextAttention")
}

fn parse_mode(value: &str) -> Result<GlassMode> {
    match value {
        "witnessed" => Ok(GlassMode::Witnessed),
        "knowledge_cutoff" => Ok(GlassMode::KnowledgeCutoff),
        "retrospective" => Ok(GlassMode::Retrospective),
        _ => Err(invalid("Glass mode", format!("unsupported mode {value}"))),
    }
}

fn qualified_sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

pub(crate) fn parse_instant(value: &str, context: &'static str) -> Result<UtcTimestamp> {
    UtcTimestamp::from_str(value).map_err(|error| invalid(context, error.to_string()))
}

pub(crate) fn parse_wire_u64(value: &str, context: &'static str) -> Result<u64> {
    if value.is_empty()
        || !value.bytes().all(|byte| byte.is_ascii_digit())
        || (value.len() > 1 && value.starts_with('0'))
    {
        return Err(invalid(context, "must be a canonical decimal u64 string"));
    }
    value.parse().map_err(|_| invalid(context, "exceeds u64"))
}

pub(crate) fn stable_identity(value: &str, context: &'static str) -> Result<StableString> {
    if value.len() > 512
        || !value.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_alphanumeric() || (index > 0 && matches!(byte, b'.' | b'_' | b':' | b'-'))
        })
    {
        return Err(invalid(context, "must be a canonical ASCII identity"));
    }
    StableString::new(value).map_err(|error| invalid(context, error.to_string()))
}

fn printable_ascii(value: &str, context: &'static str) -> Result<StableString> {
    if value.is_empty() || !value.bytes().all(|byte| (0x21..=0x7e).contains(&byte)) {
        return Err(invalid(context, "must be non-empty printable ASCII"));
    }
    StableString::new(value).map_err(|error| invalid(context, error.to_string()))
}

fn nonempty(value: &str, context: &'static str) -> Result<()> {
    if value.is_empty() {
        Err(invalid(context, "must not be empty"))
    } else {
        Ok(())
    }
}

fn one_of(value: &str, allowed: &[&str], context: &'static str) -> Result<()> {
    if allowed.contains(&value) {
        Ok(())
    } else {
        Err(invalid(context, format!("unsupported value {value}")))
    }
}

fn optional_instant(value: Option<&String>, context: &'static str) -> Result<()> {
    if let Some(value) = value {
        parse_instant(value, context)?;
    }
    Ok(())
}

fn ensure_sorted_unique<'a>(
    values: impl IntoIterator<Item = &'a str>,
    context: &'static str,
) -> Result<()> {
    let mut previous: Option<&str> = None;
    for value in values {
        if previous.is_some_and(|before| before >= value) {
            return Err(invalid(context, "must be strictly sorted and unique"));
        }
        previous = Some(value);
    }
    Ok(())
}

fn require_digest(value: &str, context: &'static str) -> Result<()> {
    if value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        Ok(())
    } else {
        Err(invalid(context, "must be sha256:<64 lowercase hex>"))
    }
}

fn optional_decimal(value: Option<&String>, context: &'static str) -> Result<()> {
    if let Some(value) = value {
        validate_decimal(value, context)?;
    }
    Ok(())
}

fn optional_integer(value: Option<&String>, context: &'static str) -> Result<()> {
    if let Some(value) = value {
        validate_integer(value, context)?;
    }
    Ok(())
}

fn validate_integer(value: &str, context: &'static str) -> Result<()> {
    let unsigned = value.strip_prefix('-').unwrap_or(value);
    if unsigned.is_empty()
        || !unsigned.bytes().all(|byte| byte.is_ascii_digit())
        || (unsigned.len() > 1 && unsigned.starts_with('0'))
    {
        Err(invalid(context, "must be an exact integer string"))
    } else {
        Ok(())
    }
}

fn validate_decimal(value: &str, context: &'static str) -> Result<()> {
    let unsigned = value.strip_prefix('-').unwrap_or(value);
    let (integer, fraction) = unsigned
        .split_once('.')
        .map_or((unsigned, None), |(left, right)| (left, Some(right)));
    if integer.is_empty()
        || !integer.bytes().all(|byte| byte.is_ascii_digit())
        || (integer.len() > 1 && integer.starts_with('0'))
        || fraction
            .is_some_and(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
    {
        Err(invalid(context, "must be an exact base-10 decimal string"))
    } else {
        Ok(())
    }
}

fn validate_unix_seconds(value: &str) -> Result<()> {
    let value = parse_wire_u64(value, "candle timeUnix")?;
    if value > 253_402_300_799 {
        return Err(invalid(
            "candle timeUnix",
            "exceeds supported Unix second 253402300799",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::ValidatedGlassViewV1;

    /// The TypeScript half of this same contract. Both halves must accept the same bytes.
    const VIEW_GOLDEN: &str = include_str!("../../../apps/glass/src/contract/golden.ts");

    /// Splits one exported golden constant out of the TypeScript module.
    fn golden(prefix: &str, suffix: &str) -> &'static str {
        let Some((_, rest)) = VIEW_GOLDEN.split_once(prefix) else {
            panic!("golden export {prefix} is missing");
        };
        let Some((value, _)) = rest.split_once(suffix) else {
            panic!("golden terminator for {prefix} is missing");
        };
        value
    }

    fn absence_golden() -> (&'static str, &'static str) {
        (
            golden(
                "export const ABSENCE_GOLDEN_VIEW_V1_JSON = `",
                "`;\n\nexport const ABSENCE_GOLDEN_VIEW_V1_DIGEST = \"",
            ),
            golden("export const ABSENCE_GOLDEN_VIEW_V1_DIGEST = \"", "\";"),
        )
    }

    /// The widening is only real if Rust accepts a document that *uses* every absence, at the
    /// exact digest TypeScript computed for the same bytes. A nullable field that neither half
    /// was ever handed a null for is a nullable field nobody verified.
    #[test]
    fn rust_accepts_the_typescript_absence_golden_at_the_same_digest() {
        let (json, expected_digest) = absence_golden();
        let view = ValidatedGlassViewV1::parse_exact(json.as_bytes(), None)
            .expect("a view whose widened fields are all null must be accepted");
        assert_eq!(view.digest().to_string(), expected_digest);
        assert_eq!(view.canonical_bytes(), json.as_bytes());
        // A candidate that states no rank yields no rank, rather than a silent zero.
        assert_eq!(
            view.choices().first().expect("one candidate").source_rank(),
            None
        );
    }

    /// The standard this widening was held to: `candles` already refused a lone bar, because one
    /// point implies an interval it does not have. Making absence expressible must not loosen it.
    #[test]
    fn a_single_bar_is_still_refused_in_a_view_full_of_absences() {
        let (json, _) = absence_golden();
        let with_one_bar = json.replace(
            "\"candles\":[]",
            "\"candles\":[{\"timeUnix\":\"1786905720\",\"knownAt\":\"2026-08-16T18:42:02.000000Z\",\"open\":\"0.000000001\",\"high\":\"0.000000002\",\"low\":\"0.000000001\",\"close\":\"0.000000002\",\"volumeTokens\":\"100\"}]",
        );
        assert!(ValidatedGlassViewV1::parse_exact(with_one_bar.as_bytes(), None).is_err());
    }

    /// Absence is null, never "". An empty string renders as a blank that reads like a value.
    #[test]
    fn an_empty_symbol_is_still_refused() {
        let (json, _) = absence_golden();
        let empty = json.replace("\"symbol\":null", "\"symbol\":\"\"");
        assert!(ValidatedGlassViewV1::parse_exact(empty.as_bytes(), None).is_err());
    }

    /// One canonical view whose candidate carries no price series, as chain-only evidence does.
    fn view_with_candles(candles: &str) -> String {
        format!(
            concat!(
                r#"{{"contract":"joshi.glass.view","schemaVersion":1,"mode":"witnessed","#,
                r#""sceneId":"scene-live-1","basisSceneId":null,"asOf":{{"catalogCommit":"3","#,
                r#""sources":[{{"sourceId":"source.a","deliveredThrough":"3","cursors":[],"#,
                r#""receivedThrough":"2026-08-19T21:48:41.182000Z"}}],"chain":null,"#,
                r#""projections":[],"renderedAt":"2026-08-19T21:48:41.185131Z"}},"#,
                r#""payload":{{"sources":[{{"id":"source.a","label":"source.a","#,
                r#""status":"degraded","lastObservedAt":null,"#,
                r#""lastIngestedAt":"2026-08-19T21:48:41.182000Z","#,
                r#""coverage":"1 retained observation.","note":"No assertion layer beneath it."}}],"#,
                r#""candidates":[{{"id":"MintAAAAAAAAAAAAAAAA","mint":"MintAAAAAAAAAAAAAAAA","#,
                r#""symbol":"unobserved","name":"MintAAAAAAAAAAAAAAAA","board":"watch","#,
                r#""lifecycle":"unknown","firstKnownAt":"2026-08-19T21:45:21.000000Z","#,
                r#""lastObservedAt":"2026-08-19T21:45:21.000000Z","rank":"1","#,
                r#""metrics":{{"priceSol":null,"marketCapUsd":null,"change5mBps":null,"#,
                r#""ageSeconds":"200","activity":"unknown","quoteSizeSol":null,"#,
                r#""executableExitSol":null}},"attentionReason":"Named by one observation.","#,
                r#""socialSummary":"No social source was acquired.","tags":["chain_observed"],"#,
                r#""watched":false,"episodeId":null,"evidence":[{{"id":"obs:source.a:1","#,
                r#""sourceId":"source.a","field":"mint","evidenceClass":"observed","#,
                r#""observedAt":"2026-08-19T21:45:21.000000Z","#,
                r#""ingestedAt":"2026-08-19T21:48:40.663000Z","#,
                r#""knownAt":"2026-08-19T21:48:41.183518Z","status":"available","#,
                r#""note":"Named by retained bytes."}}],"candles":{}}}],"episodes":[],"#,
                r#""socialEvents":[]}}}}"#
            ),
            candles
        )
    }

    fn candle(time_unix: &str) -> String {
        format!(
            concat!(
                r#"{{"timeUnix":"{}","knownAt":"2026-08-19T21:48:41.183518Z","open":"0.000000001","#,
                r#""high":"0.000000001","low":"0.000000001","close":"0.000000001","#,
                r#""volumeTokens":"0"}}"#
            ),
            time_unix
        )
    }

    #[test]
    fn a_candidate_with_no_observed_price_series_is_exact() {
        let bytes = view_with_candles("[]");
        let view = ValidatedGlassViewV1::parse_exact(bytes.as_bytes(), None)
            .expect("chain-only candidate with no price series");
        assert_eq!(view.scene_id().as_str(), "scene-live-1");
        assert!(view.contains_candidate("MintAAAAAAAAAAAAAAAA"));
    }

    #[test]
    fn a_single_bar_is_not_a_price_series() {
        let bytes = view_with_candles(&format!("[{}]", candle("1787175921")));
        assert!(ValidatedGlassViewV1::parse_exact(bytes.as_bytes(), None).is_err());
    }

    #[test]
    fn two_bars_remain_a_price_series() {
        let bytes = view_with_candles(&format!(
            "[{},{}]",
            candle("1787175921"),
            candle("1787175951")
        ));
        assert!(ValidatedGlassViewV1::parse_exact(bytes.as_bytes(), None).is_ok());
    }
}
