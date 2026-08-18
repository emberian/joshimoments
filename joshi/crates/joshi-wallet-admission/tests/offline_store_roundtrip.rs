use std::time::Duration;

use joshi_admission::PublicStatus;
use joshi_domain::{AssetId, CoverageId, CursorId, OpenVariant, StableString, UtcTimestamp};
use joshi_sources::{
    ContentType, EvidenceContext, FrameDirection, LogicalSourceLocator, ProviderEventTime,
    RawSourceFrame, SourceId, StreamClass, Transport, UnixMillis,
};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};
use joshi_wallet_admission::{
    WalletAdmissionError, WalletAdmissionMetadata, WalletAdmissionRequest, prepare_wallet_admission,
};
use joshi_wallet_source::{
    AcquisitionResponseContext, AcquisitionSurface, Canonicality, Commitment, PublicKey,
    TransactionVersionInput,
};
use joshi_wallet_topology::{
    CoverageBinding, ReducerConfig, SnapshotId, SnapshotRequest, TopologyFact,
};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

const FINALIZED: &[u8] =
    include_bytes!("../../../fixtures/wallet-source/finalized_pump_pumpswap_exact.json");
const FIRST_SIGNATURE: &str =
    "5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv";
const SECOND_SIGNATURE: &str =
    "3ShNEcfKhWrvFVTwHCK7FjgWXABAZgo9Cpr2S6AGngg9xDifcQyY2mGQQ85p11vxSRvQ3B3SbaajobL1rfSJmyjG";

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap()
}

fn timestamp(value: &str) -> UtcTimestamp {
    value.parse().unwrap()
}

fn frame(bytes: Vec<u8>, sequence: u64) -> RawSourceFrame {
    RawSourceFrame {
        contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
        source: SourceId::HeliusHttp,
        transport: Transport::Fixture,
        stream_class: StreamClass::Backfill,
        direction: FrameDirection::Inbound,
        content_type: ContentType::Json,
        received_at: UnixMillis(1_786_881_600_000),
        connection_epoch: 0,
        sequence,
        http_status: Some(200),
        safe_headers: Vec::new(),
        body: bytes.into(),
    }
}

fn evidence_context(sequence: u64, time: &str) -> EvidenceContext {
    EvidenceContext {
        occurrence_namespace: "wallet-w4-offline-store".to_owned(),
        redacted_request_fingerprint_material: format!("wallet W4 fixture {sequence}"),
        parent_acquisition_id: None,
        locator: LogicalSourceLocator::Fixture {
            name: format!("wallet-w4-{sequence}"),
        },
        source_variant: OpenVariant::known("wallet_finalized_transaction_page").unwrap(),
        source_cursor: None,
        source_events: Vec::new(),
        provider_event_time: ProviderEventTime::Missing {
            reason: "page_contains_multiple_chain_times".to_owned(),
        },
        chain_slot: None,
        transaction_index: None,
        instruction_path: Vec::new(),
        log_index: None,
        finality: Some(OpenVariant::known("finalized").unwrap()),
        acquisition_started_at: timestamp(time),
        requested_at: Some(timestamp(time)),
        monotonic_clock_id: "wallet-w4-test-process".to_owned(),
        acquisition_started_monotonic_ns: sequence * 100,
        received_monotonic_ns: sequence * 100 + 20,
        persisted_at: timestamp(time),
    }
}

fn response_context(
    coverage_id: &str,
    time: &str,
    version: u64,
    canonicality: &Canonicality,
) -> AcquisitionResponseContext {
    let version_input = |signature: &str| TransactionVersionInput {
        signature: stable(signature),
        version: version.into(),
        supersedes_transaction_fact_id: (version > 1)
            .then(|| stable(&format!("solana.transaction:{signature}:v{}", version - 1))),
        canonicality: canonicality.clone(),
    };
    AcquisitionResponseContext {
        surface: AcquisitionSurface::HeliusGetTransactionsForAddress,
        scope_ids: vec![stable("scope:wallet:w4")],
        requested_public_keys: vec![
            PublicKey::new("M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K").unwrap(),
        ],
        mint_filter: Some(PublicKey::new("So11111111111111111111111111111111111111112").unwrap()),
        commitment: Commitment::Finalized,
        available_at: timestamp(time),
        cursor_before: None,
        coverage_gap_ids: Vec::new(),
        coverage_ids: vec![stable(coverage_id)],
        transaction_versions: vec![
            version_input(FIRST_SIGNATURE),
            version_input(SECOND_SIGNATURE),
        ],
    }
}

