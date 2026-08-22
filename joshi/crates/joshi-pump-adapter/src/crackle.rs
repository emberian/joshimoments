//! Two numbers per mint, computed only from bytes a reviewed schema already promoted.
//!
//! The first is the venue's fee floor: the signed gap between the pool price a trade printed at
//! and the price its taker actually paid. It is measured per mint because it is not a constant —
//! a coin still in its pump phase and a coin that has graduated to a Raydium pool were measured
//! at very different floors, and the difference is larger than most of the price movement either
//! coin showed.
//!
//! The second is how often the price actually made a round trip large enough to clear that floor.
//! This is deliberately *not* a strategy result. It counts excursions in a retained price series;
//! it models no fill, no latency, no size, and no competition, and an excursion it counts is a
//! necessary condition for a profitable clip rather than a sufficient one. Its use is to rule
//! venues out cheaply, which it does honestly, and to rank the ones left for a human to look at.

use std::collections::BTreeMap;

use joshi_pump_api::{Acquisition, SchemaTrustDecisionV1, SchemaTrustOutcome};
use serde::{Deserialize, Serialize};

use crate::PumpAdapterError;

pub const FEE_FLOOR_V1: &str = "joshi.pump_adapter.fee_floor.v1";
pub const EXCURSION_CENSUS_V1: &str = "joshi.pump_adapter.excursion_census.v1";
pub const CRACKLE_REPORT_V1: &str = "joshi.pump_adapter.crackle_report.v1";

/// Default cap on how long either leg of one excursion may take.
pub const DEFAULT_LEG_CAP_MS: i64 = 900_000;

fn promoted_bytes(
    acquisition: &Acquisition,
    decision: &SchemaTrustDecisionV1,
    route: &str,
) -> Result<Vec<u8>, PumpAdapterError> {
    if decision.acquisition_id != acquisition.acquisition_id {
        return Err(PumpAdapterError::Contract(
            "the trust decision describes a different acquisition".into(),
        ));
    }
    if decision.outcome != SchemaTrustOutcome::Promoted {
        return Err(PumpAdapterError::Contract(format!(
            "a {route} measurement requires promoted bytes; this acquisition was {}",
            decision.reason_code
        )));
    }
    if acquisition.route_id != route {
        return Err(PumpAdapterError::Contract(format!(
            "expected route {route}, found {}",
            acquisition.route_id
        )));
    }
    acquisition
        .body
        .exact_bytes()
        .ok_or_else(|| PumpAdapterError::Contract("promoted acquisition has no exact body".into()))
}

/// Widen an exact count or a millisecond span so a ratio can be taken.
///
/// Everything that reaches this is a row count or a duration in milliseconds. A page holds at
/// most 100 rows and the retained history is months; a millisecond count would need roughly
/// 285,000 years before it stopped being exactly representable, so nothing in this crate's
/// domain loses a bit here.
#[allow(clippy::cast_precision_loss)]
pub(crate) const fn widen(value: i64) -> f64 {
    value as f64
}

fn count(value: usize) -> f64 {
    widen(i64::try_from(value).unwrap_or(i64::MAX))
}

/// The value at `permille` thousandths through an ascending series, indexed with integer maths so
/// no quantile is chosen by a float rounding accident.
fn quantile(sorted: &[f64], permille: usize) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let index = sorted.len() * permille / 1_000;
    sorted[index.min(sorted.len() - 1)]
}

fn bps(value: f64) -> String {
    format!("{value:.2}")
}

/// What one venue charges to cross its spread, measured rather than assumed.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FeeFloorV1 {
    pub contract: String,
    pub schema_version: String,
    pub subject_kind: String,
    pub subject: String,
    pub route_id: String,
    pub acquisition_id: String,
    pub body_blob_id: String,
    pub observed_at: String,
    pub rows: String,
    pub buy_rows: String,
    pub sell_rows: String,
    /// Which execution venue each row named, and how many rows named it.
    pub venue_programs: BTreeMap<String, String>,
    pub buy_median_bps: String,
    pub sell_median_bps: String,
    pub one_way_median_bps: String,
    pub one_way_max_bps: String,
    /// Twice the one-way median. Crossing in and back out costs at least this.
    pub round_trip_bps: String,
    pub trade_size_median_usd: String,
    pub trade_size_p90_usd: String,
    pub excluded_costs: Vec<String>,
}

