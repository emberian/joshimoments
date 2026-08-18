use thiserror::Error;

/// Strict scene/command admission failure.
#[derive(Debug, Error)]
pub enum OperatorAdmissionError {
    /// Input is not strict JSON for the selected V1 wire contract.
    #[error("invalid {context} JSON: {source}")]
    Json {
        /// Contract being decoded.
        context: &'static str,
        /// Exact parser failure.
        source: serde_json::Error,
    },
    /// A field violates the frozen semantic contract.
    #[error("invalid {context}: {detail}")]
    Invalid {
        /// Contract field or relation.
        context: &'static str,
        /// Human-readable invariant.
        detail: String,
    },
    /// Parsed input is valid JSON but not the one canonical byte encoding.
    #[error("{contract} bytes are not their canonical V1 encoding")]
    NonCanonical {
        /// Wire contract discriminator.
        contract: &'static str,
    },
    /// Caller-supplied digest disagrees with exact canonical bytes.
    #[error("{contract} digest mismatch: expected {expected}, computed {computed}")]
    DigestMismatch {
        /// Wire contract discriminator.
        contract: &'static str,
        /// Caller-supplied qualified digest.
        expected: String,
        /// Server-computed qualified digest.
        computed: String,
    },
    /// A validated command names a different scene or view.
    #[error("operator command scene/view binding differs from the validated Glass view")]
    SceneBinding,
}

/// Result specialized to operator admission.
pub type Result<T> = std::result::Result<T, OperatorAdmissionError>;

pub(crate) fn json_error(
    context: &'static str,
) -> impl FnOnce(serde_json::Error) -> OperatorAdmissionError {
    move |source| OperatorAdmissionError::Json { context, source }
}

pub(crate) fn invalid(context: &'static str, detail: impl Into<String>) -> OperatorAdmissionError {
    OperatorAdmissionError::Invalid {
        context,
        detail: detail.into(),
    }
}
