//! Read-only, loss-aware acquisition adapters.
//!
//! This crate deliberately stops at raw observations and source-control facts. It has no
//! transaction-builder, signer, wallet, or submission dependency. Provider payloads remain exact
//! bytes; parsing is additive metadata and never replaces the evidence.

pub mod backoff;
pub mod config;
mod contract_port;
pub mod coverage;
pub mod evidence;
pub mod frame;
pub mod health;
pub mod helius;
pub mod ingress;
pub mod provider_plan;
pub mod pumpportal;
pub mod runner_port;
pub mod scope;
pub mod websocket;

pub use backoff::{Backoff, BackoffPolicy};
pub use config::{
    CredentialFile, HeliusConfig, PublicSolanaRpcConfig, PumpPortalConfig, SourceConfig,
};
pub use coverage::{CoverageEvent, CoverageState, CoverageTracker, Cursor, GapDisposition};
pub use evidence::{
    EvidenceAdapterError, EvidenceContext, LogicalSourceLocator, ProviderEventTime,
    RETAINED_FRAME_ENVELOPE_VERSION, RetainedFrameEnvelope, SourceEventLink, observation_draft,
};
pub use frame::{
    ContentType, FrameDirection, RawSourceFrame, SafeHeader, SourceId, StreamClass, Transport,
    UnixMillis,
};
pub use health::{HealthEvent, HealthSnapshot, HealthState, SourceHealth};
pub use helius::{
    HeliusControl, HeliusError, HeliusFrameKind, HeliusFrameMetadata, HeliusHttpClient,
    HeliusSubscription, HeliusWsAdapter, HeliusWsProtocol, PublicSolanaHttpClient, RateLimitSignal,
    SolanaReadMethod, SolanaReadRequest,
};
pub use ingress::{BoundedIngress, IngressError};
pub use provider_plan::{
    BuiltInExecutionDisposition, CanaryProfilePort, PROVIDER_RUN_PLAN_DIGEST_DOMAIN,
    PROVIDER_RUN_PLAN_PORT_VERSION, PROVIDER_RUN_PLAN_TEMPLATE_DIGEST_DOMAIN, ProviderOperation,
    ProviderOperationPlan, ProviderPlanError, ProviderRunPlan, ProviderRunPlanTemplate,
    ProviderScopePort, RegisteredRunPort, RuntimeAttemptCostPort, RuntimeBudgetPort,
    ValidatedProviderOperation, ValidatedProviderRunPlan, validate_provider_run_plan,
};
pub use pumpportal::{
    PumpPortalCommand, PumpPortalControl, PumpPortalFrameKind, PumpPortalFrameMetadata,
    PumpPortalMethod, PumpPortalSession, PumpPortalWsAdapter,
    classify_frame as classify_pumpportal_frame,
};
pub use runner_port::{
    ProviderAttemptAssociation, ProviderAttemptOutcome, ProviderAttemptPermit, ProviderAttemptPlan,
    ProviderAttemptReport, ProviderCompletionReason, ProviderRunner, ProviderRunnerCompletion,
    ProviderRunnerError, ProviderRunnerNext, SyntheticProviderRunner, SyntheticScenario,
    SyntheticStep,
};
pub use scope::{HotLease, LeaseKey, LeaseKind, ScopeBook, ScopeDelta};
pub use websocket::{
    FrameInterpretation, ProtocolError, SourceOutput, WebSocketBuildError, WebSocketCommand,
    WebSocketControlHandle, WebSocketEndpoint, WebSocketExit, WebSocketProtocol,
    WebSocketRunPolicy, WebSocketRunner,
};

/// Stable adapter contract version. This versions source behavior, not provider payload schemas.
pub const ADAPTER_CONTRACT_VERSION: &str = "joshi.sources.v1";