/// Measure the fee floor from one promoted trade page.
///
/// # Errors
///
/// Returns an error when the acquisition is not a promoted trade page, or when a row is missing a
/// price, a fill price, a side, or a size.
pub fn fee_floor(
    acquisition: &Acquisition,
    decision: &SchemaTrustDecisionV1,
    subject: &str,
) -> Result<FeeFloorV1, PumpAdapterError> {
    let bytes = promoted_bytes(acquisition, decision, "trades")?;
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    let rows = value["trades"]
        .as_array()
        .ok_or_else(|| PumpAdapterError::Contract("trade page carries no trades array".into()))?;
    if rows.is_empty() {
        return Err(PumpAdapterError::Contract(
            "a fee floor cannot be measured from an empty trade page".into(),
        ));
    }
    let decimal = |row: &serde_json::Value, field: &str| -> Result<f64, PumpAdapterError> {
        row[field]
            .as_str()
            .ok_or_else(|| PumpAdapterError::Contract(format!("trade row has no {field}")))?
            .parse::<f64>()
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))
    };
    let mut buys = Vec::new();
    let mut sells = Vec::new();
    let mut magnitudes = Vec::new();
    let mut sizes = Vec::new();
    let mut venue_programs: BTreeMap<String, u64> = BTreeMap::new();
    for row in rows {
        let quoted = decimal(row, "priceUsd")?;
        if quoted <= 0.0 {
            return Err(PumpAdapterError::Contract(
                "trade row carries a non-positive pool price".into(),
            ));
        }
        let filled = decimal(row, "fillPriceUsd")?;
        let signed = (filled - quoted) / quoted * 10_000.0;
        match row["type"].as_str() {
            Some("buy") => buys.push(signed),
            Some("sell") => sells.push(signed),
            other => {
                return Err(PumpAdapterError::Contract(format!(
                    "unmeasured trade side {other:?}"
                )));
            }
        }
        magnitudes.push(signed.abs());
        sizes.push(decimal(row, "amountUsd")?);
        let program = row["program"]
            .as_str()
            .ok_or_else(|| PumpAdapterError::Contract("trade row names no program".into()))?;
        *venue_programs.entry(program.to_owned()).or_default() += 1;
    }
    for series in [&mut buys, &mut sells, &mut magnitudes, &mut sizes] {
        series.sort_by(f64::total_cmp);
    }
    let one_way_median = quantile(&magnitudes, 500);
    Ok(FeeFloorV1 {
        contract: FEE_FLOOR_V1.to_owned(),
        schema_version: "1".to_owned(),
        subject_kind: "spl_mint".to_owned(),
        subject: subject.to_owned(),
        route_id: acquisition.route_id.clone(),
        acquisition_id: acquisition.acquisition_id.clone(),
        body_blob_id: acquisition.body.blob_id().unwrap_or_default().to_owned(),
        observed_at: acquisition.clocks.received_at.clone(),
        rows: rows.len().to_string(),
        buy_rows: buys.len().to_string(),
        sell_rows: sells.len().to_string(),
        venue_programs: venue_programs
            .into_iter()
            .map(|(name, count)| (name, count.to_string()))
            .collect(),
        buy_median_bps: bps(quantile(&buys, 500)),
        sell_median_bps: bps(quantile(&sells, 500)),
        one_way_median_bps: bps(one_way_median),
        one_way_max_bps: bps(magnitudes.last().copied().unwrap_or_default()),
        round_trip_bps: bps(one_way_median * 2.0),
        trade_size_median_usd: format!("{:.4}", quantile(&sizes, 500)),
        trade_size_p90_usd: format!("{:.4}", quantile(&sizes, 900)),
        excluded_costs: vec![
            "solana_priority_fee_and_base_transaction_cost".to_owned(),
            "creator_and_protocol_fees_not_expressed_in_the_fill_price".to_owned(),
            "adverse_selection_between_decision_and_landing".to_owned(),
            "price_impact_of_a_clip_larger_than_the_measured_rows".to_owned(),
        ],
    })
}

