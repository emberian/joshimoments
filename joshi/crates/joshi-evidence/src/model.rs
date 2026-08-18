use joshi_domain::{
    AcquisitionClocks, AcquisitionId, AssertionId, BatchDigest, BlobId, CommandId, CommitSeq,
    CoverageId, CursorId, ObservationId, OpenVariant, RequestFingerprint, SourceEventId, SourceId,
    StableString, UtcTimestamp, ValueDigest, WireU64,
};
use serde::{Deserialize, Serialize};

/// One collector request, poll, stream frame, file read, or fixture acquisition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AcquisitionRecord {
    /// Occurrence identity, independent of payload content and source event identity.
    pub acquisition_id: AcquisitionId,
    /// Versioned source contract responsible for the acquisition.
    pub source_id: SourceId,
    /// Live/poll/backfill/recovery/manual/fixture acquisition family.
    pub acquisition_kind: OpenVariant,
    /// RPC/WebSocket/HTTP/browser/operator/fixture transport family.
    pub transport_kind: OpenVariant,
    /// Optional parent acquisition for reconnect/recovery lineage.
    pub parent_acquisition_id: Option<AcquisitionId>,
    /// Digest of the redacted logical request; credentials are never fingerprint input.
    pub request_fingerprint: RequestFingerprint,
    /// Adapter contract version.
    pub contract_version: StableString,
    /// Wall time when this acquisition began.
    pub started_at: UtcTimestamp,
    /// Local monotonic starting point and its process/boot domain.
    /// Source-local monotonic start when the source contract actually supplied one. Browser
    /// companion captures currently supply no monotonic clock, so absence must remain explicit.
    pub started_monotonic: Option<MonotonicReading>,
    /// Source request, connection, page, or frame locator where one exists.
    pub source_locator: Option<StableString>,
    /// Cursor observed with this acquisition. This is not authority to advance durable state;
    /// only an atomic [`CursorAdvance`] in [`DurableIngestBatch`] has that meaning.
    pub source_cursor: Option<StableString>,
    /// Independent receipt, persistence, and local duration clocks.
    pub clocks: AcquisitionClocks,
}

/// One local monotonic reading, comparable only inside its named clock domain.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct MonotonicReading {
    /// Process/boot-specific clock domain.
    pub clock_id: StableString,
    /// Exact monotonic nanoseconds encoded as a decimal JSON string.
    pub nanoseconds: WireU64,
}

/// One observation-to-source-event relation; an observation may contain many.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationSourceEvent {
    /// Alleged source event identity.
    pub source_event_id: SourceEventId,
    /// Open-world relation such as `contains`, `revision`, or `mentions`.
    pub relation: OpenVariant,
    /// Source-native ordinal within the observation, when defined.
    pub event_ordinal: Option<WireU64>,
}

/// Explicit event-time interval/status/precision for storage and replay.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationEventTime {
    /// `exact`, `bounded`, `source_missing`, or `not_applicable` at the strict store boundary.
    pub status: OpenVariant,
    /// Inclusive source-event lower wall-time bound where supplied.
    pub lower: Option<UtcTimestamp>,
    /// Exclusive source-event upper wall-time bound where supplied.
    pub upper: Option<UtcTimestamp>,
    /// Exact source precision in microseconds where supplied.
    pub precision_us: Option<WireU64>,
}

/// Optional chain-native location retained independently from source wall time.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChainLocation {
    /// Chain slot.
    pub slot: Option<WireU64>,
    /// Transaction ordinal inside the slot/block where supplied.
    pub transaction_index: Option<WireU64>,
    /// Instruction index path for nested invocations.
    pub instruction_path: Vec<WireU64>,
    /// Log/event ordinal where supplied.
    pub log_index: Option<WireU64>,
    /// Processed/confirmed/finalized or an unknown retained discriminator.
    pub commitment: Option<OpenVariant>,
}

/// Local receipt/persistence/availability clocks for one observation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationTiming {
    /// Local wall time of receipt.
    pub received_at: UtcTimestamp,
    /// Local monotonic receipt point and domain.
    pub received_monotonic: MonotonicReading,
    /// Wall time after exact bytes crossed the fixture/durable persistence boundary.
    pub persisted_at: UtcTimestamp,
    /// First local time at which a projection may use this observation.
    pub available_at: UtcTimestamp,
}

