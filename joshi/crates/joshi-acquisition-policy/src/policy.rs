use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};

use crate::{
    APPLIED_CONTRACT, ActivationAuthority, BudgetEnvelope, CLOSED_CONTRACT, CensusDenominatorRef,
    CensusKind, CollectorGeneration, DEGRADED_CONTRACT, DESIRED_CONTRACT, DegradationChange,
    DegradationReason, EffectiveScope, EvidenceLink, HotScopeClosedV1, HotScopeDegradedV1,
    HotScopeDesiredV1, HotScopeIntentV1, HotScopeRecordV1, INTENT_CONTRACT, MediaFidelity,
    PolicyDecisionV1, PolicyError, PolicyEvaluationV1, PolicyRecordHead, PressureStage,
    ScopePresence, ScopeSubject, SourceAvailability, SourceFamily, SourcePolicyV1,
    SourceScopeRequest, SubjectKind,
};

/// Validated append-only policy history used for restart reconstruction.
#[derive(Clone, Debug)]
pub struct PolicyJournal {
    records: Vec<HotScopeRecordV1>,
}

impl PolicyJournal {
    /// Validate an exact append-only record stream.
    ///
    /// # Errors
    ///
    /// Rejects broken occurrence order, predecessor links, identity reuse, malformed contracts,
    /// invalid intent inputs, and state records that do not close over a prior intent/target.
    pub fn new(records: Vec<HotScopeRecordV1>) -> Result<Self, PolicyError> {
        validate_journal(&records)?;
        Ok(Self { records })
    }

    #[must_use]
    pub fn records(&self) -> &[HotScopeRecordV1] {
        &self.records
    }

    pub(crate) fn next_head(
        &self,
        contract: &str,
        record_id: StableString,
        recorded_at: UtcTimestamp,
    ) -> Result<PolicyRecordHead, PolicyError> {
        next_head_from(&self.records, contract, record_id, recorded_at)
    }
}

/// Deterministically evaluate every current intent under one exact policy/resource snapshot.
///
/// # Errors
///
/// Rejects malformed configuration, resource counters, generations, journal closures, or time
/// arithmetic. It never clamps a malformed/excess budget into apparent permission.
#[allow(clippy::too_many_lines)] // State emission remains centralized for append-order auditability.
pub fn evaluate(
    journal: &PolicyJournal,
    evaluation: &PolicyEvaluationV1,
) -> Result<PolicyDecisionV1, PolicyError> {
    validate_evaluation(evaluation)?;
    let intents = intent_map(journal.records());
    let pressure_stage = pressure_stage(&evaluation.resources)?;
    let retained_census_denominators = retained_denominators(intents.values().copied())?;
    let selected_subjects = selected_subjects(intents.values().copied(), evaluation)?;
    let generations: BTreeMap<_, _> = evaluation
        .collector_generations
        .iter()
        .map(|generation| (generation.source_key.clone(), generation))
        .collect();
    let mut new_records = Vec::new();
    let mut inactive_model_proposal_intent_ids = Vec::new();

    let mut ordered_intents: Vec<_> = intents.values().copied().collect();
    ordered_intents.sort_by(|left, right| left.intent_id.cmp(&right.intent_id));
    for intent in ordered_intents {
        let proposal_only = matches!(intent.activation, ActivationAuthority::ProposalOnly { .. });
        if proposal_only {
            inactive_model_proposal_intent_ids.push(intent.intent_id.clone());
        }
        for requested in &intent.requested_sources {
            let existing = latest_semantic_record(
                journal.records(),
                &intent.intent_id,
                &requested.source_key,
                &requested.operation_key,
            );
            if evaluation.evaluated_at >= intent.expires_at {
                let reason = stable("expired")?;
                if !matches_closed(existing, &reason) {
                    let record = HotScopeRecordV1::Closed(HotScopeClosedV1 {
                        head: generated_head(
                            journal.records(),
                            &new_records,
                            CLOSED_CONTRACT,
                            &evaluation.decision_occurrence_id,
                            evaluation.evaluated_at,
                        )?,
                        intent_id: intent.intent_id.clone(),
                        intent_record_id: intent.head.record_id.clone(),
                        decision_occurrence_id: evaluation.decision_occurrence_id.clone(),
                        source_key: requested.source_key.clone(),
                        operation_key: requested.operation_key.clone(),
                        reason,
                        census_denominators_retained: intent.census_denominators.clone(),
                    });
                    new_records.push(record);
                }
                continue;
            }
            if evaluation.evaluated_at < intent.opened_at {
                continue;
            }
            let selected = selected_subjects.contains(&intent.subject);
            let planned = planned_state(
                intent,
                requested,
                evaluation,
                pressure_stage,
                selected,
                generations.get(&requested.source_key).copied(),
            )?;
            match planned {
                PlannedState::Desired(scope) => {
                    if !matches_desired(existing, &scope) {
                        new_records.push(HotScopeRecordV1::Desired(HotScopeDesiredV1 {
                            head: generated_head(
                                journal.records(),
                                &new_records,
                                DESIRED_CONTRACT,
                                &evaluation.decision_occurrence_id,
                                evaluation.evaluated_at,
                            )?,
                            intent_id: intent.intent_id.clone(),
                            intent_record_id: intent.head.record_id.clone(),
                            decision_occurrence_id: evaluation.decision_occurrence_id.clone(),
                            scope,
                        }));
                    }
                }
                PlannedState::Degraded {
                    effective_scope,
                    changes,
                } => {
                    if !matches_degraded(existing, effective_scope.as_ref(), &changes) {
                        new_records.push(HotScopeRecordV1::Degraded(HotScopeDegradedV1 {
                            head: generated_head(
                                journal.records(),
                                &new_records,
                                DEGRADED_CONTRACT,
                                &evaluation.decision_occurrence_id,
                                evaluation.evaluated_at,
                            )?,
                            intent_id: intent.intent_id.clone(),
                            intent_record_id: intent.head.record_id.clone(),
                            decision_occurrence_id: evaluation.decision_occurrence_id.clone(),
                            source_key: requested.source_key.clone(),
                            operation_key: requested.operation_key.clone(),
                            effective_scope,
                            changes,
                            census_denominators_retained: intent.census_denominators.clone(),
                        }));
                    }
                }
            }
        }
    }

    let mut combined = journal.records().to_vec();
    combined.extend(new_records.iter().cloned());
    let latest_desired_presence = latest_presence(&combined)?;
    Ok(PolicyDecisionV1 {
        decision_occurrence_id: evaluation.decision_occurrence_id.clone(),
        evaluated_at: evaluation.evaluated_at,
        pressure_stage,
        new_records,
        retained_census_denominators,
        inactive_model_proposal_intent_ids,
        latest_desired_presence,
    })
}

