//! The one fixed, credential-free C1 request path.
//!
//! This module can perform exactly one shape of network operation: an HTTPS POST of a caller-
//! supplied JSON-RPC body to one compiled-in endpoint, reading back at most a compiled-in number
//! of response bytes. It exposes no generic executor, no callback, no endpoint parameter, no
//! method parameter, and no reusable permit. [`C1Transport::execute_once`] takes `self` by value,
//! so a built transport can be spent once and then no longer exists.
//!
//! # What is fixed and where it came from
//!
//! [`C1_ENDPOINT_URL`] is the public mainnet endpoint named by the official Solana cluster page,
//! re-verified 2026-08-19. That page also states that the public endpoints "are not intended for
//! production applications" and publishes a rate limit of 100 requests per 10 s per IP. Older
//! design notes and this repository's `solana:mainnet-beta` *cluster* identifiers name
//! `api.mainnet-beta.solana.com`; that is an alias of the same service — both names resolved to
//! 74.63.229.125 when this was checked on 2026-08-19 — so the two are not a discrepancy and the
//! compiled-in host is the one the cluster page publishes. The request carries no credential,
//! cookie, or session of any kind.
//!
//! # What the client hardening is, and what of it is observed
//!
//! The client is built with redirects disabled, an explicit never-retry policy, proxy inheritance
//! disabled, connection pooling disabled, HTTP/1 only, HTTPS only on the public path, and a strict
//! whole-request deadline. Those are not all the same kind of claim, and this module does not
//! pretend otherwise:
//!
//! * **Observed.** Redirects are refused rather than followed, the whole-request deadline expires
//!   as a refusal, and a plaintext scheme is refused before a socket opens. Each has a test that
//!   fails if the corresponding builder call is removed.
//! * **Compiled in, and already the default here.** `retry(reqwest::retry::never())` cannot be
//!   distinguished from the default policy in this build: this crate takes `reqwest` with
//!   `default-features = false`, so neither `http2` nor `http3` is compiled, and the default
//!   protocol-NACK classifier then classifies nothing as retryable. The call is kept so a future
//!   feature change cannot quietly enable retries, not because a test can see it work.
//! * **Compiled in, and not observable in-process.** `no_proxy()` only differs from the default
//!   when the process environment names a proxy, and setting an environment variable is `unsafe`
//!   under this edition, which this crate forbids. `pool_max_idle_per_host(0)` cannot differ
//!   either: [`C1Transport::execute_once`] takes `self` by value, so a client performs exactly one
//!   request and is then dropped, and there is never a second request that could reuse a
//!   connection. The stronger property — one request per transport, ever — is enforced by the type
//!   system rather than by the pool setting, and *is* observed: a second request necessarily opens
//!   a second connection, which the loopback listener records. `http1_only()` and `referer(false)`
//!   are in the same class: a cleartext loopback listener negotiates no ALPN, so HTTP/1 is what a
//!   test would see either way, and a referer can only be attached across a redirect this path
//!   never follows, and `connect_timeout` is subsumed by the whole-request `timeout` a loopback
//!   listener always answers inside.
//!
//! # Bounding, and what "bounded" means here
//!
//! The response entity body is read incrementally and abandoned the moment the accumulated length
//! *would* pass the admitted ceiling; the body is never read to completion first. The ceiling
//! itself is [`joshi_sources::PUBLIC_SOLANA_C1_MAX_RESPONSE_BYTES`], the single source of truth
//! that the supervisor's physical-size derivation is also computed from. A declared body length is
//! compared against that ceiling before a single body byte is read, against the accumulated length
//! while the body streams, and against the delivered length once the stream ends. Both
//! disagreement directions are reachable and tested: a response that declares a length *and* sends
//! a chunked body keeps both framings in the head, and the chunked body may then over-deliver
//! against the declaration mid-stream or terminate under it.
//!
//! Response headers are reduced to the four-name, 256-byte allowlist that
//! [`joshi_sources::public_solana_c1_safe_headers_are_bounded`] defines, before any
//! [`RawSourceFrame`] can be built from them. That reduction is load bearing rather than cosmetic:
//! the supervisor's physical bound assumes it, and unfiltered response headers were measured to
//! break every stage of that bound including the physical segment.
//!
//! # Clocks
//!
//! Elapsed time is derived from a monotonic [`Instant`] pair and from nothing else. This module
//! never reads a wall clock: the wall reading is supplied once by the caller, which is the same
//! reading its journal record carries, and the returned receipt instant is that reading advanced
//! by the monotonic elapsed. A wall clock that jumps between the two monotonic readings therefore
//! cannot change the measured elapsed time, because no second wall reading is ever taken.
//!
//! # Errors carry no locator
//!
//! Every [`C1TransportError`] variant renders a fixed message plus, at most, a status code or a
//! byte count. No variant retains a URL, host, request body, response body, or header value, and
//! no `reqwest::Error` is stored or rendered — `reqwest`'s own `Display` prints the request URL,
//! so its errors are classified into these variants and then dropped.
//!
//! The ceiling for every artifact produced here is [`crate::AUTHORITY_CEILING`].

use std::{
    collections::BTreeMap,
    time::{Duration, Instant},
};

use joshi_sources::{
    ContentType, FrameDirection, RawSourceFrame, SafeHeader, SourceId, StreamClass, Transport,
    UnixMillis, public_solana_c1_safe_headers_are_bounded,
};
use reqwest::header::{
    ACCEPT, ACCEPT_ENCODING, CONTENT_LENGTH, CONTENT_TYPE, HeaderMap, HeaderValue, USER_AGENT,
};
use sha2::{Digest as _, Sha256};
use thiserror::Error;

/// The one compiled-in C1 endpoint: the official public Solana mainnet JSON-RPC endpoint.
///
/// It is credential-free and public. Nothing in this crate can point a C1 request anywhere else.
/// `api.mainnet-beta.solana.com`, which this repository's `solana:mainnet-beta` cluster
/// identifiers name, is an alias of the same service rather than a different host; this constant
/// stays on the name the official cluster page publishes.
pub const C1_ENDPOINT_URL: &str = "https://api.mainnet.solana.com";

/// The one admitted response status. Anything else is a refusal, not a retry.
pub const C1_ADMITTED_STATUS: u16 = 200;

/// The one admitted request and response media type.
pub const C1_MEDIA_TYPE: &str = "application/json";

/// The fixed transfer coding requested. C1 compiles in no decompressor, so it asks for none.
pub const C1_ACCEPT_ENCODING: &str = "identity";

/// The fixed product token sent with the single request. It carries no installation, run, wallet,
/// or process identity, so it cannot become a covert channel or a correlation handle.
pub const C1_USER_AGENT: &str = "joshi-c1/1";

/// The four response header names retained, matched after ASCII lowercasing.
///
/// This is the same allowlist [`joshi_sources::public_solana_c1_safe_headers_are_bounded`]
/// enforces. It is restated here because a filter and a check are different jobs: this list says
/// what is kept, and that function is then asked whether what was kept is within the bound. The
/// unit test `retained_header_allowlist_matches_the_shared_bound` pins the two together by
/// building a frame from every name in this list and asserting the shared check admits it.
const RETAINED_HEADER_NAMES: [&str; 4] = [
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
];

/// Longest retained header value, in bytes. It matches the shared bound's own value limit.
const MAX_RETAINED_HEADER_VALUE_BYTES: usize = 256;

/// One finished C1 response, already bounded, status-checked, and header-reduced.
///
/// Every field is an observation about the one request that produced it. None of it is evidence,
/// coverage, or a finality fact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct C1RawResponse {
    /// The observed response status. It is always [`C1_ADMITTED_STATUS`], because any other status
    /// is refused; it is carried rather than assumed so the frame states what was seen.
    pub http_status: u16,
    /// The retained response headers, reduced to the bounded allowlist and sorted by name.
    pub safe_headers: Vec<SafeHeader>,
    /// The exact response entity body bytes, never longer than the admitted ceiling.
    pub body: Vec<u8>,
    /// Elapsed wall-free duration of the single request, from the monotonic pair only.
    pub elapsed_ms: u64,
    /// The caller's wall reading advanced by [`Self::elapsed_ms`].
    ///
    /// This is a derived receipt instant, not a second wall reading: no wall clock is consulted
    /// after the request starts, so this is exactly "the start reading plus the monotonic elapsed"
    /// and is a lower bound on the instant the bytes were actually in hand.
    pub received_at: UnixMillis,
}

