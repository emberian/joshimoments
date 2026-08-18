use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum PairingError {
    #[error("origin must be an exact origin without path, credentials, query, or fragment")]
    InvalidOrigin,
    #[error("pairing epoch must advance on restart")]
    InvalidEpoch,
    #[error("pairing configuration is outside bounded limits")]
    InvalidConfig,
    #[error("pairing entropy source failed")]
    Entropy,
    #[error("pairing monotonic clock moved backwards")]
    ClockRollback,
    #[error("pairing entropy produced a duplicate active secret")]
    DuplicateSecret,
    #[error("pairing code is malformed")]
    MalformedSecret,
    #[error("pairing code is invalid, expired, revoked, or already consumed")]
    InvalidCode,
    #[error("pairing origin does not match the service origin")]
    OriginMismatch,
    #[error("pairing attempt/rate bound is exhausted")]
    RateLimited,
    #[error("pairing session is invalid, expired, revoked, or from an earlier restart epoch")]
    InvalidSession,
    #[error("pairing scope is not granted")]
    ScopeDenied,
    #[error("pairing identity is invalid")]
    Identity,
}
