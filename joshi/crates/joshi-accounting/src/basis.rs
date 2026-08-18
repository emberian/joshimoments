use std::collections::BTreeMap;

use num_bigint::{BigInt, Sign};
use num_rational::BigRational;
use num_traits::{One, Zero};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::amount::AtomQty;
use crate::model::AssetKey;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BasisQuality {
    Known,
    Estimated,
    Partial,
    Unknown,
}

#[must_use]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExactRatio(BigRational);

impl ExactRatio {
    pub fn zero() -> Self {
        Self(BigRational::zero())
    }

    pub fn from_atom_qty(value: AtomQty) -> Self {
        Self(BigRational::from_integer(BigInt::from(value.get())))
    }

    pub fn from_u64(value: u64) -> Self {
        Self(BigRational::from_integer(BigInt::from(value)))
    }

    /// Constructs and normalizes a rational value.
    ///
    /// # Errors
    ///
    /// Returns [`BasisError::InvalidDenominator`] unless the denominator is positive.
    pub fn checked_fraction(
        numerator: impl Into<BigInt>,
        denominator: impl Into<BigInt>,
    ) -> Result<Self, BasisError> {
        let numerator = numerator.into();
        let denominator = denominator.into();
        if denominator <= BigInt::zero() {
            return Err(BasisError::InvalidDenominator);
        }
        Ok(Self(BigRational::new(numerator, denominator)))
    }

    pub(crate) fn add_assign(&mut self, rhs: &Self) {
        self.0 += &rhs.0;
    }

    pub fn sub(&self, rhs: &Self) -> Self {
        Self(&self.0 - &rhs.0)
    }

    pub(crate) fn mul_fraction(&self, numerator: AtomQty, denominator: AtomQty) -> Self {
        debug_assert!(denominator != AtomQty::ZERO);
        let fraction = BigRational::new(
            BigInt::from(numerator.get()),
            BigInt::from(denominator.get()),
        );
        Self(&self.0 * fraction)
    }

    #[must_use]
    pub fn is_zero(&self) -> bool {
        self.0.is_zero()
    }

    #[must_use]
    pub fn numerator_string(&self) -> String {
        self.0.numer().to_str_radix(10)
    }

    #[must_use]
    pub fn denominator_string(&self) -> String {
        self.0.denom().to_str_radix(10)
    }

    pub(crate) fn to_u64_if_integer(&self) -> Option<u64> {
        if self.0.denom() != &BigInt::one() || self.0.numer().sign() == Sign::Minus {
            return None;
        }
        u64::try_from(self.0.numer()).ok()
    }
}

#[must_use]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Basis {
    pub quality: BasisQuality,
    /// Exact known component. Empty for wholly unknown basis.
    pub known: BTreeMap<AssetKey, ExactRatio>,
}

impl Basis {
    pub fn known(asset: AssetKey, amount: AtomQty) -> Self {
        Self {
            quality: BasisQuality::Known,
            known: BTreeMap::from([(asset, ExactRatio::from_atom_qty(amount))]),
        }
    }

    pub fn unknown() -> Self {
        Self {
            quality: BasisQuality::Unknown,
            known: BTreeMap::new(),
        }
    }

    /// Allocates a proportional slice without rounding.
    ///
    /// # Errors
    ///
    /// Returns [`BasisError::InvalidAllocation`] when the total is zero or the slice exceeds it.
    pub fn allocate(&self, quantity: AtomQty, total: AtomQty) -> Result<Self, BasisError> {
        if total == AtomQty::ZERO || quantity > total {
            return Err(BasisError::InvalidAllocation);
        }
        let known = self
            .known
            .iter()
            .map(|(asset, amount)| (asset.clone(), amount.mul_fraction(quantity, total)))
            .collect();
        Ok(Self {
            quality: self.quality,
            known,
        })
    }

    pub fn merged_with(&self, rhs: &Self) -> Self {
        let mut known = self.known.clone();
        for (asset, amount) in &rhs.known {
            known
                .entry(asset.clone())
                .or_insert_with(ExactRatio::zero)
                .add_assign(amount);
        }
        Self {
            quality: combine_quality(self.quality, rhs.quality),
            known,
        }
    }

