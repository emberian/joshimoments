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
    solana_json_rpc::INGEST_MAX_RESPONSE_BYTES,
    websocket::{FrameInterpretation, ProtocolError, WebSocketCommand, WebSocketProtocol},
};

/// Default admitted response entity body ceiling for both HTTP clients, in bytes.
///
/// This is [`crate::INGEST_MAX_RESPONSE_BYTES`] widened to `u64`, and is deliberately not a second
/// literal: the supervisor's physical-size derivation is computed from the same constant, so the
/// reader that abandons an oversized body and the derivation that budgets for one cannot disagree.
/// A caller whose durable sink can absorb more may construct a client with a larger ceiling; a
/// caller that wants a narrower one may pass that instead. Neither constructor has a default that
/// is *unbounded*, which is the property that matters.
pub const DEFAULT_MAX_RESPONSE_BYTES: u64 = INGEST_MAX_RESPONSE_BYTES as u64;

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

/// Refusals from the two bounded read-only HTTP paths.
///
/// No variant carries a URL, host, request body, response body, header value, or credential, and
/// no `reqwest::Error` is ever stored or rendered — `reqwest`'s own `Display` prints the request
/// URL, and on the authenticated path that URL carries the API key. Errors are classified through
/// `reqwest`'s predicates and then dropped. `no_refusal_renders_a_locator_or_a_credential`
/// formats every variant in both `Display` and `Debug` and refuses any rendering that contains a
/// locator- or credential-shaped substring.
#[derive(Error, Debug)]
pub enum HeliusError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("unable to encode JSON-RPC request")]
    Encode(#[from] serde_json::Error),
    /// The admitted response ceiling was zero, so no response could ever be accepted.
    #[error("the configured response ceiling admits zero bytes and can never carry a response")]
    ZeroCeiling,
    /// Deliberately omits `reqwest::Error`: it can retain the authenticated URL.
    #[error("Helius HTTP transport failed; authenticated URL omitted")]
    Transport,
    #[error("Helius HTTP response body failed; authenticated URL omitted")]
    ResponseBody,
    /// The declared body length was present but not a plain decimal byte count.
    ///
    /// **Not reachable through a live response.** `hyper` refuses a response whose
    /// `Content-Length` is not a decimal byte count while it is decoding the head, so `request`
    /// never sees such a header and returns a stream-level refusal instead. The guard is kept
    /// because it is what decides, and it is exercised directly as the function it is by
    /// `a_declared_length_that_is_not_a_plain_byte_count_is_refused`; deleting the branch fails
    /// that test. It becomes live if the head decoder is ever replaced by one that passes an
    /// unparsed declaration through.
    #[error("the response declared a body length that is not a plain byte count")]
    MalformedDeclaredLength,
    /// The declared body length was already over the ceiling, before any body byte was read.
    #[error("the response declared {declared} body bytes, over the {ceiling} byte ceiling")]
    DeclaredLengthOverCeiling {
        /// The length the response declared.
        declared: u64,
        /// The admitted ceiling.
        ceiling: u64,
    },
    /// The declared body length disagreed with the bytes actually delivered.
    #[error(
        "the response declared {declared} body bytes and delivered {delivered}; the two must agree"
    )]
    DeclaredLengthMismatch {
        /// The length the response declared.
        declared: u64,
        /// The number of bytes actually delivered.
        delivered: u64,
    },
    /// The body passed the admitted ceiling while streaming, and was abandoned there.
    #[error("the response body passed the {ceiling} byte ceiling and was abandoned")]
    BodyOverCeiling {
        /// The admitted ceiling.
        ceiling: u64,
    },
}

pub struct HeliusHttpClient {
    client: Client,
    loaded: LoadedHeliusConfig,
    next_request_id: AtomicU64,
    maximum_response_bytes: u64,
}

pub struct PublicSolanaHttpClient {
    client: Client,
    endpoint: url::Url,
    next_request_id: AtomicU64,
    maximum_response_bytes: u64,
}

