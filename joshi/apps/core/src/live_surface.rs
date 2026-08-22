//! Derive one exact Glass V1 scene from durable observations a real provider actually sent.
//!
//! Nothing here supplies a count, a cutoff, a watermark, a clock, or an identity. Every value in
//! the rendered view is read back out of the sole store, and every value the store does not carry
//! is emitted as an explicit absence rather than a number.
//!
//! Two kinds of retained bytes are read here.
//!
//! *Chain frames* (`joshi.raw_source_frame.v1` envelopes holding a Solana RPC response) name SPL
//! mints and slots. Nothing has interpreted their instructions, so they carry no price, size,
//! market cap or fill, and a candidate derived only from them has an empty price series.
//!
//! *Pump product reads* (`joshi.pump_api.acquisition.v1` attempt envelopes and their exact
//! provider bodies) can carry a `candles` window: a bare top-level JSON array of OHLCV rows the
//! swap API asserted. Those rows are the only prices this surface will ever render, they are
//! copied out as the provider's exact decimal strings, and three things about them are stated
//! rather than assumed:
//!
//! 1. The window is **gap-compressed**. Intervals in which nothing traded are omitted from the
//!    array entirely, so it is a price *path* and not a grid. The bar spacing is recovered from
//!    the timestamps themselves (never from a request argument, which is not retained), and the
//!    omitted intervals are counted so the renderer can draw absence instead of flatness.
//! 2. The newest bar's age is **not** feed freshness. A quiet coin's newest bar is arbitrarily
//!    old while the read itself is seconds old, so bar clocks and acquisition clocks are kept in
//!    different fields and never collapsed into one "staleness".
//! 3. The window **names no coin**. The route's mint lives only in the URL path, and the retained
//!    acquisition keeps the path template with `{mint}` unresolved plus a one-way request
//!    fingerprint. Nothing durable in the catalog says which coin a candle window is for, so this
//!    surface will not guess: bars are attached to a mint only when an operator states it, and
//!    that statement is rendered as `attested` evidence next to `observed` bars.

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
    /// Retained pump `candles` windows this cutoff held.
    pub candle_windows: u64,
    /// Windows holding bars that reached no candidate, because the bytes name no coin.
    pub candle_windows_unattributed: u64,
    /// Bars actually placed in the scene.
    pub candle_bars_rendered: u64,
    /// Bar spacing recovered from the retained timestamps alone, in seconds.
    ///
    /// This is the greatest common divisor of the observed gaps, so it is an upper bound on the
    /// interval the request asked for: the request argument itself is never retained. `None` when
    /// fewer than two bars were rendered and no spacing is knowable.
    pub candle_spacing_seconds: Option<String>,
    /// Adjacent bar pairs further apart than one spacing: stretches in which nothing traded.
    pub candle_gaps: u64,
    /// Spacing-sized intervals the provider omitted between the oldest and newest rendered bar.
    pub candle_omitted_intervals: u64,
    /// How the rendered bars reached a mint, or why they did not.
    pub candle_subject_binding: &'static str,
    /// Newest rendered bar clock. A market clock: it is not this source's freshness.
    pub candle_newest_bar_at: Option<String>,
    /// Newest acquisition clock for the bytes those bars came out of. This one is freshness.
    pub candle_window_known_at: Option<String>,
    pub ceiling: &'static str,
}

/// Everything an operator states about a derivation, and nothing else.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct LiveSurfaceOptions {
    /// Mint an operator states a retained, coin-anonymous `candles` window belongs to.
    ///
    /// A pump `candles` response is a bare OHLCV array, and the retained acquisition keeps the
    /// `{mint}` path *template* plus a one-way request fingerprint rather than the resolved path.
    /// Nothing durable in the catalog therefore says which coin a window is for. Setting this
    /// attaches the bars to that mint and records the binding as `attested` evidence sitting next
    /// to the `observed` bars; leaving it unset leaves the window unrendered and counted.
    pub attested_candle_subject: Option<String>,
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
pub fn derive_live_surface(
    store: &SqliteStore,
    source_id: &SourceId,
    cutoff: Option<CommitSeq>,
) -> Result<LiveSurfaceDerivation, LiveSurfaceError> {
    derive_live_surface_with(store, source_id, cutoff, &LiveSurfaceOptions::default())
}

