use joshi_admission::{
    CompanionReceiptV1, PublicAdmittedCounts, PublicBoundary, PublicCoverageScope,
    PublicGapOutcome, PublicStatus, PublicStoreReceiptV1, Sha256Digest, admit_companion,
    parse_companion, strict_json,
};
use joshi_domain::{OpenVariant, StableString, UtcTimestamp};
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use std::{path::Path, time::Duration};

const COMPANION_GOLDEN: &[u8] =
    include_bytes!("../../../apps/core/fixtures/companion_ingress_v1.json");
const WALKING_MATERIAL: &str =
    include_str!("../../../apps/core/fixtures/companion_walking_material_v1.json");
const GAP_RECEIPT_GOLDEN: &str =
    include_str!("../../../apps/core/fixtures/store_receipt_gap_v1.json");

fn time(value: &str) -> UtcTimestamp {
    value.parse().expect("valid time")
}
fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable")
}
fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 1024,
        busy_timeout: Duration::from_secs(1),
        catalog_id: stable("catalog-golden"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 1024 * 1024,
    }
}

#[test]
fn companion_ingress_golden_separates_all_three_digests_and_retries_idempotently() {
    let parsed = parse_companion(COMPANION_GOLDEN).expect("strict source ingress");
    assert_eq!(
        parsed.ingress_digest().as_str(),
        "sha256:f585b52da69d89bc5ab7a8e88f7c0ecc6486b572edbd85d0b1816c3b5d60ae2e"
    );
    let admission = admit_companion(
        parsed,
        time("2026-08-16T18:42:18.123456Z"),
        41,
        "test-monotonic",
    )
    .expect("adapter");
    assert_ne!(
        admission.parsed.ingress_digest().as_str(),
        admission.batch.store.evidence.expected_digest.as_str()
    );
    let root = tempfile::tempdir().expect("tempdir");
    let mut store = SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("store");
    store
        .migrate(time("2026-08-16T18:42:18.123456Z"))
        .expect("migrate");
    let accepted = admission.batch.commit(&mut store).expect("commit");
    assert_ne!(accepted.batch_digest, accepted.store_admission_digest);
    let companion = CompanionReceiptV1::from_committed(&admission, &accepted).expect("receipt");
    assert_eq!(companion.status, PublicStatus::Accepted);
    let retried = admission.batch.commit(&mut store).expect("retry");
    let companion_retry =
        CompanionReceiptV1::from_committed(&admission, &retried).expect("retry receipt");
    assert_eq!(companion_retry.status, PublicStatus::Idempotent);
    assert_eq!(
        companion.durable_batch_digest,
        companion_retry.durable_batch_digest
    );
    assert_eq!(
        companion.store_admission_digest,
        companion_retry.store_admission_digest
    );
}

