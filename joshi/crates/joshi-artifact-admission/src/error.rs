use std::path::PathBuf;

/// Fail-closed artifact admission defect.
#[derive(Debug, thiserror::Error)]
pub enum ArtifactAdmissionError {
    /// Contract, semantics, closure, or authority are invalid.
    #[error("invalid derived-analysis artifact: {0}")]
    Invalid(String),
    /// Immutable artifact bytes differ from their declaration.
    #[error("derived-analysis artifact digest mismatch: {0}")]
    Digest(String),
    /// Filesystem operation failed.
    #[error("derived-analysis artifact I/O failed at {path}: {source}")]
    Io {
        /// Affected path.
        path: PathBuf,
        /// Operating-system error.
        source: std::io::Error,
    },
    /// Strict JSON decoding failed.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// Arrow decoding failed.
    #[error(transparent)]
    Arrow(#[from] arrow_schema::ArrowError),
    /// Parquet decoding failed.
    #[error(transparent)]
    Parquet(#[from] parquet::errors::ParquetError),
}

impl ArtifactAdmissionError {
    pub(crate) fn io(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        Self::Io {
            path: path.into(),
            source,
        }
    }
}

/// Result specialized to artifact admission.
pub type Result<T> = std::result::Result<T, ArtifactAdmissionError>;
