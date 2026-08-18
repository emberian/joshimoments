use crate::{
    FaultInjector, FaultPoint, NoFaults, RemoteDurabilityAck, ReplicaId, Result, SegmentClosure,
    SegmentId, SpoolError, SpoolStatus, TransferChunk, codec, fsutil, model,
    spool::directory_bytes,
};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};

const LAYOUT: &[&str] = &["partial", "ready", "acks", "quarantine"];

/// Replica-side bounds and durable identity. Changing `generation` deliberately invalidates old
/// durability receipts even if a hostname or disk mount is reused.
#[derive(Clone, Debug)]
pub struct ReplicaConfig {
    pub root: PathBuf,
    pub replica_id: ReplicaId,
    pub generation: String,
    pub max_segment_bytes: u64,
    pub max_chunk_bytes: u64,
    pub max_total_bytes: u64,
}

impl ReplicaConfig {
    fn validate(&self) -> Result<()> {
        if self.generation.is_empty()
            || self.generation.len() > 255
            || self.max_segment_bytes == 0
            || self.max_chunk_bytes == 0
            || self.max_total_bytes == 0
            || self.max_segment_bytes > self.max_total_bytes
        {
            return Err(SpoolError::Invalid(
                "invalid replica identity or bound".into(),
            ));
        }
        Ok(())
    }
}

/// Durable resume state for one exact occurrence closure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ResumeState {
    Missing,
    Partial { durable_bytes: u64 },
    Durable(RemoteDurabilityAck),
    Conflict,
}

/// Transport-neutral replica receiver. A caller may carry chunks over SSH, HTTP, removable media,
/// or an in-process test; none of those transports changes receipt semantics.
pub struct Replica {
    config: ReplicaConfig,
    faults: Arc<dyn FaultInjector>,
}

impl Replica {
    /// Opens or creates a replica with production durability behavior.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid bounds/identity or directory creation/fsync failure.
    pub fn open(config: ReplicaConfig) -> Result<Self> {
        Self::open_with_faults(config, Arc::new(NoFaults))
    }

    /// Opens a replica with deterministic failure injection.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid bounds/identity or directory creation/fsync failure.
    pub fn open_with_faults(config: ReplicaConfig, faults: Arc<dyn FaultInjector>) -> Result<Self> {
        config.validate()?;
        fsutil::create_layout(&config.root, LAYOUT)?;
        Ok(Self { config, faults })
    }

    /// Returns the exact durable offset or completed ACK needed for client resume.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed durable state, wrong replica generation, integrity failure,
    /// or filesystem failure.
    pub fn resume_state(&self, expected: &SegmentClosure) -> Result<ResumeState> {
        if let Some(ack) = self.read_ack(&expected.segment_id)? {
            if ack.segment != *expected {
                return Ok(ResumeState::Conflict);
            }
            let path = self.find_ready(&expected.segment_id)?.ok_or_else(|| {
                SpoolError::Integrity(
                    "replica ACK exists but its exact ready bytes are absent".into(),
                )
            })?;
            let bytes = fsutil::read(&path)?;
            if let Err(error) = codec::verify_exact(&bytes, expected) {
                self.quarantine(&path, &error.to_string())?;
                return Err(error);
            }
            fsutil::sync_directory(&self.config.root.join("ready"))?;
            return Ok(ResumeState::Durable(ack));
        }
        if let Some(path) = self.find_ready(&expected.segment_id)? {
            let bytes = fsutil::read(&path)?;
            if let Err(error) = codec::verify_exact(&bytes, expected) {
                self.quarantine(&path, &error.to_string())?;
                return Err(error);
            }
            fsutil::sync_directory(&self.config.root.join("ready"))?;
            let ack = self.persist_ack(expected.clone())?;
            return Ok(ResumeState::Durable(ack));
        }
        if let Some(path) = self.find_partial(&expected.segment_id)? {
            if path != self.partial_path(expected) {
                return Ok(ResumeState::Conflict);
            }
            return Ok(ResumeState::Partial {
                durable_bytes: file_len(&path)?,
            });
        }
        Ok(ResumeState::Missing)
    }

