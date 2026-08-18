//! Finite-cardinality operational status, pressure, recovery, and backfill contracts.
//!
//! The crate is a pure read-only control-plane library. It has no transport, store handle,
//! provider client, logger-as-evidence path, wallet capability, or economic action. Durable
//! receipts and evidence records are supplied by integration adapters and are never inferred from
//! metrics.

mod backfill;
mod error;
mod fault;
mod metrics;
mod model;
mod pressure;
mod query;
mod status;

pub use backfill::{
    BACKFILL_PLAN_CONTRACT, BACKFILL_RESULT_CONTRACT, BackfillFailureClass, BackfillLimitsV1,
    BackfillOutcomeV1, BackfillPlanRequestV1, BackfillPlanV1, BackfillResultV1, BackfillStrategyV1,
    CrossSourceProofV1, RecoveryProofV1, plan_backfill,
};
pub use error::{OperationalError, Result};
pub use fault::{
    FAULT_SCENARIO_CONTRACT, FaultActionV1, FaultExpectationV1, FaultHarnessReportV1,
    FaultHarnessStateV1, FaultKind, FaultScenarioV1, FaultStepV1, run_fault_scenario,
};
pub use metrics::{METRIC_BATCH_CONTRACT, MetricBatchV1, MetricSampleV1};
pub use model::{
    AUTHORITY_CEILING, ArtifactKind, ArtifactStatusV1, BackfillDisposition, BudgetKind, BudgetUnit,
    CapacityStatusV1, CatalogReceiptSummaryV1, CatalogStatusV1, Component, CoverageStatusV1,
    CursorKind, CursorScopeStatusV1, DegradationCause, DegradationStage, DegradationStatusV1,
    GapKind, GapStatusV1, HealthReadiness, MetricName, MetricUnit, OperationalBoundaryV1,
    OperationalHealthV1, QuarantineClass, QuarantineStatusV1, QueueStatusV1, QuotaBudgetV1,
    RecoveryState, ReplicaStatusV1, ResourceKind, ResourceStatusV1, SaturationStatusV1,
    SourceFamily, SourceGenerationState, SourceGenerationStatusV1, SpoolStatusV1, StatusClass,
    SupervisorPhase, SupervisorStatusV1,
};
pub use pressure::{
    DEGRADATION_POLICY_CONTRACT, DegradationDecisionV1, DegradationPolicyV1, DrainAssessment,
    RecoveryDrainWindowV1, assess_recovery_drain, evaluate_degradation,
};
pub use query::{
    HEALTH_CONTRACT, MAX_HEALTH_BYTES, MAX_QUERY_BYTES, MAX_QUERY_PAGE_SIZE,
    MAX_QUERY_RESULT_BYTES, OperationalDetailV1, OperationalStatusQueryResultV1,
    OperationalStatusQueryV1, QUERY_CONTRACT, QUERY_RESULT_CONTRACT, QueryTargetV1,
    decode_health_v1, decode_query_result_for_query_v1, decode_query_result_v1, decode_query_v1,
};
pub use status::{
    DURABLE_PROGRESS_CONTRACT, DegradationRecordV1, DurableProgressKind, DurableProgressState,
    DurableProgressV1, MAX_DURABLE_PROGRESS, MAX_RESOURCE_SAMPLES, MAX_STATUS_TRANSITIONS,
    OperationalQualificationV1, OperationalStatusViewV1, RESOURCE_SAMPLE_CONTRACT,
    RecoveryRecordV1, ResourceSampleV1, STATUS_TRANSITION_CONTRACT, STATUS_VIEW_CONTRACT,
    StatusJournal, StatusTransitionV1, TransitionHeadV1, UnverifiedDurableProgressV1,
    UnverifiedOperationalStatusViewV1, UnverifiedStatusJournal,
};