impl fmt::Debug for PublicSolanaHttpClient {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PublicSolanaHttpClient")
            .field("scheme", &self.endpoint.scheme())
            .field("host", &self.endpoint.host_str())
            .field("maximum_response_bytes", &self.maximum_response_bytes)
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
            .field("maximum_response_bytes", &self.maximum_response_bytes)
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
    /// `maximum_response_bytes` is the ceiling every response this client reads is abandoned at.
    /// It is a constructor argument rather than a compiled-in constant because the ceiling that
    /// belongs here is a property of what the caller can durably retain, not of the endpoint;
    /// [`DEFAULT_MAX_RESPONSE_BYTES`] is the value derived from the shared ingest bound.
    ///
    /// # Errors
    ///
    /// Returns an error for a zero ceiling, an invalid configuration, an unreadable credential, or
    /// an HTTP-client construction failure. Transport errors never expose the authenticated URL.
    pub fn at_startup(
        config: &HeliusConfig,
        maximum_response_bytes: u64,
    ) -> Result<Self, HeliusError> {
        if maximum_response_bytes == 0 {
            return Err(HeliusError::ZeroCeiling);
        }
        let loaded = config.load()?;
        let client = Client::builder()
            // The Helius credential travels as an `api-key` query parameter, so a followed
            // redirect would put the secret in a `Referer` sent to whatever host the `Location`
            // named. reqwest follows up to ten redirects with the referer enabled by default. A
            // JSON-RPC POST has no legitimate reason to be redirected, so refuse instead.
            //
            // The scheme is not pinned here: `config::validate_endpoint` already requires https
            // for both clients at load, and additionally pins Helius to `.helius-rpc.com`. Pinning
            // it again at this layer would only make the loopback tests below unable to prove the
            // response bounding, which is the more valuable property to keep testable.
            .redirect(reqwest::redirect::Policy::none())
            .referer(false)
            .timeout(loaded.request_timeout)
            .user_agent("joshi-sources/0.1 read-only")
            .build()
            .map_err(|_| HeliusError::Transport)?;
        Ok(Self {
            client,
            loaded,
            next_request_id: AtomicU64::new(1),
            maximum_response_bytes,
        })
    }

    /// The admitted response ceiling this client abandons a body at, in bytes.
    #[must_use]
    pub const fn maximum_response_bytes(&self) -> u64 {
        self.maximum_response_bytes
    }

    /// Bind a private loopback base URL so hostile-response behaviour can be exercised offline.
    ///
    /// This exists only under `cfg(test)`, so it is compiled into this crate's own unit tests and
    /// into nothing else: no integration test, sibling crate, or external consumer can name it. It
    /// relaxes exactly one guard, the `.helius-rpc.com` HTTPS endpoint requirement, because a
    /// loopback listener speaking scripted plaintext bytes is what makes a lying framing testable
    /// at all. The credential is still loaded from a real file, so the authenticated request shape
    /// under test is the real one.
    #[cfg(test)]
    pub(crate) fn loopback(
        http_url: url::Url,
        api_key_file: &crate::config::CredentialFile,
        maximum_response_bytes: u64,
    ) -> Result<Self, HeliusError> {
        if maximum_response_bytes == 0 {
            return Err(HeliusError::ZeroCeiling);
        }
        let request_timeout = std::time::Duration::from_secs(2);
        let loaded = LoadedHeliusConfig {
            websocket_url: http_url.clone(),
            http_url,
            api_key: api_key_file.load()?,
            request_timeout,
            websocket_inactivity: request_timeout,
        };
        let client = Client::builder()
            // The Helius credential travels as an `api-key` query parameter, so a followed
            // redirect would put the secret in a `Referer` sent to whatever host the `Location`
            // named. reqwest follows up to ten redirects with the referer enabled by default. A
            // JSON-RPC POST has no legitimate reason to be redirected, so refuse instead.
            //
            // The scheme is not pinned here: `config::validate_endpoint` already requires https
            // for both clients at load, and additionally pins Helius to `.helius-rpc.com`. Pinning
            // it again at this layer would only make the loopback tests below unable to prove the
            // response bounding, which is the more valuable property to keep testable.
            .redirect(reqwest::redirect::Policy::none())
            .referer(false)
            .timeout(request_timeout)
            .user_agent("joshi-sources/0.1 read-only")
            .build()
            .map_err(|_| HeliusError::Transport)?;
        Ok(Self {
            client,
            loaded,
            next_request_id: AtomicU64::new(1),
            maximum_response_bytes,
        })
    }

