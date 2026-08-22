//! The durable half of the swap-api tap: admit a candle window and a trade page into one
//! catalog, restart, and prove both provider bodies survive byte-for-byte.
//!
//! Both outcome fixtures are verbatim `FetchOutcome` envelopes emitted by the bounded source-edge
//! client on 2026-08-22 against `https://swap-api.pump.fun` for mainnet mint
//! `HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump`.
//!
//! Neither route has a reviewed identity projection: a candle window and a trade page identify no
//! subject. That is the interesting case here. A promoted read on such a route must still commit
//! its bytes, its coverage window and both explicit decisions, and the restart proof must not
//! quietly depend on an identity claim that was never going to exist.

use std::path::{Path, PathBuf};
use std::time::Duration;

use joshi_domain::{CommitSeq, StableString, UtcTimestamp};
use joshi_pump_adapter::{
    PreparedProductRead, ProductReadInput, close_receipt, prepare_direct_product_read,
};
use joshi_pump_api::{AuthenticatedPathDecision, SchemaTrustOutcome};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};

const CANDLES_OUTCOME: &str =
    include_str!("../../joshi-pump-api/fixtures/candles_live_outcome_v1.json");
const TRADES_OUTCOME: &str =
    include_str!("../../joshi-pump-api/fixtures/trades_live_outcome_v1.json");
const CANDLES_REVIEW: &str =
    include_str!("../../joshi-pump-api/fixtures/schema_review_candles_v1.json");
const TRADES_REVIEW: &str =
    include_str!("../../joshi-pump-api/fixtures/schema_review_trades_v1.json");
const COMMITTED_AT: &str = "2026-08-22T01:30:00.000000Z";

fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        // Zero forces every retained body to a content-addressed file, so a full verification
        // after restart re-hashes the exact provider bytes rather than trusting a catalog row.
        inline_blob_max_bytes: 0,
        busy_timeout: Duration::from_secs(5),
        catalog_id: StableString::new("joshi-pump-tap-test").expect("catalog id"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    }
}

fn committed_at() -> UtcTimestamp {
    COMMITTED_AT.parse().expect("canonical instant")
}

fn prepare(outcome: &str, review: Option<&[u8]>, batch: &str) -> PreparedProductRead {
    prepare_direct_product_read(&ProductReadInput {
        outcome_bytes: outcome.trim_end().as_bytes(),
        review_bytes: review,
        authenticated_path: AuthenticatedPathDecision::NotPerformed,
        session_reason_code: "no_documented_authenticated_get_read_route_for_present_credential",
        session_detail: "undocumented public product route read with no session provider \
                         configured",
        durable_batch_id: batch,
        committed_at: committed_at(),
        committed_monotonic_ns: 1,
        decided_at: COMMITTED_AT,
    })
    .expect("prepared product read")
}

fn external_blob_path(root: &Path, blob_id: &str) -> PathBuf {
    let digest = blob_id
        .strip_prefix("sha256:")
        .expect("blob identity is a sha256 digest");
    root.join("blobs")
        .join("public_source")
        .join("sha256")
        .join(&digest[0..2])
        .join(&digest[2..4])
        .join(format!("{digest}.blob"))
}

/// One route's admitted read, remembered well enough to be checked again after a restart.
struct Admitted {
    route: &'static str,
    blob_id: String,
    response_bytes: Vec<u8>,
    trust_key: String,
    session_key: String,
}

fn admit(
    store: &mut SqliteStore,
    outcome: &str,
    review: &str,
    batch: &str,
    route: &'static str,
) -> Admitted {
    let prepared = prepare(outcome, Some(review.as_bytes()), batch);
    assert_eq!(prepared.decision.outcome, SchemaTrustOutcome::Promoted);
    assert_eq!(prepared.acquisition.route_id, route);
    assert!(
        prepared.claim.is_none(),
        "a {route} window identifies no subject, so a promotion here yields no identity claim"
    );
    assert!(prepared.identity_semantic_key().is_none());
    let receipt = prepared
        .prepared
        .admission_batch()
        .commit(store)
        .expect("commit");
    close_receipt(&prepared.prepared, &receipt).expect("receipt closure");
    assert_eq!(
        receipt.admitted.assertions, "2",
        "the trust decision and the credential-path note, and nothing invented beyond them"
    );
    assert_eq!(
        receipt.admitted.observations, "2",
        "the attempt envelope and the exact provider body"
    );
    Admitted {
        route,
        blob_id: prepared
            .acquisition
            .body
            .blob_id()
            .expect("exact body has a digest")
            .to_owned(),
        response_bytes: prepared
            .acquisition
            .body
            .exact_bytes()
            .expect("exact response bytes"),
        trust_key: prepared.trust_semantic_key(),
        session_key: prepared.session_semantic_key(),
    }
}

