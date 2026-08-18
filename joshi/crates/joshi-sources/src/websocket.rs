use std::{fmt, marker::PhantomData, time::Duration};

use bytes::Bytes;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::{mpsc, oneshot};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tokio_util::sync::CancellationToken;
use url::Url;

use crate::{
    Backoff, BackoffPolicy, BoundedIngress, ContentType, CoverageEvent, CoverageTracker, Cursor,
    GapDisposition, HealthEvent, HealthSnapshot, IngressError, RawSourceFrame, SourceHealth,
    SourceId, StreamClass, UnixMillis,
    config::{ConfigError, HeliusConfig, LoadedCredential, PumpPortalConfig, authenticated_url},
    frame::FrameDirection,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WebSocketCommand {
    pub stream_class: StreamClass,
    pub body: Bytes,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrameInterpretation {
    pub stream_class: StreamClass,
    pub cursor: Option<Cursor>,
    pub health: Option<HealthEvent>,
}

pub trait WebSocketProtocol: Send + 'static {
    type Control: Send + 'static;

    fn source_id(&self) -> SourceId;
    /// Build commands that establish the desired state on a fresh connection.
    ///
    /// # Errors
    ///
    /// Returns a sanitized protocol error when validation or encoding fails.
    fn connected(&mut self) -> Result<Vec<WebSocketCommand>, ProtocolError>;
    /// Apply one typed control-plane update and build its wire commands.
    ///
    /// # Errors
    ///
    /// Returns a sanitized protocol error when the update is invalid or cannot be encoded.
    fn control(&mut self, control: Self::Control) -> Result<Vec<WebSocketCommand>, ProtocolError>;
    fn commands_sent(&mut self);
    fn classify(&mut self, bytes: &[u8]) -> FrameInterpretation;
    fn disconnected(&mut self);

    /// `PumpPortal` has no replay cursor; Solana WS gaps instead remain open for HTTP backfill.
    fn reconnect_gap_disposition(&self) -> Option<(GapDisposition, &'static str)> {
        None
    }
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
#[error("websocket protocol control failed: {message}")]
pub struct ProtocolError {
    pub message: String,
}

impl From<serde_json::Error> for ProtocolError {
    fn from(error: serde_json::Error) -> Self {
        Self {
            message: error.to_string(),
        }
    }
}

#[derive(Clone, Debug)]
pub enum SourceOutput {
    Frame(RawSourceFrame),
    Coverage(CoverageEvent),
    Health {
        at: UnixMillis,
        event: HealthEvent,
        snapshot: HealthSnapshot,
    },
}

#[derive(Clone, Debug)]
pub struct WebSocketRunPolicy {
    pub inactivity_timeout: Duration,
    pub ping_interval: Duration,
    pub subscription_message_interval: Duration,
    pub backoff: BackoffPolicy,
    /// Optional hard ceiling on connection attempts, including the first attempt.
    pub max_connection_attempts: Option<u32>,
}

#[derive(Debug)]
pub struct WebSocketExit {
    pub health: HealthSnapshot,
    pub coverage_state: crate::CoverageState,
    pub reason: &'static str,
}

#[derive(Debug, thiserror::Error)]
pub enum WebSocketBuildError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("invalid backoff configuration: {0}")]
    Backoff(&'static str),
}

pub struct WebSocketEndpoint {
    base: Url,
    credential: Option<LoadedCredential>,
}

impl fmt::Debug for WebSocketEndpoint {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("WebSocketEndpoint")
            .field("scheme", &self.base.scheme())
            .field("host", &self.base.host_str())
            .field(
                "credential",
                &self.credential.as_ref().map(|_| "[REDACTED]"),
            )
            .finish()
    }
}

impl WebSocketEndpoint {
    /// Load a Helius WebSocket endpoint and its credential once at adapter startup.
    ///
    /// # Errors
    ///
    /// Returns a configuration error for an invalid endpoint or credential file.
    pub fn helius(config: &HeliusConfig) -> Result<(Self, WebSocketRunPolicy), ConfigError> {
        let loaded = config.load()?;
        let policy = WebSocketRunPolicy {
            inactivity_timeout: loaded.websocket_inactivity,
            ping_interval: Duration::from_secs(30),
            subscription_message_interval: Duration::from_millis(5),
            backoff: config.backoff,
            max_connection_attempts: None,
        };
        Ok((
            Self {
                base: loaded.websocket_url,
                credential: Some(loaded.api_key),
            },
            policy,
        ))
    }

