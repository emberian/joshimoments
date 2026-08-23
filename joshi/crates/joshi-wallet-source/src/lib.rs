//! Read-only, leased wallet-attention acquisition and normalization.
//!
//! This crate is deliberately incapable of constructing or submitting a transaction. It accepts
//! explicit public-key scopes, plans bounded read surfaces, preserves exact source frames through
//! `joshi-evidence`, and derives evidence-bound wallet/transaction facts without turning candidate
//! identity or coordination hypotheses into ownership claims.

mod input;
mod lease;
mod model;
mod normalize;
mod plan;
mod protocol;
mod readback;
mod topology;

pub use input::{
    AttentionPromotionError, AttentionPromotionInput, CandidateEpistemicStatus,
    CandidateWalletInput, CohortParticipant, MintCohortInput, PromotionScope, ScopeInput,
    ScopeTarget,
};
pub use lease::{ActiveLease, LeaseBook, LeaseError, ScopeLease};
pub use model::{
    AccountEffect, AccountRole, AtomDelta, Canonicality, ChainCorrection, ChainCorrectionKind,
    Commitment, CoverageAssessment, CoverageVerificationStatus, DecodedSwapInput,
    EnhancedProjection, EnhancedTransferProjection, FinalityRevision, FundingHypothesis,
    FundingHypothesisInput, InstructionAccount, InstructionFact, MintRelativeWalletFlow,
    NormalizationIssue, NormalizedWalletBatch, ParticipantRelation, ProgramOccurrence, PublicKey,
    PublicKeyError, RawTransactionFact, SameTransactionBundle, SwapFact, TokenEffect,
    TransactionLocator, TransactionVersionInput, TransferFact, TransferKind, Venue,
};
pub use normalize::{
    AcquisitionResponseContext, NormalizationError, WalletAcquisitionOutput, admit_decoded_swap,
    normalize_frame, normalize_stored_body, propose_funding_hypothesis,
    reconcile_transaction_facts, summarize_mint_relative,
};
pub use plan::{
    AcquisitionPlan, AcquisitionPlanner, AcquisitionSurface, BudgetLedger, BudgetUse, PlanConfig,
    PlanError, PlannedRead, ReadBudget, ReadRequestTemplate,
};
pub use protocol::{
    PINNED_DECODER_VERSION, PINNED_PUMP_DOCS_COMMIT, PINNED_PUMP_IDL_SHA256,
    PINNED_PUMP_SDK_NPM_INTEGRITY, PINNED_PUMP_SDK_VERSION, PINNED_PUMPSWAP_IDL_SHA256,
    PINNED_PUMPSWAP_SDK_NPM_INTEGRITY, PINNED_PUMPSWAP_SDK_VERSION, PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID, PinnedDecodeDisposition, PinnedDecodeResult, PinnedDecoderError,
    PinnedInstructionKind, PinnedProtocolInstruction, PinnedSwapIntent, PinnedTrackVolume,
    apply_pinned_protocol_decoder, decode_pinned_protocol_instruction,
};
pub use readback::{
    ReadbackError, SignaturePageEntry, StoredLocatorClass, balance_events_for_wallet,
    chain_head_slot, classify_locator, parse_retained_envelope, signature_page_entries,
};
pub use topology::{TopologyAdapterError, to_topology_facts};

/// Version of this crate's input and normalized-output contracts.
pub const WALLET_SOURCE_CONTRACT_VERSION: &str = "joshi.wallet_source.v1";
