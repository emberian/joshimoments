use joshi_domain::{
    BatchDigest, CommitSeq, OpenVariant, SourceId, StableString, UtcTimestamp, ValueDigest, WireU64,
};
use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch};
use joshi_spool::{
    AppendOutcome, ByteClosure, FaultInjector, FaultPoint, GapRecord, KeyMaterial, LocalSpool,
    ProtectionDomainId, ProtectionMetadata, ProtectionRequest, Replica, ReplicaConfig, ReplicaId,
    ResumeState, SegmentClosure, SegmentId, SegmentProtector, SpoolConfig, SpoolEntry, SpoolError,
    TransferChunk, decode_segment, encode_segment, inspect_segment,
};
use joshi_store::{AdmittedCounts, DurableReceipt, IdempotencyStatus};
use serde::Deserialize;
use std::{
    collections::BTreeSet,
    fs,
    str::FromStr,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use tempfile::TempDir;

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("test stable string")
}

fn time() -> UtcTimestamp {
    UtcTimestamp::from_str("2026-08-16T12:00:00.000000Z").expect("test time")
}

fn domain(name: &str) -> ProtectionDomainId {
    ProtectionDomainId::new(name).expect("test domain")
}

fn segment_id(name: &str) -> SegmentId {
    SegmentId::new(name).expect("test segment id")
}

fn empty_batch(name: &str) -> DurableIngestBatch {
    let mut batch = DurableIngestBatch {
        contract_version: stable(joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION),
        batch_id: stable(name),
        expected_digest: BatchDigest::new("sha256:pending").expect("placeholder digest"),
        observations: Vec::new(),
        source_events: Vec::new(),
        assertions: Vec::new(),
        coverage_windows: Vec::new(),
        coverage_gaps: Vec::new(),
        coverage_recoveries: Vec::new(),
        cursor_advances: Vec::new(),
    };
    batch.expected_digest =
        joshi_store::SqliteStore::canonical_batch_digest(&batch).expect("canonical digest");
    batch
}

fn evidence_entry(name: &str) -> SpoolEntry {
    let batch = empty_batch(name);
    SpoolEntry::EvidenceBatch(
        joshi_spool::EvidenceBatchEntry::from_batch(
            &batch,
            "joshi.store.policy.v1",
            br#"{"observationStorage":{},"coverageGapSeverity":{}}"#.to_vec(),
            None,
        )
        .expect("evidence entry"),
    )
}

fn gap_entry(name: &str) -> SpoolEntry {
    SpoolEntry::Gap(GapRecord {
        gap_id: name.into(),
        scope: CoverageScope {
            source_id: SourceId::new("test-source").expect("source id"),
            family: OpenVariant::known("replication").expect("variant"),
            subject: Some(stable("fixture")),
        },
        lower: Boundary::SourceCursor {
            value: stable("before"),
        },
        upper: None,
        reason: OpenVariant::known("disk_pressure").expect("variant"),
        detected_at: time(),
        related_segment_id: None,
    })
}

fn public_segment(name: &str, entry: SpoolEntry) -> (Vec<u8>, SegmentClosure) {
    encode_segment(
        segment_id(name),
        time(),
        &[entry],
        &ProtectionRequest::Public {
            domain: domain("public-fixture"),
        },
        None,
    )
    .expect("encode public segment")
}

fn spool_config(root: &TempDir, max_total_bytes: u64, reserve: u64) -> SpoolConfig {
    SpoolConfig {
        root: root.path().join("local"),
        max_segment_bytes: 1_000_000,
        max_entries_per_segment: 32,
        max_total_bytes,
        control_reserve_bytes: reserve,
        max_transfer_chunk_bytes: 16_384,
    }
}

fn replica_config(root: &TempDir) -> ReplicaConfig {
    ReplicaConfig {
        root: root.path().join("replica"),
        replica_id: ReplicaId::new("fixture-replica").expect("replica id"),
        generation: "generation-1".into(),
        max_segment_bytes: 1_000_000,
        max_chunk_bytes: 16_384,
        max_total_bytes: 10_000_000,
    }
}

