use crate::{FaultPoint, ProtectionDomainId, SegmentId};
use std::path::PathBuf;
use thiserror::Error;

/// Errors from the byte-durability boundary.
#[derive(Debug, Error)]
pub enum SpoolError {
    /// A stable identifier or timestamp was malformed.
    #[error("invalid protocol value: {0}")]
    Invalid(String),
    /// Serialization or envelope decoding failed.
    #[error("protocol serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    /// A filesystem operation failed.
    #[error("filesystem operation failed at {path}: {source}")]
    Io {
        /// Affected path.
        path: PathBuf,
        /// Original operating-system error.
        source: std::io::Error,
    },
    /// Exact bytes did not match their declared digest or length.
    #[error("integrity failure: {0}")]
    Integrity(String),
    /// An authenticated-private segment could not be opened.
    #[error("authenticated protection failed")]
    Authentication,
    /// The key required by a private segment was unavailable or mismatched.
    #[error("key {key_id} is unavailable for protection domain {domain}")]
    MissingKey {
        /// Non-secret key identifier.
        key_id: String,
        /// Protection domain.
        domain: ProtectionDomainId,
    },
    /// Reusing a nonce under the same key/domain was refused.
    #[error("nonce reuse refused for key {key_id} in protection domain {domain}")]
    NonceReuse {
        /// Non-secret key identifier.
        key_id: String,
        /// Protection domain.
        domain: ProtectionDomainId,
    },
    /// The same occurrence ID was presented with different bytes or closure.
    #[error("segment identity conflict for {0}")]
    IdentityConflict(SegmentId),
    /// The configured byte or entry bound was exceeded.
    #[error("configured bound exceeded: {0}")]
    BoundExceeded(String),
    /// Data admission would consume the control-record reserve.
    #[error("spool is degraded: {0}")]
    Degraded(String),
    /// A transfer chunk did not start at a resumable offset.
    #[error("transfer offset {received} does not match durable offset {expected}")]
    TransferOffset {
        /// Current durable partial length.
        expected: u64,
        /// Presented offset.
        received: u64,
    },
    /// A remote durability acknowledgement named the wrong replica generation or bytes.
    #[error("remote acknowledgement does not close the requested occurrence")]
    AckMismatch,
    /// A store receipt did not exactly close the retained batch.
    #[error("catalog receipt mismatch: {0}")]
    CatalogReceiptMismatch(String),
    /// A deterministic test fault interrupted a durability transition.
    #[error("injected failure at {0:?}")]
    Injected(FaultPoint),
}

impl SpoolError {
    pub(crate) fn io(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        Self::Io {
            path: path.into(),
            source,
        }
    }
}

/// Spool result type.
pub type Result<T> = std::result::Result<T, SpoolError>;
