use crate::{
    AttentionFact, ChainFinality, EffectiveFactRecord, EffectiveFactRef, FactProtection,
    LifecycleFact, MARKET_FACT_CONTRACT, MARKET_STATE_SNAPSHOT_CONTRACT, MarketFactPayload,
    MarketFactV1, MarketStateOutcome, MarketStateQuery, MarketStateRefusal, MarketStateSnapshotV1,
    MarketStream, PoolAdapterError, PoolProjection, READ_ONLY_AUTHORITY, RefusalCode, SelectedFact,
    SocialProductFact, StreamQuery, ValidityBasis, adapt_pool_bundle,
};
use joshi_attention::{AssertionStatus, ClusterSelectionDisposition, ProtectionDomain};
use joshi_domain::{CommitSeq, StableString};
#[cfg(feature = "sqlite-store")]
use joshi_store::SqliteStore;
use std::collections::BTreeSet;
use thiserror::Error;

/// Failure at the narrow durable-read boundary.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
#[error("effective assertion read failed: {detail}")]
pub struct ReaderError {
    pub detail: String,
}

/// Only the exact historical assertion query needed by the reducer.
pub trait EffectiveFactReader {
    /// Returns every non-retracted effective branch for one key at the explicit commit cutoff.
    /// Implementations must not consult a latest/current helper.
    ///
    /// # Errors
    ///
    /// Returns a storage/read boundary failure without inventing an empty result.
    fn effective_assertions_as_known(
        &self,
        semantic_key: &str,
        cutoff: CommitSeq,
    ) -> Result<Vec<EffectiveFactRecord>, ReaderError>;
}

#[cfg(feature = "sqlite-store")]
impl EffectiveFactReader for SqliteStore {
    fn effective_assertions_as_known(
        &self,
        semantic_key: &str,
        cutoff: CommitSeq,
    ) -> Result<Vec<EffectiveFactRecord>, ReaderError> {
        SqliteStore::effective_assertions_as_known(self, semantic_key, cutoff)
            .map(|assertions| {
                assertions
                    .into_iter()
                    .map(|assertion| EffectiveFactRecord {
                        assertion_id: assertion.assertion_id,
                        semantic_key: assertion.semantic_key,
                        produced_commit: assertion.produced_commit_seq,
                        value: assertion.value,
                        value_digest: assertion.value_digest,
                        supersedes_assertion_id: assertion.supersedes_assertion_id,
                    })
                    .collect()
            })
            .map_err(|error| ReaderError {
                detail: error.to_string(),
            })
    }
}

/// Deterministic, read-only market-state reducer over a durable effective-as-known view.
pub struct MarketStateReducer<'a, R> {
    reader: &'a R,
}

impl<'a, R: EffectiveFactReader> MarketStateReducer<'a, R> {
    #[must_use]
    pub const fn new(reader: &'a R) -> Self {
        Self { reader }
    }

    /// Reduces the four explicit streams or emits a typed refusal artifact.
    #[must_use]
    pub fn reduce(&self, query: MarketStateQuery) -> MarketStateOutcome {
        let mut closure = Vec::new();
        if let Err((code, detail)) = validate_query(&query) {
            return refused(query, code, None, detail, closure);
        }

        let social = match self.load_stream(
            &query,
            &query.social_product,
            MarketStream::SocialProduct,
            &mut closure,
        ) {
            Ok(facts) => facts,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };
        let lifecycle = match self.load_stream(
            &query,
            &query.lifecycle,
            MarketStream::Lifecycle,
            &mut closure,
        ) {
            Ok(facts) => facts,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };
        let pool = match self.load_stream(
            &query,
            &query.pool_state,
            MarketStream::PoolState,
            &mut closure,
        ) {
            Ok(facts) => facts,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };
        let attention = match self.load_stream(
            &query,
            &query.attention,
            MarketStream::Attention,
            &mut closure,
        ) {
            Ok(facts) => facts,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };

        let social_product = match social
            .into_iter()
            .map(select_social)
            .collect::<Result<Vec<_>, _>>()
        {
            Ok(selected) => selected,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };
        let lifecycle = match lifecycle
            .into_iter()
            .map(|fact| select_lifecycle(fact, &query))
            .collect::<Result<Vec<_>, _>>()
        {
            Ok(selected) => selected,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };
        let pool_state = match pool
            .into_iter()
            .map(|fact| select_pool(fact, &query))
            .collect::<Result<Vec<_>, _>>()
        {
            Ok(selected) => selected,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };
        let attention = match attention
            .into_iter()
            .map(|fact| select_attention(fact, &query))
            .collect::<Result<Vec<_>, _>>()
        {
            Ok(selected) => selected,
            Err(failure) => return refusal_from_failure(query, failure, closure),
        };
        closure.sort_by(|left, right| {
            (&left.semantic_key, &left.assertion_id)
                .cmp(&(&right.semantic_key, &right.assertion_id))
        });

        MarketStateOutcome::Accepted(MarketStateSnapshotV1 {
            contract: static_stable(MARKET_STATE_SNAPSHOT_CONTRACT),
            artifact_id: query.artifact_id,
            subject_id: query.subject_id,
            authority: static_stable(READ_ONLY_AUTHORITY),
            cut: query.cut,
            social_product,
            lifecycle,
            pool_state,
            attention,
            input_closure: closure,
        })
    }