/// Derives the exact witnessed Glass view, honouring what an operator stated about the catalog.
///
/// # Errors
///
/// Refuses when the source delivered nothing, when no observation names a renderable subject
/// (including when the only price bytes present name no coin), or when the derived bytes fail
/// exact Glass V1 validation.
#[allow(clippy::too_many_lines)] // Every derived field stays visible next to the row it came from.
pub fn derive_live_surface_with(
    store: &SqliteStore,
    source_id: &SourceId,
    cutoff: Option<CommitSeq>,
    options: &LiveSurfaceOptions,
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
    let mut attempts: BTreeMap<String, PumpAttempt> = BTreeMap::new();
    let mut bodies: BTreeMap<String, &DurableSourceObservation> = BTreeMap::new();

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
        match decode_observation(observation) {
            DecodedObservation::Subjects(named) => {
                for named in named {
                    let entry = subjects.entry(named.subject.clone()).or_default();
                    entry.evidence.push(EvidenceDraft {
                        id: observation.observation_id.to_string(),
                        source_id: observation.source_id.to_string(),
                        field: "mint".to_owned(),
                        evidence_class: "observed",
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
            DecodedObservation::PumpAttempt(attempt) => {
                attempts.insert(observation.acquisition_id.to_string(), attempt);
            }
            DecodedObservation::PumpBody => {
                bodies.insert(observation.acquisition_id.to_string(), observation);
            }
            DecodedObservation::Unrenderable(reason) => unrendered.push(UnrenderedObservation {
                observation_id: observation.observation_id.to_string(),
                locator: observation.source_locator_redacted.clone(),
                reason,
            }),
        }
    }

    // Join each retained provider body to the attempt envelope that names its route. A body on
    // its own is a bare array with no route, no mint and no interval, so a body whose sibling
    // envelope is absent is named as unrendered rather than guessed at.
    let mut windows: Vec<CandleWindow> = Vec::new();
    for (acquisition_id, body) in bodies {
        let refuse = |unrendered: &mut Vec<UnrenderedObservation>, reason: String| {
            unrendered.push(UnrenderedObservation {
                observation_id: body.observation_id.to_string(),
                locator: body.source_locator_redacted.clone(),
                reason,
            });
        };
        let Some(attempt) = attempts.get(&acquisition_id) else {
            refuse(
                &mut unrendered,
                "retained provider body has no sibling attempt envelope naming its route"
                    .to_owned(),
            );
            continue;
        };
        if attempt.route_id != CANDLE_ROUTE {
            refuse(
                &mut unrendered,
                format!(
                    "retained {} body carries no price series this surface reads",
                    attempt.route_id
                ),
            );
            continue;
        }
        if !attempt.succeeded() {
            refuse(
                &mut unrendered,
                format!(
                    "candles read returned HTTP {}, so its body is an error document and not a \
                     price series",
                    attempt
                        .http_status
                        .map_or_else(|| "with no status".to_owned(), |value| value.to_string())
                ),
            );
            continue;
        }
        match parse_candle_window(&body.payload) {
            Ok(rows) => windows.push(CandleWindow {
                observation_id: body.observation_id.to_string(),
                source_id: body.source_id.to_string(),
                ingested_at: body.received_at,
                known_at: body.available_at,
                rows,
                schema_trust: schema_trust(
                    store,
                    &attempt.route_id,
                    &acquisition_id,
                    durable.through_commit_seq,
                )?,
            }),
            Err(reason) => refuse(&mut unrendered, reason),
        }
    }

    let series = CandleSeries::merge(windows).map_err(LiveSurfaceError::CandleWindows)?;
    let mut binding = if series.is_empty() {
        "no_candle_window_retained"
    } else {
        "unattributed_bytes_name_no_coin"
    };
    if let Some(mint) = options.attested_candle_subject.as_deref()
        && let Some(attached) = series.attach(mint, &mut subjects, rendered_at)
    {
        binding = attached;
    }
    let unattributed_windows = if binding == "operator_attested_not_witnessed" {
        0
    } else {
        u64::try_from(series.window_count()).unwrap_or(u64::MAX)
    };
    if unattributed_windows > 0 {
        unrendered.extend(series.unattributed_notes());
    }

    if subjects.is_empty() {
        if !series.is_empty() {
            return Err(LiveSurfaceError::CandlesNameNoSubject {
                source_id: source_id.to_string(),
                windows: series.window_count(),
                bars: series.bar_count(),
            });
        }
        return Err(LiveSurfaceError::NoRenderableSubject {
            source_id: source_id.to_string(),
            observations: durable.observations.len(),
        });
    }

    let price_series_rendered = subjects.values().any(|draft| !draft.candles.is_empty());
    let scene_id = scene_identity(&durable);
    let candidates = candidate_wires(&subjects, rendered_at)?;
    let health = source_health(
        &durable,
        &watermark,
        event_clock_count,
        rendered_at,
        price_series_rendered,
    );
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
    let rendered = series.rendered_shape(price_series_rendered);
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
        price_series_rendered,
        candle_windows: u64::try_from(series.window_count()).unwrap_or(u64::MAX),
        candle_windows_unattributed: unattributed_windows,
        candle_bars_rendered: rendered.bars,
        candle_spacing_seconds: rendered.spacing_seconds.map(|value| value.to_string()),
        candle_gaps: rendered.gaps,
        candle_omitted_intervals: rendered.omitted_intervals,
        candle_subject_binding: binding,
        candle_newest_bar_at: rendered.newest_bar_at,
        candle_window_known_at: rendered.window_known_at,
        ceiling: if price_series_rendered {
            "provider_asserted_price_path_no_unit_no_fill_no_executability"
        } else {
            "chain_identity_only_no_price_no_fill"
        },
    };
    Ok(LiveSurfaceDerivation { view, report })
}

#[derive(Default)]
struct SubjectDraft {
    evidence: Vec<EvidenceDraft>,
    slots: Vec<u64>,
    candles: Vec<CandleWire>,
    /// Exact, derived sentence describing the attached price path, when one is attached.
    price_note: Option<String>,
    /// At least one attached window came from a read this project's schema gate did not promote.
    schema_unpromoted: bool,
}

struct EvidenceDraft {
    /// Wire identity of this evidence row. Distinct from the observation identity when one set
    /// of bytes supports two different claims: bars that were observed, and a binding attested.
    id: String,
    source_id: String,
    field: String,
    evidence_class: &'static str,
    observed_at: Option<UtcTimestamp>,
    ingested_at: UtcTimestamp,
    known_at: UtcTimestamp,
    note: String,
}

struct NamedSubject {
    subject: String,
    note: String,
}

/// Route identity, as the pinned Pump catalog spells it, for the OHLCV window route.
const CANDLE_ROUTE: &str = "candles";

/// The exact `joshi.pump_api.acquisition.v1` fields this surface reads back.
struct PumpAttempt {
    route_id: String,
    http_status: Option<u64>,
}

impl PumpAttempt {
    fn succeeded(&self) -> bool {
        self.http_status
            .is_some_and(|status| (200..300).contains(&status))
    }
}

enum DecodedObservation {
    Subjects(Vec<NamedSubject>),
    PumpAttempt(PumpAttempt),
    PumpBody,
    Unrenderable(String),
}

/// Reads the retained provider bytes and names only what the bytes themselves state.
fn decode_observation(observation: &DurableSourceObservation) -> DecodedObservation {
    if let Ok(envelope) = serde_json::from_slice::<RetainedFrameEnvelope>(&observation.payload) {
        return decode_chain_frame(observation, &envelope);
    }
    // A Pump product read admits exactly two observations per attempt: the acquisition envelope
    // under `obs:<acquisition>:attempt`, and the exact provider bytes under `obs:<acquisition>:body`.
    // The identity, not a sniffed payload shape, decides which one this is.
    if observation.observation_id.as_str() == format!("obs:{}:attempt", observation.acquisition_id)
    {
        return match serde_json::from_slice::<serde_json::Value>(&observation.payload) {
            Ok(value)
                if value.get("contract").and_then(serde_json::Value::as_str)
                    == Some("joshi.pump_api.acquisition.v1") =>
            {
                DecodedObservation::PumpAttempt(PumpAttempt {
                    route_id: value
                        .get("routeId")
                        .and_then(serde_json::Value::as_str)
                        .unwrap_or_default()
                        .to_owned(),
                    http_status: value.get("httpStatus").and_then(serde_json::Value::as_u64),
                })
            }
            _ => DecodedObservation::Unrenderable(
                "attempt observation is not a joshi.pump_api.acquisition.v1 envelope".to_owned(),
            ),
        };
    }
    if observation.observation_id.as_str() == format!("obs:{}:body", observation.acquisition_id) {
        return DecodedObservation::PumpBody;
    }
    DecodedObservation::Unrenderable(
        "retained payload is neither a joshi.raw_source_frame.v1 envelope nor a Pump product read"
            .to_owned(),
    )
}

/// Names the SPL mints one retained Solana RPC response mentions, and nothing further.
fn decode_chain_frame(
    observation: &DurableSourceObservation,
    envelope: &RetainedFrameEnvelope,
) -> DecodedObservation {
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

// ---------------------------------------------------------------------------------------------
// Pump `candles` windows.
//
// A window is a bare top-level JSON array of OHLCV rows. Every price is a decimal STRING with up
// to 28 fractional digits, and it is carried to the wire byte-for-byte: parsing one into an f64
// would silently drop digits Ember can lose money on, and re-formatting one would make the same
// number print as two different strings. The only arithmetic done here is on the integer bar
// clocks.
// ---------------------------------------------------------------------------------------------

/// One retained OHLCV row, exactly as the provider wrote it.
#[derive(Clone, Debug)]
struct CandleRow {
    time_unix: u64,
    open: String,
    high: String,
    low: String,
    close: String,
    volume: String,
}

/// One retained provider body that parsed as an ascending OHLCV window.
struct CandleWindow {
    observation_id: String,
    source_id: String,
    ingested_at: UtcTimestamp,
    known_at: UtcTimestamp,
    rows: Vec<CandleRow>,
    /// What this project's own schema gate decided about the read these bytes came from.
    ///
    /// A refusal still retains the bytes, so bars can be parsed out of a window whose shape was
    /// never reviewed. That is a fact about the provenance of a price, and it is carried to the
    /// screen rather than dropped because the parse happened to succeed.
    schema_trust: SchemaTrust,
}

/// The schema gate's recorded decision about one read, or the absence of one.
struct SchemaTrust {
    outcome: Option<String>,
    reason_code: Option<String>,
    review_id: Option<String>,
}

impl SchemaTrust {
    fn promoted(&self) -> bool {
        self.outcome.as_deref() == Some("promoted")
    }

    /// A sentence naming the gate's decision, never softened into silence.
    fn sentence(&self) -> String {
        match (self.outcome.as_deref(), self.reason_code.as_deref()) {
            (Some("promoted"), _) => format!(
                "This project's schema gate promoted the read these bars came from, against \
                 review {}.",
                self.review_id.as_deref().unwrap_or("an unnamed review"),
            ),
            (Some(outcome), reason) => format!(
                "This project's schema gate recorded the read these bars came from as {outcome}{}: \
                 the bytes were retained but their shape was never promoted, so these prices are \
                 provider assertions that passed no review.",
                reason.map_or_else(String::new, |value| format!(" ({value})")),
            ),
            (None, _) => "This project's schema gate recorded no decision for the read these bars \
                 came from, so nothing has reviewed the shape they were parsed out of."
                .to_owned(),
        }
    }
}

/// Facts about the rendered path that the frozen Glass contract has nowhere to carry.
struct RenderedShape {
    bars: u64,
    spacing_seconds: Option<u64>,
    gaps: u64,
    omitted_intervals: u64,
    newest_bar_at: Option<String>,
    window_known_at: Option<String>,
}

/// Every retained candle window in this cutoff, merged when they agree on a bar spacing.
#[derive(Default)]
struct CandleSeries {
    windows: Vec<CandleWindow>,
    /// Merged rows keyed by bar clock, newest knowledge winning a disagreement.
    rows: BTreeMap<u64, CandleRow>,
    /// Bar clocks two windows both carried with different prices.
    revisions: u64,
}

impl CandleSeries {
    /// Merge every window that agrees on a bar spacing.
    ///
    /// Two windows read at different intervals describe two different grids, and interleaving
    /// them would invent a path neither one asserts, so a spacing disagreement refuses instead.
    fn merge(windows: Vec<CandleWindow>) -> Result<Self, String> {
        let mut spacings: BTreeMap<u64, Vec<String>> = BTreeMap::new();
        for window in &windows {
            if let Some(spacing) = spacing_seconds(&window.rows) {
                spacings
                    .entry(spacing)
                    .or_default()
                    .push(window.observation_id.clone());
            }
        }
        if spacings.len() > 1 {
            let described = spacings
                .iter()
                .map(|(spacing, observations)| {
                    format!("{spacing}s from {}", observations.join(", "))
                })
                .collect::<Vec<_>>()
                .join("; ");
            return Err(format!(
                "this catalog holds candle windows on {} different bar spacings ({described}). \
                 They are different grids, not one path, so nothing is merged; narrow the catalog \
                 to one interval",
                spacings.len(),
            ));
        }
        let mut rows: BTreeMap<u64, CandleRow> = BTreeMap::new();
        let mut known: BTreeMap<u64, UtcTimestamp> = BTreeMap::new();
        let mut revisions = 0_u64;
        for window in &windows {
            for row in &window.rows {
                if let Some(existing) = rows.get(&row.time_unix) {
                    let differs = existing.open != row.open
                        || existing.high != row.high
                        || existing.low != row.low
                        || existing.close != row.close
                        || existing.volume != row.volume;
                    if differs {
                        revisions += 1;
                    }
                    let newer = known
                        .get(&row.time_unix)
                        .is_none_or(|value| window.known_at.as_datetime() > value.as_datetime());
                    if !newer {
                        continue;
                    }
                }
                rows.insert(row.time_unix, row.clone());
                known.insert(row.time_unix, window.known_at);
            }
        }
        Ok(Self {
            windows,
            rows,
            revisions,
        })
    }

    fn is_empty(&self) -> bool {
        self.windows.is_empty()
    }

    fn window_count(&self) -> usize {
        self.windows.len()
    }

    /// True when every window's read was promoted by this project's own schema gate.
    fn every_window_promoted(&self) -> bool {
        self.windows
            .iter()
            .all(|window| window.schema_trust.promoted())
    }

    fn bar_count(&self) -> usize {
        self.rows.len()
    }

    fn newest_known_at(&self) -> Option<UtcTimestamp> {
        self.windows
            .iter()
            .map(|window| window.known_at)
            .max_by_key(|value: &UtcTimestamp| value.as_datetime())
    }

    /// Every window this surface holds but could not attach to a coin.
    fn unattributed_notes(&self) -> Vec<UnrenderedObservation> {
        self.windows
            .iter()
            .map(|window| UnrenderedObservation {
                observation_id: window.observation_id.clone(),
                locator: None,
                reason: format!(
                    "{} retained candle bar(s), but a pump candles response names no coin and the \
                     retained acquisition keeps only the `{{mint}}` path template plus a one-way \
                     request fingerprint. Nothing here says which coin these bars are; state it \
                     with --candles-subject <MINT> if you know it",
                    window.rows.len(),
                ),
            })
            .collect()
    }

    /// Facts about the path as rendered, or explicit absences when nothing was rendered.
    fn rendered_shape(&self, rendered: bool) -> RenderedShape {
        if !rendered {
            return RenderedShape {
                bars: 0,
                spacing_seconds: None,
                gaps: 0,
                omitted_intervals: 0,
                newest_bar_at: None,
                window_known_at: None,
            };
        }
        let clocks = self.rows.keys().copied().collect::<Vec<_>>();
        let spacing = spacing_of(&clocks);
        let (gaps, omitted) = gap_shape(&clocks, spacing);
        RenderedShape {
            bars: u64::try_from(clocks.len()).unwrap_or(u64::MAX),
            spacing_seconds: spacing,
            gaps,
            omitted_intervals: omitted,
            newest_bar_at: clocks.last().map(|value| unix_instant(*value)),
            window_known_at: self.newest_known_at().map(|value| value.to_string()),
        }
    }

    /// Attach the merged path to the mint an operator stated, recording that binding as attested.
    ///
    /// Returns the binding label when bars actually reached the scene, `None` when they could not.
    fn attach(
        &self,
        mint: &str,
        subjects: &mut BTreeMap<String, SubjectDraft>,
        rendered_at: UtcTimestamp,
    ) -> Option<&'static str> {
        // The frozen contract refuses a one-sample series, because one bar implies an interval it
        // does not have. That bar is still real, so it is named in prose instead of drawn.
        if self.rows.len() < 2 {
            return None;
        }
        let clocks = self.rows.keys().copied().collect::<Vec<_>>();
        let spacing = spacing_of(&clocks);
        let (gaps, omitted) = gap_shape(&clocks, spacing);
        let oldest = *clocks.first().unwrap_or(&0);
        let newest = *clocks.last().unwrap_or(&0);
        let entry = subjects.entry(mint.to_owned()).or_default();
        entry.candles = self
            .rows
            .values()
            .map(|row| CandleWire {
                time_unix: row.time_unix.to_string(),
                known_at: self.newest_known_at().unwrap_or(rendered_at).to_string(),
                open: row.open.clone(),
                high: row.high.clone(),
                low: row.low.clone(),
                close: row.close.clone(),
                volume_tokens: row.volume.clone(),
            })
            .collect();
        if !self.every_window_promoted() {
            entry.schema_unpromoted = true;
        }
        entry.price_note = Some(format!(
            "{} bar(s) retained from {} pump candles window(s), spaced in multiples of {} \
             (the greatest common divisor of the {} observed steps; the request's own interval \
             argument is not retained, so the true interval may divide this). {} of those steps \
             are longer than one spacing and {} spacing-sized interval(s) are omitted because \
             nothing traded in them, so this is a price path with holes and not a grid. Bars run \
             {} to {}. The provider labels these five fields open/high/low/close/volume and \
             states no unit for any of them, so none is named here. {}",
            clocks.len(),
            self.windows.len(),
            spacing.map_or_else(|| "an unknown step".to_owned(), duration_words),
            clocks.len().saturating_sub(1),
            gaps,
            omitted,
            unix_instant(oldest),
            unix_instant(newest),
            if self.revisions == 0 {
                "No two windows disagreed about a shared bar."
            } else {
                "Windows disagreed about at least one shared bar; the later read won."
            },
        ));
        for window in &self.windows {
            entry.evidence.push(EvidenceDraft {
                id: window.observation_id.clone(),
                source_id: window.source_id.clone(),
                field: "candles".to_owned(),
                evidence_class: "observed",
                observed_at: None,
                ingested_at: window.ingested_at,
                known_at: window.known_at,
                note: format!(
                    "{} OHLCV row(s) copied byte-for-byte out of this retained provider body. {} \
                     The newest bar clock is a market clock: on a quiet coin it is arbitrarily \
                     older than this read, and it must never be read as how fresh this feed is.",
                    window.rows.len(),
                    window.schema_trust.sentence(),
                ),
            });
            entry.evidence.push(EvidenceDraft {
                id: format!("{}:operator-attested-subject", window.observation_id),
                source_id: window.source_id.clone(),
                field: "mint".to_owned(),
                evidence_class: "attested",
                observed_at: None,
                ingested_at: window.ingested_at,
                known_at: window.known_at,
                note: format!(
                    "An operator stated that this coin-anonymous candle window belongs to {mint}. \
                     The retained bytes do not say so: a candles response carries no mint, and \
                     the acquisition keeps the `{{mint}}` path template plus a one-way request \
                     fingerprint. This binding is attested, not observed.",
                ),
            });
        }
        Some("operator_attested_not_witnessed")
    }
}

/// Read back the schema gate's own decision about one product read, as known at this cutoff.
fn schema_trust(
    store: &SqliteStore,
    route_id: &str,
    acquisition_id: &str,
    cutoff: CommitSeq,
) -> Result<SchemaTrust, LiveSurfaceError> {
    // The semantic key `joshi-pump-adapter` writes the decision under. An absent decision is an
    // absence, never an implied promotion.
    let key = format!("pump.schema_trust:{route_id}:{acquisition_id}");
    let assertions = store.effective_assertions_as_known(&key, cutoff)?;
    let Some(assertion) = assertions.first() else {
        return Ok(SchemaTrust {
            outcome: None,
            reason_code: None,
            review_id: None,
        });
    };
    let decision = assertion.value.get("decision");
    let text = |name: &str| {
        decision
            .and_then(|value| value.get(name))
            .and_then(serde_json::Value::as_str)
            .map(ToOwned::to_owned)
    };
    Ok(SchemaTrust {
        outcome: text("outcome"),
        reason_code: text("reasonCode"),
        review_id: text("reviewId"),
    })
}

/// Parse one retained body as an ascending OHLCV window, refusing anything it cannot carry exactly.
fn parse_candle_window(bytes: &[u8]) -> Result<Vec<CandleRow>, String> {
    let value: serde_json::Value = serde_json::from_slice(bytes)
        .map_err(|error| format!("retained candles body is not JSON: {error}"))?;
    let rows = value
        .as_array()
        .ok_or_else(|| "retained candles body is not a bare top-level JSON array".to_owned())?;
    let mut parsed = Vec::with_capacity(rows.len());
    let mut previous: Option<u64> = None;
    for (ordinal, row) in rows.iter().enumerate() {
        let object = row
            .as_object()
            .ok_or_else(|| format!("candle row {ordinal} is not a JSON object"))?;
        let millis = object
            .get("timestamp")
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| {
                format!("candle row {ordinal} has no non-negative integer `timestamp`")
            })?;
        if millis % 1000 != 0 {
            return Err(format!(
                "candle row {ordinal} is stamped {millis}ms, which is not a whole second. The \
                 Glass bar clock is Unix seconds, and rounding would move the bar"
            ));
        }
        let time_unix = millis / 1000;
        if previous.is_some_and(|value| time_unix <= value) {
            return Err(format!(
                "candle row {ordinal} at {time_unix}s does not advance on the row before it; the \
                 catalog records this route as ascending oldest-first"
            ));
        }
        previous = Some(time_unix);
        let field = |name: &str| -> Result<String, String> {
            let text = object
                .get(name)
                .and_then(serde_json::Value::as_str)
                .ok_or_else(|| format!("candle row {ordinal} field `{name}` is not a string"))?;
            if exact_decimal(text) {
                Ok(text.to_owned())
            } else {
                Err(format!(
                    "candle row {ordinal} field `{name}` is {text:?}, which is not an exact \
                     base-10 decimal the Glass contract accepts"
                ))
            }
        };
        parsed.push(CandleRow {
            time_unix,
            open: field("open")?,
            high: field("high")?,
            low: field("low")?,
            close: field("close")?,
            volume: field("volume")?,
        });
    }
    Ok(parsed)
}

/// The exact decimal grammar the frozen Glass contract accepts, checked before the wire is built
/// so a refusal names the offending row instead of the whole document.
fn exact_decimal(value: &str) -> bool {
    let unsigned = value.strip_prefix('-').unwrap_or(value);
    let (integer, fraction) = unsigned
        .split_once('.')
        .map_or((unsigned, None), |(left, right)| (left, Some(right)));
    !integer.is_empty()
        && integer.bytes().all(|byte| byte.is_ascii_digit())
        && !(integer.len() > 1 && integer.starts_with('0'))
        && fraction.is_none_or(|part| !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit()))
}

