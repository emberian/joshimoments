use std::collections::{BTreeMap, BTreeSet};

use base64::Engine as _;
use joshi_pump_api::client::sha256;
use joshi_pump_api::normalize::schema_fingerprint;
use joshi_pump_api::{
    Acquisition, AuthDisposition, BodyCapture, IdentityStore, ParityInput, ParityInputV2,
    ParitySource, PromotionOccurrence, PromotionRunV1, RouteId, SchemaRegistry,
    SessionPathDisposition, compare, compare_v2, evaluate_promotion, normalize,
    parity_request_projection,
};
use serde_json::value::RawValue;

fn fixture(name: &str) -> Vec<u8> {
    std::fs::read(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/pump-api")
            .join(name),
    )
    .unwrap()
}

fn acquisition(id: &str, route: RouteId, bytes: &[u8]) -> Acquisition {
    Acquisition {
        contract: "joshi.pump_api.acquisition.v1".to_owned(),
        catalog_version: "joshi.pump_api.catalog.2026-08-16.v1".to_owned(),
        acquisition_id: id.to_owned(),
        request_group_id: format!("reqgrp:{id}"),
        attempt_ordinal: "1".to_owned(),
        route_id: route.to_string(),
        transport: "http".to_owned(),
        access_class: "officially_described_public".to_owned(),
        stability: "documented_mutable".to_owned(),
        session_class: "public".to_owned(),
        source_locator: "https://frontend-api-v3.pump.fun/fixture".to_owned(),
        request_fingerprint: sha256(b"same logical request"),
        http_status: Some(200),
        safe_response_headers: Vec::new(),
        clocks: joshi_pump_api::model::AcquisitionClocks {
            started_at: "2026-08-16T12:00:00.000000Z".to_owned(),
            received_at: "2026-08-16T12:00:00.010000Z".to_owned(),
            monotonic_clock_id: "fixture-clock".to_owned(),
            started_monotonic_ns: "0".to_owned(),
            received_monotonic_ns: "10000000".to_owned(),
            elapsed_ns: "10000000".to_owned(),
        },
        body: BodyCapture::Exact {
            boundary: "http_entity_body_post_transfer_decoding_identity_encoding".to_owned(),
            media_type: "application/json".to_owned(),
            bytes_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
            byte_length: bytes.len().to_string(),
            blob_id: sha256(bytes),
        },
    }
}

fn registry(route: RouteId, bytes: &[u8]) -> SchemaRegistry {
    let raw: Box<RawValue> = serde_json::from_slice(bytes).unwrap();
    SchemaRegistry {
        contract: "joshi.pump_api.schema_registry.v1".to_owned(),
        accepted: BTreeMap::from([(
            route.to_string(),
            BTreeSet::from([schema_fingerprint(&raw).unwrap()]),
        )]),
    }
}

#[test]
fn checked_in_registry_promotes_only_the_reviewed_fixture_shapes() {
    let registry = SchemaRegistry::from_slice(&fixture("schema-registry.v1.json")).unwrap();
    for (route, name) in [
        (RouteId::CoinExact, "coins-v2.synthetic.json"),
        (RouteId::CalloutRecent, "callout-recent.synthetic.json"),
        (RouteId::DiscoveryCoins, "discovery-page.synthetic.json"),
    ] {
        let bytes = fixture(name);
        let result = normalize(&acquisition("acq:registry", route, &bytes), &registry);
        assert_eq!(result.disposition, "accepted_provider_assertions");
    }
    let drift = fixture("schema-drift.synthetic.json");
    assert_eq!(
        normalize(
            &acquisition("acq:registry-drift", RouteId::CoinExact, &drift),
            &registry,
        )
        .disposition,
        "quarantined"
    );
}

#[test]
fn exact_numeric_lexemes_survive_normalization() {
    let bytes = fixture("coins-v2.synthetic.json");
    let result = normalize(
        &acquisition("acq:first", RouteId::CoinExact, &bytes),
        &registry(RouteId::CoinExact, &bytes),
    );
    assert_eq!(result.disposition, "accepted_provider_assertions");
    let fields = result.records[0]
        .fields
        .iter()
        .map(|field| (field.field.as_str(), field.value.as_deref()))
        .collect::<BTreeMap<_, _>>();
    assert_eq!(fields["created_timestamp"], Some("18446744073709551615"));
    assert_eq!(fields["last_trade_timestamp"], Some("9007199254740993"));
    assert_eq!(fields["market_cap"], Some("1.2300e-7"));
    assert_eq!(fields["usd_market_cap"], Some("0.0001000"));
}

