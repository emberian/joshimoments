//! The bounded public-Solana JSON-RPC wire contract.
//!
//! This module is real, non-test, and completely pure. It encodes the exact
//! `getSignaturesForAddress` request body this tree admits and reads a hostile response body back
//! into unverified raw conformance data. It contains no endpoint, URL, host, request header,
//! credential, socket, clock, or retry policy, and it performs no I/O. Any reviewed transport may
//! consume it — the authenticated Helius path and the free public path alike; nothing here can
//! cause a request.
//!
//! The response-side reader is written for a hostile body: it refuses before it parses (length
//! ceiling first, then UTF-8, then exactly one JSON value with no trailing bytes and no duplicate
//! keys), and every structural refusal names what it refused rather than truncating and retaining
//! a partial provider claim.
//!
//! Nothing produced here is a verified fact. The rows this module returns are provider claims
//! retained verbatim; the authority ceiling `read_only_no_execution` applies to all of it.

use std::{collections::BTreeSet, fmt};

use serde::{
    Deserialize,
    de::{self, MapAccess, SeqAccess, Visitor},
};
use serde_json::Value;
use thiserror::Error;

use crate::{
    ContentType, FrameDirection, RawSourceFrame, SafeHeader, SourceId, StreamClass, Transport,
};

// ---------------------------------------------------------------------------------------------
// Frozen wire constants
// ---------------------------------------------------------------------------------------------

/// Exact JSON-RPC protocol version string admitted on both the request and the response.
pub const SOLANA_JSON_RPC_VERSION: &str = "2.0";
/// Exact JSON-RPC request identifier. The canonical request is a single call, never a batch, so
/// the identifier is fixed rather than a counter.
pub const SOLANA_JSON_RPC_ID: u64 = 1;
/// Exact registered method name.
pub const SOLANA_SIGNATURES_METHOD: &str = "getSignaturesForAddress";
/// Exact commitment declared by the registered method and required of every returned row.
pub const SOLANA_SIGNATURES_COMMITMENT: &str = "finalized";
/// Lowest row bound the frozen schema admits.
pub const SOLANA_SIGNATURES_MIN_ROWS: u16 = 1;
/// Highest row bound the frozen schema admits.
pub const SOLANA_SIGNATURES_MAX_ROWS: u16 = 100;
/// Local restatement of the registered `max_request_bytes` for this method: 4096 bytes.
///
/// This constant is *not* read from the source registry at run time. It is pinned to the registry
/// by the unit test `registered_request_bound_matches_the_canonical_source_registry`, so a
/// registry change fails that test rather than silently widening the bound admitted here.
pub const SOLANA_JSON_RPC_MAX_REQUEST_BYTES: usize = 4 * 1_024;

/// Longest response entity body any ingest path in this tree will look at: 256 KiB.
///
/// This is the **ingress ceiling**, and `joshi-sources` is its single source of truth. It is not
/// specific to one endpoint or one method: it bounds the authenticated Helius reads, the free
/// public Solana reads, and the response reader below, all from one definition.
///
/// The coupling is realised in code rather than by agreement: at
/// `crates/joshi-supervisor/src/ingest/physical_size.rs` the supervisor's
/// `INGEST_MAX_RESPONSE_BODY_BYTES` is *defined* as `joshi_sources::INGEST_MAX_RESPONSE_BYTES
/// as u64`, so the whole physical-size derivation there reads this constant and cannot disagree
/// with it. The direction is forced by the dependency edge: `joshi-supervisor` depends on
/// `joshi-sources` and not the reverse, so the ceiling has to live on this side of it.
///
/// Nothing in *this* crate can test that coupling, because `joshi-sources` cannot depend on
/// `joshi-supervisor`; the guarantee is the `as u64` definition itself. An earlier revision
/// restated `256 * 1024` on the supervisor side instead, and an audit showed this constant could
/// then be widened 16x with every test on both sides still green. That mutation was re-run
/// against the definition now in place and fails the supervisor build: its `const _` guard
/// asserts the derived physical segment stays under the smallest hosting segment ceiling, and a
/// 4 MiB ingress ceiling does not.
///
/// **What a widening costs, measured rather than assumed.** The compile-time guard admits any
/// ceiling up to 414,267 bytes, since that is the largest one whose derived segment stays under
/// the 4 MiB anchor. Inside that range a change still compiles — but it is not consequence-free.
/// A widening is silent *on this side*, because no test here is derived from the value, and it
/// fails `joshi-supervisor` unit tests *there*, because every golden physical measurement in that
/// module is derived from 262,144. Past 414,267 bytes the supervisor stops compiling instead. So
/// whoever widens this has to re-measure the physical bound rather than only edit this line.
///
/// The number is not a schema value and is not read from the source registry. The registry
/// declares a 64 MiB `max_response_bytes` for `getSignaturesForAddress`, but that is a *contract*
/// ceiling on what the source is permitted to send, not a budget this path can durably absorb:
/// the supervisor's derivation expands one ingress byte into a worst case of `4 * (4/3)^3 =
/// 256/27`, about 9.5 bytes of local spool segment, so a 64 MiB body would not fit the configured
/// segment ceiling at all. 256 KiB is instead sized against the shape a signature page actually
/// admits — at most 100 rows, a realistic full page being roughly 20-30 KiB — leaving a wide
/// margin for long memo text and verbose `err` objects. It is a chosen operational bound, not a
/// derived or exact quantity, and a caller whose sink can absorb more may construct its client
/// with a larger one.
///
/// Refusing at this length is what keeps [`read_solana_json_rpc_body`] bounded: every step after
/// the check costs work proportional to the body, so the check runs before all of them.
pub const INGEST_MAX_RESPONSE_BYTES: usize = 256 * 1_024;

/// Exact decoded length of a Solana address.
const ADDRESS_BYTES: usize = 32;
/// Longest base58 spelling a 32-byte address can have, in bytes.
///
/// A 32-byte value is at most `2^256 - 1`, and `log58(2^256)` is under 43.7, so no 32-byte
/// address needs more than 44 base58 characters; the all-`0xFF` address realises exactly that
/// width, which `the_longest_admissible_canonical_request_body_is_exactly_156_bytes` pins.
///
/// The comparison is on **bytes**, which is what makes it a valid pre-check: the base58 alphabet
/// is ASCII, so an admissible address has one byte per character. A value longer than 44 bytes
/// therefore either carries a non-ASCII character — not base58 — or carries more than 44 base58
/// characters, which cannot decode to 32 bytes. Neither is admissible, and neither needs decoding
/// to establish.
const MAX_ADDRESS_BASE58_CHARS: usize = 44;
/// Exact decoded length of a Solana transaction signature.
///
/// This is pinned to a fixed 88-character base58 signature literal by the unit test
/// `the_admitted_signature_length_is_pinned_to_a_fixed_signature_literal`, which decodes that
/// literal without reference to this constant. Without such a pin the accept-side fixtures, which
/// build their base58 *from* this constant, would move with any change to it and the suite would
/// only be comparing the implementation with itself.
const SIGNATURE_BYTES: usize = 64;
/// Conservative bound on a retained provider refusal message. It is a local sanitation limit, not
/// a value the frozen schema declares.
///
/// Bounded on both sides by the unit test
/// `a_refusal_message_at_the_sanitation_bound_is_retained_and_one_byte_over_is_refused`, so
/// widening this number is visible as a failing test rather than as a silently larger retained
/// string.
const MAX_REFUSAL_MESSAGE_BYTES: usize = 512;
/// Conservative bound on the auxiliary data retained beside a provider refusal message, measured
/// on the canonical JSON serialization of the retained value. It is a local sanitation limit, not
/// a value the frozen schema declares — the schema says only `"rpcError":"typed_json_rpc_refusal"`
/// and declares no shape for `data` at all.
///
/// It exists for the same reason `MAX_REFUSAL_MESSAGE_BYTES` does. `data` is provider-controlled
/// content that this module hands back to a caller inside [`JsonRpcRefusal`], and without a bound
/// of its own the only thing limiting it is the whole ingress ceiling: a provider could put a
/// quarter-megabyte of its own JSON into a value documented as sanitized. Twice the message bound
/// is far above what this method's refusals carry in practice — a rate-limit refusal's data is
/// `{"retryAfterMs":250}`, 20 bytes.
///
/// Bounded on both sides by `refusal_auxiliary_data_is_bounded_at_the_same_boundary_as_the_message`.
const MAX_REFUSAL_DATA_BYTES: usize = 1_024;
/// Conservative bound on one retained safe-header value. It is a local sanitation limit, not a
/// value the frozen schema declares.
const MAX_SAFE_HEADER_VALUE_BYTES: usize = 256;

// ---------------------------------------------------------------------------------------------
// Canonical request construction (pure; no endpoint, no credential, no I/O)
// ---------------------------------------------------------------------------------------------

/// Exact canonical request body bytes for one `getSignaturesForAddress` call.
///
/// The bytes are a complete JSON-RPC 2.0 request *body* and nothing else: there is no URL, host,
/// header, or credential anywhere in this value. Constructing it neither performs nor authorizes
/// a request.
///
/// **This type carries no witness.** Both fields are public and there is no private member, so
/// any caller can build one whose `byte_len` disagrees with `body.len()`, or whose `body` is not
/// a canonical request at all. The type is a return shape, not a proof: the guarantees below hold
/// of values returned by [`canonical_solana_signatures_request`] and of nothing else, and a caller
/// that receives one from somewhere else has been told nothing by its type. Making the fields
/// private would say more, and would also break the in-tree consumers that read `body` and
/// `byte_len` directly; the doc is corrected here rather than the claim left standing.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalSolanaRequest {
    /// Exact request body bytes, canonically encoded by
    /// [`canonical_solana_signatures_request`].
    pub body: Vec<u8>,
    /// Length of `body` in bytes.
    ///
    /// Equal to `body.len()` in every value [`canonical_solana_signatures_request`] returns, which
    /// `canonical_request_bytes_are_exact_and_byte_identical_across_calls` pins. It is a
    /// convenience, never an independent fact, and a caller that needs the length of a
    /// `CanonicalSolanaRequest` it did not receive from that function should read `body.len()`.
    pub byte_len: usize,
}

