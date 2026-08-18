use crate::{CommitSeq, OpenVariant, SourceId, StableString, WireU64};
use core::fmt;
use serde::{Deserialize, Deserializer, Serialize, Serializer, de};
use std::{cmp::Ordering, collections::BTreeMap, str::FromStr};
use thiserror::Error;
use time::{OffsetDateTime, PrimitiveDateTime, UtcOffset, macros::format_description};

const WIRE_TIMESTAMP_FORMAT: &[time::format_description::BorrowedFormatItem<'static>] =
    format_description!("[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z");

/// A normalized UTC timestamp with an RFC 3339 JSON string representation.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct UtcTimestamp(OffsetDateTime);

impl UtcTimestamp {
    /// Creates a UTC timestamp from a microsecond-aligned instant.
    ///
    /// # Errors
    ///
    /// Returns an error rather than rounding when the instant has sub-microsecond precision.
    pub fn new(value: OffsetDateTime) -> Result<Self, TimestampError> {
        let value = value.to_offset(UtcOffset::UTC);
        if !value.nanosecond().is_multiple_of(1_000) {
            return Err(TimestampError(
                "instant is not aligned to an exact microsecond".into(),
            ));
        }
        Ok(Self(value))
    }

    /// Returns the normalized instant.
    #[must_use]
    pub const fn as_datetime(self) -> OffsetDateTime {
        self.0
    }
}

impl FromStr for UtcTimestamp {
    type Err = TimestampError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        PrimitiveDateTime::parse(value, WIRE_TIMESTAMP_FORMAT)
            .map(PrimitiveDateTime::assume_utc)
            .map(Self)
            .map_err(|error| TimestampError(error.to_string()))
    }
}

impl fmt::Display for UtcTimestamp {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let rendered = self
            .0
            .format(WIRE_TIMESTAMP_FORMAT)
            .map_err(|_| fmt::Error)?;
        formatter.write_str(&rendered)
    }
}

impl Serialize for UtcTimestamp {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let value = self
            .0
            .format(WIRE_TIMESTAMP_FORMAT)
            .map_err(serde::ser::Error::custom)?;
        serializer.serialize_str(&value)
    }
}

impl<'de> Deserialize<'de> for UtcTimestamp {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        value.parse().map_err(de::Error::custom)
    }
}

/// A malformed RFC 3339 timestamp.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
#[error("invalid RFC 3339 timestamp: {0}")]
pub struct TimestampError(String);

/// A source clock reading or an explicit reason that no clock was available.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum ClockReading {
    /// Exact retained source representation with named authority and precision.
    Present {
        /// Losslessly retained source value; this need not be a wall timestamp.
        value: StableString,
        /// Open-world authority discriminator such as `source_wall` or `chain_slot`.
        authority: OpenVariant,
        /// Open-world precision discriminator such as `second` or `bounded_interval`.
        precision: OpenVariant,
    },
    /// The source did not provide a reading; absence is data, not a fabricated value.
    Absent {
        /// Open-world explanation such as `not_provided` or `parse_failed`.
        reason: OpenVariant,
    },
}

/// Collector/store clocks belonging to one acquisition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AcquisitionClocks {
    /// Wall time immediately before a request, when one exists.
    pub requested_at: Option<UtcTimestamp>,
    /// Wall time when the collector received the bytes.
    pub received_at: UtcTimestamp,
    /// Wall time when the fixture or durable boundary accepted the bytes.
    pub persisted_at: UtcTimestamp,
    /// Duration in a named local monotonic domain, never compared across domains.
    pub monotonic_elapsed_ns: Option<WireU64>,
    /// Process/boot domain for the monotonic duration.
    pub monotonic_domain: Option<StableString>,
}

/// Source-native clock and ordering claims attached to an observation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SourceClock {
    /// Event-valid reading or explicit absence.
    pub event_time: ClockReading,
    /// Chain slot when applicable, serialized without JSON-number precision loss.
    pub chain_slot: Option<WireU64>,
    /// Source-native order/cursor, retained as an opaque string.
    pub source_order: Option<StableString>,
    /// Open-world finality/commitment discriminator when applicable.
    pub finality: Option<OpenVariant>,
}

/// One evidence-backed source cursor at an exact logical scope.
///
/// Collections of these values are canonically ordered by `(family, subject, cursor_kind)` and
/// contain at most one value for each such scope. A missing subject is a real source-wide scope;
/// callers must not replace it with an invented sentinel.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ScopedSourceCursor {
    /// Cursor family such as `census` or `hot_lane`.
    pub family: StableString,
    /// Optional mint/account/query/connection subject.
    pub subject: Option<StableString>,
    /// Cursor contract such as `sequence`, `page`, or `epoch`.
    pub cursor_kind: StableString,
    /// Exact opaque source value.
    pub value: StableString,
    /// Local commit that atomically advanced this cursor with its evidence.
    pub advanced_through: CommitSeq,
}

