use crate::model::{
    DegradationCause, DegradationStage, OperationalHealthV1, ResourceKind, StatusClass,
};
use crate::{OperationalError, Result};
use joshi_domain::{StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

/// Versioned deterministic degradation policy contract.
pub const DEGRADATION_POLICY_CONTRACT: &str = "joshi.operational.degradation_policy/v1";
const ONE_MILLION: u64 = 1_000_000;

/// Pressure thresholds in parts per million of usable capacity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DegradationPolicyV1 {
    pub contract: String,
    pub policy_id: StableString,
    pub optional_media_at_ppm: WireU64,
    pub slow_social_at_ppm: WireU64,
    pub reduce_hot_scopes_at_ppm: WireU64,
    pub census_only_at_ppm: WireU64,
    pub stop_before_reserve_at_ppm: WireU64,
    /// Drain/arrival ratio target in ppm. `2_000_000` means at least two times arrival.
    pub recovery_drain_to_arrival_ppm: WireU64,
}

impl DegradationPolicyV1 {
    /// Validates strict threshold order and the recovery drain target.
    ///
    /// # Errors
    ///
    /// Refuses reordered stages, thresholds outside usable capacity, or a recovery target below
    /// one-to-one drain.
    pub fn validate(&self) -> Result<()> {
        if self.contract != DEGRADATION_POLICY_CONTRACT {
            return Err(OperationalError::Contract {
                expected: DEGRADATION_POLICY_CONTRACT,
                received: self.contract.clone(),
            });
        }
        let thresholds = [
            self.optional_media_at_ppm.get(),
            self.slow_social_at_ppm.get(),
            self.reduce_hot_scopes_at_ppm.get(),
            self.census_only_at_ppm.get(),
            self.stop_before_reserve_at_ppm.get(),
        ];
        if thresholds.windows(2).any(|pair| pair[0] >= pair[1]) || thresholds[4] > ONE_MILLION {
            return Err(OperationalError::Invalid(
                "degradation thresholds must be strictly increasing and no greater than 1_000_000 ppm",
            ));
        }
        if self.recovery_drain_to_arrival_ppm.get() < ONE_MILLION {
            return Err(OperationalError::Invalid(
                "recovery drain target cannot be below admitted arrival rate",
            ));
        }
        Ok(())
    }
}

/// Pure degradation decision; adapters persist the resulting policy occurrence separately.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DegradationDecisionV1 {
    pub policy_id: StableString,
    pub pressure_ppm: WireU64,
    pub stage: DegradationStage,
    pub causes: Vec<DegradationCause>,
}

/// Evaluates queue/spool/budget/resource pressure without mutating a collector.
///
/// # Errors
///
/// Returns an error when either the policy or health snapshot is invalid.
pub fn evaluate_degradation(
    policy: &DegradationPolicyV1,
    health: &OperationalHealthV1,
    health_contract: &'static str,
) -> Result<DegradationDecisionV1> {
    policy.validate()?;
    health.validate(health_contract)?;
    let record_pressure = capacity_pressure_ppm(
        health.evidence_queue.records.used.get(),
        health.evidence_queue.records.maximum.get(),
        health.evidence_queue.records.control_reserve.get(),
    );
    let byte_pressure = capacity_pressure_ppm(
        health.evidence_queue.bytes.used.get(),
        health.evidence_queue.bytes.maximum.get(),
        health.evidence_queue.bytes.control_reserve.get(),
    );
    let spool_pressure = capacity_pressure_ppm(
        health.spool.used_bytes.get(),
        health.spool.maximum_bytes.get(),
        health.spool.control_reserve_bytes.get(),
    );
    let budget_pressure = health
        .budgets
        .iter()
        .map(|budget| consumed_ppm(budget.used.get(), budget.authorized.get()))
        .max()
        .unwrap_or(0);
    let pressure = record_pressure
        .max(byte_pressure)
        .max(spool_pressure)
        .max(budget_pressure);
    let mut causes = BTreeSet::new();
    if record_pressure >= policy.optional_media_at_ppm.get()
        || byte_pressure >= policy.optional_media_at_ppm.get()
    {
        causes.insert(DegradationCause::QueuePressure);
    }
    if spool_pressure >= policy.optional_media_at_ppm.get() {
        causes.insert(DegradationCause::SpoolPressure);
    }
    let mut hard_stop = health.evidence_queue.saturation.currently_saturated;
    for resource in &health.resources {
        match resource.kind {
            ResourceKind::DiskFreeBytes | ResourceKind::DiskFreeInodes => {
                if resource.observed.get() <= resource.limit_or_floor.get() {
                    hard_stop = true;
                    causes.insert(DegradationCause::DiskFloor);
                }
            }
            _ if matches!(
                resource.status,
                StatusClass::Refused | StatusClass::Unavailable | StatusClass::Stopped
            ) =>
            {
                hard_stop = true;
                causes.insert(DegradationCause::ResourceCeiling);
            }
            _ => {}
        }
    }
    let stage = if hard_stop || pressure >= policy.stop_before_reserve_at_ppm.get() {
        DegradationStage::StopBeforeControlReserve
    } else if pressure >= policy.census_only_at_ppm.get() {
        DegradationStage::CensusOnly
    } else if pressure >= policy.reduce_hot_scopes_at_ppm.get() {
        DegradationStage::HotScopesReduced
    } else if pressure >= policy.slow_social_at_ppm.get() {
        DegradationStage::SocialRefreshSlowed
    } else if pressure >= policy.optional_media_at_ppm.get() {
        DegradationStage::OptionalMediaDisabled
    } else {
        DegradationStage::FullFidelity
    };
    Ok(DegradationDecisionV1 {
        policy_id: policy.policy_id.clone(),
        pressure_ppm: WireU64::new(pressure.min(ONE_MILLION)),
        stage,
        causes: causes.into_iter().collect(),
    })
}

