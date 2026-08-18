use crate::{
    ATTENTION_CONTRACT, AssertionStatus, AttentionDataset, AttentionEvent, AttentionEventKind,
    AttentionInterpretation, CohortCensoring, ContentState, CoverageContext, CoverageState,
    CreatorRelation, EventTime, EventTimeStatus, ExactAttentionInput, ExactInputKind,
    FollowEdgeState, KernelEventRow, KernelMarkFamily, MarkValue, PermissionModel,
    ResponseCensoring, SocialTransitionKind,
};
use joshi_domain::UtcTimestamp;
use std::collections::{HashMap, HashSet};
use thiserror::Error;

/// Stable category for an attention-contract validation failure.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ValidationCode {
    WrongContract,
    DuplicateIdentity,
    MissingReference,
    InvalidTime,
    InvalidCoverage,
    InvalidRevision,
    InvalidJoin,
    Leakage,
    InvalidFollowRemoval,
    InvalidKernel,
    InvalidResponse,
    InvalidCohort,
}

/// One fail-closed dataset validation error.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
#[error("{code:?} at {path}: {detail}")]
pub struct AttentionValidationError {
    pub code: ValidationCode,
    pub path: String,
    pub detail: String,
}

impl AttentionDataset {
    /// Validates source identity, bitemporal joins, coverage, and response-study boundaries.
    ///
    /// # Errors
    ///
    /// Returns the first deterministic failure. No inferred row is admitted on failure.
    #[allow(clippy::too_many_lines)] // One deterministic pass makes cross-table ordering explicit.
    pub fn validate(&self) -> Result<(), AttentionValidationError> {
        if self.contract.as_str() != ATTENTION_CONTRACT {
            return fail(
                ValidationCode::WrongContract,
                "contract",
                "unsupported attention contract",
            );
        }

        unique(
            self.exact_inputs.iter().map(|row| row.input_id.as_str()),
            "exact_inputs.input_id",
        )?;
        unique(
            self.identity_versions
                .iter()
                .map(|row| row.identity_version_id.as_str()),
            "identity_versions.identity_version_id",
        )?;
        unique(
            self.follow_edge_versions
                .iter()
                .map(|row| row.assertion_id.as_str()),
            "follow_edge_versions.assertion_id",
        )?;
        unique(
            self.territory_snapshots
                .iter()
                .map(|row| row.territory_snapshot_id.as_str()),
            "territory_snapshots.territory_snapshot_id",
        )?;
        unique(
            self.selected_cluster_contexts
                .iter()
                .map(|row| row.cluster_context_id.as_str()),
            "selected_cluster_contexts.cluster_context_id",
        )?;
        unique(
            self.selected_cluster_contexts
                .iter()
                .map(|row| row.selected_for_attention_event_id.as_str()),
            "selected_cluster_contexts.selected_for_attention_event_id",
        )?;
        unique(
            self.attention_events
                .iter()
                .map(|row| row.attention_event_id.as_str()),
            "attention_events.attention_event_id",
        )?;
        unique(
            self.kernel_events
                .iter()
                .map(|row| row.kernel_event_id.as_str()),
            "kernel_events.kernel_event_id",
        )?;
        unique(
            self.audience_overlap_estimates
                .iter()
                .map(|row| row.estimate_id.as_str()),
            "audience_overlap_estimates.estimate_id",
        )?;
        unique(
            self.cohort_rows
                .iter()
                .map(|row| row.cohort_row_id.as_str()),
            "cohort_rows.cohort_row_id",
        )?;

        let inputs: HashMap<_, _> = self
            .exact_inputs
            .iter()
            .map(|row| (row.input_id.as_str(), row))
            .collect();
        let identities: HashMap<_, _> = self
            .identity_versions
            .iter()
            .map(|row| (row.identity_version_id.as_str(), row))
            .collect();
        let territories: HashMap<_, _> = self
            .territory_snapshots
            .iter()
            .map(|row| (row.territory_snapshot_id.as_str(), row))
            .collect();
        let cluster_contexts: HashMap<_, _> = self
            .selected_cluster_contexts
            .iter()
            .map(|row| (row.cluster_context_id.as_str(), row))
            .collect();
        let attention_events: HashMap<_, _> = self
            .attention_events
            .iter()
            .map(|row| (row.attention_event_id.as_str(), row))
            .collect();
        let kernel_events: HashMap<_, _> = self
            .kernel_events
            .iter()
            .map(|row| (row.kernel_event_id.as_str(), row))
            .collect();

        for (index, input) in self.exact_inputs.iter().enumerate() {
            validate_event_time(
                &input.event_time,
                &format!("exact_inputs[{index}].event_time"),
            )?;
            validate_coverage(
                &input.evidence.coverage,
                &format!("exact_inputs[{index}].evidence.coverage"),
            )?;
            if input.evidence.available_at < input.evidence.observed_at {
                return fail(
                    ValidationCode::InvalidTime,
                    &format!("exact_inputs[{index}].evidence.available_at"),
                    "availability precedes observation",
                );
            }
            validate_nested_input_times(input, index)?;
        }
        validate_revision_chains(&self.exact_inputs)?;

        for (index, version) in self.identity_versions.iter().enumerate() {
            validate_intervals(
                version.valid_time.lower,
                version.valid_time.upper,
                version.knowledge_time.known_from,
                version.knowledge_time.known_until,
                &format!("identity_versions[{index}]"),
            )?;
            require_input_refs(
                &version.evidence_input_ids,
                &inputs,
                &format!("identity_versions[{index}].evidence_input_ids"),
            )?;
            for link in &version.wallet_links {
                require_input_refs(
                    &link.evidence_input_ids,
                    &inputs,
                    &format!("identity_versions[{index}].wallet_links.evidence_input_ids"),
                )?;
            }
            if let Some(supersedes) = &version.supersedes
                && !identities.contains_key(supersedes.as_str())
            {
                return missing(
                    &format!("identity_versions[{index}].supersedes"),
                    supersedes.as_str(),
                );
            }
            for conflict in &version.conflicts_with {
                if !identities.contains_key(conflict.as_str()) {
                    return missing(
                        &format!("identity_versions[{index}].conflicts_with"),
                        conflict.as_str(),
                    );
                }
            }
        }
        validate_identity_series(&self.identity_versions)?;

        for (index, edge) in self.follow_edge_versions.iter().enumerate() {
            validate_intervals(
                edge.valid_time.lower,
                edge.valid_time.upper,
                edge.knowledge_time.known_from,
                edge.knowledge_time.known_until,
                &format!("follow_edge_versions[{index}]"),
            )?;
            require_input_refs(
                &edge.source_snapshot_input_ids,
                &inputs,
                &format!("follow_edge_versions[{index}].source_snapshot_input_ids"),
            )?;
            let mut presence_snapshot_id = None;
            if let Some(presence_id) = &edge.presence_member_input_id {
                let presence = inputs.get(presence_id.as_str()).ok_or_else(|| {
                    missing_error(
                        &format!("follow_edge_versions[{index}].presence_member_input_id"),
                        presence_id.as_str(),
                    )
                })?;
                let ExactInputKind::FollowSnapshotMember(member) = &presence.kind else {
                    return fail(
                        ValidationCode::InvalidFollowRemoval,
                        &format!("follow_edge_versions[{index}].presence_member_input_id"),
                        "presence evidence must be a follow snapshot member occurrence",
                    );
                };
                if member.root_subject_id != edge.root_subject_id
                    || member.member_subject_id != edge.member_subject_id
                    || member.direction != edge.direction
                {
                    return fail(
                        ValidationCode::InvalidFollowRemoval,
                        &format!("follow_edge_versions[{index}].presence_member_input_id"),
                        "presence member does not match the asserted follow edge",
                    );
                }
                presence_snapshot_id = Some(member.snapshot_id.as_str());
            }
            let mut snapshots = Vec::new();
            for input_id in &edge.source_snapshot_input_ids {
                let input = inputs
                    .get(input_id.as_str())
                    .unwrap_or_else(|| unreachable!("checked above"));
                let ExactInputKind::FollowSnapshotObserved(snapshot) = &input.kind else {
                    return fail(
                        ValidationCode::InvalidFollowRemoval,
                        &format!("follow_edge_versions[{index}].source_snapshot_input_ids"),
                        "follow-edge presence/removal evidence must be snapshot boundary records",
                    );
                };
                snapshots.push((*input, snapshot));
            }
            snapshots.sort_by_key(|(input, _)| input.evidence.observed_at);
            if edge.state == FollowEdgeState::Removed
                && (!edge.comparable_scope
                    || !edge.intervening_gap_ids.is_empty()
                    || edge.source_snapshot_input_ids.len() < 2)
            {
                return fail(
                    ValidationCode::InvalidFollowRemoval,
                    &format!("follow_edge_versions[{index}]"),
                    "removed requires two comparable snapshots with no intervening coverage gap",
                );
            }
            if matches!(
                edge.state,
                FollowEdgeState::Present | FollowEdgeState::Removed
            ) && edge.presence_member_input_id.is_none()
            {
                return fail(
                    ValidationCode::InvalidFollowRemoval,
                    &format!("follow_edge_versions[{index}].presence_member_input_id"),
                    "present/removed edges require an exact observed membership occurrence",
                );
            }
            if edge.state == FollowEdgeState::Removed
                && snapshots.iter().any(|(input, snapshot)| {
                    snapshot.root_subject_id != edge.root_subject_id
                        || snapshot.direction != edge.direction
                        || !snapshot.pagination_complete
                        || input.evidence.coverage.state != CoverageState::Complete
                })
            {
                return fail(
                    ValidationCode::InvalidFollowRemoval,
                    &format!("follow_edge_versions[{index}]"),
                    "removal snapshots must cover the same root/direction completely",
                );
            }
            if edge.state == FollowEdgeState::Removed
                && (snapshots.first().is_none_or(|(_, snapshot)| {
                    Some(snapshot.snapshot_id.as_str()) != presence_snapshot_id
                }) || snapshots
                    .first()
                    .map(|(_, snapshot)| snapshot.snapshot_id.as_str())
                    == snapshots
                        .last()
                        .map(|(_, snapshot)| snapshot.snapshot_id.as_str()))
            {
                return fail(
                    ValidationCode::InvalidFollowRemoval,
                    &format!("follow_edge_versions[{index}]"),
                    "removal needs an earlier observed member and a later distinct complete snapshot",
                );
            }
        }

        for (index, territory) in self.territory_snapshots.iter().enumerate() {
            validate_intervals(
                territory.valid_time.lower,
                territory.valid_time.upper,
                territory.knowledge_time.known_from,
                territory.knowledge_time.known_until,
                &format!("territory_snapshots[{index}]"),
            )?;
            require_input_refs(
                &territory.evidence_input_ids,
                &inputs,
                &format!("territory_snapshots[{index}].evidence_input_ids"),
            )?;
            if let Some(identity_id) = &territory.leader_identity_version_id
                && !identities.contains_key(identity_id.as_str())
            {
                return missing(
                    &format!("territory_snapshots[{index}].leader_identity_version_id"),
                    identity_id.as_str(),
                );
            }
            if let Some(supersedes) = &territory.supersedes
                && !territories.contains_key(supersedes.as_str())
            {
                return missing(
                    &format!("territory_snapshots[{index}].supersedes"),
                    supersedes.as_str(),
                );
            }
            for competitor in &territory.competing_snapshot_ids {
                if !territories.contains_key(competitor.as_str()) {
                    return missing(
                        &format!("territory_snapshots[{index}].competing_snapshot_ids"),
                        competitor.as_str(),
                    );
                }
            }
        }
        validate_territory_series(&self.territory_snapshots)?;

        for (index, cluster) in self.selected_cluster_contexts.iter().enumerate() {
            validate_plain_interval(
                cluster.valid_time.lower,
                cluster.valid_time.upper,
                &format!("selected_cluster_contexts[{index}].valid_time"),
            )?;
            validate_event_time(
                &cluster.selected_for_event_time,
                &format!("selected_cluster_contexts[{index}].selected_for_event_time"),
            )?;
            require_input_refs(
                &cluster.evidence_input_ids,
                &inputs,
                &format!("selected_cluster_contexts[{index}].evidence_input_ids"),
            )?;
            let Some(bound_event) =
                attention_events.get(cluster.selected_for_attention_event_id.as_str())
            else {
                return missing(
                    &format!("selected_cluster_contexts[{index}].selected_for_attention_event_id"),
                    cluster.selected_for_attention_event_id.as_str(),
                );
            };
            if bound_event.caller_cluster_context_id.as_ref() != Some(&cluster.cluster_context_id) {
                return fail(
                    ValidationCode::InvalidJoin,
                    &format!("selected_cluster_contexts[{index}].cluster_context_id"),
                    "selected context must be the event's one referenced caller cluster context",
                );
            }
            if cluster.source_available_at > cluster.selected_as_of
                || cluster.source_available_commit > cluster.selected_as_of_commit
            {
                return fail(
                    ValidationCode::Leakage,
                    &format!("selected_cluster_contexts[{index}]"),
                    "cluster artifact became available after its selection cut",
                );
            }
            if cluster.member_wallet_ids.is_empty() {
                return fail(
                    ValidationCode::InvalidJoin,
                    &format!("selected_cluster_contexts[{index}].member_wallet_ids"),
                    "selected cluster projection must name at least one wallet",
                );
            }
            if let Some(slots) = &cluster.valid_slots
                && slots.upper.is_some_and(|upper| upper <= slots.lower)
            {
                return fail(
                    ValidationCode::InvalidTime,
                    &format!("selected_cluster_contexts[{index}].valid_slots"),
                    "half-open slot interval upper bound must follow lower bound",
                );
            }
            if cluster.valid_slots.is_none() || cluster.selected_for_chain_slot.is_none() {
                return fail(
                    ValidationCode::InvalidJoin,
                    &format!("selected_cluster_contexts[{index}]"),
                    "selected cluster context requires explicit slot validity and selected slot",
                );
            }
            if cluster
                .confidence_ppm
                .is_some_and(|value| value.get() > 1_000_000)
            {
                return fail(
                    ValidationCode::InvalidJoin,
                    &format!("selected_cluster_contexts[{index}].confidence_ppm"),
                    "confidence_ppm exceeds one million",
                );
            }
        }

        for (index, event) in self.attention_events.iter().enumerate() {
            validate_attention_event(
                event,
                index,
                &inputs,
                &identities,
                &territories,
                &cluster_contexts,
            )?;
        }

        for (index, kernel) in self.kernel_events.iter().enumerate() {
            validate_kernel_event(kernel, index, &attention_events)?;
        }
        if self.kernel_events.len() != self.attention_events.len() {
            return fail(
                ValidationCode::InvalidKernel,
                "kernel_events",
                "exactly one kernel event row is required for each attention event",
            );
        }

        validate_marks(self, &kernel_events, &inputs)?;
        validate_overlaps(self)?;
        validate_responses(self, &kernel_events, &inputs)?;
        validate_cohorts(self, &kernel_events, &inputs)?;
        Ok(())
    }
}

