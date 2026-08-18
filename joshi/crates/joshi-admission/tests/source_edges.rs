#![cfg(feature = "source-edges")]

use base64::{Engine as _, engine::general_purpose::STANDARD};
use bytes::Bytes;
use joshi_admission::{
    SourceFrameInput, acknowledge_pump_reservations, admit_pump_outcome, source_frames,
};
use joshi_domain::{OpenVariant, StableString, UtcTimestamp};
use joshi_pump_api::{
    BodyCapture, CoverageScope as PumpScope, CoverageWindow as PumpWindow, FetchOutcome,
    IdentityStore,
};
use joshi_sources::{
    ContentType, EvidenceContext, FrameDirection, LogicalSourceLocator, ProviderEventTime,
    RawSourceFrame, SourceId as EdgeSourceId, StreamClass, Transport, UnixMillis,
};
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use std::{path::Path, time::Duration};

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap()
}
fn time(value: &str) -> UtcTimestamp {
    value.parse().unwrap()
}
fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 1024,
        busy_timeout: Duration::from_secs(1),
        catalog_id: stable("source-edge-test"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 1024 * 1024,
    }
}
fn store(root: &Path) -> SqliteStore {
    let mut value = SqliteStore::open(config(root), StoreMode::SingleWriter).unwrap();
    value.migrate(time("2026-08-16T18:00:00.000000Z")).unwrap();
    value
}

#[test]
fn helius_solana_and_pumpportal_frames_share_one_lossless_durable_boundary() {
    let sources = [
        EdgeSourceId::HeliusWebSocket,
        EdgeSourceId::SolanaPublicWebSocket,
        EdgeSourceId::PumpPortalWebSocket,
    ];
    let frames = sources
        .into_iter()
        .enumerate()
        .map(|(index, source)| {
            let sequence = u64::try_from(index + 1).unwrap();
            SourceFrameInput {
                frame: RawSourceFrame {
                    contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.into(),
                    source,
                    transport: Transport::WebSocket,
                    stream_class: StreamClass::BroadCensus,
                    direction: FrameDirection::Inbound,
                    content_type: ContentType::Json,
                    received_at: UnixMillis(1_786_882_538_124),
                    connection_epoch: 1,
                    sequence,
                    http_status: None,
                    safe_headers: vec![],
                    body: Bytes::from(format!("{{\"sequence\":{sequence}}}")),
                },
                context: EvidenceContext {
                    occurrence_namespace: "source-edge-test".into(),
                    redacted_request_fingerprint_material: format!("fixture-sequence-{sequence}"),
                    parent_acquisition_id: None,
                    locator: LogicalSourceLocator::Fixture {
                        name: format!("edge-{sequence}"),
                    },
                    source_variant: OpenVariant::known("fixture_frame").unwrap(),
                    source_cursor: None,
                    source_events: vec![],
                    provider_event_time: ProviderEventTime::Missing {
                        reason: "fixture".into(),
                    },
                    chain_slot: None,
                    transaction_index: None,
                    instruction_path: vec![],
                    log_index: None,
                    finality: None,
                    acquisition_started_at: time("2026-08-16T18:42:18.123000Z"),
                    requested_at: None,
                    monotonic_clock_id: "source-process-test".into(),
                    acquisition_started_monotonic_ns: sequence * 10,
                    received_monotonic_ns: sequence * 10 + 5,
                    persisted_at: time("2026-08-16T18:42:18.125000Z"),
                },
            }
        })
        .collect();
    let batch = source_frames(
        frames,
        vec![],
        vec![],
        stable("batch-source-edges-1"),
        time("2026-08-16T18:42:18.126000Z"),
        stable("core-source-edge-writer"),
        100,
    )
    .unwrap();
    let root = tempfile::tempdir().unwrap();
    let receipt = batch.commit(&mut store(root.path())).unwrap();
    assert_eq!(receipt.admitted.observations, "3");
    assert_eq!(receipt.admitted.acquisitions, "3");
    assert_eq!(receipt.acquisition_ids.len(), 3);
}