impl ScopedSourceCursor {
    fn scope_cmp(&self, other: &Self) -> Ordering {
        (&self.family, &self.subject, &self.cursor_kind).cmp(&(
            &other.family,
            &other.subject,
            &other.cursor_kind,
        ))
    }
}

/// Canonically ordered, duplicate-free cursor watermarks for one source.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(transparent)]
pub struct ScopedSourceCursors(Vec<ScopedSourceCursor>);

impl ScopedSourceCursors {
    /// Sorts scoped cursors canonically and rejects two values for the same logical scope.
    ///
    /// # Errors
    ///
    /// Returns an error if multiple entries claim the same family/subject/kind scope.
    pub fn new(mut cursors: Vec<ScopedSourceCursor>) -> Result<Self, ScopedCursorError> {
        cursors.sort_by(ScopedSourceCursor::scope_cmp);
        if cursors
            .windows(2)
            .any(|pair| pair[0].scope_cmp(&pair[1]).is_eq())
        {
            return Err(ScopedCursorError::DuplicateScope);
        }
        Ok(Self(cursors))
    }

    /// Returns the canonical cursor sequence.
    #[must_use]
    pub fn as_slice(&self) -> &[ScopedSourceCursor] {
        &self.0
    }

    /// Returns true when no atomic cursor advancement is represented.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl<'de> Deserialize<'de> for ScopedSourceCursors {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let cursors = Vec::<ScopedSourceCursor>::deserialize(deserializer)?;
        if cursors
            .windows(2)
            .any(|pair| !pair[0].scope_cmp(&pair[1]).is_lt())
        {
            return Err(de::Error::custom(
                "scoped source cursors must be strictly sorted by family, subject, and kind",
            ));
        }
        Ok(Self(cursors))
    }
}

/// Invalid collection of scoped cursor watermarks.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ScopedCursorError {
    /// Two cursor values claimed the same logical family/subject/kind scope.
    #[error("duplicate scoped source cursor family/subject/kind")]
    DuplicateScope,
}

/// Per-source delivery watermark used by an as-known or witnessed query.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SourceAsOf {
    /// Highest local commit known to be delivered from this source.
    delivered_through: CommitSeq,
    /// Evidence-backed scoped cursors, strictly sorted by family/subject/kind with no duplicates.
    /// Descriptive cursors copied from an acquisition or observation never belong here.
    cursors: ScopedSourceCursors,
    /// Last receipt wall time represented by this watermark.
    received_through: Option<UtcTimestamp>,
}

impl SourceAsOf {
    /// Builds a source watermark, rejecting a cursor advancement beyond source delivery.
    ///
    /// # Errors
    ///
    /// Returns an error if any scoped cursor claims a later commit than `delivered_through`.
    pub fn new(
        delivered_through: CommitSeq,
        cursors: ScopedSourceCursors,
        received_through: Option<UtcTimestamp>,
    ) -> Result<Self, SourceAsOfError> {
        if cursors
            .as_slice()
            .iter()
            .any(|cursor| cursor.advanced_through > delivered_through)
        {
            return Err(SourceAsOfError::CursorBeyondDelivery);
        }
        Ok(Self {
            delivered_through,
            cursors,
            received_through,
        })
    }

    /// Builds a delivered watermark with no authoritative cursor claims.
    #[must_use]
    pub const fn without_cursors(
        delivered_through: CommitSeq,
        received_through: Option<UtcTimestamp>,
    ) -> Self {
        Self {
            delivered_through,
            cursors: ScopedSourceCursors(Vec::new()),
            received_through,
        }
    }

    /// Highest represented local delivery commit.
    #[must_use]
    pub const fn delivered_through(&self) -> CommitSeq {
        self.delivered_through
    }

    /// Canonically ordered evidence-backed cursors.
    #[must_use]
    pub const fn cursors(&self) -> &ScopedSourceCursors {
        &self.cursors
    }

    /// Latest represented receipt wall time.
    #[must_use]
    pub const fn received_through(&self) -> Option<UtcTimestamp> {
        self.received_through
    }
}

impl<'de> Deserialize<'de> for SourceAsOf {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        struct WireSourceAsOf {
            delivered_through: CommitSeq,
            cursors: ScopedSourceCursors,
            received_through: Option<UtcTimestamp>,
        }

        let wire = WireSourceAsOf::deserialize(deserializer)?;
        Self::new(wire.delivered_through, wire.cursors, wire.received_through)
            .map_err(de::Error::custom)
    }
}