#[test]
fn equal_content_in_distinct_acquisitions_stays_distinct() {
    let bytes = fixture("discovery-page.synthetic.json");
    let registry = registry(RouteId::DiscoveryCoins, &bytes);
    let first = normalize(
        &acquisition("acq:occurrence-one", RouteId::DiscoveryCoins, &bytes),
        &registry,
    );
    let second = normalize(
        &acquisition("acq:occurrence-two", RouteId::DiscoveryCoins, &bytes),
        &registry,
    );
    assert_eq!(first.records.len(), 2);
    assert_eq!(second.records.len(), 2);
    assert_ne!(
        first.records[0].acquisition_id,
        second.records[0].acquisition_id
    );
    assert_eq!(
        first.records[0].exact_row_blob_id,
        second.records[0].exact_row_blob_id
    );
    assert_ne!(
        first.records[0].exact_row_blob_id,
        first.records[1].exact_row_blob_id
    );
}

#[test]
fn unpromoted_schema_is_quarantined_without_losing_raw_body() {
    let accepted = fixture("coins-v2.synthetic.json");
    let drifted = fixture("schema-drift.synthetic.json");
    let acquisition = acquisition("acq:drift", RouteId::CoinExact, &drifted);
    let result = normalize(&acquisition, &registry(RouteId::CoinExact, &accepted));
    assert_eq!(result.disposition, "quarantined");
    assert!(result.records.is_empty());
    assert!(acquisition.body.exact_bytes().is_some());
    assert_eq!(result.fidelity_gaps[0].code, "unpromoted_schema");
}

#[test]
fn duplicate_keys_are_quarantined_before_field_projection() {
    let bytes = br#"{"mint":"one","mint":"two"}"#;
    let result = normalize(
        &acquisition("acq:duplicate", RouteId::CoinExact, bytes),
        &SchemaRegistry {
            contract: "joshi.pump_api.schema_registry.v1".to_owned(),
            accepted: BTreeMap::new(),
        },
    );
    assert_eq!(result.disposition, "quarantined_parse_or_contract_error");
    assert!(
        result.fidelity_gaps[0]
            .detail
            .contains("duplicate object key")
    );
}

#[test]
fn restart_safe_identity_is_reserved_before_acknowledgement() {
    let directory = tempfile::tempdir().unwrap();
    let first_store = IdentityStore::open(directory.path()).unwrap();
    let first = first_store.reserve().unwrap();
    assert!(first.reservation_path.exists());
    let installation = first_store.installation().to_owned();
    drop(first_store);

    let second_store = IdentityStore::open(directory.path()).unwrap();
    assert_eq!(second_store.installation(), installation);
    let second = second_store.reserve().unwrap();
    assert_ne!(first.acquisition_id, second.acquisition_id);
    second_store.acknowledge_id(&first.acquisition_id).unwrap();
    assert!(!first.reservation_path.exists());
}

fn parity_input(source: &str, bytes: &[u8]) -> ParityInput {
    ParityInput {
        contract: "joshi.pump_api.parity_input.v1".to_owned(),
        source: source.to_owned(),
        route_id: "coin_exact".to_owned(),
        catalog_version: "joshi.pump_api.catalog.2026-08-16.v1".to_owned(),
        request_fingerprint: sha256(b"same logical request"),
        session_class: "authenticated:fixture".to_owned(),
        comparison_boundary: "decoded_response_body".to_owned(),
        observed_at: "2026-08-16T12:00:00.000000Z".to_owned(),
        body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        byte_length: bytes.len().to_string(),
        blob_id: sha256(bytes),
    }
}

