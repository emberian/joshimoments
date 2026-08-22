//! What the three discovery feeds actually return, pinned against real responses.
//!
//! Every fixture here is a verbatim `FetchOutcome` or observed-shape artifact emitted by the
//! bounded source-edge client on 2026-08-22 against `https://frontend-api-v3.pump.fun`. Nothing
//! is synthesized except the deliberate corruptions, which exist to prove a gate refuses.
//!
//! These tests exist because the discovery half of this catalog was written from prose and the
//! prose was wrong. `/callout/recent` is not a route at all. `limit` on `/coins` silently clamps
//! at 70 and an offset past the end silently returns an empty array. The one field that could
//! rank coins by live flow, `volume_1h_usd`, is on `/coins/search-unrestricted` and on nothing
//! else, and was in no field policy. And the whole-document fingerprint that gates every other
//! route on this catalog cannot gate these three, for a reason that is measured below rather
//! than argued.

use std::collections::{BTreeMap, BTreeSet};

use joshi_pump_api::{
    Acquisition, ClientConfig, FetchOutcome, Normalization, RouteId, RouteSpec, SchemaRegistry,
    SchemaReviewV1, SchemaTrustOutcome, decide_schema_trust, fingerprint_of_shape, normalize,
};
use serde::Deserialize;

const DISCOVERY_OUTCOME: &str = include_str!("../fixtures/discovery_coins_live_outcome_v1.json");
const CURRENTLY_LIVE_OUTCOME: &str =
    include_str!("../fixtures/currently_live_live_outcome_v1.json");
const COIN_SEARCH_OUTCOME: &str = include_str!("../fixtures/coin_search_live_outcome_v1.json");
const EMPTY_PAGE_OUTCOME: &str = include_str!("../fixtures/discovery_coins_empty_page_v1.json");
const PHANTOM_CALLOUT_OUTCOME: &str = include_str!("../fixtures/callout_recent_phantom_v1.json");
const DISCOVERY_REVIEW: &str = include_str!("../fixtures/schema_review_discovery_coins_v1.json");
const CURRENTLY_LIVE_REVIEW: &str =
    include_str!("../fixtures/schema_review_currently_live_v1.json");
const COIN_SEARCH_REVIEW: &str = include_str!("../fixtures/schema_review_coin_search_v1.json");
const SHAPE_A: &str = include_str!("../fixtures/discovery_coins_observed_shape_a_v1.json");
const SHAPE_B: &str = include_str!("../fixtures/discovery_coins_observed_shape_b_v1.json");
const DECIDED_AT: &str = "2026-08-22T03:40:00.000000Z";

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ObservedShape {
    contract: String,
    route_id: String,
    catalog_version: String,
    acquisition_id: String,
    schema_fingerprint: String,
    shape: Vec<String>,
}

fn observed_shape(source: &str) -> ObservedShape {
    let value: ObservedShape = serde_json::from_str(source).expect("observed shape parses");
    assert_eq!(value.contract, "joshi.pump_api.observed_shape.v1");
    value
}

fn attempt(outcome: &str) -> Acquisition {
    let outcome: FetchOutcome = serde_json::from_str(outcome.trim_end()).expect("outcome parses");
    outcome
        .attempts
        .last()
        .cloned()
        .expect("every read retains its attempt")
}

fn review(source: &str) -> SchemaReviewV1 {
    SchemaReviewV1::from_slice(source.as_bytes()).expect("reviewed schema parses")
}

