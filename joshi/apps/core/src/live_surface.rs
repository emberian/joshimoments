//! Derive one exact Glass V1 scene from durable observations a real provider actually sent.
//!
//! Nothing here supplies a count, a cutoff, a watermark, a clock, or an identity. Every value in
//! the rendered view is read back out of the sole store, and every value the store does not carry
//! is emitted as an explicit absence rather than a number. In particular: these observations are
//! retained provider bytes with no assertion layer beneath them, so no price, size, market cap or
//! fill is claimed, and a candidate's price series is empty rather than invented.

use joshi_domain::{CommitSeq, SourceId, StableString, UtcTimestamp};
use joshi_operator::ValidatedGlassViewV1;
use joshi_sources::RetainedFrameEnvelope;
use joshi_store::{DurableSourceObservation, DurableSourceObservations, SqliteStore};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt::Write as _,
};
use thiserror::Error;

/// Upper bound on observations one derivation will read back from the catalog.
pub const MAX_LIVE_OBSERVATIONS: usize = 512;

/// Exact, store-derived Glass scene plus the identities that justify every rendered value.
#[derive(Debug)]
pub struct LiveSurfaceDerivation {
    pub view: ValidatedGlassViewV1,
    pub report: LiveSurfaceReport,
}

/// Secret-free description of one derivation, printable next to the surface it produced.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveSurfaceReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub source_id: String,
    pub scene_id: String,
    pub view_digest: String,
    pub view_byte_length: u64,
    pub catalog_commit: String,
    pub delivered_through: String,
    pub rendered_at: String,
    pub observation_count: u64,
    pub observations_truncated: bool,
    pub candidate_count: u64,
    pub chain_slot_low: Option<String>,
    pub chain_slot_high: Option<String>,
    /// Observation identities that named no subject JOSHI can render, with the reason.
    pub unrendered_observations: Vec<UnrenderedObservation>,
    pub price_series_rendered: bool,
    pub ceiling: &'static str,
}

/// One observation that is durable and real but carries nothing this surface can name.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UnrenderedObservation {
    pub observation_id: String,
    pub locator: Option<String>,
    pub reason: String,
}

