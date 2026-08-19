//! Wire DTOs for the profile, point-in-time surface, leases and product witnesses.

use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{READ_ONLY_AUTHORITY, SURFACE_CONTRACT, SURFACE_SCHEMA_VERSION, SurfaceError};

fn stable(value: &str) -> Result<StableString, SurfaceError> {
    StableString::new(value.to_owned()).map_err(|_| SurfaceError::Contract)
}

fn digest(bytes: &[u8]) -> Result<ValueDigest, SurfaceError> {
    let mut hash = Sha256::new();
    hash.update(bytes);
    ValueDigest::new(format!("sha256:{:x}", hash.finalize()))
        .map_err(|_| SurfaceError::DigestFormat)
}

fn check_digest(value: &ValueDigest) -> Result<(), SurfaceError> {
    let text = value.as_str();
    if text.len() != 71
        || !text.starts_with("sha256:")
        || !text[7..]
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    {
        return Err(SurfaceError::DigestFormat);
    }
    Ok(())
}

/// Surface classes named by the S0 constitution.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SurfaceKind {
    LaunchNew,
    BoardsTrending,
    LiveActivity,
    CalloutsFollows,
    WatchedWalletActivity,
    SearchDirectMint,
    SocialMediaReplies,
    CreatorCommunity,
    LifecycleMigrationPools,
    PositionExposureContext,
}

/// Field-specific product/source status. These values are deliberately not a single availability
/// boolean: a chain fact can be useful while personalized product order is unavailable.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SurfaceStatus {
    PromotedContinuous,
    PublicChainAlternativeNotProductParity,
    CompanionFallback,
    Degraded,
    Unavailable,
    AbsentByDesign,
}

impl SurfaceStatus {
    #[must_use]
    pub const fn counts_product_parity(self) -> bool {
        matches!(self, Self::PromotedContinuous)
    }
}

/// Accessibility evidence for one exact task flow.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AccessibilityEvidence {
    pub keyboard: bool,
    pub large_target: bool,
    pub screen_reader: bool,
    pub reduced_motion: bool,
    pub evidence_id: StableString,
}

/// One task Ember actually performs against a surface.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceTaskV1 {
    pub task_id: StableString,
    pub name: StableString,
    pub critical: bool,
    pub accessibility: AccessibilityEvidence,
}

/// Versioned surface constitution entry.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceEntryV1 {
    pub surface_id: StableString,
    pub kind: SurfaceKind,
    pub critical: bool,
    pub route: StableString,
    pub source: StableString,
    pub personalization: StableString,
    pub ordering: StableString,
    pub pagination: StableString,
    pub cadence: StableString,
    pub fields_media: Vec<StableString>,
    pub field_status: BTreeMap<StableString, SurfaceStatus>,
    pub status: SurfaceStatus,
    pub approval: Option<StableString>,
    pub tasks: Vec<SurfaceTaskV1>,
}

/// Ember-approved, immutable-in-use profile. A Pump change creates a new version.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DailyUseSurfaceProfileV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub profile_id: StableString,
    pub profile_version: WireU64,
    pub ember_approval_id: StableString,
    pub approved_at: UtcTimestamp,
    pub surfaces: Vec<SurfaceEntryV1>,
    pub profile_digest: ValueDigest,
    pub authority: StableString,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ProfileMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    profile_id: &'a StableString,
    profile_version: WireU64,
    ember_approval_id: &'a StableString,
    approved_at: &'a UtcTimestamp,
    surfaces: &'a [SurfaceEntryV1],
    authority: &'a StableString,
}

impl DailyUseSurfaceProfileV1 {
    /// Recompute the profile's exact identity digest.
    pub fn computed_digest(&self) -> Result<ValueDigest, SurfaceError> {
        let bytes = serde_json::to_vec(&ProfileMaterial {
            contract: &self.contract,
            schema_version: self.schema_version,
            profile_id: &self.profile_id,
            profile_version: self.profile_version,
            ember_approval_id: &self.ember_approval_id,
            approved_at: &self.approved_at,
            surfaces: &self.surfaces,
            authority: &self.authority,
        })?;
        digest(&bytes)
    }