/// Metadata for one observation yielded by an acquisition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationMetadata {
    /// Occurrence identity. Equal bytes acquired twice still require two IDs.
    pub observation_id: ObservationId,
    /// Ordinal of this result inside the acquisition.
    pub acquisition_ordinal: WireU64,
    /// Frame/response/snapshot/poll-result/operator-capture/fixture family.
    pub observation_kind: OpenVariant,
    /// Zero or more event links. One raw transaction may contain many events.
    pub source_events: Vec<ObservationSourceEvent>,
    /// Open-world payload/event discriminator.
    pub source_variant: OpenVariant,
    /// Explicit source event-time interval/status/precision.
    pub event_time: ObservationEventTime,
    /// Optional chain-native transaction/instruction/log location.
    pub chain: Option<ChainLocation>,
    /// Source-native cursor text observed with this record, not advancement authority.
    pub source_cursor: Option<StableString>,
    /// Independent receipt, persistence, availability, and monotonic clocks.
    pub timing: ObservationTiming,
    /// Pending/decoded/unsupported-variant/malformed/opaque disposition.
    pub parse_disposition: OpenVariant,
    /// Optional non-secret quality/degradation code.
    pub quality_code: Option<StableString>,
    /// Declared media type; raw bytes remain authoritative.
    pub media_type: StableString,
}

/// Uncommitted observation and its exact source bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationDraft {
    /// The acquisition occurrence that yielded this observation.
    pub acquisition: AcquisitionRecord,
    /// Observation-level provenance.
    pub observation: ObservationMetadata,
    /// Exact retained source bytes.
    #[serde(with = "base64_bytes")]
    pub payload: Vec<u8>,
}

/// Content-addressed exact bytes retained by the fixture catalog.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct BlobRecord {
    /// Content metadata.
    pub reference: BlobRef,
    /// Exact bytes. A durable store may place these in an immutable external CAS.
    pub bytes: Vec<u8>,
}

/// Stable content reference. It is never used as an occurrence/event identity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct BlobRef {
    /// Algorithm-qualified content digest such as `sha256:<hex>`.
    pub blob_id: BlobId,
    /// Exact byte length, serialized as a decimal string.
    pub byte_len: WireU64,
}

/// Append-only observation envelope after content hashing.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationRecord {
    /// Acquisition occurrence identity.
    pub acquisition_id: AcquisitionId,
    /// Observation occurrence identity.
    pub observation_id: ObservationId,
    /// Ordinal inside the acquisition.
    pub acquisition_ordinal: WireU64,
    /// Storage-ready observation family.
    pub observation_kind: OpenVariant,
    /// Zero or more typed source-event relations linked to the same exact bytes.
    pub source_events: Vec<ObservationSourceEvent>,
    /// Immutable exact-content reference.
    pub blob: BlobRef,
    /// Observation-reference media type. It is not an attribute of the content hash: identical
    /// bytes may be observed under different media, retention, privacy, or storage policies.
    pub media_type: StableString,
    /// Open-world payload/event discriminator.
    pub source_variant: OpenVariant,
    /// Source event-time interval/status/precision.
    pub event_time: ObservationEventTime,
    /// Optional chain-native location.
    pub chain: Option<ChainLocation>,
    /// Source cursor observed on this record, not cursor authority.
    pub source_cursor: Option<StableString>,
    /// Independent local clocks.
    pub timing: ObservationTiming,
    /// Parse disposition.
    pub parse_disposition: OpenVariant,
    /// Optional quality code.
    pub quality_code: Option<StableString>,
}

/// Typed natural-key definition for an alleged source or chain event.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SourceEventRecord {
    /// Internal stable identity referenced by observations and assertions.
    pub source_event_id: SourceEventId,
    /// Source contract that owns the natural-key namespace.
    pub source_id: SourceId,
    /// Typed namespace such as `solana.instruction` or `social.revision`.
    pub namespace: StableString,
    /// Lossless canonical natural key under the namespace contract.
    pub natural_key: StableString,
    /// Optional source-native sortable key under this namespace contract.
    pub source_order_key: Option<StableString>,
    /// Open-world event-family discriminator.
    pub event_kind: OpenVariant,
}

/// One observation and its role in supporting an assertion.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssertionEvidence {
    /// Exact observation occurrence.
    pub observation_id: ObservationId,
    /// Open-world evidence role such as `decoded_from` or `contradicts`.
    pub role: OpenVariant,
}

/// One source event and its relation to an assertion.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssertionSourceEvent {
    /// Alleged event identity.
    pub source_event_id: SourceEventId,
    /// Open-world relation such as `claims_about` or `reconciles`.
    pub relation: OpenVariant,
}

/// One semantic operator command used as assertion evidence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssertionCommandEvidence {
    /// Immutable semantic command identity.
    pub command_id: CommandId,
    /// Open-world evidence role.
    pub role: OpenVariant,
}

/// Event-valid interval, separate from the local system-known commit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EventValidInterval {
    /// Open-world status such as `exact`, `bounded`, `unbounded`, or `not_applicable`.
    pub status: OpenVariant,
    /// Inclusive event-valid lower wall-time bound where applicable.
    pub lower: Option<UtcTimestamp>,
    /// Exclusive event-valid upper wall-time bound where applicable.
    pub upper: Option<UtcTimestamp>,
}