#[test]
fn equal_body_content_in_distinct_segment_occurrences_stays_distinct() {
    let root = TempDir::new().expect("temp root");
    let spool = LocalSpool::open(spool_config(&root, 10_000_000, 100_000)).expect("open spool");
    let entry = evidence_entry("batch-equal");
    let (first, first_closure) = public_segment("segment-occurrence-a", entry.clone());
    let (second, second_closure) = public_segment("segment-occurrence-b", entry);

    assert_ne!(first_closure.segment_id, second_closure.segment_id);
    assert_ne!(
        first_closure.exact_segment.digest,
        second_closure.exact_segment.digest
    );
    assert_eq!(
        spool
            .append_segment(&first, &first_closure)
            .expect("append first"),
        AppendOutcome::Appended
    );
    assert_eq!(
        spool
            .append_segment(&second, &second_closure)
            .expect("append second"),
        AppendOutcome::Appended
    );
    assert_eq!(spool.list_segments().expect("list").len(), 2);
}

#[test]
fn authenticated_private_segments_bind_ciphertext_and_reject_tampering() {
    let material = KeyMaterial::new("fixture-key", [7_u8; 32]).expect("key material");
    let protector = SegmentProtector::new(material).expect("protector");
    let private_domain = domain("private-social");
    let (bytes, closure) = encode_segment(
        segment_id("private-segment"),
        time(),
        &[evidence_entry("private-batch")],
        &ProtectionRequest::AuthenticatedPrivate {
            domain: private_domain,
            key_id: "fixture-key".into(),
            nonce: [3_u8; 12],
        },
        Some(&protector),
    )
    .expect("encode private");
    assert_eq!(
        decode_segment(&bytes, Some(&protector))
            .expect("decode")
            .len(),
        1
    );
    assert_eq!(closure.exact_segment, ByteClosure::of(&bytes));

    let mut envelope = inspect_segment(&bytes).expect("inspect");
    envelope.sealed_body_bytes[0] ^= 0x40;
    envelope.header.sealed_body = ByteClosure::of(&envelope.sealed_body_bytes);
    let tampered = serde_json::to_vec(&envelope).expect("tampered envelope");
    assert!(matches!(
        decode_segment(&tampered, Some(&protector)),
        Err(SpoolError::Authentication)
    ));
}

#[test]
fn nonce_reuse_is_refused_in_process_and_across_spool_restart() {
    let key = [9_u8; 32];
    let private_domain = domain("private-wallet");
    let protector =
        SegmentProtector::new(KeyMaterial::new("key-9", key).expect("key")).expect("protector");
    let request = ProtectionRequest::AuthenticatedPrivate {
        domain: private_domain.clone(),
        key_id: "key-9".into(),
        nonce: [8_u8; 12],
    };
    let (first, first_closure) = encode_segment(
        segment_id("nonce-a"),
        time(),
        &[evidence_entry("nonce-batch-a")],
        &request,
        Some(&protector),
    )
    .expect("first seal");
    assert!(matches!(
        encode_segment(
            segment_id("nonce-b"),
            time(),
            &[evidence_entry("nonce-batch-b")],
            &request,
            Some(&protector)
        ),
        Err(SpoolError::NonceReuse { .. })
    ));

    let root = TempDir::new().expect("temp root");
    let config = spool_config(&root, 10_000_000, 100_000);
    LocalSpool::open(config.clone())
        .expect("spool")
        .append_segment(&first, &first_closure)
        .expect("append first");
    let restarted_protector =
        SegmentProtector::new(KeyMaterial::new("key-9", key).expect("key")).expect("protector");
    let (second, second_closure) = encode_segment(
        segment_id("nonce-c"),
        time(),
        &[evidence_entry("nonce-batch-c")],
        &request,
        Some(&restarted_protector),
    )
    .expect("seal after restart");
    assert!(matches!(
        LocalSpool::open(config)
            .expect("reopen")
            .append_segment(&second, &second_closure),
        Err(SpoolError::NonceReuse { .. })
    ));
}

