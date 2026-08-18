//! Current Meteora DLMM dynamic-fee and amount-fee arithmetic.

use joshi_market_math::wide::{Rounding, WideMathError, mul_div_u128};
use thiserror::Error;

pub const FEE_PRECISION: u64 = 1_000_000_000;
pub const MAX_FEE_RATE: u64 = 100_000_000;

/// Validated fee rate with denominator 1,000,000,000.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DlmmFeeRate(u64);

impl DlmmFeeRate {
    /// Creates a rate within the current protocol maximum.
    ///
    /// # Errors
    ///
    /// Refuses values above `MAX_FEE_RATE`.
    pub const fn new(value: u64) -> Result<Self, DlmmFeeError> {
        if value <= MAX_FEE_RATE {
            Ok(Self(value))
        } else {
            Err(DlmmFeeError::RateAboveProtocolMaximum)
        }
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Observed dynamic-fee parameters required by the current SDK operation graph.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DynamicFeeParameters {
    pub base_factor: u16,
    pub bin_step: u16,
    pub base_fee_power_factor: u8,
    pub variable_fee_control: u32,
    pub volatility_accumulator: u32,
    pub protocol_share_bps: u16,
}

/// Dynamic-fee failure.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum DlmmFeeError {
    #[error("fee rate exceeds the current protocol maximum")]
    RateAboveProtocolMaximum,
    #[error("protocol fee share exceeds 10,000 basis points")]
    ProtocolShareAboveOneHundredPercent,
    #[error("fee arithmetic overflowed its declared width")]
    Arithmetic,
}

/// Computes the capped current DLMM total fee rate with explicit ceiling for the variable term.
///
/// # Errors
///
/// Refuses a malformed protocol share or checked arithmetic failure.
pub fn total_fee_rate(parameters: DynamicFeeParameters) -> Result<DlmmFeeRate, DlmmFeeError> {
    if parameters.protocol_share_bps > 10_000 {
        return Err(DlmmFeeError::ProtocolShareAboveOneHundredPercent);
    }
    let power = 10_u128
        .checked_pow(u32::from(parameters.base_fee_power_factor))
        .ok_or(DlmmFeeError::Arithmetic)?;
    let base_rate = u128::from(parameters.base_factor)
        .checked_mul(u128::from(parameters.bin_step))
        .and_then(|value| value.checked_mul(10))
        .and_then(|value| value.checked_mul(power))
        .ok_or(DlmmFeeError::Arithmetic)?;
    let volatility_step = u128::from(parameters.volatility_accumulator)
        .checked_mul(u128::from(parameters.bin_step))
        .ok_or(DlmmFeeError::Arithmetic)?;
    let volatility_squared = volatility_step
        .checked_mul(volatility_step)
        .ok_or(DlmmFeeError::Arithmetic)?;
    let variable_rate = mul_div_u128(
        u128::from(parameters.variable_fee_control),
        volatility_squared,
        100_000_000_000,
        Rounding::Up,
    )
    .map_err(|_: WideMathError| DlmmFeeError::Arithmetic)?;
    let rate = base_rate
        .checked_add(variable_rate)
        .ok_or(DlmmFeeError::Arithmetic)?
        .min(u128::from(MAX_FEE_RATE));
    let rate = u64::try_from(rate).map_err(|_| DlmmFeeError::Arithmetic)?;
    DlmmFeeRate::new(rate)
}

/// Fee added to a requested net input: `ceil(net * rate / (precision - rate))`.
///
/// # Errors
///
/// Refuses checked arithmetic or narrowing failure.
pub fn fee_from_net_amount(net_amount: u64, rate: DlmmFeeRate) -> Result<u64, DlmmFeeError> {
    let denominator = FEE_PRECISION
        .checked_sub(rate.get())
        .ok_or(DlmmFeeError::Arithmetic)?;
    narrow(mul_div_u128(
        u128::from(net_amount),
        u128::from(rate.get()),
        u128::from(denominator),
        Rounding::Up,
    ))
}

/// Fee included in a gross amount: `ceil(gross * rate / precision)`.
///
/// # Errors
///
/// Refuses checked arithmetic or narrowing failure.
pub fn fee_from_gross_amount(gross_amount: u64, rate: DlmmFeeRate) -> Result<u64, DlmmFeeError> {
    narrow(mul_div_u128(
        u128::from(gross_amount),
        u128::from(rate.get()),
        u128::from(FEE_PRECISION),
        Rounding::Up,
    ))
}

/// Protocol component of a realized fee, rounded down as in the current SDK.
///
/// # Errors
///
/// Refuses a share above 100% or checked arithmetic failure.
pub fn protocol_fee_amount(fee_amount: u64, share_bps: u16) -> Result<u64, DlmmFeeError> {
    if share_bps > 10_000 {
        return Err(DlmmFeeError::ProtocolShareAboveOneHundredPercent);
    }
    narrow(mul_div_u128(
        u128::from(fee_amount),
        u128::from(share_bps),
        10_000,
        Rounding::Down,
    ))
}

fn narrow(value: Result<u128, WideMathError>) -> Result<u64, DlmmFeeError> {
    u64::try_from(value.map_err(|_| DlmmFeeError::Arithmetic)?)
        .map_err(|_| DlmmFeeError::Arithmetic)
}