    /// Perform one allowlisted read-only JSON-RPC request and preserve the exact response bytes.
    ///
    /// The response entity body is read incrementally and abandoned the moment the accumulated
    /// length *would* pass this client's ceiling; it is never read to completion first. A declared
    /// body length is compared against the ceiling before a single body byte is read, and against
    /// the delivered length once the stream ends.
    ///
    /// # Errors
    ///
    /// Returns a sanitized error when encoding or transport fails, when the response declares a
    /// malformed or over-ceiling body length, when the delivered length disagrees with the
    /// declared one, or when the body passes the ceiling. No error carries a URL, host, body, or
    /// header value.
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
        let raw_body = read_bounded_body(response, self.maximum_response_bytes).await?;
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
    /// `maximum_response_bytes` is the ceiling every response this client reads is abandoned at;
    /// see [`HeliusHttpClient::at_startup`] for why it is a constructor argument.
    ///
    /// # Errors
    ///
    /// Returns an error for a zero ceiling, an invalid configuration, or an HTTP-client
    /// construction failure.
    pub fn at_startup(
        config: &PublicSolanaRpcConfig,
        maximum_response_bytes: u64,
    ) -> Result<Self, HeliusError> {
        if maximum_response_bytes == 0 {
            return Err(HeliusError::ZeroCeiling);
        }
        let (endpoint, _websocket_endpoint) = config.validate()?;
        let client = Client::builder()
            // The Helius credential travels as an `api-key` query parameter, so a followed
            // redirect would put the secret in a `Referer` sent to whatever host the `Location`
            // named. reqwest follows up to ten redirects with the referer enabled by default. A
            // JSON-RPC POST has no legitimate reason to be redirected, so refuse instead.
            //
            // The scheme is not pinned here: `config::validate_endpoint` already requires https
            // for both clients at load, and additionally pins Helius to `.helius-rpc.com`. Pinning
            // it again at this layer would only make the loopback tests below unable to prove the
            // response bounding, which is the more valuable property to keep testable.
            .redirect(reqwest::redirect::Policy::none())
            .referer(false)
            .timeout(std::time::Duration::from_millis(config.request_timeout_ms))
            .user_agent("joshi-sources/0.1 read-only")
            .build()
            .map_err(|_| HeliusError::Transport)?;
        Ok(Self {
            client,
            endpoint,
            next_request_id: AtomicU64::new(1),
            maximum_response_bytes,
        })
    }

    /// The admitted response ceiling this client abandons a body at, in bytes.
    #[must_use]
    pub const fn maximum_response_bytes(&self) -> u64 {
        self.maximum_response_bytes
    }

    /// Bind a private loopback endpoint so hostile-response behaviour can be exercised offline.
    ///
    /// `cfg(test)`-only, for the same reason and with the same scope as
    /// [`HeliusHttpClient::loopback`]: it relaxes the HTTPS endpoint requirement and nothing else.
    #[cfg(test)]
    pub(crate) fn loopback(
        endpoint: url::Url,
        maximum_response_bytes: u64,
    ) -> Result<Self, HeliusError> {
        if maximum_response_bytes == 0 {
            return Err(HeliusError::ZeroCeiling);
        }
        let client = Client::builder()
            // The Helius credential travels as an `api-key` query parameter, so a followed
            // redirect would put the secret in a `Referer` sent to whatever host the `Location`
            // named. reqwest follows up to ten redirects with the referer enabled by default. A
            // JSON-RPC POST has no legitimate reason to be redirected, so refuse instead.
            //
            // The scheme is not pinned here: `config::validate_endpoint` already requires https
            // for both clients at load, and additionally pins Helius to `.helius-rpc.com`. Pinning
            // it again at this layer would only make the loopback tests below unable to prove the
            // response bounding, which is the more valuable property to keep testable.
            .redirect(reqwest::redirect::Policy::none())
            .referer(false)
            .timeout(std::time::Duration::from_secs(2))
            .user_agent("joshi-sources/0.1 read-only")
            .build()
            .map_err(|_| HeliusError::Transport)?;
        Ok(Self {
            client,
            endpoint,
            next_request_id: AtomicU64::new(1),
            maximum_response_bytes,
        })
    }