struct FailOnce {
    point: FaultPoint,
    armed: AtomicBool,
}

impl FailOnce {
    fn at(point: FaultPoint) -> Self {
        Self {
            point,
            armed: AtomicBool::new(true),
        }
    }
}

impl FaultInjector for FailOnce {
    fn check(&self, point: FaultPoint) -> joshi_spool::Result<()> {
        if point == self.point && self.armed.swap(false, Ordering::SeqCst) {
            Err(SpoolError::Injected(point))
        } else {
            Ok(())
        }
    }
}

#[test]
fn atomic_append_recovers_both_pre_and_post_rename_failures() {
    for point in [FaultPoint::AfterTemporarySync, FaultPoint::AfterReadyRename] {
        let root = TempDir::new().expect("temp root");
        let config = spool_config(&root, 10_000_000, 100_000);
        let faults = Arc::new(FailOnce::at(point));
        let spool = LocalSpool::open_with_faults(config.clone(), faults).expect("open");
        let (bytes, closure) = public_segment("atomic-segment", evidence_entry("atomic-batch"));
        assert!(matches!(
            spool.append_segment(&bytes, &closure),
            Err(SpoolError::Injected(actual)) if actual == point
        ));
        let reopened = LocalSpool::open(config).expect("reopen");
        let outcome = reopened
            .append_segment(&bytes, &closure)
            .expect("recover append");
        assert!(matches!(
            outcome,
            AppendOutcome::Appended | AppendOutcome::Idempotent
        ));
        assert_eq!(reopened.read_segment(&closure).expect("read"), bytes);
    }
}

#[test]
fn identity_retry_is_idempotent_and_changed_bytes_conflict() {
    let root = TempDir::new().expect("temp root");
    let spool = LocalSpool::open(spool_config(&root, 10_000_000, 100_000)).expect("open");
    let (first, closure) = public_segment("same-id", evidence_entry("batch-a"));
    let (changed, changed_closure) = public_segment("same-id", evidence_entry("batch-b"));
    assert_eq!(
        spool.append_segment(&first, &closure).expect("first"),
        AppendOutcome::Appended
    );
    assert_eq!(
        spool.append_segment(&first, &closure).expect("retry"),
        AppendOutcome::Idempotent
    );
    assert!(matches!(
        spool.append_segment(&changed, &changed_closure),
        Err(SpoolError::IdentityConflict(_))
    ));
}

#[test]
fn disk_budget_preserves_control_record_reserve() {
    let (evidence, evidence_closure) =
        public_segment("budget-evidence", evidence_entry("budget-batch"));
    let (control, control_closure) = public_segment("budget-gap", gap_entry("budget-gap-record"));
    let reserve = u64::try_from(control.len()).expect("control length") + 128;
    let maximum = u64::try_from(evidence.len()).expect("evidence length") + reserve;
    let root = TempDir::new().expect("temp root");
    let spool = LocalSpool::open(spool_config(&root, maximum, reserve)).expect("open");
    spool
        .append_segment(&evidence, &evidence_closure)
        .expect("first evidence exactly fills data budget");
    let (second, second_closure) =
        public_segment("budget-evidence-2", evidence_entry("budget-batch-2"));
    assert!(matches!(
        spool.append_segment(&second, &second_closure),
        Err(SpoolError::Degraded(_))
    ));
    spool
        .append_segment(&control, &control_closure)
        .expect("control record uses reserve");
    assert!(spool.status().expect("status").degraded);
}

