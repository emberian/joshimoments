use joshi_domain::{
    AccountId, CoverageId, ObservationId, OpenVariant, SourceEventId, StableString, UtcTimestamp,
    ValueDigest, WireIntegerError, WireU64,
};
use joshi_evidence::EventValidInterval;
use serde::{Deserialize, Serialize};

use crate::{BundleId, DerivationId, FlowId, HypothesisId, HypothesisSeriesId, TopologyFactRef};

/// Non-probabilistic support score in parts per million.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(try_from = "WireU64", into = "WireU64")]
pub struct SupportPpm(WireU64);

impl SupportPpm {
    /// Maximum representable support score.
    pub const MAX: u64 = 1_000_000;

    /// Creates a bounded support score.
    ///
    /// # Errors
    ///
    /// Refuses values above one million.
    pub const fn new(value: u64) -> Result<Self, WireIntegerError> {
        if value > Self::MAX {
            Err(WireIntegerError::OutOfRange)
        } else {
            Ok(Self(WireU64::new(value)))
        }
    }

    /// Returns the native value.
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

impl TryFrom<WireU64> for SupportPpm {
    type Error = WireIntegerError;

    fn try_from(value: WireU64) -> Result<Self, Self::Error> {
        Self::new(value.get())
    }
}

impl From<SupportPpm> for WireU64 {
    fn from(value: SupportPpm) -> Self {
        value.0
    }
}

/// Half-open slot interval over which a hypothesis claims event validity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SlotInterval {
    pub lower_inclusive: WireU64,
    pub upper_exclusive: Option<WireU64>,
}

impl SlotInterval {
    /// Returns whether a slot is inside this interval.
    #[must_use]
    pub fn contains(&self, slot: WireU64) -> bool {
        slot >= self.lower_inclusive && self.upper_exclusive.is_none_or(|upper| slot < upper)
    }
}

/// Event-valid slot and wall-time axes, separate from knowledge availability.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HypothesisValidity {
    pub slots: Option<SlotInterval>,
    pub wall_time: EventValidInterval,
}

/// Exact evidence and deterministic inputs used by an inferred claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HypothesisEvidence {
    pub observation_ids: Vec<ObservationId>,
    pub source_event_ids: Vec<SourceEventId>,
    pub coverage_ids: Vec<CoverageId>,
    pub fact_refs: Vec<TopologyFactRef>,
    pub derivation_ids: Vec<DerivationId>,
    pub input_digest: ValueDigest,
}

/// One wallet's membership in a cluster hypothesis, never in a canonical entity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClusterMember {
    pub wallet_id: AccountId,
    pub membership_support_ppm: SupportPpm,
    pub role: OpenVariant,
}

/// A falsifying or observationally equivalent explanation retained with a claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AdversarialAlternative {
    pub alternative_kind: OpenVariant,
    pub description: StableString,
    pub supporting_fact_refs: Vec<TopologyFactRef>,
}

/// Inferred claim payloads. None asserts common human identity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "claim", rename_all = "snake_case")]
pub enum HypothesisClaim {
    FundingEdge {
        from_wallet_id: AccountId,
        to_wallet_id: AccountId,
        supporting_flow_ids: Vec<FlowId>,
    },
    WalletCluster {
        members: Vec<ClusterMember>,
    },
    Coordination {
        wallet_ids: Vec<AccountId>,
        bundle_ids: Vec<BundleId>,
        co_trade_derivation_ids: Vec<DerivationId>,
    },
}

/// Lifecycle state of a versioned inferred claim.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HypothesisStatus {
    Candidate,
    Supported,
    Disputed,
    Retracted,
}

/// One immutable version of a funding, clustering, or coordination hypothesis.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TopologyHypothesis {
    pub hypothesis_id: HypothesisId,
    pub hypothesis_series_id: HypothesisSeriesId,
    pub version: WireU64,
    pub claim: HypothesisClaim,
    pub producer: StableString,
    pub method: StableString,
    pub method_version: StableString,
    pub support_ppm: SupportPpm,
    pub validity: HypothesisValidity,
    pub available_at: UtcTimestamp,
    pub status: HypothesisStatus,
    pub evidence: HypothesisEvidence,
    pub supersedes_hypothesis_id: Option<HypothesisId>,
    pub adversarial_alternatives: Vec<AdversarialAlternative>,
}
