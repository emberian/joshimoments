use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{AccountId, AssetId, StableString, UtcTimestamp, VenueId, WireU64, WireU128};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    ARROW_TABLE_CONTRACT_VERSION, AssetLegDirection, BundleId, BundleLegRow, CohortAggregateRow,
    ConcentrationInputRow, CoverageBinding, CycleInputRow, DerivationId, DivergenceRow,
    EvidenceClass, FlowEdgeRow, HypothesisClaim, IncidenceRow, IncidenceSign, RouteLegRow,
    SignedAtoms, SnapshotRequest, SwapFact, SwapId, TOPOLOGY_CONTRACT_VERSION, TopologyFact,
    TopologyFactRef, TopologyHypothesis, TopologyNodeRef, TopologySnapshot, TransactionFact,
    TransactionFactId, TransactionId, WalletMintCohortRow, WalletPairCoTradeRow,
};

/// Bounded input envelope for one point-in-time reduction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TopologyInput {
    pub contract: StableString,
    pub facts: Vec<TopologyFact>,
    pub hypotheses: Vec<TopologyHypothesis>,
}

/// Hard reducer bounds. Exceeding one is visible failure, never silent truncation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReducerConfig {
    pub max_facts: usize,
    pub max_hypotheses: usize,
    pub max_pair_activities: usize,
    pub max_pair_rows: usize,
}

impl ReducerConfig {
    /// Validates nonzero reducer bounds.
    ///
    /// # Errors
    ///
    /// Refuses any zero bound.
    pub const fn new(
        max_facts: usize,
        max_hypotheses: usize,
        max_pair_activities: usize,
        max_pair_rows: usize,
    ) -> Result<Self, TopologyError> {
        if max_facts == 0 || max_hypotheses == 0 || max_pair_activities == 0 || max_pair_rows == 0 {
            Err(TopologyError::InvalidBound)
        } else {
            Ok(Self {
                max_facts,
                max_hypotheses,
                max_pair_activities,
                max_pair_rows,
            })
        }
    }
}

/// Validation or checked-reduction failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum TopologyError {
    #[error("a reducer bound must be positive")]
    InvalidBound,
    #[error("input exceeds the configured {0} bound")]
    BoundExceeded(&'static str),
    #[error("input or request contract is invalid: {0}")]
    Invalid(String),
    #[error("duplicate identity: {0}")]
    Duplicate(String),
    #[error("missing referenced object: {0}")]
    MissingReference(String),
    #[error("supersession chain is invalid: {0}")]
    InvalidSupersession(String),
    #[error("checked topology arithmetic overflowed")]
    Arithmetic,
}

/// Pure bounded reducer for exact facts, current hypotheses, and Arrow-facing rows.
pub struct TopologyReducer {
    config: ReducerConfig,
}

impl TopologyReducer {
    /// Creates a reducer with explicit resource bounds.
    #[must_use]
    pub const fn new(config: ReducerConfig) -> Self {
        Self { config }
    }

    /// Validates the complete input and creates one three-axis point-in-time snapshot.
    ///
    /// # Errors
    ///
    /// Refuses malformed evidence, dangling transaction versions, invalid supersession,
    /// noncanonical collections, arithmetic overflow, or a configured bound violation.
    pub fn snapshot(
        &self,
        input: &TopologyInput,
        request: SnapshotRequest,
    ) -> Result<TopologySnapshot, TopologyError> {
        self.validate(input, &request)?;
        let selection = select_facts(input, &request);
        let rows = build_rows(&selection.facts, &request, self.config)?;
        let current_hypotheses =
            select_hypotheses(&input.hypotheses, &selection.fact_refs, &request);
        Ok(TopologySnapshot {
            contract: stable(TOPOLOGY_CONTRACT_VERSION)?,
            arrow_table_contract: stable(ARROW_TABLE_CONTRACT_VERSION)?,
            coverage_binding: CoverageBinding::UnverifiedRequest {
                coverage_ids: request.requested_coverage_ids.clone(),
            },
            request,
            observed_transaction_versions: selection.observed_transactions,
            accepted_facts: selection.facts,
            current_hypotheses,
            excluded_noncanonical_transaction_ids: selection.excluded_noncanonical,
            excluded_unaccepted_finality_transaction_ids: selection.excluded_finality,
            flow_edges: rows.flow_edges,
            incidence: rows.incidence,
            divergence: rows.divergence,
            bundle_legs: rows.bundle_legs,
            route_legs: rows.route_legs,
            cycle_inputs: rows.cycle_inputs,
            wallet_mint_cohorts: rows.wallet_mint_cohorts,
            concentration_inputs: rows.concentration_inputs,
            cohort_aggregates: rows.cohort_aggregates,
            co_trades: rows.co_trades,
        })
    }

    fn validate(
        &self,
        input: &TopologyInput,
        request: &SnapshotRequest,
    ) -> Result<(), TopologyError> {
        if input.contract.as_str() != TOPOLOGY_CONTRACT_VERSION {
            return Err(TopologyError::Invalid("unknown topology contract".into()));
        }
        if input.facts.len() > self.config.max_facts {
            return Err(TopologyError::BoundExceeded("fact"));
        }
        if input.hypotheses.len() > self.config.max_hypotheses {
            return Err(TopologyError::BoundExceeded("hypothesis"));
        }
        validate_request(request, self.config)?;
        let catalog = validate_facts(&input.facts)?;
        validate_hypotheses(&input.hypotheses, &catalog)
    }
}

#[derive(Default)]
struct FactCatalog {
    transaction_versions: BTreeMap<TransactionFactId, TransactionFact>,
    transaction_series: BTreeMap<TransactionId, Vec<TransactionFactId>>,
    facts: BTreeMap<TopologyFactRef, (TransactionFactId, UtcTimestamp)>,
}

struct FactSelection {
    observed_transactions: Vec<TransactionFact>,
    facts: Vec<TopologyFact>,
    fact_refs: BTreeSet<TopologyFactRef>,
    excluded_noncanonical: Vec<TransactionId>,
    excluded_finality: Vec<TransactionId>,
}

