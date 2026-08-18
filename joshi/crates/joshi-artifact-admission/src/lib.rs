//! Strict admission and independent readback for immutable derived-analysis artifacts.
//!
//! The only V2 family accepted for durable registration is a descriptive chart-shape transform
//! over an operational snapshot V2. The capability returned here carries no evidence, projection,
//! ranking, hot-scope, wallet, transaction, or execution authority.

mod error;
mod manifest;
mod readback;

pub use error::{ArtifactAdmissionError, Result};
pub use manifest::{
    ArtifactPartV1, DescriptiveChartShapeRowV2, StoreResolvedChartSamplesV1,
    StoreResolvedParquetPartV2, ValidatedDerivedArtifactV2, validate_derived_artifact_v2,
    validate_derived_artifact_v2_part,
};

/// Occurrence-bound operational derived artifact contract.
pub const DERIVED_ARTIFACT_CONTRACT_V2: &str = "joshi.analysis.derived-artifact/v2";
/// Only family initially eligible for production registration.
pub const DESCRIPTIVE_ARTIFACT_FAMILY: &str = "descriptive_chart_shape";
/// Literal authority ceiling.
pub const DERIVED_AUTHORITY: &str = "derived_analysis_read_only";
/// Literal presentation class.
pub const DISPLAY_CLASS: &str = "descriptive_noncausal";
/// Literal non-strategy claim carried by every accepted row.
pub const CLAIM_SCOPE: &str = "descriptive_only_not_predictive_or_strategy_claim";