    /// Perform one allowlisted read-only JSON-RPC request and preserve the exact response bytes.
    ///
    /// The response entity body is read incrementally and abandoned the moment the accumulated
    /// length *would* pass this client's ceiling; it is never read to completion first. A declared
    /// body length is compared against the ceiling before a single body byte is read, and against
    /// the delivered length once the stream ends.
    ///
    /// # Errors
    ///
    /// Returns a sanitized error when encoding or transport fails, when the response declares a
    /// malformed or over-ceiling body length, when the delivered length disagrees with the
    /// declared one, or when the body passes the ceiling. No error carries a URL, host, body, or
    /// header value.
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
        let raw_body = read_bounded_body(response, self.maximum_response_bytes).await?;
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

/// Read the response entity body incrementally, abandoning it the moment it would pass the bound.
///
/// This is the whole boundedness argument for both HTTP clients, so it is written as one function
/// they share rather than duplicated at each call site. The accumulated length is compared
/// *before* each chunk is appended, so no allocation ever holds more than `ceiling` bytes and the
/// connection is dropped mid-stream rather than drained. A declared length narrows the bound
/// further and is checked in both directions: before the first body byte is read, and against the
/// delivered length once the stream ends.
///
/// The order matters and is not cosmetic. An earlier revision of both clients called
/// `Response::bytes()`, which reads to completion before anything can look at the result; this
/// repository measured 16 MiB of hostile input reaching a 294 MB peak RSS through exactly that
/// shape of unbounded read.
async fn read_bounded_body(
    mut response: reqwest::Response,
    ceiling: u64,
) -> Result<Bytes, HeliusError> {
    let declared = declared_body_length(response.headers())?;
    if let Some(declared) = declared
        && declared > ceiling
    {
        return Err(HeliusError::DeclaredLengthOverCeiling { declared, ceiling });
    }
    let capacity = usize::try_from(declared.unwrap_or(0).min(ceiling)).unwrap_or(0);
    let mut body: Vec<u8> = Vec::with_capacity(capacity);
    loop {
        let chunk = match response.chunk().await {
            Ok(Some(chunk)) => chunk,
            Ok(None) => break,
            Err(_) => return Err(HeliusError::ResponseBody),
        };
        let chunk_len = u64::try_from(chunk.len()).map_err(|_| HeliusError::ResponseBody)?;
        let accumulated = u64::try_from(body.len()).map_err(|_| HeliusError::ResponseBody)?;
        let projected = accumulated
            .checked_add(chunk_len)
            .ok_or(HeliusError::BodyOverCeiling { ceiling })?;
        if projected > ceiling {
            return Err(HeliusError::BodyOverCeiling { ceiling });
        }
        // A body that over-delivers against its own declared length is refused here rather than
        // accumulated. This is reachable: a response that sends both `Content-Length` and
        // `Transfer-Encoding: chunked` keeps both framings in the head, and the chunked decoder
        // then delivers whatever the chunks carry. A declaration alone still truncates, so the
        // over-delivery a plain `Content-Length` response writes past its declaration never
        // arrives; the two disagreeing framings are what makes this arm and the check after the
        // loop live.
        if let Some(declared) = declared
            && projected > declared
        {
            return Err(HeliusError::DeclaredLengthMismatch {
                declared,
                delivered: projected,
            });
        }
        body.extend_from_slice(&chunk);
    }
    let delivered = u64::try_from(body.len()).map_err(|_| HeliusError::ResponseBody)?;
    if let Some(declared) = declared
        && declared != delivered
    {
        return Err(HeliusError::DeclaredLengthMismatch {
            declared,
            delivered,
        });
    }
    Ok(Bytes::from(body))
}

/// Read the declared body length from the response head, if it declared one.
///
/// A missing declaration is allowed: a chunked response is legal and stays bounded by the ceiling.
/// A declaration that is not a plain decimal byte count is refused rather than ignored.
fn declared_body_length(headers: &HeaderMap) -> Result<Option<u64>, HeliusError> {
    let Some(value) = headers.get(reqwest::header::CONTENT_LENGTH) else {
        return Ok(None);
    };
    let Ok(value) = value.to_str() else {
        return Err(HeliusError::MalformedDeclaredLength);
    };
    let value = value.trim();
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(HeliusError::MalformedDeclaredLength);
    }
    value
        .parse::<u64>()
        .map(Some)
        .map_err(|_| HeliusError::MalformedDeclaredLength)
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

/// Private loopback scaffolding for this module's bounded-read unit tests.
///
/// It is compiled only under `cfg(test)`, so no integration test, sibling crate, or external
/// consumer can reach it. Everything here binds 127.0.0.1 with an ephemeral port and never
/// resolves a name, which is what keeps every test below offline: the only URL any of them hands
/// a client is this listener's own address.
#[cfg(test)]
pub(crate) mod probe {
    use std::{
        io::{Read as _, Write as _},
        net::{SocketAddr, TcpListener, TcpStream},
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
            mpsc,
        },
        thread,
        time::Duration,
    };