fn assert_survived(reopened: &SqliteStore, root: &Path, cutoff: CommitSeq, admitted: &Admitted) {
    let route = admitted.route;
    let trust = reopened
        .effective_assertions_as_known(&admitted.trust_key, cutoff)
        .expect("read trust decision");
    assert_eq!(
        trust.len(),
        1,
        "{route} trust decision survives the restart"
    );
    let decision = trust[0]
        .value
        .get("decision")
        .expect("trust assertion carries the decision");
    assert_eq!(
        decision.get("outcome").and_then(serde_json::Value::as_str),
        Some("promoted")
    );
    assert_eq!(
        decision.get("routeId").and_then(serde_json::Value::as_str),
        Some(route)
    );

    let session = reopened
        .effective_assertions_as_known(&admitted.session_key, cutoff)
        .expect("read credential-path note");
    assert_eq!(session.len(), 1);
    let note = session[0]
        .value
        .get("note")
        .expect("session assertion carries the note");
    assert_eq!(
        note.get("routeAccessClass")
            .and_then(serde_json::Value::as_str),
        Some("observed_public_product"),
        "the note must not describe an observed product route as a documented one"
    );
    assert_eq!(
        note.get("observedSessionClass")
            .and_then(serde_json::Value::as_str),
        Some("public")
    );

    // The read-back is keyed by the digest the acquisition declared, not by a claim, so a route
    // that yields no claim is proven durable by exactly the same comparison.
    let stored = std::fs::read(external_blob_path(root, &admitted.blob_id))
        .expect("the exact provider body is on disk after restart");
    assert_eq!(
        stored, admitted.response_bytes,
        "{route} body must survive byte-for-byte"
    );
    // And it is still the thing it was: parseable, and the shape the review promoted.
    let value: serde_json::Value = serde_json::from_slice(&stored).expect("body is json");
    match route {
        "candles" => assert_eq!(value.as_array().expect("bare array").len(), 200),
        _ => assert_eq!(value["trades"].as_array().expect("trades array").len(), 50),
    }
}

#[test]
fn a_promoted_route_without_an_identity_projection_still_admits_its_bytes() {
    let root = tempfile::tempdir().expect("temp root");
    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
    store.migrate(committed_at()).expect("migrate");
    let admitted = [
        admit(
            &mut store,
            CANDLES_OUTCOME,
            CANDLES_REVIEW,
            "batch:pump-tap:candles",
            "candles",
        ),
        admit(
            &mut store,
            TRADES_OUTCOME,
            TRADES_REVIEW,
            "batch:pump-tap:trades",
            "trades",
        ),
    ];
    drop(store);

    let reopened =
        SqliteStore::open(config(root.path()), StoreMode::ReadOnly).expect("reopen store");
    let verification = reopened.verify(VerifyDepth::Full).expect("verify");
    assert_eq!(verification.integrity, "ok");
    assert_eq!(verification.foreign_key_defects, 0);
    assert_eq!(
        verification.external_artifacts_checked, 4,
        "two attempt envelopes and two provider bodies, all re-hashed on reopen"
    );
    for one in &admitted {
        assert_survived(&reopened, root.path(), verification.max_commit_seq, one);
    }
}

#[test]
fn an_unreviewed_tap_window_is_quarantined_and_its_bytes_are_still_retained() {
    let root = tempfile::tempdir().expect("temp root");
    let prepared = prepare(CANDLES_OUTCOME, None, "batch:pump-tap:candles-unreviewed");
    assert_eq!(prepared.decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(prepared.decision.reason_code, "refused_no_review_for_route");
    assert!(prepared.claim.is_none());
    assert!(
        prepared.decision.observed_schema_fingerprint.is_some(),
        "a refusal still records the shape it refused so a review can be written from it"
    );
    assert!(
        !prepared.observed_shape.is_empty(),
        "the run hands back the exact shape lines a reviewer would read"
    );

    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
    store.migrate(committed_at()).expect("migrate");
    let receipt = prepared
        .prepared
        .admission_batch()
        .commit(&mut store)
        .expect("a refusal still commits");
    assert_eq!(receipt.admitted.observations, "2");
    let bytes = prepared
        .acquisition
        .body
        .exact_bytes()
        .expect("exact response bytes");
    let blob = prepared
        .acquisition
        .body
        .blob_id()
        .expect("digest")
        .to_owned();
    drop(store);

    let reopened =
        SqliteStore::open(config(root.path()), StoreMode::ReadOnly).expect("reopen store");
    assert_eq!(
        reopened
            .verify(VerifyDepth::Full)
            .expect("verify")
            .integrity,
        "ok"
    );
    let stored = std::fs::read(external_blob_path(root.path(), &blob))
        .expect("quarantine retains the bytes it refused to trust");
    assert_eq!(stored, bytes);
}