/// How often a retained price series made a round trip clearing a stated threshold.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExcursionCensusV1 {
    pub contract: String,
    pub schema_version: String,
    pub subject_kind: String,
    pub subject: String,
    pub route_id: String,
    pub acquisition_id: String,
    pub body_blob_id: String,
    pub observed_at: String,
    pub bars: String,
    pub span_ms: String,
    pub span_hours: String,
    /// Fraction of the wall-clock span that carried a bar at all. The provider omits intervals
    /// with no trade, so this is the coin's liveness rather than a feed defect.
    pub trade_bearing_fraction: String,
    pub bar_return_median_bps: String,
    pub bar_return_p90_bps: String,
    pub bar_return_p99_bps: String,
    pub bar_return_max_bps: String,
    pub threshold_bps: String,
    pub leg_cap_ms: String,
    pub clearing_excursions: String,
    pub clearing_excursions_per_hour: String,
    pub method: String,
}

/// Count non-overlapping down-then-up round trips whose every leg clears `threshold_bps`.
///
/// The series is read close-only, so an excursion counted here is one a reader watching closed
/// bars could actually have seen; using the bar low and high would count moves that existed only
/// inside a bar. Both legs are capped at `leg_cap_ms`, and a counted excursion consumes the bars
/// it used, so two reported excursions never share a bar.
///
/// # Errors
///
/// Returns an error when the acquisition is not a promoted candle window.
pub fn excursion_census(
    acquisition: &Acquisition,
    decision: &SchemaTrustDecisionV1,
    subject: &str,
    threshold_bps: f64,
    leg_cap_ms: i64,
) -> Result<ExcursionCensusV1, PumpAdapterError> {
    let bytes = promoted_bytes(acquisition, decision, "candles")?;
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    let rows = value
        .as_array()
        .ok_or_else(|| PumpAdapterError::Contract("candle window is not a bare array".into()))?;
    if rows.len() < 2 {
        return Err(PumpAdapterError::Contract(
            "an excursion census needs at least two bars".into(),
        ));
    }
    let mut stamps = Vec::with_capacity(rows.len());
    let mut closes = Vec::with_capacity(rows.len());
    for row in rows {
        stamps.push(
            row["timestamp"].as_i64().ok_or_else(|| {
                PumpAdapterError::Contract("candle has no epoch timestamp".into())
            })?,
        );
        let close = row["close"]
            .as_str()
            .ok_or_else(|| PumpAdapterError::Contract("candle has no close".into()))?
            .parse::<f64>()
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
        if close <= 0.0 {
            return Err(PumpAdapterError::Contract(
                "candle carries a non-positive close".into(),
            ));
        }
        closes.push(close);
    }
    if stamps.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(PumpAdapterError::Contract(
            "candle window is not strictly ascending in time".into(),
        ));
    }
    let span_ms = stamps[stamps.len() - 1] - stamps[0];
    let mut returns = closes
        .windows(2)
        .map(|pair| (pair[1] - pair[0]).abs() / pair[0] * 10_000.0)
        .collect::<Vec<_>>();
    returns.sort_by(f64::total_cmp);

    let down = 1.0 - threshold_bps / 10_000.0;
    let up = 1.0 + threshold_bps / 10_000.0;
    let mut counted = 0_u64;
    let mut anchor = 0_usize;
    while anchor + 1 < closes.len() {
        let reference = closes[anchor];
        let Some(trough) = (anchor + 1..closes.len())
            .take_while(|index| stamps[*index] - stamps[anchor] <= leg_cap_ms)
            .find(|index| closes[*index] <= reference * down)
        else {
            anchor += 1;
            continue;
        };
        let entry = closes[trough];
        let Some(exit) = (trough + 1..closes.len())
            .take_while(|index| stamps[*index] - stamps[trough] <= leg_cap_ms)
            .find(|index| closes[*index] >= entry * up)
        else {
            anchor += 1;
            continue;
        };
        counted += 1;
        anchor = exit;
    }
    let hours = widen(span_ms) / 3_600_000.0;
    Ok(ExcursionCensusV1 {
        contract: EXCURSION_CENSUS_V1.to_owned(),
        schema_version: "1".to_owned(),
        subject_kind: "spl_mint".to_owned(),
        subject: subject.to_owned(),
        route_id: acquisition.route_id.clone(),
        acquisition_id: acquisition.acquisition_id.clone(),
        body_blob_id: acquisition.body.blob_id().unwrap_or_default().to_owned(),
        observed_at: acquisition.clocks.received_at.clone(),
        bars: rows.len().to_string(),
        span_ms: span_ms.to_string(),
        span_hours: format!("{hours:.4}"),
        trade_bearing_fraction: if span_ms > 0 {
            format!("{:.4}", count(rows.len()) / (widen(span_ms) / 1000.0))
        } else {
            "0.0000".to_owned()
        },
        bar_return_median_bps: bps(quantile(&returns, 500)),
        bar_return_p90_bps: bps(quantile(&returns, 900)),
        bar_return_p99_bps: bps(quantile(&returns, 990)),
        bar_return_max_bps: bps(returns.last().copied().unwrap_or_default()),
        threshold_bps: bps(threshold_bps),
        leg_cap_ms: leg_cap_ms.to_string(),
        clearing_excursions: counted.to_string(),
        clearing_excursions_per_hour: if hours > 0.0 {
            format!(
                "{:.3}",
                widen(i64::try_from(counted).unwrap_or(i64::MAX)) / hours
            )
        } else {
            "0.000".to_owned()
        },
        method: "non_overlapping_close_only_down_then_up_both_legs_clear_threshold".to_owned(),
    })
}

