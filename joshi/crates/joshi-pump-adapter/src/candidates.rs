//! A CANDIDATE FINDER. It is not a signal, and nothing in it is an entry.
//!
//! What it does is narrow: it takes two sweeps of a discovery feed separated by a known wall-clock
//! window, joins them on mint, and ranks the coins that appear in BOTH by how far their market cap
//! moved across that window. Optionally it attaches a one-hour realised volume from
//! `/coins/search-unrestricted` and the provider's own within-lifetime peak, so a human deciding
//! where to look has flow and drawdown beside the move rather than in another window.
//!
//! WHAT IT IS NOT. It models no fill, no latency, no size, no fee, no competition and no slippage.
//! It does not say a coin will keep moving; a coin that moved 20 percent in the last ninety
//! seconds is evidence about the last ninety seconds and about nothing after them. Appearing in
//! this slate is a reason for a person to open a chart, and it is exhaustively that.
//!
//! WHY IT EXISTS. Measured 2026-08-22 on two five-page sweeps of
//! `/coins?sort=last_trade_timestamp&order=DESC` taken ninety-seven seconds apart: 196 mints in
//! the first, 216 in the second, 64 present in both, and of those 64, ten moved at least 8 percent
//! and five at least 20 percent. That persisting third is not a random third — a coin only appears
//! in both sweeps if it traded in both windows — so the join is itself the flow filter, and the
//! magnitudes it surfaces are the magnitudes Ember works.
//!
//! HONESTY RULES THIS MODULE KEEPS.
//!   * Every number carries its denominator and its window. A percentage with no interval and no
//!     population behind it is not a measurement.
//!   * An absent provider field becomes an explicit [`Reading::Unknown`] with a reason, never a
//!     zero and never an omission. A coin row with no `ath_market_cap` has no drawdown; it does
//!     not have a drawdown of nothing.
//!   * `market_cap_usd` and `usd_market_cap` disagree by up to 0.31 percent, so BOTH deltas are
//!     computed and carried. Neither is picked here.
//!   * Every mint that was dropped is counted in the slate's own census, so a short slate can
//!     never be mistaken for a quiet market.
//!   * Only rows from pages a row-projection review PROMOTED reach a candidate. A refused page is
//!     counted as refused and contributes nothing.

use std::collections::{BTreeMap, BTreeSet};

use joshi_pump_api::{Acquisition, Normalization, NormalizedRecord};
use serde::{Deserialize, Serialize};

use crate::PumpAdapterError;

pub const CRACKLE_CANDIDATE_SLATE_V1: &str = "joshi.pump_adapter.crackle_candidate_slate.v1";

/// One provider number, or an explicit statement that there was none.
///
/// The `Unknown` arm carries why, because "we did not look" and "the provider did not say" are
/// different facts and a later reader cannot recover which one happened from a null.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum Reading {
    Known(String),
    Unknown(String),
}

impl Reading {
    fn known(value: impl Into<String>) -> Self {
        Self::Known(value.into())
    }

    fn unknown(reason: &str) -> Self {
        Self::Unknown(reason.to_owned())
    }

    #[must_use]
    pub fn value(&self) -> Option<&str> {
        match self {
            Self::Known(value) => Some(value),
            Self::Unknown(_) => None,
        }
    }
}

/// One coin as one sweep saw it. Every field is exactly what the provider's row carried, or
/// nothing at all.
#[derive(Clone, Debug, Default, PartialEq)]
struct CoinRow {
    usd_market_cap: Option<f64>,
    market_cap_usd: Option<f64>,
    ath_market_cap: Option<f64>,
    ath_market_cap_timestamp: Option<i64>,
    last_trade_timestamp: Option<i64>,
    created_timestamp: Option<i64>,
    reply_count: Option<i64>,
    num_participants: Option<i64>,
    volume_1h_usd: Option<f64>,
    complete: Option<bool>,
    name: Option<String>,
}

/// One pass over a feed: every promoted row it saw, and the census of what it refused.
#[derive(Clone, Debug, Default)]
pub struct Sweep {
    rows: BTreeMap<String, CoinRow>,
    pages_promoted: usize,
    pages_refused: usize,
    rows_seen: usize,
    rows_without_mint: usize,
    observed_from: Option<String>,
    observed_to: Option<String>,
}