/// Bar spacing implied by the retained clocks alone: the greatest common divisor of the steps.
fn spacing_seconds(rows: &[CandleRow]) -> Option<u64> {
    spacing_of(&rows.iter().map(|row| row.time_unix).collect::<Vec<_>>())
}

fn spacing_of(clocks: &[u64]) -> Option<u64> {
    let mut accumulator = 0_u64;
    for pair in clocks.windows(2) {
        accumulator = gcd(accumulator, pair[1].saturating_sub(pair[0]));
    }
    (accumulator > 0).then_some(accumulator)
}

/// How many steps exceed one spacing, and how many spacing-sized intervals were omitted.
fn gap_shape(clocks: &[u64], spacing: Option<u64>) -> (u64, u64) {
    let Some(spacing) = spacing else {
        return (0, 0);
    };
    let mut gaps = 0_u64;
    let mut omitted = 0_u64;
    for pair in clocks.windows(2) {
        let step = pair[1].saturating_sub(pair[0]);
        let slots = step / spacing;
        if slots > 1 {
            gaps += 1;
            omitted += slots - 1;
        }
    }
    (gaps, omitted)
}

fn gcd(left: u64, right: u64) -> u64 {
    let (mut left, mut right) = (left, right);
    while right != 0 {
        let next = left % right;
        left = right;
        right = next;
    }
    left
}

