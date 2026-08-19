//! The deterministic physical byte bound for the one admitted C1 page.
//!
//! A committed C1 authority chain admits exactly one bounded, credential-free public
//! `getSignaturesForAddress` request for exactly one page. Before any socket may open, the runtime
//! must durably reserve a worst-case byte budget, so an ingress ceiling on the HTTP response entity
//! body has to be carried all the way to the physical spool segment that lands on disk.
//!
//! The response body is **not** the segment size. It is nested inside four serializers that expand
//! it multiplicatively, and the largest of those expansions is not a compression-style constant:
//! it is a 4x blow-up from a `Vec<u8>` that carries no serde attribute at all.
//!
//! # The chain, stage by stage
//!
//! Let `N` be the exact HTTP response entity body length in bytes.
//!
//! 1. **Frame.** The body is retained verbatim as [`joshi_sources::RawSourceFrame::body`]. No
//!    growth.
//! 2. **Retained envelope, x4.** `joshi_sources::retained_frame_payload` moves the body into
//!    [`joshi_sources::RetainedFrameEnvelope::body`], which is a plain `Vec<u8>` with **no serde
//!    attribute**. `serde_json` therefore writes it as a JSON array of decimal integers
//!    (`[255,255,...]`). For `N` elements that is at most `3N` digit characters, `N - 1` commas and
//!    two brackets, so at most `4N + 1`; `4N + 2` covers `N = 0` as well. This is a bound and not
//!    an identity — see the exact/conservative split below for what it really costs. This is the
//!    stage a prior attempt missed.
//! 3. **Observation, x4/3.** [`joshi_evidence::ObservationDraft::payload`] is
//!    `#[serde(with = "base64_bytes")]`, i.e. standard padded base64: exactly `4 * ceil(P / 3)`
//!    output bytes for `P` input bytes.
//! 4. **Batch, x1.** [`joshi_evidence::DurableIngestBatch`] carries the observation verbatim; its
//!    JSON adds only the batch contract version, batch ID, expected digest and, of its ten fields,
//!    the six a C1 page leaves as empty collections: `source_events`, `assertions`,
//!    `coverage_windows`, `coverage_gaps`, `coverage_recoveries` and `cursor_advances`.
//! 5. **Entry, x4/3.** `joshi_spool::EvidenceBatchEntry::exact_batch_bytes` is base64 **again**, so
//!    the batch JSON of stage 4 is re-encoded at `4 * ceil(B / 3)`. `exact_policy_bytes` is a
//!    second base64 field over the fixed C1 policy document.
//! 6. **Segment, x4/3.** `joshi_spool::encode_segment` frames the entry with an 8-byte big-endian
//!    length prefix, optionally seals it under ChaCha20-Poly1305 (which appends a 16-byte tag), and
//!    then writes the sealed body into `joshi_spool::DiskSegment::sealed_body_bytes`, which is
//!    base64 a **third** time. The `serde_json::to_vec` of that `DiskSegment` is the physical local
//!    spool segment.
//!
//! The body therefore reaches disk at `4 * (4/3)^3 = 256/27 ~= 9.48` times its ingress length,
//! before any fixed overhead. `joshi_supervisor::PendingSegment::new` measures stage 5; the local
//! spool enforces `SpoolConfig::max_segment_bytes` against stage 6.
//!
//! # Measured against the real chain
//!
//! The unit tests below push real frames through the real chain: the frame goes to the real C1
//! evidence adapter, [`crate::c1::evidence::C1RawObservationAdapter`], so the measured record
//! carries the policy contract, policy document, observation source variant, missing-provider-clock
//! reason and absent-monotonic-clock domain that path actually retains, rather than a local copy of
//! them. The retained header set is the largest one
//! [`joshi_sources::public_solana_c1_safe_headers_are_bounded`] admits: all four allowlisted names
//! at the full 256-byte value length, valued with the byte `serde_json` expands most.
//!
//! The measured body is the costliest one the C1 contract admits at the ceiling: a single-row page
//! padded with `z` memo text, byte 122, which the array-of-integers stage writes as three decimal
//! digits — the most any byte costs there. A page cannot be made entirely of such bytes, because
//! its structural JSON characters include bytes below 100 that cost two, so the `4N + 2` bound is
//! not tight even here; and a page of a given length is costliest with the fewest rows, which is
//! why the fixture carries one.
//!
//! At the chosen 256 KiB ingress ceiling that page reaches disk at **2,498,092 bytes, a 9.529x
//! expansion**, against a derived bound of 2,751,948 (90.7% of the bound consumed). A realistic
//! 100-row page of 20,135 bytes reaches disk at 177,389 bytes, an 8.809x expansion. Both numbers
//! are pinned by unit tests.
//!
//! The fixed allowances are measured against that same path rather than asserted. At the ceiling
//! the real per-stage overheads are 2,441 bytes of retained envelope against a 64 KiB allowance,
//! 1,980 of observation metadata against 32 KiB, 328 of batch envelope against 8 KiB, 1,028 of
//! spool entry against 16 KiB, and 1,588 of segment header against 16 KiB (1,694 when sealed) —
//! between about 9x and 27x of margin, which is where the remaining slack in the bound lives.
//! Shrinking any allowance below what the admissible worst case costs fails
//! `every_fixed_allowance_covers_the_overhead_the_real_path_measures`.
//!
//! Bodies the contract refuses are never measured through the evidence path, because they cannot
//! reach it. Only one stage of the chain depends on content at all — the array of integers — and
//! it is bounded for arbitrary bytes directly against `serde_json` by
//! `hostile_byte_patterns_stay_within_the_array_of_integers_bound`.
//!
//! # What is bounded exactly and what is bounded conservatively
//!
//! **Exact.** Three items are arithmetic identities of the encoders rather than estimates:
//!
//! 1. **Each base64 expansion, `4 * ceil(n / 3)`.** Standard padded base64 emits exactly four
//!    output bytes per three-byte input group, padding the last group. The same identity is applied
//!    unchanged at all three base64 stages.
//! 2. **The 8-byte big-endian entry length prefix** `joshi_spool::encode_segment` writes ahead of
//!    the entry bytes.
//! 3. **The 16-byte Poly1305 tag** an authenticated-private seal appends.
//!
//! The `SEGMENT_FRAMING_BYTES` constant is the exact sum of items 2 and 3 for an
//! authenticated-private domain. A public-integrity domain is not sealed and carries no tag, so for
//! that domain the constant over-states the framing by exactly 16 bytes.
//!
//! **Conservative.** Everything else is an upper bound or a fixed allowance, deliberately generous
//! and *not* derived field by field:
//!
//! - **The `4N + 2` array-of-integers expansion is a bound, not an identity.** `serde_json` writes
//!   a bare `Vec<u8>` as `sum(digits(b) for b in body) + (N - 1) + 2` bytes for `N >= 1`, and as
//!   `2` bytes for `N = 0`, where `digits(b)` is 1, 2 or 3. `4N + 2` is that quantity with every
//!   byte charged the maximum three digits, plus one spare byte. It therefore over-estimates
//!   strictly for every `N >= 1`. Its tightest case is an all-`0xFF` body, where every byte really
//!   does take three digits and the bound over-states by exactly 1 byte; on the realistic 20,135
//!   byte page measured below the identity gives 69,413 bytes against a bound of 80,542, so
//!   11,129 bytes — 13.8% of the bound — is slack. Both facts are pinned by unit tests.
//! - **Every non-body field at every stage.** That covers contract-version strings, enum
//!   discriminants, acquisition/observation/reservation identifiers, timestamps, monotonic
//!   readings, SHA-256 digests, the retained `safe_headers` allowlist, the exact policy document,
//!   the batch closure and its expected counts, the entry descriptor, the source-occurrence closure
//!   and the whole segment header. Each allowance is a round number chosen well above the largest
//!   shape this path can produce, and each is then multiplied by whatever base64 stages follow it.
//!   "Well above" is a measurement here, not a hope: the overheads quoted in the previous section
//!   are what the real path costs at the admissible worst case, and a test compares each allowance
//!   against them.
//!
//! These allowances are **preconditions, not proofs**. The bound holds for the C1 shape: exactly
//! one retained observation in exactly one batch in exactly one entry in one segment, one bounded
//! non-secret header allowlist, and the fixed C1 policy document. A caller that retains many
//! observations per batch, an unbounded header allowlist, or a policy document larger than the
//! entry allowance is outside this bound.
//!
//! # The obligation a compile-time constant cannot discharge
//!
//! The guard at the bottom of this module is a `const` assertion. It proves one thing only: that
//! the ceiling *this source file ships* derives a segment bound under the smallest
//! `SpoolConfig::max_segment_bytes` that was configured **in this tree at the time it was
//! written**. A compile-time constant cannot observe, and therefore cannot guarantee, the
//! configuration a process actually runs under. `SpoolConfig` is built at runtime from application
//! code, and a `max_segment_bytes` smaller than the anchor is a legal `SpoolConfig`.
//!
//! So the C1 runtime **must** compare its *actual* configured `SpoolConfig::max_segment_bytes`
//! against [`C1PhysicalBoundV1::max_segment_bytes`] and refuse the activation when the derived
//! bound does not fit, **before any socket can be prepared**. That check is not implemented in this
//! module and nothing here can stand in for it. This is the "Configured ceiling" obligation in
//! `docs/implementation/wave5/22_C1_RAW_BOUNDARY.md`; the anchor narrows the window in which a
//! misconfiguration is possible, it does not close it.
//!
//! The anchor itself is the private `SMALLEST_HOSTING_SEGMENT_CEILING_BYTES` constant in this
//! file. Its doc comment carries the full inventory of every `SpoolConfig::max_segment_bytes`
//! configured in this tree, with file, line and test status, and the argument for which of them a
//! C1 read could actually be hosted under.
//!
//! # What this is not
//!
//! This is a bound on **bytes only**. It is not evidence that a real retained response fits, that
//! the endpoint is reachable, that a page exists, that a read is authorized, or that any I/O may
//! occur. The unit tests in this module measure the real chain functions on chosen inputs; cases
//! are cases, and they prove nothing about all inputs.
//!
//! The ceiling for every artifact produced here is [`crate::AUTHORITY_CEILING`].