/// Refusal from canonical request construction. It never renders the rejected input back.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum SolanaRequestError {
    #[error("address is not base58")]
    AddressNotBase58,
    #[error("address does not decode to exactly 32 bytes")]
    AddressNotThirtyTwoBytes,
    #[error("address is not the canonical base58 encoding of its own bytes")]
    AddressNotCanonicalBase58,
    #[error("row bound is outside the registered 1..=100 range")]
    RowBoundOutOfRange,
    #[error("canonical request body exceeds the registered maximum request size")]
    RequestExceedsRegisteredBound,
}

/// Encode the exact canonical request body for one bounded `getSignaturesForAddress` call.
///
/// The encoding is deterministic and byte-identical for identical input: keys are emitted in the
/// fixed order `jsonrpc`, `id`, `method`, `params`, the params config object in the fixed order
/// `commitment`, `limit`, with no whitespace and no floating-point numbers. The frozen schema is
/// `fixtures/source-registry/solana_get_signatures_for_address.v1.json`, closed over by
/// `PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT`. The optional `before` cursor the schema
/// permits is deliberately not emitted: this request reads exactly one newest-first page.
///
/// The address is validated by decoding it as base58 to exactly 32 bytes and re-encoding it back
/// to the identical string. This is what licenses splicing `address` straight into the JSON
/// string with no escaping: every byte of an accepted address is drawn from the base58 alphabet,
/// which contains neither a quote nor a backslash. `bs58` decoding already refuses characters
/// outside that alphabet, so the re-encode is a defensive restatement of the property the splice
/// depends on rather than the only guard, and no input is known that reaches
/// [`SolanaRequestError::AddressNotCanonicalBase58`].
///
/// # Boundedness
///
/// Length is checked before the decode, for the same reason
/// [`read_solana_json_rpc_body`] checks its ingress ceiling first: base58 decoding is quadratic
/// in the input length, so decoding an arbitrary-length argument first would let a caller spend
/// work proportional to the square of what it passed. An address over
/// `MAX_ADDRESS_BASE58_CHARS` bytes is refused before any decode, so the decode that does run
/// is over at most 44 bytes.
///
/// That ordering is visible in the refusal a caller gets: an over-long argument is refused as
/// [`SolanaRequestError::AddressNotThirtyTwoBytes`] whether or not it is base58 at all,
/// because the length alone already establishes that it does not decode to 32 bytes.
///
/// # Errors
///
/// Refuses an address longer than `MAX_ADDRESS_BASE58_CHARS` bytes, a non-base58 address, an
/// address that does not decode to exactly 32 bytes, a non-canonical base58 address, a `max_rows`
/// outside the schema's 1..=100 range, and — as a defensive check that no admissible input is
/// expected to reach — a body larger than [`SOLANA_JSON_RPC_MAX_REQUEST_BYTES`].
pub fn canonical_solana_signatures_request(
    address: &str,
    max_rows: u16,
) -> Result<CanonicalSolanaRequest, SolanaRequestError> {
    if !(SOLANA_SIGNATURES_MIN_ROWS..=SOLANA_SIGNATURES_MAX_ROWS).contains(&max_rows) {
        return Err(SolanaRequestError::RowBoundOutOfRange);
    }
    // Length first: bs58 decoding is quadratic in its input, so an unbounded argument must never
    // reach it. Nothing over this width can decode to 32 bytes, so no admissible input is lost.
    if address.len() > MAX_ADDRESS_BASE58_CHARS {
        return Err(SolanaRequestError::AddressNotThirtyTwoBytes);
    }
    let decoded = bs58::decode(address)
        .into_vec()
        .map_err(|_| SolanaRequestError::AddressNotBase58)?;
    if decoded.len() != ADDRESS_BYTES {
        return Err(SolanaRequestError::AddressNotThirtyTwoBytes);
    }
    if bs58::encode(&decoded).into_string() != address {
        return Err(SolanaRequestError::AddressNotCanonicalBase58);
    }

    let mut body = String::with_capacity(192);
    body.push_str("{\"jsonrpc\":\"");
    body.push_str(SOLANA_JSON_RPC_VERSION);
    body.push_str("\",\"id\":");
    body.push_str(&SOLANA_JSON_RPC_ID.to_string());
    body.push_str(",\"method\":\"");
    body.push_str(SOLANA_SIGNATURES_METHOD);
    body.push_str("\",\"params\":[\"");
    body.push_str(address);
    body.push_str("\",{\"commitment\":\"");
    body.push_str(SOLANA_SIGNATURES_COMMITMENT);
    body.push_str("\",\"limit\":");
    body.push_str(&max_rows.to_string());
    body.push_str("}]}");

    let body = body.into_bytes();
    if body.len() > SOLANA_JSON_RPC_MAX_REQUEST_BYTES {
        return Err(SolanaRequestError::RequestExceedsRegisteredBound);
    }
    Ok(CanonicalSolanaRequest {
        byte_len: body.len(),
        body,
    })
}

// ---------------------------------------------------------------------------------------------
// Response conformance (pure; hostile input in, unverified raw data out)
// ---------------------------------------------------------------------------------------------

/// The three outcomes of reading a response body are kept explicitly distinct.
///
/// A well-formed provider refusal is *not* a page, *not* absence, and *not* a transport failure.
/// It is modelled as its own [`SolanaJsonRpcOutcome::ProviderRefusal`] variant and can never
/// carry rows. A malformed or hostile body is neither variant: it is an
/// [`SolanaJsonRpcConformanceError`].
#[derive(Clone, Debug, PartialEq)]
pub enum SolanaJsonRpcOutcome {
    /// A structurally conforming page of unverified raw provider claims.
    Page(RawSignaturePage),
    /// A typed JSON-RPC refusal from the provider, retained verbatim within a sanitation bound.
    ProviderRefusal(JsonRpcRefusal),
}

/// One structurally conforming page of unverified raw rows.
///
/// An empty `rows` vector NEVER means absence and NEVER establishes coverage. The frozen schema
/// declares `"absence":"never_proves_absence"`; a zero-row page is exactly one provider response
/// that listed nothing, and it licenses no claim about the wallet's history or about any window
/// having been observed.
#[derive(Clone, Debug, PartialEq)]
pub struct RawSignaturePage {
    /// Rows in the provider's declared newest-first order, retained verbatim.
    pub rows: Vec<RawSignatureRow>,
}

/// One unverified raw row. Every field is a provider claim, not a JOSHI fact.
///
/// In particular `confirmation_status` of `finalized` is NOT a JOSHI finality fact. It is the
/// provider's own word about its own view, retained verbatim because the registered method
/// declares a finalized commitment. Nothing in this crate verifies it against a chain.
#[derive(Clone, Debug, PartialEq)]
pub struct RawSignatureRow {
    /// Provider-supplied base58 signature, already checked to decode to exactly 64 bytes.
    pub signature: String,
    /// Provider-claimed slot.
    pub slot: u64,
    /// Provider-supplied error object or JSON null, retained verbatim and never interpreted here.
    pub err: Value,
    /// Provider-supplied memo. The field must be present; its value may be null.
    pub memo: Option<String>,
    /// Provider-claimed block time. The field must be present; its value may be null.
    pub block_time: Option<i64>,
    /// Provider claim only. Not a JOSHI finality fact.
    pub confirmation_status: Option<String>,
}

/// A typed JSON-RPC refusal from the provider.
///
/// This is a successful, well-formed answer that says "no". It is a first-class outcome, never a
/// page and never absence: a caller that sees this learns only that the provider declined, and
/// learns nothing about the wallet.
#[derive(Clone, Debug, PartialEq)]
pub struct JsonRpcRefusal {
    /// Provider-supplied JSON-RPC error code, retained verbatim.
    pub code: i64,
    /// Provider-supplied message, retained verbatim within a local sanitation bound.
    pub message: String,
    /// Provider-supplied auxiliary data, retained verbatim and never interpreted here.
    ///
    /// Retained within its own sanitation bound, `MAX_REFUSAL_DATA_BYTES`, measured on the
    /// canonical serialization of the value. The bound is on the retained *value*, not on the
    /// span of wire bytes it was parsed from: the two differ by whitespace and by object-key
    /// order, neither of which survives the parse.
    pub data: Option<Value>,
}

/// Refusal from response conformance reading. It never renders the rejected body back.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum SolanaJsonRpcConformanceError {
    #[error("response body is longer than the ingress ceiling")]
    ResponseExceedsIngressCeiling,
    #[error("registered row bound is outside the schema's 1..=100 range")]
    RegisteredRowBoundOutOfRange,
    #[error("response body is empty")]
    EmptyBody,
    #[error("response body is not valid UTF-8")]
    NotUtf8,
    #[error("response body is not well-formed JSON")]
    MalformedJson,
    #[error("response body carries trailing bytes after the JSON value")]
    TrailingBytes,
    #[error("response body contains a duplicate JSON object key")]
    DuplicateJsonKey,
    #[error("response body does not match the frozen JSON-RPC envelope")]
    EnvelopeMismatch,
    #[error("response body carries both a result and an error member")]
    ResultAndErrorBothPresent,
    #[error("response body carries neither a result nor an error member")]
    NeitherResultNorError,
    #[error("provider refusal message is not within the local sanitation bound")]
    RefusalMessageNotBounded,
    #[error("provider refusal auxiliary data is not within the local sanitation bound")]
    RefusalDataNotBounded,
    #[error("page carries more rows than the registered bound")]
    RowLimitExceeded,
    #[error("row signature is not base58")]
    SignatureNotBase58,
    #[error("row signature does not decode to exactly 64 bytes")]
    SignatureWrongLength,
    #[error("page repeats a signature")]
    DuplicateSignature,
    #[error("page slots are not non-increasing as the newest-first ordering requires")]
    OrderingNotNewestFirst,
    #[error("row does not carry the registered finalized commitment claim")]
    ConfirmationStatusNotFinalized,
    #[error("frame envelope does not match the bounded public-Solana declaration")]
    FrameEnvelopeMismatch,
}

