//! The C1 raw evidence boundary: one exact public-Solana HTTP response becomes one queued
//! observation, and nothing else.
//!
//! [`C1RawObservationAdapter::prepare_raw_page`] takes the finished response frame for the single
//! admitted `getSignaturesForAddress` page and returns one [`crate::PendingSegment`] holding one
//! durable ingest batch with exactly one observation. That batch's `source_events`, `assertions`,
//! `coverage_windows`, `coverage_gaps`, `coverage_recoveries` and `cursor_advances` are all empty,
//! and this module offers no way to populate them. A C1 read establishes no coverage, no cursor,
//! no absence and no source event.
//!
//! # What the retained page does not mean
//!
//! The retained payload is the exact response bytes: what came off the wire, never a
//! reserialization of a parse. The body *is* parsed once — by
//! [`joshi_sources::read_public_solana_c1_frame`], to refuse anything that is not the frozen C1
//! shape — but nothing here reads what that parse found. The outcome is discarded, and the two
//! readings a reader is most likely to make unaided are both wrong:
//!
//! - **An empty `result` array is not absence.** A page that returns zero rows says only that this
//!   one request, against one public endpoint, at one moment, came back with no rows. It is not a
//!   claim that the address has no signatures, not a claim that some range was covered and found
//!   empty, and not a gap detection. Absence in JOSHI is carried by coverage evidence, and this
//!   adapter emits none of it.
//! - **A row's `confirmationStatus` of `finalized` is a retained provider claim, not a JOSHI
//!   finality fact.** It is a string a public endpoint placed in a response body, kept because it
//!   was said and not because it is true. The observation therefore carries no chain location at
//!   all: [`joshi_evidence::ChainLocation::commitment`] is where a JOSHI finality determination
//!   would live, and this adapter never writes one, nor a slot, transaction index, instruction
//!   path or log index.
//!
//! # Clocks this adapter does not have
//!
//! The public endpoint gives no trustworthy provider clock for this read, so the observation's
//! event time is [`ProviderEventTime::Missing`] with a stated reason rather than a time inferred
//! from the payload. The adapter is handed an already-finished frame, so it also has no wall
//! reading taken immediately before the request and sets `requested_at` to `None`; the durable
//! reservation instant is used as the justified acquisition start. It observes no monotonic clock
//! either, so both monotonic readings are zero in a clock domain named
//! `c1-no-monotonic-clock:<installation>:<reservation>` — the zero elapsed that follows is a
//! placeholder in a domain that declares itself absent, never a latency measurement.
//! `persisted_at` carries the frame's provider-receipt instant forward. That is a lower bound on
//! the instant this record is actually persisted rather than a measurement of it, and it is a
//! lower bound only because the two wall instants this adapter is handed are checked against each
//! other: a frame whose receipt instant precedes its reservation instant is refused, because the
//! acquisition interval it would record runs backwards.
//!
//! Every claim in this section is pinned by the tests
//! `clocks_this_adapter_does_not_have_are_recorded_as_absent_not_as_readings` and
//! `a_frame_received_before_its_reservation_is_refused` below: the domain name, both zero readings,
//! the zero elapsed, `requested_at`, `started_at` and `persisted_at` each fail a test if they are
//! changed to their opposites.
//!
//! # The physical bound closes before durability, never after
//!
//! [`C1PhysicalBoundV1`] is taken as a constructor argument and enforced twice: a response body
//! longer than [`C1PhysicalBoundV1::max_response_body_bytes`] is refused before any evidence is
//! built, and a finished queue item whose `exact_entry_bytes` exceeds
//! [`C1PhysicalBoundV1::max_entry_bytes`] is refused before it can be handed back for durability.
//!
//! An earlier revision of this module called the second check unreachable "because every stage of
//! the derivation is an upper bound on this exact shape". That was false, and this repo measured
//! the counterexample. The derivation bounds the response *body*; the retained envelope carries
//! more than the body, and `joshi_sources::RawSourceFrame::safe_headers` is an unbounded `Vec`
//! covered only by one fixed allowance for every non-body envelope field. A long enough header
//! list therefore drives a tiny body past the entry ceiling, which the test
//! `an_unbounded_safe_header_set_drives_a_small_body_past_the_entry_ceiling` measures on an
//! 88-byte body.
//!
//! What actually holds is a precondition enforced one step earlier. Admission runs the shared
//! safe-header allowlist ([`joshi_sources::public_solana_c1_safe_headers_are_bounded`]): at most
//! four header names, each value at most 256 bytes, which is roughly a kilobyte retained and about
//! two once JSON-escaped — inside the fixed allowance the derivation reserves for the whole
//! non-body envelope, whose real cost at exactly that worst-case header set
//! [`super::physical_size`] measures. An admitted frame therefore cannot reach the entry ceiling.
//! That is an argument about one call path rather than a property of the shape, so the check
//! stays: the alternative is discovering an under-reservation after a durability result.
//!
//! Neither check is a segment-level check: comparing the derived segment bound against the
//! configured `SpoolConfig::max_segment_bytes` is the runtime's separate obligation.
//!
//! # Admission
//!
//! Admission is two refusals, and neither restates a rule that already exists elsewhere.
//!
//! The **frame** is admitted by [`joshi_sources::read_public_solana_c1_frame`], the same wire
//! contract reader the C1 request path uses. It pins the source, the adapter contract version, the
//! transport, the stream class, the direction, the content type, a positive receipt stamp, the
//! connection epoch, the sequence, an HTTP status of exactly 200 and the safe-header allowlist,
//! and then reads the body against the frozen JSON-RPC schema. A prior revision of this file
//! checked only the source and the transport and admitted everything else, including an
//! `OutboundControl` request frame whose body carried a credential — which it then retained
//! verbatim and stamped as a response. Delegating is what closes that, and it is why this module
//! holds no envelope predicate of its own. A fixture frame belongs to the sealed C0 path and is
//! refused here as an envelope mismatch; the C0 adapter admits fixture transport only and refuses
//! this frame symmetrically.
//!
//! The row bound handed to that reader is [`joshi_sources::PUBLIC_SOLANA_C1_MAX_ROWS`], the
//! schema's own maximum. This adapter is handed a finished frame and never sees the request, so it
//! cannot enforce a smaller registered row bound; that belongs to the layer that closed the
//! request and knows which bound it asked for.
//!
//! The **reservation** must be the C1 one: [`super::C1_SOURCE_KEY`], [`super::C1_OPERATION_KEY`]
//! and [`crate::AUTHORITY_CEILING`]. This adapter stamps the C1 locator and the C1 source variant
//! on whatever it is handed and propagates the reservation's authority string into the queue item,
//! so admitting a foreign reservation would label that reservation's evidence a C1 page.