#[test]
fn corruption_is_quarantined_instead_of_skipped() {
    let root = TempDir::new().expect("temp root");
    let config = spool_config(&root, 10_000_000, 100_000);
    let spool = LocalSpool::open(config.clone()).expect("open");
    let (bytes, closure) = public_segment("corrupt-me", evidence_entry("corrupt-batch"));
    spool.append_segment(&bytes, &closure).expect("append");
    let ready = fs::read_dir(config.root.join("ready"))
        .expect("ready directory")
        .next()
        .expect("ready file")
        .expect("entry")
        .path();
    let mut corrupted = fs::read(&ready).expect("read");
    corrupted[0] ^= 1;
    fs::write(&ready, corrupted).expect("corrupt fixture");
    assert!(spool.list_segments().is_err());
    assert!(
        fs::read_dir(config.root.join("quarantine"))
            .expect("quarantine")
            .count()
            >= 2
    );
}

#[test]
fn replica_does_not_trust_a_historical_ack_after_ready_bytes_corrupt() {
    let root = TempDir::new().expect("temp root");
    let config = replica_config(&root);
    let replica = Replica::open(config.clone()).expect("replica");
    let (bytes, closure) =
        public_segment("replica-corrupt", evidence_entry("replica-corrupt-batch"));
    replica
        .apply_chunk(&TransferChunk {
            closure: closure.clone(),
            offset: 0,
            bytes,
        })
        .expect("transfer")
        .expect("ack");
    let ready = fs::read_dir(config.root.join("ready"))
        .expect("ready")
        .next()
        .expect("ready file")
        .expect("entry")
        .path();
    let mut corrupt = fs::read(&ready).expect("read ready");
    corrupt[0] ^= 1;
    fs::write(&ready, corrupt).expect("corrupt ready");
    assert!(replica.resume_state(&closure).is_err());
    assert!(
        fs::read_dir(config.root.join("quarantine"))
            .expect("quarantine")
            .next()
            .is_some()
    );
}

#[test]
fn partial_retry_restart_and_crash_after_ready_rename_are_resumable() {
    let root = TempDir::new().expect("temp root");
    let config = replica_config(&root);
    let (bytes, closure) = public_segment("replicate-me", evidence_entry("replicate-batch"));
    let split = bytes.len() / 2;
    let partial_fault = Arc::new(FailOnce::at(FaultPoint::AfterPartialSync));
    let replica = Replica::open_with_faults(config.clone(), partial_fault).expect("open replica");
    assert!(matches!(
        replica.apply_chunk(&TransferChunk {
            closure: closure.clone(),
            offset: 0,
            bytes: bytes[..split].to_vec(),
        }),
        Err(SpoolError::Injected(FaultPoint::AfterPartialSync))
    ));
    let after_restart = Replica::open(config.clone()).expect("restart");
    assert_eq!(
        after_restart.resume_state(&closure).expect("resume"),
        ResumeState::Partial {
            durable_bytes: u64::try_from(split).expect("split")
        }
    );
    after_restart
        .apply_chunk(&TransferChunk {
            closure: closure.clone(),
            offset: u64::try_from(split / 2).expect("overlap"),
            bytes: bytes[split / 2..split].to_vec(),
        })
        .expect("duplicate overlap");

    let ready_fault = Arc::new(FailOnce::at(FaultPoint::AfterReplicaReadyRename));
    let replica =
        Replica::open_with_faults(config.clone(), ready_fault).expect("reopen with fault");
    assert!(matches!(
        replica.apply_chunk(&TransferChunk {
            closure: closure.clone(),
            offset: u64::try_from(split).expect("split"),
            bytes: bytes[split..].to_vec(),
        }),
        Err(SpoolError::Injected(FaultPoint::AfterReplicaReadyRename))
    ));
    let recovered = Replica::open(config).expect("final restart");
    assert!(matches!(
        recovered.resume_state(&closure).expect("durable resume"),
        ResumeState::Durable(_)
    ));
}