#[derive(Default)]
struct DerivedRows {
    flow_edges: Vec<FlowEdgeRow>,
    incidence: Vec<IncidenceRow>,
    divergence: Vec<DivergenceRow>,
    bundle_legs: Vec<BundleLegRow>,
    route_legs: Vec<RouteLegRow>,
    cycle_inputs: Vec<CycleInputRow>,
    wallet_mint_cohorts: Vec<WalletMintCohortRow>,
    concentration_inputs: Vec<ConcentrationInputRow>,
    cohort_aggregates: Vec<CohortAggregateRow>,
    co_trades: Vec<WalletPairCoTradeRow>,
}

fn validate_request(request: &SnapshotRequest, config: ReducerConfig) -> Result<(), TopologyError> {
    require_sorted_unique(&request.accepted_finalities, "accepted finalities")?;
    require_sorted_unique(&request.accepted_canonicalities, "accepted canonicalities")?;
    require_sorted_unique(&request.focus_mint_ids, "focus mints")?;
    require_sorted_unique(&request.requested_coverage_ids, "snapshot coverage")?;
    if request.accepted_finalities.is_empty() || request.accepted_canonicalities.is_empty() {
        return Err(TopologyError::Invalid(
            "accepted finality and canonicality sets must be nonempty".into(),
        ));
    }
    if request.co_trade_window_slots.get() == 0 || request.max_pair_rows.get() == 0 {
        return Err(TopologyError::Invalid(
            "co-trade window and row bound must be positive".into(),
        ));
    }
    let row_bound = usize::try_from(request.max_pair_rows.get())
        .map_err(|_| TopologyError::BoundExceeded("pair row"))?;
    if row_bound > config.max_pair_rows {
        return Err(TopologyError::BoundExceeded("pair row"));
    }
    Ok(())
}

fn validate_facts(facts: &[TopologyFact]) -> Result<FactCatalog, TopologyError> {
    let mut catalog = FactCatalog::default();
    for fact in facts {
        validate_evidence(fact.evidence())?;
        match fact {
            TopologyFact::Transaction(value) => insert_transaction(&mut catalog, value)?,
            _ => insert_dependent_fact(&mut catalog, fact)?,
        }
    }
    validate_transaction_series(&catalog)?;
    validate_dependent_facts(facts, &catalog)?;
    validate_bundles(facts, &catalog)?;
    Ok(catalog)
}

fn insert_transaction(
    catalog: &mut FactCatalog,
    value: &TransactionFact,
) -> Result<(), TopologyError> {
    if value.version.get() == 0 {
        return Err(TopologyError::Invalid(
            "transaction fact version must be positive".into(),
        ));
    }
    if catalog
        .transaction_versions
        .insert(value.transaction_fact_id.clone(), value.clone())
        .is_some()
    {
        return Err(TopologyError::Duplicate(
            value.transaction_fact_id.to_string(),
        ));
    }
    catalog
        .transaction_series
        .entry(value.transaction_id.clone())
        .or_default()
        .push(value.transaction_fact_id.clone());
    Ok(())
}

fn insert_dependent_fact(
    catalog: &mut FactCatalog,
    fact: &TopologyFact,
) -> Result<(), TopologyError> {
    validate_fact_payload(fact)?;
    if let Some(reference) = fact_ref(fact)
        && catalog
            .facts
            .insert(
                reference.clone(),
                (fact.transaction_fact_id().clone(), fact.available_at()),
            )
            .is_some()
    {
        return Err(TopologyError::Duplicate(format!("{reference:?}")));
    }
    Ok(())
}

fn validate_transaction_series(catalog: &FactCatalog) -> Result<(), TopologyError> {
    for (transaction_id, fact_ids) in &catalog.transaction_series {
        let mut versions = fact_ids
            .iter()
            .map(|id| &catalog.transaction_versions[id])
            .collect::<Vec<_>>();
        versions.sort_by_key(|value| value.version);
        for (index, value) in versions.iter().enumerate() {
            if index == 0 {
                if value.supersedes_transaction_fact_id.is_some() {
                    return Err(TopologyError::InvalidSupersession(
                        transaction_id.to_string(),
                    ));
                }
                continue;
            }
            let prior = versions[index - 1];
            if value.version <= prior.version
                || value.supersedes_transaction_fact_id.as_ref() != Some(&prior.transaction_fact_id)
                || value.available_at < prior.available_at
                || value.chain_id != prior.chain_id
                || value.signature != prior.signature
            {
                return Err(TopologyError::InvalidSupersession(
                    transaction_id.to_string(),
                ));
            }
        }
    }
    Ok(())
}

fn validate_dependent_facts(
    facts: &[TopologyFact],
    catalog: &FactCatalog,
) -> Result<(), TopologyError> {
    for fact in facts {
        if matches!(fact, TopologyFact::Transaction(_)) {
            continue;
        }
        let transaction = catalog
            .transaction_versions
            .get(fact.transaction_fact_id())
            .ok_or_else(|| {
                TopologyError::MissingReference(fact.transaction_fact_id().to_string())
            })?;
        if fact.transaction_id() != &transaction.transaction_id
            || fact.available_at() < transaction.available_at
        {
            return Err(TopologyError::Invalid(format!(
                "fact is not causally bound to transaction version {}",
                transaction.transaction_fact_id
            )));
        }
    }
    Ok(())
}

fn validate_bundles(facts: &[TopologyFact], catalog: &FactCatalog) -> Result<(), TopologyError> {
    for fact in facts {
        let TopologyFact::SameTransactionBundle(bundle) = fact else {
            continue;
        };
        if bundle.ordered_members.len() < 2 {
            return Err(TopologyError::Invalid(
                "same-transaction bundle must contain at least two facts".into(),
            ));
        }
        let unique = bundle.ordered_members.iter().collect::<BTreeSet<_>>();
        if unique.len() != bundle.ordered_members.len() {
            return Err(TopologyError::Duplicate(bundle.bundle_id.to_string()));
        }
        for member in &bundle.ordered_members {
            let (transaction_fact_id, available_at) = catalog
                .facts
                .get(member)
                .ok_or_else(|| TopologyError::MissingReference(format!("{member:?}")))?;
            if transaction_fact_id != &bundle.transaction_fact_id
                || *available_at > bundle.available_at
            {
                return Err(TopologyError::Invalid(format!(
                    "bundle {} crosses transaction versions or availability",
                    bundle.bundle_id
                )));
            }
        }
    }
    Ok(())
}

