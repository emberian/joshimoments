use joshi_attention::{
    AttentionEvent, CoverageContext, ExactAttentionInput, IdentityVersion, ResponseObservationRow,
    SelectedClusterContext, TerritorySnapshot,
};
use joshi_domain::{
    AccountId, AcquisitionId, AssertionId, AssetId, CommitSeq, CoverageId, ObservationId, PoolId,
    PositionId, ProtocolProfileId, SourceId, StableString, UtcTimestamp, ValueDigest, VenueId,
    WireU64, WireU128,
};
use serde::{Deserialize, Serialize};

/// The four independently stored input families.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MarketStream {
    SocialProduct,
    Lifecycle,
    PoolState,
    Attention,
}

/// Half-open source/object-valid interval, independent of local arrival.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ValidInterval {
    pub lower: UtcTimestamp,
    pub upper: Option<UtcTimestamp>,
}

impl ValidInterval {
    #[must_use]
    pub fn contains(&self, instant: UtcTimestamp) -> bool {
        self.lower <= instant && self.upper.is_none_or(|upper| instant < upper)
    }

    #[must_use]
    pub fn is_well_formed(&self) -> bool {
        self.upper.is_none_or(|upper| self.lower < upper)
    }
}

/// Why an assertion has (or lacks) event/object validity.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ValidityBasis {
    SourceEvent,
    SourceObjectVersion,
    FinalizedChainSlot,
    /// Receipt/capture bounds attest only when bytes were seen and cannot satisfy `valid_at`.
    CaptureAttestationOnly,
}

/// Local capture bounds retained separately from object/event validity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CaptureAttestation {
    pub started_at: UtcTimestamp,
    pub ended_at: UtcTimestamp,
    pub acquisition_id: AcquisitionId,
}

/// Minimum provenance closure required for every effective fact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FactEvidence {
    pub observation_ids: Vec<ObservationId>,
    pub source_ids: Vec<SourceId>,
    pub coverage_ids: Vec<CoverageId>,
    pub gap_ids: Vec<CoverageId>,
    pub protection: FactProtection,
}

/// Protection boundary repeated in the generic artifact input closure.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FactProtection {
    PublicIntegrity,
    AuthenticatedPrivate,
    OperatorPrivate,
    DerivedRestricted,
}

/// Chain commitment retained as a closed enum so unsupported commitment cannot look final.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChainFinality {
    Processed,
    Confirmed,
    Finalized,
    Noncanonical,
    Unsupported,
}

/// Exact chain cut for one assertion or account observation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChainPoint {
    pub slot: WireU64,
    pub finality: ChainFinality,
}

/// One versioned assertion value read through the durable store's effective-as-known query.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MarketFactV1 {
    pub contract: StableString,
    pub stream: MarketStream,
    pub subject_id: StableString,
    pub valid_time: Option<ValidInterval>,
    pub validity_basis: ValidityBasis,
    pub available_at: UtcTimestamp,
    pub available_commit: CommitSeq,
    pub capture_attestation: Option<CaptureAttestation>,
    pub chain: Option<ChainPoint>,
    pub evidence: FactEvidence,
    pub payload: MarketFactPayload,
}

/// Stream payloads remain tagged rather than sharing a weak property bag.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum MarketFactPayload {
    SocialProduct(Box<SocialProductFact>),
    Lifecycle(Box<LifecycleFact>),
    PoolState(Box<PoolBundleV1>),
    Attention(Box<AttentionFact>),
}

/// Exact social/product occurrence; protection and epistemic class stay in its evidence context.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SocialProductFact {
    pub input: ExactAttentionInput,
}

/// A marked event plus the exact selected-as-known context used for it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttentionFact {
    pub event: AttentionEvent,
    pub forcing_input: ExactAttentionInput,
    pub selected_identity: Option<IdentityVersion>,
    pub selected_territory: Option<TerritorySnapshot>,
    pub selected_cluster: Option<SelectedClusterContext>,
    pub response_observations: Vec<ResponseObservationRow>,
    pub response_coverage: CoverageContext,
}

