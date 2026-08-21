//! The bounded accounting of one hot lease: what arrived, what it cost, and exactly which
//! intervals of the leased window were not observed.
//!
//! This is a pure state machine over the typed outputs a source runner emits. It holds no socket,
//! no store handle, and no clock of its own: every instant is supplied by the caller that read it.
//! Its one job is to make silence impossible. From the instant the lease opens until the provider
//! acknowledges the subscription, and from any disconnect until the lease ends, the ledger keeps
//! an interval open; when the lease closes, every still-open interval becomes an exact typed gap
//! with both of its boundaries.

use joshi_acquisition_policy::HotLeaseTermsV1;
use joshi_sources::{
    CoverageEvent, FrameDirection, HealthEvent, RawSourceFrame, SourceOutput, StreamClass,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{Result, SupervisorError};

/// Ingress headroom held back from the lease's own byte ceiling so that the frame in flight when
/// the ceiling is reached still fits inside the reserved worst case.
pub const INGRESS_STOP_HEADROOM_BYTES: u64 = 1024 * 1024;

/// Gap severity accepted by the durable catalog for a coverage gap.
pub const SEVERITY_DEGRADED: &str = "degraded";
/// Gap severity for an interval the scope stopped covering and did not resume.
pub const SEVERITY_SCOPE_STOPPED: &str = "scope_stopped";

/// Why one lease stopped reading. Every variant is a ceiling or a provider fact, never a choice
/// made mid-run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase"
)]
pub enum LeaseStop {
    /// The leased wall window elapsed. This is the only stop that leaves no terminal gap.
    WindowElapsed,
    /// Retained ingress reached the lease's byte ceiling.
    IngressByteCeiling { observed_bytes: u64, ceiling: u64 },
    /// Retained frames reached the lease's frame ceiling.
    FrameCeiling { observed_frames: u64, ceiling: u64 },
    /// The provider connection ended before the window did.
    ProviderDisconnected { reason: String },
    /// The bounded ingress channel could not accept a frame the source had already read.
    IngressSaturated,
    /// The source runner returned before the window elapsed for a reason of its own.
    RunnerExited { reason: String },
}

impl LeaseStop {
    /// Stable code recorded on the terminal gap this stop opens.
    #[must_use]
    pub fn code(&self) -> &'static str {
        match self {
            Self::WindowElapsed => "window_elapsed",
            Self::IngressByteCeiling { .. } => "ingress_byte_ceiling_exhausted",
            Self::FrameCeiling { .. } => "frame_ceiling_exhausted",
            Self::ProviderDisconnected { .. } => "provider_disconnected",
            Self::IngressSaturated => "ingress_saturated",
            Self::RunnerExited { .. } => "runner_exited",
        }
    }

    /// Whether the remainder of the leased window went unobserved because of this stop.
    #[must_use]
    pub const fn leaves_terminal_gap(&self) -> bool {
        !matches!(self, Self::WindowElapsed)
    }
}

/// What the caller should do after handing one source output to the ledger.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseSignal {
    /// The lease may keep reading.
    Continue,
    /// A ceiling is exhausted; cancel the source runner now.
    Stop,
}

/// One exact interval of the leased window that was not observed.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LeaseGapV1 {
    pub gap_id: String,
    /// Inclusive lower wall boundary in Unix milliseconds.
    pub lower_unix_ms: i64,
    /// Exclusive upper wall boundary in Unix milliseconds. Always strictly greater than the lower.
    pub upper_unix_ms: i64,
    pub duration_ms: i64,
    pub reason: String,
    pub severity: String,
    /// Last chain slot observed before the interval opened, when the provider named one.
    pub after_slot: Option<u64>,
}

/// One retained provider frame with the local clocks that bracket its handoff.
#[derive(Clone, Debug)]
pub struct RetainedLeaseFrame {
    pub frame: RawSourceFrame,
    pub accepted_mono_ns: u64,
    pub slot: Option<u64>,
    /// Exact source variant discriminator for this frame's role on the wire.
    pub variant: &'static str,
}

