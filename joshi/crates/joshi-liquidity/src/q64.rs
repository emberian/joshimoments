//! Meteora DLMM Q64.64 bin-price operation graph.

use joshi_market_math::wide::{Rounding, WideMathError, mul_div_u128};
use thiserror::Error;

/// Q64.64 representation of one Y-atom per X-atom price.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Q64x64(u128);

impl Q64x64 {
    pub const ONE: Self = Self(1_u128 << 64);

    #[must_use]
    pub const fn from_bits(bits: u128) -> Self {
        Self(bits)
    }

    #[must_use]
    pub const fn bits(self) -> u128 {
        self.0
    }
}

/// Signed DLMM bin identifier.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct BinId(i32);

impl BinId {
    #[must_use]
    pub const fn new(value: i32) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> i32 {
        self.0
    }
}

/// Positive DLMM bin step in basis points.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BinStep(u16);

impl BinStep {
    /// Creates a positive bin step.
    ///
    /// # Errors
    ///
    /// Refuses zero; wider protocol limits belong to a versioned profile.
    pub const fn new(value: u16) -> Result<Self, Q64Error> {
        if value == 0 {
            Err(Q64Error::ZeroBinStep)
        } else {
            Ok(Self(value))
        }
    }

    #[must_use]
    pub const fn get(self) -> u16 {
        self.0
    }
}

/// Fixed-width error matching the official DLMM checked Q64.64 path.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum Q64Error {
    #[error("bin step is zero")]
    ZeroBinStep,
    #[error("absolute bin id reaches the official 0x80000 exponent limit")]
    ExponentOutOfRange,
    #[error("checked u128 Q64.64 multiplication overflowed")]
    MultiplicationOverflow,
    #[error("Q64.64 exponentiation reached zero")]
    ZeroResult,
    #[error("wide arithmetic failed while constructing the bin base")]
    Arithmetic,
}

/// Reproduces the current official DLMM `get_price_from_id` integer operation order.
///
/// # Errors
///
/// Refuses invalid bin steps, out-of-range exponents, or checked arithmetic failure.
pub fn price_from_bin_id(bin_id: BinId, bin_step: BinStep) -> Result<Q64x64, Q64Error> {
    let step_q64 = mul_div_u128(
        u128::from(bin_step.get()),
        Q64x64::ONE.bits(),
        10_000,
        Rounding::Down,
    )
    .map_err(|_: WideMathError| Q64Error::Arithmetic)?;
    let base = Q64x64::ONE
        .bits()
        .checked_add(step_q64)
        .ok_or(Q64Error::MultiplicationOverflow)?;
    pow_q64(base, bin_id.get()).map(Q64x64)
}

fn pow_q64(mut base: u128, exponent: i32) -> Result<u128, Q64Error> {
    const MAX_EXPONENT: u32 = 0x80_000;
    if exponent == 0 {
        return Ok(Q64x64::ONE.bits());
    }
    let exponent_abs = exponent.unsigned_abs();
    if exponent_abs >= MAX_EXPONENT {
        return Err(Q64Error::ExponentOutOfRange);
    }

    let mut invert = exponent.is_negative();
    if base >= Q64x64::ONE.bits() {
        base = u128::MAX / base;
        invert = !invert;
    }

    let mut result = Q64x64::ONE.bits();
    let mut squared = base;
    for bit in 0..19 {
        if exponent_abs & (1 << bit) != 0 {
            result = result
                .checked_mul(squared)
                .ok_or(Q64Error::MultiplicationOverflow)?
                >> 64;
        }
        if bit != 18 {
            squared = squared
                .checked_mul(squared)
                .ok_or(Q64Error::MultiplicationOverflow)?
                >> 64;
        }
    }
    if result == 0 {
        return Err(Q64Error::ZeroResult);
    }
    if invert {
        result = u128::MAX / result;
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bin_zero_is_exactly_one() {
        assert_eq!(
            price_from_bin_id(BinId::new(0), BinStep::new(25).unwrap()),
            Ok(Q64x64::ONE)
        );
    }

    #[test]
    fn positive_and_negative_prices_straddle_one() {
        let step = BinStep::new(25).unwrap();
        assert!(price_from_bin_id(BinId::new(1), step).unwrap() > Q64x64::ONE);
        assert!(price_from_bin_id(BinId::new(-1), step).unwrap() < Q64x64::ONE);
    }
}