/// Render one bar clock as the canonical instant this project writes everywhere else.
fn unix_instant(seconds: u64) -> String {
    let nanos = i128::from(seconds).saturating_mul(1_000_000_000);
    time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .ok()
        .and_then(|value| UtcTimestamp::new(value).ok())
        .map_or_else(
            || format!("unix second {seconds}"),
            |value| value.to_string(),
        )
}

/// A spacing in words, so a caption never has to hardcode an interval name.
fn duration_words(seconds: u64) -> String {
    match seconds {
        0 => "no step".to_owned(),
        value if value % 86_400 == 0 => format!("{}h", value / 3_600),
        value if value % 3_600 == 0 => format!("{}h", value / 3_600),
        value if value % 60 == 0 => format!("{}m", value / 60),
        value => format!("{value}s"),
    }
}

fn candidate_wires(
    subjects: &BTreeMap<String, SubjectDraft>,
    rendered_at: UtcTimestamp,
) -> Result<Vec<CandidateWire>, LiveSurfaceError> {
    let mut candidates = Vec::with_capacity(subjects.len());
    for (ordinal, (mint, draft)) in subjects.iter().enumerate() {
        let mut evidence = draft.evidence.iter().collect::<Vec<_>>();
        evidence.sort_by(|left, right| left.id.cmp(&right.id));
        evidence.dedup_by(|left, right| left.id == right.id);
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
        let slot_text = slot_phrase(&draft.slots);
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
                "Carries {} evidence row{}{slot_text}. Rows are ordered by mint identity; this is \
                 not an attention ranking. {}",
                evidence.len(),
                if evidence.len() == 1 { "" } else { "s" },
                draft.price_note.as_deref().unwrap_or(
                    "No price series is attached to this mint, so no price, size, market cap or \
                     fill is claimed for it.",
                ),
            ),
            social_summary: "No social source was acquired in this cut.".to_owned(),
            tags: if draft.candles.is_empty() {
                vec![
                    "chain_observed".to_owned(),
                    "no_price_observed".to_owned(),
                    "ticker_unobserved".to_owned(),
                ]
            } else {
                let mut tags = vec![
                    "gap_compressed_path".to_owned(),
                    "provider_asserted_price".to_owned(),
                    "subject_operator_attested".to_owned(),
                    "ticker_unobserved".to_owned(),
                    "unit_unstated".to_owned(),
                ];
                if draft.schema_unpromoted {
                    tags.push("schema_unpromoted".to_owned());
                }
                tags.sort();
                tags
            },
            watched: false,
            episode_id: None,
            evidence: evidence.into_iter().map(evidence_wire).collect(),
            // Empty unless a retained candles window was attached above: a bar JOSHI did not see
            // is a market claim it may not make, and neither is a bar it cannot attribute.
            candles: draft.candles.clone(),
        });
    }
    Ok(candidates)
}