    fn load_stream(
        &self,
        query: &MarketStateQuery,
        stream_query: &StreamQuery,
        expected_stream: MarketStream,
        closure: &mut Vec<EffectiveFactRef>,
    ) -> Result<Vec<LoadedFact>, Failure> {
        if !stream_query.enabled {
            return Ok(Vec::new());
        }
        let mut loaded = Vec::with_capacity(stream_query.semantic_keys.len());
        for semantic_key in &stream_query.semantic_keys {
            let branches = self
                .reader
                .effective_assertions_as_known(semantic_key.as_str(), query.cut.known_by_commit)
                .map_err(|error| {
                    Failure::new(
                        RefusalCode::StoreRead,
                        Some(semantic_key.clone()),
                        error.to_string(),
                    )
                })?;
            let [assertion] = branches.as_slice() else {
                let code = if branches.is_empty() {
                    RefusalCode::MissingEffectiveFact
                } else {
                    RefusalCode::AmbiguousEffectiveBranch
                };
                return Err(Failure::new(
                    code,
                    Some(semantic_key.clone()),
                    format!("expected one effective branch, observed {}", branches.len()),
                ));
            };
            let loaded_fact = validate_effective(assertion, expected_stream, query)?;
            closure.push(loaded_fact.reference.clone());
            loaded.push(loaded_fact);
        }
        Ok(loaded)
    }
}

#[derive(Clone, Debug)]
struct LoadedFact {
    reference: EffectiveFactRef,
    value: MarketFactV1,
}

#[derive(Clone, Debug)]
struct Failure {
    code: RefusalCode,
    semantic_key: Option<StableString>,
    detail: String,
}

impl Failure {
    fn new(
        code: RefusalCode,
        semantic_key: Option<StableString>,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            code,
            semantic_key,
            detail: detail.into(),
        }
    }
}

fn validate_query(query: &MarketStateQuery) -> Result<(), (RefusalCode, String)> {
    let streams = [
        &query.social_product,
        &query.lifecycle,
        &query.pool_state,
        &query.attention,
    ];
    if streams.iter().all(|stream| !stream.enabled) {
        return Err((
            RefusalCode::InvalidQuery,
            "a market-state snapshot requires at least one enabled stream".into(),
        ));
    }
    if streams
        .iter()
        .any(|stream| stream.enabled == stream.semantic_keys.is_empty())
    {
        return Err((
            RefusalCode::InvalidQuery,
            "enabled streams require keys and disabled streams forbid keys".into(),
        ));
    }
    if streams.iter().any(|stream| {
        stream
            .semantic_keys
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
    }) {
        return Err((
            RefusalCode::InvalidQuery,
            "semantic keys within each stream must be strictly sorted".into(),
        ));
    }
    if query.pool_state.enabled && query.pool_state.semantic_keys.len() != 1 {
        return Err((
            RefusalCode::InvalidQuery,
            "pool_state requires exactly one coherent bundle key".into(),
        ));
    }
    let mut keys = BTreeSet::new();
    if streams
        .iter()
        .flat_map(|stream| stream.semantic_keys.iter())
        .any(|key| !keys.insert(key.as_str()))
    {
        return Err((
            RefusalCode::InvalidQuery,
            "semantic keys must be unique across all streams".into(),
        ));
    }
    if query.cut.known_by_commit == CommitSeq::ZERO {
        return Err((
            RefusalCode::InvalidQuery,
            "knowledge cutoff must name a durable positive commit".into(),
        ));
    }
    Ok(())
}