    /// Load a `PumpPortal` WebSocket endpoint and optional credential once at adapter startup.
    ///
    /// # Errors
    ///
    /// Returns a configuration error for an invalid endpoint, unsafe metered configuration, or
    /// credential file.
    pub fn pumpportal(
        config: &PumpPortalConfig,
    ) -> Result<(Self, WebSocketRunPolicy), ConfigError> {
        let loaded = config.load()?;
        let policy = WebSocketRunPolicy {
            inactivity_timeout: loaded.websocket_inactivity,
            ping_interval: Duration::from_secs(30),
            subscription_message_interval: Duration::from_secs_f64(
                1.0 / f64::from(config.max_subscription_messages_per_second),
            ),
            backoff: config.backoff,
            max_connection_attempts: None,
        };
        Ok((
            Self {
                base: loaded.websocket_url,
                credential: loaded.api_key,
            },
            policy,
        ))
    }

    fn authenticated(&self) -> Url {
        authenticated_url(&self.base, self.credential.as_ref())
    }
}

struct ControlRequest<C> {
    control: C,
    reply: oneshot::Sender<Result<(), ProtocolError>>,
}

pub struct WebSocketControlHandle<C> {
    sender: mpsc::Sender<ControlRequest<C>>,
    _control: PhantomData<fn(C)>,
}

impl<C> Clone for WebSocketControlHandle<C> {
    fn clone(&self) -> Self {
        Self {
            sender: self.sender.clone(),
            _control: PhantomData,
        }
    }
}

impl<C: Send + 'static> WebSocketControlHandle<C> {
    /// Apply a typed control update after its commands are written to the live socket.
    ///
    /// # Errors
    ///
    /// Returns a sanitized protocol error if the runner stops, validation fails, or writing fails.
    pub async fn apply(&self, control: C) -> Result<(), ProtocolError> {
        let (reply, receiver) = oneshot::channel();
        self.sender
            .send(ControlRequest { control, reply })
            .await
            .map_err(|_| ProtocolError {
                message: "websocket runner stopped".to_owned(),
            })?;
        receiver.await.map_err(|_| ProtocolError {
            message: "websocket runner stopped before control acknowledgement".to_owned(),
        })?
    }
}

pub struct WebSocketRunner<P: WebSocketProtocol> {
    endpoint: WebSocketEndpoint,
    policy: WebSocketRunPolicy,
    protocol: P,
    controls: mpsc::Receiver<ControlRequest<P::Control>>,
    output: BoundedIngress<SourceOutput>,
    cancellation: CancellationToken,
}

impl<P: WebSocketProtocol> WebSocketRunner<P> {
    /// Construct a runner and its typed, bounded control handle.
    ///
    /// # Panics
    ///
    /// Panics when `control_capacity` is zero because the control queue must be usable and bounded.
    #[must_use]
    pub fn new(
        endpoint: WebSocketEndpoint,
        policy: WebSocketRunPolicy,
        protocol: P,
        output: BoundedIngress<SourceOutput>,
        cancellation: CancellationToken,
        control_capacity: usize,
    ) -> (Self, WebSocketControlHandle<P::Control>) {
        assert!(
            control_capacity > 0,
            "websocket control queue must be bounded above zero"
        );
        let (sender, controls) = mpsc::channel(control_capacity);
        (
            Self {
                endpoint,
                policy,
                protocol,
                controls,
                output,
                cancellation,
            },
            WebSocketControlHandle {
                sender,
                _control: PhantomData,
            },
        )
    }

