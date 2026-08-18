use joshi_domain::{StableString, WireU64};
use serde::{Deserialize, Serialize};

use crate::{BAKEOFF_CONTRACT, BAKEOFF_SCHEMA_VERSION, BakeoffError};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StreamSide {
    Candidate,
    Reference,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Finality {
    Processed,
    Confirmed,
    Finalized,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DecodeOutcome {
    Decoded,
    Unsupported,
    Malformed,
    NotAttempted,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PredicateOutcome {
    Match,
    NoMatch,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GapReason {
    MissingHydration,
    FailedTransaction,
    LogTruncated,
    ReferenceIncomplete,
    CandidateDisconnect,
    FinalityUnknown,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageWindow {
    pub window_id: StableString,
    pub lower_slot: WireU64,
    pub upper_slot: WireU64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageGap {
    pub side: StreamSide,
    pub window_id: StableString,
    pub reason: GapReason,
    pub lower_slot: WireU64,
    pub upper_slot: WireU64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CandidateRecord {
    pub signature: StableString,
    pub slot: WireU64,
    pub finality: Finality,
    pub program_mentioned: bool,
    pub logs_truncated: bool,
    pub failed_transaction: bool,
    pub predicate: PredicateOutcome,
    pub bytes: WireU64,
    pub provider_credits: WireU64,
    pub latency_ms: WireU64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReferenceRecord {
    pub signature: StableString,
    pub slot: WireU64,
    pub finality: Finality,
    pub hydrated_exact: bool,
    pub failed_transaction: bool,
    pub decode: DecodeOutcome,
    pub predicate: PredicateOutcome,
    pub bytes: WireU64,
    pub provider_credits: WireU64,
    pub latency_ms: WireU64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CostCaps {
    pub max_candidate_bytes: WireU64,
    pub max_reference_bytes: WireU64,
    pub max_candidate_credits: WireU64,
    pub max_reference_credits: WireU64,
    pub max_total_latency_ms: WireU64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Thresholds {
    pub minimum_recall_ppm: WireU64,
    pub minimum_precision_ppm: WireU64,
    pub minimum_parser_yield_ppm: WireU64,
    pub maximum_candidate_gap_count: WireU64,
    pub maximum_reference_gap_count: WireU64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BakeoffInput {
    pub contract: String,
    pub schema_version: WireU64,
    pub run_id: StableString,
    pub window: CoverageWindow,
    pub candidate: Vec<CandidateRecord>,
    pub reference: Vec<ReferenceRecord>,
    pub gaps: Vec<CoverageGap>,
    pub caps: CostCaps,
    pub thresholds: Thresholds,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RatioPpm {
    pub numerator: WireU64,
    pub denominator: WireU64,
    pub parts_per_million: WireU64,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CountSummary {
    pub candidate_records: WireU64,
    pub reference_records: WireU64,
    pub candidate_program_mentions: WireU64,
    pub candidate_truncated: WireU64,
    pub candidate_failed: WireU64,
    pub candidate_duplicates: WireU64,
    pub reference_hydration_missing: WireU64,
    pub reference_failed: WireU64,
    pub reference_decode_failures: WireU64,
    pub reference_finality_corrections: WireU64,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    CensusQualified,
    SampleOnly,
    Unavailable,
    Refused,
}

/// Public evaluator outputs are explicitly unverified because this crate cannot mint store
/// receipts, coverage attestations, decoder provenance, or provider-cost authority.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BakeoffQualificationV1 {
    UnverifiedSemantic,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BakeoffMetrics {
    pub recall: RatioPpm,
    pub precision: RatioPpm,
    pub parser_yield: RatioPpm,
    pub candidate_latency_ms: RatioPpm,
    pub reference_latency_ms: RatioPpm,
    pub candidate_bytes: WireU64,
    pub reference_bytes: WireU64,
    pub candidate_credits: WireU64,
    pub reference_credits: WireU64,
    pub counts: CountSummary,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BakeoffResult {
    pub contract: String,
    pub schema_version: WireU64,
    pub run_id: StableString,
    pub window: CoverageWindow,
    pub disposition: Disposition,
    pub qualification: BakeoffQualificationV1,
    pub reason: StableString,
    pub metrics: Option<BakeoffMetrics>,
    pub candidate_gaps: Vec<CoverageGap>,
    pub reference_gaps: Vec<CoverageGap>,
}

impl BakeoffResult {
    /// Validates result identity and the public unverified qualification ceiling.
    ///
    /// # Errors
    ///
    /// Returns an error when a result attempts to claim a different contract or qualification.
    pub fn validate(&self) -> Result<(), BakeoffError> {
        if self.contract != BAKEOFF_CONTRACT
            || self.schema_version.get() != BAKEOFF_SCHEMA_VERSION
            || self.qualification != BakeoffQualificationV1::UnverifiedSemantic
        {
            return Err(BakeoffError::InvalidContract(
                "result identity or qualification",
            ));
        }
        Ok(())
    }

    /// Recomputes and compares the result against the exact retained input.
    ///
    /// # Errors
    ///
    /// Returns an error when any disposition, metric, gap, identity, or qualification differs
    /// from the deterministic evaluator output.
    pub fn validate_against(&self, input: &BakeoffInput) -> Result<(), BakeoffError> {
        self.validate()?;
        let expected = crate::evaluate(input)?;
        if self != &expected {
            return Err(BakeoffError::InvalidContract(
                "result does not recompute from input",
            ));
        }
        Ok(())
    }
}

impl BakeoffInput {
    /// # Errors
    ///
    /// Returns an error when the contract, schema, interval, thresholds, or declared gaps are
    /// malformed. Record placement and stream-specific duplicate rules are checked by the
    /// evaluator after this structural pass.
    pub fn validate(&self) -> Result<(), BakeoffError> {
        if self.contract != BAKEOFF_CONTRACT || self.schema_version.get() != BAKEOFF_SCHEMA_VERSION
        {
            return Err(BakeoffError::InvalidContract("contract or schema"));
        }
        if self.window.lower_slot.get() >= self.window.upper_slot.get() {
            return Err(BakeoffError::InvalidContract("window bounds"));
        }
        if self.thresholds.minimum_recall_ppm.get() > 1_000_000
            || self.thresholds.minimum_precision_ppm.get() > 1_000_000
            || self.thresholds.minimum_parser_yield_ppm.get() > 1_000_000
        {
            return Err(BakeoffError::InvalidContract("threshold ppm"));
        }
        for gap in &self.gaps {
            if gap.window_id != self.window.window_id
                || gap.lower_slot.get() >= gap.upper_slot.get()
            {
                return Err(BakeoffError::InvalidContract("gap window"));
            }
        }
        for side in [StreamSide::Candidate, StreamSide::Reference] {
            let mut intervals: Vec<_> = self
                .gaps
                .iter()
                .filter(|gap| gap.side == side)
                .map(|gap| (gap.lower_slot.get(), gap.upper_slot.get()))
                .collect();
            intervals.sort_unstable();
            if intervals.windows(2).any(|pair| pair[0].1 > pair[1].0) {
                return Err(BakeoffError::InvalidContract("overlapping coverage gaps"));
            }
        }
        Ok(())
    }
}