fn validate_effective(
    assertion: &EffectiveFactRecord,
    expected_stream: MarketStream,
    query: &MarketStateQuery,
) -> Result<LoadedFact, Failure> {
    let key = Some(assertion.semantic_key.clone());
    if assertion.produced_commit > query.cut.known_by_commit {
        return Err(Failure::new(
            RefusalCode::FutureProducedCommit,
            key,
            "reader returned an assertion produced after the explicit cutoff",
        ));
    }
    let value: MarketFactV1 = serde_json::from_value(assertion.value.clone()).map_err(|error| {
        Failure::new(
            RefusalCode::UnsupportedContract,
            key.clone(),
            format!("market fact failed strict decode: {error}"),
        )
    })?;
    if value.contract.as_str() != MARKET_FACT_CONTRACT {
        return Err(Failure::new(
            RefusalCode::UnsupportedContract,
            key,
            "market fact contract is not supported",
        ));
    }
    if value.stream != expected_stream || payload_stream(&value.payload) != expected_stream {
        return Err(Failure::new(
            RefusalCode::WrongStream,
            key,
            "stream discriminator and payload must match the requested stream",
        ));
    }
    if value.subject_id != query.subject_id {
        return Err(Failure::new(
            RefusalCode::WrongSubject,
            key,
            "fact subject does not match the point-in-time query",
        ));
    }
    if value.available_at > query.cut.known_by || value.available_commit > query.cut.known_by_commit
    {
        return Err(Failure::new(
            RefusalCode::NotKnownByCut,
            key,
            "fact was not available by both wall-time and commit cutoffs",
        ));
    }
    if value.validity_basis == ValidityBasis::CaptureAttestationOnly {
        return Err(Failure::new(
            RefusalCode::CaptureAttestationIsNotValidity,
            key,
            "capture bounds cannot establish object/event validity",
        ));
    }
    let valid_time = value.valid_time.as_ref().ok_or_else(|| {
        Failure::new(
            RefusalCode::InvalidValidInterval,
            key.clone(),
            "non-capture fact has no valid-time interval",
        )
    })?;
    if !valid_time.is_well_formed() {
        return Err(Failure::new(
            RefusalCode::InvalidValidInterval,
            key,
            "valid-time interval is not half-open and increasing",
        ));
    }
    if !valid_time.contains(query.cut.valid_at) {
        return Err(Failure::new(
            RefusalCode::NotValidAtCut,
            key,
            "fact is effective-as-known but not valid at the requested event/object time",
        ));
    }
    if value.evidence.observation_ids.is_empty() || value.evidence.source_ids.is_empty() {
        return Err(Failure::new(
            RefusalCode::MissingEvidence,
            key,
            "fact cannot be traced to an observation and source",
        ));
    }
    let reference = EffectiveFactRef {
        assertion_id: assertion.assertion_id.clone(),
        semantic_key: assertion.semantic_key.clone(),
        produced_commit: assertion.produced_commit,
        value_digest: assertion.value_digest.clone(),
        supersedes_assertion_id: assertion.supersedes_assertion_id.clone(),
        available_at: value.available_at,
        available_commit: value.available_commit,
        evidence: value.evidence.clone(),
    };
    Ok(LoadedFact { reference, value })
}

const fn payload_stream(payload: &MarketFactPayload) -> MarketStream {
    match payload {
        MarketFactPayload::SocialProduct(_) => MarketStream::SocialProduct,
        MarketFactPayload::Lifecycle(_) => MarketStream::Lifecycle,
        MarketFactPayload::PoolState(_) => MarketStream::PoolState,
        MarketFactPayload::Attention(_) => MarketStream::Attention,
    }
}

fn select_social(fact: LoadedFact) -> Result<SelectedFact<SocialProductFact>, Failure> {
    let MarketFactPayload::SocialProduct(value) = fact.value.payload else {
        return Err(Failure::new(
            RefusalCode::InvalidSocialFact,
            Some(fact.reference.semantic_key),
            "social payload mismatch",
        ));
    };
    if value.input.evidence.observation_id != fact.reference.evidence.observation_ids[0]
        || value.input.evidence.source_id != fact.reference.evidence.source_ids[0]
        || protection(value.input.evidence.protection_domain) != fact.reference.evidence.protection
    {
        return Err(Failure::new(
            RefusalCode::InvalidSocialFact,
            Some(fact.reference.semantic_key),
            "social occurrence does not match the fact evidence closure",
        ));
    }
    Ok(SelectedFact {
        effective: fact.reference,
        value: *value,
    })
}

