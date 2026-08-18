//! Checked U256 intermediates for protocol formulas whose operands exceed `u64 * u64`.

use ruint::aliases::U256;
use thiserror::Error;

/// Direction applied at the one declared division boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Rounding {
    /// Truncate a nonnegative quotient.
    Down,
    /// Increment a nonnegative quotient when the remainder is nonzero.
    Up,
}

/// Exact wide-arithmetic failure.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum WideMathError {
    /// Division by zero has no protocol meaning.
    #[error("division by zero")]
    DivisionByZero,
    /// An operation exceeded its declared U256 intermediate.
    #[error("U256 arithmetic overflow")]
    Overflow,
    /// The exact quotient does not fit the declared result width.
    #[error("result does not fit the declared u128 width")]
    Narrowing,
}

/// Computes `lhs * rhs / denominator` with U256 multiplication and explicit rounding.
///
/// # Errors
///
/// Refuses a zero denominator, a U256 overflow, or a quotient above `u128::MAX`.
pub fn mul_div_u128(
    lhs: u128,
    rhs: u128,
    denominator: u128,
    rounding: Rounding,
) -> Result<u128, WideMathError> {
    if denominator == 0 {
        return Err(WideMathError::DivisionByZero);
    }
    let product = U256::from(lhs)
        .checked_mul(U256::from(rhs))
        .ok_or(WideMathError::Overflow)?;
    let divisor = U256::from(denominator);
    let quotient = product / divisor;
    let remainder = product % divisor;
    let rounded = match rounding {
        Rounding::Down => quotient,
        Rounding::Up if remainder == U256::ZERO => quotient,
        Rounding::Up => quotient
            .checked_add(U256::from(1_u8))
            .ok_or(WideMathError::Overflow)?,
    };
    u128::try_from(rounded).map_err(|_| WideMathError::Narrowing)
}

/// Computes the literal Pump curve operation `floor(lhs * rhs / denominator) + 1`.
///
/// This intentionally differs from ceiling division when the division is exact.
///
/// # Errors
///
/// Propagates checked division and addition failures.
pub fn mul_div_floor_plus_one(
    lhs: u128,
    rhs: u128,
    denominator: u128,
) -> Result<u128, WideMathError> {
    mul_div_u128(lhs, rhs, denominator, Rounding::Down)?
        .checked_add(1)
        .ok_or(WideMathError::Overflow)
}

/// Checked addition of a signed virtual reserve to an unsigned observed vault reserve.
///
/// # Errors
///
/// Refuses an effective reserve outside `u128`, including a negative value.
pub fn add_signed_reserve(raw: u64, virtual_reserve: i128) -> Result<u128, WideMathError> {
    let raw = i128::from(raw);
    let effective = raw
        .checked_add(virtual_reserve)
        .ok_or(WideMathError::Overflow)?;
    u128::try_from(effective).map_err(|_| WideMathError::Narrowing)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn literal_plus_one_is_not_ceil() {
        assert_eq!(mul_div_u128(6, 10, 6, Rounding::Up), Ok(10));
        assert_eq!(mul_div_floor_plus_one(6, 10, 6), Ok(11));
    }

    #[test]
    fn signed_effective_reserve_refuses_negative() {
        assert_eq!(add_signed_reserve(4, -5), Err(WideMathError::Narrowing));
        assert_eq!(add_signed_reserve(4, -4), Ok(0));
        assert_eq!(add_signed_reserve(4, 9), Ok(13));
    }
}