fn validate_fact_payload(fact: &TopologyFact) -> Result<(), TopologyError> {
    match fact {
        TopologyFact::Transfer(value) if value.mark.atoms.get() == 0 => {
            Err(TopologyError::Invalid("zero transfer amount".into()))
        }
        TopologyFact::Swap(value)
            if value.input.atoms.get() == 0
                || value.output.atoms.get() == 0
                || value.input.asset_id == value.output.asset_id =>
        {
            Err(TopologyError::Invalid("invalid swap amounts/assets".into()))
        }
        TopologyFact::LiquidityPositionEvent(value)
            if value.asset_legs.is_empty()
                || value
                    .asset_legs
                    .iter()
                    .any(|leg| leg.amount.atoms.get() == 0) =>
        {
            Err(TopologyError::Invalid(
                "invalid liquidity event legs".into(),
            ))
        }
        _ => Ok(()),
    }
}

fn validate_evidence(value: &crate::EvidenceClosure) -> Result<(), TopologyError> {
    require_sorted_unique(&value.observation_ids, "fact observations")?;
    require_sorted_unique(&value.source_event_ids, "fact source events")?;
    require_sorted_unique(&value.coverage_ids, "fact coverage")?;
    if value.observation_ids.is_empty() && value.source_event_ids.is_empty() {
        return Err(TopologyError::Invalid(
            "fact evidence must name an observation or source event".into(),
        ));
    }
    Ok(())
}

fn fact_ref(fact: &TopologyFact) -> Option<TopologyFactRef> {
    match fact {
        TopologyFact::Transaction(_) | TopologyFact::SameTransactionBundle(_) => None,
        TopologyFact::CallerAccount(value) => {
            Some(TopologyFactRef::CallerAccount(value.association_id.clone()))
        }
        TopologyFact::Transfer(value) => Some(TopologyFactRef::Transfer(value.flow_id.clone())),
        TopologyFact::Swap(value) => Some(TopologyFactRef::Swap(value.swap_id.clone())),
        TopologyFact::LiquidityPositionEvent(value) => Some(
            TopologyFactRef::LiquidityPositionEvent(value.liquidity_event_id.clone()),
        ),
    }
}

fn validate_hypotheses(
    hypotheses: &[TopologyHypothesis],
    facts: &FactCatalog,
) -> Result<(), TopologyError> {
    let mut by_id = BTreeMap::new();
    let mut by_series: BTreeMap<_, Vec<&TopologyHypothesis>> = BTreeMap::new();
    for hypothesis in hypotheses {
        validate_hypothesis(hypothesis, facts)?;
        if by_id
            .insert(hypothesis.hypothesis_id.clone(), hypothesis)
            .is_some()
        {
            return Err(TopologyError::Duplicate(
                hypothesis.hypothesis_id.to_string(),
            ));
        }
        by_series
            .entry(hypothesis.hypothesis_series_id.clone())
            .or_default()
            .push(hypothesis);
    }
    for values in by_series.values_mut() {
        values.sort_by_key(|value| value.version);
        for (index, value) in values.iter().enumerate() {
            if index == 0 {
                if value.supersedes_hypothesis_id.is_some() {
                    return Err(TopologyError::InvalidSupersession(
                        value.hypothesis_id.to_string(),
                    ));
                }
                continue;
            }
            let prior = values[index - 1];
            if value.version <= prior.version
                || value.supersedes_hypothesis_id.as_ref() != Some(&prior.hypothesis_id)
                || value.available_at < prior.available_at
            {
                return Err(TopologyError::InvalidSupersession(
                    value.hypothesis_id.to_string(),
                ));
            }
        }
    }
    Ok(())
}

fn validate_hypothesis(
    value: &TopologyHypothesis,
    facts: &FactCatalog,
) -> Result<(), TopologyError> {
    if value.version.get() == 0 || value.adversarial_alternatives.is_empty() {
        return Err(TopologyError::Invalid(
            "hypothesis needs positive version and adversarial alternative".into(),
        ));
    }
    validate_validity(value)?;
    validate_hypothesis_evidence(value, facts)?;
    validate_claim(&value.claim)
}

fn validate_validity(value: &TopologyHypothesis) -> Result<(), TopologyError> {
    if let Some(slots) = &value.validity.slots
        && slots
            .upper_exclusive
            .is_some_and(|upper| upper <= slots.lower_inclusive)
    {
        return Err(TopologyError::Invalid(
            "empty hypothesis slot interval".into(),
        ));
    }
    let wall = &value.validity.wall_time;
    if wall
        .lower
        .zip(wall.upper)
        .is_some_and(|(lower, upper)| upper <= lower)
    {
        return Err(TopologyError::Invalid(
            "empty hypothesis wall interval".into(),
        ));
    }
    Ok(())
}

fn validate_hypothesis_evidence(
    value: &TopologyHypothesis,
    facts: &FactCatalog,
) -> Result<(), TopologyError> {
    let evidence = &value.evidence;
    require_sorted_unique(&evidence.observation_ids, "hypothesis observations")?;
    require_sorted_unique(&evidence.source_event_ids, "hypothesis source events")?;
    require_sorted_unique(&evidence.coverage_ids, "hypothesis coverage")?;
    require_sorted_unique(&evidence.fact_refs, "hypothesis facts")?;
    require_sorted_unique(&evidence.derivation_ids, "hypothesis derivations")?;
    validate_sha256(evidence.input_digest.as_str())?;
    if evidence.fact_refs.is_empty()
        && evidence.observation_ids.is_empty()
        && evidence.source_event_ids.is_empty()
        && evidence.derivation_ids.is_empty()
    {
        return Err(TopologyError::Invalid("empty hypothesis evidence".into()));
    }
    for fact_ref in &evidence.fact_refs {
        let (_, available_at) = facts
            .facts
            .get(fact_ref)
            .ok_or_else(|| TopologyError::MissingReference(format!("{fact_ref:?}")))?;
        if *available_at > value.available_at {
            return Err(TopologyError::Invalid(
                "hypothesis predates supporting fact".into(),
            ));
        }
    }
    Ok(())
}

