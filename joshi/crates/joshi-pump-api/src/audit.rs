//! A mechanical audit over one retained acquisition, for the failure families a person kept
//! finding by hand.
//!
//! Over one session this project accumulated a dozen distinct source-level failure families —
//! a candle window that names no coin, `updated_at` in epoch seconds among millisecond siblings,
//! two market caps asserting the same quantity and disagreeing, an empty page indistinguishable
//! from absence — each found by a person, each after it had already produced a wrong number.
//! This module turns the ones that are DECIDABLE FROM A RETAINED ACQUISITION into checks, so the
//! next instance is caught by a machine instead of at 3am.
//!
//! The triage is deliberate and the boundary is stated per check:
//!
//!   * Some families are decidable from the retained envelope plus the pinned catalog alone
//!     (identity gaps, clock coherence, empty pages, zero-row container misreads).
//!   * Some are decidable only against a DECLARED expectation — a unit table, a duplicate-pair
//!     registry, a homonym registry, a gate-governance table. Those declarations live in this
//!     file, each citing the measurement it came from, so the check re-finds a known failure
//!     rather than inventing an opinion.
//!   * Some are not decidable from one acquisition at all — recall of a selection convention,
//!     whether a provider flag reflects chain state, which price leg another source quotes.
//!     Those are NAMED in `not_examined` with their reason, because an audit that silently
//!     passes what it could not examine is the exact failure it exists to catch.
//!
//! The vocabulary and refusal idiom follow [`crate::row_projection`]: every outcome is typed and
//! named, never a bare bool; a check that cannot decide says `undecidable` with its reason; and
//! every finding carries its locus (route, pointer, field, row) plus the evidence it compared
//! against. Findings are evidence, not opinions.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use time::OffsetDateTime;

use crate::ROUTE_CATALOG;
use crate::catalog::{PaginationKind, RouteId, RouteSpec};
use crate::client::sha256;
use crate::model::{Acquisition, BodyCapture, FetchOutcome};
use crate::normalize::{extracted_fields, records, reject_duplicate_keys};
use crate::row_projection::RowProjectionReviewV1;
use crate::trust::{SchemaReviewV1, SchemaTrustOutcome, TrustError};

pub const ACQUISITION_AUDIT_V1: &str = "joshi.pump_api.acquisition_audit.v1";
pub const OUTCOME_AUDIT_V1: &str = "joshi.pump_api.outcome_audit.v1";

/// Instants before this are implausible for any Pump datum: the provider did not exist in 2019.
const PLAUSIBLE_EPOCH_FLOOR_SECONDS: i64 = 1_577_836_800; // 2020-01-01T00:00:00Z
/// A provider clock may run ahead of ours by transit and skew, not by more than a week.
const PLAUSIBLE_FUTURE_SLACK_SECONDS: i64 = 7 * 86_400;
/// Transport clock disagreement worth surfacing. The `date` header has one-second resolution.
const HEADER_SKEW_HAZARD_SECONDS: i64 = 30;
/// The census over 140 rows measured the usd market-cap pair disagreeing by a median of 0.10%
/// and at most 0.31%; one later coin disagreed by nine percentage points and that was an alarm.
/// The alarm line sits well above the measured ordinary band and well below the observed alarm.
const USD_PAIR_ALARM_RELATIVE: f64 = 0.02;
/// `multiple` reconciled with `maxPriceSol/calloutPrice` as 4.5 vs 4.548 (~1.1%) when measured
/// live 2026-08-22, so the provider rounds. Two percent tolerates the rounding and still catches
/// a headline that is not derivable from its own row.
const MULTIPLE_RECONCILE_TOLERANCE: f64 = 0.02;
/// Cap on names listed inside one aggregate finding, so a finding stays readable.
const MAX_NAMES_PER_FINDING: usize = 24;

/// The failure family a finding belongs to. Eleven of the twelve session families appear here
/// (selection/recall is only ever `not_examined`); `record_integrity` is the audit's own
/// prerequisite family — an audit must first establish that what it examines is what was
/// retained, and a failure there makes the provider-facing checks undecidable rather than green.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditFamily {
    RecordIntegrity,
    IdentityGap,
    SemanticDriftAcrossRoutes,
    UnitMismatch,
    DisagreeingDuplicates,
    StalenessThatLooksLive,
    AbsenceThatLooksLikeData,
    SilentNarrowing,
    GateMeasuresContentNotSchema,
    RequiredCardinalityForcesInvention,
    SelectionRecallGap,
    ClockGaps,
    LegReferenceMismatch,
}

/// What a finding costs a reader who misses it.
///
/// * `defect` — the record, or any straightforward reading of it, yields a wrong number.
/// * `gap` — something the record needs in order to be usable is absent (a subject, a clock,
///   a coverage statement).
/// * `hazard` — the bytes are right and will be misread without the named care.
/// * `observation` — a measured fact retained for the record; no error is implied.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditSeverity {
    Defect,
    Gap,
    Hazard,
    Observation,
}

/// Where in the retained material a finding points.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditLocus {
    pub route_id: String,
    /// JSON pointer into the retained body (`$` is the document root), or a named envelope
    /// location such as `envelope:resolvedPublicPath` when the locus is not in the body.
    pub pointer: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub field: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub row_ordinal: Option<String>,
}

/// One typed finding: the family, the exact locus, what was expected, what was found, and the
/// evidence the expectation rests on. Never a bare bool.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditFinding {
    pub family: AuditFamily,
    pub check_id: String,
    pub severity: AuditSeverity,
    pub locus: AuditLocus,
    pub expected: String,
    pub found: String,
    pub evidence: String,
}

/// Verdict of one check over one acquisition.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CheckVerdict {
    /// The check ran over real material and found nothing to report.
    Clear,
    /// The check ran and emitted at least one finding.
    Findings,
    /// The check could not decide, for the stated reason. Never a pass.
    Undecidable,
}

/// One check that ran (or refused to), with its verdict. Every check the audit knows for the
/// route appears exactly once, so a reader can tell "clear" from "never looked".
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditCheckRecord {
    pub check_id: String,
    pub family: AuditFamily,
    pub verdict: CheckVerdict,
    pub detail: String,
}

/// A named check this audit structurally cannot run on this material, with the reason. These are
/// the honest boundary of the instrument: cross-source comparisons, chain truth, and quantities
/// the retention shape itself discards.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NotExaminedV1 {
    pub check_id: String,
    pub family: AuditFamily,
    pub reason: String,
}

/// The audit over one retained acquisition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AcquisitionAuditV1 {
    pub contract: String,
    pub schema_version: String,
    pub audit_id: String,
    pub route_id: String,
    pub acquisition_id: String,
    pub catalog_version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub body_blob_id: Option<String>,
    pub decided_at: String,
    pub checks: Vec<AuditCheckRecord>,
    pub findings: Vec<AuditFinding>,
    pub not_examined: Vec<NotExaminedV1>,
}

/// The audit over one retained fetch outcome: per-attempt audits plus the outcome-level
/// absence accounting (a failed cycle must be a durable gap, never a silence).
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeAuditV1 {
    pub contract: String,
    pub schema_version: String,
    pub audit_id: String,
    pub request_group_id: String,
    pub decided_at: String,
    pub outcome_checks: Vec<AuditCheckRecord>,
    pub outcome_findings: Vec<AuditFinding>,
    pub not_examined: Vec<NotExaminedV1>,
    pub attempt_audits: Vec<AcquisitionAuditV1>,
}

/// A reviewed artifact supplied to the audit: either kind, sniffed by contract.
#[derive(Clone, Debug)]
pub enum SuppliedReview {
    Document(SchemaReviewV1),
    Rows(RowProjectionReviewV1),
}

impl SuppliedReview {
    #[must_use]
    pub fn route_id(&self) -> &str {
        match self {
            Self::Document(review) => &review.route_id,
            Self::Rows(review) => &review.route_id,
        }
    }

    #[must_use]
    pub fn review_id(&self) -> &str {
        match self {
            Self::Document(review) => &review.review_id,
            Self::Rows(review) => &review.review_id,
        }
    }

    /// Strictly decode a review artifact of either kind, deciding by its `contract` line.
    ///
    /// # Errors
    ///
    /// Returns an error for unreadable JSON, an unknown contract, or an artifact that fails its
    /// own kind's strict decoding.
    pub fn from_slice(bytes: &[u8]) -> Result<Self, TrustError> {
        #[derive(Deserialize)]
        struct ContractOnly {
            contract: String,
        }
        let head: ContractOnly = serde_json::from_slice(bytes)?;
        match head.contract.as_str() {
            crate::trust::SCHEMA_REVIEW_V1 => SchemaReviewV1::from_slice(bytes).map(Self::Document),
            crate::row_projection::ROW_PROJECTION_REVIEW_V1 => {
                RowProjectionReviewV1::from_slice(bytes).map(Self::Rows)
            }
            _ => Err(TrustError::ReviewContract),
        }
    }
}

/// Which gate has been MEASURED to govern a route's trust decision.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum GateKind {
    /// One digest over the whole document. Governs single-record and homogeneous-row routes.
    DocumentFingerprint,
    /// Required + closed-optional leaves per row. Governs heterogeneous collection feeds, where
    /// eleven reads of `/coins` produced eight distinct whole-document fingerprints (2026-08-22).
    RowProjection,
    /// Nothing has ever measured which gate can govern this route.
    Unmeasured,
}

fn governing_gate(route: RouteId) -> GateKind {
    match route {
        // "`decide_schema_trust` ... is what governs `coin_exact`, `candles` and `trades`"
        // (row_projection module doc); sol_price is a single scalar record.
        RouteId::CoinExact | RouteId::SolPrice | RouteId::Candles | RouteId::Trades => {
            GateKind::DocumentFingerprint
        }
        RouteId::DiscoveryCoins
        | RouteId::CurrentlyLive
        | RouteId::CoinSearch
        | RouteId::CalloutTop
        | RouteId::CalloutByUser
        | RouteId::CalloutLeaderboard
        // Reviewed 2026-08-24 from live material: heterogeneous rows on both (movers rows carry
        // optional recommendation/deploy keys; community rows have nullable media/mention
        // leaves), so the row projection is the gate exactly as on the discovery feeds.
        | RouteId::BoardMovers
        | RouteId::CommunityCallouts => GateKind::RowProjection,
        _ => GateKind::Unmeasured,
    }
}

/// Whether the response BODY of this route restates its own subject. A `candles` window and a
/// trades page are about exactly one mint and never say which; a `coins-v2/{mint}` body carries
/// `mint`. This is what decides how loud an absent `resolvedPublicPath` is.
fn body_names_subject(route: RouteId) -> bool {
    !matches!(route, RouteId::Candles | RouteId::Trades)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ClockUnit {
    EpochMillis,
    EpochSeconds,
    Iso8601Utc,
}

impl ClockUnit {
    fn name(self) -> &'static str {
        match self {
            Self::EpochMillis => "epoch_millis",
            Self::EpochSeconds => "epoch_seconds",
            Self::Iso8601Utc => "iso8601_utc",
        }
    }
}

/// Clock fields whose unit has been MEASURED, per route family, with the measurement cited.
/// The declarations mirror [`crate::normalize`]'s semantics table; a field absent here has an
/// unmeasured unit and is handled by inference-with-its-name-said-out-loud, never by guessing.
fn declared_clocks(route: RouteId) -> &'static [(&'static str, ClockUnit, &'static str)] {
    match route {
        RouteId::CoinExact
        | RouteId::DiscoveryCoins
        | RouteId::CurrentlyLive
        | RouteId::CoinSearch => &[
            (
                "created_timestamp",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on the coin routes",
            ),
            (
                "last_trade_timestamp",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on the coin routes",
            ),
            (
                "ath_market_cap_timestamp",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on the coin routes",
            ),
            (
                "king_of_the_hill_timestamp",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on the coin routes",
            ),
            (
                "last_reply",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on the coin routes",
            ),
            (
                "thumbnail_updated_at",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on the coin routes",
            ),
            (
                "updated_at",
                ClockUnit::EpochSeconds,
                "measured 2026-08-22: epoch SECONDS while every sibling clock on the row is \
                 epoch milliseconds; read as milliseconds it lands in January 1970 and looks \
                 like a stale record instead of a units bug",
            ),
        ],
        RouteId::CalloutTop | RouteId::CalloutByUser => &[
            (
                "createdAt",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on both live callout routes",
            ),
            (
                "peakTimestamp",
                ClockUnit::EpochMillis,
                "measured 2026-08-22 on /callout/top",
            ),
            (
                "maxMultiplierAt",
                ClockUnit::Iso8601Utc,
                "measured 2026-08-22: an ISO-8601 string on the same row as an epoch-millis \
                 createdAt",
            ),
        ],
        RouteId::Candles => &[(
            "timestamp",
            ClockUnit::EpochMillis,
            "measured 2026-08-23 from the retained live body: a JSON number of epoch \
             milliseconds (bar open time), while the sibling trades route carries the same \
             name as an ISO-8601 string; declared in normalize::semantics",
        )],
        RouteId::Trades => &[(
            "timestamp",
            ClockUnit::Iso8601Utc,
            "measured 2026-08-23 from the retained live body: an ISO-8601 UTC string (trade \
             time), while the sibling candles route carries the same name as an epoch-millis \
             number; declared in normalize::semantics",
        )],
        RouteId::CommunityCallouts => &[
            (
                "createdAt",
                ClockUnit::Iso8601Utc,
                "measured 2026-08-24 on the real coin-communities host: ISO-8601 UTC with \
                 MICROSECONDS, while /callout/top and /callout/list state the same event in \
                 epoch milliseconds — two callout hosts, two encodings for one occurrence",
            ),
            (
                "maxMultiplierAt",
                ClockUnit::Iso8601Utc,
                "measured 2026-08-24: ISO-8601 UTC with microseconds, nullable",
            ),
        ],
        _ => &[],
    }
}

