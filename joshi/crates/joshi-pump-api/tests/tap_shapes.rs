//! What the two swap-api tap routes actually return, pinned against real responses.
//!
//! Both fixtures are verbatim `FetchOutcome` envelopes emitted by the bounded source-edge client
//! on 2026-08-22 against `https://swap-api.pump.fun` for mainnet mint
//! `HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump`. Nothing here is synthesized except the
//! deliberate corruptions, which exist to prove the gate refuses.
//!
//! These tests exist because both routes were catalogued from prose and the prose was wrong in
//! three separate ways: candles is a bare array rather than an enveloped one, the trades
//! continuation lives under `pagination` rather than at the root, and neither route's real field
//! names appeared in the field policy. Each assertion below is a measurement, not a restatement
//! of a provider document; there is no provider document.

use std::collections::BTreeSet;

use joshi_pump_api::{
    Acquisition, ClientConfig, FetchOutcome, Normalization, RouteId, RouteSpec, SchemaRegistry,
    SchemaReviewV1, SchemaTrustOutcome, decide_schema_trust, normalize,
};

const CANDLES_OUTCOME: &str = include_str!("../fixtures/candles_live_outcome_v1.json");
const TRADES_OUTCOME: &str = include_str!("../fixtures/trades_live_outcome_v1.json");
const CANDLES_REVIEW: &str = include_str!("../fixtures/schema_review_candles_v1.json");
const TRADES_REVIEW: &str = include_str!("../fixtures/schema_review_trades_v1.json");
const DECIDED_AT: &str = "2026-08-22T01:30:00.000000Z";

fn acquisition(outcome: &str) -> Acquisition {
    let outcome: FetchOutcome = serde_json::from_str(outcome.trim_end()).expect("outcome parses");
    assert!(outcome.completed, "the fixture is a completed read");
    outcome
        .attempts
        .last()
        .cloned()
        .expect("a completed outcome has an attempt")
}

fn review(source: &str) -> SchemaReviewV1 {
    SchemaReviewV1::from_slice(source.as_bytes()).expect("reviewed schema parses")
}

fn promoted(outcome: &str, review_source: &str) -> (Acquisition, Normalization) {
    let acquisition = acquisition(outcome);
    let review = review(review_source);
    let decision =
        decide_schema_trust(&acquisition, Some(&review), DECIDED_AT).expect("trust decision");
    assert_eq!(
        decision.outcome,
        SchemaTrustOutcome::Promoted,
        "{} was refused: {}",
        acquisition.route_id,
        decision.reason_code
    );
    let fingerprint = decision
        .observed_schema_fingerprint
        .clone()
        .expect("a promotion names the fingerprint it promoted");
    let registry = SchemaRegistry {
        contract: "joshi.pump_api.schema_registry.v1".into(),
        accepted: [(
            acquisition.route_id.clone(),
            [fingerprint].into_iter().collect::<BTreeSet<_>>(),
        )]
        .into_iter()
        .collect(),
    };
    let normalization = normalize(&acquisition, &registry);
    assert_eq!(normalization.disposition, "accepted_provider_assertions");
    (acquisition, normalization)
}

fn body(acquisition: &Acquisition) -> serde_json::Value {
    serde_json::from_slice(&acquisition.body.exact_bytes().expect("exact bytes"))
        .expect("body is JSON")
}

#[test]
fn the_tap_routes_are_switched_on_and_the_client_default_follows_the_catalog() {
    assert!(RouteSpec::for_id(RouteId::Candles).collection_enabled);
    assert!(RouteSpec::for_id(RouteId::Trades).collection_enabled);
    let from_catalog = RouteId::ALL
        .into_iter()
        .filter(|route| RouteSpec::for_id(*route).collection_enabled)
        .collect::<BTreeSet<_>>();
    assert_eq!(
        ClientConfig::default().enabled_routes,
        from_catalog,
        "the client default must not be a second hand-maintained list of enabled routes"
    );
}

#[test]
fn the_coverage_scope_key_still_fits_the_admission_boundary() {
    // `ordering` is concatenated into a 512-byte coverage-scope subject alongside the route id, a
    // 71-character request fingerprint, a 71-character cursor fingerprint and a page size. A long
    // measured note written here is not a documentation choice, it is a commit failure. Leave the
    // margin generous so the next person to edit a route's prose finds out here rather than in a
    // live run that has already spent a request.
    for route in RouteId::ALL {
        let spec = RouteSpec::for_id(route);
        assert!(
            spec.ordering.len() <= 256,
            "route {route} ordering is {} bytes; it is a scope key, not a place for the \
             measurement (that belongs in the reviewed-schema rationale)",
            spec.ordering.len()
        );
    }
}

