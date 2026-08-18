//! Durable, bounded supervision around Joshi's read-only source and spool contracts.
//!
//! This crate owns occurrence reservation, source-generation state, explicit retry decisions,
//! queue pressure, local spool transport, recovery, and offline replay. It has no provider client,
//! listener, catalog write handle, wallet authority, or transaction capability.

mod budget;
mod error;
mod harness;
mod journal;
mod model;
mod queue;
mod replay;
mod runtime;
mod runtime_config;
mod supervisor;
mod transport;

pub use error::{Result, SupervisorError};
pub use harness::{FakeProviderHarness, FakeProviderReport, FakeProviderSchedule};
pub use joshi_admission::operational::{LocalSpoolReceiptV1, SpoolCatalogReceiptV1};
pub use journal::{FaultInjector, FaultPoint, NoFaults};
pub use model::{
    AttemptKind, AttemptReservation, CollectorLifecycle, DurableOutcome, GenerationId,
    JournalEvent, JournalRecord, OperationKey, PendingSegment, ProtectionProfile,
    ProviderPlanReferenceV1, QueueClass, QueueLimits, ReservationId, ReservationRequest,
    RetryDecision, RetryPolicy, RetryTrigger, RuntimeSettlementDisposition, ShutdownReport,
    SourceKey, SourceRuntimeHealth, SupervisorConfig, SupervisorHealthV1,
};
pub use replay::{ReplayManifest, ReplaySegment, replay_spool};
pub use supervisor::Supervisor;
pub use transport::{
    CatalogDrainReport, CatalogSink, CatalogTransport, ReplicaDrainReport, ReplicaTransport,
    SourceIngressError, SourceOutputAdapter, prepare_evidence_batch,
};

/// Durable journal and health contract version.
pub const SUPERVISOR_CONTRACT_VERSION: &str = "joshi.supervisor.v1";

/// Offline replay manifest contract version.
pub const REPLAY_CONTRACT_VERSION: &str = "joshi.supervisor.replay.v1";

/// Literal authority ceiling for every runtime artifact in this crate.
pub const AUTHORITY_CEILING: &str = "read_only_no_execution";
pub use budget::{
    AttemptBudgetClaim, AttemptBudgetUsage, BudgetDimension, BudgetLedger, BudgetPermit,
    BudgetPermitId, BudgetSnapshot, RunBudgetLimits,
};
pub use joshi_sources::{
    ProviderAttemptOutcome, ProviderOperationPlan, ProviderRunPlan, ProviderRunner,
    ProviderRunnerNext, SyntheticProviderRunner, SyntheticScenario, SyntheticStep,
    ValidatedProviderRunPlan, validate_provider_run_plan,
};
pub use runtime::{
    CollectorRuntime, RuntimeProgressKind, RuntimeRunReport, RuntimeStepReport,
    SyntheticRuntimeOutcomeAdapter, synthetic_c0_json_runner,
};
pub use runtime_config::{
    CanonicalCollectorRuntimeConfigV1 as CollectorRuntimeConfigV1,
    CanonicalExecutionAccountingDocumentV1 as ExecutionAccountingDocumentV1, LocalStatusEndpoint,
    ProviderExecutionMode, RuntimeDocumentSet,
};