fn select_lifecycle(
    fact: LoadedFact,
    query: &MarketStateQuery,
) -> Result<SelectedFact<LifecycleFact>, Failure> {
    let key = Some(fact.reference.semantic_key.clone());
    let MarketFactPayload::Lifecycle(value) = fact.value.payload else {
        return Err(Failure::new(
            RefusalCode::InvalidLifecycleFact,
            key,
            "lifecycle payload mismatch",
        ));
    };
    match value.as_ref() {
        LifecycleFact::FinalizedChain {
            observation_id,
            source_id,
            ..
        } => {
            let Some(chain) = fact.value.chain else {
                return Err(Failure::new(
                    RefusalCode::InvalidLifecycleFact,
                    key,
                    "chain lifecycle fact has no chain point",
                ));
            };
            if fact.value.validity_basis != ValidityBasis::FinalizedChainSlot
                || chain.finality != ChainFinality::Finalized
                || chain.slot > query.cut.finalized_chain_slot
                || !fact
                    .reference
                    .evidence
                    .observation_ids
                    .contains(observation_id)
                || !fact.reference.evidence.source_ids.contains(source_id)
            {
                return Err(Failure::new(
                    RefusalCode::InvalidLifecycleFact,
                    key,
                    "chain lifecycle authority/finality/slot/evidence is incoherent",
                ));
            }
        }
        LifecycleFact::ProductHint {
            observation_id,
            source_id,
            ..
        } => {
            if fact.value.chain.is_some()
                || fact.value.validity_basis == ValidityBasis::FinalizedChainSlot
                || !fact
                    .reference
                    .evidence
                    .observation_ids
                    .contains(observation_id)
                || !fact.reference.evidence.source_ids.contains(source_id)
            {
                return Err(Failure::new(
                    RefusalCode::InvalidLifecycleFact,
                    key,
                    "provider hint must remain non-chain provider evidence",
                ));
            }
        }
    }
    Ok(SelectedFact {
        effective: fact.reference,
        value: *value,
    })
}

fn select_pool(
    fact: LoadedFact,
    query: &MarketStateQuery,
) -> Result<SelectedFact<PoolProjection>, Failure> {
    let key = Some(fact.reference.semantic_key.clone());
    let MarketFactPayload::PoolState(bundle) = fact.value.payload else {
        return Err(Failure::new(
            RefusalCode::PoolClosureUnsupported,
            key,
            "pool payload mismatch",
        ));
    };
    let Some(chain) = fact.value.chain else {
        return Err(Failure::new(
            RefusalCode::PoolClosureNotFinalized,
            key,
            "pool bundle has no chain point",
        ));
    };
    if fact.value.validity_basis != ValidityBasis::FinalizedChainSlot
        || chain.finality != ChainFinality::Finalized
        || chain.slot != query.cut.finalized_chain_slot
        || bundle.slot != query.cut.finalized_chain_slot
    {
        return Err(Failure::new(
            RefusalCode::PoolClosureNotFinalized,
            key,
            "pool bundle must be the exact finalized slot requested by the snapshot",
        ));
    }
    let projection = adapt_pool_bundle(&bundle).map_err(|error| {
        let code = match error {
            PoolAdapterError::EmptyClosure | PoolAdapterError::MissingRole(_) => {
                RefusalCode::PoolClosureIncomplete
            }
            PoolAdapterError::MixedSlot => RefusalCode::PoolClosureMixedSlot,
            PoolAdapterError::NotFinalized => RefusalCode::PoolClosureNotFinalized,
            PoolAdapterError::KernelRefusal(_) => RefusalCode::PoolKernelRefused,
            _ => RefusalCode::PoolClosureUnsupported,
        };
        Failure::new(code, key.clone(), error.to_string())
    })?;
    Ok(SelectedFact {
        effective: fact.reference,
        value: projection,
    })
}

