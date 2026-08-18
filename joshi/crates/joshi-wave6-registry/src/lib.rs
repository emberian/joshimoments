//! Fixture-only authority and artifact-registry contracts for Wave 6.
//!
//! This crate implements the pre-`W5-G1` portion of `N00/W6-0`. It validates exact canonical
//! program-registration bytes and their internal digest closure. Public success is always
//! [`SemanticCeilingV1::UnverifiedSemanticFixtureOnly`]. The crate has no store dependency,
//! receipt type, migration, provider client, mutable path, presentation hook, or economic API.
//! A future sole-store adapter must resolve every consumed Wave 5 gate before any operational
//! Wave 6 release can exist.

#![forbid(unsafe_code)]

mod canonical;
mod error;
mod model;
mod validate;

pub use canonical::{
    ValidatedProgramRegistration, canonical_bytes, digest_bytes, parse_program_registration_exact,
};
pub use error::{RegistryError, Result};
pub use model::{
    ArtifactKindRegistrationV1, ClaimRungV1, DataPolicyV1, DeskOperationV1, FixtureMaturityV1,
    LocalSymbolV1, ProgramAuthorityV1, ProgramBudgetsV1, ProgramRegistrationDigestMaterialV1,
    SemanticCeilingV1, Wave5GateRefV1, Wave5GateV1, Wave6ProgramRegistrationV1,
};

/// Exact wire contract for the fixture-only Wave 6 program registration.
pub const PROGRAM_REGISTRATION_CONTRACT: &str = "joshi.wave6.program-registration.v1";

#[cfg(test)]
mod tests;