fn validate_nested_input_times(
    input: &ExactAttentionInput,
    index: usize,
) -> Result<(), AttentionValidationError> {
    match &input.kind {
        ExactInputKind::CalloutObserved(row) => {
            if matches!(
                row.content_state,
                ContentState::Deleted | ContentState::Tombstone
            ) && row.supersedes_revision_id.is_none()
            {
                return fail(
                    ValidationCode::InvalidRevision,
                    &format!("exact_inputs[{index}].payload.supersedes_revision_id"),
                    "callout deletion/tombstone must supersede a retained prior revision",
                );
            }
            for outcome in &row.retrospective_outcomes {
                if outcome.available_at < outcome.as_of {
                    return fail(
                        ValidationCode::InvalidTime,
                        &format!("exact_inputs[{index}].payload.retrospective_outcomes"),
                        "retrospective field availability precedes its as-of time",
                    );
                }
            }
        }
        ExactInputKind::FollowSnapshotMember(row) => validate_event_time(
            &row.provider_follow_time,
            &format!("exact_inputs[{index}].payload.provider_follow_time"),
        )?,
        ExactInputKind::CommunitySnapshotObserved(row) => validate_event_time(
            &row.provider_updated_at,
            &format!("exact_inputs[{index}].payload.provider_updated_at"),
        )?,
        ExactInputKind::CreatorRelationObserved(row)
            if row.relation == CreatorRelation::OrdinaryFeeSweep
                && row.permission_model != PermissionModel::Permissionless =>
        {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("exact_inputs[{index}].payload.permission_model"),
                "ordinary creator-fee sweeps must retain their permissionless predicate",
            );
        }
        ExactInputKind::SocialTransitionObserved(row)
            if row.transition == SocialTransitionKind::SocialFeeClaim
                && (row.authority != PermissionModel::PlatformAuthorized
                    || row.mint_id.is_some()) =>
        {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("exact_inputs[{index}].payload"),
                "a raw social-fee claim is platform-authorized and mintless; coin attribution is derived separately",
            );
        }
        ExactInputKind::SocialContentObserved(row)
            if matches!(row.state, ContentState::Deleted | ContentState::Tombstone)
                && row.supersedes_revision_id.is_none() =>
        {
            return fail(
                ValidationCode::InvalidRevision,
                &format!("exact_inputs[{index}].payload.supersedes_revision_id"),
                "deletion/tombstone must supersede a retained prior revision",
            );
        }
        _ => {}
    }
    Ok(())
}

