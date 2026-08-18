use core::fmt;
use std::collections::BTreeSet;
use std::str::FromStr;

use joshi_domain::{
    AccountId, AssetId, BatchDigest, CommitSeq, CoverageId, PoolId, PositionId, StableString,
    UtcTimestamp, VenueId, WireU64, WireU128,
};
use serde::{Deserialize, Deserializer, Serialize, Serializer, de};
use thiserror::Error;

use crate::{
    BundleId, DerivationId, HypothesisId, ProgramId, SnapshotId, SwapId, TopologyFact,
    TopologyFactRef, TopologyHypothesis, TransactionId,
};

/// Exact signed atomic quantity serialized as a canonical decimal string.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SignedAtoms(i128);

impl SignedAtoms {
    /// Creates a signed atomic quantity.
    #[must_use]
    pub const fn new(value: i128) -> Self {
        Self(value)
    }

    /// Returns the native value.
    #[must_use]
    pub const fn get(self) -> i128 {
        self.0
    }
}

impl fmt::Display for SignedAtoms {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for SignedAtoms {
    type Err = SignedAtomsParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        if value.is_empty()
            || value == "-0"
            || value.starts_with('+')
            || value.starts_with("00")
            || value.starts_with("-0")
            || !value
                .strip_prefix('-')
                .unwrap_or(value)
                .bytes()
                .all(|byte| byte.is_ascii_digit())
        {
            return Err(SignedAtomsParseError::NonCanonical);
        }
        value
            .parse()
            .map(Self)
            .map_err(|_| SignedAtomsParseError::OutOfRange)
    }
}

impl Serialize for SignedAtoms {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for SignedAtoms {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        value.parse().map_err(de::Error::custom)
    }
}

/// Invalid signed atomic wire value.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum SignedAtomsParseError {
    #[error("signed atoms must use minimal signed decimal digits")]
    NonCanonical,
    #[error("signed atoms are outside the i128 range")]
    OutOfRange,
}

/// Epistemic class of a table row.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClass {
    Observed,
    DeterministicDerived,
    InferredHypothesis,
}

/// Typed node in the multiplex graph without collapsing accounts, venues, pools, or positions.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum TopologyNodeRef {
    Wallet(AccountId),
    Account(AccountId),
    Venue(VenueId),
    Pool(PoolId),
    Program(ProgramId),
    Position(PositionId),
}

/// Oriented incidence sign. Tail is -1 and head is +1 in the B1 matrix.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IncidenceSign {
    TailMinusOne,
    HeadPlusOne,
}

/// Canonical marked directed-edge row.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FlowEdgeRow {
    pub edge_id: StableString,
    pub transaction_id: TransactionId,
    pub slot: WireU64,
    pub source: TopologyNodeRef,
    pub target: TopologyNodeRef,
    pub asset_id: AssetId,
    pub atoms: WireU64,
    pub edge_kind: StableString,
    pub venue_id: Option<VenueId>,
    pub pool_id: Option<PoolId>,
    pub evidence_class: EvidenceClass,
    pub input_fact: TopologyFactRef,
}

/// Sparse oriented B1 matrix row for graph/Hodge decomposition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IncidenceRow {
    pub edge_id: StableString,
    pub node: TopologyNodeRef,
    pub sign: IncidenceSign,
    pub asset_id: AssetId,
    pub atoms: WireU64,
    pub slot: WireU64,
}

/// Windowed node accumulation/divergence input without floating-point shares.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DivergenceRow {
    pub derivation_id: DerivationId,
    pub node: TopologyNodeRef,
    pub asset_id: AssetId,
    pub through_slot: WireU64,
    pub inflow_atoms: WireU128,
    pub outflow_atoms: WireU128,
    pub net_accumulation_atoms: SignedAtoms,
    pub evidence_class: EvidenceClass,
    pub input_edge_ids: Vec<StableString>,
}

/// Ordered fact membership in an exact same-transaction bundle.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BundleLegRow {
    pub bundle_id: BundleId,
    pub transaction_id: TransactionId,
    pub ordinal: WireU64,
    pub fact_ref: TopologyFactRef,
    pub evidence_class: EvidenceClass,
}

