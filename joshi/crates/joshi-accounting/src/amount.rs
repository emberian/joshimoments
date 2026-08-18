use std::cmp::Ordering;

use joshi_domain::{WireU64, WireU128};
use thiserror::Error;

/// Atomic quantity at one Solana account boundary.
#[must_use]
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct AtomQty(WireU64);

impl AtomQty {
    pub const ZERO: Self = Self(WireU64::new(0));

    pub const fn new(value: u64) -> Self {
        Self(WireU64::new(value))
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0.get()
    }

    /// Adds two account quantities without wrapping.
    ///
    /// # Errors
    ///
    /// Returns [`ArithmeticError::Overflow`] when the result exceeds `u64`.
    pub fn checked_add(self, rhs: Self) -> Result<Self, ArithmeticError> {
        self.get()
            .checked_add(rhs.get())
            .map(Self::new)
            .ok_or(ArithmeticError::Overflow("u64 addition"))
    }

    /// Subtracts two account quantities without wrapping.
    ///
    /// # Errors
    ///
    /// Returns [`ArithmeticError::Underflow`] when `rhs` is larger than `self`.
    pub fn checked_sub(self, rhs: Self) -> Result<Self, ArithmeticError> {
        self.get()
            .checked_sub(rhs.get())
            .map(Self::new)
            .ok_or(ArithmeticError::Underflow("u64 subtraction"))
    }
}

/// Checked aggregate quantity across controlled accounts.
#[must_use]
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct TotalAtoms(WireU128);

impl TotalAtoms {
    pub const ZERO: Self = Self(WireU128::new(0));

    pub const fn new(value: u128) -> Self {
        Self(WireU128::new(value))
    }

    #[must_use]
    pub const fn get(self) -> u128 {
        self.0.get()
    }

    /// Adds two aggregate quantities without wrapping.
    ///
    /// # Errors
    ///
    /// Returns [`ArithmeticError::Overflow`] when the result exceeds `u128`.
    pub fn checked_add(self, rhs: Self) -> Result<Self, ArithmeticError> {
        self.get()
            .checked_add(rhs.get())
            .map(Self::new)
            .ok_or(ArithmeticError::Overflow("u128 aggregate addition"))
    }

    /// Subtracts two aggregate quantities without wrapping.
    ///
    /// # Errors
    ///
    /// Returns [`ArithmeticError::Underflow`] when `rhs` is larger than `self`.
    pub fn checked_sub(self, rhs: Self) -> Result<Self, ArithmeticError> {
        self.get()
            .checked_sub(rhs.get())
            .map(Self::new)
            .ok_or(ArithmeticError::Underflow("u128 aggregate subtraction"))
    }
}

impl From<AtomQty> for TotalAtoms {
    fn from(value: AtomQty) -> Self {
        Self(WireU128::new(u128::from(value.get())))
    }
}

#[must_use]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SignedAtoms {
    Increase(TotalAtoms),
    Decrease(TotalAtoms),
    Unchanged,
}

impl SignedAtoms {
    pub fn between(before: TotalAtoms, after: TotalAtoms) -> Self {
        match after.cmp(&before) {
            Ordering::Greater => Self::Increase(TotalAtoms::new(after.get() - before.get())),
            Ordering::Less => Self::Decrease(TotalAtoms::new(before.get() - after.get())),
            Ordering::Equal => Self::Unchanged,
        }
    }

    #[must_use]
    pub fn exact_increase(self, expected: AtomQty) -> bool {
        matches!(self, Self::Increase(actual) if actual.get() == u128::from(expected.get()))
    }

    #[must_use]
    pub fn exact_decrease(self, expected: AtomQty) -> bool {
        matches!(self, Self::Decrease(actual) if actual.get() == u128::from(expected.get()))
    }
}

/// Integer floor multiplication/division with a checked `u128` intermediate.
///
/// # Errors
///
/// Returns an error for a zero denominator or a quotient that cannot narrow to `u64`.
pub fn mul_div_floor(lhs: u64, rhs: u64, denominator: u64) -> Result<u64, ArithmeticError> {
    if denominator == 0 {
        return Err(ArithmeticError::DivisionByZero);
    }
    let product = u128::from(lhs)
        .checked_mul(u128::from(rhs))
        .ok_or(ArithmeticError::Overflow("u128 multiplication"))?;
    let quotient = product / u128::from(denominator);
    u64::try_from(quotient).map_err(|_| ArithmeticError::Narrowing)
}

/// Integer ceiling multiplication/division with a checked `u128` intermediate.
///
/// # Errors
///
/// Returns an error for a zero denominator or a quotient that cannot narrow to `u64`.
pub fn mul_div_ceil(lhs: u64, rhs: u64, denominator: u64) -> Result<u64, ArithmeticError> {
    if denominator == 0 {
        return Err(ArithmeticError::DivisionByZero);
    }
    let product = u128::from(lhs)
        .checked_mul(u128::from(rhs))
        .ok_or(ArithmeticError::Overflow("u128 multiplication"))?;
    let divisor = u128::from(denominator);
    let quotient = product / divisor;
    let rounded = quotient
        .checked_add(u128::from(product % divisor != 0))
        .ok_or(ArithmeticError::Overflow("ceiling increment"))?;
    u64::try_from(rounded).map_err(|_| ArithmeticError::Narrowing)
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ArithmeticError {
    #[error("division by zero")]
    DivisionByZero,
    #[error("arithmetic overflow during {0}")]
    Overflow(&'static str),
    #[error("arithmetic underflow during {0}")]
    Underflow(&'static str),
    #[error("result does not fit its declared atomic width")]
    Narrowing,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mul_div_uses_declared_rounding() {
        assert_eq!(mul_div_floor(7, 10, 6), Ok(11));
        assert_eq!(mul_div_ceil(7, 10, 6), Ok(12));
        assert_eq!(mul_div_ceil(6, 10, 6), Ok(10));
    }

    #[test]
    fn canonical_decimal_rejects_ambiguous_forms() {
        for value in ["", "+1", "-0", "00", "01", " 1", "1.0"] {
            assert!(serde_json::from_str::<WireU64>(&format!("\"{value}\"")).is_err());
        }
        assert_eq!(serde_json::from_str::<WireU64>("\"0\"").unwrap().get(), 0);
    }
}
