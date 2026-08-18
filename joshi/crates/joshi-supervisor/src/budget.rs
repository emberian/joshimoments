use crate::{Result, SupervisorError};
pub use joshi_admission::wave5::RunBudgetLimitsV1 as RunBudgetLimits;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// One independently enforced run-budget dimension.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BudgetDimension {
    Requests,
    Pages,
    IngressBytes,
    DurableBytes,
    ProviderCredits,
    ElapsedMilliseconds,
    InFlightAttempts,
}

/// Worst-case cost declared before one provider call. A source whose maximum response or charge
/// cannot be stated is not runnable through this boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AttemptBudgetClaim {
    pub requests: u64,
    pub pages: u64,
    pub maximum_ingress_bytes: u64,
    pub maximum_durable_bytes: u64,
    pub maximum_provider_credits: u64,
    pub maximum_ingress_bytes_per_second: Option<u64>,
    pub maximum_elapsed_ms: u64,
}

impl AttemptBudgetClaim {
    /// Validate a bounded single-attempt claim.
    ///
    /// # Errors
    ///
    /// Refuses a claim that is not exactly one request/connection or has no byte/time bound.
    pub fn validate(self) -> Result<()> {
        if self.requests != 1
            || self.maximum_ingress_bytes == 0
            || self.maximum_durable_bytes == 0
            || self.maximum_elapsed_ms == 0
            || self.maximum_ingress_bytes_per_second == Some(0)
        {
            return Err(SupervisorError::InvalidValue(
                "attempt budget must describe one bounded request with byte and time maxima".into(),
            ));
        }
        Ok(())
    }
}

/// Actual provider and durability use used to settle one permit. Provider failure still consumes
/// the request, received bytes, elapsed time, and any provider credits it reports.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AttemptBudgetUsage {
    pub requests: u64,
    pub pages: u64,
    pub ingress_bytes: u64,
    pub durable_bytes: u64,
    pub provider_credits: u64,
    pub elapsed_ms: u64,
}

/// Process-local identity for a worst-case reservation. This is budget concurrency state, not
/// durable source occurrence identity.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct BudgetPermitId(u64);

impl BudgetPermitId {
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Opaque permission to perform exactly one bounded provider operation. Only `BudgetLedger` can
/// construct it; callers must return it by `settle` or `cancel_before_io`.
#[derive(Debug)]
pub struct BudgetPermit {
    id: BudgetPermitId,
    claim: AttemptBudgetClaim,
}

impl BudgetPermit {
    #[must_use]
    pub const fn id(&self) -> BudgetPermitId {
        self.id
    }

    #[must_use]
    pub const fn claim(&self) -> AttemptBudgetClaim {
        self.claim
    }
}

/// Observable budget state. Outstanding maxima are kept separate from provider-observed use; the
/// latter never impersonates a provider invoice.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BudgetSnapshot {
    pub limits: RunBudgetLimits,
    pub used: AttemptBudgetUsage,
    pub outstanding_attempts: u64,
    pub outstanding_maximum_ingress_bytes: u64,
    pub outstanding_maximum_durable_bytes: u64,
    pub outstanding_maximum_provider_credits: u64,
    pub maximum_possible_elapsed_overshoot_ms: u64,
    pub terminal_violation: Option<BudgetDimension>,
}

/// Single-run, in-process budget ledger. Durable source reservations remain the crash authority;
/// this ledger prevents a running process from beginning work beyond a registered envelope.
#[derive(Debug)]
pub struct BudgetLedger {
    limits: RunBudgetLimits,
    started_monotonic_ms: u64,
    next_id: u64,
    used: AttemptBudgetUsage,
    outstanding: BTreeMap<BudgetPermitId, AttemptBudgetClaim>,
    terminal_violation: Option<BudgetDimension>,
}

impl BudgetLedger {
    /// Start an empty ledger at a caller-supplied monotonic clock value.
    ///
    /// # Errors
    ///
    /// Refuses an invalid run envelope.
    pub fn new(limits: RunBudgetLimits, started_monotonic_ms: u64) -> Result<Self> {
        limits.validate()?;
        Ok(Self {
            limits,
            started_monotonic_ms,
            next_id: 1,
            used: AttemptBudgetUsage {
                requests: 0,
                pages: 0,
                ingress_bytes: 0,
                durable_bytes: 0,
                provider_credits: 0,
                elapsed_ms: 0,
            },
            outstanding: BTreeMap::new(),
            terminal_violation: None,
        })
    }