use serde::Serialize;

use crate::{Result, SupervisorError};

/// The one-page C1 ingress ceiling, in bytes of HTTP response entity body.
///
/// This is **not** an independent number. It is the same ceiling
/// [`joshi_sources::PUBLIC_SOLANA_C1_MAX_RESPONSE_BYTES`] declares, widened to `u64`. That
/// constant is the single source of truth, and it has to be: `joshi-supervisor` depends on
/// `joshi-sources` and not the reverse, so the reader that refuses an oversized body and the
/// derivation that budgets for one must both reach the same value through the dependency edge
/// rather than by two hand-maintained literals. An earlier revision restated `256 * 1024` here,
/// and an audit showed the sources-side ceiling could then be changed 16x with every test on both
/// sides still green.
///
/// Why 256 KiB is the chosen operational value is documented on the `joshi-sources` constant. In
/// short: a `getSignaturesForAddress` page is at most 100 rows, a realistic full page measures
/// about 20 KiB, and the source registry's 64 MiB `max_response_bytes` is a *contract* ceiling on
/// what the source may send (256x this value) rather than a budget this path can durably absorb.
///
/// At this ceiling the derived physical segment is 2,751,948 bytes: 65.6% of the 4 MiB anchor
/// carried by the private `SMALLEST_HOSTING_SEGMENT_CEILING_BYTES` constant in this file, leaving
/// 1,442,356 bytes of headroom.
///
/// See [`c1_physical_bound`] for what this expands to on disk.
pub const C1_MAX_RESPONSE_BODY_BYTES: u64 =
    joshi_sources::PUBLIC_SOLANA_C1_MAX_RESPONSE_BYTES as u64;

/// The smallest `SpoolConfig::max_segment_bytes` a C1 read could actually be hosted under: the
/// 4 MiB the `joshi-core` application configures.
///
/// This is the anchor the compile-time guard at the bottom of this module uses. A prior revision
/// anchored to 16 MiB and described it as the smallest durable configuration; that number is a
/// `cfg(test)` fixture and was never a durable configuration at all.
///
/// Every `SpoolConfig::max_segment_bytes` in the tree, so the next reader can check the anchor
/// without re-deriving it:
///
/// | site | value | status |
/// | --- | --- | --- |
/// | `apps/collector/src/main.rs:206` | 32 MiB | non-test: the collector application |
/// | `apps/core/src/wave5_g0.rs:1831` | 4 MiB | non-test: `joshi-core`, `wave5_g0::supervisor_config` |
/// | `apps/core/src/wave5_readiness.rs:215` | 4 MiB | non-test: `joshi-core`, `wave5_readiness::spool_config` |
/// | `crates/joshi-supervisor/src/bin/joshi-supervisor-kill-child.rs:67` | 1 MiB | not `cfg(test)`, but a fault-injection child binary |
/// | `crates/joshi-supervisor/src/runtime.rs:1793` | 16 MiB | `cfg(test)` fixture (`mod tests` opens at line 1613) |
/// | `crates/joshi-supervisor/tests/support/mod.rs:21` | 1 MiB | integration-test support |
/// | `crates/joshi-spool/tests/protocol.rs:105` | 1,000,000 | integration test in `joshi-spool` |
///
/// Two further `max_segment_bytes` values in the tree belong to `joshi_spool::ReplicaConfig`, a
/// different type bounding remote replica ingest rather than the local spool this bound targets:
/// `crates/joshi-supervisor/tests/continuity.rs:211` (1 MiB) and
/// `crates/joshi-spool/tests/protocol.rs:118` (1,000,000). Both are integration tests.
///
/// **Why 4 MiB and not the 1 MiB minimum.** The two 1 MiB `SpoolConfig` sites are the kill-fault
/// child binary and one integration-test support fixture. The child binary is not `cfg(test)`, but
/// it exists only to be spawned and killed by `crates/joshi-supervisor/tests/continuity.rs`: it
/// hardcodes a `kill-source`/`kill-poll` reservation and panics if it survives its fault point, so
/// no C1 read runs under it. That exclusion is load-bearing, so its consequence is stated plainly
/// rather than left implicit: **the bound derived here does not fit a 1 MiB segment ceiling**
/// (2,751,948 > 1,048,576), and no C1 ingress ceiling worth shipping would. The fixed allowances
/// alone derive 266,432 physical bytes from a zero-length body, and a 1 MiB ceiling admits at most
/// 82,491 bytes of ingress. Both numbers are pinned by a unit test. That 82,491 is well under the
/// 256 KiB this module ships, and under what a 100-row page carrying memo text is expected to
/// need — that expectation is a judgment about the source, not a measurement of it. A 1 MiB spool
/// is therefore not treated as a C1 host, and the runtime check described in the module
/// documentation is what has to enforce that.
const SMALLEST_HOSTING_SEGMENT_CEILING_BYTES: u64 = 4 * 1024 * 1024;

/// Conservative allowance for every non-body field of the retained frame envelope: envelope and
/// adapter contract versions, transport/stream-class/direction/content-type discriminants, the HTTP
/// status, the bounded non-secret `safe_headers` allowlist, and all JSON keys and punctuation.
const RETAINED_ENVELOPE_FIXED_BYTES: u64 = 64 * 1024;

/// Conservative allowance for the acquisition record and observation metadata that wrap the base64
/// payload inside one serialized `ObservationDraft`: identifiers, the request fingerprint, locator,
/// clocks, monotonic readings, event-time interval, media type and all JSON keys.
const OBSERVATION_METADATA_FIXED_BYTES: u64 = 32 * 1024;

/// Conservative allowance for the durable ingest batch envelope around its one observation: batch
/// contract version, batch ID, expected digest and the six collections a C1 page leaves empty.
const BATCH_FIXED_BYTES: u64 = 8 * 1024;

/// Conservative allowance for the spool entry around the base64 batch: the `SpoolEntry` tag and
/// wrapper, the batch closure with its digests and expected counts, the acquisition ID list, and
/// the base64 of the fixed C1 policy document.
const ENTRY_FIXED_BYTES: u64 = 16 * 1024;

