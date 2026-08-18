use std::{
    collections::BTreeMap,
    fmt,
    sync::atomic::{AtomicU64, Ordering},
};

use bytes::Bytes;
use reqwest::{Client, StatusCode, header::HeaderMap};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use thiserror::Error;

use crate::{
    config::{
        ConfigError, HeliusConfig, LoadedHeliusConfig, PublicSolanaRpcConfig, authenticated_url,
    },
    coverage::Cursor,
    frame::{
        ContentType, FrameDirection, RawSourceFrame, SafeHeader, SourceId, StreamClass, Transport,
        UnixMillis,
    },
    health::HealthEvent,
    websocket::{FrameInterpretation, ProtocolError, WebSocketCommand, WebSocketProtocol},
};

/// The HTTP adapter cannot represent a write method. Adding one requires changing this enum.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SolanaReadMethod {
    GetAccountInfo,
    GetMultipleAccounts,
    GetProgramAccounts,
    GetSignaturesForAddress,
    GetTransaction,
    GetBlock,
    GetSlot,
    GetBlockHeight,
    GetSignatureStatuses,
}

impl SolanaReadMethod {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::GetAccountInfo => "getAccountInfo",
            Self::GetMultipleAccounts => "getMultipleAccounts",
            Self::GetProgramAccounts => "getProgramAccounts",
            Self::GetSignaturesForAddress => "getSignaturesForAddress",
            Self::GetTransaction => "getTransaction",
            Self::GetBlock => "getBlock",
            Self::GetSlot => "getSlot",
            Self::GetBlockHeight => "getBlockHeight",
            Self::GetSignatureStatuses => "getSignatureStatuses",
        }
    }

    #[must_use]
    pub const fn stream_class(self) -> StreamClass {
        match self {
            Self::GetBlock | Self::GetSignaturesForAddress | Self::GetTransaction => {
                StreamClass::Backfill
            }
            _ => StreamClass::Control,
        }
    }
}

#[derive(Clone, Debug)]
pub struct SolanaReadRequest {
    pub method: SolanaReadMethod,
    pub params: Value,
}

impl SolanaReadRequest {
    #[must_use]
    pub fn new(method: SolanaReadMethod, params: Value) -> Self {
        Self { method, params }
    }

    fn encode(&self, id: u64) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(&json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": self.method.as_str(),
            "params": self.params,
        }))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RateLimitSignal {
    pub http_status: Option<u16>,
    pub rpc_code: Option<i64>,
    pub retry_after_ms: Option<u64>,
}

#[derive(Error, Debug)]
pub enum HeliusError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("unable to encode JSON-RPC request")]
    Encode(#[from] serde_json::Error),
    /// Deliberately omits `reqwest::Error`: it can retain the authenticated URL.
    #[error("Helius HTTP transport failed; authenticated URL omitted")]
    Transport,
    #[error("Helius HTTP response body failed; authenticated URL omitted")]
    ResponseBody,
}

pub struct HeliusHttpClient {
    client: Client,
    loaded: LoadedHeliusConfig,
    next_request_id: AtomicU64,
}

pub struct PublicSolanaHttpClient {
    client: Client,
    endpoint: url::Url,
    next_request_id: AtomicU64,
}

impl fmt::Debug for PublicSolanaHttpClient {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PublicSolanaHttpClient")
            .field("scheme", &self.endpoint.scheme())
            .field("host", &self.endpoint.host_str())
            .field(
                "next_request_id",
                &self.next_request_id.load(Ordering::Relaxed),
            )
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for HeliusHttpClient {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HeliusHttpClient")
            .field("config", &self.loaded)
            .field(
                "next_request_id",
                &self.next_request_id.load(Ordering::Relaxed),
            )
            .finish_non_exhaustive()
    }
}

impl HeliusHttpClient {
    /// Loads the credential exactly once, while constructing the live adapter.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid configuration, unreadable credential, or HTTP-client
    /// construction failure. Transport errors never expose the authenticated URL.
    pub fn at_startup(config: &HeliusConfig) -> Result<Self, HeliusError> {
        let loaded = config.load()?;
        let client = Client::builder()
            .timeout(loaded.request_timeout)
            .user_agent("joshi-sources/0.1 read-only")
            .build()
            .map_err(|_| HeliusError::Transport)?;
        Ok(Self {
            client,
            loaded,
            next_request_id: AtomicU64::new(1),
        })
    }