fn validate_revision_chains(
    inputs: &[ExactAttentionInput],
) -> Result<(), AttentionValidationError> {
    let mut revisions: HashMap<&str, (&str, Option<&str>, &ExactAttentionInput)> = HashMap::new();
    for (index, input) in inputs.iter().enumerate() {
        let revision = match &input.kind {
            ExactInputKind::CalloutObserved(row) => Some((
                row.revision_id.as_str(),
                row.provider_callout_id.as_str(),
                row.supersedes_revision_id
                    .as_ref()
                    .map(crate::RevisionId::as_str),
            )),
            ExactInputKind::SocialContentObserved(row) => Some((
                row.revision_id.as_str(),
                row.provider_object_id.as_str(),
                row.supersedes_revision_id
                    .as_ref()
                    .map(crate::RevisionId::as_str),
            )),
            _ => None,
        };
        if let Some((revision_id, object_id, supersedes)) = revision
            && revisions
                .insert(revision_id, (object_id, supersedes, input))
                .is_some()
        {
            return fail(
                ValidationCode::DuplicateIdentity,
                &format!("exact_inputs[{index}].payload.revision_id"),
                "revision identity is not occurrence-unique",
            );
        }
    }
    for (revision, (object, supersedes, input)) in &revisions {
        if let Some(parent) = supersedes {
            let Some((parent_object, _, parent_input)) = revisions.get(parent) else {
                return missing("exact_inputs.payload.supersedes_revision_id", parent);
            };
            if parent == revision || parent_object != object {
                return fail(
                    ValidationCode::InvalidRevision,
                    "exact_inputs.payload.supersedes_revision_id",
                    "revision may supersede only an earlier revision of the same provider object",
                );
            }
            if parent_input.evidence.available_at > input.evidence.available_at
                || parent_input.evidence.available_commit > input.evidence.available_commit
            {
                return fail(
                    ValidationCode::InvalidRevision,
                    "exact_inputs.payload.supersedes_revision_id",
                    "a revision cannot supersede evidence that was not yet available",
                );
            }
            let mut seen = HashSet::new();
            let mut cursor = Some(*parent);
            while let Some(value) = cursor {
                if !seen.insert(value) || value == *revision {
                    return fail(
                        ValidationCode::InvalidRevision,
                        "exact_inputs.payload.supersedes_revision_id",
                        "revision chain contains a cycle",
                    );
                }
                cursor = revisions.get(value).and_then(|(_, next, _)| *next);
            }
        }
    }
    Ok(())
}

fn validate_identity_series(
    versions: &[crate::IdentityVersion],
) -> Result<(), AttentionValidationError> {
    let mut groups: HashMap<&str, Vec<&crate::IdentityVersion>> = HashMap::new();
    for version in versions {
        groups
            .entry(version.identity_series_id.as_str())
            .or_default()
            .push(version);
    }
    for (series, rows) in &mut groups {
        rows.sort_by_key(|row| row.knowledge_time.known_from);
        if rows.first().is_some_and(|row| row.supersedes.is_some()) {
            return fail(
                ValidationCode::InvalidRevision,
                "identity_versions.supersedes",
                &format!("identity series {series} has no root version"),
            );
        }
        for pair in rows.windows(2) {
            let previous = pair[0];
            let current = pair[1];
            if current.subject_id != previous.subject_id
                || current.supersedes.as_ref() != Some(&previous.identity_version_id)
                || previous.knowledge_time.known_until != Some(current.knowledge_time.known_from)
            {
                return fail(
                    ValidationCode::InvalidRevision,
                    "identity_versions",
                    &format!(
                        "identity series {series} must be one same-subject, temporally closed supersession chain"
                    ),
                );
            }
        }
    }
    Ok(())
}