/// Clock-named fields whose unit NOTHING has measured. The audit will state which single unit
/// their magnitude admits — an inference said as an inference — or refuse to decide.
fn undeclared_clock_suspects(route: RouteId) -> &'static [&'static str] {
    match route {
        RouteId::SolPrice => &["asOfTimestamp"],
        RouteId::BalanceSummary | RouteId::BalanceTokens => &["updatedAt"],
        // community_callouts left this list 2026-08-24: its clocks are measured and declared
        // above. The messages sibling has still never been called by this collector.
        RouteId::CommunityMessages => &["createdAt"],
        RouteId::InMemoryCoin => &["creationTime", "graduationDate", "lastRecommendedAt"],
        _ => &[],
    }
}

/// Field names that mean DIFFERENT quantities on different routes, with each meaning and the
/// evidence. A reader who joins on the shared name silently mixes the quantities.
struct Homonym {
    field: &'static str,
    meanings: &'static [(RouteId, &'static str)],
    evidence: &'static str,
    /// How silently the mix-up bites: a quantity swap is silent (hazard); an encoding swap
    /// fails loudly at parse time (observation).
    severity: AuditSeverity,
}

const HOMONYMS: &[Homonym] = &[
    Homonym {
        field: "multiple",
        meanings: &[
            (
                RouteId::CalloutTop,
                "the PEAK multiple as of the read (reconciles with maxPriceSol/calloutPrice)",
            ),
            (
                RouteId::CalloutByUser,
                "the CURRENT multiple at the read; the peak on this route is maxMultiplier",
            ),
        ],
        evidence: "measured 2026-08-22: same name, different quantity on the two live callout \
                   routes; mixing them silently conflates peak with current",
        severity: AuditSeverity::Hazard,
    },
    Homonym {
        field: "createdAt",
        meanings: &[
            (
                RouteId::CalloutTop,
                "measured epoch milliseconds (occurrence time)",
            ),
            (
                RouteId::CalloutByUser,
                "measured epoch milliseconds (occurrence time)",
            ),
            (
                RouteId::CommunityMessages,
                "unit never measured; nothing has ever called this route",
            ),
            (
                RouteId::CommunityCallouts,
                "measured 2026-08-24: ISO-8601 UTC with MICROSECONDS (occurrence time) — the \
                 same event family the frontend-api callout routes state in epoch millis",
            ),
        ],
        evidence: "the frontend-api callout unit was measured 2026-08-22 and the \
                   coin-communities unit 2026-08-24: one event family, two hosts, two \
                   encodings, so a join on this name must normalise out loud; the messages \
                   route remains uncalled",
        severity: AuditSeverity::Observation,
    },
    Homonym {
        field: "timestamp",
        meanings: &[
            (
                RouteId::Candles,
                "an epoch-milliseconds JSON number (bar open time)",
            ),
            (RouteId::Trades, "an ISO-8601 UTC string (trade time)"),
        ],
        evidence: "measured 2026-08-23 from the retained live bodies: the two swap-api routes \
                   carry the SAME field name under different encodings and units; a reader \
                   joining them by name fails loudly at best and silently at worst",
        severity: AuditSeverity::Observation,
    },
];

/// One parsed row: ordinal plus top-level field tokens (exact JSON text, trimmed).
struct Row {
    ordinal: usize,
    fields: BTreeMap<String, String>,
}

/// What the integrity chain managed to establish about the body.
struct ParsedBody {
    raw: Box<RawValue>,
    rows: Vec<Row>,
}

/// Why the content checks cannot run, when they cannot.
#[derive(Clone, Copy)]
enum ContentBlock {
    NonExactBody,
    BodyIdentityMismatch,
    NonSuccessStatus,
    UnparseableJson,
    ContainerUnreadable,
}

impl ContentBlock {
    fn reason(self) -> &'static str {
        match self {
            Self::NonExactBody => "the retained body is not exact, so there is nothing to examine",
            Self::BodyIdentityMismatch => {
                "the retained bytes do not match their declared identity, so nothing derived \
                 from them can be trusted enough to examine"
            }
            Self::NonSuccessStatus => {
                "a non-2xx body is a provider error page, not product content; content checks \
                 do not apply to it"
            }
            Self::UnparseableJson => {
                "the body is not well-formed JSON, so it has no fields to examine"
            }
            Self::ContainerUnreadable => {
                "the reviewed container for this route did not yield rows from these bytes"
            }
        }
    }
}

struct Auditor {
    route: String,
    checks: Vec<AuditCheckRecord>,
    findings: Vec<AuditFinding>,
}

impl Auditor {
    fn clear(&mut self, check_id: &str, family: AuditFamily, detail: &str) {
        self.checks.push(AuditCheckRecord {
            check_id: check_id.to_owned(),
            family,
            verdict: CheckVerdict::Clear,
            detail: detail.to_owned(),
        });
    }

    fn undecidable(&mut self, check_id: &str, family: AuditFamily, reason: &str) {
        self.checks.push(AuditCheckRecord {
            check_id: check_id.to_owned(),
            family,
            verdict: CheckVerdict::Undecidable,
            detail: reason.to_owned(),
        });
    }

    fn blocked(&mut self, check_id: &str, family: AuditFamily, block: ContentBlock) {
        self.undecidable(check_id, family, block.reason());
    }

    /// Record a check that emitted `findings`, and the findings themselves.
    fn found(&mut self, check_id: &str, family: AuditFamily, findings: Vec<AuditFinding>) {
        self.checks.push(AuditCheckRecord {
            check_id: check_id.to_owned(),
            family,
            verdict: CheckVerdict::Findings,
            detail: format!("{} finding(s)", findings.len()),
        });
        self.findings.extend(findings);
    }

    /// Record either a clear verdict or the findings, depending on whether any were produced.
    fn decide(
        &mut self,
        check_id: &str,
        family: AuditFamily,
        findings: Vec<AuditFinding>,
        clear_detail: &str,
    ) {
        if findings.is_empty() {
            self.clear(check_id, family, clear_detail);
        } else {
            self.found(check_id, family, findings);
        }
    }

    #[allow(clippy::too_many_arguments)] // A finding's fields are its schema; a builder would hide them.
    fn finding(
        &self,
        family: AuditFamily,
        check_id: &str,
        severity: AuditSeverity,
        pointer: &str,
        field: Option<&str>,
        row_ordinal: Option<usize>,
        expected: &str,
        found: &str,
        evidence: &str,
    ) -> AuditFinding {
        AuditFinding {
            family,
            check_id: check_id.to_owned(),
            severity,
            locus: AuditLocus {
                route_id: self.route.clone(),
                pointer: pointer.to_owned(),
                field: field.map(str::to_owned),
                row_ordinal: row_ordinal.map(|value| value.to_string()),
            },
            expected: expected.to_owned(),
            found: found.to_owned(),
            evidence: evidence.to_owned(),
        }
    }
}

fn parse_canonical_utc(value: &str) -> Option<OffsetDateTime> {
    time::PrimitiveDateTime::parse(
        value,
        time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ),
    )
    .ok()
    .map(time::PrimitiveDateTime::assume_utc)
}

fn parse_http_date(value: &str) -> Option<OffsetDateTime> {
    time::PrimitiveDateTime::parse(
        value,
        time::macros::format_description!(
            "[weekday repr:short], [day] [month repr:short] [year] [hour]:[minute]:[second] GMT"
        ),
    )
    .ok()
    .map(time::PrimitiveDateTime::assume_utc)
}

/// Numeric value of a token that is either a JSON number or a quoted decimal string.
fn token_f64(token: &str) -> Option<f64> {
    if token.starts_with('"') {
        serde_json::from_str::<String>(token)
            .ok()?
            .trim()
            .parse()
            .ok()
    } else {
        token.parse().ok()
    }
}

fn token_string(token: &str) -> Option<String> {
    token
        .starts_with('"')
        .then(|| serde_json::from_str(token).ok())
        .flatten()
}

fn epoch_from_unit(value: f64, unit: ClockUnit) -> Option<i64> {
    let seconds = match unit {
        ClockUnit::EpochMillis => value / 1000.0,
        ClockUnit::EpochSeconds => value,
        ClockUnit::Iso8601Utc => return None,
    };
    if seconds.is_finite() && seconds.abs() < 253_402_300_800.0 {
        #[allow(clippy::cast_possible_truncation)] // bounded just above
        Some(seconds as i64)
    } else {
        None
    }
}

fn describe_epoch_seconds(seconds: i64) -> String {
    OffsetDateTime::from_unix_timestamp(seconds).map_or_else(
        |_| format!("{seconds} seconds from epoch (outside representable time)"),
        |instant| {
            format!(
                "{:04}-{:02}-{:02}",
                instant.year(),
                u8::from(instant.month()),
                instant.day()
            )
        },
    )
}

/// Run every check the audit knows over one retained acquisition.
///
/// Total in the same way the trust gates are total: every check the audit knows for this route
/// appears in the result with a verdict, findings are typed and cite their evidence, and the
/// checks this material structurally cannot support are named in `not_examined`.
///
/// # Errors
///
/// Returns an error only when the acquisition names a route outside the pinned catalog or the
/// decision timestamp is not canonical. Everything provider-side becomes findings, not errors.
#[allow(clippy::too_many_lines)] // The check sequence stays auditable in one place, like the gates.
pub fn audit_acquisition(
    acquisition: &Acquisition,
    review: Option<&SuppliedReview>,
    decided_at: &str,
) -> Result<AcquisitionAuditV1, TrustError> {
    let route = acquisition
        .route_id
        .parse::<RouteId>()
        .map_err(|_| TrustError::UnknownRoute(acquisition.route_id.clone()))?;
    if !crate::trust::is_canonical_utc(decided_at) {
        return Err(TrustError::DecidedAt);
    }
    let spec = RouteSpec::for_id(route);
    let mut auditor = Auditor {
        route: route.to_string(),
        checks: Vec::new(),
        findings: Vec::new(),
    };

    // ---- record integrity: establish WHAT is being examined ------------------------------

    if acquisition.catalog_version == ROUTE_CATALOG {
        auditor.clear(
            "audit/integrity/catalog_version",
            AuditFamily::RecordIntegrity,
            "acquired under the pinned route catalog this audit's route facts describe",
        );
    } else {
        let finding = auditor.finding(
            AuditFamily::RecordIntegrity,
            "audit/integrity/catalog_version",
            AuditSeverity::Hazard,
            "envelope:catalogVersion",
            None,
            None,
            ROUTE_CATALOG,
            &acquisition.catalog_version,
            "route facts (subjects, pagination, gate governance) are pinned per catalog \
             version; under a different pin they may not apply",
        );
        auditor.found(
            "audit/integrity/catalog_version",
            AuditFamily::RecordIntegrity,
            vec![finding],
        );
    }

    let mut block: Option<ContentBlock> = None;
    let mut exact_bytes: Option<Vec<u8>> = None;
    match &acquisition.body {
        BodyCapture::Exact {
            bytes_base64: _,
            byte_length,
            blob_id,
            ..
        } => {
            if let Some(bytes) = acquisition.body.exact_bytes() {
                if byte_length == &bytes.len().to_string() && blob_id == &sha256(&bytes) {
                    auditor.clear(
                        "audit/integrity/body_capture",
                        AuditFamily::RecordIntegrity,
                        "exact body decodes and matches its declared length and digest",
                    );
                    exact_bytes = Some(bytes);
                } else {
                    let finding = auditor.finding(
                        AuditFamily::RecordIntegrity,
                        "audit/integrity/body_capture",
                        AuditSeverity::Defect,
                        "envelope:body",
                        None,
                        None,
                        "declared byteLength and blobId matching the retained bytes",
                        "declared body identity does not match the bytes retained under it",
                        "an acquisition whose bytes are not what it says they are certifies \
                         nothing",
                    );
                    auditor.found(
                        "audit/integrity/body_capture",
                        AuditFamily::RecordIntegrity,
                        vec![finding],
                    );
                    block = Some(ContentBlock::BodyIdentityMismatch);
                }
            } else {
                let finding = auditor.finding(
                    AuditFamily::RecordIntegrity,
                    "audit/integrity/body_capture",
                    AuditSeverity::Defect,
                    "envelope:body",
                    None,
                    None,
                    "base64 that decodes",
                    "the retained body base64 did not decode",
                    "undecodable retention is a lost acquisition wearing a kept one's envelope",
                );
                auditor.found(
                    "audit/integrity/body_capture",
                    AuditFamily::RecordIntegrity,
                    vec![finding],
                );
                block = Some(ContentBlock::BodyIdentityMismatch);
            }
        }
        BodyCapture::Truncated { .. } | BodyCapture::Missing { .. } => {
            let finding = auditor.finding(
                AuditFamily::RecordIntegrity,
                "audit/integrity/body_capture",
                AuditSeverity::Gap,
                "envelope:body",
                None,
                None,
                "an exact retained body",
                "the body capture is truncated or missing",
                "only complete exact bytes can be examined; this is retained absence, not data",
            );
            auditor.found(
                "audit/integrity/body_capture",
                AuditFamily::RecordIntegrity,
                vec![finding],
            );
            block = Some(ContentBlock::NonExactBody);
        }
    }

    let success_status = acquisition
        .http_status
        .is_some_and(|status| (200..300).contains(&status));
    if success_status {
        auditor.clear(
            "audit/integrity/http_status",
            AuditFamily::RecordIntegrity,
            "2xx response; the body is product content",
        );
    } else {
        let finding = auditor.finding(
            AuditFamily::RecordIntegrity,
            "audit/integrity/http_status",
            AuditSeverity::Observation,
            "envelope:httpStatus",
            None,
            None,
            "2xx for product content (an error body is retained but never read as product)",
            &acquisition
                .http_status
                .map_or_else(|| "no status".to_owned(), |status| status.to_string()),
            "a retained refusal is evidence too; the content checks below refuse to read it \
             as product",
        );
        auditor.found(
            "audit/integrity/http_status",
            AuditFamily::RecordIntegrity,
            vec![finding],
        );
        if block.is_none() {
            block = Some(ContentBlock::NonSuccessStatus);
        }
    }

    let mut body: Option<ParsedBody> = None;
    match (&block, &exact_bytes) {
        (None, Some(bytes)) => {
            if reject_duplicate_keys(bytes).is_err() {
                let finding = auditor.finding(
                    AuditFamily::RecordIntegrity,
                    "audit/integrity/json_wellformed",
                    AuditSeverity::Defect,
                    "$",
                    None,
                    None,
                    "well-formed JSON without duplicate object keys",
                    "the body is not well-formed JSON or repeats an object key",
                    "a duplicate key makes every reader's answer depend on its parser",
                );
                auditor.found(
                    "audit/integrity/json_wellformed",
                    AuditFamily::RecordIntegrity,
                    vec![finding],
                );
                block = Some(ContentBlock::UnparseableJson);
            } else if let Ok(raw) = serde_json::from_slice::<Box<RawValue>>(bytes) {
                auditor.clear(
                    "audit/integrity/json_wellformed",
                    AuditFamily::RecordIntegrity,
                    "well-formed JSON, no duplicate keys",
                );
                match records(route, &raw) {
                    Ok(raw_rows) => {
                        let rows = raw_rows
                            .iter()
                            .enumerate()
                            .filter_map(|(ordinal, row)| {
                                let object: BTreeMap<String, Box<RawValue>> =
                                    serde_json::from_str(row.get()).ok()?;
                                Some(Row {
                                    ordinal,
                                    fields: object
                                        .into_iter()
                                        .map(|(key, value)| (key, value.get().trim().to_owned()))
                                        .collect(),
                                })
                            })
                            .collect();
                        body = Some(ParsedBody { raw, rows });
                    }
                    Err(_) => {
                        block = Some(ContentBlock::ContainerUnreadable);
                    }
                }
            } else {
                let finding = auditor.finding(
                    AuditFamily::RecordIntegrity,
                    "audit/integrity/json_wellformed",
                    AuditSeverity::Defect,
                    "$",
                    None,
                    None,
                    "well-formed JSON",
                    "the body did not parse",
                    "unparseable bytes have no fields to audit",
                );
                auditor.found(
                    "audit/integrity/json_wellformed",
                    AuditFamily::RecordIntegrity,
                    vec![finding],
                );
                block = Some(ContentBlock::UnparseableJson);
            }
        }
        (blocked_reason, _) => {
            let reason = blocked_reason
                .as_ref()
                .copied()
                .unwrap_or(ContentBlock::NonExactBody);
            auditor.blocked(
                "audit/integrity/json_wellformed",
                AuditFamily::RecordIntegrity,
                reason,
            );
        }
    }

    // ---- clocks --------------------------------------------------------------------------

    check_clock_coherence(&mut auditor, acquisition);
    let received = parse_canonical_utc(&acquisition.clocks.received_at);
    check_header_date_skew(&mut auditor, acquisition, received);

    // ---- identity ------------------------------------------------------------------------

    check_subject_restated(&mut auditor, acquisition, route, spec);
    check_subject_corroborated(&mut auditor, acquisition, route, body.as_ref(), block);

    // ---- gate governance ------------------------------------------------------------------

    check_review_kind(&mut auditor, route, review);
    check_gate_replay(&mut auditor, acquisition, review, decided_at);
    check_review_hygiene(&mut auditor, review);

    // ---- content checks (all refuse via the block reason when the body is unavailable) ----

    match (&body, block) {
        (Some(parsed), None) => {
            let upper_bound_seconds =
                received.map(|instant| instant.unix_timestamp() + PLAUSIBLE_FUTURE_SLACK_SECONDS);
            check_container_rows(&mut auditor, route, parsed);
            check_limit_clamp(&mut auditor, acquisition, spec, parsed);
            check_retained_but_unread(&mut auditor, route, parsed);
            check_empty_page(&mut auditor, route, parsed);
            check_trades_terminal_shape(&mut auditor, route, parsed);
            check_multiple_floor(&mut auditor, route, parsed);
            check_declared_clock_plausibility(&mut auditor, route, parsed, upper_bound_seconds);
            check_undeclared_clock_inference(&mut auditor, route, parsed, upper_bound_seconds);
            check_mixed_units_on_row(&mut auditor, route, parsed);
            check_usd_market_cap_pair(&mut auditor, route, parsed);
            check_total_supply_pair(&mut auditor, route, parsed);
            check_multiple_reconciles(&mut auditor, route, parsed);
            check_graduated_reserves(&mut auditor, route, parsed);
            check_unknown_curve_state(&mut auditor, route, parsed);
            check_homonyms(&mut auditor, route, parsed);
            check_fee_leg_wedge(&mut auditor, route, parsed);
            check_occurrence_without_availability(&mut auditor, route, parsed);
        }
        (_, blocked_reason) => {
            let reason = blocked_reason.unwrap_or(ContentBlock::ContainerUnreadable);
            for (check_id, family) in CONTENT_CHECKS {
                auditor.blocked(check_id, *family, reason);
            }
        }
    }

    Ok(AcquisitionAuditV1 {
        contract: ACQUISITION_AUDIT_V1.to_owned(),
        schema_version: "1".to_owned(),
        audit_id: format!("audit:pump-acquisition:{}", acquisition.acquisition_id),
        route_id: route.to_string(),
        acquisition_id: acquisition.acquisition_id.clone(),
        catalog_version: acquisition.catalog_version.clone(),
        body_blob_id: acquisition.body.blob_id().map(str::to_owned),
        decided_at: decided_at.to_owned(),
        checks: auditor.checks,
        findings: auditor.findings,
        not_examined: not_examined(route),
    })
}

