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

// ---------------------------------------------------------------------------------------------
// The row-projection gate.
//
// Everything above measures why one digest over a whole page cannot gate these three routes.
// Everything below is the gate that can: a required leaf set every row must carry, and a closed
// optional set a row may carry, checked per row over exactly the projection the normalizer reads.
// ---------------------------------------------------------------------------------------------

const DISCOVERY_ROWS: &str = include_str!("../fixtures/row_projection_discovery_coins_v1.json");
const CURRENTLY_LIVE_ROWS: &str = include_str!("../fixtures/row_projection_currently_live_v1.json");
const COIN_SEARCH_ROWS: &str = include_str!("../fixtures/row_projection_coin_search_v1.json");

fn row_review(source: &str) -> joshi_pump_api::RowProjectionReviewV1 {
    joshi_pump_api::RowProjectionReviewV1::from_slice(source.as_bytes())
        .expect("row projection parses")
}

/// Replace a fixture's body with deliberately altered bytes, keeping the envelope honest so the
/// gate refuses on the alteration rather than on a digest mismatch.
fn with_body(acquisition: &Acquisition, bytes: &[u8]) -> Acquisition {
    use base64::Engine as _;
    use joshi_pump_api::BodyCapture;
    use joshi_pump_api::client::sha256;

    let mut altered = acquisition.clone();
    let BodyCapture::Exact {
        boundary,
        media_type,
        ..
    } = acquisition.body.clone()
    else {
        panic!("fixture body is exact");
    };
    altered.body = BodyCapture::Exact {
        boundary,
        media_type,
        bytes_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        byte_length: bytes.len().to_string(),
        blob_id: sha256(bytes),
    };
    altered
}

fn rows_of(acquisition: &Acquisition) -> Vec<serde_json::Value> {
    body(acquisition)
        .as_array()
        .expect("a discovery page is a bare array")
        .clone()
}

fn body_of(rows: Vec<serde_json::Value>) -> Vec<u8> {
    serde_json::to_vec(&serde_json::Value::Array(rows)).expect("re-serializes")
}

#[test]
fn the_row_projection_promotes_all_three_discovery_feeds() {
    for (outcome, source, route) in [
        (DISCOVERY_OUTCOME, DISCOVERY_ROWS, "discovery_coins"),
        (
            CURRENTLY_LIVE_OUTCOME,
            CURRENTLY_LIVE_ROWS,
            "currently_live",
        ),
        (COIN_SEARCH_OUTCOME, COIN_SEARCH_ROWS, "coin_search"),
    ] {
        let review = row_review(source);
        assert_eq!(review.route_id, route);
        let decision = joshi_pump_api::decide_row_projection_trust(
            &attempt(outcome),
            Some(&review),
            DECIDED_AT,
        )
        .expect("decision");
        assert_eq!(
            decision.outcome,
            SchemaTrustOutcome::Promoted,
            "{route} refused: {} / {}",
            decision.reason_code,
            decision.detail
        );
        assert_eq!(decision.reason_code, "promoted_reviewed_row_projection");
        // The whole-document fingerprint is recorded on the promotion and gates nothing. It stays
        // a drift signal: a digest nobody has seen before is worth a look even when rows pass.
        assert!(decision.observed_schema_fingerprint.is_some());
        assert_eq!(
            decision.review_shape_digest.as_deref(),
            Some(review.leaf_digest().as_str())
        );
    }
}