fn validate_territory_series(
    versions: &[crate::TerritorySnapshot],
) -> Result<(), AttentionValidationError> {
    let mut groups: HashMap<&str, Vec<&crate::TerritorySnapshot>> = HashMap::new();
    for version in versions {
        groups
            .entry(version.territory_series_id.as_str())
            .or_default()
            .push(version);
    }
    for (series, rows) in &mut groups {
        rows.sort_by_key(|row| row.knowledge_time.known_from);
        if rows.first().is_some_and(|row| row.supersedes.is_some()) {
            return fail(
                ValidationCode::InvalidRevision,
                "territory_snapshots.supersedes",
                &format!("territory series {series} has no root version"),
            );
        }
        for pair in rows.windows(2) {
            let previous = pair[0];
            let current = pair[1];
            if current.mint_id != previous.mint_id
                || current.supersedes.as_ref() != Some(&previous.territory_snapshot_id)
                || previous.knowledge_time.known_until != Some(current.knowledge_time.known_from)
            {
                return fail(
                    ValidationCode::InvalidRevision,
                    "territory_snapshots",
                    &format!(
                        "territory series {series} must be one same-mint, temporally closed supersession chain"
                    ),
                );
            }
        }
    }
    Ok(())
}

#[allow(clippy::too_many_lines)] // Every point-in-time join is deliberately checked at one boundary.
fn validate_attention_event<'a>(
    event: &AttentionEvent,
    index: usize,
    inputs: &HashMap<&'a str, &'a ExactAttentionInput>,
    identities: &HashMap<&str, &crate::IdentityVersion>,
    territories: &HashMap<&str, &crate::TerritorySnapshot>,
    clusters: &HashMap<&str, &crate::SelectedClusterContext>,
) -> Result<(), AttentionValidationError> {
    validate_event_time(
        &event.event_time,
        &format!("attention_events[{index}].event_time"),
    )?;
    validate_coverage(
        &event.coverage,
        &format!("attention_events[{index}].coverage"),
    )?;
    if event.interpretation != AttentionInterpretation::MarkedForcingEventNoCausalClaim {
        return fail(
            ValidationCode::InvalidKernel,
            &format!("attention_events[{index}].interpretation"),
            "attention events must explicitly disclaim a causal interpretation",
        );
    }
    if event.available_at < event.observed_at {
        return fail(
            ValidationCode::InvalidTime,
            &format!("attention_events[{index}].available_at"),
            "event availability precedes observation",
        );
    }
    let source =
        inputs
            .get(event.forcing_input_id.as_str())
            .ok_or_else(|| AttentionValidationError {
                code: ValidationCode::MissingReference,
                path: format!("attention_events[{index}].forcing_input_id"),
                detail: format!("missing {}", event.forcing_input_id),
            })?;
    if event.event_time != source.event_time || event.observed_at != source.evidence.observed_at {
        return fail(
            ValidationCode::InvalidJoin,
            &format!("attention_events[{index}]"),
            "attention anchor time and observation time must exactly match the forcing input occurrence",
        );
    }
    if !event_kind_matches_source(event.event_kind, &source.kind) {
        return fail(
            ValidationCode::InvalidJoin,
            &format!("attention_events[{index}].event_kind"),
            "forcing input family does not match the attention event family",
        );
    }
    if source.evidence.available_at > event.available_at
        || source.evidence.available_commit > event.available_commit
    {
        return fail(
            ValidationCode::Leakage,
            &format!("attention_events[{index}].forcing_input_id"),
            "forcing evidence was not available at the event cutoff",
        );
    }
    if let Some(source_mint) = input_mint(source)
        && source_mint != &event.mint_id
    {
        return fail(
            ValidationCode::InvalidJoin,
            &format!("attention_events[{index}].mint_id"),
            "event mint differs from forcing input mint",
        );
    }
    match &source.kind {
        ExactInputKind::CalloutObserved(callout)
            if event.direction != Some(callout.direction)
                || event.amount_atoms != callout.amount_atoms
                || event.amount_asset_id != callout.amount_asset_id =>
        {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}]"),
                "callout direction/amount must exactly match the forcing source occurrence",
            );
        }
        ExactInputKind::CalloutObserved(_) => {}
        _ if event.direction.is_some()
            || event.amount_atoms.is_some()
            || event.amount_asset_id.is_some() =>
        {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}]"),
                "callout direction/amount fields are invalid for this event family",
            );
        }
        _ => {}
    }
    let effective = event.event_time.lower;
    if let Some(identity_id) = &event.caller_identity_version_id {
        let identity = identities.get(identity_id.as_str()).ok_or_else(|| {
            missing_error(
                &format!("attention_events[{index}].caller_identity_version_id"),
                identity_id.as_str(),
            )
        })?;
        require_assertion_as_of(
            identity.status,
            identity.valid_time.lower,
            identity.valid_time.upper,
            identity.knowledge_time.known_from,
            identity.knowledge_time.known_until,
            effective,
            event.available_at,
            &format!("attention_events[{index}].caller_identity_version_id"),
        )?;
        if identities.values().any(|candidate| {
            candidate.identity_series_id == identity.identity_series_id
                && candidate.knowledge_time.known_from > identity.knowledge_time.known_from
                && candidate.knowledge_time.known_from <= event.available_at
                && effective.is_some_and(|time| {
                    contains(candidate.valid_time.lower, candidate.valid_time.upper, time)
                })
        }) {
            return fail(
                ValidationCode::Leakage,
                &format!("attention_events[{index}].caller_identity_version_id"),
                "selected identity is not the latest effective version known at the event cutoff",
            );
        }
        if let Some(wallet) = &event.caller_wallet_id
            && !identity
                .wallet_links
                .iter()
                .any(|link| &link.wallet_id == wallet)
        {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}].caller_wallet_id"),
                "caller wallet is not supported by the selected identity version",
            );
        }
    }
    if let Some(territory_id) = &event.territory_snapshot_id {
        let territory = territories.get(territory_id.as_str()).ok_or_else(|| {
            missing_error(
                &format!("attention_events[{index}].territory_snapshot_id"),
                territory_id.as_str(),
            )
        })?;
        require_assertion_as_of(
            territory.status,
            territory.valid_time.lower,
            territory.valid_time.upper,
            territory.knowledge_time.known_from,
            territory.knowledge_time.known_until,
            effective,
            event.available_at,
            &format!("attention_events[{index}].territory_snapshot_id"),
        )?;
        if territories.values().any(|candidate| {
            candidate.territory_series_id == territory.territory_series_id
                && candidate.knowledge_time.known_from > territory.knowledge_time.known_from
                && candidate.knowledge_time.known_from <= event.available_at
                && effective.is_some_and(|time| {
                    contains(candidate.valid_time.lower, candidate.valid_time.upper, time)
                })
        }) {
            return fail(
                ValidationCode::Leakage,
                &format!("attention_events[{index}].territory_snapshot_id"),
                "selected territory is not the latest effective version known at the event cutoff",
            );
        }
        if territory.mint_id != event.mint_id {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}].territory_snapshot_id"),
                "territory snapshot belongs to another mint",
            );
        }
    }
    if let Some(cluster_id) = &event.caller_cluster_context_id {
        let cluster = clusters.get(cluster_id.as_str()).ok_or_else(|| {
            missing_error(
                &format!("attention_events[{index}].caller_cluster_context_id"),
                cluster_id.as_str(),
            )
        })?;
        let Some(event_time) = effective else {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}].caller_cluster_context_id"),
                "a cluster join requires a known event-time lower bound",
            );
        };
        if cluster.source_status == AssertionStatus::Retracted
            || cluster.source_available_at > event.available_at
            || cluster.source_available_commit > event.available_commit
            || !contains(
                cluster.valid_time.lower,
                cluster.valid_time.upper,
                event_time,
            )
        {
            return fail(
                ValidationCode::Leakage,
                &format!("attention_events[{index}].caller_cluster_context_id"),
                "cluster hypothesis was not valid and available at the event cutoff",
            );
        }
        if cluster.selected_for_attention_event_id != event.attention_event_id
            || cluster.selected_for_event_time != event.event_time
            || cluster.selected_for_chain_slot != event.chain_slot
            || cluster.selected_as_of != event.available_at
            || cluster.selected_as_of_commit != event.available_commit
        {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}].caller_cluster_context_id"),
                "selected cluster context is not bound to this exact event/time/slot/availability cut",
            );
        }
        let Some(slots) = &cluster.valid_slots else {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}].caller_cluster_context_id"),
                "an active cluster join requires an explicit slot-validity interval",
            );
        };
        {
            let Some(event_slot) = event.chain_slot else {
                return fail(
                    ValidationCode::InvalidJoin,
                    &format!("attention_events[{index}].chain_slot"),
                    "a slot-valid cluster join requires the event chain slot",
                );
            };
            if event_slot < slots.lower || slots.upper.is_some_and(|upper| event_slot >= upper) {
                return fail(
                    ValidationCode::Leakage,
                    &format!("attention_events[{index}].caller_cluster_context_id"),
                    "cluster hypothesis was not slot-valid at the event",
                );
            }
        }
        if let Some(wallet) = &event.caller_wallet_id
            && !cluster.member_wallet_ids.contains(wallet)
        {
            return fail(
                ValidationCode::InvalidJoin,
                &format!("attention_events[{index}].caller_cluster_context_id"),
                "caller wallet is not a member of the selected cluster hypothesis",
            );
        }
    }
    if let Some(context) = &event.presentation_context
        && (event.scene_id.as_ref() != Some(&context.scene_id)
            || context.observed_at > event.available_at)
    {
        return fail(
            ValidationCode::InvalidJoin,
            &format!("attention_events[{index}].presentation_context"),
            "presentation must bind the same scene and be observed by the event cutoff",
        );
    }
    if event.choice_set_id.is_some() && event.presentation_context.is_none() {
        return fail(
            ValidationCode::InvalidJoin,
            &format!("attention_events[{index}].choice_set_id"),
            "a witnessed choice set requires a presentation/view/session binding",
        );
    }
    Ok(())
}

