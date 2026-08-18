//! Host-agnostic, append-only acquisition spool and resumable replica protocol.
//!
//! This crate owns byte durability only. It does not interpret evidence, advance source cursors,
//! mint catalog commit sequences, authorize disposal, or expose any signing/trading capability.

mod codec;
mod error;
mod fsutil;
mod model;
mod protection;
mod replica;
mod spool;

pub use codec::{decode_segment, encode_segment, inspect_segment};
pub use error::{Result, SpoolError};
pub use fsutil::{FaultInjector, FaultPoint, NoFaults};
pub use model::{
    AckKey, BatchClosure, ByteClosure, CatalogAdmissionAck, CursorCandidate, DeletionPhase,
    DeletionRecord, DiskSegment, EntryDescriptor, EvidenceBatchEntry, ExpectedCounts, GapRecord,
    ProtectionClass, ProtectionDomainId, ProtectionMetadata, ProtectionRequest,
    RemoteDurabilityAck, ReplicaId, RetentionRecord, SegmentClosure, SegmentHeader, SegmentId,
    SourceOccurrence, SpoolEntry, SpoolStatus, TransferChunk,
};
pub use protection::{KeyMaterial, SegmentProtector};
pub use replica::{Replica, ReplicaConfig, ResumeState};
pub use spool::{AppendOutcome, LocalSpool, SpoolConfig};

/// JSON-visible spool protocol contract.
pub const SPOOL_CONTRACT_VERSION: &str = "joshi.spool.segment.v1";

/// JSON-visible remote durability acknowledgement contract.
pub const REMOTE_ACK_CONTRACT_VERSION: &str = "joshi.spool.remote_ack.v1";

/// JSON-visible catalog admission acknowledgement contract.
pub const CATALOG_ACK_CONTRACT_VERSION: &str = "joshi.spool.catalog_ack.v1";