#[test]
fn crash_after_ack_temp_sync_recovers_without_manufacturing_a_second_receipt() {
    let root = TempDir::new().expect("temp root");
    let config = replica_config(&root);
    let (bytes, closure) = public_segment("ack-crash", evidence_entry("ack-crash-batch"));
    let faults = Arc::new(FailOnce::at(FaultPoint::AfterAckTemporarySync));
    let replica = Replica::open_with_faults(config.clone(), faults).expect("open replica");
    assert!(matches!(
        replica.apply_chunk(&TransferChunk {
            closure: closure.clone(),
            offset: 0,
            bytes,
        }),
        Err(SpoolError::Injected(FaultPoint::AfterAckTemporarySync))
    ));

    let recovered = Replica::open(config).expect("restart");
    let first = recovered.resume_state(&closure).expect("recover ack");
    let second = recovered.resume_state(&closure).expect("idempotent ack");
    assert!(matches!(first, ResumeState::Durable(_)));
    assert_eq!(first, second);
}

#[test]
fn forward_chunk_gap_and_mismatched_overlap_are_refused() {
    let root = TempDir::new().expect("temp root");
    let replica = Replica::open(replica_config(&root)).expect("open");
    let (bytes, closure) = public_segment("offsets", evidence_entry("offset-batch"));
    assert!(matches!(
        replica.apply_chunk(&TransferChunk {
            closure: closure.clone(),
            offset: 1,
            bytes: bytes[1..20].to_vec(),
        }),
        Err(SpoolError::TransferOffset { .. })
    ));
    replica
        .apply_chunk(&TransferChunk {
            closure: closure.clone(),
            offset: 0,
            bytes: bytes[..40].to_vec(),
        })
        .expect("first partial");
    let mut mismatch = bytes[20..50].to_vec();
    mismatch[0] ^= 1;
    assert!(matches!(
        replica.apply_chunk(&TransferChunk {
            closure,
            offset: 20,
            bytes: mismatch,
        }),
        Err(SpoolError::Integrity(_))
    ));
}

#[test]
fn remote_ack_is_only_ciphertext_durability_and_never_deletes_local_bytes() {
    let root = TempDir::new().expect("temp root");
    let local_config = spool_config(&root, 10_000_000, 100_000);
    let local = LocalSpool::open(local_config).expect("local");
    let replica = Replica::open(replica_config(&root)).expect("replica");
    let (bytes, closure) = public_segment("ack-boundary", evidence_entry("ack-batch"));
    local
        .append_segment(&bytes, &closure)
        .expect("append local");
    let outbound = local
        .read_transfer_chunk(&closure, 0)
        .expect("bounded outbound chunk");
    let ack = replica
        .apply_chunk(&outbound)
        .expect("transfer")
        .expect("durable ack");
    local.record_remote_ack(&ack).expect("record ack");
    assert_eq!(local.read_segment(&closure).expect("still local"), bytes);
    let ack_json = serde_json::to_value(ack).expect("ack json");
    assert!(ack_json.get("commitSeq").is_none());
    assert!(ack_json.get("cursor").is_none());
    assert!(ack_json.get("catalogId").is_none());
}

