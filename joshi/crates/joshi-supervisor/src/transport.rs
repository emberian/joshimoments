use crate::{
    DurableOutcome, FaultInjector, FaultPoint, ProtectionProfile, Result, SupervisorError,
};
use joshi_admission::{
    PublicStoreReceiptV1, Sha256Digest,
    operational::{
        AUTHORITY, ExactByteClosureV1, OperationalStatus, PublicProtectionClass,
        SPOOL_CATALOG_RECEIPT_CONTRACT, SpoolBatchClosureV1, SpoolCatalogReceiptV1,
    },
};
use joshi_domain::UtcTimestamp;
use joshi_spool::{
    EvidenceBatchEntry, LocalSpool, ProtectionMetadata, ProtectionRequest, RemoteDurabilityAck,
    Replica, ResumeState, SegmentClosure, SegmentId, SegmentProtector, SpoolEntry, encode_segment,
    inspect_segment,
};
use joshi_store::DurableReceipt;
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeMap, sync::Arc};

/// Source-owned lossless mapping into the common spool queue. The supervisor deliberately cannot
/// invent event IDs, event time, finality, coverage, or cursor authority for a raw `SourceOutput`.
pub trait SourceOutputAdapter {
    /// Prepare one exact bounded spool item under a prior durable reservation.
    ///
    /// # Errors
    ///
    /// Refuses a source output whose evidence/coverage semantics cannot be represented exactly.
    fn prepare(
        &mut self,
        reservation: &crate::AttemptReservation,
        output: joshi_sources::SourceOutput,
    ) -> Result<crate::PendingSegment>;
}

#[derive(Debug)]
// Saturation must return the exact owned item, including its exact bytes and reservation. Boxing
// would only move that bounded payload behind another allocation and would weaken the public seam.
#[allow(clippy::large_enum_variant)]
pub enum SourceIngressError {
    Adapter(SupervisorError),
    Saturated(crate::PendingSegment),
}

/// Prepare an exact durable ingest batch from any reviewed source adapter (ordinary
/// `SourceOutput`, direct Pump, companion, or wallet-source). The origin segment deliberately
/// has no store-admission digest: that digest does not exist until the sole store commits exact
/// retained bytes and is bound later by a separate catalog acknowledgement.
///
/// # Errors
///
/// Refuses noncanonical batch bytes, wrong logical/policy closure, or queue-item encoding failure.
pub fn prepare_evidence_batch(
    reservation: crate::AttemptReservation,
    batch: &joshi_evidence::DurableIngestBatch,
    exact_batch_bytes: Vec<u8>,
    policy_contract: impl Into<String>,
    exact_policy_bytes: Vec<u8>,
) -> Result<crate::PendingSegment> {
    let entry = EvidenceBatchEntry::from_exact_bytes(
        batch,
        exact_batch_bytes,
        policy_contract,
        exact_policy_bytes,
        None,
    )?;
    crate::PendingSegment::new(
        reservation,
        SpoolEntry::EvidenceBatch(entry),
        crate::QueueClass::Evidence,
    )
}

pub(crate) struct LocalTransport {
    spool: LocalSpool,
    installation_id: String,
    protectors: BTreeMap<String, Arc<SegmentProtector>>,
    faults: Arc<dyn FaultInjector>,
    maximum_bytes_per_utc_day: u64,
}

impl LocalTransport {
    pub(crate) fn new(
        spool: LocalSpool,
        installation_id: String,
        protectors: BTreeMap<String, Arc<SegmentProtector>>,
        faults: Arc<dyn FaultInjector>,
        maximum_bytes_per_utc_day: u64,
    ) -> Self {
        Self {
            spool,
            installation_id,
            protectors,
            faults,
            maximum_bytes_per_utc_day,
        }
    }

    pub(crate) fn spool(&self) -> &LocalSpool {
        &self.spool
    }

    pub(crate) fn attempt_segment_id(&self, reservation_id: &crate::ReservationId) -> SegmentId {
        stable_segment_id("attempt", &self.installation_id, reservation_id.as_str())
    }

    pub(crate) fn control_segment_id(&self, ordinal: u64, purpose: &str) -> SegmentId {
        stable_segment_id(
            purpose,
            &self.installation_id,
            &format!("control-{ordinal}"),
        )
    }

    pub(crate) fn append_attempt(
        &self,
        reservation: &crate::AttemptReservation,
        entry: &SpoolEntry,
    ) -> Result<(SegmentClosure, DurableOutcome)> {
        let id = self.attempt_segment_id(&reservation.reservation_id);
        self.append(id, reservation.reserved_at, &reservation.protection, entry)
    }

