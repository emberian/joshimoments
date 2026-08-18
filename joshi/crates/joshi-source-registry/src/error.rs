use thiserror::Error;

/// Strict refusal from source or budget validation. Error text never contains credentials.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum RegistryError {
    #[error("invalid source registry contract: {0}")]
    InvalidContract(&'static str),
    #[error("invalid source registry value: {0}")]
    InvalidValue(&'static str),
    #[error("duplicate source identity")]
    DuplicateSource,
    #[error("duplicate method identity")]
    DuplicateMethod,
    #[error("duplicate field identity")]
    DuplicateField,
    #[error("source fingerprint does not match canonical contract")]
    FingerprintMismatch,
    #[error("wallet-bearing credential authority is not admitted to read-only collection")]
    WalletBearingCredential,
    #[error("zero-priced access is not evidence of unauthenticated access")]
    ZeroPriceNotUnauthenticated,
    #[error("budget dimension exceeds its hard cap")]
    BudgetExceeded,
    #[error("budget reservation is not bounded")]
    UnboundedReservation,
    #[error("budget reservation does not match this run")]
    ReservationMismatch,
    #[error("budget usage cannot be represented")]
    ArithmeticOverflow,
    #[error("kill switch is active")]
    KillSwitched,
    #[error("source is not enabled")]
    SourceDisabled,
    #[error("unsupported source-specific absence or progress semantics")]
    InvalidSemantics,
    #[error("JSON encoding failed")]
    Json,
}

impl From<serde_json::Error> for RegistryError {
    fn from(_: serde_json::Error) -> Self {
        Self::Json
    }
}
