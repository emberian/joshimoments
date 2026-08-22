//! How a backwards trade walk reads pages, and how it stops.
//!
//! The terminal fixture is the real thing rather than a guess: it is a verbatim `FetchOutcome`
//! from 2026-08-22 for a seek past the beginning of a mint's retained history. Its shape had
//! never been observed when the trades schema was reviewed, and the review said so. It is checked
//! in here so the shape a person has to review is a file rather than a memory.

use std::path::Path;
use std::time::Duration;

use joshi_domain::{CommitSeq, StableString, UtcTimestamp};
use joshi_pump_adapter::{
    Adjacency, PageFacts, ProductReadInput, TRADES_BACKFILL_WALK_V1, TradesBackfillPageV1,
    TradesBackfillWalkV1, WalkStop, backfill, page_record, prepare_trades_backfill_page,
    requests_per_hour_of_tape, span_millis,
};
use joshi_pump_api::{
    Acquisition, AuthenticatedPathDecision, FetchOutcome, SchemaReviewV1, SchemaTrustOutcome,
    decide_schema_trust,
};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};

const TERMINAL: &str = include_str!("../../joshi-pump-api/fixtures/trades_terminal_page_v1.json");
const TRADES_OUTCOME: &str =
    include_str!("../../joshi-pump-api/fixtures/trades_live_outcome_v1.json");
const TRADES_REVIEW: &str =
    include_str!("../../joshi-pump-api/fixtures/schema_review_trades_v1.json");
const COMMITTED_AT: &str = "2026-08-22T02:30:00.000000Z";

/// The exact structural fingerprint of a terminal trade page, observed 2026-08-22.
///
/// It is pinned as a constant so that a person reviewing this shape is reviewing the same bytes
/// this test saw, and so that a later provider change to the terminal shape fails here loudly
/// instead of quietly widening what a walk will accept as "the end".
const TERMINAL_FINGERPRINT: &str =
    "sha256:07b9bc265d028307284a0c37bcb2e570b029f811050cadba36aec59a4092eeb5";

fn acquisition(outcome: &str) -> Acquisition {
    let outcome: FetchOutcome = serde_json::from_str(outcome.trim_end()).expect("outcome parses");
    outcome
        .attempts
        .last()
        .cloned()
        .expect("outcome has an attempt")
}

fn body(acquisition: &Acquisition) -> Vec<u8> {
    acquisition.body.exact_bytes().expect("exact bytes")
}

fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 0,
        busy_timeout: Duration::from_secs(5),
        catalog_id: StableString::new("joshi-pump-backfill-test").expect("catalog id"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    }
}

fn facts(outcome: &str) -> PageFacts {
    PageFacts::from_promoted_bytes(&body(&acquisition(outcome))).expect("page facts")
}

fn walk(stop: WalkStop, pages: Vec<TradesBackfillPageV1>) -> TradesBackfillWalkV1 {
    let promoted = pages
        .iter()
        .filter(|page| page.schema_trust_outcome == "promoted")
        .count();
    TradesBackfillWalkV1 {
        contract: TRADES_BACKFILL_WALK_V1.to_owned(),
        schema_version: "1".to_owned(),
        walk_id: "walk:pump-trades:test".to_owned(),
        route_id: "trades".to_owned(),
        catalog_version: joshi_pump_api::ROUTE_CATALOG.to_owned(),
        subject_kind: "spl_mint".to_owned(),
        subject: "HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump".to_owned(),
        page_limit: "100".to_owned(),
        started_at: COMMITTED_AT.to_owned(),
        ended_at: COMMITTED_AT.to_owned(),
        requests_used: pages.len().to_string(),
        request_budget: "8".to_owned(),
        elapsed_ms: "1200".to_owned(),
        wall_budget_ms: "120000".to_owned(),
        pages_attempted: pages.len().to_string(),
        pages_promoted: promoted.to_string(),
        rows_retained: "0".to_owned(),
        newest_event_time: None,
        oldest_event_time: None,
        covered_span_ms: None,
        requests_per_hour_of_tape: None,
        stop,
        stop_detail: "test".to_owned(),
        unreviewed_schema_fingerprint: None,
        pages,
    }
}