impl Sweep {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Fold one page whose row projection was already decided.
    ///
    /// A page whose normalization is not `accepted_provider_assertions` is counted as refused and
    /// contributes no row. That is the whole point: an ungated row must not be able to reach a
    /// ranking by way of a convenience function.
    pub fn absorb(&mut self, acquisition: &Acquisition, normalization: &Normalization) {
        if normalization.disposition != "accepted_provider_assertions" {
            self.pages_refused += 1;
            return;
        }
        self.pages_promoted += 1;
        let seen = acquisition.clocks.received_at.clone();
        self.observed_from = Some(match self.observed_from.take() {
            Some(existing) if existing <= seen => existing,
            _ => seen.clone(),
        });
        self.observed_to = Some(match self.observed_to.take() {
            Some(existing) if existing >= seen => existing,
            _ => seen,
        });
        for record in &normalization.records {
            self.rows_seen += 1;
            let Some(mint) = text(record, "mint") else {
                self.rows_without_mint += 1;
                continue;
            };
            let row = CoinRow {
                usd_market_cap: number(record, "usd_market_cap"),
                market_cap_usd: number(record, "market_cap_usd"),
                ath_market_cap: number(record, "ath_market_cap"),
                ath_market_cap_timestamp: integer(record, "ath_market_cap_timestamp"),
                last_trade_timestamp: integer(record, "last_trade_timestamp"),
                created_timestamp: integer(record, "created_timestamp"),
                reply_count: integer(record, "reply_count"),
                num_participants: integer(record, "num_participants"),
                volume_1h_usd: number(record, "volume_1h_usd"),
                complete: boolean(record, "complete"),
                name: text(record, "name"),
            };
            // A mint seen twice in one sweep keeps its first sighting, so the sweep's clock and
            // its rows describe the same pass rather than a mixture of two.
            self.rows.entry(mint).or_insert(row);
        }
    }

    #[must_use]
    pub fn distinct_mints(&self) -> usize {
        self.rows.len()
    }
}

/// One coin worth a human's attention, with everything needed to distrust it.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CrackleCandidateV1 {
    pub mint: String,
    pub name: Reading,
    /// Signed percentage move of `usd_market_cap` across the sweep window.
    pub usd_market_cap_move_percent: Reading,
    /// The same move computed from the OTHER provider USD field. The two disagree by up to 0.31
    /// percent and neither is preferred; a candidate on which they disagree materially is a
    /// candidate to distrust.
    pub market_cap_usd_move_percent: Reading,
    pub usd_market_cap_early: Reading,
    pub usd_market_cap_late: Reading,
    /// How far below the provider's own recorded peak this coin now sits, as a signed percentage.
    pub drawdown_from_ath_percent: Reading,
    /// Age of that peak at the late sweep, in milliseconds. A peak from three minutes ago and a
    /// peak from three weeks ago are not the same fact.
    pub ath_age_ms: Reading,
    /// Realised one-hour USD volume, present only when a flow sweep supplied it. It is a provider
    /// aggregate over a window whose edges are not observable here.
    pub volume_1h_usd: Reading,
    pub last_trade_age_ms: Reading,
    pub coin_age_ms: Reading,
    pub reply_count: Reading,
    pub num_participants: Reading,
    /// `on_curve`, `graduated` or `unknown`. A graduated coin's reserve fields are frozen launch
    /// constants; nothing here derives a price from reserves for any coin, in either state.
    pub curve_state: String,
}

/// The census of one candidate-finding pass. Every count here exists so that a short slate cannot
/// be read as a quiet market.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SlateCensusV1 {
    pub sweep_window_ms: Reading,
    pub early_observed_from: Reading,
    pub early_observed_to: Reading,
    pub late_observed_from: Reading,
    pub late_observed_to: Reading,
    pub early_pages_promoted: String,
    pub early_pages_refused: String,
    pub late_pages_promoted: String,
    pub late_pages_refused: String,
    pub flow_pages_promoted: String,
    pub flow_pages_refused: String,
    pub early_distinct_mints: String,
    pub late_distinct_mints: String,
    pub mints_in_both_sweeps: String,
    /// In both sweeps but lacking a comparable `usd_market_cap` in one of them, so unrankable.
    pub mints_dropped_for_missing_market_cap: String,
    pub candidates_ranked: String,
    pub candidates_without_ath: String,
    pub candidates_without_volume: String,
}

/// The finished slate. Read the `authority` line before the candidates.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CrackleCandidateSlateV1 {
    pub contract: String,
    pub schema_version: String,
    /// Says out loud what this document is, because the ranking looks like a score and is not one.
    pub authority: String,
    pub route_id: String,
    pub sort_basis: String,
    pub census: SlateCensusV1,
    pub candidates: Vec<CrackleCandidateV1>,
}