#[test]
fn pump_reservation_is_acknowledged_only_after_an_exact_durable_receipt() {
    let root = tempfile::tempdir().unwrap();
    let identities = IdentityStore::open(root.path().join("identities")).unwrap();
    let reservation = identities.reserve().unwrap();
    assert!(reservation.reservation_path.exists());
    let body = br#"{"mint":"MINT000000000001"}"#.to_vec();
    let acquisition = joshi_pump_api::model::Acquisition {
        contract: joshi_pump_api::SOURCE_CONTRACT.into(),
        catalog_version: joshi_pump_api::ROUTE_CATALOG.into(),
        acquisition_id: reservation.acquisition_id.clone(),
        request_group_id: "request-group-1".into(),
        attempt_ordinal: "0".into(),
        route_id: "coin_exact".into(),
        transport: "http".into(),
        access_class: "officially_described_public".into(),
        stability: "documented_mutable".into(),
        session_class: "none".into(),
        source_locator: "https://frontend-api-v3.pump.fun/coins/{mint}".into(),
        request_fingerprint: format!("sha256:{}", "a".repeat(64)),
        http_status: Some(200),
        safe_response_headers: vec![],
        clocks: joshi_pump_api::model::AcquisitionClocks {
            started_at: "2026-08-16T18:42:18.123000Z".into(),
            received_at: "2026-08-16T18:42:18.124000Z".into(),
            monotonic_clock_id: "pump-client-test".into(),
            started_monotonic_ns: "10".into(),
            received_monotonic_ns: "20".into(),
            elapsed_ns: "10".into(),
        },
        body: BodyCapture::Exact {
            boundary: "http_entity_body_post_transfer_decoding_identity_encoding".into(),
            media_type: "application/json".into(),
            bytes_base64: STANDARD.encode(&body),
            byte_length: body.len().to_string(),
            blob_id: joshi_admission::Sha256Digest::of_bytes(&body).to_string(),
        },
    };
    let outcome = FetchOutcome {
        contract: "joshi.pump_api.fetch_outcome.v1".into(),
        request_group_id: "request-group-1".into(),
        attempts: vec![acquisition],
        coverage_windows: vec![PumpWindow {
            window_id: "coverage-pump-1".into(),
            observed_from: "2026-08-16T18:42:18.123000Z".into(),
            observed_to: "2026-08-16T18:42:18.124000Z".into(),
            scope: PumpScope {
                route_id: "coins-current".into(),
                request_fingerprint: format!("sha256:{}", "a".repeat(64)),
                order_semantics: "snapshot".into(),
                cursor_in_fingerprint: None,
                page_size: None,
            },
            acquisition_ids: vec![reservation.acquisition_id.clone()],
            completeness: "complete".into(),
        }],
        coverage_gaps: vec![],
        completed: true,
    };
    let mut forged_public = outcome.clone();
    forged_public.attempts[0].route_id = "user_profile".into();
    forged_public.attempts[0].access_class = "observed_public_product".into();
    forged_public.attempts[0].stability = "authenticated_unverified".into();
    assert!(
        admit_pump_outcome(
            &forged_public,
            "batch-pump-forged-public",
            time("2026-08-16T18:42:18.125000Z"),
            30,
        )
        .is_err()
    );
    let admission = admit_pump_outcome(
        &outcome,
        "batch-pump-1",
        time("2026-08-16T18:42:18.125000Z"),
        30,
    )
    .unwrap();
    let mut durable = store(root.path());
    let receipt = admission.batch.commit(&mut durable).unwrap();
    let mut partial = receipt.clone();
    partial.acquisition_ids.clear();
    assert!(acknowledge_pump_reservations(&identities, &admission, &partial).is_err());
    assert!(reservation.reservation_path.exists());
    let mut wrong = receipt.clone();
    wrong.batch_id = "wrong-batch".into();
    assert!(acknowledge_pump_reservations(&identities, &admission, &wrong).is_err());
    assert!(reservation.reservation_path.exists());
    acknowledge_pump_reservations(&identities, &admission, &receipt).unwrap();
    assert!(!reservation.reservation_path.exists());
}
