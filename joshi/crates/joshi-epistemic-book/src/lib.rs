//! Pure, strict contracts for JOSHI's read-only epistemic position book.
//!
//! This crate owns no store, source, presentation, portfolio, wallet, transaction, signer, or
//! execution capability. It validates immutable semantic artifacts and exposes exact canonical
//! bytes for an integration-owned durable adapter.

#![forbid(unsafe_code)]

mod canonical;
mod ensemble;
mod error;
mod model;
mod score;
mod validate;

pub use canonical::{ValidatedArtifact, canonical_bytes, digest_bytes};
pub use ensemble::{
    assess_shadow_ensemble_semantics, evaluate_shadow_ensemble, validate_ensemble_artifact,
};
pub use error::{BookError, Result};
pub use model::*;
pub use score::{build_brier_score, preview_brier_score, validate_score_artifact};
pub use validate::{
    decode_adjudication, decode_claim_definition, decode_claim_occurrence,
    decode_forecast_submission, decode_score_artifact, decode_support_summary,
    validate_adjudication, validate_claim_definition, validate_claim_definition_supersession,
    validate_claim_occurrence, validate_forecast_submission, validate_revision,
    validate_revision_occurrence, validate_support_summary,
};

/// Stable semantic contracts emitted by this crate.
pub const CLAIM_DEFINITION_CONTRACT: &str = "joshi.epistemic.claim_definition/v1";
pub const CLAIM_OCCURRENCE_CONTRACT: &str = "joshi.epistemic.claim_occurrence/v1";
pub const FORECAST_SUBMISSION_CONTRACT: &str = "joshi.epistemic.forecast_submission/v1";
pub const ADJUDICATION_CONTRACT: &str = "joshi.epistemic.adjudication/v1";
pub const SCORE_ARTIFACT_CONTRACT: &str = "joshi.epistemic.proper_score/v1";
pub const SUPPORT_SUMMARY_CONTRACT: &str = "joshi.epistemic.support_calibration/v1";
pub const SHADOW_ENSEMBLE_CONTRACT: &str = "joshi.epistemic.shadow_ensemble/v1";
pub const SCHEMA_VERSION: u64 = 1;
pub const PROBABILITY_SCALE_PPM: u64 = 1_000_000;

#[cfg(test)]
mod tests;