    pub(crate) fn append_control(
        &self,
        id: SegmentId,
        created_at: UtcTimestamp,
        protection: &ProtectionProfile,
        entry: &SpoolEntry,
    ) -> Result<(SegmentClosure, DurableOutcome)> {
        self.append(id, created_at, protection, entry)
    }

    fn append(
        &self,
        id: SegmentId,
        created_at: UtcTimestamp,
        protection: &ProtectionProfile,
        entry: &SpoolEntry,
    ) -> Result<(SegmentClosure, DurableOutcome)> {
        protection.validate()?;
        let nonce = deterministic_nonce(&self.installation_id, &id, protection);
        let request = match protection {
            ProtectionProfile::PublicIntegrity { domain } => ProtectionRequest::Public {
                domain: domain.clone(),
            },
            ProtectionProfile::AuthenticatedPrivate { domain, key_id } => {
                ProtectionRequest::AuthenticatedPrivate {
                    domain: domain.clone(),
                    key_id: key_id.clone(),
                    nonce,
                }
            }
        };
        let protector = protection
            .key_id()
            .and_then(|key_id| self.protectors.get(key_id))
            .map(AsRef::as_ref);
        let (bytes, closure) = encode_segment(
            id,
            created_at,
            std::slice::from_ref(entry),
            &request,
            protector,
        )?;
        if matches!(entry, SpoolEntry::EvidenceBatch(_)) {
            self.enforce_daily_budget(created_at, &closure)?;
        }
        let outcome = self.spool.append_segment(&bytes, &closure)?;
        self.faults.check(FaultPoint::AfterLocalSpoolAppend)?;
        Ok((closure, outcome.into()))
    }

    fn enforce_daily_budget(
        &self,
        created_at: UtcTimestamp,
        incoming: &SegmentClosure,
    ) -> Result<()> {
        let day = utc_day(created_at);
        let mut used = 0_u64;
        for closure in self.spool.list_segments()? {
            if closure.segment_id == incoming.segment_id {
                // Same-identity retry adds no bytes. The spool still performs exact conflict
                // detection below.
                return Ok(());
            }
            let bytes = self.spool.read_segment(&closure)?;
            let segment = inspect_segment(&bytes)?;
            if utc_day(segment.header.created_at) == day {
                used = used
                    .checked_add(closure.exact_segment.byte_len)
                    .ok_or_else(|| {
                        SupervisorError::InvalidValue("daily spool byte sum overflow".into())
                    })?;
            }
        }
        let incoming_bytes = incoming.exact_segment.byte_len;
        if used.saturating_add(incoming_bytes) > self.maximum_bytes_per_utc_day {
            Err(SupervisorError::DailySpoolBudget {
                day,
                used,
                incoming: incoming_bytes,
                maximum: self.maximum_bytes_per_utc_day,
            })
        } else {
            Ok(())
        }
    }

    pub(crate) fn find_attempt(
        &self,
        reservation_id: &crate::ReservationId,
    ) -> Result<Option<(SegmentClosure, Vec<String>)>> {
        let expected = self.attempt_segment_id(reservation_id);
        let Some(closure) = self
            .spool
            .list_segments()?
            .into_iter()
            .find(|closure| closure.segment_id == expected)
        else {
            return Ok(None);
        };
        let bytes = self.spool.read_segment(&closure)?;
        let segment = inspect_segment(&bytes)?;
        Ok(Some((
            closure,
            segment
                .header
                .entries
                .iter()
                .map(|entry| entry.kind.clone())
                .collect(),
        )))
    }
}

fn utc_day(value: UtcTimestamp) -> String {
    value.to_string().chars().take(10).collect()
}

fn stable_segment_id(purpose: &str, installation: &str, material: &str) -> SegmentId {
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.supervisor.segment-id.v1\0");
    hasher.update(purpose.as_bytes());
    hasher.update(b"\0");
    hasher.update(installation.as_bytes());
    hasher.update(b"\0");
    hasher.update(material.as_bytes());
    SegmentId::new(format!(
        "segment-{purpose}-{}-{:x}",
        &installation[5..13],
        hasher.finalize()
    ))
    .expect("fixed bounded segment identity")
}