    /// A private loopback listener that answers each connection with one scripted response.
    ///
    /// The accept loop is the load-bearing part rather than a convenience: a second request
    /// necessarily arrives on a second connection, and a listener that accepted once and exited
    /// would leave it in the kernel backlog where no assertion could see it. Accepting in a loop
    /// and recording each request is what makes [`Loopback::request`] real.
    pub(crate) struct Loopback {
        addr: SocketAddr,
        requests: mpsc::Receiver<Vec<u8>>,
        stopping: Arc<AtomicBool>,
    }

    impl Loopback {
        pub(crate) fn start(response: Vec<u8>) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind a loopback listener");
            let addr = listener.local_addr().expect("loopback address");
            let (sender, requests) = mpsc::channel();
            let stopping = Arc::new(AtomicBool::new(false));
            let signal = Arc::clone(&stopping);
            thread::spawn(move || {
                loop {
                    let Ok((mut stream, _)) = listener.accept() else {
                        return;
                    };
                    if signal.load(Ordering::SeqCst) {
                        return;
                    }
                    stream
                        .set_read_timeout(Some(Duration::from_secs(5)))
                        .expect("loopback read timeout");
                    let request = read_request(&mut stream);
                    if request.is_empty() {
                        continue;
                    }
                    if sender.send(request).is_err() {
                        return;
                    }
                    // A refused response is expected to break the pipe part way through.
                    let _ = stream.write_all(&response);
                    let _ = stream.flush();
                }
            });
            Self {
                addr,
                requests,
                stopping,
            }
        }

        pub(crate) fn endpoint(&self) -> url::Url {
            format!("http://{}", self.addr)
                .parse()
                .expect("loopback endpoint")
        }

        /// The one request the listener observed, or a panic if it never arrived.
        pub(crate) fn request(&self) -> Vec<u8> {
            self.requests
                .recv_timeout(Duration::from_secs(5))
                .expect("the loopback listener observed one request")
        }