impl C1RawResponse {
    /// Build the exact bounded C1 frame envelope around this response.
    ///
    /// Every envelope field except the status, headers, body, and receipt instant is fixed: this
    /// path performs exactly one inbound HTTP JSON backfill frame on one connection, so the
    /// connection epoch and sequence are both 1. [`joshi_sources::read_public_solana_c1_frame`]
    /// refuses any other envelope.
    #[must_use]
    pub fn to_frame(&self) -> RawSourceFrame {
        RawSourceFrame {
            contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
            source: SourceId::SolanaPublicHttp,
            transport: Transport::Http,
            stream_class: StreamClass::Backfill,
            direction: FrameDirection::Inbound,
            content_type: ContentType::Json,
            received_at: self.received_at,
            connection_epoch: 1,
            sequence: 1,
            http_status: Some(self.http_status),
            safe_headers: self.safe_headers.clone(),
            body: bytes::Bytes::copy_from_slice(&self.body),
        }
    }
}

/// Refusals from the one fixed C1 request path.
///
/// No variant carries a URL, host, request body, response body, header value, or credential. The
/// unit test `no_error_variant_renders_an_endpoint_shaped_string` formats every variant, in both
/// `Display` and `Debug`, and refuses any rendering containing an endpoint-shaped substring.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum C1TransportError {
    /// The admitted body ceiling was zero, so no response could ever be accepted.
    #[error("the C1 response ceiling admits zero bytes and can never carry a page")]
    ZeroCeiling,
    /// The deadline was zero or unrepresentable.
    #[error("the C1 request deadline is zero or outside the representable range")]
    InvalidDeadline,
    /// The request body was empty or over the registered request bound.
    #[error("the C1 request body is empty or over the registered request bound")]
    InvalidRequestBody,
    /// The single-threaded async executor backing the one request could not be created.
    #[error("the single-request C1 executor could not be created")]
    ExecutorUnavailable,
    /// The fixed client could not be constructed (TLS backend, resolver, or configuration).
    #[error("the fixed C1 client could not be built")]
    ClientBuild,
    /// The fixed request could not be constructed from the compiled-in endpoint and method.
    #[error("the fixed C1 request could not be built")]
    RequestBuild,
    /// The connection could not be established.
    #[error("the C1 connection could not be established")]
    Connect,
    /// The strict whole-request deadline expired.
    #[error("the C1 request passed its strict deadline")]
    Deadline,
    /// The request failed before any response status was observed.
    #[error("the C1 request failed before a response was observed")]
    RequestFailed,
    /// The response body stream failed part way through.
    #[error("the C1 response body stream failed before it completed")]
    BodyStream,
    /// A redirect was offered and refused. C1 follows none.
    #[error("the C1 endpoint offered a redirect, which this path never follows")]
    RedirectRefused,
    /// The response status was not the single admitted one.
    #[error("the C1 endpoint answered with response status {status}, which is not admitted")]
    UnexpectedStatus {
        /// The observed status code.
        status: u16,
    },
    /// The response declared no media type at all.
    #[error("the C1 response declared no media type")]
    MissingMediaType,
    /// The response declared a media type other than the admitted one.
    #[error("the C1 response declared a media type other than the admitted one")]
    UnexpectedMediaType,
    /// The declared body length was present but not a plain decimal byte count.
    ///
    /// **Not reachable through a live response.** `hyper` refuses a response whose
    /// `Content-Length` is not a decimal byte count while it is decoding the head, so
    /// `execute_once` never sees such a header and returns a stream-level refusal instead. The
    /// guard is kept because it is what decides, and it is exercised directly as the function it
    /// is by `a_declared_length_that_is_not_a_plain_byte_count_is_refused`; deleting the branch
    /// fails that test. It becomes live if the head decoder is ever replaced by one that passes an
    /// unparsed declaration through.
    #[error("the C1 response declared a body length that is not a plain byte count")]
    MalformedDeclaredLength,
    /// The declared body length was already over the admitted ceiling, before any body was read.
    #[error(
        "the C1 response declared {declared} body bytes, over the {ceiling} byte admitted ceiling"
    )]
    DeclaredLengthOverCeiling {
        /// The length the response declared.
        declared: u64,
        /// The admitted ceiling.
        ceiling: u64,
    },
    /// The declared body length disagreed with the bytes actually delivered.
    #[error(
        "the C1 response declared {declared} body bytes and delivered {delivered}; the two must agree"
    )]
    DeclaredLengthMismatch {
        /// The length the response declared.
        declared: u64,
        /// The number of bytes actually delivered.
        delivered: u64,
    },
    /// The body passed the admitted ceiling while streaming, and was abandoned there.
    #[error("the C1 response body passed the {ceiling} byte admitted ceiling and was abandoned")]
    BodyOverCeiling {
        /// The admitted ceiling.
        ceiling: u64,
    },
    /// The reduced header set still failed the shared bounded-header check.
    ///
    /// **Not reachable while the filter and the shared bound agree**, which is the whole point of
    /// keeping both: [`RETAINED_HEADER_NAMES`] is the shared allowlist, a `BTreeMap` keyed by name
    /// admits each name once, and a value is dropped unless it is valid UTF-8, at most
    /// [`MAX_RETAINED_HEADER_VALUE_BYTES`] long, and free of control characters — exactly the four
    /// conditions `joshi_sources::public_solana_c1_safe_headers_are_bounded` checks. Every set the
    /// reduction can produce is therefore admitted. This is the fail-safe for the moment those
    /// two drift apart, and `every_reduction_the_filter_can_produce_is_within_the_shared_bound`
    /// is what fails first if they do.
    #[error("the reduced C1 response header set is not within the shared bounded allowance")]
    HeaderBudget,
    /// The elapsed or receipt instant could not be represented.
    #[error("the C1 request duration or receipt instant is outside the representable range")]
    ClockRange,
}

/// One spendable, fixed, credential-free C1 request.
///
/// The endpoint and method are compiled in; nothing about them is a constructor argument on the
/// public path. The value is spent by [`C1Transport::execute_once`], which takes it by value.
pub struct C1Transport {
    client: reqwest::Client,
    executor: tokio::runtime::Runtime,
    endpoint: String,
    maximum_response_bytes: u64,
    deadline: Duration,
}

/// `Debug` is written by hand rather than derived because the derive rendered the bound endpoint.
///
/// Every error on this path is careful to carry no URL, and a formatted transport would have
/// reintroduced one through the back door: a caller who logged the value it holds would emit the
/// host into whatever the log reaches. The bounds are safe to show and are the only useful part.
impl std::fmt::Debug for C1Transport {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("C1Transport")
            .field("maximum_response_bytes", &self.maximum_response_bytes)
            .field("deadline_ms", &self.deadline.as_millis())
            .finish_non_exhaustive()
    }
}

impl C1Transport {
    /// Build the one fixed C1 request against the compiled-in public endpoint.
    ///
    /// There is deliberately no endpoint, method, header, credential, or executor argument. The
    /// only two knobs are the admitted response ceiling and the strict deadline, and both only
    /// ever narrow what this path will accept.
    ///
    /// # Errors
    ///
    /// Refuses a zero ceiling, a zero deadline, and a failure to create the executor or the fixed
    /// client.
    pub fn open(maximum_response_bytes: u64, deadline_ms: u64) -> Result<Self, C1TransportError> {
        Self::bind(
            C1_ENDPOINT_URL.to_owned(),
            true,
            maximum_response_bytes,
            deadline_ms,
        )
    }

    /// Bind a private loopback base URL so hostile-response behaviour can be exercised offline.
    ///
    /// This exists only under `cfg(test)`, so it is compiled into this crate's own unit tests and
    /// into nothing else: no integration test, no sibling crate, and no external consumer can name
    /// it. It relaxes exactly one guard, the HTTPS-only requirement, because a loopback listener
    /// speaking scripted plaintext bytes is what makes a lying framing testable at all.
    #[cfg(test)]
    pub(crate) fn loopback(
        base_url: String,
        maximum_response_bytes: u64,
        deadline_ms: u64,
    ) -> Result<Self, C1TransportError> {
        Self::bind(base_url, false, maximum_response_bytes, deadline_ms)
    }

