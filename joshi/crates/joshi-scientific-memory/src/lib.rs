//! Append-only scientific memory for scenes, operator acts, episodes, and outcome replay.
//!
//! This crate is a pure semantic boundary. It does not render Glass, infer transactions/fills,
//! call a store, or access a wallet. An operator act is retained as an unverified semantic
//! occurrence before scene or presentation closure is available; only a private store adapter can
//! issue a durability receipt. Scene-qualified research admission is a separate predicate and
//! refuses without store qualification or presentation closure.

#![forbid(unsafe_code)]

mod kernel;
mod model;
mod port;

pub use kernel::{
    MemoryError, MemoryKernel, ResearchAdmission, ResearchRefusal, Transition, TransitionOutcome,
    UnverifiedSemanticAct,
};
pub use model::*;
pub use port::*;

/// Stable wire contract for this semantic family.
pub const MEMORY_CONTRACT: &str = "joshi.scientific_memory.v1";

/// Encoding rule for all positive logical session ticks in the semantic DTOs.
pub const MEMORY_TIME_ENCODING: &str = "positive canonical decimal-string LogicalSessionTick values from the session clock; not wall-clock milliseconds or nanoseconds";

/// Encoding and lineage for scene publication cuts.
pub const CATALOG_COMMIT_ENCODING: &str = "positive canonical decimal-string CatalogCommitSeq from the immutable scene catalog; never a session tick";

/// Store-owned receipt contract for a durably appended exact memory occurrence.
pub const MEMORY_STORE_RECEIPT_CONTRACT: &str = "joshi.store.scientific_memory_receipt.v1";

#[cfg(test)]
mod tests;
