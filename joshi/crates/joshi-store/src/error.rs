use std::{io, path::PathBuf};
use thiserror::Error;

/// Result type for the durable store boundary.
pub type Result<T> = std::result::Result<T, StoreError>;

/// A fail-closed persistence or contract error.
#[derive(Debug, Error)]
pub enum StoreError {
    /// `SQLite` rejected an operation or reported a storage defect.
    #[error("SQLite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    /// Filesystem persistence or verification failed.
    #[error("filesystem error at {path}: {source}")]
    Io {
        /// Exact affected path.
        path: PathBuf,
        /// Original I/O error.
        source: io::Error,
    },
    /// JSON encoding or decoding failed at a durable boundary.
    #[error("JSON contract error: {0}")]
    Json(#[from] serde_json::Error),
    /// The linked `SQLite` runtime does not contain the required WAL fix.
    #[error("unsafe SQLite runtime {actual}; require at least 3.51.3")]
    UnsafeSqliteRuntime {
        /// Linked runtime version.
        actual: String,
    },
    /// Runtime PRAGMAs did not match the durability contract.
    #[error("SQLite runtime setting {setting} was {actual}, expected {expected}")]
    RuntimeSetting {
        /// Setting name.
        setting: &'static str,
        /// Observed value.
        actual: String,
        /// Required value.
        expected: &'static str,
    },
    /// The file belongs to another `SQLite` application.
    #[error("unexpected SQLite application_id {actual}")]
    ApplicationId {
        /// Existing application identifier.
        actual: i32,
    },
    /// An applied migration differs from this source tree.
    #[error("migration history conflict at {migration}: {detail}")]
    MigrationConflict {
        /// Migration file or ID.
        migration: String,
        /// Exact mismatch.
        detail: String,
    },
    /// A stable identity was retried with different immutable content.
    #[error("conflicting {kind} identity {identity}")]
    IdentityConflict {
        /// Identity family.
        kind: &'static str,
        /// Conflicting identity.
        identity: String,
    },
    /// A required relationship or supported discriminator is invalid.
    #[error("invalid durable batch: {0}")]
    InvalidBatch(String),
    /// A required referenced row does not exist at the commit boundary.
    #[error("missing {kind} identity {identity}")]
    MissingIdentity {
        /// Identity family.
        kind: &'static str,
        /// Missing identity.
        identity: String,
    },
    /// An algorithm-qualified digest is malformed or unsupported.
    #[error("invalid {kind} digest {value}")]
    InvalidDigest {
        /// Digest role.
        kind: &'static str,
        /// Rejected representation.
        value: String,
    },
    /// A stable wire integer cannot fit `SQLite`'s signed integer representation.
    #[error("{field} value {value} cannot be represented by SQLite")]
    IntegerRange {
        /// Field name.
        field: &'static str,
        /// Exact rejected value.
        value: String,
    },
    /// A timestamp cannot be represented as signed epoch microseconds.
    #[error("timestamp for {field} is outside the SQLite microsecond range")]
    TimestampRange {
        /// Timestamp field.
        field: &'static str,
    },
    /// Prepared bytes were changed, removed, or replaced before commit.
    #[error("prepared artifact verification failed at {path}: {detail}")]
    ArtifactVerification {
        /// Exact artifact path.
        path: PathBuf,
        /// Verification mismatch.
        detail: String,
    },
    /// Backup restore refuses to overwrite an existing destination.
    #[error("restore destination already exists: {0}")]
    RestoreDestinationExists(PathBuf),
    /// Another process or store instance owns the catalog's single-writer lease.
    #[error("catalog writer lease is already held: {0}")]
    WriterLeaseUnavailable(PathBuf),
    /// A deliberately injected test failure interrupted a durability phase.
    #[cfg(test)]
    #[error("injected failure at {0}")]
    Injected(&'static str),
}

impl StoreError {
    pub(crate) fn io(path: impl Into<PathBuf>, source: io::Error) -> Self {
        Self::Io {
            path: path.into(),
            source,
        }
    }
}
