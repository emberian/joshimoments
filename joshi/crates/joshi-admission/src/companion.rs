use crate::{
    AdmissionBatch, AdmissionError, AdmissionPolicy, PublicStatus, PublicStoreReceiptV1,
    Sha256Digest, SourceDraftBatch, batch::source_registration, source_drafts, strict_json,
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use joshi_domain::{
    AcquisitionClocks, AcquisitionId, AssertionId, CoverageId, ObservationId, OpenVariant,
    RequestFingerprint, SourceEventId, SourceId, StableString, UtcTimestamp, ValueDigest, WireU64,
};
use joshi_evidence::{
    AcquisitionRecord, AssertionDraft, AssertionEvidence, AssertionSourceEvent, Boundary,
    CoverageGap, CoverageScope, CoverageWindow, EventValidInterval, EvidenceDraft,
    MonotonicReading, ObservationDraft, ObservationEventTime, ObservationMetadata,
    ObservationSourceEvent, ObservationTiming, SourceEventRecord,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use url::Url;

pub const COMPANION_BATCH_CONTRACT: &str = "joshi.pump_companion.capture_batch";
pub const COMPANION_RECEIPT_CONTRACT: &str = "joshi.pump_companion.ingest_receipt";
pub const MAX_COMPANION_BATCH_BYTES: usize = 512 * 1024;
const SOURCE_ID: &str = "pump.companion.browser.v1";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Producer {
    adapter: String,
    adapter_version: String,
    installation_id: String,
    extension_session_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FidelityGap {
    reason: String,
    effect: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExactPayload {
    body_base64: String,
    blob_id: Sha256Digest,
    bytes: String,
    boundary: String,
    protection_class: String,
    retention_class: String,
    transfer_encoding: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct NormalizedRecord {
    ordinal: String,
    kind: String,
    natural_key: String,
    fields: BTreeMap<String, FieldValue>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "encoding", content = "value", rename_all = "kebab-case")]
enum FieldValue {
    Utf8(String),
    JsonNumberLexeme(String),
    Boolean(bool),
    Null(()),
    Utf8List(Vec<String>),
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CompanionAcquisition {
    schema: String,
    acquisition_id: String,
    source_id: String,
    acquisition_kind: String,
    transport_kind: String,
    trust: String,
    contract_version: String,
    route_id: String,
    source_origin: String,
    source_path: String,
    page_path: String,
    page_instance_id: String,
    captured_at: String,
    received_at: String,
    source_clock_contract: String,
    sequence: String,
    request_fingerprint: Sha256Digest,
    request_fingerprint_contract: String,
    request_projection_completeness: String,
    response_blob_id: Sha256Digest,
    response_bytes: String,
    response_boundary: String,
    media_type: String,
    parse_disposition: String,
    source_record_count: String,
    emitted_record_count: String,
    omitted_record_count: String,
    records: Vec<NormalizedRecord>,
    fidelity: String,
    evidence_disposition: String,
    #[serde(default)]
    fidelity_gap: Option<FidelityGap>,
    #[serde(default)]
    exact_payload: Option<ExactPayload>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CompanionGap {
    schema: String,
    gap_id: String,
    source_id: String,
    route_id: String,
    source_origin: String,
    source_path: String,
    page_path: String,
    page_instance_id: String,
    acquisition_id: String,
    request_fingerprint: Sha256Digest,
    response_blob_id: Option<Sha256Digest>,
    reason: String,
    sequence_start: String,
    sequence_end: String,
    last_accepted_sequence: Option<String>,
    first_resumed_sequence: Option<String>,
    captured_at_start: String,
    captured_at_end: String,
    detected_at: String,
    source_clock_contract: String,
    dropped_acquisitions: String,
    dropped_records: Option<String>,
    dropped_bytes: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CompanionBatch {
    contract: String,
    schema_version: u64,
    batch_id: String,
    batch_digest: Sha256Digest,
    producer: Producer,
    acquisitions: Vec<CompanionAcquisition>,
    gaps: Vec<CompanionGap>,
}

#[derive(Clone, Debug)]
pub struct ParsedCompanionBatch {
    batch: CompanionBatch,
    acquisition_envelopes: Vec<Vec<u8>>,
}

impl ParsedCompanionBatch {
    #[must_use]
    pub fn ingress_batch_id(&self) -> &str {
        &self.batch.batch_id
    }
    #[must_use]
    pub fn ingress_digest(&self) -> &Sha256Digest {
        &self.batch.batch_digest
    }
    #[must_use]
    pub fn acquisition_ids(&self) -> Vec<String> {
        sorted_distinct(
            self.batch
                .acquisitions
                .iter()
                .map(|value| value.acquisition_id.clone()),
        )
    }
    #[must_use]
    pub fn gap_ids(&self) -> Vec<String> {
        sorted_distinct(self.batch.gaps.iter().map(|value| value.gap_id.clone()))
    }
    #[must_use]
    pub fn installation_id(&self) -> &str {
        &self.batch.producer.installation_id
    }
}

/// Strictly parse a companion batch and verify its source-owned ingress digest.
///
/// # Errors
///
/// Returns an error for malformed, ambiguous, oversized, unrecognized, or digest-mismatched input.
pub fn parse_companion(bytes: &[u8]) -> Result<ParsedCompanionBatch, AdmissionError> {
    let node = strict_json::parse_node(bytes, MAX_COMPANION_BATCH_BYTES)?;
    let material = node.canonical_object_members(&[
        "contract",
        "schemaVersion",
        "batchId",
        "producer",
        "acquisitions",
        "gaps",
    ])?;
    let acquisition_envelopes = match node.object_member("acquisitions") {
        Some(strict_json::StrictNode::Array(values)) => values
            .iter()
            .map(strict_json::StrictNode::canonical_bytes)
            .collect::<Result<Vec<_>, _>>()?,
        _ => {
            return Err(AdmissionError::Contract(
                "companion acquisitions must be an array".into(),
            ));
        }
    };
    let batch: CompanionBatch = strict_json::decode_node(node)?;
    if batch.contract != COMPANION_BATCH_CONTRACT
        || batch.schema_version != 1
        || batch.acquisitions.len() > 25
        || batch.gaps.len() > 25
    {
        return Err(AdmissionError::Contract(
            "unsupported or oversized companion batch".into(),
        ));
    }
    if Sha256Digest::of_bytes(&material) != batch.batch_digest {
        return Err(AdmissionError::Contract(
            "companion ingress digest mismatch".into(),
        ));
    }
    validate_uuid(&batch.batch_id)?;
    if batch.producer.adapter != "pump-companion" || batch.producer.adapter_version.is_empty() {
        return Err(AdmissionError::Contract(
            "invalid companion producer".into(),
        ));
    }
    validate_uuid(&batch.producer.installation_id)?;
    validate_uuid(&batch.producer.extension_session_id)?;
    for acquisition in &batch.acquisitions {
        validate_acquisition(acquisition)?;
    }
    for gap in &batch.gaps {
        validate_gap(gap)?;
    }
    ensure_unique(
        batch
            .acquisitions
            .iter()
            .map(|value| value.acquisition_id.as_str()),
        "companion acquisition",
    )?;
    ensure_unique(
        batch.gaps.iter().map(|value| value.gap_id.as_str()),
        "companion gap",
    )?;
    Ok(ParsedCompanionBatch {
        batch,
        acquisition_envelopes,
    })
}

#[derive(Clone, Debug)]
pub struct CompanionAdmission {
    pub batch: AdmissionBatch,
    pub parsed: ParsedCompanionBatch,
}

#[allow(clippy::too_many_lines)]
/// Adapt a validated companion message into a lossless durable ingest batch.
///
/// # Errors
///
/// Returns an error when source claims, clocks, identities, or evidence closures are invalid.
pub fn admit_companion(
    parsed: ParsedCompanionBatch,
    committed_at: UtcTimestamp,
    committed_mono_ns: u64,
    writer_clock_id: &str,
) -> Result<CompanionAdmission, AdmissionError> {
    let source_id = SourceId::new(SOURCE_ID)?;
    let writer_clock = StableString::new(writer_clock_id)?;
    let mut drafts = Vec::new();
    let mut source_events = Vec::new();
    for (index, acquisition) in parsed.batch.acquisitions.iter().enumerate() {
        let captured_at = source_millis(&acquisition.captured_at)?;
        let received_at = source_millis(&acquisition.received_at)?;
        if received_at < captured_at {
            return Err(AdmissionError::SourceEnvelope(
                "companion receivedAt precedes capturedAt".into(),
            ));
        }
        let acquisition_record = AcquisitionRecord {
            acquisition_id: AcquisitionId::new(acquisition.acquisition_id.clone())?,
            source_id: source_id.clone(),
            acquisition_kind: OpenVariant::known("live")?,
            transport_kind: OpenVariant::known("browser")?,
            parent_acquisition_id: None,
            request_fingerprint: RequestFingerprint::new(
                acquisition.request_fingerprint.to_string(),
            )?,
            contract_version: StableString::new(acquisition.contract_version.clone())?,
            started_at: captured_at,
            started_monotonic: None,
            source_locator: Some(StableString::new(format!(
                "{}{}",
                acquisition.source_origin, acquisition.source_path
            ))?),
            source_cursor: Some(StableString::new(acquisition.sequence.clone())?),
            clocks: AcquisitionClocks {
                requested_at: None,
                received_at,
                persisted_at: committed_at,
                monotonic_elapsed_ns: None,
                monotonic_domain: None,
            },
        };
        let mut links = Vec::new();
        for record in &acquisition.records {
            let source_event_id = SourceEventId::new(format!(
                "event:companion:{}:{}",
                acquisition.acquisition_id, record.ordinal
            ))?;
            source_events.push(SourceEventRecord {
                source_event_id: source_event_id.clone(),
                source_id: source_id.clone(),
                namespace: StableString::new("pump_companion.normalized_record")?,
                natural_key: StableString::new(record.natural_key.clone())?,
                source_order_key: Some(StableString::new(record.ordinal.clone())?),
                event_kind: OpenVariant::known(record.kind.clone())?,
            });
            links.push(ObservationSourceEvent {
                source_event_id: source_event_id.clone(),
                relation: OpenVariant::known("contains")?,
                event_ordinal: Some(WireU64::new(parse_u64(&record.ordinal)?)),
            });
        }
        links.sort_by(|left, right| {
            (&left.source_event_id, &left.relation.discriminator)
                .cmp(&(&right.source_event_id, &right.relation.discriminator))
        });
        let envelope_id = ObservationId::new(format!(
            "obs:companion:{}:attestation",
            acquisition.acquisition_id
        ))?;
        drafts.push(EvidenceDraft::Observation(ObservationDraft {
            acquisition: acquisition_record.clone(),
            observation: ObservationMetadata {
                observation_id: envelope_id.clone(),
                acquisition_ordinal: WireU64::new(0),
                observation_kind: OpenVariant::known("response")?,
                source_events: links,
                source_variant: OpenVariant::known(acquisition.route_id.clone())?,
                event_time: ObservationEventTime {
                    status: OpenVariant::known("exact")?,
                    lower: Some(captured_at),
                    upper: Some(source_millis_exclusive(&acquisition.captured_at)?),
                    precision_us: Some(WireU64::new(1_000)),
                },
                chain: None,
                source_cursor: Some(StableString::new(acquisition.sequence.clone())?),
                timing: ObservationTiming {
                    received_at: committed_at,
                    received_monotonic: MonotonicReading {
                        clock_id: writer_clock.clone(),
                        nanoseconds: WireU64::new(committed_mono_ns),
                    },
                    persisted_at: committed_at,
                    available_at: committed_at,
                },
                parse_disposition: OpenVariant::known(
                    match acquisition.parse_disposition.as_str() {
                        "parsed" | "no-projectable-records" => "decoded",
                        "invalid-json" => "malformed",
                        _ => {
                            return Err(AdmissionError::SourceEnvelope(
                                "invalid companion parse disposition".into(),
                            ));
                        }
                    },
                )?,
                quality_code: (acquisition.fidelity == "lossy-normalized-attestation")
                    .then(|| StableString::new("exact_source_bytes_withheld"))
                    .transpose()?,
                media_type: StableString::new(
                    "application/vnd.joshi.pump-companion-acquisition+json",
                )?,
            },
            payload: parsed.acquisition_envelopes[index].clone(),
        }));
        if let Some(exact) = &acquisition.exact_payload {
            let bytes = STANDARD.decode(&exact.body_base64).map_err(|_| {
                AdmissionError::SourceEnvelope("invalid companion exactPayload base64".into())
            })?;
            if parse_u64(&exact.bytes)?
                != u64::try_from(bytes.len()).map_err(|_| {
                    AdmissionError::SourceEnvelope("companion body length exceeds u64".into())
                })?
                || Sha256Digest::of_bytes(&bytes) != exact.blob_id
                || exact.blob_id != acquisition.response_blob_id
                || exact.bytes != acquisition.response_bytes
            {
                return Err(AdmissionError::SourceEnvelope(
                    "companion exactPayload closure mismatch".into(),
                ));
            }
            drafts.push(EvidenceDraft::Observation(ObservationDraft {
                acquisition: acquisition_record,
                observation: ObservationMetadata {
                    observation_id: ObservationId::new(format!(
                        "obs:companion:{}:body",
                        acquisition.acquisition_id
                    ))?,
                    acquisition_ordinal: WireU64::new(1),
                    observation_kind: OpenVariant::known("response")?,
                    source_events: Vec::new(),
                    source_variant: OpenVariant::known(acquisition.route_id.clone())?,
                    event_time: ObservationEventTime {
                        status: OpenVariant::known("not_applicable")?,
                        lower: None,
                        upper: None,
                        precision_us: None,
                    },
                    chain: None,
                    source_cursor: Some(StableString::new(acquisition.sequence.clone())?),
                    timing: ObservationTiming {
                        received_at: committed_at,
                        received_monotonic: MonotonicReading {
                            clock_id: writer_clock.clone(),
                            nanoseconds: WireU64::new(committed_mono_ns),
                        },
                        persisted_at: committed_at,
                        available_at: committed_at,
                    },
                    parse_disposition: OpenVariant::known("opaque")?,
                    quality_code: None,
                    media_type: StableString::new(acquisition.media_type.clone())?,
                },
                payload: bytes,
            }));
        }
        for record in &acquisition.records {
            drafts.push(EvidenceDraft::Assertion(assertion(
                acquisition,
                record,
                &envelope_id,
                committed_at,
            )?));
        }
    }
    for gap in &parsed.batch.gaps {
        let scope = companion_scope(
            &source_id,
            &gap.route_id,
            gap.request_fingerprint.as_str(),
            &gap.page_instance_id,
        )?;
        let coverage_id = CoverageId::new(format!("coverage:companion-gap:{}", gap.gap_id))?;
        let lower = match &gap.last_accepted_sequence {
            Some(value) => Boundary::SourceCursor {
                value: StableString::new(value.clone())?,
            },
            None => Boundary::Unknown {
                reason: OpenVariant::known("last_accepted_unknown")?,
            },
        };
        let upper = Some(Boundary::SourceCursor {
            value: StableString::new(
                gap.first_resumed_sequence
                    .clone()
                    .unwrap_or_else(|| gap.sequence_end.clone()),
            )?,
        });
        drafts.push(EvidenceDraft::CoverageWindow(CoverageWindow {
            coverage_id: coverage_id.clone(),
            scope: scope.clone(),
            lower: lower.clone(),
            upper: upper.clone(),
            state: OpenVariant::known("degraded")?,
            available_at: committed_at,
        }));
        drafts.push(EvidenceDraft::CoverageGap(CoverageGap {
            gap_id: CoverageId::new(gap.gap_id.clone())?,
            coverage_id,
            scope,
            lower,
            upper,
            reason: OpenVariant::known(gap.reason.replace('-', "_"))?,
            detected_at: source_millis(&gap.detected_at)?,
        }));
    }
    let registration = source_registration(
        source_id,
        "pump_companion",
        "pump-companion-admission.v1",
        &parsed.batch.producer.adapter_version,
    )?;
    let batch_id = StableString::new(format!("companion:{}", parsed.batch.batch_id))?;
    let batch = source_drafts(SourceDraftBatch {
        batch_id,
        drafts,
        source_events,
        cursor_advances: Vec::new(),
        registrations: vec![registration],
        policy: AdmissionPolicy::authenticated_private()?,
        committed_at,
        writer_clock_id: writer_clock,
        committed_mono_ns,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
    })?;
    Ok(CompanionAdmission { batch, parsed })
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CompanionReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub ingress_batch_id: String,
    pub ingress_batch_digest: Sha256Digest,
    pub status: PublicStatus,
    pub from_commit_seq: String,
    pub through_commit_seq: String,
    pub durable_batch_id: String,
    pub durable_batch_digest: Sha256Digest,
    pub store_admission_digest: Sha256Digest,
    pub acquisition_count: String,
    pub gap_count: String,
    pub committed_acquisition_ids: Vec<String>,
    pub committed_gap_ids: Vec<String>,
}

impl CompanionReceiptV1 {
    /// Close the source ACK over the exact post-commit durable receipt.
    ///
    /// # Errors
    ///
    /// Returns an error if any batch, acquisition, gap, or digest identity differs.
    pub fn from_committed(
        admission: &CompanionAdmission,
        receipt: &PublicStoreReceiptV1,
    ) -> Result<Self, AdmissionError> {
        let acquisition_ids = admission.parsed.acquisition_ids();
        let gap_ids = admission.parsed.gap_ids();
        if receipt.batch_id != admission.batch.store.evidence.batch_id.as_str()
            || receipt.batch_digest.as_str()
                != admission.batch.store.evidence.expected_digest.as_str()
            || receipt.acquisition_ids != acquisition_ids
        {
            return Err(AdmissionError::Receipt(
                "companion durable receipt closure mismatch".into(),
            ));
        }
        let receipt_gap_ids = receipt
            .gap_outcomes
            .iter()
            .map(|gap| gap.gap_id.clone())
            .collect::<Vec<_>>();
        if receipt_gap_ids != gap_ids {
            return Err(AdmissionError::Receipt(
                "companion durable gap closure mismatch".into(),
            ));
        }
        Ok(Self {
            contract: COMPANION_RECEIPT_CONTRACT.into(),
            schema_version: 1,
            catalog_id: receipt.catalog_id.clone(),
            catalog_schema: receipt.catalog_schema.clone(),
            ingress_batch_id: admission.parsed.batch.batch_id.clone(),
            ingress_batch_digest: admission.parsed.batch.batch_digest.clone(),
            status: receipt.status.clone(),
            from_commit_seq: receipt.from_commit_seq.clone(),
            through_commit_seq: receipt.through_commit_seq.clone(),
            durable_batch_id: receipt.batch_id.clone(),
            durable_batch_digest: receipt.batch_digest.clone(),
            store_admission_digest: receipt.store_admission_digest.clone(),
            acquisition_count: acquisition_ids.len().to_string(),
            gap_count: gap_ids.len().to_string(),
            committed_acquisition_ids: acquisition_ids,
            committed_gap_ids: gap_ids,
        })
    }
}

#[derive(Serialize)]
struct AssertionValueMaterial<'a> {
    contract: &'static str,
    assertion_kind: &'a OpenVariant,
    producer: &'a StableString,
    producer_version: &'a StableString,
    extension: &'a Value,
}

fn assertion(
    acquisition: &CompanionAcquisition,
    record: &NormalizedRecord,
    observation_id: &ObservationId,
    available_at: UtcTimestamp,
) -> Result<AssertionDraft, AdmissionError> {
    let event_id = SourceEventId::new(format!(
        "event:companion:{}:{}",
        acquisition.acquisition_id, record.ordinal
    ))?;
    let record_value = serde_json::to_value(record)?;
    let mut extension = serde_json::Map::new();
    extension.insert("record".into(), record_value);
    extension.insert(
        "trust".into(),
        Value::String("page-delivered-untrusted".into()),
    );
    // This interval describes only what the browser capture reported at one sampled instant.
    // It is deliberately a capture-attestation namespace, never effective object validity.
    let assertion_kind = OpenVariant::known("companion_capture_snapshot_attestation")?;
    let producer = StableString::new("pump-companion")?;
    let producer_version = StableString::new("1")?;
    let extension = Value::Object(extension);
    let digest = Sha256Digest::of_bytes(&serde_json::to_vec(&AssertionValueMaterial {
        contract: "joshi.assertion_value.v1",
        assertion_kind: &assertion_kind,
        producer: &producer,
        producer_version: &producer_version,
        extension: &extension,
    })?);
    Ok(AssertionDraft {
        assertion_id: AssertionId::new(format!(
            "assertion:companion:{}:{}",
            acquisition.acquisition_id, record.ordinal
        ))?,
        semantic_key: StableString::new(format!(
            "companion.capture_snapshot:{}",
            Sha256Digest::of_bytes(record.natural_key.as_bytes())
        ))?,
        assertion_kind,
        producer,
        producer_version,
        assertion_status: OpenVariant::known("candidate")?,
        valid_time: EventValidInterval {
            status: OpenVariant::known("exact")?,
            lower: Some(source_millis(&acquisition.captured_at)?),
            upper: Some(source_millis_exclusive(&acquisition.captured_at)?),
        },
        evidence: vec![AssertionEvidence {
            observation_id: observation_id.clone(),
            role: OpenVariant::known("decoded_from")?,
        }],
        source_events: vec![AssertionSourceEvent {
            source_event_id: event_id,
            relation: OpenVariant::known("claims_about")?,
        }],
        command_evidence: Vec::new(),
        supersedes_assertion_id: None,
        available_at,
        value_digest: ValueDigest::new(digest.to_string())?,
        extension,
    })
}

fn validate_acquisition(value: &CompanionAcquisition) -> Result<(), AdmissionError> {
    validate_uuid(&value.acquisition_id)?;
    validate_uuid(&value.page_instance_id)?;
    if value.schema != "joshi.pump-companion.acquisition.v1"
        || value.source_id != "pump-companion"
        || value.acquisition_kind != "http-response"
        || value.transport_kind != "browser-fetch"
        || value.trust != "page-delivered-untrusted"
        || value.contract_version != "pump-companion-admission.v1"
    {
        return Err(AdmissionError::Contract(
            "invalid companion acquisition contract".into(),
        ));
    }
    validate_route(&value.route_id)?;
    validate_origin(&value.source_origin)?;
    validate_path(&value.source_path)?;
    validate_path(&value.page_path)?;
    source_millis(&value.captured_at)?;
    source_millis(&value.received_at)?;
    parse_u64(&value.sequence)?;
    parse_u64(&value.response_bytes)?;
    for count in [
        &value.source_record_count,
        &value.emitted_record_count,
        &value.omitted_record_count,
    ] {
        parse_u64(count)?;
    }
    if value.records.len() > 100
        || parse_u64(&value.emitted_record_count)? != value.records.len() as u64
    {
        return Err(AdmissionError::SourceEnvelope(
            "companion emitted record count mismatch".into(),
        ));
    }
    let mut ordinals = BTreeSet::new();
    for record in &value.records {
        if record.kind.is_empty()
            || record.kind.len() > 80
            || record.natural_key.is_empty()
            || record.natural_key.len() > 512
            || !ordinals.insert(parse_u64(&record.ordinal)?)
        {
            return Err(AdmissionError::SourceEnvelope(
                "invalid companion normalized record".into(),
            ));
        }
        validate_fields(&record.fields)?;
    }
    match value.fidelity.as_str() {
        "exact-private-response-bytes"
            if value.exact_payload.is_some()
                && value.fidelity_gap.is_none()
                && value.evidence_disposition == "candidate-exact-private-observation" => {}
        "lossy-normalized-attestation"
            if value.exact_payload.is_none()
                && value.fidelity_gap.is_some()
                && value.evidence_disposition == "not-admissible-as-exact-observation" => {}
        _ => {
            return Err(AdmissionError::SourceEnvelope(
                "invalid companion fidelity sum".into(),
            ));
        }
    }
    Ok(())
}

fn validate_gap(value: &CompanionGap) -> Result<(), AdmissionError> {
    validate_uuid(&value.gap_id)?;
    validate_uuid(&value.acquisition_id)?;
    validate_uuid(&value.page_instance_id)?;
    if value.schema != "joshi.pump-companion.coverage-gap.v1" || value.source_id != "pump-companion"
    {
        return Err(AdmissionError::Contract(
            "invalid companion gap contract".into(),
        ));
    }
    validate_route(&value.route_id)?;
    validate_origin(&value.source_origin)?;
    validate_path(&value.source_path)?;
    validate_path(&value.page_path)?;
    let start = parse_u64(&value.sequence_start)?;
    let end = parse_u64(&value.sequence_end)?;
    if start > end {
        return Err(AdmissionError::SourceEnvelope(
            "companion gap sequence interval is inverted".into(),
        ));
    }
    for number in [
        &value.last_accepted_sequence,
        &value.first_resumed_sequence,
        &value.dropped_records,
        &value.dropped_bytes,
    ]
    .into_iter()
    .flatten()
    {
        parse_u64(number)?;
    }
    parse_u64(&value.dropped_acquisitions)?;
    source_millis(&value.captured_at_start)?;
    source_millis(&value.captured_at_end)?;
    source_millis(&value.detected_at)?;
    Ok(())
}

fn validate_fields(fields: &BTreeMap<String, FieldValue>) -> Result<(), AdmissionError> {
    for (key, value) in fields {
        if key.len() > 80 {
            return Err(AdmissionError::SourceEnvelope(
                "companion field key is too long".into(),
            ));
        }
        match value {
            FieldValue::JsonNumberLexeme(value) if !valid_json_number_lexeme(value) => {
                return Err(AdmissionError::SourceEnvelope(
                    "invalid retained JSON number lexeme".into(),
                ));
            }
            FieldValue::Utf8List(values) if values.len() > 100 => {
                return Err(AdmissionError::SourceEnvelope(
                    "companion string list is too long".into(),
                ));
            }
            _ => {}
        }
    }
    Ok(())
}

fn valid_json_number_lexeme(value: &str) -> bool {
    value.len() <= 1024
        && serde_json::from_str::<serde_json::Number>(value).is_ok()
        && !value.starts_with('+')
        && !(value.starts_with('0') && value.len() > 1 && value.as_bytes()[1].is_ascii_digit())
        && !(value.starts_with("-0") && value.len() > 2 && value.as_bytes()[2].is_ascii_digit())
}
fn validate_route(value: &str) -> Result<(), AdmissionError> {
    if matches!(
        value,
        "coin-v2"
            | "callout-recent"
            | "callout-mint"
            | "following"
            | "community"
            | "community-messages"
            | "community-callouts"
            | "community-feed"
            | "profile-community"
    ) {
        Ok(())
    } else {
        Err(AdmissionError::Contract("unknown companion route".into()))
    }
}
fn validate_origin(value: &str) -> Result<(), AdmissionError> {
    let parsed = Url::parse(value)
        .map_err(|_| AdmissionError::SourceEnvelope("invalid companion origin".into()))?;
    if parsed.scheme() == "https"
        && parsed.path() == "/"
        && parsed.query().is_none()
        && parsed.fragment().is_none()
        && matches!(
            parsed.host_str(),
            Some("frontend-api-v3.pump.fun" | "api.coin-communities.xyz" | "profile-api.pump.fun")
        )
    {
        Ok(())
    } else {
        Err(AdmissionError::SourceEnvelope(
            "companion origin is outside the allowlist".into(),
        ))
    }
}
fn validate_path(value: &str) -> Result<(), AdmissionError> {
    if value.starts_with('/') && value.len() <= 2000 && !value.contains('?') && !value.contains('#')
    {
        Ok(())
    } else {
        Err(AdmissionError::SourceEnvelope(
            "unsafe companion path".into(),
        ))
    }
}
fn source_millis(value: &str) -> Result<UtcTimestamp, AdmissionError> {
    if value.len() != 24 || !value.ends_with('Z') || value.as_bytes().get(19) != Some(&b'.') {
        return Err(AdmissionError::SourceEnvelope(
            "source time must have exactly three fractional UTC digits".into(),
        ));
    }
    let durable = format!("{}000Z", &value[..value.len() - 1]);
    durable
        .parse()
        .map_err(|_| AdmissionError::SourceEnvelope("invalid source UTC timestamp".into()))
}
fn source_millis_exclusive(value: &str) -> Result<UtcTimestamp, AdmissionError> {
    let lower = source_millis(value)?;
    let upper = lower
        .as_datetime()
        .checked_add(time::Duration::milliseconds(1))
        .ok_or_else(|| {
            AdmissionError::SourceEnvelope("source timestamp interval overflows".into())
        })?;
    UtcTimestamp::new(upper)
        .map_err(|_| AdmissionError::SourceEnvelope("invalid source timestamp interval".into()))
}
fn parse_u64(value: &str) -> Result<u64, AdmissionError> {
    Ok(value.parse::<WireU64>()?.get())
}
fn validate_uuid(value: &str) -> Result<(), AdmissionError> {
    let valid = value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                byte == b'-'
            } else {
                byte.is_ascii_digit()
                    || (b'a'..=b'f').contains(&byte)
                    || (b'A'..=b'F').contains(&byte)
            }
        });
    if valid {
        Ok(())
    } else {
        Err(AdmissionError::SourceEnvelope(
            "identity must be a UUID".into(),
        ))
    }
}
fn ensure_unique<'a>(
    values: impl Iterator<Item = &'a str>,
    kind: &str,
) -> Result<(), AdmissionError> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !seen.insert(value) {
            return Err(AdmissionError::SourceEnvelope(format!(
                "duplicate {kind} ID"
            )));
        }
    }
    Ok(())
}
fn sorted_distinct(values: impl Iterator<Item = String>) -> Vec<String> {
    values.collect::<BTreeSet<_>>().into_iter().collect()
}
fn companion_scope(
    source_id: &SourceId,
    route: &str,
    fingerprint: &str,
    page: &str,
) -> Result<CoverageScope, AdmissionError> {
    Ok(CoverageScope {
        source_id: source_id.clone(),
        family: OpenVariant::known("hot_lane")?,
        subject: Some(StableString::new(format!(
            "companion:{route}|{fingerprint}|{page}"
        ))?),
    })
}