#[test]
fn exact_catalog_receipt_is_separate_and_mismatch_is_refused() {
    let root = TempDir::new().expect("temp root");
    let local = LocalSpool::open(spool_config(&root, 10_000_000, 100_000)).expect("local");
    let entry = evidence_entry("catalog-batch");
    let SpoolEntry::EvidenceBatch(batch_entry) = &entry else {
        panic!("expected batch");
    };
    let batch_entry = batch_entry.clone();
    let (bytes, closure) = public_segment("catalog-segment", entry);
    local.append_segment(&bytes, &closure).expect("append");
    let receipt = DurableReceipt {
        contract: stable("joshi.store.ingest_receipt"),
        schema_version: 1,
        catalog_id: stable("catalog-fixture"),
        catalog_schema: stable("schema-fixture"),
        commit_seq: CommitSeq::new(4),
        from_commit_seq: CommitSeq::new(4),
        through_commit_seq: CommitSeq::new(4),
        batch_id: stable(&batch_entry.closure.batch_id),
        batch_digest: BatchDigest::new(&batch_entry.closure.logical_digest).expect("digest"),
        admission_digest: ValueDigest::new(format!("sha256:{}", "a".repeat(64)))
            .expect("admission"),
        status: IdempotencyStatus::Accepted,
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
    };
    let ack = local
        .record_catalog_receipt(&closure.segment_id, &receipt)
        .expect("catalog ack");
    assert_eq!(ack.from_commit_seq, 4);
    assert_eq!(ack.admission_digest, receipt.admission_digest.to_string());
    assert_eq!(
        local.read_segment(&closure).expect("origin retained"),
        bytes
    );

    let retried = local
        .record_catalog_receipt(&closure.segment_id, &receipt)
        .expect("exact catalog ACK retry");
    assert_eq!(retried, ack);

    let mut wrong = receipt.clone();
    wrong.admitted.observations = WireU64::new(1);
    assert!(
        local
            .record_catalog_receipt(&closure.segment_id, &wrong)
            .is_err()
    );

    let mut wrong_digest = receipt;
    wrong_digest.admission_digest =
        ValueDigest::new(format!("sha256:{}", "b".repeat(64))).expect("wrong admission");
    assert!(
        local
            .record_catalog_receipt(&closure.segment_id, &wrong_digest)
            .is_err()
    );
}

#[test]
fn catalog_ack_crash_after_temporary_sync_retries_without_rewriting_origin() {
    let root = TempDir::new().expect("temp root");
    let config = spool_config(&root, 10_000_000, 100_000);
    let faults = Arc::new(FailOnce::at(FaultPoint::AfterAckTemporarySync));
    let local = LocalSpool::open_with_faults(config.clone(), faults).expect("faulted spool");
    let entry = evidence_entry("catalog-crash-batch");
    let SpoolEntry::EvidenceBatch(batch_entry) = &entry else {
        panic!("expected batch");
    };
    let batch_entry = batch_entry.clone();
    let (bytes, closure) = public_segment("catalog-crash-segment", entry);
    local
        .append_segment(&bytes, &closure)
        .expect("append origin");
    let receipt = DurableReceipt {
        contract: stable("joshi.store.ingest_receipt"),
        schema_version: 1,
        catalog_id: stable("catalog-fixture"),
        catalog_schema: stable("schema-fixture"),
        commit_seq: CommitSeq::new(7),
        from_commit_seq: CommitSeq::new(7),
        through_commit_seq: CommitSeq::new(7),
        batch_id: stable(&batch_entry.closure.batch_id),
        batch_digest: BatchDigest::new(&batch_entry.closure.logical_digest).expect("digest"),
        admission_digest: ValueDigest::new(format!("sha256:{}", "c".repeat(64)))
            .expect("admission"),
        status: IdempotencyStatus::Accepted,
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
    };
    assert!(matches!(
        local.record_catalog_receipt(&closure.segment_id, &receipt),
        Err(SpoolError::Injected(FaultPoint::AfterAckTemporarySync))
    ));
    assert_eq!(
        local.read_segment(&closure).expect("origin retained"),
        bytes
    );

    let reopened = LocalSpool::open(config).expect("reopen spool");
    let ack = reopened
        .record_catalog_receipt(&closure.segment_id, &receipt)
        .expect("retry pending ACK");
    assert_eq!(ack.admission_digest, receipt.admission_digest.to_string());
    assert_eq!(
        reopened.read_segment(&closure).expect("origin retained"),
        bytes
    );
}

#[derive(Deserialize)]
struct Schedules {
    contract: String,
    scenarios: Vec<Scenario>,
}

#[derive(Deserialize)]
struct Scenario {
    name: String,
    operations: Vec<Operation>,
}