/// Uncommitted, versioned assertion derived from retained observations.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssertionDraft {
    /// Assertion occurrence/content identity under the producer's contract.
    pub assertion_id: AssertionId,
    /// Semantic key whose correction/supersession history this assertion belongs to.
    pub semantic_key: StableString,
    /// Assertion family/discriminator, open to later variants.
    pub assertion_kind: OpenVariant,
    /// Named producer and semantic version/build.
    pub producer: StableString,
    /// Producer contract version.
    pub producer_version: StableString,
    /// Candidate/accepted/unsupported/retraction status as an open-world discriminator.
    pub assertion_status: OpenVariant,
    /// Event-valid interval, independent from system-known order.
    pub valid_time: EventValidInterval,
    /// Exact observations and their evidence roles.
    pub evidence: Vec<AssertionEvidence>,
    /// Source events and their semantic relation to this claim.
    pub source_events: Vec<AssertionSourceEvent>,
    /// Semantic commands used as evidence, never inferred from fills.
    pub command_evidence: Vec<AssertionCommandEvidence>,
    /// Earlier assertion explicitly superseded by this claim, if any.
    pub supersedes_assertion_id: Option<AssertionId>,
    /// First local availability time for this claim.
    pub available_at: UtcTimestamp,
    /// Algorithm-qualified digest of the producer's canonical assertion value.
    pub value_digest: ValueDigest,
    /// Extension payload only; canonical economic families belong in typed tables/projections.
    pub extension: serde_json::Value,
}

/// Append-only assertion carrying its local knowledge order.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssertionRecord {
    /// Original draft contents.
    #[serde(flatten)]
    pub assertion: AssertionDraft,
}

/// Typed scope over which collection coverage is claimed.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CoverageScope {
    /// Source contract.
    pub source_id: SourceId,
    /// Typed family such as `market_census` or `hot_lane`.
    pub family: OpenVariant,
    /// Optional mint/account/query/connection subject.
    pub subject: Option<StableString>,
}

/// Boundary of a coverage window or gap without inventing a shared total clock.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "clock", rename_all = "snake_case")]
pub enum Boundary {
    /// Local wall-time boundary.
    Wall { value: UtcTimestamp },
    /// Durable knowledge-order boundary.
    Commit { value: CommitSeq },
    /// Source-native opaque cursor boundary.
    SourceCursor { value: StableString },
    /// Source explicitly did not provide a usable boundary.
    Unknown { reason: OpenVariant },
}

/// An append-only claim about a span of successfully observed source coverage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CoverageWindow {
    /// Unique coverage record identity.
    pub coverage_id: CoverageId,
    /// Scope of the claim.
    pub scope: CoverageScope,
    /// Inclusive lower boundary under its named clock.
    pub lower: Boundary,
    /// Optional upper boundary; `None` means the window was open when observed.
    pub upper: Option<Boundary>,
    /// Open-world collection state.
    pub state: OpenVariant,
    /// Local availability time of this coverage claim.
    pub available_at: UtcTimestamp,
}

/// A visible, scoped interval where evidence may be missing or degraded.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CoverageGap {
    /// Unique gap record identity.
    pub gap_id: CoverageId,
    /// Coverage window within which the defect occurred.
    pub coverage_id: CoverageId,
    /// Scope affected by the gap.
    pub scope: CoverageScope,
    /// Last trustworthy lower boundary.
    pub lower: Boundary,
    /// Upper bound known at detection, when the source already exposes one.
    pub upper: Option<Boundary>,
    /// Open-world cause/disposition.
    pub reason: OpenVariant,
    /// When the system learned of the gap.
    pub detected_at: UtcTimestamp,
}

/// Append-only later knowledge about recovery from a previously detected gap.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CoverageRecovery {
    /// Unique recovery record identity.
    pub recovery_id: CoverageId,
    /// Earlier immutable gap being recovered or declared unrecoverable.
    pub gap_id: CoverageId,
    /// Optional acquisition that established recovery.
    pub acquisition_id: Option<AcquisitionId>,
    /// Open-world state such as `partial`, `complete`, or `unrecoverable`.
    pub status: OpenVariant,
    /// Trustworthy source boundary established by recovery, when available.
    pub recovered_through: Option<Boundary>,
    /// Observation occurrences proving the recovery claim.
    pub evidence: Vec<ObservationId>,
    /// When the system learned this recovery claim.
    pub available_at: UtcTimestamp,
}

