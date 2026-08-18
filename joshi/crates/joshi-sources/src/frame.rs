use bytes::Bytes;
use serde::{Deserialize, Serialize};

/// Milliseconds since the Unix epoch. A named integer prevents accidental wall-clock floats.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct UnixMillis(pub i64);

#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceId {
    HeliusHttp,
    HeliusWebSocket,
    PumpPortalWebSocket,
    SolanaPublicHttp,
    SolanaPublicWebSocket,
    Other(String),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Transport {
    Http,
    WebSocket,
    Fixture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StreamClass {
    BroadCensus,
    LeasedHot,
    Backfill,
    Control,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContentType {
    Json,
    Binary,
    Text,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FrameDirection {
    Inbound,
    OutboundControl,
}

/// A deliberately small allowlist of non-secret response headers useful for rate control.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SafeHeader {
    pub name: String,
    pub value: String,
}

/// Exact provider bytes plus receipt provenance.
///
/// `body` is never a reserialization of parsed JSON. Derivations may point at this observation,
/// but must not replace it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RawSourceFrame {
    pub contract_version: String,
    pub source: SourceId,
    pub transport: Transport,
    pub stream_class: StreamClass,
    pub direction: FrameDirection,
    pub content_type: ContentType,
    pub received_at: UnixMillis,
    pub connection_epoch: u64,
    pub sequence: u64,
    pub http_status: Option<u16>,
    pub safe_headers: Vec<SafeHeader>,
    pub body: Bytes,
}

impl RawSourceFrame {
    #[must_use]
    pub fn inbound_websocket(
        source: SourceId,
        stream_class: StreamClass,
        received_at: UnixMillis,
        connection_epoch: u64,
        sequence: u64,
        content_type: ContentType,
        body: Bytes,
    ) -> Self {
        Self {
            contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
            source,
            transport: Transport::WebSocket,
            stream_class,
            direction: FrameDirection::Inbound,
            content_type,
            received_at,
            connection_epoch,
            sequence,
            http_status: None,
            safe_headers: Vec::new(),
            body,
        }
    }
}