enum PlannedState {
    Desired(EffectiveScope),
    Degraded {
        effective_scope: Option<EffectiveScope>,
        changes: Vec<DegradationChange>,
    },
}

#[allow(clippy::too_many_lines)] // Ordered degradation is easier to audit as one explicit ladder.
fn planned_state(
    intent: &HotScopeIntentV1,
    requested: &SourceScopeRequest,
    evaluation: &PolicyEvaluationV1,
    pressure: PressureStage,
    selected: bool,
    generation: Option<&CollectorGeneration>,
) -> Result<PlannedState, PolicyError> {
    let mut changes = Vec::new();
    let source_policy = evaluation
        .policy
        .source_policies
        .iter()
        .find(|policy| policy.source_key == requested.source_key);
    let mut active = true;

    if matches!(intent.activation, ActivationAuthority::ProposalOnly { .. }) {
        active = false;
        changes.push(change(
            DegradationReason::ModelProposalNonactivating,
            "model proposal requires a distinct operator-accepted intent",
            &[],
        )?);
    }
    if !selected && !matches!(intent.activation, ActivationAuthority::ProposalOnly { .. }) {
        active = false;
        changes.push(change(
            DegradationReason::CapacityEvictedLeastRecentlyJustified,
            "subject is outside the deterministic recency capacity cut",
            &[],
        )?);
    }
    if intent.policy_config_digest != evaluation.policy.config_digest {
        active = false;
        changes.push(change(
            DegradationReason::PolicyConfigMismatch,
            "intent policy digest differs from evaluation policy digest",
            &[],
        )?);
    }
    match source_policy {
        None => {
            active = false;
            changes.push(change(
                DegradationReason::BudgetRefused,
                "source is absent from the policy allowlist",
                &[],
            )?);
        }
        Some(policy) if !source_request_allowed(requested, policy)? => {
            active = false;
            changes.push(change(
                DegradationReason::BudgetRefused,
                "source operation or one independent budget dimension exceeds its hard ceiling",
                &[],
            )?);
        }
        Some(_) => {}
    }
    match generation {
        None => {
            active = false;
            changes.push(change(
                DegradationReason::SourceUnavailable,
                "collector supplied no generation/health record for this source",
                &[],
            )?);
        }
        Some(value) if value.availability == SourceAvailability::Unavailable => {
            active = false;
            changes.push(change(
                DegradationReason::SourceUnavailable,
                "collector source generation is unavailable",
                &value.evidence,
            )?);
        }
        Some(value) if value.availability == SourceAvailability::Degraded => {
            changes.push(change(
                DegradationReason::SourceDegraded,
                "collector source generation reports degraded health",
                &value.evidence,
            )?);
        }
        Some(_) => {}
    }
    if pressure == PressureStage::DenominatorOnly {
        active = false;
        changes.push(change(
            DegradationReason::DenominatorOnlyOverload,
            "hot acquisition is absent while the census denominator is retained",
            &evaluation.resources.evidence,
        )?);
    } else if pressure == PressureStage::StopBeforeReserve {
        active = false;
        changes.push(change(
            DegradationReason::StopBeforeReserve,
            "hot acquisition stopped before disk or protected control reserve exhaustion",
            &evaluation.resources.evidence,
        )?);
    }

    let mut fidelity = requested.fidelity.clone();
    let mut expires_at = intent.expires_at;
    if pressure >= PressureStage::DropOptionalBodies {
        let fidelity_reduced = fidelity.exact_private_bodies_optional
            || fidelity.media == MediaFidelity::ExactOptional;
        fidelity.exact_private_bodies_optional = false;
        if fidelity.media == MediaFidelity::ExactOptional {
            fidelity.media = MediaFidelity::None;
        }
        if fidelity_reduced {
            changes.push(change(
                DegradationReason::OptionalBodiesDropped,
                "optional media and exact private bodies are disabled first",
                &evaluation.resources.evidence,
            )?);
        }
    }
    if pressure >= PressureStage::SlowRefresh && is_social(requested.source_family) {
        let floor = evaluation.policy.degraded_social_refresh_us;
        if fidelity
            .refresh_interval_us
            .is_some_and(|requested| requested < floor)
        {
            fidelity.refresh_interval_us = Some(floor);
            changes.push(change(
                DegradationReason::SocialRefreshSlowed,
                "social/profile refresh is slowed to the configured deterministic floor",
                &evaluation.resources.evidence,
            )?);
        }
    }
    if pressure >= PressureStage::ShortenHotLeases {
        let shortened = add_microseconds(
            intent.last_justified_at,
            evaluation.policy.shortened_hot_ttl_us,
        )?;
        if shortened < expires_at {
            expires_at = shortened;
            changes.push(change(
                DegradationReason::HotLeaseShortened,
                "expiry is capped at last justification plus the configured degraded TTL",
                &evaluation.resources.evidence,
            )?);
        }
        if evaluation.evaluated_at >= expires_at {
            active = false;
        }
    }
    changes.sort();
    changes.dedup();

    let effective_scope = active.then(|| EffectiveScope {
        subject: intent.subject.clone(),
        source_key: requested.source_key.clone(),
        operation_key: requested.operation_key.clone(),
        source_family: requested.source_family,
        fidelity,
        budget: requested.budget.clone(),
        expires_at,
        census_denominators: intent.census_denominators.clone(),
    });
    if changes.is_empty() {
        Ok(PlannedState::Desired(
            effective_scope.expect("active when there are no degradation changes"),
        ))
    } else {
        Ok(PlannedState::Degraded {
            effective_scope,
            changes,
        })
    }
}