fn validate_claim(claim: &HypothesisClaim) -> Result<(), TopologyError> {
    match claim {
        HypothesisClaim::FundingEdge {
            from_wallet_id,
            to_wallet_id,
            supporting_flow_ids,
        } => {
            require_sorted_unique(supporting_flow_ids, "funding flows")?;
            if from_wallet_id == to_wallet_id || supporting_flow_ids.is_empty() {
                return Err(TopologyError::Invalid("invalid funding claim".into()));
            }
        }
        HypothesisClaim::WalletCluster { members } => {
            if members.len() < 2
                || members
                    .windows(2)
                    .any(|pair| pair[0].wallet_id >= pair[1].wallet_id)
            {
                return Err(TopologyError::Invalid(
                    "cluster members must be sorted, unique, and nontrivial".into(),
                ));
            }
        }
        HypothesisClaim::Coordination {
            wallet_ids,
            bundle_ids,
            co_trade_derivation_ids,
        } => {
            require_sorted_unique(wallet_ids, "coordination wallets")?;
            require_sorted_unique(bundle_ids, "coordination bundles")?;
            require_sorted_unique(co_trade_derivation_ids, "coordination co-trades")?;
            if wallet_ids.len() < 2 || bundle_ids.is_empty() && co_trade_derivation_ids.is_empty() {
                return Err(TopologyError::Invalid("invalid coordination claim".into()));
            }
        }
    }
    Ok(())
}

fn select_facts(input: &TopologyInput, request: &SnapshotRequest) -> FactSelection {
    let transactions = current_transactions(&input.facts, request.available_through);
    let accepted_canonicality = discriminators(&request.accepted_canonicalities);
    let accepted_finality = discriminators(&request.accepted_finalities);
    let mut accepted_fact_ids = BTreeSet::new();
    let mut excluded_noncanonical = Vec::new();
    let mut excluded_finality = Vec::new();
    let mut observed_transactions = Vec::new();
    let mut selected = Vec::new();
    for transaction in transactions.values() {
        if transaction.slot > request.event_slot {
            continue;
        }
        observed_transactions.push((*transaction).clone());
        if !accepted_canonicality.contains(transaction.canonicality.discriminator.as_str()) {
            excluded_noncanonical.push(transaction.transaction_id.clone());
        } else if !accepted_finality.contains(transaction.finality.discriminator.as_str()) {
            excluded_finality.push(transaction.transaction_id.clone());
        } else {
            accepted_fact_ids.insert(transaction.transaction_fact_id.clone());
            selected.push(TopologyFact::Transaction((*transaction).clone()));
        }
    }
    for fact in &input.facts {
        if matches!(fact, TopologyFact::Transaction(_))
            || fact.available_at() > request.available_through
            || !accepted_fact_ids.contains(fact.transaction_fact_id())
        {
            continue;
        }
        selected.push(fact.clone());
    }
    selected.sort_by_key(fact_sort_key);
    observed_transactions.sort_by(|left, right| {
        left.transaction_id
            .cmp(&right.transaction_id)
            .then(left.version.cmp(&right.version))
    });
    let fact_refs = selected.iter().filter_map(fact_ref).collect();
    excluded_noncanonical.sort();
    excluded_finality.sort();
    FactSelection {
        observed_transactions,
        facts: selected,
        fact_refs,
        excluded_noncanonical,
        excluded_finality,
    }
}

fn current_transactions(
    facts: &[TopologyFact],
    cutoff: UtcTimestamp,
) -> BTreeMap<TransactionId, &TransactionFact> {
    let mut current: BTreeMap<TransactionId, &TransactionFact> = BTreeMap::new();
    for fact in facts {
        let TopologyFact::Transaction(transaction) = fact else {
            continue;
        };
        if transaction.available_at > cutoff {
            continue;
        }
        current
            .entry(transaction.transaction_id.clone())
            .and_modify(|known| {
                if transaction.version > known.version {
                    *known = transaction;
                }
            })
            .or_insert(transaction);
    }
    current
}

fn select_hypotheses(
    hypotheses: &[TopologyHypothesis],
    selected_facts: &BTreeSet<TopologyFactRef>,
    request: &SnapshotRequest,
) -> Vec<TopologyHypothesis> {
    let mut current = BTreeMap::new();
    for hypothesis in hypotheses {
        if hypothesis.available_at > request.available_through
            || !valid_at(hypothesis, request.event_slot, request.event_time)
            || !hypothesis
                .evidence
                .fact_refs
                .iter()
                .all(|value| selected_facts.contains(value))
        {
            continue;
        }
        current
            .entry(hypothesis.hypothesis_series_id.clone())
            .and_modify(|known: &mut &TopologyHypothesis| {
                if hypothesis.version > known.version {
                    *known = hypothesis;
                }
            })
            .or_insert(hypothesis);
    }
    let mut result = current.into_values().cloned().collect::<Vec<_>>();
    result.sort_by(|left, right| {
        left.hypothesis_series_id
            .cmp(&right.hypothesis_series_id)
            .then(left.version.cmp(&right.version))
    });
    result
}

fn valid_at(value: &TopologyHypothesis, slot: WireU64, wall_time: UtcTimestamp) -> bool {
    let slot_valid = value
        .validity
        .slots
        .as_ref()
        .is_none_or(|interval| interval.contains(slot));
    let wall = &value.validity.wall_time;
    let wall_valid = match wall.status.discriminator.as_str() {
        "bounded" => {
            wall.lower.is_some_and(|lower| wall_time >= lower)
                && wall.upper.is_some_and(|upper| wall_time < upper)
        }
        "unbounded" => wall.lower.is_none() && wall.upper.is_none(),
        _ => false,
    };
    slot_valid && wall_valid
}

