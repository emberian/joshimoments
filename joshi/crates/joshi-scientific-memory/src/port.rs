//! Store adapter boundary for durable scientific-memory appends.
//!
//! This module deliberately defines no store implementation, receipt constructor, receipt parser,
//! or semantic-upgrade path. A public semantic caller can prepare exact occurrence bytes; the sole
//! private store owns receipt bytes and any separately authorized qualified-research view.

use std::error::Error;

use crate::{Digest, MemoryOccurrence, parse_memory_occurrence_exact};

/// Exact bytes presented to a store adapter for one idempotent append.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryStoreAppendRequestV1 {
    id: String,
    digest: Digest,
    bytes: Vec<u8>,
}

impl MemoryStoreAppendRequestV1 {
    /// Derives the exact append request from strict canonical occurrence bytes.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical occurrence bytes or a digest/identity mismatch.
    pub fn from_occurrence(occurrence: &MemoryOccurrence) -> Result<Self, String> {
        let occurrence_bytes = serde_json::to_vec(occurrence).map_err(|error| error.to_string())?;
        let parsed = parse_memory_occurrence_exact(&occurrence_bytes)?;
        let occurrence_id = parsed.occurrence_id();
        let occurrence_digest = parsed.exact_digest().map_err(|error| error.to_string())?;
        Ok(Self {
            id: occurrence_id,
            digest: occurrence_digest,
            bytes: occurrence_bytes,
        })
    }

    /// Exact append identity.
    #[must_use]
    pub fn occurrence_id(&self) -> &str {
        &self.id
    }

    /// SHA-256 digest of the exact occurrence bytes.
    #[must_use]
    pub fn occurrence_digest(&self) -> &Digest {
        &self.digest
    }

    /// Strict canonical occurrence bytes to fsync and read back exactly.
    #[must_use]
    pub fn occurrence_bytes(&self) -> &[u8] {
        &self.bytes
    }
}

/// Implementation boundary for the sole durable scientific-memory store authority.
///
/// A conforming store must fsync/readback `request.occurrence_bytes` and atomically retain a
/// *private* receipt under `MEMORY_STORE_RECEIPT_CONTRACT` with the exact occurrence ID/digest,
/// positive queue generation, store commit sequence, and run identity. That receipt is owned by
/// `joshi-store`, not deserialized or treated as an authority by this public semantic crate.
pub trait ScientificMemoryStorePort {
    /// Store-specific failure without wallet, transaction, fill, or economic authority.
    type Error: Error + Send + Sync + 'static;

    /// Fsyncs and read-verifies `request.occurrence_bytes` while retaining its private receipt.
    ///
    /// Success does not qualify, mutate, or upgrade a `MemoryKernel`; only the sole private store
    /// can use its receipt when it materializes a separately authorized research view.
    ///
    /// # Errors
    ///
    /// Returns the adapter's error when durable append, fsync, or readback fails.
    fn append_memory_occurrence(
        &mut self,
        request: &MemoryStoreAppendRequestV1,
    ) -> Result<(), Self::Error>;
}
