//! Deterministic reducers and independent S2 qualification.

use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};

use crate::{
    DailyUseSurfaceProfileV1, DeclaredObservedUniverseV1, EmberUseSessionV1, FieldState,
    HotLeaseV1, QUALIFICATION_EVIDENCE_CONTRACT, QualificationCeiling, QualificationResultV1,
    READ_ONLY_AUTHORITY, SURFACE_CONTRACT, SURFACE_SCHEMA_VERSION, SurfaceCutV1, SurfaceError,
    SurfaceMembership, SurfaceObservationV1, SurfaceOmissionV1, SurfaceSemanticAuthority,
};

/// A complete point-in-time reduction. `observations` may include later corrections; knowledge
/// time filtering makes those corrections invisible to an earlier cut.
pub struct SurfaceReducer;

impl SurfaceReducer {
    /// Reduce the complete admitted observation set at an exact knowledge cutoff.
    pub fn reduce(
        profile: &DailyUseSurfaceProfileV1,
        universe: DeclaredObservedUniverseV1,
        observations: &[SurfaceObservationV1],
        cutoff: UtcTimestamp,
        render_limit: usize,
    ) -> Result<SurfaceCutV1, SurfaceError> {
        profile.validate()?;
        universe.validate()?;
        if universe.cutoff != cutoff {
            return Err(SurfaceError::Cutoff);
        }
        let mut admitted: Vec<&SurfaceObservationV1> = observations
            .iter()
            .filter(|item| item.known_at <= cutoff)
            .collect();
        admitted.sort_by(|a, b| {
            a.known_at
                .cmp(&b.known_at)
                .then(a.event_id.cmp(&b.event_id))
        });
        let mut seen: BTreeMap<StableString, SurfaceObservationV1> = BTreeMap::new();
        for item in admitted {
            item.validate()?;
            let Some(surface) = profile
                .surfaces
                .iter()
                .find(|surface| surface.surface_id == item.surface_id)
            else {
                return Err(SurfaceError::Contract);
            };
            if surface.source != item.source_id {
                return Err(SurfaceError::Contract);
            }
            if item
                .fields
                .keys()
                .any(|field| !surface.fields_media.contains(field))
            {
                return Err(SurfaceError::Contract);
            }
            if universe.closed
                && !universe
                    .eligible_subjects
                    .iter()
                    .any(|subject| subject == &item.subject)
            {
                return Err(SurfaceError::UniverseNotClosed);
            }
            if let Some(superseded) = &item.supersedes_event_id {
                let Some(prior) = seen.get(superseded) else {
                    return Err(SurfaceError::ConflictingEvent);
                };
                if prior.subject != item.subject
                    || prior.surface_id != item.surface_id
                    || prior.source_id != item.source_id
                    || prior.known_at >= item.known_at
                {
                    return Err(SurfaceError::ConflictingEvent);
                }
                seen.remove(superseded);
            }
            if let Some(prior) = seen.get(&item.event_id) {
                if prior != item {
                    return Err(SurfaceError::ConflictingEvent);
                }
            } else {
                seen.insert(item.event_id.clone(), item.clone());
            }
        }
        let mut values: Vec<_> = seen.into_values().collect();
        values.sort_by(|a, b| {
            a.order_key
                .cmp(&b.order_key)
                .then(a.subject.cmp(&b.subject))
                .then(a.event_id.cmp(&b.event_id))
        });
        let all_values = values.clone();
        if universe.closed
            && all_values.iter().any(|item| {
                !universe
                    .eligible_subjects
                    .iter()
                    .any(|subject| subject == &item.subject)
            })
        {
            return Err(SurfaceError::UniverseNotClosed);
        }
        let mut omissions = Vec::new();
        for item in &all_values {
            if item
                .memberships
                .contains(&SurfaceMembership::DenominatorOnly)
            {
                omissions.push(SurfaceOmissionV1 {
                    subject: item.subject.clone(),
                    reason: stable("denominator_only")?,
                    membership: SurfaceMembership::DenominatorOnly,
                });
            }
        }
        if universe.closed {
            let present: BTreeSet<_> = all_values.iter().map(|item| item.subject.clone()).collect();
            for subject in &universe.eligible_subjects {
                if !present.contains(subject) {
                    omissions.push(SurfaceOmissionV1 {
                        subject: subject.clone(),
                        reason: stable("not_observed_by_cutoff")?,
                        membership: SurfaceMembership::DenominatorOnly,
                    });
                }
            }
        }
        values.retain(|item| {
            !item
                .memberships
                .contains(&SurfaceMembership::DenominatorOnly)
        });
        values.truncate(render_limit);
        let candidates: Vec<_> = all_values
            .iter()
            .filter(|item| {
                !item
                    .memberships
                    .contains(&SurfaceMembership::DenominatorOnly)
            })
            .collect();
        for item in candidates.iter().skip(render_limit) {
            if !item
                .memberships
                .contains(&SurfaceMembership::DenominatorOnly)
            {
                omissions.push(SurfaceOmissionV1 {
                    subject: item.subject.clone(),
                    reason: stable("bounded_rendered_subset")?,
                    membership: item
                        .memberships
                        .first()
                        .copied()
                        .unwrap_or(SurfaceMembership::Census),
                });
            }
        }
        omissions.sort_by(|a, b| {
            a.subject
                .cmp(&b.subject)
                .then(a.reason.cmp(&b.reason))
                .then(a.membership.cmp(&b.membership))
        });
        // A cut is a subject partition, even when several surface rows exist for one subject or
        // the render limit truncates rows. A rendered subject therefore cannot also be omitted,
        // and one explicit omission is retained for every non-rendered eligible subject.
        let rendered_subjects: BTreeSet<_> =
            values.iter().map(|item| item.subject.clone()).collect();
        omissions.retain(|omission| !rendered_subjects.contains(&omission.subject));
        omissions.dedup_by(|a, b| a.subject == b.subject);
        if universe.closed {
            let omitted_subjects: BTreeSet<_> =
                omissions.iter().map(|item| item.subject.clone()).collect();
            for subject in &universe.eligible_subjects {
                if !rendered_subjects.contains(subject) && !omitted_subjects.contains(subject) {
                    omissions.push(SurfaceOmissionV1 {
                        subject: subject.clone(),
                        reason: stable("not_observed_by_cutoff")?,
                        membership: SurfaceMembership::DenominatorOnly,
                    });
                }
            }
        }
        omissions.sort_by(|a, b| {
            a.subject
                .cmp(&b.subject)
                .then(a.reason.cmp(&b.reason))
                .then(a.membership.cmp(&b.membership))
        });
        #[derive(Clone, Eq, Ord, PartialEq, PartialOrd)]
        struct FieldKey {
            surface_id: StableString,
            source_id: StableString,
            subject: StableString,
            field: StableString,
        }
        let mut state_by_field: BTreeMap<FieldKey, (Option<UtcTimestamp>, FieldState)> =
            BTreeMap::new();
        for surface in &profile.surfaces {
            for subject in &universe.eligible_subjects {
                for field_name in &surface.fields_media {
                    let key = FieldKey {
                        surface_id: surface.surface_id.clone(),
                        source_id: surface.source.clone(),
                        subject: subject.clone(),
                        field: field_name.clone(),
                    };
                    state_by_field.insert(
                        key,
                        (
                            None,
                            FieldState::Unknown {
                                reason: stable("not_observed_by_cutoff")?,
                            },
                        ),
                    );
                }
            }
        }
        for item in &all_values {
            let Some(surface) = profile
                .surfaces
                .iter()
                .find(|surface| surface.surface_id == item.surface_id)
            else {
                return Err(SurfaceError::Contract);
            };
            for field_name in &surface.fields_media {
                let state = item
                    .fields
                    .get(field_name)
                    .cloned()
                    .unwrap_or(FieldState::Unknown {
                        reason: stable("field_not_observed")?,
                    });
                let field = FieldKey {
                    surface_id: item.surface_id.clone(),
                    source_id: item.source_id.clone(),
                    subject: item.subject.clone(),
                    field: field_name.clone(),
                };
                let replace = state_by_field.get(&field).is_none_or(|(known_at, _)| {
                    known_at.is_none_or(|previous| item.known_at >= previous)
                });
                if replace {
                    state_by_field.insert(field, (Some(item.known_at), state));
                }
            }
        }
        let states: Vec<_> = state_by_field
            .into_iter()
            .map(|(field, (_, state))| crate::SurfaceFieldStateV1 {
                surface_id: field.surface_id,
                source_id: field.source_id,
                subject: field.subject,
                field: field.field,
                state,
            })
            .collect();
        let cut = SurfaceCutV1 {
            contract: stable(SURFACE_CONTRACT)?,
            schema_version: SURFACE_SCHEMA_VERSION,
            profile_digest: profile.profile_digest.clone(),
            cutoff,
            universe,
            rendered: values,
            omissions,
            ordering_policy: stable("order_key_subject_event_id_v1")?,
            source_states: states,
            reducer_digest: ValueDigest::new(
                "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            )
            .map_err(|_| SurfaceError::DigestFormat)?,
            authority: stable(READ_ONLY_AUTHORITY)?,
        };
        let mut cut = cut;
        cut.reducer_digest = cut.computed_reducer_digest()?;
        cut.validate_against(profile)?;
        Ok(cut)
    }

    /// Resume reduction from a prior cut. The prior is a checkpoint only; the target remains a
    /// complete point-in-time closure, so full and incremental bytes are identical.
    pub fn reduce_incremental(
        prior: &SurfaceCutV1,
        profile: &DailyUseSurfaceProfileV1,
        universe: DeclaredObservedUniverseV1,
        observations: &[SurfaceObservationV1],
        cutoff: UtcTimestamp,
        render_limit: usize,
    ) -> Result<SurfaceCutV1, SurfaceError> {
        prior.validate()?;
        if prior.profile_digest != profile.profile_digest || cutoff <= prior.cutoff {
            return Err(SurfaceError::Cutoff);
        }
        Self::reduce(profile, universe, observations, cutoff, render_limit)
    }
}

fn stable(value: &str) -> Result<StableString, SurfaceError> {
    StableString::new(value).map_err(|_| SurfaceError::Contract)
}

/// Evaluate S2 product evidence without inferring it from telemetry or economics.
pub fn qualify_cockpit(
    profile: &DailyUseSurfaceProfileV1,
    sessions: &[EmberUseSessionV1],
) -> Result<QualificationResultV1, SurfaceError> {
    profile.validate()?;
    let required: BTreeSet<_> = profile
        .surfaces
        .iter()
        .filter(|surface| surface.critical)
        .flat_map(|surface| {
            surface
                .tasks
                .iter()
                .filter(|task| task.critical)
                .map(|task| task.task_id.clone())
        })
        .collect();
    let mut qualifying = Vec::new();
    for session in sessions {
        if session.profile_digest != profile.profile_digest
            || session.build_digest != session.acknowledgment.build_digest
            || session.session_id != session.acknowledgment.session_id
            || session.profile_digest != session.acknowledgment.profile_digest
        {
            return Err(SurfaceError::QualificationBinding);
        }
        let ack = &session.acknowledgment;
        let evidence_valid = session.evidence.iter().all(|evidence| {
            evidence.contract.as_str() == QUALIFICATION_EVIDENCE_CONTRACT
                && evidence.evidence_digest.as_str().len() == 71
                && evidence.evidence_digest.as_str().starts_with("sha256:")
        });
        if !evidence_valid {
            return Err(SurfaceError::QualificationBinding);
        }
        if ack.reduced_navigation_burden
            && ack.preserved_orientation
            && ack.worth_reopening
            && required.is_subset(&session.supported_critical_tasks)
            && (!session.switched_away_for_parity_gap || session.switch_reason.is_some())
        {
            qualifying.push(session);
        }
    }
    // Public caller-supplied session/receipt DTOs are an unverified semantic ceiling. A private
    // atomic store adapter must resolve the evidence before any capability can be attained.
    let capabilities = BTreeSet::new();
    let status = if !qualifying.is_empty() {
        "unverified"
    } else {
        "unqualified"
    };
    Ok(QualificationResultV1 {
        profile_digest: profile.profile_digest.clone(),
        capabilities,
        session_ids: qualifying.iter().map(|s| s.session_id.clone()).collect(),
        status: stable(status)?,
        verified: false,
        ceiling: QualificationCeiling::UnverifiedSemantic,
    })
}

/// Validate a lease at the explicit local-control waist.
pub fn validate_hot_lease(lease: &HotLeaseV1) -> Result<(), SurfaceError> {
    if lease.authority != SurfaceSemanticAuthority::UnverifiedSemantic {
        return Err(SurfaceError::HotControlClosure);
    }
    lease.validate()
}

/// Convenience wrapper for integrators that do not need the reducer type name.
pub fn reduce_surface(
    profile: &DailyUseSurfaceProfileV1,
    universe: DeclaredObservedUniverseV1,
    observations: &[SurfaceObservationV1],
    cutoff: UtcTimestamp,
    render_limit: usize,
) -> Result<SurfaceCutV1, SurfaceError> {
    SurfaceReducer::reduce(profile, universe, observations, cutoff, render_limit)
}

/// Convenience wrapper preserving the full-closure incremental semantics.
pub fn reduce_surface_incremental(
    prior: &SurfaceCutV1,
    profile: &DailyUseSurfaceProfileV1,
    universe: DeclaredObservedUniverseV1,
    observations: &[SurfaceObservationV1],
    cutoff: UtcTimestamp,
    render_limit: usize,
) -> Result<SurfaceCutV1, SurfaceError> {
    SurfaceReducer::reduce_incremental(prior, profile, universe, observations, cutoff, render_limit)
}

/// Parse strict canonical bytes produced by this crate.
pub fn parse_surface_cut(bytes: &[u8]) -> Result<SurfaceCutV1, SurfaceError> {
    let cut: SurfaceCutV1 = serde_json::from_slice(bytes)?;
    cut.validate()?;
    Ok(cut)
}

/// Parse and close a cut against the exact approved profile denominator.
pub fn parse_surface_cut_against(
    bytes: &[u8],
    profile: &DailyUseSurfaceProfileV1,
) -> Result<SurfaceCutV1, SurfaceError> {
    let cut = parse_surface_cut(bytes)?;
    cut.validate_against(profile)?;
    Ok(cut)
}

/// Parse strict profile bytes; unknown fields are rejected by the DTOs.
pub fn parse_profile(bytes: &[u8]) -> Result<DailyUseSurfaceProfileV1, SurfaceError> {
    let profile: DailyUseSurfaceProfileV1 = serde_json::from_slice(bytes)?;
    profile.validate()?;
    Ok(profile)
}

/// Lease TTL as an exact wire integer, useful to integrators avoiding native integer coercion.
#[must_use]
pub const fn ttl(seconds: u64) -> WireU64 {
    WireU64::new(seconds)
}
