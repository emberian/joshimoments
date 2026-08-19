//! Pure source, privacy, cost, and bounded-run contracts for Wave 5 acquisition.
//!
//! This crate deliberately has no transport, credential, filesystem, store, wallet, or async
//! dependency. It validates source declarations and reserves an independently bounded run budget;
//! a collector may use those results as a narrow pre-I/O port. A valid declaration is not proof of
//! provider availability, quota remaining, or coverage.

mod budget;
mod contract;
mod error;
mod profiles;

pub use budget::{
    BudgetReservation, BudgetUsage, CostEstimate, ReservationScope, RunBudget, RunBudgetSnapshot,
};
pub use contract::{
    AbsenceSemantics, AccessClass, BillingPolicy, BillingUnit, Commitment, CredentialAuthority,
    CredentialDescriptor, FieldAuthority, FieldContract, FieldKind, FinalityPolicy, GapSemantics,
    KillSwitch, MethodContract, MethodKind, PUBLIC_SOLANA_MAINNET_SOURCE_ID,
    PUBLIC_SOLANA_SIGNATURES_METHOD_KEY, ProgressSemantics, ProtectionClass, QuotaReset, QuotaSpec,
    RetentionClass, RetryPolicy, SchemaFingerprint, SourceContract, SourceContractBuilder,
    SourceRegistry, SourceRegistryBuilder, SourceStatus, ZeroPriceAttestation,
    public_solana_mainnet_contract, pumpportal_contract,
};
pub use error::RegistryError;
pub use profiles::{CanaryProfile, PlanningProfile, planning_profiles};

/// Stable wire contract for this crate.
pub const REGISTRY_CONTRACT: &str = "joshi.source_registry/v1";
/// Current schema version.
pub const REGISTRY_SCHEMA_VERSION: u64 = 1;

#[cfg(test)]
mod tests;