use crate::{AUTHORITY_CEILING, AttemptReservation, PendingSegment, Result, SupervisorError};
use joshi_domain::{BatchDigest, OpenVariant, StableString, UtcTimestamp};
use joshi_evidence::{DurableIngestBatch, EvidenceDraft};
use joshi_sources::{
    EvidenceContext, LogicalSourceLocator, PUBLIC_SOLANA_C1_MAX_ROWS, PUBLIC_SOLANA_C1_METHOD,
    ProviderEventTime, RawSourceFrame, UnixMillis,
};

use super::physical_size::{C1_MAX_RESPONSE_BODY_BYTES, C1PhysicalBoundV1, c1_physical_bound};
use super::{C1_OPERATION_KEY, C1_SOURCE_KEY};

/// Store policy contract governing every C1 raw page retained by this adapter.
pub const C1_RAW_POLICY_CONTRACT: &str = "joshi.store.policy.c1_public_raw.v1";

/// Observation source variant for the one admitted C1 page shape.
pub const C1_RAW_OBSERVATION_VARIANT: &str = "public_solana_c1_raw_page";

/// The exact policy document retained beside every C1 raw batch.
///
/// It states two things and no others: the observation storage for this source is a public source,
/// and a coverage gap on it is informational. It asserts no coverage, no finality and no absence,
/// because a C1 read establishes none of them.
const C1_RAW_POLICY_BYTES: &[u8] = br#"{"observationStorage":{"solana_public_http":"public_source"},"coverageGapSeverity":{"solana_public_http":"informational"}}"#;

/// Stated reason for the missing provider event time on every C1 raw page.
const C1_MISSING_PROVIDER_CLOCK_REASON: &str =
    "public_endpoint_response_carries_no_trustworthy_provider_clock";

/// Monotonic clock domain prefix declaring that this adapter reads no monotonic clock.
const C1_ABSENT_MONOTONIC_CLOCK_DOMAIN: &str = "c1-no-monotonic-clock";

/// Endpoint-shaped substrings refused in redacted request fingerprint material. The material
/// identifies a logical request; a URL, host or header value would defeat the redaction.
///
/// Each entry is load bearing on its own: the test
/// `every_endpoint_shaped_needle_refuses_material_that_contains_it` probes the guard once per
/// needle, in both ASCII cases, so deleting any one of the four fails a test rather than silently
/// widening what may be hashed.
const ENDPOINT_SHAPED_NEEDLES: [&str; 4] = ["http", "://", "api.", "solana.com"];

/// Turns one exact C1 HTTP response into one queued raw observation under a prior reservation.
///
/// The adapter holds the physical byte bound it enforces and the validated source variant it
/// stamps on every observation. It holds no endpoint, no client, no cursor and no coverage state.
#[derive(Clone, Debug)]
pub struct C1RawObservationAdapter {
    bound: C1PhysicalBoundV1,
    source_variant: OpenVariant,
}

