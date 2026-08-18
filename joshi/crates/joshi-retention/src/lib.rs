//! Pure retention capability and transition kernel.
//!
//! This crate describes authenticated-private retention state across the origin spool, CAS,
//! replicas, exports, and derived references.  It accepts append-only occurrence facts and emits
//! deterministic eligibility/refusal reports.  It has no filesystem, key-management, transport,
//! or deletion-action API: a [`DeletionReceipt`] is an externally observed fact, not permission
//! to perform the corresponding operation.

#![forbid(unsafe_code)]

mod kernel;
mod model;

pub use kernel::{Kernel, KernelError, Transition, TransitionOutcome};
pub use model::{
    ByteFact, CompletionState, CoverageEffect, DeletionPhase, DeletionReceipt, DeletionRequest,
    DerivedReference, DomainId, ExportReference, Inventory, InventoryItem, InventoryKind,
    InventoryWitness, KeyState, Occurrence, OccurrenceId, ProtectionDomain, Refusal, Release,
    ReleaseId, ReleaseScope, ReplicaReference, RetentionReport, RetentionStatus, Tombstone,
    TombstoneId, parse_occurrence_exact,
};

/// JSON contract for the pure retention kernel.
pub const RETENTION_CONTRACT: &str = "joshi.retention.kernel.v1";

#[cfg(test)]
mod tests;
