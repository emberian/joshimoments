//! Registry-contract failures.

use thiserror::Error;

/// Result type for Wave 6 fixture registry validation.
pub type Result<T> = std::result::Result<T, RegistryError>;

/// Exact registration or registry validation failure.
#[derive(Debug, Error)]
pub enum RegistryError {
    /// JSON was malformed or could not be encoded.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// A stable identity or digest could not be represented.
    #[error("invalid stable identity: {0}")]
    Identity(String),
    /// Exact bytes differed from the sole canonical encoding.
    #[error("program registration bytes are not canonical compact JSON with one trailing newline")]
    NonCanonical,
    /// A digest did not use the algorithm-qualified SHA-256 representation.
    #[error("{field} must be sha256 followed by 64 lowercase hexadecimal digits")]
    DigestFormat {
        /// Field carrying the malformed digest.
        field: &'static str,
    },
    /// The self-declared registration digest did not close over its exact material.
    #[error("program registration digest mismatch")]
    DigestMismatch,
    /// The fixed fixture-only contract, authority, or ceiling was changed.
    #[error("program registration contract, authority, or semantic ceiling mismatch")]
    Authority,
    /// A canonical collection was empty, unsorted, duplicated, or otherwise incomplete.
    #[error("invalid canonical collection: {0}")]
    Collection(&'static str),
    /// An artifact kind or local symbol violated the fixture registry contract.
    #[error("invalid artifact or symbol contract: {0}")]
    Artifact(&'static str),
    /// A budget or data policy attempted to widen the fixture-only boundary.
    #[error("fixture-only budget or data policy violation: {0}")]
    Policy(&'static str),
    /// A mandatory forbidden capability was not explicitly frozen out.
    #[error("registration does not explicitly prohibit {0}")]
    MissingProhibition(&'static str),
    /// A claim did not use the exact rung-specific grammar registered for its artifact kind.
    #[error("claim language does not match its registered artifact kind and H0-H5 rung")]
    ClaimLanguage,
    /// An artifact DAG contained an unknown kind, duplicate, future edge, or broken reference.
    #[error("artifact DAG closure failure: {0}")]
    Dag(&'static str),
    /// A fixture decision branched, backdated, widened authority, or referenced unknown evidence.
    #[error("fixture decision ledger failure: {0}")]
    Decision(&'static str),
    /// A campaign lifecycle skipped, branched, backdated, or mutated frozen commitment.
    #[error("fixture campaign lifecycle failure: {0}")]
    Campaign(&'static str),
    /// A checked evaluation artifact violated its registered exact wire contract.
    #[error("fixture evaluation artifact failure: {0}")]
    Evaluation(&'static str),
}
