mod support;

use joshi_domain::{BatchDigest, CommitSeq, OpenVariant, StableString, ValueDigest, WireU64};
use joshi_spool::{
    KeyMaterial, ProtectionDomainId, Replica, ReplicaConfig, ReplicaId, SegmentProtector,
};
use joshi_store::{AdmittedCounts, DurableReceipt, IdempotencyStatus};
use joshi_supervisor::{
    AttemptKind, CatalogSink, CatalogTransport, CollectorLifecycle, FakeProviderHarness,
    FakeProviderSchedule, FaultInjector, FaultPoint, PendingSegment, ProtectionProfile, QueueClass,
    ReplicaTransport, RetryDecision, RetryTrigger, Supervisor, SupervisorError, replay_spool,
};
use std::{
    collections::BTreeMap,
    fs,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tempfile::TempDir;

struct ArmableFault {
    point: FaultPoint,
    armed: AtomicBool,
}

impl ArmableFault {
    fn new(point: FaultPoint) -> Self {
        Self {
            point,
            armed: AtomicBool::new(false),
        }
    }

    fn arm(&self) {
        self.armed.store(true, Ordering::SeqCst);
    }
}

impl FaultInjector for ArmableFault {
    fn check(&self, point: FaultPoint) -> joshi_supervisor::Result<()> {
        if point == self.point && self.armed.swap(false, Ordering::SeqCst) {
            Err(SupervisorError::Injected(point))
        } else {
            Ok(())
        }
    }
}

#[test]
fn journal_and_spool_failpoints_recover_without_skip_or_duplicate_identity() {
    for point in [
        FaultPoint::AfterJournalTemporarySync,
        FaultPoint::AfterJournalRename,
    ] {
        let root = TempDir::new().unwrap();
        let fault = Arc::new(ArmableFault::new(point));
        let mut supervisor = Supervisor::open_with_faults(
            support::config(root.path()),
            BTreeMap::new(),
            fault.clone(),
        )
        .unwrap();
        fault.arm();
        assert!(matches!(
            supervisor.reserve(support::request(AttemptKind::Poll, "journal"), support::at()),
            Err(SupervisorError::Injected(actual)) if actual == point
        ));
        drop(supervisor);

        let mut recovered = Supervisor::open(support::config(root.path())).unwrap();
        let resolved = recovered.reconcile_startup(support::at()).unwrap();
        assert_eq!(resolved.len(), 1);
        let replay = replay_spool(recovered.spool(), &BTreeMap::new()).unwrap();
        assert_eq!(replay.control_entries, 1);
        assert_eq!(replay.evidence_batches, 0);
    }

    let root = TempDir::new().unwrap();
    let fault = Arc::new(ArmableFault::new(FaultPoint::AfterLocalSpoolAppend));
    let mut supervisor =
        Supervisor::open_with_faults(support::config(root.path()), BTreeMap::new(), fault.clone())
            .unwrap();
    let reservation = supervisor
        .reserve(support::request(AttemptKind::Poll, "spool"), support::at())
        .unwrap();
    supervisor
        .try_enqueue(
            PendingSegment::new(
                reservation,
                support::evidence_entry("failpoint-batch"),
                QueueClass::Evidence,
            )
            .unwrap(),
        )
        .unwrap();
    fault.arm();
    assert!(matches!(
        supervisor.drain_one(support::at()),
        Err(SupervisorError::Injected(FaultPoint::AfterLocalSpoolAppend))
    ));
    drop(supervisor);
    let mut recovered = Supervisor::open(support::config(root.path())).unwrap();
    recovered.reconcile_startup(support::at()).unwrap();
    let replay = replay_spool(recovered.spool(), &BTreeMap::new()).unwrap();
    assert_eq!(replay.evidence_batches, 1);
    assert_eq!(replay.control_entries, 0);
}

#[test]
fn health_write_failure_never_changes_evidence_progress() {
    let root = TempDir::new().unwrap();
    let fault = Arc::new(ArmableFault::new(FaultPoint::AfterHealthTemporarySync));
    let mut supervisor =
        Supervisor::open_with_faults(support::config(root.path()), BTreeMap::new(), fault.clone())
            .unwrap();
    fault.arm();
    assert!(matches!(
        supervisor.health(),
        Err(SupervisorError::Injected(
            FaultPoint::AfterHealthTemporarySync
        ))
    ));
    drop(supervisor);
    let mut reopened = Supervisor::open(support::config(root.path())).unwrap();
    assert_eq!(reopened.health().unwrap().ready_segments, 0);
}

#[test]
fn retry_is_deterministic_and_never_crosses_generation() {
    let root = TempDir::new().unwrap();
    let mut supervisor = Supervisor::open(support::config(root.path())).unwrap();
    let first = supervisor
        .reserve(
            support::request(AttemptKind::HttpRequest, "retry"),
            support::at(),
        )
        .unwrap();
    assert_eq!(
        supervisor
            .decide_retry(&first, RetryTrigger::Transport, None, support::at())
            .unwrap(),
        RetryDecision::Scheduled {
            after_ms: 10,
            next_attempt_ordinal: 2,
        }
    );
    supervisor
        .abandon(
            &first,
            OpenVariant::known("transport_failure").unwrap(),
            support::at(),
        )
        .unwrap();
    let second = supervisor.reserve_retry(&first, support::at()).unwrap();
    assert_eq!(second.generation, first.generation);
    assert_eq!(second.attempt_ordinal, 2);
    assert_eq!(
        supervisor
            .decide_retry(
                &second,
                RetryTrigger::RateLimited,
                Some(Duration::from_secs(2)),
                support::at(),
            )
            .unwrap(),
        RetryDecision::Exhausted
    );
}

#[test]
fn private_segments_are_sealed_before_replication_and_replay_needs_the_key() {
    let root = TempDir::new().unwrap();
    let key_id = "fixture-private-key";
    let protector =
        Arc::new(SegmentProtector::new(KeyMaterial::new(key_id, [7_u8; 32]).unwrap()).unwrap());
    let protectors = BTreeMap::from([(key_id.to_owned(), protector)]);
    let mut supervisor =
        Supervisor::open_with_protectors(support::config(root.path()), protectors.clone()).unwrap();
    let mut request = support::request(AttemptKind::Poll, "private");
    request.protection = ProtectionProfile::AuthenticatedPrivate {
        domain: ProtectionDomainId::new("private-fixture").unwrap(),
        key_id: key_id.into(),
    };
    let reservation = supervisor.reserve(request, support::at()).unwrap();
    supervisor
        .try_enqueue(
            PendingSegment::new(
                reservation,
                support::evidence_entry("private-batch"),
                QueueClass::Evidence,
            )
            .unwrap(),
        )
        .unwrap();
    supervisor.drain_one(support::at()).unwrap().unwrap();

    let opaque = replay_spool(supervisor.spool(), &BTreeMap::new()).unwrap();
    assert_eq!(opaque.opaque_private_segments, 1);
    assert_eq!(opaque.evidence_batches, 0);
    let opened = replay_spool(supervisor.spool(), &protectors).unwrap();
    assert_eq!(opened.opaque_private_segments, 0);
    assert_eq!(opened.evidence_batches, 1);

    let replica = Replica::open(ReplicaConfig {
        root: root.path().join("replica"),
        replica_id: ReplicaId::new("fixture-replica").unwrap(),
        generation: "generation-1".into(),
        max_segment_bytes: 1024 * 1024,
        max_chunk_bytes: 4096,
        max_total_bytes: 128 * 1024 * 1024,
    })
    .unwrap();
    let report = ReplicaTransport::new(supervisor.spool(), &replica)
        .drain()
        .unwrap();
    assert_eq!(report.remote_acks_recorded, 1);
    assert_eq!(supervisor.spool().list_segments().unwrap().len(), 1);
}

struct ExactFakeCatalog {
    calls: u64,
}

impl CatalogSink for ExactFakeCatalog {
    fn admit(
        &mut self,
        _segment: &joshi_spool::SegmentClosure,
        batch: &joshi_spool::EvidenceBatchEntry,
    ) -> std::result::Result<DurableReceipt, String> {
        self.calls = self.calls.saturating_add(1);
        Ok(DurableReceipt {
            contract: StableString::new("joshi.store.ingest_receipt").unwrap(),
            schema_version: 1,
            catalog_id: StableString::new("fixture-catalog").unwrap(),
            catalog_schema: StableString::new("fixture-schema").unwrap(),
            commit_seq: CommitSeq::new(4),
            from_commit_seq: CommitSeq::new(4),
            through_commit_seq: CommitSeq::new(4),
            batch_id: StableString::new(batch.closure.batch_id.clone()).unwrap(),
            batch_digest: BatchDigest::new(batch.closure.logical_digest.clone()).unwrap(),
            // The origin segment is sealed before store admission, so the postcommit receipt
            // supplies its independently-domain-separated admission digest.
            admission_digest: ValueDigest::new(
                "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            )
            .unwrap(),
            status: if self.calls == 1 {
                IdempotencyStatus::Accepted
            } else {
                IdempotencyStatus::Idempotent
            },
            admitted: AdmittedCounts {
                acquisitions: WireU64::new(0),
                raw_blobs: WireU64::new(0),
                raw_bytes: WireU64::new(0),
                observations: WireU64::new(0),
                source_events: WireU64::new(0),
                assertions: WireU64::new(0),
                coverage_windows: WireU64::new(0),
                coverage_gaps: WireU64::new(0),
                coverage_recoveries: WireU64::new(0),
                cursor_advances: WireU64::new(0),
            },
            acquisition_ids: Vec::new(),
            gap_outcomes: Vec::new(),
        })
    }
}

#[test]
fn exact_catalog_ack_is_retryable_and_never_releases_segment_retention() {
    let root = TempDir::new().unwrap();
    let mut supervisor = Supervisor::open(support::config(root.path())).unwrap();
    let reservation = supervisor
        .reserve(
            support::request(AttemptKind::Poll, "catalog"),
            support::at(),
        )
        .unwrap();
    supervisor
        .try_enqueue(
            PendingSegment::new(
                reservation,
                support::evidence_entry("catalog-batch"),
                QueueClass::Evidence,
            )
            .unwrap(),
        )
        .unwrap();
    supervisor.drain_one(support::at()).unwrap().unwrap();
    let mut catalog = ExactFakeCatalog { calls: 0 };
    let protectors = BTreeMap::new();
    let transport = CatalogTransport::new(supervisor.spool(), &protectors);
    assert_eq!(
        transport.drain(&mut catalog).unwrap().catalog_acks_recorded,
        1
    );
    assert_eq!(
        transport.drain(&mut catalog).unwrap().catalog_acks_recorded,
        1
    );
    assert_eq!(catalog.calls, 2);
    assert_eq!(supervisor.spool().list_segments().unwrap().len(), 1);
    assert_eq!(supervisor.health().unwrap().catalog_ack_files, 1);
}

#[test]
fn corruption_is_quarantined_and_never_skipped_by_replay() {
    let root = TempDir::new().unwrap();
    let mut supervisor = Supervisor::open(support::config(root.path())).unwrap();
    let reservation = supervisor
        .reserve(
            support::request(AttemptKind::Poll, "corrupt"),
            support::at(),
        )
        .unwrap();
    supervisor
        .try_enqueue(
            PendingSegment::new(
                reservation,
                support::evidence_entry("corrupt-batch"),
                QueueClass::Evidence,
            )
            .unwrap(),
        )
        .unwrap();
    supervisor.drain_one(support::at()).unwrap().unwrap();
    let ready = fs::read_dir(root.path().join("spool/ready"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let mut bytes = fs::read(&ready).unwrap();
    bytes[0] ^= 1;
    fs::write(&ready, bytes).unwrap();
    assert!(replay_spool(supervisor.spool(), &BTreeMap::new()).is_err());
    assert!(
        fs::read_dir(root.path().join("spool/quarantine"))
            .unwrap()
            .next()
            .is_some()
    );
}

#[test]
fn accelerated_24h_run_is_bounded_replayable_and_has_no_false_cursor() {
    let schedule: FakeProviderSchedule = serde_json::from_str(include_str!(
        "../../../fixtures/supervisor/fake_provider_24h.json"
    ))
    .unwrap();
    let root = TempDir::new().unwrap();
    let mut supervisor = Supervisor::open(support::config(root.path())).unwrap();
    supervisor.reconcile_startup(support::at()).unwrap();
    let report = FakeProviderHarness::new(schedule)
        .unwrap()
        .run(&mut supervisor, support::at())
        .unwrap();
    assert_eq!(report.virtual_duration_seconds, 86_400);
    assert_eq!(report.frames_durable, 24);
    assert!(report.duplicate_frames > 0);
    assert!(report.retry_decisions > 0);
    assert!(report.explicit_attempt_gaps > 0);
    assert_eq!(report.false_cursor_advances, 0);
    assert!(!report.shutdown.deadline_exceeded);
    let first = replay_spool(supervisor.spool(), &BTreeMap::new()).unwrap();
    let second = replay_spool(supervisor.spool(), &BTreeMap::new()).unwrap();
    assert_eq!(first, second);
    assert_eq!(first.ordered_closure_digest, report.final_replay_digest);
    assert_eq!(
        supervisor.health().unwrap().lifecycle,
        CollectorLifecycle::Stopped
    );
}

#[test]
fn daily_budget_and_queue_saturation_stop_with_durable_control_gaps() {
    let budget_root = TempDir::new().unwrap();
    let mut budget_config = support::config(budget_root.path());
    budget_config.maximum_spool_bytes_per_utc_day = 1;
    let mut budgeted = Supervisor::open(budget_config).unwrap();
    let reservation = budgeted
        .reserve(
            support::request(AttemptKind::HttpRequest, "daily-budget"),
            support::at(),
        )
        .unwrap();
    budgeted
        .try_enqueue(
            PendingSegment::new(
                reservation,
                support::evidence_entry("daily-budget-batch"),
                QueueClass::Evidence,
            )
            .unwrap(),
        )
        .unwrap();
    assert!(matches!(
        budgeted.drain_one(support::at()),
        Err(SupervisorError::DailySpoolBudget { .. })
    ));
    let pressure = budgeted
        .stop_front_for_pressure(
            OpenVariant::known("spool_budget_pressure").unwrap(),
            support::at(),
        )
        .unwrap();
    pressure.validate().unwrap();
    let replay = replay_spool(budgeted.spool(), &BTreeMap::new()).unwrap();
    assert_eq!(replay.evidence_batches, 0);
    assert_eq!(replay.control_entries, 1);

    let queue_root = TempDir::new().unwrap();
    let mut queue_config = support::config(queue_root.path());
    queue_config.queue.maximum_records = 3;
    queue_config.queue.control_reserve_records = 1;
    let mut bounded = Supervisor::open(queue_config).unwrap();
    let mut rejected = None;
    for index in 0..3 {
        let reservation = bounded
            .reserve(
                support::request(AttemptKind::HttpRequest, "queue-bound"),
                support::at(),
            )
            .unwrap();
        let item = PendingSegment::new(
            reservation,
            support::evidence_entry(&format!("queue-batch-{index}")),
            QueueClass::Evidence,
        )
        .unwrap();
        if let Err(item) = bounded.try_enqueue(item) {
            rejected = Some(item);
        }
    }
    let saturation = bounded
        .stop_saturated(
            rejected.expect("third evidence record must preserve exact ownership"),
            support::at(),
        )
        .unwrap();
    saturation.validate().unwrap();
    let health = bounded.health().unwrap();
    assert_eq!(health.queue_records, 2);
    assert_eq!(health.saturation_stops, 1);
    assert_eq!(health.ready_segments, 1);
}