fn metadata(
    batch_id: &str,
    coverage_id: &str,
    time: &str,
    predecessor: Option<CursorId>,
) -> WalletAdmissionMetadata {
    WalletAdmissionMetadata {
        batch_id: stable(batch_id),
        coverage_id: CoverageId::new(coverage_id).unwrap(),
        coverage_family: OpenVariant::known("hot_lane").unwrap(),
        coverage_subject: Some(stable(
            "solana.account:M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K",
        )),
        predecessor_cursor_id: predecessor,
        committed_at: timestamp(time),
        writer_clock_id: stable("wallet-w4-test-writer"),
        committed_mono_ns: 500.into(),
        writer_build: stable("wallet-admission-test-v1"),
    }
}

fn snapshot_request(id: &str, coverage_id: &str, time: &str) -> SnapshotRequest {
    SnapshotRequest {
        snapshot_id: SnapshotId::new(id).unwrap(),
        available_through: timestamp(time),
        event_slot: 355_001_241.into(),
        event_time: timestamp(time),
        accepted_finalities: vec![stable("finalized")],
        accepted_canonicalities: vec![stable("canonical")],
        focus_mint_ids: vec![
            AssetId::new("solana.mint:So11111111111111111111111111111111111111112").unwrap(),
        ],
        requested_coverage_ids: vec![CoverageId::new(coverage_id).unwrap()],
        co_trade_window_slots: 10.into(),
        max_pair_rows: 100.into(),
    }
}

fn store(temp: &TempDir) -> SqliteStore {
    store_named(temp, "catalog:wallet-w4-test")
}

