//! Walking one mint's trade history backwards on the provider's own exclusive keyset cursor.
//!
//! The candle route cannot reach the past: it hands back one newest-anchored window of at most
//! 1000 gap-compressed bars and its `before` argument was measured inert, so on a busy coin it is
//! permanently seventeen minutes wide. The trade route can, because `pagination.nextCursor` is the
//! reconstructible exclusive keyset `slotIndexId-epochMillis` of the last returned row. This
//! module owns the record of one such walk.
//!
//! Nothing here decides that a walk is complete. A walk stops, and the reason it stopped is a
//! durable assertion bound to the last page it actually read. A walk that ends without that
//! assertion did not stop, it died, and the difference is meant to be visible on disk.

use std::collections::BTreeSet;

use joshi_domain::UtcTimestamp;
use joshi_pump_api::{Acquisition, SchemaTrustDecisionV1};
use serde::{Deserialize, Serialize};

use crate::{PumpAdapterError, TRADES_BACKFILL_WALK_V1};

/// Why a walk stopped. Every variant is written down; none of them is silence.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WalkStop {
    /// The caller's hard ceiling on provider requests was reached.
    RequestBudgetExhausted,
    /// The caller's hard ceiling on wall-clock time was reached.
    WallClockBudgetExhausted,
    /// The caller's hard ceiling on pages was reached.
    PageBudgetExhausted,
    /// The walk reached the instant the caller asked it to stop before.
    HorizonReached,
    /// The provider answered, and its own `hasMore` said there is nothing older.
    ProviderReportedNoMore,
    /// A promoted page carried no continuation cursor, so there is nowhere older to ask for.
    CursorAbsent,
    /// A page's schema did not match the reviewed shape. The bytes are retained and the walk
    /// stops; widening a review is a human act, not a walker's.
    SchemaRefusedPendingReview,
    /// The provider did not return a usable success body for this page.
    ProviderRefused,
    /// A page carried a row the previous page had already returned, so the cursor is not the
    /// exclusive keyset it was measured to be and the chain can no longer be trusted.
    PageOverlappedPrevious,
    /// A promoted page carried no rows at all.
    EmptyPage,
}

impl WalkStop {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RequestBudgetExhausted => "request_budget_exhausted",
            Self::WallClockBudgetExhausted => "wall_clock_budget_exhausted",
            Self::PageBudgetExhausted => "page_budget_exhausted",
            Self::HorizonReached => "horizon_reached",
            Self::ProviderReportedNoMore => "provider_reported_no_more",
            Self::CursorAbsent => "cursor_absent",
            Self::SchemaRefusedPendingReview => "schema_refused_pending_review",
            Self::ProviderRefused => "provider_refused",
            Self::PageOverlappedPrevious => "page_overlapped_previous",
            Self::EmptyPage => "empty_page",
        }
    }

    /// Whether this stop needs a person before the walk can be resumed or widened.
    #[must_use]
    pub const fn needs_review(self) -> bool {
        matches!(
            self,
            Self::SchemaRefusedPendingReview | Self::PageOverlappedPrevious
        )
    }
}

/// How one page sat against the page before it. Contiguity is the provider's claim, never ours:
/// an exclusive keyset proves the pages do not overlap, and proves nothing about a hole.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Adjacency {
    FirstPage,
    StrictlyOlderNoOverlap,
    Overlapped,
    NotComparable,
}

/// What one promoted trade page says about itself.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PageFacts {
    pub rows: usize,
    pub newest_key: String,
    pub oldest_key: String,
    pub newest_event_time: String,
    pub oldest_event_time: String,
    pub next_cursor: Option<String>,
    pub has_more: Option<bool>,
    /// Whether `nextCursor` really is the last row's key, as it was measured to be.
    pub cursor_matches_last_row: bool,
    row_keys: BTreeSet<String>,
}