    /// Reserve worst-case capacity before any provider I/O.
    ///
    /// # Errors
    ///
    /// Refuses malformed/unbounded claims, exhausted dimensions, concurrency overflow, a start at
    /// or after the run deadline, or an attempt timeout above the declared in-flight overshoot.
    pub fn reserve(
        &mut self,
        claim: AttemptBudgetClaim,
        now_monotonic_ms: u64,
    ) -> Result<BudgetPermit> {
        claim.validate()?;
        if let Some(dimension) = self.terminal_violation {
            return Err(SupervisorError::RunBudgetExhausted { dimension });
        }
        match (
            self.limits.maximum_ingress_bytes_per_second,
            claim.maximum_ingress_bytes_per_second,
        ) {
            (Some(limit), Some(claimed)) if claimed <= limit => {}
            (Some(_), _) => {
                return Err(SupervisorError::InvalidValue(
                    "attempt has no admissible hard ingress-rate bound".into(),
                ));
            }
            (None, Some(_) | None) => {}
        }
        let elapsed = now_monotonic_ms
            .checked_sub(self.started_monotonic_ms)
            .ok_or_else(|| {
                SupervisorError::InvalidState("monotonic clock moved backward".into())
            })?;
        if elapsed >= self.limits.maximum_elapsed_ms {
            return Err(exhausted(BudgetDimension::ElapsedMilliseconds));
        }
        if claim.maximum_elapsed_ms > self.limits.maximum_in_flight_elapsed_overshoot_ms {
            return Err(SupervisorError::InvalidValue(
                "attempt timeout exceeds declared in-flight time overshoot".into(),
            ));
        }
        let outstanding_attempts = u64::try_from(self.outstanding.len()).unwrap_or(u64::MAX);
        require_fit(
            BudgetDimension::InFlightAttempts,
            outstanding_attempts,
            1,
            self.limits.maximum_in_flight_attempts,
        )?;
        let outstanding = outstanding_totals(&self.outstanding);
        require_fit(
            BudgetDimension::Requests,
            self.used.requests.saturating_add(outstanding.requests),
            claim.requests,
            self.limits.maximum_requests,
        )?;
        require_fit(
            BudgetDimension::Pages,
            self.used.pages.saturating_add(outstanding.pages),
            claim.pages,
            self.limits.maximum_pages,
        )?;
        require_fit(
            BudgetDimension::IngressBytes,
            self.used
                .ingress_bytes
                .saturating_add(outstanding.maximum_ingress_bytes),
            claim.maximum_ingress_bytes,
            self.limits.maximum_ingress_bytes,
        )?;
        require_fit(
            BudgetDimension::DurableBytes,
            self.used
                .durable_bytes
                .saturating_add(outstanding.maximum_durable_bytes),
            claim.maximum_durable_bytes,
            self.limits.maximum_durable_bytes,
        )?;
        require_fit(
            BudgetDimension::ProviderCredits,
            self.used
                .provider_credits
                .saturating_add(outstanding.maximum_provider_credits),
            claim.maximum_provider_credits,
            self.limits.maximum_provider_credits,
        )?;
        let id = BudgetPermitId(self.next_id);
        self.next_id = self.next_id.checked_add(1).ok_or_else(|| {
            SupervisorError::InvalidState("budget permit identity overflow".into())
        })?;
        self.outstanding.insert(id, claim);
        Ok(BudgetPermit { id, claim })
    }

    /// Settle exact use after I/O and local durability are known.
    ///
    /// # Errors
    ///
    /// Refuses a foreign/reused permit, actual use beyond any reserved maximum, or an operation
    /// that reports anything other than its one reserved request.
    #[allow(clippy::needless_pass_by_value)] // Consuming the opaque permit prevents caller reuse.
    pub fn settle(&mut self, permit: BudgetPermit, usage: AttemptBudgetUsage) -> Result<()> {
        let violation = self.settlement_violation(&permit, usage)?;
        let Some(claim) = self.outstanding.remove(&permit.id) else {
            return Err(SupervisorError::InvalidState(
                "budget permit is foreign or already settled".into(),
            ));
        };
        if claim != permit.claim {
            return Err(SupervisorError::InvalidState(
                "budget permit claim does not match ledger state".into(),
            ));
        }
        // A malformed post-I/O report cannot refund the request/page capacity it necessarily
        // consumed. Preserve larger observed counts, but charge at least the exact claim.
        let charged_requests = usage.requests.max(claim.requests);
        let charged_pages = usage.pages.max(claim.pages);
        self.used.requests = self.used.requests.saturating_add(charged_requests);
        self.used.pages = self.used.pages.saturating_add(charged_pages);
        self.used.ingress_bytes = self.used.ingress_bytes.saturating_add(usage.ingress_bytes);
        self.used.durable_bytes = self.used.durable_bytes.saturating_add(usage.durable_bytes);
        self.used.provider_credits = self
            .used
            .provider_credits
            .saturating_add(usage.provider_credits);
        self.used.elapsed_ms = self.used.elapsed_ms.max(usage.elapsed_ms);
        if let Some(dimension) = violation {
            self.terminal_violation = Some(dimension);
            return Err(SupervisorError::AttemptBudgetExceeded);
        }
        Ok(())
    }

