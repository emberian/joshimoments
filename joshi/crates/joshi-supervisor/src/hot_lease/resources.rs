//! Exact resource readings taken from this machine, this filesystem, and this process.
//!
//! Every number the acquisition policy reduces into a pressure stage is read here from something
//! that actually exists: `statvfs` on the filesystem that will hold the retained bytes, the sizes
//! and modification times of the files already retained under the run root today, and the live
//! occupancy of the bounded ingress channel the lease will read through. Nothing is estimated and
//! nothing is defaulted; a dimension that cannot be read is an error, never a permissive number.

use std::{
    fs,
    path::{Path, PathBuf},
    time::SystemTime,
};

use joshi_acquisition_policy::{EvidenceKind, EvidenceLink, ResourceSnapshotV1};
use joshi_domain::{StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};

use crate::{Result, SupervisorError};

/// Stable wire contract for one exact resource measurement occurrence.
pub const RESOURCE_MEASUREMENT_CONTRACT: &str = "joshi.supervisor.resource_measurement/v1";

/// Declared ceilings the measurement is compared against. These are policy, not readings, and are
/// recorded next to the readings so a replay can tell the two apart.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceCeilings {
    /// Free bytes at or below which hot acquisition stops before reserving anything further.
    pub disk_floor_bytes: u64,
    /// Bytes of headroom above the floor that must remain for control-plane writes.
    pub control_reserve_required_bytes: u64,
    /// Bytes this installation may retain under the run root in one UTC day.
    pub max_retained_bytes_per_utc_day: u64,
    /// Records the bounded source ingress channel may hold.
    pub ingress_record_capacity: u64,
    /// Records within that capacity held back for control frames.
    pub ingress_record_control_reserve: u64,
    /// Bytes the in-process retention buffer may hold before a lease must stop reading.
    pub retention_buffer_byte_capacity: u64,
    /// Bytes within that buffer held back for control frames.
    pub retention_buffer_byte_control_reserve: u64,
}

impl ResourceCeilings {
    /// Ceilings for one bounded local hot lease on a workstation-class filesystem.
    ///
    /// The daily retention ceiling is deliberately of the same order as the only high-fidelity
    /// capture this project has ever taken: 11,943,303 bytes in 5.979 seconds on 2026-08-16.
    #[must_use]
    pub const fn local_workstation(ingress_record_capacity: u64) -> Self {
        Self {
            disk_floor_bytes: 4 * 1024 * 1024 * 1024,
            control_reserve_required_bytes: 256 * 1024 * 1024,
            max_retained_bytes_per_utc_day: 2 * 1024 * 1024 * 1024,
            ingress_record_capacity,
            ingress_record_control_reserve: 64,
            retention_buffer_byte_capacity: 256 * 1024 * 1024,
            retention_buffer_byte_control_reserve: 1024 * 1024,
        }
    }
}

/// One exact resource measurement occurrence, retained as its own artifact so the pressure stage
/// a lease ran under can be recomputed from bytes rather than trusted.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceMeasurementV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub sampled_at: UtcTimestamp,
    pub ceilings: ResourceCeilings,
    /// Filesystem the retained bytes will land on.
    pub measured_path: String,
    /// `statvfs` fragment size on that filesystem.
    pub statvfs_fragment_bytes: WireU64,
    /// `statvfs` blocks available to an unprivileged writer on that filesystem.
    pub statvfs_blocks_available: WireU64,
    /// `statvfs_fragment_bytes * statvfs_blocks_available`.
    pub disk_free_bytes: WireU64,
    /// Regular files under the run root whose modification time falls on the sampled UTC day.
    pub retained_files_today: WireU64,
    /// Exact byte sum of those files.
    pub retained_bytes_today: WireU64,
    /// Records currently queued in the bounded source ingress channel.
    pub ingress_records_used: WireU64,
    /// Bytes currently held in the in-process retention buffer.
    pub retention_buffer_bytes_used: WireU64,
}

impl ResourceMeasurementV1 {
    /// Canonical bytes of this measurement, used as its own content address.
    ///
    /// # Errors
    ///
    /// Returns an error when the measurement cannot be serialized.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>> {
        Ok(serde_json::to_vec(self)?)
    }

    /// Content address of the exact measurement bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the measurement cannot be serialized.
    pub fn digest(&self) -> Result<String> {
        let mut hasher = Sha256::new();
        hasher.update(self.canonical_bytes()?);
        Ok(format!("sha256:{:x}", hasher.finalize()))
    }

    /// Reduce the readings into the exact snapshot the acquisition policy consumes.
    ///
    /// The one evidence link names this measurement by its own content address, so a replay can
    /// re-derive every counter in the snapshot from retained bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the measurement cannot be serialized or a wire value is invalid.
    pub fn snapshot(&self) -> Result<ResourceSnapshotV1> {
        let digest = self.digest()?;
        let evidence = EvidenceLink {
            kind: EvidenceKind::Artifact,
            id: StableString::new(format!("resource-measurement:{digest}"))?,
            digest: Some(joshi_domain::ValueDigest::new(digest)?),
            available_at: self.sampled_at,
            commit_seq: None,
        };
        let free = self.disk_free_bytes.get();
        Ok(ResourceSnapshotV1 {
            sampled_at: self.sampled_at,
            evidence: vec![evidence],
            queue_records_used: self.ingress_records_used,
            queue_record_capacity: WireU64::new(self.ceilings.ingress_record_capacity),
            queue_record_control_reserve: WireU64::new(
                self.ceilings.ingress_record_control_reserve,
            ),
            queue_bytes_used: self.retention_buffer_bytes_used,
            queue_byte_capacity: WireU64::new(self.ceilings.retention_buffer_byte_capacity),
            queue_byte_control_reserve: WireU64::new(
                self.ceilings.retention_buffer_byte_control_reserve,
            ),
            spool_bytes_today: self.retained_bytes_today,
            max_spool_bytes_today: WireU64::new(self.ceilings.max_retained_bytes_per_utc_day),
            disk_free_bytes: self.disk_free_bytes,
            disk_floor_bytes: WireU64::new(self.ceilings.disk_floor_bytes),
            // Headroom above the floor is what a control write can actually consume; the floor
            // itself is not available to anyone.
            control_reserve_free_bytes: WireU64::new(
                free.saturating_sub(self.ceilings.disk_floor_bytes),
            ),
            control_reserve_required_bytes: WireU64::new(
                self.ceilings.control_reserve_required_bytes,
            ),
        })
    }
}

