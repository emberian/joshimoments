//! The two numbers this project actually uses, and the gate in front of them.
//!
//! Both live fixtures are verbatim `FetchOutcome` envelopes from 2026-08-22 for mainnet mint
//! `HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump`. The synthetic series below is not a fixture of
//! anything: it is a hand-built price path with an answer worked out by hand, and it exists
//! because "the counter runs" and "the counter counts the right thing" are different claims.

use std::collections::BTreeSet;

use base64::Engine as _;
use joshi_pump_adapter::{crackle, crackle_report, excursion_census, fee_floor};
use joshi_pump_api::client::sha256;
use joshi_pump_api::{
    Acquisition, BodyCapture, FetchOutcome, SchemaReviewV1, SchemaTrustDecisionV1,
    SchemaTrustOutcome, decide_schema_trust,
};

const CANDLES_OUTCOME: &str =
    include_str!("../../joshi-pump-api/fixtures/candles_live_outcome_v1.json");
const TRADES_OUTCOME: &str =
    include_str!("../../joshi-pump-api/fixtures/trades_live_outcome_v1.json");
const CANDLES_REVIEW: &str =
    include_str!("../../joshi-pump-api/fixtures/schema_review_candles_v1.json");
const TRADES_REVIEW: &str =
    include_str!("../../joshi-pump-api/fixtures/schema_review_trades_v1.json");
const MINT: &str = "HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump";
const AT: &str = "2026-08-22T02:30:00.000000Z";

fn acquisition(outcome: &str) -> Acquisition {
    let outcome: FetchOutcome = serde_json::from_str(outcome.trim_end()).expect("outcome parses");
    outcome.attempts.last().cloned().expect("an attempt")
}

fn promoted(outcome: &str, review: &str) -> (Acquisition, SchemaTrustDecisionV1) {
    let acquisition = acquisition(outcome);
    let review = SchemaReviewV1::from_slice(review.as_bytes()).expect("review parses");
    let decision = decide_schema_trust(&acquisition, Some(&review), AT).expect("decide");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Promoted);
    (acquisition, decision)
}

/// Replace a promoted acquisition's body with a hand-built one, keeping its identity honest.
fn with_body(source: &str, bytes: &[u8]) -> (Acquisition, SchemaTrustDecisionV1) {
    let (mut acquisition, mut decision) = promoted(source, CANDLES_REVIEW);
    let BodyCapture::Exact {
        boundary,
        media_type,
        ..
    } = acquisition.body.clone()
    else {
        panic!("fixture body is exact");
    };
    acquisition.body = BodyCapture::Exact {
        boundary,
        media_type,
        bytes_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        byte_length: bytes.len().to_string(),
        blob_id: sha256(bytes),
    };
    decision.body_blob_id = Some(sha256(bytes));
    (acquisition, decision)
}

/// A 1s series with the given closes, ascending, one second apart.
fn series(closes: &[f64]) -> Vec<u8> {
    let rows = closes
        .iter()
        .enumerate()
        .map(|(index, close)| {
            serde_json::json!({
                "timestamp": 1_787_000_000_000_i64 + i64::try_from(index).expect("index fits") * 1_000,
                "open": format!("{close:.10}"),
                "high": format!("{close:.10}"),
                "low": format!("{close:.10}"),
                "close": format!("{close:.10}"),
                "volume": "1.0",
            })
        })
        .collect::<Vec<_>>();
    serde_json::to_vec(&rows).expect("series serializes")
}

#[test]
fn the_fee_floor_is_measured_from_the_gap_between_the_pool_price_and_what_the_taker_paid() {
    let (acquisition, decision) = promoted(TRADES_OUTCOME, TRADES_REVIEW);
    let floor = fee_floor(&acquisition, &decision, MINT).expect("fee floor");
    assert_eq!(floor.rows, "50");
    assert_eq!(floor.buy_rows, "30");
    assert_eq!(floor.sell_rows, "20");
    assert_eq!(
        floor.venue_programs,
        [("raydium_v4_amm".to_owned(), "50".to_owned())]
            .into_iter()
            .collect(),
        "the floor belongs to a venue, and the venue is named rather than assumed"
    );
    assert_eq!(floor.one_way_median_bps, "24.47");
    assert_eq!(floor.round_trip_bps, "48.94");
    // A buy pays above the pool price and a sell receives below it. A floor that came out
    // symmetric with the wrong signs would mean the two fields had been swapped.
    assert!(floor.buy_median_bps.starts_with('2'));
    assert!(floor.sell_median_bps.starts_with('-'));
    assert!(
        !floor.excluded_costs.is_empty(),
        "the floor must carry what it does not include"
    );
    assert!(
        floor
            .excluded_costs
            .iter()
            .any(|cost| cost.contains("priority_fee")),
        "the Solana fee is not in the fill price and the record has to say so"
    );
}