fn validate_kernel_event(
    kernel: &KernelEventRow,
    index: usize,
    events: &HashMap<&str, &AttentionEvent>,
) -> Result<(), AttentionValidationError> {
    let event = events
        .get(kernel.attention_event_id.as_str())
        .ok_or_else(|| {
            missing_error(
                &format!("kernel_events[{index}].attention_event_id"),
                kernel.attention_event_id.as_str(),
            )
        })?;
    validate_event_time(
        &kernel.event_time,
        &format!("kernel_events[{index}].event_time"),
    )?;
    validate_coverage(
        &kernel.coverage,
        &format!("kernel_events[{index}].coverage"),
    )?;
    if kernel.mint_id != event.mint_id
        || kernel.event_kind != event.event_kind
        || kernel.event_time != event.event_time
        || kernel.event_available_at != event.available_at
        || kernel.event_available_commit != event.available_commit
        || kernel.caller_identity_version_id != event.caller_identity_version_id
        || kernel.caller_wallet_id != event.caller_wallet_id
        || kernel.caller_cluster_context_id != event.caller_cluster_context_id
        || kernel.direction != event.direction
        || kernel.amount_atoms != event.amount_atoms
        || kernel.amount_asset_id != event.amount_asset_id
        || kernel.venue_id != event.venue_id
        || kernel.chain_slot != event.chain_slot
        || kernel.territory_snapshot_id != event.territory_snapshot_id
        || kernel.community_id != event.community_id
        || kernel.lifecycle_id != event.lifecycle_id
        || kernel.regime_epoch != event.regime_epoch
        || kernel.topology_epoch != event.topology_epoch
        || kernel.scene_id != event.scene_id
        || kernel.presentation_context != event.presentation_context
        || kernel.decision_id != event.decision_id
        || kernel.choice_set_id != event.choice_set_id
    {
        return fail(
            ValidationCode::InvalidKernel,
            &format!("kernel_events[{index}]"),
            "kernel event does not faithfully index its attention event",
        );
    }
    if kernel.fit_eligible_from < kernel.event_available_at {
        return fail(
            ValidationCode::Leakage,
            &format!("kernel_events[{index}].fit_eligible_from"),
            "event cannot be fit-eligible before its evidence is available",
        );
    }
    Ok(())
}