/// Live occupancy of the bounded ingress the lease will read through.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IngressOccupancy {
    pub records_used: u64,
    pub buffer_bytes_used: u64,
}

/// Take one exact resource measurement over the filesystem holding `run_root`.
///
/// # Errors
///
/// Returns an error when `statvfs` fails, the run root cannot be walked, a file size or clock is
/// outside the representable range, or a ceiling is internally inconsistent.
pub fn measure(
    run_root: &Path,
    ceilings: ResourceCeilings,
    ingress: IngressOccupancy,
    sampled_at: UtcTimestamp,
) -> Result<ResourceMeasurementV1> {
    if ceilings.ingress_record_control_reserve >= ceilings.ingress_record_capacity
        || ceilings.retention_buffer_byte_control_reserve >= ceilings.retention_buffer_byte_capacity
        || ceilings.max_retained_bytes_per_utc_day == 0
    {
        return Err(SupervisorError::InvalidConfig(
            "resource ceilings must leave a strictly smaller protected control reserve".into(),
        ));
    }
    fs::create_dir_all(run_root).map_err(|error| SupervisorError::io(run_root, error))?;
    let statistics = rustix::fs::statvfs(run_root)
        .map_err(|error| SupervisorError::io(run_root, std::io::Error::from(error)))?;
    let fragment = statistics.f_frsize;
    let available = statistics.f_bavail;
    let free = fragment.checked_mul(available).ok_or_else(|| {
        SupervisorError::InvalidValue("filesystem free-byte product overflowed".into())
    })?;
    let (files_today, bytes_today) = retained_today(run_root, sampled_at)?;
    Ok(ResourceMeasurementV1 {
        contract: StableString::new(RESOURCE_MEASUREMENT_CONTRACT)?,
        schema_version: WireU64::new(1),
        sampled_at,
        ceilings,
        measured_path: run_root.display().to_string(),
        statvfs_fragment_bytes: WireU64::new(fragment),
        statvfs_blocks_available: WireU64::new(available),
        disk_free_bytes: WireU64::new(free),
        retained_files_today: WireU64::new(files_today),
        retained_bytes_today: WireU64::new(bytes_today),
        ingress_records_used: WireU64::new(ingress.records_used),
        retention_buffer_bytes_used: WireU64::new(ingress.buffer_bytes_used),
    })
}

/// Exact file count and byte sum under `root` for the UTC day of `sampled_at`.
fn retained_today(root: &Path, sampled_at: UtcTimestamp) -> Result<(u64, u64)> {
    let day = sampled_at.as_datetime().date();
    let mut pending: Vec<PathBuf> = vec![root.to_path_buf()];
    let mut files = 0_u64;
    let mut bytes = 0_u64;
    while let Some(directory) = pending.pop() {
        let entries =
            fs::read_dir(&directory).map_err(|error| SupervisorError::io(&directory, error))?;
        for entry in entries {
            let entry = entry.map_err(|error| SupervisorError::io(&directory, error))?;
            let path = entry.path();
            let metadata =
                fs::symlink_metadata(&path).map_err(|error| SupervisorError::io(&path, error))?;
            if metadata.is_dir() {
                pending.push(path);
                continue;
            }
            if !metadata.is_file() {
                // Symlinks and devices retain nothing of their own under this root.
                continue;
            }
            let modified = metadata
                .modified()
                .map_err(|error| SupervisorError::io(&path, error))?;
            if utc_date(modified)? != day {
                continue;
            }
            files = files.saturating_add(1);
            bytes = bytes.checked_add(metadata.len()).ok_or_else(|| {
                SupervisorError::InvalidValue("retained byte sum overflowed".into())
            })?;
        }
    }
    Ok((files, bytes))
}

fn utc_date(value: SystemTime) -> Result<time::Date> {
    let offset = value.duration_since(SystemTime::UNIX_EPOCH).map_err(|_| {
        SupervisorError::InvalidValue("file modification time precedes 1970".into())
    })?;
    let seconds = i64::try_from(offset.as_secs()).map_err(|_| {
        SupervisorError::InvalidValue(
            "file modification time is outside the supported range".into(),
        )
    })?;
    time::OffsetDateTime::from_unix_timestamp(seconds)
        .map(time::OffsetDateTime::date)
        .map_err(|_| {
            SupervisorError::InvalidValue(
                "file modification time is outside the supported range".into(),
            )
        })
}