/// Every content check, so a blocked body records each one as undecidable rather than absent.
const CONTENT_CHECKS: &[(&str, AuditFamily)] = &[
    (
        "audit/narrowing/container_rows",
        AuditFamily::SilentNarrowing,
    ),
    ("audit/narrowing/limit_clamp", AuditFamily::SilentNarrowing),
    (
        "audit/narrowing/retained_but_unread",
        AuditFamily::SilentNarrowing,
    ),
    (
        "audit/absence/empty_page",
        AuditFamily::AbsenceThatLooksLikeData,
    ),
    (
        "audit/absence/trades_terminal_shape",
        AuditFamily::AbsenceThatLooksLikeData,
    ),
    (
        "audit/absence/multiple_floor",
        AuditFamily::AbsenceThatLooksLikeData,
    ),
    (
        "audit/units/declared_clock_plausibility",
        AuditFamily::UnitMismatch,
    ),
    (
        "audit/units/undeclared_clock_inference",
        AuditFamily::UnitMismatch,
    ),
    ("audit/units/mixed_units_on_row", AuditFamily::UnitMismatch),
    (
        "audit/duplicates/usd_market_cap_pair",
        AuditFamily::DisagreeingDuplicates,
    ),
    (
        "audit/duplicates/total_supply_pair",
        AuditFamily::DisagreeingDuplicates,
    ),
    (
        "audit/duplicates/multiple_reconciles",
        AuditFamily::DisagreeingDuplicates,
    ),
    (
        "audit/staleness/graduated_reserves",
        AuditFamily::StalenessThatLooksLive,
    ),
    (
        "audit/staleness/unknown_curve_state",
        AuditFamily::StalenessThatLooksLive,
    ),
    (
        "audit/homonyms/cross_route_meaning",
        AuditFamily::SemanticDriftAcrossRoutes,
    ),
    ("audit/leg/fee_wedge", AuditFamily::LegReferenceMismatch),
    (
        "audit/clock_gaps/occurrence_without_availability",
        AuditFamily::ClockGaps,
    ),
];

fn check_clock_coherence(auditor: &mut Auditor, acquisition: &Acquisition) {
    const CHECK: &str = "audit/clock_gaps/clock_coherence";
    let clocks = &acquisition.clocks;
    let started = parse_canonical_utc(&clocks.started_at);
    let received = parse_canonical_utc(&clocks.received_at);
    let (Some(started), Some(received)) = (started, received) else {
        let finding = auditor.finding(
            AuditFamily::ClockGaps,
            CHECK,
            AuditSeverity::Defect,
            "envelope:clocks",
            None,
            None,
            "canonical six-digit UTC startedAt and receivedAt",
            "at least one edge clock is not canonical",
            "the acquisition clock is the only availability instant this record has",
        );
        auditor.found(CHECK, AuditFamily::ClockGaps, vec![finding]);
        return;
    };
    let mut findings = Vec::new();
    if received < started {
        findings.push(auditor.finding(
            AuditFamily::ClockGaps,
            CHECK,
            AuditSeverity::Defect,
            "envelope:clocks",
            None,
            None,
            "startedAt <= receivedAt",
            &format!(
                "receivedAt {} precedes startedAt {}",
                clocks.received_at, clocks.started_at
            ),
            "a response received before its request was sent is a broken clock, not a fast one",
        ));
    }
    let monotonic = (
        clocks.started_monotonic_ns.parse::<u128>(),
        clocks.received_monotonic_ns.parse::<u128>(),
        clocks.elapsed_ns.parse::<u128>(),
    );
    if let (Ok(started_ns), Ok(received_ns), Ok(elapsed_ns)) = monotonic {
        if received_ns.checked_sub(started_ns) != Some(elapsed_ns) {
            findings.push(auditor.finding(
                AuditFamily::ClockGaps,
                CHECK,
                AuditSeverity::Defect,
                "envelope:clocks",
                None,
                None,
                "elapsedNs == receivedMonotonicNs - startedMonotonicNs",
                &format!(
                    "elapsedNs {} vs monotonic difference of {} and {}",
                    clocks.elapsed_ns, clocks.received_monotonic_ns, clocks.started_monotonic_ns
                ),
                "the monotonic triple must telescope; anything else is an edited clock",
            ));
        }
    } else {
        findings.push(auditor.finding(
            AuditFamily::ClockGaps,
            CHECK,
            AuditSeverity::Defect,
            "envelope:clocks",
            None,
            None,
            "monotonic nanosecond readings that parse as unsigned integers",
            "at least one monotonic reading does not parse",
            "an unreadable monotonic clock cannot support any latency statement",
        ));
    }
    auditor.decide(
        CHECK,
        AuditFamily::ClockGaps,
        findings,
        "edge clocks are canonical, ordered, and the monotonic triple telescopes",
    );
}

fn check_header_date_skew(
    auditor: &mut Auditor,
    acquisition: &Acquisition,
    received: Option<OffsetDateTime>,
) {
    const CHECK: &str = "audit/clock_gaps/header_date_skew";
    let header = acquisition
        .safe_response_headers
        .iter()
        .find(|header| header.name.eq_ignore_ascii_case("date"));
    let Some(header) = header else {
        let finding = auditor.finding(
            AuditFamily::ClockGaps,
            CHECK,
            AuditSeverity::Observation,
            "envelope:safeResponseHeaders",
            Some("date"),
            None,
            "a `date` response header, the one transport-level provider clock",
            "no date header was retained",
            "without any provider clock, ordering rests entirely on our receive instant",
        );
        auditor.found(CHECK, AuditFamily::ClockGaps, vec![finding]);
        return;
    };
    let (Some(received), Some(header_instant)) = (received, parse_http_date(&header.value)) else {
        auditor.undecidable(
            CHECK,
            AuditFamily::ClockGaps,
            "the date header or the receive clock did not parse, so skew is not measurable",
        );
        return;
    };
    let skew_seconds = (received - header_instant).whole_seconds();
    if skew_seconds.abs() > HEADER_SKEW_HAZARD_SECONDS {
        let finding = auditor.finding(
            AuditFamily::ClockGaps,
            CHECK,
            AuditSeverity::Hazard,
            "envelope:safeResponseHeaders",
            Some("date"),
            None,
            &format!("provider date within {HEADER_SKEW_HAZARD_SECONDS}s of our receive instant"),
            &format!("provider date is {skew_seconds}s from receivedAt"),
            "a large transport-clock gap means one of the two clocks cannot be trusted for \
             staleness arithmetic",
        );
        auditor.found(CHECK, AuditFamily::ClockGaps, vec![finding]);
    } else {
        auditor.clear(
            CHECK,
            AuditFamily::ClockGaps,
            &format!("provider date header within {skew_seconds}s of our receive instant"),
        );
    }
}

fn check_subject_restated(
    auditor: &mut Auditor,
    acquisition: &Acquisition,
    route: RouteId,
    spec: RouteSpec,
) {
    const CHECK: &str = "audit/identity_gap/subject_restated";
    let segments = spec.public_subject_path();
    if segments.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::IdentityGap,
            "the pinned catalog declares no public subject segment for this route",
        );
        return;
    }
    let mut findings = Vec::new();
    for segment in segments {
        let present = acquisition
            .resolved_public_path
            .get(*segment)
            .is_some_and(|value| !value.trim().is_empty());
        if !present {
            let severity = if body_names_subject(route) {
                // The body restates its subject, so the envelope absence costs corroboration,
                // not identity.
                AuditSeverity::Observation
            } else {
                AuditSeverity::Gap
            };
            findings.push(auditor.finding(
                AuditFamily::IdentityGap,
                CHECK,
                severity,
                "envelope:resolvedPublicPath",
                Some(segment),
                None,
                &format!(
                    "the request's public `{segment}` restated on the envelope, because the \
                     body of this route does {}state it",
                    if body_names_subject(route) {
                        ""
                    } else {
                        "NOT "
                    }
                ),
                &format!("no resolved `{segment}` on the acquisition"),
                "a candle window names no coin, a curve account names no mint, an account \
                 response is positional: when the request is not retained either, nothing \
                 durable says what the bytes are about (the CandlesNameNoSubject seam)",
            ));
        }
    }
    auditor.decide(
        CHECK,
        AuditFamily::IdentityGap,
        findings,
        "every catalog-declared public subject segment is restated on the envelope",
    );
}