    /// Run until cancellation or a failure that cannot safely be emitted downstream.
    #[allow(clippy::too_many_lines)]
    pub async fn run(mut self, started_at: UnixMillis) -> WebSocketExit {
        let source = self.protocol.source_id();
        let mut health = SourceHealth::new(source.clone(), started_at);
        let mut coverage = CoverageTracker::new(source.clone());
        let Ok(mut backoff) = Backoff::new(self.policy.backoff) else {
            return WebSocketExit {
                health: health.snapshot().clone(),
                coverage_state: coverage.state().clone(),
                reason: "invalid_backoff",
            };
        };
        let mut sequence = 0_u64;
        let mut epoch = 0_u64;
        let mut connection_attempts = 0_u32;

        loop {
            if self.cancellation.is_cancelled() {
                let now = now_millis();
                let event = HealthEvent::Stopped {
                    reason: "cancelled".to_owned(),
                };
                if emit_health(&self.output, &mut health, now, event).is_err() {
                    return exit(&health, &coverage, "ingress_saturated");
                }
                let _ = emit(
                    &self.output,
                    SourceOutput::Coverage(coverage.stop(now, "cancelled")),
                );
                return exit(&health, &coverage, "cancelled");
            }

            if self
                .policy
                .max_connection_attempts
                .is_some_and(|maximum| connection_attempts >= maximum)
            {
                return exit(&health, &coverage, "connection_attempt_limit");
            }
            connection_attempts = connection_attempts.saturating_add(1);

            let now = now_millis();
            if emit_health(&self.output, &mut health, now, HealthEvent::ConnectAttempt).is_err() {
                return exit(&health, &coverage, "ingress_saturated");
            }
            // Never render the error: tungstenite may retain the authenticated request URI.
            let endpoint = self.endpoint.authenticated();
            let connected = connect_async(endpoint.as_str()).await;
            let Ok((mut socket, _response)) = connected else {
                let now = now_millis();
                if emit_health(
                    &self.output,
                    &mut health,
                    now,
                    HealthEvent::Disconnected {
                        reason: "connect_failed_authenticated_url_omitted".to_owned(),
                    },
                )
                .is_err()
                {
                    return exit(&health, &coverage, "ingress_saturated");
                }
                if let Some(event) = coverage.disconnected(now, "connect_failed")
                    && emit(&self.output, SourceOutput::Coverage(event)).is_err()
                {
                    return exit(&health, &coverage, "ingress_saturated");
                }
                if !self.wait_backoff(&mut health, &mut backoff).await {
                    return exit(&health, &coverage, "cancelled");
                }
                continue;
            };

            epoch = epoch.saturating_add(1);
            backoff.reset();
            let now = now_millis();
            if emit_health(&self.output, &mut health, now, HealthEvent::Connected).is_err()
                || emit(
                    &self.output,
                    SourceOutput::Coverage(coverage.connected(now)),
                )
                .is_err()
            {
                return exit(&health, &coverage, "ingress_saturated");
            }
            if let Some((disposition, reason)) = self.protocol.reconnect_gap_disposition()
                && let Some(event) = coverage.classify_gap(now, disposition, reason)
                && emit(&self.output, SourceOutput::Coverage(event)).is_err()
            {
                return exit(&health, &coverage, "ingress_saturated");
            }

            let startup = match self.protocol.connected() {
                Ok(commands) => commands,
                Err(error) => {
                    let _ = emit_health(
                        &self.output,
                        &mut health,
                        now_millis(),
                        HealthEvent::SubscriptionRejected {
                            reason: error.message,
                        },
                    );
                    return exit(&health, &coverage, "protocol_startup_rejected");
                }
            };
            if send_commands(
                &mut socket,
                &self.output,
                &source,
                epoch,
                &mut sequence,
                &startup,
                self.policy.subscription_message_interval,
            )
            .await
            .is_err()
            {
                self.protocol.disconnected();
                if let Some(event) = coverage.disconnected(now_millis(), "startup_write_failed") {
                    let _ = emit(&self.output, SourceOutput::Coverage(event));
                }
                if !self.wait_backoff(&mut health, &mut backoff).await {
                    return exit(&health, &coverage, "cancelled");
                }
                continue;
            }
            self.protocol.commands_sent();

            let (mut writer, mut reader) = socket.split();
            let mut ping = tokio::time::interval(self.policy.ping_interval);
            ping.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            let silence = tokio::time::sleep(self.policy.inactivity_timeout);
            tokio::pin!(silence);
            let disconnect_reason = loop {
                tokio::select! {
                    () = self.cancellation.cancelled() => {
                        let _ = writer.send(Message::Close(None)).await;
                        break "cancelled";
                    }
                    _instant = ping.tick() => {
                        if writer.send(Message::Ping(Bytes::new())).await.is_err() {
                            break "ping_failed";
                        }
                    }
                    () = &mut silence => {
                        break "inactivity_timeout";
                    }
                    request = self.controls.recv() => {
                        let Some(request) = request else {
                            break "control_channel_closed";
                        };
                        let commands = self.protocol.control(request.control);
                        match commands {
                            Err(error) => {
                                let _ = request.reply.send(Err(error));
                            }
                            Ok(commands) => {
                                let result = send_commands_split(
                                    &mut writer,
                                    &self.output,
                                    &source,
                                    epoch,
                                    &mut sequence,
                                    &commands,
                                    self.policy.subscription_message_interval,
                                ).await;
                                if result.is_ok() {
                                    self.protocol.commands_sent();
                                    let _ = request.reply.send(Ok(()));
                                } else {
                                    let _ = request.reply.send(Err(ProtocolError { message: "socket write failed".to_owned() }));
                                    break "control_write_failed";
                                }
                            }
                        }
                    }
                    message = reader.next() => {
                        let Some(message) = message else {
                            break "peer_closed";
                        };
                        let Ok(message) = message else {
                            break "read_failed";
                        };
                        silence.as_mut().reset(tokio::time::Instant::now() + self.policy.inactivity_timeout);
                        let (body, content_type) = match message {
                            Message::Text(text) => (Bytes::copy_from_slice(text.as_bytes()), ContentType::Json),
                            Message::Binary(bytes) => (bytes, ContentType::Binary),
                            Message::Close(_) => break "peer_closed",
                            Message::Ping(payload) => {
                                if writer.send(Message::Pong(payload)).await.is_err() {
                                    break "pong_failed";
                                }
                                continue;
                            }
                            Message::Pong(_) | Message::Frame(_) => continue,
                        };
                        let interpretation = self.protocol.classify(&body);
                        sequence = sequence.saturating_add(1);
                        let received_at = now_millis();
                        let frame = RawSourceFrame::inbound_websocket(
                            source.clone(),
                            interpretation.stream_class,
                            received_at,
                            epoch,
                            sequence,
                            content_type,
                            body,
                        );
                        if emit(&self.output, SourceOutput::Frame(frame)).is_err() {
                            health.apply(received_at, &HealthEvent::IngressSaturated);
                            return exit(&health, &coverage, "ingress_saturated");
                        }
                        if emit_health(&self.output, &mut health, received_at, HealthEvent::FrameAccepted).is_err() {
                            return exit(&health, &coverage, "ingress_saturated");
                        }
                        if let Some(cursor) = interpretation.cursor {
                            let event = coverage.observed(cursor, received_at);
                            if emit(&self.output, SourceOutput::Coverage(event)).is_err() {
                                return exit(&health, &coverage, "ingress_saturated");
                            }
                        }
                        if let Some(event) = interpretation.health
                            && emit_health(&self.output, &mut health, received_at, event).is_err()
                        {
                            return exit(&health, &coverage, "ingress_saturated");
                        }
                    }
                }
            };

            self.protocol.disconnected();
            let now = now_millis();
            if disconnect_reason == "cancelled" {
                let _ = emit_health(
                    &self.output,
                    &mut health,
                    now,
                    HealthEvent::Stopped {
                        reason: "cancelled".to_owned(),
                    },
                );
                let _ = emit(
                    &self.output,
                    SourceOutput::Coverage(coverage.stop(now, "cancelled")),
                );
                return exit(&health, &coverage, "cancelled");
            }
            if emit_health(
                &self.output,
                &mut health,
                now,
                HealthEvent::Disconnected {
                    reason: disconnect_reason.to_owned(),
                },
            )
            .is_err()
            {
                return exit(&health, &coverage, "ingress_saturated");
            }
            if let Some(event) = coverage.disconnected(now, disconnect_reason)
                && emit(&self.output, SourceOutput::Coverage(event)).is_err()
            {
                return exit(&health, &coverage, "ingress_saturated");
            }
            if !self.wait_backoff(&mut health, &mut backoff).await {
                return exit(&health, &coverage, "cancelled");
            }
        }
    }