fn selected_subjects<'a>(
    intents: impl Iterator<Item = &'a HotScopeIntentV1>,
    evaluation: &PolicyEvaluationV1,
) -> Result<BTreeSet<ScopeSubject>, PolicyError> {
    let mut recency = BTreeMap::<ScopeSubject, (UtcTimestamp, StableString)>::new();
    for intent in intents.filter(|intent| {
        intent.opened_at <= evaluation.evaluated_at
            && evaluation.evaluated_at < intent.expires_at
            && !matches!(intent.activation, ActivationAuthority::ProposalOnly { .. })
    }) {
        let candidate = (intent.last_justified_at, intent.intent_id.clone());
        recency
            .entry(intent.subject.clone())
            .and_modify(|current| {
                if candidate > *current {
                    *current = candidate.clone();
                }
            })
            .or_insert(candidate);
    }
    let mut by_kind = BTreeMap::<SubjectKind, Vec<_>>::new();
    for (subject, score) in recency {
        by_kind
            .entry(subject.kind)
            .or_default()
            .push((subject, score));
    }
    let mut selected = BTreeSet::new();
    for (kind, mut candidates) in by_kind {
        candidates.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        let cap = match kind {
            SubjectKind::Mint => evaluation.policy.max_hot_mints.get(),
            SubjectKind::Wallet => evaluation.policy.max_hot_wallets.get(),
            SubjectKind::Profile | SubjectKind::Community | SubjectKind::Territory => {
                evaluation.policy.max_other_subjects.get()
            }
        };
        let cap = usize::try_from(cap).map_err(|_| {
            PolicyError::InvalidValue("subject capacity does not fit local usize".into())
        })?;
        selected.extend(candidates.into_iter().take(cap).map(|(subject, _)| subject));
    }
    Ok(selected)
}

fn pressure_stage(resources: &crate::ResourceSnapshotV1) -> Result<PressureStage, PolicyError> {
    validate_resources(resources)?;
    if resources.disk_free_bytes <= resources.disk_floor_bytes
        || resources.control_reserve_free_bytes < resources.control_reserve_required_bytes
    {
        return Ok(PressureStage::StopBeforeReserve);
    }
    let record_usable = resources
        .queue_record_capacity
        .get()
        .checked_sub(resources.queue_record_control_reserve.get())
        .ok_or_else(|| PolicyError::InvalidValue("record reserve exceeds capacity".into()))?;
    let byte_usable = resources
        .queue_byte_capacity
        .get()
        .checked_sub(resources.queue_byte_control_reserve.get())
        .ok_or_else(|| PolicyError::InvalidValue("byte reserve exceeds capacity".into()))?;
    if resources.spool_bytes_today >= resources.max_spool_bytes_today
        || resources.queue_records_used.get() >= record_usable
        || resources.queue_bytes_used.get() >= byte_usable
    {
        return Ok(PressureStage::DenominatorOnly);
    }
    Ok(max_stage(
        utilization_stage(resources.queue_records_used.get(), record_usable),
        utilization_stage(resources.queue_bytes_used.get(), byte_usable),
    ))
}

fn utilization_stage(used: u64, capacity: u64) -> PressureStage {
    let used = u128::from(used);
    let capacity = u128::from(capacity);
    if used * 100 >= capacity * 90 {
        PressureStage::ShortenHotLeases
    } else if used * 100 >= capacity * 75 {
        PressureStage::SlowRefresh
    } else if used * 100 >= capacity * 50 {
        PressureStage::DropOptionalBodies
    } else {
        PressureStage::Full
    }
}

const fn max_stage(left: PressureStage, right: PressureStage) -> PressureStage {
    if left as u8 >= right as u8 {
        left
    } else {
        right
    }
}

fn source_request_allowed(
    request: &SourceScopeRequest,
    policy: &SourcePolicyV1,
) -> Result<bool, PolicyError> {
    Ok(policy
        .operation_keys
        .binary_search(&request.operation_key)
        .is_ok()
        && budget_within(
            &request.budget,
            &policy.maximum_budget,
            policy.native_units_authorized,
        )?)
}

fn budget_within(
    requested: &BudgetEnvelope,
    ceiling: &BudgetEnvelope,
    native_authorized: bool,
) -> Result<bool, PolicyError> {
    validate_budget(requested)?;
    validate_budget(ceiling)?;
    if requested.max_requests > ceiling.max_requests
        || requested.max_pages > ceiling.max_pages
        || requested.max_response_bytes > ceiling.max_response_bytes
        || requested.max_provider_credits > ceiling.max_provider_credits
        || (!native_authorized && !requested.chain_native.is_empty())
    {
        return Ok(false);
    }
    let currency_ok = requested.provider_currency.iter().all(|budget| {
        ceiling.provider_currency.iter().any(|limit| {
            limit.currency == budget.currency
                && limit.decimals_evidence == budget.decimals_evidence
                && budget.max_minor_units <= limit.max_minor_units
        })
    });
    let native_ok = requested.chain_native.iter().all(|budget| {
        ceiling.chain_native.iter().any(|limit| {
            limit.asset_id == budget.asset_id
                && limit.decimals_evidence == budget.decimals_evidence
                && budget.max_atoms <= limit.max_atoms
        })
    });
    Ok(currency_ok && native_ok)
}