fn check_subject_corroborated(
    auditor: &mut Auditor,
    acquisition: &Acquisition,
    route: RouteId,
    body: Option<&ParsedBody>,
    block: Option<ContentBlock>,
) {
    const CHECK: &str = "audit/identity_gap/subject_corroborated";
    if route != RouteId::CoinExact {
        auditor.clear(
            CHECK,
            AuditFamily::IdentityGap,
            "corroboration is defined only where both the request and the body state the \
             subject; on this route they do not both",
        );
        return;
    }
    let Some(parsed) = body else {
        auditor.blocked(
            CHECK,
            AuditFamily::IdentityGap,
            block.unwrap_or(ContentBlock::NonExactBody),
        );
        return;
    };
    let body_mint = parsed
        .rows
        .first()
        .and_then(|row| row.fields.get("mint"))
        .and_then(|token| token_string(token));
    let resolved = acquisition.resolved_public_path.get("mint");
    match (body_mint, resolved) {
        (Some(body_mint), Some(resolved)) => {
            if &body_mint == resolved {
                auditor.clear(
                    CHECK,
                    AuditFamily::IdentityGap,
                    "the body's mint equals the request's resolved mint",
                );
            } else {
                let finding = auditor.finding(
                    AuditFamily::IdentityGap,
                    CHECK,
                    AuditSeverity::Defect,
                    "$/mint",
                    Some("mint"),
                    Some(0),
                    &format!("body mint equal to requested mint {resolved}"),
                    &format!("body names {body_mint}"),
                    "a body about a different subject than the one asked for is the identity \
                     gap at its loudest",
                );
                auditor.found(CHECK, AuditFamily::IdentityGap, vec![finding]);
            }
        }
        (None, _) => {
            auditor.undecidable(
                CHECK,
                AuditFamily::IdentityGap,
                "the body carries no readable mint string to corroborate",
            );
        }
        (_, None) => {
            auditor.undecidable(
                CHECK,
                AuditFamily::IdentityGap,
                "no request-side resolved mint was retained on this envelope (it predates \
                 resolvedPublicPath), so there is nothing to corroborate against",
            );
        }
    }
}

fn check_review_kind(auditor: &mut Auditor, route: RouteId, review: Option<&SuppliedReview>) {
    const CHECK: &str = "audit/gate/review_kind";
    let Some(review) = review else {
        auditor.undecidable(
            CHECK,
            AuditFamily::GateMeasuresContentNotSchema,
            "no review was supplied; which gate governs these bytes cannot be examined",
        );
        return;
    };
    if review.route_id() != route.to_string() {
        let finding = auditor.finding(
            AuditFamily::GateMeasuresContentNotSchema,
            CHECK,
            AuditSeverity::Defect,
            "review",
            None,
            None,
            &format!("a review for route {route}"),
            &format!(
                "review {} covers route {}",
                review.review_id(),
                review.route_id()
            ),
            "a review for another route certifies nothing about this one",
        );
        auditor.found(
            CHECK,
            AuditFamily::GateMeasuresContentNotSchema,
            vec![finding],
        );
        return;
    }
    match (governing_gate(route), review) {
        (GateKind::RowProjection, SuppliedReview::Document(_)) => {
            let finding = auditor.finding(
                AuditFamily::GateMeasuresContentNotSchema,
                CHECK,
                AuditSeverity::Defect,
                "review",
                None,
                None,
                "a row-projection review: this route's rows are heterogeneous",
                "a whole-document fingerprint review",
                "a document fingerprint over heterogeneous rows measures which coins landed in \
                 the page, not the schema: eleven reads of /coins produced eight fingerprints \
                 (2026-08-22)",
            );
            auditor.found(
                CHECK,
                AuditFamily::GateMeasuresContentNotSchema,
                vec![finding],
            );
        }
        (GateKind::Unmeasured, _) => {
            auditor.undecidable(
                CHECK,
                AuditFamily::GateMeasuresContentNotSchema,
                "nothing has measured which gate can govern this route; the first live call \
                 must decide it before any review kind is called right",
            );
        }
        _ => {
            auditor.clear(
                CHECK,
                AuditFamily::GateMeasuresContentNotSchema,
                "the supplied review kind matches the gate measured to govern this route",
            );
        }
    }
}

fn check_gate_replay(
    auditor: &mut Auditor,
    acquisition: &Acquisition,
    review: Option<&SuppliedReview>,
    decided_at: &str,
) {
    const CHECK: &str = "audit/gate/decision_replay";
    let decision = match review {
        None => {
            auditor.undecidable(
                CHECK,
                AuditFamily::GateMeasuresContentNotSchema,
                "no review was supplied; absence of a review is a refusal at the gate, and \
                 there is nothing to replay",
            );
            return;
        }
        Some(SuppliedReview::Document(review)) => {
            crate::trust::decide_schema_trust(acquisition, Some(review), decided_at)
        }
        Some(SuppliedReview::Rows(review)) => crate::row_projection::decide_row_projection_trust(
            acquisition,
            Some(review),
            decided_at,
        ),
    };
    match decision {
        Ok(decision) if decision.outcome == SchemaTrustOutcome::Promoted => {
            auditor.clear(
                CHECK,
                AuditFamily::GateMeasuresContentNotSchema,
                &format!(
                    "the gate promotes these bytes under review {:?}",
                    decision.review_id
                ),
            );
        }
        Ok(decision) => {
            let finding = auditor.finding(
                AuditFamily::GateMeasuresContentNotSchema,
                CHECK,
                AuditSeverity::Hazard,
                "$",
                None,
                None,
                "promotion under the supplied review",
                &format!("{}: {}", decision.reason_code, decision.detail),
                "the gate's own refusal, replayed offline over the retained bytes",
            );
            auditor.found(
                CHECK,
                AuditFamily::GateMeasuresContentNotSchema,
                vec![finding],
            );
        }
        Err(error) => {
            auditor.undecidable(
                CHECK,
                AuditFamily::GateMeasuresContentNotSchema,
                &format!("the gate itself could not run: {error}"),
            );
        }
    }
}

fn check_review_hygiene(auditor: &mut Auditor, review: Option<&SuppliedReview>) {
    const CHECK: &str = "audit/invention/review_hygiene";
    match review {
        None => auditor.undecidable(
            CHECK,
            AuditFamily::RequiredCardinalityForcesInvention,
            "no review was supplied, so its internal consistency cannot be examined",
        ),
        Some(SuppliedReview::Document(review)) => match review.validate() {
            Ok(()) => auditor.clear(
                CHECK,
                AuditFamily::RequiredCardinalityForcesInvention,
                "the document review passes its own shape/fingerprint closure",
            ),
            Err(error) => {
                let finding = auditor.finding(
                    AuditFamily::RequiredCardinalityForcesInvention,
                    CHECK,
                    AuditSeverity::Defect,
                    "review",
                    None,
                    None,
                    "an internally consistent review",
                    &error.to_string(),
                    "an inconsistent review can demand what no honest body carries",
                );
                auditor.found(
                    CHECK,
                    AuditFamily::RequiredCardinalityForcesInvention,
                    vec![finding],
                );
            }
        },
        Some(SuppliedReview::Rows(review)) => match review.validate() {
            Ok(()) => auditor.clear(
                CHECK,
                AuditFamily::RequiredCardinalityForcesInvention,
                "the row review passes its own closure, including that required leaves are \
                 leaves the normalizer actually reads",
            ),
            Err(error) => {
                let finding = auditor.finding(
                    AuditFamily::RequiredCardinalityForcesInvention,
                    CHECK,
                    AuditSeverity::Defect,
                    "review",
                    None,
                    None,
                    "an internally consistent row review (required subset of read fields)",
                    &error.to_string(),
                    "requiring what is never read turns a fail-closed gate into noise; \
                     requiring what cannot exist demands invention",
                );
                auditor.found(
                    CHECK,
                    AuditFamily::RequiredCardinalityForcesInvention,
                    vec![finding],
                );
            }
        },
    }
}

fn check_container_rows(auditor: &mut Auditor, _route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/narrowing/container_rows";
    if !parsed.rows.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::SilentNarrowing,
            &format!("the reviewed container yielded {} rows", parsed.rows.len()),
        );
        return;
    }
    // Zero rows out of the container while the body carries a nonempty array SOMEWHERE is the
    // exact shape of the candles bug: a shared envelope guess read a 1000-row body as 0 rows.
    let mut nonempty_arrays = Vec::new();
    scan_nonempty_arrays(&parsed.raw, "$", 0, &mut nonempty_arrays);
    if nonempty_arrays.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::SilentNarrowing,
            "zero rows, and the body carries no nonempty array anywhere: a genuinely empty page",
        );
        return;
    }
    let listing = nonempty_arrays
        .iter()
        .take(MAX_NAMES_PER_FINDING)
        .map(|(pointer, count)| format!("{pointer} ({count} elements)"))
        .collect::<Vec<_>>()
        .join(", ");
    let finding = auditor.finding(
        AuditFamily::SilentNarrowing,
        CHECK,
        AuditSeverity::Defect,
        "$",
        None,
        None,
        "the reviewed container yielding the body's rows",
        &format!("0 rows from the container while the body carries nonempty arrays at {listing}"),
        "a normalizer reading the wrong envelope path returned 0 rows out of a 1000-row candle \
         body (2026-08-22); zero-out-of-something is a misread, not an empty page",
    );
    auditor.found(CHECK, AuditFamily::SilentNarrowing, vec![finding]);
}

/// Page-size clamps MEASURED per route, each citing its measurement. A route absent here has no
/// measured clamp value — not "no clamp": /coins/search-unrestricted honoured limit=100 and its
/// behaviour above that is unmeasured, which is exactly why two siblings on one host cannot
/// share this constant.
fn measured_limit_clamp(route: RouteId) -> Option<usize> {
    match route {
        // limit=71, limit=100 and limit=1000 each returned exactly 70 rows with HTTP 200 and no
        // warning of any kind (measured 2026-08-22; see the catalog entry).
        RouteId::DiscoveryCoins => Some(70),
        // limit=200 and limit=500 each returned exactly 150 rows with HTTP 200 and no warning,
        // while 5, 70 (bare) and 150 were honoured (measured 2026-08-24).
        RouteId::BoardMovers => Some(150),
        _ => None,
    }
}

/// The query parameter whose requested value bounds this route's page, where one exists. The
/// paged kinds name it structurally; `board_movers` is not paged — there is no offset — but its
/// `limit` bounds the single window and silently clamps at 150 (measured 2026-08-24), so
/// ask-vs-delivered is exactly as decidable there as on /coins.
fn clamp_parameter(spec: RouteSpec) -> Option<&'static str> {
    match spec.pagination {
        PaginationKind::OffsetLimit => Some("limit"),
        PaginationKind::PageSize => Some("size"),
        _ if spec.id == RouteId::BoardMovers => Some("limit"),
        _ => None,
    }
}

/// Family 7's loudest member, decidable only because retention changed: the envelope's
/// `resolvedPublicQuery` restates the requested page size, so requested-vs-delivered becomes a
/// comparison instead of a permanent unknown. Where the envelope predates that field (or the
/// request declared no limit) the verdict stays UNDECIDABLE with its reason — the check never
/// assumes what an older record did not retain.
fn check_limit_clamp(
    auditor: &mut Auditor,
    acquisition: &Acquisition,
    spec: RouteSpec,
    parsed: &ParsedBody,
) {
    const CHECK: &str = "audit/narrowing/limit_clamp";
    let Some(parameter) = clamp_parameter(spec) else {
        auditor.clear(
            CHECK,
            AuditFamily::SilentNarrowing,
            "not a limit-paged route; no requested page size exists to be clamped",
        );
        return;
    };
    let Some(requested_raw) = acquisition.resolved_public_query.get(parameter) else {
        auditor.undecidable(
            CHECK,
            AuditFamily::SilentNarrowing,
            &format!(
                "no requested `{parameter}` is retained on this envelope — it predates \
                 resolvedPublicQuery or the request sent no `{parameter}` — so \
                 requested-vs-delivered cannot be compared; a silent clamp stays undecidable, \
                 never assumed absent"
            ),
        );
        return;
    };
    let Ok(requested) = requested_raw.parse::<usize>() else {
        let finding = auditor.finding(
            AuditFamily::SilentNarrowing,
            CHECK,
            AuditSeverity::Hazard,
            "envelope:resolvedPublicQuery",
            Some(parameter),
            None,
            "a nonnegative integer page size restated from the request",
            &format!("`{requested_raw}` does not parse as one"),
            "a request the provider would have rejected or coerced cannot anchor a \
             requested-vs-delivered comparison",
        );
        auditor.found(CHECK, AuditFamily::SilentNarrowing, vec![finding]);
        return;
    };
    let delivered = parsed.rows.len();
    if delivered == requested {
        auditor.clear(
            CHECK,
            AuditFamily::SilentNarrowing,
            &format!("requested {requested} row(s) and the provider delivered exactly that"),
        );
        return;
    }
    if delivered > requested {
        let finding = auditor.finding(
            AuditFamily::SilentNarrowing,
            CHECK,
            AuditSeverity::Defect,
            "$",
            Some(parameter),
            None,
            &format!("at most the requested {requested} row(s)"),
            &format!("{delivered} rows: the provider ignored the requested bound"),
            "an over-delivered page means the limit parameter did not govern this response, \
             so nothing about its coverage follows from what was asked",
        );
        auditor.found(CHECK, AuditFamily::SilentNarrowing, vec![finding]);
        return;
    }
    match measured_limit_clamp(spec.id) {
        Some(clamp) if delivered == clamp && requested > clamp => {
            let finding = auditor.finding(
                AuditFamily::SilentNarrowing,
                CHECK,
                AuditSeverity::Defect,
                "$",
                Some(parameter),
                None,
                &format!("the requested {requested} row(s), or a stated narrowing"),
                &format!(
                    "{delivered} rows — exactly this route's measured silent clamp of {clamp} \
                     — under HTTP 2xx with no warning"
                ),
                "measured 2026-08-22 on /coins: limit=71, limit=100 and limit=1000 each \
                 returned exactly 70 rows; a caller that asks and counts is the only caller \
                 that finds out, and this record retained the ask",
            );
            auditor.found(CHECK, AuditFamily::SilentNarrowing, vec![finding]);
        }
        _ => {
            auditor.undecidable(
                CHECK,
                AuditFamily::SilentNarrowing,
                &format!(
                    "requested {requested}, delivered {delivered}: a short page is either the \
                     population tail past this offset or an unmeasured narrowing, and one \
                     acquisition cannot tell which; no measured clamp value for this route \
                     matches the delivered count"
                ),
            );
        }
    }
}

fn scan_nonempty_arrays(
    raw: &RawValue,
    pointer: &str,
    depth: usize,
    into: &mut Vec<(String, usize)>,
) {
    if depth > 8 || into.len() > 32 {
        return;
    }
    let source = raw.get().trim_start();
    if source.starts_with('[') {
        if let Ok(items) = serde_json::from_str::<Vec<Box<RawValue>>>(raw.get())
            && !items.is_empty()
        {
            into.push((pointer.to_owned(), items.len()));
        }
    } else if source.starts_with('{')
        && let Ok(object) = serde_json::from_str::<BTreeMap<String, Box<RawValue>>>(raw.get())
    {
        for (key, value) in object {
            scan_nonempty_arrays(&value, &format!("{pointer}/{key}"), depth + 1, into);
        }
    }
}