/// Read a raw public-Solana JSON-RPC response body into unverified raw conformance data.
///
/// This is the public entry point for hostile-body validation. It takes only the raw bytes and the
/// registered `max_rows` and returns only unverified raw conformance data: structural conformance
/// to the frozen schema is all that is established. No returned value is evidence, coverage, or a
/// finality fact.
///
/// The ordering rule enforced here is **slots non-increasing**. The schema declares
/// `"ordering":"newest_first"`, and slots may repeat: one slot can contain several signatures for
/// the same address, so equal adjacent slots are legal and are accepted. A strictly increasing
/// step is refused. Within a run of equal slots this reader deliberately imposes no order, because
/// the payload carries no total order there and JOSHI does not invent one; repeated *signatures*
/// are refused separately.
///
/// A well-formed typed JSON-RPC error is returned as
/// [`SolanaJsonRpcOutcome::ProviderRefusal`] and can never carry rows.
///
/// # Boundedness
///
/// The reader is bounded by length before it is bounded by anything else. A body longer than
/// [`INGEST_MAX_RESPONSE_BYTES`] is refused as the very first act, before the bytes are
/// examined as UTF-8, parsed, walked for duplicate keys, or decoded, so a hostile body cannot make
/// this function allocate in proportion to its own length. Inside that ceiling the work is bounded
/// but not minimal: the document is still parsed once into a `serde_json::Value`, walked a second
/// time for duplicate keys, and decoded into typed rows before the registered row bound is
/// applied, so peak cost is a small multiple of the ceiling rather than of `max_rows`.
///
/// # Errors
///
/// Refuses a body longer than [`INGEST_MAX_RESPONSE_BYTES`], a `max_rows` outside
/// 1..=100, an empty body, non-UTF-8 input, malformed JSON, trailing bytes after the JSON value,
/// duplicate JSON object keys at any depth, an envelope that is neither a typed result nor a typed
/// error (or is both), a page over the registered row bound, a signature that is not base58 or
/// does not decode to 64 bytes, a repeated signature, a strictly increasing slot step, and a row
/// whose commitment claim is not `finalized`.
///
/// A well-formed typed JSON-RPC error does **not** always reach
/// [`SolanaJsonRpcOutcome::ProviderRefusal`]. Its message is also sanitation-bounded, so a
/// refusal whose message is empty, longer than the local 512-byte bound, or carrying a control
/// character is refused as
/// [`SolanaJsonRpcConformanceError::RefusalMessageNotBounded`] rather than returned, and a
/// refusal whose auxiliary `data` serializes to more than the local 1024-byte bound is refused as
/// [`SolanaJsonRpcConformanceError::RefusalDataNotBounded`]. Both bounds refuse the whole body
/// rather than retaining a truncated provider claim.
pub fn read_solana_json_rpc_body(
    body: &[u8],
    max_rows: u16,
) -> Result<SolanaJsonRpcOutcome, SolanaJsonRpcConformanceError> {
    // First act of all, before any allocation, copy, decode, or parse. Everything below this line
    // costs work proportional to the body, so the length is what bounds the whole reader.
    if body.len() > INGEST_MAX_RESPONSE_BYTES {
        return Err(SolanaJsonRpcConformanceError::ResponseExceedsIngressCeiling);
    }
    if !(SOLANA_SIGNATURES_MIN_ROWS..=SOLANA_SIGNATURES_MAX_ROWS).contains(&max_rows) {
        return Err(SolanaJsonRpcConformanceError::RegisteredRowBoundOutOfRange);
    }
    if body.is_empty() {
        return Err(SolanaJsonRpcConformanceError::EmptyBody);
    }
    let text = std::str::from_utf8(body).map_err(|_| SolanaJsonRpcConformanceError::NotUtf8)?;

    let mut reader = serde_json::Deserializer::from_str(text);
    let value = Value::deserialize(&mut reader)
        .map_err(|_| SolanaJsonRpcConformanceError::MalformedJson)?;
    reader
        .end()
        .map_err(|_| SolanaJsonRpcConformanceError::TrailingBytes)?;

    // The document is now known to be exactly one well-formed JSON value, so the only refusal this
    // second pass can raise is this module's own explicit duplicate-key refusal.
    let mut scanner = serde_json::Deserializer::from_str(text);
    DuplicateFreeJson::deserialize(&mut scanner)
        .map_err(|_| SolanaJsonRpcConformanceError::DuplicateJsonKey)?;

    classify_envelope(value, max_rows)
}

/// Read one bounded public-Solana response frame into unverified raw conformance data.
///
/// This is the promoted frame-envelope half of the former runner-internal `validate_response`. It
/// checks only the frame envelope this crate itself produced and then defers to
/// [`read_solana_json_rpc_body`]. It reads no budget and consults no clock. It does read the
/// frame's own `received_at` receipt stamp, but only to require that it is a positive Unix-millis
/// value; nothing here compares that stamp against a current time, and elapsed time is not a wire
/// fact and is not admitted at all.
///
/// # Errors
///
/// Refuses a frame whose envelope is not the exact bounded declaration, and propagates every
/// body refusal from [`read_solana_json_rpc_body`].
pub fn read_solana_json_rpc_frame(
    frame: &RawSourceFrame,
    max_rows: u16,
) -> Result<SolanaJsonRpcOutcome, SolanaJsonRpcConformanceError> {
    if frame.source != SourceId::SolanaPublicHttp
        || frame.contract_version != crate::ADAPTER_CONTRACT_VERSION
        || frame.transport != Transport::Http
        || frame.stream_class != StreamClass::Backfill
        || frame.direction != FrameDirection::Inbound
        || frame.content_type != ContentType::Json
        || frame.received_at.0 <= 0
        || frame.connection_epoch != 1
        || frame.sequence != 1
        || frame.http_status != Some(200)
        || !solana_safe_headers_are_bounded(&frame.safe_headers)
    {
        return Err(SolanaJsonRpcConformanceError::FrameEnvelopeMismatch);
    }
    read_solana_json_rpc_body(&frame.body, max_rows)
}

/// Report whether a retained safe-header set is within the bounded allowance.
///
/// Only the four rate-limit response headers are admitted, each at most once after ASCII
/// lowercasing, each value at most 256 bytes (`MAX_SAFE_HEADER_VALUE_BYTES`), and none carrying a
/// control character. Name matching folds ASCII case only; no other Unicode case folding applies.
///
/// The leading length comparison is implied by the two checks that follow it — only four names are
/// admitted and none may repeat, so no admissible set can exceed four headers — and is kept only
/// to state the bound where a reader looks for it. It is not the check that refuses an oversized
/// set, and deleting it would not widen what this function accepts.
#[must_use]
pub fn solana_safe_headers_are_bounded(headers: &[SafeHeader]) -> bool {
    const ALLOWED: &[&str] = &[
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    ];
    let mut names = BTreeSet::new();
    headers.len() <= ALLOWED.len()
        && headers.iter().all(|header| {
            let name = header.name.to_ascii_lowercase();
            ALLOWED.contains(&name.as_str())
                && names.insert(name)
                && header.value.len() <= MAX_SAFE_HEADER_VALUE_BYTES
                && !header.value.chars().any(char::is_control)
        })
}

// ---------------------------------------------------------------------------------------------
// Closed wire shapes
// ---------------------------------------------------------------------------------------------

/// Closed shape of a JSON-RPC result response for this method.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct JsonRpcResponse {
    pub(crate) jsonrpc: String,
    pub(crate) id: u64,
    pub(crate) result: Vec<SignatureRow>,
}

/// Closed shape of a typed JSON-RPC error response for this method.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct JsonRpcErrorResponse {
    pub(crate) jsonrpc: String,
    pub(crate) id: u64,
    pub(crate) error: JsonRpcErrorObject,
}

/// Closed shape of the typed `rpcError` object the frozen schema declares.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct JsonRpcErrorObject {
    pub(crate) code: i64,
    pub(crate) message: String,
    #[serde(default)]
    pub(crate) data: Option<Value>,
}

/// Closed shape of one row. Every nullable member must still be *present*.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct SignatureRow {
    pub(crate) signature: String,
    pub(crate) slot: u64,
    pub(crate) err: Value,
    #[serde(deserialize_with = "required_nullable")]
    pub(crate) memo: RequiredNullable<String>,
    #[serde(deserialize_with = "required_nullable")]
    pub(crate) block_time: RequiredNullable<i64>,
    #[serde(deserialize_with = "required_nullable")]
    pub(crate) confirmation_status: RequiredNullable<String>,
}

/// A member that must be present on the wire but whose value may be JSON null.
///
/// This is deliberately not a bare `Option` field and deliberately not a `serde(transparent)`
/// newtype over one. Serde resolves a *missing* field whose decoder reaches `deserialize_option`
/// to `None`, so both spellings silently accept an absent member — the member is then not
/// required at all. Routing every such field through [`required_nullable`] makes serde emit a hard
/// missing-field refusal instead, which is what distinguishes "the provider said null" from "the
/// provider did not answer this member".
#[derive(Debug)]
pub(crate) struct RequiredNullable<T>(pub(crate) Option<T>);

/// Decode a member that must be present on the wire but whose value may be JSON null.
///
/// # Errors
///
/// Returns the deserializer's error when the member is absent or is neither null nor a `T`.
pub(crate) fn required_nullable<'de, D, T>(deserializer: D) -> Result<RequiredNullable<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer).map(RequiredNullable)
}

fn classify_envelope(
    value: Value,
    max_rows: u16,
) -> Result<SolanaJsonRpcOutcome, SolanaJsonRpcConformanceError> {
    let Value::Object(members) = &value else {
        return Err(SolanaJsonRpcConformanceError::EnvelopeMismatch);
    };
    match (
        members.contains_key("result"),
        members.contains_key("error"),
    ) {
        (true, false) => {
            let response: JsonRpcResponse = serde_json::from_value(value)
                .map_err(|_| SolanaJsonRpcConformanceError::EnvelopeMismatch)?;
            validate_json_rpc_page(response, max_rows).map(SolanaJsonRpcOutcome::Page)
        }
        (false, true) => {
            let response: JsonRpcErrorResponse = serde_json::from_value(value)
                .map_err(|_| SolanaJsonRpcConformanceError::EnvelopeMismatch)?;
            validate_json_rpc_refusal(response).map(SolanaJsonRpcOutcome::ProviderRefusal)
        }
        (true, true) => Err(SolanaJsonRpcConformanceError::ResultAndErrorBothPresent),
        (false, false) => Err(SolanaJsonRpcConformanceError::NeitherResultNorError),
    }
}