impl C1RawObservationAdapter {
    /// Binds the adapter to the shipped C1 physical byte bound and closes the wire validity of its
    /// fixed vocabulary once, rather than on every page.
    ///
    /// The bound is an argument rather than a constant so the value this adapter enforces is the
    /// same value a caller can record as evidence, but it is not a free parameter: only the bound
    /// derived from [`C1_MAX_RESPONSE_BODY_BYTES`] is admitted. A smaller one disagrees with the
    /// ingress ceiling the shared wire contract reader itself enforces, so the two layers would
    /// mean different things by "a page"; a larger one would have this adapter build — and this
    /// process allocate roughly 9.5x — a body no C1 response may carry. The whole bound is
    /// compared rather than only its ingress field, because a value can only come from
    /// [`super::physical_size::c1_physical_bound`] and equality there is equality of the entire
    /// derivation.
    ///
    /// # Errors
    ///
    /// Refuses any bound other than the one derived from the shipped C1 ingress ceiling, and
    /// refuses a source variant that cannot satisfy the shared wire contract.
    pub fn new(bound: C1PhysicalBoundV1) -> Result<Self> {
        if bound != c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES)? {
            return Err(SupervisorError::InvalidValue(format!(
                "the C1 raw adapter admits only the physical bound derived from the shipped \
                 {C1_MAX_RESPONSE_BODY_BYTES} byte ingress ceiling"
            )));
        }
        Ok(Self {
            bound,
            source_variant: OpenVariant::known(C1_RAW_OBSERVATION_VARIANT)?,
        })
    }

    /// Prepares the single queue item for one exact C1 response page.
    ///
    /// The response body is retained verbatim inside the observation payload. The resulting batch
    /// carries exactly one observation and nothing else: no source event, no assertion, no coverage
    /// window, no coverage gap, no coverage recovery and no cursor advance.
    ///
    /// # Errors
    ///
    /// Refuses a reservation that is not the C1 source, operation and authority; a response body
    /// over [`C1PhysicalBoundV1::max_response_body_bytes`]; a frame that
    /// [`joshi_sources::read_public_solana_c1_frame`] does not admit as the exact C1 envelope and
    /// body shape; a frame received before its reservation was taken; a finished entry over
    /// [`C1PhysicalBoundV1::max_entry_bytes`]; and any value that cannot satisfy the shared
    /// evidence, digest or spool contracts. It also refuses request fingerprint material that
    /// looks like an endpoint, which the pinned reservation identity makes unreachable through
    /// this function today; that guard is on the material format itself and is tested directly.
    pub fn prepare_raw_page(
        &self,
        reservation: &AttemptReservation,
        frame: RawSourceFrame,
    ) -> Result<PendingSegment> {
        admit_reservation(reservation)?;
        let body_bytes = u64::try_from(frame.body.len()).map_err(|_| {
            SupervisorError::InvalidValue("C1 response body length exceeds u64".into())
        })?;
        if body_bytes > self.bound.max_response_body_bytes() {
            return Err(SupervisorError::InvalidValue(format!(
                "C1 response body is {body_bytes} bytes, over the {} byte physical response \
                 ceiling; nothing was built",
                self.bound.max_response_body_bytes()
            )));
        }
        admit_frame(&frame)?;
        self.build_admitted_page(reservation, frame)
    }

    /// Builds the queue item for a frame and reservation that admission has already accepted.
    ///
    /// Split out from [`Self::prepare_raw_page`] so the entry-stage refusal at the end of this
    /// function has a test that actually reaches it. Admission bounds the retained envelope, so no
    /// admitted frame can drive the entry past its ceiling; a test calls this function directly
    /// with the header-heavy frame admission refuses, and deleting the refusal fails that test.
    fn build_admitted_page(
        &self,
        reservation: &AttemptReservation,
        frame: RawSourceFrame,
    ) -> Result<PendingSegment> {
        let material = redacted_fingerprint_material(
            reservation.source_key.as_str(),
            reservation.operation_key.as_str(),
        )?;
        let received_at = unix_millis_to_utc(frame.received_at)?;
        refuse_inverted_acquisition_interval(reservation.reserved_at, received_at)?;
        let namespace = occurrence_namespace(reservation);
        let context = EvidenceContext {
            redacted_request_fingerprint_material: material,
            parent_acquisition_id: None,
            locator: LogicalSourceLocator::SolanaPublicHttp {
                method: PUBLIC_SOLANA_C1_METHOD,
            },
            source_variant: self.source_variant.clone(),
            source_cursor: None,
            source_events: Vec::new(),
            provider_event_time: ProviderEventTime::Missing {
                reason: C1_MISSING_PROVIDER_CLOCK_REASON.to_owned(),
            },
            chain_slot: None,
            transaction_index: None,
            instruction_path: Vec::new(),
            log_index: None,
            finality: None,
            acquisition_started_at: reservation.reserved_at,
            requested_at: None,
            monotonic_clock_id: format!("{C1_ABSENT_MONOTONIC_CLOCK_DOMAIN}:{namespace}"),
            acquisition_started_monotonic_ns: 0,
            received_monotonic_ns: 0,
            persisted_at: received_at,
            occurrence_namespace: namespace,
        };
        let EvidenceDraft::Observation(observation) =
            joshi_sources::observation_draft(frame, context)?
        else {
            return Err(SupervisorError::InvalidState(
                "the C1 raw page did not produce an observation".into(),
            ));
        };
        let mut batch = DurableIngestBatch {
            contract_version: StableString::new(
                joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION,
            )?,
            batch_id: StableString::new(format!("batch:c1:{}", reservation.reservation_id))?,
            expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64)))?,
            observations: vec![observation],
            source_events: Vec::new(),
            assertions: Vec::new(),
            coverage_windows: Vec::new(),
            coverage_gaps: Vec::new(),
            coverage_recoveries: Vec::new(),
            cursor_advances: Vec::new(),
        };
        batch.expected_digest = joshi_store::SqliteStore::canonical_batch_digest(&batch)
            .map_err(|error| SupervisorError::InvalidValue(error.to_string()))?;
        let exact_batch_bytes = serde_json::to_vec(&batch)?;
        let pending = crate::prepare_evidence_batch(
            reservation.clone(),
            &batch,
            exact_batch_bytes,
            C1_RAW_POLICY_CONTRACT,
            C1_RAW_POLICY_BYTES.to_vec(),
        )?;
        refuse_oversized_entry(&self.bound, pending.exact_entry_bytes)?;
        Ok(pending)
    }
}

/// Closes the entry stage of the physical policy over a finished queue item, before that item can
/// be handed back and become a durability result.
fn refuse_oversized_entry(bound: &C1PhysicalBoundV1, exact_entry_bytes: u64) -> Result<()> {
    if exact_entry_bytes > bound.max_entry_bytes() {
        return Err(SupervisorError::InvalidValue(format!(
            "C1 queue entry is {exact_entry_bytes} bytes, over the {} byte physical entry \
             ceiling; it is refused before any durability result",
            bound.max_entry_bytes()
        )));
    }
    Ok(())
}

/// Admits only the one C1 frame shape, by asking the shared wire contract reader rather than by
/// holding a second opinion about what that shape is.
///
/// The returned outcome is deliberately discarded. Whether the provider answered with a page or
/// with a typed JSON-RPC refusal, the retained bytes are the same exact bytes and this adapter
/// records neither reading; the call is made for its refusals.
fn admit_frame(frame: &RawSourceFrame) -> Result<()> {
    joshi_sources::read_public_solana_c1_frame(frame, PUBLIC_SOLANA_C1_MAX_ROWS)
        .map(|_outcome| ())
        .map_err(|error| {
            SupervisorError::InvalidValue(format!(
                "the C1 raw adapter admits only a conforming public-Solana C1 response frame: \
                 {error}"
            ))
        })
}