/// Derives the exact witnessed Glass view for one source as known at the store's latest commit.
///
/// # Errors
///
/// Refuses when the source delivered nothing, when no observation names a renderable subject, or
/// when the derived bytes fail exact Glass V1 validation.
#[allow(clippy::too_many_lines)] // Every derived field stays visible next to the row it came from.
pub fn derive_live_surface(
    store: &SqliteStore,
    source_id: &SourceId,
    cutoff: Option<CommitSeq>,
) -> Result<LiveSurfaceDerivation, LiveSurfaceError> {
    let durable = store
        .source_observations_as_known(source_id, cutoff, MAX_LIVE_OBSERVATIONS)?
        .ok_or_else(|| LiveSurfaceError::NoObservations(source_id.to_string()))?;
    let watermark = store
        .source_as_of(source_id, durable.through_commit_seq)?
        .ok_or_else(|| LiveSurfaceError::NoObservations(source_id.to_string()))?;

    let mut subjects: BTreeMap<String, SubjectDraft> = BTreeMap::new();
    let mut unrendered = Vec::new();
    let mut slot_low: Option<u64> = None;
    let mut slot_high: Option<u64> = None;
    let mut event_clock_count = 0_u64;
    let mut rendered_at = durable.through_committed_at;

    for observation in &durable.observations {
        rendered_at = later(rendered_at, observation.received_at);
        rendered_at = later(rendered_at, observation.available_at);
        if let Some(value) = observation.source_event_lower {
            rendered_at = later(rendered_at, value);
            event_clock_count += 1;
        }
        if let Some(slot) = observation.chain_slot {
            slot_low = Some(slot_low.map_or(slot, |value: u64| value.min(slot)));
            slot_high = Some(slot_high.map_or(slot, |value: u64| value.max(slot)));
        }
        let decoded = decode_observation(observation);
        match decoded {
            DecodedObservation::Subjects(named) => {
                for named in named {
                    let entry =
                        subjects
                            .entry(named.subject.clone())
                            .or_insert_with(|| SubjectDraft {
                                evidence: Vec::new(),
                                slots: Vec::new(),
                            });
                    entry.evidence.push(EvidenceDraft {
                        observation_id: observation.observation_id.to_string(),
                        source_id: observation.source_id.to_string(),
                        observed_at: observation.source_event_lower,
                        ingested_at: observation.received_at,
                        known_at: observation.available_at,
                        note: named.note,
                    });
                    if let Some(slot) = observation.chain_slot {
                        entry.slots.push(slot);
                    }
                }
            }
            DecodedObservation::Unrenderable(reason) => unrendered.push(UnrenderedObservation {
                observation_id: observation.observation_id.to_string(),
                locator: observation.source_locator_redacted.clone(),
                reason,
            }),
        }
    }

    if subjects.is_empty() {
        return Err(LiveSurfaceError::NoRenderableSubject {
            source_id: source_id.to_string(),
            observations: durable.observations.len(),
        });
    }

    let scene_id = scene_identity(&durable);
    let candidates = candidate_wires(&subjects, rendered_at)?;
    let health = source_health(&durable, &watermark, event_clock_count, rendered_at);
    let cursors = watermark
        .cursors()
        .as_slice()
        .iter()
        .map(|cursor| CursorWire {
            family: cursor.family.as_str().to_owned(),
            subject: cursor.subject.as_ref().map(ToString::to_string),
            cursor_kind: cursor.cursor_kind.as_str().to_owned(),
            value: cursor.value.as_str().to_owned(),
            advanced_through: cursor.advanced_through.get().to_string(),
        })
        .collect::<Vec<_>>();

    let wire = GlassViewWire {
        contract: "joshi.glass.view".to_owned(),
        schema_version: 1,
        mode: "witnessed".to_owned(),
        scene_id: scene_id.clone(),
        basis_scene_id: None,
        as_of: AsOfWire {
            catalog_commit: durable.through_commit_seq.get().to_string(),
            sources: vec![SourceAsOfWire {
                source_id: source_id.to_string(),
                delivered_through: watermark.delivered_through().get().to_string(),
                cursors,
                received_through: watermark.received_through().map(|value| value.to_string()),
            }],
            // The provider stated a slot but never a commitment level, so finality is named as
            // unstated instead of being upgraded to confirmed or finalized.
            chain: slot_high.map(|slot| ChainWire {
                cluster: "solana".to_owned(),
                slot: slot.to_string(),
                finality: "unstated".to_owned(),
            }),
            projections: Vec::new(),
            rendered_at: rendered_at.to_string(),
        },
        payload: GlassPayloadWire {
            sources: vec![health],
            candidates,
            episodes: Vec::new(),
            social_events: Vec::new(),
        },
    };

    let bytes = serde_json::to_vec(&wire)?;
    let view = ValidatedGlassViewV1::parse_exact(&bytes, None)?;
    let report = LiveSurfaceReport {
        contract: "joshi.core.live_surface",
        schema_version: 1,
        authority: "read_only_no_execution",
        source_id: source_id.to_string(),
        scene_id,
        view_digest: view.digest().to_string(),
        view_byte_length: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        catalog_commit: durable.through_commit_seq.get().to_string(),
        delivered_through: durable.delivered_through.get().to_string(),
        rendered_at: rendered_at.to_string(),
        observation_count: u64::try_from(durable.observations.len()).unwrap_or(u64::MAX),
        observations_truncated: durable.truncated,
        candidate_count: u64::try_from(subjects.len()).unwrap_or(u64::MAX),
        chain_slot_low: slot_low.map(|value| value.to_string()),
        chain_slot_high: slot_high.map(|value| value.to_string()),
        unrendered_observations: unrendered,
        price_series_rendered: false,
        ceiling: "chain_identity_only_no_price_no_fill",
    };
    Ok(LiveSurfaceDerivation { view, report })
}

struct SubjectDraft {
    evidence: Vec<EvidenceDraft>,
    slots: Vec<u64>,
}

struct EvidenceDraft {
    observation_id: String,
    source_id: String,
    observed_at: Option<UtcTimestamp>,
    ingested_at: UtcTimestamp,
    known_at: UtcTimestamp,
    note: String,
}

struct NamedSubject {
    subject: String,
    note: String,
}

enum DecodedObservation {
    Subjects(Vec<NamedSubject>),
    Unrenderable(String),
}

