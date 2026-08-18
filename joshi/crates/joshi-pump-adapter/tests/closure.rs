use std::{path::Path, time::Duration};

use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use joshi_pump_adapter::{
    OFFLINE_FIXTURE_SELECTION_CONTRACT, PUMP_MEASUREMENT_RECEIPT_CONTRACT, PUMP_POLICY_CONTRACT,
    PUMP_RECEIPT_CONTRACT, PumpSourceKind, close_receipt, close_receipt_bytes, prepare_companion,
    prepare_direct, prepare_direct_with_offline_fixture_selection, prepare_parity_measurement,
    prepare_promotion_measurement,
};
use joshi_pump_api::{AuthDisposition, ParityInputV2, ParitySource};
use joshi_store::{SqliteStore, StoreConfig, StoreMode};

const DIRECT: &[u8] =
    include_bytes!("../../../fixtures/pump-api/direct-fetch-outcome.synthetic.json");
const COMPANION: &[u8] = include_bytes!("../../../apps/core/fixtures/companion_ingress_v1.json");
const OFFLINE_SELECTION: &[u8] =
    include_bytes!("../../../fixtures/pump-api/offline-fixture-selection-v1.json");

fn time(value: &str) -> UtcTimestamp {
    value.parse().unwrap()
}
fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap()
}
fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 1024,
        busy_timeout: Duration::from_secs(1),
        catalog_id: stable("pump-adapter-test"),
        max_observations_per_batch: 128,
        max_raw_bytes_per_batch: 2 * 1024 * 1024,
    }
}
fn store(root: &Path) -> SqliteStore {
    let mut store = SqliteStore::open(config(root), StoreMode::SingleWriter).unwrap();
    store.migrate(time("2026-08-17T12:00:01.000000Z")).unwrap();
    store
}

#[test]
fn direct_ingress_closes_source_batch_policy_spool_and_catalog_domains() {
    let prepared = prepare_direct(
        DIRECT,
        "batch-pump-w4-direct-1",
        time("2026-08-17T12:00:00.020000Z"),
        300,
    )
    .unwrap();
    assert_eq!(prepared.source_kind(), PumpSourceKind::DirectPumpApi);
    assert_eq!(prepared.exact_ingress_bytes(), DIRECT);
    let precommit = prepared.spool_entry(None).unwrap();
    assert_eq!(precommit.closure.policy_contract, PUMP_POLICY_CONTRACT);
    assert_eq!(precommit.closure.admission_digest, None);
    assert_ne!(
        prepared.ingress().exact_ingress.digest.as_str(),
        precommit.closure.logical_digest
    );
    assert_ne!(
        precommit.closure.exact_batch.digest,
        precommit.closure.exact_policy.digest
    );

    let root = tempfile::tempdir().unwrap();
    let public = prepared
        .admission_batch()
        .commit(&mut store(root.path()))
        .unwrap();
    let closed = close_receipt(&prepared, &public).unwrap();
    assert_eq!(closed.contract, PUMP_RECEIPT_CONTRACT);
    assert_eq!(closed.durable_logical_digest, public.batch_digest);
    assert_eq!(closed.store_admission_digest, public.store_admission_digest);
    let admission_digest = ValueDigest::new(public.store_admission_digest.to_string()).unwrap();
    let postcommit = prepared.spool_entry(Some(&admission_digest)).unwrap();
    assert_eq!(
        postcommit.closure.admission_digest.as_deref(),
        Some(public.store_admission_digest.as_str())
    );

    let receipt_bytes = serde_json::to_vec(&public).unwrap();
    assert_eq!(
        close_receipt_bytes(&prepared, &receipt_bytes).unwrap(),
        closed
    );
    let duplicate =
        String::from_utf8(receipt_bytes)
            .unwrap()
            .replacen('{', "{\"contract\":\"duplicate\",", 1);
    assert!(close_receipt_bytes(&prepared, duplicate.as_bytes()).is_err());
}