#[allow(clippy::too_many_lines)] // Mark leakage, provenance, and family closure are one admission rule.
fn validate_marks(
    dataset: &AttentionDataset,
    kernel_events: &HashMap<&str, &KernelEventRow>,
    inputs: &HashMap<&str, &ExactAttentionInput>,
) -> Result<(), AttentionValidationError> {
    let mut families: HashMap<&str, HashSet<KernelMarkFamily>> = HashMap::new();
    let mut keys = HashSet::new();
    for (index, mark) in dataset.kernel_marks.iter().enumerate() {
        let Some(event) = kernel_events.get(mark.kernel_event_id.as_str()) else {
            return missing(
                &format!("kernel_marks[{index}].kernel_event_id"),
                mark.kernel_event_id.as_str(),
            );
        };
        validate_coverage(&mark.coverage, &format!("kernel_marks[{index}].coverage"))?;
        let key = (
            mark.kernel_event_id.as_str(),
            mark.family,
            mark.name.as_str(),
        );
        if !keys.insert(key) {
            return fail(
                ValidationCode::DuplicateIdentity,
                &format!("kernel_marks[{index}]"),
                "kernel event/family/name must be unique",
            );
        }
        if mark.available_at > event.event_available_at
            || mark.available_commit > event.event_available_commit
            || mark.observed_through > event.event_available_at
            || mark.through_cut > event.event_available_at
        {
            return fail(
                ValidationCode::Leakage,
                &format!("kernel_marks[{index}]"),
                "mark crosses the event availability cutoff",
            );
        }
        if mark.family == KernelMarkFamily::Presentation
            && (event.presentation_context.is_none()
                || !matches!(
                    mark.epistemic_class,
                    crate::EpistemicClass::ProviderPresentation
                        | crate::EpistemicClass::OperatorAnnotation
                ))
        {
            return fail(
                ValidationCode::InvalidKernel,
                &format!("kernel_marks[{index}]"),
                "presentation marks require a bound witnessed view and presentation epistemic class",
            );
        }
        let lower_name = mark.name.as_str().to_ascii_lowercase();
        if [
            "multiple",
            "peak",
            "max_price",
            "max_multiplier",
            "future_return",
        ]
        .iter()
        .any(|needle| lower_name.contains(needle))
        {
            return fail(
                ValidationCode::Leakage,
                &format!("kernel_marks[{index}].name"),
                "retrospective provider outcome cannot be an anchor-time mark",
            );
        }
        if matches!(mark.value, MarkValue::Unknown(_)) != mark.missingness_reason.is_some() {
            return fail(
                ValidationCode::InvalidKernel,
                &format!("kernel_marks[{index}].missingness_reason"),
                "unknown marks require a reason and observed marks must not carry one",
            );
        }
        require_input_refs(
            &mark.source_input_ids,
            inputs,
            &format!("kernel_marks[{index}].source_input_ids"),
        )?;
        if mark.source_input_ids.iter().any(|id| {
            inputs
                .get(id.as_str())
                .is_some_and(|input| input.evidence.available_at > mark.available_at)
        }) {
            return fail(
                ValidationCode::Leakage,
                &format!("kernel_marks[{index}].source_input_ids"),
                "mark source was unavailable when the mark became available",
            );
        }
        families
            .entry(mark.kernel_event_id.as_str())
            .or_default()
            .insert(mark.family);
    }
    for event in &dataset.kernel_events {
        if event.event_kind == AttentionEventKind::Callout {
            let have = families.get(event.kernel_event_id.as_str());
            for required in [
                KernelMarkFamily::CallerHistory,
                KernelMarkFamily::Context,
                KernelMarkFamily::Territory,
                KernelMarkFamily::Lifecycle,
                KernelMarkFamily::AudienceOverlap,
            ] {
                if !have.is_some_and(|set| set.contains(&required)) {
                    return fail(
                        ValidationCode::InvalidKernel,
                        "kernel_marks",
                        "each callout needs an observed or explicitly missing row for every required mark family",
                    );
                }
            }
        }
    }
    Ok(())
}

fn validate_overlaps(dataset: &AttentionDataset) -> Result<(), AttentionValidationError> {
    for (index, overlap) in dataset.audience_overlap_estimates.iter().enumerate() {
        validate_coverage(
            &overlap.left_coverage,
            &format!("audience_overlap_estimates[{index}].left_coverage"),
        )?;
        validate_coverage(
            &overlap.right_coverage,
            &format!("audience_overlap_estimates[{index}].right_coverage"),
        )?;
        if overlap.intersection_count > overlap.left_denominator
            || overlap.intersection_count > overlap.right_denominator
        {
            return fail(
                ValidationCode::InvalidKernel,
                &format!("audience_overlap_estimates[{index}]"),
                "intersection exceeds an observed denominator",
            );
        }
        if overlap.available_at < overlap.observed_through {
            return fail(
                ValidationCode::InvalidTime,
                &format!("audience_overlap_estimates[{index}].available_at"),
                "overlap availability precedes its observation cutoff",
            );
        }
    }
    Ok(())
}