/// Swap leg suitable for reconstructing a same-transaction cross-venue route.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RouteLegRow {
    pub bundle_id: BundleId,
    pub ordinal: WireU64,
    pub swap_id: SwapId,
    pub wallet_id: Option<AccountId>,
    pub venue_id: VenueId,
    pub pool_id: Option<PoolId>,
    pub input_asset_id: AssetId,
    pub input_atoms: WireU64,
    pub output_asset_id: AssetId,
    pub output_atoms: WireU64,
}

/// Route endpoint closure input; `is_closed` is structural, not a profit claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CycleInputRow {
    pub derivation_id: DerivationId,
    pub bundle_id: BundleId,
    pub wallet_id: Option<AccountId>,
    pub first_input_asset_id: AssetId,
    pub last_output_asset_id: AssetId,
    pub ordered_leg_count: WireU64,
    pub path_is_contiguous: bool,
    pub is_asset_closed: bool,
    pub evidence_class: EvidenceClass,
}

/// Mint-relative wallet activity inside the selected point-in-time window.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WalletMintCohortRow {
    pub derivation_id: DerivationId,
    pub wallet_id: AccountId,
    pub mint_id: AssetId,
    pub first_observed_acquisition_slot: Option<WireU64>,
    pub last_observed_disposal_slot: Option<WireU64>,
    pub acquired_atoms: WireU128,
    pub disposed_atoms: WireU128,
    pub swap_count: WireU64,
    pub venue_ids: Vec<VenueId>,
    pub input_swap_ids: Vec<SwapId>,
    pub coverage_ids: Vec<CoverageId>,
    pub evidence_class: EvidenceClass,
}

/// Raw per-wallet weights for concentration calculations under a named window.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConcentrationInputRow {
    pub derivation_id: DerivationId,
    pub wallet_id: AccountId,
    pub mint_id: AssetId,
    pub acquired_atoms: WireU128,
    pub disposed_atoms: WireU128,
    pub total_mint_activity_atoms: WireU128,
    pub window_total_activity_atoms: WireU128,
    pub evidence_class: EvidenceClass,
}

/// Count-based cohort entry/exit/churn inputs; observed transfers are not inventory proof.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CohortAggregateRow {
    pub derivation_id: DerivationId,
    pub mint_id: AssetId,
    pub wallets_with_observed_acquisition: WireU64,
    pub wallets_with_observed_disposal: WireU64,
    pub wallets_with_both: WireU64,
    pub coverage_ids: Vec<CoverageId>,
    pub evidence_class: EvidenceClass,
}

/// Bounded temporal co-trading feature, never a common-identity claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WalletPairCoTradeRow {
    pub derivation_id: DerivationId,
    pub wallet_a_id: AccountId,
    pub wallet_b_id: AccountId,
    pub mint_id: AssetId,
    pub window_slots: WireU64,
    pub joint_occurrences: WireU64,
    pub first_joint_slot: WireU64,
    pub last_joint_slot: WireU64,
    pub input_swap_ids: Vec<SwapId>,
    pub evidence_class: EvidenceClass,
}

/// Three-axis point-in-time request: knowledge cutoff, chain slot, and event wall time.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SnapshotRequest {
    pub snapshot_id: SnapshotId,
    pub available_through: UtcTimestamp,
    pub event_slot: WireU64,
    pub event_time: UtcTimestamp,
    pub accepted_finalities: Vec<StableString>,
    pub accepted_canonicalities: Vec<StableString>,
    pub focus_mint_ids: Vec<AssetId>,
    pub requested_coverage_ids: Vec<CoverageId>,
    pub co_trade_window_slots: WireU64,
    pub max_pair_rows: WireU64,
}

/// Coverage references supplied to the pure reducer but not yet checked against the core store.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum CoverageBinding {
    UnverifiedRequest {
        coverage_ids: Vec<CoverageId>,
    },
    /// Exact requested coverage closed by one validated public store receipt.
    StoreVerified {
        coverage_ids: Vec<CoverageId>,
        catalog_id: StableString,
        through_commit_seq: CommitSeq,
        receipt_closures: Vec<StoreCoverageReceipt>,
    },
}

/// One validated durable receipt contributing coverage/facts to a topology snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StoreCoverageReceipt {
    pub catalog_id: StableString,
    pub through_commit_seq: CommitSeq,
    pub batch_id: StableString,
    pub batch_digest: BatchDigest,
    pub coverage_ids: Vec<CoverageId>,
}

