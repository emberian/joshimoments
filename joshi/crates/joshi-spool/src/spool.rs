use crate::{
    AckKey, CatalogAdmissionAck, FaultInjector, FaultPoint, NoFaults, RemoteDurabilityAck, Result,
    SegmentClosure, SegmentId, SpoolError, SpoolStatus, TransferChunk, codec, fsutil, model,
};
use joshi_store::{DurableReceipt, GapOutcome};
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};

const LAYOUT: &[&str] = &["staging", "ready", "acks", "catalog_acks", "quarantine"];

/// Local byte-spool bounds. `control_reserve_bytes` is unavailable to evidence segments, allowing
/// pressure/corruption/deletion facts to remain appendable after evidence admission degrades.
#[derive(Clone, Debug)]
pub struct SpoolConfig {
    pub root: PathBuf,
    pub max_segment_bytes: u64,
    pub max_entries_per_segment: usize,
    pub max_total_bytes: u64,
    pub control_reserve_bytes: u64,
    pub max_transfer_chunk_bytes: u64,
}

impl SpoolConfig {
    fn validate(&self) -> Result<()> {
        if self.max_segment_bytes == 0
            || self.max_entries_per_segment == 0
            || self.max_total_bytes == 0
            || self.max_transfer_chunk_bytes == 0
            || self.control_reserve_bytes >= self.max_total_bytes
        {
            return Err(SpoolError::Invalid(
                "invalid zero or reserve spool bound".into(),
            ));
        }
        Ok(())
    }
}

/// Result of idempotent local admission.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AppendOutcome {
    /// New exact bytes crossed the durable rename/fsync boundary.
    Appended,
    /// The same occurrence and exact byte closure were already durable.
    Idempotent,
}

/// Filesystem-backed single-host spool. All methods are synchronous so callers choose their own
/// process/runtime boundary.
pub struct LocalSpool {
    config: SpoolConfig,
    faults: Arc<dyn FaultInjector>,
}

impl LocalSpool {
    /// Opens or creates a spool with production durability behavior.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid bounds or failure to create/fsync the directory layout.
    pub fn open(config: SpoolConfig) -> Result<Self> {
        Self::open_with_faults(config, Arc::new(NoFaults))
    }

    /// Opens a spool with deterministic failure injection.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid bounds or failure to create/fsync the directory layout.
    pub fn open_with_faults(config: SpoolConfig, faults: Arc<dyn FaultInjector>) -> Result<Self> {
        config.validate()?;
        fsutil::create_layout(&config.root, LAYOUT)?;
        Ok(Self { config, faults })
    }

    /// Admits one already-encoded segment. Same ID/same bytes is idempotent; same ID/different
    /// bytes is a hard conflict. Private nonce uniqueness is rechecked across durable segments.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid bytes/closure, identity or nonce conflict, exhausted bounds,
    /// filesystem failure, or an injected durability fault.
    pub fn append_segment(&self, bytes: &[u8], expected: &SegmentClosure) -> Result<AppendOutcome> {
        let segment = codec::verify_exact(bytes, expected)?;
        if expected.exact_segment.byte_len > self.config.max_segment_bytes {
            return Err(SpoolError::BoundExceeded("segment byte length".into()));
        }
        if segment.header.entries.len() > self.config.max_entries_per_segment {
            return Err(SpoolError::BoundExceeded("segment entry count".into()));
        }

        if let Some((_path, closure)) = self.find_segment(&expected.segment_id)? {
            if closure == *expected {
                fsutil::sync_directory(&self.config.root.join("ready"))?;
                return Ok(AppendOutcome::Idempotent);
            }
            return Err(SpoolError::IdentityConflict(expected.segment_id.clone()));
        }
        self.reject_persisted_nonce_reuse(&segment)?;

        let is_control = segment
            .header
            .entries
            .iter()
            .all(|entry| entry.kind != "evidence_batch");
        let path = self.ready_path(expected);
        let pending = path.parent().map(|parent| {
            parent.join(format!(
                ".{}.pending",
                path.file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or("invalid")
            ))
        });
        let recovering = match pending {
            Some(ref pending) if pending.exists() => {
                if fsutil::read(pending)? != bytes {
                    return Err(SpoolError::Integrity(
                        "pending segment bytes conflict with retry".into(),
                    ));
                }
                true
            }
            _ => false,
        };
        if !recovering {
            self.reserve(bytes.len(), is_control)?;
        }
        fsutil::atomic_write(
            &path,
            bytes,
            self.faults.as_ref(),
            FaultPoint::AfterTemporarySync,
            FaultPoint::AfterReadyRename,
        )?;
        Ok(AppendOutcome::Appended)
    }