fn store_named(temp: &TempDir, catalog_id: &str) -> SqliteStore {
    let root = temp.path();
    let mut store = SqliteStore::open(
        StoreConfig {
            catalog_path: root.join("wallet.sqlite3"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024 * 1024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: stable(catalog_id),
            max_observations_per_batch: 256,
            max_raw_bytes_per_batch: 4 * 1024 * 1024,
        },
        StoreMode::SingleWriter,
    )
    .unwrap();
    store
        .migrate(timestamp("2026-08-16T11:59:00.000000Z"))
        .unwrap();
    store
}

fn prepare_named(
    bytes: Vec<u8>,
    sequence: u64,
    batch_id: &str,
    coverage_id: &str,
) -> joshi_wallet_admission::PreparedWalletAdmission {
    prepare_wallet_admission(WalletAdmissionRequest {
        frame: frame(bytes, sequence),
        evidence_context: evidence_context(sequence, "2026-08-16T12:00:00.000000Z"),
        response_context: response_context(
            coverage_id,
            "2026-08-16T12:00:00.000000Z",
            1,
            &Canonicality::Canonical,
        ),
        metadata: metadata(batch_id, coverage_id, "2026-08-16T12:00:00.000000Z", None),
    })
    .unwrap()
}

fn prepare_first() -> joshi_wallet_admission::PreparedWalletAdmission {
    prepare_named(
        FINALIZED.to_vec(),
        1,
        "batch:wallet:w4:v1",
        "coverage:wallet:w4:v1",
    )
}

#[test]
fn exact_frame_receipt_facts_coverage_and_snapshot_close() {
    let temp = TempDir::new().unwrap();
    let mut store = store(&temp);
    let admitted = prepare_first()
        .commit(
            &mut store,
            ReducerConfig::new(500, 10, 500, 100).unwrap(),
            snapshot_request(
                "snapshot:wallet:w4:v1",
                "coverage:wallet:w4:v1",
                "2026-08-16T12:00:00.000000Z",
            ),
            None,
        )
        .unwrap();

    assert_eq!(admitted.receipt.admitted.observations, "1");
    assert_eq!(admitted.receipt.admitted.source_events, "2");
    assert_eq!(admitted.receipt.admitted.coverage_windows, "1");
    assert_eq!(admitted.receipt.admitted.cursor_advances, "1");
    assert_eq!(admitted.raw_body_len.get(), FINALIZED.len() as u64);
    assert_eq!(
        admitted.raw_body_digest.as_str(),
        format!("sha256:{:x}", Sha256::digest(FINALIZED))
    );
    assert_eq!(admitted.transaction_facts.len(), 2);
    assert_eq!(
        admitted
            .transaction_facts
            .iter()
            .map(|fact| fact.executed_transfers.len())
            .sum::<usize>(),
        4
    );
    assert_eq!(
        admitted
            .transaction_facts
            .iter()
            .map(|fact| fact.decoded_swaps.len())
            .sum::<usize>(),
        2
    );
    assert!(
        admitted
            .topology_facts
            .iter()
            .any(|fact| matches!(fact, TopologyFact::CallerAccount(_)))
    );
    assert_eq!(
        admitted
            .topology_facts
            .iter()
            .filter(|fact| matches!(fact, TopologyFact::SameTransactionBundle(_)))
            .count(),
        2
    );
    assert!(admitted.quarantined_enhanced_projections.is_empty());
    assert!(admitted.justified_cursor.is_some());
    assert!(matches!(
        &admitted.topology_snapshot.coverage_binding,
        CoverageBinding::StoreVerified { coverage_ids, .. }
            if coverage_ids == &admitted.verified_coverage_ids
    ));
    let report = store.verify(VerifyDepth::Full).unwrap();
    assert_eq!(report.integrity, "ok");
    assert_eq!(report.foreign_key_defects, 0);

    // Exact replay returns the already-committed receipt; it cannot create a second cursor or
    // silently admit changed bytes under the same batch/occurrence identities.
    let retry = prepare_first()
        .commit(
            &mut store,
            ReducerConfig::new(500, 10, 500, 100).unwrap(),
            snapshot_request(
                "snapshot:wallet:w4:v1:retry",
                "coverage:wallet:w4:v1",
                "2026-08-16T12:00:00.000000Z",
            ),
            None,
        )
        .unwrap();
    assert_eq!(retry.receipt.status, PublicStatus::Idempotent);
    assert_eq!(retry.receipt.batch_digest, admitted.receipt.batch_digest);
    assert_eq!(retry.receipt.commit_seq, admitted.receipt.commit_seq);
}

#[test]
fn later_noncanonical_versions_are_visible_without_rewriting_prior_snapshot() {
    let temp = TempDir::new().unwrap();
    let mut store = store(&temp);
    let first = prepare_first()
        .commit(
            &mut store,
            ReducerConfig::new(500, 10, 500, 100).unwrap(),
            snapshot_request(
                "snapshot:wallet:w4:v1",
                "coverage:wallet:w4:v1",
                "2026-08-16T12:00:00.000000Z",
            ),
            None,
        )
        .unwrap();
    let frozen_snapshot = serde_json::to_vec(&first.topology_snapshot).unwrap();
    assert!(!first.topology_snapshot.accepted_facts.is_empty());

    let mut corrected_json: serde_json::Value = serde_json::from_slice(FINALIZED).unwrap();
    corrected_json["result"]
        .as_object_mut()
        .unwrap()
        .remove("paginationToken");
    let history = first.verified_history();
    let mut correction_snapshot_request = snapshot_request(
        "snapshot:wallet:w4:v2",
        "coverage:wallet:w4:v2",
        "2026-08-16T12:01:00.000000Z",
    );
    correction_snapshot_request.requested_coverage_ids = vec![
        CoverageId::new("coverage:wallet:w4:v1").unwrap(),
        CoverageId::new("coverage:wallet:w4:v2").unwrap(),
    ];
    let correction = prepare_wallet_admission(WalletAdmissionRequest {
        frame: frame(serde_json::to_vec(&corrected_json).unwrap(), 2),
        evidence_context: evidence_context(2, "2026-08-16T12:00:00.000000Z"),
        response_context: response_context(
            "coverage:wallet:w4:v2",
            "2026-08-16T12:01:00.000000Z",
            2,
            &Canonicality::NonCanonical,
        ),
        metadata: metadata(
            "batch:wallet:w4:v2",
            "coverage:wallet:w4:v2",
            "2026-08-16T12:01:00.000000Z",
            None,
        ),
    })
    .unwrap()
    .commit(
        &mut store,
        ReducerConfig::new(1000, 10, 1000, 100).unwrap(),
        correction_snapshot_request,
        Some(&history),
    )
    .unwrap();

    assert_eq!(
        correction
            .topology_snapshot
            .observed_transaction_versions
            .len(),
        2
    );
    assert!(
        correction
            .topology_snapshot
            .observed_transaction_versions
            .iter()
            .all(|fact| fact.version.get() == 2
                && fact.canonicality.discriminator.as_str() == "noncanonical")
    );
    assert!(correction.topology_snapshot.accepted_facts.is_empty());
    assert_eq!(correction.coverage_receipts.len(), 2);
    assert_eq!(correction.verified_coverage_ids.len(), 2);
    assert_eq!(
        correction
            .topology_snapshot
            .excluded_noncanonical_transaction_ids
            .len(),
        2
    );
    assert_eq!(
        serde_json::to_vec(&first.topology_snapshot).unwrap(),
        frozen_snapshot
    );
    assert_ne!(
        first.topology_snapshot_digest,
        correction.topology_snapshot_digest
    );
}

#[test]
fn history_from_an_unrelated_catalog_cannot_enter_a_snapshot() {
    let first_temp = TempDir::new().unwrap();
    let mut first_store = store_named(&first_temp, "catalog:wallet-history-a");
    let first = prepare_named(
        FINALIZED.to_vec(),
        10,
        "batch:wallet:history:a",
        "coverage:wallet:history:a",
    )
    .commit(
        &mut first_store,
        ReducerConfig::new(500, 10, 500, 100).unwrap(),
        snapshot_request(
            "snapshot:wallet:history:a",
            "coverage:wallet:history:a",
            "2026-08-16T12:00:00.000000Z",
        ),
        None,
    )
    .unwrap();
    let unrelated_history = first.verified_history();

    let second_temp = TempDir::new().unwrap();
    let mut second_store = store_named(&second_temp, "catalog:wallet-history-b");
    let result = prepare_named(
        FINALIZED.to_vec(),
        11,
        "batch:wallet:history:b",
        "coverage:wallet:history:b",
    )
    .commit(
        &mut second_store,
        ReducerConfig::new(500, 10, 500, 100).unwrap(),
        snapshot_request(
            "snapshot:wallet:history:b:refused",
            "coverage:wallet:history:b",
            "2026-08-16T12:00:00.000000Z",
        ),
        Some(&unrelated_history),
    );
    assert!(matches!(
        result,
        Err(WalletAdmissionError::HistoryCatalogMismatch)
    ));

    // The exact evidence commit is recoverable even though snapshot construction refused. An
    // exact retry without the unrelated history receives the idempotent receipt and can proceed.
    let recovered = prepare_named(
        FINALIZED.to_vec(),
        11,
        "batch:wallet:history:b",
        "coverage:wallet:history:b",
    )
    .commit(
        &mut second_store,
        ReducerConfig::new(500, 10, 500, 100).unwrap(),
        snapshot_request(
            "snapshot:wallet:history:b:recovered",
            "coverage:wallet:history:b",
            "2026-08-16T12:00:00.000000Z",
        ),
        None,
    )
    .unwrap();
    assert_eq!(recovered.receipt.status, PublicStatus::Idempotent);
    assert_eq!(recovered.coverage_receipts.len(), 1);
}
