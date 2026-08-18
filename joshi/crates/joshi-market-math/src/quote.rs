//! Quote identity, marks, and executable-liquidation distinctions.

use crate::{
    fee::FeeBreakdown,
    profile::ProtocolProfile,
    wide::{Rounding, WideMathError, mul_div_u128},
};
use joshi_accounting::amount::AtomQty;
use joshi_domain::{
    AssetId, CommandId, ObservationId, PoolId, ProtocolProfileId, QuoteId, VenueId, WireU64,
};
use thiserror::Error;

/// An atomic quantity with explicit asset identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssetAmount {
    pub asset_id: AssetId,
    pub atoms: AtomQty,
}

/// Supported and deliberately unsupported quote size semantics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QuoteSize {
    ExactBaseOutBuy(AtomQty),
    ExactBaseInSell(AtomQty),
    ExactQuoteInBuy(AtomQty),
    ExactQuoteOutSell(AtomQty),
}

/// Immutable operator intent and expected state identity for a quote calculation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuoteRequest {
    pub quote_id: QuoteId,
    pub intent_command_id: Option<CommandId>,
    pub intended_state_observation: Option<ObservationId>,
    pub expected_profile_id: ProtocolProfileId,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub size: QuoteSize,
}

/// Complete evidence closure used for one calculation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuoteObservationClosure {
    pub state_observation_id: ObservationId,
    pub fee_observation_id: ObservationId,
    pub slot: WireU64,
}

/// Request identity bound to the state actually observed by the calculator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuoteBinding {
    pub quote_id: QuoteId,
    pub intent_command_id: Option<CommandId>,
    pub intended_state_observation: Option<ObservationId>,
    pub observed: QuoteObservationClosure,
    pub profile: ProtocolProfile,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
}

/// Exact formula operation graph used for a successful result.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FormulaId {
    PumpCurveExactBaseOutBuyV1,
    PumpCurveExactBaseInSellV1,
    PumpSwapExactBaseOutBuyV1,
    PumpSwapExactBaseInSellV1,
}

/// Exact atomic-price ratio. The denominator is nonzero and the pair is reduced.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AtomicPrice {
    numerator_quote_atoms: u128,
    denominator_base_atoms: u128,
}

impl AtomicPrice {
    /// Creates a normalized quote-atoms/base-atoms ratio.
    ///
    /// # Errors
    ///
    /// Refuses a zero denominator.
    pub fn new(
        numerator_quote_atoms: u128,
        denominator_base_atoms: u128,
    ) -> Result<Self, QuoteRefusal> {
        if denominator_base_atoms == 0 {
            return Err(QuoteRefusal::InvalidReserveState);
        }
        let divisor = gcd(numerator_quote_atoms, denominator_base_atoms);
        Ok(Self {
            numerator_quote_atoms: numerator_quote_atoms / divisor,
            denominator_base_atoms: denominator_base_atoms / divisor,
        })
    }

    #[must_use]
    pub const fn numerator_quote_atoms(self) -> u128 {
        self.numerator_quote_atoms
    }

    #[must_use]
    pub const fn denominator_base_atoms(self) -> u128 {
        self.denominator_base_atoms
    }
}

const fn gcd(mut lhs: u128, mut rhs: u128) -> u128 {
    while rhs != 0 {
        let remainder = lhs % rhs;
        lhs = rhs;
        rhs = remainder;
    }
    if lhs == 0 { 1 } else { lhs }
}

/// A ratio-only observation. It makes no assertion about executable capacity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MarkObservation {
    pub profile_id: ProtocolProfileId,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
    pub observation_id: ObservationId,
    pub slot: WireU64,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub atomic_price: AtomicPrice,
}

/// Successful exact size-specific projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SpotQuote {
    pub binding: QuoteBinding,
    pub formula: FormulaId,
    pub requested_size: QuoteSize,
    pub input: AssetAmount,
    pub output: AssetAmount,
    /// Constant-product consideration before separately rounded fee components.
    pub raw_quote_atoms: AtomQty,
    pub fees: FeeBreakdown,
}

/// Success or refusal retained inside an immutable, evidence-bound calculation artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QuoteOutcome {
    Success(Box<SpotQuote>),
    Refused(QuoteRefusal),
}