/// Reads the retained provider bytes and names only what the bytes themselves state.
fn decode_observation(observation: &DurableSourceObservation) -> DecodedObservation {
    let Ok(envelope) = serde_json::from_slice::<RetainedFrameEnvelope>(&observation.payload) else {
        return DecodedObservation::Unrenderable(
            "retained payload is not a joshi.raw_source_frame.v1 envelope".to_owned(),
        );
    };
    let Ok(body) = serde_json::from_slice::<serde_json::Value>(&envelope.body) else {
        return DecodedObservation::Unrenderable(
            "retained provider body is not JSON this surface can read".to_owned(),
        );
    };
    let Some(result) = body.get("result") else {
        return DecodedObservation::Unrenderable(
            "provider response carries no result member".to_owned(),
        );
    };
    let Some(meta) = result.get("meta") else {
        return DecodedObservation::Unrenderable(
            "provider response is not a transaction with token balances".to_owned(),
        );
    };
    let failed = meta.get("err").is_some_and(|value| !value.is_null());
    let mut mints: BTreeSet<String> = BTreeSet::new();
    for key in ["preTokenBalances", "postTokenBalances"] {
        if let Some(entries) = meta.get(key).and_then(serde_json::Value::as_array) {
            for entry in entries {
                if let Some(mint) = entry.get("mint").and_then(serde_json::Value::as_str) {
                    mints.insert(mint.to_owned());
                }
            }
        }
    }
    if mints.is_empty() {
        return DecodedObservation::Unrenderable("transaction names no SPL token mint".to_owned());
    }
    let outcome = if failed {
        "the transaction failed on chain, so it moved no tokens and set no price"
    } else {
        "the transaction succeeded; no fill, size or price is claimed because nothing has \
         interpreted its instructions"
    };
    let slot = observation.chain_slot.map_or_else(
        || "an unstated slot".to_owned(),
        |slot| format!("slot {slot}"),
    );
    let subjects = mints
        .into_iter()
        .map(|mint| NamedSubject {
            note: format!(
                "Named by retained {} bytes at {slot}; {outcome}.",
                observation
                    .source_locator_redacted
                    .clone()
                    .unwrap_or_else(|| "provider".to_owned()),
            ),
            subject: mint,
        })
        .collect();
    DecodedObservation::Subjects(subjects)
}