    pub(crate) fn settlement_violation(
        &self,
        permit: &BudgetPermit,
        usage: AttemptBudgetUsage,
    ) -> Result<Option<BudgetDimension>> {
        let claim = self.outstanding.get(&permit.id).ok_or_else(|| {
            SupervisorError::InvalidState("budget permit is foreign or already settled".into())
        })?;
        if claim != &permit.claim {
            return Err(SupervisorError::InvalidState(
                "budget permit claim does not match ledger state".into(),
            ));
        }
        let rate_exceeded = self
            .limits
            .maximum_ingress_bytes_per_second
            .is_some_and(|rate| {
                let observed_scaled = u128::from(usage.ingress_bytes).saturating_mul(1_000);
                let one_second_burst_or_elapsed = usage.elapsed_ms.max(1_000);
                observed_scaled
                    > u128::from(rate).saturating_mul(u128::from(one_second_burst_or_elapsed))
            });
        Ok(if usage.requests != claim.requests {
            Some(BudgetDimension::Requests)
        } else if usage.pages != claim.pages {
            Some(BudgetDimension::Pages)
        } else if usage.ingress_bytes > claim.maximum_ingress_bytes || rate_exceeded {
            Some(BudgetDimension::IngressBytes)
        } else if usage.durable_bytes > claim.maximum_durable_bytes {
            Some(BudgetDimension::DurableBytes)
        } else if usage.provider_credits > claim.maximum_provider_credits {
            Some(BudgetDimension::ProviderCredits)
        } else if usage.elapsed_ms > claim.maximum_elapsed_ms {
            Some(BudgetDimension::ElapsedMilliseconds)
        } else {
            None
        })
    }

    /// Release a permit only when provider I/O provably did not begin.
    ///
    /// # Errors
    ///
    /// Refuses a foreign or already consumed permit.
    #[allow(clippy::needless_pass_by_value)] // Cancellation consumes the one-shot permit.
    pub fn cancel_before_io(&mut self, permit: BudgetPermit) -> Result<()> {
        let Some(claim) = self.outstanding.remove(&permit.id) else {
            return Err(SupervisorError::InvalidState(
                "budget permit is foreign or already settled".into(),
            ));
        };
        if claim != permit.claim {
            return Err(SupervisorError::InvalidState(
                "budget permit claim does not match ledger state".into(),
            ));
        }
        Ok(())
    }

    pub(crate) fn restore_consumed(
        &mut self,
        usage: AttemptBudgetUsage,
        violation: Option<BudgetDimension>,
    ) -> Result<()> {
        if self.has_outstanding_permits() {
            return Err(SupervisorError::InvalidState(
                "cannot restore execution use while permits are outstanding".into(),
            ));
        }
        self.used.requests = self
            .used
            .requests
            .checked_add(usage.requests)
            .ok_or_else(|| {
                SupervisorError::InvalidState("restored request count overflow".into())
            })?;
        self.used.pages =
            self.used.pages.checked_add(usage.pages).ok_or_else(|| {
                SupervisorError::InvalidState("restored page count overflow".into())
            })?;
        self.used.ingress_bytes = self
            .used
            .ingress_bytes
            .checked_add(usage.ingress_bytes)
            .ok_or_else(|| {
                SupervisorError::InvalidState("restored ingress count overflow".into())
            })?;
        self.used.durable_bytes = self
            .used
            .durable_bytes
            .checked_add(usage.durable_bytes)
            .ok_or_else(|| {
                SupervisorError::InvalidState("restored durable count overflow".into())
            })?;
        self.used.provider_credits = self
            .used
            .provider_credits
            .checked_add(usage.provider_credits)
            .ok_or_else(|| {
                SupervisorError::InvalidState("restored credit count overflow".into())
            })?;
        self.used.elapsed_ms = self.used.elapsed_ms.max(usage.elapsed_ms);
        self.terminal_violation = self.terminal_violation.or(violation);
        if self.terminal_violation.is_none() {
            let dimensions = [
                (
                    BudgetDimension::Requests,
                    self.used.requests,
                    self.limits.maximum_requests,
                ),
                (
                    BudgetDimension::Pages,
                    self.used.pages,
                    self.limits.maximum_pages,
                ),
                (
                    BudgetDimension::IngressBytes,
                    self.used.ingress_bytes,
                    self.limits.maximum_ingress_bytes,
                ),
                (
                    BudgetDimension::DurableBytes,
                    self.used.durable_bytes,
                    self.limits.maximum_durable_bytes,
                ),
                (
                    BudgetDimension::ProviderCredits,
                    self.used.provider_credits,
                    self.limits.maximum_provider_credits,
                ),
            ];
            self.terminal_violation = dimensions
                .into_iter()
                .find_map(|(dimension, used, limit)| (used > limit).then_some(dimension));
        }
        Ok(())
    }