fn check_retained_but_unread(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/narrowing/retained_but_unread";
    let read: BTreeSet<&str> = extracted_fields(route).iter().copied().collect();
    if read.is_empty() || parsed.rows.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::SilentNarrowing,
            "no extraction projection or no rows; nothing can be silently narrowed here",
        );
        return;
    }
    let mut unread: BTreeMap<&str, usize> = BTreeMap::new();
    for row in &parsed.rows {
        for field in row.fields.keys() {
            if !read.contains(field.as_str()) {
                *unread.entry(field.as_str()).or_default() += 1;
            }
        }
    }
    if unread.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::SilentNarrowing,
            "every field the body carries is in the extraction projection",
        );
        return;
    }
    let names = unread
        .iter()
        .take(MAX_NAMES_PER_FINDING)
        .map(|(name, count)| format!("{name} (on {count} rows)"))
        .collect::<Vec<_>>()
        .join(", ");
    let finding = auditor.finding(
        AuditFamily::SilentNarrowing,
        CHECK,
        AuditSeverity::Observation,
        "$",
        None,
        None,
        "visibility of what the projection leaves in the bytes unread",
        &format!(
            "{} field name(s) present in the body and read by nothing: {names}",
            unread.len()
        ),
        "silent narrowing is how ath_market_cap and volume_1h_usd went missing from three \
         routes for three days; free text and media URLs are documented deliberate exclusions \
         (normalize.rs), so the reader's job is to spot a VALUE-bearing name in this list",
    );
    auditor.found(CHECK, AuditFamily::SilentNarrowing, vec![finding]);
}

fn check_empty_page(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/absence/empty_page";
    let collection = matches!(
        route,
        RouteId::DiscoveryCoins
            | RouteId::CurrentlyLive
            | RouteId::CoinSearch
            | RouteId::Candles
            | RouteId::CalloutTop
            | RouteId::CalloutByUser
            | RouteId::CalloutLeaderboard
            | RouteId::BoardMovers
            | RouteId::CommunityCallouts
    );
    if !collection {
        auditor.clear(
            CHECK,
            AuditFamily::AbsenceThatLooksLikeData,
            "not a collection route governed by this check (the trades terminal shape has its \
             own)",
        );
        return;
    }
    if !parsed.rows.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::AbsenceThatLooksLikeData,
            &format!(
                "{} rows; the page asserts content, not absence",
                parsed.rows.len()
            ),
        );
        return;
    }
    let evidence = match route {
        RouteId::DiscoveryCoins | RouteId::CurrentlyLive | RouteId::CoinSearch => {
            "measured 2026-08-22: an offset past the end answers a bare [] under HTTP 200, \
             byte-identical to a filter that matched nothing"
        }
        RouteId::CalloutTop | RouteId::CalloutByUser | RouteId::CommunityCallouts => {
            "an empty callout answer is retained as an absent record and never as evidence \
             that nobody called (and /callout/list keyed by a mint instead of a user answers \
             empty for the ordinary reason that no user has that id)"
        }
        RouteId::BoardMovers => {
            "no empty movers board has ever been observed (bare reads answer 70 rows); an \
             empty one would be a provider condition worth a look, never a statement that \
             nothing moves"
        }
        _ => {
            "no measured empty-page semantics exist for this route; absence may not be read \
             as data"
        }
    };
    let finding = auditor.finding(
        AuditFamily::AbsenceThatLooksLikeData,
        CHECK,
        AuditSeverity::Hazard,
        "$",
        None,
        None,
        "a page whose emptiness has one meaning",
        "zero rows under HTTP 2xx",
        evidence,
    );
    auditor.found(CHECK, AuditFamily::AbsenceThatLooksLikeData, vec![finding]);
}

fn check_trades_terminal_shape(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/absence/trades_terminal_shape";
    if route != RouteId::Trades {
        auditor.clear(
            CHECK,
            AuditFamily::AbsenceThatLooksLikeData,
            "trades-only check",
        );
        return;
    }
    if !parsed.rows.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::AbsenceThatLooksLikeData,
            "the page carries trades; it is not a terminal page",
        );
        return;
    }
    let root: Option<BTreeMap<String, Box<RawValue>>> = serde_json::from_str(parsed.raw.get()).ok();
    let pagination = root.as_ref().and_then(|object| {
        object.get("pagination").and_then(|value| {
            serde_json::from_str::<BTreeMap<String, Box<RawValue>>>(value.get()).ok()
        })
    });
    let has_more = pagination
        .as_ref()
        .and_then(|object| object.get("hasMore"))
        .map(|value| value.get().trim() == "true");
    let cursor_present = pagination
        .as_ref()
        .is_some_and(|object| object.contains_key("nextCursor"));
    match has_more {
        Some(false) if !cursor_present => {
            let finding = auditor.finding(
                AuditFamily::AbsenceThatLooksLikeData,
                CHECK,
                AuditSeverity::Observation,
                "$/pagination",
                Some("hasMore"),
                None,
                "a page of trades or a claimed continuation",
                "zero trades, hasMore=false, no cursor key: the terminal shape",
                "measured 2026-08-22: seeking past the beginning of a mint's retained history \
                 returns this distinct structural shape; it means past-the-beginning, and the \
                 reviewed schema refuses it by design",
            );
            auditor.found(CHECK, AuditFamily::AbsenceThatLooksLikeData, vec![finding]);
        }
        Some(_) => {
            let finding = auditor.finding(
                AuditFamily::AbsenceThatLooksLikeData,
                CHECK,
                AuditSeverity::Hazard,
                "$/pagination",
                Some("hasMore"),
                None,
                "an empty trades page only at the terminal shape",
                "zero trades while the provider claims continuation",
                "an empty page that claims more is neither content nor a measured terminal; \
                 refuse to read it as either",
            );
            auditor.found(CHECK, AuditFamily::AbsenceThatLooksLikeData, vec![finding]);
        }
        None => {
            auditor.undecidable(
                CHECK,
                AuditFamily::AbsenceThatLooksLikeData,
                "zero trades and no readable pagination.hasMore: the empty page cannot be \
                 classified as terminal or truncated",
            );
        }
    }
}

fn check_multiple_floor(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/absence/multiple_floor";
    if !matches!(route, RouteId::CalloutTop | RouteId::CalloutByUser) {
        auditor.clear(
            CHECK,
            AuditFamily::AbsenceThatLooksLikeData,
            "callout-only check",
        );
        return;
    }
    let mut floor_rows = 0usize;
    let mut first = None;
    for row in &parsed.rows {
        let multiple = row
            .fields
            .get("multiple")
            .and_then(|token| token_f64(token));
        if multiple.is_some_and(|value| (value - 1.0).abs() < f64::EPSILON) {
            floor_rows += 1;
            first.get_or_insert(row.ordinal);
        }
    }
    if floor_rows == 0 {
        auditor.clear(
            CHECK,
            AuditFamily::AbsenceThatLooksLikeData,
            "no row carries multiple=1; nothing here is at the floor",
        );
        return;
    }
    let finding = auditor.finding(
        AuditFamily::AbsenceThatLooksLikeData,
        CHECK,
        AuditSeverity::Observation,
        "$",
        Some("multiple"),
        first,
        "multiple=1 read as its own bin: the coin never exceeded its callout price",
        &format!("{floor_rows} row(s) at the multiple=1 floor"),
        "measured 2026-08-22: multiple=1 with the two prices equal is a FLOOR, not a missing \
         value; treating it as missing silently drops every failed callout, which is the \
         survivorship error this project keeps finding",
    );
    auditor.found(CHECK, AuditFamily::AbsenceThatLooksLikeData, vec![finding]);
}

#[allow(clippy::too_many_lines)] // The three unit verdicts and their evidence stay together.
fn check_declared_clock_plausibility(
    auditor: &mut Auditor,
    route: RouteId,
    parsed: &ParsedBody,
    upper_bound_seconds: Option<i64>,
) {
    const CHECK: &str = "audit/units/declared_clock_plausibility";
    let declared = declared_clocks(route);
    if declared.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::UnitMismatch,
            "no clock on this route has a measured unit declaration",
        );
        return;
    }
    let Some(upper) = upper_bound_seconds else {
        auditor.undecidable(
            CHECK,
            AuditFamily::UnitMismatch,
            "the acquisition's receive clock did not parse, so no plausibility window exists",
        );
        return;
    };
    let plausible = |seconds: i64| (PLAUSIBLE_EPOCH_FLOOR_SECONDS..=upper).contains(&seconds);
    let mut findings = Vec::new();
    let mut examined = 0usize;
    for (field, unit, evidence) in declared {
        let mut offending: Option<(usize, String, String, AuditSeverity)> = None;
        let mut offense_count = 0usize;
        for row in &parsed.rows {
            let Some(token) = row.fields.get(*field) else {
                continue;
            };
            if token == "null" {
                continue;
            }
            examined += 1;
            match unit {
                ClockUnit::Iso8601Utc => {
                    let iso_ok = token_string(token).is_some_and(|text| {
                        OffsetDateTime::parse(&text, &time::format_description::well_known::Rfc3339)
                            .is_ok()
                    });
                    if !iso_ok {
                        offense_count += 1;
                        offending.get_or_insert((
                            row.ordinal,
                            format!("`{token}` is not an ISO-8601 instant"),
                            "declared ISO-8601 UTC".to_owned(),
                            AuditSeverity::Hazard,
                        ));
                    }
                }
                ClockUnit::EpochMillis | ClockUnit::EpochSeconds => {
                    let Some(value) = token_f64(token) else {
                        offense_count += 1;
                        offending.get_or_insert((
                            row.ordinal,
                            format!("`{token}` is not numeric"),
                            format!("declared {}", unit.name()),
                            AuditSeverity::Hazard,
                        ));
                        continue;
                    };
                    let as_declared = epoch_from_unit(value, *unit);
                    if as_declared.is_some_and(plausible) {
                        continue;
                    }
                    offense_count += 1;
                    let other = match unit {
                        ClockUnit::EpochMillis => ClockUnit::EpochSeconds,
                        _ => ClockUnit::EpochMillis,
                    };
                    let as_other = epoch_from_unit(value, other);
                    let declared_lands = as_declared.map_or_else(
                        || "outside representable time".to_owned(),
                        |seconds| format!("on {}", describe_epoch_seconds(seconds)),
                    );
                    let (description, severity) = match as_other {
                        // Plausible under exactly the OTHER unit: the measured shape of the
                        // updated_at bug, where a wrong read lands in January 1970.
                        Some(other_s) if plausible(other_s) => (
                            format!(
                                "read under its declared unit it lands {declared_lands}; only \
                                 {} ({}) is plausible — the January-1970 signature",
                                other.name(),
                                describe_epoch_seconds(other_s),
                            ),
                            AuditSeverity::Defect,
                        ),
                        _ => (
                            format!(
                                "read under its declared unit it lands {declared_lands}, and \
                                 no known unit makes it plausible"
                            ),
                            AuditSeverity::Hazard,
                        ),
                    };
                    offending.get_or_insert((
                        row.ordinal,
                        description,
                        format!("declared {}", unit.name()),
                        severity,
                    ));
                }
            }
        }
        if let Some((ordinal, description, expected, severity)) = offending {
            findings.push(auditor.finding(
                AuditFamily::UnitMismatch,
                CHECK,
                severity,
                "$",
                Some(field),
                Some(ordinal),
                &expected,
                &format!("{description} ({offense_count} offending value(s))"),
                evidence,
            ));
        }
    }
    if examined == 0 {
        auditor.undecidable(
            CHECK,
            AuditFamily::UnitMismatch,
            "no declared clock field appears with a value in this body, so the declarations \
             were not exercised",
        );
        return;
    }
    auditor.decide(
        CHECK,
        AuditFamily::UnitMismatch,
        findings,
        &format!("{examined} declared clock value(s) are plausible under their measured units"),
    );
}

