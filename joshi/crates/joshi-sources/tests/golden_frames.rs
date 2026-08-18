use bytes::Bytes;
use joshi_domain::{OpenVariant, UtcTimestamp};
use joshi_evidence::EvidenceDraft;
use joshi_sources::{
    ContentType, EvidenceContext, FrameDirection, HeliusFrameKind, HeliusWsProtocol,
    LogicalSourceLocator, ProviderEventTime, PumpPortalFrameKind, RawSourceFrame,
    RetainedFrameEnvelope, SourceEventLink, SourceId, StreamClass, Transport, UnixMillis,
    classify_pumpportal_frame, observation_draft,
};

const PUMP_NEW: &[u8] =
    include_bytes!("../../../fixtures/sources/pumpportal_new_token_observed_2026-08-14.json");
const PUMP_MIGRATION: &[u8] =
    include_bytes!("../../../fixtures/sources/pumpportal_migration_observed_2026-08-14.json");
const PUMP_REJECTION: &[u8] = include_bytes!(
    "../../../fixtures/sources/pumpportal_funded_key_rejection_observed_2026-08-14.json"
);
const HELIUS_ACK: &[u8] =
    include_bytes!("../../../fixtures/sources/helius_subscription_ack_official_shape.json");
const HELIUS_LOGS: &[u8] =
    include_bytes!("../../../fixtures/sources/helius_logs_notification_official_shape.json");
const HELIUS_LIVE_CHARACTERIZATION: &[u8] = include_bytes!(
    "../../../fixtures/sources/helius_live_characterization_2026-08-16.sanitized.json"
);

fn persisted_at() -> UtcTimestamp {
    "2026-08-16T12:00:00.000000Z".parse().unwrap()
}

fn frame(source: SourceId, class: StreamClass, body: &'static [u8]) -> RawSourceFrame {
    RawSourceFrame {
        contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
        source,
        transport: Transport::Fixture,
        stream_class: class,
        direction: FrameDirection::Inbound,
        content_type: ContentType::Json,
        received_at: UnixMillis(1_786_881_600_000),
        connection_epoch: 1,
        sequence: 1,
        http_status: None,
        safe_headers: Vec::new(),
        body: Bytes::from_static(body),
    }
}

#[test]
fn pumpportal_golden_frames_retain_open_world_shapes() {
    assert_eq!(
        classify_pumpportal_frame(PUMP_NEW).kind,
        PumpPortalFrameKind::NewToken
    );
    assert_eq!(
        classify_pumpportal_frame(PUMP_MIGRATION).kind,
        PumpPortalFrameKind::Migration
    );
    assert_eq!(
        classify_pumpportal_frame(PUMP_REJECTION).kind,
        PumpPortalFrameKind::AuthenticationOrFundingRejected
    );
}

#[test]
fn helius_ack_then_notification_carries_the_chain_slot_cursor() {
    let mut protocol = HeliusWsProtocol::default();
    protocol.register_request(7, StreamClass::BroadCensus);
    assert_eq!(
        protocol.classify(HELIUS_ACK).1.kind,
        HeliusFrameKind::SubscriptionAcknowledged
    );
    let (class, metadata) = protocol.classify(HELIUS_LOGS);
    assert_eq!(class, StreamClass::BroadCensus);
    assert_eq!(
        metadata.cursor,
        Some(joshi_sources::Cursor::SolanaSlot(355_001_234))
    );
}

#[test]
fn exact_fixture_bytes_reach_the_shared_evidence_contract() {
    let draft = observation_draft(
        frame(SourceId::PumpPortalWebSocket, StreamClass::BroadCensus, PUMP_NEW),
        EvidenceContext {
            occurrence_namespace: "golden-fixture-run-001".to_owned(),
            redacted_request_fingerprint_material: "subscribeNewToken".to_owned(),
            parent_acquisition_id: None,
            locator: LogicalSourceLocator::PumpPortalWebSocket { feed: "new_token" },
            source_variant: OpenVariant::known("new_token").unwrap(),
            source_cursor: None,
            source_events: vec![SourceEventLink {
                source_event_id:
                    "solana_signature:3ShNEcfKhWrvFVTwHCK7FjgWXABAZgo9Cpr2S6AGngg9xDifcQyY2mGQQ85p11vxSRvQ3B3SbaajobL1rfSJmyjG"
                        .to_owned(),
                relation: OpenVariant::known("contains").unwrap(),
                event_ordinal: Some(0),
            }],
            provider_event_time: ProviderEventTime::Missing {
                reason: "not_provided".to_owned(),
            },
            chain_slot: None,
            transaction_index: None,
            instruction_path: Vec::new(),
            log_index: None,
            finality: Some(OpenVariant::known("processed").unwrap()),
            acquisition_started_at: persisted_at(),
            requested_at: None,
            monotonic_clock_id: "golden-fixture-process-001".to_owned(),
            acquisition_started_monotonic_ns: 10,
            received_monotonic_ns: 20,
            persisted_at: persisted_at(),
        },
    )
    .unwrap();
    let EvidenceDraft::Observation(draft) = draft else {
        panic!("expected observation draft");
    };
    let retained: RetainedFrameEnvelope = serde_json::from_slice(&draft.payload).unwrap();
    assert_eq!(retained.body, PUMP_NEW);
    assert_eq!(retained.direction, FrameDirection::Inbound);
    assert_eq!(retained.stream_class, StreamClass::BroadCensus);
    assert!(draft.acquisition.source_locator.is_some());
    assert!(
        !draft
            .acquisition
            .source_locator
            .unwrap()
            .as_str()
            .contains("api-key")
    );
}

#[test]
fn sanitized_live_characterization_is_explicitly_not_replay_evidence() {
    let value: serde_json::Value = serde_json::from_slice(HELIUS_LIVE_CHARACTERIZATION).unwrap();
    assert_eq!(
        value["fixture_contract"],
        "joshi.sanitized_provider_characterization.v1"
    );
    assert_eq!(value["not_replay_evidence"], true);
    assert_eq!(value["sample"]["connection_attempts"], 1);
    assert_eq!(value["route_aggregate"]["unknown_route_notifications"], 0);
}
