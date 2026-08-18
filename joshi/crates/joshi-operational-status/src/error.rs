use thiserror::Error;

/// Operational contract or deterministic state-machine failure.
#[derive(Debug, Error)]
pub enum OperationalError {
    /// The caller supplied the wrong versioned contract literal.
    #[error("unexpected contract: expected {expected}, received {received}")]
    Contract {
        /// Required literal.
        expected: &'static str,
        /// Received literal.
        received: String,
    },
    /// A strict DTO violated a semantic invariant.
    #[error("invalid operational status: {0}")]
    Invalid(&'static str),
    /// A bounded collection or body exceeded its declared ceiling.
    #[error("operational bound exceeded for {field}: maximum {maximum}")]
    BoundExceeded {
        /// Bounded field.
        field: &'static str,
        /// Maximum permitted value.
        maximum: u64,
    },
    /// Strict JSON decoding failed.
    #[error("operational JSON decoding failed: {0}")]
    Json(#[from] serde_json::Error),
    /// A deterministic fault scenario's declared expected state did not match the harness.
    #[error("fault scenario expectation failed at step {step}: {field}")]
    FaultExpectation {
        /// Zero-based step.
        step: usize,
        /// Mismatched field.
        field: &'static str,
    },
}

/// Result alias for the operational status crate.
pub type Result<T> = std::result::Result<T, OperationalError>;
