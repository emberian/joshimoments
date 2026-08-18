//! Typed publication-contract failures.

use thiserror::Error;

/// Exact preparation, publication, head, receipt, or selection defect.
#[derive(Debug, Error)]
pub enum PublicationError {
    /// The nested financial projection is invalid.
    #[error(transparent)]
    Projection(#[from] joshi_projection::ProjectionError),
    /// JSON encoding or strict decoding failed.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// A stable identity could not be constructed.
    #[error("invalid publication identity: {0}")]
    Identity(String),
    /// A digest does not use the exact SHA-256 wire form.
    #[error("digest must be sha256 followed by 64 lowercase hexadecimal digits: {0}")]
    DigestFormat(String),
    /// A self-declared digest does not match recomputed exact bytes.
    #[error("{field} digest mismatch: declared {declared}, computed {computed}")]
    DigestMismatch {
        /// Semantic field whose digest failed.
        field: &'static str,
        /// Digest carried by the object.
        declared: String,
        /// Digest recomputed from exact material.
        computed: String,
    },
    /// A contract discriminator, schema, authority, or finality tag is not V1.
    #[error("publication contract, schema, authority, or finality mismatch")]
    Contract,
    /// Projection metadata differs across artifact, checkpoint, publication, or receipt.
    #[error("projection artifact/checkpoint/publication metadata mismatch")]
    ProjectionMismatch,
    /// Publication commit ordering or input cutoff is invalid.
    #[error("publication commit must follow its exact closed projection cutoff")]
    CommitOrder,
    /// Supersession identity or projection lineage does not match the prior immutable record.
    #[error("publication supersession lineage mismatch")]
    Supersession,
    /// The exact prepared artifact receipt does not match the bytes about to be committed.
    #[error("prepared artifact receipt does not match exact projection bytes")]
    PreparedArtifact,
    /// A durable receipt does not echo its immutable committed object exactly.
    #[error("durable publication receipt does not match its committed object")]
    ReceiptMismatch,
    /// An immutable query attempted to use a publication beyond its requested knowledge cutoff.
    #[error("publication is later than the requested knowledge cutoff")]
    LaterKnowledge,
    /// Conflicting candidates are absent, duplicated, unordered, or insufficient.
    #[error("conflicting publication candidates must be sorted, unique, and at least two")]
    ConflictCandidates,
    /// Selected publication does not match the explicit query identity/digest.
    #[error("loaded publication does not satisfy the exact immutable query")]
    QueryMismatch,
    /// Byte length cannot cross the canonical u64 wire boundary.
    #[error("artifact byte length exceeds the canonical u64 boundary")]
    ByteLength,
    #[error("cockpit V2 semantic manifest contract failure")]
    CockpitV2Contract,
    #[error("cockpit V2 typed reference closure failure")]
    CockpitV2Reference,
    #[error("private or authenticated bytes are forbidden in a public cockpit artifact")]
    CockpitV2PrivateBytes,
    #[error("cockpit V2 reference is later than its exact cutoff")]
    CockpitV2Cutoff,
    #[error("cockpit V2 references are not sorted and duplicate-free")]
    CockpitV2Ordering,
    #[error("cockpit V2 digest closure failure")]
    CockpitV2Digest,
    #[error("cockpit V2 commit/head transition failure")]
    CockpitV2Stage,
}