/// One mint's crackle measurement: the floor it has to clear, and how often it cleared it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CrackleReportV1 {
    pub contract: String,
    pub schema_version: String,
    pub subject_kind: String,
    pub subject: String,
    pub measured_at: String,
    pub fee_floor: FeeFloorV1,
    pub census: ExcursionCensusV1,
    /// What this number is not. Read it before the number.
    pub not_a_strategy_result: String,
}

/// Measure one mint's fee floor and then count the excursions that cleared it.
///
/// The threshold is the measured floor rather than a chosen constant, which is the whole point:
/// the same price series is worth looking at on one venue and worthless on another.
///
/// # Errors
///
/// Returns an error when either acquisition is unpromoted or malformed, or when the two describe
/// different subjects.
pub fn crackle_report(
    trades: (&Acquisition, &SchemaTrustDecisionV1),
    candles: (&Acquisition, &SchemaTrustDecisionV1),
    subject: &str,
    measured_at: &str,
    leg_cap_ms: i64,
) -> Result<CrackleReportV1, PumpAdapterError> {
    let fee_floor = fee_floor(trades.0, trades.1, subject)?;
    let threshold = fee_floor
        .round_trip_bps
        .parse::<f64>()
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
    let census = excursion_census(candles.0, candles.1, subject, threshold, leg_cap_ms)?;
    Ok(CrackleReportV1 {
        contract: CRACKLE_REPORT_V1.to_owned(),
        schema_version: "1".to_owned(),
        subject_kind: "spl_mint".to_owned(),
        subject: subject.to_owned(),
        measured_at: measured_at.to_owned(),
        fee_floor,
        census,
        not_a_strategy_result:
            "This counts excursions in a retained price series against a measured venue fee. It \
             models no fill, no latency, no order size, no competition for the same move, and \
             none of the excluded costs the fee floor names. A counted excursion is necessary for \
             a profitable clip and nowhere near sufficient. A count of zero is meaningful; a \
             count above zero is a reason to look, not a result."
                .to_owned(),
    })
}