fn build_rows(
    facts: &[TopologyFact],
    request: &SnapshotRequest,
    config: ReducerConfig,
) -> Result<DerivedRows, TopologyError> {
    let transactions = facts
        .iter()
        .filter_map(|fact| match fact {
            TopologyFact::Transaction(value) => Some((value.transaction_fact_id.clone(), value)),
            _ => None,
        })
        .collect::<BTreeMap<_, _>>();
    let mut rows = DerivedRows::default();
    rows.flow_edges = build_flow_edges(facts, &transactions)?;
    rows.incidence = build_incidence(&rows.flow_edges);
    rows.divergence = build_divergence(&rows.flow_edges, request)?;
    build_bundle_rows(facts, &mut rows, request)?;
    build_cohort_rows(facts, &mut rows, &transactions, request)?;
    rows.co_trades = build_co_trades(facts, &transactions, request, config)?;
    Ok(rows)
}

fn build_flow_edges(
    facts: &[TopologyFact],
    transactions: &BTreeMap<TransactionFactId, &TransactionFact>,
) -> Result<Vec<FlowEdgeRow>, TopologyError> {
    let mut rows = Vec::new();
    for fact in facts {
        match fact {
            TopologyFact::Transfer(value) => rows.push(FlowEdgeRow {
                edge_id: stable(value.flow_id.as_str())?,
                transaction_id: value.transaction_id.clone(),
                slot: transactions[&value.transaction_fact_id].slot,
                source: TopologyNodeRef::Account(value.from_account_id.clone()),
                target: TopologyNodeRef::Account(value.to_account_id.clone()),
                asset_id: value.mark.asset_id.clone(),
                atoms: value.mark.atoms,
                edge_kind: value.mark.flow_kind.discriminator.clone(),
                venue_id: value.mark.venue_id.clone(),
                pool_id: value.mark.pool_id.clone(),
                evidence_class: EvidenceClass::Observed,
                input_fact: TopologyFactRef::Transfer(value.flow_id.clone()),
            }),
            TopologyFact::Swap(value) => {
                append_swap_edges(&mut rows, value, transactions)?;
            }
            TopologyFact::LiquidityPositionEvent(value) => {
                append_liquidity_edges(&mut rows, value, transactions)?;
            }
            _ => {}
        }
    }
    rows.sort_by(|left, right| left.edge_id.cmp(&right.edge_id));
    Ok(rows)
}

fn append_swap_edges(
    rows: &mut Vec<FlowEdgeRow>,
    value: &SwapFact,
    transactions: &BTreeMap<TransactionFactId, &TransactionFact>,
) -> Result<(), TopologyError> {
    let actor = value.trader_wallet_id.as_ref().map_or_else(
        || TopologyNodeRef::Account(value.caller_account_id.clone()),
        |wallet| TopologyNodeRef::Wallet(wallet.clone()),
    );
    let market = value.pool_id.as_ref().map_or_else(
        || TopologyNodeRef::Venue(value.venue_id.clone()),
        |pool| TopologyNodeRef::Pool(pool.clone()),
    );
    let slot = transactions[&value.transaction_fact_id].slot;
    rows.push(flow_edge(
        format!("swap:{}:input", value.swap_id),
        value,
        slot,
        actor.clone(),
        market.clone(),
        &value.input,
        "swap_input",
    )?);
    rows.push(flow_edge(
        format!("swap:{}:output", value.swap_id),
        value,
        slot,
        market,
        actor.clone(),
        &value.output,
        "swap_output",
    )?);
    for (index, fee) in value.fee_legs.iter().enumerate() {
        rows.push(flow_edge(
            format!("swap:{}:fee:{index}", value.swap_id),
            value,
            slot,
            actor.clone(),
            TopologyNodeRef::Program(value.program_id.clone()),
            fee,
            "swap_fee",
        )?);
    }
    Ok(())
}

fn flow_edge(
    edge_id: String,
    swap: &SwapFact,
    slot: WireU64,
    source: TopologyNodeRef,
    target: TopologyNodeRef,
    amount: &crate::AssetAmount,
    edge_kind: &str,
) -> Result<FlowEdgeRow, TopologyError> {
    Ok(FlowEdgeRow {
        edge_id: stable(edge_id)?,
        transaction_id: swap.transaction_id.clone(),
        slot,
        source,
        target,
        asset_id: amount.asset_id.clone(),
        atoms: amount.atoms,
        edge_kind: stable(edge_kind)?,
        venue_id: Some(swap.venue_id.clone()),
        pool_id: swap.pool_id.clone(),
        evidence_class: EvidenceClass::Observed,
        input_fact: TopologyFactRef::Swap(swap.swap_id.clone()),
    })
}

fn append_liquidity_edges(
    rows: &mut Vec<FlowEdgeRow>,
    value: &crate::LiquidityPositionEventFact,
    transactions: &BTreeMap<TransactionFactId, &TransactionFact>,
) -> Result<(), TopologyError> {
    let actor = value.actor_wallet_id.as_ref().map_or_else(
        || TopologyNodeRef::Account(value.authority_account_id.clone()),
        |wallet| TopologyNodeRef::Wallet(wallet.clone()),
    );
    let position = TopologyNodeRef::Position(value.position_id.clone());
    let pool = TopologyNodeRef::Pool(value.pool_id.clone());
    let slot = transactions[&value.transaction_fact_id].slot;
    for (index, leg) in value.asset_legs.iter().enumerate() {
        let (source, target) = match leg.direction {
            AssetLegDirection::IntoWallet
            | AssetLegDirection::OutOfPool
            | AssetLegDirection::Fee
            | AssetLegDirection::Reward => (pool.clone(), actor.clone()),
            AssetLegDirection::OutOfWallet | AssetLegDirection::IntoPool => {
                (actor.clone(), pool.clone())
            }
            AssetLegDirection::IntoPosition => (actor.clone(), position.clone()),
            AssetLegDirection::OutOfPosition => (position.clone(), actor.clone()),
        };
        rows.push(FlowEdgeRow {
            edge_id: stable(format!("lp:{}:{index}", value.liquidity_event_id))?,
            transaction_id: value.transaction_id.clone(),
            slot,
            source,
            target,
            asset_id: leg.amount.asset_id.clone(),
            atoms: leg.amount.atoms,
            edge_kind: stable(format!(
                "lp:{}:{:?}",
                value.event_kind.discriminator.as_str(),
                leg.direction
            ))?,
            venue_id: Some(value.venue_id.clone()),
            pool_id: Some(value.pool_id.clone()),
            evidence_class: EvidenceClass::Observed,
            input_fact: TopologyFactRef::LiquidityPositionEvent(value.liquidity_event_id.clone()),
        });
    }
    Ok(())
}

