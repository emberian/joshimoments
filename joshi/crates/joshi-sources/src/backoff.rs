use std::time::Duration;

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct BackoffPolicy {
    pub initial_ms: u64,
    pub maximum_ms: u64,
    /// Fixed-point multiplier where 1,000 means 1x and 2,000 means 2x.
    pub multiplier_milli: u32,
    /// Symmetric jitter in per-mille. `200` means ±20%.
    pub jitter_per_mille: u16,
}

impl Default for BackoffPolicy {
    fn default() -> Self {
        Self {
            initial_ms: 500,
            maximum_ms: 30_000,
            multiplier_milli: 2_000,
            jitter_per_mille: 200,
        }
    }
}

impl BackoffPolicy {
    /// Validate the policy bounds.
    ///
    /// # Errors
    ///
    /// Returns an error when a delay is zero or inverted, the multiplier shrinks delays, or
    /// jitter exceeds 100%.
    pub fn validate(self) -> Result<Self, &'static str> {
        if self.initial_ms == 0 {
            return Err("initial backoff must be nonzero");
        }
        if self.maximum_ms < self.initial_ms {
            return Err("maximum backoff must be at least the initial backoff");
        }
        if self.multiplier_milli < 1_000 {
            return Err("backoff multiplier must be at least 1x");
        }
        if self.jitter_per_mille > 1_000 {
            return Err("jitter cannot exceed 100%");
        }
        Ok(self)
    }
}

#[derive(Clone, Debug)]
pub struct Backoff {
    policy: BackoffPolicy,
    attempt: u32,
}

impl Backoff {
    /// Create a deterministic backoff sequence.
    ///
    /// # Errors
    ///
    /// Returns an error when `policy` fails [`BackoffPolicy::validate`].
    pub fn new(policy: BackoffPolicy) -> Result<Self, &'static str> {
        Ok(Self {
            policy: policy.validate()?,
            attempt: 0,
        })
    }

    #[must_use]
    pub fn attempt(&self) -> u32 {
        self.attempt
    }

    pub fn reset(&mut self) {
        self.attempt = 0;
    }

    /// Return the next delay. `entropy` is injected so offline tests need no RNG or sleeping.
    pub fn next_delay(&mut self, entropy: u64) -> Duration {
        let exponent = self.attempt.min(63);
        let mut base = u128::from(self.policy.initial_ms);
        for _ in 0..exponent {
            base = base.saturating_mul(u128::from(self.policy.multiplier_milli)) / 1_000;
            if base >= u128::from(self.policy.maximum_ms) {
                base = u128::from(self.policy.maximum_ms);
                break;
            }
        }
        self.attempt = self.attempt.saturating_add(1);

        let base = u64::try_from(base.min(u128::from(self.policy.maximum_ms)))
            .unwrap_or(self.policy.maximum_ms);
        let spread = base.saturating_mul(u64::from(self.policy.jitter_per_mille)) / 1_000;
        if spread == 0 {
            return Duration::from_millis(base);
        }
        let width = spread.saturating_mul(2).saturating_add(1);
        let offset = i128::from(entropy % width) - i128::from(spread);
        let jittered = (i128::from(base) + offset)
            .max(0)
            .min(i128::from(self.policy.maximum_ms));
        Duration::from_millis(u64::try_from(jittered).unwrap_or(self.policy.maximum_ms))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delay_is_bounded_and_resettable() {
        let mut backoff = Backoff::new(BackoffPolicy {
            initial_ms: 100,
            maximum_ms: 1_000,
            multiplier_milli: 2_000,
            jitter_per_mille: 100,
        })
        .unwrap();
        let values: Vec<_> = (0..8)
            .map(|entropy| u64::try_from(backoff.next_delay(entropy).as_millis()).unwrap())
            .collect();
        assert!((90..=110).contains(&values[0]));
        assert!(values.iter().all(|value| *value <= 1_000));
        backoff.reset();
        assert!((90..=110).contains(&u64::try_from(backoff.next_delay(0).as_millis()).unwrap()));
    }
}
