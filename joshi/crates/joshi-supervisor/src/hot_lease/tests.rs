//! Offline proof of the two things a hot lease must never get wrong: it stops at the first
//! exhausted ceiling, and it turns every interval it did not observe into an exact durable row.

use std::time::Duration;

use bytes::Bytes;
use joshi_acquisition_policy::{
    HotLeaseTermsV1, PressureStage, ScopeSubject, SourceFamily, SubjectKind,
};
use joshi_admission::{SourceFrameInput, source_frames};
use joshi_domain::{StableString, UtcTimestamp, WireU64};
use joshi_sources::{
    ADAPTER_CONTRACT_VERSION, ContentType, CoverageEvent, Cursor, EvidenceContext, FrameDirection,
    HealthEvent, LogicalSourceLocator, ProviderEventTime, RawSourceFrame, SourceHealth, SourceId,
    SourceOutput, StreamClass, Transport, UnixMillis,
};
use joshi_store::{SqliteStore, StoreConfig, StoreMode};

use crate::hot_lease::{
    LeaseCommitContext, LeaseLedger, LeaseSignal, LeaseStop, SEVERITY_DEGRADED,
    SEVERITY_SCOPE_STOPPED, commit_lease, derive_mint_universe, lease_attempt_claim,
    lease_run_budget, read_lease, retain::utc_from_millis, websocket_source_registration,
};

const SUBJECT: &str = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump";
const OPEN_MS: i64 = 1_786_882_538_000;

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable test value")
}

fn instant(millis: i64) -> UtcTimestamp {
    utc_from_millis(millis).expect("representable instant")
}

/// Terms with a 60-second window, a 4 MiB ingress ceiling, and a 10-frame ceiling.
fn terms(window_ms: u64, max_ingress_bytes: u64, max_frames: u64) -> HotLeaseTermsV1 {
    HotLeaseTermsV1 {
        contract: stable(joshi_acquisition_policy::HOT_LEASE_TERMS_CONTRACT),
        schema_version: WireU64::new(1),
        decision_occurrence_id: stable("decision-test"),
        intent_id: stable("intent-test"),
        scope_record_id: stable("desired-record-test"),
        subject: ScopeSubject {
            kind: SubjectKind::Mint,
            key: stable(SUBJECT),
        },
        source_key: stable("helius-websocket-mainnet"),
        operation_key: stable("mint-hot-logs-subscription"),
        source_family: SourceFamily::HeliusPublicChain,
        pressure_stage: PressureStage::Full,
        opened_at: instant(OPEN_MS),
        expires_at: instant(OPEN_MS + i64::try_from(window_ms).unwrap()),
        window_us: WireU64::new(window_ms * 1_000),
        max_connections: WireU64::new(1),
        max_frames: WireU64::new(max_frames),
        max_ingress_bytes: WireU64::new(max_ingress_bytes),
        max_provider_credits: WireU64::new(1_000),
        exact_public_bodies: true,
        degradations: Vec::new(),
        census_ids: vec![stable("census-test")],
        authority: stable("read_only_no_execution"),
    }
}

fn subscribe_request(at: i64) -> SourceOutput {
    SourceOutput::Frame(RawSourceFrame {
        contract_version: ADAPTER_CONTRACT_VERSION.to_owned(),
        source: SourceId::HeliusWebSocket,
        transport: Transport::WebSocket,
        stream_class: StreamClass::LeasedHot,
        direction: FrameDirection::OutboundControl,
        content_type: ContentType::Json,
        received_at: UnixMillis(at),
        connection_epoch: 1,
        sequence: 1,
        http_status: None,
        safe_headers: Vec::new(),
        body: Bytes::from_static(
            br#"{"jsonrpc":"2.0","id":1,"method":"logsSubscribe","params":[{"mentions":["9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"]},{"commitment":"confirmed"}]}"#,
        ),
    })
}