/// Admits only a reservation taken for the one C1 source, operation and authority.
fn admit_reservation(reservation: &AttemptReservation) -> Result<()> {
    if reservation.source_key.as_str() != C1_SOURCE_KEY
        || reservation.operation_key.as_str() != C1_OPERATION_KEY
    {
        return Err(SupervisorError::InvalidValue(format!(
            "the C1 raw adapter stamps the C1 locator and source variant, so it admits only a \
             reservation for source {C1_SOURCE_KEY} and operation {C1_OPERATION_KEY}"
        )));
    }
    if reservation.authority.as_str() != AUTHORITY_CEILING {
        return Err(SupervisorError::InvalidValue(format!(
            "a C1 reservation must carry the {AUTHORITY_CEILING} authority ceiling; this adapter \
             propagates that string into the queue item rather than checking it later"
        )));
    }
    Ok(())
}

/// Refuses an acquisition interval that runs backwards.
///
/// `acquisition_started_at` is the durable reservation instant and `persisted_at` carries the
/// frame's receipt instant. Nothing relates those two clocks by construction — they are two wall
/// readings taken by different layers — so a frame stamped before its own reservation would record
/// an acquisition that finished before it started, and a `persisted_at` that bounds nothing. Equal
/// instants are admitted: the receipt stamp has millisecond resolution and the reservation instant
/// is microsecond-aligned, so a genuinely simultaneous pair can compare equal.
fn refuse_inverted_acquisition_interval(
    reserved_at: UtcTimestamp,
    received_at: UtcTimestamp,
) -> Result<()> {
    if received_at < reserved_at {
        return Err(SupervisorError::InvalidValue(
            "the C1 frame was received before its reservation was taken; the acquisition interval \
             would run backwards and persisted_at would bound nothing"
                .into(),
        ));
    }
    Ok(())
}

/// Builds the occurrence namespace that keeps two retained C1 pages distinct records.
///
/// [`joshi_sources::observation_draft`] derives both the acquisition ID and the observation ID from
/// exactly `(namespace, connection_epoch, sequence)`, and the observation ID is a store primary
/// key; that function documents the uniqueness precondition as its caller's to discharge. The
/// admitted C1 frame shape fixes `connection_epoch` and `sequence` at 1, so the namespace is the
/// only part of that triple that can vary at all. The installation ID alone is constant across
/// every reservation on one installation, so two reservations retaining two pages would have
/// collided on one primary key. The reservation ID is the per-attempt identity the supervisor
/// journal already mints uniquely, so it is what discharges the precondition here.
fn occurrence_namespace(reservation: &AttemptReservation) -> String {
    format!(
        "{}:{}",
        reservation.installation_id, reservation.reservation_id
    )
}

/// Builds the non-secret logical request material that is hashed into the request fingerprint.
///
/// The material names the reservation's logical source and operation and nothing else. It carries
/// no endpoint, URL, host, header or credential, and material that looks like one is refused rather
/// than hashed. It takes the two keys as strings rather than the reservation so every needle can be
/// probed on material a `SourceKey` cannot even hold: `SourceKey::new` refuses `/`, so `://` is
/// unreachable through that type.
fn redacted_fingerprint_material(source_key: &str, operation_key: &str) -> Result<String> {
    let material = format!("c1_public_raw:{source_key}:{operation_key}");
    let lowered = material.to_ascii_lowercase();
    if ENDPOINT_SHAPED_NEEDLES
        .iter()
        .any(|needle| lowered.contains(needle))
    {
        return Err(SupervisorError::InvalidValue(
            "C1 request fingerprint material must carry no endpoint, URL, host, header or \
             credential"
                .into(),
        ));
    }
    Ok(material)
}

