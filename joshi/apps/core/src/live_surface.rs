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
//! provider bodies) come in two kinds this surface reads.
//!
//! *Coin metadata reads* (`coin_exact`, one JSON object; `discovery_coins`, a bare array of the
//! same coin records) name their own subject in the body: every record carries a `mint`, and
//! usually a `symbol`, a `name`, and two USD market-cap fields (`usd_market_cap` and
//! `market_cap_usd`) that this provider asserts side by side and that disagree with each other.
//! The ticker, name and one market cap are copied to the candidate as provider claims, the
//! market-cap literal byte-for-byte, with the read's own clock beside every value; the sibling
//! market-cap claim and the disagreement stay visible in the evidence rather than being averaged
//! away. A subject with no such read keeps its explicit absences: nothing here defaults.
//!
//! *`candles` windows* are a bare top-level JSON array of OHLCV rows the swap API asserted.
//! Those rows are the only prices this surface will ever render, they are copied out as the
//! provider's exact decimal strings, and three things about them are stated rather than assumed:
//!
//! 1. The window is **gap-compressed**. Intervals in which nothing traded are omitted from the
//!    array entirely, so it is a price *path* and not a grid. The bar spacing is recovered from
//!    the timestamps themselves (never from a request argument, which is not retained), and the
//!    omitted intervals are counted so the renderer can draw absence instead of flatness.
//! 2. The newest bar's age is **not** feed freshness. A quiet coin's newest bar is arbitrarily
//!    old while the read itself is seconds old, so bar clocks and acquisition clocks are kept in
//!    different fields and never collapsed into one "staleness".
//! 3. The window's coin is **never guessed**. The provider body names no coin; the mint lives in
//!    the URL path the request carried. An acquisition retained since the catalog began marking
//!    the mint segment public restates that resolved value on its attempt envelope
//!    (`resolvedPublicPath`), and bars from such a window bind to that mint with the binding
//!    rendered as `derived` evidence — resolved from the request's own durable record, not
//!    observed in the body. An older or hand-fed window whose envelope carries no resolved mint
//!    still refuses: its bars attach only when an operator states the coin, rendered as
//!    `attested` evidence, and with neither statement the window stays unrendered and counted.

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
///
/// This is a render window bound, not a knowledge bound. When a source has delivered more than
/// this at the cutoff, the derivation reads the NEWEST window — so a live head keeps tracking
/// the source's true delivered-through watermark however large the catalog grows — and states
/// the truncation in its report (`observationsTruncated`, with `observationsElided` counting
/// what fell outside) and in the rendered source coverage. The elided observations are the
/// oldest ones; falling outside this window is never a claim they did not happen: the catalog
/// retains them, and an explicit-cutoff read still reaches them.
pub const MAX_LIVE_OBSERVATIONS: usize = 512;

/// Version of this module's derivation output: everything that decides the exact bytes
/// [`derive_live_surface_with`] emits for an unchanged catalog — field selection, metadata
/// claims, ordering, and the scene-identity preimage itself.
///
/// The follow ledger pins this value on every scene it records, so a remount can tell "this
/// scene was derived by older code" (an immutable historical fact, kept byte-exact where an act
/// retained the bytes and retired where it did not) apart from "this mount's own state is
/// corrupt" (refused, loudly, as before).
///
/// **BUMP THIS WHENEVER A CODE CHANGE CAN ALTER THE DERIVED BYTES FOR AN UNCHANGED CATALOG.**
/// Failing to bump it is exactly the bug that bricked every follow state on 2026-08-23: the
/// candidate-metadata surface changed what a view contains, remount re-derived recorded scenes
/// into different bytes, and the honest identity check refused every mount forever
/// ("scene … does not re-derive to its recorded identity") while the launcher retried a failure
/// no catalog advance could fix.
///
/// History:
/// - (unrecorded): every derivation before this constant existed. A follow ledger recording no
///   version is from this era, and its unretained scenes retire at the first upgraded remount.
/// - `"2"`: candidate metadata claims (ticker, name, market cap) joined the view, and the
///   derivation version joined the scene-identity preimage.
/// - `"3"`: the observation window became newest-anchored at the cutoff. An over-cap catalog
///   previously rendered the OLDEST [`MAX_LIVE_OBSERVATIONS`] observations and took its
///   watermark from that window, so a live head froze the moment the window first filled
///   (observed live 2026-08-24: cutoff wedged at commit 356 while the keeper stood at 585).
///   Window selection decides the derived bytes, so an over-cap catalog derives different bytes
///   under this version, and the rendered coverage now states the truncation.
/// - `"4"`: the rendered candidate set became bounded and recency-ordered. Hours of discovery
///   sweeps had accumulated 1,191 subjects into one 6.4 MB view that no longer fit the bounded
///   Glass response contract (observed live 2026-08-24: every snapshot answered 500). Candidates
///   now serve newest-observation-first, at most [`MAX_RENDERED_CANDIDATES`], with the elision
///   counted in the report and stated in the view's unrendered notes — an elided candidate
///   remains observed in the catalog; falling out of render is a bound, never a denial.
pub const LIVE_SURFACE_DERIVATION_VERSION: &str = "4";

