//! Point-in-time wallet, asset-flow, venue, bundle, and hypothesis topology.
//!
//! Exact public-chain facts remain distinct from deterministic projections and from inferred
//! funding, clustering, or coordination claims. No type in this crate resolves a human identity,
//! ranks a wallet, constructs a transaction, or supplies trading authority.

#![forbid(unsafe_code)]

mod fact;
mod hypothesis;
mod id;
mod reducer;
mod table;

pub use fact::{
    AssetAmount, AssetLeg, AssetLegDirection, CallerAccountFact, EvidenceClosure, FlowMark,
    LiquidityPositionEventFact, SameTransactionBundleFact, SwapFact, TopologyFact, TopologyFactRef,
    TransactionFact, TransferFact,
};
pub use hypothesis::{
    AdversarialAlternative, ClusterMember, HypothesisClaim, HypothesisEvidence, HypothesisStatus,
    HypothesisValidity, SlotInterval, SupportPpm, TopologyHypothesis,
};
pub use id::{
    BundleId, DerivationId, FlowId, HypothesisId, HypothesisSeriesId, LiquidityEventId, ProgramId,
    SnapshotId, SwapId, TransactionFactId, TransactionId,
};
pub use reducer::{ReducerConfig, TopologyError, TopologyInput, TopologyReducer};
pub use table::{
    BundleLegRow, CohortAggregateRow, ConcentrationInputRow, CoverageBinding, CoverageBindingError,
    CycleInputRow, DivergenceRow, EvidenceClass, FlowEdgeRow, IncidenceRow, IncidenceSign,
    RouteLegRow, SignedAtoms, SignedAtomsParseError, SnapshotRequest, StoreCoverageReceipt,
    TopologyNodeRef, TopologyQuery, TopologySnapshot, WalletMintCohortRow, WalletPairCoTradeRow,
};

/// Version of the typed topology input and snapshot contract.
pub const TOPOLOGY_CONTRACT_VERSION: &str = "joshi.wallet_topology.v1";

/// Version of the canonical Arrow-facing logical table family.
pub const ARROW_TABLE_CONTRACT_VERSION: &str = "joshi.wallet_topology.arrow_tables.v1";

#[cfg(test)]
mod tests;