/// How this build reads one Helius WebSocket frame. Classification is additive metadata; the
/// exact bytes are retained either way.
#[derive(Clone, Debug, Eq, PartialEq)]
enum WsFrameKind {
    SubscriptionAcknowledged { subscription_id: u64 },
    Notification { slot: Option<u64> },
    RpcError { code: Option<i64> },
    Unrecognized,
}

/// Bounded accounting for exactly one hot lease.
#[derive(Debug)]
pub struct LeaseLedger {
    terms: HotLeaseTermsV1,
    namespace: String,
    stop_threshold_bytes: u64,
    opened_unix_ms: i64,
    expires_unix_ms: i64,
    frames: Vec<RetainedLeaseFrame>,
    inbound_frames: u64,
    notifications: u64,
    ingress_bytes: u64,
    subscription_id: Option<u64>,
    subscribed_at_unix_ms: Option<i64>,
    last_slot: Option<u64>,
    unobserved_since: Option<(i64, String)>,
    gaps: Vec<LeaseGapV1>,
    health: Vec<String>,
    provider_errors: Vec<String>,
    stop: Option<LeaseStop>,
    closed_unix_ms: Option<i64>,
}

impl LeaseLedger {
    /// Open the ledger at the exact instant the lease opens.
    ///
    /// The lease begins unobserved: nothing is subscribed until the provider says so, and that
    /// interval is a gap unless an acknowledgement closes it.
    ///
    /// # Errors
    ///
    /// Refuses terms whose window is empty, whose byte ceiling leaves no room for one in-flight
    /// frame, or whose frame ceiling is zero.
    pub fn open(terms: HotLeaseTermsV1, namespace: String, opened_unix_ms: i64) -> Result<Self> {
        let window_ms = i64::try_from(terms.window_ms()).map_err(|_| {
            SupervisorError::InvalidValue("hot lease window does not fit a wall clock".into())
        })?;
        if window_ms <= 0 {
            return Err(SupervisorError::InvalidValue(
                "hot lease window must be at least one millisecond".into(),
            ));
        }
        if terms.max_ingress_bytes.get() <= INGRESS_STOP_HEADROOM_BYTES {
            return Err(SupervisorError::InvalidValue(
                "hot lease byte ceiling must exceed the reserved single-frame headroom".into(),
            ));
        }
        if terms.max_frames.get() == 0 {
            return Err(SupervisorError::InvalidValue(
                "hot lease frame ceiling must be positive".into(),
            ));
        }
        let expires_unix_ms = opened_unix_ms.checked_add(window_ms).ok_or_else(|| {
            SupervisorError::InvalidValue("hot lease expiry overflows the wall clock".into())
        })?;
        let stop_threshold_bytes = terms
            .max_ingress_bytes
            .get()
            .saturating_sub(INGRESS_STOP_HEADROOM_BYTES);
        Ok(Self {
            terms,
            namespace,
            stop_threshold_bytes,
            opened_unix_ms,
            expires_unix_ms,
            frames: Vec::new(),
            inbound_frames: 0,
            notifications: 0,
            ingress_bytes: 0,
            subscription_id: None,
            subscribed_at_unix_ms: None,
            last_slot: None,
            unobserved_since: Some((
                opened_unix_ms,
                "subscription_not_yet_acknowledged".to_owned(),
            )),
            gaps: Vec::new(),
            health: Vec::new(),
            provider_errors: Vec::new(),
            stop: None,
            closed_unix_ms: None,
        })
    }