    /// Lists verified durable segment closures. Corrupt files are quarantined and surfaced as an
    /// error, so callers can append a scoped gap rather than silently skipping loss.
    ///
    /// # Errors
    ///
    /// Returns the integrity or filesystem error after quarantining a corrupt segment.
    pub fn list_segments(&self) -> Result<Vec<SegmentClosure>> {
        let mut closures = Vec::new();
        for path in fsutil::list_files(&self.config.root.join("ready"))? {
            if !path
                .file_name()
                .and_then(|value| value.to_str())
                .is_some_and(|name| name.ends_with(".segment"))
            {
                continue;
            }
            let bytes = fsutil::read(&path)?;
            match codec::exact_closure(&bytes) {
                Ok(closure) => closures.push(closure),
                Err(error) => {
                    self.quarantine(&path, &error.to_string())?;
                    return Err(error);
                }
            }
        }
        closures.sort_by(|left, right| left.segment_id.cmp(&right.segment_id));
        Ok(closures)
    }

    /// Reads exact durable bytes for transfer, verifying them before release.
    ///
    /// # Errors
    ///
    /// Returns an error when the segment is absent, conflicts, is corrupt, or cannot be read.
    pub fn read_segment(&self, expected: &SegmentClosure) -> Result<Vec<u8>> {
        let Some((path, closure)) = self.find_segment(&expected.segment_id)? else {
            return Err(SpoolError::Invalid(format!(
                "segment {} is not present",
                expected.segment_id
            )));
        };
        if closure != *expected {
            return Err(SpoolError::IdentityConflict(expected.segment_id.clone()));
        }
        let bytes = fsutil::read(&path)?;
        if let Err(error) = codec::verify_exact(&bytes, expected) {
            self.quarantine(&path, &error.to_string())?;
            return Err(error);
        }
        Ok(bytes)
    }

    /// Reads the next configured bounded transfer chunk from an exact durable offset.
    ///
    /// # Errors
    ///
    /// Returns an error when the segment is absent/conflicting/corrupt, the offset is at or beyond
    /// the segment end, a configured length cannot fit in memory, or the filesystem read fails.
    pub fn read_transfer_chunk(
        &self,
        expected: &SegmentClosure,
        offset: u64,
    ) -> Result<TransferChunk> {
        let bytes = self.read_segment(expected)?;
        let start = usize::try_from(offset)
            .map_err(|_| SpoolError::BoundExceeded("transfer offset".into()))?;
        if start >= bytes.len() {
            return Err(SpoolError::TransferOffset {
                expected: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
                received: offset,
            });
        }
        let maximum = usize::try_from(self.config.max_transfer_chunk_bytes)
            .map_err(|_| SpoolError::BoundExceeded("configured transfer chunk length".into()))?;
        let end = start.saturating_add(maximum).min(bytes.len());
        Ok(TransferChunk {
            closure: expected.clone(),
            offset,
            bytes: bytes[start..end].to_vec(),
        })
    }