#[test]
fn the_same_page_that_the_document_gate_refuses_is_the_one_the_row_gate_promotes() {
    // Both artifacts ship, and both are true. This pins that they disagree about the same bytes
    // for the reason recorded rather than by accident.
    let acquisition = attempt(DISCOVERY_OUTCOME);
    let document = decide_schema_trust(&acquisition, Some(&review(DISCOVERY_REVIEW)), DECIDED_AT)
        .expect("decision");
    let rows = joshi_pump_api::decide_row_projection_trust(
        &acquisition,
        Some(&row_review(DISCOVERY_ROWS)),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(document.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(rows.outcome, SchemaTrustOutcome::Promoted);
    assert_eq!(
        document.observed_schema_fingerprint, rows.observed_schema_fingerprint,
        "one body, one document fingerprint, two different questions asked about it"
    );
}

#[test]
fn a_row_carrying_an_unreviewed_leaf_refuses_rather_than_being_projected_away() {
    // This is the failure that lost ath_market_cap and volume_1h_usd for three days: a field the
    // normalizer did not know about simply vanished, and no gate anywhere had an opinion.
    let acquisition = attempt(DISCOVERY_OUTCOME);
    let mut rows = rows_of(&acquisition);
    rows[1]
        .as_object_mut()
        .expect("row is an object")
        .insert("brand_new_provider_field".into(), serde_json::json!(7));
    let altered = with_body(&acquisition, &body_of(rows));
    let decision = joshi_pump_api::decide_row_projection_trust(
        &altered,
        Some(&row_review(DISCOVERY_ROWS)),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_row_carries_unreviewed_leaf");
    assert!(
        decision.detail.contains("row 1")
            && decision
                .detail
                .contains("$/brand_new_provider_field:number"),
        "the refusal must name the row and the leaf: {}",
        decision.detail
    );
}

#[test]
fn a_row_missing_a_required_leaf_refuses_and_names_the_row_and_the_leaf() {
    let acquisition = attempt(DISCOVERY_OUTCOME);
    let mut rows = rows_of(&acquisition);
    rows[2]
        .as_object_mut()
        .expect("row is an object")
        .remove("mint")
        .expect("mint is required on this route");
    let altered = with_body(&acquisition, &body_of(rows));
    let decision = joshi_pump_api::decide_row_projection_trust(
        &altered,
        Some(&row_review(DISCOVERY_ROWS)),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_row_missing_required_leaf");
    assert!(
        decision.detail.contains("row 2") && decision.detail.contains("$/mint"),
        "{}",
        decision.detail
    );
}

#[test]
fn a_retyped_leaf_refuses_as_a_wire_type_and_not_as_an_unknown_field() {
    // A provider that starts sending a mint as a number has drifted, and the refusal has to say
    // which of the two things happened or the next reader will chase the wrong one.
    let acquisition = attempt(DISCOVERY_OUTCOME);
    let mut rows = rows_of(&acquisition);
    rows[0]
        .as_object_mut()
        .expect("row is an object")
        .insert("mint".into(), serde_json::json!(1234));
    let altered = with_body(&acquisition, &body_of(rows));
    let decision = joshi_pump_api::decide_row_projection_trust(
        &altered,
        Some(&row_review(DISCOVERY_ROWS)),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_row_leaf_type_not_reviewed");
    assert!(
        decision.detail.contains("$/mint:number"),
        "{}",
        decision.detail
    );
}

#[test]
fn an_empty_page_is_refused_rather_than_vacuously_promoted() {
    // Every per-row check passes trivially over zero rows. Promoting that would certify a row
    // shape from no rows, on a route whose past-the-end answer is byte-identical to its
    // matched-nothing answer.
    let decision = joshi_pump_api::decide_row_projection_trust(
        &attempt(EMPTY_PAGE_OUTCOME),
        Some(&row_review(DISCOVERY_ROWS)),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(
        decision.reason_code,
        "refused_empty_page_has_no_row_to_check"
    );
}

#[test]
fn a_row_projection_authored_for_one_route_never_promotes_another() {
    let decision = joshi_pump_api::decide_row_projection_trust(
        &attempt(DISCOVERY_OUTCOME),
        Some(&row_review(COIN_SEARCH_ROWS)),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(
        decision.reason_code,
        "refused_row_projection_review_route_mismatch"
    );
}

#[test]
fn a_leaf_cannot_be_both_required_on_every_row_and_optional_on_a_row() {
    let mut review = row_review(DISCOVERY_ROWS);
    review
        .optional_leaves
        .push(review.required_leaves[0].clone());
    assert!(
        review.validate().is_err(),
        "a leaf listing that says a field is both must not be usable"
    );
}

#[test]
fn normalizing_through_the_row_gate_emits_records_only_when_every_row_passes() {
    let acquisition = attempt(DISCOVERY_OUTCOME);
    let review = row_review(DISCOVERY_ROWS);
    let good = joshi_pump_api::normalize_with_row_projection(&acquisition, &review);
    assert_eq!(good.disposition, "accepted_provider_assertions");
    assert_eq!(good.records.len(), 3);
    assert!(
        good.schema_fingerprint.is_some(),
        "the document fingerprint still travels as an observation"
    );

    let mut rows = rows_of(&acquisition);
    rows[0]
        .as_object_mut()
        .expect("row is an object")
        .insert("surprise".into(), serde_json::json!("x"));
    let altered = with_body(&acquisition, &body_of(rows));
    let refused = joshi_pump_api::normalize_with_row_projection(&altered, &review);
    assert_eq!(refused.disposition, "quarantined");
    assert!(refused.records.is_empty());
    let gap = refused.fidelity_gaps.first().expect("a named gap");
    assert_eq!(gap.code, "refused_row_carries_unreviewed_leaf");
    assert!(gap.detail.contains("$/surprise:string"), "{}", gap.detail);
}

#[test]
fn observed_row_leaves_reports_what_a_body_carried_and_nothing_more() {
    // The reviewer's material: what a page actually held, split into present-on-every-row and
    // present-on-some. It is deliberately an observation and never a review.
    let acquisition = attempt(COIN_SEARCH_OUTCOME);
    let bytes = acquisition.body.exact_bytes().expect("bytes");
    let (required, optional) =
        joshi_pump_api::observed_row_leaves(RouteId::CoinSearch, &bytes).expect("leaves");
    assert!(required.contains(&"$/mint:string".to_owned()));
    assert!(
        required.contains(&"$/volume_1h_usd:number".to_owned()),
        "every row of a term-bearing search page carried a one-hour volume"
    );
    let shipped = row_review(COIN_SEARCH_ROWS);
    // The nested `mayhem` object is the only nested structure measured on any coin row, and it
    // appears on some search pages and not others. It belongs in the reviewed OPTIONAL set, and
    // asserting it against one body would be asserting a coincidence.
    assert!(
        shipped
            .optional_leaves
            .iter()
            .any(|leaf| leaf.starts_with("$/mayhem/")),
        "the closed optional set must cover the nested mayhem object"
    );
    let closed = shipped
        .required_leaves
        .iter()
        .chain(&shipped.optional_leaves)
        .collect::<BTreeSet<_>>();
    for leaf in required.iter().chain(&optional) {
        assert!(
            closed.contains(leaf),
            "the shipped review must already cover every leaf this body carried: {leaf}"
        );
    }
}

#[test]
fn a_graduated_coin_will_not_hand_back_reserves_to_anyone() {
    // MEASURED: a complete=true coin carried untouched launch constants while its market cap fell
    // 97 percent in ninety-seven seconds. A sibling reconstructing curve state must not be able to
    // assemble that quartet at all, so the accessor refuses and the field tag says why.
    use joshi_pump_api::{CurveState, ReserveRefusal, curve_state, price_bearing_reserves};

    let acquisition = attempt(DISCOVERY_OUTCOME);
    let normalization =
        joshi_pump_api::normalize_with_row_projection(&acquisition, &row_review(DISCOVERY_ROWS));
    let mut checked_graduated = 0_usize;
    let mut checked_on_curve = 0_usize;
    for record in &normalization.records {
        let tag = record
            .fields
            .iter()
            .find(|field| field.field == "virtual_sol_reserves")
            .map(|field| field.semantics.as_str());
        match curve_state(record) {
            CurveState::Graduated => {
                checked_graduated += 1;
                assert_eq!(
                    price_bearing_reserves(record).unwrap_err(),
                    ReserveRefusal::Graduated
                );
                assert_eq!(
                    tag,
                    Some("provider_launch_constant_after_graduation_never_a_price_input")
                );
            }
            CurveState::OnCurve => {
                checked_on_curve += 1;
                price_bearing_reserves(record).expect("a live curve hands back its reserves");
                assert_eq!(tag, Some("provider_bonding_curve_reserve_while_on_curve"));
            }
            CurveState::Unknown => {
                assert_eq!(
                    price_bearing_reserves(record).unwrap_err(),
                    ReserveRefusal::CurveStateUnknown
                );
            }
        }
    }
    assert!(
        checked_graduated + checked_on_curve > 0,
        "the fixture must exercise at least one curve state"
    );
}

#[test]
fn a_record_with_no_complete_flag_is_treated_as_unknown_and_not_as_live() {
    use joshi_pump_api::{CurveState, ReserveRefusal, curve_state, price_bearing_reserves};

    let acquisition = attempt(DISCOVERY_OUTCOME);
    let mut rows = rows_of(&acquisition);
    for row in &mut rows {
        row.as_object_mut().expect("object").remove("complete");
    }
    // Removing a required leaf refuses at the gate, which is the point; read the record through
    // the permissive path instead so the reserve accessor itself is what is being tested.
    let altered = with_body(&acquisition, &body_of(rows));
    let (_, normalization) = {
        let bytes = altered.body.exact_bytes().expect("bytes");
        let raw: Box<serde_json::value::RawValue> = serde_json::from_slice(&bytes).expect("json");
        let registry = SchemaRegistry {
            contract: "joshi.pump_api.schema_registry.v1".into(),
            accepted: [(
                altered.route_id.clone(),
                [joshi_pump_api::schema_fingerprint(&raw).expect("fingerprint")]
                    .into_iter()
                    .collect::<BTreeSet<_>>(),
            )]
            .into_iter()
            .collect(),
        };
        (altered.clone(), normalize(&altered, &registry))
    };
    for record in &normalization.records {
        assert_eq!(curve_state(record), CurveState::Unknown);
        assert_eq!(
            price_bearing_reserves(record).unwrap_err(),
            ReserveRefusal::CurveStateUnknown,
            "an unknown curve state is not a live one"
        );
        assert_eq!(
            record
                .fields
                .iter()
                .find(|field| field.field == "real_sol_reserves")
                .map(|field| field.semantics.as_str()),
            Some("provider_reserve_of_unknown_curve_state_never_a_price_input")
        );
    }
}

#[test]
fn neither_usd_market_cap_is_preferred_and_each_tag_names_the_other() {
    let acquisition = attempt(DISCOVERY_OUTCOME);
    let normalization =
        joshi_pump_api::normalize_with_row_projection(&acquisition, &row_review(DISCOVERY_ROWS));
    for record in &normalization.records {
        let tag = |name: &str| {
            record
                .fields
                .iter()
                .find(|field| field.field == name)
                .map(|field| field.semantics.as_str())
        };
        assert_eq!(
            tag("market_cap_usd"),
            Some("provider_usd_market_cap_assertion_disagreeing_with_usd_market_cap")
        );
        assert_eq!(
            tag("usd_market_cap"),
            Some("provider_usd_market_cap_assertion_disagreeing_with_market_cap_usd")
        );
        assert_eq!(
            tag("market_cap"),
            Some("provider_quote_denominated_market_cap_assertion"),
            "the SOL-denominated one is a third quantity, not a rounding of either"
        );
    }
}

#[test]
fn the_routes_the_document_gate_already_governs_are_not_disturbed_by_this_one() {
    // Why `candles` never needed a row projection, stated as a measurement rather than as a
    // reassurance: its rows are perfectly homogeneous, so its whole-document fingerprint is a
    // function of its schema and not of its contents. Every one of its rows carries the same six
    // leaves and NOTHING is optional, which is exactly the condition under which one digest over
    // a page is a sound gate. `coin_exact` is one record, so the same holds trivially.
    //
    // The row gate is therefore additive: it is switched on for the three discovery feeds and for
    // nothing else, and the reviews governing candles, trades and coin_exact are untouched.
    const CANDLES: &str = include_str!("../fixtures/candles_live_outcome_v1.json");
    let bytes = attempt(CANDLES).body.exact_bytes().expect("bytes");
    let (required, optional) =
        joshi_pump_api::observed_row_leaves(RouteId::Candles, &bytes).expect("leaves");
    assert_eq!(
        required,
        vec![
            "$/close:string".to_owned(),
            "$/high:string".to_owned(),
            "$/low:string".to_owned(),
            "$/open:string".to_owned(),
            "$/timestamp:number".to_owned(),
            "$/volume:string".to_owned(),
        ]
    );
    assert!(
        optional.is_empty(),
        "a homogeneous route has no optional leaves, which is why its document digest gates \
         soundly and why nothing about it changes here: {optional:?}"
    );
}

#[test]
fn the_v2_amendments_are_exactly_the_two_leaves_live_pages_refused_on() {
    // Both amendments were forced by a real refusal within minutes of the gate shipping, and both
    // are pinned here so that a later edit cannot quietly re-tighten or further widen them.
    //
    // A coin created with no metadata at all — mint 3E3bEp…jpump, name "NA" — carries no
    // `image_uri`, so requiring it refused an otherwise sound page.
    let discovery = row_review(DISCOVERY_ROWS);
    assert!(
        discovery
            .optional_leaves
            .contains(&"$/image_uri:string".to_owned()),
        "a coin with no metadata is a real coin; image_uri is optional"
    );
    assert!(
        !discovery
            .required_leaves
            .contains(&"$/image_uri:string".to_owned())
    );
    // A nested field nobody had read, seen beside {"state":"completed","mode":"auto"}.
    let search = row_review(COIN_SEARCH_ROWS);
    assert!(
        search
            .optional_leaves
            .contains(&"$/mayhem/complete_reason:string".to_owned()),
        "the leaf three live pages refused on is now reviewed, and reviewed as optional"
    );
    assert!(
        !search
            .required_leaves
            .iter()
            .any(|leaf| leaf.starts_with("$/mayhem/")),
        "nothing nested is required; it appears on some rows only"
    );
}

#[test]
fn tightening_one_leaf_back_to_required_reproduces_the_refusal_it_was_amended_for() {
    // The counterfactual, so the amendment is a measured change and not a loosening of habit.
    let acquisition = attempt(DISCOVERY_OUTCOME);
    let mut rows = rows_of(&acquisition);
    rows[0]
        .as_object_mut()
        .expect("row is an object")
        .remove("last_trade_timestamp");
    let altered = with_body(&acquisition, &body_of(rows));

    let amended = row_review(DISCOVERY_ROWS);
    let decision =
        joshi_pump_api::decide_row_projection_trust(&altered, Some(&amended), DECIDED_AT)
            .expect("decision");
    assert_eq!(
        decision.outcome,
        SchemaTrustOutcome::Promoted,
        "{}: {}",
        decision.reason_code,
        decision.detail
    );

    // Tightened on a leaf the normalizer DOES read, because from v3 a review may not require one
    // it does not: `last_trade_timestamp` is extracted, and a search row for a coin that has never
    // traded is what proved it optional.
    let mut tightened = amended;
    tightened
        .optional_leaves
        .retain(|leaf| leaf != "$/last_trade_timestamp:number");
    tightened
        .required_leaves
        .push("$/last_trade_timestamp:number".into());
    tightened.required_leaves.sort();
    let decision =
        joshi_pump_api::decide_row_projection_trust(&altered, Some(&tightened), DECIDED_AT)
            .expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_row_missing_required_leaf");
    assert!(
        decision.detail.contains("$/last_trade_timestamp"),
        "{}",
        decision.detail
    );
}

#[test]
fn a_nested_leaf_outside_the_closed_set_refuses_at_its_full_pointer() {
    // The search route carries the only nested structure measured on a coin row, so the refusal
    // has to name `$/mayhem/whatever` and not merely `$/mayhem`.
    let acquisition = attempt(COIN_SEARCH_OUTCOME);
    let mut rows = body(&acquisition).as_array().expect("bare array").clone();
    rows[0].as_object_mut().expect("row").insert(
        "mayhem".into(),
        serde_json::json!({"state": "completed", "invented_by_this_test": "x"}),
    );
    let altered = with_body(&acquisition, &body_of(rows));
    let decision = joshi_pump_api::decide_row_projection_trust(
        &altered,
        Some(&row_review(COIN_SEARCH_ROWS)),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_row_carries_unreviewed_leaf");
    assert!(
        decision
            .detail
            .contains("$/mayhem/invented_by_this_test:string"),
        "{}",
        decision.detail
    );
}

#[test]
fn a_review_may_not_require_a_leaf_this_crate_never_reads() {
    // Requiring an unread field cannot protect anything — its absence reaches no consumer — and it
    // costs a refusal every time the provider omits it on a rare row. Three live pages refused
    // that way within minutes of the first version of these reviews shipping. A fail-closed gate
    // whose refusals do not matter is a gate people learn to wave through, so the review itself
    // now refuses to be written that way.
    let mut review = row_review(DISCOVERY_ROWS);
    review.required_leaves.push("$/image_uri:string".to_owned());
    review
        .optional_leaves
        .retain(|leaf| leaf != "$/image_uri:string");
    assert!(
        review.validate().is_err(),
        "image_uri is never extracted, so requiring it must be rejected at review time"
    );
    let decision = joshi_pump_api::decide_row_projection_trust(
        &attempt(DISCOVERY_OUTCOME),
        Some(&review),
        DECIDED_AT,
    )
    .expect("decision");
    assert_eq!(
        decision.reason_code,
        "refused_row_projection_review_internally_inconsistent"
    );
}

#[test]
fn every_shipped_review_requires_only_what_it_consumes_and_closes_over_the_rest() {
    for (source, outcome) in [
        (DISCOVERY_ROWS, DISCOVERY_OUTCOME),
        (CURRENTLY_LIVE_ROWS, CURRENTLY_LIVE_OUTCOME),
        (COIN_SEARCH_ROWS, COIN_SEARCH_OUTCOME),
    ] {
        let review = row_review(source);
        review.validate().expect("shipped review is closed");
        assert!(
            !review.required_leaves.is_empty(),
            "a projection requiring nothing certifies nothing"
        );
        // `mint` is the one leaf without which a row cannot be joined to anything at all.
        assert!(
            review.required_leaves.contains(&"$/mint:string".to_owned()),
            "every coin row must be identifiable"
        );
        // And the closed set genuinely covers the page it was reviewed against.
        let bytes = attempt(outcome).body.exact_bytes().expect("bytes");
        let route = review
            .route_id
            .parse::<RouteId>()
            .expect("catalogued route");
        let (required, optional) =
            joshi_pump_api::observed_row_leaves(route, &bytes).expect("leaves");
        let closed = review
            .required_leaves
            .iter()
            .chain(&review.optional_leaves)
            .collect::<BTreeSet<_>>();
        for leaf in required.iter().chain(&optional) {
            assert!(closed.contains(leaf), "{leaf} is outside the closed set");
        }
    }
}