    /// Accept one typed source output.
    ///
    /// # Errors
    ///
    /// Returns an error only when a retained frame cannot be measured; provider misbehavior is
    /// recorded, not raised.
    pub fn accept(&mut self, output: SourceOutput, accepted_mono_ns: u64) -> Result<LeaseSignal> {
        match output {
            SourceOutput::Frame(frame) => self.accept_frame(frame, accepted_mono_ns),
            SourceOutput::Coverage(event) => {
                self.accept_coverage(&event);
                Ok(LeaseSignal::Continue)
            }
            SourceOutput::Health { at, event, .. } => {
                self.accept_health(at.0, &event);
                Ok(if matches!(event, HealthEvent::IngressSaturated) {
                    self.stop.get_or_insert(LeaseStop::IngressSaturated);
                    LeaseSignal::Stop
                } else {
                    LeaseSignal::Continue
                })
            }
        }
    }

    fn accept_frame(
        &mut self,
        frame: RawSourceFrame,
        accepted_mono_ns: u64,
    ) -> Result<LeaseSignal> {
        let bytes = u64::try_from(frame.body.len()).map_err(|_| {
            SupervisorError::InvalidValue("retained frame length is not representable".into())
        })?;
        let inbound = frame.direction == FrameDirection::Inbound;
        let (variant, slot) = if inbound {
            match classify(&frame.body) {
                WsFrameKind::SubscriptionAcknowledged { subscription_id } => {
                    self.acknowledge(subscription_id, frame.received_at.0);
                    ("solana_ws_subscription_acknowledgement", None)
                }
                WsFrameKind::Notification { slot } => {
                    self.notifications = self.notifications.saturating_add(1);
                    if let Some(value) = slot {
                        self.last_slot = Some(value);
                    }
                    ("solana_ws_logs_notification", slot)
                }
                WsFrameKind::RpcError { code } => {
                    self.provider_errors.push(format!(
                        "provider rejected a subscription request with JSON-RPC code {code:?}"
                    ));
                    ("solana_ws_rpc_error", None)
                }
                WsFrameKind::Unrecognized => ("solana_ws_unrecognized_frame", None),
            }
        } else {
            ("solana_ws_subscription_request", None)
        };
        if inbound {
            self.inbound_frames = self.inbound_frames.saturating_add(1);
            self.ingress_bytes = self.ingress_bytes.saturating_add(bytes);
        }
        self.frames.push(RetainedLeaseFrame {
            frame,
            accepted_mono_ns,
            slot,
            variant,
        });

        if self.ingress_bytes >= self.stop_threshold_bytes {
            self.stop.get_or_insert(LeaseStop::IngressByteCeiling {
                observed_bytes: self.ingress_bytes,
                ceiling: self.terms.max_ingress_bytes.get(),
            });
            return Ok(LeaseSignal::Stop);
        }
        if self.inbound_frames >= self.terms.max_frames.get() {
            self.stop.get_or_insert(LeaseStop::FrameCeiling {
                observed_frames: self.inbound_frames,
                ceiling: self.terms.max_frames.get(),
            });
            return Ok(LeaseSignal::Stop);
        }
        Ok(LeaseSignal::Continue)
    }

    fn acknowledge(&mut self, subscription_id: u64, at_unix_ms: i64) {
        if self.subscription_id.is_some() {
            // A second acknowledgement on a one-connection lease is a provider fact worth
            // retaining, but it does not reopen coverage that is already open.
            self.provider_errors.push(format!(
                "provider acknowledged a second subscription id {subscription_id}"
            ));
            return;
        }
        self.subscription_id = Some(subscription_id);
        self.subscribed_at_unix_ms = Some(at_unix_ms);
        self.close_unobserved(at_unix_ms, SEVERITY_DEGRADED);
    }