#[allow(clippy::too_many_lines)] // The per-unit tallies and their two verdicts stay together.
fn check_undeclared_clock_inference(
    auditor: &mut Auditor,
    route: RouteId,
    parsed: &ParsedBody,
    upper_bound_seconds: Option<i64>,
) {
    const CHECK: &str = "audit/units/undeclared_clock_inference";
    let suspects = undeclared_clock_suspects(route);
    if suspects.is_empty() {
        auditor.clear(
            CHECK,
            AuditFamily::UnitMismatch,
            "no clock-named field on this route lacks a measured unit",
        );
        return;
    }
    let Some(upper) = upper_bound_seconds else {
        auditor.undecidable(
            CHECK,
            AuditFamily::UnitMismatch,
            "the acquisition's receive clock did not parse, so no plausibility window exists",
        );
        return;
    };
    let plausible = |seconds: i64| (PLAUSIBLE_EPOCH_FLOOR_SECONDS..=upper).contains(&seconds);
    let mut findings = Vec::new();
    let mut saw_any = false;
    for field in suspects {
        let mut millis_only = 0usize;
        let mut seconds_only = 0usize;
        let mut iso_only = 0usize;
        let mut ambiguous = 0usize;
        let mut neither = 0usize;
        let mut first = None;
        for row in &parsed.rows {
            let Some(token) = row.fields.get(*field) else {
                continue;
            };
            if token == "null" {
                continue;
            }
            saw_any = true;
            first.get_or_insert(row.ordinal);
            // A quoted value that parses as an RFC 3339 instant is its own classification,
            // measured on trades 2026-08-23: `timestamp` there is `2026-08-22T01:11:13.000Z`
            // while the sibling candles route carries the same name as an epoch-millis number.
            let iso_instant = token_string(token).and_then(|text| {
                OffsetDateTime::parse(&text, &time::format_description::well_known::Rfc3339).ok()
            });
            if let Some(instant) = iso_instant {
                if plausible(instant.unix_timestamp()) {
                    iso_only += 1;
                } else {
                    neither += 1;
                }
                continue;
            }
            let Some(value) = token_f64(token) else {
                neither += 1;
                continue;
            };
            let as_millis = epoch_from_unit(value, ClockUnit::EpochMillis).is_some_and(plausible);
            let as_seconds = epoch_from_unit(value, ClockUnit::EpochSeconds).is_some_and(plausible);
            match (as_millis, as_seconds) {
                (true, false) => millis_only += 1,
                (false, true) => seconds_only += 1,
                (true, true) => ambiguous += 1,
                (false, false) => neither += 1,
            }
        }
        let total = millis_only + seconds_only + iso_only + ambiguous + neither;
        if total == 0 {
            continue;
        }
        let sole = [
            (millis_only, "epoch_millis"),
            (seconds_only, "epoch_seconds"),
            (iso_only, "iso8601_utc"),
        ]
        .into_iter()
        .find(|(count, _)| *count == total);
        let (severity, found) = if neither == 0
            && ambiguous == 0
            && let Some((_, unit)) = sole
        {
            (
                AuditSeverity::Observation,
                format!(
                    "all {total} value(s) are plausible ONLY as {unit}; this is an inference \
                     from magnitude and form, not a measurement, and stays unfit to declare a \
                     unit"
                ),
            )
        } else {
            (
                AuditSeverity::Hazard,
                format!(
                    "the values do not admit one reading: {millis_only} millis-only, \
                     {seconds_only} seconds-only, {iso_only} iso8601, {ambiguous} ambiguous, \
                     {neither} implausible under any unit"
                ),
            )
        };
        findings.push(auditor.finding(
            AuditFamily::UnitMismatch,
            CHECK,
            severity,
            "$",
            Some(field),
            first,
            "a measured unit declaration for a clock this crate reads",
            &found,
            "no measurement has pinned this field's unit; a unit error here would survive \
             exactly the way updated_at's did until someone measured it",
        ));
    }
    if !saw_any {
        auditor.undecidable(
            CHECK,
            AuditFamily::UnitMismatch,
            "no unmeasured clock-named field carries a value in this body",
        );
        return;
    }
    auditor.decide(
        CHECK,
        AuditFamily::UnitMismatch,
        findings,
        "unmeasured clock fields were absent from every row",
    );
}

fn check_mixed_units_on_row(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/units/mixed_units_on_row";
    let declared = declared_clocks(route);
    let has_seconds = declared
        .iter()
        .any(|(_, unit, _)| *unit == ClockUnit::EpochSeconds);
    let has_millis = declared
        .iter()
        .any(|(_, unit, _)| *unit == ClockUnit::EpochMillis);
    if !(has_seconds && has_millis) {
        auditor.clear(
            CHECK,
            AuditFamily::UnitMismatch,
            "this route's declared clocks do not mix units",
        );
        return;
    }
    let mut mixed_rows = 0usize;
    let mut first = None;
    for row in &parsed.rows {
        let mut units = BTreeSet::new();
        for (field, unit, _) in declared {
            if row.fields.get(*field).is_some_and(|token| token != "null") {
                units.insert(unit.name());
            }
        }
        if units.contains("epoch_seconds") && units.contains("epoch_millis") {
            mixed_rows += 1;
            first.get_or_insert(row.ordinal);
        }
    }
    if mixed_rows == 0 {
        auditor.clear(
            CHECK,
            AuditFamily::UnitMismatch,
            "no row carries clocks under both units at once",
        );
        return;
    }
    let finding = auditor.finding(
        AuditFamily::UnitMismatch,
        CHECK,
        AuditSeverity::Hazard,
        "$",
        Some("updated_at"),
        first,
        "one unit per row, or a reader who knows there is not",
        &format!("{mixed_rows} row(s) carry epoch-seconds and epoch-millis clocks side by side"),
        "measured 2026-08-22: updated_at is epoch SECONDS while every sibling clock is \
         milliseconds; read wrong it lands in January 1970 and looks like a stale record \
         rather than a units bug",
    );
    auditor.found(CHECK, AuditFamily::UnitMismatch, vec![finding]);
}

fn median_and_max(values: &mut [f64]) -> Option<(f64, f64)> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median = values[values.len() / 2];
    let max = *values.last()?;
    Some((median, max))
}

fn check_usd_market_cap_pair(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/duplicates/usd_market_cap_pair";
    if !matches!(
        route,
        RouteId::CoinExact | RouteId::DiscoveryCoins | RouteId::CurrentlyLive | RouteId::CoinSearch
    ) {
        auditor.clear(
            CHECK,
            AuditFamily::DisagreeingDuplicates,
            "coin-route-only check",
        );
        return;
    }
    let mut gaps = Vec::new();
    let mut worst: Option<(usize, f64)> = None;
    for row in &parsed.rows {
        let a = row
            .fields
            .get("market_cap_usd")
            .and_then(|token| token_f64(token));
        let b = row
            .fields
            .get("usd_market_cap")
            .and_then(|token| token_f64(token));
        let (Some(a), Some(b)) = (a, b) else { continue };
        let scale = a.abs().max(b.abs());
        if scale <= f64::EPSILON {
            continue;
        }
        let gap = (a - b).abs() / scale;
        if worst.is_none_or(|(_, current)| gap > current) {
            worst = Some((row.ordinal, gap));
        }
        gaps.push(gap);
    }
    let Some((median, max)) = median_and_max(&mut gaps) else {
        auditor.clear(
            CHECK,
            AuditFamily::DisagreeingDuplicates,
            "no row carries both usd market-cap assertions",
        );
        return;
    };
    let severity = if max > USD_PAIR_ALARM_RELATIVE {
        AuditSeverity::Defect
    } else {
        AuditSeverity::Observation
    };
    let finding = auditor.finding(
        AuditFamily::DisagreeingDuplicates,
        CHECK,
        severity,
        "$",
        Some("market_cap_usd"),
        worst.map(|(ordinal, _)| ordinal),
        "two provider fields asserting the same USD market cap",
        &format!(
            "over {} row(s) carrying both, relative disagreement median {:.4}%, max {:.4}%",
            gaps.len(),
            median * 100.0,
            max * 100.0
        ),
        "measured 2026-08-22 over 140 rows: median 0.10%, max 0.31%, and one later coin at \
         NINE percentage points; neither field is preferred, and the gap between two price \
         assertions is itself a state variable",
    );
    auditor.found(CHECK, AuditFamily::DisagreeingDuplicates, vec![finding]);
}

fn check_total_supply_pair(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/duplicates/total_supply_pair";
    if !matches!(
        route,
        RouteId::CoinExact | RouteId::DiscoveryCoins | RouteId::CurrentlyLive | RouteId::CoinSearch
    ) {
        auditor.clear(
            CHECK,
            AuditFamily::DisagreeingDuplicates,
            "coin-route-only check",
        );
        return;
    }
    let mut disagreements = 0usize;
    let mut first: Option<(usize, String)> = None;
    let mut both = 0usize;
    for row in &parsed.rows {
        let number = row.fields.get("total_supply").cloned();
        let string = row
            .fields
            .get("total_supply_str")
            .and_then(|token| token_string(token));
        let (Some(number), Some(string)) = (number, string) else {
            continue;
        };
        both += 1;
        let agree = number == string
            || matches!(
                (number.parse::<f64>(), string.parse::<f64>()),
                (Ok(a), Ok(b)) if (a - b).abs() <= f64::EPSILON * a.abs().max(b.abs())
            );
        if !agree {
            disagreements += 1;
            first.get_or_insert((row.ordinal, format!("{number} vs \"{string}\"")));
        }
    }
    if both == 0 {
        auditor.clear(
            CHECK,
            AuditFamily::DisagreeingDuplicates,
            "no row carries both total_supply and total_supply_str",
        );
        return;
    }
    if disagreements == 0 {
        auditor.clear(
            CHECK,
            AuditFamily::DisagreeingDuplicates,
            &format!("total_supply and total_supply_str agree on all {both} row(s) carrying both"),
        );
        return;
    }
    let (ordinal, example) = first.unwrap_or((0, String::new()));
    let finding = auditor.finding(
        AuditFamily::DisagreeingDuplicates,
        CHECK,
        AuditSeverity::Observation,
        "$",
        Some("total_supply"),
        Some(ordinal),
        "the numeric and string encodings of one supply agreeing",
        &format!("{disagreements} of {both} row(s) disagree; first: {example}"),
        "both encodings are retained and neither is preferred; a disagreement means the \
         provider computed them at different instants or one lost precision",
    );
    auditor.found(CHECK, AuditFamily::DisagreeingDuplicates, vec![finding]);
}

fn check_multiple_reconciles(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/duplicates/multiple_reconciles";
    if !matches!(route, RouteId::CalloutTop | RouteId::CalloutByUser) {
        auditor.clear(
            CHECK,
            AuditFamily::DisagreeingDuplicates,
            "callout-only check",
        );
        return;
    }
    let mut decidable = 0usize;
    let mut findings = Vec::new();
    for row in &parsed.rows {
        let multiple = row
            .fields
            .get("multiple")
            .and_then(|token| token_f64(token));
        let callout_price = row
            .fields
            .get("calloutPrice")
            .and_then(|token| token_f64(token));
        let max_price = row
            .fields
            .get("maxPriceSol")
            .and_then(|token| token_f64(token));
        let (Some(multiple), Some(callout_price), Some(max_price)) =
            (multiple, callout_price, max_price)
        else {
            continue;
        };
        if callout_price.abs() <= f64::EPSILON {
            continue;
        }
        decidable += 1;
        // The provider floors the headline at 1: a coin that never exceeded its callout price
        // reports multiple=1 with the two prices equal.
        let derived = (max_price / callout_price).max(1.0);
        let gap = (multiple - derived).abs() / derived.max(1.0);
        if gap > MULTIPLE_RECONCILE_TOLERANCE {
            findings.push(auditor.finding(
                AuditFamily::DisagreeingDuplicates,
                CHECK,
                AuditSeverity::Hazard,
                "$",
                Some("multiple"),
                Some(row.ordinal),
                &format!("multiple ~= max(maxPriceSol/calloutPrice, 1) = {derived:.4}"),
                &format!(
                    "multiple = {multiple} ({:.2}% off its own row)",
                    gap * 100.0
                ),
                "measured 2026-08-22: the headline reconciled as 4.5 vs 4.548, so it is \
                 derivable from the row and must be CHECKED rather than trusted; a row where \
                 it is not derivable is a headline from somewhere else",
            ));
        }
    }
    if decidable == 0 {
        auditor.undecidable(
            CHECK,
            AuditFamily::DisagreeingDuplicates,
            "no row carries the full multiple/calloutPrice/maxPriceSol triple with a nonzero \
             callout price, so the headline cannot be recomputed",
        );
        return;
    }
    auditor.decide(
        CHECK,
        AuditFamily::DisagreeingDuplicates,
        findings,
        &format!("the provider's multiple is derivable from its own row on all {decidable} decidable row(s)"),
    );
}

fn check_graduated_reserves(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/staleness/graduated_reserves";
    if !matches!(
        route,
        RouteId::CoinExact | RouteId::DiscoveryCoins | RouteId::CurrentlyLive | RouteId::CoinSearch
    ) {
        auditor.clear(
            CHECK,
            AuditFamily::StalenessThatLooksLive,
            "coin-route-only check",
        );
        return;
    }
    let reserve_fields = [
        "virtual_sol_reserves",
        "virtual_token_reserves",
        "virtual_quote_reserves",
        "real_sol_reserves",
        "real_token_reserves",
        "real_quote_reserves",
    ];
    let mut frozen_rows = 0usize;
    let mut first = None;
    for row in &parsed.rows {
        let graduated = row
            .fields
            .get("complete")
            .is_some_and(|token| token == "true");
        let carries_reserves = reserve_fields
            .iter()
            .any(|field| row.fields.get(*field).is_some_and(|token| token != "null"));
        if graduated && carries_reserves {
            frozen_rows += 1;
            first.get_or_insert(row.ordinal);
        }
    }
    if frozen_rows == 0 {
        auditor.clear(
            CHECK,
            AuditFamily::StalenessThatLooksLive,
            "no graduated row presents a reserve quartet",
        );
        return;
    }
    let finding = auditor.finding(
        AuditFamily::StalenessThatLooksLive,
        CHECK,
        AuditSeverity::Hazard,
        "$",
        Some("virtual_sol_reserves"),
        first,
        "reserves only where the provider still maintains them",
        &format!(
            "{frozen_rows} graduated row(s) still present reserve fields, which are frozen \
             launch constants"
        ),
        "measured 2026-08-22: a graduated coin kept launch-constant reserves \
         (virtual_sol_reserves=30000000000, real_sol_reserves=0) while its market cap fell 97% \
         in 97 seconds; crate::reserves refuses to assemble these into curve state",
    );
    auditor.found(CHECK, AuditFamily::StalenessThatLooksLive, vec![finding]);
}

fn check_unknown_curve_state(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/staleness/unknown_curve_state";
    if !matches!(
        route,
        RouteId::CoinExact | RouteId::DiscoveryCoins | RouteId::CurrentlyLive | RouteId::CoinSearch
    ) {
        auditor.clear(
            CHECK,
            AuditFamily::StalenessThatLooksLive,
            "coin-route-only check",
        );
        return;
    }
    let mut unknown_rows = 0usize;
    let mut first = None;
    for row in &parsed.rows {
        let complete_readable = row
            .fields
            .get("complete")
            .is_some_and(|token| token == "true" || token == "false");
        let carries_reserves = row
            .fields
            .get("virtual_sol_reserves")
            .is_some_and(|token| token != "null");
        if carries_reserves && !complete_readable {
            unknown_rows += 1;
            first.get_or_insert(row.ordinal);
        }
    }
    if unknown_rows == 0 {
        auditor.clear(
            CHECK,
            AuditFamily::StalenessThatLooksLive,
            "every row presenting reserves also states its curve state",
        );
        return;
    }
    let finding = auditor.finding(
        AuditFamily::StalenessThatLooksLive,
        CHECK,
        AuditSeverity::Hazard,
        "$",
        Some("complete"),
        first,
        "a readable `complete` flag wherever reserves are presented",
        &format!("{unknown_rows} row(s) present reserves with no readable curve state"),
        "an unknown curve state is not a live one (crate::reserves); reserves of unknown \
         state are never a price input",
    );
    auditor.found(CHECK, AuditFamily::StalenessThatLooksLive, vec![finding]);
}

