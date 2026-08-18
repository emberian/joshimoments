//! Stable accessible metric wrappers and epistemic status.

use joshi_domain::{CoverageId, ObservationId, StableString, UtcTimestamp, ValueDigest, WireU64};
use serde::{Deserialize, Serialize};

/// How a fact entered the view; this must not be inferred from its visual treatment.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpistemicClass {
    Observed,
    DeterministicCalculation,
}

/// Typed value availability. Missing, unknown, unsupported, stale, and conflict are not zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum MetricReading<T> {
    Known {
        value: T,
    },
    Stale {
        value: T,
        reason: StableString,
    },
    Conflicting {
        candidates: Vec<T>,
        reason: StableString,
    },
    Missing {
        reason: StableString,
    },
    Unknown {
        reason: StableString,
    },
    Unsupported {
        reason: StableString,
    },
    Refused {
        reason: StableString,
    },
}

/// Dimension of an exact metric. A display label is never its unit authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum MetricUnit {
    AssetAtoms {
        asset_id: joshi_domain::AssetId,
        decimals: u8,
        definition_observation_id: ObservationId,
    },
    AtomicPriceRatio {
        quote_asset_id: joshi_domain::AssetId,
        base_asset_id: joshi_domain::AssetId,
    },
    LiquidityShare,
    Q64x64Price,
    BasisPoints,
    Count,
}

/// One exact, stable, accessible metric. The enclosing projection result digest binds it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExactMetric<T> {
    pub metric_id: StableString,
    pub semantic_label: StableString,
    pub epistemic_class: EpistemicClass,
    pub reading: MetricReading<T>,
    pub unit: MetricUnit,
    pub evidence: Vec<ObservationId>,
    pub source_value_digest: Option<ValueDigest>,
    pub rendering_hint: Option<StableString>,
}

/// Whether an observation-bound calculation is still eligible for display as current.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MonotonicValidityWindow {
    pub clock_id: StableString,
    pub observed_mono_ns: WireU64,
    pub expires_mono_ns: WireU64,
}

/// Coverage of the state/route observations used for one calculation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ValidityCoverage {
    Complete,
    Partial {
        gap_ids: Vec<CoverageId>,
        reason: StableString,
    },
    Conflicting {
        reason: StableString,
    },
    Unknown {
        reason: StableString,
    },
}

/// Whether an observation-bound calculation is still eligible for display as current.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum Freshness {
    Fresh {
        state_received_at: UtcTimestamp,
        evaluated_at: UtcTimestamp,
        expires_at: UtcTimestamp,
        monotonic: MonotonicValidityWindow,
        evaluated_slot: WireU64,
        valid_through_slot: WireU64,
        coverage: ValidityCoverage,
    },
    Stale {
        state_received_at: UtcTimestamp,
        evaluated_at: UtcTimestamp,
        expires_at: UtcTimestamp,
        monotonic: MonotonicValidityWindow,
        evaluated_slot: WireU64,
        valid_through_slot: WireU64,
        coverage: ValidityCoverage,
        reason: StableString,
    },
    Conflicting {
        reason: StableString,
    },
    Unknown {
        reason: StableString,
    },
}

impl Freshness {
    /// Validates the declared slot relation.
    ///
    /// # Errors
    ///
    /// Returns a static description if a fresh/stale claim contradicts its exact slots.
    pub fn validate(&self) -> Result<(), &'static str> {
        let coverage = match self {
            Self::Fresh { coverage, .. } | Self::Stale { coverage, .. } => Some(coverage),
            Self::Conflicting { .. } | Self::Unknown { .. } => None,
        };
        if let Some(ValidityCoverage::Partial { gap_ids, .. }) = coverage
            && (gap_ids.is_empty() || gap_ids.windows(2).any(|window| window[0] >= window[1]))
        {
            return Err("partial validity coverage requires sorted unique gap identities");
        }
        match self {
            Self::Fresh {
                state_received_at,
                evaluated_at,
                expires_at,
                monotonic,
                evaluated_slot,
                valid_through_slot,
                ..
            } if state_received_at > evaluated_at
                || evaluated_at > expires_at
                || evaluated_slot > valid_through_slot
                || monotonic.observed_mono_ns >= monotonic.expires_mono_ns =>
            {
                Err("fresh validity window contradicts its wall, monotonic, or slot bounds")
            }
            Self::Stale {
                state_received_at,
                evaluated_at,
                expires_at,
                monotonic,
                evaluated_slot,
                valid_through_slot,
                ..
            } if state_received_at > expires_at
                || monotonic.observed_mono_ns >= monotonic.expires_mono_ns
                || (evaluated_at <= expires_at && evaluated_slot <= valid_through_slot) =>
            {
                Err("stale validity window has not expired or has malformed bounds")
            }
            _ => Ok(()),
        }
    }
}