#[test]
fn offline_fixture_selection_is_exact_separate_evidence_and_not_ordinary_admission() {
    let committed_at = time("2026-08-17T12:00:00.020000Z");
    let ordinary = prepare_direct(DIRECT, "batch-pump-ordinary", committed_at, 300).unwrap();
    assert_eq!(
        ordinary.admission_batch().store.evidence.observations.len(),
        2
    );
    assert_eq!(
        ordinary
            .admission_batch()
            .store
            .evidence
            .coverage_windows
            .len(),
        1
    );

    let prepared = prepare_direct_with_offline_fixture_selection(
        DIRECT,
        OFFLINE_SELECTION,
        "batch-pump-g0-selection",
        committed_at,
        300,
    )
    .unwrap();
    let evidence = &prepared.admission_batch().store.evidence;
    assert_eq!(evidence.observations.len(), 3);
    assert_eq!(evidence.coverage_windows.len(), 3);
    let selection = evidence
        .observations
        .iter()
        .find(|value| {
            value.observation.source_variant.discriminator.as_str() == "offline_fixture_selection"
        })
        .unwrap();
    assert_eq!(selection.payload, OFFLINE_SELECTION);
    assert_eq!(
        selection
            .observation
            .observation_kind
            .discriminator
            .as_str(),
        "fixture"
    );
    assert_eq!(
        selection
            .observation
            .parse_disposition
            .discriminator
            .as_str(),
        "decoded"
    );
    let exact: serde_json::Value = serde_json::from_slice(&selection.payload).unwrap();
    assert_eq!(exact["contract"], OFFLINE_FIXTURE_SELECTION_CONTRACT);
    assert!(evidence.coverage_windows.iter().any(|window| {
        window
            .scope
            .subject
            .as_ref()
            .is_some_and(|value| value.as_str() == "MintA")
            && window.scope.family.discriminator.as_str() == "hot_lane"
    }));
    assert!(evidence.coverage_windows.iter().any(|window| {
        window
            .scope
            .subject
            .as_ref()
            .is_some_and(|value| value.as_str() == "MintB")
            && window.scope.family.discriminator.as_str() == "market_census"
    }));

    let root = tempfile::tempdir().unwrap();
    let public = prepared
        .admission_batch()
        .commit(&mut store(root.path()))
        .unwrap();
    assert_eq!(
        close_receipt(&prepared, &public).unwrap().status,
        public.status
    );
}

#[test]
fn offline_fixture_selection_refuses_subject_substitution() {
    let changed = String::from_utf8(OFFLINE_SELECTION.to_vec())
        .unwrap()
        .replace("MintB", "MintC");
    assert!(
        prepare_direct_with_offline_fixture_selection(
            DIRECT,
            changed.as_bytes(),
            "batch-pump-g0-substitution",
            time("2026-08-17T12:00:00.020000Z"),
            300,
        )
        .is_err()
    );
}

#[test]
fn companion_uses_the_same_durable_closure_and_keeps_its_source_ack_distinct() {
    let prepared = prepare_companion(
        COMPANION,
        time("2026-08-17T12:00:00.020000Z"),
        300,
        "pump-companion-test-writer",
    )
    .unwrap();
    assert_eq!(prepared.source_kind(), PumpSourceKind::PumpCompanion);
    assert_ne!(
        prepared.ingress().source_declared_digest.as_ref().unwrap(),
        &prepared.ingress().exact_ingress.digest
    );
    let root = tempfile::tempdir().unwrap();
    let public = prepared
        .admission_batch()
        .commit(&mut store(root.path()))
        .unwrap();
    let adapter = close_receipt(&prepared, &public).unwrap();
    let browser = prepared.companion_receipt(&public).unwrap();
    assert_eq!(adapter.durable_logical_digest, browser.durable_batch_digest);
    assert_eq!(
        adapter.store_admission_digest,
        browser.store_admission_digest
    );
    assert_eq!(
        adapter.source_declared_digest.as_ref(),
        Some(&browser.ingress_batch_digest)
    );

    let mut wrong = public;
    wrong.batch_id = "wrong-durable-batch".into();
    assert!(close_receipt(&prepared, &wrong).is_err());
    assert!(prepared.companion_receipt(&wrong).is_err());
}

fn parity_input(source: ParitySource, body: &[u8]) -> ParityInputV2 {
    use base64::Engine as _;
    let source_acquisition_id = match source {
        ParitySource::PumpCompanion => "acq:companion-adapter-fixture",
        ParitySource::DirectPumpApi => "acq:direct-adapter-fixture",
    };
    ParityInputV2 {
        contract: "joshi.pump_api.parity_input.v2".into(),
        pair_id: "pair-adapter-fixture".into(),
        source_acquisition_id: source_acquisition_id.into(),
        source,
        route_id: "discovery_coins".into(),
        catalog_version: joshi_pump_api::ROUTE_CATALOG.into(),
        request_fingerprint: joshi_pump_api::client::sha256(b"request"),
        request_fingerprint_contract: "pump-parity-request-projection.v2".into(),
        request_projection_completeness: "complete".into(),
        visible_filter_fingerprint: joshi_pump_api::client::sha256(b"filter"),
        cursor_in_fingerprint: None,
        pagination_kind: "offset_limit".into(),
        page_ordinal: "0".into(),
        session_class: "ordinary_authenticated".into(),
        session_occurrence_id: joshi_pump_api::client::sha256(b"session"),
        auth_disposition: AuthDisposition::OrdinarySessionAccepted,
        comparison_boundary: "fetch_response_decoded_body_bytes".into(),
        started_at: "2026-08-17T12:00:00.000000Z".into(),
        received_at: "2026-08-17T12:00:00.010000Z".into(),
        http_status: 200,
        body_base64: base64::engine::general_purpose::STANDARD.encode(body),
        byte_length: body.len().to_string(),
        blob_id: joshi_pump_api::client::sha256(body),
        rendered_order_digest: None,
    }
}