fn build_incidence(edges: &[FlowEdgeRow]) -> Vec<IncidenceRow> {
    let mut rows = Vec::with_capacity(edges.len().saturating_mul(2));
    for edge in edges {
        rows.push(IncidenceRow {
            edge_id: edge.edge_id.clone(),
            node: edge.source.clone(),
            sign: IncidenceSign::TailMinusOne,
            asset_id: edge.asset_id.clone(),
            atoms: edge.atoms,
            slot: edge.slot,
        });
        rows.push(IncidenceRow {
            edge_id: edge.edge_id.clone(),
            node: edge.target.clone(),
            sign: IncidenceSign::HeadPlusOne,
            asset_id: edge.asset_id.clone(),
            atoms: edge.atoms,
            slot: edge.slot,
        });
    }
    rows
}

fn build_divergence(
    edges: &[FlowEdgeRow],
    request: &SnapshotRequest,
) -> Result<Vec<DivergenceRow>, TopologyError> {
    type Accumulator = (u128, u128, BTreeSet<StableString>);
    let mut grouped: BTreeMap<(TopologyNodeRef, AssetId), Accumulator> = BTreeMap::new();
    for edge in edges {
        let source = grouped
            .entry((edge.source.clone(), edge.asset_id.clone()))
            .or_default();
        source.1 = source
            .1
            .checked_add(u128::from(edge.atoms.get()))
            .ok_or(TopologyError::Arithmetic)?;
        source.2.insert(edge.edge_id.clone());
        let target = grouped
            .entry((edge.target.clone(), edge.asset_id.clone()))
            .or_default();
        target.0 = target
            .0
            .checked_add(u128::from(edge.atoms.get()))
            .ok_or(TopologyError::Arithmetic)?;
        target.2.insert(edge.edge_id.clone());
    }
    grouped
        .into_iter()
        .enumerate()
        .map(|(index, ((node, asset_id), (inflow, outflow, edge_ids)))| {
            let inflow_signed = i128::try_from(inflow).map_err(|_| TopologyError::Arithmetic)?;
            let outflow_signed = i128::try_from(outflow).map_err(|_| TopologyError::Arithmetic)?;
            Ok(DivergenceRow {
                derivation_id: derivation(&request.snapshot_id, "divergence", index)?,
                node,
                asset_id,
                through_slot: request.event_slot,
                inflow_atoms: WireU128::new(inflow),
                outflow_atoms: WireU128::new(outflow),
                net_accumulation_atoms: SignedAtoms::new(
                    inflow_signed
                        .checked_sub(outflow_signed)
                        .ok_or(TopologyError::Arithmetic)?,
                ),
                evidence_class: EvidenceClass::DeterministicDerived,
                input_edge_ids: edge_ids.into_iter().collect(),
            })
        })
        .collect()
}

fn build_bundle_rows(
    facts: &[TopologyFact],
    rows: &mut DerivedRows,
    request: &SnapshotRequest,
) -> Result<(), TopologyError> {
    let swaps = facts
        .iter()
        .filter_map(|fact| match fact {
            TopologyFact::Swap(value) => Some((value.swap_id.clone(), value)),
            _ => None,
        })
        .collect::<BTreeMap<_, _>>();
    for fact in facts {
        let TopologyFact::SameTransactionBundle(bundle) = fact else {
            continue;
        };
        let mut route = Vec::new();
        for (index, member) in bundle.ordered_members.iter().enumerate() {
            rows.bundle_legs.push(BundleLegRow {
                bundle_id: bundle.bundle_id.clone(),
                transaction_id: bundle.transaction_id.clone(),
                ordinal: WireU64::new(index as u64),
                fact_ref: member.clone(),
                evidence_class: EvidenceClass::Observed,
            });
            if let TopologyFactRef::Swap(swap_id) = member {
                let swap = swaps
                    .get(swap_id)
                    .ok_or_else(|| TopologyError::MissingReference(swap_id.to_string()))?;
                route.push(RouteLegRow {
                    bundle_id: bundle.bundle_id.clone(),
                    ordinal: WireU64::new(index as u64),
                    swap_id: swap.swap_id.clone(),
                    wallet_id: swap.trader_wallet_id.clone(),
                    venue_id: swap.venue_id.clone(),
                    pool_id: swap.pool_id.clone(),
                    input_asset_id: swap.input.asset_id.clone(),
                    input_atoms: swap.input.atoms,
                    output_asset_id: swap.output.asset_id.clone(),
                    output_atoms: swap.output.atoms,
                });
            }
        }
        if !route.is_empty() {
            rows.cycle_inputs.push(cycle_input(
                &bundle.bundle_id,
                &route,
                request,
                rows.cycle_inputs.len(),
            )?);
            rows.route_legs.extend(route);
        }
    }
    Ok(())
}

fn cycle_input(
    bundle_id: &BundleId,
    route: &[RouteLegRow],
    request: &SnapshotRequest,
    index: usize,
) -> Result<CycleInputRow, TopologyError> {
    let first = &route[0];
    let last = &route[route.len() - 1];
    let path_is_contiguous = route
        .windows(2)
        .all(|pair| pair[0].output_asset_id == pair[1].input_asset_id);
    let wallet_id = route
        .first()
        .and_then(|value| value.wallet_id.clone())
        .filter(|wallet| {
            route
                .iter()
                .all(|value| value.wallet_id.as_ref() == Some(wallet))
        });
    Ok(CycleInputRow {
        derivation_id: derivation(&request.snapshot_id, "cycle", index)?,
        bundle_id: bundle_id.clone(),
        wallet_id,
        first_input_asset_id: first.input_asset_id.clone(),
        last_output_asset_id: last.output_asset_id.clone(),
        ordered_leg_count: WireU64::new(route.len() as u64),
        path_is_contiguous,
        is_asset_closed: path_is_contiguous && first.input_asset_id == last.output_asset_id,
        evidence_class: EvidenceClass::DeterministicDerived,
    })
}