    fn bind(
        endpoint: String,
        https_only: bool,
        maximum_response_bytes: u64,
        deadline_ms: u64,
    ) -> Result<Self, C1TransportError> {
        if maximum_response_bytes == 0 {
            return Err(C1TransportError::ZeroCeiling);
        }
        if deadline_ms == 0 {
            return Err(C1TransportError::InvalidDeadline);
        }
        let deadline = Duration::from_millis(deadline_ms);
        let mut headers = HeaderMap::new();
        headers.insert(
            CONTENT_TYPE,
            HeaderValue::from_static(strip_lifetime(C1_MEDIA_TYPE)),
        );
        headers.insert(
            ACCEPT,
            HeaderValue::from_static(strip_lifetime(C1_MEDIA_TYPE)),
        );
        headers.insert(
            ACCEPT_ENCODING,
            HeaderValue::from_static(strip_lifetime(C1_ACCEPT_ENCODING)),
        );
        headers.insert(
            USER_AGENT,
            HeaderValue::from_static(strip_lifetime(C1_USER_AGENT)),
        );
        let client = reqwest::Client::builder()
            // Nothing about this request may be repeated, redirected, proxied, or pooled.
            .redirect(reqwest::redirect::Policy::none())
            .retry(reqwest::retry::never())
            .no_proxy()
            .pool_max_idle_per_host(0)
            .referer(false)
            .http1_only()
            .https_only(https_only)
            .connect_timeout(deadline)
            .timeout(deadline)
            .default_headers(headers)
            .build()
            .map_err(|_| C1TransportError::ClientBuild)?;
        let executor = tokio::runtime::Builder::new_current_thread()
            .enable_io()
            .enable_time()
            .build()
            .map_err(|_| C1TransportError::ExecutorUnavailable)?;
        Ok(Self {
            client,
            executor,
            endpoint,
            maximum_response_bytes,
            deadline,
        })
    }

    /// The SHA-256 of the endpoint string this transport will actually contact.
    ///
    /// The journal records this rather than the endpoint itself. It is read from the bound
    /// endpoint rather than from [`C1_ENDPOINT_URL`], so a record produced against a private
    /// loopback listener is visibly not a record of a public read.
    #[must_use]
    pub fn endpoint_digest(&self) -> String {
        sha256(self.endpoint.as_bytes())
    }

    /// The admitted response ceiling this transport will stop at, in bytes.
    #[must_use]
    pub const fn maximum_response_bytes(&self) -> u64 {
        self.maximum_response_bytes
    }

    /// The strict whole-request deadline, in milliseconds.
    #[must_use]
    pub fn deadline_ms(&self) -> u64 {
        u64::try_from(self.deadline.as_millis()).unwrap_or(u64::MAX)
    }

    /// Perform the single admitted request and consume this transport.
    ///
    /// `wall_started` is the caller's one wall reading, in the same clock domain its journal uses.
    /// It is never re-read: the returned receipt instant is this value advanced by the monotonic
    /// elapsed, so a wall clock that jumps mid-request changes neither the elapsed time nor the
    /// relationship between the two.
    ///
    /// The order of work is deliberate and is the boundedness argument. Status, media type, and
    /// declared length are all settled from the response head, before one body byte is read; the
    /// header set is reduced and checked next; only then does the body stream, and it is abandoned
    /// the moment the accumulated length would pass the ceiling.
    ///
    /// # Errors
    ///
    /// Refuses an empty or oversized request body, a connection failure, an expired deadline, a
    /// redirect, any status other than [`C1_ADMITTED_STATUS`], a missing or non-JSON media type, a
    /// malformed or oversized declared length, a declared length that disagrees with the delivered
    /// bytes, a body over the admitted ceiling, a header set outside the shared bounded allowance,
    /// and an unrepresentable duration.
    pub fn execute_once(
        self,
        request_body: &[u8],
        wall_started: UnixMillis,
    ) -> Result<C1RawResponse, C1TransportError> {
        if request_body.is_empty()
            || request_body.len() > joshi_sources::PUBLIC_SOLANA_C1_MAX_REQUEST_BYTES
        {
            return Err(C1TransportError::InvalidRequestBody);
        }
        let ceiling = self.maximum_response_bytes;
        let body = request_body.to_vec();
        let started = Instant::now();
        let outcome = self.executor.block_on(async {
            let response = self
                .client
                .post(&self.endpoint)
                .body(body)
                .send()
                .await
                .map_err(|error| classify_send(&error))?;
            let status = response.status().as_u16();
            if status != C1_ADMITTED_STATUS {
                return Err(if response.status().is_redirection() {
                    C1TransportError::RedirectRefused
                } else {
                    C1TransportError::UnexpectedStatus { status }
                });
            }
            admit_media_type(response.headers())?;
            let declared = declared_body_length(response.headers())?;
            if let Some(declared) = declared
                && declared > ceiling
            {
                return Err(C1TransportError::DeclaredLengthOverCeiling { declared, ceiling });
            }
            let safe_headers = retained_headers(response.headers());
            if !public_solana_c1_safe_headers_are_bounded(&safe_headers) {
                return Err(C1TransportError::HeaderBudget);
            }
            let body = stream_bounded_body(response, ceiling, declared).await?;
            Ok((status, safe_headers, body))
        });
        let elapsed = started.elapsed();
        let (http_status, safe_headers, body) = outcome?;
        let elapsed_ms =
            u64::try_from(elapsed.as_millis()).map_err(|_| C1TransportError::ClockRange)?;
        let received_at = advance_wall(wall_started, elapsed_ms)?;
        Ok(C1RawResponse {
            http_status,
            safe_headers,
            body,
            elapsed_ms,
            received_at,
        })
    }
}

/// Read the response entity body incrementally, abandoning it the moment it would pass the bound.
///
/// The accumulated length is compared *before* each chunk is appended, so no allocation ever holds
/// more than `ceiling` bytes and the connection is dropped mid-stream rather than drained. A
/// declared length narrows the bound further, and the delivered length is compared against it once
/// the stream ends.
async fn stream_bounded_body(
    mut response: reqwest::Response,
    ceiling: u64,
    declared: Option<u64>,
) -> Result<Vec<u8>, C1TransportError> {
    let capacity = usize::try_from(declared.unwrap_or(0).min(ceiling)).unwrap_or(0);
    let mut body: Vec<u8> = Vec::with_capacity(capacity);
    loop {
        let chunk = match response.chunk().await {
            Ok(Some(chunk)) => chunk,
            Ok(None) => break,
            Err(error) => return Err(classify_body(&error)),
        };
        let chunk_len = u64::try_from(chunk.len()).map_err(|_| C1TransportError::ClockRange)?;
        let accumulated = u64::try_from(body.len()).map_err(|_| C1TransportError::ClockRange)?;
        let projected = accumulated
            .checked_add(chunk_len)
            .ok_or(C1TransportError::BodyOverCeiling { ceiling })?;
        if projected > ceiling {
            return Err(C1TransportError::BodyOverCeiling { ceiling });
        }
        // A body that over-delivers against its own declared length is refused here rather than
        // accumulated. This is reachable: a response that sends both `Content-Length` and
        // `Transfer-Encoding: chunked` keeps both framings in the head, and the chunked decoder
        // then delivers whatever the chunks carry. A declaration alone still truncates, so the
        // over-delivery a plain `Content-Length` response writes past its declaration never
        // arrives; the two disagreeing framings are what makes this arm and the check after the
        // loop live, and both directions are pinned by the `a_chunked_body_*_declared_length_*`
        // tests.
        if let Some(declared) = declared
            && projected > declared
        {
            return Err(C1TransportError::DeclaredLengthMismatch {
                declared,
                delivered: projected,
            });
        }
        body.extend_from_slice(&chunk);
    }
    let delivered = u64::try_from(body.len()).map_err(|_| C1TransportError::ClockRange)?;
    if let Some(declared) = declared
        && declared != delivered
    {
        return Err(C1TransportError::DeclaredLengthMismatch {
            declared,
            delivered,
        });
    }
    Ok(body)
}

/// Require the response to declare exactly the admitted JSON media type.
fn admit_media_type(headers: &reqwest::header::HeaderMap) -> Result<(), C1TransportError> {
    let Some(value) = headers.get(CONTENT_TYPE) else {
        return Err(C1TransportError::MissingMediaType);
    };
    let Ok(value) = value.to_str() else {
        return Err(C1TransportError::UnexpectedMediaType);
    };
    let media_type = value
        .split(';')
        .next()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    if media_type == C1_MEDIA_TYPE {
        Ok(())
    } else {
        Err(C1TransportError::UnexpectedMediaType)
    }
}

/// Read the declared body length from the response head, if it declared one.
///
/// A missing declaration is allowed: a chunked response is legal and stays bounded by the ceiling.
/// A declaration that is not a plain decimal byte count is refused rather than ignored.
fn declared_body_length(
    headers: &reqwest::header::HeaderMap,
) -> Result<Option<u64>, C1TransportError> {
    let Some(value) = headers.get(CONTENT_LENGTH) else {
        return Ok(None);
    };
    let Ok(value) = value.to_str() else {
        return Err(C1TransportError::MalformedDeclaredLength);
    };
    let value = value.trim();
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(C1TransportError::MalformedDeclaredLength);
    }
    value
        .parse::<u64>()
        .map(Some)
        .map_err(|_| C1TransportError::MalformedDeclaredLength)
}

