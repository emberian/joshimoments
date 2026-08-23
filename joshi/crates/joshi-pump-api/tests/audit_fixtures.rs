//! The audit run over the real retained acquisitions in this crate's fixtures.
//!
//! Every fixture here is a verbatim envelope from a live 2026-08-22 read. The point of these
//! tests is regression: each known failure family that those bytes exhibit must keep being
//! FOUND, by name, with its measured magnitude — because every one of them was originally found
//! by a person, after it had already produced a wrong number. A checked-in body that stops
//! producing its finding means the audit broke, not that the failure healed.

use joshi_pump_api::{
    Acquisition, AcquisitionAuditV1, AuditFinding, AuditSeverity, CheckVerdict, FetchOutcome,
    SuppliedReview, audit_acquisition, audit_fetch_outcome,
};

const DECIDED_AT: &str = "2026-08-23T12:00:00.000000Z";

const CANDLES_OUTCOME: &str = include_str!("../fixtures/candles_live_outcome_v1.json");
const TRADES_OUTCOME: &str = include_str!("../fixtures/trades_live_outcome_v1.json");
const TRADES_TERMINAL: &str = include_str!("../fixtures/trades_terminal_page_v1.json");
const DISCOVERY_OUTCOME: &str = include_str!("../fixtures/discovery_coins_live_outcome_v1.json");
const DISCOVERY_CLAMP_OUTCOME: &str =
    include_str!("../fixtures/discovery_coins_clamp_outcome_v1.json");
const DISCOVERY_EMPTY: &str = include_str!("../fixtures/discovery_coins_empty_page_v1.json");
const COIN_SEARCH_OUTCOME: &str = include_str!("../fixtures/coin_search_live_outcome_v1.json");
const CURRENTLY_LIVE_OUTCOME: &str =
    include_str!("../fixtures/currently_live_live_outcome_v1.json");
const PHANTOM_OUTCOME: &str = include_str!("../fixtures/callout_recent_phantom_v1.json");
const COIN_EXACT_ACQUISITION: &str =
    include_str!("../fixtures/coin_exact_live_acquisition_v1.json");
const DISCOVERY_ROW_REVIEW: &str =
    include_str!("../fixtures/row_projection_discovery_coins_v1.json");
const TRADES_REVIEW: &str = include_str!("../fixtures/schema_review_trades_v1.json");
const COIN_EXACT_REVIEW: &str = include_str!("../fixtures/schema_review_coin_exact_v1.json");

fn attempt(outcome: &str) -> Acquisition {
    let outcome: FetchOutcome = serde_json::from_str(outcome.trim_end()).expect("outcome parses");
    outcome
        .attempts
        .last()
        .cloned()
        .expect("every retained outcome carries its attempt")
}

fn review(source: &str) -> SuppliedReview {
    SuppliedReview::from_slice(source.trim_end().as_bytes()).expect("review artifact parses")
}

fn audit(outcome: &str, supplied: Option<&SuppliedReview>) -> AcquisitionAuditV1 {
    audit_acquisition(&attempt(outcome), supplied, DECIDED_AT).expect("audit runs")
}

fn findings<'a>(audit: &'a AcquisitionAuditV1, check_id: &str) -> Vec<&'a AuditFinding> {
    audit
        .findings
        .iter()
        .filter(|finding| finding.check_id == check_id)
        .collect()
}

fn verdict(audit: &AcquisitionAuditV1, check_id: &str) -> CheckVerdict {
    audit
        .checks
        .iter()
        .find(|check| check.check_id == check_id)
        .map_or_else(
            || panic!("{check_id} must be recorded"),
            |check| check.verdict,
        )
}

/// FAMILY 1, the third instance in one week: 1,997 candle bars retained with nothing anywhere
/// saying which coin they describe. The catalog declares `mint` a public subject for this route
/// and the envelope predates `resolvedPublicPath`, so the audit must say the subject is missing.
#[test]
fn candles_fixture_refinds_the_identity_gap() {
    let audit = audit(CANDLES_OUTCOME, None);
    let gap = findings(&audit, "audit/identity_gap/subject_restated");
    assert_eq!(gap.len(), 1);
    assert_eq!(
        gap[0].severity,
        AuditSeverity::Gap,
        "a candle window names no coin"
    );
    assert!(gap[0].evidence.contains("CandlesNameNoSubject"));
}