    /// Perform one allowlisted read-only JSON-RPC request and preserve the exact response bytes.
    ///
    /// # Errors
    ///
    /// Returns a sanitized error when encoding, transport, or response-body acquisition fails.
    pub async fn request(
        &self,
        request: &SolanaReadRequest,
        received_at: UnixMillis,
        sequence: u64,
    ) -> Result<(RawSourceFrame, Option<RateLimitSignal>), HeliusError> {
        let id = self.next_request_id.fetch_add(1, Ordering::Relaxed);
        let body = request.encode(id)?;
        let endpoint = authenticated_url(&self.loaded.http_url, Some(&self.loaded.api_key));
        let response = self
            .client
            .post(endpoint)
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(body)
            .send()
            .await
            .map_err(|_| HeliusError::Transport)?;
        let status = response.status();
        let headers = safe_headers(response.headers());
        let raw_body = response
            .bytes()
            .await
            .map_err(|_| HeliusError::ResponseBody)?;
        let rate_limit = classify_rate_limit(status, &headers, &raw_body);
        Ok((
            RawSourceFrame {
                contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
                source: SourceId::HeliusHttp,
                transport: Transport::Http,
                stream_class: request.method.stream_class(),
                direction: FrameDirection::Inbound,
                content_type: ContentType::Json,
                received_at,
                connection_epoch: 0,
                sequence,
                http_status: Some(status.as_u16()),
                safe_headers: headers,
                body: raw_body,
            },
            rate_limit,
        ))
    }
}

impl PublicSolanaHttpClient {
    /// Construct a client for a validated unauthenticated Solana RPC endpoint.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid configuration or HTTP-client construction failure.
    pub fn at_startup(config: &PublicSolanaRpcConfig) -> Result<Self, HeliusError> {
        let (endpoint, _websocket_endpoint) = config.validate()?;
        let client = Client::builder()
            .timeout(std::time::Duration::from_millis(config.request_timeout_ms))
            .user_agent("joshi-sources/0.1 read-only")
            .build()
            .map_err(|_| HeliusError::Transport)?;
        Ok(Self {
            client,
            endpoint,
            next_request_id: AtomicU64::new(1),
        })
    }

    /// Perform one allowlisted read-only JSON-RPC request and preserve the exact response bytes.
    ///
    /// # Errors
    ///
    /// Returns a sanitized error when encoding, transport, or response-body acquisition fails.
    pub async fn request(
        &self,
        request: &SolanaReadRequest,
        received_at: UnixMillis,
        sequence: u64,
    ) -> Result<(RawSourceFrame, Option<RateLimitSignal>), HeliusError> {
        let id = self.next_request_id.fetch_add(1, Ordering::Relaxed);
        let body = request.encode(id)?;
        let response = self
            .client
            .post(self.endpoint.clone())
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(body)
            .send()
            .await
            .map_err(|_| HeliusError::Transport)?;
        let status = response.status();
        let headers = safe_headers(response.headers());
        let raw_body = response
            .bytes()
            .await
            .map_err(|_| HeliusError::ResponseBody)?;
        let rate_limit = classify_rate_limit(status, &headers, &raw_body);
        Ok((
            RawSourceFrame {
                contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
                source: SourceId::SolanaPublicHttp,
                transport: Transport::Http,
                stream_class: request.method.stream_class(),
                direction: FrameDirection::Inbound,
                content_type: ContentType::Json,
                received_at,
                connection_epoch: 0,
                sequence,
                http_status: Some(status.as_u16()),
                safe_headers: headers,
                body: raw_body,
            },
            rate_limit,
        ))
    }
}

fn safe_headers(headers: &HeaderMap) -> Vec<SafeHeader> {
    const ALLOWED: &[&str] = &[
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    ];
    let mut safe = Vec::new();
    for name in ALLOWED {
        let Some(value) = headers.get(*name) else {
            continue;
        };
        let Ok(value) = value.to_str() else {
            continue;
        };
        if value.len() <= 256 && !value.chars().any(char::is_control) {
            safe.push(SafeHeader {
                name: (*name).to_owned(),
                value: value.to_owned(),
            });
        }
    }
    safe
}