    fn accept_coverage(&mut self, event: &CoverageEvent) {
        match event {
            CoverageEvent::CursorObserved {
                cursor: joshi_sources::Cursor::SolanaSlot(slot),
                ..
            } => self.last_slot = Some(*slot),
            CoverageEvent::GapOpened { at, reason, .. } => {
                self.open_unobserved(at.0, format!("websocket_{reason}"));
            }
            CoverageEvent::WindowClosed { at, reason, .. } => {
                if reason == "cancelled" {
                    // This lease cancelled the runner because a ceiling was reached or the
                    // window elapsed. Its own close accounts for the remainder; recording our
                    // own stop as a separate unobserved interval would double-count it.
                    return;
                }
                if self.stop.is_none() {
                    self.stop = Some(LeaseStop::RunnerExited {
                        reason: reason.clone(),
                    });
                }
                self.open_unobserved(at.0, format!("source_window_closed_{reason}"));
            }
            CoverageEvent::WindowOpened { .. }
            | CoverageEvent::CursorObserved { .. }
            | CoverageEvent::RecoveryStarted { .. }
            | CoverageEvent::GapClassified { .. } => {}
        }
    }

    fn accept_health(&mut self, at_unix_ms: i64, event: &HealthEvent) {
        let code = match event {
            HealthEvent::ConnectAttempt => "connect_attempt".to_owned(),
            HealthEvent::Connected => "connected".to_owned(),
            HealthEvent::FrameAccepted => return,
            HealthEvent::Disconnected { reason } => {
                self.open_unobserved(at_unix_ms, format!("websocket_disconnected_{reason}"));
                if self.stop.is_none() {
                    self.stop = Some(LeaseStop::ProviderDisconnected {
                        reason: reason.clone(),
                    });
                }
                format!("disconnected:{reason}")
            }
            HealthEvent::SubscriptionRejected { reason } => {
                self.provider_errors
                    .push(format!("provider rejected the subscription: {reason}"));
                "subscription_rejected".to_owned()
            }
            other => format!("{other:?}")
                .split_whitespace()
                .next()
                .unwrap_or("health")
                .to_ascii_lowercase(),
        };
        self.health.push(format!("{at_unix_ms}:{code}"));
    }

    fn open_unobserved(&mut self, at_unix_ms: i64, reason: String) {
        if self.unobserved_since.is_none() {
            self.unobserved_since = Some((at_unix_ms.max(self.opened_unix_ms), reason));
        }
    }

    fn close_unobserved(&mut self, at_unix_ms: i64, severity: &str) {
        let Some((since, reason)) = self.unobserved_since.take() else {
            return;
        };
        self.push_gap(since, at_unix_ms, reason, severity);
    }

    fn push_gap(&mut self, lower: i64, upper: i64, reason: String, severity: &str) {
        if upper <= lower {
            // A zero-length interval is not a gap; recording one would overstate uncertainty.
            return;
        }
        let ordinal = self.gaps.len();
        self.gaps.push(LeaseGapV1 {
            gap_id: format!("gap-{}-{ordinal:04}", self.namespace),
            lower_unix_ms: lower,
            upper_unix_ms: upper,
            duration_ms: upper.saturating_sub(lower),
            reason,
            severity: severity.to_owned(),
            after_slot: self.last_slot,
        });
    }

    /// Close the lease at an exact instant and settle every still-open interval.
    ///
    /// Any interval still open becomes a gap ending here, and any stop other than window expiry
    /// opens one final gap covering the remainder of the leased window.
    pub fn close(&mut self, at_unix_ms: i64, stop: LeaseStop) {
        if self.closed_unix_ms.is_some() {
            return;
        }
        if stop.leaves_terminal_gap() {
            // Everything from here to the leased expiry is one unobserved interval. If an
            // interval was already open when the lease stopped, it is the beginning of that same
            // remainder and carries the cause; two adjacent rows would only split one fact.
            let (lower, reason) = self
                .unobserved_since
                .take()
                .unwrap_or_else(|| (at_unix_ms, format!("lease_stopped_early_{}", stop.code())));
            let upper = self.expires_unix_ms.max(at_unix_ms);
            self.push_gap(lower, upper, reason, SEVERITY_SCOPE_STOPPED);
        } else {
            self.close_unobserved(at_unix_ms, SEVERITY_DEGRADED);
        }
        self.stop = Some(stop);
        self.closed_unix_ms = Some(at_unix_ms);
    }

