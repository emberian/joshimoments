use joshi_domain::{BatchDigest, OpenVariant, SourceId, StableString, UtcTimestamp, ValueDigest};
use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch};
use joshi_spool::{EvidenceBatchEntry, ProtectionDomainId, SpoolConfig, SpoolEntry};
use joshi_supervisor::{
    AttemptKind, FaultInjector, FaultPoint, OperationKey, PendingSegment, ProtectionProfile,
    QueueClass, QueueLimits, ReservationRequest, RetryPolicy, SourceKey, Supervisor,
    SupervisorConfig, SupervisorError,
};
use std::{collections::BTreeMap, env, fs, path::PathBuf, sync::Arc, thread, time::Duration};

struct KillPause {
    target: FaultPoint,
    marker: PathBuf,
}

impl FaultInjector for KillPause {
    fn check(&self, point: FaultPoint) -> Result<(), SupervisorError> {
        if point == self.target {
            fs::write(&self.marker, format!("{point:?}")).unwrap();
            loop {
                thread::sleep(Duration::from_secs(1));
            }
        }
        Ok(())
    }
}

fn main() {
    let mut args = env::args().skip(1);
    let root = PathBuf::from(args.next().expect("collector root"));
    let phase = args.next().expect("kill phase");
    let at: UtcTimestamp = "2026-08-17T12:00:00.000000Z".parse().unwrap();
    let target = match phase.as_str() {
        "before_pre_io_reservation" => FaultPoint::BeforeAttemptReservation,
        "after_pre_io_reservation" => FaultPoint::AfterAttemptReservation,
        "before_origin_fsync" => FaultPoint::BeforeLocalSpoolAppend,
        "after_origin_fsync" => FaultPoint::AfterLocalSpoolAppend,
        other => panic!("unknown phase {other}"),
    };
    let mut supervisor = Supervisor::open_with_faults(
        config(&root),
        BTreeMap::new(),
        Arc::new(KillPause {
            target,
            marker: root.join("child-ready"),
        }),
    )
    .unwrap();
    supervisor.reconcile_startup(at).unwrap();
    let reservation = supervisor.reserve(request(at), at).unwrap();
    let item = PendingSegment::new(
        reservation,
        evidence_entry("kill-origin"),
        QueueClass::Evidence,
    )
    .unwrap();
    supervisor.try_enqueue(item).unwrap();
    supervisor.drain_one(at).unwrap().unwrap();
    panic!("kill child passed requested fault point {phase}");
}

fn config(root: &std::path::Path) -> SupervisorConfig {
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
        queue: QueueLimits::default(),
        retry: RetryPolicy::default(),
        shutdown_deadline: Duration::from_secs(2),
        maximum_spool_bytes_per_utc_day: 64 * 1024 * 1024,
    }
}

fn request(at: UtcTimestamp) -> ReservationRequest {
    ReservationRequest {
        source_key: SourceKey::new("kill-source").unwrap(),
        operation_key: OperationKey::new("kill-poll").unwrap(),
        kind: AttemptKind::Poll,
        scope: CoverageScope {
            source_id: SourceId::new("fixture.kill.v1").unwrap(),
            family: OpenVariant::known("kill_fixture").unwrap(),
            subject: None,
        },
        lower: Boundary::Wall { value: at },
        protection: ProtectionProfile::PublicIntegrity {
            domain: ProtectionDomainId::new("public-kill-fixture").unwrap(),
        },
        run: None,
        execution_claim: None,
        provider_plan: None,
    }
}

fn evidence_entry(name: &str) -> SpoolEntry {
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
    let admission = ValueDigest::new(format!("sha256:{:064x}", name.len())).unwrap();
    SpoolEntry::EvidenceBatch(
        EvidenceBatchEntry::from_batch(
            &batch,
            "joshi.store.policy.v1",
            br#"{"observationStorage":{},"coverageGapSeverity":{}}"#.to_vec(),
            Some(&admission),
        )
        .unwrap(),
    )
}
