use thiserror::Error;

/// A surface contract cannot be admitted or reduced.
#[derive(Debug, Error)]
pub enum SurfaceError {
    #[error("surface contract or schema mismatch")]
    Contract,
    #[error("surface profile has no surfaces")]
    EmptyProfile,
    #[error("surface profile contains duplicate surface id")]
    DuplicateSurface,
    #[error("surface profile contains duplicate task id")]
    DuplicateTask,
    #[error("critical surface lacks all accessibility task evidence")]
    CriticalAccessibility,
    #[error("critical surface is absent by design or not parity-capable")]
    CriticalParity,
    #[error("absent-by-design requires Ember approval and a reason")]
    AbsentByDesignApproval,
    #[error("public-chain alternative cannot satisfy product parity")]
    AlternativeNotParity,
    #[error("digest format is not sha256 lowercase hex")]
    DigestFormat,
    #[error("declared digest does not match canonical bytes")]
    DigestMismatch,
    #[error("point-in-time cutoff is invalid")]
    Cutoff,
    #[error("event is not admitted by the requested point-in-time cutoff")]
    FutureEvent,
    #[error("duplicate event identity has different bytes")]
    ConflictingEvent,
    #[error("membership is contradictory")]
    Membership,
    #[error("eligible universe is not closed")]
    UniverseNotClosed,
    #[error("hot scope lacks a closed control receipt")]
    HotControlClosure,
    #[error("hot scope lease interval or TTL is invalid")]
    HotLeaseInterval,
    #[error("hot scope is missing denominator or acquisition reservation")]
    HotLeaseEvidence,
    #[error("qualification acknowledgment is not bound to the exact build and session")]
    QualificationBinding,
    #[error("preliminary qualification requires one qualifying session")]
    PreliminaryQualification,
    #[error("repeated-use qualification requires independent qualifying sessions")]
    RepeatedQualification,
    #[error("JSON encoding failed")]
    Json(#[from] serde_json::Error),
}
