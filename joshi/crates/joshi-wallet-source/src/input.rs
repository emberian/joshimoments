use joshi_domain::{StableString, UtcTimestamp};
use serde::{Deserialize, Serialize};

use crate::{ParticipantRelation, PublicKey, ReadBudget};

/// Epistemic status of an address supplied by an upstream resolver or the operator.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CandidateEpistemicStatus {
    /// Exact provider claim, such as the wallet field on a particular profile revision.
    ProviderClaim,
    /// Exact on-chain fact, such as signing one classified instruction.
    OnChainFact,
    /// Operator-selected public address without an ownership claim.
    OperatorSelected,
    /// Versioned machine inference that remains a hypothesis.
    Inferred,
    /// Contradicted or retracted candidate retained for replay.
    Retracted,
    /// Unknown forward-compatible status.
    Other(StableString),
}

/// One candidate public wallet. This is never a private-key or ownership record.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CandidateWalletInput {
    pub candidate_id: StableString,
    pub wallet: PublicKey,
    pub relation: ParticipantRelation,
    pub epistemic_status: CandidateEpistemicStatus,
    pub subject_id: Option<StableString>,
    pub inference_version: Option<StableString>,
    pub evidence_observation_ids: Vec<StableString>,
    pub evidence_coverage_ids: Vec<StableString>,
    pub valid_from: Option<UtcTimestamp>,
    pub valid_to: Option<UtcTimestamp>,
    pub available_at: UtcTimestamp,
}

/// One participant candidate interpreted only relative to a named mint.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CohortParticipant {
    pub wallet: CandidateWalletInput,
    pub mint_relation: ParticipantRelation,
    pub relation_evidence_ids: Vec<StableString>,
}

/// Versioned, evidence-bound mint cohort supplied by another projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MintCohortInput {
    pub cohort_id: StableString,
    pub cohort_version: StableString,
    pub mint: PublicKey,
    pub participants: Vec<CohortParticipant>,
    pub derivation_method: StableString,
    pub evidence_observation_ids: Vec<StableString>,
    pub evidence_coverage_ids: Vec<StableString>,
    pub available_at: UtcTimestamp,
}

/// Explicit acquisition target. A cohort never expands itself by crawling neighbors.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ScopeTarget {
    Wallet { candidate: CandidateWalletInput },
    MintCohort { cohort: MintCohortInput },
}

impl ScopeTarget {
    #[must_use]
    pub fn public_keys(&self) -> Vec<PublicKey> {
        match self {
            Self::Wallet { candidate } => vec![candidate.wallet.clone()],
            Self::MintCohort { cohort } => cohort
                .participants
                .iter()
                .map(|participant| participant.wallet.wallet.clone())
                .collect(),
        }
    }

    #[must_use]
    pub fn mint(&self) -> Option<&PublicKey> {
        match self {
            Self::Wallet { .. } => None,
            Self::MintCohort { cohort } => Some(&cohort.mint),
        }
    }
}

/// Versioned input to the leased source plane.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ScopeInput {
    pub contract_version: StableString,
    pub scope_id: StableString,
    pub target: ScopeTarget,
    pub requested_at: UtcTimestamp,
    pub available_at: UtcTimestamp,
    pub evidence_input_ids: Vec<StableString>,
    pub evidence_coverage_ids: Vec<StableString>,
    pub budget: ReadBudget,
}

/// Shape requested by an upstream attention router.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PromotionScope {
    WalletLiveAndBackfill,
    MintCohortLiveAndBackfill,
    BackfillOnly,
    Other(StableString),
}

/// Evidence references from Pump callout/follow observations into this independent source.
///
/// The social payload is not copied into a chain record. This value says only that a separate,
/// retained input requested a bounded public-key scope.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AttentionPromotionInput {
    pub contract_version: StableString,
    pub promotion_id: StableString,
    pub mint_id: PublicKey,
    pub wallet_id: Option<PublicKey>,
    /// Event-bound caller-cluster context selected by the social transition plane.
    pub caller_cluster_context_id: Option<StableString>,
    /// Source hypothesis resolved through `caller_cluster_context_id`, never a bare current label.
    pub source_cluster_hypothesis_id: Option<StableString>,
    pub reason_variant: StableString,
    pub requested_hot_scope: PromotionScope,
    pub as_of_available_at: UtcTimestamp,
    pub expires_at: UtcTimestamp,
    pub evidence_input_ids: Vec<StableString>,
    pub evidence_coverage_ids: Vec<StableString>,
    pub derivation_version: StableString,
}

impl AttentionPromotionInput {
    /// Rejects an unbound cluster hypothesis that could leak future/current cluster knowledge into
    /// an earlier social event.
    ///
    /// # Errors
    ///
    /// A source cluster hypothesis is valid only when accompanied by the event-bound selected
    /// cluster context that resolved it.
    pub const fn validate_cluster_binding(&self) -> Result<(), AttentionPromotionError> {
        if self.source_cluster_hypothesis_id.is_some() && self.caller_cluster_context_id.is_none() {
            Err(AttentionPromotionError::BareClusterHypothesis)
        } else {
            Ok(())
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum AttentionPromotionError {
    #[error("cluster hypothesis requires an event-bound selected cluster context")]
    BareClusterHypothesis,
}