/// Reduce the response headers to the bounded C1 allowlist.
///
/// Only the four allowlisted names survive, at most once each, with a value that is valid UTF-8,
/// at most [`MAX_RETAINED_HEADER_VALUE_BYTES`] long, and free of control characters. A repeated or
/// unqualified value is dropped rather than refused: a header the endpoint controls must not be
/// able to deny the read, and dropping it keeps the retained set inside the bound the supervisor's
/// physical derivation assumes. The result is sorted by name so the retained set is deterministic.
fn retained_headers(headers: &reqwest::header::HeaderMap) -> Vec<SafeHeader> {
    let mut retained: BTreeMap<String, String> = BTreeMap::new();
    for (name, value) in headers {
        let name = name.as_str().to_ascii_lowercase();
        if !RETAINED_HEADER_NAMES.contains(&name.as_str()) || retained.contains_key(&name) {
            continue;
        }
        let Ok(value) = value.to_str() else {
            continue;
        };
        if value.len() > MAX_RETAINED_HEADER_VALUE_BYTES || value.chars().any(char::is_control) {
            continue;
        }
        retained.insert(name, value.to_owned());
    }
    retained
        .into_iter()
        .map(|(name, value)| SafeHeader { name, value })
        .collect()
}

/// Classify a send-phase `reqwest` failure without retaining or rendering it.
///
/// `reqwest::Error`'s own `Display` prints the request URL, so the error is inspected through its
/// predicates and then dropped. Ordering matters: a timeout is also a request error.
fn classify_send(error: &reqwest::Error) -> C1TransportError {
    if error.is_timeout() {
        C1TransportError::Deadline
    } else if error.is_connect() {
        C1TransportError::Connect
    } else if error.is_redirect() {
        C1TransportError::RedirectRefused
    } else if error.is_builder() {
        C1TransportError::RequestBuild
    } else {
        C1TransportError::RequestFailed
    }
}

/// Classify a body-phase `reqwest` failure without retaining or rendering it.
fn classify_body(error: &reqwest::Error) -> C1TransportError {
    if error.is_timeout() {
        C1TransportError::Deadline
    } else {
        C1TransportError::BodyStream
    }
}

/// Advance one wall reading by a monotonic elapsed duration.
fn advance_wall(started: UnixMillis, elapsed_ms: u64) -> Result<UnixMillis, C1TransportError> {
    let elapsed = i64::try_from(elapsed_ms).map_err(|_| C1TransportError::ClockRange)?;
    started
        .0
        .checked_add(elapsed)
        .map(UnixMillis)
        .ok_or(C1TransportError::ClockRange)
}

fn sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

/// Re-borrow a `&'static str` constant as `&'static str`.
///
/// `HeaderValue::from_static` requires a `'static` argument, and naming the constants through this
/// function keeps the fixed header values readable as constants at the call site rather than as
/// repeated string literals that could drift from the exported constants.
const fn strip_lifetime(value: &'static str) -> &'static str {
    value
}

/// Private loopback scaffolding shared by this crate's own C1 unit tests.
///
/// It is compiled only under `cfg(test)`, so no integration test, sibling crate, or external
/// consumer can reach it. Everything here binds 127.0.0.1 with an ephemeral port and never
/// resolves a name, which is what keeps every C1 test in this crate offline.
#[cfg(test)]
pub(crate) mod probe {
    use super::*;
    use joshi_sources::canonical_public_solana_c1_request;
    use std::{
        fmt::Write as _,
        io::{Read as _, Write as _},
        net::{SocketAddr, TcpListener, TcpStream},
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
            mpsc,
        },
        thread,
    };
    /// A wallet whose base58 decodes to exactly 32 bytes, reused from the activation fixtures.
    pub(crate) const WALLET: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";
    /// The strict deadline every loopback test runs under. Short, so a hang test stays quick.
    pub(crate) const DEADLINE_MS: u64 = 400;
    /// A fixed wall reading. Nothing in this module reads a wall clock, so tests supply one.
    pub(crate) const WALL: UnixMillis = UnixMillis(1_786_881_600_000);

    /// One scripted step a loopback listener performs after it has read the whole request.
    pub(crate) enum Step {
        Write(Vec<u8>),
        Sleep(Duration),
    }

    /// A private loopback listener that records *every* connection it is offered.
    ///
    /// It is plain `std::net`, on 127.0.0.1 with an ephemeral port, and it never resolves a name.
    /// No test in this module can reach a public endpoint: the only URL any of them binds is this
    /// listener's own address.
    ///
    /// The accept loop is the load-bearing part. Every C1 transport builds its own `reqwest`
    /// client and spends it on one request, so a *second* request necessarily arrives on a second
    /// connection. A listener that accepted once and exited would silently leave that second
    /// connection in the kernel backlog, and [`Loopback::assert_no_further_request`] would then be
    /// unconditionally true — the no-second-request property, which is the whole point of the C1
    /// path, would have no test that could refute it. Accepting in a loop and recording each
    /// request is what makes that assertion real; `the_loopback_records_every_connection_so_a_
    /// second_request_is_observable` pins the harness itself.
    ///
    /// Only the first connection is scripted. A later one is read, recorded, and closed, which is
    /// all a request that must never have issued deserves.
    pub(crate) struct Loopback {
        addr: SocketAddr,
        requests: mpsc::Receiver<Vec<u8>>,
        stopping: Arc<AtomicBool>,
    }

    impl Loopback {
        pub(crate) fn start(script: Vec<Step>) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind a loopback listener");
            let addr = listener.local_addr().expect("loopback address");
            let (sender, requests) = mpsc::channel();
            let stopping = Arc::new(AtomicBool::new(false));
            let signal = Arc::clone(&stopping);
            thread::spawn(move || {
                let mut script = Some(script);
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
                    for step in script.take().unwrap_or_default() {
                        match step {
                            Step::Write(bytes) => {
                                // A refused response is expected to break the pipe part way
                                // through.
                                let _ = stream.write_all(&bytes);
                                let _ = stream.flush();
                            }
                            Step::Sleep(duration) => thread::sleep(duration),
                        }
                    }
                }
            });
            Self {
                addr,
                requests,
                stopping,
            }
        }

        pub(crate) fn base_url(&self) -> String {
            format!("http://{}", self.addr)
        }

        pub(crate) fn transport(&self, ceiling: u64) -> C1Transport {
            C1Transport::loopback(self.base_url(), ceiling, DEADLINE_MS)
                .expect("bind the loopback transport")
        }

        pub(crate) fn request(&self) -> Vec<u8> {
            self.requests
                .recv_timeout(Duration::from_secs(5))
                .expect("the loopback listener observed one request")
        }

        /// Every request observed so far, after a short grace for one still in flight.
        pub(crate) fn observed_requests(&self) -> Vec<Vec<u8>> {
            let mut seen = Vec::new();
            while let Ok(request) = self.requests.recv_timeout(Duration::from_millis(200)) {
                seen.push(request);
            }
            seen
        }

        /// Assert that exactly one request reached the listener and no other followed.
        ///
        /// The listener accepts in a loop, so a second request — which necessarily opens a second
        /// connection — is recorded rather than left unaccepted. This drains the one expected
        /// request and then proves the channel stays empty.
        pub(crate) fn assert_exactly_one_request(&self) {
            let _ = self.request();
            self.assert_no_further_request();
        }

        pub(crate) fn assert_no_further_request(&self) {
            assert!(
                self.requests
                    .recv_timeout(Duration::from_millis(200))
                    .is_err(),
                "the loopback listener observed a request it must never have seen"
            );
        }
    }

    /// Wake the accept loop so the listener thread ends with its test rather than outliving it.
    ///
    /// The flag is read immediately after `accept` returns, so the connection this opens is never
    /// mistaken for a request: the thread sees the flag and exits before reading a byte.
    impl Drop for Loopback {
        fn drop(&mut self) {
            self.stopping.store(true, Ordering::SeqCst);
            let _ = TcpStream::connect_timeout(&self.addr, Duration::from_millis(200));
        }
    }

    /// Read one whole HTTP/1 request: head to the blank line, then exactly its declared body.
    pub(crate) fn read_request(stream: &mut TcpStream) -> Vec<u8> {
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

    pub(crate) fn request_line(request: &[u8]) -> String {
        String::from_utf8_lossy(request)
            .lines()
            .next()
            .unwrap_or_default()
            .to_owned()
    }

    /// The request's header names and values, names lowercased, in the order they were sent.
    pub(crate) fn request_headers(request: &[u8]) -> Vec<(String, String)> {
        String::from_utf8_lossy(request)
            .split("\r\n\r\n")
            .next()
            .unwrap_or_default()
            .lines()
            .skip(1)
            .filter_map(|line| {
                line.split_once(':').map(|(name, value)| {
                    (name.trim().to_ascii_lowercase(), value.trim().to_owned())
                })
            })
            .collect()
    }

    pub(crate) fn request_body(request: &[u8]) -> Vec<u8> {
        let text = String::from_utf8_lossy(request).into_owned();
        let Some(offset) = text.find("\r\n\r\n") else {
            return Vec::new();
        };
        request[offset + 4..].to_vec()
    }

    pub(crate) fn header_value(request: &[u8], name: &str) -> Option<String> {
        request_headers(request)
            .into_iter()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value)
    }

    pub(crate) fn canonical_body() -> Vec<u8> {
        canonical_public_solana_c1_request(WALLET, 10)
            .expect("canonical C1 request body")
            .body
    }

    /// One well-formed empty page, as raw HTTP/1 response bytes with a declared length.
    pub(crate) fn ok_page_response(body: &str, extra_headers: &str) -> Vec<u8> {
        format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n{extra_headers}\r\n{body}",
        body.len()
    )
    .into_bytes()
    }

    pub(crate) fn chunked_response(
        chunks: &[&str],
        extra_headers: &str,
        terminate: bool,
    ) -> Vec<u8> {
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

    pub(crate) const EMPTY_PAGE: &str = r#"{"jsonrpc":"2.0","id":1,"result":[]}"#;
}