    /// Applies one bounded chunk at an exact offset. Duplicate/overlapping retry bytes are accepted
    /// only when equal; forward gaps are refused. Completion returns an ACK only after verified
    /// ready bytes and the ACK itself have both crossed fsync/rename boundaries.
    ///
    /// # Errors
    ///
    /// Returns an error for bounds, offset/overlap conflict, exhausted disk, integrity failure,
    /// filesystem failure, or an injected durability fault.
    pub fn apply_chunk(&self, chunk: &TransferChunk) -> Result<Option<RemoteDurabilityAck>> {
        let total = chunk.closure.exact_segment.byte_len;
        if total == 0 || total > self.config.max_segment_bytes {
            return Err(SpoolError::BoundExceeded(
                "replica segment byte length".into(),
            ));
        }
        let chunk_len = u64::try_from(chunk.bytes.len())
            .map_err(|_| SpoolError::BoundExceeded("transfer chunk byte length".into()))?;
        if chunk_len == 0 || chunk_len > self.config.max_chunk_bytes {
            return Err(SpoolError::BoundExceeded(
                "transfer chunk byte length".into(),
            ));
        }
        let chunk_end = chunk
            .offset
            .checked_add(chunk_len)
            .ok_or_else(|| SpoolError::BoundExceeded("transfer chunk end".into()))?;
        if chunk_end > total {
            return Err(SpoolError::BoundExceeded(
                "transfer chunk exceeds segment closure".into(),
            ));
        }

        match self.resume_state(&chunk.closure)? {
            ResumeState::Durable(ack) => return Ok(Some(ack)),
            ResumeState::Conflict => {
                return Err(SpoolError::IdentityConflict(
                    chunk.closure.segment_id.clone(),
                ));
            }
            ResumeState::Missing | ResumeState::Partial { .. } => {}
        }

        let path = self.partial_path(&chunk.closure);
        let current = if path.exists() {
            fsutil::read(&path)?
        } else {
            Vec::new()
        };
        let durable_len = u64::try_from(current.len())
            .map_err(|_| SpoolError::BoundExceeded("partial byte length".into()))?;
        if chunk.offset > durable_len {
            return Err(SpoolError::TransferOffset {
                expected: durable_len,
                received: chunk.offset,
            });
        }
        let overlap_end = usize::try_from(durable_len.min(chunk_end).saturating_sub(chunk.offset))
            .map_err(|_| SpoolError::BoundExceeded("transfer overlap".into()))?;
        let start = usize::try_from(chunk.offset)
            .map_err(|_| SpoolError::BoundExceeded("transfer offset".into()))?;
        let current_overlap = current
            .get(start..start.saturating_add(overlap_end))
            .ok_or_else(|| SpoolError::Integrity("partial overlap is out of bounds".into()))?;
        if current_overlap != &chunk.bytes[..overlap_end] {
            return Err(SpoolError::Integrity(
                "retried transfer bytes differ from durable partial bytes".into(),
            ));
        }
        let suffix = &chunk.bytes[overlap_end..];
        if !suffix.is_empty() {
            let used = directory_bytes(&self.config.root)?;
            let after = used
                .checked_add(u64::try_from(suffix.len()).unwrap_or(u64::MAX))
                .ok_or_else(|| SpoolError::BoundExceeded("replica disk usage".into()))?;
            if after > self.config.max_total_bytes {
                return Err(SpoolError::Degraded(
                    "replica byte budget exhausted; surface a scoped transfer gap".into(),
                ));
            }
            fsutil::append_and_sync(&path, suffix)?;
            self.faults.check(FaultPoint::AfterPartialSync)?;
        }

        if file_len(&path)? < total {
            return Ok(None);
        }
        let complete = fsutil::read(&path)?;
        if let Err(error) = codec::verify_exact(&complete, &chunk.closure) {
            self.quarantine(&path, &error.to_string())?;
            return Err(error);
        }
        let ready = self.ready_path(&chunk.closure);
        fs::rename(&path, &ready).map_err(|error| SpoolError::io(&ready, error))?;
        self.faults.check(FaultPoint::AfterReplicaReadyRename)?;
        fsutil::sync_directory(&self.config.root.join("partial"))?;
        fsutil::sync_directory(&self.config.root.join("ready"))?;
        Ok(Some(self.persist_ack(chunk.closure.clone())?))
    }

    /// Current replica disk capacity.
    ///
    /// # Errors
    ///
    /// Returns an error when filesystem usage cannot be inspected or overflows.
    pub fn status(&self) -> Result<SpoolStatus> {
        let used_bytes = directory_bytes(&self.config.root)?;
        Ok(SpoolStatus {
            used_bytes,
            maximum_bytes: self.config.max_total_bytes,
            control_reserve_bytes: 0,
            degraded: used_bytes >= self.config.max_total_bytes,
        })
    }