    pub(crate) fn checked_sub_known(&self, rhs: &Self) -> Result<Self, BasisError> {
        let mut known = self.known.clone();
        for (asset, amount) in &rhs.known {
            let value = known.get_mut(asset).ok_or(BasisError::NegativeBasis)?;
            let next = value.sub(amount);
            if next.0 < BigRational::zero() {
                return Err(BasisError::NegativeBasis);
            }
            *value = next;
        }
        known.retain(|_, value| !value.is_zero());
        Ok(Self {
            quality: self.quality,
            known,
        })
    }

    #[must_use]
    pub fn is_exact_zero(&self) -> bool {
        self.quality != BasisQuality::Unknown && self.known.values().all(ExactRatio::is_zero)
    }

    #[must_use]
    pub fn component(&self, asset: &AssetKey) -> Option<&ExactRatio> {
        self.known.get(asset)
    }
}

fn combine_quality(lhs: BasisQuality, rhs: BasisQuality) -> BasisQuality {
    use BasisQuality::{Estimated, Known, Partial, Unknown};
    match (lhs, rhs) {
        (Known, Known) => Known,
        (Unknown, Unknown) => Unknown,
        (Partial | Unknown, _) | (_, Partial | Unknown) => Partial,
        (Estimated, _) | (_, Estimated) => Estimated,
    }
}

#[must_use]
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RatioWire {
    pub numerator: String,
    pub denominator: String,
}

impl RatioWire {
    pub fn from_ratio(value: &ExactRatio) -> Self {
        Self {
            numerator: value.numerator_string(),
            denominator: value.denominator_string(),
        }
    }

    /// Parses and validates a reduced rational.
    ///
    /// # Errors
    ///
    /// Returns a [`BasisError`] for invalid integers, denominator, or non-reduced form.
    pub fn parse(&self) -> Result<ExactRatio, BasisError> {
        validate_signed(&self.numerator)?;
        validate_unsigned_positive(&self.denominator)?;
        let numerator =
            BigInt::parse_bytes(self.numerator.as_bytes(), 10).ok_or(BasisError::InvalidInteger)?;
        let denominator = BigInt::parse_bytes(self.denominator.as_bytes(), 10)
            .ok_or(BasisError::InvalidInteger)?;
        let ratio = ExactRatio::checked_fraction(numerator, denominator)?;
        if RatioWire::from_ratio(&ratio) != *self {
            return Err(BasisError::NonCanonicalRatio);
        }
        Ok(ratio)
    }
}

fn validate_signed(value: &str) -> Result<(), BasisError> {
    let digits = value.strip_prefix('-').unwrap_or(value);
    if value.starts_with('+')
        || digits.is_empty()
        || (digits.len() > 1 && digits.starts_with('0'))
        || value == "-0"
        || !digits.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(BasisError::InvalidInteger);
    }
    Ok(())
}

fn validate_unsigned_positive(value: &str) -> Result<(), BasisError> {
    validate_signed(value)?;
    if value.starts_with('-') || value == "0" {
        return Err(BasisError::InvalidDenominator);
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum BasisError {
    #[error("basis allocation must be positive and no larger than its lot")]
    InvalidAllocation,
    #[error("rational denominator must be positive")]
    InvalidDenominator,
    #[error("invalid canonical decimal integer")]
    InvalidInteger,
    #[error("rational must be reduced and canonical")]
    NonCanonicalRatio,
    #[error("basis subtraction would become negative")]
    NegativeBasis,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_ratio_is_reduced_and_positive_denominator() {
        let ratio = ExactRatio::checked_fraction(BigInt::from(-2), BigInt::from(4)).unwrap();
        assert_eq!(ratio.numerator_string(), "-1");
        assert_eq!(ratio.denominator_string(), "2");
        assert_eq!(
            RatioWire {
                numerator: "-2".into(),
                denominator: "4".into(),
            }
            .parse(),
            Err(BasisError::NonCanonicalRatio)
        );
    }

    #[test]
    fn partial_allocation_is_exact() {
        let sol = AssetKey::new("sol").unwrap();
        let basis = Basis::known(sol.clone(), AtomQty::new(101));
        let allocated = basis
            .allocate(AtomQty::new(600), AtomQty::new(1_000))
            .unwrap();
        let amount = allocated.component(&sol).unwrap();
        assert_eq!(amount.numerator_string(), "303");
        assert_eq!(amount.denominator_string(), "5");
    }
}