    /// Durably records a replica receipt after matching every occurrence/byte/domain/generation
    /// field. This receipt does not dequeue, delete, or imply catalog admission.
    ///
    /// # Errors
    ///
    /// Returns an error when the receipt does not close local bytes or cannot be made durable.
    pub fn record_remote_ack(&self, ack: &RemoteDurabilityAck) -> Result<AppendOutcome> {
        if ack.contract != crate::REMOTE_ACK_CONTRACT_VERSION {
            return Err(SpoolError::AckMismatch);
        }
        let Some((_path, local)) = self.find_segment(&ack.segment.segment_id)? else {
            return Err(SpoolError::AckMismatch);
        };
        if local != ack.segment || ack.replica_generation.is_empty() {
            return Err(SpoolError::AckMismatch);
        }
        let bytes = serde_json::to_vec(ack)?;
        let path = self.remote_ack_path(
            &ack.segment.segment_id,
            &AckKey {
                replica_id: ack.replica_id.clone(),
                replica_generation: ack.replica_generation.clone(),
            },
        );
        atomic_idempotent_json(
            &path,
            &bytes,
            self.faults.as_ref(),
            FaultPoint::AfterAckTemporarySync,
        )
    }

    /// Matches a real post-commit store receipt against one retained batch and durably records the
    /// stronger admission closure. This remains separate from remote byte durability.
    ///
    /// # Errors
    ///
    /// Returns an error when the exact batch/policy/count/acquisition/gap/commit closure differs or
    /// when the admission receipt cannot be made durable.
    pub fn record_catalog_receipt(
        &self,
        segment_id: &SegmentId,
        receipt: &DurableReceipt,
    ) -> Result<CatalogAdmissionAck> {
        let (path, _closure) = self
            .find_segment(segment_id)?
            .ok_or_else(|| SpoolError::Invalid(format!("segment {segment_id} is not present")))?;
        let bytes = fsutil::read(&path)?;
        let segment = codec::inspect_segment(&bytes)?;
        let batch = segment
            .header
            .entries
            .iter()
            .filter_map(|entry| entry.batch.as_ref())
            .find(|batch| batch.batch_id == receipt.batch_id.as_str())
            .ok_or_else(|| {
                SpoolError::CatalogReceiptMismatch("batch is absent from segment header".into())
            })?;
        verify_receipt(batch, receipt)?;
        let ack = CatalogAdmissionAck {
            contract: String::new(),
            segment_id: segment_id.clone(),
            catalog_id: receipt.catalog_id.to_string(),
            catalog_schema: receipt.catalog_schema.to_string(),
            batch_id: receipt.batch_id.to_string(),
            logical_digest: receipt.batch_digest.to_string(),
            admission_digest: receipt.admission_digest.to_string(),
            from_commit_seq: receipt.from_commit_seq.get(),
            through_commit_seq: receipt.through_commit_seq.get(),
        }
        .with_contract();
        let encoded = serde_json::to_vec(&ack)?;
        let durable_path = self.catalog_ack_path(segment_id, &ack.batch_id, &ack.catalog_id);
        atomic_idempotent_json(
            &durable_path,
            &encoded,
            self.faults.as_ref(),
            FaultPoint::AfterAckTemporarySync,
        )?;
        Ok(ack)
    }

    /// Current on-disk capacity state.
    ///
    /// # Errors
    ///
    /// Returns an error when filesystem usage cannot be inspected or overflows.
    pub fn status(&self) -> Result<SpoolStatus> {
        let used_bytes = directory_bytes(&self.config.root)?;
        Ok(SpoolStatus {
            used_bytes,
            maximum_bytes: self.config.max_total_bytes,
            control_reserve_bytes: self.config.control_reserve_bytes,
            degraded: used_bytes
                >= self
                    .config
                    .max_total_bytes
                    .saturating_sub(self.config.control_reserve_bytes),
        })
    }

    fn reserve(&self, incoming: usize, is_control: bool) -> Result<()> {
        let used = directory_bytes(&self.config.root)?;
        let incoming = u64::try_from(incoming)
            .map_err(|_| SpoolError::BoundExceeded("incoming segment length".into()))?;
        let after = used
            .checked_add(incoming)
            .ok_or_else(|| SpoolError::BoundExceeded("spool byte sum".into()))?;
        let limit = if is_control {
            self.config.max_total_bytes
        } else {
            self.config
                .max_total_bytes
                .saturating_sub(self.config.control_reserve_bytes)
        };
        if after > limit {
            return Err(SpoolError::Degraded(format!(
                "{used} bytes used plus {incoming} incoming exceeds {limit}; append a scoped gap"
            )));
        }
        Ok(())
    }