impl PageFacts {
    /// Read one trade page's own account of itself out of exact bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the bytes are not the reviewed trade-page shape.
    pub fn from_promoted_bytes(bytes: &[u8]) -> Result<Self, PumpAdapterError> {
        let value: serde_json::Value = serde_json::from_slice(bytes)?;
        let rows = value
            .get("trades")
            .and_then(serde_json::Value::as_array)
            .ok_or_else(|| {
                PumpAdapterError::Contract("trade page carries no trades array".into())
            })?;
        let key = |row: &serde_json::Value| {
            row.get("slotIndexId")
                .and_then(serde_json::Value::as_str)
                .map(str::to_owned)
                .ok_or_else(|| {
                    PumpAdapterError::Contract("trade row carries no slotIndexId".into())
                })
        };
        let stamp = |row: &serde_json::Value| {
            row.get("timestamp")
                .and_then(serde_json::Value::as_str)
                .map(str::to_owned)
                .ok_or_else(|| PumpAdapterError::Contract("trade row carries no timestamp".into()))
        };
        let pagination = value.get("pagination");
        let next_cursor = pagination
            .and_then(|value| value.get("nextCursor"))
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned);
        let has_more = pagination
            .and_then(|value| value.get("hasMore"))
            .and_then(serde_json::Value::as_bool);
        let (Some(first), Some(last)) = (rows.first(), rows.last()) else {
            return Ok(Self {
                rows: 0,
                newest_key: String::new(),
                oldest_key: String::new(),
                newest_event_time: String::new(),
                oldest_event_time: String::new(),
                next_cursor,
                has_more,
                cursor_matches_last_row: false,
                row_keys: BTreeSet::new(),
            });
        };
        let oldest_key = key(last)?;
        let cursor_matches_last_row = next_cursor
            .as_deref()
            .is_some_and(|cursor| cursor.starts_with(oldest_key.as_str()));
        let mut row_keys = BTreeSet::new();
        for row in rows {
            row_keys.insert(key(row)?);
        }
        Ok(Self {
            rows: rows.len(),
            newest_key: key(first)?,
            oldest_key,
            newest_event_time: stamp(first)?,
            oldest_event_time: stamp(last)?,
            next_cursor,
            has_more,
            cursor_matches_last_row,
            row_keys,
        })
    }

    /// Compare this page against the keys the previous page returned.
    ///
    /// `slotIndexId` is a fixed-width lexicographic key, so ordinary string comparison is the
    /// provider's own ordering rather than a reinterpretation of it.
    #[must_use]
    pub fn adjacency_to(&self, previous: Option<&Self>) -> Adjacency {
        let Some(previous) = previous else {
            return Adjacency::FirstPage;
        };
        if self.row_keys.is_empty() || previous.row_keys.is_empty() {
            return Adjacency::NotComparable;
        }
        if !self.row_keys.is_disjoint(&previous.row_keys) {
            return Adjacency::Overlapped;
        }
        let (Some(newest_here), Some(oldest_there)) =
            (self.row_keys.last(), previous.row_keys.first())
        else {
            return Adjacency::NotComparable;
        };
        if newest_here < oldest_there {
            Adjacency::StrictlyOlderNoOverlap
        } else {
            Adjacency::Overlapped
        }
    }
}

/// One page of a walk, as it will be readable after a restart.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TradesBackfillPageV1 {
    pub ordinal: String,
    pub acquisition_id: String,
    pub http_status: Option<String>,
    pub body_blob_id: Option<String>,
    /// The cursor this page was asked for with, absent on the first page. Retained as a digest
    /// because the catalog marks a cursor sensitive.
    pub request_cursor_fingerprint: Option<String>,
    pub next_cursor_fingerprint: Option<String>,
    pub cursor_matches_last_row: Option<bool>,
    pub rows: Option<String>,
    pub newest_event_time: Option<String>,
    pub oldest_event_time: Option<String>,
    pub adjacency: Adjacency,
    pub schema_trust_outcome: String,
    pub schema_trust_reason: String,
    pub observed_schema_fingerprint: Option<String>,
}

