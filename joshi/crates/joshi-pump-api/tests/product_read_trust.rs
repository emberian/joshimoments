//! Schema-trust and identity-claim behaviour, exercised against one real mainnet Pump response.
//!
//! The acquisition fixture is a verbatim envelope produced by the bounded source-edge client on
//! 2026-08-21 against `https://frontend-api-v3.pump.fun/coins-v2/{mint}`; the reviewed schema is
//! the artifact that was actually reviewed to promote it. Nothing here is synthesized except the
//! deliberate corruptions, which exist to prove the gate refuses.

use std::collections::BTreeSet;

use base64::Engine as _;
use joshi_pump_api::client::sha256;
use joshi_pump_api::{
    Acquisition, AuthenticatedPathDecision, BodyCapture, Normalization, SchemaRegistry,
    SchemaReviewV1, SchemaTrustOutcome, decide_schema_trust, normalize, product_identity_claim,
    session_path_note,
};

const ACQUISITION: &str = include_str!("../fixtures/coin_exact_live_acquisition_v1.json");
const REVIEW: &str = include_str!("../fixtures/schema_review_coin_exact_v1.json");
const DECIDED_AT: &str = "2026-08-21T11:20:00.000000Z";

fn acquisition() -> Acquisition {
    serde_json::from_str(ACQUISITION).expect("live acquisition fixture parses")
}

fn review() -> SchemaReviewV1 {
    SchemaReviewV1::from_slice(REVIEW.as_bytes()).expect("reviewed schema parses")
}

fn body_bytes(acquisition: &Acquisition) -> Vec<u8> {
    acquisition
        .body
        .exact_bytes()
        .expect("fixture has exact bytes")
}

/// Replace the exact body with `bytes`, keeping the declared length and digest honest.
fn with_body(mut acquisition: Acquisition, bytes: &[u8]) -> Acquisition {
    let BodyCapture::Exact {
        boundary,
        media_type,
        ..
    } = acquisition.body.clone()
    else {
        panic!("fixture body is not exact");
    };
    acquisition.body = BodyCapture::Exact {
        boundary,
        media_type,
        bytes_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        byte_length: bytes.len().to_string(),
        blob_id: sha256(bytes),
    };
    acquisition
}

fn promoted_normalization(acquisition: &Acquisition, fingerprint: &str) -> Normalization {
    let registry = SchemaRegistry {
        contract: "joshi.pump_api.schema_registry.v1".into(),
        accepted: [(
            acquisition.route_id.clone(),
            [fingerprint.to_owned()]
                .into_iter()
                .collect::<BTreeSet<_>>(),
        )]
        .into_iter()
        .collect(),
    };
    normalize(acquisition, &registry)
}

#[test]
fn the_reviewed_shape_must_hash_to_the_pinned_fingerprint() {
    let mut review = review();
    assert_eq!(review.shape_digest(), review.schema_fingerprint);
    review.reviewed_shape[0] = "$/associated_bonding_curve:number".into();
    assert!(
        review.validate().is_err(),
        "a review whose shape no longer hashes to its fingerprint must be rejected"
    );
}

#[test]
fn a_review_cannot_pin_a_fingerprint_without_retaining_a_shape() {
    let mut review = review();
    review.reviewed_shape.clear();
    assert!(review.validate().is_err());
}

#[test]
fn an_absent_review_refuses_and_still_records_what_was_observed() {
    let acquisition = acquisition();
    let decision = decide_schema_trust(&acquisition, None, DECIDED_AT).expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_no_review_for_route");
    assert!(!decision.promoted());
    assert_eq!(
        decision.observed_schema_fingerprint.as_deref(),
        Some(review().schema_fingerprint.as_str()),
        "a refusal still retains the fingerprint it refused"
    );
    assert_eq!(decision.review_id, None);
}

#[test]
fn the_reviewed_shape_promotes_the_observation_it_reviewed() {
    let acquisition = acquisition();
    let decision =
        decide_schema_trust(&acquisition, Some(&review()), DECIDED_AT).expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Promoted);
    assert_eq!(
        decision.reason_code,
        "promoted_reviewed_schema_fingerprint_match"
    );
    assert_eq!(
        decision.review_id.as_deref(),
        Some("review:pump-coin-exact:2026-08-21:v1")
    );
    assert_eq!(
        decision.review_shape_digest,
        decision.observed_schema_fingerprint
    );
}

#[test]
fn provider_shape_drift_refuses_rather_than_normalizing() {
    let acquisition = acquisition();
    let original = body_bytes(&acquisition);
    let text = String::from_utf8(original).expect("body is utf8");
    let drifted = text
        .replace(
            "\"twitter\":\"https://x.com/patchsol/status/2090194026267803792\"",
            "\"twitter\":null",
        )
        .into_bytes();
    assert_ne!(
        drifted,
        body_bytes(&acquisition),
        "the drift rewrite must actually change the bytes"
    );
    let drifted = with_body(acquisition, &drifted);
    let decision = decide_schema_trust(&drifted, Some(&review()), DECIDED_AT).expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(
        decision.reason_code,
        "refused_observed_fingerprint_not_reviewed"
    );
    assert_ne!(
        decision.observed_schema_fingerprint.as_deref(),
        Some(review().schema_fingerprint.as_str())
    );
}

#[test]
fn a_reviewer_refusal_is_final() {
    let mut review = review();
    review.decision = SchemaTrustOutcome::Refused;
    let decision =
        decide_schema_trust(&acquisition(), Some(&review), DECIDED_AT).expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_reviewer_refused_this_schema");
}

#[test]
fn a_review_for_another_route_never_promotes() {
    let mut review = review();
    review.route_id = "sol_price".into();
    let decision =
        decide_schema_trust(&acquisition(), Some(&review), DECIDED_AT).expect("decision");
    assert_eq!(decision.reason_code, "refused_review_route_mismatch");
}