#[cfg(test)]
mod tests {
    use super::probe::*;
    use super::*;
    // The one ingress ceiling in the tree. `joshi-sources` owns the number and
    // `c1::physical_size` widens it once; this transport restates it nowhere.
    use crate::c1::physical_size::C1_MAX_RESPONSE_BODY_BYTES;
    use joshi_sources::{
        PUBLIC_SOLANA_C1_MAX_REQUEST_BYTES, PublicSolanaC1Outcome, read_public_solana_c1_frame,
    };
    use std::{fmt::Write as _, net::TcpListener};

    #[test]
    fn the_compiled_in_endpoint_is_the_public_mainnet_host_the_cluster_page_names() {
        assert_eq!(C1_ENDPOINT_URL, "https://api.mainnet.solana.com");
        assert!(
            C1_ENDPOINT_URL.starts_with("https://"),
            "the public path is HTTPS only"
        );
        assert!(
            !C1_ENDPOINT_URL.contains("mainnet-beta"),
            "the alias is a real alias of the same service, but this constant stays on the name \
             the official cluster page publishes"
        );
        let transport = C1Transport::open(C1_MAX_RESPONSE_BODY_BYTES, DEADLINE_MS)
            .expect("build the fixed public transport");
        assert_eq!(
            transport.endpoint_digest(),
            sha256(C1_ENDPOINT_URL.as_bytes()),
            "the journal records the digest of the endpoint actually bound"
        );
        assert_eq!(
            transport.maximum_response_bytes(),
            C1_MAX_RESPONSE_BODY_BYTES
        );
        assert_eq!(transport.deadline_ms(), DEADLINE_MS);
    }

    #[test]
    fn zero_ceiling_and_zero_deadline_are_refused_before_a_client_exists() {
        assert_eq!(
            C1Transport::open(0, DEADLINE_MS).unwrap_err(),
            C1TransportError::ZeroCeiling
        );
        assert_eq!(
            C1Transport::open(C1_MAX_RESPONSE_BODY_BYTES, 0).unwrap_err(),
            C1TransportError::InvalidDeadline
        );
    }

    #[test]
    fn an_empty_or_oversized_request_body_is_refused_before_a_socket_opens() {
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        assert_eq!(
            server
                .transport(C1_MAX_RESPONSE_BODY_BYTES)
                .execute_once(b"", WALL)
                .unwrap_err(),
            C1TransportError::InvalidRequestBody
        );
        let oversized = vec![b'x'; PUBLIC_SOLANA_C1_MAX_REQUEST_BYTES + 1];
        assert_eq!(
            server
                .transport(C1_MAX_RESPONSE_BODY_BYTES)
                .execute_once(&oversized, WALL)
                .unwrap_err(),
            C1TransportError::InvalidRequestBody
        );
        server.assert_no_further_request();
    }

    #[test]
    fn the_emitted_request_is_exactly_one_fixed_post_with_the_canonical_body() {
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        let body = canonical_body();
        let response = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&body, WALL)
            .expect("one successful bounded page");
        assert_eq!(response.http_status, C1_ADMITTED_STATUS);