/// Evidence-backed source cursor advancement that must commit with its observations.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CursorAdvance {
    /// Unique cursor advancement identity.
    pub cursor_id: CursorId,
    /// Source and logical scope to which the cursor applies.
    pub scope: CoverageScope,
    /// Cursor kind and exact opaque value.
    pub cursor_kind: OpenVariant,
    /// Exact cursor value.
    pub cursor_value: StableString,
    /// Acquisition containing all evidence for this advancement.
    pub acquisition_id: AcquisitionId,
    /// Required primary observation from the same acquisition and commit.
    pub primary_observation_id: ObservationId,
    /// Non-empty exact evidence set, all from the same acquisition and commit.
    pub evidence: Vec<ObservationId>,
    /// Prior cursor in this scope/kind chain, when one exists.
    pub predecessor_cursor_id: Option<CursorId>,
}

/// Lossless atomic input contract for a later durable store implementation.
///
/// The current fixture catalog intentionally does not claim durable batch/cursor semantics. A
/// durable writer must accept this whole value in one transaction and return only after commit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DurableIngestBatch {
    /// Version of the canonical batch contract used for its digest.
    pub contract_version: StableString,
    /// Stable idempotency identity for the complete batch contents.
    pub batch_id: StableString,
    /// Supplied algorithm-qualified digest of canonical digest material excluding this field.
    pub expected_digest: BatchDigest,
    /// Raw observation occurrences; acquisitions may repeat exactly within the batch.
    pub observations: Vec<ObservationDraft>,
    /// Typed source-event natural keys referenced by observations/assertions.
    pub source_events: Vec<SourceEventRecord>,
    /// Versioned parser/resolver claims.
    pub assertions: Vec<AssertionDraft>,
    /// Positive coverage claims.
    pub coverage_windows: Vec<CoverageWindow>,
    /// Gap detections.
    pub coverage_gaps: Vec<CoverageGap>,
    /// Later append-only recovery claims.
    pub coverage_recoveries: Vec<CoverageRecovery>,
    /// Cursor advances that must be validated against this batch's evidence.
    pub cursor_advances: Vec<CursorAdvance>,
}

mod base64_bytes {
    use base64::{Engine as _, engine::general_purpose::STANDARD};
    use serde::{Deserialize, Deserializer, Serializer, de};

    pub fn serialize<S>(bytes: &[u8], serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&STANDARD.encode(bytes))
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Vec<u8>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let encoded = String::deserialize(deserializer)?;
        STANDARD.decode(encoded).map_err(de::Error::custom)
    }
}

/// All append-only inputs accepted by the evidence writer.
#[derive(Clone, Debug, Eq, PartialEq)]
// Keeping the typed observation inline preserves the ergonomic collector contract. Queue commands
// box this enum, so the size does not multiply bounded-channel allocation.
#[allow(clippy::large_enum_variant)]
pub enum EvidenceDraft {
    /// Raw observation plus acquisition provenance and bytes.
    Observation(ObservationDraft),
    /// Parser/resolver claim over retained evidence.
    Assertion(AssertionDraft),
    /// Successful coverage claim.
    CoverageWindow(CoverageWindow),
    /// Explicit missing/degraded coverage claim.
    CoverageGap(CoverageGap),
    /// Append-only later recovery claim.
    CoverageRecovery(CoverageRecovery),
}

impl From<ObservationDraft> for EvidenceDraft {
    fn from(value: ObservationDraft) -> Self {
        Self::Observation(value)
    }
}

/// Identity returned by the idempotent append boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum EvidenceIdentity {
    /// Observation identity; the acquisition is stored independently.
    Observation(ObservationId),
    /// Assertion identity.
    Assertion(AssertionId),
    /// Coverage-window identity.
    CoverageWindow(CoverageId),
    /// Coverage-gap identity.
    CoverageGap(CoverageId),
    /// Coverage-recovery identity.
    CoverageRecovery(CoverageId),
}

/// A value and the local commit at which it became available.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Committed<T> {
    /// Durable local knowledge order.
    pub commit_seq: CommitSeq,
    /// Append-only record.
    pub value: T,
}

#[cfg(test)]
mod tests {
    use serde::{Deserialize, Serialize};

    #[derive(Debug, Eq, PartialEq, Serialize, Deserialize)]
    struct ExactBytes {
        #[serde(with = "super::base64_bytes")]
        value: Vec<u8>,
    }

    #[test]
    fn exact_bytes_use_a_base64_string_not_json_numbers() {
        let value = ExactBytes {
            value: vec![0, 255, 128],
        };
        let encoded = serde_json::to_string(&value);
        assert_eq!(encoded.ok().as_deref(), Some(r#"{"value":"AP+A"}"#));
        let decoded = serde_json::from_str::<ExactBytes>(r#"{"value":"AP+A"}"#);
        assert_eq!(decoded.ok(), Some(value));
    }
}