fn validate_responses(
    dataset: &AttentionDataset,
    kernels: &HashMap<&str, &KernelEventRow>,
    inputs: &HashMap<&str, &ExactAttentionInput>,
) -> Result<(), AttentionValidationError> {
    let mut keys = HashSet::new();
    for (index, response) in dataset.response_observations.iter().enumerate() {
        let Some(kernel) = kernels.get(response.kernel_event_id.as_str()) else {
            return missing(
                &format!("response_observations[{index}].kernel_event_id"),
                response.kernel_event_id.as_str(),
            );
        };
        if response.subject_mint_id != kernel.mint_id {
            return fail(
                ValidationCode::InvalidResponse,
                &format!("response_observations[{index}].subject_mint_id"),
                "response subject differs from kernel event mint",
            );
        }
        if response.window_start_seconds >= response.window_end_seconds {
            return fail(
                ValidationCode::InvalidResponse,
                &format!("response_observations[{index}]"),
                "response window must have positive width",
            );
        }
        let key = (
            response.kernel_event_id.as_str(),
            response.response_name.as_str(),
            response.window_start_seconds,
            response.window_end_seconds,
        );
        if !keys.insert(key) {
            return fail(
                ValidationCode::DuplicateIdentity,
                &format!("response_observations[{index}]"),
                "response event/name/window must be unique",
            );
        }
        validate_event_time(
            &response.event_time,
            &format!("response_observations[{index}].event_time"),
        )?;
        validate_coverage(
            &response.coverage,
            &format!("response_observations[{index}].coverage"),
        )?;
        if response.available_at < response.observed_at
            || response.available_at < kernel.event_available_at
            || response.analysis_cutoff < response.available_at
        {
            return fail(
                ValidationCode::InvalidTime,
                &format!("response_observations[{index}].available_at"),
                "response availability is inconsistent with observation/event availability",
            );
        }
        if response.value.is_none() && matches!(response.censoring, ResponseCensoring::None) {
            return fail(
                ValidationCode::InvalidResponse,
                &format!("response_observations[{index}].censoring"),
                "absent follow-up must be censored, never encoded as a zero/empty response",
            );
        }
        validate_response_censoring(
            &response.censoring,
            &format!("response_observations[{index}].censoring"),
        )?;
        require_input_refs(
            &response.source_input_ids,
            inputs,
            &format!("response_observations[{index}].source_input_ids"),
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_lines)] // Risk-set, terminal-event, censoring, and cut checks stay atomic.
fn validate_cohorts(
    dataset: &AttentionDataset,
    kernels: &HashMap<&str, &KernelEventRow>,
    inputs: &HashMap<&str, &ExactAttentionInput>,
) -> Result<(), AttentionValidationError> {
    let mut risk_sets: HashMap<&str, (u64, usize, bool)> = HashMap::new();
    let mut risk_subjects = HashSet::new();
    for (index, cohort) in dataset.cohort_rows.iter().enumerate() {
        let Some(kernel) = kernels.get(cohort.anchor_kernel_event_id.as_str()) else {
            return missing(
                &format!("cohort_rows[{index}].anchor_kernel_event_id"),
                cohort.anchor_kernel_event_id.as_str(),
            );
        };
        validate_coverage(&cohort.coverage, &format!("cohort_rows[{index}].coverage"))?;
        if cohort.anchor_cut < kernel.event_available_at
            || cohort.fit_cutoff < cohort.anchor_cut
            || cohort.risk_entry_at < cohort.risk_origin_at
            || cohort
                .risk_exit_at
                .is_some_and(|exit| exit < cohort.risk_entry_at)
        {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}]"),
                "cohort time order is invalid",
            );
        }
        if cohort.risk_set_denominator.get() == 0 {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].risk_set_denominator"),
                "risk set denominator must be explicit and nonzero",
            );
        }
        if !risk_subjects.insert((cohort.risk_set_id.as_str(), &cohort.subject)) {
            return fail(
                ValidationCode::DuplicateIdentity,
                &format!("cohort_rows[{index}].subject"),
                "a subject may appear only once in a risk set",
            );
        }
        let group = risk_sets.entry(cohort.risk_set_id.as_str()).or_insert((
            cohort.risk_set_denominator.get(),
            0,
            true,
        ));
        if group.0 != cohort.risk_set_denominator.get() {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].risk_set_denominator"),
                "all rows in a risk set must agree on its denominator",
            );
        }
        group.1 += 1;
        group.2 &= cohort.coverage.state == CoverageState::Complete;
        if cohort.left_truncated != (cohort.risk_entry_at > cohort.risk_origin_at) {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].left_truncated"),
                "left truncation flag must agree with risk entry after risk origin",
            );
        }
        if cohort.event_of_interest.is_some() && !cohort.competing_events.is_empty() {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}]"),
                "an event of interest and a competing terminal event cannot both label one risk spell",
            );
        }
        if cohort.competing_events.len() > 1 {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].competing_events"),
                "one risk spell may have only its first competing terminal event",
            );
        }
        if (cohort.event_of_interest.is_some() || !cohort.competing_events.is_empty())
            && !matches!(cohort.censoring, CohortCensoring::None)
        {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].censoring"),
                "competing/events-of-interest terminate risk; they are not censoring",
            );
        }
        if cohort.event_of_interest.is_none()
            && cohort.competing_events.is_empty()
            && matches!(cohort.censoring, CohortCensoring::None)
        {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].censoring"),
                "no observed terminal event requires explicit censoring",
            );
        }
        if cohort.choice_set_id.is_some() && cohort.witnessed_choice_set_complete != Some(true) {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].witnessed_choice_set_complete"),
                "choice-set claims require complete witnessed membership",
            );
        }
        if cohort.choice_set_id.is_some() && cohort.coverage.state != CoverageState::Complete {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].coverage"),
                "complete witnessed choice-set membership requires complete candidate coverage",
            );
        }
        if cohort.choice_set_id.is_some() && kernel.presentation_context.is_none() {
            return fail(
                ValidationCode::InvalidCohort,
                &format!("cohort_rows[{index}].choice_set_id"),
                "witnessed choice-set completeness requires a bound presentation/view/session",
            );
        }
        for event in cohort
            .event_of_interest
            .iter()
            .chain(cohort.competing_events.iter())
        {
            validate_event_time(
                &event.event_time,
                &format!("cohort_rows[{index}].terminal_event.event_time"),
            )?;
            if event.known_at > cohort.fit_cutoff {
                return fail(
                    ValidationCode::Leakage,
                    &format!("cohort_rows[{index}].terminal_event.known_at"),
                    "terminal event was unknown at the fit cutoff",
                );
            }
            require_input_refs(
                &event.source_input_ids,
                inputs,
                &format!("cohort_rows[{index}].terminal_event.source_input_ids"),
            )?;
            let Some(terminal_time) = event.event_time.lower else {
                return fail(
                    ValidationCode::InvalidCohort,
                    &format!("cohort_rows[{index}].terminal_event.event_time"),
                    "an observed terminal event requires a known lower bound",
                );
            };
            if cohort.risk_exit_at != Some(terminal_time) {
                return fail(
                    ValidationCode::InvalidCohort,
                    &format!("cohort_rows[{index}].risk_exit_at"),
                    "risk exit must equal the observed terminal-event lower bound",
                );
            }
        }
        for exposure in &cohort.exposure_summaries {
            validate_coverage(
                &exposure.coverage,
                &format!("cohort_rows[{index}].exposure_summaries.coverage"),
            )?;
            if exposure.available_at > cohort.anchor_cut
                || exposure.observed_through > cohort.anchor_cut
            {
                return fail(
                    ValidationCode::Leakage,
                    &format!("cohort_rows[{index}].exposure_summaries"),
                    "exposure summary crosses the anchor cut",
                );
            }
        }
        validate_cohort_censoring(
            &cohort.censoring,
            &format!("cohort_rows[{index}].censoring"),
        )?;
    }
    for (risk_set, (denominator, rows, complete)) in risk_sets {
        if complete && u64::try_from(rows).ok() != Some(denominator) {
            return fail(
                ValidationCode::InvalidCohort,
                "cohort_rows.risk_set_denominator",
                &format!(
                    "complete risk set {risk_set} has {rows} rows but denominator {denominator}"
                ),
            );
        }
    }
    Ok(())
}

fn event_kind_matches_source(kind: AttentionEventKind, source: &ExactInputKind) -> bool {
    matches!(
        (kind, source),
        (
            AttentionEventKind::Callout,
            ExactInputKind::CalloutObserved(_)
        ) | (
            AttentionEventKind::FollowChange,
            ExactInputKind::FollowSnapshotObserved(_) | ExactInputKind::FollowSnapshotMember(_)
        ) | (
            AttentionEventKind::CreatorTransition,
            ExactInputKind::CreatorRelationObserved(_)
        ) | (
            AttentionEventKind::CommunityTransition,
            ExactInputKind::CommunitySnapshotObserved(_)
        ) | (
            AttentionEventKind::CommentBurst,
            ExactInputKind::SocialContentObserved(_)
        ) | (
            AttentionEventKind::SocialTransition,
            ExactInputKind::SocialTransitionObserved(_)
        )
    )
}

fn input_mint(input: &ExactAttentionInput) -> Option<&joshi_domain::AssetId> {
    match &input.kind {
        ExactInputKind::CalloutObserved(row) => Some(&row.mint_id),
        ExactInputKind::CreatorRelationObserved(row) => Some(&row.mint_id),
        ExactInputKind::CommunitySnapshotObserved(row) => row.mint_id.as_ref(),
        ExactInputKind::SocialContentObserved(row) => row.mint_id.as_ref(),
        ExactInputKind::SocialTransitionObserved(row) => row.mint_id.as_ref(),
        ExactInputKind::FollowSnapshotObserved(_)
        | ExactInputKind::FollowSnapshotMember(_)
        | ExactInputKind::IdentityLinkObserved(_) => None,
    }
}