fn candidate_wires(
    subjects: &BTreeMap<String, SubjectDraft>,
    rendered_at: UtcTimestamp,
) -> Result<Vec<CandidateWire>, LiveSurfaceError> {
    let mut candidates = Vec::with_capacity(subjects.len());
    for (ordinal, (mint, draft)) in subjects.iter().enumerate() {
        let mut evidence = draft.evidence.iter().collect::<Vec<_>>();
        evidence.sort_by(|left, right| left.observation_id.cmp(&right.observation_id));
        evidence.dedup_by(|left, right| left.observation_id == right.observation_id);
        let mut first = None;
        let mut last = None;
        for entry in &evidence {
            let clock = entry.observed_at.unwrap_or(entry.known_at);
            first = Some(first.map_or(clock, |value| earlier(value, clock)));
            last = Some(last.map_or(clock, |value| later(value, clock)));
        }
        let (Some(first), Some(last)) = (first, last) else {
            return Err(LiveSurfaceError::Invariant(
                "a rendered subject carried no evidence clock",
            ));
        };
        let mut slots = draft.slots.clone();
        slots.sort_unstable();
        slots.dedup();
        let slot_text = if slots.is_empty() {
            "no chain slot".to_owned()
        } else {
            format!(
                "slot{} {}",
                if slots.len() == 1 { "" } else { "s" },
                slots
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        };
        let age_seconds = (rendered_at.as_datetime() - first.as_datetime()).whole_seconds();
        candidates.push(CandidateWire {
            id: mint.clone(),
            mint: mint.clone(),
            symbol: "unobserved".to_owned(),
            name: mint.clone(),
            board: "watch".to_owned(),
            lifecycle: "unknown".to_owned(),
            first_known_at: first.to_string(),
            last_observed_at: last.to_string(),
            rank: (u64::try_from(ordinal).unwrap_or(u64::MAX).saturating_add(1)).to_string(),
            metrics: CandidateMetricsWire {
                price_sol: None,
                market_cap_usd: None,
                change_5m_bps: None,
                age_seconds: u64::try_from(age_seconds)
                    .ok()
                    .map(|value| value.to_string()),
                activity: "unknown".to_owned(),
                quote_size_sol: None,
                executable_exit_sol: None,
            },
            attention_reason: format!(
                "Named by {} retained provider observation{} at {slot_text}. Rows are ordered by \
                 mint identity; this is not an attention ranking.",
                evidence.len(),
                if evidence.len() == 1 { "" } else { "s" },
            ),
            social_summary: "No social source was acquired in this cut.".to_owned(),
            tags: vec![
                "chain_observed".to_owned(),
                "no_price_observed".to_owned(),
                "ticker_unobserved".to_owned(),
            ],
            watched: false,
            episode_id: None,
            evidence: evidence
                .into_iter()
                .map(|entry| EvidenceRefWire {
                    id: entry.observation_id.clone(),
                    source_id: entry.source_id.clone(),
                    field: "mint".to_owned(),
                    evidence_class: "observed".to_owned(),
                    observed_at: entry.observed_at.map(|value| value.to_string()),
                    ingested_at: entry.ingested_at.to_string(),
                    known_at: entry.known_at.to_string(),
                    status: "available".to_owned(),
                    note: entry.note.clone(),
                })
                .collect(),
            // Empty on purpose: no price series was observed for this mint, and a bar JOSHI did
            // not see is a market claim it may not make.
            candles: Vec::new(),
        });
    }
    Ok(candidates)
}

fn source_health(
    durable: &DurableSourceObservations,
    watermark: &joshi_domain::SourceAsOf,
    event_clock_count: u64,
    rendered_at: UtcTimestamp,
) -> SourceHealthWire {
    let total = u64::try_from(durable.observations.len()).unwrap_or(u64::MAX);
    let quality_notes = durable
        .observations
        .iter()
        .filter(|observation| observation.quality_code.is_some())
        .count();
    let quality_notes = u64::try_from(quality_notes).unwrap_or(u64::MAX);
    let last_observed = durable
        .observations
        .iter()
        .filter_map(|observation| observation.source_event_lower)
        .max_by_key(|value: &UtcTimestamp| value.as_datetime());
    let last_ingested = durable
        .observations
        .iter()
        .map(|observation| observation.received_at)
        .max_by_key(|value: &UtcTimestamp| value.as_datetime());
    let low = durable
        .observations
        .first()
        .map_or(0, |observation| observation.commit_seq.get());
    SourceHealthWire {
        id: durable.source_id.to_string(),
        label: durable.source_id.to_string(),
        status: if quality_notes == 0 {
            "fresh".to_owned()
        } else {
            "degraded".to_owned()
        },
        last_observed_at: last_observed.map(|value| value.to_string()),
        last_ingested_at: last_ingested.map(|value| value.to_string()),
        coverage: format!(
            "{total} retained observation{} across commits {low} through {}, delivered through \
             commit {}, rendered at commit {}. {event_clock_count} carr{} a provider event clock.",
            if total == 1 { "" } else { "s" },
            durable.delivered_through.get(),
            watermark.delivered_through().get(),
            durable.through_commit_seq.get(),
            if event_clock_count == 1 { "ies" } else { "y" },
        ),
        note: format!(
            "{quality_notes} observation{} recorded an exact adapter quality note. Provider bytes \
             are retained without an assertion layer beneath them, so this surface names \
             identities and clocks only: no price, size, market cap or fill is claimed. Coverage \
             outside these commits is unknown rather than empty. Rendered at {rendered_at}.",
            if quality_notes == 1 { "" } else { "s" },
        ),
    }
}

/// Deterministic scene identity: the same catalog contents always re-derive the same scene.
fn scene_identity(durable: &DurableSourceObservations) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.core.live_surface.scene.v1\0");
    hasher.update(durable.source_id.as_str().as_bytes());
    hasher.update(b"\0");
    hasher.update(durable.through_commit_seq.get().to_string().as_bytes());
    for observation in &durable.observations {
        hasher.update(b"\0");
        hasher.update(observation.observation_id.as_str().as_bytes());
    }
    let digest = hasher.finalize();
    let mut hex = String::with_capacity(32);
    for byte in digest.iter().take(16) {
        write!(hex, "{byte:02x}").expect("string write is infallible");
    }
    format!("scene-live-{hex}")
}

