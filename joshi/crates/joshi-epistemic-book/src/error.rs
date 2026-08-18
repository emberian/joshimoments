use thiserror::Error;

/// Fail-closed epistemic-contract error.
#[derive(Debug, Error)]
pub enum BookError {
    /// Contract, timing, closure, authority, or semantic validation failed.
    #[error("invalid epistemic-book artifact: {0}")]
    Invalid(String),
    /// Input bytes are valid JSON but not the one canonical representation.
    #[error("noncanonical epistemic-book bytes")]
    NonCanonical,
    /// Strict JSON decoding failed.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// A shared stable string or digest could not be constructed.
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
}

/// Result specialized to the pure epistemic-book boundary.
pub type Result<T> = std::result::Result<T, BookError>;
