//! Strict H0-H5 claim-language grammar.

use joshi_domain::StableString;
use serde::{Deserialize, Serialize};

use crate::{
    ClaimRungV1, ProgramAuthorityV1, RegistryError, Result, SemanticCeilingV1,
    Wave6ProgramRegistrationV1,
};

/// Exact permitted statement family for one scientific rung.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimVerbV1 {
    /// H0: a declared finalized boundary fact.
    DeclaredBoundaryFact,
    /// H1: exact profiled deterministic result or refusal.
    DeterministicResultOrRefusal,
    /// H2: observation-policy-scoped description.
    ObservationPolicyScopedDescription,
    /// H3: calibrated conditional estimate, not cause.
    CalibratedConditionalEstimate,
    /// H4: compatible equivalence class, not identity.
    CompatibleEquivalenceClass,
    /// H5: read-only hypothetical proposal.
    HypotheticalReadOnlyProposal,
}

/// Causal meaning is unavailable to the fixture registry.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimCausalityV1 {
    /// No causal identification or effect claim.
    NotClaimed,
}

/// Identity meaning of a claim.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimIdentityMeaningV1 {
    /// No identity/intent inference.
    NotClaimed,
    /// H4-only observational equivalence class.
    CompatibleEquivalenceClassOnly,
}

/// Economic meaning is permanently absent at this boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimEconomicMeaningV1 {
    /// No profit, advantage, execution, or asset-authority claim.
    NoEconomicAuthorityOrProfitClaim,
}

/// Machine-readable claim statement bound to one registered artifact kind.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClaimLanguageV1 {
    /// Claim statement identity.
    pub claim_id: StableString,
    /// Artifact occurrence to which the statement applies.
    pub artifact_id: StableString,
    /// Registered artifact kind.
    pub artifact_kind_id: StableString,
    /// Exact registered permissible statement, not free-form prose.
    pub statement: StableString,
    /// Scientific rung.
    pub rung: ClaimRungV1,
    /// Rung-specific statement family.
    pub verb: ClaimVerbV1,
    /// Causal meaning.
    pub causality: ClaimCausalityV1,
    /// Identity meaning.
    pub identity_meaning: ClaimIdentityMeaningV1,
    /// Economic meaning.
    pub economic_meaning: ClaimEconomicMeaningV1,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
}

/// Intrinsically valid but caller-fed claim language.
#[derive(Clone, Debug)]
pub struct UnverifiedClaimLanguage(ClaimLanguageV1);

impl UnverifiedClaimLanguage {
    /// Returns the intrinsically validated statement.
    #[must_use]
    pub const fn value(&self) -> &ClaimLanguageV1 {
        &self.0
    }

    /// Public success remains unverified fixture semantics.
    #[must_use]
    pub const fn semantic_ceiling(&self) -> SemanticCeilingV1 {
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    }
}

fn expected_verb(rung: ClaimRungV1) -> ClaimVerbV1 {
    match rung {
        ClaimRungV1::H0Settlement => ClaimVerbV1::DeclaredBoundaryFact,
        ClaimRungV1::H1ProtocolKinematics => ClaimVerbV1::DeterministicResultOrRefusal,
        ClaimRungV1::H2Descriptive => ClaimVerbV1::ObservationPolicyScopedDescription,
        ClaimRungV1::H3Fitted => ClaimVerbV1::CalibratedConditionalEstimate,
        ClaimRungV1::H4LatentAbductive => ClaimVerbV1::CompatibleEquivalenceClass,
        ClaimRungV1::H5Policy => ClaimVerbV1::HypotheticalReadOnlyProposal,
    }
}

/// Validates one typed claim against its exact registered artifact kind.
///
/// # Errors
///
/// Refuses unknown kinds, rung/verb substitution, arbitrary wording, identity laundering, or
/// authority widening. Success remains caller-fed fixture semantics.
pub fn validate_claim_language(
    registration: &Wave6ProgramRegistrationV1,
    claim: ClaimLanguageV1,
) -> Result<UnverifiedClaimLanguage> {
    let kind = registration
        .artifact_kinds
        .binary_search_by(|kind| kind.kind_id.cmp(&claim.artifact_kind_id))
        .ok()
        .map(|index| &registration.artifact_kinds[index])
        .ok_or(RegistryError::ClaimLanguage)?;
    let expected_identity = if claim.rung == ClaimRungV1::H4LatentAbductive {
        ClaimIdentityMeaningV1::CompatibleEquivalenceClassOnly
    } else {
        ClaimIdentityMeaningV1::NotClaimed
    };
    if claim.rung != kind.claim_rung
        || claim.verb != expected_verb(claim.rung)
        || claim.statement != kind.permitted_claim
        || claim.causality != ClaimCausalityV1::NotClaimed
        || claim.identity_meaning != expected_identity
        || claim.economic_meaning != ClaimEconomicMeaningV1::NoEconomicAuthorityOrProfitClaim
        || claim.authority != registration.authority
        || claim.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(RegistryError::ClaimLanguage);
    }
    Ok(UnverifiedClaimLanguage(claim))
}