/// FAMILY 3 adjacent, closed 2026-08-23: the candle `timestamp` unit is now DECLARED (measured
/// from the retained bytes, mirrored in `normalize::semantics`), so the audit checks the
/// declaration against the bytes instead of hedging an inference — and the declaration holds.
#[test]
fn candles_timestamp_unit_is_declared_and_holds_on_the_bytes() {
    let audit = audit(CANDLES_OUTCOME, None);
    assert_eq!(
        verdict(&audit, "audit/units/declared_clock_plausibility"),
        CheckVerdict::Clear,
        "every bar-open instant is plausible as declared epoch millis"
    );
    assert_eq!(
        verdict(&audit, "audit/units/undeclared_clock_inference"),
        CheckVerdict::Clear,
        "no clock-named field on candles lacks a measured unit any more"
    );
}

/// FAMILY 3, the measured trap itself: every discovery row carries `updated_at` in epoch
/// seconds beside millisecond siblings, and the declared units all hold on the real bytes.
#[test]
fn discovery_fixture_refinds_the_mixed_unit_row() {
    let supplied = review(DISCOVERY_ROW_REVIEW);
    let audit = audit(DISCOVERY_OUTCOME, Some(&supplied));
    assert_eq!(
        verdict(&audit, "audit/units/declared_clock_plausibility"),
        CheckVerdict::Clear,
        "the declared units hold on the live bytes"
    );
    let mixed = findings(&audit, "audit/units/mixed_units_on_row");
    assert_eq!(mixed.len(), 1);
    assert_eq!(mixed[0].severity, AuditSeverity::Hazard);
    assert!(mixed[0].evidence.contains("January 1970"));
}

/// FAMILY 4: both usd market caps are on the live rows and disagree by a measured, ordinary
/// amount — an observation, not an alarm, and never a preference.
#[test]
fn discovery_fixture_measures_the_usd_pair_gap() {
    let audit = audit(DISCOVERY_OUTCOME, None);
    let pair = findings(&audit, "audit/duplicates/usd_market_cap_pair");
    assert_eq!(pair.len(), 1);
    assert_eq!(
        pair[0].severity,
        AuditSeverity::Observation,
        "the live gap is census-ordinary"
    );
    assert!(pair[0].found.contains("relative disagreement"));
}

/// FAMILY 7 visibility: the live discovery rows carry fields nothing extracts. The audit lists
/// them in one observation so a value-bearing name cannot go missing silently again.
#[test]
fn discovery_fixture_lists_retained_but_unread_fields() {
    let audit = audit(DISCOVERY_OUTCOME, None);
    let unread = findings(&audit, "audit/narrowing/retained_but_unread");
    assert_eq!(unread.len(), 1);
    assert!(unread[0].evidence.contains("ath_market_cap"));
}

/// FAMILY 7, the retention side of the clamp: every envelope retained before
/// `resolvedPublicQuery` existed keeps the clamp check UNDECIDABLE with its reason. Decidability
/// arrived with the retention change and must never be backdated onto records that lack the ask.
#[test]
fn pre_retention_envelopes_keep_the_clamp_undecidable_never_assumed() {
    let audit = audit(DISCOVERY_OUTCOME, None);
    let check = audit
        .checks
        .iter()
        .find(|check| check.check_id == "audit/narrowing/limit_clamp")
        .expect("the clamp check runs on every limit-paged route");
    assert_eq!(check.verdict, CheckVerdict::Undecidable);
    assert!(check.detail.contains("resolvedPublicQuery"));
    assert!(
        !audit
            .not_examined
            .iter()
            .any(|entry| entry.check_id == "audit/narrowing/limit_clamp"),
        "the clamp left the structural boundary when retention began restating the ask"
    );
}