#[test]
fn no_number_comes_out_of_bytes_no_review_promoted() {
    let acquisition = acquisition(TRADES_OUTCOME);
    let mut refused = decide_schema_trust(&acquisition, None, AT).expect("decide");
    assert_eq!(refused.outcome, SchemaTrustOutcome::Refused);
    let error = fee_floor(&acquisition, &refused, MINT).expect_err("a refusal yields no number");
    assert!(error.to_string().contains("refused_no_review_for_route"));

    // And a decision that was not taken about *this* acquisition cannot stand in for one.
    refused.outcome = SchemaTrustOutcome::Promoted;
    refused.acquisition_id = "acq:pump-api:somewhere-else".to_owned();
    let error = fee_floor(&acquisition, &refused, MINT).expect_err("mismatched decision refused");
    assert!(error.to_string().contains("different acquisition"));
}

#[test]
fn a_candle_route_measurement_refuses_a_trade_page_and_the_other_way_round() {
    let (candles, candles_decision) = promoted(CANDLES_OUTCOME, CANDLES_REVIEW);
    let (trades, trades_decision) = promoted(TRADES_OUTCOME, TRADES_REVIEW);
    assert!(fee_floor(&candles, &candles_decision, MINT).is_err());
    assert!(excursion_census(&trades, &trades_decision, MINT, 50.0, 900_000).is_err());
}

#[test]
fn the_excursion_counter_counts_a_hand_worked_series_exactly() {
    // Two excursions, worked out by hand at a 50 bps threshold.
    //   index 0 (100.0) -> index 1 (99.0) is -100 bps, clears the 50 bps down leg
    //   index 1 (99.0)  -> index 2 (100.5) is +151 bps, clears the up leg. One.
    //   index 2 (100.5) -> index 4 (99.3) clears down; index 4 -> index 5 (100.2) clears up. Two.
    // Index 3 is skipped by the down leg and no bar is used by two excursions.
    let (acquisition, decision) = with_body(
        CANDLES_OUTCOME,
        &series(&[100.0, 99.0, 100.5, 100.4, 99.3, 100.2]),
    );
    let census = excursion_census(&acquisition, &decision, MINT, 50.0, 900_000).expect("census");
    assert_eq!(census.bars, "6");
    assert_eq!(census.clearing_excursions, "2");
    assert_eq!(census.span_ms, "5000");

    // The same series against a threshold nothing in it clears.
    let census = excursion_census(&acquisition, &decision, MINT, 500.0, 900_000).expect("census");
    assert_eq!(
        census.clearing_excursions, "0",
        "a zero is the answer that rules a venue out, and it has to be reachable"
    );

    // A leg cap shorter than the excursion takes disqualifies it even though the move happened.
    let census = excursion_census(&acquisition, &decision, MINT, 50.0, 500).expect("census");
    assert_eq!(
        census.clearing_excursions, "0",
        "an excursion that takes longer than the caller will wait is not an excursion for them"
    );
}

#[test]
fn a_monotone_series_has_no_round_trips_however_far_it_travels() {
    let rising = (0..64)
        .map(|step| 100.0 + f64::from(step))
        .collect::<Vec<_>>();
    let (acquisition, decision) = with_body(CANDLES_OUTCOME, &series(&rising));
    let census = excursion_census(&acquisition, &decision, MINT, 50.0, 900_000).expect("census");
    assert_eq!(
        census.clearing_excursions, "0",
        "a coin that only goes up offers no dip to buy, which is the whole point of the count"
    );
    assert!(
        census.bar_return_max_bps.parse::<f64>().expect("bps") > 50.0,
        "and it moved plenty; the counter is not simply reporting a quiet series"
    );
}

#[test]
fn a_scrambled_time_axis_is_refused_rather_than_measured() {
    let mut rows: Vec<serde_json::Value> =
        serde_json::from_slice(&series(&[100.0, 99.0, 100.5])).expect("rows");
    rows.swap(0, 2);
    let bytes = serde_json::to_vec(&rows).expect("bytes");
    let (acquisition, decision) = with_body(CANDLES_OUTCOME, &bytes);
    let error = excursion_census(&acquisition, &decision, MINT, 50.0, 900_000)
        .expect_err("a descending window must not be silently counted");
    assert!(error.to_string().contains("ascending"));
}

#[test]
fn the_report_counts_against_the_floor_it_measured_rather_than_a_chosen_constant() {
    let (candles, candles_decision) = promoted(CANDLES_OUTCOME, CANDLES_REVIEW);
    let (trades, trades_decision) = promoted(TRADES_OUTCOME, TRADES_REVIEW);
    let report = crackle_report(
        (&trades, &trades_decision),
        (&candles, &candles_decision),
        MINT,
        AT,
        crackle::DEFAULT_LEG_CAP_MS,
    )
    .expect("report");
    assert_eq!(report.fee_floor.round_trip_bps, "48.94");
    assert_eq!(
        report.census.threshold_bps, report.fee_floor.round_trip_bps,
        "the threshold is the measured floor; that coupling is the reason the number is per-mint"
    );
    assert!(
        report
            .not_a_strategy_result
            .contains("nowhere near sufficient"),
        "the report has to carry its own limits or it will be read as a result"
    );
    // Distinct contracts so a later reader cannot confuse the parts for the whole.
    let contracts = [
        report.contract.as_str(),
        report.fee_floor.contract.as_str(),
        report.census.contract.as_str(),
    ]
    .into_iter()
    .collect::<BTreeSet<_>>();
    assert_eq!(contracts.len(), 3);
}