    #[must_use]
    pub fn snapshot(&self, now_monotonic_ms: u64) -> BudgetSnapshot {
        let outstanding = outstanding_totals(&self.outstanding);
        let elapsed = now_monotonic_ms.saturating_sub(self.started_monotonic_ms);
        let used = AttemptBudgetUsage {
            elapsed_ms: elapsed,
            ..self.used
        };
        BudgetSnapshot {
            limits: self.limits,
            used,
            outstanding_attempts: u64::try_from(self.outstanding.len()).unwrap_or(u64::MAX),
            outstanding_maximum_ingress_bytes: outstanding.maximum_ingress_bytes,
            outstanding_maximum_durable_bytes: outstanding.maximum_durable_bytes,
            outstanding_maximum_provider_credits: outstanding.maximum_provider_credits,
            maximum_possible_elapsed_overshoot_ms: self
                .outstanding
                .values()
                .map(|claim| claim.maximum_elapsed_ms)
                .max()
                .unwrap_or(0),
            terminal_violation: self.terminal_violation,
        }
    }

    #[must_use]
    pub fn has_outstanding_permits(&self) -> bool {
        !self.outstanding.is_empty()
    }
}

fn outstanding_totals(
    outstanding: &BTreeMap<BudgetPermitId, AttemptBudgetClaim>,
) -> AttemptBudgetClaim {
    outstanding.values().fold(
        AttemptBudgetClaim {
            requests: 0,
            pages: 0,
            maximum_ingress_bytes: 0,
            maximum_durable_bytes: 0,
            maximum_provider_credits: 0,
            maximum_ingress_bytes_per_second: None,
            maximum_elapsed_ms: 0,
        },
        |mut totals, value| {
            totals.requests = totals.requests.saturating_add(value.requests);
            totals.pages = totals.pages.saturating_add(value.pages);
            totals.maximum_ingress_bytes = totals
                .maximum_ingress_bytes
                .saturating_add(value.maximum_ingress_bytes);
            totals.maximum_durable_bytes = totals
                .maximum_durable_bytes
                .saturating_add(value.maximum_durable_bytes);
            totals.maximum_provider_credits = totals
                .maximum_provider_credits
                .saturating_add(value.maximum_provider_credits);
            totals.maximum_elapsed_ms = totals.maximum_elapsed_ms.max(value.maximum_elapsed_ms);
            totals
        },
    )
}

fn require_fit(dimension: BudgetDimension, used: u64, incoming: u64, maximum: u64) -> Result<()> {
    if used
        .checked_add(incoming)
        .is_none_or(|value| value > maximum)
    {
        return Err(exhausted(dimension));
    }
    Ok(())
}