/// Converts a source-frame receipt instant into the shared UTC wire timestamp.
fn unix_millis_to_utc(value: UnixMillis) -> Result<UtcTimestamp> {
    let nanos = i128::from(value.0).checked_mul(1_000_000).ok_or_else(|| {
        SupervisorError::InvalidValue("C1 frame receipt instant overflows".into())
    })?;
    let value = time::OffsetDateTime::from_unix_timestamp_nanos(nanos).map_err(|_| {
        SupervisorError::InvalidValue("C1 frame receipt instant is outside UTC range".into())
    })?;
    UtcTimestamp::new(value).map_err(|error| SupervisorError::InvalidValue(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        AttemptKind, GenerationId, OperationKey, ProtectionProfile, QueueClass, ReservationId,
        SourceKey,
    };
    use bytes::Bytes;
    use joshi_domain::SourceId as DomainSourceId;
    use joshi_evidence::{Boundary, CoverageScope, ObservationDraft};
    use joshi_sources::{
        ContentType, FrameDirection, RetainedFrameEnvelope, SafeHeader, SourceId, StreamClass,
        Transport,
    };
    use joshi_spool::{ProtectionDomainId, SpoolEntry};

    /// Base58 of 64 bytes of `0x01`. The frozen schema requires a signature that decodes to exactly
    /// 64 bytes, and every page below is read by the shared reader, so a wrong constant here fails
    /// those tests rather than passing silently.
    const SIGNATURE: &str =
        "2AXDGYSE4f2sz7tvMMzyHvUfcoJmxudvdhBcmiUSo6ijwfYmfZYsKRxboQMPh3R4kUhXRVdtSXFXMheka4Rc4P2";

    /// The receipt instant every test frame carries: 2026-08-16T12:00:00Z.
    const RECEIVED_AT_MILLIS: i64 = 1_786_881_600_000;

    /// One second before that receipt instant, so the recorded acquisition interval runs forwards.
    const RESERVED_AT: &str = "2026-08-16T11:59:59.000000Z";

    fn page_with_memo(memo: &str) -> Vec<u8> {
        format!(
            r#"{{"jsonrpc":"2.0","result":[{{"signature":"{SIGNATURE}","slot":123,"err":null,"memo":{memo},"blockTime":1786881600,"confirmationStatus":"finalized"}}],"id":1}}"#
        )
        .into_bytes()
    }

    fn page() -> Vec<u8> {
        page_with_memo("null")
    }

    fn reservation() -> AttemptReservation {
        let reserved_at: UtcTimestamp = RESERVED_AT.parse().expect("timestamp");
        AttemptReservation {
            contract: crate::SUPERVISOR_CONTRACT_VERSION.into(),
            reservation_id: ReservationId::new("resv-c1-000001").expect("reservation ID"),
            installation_id: "inst-00000000000000000000000000000000".into(),
            source_key: SourceKey::new(C1_SOURCE_KEY).expect("source key"),
            operation_key: OperationKey::new(C1_OPERATION_KEY).expect("operation key"),
            generation: GenerationId::new(1),
            attempt_ordinal: 1,
            kind: AttemptKind::HttpRequest,
            scope: CoverageScope {
                source_id: DomainSourceId::new("solana.public_http.v1").expect("source ID"),
                family: OpenVariant::known("signatures_for_address").expect("family"),
                subject: None,
            },
            lower: Boundary::Wall { value: reserved_at },
            protection: ProtectionProfile::PublicIntegrity {
                domain: ProtectionDomainId::new("public-solana-c1").expect("protection domain"),
            },
            run: None,
            execution_claim: None,
            provider_plan: None,
            reserved_at,
            authority: AUTHORITY_CEILING.into(),
        }
    }

    fn frame(body: &[u8]) -> RawSourceFrame {
        RawSourceFrame {
            contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
            source: SourceId::SolanaPublicHttp,
            transport: Transport::Http,
            stream_class: StreamClass::Backfill,
            direction: FrameDirection::Inbound,
            content_type: ContentType::Json,
            received_at: UnixMillis(RECEIVED_AT_MILLIS),
            connection_epoch: 1,
            sequence: 1,
            http_status: Some(200),
            safe_headers: Vec::new(),
            body: Bytes::copy_from_slice(body),
        }
    }

    fn shipped_bound() -> C1PhysicalBoundV1 {
        c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES).expect("physical bound")
    }

    fn adapter() -> C1RawObservationAdapter {
        C1RawObservationAdapter::new(shipped_bound()).expect("adapter")
    }

    fn entry(pending: &PendingSegment) -> &joshi_spool::EvidenceBatchEntry {
        let SpoolEntry::EvidenceBatch(entry) = &pending.entry else {
            panic!("a C1 raw page must queue an evidence batch");
        };
        entry
    }

    fn decode_batch(pending: &PendingSegment) -> DurableIngestBatch {
        serde_json::from_slice(&entry(pending).exact_batch_bytes)
            .expect("retained batch bytes decode")
    }

    fn only_observation(pending: &PendingSegment) -> ObservationDraft {
        let mut batch = decode_batch(pending);
        assert_eq!(batch.observations.len(), 1, "exactly one observation");
        batch.observations.remove(0)
    }

    #[test]
    fn batch_carries_exactly_one_observation_and_no_source_event_coverage_or_cursor() {
        let pending = adapter()
            .prepare_raw_page(&reservation(), frame(&page()))
            .expect("prepared page");
        assert_eq!(pending.class, QueueClass::Evidence);
        let batch = decode_batch(&pending);
        assert_eq!(batch.observations.len(), 1);
        assert!(batch.source_events.is_empty(), "no source event");
        assert!(batch.assertions.is_empty(), "no assertion");
        assert!(batch.coverage_windows.is_empty(), "no coverage window");
        assert!(batch.coverage_gaps.is_empty(), "no coverage gap");
        assert!(batch.coverage_recoveries.is_empty(), "no coverage recovery");
        assert!(batch.cursor_advances.is_empty(), "no cursor advance");
        assert!(
            entry(&pending).cursor_candidates.is_empty(),
            "no cursor candidate"
        );
    }

    #[test]
    fn evidence_context_records_no_cursor_no_chain_location_and_a_missing_provider_clock() {
        let pending = adapter()
            .prepare_raw_page(&reservation(), frame(&page()))
            .expect("prepared page");
        let observation = only_observation(&pending);
        assert!(observation.observation.source_events.is_empty());
        assert!(observation.observation.source_cursor.is_none());
        assert!(observation.acquisition.source_cursor.is_none());
        assert!(
            observation.observation.chain.is_none(),
            "no chain slot, transaction index, instruction path, log index or finality"
        );
        assert_eq!(
            observation
                .observation
                .event_time
                .status
                .discriminator
                .as_str(),
            "source_missing"
        );
        assert!(observation.observation.event_time.lower.is_none());
        assert!(observation.observation.event_time.upper.is_none());
        assert_eq!(
            C1_MISSING_PROVIDER_CLOCK_REASON,
            "public_endpoint_response_carries_no_trustworthy_provider_clock"
        );
        assert_eq!(
            observation
                .observation
                .quality_code
                .as_ref()
                .map(joshi_domain::StableString::as_str),
            Some(
                "event_time_missing:public_endpoint_response_carries_no_trustworthy_provider_clock"
            ),
            "the missing provider clock carries its stated reason"
        );
        assert_eq!(
            observation
                .observation
                .source_variant
                .discriminator
                .as_str(),
            "public_solana_c1_raw_page"
        );
        assert_eq!(C1_RAW_OBSERVATION_VARIANT, "public_solana_c1_raw_page");
        assert_eq!(
            observation
                .observation
                .parse_disposition
                .discriminator
                .as_str(),
            "opaque"
        );
    }

    #[test]
    fn clocks_this_adapter_does_not_have_are_recorded_as_absent_not_as_readings() {
        let reservation = reservation();
        let pending = adapter()
            .prepare_raw_page(&reservation, frame(&page()))
            .expect("prepared page");
        let observation = only_observation(&pending);
        let received_at = unix_millis_to_utc(UnixMillis(RECEIVED_AT_MILLIS)).expect("receipt");

        // Spelled out rather than built from the constant under test: a domain named for a clock
        // this adapter does not read is the claim, so renaming the constant must fail here.
        assert_eq!(C1_ABSENT_MONOTONIC_CLOCK_DOMAIN, "c1-no-monotonic-clock");
        let domain = format!(
            "c1-no-monotonic-clock:{}:{}",
            reservation.installation_id, reservation.reservation_id
        );
        assert_eq!(
            observation
                .acquisition
                .clocks
                .monotonic_domain
                .as_ref()
                .map(joshi_domain::StableString::as_str),
            Some(domain.as_str()),
            "the monotonic domain must declare the absent clock and name this reservation"
        );
        let started = observation
            .acquisition
            .started_monotonic
            .as_ref()
            .expect("a declared-absent monotonic start");
        assert_eq!(started.clock_id.as_str(), domain);
        assert_eq!(started.nanoseconds.get(), 0, "no monotonic start is read");
        let received_monotonic = &observation.observation.timing.received_monotonic;
        assert_eq!(received_monotonic.clock_id.as_str(), domain);
        assert_eq!(
            received_monotonic.nanoseconds.get(),
            0,
            "no monotonic receipt is read"
        );
        assert_eq!(
            observation
                .acquisition
                .clocks
                .monotonic_elapsed_ns
                .map(joshi_domain::WireU64::get),
            Some(0),
            "the elapsed placeholder is zero, never a latency measurement"
        );

        assert!(
            observation.acquisition.clocks.requested_at.is_none(),
            "no wall reading was taken immediately before the request"
        );
        assert_eq!(
            observation.acquisition.started_at, reservation.reserved_at,
            "the durable reservation instant is the justified acquisition start"
        );
        assert_eq!(observation.acquisition.clocks.received_at, received_at);
        assert_eq!(
            observation.acquisition.clocks.persisted_at, received_at,
            "persisted_at carries the frame receipt instant forward"
        );
        assert_eq!(observation.observation.timing.persisted_at, received_at);
        assert!(
            observation.acquisition.started_at <= observation.acquisition.clocks.persisted_at,
            "the recorded acquisition interval runs forwards"
        );
    }

    #[test]
    fn a_frame_received_before_its_reservation_is_refused() {
        let received_at = unix_millis_to_utc(UnixMillis(RECEIVED_AT_MILLIS)).expect("receipt");
        let one_ms_later =
            UtcTimestamp::new(received_at.as_datetime() + time::Duration::milliseconds(1))
                .expect("timestamp");
        let mut reservation = reservation();
        reservation.reserved_at = one_ms_later;
        let error = adapter()
            .prepare_raw_page(&reservation, frame(&page()))
            .expect_err("an inverted acquisition interval is refused");
        assert!(
            error.to_string().contains("would run backwards"),
            "unexpected error: {error}"
        );

        reservation.reserved_at = received_at;
        adapter()
            .prepare_raw_page(&reservation, frame(&page()))
            .expect("equal instants are admitted");
    }

    #[test]
    fn two_reservations_never_collide_on_one_observation_id() {
        let first = reservation();
        let mut second = reservation();
        second.reservation_id = ReservationId::new("resv-c1-000002").expect("reservation ID");
        assert_eq!(
            first.installation_id, second.installation_id,
            "the installation ID is constant across reservations, so it cannot separate them"
        );

        let adapter = adapter();
        let first = only_observation(
            &adapter
                .prepare_raw_page(&first, frame(&page()))
                .expect("first page"),
        );
        let second = only_observation(
            &adapter
                .prepare_raw_page(&second, frame(&page()))
                .expect("second page"),
        );

        assert_ne!(
            first.observation.observation_id.as_str(),
            second.observation.observation_id.as_str(),
            "two reservations must not collide on one observation primary key"
        );
        assert_ne!(
            first.acquisition.acquisition_id.as_str(),
            second.acquisition.acquisition_id.as_str()
        );
        assert!(
            first
                .observation
                .observation_id
                .as_str()
                .contains("resv-c1-000001"),
            "the reservation identity is what makes the occurrence unique: {}",
            first.observation.observation_id
        );
    }

    #[test]
    fn retained_payload_is_the_response_body_verbatim_including_escapes() {
        let body = page_with_memo(r#""a \" quote, a \\ backslash and a \u0000 NUL escape""#);
        let pending = adapter()
            .prepare_raw_page(&reservation(), frame(&body))
            .expect("prepared page");
        let observation = only_observation(&pending);
        let envelope: RetainedFrameEnvelope =
            serde_json::from_slice(&observation.payload).expect("retained envelope decodes");
        assert_eq!(envelope.body, body, "retained bytes are the response bytes");
        let retained = String::from_utf8(envelope.body.clone()).expect("retained bytes are UTF-8");
        assert!(
            retained.contains(r"\u0000") && retained.contains(r"\\"),
            "the escapes are retained as written, so nothing reserialized a parse: {retained}"
        );
        assert_eq!(envelope.http_status, Some(200));
        assert_eq!(envelope.transport, Transport::Http);
    }

    #[test]
    fn a_typed_provider_refusal_page_is_retained_verbatim_and_not_interpreted() {
        let body = br#"{"jsonrpc":"2.0","error":{"code":-32005,"message":"rate limited"},"id":1}"#;
        let pending = adapter()
            .prepare_raw_page(&reservation(), frame(body))
            .expect("a typed provider refusal is a response and is retained");
        let observation = only_observation(&pending);
        let envelope: RetainedFrameEnvelope =
            serde_json::from_slice(&observation.payload).expect("retained envelope decodes");
        assert_eq!(
            envelope.body, body,
            "the refusal bytes are retained exactly as sent"
        );
        assert!(
            observation.observation.chain.is_none(),
            "a provider refusal establishes nothing at all"
        );
    }

    #[test]
    fn locator_is_the_public_solana_http_get_signatures_for_address_method() {
        let pending = adapter()
            .prepare_raw_page(&reservation(), frame(&page()))
            .expect("prepared page");
        let observation = only_observation(&pending);
        assert_eq!(
            observation
                .acquisition
                .source_locator
                .as_ref()
                .map(joshi_domain::StableString::as_str),
            Some("solana_public:http:getSignaturesForAddress")
        );
        assert_eq!(
            observation.acquisition.source_id.as_str(),
            "solana.public_http.v1"
        );
    }

    #[test]
    fn redacted_request_fingerprint_material_carries_no_endpoint_url_host_or_credential() {
        let material =
            redacted_fingerprint_material(C1_SOURCE_KEY, C1_OPERATION_KEY).expect("material");
        let lowered = material.to_ascii_lowercase();
        for needle in ENDPOINT_SHAPED_NEEDLES {
            assert!(
                !lowered.contains(needle),
                "fingerprint material {material} must not contain {needle}"
            );
        }
        assert_eq!(
            material,
            format!("c1_public_raw:{C1_SOURCE_KEY}:{C1_OPERATION_KEY}")
        );
    }

    #[test]
    fn every_endpoint_shaped_needle_refuses_material_that_contains_it() {
        // Stated here rather than read from the array under test: iterating the array would delete
        // a needle's own probe along with the needle, which is how three of these went unverified.
        const REQUIRED_NEEDLES: [&str; 4] = ["http", "://", "api.", "solana.com"];
        assert_eq!(
            ENDPOINT_SHAPED_NEEDLES, REQUIRED_NEEDLES,
            "the refused needle set is fixed; a change belongs in this test too"
        );
        for needle in REQUIRED_NEEDLES {
            for spelling in [needle.to_owned(), needle.to_ascii_uppercase()] {
                let source_key = format!("solana.public.mainnet{spelling}");
                let error = redacted_fingerprint_material(&source_key, C1_OPERATION_KEY)
                    .expect_err("endpoint-shaped material is refused rather than hashed");
                assert!(
                    error.to_string().contains("no endpoint"),
                    "needle {spelling} produced an unexpected error: {error}"
                );
            }
        }
        redacted_fingerprint_material(C1_SOURCE_KEY, C1_OPERATION_KEY)
            .expect("the shipped C1 keys carry no needle");
    }

    #[test]
    fn response_body_over_the_physical_bound_is_refused_before_any_evidence_is_built() {
        let adapter = adapter();
        let ceiling = usize::try_from(C1_MAX_RESPONSE_BODY_BYTES).expect("ceiling fits usize");
        let base = page_with_memo(r#""""#).len();

        let at_ceiling = page_with_memo(&format!(r#""{}""#, "a".repeat(ceiling - base)));
        assert_eq!(at_ceiling.len(), ceiling);
        adapter
            .prepare_raw_page(&reservation(), frame(&at_ceiling))
            .expect("a conforming body at the ceiling is admitted");

        let over_ceiling = page_with_memo(&format!(r#""{}""#, "a".repeat(ceiling - base + 1)));
        assert_eq!(over_ceiling.len(), ceiling + 1);
        let error = adapter
            .prepare_raw_page(&reservation(), frame(&over_ceiling))
            .expect_err("a body over the ceiling is refused");
        assert!(
            error.to_string().contains("physical response ceiling"),
            "unexpected error: {error}"
        );
    }

    /// A frame whose safe-header list is far outside the shared allowlist. The body is 88 bytes;
    /// the headers are what make the retained envelope enormous.
    fn header_heavy_frame() -> RawSourceFrame {
        let mut frame = frame(
            br#"{"jsonrpc":"2.0","result":[],"id":1,"padding":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#,
        );
        assert_eq!(frame.body.len(), 88, "an 88-byte body");
        frame.safe_headers = (0..8_000)
            .map(|_| SafeHeader {
                name: "retry-after".to_owned(),
                value: "a".repeat(256),
            })
            .collect();
        frame
    }

    #[test]
    fn an_unbounded_safe_header_set_drives_a_small_body_past_the_entry_ceiling() {
        let bound = shipped_bound();
        let error = adapter()
            .build_admitted_page(&reservation(), header_heavy_frame())
            .expect_err("the entry stage refuses the oversized queue item");
        let message = error.to_string();
        assert!(
            message.contains("physical entry ceiling"),
            "unexpected error: {message}"
        );
        assert!(
            message.contains(&bound.max_entry_bytes().to_string()),
            "the refusal names the ceiling it applied: {message}"
        );
    }

    #[test]
    fn an_unbounded_safe_header_set_is_refused_at_admission_before_that_entry_is_built() {
        let error = adapter()
            .prepare_raw_page(&reservation(), header_heavy_frame())
            .expect_err("the shared safe-header allowlist refuses the frame");
        assert!(
            error
                .to_string()
                .contains("conforming public-Solana C1 response frame"),
            "unexpected error: {error}"
        );

        let mut bounded = frame(&page());
        bounded.safe_headers = [
            "retry-after",
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
        ]
        .into_iter()
        .map(|name| SafeHeader {
            name: name.to_owned(),
            value: "a".repeat(256),
        })
        .collect();
        let pending = adapter()
            .prepare_raw_page(&reservation(), bounded)
            .expect("the full allowlisted header set is admitted");
        assert!(
            pending.exact_entry_bytes <= shipped_bound().max_entry_bytes(),
            "an admitted header set stays inside the entry ceiling"
        );
    }

    #[test]
    fn every_frame_envelope_field_the_shared_reader_pins_is_refused_here_too() {
        let mut cases: Vec<(&str, RawSourceFrame)> = Vec::new();

        let mut case = frame(&page());
        case.contract_version = "joshi.sources.adapter.v0".to_owned();
        cases.push(("a foreign adapter contract version", case));

        let mut case = frame(&page());
        case.source = SourceId::HeliusHttp;
        cases.push(("a non public-Solana source", case));

        let mut case = frame(&page());
        case.transport = Transport::Fixture;
        cases.push(("a fixture transport frame", case));

        let mut case = frame(&page());
        case.stream_class = StreamClass::Control;
        cases.push(("a control stream class", case));

        let mut case = frame(&page());
        case.direction = FrameDirection::OutboundControl;
        cases.push(("an outbound control frame", case));

        let mut case = frame(&page());
        case.content_type = ContentType::Text;
        cases.push(("a non-JSON content type", case));

        let mut case = frame(&page());
        case.received_at = UnixMillis(0);
        cases.push(("a zero receipt stamp", case));

        let mut case = frame(&page());
        case.received_at = UnixMillis(-1);
        cases.push(("a negative receipt stamp", case));

        let mut case = frame(&page());
        case.connection_epoch = 2;
        cases.push(("a second connection epoch", case));

        let mut case = frame(&page());
        case.sequence = 2;
        cases.push(("a second sequence number", case));

        let mut case = frame(&page());
        case.http_status = Some(429);
        cases.push(("a non-200 HTTP status", case));

        let mut case = frame(&page());
        case.http_status = None;
        cases.push(("an absent HTTP status", case));

        let mut case = frame(&page());
        case.safe_headers = vec![SafeHeader {
            name: "authorization".to_owned(),
            value: "secret".to_owned(),
        }];
        cases.push(("a header outside the allowlist", case));

        let mut case = frame(&page());
        case.body = Bytes::from_static(br#"{"jsonrpc":"2.0","result":[],"id":2}"#);
        cases.push(("a wrong JSON-RPC id", case));

        for (label, case) in cases {
            let error = adapter()
                .prepare_raw_page(&reservation(), case)
                .expect_err(label);
            assert!(
                error
                    .to_string()
                    .contains("conforming public-Solana C1 response frame"),
                "{label} produced an unexpected error: {error}"
            );
        }
    }

    #[test]
    fn an_outbound_request_frame_carrying_a_credential_is_refused_rather_than_retained() {
        let mut credential_bearing = frame(&page());
        credential_bearing.direction = FrameDirection::OutboundControl;
        credential_bearing.body = Bytes::from_static(
            br#"{"jsonrpc":"2.0","method":"getSignaturesForAddress","apiKey":"s3cr3t","id":1}"#,
        );
        let error = adapter()
            .prepare_raw_page(&reservation(), credential_bearing)
            .expect_err("a request frame is not a retained response");
        assert!(
            error
                .to_string()
                .contains("conforming public-Solana C1 response frame"),
            "unexpected error: {error}"
        );
        assert!(
            !error.to_string().contains("s3cr3t"),
            "the refusal never renders the rejected body back: {error}"
        );
    }

    #[test]
    fn a_reservation_that_is_not_the_c1_source_operation_and_authority_is_refused() {
        let adapter = adapter();

        let mut foreign_source = reservation();
        foreign_source.source_key = SourceKey::new("helius.mainnet").expect("source key");
        let error = adapter
            .prepare_raw_page(&foreign_source, frame(&page()))
            .expect_err("a foreign source key is refused");
        assert!(
            error.to_string().contains(C1_SOURCE_KEY),
            "unexpected error: {error}"
        );

        let mut foreign_operation = reservation();
        foreign_operation.operation_key = OperationKey::new("get_account_info").expect("operation");
        let error = adapter
            .prepare_raw_page(&foreign_operation, frame(&page()))
            .expect_err("a foreign operation key is refused");
        assert!(
            error.to_string().contains(C1_OPERATION_KEY),
            "unexpected error: {error}"
        );

        let mut widened_authority = reservation();
        widened_authority.authority = "read_write_execution".to_owned();
        let error = adapter
            .prepare_raw_page(&widened_authority, frame(&page()))
            .expect_err("an authority above the crate ceiling is refused");
        assert!(
            error.to_string().contains(AUTHORITY_CEILING),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn queue_entry_over_the_physical_entry_bound_is_refused_before_any_durability_result() {
        let bound = shipped_bound();
        refuse_oversized_entry(&bound, bound.max_entry_bytes()).expect("an entry at the ceiling");
        let error = refuse_oversized_entry(&bound, bound.max_entry_bytes() + 1)
            .expect_err("an entry over the ceiling is refused");
        assert!(
            error.to_string().contains("physical entry ceiling"),
            "unexpected error: {error}"
        );
        let pending = adapter()
            .prepare_raw_page(&reservation(), frame(&page()))
            .expect("prepared page");
        assert!(
            pending.exact_entry_bytes <= bound.max_entry_bytes(),
            "a returned queue item is inside the entry ceiling"
        );
    }

    #[test]
    fn policy_document_claims_public_source_storage_and_informational_gaps_only() {
        let pending = adapter()
            .prepare_raw_page(&reservation(), frame(&page()))
            .expect("prepared page");
        let policy = entry(&pending).exact_policy_bytes.clone();
        assert_eq!(policy, C1_RAW_POLICY_BYTES);
        let policy = String::from_utf8(policy).expect("policy is UTF-8");
        assert!(policy.contains(r#""public_source""#));
        assert!(policy.contains(r#""informational""#));
        for forbidden in [
            "coverageWindow",
            "cursor",
            "finality",
            "finalized",
            "absence",
            "absent",
        ] {
            assert!(
                !policy.contains(forbidden),
                "C1 policy must assert no {forbidden}"
            );
        }
    }

    #[test]
    fn a_bound_that_is_not_the_shipped_c1_ingress_ceiling_is_refused_at_construction() {
        for ingress in [
            0,
            1,
            C1_MAX_RESPONSE_BODY_BYTES - 1,
            C1_MAX_RESPONSE_BODY_BYTES + 1,
            C1_MAX_RESPONSE_BODY_BYTES * 16,
        ] {
            let bound = c1_physical_bound(ingress).expect("physical bound");
            let error = C1RawObservationAdapter::new(bound)
                .expect_err("only the shipped bound is admitted");
            assert!(
                error.to_string().contains("shipped"),
                "ingress {ingress} produced an unexpected error: {error}"
            );
        }
        C1RawObservationAdapter::new(shipped_bound()).expect("the shipped bound is admitted");
    }
}