#[derive(Deserialize)]
struct Operation {
    op: String,
    segment: Option<usize>,
    offset: Option<u64>,
    length: Option<usize>,
    #[serde(default)]
    expect_error: bool,
}

#[test]
fn deterministic_fixture_schedules_cover_reorder_duplicate_and_partial_resume() {
    let schedules: Schedules = serde_json::from_str(include_str!(
        "../../../fixtures/spool/replication_schedules.json"
    ))
    .expect("schedule fixture");
    assert_eq!(schedules.contract, "joshi.spool.replication_schedules.v1");
    let scenario_names: BTreeSet<_> = schedules
        .scenarios
        .iter()
        .map(|scenario| scenario.name.as_str())
        .collect();
    assert_eq!(scenario_names.len(), schedules.scenarios.len());

    for scenario in schedules.scenarios {
        let root = TempDir::new().expect("temp root");
        let config = replica_config(&root);
        let segments = [
            public_segment("schedule-a", evidence_entry("schedule-batch-a")),
            public_segment("schedule-b", evidence_entry("schedule-batch-b")),
        ];
        let mut replica = Replica::open(config.clone()).expect("replica");
        for operation in scenario.operations {
            match operation.op.as_str() {
                "restart" => replica = Replica::open(config.clone()).expect("restart"),
                "send" => {
                    let index = operation.segment.expect("segment");
                    let (bytes, closure) = &segments[index];
                    let offset = operation.offset.expect("offset");
                    let start = usize::try_from(offset).expect("fixture offset");
                    let end = start
                        .saturating_add(operation.length.expect("length"))
                        .min(bytes.len());
                    let result = replica.apply_chunk(&TransferChunk {
                        closure: closure.clone(),
                        offset,
                        bytes: bytes[start..end].to_vec(),
                    });
                    assert_eq!(result.is_err(), operation.expect_error, "{}", scenario.name);
                }
                "send_remainder" => {
                    let index = operation.segment.expect("segment");
                    let (bytes, closure) = &segments[index];
                    let offset = match replica.resume_state(closure).expect("resume") {
                        ResumeState::Missing | ResumeState::Durable(_) => 0,
                        ResumeState::Partial { durable_bytes } => durable_bytes,
                        ResumeState::Conflict => panic!("fixture conflict"),
                    };
                    let start = usize::try_from(offset).expect("resume offset");
                    let result = replica.apply_chunk(&TransferChunk {
                        closure: closure.clone(),
                        offset,
                        bytes: if start == bytes.len() {
                            bytes.clone()
                        } else {
                            bytes[start..].to_vec()
                        },
                    });
                    assert!(result.is_ok(), "{}", scenario.name);
                }
                "expect_durable" => {
                    let index = operation.segment.expect("segment");
                    assert!(matches!(
                        replica
                            .resume_state(&segments[index].1)
                            .expect("durable state"),
                        ResumeState::Durable(_)
                    ));
                }
                other => panic!("unsupported fixture operation {other}"),
            }
        }
    }
}

#[test]
fn private_header_contains_key_id_but_never_key_bytes() {
    let key_bytes = [0xAB_u8; 32];
    let protector = SegmentProtector::new(
        KeyMaterial::new("non-secret-key-id", key_bytes).expect("key material"),
    )
    .expect("protector");
    let (bytes, _) = encode_segment(
        segment_id("metadata-private"),
        time(),
        &[evidence_entry("metadata-batch")],
        &ProtectionRequest::AuthenticatedPrivate {
            domain: domain("metadata-domain"),
            key_id: "non-secret-key-id".into(),
            nonce: [1_u8; 12],
        },
        Some(&protector),
    )
    .expect("encode");
    let inspected = inspect_segment(&bytes).expect("inspect");
    assert!(matches!(
        inspected.header.protection,
        ProtectionMetadata::AuthenticatedPrivate { .. }
    ));
    assert!(
        !bytes
            .windows(key_bytes.len())
            .any(|window| window == key_bytes)
    );
}
