use crate::{
    ChainFinality, FactEvidence, LifecycleFact, MARKET_FACT_CONTRACT, MarketFactPayload,
    MarketFactV1, MarketStream, ValidityBasis,
};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp};
use thiserror::Error;

use crate::{CaptureAttestation, ChainPoint, ValidInterval};

/// Temporal, provenance, and chain context shared by one lifecycle statement.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LifecycleFactContext {
    pub subject_id: StableString,
    pub valid_time: ValidInterval,
    pub validity_basis: ValidityBasis,
    pub available_at: UtcTimestamp,
    pub available_commit: CommitSeq,
    pub capture_attestation: Option<CaptureAttestation>,
    pub chain: Option<ChainPoint>,
    pub evidence: FactEvidence,
}

/// Strict lifecycle authority/provenance failure.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum LifecycleAdapterError {
    #[error("lifecycle valid-time interval is malformed")]
    InvalidValidTime,
    #[error("lifecycle fact has no observation or source evidence")]
    MissingEvidence,
    #[error("finalized lifecycle fact lacks exact finalized-chain authority")]
    InvalidChainAuthority,
    #[error("product lifecycle hint attempted to claim chain authority")]
    ProductHintClaimsChainTruth,
    #[error("lifecycle payload evidence does not match its fact closure")]
    EvidenceMismatch,
}

/// Wraps a typed lifecycle fact while preserving the chain/provider authority distinction.
///
/// # Errors
///
/// Refuses malformed validity, missing/mismatched evidence, non-final chain facts, and product
/// hints that attempt to use chain authority.
pub fn adapt_lifecycle_fact(
    context: LifecycleFactContext,
    lifecycle: LifecycleFact,
) -> Result<MarketFactV1, LifecycleAdapterError> {
    if !context.valid_time.is_well_formed() {
        return Err(LifecycleAdapterError::InvalidValidTime);
    }
    if context.evidence.observation_ids.is_empty() || context.evidence.source_ids.is_empty() {
        return Err(LifecycleAdapterError::MissingEvidence);
    }
    let (observation_id, source_id) = match &lifecycle {
        LifecycleFact::FinalizedChain {
            observation_id,
            source_id,
            ..
        } => {
            if context.validity_basis != ValidityBasis::FinalizedChainSlot
                || context
                    .chain
                    .as_ref()
                    .is_none_or(|chain| chain.finality != ChainFinality::Finalized)
            {
                return Err(LifecycleAdapterError::InvalidChainAuthority);
            }
            (observation_id, source_id)
        }
        LifecycleFact::ProductHint {
            observation_id,
            source_id,
            ..
        } => {
            if context.validity_basis == ValidityBasis::FinalizedChainSlot
                || context.chain.is_some()
            {
                return Err(LifecycleAdapterError::ProductHintClaimsChainTruth);
            }
            (observation_id, source_id)
        }
    };
    if !context.evidence.observation_ids.contains(observation_id)
        || !context.evidence.source_ids.contains(source_id)
    {
        return Err(LifecycleAdapterError::EvidenceMismatch);
    }
    Ok(MarketFactV1 {
        contract: StableString::new(MARKET_FACT_CONTRACT)
            .unwrap_or_else(|_| unreachable!("static contract is valid")),
        stream: MarketStream::Lifecycle,
        subject_id: context.subject_id,
        valid_time: Some(context.valid_time),
        validity_basis: context.validity_basis,
        available_at: context.available_at,
        available_commit: context.available_commit,
        capture_attestation: context.capture_attestation,
        chain: context.chain,
        evidence: context.evidence,
        payload: MarketFactPayload::Lifecycle(Box::new(lifecycle)),
    })
}
