use joshi_domain::{
    AccountId, AssetId, CoverageId, ObservationId, OpenVariant, PoolId, PositionId, SourceEventId,
    StableString, UtcTimestamp, VenueId, WireU64, WireU128,
};
use serde::{Deserialize, Serialize};

use crate::{
    BundleId, FlowId, LiquidityEventId, ProgramId, SwapId, TransactionFactId, TransactionId,
};

/// Exact evidence and source-coverage closure supporting a fact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceClosure {
    pub observation_ids: Vec<ObservationId>,
    pub source_event_ids: Vec<SourceEventId>,
    pub coverage_ids: Vec<CoverageId>,
}

/// One exact amount in atomic units.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AssetAmount {
    pub asset_id: AssetId,
    pub atoms: WireU64,
}

/// Direction and semantic boundary of an exact asset leg.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssetLegDirection {
    IntoWallet,
    OutOfWallet,
    IntoPool,
    OutOfPool,
    IntoPosition,
    OutOfPosition,
    Fee,
    Reward,
}

/// Mark carried by a directed flow edge.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FlowMark {
    pub asset_id: AssetId,
    pub atoms: WireU64,
    pub flow_kind: OpenVariant,
    pub venue_id: Option<VenueId>,
    pub pool_id: Option<PoolId>,
}

/// One amount attached to a liquidity-position action.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AssetLeg {
    pub direction: AssetLegDirection,
    pub amount: AssetAmount,
}

/// Exact transaction location and availability.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransactionFact {
    pub transaction_fact_id: TransactionFactId,
    pub transaction_id: TransactionId,
    pub version: WireU64,
    pub supersedes_transaction_fact_id: Option<TransactionFactId>,
    pub chain_id: StableString,
    pub signature: StableString,
    pub slot: WireU64,
    pub block_time: Option<UtcTimestamp>,
    pub finality: OpenVariant,
    pub canonicality: OpenVariant,
    pub available_at: UtcTimestamp,
    pub evidence: EvidenceClosure,
}

/// Exact account role in one instruction or transaction boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CallerAccountFact {
    pub association_id: StableString,
    pub transaction_id: TransactionId,
    pub transaction_fact_id: TransactionFactId,
    pub instruction_path: StableString,
    pub account_id: AccountId,
    pub account_ordinal: WireU64,
    pub role: OpenVariant,
    pub program_id: Option<ProgramId>,
    pub is_signer: bool,
    pub is_writable: bool,
    pub available_at: UtcTimestamp,
    pub evidence: EvidenceClosure,
}

/// Exact decoded transfer. Calling it funding requires a separate hypothesis.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransferFact {
    pub flow_id: FlowId,
    pub transaction_id: TransactionId,
    pub transaction_fact_id: TransactionFactId,
    pub instruction_path: StableString,
    pub event_ordinal: WireU64,
    pub from_account_id: AccountId,
    pub to_account_id: AccountId,
    pub program_id: ProgramId,
    pub mark: FlowMark,
    pub available_at: UtcTimestamp,
    pub evidence: EvidenceClosure,
}

/// Exact decoded swap with actor attribution only where chain evidence establishes it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SwapFact {
    pub swap_id: SwapId,
    pub transaction_id: TransactionId,
    pub transaction_fact_id: TransactionFactId,
    pub instruction_path: StableString,
    pub event_ordinal: WireU64,
    pub trader_wallet_id: Option<AccountId>,
    pub caller_account_id: AccountId,
    pub program_id: ProgramId,
    pub venue_id: VenueId,
    pub pool_id: Option<PoolId>,
    pub input: AssetAmount,
    pub output: AssetAmount,
    pub fee_legs: Vec<AssetAmount>,
    pub available_at: UtcTimestamp,
    pub evidence: EvidenceClosure,
}

/// Exact observed liquidity-position mutation or accrual claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LiquidityPositionEventFact {
    pub liquidity_event_id: LiquidityEventId,
    pub transaction_id: TransactionId,
    pub transaction_fact_id: TransactionFactId,
    pub instruction_path: StableString,
    pub event_ordinal: WireU64,
    pub position_id: PositionId,
    pub actor_wallet_id: Option<AccountId>,
    pub authority_account_id: AccountId,
    pub program_id: ProgramId,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
    pub event_kind: OpenVariant,
    pub asset_legs: Vec<AssetLeg>,
    pub protocol_liquidity_units: Option<WireU128>,
    pub available_at: UtcTimestamp,
    pub evidence: EvidenceClosure,
}

/// Typed reference to one topology fact.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum TopologyFactRef {
    CallerAccount(StableString),
    Transfer(FlowId),
    Swap(SwapId),
    LiquidityPositionEvent(LiquidityEventId),
}

/// Ordered exact facts occurring inside one chain transaction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SameTransactionBundleFact {
    pub bundle_id: BundleId,
    pub transaction_id: TransactionId,
    pub transaction_fact_id: TransactionFactId,
    pub ordered_members: Vec<TopologyFactRef>,
    pub available_at: UtcTimestamp,
    pub evidence: EvidenceClosure,
}

/// Closed set of exact public-chain facts accepted by the reducer.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "fact", rename_all = "snake_case")]
pub enum TopologyFact {
    Transaction(TransactionFact),
    CallerAccount(CallerAccountFact),
    Transfer(TransferFact),
    Swap(SwapFact),
    LiquidityPositionEvent(LiquidityPositionEventFact),
    SameTransactionBundle(SameTransactionBundleFact),
}

impl TopologyFact {
    /// Returns the local availability time used for point-in-time filtering.
    #[must_use]
    pub const fn available_at(&self) -> UtcTimestamp {
        match self {
            Self::Transaction(value) => value.available_at,
            Self::CallerAccount(value) => value.available_at,
            Self::Transfer(value) => value.available_at,
            Self::Swap(value) => value.available_at,
            Self::LiquidityPositionEvent(value) => value.available_at,
            Self::SameTransactionBundle(value) => value.available_at,
        }
    }

    /// Returns the referenced transaction, including a transaction fact's own identity.
    #[must_use]
    pub const fn transaction_id(&self) -> &TransactionId {
        match self {
            Self::Transaction(value) => &value.transaction_id,
            Self::CallerAccount(value) => &value.transaction_id,
            Self::Transfer(value) => &value.transaction_id,
            Self::Swap(value) => &value.transaction_id,
            Self::LiquidityPositionEvent(value) => &value.transaction_id,
            Self::SameTransactionBundle(value) => &value.transaction_id,
        }
    }

    /// Returns the immutable transaction fact version used by this record.
    #[must_use]
    pub const fn transaction_fact_id(&self) -> &TransactionFactId {
        match self {
            Self::Transaction(value) => &value.transaction_fact_id,
            Self::CallerAccount(value) => &value.transaction_fact_id,
            Self::Transfer(value) => &value.transaction_fact_id,
            Self::Swap(value) => &value.transaction_fact_id,
            Self::LiquidityPositionEvent(value) => &value.transaction_fact_id,
            Self::SameTransactionBundle(value) => &value.transaction_fact_id,
        }
    }

    /// Returns the exact evidence closure.
    #[must_use]
    pub const fn evidence(&self) -> &EvidenceClosure {
        match self {
            Self::Transaction(value) => &value.evidence,
            Self::CallerAccount(value) => &value.evidence,
            Self::Transfer(value) => &value.evidence,
            Self::Swap(value) => &value.evidence,
            Self::LiquidityPositionEvent(value) => &value.evidence,
            Self::SameTransactionBundle(value) => &value.evidence,
        }
    }
}