#[allow(clippy::too_many_lines)] // All append-only transition checks share one ordered pass.
fn validate_journal(records: &[HotScopeRecordV1]) -> Result<(), PolicyError> {
    let mut identities = BTreeSet::new();
    let mut intents = BTreeMap::new();
    let mut target_records = BTreeMap::new();
    let mut latest_targets = BTreeMap::new();
    let mut previous: Option<&PolicyRecordHead> = None;
    let mut closed = BTreeSet::new();
    for record in records {
        let head = record.head();
        if head.schema_version.get() != 1 {
            return Err(PolicyError::InvalidContract(
                "policy record schemaVersion must be 1".into(),
            ));
        }
        let expected_contract = match record {
            HotScopeRecordV1::Intent(_) => INTENT_CONTRACT,
            HotScopeRecordV1::Desired(_) => DESIRED_CONTRACT,
            HotScopeRecordV1::Applied(_) => APPLIED_CONTRACT,
            HotScopeRecordV1::Degraded(_) => DEGRADED_CONTRACT,
            HotScopeRecordV1::Closed(_) => CLOSED_CONTRACT,
        };
        if head.contract.as_str() != expected_contract {
            return Err(PolicyError::InvalidContract(format!(
                "record expects {expected_contract}"
            )));
        }
        if !identities.insert(head.record_id.clone()) {
            return Err(PolicyError::Journal(
                "duplicate record occurrence id".into(),
            ));
        }
        match previous {
            None if head.predecessor_record_id.is_some() => {
                return Err(PolicyError::Journal(
                    "first record cannot name a predecessor".into(),
                ));
            }
            Some(prior)
                if prior.record_ordinal.get().checked_add(1) != Some(head.record_ordinal.get())
                    || head.predecessor_record_id.as_ref() != Some(&prior.record_id)
                    || head.recorded_at < prior.recorded_at =>
            {
                return Err(PolicyError::Journal(
                    "record ordinal/predecessor does not close over the prior append".into(),
                ));
            }
            _ => {}
        }
        match record {
            HotScopeRecordV1::Intent(intent) => {
                validate_intent(intent)?;
                if intents.insert(intent.intent_id.clone(), intent).is_some() {
                    return Err(PolicyError::Journal("duplicate intent identity".into()));
                }
            }
            HotScopeRecordV1::Desired(value) => {
                validate_state_source(
                    &intents,
                    &value.intent_id,
                    &value.intent_record_id,
                    &value.scope.source_key,
                    &value.scope.operation_key,
                )?;
                ensure_not_closed(
                    &closed,
                    &value.intent_id,
                    &value.scope.source_key,
                    &value.scope.operation_key,
                )?;
                let intent = intents
                    .get(&value.intent_id)
                    .expect("validated intent exists");
                let request = intent
                    .requested_sources
                    .iter()
                    .find(|request| {
                        request.source_key == value.scope.source_key
                            && request.operation_key == value.scope.operation_key
                    })
                    .expect("validated source exists");
                validate_effective_scope(intent, request, &value.scope, false)?;
                target_records.insert(
                    value.head.record_id.clone(),
                    (
                        value.intent_id.clone(),
                        value.scope.source_key.clone(),
                        value.scope.operation_key.clone(),
                        ScopePresence::Active,
                    ),
                );
                latest_targets.insert(
                    state_key(
                        &value.intent_id,
                        &value.scope.source_key,
                        &value.scope.operation_key,
                    ),
                    value.head.record_id.clone(),
                );
            }
            HotScopeRecordV1::Degraded(value) => {
                validate_state_source(
                    &intents,
                    &value.intent_id,
                    &value.intent_record_id,
                    &value.source_key,
                    &value.operation_key,
                )?;
                ensure_not_closed(
                    &closed,
                    &value.intent_id,
                    &value.source_key,
                    &value.operation_key,
                )?;
                validate_sorted_unique(&value.changes, "degradation changes")?;
                if value.changes.is_empty() {
                    return Err(PolicyError::Journal(
                        "degraded record requires an explicit change/reason".into(),
                    ));
                }
                let intent = intents
                    .get(&value.intent_id)
                    .expect("validated intent exists");
                if value.census_denominators_retained != intent.census_denominators {
                    return Err(PolicyError::Journal(
                        "degraded record changed the denominator closure".into(),
                    ));
                }
                for change in &value.changes {
                    validate_sorted_unique(&change.evidence, "degradation evidence")?;
                    if change
                        .evidence
                        .iter()
                        .any(|link| link.available_at > value.head.recorded_at)
                    {
                        return Err(PolicyError::Journal(
                            "degradation uses future-known evidence".into(),
                        ));
                    }
                }
                if let Some(scope) = &value.effective_scope {
                    let request = intent
                        .requested_sources
                        .iter()
                        .find(|request| {
                            request.source_key == value.source_key
                                && request.operation_key == value.operation_key
                        })
                        .expect("validated source exists");
                    validate_effective_scope(intent, request, scope, true)?;
                }
                let presence = if value.effective_scope.is_some() {
                    ScopePresence::Active
                } else {
                    ScopePresence::Absent
                };
                target_records.insert(
                    value.head.record_id.clone(),
                    (
                        value.intent_id.clone(),
                        value.source_key.clone(),
                        value.operation_key.clone(),
                        presence,
                    ),
                );
                latest_targets.insert(
                    state_key(&value.intent_id, &value.source_key, &value.operation_key),
                    value.head.record_id.clone(),
                );
            }
            HotScopeRecordV1::Closed(value) => {
                validate_state_source(
                    &intents,
                    &value.intent_id,
                    &value.intent_record_id,
                    &value.source_key,
                    &value.operation_key,
                )?;
                let key = state_key(&value.intent_id, &value.source_key, &value.operation_key);
                let intent = intents
                    .get(&value.intent_id)
                    .expect("validated intent exists");
                if value.census_denominators_retained != intent.census_denominators {
                    return Err(PolicyError::Journal(
                        "closed record changed the denominator closure".into(),
                    ));
                }
                if !closed.insert(key) {
                    return Err(PolicyError::Journal(
                        "scope source was closed more than once".into(),
                    ));
                }
                target_records.insert(
                    value.head.record_id.clone(),
                    (
                        value.intent_id.clone(),
                        value.source_key.clone(),
                        value.operation_key.clone(),
                        ScopePresence::Absent,
                    ),
                );
                latest_targets.insert(
                    state_key(&value.intent_id, &value.source_key, &value.operation_key),
                    value.head.record_id.clone(),
                );
            }
            HotScopeRecordV1::Applied(value) => {
                let Some((intent, source, operation, presence)) =
                    target_records.get(&value.target_record_id)
                else {
                    return Err(PolicyError::Journal(
                        "applied record references an unknown or later control target".into(),
                    ));
                };
                if (
                    &value.intent_id,
                    &value.source_key,
                    &value.operation_key,
                    value.presence,
                ) != (intent, source, operation, *presence)
                    || value.provider_acceptance.as_str() != "not_asserted"
                    || value.coverage_status.as_str() != "not_asserted"
                {
                    return Err(PolicyError::Journal(
                        "applied record changes target meaning or asserts provider coverage".into(),
                    ));
                }
                if latest_targets.get(&state_key(
                    &value.intent_id,
                    &value.source_key,
                    &value.operation_key,
                )) != Some(&value.target_record_id)
                    || value.control_handed_to_adapter_at > value.head.recorded_at
                {
                    return Err(PolicyError::Journal(
                        "applied record targets stale state or predates local control handoff"
                            .into(),
                    ));
                }
                validate_digest(&value.control_bytes_digest)?;
                validate_digest(&value.control_write_reservation_digest)?;
            }
        }
        previous = Some(head);
    }
    Ok(())
}