/// Normalize a fixture by admitting exactly the fingerprint it actually carries.
///
/// This deliberately bypasses the promote-or-quarantine gate, because the gate refuses all three
/// of these routes on purpose and these tests still have to describe what the bytes contain. It
/// is the reading a promotion would produce, never evidence that one happened.
fn records_of(outcome: &str) -> (Acquisition, Normalization) {
    let acquisition = attempt(outcome);
    let bytes = acquisition.body.exact_bytes().expect("exact bytes");
    let raw: Box<serde_json::value::RawValue> = serde_json::from_slice(&bytes).expect("JSON");
    let registry = SchemaRegistry {
        contract: "joshi.pump_api.schema_registry.v1".into(),
        accepted: [(
            acquisition.route_id.clone(),
            [joshi_pump_api::schema_fingerprint(&raw).expect("fingerprint")]
                .into_iter()
                .collect::<BTreeSet<_>>(),
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

fn field<'a>(record: &'a joshi_pump_api::NormalizedRecord, name: &str) -> Option<&'a str> {
    record
        .fields
        .iter()
        .find(|field| field.field == name)
        .and_then(|field| field.value.as_deref())
}

#[test]
fn the_three_discovery_feeds_are_switched_on_and_the_phantom_stays_off() {
    for route in [
        RouteId::DiscoveryCoins,
        RouteId::CurrentlyLive,
        RouteId::CoinSearch,
    ] {
        assert!(
            RouteSpec::for_id(route).collection_enabled,
            "{route} carries measured discovery signal and is collectable"
        );
    }
    assert!(
        !RouteSpec::for_id(RouteId::CalloutRecent).collection_enabled,
        "/callout/recent answered 400 and is not a route; it must never be collectable"
    );
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
fn a_discovery_page_is_a_bare_array_and_not_an_enveloped_one() {
    let (acquisition, normalization) = records_of(DISCOVERY_OUTCOME);
    assert!(
        body(&acquisition).is_array(),
        "/coins answers with a bare top-level JSON array"
    );
    assert_eq!(
        normalization.records.len(),
        3,
        "reading a bare array as an enveloped one yields zero rows out of a full page, which is \
         exactly how the candle normalizer was wrong for three days"
    );
    let page = normalization.page.expect("page observation");
    assert_eq!(page.item_count, "3");
    assert_eq!(
        page.next_cursor_fingerprint, None,
        "a bare array carries no continuation of any kind, so nothing may invent one"
    );
    assert_eq!(
        page.completion_claim, "unknown_not_inferred_from_page_length",
        "three rows back from limit=3 is not evidence that three coins exist"
    );
}

#[test]
fn an_empty_discovery_page_is_never_evidence_that_nothing_matched() {
    // Measured: offset=1030, 2000 and 5000 each returned the two bytes `[]` under HTTP 200, while
    // offset=1000 returned a full page. Past-the-end and no-such-coin are indistinguishable here.
    let (acquisition, normalization) = records_of(EMPTY_PAGE_OUTCOME);
    assert_eq!(acquisition.http_status, Some(200));
    assert_eq!(acquisition.body.exact_bytes().expect("bytes").len(), 2);
    assert!(normalization.records.is_empty());
    let (_, populated) = records_of(DISCOVERY_OUTCOME);
    assert_ne!(
        normalization.schema_fingerprint, populated.schema_fingerprint,
        "an empty page collapses to the single line `$:array`, so it is a different shape and a \
         reviewed schema for a populated page refuses it rather than reading it as zero coins"
    );
}

#[test]
fn callout_recent_is_not_a_route_and_the_refutation_is_durable() {
    let acquisition = attempt(PHANTOM_CALLOUT_OUTCOME);
    assert_eq!(acquisition.route_id, "callout_recent");
    assert_eq!(
        acquisition.http_status,
        Some(400),
        "the catalogued global recent-callout feed does not exist"
    );
    let bytes = acquisition
        .body
        .exact_bytes()
        .expect("the error body is retained");
    let text = String::from_utf8(bytes).expect("utf8");
    assert!(
        text.contains("uuid is expected"),
        "the provider rejected the literal path segment `recent` with a UUID parse, which means \
         the handler that caught this path is /callout/{{uuid}}: {text}"
    );
    let decision = decide_schema_trust(&acquisition, None, DECIDED_AT).expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_non_success_status");
    assert_eq!(
        decision.observed_schema_fingerprint, None,
        "an error body is retained as bytes and never fingerprinted as a product schema"
    );
}

#[test]
fn the_discovery_fingerprint_moves_with_the_page_contents_rather_than_the_schema() {
    // Two byte-identical requests, ninety-seven seconds apart: limit=70, offset=0,
    // sort=last_trade_timestamp, order=DESC. This is the measurement that decides whether the
    // whole-document fingerprint can gate a heterogeneous-row collection route. It cannot.
    let a = observed_shape(SHAPE_A);
    let b = observed_shape(SHAPE_B);
    assert_eq!(a.route_id, "discovery_coins");
    assert_eq!(b.route_id, a.route_id);
    assert_eq!(a.catalog_version, b.catalog_version);
    assert_ne!(
        a.acquisition_id, b.acquisition_id,
        "two distinct reads, not one read counted twice"
    );
    assert_eq!(fingerprint_of_shape(&a.shape), a.schema_fingerprint);
    assert_eq!(fingerprint_of_shape(&b.shape), b.schema_fingerprint);
    assert_ne!(
        a.schema_fingerprint, b.schema_fingerprint,
        "the same request twice produced two schemas"
    );
    let left = a.shape.iter().collect::<BTreeSet<_>>();
    let right = b.shape.iter().collect::<BTreeSet<_>>();
    assert_eq!(
        left.difference(&right)
            .copied()
            .cloned()
            .collect::<Vec<_>>(),
        vec![
            "$/*/cto_address:string".to_owned(),
            "$/*/cto_profile_image:string".to_owned(),
            "$/*/cto_username:string".to_owned(),
        ],
        "the whole difference is that one page happened to contain a coin with a community \
         takeover recorded"
    );
    assert!(
        right.difference(&left).next().is_none(),
        "the later page is a strict subset, so no provider field was renamed or removed"
    );
}

#[test]
fn a_review_pinned_to_one_discovery_page_refuses_the_next_one() {
    // The consequence of the measurement above, driven through the real gate. A reviewer who
    // promoted a single observed page would refuse the very next read for no provider-side reason.
    let a = observed_shape(SHAPE_A);
    let promoted = SchemaReviewV1 {
        contract: joshi_pump_api::SCHEMA_REVIEW_V1.to_owned(),
        schema_version: "1".to_owned(),
        review_id: "review:test-pinned-to-one-page".to_owned(),
        route_id: a.route_id.clone(),
        catalog_version: a.catalog_version.clone(),
        schema_fingerprint: a.schema_fingerprint.clone(),
        reviewed_shape: a.shape.clone(),
        reviewer: "this test".to_owned(),
        reviewed_at: DECIDED_AT.to_owned(),
        decision: SchemaTrustOutcome::Promoted,
        rationale: "constructed here to show what promoting one page would cost".to_owned(),
    };
    promoted
        .validate()
        .expect("the constructed review is closed");
    let decision =
        decide_schema_trust(&attempt(DISCOVERY_OUTCOME), Some(&promoted), DECIDED_AT).expect("ok");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(
        decision.reason_code, "refused_observed_fingerprint_not_reviewed",
        "and the refusal reason would read as provider drift when nothing drifted"
    );
}

#[test]
fn the_shipped_discovery_reviews_quarantine_rather_than_promote() {
    for (outcome, source, route) in [
        (DISCOVERY_OUTCOME, DISCOVERY_REVIEW, "discovery_coins"),
        (
            CURRENTLY_LIVE_OUTCOME,
            CURRENTLY_LIVE_REVIEW,
            "currently_live",
        ),
        (COIN_SEARCH_OUTCOME, COIN_SEARCH_REVIEW, "coin_search"),
    ] {
        let review = review(source);
        assert_eq!(review.route_id, route);
        assert_eq!(
            review.decision,
            SchemaTrustOutcome::Refused,
            "{route} is quarantined deliberately, on a measured instability, not by omission"
        );
        let decision =
            decide_schema_trust(&attempt(outcome), Some(&review), DECIDED_AT).expect("decision");
        assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
        assert_eq!(
            decision.reason_code, "refused_reviewer_refused_this_schema",
            "a named reviewer refusal, not an absent review"
        );
        assert!(
            decision.observed_schema_fingerprint.is_some(),
            "a quarantine still records what was observed"
        );
    }
}

#[test]
fn only_the_search_route_carries_a_realised_volume_and_it_ranks_by_it() {
    let (_, search) = records_of(COIN_SEARCH_OUTCOME);
    let volumes = search
        .records
        .iter()
        .map(|record| {
            field(record, "volume_1h_usd")
                .expect("every search row carries volume_1h_usd")
                .parse::<f64>()
                .expect("a JSON number lexeme")
        })
        .collect::<Vec<_>>();
    assert_eq!(volumes.len(), 5);
    assert!(
        volumes.windows(2).all(|pair| pair[0] >= pair[1]),
        "/coins/search-unrestricted returns rows descending by one-hour USD volume: {volumes:?}"
    );
    assert!(
        volumes.iter().all(|value| *value > 0.0),
        "a term-bearing search page carries live coins, not dead ones"
    );
    for (outcome, route) in [
        (DISCOVERY_OUTCOME, "discovery_coins"),
        (CURRENTLY_LIVE_OUTCOME, "currently_live"),
    ] {
        let (_, other) = records_of(outcome);
        assert!(
            other
                .records
                .iter()
                .all(|record| field(record, "volume_1h_usd").is_none()),
            "{route} carries no volume field at all, so it cannot rank coins by flow"
        );
    }
}

#[test]
fn the_live_feed_is_the_only_one_carrying_an_audience_count() {
    let (_, live) = records_of(CURRENTLY_LIVE_OUTCOME);
    assert!(!live.records.is_empty());
    for record in &live.records {
        field(record, "num_participants").expect("every live row carries num_participants");
    }
    let (_, discovery) = records_of(DISCOVERY_OUTCOME);
    assert!(
        discovery
            .records
            .iter()
            .all(|record| field(record, "num_participants").is_none())
    );
}

#[test]
fn updated_at_is_epoch_seconds_where_every_sibling_time_is_milliseconds() {
    // Read as milliseconds `updated_at` lands in January 1970, which reads as a plausible stale
    // record rather than as a units error. That is why the tag carries the distinction and why
    // nothing here rescales the lexeme.
    let (_, live) = records_of(CURRENTLY_LIVE_OUTCOME);
    let record = live
        .records
        .iter()
        .find(|record| field(record, "updated_at").is_some())
        .expect("a live row carries updated_at");
    let seconds = field(record, "updated_at")
        .expect("present")
        .parse::<i64>()
        .expect("integer lexeme");
    let millis = field(record, "created_timestamp")
        .expect("present")
        .parse::<i64>()
        .expect("integer lexeme");
    assert!(
        millis / seconds > 500 && millis / seconds < 2000,
        "created_timestamp is milliseconds and updated_at is seconds on the same row: \
         {millis} against {seconds}"
    );
    let tagged = record
        .fields
        .iter()
        .find(|field| field.field == "updated_at")
        .expect("present");
    assert_eq!(
        tagged.semantics, "provider_event_time_epoch_seconds_unparsed",
        "the units hazard travels with the field or it will be lost"
    );
}

#[test]
fn two_provider_fields_claim_the_same_market_cap_and_disagree() {
    // Neither may be silently preferred downstream: they were computed against different SOL
    // price snapshots and differ on essentially every row.
    let (_, live) = records_of(CURRENTLY_LIVE_OUTCOME);
    let disagreements = live
        .records
        .iter()
        .filter_map(|record| {
            let left = field(record, "market_cap_usd")?;
            let right = field(record, "usd_market_cap")?;
            (left != right).then_some((left.to_owned(), right.to_owned()))
        })
        .collect::<Vec<_>>();
    assert!(
        !disagreements.is_empty(),
        "market_cap_usd and usd_market_cap are two provider assertions about one quantity"
    );
    for (left, right) in &disagreements {
        let left = left.parse::<f64>().expect("number");
        let right = right.parse::<f64>().expect("number");
        assert!(
            (left - right).abs() / right < 0.01,
            "they disagree by well under one percent, which is exactly what makes preferring one \
             silently plausible: {left} against {right}"
        );
    }
}

#[test]
fn the_drawdown_pair_survives_normalization_on_every_coin_route() {
    // ath_market_cap with ath_market_cap_timestamp is the only within-lifetime peak this provider
    // exposes, and the earlier field policy dropped it from all four coin routes.
    let mut seen = BTreeMap::new();
    for (outcome, route) in [
        (DISCOVERY_OUTCOME, "discovery_coins"),
        (CURRENTLY_LIVE_OUTCOME, "currently_live"),
        (COIN_SEARCH_OUTCOME, "coin_search"),
    ] {
        let (_, normalization) = records_of(outcome);
        let count = normalization
            .records
            .iter()
            .filter(|record| {
                field(record, "ath_market_cap").is_some()
                    && field(record, "ath_market_cap_timestamp").is_some()
            })
            .count();
        seen.insert(route, count);
    }
    for (route, count) in &seen {
        assert!(
            *count > 0,
            "{route} carries the ATH pair and normalization must not drop it"
        );
    }
}