#[test]
fn an_error_response_is_retained_but_never_promoted() {
    let mut acquisition = acquisition();
    acquisition.http_status = Some(503);
    let decision =
        decide_schema_trust(&acquisition, Some(&review()), DECIDED_AT).expect("decision");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(decision.reason_code, "refused_non_success_status");
    assert!(
        decision.body_blob_id.is_some(),
        "the refused response body identity is still recorded"
    );
}

#[test]
fn a_body_whose_digest_disagrees_with_its_bytes_refuses() {
    let mut acquisition = acquisition();
    let BodyCapture::Exact {
        boundary,
        media_type,
        bytes_base64,
        byte_length,
        ..
    } = acquisition.body.clone()
    else {
        panic!("fixture body is not exact");
    };
    acquisition.body = BodyCapture::Exact {
        boundary,
        media_type,
        bytes_base64,
        byte_length,
        blob_id: sha256(b"not these bytes"),
    };
    let decision =
        decide_schema_trust(&acquisition, Some(&review()), DECIDED_AT).expect("decision");
    assert_eq!(decision.reason_code, "refused_body_identity_mismatch");
}

#[test]
fn a_decision_needs_a_canonical_utc_instant() {
    assert!(decide_schema_trust(&acquisition(), Some(&review()), "2026-08-21T11:20:00Z").is_err());
}

#[test]
fn the_identity_claim_copies_only_the_providers_own_strings() {
    let acquisition = acquisition();
    let review = review();
    let normalization = promoted_normalization(&acquisition, &review.schema_fingerprint);
    assert_eq!(normalization.disposition, "accepted_provider_assertions");
    let claim = product_identity_claim(&acquisition, &normalization).expect("claim");

    let raw: serde_json::Value =
        serde_json::from_slice(&body_bytes(&acquisition)).expect("body is json");
    let object = raw.as_object().expect("body is an object");
    assert_eq!(
        object.get("mint").and_then(serde_json::Value::as_str),
        Some(claim.subject.as_str())
    );
    for (name, value) in &claim.attributes {
        assert_eq!(
            object.get(name).and_then(serde_json::Value::as_str),
            Some(value.as_str()),
            "attribute {name} must be the provider's exact string"
        );
        assert_eq!(
            claim.attribute_encodings.get(name).map(String::as_str),
            Some("utf8")
        );
    }
    assert_eq!(claim.subject_kind, "spl_mint");
    assert_eq!(claim.schema_fingerprint, review.schema_fingerprint);
    assert_eq!(claim.observed_at, acquisition.clocks.received_at);
    assert!(claim.claim_digest.starts_with("sha256:"));
}

#[test]
fn the_identity_claim_never_carries_price_or_reserve_state() {
    let acquisition = acquisition();
    let normalization = promoted_normalization(&acquisition, &review().schema_fingerprint);
    let claim = product_identity_claim(&acquisition, &normalization).expect("claim");
    let expected = [
        "creator",
        "name",
        "program",
        "protocol",
        "quote_mint",
        "symbol",
        "token_program",
    ]
    .into_iter()
    .collect::<BTreeSet<_>>();
    let observed = claim
        .attributes
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    assert!(
        observed.is_subset(&expected),
        "identity attributes drifted outside the reviewed projection: {observed:?}"
    );
    for forbidden in [
        "market_cap",
        "usd_market_cap",
        "virtual_sol_reserves",
        "real_token_reserves",
        "total_supply",
        "ath_market_cap",
    ] {
        assert!(!claim.attributes.contains_key(forbidden));
    }
}

#[test]
fn a_quarantined_normalization_yields_no_identity_claim() {
    let acquisition = acquisition();
    let registry = SchemaRegistry {
        contract: "joshi.pump_api.schema_registry.v1".into(),
        accepted: std::collections::BTreeMap::new(),
    };
    let normalization = normalize(&acquisition, &registry);
    assert_eq!(normalization.disposition, "quarantined");
    assert!(product_identity_claim(&acquisition, &normalization).is_err());
}

#[test]
fn a_normalization_from_another_occurrence_is_refused() {
    let acquisition = acquisition();
    let mut normalization = promoted_normalization(&acquisition, &review().schema_fingerprint);
    normalization.acquisition_id = "acq:pump-api:elsewhere".into();
    assert!(product_identity_claim(&acquisition, &normalization).is_err());
}

#[test]
fn a_public_read_is_recorded_as_an_unexercised_credential_path() {
    let acquisition = acquisition();
    let note = session_path_note(
        &acquisition,
        AuthenticatedPathDecision::NotPerformed,
        "no_documented_authenticated_get_read_route_for_present_credential",
        "read with no session provider configured",
        DECIDED_AT,
    )
    .expect("note");
    assert_eq!(note.observed_session_class, "public");
    assert!(!note.route_requires_session);
    assert_eq!(note.route_access_class, "officially_described_public");
    assert_eq!(
        note.auth_disposition,
        joshi_pump_api::AuthDisposition::NotRequiredPublic
    );
    assert_eq!(
        note.authenticated_path,
        AuthenticatedPathDecision::NotPerformed
    );
}

#[test]
fn a_rejected_session_is_never_reported_as_an_accepted_one() {
    let mut acquisition = acquisition();
    acquisition.http_status = Some(403);
    acquisition.session_class = "authenticated:sha256:deadbeef".into();
    let note = session_path_note(
        &acquisition,
        AuthenticatedPathDecision::Performed,
        "session_presented",
        "the provider rejected the session",
        DECIDED_AT,
    )
    .expect("note");
    assert_eq!(
        note.auth_disposition,
        joshi_pump_api::AuthDisposition::SessionRejected
    );
}
