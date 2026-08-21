//! The durable half of one Pump product read: admit the exact bytes, attach the explicit
//! decisions, commit, drop the store, reopen it, and read the fact and its bytes back.
//!
//! The outcome fixture is a verbatim `FetchOutcome` emitted by the bounded source-edge client on
//! 2026-08-21 against `https://frontend-api-v3.pump.fun/coins-v2/{mint}` for a real mainnet mint.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::Duration;

use joshi_domain::{StableString, UtcTimestamp};
use joshi_pump_adapter::{
    PreparedProductRead, ProductReadInput, close_receipt, prepare_direct_product_read,
};
use joshi_pump_api::{AuthenticatedPathDecision, SchemaTrustOutcome};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};

const OUTCOME: &str = include_str!("../fixtures/coin_exact_live_outcome_v1.json");
const REVIEW: &str = include_str!("../../joshi-pump-api/fixtures/schema_review_coin_exact_v1.json");
const COMMITTED_AT: &str = "2026-08-21T11:30:00.000000Z";

fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 0,
        busy_timeout: Duration::from_secs(5),
        catalog_id: StableString::new("joshi-pump-product-read-test").expect("catalog id"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    }
}

fn committed_at() -> UtcTimestamp {
    COMMITTED_AT.parse().expect("canonical instant")
}