/// One completed backwards walk over a mint's trade history.
///
/// Every count here is of what actually happened, not of what was planned. `covered_span_ms` is
/// the distance between the newest and oldest retained rows, so the request cost of an hour of
/// tape is a division rather than an estimate.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TradesBackfillWalkV1 {
    pub contract: String,
    pub schema_version: String,
    pub walk_id: String,
    pub route_id: String,
    pub catalog_version: String,
    pub subject_kind: String,
    pub subject: String,
    pub page_limit: String,
    pub started_at: String,
    pub ended_at: String,
    pub requests_used: String,
    pub request_budget: String,
    pub elapsed_ms: String,
    pub wall_budget_ms: String,
    pub pages_attempted: String,
    pub pages_promoted: String,
    pub rows_retained: String,
    pub newest_event_time: Option<String>,
    pub oldest_event_time: Option<String>,
    pub covered_span_ms: Option<String>,
    /// Requests spent per hour of retained tape, to three decimals. Absent when the walk covered
    /// no measurable span.
    pub requests_per_hour_of_tape: Option<String>,
    pub stop: WalkStop,
    pub stop_detail: String,
    /// Present when the walk stopped on a shape a person has to look at before it can continue.
    pub unreviewed_schema_fingerprint: Option<String>,
    pub pages: Vec<TradesBackfillPageV1>,
}

impl TradesBackfillWalkV1 {
    /// Semantic key this walk is readable under after a restart.
    ///
    /// The walk id is part of the key on purpose: two walks over one mint are two separate
    /// observations of a moving history, and collapsing them under one key would need a real
    /// supersession chain that nothing here has earned.
    #[must_use]
    pub fn semantic_key(&self) -> String {
        format!(
            "pump.trades_backfill:{}:{}:{}",
            self.subject_kind, self.subject, self.walk_id
        )
    }

    #[must_use]
    pub fn assertion_id(&self) -> String {
        format!("assertion:pump-trades-backfill:{}", self.walk_id)
    }

    /// Check the internal arithmetic of a walk record before it is trusted.
    ///
    /// # Errors
    ///
    /// Returns an error when the page list disagrees with the totals it claims.
    pub fn validate(&self) -> Result<(), PumpAdapterError> {
        if self.contract != TRADES_BACKFILL_WALK_V1 || self.schema_version != "1" {
            return Err(PumpAdapterError::Contract(
                "trades backfill walk contract/version mismatch".into(),
            ));
        }
        if self.pages.len().to_string() != self.pages_attempted {
            return Err(PumpAdapterError::Contract(
                "walk page list disagrees with the attempt count it claims".into(),
            ));
        }
        let promoted = self
            .pages
            .iter()
            .filter(|page| page.schema_trust_outcome == "promoted")
            .count();
        if promoted.to_string() != self.pages_promoted {
            return Err(PumpAdapterError::Contract(
                "walk page list disagrees with the promotion count it claims".into(),
            ));
        }
        if self.pages.is_empty() {
            return Err(PumpAdapterError::Contract(
                "a walk record must name at least the page it stopped on".into(),
            ));
        }
        Ok(())
    }
}

/// Build the page record for one attempted page.
#[must_use]
pub fn page_record(
    ordinal: usize,
    acquisition: &Acquisition,
    decision: &SchemaTrustDecisionV1,
    facts: Option<&PageFacts>,
    adjacency: Adjacency,
    request_cursor_fingerprint: Option<String>,
) -> TradesBackfillPageV1 {
    TradesBackfillPageV1 {
        ordinal: ordinal.to_string(),
        acquisition_id: acquisition.acquisition_id.clone(),
        http_status: acquisition.http_status.map(|status| status.to_string()),
        body_blob_id: acquisition.body.blob_id().map(str::to_owned),
        request_cursor_fingerprint,
        next_cursor_fingerprint: facts
            .and_then(|facts| facts.next_cursor.as_deref())
            .map(|cursor| joshi_pump_api::client::sha256(cursor.as_bytes())),
        cursor_matches_last_row: facts.map(|facts| facts.cursor_matches_last_row),
        rows: facts.map(|facts| facts.rows.to_string()),
        newest_event_time: facts.map(|facts| facts.newest_event_time.clone()),
        oldest_event_time: facts.map(|facts| facts.oldest_event_time.clone()),
        adjacency,
        schema_trust_outcome: format!("{:?}", decision.outcome).to_ascii_lowercase(),
        schema_trust_reason: decision.reason_code.clone(),
        observed_schema_fingerprint: decision.observed_schema_fingerprint.clone(),
    }
}

