//! Store-query and evidence closure retained by every projection artifact.

use joshi_domain::{
    AsOfVector, AssertionId, CommitSeq, CoverageId, ObservationId, StableString, ValueDigest,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Minimal immutable reference to an effective branch selected by a store as-known query.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EffectiveAssertionRef {
    pub assertion_id: AssertionId,
    pub semantic_key: StableString,
    pub produced_commit_seq: CommitSeq,
    pub value_digest: ValueDigest,
    pub supersedes_assertion_id: Option<AssertionId>,
}

/// Explicit coverage state for one named projection input surface.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum CoverageStatus {
    Complete,
    Partial { reason: StableString },
    Gap { reason: StableString },
    Conflicting { reason: StableString },
    Unknown { reason: StableString },
}

/// Coverage conclusion with exact durable gap identities when present.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionCoverage {
    pub scope: StableString,
    pub status: CoverageStatus,
    pub gap_ids: Vec<CoverageId>,
}

/// Closed evidence and store-query horizon used by a projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionInputClosure {
    pub from_commit_seq: CommitSeq,
    pub through_commit_seq: CommitSeq,
    pub as_of: AsOfVector,
    pub controlled_domain_id: StableString,
    pub effective_assertions: Vec<EffectiveAssertionRef>,
    pub observation_ids: Vec<ObservationId>,
}

impl ProjectionInputClosure {
    /// Checks cutoff, finalized-chain, canonical-order, and effective-branch closure.
    ///
    /// # Errors
    ///
    /// Returns an explicit closure defect; no partial artifact should be emitted.
    pub fn validate(&self) -> Result<(), InputClosureError> {
        if self.from_commit_seq > self.through_commit_seq
            || self.through_commit_seq != self.as_of.catalog_commit
        {
            return Err(InputClosureError::CommitRange);
        }
        let chain = self
            .as_of
            .chain
            .as_ref()
            .ok_or(InputClosureError::MissingFinalizedChain)?;
        if chain.finality.is_unknown() || chain.finality.discriminator.as_str() != "finalized" {
            return Err(InputClosureError::MissingFinalizedChain);
        }
        if self
            .observation_ids
            .windows(2)
            .any(|window| window[0] >= window[1])
        {
            return Err(InputClosureError::ObservationOrder);
        }
        if self.effective_assertions.windows(2).any(|window| {
            (&window[0].semantic_key, &window[0].assertion_id)
                >= (&window[1].semantic_key, &window[1].assertion_id)
        }) {
            return Err(InputClosureError::AssertionOrder);
        }
        if self
            .effective_assertions
            .iter()
            .any(|assertion| assertion.produced_commit_seq > self.through_commit_seq)
        {
            return Err(InputClosureError::AssertionBeyondCutoff);
        }
        Ok(())
    }
}

/// Invalid evidence/store-query closure.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum InputClosureError {
    #[error("projection commit range is inverted or disagrees with as-of cutoff")]
    CommitRange,
    #[error("projection does not carry an exact finalized chain watermark")]
    MissingFinalizedChain,
    #[error("observation identities are not strictly ordered")]
    ObservationOrder,
    #[error("effective assertion references are not strictly ordered")]
    AssertionOrder,
    #[error("effective assertion was produced beyond the projection cutoff")]
    AssertionBeyondCutoff,
}