/// The chain slots a subject was named at, as a clause a sentence can carry.
fn slot_phrase(slots: &[u64]) -> String {
    let mut slots = slots.to_vec();
    slots.sort_unstable();
    slots.dedup();
    if slots.is_empty() {
        return ", which state no chain slot".to_owned();
    }
    format!(
        " at slot{} {}",
        if slots.len() == 1 { "" } else { "s" },
        slots
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join(", ")
    )
}

/// One evidence row on the wire. Its class is carried from the draft rather than assumed, so a
/// binding an operator stated can never render beside observed bytes as though it were observed.
fn evidence_wire(entry: &EvidenceDraft) -> EvidenceRefWire {
    EvidenceRefWire {
        id: entry.id.clone(),
        source_id: entry.source_id.clone(),
        field: entry.field.clone(),
        evidence_class: entry.evidence_class.to_owned(),
        observed_at: entry.observed_at.map(|value| value.to_string()),
        ingested_at: entry.ingested_at.to_string(),
        known_at: entry.known_at.to_string(),
        status: "available".to_owned(),
        note: entry.note.clone(),
    }
}

fn source_health(
    durable: &DurableSourceObservations,
    watermark: &joshi_domain::SourceAsOf,
    event_clock_count: u64,
    rendered_at: UtcTimestamp,
    price_series_rendered: bool,
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
             are retained without an assertion layer beneath them. {} Coverage outside these \
             commits is unknown rather than empty. The ingest clock above is this source's \
             freshness; a bar clock inside a candidate is a market clock and is not. Rendered at \
             {rendered_at}.",
            if quality_notes == 1 { "" } else { "s" },
            if price_series_rendered {
                "One or more candidates carry an OHLCV path the provider asserted, copied out \
                 verbatim: those bars are provider claims about price, not fills, not quotes, \
                 not executability, and the provider states no unit for them. Nothing else here \
                 is a market claim: no size, market cap or fill is asserted."
            } else {
                "This surface names identities and clocks only: no price, size, market cap or \
                 fill is claimed."
            },
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
    #[error(
        "source {source_id} retained {windows} candle window(s) holding {bars} bar(s), and \
         nothing else that names a subject. A Pump candles response is a bare OHLCV array that \
         names no coin, and the retained acquisition keeps the `{{mint}}` path template plus a \
         one-way request fingerprint rather than the resolved path, so this catalog does not say \
         which coin these bars are. Re-run with --candles-subject <MINT> to state it yourself; it \
         will be rendered as attested, not observed"
    )]
    CandlesNameNoSubject {
        source_id: String,
        windows: usize,
        bars: usize,
    },
    #[error("retained candle windows cannot be merged: {0}")]
    CandleWindows(String),
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

