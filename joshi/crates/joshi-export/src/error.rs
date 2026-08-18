use std::path::PathBuf;
use thiserror::Error;

/// Exact snapshot materialization failure.
#[derive(Debug, Error)]
pub enum ExportError {
    /// Snapshot input or manifest violates frozen V1 structure.
    #[error("invalid snapshot V1: {0}")]
    Invalid(String),
    /// Refuses replacement of an immutable destination.
    #[error("snapshot destination already exists: {0}")]
    DestinationExists(PathBuf),
    /// Filesystem operation failed.
    #[error("snapshot I/O failed at {path}: {source}")]
    Io {
        /// Affected path.
        path: PathBuf,
        /// Operating-system error.
        source: std::io::Error,
    },
    /// JSON encoding or decoding failed.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// Arrow contract or array operation failed.
    #[error(transparent)]
    Arrow(#[from] arrow_schema::ArrowError),
    /// Parquet read/write failed.
    #[error(transparent)]
    Parquet(#[from] parquet::errors::ParquetError),
    /// Read-only operational catalog access failed.
    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),
}

impl ExportError {
    pub(crate) fn io(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        Self::Io {
            path: path.into(),
            source,
        }
    }
}

/// Result specialized to snapshot materialization.
pub type Result<T> = std::result::Result<T, ExportError>;