fn validate_effective_scope(
    intent: &HotScopeIntentV1,
    requested: &SourceScopeRequest,
    scope: &EffectiveScope,
    degraded: bool,
) -> Result<(), PolicyError> {
    if scope.subject != intent.subject
        || scope.source_key != requested.source_key
        || scope.operation_key != requested.operation_key
        || scope.source_family != requested.source_family
        || scope.budget != requested.budget
        || scope.census_denominators != intent.census_denominators
        || scope.expires_at > intent.expires_at
    {
        return Err(PolicyError::Journal(
            "effective scope expanded or changed its exact intent/source closure".into(),
        ));
    }
    if !degraded {
        if scope.fidelity != requested.fidelity || scope.expires_at != intent.expires_at {
            return Err(PolicyError::Journal(
                "desired scope must retain exact requested fidelity and expiry".into(),
            ));
        }
        return Ok(());
    }
    let refresh_not_faster = match (
        requested.fidelity.refresh_interval_us,
        scope.fidelity.refresh_interval_us,
    ) {
        (None, None) => true,
        (Some(requested), Some(effective)) => effective >= requested,
        _ => false,
    };
    if scope.fidelity.exact_public_bodies != requested.fidelity.exact_public_bodies
        || (scope.fidelity.exact_private_bodies_optional
            && !requested.fidelity.exact_private_bodies_optional)
        || scope.fidelity.media > requested.fidelity.media
        || !refresh_not_faster
    {
        return Err(PolicyError::Journal(
            "degraded scope increased source fidelity or refresh rate".into(),
        ));
    }
    Ok(())
}

fn validate_intent(intent: &HotScopeIntentV1) -> Result<(), PolicyError> {
    if intent.authority.as_str() != "read_only_no_execution" {
        return Err(PolicyError::InvalidValue(
            "intent authority must be read_only_no_execution".into(),
        ));
    }
    if intent.opened_at >= intent.expires_at
        || intent.last_justified_at > intent.head.recorded_at
        || intent.last_justified_at > intent.as_of.available_through
        || intent.as_of.available_through > intent.head.recorded_at
    {
        return Err(PolicyError::InvalidValue(
            "intent interval or knowledge clocks are invalid".into(),
        ));
    }
    let intent_commit = intent.as_of.commit_through.ok_or_else(|| {
        PolicyError::InvalidValue("hot-scope intent requires a bounded commit cutoff".into())
    })?;
    validate_digest(&intent.policy_config_digest)?;
    if intent.reasons.is_empty()
        || intent.census_denominators.is_empty()
        || intent.requested_sources.is_empty()
    {
        return Err(PolicyError::InvalidValue(
            "intent requires reasons, denominator closure, and requested sources".into(),
        ));
    }
    validate_sorted_unique(&intent.reasons, "intent reasons")?;
    validate_sorted_unique(&intent.census_denominators, "census denominators")?;
    validate_sorted_unique(&intent.requested_sources, "requested sources")?;
    let latest_reason = intent
        .reasons
        .iter()
        .map(|reason| reason.justified_at)
        .max()
        .expect("nonempty reasons");
    if latest_reason != intent.last_justified_at {
        return Err(PolicyError::InvalidValue(
            "lastJustifiedAt must equal the latest exact reason time".into(),
        ));
    }
    for reason in &intent.reasons {
        if reason.justified_at > intent.as_of.available_through || reason.evidence.is_empty() {
            return Err(PolicyError::InvalidValue(
                "reason is future-known or has no evidence".into(),
            ));
        }
        validate_sorted_unique(&reason.evidence, "reason evidence")?;
        validate_evidence_cut(&reason.evidence, &intent.as_of, "reason evidence")?;
    }
    if !intent
        .reasons
        .iter()
        .flat_map(|reason| &reason.evidence)
        .any(|link| {
            link.kind == crate::EvidenceKind::PolicyOccurrence
                && link.id == intent.policy_occurrence_id
                && link.digest.as_ref() == Some(&intent.policy_config_digest)
        })
    {
        return Err(PolicyError::InvalidValue(
            "intent lacks exact policy occurrence/config evidence".into(),
        ));
    }
    let has_model_reason = intent
        .reasons
        .iter()
        .any(|reason| reason.kind == crate::IntentReasonKind::ModelProposal);
    if has_model_reason && !matches!(intent.activation, ActivationAuthority::ProposalOnly { .. }) {
        return Err(PolicyError::InvalidValue(
            "a model proposal must remain proposal-only; acceptance is a distinct intent".into(),
        ));
    }
    if matches!(intent.activation, ActivationAuthority::ProposalOnly { .. }) && !has_model_reason {
        return Err(PolicyError::InvalidValue(
            "proposal-only authority requires a model-proposal reason".into(),
        ));
    }
    validate_activation_binding(intent)?;
    for denominator in &intent.census_denominators {
        validate_denominator(denominator)?;
        if denominator.as_of.available_through > intent.as_of.available_through {
            return Err(PolicyError::InvalidValue(
                "denominator is later-known than intent cutoff".into(),
            ));
        }
        let denominator_commit = denominator.as_of.commit_through.ok_or_else(|| {
            PolicyError::InvalidValue("denominator requires a bounded commit cutoff".into())
        })?;
        if denominator_commit > intent_commit {
            return Err(PolicyError::InvalidValue(
                "denominator commit cutoff exceeds intent commit cutoff".into(),
            ));
        }
    }
    for requested in &intent.requested_sources {
        validate_budget(&requested.budget)?;
    }
    Ok(())
}

fn validate_denominator(value: &CensusDenominatorRef) -> Result<(), PolicyError> {
    validate_digest(&value.eligible_universe_digest)?;
    validate_sorted_unique(&value.evidence, "denominator evidence")?;
    validate_sorted_unique(&value.coverage_evidence, "denominator coverage evidence")?;
    if value.evidence.is_empty()
        || value.coverage_evidence.is_empty()
        || value
            .coverage_evidence
            .iter()
            .any(|link| link.kind != crate::EvidenceKind::Coverage)
    {
        return Err(PolicyError::InvalidValue(
            "denominator requires evidence and typed coverage closure".into(),
        ));
    }
    if value.as_of.commit_through.is_none() {
        return Err(PolicyError::InvalidValue(
            "denominator requires a bounded commit cutoff".into(),
        ));
    }
    validate_evidence_cut(&value.evidence, &value.as_of, "denominator evidence")?;
    validate_evidence_cut(
        &value.coverage_evidence,
        &value.as_of,
        "denominator coverage evidence",
    )?;
    if value.kind == CensusKind::ProductBoardParityPassed && value.parity_receipt_id.is_none() {
        return Err(PolicyError::InvalidValue(
            "product-board denominator requires a passed parity receipt".into(),
        ));
    }
    if value.kind == CensusKind::IndependentChainProvider && value.parity_receipt_id.is_some() {
        return Err(PolicyError::InvalidValue(
            "independent census cannot claim a product-board parity receipt".into(),
        ));
    }
    Ok(())
}