    /// Validate constitution and the self-declared exact profile digest.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        if self.contract.as_str() != SURFACE_CONTRACT
            || self.schema_version != SURFACE_SCHEMA_VERSION
            || self.authority.as_str() != READ_ONLY_AUTHORITY
            || self.surfaces.is_empty()
        {
            return Err(if self.surfaces.is_empty() {
                SurfaceError::EmptyProfile
            } else {
                SurfaceError::Contract
            });
        }
        check_digest(&self.profile_digest)?;
        let mut ids = BTreeSet::new();
        let mut task_ids = BTreeSet::new();
        for surface in &self.surfaces {
            if !ids.insert(surface.surface_id.clone()) {
                return Err(SurfaceError::DuplicateSurface);
            }
            if surface.fields_media.is_empty()
                || surface
                    .fields_media
                    .windows(2)
                    .any(|pair| pair[0] >= pair[1])
                || surface.field_status.len() != surface.fields_media.len()
                || surface
                    .fields_media
                    .iter()
                    .any(|field| !surface.field_status.contains_key(field))
            {
                return Err(SurfaceError::Contract);
            }
            if surface.critical && !surface.tasks.iter().any(|task| task.critical) {
                return Err(SurfaceError::CriticalAccessibility);
            }
            for task in &surface.tasks {
                if !task_ids.insert(task.task_id.clone()) {
                    return Err(SurfaceError::DuplicateTask);
                }
            }
            if matches!(surface.status, SurfaceStatus::AbsentByDesign)
                && (surface.approval.is_none()
                    || surface
                        .approval
                        .as_ref()
                        .is_some_and(|v| v.as_str().trim().is_empty()))
            {
                return Err(SurfaceError::AbsentByDesignApproval);
            }
            // A profile is a constitution, not a success witness. Critical degraded,
            // unavailable, alternative and absent-by-design entries remain representable so
            // gaps cannot be hidden by narrowing the denominator. Accessibility and parity are
            // evaluated independently by `qualify_cockpit`.
        }
        if self.computed_digest()? != self.profile_digest {
            return Err(SurfaceError::DigestMismatch);
        }
        Ok(())
    }

    /// Compact canonical profile bytes for store/publication handoff.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, SurfaceError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    /// Number of critical entries that truly count as product parity.
    #[must_use]
    pub fn critical_count(&self) -> usize {
        self.surfaces.iter().filter(|s| s.critical).count()
    }
}

/// A declared eligible universe and its point-in-time denominator.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DeclaredObservedUniverseV1 {
    pub universe_id: StableString,
    pub surface_version: WireU64,
    pub cutoff: UtcTimestamp,
    pub eligible_count: WireU64,
    pub eligible_subjects: Vec<StableString>,
    pub eligible_digest: ValueDigest,
    pub closed: bool,
    pub sample_only: bool,
}

impl DeclaredObservedUniverseV1 {
    pub fn validate(&self) -> Result<(), SurfaceError> {
        check_digest(&self.eligible_digest)?;
        if !self.closed && !self.sample_only {
            return Err(SurfaceError::UniverseNotClosed);
        }
        if self
            .eligible_subjects
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
            || u64::try_from(self.eligible_subjects.len())
                .map_err(|_| SurfaceError::UniverseNotClosed)?
                != self.eligible_count.get()
        {
            return Err(SurfaceError::UniverseNotClosed);
        }
        let expected = digest(&serde_json::to_vec(&self.eligible_subjects)?)?;
        if expected != self.eligible_digest {
            return Err(SurfaceError::DigestMismatch);
        }
        Ok(())
    }
}

/// Membership in the broad sensorium. `DenominatorOnly` is intentionally not rendered.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SurfaceMembership {
    Census,
    Warm,
    Hot,
    Episode,
    ColdControl,
    DenominatorOnly,
}

/// Explicit field-level epistemic state.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum FieldState {
    Covered {
        observed_at: UtcTimestamp,
    },
    Gap {
        gap_id: StableString,
        since: UtcTimestamp,
    },
    Stale {
        observed_at: UtcTimestamp,
        age_seconds: WireU64,
    },
    Refused {
        reason: StableString,
    },
    Unknown {
        reason: StableString,
    },
}

