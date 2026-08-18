//! Append-only evidence contracts and a bounded, offline single-writer catalog.
//!
//! The in-memory catalog is a fixture/replay seam, not the durable store. A later store crate can
//! implement the same append semantics without changing collector or query contracts.

mod catalog;
mod ingest;
mod model;

pub use catalog::{AppendStatus, CatalogError, CatalogSnapshot, CommitReceipt, InMemoryCatalog};
pub use ingest::{
    BoundedIngestHandle, BoundedIngestWorker, IngestError, IngestLimits, PendingAppend,
    bounded_ingest,
};
pub use model::{
    AcquisitionRecord, AssertionCommandEvidence, AssertionDraft, AssertionEvidence,
    AssertionRecord, AssertionSourceEvent, BlobRecord, BlobRef, Boundary, ChainLocation, Committed,
    CoverageGap, CoverageRecovery, CoverageScope, CoverageWindow, CursorAdvance,
    DurableIngestBatch, EventValidInterval, EvidenceDraft, EvidenceIdentity, MonotonicReading,
    ObservationDraft, ObservationEventTime, ObservationMetadata, ObservationRecord,
    ObservationSourceEvent, ObservationTiming, SourceEventRecord,
};

/// Version of the JSON-visible evidence envelope contract.
pub const EVIDENCE_CONTRACT_VERSION: &str = "joshi.evidence.v1";

/// Version tag included in canonical durable-ingest batch digest material.
pub const DURABLE_INGEST_BATCH_CONTRACT_VERSION: &str = "joshi.durable_ingest_batch.v1";