/// The most candidates one scene renders. The bounded Glass response contract is 4 MiB and a
/// candidate wire with its evidence rows runs a few KB (measured 5.4 KB average on the catalog
/// that broke: 1,191 subjects, 6.4 MB), so 300 leaves the response comfortably inside its bound
/// with headroom for hot coins' larger candle paths — while being more than any board renders
/// attentively. Elision is counted and stated, never silent.
pub const MAX_RENDERED_CANDIDATES: usize = 300;

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
    /// The derivation version that produced these bytes: [`LIVE_SURFACE_DERIVATION_VERSION`].
    pub derivation_version: &'static str,
    pub source_id: String,
    pub scene_id: String,
    pub view_digest: String,
    pub view_byte_length: u64,
    pub catalog_commit: String,
    pub delivered_through: String,
    pub rendered_at: String,
    pub observation_count: u64,
    /// True when the source held more observations at the cutoff than the render window allows.
    pub observations_truncated: bool,
    /// How many observations at or before the cutoff fell outside the render window: the oldest
    /// ones. A render bound, never an absence claim — the catalog retains every one of them.
    pub observations_elided: u64,
    pub candidate_count: u64,
    /// Candidates actually rendered into the view, after the recency bound.
    pub candidates_rendered: u64,
    /// Observed subjects elided by [`MAX_RENDERED_CANDIDATES`]; stated in the view's notes.
    pub candidates_elided: u64,
    /// Retained `coin_exact` / `discovery_coins` bodies this cutoff held and parsed.
    pub coin_metadata_observations: u64,
    /// Coin records those bodies carried (a discovery page holds many rows).
    pub coin_metadata_rows: u64,
    /// Candidates whose ticker/name/market-cap claims came from those records.
    pub coin_metadata_subjects: u64,
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
    /// A pump `candles` response is a bare OHLCV array that names no coin. An acquisition whose
    /// retained attempt envelope restates its request-resolved mint needs no statement here and
    /// is never re-labelled by one; this option covers only windows whose envelope carries no
    /// resolved mint — an older read, or a hand-fed fixture. Setting it attaches those bars to
    /// that mint and records the binding as `attested` evidence sitting next to the `observed`
    /// bars; leaving it unset leaves such a window unrendered and counted.
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
    // The NEWEST window at the cutoff, carrying the source's true delivered-through. The prefix
    // read must never serve a live surface: with an over-cap catalog its window and watermark
    // stop at the moment the window first fills, which froze the live cockpit on 2026-08-24.
    let durable = store
        .source_observations_newest_as_known(source_id, cutoff, MAX_LIVE_OBSERVATIONS)?
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
                    entry.chain_named = true;
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
    // its own is a bare array or object with no route, no mint and no interval, so a body whose
    // sibling envelope is absent is named as unrendered rather than guessed at.
    let mut windows: Vec<CandleWindow> = Vec::new();
    let mut metadata_observations = 0_usize;
    let mut metadata_rows = 0_usize;
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
        if !attempt.succeeded() {
            refuse(
                &mut unrendered,
                format!(
                    "{} read returned HTTP {}, so its body is an error document and not {}",
                    attempt.route_id,
                    attempt
                        .http_status
                        .map_or_else(|| "with no status".to_owned(), |value| value.to_string()),
                    if attempt.route_id == CANDLE_ROUTE {
                        "a price series"
                    } else {
                        "a coin record"
                    },
                ),
            );
            continue;
        }
        match attempt.route_id.as_str() {
            CANDLE_ROUTE => match parse_candle_window(&body.payload) {
                Ok(rows) => windows.push(CandleWindow {
                    observation_id: body.observation_id.to_string(),
                    source_id: body.source_id.to_string(),
                    ingested_at: body.received_at,
                    known_at: body.available_at,
                    request_mint: attempt.request_mint.clone(),
                    request_currency: attempt.request_currency.clone(),
                    rows,
                    schema_trust: schema_trust(
                        store,
                        &attempt.route_id,
                        &acquisition_id,
                        durable.through_commit_seq,
                    )?,
                }),
                Err(reason) => refuse(&mut unrendered, reason),
            },
            COIN_EXACT_ROUTE | DISCOVERY_ROUTE => {
                let trust = schema_trust(
                    store,
                    &attempt.route_id,
                    &acquisition_id,
                    durable.through_commit_seq,
                )?;
                match parse_coin_records(&attempt.route_id, &body.payload) {
                    Ok(records) => {
                        metadata_observations += 1;
                        if records.is_empty() && attempt.route_id == DISCOVERY_ROUTE {
                            refuse(
                                &mut unrendered,
                                "discovery page is an empty array; past-the-end and no-match \
                                 are the same two bytes on this route, so this names no coin \
                                 and is no evidence that none matched"
                                    .to_owned(),
                            );
                            continue;
                        }
                        metadata_rows += records.len();
                        admit_coin_records(records, body, &attempt.route_id, &trust, &mut subjects);
                    }
                    Err(reason) => refuse(&mut unrendered, reason),
                }
            }
            other => refuse(
                &mut unrendered,
                format!(
                    "retained {other} body carries neither a price series nor coin metadata \
                     this surface reads"
                ),
            ),
        }
    }

    let candles = bind_candle_windows(windows, options, &mut subjects, rendered_at)?;
    unrendered.extend(candles.notes.iter().cloned());
    resolve_metadata(&mut subjects);

    if subjects.is_empty() {
        if candles.windows_total > 0 {
            return Err(LiveSurfaceError::CandlesNameNoSubject {
                source_id: source_id.to_string(),
                windows: candles.windows_total,
                bars: candles.bars_total,
            });
        }
        return Err(LiveSurfaceError::NoRenderableSubject {
            source_id: source_id.to_string(),
            observations: durable.observations.len(),
        });
    }

    let price_series_rendered = subjects.values().any(|draft| !draft.candles.is_empty());
    let metadata_rendered = subjects.values().any(|draft| !draft.metadata.is_empty());
    let price_unit_stated = subjects.values().any(|draft| draft.price_unit_stated);
    let metadata_subjects = subjects
        .values()
        .filter(|draft| !draft.metadata.is_empty())
        .count();
    let scene_id = scene_identity(&durable);
    let mut candidates = candidate_wires(&subjects, rendered_at)?;
    // Newest observation first: the hunting order, and the order that makes the bound below
    // keep the candidates an operator would actually look at. Deterministic: recency
    // descending, absent recency last, ties broken by wire id.
    candidates.sort_by(|a, b| {
        b.last_observed_at
            .cmp(&a.last_observed_at)
            .then_with(|| a.id.cmp(&b.id))
    });
    let candidates_elided = candidates.len().saturating_sub(MAX_RENDERED_CANDIDATES);
    let candidates_rendered = candidates.len().min(MAX_RENDERED_CANDIDATES);
    if candidates_elided > 0 {
        candidates.truncate(MAX_RENDERED_CANDIDATES);
        unrendered.push(UnrenderedObservation {
            observation_id: format!("candidates:elided:{candidates_elided}"),
            locator: None,
            reason: format!(
                "{candidates_elided} additional observed subject(s) were elided by recency at \
                 the bounded response contract ({MAX_RENDERED_CANDIDATES} rendered); they remain \
                 observed in the catalog, and elision is a render bound, never a denial"
            ),
        });
    }
    let health = source_health(
        &durable,
        &watermark,
        event_clock_count,
        rendered_at,
        price_series_rendered,
        metadata_rendered,
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
    let rendered = candles.shape;
    let report = LiveSurfaceReport {
        contract: "joshi.core.live_surface",
        schema_version: 1,
        authority: "read_only_no_execution",
        derivation_version: LIVE_SURFACE_DERIVATION_VERSION,
        source_id: source_id.to_string(),
        scene_id,
        view_digest: view.digest().to_string(),
        view_byte_length: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        catalog_commit: durable.through_commit_seq.get().to_string(),
        delivered_through: durable.delivered_through.get().to_string(),
        rendered_at: rendered_at.to_string(),
        observation_count: u64::try_from(durable.observations.len()).unwrap_or(u64::MAX),
        observations_truncated: durable.truncated,
        observations_elided: durable.elided,
        candidate_count: u64::try_from(subjects.len()).unwrap_or(u64::MAX),
        candidates_rendered: u64::try_from(candidates_rendered).unwrap_or(u64::MAX),
        candidates_elided: u64::try_from(candidates_elided).unwrap_or(u64::MAX),
        coin_metadata_observations: u64::try_from(metadata_observations).unwrap_or(u64::MAX),
        coin_metadata_rows: u64::try_from(metadata_rows).unwrap_or(u64::MAX),
        coin_metadata_subjects: u64::try_from(metadata_subjects).unwrap_or(u64::MAX),
        chain_slot_low: slot_low.map(|value| value.to_string()),
        chain_slot_high: slot_high.map(|value| value.to_string()),
        unrendered_observations: unrendered,
        price_series_rendered,
        candle_windows: u64::try_from(candles.windows_total).unwrap_or(u64::MAX),
        candle_windows_unattributed: u64::try_from(candles.windows_unattributed)
            .unwrap_or(u64::MAX),
        candle_bars_rendered: rendered.bars,
        candle_spacing_seconds: rendered.spacing_seconds.map(|value| value.to_string()),
        candle_gaps: rendered.gaps,
        candle_omitted_intervals: rendered.omitted_intervals,
        candle_subject_binding: candles.binding,
        candle_newest_bar_at: rendered.newest_bar_at,
        candle_window_known_at: rendered.window_known_at,
        ceiling: match (price_series_rendered, metadata_rendered) {
            (true, true) => "provider_asserted_prices_and_coin_metadata_no_fill_no_executability",
            (true, false) if price_unit_stated => {
                "provider_asserted_price_path_request_stated_unit_no_fill_no_executability"
            }
            (true, false) => "provider_asserted_price_path_no_unit_no_fill_no_executability",
            (false, true) => "provider_asserted_coin_metadata_no_price_no_fill",
            (false, false) => "chain_identity_only_no_price_no_fill",
        },
    };
    Ok(LiveSurfaceDerivation { view, report })
}

#[derive(Default)]
#[allow(clippy::struct_excessive_bools)] // Each flag is an independent provenance fact.
struct SubjectDraft {
    evidence: Vec<EvidenceDraft>,
    slots: Vec<u64>,
    /// A retained chain frame named this mint; product reads and attestations do not set this.
    chain_named: bool,
    candles: Vec<CandleWire>,
    /// Exact, derived sentence describing the attached price path, when one is attached.
    price_note: Option<String>,
    /// At least one attached window came from a read this project's schema gate did not promote.
    schema_unpromoted: bool,
    /// At least one attached window bound through its request-resolved envelope mint.
    candles_request_resolved: bool,
    /// At least one attached window bound only through an operator's attestation.
    candles_operator_attested: bool,
    /// Every provider coin record naming this mint. `resolve_metadata` turns the newest into the
    /// rendered claim below and keeps every disagreement visible in the evidence.
    metadata: Vec<CoinMetadataClaim>,
    /// Rendered identity and market-cap claims, resolved from `metadata`. All provider claims.
    symbol: Option<String>,
    name: Option<String>,
    market_cap_usd: Option<String>,
    /// The same document asserted two USD market caps and they differ.
    market_cap_disagrees: bool,
    /// Sentence for the candidate caption naming where the metadata came from and how old it is.
    metadata_note: Option<String>,
    /// Newest bar close, rendered as a SOL price only when the request stated that denomination.
    price_sol: Option<String>,
    /// Every merged window restated the denomination the request asked for.
    price_unit_stated: bool,
    /// Move over the last five minutes of bar clock, in basis points, when derivable.
    change_5m_bps: Option<String>,
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
/// Route identity for the one-coin metadata read (`/coins-v2/{mint}`, one JSON object).
const COIN_EXACT_ROUTE: &str = "coin_exact";
/// Route identity for the discovery feed (`/coins`, a bare array of coin records).
const DISCOVERY_ROUTE: &str = "discovery_coins";

/// The exact `joshi.pump_api.acquisition.v1` fields this surface reads back.
struct PumpAttempt {
    route_id: String,
    http_status: Option<u64>,
    /// The mint the request resolved into its path, when the retained envelope restates it.
    ///
    /// The transport client writes `resolvedPublicPath` only for path segments the pinned route
    /// catalog marks as public subjects, so a value here is the request's own durable statement
    /// of which coin it asked about. Envelopes retained before that field existed have no value,
    /// and their windows keep refusing to bind without an operator statement.
    request_mint: Option<String>,
    /// The denomination the request asked the candle route for, when the envelope restates it.
    ///
    /// A candles body never states a unit for its five numeric fields; the only durable
    /// statement of the denomination is the request's own `currency` parameter, which the
    /// pinned catalog retains verbatim on the envelope (`resolvedPublicQuery`). Envelopes
    /// retained before that field existed have no value, and their prices stay unit-unstated.
    request_currency: Option<String>,
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
                    request_mint: value
                        .get("resolvedPublicPath")
                        .and_then(|resolved| resolved.get("mint"))
                        .and_then(serde_json::Value::as_str)
                        .map(ToOwned::to_owned),
                    request_currency: value
                        .get("resolvedPublicQuery")
                        .and_then(|resolved| resolved.get("currency"))
                        .and_then(serde_json::Value::as_str)
                        .map(ToOwned::to_owned),
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
// Pump coin metadata reads: `coin_exact` (one JSON object) and `discovery_coins` (a bare array
// of the same coin records).
//
// Unlike a candles window, a coin record names its own subject: the body carries `mint`. The
// ticker, name and market caps copied out here are provider claims about a mutable record, and
// the schema reviews for these routes promoted identity strings only — so every claim travels
// with the read's own clock and the gate's actual decision, never as a bare number. The two USD
// market-cap fields the provider asserts side by side (`usd_market_cap`, `market_cap_usd`)
// disagree with each other on real coins; one is rendered, named, and the other is kept visible
// in the evidence instead of being averaged into a number nobody asserted.
// ---------------------------------------------------------------------------------------------

/// One provider coin record, parsed for the exact fields this surface renders.
///
/// The market-cap fields are captured as raw JSON literals so the provider's exact decimal text
/// reaches the wire: parsing them into an `f64` would fabricate digits.
#[derive(serde::Deserialize)]
struct CoinRecordWire<'a> {
    mint: Option<String>,
    name: Option<String>,
    symbol: Option<String>,
    #[serde(borrow)]
    usd_market_cap: Option<&'a serde_json::value::RawValue>,
    #[serde(borrow)]
    market_cap_usd: Option<&'a serde_json::value::RawValue>,
}

/// One coin record's renderable claims, before the read's clocks and trust are attached.
#[derive(Debug)]
struct CoinRecordClaim {
    row_ordinal: Option<usize>,
    mint: String,
    symbol: Option<String>,
    name: Option<String>,
    /// Exact `usd_market_cap` literal, present only when it passes the Glass decimal grammar.
    usd_market_cap: Option<String>,
    /// Exact sibling `market_cap_usd` literal, kept for the disagreement statement.
    market_cap_usd: Option<String>,
    /// Honesty notes about this row: an empty ticker, a literal the contract cannot carry.
    notes: Vec<String>,
}

/// One coin record bound to the read that retained it: what the candidate resolution consumes.
struct CoinMetadataClaim {
    observation_id: String,
    source_id: String,
    route_id: String,
    row_ordinal: Option<usize>,
    ingested_at: UtcTimestamp,
    known_at: UtcTimestamp,
    symbol: Option<String>,
    name: Option<String>,
    usd_market_cap: Option<String>,
    market_cap_usd: Option<String>,
    notes: Vec<String>,
    trust_sentence: String,
    trust_promoted: bool,
}

impl CoinMetadataClaim {
    /// Wire identity prefix for this claim's evidence rows, unique per row of a discovery page.
    fn evidence_id(&self, suffix: &str) -> String {
        match self.row_ordinal {
            Some(ordinal) => format!("{}:row{ordinal}:{suffix}", self.observation_id),
            None => format!("{}:{suffix}", self.observation_id),
        }
    }