/// Lifecycle statements are separated by authority; provider hints are never chain facts.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "authority", rename_all = "snake_case")]
pub enum LifecycleFact {
    FinalizedChain {
        mint_id: AssetId,
        event: ChainLifecycleEvent,
        observation_id: ObservationId,
        source_id: SourceId,
    },
    ProductHint {
        mint_id: AssetId,
        hint: ProductLifecycleHint,
        observation_id: ObservationId,
        source_id: SourceId,
        provider_revision: StableString,
    },
}

/// Chain-established Pump/PumpSwap lifecycle and fee/share occurrences.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum ChainLifecycleEvent {
    Created {
        pool_id: PoolId,
    },
    Completed {
        pool_id: PoolId,
    },
    Migrated {
        from_pool_id: PoolId,
        to_pool_id: PoolId,
    },
    CreatorChanged {
        creator: AccountId,
    },
    FeeConfigurationChanged {
        configuration_digest: ValueDigest,
    },
    FeeShareProgramChanged {
        recipient: AccountId,
        enabled: bool,
    },
}

/// Product presentation can nominate these hints but cannot establish protocol state.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductLifecycleHint {
    Created,
    Complete,
    Migrated,
    CreatorClaimed,
    FeeSharingShown,
}

/// Pool family whose exact account closure is represented.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PoolKind {
    PumpCurve,
    PumpSwapCanonical,
    MeteoraDlmmPosition,
}

/// Account role in a coherent closure. Unsupported roles are retained and rejected.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PoolAccountRole {
    Curve,
    Pool,
    Position,
    GlobalConfiguration,
    FeeConfiguration,
    BaseMint,
    QuoteMint,
    BaseVault,
    QuoteVault,
    LbPair,
    ReserveX,
    ReserveY,
    MintX,
    MintY,
    BinArray,
    BitmapExtension,
    Unsupported,
}

/// One decoded account occurrence inside a same-slot closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PoolAccountObservation {
    pub role: PoolAccountRole,
    pub account_id: AccountId,
    pub observation_id: ObservationId,
    pub slot: WireU64,
    pub finality: ChainFinality,
    pub data_digest: ValueDigest,
    pub decoder_profile: StableString,
    pub unsupported_fields: Vec<StableString>,
}

/// Token program and extension closure for a mint account.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TokenDefinitionV1 {
    pub asset_id: AssetId,
    pub decimals: u8,
    pub token_program: StableString,
    pub observation_id: ObservationId,
    pub decoded_extensions: Vec<StableString>,
    pub unsupported_extensions: Vec<StableString>,
}

/// Protocol behavior profile wire representation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProtocolProfileV1 {
    pub id: ProtocolProfileId,
    pub venue_id: VenueId,
    pub program_identity: StableString,
    pub source_revision: StableString,
}

/// Venue lifecycle needed by the exact read-only kernels.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", content = "detail", rename_all = "snake_case")]
pub enum VenueLifecycleV1 {
    Trading,
    Complete,
    Migrated,
    Disabled,
    Unknown(StableString),
}

