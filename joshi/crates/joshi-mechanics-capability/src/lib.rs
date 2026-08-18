//! Bounded, read-only Wave 5 mechanics capability evidence.
//!
//! A registry is deliberately only a semantic status index. It owns no store, source client,
//! transaction builder, signer, wallet, or execution authority. In particular, this crate never
//! infers one capability from another: a simulation is not an attempt, a quote is not a fill, and
//! a full-position quote is not a terminal close.

#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{
    AsOfVector, CoverageId, ObservationId, PositionId, ProtocolProfileId, QuoteId, SourceId,
    StableString, ValueDigest,
};
use joshi_market_math::profile::{ProtocolFamily, ProtocolProfile};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Stable semantic contract for this pure capability index.
pub const MECHANICS_CAPABILITY_CONTRACT: &str = "joshi.mechanics_capability.v1";

/// Authority ceiling of every value this crate can construct.
///
/// A caller can construct a semantic preflight row, but only a store/source adapter may later
/// qualify it as durable witnessed evidence. This crate has no such adapter.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceAuthority {
    UnverifiedSemantic,
}

/// One independently attainable mechanics object.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityKind {
    ExactMath,
    CoherentRealState,
    Mark,
    MarginalQuote,
    SizeQuote,
    ObservedSimulation,
    ObservedAttempt,
    LandedFillOrFailure,
    WholePositionLiquidation,
    TerminalPositionClosure,
    Publication,
    Calibration,
}

impl CapabilityKind {
    /// All kinds in the contract, in their stable wire order.
    pub const ALL: [Self; 12] = [
        Self::ExactMath,
        Self::CoherentRealState,
        Self::Mark,
        Self::MarginalQuote,
        Self::SizeQuote,
        Self::ObservedSimulation,
        Self::ObservedAttempt,
        Self::LandedFillOrFailure,
        Self::WholePositionLiquidation,
        Self::TerminalPositionClosure,
        Self::Publication,
        Self::Calibration,
    ];
}

/// Human-readable profile identity copied from the exact market-math profile.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProfileIdentity {
    pub profile_id: ProtocolProfileId,
    pub venue_id: joshi_domain::VenueId,
    pub family: ProtocolFamilyName,
    pub program_identity: StableString,
    pub source_revision: StableString,
}

impl From<&ProtocolProfile> for ProfileIdentity {
    fn from(profile: &ProtocolProfile) -> Self {
        Self {
            profile_id: profile.id.clone(),
            venue_id: profile.venue.clone(),
            family: profile.family.into(),
            program_identity: profile.program_identity.clone(),
            source_revision: profile.source_revision.clone(),
        }
    }
}

/// Serializable name for a market-math protocol family.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtocolFamilyName {
    PumpCurve,
    PumpSwapCanonical,
    PumpSwapNonCanonical,
    MeteoraDlmm,
}

impl From<ProtocolFamily> for ProtocolFamilyName {
    fn from(value: ProtocolFamily) -> Self {
        match value {
            ProtocolFamily::PumpCurve => Self::PumpCurve,
            ProtocolFamily::PumpSwapCanonical => Self::PumpSwapCanonical,
            ProtocolFamily::PumpSwapNonCanonical => Self::PumpSwapNonCanonical,
            ProtocolFamily::MeteoraDlmm => Self::MeteoraDlmm,
        }
    }
}

/// Finality attached to the evidence horizon. It is not inferred from a status name.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum Finality {
    Finalized,
    Confirmed,
    Processed,
    Unknown { reason: StableString },
}

impl Finality {
    fn is_finalized(&self) -> bool {
        matches!(self, Self::Finalized)
    }

    fn is_known(&self) -> bool {
        !matches!(self, Self::Unknown { .. })
    }
}

/// Coverage for the exact source/profile observation, including named gaps.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum CoverageState {
    Complete,
    Partial { reason: StableString },
    Gap { reason: StableString },
    Conflicting { reason: StableString },
    Unknown { reason: StableString },
}

impl CoverageState {
    fn is_complete(&self) -> bool {
        matches!(self, Self::Complete)
    }
}

/// Point-in-time coverage and finality closure. `as_of` remains the source of clock truth.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceHorizon {
    pub as_of: AsOfVector,
    pub finality: Finality,
    pub coverage: CoverageState,
    pub coverage_ids: Vec<CoverageId>,
}