fn prepare(review: Option<&[u8]>) -> PreparedProductRead {
    prepare_direct_product_read(&ProductReadInput {
        outcome_bytes: OUTCOME.trim_end().as_bytes(),
        review_bytes: review,
        authenticated_path: AuthenticatedPathDecision::NotPerformed,
        session_reason_code: "no_documented_authenticated_get_read_route_for_present_credential",
        session_detail: "public product route read with no session provider configured",
        durable_batch_id: "batch:pump-product-read:test",
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

#[test]
fn a_promoted_product_read_survives_a_restart_with_the_bytes_that_said_so() {
    let root = tempfile::tempdir().expect("temp root");
    let prepared = prepare(Some(REVIEW.as_bytes()));
    assert_eq!(prepared.decision.outcome, SchemaTrustOutcome::Promoted);
    let claim = prepared.claim.clone().expect("promotion yields a claim");
    let response_bytes = prepared
        .acquisition
        .body
        .exact_bytes()
        .expect("exact response bytes");

    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
    store.migrate(committed_at()).expect("migrate");
    let receipt = prepared
        .prepared
        .admission_batch()
        .commit(&mut store)
        .expect("commit");
    let closed = close_receipt(&prepared.prepared, &receipt).expect("receipt closure");
    assert_eq!(receipt.admitted.assertions, "3");
    assert_eq!(receipt.admitted.observations, "2");
    assert_eq!(
        closed.durable_logical_digest.as_str(),
        receipt.batch_digest.as_str()
    );
    drop(store);

    let reopened =
        SqliteStore::open(config(root.path()), StoreMode::ReadOnly).expect("reopen store");
    let verification = reopened.verify(VerifyDepth::Full).expect("verify");
    assert_eq!(verification.integrity, "ok");
    assert_eq!(verification.foreign_key_defects, 0);
    assert_eq!(
        verification.external_artifacts_checked, 2,
        "both retained bodies are content-addressed files re-hashed on reopen"
    );

    let key = prepared
        .identity_semantic_key()
        .expect("promotion has a semantic key");
    let rows = reopened
        .effective_assertions_as_known(&key, verification.max_commit_seq)
        .expect("read back");
    assert_eq!(rows.len(), 1);
    let stored = &rows[0];
    assert_eq!(stored.assertion_id.as_str(), claim.claim_id);
    let stored_claim = stored
        .value
        .get("claim")
        .cloned()
        .expect("assertion carries the claim");
    assert_eq!(
        serde_json::from_value::<joshi_pump_api::ProductIdentityClaimV1>(stored_claim)
            .expect("claim decodes"),
        claim
    );

    let bytes = std::fs::read(external_blob_path(root.path(), &claim.body_blob_id))
        .expect("the exact provider body is on disk after restart");
    assert_eq!(bytes, response_bytes);
    let value: serde_json::Value = serde_json::from_slice(&bytes).expect("body is json");
    let object = value.as_object().expect("body is an object");
    assert_eq!(
        object.get("mint").and_then(serde_json::Value::as_str),
        Some(claim.subject.as_str())
    );
    for (name, expected) in &claim.attributes {
        assert_eq!(
            object.get(name).and_then(serde_json::Value::as_str),
            Some(expected.as_str()),
            "read-back bytes must still say {name}"
        );
    }
}

#[test]
fn the_trust_and_credential_decisions_are_readable_after_a_restart() {
    let root = tempfile::tempdir().expect("temp root");
    let prepared = prepare(Some(REVIEW.as_bytes()));
    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
    store.migrate(committed_at()).expect("migrate");
    prepared
        .prepared
        .admission_batch()
        .commit(&mut store)
        .expect("commit");
    drop(store);

    let reopened =
        SqliteStore::open(config(root.path()), StoreMode::ReadOnly).expect("reopen store");
    let cutoff = reopened
        .verify(VerifyDepth::Quick)
        .expect("verify")
        .max_commit_seq;

    let trust = reopened
        .effective_assertions_as_known(&prepared.trust_semantic_key(), cutoff)
        .expect("read trust decision");
    assert_eq!(trust.len(), 1);
    let decision = trust[0]
        .value
        .get("decision")
        .expect("trust assertion carries the decision");
    assert_eq!(
        decision.get("outcome").and_then(serde_json::Value::as_str),
        Some("promoted")
    );
    assert_eq!(
        decision.get("reviewId").and_then(serde_json::Value::as_str),
        Some("review:pump-coin-exact:2026-08-21:v1")
    );

    let session = reopened
        .effective_assertions_as_known(&prepared.session_semantic_key(), cutoff)
        .expect("read credential-path note");
    assert_eq!(session.len(), 1);
    let note = session[0]
        .value
        .get("note")
        .expect("session assertion carries the note");
    assert_eq!(
        note.get("authenticatedPath")
            .and_then(serde_json::Value::as_str),
        Some("not_performed")
    );
    assert_eq!(
        note.get("observedSessionClass")
            .and_then(serde_json::Value::as_str),
        Some("public")
    );
}

#[test]
fn a_refused_schema_still_commits_the_bytes_but_asserts_no_product_fact() {
    let root = tempfile::tempdir().expect("temp root");
    let prepared = prepare(None);
    assert_eq!(prepared.decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(prepared.decision.reason_code, "refused_no_review_for_route");
    assert!(prepared.claim.is_none());
    assert!(prepared.identity_semantic_key().is_none());

    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
    store.migrate(committed_at()).expect("migrate");
    let receipt = prepared
        .prepared
        .admission_batch()
        .commit(&mut store)
        .expect("commit");
    close_receipt(&prepared.prepared, &receipt).expect("receipt closure");
    assert_eq!(receipt.admitted.assertions, "2");
    assert_eq!(receipt.admitted.observations, "2");
    drop(store);

    let reopened =
        SqliteStore::open(config(root.path()), StoreMode::ReadOnly).expect("reopen store");
    let cutoff = reopened
        .verify(VerifyDepth::Quick)
        .expect("verify")
        .max_commit_seq;
    let quarantined = reopened
        .effective_assertions_as_known(
            "pump.product_identity:spl_mint:14m1ketwD6ikdjxtYnm3jtxVzPD9wXhnu5wYGMTWpump",
            cutoff,
        )
        .expect("query");
    assert!(
        quarantined.is_empty(),
        "a refused schema must not leave a product fact behind"
    );
    let blob = external_blob_path(
        root.path(),
        prepared
            .decision
            .body_blob_id
            .as_deref()
            .expect("refusal still names the body"),
    );
    assert!(
        blob.exists(),
        "a refusal retains the exact provider bytes it refused"
    );
}

#[test]
fn a_review_for_the_wrong_catalog_refuses_at_the_adapter_boundary() {
    let mut review: serde_json::Value = serde_json::from_str(REVIEW).expect("review json");
    review["catalogVersion"] =
        serde_json::Value::String("joshi.pump_api.catalog.1999-01-01".into());
    let bytes = serde_json::to_vec(&review).expect("review bytes");
    let prepared = prepare(Some(&bytes));
    assert_eq!(prepared.decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(
        prepared.decision.reason_code,
        "refused_review_catalog_version_mismatch"
    );
    assert!(prepared.claim.is_none());
}

#[test]
fn an_incomplete_outcome_is_never_admitted_as_a_product_read() {
    let mut outcome: serde_json::Value = serde_json::from_str(OUTCOME).expect("outcome json");
    outcome["completed"] = serde_json::Value::Bool(false);
    let bytes = serde_json::to_vec(&outcome).expect("outcome bytes");
    let outcome = prepare_direct_product_read(&ProductReadInput {
        outcome_bytes: &bytes,
        review_bytes: Some(REVIEW.as_bytes()),
        authenticated_path: AuthenticatedPathDecision::NotPerformed,
        session_reason_code: "test",
        session_detail: "test",
        durable_batch_id: "batch:pump-product-read:test",
        committed_at: committed_at(),
        committed_monotonic_ns: 1,
        decided_at: COMMITTED_AT,
    });
    let Err(error) = outcome else {
        panic!("an incomplete outcome must be refused");
    };
    assert!(error.to_string().contains("completed fetch outcome"));
}

#[test]
fn the_observed_shape_is_reported_so_a_reviewer_can_author_a_review_from_a_run() {
    let prepared = prepare(None);
    let lines = prepared.observed_shape.iter().collect::<BTreeSet<_>>();
    assert_eq!(lines.len(), prepared.observed_shape.len());
    assert!(prepared.observed_shape.contains(&"$:object".to_owned()));
    assert!(
        prepared
            .observed_shape
            .contains(&"$/creator:string".to_owned())
    );
    assert_eq!(
        joshi_pump_api::fingerprint_of_shape(&prepared.observed_shape),
        prepared
            .decision
            .observed_schema_fingerprint
            .clone()
            .expect("a shaped body has a fingerprint")
    );
}