/// Invalid relationship inside one source as-of watermark.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum SourceAsOfError {
    /// A cursor cannot be justified at a later commit than the source's delivered watermark.
    #[error("scoped cursor advancement exceeds source delivery watermark")]
    CursorBeyondDelivery,
}

/// Chain-native watermark, separate from wall and commit clocks.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChainAsOf {
    /// Network/cluster discriminator.
    pub cluster: StableString,
    /// Highest represented slot.
    pub slot: WireU64,
    /// Open-world finality/commitment claim.
    pub finality: OpenVariant,
}

/// Named vector of the independent cutoffs used to build a query result.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AsOfVector {
    /// Durable catalog cutoff. This is knowledge order, not world time.
    pub catalog_commit: CommitSeq,
    /// Per-source delivery watermarks; especially important for witnessed scenes.
    pub sources: BTreeMap<SourceId, SourceAsOf>,
    /// Optional chain watermark, when a query carries chain observations.
    pub chain: Option<ChainAsOf>,
    /// Exact projection contract versions used in the result.
    pub projections: BTreeMap<StableString, StableString>,
    /// Wall time when the result was rendered, not an evidence-valid time.
    pub rendered_at: UtcTimestamp,
}

#[cfg(test)]
mod tests {
    use super::{ScopedSourceCursor, ScopedSourceCursors, SourceAsOf, UtcTimestamp};
    use crate::{CommitSeq, StableString};
    use time::{OffsetDateTime, format_description::well_known::Rfc3339};

    #[test]
    fn timestamps_require_canonical_microsecond_utc_strings() {
        let timestamp = "2026-08-16T16:30:00.123456Z".parse::<UtcTimestamp>();
        assert!(timestamp.is_ok());
        if let Ok(timestamp) = timestamp {
            assert_eq!(timestamp.to_string(), "2026-08-16T16:30:00.123456Z");
            assert_eq!(
                serde_json::to_string(&timestamp).ok().as_deref(),
                Some("\"2026-08-16T16:30:00.123456Z\"")
            );
        }
        assert!("2026-08-16T16:30:00Z".parse::<UtcTimestamp>().is_err());
        assert!(
            "2026-08-16T12:30:00.000000-04:00"
                .parse::<UtcTimestamp>()
                .is_err()
        );
        assert!(
            "2026-08-16T16:30:00.1234567Z"
                .parse::<UtcTimestamp>()
                .is_err()
        );
        let nanosecond_instant = OffsetDateTime::parse("2026-08-16T16:30:00.123456789Z", &Rfc3339);
        assert!(nanosecond_instant.is_ok());
        if let Ok(nanosecond_instant) = nanosecond_instant {
            assert!(UtcTimestamp::new(nanosecond_instant).is_err());
        }
    }

    fn cursor(subject: Option<&str>, kind: &str, advanced: u64) -> ScopedSourceCursor {
        ScopedSourceCursor {
            family: StableString::new("attention").unwrap_or_else(|_| unreachable!()),
            subject: subject
                .map(StableString::new)
                .transpose()
                .unwrap_or_else(|_| unreachable!()),
            cursor_kind: StableString::new(kind).unwrap_or_else(|_| unreachable!()),
            value: StableString::new(format!("value-{advanced}"))
                .unwrap_or_else(|_| unreachable!()),
            advanced_through: CommitSeq::new(advanced),
        }
    }

    #[test]
    fn scoped_cursors_are_canonical_and_duplicate_free() {
        let cursors = ScopedSourceCursors::new(vec![
            cursor(Some("mint-a"), "sequence", 3),
            cursor(None, "epoch", 2),
        ]);
        assert!(cursors.is_ok());
        if let Ok(cursors) = cursors {
            assert_eq!(cursors.as_slice()[0].subject, None);
            let json = serde_json::to_string(&cursors).unwrap_or_else(|_| unreachable!());
            let mut reversed = cursors.as_slice().to_vec();
            reversed.reverse();
            let reversed_json = serde_json::to_string(&reversed).unwrap_or_else(|_| unreachable!());
            assert!(serde_json::from_str::<ScopedSourceCursors>(&json).is_ok());
            assert!(serde_json::from_str::<ScopedSourceCursors>(&reversed_json).is_err());
        }
        assert!(
            ScopedSourceCursors::new(vec![
                cursor(Some("mint-a"), "sequence", 3),
                cursor(Some("mint-a"), "sequence", 4),
            ])
            .is_err()
        );

        let ahead = ScopedSourceCursors::new(vec![cursor(None, "epoch", 4)])
            .unwrap_or_else(|_| unreachable!());
        assert!(SourceAsOf::new(CommitSeq::new(3), ahead, None).is_err());
    }
}