impl EvidenceHorizon {
    /// Constructs a horizon, rejecting contradictory coverage IDs.
    ///
    /// # Errors
    ///
    /// Returns [`HorizonError`] when IDs contradict the declared coverage state.
    pub fn new(
        as_of: AsOfVector,
        finality: Finality,
        coverage: CoverageState,
        mut coverage_ids: Vec<CoverageId>,
    ) -> Result<Self, HorizonError> {
        coverage_ids.sort();
        if coverage_ids.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(HorizonError::DuplicateCoverage);
        }
        if coverage.is_complete() && !coverage_ids.is_empty() {
            return Err(HorizonError::CompleteWithGaps);
        }
        if matches!(coverage, CoverageState::Gap { .. }) && coverage_ids.is_empty() {
            return Err(HorizonError::GapWithoutId);
        }
        Ok(Self {
            as_of,
            finality,
            coverage,
            coverage_ids,
        })
    }

    /// Returns whether this horizon can support a strict finalized claim.
    #[must_use]
    pub fn supports_finalized_complete_claim(&self) -> bool {
        self.finality.is_finalized() && self.coverage.is_complete()
    }
}

/// Invalid horizon relationship.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum HorizonError {
    #[error("coverage IDs are duplicated")]
    DuplicateCoverage,
    #[error("complete coverage cannot carry gap IDs")]
    CompleteWithGaps,
    #[error("a gap coverage state requires at least one named gap ID")]
    GapWithoutId,
}

/// IDs that make an evidence occurrence auditable without pretending it is a transaction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceBinding {
    pub source_id: SourceId,
    pub profile_id: ProtocolProfileId,
    pub state_observation_id: Option<ObservationId>,
    pub quote_id: Option<QuoteId>,
    pub attempt_id: Option<StableString>,
    pub fill_id: Option<StableString>,
    pub failure_id: Option<StableString>,
    pub liquidation_id: Option<StableString>,
    pub position_id: Option<PositionId>,
    pub publication_id: Option<StableString>,
    pub calibration_id: Option<StableString>,
    pub terminal_closure_id: Option<StableString>,
    pub horizon: EvidenceHorizon,
    /// Build/source digest is descriptive provenance, never an authority token.
    pub source_digest: Option<ValueDigest>,
}

impl EvidenceBinding {
    /// Validates occurrence IDs required by one capability, without checking its registry entry.
    ///
    /// # Errors
    ///
    /// Returns [`BindingError`] when a required occurrence ID or source/as-of join is absent.
    pub fn validate_for(&self, kind: CapabilityKind) -> Result<(), BindingError> {
        if matches!(
            kind,
            CapabilityKind::ExactMath
                | CapabilityKind::CoherentRealState
                | CapabilityKind::Mark
                | CapabilityKind::ObservedSimulation
                | CapabilityKind::WholePositionLiquidation
                | CapabilityKind::TerminalPositionClosure
        ) && self.state_observation_id.is_none()
        {
            return Err(BindingError::MissingId("state_observation_id"));
        }
        if matches!(kind, CapabilityKind::ExactMath) && self.source_digest.is_none() {
            return Err(BindingError::MissingId("exact_profile_build_digest"));
        }
        let needs_quote = matches!(
            kind,
            CapabilityKind::MarginalQuote | CapabilityKind::SizeQuote
        );
        if needs_quote && self.quote_id.is_none() {
            return Err(BindingError::MissingId("quote_id"));
        }
        if matches!(kind, CapabilityKind::ObservedAttempt) && self.attempt_id.is_none() {
            return Err(BindingError::MissingId("attempt_id"));
        }
        if matches!(kind, CapabilityKind::LandedFillOrFailure)
            && (self.attempt_id.is_none() || (self.fill_id.is_none() && self.failure_id.is_none()))
        {
            return Err(BindingError::MissingAttemptAndOutcome);
        }
        if matches!(kind, CapabilityKind::WholePositionLiquidation)
            && (self.quote_id.is_none() || self.liquidation_id.is_none())
        {
            return Err(BindingError::MissingQuoteAndLiquidation);
        }
        if matches!(kind, CapabilityKind::TerminalPositionClosure)
            && (self.liquidation_id.is_none()
                || self.position_id.is_none()
                || self.terminal_closure_id.is_none())
        {
            return Err(BindingError::MissingLiquidationPositionAndTerminalReceipt);
        }
        if matches!(kind, CapabilityKind::Publication) && self.publication_id.is_none() {
            return Err(BindingError::MissingId("publication_id"));
        }
        if matches!(kind, CapabilityKind::Calibration) && self.calibration_id.is_none() {
            return Err(BindingError::MissingId("calibration_id"));
        }
        if !self.horizon.as_of.sources.contains_key(&self.source_id) {
            return Err(BindingError::SourceAbsentFromAsOf);
        }
        Ok(())
    }
}

/// Invalid identity closure for a capability occurrence.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum BindingError {
    #[error("required occurrence ID is missing: {0}")]
    MissingId(&'static str),
    #[error("landed evidence requires both attempt_id and fill_id")]
    MissingAttemptAndOutcome,
    #[error("whole-position liquidation requires quote_id and liquidation_id")]
    MissingQuoteAndLiquidation,
    #[error("terminal closure requires liquidation_id and position_id")]
    MissingLiquidationPositionAndTerminalReceipt,
    #[error("the bound source is absent from the as-of source vector")]
    SourceAbsentFromAsOf,
}