fn validate_activation_binding(intent: &HotScopeIntentV1) -> Result<(), PolicyError> {
    if let ActivationAuthority::ProposalOnly {
        model_artifact_id,
        model_proposal_id,
    } = &intent.activation
    {
        let has_artifact = intent
            .reasons
            .iter()
            .flat_map(|reason| &reason.evidence)
            .any(|link| {
                link.kind == crate::EvidenceKind::Artifact && &link.id == model_artifact_id
            });
        if &intent.requesting_occurrence_id != model_proposal_id || !has_artifact {
            return Err(PolicyError::InvalidValue(
                "model proposal lacks its exact proposal occurrence or artifact evidence".into(),
            ));
        }
        return Ok(());
    }
    let ActivationAuthority::OperatorAccepted(binding) = &intent.activation else {
        return Ok(());
    };
    let crate::OperatorAcceptanceBinding {
        operator_command_id,
        operator_command_digest,
        operator_admission_receipt_id,
        scene_id,
        scene_view_digest,
        presentation_choice_binding,
    } = binding.as_ref();
    validate_digest(operator_command_digest)?;
    validate_digest(scene_view_digest)?;
    if intent.scene_id.as_ref() != Some(scene_id)
        || &intent.requesting_occurrence_id != operator_command_id
    {
        return Err(PolicyError::InvalidValue(
            "operator activation command/scene does not match the intent request".into(),
        ));
    }
    let evidence = intent.reasons.iter().flat_map(|reason| &reason.evidence);
    let mut has_command = false;
    let mut has_scene = false;
    let mut has_receipt = false;
    for link in evidence {
        has_command |= link.kind == crate::EvidenceKind::OperatorCommand
            && &link.id == operator_command_id
            && link.digest.as_ref() == Some(operator_command_digest);
        has_scene |= link.kind == crate::EvidenceKind::Scene
            && &link.id == scene_id
            && link.digest.as_ref() == Some(scene_view_digest);
        has_receipt |=
            link.kind == crate::EvidenceKind::Receipt && &link.id == operator_admission_receipt_id;
    }
    if !has_command || !has_scene || !has_receipt {
        return Err(PolicyError::InvalidValue(
            "operator activation lacks exact command, scene, or admission-receipt evidence".into(),
        ));
    }
    if let Some(binding) = presentation_choice_binding {
        validate_digest(&binding.presentation_digest)?;
        match (&binding.choice_context_id, &binding.choice_context_digest) {
            (Some(_), Some(digest)) => validate_digest(digest)?,
            (None, None) => {}
            _ => {
                return Err(PolicyError::InvalidValue(
                    "choice-context identity and digest must be jointly present or absent".into(),
                ));
            }
        }
        let commit_cut = intent.as_of.commit_through.ok_or_else(|| {
            PolicyError::InvalidValue("operator activation requires a commit cutoff".into())
        })?;
        if binding.available_at > intent.as_of.available_through || binding.commit_seq > commit_cut
        {
            return Err(PolicyError::InvalidValue(
                "presentation/choice binding is later-known than the intent cutoff".into(),
            ));
        }
    }
    Ok(())
}

fn validate_evidence_cut(
    values: &[EvidenceLink],
    as_of: &crate::AsOfCutoff,
    what: &str,
) -> Result<(), PolicyError> {
    let commit_cut = as_of.commit_through.ok_or_else(|| {
        PolicyError::InvalidValue(format!("{what} requires a bounded commit cutoff"))
    })?;
    for value in values {
        let commit = value.commit_seq.ok_or_else(|| {
            PolicyError::InvalidValue(format!("{what} link requires a commit sequence"))
        })?;
        if value.available_at > as_of.available_through || commit > commit_cut {
            return Err(PolicyError::InvalidValue(format!(
                "{what} is later-known than its declared as-of"
            )));
        }
        if let Some(digest) = &value.digest {
            validate_digest(digest)?;
        }
    }
    Ok(())
}

fn validate_evaluation(value: &PolicyEvaluationV1) -> Result<(), PolicyError> {
    validate_digest(&value.policy.config_digest)?;
    if value.policy.max_hot_mints.get() == 0
        || value.policy.max_hot_wallets.get() == 0
        || value.policy.shortened_hot_ttl_us.get() == 0
        || value.policy.degraded_social_refresh_us.get() == 0
        || value.policy.shortened_hot_ttl_us.get() > i64::MAX as u64
    {
        return Err(PolicyError::InvalidValue(
            "policy capacities and degradation durations must be positive and representable".into(),
        ));
    }
    validate_sorted_unique_by(
        &value.policy.source_policies,
        |item| &item.source_key,
        "source policies",
    )?;
    for source in &value.policy.source_policies {
        validate_sorted_unique(&source.operation_keys, "source operation keys")?;
        if source.operation_keys.is_empty() {
            return Err(PolicyError::InvalidValue(
                "source policy requires an operation allowlist".into(),
            ));
        }
        validate_budget(&source.maximum_budget)?;
    }
    validate_sorted_unique_by(
        &value.collector_generations,
        |item| &item.source_key,
        "collector generations",
    )?;
    for generation in &value.collector_generations {
        validate_sorted_unique(&generation.evidence, "source-health evidence")?;
        if generation.evidence.is_empty()
            || generation
                .evidence
                .iter()
                .any(|link| link.available_at > value.evaluated_at)
        {
            return Err(PolicyError::InvalidValue(
                "collector generation requires source-health evidence known by evaluation".into(),
            ));
        }
        validate_optional_evidence_digests(&generation.evidence)?;
    }
    if value.resources.sampled_at > value.evaluated_at
        || value.resources.evidence.is_empty()
        || value
            .resources
            .evidence
            .iter()
            .any(|link| link.available_at > value.evaluated_at)
    {
        return Err(PolicyError::InvalidValue(
            "resource snapshot requires evidence sampled and known by evaluation".into(),
        ));
    }
    validate_sorted_unique(&value.resources.evidence, "resource evidence")?;
    validate_optional_evidence_digests(&value.resources.evidence)?;
    validate_resources(&value.resources)
}

fn validate_optional_evidence_digests(values: &[EvidenceLink]) -> Result<(), PolicyError> {
    for value in values {
        if let Some(digest) = &value.digest {
            validate_digest(digest)?;
        }
    }
    Ok(())
}