#[test]
fn the_terminal_page_is_a_shape_no_review_has_promoted() {
    let acquisition = acquisition(TERMINAL);
    assert_eq!(acquisition.http_status, Some(200));
    assert_eq!(
        body(&acquisition),
        br#"{"trades":[],"pagination":{"hasMore":false,"limit":3}}"#,
        "the end of history is an empty array and a pagination object with no cursor at all"
    );
    let review = SchemaReviewV1::from_slice(TRADES_REVIEW.as_bytes()).expect("review");
    let decision = decide_schema_trust(&acquisition, Some(&review), COMMITTED_AT).expect("decide");
    assert_eq!(decision.outcome, SchemaTrustOutcome::Refused);
    assert_eq!(
        decision.reason_code,
        "refused_observed_fingerprint_not_reviewed"
    );
    assert_eq!(
        decision.observed_schema_fingerprint.as_deref(),
        Some(TERMINAL_FINGERPRINT),
        "the fingerprint a human has to review must be exactly this"
    );
    // The reviewed rationale predicted a null cursor. It is absent instead, which is why the
    // prediction was written as a prediction and the gate was left to decide.
    assert_ne!(
        decision.observed_schema_fingerprint.as_deref(),
        Some(review.schema_fingerprint.as_str())
    );
}

#[test]
fn reaching_the_end_of_history_stops_the_walk_for_a_person_rather_than_widening_anything() {
    let stop = backfill::classify_stop(
        backfill::PageVerdict {
            promoted: false,
            http_status: Some(200),
            trust_reason: "refused_observed_fingerprint_not_reviewed",
            facts: None,
            adjacency: Adjacency::NotComparable,
            horizon_reached: false,
        },
        backfill::WalkBudgets {
            pages_so_far: 1,
            max_pages: 64,
            requests_used: 1,
            request_budget: 8,
            elapsed_ms: 10,
            wall_budget_ms: 120_000,
        },
    );
    assert_eq!(stop, Some(WalkStop::SchemaRefusedPendingReview));
    assert!(
        WalkStop::SchemaRefusedPendingReview.needs_review(),
        "an unreviewed shape must be flagged for a person, not absorbed by the walker"
    );
    assert!(WalkStop::PageOverlappedPrevious.needs_review());
    assert!(!WalkStop::RequestBudgetExhausted.needs_review());
}

#[test]
fn an_untrusted_page_still_reaches_the_store_with_the_reason_the_walk_stopped() {
    let root = tempfile::tempdir().expect("temp root");
    let record = walk(
        WalkStop::SchemaRefusedPendingReview,
        vec![page_record(
            0,
            &acquisition(TERMINAL),
            &decide_schema_trust(
                &acquisition(TERMINAL),
                Some(&SchemaReviewV1::from_slice(TRADES_REVIEW.as_bytes()).expect("review")),
                COMMITTED_AT,
            )
            .expect("decide"),
            None,
            Adjacency::NotComparable,
            None,
        )],
    );
    let prepared = prepare_trades_backfill_page(
        &ProductReadInput {
            outcome_bytes: TERMINAL.trim_end().as_bytes(),
            review_bytes: Some(TRADES_REVIEW.as_bytes()),
            authenticated_path: AuthenticatedPathDecision::NotPerformed,
            session_reason_code: "no_documented_authenticated_get_read_route_for_present_credential",
            session_detail: "undocumented public product route, no session provider configured",
            durable_batch_id: "batch:pump-trades-backfill:terminal",
            committed_at: COMMITTED_AT.parse().expect("instant"),
            committed_monotonic_ns: 1,
            decided_at: COMMITTED_AT,
        },
        Some(&record),
    )
    .expect("a refused page is still admissible; a walk must be able to record why it stopped");
    assert_eq!(prepared.decision.outcome, SchemaTrustOutcome::Refused);

    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
    store
        .migrate(COMMITTED_AT.parse::<UtcTimestamp>().expect("instant"))
        .expect("migrate");
    let receipt = prepared
        .prepared
        .admission_batch()
        .commit(&mut store)
        .expect("commit");
    assert_eq!(
        receipt.admitted.assertions, "3",
        "the trust refusal, the credential-path note, and the walk record"
    );
    drop(store);

    let reopened =
        SqliteStore::open(config(root.path()), StoreMode::ReadOnly).expect("reopen store");
    let verification = reopened.verify(VerifyDepth::Full).expect("verify");
    assert_eq!(verification.integrity, "ok");
    let rows = reopened
        .effective_assertions_as_known(&record.semantic_key(), verification.max_commit_seq)
        .expect("read walk record");
    assert_eq!(
        rows.len(),
        1,
        "the reason the walk stopped survives a restart"
    );
    let stored = rows[0]
        .value
        .get("walk")
        .expect("assertion carries the walk");
    assert_eq!(
        stored.get("stop").and_then(serde_json::Value::as_str),
        Some("schema_refused_pending_review")
    );
    let decoded: TradesBackfillWalkV1 =
        serde_json::from_value(stored.clone()).expect("walk decodes");
    assert_eq!(decoded, record);
    let _: CommitSeq = verification.max_commit_seq;
}

