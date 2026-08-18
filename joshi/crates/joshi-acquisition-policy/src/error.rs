use thiserror::Error;

/// Refusal from strict policy validation or deterministic replay.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum PolicyError {
    #[error("invalid policy contract: {0}")]
    InvalidContract(String),
    #[error("invalid policy value: {0}")]
    InvalidValue(String),
    #[error("append-only journal violation: {0}")]
    Journal(String),
    #[error("budget arithmetic overflow")]
    BudgetOverflow,
    #[error("collector control receipt does not close its command: {0}")]
    ControlReceipt(String),
    #[error("JSON encoding failed: {0}")]
    Json(String),
}

impl From<serde_json::Error> for PolicyError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value.to_string())
    }
}