/// Requests spent per hour of retained tape, rendered to three decimals.
#[must_use]
pub fn requests_per_hour_of_tape(requests: u32, span_ms: i64) -> Option<String> {
    if span_ms <= 0 {
        return None;
    }
    let hours = crate::crackle::widen(span_ms) / 3_600_000.0;
    Some(format!("{:.3}", f64::from(requests) / hours))
}

/// Milliseconds between two ISO-8601 provider instants, as the provider wrote them.
///
/// # Errors
///
/// Returns an error when either instant is not RFC 3339.
pub fn span_millis(newest: &str, oldest: &str) -> Result<i64, PumpAdapterError> {
    let parse = |value: &str| {
        time::OffsetDateTime::parse(value, &time::format_description::well_known::Rfc3339)
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))
    };
    let nanos = parse(newest)?.unix_timestamp_nanos() - parse(oldest)?.unix_timestamp_nanos();
    i64::try_from(nanos / 1_000_000).map_err(|_| {
        PumpAdapterError::Contract("provider instants are implausibly far apart".into())
    })
}

/// Whether a provider instant is at or before the caller's stop-before horizon.
///
/// # Errors
///
/// Returns an error when either instant is unparseable.
pub fn at_or_before(instant: &str, horizon: UtcTimestamp) -> Result<bool, PumpAdapterError> {
    let parsed =
        time::OffsetDateTime::parse(instant, &time::format_description::well_known::Rfc3339)
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
    Ok(parsed <= horizon.as_datetime())
}

/// What one page turned out to be, as far as the walk is concerned.
#[derive(Clone, Copy, Debug)]
pub struct PageVerdict<'a> {
    pub promoted: bool,
    pub http_status: Option<u16>,
    pub trust_reason: &'a str,
    pub facts: Option<&'a PageFacts>,
    pub adjacency: Adjacency,
    /// Whether this page reached back past the caller's stop-before instant.
    pub horizon_reached: bool,
}

/// The ceilings the walk is running under, as they stand after the page just read.
#[derive(Clone, Copy, Debug)]
pub struct WalkBudgets {
    pub pages_so_far: usize,
    pub max_pages: usize,
    pub requests_used: u32,
    pub request_budget: usize,
    pub elapsed_ms: u128,
    pub wall_budget_ms: u128,
}

/// Decide whether the walk stops here, and for which written-down reason.
///
/// The order is deliberate and is the order of severity, not of convenience. A page that cannot
/// be trusted stops the walk before any budget question is asked, because continuing past an
/// unreviewed shape would spend budget accumulating pages nobody may read. A provider refusal
/// outranks a clean end for the same reason. Budgets are last: they are the only stops that mean
/// "there is more, and we chose not to fetch it".
#[must_use]
pub fn classify_stop(verdict: PageVerdict<'_>, budgets: WalkBudgets) -> Option<WalkStop> {
    if !verdict.promoted {
        let success = verdict
            .http_status
            .is_some_and(|status| (200..300).contains(&status));
        let shape_problem = matches!(
            verdict.trust_reason,
            "refused_observed_fingerprint_not_reviewed" | "refused_no_review_for_route"
        );
        return Some(if success && shape_problem {
            WalkStop::SchemaRefusedPendingReview
        } else {
            WalkStop::ProviderRefused
        });
    }
    let facts = verdict.facts?;
    if facts.rows == 0 {
        return Some(WalkStop::EmptyPage);
    }
    if verdict.adjacency == Adjacency::Overlapped {
        return Some(WalkStop::PageOverlappedPrevious);
    }
    if facts.has_more == Some(false) {
        return Some(WalkStop::ProviderReportedNoMore);
    }
    if facts.next_cursor.is_none() {
        return Some(WalkStop::CursorAbsent);
    }
    if verdict.horizon_reached {
        return Some(WalkStop::HorizonReached);
    }
    if budgets.pages_so_far >= budgets.max_pages {
        return Some(WalkStop::PageBudgetExhausted);
    }
    if budgets.requests_used as usize >= budgets.request_budget {
        return Some(WalkStop::RequestBudgetExhausted);
    }
    if budgets.elapsed_ms >= budgets.wall_budget_ms {
        return Some(WalkStop::WallClockBudgetExhausted);
    }
    None
}