fn deterministic_nonce(
    installation: &str,
    segment_id: &SegmentId,
    protection: &ProtectionProfile,
) -> [u8; 12] {
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.supervisor.segment-nonce.v1\0");
    hasher.update(installation.as_bytes());
    hasher.update(b"\0");
    hasher.update(segment_id.as_str().as_bytes());
    hasher.update(b"\0");
    hasher.update(protection.domain().as_str().as_bytes());
    if let Some(key_id) = protection.key_id() {
        hasher.update(b"\0");
        hasher.update(key_id.as_bytes());
    }
    let digest = hasher.finalize();
    let mut nonce = [0_u8; 12];
    nonce.copy_from_slice(&digest[..12]);
    nonce
}

/// Exact sink seam used by the transport-neutral catalog replay adapter. Implementations must
/// return the real post-commit durable receipt, not an HTTP status or partial acknowledgement.
pub trait CatalogSink {
    /// Admit one exact retained batch/policy closure.
    ///
    /// # Errors
    ///
    /// Returns a sanitized error when no exact post-commit receipt is available.
    fn admit(
        &mut self,
        segment: &SegmentClosure,
        batch: &EvidenceBatchEntry,
    ) -> std::result::Result<DurableReceipt, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CatalogDrainReport {
    pub segments_examined: u64,
    pub batches_admitted: u64,
    pub catalog_acks_recorded: u64,
    pub control_entries_retained: u64,
    pub receipts: Vec<SpoolCatalogReceiptV1>,
}

/// No-listener, transport-neutral spool-to-catalog replay. Exact bytes remain in the spool after
/// every receipt; this adapter has no retention or deletion method.
pub struct CatalogTransport<'a> {
    spool: &'a LocalSpool,
    protectors: &'a BTreeMap<String, Arc<SegmentProtector>>,
}

impl<'a> CatalogTransport<'a> {
    #[must_use]
    pub const fn new(
        spool: &'a LocalSpool,
        protectors: &'a BTreeMap<String, Arc<SegmentProtector>>,
    ) -> Self {
        Self { spool, protectors }
    }

    /// Replay every verified segment into an exact catalog sink.
    ///
    /// # Errors
    ///
    /// Refuses corruption, unavailable private keys, sink failure, or a mismatched catalog
    /// receipt. A segment is never deleted or skipped on failure.
    pub fn drain(&self, sink: &mut dyn CatalogSink) -> Result<CatalogDrainReport> {
        let closures = self.spool.list_segments()?;
        let mut report = CatalogDrainReport {
            segments_examined: 0,
            batches_admitted: 0,
            catalog_acks_recorded: 0,
            control_entries_retained: 0,
            receipts: Vec::new(),
        };
        for closure in closures {
            report.segments_examined = report.segments_examined.saturating_add(1);
            let bytes = self.spool.read_segment(&closure)?;
            let inspected = inspect_segment(&bytes)?;
            let protector = protector_for(&inspected.header.protection, self.protectors)?;
            let entries = joshi_spool::decode_segment(&bytes, protector)?;
            for entry in entries {
                let SpoolEntry::EvidenceBatch(batch) = entry else {
                    report.control_entries_retained =
                        report.control_entries_retained.saturating_add(1);
                    continue;
                };
                let receipt = sink
                    .admit(&closure, &batch)
                    .map_err(SupervisorError::Catalog)?;
                self.spool
                    .record_catalog_receipt(&closure.segment_id, &receipt)?;
                let public = PublicStoreReceiptV1::from_committed(
                    &receipt,
                    &serde_json::from_slice(&batch.exact_batch_bytes)?,
                )?;
                let exact_segment = exact_closure(
                    &closure.exact_segment.digest,
                    closure.exact_segment.byte_len,
                )?;
                let receipt = SpoolCatalogReceiptV1 {
                    contract: SPOOL_CATALOG_RECEIPT_CONTRACT.into(),
                    schema_version: 1,
                    segment_id: closure.segment_id.to_string(),
                    protection_domain: closure.domain.to_string(),
                    protection_class: public_protection(closure.protection_class),
                    exact_segment,
                    batch: SpoolBatchClosureV1 {
                        batch_id: batch.closure.batch_id.clone(),
                        exact_batch: exact_closure(
                            &batch.closure.exact_batch.digest,
                            batch.closure.exact_batch.byte_len,
                        )?,
                        logical_batch_digest: Sha256Digest::parse(&batch.closure.logical_digest)?,
                        exact_policy: exact_closure(
                            &batch.closure.exact_policy.digest,
                            batch.closure.exact_policy.byte_len,
                        )?,
                        store_admission_digest: Sha256Digest::parse(
                            receipt.admission_digest.as_str(),
                        )?,
                    },
                    status: match &public.status {
                        joshi_admission::PublicStatus::Accepted => OperationalStatus::Accepted,
                        joshi_admission::PublicStatus::Idempotent => OperationalStatus::Idempotent,
                    },
                    catalog_receipt: public,
                    authority: AUTHORITY.into(),
                };
                receipt.validate()?;
                report.receipts.push(receipt);
                report.batches_admitted = report.batches_admitted.saturating_add(1);
                report.catalog_acks_recorded = report.catalog_acks_recorded.saturating_add(1);
            }
        }
        Ok(report)
    }
}