fn exhausted(dimension: BudgetDimension) -> SupervisorError {
    SupervisorError::RunBudgetExhausted { dimension }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn limits() -> RunBudgetLimits {
        RunBudgetLimits {
            maximum_requests: 2,
            maximum_pages: 2,
            maximum_ingress_bytes: 100,
            maximum_durable_bytes: 200,
            maximum_provider_credits: 5,
            maximum_ingress_bytes_per_second: Some(80),
            maximum_elapsed_ms: 1_000,
            maximum_in_flight_attempts: 1,
            maximum_in_flight_elapsed_overshoot_ms: 100,
        }
    }

    fn claim() -> AttemptBudgetClaim {
        AttemptBudgetClaim {
            requests: 1,
            pages: 1,
            maximum_ingress_bytes: 50,
            maximum_durable_bytes: 100,
            maximum_provider_credits: 2,
            maximum_ingress_bytes_per_second: Some(80),
            maximum_elapsed_ms: 100,
        }
    }

    #[test]
    fn worst_case_is_reserved_before_io_and_unused_capacity_returns_only_on_settle() {
        let mut ledger = BudgetLedger::new(limits(), 10).unwrap();
        let permit = ledger.reserve(claim(), 10).unwrap();
        assert!(matches!(
            ledger.reserve(claim(), 10),
            Err(SupervisorError::RunBudgetExhausted {
                dimension: BudgetDimension::InFlightAttempts
            })
        ));
        ledger
            .settle(
                permit,
                AttemptBudgetUsage {
                    requests: 1,
                    pages: 1,
                    ingress_bytes: 7,
                    durable_bytes: 19,
                    provider_credits: 1,
                    elapsed_ms: 4,
                },
            )
            .unwrap();
        let second = ledger.reserve(claim(), 20).unwrap();
        ledger.cancel_before_io(second).unwrap();
        assert!(!ledger.has_outstanding_permits());
        assert_eq!(ledger.snapshot(20).used.requests, 1);
    }

    #[test]
    fn every_count_and_byte_ceiling_is_hard_and_time_overshoot_is_declared() {
        let mut ledger = BudgetLedger::new(limits(), 0).unwrap();
        let permit = ledger.reserve(claim(), 999).unwrap();
        let snapshot = ledger.snapshot(999);
        assert_eq!(snapshot.maximum_possible_elapsed_overshoot_ms, 100);
        assert!(matches!(
            ledger.reserve(claim(), 1_000),
            Err(SupervisorError::RunBudgetExhausted {
                dimension: BudgetDimension::ElapsedMilliseconds
            })
        ));
        assert!(matches!(
            ledger.settle(
                permit,
                AttemptBudgetUsage {
                    requests: 1,
                    pages: 1,
                    ingress_bytes: 51,
                    durable_bytes: 0,
                    provider_credits: 0,
                    elapsed_ms: 100,
                }
            ),
            Err(SupervisorError::AttemptBudgetExceeded)
        ));
        assert!(!ledger.has_outstanding_permits());
        assert_eq!(
            ledger.snapshot(1_000).terminal_violation,
            Some(BudgetDimension::IngressBytes)
        );
        assert!(matches!(
            ledger.reserve(claim(), 999),
            Err(SupervisorError::RunBudgetExhausted {
                dimension: BudgetDimension::IngressBytes
            })
        ));
    }

    #[test]
    fn provider_credit_zero_is_valid_but_cannot_admit_a_paid_attempt() {
        let mut free = limits();
        free.maximum_provider_credits = 0;
        let mut ledger = BudgetLedger::new(free, 0).unwrap();
        let mut paid = claim();
        paid.maximum_provider_credits = 1;
        assert!(matches!(
            ledger.reserve(paid, 0),
            Err(SupervisorError::RunBudgetExhausted {
                dimension: BudgetDimension::ProviderCredits
            })
        ));
        let mut no_charge = claim();
        no_charge.maximum_provider_credits = 0;
        let permit = ledger.reserve(no_charge, 0).unwrap();
        ledger.cancel_before_io(permit).unwrap();
    }

    #[test]
    fn started_attempt_cannot_refund_itself_by_underreporting_counts() {
        let mut ledger = BudgetLedger::new(limits(), 0).unwrap();
        let permit = ledger.reserve(claim(), 0).unwrap();
        assert!(matches!(
            ledger.settle(
                permit,
                AttemptBudgetUsage {
                    requests: 0,
                    pages: 0,
                    ingress_bytes: 1,
                    durable_bytes: 1,
                    provider_credits: 0,
                    elapsed_ms: 1,
                }
            ),
            Err(SupervisorError::AttemptBudgetExceeded)
        ));
        let snapshot = ledger.snapshot(1);
        assert_eq!(snapshot.terminal_violation, Some(BudgetDimension::Requests));
        assert_eq!(snapshot.used.requests, 1);
        assert_eq!(snapshot.used.pages, 1);
        assert_eq!(snapshot.used.ingress_bytes, 1);
        assert!(!ledger.has_outstanding_permits());
    }
}