/// Quote request bound to the state actually observed, even when calculation is refused.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuoteCalculation {
    pub binding: QuoteBinding,
    pub requested_size: QuoteSize,
    pub outcome: QuoteOutcome,
}

impl QuoteCalculation {
    /// Converts the retained outcome to an ordinary result while consuming the artifact.
    ///
    /// # Errors
    ///
    /// Returns the exact typed refusal retained by the calculation.
    pub fn into_result(self) -> Result<SpotQuote, QuoteRefusal> {
        match self.outcome {
            QuoteOutcome::Success(quote) => Ok(*quote),
            QuoteOutcome::Refused(refusal) => Err(refusal),
        }
    }
}

/// Whole-position liquidation projection constructed only from an exact sell quote.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutableLiquidation {
    quote: SpotQuote,
    full_position_atoms: AtomQty,
}

impl ExecutableLiquidation {
    /// Promotes a size-specific exact-base-in sell quote after proving it covers the full holding.
    ///
    /// # Errors
    ///
    /// Refuses marks, buy quotes, partial-size quotes, or inconsistent input identity.
    pub fn from_full_position_quote(
        quote: SpotQuote,
        full_position_atoms: AtomQty,
    ) -> Result<Self, QuoteRefusal> {
        let QuoteSize::ExactBaseInSell(requested) = quote.requested_size else {
            return Err(QuoteRefusal::NotAFullLiquidationQuote);
        };
        if requested != full_position_atoms || quote.input.atoms != full_position_atoms {
            return Err(QuoteRefusal::NotAFullLiquidationQuote);
        }
        Ok(Self {
            quote,
            full_position_atoms,
        })
    }

    #[must_use]
    pub const fn quote(&self) -> &SpotQuote {
        &self.quote
    }

    pub const fn full_position_atoms(&self) -> AtomQty {
        self.full_position_atoms
    }
}

/// Result or exact reason the requested semantics were unavailable.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum QuoteRefusal {
    #[error("quote size is zero")]
    ZeroSize,
    #[error("the requested exact-quote size path is not implemented by this formula profile")]
    UnsupportedSizeKind,
    #[error("venue lifecycle is not trading")]
    InactiveLifecycle,
    #[error("request expected a different observation than the state actually used")]
    IntendedStateMismatch,
    #[error("request profile does not match the observed calculator profile")]
    ProfileMismatch,
    #[error("request venue, pool, or asset pair does not match observed state")]
    MarketIdentityMismatch,
    #[error("virtual or effective reserves are zero or otherwise invalid")]
    InvalidReserveState,
    #[error("requested base output exceeds real base inventory")]
    InsufficientRealBase,
    #[error("requested calculation requires more real quote inventory than observed")]
    InsufficientRealQuote,
    #[error("effective signed quote reserve is nonpositive")]
    NonpositiveEffectiveQuoteReserve,
    #[error("fee configuration is malformed")]
    MalformedFeeConfiguration,
    #[error("creator-fee applicability is unknown at this observation")]
    CreatorFeeApplicabilityUnknown,
    #[error("separately rounded fees exceed raw sell output")]
    FeesExceedRawOutput,
    #[error("quote is not an exact whole-position liquidation")]
    NotAFullLiquidationQuote,
    #[error("checked protocol arithmetic failed")]
    Arithmetic,
}

impl From<WideMathError> for QuoteRefusal {
    fn from(_: WideMathError) -> Self {
        Self::Arithmetic
    }
}

/// Narrows an exact protocol quantity to a Solana atomic amount.
///
/// # Errors
///
/// Refuses a value above `u64::MAX`.
pub(crate) fn atoms(value: u128) -> Result<AtomQty, QuoteRefusal> {
    u64::try_from(value)
        .map(AtomQty::new)
        .map_err(|_| QuoteRefusal::Arithmetic)
}

/// Computes and normalizes a market-cap ratio using U256 multiplication.
///
/// # Errors
///
/// Propagates wide arithmetic failures.
pub(crate) fn market_cap(
    quote_reserve: u128,
    supply: u64,
    base_reserve: u128,
) -> Result<u128, QuoteRefusal> {
    mul_div_u128(
        quote_reserve,
        u128::from(supply),
        base_reserve,
        Rounding::Down,
    )
    .map_err(Into::into)
}