fn validate_resources(value: &crate::ResourceSnapshotV1) -> Result<(), PolicyError> {
    if value.queue_record_capacity.get() == 0
        || value.queue_byte_capacity.get() == 0
        || value.max_spool_bytes_today.get() == 0
        || value.queue_record_control_reserve >= value.queue_record_capacity
        || value.queue_byte_control_reserve >= value.queue_byte_capacity
    {
        return Err(PolicyError::InvalidValue(
            "resource capacity is zero or protected reserve is not strictly smaller".into(),
        ));
    }
    Ok(())
}

fn validate_budget(value: &BudgetEnvelope) -> Result<(), PolicyError> {
    validate_sorted_unique_by(
        &value.provider_currency,
        |item| &item.currency,
        "provider currency budgets",
    )?;
    validate_sorted_unique_by(
        &value.chain_native,
        |item| &item.asset_id,
        "chain-native budgets",
    )?;
    for budget in &value.provider_currency {
        validate_digest_link(&budget.decimals_evidence)?;
    }
    for budget in &value.chain_native {
        validate_digest_link(&budget.decimals_evidence)?;
    }
    Ok(())
}

fn validate_digest_link(value: &EvidenceLink) -> Result<(), PolicyError> {
    let digest = value.digest.as_ref().ok_or_else(|| {
        PolicyError::InvalidValue("decimals evidence requires an exact digest".into())
    })?;
    validate_digest(digest)
}

fn validate_digest(value: &ValueDigest) -> Result<(), PolicyError> {
    let Some(hex) = value.as_str().strip_prefix("sha256:") else {
        return Err(PolicyError::InvalidValue(
            "digest must be sha256-qualified".into(),
        ));
    };
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(PolicyError::InvalidValue(
            "digest must contain 64 lowercase hexadecimal digits".into(),
        ));
    }
    Ok(())
}

fn validate_sorted_unique<T: Ord>(values: &[T], what: &str) -> Result<(), PolicyError> {
    if values.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(PolicyError::InvalidValue(format!(
            "{what} must be sorted and duplicate-free"
        )));
    }
    Ok(())
}

fn validate_sorted_unique_by<T, K: Ord>(
    values: &[T],
    key: impl Fn(&T) -> &K,
    what: &str,
) -> Result<(), PolicyError> {
    if values.windows(2).any(|pair| key(&pair[0]) >= key(&pair[1])) {
        return Err(PolicyError::InvalidValue(format!(
            "{what} must be sorted and duplicate-free"
        )));
    }
    Ok(())
}

fn validate_state_source(
    intents: &BTreeMap<StableString, &HotScopeIntentV1>,
    intent_id: &StableString,
    intent_record_id: &StableString,
    source_key: &StableString,
    operation_key: &StableString,
) -> Result<(), PolicyError> {
    let intent = intents
        .get(intent_id)
        .ok_or_else(|| PolicyError::Journal("state references an unknown intent".into()))?;
    if &intent.head.record_id != intent_record_id
        || !intent.requested_sources.iter().any(|request| {
            &request.source_key == source_key && &request.operation_key == operation_key
        })
    {
        return Err(PolicyError::Journal(
            "state does not close over the exact intent/source operation".into(),
        ));
    }
    Ok(())
}

fn ensure_not_closed(
    closed: &BTreeSet<String>,
    intent: &StableString,
    source: &StableString,
    operation: &StableString,
) -> Result<(), PolicyError> {
    if closed.contains(&state_key(intent, source, operation)) {
        Err(PolicyError::Journal(
            "desired/degraded state follows terminal closure".into(),
        ))
    } else {
        Ok(())
    }
}

fn intent_map(records: &[HotScopeRecordV1]) -> BTreeMap<StableString, &HotScopeIntentV1> {
    records
        .iter()
        .filter_map(|record| match record {
            HotScopeRecordV1::Intent(value) => Some((value.intent_id.clone(), value)),
            _ => None,
        })
        .collect()
}

pub(crate) fn latest_semantic_record<'a>(
    records: &'a [HotScopeRecordV1],
    intent: &StableString,
    source: &StableString,
    operation: &StableString,
) -> Option<&'a HotScopeRecordV1> {
    records.iter().rev().find(|record| match record {
        HotScopeRecordV1::Desired(value) => {
            &value.intent_id == intent
                && &value.scope.source_key == source
                && &value.scope.operation_key == operation
        }
        HotScopeRecordV1::Degraded(value) => {
            &value.intent_id == intent
                && &value.source_key == source
                && &value.operation_key == operation
        }
        HotScopeRecordV1::Closed(value) => {
            &value.intent_id == intent
                && &value.source_key == source
                && &value.operation_key == operation
        }
        HotScopeRecordV1::Intent(_) | HotScopeRecordV1::Applied(_) => false,
    })
}

pub(crate) fn semantic_target(
    record: &HotScopeRecordV1,
) -> Option<(
    &StableString,
    &StableString,
    &StableString,
    ScopePresence,
    Option<&EffectiveScope>,
)> {
    match record {
        HotScopeRecordV1::Desired(value) => Some((
            &value.intent_id,
            &value.scope.source_key,
            &value.scope.operation_key,
            ScopePresence::Active,
            Some(&value.scope),
        )),
        HotScopeRecordV1::Degraded(value) => Some((
            &value.intent_id,
            &value.source_key,
            &value.operation_key,
            if value.effective_scope.is_some() {
                ScopePresence::Active
            } else {
                ScopePresence::Absent
            },
            value.effective_scope.as_ref(),
        )),
        HotScopeRecordV1::Closed(value) => Some((
            &value.intent_id,
            &value.source_key,
            &value.operation_key,
            ScopePresence::Absent,
            None,
        )),
        HotScopeRecordV1::Intent(_) | HotScopeRecordV1::Applied(_) => None,
    }
}

fn latest_presence(
    records: &[HotScopeRecordV1],
) -> Result<BTreeMap<StableString, ScopePresence>, PolicyError> {
    let mut result = BTreeMap::new();
    for record in records {
        if let Some((intent, source, operation, presence, _)) = semantic_target(record) {
            result.insert(stable(state_key(intent, source, operation))?, presence);
        }
    }
    Ok(result)
}

