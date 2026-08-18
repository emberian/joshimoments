use joshi_domain::StableString;
use serde::{Deserialize, Serialize};

use crate::{BudgetUsage, RegistryError, RunBudget};

/// Offline-to-metered acquisition planning ladder. Profiles are declarations, not permission to
/// perform I/O; an integrator must register one exact profile with a run before reserving work.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CanaryProfile {
    C0,
    C1,
    C2,
    C3,
    C4,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PlanningProfile {
    pub profile: CanaryProfile,
    pub name: String,
    pub duration_seconds: u64,
    pub max_ingress_bytes_per_day: u64,
    pub max_durable_bytes_per_day: u64,
    pub budget: BudgetUsage,
}

impl PlanningProfile {
    /// # Errors
    ///
    /// Returns an all-zero or otherwise invalid run-cap refusal.
    pub fn run_budget(&self) -> Result<RunBudget, RegistryError> {
        Err(RegistryError::InvalidValue("run registration required"))
    }

    /// Binds the planning ceiling to the exact registered run occurrence before I/O.
    ///
    /// # Errors
    ///
    /// Returns an invalid-run or empty-cap refusal.
    pub fn registered_run_budget(&self, run_id: StableString) -> Result<RunBudget, RegistryError> {
        RunBudget::with_run_id(run_id, self.budget.clone())
    }
}

/// Frozen C0-C4 planning values from W5-A4. Numeric values are hard ceilings for a run, never an
/// invoice, quota expansion, or economic authority.
#[must_use]
pub fn planning_profiles() -> Vec<PlanningProfile> {
    vec![
        profile(
            CanaryProfile::C0,
            "offline_fake_source_walk",
            3_600,
            (64 * 1024 * 1024, 64 * 1024 * 1024, 1_000, 1_000, 0),
        ),
        profile(
            CanaryProfile::C1,
            "one_public_conformance_page",
            60,
            (64 * 1024 * 1024, 64 * 1024 * 1024, 25, 25, 250),
        ),
        profile(
            CanaryProfile::C2,
            "compact_census_bakeoff",
            3_600,
            (256 * 1024 * 1024, 128 * 1024 * 1024, 10_000, 10_000, 10_000),
        ),
        profile(
            CanaryProfile::C3,
            "six_hour_selective",
            6 * 3_600,
            (512 * 1024 * 1024, 256 * 1024 * 1024, 25_000, 25_000, 25_000),
        ),
        profile(
            CanaryProfile::C4,
            "seventy_two_hour_selective",
            72 * 3_600,
            (2_000_000_000, 1_000_000_000, 100_000, 100_000, 100_000),
        ),
    ]
}

fn profile(
    profile: CanaryProfile,
    name: &str,
    duration_seconds: u64,
    limits: (u64, u64, u64, u64, u64),
) -> PlanningProfile {
    let (ingress, durable, requests, pages, credits) = limits;
    let budget = BudgetUsage {
        requests,
        pages,
        ingress_bytes: ingress,
        durable_bytes: durable,
        provider_credits: credits,
        wall_millis: duration_seconds.saturating_mul(1_000),
        ..BudgetUsage::default()
    };
    PlanningProfile {
        profile,
        name: name.to_owned(),
        duration_seconds,
        max_ingress_bytes_per_day: ingress,
        max_durable_bytes_per_day: durable,
        budget,
    }
}
