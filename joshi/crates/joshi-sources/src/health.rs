use serde::{Deserialize, Serialize};

use crate::frame::{SourceId, UnixMillis};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HealthState {
    Starting,
    Connecting,
    Healthy,
    Degraded,
    BackingOff,
    Stopped,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum HealthEvent {
    ConnectAttempt,
    Connected,
    FrameAccepted,
    MalformedFrame { reason: String },
    RateLimited { retry_after_ms: Option<u64> },
    AuthenticationRejected,
    SubscriptionRejected { reason: String },
    IngressSaturated,
    Disconnected { reason: String },
    BackoffStarted { delay_ms: u64 },
    Stopped { reason: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct HealthSnapshot {
    pub source: SourceId,
    pub state: HealthState,
    pub connection_epoch: u64,
    pub accepted_frames: u64,
    pub malformed_frames: u64,
    pub disconnects: u64,
    pub rate_limits: u64,
    pub ingress_saturations: u64,
    pub last_transition_at: UnixMillis,
    pub last_frame_at: Option<UnixMillis>,
    pub detail: Option<String>,
}

#[derive(Clone, Debug)]
pub struct SourceHealth {
    snapshot: HealthSnapshot,
}

impl SourceHealth {
    #[must_use]
    pub fn new(source: SourceId, at: UnixMillis) -> Self {
        Self {
            snapshot: HealthSnapshot {
                source,
                state: HealthState::Starting,
                connection_epoch: 0,
                accepted_frames: 0,
                malformed_frames: 0,
                disconnects: 0,
                rate_limits: 0,
                ingress_saturations: 0,
                last_transition_at: at,
                last_frame_at: None,
                detail: None,
            },
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> &HealthSnapshot {
        &self.snapshot
    }

    pub fn apply(&mut self, at: UnixMillis, event: &HealthEvent) {
        self.snapshot.last_transition_at = at;
        match event {
            HealthEvent::ConnectAttempt => {
                self.snapshot.state = HealthState::Connecting;
                self.snapshot.detail = None;
            }
            HealthEvent::Connected => {
                self.snapshot.state = HealthState::Healthy;
                self.snapshot.connection_epoch = self.snapshot.connection_epoch.saturating_add(1);
                self.snapshot.detail = None;
            }
            HealthEvent::FrameAccepted => {
                self.snapshot.accepted_frames = self.snapshot.accepted_frames.saturating_add(1);
                self.snapshot.last_frame_at = Some(at);
            }
            HealthEvent::MalformedFrame { reason } => {
                self.snapshot.state = HealthState::Degraded;
                self.snapshot.malformed_frames = self.snapshot.malformed_frames.saturating_add(1);
                self.snapshot.detail = Some(reason.clone());
            }
            HealthEvent::RateLimited { .. } => {
                self.snapshot.state = HealthState::Degraded;
                self.snapshot.rate_limits = self.snapshot.rate_limits.saturating_add(1);
                self.snapshot.detail = Some("provider rate limit".to_owned());
            }
            HealthEvent::AuthenticationRejected => {
                self.snapshot.state = HealthState::Degraded;
                self.snapshot.detail = Some("provider rejected authentication".to_owned());
            }
            HealthEvent::SubscriptionRejected { reason } => {
                self.snapshot.state = HealthState::Degraded;
                self.snapshot.detail = Some(reason.clone());
            }
            HealthEvent::IngressSaturated => {
                self.snapshot.state = HealthState::Degraded;
                self.snapshot.ingress_saturations =
                    self.snapshot.ingress_saturations.saturating_add(1);
                self.snapshot.detail = Some("bounded ingress saturated".to_owned());
            }
            HealthEvent::Disconnected { reason } => {
                self.snapshot.state = HealthState::Degraded;
                self.snapshot.disconnects = self.snapshot.disconnects.saturating_add(1);
                self.snapshot.detail = Some(reason.clone());
            }
            HealthEvent::BackoffStarted { .. } => {
                self.snapshot.state = HealthState::BackingOff;
            }
            HealthEvent::Stopped { reason } => {
                self.snapshot.state = HealthState::Stopped;
                self.snapshot.detail = Some(reason.clone());
            }
        }
    }
}