#[derive(Clone, Serialize)]
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

#[cfg(test)]
mod tests {
    use super::{
        CandleRow, DecodedObservation, LiveSurfaceOptions, decode_observation,
        derive_live_surface_with, gap_shape, parse_candle_window, source_identity, spacing_of,
    };
    use joshi_domain::{StableString, UtcTimestamp};
    use joshi_pump_adapter::{ProductReadInput, close_receipt, prepare_direct_product_read};
    use joshi_pump_api::AuthenticatedPathDecision;
    use joshi_store::{SqliteStore, StoreConfig, StoreMode};
    use std::{path::Path, time::Duration};

    /// One verbatim `FetchOutcome` the bounded source-edge client emitted on 2026-08-22 against
    /// `https://swap-api.pump.fun/v1/coins/{mint}/candles` for a real mainnet mint. Its body is
    /// 200 gap-compressed one-second bars, which is exactly the shape this surface has to render
    /// honestly: 200 bars spread over 8952 wall-clock seconds.
    const CANDLES_OUTCOME: &str =
        include_str!("../../../crates/joshi-pump-api/fixtures/candles_live_outcome_v1.json");
    const CANDLES_REVIEW: &str =
        include_str!("../../../crates/joshi-pump-api/fixtures/schema_review_candles_v1.json");
    const COMMITTED_AT: &str = "2026-08-22T01:30:00.000000Z";
    /// The mint the operator actually asked the swap API for. The retained bytes do not say it.
    const SUBJECT: &str = "HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump";