#[test]
fn mismatches_are_private_exact_observations_not_promoted_facts() {
    let companion = serde_json::to_vec(&parity_input(
        ParitySource::PumpCompanion,
        br#"[{"mint":"MintA"}]"#,
    ))
    .unwrap();
    let direct = serde_json::to_vec(&parity_input(
        ParitySource::DirectPumpApi,
        br#"[{"mint":"MintB"}]"#,
    ))
    .unwrap();
    let measurement = prepare_parity_measurement(
        &companion,
        &direct,
        "batch-pump-parity-fixture",
        time("2026-08-17T12:00:00.020000Z"),
        400,
        "pump-parity-writer",
        50_000,
        20,
    )
    .unwrap();
    assert_eq!(measurement.batch.store.evidence.observations.len(), 3);
    assert_eq!(
        measurement
            .batch
            .store
            .evidence
            .observations
            .iter()
            .map(|value| value.acquisition.acquisition_id.to_string())
            .collect::<std::collections::BTreeSet<_>>()
            .len(),
        2
    );
    assert!(measurement.batch.store.evidence.assertions.is_empty());
    assert!(measurement.batch.store.evidence.source_events.is_empty());
    assert!(
        measurement
            .report
            .mismatches
            .iter()
            .any(|value| value.kind == "ordered_membership")
    );
    assert_eq!(
        measurement.report_bytes,
        serde_json::to_vec(&measurement.report).unwrap()
    );
    assert!(
        measurement
            .batch
            .store
            .observation_storage
            .values()
            .all(|policy| policy.retention_class.as_str() == "app_private" && policy.force_external)
    );
    let precommit = measurement.spool_entry(None).unwrap();
    assert_eq!(precommit.closure.policy_contract, PUMP_POLICY_CONTRACT);
    assert_eq!(precommit.closure.counts.acquisitions, 2);
    assert_eq!(precommit.closure.counts.observations, 3);
    let root = tempfile::tempdir().unwrap();
    let receipt = measurement.batch.commit(&mut store(root.path())).unwrap();
    let closed = measurement.close_receipt(&receipt).unwrap();
    assert_eq!(closed.contract, PUMP_MEASUREMENT_RECEIPT_CONTRACT);
    assert_eq!(closed.measurement_kind, "parity_v2");
    assert_eq!(closed.committed_acquisition_ids.len(), 2);
    let admission_digest = ValueDigest::new(receipt.store_admission_digest.to_string()).unwrap();
    let postcommit = measurement.spool_entry(Some(&admission_digest)).unwrap();
    assert_eq!(
        postcommit.closure.admission_digest.as_deref(),
        Some(receipt.store_admission_digest.as_str())
    );
    assert_eq!(receipt.admitted.observations, "3");
    assert_eq!(receipt.admitted.acquisitions, "2");
    assert_eq!(receipt.admitted.assertions, "0");
}

#[test]
fn promotion_requires_its_own_durable_measurement_receipt_before_any_census_use() {
    let run = std::fs::read(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/pump-api/promotion-gate.synthetic.json"),
    )
    .unwrap();
    let measurement = prepare_promotion_measurement(
        &run,
        "batch-pump-promotion-fixture",
        time("2026-08-17T12:00:01.000000Z"),
        500,
        "pump-promotion-writer",
    )
    .unwrap();
    assert_eq!(
        measurement.report.disposition,
        "promotable_continuous_direct_source"
    );
    assert_eq!(measurement.batch.store.evidence.observations.len(), 2);
    assert!(measurement.batch.store.evidence.assertions.is_empty());
    assert_eq!(
        measurement.report_bytes,
        serde_json::to_vec(&measurement.report).unwrap()
    );
    let precommit = measurement.spool_entry(None).unwrap();
    assert_eq!(precommit.closure.counts.acquisitions, 1);
    assert_eq!(precommit.closure.counts.observations, 2);
    let root = tempfile::tempdir().unwrap();
    let receipt = measurement.batch.commit(&mut store(root.path())).unwrap();
    let closed = measurement.close_receipt(&receipt).unwrap();
    assert_eq!(closed.contract, PUMP_MEASUREMENT_RECEIPT_CONTRACT);
    assert_eq!(closed.measurement_kind, "promotion_v1");
    assert_eq!(closed.committed_acquisition_ids.len(), 1);
    assert_eq!(receipt.admitted.observations, "2");
    assert_eq!(receipt.admitted.assertions, "0");
}