/// FAMILY 7 convicted on live bytes, 2026-08-23: the first acquisition retained AFTER the
/// envelope began restating its own ask (`resolvedPublicQuery`). The request said limit=1000;
/// the provider answered exactly 70 rows under HTTP 200 with no warning; the audit names both
/// numbers as a defect. This fixture is the clamp the audit could previously only refuse to
/// examine, caught by a machine because retention changed.
#[test]
fn the_fresh_clamp_acquisition_is_convicted_with_both_numbers() {
    let attempt = attempt(DISCOVERY_CLAMP_OUTCOME);
    assert_eq!(
        attempt
            .resolved_public_query
            .get("limit")
            .map(String::as_str),
        Some("1000"),
        "the envelope restates the requested limit verbatim"
    );
    assert_eq!(
        attempt
            .resolved_public_query
            .get("sort")
            .map(String::as_str),
        Some("created_timestamp"),
        "every declared page-shape parameter travels, not only the limit"
    );
    let supplied = review(DISCOVERY_ROW_REVIEW);
    let audit = audit_acquisition(&attempt, Some(&supplied), DECIDED_AT).expect("audit runs");
    let clamp = findings(&audit, "audit/narrowing/limit_clamp");
    assert_eq!(clamp.len(), 1);
    assert_eq!(clamp[0].severity, AuditSeverity::Defect);
    assert!(clamp[0].expected.contains("1000"));
    assert!(clamp[0].found.contains("70 rows"));
    assert!(clamp[0].found.contains("clamp of 70"));
}

/// FAMILY 6 + FAMILY 8 together on real bytes: the empty discovery page refuses to be read as
/// absence, and the row gate (replayed by the audit) refuses to certify a schema from zero rows.
#[test]
fn empty_discovery_page_refuses_both_ways() {
    let supplied = review(DISCOVERY_ROW_REVIEW);
    let audit = audit(DISCOVERY_EMPTY, Some(&supplied));
    let empty = findings(&audit, "audit/absence/empty_page");
    assert_eq!(empty.len(), 1);
    assert_eq!(empty[0].severity, AuditSeverity::Hazard);
    let replay = findings(&audit, "audit/gate/decision_replay");
    assert_eq!(replay.len(), 1);
    assert!(
        replay[0]
            .found
            .contains("refused_empty_page_has_no_row_to_check")
    );
}

/// FAMILY 6: the trades terminal page is a distinct structural shape meaning past-the-beginning,
/// and the reviewed schema refuses it by design. Both facts must keep being said.
#[test]
fn trades_terminal_page_is_named_and_the_gate_refuses_it() {
    let supplied = review(TRADES_REVIEW);
    let audit = audit(TRADES_TERMINAL, Some(&supplied));
    let terminal = findings(&audit, "audit/absence/trades_terminal_shape");
    assert_eq!(terminal.len(), 1);
    assert!(terminal[0].found.contains("terminal shape"));
    let replay = findings(&audit, "audit/gate/decision_replay");
    assert_eq!(
        replay.len(),
        1,
        "the reviewed schema refuses the terminal shape"
    );
}

/// FAMILY 2 + FAMILY 3, measured across the two swap-api siblings: `timestamp` is an
/// epoch-millis NUMBER on candles and an ISO-8601 STRING on trades — the same name under two
/// encodings. Both units are DECLARED now (2026-08-23), the trades declaration holds on the
/// retained bytes, and the homonym stays flagged on both routes as a declared fact.
#[test]
fn swap_api_timestamp_homonym_is_found_on_both_routes() {
    let trades = audit(TRADES_OUTCOME, None);
    assert_eq!(
        verdict(&trades, "audit/units/declared_clock_plausibility"),
        CheckVerdict::Clear,
        "every trade instant parses as the declared ISO-8601 UTC"
    );
    assert_eq!(
        verdict(&trades, "audit/units/undeclared_clock_inference"),
        CheckVerdict::Clear,
        "no clock-named field on trades lacks a measured unit any more"
    );
    let homonym = findings(&trades, "audit/homonyms/cross_route_meaning");
    assert!(
        homonym
            .iter()
            .any(|finding| finding.locus.field.as_deref() == Some("timestamp")),
        "trades must flag the timestamp homonym"
    );
    let candles = audit(CANDLES_OUTCOME, None);
    let homonym = findings(&candles, "audit/homonyms/cross_route_meaning");
    assert!(
        homonym
            .iter()
            .any(|finding| finding.locus.field.as_deref() == Some("timestamp")),
        "candles must flag the same homonym from its side"
    );
}