    fn provenance(&self) -> String {
        match self.row_ordinal {
            Some(ordinal) => format!("row {ordinal} of the retained {} page", self.route_id),
            None => format!("the retained {} record", self.route_id),
        }
    }
}

/// Copy one string field out of a record, turning the provider's empty string into an absence.
fn record_text(value: Option<String>, field: &str, notes: &mut Vec<String>) -> Option<String> {
    match value {
        Some(text) if text.is_empty() => {
            notes.push(format!(
                "the provider asserted an empty `{field}`, which is rendered as an absence \
                 rather than an empty label"
            ));
            None
        }
        other => other,
    }
}

/// Copy one market-cap literal out of a record byte-for-byte, or state why it cannot be carried.
fn record_decimal(
    value: Option<&serde_json::value::RawValue>,
    field: &str,
    notes: &mut Vec<String>,
) -> Option<String> {
    let literal = value?.get().to_owned();
    if exact_decimal(&literal) {
        Some(literal)
    } else {
        notes.push(format!(
            "the provider wrote `{field}` as {literal}, which is not an exact base-10 decimal \
             the Glass contract can carry, so it is not rendered as a number"
        ));
        None
    }
}

/// Parse one retained metadata body into per-row claims, refusing shapes it cannot read exactly.
fn parse_coin_records(route_id: &str, bytes: &[u8]) -> Result<Vec<CoinRecordClaim>, String> {
    let claim = |record: CoinRecordWire<'_>, ordinal: Option<usize>| {
        let mut notes = Vec::new();
        let mint = record.mint.filter(|value| !value.is_empty());
        let symbol = record_text(record.symbol, "symbol", &mut notes);
        let name = record_text(record.name, "name", &mut notes);
        let usd_market_cap = record_decimal(record.usd_market_cap, "usd_market_cap", &mut notes);
        let market_cap_usd = record_decimal(record.market_cap_usd, "market_cap_usd", &mut notes);
        mint.map(|mint| CoinRecordClaim {
            row_ordinal: ordinal,
            mint,
            symbol,
            name,
            usd_market_cap,
            market_cap_usd,
            notes,
        })
        .ok_or(ordinal)
    };
    if route_id == COIN_EXACT_ROUTE {
        let record = serde_json::from_slice::<CoinRecordWire<'_>>(bytes).map_err(|error| {
            format!("retained coin_exact body is not one JSON coin record: {error}")
        })?;
        return claim(record, None).map(|value| vec![value]).map_err(|_| {
            "retained coin_exact record carries no `mint`, so nothing durable says which coin \
             it describes"
                .to_owned()
        });
    }
    let records = serde_json::from_slice::<Vec<CoinRecordWire<'_>>>(bytes).map_err(|error| {
        format!("retained discovery_coins body is not a bare array of coin records: {error}")
    })?;
    let mut claims = Vec::with_capacity(records.len());
    let mut mintless = Vec::new();
    for (ordinal, record) in records.into_iter().enumerate() {
        match claim(record, Some(ordinal)) {
            Ok(value) => claims.push(value),
            Err(ordinal) => mintless.push(ordinal),
        }
    }
    if !mintless.is_empty() {
        return Err(format!(
            "discovery row(s) {} carry no `mint`, so nothing durable says which coins they \
             describe; the page is refused whole rather than partially trusted",
            mintless
                .iter()
                .map(|value| value.map_or_else(|| "?".to_owned(), |v| v.to_string()))
                .collect::<Vec<_>>()
                .join(", "),
        ));
    }
    Ok(claims)
}

/// Fold one retained metadata body's rows into the subject drafts, one claim per named mint.
fn admit_coin_records(
    records: Vec<CoinRecordClaim>,
    body: &DurableSourceObservation,
    route_id: &str,
    trust: &SchemaTrust,
    subjects: &mut BTreeMap<String, SubjectDraft>,
) {
    for record in records {
        let claim = CoinMetadataClaim {
            observation_id: body.observation_id.to_string(),
            source_id: body.source_id.to_string(),
            route_id: route_id.to_owned(),
            row_ordinal: record.row_ordinal,
            ingested_at: body.received_at,
            known_at: body.available_at,
            symbol: record.symbol,
            name: record.name,
            usd_market_cap: record.usd_market_cap,
            market_cap_usd: record.market_cap_usd,
            notes: record.notes,
            trust_sentence: trust.sentence(),
            trust_promoted: trust.promoted(),
        };
        let entry = subjects.entry(record.mint.clone()).or_default();
        entry.evidence.push(EvidenceDraft {
            id: claim.evidence_id("coin-record"),
            source_id: claim.source_id.clone(),
            field: "mint".to_owned(),
            evidence_class: "observed",
            observed_at: None,
            ingested_at: claim.ingested_at,
            known_at: claim.known_at,
            note: format!(
                "Named by {}: the coin record itself carries this mint, so the naming is \
                 observed in the provider's own bytes. {}{}",
                claim.provenance(),
                claim.trust_sentence,
                if claim.notes.is_empty() {
                    String::new()
                } else {
                    format!(" Also on this row: {}.", claim.notes.join("; "))
                },
            ),
        });
        entry.metadata.push(claim);
    }
}

/// Resolve each subject's retained coin records into one rendered claim, newest knowledge first.
///
/// The newest read wins the rendered ticker, name and market cap; every older read keeps its own
/// naming evidence, and a disagreement between reads is stated on the winning claim's evidence
/// rather than silently overwritten. The rendered market cap is the provider's `usd_market_cap`
/// field, named as such; the sibling `market_cap_usd` claim stays visible beside it.
#[allow(clippy::too_many_lines)] // Every rendered claim keeps its provenance sentence inline.
fn resolve_metadata(subjects: &mut BTreeMap<String, SubjectDraft>) {
    for draft in subjects.values_mut() {
        if draft.metadata.is_empty() {
            continue;
        }
        draft.metadata.sort_by(|left, right| {
            left.known_at
                .as_datetime()
                .cmp(&right.known_at.as_datetime())
                .then_with(|| left.observation_id.cmp(&right.observation_id))
                .then_with(|| left.row_ordinal.cmp(&right.row_ordinal))
        });
        let Some(winner) = draft.metadata.last() else {
            continue;
        };
        let disagreements = draft
            .metadata
            .iter()
            .rev()
            .skip(1)
            .filter(|earlier| {
                earlier.symbol != winner.symbol
                    || earlier.name != winner.name
                    || earlier.usd_market_cap != winner.usd_market_cap
            })
            .count();
        draft.symbol = winner.symbol.clone();
        draft.name = winner.name.clone();
        draft.market_cap_usd = winner.usd_market_cap.clone();
        if draft.metadata.iter().any(|claim| !claim.trust_promoted) {
            draft.schema_unpromoted = true;
        }
        let mut identity_note = format!(
            "Ticker, name and market cap are provider claims copied from {}, read at {}.",
            winner.provenance(),
            winner.known_at,
        );
        if disagreements > 0 {
            let _ = write!(
                identity_note,
                " {disagreements} earlier retained read(s) asserted different values; the \
                 newest read is rendered and the earlier ones remain in the evidence.",
            );
        }
        if let (Some(rendered), Some(sibling)) = (
            winner.usd_market_cap.as_deref(),
            winner.market_cap_usd.as_deref(),
        ) {
            if rendered != sibling {
                draft.market_cap_disagrees = true;
            }
            let delta = change_basis_points(sibling, rendered).map_or_else(
                || "a difference this surface's exact arithmetic cannot state".to_owned(),
                |bps| format!("{bps} basis point(s) apart"),
            );
            let _ = write!(
                identity_note,
                " The provider asserts two USD market caps in the same document: \
                 usd_market_cap={rendered} (rendered) and market_cap_usd={sibling} \
                 ({delta}); neither is averaged and the rendered field is named.",
            );
        }
        draft.metadata_note = Some(identity_note);
        // Evidence rows for the rendered fields, one per field, carrying the read's own clock so
        // the age of every number is part of what reaches the screen.
        let field_rows: [(&str, Option<&String>, String); 3] = [
            (
                "symbol",
                winner.symbol.as_ref(),
                format!(
                    "Provider-asserted ticker from {}. {}",
                    winner.provenance(),
                    winner.trust_sentence,
                ),
            ),
            (
                "name",
                winner.name.as_ref(),
                format!(
                    "Provider-asserted display name from {}. {}",
                    winner.provenance(),
                    winner.trust_sentence,
                ),
            ),
            (
                "metrics.marketCapUsd",
                winner.usd_market_cap.as_ref(),
                format!(
                    "The provider's own `usd_market_cap` claim from {}, copied byte-for-byte. \
                     {} The same document asserts a sibling `market_cap_usd` of {}; the two \
                     are the provider's claims, not valuations this project computed, and the \
                     schema review for this route promoted identity strings only — mutable \
                     market state like this number passed no review.",
                    winner.provenance(),
                    winner.trust_sentence,
                    winner
                        .market_cap_usd
                        .as_deref()
                        .unwrap_or("(absent from the record)"),
                ),
            ),
        ];
        for (field, value, note) in field_rows {
            if value.is_none() {
                continue;
            }
            draft.evidence.push(EvidenceDraft {
                id: winner.evidence_id(&format!("claim-{}", field.replace('.', "-"))),
                source_id: winner.source_id.clone(),
                field: field.to_owned(),
                evidence_class: "observed",
                observed_at: None,
                ingested_at: winner.ingested_at,
                known_at: winner.known_at,
                note,
            });
        }
    }
}

