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
pub mod pda;
pub mod provider_plan;
pub mod pump_swap;
pub mod pumpportal;
pub mod runner_port;
pub mod scope;
pub mod solana_account;
pub mod solana_json_rpc;
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
    DEFAULT_MAX_RESPONSE_BYTES, HeliusControl, HeliusError, HeliusFrameKind, HeliusFrameMetadata,
    HeliusHttpClient, HeliusSubscription, HeliusWsAdapter, HeliusWsProtocol,
    PublicSolanaHttpClient, RateLimitSignal, SolanaReadMethod, SolanaReadRequest,
};
pub use ingress::{BoundedIngress, IngressError};
pub use pda::{
    MAX_SEED_LEN, MAX_SEEDS, PROGRAM_DERIVED_ADDRESS_MARKER, decode_address,
    derivation_bump as program_derivation_bump, derive_program_address, descending_bump_candidates,
};
pub use provider_plan::{
    BuiltInExecutionDisposition, CanaryProfilePort, MAX_PROVIDER_RUN_PLAN_BYTES,
    PROVIDER_RUN_PLAN_DIGEST_DOMAIN, PROVIDER_RUN_PLAN_PORT_VERSION,
    PROVIDER_RUN_PLAN_TEMPLATE_DIGEST_DOMAIN, PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT,
    PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT, ProviderOperation, ProviderOperationPlan,
    ProviderPlanError, ProviderRunPlan, ProviderRunPlanTemplate, ProviderScopePort,
    RegisteredRunPort, RuntimeAttemptCostPort, RuntimeBudgetPort,
    SEALED_C0_METHOD_SCHEMA_FINGERPRINT, SEALED_C0_SOURCE_CONTRACT_FINGERPRINT,
    ValidatedProviderOperation, ValidatedProviderRunPlan, parse_provider_run_plan_exact,
    validate_provider_run_plan,
};
pub use pump_swap::{
    BONDING_CURVE_CORE_LEN, BONDING_CURVE_CREATOR_OFFSET, BONDING_CURVE_LOCATED_LEN,
    BONDING_CURVE_SEED, BONDING_CURVE_UNNAMED_BYTES_RANGE, BONDING_CURVE_UNNAMED_PUBKEY_RANGE,
    BONDING_CURVE_WITH_CREATOR_LEN, FEE_CONFIG_ACCOUNT_LEN, FEE_CONFIG_SEED, FeeRatesBps,
    FeeTierRow, GLOBAL_ACCOUNT_LEN, GLOBAL_NAMED_LEN, GLOBAL_SEED, POOL_ACCOUNT_LEN,
    POOL_NAMED_LEN, POOL_REQUIRED_ZERO_RANGES, POOL_SEED, POOL_UNATTRIBUTED_QUOTE_SIDE_LEN,
    POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET, POOL_UNNAMED_BYTE_OFFSET, PUMP_AMM_PROGRAM_ID,
    PUMP_BONDING_CURVE_PROGRAM_ID, PUMP_CURVE_FEE_CONFIG_ADDRESS, PUMP_FEE_CONFIG_ADDRESS,
    PUMP_FEE_PROGRAM_ID, PUMP_GLOBAL_ADDRESS, PumpBondingCurve, PumpDecodeError, PumpFeeConfig,
    PumpGlobal, PumpSwapPool, SPL_TOKEN_2022_PROGRAM_ID, SPL_TOKEN_PROGRAM_ID, TokenExtension,
    TokenMint, TokenVault, WRAPPED_SOL_MINT, anchor_account_discriminator,
    bonding_curve_candidates, bonding_curve_derivation_bump, fee_config_derivation_bump,
    global_derivation_bump,
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
pub use solana_account::{
    AccountEntry, AccountResponseError, AccountSetResponse, BlockClock, RetainedAccount,
    read_account_info, read_block_clock, read_multiple_accounts,
};
pub use solana_json_rpc::{
    CanonicalSolanaRequest, INGEST_MAX_RESPONSE_BYTES, JsonRpcRefusal, RawSignaturePage,
    RawSignatureRow, SOLANA_JSON_RPC_ID, SOLANA_JSON_RPC_MAX_REQUEST_BYTES,
    SOLANA_JSON_RPC_VERSION, SOLANA_SIGNATURES_COMMITMENT, SOLANA_SIGNATURES_MAX_ROWS,
    SOLANA_SIGNATURES_METHOD, SOLANA_SIGNATURES_MIN_ROWS, SolanaJsonRpcConformanceError,
    SolanaJsonRpcOutcome, SolanaRequestError, canonical_solana_signatures_request,
    read_solana_json_rpc_body, read_solana_json_rpc_frame, solana_safe_headers_are_bounded,
};
pub use websocket::{
    FrameInterpretation, ProtocolError, SourceOutput, WebSocketBuildError, WebSocketCommand,
    WebSocketControlHandle, WebSocketEndpoint, WebSocketExit, WebSocketProtocol,
    WebSocketRunPolicy, WebSocketRunner,
};

/// Stable adapter contract version. This versions source behavior, not provider payload schemas.
pub const ADAPTER_CONTRACT_VERSION: &str = "joshi.sources.v1";
