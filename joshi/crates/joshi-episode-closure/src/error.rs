use thiserror::Error;

#[derive(Debug, Error)]
pub enum ClosureError {
    #[error("invalid episode closure: {0}")]
    Invalid(String),
    #[error(transparent)]
    Admission(#[from] joshi_admission::AdmissionError),
    #[error(transparent)]
    StrictJson(#[from] joshi_admission::strict_json::StrictJsonError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

pub type Result<T> = std::result::Result<T, ClosureError>;