#[test]
fn strict_json_rejects_duplicate_dangerous_unknown_and_oversized_inputs() {
    assert!(strict_json::parse::<serde_json::Value>(br#"{"a":1,"a":2}"#, 100).is_err());
    assert!(
        strict_json::parse::<serde_json::Value>(br#"{"nested":{"__proto__":{}}}"#, 100).is_err()
    );
    assert!(strict_json::parse::<CompanionReceiptV1>(br#"{"unknown":true}"#, 100).is_err());
    assert!(strict_json::parse::<serde_json::Value>(br#"{"a":1}"#, 2).is_err());
}

#[test]
fn public_receipt_is_recursively_camel_case_for_a_nonempty_scoped_gap() {
    let receipt = PublicStoreReceiptV1 {
        contract: "joshi.store.ingest_receipt".into(),
        schema_version: 1,
        catalog_id: "catalog-golden".into(),
        catalog_schema: "joshi.sqlite.v7".into(),
        commit_seq: "14".into(),
        batch_id: "batch-1".into(),
        batch_digest: Sha256Digest::parse(format!("sha256:{}", "a".repeat(64))).unwrap(),
        store_admission_digest: Sha256Digest::parse(format!("sha256:{}", "b".repeat(64))).unwrap(),
        status: PublicStatus::Accepted,
        from_commit_seq: "14".into(),
        through_commit_seq: "14".into(),
        admitted: PublicAdmittedCounts {
            acquisitions: "0".into(),
            raw_blobs: "0".into(),
            raw_bytes: "0".into(),
            observations: "0".into(),
            source_events: "0".into(),
            assertions: "0".into(),
            coverage_windows: "1".into(),
            coverage_gaps: "1".into(),
            coverage_recoveries: "0".into(),
            cursor_advances: "0".into(),
        },
        acquisition_ids: vec![],
        gap_outcomes: vec![PublicGapOutcome {
            gap_id: "gap-1".into(),
            scope: PublicCoverageScope {
                source_id: "source-1".into(),
                family: OpenVariant::known("hot_lane").unwrap(),
                subject: Some("coin-a".into()),
            },
            lower: PublicBoundary::SourceCursor { value: "7".into() },
            upper: Some(PublicBoundary::Unknown {
                reason: OpenVariant::known("disconnect").unwrap(),
            }),
            outcome: "recorded".into(),
        }],
    };
    let encoded = serde_json::to_string(&receipt).expect("receipt JSON");
    assert_eq!(encoded, GAP_RECEIPT_GOLDEN.trim_end());
    assert!(encoded.contains(r#""sourceId":"source-1""#));
    assert!(!encoded.contains("source_id"));
    let decoded: PublicStoreReceiptV1 =
        strict_json::parse(encoded.as_bytes(), 64 * 1024).expect("strict roundtrip");
    assert_eq!(decoded, receipt);
}

#[test]
fn companion_missing_monotonic_and_point_validity_are_never_fabricated() {
    let material = WALKING_MATERIAL.trim_end();
    let digest = Sha256Digest::of_bytes(material.as_bytes());
    let request = material.replacen(
        "\"producer\"",
        &format!("\"batchDigest\":\"{digest}\",\"producer\""),
        1,
    );
    let parsed = parse_companion(request.as_bytes()).expect("walking ingress");
    let committed_at = time("2026-08-16T18:43:00.000000Z");
    let admission =
        admit_companion(parsed, committed_at, 99, "core-ingress-clock").expect("admission");
    let observation = &admission.batch.store.evidence.observations[0];
    assert_eq!(observation.acquisition.started_monotonic, None);
    assert_eq!(observation.acquisition.clocks.monotonic_elapsed_ns, None);
    assert_eq!(observation.acquisition.clocks.monotonic_domain, None);
    assert_eq!(observation.observation.timing.received_at, committed_at);
    assert_eq!(
        observation
            .observation
            .timing
            .received_monotonic
            .nanoseconds
            .get(),
        99
    );
    let assertion = &admission.batch.store.evidence.assertions[0];
    assert_eq!(
        assertion.assertion_kind.discriminator.as_str(),
        "companion_capture_snapshot_attestation"
    );
    assert!(
        assertion
            .semantic_key
            .as_str()
            .starts_with("companion.capture_snapshot:")
    );
    assert_eq!(assertion.valid_time.status.discriminator.as_str(), "exact");
    assert_eq!(
        assertion.valid_time.lower.unwrap().to_string(),
        "2026-08-16T18:42:18.123000Z"
    );
    assert_eq!(
        assertion.valid_time.upper.unwrap().to_string(),
        "2026-08-16T18:42:18.124000Z"
    );
    let at_capture = time("2026-08-16T18:42:18.123000Z");
    let before_capture = time("2026-08-16T18:42:18.122999Z");
    let at_exclusive_upper = time("2026-08-16T18:42:18.124000Z");
    let lower = assertion.valid_time.lower.unwrap();
    let upper = assertion.valid_time.upper.unwrap();
    assert!(at_capture >= lower && at_capture < upper);
    assert!(!(before_capture >= lower && before_capture < upper));
    assert!(!(at_exclusive_upper >= lower && at_exclusive_upper < upper));
}