fn check_homonyms(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/homonyms/cross_route_meaning";
    let mut findings = Vec::new();
    for homonym in HOMONYMS {
        let Some((_, here)) = homonym
            .meanings
            .iter()
            .find(|(meaning_route, _)| *meaning_route == route)
        else {
            continue;
        };
        let carried = parsed
            .rows
            .iter()
            .find(|row| row.fields.contains_key(homonym.field));
        let Some(row) = carried else { continue };
        let elsewhere = homonym
            .meanings
            .iter()
            .filter(|(meaning_route, _)| *meaning_route != route)
            .map(|(meaning_route, meaning)| format!("{meaning_route}: {meaning}"))
            .collect::<Vec<_>>()
            .join("; ");
        findings.push(auditor.finding(
            AuditFamily::SemanticDriftAcrossRoutes,
            CHECK,
            homonym.severity,
            "$",
            Some(homonym.field),
            Some(row.ordinal),
            &format!("on this route `{}` means: {here}", homonym.field),
            &format!("the SAME name elsewhere means: {elsewhere}"),
            homonym.evidence,
        ));
    }
    auditor.decide(
        CHECK,
        AuditFamily::SemanticDriftAcrossRoutes,
        findings,
        "no field of this body is a registered cross-route homonym",
    );
}

fn check_fee_leg_wedge(auditor: &mut Auditor, route: RouteId, parsed: &ParsedBody) {
    const CHECK: &str = "audit/leg/fee_wedge";
    if route != RouteId::Trades {
        auditor.clear(
            CHECK,
            AuditFamily::LegReferenceMismatch,
            "trades-only check",
        );
        return;
    }
    let mut gaps_bps = Vec::new();
    for row in &parsed.rows {
        let price = row
            .fields
            .get("priceSol")
            .and_then(|token| token_f64(token));
        let fill = row
            .fields
            .get("fillPriceSol")
            .and_then(|token| token_f64(token));
        let (Some(price), Some(fill)) = (price, fill) else {
            continue;
        };
        if price.abs() <= f64::EPSILON {
            continue;
        }
        gaps_bps.push(((fill / price) - 1.0).abs() * 10_000.0);
    }
    let count = gaps_bps.len();
    let Some((median, max)) = median_and_max(&mut gaps_bps) else {
        auditor.undecidable(
            CHECK,
            AuditFamily::LegReferenceMismatch,
            "no row carries both priceSol and fillPriceSol, so the leg wedge is not measurable \
             from this page",
        );
        return;
    };
    let finding = auditor.finding(
        AuditFamily::LegReferenceMismatch,
        CHECK,
        AuditSeverity::Observation,
        "$/trades",
        Some("fillPriceSol"),
        None,
        "two stated legs whose gap is the venue fee, kept apart",
        &format!("over {count} row(s): |fill/price - 1| median {median:.1} bps, max {max:.1} bps"),
        "the pool price and the taker's fill are DIFFERENT LEGS of the same trade; tape and \
         swap-api once disagreed by exactly the pool fee because one stated the reserve-delta \
         leg and the other the trader leg — this wedge is that fee, measured from retained \
         bytes, and mixing the legs across sources reproduces the mismatch",
    );
    auditor.found(CHECK, AuditFamily::LegReferenceMismatch, vec![finding]);
}

fn check_occurrence_without_availability(
    auditor: &mut Auditor,
    route: RouteId,
    parsed: &ParsedBody,
) {
    const CHECK: &str = "audit/clock_gaps/occurrence_without_availability";
    if !matches!(
        route,
        RouteId::CalloutTop | RouteId::CalloutByUser | RouteId::CalloutLeaderboard
    ) {
        auditor.clear(CHECK, AuditFamily::ClockGaps, "callout-route-only check");
        return;
    }
    if parsed.rows.is_empty() {
        auditor.clear(CHECK, AuditFamily::ClockGaps, "no rows carry any clock");
        return;
    }
    let finding = auditor.finding(
        AuditFamily::ClockGaps,
        CHECK,
        AuditSeverity::Observation,
        "$",
        Some("createdAt"),
        None,
        "both an occurrence clock and an availability clock",
        "every clock on this route is an occurrence time; nothing states when the provider \
         learned of a callout or made it visible",
        "measured 2026-08-22: a t=0 built from createdAt is \"the callout says it happened \
         then\", never \"we could have known then\"; the only availability instant is our own \
         receivedAt, and every study on this route must state that confound",
    );
    auditor.found(CHECK, AuditFamily::ClockGaps, vec![finding]);
}

/// The checks this audit structurally cannot run over one retained acquisition, named per route.
fn not_examined(route: RouteId) -> Vec<NotExaminedV1> {
    let mut entries = vec![NotExaminedV1 {
        check_id: "audit/selection/recall".to_owned(),
        family: AuditFamily::SelectionRecallGap,
        reason: "what a selection convention (a searchTerm sweep, `LIKE '%pump'`) fails to \
                 reach is a recall measurement against an independent enumeration; no single \
                 retained acquisition can decide it"
            .to_owned(),
    }];
    if matches!(
        route,
        RouteId::CoinExact | RouteId::DiscoveryCoins | RouteId::CurrentlyLive | RouteId::CoinSearch
    ) {
        entries.push(NotExaminedV1 {
            check_id: "audit/staleness/flag_truth".to_owned(),
            family: AuditFamily::StalenessThatLooksLive,
            reason: "whether `complete` and the fee fields reflect chain state needs the \
                     chain: the frontend flag was wrong for 3 of 12 coins and the Global \
                     account declares creator fee 5 where the program applies 30; a product \
                     read alone cannot see either"
                .to_owned(),
        });
    }
    // `audit/narrowing/limit_clamp` used to be named here: the requested limit survived only
    // inside the one-way request fingerprint, so a silent clamp was structurally undecidable.
    // Since the catalog began declaring page-shape parameters public and the envelope began
    // restating them (`resolvedPublicQuery`), that check RUNS — and reports UNDECIDABLE with
    // its reason on envelopes that predate the field, never a pass.
    if matches!(route, RouteId::Trades | RouteId::Candles) {
        entries.push(NotExaminedV1 {
            check_id: "audit/leg/cross_source".to_owned(),
            family: AuditFamily::LegReferenceMismatch,
            reason: "which price leg ANOTHER source states (reserve-delta vs trader leg) is a \
                     two-source comparison; one retained acquisition carries only its own legs"
                .to_owned(),
        });
    }
    entries
}

/// Audit one retained fetch outcome: every attempt, plus the outcome-level absence accounting.
///
/// # Errors
///
/// Returns an error when any attempt names a route outside the pinned catalog or the decision
/// timestamp is not canonical.
pub fn audit_fetch_outcome(
    outcome: &FetchOutcome,
    reviews: &[SuppliedReview],
    decided_at: &str,
) -> Result<OutcomeAuditV1, TrustError> {
    const GAP_CHECK: &str = "audit/absence/outcome_gap_accounting";
    if !crate::trust::is_canonical_utc(decided_at) {
        return Err(TrustError::DecidedAt);
    }
    let mut attempt_audits = Vec::new();
    for attempt in &outcome.attempts {
        let review = select_review(reviews, &attempt.route_id);
        attempt_audits.push(audit_acquisition(attempt, review, decided_at)?);
    }
    let route_id = outcome
        .attempts
        .first()
        .map_or_else(|| "outcome".to_owned(), |attempt| attempt.route_id.clone());
    let mut checks = Vec::new();
    let mut findings = Vec::new();
    let locus = |pointer: &str| AuditLocus {
        route_id: route_id.clone(),
        pointer: pointer.to_owned(),
        field: None,
        row_ordinal: None,
    };

    if outcome.attempts.is_empty() {
        findings.push(AuditFinding {
            family: AuditFamily::AbsenceThatLooksLikeData,
            check_id: GAP_CHECK.to_owned(),
            severity: AuditSeverity::Defect,
            locus: locus("outcome:attempts"),
            expected: "at least one retained attempt".to_owned(),
            found: "an outcome with no attempt at all".to_owned(),
            evidence: "an outcome that retained nothing asserts nothing; treating it as a \
                       completed read is absence wearing data's envelope"
                .to_owned(),
        });
    }
    if outcome.completed && outcome.coverage_windows.is_empty() {
        findings.push(AuditFinding {
            family: AuditFamily::AbsenceThatLooksLikeData,
            check_id: GAP_CHECK.to_owned(),
            severity: AuditSeverity::Hazard,
            locus: locus("outcome:coverageWindows"),
            expected: "a completed outcome stating what it covered".to_owned(),
            found: "completed=true with no coverage window".to_owned(),
            evidence: "completion without a coverage statement cannot be distinguished later \
                       from a read that covered nothing"
                .to_owned(),
        });
    }
    if !outcome.completed && outcome.coverage_gaps.is_empty() {
        findings.push(AuditFinding {
            family: AuditFamily::AbsenceThatLooksLikeData,
            check_id: GAP_CHECK.to_owned(),
            severity: AuditSeverity::Hazard,
            locus: locus("outcome:coverageGaps"),
            expected: "an incomplete outcome recording a durable gap".to_owned(),
            found: "completed=false with no recorded coverage gap".to_owned(),
            evidence: "a failed cycle must be a durable gap, never a silence; a silent stop \
                       is indistinguishable from a still market"
                .to_owned(),
        });
    }
    if findings.is_empty() {
        checks.push(AuditCheckRecord {
            check_id: GAP_CHECK.to_owned(),
            family: AuditFamily::AbsenceThatLooksLikeData,
            verdict: CheckVerdict::Clear,
            detail: "attempts, coverage windows and gaps account for what happened".to_owned(),
        });
    } else {
        checks.push(AuditCheckRecord {
            check_id: GAP_CHECK.to_owned(),
            family: AuditFamily::AbsenceThatLooksLikeData,
            verdict: CheckVerdict::Findings,
            detail: format!("{} finding(s)", findings.len()),
        });
    }

    Ok(OutcomeAuditV1 {
        contract: OUTCOME_AUDIT_V1.to_owned(),
        schema_version: "1".to_owned(),
        audit_id: format!("audit:pump-outcome:{}", outcome.request_group_id),
        request_group_id: outcome.request_group_id.clone(),
        decided_at: decided_at.to_owned(),
        outcome_checks: checks,
        outcome_findings: findings,
        not_examined: vec![NotExaminedV1 {
            check_id: "audit/absence/stream_coverage".to_owned(),
            family: AuditFamily::AbsenceThatLooksLikeData,
            reason: "subscription acknowledgement versus per-subject delivery (453 trades on \
                     one source, zero frames on the subscribed one) lives on the websocket \
                     path, outside this record shape entirely"
                .to_owned(),
        }],
        attempt_audits,
    })
}