    #[must_use]
    pub fn terms(&self) -> &HotLeaseTermsV1 {
        &self.terms
    }

    #[must_use]
    pub fn namespace(&self) -> &str {
        &self.namespace
    }

    #[must_use]
    pub fn frames(&self) -> &[RetainedLeaseFrame] {
        &self.frames
    }

    #[must_use]
    pub fn gaps(&self) -> &[LeaseGapV1] {
        &self.gaps
    }

    #[must_use]
    pub const fn ingress_bytes(&self) -> u64 {
        self.ingress_bytes
    }

    #[must_use]
    pub const fn inbound_frames(&self) -> u64 {
        self.inbound_frames
    }

    #[must_use]
    pub const fn notifications(&self) -> u64 {
        self.notifications
    }

    #[must_use]
    pub const fn subscription_id(&self) -> Option<u64> {
        self.subscription_id
    }

    #[must_use]
    pub const fn subscribed_at_unix_ms(&self) -> Option<i64> {
        self.subscribed_at_unix_ms
    }

    #[must_use]
    pub const fn opened_unix_ms(&self) -> i64 {
        self.opened_unix_ms
    }

    #[must_use]
    pub const fn expires_unix_ms(&self) -> i64 {
        self.expires_unix_ms
    }

    #[must_use]
    pub const fn closed_unix_ms(&self) -> Option<i64> {
        self.closed_unix_ms
    }

    #[must_use]
    pub const fn stop(&self) -> Option<&LeaseStop> {
        self.stop.as_ref()
    }

    #[must_use]
    pub fn provider_errors(&self) -> &[String] {
        &self.provider_errors
    }

    #[must_use]
    pub fn health(&self) -> &[String] {
        &self.health
    }

    /// Exact observed milliseconds of the leased window: the window minus every gap.
    ///
    /// A gap is recorded with its true boundaries, and a final drain can push one past the leased
    /// expiry, so only the part of each gap that intersects the leased window is subtracted here.
    #[must_use]
    pub fn observed_ms(&self) -> i64 {
        let unobserved: i64 = self
            .gaps
            .iter()
            .map(|gap| {
                let lower = gap.lower_unix_ms.max(self.opened_unix_ms);
                let upper = gap.upper_unix_ms.min(self.expires_unix_ms);
                upper.saturating_sub(lower).max(0)
            })
            .sum();
        self.expires_unix_ms
            .saturating_sub(self.opened_unix_ms)
            .saturating_sub(unobserved)
            .max(0)
    }

    /// Stream class every retained frame of this lease belongs to, for the receipt.
    #[must_use]
    pub fn stream_classes(&self) -> Vec<StreamClass> {
        let mut classes: Vec<StreamClass> = self
            .frames
            .iter()
            .map(|retained| retained.frame.stream_class)
            .collect();
        classes.sort_by_key(|class| format!("{class:?}"));
        classes.dedup_by_key(|class| format!("{class:?}"));
        classes
    }
}

/// Read one Helius WebSocket frame well enough to know whether coverage started.
fn classify(body: &[u8]) -> WsFrameKind {
    let Ok(value) = serde_json::from_slice::<Value>(body) else {
        return WsFrameKind::Unrecognized;
    };
    if let Some(error) = value.get("error") {
        return WsFrameKind::RpcError {
            code: error.get("code").and_then(Value::as_i64),
        };
    }
    if value.get("id").and_then(Value::as_u64).is_some()
        && let Some(subscription_id) = value.get("result").and_then(Value::as_u64)
    {
        return WsFrameKind::SubscriptionAcknowledged { subscription_id };
    }
    if value.get("method").is_some() {
        return WsFrameKind::Notification {
            slot: value
                .pointer("/params/result/context/slot")
                .and_then(Value::as_u64),
        };
    }
    WsFrameKind::Unrecognized
}