/// An exact decimal string as an integer mantissa and its fractional scale.
fn decimal_mantissa(value: &str) -> Option<(i128, u32)> {
    if !exact_decimal(value) {
        return None;
    }
    let negative = value.starts_with('-');
    let unsigned = value.strip_prefix('-').unwrap_or(value);
    let (integer, fraction) = unsigned
        .split_once('.')
        .map_or((unsigned, ""), |(left, right)| (left, right));
    let mantissa = format!("{integer}{fraction}").parse::<i128>().ok()?;
    Some((
        if negative { -mantissa } else { mantissa },
        u32::try_from(fraction.len()).ok()?,
    ))
}

/// `(latest - reference) / reference` in basis points, exactly, rounded half away from zero.
///
/// Integer arithmetic over the exact decimal strings: no float ever touches a provider number.
/// `None` when either literal cannot be read, the reference is not positive, or the exact ratio
/// overflows 128-bit arithmetic — a refusal, never a rounding of a different kind.
fn change_basis_points(latest: &str, reference: &str) -> Option<i128> {
    let (latest_mantissa, latest_scale) = decimal_mantissa(latest)?;
    let (reference_mantissa, reference_scale) = decimal_mantissa(reference)?;
    let scale = latest_scale.max(reference_scale);
    let latest_scaled = latest_mantissa.checked_mul(10_i128.checked_pow(scale - latest_scale)?)?;
    let reference_scaled =
        reference_mantissa.checked_mul(10_i128.checked_pow(scale - reference_scale)?)?;
    if reference_scaled <= 0 {
        return None;
    }
    let numerator = latest_scaled
        .checked_sub(reference_scaled)?
        .checked_mul(10_000)?;
    let adjust = if numerator >= 0 {
        reference_scaled
    } else {
        -reference_scaled
    };
    Some(numerator.checked_mul(2)?.checked_add(adjust)? / (reference_scaled.checked_mul(2)?))
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
    /// Mint the acquisition's retained attempt envelope restates as request-resolved, if any.
    request_mint: Option<String>,
    /// Denomination the request asked for, when the retained envelope restates its `currency`.
    request_currency: Option<String>,
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
    /// Which window's observation each merged bar came out of, keyed by bar clock.
    origins: BTreeMap<u64, String>,
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
        // Two windows whose retained envelopes state different requested denominations are two
        // different series, whatever their spacing: interleaving a SOL path with a USD path
        // would invent numbers neither response asserts.
        let mut currencies: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for window in &windows {
            if let Some(currency) = &window.request_currency {
                currencies
                    .entry(currency.clone())
                    .or_default()
                    .push(window.observation_id.clone());
            }
        }
        if currencies.len() > 1 {
            let described = currencies
                .iter()
                .map(|(currency, observations)| {
                    format!("{currency} from {}", observations.join(", "))
                })
                .collect::<Vec<_>>()
                .join("; ");
            return Err(format!(
                "this catalog holds candle windows requested in {} different denominations \
                 ({described}). They are different series, not one path, so nothing is merged; \
                 narrow the catalog to one currency",
                currencies.len(),
            ));
        }
        let mut rows: BTreeMap<u64, CandleRow> = BTreeMap::new();
        let mut origins: BTreeMap<u64, String> = BTreeMap::new();
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
                origins.insert(row.time_unix, window.observation_id.clone());
                known.insert(row.time_unix, window.known_at);
            }
        }
        Ok(Self {
            windows,
            rows,
            origins,
            revisions,
        })
    }

    /// The denomination of the merged path, when every window's envelope restates the same one.
    ///
    /// `None` means unstated, not "SOL by habit": at least one merged window predates the
    /// envelope restating its `currency`, so nothing durable says what these numbers denominate.
    fn stated_currency(&self) -> Option<&str> {
        let mut stated = None;
        for window in &self.windows {
            stated = Some(window.request_currency.as_deref()?);
        }
        stated
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

    /// Every window this surface holds but could not attach to a coin, with the true reason
    /// per window: a coin nothing durable names, or a series too short for the frozen contract.
    fn unattributed_notes(&self) -> Vec<UnrenderedObservation> {
        self.windows
            .iter()
            .map(|window| UnrenderedObservation {
                observation_id: window.observation_id.clone(),
                locator: None,
                reason: match window.request_mint.as_deref() {
                    Some(mint) => format!(
                        "{} retained candle bar(s) resolved to {mint} from the request path, but \
                         the merged series holds fewer than two bars, and a one-sample series \
                         implies an interval it does not have, so the frozen contract refuses to \
                         draw it",
                        window.rows.len(),
                    ),
                    None => format!(
                        "{} retained candle bar(s), but a pump candles response names no coin and \
                         this acquisition's retained envelope carries no request-resolved mint — \
                         an older read, or a hand-fed fixture. Nothing here says which coin these \
                         bars are; state it with --candles-subject <MINT> if you know it",
                        window.rows.len(),
                    ),
                },
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

    /// Attach the merged path to one mint, recording per window how that binding was established:
    /// the request's own resolved path restated on the retained envelope (`derived`), or the
    /// operator's statement (`attested`). Which one applies is a fact about each window, so one
    /// merged series can carry both.
    ///
    /// Returns whether bars actually reached the scene.
    fn attach(
        &self,
        mint: &str,
        subjects: &mut BTreeMap<String, SubjectDraft>,
        rendered_at: UtcTimestamp,
    ) -> bool {
        // The frozen contract refuses a one-sample series, because one bar implies an interval it
        // does not have. That bar is still real, so it is named in prose instead of drawn.
        if self.rows.len() < 2 {
            return false;
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
        self.derive_price_metrics(entry, rendered_at);
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
            if window.request_mint.is_some() {
                entry.candles_request_resolved = true;
            } else {
                entry.candles_operator_attested = true;
            }
            entry.evidence.push(window.subject_binding_evidence(mint));
        }
        true
    }

    fn window_by_observation(&self, observation_id: &str) -> Option<&CandleWindow> {
        self.windows
            .iter()
            .find(|window| window.observation_id == observation_id)
    }

    /// Derive the two numbers the frozen metric block can carry from an attached path — the
    /// newest close as a SOL price, and the move over the last five minutes of bar clock — and
    /// refuse each one out loud when its basis is not actually retained.
    ///
    /// Every refusal is appended to the price note so the absence on screen has its reason next
    /// to the bars that are on screen.
    #[allow(clippy::too_many_lines)] // Each derived number keeps its basis and refusals inline.
    fn derive_price_metrics(&self, entry: &mut SubjectDraft, rendered_at: UtcTimestamp) {
        const FIVE_MINUTES_SECONDS: u64 = 300;
        let Some((&newest_clock, newest_row)) = self.rows.iter().next_back() else {
            return;
        };
        let known_at = self.newest_known_at().unwrap_or(rendered_at);
        let currency = self.stated_currency().map(ToOwned::to_owned);
        entry.price_unit_stated = currency.is_some();
        let newest_origin = self.origins.get(&newest_clock).cloned().unwrap_or_default();
        let origin_window = self.window_by_observation(&newest_origin);
        let mut refusals = Vec::new();

        match currency.as_deref() {
            Some(stated) if stated.eq_ignore_ascii_case("sol") => {
                entry.price_sol = Some(newest_row.close.clone());
                entry.evidence.push(EvidenceDraft {
                    id: format!("{newest_origin}:price-close"),
                    source_id: origin_window
                        .map(|window| window.source_id.clone())
                        .unwrap_or_default(),
                    field: "metrics.priceSol".to_owned(),
                    evidence_class: "derived",
                    observed_at: None,
                    ingested_at: origin_window.map_or(rendered_at, |window| window.ingested_at),
                    known_at,
                    note: format!(
                        "The newest retained bar's close, {} at {}. The request that retained \
                         this window asked for currency={stated} and its envelope restates that; \
                         the provider body itself states no unit. A provider-asserted trade-path \
                         close: not a quote, not a fill, not executability — and the bar clock \
                         is a market clock, so on a quiet coin this number is older than the \
                         read that carried it (read known at {known_at}).",
                        newest_row.close,
                        unix_instant(newest_clock),
                    ),
                });
            }
            Some(stated) => refusals.push(format!(
                "The newest close is {} at {}, requested in {stated}; the frozen contract's \
                 price field carries SOL only, so it stays empty rather than relabelling a \
                 {stated} number.",
                newest_row.close,
                unix_instant(newest_clock),
            )),
            None => refusals.push(format!(
                "The newest close is {} at {}, but no merged window's envelope restates a \
                 requested denomination — the request sent no `currency`, predates the envelope \
                 restating it, or is a hand-fed fixture — so no SOL price is claimed: a number \
                 without its unit is not rendered as one.",
                newest_row.close,
                unix_instant(newest_clock),
            )),
        }

        // The five-minute move: newest close against the latest close at least 300 bar-clock
        // seconds earlier. The series is gap-compressed, so the reference bar's true distance is
        // measured and stated, never assumed to be exactly five minutes.
        let reference = self
            .rows
            .range(..=newest_clock.saturating_sub(FIVE_MINUTES_SECONDS))
            .next_back();
        match reference {
            None => refusals.push(format!(
                "No five-minute move is derivable: the retained path reaches only {}s behind \
                 the newest bar.",
                newest_clock.saturating_sub(*self.rows.keys().next().unwrap_or(&newest_clock)),
            )),
            Some((&reference_clock, reference_row)) => {
                let reference_origin = self
                    .origins
                    .get(&reference_clock)
                    .cloned()
                    .unwrap_or_default();
                // A basis-point ratio is unit-free only when both bars share one denomination:
                // guaranteed within one window (one response is one series), and across windows
                // only when every envelope states the same requested currency.
                let same_series = reference_origin == newest_origin || currency.is_some();
                let span = newest_clock - reference_clock;
                if same_series {
                    match change_basis_points(&newest_row.close, &reference_row.close) {
                        Some(bps) => {
                            entry.change_5m_bps = Some(bps.to_string());
                            entry.evidence.push(EvidenceDraft {
                                id: format!("{newest_origin}:change-5m"),
                                source_id: origin_window
                                    .map(|window| window.source_id.clone())
                                    .unwrap_or_default(),
                                field: "metrics.change5mBps".to_owned(),
                                evidence_class: "derived",
                                observed_at: None,
                                ingested_at: origin_window
                                    .map_or(rendered_at, |window| window.ingested_at),
                                known_at,
                                note: format!(
                                    "Derived: close {} of the newest bar at {} against close {} \
                                     of the latest bar at least 300s earlier, at {} — {span}s \
                                     before, measured on a gap-compressed path, so the basis is \
                                     the stated span and never an assumed grid. Rounded to the \
                                     nearest basis point; both closes are provider assertions \
                                     from the retained window(s), and a ratio of two same-series \
                                     closes carries no currency.",
                                    newest_row.close,
                                    unix_instant(newest_clock),
                                    reference_row.close,
                                    unix_instant(reference_clock),
                                ),
                            });
                        }
                        None => refusals.push(
                            "No five-minute move is derivable: the exact ratio of the two \
                             closes cannot be computed in this surface's 128-bit integer \
                             arithmetic, and approximating it would fabricate digits."
                                .to_owned(),
                        ),
                    }
                } else {
                    refusals.push(format!(
                        "No five-minute move is derivable: the two bars it needs come from \
                         different retained windows ({span}s apart) and not every envelope \
                         restates its requested denomination, so nothing durable says they are \
                         one series.",
                    ));
                }
            }
        }

        if !refusals.is_empty() {
            let appended = refusals.join(" ");
            entry.price_note = Some(match entry.price_note.take() {
                Some(existing) => format!("{existing} {appended}"),
                None => appended,
            });
        }
    }
}

impl CandleWindow {
    /// The evidence row stating how this window's bars reached `mint`: derived from the
    /// request's own durable record, or attested by an operator. Never observed — the provider
    /// body names no coin either way.
    fn subject_binding_evidence(&self, mint: &str) -> EvidenceDraft {
        if self.request_mint.is_some() {
            EvidenceDraft {
                id: format!("{}:request-resolved-subject", self.observation_id),
                source_id: self.source_id.clone(),
                field: "mint".to_owned(),
                evidence_class: "derived",
                observed_at: None,
                ingested_at: self.ingested_at,
                known_at: self.known_at,
                note: format!(
                    "The acquisition that retained this window resolved {mint} into its request \
                     path and its retained attempt envelope restates that resolved segment, \
                     which the pinned route catalog marks as a public subject. The provider body \
                     itself names no coin, so this binding is derived from the request's own \
                     durable record — an operator-independent public fact — not observed in the \
                     body and not attested by anyone.",
                ),
            }
        } else {
            EvidenceDraft {
                id: format!("{}:operator-attested-subject", self.observation_id),
                source_id: self.source_id.clone(),
                field: "mint".to_owned(),
                evidence_class: "attested",
                observed_at: None,
                ingested_at: self.ingested_at,
                known_at: self.known_at,
                note: format!(
                    "An operator stated that this coin-anonymous candle window belongs to \
                     {mint}. The retained bytes do not say so: a candles response carries no \
                     mint, and this acquisition's envelope keeps only the `{{mint}}` path \
                     template plus a one-way request fingerprint. This binding is attested, not \
                     observed.",
                ),
            }
        }
    }
}

/// How every retained candle window in one cutoff did or did not reach a coin.
struct CandleBindingOutcome {
    /// Retained windows, attached or not.
    windows_total: usize,
    /// Windows whose bars reached no candidate.
    windows_unattributed: usize,
    /// Merged bars across every group, rendered or not, for the refusal message.
    bars_total: usize,
    /// One label describing how the rendered bars reached their mints.
    binding: &'static str,
    /// Aggregated facts about the rendered paths, or explicit absences.
    shape: RenderedShape,
    /// One note per window that stayed unrendered, with the true reason.
    notes: Vec<UnrenderedObservation>,
}

/// Bind retained candle windows to coins without guessing.
///
/// Windows are grouped by the mint their own acquisition resolved into its request path; each
/// group merges and attaches to that mint. Windows whose envelope restates no mint join the
/// operator-stated group when `--candles-subject` was given — including a stated mint that also
/// has request-resolved windows, which merges both onto one subject with each window keeping its
/// own binding evidence — and otherwise stay unrendered and counted.
fn bind_candle_windows(
    windows: Vec<CandleWindow>,
    options: &LiveSurfaceOptions,
    subjects: &mut BTreeMap<String, SubjectDraft>,
    rendered_at: UtcTimestamp,
) -> Result<CandleBindingOutcome, LiveSurfaceError> {
    let windows_total = windows.len();
    let mut groups: BTreeMap<String, Vec<CandleWindow>> = BTreeMap::new();
    let mut anonymous: Vec<CandleWindow> = Vec::new();
    for window in windows {
        match window.request_mint.clone() {
            Some(mint) => groups.entry(mint).or_default().push(window),
            None => anonymous.push(window),
        }
    }
    let mut notes = Vec::new();
    if let Some(stated) = options.attested_candle_subject.as_deref() {
        groups
            .entry(stated.to_owned())
            .or_default()
            .append(&mut anonymous);
    } else {
        for window in &anonymous {
            notes.push(UnrenderedObservation {
                observation_id: window.observation_id.clone(),
                locator: None,
                reason: format!(
                    "{} retained candle bar(s), but a pump candles response names no coin and \
                     this acquisition's retained envelope carries no request-resolved mint — an \
                     older read, or a hand-fed fixture. Nothing here says which coin these bars \
                     are; state it with --candles-subject <MINT> if you know it",
                    window.rows.len(),
                ),
            });
        }
    }
    let mut windows_unattributed = anonymous.len();
    let mut bars_total = 0_usize;
    let mut bound_request = false;
    let mut bound_operator = false;
    let mut shapes = Vec::new();
    for (mint, group) in groups {
        let series = CandleSeries::merge(group).map_err(LiveSurfaceError::CandleWindows)?;
        bars_total += series.bar_count();
        if series.attach(&mint, subjects, rendered_at) {
            bound_request |= series
                .windows
                .iter()
                .any(|window| window.request_mint.is_some());
            bound_operator |= series
                .windows
                .iter()
                .any(|window| window.request_mint.is_none());
            shapes.push(series.rendered_shape(true));
        } else {
            windows_unattributed += series.window_count();
            notes.extend(series.unattributed_notes());
        }
    }
    let binding = match (windows_total == 0, bound_request, bound_operator) {
        (true, _, _) => "no_candle_window_retained",
        (false, true, true) => "request_path_resolved_and_operator_attested",
        (false, true, false) => "request_path_resolved",
        (false, false, true) => "operator_attested_not_witnessed",
        (false, false, false) => "unattributed_bytes_name_no_coin",
    };
    Ok(CandleBindingOutcome {
        windows_total,
        windows_unattributed,
        bars_total,
        binding,
        shape: aggregate_shapes(shapes),
        notes,
    })
}

/// Fold the rendered shape of every attached series into the report's single set of fields.
///
/// Sums are honest sums; the spacing survives only when every rendered path shares one, because
/// two coins on two grids have no single spacing and inventing one would be a claim about
/// neither. Newest clocks take the latest across paths.
fn aggregate_shapes(shapes: Vec<RenderedShape>) -> RenderedShape {
    let mut folded = RenderedShape {
        bars: 0,
        spacing_seconds: None,
        gaps: 0,
        omitted_intervals: 0,
        newest_bar_at: None,
        window_known_at: None,
    };
    let mut spacings: BTreeSet<u64> = BTreeSet::new();
    for shape in shapes {
        folded.bars += shape.bars;
        folded.gaps += shape.gaps;
        folded.omitted_intervals += shape.omitted_intervals;
        spacings.extend(shape.spacing_seconds);
        if let Some(value) = shape.newest_bar_at
            && folded
                .newest_bar_at
                .as_ref()
                .is_none_or(|held| *held < value)
        {
            folded.newest_bar_at = Some(value);
        }
        if let Some(value) = shape.window_known_at
            && folded
                .window_known_at
                .as_ref()
                .is_none_or(|held| *held < value)
        {
            folded.window_known_at = Some(value);
        }
    }
    if spacings.len() == 1 {
        folded.spacing_seconds = spacings.into_iter().next();
    }
    folded
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

#[allow(clippy::too_many_lines)] // Every derived field stays visible next to the row it came from.
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
        let absence = match (draft.candles.is_empty(), draft.metadata.is_empty()) {
            (true, true) => Some(
                "No price series and no coin metadata are attached to this mint, so no price, \
                 ticker, size, market cap or fill is claimed for it.",
            ),
            (true, false) => Some(
                "No price series is attached to this mint, so no price or fill is claimed \
                 for it.",
            ),
            (false, _) => None,
        };
        let caption = [
            draft.price_note.as_deref(),
            absence,
            draft.metadata_note.as_deref(),
        ]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>()
        .join(" ");
        let mut tags = Vec::new();
        if draft.chain_named {
            tags.push("chain_observed".to_owned());
        }
        if draft.symbol.is_none() {
            tags.push("ticker_unobserved".to_owned());
        }
        if draft.candles.is_empty() {
            tags.push("no_price_observed".to_owned());
        } else {
            tags.push("gap_compressed_path".to_owned());
            tags.push("provider_asserted_price".to_owned());
            tags.push(if draft.price_unit_stated {
                "unit_request_stated".to_owned()
            } else {
                "unit_unstated".to_owned()
            });
            if draft.candles_request_resolved {
                tags.push("subject_request_resolved".to_owned());
            }
            if draft.candles_operator_attested {
                tags.push("subject_operator_attested".to_owned());
            }
        }
        if !draft.metadata.is_empty() {
            tags.push("coin_metadata_observed".to_owned());
        }
        if draft.market_cap_usd.is_some() {
            tags.push("market_cap_from_usd_market_cap".to_owned());
        }
        if draft.market_cap_disagrees {
            tags.push("market_cap_fields_disagree".to_owned());
        }
        if draft.schema_unpromoted {
            tags.push("schema_unpromoted".to_owned());
        }
        tags.sort();
        candidates.push(CandidateWire {
            id: mint.clone(),
            mint: mint.clone(),
            symbol: draft.symbol.clone(),
            name: draft.name.clone(),
            board: "watch".to_owned(),
            lifecycle: "unknown".to_owned(),
            first_known_at: first.to_string(),
            last_observed_at: last.to_string(),
            rank: (u64::try_from(ordinal).unwrap_or(u64::MAX).saturating_add(1)).to_string(),
            metrics: CandidateMetricsWire {
                price_sol: draft.price_sol.clone(),
                market_cap_usd: draft.market_cap_usd.clone(),
                change_5m_bps: draft.change_5m_bps.clone(),
                age_seconds: u64::try_from(age_seconds)
                    .ok()
                    .map(|value| value.to_string()),
                activity: "unknown".to_owned(),
                quote_size_sol: None,
                executable_exit_sol: None,
            },
            attention_reason: format!(
                "Carries {} evidence row{}{slot_text}. Rows are ordered by mint identity; this is \
                 not an attention ranking. {caption}",
                evidence.len(),
                if evidence.len() == 1 { "" } else { "s" },
            ),
            social_summary: "No social source was acquired in this cut.".to_owned(),
            tags,
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
    metadata_rendered: bool,
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
        coverage: {
            let mut coverage = format!(
                "{total} retained observation{} across commits {low} through {}, delivered \
                 through commit {}, rendered at commit {}. {event_clock_count} carr{} a provider \
                 event clock.",
                if total == 1 { "" } else { "s" },
                durable.delivered_through.get(),
                watermark.delivered_through().get(),
                durable.through_commit_seq.get(),
                if event_clock_count == 1 { "ies" } else { "y" },
            );
            if durable.elided > 0 {
                // A truncated window is a render bound, and it is stated: the observations that
                // did not fit are the oldest, they are retained by the catalog, and nothing about
                // this sentence is a claim they did not happen.
                let _ = write!(
                    coverage,
                    " This is the newest render window the surface draws; {} older retained \
                     observation{} at this cutoff did not fit and remain in the catalog, not \
                     absent.",
                    durable.elided,
                    if durable.elided == 1 { "" } else { "s" },
                );
            }
            coverage
        },
        note: format!(
            "{quality_notes} observation{} recorded an exact adapter quality note. Provider bytes \
             are retained without an assertion layer beneath them. {} Coverage outside these \
             commits is unknown rather than empty. The ingest clock above is this source's \
             freshness; a bar clock inside a candidate is a market clock and is not. Rendered at \
             {rendered_at}.",
            if quality_notes == 1 { "" } else { "s" },
            match (price_series_rendered, metadata_rendered) {
                (true, true) => {
                    "One or more candidates carry an OHLCV path the provider asserted, copied \
                     out verbatim: those bars are provider claims about price, not fills, not \
                     quotes, not executability, and the body states no unit for them — where a \
                     unit is stated, it is the request's own retained denomination. Tickers, \
                     names and market caps are likewise provider-asserted coin metadata copied \
                     from retained product reads: claims about a mutable record, not valuations \
                     this project computed. No size, fill or executability is asserted."
                }
                (true, false) => {
                    "One or more candidates carry an OHLCV path the provider asserted, copied \
                     out verbatim: those bars are provider claims about price, not fills, not \
                     quotes, not executability, and the provider states no unit for them. \
                     Nothing else here is a market claim: no size, market cap or fill is \
                     asserted."
                }
                (false, true) => {
                    "One or more candidates carry provider-asserted coin metadata (ticker, \
                     name, market cap) copied from retained product reads: those are the \
                     provider's claims about a mutable record, not valuations this project \
                     computed. No price series, size, fill or executability is asserted."
                }
                (false, false) => {
                    "This surface names identities and clocks only: no price, size, market cap \
                     or fill is claimed."
                }
            },
        ),
    }
}

/// Deterministic scene identity: the same catalog contents at the same derivation version always
/// name the same scene, and two derivation versions never name the same scene even over identical
/// evidence — so an upgraded remount can mint a fresh scene at an unchanged watermark without
/// colliding with the retired scene it supersedes.
fn scene_identity(durable: &DurableSourceObservations) -> String {
    scene_identity_under(LIVE_SURFACE_DERIVATION_VERSION, durable)
}

fn scene_identity_under(derivation_version: &str, durable: &DurableSourceObservations) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.core.live_surface.scene.v2\0");
    hasher.update(derivation_version.as_bytes());
    hasher.update(b"\0");
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
         names no coin, and none of these acquisitions' retained envelopes restates a \
         request-resolved mint — an acquisition from before the catalog marked the mint path \
         segment public, or a hand-fed fixture — so this catalog does not say which coin these \
         bars are. Re-run with --candles-subject <MINT> to state it yourself; it will be \
         rendered as attested, not observed"
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
    // Null is the honest value when no retained read names a ticker or display name: the frozen
    // contract renders the mint then, and a placeholder string would be indistinguishable from a
    // real short ticker.
    symbol: Option<String>,
    name: Option<String>,
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
        CandleRow, DecodedObservation, LIVE_SURFACE_DERIVATION_VERSION, LiveSurfaceOptions,
        MAX_LIVE_OBSERVATIONS, change_basis_points, decode_observation, derive_live_surface_with,
        gap_shape, parse_candle_window, parse_coin_records, scene_identity_under, source_identity,
        spacing_of,
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
    /// One verbatim `coin_exact` acquisition envelope retained 2026-08-21 against
    /// `https://frontend-api-v3.pump.fun/coins-v2/{mint}` for a real mainnet coin. Its body is
    /// one flat JSON coin record that names its own mint, ticker and name, and asserts two USD
    /// market caps that disagree by about 4.6%.
    const COIN_EXACT_ACQUISITION: &str =
        include_str!("../../../crates/joshi-pump-api/fixtures/coin_exact_live_acquisition_v1.json");
    const COIN_EXACT_REVIEW: &str =
        include_str!("../../../crates/joshi-pump-api/fixtures/schema_review_coin_exact_v1.json");
    /// One verbatim `discovery_coins` fetch outcome retained 2026-08-22: three coin records in a
    /// bare top-level array, each naming its own mint.
    const DISCOVERY_OUTCOME: &str = include_str!(
        "../../../crates/joshi-pump-api/fixtures/discovery_coins_live_outcome_v1.json"
    );
    const DISCOVERY_REVIEW: &str = include_str!(
        "../../../crates/joshi-pump-api/fixtures/schema_review_discovery_coins_v1.json"
    );
    const COMMITTED_AT: &str = "2026-08-22T01:30:00.000000Z";
    /// The mint the operator actually asked the swap API for. The retained bytes do not say it.
    const SUBJECT: &str = "HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump";
    /// The mint the retained `coin_exact` record names in its own body.
    const COIN_EXACT_MINT: &str = "14m1ketwD6ikdjxtYnm3jtxVzPD9wXhnu5wYGMTWpump";
    /// The first row of the retained discovery page.
    const DISCOVERY_MINT: &str = "8YL3TBEhoNQmrEBZTD48ZoJAFHz4YiZKDSngLbvSpump";

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
        store_with_outcome(root, CANDLES_OUTCOME.trim_end().as_bytes(), review_bytes)
    }

    /// The same verbatim read, with the attempt envelope restating the request-resolved mint —
    /// exactly what every acquisition made since the pinned catalog marked the mint path segment
    /// public carries. The provider body bytes are untouched.
    fn resolved_outcome() -> Vec<u8> {
        let mut value: serde_json::Value =
            serde_json::from_str(CANDLES_OUTCOME.trim_end()).expect("fixture outcome parses");
        value["attempts"][0]["resolvedPublicPath"] = serde_json::json!({ "mint": SUBJECT });
        serde_json::to_vec(&value).expect("patched outcome serializes")
    }

    fn store_with_outcome(
        root: &Path,
        outcome_bytes: &[u8],
        review_bytes: Option<&[u8]>,
    ) -> SqliteStore {
        let mut store =
            SqliteStore::open(config(root), StoreMode::SingleWriter).expect("open store");
        store.migrate(committed_at()).expect("migrate");
        commit_outcome(
            &mut store,
            outcome_bytes,
            review_bytes,
            "batch:pump-tap:candles",
            1,
        );
        store
    }

    /// Admit one more fetch outcome into an already-open store, exactly as the tap does.
    fn commit_outcome(
        store: &mut SqliteStore,
        outcome_bytes: &[u8],
        review_bytes: Option<&[u8]>,
        durable_batch_id: &str,
        committed_monotonic_ns: u64,
    ) {
        commit_outcome_at(
            store,
            outcome_bytes,
            review_bytes,
            durable_batch_id,
            committed_monotonic_ns,
            COMMITTED_AT,
        );
    }

    /// The same admission at a stated commit instant, for fixtures received on other clocks.
    fn commit_outcome_at(
        store: &mut SqliteStore,
        outcome_bytes: &[u8],
        review_bytes: Option<&[u8]>,
        durable_batch_id: &str,
        committed_monotonic_ns: u64,
        committed_at: &str,
    ) {
        let instant: UtcTimestamp = committed_at.parse().expect("canonical instant");
        let prepared = prepare_direct_product_read(&ProductReadInput {
            outcome_bytes,
            review_bytes,
            authenticated_path: AuthenticatedPathDecision::NotPerformed,
            session_reason_code: "no_documented_authenticated_get_read_route_for_present_credential",
            session_detail: "undocumented public product route read with no session provider",
            durable_batch_id,
            committed_at: instant,
            committed_monotonic_ns,
            decided_at: committed_at,
        })
        .expect("prepared product read");
        let receipt = prepared
            .prepared
            .admission_batch()
            .commit(store)
            .expect("commit");
        close_receipt(&prepared.prepared, &receipt).expect("receipt closure");
    }

    /// Wrap one retained acquisition envelope into the fetch-outcome shape the adapter admits.
    fn outcome_of(attempt: &serde_json::Value) -> Vec<u8> {
        serde_json::to_vec(&serde_json::json!({
            "contract": "joshi.pump_api.fetch_outcome.v1",
            "requestGroupId": attempt["requestGroupId"],
            "attempts": [attempt],
            "coverageWindows": [],
            "coverageGaps": [],
            "completed": true,
        }))
        .expect("outcome serializes")
    }

    /// The verbatim `coin_exact` read as a committable outcome, optionally re-addressed to another
    /// mint. The mint patch is a byte-exact text substitution on the provider body (never a JSON
    /// re-serialization, which would rewrite the provider's float literals), with the body's
    /// length and digest recomputed so admission still closes.
    fn coin_exact_outcome(mint_override: Option<&str>) -> Vec<u8> {
        use base64::{Engine as _, engine::general_purpose::STANDARD};
        use sha2::Digest as _;
        use std::fmt::Write as _;
        let mut attempt: serde_json::Value =
            serde_json::from_str(COIN_EXACT_ACQUISITION.trim_end()).expect("fixture parses");
        if let Some(mint) = mint_override {
            let encoded = attempt["body"]["bytesBase64"]
                .as_str()
                .expect("fixture body")
                .to_owned();
            let body = STANDARD.decode(encoded).expect("fixture base64");
            let text = String::from_utf8(body).expect("fixture body is UTF-8");
            let patched = text.replace(COIN_EXACT_MINT, mint);
            let digest = sha2::Sha256::digest(patched.as_bytes());
            let hex = digest.iter().fold(String::new(), |mut out, byte| {
                let _ = write!(out, "{byte:02x}");
                out
            });
            attempt["body"]["bytesBase64"] =
                serde_json::Value::String(STANDARD.encode(patched.as_bytes()));
            attempt["body"]["byteLength"] = serde_json::Value::String(patched.len().to_string());
            attempt["body"]["blobId"] = serde_json::Value::String(format!("sha256:{hex}"));
        }
        outcome_of(&attempt)
    }

    /// The verbatim candles read with its envelope restating both the request-resolved mint and
    /// the requested denomination — what every acquisition made by the current tap carries.
    fn sol_candles_outcome() -> Vec<u8> {
        let mut value: serde_json::Value =
            serde_json::from_str(CANDLES_OUTCOME.trim_end()).expect("fixture outcome parses");
        value["attempts"][0]["resolvedPublicPath"] = serde_json::json!({ "mint": SUBJECT });
        value["attempts"][0]["resolvedPublicQuery"] =
            serde_json::json!({ "currency": "SOL", "interval": "1s", "limit": "200" });
        serde_json::to_vec(&value).expect("patched outcome serializes")
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
        // No retained read names a ticker or a name for this mint, so the wire says null and
        // never a placeholder that could be misread as a real short ticker.
        assert!(candidate["symbol"].is_null());
        assert!(candidate["name"].is_null());
        assert!(candidate["metrics"]["marketCapUsd"].is_null());
        // This fixture predates the envelope restating its requested `currency`, so the newest
        // close stays out of the SOL-labelled price field and the caption says why.
        assert!(candidate["metrics"]["priceSol"].is_null());
        let reason = candidate["attentionReason"].as_str().unwrap_or_default();
        assert!(reason.contains("no SOL price is claimed"), "{reason}");
        // A five-minute move IS derivable here: both closes come out of one window, and a ratio
        // of two same-series closes carries no currency.
        assert_eq!(candidate["metrics"]["change5mBps"], "44");
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
    fn a_request_resolved_mint_binds_the_bars_with_no_operator_standing_by() {
        // The keeper has no operator beside it. An acquisition whose retained envelope restates
        // the mint the request resolved must derive a scene on its own, with the binding
        // labelled as derived from the request — and never upgraded to observed, because the
        // provider body still names no coin.
        let root = tempfile::tempdir().expect("temp root");
        let store = store_with_outcome(
            root.path(),
            &resolved_outcome(),
            Some(CANDLES_REVIEW.as_bytes()),
        );
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let derived =
            derive_live_surface_with(&store, &source, None, &LiveSurfaceOptions::default())
                .expect("a request-resolved window binds without an operator");
        let report = &derived.report;
        assert_eq!(report.candle_subject_binding, "request_path_resolved");
        assert_eq!(report.candle_windows, 1);
        assert_eq!(report.candle_windows_unattributed, 0);
        assert_eq!(report.candle_bars_rendered, 200);
        assert!(report.price_series_rendered);

        let view: serde_json::Value =
            serde_json::from_slice(derived.view.canonical_bytes()).expect("canonical view");
        let candidate = &view["payload"]["candidates"][0];
        assert_eq!(candidate["mint"], SUBJECT);
        let evidence = candidate["evidence"].as_array().expect("evidence");
        let classes = evidence
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
        assert!(classes.contains(&("mint".to_owned(), "derived".to_owned())));
        assert!(
            !classes.contains(&("mint".to_owned(), "attested".to_owned())),
            "nobody attested anything on this path"
        );
        let note = evidence
            .iter()
            .find(|entry| entry["field"] == "mint")
            .and_then(|entry| entry["note"].as_str())
            .unwrap_or_default();
        assert!(note.contains("resolved"), "{note}");
        assert!(note.contains("request path"), "{note}");
        let tags = candidate["tags"].as_array().expect("tags");
        assert!(
            tags.iter().any(|tag| tag == "subject_request_resolved"),
            "{tags:?}"
        );
        assert!(!tags.iter().any(|tag| tag == "subject_operator_attested"));
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
    fn a_coin_exact_record_names_its_coin_and_renders_provider_claims() {
        let root = tempfile::tempdir().expect("temp root");
        let mut store =
            SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
        store.migrate(committed_at()).expect("migrate");
        commit_outcome(
            &mut store,
            &coin_exact_outcome(None),
            Some(COIN_EXACT_REVIEW.as_bytes()),
            "batch:pump-tap:coin-exact",
            1,
        );
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let derived =
            derive_live_surface_with(&store, &source, None, &LiveSurfaceOptions::default())
                .expect("a coin record names its own subject");
        let report = &derived.report;
        assert_eq!(report.coin_metadata_observations, 1);
        assert_eq!(report.coin_metadata_rows, 1);
        assert_eq!(report.coin_metadata_subjects, 1);
        assert_eq!(report.candidate_count, 1);
        assert!(!report.price_series_rendered);
        assert_eq!(
            report.ceiling,
            "provider_asserted_coin_metadata_no_price_no_fill"
        );

        let view: serde_json::Value =
            serde_json::from_slice(derived.view.canonical_bytes()).expect("canonical view");
        let candidate = &view["payload"]["candidates"][0];
        assert_eq!(candidate["mint"], COIN_EXACT_MINT);
        assert_eq!(candidate["symbol"], "FAUCAT");
        assert_eq!(candidate["name"], "FAUCAT");
        // The provider's exact `usd_market_cap` literal, byte-for-byte: a float round-trip here
        // would fabricate digits nobody asserted.
        assert_eq!(candidate["metrics"]["marketCapUsd"], "2540.9742079027883");
        assert!(candidate["metrics"]["priceSol"].is_null());
        assert!(candidate["metrics"]["change5mBps"].is_null());
        assert_eq!(candidate["candles"].as_array().map(Vec::len), Some(0));
        let tags = candidate["tags"].as_array().expect("tags");
        for expected in [
            "coin_metadata_observed",
            "market_cap_from_usd_market_cap",
            "market_cap_fields_disagree",
            "no_price_observed",
        ] {
            assert!(
                tags.iter().any(|tag| tag == expected),
                "{expected} in {tags:?}"
            );
        }
        // No chain frame named this mint, and its ticker IS observed.
        assert!(!tags.iter().any(|tag| tag == "chain_observed"), "{tags:?}");
        assert!(
            !tags.iter().any(|tag| tag == "ticker_unobserved"),
            "{tags:?}"
        );
        // The sibling market-cap claim stays visible instead of being averaged away.
        let reason = candidate["attentionReason"].as_str().unwrap_or_default();
        assert!(
            reason.contains("usd_market_cap=2540.9742079027883 (rendered)"),
            "{reason}"
        );
        assert!(
            reason.contains("market_cap_usd=2425.309648246627"),
            "{reason}"
        );
        let evidence = candidate["evidence"].as_array().expect("evidence");
        let fields = evidence
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
        for expected in ["mint", "symbol", "name", "metrics.marketCapUsd"] {
            assert!(
                fields.contains(&(expected.to_owned(), "observed".to_owned())),
                "{expected} observed in {fields:?}"
            );
        }
        // Freshness travels with the number: each rendered claim's evidence row carries the
        // read's own knowledge clock.
        let market_cap = evidence
            .iter()
            .find(|entry| entry["field"] == "metrics.marketCapUsd")
            .expect("market-cap evidence row");
        assert_eq!(market_cap["knownAt"], COMMITTED_AT);
        let note = market_cap["note"].as_str().unwrap_or_default();
        assert!(note.contains("`usd_market_cap`"), "{note}");
        assert!(note.contains("2425.309648246627"), "{note}");
        assert!(note.contains("passed no review"), "{note}");
    }

    #[test]
    fn a_discovery_page_renders_each_row_as_provider_claims() {
        let root = tempfile::tempdir().expect("temp root");
        let mut store =
            SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
        store.migrate(committed_at()).expect("migrate");
        // The discovery fixture was received at 03:33Z, later than the shared candles-era commit
        // instant, and the store refuses a persistence clock behind the receive clock.
        commit_outcome_at(
            &mut store,
            DISCOVERY_OUTCOME.trim_end().as_bytes(),
            Some(DISCOVERY_REVIEW.as_bytes()),
            "batch:pump-tap:discovery",
            1,
            "2026-08-22T04:00:00.000000Z",
        );
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let derived =
            derive_live_surface_with(&store, &source, None, &LiveSurfaceOptions::default())
                .expect("discovery rows name their own subjects");
        assert_eq!(derived.report.coin_metadata_observations, 1);
        assert_eq!(derived.report.coin_metadata_rows, 3);
        assert_eq!(derived.report.candidate_count, 3);
        assert_eq!(derived.report.candidates_rendered, 3);
        assert_eq!(derived.report.candidates_elided, 0);

        let view: serde_json::Value =
            serde_json::from_slice(derived.view.canonical_bytes()).expect("canonical view");
        let candidates = view["payload"]["candidates"]
            .as_array()
            .expect("candidates");
        let candidate = candidates
            .iter()
            .find(|candidate| candidate["mint"] == DISCOVERY_MINT)
            .expect("the first discovery row renders");
        assert_eq!(candidate["symbol"], "Bear");
        assert_eq!(candidate["name"], "BearShit");
        assert_eq!(candidate["metrics"]["marketCapUsd"], "2488.8286363782618");
        let tags = candidate["tags"].as_array().expect("tags");
        assert!(!tags.iter().any(|tag| tag == "chain_observed"), "{tags:?}");
        let naming = candidate["evidence"]
            .as_array()
            .expect("evidence")
            .iter()
            .find(|entry| entry["field"] == "mint")
            .and_then(|entry| entry["note"].as_str())
            .unwrap_or_default()
            .to_owned();
        assert!(
            naming.contains("row 0 of the retained discovery_coins page"),
            "{naming}"
        );
    }

    #[test]
    fn a_request_stated_sol_denomination_renders_the_newest_close_as_the_price() {
        let root = tempfile::tempdir().expect("temp root");
        let store = store_with_outcome(
            root.path(),
            &sol_candles_outcome(),
            Some(CANDLES_REVIEW.as_bytes()),
        );
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let derived =
            derive_live_surface_with(&store, &source, None, &LiveSurfaceOptions::default())
                .expect("a resolved window with a stated denomination renders");
        assert_eq!(
            derived.report.ceiling,
            "provider_asserted_price_path_request_stated_unit_no_fill_no_executability"
        );
        let view: serde_json::Value =
            serde_json::from_slice(derived.view.canonical_bytes()).expect("canonical view");
        let candidate = &view["payload"]["candidates"][0];
        // The newest bar's close, byte-for-byte, labelled SOL only because the request's own
        // retained `currency` says so; the body never states a unit.
        assert_eq!(
            candidate["metrics"]["priceSol"],
            "0.0127875704036029988601137368"
        );
        // Newest close against the latest close at least 300s earlier — 390s here, measured on
        // the gap-compressed path — rounded to the nearest basis point.
        assert_eq!(candidate["metrics"]["change5mBps"], "44");
        let tags = candidate["tags"].as_array().expect("tags");
        assert!(
            tags.iter().any(|tag| tag == "unit_request_stated"),
            "{tags:?}"
        );
        assert!(!tags.iter().any(|tag| tag == "unit_unstated"), "{tags:?}");
        let evidence = candidate["evidence"].as_array().expect("evidence");
        let price = evidence
            .iter()
            .find(|entry| entry["field"] == "metrics.priceSol")
            .expect("price evidence row");
        assert_eq!(price["evidenceClass"], "derived");
        let price_note = price["note"].as_str().unwrap_or_default();
        assert!(price_note.contains("currency=SOL"), "{price_note}");
        assert!(price_note.contains("not a quote"), "{price_note}");
        let change = evidence
            .iter()
            .find(|entry| entry["field"] == "metrics.change5mBps")
            .expect("change evidence row");
        assert_eq!(change["evidenceClass"], "derived");
        let change_note = change["note"].as_str().unwrap_or_default();
        assert!(change_note.contains("390s"), "{change_note}");
        assert!(
            change_note.contains("at least 300s earlier"),
            "{change_note}"
        );
    }

    #[test]
    fn one_candidate_carries_identity_price_and_market_cap_together() {
        // The cockpit case Ember actually sits in front of: one coin whose candles and coin
        // record were both retained. The candidate renders ticker, name, market cap, SOL price
        // and five-minute move together, each claim carrying its own provenance.
        let root = tempfile::tempdir().expect("temp root");
        let mut store =
            SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
        store.migrate(committed_at()).expect("migrate");
        commit_outcome(
            &mut store,
            &sol_candles_outcome(),
            Some(CANDLES_REVIEW.as_bytes()),
            "batch:pump-tap:candles",
            1,
        );
        commit_outcome(
            &mut store,
            &coin_exact_outcome(Some(SUBJECT)),
            Some(COIN_EXACT_REVIEW.as_bytes()),
            "batch:pump-tap:coin-exact",
            2,
        );
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let derived =
            derive_live_surface_with(&store, &source, None, &LiveSurfaceOptions::default())
                .expect("both reads render onto one candidate");
        assert_eq!(
            derived.report.ceiling,
            "provider_asserted_prices_and_coin_metadata_no_fill_no_executability"
        );
        assert_eq!(derived.report.candidate_count, 1);
        let view: serde_json::Value =
            serde_json::from_slice(derived.view.canonical_bytes()).expect("canonical view");
        let candidate = &view["payload"]["candidates"][0];
        assert_eq!(candidate["mint"], SUBJECT);
        assert_eq!(candidate["symbol"], "FAUCAT");
        assert_eq!(candidate["name"], "FAUCAT");
        assert_eq!(candidate["metrics"]["marketCapUsd"], "2540.9742079027883");
        assert_eq!(
            candidate["metrics"]["priceSol"],
            "0.0127875704036029988601137368"
        );
        assert_eq!(candidate["metrics"]["change5mBps"], "44");
        assert_eq!(candidate["candles"].as_array().map(Vec::len), Some(200));
    }

    #[test]
    fn coin_records_are_parsed_exactly_and_refused_when_they_cannot_be() {
        // The provider's empty string is an absence, never an empty label.
        let claims = parse_coin_records(
            "coin_exact",
            br#"{"mint":"MintAAAAAAAAAAAAAAAA","symbol":"","name":"Real","usd_market_cap":12.5}"#,
        )
        .expect("record parses");
        assert_eq!(claims.len(), 1);
        assert!(claims[0].symbol.is_none());
        assert_eq!(claims[0].name.as_deref(), Some("Real"));
        assert_eq!(claims[0].usd_market_cap.as_deref(), Some("12.5"));
        assert!(
            claims[0]
                .notes
                .iter()
                .any(|note| note.contains("empty `symbol`"))
        );

        // A literal the frozen decimal grammar cannot carry is refused as a number and stated,
        // never converted: converting 1.2e3 to "1200" would re-format a provider assertion.
        let claims = parse_coin_records(
            "coin_exact",
            br#"{"mint":"MintAAAAAAAAAAAAAAAA","usd_market_cap":1.2e3}"#,
        )
        .expect("record parses");
        assert!(claims[0].usd_market_cap.is_none());
        assert!(claims[0].notes.iter().any(|note| note.contains("1.2e3")));

        // A record with no mint names nothing and is refused whole.
        let error = parse_coin_records("coin_exact", br#"{"symbol":"X"}"#)
            .expect_err("a mintless record names no coin");
        assert!(error.contains("no `mint`"), "{error}");

        // An empty discovery page parses to zero claims; the caller states the ambiguity.
        assert!(
            parse_coin_records("discovery_coins", b"[]")
                .expect("empty page parses")
                .is_empty()
        );
    }

    #[test]
    fn basis_point_moves_are_exact_integer_arithmetic_with_stated_rounding() {
        assert_eq!(change_basis_points("101", "100"), Some(100));
        assert_eq!(change_basis_points("99", "100"), Some(-100));
        assert_eq!(change_basis_points("100", "100"), Some(0));
        // Half a basis point rounds away from zero, in both directions.
        assert_eq!(change_basis_points("100.005", "100"), Some(1));
        assert_eq!(change_basis_points("99.995", "100"), Some(-1));
        // Scales align exactly across different fractional lengths.
        assert_eq!(change_basis_points("0.0002", "0.0001"), Some(10_000));
        // A non-positive reference has no ratio, and a refusal is not a zero.
        assert_eq!(change_basis_points("1", "0"), None);
        assert_eq!(change_basis_points("1", "-1"), None);
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

    /// Two derivation versions never name the same scene over identical evidence, so an upgraded
    /// remount can mint a fresh scene at an unchanged watermark without colliding with the
    /// retired scene it supersedes — and the report says which version produced its bytes.
    #[test]
    fn scene_identity_separates_derivation_versions_over_identical_evidence() {
        let root = tempfile::tempdir().expect("temp root");
        let store = store_with_candles(root.path());
        let source = source_identity("pump.api.product.v1").expect("source identity");
        let durable = store
            .source_observations_newest_as_known(&source, None, MAX_LIVE_OBSERVATIONS)
            .expect("durable readback")
            .expect("fixture store holds observations");
        let current = scene_identity_under(LIVE_SURFACE_DERIVATION_VERSION, &durable);
        let other = scene_identity_under("previous-era", &durable);
        assert_ne!(
            current, other,
            "the derivation version is part of the scene-identity preimage"
        );
        assert_eq!(
            scene_identity_under(LIVE_SURFACE_DERIVATION_VERSION, &durable),
            current,
            "identity stays deterministic at a fixed version"
        );

        let derived = derive_live_surface_with(
            &store,
            &source,
            None,
            &LiveSurfaceOptions {
                attested_candle_subject: Some(SUBJECT.to_owned()),
            },
        )
        .expect("fixture derivation");
        assert_eq!(
            derived.report.derivation_version,
            LIVE_SURFACE_DERIVATION_VERSION
        );
        assert_eq!(derived.report.scene_id, current);
    }
}