/// Why a requested capability did not produce a positive observation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum RefusalReason {
    MissingEvidence,
    IncoherentState,
    UnsupportedProfile,
    UnsupportedSize,
    NonFinalEvidence,
    CoverageGap,
    ProviderRefusal,
    NotObserved,
    Other {
        code: StableString,
        detail: Option<StableString>,
    },
}

/// Independent state for one capability; variants do not imply any other variant.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum EvidenceStatus {
    Attained,
    Refused { reason: RefusalReason },
    PendingOpportunity,
    Unavailable { reason: RefusalReason },
}

impl EvidenceStatus {
    fn is_attained(&self) -> bool {
        matches!(self, Self::Attained)
    }
}

/// One immutable semantic capability row.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapabilityEvidence {
    pub authority: EvidenceAuthority,
    pub kind: CapabilityKind,
    pub status: EvidenceStatus,
    pub binding: EvidenceBinding,
}

/// Explicit spelling for callers that want to carry the crate's authority ceiling in a type name.
pub type UnverifiedSemanticCapabilityEvidence = CapabilityEvidence;

impl CapabilityEvidence {
    /// Builds an occurrence after checking its IDs and source/as-of join.
    ///
    /// # Errors
    ///
    /// Returns [`BindingError`] when the evidence binding does not close the named capability.
    pub fn new(
        kind: CapabilityKind,
        status: EvidenceStatus,
        binding: EvidenceBinding,
    ) -> Result<Self, BindingError> {
        binding.validate_for(kind)?;
        Ok(Self {
            authority: EvidenceAuthority::UnverifiedSemantic,
            kind,
            status,
            binding,
        })
    }
}

/// One registered profile and its independent capability rows.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MechanicsProfile {
    pub profile: ProfileIdentity,
    pub source_id: SourceId,
    pub capabilities: BTreeMap<CapabilityKind, CapabilityEvidence>,
}

/// Pure per-profile capability registry. It has no durable/store authority.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MechanicsCapabilityRegistry {
    profiles: BTreeMap<ProtocolProfileId, MechanicsProfile>,
}

/// Explicitly unverified name for this pure registry; the shorter alias remains ergonomic.
pub type UnverifiedSemanticMechanicsCapabilityRegistry = MechanicsCapabilityRegistry;

impl MechanicsCapabilityRegistry {
    /// Registers one profile/source pair. Registration does not grant any capability.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError::DuplicateProfile`] when the profile is already registered.
    pub fn register_profile(
        &mut self,
        profile: &ProtocolProfile,
        source_id: SourceId,
    ) -> Result<(), RegistryError> {
        let identity = ProfileIdentity::from(profile);
        if self.profiles.contains_key(&identity.profile_id) {
            return Err(RegistryError::DuplicateProfile);
        }
        self.profiles.insert(
            identity.profile_id.clone(),
            MechanicsProfile {
                profile: identity,
                source_id,
                capabilities: BTreeMap::new(),
            },
        );
        Ok(())
    }

    /// Records/replaces only the named capability; no ladder or transitive inference is run.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError`] when the profile, source, binding, or finality closure is invalid.
    pub fn record(&mut self, evidence: CapabilityEvidence) -> Result<(), RegistryError> {
        let profile = self
            .profiles
            .get_mut(&evidence.binding.profile_id)
            .ok_or(RegistryError::UnknownProfile)?;
        if profile.source_id != evidence.binding.source_id {
            return Err(RegistryError::SourceProfileMismatch);
        }
        evidence
            .binding
            .validate_for(evidence.kind)
            .map_err(RegistryError::Binding)?;
        if matches!(evidence.status, EvidenceStatus::Attained)
            && !evidence.binding.horizon.finality.is_known()
        {
            return Err(RegistryError::UnknownFinality);
        }
        profile.capabilities.insert(evidence.kind, evidence);
        Ok(())
    }

    /// Returns a profile's semantic rows. Nothing is derived on read.
    #[must_use]
    pub fn profile(&self, profile_id: &ProtocolProfileId) -> Option<&MechanicsProfile> {
        self.profiles.get(profile_id)
    }

    /// Returns all registered profiles in canonical profile-ID order.
    pub fn profiles(&self) -> impl Iterator<Item = &MechanicsProfile> {
        self.profiles.values()
    }

    /// Returns a single independent row.
    #[must_use]
    pub fn capability(
        &self,
        profile_id: &ProtocolProfileId,
        kind: CapabilityKind,
    ) -> Option<&CapabilityEvidence> {
        self.profiles
            .get(profile_id)
            .and_then(|profile| profile.capabilities.get(&kind))
    }

