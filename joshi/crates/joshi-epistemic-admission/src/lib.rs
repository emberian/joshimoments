//! Receipt-gated semantic-admission boundary for the epistemic position book.
//!
//! This crate deliberately has no store writer. Public callers can validate caller-owned
//! semantic objects as [`UnverifiedSemantic`], but cannot produce a durable occurrence, sealed
//! first-round submission, adjudication, score, or ensemble. Those admissions require the
//! private store adapter described in `docs/implementation/wave5/14_EPISTEMIC_ADMISSION.md`.
//!
//! No API in this crate may influence acquisition, retrieval, presentation, execution, asset
//! reservation, transaction construction, signing, or submission.

#![forbid(unsafe_code)]

mod error;
mod port;
mod preflight;

pub use error::{EpistemicAdmissionError, Result};
pub use port::{
    AdjudicationReceiptSet, CapabilityClosureReceipt, CutoffReceipt, EvidenceClosureReceipt,
    FirstRoundSealReceipt, OccurrenceCommitReceipt, SceneReceipt, SealedNamespaceReceipt,
    StoreResolvedAdjudication, StoreResolvedClaimOccurrence, StoreResolvedFirstRoundSubmission,
    StoreResolvedScore, StoreResolvedShadowEnsemble, StoreResolvedSupport, SubmissionCommitReceipt,
    SupportLineageReceipt, UniverseReceipt, VisibilityReceipt,
};
pub use preflight::{
    ClaimOccurrencePreflight, FirstRoundSubmissionPreflight, UnverifiedSemantic,
    preflight_claim_occurrence, preflight_first_round_submission,
};

#[cfg(test)]
mod tests;