#[test]
fn parity_requires_matching_request_and_preserves_numeric_lexeme_diffs() {
    let equal = br#"{"n":9007199254740993}"#;
    assert_eq!(
        compare(
            &parity_input("companion", equal),
            &parity_input("direct", equal),
            10
        )
        .disposition,
        "exact_bytes_equal"
    );

    let left = parity_input("companion", br#"{"n":1.000}"#);
    let right = parity_input("direct", br#"{"n":1.0}"#);
    let report = compare(&left, &right, 10);
    assert_eq!(report.disposition, "comparable_response_difference");
    assert_eq!(report.differences[0].pointer, "$/n");

    let mut wrong_request = right;
    wrong_request.request_fingerprint = sha256(b"different request");
    assert_eq!(
        compare(&left, &wrong_request, 10).disposition,
        "incomparable"
    );
}

#[test]
fn checked_in_parity_pair_is_strict_and_exact() {
    let companion: ParityInput =
        serde_json::from_slice(&fixture("parity-companion.synthetic.json")).unwrap();
    let direct: ParityInput =
        serde_json::from_slice(&fixture("parity-direct.synthetic.json")).unwrap();
    let report = compare(&companion, &direct, 10);
    assert_eq!(report.disposition, "exact_bytes_equal", "{report:?}");
    assert!(report.precondition_failures.is_empty());
}

fn parity_v2(source: ParitySource, bytes: &[u8]) -> ParityInputV2 {
    let source_acquisition_id = match source {
        ParitySource::PumpCompanion => "acq:companion-pair-fixture-1",
        ParitySource::DirectPumpApi => "acq:direct-pair-fixture-1",
    };
    ParityInputV2 {
        contract: "joshi.pump_api.parity_input.v2".into(),
        pair_id: "pair-fixture-1".into(),
        source_acquisition_id: source_acquisition_id.into(),
        source,
        route_id: "discovery_coins".into(),
        catalog_version: joshi_pump_api::ROUTE_CATALOG.into(),
        request_fingerprint: sha256(b"request"),
        request_fingerprint_contract: "pump-parity-request-projection.v2".into(),
        request_projection_completeness: "complete".into(),
        visible_filter_fingerprint: sha256(b"filter"),
        cursor_in_fingerprint: None,
        pagination_kind: "offset_limit".into(),
        page_ordinal: "0".into(),
        session_class: "ordinary_authenticated".into(),
        session_occurrence_id: sha256(b"session-1"),
        auth_disposition: AuthDisposition::OrdinarySessionAccepted,
        comparison_boundary: "fetch_response_decoded_body_bytes".into(),
        started_at: "2026-08-17T12:00:00.000000Z".into(),
        received_at: "2026-08-17T12:00:00.010000Z".into(),
        http_status: 200,
        body_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        byte_length: bytes.len().to_string(),
        blob_id: sha256(bytes),
        rendered_order_digest: None,
    }
}

#[test]
fn parity_v2_binds_session_filter_cursor_time_and_retains_render_uncertainty() {
    let body = br#"[{"mint":"MintA"},{"mint":"MintB"}]"#;
    let companion = parity_v2(ParitySource::PumpCompanion, body);
    let mut direct = parity_v2(ParitySource::DirectPumpApi, body);
    direct.received_at = "2026-08-17T12:00:00.030000Z".into();
    let report = compare_v2(&companion, &direct, 50_000, 20);
    assert_eq!(report.disposition, "exact_bytes_equal", "{report:?}");
    assert_eq!(report.ordered_membership_disposition, "exact_match");
    assert_eq!(
        report.rendered_order_disposition,
        "provider_response_only_rendered_order_unwitnessed"
    );

    direct.visible_filter_fingerprint = sha256(b"different-filter");
    assert!(
        compare_v2(&companion, &direct, 50_000, 20)
            .precondition_failures
            .contains(&"visible_filter_fingerprint".to_owned())
    );
    direct.visible_filter_fingerprint = companion.visible_filter_fingerprint.clone();
    direct.received_at = "2026-08-17T12:00:01.000000Z".into();
    assert!(
        compare_v2(&companion, &direct, 50_000, 20)
            .precondition_failures
            .contains(&"pair_time_boundary".to_owned())
    );
}

#[test]
fn parity_v2_retains_membership_schema_auth_and_pagination_failures() {
    let left = br#"{"callouts":[{"calloutId":"a"}],"nextCursor":"one"}"#;
    let right = br#"{"callouts":[{"calloutId":"b"}],"nextCursor":"two","drift":true}"#;
    let mut companion = parity_v2(ParitySource::PumpCompanion, left);
    companion.route_id = "callout_recent".into();
    companion.pagination_kind = "cursor".into();
    let mut direct = parity_v2(ParitySource::DirectPumpApi, right);
    direct.route_id = "callout_recent".into();
    direct.pagination_kind = "cursor".into();
    let report = compare_v2(&companion, &direct, 50_000, 20);
    assert_eq!(
        report.disposition, "comparable_with_mismatch_evidence",
        "{report:?}"
    );
    assert!(
        report
            .mismatches
            .iter()
            .any(|item| item.kind == "schema_drift")
    );
    assert!(
        report
            .mismatches
            .iter()
            .any(|item| item.kind == "ordered_membership")
    );
    assert_eq!(report.pagination_disposition, "cursor_mismatch");

    direct.auth_disposition = AuthDisposition::SessionRejected;
    assert!(
        compare_v2(&companion, &direct, 50_000, 20)
            .precondition_failures
            .contains(&"auth_disposition".to_owned())
    );
}

fn promotion_occurrence(index: usize) -> PromotionOccurrence {
    PromotionOccurrence {
        pair_id: format!("pair-{index}"),
        pair_report_blob_id: sha256(format!("report-{index}").as_bytes()),
        session_occurrence_id: sha256(format!("session-{}", index % 3).as_bytes()),
        comparable: true,
        ordered_membership_match: index != 19,
        differences_understood: true,
        difference_review_id: (index == 19).then(|| "review-membership-difference-19".into()),
        mismatch_count: if index == 19 { "1" } else { "0" }.into(),
        pagination_gap_ids: vec![],
        pagination_chain_complete: true,
        auth_accepted: true,
        schema_quarantined: false,
    }
}

#[test]
fn promotion_requires_twenty_pairs_three_sessions_nineteen_matches_and_clean_pagination() {
    let run = PromotionRunV1 {
        contract: "joshi.pump_api.promotion_run.v1".into(),
        run_id: "promotion-fixture".into(),
        route_id: "discovery_coins".into(),
        catalog_version: joshi_pump_api::ROUTE_CATALOG.into(),
        session_path_disposition: SessionPathDisposition::OrdinaryHeadlessSessionAdmissible,
        occurrences: (0..20).map(promotion_occurrence).collect(),
        stop_condition_ids: vec![],
    };
    let report = evaluate_promotion(&run);
    assert_eq!(report.disposition, "promotable_continuous_direct_source");
    assert_eq!(report.ordered_membership_match_count, "19");

    let checked_in: PromotionRunV1 =
        serde_json::from_slice(&fixture("promotion-gate.synthetic.json")).unwrap();
    assert_eq!(
        evaluate_promotion(&checked_in).disposition,
        "promotable_continuous_direct_source"
    );
    let not_run: PromotionRunV1 =
        serde_json::from_slice(&fixture("promotion-not-run.v1.json")).unwrap();
    let not_run_report = evaluate_promotion(&not_run);
    assert_eq!(not_run_report.disposition, "not_promoted");
    assert_eq!(
        not_run_report.session_path_disposition,
        SessionPathDisposition::NotRunEmberPresentRequired
    );
    assert!(
        not_run_report
            .failures
            .contains(&"ember_present_run_not_performed".into())
    );

    let mut blocked = run;
    blocked.occurrences[0]
        .pagination_gap_ids
        .push("gap:page-zero".into());
    assert_eq!(evaluate_promotion(&blocked).disposition, "not_promoted");
    blocked.session_path_disposition = SessionPathDisposition::AuthenticatedDirectNotAdmissible;
    assert_eq!(
        evaluate_promotion(&blocked).disposition,
        "authenticated_direct_not_admissible"
    );
}

#[test]
fn rust_and_companion_share_the_exact_digest_only_parity_request_projection() {
    let request = joshi_pump_api::LogicalRequest {
        route: RouteId::CalloutRecent,
        parameters: joshi_pump_api::RequestParameters {
            path: BTreeMap::new(),
            query: BTreeMap::from([
                ("limit".into(), "20".into()),
                ("pageToken".into(), "opaque".into()),
            ]),
        },
    };
    let projection = parity_request_projection(&request).unwrap();
    assert_eq!(
        projection.request_fingerprint,
        "sha256:5b1a8618d11ea5e82db7ff655045687041d6b01288a93be29d5e2882c5e62f2f"
    );
    assert_eq!(
        projection.visible_filter_fingerprint,
        "sha256:6082d6edfb541889d2c990caf17ea94cb564581ac5c2c18c7493ad3e5f84b449"
    );
    assert_eq!(
        projection.cursor_in_fingerprint.as_deref(),
        Some("sha256:93439aa1dc7d4b929a45c4c2185edad219c15de28c42a4eb5642aa002254b3b1")
    );
}