#[allow(clippy::too_many_arguments)] // The two independent bitemporal axes stay visible at call sites.
fn require_assertion_as_of(
    status: AssertionStatus,
    valid_lower: UtcTimestamp,
    valid_upper: Option<UtcTimestamp>,
    known_from: UtcTimestamp,
    known_until: Option<UtcTimestamp>,
    event_time: Option<UtcTimestamp>,
    cutoff: UtcTimestamp,
    path: &str,
) -> Result<(), AttentionValidationError> {
    let Some(event_time) = event_time else {
        return fail(
            ValidationCode::InvalidJoin,
            path,
            "point-in-time join requires a known event-time lower bound",
        );
    };
    if status == AssertionStatus::Retracted
        || !contains(valid_lower, valid_upper, event_time)
        || !contains(known_from, known_until, cutoff)
    {
        return fail(
            ValidationCode::Leakage,
            path,
            "selected assertion was not effective and known at the event cutoff",
        );
    }
    Ok(())
}

fn validate_event_time(value: &EventTime, path: &str) -> Result<(), AttentionValidationError> {
    match value.status {
        EventTimeStatus::Exact => {
            let (Some(lower), Some(upper), Some(precision)) =
                (value.lower, value.upper, value.precision_us)
            else {
                return fail(
                    ValidationCode::InvalidTime,
                    path,
                    "exact event time requires half-open bounds and an explicit precision",
                );
            };
            let width_us = (upper.as_datetime() - lower.as_datetime()).whole_microseconds();
            if width_us <= 0 || width_us != i128::from(precision.get()) {
                return fail(
                    ValidationCode::InvalidTime,
                    path,
                    "exact event interval width must equal precision_us under [lower, upper)",
                );
            }
        }
        EventTimeStatus::Bounded => {
            let (Some(lower), Some(upper)) = (value.lower, value.upper) else {
                return fail(
                    ValidationCode::InvalidTime,
                    path,
                    "bounded event time requires both bounds",
                );
            };
            if upper <= lower {
                return fail(
                    ValidationCode::InvalidTime,
                    path,
                    "half-open event-time upper bound must follow lower bound",
                );
            }
        }
        EventTimeStatus::SourceMissing | EventTimeStatus::NotApplicable => {
            if value.lower.is_some() || value.upper.is_some() || value.precision_us.is_some() {
                return fail(
                    ValidationCode::InvalidTime,
                    path,
                    "missing/not-applicable event time cannot carry interpreted bounds",
                );
            }
        }
    }
    Ok(())
}

fn validate_coverage(value: &CoverageContext, path: &str) -> Result<(), AttentionValidationError> {
    match value.state {
        CoverageState::Complete if !value.gap_ids.is_empty() => fail(
            ValidationCode::InvalidCoverage,
            path,
            "complete coverage cannot cite an intersecting gap",
        ),
        CoverageState::Gapped if value.gap_ids.is_empty() => fail(
            ValidationCode::InvalidCoverage,
            path,
            "gapped coverage requires at least one scoped gap identity",
        ),
        CoverageState::NotApplicable
            if !value.window_ids.is_empty()
                || !value.gap_ids.is_empty()
                || value.source_cursor.is_some() =>
        {
            fail(
                ValidationCode::InvalidCoverage,
                path,
                "not-applicable coverage cannot claim windows, gaps, or a cursor",
            )
        }
        _ => Ok(()),
    }
}

fn validate_intervals(
    valid_lower: UtcTimestamp,
    valid_upper: Option<UtcTimestamp>,
    known_from: UtcTimestamp,
    known_until: Option<UtcTimestamp>,
    path: &str,
) -> Result<(), AttentionValidationError> {
    validate_plain_interval(valid_lower, valid_upper, &format!("{path}.valid_time"))?;
    validate_plain_interval(known_from, known_until, &format!("{path}.knowledge_time"))
}

fn validate_plain_interval(
    lower: UtcTimestamp,
    upper: Option<UtcTimestamp>,
    path: &str,
) -> Result<(), AttentionValidationError> {
    if upper.is_some_and(|upper| upper <= lower) {
        fail(
            ValidationCode::InvalidTime,
            path,
            "half-open interval upper bound must follow lower bound",
        )
    } else {
        Ok(())
    }
}

fn contains(lower: UtcTimestamp, upper: Option<UtcTimestamp>, value: UtcTimestamp) -> bool {
    lower <= value && upper.is_none_or(|upper| value < upper)
}

fn validate_response_censoring(
    value: &ResponseCensoring,
    path: &str,
) -> Result<(), AttentionValidationError> {
    match value {
        ResponseCensoring::Interval { lower, upper, .. } if upper <= lower => fail(
            ValidationCode::InvalidResponse,
            path,
            "interval-censor upper bound must follow lower bound",
        ),
        ResponseCensoring::SourceLoss { gap_ids, .. } if gap_ids.is_empty() => fail(
            ValidationCode::InvalidResponse,
            path,
            "source-loss censoring requires scoped gap identities",
        ),
        _ => Ok(()),
    }
}

fn validate_cohort_censoring(
    value: &CohortCensoring,
    path: &str,
) -> Result<(), AttentionValidationError> {
    match value {
        CohortCensoring::Interval { lower, upper, .. } if upper <= lower => fail(
            ValidationCode::InvalidCohort,
            path,
            "interval-censor upper bound must follow lower bound",
        ),
        CohortCensoring::SourceLoss { gap_ids, .. } if gap_ids.is_empty() => fail(
            ValidationCode::InvalidCohort,
            path,
            "source-loss censoring requires scoped gap identities",
        ),
        _ => Ok(()),
    }
}

fn require_input_refs(
    ids: &[crate::AttentionInputId],
    inputs: &HashMap<&str, &ExactAttentionInput>,
    path: &str,
) -> Result<(), AttentionValidationError> {
    for id in ids {
        if !inputs.contains_key(id.as_str()) {
            return missing(path, id.as_str());
        }
    }
    Ok(())
}

fn unique<'a>(
    values: impl Iterator<Item = &'a str>,
    path: &str,
) -> Result<(), AttentionValidationError> {
    let mut seen = HashSet::new();
    for value in values {
        if !seen.insert(value) {
            return fail(
                ValidationCode::DuplicateIdentity,
                path,
                &format!("duplicate {value}"),
            );
        }
    }
    Ok(())
}

fn missing<T>(path: &str, id: &str) -> Result<T, AttentionValidationError> {
    Err(missing_error(path, id))
}

fn missing_error(path: &str, id: &str) -> AttentionValidationError {
    AttentionValidationError {
        code: ValidationCode::MissingReference,
        path: path.to_owned(),
        detail: format!("missing {id}"),
    }
}

fn fail<T>(code: ValidationCode, path: &str, detail: &str) -> Result<T, AttentionValidationError> {
    Err(AttentionValidationError {
        code,
        path: path.to_owned(),
        detail: detail.to_owned(),
    })
}