/// Store receipt cannot be attached to a different reducer request after the fact.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum CoverageBindingError {
    #[error("store receipt coverage closure must be nonempty")]
    EmptyReceiptClosure,
    #[error("store receipt coverage does not exactly match the snapshot request")]
    CoverageMismatch,
    #[error("store receipt coverage closure spans different catalogs")]
    CatalogMismatch,
    #[error("store receipt coverage closure is not strictly ordered and duplicate-free")]
    InvalidReceiptOrder,
}

/// Bounded glass/analysis selection over one immutable snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TopologyQuery {
    pub query_id: StableString,
    pub snapshot_id: SnapshotId,
    pub wallet_ids: Vec<AccountId>,
    pub mint_ids: Vec<AssetId>,
    pub venue_ids: Vec<VenueId>,
    pub hypothesis_ids: Vec<HypothesisId>,
    pub include_evidence_classes: Vec<EvidenceClass>,
    pub row_limit: WireU64,
}

/// Immutable point-in-time fact/hypothesis selection and canonical analytical rows.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TopologySnapshot {
    pub contract: StableString,
    pub arrow_table_contract: StableString,
    pub request: SnapshotRequest,
    pub coverage_binding: CoverageBinding,
    pub observed_transaction_versions: Vec<crate::TransactionFact>,
    pub accepted_facts: Vec<TopologyFact>,
    pub current_hypotheses: Vec<TopologyHypothesis>,
    pub excluded_noncanonical_transaction_ids: Vec<TransactionId>,
    pub excluded_unaccepted_finality_transaction_ids: Vec<TransactionId>,
    pub flow_edges: Vec<FlowEdgeRow>,
    pub incidence: Vec<IncidenceRow>,
    pub divergence: Vec<DivergenceRow>,
    pub bundle_legs: Vec<BundleLegRow>,
    pub route_legs: Vec<RouteLegRow>,
    pub cycle_inputs: Vec<CycleInputRow>,
    pub wallet_mint_cohorts: Vec<WalletMintCohortRow>,
    pub concentration_inputs: Vec<ConcentrationInputRow>,
    pub cohort_aggregates: Vec<CohortAggregateRow>,
    pub co_trades: Vec<WalletPairCoTradeRow>,
}

impl TopologySnapshot {
    /// Consume an unverified snapshot and bind it to exact store-confirmed coverage closure.
    ///
    /// The caller must obtain these values from a validated durable receipt. Exact set equality
    /// prevents a receipt for a narrower or unrelated acquisition from blessing the snapshot.
    ///
    /// # Errors
    ///
    /// Refuses an empty, cross-catalog, duplicate/out-of-order, or coverage-mismatched receipt
    /// closure.
    pub fn with_store_verified_coverage(
        mut self,
        mut receipt_closures: Vec<StoreCoverageReceipt>,
    ) -> Result<Self, CoverageBindingError> {
        receipt_closures.sort_by(|left, right| {
            left.through_commit_seq
                .cmp(&right.through_commit_seq)
                .then(left.batch_id.cmp(&right.batch_id))
        });
        let Some(first) = receipt_closures.first() else {
            return Err(CoverageBindingError::EmptyReceiptClosure);
        };
        let catalog_id = first.catalog_id.clone();
        if receipt_closures
            .iter()
            .any(|receipt| receipt.catalog_id != catalog_id)
        {
            return Err(CoverageBindingError::CatalogMismatch);
        }
        if receipt_closures.windows(2).any(|pair| {
            pair[0].through_commit_seq >= pair[1].through_commit_seq
                || pair[0].batch_id == pair[1].batch_id
        }) {
            return Err(CoverageBindingError::InvalidReceiptOrder);
        }
        let through_commit_seq = receipt_closures
            .last()
            .ok_or(CoverageBindingError::EmptyReceiptClosure)?
            .through_commit_seq;
        let mut coverage_ids = receipt_closures
            .iter()
            .flat_map(|receipt| receipt.coverage_ids.iter().cloned())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        coverage_ids.sort();
        if coverage_ids != self.request.requested_coverage_ids {
            return Err(CoverageBindingError::CoverageMismatch);
        }
        self.coverage_binding = CoverageBinding::StoreVerified {
            coverage_ids,
            catalog_id,
            through_commit_seq,
            receipt_closures,
        };
        Ok(self)
    }
}