#[derive(Default)]
struct CohortAccumulator {
    first_acquisition: Option<WireU64>,
    last_disposal: Option<WireU64>,
    acquired: u128,
    disposed: u128,
    swaps: BTreeSet<SwapId>,
    venues: BTreeSet<VenueId>,
}

fn build_cohort_rows(
    facts: &[TopologyFact],
    rows: &mut DerivedRows,
    transactions: &BTreeMap<TransactionFactId, &TransactionFact>,
    request: &SnapshotRequest,
) -> Result<(), TopologyError> {
    let focus = request
        .focus_mint_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut grouped: BTreeMap<(AccountId, AssetId), CohortAccumulator> = BTreeMap::new();
    for fact in facts {
        let TopologyFact::Swap(swap) = fact else {
            continue;
        };
        let Some(wallet) = &swap.trader_wallet_id else {
            continue;
        };
        let slot = transactions[&swap.transaction_fact_id].slot;
        if focus.contains(&swap.output.asset_id) {
            let value = grouped
                .entry((wallet.clone(), swap.output.asset_id.clone()))
                .or_default();
            value.first_acquisition = Some(
                value
                    .first_acquisition
                    .map_or(slot, |known| known.min(slot)),
            );
            value.acquired = value
                .acquired
                .checked_add(u128::from(swap.output.atoms.get()))
                .ok_or(TopologyError::Arithmetic)?;
            value.swaps.insert(swap.swap_id.clone());
            value.venues.insert(swap.venue_id.clone());
        }
        if focus.contains(&swap.input.asset_id) {
            let value = grouped
                .entry((wallet.clone(), swap.input.asset_id.clone()))
                .or_default();
            value.last_disposal = Some(value.last_disposal.map_or(slot, |known| known.max(slot)));
            value.disposed = value
                .disposed
                .checked_add(u128::from(swap.input.atoms.get()))
                .ok_or(TopologyError::Arithmetic)?;
            value.swaps.insert(swap.swap_id.clone());
            value.venues.insert(swap.venue_id.clone());
        }
    }
    append_cohort_tables(rows, &grouped, request)
}

fn append_cohort_tables(
    rows: &mut DerivedRows,
    grouped: &BTreeMap<(AccountId, AssetId), CohortAccumulator>,
    request: &SnapshotRequest,
) -> Result<(), TopologyError> {
    let mut totals = BTreeMap::<AssetId, u128>::new();
    for ((_, mint), value) in grouped {
        let activity = value
            .acquired
            .checked_add(value.disposed)
            .ok_or(TopologyError::Arithmetic)?;
        let total = totals.entry(mint.clone()).or_default();
        *total = total
            .checked_add(activity)
            .ok_or(TopologyError::Arithmetic)?;
    }
    for (index, ((wallet, mint), value)) in grouped.iter().enumerate() {
        let cohort_id = derivation(&request.snapshot_id, "wallet_mint", index)?;
        rows.wallet_mint_cohorts.push(WalletMintCohortRow {
            derivation_id: cohort_id,
            wallet_id: wallet.clone(),
            mint_id: mint.clone(),
            first_observed_acquisition_slot: value.first_acquisition,
            last_observed_disposal_slot: value.last_disposal,
            acquired_atoms: WireU128::new(value.acquired),
            disposed_atoms: WireU128::new(value.disposed),
            swap_count: WireU64::new(value.swaps.len() as u64),
            venue_ids: value.venues.iter().cloned().collect(),
            input_swap_ids: value.swaps.iter().cloned().collect(),
            coverage_ids: request.requested_coverage_ids.clone(),
            evidence_class: EvidenceClass::DeterministicDerived,
        });
        let activity = value
            .acquired
            .checked_add(value.disposed)
            .ok_or(TopologyError::Arithmetic)?;
        rows.concentration_inputs.push(ConcentrationInputRow {
            derivation_id: derivation(&request.snapshot_id, "concentration", index)?,
            wallet_id: wallet.clone(),
            mint_id: mint.clone(),
            acquired_atoms: WireU128::new(value.acquired),
            disposed_atoms: WireU128::new(value.disposed),
            total_mint_activity_atoms: WireU128::new(activity),
            window_total_activity_atoms: WireU128::new(totals[mint]),
            evidence_class: EvidenceClass::DeterministicDerived,
        });
    }
    rows.cohort_aggregates = cohort_aggregates(grouped, request)?;
    Ok(())
}

fn cohort_aggregates(
    grouped: &BTreeMap<(AccountId, AssetId), CohortAccumulator>,
    request: &SnapshotRequest,
) -> Result<Vec<CohortAggregateRow>, TopologyError> {
    let mut counts = BTreeMap::<AssetId, (u64, u64, u64)>::new();
    for ((_, mint), value) in grouped {
        let entry = counts.entry(mint.clone()).or_default();
        if value.first_acquisition.is_some() {
            entry.0 = entry.0.checked_add(1).ok_or(TopologyError::Arithmetic)?;
        }
        if value.last_disposal.is_some() {
            entry.1 = entry.1.checked_add(1).ok_or(TopologyError::Arithmetic)?;
        }
        if value.first_acquisition.is_some() && value.last_disposal.is_some() {
            entry.2 = entry.2.checked_add(1).ok_or(TopologyError::Arithmetic)?;
        }
    }
    counts
        .into_iter()
        .enumerate()
        .map(|(index, (mint_id, (acquired, disposed, both)))| {
            Ok(CohortAggregateRow {
                derivation_id: derivation(&request.snapshot_id, "cohort", index)?,
                mint_id,
                wallets_with_observed_acquisition: WireU64::new(acquired),
                wallets_with_observed_disposal: WireU64::new(disposed),
                wallets_with_both: WireU64::new(both),
                coverage_ids: request.requested_coverage_ids.clone(),
                evidence_class: EvidenceClass::DeterministicDerived,
            })
        })
        .collect()
}

