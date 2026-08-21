//! Deterministic, append-only policy for promoting bounded census subjects into hot acquisition.
//!
//! This crate owns no source credential, store handle, live subscription, or economic action. It
//! reduces already-admitted intents and exact resource snapshots into auditable desired scope, and
//! adapts those records into inert collector-control bytes. A source adapter receipt is required
//! before an applied record may exist; applied never means provider acceptance or coverage.

mod control;
mod error;
mod hot_lease;
mod model;
mod policy;

pub use control::{
    CollectorControlAction, CollectorControlCommandV1, CollectorControlReceiptV1,
    CollectorControlReservationV1, ControlReservationExpectation, SupervisorProtectionProfileV1,
    adapt_supervisor_control_reservation, pending_control_commands, receipt_to_applied,
};
pub use error::PolicyError;
pub use hot_lease::{
    HOT_LEASE_AUTHORITY, HOT_LEASE_TERMS_CONTRACT, HotLeaseTermsV1,
    pressure_permits_hot_acquisition, promote_one,
};
pub use model::{
    ActivationAuthority, AsOfCutoff, BudgetEnvelope, CensusDenominatorRef, CensusKind,
    ChainNativeBudget, CollectorGeneration, DegradationChange, DegradationReason, EffectiveScope,
    EvidenceKind, EvidenceLink, Fidelity, HotScopeAppliedV1, HotScopeClosedV1, HotScopeDegradedV1,
    HotScopeDesiredV1, HotScopeIntentV1, HotScopeRecordV1, IntentReason, IntentReasonKind,
    MediaFidelity, OperatorAcceptanceBinding, PolicyConfigV1, PolicyDecisionV1, PolicyEvaluationV1,
    PolicyRecordHead, PresentationChoiceBinding, PressureStage, ProviderCurrencyBudget, RecordId,
    ResourceSnapshotV1, ScopePresence, ScopeSubject, SourceAvailability, SourceFamily,
    SourcePolicyV1, SourceScopeRequest, SubjectKind,
};
pub use policy::{PolicyJournal, evaluate};

/// Stable wire contract versions emitted by this crate.
pub const INTENT_CONTRACT: &str = "joshi.hot_scope_intent/v1";
pub const DESIRED_CONTRACT: &str = "joshi.hot_scope_desired/v1";
pub const APPLIED_CONTRACT: &str = "joshi.hot_scope_applied/v1";
pub const DEGRADED_CONTRACT: &str = "joshi.hot_scope_degraded/v1";
pub const CLOSED_CONTRACT: &str = "joshi.hot_scope_closed/v1";
pub const CONTROL_COMMAND_CONTRACT: &str = "joshi.collector_scope_control/v1";
pub const CONTROL_RECEIPT_CONTRACT: &str = "joshi.collector_scope_control_receipt/v1";

#[cfg(test)]
mod tests;