#[allow(clippy::too_many_lines)] // Context families retain distinct bitemporal predicates.
fn select_attention(
    fact: LoadedFact,
    query: &MarketStateQuery,
) -> Result<SelectedFact<AttentionFact>, Failure> {
    let key = Some(fact.reference.semantic_key.clone());
    let MarketFactPayload::Attention(value) = fact.value.payload else {
        return Err(Failure::new(
            RefusalCode::InvalidAttentionFact,
            key,
            "attention payload mismatch",
        ));
    };
    if value.event.available_at > query.cut.known_by
        || value.event.available_commit > query.cut.known_by_commit
        || value.event.forcing_input_id != value.forcing_input.input_id
        || value.forcing_input.evidence.observation_id != fact.reference.evidence.observation_ids[0]
        || protection(value.forcing_input.evidence.protection_domain)
            != fact.reference.evidence.protection
    {
        return Err(Failure::new(
            RefusalCode::InvalidAttentionFact,
            key,
            "marked event availability, forcing occurrence, or evidence is incoherent",
        ));
    }
    if let Some(identity) = &value.selected_identity
        && (identity.status == AssertionStatus::Retracted
            || identity.knowledge_time.available_commit > query.cut.known_by_commit
            || identity.knowledge_time.known_from > query.cut.known_by
            || identity
                .knowledge_time
                .known_until
                .is_some_and(|until| query.cut.known_by >= until)
            || identity.valid_time.lower > query.cut.valid_at
            || identity
                .valid_time
                .upper
                .is_some_and(|upper| query.cut.valid_at >= upper))
    {
        return Err(Failure::new(
            RefusalCode::InvalidAttentionFact,
            key,
            "selected identity was not valid and known at the exact cut",
        ));
    }
    if let Some(territory) = &value.selected_territory
        && (territory.status == AssertionStatus::Retracted
            || territory.knowledge_time.available_commit > query.cut.known_by_commit
            || territory.knowledge_time.known_from > query.cut.known_by
            || territory
                .knowledge_time
                .known_until
                .is_some_and(|until| query.cut.known_by >= until)
            || territory.valid_time.lower > query.cut.valid_at
            || territory
                .valid_time
                .upper
                .is_some_and(|upper| query.cut.valid_at >= upper))
    {
        return Err(Failure::new(
            RefusalCode::InvalidAttentionFact,
            key,
            "selected territory was not valid and known at the exact cut",
        ));
    }
    if let Some(cluster) = &value.selected_cluster
        && (cluster.source_status == AssertionStatus::Retracted
            || cluster.selection_disposition
                != ClusterSelectionDisposition::LatestEffectiveKnownForExactCut
            || cluster.source_available_commit > query.cut.known_by_commit
            || cluster.selected_as_of_commit > query.cut.known_by_commit
            || cluster.source_available_at > query.cut.known_by
            || cluster.selected_as_of > query.cut.known_by
            || cluster.valid_time.lower > query.cut.valid_at
            || cluster
                .valid_time
                .upper
                .is_some_and(|upper| query.cut.valid_at >= upper)
            || cluster.valid_slots.as_ref().is_some_and(|slots| {
                query.cut.finalized_chain_slot < slots.lower
                    || slots
                        .upper
                        .is_some_and(|upper| query.cut.finalized_chain_slot >= upper)
            }))
    {
        return Err(Failure::new(
            RefusalCode::InvalidAttentionFact,
            key,
            "selected cluster was not valid and selected-as-known at the exact cut",
        ));
    }
    if value.response_observations.iter().any(|response| {
        response.available_at > query.cut.known_by || response.analysis_cutoff > query.cut.known_by
    }) {
        return Err(Failure::new(
            RefusalCode::InvalidAttentionFact,
            key,
            "response row was not available by the exact cut",
        ));
    }
    Ok(SelectedFact {
        effective: fact.reference,
        value: *value,
    })
}

fn refusal_from_failure(
    query: MarketStateQuery,
    failure: Failure,
    closure: Vec<EffectiveFactRef>,
) -> MarketStateOutcome {
    refused(
        query,
        failure.code,
        failure.semantic_key,
        failure.detail,
        closure,
    )
}

fn refused(
    query: MarketStateQuery,
    code: RefusalCode,
    semantic_key: Option<StableString>,
    detail: impl AsRef<str>,
    closure: Vec<EffectiveFactRef>,
) -> MarketStateOutcome {
    MarketStateOutcome::Refused(MarketStateRefusal {
        contract: static_stable(MARKET_STATE_SNAPSHOT_CONTRACT),
        artifact_id: query.artifact_id.clone(),
        authority: static_stable(READ_ONLY_AUTHORITY),
        query,
        code,
        semantic_key,
        detail: safe_detail(detail.as_ref()),
        inputs_read_before_refusal: closure,
    })
}

fn safe_detail(detail: &str) -> StableString {
    let cleaned: String = detail
        .chars()
        .filter(|character| !character.is_control())
        .take(500)
        .collect();
    StableString::new(if cleaned.trim().is_empty() {
        "unspecified reducer refusal"
    } else {
        cleaned.trim()
    })
    .unwrap_or_else(|_| static_stable("invalid reducer refusal detail"))
}

fn static_stable(value: &'static str) -> StableString {
    StableString::new(value).unwrap_or_else(|_| unreachable!("static stable string is valid"))
}

const fn protection(value: ProtectionDomain) -> FactProtection {
    match value {
        ProtectionDomain::PublicProtocol | ProtectionDomain::PublicProduct => {
            FactProtection::PublicIntegrity
        }
        ProtectionDomain::AuthenticatedPrivateSocial => FactProtection::AuthenticatedPrivate,
        ProtectionDomain::OperatorPrivate => FactProtection::OperatorPrivate,
        ProtectionDomain::DerivedRestricted => FactProtection::DerivedRestricted,
    }
}