    /// The exact store layout `joshi-pump-product-read` writes into its `--state-dir`, including
    /// its zero inline ceiling: every retained body lands in the content-addressed blob tree, so
    /// mounting it also has to carry that tree across.
    fn config(root: &Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 0,
            busy_timeout: Duration::from_secs(5),
            catalog_id: StableString::new("joshi-live-surface-candles").expect("catalog id"),
            max_observations_per_batch: 64,
            max_raw_bytes_per_batch: 4 * 1024 * 1024,
        }
    }

    fn committed_at() -> UtcTimestamp {
        COMMITTED_AT.parse().expect("canonical instant")
    }

    /// Admit the real candles read exactly as `joshi-pump-product-read` does.
    fn store_with_candles(root: &Path) -> SqliteStore {
        store_with_review(root, Some(CANDLES_REVIEW.as_bytes()))
    }

    fn store_with_review(root: &Path, review_bytes: Option<&[u8]>) -> SqliteStore {
        let prepared = prepare_direct_product_read(&ProductReadInput {
            outcome_bytes: CANDLES_OUTCOME.trim_end().as_bytes(),
            review_bytes,
            authenticated_path: AuthenticatedPathDecision::NotPerformed,
            session_reason_code: "no_documented_authenticated_get_read_route_for_present_credential",
            session_detail: "undocumented public product route read with no session provider",
            durable_batch_id: "batch:pump-tap:candles",
            committed_at: committed_at(),
            committed_monotonic_ns: 1,
            decided_at: COMMITTED_AT,
        })
        .expect("prepared product read");
        let mut store =
            SqliteStore::open(config(root), StoreMode::SingleWriter).expect("open store");
        store.migrate(committed_at()).expect("migrate");
        let receipt = prepared
            .prepared
            .admission_batch()
            .commit(&mut store)
            .expect("commit");
        close_receipt(&prepared.prepared, &receipt).expect("receipt closure");
        store
    }

    fn rows(clocks: &[u64]) -> Vec<CandleRow> {
        clocks
            .iter()
            .map(|clock| CandleRow {
                time_unix: *clock,
                open: "1".to_owned(),
                high: "1".to_owned(),
                low: "1".to_owned(),
                close: "1".to_owned(),
                volume: "1".to_owned(),
            })
            .collect()
    }

    #[test]
    fn a_retained_candle_window_reaches_the_scene_only_when_a_subject_is_stated() {
        let root = tempfile::tempdir().expect("temp root");
        let store = store_with_candles(root.path());
        let source = source_identity("pump.api.product.v1").expect("source identity");

        // Without a stated subject the bars are real, retained, parsed -- and still refused,
        // because a candles response names no coin and this surface will not guess one.
        let refusal =
            derive_live_surface_with(&store, &source, None, &LiveSurfaceOptions::default())
                .expect_err("an unattributed candle window is not a renderable subject");
        let text = refusal.to_string();
        assert!(text.contains("names no coin"), "{text}");
        assert!(text.contains("--candles-subject"), "{text}");

        let derived = derive_live_surface_with(
            &store,
            &source,
            None,
            &LiveSurfaceOptions {
                attested_candle_subject: Some(SUBJECT.to_owned()),
            },
        )
        .expect("stating the subject renders the retained path");
        let report = &derived.report;
        assert!(report.price_series_rendered);
        assert_eq!(report.candle_windows, 1);
        assert_eq!(report.candle_windows_unattributed, 0);
        assert_eq!(report.candle_bars_rendered, 200);
        // Recovered from the retained clocks alone. The request's `interval` argument is not in
        // the catalog at all, so a hardcoded "30-second interval" caption could only be a lie.
        assert_eq!(report.candle_spacing_seconds.as_deref(), Some("1"));
        // 200 bars over 8952 seconds: 8753 one-second intervals had no trade at all. That silence
        // is counted rather than smoothed over.
        assert_eq!(report.candle_gaps, 141);
        assert_eq!(report.candle_omitted_intervals, 8_753);
        assert_eq!(
            report.candle_subject_binding,
            "operator_attested_not_witnessed"
        );
        // THE HAZARD, live in this real window: the read completed at 01:23:12Z and the newest
        // bar it returned is stamped 01:11:13Z. The coin simply did not trade for the last ~12
        // minutes, so bar age here is 719 seconds while the feed is seconds old. Anything that
        // renders staleness must read the acquisition clock, never the bar clock, and the two
        // therefore live in two different report fields that must not be collapsed.
        assert_eq!(
            report.candle_newest_bar_at.as_deref(),
            Some("2026-08-22T01:11:13.000000Z")
        );
        assert_eq!(
            report.candle_window_known_at.as_deref(),
            Some("2026-08-22T01:30:00.000000Z")
        );
        assert_ne!(report.candle_newest_bar_at, report.candle_window_known_at);
        assert_eq!(
            report.ceiling,
            "provider_asserted_price_path_no_unit_no_fill_no_executability"
        );

        let view: serde_json::Value =
            serde_json::from_slice(derived.view.canonical_bytes()).expect("canonical view");
        let candidate = &view["payload"]["candidates"][0];
        assert_eq!(candidate["mint"], SUBJECT);
        let candles = candidate["candles"].as_array().expect("candle array");
        assert_eq!(candles.len(), 200);
        // The provider's exact 28-digit decimal strings reach the wire byte-for-byte. A float
        // round-trip through this path would silently drop digits.
        assert_eq!(candles[0]["open"], "0.0127543073470319645806409668");
        assert_eq!(candles[0]["timeUnix"], "1787352121");
        assert_eq!(candles[199]["close"], "0.0127875704036029988601137368");
        // The binding of bars to a coin is attested; the bars themselves are observed.
        let classes = candidate["evidence"]
            .as_array()
            .expect("evidence")
            .iter()
            .map(|entry| {
                (
                    entry["field"].as_str().unwrap_or_default().to_owned(),
                    entry["evidenceClass"]
                        .as_str()
                        .unwrap_or_default()
                        .to_owned(),
                )
            })
            .collect::<Vec<_>>();
        assert!(classes.contains(&("candles".to_owned(), "observed".to_owned())));
        assert!(classes.contains(&("mint".to_owned(), "attested".to_owned())));
    }

    #[test]
    fn a_window_whose_schema_was_never_promoted_still_says_so_next_to_its_prices() {
        // The gate refuses a read with no review, and retains its bytes anyway. Bars parse out of
        // those bytes exactly as well, so the refusal has to travel with them to the screen: a
        // price whose shape nothing reviewed must not render identically to one that was.
        let root = tempfile::tempdir().expect("temp root");
        let store = store_with_review(root.path(), None);
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let derived = derive_live_surface_with(
            &store,
            &source,
            None,
            &LiveSurfaceOptions {
                attested_candle_subject: Some(SUBJECT.to_owned()),
            },
        )
        .expect("retained bytes still render");
        let view: serde_json::Value =
            serde_json::from_slice(derived.view.canonical_bytes()).expect("canonical view");
        let candidate = &view["payload"]["candidates"][0];
        assert_eq!(candidate["candles"].as_array().map(Vec::len), Some(200));
        let tags = candidate["tags"].as_array().expect("tags");
        assert!(
            tags.iter().any(|tag| tag == "schema_unpromoted"),
            "{tags:?}"
        );
        let note = candidate["evidence"]
            .as_array()
            .expect("evidence")
            .iter()
            .find(|entry| entry["field"] == "candles")
            .and_then(|entry| entry["note"].as_str())
            .unwrap_or_default();
        assert!(note.contains("refused"), "{note}");
        assert!(note.contains("refused_no_review_for_route"), "{note}");
        assert!(note.contains("passed no review"), "{note}");

        // And the promoted read says the opposite, naming the review it was measured against.
        let promoted_root = tempfile::tempdir().expect("temp root");
        let promoted = derive_live_surface_with(
            &store_with_candles(promoted_root.path()),
            &source,
            None,
            &LiveSurfaceOptions {
                attested_candle_subject: Some(SUBJECT.to_owned()),
            },
        )
        .expect("promoted read renders");
        let promoted_view: serde_json::Value =
            serde_json::from_slice(promoted.view.canonical_bytes()).expect("canonical view");
        let promoted_candidate = &promoted_view["payload"]["candidates"][0];
        assert!(
            !promoted_candidate["tags"]
                .as_array()
                .expect("tags")
                .iter()
                .any(|tag| tag == "schema_unpromoted")
        );
        let promoted_note = promoted_candidate["evidence"]
            .as_array()
            .expect("evidence")
            .iter()
            .find(|entry| entry["field"] == "candles")
            .and_then(|entry| entry["note"].as_str())
            .unwrap_or_default();
        assert!(
            promoted_note.contains("review:pump-candles:2026-08-22:v1"),
            "{promoted_note}"
        );
    }

    #[test]
    fn the_two_commands_ember_runs_chain_over_one_real_catalog_directory() {
        // The whole path, minus the network and the HTTP server: the tap writes a catalog into a
        // state directory, and `live-surface-inspect --catalog <that dir>` mounts it read-only,
        // copies the blob tree, migrates a writable overlay, and derives a scene with real bars.
        let tap = tempfile::tempdir().expect("tap state dir");
        drop(store_with_candles(tap.path()));
        let overlay = tempfile::tempdir().expect("overlay state dir");
        let mounted = crate::live_gesture::mount_live_surface_with(
            tap.path(),
            overlay.path(),
            "pump.api.product.v1",
            &LiveSurfaceOptions {
                attested_candle_subject: Some(SUBJECT.to_owned()),
            },
        )
        .expect("the tap's own state directory mounts as a catalog");
        assert_eq!(mounted.surface.candle_bars_rendered, 200);
        assert!(mounted.surface.price_series_rendered);
        let view: serde_json::Value =
            serde_json::from_slice(mounted.view.canonical_bytes()).expect("canonical view");
        assert_eq!(
            view["payload"]["candidates"][0]["candles"]
                .as_array()
                .map(Vec::len),
            Some(200),
        );
    }

    #[test]
    fn the_same_catalog_derives_the_same_scene_twice() {
        let root = tempfile::tempdir().expect("temp root");
        let store = store_with_candles(root.path());
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let options = LiveSurfaceOptions {
            attested_candle_subject: Some(SUBJECT.to_owned()),
        };
        let first = derive_live_surface_with(&store, &source, None, &options).expect("first");
        let second = derive_live_surface_with(&store, &source, None, &options).expect("second");
        assert_eq!(first.view.digest(), second.view.digest());
        assert_eq!(first.report, second.report);
    }

    #[test]
    fn the_attempt_envelope_and_the_provider_body_are_told_apart_by_identity() {
        let root = tempfile::tempdir().expect("temp root");
        let store = store_with_candles(root.path());
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let durable = store
            .source_observations_as_known(&source, None, super::MAX_LIVE_OBSERVATIONS)
            .expect("read observations")
            .expect("the catalog holds the read");
        assert_eq!(durable.observations.len(), 2);
        let mut attempts = 0;
        let mut bodies = 0;
        for observation in &durable.observations {
            match decode_observation(observation) {
                DecodedObservation::PumpAttempt(attempt) => {
                    assert_eq!(attempt.route_id, "candles");
                    assert!(attempt.succeeded());
                    attempts += 1;
                }
                DecodedObservation::PumpBody => bodies += 1,
                DecodedObservation::Subjects(_) => panic!("a candle window names no subject"),
                DecodedObservation::Unrenderable(reason) => panic!("unrenderable: {reason}"),
            }
        }
        assert_eq!((attempts, bodies), (1, 1));
    }

    #[test]
    fn a_window_that_is_not_ascending_is_refused_rather_than_sorted() {
        let bytes = br#"[{"timestamp":2000,"open":"1","high":"1","low":"1","close":"1","volume":"1"},
                         {"timestamp":1000,"open":"1","high":"1","low":"1","close":"1","volume":"1"}]"#;
        let error = parse_candle_window(bytes).expect_err("descending rows are a real finding");
        assert!(error.contains("does not advance"), "{error}");
    }

    #[test]
    fn a_sub_second_bar_clock_is_refused_rather_than_rounded() {
        let bytes =
            br#"[{"timestamp":1500,"open":"1","high":"1","low":"1","close":"1","volume":"1"}]"#;
        let error = parse_candle_window(bytes).expect_err("a rounded bar is a moved bar");
        assert!(error.contains("whole second"), "{error}");
    }

    #[test]
    fn a_price_that_is_not_an_exact_decimal_is_refused_rather_than_coerced() {
        let bytes =
            br#"[{"timestamp":1000,"open":"1e-9","high":"1","low":"1","close":"1","volume":"1"}]"#;
        let error = parse_candle_window(bytes).expect_err("scientific notation is not a decimal");
        assert!(error.contains("base-10 decimal"), "{error}");
    }

    #[test]
    fn spacing_is_the_common_divisor_of_the_steps_and_never_an_assumed_interval() {
        // Three bars 60s and 300s apart: the market was quiet for four minutes in the middle.
        let clocks = [0_u64, 60, 360];
        assert_eq!(spacing_of(&clocks), Some(60));
        assert_eq!(gap_shape(&clocks, Some(60)), (1, 4));
        // A series in which no two bars are adjacent cannot prove the interval is not smaller;
        // the divisor is an upper bound and the caption has to say so.
        let sparse = [0_u64, 120, 240];
        assert_eq!(spacing_of(&sparse), Some(120));
        assert_eq!(gap_shape(&sparse, Some(120)), (0, 0));
        assert_eq!(
            spacing_of(
                &rows(&[7])
                    .iter()
                    .map(|row| row.time_unix)
                    .collect::<Vec<_>>()
            ),
            None
        );
    }
}
