//! Point-in-time attention and social-topology contracts.
//!
//! This crate keeps provider observations, versioned identity/topology assertions, marked
//! attention events, and response-study rows separate. A callout is an input to a response
//! process, not a treatment indicator or a claim that the caller caused a later move.

#![forbid(unsafe_code)]

mod id;
mod model;
mod validate;
mod wire;

pub use id::{
    AttentionEventId, AttentionInputId, ClusterContextId, CohortRowId, CommunityId,
    IdentityVersionId, KernelEventId, RevisionId, SubjectId, TerritorySnapshotId,
    WalletClusterHypothesisId,
};
pub use model::*;
pub use validate::{AttentionValidationError, ValidationCode};
pub use wire::{JsonNumberLexeme, SignedWireI64};

/// JSON-visible contract for an attention dataset and its response-study tables.
pub const ATTENTION_CONTRACT: &str = "joshi.attention.dataset.v1";