    fn find_segment(&self, id: &SegmentId) -> Result<Option<(PathBuf, SegmentClosure)>> {
        let prefix = format!("{}.", model::stable_path_component(id.as_str()));
        let mut found = None;
        for path in fsutil::list_files(&self.config.root.join("ready"))? {
            let matches = path
                .file_name()
                .and_then(|value| value.to_str())
                .is_some_and(|name| name.starts_with(&prefix) && name.ends_with(".segment"));
            if !matches {
                continue;
            }
            let bytes = fsutil::read(&path)?;
            let closure = match codec::exact_closure(&bytes) {
                Ok(closure) => closure,
                Err(error) => {
                    self.quarantine(&path, &error.to_string())?;
                    return Err(error);
                }
            };
            if closure.segment_id != *id || found.is_some() {
                return Err(SpoolError::IdentityConflict(id.clone()));
            }
            found = Some((path, closure));
        }
        Ok(found)
    }

    fn reject_persisted_nonce_reuse(&self, incoming: &crate::DiskSegment) -> Result<()> {
        let crate::ProtectionMetadata::AuthenticatedPrivate {
            key_id,
            nonce_base64,
            ..
        } = &incoming.header.protection
        else {
            return Ok(());
        };
        for path in fsutil::list_files(&self.config.root.join("ready"))? {
            if !path
                .file_name()
                .and_then(|value| value.to_str())
                .is_some_and(|name| name.ends_with(".segment"))
            {
                continue;
            }
            let existing = codec::inspect_segment(&fsutil::read(&path)?)?;
            if let crate::ProtectionMetadata::AuthenticatedPrivate {
                key_id: existing_key,
                nonce_base64: existing_nonce,
                ..
            } = &existing.header.protection
                && existing.header.domain == incoming.header.domain
                && existing_key == key_id
                && existing_nonce == nonce_base64
            {
                return Err(SpoolError::NonceReuse {
                    key_id: key_id.clone(),
                    domain: incoming.header.domain.clone(),
                });
            }
        }
        Ok(())
    }

    fn ready_path(&self, closure: &SegmentClosure) -> PathBuf {
        self.config.root.join("ready").join(format!(
            "{}.{}.segment",
            model::stable_path_component(closure.segment_id.as_str()),
            closure.exact_segment.digest.replace(':', "-")
        ))
    }

    fn remote_ack_path(&self, segment: &SegmentId, key: &AckKey) -> PathBuf {
        self.config.root.join("acks").join(format!(
            "{}.{}.{}.json",
            model::stable_path_component(segment.as_str()),
            model::stable_path_component(key.replica_id.as_str()),
            model::stable_path_component(&key.replica_generation)
        ))
    }

    fn catalog_ack_path(&self, segment: &SegmentId, batch: &str, catalog: &str) -> PathBuf {
        self.config.root.join("catalog_acks").join(format!(
            "{}.{}.{}.json",
            model::stable_path_component(segment.as_str()),
            model::stable_path_component(batch),
            model::stable_path_component(catalog)
        ))
    }

    fn quarantine(&self, path: &Path, reason: &str) -> Result<()> {
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| SpoolError::Invalid("quarantine filename is not UTF-8".into()))?;
        let destination = self.config.root.join("quarantine").join(name);
        fs::rename(path, &destination).map_err(|error| SpoolError::io(&destination, error))?;
        fsutil::sync_directory(&self.config.root.join("ready"))?;
        fsutil::sync_directory(&self.config.root.join("quarantine"))?;
        let reason_path = self
            .config
            .root
            .join("quarantine")
            .join(format!("{name}.reason.json"));
        let reason_bytes = serde_json::to_vec(&serde_json::json!({
            "contract": "joshi.spool.quarantine.v1",
            "reason": reason,
        }))?;
        fsutil::atomic_write(
            &reason_path,
            &reason_bytes,
            &NoFaults,
            FaultPoint::AfterTemporarySync,
            FaultPoint::AfterReadyRename,
        )
    }
}

