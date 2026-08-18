use std::path::PathBuf;

/// Supervisor error. Messages must remain diagnostic and must never contain provider credentials
/// or response bodies.
#[derive(Debug, thiserror::Error)]
pub enum SupervisorError {
    #[error("supervisor configuration is invalid: {0}")]
    InvalidConfig(String),
    #[error("supervisor protocol value is invalid: {0}")]
    InvalidValue(String),
    #[error("supervisor state transition is invalid: {0}")]
    InvalidState(String),
    #[error("supervisor journal is corrupt: {0}")]
    CorruptJournal(String),
    #[error("another supervisor process owns {0}")]
    AlreadyRunning(PathBuf),
    #[error("filesystem operation failed at {path}: {source}")]
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("supervisor serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("spool boundary failed: {0}")]
    Spool(#[from] joshi_spool::SpoolError),
    #[error("domain wire value failed: {0}")]
    Wire(#[from] joshi_domain::WireStringError),
    #[error("source evidence adapter failed: {0}")]
    SourceEvidence(#[from] joshi_sources::EvidenceAdapterError),
    #[error("strict operational receipt failed: {0}")]
    Admission(#[from] joshi_admission::AdmissionError),
    #[error("receipt digest failed: {0}")]
    Digest(#[from] joshi_admission::DigestError),
    #[error("injected supervisor failure at {0:?}")]
    Injected(crate::FaultPoint),
    #[error("catalog sink refused exact evidence: {0}")]
    Catalog(String),
    #[error(
        "UTC-day spool budget exceeded for {day}: {used} used + {incoming} incoming > {maximum}"
    )]
    DailySpoolBudget {
        day: String,
        used: u64,
        incoming: u64,
        maximum: u64,
    },
    #[error("run budget is exhausted for {dimension:?}")]
    RunBudgetExhausted { dimension: crate::BudgetDimension },
    #[error("provider use exceeded its pre-I/O attempt budget")]
    AttemptBudgetExceeded,
    #[error("provider runner boundary failed: {0}")]
    ProviderRunner(#[from] joshi_sources::ProviderRunnerError),
    #[error("provider plan boundary failed: {0}")]
    ProviderPlan(#[from] joshi_sources::ProviderPlanError),
    #[error("provider execution is disabled pending canonical registry admission")]
    ProviderDisabledPendingCanonicalAdmission,
}

impl SupervisorError {
    pub(crate) fn io(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        Self::Io {
            path: path.into(),
            source,
        }
    }
}

pub type Result<T> = std::result::Result<T, SupervisorError>;