/// Rank the coins present in both sweeps by how far their market cap moved between them.
///
/// `flow` is an optional sweep of `/coins/search-unrestricted`, the only route measured to carry
/// `volume_1h_usd`. Its coverage is whatever terms were swept, so a candidate with no volume here
/// is a candidate the flow sweep did not reach, never a candidate with no volume.
///
/// # Errors
///
/// Returns an error when either sweep promoted no page at all, because a slate built from nothing
/// would be a slate that looks empty for the wrong reason.
#[allow(clippy::too_many_lines)] // Every reading and its unknown-reason stay visible together.
pub fn find_candidates(
    early: &Sweep,
    late: &Sweep,
    flow: Option<&Sweep>,
    limit: usize,
) -> Result<CrackleCandidateSlateV1, PumpAdapterError> {
    if early.pages_promoted == 0 || late.pages_promoted == 0 {
        return Err(PumpAdapterError::Contract(
            "a candidate slate needs at least one promoted page in each sweep; an empty slate \
             must not be produced from a sweep that never succeeded"
                .into(),
        ));
    }
    let both = early
        .rows
        .keys()
        .filter(|mint| late.rows.contains_key(*mint))
        .cloned()
        .collect::<BTreeSet<_>>();
    let window_ms = span_ms(early.observed_to.as_deref(), late.observed_to.as_deref());
    let late_clock = late.observed_to.as_deref().and_then(parse_utc_ms);

    let mut dropped = 0_usize;
    let mut ranked = Vec::new();
    for mint in &both {
        let (before, after) = (&early.rows[mint], &late.rows[mint]);
        let Some(move_percent) = percent_move(before.usd_market_cap, after.usd_market_cap) else {
            dropped += 1;
            continue;
        };
        let flow_row = flow.and_then(|sweep| sweep.rows.get(mint));
        ranked.push((
            move_percent.abs(),
            CrackleCandidateV1 {
                mint: mint.clone(),
                name: after.name.clone().map_or_else(
                    || Reading::unknown("provider row carried no name"),
                    Reading::Known,
                ),
                usd_market_cap_move_percent: Reading::known(format!("{move_percent:.4}")),
                market_cap_usd_move_percent: percent_move(
                    before.market_cap_usd,
                    after.market_cap_usd,
                )
                .map_or_else(
                    || Reading::unknown("one sweep carried no market_cap_usd for this mint"),
                    |value| Reading::known(format!("{value:.4}")),
                ),
                usd_market_cap_early: reading_f64(
                    before.usd_market_cap,
                    "the early sweep carried no usd_market_cap",
                ),
                usd_market_cap_late: reading_f64(
                    after.usd_market_cap,
                    "the late sweep carried no usd_market_cap",
                ),
                drawdown_from_ath_percent: match (after.ath_market_cap, after.usd_market_cap) {
                    (Some(peak), Some(now)) if peak > 0.0 => {
                        Reading::known(format!("{:.4}", 100.0 * (now - peak) / peak))
                    }
                    _ => Reading::unknown(
                        "provider row carried no usable ath_market_cap, so this coin has no \
                         drawdown rather than a drawdown of zero",
                    ),
                },
                ath_age_ms: age_ms(
                    late_clock,
                    after.ath_market_cap_timestamp,
                    "ath_market_cap_timestamp",
                ),
                volume_1h_usd: flow_row.and_then(|row| row.volume_1h_usd).map_or_else(
                    || {
                        Reading::unknown(if flow.is_none() {
                            "no flow sweep was run, so no realised volume was looked for"
                        } else {
                            "the flow sweep's terms did not reach this mint; this is not a volume \
                             of zero"
                        })
                    },
                    |value| Reading::known(format!("{value}")),
                ),
                last_trade_age_ms: age_ms(
                    late_clock,
                    after.last_trade_timestamp,
                    "last_trade_timestamp",
                ),
                coin_age_ms: age_ms(late_clock, after.created_timestamp, "created_timestamp"),
                reply_count: reading_i64(after.reply_count, "provider row carried no reply_count"),
                num_participants: reading_i64(
                    after.num_participants,
                    "this route carries no num_participants; only /coins/currently-live does",
                ),
                curve_state: match after.complete {
                    Some(true) => "graduated",
                    Some(false) => "on_curve",
                    None => "unknown",
                }
                .to_owned(),
            },
        ));
    }
    ranked.sort_by(|left, right| {
        right
            .0
            .partial_cmp(&left.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.1.mint.cmp(&right.1.mint))
    });
    let total_ranked = ranked.len();
    let without_ath = ranked
        .iter()
        .filter(|(_, candidate)| candidate.drawdown_from_ath_percent.value().is_none())
        .count();
    let without_volume = ranked
        .iter()
        .filter(|(_, candidate)| candidate.volume_1h_usd.value().is_none())
        .count();
    let candidates = ranked
        .into_iter()
        .take(limit)
        .map(|(_, candidate)| candidate)
        .collect();

    Ok(CrackleCandidateSlateV1 {
        contract: CRACKLE_CANDIDATE_SLATE_V1.to_owned(),
        schema_version: "1".to_owned(),
        authority: "candidate_finder_for_human_attention_not_a_signal_and_not_an_entry".to_owned(),
        route_id: "discovery_coins".to_owned(),
        sort_basis: "descending absolute percentage move of usd_market_cap across the sweep \
                     window; ties broken by mint"
            .to_owned(),
        census: SlateCensusV1 {
            sweep_window_ms: window_ms,
            early_observed_from: reading_clock(early.observed_from.as_deref()),
            early_observed_to: reading_clock(early.observed_to.as_deref()),
            late_observed_from: reading_clock(late.observed_from.as_deref()),
            late_observed_to: reading_clock(late.observed_to.as_deref()),
            early_pages_promoted: early.pages_promoted.to_string(),
            early_pages_refused: early.pages_refused.to_string(),
            late_pages_promoted: late.pages_promoted.to_string(),
            late_pages_refused: late.pages_refused.to_string(),
            flow_pages_promoted: flow.map_or(0, |sweep| sweep.pages_promoted).to_string(),
            flow_pages_refused: flow.map_or(0, |sweep| sweep.pages_refused).to_string(),
            early_distinct_mints: early.rows.len().to_string(),
            late_distinct_mints: late.rows.len().to_string(),
            mints_in_both_sweeps: both.len().to_string(),
            mints_dropped_for_missing_market_cap: dropped.to_string(),
            candidates_ranked: total_ranked.to_string(),
            candidates_without_ath: without_ath.to_string(),
            candidates_without_volume: without_volume.to_string(),
        },
        candidates,
    })
}