impl FieldState {
    #[must_use]
    pub const fn is_covered(&self) -> bool {
        matches!(self, Self::Covered { .. })
    }

    pub(crate) fn valid_at(&self, cutoff: UtcTimestamp) -> bool {
        match self {
            Self::Covered { observed_at }
            | Self::Gap {
                since: observed_at, ..
            } => *observed_at <= cutoff,
            Self::Stale {
                observed_at,
                age_seconds,
            } => {
                if *observed_at > cutoff {
                    return false;
                }
                let elapsed = (cutoff.as_datetime() - observed_at.as_datetime()).whole_seconds();
                u64::try_from(elapsed).is_ok_and(|value| value == age_seconds.get())
            }
            Self::Refused { .. } | Self::Unknown { .. } => true,
        }
    }
}

/// One subject admitted to a census/hot reduction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceObservationV1 {
    pub event_id: StableString,
    pub subject: StableString,
    pub observed_at: UtcTimestamp,
    pub known_at: UtcTimestamp,
    pub supersedes_event_id: Option<StableString>,
    pub surface_id: StableString,
    pub source_id: StableString,
    pub memberships: Vec<SurfaceMembership>,
    pub fields: BTreeMap<StableString, FieldState>,
    pub order_key: StableString,
    pub evidence_digest: ValueDigest,
}

impl SurfaceObservationV1 {
    pub fn validate(&self) -> Result<(), SurfaceError> {
        check_digest(&self.evidence_digest)?;
        if self.observed_at > self.known_at {
            return Err(SurfaceError::Cutoff);
        }
        let unique: BTreeSet<_> = self.memberships.iter().copied().collect();
        if unique.len() != self.memberships.len()
            || (unique.contains(&SurfaceMembership::DenominatorOnly) && unique.len() > 1)
        {
            return Err(SurfaceError::Membership);
        }
        Ok(())
    }
}

/// Explicit omission reason retained beside the bounded rendered subset.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceOmissionV1 {
    pub subject: StableString,
    pub reason: StableString,
    pub membership: SurfaceMembership,
}

/// A field state keyed by the complete surface/source/subject/field tuple.
///
/// This is intentionally a list rather than a delimited JSON object map: a subject or
/// provider identifier may contain punctuation, and a source-wide state must never mask a
/// different subject's unknown state.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceFieldStateV1 {
    pub surface_id: StableString,
    pub source_id: StableString,
    pub subject: StableString,
    pub field: StableString,
    pub state: FieldState,
}

/// A deterministic immutable point-in-time surface projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceCutV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub profile_digest: ValueDigest,
    pub cutoff: UtcTimestamp,
    pub universe: DeclaredObservedUniverseV1,
    pub rendered: Vec<SurfaceObservationV1>,
    pub omissions: Vec<SurfaceOmissionV1>,
    pub ordering_policy: StableString,
    pub source_states: Vec<SurfaceFieldStateV1>,
    pub reducer_digest: ValueDigest,
    pub authority: StableString,
}

