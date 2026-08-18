use thiserror::Error;

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum BakeoffError {
    #[error("invalid census bakeoff contract: {0}")]
    InvalidContract(&'static str),
    #[error("census bakeoff input is incomplete: {0}")]
    Incomplete(&'static str),
    #[error("conflicting duplicate signature")]
    ConflictingDuplicate,
    #[error("cost cap exceeded")]
    CostCapExceeded,
    #[error("invalid exact integer or arithmetic overflow")]
    Arithmetic,
    #[error("JSON encoding failed")]
    Json,
}

impl From<serde_json::Error> for BakeoffError {
    fn from(_: serde_json::Error) -> Self {
        Self::Json
    }
}
