//! Fixture-only authority and artifact-registry contracts for Wave 6.
//!
//! This crate implements the pre-`W5-G1` portion of `N00/W6-0`. It validates exact canonical
//! program-registration bytes and their internal digest closure. Public success is always
//! [`SemanticCeilingV1::UnverifiedSemanticFixtureOnly`]. The crate has no store dependency,
//! receipt type, migration, provider client, mutable path, presentation hook, or economic API.
//! A future sole-store adapter must resolve every consumed Wave 5 gate before any operational
//! Wave 6 release can exist.

#![forbid(unsafe_code)]

mod campaign;
mod canonical;
mod claim;
mod dag;
mod decision;
mod error;
mod model;
mod validate;

pub use campaign::{
    CampaignLifecycleDigestMaterialV1, CampaignLifecycleV1, CampaignStateV1, CampaignTransitionV1,
};
pub use canonical::{
    ValidatedExactArtifact, ValidatedProgramRegistration, canonical_bytes, digest_bytes,
    parse_artifact_dag_exact, parse_campaign_lifecycle_exact, parse_decision_ledger_exact,
    parse_program_registration_exact,
};
pub use claim::{
    ClaimCausalityV1, ClaimEconomicMeaningV1, ClaimIdentityMeaningV1, ClaimLanguageV1, ClaimVerbV1,
    UnverifiedClaimLanguage, validate_claim_language,
};
pub use dag::{ArtifactDagDigestMaterialV1, ArtifactDagV1, ArtifactOccurrenceV1, ArtifactRefV1};
pub use decision::{
    ArtifactDecisionKindV1, ArtifactDecisionV1, FixtureDecisionLedgerDigestMaterialV1,
    FixtureDecisionLedgerV1,
};
pub use error::{RegistryError, Result};
pub use model::{
    ArtifactKindRegistrationV1, ClaimRungV1, DataPolicyV1, DeskOperationV1, FixtureMaturityV1,
    LocalSymbolV1, ProgramAuthorityV1, ProgramBudgetsV1, ProgramRegistrationDigestMaterialV1,
    SemanticCeilingV1, Wave5GateRefV1, Wave5GateV1, Wave6ProgramRegistrationV1,
};

/// Exact wire contract for the fixture-only Wave 6 program registration.
pub const PROGRAM_REGISTRATION_CONTRACT: &str = "joshi.wave6.program-registration.v1";
/// Exact wire contract for a fixture-only artifact DAG.
pub const ARTIFACT_DAG_CONTRACT: &str = "joshi.wave6.artifact-dag.v1";
/// Exact wire contract for append-only fixture dispositions.
pub const FIXTURE_DECISION_LEDGER_CONTRACT: &str = "joshi.wave6.fixture-decision-ledger.v1";
/// Exact wire contract for a caller-fed fixture campaign lifecycle.
pub const CAMPAIGN_LIFECYCLE_CONTRACT: &str = "joshi.wave6.campaign-lifecycle.v1";

#[cfg(test)]
mod tests;