/// The review whose route matches, preferring the kind measured to govern that route when both
/// kinds are supplied.
#[must_use]
pub fn select_review<'a>(
    reviews: &'a [SuppliedReview],
    route_id: &str,
) -> Option<&'a SuppliedReview> {
    let matching: Vec<&SuppliedReview> = reviews
        .iter()
        .filter(|review| review.route_id() == route_id)
        .collect();
    if matching.len() > 1
        && let Ok(route) = route_id.parse::<RouteId>()
    {
        let preferred = match governing_gate(route) {
            GateKind::RowProjection => matching
                .iter()
                .find(|review| matches!(review, SuppliedReview::Rows(_))),
            GateKind::DocumentFingerprint => matching
                .iter()
                .find(|review| matches!(review, SuppliedReview::Document(_))),
            GateKind::Unmeasured => None,
        };
        if let Some(review) = preferred {
            return Some(review);
        }
    }
    matching.into_iter().next()
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine as _;

    const DECIDED_AT: &str = "2026-08-23T12:00:00.000000Z";

    fn acquisition(route: RouteId, body: &[u8]) -> Acquisition {
        Acquisition {
            contract: "joshi.pump_api.acquisition.v1".to_owned(),
            catalog_version: ROUTE_CATALOG.to_owned(),
            acquisition_id: "acq:test:1".to_owned(),
            request_group_id: "reqgrp:test:1".to_owned(),
            attempt_ordinal: "1".to_owned(),
            route_id: route.to_string(),
            transport: "http".to_owned(),
            access_class: "observed_public_product".to_owned(),
            stability: "undocumented_observed".to_owned(),
            session_class: "public".to_owned(),
            source_locator: "https://frontend-api-v3.pump.fun/test".to_owned(),
            resolved_public_path: BTreeMap::new(),
            resolved_public_query: BTreeMap::new(),
            request_fingerprint: sha256(b"test"),
            http_status: Some(200),
            safe_response_headers: vec![crate::model::SafeHeader {
                name: "date".to_owned(),
                value: "Sun, 23 Aug 2026 11:59:59 GMT".to_owned(),
            }],
            clocks: crate::model::AcquisitionClocks {
                started_at: "2026-08-23T11:59:59.000000Z".to_owned(),
                received_at: "2026-08-23T12:00:00.000000Z".to_owned(),
                monotonic_clock_id: "test-clock".to_owned(),
                started_monotonic_ns: "0".to_owned(),
                received_monotonic_ns: "1000000000".to_owned(),
                elapsed_ns: "1000000000".to_owned(),
            },
            body: BodyCapture::Exact {
                boundary: "http_entity_body_post_transfer_decoding_identity_encoding".to_owned(),
                media_type: "application/json".to_owned(),
                bytes_base64: base64::engine::general_purpose::STANDARD.encode(body),
                byte_length: body.len().to_string(),
                blob_id: sha256(body),
            },
        }
    }

    fn findings_for<'a>(audit: &'a AcquisitionAuditV1, check_id: &str) -> Vec<&'a AuditFinding> {
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
            .map(|check| check.verdict)
            .expect("every known check is recorded")
    }

    /// Family 3, the January-1970 signature: a declared-seconds clock carrying a millis value
    /// and vice versa are both defects, while the measured mix itself is a standing hazard.
    #[test]
    fn unit_mismatch_lands_as_a_defect_with_both_datings() {
        // updated_at is declared SECONDS; give it a millisecond magnitude.
        let body = br#"[{"mint":"M1","complete":false,"created_timestamp":1787352121000,"updated_at":1787352121000}]"#;
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, body),
            None,
            DECIDED_AT,
        )
        .unwrap();
        let findings = findings_for(&audit, "audit/units/declared_clock_plausibility");
        assert_eq!(findings.len(), 1, "one aggregated finding for updated_at");
        assert_eq!(findings[0].severity, AuditSeverity::Defect);
        assert_eq!(findings[0].locus.field.as_deref(), Some("updated_at"));
        assert!(findings[0].found.contains("January-1970 signature"));
    }

    #[test]
    fn plausible_declared_clocks_and_the_mixed_unit_trap_both_report() {
        let body = br#"[{"mint":"M1","complete":false,"created_timestamp":1787352121000,"updated_at":1787352121}]"#;
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, body),
            None,
            DECIDED_AT,
        )
        .unwrap();
        assert_eq!(
            verdict(&audit, "audit/units/declared_clock_plausibility"),
            CheckVerdict::Clear
        );
        // The row carries both units at once: the standing measured trap.
        let mixed = findings_for(&audit, "audit/units/mixed_units_on_row");
        assert_eq!(mixed.len(), 1);
        assert_eq!(mixed[0].severity, AuditSeverity::Hazard);
    }

    /// Family 1: candles bytes cannot name their coin, so an envelope that does not restate the
    /// requested mint is an identity gap; restating it clears the check.
    #[test]
    fn identity_gap_clears_when_the_envelope_restates_the_subject() {
        let body = br#"[{"timestamp":1787352121000,"open":"1","high":"1","low":"1","close":"1","volume":"1"}]"#;
        let bare = acquisition(RouteId::Candles, body);
        let audit = audit_acquisition(&bare, None, DECIDED_AT).unwrap();
        let gap = findings_for(&audit, "audit/identity_gap/subject_restated");
        assert_eq!(gap.len(), 1);
        assert_eq!(gap[0].severity, AuditSeverity::Gap);

        let mut restated = bare;
        restated
            .resolved_public_path
            .insert("mint".to_owned(), "Mint111".to_owned());
        let audit = audit_acquisition(&restated, None, DECIDED_AT).unwrap();
        assert_eq!(
            verdict(&audit, "audit/identity_gap/subject_restated"),
            CheckVerdict::Clear
        );
    }

    /// Family 6: an empty discovery page refuses to be read as absence.
    #[test]
    fn empty_page_is_a_hazard_not_a_result() {
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, b"[]"),
            None,
            DECIDED_AT,
        )
        .unwrap();
        let findings = findings_for(&audit, "audit/absence/empty_page");
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].severity, AuditSeverity::Hazard);
    }

    /// Family 7: zero rows out of a body that carries a nonempty array somewhere is the shape
    /// of the candles envelope misread, and it is a defect.
    #[test]
    fn container_zero_rows_with_content_elsewhere_is_a_defect() {
        // trades reader looks under `trades`; put rows under a different key.
        let body = br#"{"rows":[{"a":1},{"a":2}],"pagination":{"hasMore":true}}"#;
        let audit =
            audit_acquisition(&acquisition(RouteId::Trades, body), None, DECIDED_AT).unwrap();
        let findings = findings_for(&audit, "audit/narrowing/container_rows");
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].severity, AuditSeverity::Defect);
        assert!(findings[0].found.contains("$/rows"));
    }

    /// Family 6: multiple=1 is a floor bin, not a missing value.
    #[test]
    fn multiple_floor_is_counted_as_its_own_bin() {
        let body = br#"{"callouts":[{"coinMint":"M1","multiple":1,"calloutPrice":2.0,"maxPriceSol":2.0,"createdAt":1787352121000},{"coinMint":"M2","multiple":4.5,"calloutPrice":1.0,"maxPriceSol":4.548,"createdAt":1787352121000}]}"#;
        let audit =
            audit_acquisition(&acquisition(RouteId::CalloutTop, body), None, DECIDED_AT).unwrap();
        let floor = findings_for(&audit, "audit/absence/multiple_floor");
        assert_eq!(floor.len(), 1);
        assert!(floor[0].found.contains("1 row(s)"));
        // And the derivable headline reconciles within tolerance on both rows.
        assert_eq!(
            verdict(&audit, "audit/duplicates/multiple_reconciles"),
            CheckVerdict::Clear
        );
    }

    /// Family 4: a headline that is not derivable from its own row is a hazard.
    #[test]
    fn irreconcilable_multiple_is_flagged() {
        let body = br#"{"callouts":[{"coinMint":"M1","multiple":9.0,"calloutPrice":1.0,"maxPriceSol":4.5,"createdAt":1787352121000}]}"#;
        let audit =
            audit_acquisition(&acquisition(RouteId::CalloutTop, body), None, DECIDED_AT).unwrap();
        let findings = findings_for(&audit, "audit/duplicates/multiple_reconciles");
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].severity, AuditSeverity::Hazard);
    }

    /// Family 4: the usd pair disagreement is measured, and the nine-percentage-point class
    /// elevates to a defect while the census-ordinary class stays an observation.
    #[test]
    fn usd_pair_gap_is_measured_and_escalates_on_the_alarm_class() {
        let ordinary =
            br#"[{"mint":"M1","complete":false,"market_cap_usd":1000.0,"usd_market_cap":1001.0}]"#;
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, ordinary),
            None,
            DECIDED_AT,
        )
        .unwrap();
        let findings = findings_for(&audit, "audit/duplicates/usd_market_cap_pair");
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].severity, AuditSeverity::Observation);

        let alarm =
            br#"[{"mint":"M1","complete":false,"market_cap_usd":1000.0,"usd_market_cap":1090.0}]"#;
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, alarm),
            None,
            DECIDED_AT,
        )
        .unwrap();
        let findings = findings_for(&audit, "audit/duplicates/usd_market_cap_pair");
        assert_eq!(findings[0].severity, AuditSeverity::Defect);
    }

    /// Family 5: a graduated row still presenting reserves is the frozen-launch-constant trap.
    #[test]
    fn graduated_reserves_are_flagged_as_stale_presented_live() {
        let body = br#"[{"mint":"M1","complete":true,"virtual_sol_reserves":30000000000,"real_sol_reserves":0,"usd_market_cap":3000000.0}]"#;
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, body),
            None,
            DECIDED_AT,
        )
        .unwrap();
        let findings = findings_for(&audit, "audit/staleness/graduated_reserves");
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].severity, AuditSeverity::Hazard);
    }

    /// Family 2: `multiple` on the by-user route is flagged as a registered homonym.
    #[test]
    fn homonym_multiple_is_surfaced_with_both_meanings() {
        let body = br#"{"callouts":[{"coinMint":"M1","multiple":2.0,"maxMultiplier":3.0,"createdAt":1787352121000}]}"#;
        let audit = audit_acquisition(&acquisition(RouteId::CalloutByUser, body), None, DECIDED_AT)
            .unwrap();
        let findings = findings_for(&audit, "audit/homonyms/cross_route_meaning");
        assert!(
            findings
                .iter()
                .any(|finding| finding.locus.field.as_deref() == Some("multiple")),
            "multiple is a registered homonym"
        );
    }

    /// A non-2xx body records every content check as undecidable, never as clear.
    #[test]
    fn error_bodies_make_content_checks_undecidable_not_green() {
        let mut refused = acquisition(RouteId::DiscoveryCoins, br#"{"statusCode":400}"#);
        refused.http_status = Some(400);
        let audit = audit_acquisition(&refused, None, DECIDED_AT).unwrap();
        for (check_id, _) in CONTENT_CHECKS {
            assert_eq!(
                verdict(&audit, check_id),
                CheckVerdict::Undecidable,
                "{check_id} must refuse, not pass, over an error body"
            );
        }
    }

    /// Family 8: a whole-document review supplied for a heterogeneous feed is the measured
    /// wrong gate.
    #[test]
    fn document_review_over_heterogeneous_rows_is_the_wrong_gate() {
        let review = SuppliedReview::Document(SchemaReviewV1 {
            contract: crate::trust::SCHEMA_REVIEW_V1.to_owned(),
            schema_version: "1".to_owned(),
            review_id: "review:test".to_owned(),
            route_id: RouteId::DiscoveryCoins.to_string(),
            catalog_version: ROUTE_CATALOG.to_owned(),
            schema_fingerprint: crate::normalize::fingerprint_of_shape(&["$:array".to_owned()]),
            reviewed_shape: vec!["$:array".to_owned()],
            reviewer: "test".to_owned(),
            reviewed_at: DECIDED_AT.to_owned(),
            decision: SchemaTrustOutcome::Promoted,
            rationale: "test".to_owned(),
        });
        let body = br#"[{"mint":"M1","complete":false}]"#;
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, body),
            Some(&review),
            DECIDED_AT,
        )
        .unwrap();
        let findings = findings_for(&audit, "audit/gate/review_kind");
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].severity, AuditSeverity::Defect);
    }

    /// Outcome-level family 6: an incomplete outcome with no recorded gap is a silence.
    #[test]
    fn incomplete_outcome_without_a_gap_is_a_silence_finding() {
        let outcome = FetchOutcome {
            contract: "joshi.pump_api.fetch_outcome.v1".to_owned(),
            request_group_id: "reqgrp:test:1".to_owned(),
            attempts: vec![acquisition(RouteId::DiscoveryCoins, b"[]")],
            coverage_windows: Vec::new(),
            coverage_gaps: Vec::new(),
            completed: false,
        };
        let audit = audit_fetch_outcome(&outcome, &[], DECIDED_AT).unwrap();
        assert!(
            audit
                .outcome_findings
                .iter()
                .any(|finding| finding.found.contains("no recorded coverage gap"))
        );
    }

    /// The undecidable discipline: no review means the gate checks refuse rather than pass.
    #[test]
    fn missing_review_is_undecidable_never_clear() {
        let audit = audit_acquisition(
            &acquisition(
                RouteId::DiscoveryCoins,
                br#"[{"mint":"M1","complete":false}]"#,
            ),
            None,
            DECIDED_AT,
        )
        .unwrap();
        assert_eq!(
            verdict(&audit, "audit/gate/review_kind"),
            CheckVerdict::Undecidable
        );
        assert_eq!(
            verdict(&audit, "audit/gate/decision_replay"),
            CheckVerdict::Undecidable
        );
    }

    /// Every audit names what it could not examine, so a passing report still shows its edges.
    #[test]
    fn not_examined_names_the_cross_source_boundary() {
        let audit = audit_acquisition(
            &acquisition(
                RouteId::DiscoveryCoins,
                br#"[{"mint":"M1","complete":false}]"#,
            ),
            None,
            DECIDED_AT,
        )
        .unwrap();
        let ids: Vec<&str> = audit
            .not_examined
            .iter()
            .map(|entry| entry.check_id.as_str())
            .collect();
        assert!(ids.contains(&"audit/selection/recall"));
        assert!(ids.contains(&"audit/staleness/flag_truth"));
        assert!(
            !ids.contains(&"audit/narrowing/limit_clamp"),
            "the clamp check runs now that retention restates the ask; it no longer hides in \
             the structural boundary"
        );
    }

    /// Family 7, made decidable by retention: an envelope that restates its requested limit
    /// convicts the measured /coins clamp, naming both numbers.
    #[test]
    fn a_retained_limit_convicts_the_measured_discovery_clamp() {
        let rows: Vec<String> = (0..70)
            .map(|ordinal| format!(r#"{{"mint":"M{ordinal}","complete":false}}"#))
            .collect();
        let body = format!("[{}]", rows.join(","));
        let mut clamped = acquisition(RouteId::DiscoveryCoins, body.as_bytes());
        clamped
            .resolved_public_query
            .insert("limit".to_owned(), "1000".to_owned());
        let audit = audit_acquisition(&clamped, None, DECIDED_AT).unwrap();
        let findings = findings_for(&audit, "audit/narrowing/limit_clamp");
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].severity, AuditSeverity::Defect);
        assert!(findings[0].expected.contains("1000"));
        assert!(findings[0].found.contains("70 rows"));
        assert!(findings[0].found.contains("clamp of 70"));
    }

    /// The same bytes without the retained ask stay UNDECIDABLE with the reason — the check
    /// never becomes decidable for records that lack the data.
    #[test]
    fn an_envelope_without_the_ask_keeps_the_clamp_undecidable() {
        let body = br#"[{"mint":"M1","complete":false}]"#;
        let audit = audit_acquisition(
            &acquisition(RouteId::DiscoveryCoins, body),
            None,
            DECIDED_AT,
        )
        .unwrap();
        assert_eq!(
            verdict(&audit, "audit/narrowing/limit_clamp"),
            CheckVerdict::Undecidable
        );
        let detail = &audit
            .checks
            .iter()
            .find(|check| check.check_id == "audit/narrowing/limit_clamp")
            .unwrap()
            .detail;
        assert!(detail.contains("resolvedPublicQuery"));
    }

    /// A short page that is not the measured clamp value cannot be told apart from the
    /// population tail by one acquisition, and an exactly-honoured limit is clear.
    #[test]
    fn short_pages_stay_ambiguous_and_honoured_limits_clear() {
        let mut short = acquisition(
            RouteId::DiscoveryCoins,
            br#"[{"mint":"M1","complete":false},{"mint":"M2","complete":false}]"#,
        );
        short
            .resolved_public_query
            .insert("limit".to_owned(), "50".to_owned());
        let audit = audit_acquisition(&short, None, DECIDED_AT).unwrap();
        assert_eq!(
            verdict(&audit, "audit/narrowing/limit_clamp"),
            CheckVerdict::Undecidable
        );

        let mut honoured = acquisition(
            RouteId::DiscoveryCoins,
            br#"[{"mint":"M1","complete":false},{"mint":"M2","complete":false}]"#,
        );
        honoured
            .resolved_public_query
            .insert("limit".to_owned(), "2".to_owned());
        let audit = audit_acquisition(&honoured, None, DECIDED_AT).unwrap();
        assert_eq!(
            verdict(&audit, "audit/narrowing/limit_clamp"),
            CheckVerdict::Clear
        );
    }
}