/// FAMILY 12 residue measurable from one source: the pool-price and fill-price legs of the
/// retained trades page differ by a measured wedge, which is the venue fee stated per row.
#[test]
fn trades_fixture_measures_the_leg_wedge() {
    let audit = audit(TRADES_OUTCOME, None);
    let wedge = findings(&audit, "audit/leg/fee_wedge");
    assert_eq!(wedge.len(), 1);
    assert!(wedge[0].found.contains("50 row(s)"));
    // FAMILY 1 again: a trades page names no mint either.
    let gap = findings(&audit, "audit/identity_gap/subject_restated");
    assert_eq!(gap.len(), 1);
    assert_eq!(gap[0].severity, AuditSeverity::Gap);
}

/// FAMILY 6 at the outcome level: the phantom-callout outcome is incomplete with no recorded
/// coverage gap — a silence — and its 400 body makes every content check undecidable, not green.
#[test]
fn phantom_callout_outcome_is_a_silence_and_never_green() {
    let outcome: FetchOutcome =
        serde_json::from_str(PHANTOM_OUTCOME.trim_end()).expect("outcome parses");
    let audit = audit_fetch_outcome(&outcome, &[], DECIDED_AT).expect("audit runs");
    assert!(
        audit
            .outcome_findings
            .iter()
            .any(|finding| finding.found.contains("no recorded coverage gap")),
        "a failed cycle must be a durable gap, never a silence"
    );
    let attempt = &audit.attempt_audits[0];
    let undecidable = attempt
        .checks
        .iter()
        .filter(|check| check.verdict == CheckVerdict::Undecidable)
        .count();
    assert!(
        undecidable >= 10,
        "content checks over a 400 body must refuse, not pass; got {undecidable}"
    );
}

/// The promoted path stays quiet where it should: `coin_exact` bytes under their reviewed schema
/// replay to promotion, and the subject corroboration is honestly undecidable because the
/// envelope predates `resolvedPublicPath`.
#[test]
fn coin_exact_promotes_and_names_its_missing_corroboration() {
    let acquisition: Acquisition =
        serde_json::from_str(COIN_EXACT_ACQUISITION.trim_end()).expect("acquisition parses");
    let supplied = review(COIN_EXACT_REVIEW);
    let audit = audit_acquisition(&acquisition, Some(&supplied), DECIDED_AT).expect("audit runs");
    assert_eq!(
        verdict(&audit, "audit/gate/decision_replay"),
        CheckVerdict::Clear
    );
    assert_eq!(
        verdict(&audit, "audit/identity_gap/subject_corroborated"),
        CheckVerdict::Undecidable,
        "no request-side mint was retained, and the audit must say so instead of passing"
    );
}

/// Every audited fixture names the checks it structurally could not run. An audit that hides
/// its boundary is the failure it exists to catch.
#[test]
fn every_fixture_audit_names_its_not_examined_boundary() {
    for outcome in [
        CANDLES_OUTCOME,
        TRADES_OUTCOME,
        DISCOVERY_OUTCOME,
        COIN_SEARCH_OUTCOME,
        CURRENTLY_LIVE_OUTCOME,
    ] {
        let audit = audit(outcome, None);
        assert!(
            audit
                .not_examined
                .iter()
                .any(|entry| entry.check_id == "audit/selection/recall"),
            "route {} must name the recall boundary",
            audit.route_id
        );
    }
}