fn retained_denominators<'a>(
    intents: impl Iterator<Item = &'a HotScopeIntentV1>,
) -> Result<Vec<CensusDenominatorRef>, PolicyError> {
    let mut by_id = BTreeMap::new();
    for denominator in intents.flat_map(|intent| &intent.census_denominators) {
        if let Some(current) = by_id.insert(denominator.census_id.clone(), denominator.clone())
            && current != *denominator
        {
            return Err(PolicyError::Journal(
                "census identity was reused for changed denominator contents".into(),
            ));
        }
    }
    Ok(by_id.into_values().collect())
}

fn latest_target_record<'a>(
    records: &'a [HotScopeRecordV1],
    intent: &StableString,
    source: &StableString,
    operation: &StableString,
) -> Option<&'a HotScopeRecordV1> {
    latest_semantic_record(records, intent, source, operation)
}

pub(crate) fn all_latest_targets(records: &[HotScopeRecordV1]) -> Vec<&HotScopeRecordV1> {
    let intents = intent_map(records);
    let mut result = Vec::new();
    for intent in intents.values() {
        for request in &intent.requested_sources {
            if let Some(record) = latest_target_record(
                records,
                &intent.intent_id,
                &request.source_key,
                &request.operation_key,
            ) {
                result.push(record);
            }
        }
    }
    result.sort_by_key(|record| record.head().record_id.clone());
    result
}

fn latest_applied<'a>(
    records: &'a [HotScopeRecordV1],
    intent: &StableString,
    source: &StableString,
    operation: &StableString,
) -> Option<&'a crate::HotScopeAppliedV1> {
    records.iter().rev().find_map(|record| match record {
        HotScopeRecordV1::Applied(value)
            if &value.intent_id == intent
                && &value.source_key == source
                && &value.operation_key == operation =>
        {
            Some(value)
        }
        _ => None,
    })
}

pub(crate) fn target_needs_control(
    records: &[HotScopeRecordV1],
    target: &HotScopeRecordV1,
    generation: WireU64,
) -> Result<bool, PolicyError> {
    let Some((intent, source, operation, presence, _)) = semantic_target(target) else {
        return Err(PolicyError::InvalidValue(
            "control target is not desired/degraded/closed".into(),
        ));
    };
    let applied = latest_applied(records, intent, source, operation);
    if presence == ScopePresence::Absent {
        return Ok(applied.is_some_and(|value| {
            value.generation == generation && value.presence == ScopePresence::Active
        }));
    }
    Ok(applied.is_none_or(|value| {
        value.target_record_id != target.head().record_id
            || value.generation != generation
            || value.presence != presence
    }))
}

fn generated_head(
    prior: &[HotScopeRecordV1],
    generated: &[HotScopeRecordV1],
    contract: &str,
    decision_id: &StableString,
    recorded_at: UtcTimestamp,
) -> Result<PolicyRecordHead, PolicyError> {
    let base = prior.last().map_or(Ok(0), |record| {
        record
            .head()
            .record_ordinal
            .get()
            .checked_add(1)
            .ok_or(PolicyError::BudgetOverflow)
    })?;
    let ordinal = base
        .checked_add(u64::try_from(generated.len()).map_err(|_| PolicyError::BudgetOverflow)?)
        .ok_or(PolicyError::BudgetOverflow)?;
    let record_id = stable(format!("{}:{ordinal}", decision_id.as_str()))?;
    let predecessor_record_id = generated
        .last()
        .map(|record| record.head().record_id.clone())
        .or_else(|| prior.last().map(|record| record.head().record_id.clone()));
    Ok(PolicyRecordHead {
        contract: stable(contract)?,
        schema_version: WireU64::new(1),
        record_id,
        record_ordinal: WireU64::new(ordinal),
        recorded_at,
        predecessor_record_id,
    })
}

fn next_head_from(
    records: &[HotScopeRecordV1],
    contract: &str,
    record_id: StableString,
    recorded_at: UtcTimestamp,
) -> Result<PolicyRecordHead, PolicyError> {
    let ordinal = records.last().map_or(Ok(0), |record| {
        record
            .head()
            .record_ordinal
            .get()
            .checked_add(1)
            .ok_or(PolicyError::BudgetOverflow)
    })?;
    Ok(PolicyRecordHead {
        contract: stable(contract)?,
        schema_version: WireU64::new(1),
        record_id,
        record_ordinal: WireU64::new(ordinal),
        recorded_at,
        predecessor_record_id: records.last().map(|record| record.head().record_id.clone()),
    })
}

fn matches_desired(current: Option<&HotScopeRecordV1>, scope: &EffectiveScope) -> bool {
    matches!(current, Some(HotScopeRecordV1::Desired(value)) if value.scope == *scope)
}

fn matches_degraded(
    current: Option<&HotScopeRecordV1>,
    effective_scope: Option<&EffectiveScope>,
    changes: &[DegradationChange],
) -> bool {
    matches!(current, Some(HotScopeRecordV1::Degraded(value))
        if value.effective_scope.as_ref() == effective_scope && value.changes == changes)
}

fn matches_closed(current: Option<&HotScopeRecordV1>, reason: &StableString) -> bool {
    matches!(current, Some(HotScopeRecordV1::Closed(value)) if &value.reason == reason)
}

fn state_key(intent: &StableString, source: &StableString, operation: &StableString) -> String {
    format!(
        "{}|{}|{}",
        intent.as_str(),
        source.as_str(),
        operation.as_str()
    )
}

fn change(
    reason: DegradationReason,
    detail: &str,
    evidence: &[EvidenceLink],
) -> Result<DegradationChange, PolicyError> {
    Ok(DegradationChange {
        reason,
        detail: stable(detail)?,
        evidence: evidence.to_vec(),
    })
}

fn is_social(family: SourceFamily) -> bool {
    matches!(
        family,
        SourceFamily::PumpProductAuthenticated
            | SourceFamily::SocialProfile
            | SourceFamily::PublicMedia
    )
}

fn add_microseconds(start: UtcTimestamp, amount: WireU64) -> Result<UtcTimestamp, PolicyError> {
    let micros = i64::try_from(amount.get())
        .map_err(|_| PolicyError::InvalidValue("duration exceeds i64 microseconds".into()))?;
    let value = start
        .as_datetime()
        .checked_add(time::Duration::microseconds(micros))
        .ok_or_else(|| PolicyError::InvalidValue("timestamp addition overflowed".into()))?;
    UtcTimestamp::new(value).map_err(|error| PolicyError::InvalidValue(error.to_string()))
}

fn stable(value: impl Into<String>) -> Result<StableString, PolicyError> {
    StableString::new(value).map_err(|error| PolicyError::InvalidValue(error.to_string()))
}