fn later(left: UtcTimestamp, right: UtcTimestamp) -> UtcTimestamp {
    if right.as_datetime() > left.as_datetime() {
        right
    } else {
        left
    }
}

fn earlier(left: UtcTimestamp, right: UtcTimestamp) -> UtcTimestamp {
    if right.as_datetime() < left.as_datetime() {
        right
    } else {
        left
    }
}

/// Parses a registered source identity from a CLI argument.
///
/// # Errors
///
/// Fails when the value is not a valid source identity.
pub fn source_identity(value: &str) -> Result<SourceId, LiveSurfaceError> {
    SourceId::new(value.to_owned())
        .map_err(|error| LiveSurfaceError::InvalidSource(error.to_string()))
}

/// Builds a validated stable string, used for capture metadata identities.
///
/// # Errors
///
/// Fails when the value is not a valid stable wire string.
pub fn stable(value: impl Into<String>) -> Result<StableString, LiveSurfaceError> {
    StableString::new(value).map_err(|error| LiveSurfaceError::InvalidSource(error.to_string()))
}

#[derive(Debug, Error)]
pub enum LiveSurfaceError {
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Operator(#[from] joshi_operator::OperatorAdmissionError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("catalog holds no durable observation for source {0}")]
    NoObservations(String),
    #[error(
        "source {source_id} has {observations} durable observation(s) and none names a subject \
         this surface can render"
    )]
    NoRenderableSubject {
        source_id: String,
        observations: usize,
    },
    #[error("invalid source identity: {0}")]
    InvalidSource(String),
    #[error("live surface invariant failed: {0}")]
    Invariant(&'static str),
}

// ---------------------------------------------------------------------------------------------
// Frozen Glass V1 wire mirror.
//
// These structs exist only to emit the exact canonical bytes `joshi_operator::GlassViewWire`
// accepts, in its exact declaration order. Every derived view is immediately re-parsed by
// `ValidatedGlassViewV1::parse_exact`, which refuses any drift between this mirror and the
// contract, so a mismatch fails loudly at derivation time rather than silently on screen.
// ---------------------------------------------------------------------------------------------

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct GlassViewWire {
    contract: String,
    schema_version: u64,
    mode: String,
    scene_id: String,
    basis_scene_id: Option<String>,
    as_of: AsOfWire,
    payload: GlassPayloadWire,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AsOfWire {
    catalog_commit: String,
    sources: Vec<SourceAsOfWire>,
    chain: Option<ChainWire>,
    projections: Vec<ProjectionWire>,
    rendered_at: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SourceAsOfWire {
    source_id: String,
    delivered_through: String,
    cursors: Vec<CursorWire>,
    received_through: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CursorWire {
    family: String,
    subject: Option<String>,
    cursor_kind: String,
    value: String,
    advanced_through: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ChainWire {
    cluster: String,
    slot: String,
    finality: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ProjectionWire {
    name: String,
    version: String,
    state_digest: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct GlassPayloadWire {
    sources: Vec<SourceHealthWire>,
    candidates: Vec<CandidateWire>,
    // This derivation renders neither episodes nor social events: no episode closure and no
    // social source participate in a chain-identity-only cut.
    episodes: Vec<serde_json::Value>,
    social_events: Vec<serde_json::Value>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SourceHealthWire {
    id: String,
    label: String,
    status: String,
    last_observed_at: Option<String>,
    last_ingested_at: Option<String>,
    coverage: String,
    note: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CandidateWire {
    id: String,
    mint: String,
    symbol: String,
    name: String,
    board: String,
    lifecycle: String,
    first_known_at: String,
    last_observed_at: String,
    rank: String,
    metrics: CandidateMetricsWire,
    attention_reason: String,
    social_summary: String,
    tags: Vec<String>,
    watched: bool,
    episode_id: Option<String>,
    evidence: Vec<EvidenceRefWire>,
    candles: Vec<CandleWire>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CandidateMetricsWire {
    price_sol: Option<String>,
    market_cap_usd: Option<String>,
    change_5m_bps: Option<String>,
    age_seconds: Option<String>,
    activity: String,
    quote_size_sol: Option<String>,
    executable_exit_sol: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CandleWire {
    time_unix: String,
    known_at: String,
    open: String,
    high: String,
    low: String,
    close: String,
    volume_tokens: String,
}