        let request = server.request();
        assert_eq!(request_line(&request), "POST / HTTP/1.1");
        let mut names: Vec<String> = request_headers(&request)
            .into_iter()
            .map(|(name, _)| name)
            .collect();
        names.sort();
        assert_eq!(
            names,
            vec![
                "accept".to_owned(),
                "accept-encoding".to_owned(),
                "content-length".to_owned(),
                "content-type".to_owned(),
                "host".to_owned(),
                "user-agent".to_owned(),
            ],
            "the request carries exactly the fixed safe header set; `host` and `content-length` \
             are framing this path does not choose"
        );
        assert_eq!(
            header_value(&request, "accept").as_deref(),
            Some(C1_MEDIA_TYPE)
        );
        assert_eq!(
            header_value(&request, "content-type").as_deref(),
            Some(C1_MEDIA_TYPE)
        );
        assert_eq!(
            header_value(&request, "accept-encoding").as_deref(),
            Some(C1_ACCEPT_ENCODING)
        );
        assert_eq!(
            header_value(&request, "user-agent").as_deref(),
            Some(C1_USER_AGENT)
        );
        assert_eq!(
            header_value(&request, "content-length").as_deref(),
            Some(body.len().to_string().as_str())
        );
        assert_eq!(request_body(&request), body);
        assert_eq!(
            request_body(&request),
            br#"{"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":["BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh",{"commitment":"finalized","limit":10}]}"#
                .to_vec(),
            "the exact request byte string is pinned here, not merely round-tripped"
        );
    }

    /// Pin the harness the no-second-request property depends on.
    ///
    /// Every assertion elsewhere that "exactly one request" or "no further request" happened is
    /// only worth something if the listener can actually see a second one. Each transport spends
    /// its own client on one request, so a second request must open a second connection; this
    /// proves the accept loop records it. If the listener ever goes back to accepting once,
    /// `assert_no_further_request` becomes unconditionally true and this test is what fails.
    #[test]
    fn the_loopback_records_every_connection_so_a_second_request_is_observable() {
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .expect("the first request is answered");
        // The second transport is a second client, so this is a second connection by construction.
        let _ = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL);
        let observed = server.observed_requests();
        assert_eq!(
            observed.len(),
            2,
            "the listener must observe both connections; every one-request assertion in this \
             crate is vacuous otherwise"
        );
        for request in &observed {
            assert_eq!(request_body(request), canonical_body());
        }
    }

    #[test]
    fn a_successful_page_yields_a_frame_the_shared_wire_contract_admits() {
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        let response = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .expect("one successful bounded page");
        assert_eq!(response.body, EMPTY_PAGE.as_bytes());
        let frame = response.to_frame();
        assert!(matches!(
            read_public_solana_c1_frame(&frame, 10),
            Ok(PublicSolanaC1Outcome::Page(page)) if page.rows.is_empty()
        ));
    }

    #[test]
    fn only_the_four_allowlisted_response_headers_are_retained() {
        let extra = concat!(
            "Retry-After: 3\r\n",
            "X-RateLimit-Limit: 100\r\n",
            "X-RateLimit-Remaining: 99\r\n",
            "X-RateLimit-Reset: 7\r\n",
            "Set-Cookie: session=secret\r\n",
            "Server: nginx\r\n",
            "X-Trace-Id: 0123456789abcdef\r\n",
        );
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, extra))]);
        let response = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .expect("one successful bounded page");
        assert_eq!(
            response
                .safe_headers
                .iter()
                .map(|header| (header.name.as_str(), header.value.as_str()))
                .collect::<Vec<_>>(),
            vec![
                ("retry-after", "3"),
                ("x-ratelimit-limit", "100"),
                ("x-ratelimit-remaining", "99"),
                ("x-ratelimit-reset", "7"),
            ],
            "the reduced set is the allowlist, sorted, and carries no cookie or trace header"
        );
        assert!(public_solana_c1_safe_headers_are_bounded(
            &response.safe_headers
        ));
    }

    #[test]
    fn a_repeated_allowlisted_header_is_retained_once_and_an_oversized_value_is_dropped() {
        let long = "9".repeat(MAX_RETAINED_HEADER_VALUE_BYTES + 1);
        let extra = format!(
            "Retry-After: 3\r\nRetry-After: 4\r\nX-RateLimit-Limit: {long}\r\nX-RateLimit-Reset: 7\r\n"
        );
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, &extra))]);
        let response = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .expect("one successful bounded page");
        assert_eq!(
            response
                .safe_headers
                .iter()
                .map(|header| (header.name.as_str(), header.value.as_str()))
                .collect::<Vec<_>>(),
            vec![("retry-after", "3"), ("x-ratelimit-reset", "7")],
            "a repeat keeps the first value only, and an over-long value is dropped entirely"
        );
        assert!(public_solana_c1_safe_headers_are_bounded(
            &response.safe_headers
        ));
    }

    #[test]
    fn many_unfiltered_headers_still_reduce_to_a_bounded_retained_set() {
        let mut extra = String::new();
        for index in 0..64 {
            let _ = write!(extra, "X-Pad-{index}: {}\r\n", "p".repeat(64));
        }
        extra.push_str("Retry-After: 1\r\n");
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, &extra))]);
        let response = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .expect("one successful bounded page");
        assert_eq!(response.safe_headers.len(), 1);
        // A far larger header block is refused by the response parser before this filter ever
        // sees it, so 64 is chosen to stay inside that limit and still exercise the reduction.
        assert!(public_solana_c1_safe_headers_are_bounded(
            &response.safe_headers
        ));
    }

    #[test]
    fn retained_header_allowlist_matches_the_shared_bound() {
        let retained: Vec<SafeHeader> = RETAINED_HEADER_NAMES
            .iter()
            .map(|name| SafeHeader {
                name: (*name).to_owned(),
                value: "1".to_owned(),
            })
            .collect();
        assert!(
            public_solana_c1_safe_headers_are_bounded(&retained),
            "every name this module keeps must be a name the shared bound admits"
        );
    }

    /// The HTTPS-only guard is what keeps the compiled-in public path off cleartext.
    ///
    /// `C1Transport::open` always binds an `https` URL, so the guard cannot be exercised through
    /// it; `bind` is called directly with the same `https_only` argument `open` passes and a
    /// plaintext loopback URL. The listener must never see the request at all.
    #[test]
    fn a_plaintext_endpoint_is_refused_by_the_https_only_guard_before_a_socket_opens() {
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        let error = C1Transport::bind(
            server.base_url(),
            true,
            C1_MAX_RESPONSE_BODY_BYTES,
            DEADLINE_MS,
        )
        .expect("binding a transport never inspects the scheme")
        .execute_once(&canonical_body(), WALL)
        .unwrap_err();
        assert_eq!(
            error,
            C1TransportError::RequestBuild,
            "a cleartext scheme is refused while the request is being built"
        );
        assert_no_locator(&error);
        server.assert_no_further_request();
    }

    #[test]
    fn a_redirect_is_refused_and_never_followed() {
        let redirect = concat!(
            "HTTP/1.1 302 Found\r\n",
            "Location: https://api.evil.example/steal\r\n",
            "Content-Type: application/json\r\n",
            "Content-Length: 0\r\n\r\n",
        );
        let server = Loopback::start(vec![Step::Write(redirect.as_bytes().to_vec())]);
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert_eq!(error, C1TransportError::RedirectRefused);
        server.assert_exactly_one_request();
        let rendered = format!("{error}");
        assert!(
            !rendered.contains("evil"),
            "the refusal must not echo the offered location"
        );
    }

    #[test]
    fn an_unexpected_status_is_refused_with_the_code_and_nothing_else() {
        let refusal = concat!(
            "HTTP/1.1 500 Internal Server Error\r\n",
            "Content-Type: application/json\r\n",
            "Content-Length: 2\r\n\r\n",
            "{}",
        );
        let server = Loopback::start(vec![Step::Write(refusal.as_bytes().to_vec())]);
        assert_eq!(
            server
                .transport(C1_MAX_RESPONSE_BODY_BYTES)
                .execute_once(&canonical_body(), WALL)
                .unwrap_err(),
            C1TransportError::UnexpectedStatus { status: 500 }
        );
    }

    #[test]
    fn a_missing_or_wrong_media_type_is_refused() {
        let server = Loopback::start(vec![Step::Write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}".to_vec(),
        )]);
        assert_eq!(
            server
                .transport(C1_MAX_RESPONSE_BODY_BYTES)
                .execute_once(&canonical_body(), WALL)
                .unwrap_err(),
            C1TransportError::MissingMediaType
        );

        let server = Loopback::start(vec![Step::Write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n\r\n{}".to_vec(),
        )]);
        assert_eq!(
            server
                .transport(C1_MAX_RESPONSE_BODY_BYTES)
                .execute_once(&canonical_body(), WALL)
                .unwrap_err(),
            C1TransportError::UnexpectedMediaType
        );
    }

    #[test]
    fn a_json_media_type_with_a_charset_parameter_is_still_admitted() {
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: Application/JSON; charset=utf-8\r\nContent-Length: {}\r\n\r\n{EMPTY_PAGE}",
            EMPTY_PAGE.len()
        );
        let server = Loopback::start(vec![Step::Write(head.into_bytes())]);
        assert_eq!(
            server
                .transport(C1_MAX_RESPONSE_BODY_BYTES)
                .execute_once(&canonical_body(), WALL)
                .expect("a parameterised JSON media type is still JSON")
                .body,
            EMPTY_PAGE.as_bytes()
        );
    }

    #[test]
    fn a_missing_declared_length_with_a_chunked_body_is_accepted_and_still_bounded() {
        let server = Loopback::start(vec![Step::Write(chunked_response(
            &[r#"{"jsonrpc":"2.0","#, r#""id":1,"result":[]}"#],
            "",
            true,
        ))]);
        let response = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .expect("a chunked page carries no declared length and is still bounded");
        assert_eq!(response.body, EMPTY_PAGE.as_bytes());
    }

    #[test]
    fn a_declared_length_over_the_ceiling_is_refused_before_the_body_is_awaited() {
        let ceiling = 4_096;
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
            ceiling + 1
        );
        // The listener sends only the head and then holds the connection open far past the
        // deadline. A transport that waited for the body would time out instead of refusing.
        let server = Loopback::start(vec![
            Step::Write(head.into_bytes()),
            Step::Sleep(Duration::from_millis(DEADLINE_MS * 4)),
        ]);
        let started = Instant::now();
        let error = server
            .transport(ceiling)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert_eq!(
            error,
            C1TransportError::DeclaredLengthOverCeiling {
                declared: ceiling + 1,
                ceiling
            }
        );
        assert!(
            started.elapsed() < Duration::from_millis(DEADLINE_MS),
            "the declared length is settled from the response head, not after the body"
        );
    }

    #[test]
    fn a_malformed_declared_length_is_refused() {
        let server = Loopback::start(vec![Step::Write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 0x10\r\n\r\n{}"
                .to_vec(),
        )]);
        // hyper may refuse the framing itself; either way this is a refusal and never a page.
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert!(
            matches!(
                error,
                C1TransportError::MalformedDeclaredLength
                    | C1TransportError::RequestFailed
                    | C1TransportError::BodyStream
            ),
            "a non-decimal declared length is a refusal, got {error:?}"
        );
    }

    #[test]
    fn a_declared_length_longer_than_the_delivered_body_is_refused() {
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{EMPTY_PAGE}",
            EMPTY_PAGE.len() + 64
        );
        let server = Loopback::start(vec![Step::Write(head.into_bytes())]);
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert!(
            matches!(
                error,
                C1TransportError::DeclaredLengthMismatch { .. } | C1TransportError::BodyStream
            ),
            "an under-delivered declared length is a refusal, got {error:?}"
        );
    }

    #[test]
    fn a_declared_length_shorter_than_the_written_bytes_never_smuggles_the_remainder() {
        let padding = "x".repeat(4_096);
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{EMPTY_PAGE}{padding}",
            EMPTY_PAGE.len()
        );
        let server = Loopback::start(vec![Step::Write(head.into_bytes())]);
        let outcome = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL);
        match outcome {
            // The HTTP/1 decoder stops at the declared length, so the trailing bytes are never
            // delivered here and can never reach a retained observation.
            Ok(response) => assert_eq!(
                response.body,
                EMPTY_PAGE.as_bytes(),
                "bytes past the declared length must never enter the retained body"
            ),
            Err(error) => assert!(
                matches!(error, C1TransportError::DeclaredLengthMismatch { .. }),
                "over-delivery is a length disagreement, got {error:?}"
            ),
        }
    }

    /// Two disagreeing framings are the case the in-loop over-delivery guard actually catches.
    ///
    /// `hyper` leaves both `Content-Length` and `Transfer-Encoding: chunked` in the head and
    /// decodes the chunked body, so the delivered length runs past the declared one while the
    /// stream is still being read. The refusal is pinned exactly, because "some error happened"
    /// would stay green if the guard were deleted and the body were simply retained.
    #[test]
    fn a_chunked_body_that_contradicts_a_declared_length_is_refused_mid_stream() {
        let server = Loopback::start(vec![Step::Write(chunked_response(
            &[EMPTY_PAGE],
            "Content-Length: 5\r\n",
            true,
        ))]);
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert_eq!(
            error,
            C1TransportError::DeclaredLengthMismatch {
                declared: 5,
                delivered: EMPTY_PAGE.len() as u64,
            },
            "a response whose two framings disagree is never a page"
        );
    }

    /// The same disagreement in the other direction, which only the post-loop check can see.
    ///
    /// The chunked stream terminates cleanly under its declared length, so nothing during the
    /// loop is out of bounds; the delivered total is compared against the declaration once the
    /// body ends. This is the reachable case for that comparison.
    /// The in-loop guard is a *boundedness* guard, not just a different error name.
    ///
    /// Deleting it and letting the post-loop comparison catch the same disagreement produces the
    /// same refusal for a body that ends — which is why the mid-stream case above cannot pin it.
    /// What it actually buys is abandonment: the stream here never terminates and the listener
    /// then holds the socket far past the deadline, so a transport that accumulated first would
    /// return `Deadline` instead of naming the disagreement.
    #[test]
    fn a_chunked_body_running_past_its_declared_length_is_abandoned_mid_stream() {
        let chunk = "z".repeat(1_024);
        let chunks: Vec<&str> = (0..16).map(|_| chunk.as_str()).collect();
        let server = Loopback::start(vec![
            Step::Write(chunked_response(&chunks, "Content-Length: 5\r\n", false)),
            Step::Sleep(Duration::from_millis(DEADLINE_MS * 4)),
        ]);
        let started = Instant::now();
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        let C1TransportError::DeclaredLengthMismatch {
            declared,
            delivered,
        } = error
        else {
            panic!("an over-delivered declaration is a length disagreement, got {error:?}")
        };
        assert_eq!(declared, 5);
        assert!(
            delivered > declared,
            "the body is abandoned the moment it passes its own declaration, at {delivered} bytes"
        );
        assert!(
            started.elapsed() < Duration::from_millis(DEADLINE_MS),
            "the disagreement is settled mid-stream, not after the body is drained"
        );
    }

    #[test]
    fn a_chunked_body_under_its_declared_length_is_refused_after_the_stream_ends() {
        let server = Loopback::start(vec![Step::Write(chunked_response(
            &[EMPTY_PAGE],
            "Content-Length: 4096\r\n",
            true,
        ))]);
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert_eq!(
            error,
            C1TransportError::DeclaredLengthMismatch {
                declared: 4_096,
                delivered: EMPTY_PAGE.len() as u64,
            },
            "an under-delivered declaration is refused once the stream ends"
        );
    }

    #[test]
    fn a_streaming_body_past_the_ceiling_is_abandoned_without_reading_to_the_end() {
        let ceiling = 4_096;
        let chunk = "z".repeat(1_024);
        let chunks: Vec<&str> = (0..16).map(|_| chunk.as_str()).collect();
        // The stream is deliberately never terminated, and the listener then holds the socket
        // open far past the deadline. A transport that read to the end before bounding would time
        // out; abandoning mid-stream is the only way to return this refusal promptly.
        let server = Loopback::start(vec![
            Step::Write(chunked_response(&chunks, "", false)),
            Step::Sleep(Duration::from_millis(DEADLINE_MS * 4)),
        ]);
        let started = Instant::now();
        let error = server
            .transport(ceiling)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert_eq!(error, C1TransportError::BodyOverCeiling { ceiling });
        assert!(
            started.elapsed() < Duration::from_millis(DEADLINE_MS),
            "the body is abandoned at the ceiling, not drained to completion"
        );
    }

    /// A connection that dies before any response byte must not become a second request.
    ///
    /// This is the shape a retrying client would duplicate: the request was written and the peer
    /// closed with nothing back. The accept loop records every connection, so a retry would show
    /// up here as a second request.
    ///
    /// What this does and does not establish is written out in the module documentation: with
    /// this crate's feature set `reqwest`'s default classifier already retries nothing, so a
    /// green here is a statement about the behaviour, not proof that `retry(never())` is what
    /// produced it.
    #[test]
    fn a_connection_closed_with_no_response_produces_exactly_one_request() {
        let server = Loopback::start(Vec::new());
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert!(
            matches!(
                error,
                C1TransportError::RequestFailed | C1TransportError::BodyStream
            ),
            "a peer that answers nothing is a refusal, got {error:?}"
        );
        assert_eq!(
            server.observed_requests().len(),
            1,
            "the one request is never duplicated after a dead connection"
        );
    }

    #[test]
    fn an_exhausted_deadline_is_a_refusal() {
        let server = Loopback::start(vec![Step::Sleep(Duration::from_millis(DEADLINE_MS * 6))]);
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert_eq!(error, C1TransportError::Deadline);
        server.assert_exactly_one_request();
    }

    #[test]
    fn a_refused_connection_is_a_refusal_that_names_nothing() {
        // Bind and immediately drop the listener, so the port is almost certainly unbound.
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let addr = listener.local_addr().expect("addr");
        drop(listener);
        let error = C1Transport::loopback(format!("http://{addr}"), 4_096, DEADLINE_MS)
            .expect("bind the loopback transport")
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert!(
            matches!(
                error,
                C1TransportError::Connect | C1TransportError::RequestFailed
            ),
            "an unreachable address is a refusal, got {error:?}"
        );
        assert_no_locator(&error);
    }

    #[test]
    fn elapsed_is_derived_from_the_monotonic_pair_and_not_from_the_supplied_wall_reading() {
        let early = UnixMillis(946_684_800_000);
        let late = UnixMillis(1_893_456_000_000);
        let mut elapsed = Vec::new();
        for wall in [early, late] {
            let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
            let response = server
                .transport(C1_MAX_RESPONSE_BODY_BYTES)
                .execute_once(&canonical_body(), wall)
                .expect("one successful bounded page");
            assert_eq!(
                response.received_at.0 - wall.0,
                i64::try_from(response.elapsed_ms).expect("elapsed fits i64"),
                "the receipt instant is exactly the supplied wall reading plus monotonic elapsed"
            );
            elapsed.push(response.elapsed_ms);
        }
        let wall_gap = u64::try_from(late.0 - early.0).expect("wall gap fits u64");
        let measured_gap = elapsed[0].abs_diff(elapsed[1]);
        assert!(
            measured_gap < 1_000 && measured_gap < wall_gap,
            "a wall reading {wall_gap} ms apart moved the measured elapsed by {measured_gap} ms"
        );
    }

    /// The monotonic pair has to *measure* something, not merely be arithmetically consistent.
    ///
    /// Without this, a clock that reported a constant zero elapsed would satisfy every other
    /// assertion about elapsed time in this module: the receipt instant would equal the supplied
    /// wall reading, and a wall jump would still move nothing.
    #[test]
    fn a_deliberately_slow_response_moves_the_measured_elapsed_off_zero() {
        const HELD_MS: u64 = 120;
        let server = Loopback::start(vec![
            Step::Sleep(Duration::from_millis(HELD_MS)),
            Step::Write(ok_page_response(EMPTY_PAGE, "")),
        ]);
        let response = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .expect("a slow but well-formed page is still a page");
        assert!(
            response.elapsed_ms >= HELD_MS - 10,
            "a response held for {HELD_MS} ms measured {} ms",
            response.elapsed_ms
        );
        assert!(
            response.elapsed_ms < DEADLINE_MS,
            "the request still finished inside its deadline: {} ms",
            response.elapsed_ms
        );
        assert_eq!(
            response.received_at.0 - WALL.0,
            i64::try_from(response.elapsed_ms).expect("elapsed fits i64"),
            "the receipt instant is the supplied wall reading advanced by the measured elapsed"
        );
    }

    #[test]
    fn a_declared_length_that_is_not_a_plain_byte_count_is_refused() {
        // `hyper` refuses this framing before a response ever reaches `execute_once`, which is
        // what `a_malformed_declared_length_is_refused` observes end to end. The guard is still
        // the thing that decides, so it is exercised here as the function it is.
        // `+5` is the one that separates this guard from the `parse` fallback below it:
        // `u64::from_str` accepts a leading sign, and only the digit check refuses it.
        for malformed in ["0x10", "10 20", "-1", "+5", "+0", "", "   ", "12a", "١٢"] {
            let mut headers = HeaderMap::new();
            headers.insert(
                CONTENT_LENGTH,
                HeaderValue::from_str(malformed).expect("a header value"),
            );
            assert_eq!(
                declared_body_length(&headers).unwrap_err(),
                C1TransportError::MalformedDeclaredLength,
                "{malformed:?} is not a plain decimal byte count"
            );
        }
        let mut headers = HeaderMap::new();
        headers.insert(
            CONTENT_LENGTH,
            HeaderValue::from_bytes(&[0xff, 0xfe]).expect("an opaque header value"),
        );
        assert_eq!(
            declared_body_length(&headers).unwrap_err(),
            C1TransportError::MalformedDeclaredLength,
            "a declared length that is not UTF-8 is refused, never ignored"
        );
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_LENGTH, HeaderValue::from_static(" 36 "));
        assert_eq!(
            declared_body_length(&headers).expect("a padded decimal count"),
            Some(36),
            "surrounding whitespace is trimmed rather than refused"
        );
        assert_eq!(
            declared_body_length(&HeaderMap::new()).expect("no declaration at all"),
            None,
            "a chunked response declares no length and is bounded by the ceiling alone"
        );
    }

    /// The reduction and the shared bound are two different jobs, and this is what ties them.
    ///
    /// [`C1TransportError::HeaderBudget`] is unreachable exactly while this holds: every set
    /// `retained_headers` can produce is one `public_solana_c1_safe_headers_are_bounded` admits.
    /// Raising [`MAX_RETAINED_HEADER_VALUE_BYTES`] past the shared value limit, or adding a name
    /// to [`RETAINED_HEADER_NAMES`] the shared allowlist does not carry, breaks that and fails
    /// here rather than turning a live endpoint's headers into a refused read.
    #[test]
    fn every_reduction_the_filter_can_produce_is_within_the_shared_bound() {
        let at_bound = "v".repeat(MAX_RETAINED_HEADER_VALUE_BYTES);
        let over_bound = "v".repeat(MAX_RETAINED_HEADER_VALUE_BYTES + 1);
        let mut hostile = HeaderMap::new();
        for name in RETAINED_HEADER_NAMES {
            hostile.append(name, HeaderValue::from_str(&at_bound).expect("value"));
            hostile.append(name, HeaderValue::from_str(&over_bound).expect("value"));
            hostile.append(name, HeaderValue::from_static("second"));
        }
        for index in 0..64_u32 {
            hostile.append(
                reqwest::header::HeaderName::from_bytes(format!("x-pad-{index}").as_bytes())
                    .expect("header name"),
                HeaderValue::from_str(&over_bound).expect("value"),
            );
        }
        hostile.append(
            "set-cookie",
            HeaderValue::from_static("session=secret; Path=/"),
        );
        hostile.append(
            CONTENT_LENGTH,
            HeaderValue::from_bytes(&[0xff]).expect("opaque value"),
        );
        let retained = retained_headers(&hostile);
        assert_eq!(
            retained
                .iter()
                .map(|header| header.name.as_str())
                .collect::<Vec<_>>(),
            RETAINED_HEADER_NAMES.to_vec(),
            "the reduction keeps exactly the allowlist, sorted, and nothing else"
        );
        for header in &retained {
            assert_eq!(
                header.value, at_bound,
                "the first admissible value wins and an over-long one is dropped"
            );
        }
        assert!(
            public_solana_c1_safe_headers_are_bounded(&retained),
            "a value of exactly {MAX_RETAINED_HEADER_VALUE_BYTES} bytes must be inside the shared \
             bound; this is the coupling that makes HeaderBudget unreachable"
        );

        // An empty response head reduces to an empty set, which is also within the bound.
        assert!(retained_headers(&HeaderMap::new()).is_empty());
        assert!(public_solana_c1_safe_headers_are_bounded(&[]));
    }

    #[test]
    fn a_control_character_or_opaque_value_is_dropped_rather_than_refusing_the_read() {
        let mut headers = HeaderMap::new();
        headers.append(
            "retry-after",
            HeaderValue::from_bytes(b"3\t4").expect("a control-carrying value"),
        );
        headers.append(
            "x-ratelimit-limit",
            HeaderValue::from_bytes(&[0xff, 0xfe]).expect("an opaque value"),
        );
        headers.append("x-ratelimit-reset", HeaderValue::from_static("7"));
        let retained = retained_headers(&headers);
        assert_eq!(
            retained
                .iter()
                .map(|header| (header.name.as_str(), header.value.as_str()))
                .collect::<Vec<_>>(),
            vec![("x-ratelimit-reset", "7")],
            "a header the endpoint controls may be dropped but must never deny the read"
        );
        assert!(public_solana_c1_safe_headers_are_bounded(&retained));
    }

    /// Every refusal this module can produce, so the redaction check is exhaustive rather than a
    /// sample. The `match` below fails to compile if a variant is added and not listed here.
    fn every_error_variant() -> Vec<C1TransportError> {
        let all = vec![
            C1TransportError::ZeroCeiling,
            C1TransportError::InvalidDeadline,
            C1TransportError::InvalidRequestBody,
            C1TransportError::ExecutorUnavailable,
            C1TransportError::ClientBuild,
            C1TransportError::RequestBuild,
            C1TransportError::Connect,
            C1TransportError::Deadline,
            C1TransportError::RequestFailed,
            C1TransportError::BodyStream,
            C1TransportError::RedirectRefused,
            C1TransportError::UnexpectedStatus { status: 503 },
            C1TransportError::MissingMediaType,
            C1TransportError::UnexpectedMediaType,
            C1TransportError::MalformedDeclaredLength,
            C1TransportError::DeclaredLengthOverCeiling {
                declared: 9,
                ceiling: 8,
            },
            C1TransportError::DeclaredLengthMismatch {
                declared: 9,
                delivered: 8,
            },
            C1TransportError::BodyOverCeiling { ceiling: 8 },
            C1TransportError::HeaderBudget,
            C1TransportError::ClockRange,
        ];
        for error in &all {
            match error {
                C1TransportError::ZeroCeiling
                | C1TransportError::InvalidDeadline
                | C1TransportError::InvalidRequestBody
                | C1TransportError::ExecutorUnavailable
                | C1TransportError::ClientBuild
                | C1TransportError::RequestBuild
                | C1TransportError::Connect
                | C1TransportError::Deadline
                | C1TransportError::RequestFailed
                | C1TransportError::BodyStream
                | C1TransportError::RedirectRefused
                | C1TransportError::UnexpectedStatus { .. }
                | C1TransportError::MissingMediaType
                | C1TransportError::UnexpectedMediaType
                | C1TransportError::MalformedDeclaredLength
                | C1TransportError::DeclaredLengthOverCeiling { .. }
                | C1TransportError::DeclaredLengthMismatch { .. }
                | C1TransportError::BodyOverCeiling { .. }
                | C1TransportError::HeaderBudget
                | C1TransportError::ClockRange => {}
            }
        }
        all
    }

    fn assert_no_locator(error: &C1TransportError) {
        for rendered in [format!("{error}"), format!("{error:?}")] {
            let lowered = rendered.to_ascii_lowercase();
            for needle in ["http", "://", "api.", "solana"] {
                assert!(
                    !lowered.contains(needle),
                    "refusal {rendered:?} leaks the endpoint-shaped substring {needle:?}"
                );
            }
        }
    }

    #[test]
    fn no_error_variant_renders_an_endpoint_shaped_string() {
        for error in every_error_variant() {
            assert_no_locator(&error);
        }
    }

    #[test]
    fn every_loopback_refusal_observed_in_practice_renders_without_a_locator() {
        let redirect = concat!(
            "HTTP/1.1 307 Temporary Redirect\r\n",
            "Location: https://api.mainnet.solana.com/other\r\n",
            "Content-Type: application/json\r\n",
            "Content-Length: 0\r\n\r\n",
        );
        let server = Loopback::start(vec![Step::Write(redirect.as_bytes().to_vec())]);
        let error = server
            .transport(C1_MAX_RESPONSE_BODY_BYTES)
            .execute_once(&canonical_body(), WALL)
            .unwrap_err();
        assert_no_locator(&error);
    }
}