pub(crate) fn public_protection(value: joshi_spool::ProtectionClass) -> PublicProtectionClass {
    match value {
        joshi_spool::ProtectionClass::PublicIntegrity => PublicProtectionClass::PublicIntegrity,
        joshi_spool::ProtectionClass::AuthenticatedPrivate => {
            PublicProtectionClass::AuthenticatedPrivate
        }
    }
}

pub(crate) fn exact_closure(digest: &str, byte_len: u64) -> Result<ExactByteClosureV1> {
    Ok(ExactByteClosureV1 {
        digest: Sha256Digest::parse(digest)?,
        byte_length: byte_len.to_string(),
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplicaDrainReport {
    pub segments_examined: u64,
    pub chunks_sent: u64,
    pub remote_acks_recorded: u64,
}

/// In-process adapter over the transport-neutral replica protocol. It exists for offline replay
/// and conformance tests; it opens no socket and grants no remote semantic authority.
pub struct ReplicaTransport<'a> {
    local: &'a LocalSpool,
    replica: &'a Replica,
}

impl<'a> ReplicaTransport<'a> {
    #[must_use]
    pub const fn new(local: &'a LocalSpool, replica: &'a Replica) -> Self {
        Self { local, replica }
    }

    /// Resume and reproduce every exact sealed segment at the named replica generation.
    ///
    /// # Errors
    ///
    /// Refuses gaps, conflicts, corruption, or non-durable acknowledgements.
    pub fn drain(&self) -> Result<ReplicaDrainReport> {
        let mut report = ReplicaDrainReport {
            segments_examined: 0,
            chunks_sent: 0,
            remote_acks_recorded: 0,
        };
        for closure in self.local.list_segments()? {
            report.segments_examined = report.segments_examined.saturating_add(1);
            let ack = self.replicate_one(&closure, &mut report)?;
            self.local.record_remote_ack(&ack)?;
            report.remote_acks_recorded = report.remote_acks_recorded.saturating_add(1);
        }
        Ok(report)
    }

    fn replicate_one(
        &self,
        closure: &SegmentClosure,
        report: &mut ReplicaDrainReport,
    ) -> Result<RemoteDurabilityAck> {
        loop {
            match self.replica.resume_state(closure)? {
                ResumeState::Durable(ack) => return Ok(ack),
                ResumeState::Conflict => {
                    return Err(SupervisorError::InvalidState(format!(
                        "replica conflicts with segment {}",
                        closure.segment_id
                    )));
                }
                ResumeState::Missing => {
                    let chunk = self.local.read_transfer_chunk(closure, 0)?;
                    report.chunks_sent = report.chunks_sent.saturating_add(1);
                    if let Some(ack) = self.replica.apply_chunk(&chunk)? {
                        return Ok(ack);
                    }
                }
                ResumeState::Partial { durable_bytes } => {
                    let offset = if durable_bytes == closure.exact_segment.byte_len {
                        durable_bytes.saturating_sub(1)
                    } else {
                        durable_bytes
                    };
                    let chunk = self.local.read_transfer_chunk(closure, offset)?;
                    report.chunks_sent = report.chunks_sent.saturating_add(1);
                    if let Some(ack) = self.replica.apply_chunk(&chunk)? {
                        return Ok(ack);
                    }
                }
            }
        }
    }
}

pub(crate) fn protector_for<'a>(
    metadata: &ProtectionMetadata,
    protectors: &'a BTreeMap<String, Arc<SegmentProtector>>,
) -> Result<Option<&'a SegmentProtector>> {
    match metadata {
        ProtectionMetadata::PublicIntegrity => Ok(None),
        ProtectionMetadata::AuthenticatedPrivate { key_id, .. } => protectors
            .get(key_id)
            .map(|value| Some(value.as_ref()))
            .ok_or_else(|| {
                SupervisorError::InvalidState(format!(
                    "private segment requires unavailable key ID {key_id}"
                ))
            }),
    }
}