        /// True when the listener was never contacted within a short settling window.
        ///
        /// This is the negative of [`Loopback::request`] and exists for exactly one property: a
        /// host named by a `Location` header must receive no connection at all. The window is
        /// short because the redirect it guards against would have been followed immediately,
        /// within the same client call that already returned.
        pub(crate) fn observed_no_request(&self) -> bool {
            matches!(
                self.requests.recv_timeout(Duration::from_millis(250)),
                Err(mpsc::RecvTimeoutError::Timeout)
            )
        }
    }

    /// Wake the accept loop so the listener thread ends with its test rather than outliving it.
    impl Drop for Loopback {
        fn drop(&mut self) {
            self.stopping.store(true, Ordering::SeqCst);
            let _ = TcpStream::connect_timeout(&self.addr, Duration::from_millis(200));
        }
    }

    /// Read one whole HTTP/1 request: head to the blank line, then exactly its declared body.
    fn read_request(stream: &mut TcpStream) -> Vec<u8> {
        let mut raw = Vec::new();
        let mut byte = [0_u8; 1];
        while !raw.ends_with(b"\r\n\r\n") {
            match stream.read(&mut byte) {
                Ok(0) | Err(_) => return raw,
                Ok(_) => raw.push(byte[0]),
            }
        }
        let head = String::from_utf8_lossy(&raw).to_ascii_lowercase();
        let declared = head
            .lines()
            .find_map(|line| line.strip_prefix("content-length:"))
            .and_then(|value| value.trim().parse::<usize>().ok())
            .unwrap_or(0);
        let mut body = vec![0_u8; declared];
        if declared > 0 && stream.read_exact(&mut body).is_err() {
            return raw;
        }
        raw.extend_from_slice(&body);
        raw
    }

    /// One well-formed response with a declared body length.
    pub(crate) fn declared_response(body: &str, extra_headers: &str) -> Vec<u8> {
        format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n{extra_headers}\r\n{body}",
            body.len()
        )
        .into_bytes()
    }

    /// One chunked response, optionally carrying extra head lines and a terminating chunk.
    pub(crate) fn chunked_response(
        chunks: &[&str],
        extra_headers: &str,
        terminate: bool,
    ) -> Vec<u8> {
        use std::fmt::Write as _;
        let mut response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n{extra_headers}\r\n"
        );
        for chunk in chunks {
            let _ = write!(response, "{:x}\r\n{chunk}\r\n", chunk.len());
        }
        if terminate {
            response.push_str("0\r\n\r\n");
        }
        response.into_bytes()
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

    // -----------------------------------------------------------------------------------------
    // Bounded response reads, against a private loopback listener
    // -----------------------------------------------------------------------------------------

    use probe::{Loopback, chunked_response, declared_response};

    /// The one request every loopback test issues. Its shape is irrelevant to the bound; what is
    /// under test is what the *response* can make the client do.
    fn read_request() -> SolanaReadRequest {
        SolanaReadRequest::new(SolanaReadMethod::GetSlot, json!([]))
    }

    fn public_client(loopback: &Loopback, ceiling: u64) -> PublicSolanaHttpClient {
        PublicSolanaHttpClient::loopback(loopback.endpoint(), ceiling)
            .expect("bind the loopback public client")
    }

    /// Perform one request through the public client against a scripted loopback response.
    fn read_public(
        response: Vec<u8>,
        ceiling: u64,
    ) -> Result<(RawSourceFrame, Option<RateLimitSignal>), HeliusError> {
        let loopback = Loopback::start(response);
        let client = public_client(&loopback, ceiling);
        let outcome = runtime().block_on(client.request(&read_request(), UnixMillis(1_000), 1));
        // The request really did reach the listener, so a refusal below is a refusal of the
        // response rather than a connection that never happened.
        assert!(!loopback.request().is_empty());
        outcome
    }

    fn runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("single-threaded loopback runtime")
    }

    /// A JSON body of exactly `length` bytes: a padded string value, so it stays well-formed.
    ///
    /// The envelope `{"a":""}` is eight bytes, so the padding is `length - 8`. The length is
    /// asserted rather than assumed: a fixture that silently produced a shorter body than the
    /// ceiling would make the at-the-ceiling and over-the-ceiling tests both vacuous.
    fn body_of_exact_length(length: usize) -> String {
        assert!(
            length >= 8,
            "the shortest well-formed padded body is 8 bytes"
        );
        let body = format!("{{\"a\":\"{}\"}}", "z".repeat(length - 8));
        assert_eq!(
            body.len(),
            length,
            "the fixture body must be exactly {length} bytes"
        );
        body
    }

    #[test]
    fn a_body_at_exactly_the_ceiling_is_admitted_and_retained_byte_for_byte() {
        let body = body_of_exact_length(256);
        let (frame, rate_limit) =
            read_public(declared_response(&body, ""), 256).expect("a body at the ceiling");
        assert_eq!(frame.body.as_ref(), body.as_bytes());
        assert_eq!(frame.http_status, Some(200));
        assert!(rate_limit.is_none());
    }

    #[test]
    fn a_declared_length_one_byte_over_the_ceiling_is_refused_before_the_body_is_read() {
        let body = body_of_exact_length(257);
        let error = read_public(declared_response(&body, ""), 256)
            .expect_err("a declared length over the ceiling");
        assert!(
            matches!(
                error,
                HeliusError::DeclaredLengthOverCeiling {
                    declared: 257,
                    ceiling: 256
                }
            ),
            "expected a declared-length refusal, got {error:?}"
        );
    }

    /// A chunked response declares no length, so only the accumulating check can stop it.
    ///
    /// The chunks are sized so that no single one is over the ceiling: the refusal has to come
    /// from the accumulated total, which is what makes this a test of the incremental bound rather
    /// than of a single-chunk length check.
    #[test]
    fn an_undeclared_body_is_abandoned_the_moment_the_accumulated_length_passes_the_ceiling() {
        let chunk = "z".repeat(64);
        let chunks: Vec<&str> = std::iter::repeat_n(chunk.as_str(), 8).collect();
        let error = read_public(chunked_response(&chunks, "", true), 256)
            .expect_err("an accumulated body over the ceiling");
        assert!(
            matches!(error, HeliusError::BodyOverCeiling { ceiling: 256 }),
            "expected an accumulated-body refusal, got {error:?}"
        );
    }

    /// A response that sends both framings keeps both in the head, so the chunked decoder can
    /// deliver more than the declaration promised.
    #[test]
    fn a_chunked_body_that_over_delivers_against_its_declared_length_is_refused() {
        let error = read_public(
            chunked_response(&["0123456789"], "Content-Length: 4\r\n", true),
            256,
        )
        .expect_err("an over-delivering body");
        assert!(
            matches!(
                error,
                HeliusError::DeclaredLengthMismatch {
                    declared: 4,
                    delivered: 10
                }
            ),
            "expected an over-delivery refusal, got {error:?}"
        );
    }

    /// The same disagreement in the other direction: the stream ends under its declaration.
    #[test]
    fn a_chunked_body_that_under_delivers_against_its_declared_length_is_refused() {
        let error = read_public(
            chunked_response(&["0123"], "Content-Length: 10\r\n", true),
            256,
        )
        .expect_err("an under-delivering body");
        assert!(
            matches!(
                error,
                HeliusError::DeclaredLengthMismatch {
                    declared: 10,
                    delivered: 4
                }
            ),
            "expected an under-delivery refusal, got {error:?}"
        );
    }

    /// The declared-length parser is exercised as the function it is.
    ///
    /// `hyper` refuses a non-decimal `Content-Length` while decoding the head, so this branch is
    /// not reachable through a live response; deleting it still fails this test.
    #[test]
    fn a_declared_length_that_is_not_a_plain_byte_count_is_refused() {
        let mut headers = HeaderMap::new();
        headers.insert(
            reqwest::header::CONTENT_LENGTH,
            reqwest::header::HeaderValue::from_static("0x10"),
        );
        assert!(matches!(
            declared_body_length(&headers),
            Err(HeliusError::MalformedDeclaredLength)
        ));

        headers.insert(
            reqwest::header::CONTENT_LENGTH,
            reqwest::header::HeaderValue::from_static("12"),
        );
        assert!(matches!(declared_body_length(&headers), Ok(Some(12))));
        assert!(matches!(declared_body_length(&HeaderMap::new()), Ok(None)));
    }

    /// A 3xx is refused rather than followed, and the target it names is never contacted.
    ///
    /// This is a credential-boundary test, not a politeness one. The Helius credential travels as
    /// an `api-key` query parameter, and reqwest follows up to ten redirects with `Referer`
    /// enabled by default, so a followed redirect would hand the secret to whatever host the
    /// `Location` named. The refusal is asserted, and so is the stronger property: the redirect
    /// target receives no connection at all.
    #[test]
    fn a_redirect_is_refused_and_the_named_target_is_never_contacted() {
        let target = Loopback::start(declared_response("{}", ""));
        let redirect = format!(
            "HTTP/1.1 302 Found\r\nLocation: {}\r\nContent-Length: 0\r\n\r\n",
            target.endpoint()
        );
        let outcome = read_public(redirect.into_bytes(), 4_096);

        let frame = outcome
            .expect("a 3xx is a response, not a transport failure")
            .0;
        assert_eq!(
            frame.http_status,
            Some(302),
            "the redirect is retained as what it is rather than followed"
        );
        assert!(
            target.observed_no_request(),
            "the host named by Location must never be contacted"
        );
    }

    #[test]
    fn neither_client_can_be_constructed_with_a_ceiling_that_admits_nothing() {
        let loopback = Loopback::start(Vec::new());
        assert!(matches!(
            PublicSolanaHttpClient::loopback(loopback.endpoint(), 0),
            Err(HeliusError::ZeroCeiling)
        ));
        let key = credential_file();
        assert!(matches!(
            HeliusHttpClient::loopback(loopback.endpoint(), &key.1, 0),
            Err(HeliusError::ZeroCeiling)
        ));
    }

    /// A credential file whose directory outlives the returned handle.
    ///
    /// The loader refuses any credential readable by group or other, so the fixture sets
    /// owner-only permissions rather than relying on the process umask.
    fn credential_file() -> (tempfile::TempDir, crate::config::CredentialFile) {
        let directory = tempfile::tempdir().expect("credential directory");
        let path = directory.path().join("helius-key");
        std::fs::write(&path, "loopback-api-key").expect("write the credential");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
                .expect("owner-only credential permissions");
        }
        (directory, crate::config::CredentialFile(path))
    }

    /// The paid path carries the same bound as the free one, and that is the whole point of the
    /// change: the ceiling was harvested from a guardrail that only ever guarded the free path.
    #[test]
    fn the_authenticated_client_abandons_an_over_ceiling_body_the_same_way() {
        let chunk = "z".repeat(64);
        let chunks: Vec<&str> = std::iter::repeat_n(chunk.as_str(), 8).collect();
        let loopback = Loopback::start(chunked_response(&chunks, "", true));
        let key = credential_file();
        let client = HeliusHttpClient::loopback(loopback.endpoint(), &key.1, 256)
            .expect("bind the loopback authenticated client");
        assert_eq!(client.maximum_response_bytes(), 256);
        let error = runtime()
            .block_on(client.request(&read_request(), UnixMillis(1_000), 1))
            .expect_err("an accumulated body over the ceiling");
        assert!(!loopback.request().is_empty());
        assert!(
            matches!(error, HeliusError::BodyOverCeiling { ceiling: 256 }),
            "expected an accumulated-body refusal, got {error:?}"
        );
    }

    /// The authenticated request really does carry the credential, so the refusal above is a
    /// refusal of the authenticated shape rather than of an unauthenticated one.
    #[test]
    fn the_authenticated_request_carries_its_credential_in_the_query_and_the_error_never_does() {
        let body = body_of_exact_length(64);
        let loopback = Loopback::start(declared_response(&body, ""));
        let key = credential_file();
        let client = HeliusHttpClient::loopback(loopback.endpoint(), &key.1, 256)
            .expect("bind the loopback authenticated client");
        let (frame, _) = runtime()
            .block_on(client.request(&read_request(), UnixMillis(1_000), 1))
            .expect("a body under the ceiling");
        assert_eq!(frame.body.as_ref(), body.as_bytes());
        let request = String::from_utf8_lossy(&loopback.request()).into_owned();
        assert!(
            request.contains("api-key=loopback-api-key"),
            "the authenticated request must carry its credential"
        );
    }

    /// Every refusal is formatted in both `Display` and `Debug` and checked for a locator.
    ///
    /// This is the property the whole error type exists for: `reqwest::Error`'s own `Display`
    /// prints the request URL, and on the authenticated path that URL carries the API key.
    #[test]
    fn no_refusal_renders_a_locator_or_a_credential() {
        let errors = [
            HeliusError::ZeroCeiling,
            HeliusError::Transport,
            HeliusError::ResponseBody,
            HeliusError::MalformedDeclaredLength,
            HeliusError::DeclaredLengthOverCeiling {
                declared: 1,
                ceiling: 2,
            },
            HeliusError::DeclaredLengthMismatch {
                declared: 1,
                delivered: 2,
            },
            HeliusError::BodyOverCeiling { ceiling: 2 },
        ];
        for error in &errors {
            for rendered in [format!("{error}"), format!("{error:?}")] {
                let lowered = rendered.to_ascii_lowercase();
                for forbidden in [
                    "http://",
                    "https://",
                    "127.0.0.1",
                    "helius-rpc.com",
                    "solana.com",
                    "api-key",
                    "jsonrpc",
                ] {
                    assert!(
                        !lowered.contains(forbidden),
                        "{rendered:?} renders {forbidden:?}"
                    );
                }
            }
        }
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