fn verify_receipt(batch: &crate::BatchClosure, receipt: &DurableReceipt) -> Result<()> {
    if batch.admission_digest.is_some() {
        return Err(SpoolError::CatalogReceiptMismatch(
            "origin segment must not contain a postcommit store admission digest".into(),
        ));
    }
    if receipt.from_commit_seq != receipt.through_commit_seq
        || receipt.commit_seq != receipt.through_commit_seq
    {
        return Err(SpoolError::CatalogReceiptMismatch(
            "catalog receipt must close one exact ingest commit".into(),
        ));
    }
    if receipt.admission_digest.as_str() == batch.logical_digest {
        return Err(SpoolError::CatalogReceiptMismatch(
            "logical and store-admission digest domains must remain distinct".into(),
        ));
    }
    let counts = &batch.counts;
    let admitted = &receipt.admitted;
    let actual_acquisitions: BTreeSet<_> = receipt
        .acquisition_ids
        .iter()
        .map(ToString::to_string)
        .collect();
    let expected_acquisitions: BTreeSet<_> = batch.acquisition_ids.iter().cloned().collect();
    let actual_gaps: BTreeSet<_> = receipt
        .gap_outcomes
        .iter()
        .map(|gap: &GapOutcome| gap.gap_id.to_string())
        .collect();
    let expected_gaps: BTreeSet<_> = batch.gap_ids.iter().cloned().collect();
    let all_match = receipt.batch_id.as_str() == batch.batch_id
        && receipt.contract.as_str() == "joshi.store.ingest_receipt"
        && receipt.schema_version == 1
        && receipt.batch_digest.as_str() == batch.logical_digest
        && admitted.acquisitions.get() == counts.acquisitions
        && admitted.raw_blobs.get() == counts.raw_blobs
        && admitted.raw_bytes.get() == counts.raw_bytes
        && admitted.observations.get() == counts.observations
        && admitted.source_events.get() == counts.source_events
        && admitted.assertions.get() == counts.assertions
        && admitted.coverage_windows.get() == counts.coverage_windows
        && admitted.coverage_gaps.get() == counts.coverage_gaps
        && admitted.coverage_recoveries.get() == counts.coverage_recoveries
        && admitted.cursor_advances.get() == counts.cursor_advances
        && actual_acquisitions == expected_acquisitions
        && actual_gaps == expected_gaps
        && receipt.from_commit_seq.get() > 0;
    if all_match {
        Ok(())
    } else {
        Err(SpoolError::CatalogReceiptMismatch(
            "batch/digest/policy/count/acquisition/gap/commit closure differs".into(),
        ))
    }
}

fn atomic_idempotent_json(
    path: &Path,
    bytes: &[u8],
    faults: &dyn FaultInjector,
    after_temp: FaultPoint,
) -> Result<AppendOutcome> {
    if path.exists() {
        return if fsutil::read(path)? == bytes {
            if let Some(parent) = path.parent() {
                fsutil::sync_directory(parent)?;
            }
            Ok(AppendOutcome::Idempotent)
        } else {
            Err(SpoolError::Integrity(format!(
                "durable receipt conflict at {}",
                path.display()
            )))
        };
    }
    fsutil::atomic_write(
        path,
        bytes,
        faults,
        after_temp,
        FaultPoint::AfterReadyRename,
    )?;
    Ok(AppendOutcome::Appended)
}

pub(crate) fn directory_bytes(root: &Path) -> Result<u64> {
    let mut total = 0_u64;
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory).map_err(|error| SpoolError::io(&directory, error))? {
            let entry = entry.map_err(|error| SpoolError::io(&directory, error))?;
            let metadata = entry
                .metadata()
                .map_err(|error| SpoolError::io(entry.path(), error))?;
            if metadata.is_dir() {
                pending.push(entry.path());
            } else if metadata.is_file() {
                total = total
                    .checked_add(metadata.len())
                    .ok_or_else(|| SpoolError::BoundExceeded("spool disk usage".into()))?;
            }
        }
    }
    Ok(total)
}