    /// Checks named requirements and reports every failed join without changing the registry.
    #[must_use]
    pub fn check_prerequisites(&self, requirements: &[ClaimPrerequisite]) -> ClaimCheck {
        let mut failures = Vec::new();
        for requirement in requirements {
            let Some(profile) = self.profiles.get(&requirement.profile_id) else {
                failures.push(PrerequisiteFailure::UnknownProfile {
                    profile_id: requirement.profile_id.clone(),
                    capability: requirement.capability,
                });
                continue;
            };
            let Some(evidence) = profile.capabilities.get(&requirement.capability) else {
                failures.push(PrerequisiteFailure::Missing {
                    profile_id: requirement.profile_id.clone(),
                    capability: requirement.capability,
                });
                continue;
            };
            if !evidence.status.is_attained() {
                failures.push(PrerequisiteFailure::Status {
                    profile_id: requirement.profile_id.clone(),
                    capability: requirement.capability,
                    status: evidence.status.clone(),
                });
                continue;
            }
            if requirement.require_finalized && !evidence.binding.horizon.finality.is_finalized() {
                failures.push(PrerequisiteFailure::Finality {
                    profile_id: requirement.profile_id.clone(),
                    capability: requirement.capability,
                });
            }
            if requirement.require_complete_coverage
                && !evidence.binding.horizon.coverage.is_complete()
            {
                failures.push(PrerequisiteFailure::Coverage {
                    profile_id: requirement.profile_id.clone(),
                    capability: requirement.capability,
                });
            }
        }
        ClaimCheck { failures }
    }
}

/// A named prerequisite; every capability must be listed explicitly by a consuming claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClaimPrerequisite {
    pub profile_id: ProtocolProfileId,
    pub capability: CapabilityKind,
    pub require_finalized: bool,
    pub require_complete_coverage: bool,
}

impl ClaimPrerequisite {
    /// Strict prerequisite suitable for executable-price or accounting claims.
    #[must_use]
    pub const fn strict(profile_id: ProtocolProfileId, capability: CapabilityKind) -> Self {
        Self {
            profile_id,
            capability,
            require_finalized: true,
            require_complete_coverage: true,
        }
    }

    /// A capability-only prerequisite, useful for descriptive read-side claims.
    #[must_use]
    pub const fn attained(profile_id: ProtocolProfileId, capability: CapabilityKind) -> Self {
        Self {
            profile_id,
            capability,
            require_finalized: false,
            require_complete_coverage: false,
        }
    }
}

/// Failed prerequisite joins. All failures are retained; none are collapsed into a scalar gate.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub enum PrerequisiteFailure {
    UnknownProfile {
        profile_id: ProtocolProfileId,
        capability: CapabilityKind,
    },
    Missing {
        profile_id: ProtocolProfileId,
        capability: CapabilityKind,
    },
    Status {
        profile_id: ProtocolProfileId,
        capability: CapabilityKind,
        status: EvidenceStatus,
    },
    Finality {
        profile_id: ProtocolProfileId,
        capability: CapabilityKind,
    },
    Coverage {
        profile_id: ProtocolProfileId,
        capability: CapabilityKind,
    },
}

/// Result of a semantic prerequisite preflight. This does not qualify a durable claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClaimCheck {
    pub failures: Vec<PrerequisiteFailure>,
}

/// Explicitly unverified spelling for semantic preflight results.
pub type UnverifiedSemanticClaimCheck = ClaimCheck;

impl ClaimCheck {
    #[must_use]
    pub const fn semantically_satisfied(&self) -> bool {
        self.failures.is_empty()
    }
}

/// Registry construction/recording failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum RegistryError {
    #[error("profile is already registered")]
    DuplicateProfile,
    #[error("capability refers to an unregistered profile")]
    UnknownProfile,
    #[error("capability source does not match the profile source")]
    SourceProfileMismatch,
    #[error("capability binding is invalid: {0}")]
    Binding(BindingError),
    #[error("attained capability has unknown finality")]
    UnknownFinality,
}

/// The subset of identifiers used by a status row, convenient for audits and tests.
#[must_use]
pub fn bound_ids(evidence: &CapabilityEvidence) -> BTreeSet<StableString> {
    let mut ids = BTreeSet::new();
    for value in [
        evidence.binding.attempt_id.clone(),
        evidence.binding.fill_id.clone(),
        evidence.binding.liquidation_id.clone(),
        evidence.binding.publication_id.clone(),
        evidence.binding.calibration_id.clone(),
    ]
    .into_iter()
    .flatten()
    {
        ids.insert(value);
    }
    ids
}

#[cfg(test)]
mod tests;