#[test]
fn two_real_pages_are_strictly_older_with_no_overlap_and_the_same_page_is_not() {
    let page = facts(TRADES_OUTCOME);
    assert_eq!(page.rows, 50);
    assert!(
        page.cursor_matches_last_row,
        "the cursor is the last row's key"
    );
    assert_eq!(page.has_more, Some(true));
    assert_eq!(page.adjacency_to(None), Adjacency::FirstPage);
    assert_eq!(
        page.adjacency_to(Some(&page)),
        Adjacency::Overlapped,
        "a page compared against itself shares every row, which is the failure the walk watches for"
    );
    let terminal = PageFacts::from_promoted_bytes(&body(&acquisition(TERMINAL)))
        .expect("an empty page still parses");
    assert_eq!(terminal.rows, 0);
    assert_eq!(terminal.next_cursor, None);
    assert_eq!(terminal.has_more, Some(false));
    assert_eq!(terminal.adjacency_to(Some(&page)), Adjacency::NotComparable);
}

#[test]
fn a_walk_record_whose_arithmetic_does_not_close_is_refused() {
    let good = walk(
        WalkStop::RequestBudgetExhausted,
        vec![page_record(
            0,
            &acquisition(TRADES_OUTCOME),
            &decide_schema_trust(
                &acquisition(TRADES_OUTCOME),
                Some(&SchemaReviewV1::from_slice(TRADES_REVIEW.as_bytes()).expect("review")),
                COMMITTED_AT,
            )
            .expect("decide"),
            Some(&facts(TRADES_OUTCOME)),
            Adjacency::FirstPage,
            None,
        )],
    );
    good.validate().expect("a consistent record validates");
    let mut lying = good.clone();
    lying.pages_promoted = "7".to_owned();
    assert!(lying.validate().is_err());
    let mut empty = good.clone();
    empty.pages.clear();
    empty.pages_attempted = "0".to_owned();
    empty.pages_promoted = "0".to_owned();
    assert!(
        empty.validate().is_err(),
        "a walk must name at least the page it stopped on"
    );
}

#[test]
fn the_cost_of_tape_is_requests_divided_by_the_hours_it_covered() {
    // The measured Bert walk: eight requests reached back seven hours and seven minutes.
    let span = span_millis("2026-08-22T01:53:35.000Z", "2026-08-21T18:46:13.000Z").expect("span");
    assert_eq!(span, 25_642_000);
    assert_eq!(requests_per_hour_of_tape(8, span).as_deref(), Some("1.123"));
    // A page limit of 100 makes the cost a pure function of the trade rate, so a coin printing
    // 86 trades a minute costs about fifty times more per hour of tape than one printing 1.9.
    assert_eq!(
        requests_per_hour_of_tape(1, 70_000).as_deref(),
        Some("51.429")
    );
    assert_eq!(requests_per_hour_of_tape(8, 0), None);
}

#[test]
fn budgets_only_stop_a_walk_after_every_reason_that_means_something_worse() {
    let page = facts(TRADES_OUTCOME);
    let verdict = |adjacency| backfill::PageVerdict {
        promoted: true,
        http_status: Some(200),
        trust_reason: "promoted_reviewed_schema_fingerprint_match",
        facts: Some(&page),
        adjacency,
        horizon_reached: false,
    };
    let spent = backfill::WalkBudgets {
        pages_so_far: 64,
        max_pages: 64,
        requests_used: 8,
        request_budget: 8,
        elapsed_ms: 999_999,
        wall_budget_ms: 1_000,
    };
    // Everything is exhausted at once, and an overlap still wins: a budget stop says "there is
    // more and we chose not to fetch it", which would be the wrong thing on disk here.
    assert_eq!(
        backfill::classify_stop(verdict(Adjacency::Overlapped), spent),
        Some(WalkStop::PageOverlappedPrevious)
    );
    assert_eq!(
        backfill::classify_stop(verdict(Adjacency::StrictlyOlderNoOverlap), spent),
        Some(WalkStop::PageBudgetExhausted)
    );
    let room = backfill::WalkBudgets {
        pages_so_far: 1,
        max_pages: 64,
        requests_used: 1,
        request_budget: 8,
        elapsed_ms: 10,
        wall_budget_ms: 120_000,
    };
    assert_eq!(
        backfill::classify_stop(verdict(Adjacency::StrictlyOlderNoOverlap), room),
        None,
        "a healthy page under budget does not stop the walk"
    );
}