fn validate_json_rpc_page(
    response: JsonRpcResponse,
    max_rows: u16,
) -> Result<RawSignaturePage, SolanaJsonRpcConformanceError> {
    if response.jsonrpc != SOLANA_JSON_RPC_VERSION || response.id != SOLANA_JSON_RPC_ID {
        return Err(SolanaJsonRpcConformanceError::EnvelopeMismatch);
    }
    if response.result.len() > usize::from(max_rows) {
        return Err(SolanaJsonRpcConformanceError::RowLimitExceeded);
    }
    let mut prior_slot: Option<u64> = None;
    let mut signatures: BTreeSet<String> = BTreeSet::new();
    let mut rows = Vec::with_capacity(response.result.len());
    for row in response.result {
        let decoded = bs58::decode(&row.signature)
            .into_vec()
            .map_err(|_| SolanaJsonRpcConformanceError::SignatureNotBase58)?;
        if decoded.len() != SIGNATURE_BYTES {
            return Err(SolanaJsonRpcConformanceError::SignatureWrongLength);
        }
        if !signatures.insert(row.signature.clone()) {
            return Err(SolanaJsonRpcConformanceError::DuplicateSignature);
        }
        // Newest-first is enforced as "slots never increase". Equal adjacent slots are legal.
        if prior_slot.is_some_and(|prior| row.slot > prior) {
            return Err(SolanaJsonRpcConformanceError::OrderingNotNewestFirst);
        }
        if row.confirmation_status.0.as_deref() != Some(SOLANA_SIGNATURES_COMMITMENT) {
            return Err(SolanaJsonRpcConformanceError::ConfirmationStatusNotFinalized);
        }
        prior_slot = Some(row.slot);
        rows.push(RawSignatureRow {
            signature: row.signature,
            slot: row.slot,
            err: row.err,
            memo: row.memo.0,
            block_time: row.block_time.0,
            confirmation_status: row.confirmation_status.0,
        });
    }
    Ok(RawSignaturePage { rows })
}

fn validate_json_rpc_refusal(
    response: JsonRpcErrorResponse,
) -> Result<JsonRpcRefusal, SolanaJsonRpcConformanceError> {
    if response.jsonrpc != SOLANA_JSON_RPC_VERSION || response.id != SOLANA_JSON_RPC_ID {
        return Err(SolanaJsonRpcConformanceError::EnvelopeMismatch);
    }
    let message = response.error.message;
    if message.is_empty()
        || message.len() > MAX_REFUSAL_MESSAGE_BYTES
        || message.chars().any(char::is_control)
    {
        return Err(SolanaJsonRpcConformanceError::RefusalMessageNotBounded);
    }
    let data = match response.error.data {
        None => None,
        Some(data) => {
            // The encode arm cannot fail for a `Value` that came from a successful parse: every
            // such value is representable. It refuses rather than admits anyway, so an encoder
            // failure could never be the reason an unmeasured value was retained.
            let encoded = serde_json::to_vec(&data)
                .map_err(|_| SolanaJsonRpcConformanceError::RefusalDataNotBounded)?;
            if encoded.len() > MAX_REFUSAL_DATA_BYTES {
                return Err(SolanaJsonRpcConformanceError::RefusalDataNotBounded);
            }
            Some(data)
        }
    };
    Ok(JsonRpcRefusal {
        code: response.error.code,
        message,
        data,
    })
}

// ---------------------------------------------------------------------------------------------
// Duplicate-key scanner
// ---------------------------------------------------------------------------------------------

/// A whole-document walk that refuses a repeated object key at any depth.
///
/// `serde_json` silently keeps the last value for a repeated key when the target is a
/// `serde_json::Value`, so duplicate refusal cannot be delegated to the typed decode. This scan
/// carries no data: it exists only to raise the refusal.
struct DuplicateFreeJson;

impl<'de> Deserialize<'de> for DuplicateFreeJson {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_any(DuplicateFreeJsonVisitor)
    }
}

struct DuplicateFreeJsonVisitor;