/// Conservative allowance for the disk segment header around the base64 sealed body: contract,
/// segment ID, creation time, protection domain and metadata, the entry descriptor with its
/// duplicated batch closure, and the source-occurrence closure.
const SEGMENT_FIXED_BYTES: u64 = 16 * 1024;

/// Exact physical framing added between the entry bytes and the sealed segment body: an 8-byte
/// big-endian entry length prefix plus, for an authenticated-private domain, a 16-byte
/// Poly1305 tag. A public-integrity domain uses only the 8 bytes; 24 covers both.
const SEGMENT_FRAMING_BYTES: u64 = 24;

/// Worst-case physical byte sizes for one C1 page, from ingress body to local spool segment.
///
/// Every field is an upper bound, not a measurement of any particular response. The fields are
/// nested: each stage contains the one above it.
///
/// The whole contract of this type is that the last five fields *are* the derivation of the first
/// one, so the only way to obtain a value is [`c1_physical_bound`]. It is deliberately
/// `Serialize`-only: it can be recorded as evidence, and it cannot be reconstituted from JSON.
/// Deriving `Deserialize` would admit a value whose fields do not derive from its
/// `maxResponseBodyBytes` and whose accessors would then hand a caller a budget nothing computed —
/// exactly the under-reservation this module exists to prevent. Nothing in the tree deserializes
/// this type. A future reader who needs to accept one over the wire must re-run the derivation on
/// the received `maxResponseBodyBytes` and reject any value that does not match it field for field,
/// not add the derive back.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
// Every field is a maximum, and the shared `max` prefix is what makes that readable on the wire
// and at each accessor. Dropping it would make `segment_bytes` read like a measurement.
#[allow(clippy::struct_field_names)]
pub struct C1PhysicalBoundV1 {
    max_response_body_bytes: u64,
    max_retained_envelope_bytes: u64,
    max_observation_payload_bytes: u64,
    max_batch_bytes: u64,
    max_entry_bytes: u64,
    max_segment_bytes: u64,
}

impl C1PhysicalBoundV1 {
    /// The ingress ceiling this bound was derived from: the HTTP response entity body length.
    #[must_use]
    pub const fn max_response_body_bytes(&self) -> u64 {
        self.max_response_body_bytes
    }

    /// Upper bound on `serde_json::to_vec` of the retained frame envelope, whose `body` field is a
    /// bare `Vec<u8>` and is therefore written as a JSON array of decimal integers.
    #[must_use]
    pub const fn max_retained_envelope_bytes(&self) -> u64 {
        self.max_retained_envelope_bytes
    }

    /// Upper bound on `serde_json::to_vec` of one `ObservationDraft`: the base64 of the retained
    /// envelope plus its acquisition and observation metadata.
    #[must_use]
    pub const fn max_observation_payload_bytes(&self) -> u64 {
        self.max_observation_payload_bytes
    }

    /// Upper bound on `serde_json::to_vec` of the `DurableIngestBatch` holding that one
    /// observation. These are the `exact_batch_bytes` retained by the spool entry.
    #[must_use]
    pub const fn max_batch_bytes(&self) -> u64 {
        self.max_batch_bytes
    }

    /// Upper bound on `serde_json::to_vec` of the `SpoolEntry`, which base64s the batch bytes
    /// again. This is the quantity `PendingSegment::new` measures as `exact_entry_bytes`.
    #[must_use]
    pub const fn max_entry_bytes(&self) -> u64 {
        self.max_entry_bytes
    }

    /// Upper bound on the physical local spool segment written to disk by
    /// `joshi_spool::encode_segment`. This is the quantity the local spool checks against
    /// `SpoolConfig::max_segment_bytes`.
    #[must_use]
    pub const fn max_segment_bytes(&self) -> u64 {
        self.max_segment_bytes
    }
}

/// Derives the worst-case physical byte sizes for one C1 page from an ingress body ceiling.
///
/// The derivation applies the exact encoder expansions described in the module documentation and
/// adds a conservative fixed allowance at each stage. Every step is checked arithmetic; nothing
/// saturates, because a saturated budget would silently under-reserve.
///
/// The result is monotonically nondecreasing in `max_response_body_bytes`.
///
/// # Errors
///
/// Returns [`SupervisorError::InvalidValue`] when any step would overflow `u64`.
pub fn c1_physical_bound(max_response_body_bytes: u64) -> Result<C1PhysicalBoundV1> {
    derive(max_response_body_bytes).map_err(|stage| {
        SupervisorError::InvalidValue(format!(
            "C1 physical size overflowed u64 at the {stage} stage"
        ))
    })
}

/// The whole derivation, const-evaluable so the shipped ceiling can be checked at compile time.
///
/// The error carries the stage name rather than a [`SupervisorError`], because building a
/// [`SupervisorError`] allocates and cannot run in a const context.
const fn derive(
    max_response_body_bytes: u64,
) -> core::result::Result<C1PhysicalBoundV1, &'static str> {
    let Some(body_array_bytes) = json_integer_array_bytes(max_response_body_bytes) else {
        return Err("retained frame envelope body array");
    };
    let Some(max_retained_envelope_bytes) =
        body_array_bytes.checked_add(RETAINED_ENVELOPE_FIXED_BYTES)
    else {
        return Err("retained frame envelope");
    };

    let Some(payload_base64_bytes) = base64_bytes(max_retained_envelope_bytes) else {
        return Err("observation payload base64");
    };
    let Some(max_observation_payload_bytes) =
        payload_base64_bytes.checked_add(OBSERVATION_METADATA_FIXED_BYTES)
    else {
        return Err("observation draft");
    };

    let Some(max_batch_bytes) = max_observation_payload_bytes.checked_add(BATCH_FIXED_BYTES) else {
        return Err("durable ingest batch");
    };

    let Some(batch_base64_bytes) = base64_bytes(max_batch_bytes) else {
        return Err("exact batch bytes base64");
    };
    let Some(max_entry_bytes) = batch_base64_bytes.checked_add(ENTRY_FIXED_BYTES) else {
        return Err("spool entry");
    };

    let Some(framed_body_bytes) = max_entry_bytes.checked_add(SEGMENT_FRAMING_BYTES) else {
        return Err("segment body framing");
    };
    let Some(sealed_body_base64_bytes) = base64_bytes(framed_body_bytes) else {
        return Err("sealed segment body base64");
    };
    let Some(max_segment_bytes) = sealed_body_base64_bytes.checked_add(SEGMENT_FIXED_BYTES) else {
        return Err("disk segment");
    };

    Ok(C1PhysicalBoundV1 {
        max_response_body_bytes,
        max_retained_envelope_bytes,
        max_observation_payload_bytes,
        max_batch_bytes,
        max_entry_bytes,
        max_segment_bytes,
    })
}

/// Upper bound, *not* an identity, on `serde_json` output for a `Vec<u8>` of `count` bytes carrying
/// no serde attribute.
///
/// The identity is `sum(digits(b) for b in body) + (count - 1) + 2` for `count >= 1` and `2` for
/// `count = 0`. This charges every element the maximum three decimal digits, giving
/// `3 * count + (count - 1) + 2 = 4 * count + 1`, and adds one spare byte so the same expression
/// also covers the empty `[]` case. It over-estimates strictly for every `count >= 1`: by exactly
/// 1 byte when every element is at least 100, and by more for any smaller element.
const fn json_integer_array_bytes(count: u64) -> Option<u64> {
    match count.checked_mul(4) {
        Some(value) => value.checked_add(2),
        None => None,
    }
}

/// Exact standard padded base64 output length for `count` input bytes: `4 * ceil(count / 3)`.
const fn base64_bytes(count: u64) -> Option<u64> {
    match count.checked_add(2) {
        Some(value) => (value / 3).checked_mul(4),
        None => None,
    }
}