impl SurfaceCutV1 {
    pub fn computed_reducer_digest(&self) -> Result<ValueDigest, SurfaceError> {
        #[derive(Serialize)]
        #[serde(rename_all = "camelCase")]
        struct Material<'a> {
            profile_digest: &'a ValueDigest,
            cutoff: UtcTimestamp,
            universe: &'a DeclaredObservedUniverseV1,
            rendered: &'a [SurfaceObservationV1],
            omissions: &'a [SurfaceOmissionV1],
            ordering_policy: &'a StableString,
            source_states: &'a [SurfaceFieldStateV1],
            authority: &'a StableString,
        }
        let material = Material {
            profile_digest: &self.profile_digest,
            cutoff: self.cutoff,
            universe: &self.universe,
            rendered: &self.rendered,
            omissions: &self.omissions,
            ordering_policy: &self.ordering_policy,
            source_states: &self.source_states,
            authority: &self.authority,
        };
        digest(&serde_json::to_vec(&material)?)
    }

    pub fn validate(&self) -> Result<(), SurfaceError> {
        if self.contract.as_str() != SURFACE_CONTRACT
            || self.schema_version != SURFACE_SCHEMA_VERSION
            || self.authority.as_str() != READ_ONLY_AUTHORITY
        {
            return Err(SurfaceError::Contract);
        }
        check_digest(&self.profile_digest)?;
        check_digest(&self.reducer_digest)?;
        self.universe.validate()?;
        if self.universe.cutoff != self.cutoff
            || self.rendered.windows(2).any(|w| {
                (
                    w[0].order_key.clone(),
                    w[0].subject.clone(),
                    w[0].event_id.clone(),
                ) >= (
                    w[1].order_key.clone(),
                    w[1].subject.clone(),
                    w[1].event_id.clone(),
                )
            })
        {
            return Err(SurfaceError::Cutoff);
        }
        if self.omissions.windows(2).any(|w| {
            (w[0].subject.clone(), w[0].reason.clone(), w[0].membership)
                >= (w[1].subject.clone(), w[1].reason.clone(), w[1].membership)
        }) {
            return Err(SurfaceError::Membership);
        }
        let eligible: BTreeSet<_> = self.universe.eligible_subjects.iter().cloned().collect();
        let rendered_subjects: BTreeSet<_> = self
            .rendered
            .iter()
            .map(|item| item.subject.clone())
            .collect();
        let omitted_subjects: BTreeSet<_> = self
            .omissions
            .iter()
            .map(|item| item.subject.clone())
            .collect();
        if self.rendered.iter().any(|item| {
            item.memberships
                .contains(&SurfaceMembership::DenominatorOnly)
                || (self.universe.closed && !eligible.contains(&item.subject))
        }) || self
            .omissions
            .iter()
            .any(|item| self.universe.closed && !eligible.contains(&item.subject))
            || rendered_subjects
                .intersection(&omitted_subjects)
                .next()
                .is_some()
        {
            return Err(SurfaceError::UniverseNotClosed);
        }
        if self.universe.closed {
            let mut partition = rendered_subjects.clone();
            partition.extend(omitted_subjects.iter().cloned());
            if partition != eligible || omitted_subjects.len() != self.omissions.len() {
                return Err(SurfaceError::UniverseNotClosed);
            }
        }
        for item in &self.rendered {
            item.validate()?;
            if item
                .fields
                .values()
                .any(|state| !state.valid_at(self.cutoff))
            {
                return Err(SurfaceError::Cutoff);
            }
        }
        if self.source_states.windows(2).any(|w| w[0] >= w[1]) {
            return Err(SurfaceError::Membership);
        }
        let mut keys = BTreeSet::new();
        let eligible: BTreeSet<_> = self.universe.eligible_subjects.iter().cloned().collect();
        for state in &self.source_states {
            if !keys.insert((
                state.surface_id.clone(),
                state.source_id.clone(),
                state.subject.clone(),
                state.field.clone(),
            )) || (self.universe.closed && !eligible.contains(&state.subject))
                || !state.state.valid_at(self.cutoff)
            {
                return Err(SurfaceError::Membership);
            }
        }
        if self.universe.closed
            && self.universe.eligible_subjects.iter().any(|subject| {
                !self
                    .source_states
                    .iter()
                    .any(|state| &state.subject == subject)
            })
        {
            return Err(SurfaceError::Cutoff);
        }
        if self.computed_reducer_digest()? != self.reducer_digest {
            return Err(SurfaceError::DigestMismatch);
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, SurfaceError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    /// Validate the profile-derived field/source/subject denominator in addition to intrinsic
    /// cut closure. This prevents a caller-authored cut from omitting required Unknown cells.
    pub fn validate_against(&self, profile: &DailyUseSurfaceProfileV1) -> Result<(), SurfaceError> {
        self.validate()?;
        profile.validate()?;
        if self.profile_digest != profile.profile_digest {
            return Err(SurfaceError::DigestMismatch);
        }
        let expected: BTreeSet<_> = profile
            .surfaces
            .iter()
            .flat_map(|surface| {
                self.universe
                    .eligible_subjects
                    .iter()
                    .flat_map(move |subject| {
                        surface.fields_media.iter().map(move |field| {
                            (
                                surface.surface_id.clone(),
                                surface.source.clone(),
                                subject.clone(),
                                field.clone(),
                            )
                        })
                    })
            })
            .collect();
        let actual: BTreeSet<_> = self
            .source_states
            .iter()
            .map(|state| {
                (
                    state.surface_id.clone(),
                    state.source_id.clone(),
                    state.subject.clone(),
                    state.field.clone(),
                )
            })
            .collect();
        if actual != expected || actual.len() != self.source_states.len() {
            return Err(SurfaceError::UniverseNotClosed);
        }
        Ok(())
    }
}

/// Hot-scope lifecycle. Applied closes local collector control only; it never proves provider
/// acceptance or coverage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeIntentV1 {
    pub intent_id: StableString,
    pub subject: StableString,
    pub reason: StableString,
    pub denominator: StableString,
    pub created_at: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeDesiredV1 {
    pub desired_id: StableString,
    pub intent_id: StableString,
    pub lease_id: StableString,
    pub reason: StableString,
    pub ttl_seconds: WireU64,
    pub expires_at: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotControlWriteReservationV1 {
    pub reservation_id: StableString,
    pub desired_id: StableString,
    pub reserved_at: UtcTimestamp,
    pub control_digest: ValueDigest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeAppliedV1 {
    pub applied_id: StableString,
    pub desired_id: StableString,
    pub control_reservation_id: StableString,
    pub applied_at: UtcTimestamp,
    pub receipt_id: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeDegradedV1 {
    pub degraded_id: StableString,
    pub desired_id: StableString,
    pub control_reservation_id: StableString,
    pub degraded_at: UtcTimestamp,
    pub reason: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AcquisitionReservationV1 {
    pub reservation_id: StableString,
    pub subject: StableString,
    pub reserved_at: UtcTimestamp,
    pub cost_digest: ValueDigest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotLeaseV1 {
    pub lease_id: StableString,
    pub intent: HotScopeIntentV1,
    pub desired: HotScopeDesiredV1,
    pub denominator: StableString,
    pub control_reservation: HotControlWriteReservationV1,
    pub applied: Option<HotScopeAppliedV1>,
    pub degraded: Option<HotScopeDegradedV1>,
    pub acquisition_reservation: AcquisitionReservationV1,
    pub authority: SurfaceSemanticAuthority,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SurfaceSemanticAuthority {
    UnverifiedSemantic,
}

impl HotLeaseV1 {
    pub fn validate(&self) -> Result<(), SurfaceError> {
        if self.authority != SurfaceSemanticAuthority::UnverifiedSemantic {
            return Err(SurfaceError::HotControlClosure);
        }
        check_digest(&self.control_reservation.control_digest)?;
        check_digest(&self.acquisition_reservation.cost_digest)?;
        if self.lease_id != self.desired.lease_id
            || self.desired.intent_id != self.intent.intent_id
            || self.denominator != self.intent.denominator
            || self.desired.ttl_seconds.get() == 0
            || (self.desired.expires_at.as_datetime()
                - self.control_reservation.reserved_at.as_datetime())
            .whole_microseconds()
                != i128::from(self.desired.ttl_seconds.get()) * 1_000_000
            || self.control_reservation.reserved_at < self.intent.created_at
            || self.desired.expires_at <= self.control_reservation.reserved_at
            || self.acquisition_reservation.reserved_at < self.control_reservation.reserved_at
            || (self.applied.is_some() == self.degraded.is_some())
        {
            return Err(
                if self.desired.ttl_seconds.get() == 0
                    || self.desired.expires_at <= self.control_reservation.reserved_at
                {
                    SurfaceError::HotLeaseInterval
                } else {
                    SurfaceError::HotControlClosure
                },
            );
        }
        if self.acquisition_reservation.subject != self.intent.subject {
            return Err(SurfaceError::HotLeaseEvidence);
        }
        if let Some(applied) = &self.applied
            && (applied.desired_id != self.desired.desired_id
                || applied.control_reservation_id != self.control_reservation.reservation_id
                || applied.applied_at < self.control_reservation.reserved_at
                || applied.applied_at >= self.desired.expires_at)
        {
            {
                return Err(SurfaceError::HotControlClosure);
            }
        }
        if let Some(degraded) = &self.degraded
            && (degraded.desired_id != self.desired.desired_id
                || degraded.control_reservation_id != self.control_reservation.reservation_id
                || degraded.degraded_at < self.control_reservation.reserved_at
                || degraded.degraded_at >= self.desired.expires_at)
        {
            {
                return Err(SurfaceError::HotControlClosure);
            }
        }
        let closed_at = match (&self.applied, &self.degraded) {
            (Some(applied), None) => applied.applied_at,
            (None, Some(degraded)) => degraded.degraded_at,
            _ => return Err(SurfaceError::HotControlClosure),
        };
        if self.acquisition_reservation.reserved_at < closed_at
            || self.acquisition_reservation.reserved_at >= self.desired.expires_at
        {
            return Err(SurfaceError::HotControlClosure);
        }
        Ok(())
    }

    /// Compact canonical lease bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the lease does not validate or cannot be encoded.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, SurfaceError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }
}

/// Exact Ember acknowledgment used for product-use qualification.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EmberUseAcknowledgmentV1 {
    pub acknowledgment_id: StableString,
    pub build_digest: ValueDigest,
    pub session_id: StableString,
    pub profile_digest: ValueDigest,
    pub reduced_navigation_burden: bool,
    pub preserved_orientation: bool,
    pub worth_reopening: bool,
    pub acknowledged_at: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EmberUseSessionV1 {
    pub session_id: StableString,
    pub build_digest: ValueDigest,
    pub profile_digest: ValueDigest,
    pub supported_critical_tasks: BTreeSet<StableString>,
    pub switched_away_for_parity_gap: bool,
    pub switch_reason: Option<SwitchAwayReason>,
    pub fixture_rendered: bool,
    pub live_read_only: bool,
    pub evidence: Vec<QualificationEvidenceRefV1>,
    pub acknowledgment: EmberUseAcknowledgmentV1,
}

impl EmberUseSessionV1 {
    /// Compact canonical session bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the session cannot be encoded.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, SurfaceError> {
        Ok(serde_json::to_vec(self)?)
    }
}

/// Typed reason for leaving Glass; arbitrary text cannot manufacture a parity witness.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SwitchAwayReason {
    ManualExecution,
    RecordedParityGap,
}

/// Exact durable witness category for an independent cockpit capability.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QualificationEvidenceKind {
    FixtureRender,
    LiveReadOnly,
    Accessibility,
}

/// Typed receipt binding an Ember-use capability to immutable evidence bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidenceRefV1 {
    pub contract: StableString,
    pub kind: QualificationEvidenceKind,
    pub evidence_id: StableString,
    pub evidence_digest: ValueDigest,
}

/// Independent S2 maturity; does not include clicks, dwell, trades or profit.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CockpitQualification {
    FixtureRendered,
    LiveReadOnly,
    PreliminaryEmberUse,
    RepeatedEmberUse,
    CriticalTasksAccessible,
}

/// Product qualification result, with each attained capability independently visible.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationResultV1 {
    pub profile_digest: ValueDigest,
    pub capabilities: BTreeSet<CockpitQualification>,
    pub session_ids: Vec<StableString>,
    pub status: StableString,
    pub verified: bool,
    pub ceiling: QualificationCeiling,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QualificationCeiling {
    UnverifiedSemantic,
}

/// Constructor helper for profile material, used by fixtures and integrators.
pub fn make_profile_digest(
    profile: &DailyUseSurfaceProfileV1,
) -> Result<ValueDigest, SurfaceError> {
    profile.computed_digest()
}

/// Constructor helper for exact profile header.
pub fn profile_header(
    profile_id: &str,
    version: u64,
    approval: &str,
    _approved_at: UtcTimestamp,
) -> Result<(StableString, WireU64, StableString, StableString), SurfaceError> {
    Ok((
        stable(profile_id)?,
        WireU64::new(version),
        stable(approval)?,
        stable(READ_ONLY_AUTHORITY)?,
    ))
}