/// Creator-fee applicability cannot default to zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", content = "basis_points", rename_all = "snake_case")]
pub enum CreatorFeeV1 {
    NotApplicable,
    Charged(u16),
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FeeScheduleV1 {
    pub lp_basis_points: u16,
    pub protocol_basis_points: u16,
    pub creator: CreatorFeeV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FeeTierV1 {
    pub threshold_quote_atoms: WireU128,
    pub schedule: FeeScheduleV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum FeePolicyV1 {
    Flat(FeeScheduleV1),
    MarketCapTiers(Vec<FeeTierV1>),
}

/// Complete Pump bonding-curve state, still bound to its account observations.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PumpCurveWireState {
    pub profile: ProtocolProfileV1,
    pub pool_id: PoolId,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub state_observation_id: ObservationId,
    pub fee_observation_id: ObservationId,
    pub slot: WireU64,
    pub lifecycle: VenueLifecycleV1,
    pub virtual_base_reserves: WireU64,
    pub virtual_quote_reserves: WireU64,
    pub real_base_reserves: WireU64,
    pub real_quote_reserves: WireU64,
    pub base_mint_supply: WireU64,
    pub is_mayhem_mode: bool,
    pub fee_policy: FeePolicyV1,
}

/// Complete canonical `PumpSwap` state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PumpSwapWireState {
    pub profile: ProtocolProfileV1,
    pub pool_id: PoolId,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub state_observation_id: ObservationId,
    pub fee_observation_id: ObservationId,
    pub slot: WireU64,
    pub lifecycle: VenueLifecycleV1,
    pub base_reserves: WireU64,
    pub raw_quote_reserves: WireU64,
    pub virtual_quote_reserves: StableString,
    pub base_mint_supply: WireU64,
    pub fee_policy: FeePolicyV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DlmmPositionVersionV1 {
    V1,
    V2,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DlmmPositionLifecycleV1 {
    Open,
    EmptyOpen,
    Closed,
    Unsupported,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssetPairV1 {
    pub x_atoms: WireU64,
    pub y_atoms: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RewardAmountV1 {
    pub asset_id: AssetId,
    pub atoms: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum DlmmAccrualV1 {
    Observed {
        fees: AssetPairV1,
        rewards: Vec<RewardAmountV1>,
    },
    Unsupported {
        fields: Vec<StableString>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DlmmBinV1 {
    pub bin_id: i32,
    pub price_q64: WireU128,
    pub pool_amounts: AssetPairV1,
    pub liquidity_supply: WireU128,
    pub position_share: WireU128,
    pub accrual: DlmmAccrualV1,
}

/// Complete selected DLMM position/pool/bin input for inventory projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DlmmPositionWireState {
    pub profile: ProtocolProfileV1,
    pub pool_id: PoolId,
    pub position_id: PositionId,
    pub observation_id: ObservationId,
    pub slot: WireU64,
    pub version: DlmmPositionVersionV1,
    pub lifecycle: DlmmPositionLifecycleV1,
    pub token_x: TokenDefinitionV1,
    pub token_y: TokenDefinitionV1,
    pub lower_bin_id: i32,
    pub upper_bin_id: i32,
    pub active_bin_id: i32,
    pub bin_step_basis_points: u16,
    pub bins: Vec<DlmmBinV1>,
    pub unsupported_fields: Vec<StableString>,
}

/// Decoded state must agree with the declared bundle family.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "state", rename_all = "snake_case")]
pub enum DecodedPoolStateV1 {
    PumpCurve(PumpCurveWireState),
    PumpSwapCanonical(PumpSwapWireState),
    MeteoraDlmmPosition(DlmmPositionWireState),
}

/// One account-complete, same-slot candidate closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PoolBundleV1 {
    pub bundle_id: StableString,
    pub pool_kind: PoolKind,
    pub pool_id: PoolId,
    pub slot: WireU64,
    pub accounts: Vec<PoolAccountObservation>,
    pub decoded_state: DecodedPoolStateV1,
}

/// Explicit point-in-time query. No field means “latest.”
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MarketStateCut {
    pub valid_at: UtcTimestamp,
    pub known_by: UtcTimestamp,
    pub known_by_commit: CommitSeq,
    pub finalized_chain_slot: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StreamQuery {
    pub enabled: bool,
    pub semantic_keys: Vec<StableString>,
}

/// Exact semantic-key manifest; disabled streams remain explicit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MarketStateQuery {
    pub artifact_id: StableString,
    pub subject_id: StableString,
    pub cut: MarketStateCut,
    pub social_product: StreamQuery,
    pub lifecycle: StreamQuery,
    pub pool_state: StreamQuery,
    pub attention: StreamQuery,
}

/// Durable assertion metadata retained in the reducer input closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectiveFactRef {
    pub assertion_id: AssertionId,
    pub semantic_key: StableString,
    pub produced_commit: CommitSeq,
    pub value_digest: ValueDigest,
    pub supersedes_assertion_id: Option<AssertionId>,
    pub available_at: UtcTimestamp,
    pub available_commit: CommitSeq,
    pub evidence: FactEvidence,
}

/// Store-neutral row returned by the narrow effective-as-known reader seam.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectiveFactRecord {
    pub assertion_id: AssertionId,
    pub semantic_key: StableString,
    pub produced_commit: CommitSeq,
    pub value: serde_json::Value,
    pub value_digest: ValueDigest,
    pub supersedes_assertion_id: Option<AssertionId>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SelectedFact<T> {
    pub effective: EffectiveFactRef,
    pub value: T,
}

/// Exact reserve mark or inventory projection; never an executable quote or liquidation value.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PoolProjection {
    PumpCurve {
        bundle_id: StableString,
        pool_id: PoolId,
        slot: WireU64,
        numerator_quote_atoms: WireU128,
        denominator_base_atoms: WireU128,
        quote_state_admitted: bool,
    },
    PumpSwapCanonical {
        bundle_id: StableString,
        pool_id: PoolId,
        slot: WireU64,
        numerator_quote_atoms: WireU128,
        denominator_base_atoms: WireU128,
        quote_state_admitted: bool,
    },
    MeteoraDlmmPosition {
        bundle_id: StableString,
        pool_id: PoolId,
        position_id: PositionId,
        slot: WireU64,
        principal: AssetPairV1,
        pending_fees: Option<AssetPairV1>,
        unsupported_fields: Vec<StableString>,
        inventory_state_admitted: bool,
    },
}

/// Accepted immutable input artifact for downstream deterministic publication.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MarketStateSnapshotV1 {
    pub contract: StableString,
    pub artifact_id: StableString,
    pub subject_id: StableString,
    pub authority: StableString,
    pub cut: MarketStateCut,
    pub social_product: Vec<SelectedFact<SocialProductFact>>,
    pub lifecycle: Vec<SelectedFact<LifecycleFact>>,
    pub pool_state: Vec<SelectedFact<PoolProjection>>,
    pub attention: Vec<SelectedFact<AttentionFact>>,
    pub input_closure: Vec<EffectiveFactRef>,
}

/// Stable refusal categories; callers publish a refusal rather than substitute zeros.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RefusalCode {
    InvalidQuery,
    StoreRead,
    MissingEffectiveFact,
    AmbiguousEffectiveBranch,
    UnsupportedContract,
    WrongStream,
    WrongSubject,
    InvalidValidInterval,
    CaptureAttestationIsNotValidity,
    NotValidAtCut,
    NotKnownByCut,
    FutureProducedCommit,
    MissingEvidence,
    InvalidSocialFact,
    InvalidAttentionFact,
    InvalidLifecycleFact,
    PoolClosureIncomplete,
    PoolClosureMixedSlot,
    PoolClosureNotFinalized,
    PoolClosureUnsupported,
    PoolKernelRefused,
}

/// Deterministic refusal artifact with the exact query that did not admit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MarketStateRefusal {
    pub contract: StableString,
    pub artifact_id: StableString,
    pub authority: StableString,
    pub query: MarketStateQuery,
    pub code: RefusalCode,
    pub semantic_key: Option<StableString>,
    pub detail: StableString,
    pub inputs_read_before_refusal: Vec<EffectiveFactRef>,
}

/// Acceptance and refusal are both first-class reducer outcomes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "outcome", content = "artifact", rename_all = "snake_case")]
pub enum MarketStateOutcome {
    Accepted(MarketStateSnapshotV1),
    Refused(MarketStateRefusal),
}
