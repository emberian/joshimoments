use joshi_domain::{
    AcquisitionClocks, AcquisitionId, ObservationId, OpenVariant, RequestFingerprint,
    SourceEventId, StableString, UtcTimestamp, WireStringError, WireU64,
};
use joshi_evidence::{
    ChainLocation, EvidenceDraft, MonotonicReading, ObservationDraft, ObservationEventTime,
    ObservationMetadata, ObservationSourceEvent, ObservationTiming,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;
use time::OffsetDateTime;

use crate::frame::{
    ContentType, FrameDirection, RawSourceFrame, SafeHeader, SourceId, StreamClass, Transport,
    UnixMillis,
};

pub const RETAINED_FRAME_ENVELOPE_VERSION: &str = "joshi.raw_source_frame.v1";

/// Storage payload retaining transport semantics and the provider body as exact bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RetainedFrameEnvelope {
    pub envelope_version: String,
    pub adapter_contract_version: String,
    pub transport: Transport,
    pub stream_class: StreamClass,
    pub direction: FrameDirection,
    pub original_content_type: ContentType,
    pub http_status: Option<u16>,
    pub safe_headers: Vec<SafeHeader>,
    pub body: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LogicalSourceLocator {
    HeliusHttp { method: &'static str },
    HeliusWebSocket { subscription: &'static str },
    PumpPortalWebSocket { feed: &'static str },
    SolanaPublicHttp { method: &'static str },
    SolanaPublicWebSocket { subscription: &'static str },
    Fixture { name: String },
}

impl LogicalSourceLocator {
    fn stable(&self) -> Result<StableString, WireStringError> {
        let value = match self {
            Self::HeliusHttp { method } => format!("helius:http:{method}"),
            Self::HeliusWebSocket { subscription } => format!("helius:websocket:{subscription}"),
            Self::PumpPortalWebSocket { feed } => format!("pumpportal:websocket:{feed}"),
            Self::SolanaPublicHttp { method } => format!("solana_public:http:{method}"),
            Self::SolanaPublicWebSocket { subscription } => {
                format!("solana_public:websocket:{subscription}")
            }
            Self::Fixture { name } => format!("fixture:{name}"),
        };
        StableString::new(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderEventTime {
    Exact {
        value: UtcTimestamp,
        precision_us: u64,
    },
    Bounded {
        lower: UtcTimestamp,
        upper: UtcTimestamp,
        precision_us: u64,
    },
    Missing {
        reason: String,
    },
    NotApplicable,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceEventLink {
    pub source_event_id: String,
    pub relation: OpenVariant,
    pub event_ordinal: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceContext {
    /// Stable installation/run or connection identity. Epoch/sequence alone can repeat on restart.
    pub occurrence_namespace: String,
    /// Non-secret logical request material used only to compute an irreversible SHA-256 digest.
    pub redacted_request_fingerprint_material: String,
    pub parent_acquisition_id: Option<String>,
    pub locator: LogicalSourceLocator,
    pub source_variant: OpenVariant,
    pub source_cursor: Option<String>,
    /// Zero, one, or many events alleged by this exact provider frame.
    pub source_events: Vec<SourceEventLink>,
    pub provider_event_time: ProviderEventTime,
    pub chain_slot: Option<u64>,
    pub transaction_index: Option<u64>,
    pub instruction_path: Vec<u64>,
    pub log_index: Option<u64>,
    pub finality: Option<OpenVariant>,
    /// Justified start of this per-request/per-frame acquisition.
    pub acquisition_started_at: UtcTimestamp,
    /// Wall time immediately before an HTTP request, when applicable.
    pub requested_at: Option<UtcTimestamp>,
    pub monotonic_clock_id: String,
    pub acquisition_started_monotonic_ns: u64,
    pub received_monotonic_ns: u64,
    pub persisted_at: UtcTimestamp,
}

#[derive(Error, Debug)]
pub enum EvidenceAdapterError {
    #[error("source timestamp is outside the supported range")]
    TimestampOutOfRange,
    #[error("invalid evidence wire value: {0}")]
    Wire(#[from] WireStringError),
    #[error("redacted request fingerprint material contains a secret-looking field")]
    UnsafeFingerprintMaterial,
    #[error("event-time interval is invalid or outside the supported range")]
    InvalidEventTime,
    #[error("unable to encode the versioned retained-frame envelope")]
    Envelope(#[from] serde_json::Error),
}

/// Convert an exact source frame into the shared evidence envelope without authenticated URLs or
/// headers. Equal bytes acquired twice retain distinct occurrence IDs through a stable run or
/// connection namespace plus epoch/sequence.
///
/// # Errors
///
/// Returns an error when a timestamp is outside the supported range or any source-provided value
/// cannot satisfy the shared wire contract.
// Keep the full field mapping visible together: omission is riskier here than local line count.
#[allow(clippy::too_many_lines)]
pub fn observation_draft(
    frame: RawSourceFrame,
    context: EvidenceContext,
) -> Result<EvidenceDraft, EvidenceAdapterError> {
    let payload = retained_frame_payload(&frame)?;
    let source_id = domain_source_id(&frame.source)?;
    let received_at = timestamp(frame.received_at)?;
    let occurrence_namespace = StableString::new(context.occurrence_namespace)?;
    let source_slug = source_id.as_str().replace(':', "-");
    let occurrence = format!(
        "{source_slug}:{}:{}:{}",
        occurrence_namespace.as_str(),
        frame.connection_epoch,
        frame.sequence
    );
    let acquisition_id = AcquisitionId::new(format!("acq:{occurrence}"))?;
    let observation_id = ObservationId::new(format!("obs:{occurrence}"))?;
    let source_events = context
        .source_events
        .into_iter()
        .map(|event| -> Result<ObservationSourceEvent, WireStringError> {
            Ok(ObservationSourceEvent {
                source_event_id: SourceEventId::new(event.source_event_id)?,
                relation: event.relation,
                event_ordinal: event.event_ordinal.map(WireU64::new),
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    let source_cursor = context.source_cursor.map(StableString::new).transpose()?;
    let (event_time, quality_code) = match context.provider_event_time {
        ProviderEventTime::Exact {
            value,
            precision_us,
        } => {
            let precision = i64::try_from(precision_us)
                .ok()
                .filter(|value| *value > 0)
                .ok_or(EvidenceAdapterError::InvalidEventTime)?;
            let upper = value
                .as_datetime()
                .checked_add(time::Duration::microseconds(precision))
                .ok_or(EvidenceAdapterError::InvalidEventTime)?;
            let upper =
                UtcTimestamp::new(upper).map_err(|_| EvidenceAdapterError::InvalidEventTime)?;
            (
                ObservationEventTime {
                    status: OpenVariant::known("exact")?,
                    lower: Some(value),
                    upper: Some(upper),
                    precision_us: Some(WireU64::new(precision_us)),
                },
                None,
            )
        }
        ProviderEventTime::Bounded {
            lower,
            upper,
            precision_us,
        } => {
            if lower >= upper || precision_us == 0 {
                return Err(EvidenceAdapterError::InvalidEventTime);
            }
            (
                ObservationEventTime {
                    status: OpenVariant::known("bounded")?,
                    lower: Some(lower),
                    upper: Some(upper),
                    precision_us: Some(WireU64::new(precision_us)),
                },
                None,
            )
        }
        ProviderEventTime::Missing { reason } => (
            ObservationEventTime {
                status: OpenVariant::known("source_missing")?,
                lower: None,
                upper: None,
                precision_us: None,
            },
            Some(StableString::new(format!("event_time_missing:{reason}"))?),
        ),
        ProviderEventTime::NotApplicable => (
            ObservationEventTime {
                status: OpenVariant::known("not_applicable")?,
                lower: None,
                upper: None,
                precision_us: None,
            },
            None,
        ),
    };
    let finality = context.finality;
    let chain = if context.chain_slot.is_some()
        || context.transaction_index.is_some()
        || !context.instruction_path.is_empty()
        || context.log_index.is_some()
        || finality.is_some()
    {
        Some(ChainLocation {
            slot: context.chain_slot.map(WireU64::new),
            transaction_index: context.transaction_index.map(WireU64::new),
            instruction_path: context
                .instruction_path
                .into_iter()
                .map(WireU64::new)
                .collect(),
            log_index: context.log_index.map(WireU64::new),
            commitment: finality,
        })
    } else {
        None
    };
    let monotonic_clock_id = StableString::new(context.monotonic_clock_id)?;
    let started_monotonic = MonotonicReading {
        clock_id: monotonic_clock_id.clone(),
        nanoseconds: WireU64::new(context.acquisition_started_monotonic_ns),
    };
    let received_monotonic = MonotonicReading {
        clock_id: monotonic_clock_id.clone(),
        nanoseconds: WireU64::new(context.received_monotonic_ns),
    };
    let monotonic_elapsed_ns = context
        .received_monotonic_ns
        .checked_sub(context.acquisition_started_monotonic_ns)
        .map(WireU64::new);
    let locator = context.locator.stable()?;
    let request_fingerprint = request_fingerprint(
        &context.redacted_request_fingerprint_material,
        &locator,
        &source_id,
    )?;
    let (acquisition_kind, transport_kind, observation_kind) = match frame.transport {
        Transport::Http => ("rpc_request", "http", "response"),
        Transport::WebSocket => ("stream_frame", "websocket", "frame"),
        Transport::Fixture => ("fixture", "fixture", "fixture"),
    };
    let parent_acquisition_id = context
        .parent_acquisition_id
        .map(AcquisitionId::new)
        .transpose()?;
    Ok(EvidenceDraft::Observation(ObservationDraft {
        acquisition: joshi_evidence::AcquisitionRecord {
            acquisition_id,
            source_id,
            acquisition_kind: OpenVariant::known(acquisition_kind)?,
            transport_kind: OpenVariant::known(transport_kind)?,
            parent_acquisition_id,
            request_fingerprint,
            contract_version: StableString::new(frame.contract_version)?,
            started_at: context.acquisition_started_at,
            started_monotonic: Some(started_monotonic),
            source_locator: Some(locator),
            source_cursor: source_cursor.clone(),
            clocks: AcquisitionClocks {
                requested_at: context.requested_at,
                received_at,
                persisted_at: context.persisted_at,
                monotonic_elapsed_ns,
                monotonic_domain: Some(monotonic_clock_id),
            },
        },
        observation: ObservationMetadata {
            observation_id,
            acquisition_ordinal: WireU64::new(0),
            observation_kind: OpenVariant::known(observation_kind)?,
            source_events,
            source_variant: context.source_variant,
            event_time,
            chain,
            source_cursor,
            timing: ObservationTiming {
                received_at,
                received_monotonic,
                persisted_at: context.persisted_at,
                available_at: context.persisted_at,
            },
            parse_disposition: OpenVariant::known("opaque")?,
            quality_code,
            media_type: StableString::new("application/vnd.joshi.raw-source-frame+json")?,
        },
        payload,
    }))
}

fn retained_frame_payload(frame: &RawSourceFrame) -> Result<Vec<u8>, serde_json::Error> {
    serde_json::to_vec(&RetainedFrameEnvelope {
        envelope_version: RETAINED_FRAME_ENVELOPE_VERSION.to_owned(),
        adapter_contract_version: frame.contract_version.clone(),
        transport: frame.transport,
        stream_class: frame.stream_class,
        direction: frame.direction,
        original_content_type: frame.content_type,
        http_status: frame.http_status,
        safe_headers: frame.safe_headers.clone(),
        body: frame.body.to_vec(),
    })
}

fn request_fingerprint(
    material: &str,
    locator: &StableString,
    source_id: &joshi_domain::SourceId,
) -> Result<RequestFingerprint, EvidenceAdapterError> {
    let lower = material.to_ascii_lowercase();
    if [
        "api-key=",
        "api_key=",
        "authorization:",
        "token=",
        "secret=",
    ]
    .iter()
    .any(|needle| lower.contains(needle))
    {
        return Err(EvidenceAdapterError::UnsafeFingerprintMaterial);
    }
    let material = StableString::new(material)?;
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.source.request.v1\0");
    hasher.update(source_id.as_str().as_bytes());
    hasher.update(b"\0");
    hasher.update(locator.as_str().as_bytes());
    hasher.update(b"\0");
    hasher.update(material.as_str().as_bytes());
    RequestFingerprint::new(format!("sha256:{:x}", hasher.finalize())).map_err(Into::into)
}

/// Map an adapter source identity to the stable shared-domain identity.
///
/// # Errors
///
/// Returns an error if an open-world source identifier violates the shared wire contract.
pub fn domain_source_id(source: &SourceId) -> Result<joshi_domain::SourceId, WireStringError> {
    let value = match source {
        SourceId::HeliusHttp => "helius.http.solana.v1".to_owned(),
        SourceId::HeliusWebSocket => "helius.websocket.solana.v1".to_owned(),
        SourceId::PumpPortalWebSocket => "pumpportal.websocket.data.v1".to_owned(),
        SourceId::SolanaPublicHttp => "solana.public_http.v1".to_owned(),
        SourceId::SolanaPublicWebSocket => "solana.public_websocket.v1".to_owned(),
        SourceId::Other(value) => format!("source.other.{value}"),
    };
    joshi_domain::SourceId::new(value)
}

fn timestamp(value: UnixMillis) -> Result<UtcTimestamp, EvidenceAdapterError> {
    let nanos = i128::from(value.0).saturating_mul(1_000_000);
    let timestamp = OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|_| EvidenceAdapterError::TimestampOutOfRange)?;
    UtcTimestamp::new(timestamp).map_err(|_| EvidenceAdapterError::TimestampOutOfRange)
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;
    use joshi_evidence::{EvidenceDraft, InMemoryCatalog};

    use crate::frame::{FrameDirection, StreamClass, Transport};

    use super::*;

    fn timestamp_value() -> UtcTimestamp {
        "2026-08-16T12:00:00.000000Z".parse().unwrap()
    }

    fn frame(sequence: u64) -> RawSourceFrame {
        RawSourceFrame {
            contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
            source: SourceId::PumpPortalWebSocket,
            transport: Transport::Fixture,
            stream_class: StreamClass::BroadCensus,
            direction: FrameDirection::Inbound,
            content_type: ContentType::Json,
            received_at: UnixMillis(1_786_881_600_000),
            connection_epoch: 1,
            sequence,
            http_status: None,
            safe_headers: Vec::new(),
            body: Bytes::from_static(br#"{"solAmount":2,"marketCapSol":28.069557848389476}"#),
        }
    }

    fn context() -> EvidenceContext {
        EvidenceContext {
            occurrence_namespace: "fixture-run-001".to_owned(),
            redacted_request_fingerprint_material: "subscribeNewToken".to_owned(),
            parent_acquisition_id: None,
            locator: LogicalSourceLocator::PumpPortalWebSocket { feed: "new_token" },
            source_variant: OpenVariant::known("new_token").unwrap(),
            source_cursor: None,
            source_events: Vec::new(),
            provider_event_time: ProviderEventTime::Missing {
                reason: "not_provided".to_owned(),
            },
            chain_slot: None,
            transaction_index: None,
            instruction_path: Vec::new(),
            log_index: None,
            finality: Some(OpenVariant::known("processed").unwrap()),
            acquisition_started_at: timestamp_value(),
            requested_at: None,
            monotonic_clock_id: "fixture-process-001".to_owned(),
            acquisition_started_monotonic_ns: 10,
            received_monotonic_ns: 20,
            persisted_at: timestamp_value(),
        }
    }

    #[test]
    fn exact_bytes_survive_the_shared_evidence_boundary() {
        let expected = frame(1).body.to_vec();
        let draft = observation_draft(frame(1), context()).unwrap();
        let EvidenceDraft::Observation(draft) = draft else {
            panic!("expected observation")
        };
        let retained: RetainedFrameEnvelope = serde_json::from_slice(&draft.payload).unwrap();
        assert_eq!(retained.body, expected);
        assert_eq!(retained.direction, FrameDirection::Inbound);
        assert_eq!(retained.stream_class, StreamClass::BroadCensus);
        assert_eq!(
            draft.acquisition.source_locator.unwrap().as_str(),
            "pumpportal:websocket:new_token"
        );
    }

    #[test]
    fn elapsed_monotonic_time_subtracts_the_nonzero_start_exactly_once() {
        let draft = observation_draft(frame(1), context()).unwrap();
        let EvidenceDraft::Observation(draft) = draft else {
            panic!("expected observation")
        };
        assert_eq!(
            draft.acquisition.clocks.monotonic_elapsed_ns,
            Some(WireU64::new(10))
        );
        assert_eq!(
            draft.observation.timing.received_monotonic.nanoseconds,
            WireU64::new(20)
        );
    }

    #[test]
    fn equal_bytes_from_two_occurrences_do_not_collapse() {
        let mut catalog = InMemoryCatalog::default();
        catalog
            .append(observation_draft(frame(1), context()).unwrap())
            .unwrap();
        catalog
            .append(observation_draft(frame(2), context()).unwrap())
            .unwrap();
        let snapshot = catalog.snapshot();
        assert_eq!(snapshot.observations.len(), 2);
        assert_eq!(snapshot.blobs.len(), 1);
    }

    #[test]
    fn one_frame_can_name_multiple_source_events() {
        let mut context = context();
        context.source_events = vec![
            SourceEventLink {
                source_event_id: "event:one".to_owned(),
                relation: OpenVariant::known("contains").unwrap(),
                event_ordinal: Some(0),
            },
            SourceEventLink {
                source_event_id: "event:two".to_owned(),
                relation: OpenVariant::known("contains").unwrap(),
                event_ordinal: Some(1),
            },
        ];
        let draft = observation_draft(frame(1), context).unwrap();
        let EvidenceDraft::Observation(draft) = draft else {
            panic!("expected observation")
        };
        let ids: Vec<_> = draft
            .observation
            .source_events
            .iter()
            .map(|event| event.source_event_id.as_str())
            .collect();
        assert_eq!(ids, ["event:one", "event:two"]);
    }

    #[test]
    fn occurrence_namespace_prevents_restart_identity_collisions() {
        let first = observation_draft(frame(1), context()).unwrap();
        let mut restarted = context();
        restarted.occurrence_namespace = "fixture-run-002".to_owned();
        let second = observation_draft(frame(1), restarted).unwrap();
        let (EvidenceDraft::Observation(first), EvidenceDraft::Observation(second)) =
            (first, second)
        else {
            panic!("expected observations")
        };
        assert_ne!(
            first.observation.observation_id,
            second.observation.observation_id
        );
    }

    #[test]
    fn fingerprint_material_rejects_secret_looking_fields() {
        let mut context = context();
        context.redacted_request_fingerprint_material = "api-key=do-not-store".to_owned();
        assert!(matches!(
            observation_draft(frame(1), context),
            Err(EvidenceAdapterError::UnsafeFingerprintMaterial)
        ));
    }

    #[test]
    fn exact_event_time_is_stored_as_a_checked_half_open_interval() {
        let mut context = context();
        let lower: UtcTimestamp = "2026-08-16T12:00:00.123456Z".parse().unwrap();
        context.provider_event_time = ProviderEventTime::Exact {
            value: lower,
            precision_us: 1,
        };
        let draft = observation_draft(frame(1), context).unwrap();
        let EvidenceDraft::Observation(draft) = draft else {
            panic!("expected observation")
        };
        assert_eq!(draft.observation.event_time.lower, Some(lower));
        assert_eq!(
            draft.observation.event_time.upper.unwrap().to_string(),
            "2026-08-16T12:00:00.123457Z"
        );
    }
}