    fn persist_ack(&self, segment: SegmentClosure) -> Result<RemoteDurabilityAck> {
        let ack = RemoteDurabilityAck::new(
            self.config.replica_id.clone(),
            self.config.generation.clone(),
            segment,
        );
        let bytes = serde_json::to_vec(&ack)?;
        let path = self.ack_path(&ack.segment.segment_id);
        if path.exists() {
            let existing: RemoteDurabilityAck = serde_json::from_slice(&fsutil::read(&path)?)?;
            return if existing == ack {
                Ok(existing)
            } else {
                Err(SpoolError::AckMismatch)
            };
        }
        fsutil::atomic_write(
            &path,
            &bytes,
            self.faults.as_ref(),
            FaultPoint::AfterAckTemporarySync,
            FaultPoint::AfterReadyRename,
        )?;
        Ok(ack)
    }

    fn read_ack(&self, id: &SegmentId) -> Result<Option<RemoteDurabilityAck>> {
        let path = self.ack_path(id);
        if path.exists() {
            fsutil::sync_directory(&self.config.root.join("acks"))?;
            let ack: RemoteDurabilityAck = serde_json::from_slice(&fsutil::read(&path)?)?;
            if ack.contract != crate::REMOTE_ACK_CONTRACT_VERSION
                || ack.replica_id != self.config.replica_id
                || ack.replica_generation != self.config.generation
            {
                return Err(SpoolError::AckMismatch);
            }
            Ok(Some(ack))
        } else {
            Ok(None)
        }
    }

    fn find_ready(&self, id: &SegmentId) -> Result<Option<PathBuf>> {
        find_one_by_prefix(&self.config.root.join("ready"), id, ".segment")
    }

    fn find_partial(&self, id: &SegmentId) -> Result<Option<PathBuf>> {
        find_one_by_prefix(&self.config.root.join("partial"), id, ".part")
    }

    fn partial_path(&self, closure: &SegmentClosure) -> PathBuf {
        self.config
            .root
            .join("partial")
            .join(closure_filename(closure, "part"))
    }

    fn ready_path(&self, closure: &SegmentClosure) -> PathBuf {
        self.config
            .root
            .join("ready")
            .join(closure_filename(closure, "segment"))
    }

    fn ack_path(&self, id: &SegmentId) -> PathBuf {
        self.config.root.join("acks").join(format!(
            "{}.{}.{}.json",
            model::stable_path_component(id.as_str()),
            model::stable_path_component(self.config.replica_id.as_str()),
            model::stable_path_component(&self.config.generation)
        ))
    }

    fn quarantine(&self, path: &Path, reason: &str) -> Result<()> {
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| SpoolError::Invalid("quarantine filename is not UTF-8".into()))?;
        let destination = self.config.root.join("quarantine").join(name);
        fs::rename(path, &destination).map_err(|error| SpoolError::io(&destination, error))?;
        fsutil::sync_directory(&self.config.root.join("quarantine"))?;
        let reason_path = self
            .config
            .root
            .join("quarantine")
            .join(format!("{name}.reason.json"));
        let bytes = serde_json::to_vec(&serde_json::json!({
            "contract": "joshi.spool.quarantine.v1",
            "reason": reason,
        }))?;
        fsutil::atomic_write(
            &reason_path,
            &bytes,
            &NoFaults,
            FaultPoint::AfterTemporarySync,
            FaultPoint::AfterReadyRename,
        )
    }
}

fn closure_filename(closure: &SegmentClosure, extension: &str) -> String {
    format!(
        "{}.{}.{}",
        model::stable_path_component(closure.segment_id.as_str()),
        closure.exact_segment.digest.replace(':', "-"),
        extension
    )
}

fn find_one_by_prefix(directory: &Path, id: &SegmentId, suffix: &str) -> Result<Option<PathBuf>> {
    let prefix = format!("{}.", model::stable_path_component(id.as_str()));
    let mut matches = fsutil::list_files(directory)?.into_iter().filter(|path| {
        path.file_name()
            .and_then(|value| value.to_str())
            .is_some_and(|name| name.starts_with(&prefix) && name.ends_with(suffix))
    });
    let first = matches.next();
    if matches.next().is_some() {
        return Err(SpoolError::IdentityConflict(id.clone()));
    }
    Ok(first)
}

fn file_len(path: &Path) -> Result<u64> {
    fs::metadata(path)
        .map(|metadata| metadata.len())
        .map_err(|error| SpoolError::io(path, error))
}