impl<'de> Visitor<'de> for DuplicateFreeJsonVisitor {
    type Value = DuplicateFreeJson;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON document with no duplicate object key")
    }

    fn visit_bool<E>(self, _value: bool) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_i64<E>(self, _value: i64) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_i128<E>(self, _value: i128) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_u64<E>(self, _value: u64) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_u128<E>(self, _value: u128) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_str<E>(self, _value: &str) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_string<E>(self, _value: String) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }
    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(DuplicateFreeJson)
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_any(Self)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        while sequence.next_element::<DuplicateFreeJson>()?.is_some() {}
        Ok(DuplicateFreeJson)
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut names = BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            if !names.insert(key) {
                return Err(de::Error::custom("duplicate JSON object key"));
            }
            map.next_value::<DuplicateFreeJson>()?;
        }
        Ok(DuplicateFreeJson)
    }
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;

    use super::*;
    use crate::UnixMillis;

    const WALLET: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";

    /// The exact canonical request body for [`WALLET`] with a two-row bound.
    const CANONICAL_TWO_ROW_REQUEST: &str = r#"{"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":["BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh",{"commitment":"finalized","limit":2}]}"#;

    /// The exact canonical request body for [`WALLET`] at the registered 100-row maximum, which is
    /// the widest `limit` the schema admits and therefore the longest body this wallet produces.
    const CANONICAL_HUNDRED_ROW_REQUEST: &str = r#"{"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":["BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh",{"commitment":"finalized","limit":100}]}"#;

    /// A fixed 88-character base58 signature literal, written out here rather than encoded from
    /// [`SIGNATURE_BYTES`]. It is the same signature-shaped fixture the wallet-source fixtures in
    /// this tree carry (`fixtures/wallet-source/finalized_pump_pumpswap_exact.json`); nothing here
    /// claims it was captured from mainnet, only that it is a fixed literal of the exact width a
    /// Solana ed25519 transaction signature has, which is what lets it pin the constant.
    const FIXED_SIGNATURE: &str =
        "5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv";

    fn signature(byte: u8) -> String {
        bs58::encode([byte; SIGNATURE_BYTES]).into_string()
    }

    fn two_row_body(slots: [u64; 2]) -> Vec<u8> {
        rows_body(&[(signature(1), slots[0]), (signature(2), slots[1])])
    }

    fn rows_body(rows: &[(String, u64)]) -> Vec<u8> {
        let rendered: Vec<_> = rows
            .iter()
            .map(|(signature, slot)| {
                serde_json::json!({
                    "signature": signature,
                    "slot": slot,
                    "err": Value::Null,
                    "memo": Value::Null,
                    "blockTime": 1,
                    "confirmationStatus": "finalized"
                })
            })
            .collect();
        serde_json::to_vec(&serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": rendered
        }))
        .expect("response JSON")
    }

    fn frame_with(body: Vec<u8>) -> RawSourceFrame {
        RawSourceFrame {
            contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
            source: SourceId::SolanaPublicHttp,
            transport: Transport::Http,
            stream_class: StreamClass::Backfill,
            direction: FrameDirection::Inbound,
            content_type: ContentType::Json,
            received_at: UnixMillis(1_000),
            connection_epoch: 1,
            sequence: 1,
            http_status: Some(200),
            safe_headers: Vec::new(),
            body: Bytes::from(body),
        }
    }

    fn page_of(body: &[u8], max_rows: u16) -> RawSignaturePage {
        match read_solana_json_rpc_body(body, max_rows).expect("conforming page") {
            SolanaJsonRpcOutcome::Page(page) => page,
            SolanaJsonRpcOutcome::ProviderRefusal(_) => {
                panic!("a provider refusal is not a page")
            }
        }
    }

    // -----------------------------------------------------------------------------------------
    // Canonical request construction
    // -----------------------------------------------------------------------------------------

    #[test]
    fn canonical_request_bytes_are_exact_and_byte_identical_across_calls() {
        let first = canonical_solana_signatures_request(WALLET, 2).expect("canonical request");
        let second = canonical_solana_signatures_request(WALLET, 2).expect("canonical request");
        assert_eq!(first.body, CANONICAL_TWO_ROW_REQUEST.as_bytes());
        assert_eq!(first.byte_len, 154);
        assert_eq!(first.byte_len, first.body.len());
        assert_eq!(first, second);
    }

    /// The exact byte length of the longest canonical request body any admissible input can
    /// produce. The test this replaces asserted only `byte_len <= SOLANA_JSON_RPC_MAX_REQUEST_BYTES`,
    /// which the `.expect` on the preceding line already implied — deleting the
    /// `RequestExceedsRegisteredBound` guard left it green. A number is what makes a widening
    /// visible.
    ///
    /// The body is longest when the address is longest and `limit` is widest. `limit` is widest at
    /// the registered 100-row maximum, and a 32-byte address base58-encodes to at most 44
    /// characters, a maximum the all-`0xFF` address realises. So 156 bytes is the ceiling over
    /// every input this constructor accepts, 3940 bytes clear of the registered 4096-byte bound.
    #[test]
    fn the_longest_admissible_canonical_request_body_is_exactly_156_bytes() {
        let widest_address = bs58::encode([0xFF_u8; ADDRESS_BYTES]).into_string();
        assert_eq!(widest_address.len(), 44);
        let widest =
            canonical_solana_signatures_request(&widest_address, SOLANA_SIGNATURES_MAX_ROWS)
                .expect("canonical request");
        assert_eq!(widest.byte_len, 156);
        assert_eq!(widest.body.len(), 156);
        assert_eq!(SOLANA_JSON_RPC_MAX_REQUEST_BYTES - widest.byte_len, 3_940);

        let wallet = canonical_solana_signatures_request(WALLET, SOLANA_SIGNATURES_MAX_ROWS)
            .expect("canonical request");
        assert_eq!(wallet.body, CANONICAL_HUNDRED_ROW_REQUEST.as_bytes());
        assert_eq!(wallet.byte_len, 156);
        assert_eq!(
            wallet.byte_len - CANONICAL_TWO_ROW_REQUEST.len(),
            2,
            "the only variable-width member between the two bodies is the two extra `limit` digits"
        );
    }

    #[test]
    fn registered_request_bound_matches_the_canonical_source_registry() {
        let admitted = crate::contract_port::admit_runtime_method(
            joshi_source_registry::PUBLIC_SOLANA_MAINNET_SOURCE_ID,
            joshi_source_registry::PUBLIC_SOLANA_SIGNATURES_METHOD_KEY,
        )
        .expect("admitted method");
        assert_eq!(
            u64::try_from(SOLANA_JSON_RPC_MAX_REQUEST_BYTES).expect("bound fits"),
            admitted.method.max_request_bytes
        );
    }

    #[test]
    fn canonical_request_refuses_a_bad_address_and_out_of_range_row_bounds() {
        assert_eq!(
            canonical_solana_signatures_request("not a base58 address!", 2),
            Err(SolanaRequestError::AddressNotBase58)
        );
        let too_short = bs58::encode([7_u8; 31]).into_string();
        assert_eq!(
            canonical_solana_signatures_request(&too_short, 2),
            Err(SolanaRequestError::AddressNotThirtyTwoBytes)
        );
        let too_long = bs58::encode([7_u8; 33]).into_string();
        assert_eq!(
            canonical_solana_signatures_request(&too_long, 2),
            Err(SolanaRequestError::AddressNotThirtyTwoBytes)
        );
        assert_eq!(
            canonical_solana_signatures_request(WALLET, 0),
            Err(SolanaRequestError::RowBoundOutOfRange)
        );
        assert_eq!(
            canonical_solana_signatures_request(WALLET, 101),
            Err(SolanaRequestError::RowBoundOutOfRange)
        );
    }

    /// The length check runs before the decode, so an over-long argument is refused on its
    /// length rather than decoded first. The needle is a value that is **not** base58 and is over
    /// the width: with the length check in place it is refused as not decoding to 32 bytes, and
    /// with the check deleted the same value reaches `bs58` and comes back as not base58. One
    /// assertion therefore distinguishes the two orderings, without depending on how long a
    /// quadratic decode of a large input takes.
    #[test]
    fn an_over_long_address_is_refused_on_length_before_it_is_decoded() {
        let widest = bs58::encode([0xFF_u8; ADDRESS_BYTES]).into_string();
        assert_eq!(widest.len(), MAX_ADDRESS_BASE58_CHARS);
        assert_eq!(WALLET.len(), MAX_ADDRESS_BASE58_CHARS);
        canonical_solana_signatures_request(&widest, 2)
            .expect("the widest 32-byte address is admitted");

        let over_long_not_base58 = "!".repeat(MAX_ADDRESS_BASE58_CHARS + 1);
        assert_eq!(
            canonical_solana_signatures_request(&over_long_not_base58, 2),
            Err(SolanaRequestError::AddressNotThirtyTwoBytes),
            "the length is what refuses this, not the alphabet"
        );
        assert_eq!(
            canonical_solana_signatures_request("!", 2),
            Err(SolanaRequestError::AddressNotBase58),
            "the control: inside the width, the alphabet is still what refuses"
        );

        // One base58 character over the width, and a value far past it. Neither is decoded.
        let one_over = "1".repeat(MAX_ADDRESS_BASE58_CHARS + 1);
        assert_eq!(
            canonical_solana_signatures_request(&one_over, 2),
            Err(SolanaRequestError::AddressNotThirtyTwoBytes)
        );
        let far_over = "z".repeat(4 * 1_024);
        assert_eq!(
            canonical_solana_signatures_request(&far_over, 2),
            Err(SolanaRequestError::AddressNotThirtyTwoBytes)
        );

        // A multi-byte character makes the value wider in bytes than in characters, which is what
        // the byte comparison is for: it cannot be an ASCII base58 address either way.
        let wide_chars = "\u{e9}".repeat(MAX_ADDRESS_BASE58_CHARS);
        assert_eq!(wide_chars.chars().count(), MAX_ADDRESS_BASE58_CHARS);
        assert!(wide_chars.len() > MAX_ADDRESS_BASE58_CHARS);
        assert_eq!(
            canonical_solana_signatures_request(&wide_chars, 2),
            Err(SolanaRequestError::AddressNotThirtyTwoBytes)
        );
    }

    // -----------------------------------------------------------------------------------------
    // Hostile-body refusals
    // -----------------------------------------------------------------------------------------

    /// The "before parsing" half of the name is what the non-JSON body pins: were the row-bound
    /// check moved after the parse, these bytes would come back as `MalformedJson` instead. The
    /// control asserts exactly that, so the difference between the two orderings is observable
    /// here rather than assumed.
    #[test]
    fn an_out_of_range_registered_row_bound_is_refused_before_parsing() {
        let not_json: &[u8] = b"not json at all";
        for max_rows in [0, 101, u16::MAX] {
            assert_eq!(
                read_solana_json_rpc_body(not_json, max_rows),
                Err(SolanaJsonRpcConformanceError::RegisteredRowBoundOutOfRange)
            );
        }
        assert_eq!(
            read_solana_json_rpc_body(not_json, 2),
            Err(SolanaJsonRpcConformanceError::MalformedJson),
            "the control: the same bytes do reach the parser once the row bound is in range"
        );

        // The check also precedes the UTF-8 decode and the empty-body refusal, so neither of those
        // can stand in for it.
        assert_eq!(
            read_solana_json_rpc_body(&[0x7b, 0xff, 0x7d], 0),
            Err(SolanaJsonRpcConformanceError::RegisteredRowBoundOutOfRange)
        );
        assert_eq!(
            read_solana_json_rpc_body(b"", 0),
            Err(SolanaJsonRpcConformanceError::RegisteredRowBoundOutOfRange)
        );

        // A body that would otherwise be read normally is refused on the same ground.
        assert_eq!(
            read_solana_json_rpc_body(&two_row_body([10, 9]), 101),
            Err(SolanaJsonRpcConformanceError::RegisteredRowBoundOutOfRange)
        );
    }

    #[test]
    fn an_empty_body_is_refused() {
        assert_eq!(
            read_solana_json_rpc_body(b"", 2),
            Err(SolanaJsonRpcConformanceError::EmptyBody)
        );
    }

    #[test]
    fn a_non_utf8_body_is_refused() {
        assert_eq!(
            read_solana_json_rpc_body(&[0x7b, 0xff, 0x7d], 2),
            Err(SolanaJsonRpcConformanceError::NotUtf8)
        );
    }

    #[test]
    fn a_malformed_json_body_is_refused() {
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"2.0","#, 2),
            Err(SolanaJsonRpcConformanceError::MalformedJson)
        );
    }

    #[test]
    fn trailing_bytes_after_the_json_value_are_refused() {
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"2.0","id":1,"result":[]} {"id":1}"#, 2),
            Err(SolanaJsonRpcConformanceError::TrailingBytes)
        );
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"2.0","id":1,"result":[]}junk"#, 2),
            Err(SolanaJsonRpcConformanceError::TrailingBytes)
        );
    }

    #[test]
    fn duplicate_json_object_keys_are_refused_at_the_root_and_inside_a_row() {
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"2.0","id":1,"id":1,"result":[]}"#, 2),
            Err(SolanaJsonRpcConformanceError::DuplicateJsonKey)
        );
        let nested = format!(
            r#"{{"jsonrpc":"2.0","id":1,"result":[{{"signature":"{}","slot":10,"slot":10,"err":null,"memo":null,"blockTime":1,"confirmationStatus":"finalized"}}]}}"#,
            signature(1)
        );
        assert_eq!(
            read_solana_json_rpc_body(nested.as_bytes(), 2),
            Err(SolanaJsonRpcConformanceError::DuplicateJsonKey)
        );
    }

    #[test]
    fn an_unknown_or_missing_envelope_member_is_refused() {
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"2.0","id":1,"result":[],"context":{}}"#, 2),
            Err(SolanaJsonRpcConformanceError::EnvelopeMismatch)
        );
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"2.0","id":2,"result":[]}"#, 2),
            Err(SolanaJsonRpcConformanceError::EnvelopeMismatch)
        );
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"1.0","id":1,"result":[]}"#, 2),
            Err(SolanaJsonRpcConformanceError::EnvelopeMismatch)
        );
        assert_eq!(
            read_solana_json_rpc_body(b"[]", 2),
            Err(SolanaJsonRpcConformanceError::EnvelopeMismatch)
        );
        assert_eq!(
            read_solana_json_rpc_body(br#"{"jsonrpc":"2.0","id":1}"#, 2),
            Err(SolanaJsonRpcConformanceError::NeitherResultNorError)
        );
    }

    /// The row shape is closed, and `deny_unknown_fields` is the only thing that closes it: the
    /// duplicate-key scan does not fire on a *new* key, and nothing else inspects a row's member
    /// set. Without it a provider could attach arbitrary members to a retained row.
    #[test]
    fn an_unknown_member_on_a_row_is_refused() {
        fn row_with(extra: Option<(&str, Value)>) -> Vec<u8> {
            let mut row = serde_json::json!({
                "signature": signature(1),
                "slot": 10,
                "err": Value::Null,
                "memo": Value::Null,
                "blockTime": 1,
                "confirmationStatus": "finalized"
            });
            if let Some((name, value)) = extra {
                row.as_object_mut()
                    .expect("row object")
                    .insert(name.to_owned(), value);
            }
            serde_json::to_vec(&serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "result": [row]
            }))
            .expect("body")
        }

        // The control: the same row without the extra member is a conforming one-row page.
        assert_eq!(page_of(&row_with(None), 2).rows.len(), 1);

        for (name, value) in [
            ("blockHeight", serde_json::json!(1)),
            ("confirmation_status", serde_json::json!("finalized")),
            ("signature ", serde_json::json!("padded key")),
        ] {
            assert_eq!(
                read_solana_json_rpc_body(&row_with(Some((name, value))), 2),
                Err(SolanaJsonRpcConformanceError::EnvelopeMismatch),
                "a row carrying {name} must be refused"
            );
        }
    }

    /// The same closure on the typed-error envelope. The `result` envelope already has this pin
    /// in `an_unknown_or_missing_envelope_member_is_refused`; the error envelope is a separate
    /// struct with its own `deny_unknown_fields`, and had none.
    #[test]
    fn an_unknown_member_on_the_error_envelope_is_refused() {
        assert_eq!(
            read_solana_json_rpc_body(
                br#"{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"no"},"result":null}"#,
                2
            ),
            Err(SolanaJsonRpcConformanceError::ResultAndErrorBothPresent),
            "a null result is still a result member, and that is refused before the shape is read"
        );
        assert_eq!(
            read_solana_json_rpc_body(
                br#"{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"no"},"context":{}}"#,
                2
            ),
            Err(SolanaJsonRpcConformanceError::EnvelopeMismatch)
        );
        // The control: the same envelope without the extra member is a typed provider refusal.
        assert!(matches!(
            read_solana_json_rpc_body(
                br#"{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"no"}}"#,
                2
            ),
            Ok(SolanaJsonRpcOutcome::ProviderRefusal(_))
        ));
    }

    /// A member the schema declares as nullable must still be *present*. Serde resolves a missing
    /// option-shaped field to `None`, so absence would otherwise be indistinguishable from an
    /// explicit provider null.
    #[test]
    fn a_row_missing_a_required_nullable_member_is_refused() {
        for absent in ["memo", "blockTime", "confirmationStatus", "err"] {
            let mut row = serde_json::json!({
                "signature": signature(1),
                "slot": 10,
                "err": Value::Null,
                "memo": Value::Null,
                "blockTime": 1,
                "confirmationStatus": "finalized"
            });
            row.as_object_mut().expect("row object").remove(absent);
            let body = serde_json::to_vec(&serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "result": [row]
            }))
            .expect("body");
            assert_eq!(
                read_solana_json_rpc_body(&body, 2),
                Err(SolanaJsonRpcConformanceError::EnvelopeMismatch),
                "a row missing {absent} must be refused"
            );
        }
    }

    #[test]
    fn a_row_member_that_is_explicitly_null_is_accepted_and_retained_as_null() {
        let body = serde_json::to_vec(&serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": [{
                "signature": signature(1),
                "slot": 10,
                "err": Value::Null,
                "memo": Value::Null,
                "blockTime": Value::Null,
                "confirmationStatus": "finalized"
            }]
        }))
        .expect("body");
        let page = page_of(&body, 2);
        assert_eq!(page.rows[0].memo, None);
        assert_eq!(page.rows[0].block_time, None);
    }

    #[test]
    fn a_page_over_the_registered_row_bound_is_refused() {
        assert_eq!(
            read_solana_json_rpc_body(&two_row_body([10, 9]), 1),
            Err(SolanaJsonRpcConformanceError::RowLimitExceeded)
        );
    }

    /// [`SIGNATURE_BYTES`] is what every accept-side fixture in this module encodes its base58
    /// from, so those fixtures move with the constant and cannot pin it; the reject-side test
    /// below uses hardcoded 63- and 65-byte arrays, which only pin the neighbours. This test
    /// decodes a fixed literal instead: 64 appears here as a number, and the reader must accept a
    /// row carrying that exact literal, so changing the constant in either direction fails here.
    #[test]
    fn the_admitted_signature_length_is_pinned_to_a_fixed_signature_literal() {
        assert_eq!(FIXED_SIGNATURE.len(), 88);
        let decoded = bs58::decode(FIXED_SIGNATURE)
            .into_vec()
            .expect("the fixed signature literal is base58");
        assert_eq!(decoded.len(), 64);
        assert_eq!(SIGNATURE_BYTES, 64);

        let page = page_of(&rows_body(&[(FIXED_SIGNATURE.to_owned(), 10)]), 2);
        assert_eq!(page.rows.len(), 1);
        assert_eq!(page.rows[0].signature, FIXED_SIGNATURE);
    }

    #[test]
    fn a_signature_that_decodes_to_the_wrong_length_is_refused() {
        let short = bs58::encode([3_u8; 63]).into_string();
        assert_eq!(
            read_solana_json_rpc_body(&rows_body(&[(short, 10)]), 2),
            Err(SolanaJsonRpcConformanceError::SignatureWrongLength)
        );
        let long = bs58::encode([3_u8; 65]).into_string();
        assert_eq!(
            read_solana_json_rpc_body(&rows_body(&[(long, 10)]), 2),
            Err(SolanaJsonRpcConformanceError::SignatureWrongLength)
        );
    }

    #[test]
    fn a_signature_outside_the_base58_alphabet_is_refused() {
        assert_eq!(
            read_solana_json_rpc_body(&rows_body(&[("not base58!".to_owned(), 10)]), 2),
            Err(SolanaJsonRpcConformanceError::SignatureNotBase58)
        );
    }

    #[test]
    fn a_repeated_signature_inside_one_page_is_refused() {
        let repeated = rows_body(&[(signature(1), 10), (signature(1), 10)]);
        assert_eq!(
            read_solana_json_rpc_body(&repeated, 2),
            Err(SolanaJsonRpcConformanceError::DuplicateSignature)
        );
    }

    /// The enforced ordering rule is "slots never increase". Equal adjacent slots are legal
    /// because one slot can carry several signatures for the same address; a strictly increasing
    /// step contradicts the schema's declared newest-first ordering and is refused.
    #[test]
    fn equal_slots_are_legal_and_a_strictly_increasing_slot_step_is_refused() {
        let equal = page_of(&two_row_body([11, 11]), 2);
        assert_eq!(equal.rows.len(), 2);
        assert_eq!(equal.rows[0].slot, 11);
        assert_eq!(equal.rows[1].slot, 11);

        let decreasing = page_of(&two_row_body([11, 10]), 2);
        assert_eq!(decreasing.rows[1].slot, 10);

        assert_eq!(
            read_solana_json_rpc_body(&two_row_body([9, 10]), 2),
            Err(SolanaJsonRpcConformanceError::OrderingNotNewestFirst)
        );
    }

    #[test]
    fn a_row_without_the_registered_finalized_claim_is_refused() {
        let mut value: Value =
            serde_json::from_slice(&two_row_body([10, 9])).expect("scripted body");
        value["result"][0]["confirmationStatus"] = Value::String("confirmed".to_owned());
        let confirmed = serde_json::to_vec(&value).expect("body");
        assert_eq!(
            read_solana_json_rpc_body(&confirmed, 2),
            Err(SolanaJsonRpcConformanceError::ConfirmationStatusNotFinalized)
        );

        value["result"][0]["confirmationStatus"] = Value::Null;
        let null_status = serde_json::to_vec(&value).expect("body");
        assert_eq!(
            read_solana_json_rpc_body(&null_status, 2),
            Err(SolanaJsonRpcConformanceError::ConfirmationStatusNotFinalized)
        );
    }

    // -----------------------------------------------------------------------------------------
    // Explicit non-facts
    // -----------------------------------------------------------------------------------------

    /// A zero-row page is exactly one provider response that listed nothing. It NEVER means the
    /// wallet has no history and it NEVER establishes that any window was observed. The frozen
    /// schema says `"absence":"never_proves_absence"` and this reader derives nothing from it.
    #[test]
    fn an_empty_result_array_is_a_zero_row_page_and_never_absence_or_coverage() {
        let page = page_of(br#"{"jsonrpc":"2.0","id":1,"result":[]}"#, 2);
        assert!(page.rows.is_empty());
    }

    /// `finalized` here is the provider's own word, retained verbatim because the registered
    /// method declares that commitment. Nothing in this crate checks it against a chain, so it is
    /// NOT a JOSHI finality fact and no caller may treat it as one.
    #[test]
    fn a_finalized_confirmation_status_is_a_retained_provider_claim_not_a_joshi_finality_fact() {
        let page = page_of(&two_row_body([10, 9]), 2);
        assert_eq!(
            page.rows[0].confirmation_status.as_deref(),
            Some(SOLANA_SIGNATURES_COMMITMENT)
        );
        assert_eq!(page.rows[0].err, Value::Null);
        assert_eq!(page.rows[0].block_time, Some(1));
        assert_eq!(page.rows[0].memo, None);
    }

    // -----------------------------------------------------------------------------------------
    // Typed provider refusal
    // -----------------------------------------------------------------------------------------

    #[test]
    fn a_well_formed_rpc_error_is_a_typed_provider_refusal_and_never_a_page() {
        let body = br#"{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Invalid params: limit out of range"}}"#;
        match read_solana_json_rpc_body(body, 2).expect("typed refusal") {
            SolanaJsonRpcOutcome::ProviderRefusal(refusal) => {
                assert_eq!(refusal.code, -32_602);
                assert_eq!(refusal.message, "Invalid params: limit out of range");
                assert_eq!(refusal.data, None);
            }
            SolanaJsonRpcOutcome::Page(_) => panic!("a typed refusal must never be a page"),
        }
    }

    /// The refusal branch binds the envelope to *this* request exactly as the page branch does.
    /// Both halves are load bearing on their own: without the version check a refusal spoken in
    /// another protocol version would be accepted, and without the id check a refusal answering a
    /// different request would be accepted as the refusal of this one. This path issues one
    /// request, with `id` fixed at 1, so an answer carrying any other id is an answer to
    /// something else.
    #[test]
    fn a_refusal_that_does_not_bind_this_requests_envelope_is_refused() {
        fn refusal(jsonrpc: &str, id: i64) -> Vec<u8> {
            serde_json::to_vec(&serde_json::json!({
                "jsonrpc": jsonrpc,
                "id": id,
                "error": {"code": -32_005, "message": "rate limited"}
            }))
            .expect("refusal body")
        }

        // The control: the exact envelope is a typed provider refusal.
        assert!(matches!(
            read_solana_json_rpc_body(
                &refusal(
                    SOLANA_JSON_RPC_VERSION,
                    i64::try_from(SOLANA_JSON_RPC_ID).expect("id fits"),
                ),
                2
            ),
            Ok(SolanaJsonRpcOutcome::ProviderRefusal(_))
        ));

        for jsonrpc in ["1.0", "2", "2.0.0", ""] {
            assert_eq!(
                read_solana_json_rpc_body(&refusal(jsonrpc, 1), 2),
                Err(SolanaJsonRpcConformanceError::EnvelopeMismatch),
                "a refusal declaring JSON-RPC {jsonrpc} must not answer for this request"
            );
        }
        for id in [0, 2, 7, i64::MAX] {
            assert_eq!(
                read_solana_json_rpc_body(&refusal(SOLANA_JSON_RPC_VERSION, id), 2),
                Err(SolanaJsonRpcConformanceError::EnvelopeMismatch),
                "a refusal answering request {id} must not answer for request 1"
            );
        }
    }

    #[test]
    fn a_typed_provider_refusal_retains_auxiliary_data_verbatim() {
        let body = br#"{"jsonrpc":"2.0","id":1,"error":{"code":-32005,"message":"rate limited","data":{"retryAfterMs":250}}}"#;
        match read_solana_json_rpc_body(body, 2).expect("typed refusal") {
            SolanaJsonRpcOutcome::ProviderRefusal(refusal) => {
                assert_eq!(refusal.data, Some(serde_json::json!({"retryAfterMs": 250})));
            }
            SolanaJsonRpcOutcome::Page(_) => panic!("a typed refusal must never be a page"),
        }
    }

    /// `data` is provider-controlled content retained beside the message, and it carries the same
    /// kind of bound: an at-bound / one-byte-over pair, measured on the canonical serialization
    /// of the retained value. The test this replaces was named for a bound it never asserted.
    #[test]
    fn refusal_auxiliary_data_is_bounded_at_the_same_boundary_as_the_message() {
        fn refusal_body(data: &Value) -> Vec<u8> {
            serde_json::to_vec(&serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32_005, "message": "rate limited", "data": data}
            }))
            .expect("refusal body")
        }

        fn retained_data(body: &[u8]) -> Option<Value> {
            match read_solana_json_rpc_body(body, 2).expect("typed refusal") {
                SolanaJsonRpcOutcome::ProviderRefusal(refusal) => refusal.data,
                SolanaJsonRpcOutcome::Page(_) => panic!("a typed refusal must never be a page"),
            }
        }

        // A string of `n` payload bytes serializes to `n + 2` bytes: the two quotes.
        let at_bound = Value::String("d".repeat(MAX_REFUSAL_DATA_BYTES - 2));
        assert_eq!(
            serde_json::to_vec(&at_bound).expect("encoded").len(),
            MAX_REFUSAL_DATA_BYTES
        );
        assert_eq!(retained_data(&refusal_body(&at_bound)), Some(at_bound));

        let over_bound = Value::String("d".repeat(MAX_REFUSAL_DATA_BYTES - 1));
        assert_eq!(
            serde_json::to_vec(&over_bound).expect("encoded").len(),
            MAX_REFUSAL_DATA_BYTES + 1
        );
        assert_eq!(
            read_solana_json_rpc_body(&refusal_body(&over_bound), 2),
            Err(SolanaJsonRpcConformanceError::RefusalDataNotBounded)
        );

        // The bound is on the whole retained value, not on any one string inside it: a structure
        // built from short members is refused once the structure itself is over the bound.
        let wide: Value = (0..128)
            .map(|index| (format!("key{index:04}"), serde_json::json!(index)))
            .collect::<serde_json::Map<_, _>>()
            .into();
        assert!(serde_json::to_vec(&wide).expect("encoded").len() > MAX_REFUSAL_DATA_BYTES);
        assert_eq!(
            read_solana_json_rpc_body(&refusal_body(&wide), 2),
            Err(SolanaJsonRpcConformanceError::RefusalDataNotBounded)
        );

        // An absent `data` member is not a bound violation. Neither is an explicit null, which
        // serde resolves to the same `None`: unlike a row's nullable members, `data` is a genuine
        // option and this module does not distinguish "absent" from "null" for it.
        assert_eq!(
            retained_data(
                br#"{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"rate limited"}}"#
            ),
            None
        );
        assert_eq!(retained_data(&refusal_body(&Value::Null)), None);

        // The two sanitation bounds are separate refusals, not one: an over-long message on an
        // in-bound `data` is still refused as the message bound.
        let long_message = serde_json::to_vec(&serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32_005,
                "message": "m".repeat(MAX_REFUSAL_MESSAGE_BYTES + 1),
                "data": {"retryAfterMs": 250}
            }
        }))
        .expect("refusal body");
        assert_eq!(
            read_solana_json_rpc_body(&long_message, 2),
            Err(SolanaJsonRpcConformanceError::RefusalMessageNotBounded)
        );
    }

    /// Every other sanitation bound in this module carries an at-bound / one-byte-over pair. This
    /// is the pair for the refusal-message bound, which had neither: deleting the length clause,
    /// or widening it to 1 MiB, left the whole suite green.
    ///
    /// The bound counts **bytes**, not characters, so the multi-byte case is checked too: 256
    /// two-byte characters are at the bound and 257 are over it.
    #[test]
    fn a_refusal_message_at_the_sanitation_bound_is_retained_and_one_byte_over_is_refused() {
        fn refusal_body(message: &str) -> Vec<u8> {
            serde_json::to_vec(&serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32_005, "message": message}
            }))
            .expect("refusal body")
        }

        fn retained_message(body: &[u8]) -> String {
            match read_solana_json_rpc_body(body, 2).expect("typed refusal") {
                SolanaJsonRpcOutcome::ProviderRefusal(refusal) => refusal.message,
                SolanaJsonRpcOutcome::Page(_) => panic!("a typed refusal must never be a page"),
            }
        }

        // ASCII, so one character is exactly one byte and the length is exact, not approximate.
        let at_bound = "m".repeat(MAX_REFUSAL_MESSAGE_BYTES);
        assert_eq!(at_bound.len(), 512);
        assert_eq!(retained_message(&refusal_body(&at_bound)), at_bound);

        let over_bound = "m".repeat(MAX_REFUSAL_MESSAGE_BYTES + 1);
        assert_eq!(over_bound.len(), 513);
        assert_eq!(
            read_solana_json_rpc_body(&refusal_body(&over_bound), 2),
            Err(SolanaJsonRpcConformanceError::RefusalMessageNotBounded)
        );

        let wide_at_bound = "\u{e9}".repeat(MAX_REFUSAL_MESSAGE_BYTES / 2);
        assert_eq!(wide_at_bound.len(), 512);
        assert_eq!(wide_at_bound.chars().count(), 256);
        assert_eq!(
            retained_message(&refusal_body(&wide_at_bound)),
            wide_at_bound
        );

        let wide_over_bound = "\u{e9}".repeat(MAX_REFUSAL_MESSAGE_BYTES / 2 + 1);
        assert_eq!(wide_over_bound.len(), 514);
        assert_eq!(
            read_solana_json_rpc_body(&refusal_body(&wide_over_bound), 2),
            Err(SolanaJsonRpcConformanceError::RefusalMessageNotBounded)
        );
    }

    #[test]
    fn an_unbounded_or_malformed_refusal_is_not_a_typed_provider_refusal() {
        assert_eq!(
            read_solana_json_rpc_body(
                br#"{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":""}}"#,
                2
            ),
            Err(SolanaJsonRpcConformanceError::RefusalMessageNotBounded)
        );
        let control = format!(
            r#"{{"jsonrpc":"2.0","id":1,"error":{{"code":-1,"message":"{}"}}}}"#,
            "bad\\u0007message"
        );
        assert_eq!(
            read_solana_json_rpc_body(control.as_bytes(), 2),
            Err(SolanaJsonRpcConformanceError::RefusalMessageNotBounded)
        );
        assert_eq!(
            read_solana_json_rpc_body(
                br#"{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"no","extra":1}}"#,
                2
            ),
            Err(SolanaJsonRpcConformanceError::EnvelopeMismatch)
        );
        assert_eq!(
            read_solana_json_rpc_body(
                br#"{"jsonrpc":"2.0","id":1,"result":[],"error":{"code":-1,"message":"no"}}"#,
                2
            ),
            Err(SolanaJsonRpcConformanceError::ResultAndErrorBothPresent)
        );
    }

    // -----------------------------------------------------------------------------------------
    // Frame envelope
    // -----------------------------------------------------------------------------------------

    #[test]
    fn frame_envelope_substitution_is_refused_before_the_body_is_read() {
        let mut wrong_status = frame_with(two_row_body([10, 9]));
        wrong_status.http_status = Some(204);
        assert_eq!(
            read_solana_json_rpc_frame(&wrong_status, 2),
            Err(SolanaJsonRpcConformanceError::FrameEnvelopeMismatch)
        );

        let mut unbounded_headers = frame_with(two_row_body([10, 9]));
        unbounded_headers.safe_headers = vec![SafeHeader {
            name: "authorization".to_owned(),
            value: "secret".to_owned(),
        }];
        assert!(!solana_safe_headers_are_bounded(
            &unbounded_headers.safe_headers
        ));
        assert_eq!(
            read_solana_json_rpc_frame(&unbounded_headers, 2),
            Err(SolanaJsonRpcConformanceError::FrameEnvelopeMismatch)
        );
    }

    // -----------------------------------------------------------------------------------------
    // Response ingress ceiling
    // -----------------------------------------------------------------------------------------

    /// A well-formed one-row body padded with ASCII memo text to exactly `length` bytes. One
    /// padding character is exactly one JSON byte, because `a` needs no escaping and is one UTF-8
    /// byte, so the padded length is exact rather than approximate.
    fn body_of_exact_length(length: usize) -> Vec<u8> {
        let render = |memo: String| {
            serde_json::to_vec(&serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{
                    "signature": signature(1),
                    "slot": 10,
                    "err": Value::Null,
                    "memo": memo,
                    "blockTime": 1,
                    "confirmationStatus": "finalized"
                }]
            }))
            .expect("padded body")
        };
        let padding = length
            .checked_sub(render(String::new()).len())
            .expect("requested length is at least the unpadded body");
        let body = render("a".repeat(padding));
        assert_eq!(
            body.len(),
            length,
            "ASCII padding is one byte per character"
        );
        body
    }

    /// The refusal must land before the parser, so this body is deliberately not JSON: reaching
    /// the parser at all would report `MalformedJson` instead, and reaching it would also mean the
    /// whole hostile body had already been examined.
    #[test]
    fn a_body_over_the_response_ceiling_is_refused_before_it_is_parsed() {
        let hostile = vec![b'{'; INGEST_MAX_RESPONSE_BYTES + 1];
        assert_eq!(
            read_solana_json_rpc_body(&hostile, 2),
            Err(SolanaJsonRpcConformanceError::ResponseExceedsIngressCeiling)
        );
    }

    #[test]
    fn one_byte_over_the_response_ceiling_is_refused_even_though_the_body_is_well_formed() {
        let body = body_of_exact_length(INGEST_MAX_RESPONSE_BYTES + 1);
        assert_eq!(
            read_solana_json_rpc_body(&body, 2),
            Err(SolanaJsonRpcConformanceError::ResponseExceedsIngressCeiling)
        );
    }

    #[test]
    fn a_body_at_exactly_the_response_ceiling_is_still_read_normally() {
        let body = body_of_exact_length(INGEST_MAX_RESPONSE_BYTES);
        assert_eq!(body.len(), INGEST_MAX_RESPONSE_BYTES);
        let page = page_of(&body, 2);
        assert_eq!(page.rows.len(), 1);
        assert!(
            page.rows[0]
                .memo
                .as_deref()
                .is_some_and(|memo| memo.len() > 1_024),
            "the padded memo must survive verbatim, so the ceiling is inclusive"
        );
    }

    #[test]
    fn a_frame_over_the_response_ceiling_is_refused_by_the_same_ingress_bound() {
        let mut frame = conforming_frame();
        frame.body = Bytes::from(vec![b'{'; INGEST_MAX_RESPONSE_BYTES + 1]);
        assert_eq!(
            read_solana_json_rpc_frame(&frame, 2),
            Err(SolanaJsonRpcConformanceError::ResponseExceedsIngressCeiling)
        );
    }

    /// The local ingress ceiling is a chosen operational bound, not the registered contract bound.
    /// It must stay strictly inside what the registry declares, and this pins the relationship so a
    /// registry change cannot silently make the local bound the looser of the two.
    #[test]
    fn the_ingress_ceiling_stays_strictly_inside_the_registered_response_bound() {
        let admitted = crate::contract_port::admit_runtime_method(
            joshi_source_registry::PUBLIC_SOLANA_MAINNET_SOURCE_ID,
            joshi_source_registry::PUBLIC_SOLANA_SIGNATURES_METHOD_KEY,
        )
        .expect("admitted method");
        assert_eq!(admitted.method.max_response_bytes, 64 * 1_024 * 1_024);
        assert!(
            u64::try_from(INGEST_MAX_RESPONSE_BYTES).expect("ceiling fits")
                < admitted.method.max_response_bytes
        );
    }

    // -----------------------------------------------------------------------------------------
    // Retained safe-header allowlist
    // -----------------------------------------------------------------------------------------

    /// The exact four names the bounded allowance admits, in the lowercased spelling.
    const ALLOWED_HEADER_NAMES: [&str; 4] = [
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    ];

    fn header(name: &str, value: &str) -> SafeHeader {
        SafeHeader {
            name: name.to_owned(),
            value: value.to_owned(),
        }
    }

    #[test]
    fn every_allowed_rate_limit_header_is_admitted_on_its_own() {
        for name in ALLOWED_HEADER_NAMES {
            assert!(
                solana_safe_headers_are_bounded(&[header(name, "1")]),
                "{name} is on the bounded allowlist and must be admitted"
            );
        }
    }

    /// A frame carrying the whole allowlist at once is a conforming frame. The suite otherwise
    /// only ever accepts an empty header vector, which would leave the allowance untested on its
    /// accept side.
    #[test]
    fn a_frame_carrying_the_whole_allowlist_is_accepted() {
        let headers: Vec<_> = ALLOWED_HEADER_NAMES
            .iter()
            .map(|name| header(name, "1"))
            .collect();
        assert!(solana_safe_headers_are_bounded(&headers));
        let mut frame = conforming_frame();
        frame.safe_headers = headers;
        match read_solana_json_rpc_frame(&frame, 2).expect("conforming frame with headers") {
            SolanaJsonRpcOutcome::Page(page) => assert_eq!(page.rows.len(), 2),
            SolanaJsonRpcOutcome::ProviderRefusal(_) => {
                panic!("a provider refusal is not a page")
            }
        }
    }

    #[test]
    fn allowed_header_names_are_matched_case_insensitively() {
        assert!(solana_safe_headers_are_bounded(&[header(
            "Retry-After",
            "1"
        )]));
        assert!(solana_safe_headers_are_bounded(&[header(
            "X-RateLimit-Reset",
            "1"
        )]));
        // Case folding is also what makes the single-occurrence rule bite across spellings.
        assert!(!solana_safe_headers_are_bounded(&[
            header("retry-after", "1"),
            header("RETRY-AFTER", "2"),
        ]));
    }

    #[test]
    fn a_header_name_outside_the_allowlist_is_refused() {
        assert!(!solana_safe_headers_are_bounded(&[header(
            "authorization",
            "secret"
        )]));
        assert!(!solana_safe_headers_are_bounded(&[header(
            "retry-after-ms",
            "1"
        )]));
    }

    #[test]
    fn a_header_value_at_the_sanitation_bound_is_admitted_and_one_byte_over_is_refused() {
        let at_bound = "v".repeat(MAX_SAFE_HEADER_VALUE_BYTES);
        assert_eq!(at_bound.len(), 256);
        assert!(solana_safe_headers_are_bounded(&[header(
            "retry-after",
            &at_bound
        )]));
        let over_bound = "v".repeat(MAX_SAFE_HEADER_VALUE_BYTES + 1);
        assert!(!solana_safe_headers_are_bounded(&[header(
            "retry-after",
            &over_bound
        )]));
    }

    #[test]
    fn a_header_value_carrying_a_control_character_is_refused() {
        for value in ["1\r\nx-injected: 2", "1\u{7f}", "1\u{0}"] {
            assert!(
                !solana_safe_headers_are_bounded(&[header("retry-after", value)]),
                "a control character must never survive into a retained header"
            );
        }
    }

    /// More headers than the allowlist admits cannot be accepted, whichever way the surplus is
    /// built: a fifth header is necessarily either a repeat of an admitted name or a name that is
    /// not admitted at all.
    #[test]
    fn more_headers_than_the_allowlist_admits_are_refused() {
        let mut repeated: Vec<_> = ALLOWED_HEADER_NAMES
            .iter()
            .map(|name| header(name, "1"))
            .collect();
        repeated.push(header("retry-after", "2"));
        assert_eq!(repeated.len(), ALLOWED_HEADER_NAMES.len() + 1);
        assert!(!solana_safe_headers_are_bounded(&repeated));

        let mut foreign: Vec<_> = ALLOWED_HEADER_NAMES
            .iter()
            .map(|name| header(name, "1"))
            .collect();
        foreign.push(header("x-ratelimit-policy", "1"));
        assert!(!solana_safe_headers_are_bounded(&foreign));
    }

    // -----------------------------------------------------------------------------------------
    // Frame envelope, one guard at a time
    // -----------------------------------------------------------------------------------------

    /// The exact conforming frame the envelope tests below start from. Each of those tests flips
    /// exactly one field, so a refusal there is caused by that field and by nothing else.
    fn conforming_frame() -> RawSourceFrame {
        frame_with(two_row_body([10, 9]))
    }

    fn assert_envelope_refused(frame: &RawSourceFrame) {
        assert_eq!(
            read_solana_json_rpc_frame(frame, 2),
            Err(SolanaJsonRpcConformanceError::FrameEnvelopeMismatch)
        );
    }

    /// Control for every single-field flip below. Without this, a flip test would pass even if the
    /// frame were refused for some unrelated reason.
    #[test]
    fn the_unflipped_conforming_frame_is_accepted() {
        match read_solana_json_rpc_frame(&conforming_frame(), 2).expect("conforming frame") {
            SolanaJsonRpcOutcome::Page(page) => assert_eq!(page.rows.len(), 2),
            SolanaJsonRpcOutcome::ProviderRefusal(_) => {
                panic!("a provider refusal is not a page")
            }
        }
    }

    /// The envelope is checked before the body: a frame with a wrong envelope is refused as an
    /// envelope mismatch even when its body is not JSON at all.
    #[test]
    fn the_frame_envelope_is_refused_before_the_body_is_looked_at() {
        let mut frame = conforming_frame();
        frame.transport = Transport::WebSocket;
        frame.body = Bytes::from_static(b"not json at all");
        assert_envelope_refused(&frame);
    }

    #[test]
    fn a_frame_from_another_source_is_refused() {
        for source in [
            SourceId::HeliusHttp,
            SourceId::SolanaPublicWebSocket,
            SourceId::Other("solana.public.mainnet".to_owned()),
        ] {
            let mut frame = conforming_frame();
            frame.source = source;
            assert_envelope_refused(&frame);
        }
    }

    #[test]
    fn a_frame_carrying_another_adapter_contract_version_is_refused() {
        let mut frame = conforming_frame();
        frame.contract_version = "joshi.sources.v0".to_owned();
        assert_envelope_refused(&frame);
    }

    #[test]
    fn a_frame_on_another_transport_is_refused() {
        for transport in [Transport::WebSocket, Transport::Fixture] {
            let mut frame = conforming_frame();
            frame.transport = transport;
            assert_envelope_refused(&frame);
        }
    }

    #[test]
    fn a_frame_in_another_stream_class_is_refused() {
        for stream_class in [
            StreamClass::BroadCensus,
            StreamClass::LeasedHot,
            StreamClass::Control,
        ] {
            let mut frame = conforming_frame();
            frame.stream_class = stream_class;
            assert_envelope_refused(&frame);
        }
    }

    #[test]
    fn an_outbound_control_frame_is_refused() {
        let mut frame = conforming_frame();
        frame.direction = FrameDirection::OutboundControl;
        assert_envelope_refused(&frame);
    }

    #[test]
    fn a_frame_declaring_another_content_type_is_refused() {
        for content_type in [ContentType::Binary, ContentType::Text, ContentType::Unknown] {
            let mut frame = conforming_frame();
            frame.content_type = content_type;
            assert_envelope_refused(&frame);
        }
    }

    /// The receipt stamp is the one clock-shaped field the envelope reads, and it is read only to
    /// require a positive Unix-millis value. Nothing compares it against a current time, so this
    /// establishes a well-formedness floor and nothing about when the frame was received.
    #[test]
    fn a_frame_without_a_positive_receipt_stamp_is_refused() {
        for stamp in [0, -1, i64::MIN] {
            let mut frame = conforming_frame();
            frame.received_at = UnixMillis(stamp);
            assert_envelope_refused(&frame);
        }
    }

    #[test]
    fn a_frame_from_another_connection_epoch_is_refused() {
        for epoch in [0, 2, u64::MAX] {
            let mut frame = conforming_frame();
            frame.connection_epoch = epoch;
            assert_envelope_refused(&frame);
        }
    }

    /// This contract admits one frame on one connection, so any sequence other than the first
    /// is a frame this contract never asked for.
    #[test]
    fn a_frame_at_another_sequence_number_is_refused() {
        for sequence in [0, 2, u64::MAX] {
            let mut frame = conforming_frame();
            frame.sequence = sequence;
            assert_envelope_refused(&frame);
        }
    }

    #[test]
    fn a_frame_without_an_http_200_status_is_refused() {
        for status in [None, Some(199), Some(201), Some(204), Some(429), Some(500)] {
            let mut frame = conforming_frame();
            frame.http_status = status;
            assert_envelope_refused(&frame);
        }
    }

    #[test]
    fn a_frame_with_an_unbounded_safe_header_set_is_refused() {
        let mut frame = conforming_frame();
        frame.safe_headers = vec![header("authorization", "secret")];
        assert_envelope_refused(&frame);
    }
}