#[test]
fn a_candle_window_is_a_bare_array_of_six_field_rows() {
    let (_, normalization) = promoted(CANDLES_OUTCOME, CANDLES_REVIEW);
    assert_eq!(
        normalization.records.len(),
        200,
        "candles is a bare top-level JSON array; reading it as an enveloped one yields zero rows"
    );
    for record in &normalization.records {
        let fields = record
            .fields
            .iter()
            .map(|field| field.field.as_str())
            .collect::<BTreeSet<_>>();
        assert_eq!(
            fields,
            ["close", "high", "low", "open", "timestamp", "volume"]
                .into_iter()
                .collect::<BTreeSet<_>>()
        );
    }
    let first = &normalization.records[0].fields;
    let of = |name: &str| {
        first
            .iter()
            .find(|field| field.field == name)
            .expect("field present")
    };
    assert_eq!(of("timestamp").encoding, "json_number_lexeme");
    assert_eq!(of("timestamp").semantics, "provider_event_time_unparsed");
    // Every price and volume arrives as a JSON string of decimals. Tagging it `utf8` alone would
    // let a later reader treat a price like a name, so the semantics carry the distinction.
    for name in ["open", "high", "low", "close", "volume"] {
        assert_eq!(of(name).encoding, "utf8", "{name}");
        assert_eq!(
            of(name).semantics,
            "provider_decimal_string_unparsed",
            "{name}"
        );
    }
    // A bare array carries no continuation of any kind, so nothing may invent one.
    let page = normalization.page.expect("page observation");
    assert_eq!(page.item_count, "200");
    assert_eq!(page.next_cursor_fingerprint, None);
}

#[test]
fn the_candle_window_is_ascending_and_gap_compressed_rather_than_a_regular_grid() {
    let acquisition = acquisition(CANDLES_OUTCOME);
    let rows = body(&acquisition);
    let rows = rows.as_array().expect("candles is a bare array");
    let stamps = rows
        .iter()
        .map(|row| row["timestamp"].as_i64().expect("epoch millis"))
        .collect::<Vec<_>>();
    assert!(
        stamps.windows(2).all(|pair| pair[0] < pair[1]),
        "candles arrive oldest-first; the catalog used to say this had to be remeasured per \
         response, and this fixture is that measurement"
    );
    let span = stamps.last().expect("rows") - stamps[0];
    let bars = i64::try_from(stamps.len()).expect("row count fits i64");
    assert!(
        span > (bars - 1) * 1_000,
        "a 1s window spanning {span} ms in {bars} bars can only mean empty seconds are omitted \
         rather than emitted flat, so consecutive rows are not one interval apart"
    );
    assert!(
        rows.iter().all(|row| row["volume"] != "0"),
        "no zero-volume bar appears, which is what gap compression means in practice"
    );
    // The bar open is the carried previous close, not the first trade of the interval, and the
    // provider repeats it byte-for-byte. Anything computing a gap between bars must know this.
    for pair in rows.windows(2) {
        assert_eq!(pair[1]["open"], pair[0]["close"]);
    }
}

#[test]
fn a_trade_page_carries_its_continuation_under_pagination() {
    let (acquisition, normalization) = promoted(TRADES_OUTCOME, TRADES_REVIEW);
    assert_eq!(normalization.records.len(), 50);
    for record in &normalization.records {
        let fields = record
            .fields
            .iter()
            .map(|field| field.field.as_str())
            .collect::<BTreeSet<_>>();
        assert_eq!(
            fields,
            [
                "amountSol",
                "amountUsd",
                "baseAmount",
                "fillPriceSol",
                "fillPriceUsd",
                "priceSol",
                "priceUsd",
                "program",
                "quoteAmount",
                "slotIndexId",
                "timestamp",
                "tx",
                "type",
                "userAddress",
            ]
            .into_iter()
            .collect::<BTreeSet<_>>()
        );
    }
    let page = normalization.page.expect("page observation");
    assert_eq!(page.item_count, "50");
    assert!(
        page.next_cursor_fingerprint.is_some(),
        "the continuation lives under `pagination`, not at the root; reading only the root \
         reported no next page while the provider said hasMore"
    );
    let rows = body(&acquisition);
    let pagination = &rows["pagination"];
    assert_eq!(pagination["hasMore"], serde_json::json!(true));
    let cursor = pagination["nextCursor"].as_str().expect("cursor string");
    let last = rows["trades"]
        .as_array()
        .expect("array")
        .last()
        .expect("row");
    // The cursor is the exclusive keyset of the last row rather than an opaque server token, so a
    // page boundary can be reconstructed from retained bytes alone.
    assert!(
        cursor.starts_with(last["slotIndexId"].as_str().expect("slot index")),
        "nextCursor {cursor} should begin with the last row's slotIndexId"
    );
}