fn inbound(at: i64, sequence: u64, body: Vec<u8>) -> SourceOutput {
    SourceOutput::Frame(RawSourceFrame::inbound_websocket(
        SourceId::HeliusWebSocket,
        StreamClass::LeasedHot,
        UnixMillis(at),
        1,
        sequence,
        ContentType::Json,
        Bytes::from(body),
    ))
}

fn acknowledgement(at: i64) -> SourceOutput {
    inbound(at, 2, br#"{"jsonrpc":"2.0","result":41,"id":1}"#.to_vec())
}

fn notification(at: i64, sequence: u64, slot: u64, padding: usize) -> SourceOutput {
    let body = format!(
        r#"{{"jsonrpc":"2.0","method":"logsNotification","params":{{"subscription":41,"result":{{"context":{{"slot":{slot}}},"value":{{"signature":"{}","err":null,"logs":["Program log: pad"]}}}}}}}}"#,
        "s".repeat(padding)
    );
    inbound(at, sequence, body.into_bytes())
}

fn disconnected(at: i64, reason: &str) -> Vec<SourceOutput> {
    // Exactly what `WebSocketRunner` emits when a live socket ends: a health transition and a
    // coverage gap opened at the same instant.
    let mut health = SourceHealth::new(SourceId::HeliusWebSocket, UnixMillis(at));
    let event = HealthEvent::Disconnected {
        reason: reason.to_owned(),
    };
    health.apply(UnixMillis(at), &event);
    vec![
        SourceOutput::Health {
            at: UnixMillis(at),
            event,
            snapshot: health.snapshot().clone(),
        },
        SourceOutput::Coverage(CoverageEvent::GapOpened {
            source: SourceId::HeliusWebSocket,
            connection_epoch: 1,
            at: UnixMillis(at),
            after_cursor: Some(Cursor::SolanaSlot(440_345_975)),
            reason: reason.to_owned(),
        }),
    ]
}

fn catalog(root: &std::path::Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 4 * 1024 * 1024,
        busy_timeout: Duration::from_secs(5),
        catalog_id: stable("joshi-hot-lease-test"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 64 * 1024 * 1024,
    }
}

fn commit_context() -> LeaseCommitContext {
    LeaseCommitContext {
        subject_key: SUBJECT.to_owned(),
        request_fingerprint_material: format!(
            "transport=websocket;method=logsSubscribe;mentions={SUBJECT};commitment=confirmed"
        ),
        persisted_at: instant(OPEN_MS + 120_000),
        writer_clock_id: "joshi-hot-lease-test".to_owned(),
        committed_mono_ns: 5_000_000,
        max_observations_per_batch: 64,
    }
}

/// A dropped socket must become an exact durable interval, readable after the writer is gone.
#[test]
fn a_dropped_socket_becomes_an_exact_gap_row_and_never_a_silence() {
    let mut ledger = LeaseLedger::open(
        terms(60_000, 4 * 1024 * 1024, 10_000),
        "test-disconnect".to_owned(),
        OPEN_MS,
    )
    .expect("terms open a lease");

    ledger.accept(subscribe_request(OPEN_MS + 10), 10).unwrap();
    ledger.accept(acknowledgement(OPEN_MS + 250), 250).unwrap();
    ledger
        .accept(notification(OPEN_MS + 1_000, 3, 440_345_975, 64), 1_000)
        .unwrap();
    for output in disconnected(OPEN_MS + 4_000, "peer_closed") {
        ledger.accept(output, 4_000).unwrap();
    }
    ledger.close(
        OPEN_MS + 4_200,
        LeaseStop::ProviderDisconnected {
            reason: "peer_closed".to_owned(),
        },
    );

    // Two intervals: before the acknowledgement, and from the exact instant the socket dropped
    // through to the leased expiry, carrying the provider's own reason for the drop.
    let gaps = ledger.gaps();
    assert_eq!(gaps.len(), 2, "gaps: {gaps:#?}");
    assert_eq!(gaps[0].lower_unix_ms, OPEN_MS);
    assert_eq!(gaps[0].upper_unix_ms, OPEN_MS + 250);
    assert_eq!(gaps[0].reason, "subscription_not_yet_acknowledged");
    assert_eq!(gaps[0].severity, SEVERITY_DEGRADED);
    assert_eq!(gaps[1].lower_unix_ms, OPEN_MS + 4_000);
    assert_eq!(gaps[1].upper_unix_ms, OPEN_MS + 60_000);
    assert!(gaps[1].reason.contains("peer_closed"));
    assert_eq!(gaps[1].severity, SEVERITY_SCOPE_STOPPED);
    assert_eq!(gaps[1].after_slot, Some(440_345_975));

    // Every millisecond of the leased window is either observed or named by a gap.
    let unobserved: i64 = gaps.iter().map(|gap| gap.duration_ms).sum();
    assert_eq!(unobserved + ledger.observed_ms(), 60_000);

    let root = tempfile::tempdir().expect("temporary catalog root");
    let receipt = {
        let mut store =
            SqliteStore::open(catalog(root.path()), StoreMode::SingleWriter).expect("catalog");
        store.migrate(instant(OPEN_MS)).expect("migrations");
        commit_lease(&mut store, &ledger, &commit_context()).expect("lease retains")
    };
    assert_eq!(receipt.gap_ids.len(), 2);
    assert_eq!(receipt.retained_observations, 3);
    // Both severities were admitted, so the coverage claim landed in two durable batches.
    assert_eq!(receipt.coverage_batches.len(), 2);

    // The writer is gone. Read the lease back out of the reopened catalog.
    let readback =
        read_lease(&catalog(root.path()), &receipt.coverage_id, 4_096).expect("lease reads back");
    let window = readback.coverage.expect("the coverage claim survived");
    assert_eq!(window.coverage_level, "hot");
    assert_eq!(window.scope_key, SUBJECT);
    assert_eq!(readback.gaps.len(), 2);
    assert_eq!(readback.websocket_observation_count, 3);
    assert!(readback.read_back_payload_bytes > 0);
    assert_eq!(readback.highest_observed_slot, Some(440_345_975));
    assert!(
        readback
            .first_payload_preview
            .as_deref()
            .is_some_and(|preview| preview.contains("joshi.raw_source_frame.v1")),
        "the retained payload is the versioned frame envelope"
    );
    assert!(
        readback
            .first_frame_body_preview
            .as_deref()
            .is_some_and(|body| body.contains("logsSubscribe") && body.contains(SUBJECT)),
        "the retained outbound request proves exactly what was subscribed, and to nothing else"
    );

    // Each stored interval carries both of its exact boundaries in microseconds.
    for (index, gap) in readback.gaps.iter().enumerate() {
        let expected = &gaps[index];
        assert_eq!(gap.event_lower_us, Some(expected.lower_unix_ms * 1_000));
        assert_eq!(gap.event_upper_us, Some(expected.upper_unix_ms * 1_000));
        assert_eq!(gap.duration_us(), Some(expected.duration_ms * 1_000));
        assert_eq!(gap.cause_code, expected.reason);
        assert_eq!(gap.severity, expected.severity);
        assert_eq!(gap.scope_subject.as_deref(), Some(SUBJECT));
    }
}

/// The lease stops at the first exhausted ceiling and says which one.
#[test]
fn the_byte_ceiling_stops_the_lease_and_opens_a_terminal_interval() {
    // A ceiling just above the reserved single-frame headroom, so two padded notifications reach
    // it. The stop threshold is the ceiling minus that headroom.
    let ceiling = crate::hot_lease::INGRESS_STOP_HEADROOM_BYTES + 8_192;
    let mut ledger = LeaseLedger::open(
        terms(60_000, ceiling, 10_000),
        "test-bytes".to_owned(),
        OPEN_MS,
    )
    .expect("terms open a lease");
    ledger.accept(acknowledgement(OPEN_MS + 100), 100).unwrap();
    let mut signal = LeaseSignal::Continue;
    let mut sent = 0_u64;
    let mut at = OPEN_MS + 200;
    while signal == LeaseSignal::Continue && sent < 64 {
        sent += 1;
        at += 10;
        signal = ledger
            .accept(notification(at, sent + 10, 440_345_975 + sent, 4_096), 0)
            .unwrap();
    }
    assert_eq!(signal, LeaseSignal::Stop);
    assert!(ledger.ingress_bytes() >= ceiling - crate::hot_lease::INGRESS_STOP_HEADROOM_BYTES);
    assert!(
        ledger.ingress_bytes() <= ceiling,
        "the reserved worst case must still contain the frame that reached the ceiling"
    );
    let stop = ledger.stop().cloned().expect("a ceiling stopped the lease");
    assert!(matches!(stop, LeaseStop::IngressByteCeiling { .. }));

    ledger.close(at, stop);
    let terminal = ledger.gaps().last().expect("a terminal interval");
    assert_eq!(terminal.lower_unix_ms, at);
    assert_eq!(terminal.upper_unix_ms, OPEN_MS + 60_000);
    assert!(terminal.reason.contains("ingress_byte_ceiling_exhausted"));
    assert_eq!(terminal.severity, SEVERITY_SCOPE_STOPPED);
}

/// The frame ceiling is enforced independently of the byte ceiling.
#[test]
fn the_frame_ceiling_stops_the_lease_independently() {
    let mut ledger = LeaseLedger::open(
        terms(60_000, 8 * 1024 * 1024, 3),
        "test-frames".to_owned(),
        OPEN_MS,
    )
    .expect("terms open a lease");
    assert_eq!(
        ledger.accept(acknowledgement(OPEN_MS + 100), 100).unwrap(),
        LeaseSignal::Continue
    );
    assert_eq!(
        ledger
            .accept(notification(OPEN_MS + 200, 3, 1, 16), 0)
            .unwrap(),
        LeaseSignal::Continue
    );
    assert_eq!(
        ledger
            .accept(notification(OPEN_MS + 300, 4, 2, 16), 0)
            .unwrap(),
        LeaseSignal::Stop
    );
    assert!(matches!(
        ledger.stop(),
        Some(LeaseStop::FrameCeiling { ceiling: 3, .. })
    ));
    assert_eq!(ledger.inbound_frames(), 3);
    assert_eq!(ledger.notifications(), 2);
}

/// A lease that runs its whole window and never disconnects owes exactly one interval: the one
/// before the provider acknowledged the subscription.
#[test]
fn a_clean_window_owes_only_the_pre_acknowledgement_interval() {
    let mut ledger = LeaseLedger::open(
        terms(30_000, 4 * 1024 * 1024, 10_000),
        "test-clean".to_owned(),
        OPEN_MS,
    )
    .expect("terms open a lease");
    ledger.accept(subscribe_request(OPEN_MS + 5), 5).unwrap();
    ledger.accept(acknowledgement(OPEN_MS + 180), 180).unwrap();
    ledger
        .accept(notification(OPEN_MS + 900, 3, 7, 32), 900)
        .unwrap();
    ledger.close(OPEN_MS + 30_000, LeaseStop::WindowElapsed);
    assert_eq!(ledger.gaps().len(), 1);
    assert_eq!(ledger.gaps()[0].upper_unix_ms, OPEN_MS + 180);
    assert_eq!(ledger.observed_ms(), 30_000 - 180);
}

/// The registration the coverage batch uses must be the one the frame path already wrote.
#[test]
fn registration_matches_the_frame_path() {
    let root = tempfile::tempdir().expect("temporary catalog root");
    let mut store =
        SqliteStore::open(catalog(root.path()), StoreMode::SingleWriter).expect("catalog");
    store.migrate(instant(OPEN_MS)).expect("migrations");

    let SourceOutput::Frame(frame) = acknowledgement(OPEN_MS + 100) else {
        unreachable!("acknowledgement is a frame")
    };
    let batch = source_frames(
        vec![SourceFrameInput {
            context: EvidenceContext {
                occurrence_namespace: "registration-probe".to_owned(),
                redacted_request_fingerprint_material: "method=logsSubscribe".to_owned(),
                parent_acquisition_id: None,
                locator: LogicalSourceLocator::HeliusWebSocket {
                    subscription: "logsSubscribe",
                },
                source_variant: joshi_domain::OpenVariant::known("probe").unwrap(),
                source_cursor: None,
                source_events: Vec::new(),
                provider_event_time: ProviderEventTime::Missing {
                    reason: "probe".to_owned(),
                },
                chain_slot: None,
                transaction_index: None,
                instruction_path: Vec::new(),
                log_index: None,
                finality: None,
                acquisition_started_at: instant(OPEN_MS + 100),
                requested_at: None,
                monotonic_clock_id: "probe".to_owned(),
                acquisition_started_monotonic_ns: 1,
                received_monotonic_ns: 2,
                persisted_at: instant(OPEN_MS + 100),
            },
            frame,
        }],
        Vec::new(),
        Vec::new(),
        stable("registration-probe"),
        instant(OPEN_MS + 100),
        stable("probe-clock"),
        1,
    )
    .expect("frame batch builds");
    batch.commit(&mut store).expect("frame batch commits");

    // If this crate's reproduction of the registration recipe drifted, the store would refuse it
    // as an identity conflict rather than silently accept a second contract for one source.
    let status = store
        .register_source(&websocket_source_registration().expect("registration builds"))
        .expect("registration matches the one the frame path already wrote");
    assert_eq!(status, joshi_store::IdempotencyStatus::Idempotent);
}

/// The run budget a lease preregisters is finite in every dimension and never widens its terms.
#[test]
fn the_preregistered_budget_is_finite_and_no_wider_than_the_terms() {
    let terms = terms(45_000, 8 * 1024 * 1024, 20_000);
    let limits = lease_run_budget(&terms).expect("terms form a valid envelope");
    assert_eq!(limits.maximum_requests, terms.max_connections.get());
    assert_eq!(limits.maximum_ingress_bytes, terms.max_ingress_bytes.get());
    assert_eq!(limits.maximum_in_flight_attempts, 1);
    assert!(limits.maximum_elapsed_ms >= terms.window_ms());
    assert!(limits.maximum_ingress_bytes_per_second.is_some());
    let claim = lease_attempt_claim(limits);
    assert_eq!(claim.requests, 1);
    assert!(claim.maximum_ingress_bytes <= limits.maximum_ingress_bytes);
    claim.validate().expect("one bounded connection");

    // A window of zero has no lease in it.
    let mut empty = terms.clone();
    empty.window_us = WireU64::new(0);
    assert!(lease_run_budget(&empty).is_err());
    assert!(LeaseLedger::open(empty, "n".to_owned(), OPEN_MS).is_err());

    // A byte ceiling that cannot contain one in-flight frame is refused outright.
    let mut thin = terms;
    thin.max_ingress_bytes = WireU64::new(crate::hot_lease::INGRESS_STOP_HEADROOM_BYTES);
    assert!(LeaseLedger::open(thin, "n".to_owned(), OPEN_MS).is_err());
}

/// The eligible universe is exactly the mints the provider named, and nothing else.
#[test]
fn the_census_universe_is_only_what_the_provider_named() {
    let envelope = |body: &str| {
        serde_json::to_vec(&joshi_sources::RetainedFrameEnvelope {
            envelope_version: joshi_sources::RETAINED_FRAME_ENVELOPE_VERSION.to_owned(),
            adapter_contract_version: ADAPTER_CONTRACT_VERSION.to_owned(),
            transport: Transport::Http,
            stream_class: StreamClass::Backfill,
            direction: FrameDirection::Inbound,
            original_content_type: ContentType::Json,
            http_status: Some(200),
            safe_headers: Vec::new(),
            body: body.as_bytes().to_vec(),
        })
        .expect("envelope encodes")
    };
    let older = envelope(
        r#"{"result":{"slot":100,"meta":{"preTokenBalances":[{"mint":"So11111111111111111111111111111111111111112"}],
             "postTokenBalances":[{"mint":"9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"},
                                  {"mint":"So11111111111111111111111111111111111111112"}]}}}"#,
    );
    let newer = envelope(
        r#"{"result":{"slot":200,"meta":{"postTokenBalances":[{"mint":"4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"},
                                  {"mint":"9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"}]}}}"#,
    );
    let empty = envelope(r#"{"result":378123456}"#);
    let universe = derive_mint_universe(&[
        ("obs-1".to_owned(), older),
        ("obs-2".to_owned(), newer),
        ("obs-3".to_owned(), empty),
    ])
    .expect("universe derives");

    assert_eq!(universe.subject_count(), 2);
    assert_eq!(universe.payloads_with_mints, 2);
    assert_eq!(universe.derived_from_observations.len(), 3);
    assert!(
        !universe
            .mints
            .iter()
            .any(|sighting| sighting.mint.starts_with("So111")),
        "wrapped SOL is the venue's quote asset, never a leasable subject"
    );
    let pump = universe
        .mints
        .iter()
        .find(|sighting| sighting.mint.ends_with("pump"))
        .expect("the pump mint is in the universe");
    assert_eq!(pump.sightings, 2);
    assert_eq!(pump.highest_slot, Some(200));

    // Highest slot first, then fewest sightings: the mint specific to the newest transaction.
    let promoted = universe.deterministic_promotion().expect("a promotion");
    assert_eq!(
        promoted.mint,
        "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    );

    // A payload that is not a retained frame envelope is a refusal, not a silently empty universe.
    assert!(derive_mint_universe(&[("obs-4".to_owned(), b"not-an-envelope".to_vec())]).is_err());
}

/// The resource snapshot is read from this filesystem and this process, not defaulted.
#[test]
fn the_resource_snapshot_is_measured_rather_than_declared() {
    let root = tempfile::tempdir().expect("temporary run root");
    std::fs::write(root.path().join("retained.bin"), vec![7_u8; 4_096]).expect("write");
    let sampled_at = UtcTimestamp::new(
        time::OffsetDateTime::now_utc()
            .replace_nanosecond(0)
            .expect("aligned"),
    )
    .expect("now");
    let measurement = crate::hot_lease::measure(
        root.path(),
        crate::hot_lease::ResourceCeilings::local_workstation(4_096),
        crate::hot_lease::IngressOccupancy {
            records_used: 0,
            buffer_bytes_used: 0,
        },
        sampled_at,
    )
    .expect("this machine can be measured");

    assert!(measurement.disk_free_bytes.get() > 0);
    assert_eq!(
        measurement.disk_free_bytes.get(),
        measurement.statvfs_fragment_bytes.get() * measurement.statvfs_blocks_available.get()
    );
    assert!(measurement.retained_bytes_today.get() >= 4_096);
    assert!(measurement.retained_files_today.get() >= 1);

    let snapshot = measurement
        .snapshot()
        .expect("readings reduce to a snapshot");
    assert_eq!(snapshot.sampled_at, sampled_at);
    assert_eq!(snapshot.evidence.len(), 1);
    assert_eq!(
        snapshot.evidence[0]
            .digest
            .as_ref()
            .map(joshi_domain::ValueDigest::as_str),
        Some(measurement.digest().expect("digest").as_str())
    );
    assert!(snapshot.queue_record_control_reserve < snapshot.queue_record_capacity);
    assert!(snapshot.disk_free_bytes.get() > 0);

    // The measurement is its own content address: a changed reading is a changed digest.
    let mut altered = measurement.clone();
    altered.retained_bytes_today = WireU64::new(altered.retained_bytes_today.get() + 1);
    assert_ne!(
        altered.digest().expect("digest"),
        measurement.digest().expect("digest")
    );
}
