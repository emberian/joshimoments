use serde::{Deserialize, Serialize};

use crate::frame::{SourceId, UnixMillis};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum Cursor {
    SolanaSlot(u64),
    Signature(String),
    ProviderSequence(String),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GapDisposition {
    /// Recovery was verified over the complete bounded interval.
    Recovered,
    /// Only some of the interval could be replayed.
    Partial,
    /// The source has no cursor/backfill contract (`PumpPortal` live data).
    Unrecoverable,
    /// Recovery has not yet established an answer.
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoverageState {
    NotStarted,
    Open,
    GapOpen,
    Recovering,
    Stopped,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum CoverageEvent {
    WindowOpened {
        source: SourceId,
        connection_epoch: u64,
        at: UnixMillis,
    },
    /// A recovery anchor observed in a frame. This is not a durable cursor advance.
    CursorObserved {
        source: SourceId,
        cursor: Cursor,
        at: UnixMillis,
    },
    GapOpened {
        source: SourceId,
        connection_epoch: u64,
        at: UnixMillis,
        after_cursor: Option<Cursor>,
        reason: String,
    },
    RecoveryStarted {
        source: SourceId,
        at: UnixMillis,
    },
    GapClassified {
        source: SourceId,
        started_at: UnixMillis,
        ended_at: UnixMillis,
        after_cursor: Option<Cursor>,
        disposition: GapDisposition,
        reason: String,
    },
    WindowClosed {
        source: SourceId,
        at: UnixMillis,
        reason: String,
    },
}

#[derive(Clone, Debug)]
struct OpenGap {
    started_at: UnixMillis,
    after_cursor: Option<Cursor>,
}

/// Connection coverage is state, not an inference from whether events happened to arrive.
#[derive(Clone, Debug)]
pub struct CoverageTracker {
    source: SourceId,
    state: CoverageState,
    connection_epoch: u64,
    last_cursor: Option<Cursor>,
    gap: Option<OpenGap>,
}

impl CoverageTracker {
    #[must_use]
    pub fn new(source: SourceId) -> Self {
        Self {
            source,
            state: CoverageState::NotStarted,
            connection_epoch: 0,
            last_cursor: None,
            gap: None,
        }
    }

    #[must_use]
    pub fn state(&self) -> &CoverageState {
        &self.state
    }

    #[must_use]
    pub fn last_cursor(&self) -> Option<&Cursor> {
        self.last_cursor.as_ref()
    }

    pub fn connected(&mut self, at: UnixMillis) -> CoverageEvent {
        self.connection_epoch = self.connection_epoch.saturating_add(1);
        if self.gap.is_none() {
            self.state = CoverageState::Open;
        }
        CoverageEvent::WindowOpened {
            source: self.source.clone(),
            connection_epoch: self.connection_epoch,
            at,
        }
    }

    pub fn observed(&mut self, cursor: Cursor, at: UnixMillis) -> CoverageEvent {
        self.last_cursor = Some(cursor.clone());
        CoverageEvent::CursorObserved {
            source: self.source.clone(),
            cursor,
            at,
        }
    }

    /// Opens at most one gap. Repeated failures preserve the original uncertain interval.
    pub fn disconnected(
        &mut self,
        at: UnixMillis,
        reason: impl Into<String>,
    ) -> Option<CoverageEvent> {
        if self.gap.is_some() {
            return None;
        }
        let after_cursor = self.last_cursor.clone();
        self.gap = Some(OpenGap {
            started_at: at,
            after_cursor: after_cursor.clone(),
        });
        self.state = CoverageState::GapOpen;
        Some(CoverageEvent::GapOpened {
            source: self.source.clone(),
            connection_epoch: self.connection_epoch,
            at,
            after_cursor,
            reason: reason.into(),
        })
    }

    pub fn begin_recovery(&mut self, at: UnixMillis) -> Option<CoverageEvent> {
        self.gap.as_ref()?;
        self.state = CoverageState::Recovering;
        Some(CoverageEvent::RecoveryStarted {
            source: self.source.clone(),
            at,
        })
    }

    pub fn classify_gap(
        &mut self,
        ended_at: UnixMillis,
        disposition: GapDisposition,
        reason: impl Into<String>,
    ) -> Option<CoverageEvent> {
        let gap = self.gap.take()?;
        self.state = CoverageState::Open;
        Some(CoverageEvent::GapClassified {
            source: self.source.clone(),
            started_at: gap.started_at,
            ended_at,
            after_cursor: gap.after_cursor,
            disposition,
            reason: reason.into(),
        })
    }

    pub fn stop(&mut self, at: UnixMillis, reason: impl Into<String>) -> CoverageEvent {
        self.state = CoverageState::Stopped;
        CoverageEvent::WindowClosed {
            source: self.source.clone(),
            at,
            reason: reason.into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reconnect_does_not_claim_the_gap_was_recovered() {
        let mut tracker = CoverageTracker::new(SourceId::PumpPortalWebSocket);
        tracker.connected(UnixMillis(1));
        tracker.disconnected(UnixMillis(2), "socket reset").unwrap();
        tracker.connected(UnixMillis(3));
        assert_eq!(tracker.state(), &CoverageState::GapOpen);
        let event = tracker
            .classify_gap(
                UnixMillis(3),
                GapDisposition::Unrecoverable,
                "provider has no replay cursor",
            )
            .unwrap();
        assert!(matches!(
            event,
            CoverageEvent::GapClassified {
                disposition: GapDisposition::Unrecoverable,
                ..
            }
        ));
    }

    #[test]
    fn duplicate_disconnect_keeps_the_first_gap_boundary() {
        let mut tracker = CoverageTracker::new(SourceId::HeliusWebSocket);
        tracker.connected(UnixMillis(1));
        tracker.observed(Cursor::SolanaSlot(42), UnixMillis(2));
        assert!(tracker.disconnected(UnixMillis(3), "one").is_some());
        assert!(tracker.disconnected(UnixMillis(4), "two").is_none());
    }
}