/// Compile-time guard: the ceiling this module ships must derive a physical segment bound strictly
/// under `SMALLEST_HOSTING_SEGMENT_CEILING_BYTES`. If either number is ever changed to break that,
/// the crate stops building rather than the runtime under-reserving.
///
/// This guard is about the two constants in this file and nothing else. It cannot see the
/// `SpoolConfig` a process is actually opened with; see the module documentation for the runtime
/// check that obligation requires.
const _: () = match derive(C1_MAX_RESPONSE_BODY_BYTES) {
    Ok(bound) => assert!(bound.max_segment_bytes < SMALLEST_HOSTING_SEGMENT_CEILING_BYTES),
    Err(_) => panic!("the chosen C1 ingress ceiling must derive a physical bound"),
};

#[cfg(test)]
mod tests {
    use super::*;

    use bytes::Bytes;
    use joshi_domain::{OpenVariant, SourceId as DomainSourceId, StableString, UtcTimestamp};
    use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch, ObservationDraft};
    use joshi_sources::{
        ADAPTER_CONTRACT_VERSION, ContentType, FrameDirection, RawSourceFrame, SafeHeader,
        SourceId, StreamClass, Transport, UnixMillis, public_solana_c1_safe_headers_are_bounded,
    };
    use joshi_spool::{
        EvidenceBatchEntry, KeyMaterial, ProtectionDomainId, ProtectionRequest, SegmentId,
        SegmentProtector, SpoolEntry, encode_segment,
    };

    use crate::{
        AttemptKind, AttemptReservation, GenerationId, OperationKey, PendingSegment,
        ProtectionProfile, ReservationId, SourceKey,
        c1::{C1_OPERATION_KEY, C1_SOURCE_KEY, evidence::C1RawObservationAdapter},
    };

    /// One deterministic body-byte pattern: the byte this generator places at each position.
    type BytePattern = fn(usize) -> u8;

    /// Bitcoin/Solana base58 alphabet: no `0`, `O`, `I` or `l`.
    const BASE58: &[u8] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

    /// The only four response header names the C1 contract retains, per
    /// `joshi_sources::public_solana_c1_safe_headers_are_bounded`. The list is duplicated here
    /// because the one in `joshi-sources` is a private `const` inside that function; the duplicate
    /// is not trusted, it is checked against the real predicate by
    /// `the_header_fixture_is_the_largest_admissible_safe_header_set`.
    const ADMISSIBLE_HEADER_NAMES: [&str; 4] = [
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    ];

    /// The longest retained value that predicate admits, in bytes. Also private in `joshi-sources`,
    /// and also pinned against the real predicate rather than trusted.
    const ADMISSIBLE_HEADER_VALUE_BYTES: usize = 256;

    /// Overhead each stage measures at the shipped ingress ceiling on the public-integrity
    /// domain, pinned exactly by `every_fixed_allowance_covers_the_overhead_the_real_path_measures`
    /// so the margins quoted in the module documentation cannot drift unnoticed.
    const OVERHEAD_RETAINED_ENVELOPE: u64 = 2_441;
    const OVERHEAD_OBSERVATION: u64 = 1_980;
    const OVERHEAD_BATCH: u64 = 328;
    const OVERHEAD_ENTRY: u64 = 1_028;
    const OVERHEAD_SEGMENT: u64 = 1_588;

    /// Physical byte lengths actually produced by the real chain functions.
    #[derive(Clone, Copy, Debug)]
    struct Measured {
        retained_envelope: u64,
        observation: u64,
        batch: u64,
        entry: u64,
        segment: u64,
    }

    /// What each stage adds *beyond* the exact encoder expansion of the stage inside it. These are
    /// the quantities the fixed allowance constants have to cover, so they are what
    /// `every_fixed_allowance_covers_the_overhead_the_real_path_measures` compares against.
    #[derive(Clone, Copy, Debug)]
    struct Overhead {
        retained_envelope: u64,
        observation: u64,
        batch: u64,
        entry: u64,
        segment: u64,
    }

    fn at() -> UtcTimestamp {
        "2026-08-19T00:00:00.000000Z".parse().unwrap()
    }

    fn scope() -> CoverageScope {
        CoverageScope {
            source_id: DomainSourceId::new("solana.public_http.v1").unwrap(),
            family: OpenVariant::known("chain_signature_page").unwrap(),
            subject: Some(
                StableString::new("address:TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA").unwrap(),
            ),
        }
    }

    fn reservation() -> AttemptReservation {
        AttemptReservation {
            contract: crate::SUPERVISOR_CONTRACT_VERSION.into(),
            reservation_id: ReservationId::new("c1-physical-size-0001").unwrap(),
            installation_id: "inst-00000000000000000000000000000000".into(),
            source_key: SourceKey::new(C1_SOURCE_KEY).unwrap(),
            operation_key: OperationKey::new(C1_OPERATION_KEY).unwrap(),
            generation: GenerationId::new(1),
            attempt_ordinal: 1,
            kind: AttemptKind::HttpRequest,
            scope: scope(),
            lower: Boundary::Wall { value: at() },
            protection: ProtectionProfile::PublicIntegrity {
                domain: ProtectionDomainId::new("public-c1").unwrap(),
            },
            run: None,
            execution_claim: None,
            provider_plan: None,
            reserved_at: at(),
            authority: crate::AUTHORITY_CEILING.into(),
        }
    }

    /// The largest safe-header set the C1 contract can admit, and therefore the largest one a
    /// conforming transport can hand this path.
    ///
    /// Every one of the four allowlisted names is present, because a fifth header would have to
    /// repeat a name and repeats are refused. Every value is `ADMISSIBLE_HEADER_VALUE_BYTES` of
    /// `"`, which is the admissible byte with the largest JSON expansion: `serde_json` escapes it
    /// to two output bytes, while a control character — which would escape to six — is refused by
    /// the predicate outright. So this set maximises both the retained byte count and its JSON
    /// encoding.
    ///
    /// An earlier revision used eight plausible-looking rate-limit headers with short values. That
    /// set is not admissible under the real contract at all — half its names are outside the
    /// allowlist and it carries twice the admitted count — and an audit measured its retained
    /// overhead at 645 bytes, roughly a quarter of what this fixture costs.
    fn worst_case_admissible_headers() -> Vec<SafeHeader> {
        ADMISSIBLE_HEADER_NAMES
            .into_iter()
            .map(|name| SafeHeader {
                name: name.to_owned(),
                value: "\"".repeat(ADMISSIBLE_HEADER_VALUE_BYTES),
            })
            .collect()
    }

    /// The frame receipt instant, which is the reservation instant. The adapter refuses a frame
    /// received before its reservation was taken, so the fixture derives one from the other rather
    /// than restating it.
    fn received_at() -> UnixMillis {
        UnixMillis(at().as_datetime().unix_timestamp() * 1_000)
    }

    /// The exact envelope the C1 wire contract admits, and the only one this path can measure:
    /// [`joshi_sources::read_public_solana_c1_frame`] pins the source, contract version, transport,
    /// stream class, direction, content type, a positive receipt stamp, `connection_epoch == 1`,
    /// `sequence == 1`, an HTTP status of exactly 200 and the safe-header allowlist, and the C1
    /// evidence adapter delegates admission to it. There is no wider shape to charge: a frame the
    /// contract refuses never reaches the evidence path at all.
    fn frame(body: Vec<u8>, headers: Vec<SafeHeader>) -> RawSourceFrame {
        RawSourceFrame {
            contract_version: ADAPTER_CONTRACT_VERSION.to_owned(),
            source: SourceId::SolanaPublicHttp,
            transport: Transport::Http,
            stream_class: StreamClass::Backfill,
            direction: FrameDirection::Inbound,
            content_type: ContentType::Json,
            received_at: received_at(),
            connection_epoch: 1,
            sequence: 1,
            http_status: Some(200),
            safe_headers: headers,
            body: Bytes::from(body),
        }
    }

    /// Runs the **real** C1 evidence adapter over one frame at the shipped ingress ceiling.
    ///
    /// Everything measured below therefore carries the vocabulary that path actually retains — its
    /// policy contract and policy document, its observation source variant, its missing-provider-
    /// clock reason and its absent-monotonic-clock domain — rather than a local restatement of
    /// them. A prior revision rebuilt the chain by hand from copied strings, and the copy diverged
    /// from the real path on all four.
    fn prepare(body: Vec<u8>, headers: Vec<SafeHeader>) -> PendingSegment {
        C1RawObservationAdapter::new(c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES).unwrap())
            .unwrap()
            .prepare_raw_page(&reservation(), frame(body, headers))
            .unwrap()
    }

    fn batch_entry(pending: &PendingSegment) -> &EvidenceBatchEntry {
        let SpoolEntry::EvidenceBatch(entry) = &pending.entry else {
            panic!("a C1 raw page must queue an evidence batch")
        };
        entry
    }

    fn only_observation(pending: &PendingSegment) -> ObservationDraft {
        let mut batch: DurableIngestBatch =
            serde_json::from_slice(&batch_entry(pending).exact_batch_bytes).unwrap();
        assert_eq!(batch.observations.len(), 1, "exactly one observation");
        batch.observations.remove(0)
    }

    /// Measures every physical stage of one page.
    ///
    /// `nonce` selects an authenticated-private segment when present; `None` uses the
    /// public-integrity domain, whose sealed body is the plaintext body.
    fn measure(body: Vec<u8>, headers: Vec<SafeHeader>, nonce: Option<[u8; 12]>) -> Measured {
        let pending = prepare(body, headers);
        let observation = only_observation(&pending);

        let domain = ProtectionDomainId::new("public-c1").unwrap();
        let (protection, protector) = match nonce {
            None => (ProtectionRequest::Public { domain }, None),
            Some(nonce) => (
                ProtectionRequest::AuthenticatedPrivate {
                    domain,
                    key_id: "c1-physical-size-key".to_owned(),
                    nonce,
                },
                Some(
                    SegmentProtector::new(
                        KeyMaterial::new("c1-physical-size-key", [7_u8; 32]).unwrap(),
                    )
                    .unwrap(),
                ),
            ),
        };
        let (segment, _closure) = encode_segment(
            SegmentId::new("seg-c1-physical-size-0001").unwrap(),
            at(),
            std::slice::from_ref(&pending.entry),
            &protection,
            protector.as_ref(),
        )
        .unwrap();

        Measured {
            retained_envelope: observation.payload.len() as u64,
            observation: serde_json::to_vec(&observation).unwrap().len() as u64,
            batch: batch_entry(&pending).exact_batch_bytes.len() as u64,
            entry: pending.exact_entry_bytes,
            segment: segment.len() as u64,
        }
    }

    /// Subtracts the exact encoder expansion of each inner stage, leaving exactly what the fixed
    /// allowance constants have to pay for.
    ///
    /// The segment stage uses the framing the measured domain really carries — 8 bytes of length
    /// prefix, plus a 16-byte Poly1305 tag only when sealed — rather than the 24 of
    /// `SEGMENT_FRAMING_BYTES`, which covers both domains and would understate a public-integrity
    /// segment's overhead by the base64 of the tag it does not have.
    fn overhead(body: &[u8], nonce: Option<[u8; 12]>) -> Overhead {
        let measured = measure(body.to_vec(), worst_case_admissible_headers(), nonce);
        let framing = if nonce.is_some() { 24 } else { 8 };
        let after = |stage: &str, outer: u64, inner: u64| -> u64 {
            outer
                .checked_sub(inner)
                .unwrap_or_else(|| panic!("the {stage} stage measured smaller than the stage it contains: {outer} < {inner}"))
        };
        Overhead {
            retained_envelope: after(
                "retained envelope",
                measured.retained_envelope,
                exact_json_integer_array_bytes(body),
            ),
            observation: after(
                "observation",
                measured.observation,
                base64_bytes(measured.retained_envelope).unwrap(),
            ),
            batch: after("batch", measured.batch, measured.observation),
            entry: after(
                "entry",
                measured.entry,
                base64_bytes(measured.batch).unwrap(),
            ),
            segment: after(
                "segment",
                measured.segment,
                base64_bytes(measured.entry + framing).unwrap(),
            ),
        }
    }

    fn assert_within_bound(body_len: u64, measured: Measured) {
        let bound = c1_physical_bound(body_len).unwrap();
        assert!(
            measured.retained_envelope <= bound.max_retained_envelope_bytes(),
            "retained envelope {} exceeded bound {} at body {body_len}",
            measured.retained_envelope,
            bound.max_retained_envelope_bytes()
        );
        assert!(
            measured.observation <= bound.max_observation_payload_bytes(),
            "observation {} exceeded bound {} at body {body_len}",
            measured.observation,
            bound.max_observation_payload_bytes()
        );
        assert!(
            measured.batch <= bound.max_batch_bytes(),
            "batch {} exceeded bound {} at body {body_len}",
            measured.batch,
            bound.max_batch_bytes()
        );
        assert!(
            measured.entry <= bound.max_entry_bytes(),
            "entry {} exceeded bound {} at body {body_len}",
            measured.entry,
            bound.max_entry_bytes()
        );
        assert!(
            measured.segment <= bound.max_segment_bytes(),
            "segment {} exceeded bound {} at body {body_len}",
            measured.segment,
            bound.max_segment_bytes()
        );
    }

    /// A well-formed 88-character base58 string of the shape a Solana signature takes: it decodes
    /// to exactly the 64 bytes the wire contract requires, and distinct seeds give distinct
    /// strings. It is a realistic *shape*, deterministically generated; it is not a signature over
    /// anything.
    ///
    /// The leading character is drawn from `2345` deliberately. An 88-character base58 string can
    /// carry a value at or above `2^512`, which decodes to 65 bytes and is refused; holding the
    /// most significant digit under 5 keeps every generated value inside the 64-byte range.
    fn base58_signature(seed: usize) -> String {
        (0..88_usize)
            .map(|index| {
                if index == 0 {
                    return char::from(BASE58[1 + seed % 4]);
                }
                let position = seed
                    .wrapping_mul(31)
                    .wrapping_add(index.wrapping_mul(17))
                    .wrapping_add(index * index);
                char::from(BASE58[position % BASE58.len()])
            })
            .collect()
    }

    /// One conforming row carrying `memo` bytes of memo text, or a null memo when `memo` is
    /// `None`.
    ///
    /// Memo text is all `z`, byte 122, which `serde_json` writes as three decimal digits at the
    /// array-of-integers stage. Three digits is the most any byte costs there, so memo text is the
    /// most expensive filler an admitted page can carry.
    fn row(index: usize, memo: Option<usize>) -> String {
        let offset = u64::try_from(index).unwrap();
        let memo = match memo {
            None => "null".to_owned(),
            Some(bytes) => format!(r#""{}""#, "z".repeat(bytes)),
        };
        format!(
            r#"{{"blockTime":{},"confirmationStatus":"finalized","err":null,"memo":{memo},"signature":"{}","slot":{}}}"#,
            1_786_881_600_u64 - offset,
            base58_signature(index),
            398_712_345_u64 - offset
        )
    }

    /// A conforming `getSignaturesForAddress` success page, one row per element of `memos`. Slots
    /// and block times decrease with the row index, which is the newest-first order the contract
    /// requires.
    fn page(memos: &[Option<usize>]) -> Vec<u8> {
        let rows: Vec<String> = memos
            .iter()
            .enumerate()
            .map(|(index, memo)| row(index, *memo))
            .collect();
        format!(
            r#"{{"jsonrpc":"2.0","result":[{}],"id":1}}"#,
            rows.join(",")
        )
        .into_bytes()
    }

    /// A 100-row `getSignaturesForAddress` success response with no memo text: the maximum row
    /// count this method returns at a realistic size.
    fn realistic_page() -> Vec<u8> {
        page(&[None; 100])
    }

    /// A conforming page of exactly `total` bytes over `rows` rows, the padding spent on memo text.
    fn padded_page(total: usize, rows: usize) -> Vec<u8> {
        let base = page(&vec![Some(0); rows]).len();
        assert!(
            total >= base,
            "a {rows}-row page is at least {base} bytes; {total} was asked for"
        );
        let extra = total - base;
        let mut memos = vec![Some(extra / rows); rows];
        memos[0] = Some(extra / rows + extra % rows);
        let body = page(&memos);
        assert_eq!(body.len(), total, "the padded page must hit its target");
        body
    }

    /// The costliest admissible body of exactly `total` bytes this module can build: one row, with
    /// every padding byte spent on three-digit memo text.
    ///
    /// One row rather than a hundred because a row's structure — quotes, commas, colons, decimal
    /// digits, field names — carries bytes below 100 that cost two digits rather than three, so the
    /// fewer rows a page of a given length has, the more of it is charged the maximum.
    /// `a_single_row_page_is_the_costliest_shape_of_its_length` checks that against the hundred-row
    /// alternative rather than leaving it as an argument.
    fn costliest_page_of_length(total: usize) -> Vec<u8> {
        padded_page(total, 1)
    }

    /// The costliest body the C1 contract admits at all: that page at the ingress ceiling.
    fn costliest_admissible_page() -> Vec<u8> {
        costliest_page_of_length(usize::try_from(C1_MAX_RESPONSE_BODY_BYTES).unwrap())
    }

    /// The array of integers is the only stage of the chain whose cost depends on content, so the
    /// costliest admissible body is whichever one it charges most. This compares the fixture used
    /// everywhere above against the hundred-row page of the same length.
    #[test]
    fn a_single_row_page_is_the_costliest_shape_of_its_length() {
        let total = usize::try_from(C1_MAX_RESPONSE_BODY_BYTES).unwrap();
        let one_row = exact_json_integer_array_bytes(&costliest_page_of_length(total));
        let hundred_rows = exact_json_integer_array_bytes(&padded_page(total, 100));
        let realistic = exact_json_integer_array_bytes(&realistic_page());
        assert!(
            one_row > hundred_rows,
            "the one-row page wrote {one_row} against the hundred-row page's {hundred_rows}"
        );
        // Neither reaches the 4N + 2 bound: even an all-memo page carries structural bytes below
        // 100, which cost two digits.
        assert!(one_row < json_integer_array_bytes(u64::try_from(total).unwrap()).unwrap());
        // And the realistic page, which spends its length on signatures rather than memo text,
        // costs less per byte than either.
        assert!(
            realistic * u64::try_from(total).unwrap()
                < one_row * u64::try_from(realistic_page().len()).unwrap()
        );
    }

    /// The ingress ceiling is not an independent literal: it is the `joshi-sources` ceiling widened
    /// to `u64`. This fails the moment the two diverge, which is what a re-hardcoded copy on either
    /// side would do.
    #[test]
    fn the_ingress_ceiling_is_the_sources_ceiling_widened() {
        assert_eq!(
            C1_MAX_RESPONSE_BODY_BYTES,
            u64::try_from(joshi_sources::PUBLIC_SOLANA_C1_MAX_RESPONSE_BYTES).unwrap(),
            "the supervisor ceiling must be the joshi-sources ceiling, not a second literal"
        );
        // The value both sides ship today. Every golden number in this module is derived from it.
        assert_eq!(C1_MAX_RESPONSE_BODY_BYTES, 256 * 1024);
    }

    /// Every body and envelope measured here has to be one the C1 wire contract actually admits,
    /// or the measurement is of a shape that can never reach disk. This asks the contract reader
    /// itself rather than asserting the property.
    #[test]
    fn every_measured_fixture_is_a_frame_the_wire_contract_admits() {
        for body in [
            page(&[]),
            page(&[None]),
            page(&[Some(0); 100]),
            realistic_page(),
            costliest_page_of_length(65_536),
            costliest_admissible_page(),
        ] {
            let length = body.len();
            let outcome = joshi_sources::read_public_solana_c1_frame(
                &frame(body, worst_case_admissible_headers()),
                joshi_sources::PUBLIC_SOLANA_C1_MAX_ROWS,
            );
            assert!(
                outcome.is_ok(),
                "the {length} byte fixture page is not a frame the C1 contract admits: {:?}",
                outcome.err()
            );
        }
        assert_eq!(
            costliest_admissible_page().len(),
            usize::try_from(C1_MAX_RESPONSE_BODY_BYTES).unwrap(),
            "the costliest fixture must sit exactly on the ingress ceiling"
        );
    }

    /// The header fixture has to be the admissible worst case, or the fixed allowances are being
    /// exercised against a set the real contract would reject. This pins that it is maximal in
    /// both directions the predicate bounds: one more header and one more value byte.
    #[test]
    fn the_header_fixture_is_the_largest_admissible_safe_header_set() {
        let headers = worst_case_admissible_headers();
        assert!(
            public_solana_c1_safe_headers_are_bounded(&headers),
            "the fixture must be a set the real C1 contract admits"
        );
        assert_eq!(headers.len(), ADMISSIBLE_HEADER_NAMES.len());

        let mut fifth = headers.clone();
        fifth.push(headers[0].clone());
        assert!(
            !public_solana_c1_safe_headers_are_bounded(&fifth),
            "a fifth header must repeat an allowlisted name, and repeats are refused"
        );

        for index in 0..headers.len() {
            let mut wider = headers.clone();
            wider[index].value.push('"');
            assert!(
                !public_solana_c1_safe_headers_are_bounded(&wider),
                "{ADMISSIBLE_HEADER_VALUE_BYTES} is the exact per-value ceiling",
            );
        }

        // Each admissible value costs two JSON bytes per byte retained, and nothing admissible
        // costs more: `serde_json` escapes only `"`, `\` and control characters, and control
        // characters are refused above.
        assert_eq!(
            serde_json::to_vec(&headers[0].value).unwrap().len(),
            2 * ADMISSIBLE_HEADER_VALUE_BYTES + 2
        );
    }

    /// The fixed allowances are the conservative half of this bound, so they are measured against
    /// the real path rather than asserted. Shrinking any of them below what the admissible worst
    /// case actually costs fails here.
    #[test]
    fn every_fixed_allowance_covers_the_overhead_the_real_path_measures() {
        for body in [
            page(&[]),
            page(&[None]),
            realistic_page(),
            costliest_admissible_page(),
        ] {
            let body_len = body.len();
            for nonce in [None, Some([3_u8; 12])] {
                let measured = overhead(&body, nonce);
                assert!(
                    measured.retained_envelope <= RETAINED_ENVELOPE_FIXED_BYTES,
                    "retained envelope overhead {} exceeded its {RETAINED_ENVELOPE_FIXED_BYTES} byte allowance at body {body_len}",
                    measured.retained_envelope
                );
                assert!(
                    measured.observation <= OBSERVATION_METADATA_FIXED_BYTES,
                    "observation metadata overhead {} exceeded its {OBSERVATION_METADATA_FIXED_BYTES} byte allowance at body {body_len}",
                    measured.observation
                );
                assert!(
                    measured.batch <= BATCH_FIXED_BYTES,
                    "batch overhead {} exceeded its {BATCH_FIXED_BYTES} byte allowance at body {body_len}",
                    measured.batch
                );
                assert!(
                    measured.entry <= ENTRY_FIXED_BYTES,
                    "entry overhead {} exceeded its {ENTRY_FIXED_BYTES} byte allowance at body {body_len}",
                    measured.entry
                );
                assert!(
                    measured.segment <= SEGMENT_FIXED_BYTES,
                    "segment overhead {} exceeded its {SEGMENT_FIXED_BYTES} byte allowance at body {body_len}",
                    measured.segment
                );
            }
        }

        // The measured overheads at the shipped ceiling, public-integrity domain. They are pinned
        // exactly so the documented margins cannot drift: a change to the retained policy document
        // or to the C1 observation vocabulary moves these numbers and has to be re-measured here.
        let at_ceiling = overhead(&costliest_admissible_page(), None);
        assert_eq!(at_ceiling.retained_envelope, OVERHEAD_RETAINED_ENVELOPE);
        assert_eq!(at_ceiling.observation, OVERHEAD_OBSERVATION);
        assert_eq!(at_ceiling.batch, OVERHEAD_BATCH);
        assert_eq!(at_ceiling.entry, OVERHEAD_ENTRY);
        assert_eq!(at_ceiling.segment, OVERHEAD_SEGMENT);
    }

    #[test]
    fn measured_chain_stays_within_the_bound_at_several_body_sizes() {
        let bodies = [
            page(&[]),
            page(&[None]),
            page(&[Some(0); 100]),
            realistic_page(),
            costliest_page_of_length(65_536),
            costliest_admissible_page(),
        ];
        for body in bodies {
            let body_len = u64::try_from(body.len()).unwrap();
            assert_within_bound(
                body_len,
                measure(body, worst_case_admissible_headers(), None),
            );
        }
    }

    #[test]
    fn hostile_byte_patterns_stay_within_the_array_of_integers_bound() {
        // 0xFF is the worst case for the array-of-integers stage: three digits per element.
        // 0x22 and 0x5C are the worst cases for any JSON string encoder on the path. 0x00 is the
        // worst case for a control-character escape.
        let patterns: [(&str, BytePattern); 5] = [
            ("all_0xff", |_| 0xFF),
            ("all_quote_0x22", |_| 0x22),
            ("all_backslash_0x5c", |_| 0x5C),
            ("all_nul_0x00", |_| 0x00),
            ("repeating_mix", |index| {
                [0xFF_u8, 0x22, 0x5C, 0x00, 0x7F, 0x80][index % 6]
            }),
        ];
        for (label, generator) in patterns {
            for length in [0_usize, 1, 3, 4, 1024, 65_536] {
                let body: Vec<u8> = (0..length).map(generator).collect();
                let exact = exact_json_integer_array_bytes(&body);
                let bound = json_integer_array_bytes(u64::try_from(length).unwrap()).unwrap();
                assert!(
                    exact <= bound,
                    "{label} at {length} bytes wrote {exact} against a bound of {bound}"
                );
            }
        }

        // The same statement at the ingress ceiling, where the margin is thinnest: an all-0xFF
        // body pays three digits for every byte, and the bound still covers it by exactly one.
        let all_high = vec![0xFF_u8; usize::try_from(C1_MAX_RESPONSE_BODY_BYTES).unwrap()];
        assert_eq!(
            json_integer_array_bytes(C1_MAX_RESPONSE_BODY_BYTES).unwrap()
                - exact_json_integer_array_bytes(&all_high),
            1
        );
    }

    #[test]
    fn a_realistic_full_page_stays_within_the_bound() {
        let body = realistic_page();
        let length = body.len();
        assert!(
            u64::try_from(length).unwrap() <= C1_MAX_RESPONSE_BODY_BYTES,
            "a 100-row page of {length} bytes must fit the chosen ingress ceiling"
        );
        let realistic = measure(body, worst_case_admissible_headers(), None);
        assert_within_bound(u64::try_from(length).unwrap(), realistic);
        // The second headline measurement: 20_135 ingress bytes reach disk at 177_389, an 8.809x
        // expansion, under the 9.529x the memo-padded page at the ceiling pays.
        assert_eq!(length, 20_135);
        assert_eq!(realistic.segment, 177_389);
        assert_eq!(
            realistic.segment * 1000 / u64::try_from(length).unwrap(),
            8_809
        );
    }

    #[test]
    fn an_authenticated_private_segment_stays_within_the_bound() {
        assert_within_bound(
            C1_MAX_RESPONSE_BODY_BYTES,
            measure(
                costliest_admissible_page(),
                worst_case_admissible_headers(),
                Some([3_u8; 12]),
            ),
        );
    }

    /// Strictly increasing, not merely nondecreasing: a `derive` that returned a constant, or that
    /// dropped the body term at some stage, satisfies `>=` at every sample and fails here.
    ///
    /// The sampled domain is the whole `0 ..= 1 MiB` range the binary search in
    /// `a_one_mebibyte_segment_ceiling_cannot_host_the_shipped_c1_ceiling` walks, not just the
    /// shipped ceiling. The stride is larger than the 3-byte base64 group, so every stage really
    /// does move between consecutive samples.
    #[test]
    fn the_bound_is_strictly_increasing_in_the_ingress_ceiling() {
        let mut previous = c1_physical_bound(0).unwrap();
        for body_len in (0..=SMALLEST_CONFIGURED_SEGMENT_CEILING_BYTES)
            .step_by(997)
            .skip(1)
        {
            let current = c1_physical_bound(body_len).unwrap();
            assert!(current.max_response_body_bytes() > previous.max_response_body_bytes());
            assert!(current.max_retained_envelope_bytes() > previous.max_retained_envelope_bytes());
            assert!(
                current.max_observation_payload_bytes() > previous.max_observation_payload_bytes()
            );
            assert!(current.max_batch_bytes() > previous.max_batch_bytes());
            assert!(current.max_entry_bytes() > previous.max_entry_bytes());
            assert!(current.max_segment_bytes() > previous.max_segment_bytes());
            previous = current;
        }
    }

    #[test]
    fn the_derivation_errors_rather_than_wrapping() {
        for input in [u64::MAX, u64::MAX / 2, u64::MAX / 4, u64::MAX / 8] {
            assert!(
                matches!(
                    c1_physical_bound(input),
                    Err(SupervisorError::InvalidValue(_))
                ),
                "c1_physical_bound({input}) must refuse rather than wrap"
            );
        }
    }

    /// The smallest `SpoolConfig::max_segment_bytes` configured anywhere in the tree, which the
    /// anchor deliberately excludes: the kill-fault child binary and two integration fixtures.
    const SMALLEST_CONFIGURED_SEGMENT_CEILING_BYTES: u64 = 1024 * 1024;

    /// Pins the relationship the compile-time guard asserts, so a change to either constant fails
    /// here with the numbers in hand rather than only as a `const` assertion.
    #[test]
    fn the_chosen_ceiling_stays_strictly_under_the_hosting_anchor() {
        let bound = c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES).unwrap();
        assert!(
            bound.max_segment_bytes() < SMALLEST_HOSTING_SEGMENT_CEILING_BYTES,
            "segment bound {} must stay under the 4 MiB hosting anchor",
            bound.max_segment_bytes()
        );
        // 2_751_948 physical segment bytes against the 4_194_304 byte anchor: 1_442_356 bytes
        // (1.38 MiB) of headroom, with 65.6% of the anchor consumed.
        assert_eq!(bound.max_segment_bytes(), 2_751_948);
        let headroom = SMALLEST_HOSTING_SEGMENT_CEILING_BYTES - bound.max_segment_bytes();
        assert_eq!(headroom, 1_442_356);
        assert_eq!(
            bound.max_segment_bytes() * 1000 / SMALLEST_HOSTING_SEGMENT_CEILING_BYTES,
            656
        );
    }

    /// The anchor excludes the 1 MiB configurations because no C1 read runs under them. That
    /// exclusion has a consequence, and this test states it: the shipped bound does not fit a 1 MiB
    /// segment ceiling. A 1 MiB spool is therefore not treated as a C1 host, which is why the
    /// runtime configuration check is load-bearing rather than decorative.
    ///
    /// Whether the ~82 KiB of ingress a 1 MiB ceiling does admit would hold a full 100-row page is
    /// a judgment about the source, not a measurement of it: the realistic page measured in this
    /// module is 20,135 bytes, and how much longer a page carrying maximal memo text could be is
    /// not something this module observes.
    #[test]
    fn a_one_mebibyte_segment_ceiling_cannot_host_the_shipped_c1_ceiling() {
        let bound = c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES).unwrap();
        assert!(
            bound.max_segment_bytes() > SMALLEST_CONFIGURED_SEGMENT_CEILING_BYTES,
            "the shipped bound {} was expected not to fit a 1 MiB segment ceiling",
            bound.max_segment_bytes()
        );

        // The fixed allowances alone, before a single ingress byte, already consume a quarter of a
        // 1 MiB ceiling.
        assert_eq!(c1_physical_bound(0).unwrap().max_segment_bytes(), 266_432);

        // The largest ingress ceiling that fits under 1 MiB at all. The search assumes the bound
        // is nondecreasing over the whole `0 ..= 1 MiB` search domain, which
        // `the_bound_is_strictly_increasing_in_the_ingress_ceiling` samples across exactly that
        // range; the two assertions after the loop then check the answer directly, so the result
        // does not rest on the search's assumption alone.
        let mut low = 0_u64;
        let mut high = SMALLEST_CONFIGURED_SEGMENT_CEILING_BYTES;
        while low < high {
            let middle = low + (high - low).div_ceil(2);
            if c1_physical_bound(middle).unwrap().max_segment_bytes()
                < SMALLEST_CONFIGURED_SEGMENT_CEILING_BYTES
            {
                low = middle;
            } else {
                high = middle - 1;
            }
        }
        assert_eq!(low, 82_491);
        assert!(
            c1_physical_bound(low).unwrap().max_segment_bytes()
                < SMALLEST_CONFIGURED_SEGMENT_CEILING_BYTES,
            "{low} ingress bytes must still fit a 1 MiB segment ceiling"
        );
        assert!(
            c1_physical_bound(low + 1).unwrap().max_segment_bytes()
                >= SMALLEST_CONFIGURED_SEGMENT_CEILING_BYTES,
            "one ingress byte past {low} must not fit a 1 MiB segment ceiling"
        );
        assert!(
            low < 100 * 1024,
            "a 1 MiB spool admits under 100 KiB of ingress, measured at {low} bytes"
        );
    }

    #[test]
    fn the_expansion_is_multiplicative_not_a_fixed_overhead() {
        // A prior attempt claimed that the response body plus 16 KiB bounds one spool segment.
        // It does not: the body passes an array-of-integers encoder and three base64 encoders, so
        // the growth is multiplicative. This test pins that fact against the real chain.
        let measured = measure(
            costliest_admissible_page(),
            worst_case_admissible_headers(),
            None,
        );
        let refuted = C1_MAX_RESPONSE_BODY_BYTES + 16 * 1024;
        assert!(
            measured.segment > refuted,
            "a body-plus-16-KiB claim would have under-reserved: measured {} against {refuted}",
            measured.segment
        );
        assert!(
            measured.segment >= C1_MAX_RESPONSE_BODY_BYTES * 9,
            "expected at least a 9x physical expansion, measured {}",
            measured.segment
        );
        let bound = c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES).unwrap();
        // The headline measurement the module documentation quotes: 2_498_092 physical segment
        // bytes for the costliest admissible 262_144 byte page, a 9.529x expansion that consumes
        // 90.7% of the derived bound.
        assert_eq!(measured.segment, 2_498_092);
        assert_eq!(measured.segment * 1000 / C1_MAX_RESPONSE_BODY_BYTES, 9_529);
        assert_eq!(measured.segment * 1000 / bound.max_segment_bytes(), 907);
        assert!(measured.segment <= bound.max_segment_bytes());
    }

    /// Length of the base64 text a **real** encoder on this path writes for `count` input bytes.
    ///
    /// `ObservationDraft::payload` carries `#[serde(with = "base64_bytes")]` and is stage 3 of the
    /// chain, so replacing its bytes and serializing measures the encoder itself. An earlier
    /// revision checked `base64_bytes` only against a restatement of `4 * ceil(n / 3)`, which a
    /// systematic error in the model would have satisfied.
    fn real_observation_base64_len(observation: &ObservationDraft, count: usize) -> u64 {
        let mut probe = observation.clone();
        probe.payload = vec![0x5A_u8; count];
        let value = serde_json::to_value(&probe).unwrap();
        u64::try_from(value["payload"].as_str().unwrap().len()).unwrap()
    }

    /// The same measurement against the *other* real encoder on the path: `joshi-spool` has its own
    /// `base64_bytes` serde module, used for stages 5 and 6.
    fn real_entry_base64_len(entry: &EvidenceBatchEntry, count: usize) -> u64 {
        let mut probe = entry.clone();
        probe.exact_policy_bytes = vec![0x5A_u8; count];
        let value = serde_json::to_value(&probe).unwrap();
        u64::try_from(value["exactPolicyBytes"].as_str().unwrap().len()).unwrap()
    }

    #[test]
    fn the_base64_expansion_matches_the_real_encoders() {
        // A deliberately small page: the probes below serialize this entry hundreds of times,
        // and the encoder identity does not depend on what the surrounding record holds.
        let pending = prepare(page(&[]), worst_case_admissible_headers());
        let observation = only_observation(&pending);
        let entry = batch_entry(&pending);

        for count in 0..=256_usize {
            let expected = base64_bytes(u64::try_from(count).unwrap()).unwrap();
            assert_eq!(
                real_observation_base64_len(&observation, count),
                expected,
                "joshi-evidence base64 disagreed at {count} input bytes"
            );
            assert_eq!(
                real_entry_base64_len(entry, count),
                expected,
                "joshi-spool base64 disagreed at {count} input bytes"
            );
        }

        // And at the lengths this path really reaches, where an off-by-a-group model error would
        // matter most.
        for count in [65_536_usize, 262_144, 1_048_575, 1_048_576, 1_048_577] {
            let expected = base64_bytes(u64::try_from(count).unwrap()).unwrap();
            assert_eq!(real_observation_base64_len(&observation, count), expected);
            assert_eq!(real_entry_base64_len(entry, count), expected);
        }

        // Content independence, which is why the hostile byte patterns are bounded at the
        // array-of-integers stage alone: the same length encodes to the same length whatever the
        // bytes are.
        let lengths: Vec<usize> = [0x00_u8, 0xFF, 0x5A, 0x22]
            .into_iter()
            .map(|fill| {
                let mut probe = observation.clone();
                probe.payload = vec![fill; 3_001];
                serde_json::to_value(&probe).unwrap()["payload"]
                    .as_str()
                    .unwrap()
                    .len()
            })
            .collect();
        assert_eq!(lengths, vec![4004; 4]);
        assert_eq!(base64_bytes(3_001).unwrap(), 4004);
    }

    /// Decimal digits `serde_json` writes for one `u8` element of a bare `Vec<u8>`.
    fn digits(byte: u8) -> u64 {
        match byte {
            0..=9 => 1,
            10..=99 => 2,
            100..=255 => 3,
        }
    }

    /// The physical `serde_json` length of a `Vec<u8>` written as a JSON array of decimal integers.
    fn exact_json_integer_array_bytes(body: &[u8]) -> u64 {
        u64::try_from(serde_json::to_vec(body).unwrap().len()).unwrap()
    }

    /// The audited honesty defect: `4N + 2` was filed as an exact identity. It is not one. This
    /// test pins both the real identity and the size of the over-estimate, so the documentation
    /// cannot drift back.
    #[test]
    fn the_array_of_integers_expansion_is_a_strict_over_estimate_not_an_identity() {
        // The identity, checked against serde_json on a body covering every byte value.
        let mixed: Vec<u8> = (0..=255_u8).collect();
        let count = u64::try_from(mixed.len()).unwrap();
        let identity = mixed.iter().copied().map(digits).sum::<u64>() + (count - 1) + 2;
        assert_eq!(exact_json_integer_array_bytes(&mixed), identity);
        assert_eq!(exact_json_integer_array_bytes(&[]), 2);
        assert!(json_integer_array_bytes(count).unwrap() > identity);

        // The documented small cases, checked against serde_json rather than restated: three bytes
        // of 0xFF write as `[255,255,255]`, 13 bytes, against a bound of 14.
        assert_eq!(json_integer_array_bytes(0).unwrap(), 2);
        assert_eq!(json_integer_array_bytes(1).unwrap(), 6);
        assert_eq!(json_integer_array_bytes(3).unwrap(), 14);
        assert_eq!(exact_json_integer_array_bytes(&[255_u8; 3]), 13);

        // Tightest case: every element takes three digits, and the bound still over-states by one.
        let all_high = vec![0xFF_u8; 4096];
        assert_eq!(
            json_integer_array_bytes(4096).unwrap() - exact_json_integer_array_bytes(&all_high),
            1
        );

        // The realistic page: 11_129 bytes of slack, 13.8% of the bound.
        let page = realistic_page();
        let page_len = u64::try_from(page.len()).unwrap();
        let exact = exact_json_integer_array_bytes(&page);
        let bound = json_integer_array_bytes(page_len).unwrap();
        assert_eq!(page_len, 20_135);
        assert_eq!(exact, 69_413);
        assert_eq!(bound, 80_542);
        assert_eq!(bound - exact, 11_129);
        assert_eq!((bound - exact) * 1000 / bound, 138);
    }
}