#[must_use]
pub fn classify_rate_limit(
    status: StatusCode,
    headers: &[SafeHeader],
    body: &[u8],
) -> Option<RateLimitSignal> {
    let rpc_code = serde_json::from_slice::<Value>(body)
        .ok()
        .and_then(|value| value.pointer("/error/code").and_then(Value::as_i64));
    if status != StatusCode::TOO_MANY_REQUESTS && rpc_code != Some(-32005) {
        return None;
    }
    let retry_after_ms = headers
        .iter()
        .find(|header| header.name.eq_ignore_ascii_case("retry-after"))
        .and_then(|header| header.value.parse::<u64>().ok())
        .map(|seconds| seconds.saturating_mul(1_000));
    Some(RateLimitSignal {
        http_status: Some(status.as_u16()),
        rpc_code,
        retry_after_ms,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HeliusSubscription {
    PumpProgramLogs {
        program: String,
        commitment: String,
    },
    Account {
        pubkey: String,
        commitment: String,
    },
    ProgramAccounts {
        program: String,
        commitment: String,
    },
    Signature {
        signature: String,
        commitment: String,
    },
    Root,
    Slots,
}

impl HeliusSubscription {
    /// Validate all address-shaped inputs before generating a subscription command.
    ///
    /// # Errors
    ///
    /// Returns an error when an address or signature is not valid base58 of the expected length.
    pub fn validate(&self) -> Result<(), &'static str> {
        match self {
            Self::PumpProgramLogs { program, .. } | Self::ProgramAccounts { program, .. } => {
                validate_address(program)
            }
            Self::Account { pubkey, .. } => validate_address(pubkey),
            Self::Signature { signature, .. } => {
                let decoded = bs58::decode(signature)
                    .into_vec()
                    .map_err(|_| "invalid signature")?;
                if decoded.len() == 64 {
                    Ok(())
                } else {
                    Err("invalid signature")
                }
            }
            Self::Root | Self::Slots => Ok(()),
        }
    }

    /// Encode the standard Solana JSON-RPC subscription request.
    ///
    /// # Errors
    ///
    /// Returns an error if JSON serialization fails.
    pub fn request(&self, id: u64) -> Result<Bytes, serde_json::Error> {
        let (method, params) = match self {
            Self::PumpProgramLogs {
                program,
                commitment,
            } => (
                "logsSubscribe",
                json!([{"mentions": [program]}, {"commitment": commitment}]),
            ),
            Self::Account { pubkey, commitment } => (
                "accountSubscribe",
                json!([pubkey, {"encoding": "base64", "commitment": commitment}]),
            ),
            Self::ProgramAccounts {
                program,
                commitment,
            } => (
                "programSubscribe",
                json!([program, {"encoding": "base64", "commitment": commitment}]),
            ),
            Self::Signature {
                signature,
                commitment,
            } => (
                "signatureSubscribe",
                json!([signature, {"commitment": commitment, "enableReceivedNotification": true}]),
            ),
            Self::Root => ("rootSubscribe", json!([])),
            Self::Slots => ("slotSubscribe", json!([])),
        };
        serde_json::to_vec(&json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}))
            .map(Bytes::from)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HeliusFrameKind {
    SubscriptionAcknowledged,
    Notification,
    RpcError {
        code: Option<i64>,
        message: Option<String>,
    },
    Unknown,
    Malformed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeliusFrameMetadata {
    pub kind: HeliusFrameKind,
    pub cursor: Option<Cursor>,
    pub subscription_id: Option<u64>,
}

#[derive(Clone, Debug, Default)]
pub struct HeliusWsProtocol {
    pending: BTreeMap<u64, StreamClass>,
    active: BTreeMap<u64, StreamClass>,
}

impl HeliusWsProtocol {
    pub fn register_request(&mut self, request_id: u64, class: StreamClass) {
        self.pending.insert(request_id, class);
    }

    #[must_use]
    pub fn classify(&mut self, bytes: &[u8]) -> (StreamClass, HeliusFrameMetadata) {
        let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
            return (
                StreamClass::Control,
                HeliusFrameMetadata {
                    kind: HeliusFrameKind::Malformed,
                    cursor: None,
                    subscription_id: None,
                },
            );
        };
        if let Some(error) = value.get("error") {
            return (
                StreamClass::Control,
                HeliusFrameMetadata {
                    kind: HeliusFrameKind::RpcError {
                        code: error.get("code").and_then(Value::as_i64),
                        message: error
                            .get("message")
                            .and_then(Value::as_str)
                            .map(ToOwned::to_owned),
                    },
                    cursor: None,
                    subscription_id: None,
                },
            );
        }
        if let (Some(request_id), Some(subscription_id)) = (
            value.get("id").and_then(Value::as_u64),
            value.get("result").and_then(Value::as_u64),
        ) {
            let class = self
                .pending
                .remove(&request_id)
                .unwrap_or(StreamClass::Control);
            self.active.insert(subscription_id, class);
            return (
                StreamClass::Control,
                HeliusFrameMetadata {
                    kind: HeliusFrameKind::SubscriptionAcknowledged,
                    cursor: None,
                    subscription_id: Some(subscription_id),
                },
            );
        }
        let subscription_id = value
            .pointer("/params/subscription")
            .and_then(Value::as_u64);
        let class = subscription_id
            .and_then(|id| self.active.get(&id).copied())
            .unwrap_or(StreamClass::Control);
        let slot = value
            .pointer("/params/result/context/slot")
            .and_then(Value::as_u64)
            .or_else(|| value.pointer("/params/result/slot").and_then(Value::as_u64))
            .or_else(|| {
                value
                    .get("params")
                    .and_then(|params| params.get("result"))
                    .and_then(Value::as_u64)
            });
        (
            class,
            HeliusFrameMetadata {
                kind: if value.get("method").is_some() {
                    HeliusFrameKind::Notification
                } else {
                    HeliusFrameKind::Unknown
                },
                cursor: slot.map(Cursor::SolanaSlot),
                subscription_id,
            },
        )
    }

    pub fn reset_connection(&mut self) {
        self.pending.clear();
        self.active.clear();
    }
}

fn validate_address(value: &str) -> Result<(), &'static str> {
    let decoded = bs58::decode(value)
        .into_vec()
        .map_err(|_| "invalid Solana address")?;
    if decoded.len() == 32 {
        Ok(())
    } else {
        Err("invalid Solana address")
    }
}

#[derive(Clone, Debug)]
pub enum HeliusControl {
    AddSubscription {
        subscription: HeliusSubscription,
        stream_class: StreamClass,
    },
}

#[derive(Clone, Debug)]
pub struct HeliusWsAdapter {
    subscriptions: Vec<(HeliusSubscription, StreamClass)>,
    protocol: HeliusWsProtocol,
    next_request_id: u64,
}

impl HeliusWsAdapter {
    /// Validate and construct a read-only Helius WebSocket protocol adapter.
    ///
    /// # Errors
    ///
    /// Returns an error when any configured subscription is invalid.
    pub fn new(
        subscriptions: Vec<(HeliusSubscription, StreamClass)>,
    ) -> Result<Self, ProtocolError> {
        for (subscription, _) in &subscriptions {
            subscription.validate().map_err(|message| ProtocolError {
                message: message.to_owned(),
            })?;
        }
        Ok(Self {
            subscriptions,
            protocol: HeliusWsProtocol::default(),
            next_request_id: 1,
        })
    }

    fn command(
        &mut self,
        subscription: &HeliusSubscription,
        stream_class: StreamClass,
    ) -> Result<WebSocketCommand, ProtocolError> {
        subscription.validate().map_err(|message| ProtocolError {
            message: message.to_owned(),
        })?;
        let request_id = self.next_request_id;
        self.next_request_id = self.next_request_id.saturating_add(1);
        self.protocol.register_request(request_id, stream_class);
        Ok(WebSocketCommand {
            stream_class,
            body: subscription.request(request_id)?,
        })
    }
}

impl WebSocketProtocol for HeliusWsAdapter {
    type Control = HeliusControl;

    fn source_id(&self) -> SourceId {
        SourceId::HeliusWebSocket
    }

    fn connected(&mut self) -> Result<Vec<WebSocketCommand>, ProtocolError> {
        self.protocol.reset_connection();
        let subscriptions = self.subscriptions.clone();
        subscriptions
            .iter()
            .map(|(subscription, class)| self.command(subscription, *class))
            .collect()
    }

    fn control(&mut self, control: Self::Control) -> Result<Vec<WebSocketCommand>, ProtocolError> {
        match control {
            HeliusControl::AddSubscription {
                subscription,
                stream_class,
            } => {
                let command = self.command(&subscription, stream_class)?;
                self.subscriptions.push((subscription, stream_class));
                Ok(vec![command])
            }
        }
    }

    fn commands_sent(&mut self) {}

    fn classify(&mut self, bytes: &[u8]) -> FrameInterpretation {
        let (stream_class, metadata) = self.protocol.classify(bytes);
        let health = match metadata.kind {
            HeliusFrameKind::Malformed => Some(HealthEvent::MalformedFrame {
                reason: "invalid Helius JSON websocket frame".to_owned(),
            }),
            HeliusFrameKind::RpcError {
                code: Some(-32005), ..
            } => Some(HealthEvent::RateLimited {
                retry_after_ms: None,
            }),
            HeliusFrameKind::RpcError { message, .. } => Some(HealthEvent::SubscriptionRejected {
                reason: message.unwrap_or_else(|| "Helius JSON-RPC error".to_owned()),
            }),
            _ => None,
        };
        FrameInterpretation {
            stream_class,
            cursor: metadata.cursor,
            health,
        }
    }

    fn disconnected(&mut self) {
        self.protocol.reset_connection();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PUMP_PROGRAM: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";

    #[test]
    fn read_method_set_contains_no_transaction_submission_or_simulation() {
        let methods = [
            SolanaReadMethod::GetAccountInfo,
            SolanaReadMethod::GetMultipleAccounts,
            SolanaReadMethod::GetProgramAccounts,
            SolanaReadMethod::GetSignaturesForAddress,
            SolanaReadMethod::GetTransaction,
            SolanaReadMethod::GetBlock,
            SolanaReadMethod::GetSlot,
            SolanaReadMethod::GetBlockHeight,
            SolanaReadMethod::GetSignatureStatuses,
        ];
        let names: Vec<_> = methods.into_iter().map(SolanaReadMethod::as_str).collect();
        assert!(names.iter().all(|name| !name.starts_with("send")));
        assert!(!names.contains(&"simulateTransaction"));
        assert!(!names.contains(&"getLatestBlockhash"));
    }

    #[test]
    fn logs_subscription_is_standard_solana_json_rpc() {
        let subscription = HeliusSubscription::PumpProgramLogs {
            program: PUMP_PROGRAM.to_owned(),
            commitment: "processed".to_owned(),
        };
        subscription.validate().unwrap();
        let request = subscription.request(7).unwrap();
        let value: Value = serde_json::from_slice(&request).unwrap();
        assert_eq!(value["method"], "logsSubscribe");
        assert_eq!(value["params"][0]["mentions"][0], PUMP_PROGRAM);
    }

    #[test]
    fn subscription_ack_maps_later_frames_to_the_registered_class() {
        let mut protocol = HeliusWsProtocol::default();
        protocol.register_request(7, StreamClass::BroadCensus);
        let (class, ack) = protocol.classify(br#"{"jsonrpc":"2.0","result":99,"id":7}"#);
        assert_eq!(class, StreamClass::Control);
        assert_eq!(ack.kind, HeliusFrameKind::SubscriptionAcknowledged);
        let (class, frame) = protocol.classify(
            br#"{"jsonrpc":"2.0","method":"logsNotification","params":{"result":{"context":{"slot":123},"value":{"signature":"x","err":null,"logs":[]}},"subscription":99}}"#,
        );
        assert_eq!(class, StreamClass::BroadCensus);
        assert_eq!(frame.cursor, Some(Cursor::SolanaSlot(123)));
    }

    #[test]
    fn rate_limit_is_derived_without_rewriting_body() {
        let body =
            br#"{"jsonrpc":"2.0","error":{"code":-32005,"message":"Too many requests"},"id":1}"#;
        let signal = classify_rate_limit(
            StatusCode::OK,
            &[SafeHeader {
                name: "retry-after".to_owned(),
                value: "2".to_owned(),
            }],
            body,
        )
        .unwrap();
        assert_eq!(signal.rpc_code, Some(-32005));
        assert_eq!(signal.retry_after_ms, Some(2_000));
    }
}