#[test]
fn a_trade_page_is_newest_first_and_the_fill_price_is_not_the_pool_price() {
    let acquisition = acquisition(TRADES_OUTCOME);
    let rows = body(&acquisition);
    let rows = rows["trades"].as_array().expect("trades array").clone();
    let keys = rows
        .iter()
        .map(|row| row["slotIndexId"].as_str().expect("slot index").to_owned())
        .collect::<Vec<_>>();
    assert!(
        keys.windows(2).all(|pair| pair[0] > pair[1]),
        "trades arrive newest-first, strictly descending by slotIndexId"
    );
    // What the taker paid is not what the pool printed. Anything that reads a wiggle off the
    // price series and calls it capturable has to cross this gap twice.
    let mut gaps = Vec::new();
    for row in &rows {
        let quoted: f64 = row["priceUsd"]
            .as_str()
            .expect("price")
            .parse()
            .expect("f64");
        let filled: f64 = row["fillPriceUsd"]
            .as_str()
            .expect("fill")
            .parse()
            .expect("f64");
        let signed = (filled - quoted) / quoted * 10_000.0;
        match row["type"].as_str().expect("side") {
            "buy" => assert!(signed > 0.0, "a buy fills above the pool price"),
            "sell" => assert!(signed < 0.0, "a sell fills below the pool price"),
            other => panic!("unmeasured trade side {other:?}"),
        }
        // The gap is capped rather than growing with size: it behaves like a fee, and one row in
        // this page sits far below the cap, so a floor is NOT an invariant here.
        assert!(
            signed.abs() < 40.0,
            "fill-versus-pool gap of {signed} bps exceeds anything this fixture measured"
        );
        gaps.push(signed.abs());
    }
    assert_eq!(gaps.len(), 50);
    gaps.sort_by(f64::total_cmp);
    let median = gaps[gaps.len() / 2];
    assert!(
        (20.0..30.0).contains(&median),
        "the typical round of this venue's fee was about 25 bps; measured median {median}"
    );
}

#[test]
fn a_review_authored_for_one_tap_route_cannot_promote_the_other() {
    let candles = acquisition(CANDLES_OUTCOME);
    let decision = decide_schema_trust(&candles, Some(&review(TRADES_REVIEW)), DECIDED_AT)
        .expect("trust decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_review_route_mismatch");
}

#[test]
fn one_renamed_provider_field_refuses_the_whole_window() {
    use base64::Engine as _;
    use joshi_pump_api::BodyCapture;
    use joshi_pump_api::client::sha256;

    let mut acquisition = acquisition(CANDLES_OUTCOME);
    let bytes = acquisition.body.exact_bytes().expect("exact bytes");
    let drifted = String::from_utf8(bytes)
        .expect("utf8 body")
        .replacen("\"volume\"", "\"vol\"", 1)
        .into_bytes();
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
        bytes_base64: base64::engine::general_purpose::STANDARD.encode(&drifted),
        byte_length: drifted.len().to_string(),
        blob_id: sha256(&drifted),
    };
    let decision = decide_schema_trust(&acquisition, Some(&review(CANDLES_REVIEW)), DECIDED_AT)
        .expect("trust decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(
        decision.reason_code,
        "refused_observed_fingerprint_not_reviewed"
    );
    assert!(
        decision.observed_schema_fingerprint.is_some(),
        "a refusal still records the shape it refused"
    );
}

#[test]
fn the_two_tap_routes_agree_on_the_newest_event_they_saw() {
    // These two fixtures were fetched eight seconds apart against the same mint. The newest
    // candle bar and the newest trade are the same second, which is the cross-check that makes
    // the pair usable: neither route is running behind the other, and the candle series really
    // is built from the trade stream.
    //
    // It also settles a reading that would otherwise be wrong. Both were fetched at 01:23:20 and
    // the newest event in both is 01:11:13, twelve minutes earlier. That is not feed staleness;
    // the coin simply did not trade for twelve minutes, and because empty intervals are omitted
    // the newest bar is as old as the last trade. The age of the newest bar measures how quiet
    // the coin is, never how fresh the feed is.
    let candles = acquisition(CANDLES_OUTCOME);
    let trades = acquisition(TRADES_OUTCOME);
    let bars = body(&candles);
    let newest_bar = bars.as_array().expect("bare array").last().expect("a bar")["timestamp"]
        .as_i64()
        .expect("epoch millis");
    let rows = body(&trades);
    let newest_trade = rows["trades"].as_array().expect("array")[0]["timestamp"]
        .as_str()
        .expect("iso instant")
        .to_owned();
    let newest_trade = time::OffsetDateTime::parse(
        &newest_trade,
        &time::format_description::well_known::Rfc3339,
    )
    .expect("iso instant parses")
    .unix_timestamp()
        * 1_000;
    assert_eq!(
        newest_bar, newest_trade,
        "the newest candle bar and the newest trade must be the same instant"
    );
    let received = time::PrimitiveDateTime::parse(
        &candles.clocks.received_at,
        time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ),
    )
    .expect("canonical instant")
    .assume_utc()
    .unix_timestamp()
        * 1_000;
    assert!(
        received - newest_bar > 600_000,
        "this pair was captured across a quiet stretch, which is the case worth pinning"
    );
}
