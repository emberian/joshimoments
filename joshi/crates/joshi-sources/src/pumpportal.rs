use std::{collections::BTreeMap, time::Duration};

use bytes::Bytes;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::{
    GapDisposition, SourceId, UnixMillis,
    frame::StreamClass,
    health::HealthEvent,
    scope::{LeaseKind, ScopeBook, ScopeDelta},
    websocket::{FrameInterpretation, ProtocolError, WebSocketCommand, WebSocketProtocol},
};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PumpPortalMethod {
    SubscribeNewToken,
    SubscribeMigration,
    SubscribeTokenTrade,
    UnsubscribeTokenTrade,
    SubscribeAccountTrade,
    UnsubscribeAccountTrade,
}

impl PumpPortalMethod {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SubscribeNewToken => "subscribeNewToken",
            Self::SubscribeMigration => "subscribeMigration",
            Self::SubscribeTokenTrade => "subscribeTokenTrade",
            Self::UnsubscribeTokenTrade => "unsubscribeTokenTrade",
            Self::SubscribeAccountTrade => "subscribeAccountTrade",
            Self::UnsubscribeAccountTrade => "unsubscribeAccountTrade",
        }
    }

    #[must_use]
    pub const fn stream_class(self) -> StreamClass {
        match self {
            Self::SubscribeNewToken | Self::SubscribeMigration => StreamClass::BroadCensus,
            Self::SubscribeTokenTrade
            | Self::UnsubscribeTokenTrade
            | Self::SubscribeAccountTrade
            | Self::UnsubscribeAccountTrade => StreamClass::LeasedHot,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PumpPortalCommand {
    pub method: PumpPortalMethod,
    pub keys: Vec<String>,
    pub body: Bytes,
}

impl PumpPortalCommand {
    fn new(method: PumpPortalMethod, keys: Vec<String>) -> Result<Self, serde_json::Error> {
        let body = if keys.is_empty() {
            serde_json::to_vec(&json!({"method": method.as_str()}))?
        } else {
            serde_json::to_vec(&json!({"method": method.as_str(), "keys": keys}))?
        };
        Ok(Self {
            method,
            keys,
            body: Bytes::from(body),
        })
    }
}

#[derive(Clone, Debug)]
pub struct PumpPortalCommandBatch {
    pub commands: Vec<PumpPortalCommand>,
    delta: ScopeDelta,
}

impl PumpPortalCommandBatch {
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.commands.is_empty()
    }
}

#[derive(Clone, Debug)]
pub struct PumpPortalSession {
    census_new_tokens: bool,
    census_migrations: bool,
    metered_enabled: bool,
    max_keys_per_message: usize,
    minimum_update_interval: Duration,
    scopes: ScopeBook,
}

impl PumpPortalSession {
    /// Construct one multiplexed `PumpPortal` data session.
    ///
    /// # Errors
    ///
    /// Returns an error when any message-rate or scope bound is zero or exceeds the documented
    /// provider ceiling.
    pub fn new(
        census_new_tokens: bool,
        census_migrations: bool,
        metered_enabled: bool,
        max_hot_keys: usize,
        max_keys_per_message: usize,
        max_subscription_messages_per_second: u16,
    ) -> Result<Self, &'static str> {
        if max_keys_per_message == 0 || max_keys_per_message > 5_000 {
            return Err("PumpPortal key batches must contain between 1 and 5,000 keys");
        }
        if max_subscription_messages_per_second == 0 || max_subscription_messages_per_second > 200 {
            return Err("PumpPortal subscription update rate must be between 1 and 200/s");
        }
        Ok(Self {
            census_new_tokens,
            census_migrations,
            metered_enabled,
            max_keys_per_message,
            minimum_update_interval: Duration::from_secs_f64(
                1.0 / f64::from(max_subscription_messages_per_second),
            ),
            scopes: ScopeBook::new(max_hot_keys).map_err(|_| "invalid hot-scope capacity")?,
        })
    }

    #[must_use]
    pub const fn minimum_update_interval(&self) -> Duration {
        self.minimum_update_interval
    }

    pub fn scopes_mut(&mut self) -> &mut ScopeBook {
        &mut self.scopes
    }

    /// Build commands for a fresh socket. `PumpPortal` asks clients to multiplex all scopes on one
    /// connection.
    ///
    /// # Errors
    ///
    /// Returns an error if a typed subscription command cannot be serialized.
    pub fn startup_batch(&mut self) -> Result<PumpPortalCommandBatch, serde_json::Error> {
        self.scopes.reset_applied();
        let delta = self.scopes.delta();
        let mut commands = Vec::new();
        if self.census_new_tokens {
            commands.push(PumpPortalCommand::new(
                PumpPortalMethod::SubscribeNewToken,
                Vec::new(),
            )?);
        }
        if self.census_migrations {
            commands.push(PumpPortalCommand::new(
                PumpPortalMethod::SubscribeMigration,
                Vec::new(),
            )?);
        }
        if self.metered_enabled {
            commands.extend(self.commands_for_delta(&delta)?);
        }
        Ok(PumpPortalCommandBatch { commands, delta })
    }

    /// Build the subscribe/unsubscribe commands needed to match desired leases.
    ///
    /// # Errors
    ///
    /// Returns an error if a typed subscription command cannot be serialized.
    pub fn reconcile_batch(&self) -> Result<PumpPortalCommandBatch, serde_json::Error> {
        let delta = self.scopes.delta();
        let commands = if self.metered_enabled {
            self.commands_for_delta(&delta)?
        } else {
            Vec::new()
        };
        Ok(PumpPortalCommandBatch { commands, delta })
    }

    /// Mark only after every command in the batch was written. A partial write requires reconnect.
    pub fn commit_batch(&mut self, batch: &PumpPortalCommandBatch) {
        if self.metered_enabled {
            self.scopes.mark_applied(&batch.delta);
        }
    }

    fn commands_for_delta(
        &self,
        delta: &ScopeDelta,
    ) -> Result<Vec<PumpPortalCommand>, serde_json::Error> {
        let mut grouped: BTreeMap<(LeaseKind, bool), Vec<String>> = BTreeMap::new();
        for key in &delta.subscribe {
            grouped
                .entry((key.kind, true))
                .or_default()
                .push(key.address.clone());
        }
        for key in &delta.unsubscribe {
            grouped
                .entry((key.kind, false))
                .or_default()
                .push(key.address.clone());
        }
        let mut commands = Vec::new();
        for ((kind, subscribe), keys) in grouped {
            let method = match (kind, subscribe) {
                (LeaseKind::MintTrades, true) => PumpPortalMethod::SubscribeTokenTrade,
                (LeaseKind::MintTrades, false) => PumpPortalMethod::UnsubscribeTokenTrade,
                (LeaseKind::AccountTrades, true) => PumpPortalMethod::SubscribeAccountTrade,
                (LeaseKind::AccountTrades, false) => PumpPortalMethod::UnsubscribeAccountTrade,
            };
            for chunk in keys.chunks(self.max_keys_per_message) {
                commands.push(PumpPortalCommand::new(method, chunk.to_vec())?);
            }
        }
        Ok(commands)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PumpPortalFrameKind {
    NewToken,
    Migration,
    Trade,
    Acknowledgement,
    AuthenticationOrFundingRejected,
    ProviderControl,
    UnknownEvent,
    Malformed,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct PumpPortalFrameMetadata {
    pub kind: PumpPortalFrameKind,
    pub stream_class: StreamClass,
    pub signature: Option<String>,
    pub mint: Option<String>,
    /// The official feed currently supplies no replay cursor.
    pub replay_cursor: Option<String>,
    /// False for observed 2026-08 frames; absence must never be replaced with receipt time.
    pub provider_event_clock_present: bool,
}

#[must_use]
pub fn classify_frame(bytes: &[u8]) -> PumpPortalFrameMetadata {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        return PumpPortalFrameMetadata {
            kind: PumpPortalFrameKind::Malformed,
            stream_class: StreamClass::Control,
            signature: None,
            mint: None,
            replay_cursor: None,
            provider_event_clock_present: false,
        };
    };
    let message = value.get("message").and_then(Value::as_str);
    if let Some(message) = message {
        let lower = message.to_ascii_lowercase();
        let kind = if lower.contains("api key")
            || lower.contains("funded")
            || lower.contains("0.02 sol")
        {
            PumpPortalFrameKind::AuthenticationOrFundingRejected
        } else if lower.contains("successfully subscribed") {
            PumpPortalFrameKind::Acknowledgement
        } else {
            PumpPortalFrameKind::ProviderControl
        };
        return PumpPortalFrameMetadata {
            kind,
            stream_class: StreamClass::Control,
            signature: None,
            mint: None,
            replay_cursor: None,
            provider_event_clock_present: clock_present(&value),
        };
    }
    let tx_type = value.get("txType").and_then(Value::as_str);
    let (kind, stream_class) = match tx_type {
        Some("create") => (PumpPortalFrameKind::NewToken, StreamClass::BroadCensus),
        Some("migrate") => (PumpPortalFrameKind::Migration, StreamClass::BroadCensus),
        Some("buy" | "sell") => (PumpPortalFrameKind::Trade, StreamClass::LeasedHot),
        _ => (PumpPortalFrameKind::UnknownEvent, StreamClass::Control),
    };
    PumpPortalFrameMetadata {
        kind,
        stream_class,
        signature: value
            .get("signature")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
        mint: value
            .get("mint")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
        replay_cursor: None,
        provider_event_clock_present: clock_present(&value),
    }
}

fn clock_present(value: &Value) -> bool {
    ["timestamp", "blockTime", "block_time", "eventTime", "time"]
        .iter()
        .any(|key| value.get(*key).is_some_and(|value| !value.is_null()))
}

#[derive(Clone, Debug)]
pub enum PumpPortalControl {
    Upsert(crate::HotLease),
    Release { lease_id: String },
    Expire { now: UnixMillis },
}

#[derive(Clone, Debug)]
pub struct PumpPortalWsAdapter {
    session: PumpPortalSession,
    pending: Option<PumpPortalCommandBatch>,
}

impl PumpPortalWsAdapter {
    /// Construct the read-only protocol adapter from validated source settings.
    ///
    /// # Errors
    ///
    /// Returns a sanitized protocol error if the configured scope bounds are invalid.
    pub fn from_config(config: &crate::PumpPortalConfig) -> Result<Self, ProtocolError> {
        let _ = config;
        Err(ProtocolError {
            message:
                "PumpPortal live runtime is disabled: its API key carries wallet-signing authority"
                    .to_owned(),
        })
    }

    fn set_pending(&mut self, batch: PumpPortalCommandBatch) -> Vec<WebSocketCommand> {
        let commands = batch
            .commands
            .iter()
            .map(|command| WebSocketCommand {
                stream_class: command.method.stream_class(),
                body: command.body.clone(),
            })
            .collect();
        self.pending = Some(batch);
        commands
    }
}

impl WebSocketProtocol for PumpPortalWsAdapter {
    type Control = PumpPortalControl;

    fn source_id(&self) -> SourceId {
        SourceId::PumpPortalWebSocket
    }

    fn connected(&mut self) -> Result<Vec<WebSocketCommand>, ProtocolError> {
        let batch = self.session.startup_batch()?;
        Ok(self.set_pending(batch))
    }

    fn control(&mut self, control: Self::Control) -> Result<Vec<WebSocketCommand>, ProtocolError> {
        match control {
            PumpPortalControl::Upsert(lease) => {
                self.session
                    .scopes_mut()
                    .upsert(lease)
                    .map_err(|error| ProtocolError {
                        message: error.to_string(),
                    })?;
            }
            PumpPortalControl::Release { lease_id } => {
                self.session.scopes_mut().release(&lease_id);
            }
            PumpPortalControl::Expire { now } => {
                self.session.scopes_mut().expire(now);
            }
        }
        let batch = self.session.reconcile_batch()?;
        Ok(self.set_pending(batch))
    }

    fn commands_sent(&mut self) {
        if let Some(batch) = self.pending.take() {
            self.session.commit_batch(&batch);
        }
    }

    fn classify(&mut self, bytes: &[u8]) -> FrameInterpretation {
        let metadata = classify_frame(bytes);
        let health = match metadata.kind {
            PumpPortalFrameKind::Malformed => Some(HealthEvent::MalformedFrame {
                reason: "invalid PumpPortal JSON websocket frame".to_owned(),
            }),
            PumpPortalFrameKind::AuthenticationOrFundingRejected => {
                Some(HealthEvent::AuthenticationRejected)
            }
            _ => None,
        };
        FrameInterpretation {
            stream_class: metadata.stream_class,
            cursor: None,
            health,
        }
    }

    fn disconnected(&mut self) {
        self.pending = None;
        self.session.scopes.reset_applied();
    }

    fn reconnect_gap_disposition(&self) -> Option<(GapDisposition, &'static str)> {
        Some((
            GapDisposition::Unrecoverable,
            "PumpPortal data websocket exposes no replay cursor or historical backfill",
        ))
    }
}

#[cfg(test)]
mod tests {
    use crate::{
        frame::UnixMillis,
        scope::{HotLease, LeaseKey},
    };

    use super::*;

    const MINT: &str = "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump";
    const WALLET: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";

    #[test]
    fn startup_uses_one_socket_command_stream_for_census_and_hot_scopes() {
        let mut session = PumpPortalSession::new(true, true, true, 10, 5_000, 20).unwrap();
        session
            .scopes_mut()
            .upsert(HotLease {
                lease_id: "mint-lease".to_owned(),
                key: LeaseKey::new(LeaseKind::MintTrades, MINT).unwrap(),
                opened_at: UnixMillis(1),
                expires_at: UnixMillis(10),
                reason: "operator hot coin".to_owned(),
            })
            .unwrap();
        session
            .scopes_mut()
            .upsert(HotLease {
                lease_id: "wallet-lease".to_owned(),
                key: LeaseKey::new(LeaseKind::AccountTrades, WALLET).unwrap(),
                opened_at: UnixMillis(1),
                expires_at: UnixMillis(10),
                reason: "wallet ecology".to_owned(),
            })
            .unwrap();
        let batch = session.startup_batch().unwrap();
        let methods: Vec<_> = batch
            .commands
            .iter()
            .map(|command| command.method)
            .collect();
        assert_eq!(
            methods,
            vec![
                PumpPortalMethod::SubscribeNewToken,
                PumpPortalMethod::SubscribeMigration,
                PumpPortalMethod::SubscribeTokenTrade,
                PumpPortalMethod::SubscribeAccountTrade,
            ]
        );
        let token = &batch.commands[2];
        let account = &batch.commands[3];
        assert_eq!(token.keys, vec![MINT]);
        assert_eq!(account.keys, vec![WALLET]);
    }

    #[test]
    fn vendor_numbers_are_not_reserialized() {
        let bytes = br#"{"signature":"s","mint":"m","txType":"create","solAmount":2,"vSolInBondingCurve":30.059259257999976}"#;
        let metadata = classify_frame(bytes);
        assert_eq!(metadata.kind, PumpPortalFrameKind::NewToken);
        assert!(!metadata.provider_event_clock_present);
        assert_eq!(bytes, &bytes[..]);
    }

    #[test]
    fn funding_rejection_is_a_health_control_not_market_silence() {
        let bytes = br#"{"message":"'subscribeTokenTrade' methods are only available when connecting with an API key funded with at least 0.02 SOL."}"#;
        assert_eq!(
            classify_frame(bytes).kind,
            PumpPortalFrameKind::AuthenticationOrFundingRejected
        );
    }
}
