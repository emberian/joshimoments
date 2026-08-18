#![allow(dead_code)]

use joshi_domain::{BatchDigest, OpenVariant, SourceId, StableString, UtcTimestamp};
use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch};
use joshi_spool::{EvidenceBatchEntry, ProtectionDomainId, SpoolConfig, SpoolEntry};
use joshi_supervisor::{
    AttemptKind, OperationKey, ProtectionProfile, QueueLimits, ReservationRequest, RetryPolicy,
    SourceKey, SupervisorConfig,
};
use std::{path::Path, time::Duration};

pub fn at() -> UtcTimestamp {
    "2026-08-17T12:00:00.000000Z".parse().unwrap()
}

pub fn config(root: &Path) -> SupervisorConfig {
    SupervisorConfig {
        root: root.to_path_buf(),
        spool: SpoolConfig {
            root: root.join("spool"),
            max_segment_bytes: 1024 * 1024,
            max_entries_per_segment: 32,
            max_total_bytes: 128 * 1024 * 1024,
            control_reserve_bytes: 1024 * 1024,
            max_transfer_chunk_bytes: 4096,
        },
        queue: QueueLimits {
            maximum_records: 6,
            maximum_bytes: 1024 * 1024,
            control_reserve_records: 2,
            control_reserve_bytes: 64 * 1024,
        },
        retry: RetryPolicy {
            maximum_attempts_per_generation: 3,
            base_delay: Duration::from_millis(10),
            maximum_delay: Duration::from_secs(1),
        },
        shutdown_deadline: Duration::from_secs(2),
        maximum_spool_bytes_per_utc_day: 64 * 1024 * 1024,
    }
}

pub fn request(kind: AttemptKind, operation: &str) -> ReservationRequest {
    ReservationRequest {
        source_key: SourceKey::new("fixture-source").unwrap(),
        operation_key: OperationKey::new(operation).unwrap(),
        kind,
        scope: CoverageScope {
            source_id: SourceId::new("fixture.source.v1").unwrap(),
            family: OpenVariant::known("fixture").unwrap(),
            subject: Some(StableString::new("bounded-subject").unwrap()),
        },
        lower: Boundary::Wall { value: at() },
        protection: ProtectionProfile::PublicIntegrity {
            domain: ProtectionDomainId::new("public-fixture").unwrap(),
        },
        run: None,
        execution_claim: None,
        provider_plan: None,
    }
}

pub fn evidence_entry(name: &str) -> SpoolEntry {
    let mut batch = DurableIngestBatch {
        contract_version: StableString::new(joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION)
            .unwrap(),
        batch_id: StableString::new(name).unwrap(),
        expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64))).unwrap(),
        observations: Vec::new(),
        source_events: Vec::new(),
        assertions: Vec::new(),
        coverage_windows: Vec::new(),
        coverage_gaps: Vec::new(),
        coverage_recoveries: Vec::new(),
        cursor_advances: Vec::new(),
    };
    batch.expected_digest = joshi_store::SqliteStore::canonical_batch_digest(&batch).unwrap();
    SpoolEntry::EvidenceBatch(
        EvidenceBatchEntry::from_batch(
            &batch,
            "joshi.store.policy.v1",
            br#"{"observationStorage":{},"coverageGapSeverity":{}}"#.to_vec(),
            None,
        )
        .unwrap(),
    )
}