    async fn wait_backoff(&self, health: &mut SourceHealth, backoff: &mut Backoff) -> bool {
        let entropy = u64::try_from(now_millis().0).unwrap_or_default();
        let delay = backoff.next_delay(entropy);
        if emit_health(
            &self.output,
            health,
            now_millis(),
            HealthEvent::BackoffStarted {
                delay_ms: delay.as_millis().try_into().unwrap_or(u64::MAX),
            },
        )
        .is_err()
        {
            return false;
        }
        tokio::select! {
            () = self.cancellation.cancelled() => false,
            () = tokio::time::sleep(delay) => true,
        }
    }
}

async fn send_commands<S>(
    socket: &mut tokio_tungstenite::WebSocketStream<S>,
    output: &BoundedIngress<SourceOutput>,
    source: &SourceId,
    epoch: u64,
    sequence: &mut u64,
    commands: &[WebSocketCommand],
    interval: Duration,
) -> Result<(), ()>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
{
    for (index, command) in commands.iter().enumerate() {
        socket
            .send(Message::Text(
                String::from_utf8_lossy(&command.body).into_owned().into(),
            ))
            .await
            .map_err(|_| ())?;
        record_outbound(output, source, epoch, sequence, command)?;
        if index + 1 < commands.len() {
            tokio::time::sleep(interval).await;
        }
    }
    Ok(())
}