fn percent_move(before: Option<f64>, after: Option<f64>) -> Option<f64> {
    let (before, after) = (before?, after?);
    (before != 0.0 && before.is_finite() && after.is_finite())
        .then(|| 100.0 * (after - before) / before)
}

fn reading_f64(value: Option<f64>, reason: &str) -> Reading {
    value.map_or_else(
        || Reading::unknown(reason),
        |value| Reading::known(value.to_string()),
    )
}

fn reading_i64(value: Option<i64>, reason: &str) -> Reading {
    value.map_or_else(
        || Reading::unknown(reason),
        |value| Reading::known(value.to_string()),
    )
}

fn reading_clock(value: Option<&str>) -> Reading {
    value.map_or_else(
        || Reading::unknown("no page in this sweep was promoted, so it has no clock"),
        Reading::known,
    )
}

/// Age of a provider EPOCH-MILLISECOND instant at the sweep clock.
///
/// `updated_at` is deliberately not routed through here: it is epoch SECONDS while every sibling
/// time on the same row is milliseconds, and mixing them silently is exactly the mistake this
/// codebase keeps paying for.
fn age_ms(now_ms: Option<i64>, at_ms: Option<i64>, field: &str) -> Reading {
    match (now_ms, at_ms) {
        (Some(now), Some(at)) => Reading::known((now - at).to_string()),
        (None, _) => Reading::unknown("the sweep carried no readable clock"),
        (_, None) => Reading::Unknown(format!("provider row carried no {field}")),
    }
}

fn span_ms(from: Option<&str>, to: Option<&str>) -> Reading {
    match (from.and_then(parse_utc_ms), to.and_then(parse_utc_ms)) {
        (Some(from), Some(to)) => Reading::known((to - from).to_string()),
        _ => Reading::unknown("one of the sweeps has no readable clock, so there is no window"),
    }
}

fn parse_utc_ms(value: &str) -> Option<i64> {
    let parsed = time::PrimitiveDateTime::parse(
        value,
        time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ),
    )
    .ok()?;
    // A clock that does not fit an i64 of milliseconds is 292 million years from the epoch, so
    // this cannot silently truncate a real acquisition instant. It still refuses rather than
    // wrapping, because a wrapped clock would produce a confident and wrong window.
    i64::try_from(
        parsed
            .assume_utc()
            .unix_timestamp_nanos()
            .div_euclid(1_000_000),
    )
    .ok()
}

fn lexeme<'a>(record: &'a NormalizedRecord, name: &str) -> Option<&'a str> {
    record
        .fields
        .iter()
        .find(|field| field.field == name)
        .and_then(|field| field.value.as_deref())
}

fn text(record: &NormalizedRecord, name: &str) -> Option<String> {
    record
        .fields
        .iter()
        .find(|field| field.field == name && field.encoding == "utf8")
        .and_then(|field| field.value.clone())
}

fn number(record: &NormalizedRecord, name: &str) -> Option<f64> {
    lexeme(record, name)?.parse().ok()
}

fn integer(record: &NormalizedRecord, name: &str) -> Option<i64> {
    lexeme(record, name)?.parse().ok()
}

fn boolean(record: &NormalizedRecord, name: &str) -> Option<bool> {
    match lexeme(record, name)? {
        "true" => Some(true),
        "false" => Some(false),
        _ => None,
    }
}
