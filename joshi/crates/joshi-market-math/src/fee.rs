//! Exact fee components and observation-bound selection policies.

use crate::wide::{Rounding, WideMathError, mul_div_u128};
use thiserror::Error;

const BASIS_POINTS_DENOMINATOR: u128 = 10_000;

/// Validated basis-point rate with denominator 10,000.
#[derive(Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
pub struct FeeBps(u16);

impl FeeBps {
    /// Creates a rate no greater than 100%.
    ///
    /// # Errors
    ///
    /// Refuses values above 10,000 basis points.
    pub const fn new(value: u16) -> Result<Self, FeeError> {
        if value <= 10_000 {
            Ok(Self(value))
        } else {
            Err(FeeError::RateAboveOneHundredPercent)
        }
    }

    #[must_use]
    pub const fn get(self) -> u16 {
        self.0
    }
}

/// Whether a creator component was resolved from the observed state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CreatorFee {
    NotApplicable,
    Charged(FeeBps),
    Unknown,
}

/// Separately rounded LP, protocol, and creator rates.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FeeSchedule {
    pub lp: FeeBps,
    pub protocol: FeeBps,
    pub creator: CreatorFee,
}

/// One exact integer market-cap threshold and its schedule.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FeeTier {
    pub threshold_quote_atoms: u128,
    pub schedule: FeeSchedule,
}

/// Flat or dynamic fee configuration observed for a venue state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FeePolicy {
    Flat(FeeSchedule),
    MarketCapTiers(Vec<FeeTier>),
}

impl FeePolicy {
    /// Selects the exact schedule for a truncated integer market cap.
    ///
    /// The first tier is the below-first-threshold fallback. At or above a threshold, the highest
    /// threshold not exceeding market cap wins, matching the official Pump fee helper order.
    ///
    /// # Errors
    ///
    /// Refuses an empty, duplicate, or non-increasing tier table.
    pub fn select(&self, market_cap_quote_atoms: u128) -> Result<FeeSchedule, FeeError> {
        match self {
            Self::Flat(schedule) => Ok(*schedule),
            Self::MarketCapTiers(tiers) => {
                if tiers.is_empty() {
                    return Err(FeeError::EmptyTierTable);
                }
                if tiers.windows(2).any(|window| {
                    window[0].threshold_quote_atoms >= window[1].threshold_quote_atoms
                }) {
                    return Err(FeeError::UnorderedTierTable);
                }
                Ok(tiers
                    .iter()
                    .rev()
                    .find(|tier| tier.threshold_quote_atoms <= market_cap_quote_atoms)
                    .unwrap_or(&tiers[0])
                    .schedule)
            }
        }
    }
}

/// Exact separately rounded fee amounts.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct FeeBreakdown {
    pub lp_atoms: u64,
    pub protocol_atoms: u64,
    pub creator_atoms: u64,
}

impl FeeBreakdown {
    /// Sums all exact components without wrapping.
    ///
    /// # Errors
    ///
    /// Refuses a sum above `u64::MAX`.
    pub fn checked_total(self) -> Result<u64, FeeError> {
        self.lp_atoms
            .checked_add(self.protocol_atoms)
            .and_then(|value| value.checked_add(self.creator_atoms))
            .ok_or(FeeError::Arithmetic(WideMathError::Narrowing))
    }
}

/// Fee configuration or arithmetic failure.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum FeeError {
    #[error("fee rate exceeds 10,000 basis points")]
    RateAboveOneHundredPercent,
    #[error("dynamic fee table is empty")]
    EmptyTierTable,
    #[error("dynamic fee thresholds are not strictly increasing")]
    UnorderedTierTable,
    #[error("creator-fee applicability was not observed")]
    CreatorFeeUnknown,
    #[error(transparent)]
    Arithmetic(#[from] WideMathError),
}

/// Applies every schedule component independently with ceiling division.
///
/// # Errors
///
/// Refuses unknown creator applicability or arithmetic/narrowing failure.
pub fn calculate_fees(raw_amount: u64, schedule: FeeSchedule) -> Result<FeeBreakdown, FeeError> {
    fn component(raw_amount: u64, bps: FeeBps) -> Result<u64, FeeError> {
        let value = mul_div_u128(
            u128::from(raw_amount),
            u128::from(bps.get()),
            BASIS_POINTS_DENOMINATOR,
            Rounding::Up,
        )?;
        u64::try_from(value).map_err(|_| FeeError::Arithmetic(WideMathError::Narrowing))
    }

    let creator_atoms = match schedule.creator {
        CreatorFee::NotApplicable => 0,
        CreatorFee::Charged(rate) => component(raw_amount, rate)?,
        CreatorFee::Unknown => return Err(FeeError::CreatorFeeUnknown),
    };
    Ok(FeeBreakdown {
        lp_atoms: component(raw_amount, schedule.lp)?,
        protocol_atoms: component(raw_amount, schedule.protocol)?,
        creator_atoms,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rate(value: u16) -> FeeBps {
        FeeBps::new(value).expect("test rate is valid")
    }

    #[test]
    fn components_round_separately() {
        let fees = calculate_fees(
            1,
            FeeSchedule {
                lp: rate(1),
                protocol: rate(1),
                creator: CreatorFee::Charged(rate(1)),
            },
        );
        assert_eq!(
            fees,
            Ok(FeeBreakdown {
                lp_atoms: 1,
                protocol_atoms: 1,
                creator_atoms: 1
            })
        );
    }

    #[test]
    fn tier_boundaries_are_exact() {
        let low = FeeSchedule {
            lp: rate(1),
            protocol: rate(2),
            creator: CreatorFee::NotApplicable,
        };
        let high = FeeSchedule {
            lp: rate(3),
            protocol: rate(4),
            creator: CreatorFee::NotApplicable,
        };
        let policy = FeePolicy::MarketCapTiers(vec![
            FeeTier {
                threshold_quote_atoms: 10,
                schedule: low,
            },
            FeeTier {
                threshold_quote_atoms: 20,
                schedule: high,
            },
        ]);
        assert_eq!(policy.select(9), Ok(low));
        assert_eq!(policy.select(10), Ok(low));
        assert_eq!(policy.select(19), Ok(low));
        assert_eq!(policy.select(20), Ok(high));
    }
}