#[derive(Clone)]
struct Activity {
    mint: AssetId,
    wallet: AccountId,
    slot: WireU64,
    swap_id: SwapId,
}

#[derive(Default)]
struct PairAccumulator {
    joint: u64,
    first: Option<WireU64>,
    last: Option<WireU64>,
    swaps: BTreeSet<SwapId>,
}

fn build_co_trades(
    facts: &[TopologyFact],
    transactions: &BTreeMap<TransactionFactId, &TransactionFact>,
    request: &SnapshotRequest,
    config: ReducerConfig,
) -> Result<Vec<WalletPairCoTradeRow>, TopologyError> {
    let activities = co_trade_activities(facts, transactions, request);
    if activities.len() > config.max_pair_activities {
        return Err(TopologyError::BoundExceeded("co-trade activity"));
    }
    let mut pairs: BTreeMap<(AssetId, AccountId, AccountId), PairAccumulator> = BTreeMap::new();
    let window = request.co_trade_window_slots.get();
    for (index, left) in activities.iter().enumerate() {
        for right in &activities[index + 1..] {
            if right.mint != left.mint {
                break;
            }
            if right.slot.get().saturating_sub(left.slot.get()) > window {
                break;
            }
            if right.wallet == left.wallet {
                continue;
            }
            let (wallet_a, wallet_b) = if left.wallet < right.wallet {
                (left.wallet.clone(), right.wallet.clone())
            } else {
                (right.wallet.clone(), left.wallet.clone())
            };
            let value = pairs
                .entry((left.mint.clone(), wallet_a, wallet_b))
                .or_default();
            value.joint = value
                .joint
                .checked_add(1)
                .ok_or(TopologyError::Arithmetic)?;
            value.first = Some(value.first.map_or(left.slot, |known| known.min(left.slot)));
            value.last = Some(value.last.map_or(right.slot, |known| known.max(right.slot)));
            value.swaps.insert(left.swap_id.clone());
            value.swaps.insert(right.swap_id.clone());
        }
    }
    let requested_bound = usize::try_from(request.max_pair_rows.get())
        .map_err(|_| TopologyError::BoundExceeded("pair row"))?;
    if pairs.len() > requested_bound || pairs.len() > config.max_pair_rows {
        return Err(TopologyError::BoundExceeded("pair row"));
    }
    pairs
        .into_iter()
        .enumerate()
        .map(|(index, ((mint_id, wallet_a_id, wallet_b_id), value))| {
            Ok(WalletPairCoTradeRow {
                derivation_id: derivation(&request.snapshot_id, "co_trade", index)?,
                wallet_a_id,
                wallet_b_id,
                mint_id,
                window_slots: request.co_trade_window_slots,
                joint_occurrences: WireU64::new(value.joint),
                first_joint_slot: value.first.ok_or(TopologyError::Arithmetic)?,
                last_joint_slot: value.last.ok_or(TopologyError::Arithmetic)?,
                input_swap_ids: value.swaps.into_iter().collect(),
                evidence_class: EvidenceClass::DeterministicDerived,
            })
        })
        .collect()
}

fn co_trade_activities(
    facts: &[TopologyFact],
    transactions: &BTreeMap<TransactionFactId, &TransactionFact>,
    request: &SnapshotRequest,
) -> Vec<Activity> {
    let focus = request
        .focus_mint_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut activities = Vec::new();
    for fact in facts {
        let TopologyFact::Swap(swap) = fact else {
            continue;
        };
        let Some(wallet) = &swap.trader_wallet_id else {
            continue;
        };
        for mint in [&swap.input.asset_id, &swap.output.asset_id] {
            if focus.contains(mint) {
                activities.push(Activity {
                    mint: mint.clone(),
                    wallet: wallet.clone(),
                    slot: transactions[&swap.transaction_fact_id].slot,
                    swap_id: swap.swap_id.clone(),
                });
            }
        }
    }
    activities.sort_by(|left, right| {
        (&left.mint, left.slot, &left.wallet, &left.swap_id).cmp(&(
            &right.mint,
            right.slot,
            &right.wallet,
            &right.swap_id,
        ))
    });
    activities
}

fn discriminators(values: &[StableString]) -> BTreeSet<&str> {
    values.iter().map(StableString::as_str).collect()
}

fn fact_sort_key(fact: &TopologyFact) -> (u8, String) {
    match fact {
        TopologyFact::Transaction(value) => (0, value.transaction_fact_id.to_string()),
        TopologyFact::CallerAccount(value) => (1, value.association_id.to_string()),
        TopologyFact::Transfer(value) => (2, value.flow_id.to_string()),
        TopologyFact::Swap(value) => (3, value.swap_id.to_string()),
        TopologyFact::LiquidityPositionEvent(value) => (4, value.liquidity_event_id.to_string()),
        TopologyFact::SameTransactionBundle(value) => (5, value.bundle_id.to_string()),
    }
}

fn derivation(
    snapshot_id: &crate::SnapshotId,
    family: &str,
    index: usize,
) -> Result<DerivationId, TopologyError> {
    DerivationId::new(format!("{}:{family}:{index}", snapshot_id.as_str()))
        .map_err(|error| TopologyError::Invalid(error.to_string()))
}

fn stable(value: impl Into<String>) -> Result<StableString, TopologyError> {
    StableString::new(value).map_err(|error| TopologyError::Invalid(error.to_string()))
}

fn validate_sha256(value: &str) -> Result<(), TopologyError> {
    let Some(payload) = value.strip_prefix("sha256:") else {
        return Err(TopologyError::Invalid(
            "digest is not sha256-qualified".into(),
        ));
    };
    if payload.len() != 64
        || !payload
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(TopologyError::Invalid(
            "digest is not lowercase sha256 hex".into(),
        ));
    }
    Ok(())
}

fn require_sorted_unique<T: Ord>(values: &[T], label: &str) -> Result<(), TopologyError> {
    if values.windows(2).any(|pair| pair[0] >= pair[1]) {
        Err(TopologyError::Invalid(format!(
            "{label} must be strictly sorted and unique"
        )))
    } else {
        Ok(())
    }
}
