use std::{fmt, str::FromStr};

use joshi_domain::{
    AccountId, ObservationId, SourceEventId, StableString, UtcTimestamp, WireStringError, WireU64,
};
use serde::{Deserialize, Deserializer, Serialize, de};

/// A validated Solana public key. It conveys no private-key material or ownership claim.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct PublicKey(String);

impl PublicKey {
    /// Validate a base58-encoded 32-byte public key.
    ///
    /// # Errors
    ///
    /// Rejects invalid base58 or any decoded length other than 32 bytes.
    pub fn new(value: impl Into<String>) -> Result<Self, PublicKeyError> {
        let value = value.into();
        let bytes = bs58::decode(&value)
            .into_vec()
            .map_err(|_| PublicKeyError::InvalidBase58)?;
        if bytes.len() != 32 {
            return Err(PublicKeyError::InvalidLength);
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Map the chain key into the one canonical domain-account namespace.
    ///
    /// # Errors
    ///
    /// Returns a wire error only if the shared account identity contract changes incompatibly.
    pub fn domain_account_id(&self) -> Result<AccountId, WireStringError> {
        AccountId::new(format!("solana.account:{}", self.0))
    }
}

impl fmt::Display for PublicKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl FromStr for PublicKey {
    type Err = PublicKeyError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for PublicKey {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::new(String::deserialize(deserializer)?).map_err(de::Error::custom)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum PublicKeyError {
    #[error("Solana public key is not valid base58")]
    InvalidBase58,
    #[error("Solana public key must decode to exactly 32 bytes")]
    InvalidLength,
}

/// Canonical signed atom delta. Positive amounts do not carry a leading plus sign.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(transparent)]
pub struct AtomDelta(String);

impl AtomDelta {
    #[must_use]
    pub fn from_pre_post(pre: u64, post: u64) -> Self {
        let delta = i128::from(post) - i128::from(pre);
        Self(delta.to_string())
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for AtomDelta {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        let parsed = value.parse::<i128>().map_err(de::Error::custom)?;
        if parsed.to_string() != value {
            return Err(de::Error::custom("atom delta is not canonical"));
        }
        Ok(Self(value))
    }
}

/// Open but deliberately non-identity participant relation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParticipantRelation {
    ProfileWalletProviderClaim,
    SignedInstructionUser,
    SignedTransactionAccount,
    TransferCounterparty,
    SameTransactionAccount,
    DeclaredCreator,
    MintHolderCandidate,
    CohortCandidate,
    OperatorSelected,
    Other(StableString),
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Commitment {
    Processed,
    Confirmed,
    Finalized,
}

/// Canonicality is an append-only chain-resolution claim, independent of mere observation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Canonicality {
    ObservedAtCommitment,
    Canonical,
    NonCanonical,
    Conflicted,
}

/// Caller-supplied version context for one signature in an acquisition page.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransactionVersionInput {
    pub signature: StableString,
    pub version: WireU64,
    pub supersedes_transaction_fact_id: Option<StableString>,
    pub canonicality: Canonicality,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Venue {
    PumpBondingCurve,
    PumpSwap,
    SystemProgram,
    SplToken,
    SplToken2022,
    Other(PublicKey),
}

/// Chain-native transaction location. Transaction index remains absent when the source omitted it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TransactionLocator {
    pub signature: StableString,
    pub slot: WireU64,
    pub transaction_index: Option<WireU64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AccountRole {
    pub account: PublicKey,
    pub ordinal: WireU64,
    pub signer: bool,
    pub writable: bool,
    pub source: Option<StableString>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AccountEffect {
    pub account: PublicKey,
    pub account_index: WireU64,
    pub pre_atoms: WireU64,
    pub post_atoms: WireU64,
    pub delta_atoms: AtomDelta,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TokenEffect {
    pub account_index: WireU64,
    pub account: Option<PublicKey>,
    pub owner: Option<PublicKey>,
    pub mint: PublicKey,
    pub decimals: WireU64,
    pub pre_atoms: WireU64,
    pub post_atoms: WireU64,
    pub delta_atoms: AtomDelta,
}

/// Account as it appeared in one instruction's ordered caller-account list.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InstructionAccount {
    pub account: PublicKey,
    pub ordinal: WireU64,
    pub signer: bool,
    pub writable: bool,
    pub role: Option<StableString>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InstructionFact {
    pub instruction_id: StableString,
    pub transaction_fact_id: StableString,
    pub outer_index: WireU64,
    pub inner_index: Option<WireU64>,
    pub program_id: Option<PublicKey>,
    /// Exact base58 instruction bytes as supplied by the raw Solana transaction.
    /// Parsed provider projections must not synthesize this field.
    pub raw_data_base58: Option<StableString>,
    pub parsed_type: Option<StableString>,
    pub accounts: Vec<InstructionAccount>,
    pub execution_succeeded: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProgramOccurrence {
    pub program_id: PublicKey,
    pub venue: Venue,
    pub instruction_paths: Vec<Vec<WireU64>>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransferKind {
    NativeSystemInstruction,
    ParsedTokenInstruction,
}

/// Executed transfer fact. Failed transactions never emit this row.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TransferFact {
    pub flow_id: StableString,
    pub transaction_fact_id: StableString,
    pub transaction: TransactionLocator,
    pub outer_index: Option<WireU64>,
    pub inner_index: Option<WireU64>,
    pub order: WireU64,
    pub from_account: PublicKey,
    pub to_account: PublicKey,
    pub authority: Option<PublicKey>,
    pub asset_id: StableString,
    pub atoms: WireU64,
    pub program_id: PublicKey,
    pub venue: Venue,
    pub pool: Option<PublicKey>,
    pub kind: TransferKind,
}

/// Versioned Pump/PumpSwap decoder output presented for strict admission against raw evidence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DecodedSwapInput {
    pub decode_id: StableString,
    pub decoder_version: StableString,
    pub observation_id: ObservationId,
    pub transaction: TransactionLocator,
    pub instruction_path: Vec<WireU64>,
    pub event_ordinal: WireU64,
    pub trader_wallet: PublicKey,
    pub program_id: PublicKey,
    pub pool: Option<PublicKey>,
    pub input_asset_id: StableString,
    pub input_atoms: WireU64,
    pub output_asset_id: StableString,
    pub output_atoms: WireU64,
    pub available_at: UtcTimestamp,
}

/// Exact admitted swap semantics backed by a named decoder and raw transaction observation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SwapFact {
    pub swap_id: StableString,
    pub transaction_fact_id: StableString,
    pub decoder_version: StableString,
    pub observation_id: ObservationId,
    pub transaction: TransactionLocator,
    pub instruction_path: Vec<WireU64>,
    pub event_ordinal: WireU64,
    pub trader_wallet: PublicKey,
    pub venue: Venue,
    pub program_id: PublicKey,
    pub pool: Option<PublicKey>,
    pub input_asset_id: StableString,
    pub input_atoms: WireU64,
    pub output_asset_id: StableString,
    pub output_atoms: WireU64,
    pub available_at: UtcTimestamp,
}

/// Versioned hypothesis input. A transfer itself remains the only direct funding-edge fact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FundingHypothesisInput {
    pub hypothesis_id: StableString,
    pub transfer_flow_id: StableString,
    pub candidate_recipient: PublicKey,
    pub method: StableString,
    pub inference_version: StableString,
    pub evidence_observation_ids: Vec<ObservationId>,
    pub available_at: UtcTimestamp,
}

/// Inferred funding relation, never merged into exact transfers or entity identity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FundingHypothesis {
    pub hypothesis_id: StableString,
    pub transfer_flow_id: StableString,
    pub candidate_funder: PublicKey,
    pub candidate_recipient: PublicKey,
    pub method: StableString,
    pub inference_version: StableString,
    pub evidence_observation_ids: Vec<ObservationId>,
    pub available_at: UtcTimestamp,
    pub establishes_common_ownership: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SameTransactionBundle {
    pub bundle_id: StableString,
    pub transaction_fact_id: StableString,
    pub transaction: TransactionLocator,
    pub ordered_accounts: Vec<PublicKey>,
    pub signer_accounts: Vec<PublicKey>,
    pub ordered_fact_ids: Vec<StableString>,
}

/// Directly decoded chain transaction facts. No entity ownership or skill is inferred.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RawTransactionFact {
    pub fact_id: StableString,
    pub version: WireU64,
    pub supersedes_transaction_fact_id: Option<StableString>,
    pub canonicality: Canonicality,
    pub observation_id: ObservationId,
    /// Typed source-event identities assigned by the receipt-bound admission adapter.
    #[serde(default)]
    pub source_event_ids: Vec<SourceEventId>,
    pub transaction: TransactionLocator,
    pub block_time_seconds: Option<WireU64>,
    pub available_at: UtcTimestamp,
    pub commitment: Commitment,
    pub succeeded: bool,
    pub fee_atoms: Option<WireU64>,
    pub account_roles: Vec<AccountRole>,
    pub native_effects: Vec<AccountEffect>,
    pub token_effects: Vec<TokenEffect>,
    pub instructions: Vec<InstructionFact>,
    pub programs: Vec<ProgramOccurrence>,
    pub executed_transfers: Vec<TransferFact>,
    pub decoded_swaps: Vec<SwapFact>,
    pub same_transaction_bundle: SameTransactionBundle,
    pub query_scope_ids: Vec<StableString>,
    pub requested_coverage_ids: Vec<StableString>,
}

/// A vendor parser assertion retained separately from raw-chain normalization.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnhancedProjection {
    pub projection_id: StableString,
    pub observation_id: ObservationId,
    pub signature: StableString,
    pub slot: Option<WireU64>,
    pub provider_type: Option<StableString>,
    pub provider_source: Option<StableString>,
    pub transfers: Vec<EnhancedTransferProjection>,
    pub claims_swap: bool,
    pub requires_raw_reconciliation: bool,
}

/// Vendor-parsed transfer claim that has not yet been reconciled to one raw transaction fact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnhancedTransferProjection {
    pub projection_transfer_id: StableString,
    pub transaction: TransactionLocator,
    pub order: WireU64,
    pub from_account: PublicKey,
    pub to_account: PublicKey,
    pub asset_id: StableString,
    pub atoms: WireU64,
}

/// Derived mint-relative row; cohort membership remains an explicit input reference.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MintRelativeWalletFlow {
    pub flow_summary_id: StableString,
    pub mint: PublicKey,
    pub wallet: PublicKey,
    pub cohort_input_id: StableString,
    pub evidence_fact_ids: Vec<StableString>,
    pub gross_in_atoms: WireU64,
    pub gross_out_atoms: WireU64,
    pub first_observed_slot: WireU64,
    pub last_observed_slot: WireU64,
    pub transaction_count: WireU64,
    pub venues: Vec<Venue>,
    pub available_at: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NormalizationIssue {
    MalformedProviderJson,
    ProviderError,
    NullTransaction,
    MissingTransactionIndex,
    MissingBlockTime,
    MissingMeta,
    UnsupportedInstruction,
    LegacyEnhancedNeedsRawReconciliation,
    UnknownAccountKeyShape,
    Other(StableString),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoverageVerificationStatus {
    RequestedUnverified,
    CoreStoreVerified,
}

/// Coverage is scoped to exactly the leased query and does not assert global completeness.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CoverageAssessment {
    pub scope_ids: Vec<StableString>,
    pub lower_slot: Option<WireU64>,
    pub upper_slot: Option<WireU64>,
    pub source_cursor_candidate: Option<StableString>,
    pub page_exhausted: bool,
    pub gap_ids: Vec<StableString>,
    pub verification_status: CoverageVerificationStatus,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NormalizedWalletBatch {
    pub contract_version: StableString,
    pub observation_id: ObservationId,
    pub raw_transactions: Vec<RawTransactionFact>,
    pub enhanced_projections: Vec<EnhancedProjection>,
    pub coverage: CoverageAssessment,
    pub issues: Vec<NormalizationIssue>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChainCorrectionKind {
    FinalityAdvanced,
    FinalityRegressed,
    SlotConflict,
    TransactionBecameUnavailable,
    Reappeared,
    NoSemanticChange,
}

/// Append-only reconciliation claim between two observations of one signature.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChainCorrection {
    pub correction_id: StableString,
    pub signature: StableString,
    pub previous_observation_id: ObservationId,
    pub current_observation_id: ObservationId,
    pub kind: ChainCorrectionKind,
    pub available_at: UtcTimestamp,
}

/// Explicit finality revision; callers persist this as a new assertion, never an update.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FinalityRevision {
    pub signature: StableString,
    pub previous: Commitment,
    pub current: Commitment,
    pub previous_observation_id: ObservationId,
    pub current_observation_id: ObservationId,
    pub available_at: UtcTimestamp,
}