async fn send_commands_split<S>(
    writer: &mut futures_util::stream::SplitSink<tokio_tungstenite::WebSocketStream<S>, Message>,
    output: &BoundedIngress<SourceOutput>,
    source: &SourceId,
    epoch: u64,
    sequence: &mut u64,
    commands: &[WebSocketCommand],
    interval: Duration,
) -> Result<(), ()>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
{
    for (index, command) in commands.iter().enumerate() {
        writer
            .send(Message::Text(
                String::from_utf8_lossy(&command.body).into_owned().into(),
            ))
            .await
            .map_err(|_| ())?;
        record_outbound(output, source, epoch, sequence, command)?;
        if index + 1 < commands.len() {
            tokio::time::sleep(interval).await;
        }
    }
    Ok(())
}

fn record_outbound(
    output: &BoundedIngress<SourceOutput>,
    source: &SourceId,
    epoch: u64,
    sequence: &mut u64,
    command: &WebSocketCommand,
) -> Result<(), ()> {
    *sequence = sequence.saturating_add(1);
    let frame = RawSourceFrame {
        contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
        source: source.clone(),
        transport: crate::Transport::WebSocket,
        stream_class: command.stream_class,
        direction: FrameDirection::OutboundControl,
        content_type: ContentType::Json,
        received_at: now_millis(),
        connection_epoch: epoch,
        sequence: *sequence,
        http_status: None,
        safe_headers: Vec::new(),
        body: command.body.clone(),
    };
    emit(output, SourceOutput::Frame(frame))
}

fn emit(output: &BoundedIngress<SourceOutput>, item: SourceOutput) -> Result<(), ()> {
    output.try_send(item).map_err(|error| match error {
        IngressError::Full(_) | IngressError::Closed(_) => (),
    })
}

fn emit_health(
    output: &BoundedIngress<SourceOutput>,
    health: &mut SourceHealth,
    at: UnixMillis,
    event: HealthEvent,
) -> Result<(), ()> {
    health.apply(at, &event);
    emit(
        output,
        SourceOutput::Health {
            at,
            event,
            snapshot: health.snapshot().clone(),
        },
    )
}

fn exit(health: &SourceHealth, coverage: &CoverageTracker, reason: &'static str) -> WebSocketExit {
    WebSocketExit {
        health: health.snapshot().clone(),
        coverage_state: coverage.state().clone(),
        reason,
    }
}

fn now_millis() -> UnixMillis {
    let millis = time::OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000;
    UnixMillis(millis.try_into().unwrap_or(if millis.is_negative() {
        i64::MIN
    } else {
        i64::MAX
    }))
}