/// One fixed-interval drain measurement during a declared recovery window.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecoveryDrainWindowV1 {
    pub recovery_window_id: StableString,
    pub started_at: UtcTimestamp,
    pub ended_at: UtcTimestamp,
    pub backlog_start_records: WireU64,
    pub admitted_arrival_records: WireU64,
    pub durably_drained_records: WireU64,
    pub backlog_end_records: WireU64,
    pub backlog_start_bytes: WireU64,
    pub admitted_arrival_bytes: WireU64,
    pub durably_drained_bytes: WireU64,
    pub backlog_end_bytes: WireU64,
}

/// Result of the recovery-only drain target.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DrainAssessment {
    NotApplicableNoBacklog,
    MeetsTarget,
    BelowTarget,
}

/// Checks exact backlog conservation and the configured drain target.
///
/// The target is evaluated only for a non-empty backlog inside this explicitly named window.
/// Lifetime counters cannot satisfy it.
///
/// # Errors
///
/// Refuses reversed time, inconsistent record/byte balances, or drain beyond available backlog.
pub fn assess_recovery_drain(
    window: &RecoveryDrainWindowV1,
    minimum_drain_to_arrival_ppm: WireU64,
) -> Result<DrainAssessment> {
    if window.ended_at <= window.started_at {
        return Err(OperationalError::Invalid(
            "recovery drain window must have positive wall duration",
        ));
    }
    check_balance(
        window.backlog_start_records.get(),
        window.admitted_arrival_records.get(),
        window.durably_drained_records.get(),
        window.backlog_end_records.get(),
    )?;
    check_balance(
        window.backlog_start_bytes.get(),
        window.admitted_arrival_bytes.get(),
        window.durably_drained_bytes.get(),
        window.backlog_end_bytes.get(),
    )?;
    if window.backlog_start_records.get() == 0 && window.backlog_start_bytes.get() == 0 {
        return Ok(DrainAssessment::NotApplicableNoBacklog);
    }
    let target = minimum_drain_to_arrival_ppm.get();
    if target < ONE_MILLION {
        return Err(OperationalError::Invalid(
            "drain target must be at least 1_000_000 ppm",
        ));
    }
    let records_pass = ratio_meets(
        window.durably_drained_records.get(),
        window.admitted_arrival_records.get(),
        target,
    );
    let bytes_pass = ratio_meets(
        window.durably_drained_bytes.get(),
        window.admitted_arrival_bytes.get(),
        target,
    );
    Ok(if records_pass && bytes_pass {
        DrainAssessment::MeetsTarget
    } else {
        DrainAssessment::BelowTarget
    })
}

fn capacity_pressure_ppm(used: u64, maximum: u64, reserve: u64) -> u64 {
    let usable = maximum.saturating_sub(reserve);
    if usable == 0 {
        return ONE_MILLION;
    }
    u64::try_from(
        u128::from(used)
            .saturating_mul(u128::from(ONE_MILLION))
            .checked_div(u128::from(usable))
            .unwrap_or(u128::from(ONE_MILLION)),
    )
    .unwrap_or(u64::MAX)
    .min(ONE_MILLION)
}

fn consumed_ppm(used: u64, authorized: u64) -> u64 {
    if authorized == 0 {
        return if used == 0 { 0 } else { ONE_MILLION };
    }
    u64::try_from(u128::from(used).saturating_mul(u128::from(ONE_MILLION)) / u128::from(authorized))
        .unwrap_or(u64::MAX)
        .min(ONE_MILLION)
}

fn check_balance(start: u64, arrived: u64, drained: u64, end: u64) -> Result<()> {
    let available = start
        .checked_add(arrived)
        .ok_or(OperationalError::Invalid("recovery backlog overflow"))?;
    if drained > available || available - drained != end {
        return Err(OperationalError::Invalid(
            "recovery backlog does not conserve admitted and durably drained work",
        ));
    }
    Ok(())
}

fn ratio_meets(drained: u64, arrived: u64, target_ppm: u64) -> bool {
    if arrived == 0 {
        return drained > 0;
    }
    u128::from(drained) * u128::from(ONE_MILLION) >= u128::from(arrived) * u128::from(target_ppm)
}
