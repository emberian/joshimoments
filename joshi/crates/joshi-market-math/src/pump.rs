//! Pump curve and `PumpSwap` exact-base quote kernels.

use crate::{
    fee::{FeeError, FeePolicy, FeeSchedule, calculate_fees},
    profile::{ProtocolFamily, ProtocolProfile, VenueLifecycle},
    quote::{
        AssetAmount, AtomicPrice, FormulaId, MarkObservation, QuoteBinding, QuoteCalculation,
        QuoteObservationClosure, QuoteOutcome, QuoteRefusal, QuoteRequest, QuoteSize, SpotQuote,
        atoms, market_cap,
    },
    wide::{Rounding, add_signed_reserve, mul_div_floor_plus_one, mul_div_u128},
};
use joshi_accounting::amount::AtomQty;
use joshi_domain::{AssetId, ObservationId, PoolId, WireU64};

/// Exact Pump bonding-curve reserves and fee state at one observation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PumpCurveState {
    pub profile: ProtocolProfile,
    pub pool_id: PoolId,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub state_observation_id: ObservationId,
    pub fee_observation_id: ObservationId,
    pub slot: WireU64,
    pub lifecycle: VenueLifecycle,
    pub virtual_base_reserves: AtomQty,
    pub virtual_quote_reserves: AtomQty,
    pub real_base_reserves: AtomQty,
    pub real_quote_reserves: AtomQty,
    pub base_mint_supply: AtomQty,
    /// Exact observed curve mode controlling the fee-tier supply operand.
    pub is_mayhem_mode: bool,
    pub fee_policy: FeePolicy,
}

/// Exact `PumpSwap` pool and fee state at one observation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PumpSwapState {
    pub profile: ProtocolProfile,
    pub pool_id: PoolId,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub state_observation_id: ObservationId,
    pub fee_observation_id: ObservationId,
    pub slot: WireU64,
    pub lifecycle: VenueLifecycle,
    pub base_reserves: AtomQty,
    pub raw_quote_reserves: AtomQty,
    pub virtual_quote_reserves: i128,
    pub base_mint_supply: AtomQty,
    pub fee_policy: FeePolicy,
}

impl PumpCurveState {
    /// Reserve-ratio mark without executable-size meaning.
    ///
    /// # Errors
    ///
    /// Refuses an invalid zero virtual base reserve.
    pub fn mark(&self) -> Result<MarkObservation, QuoteRefusal> {
        Ok(MarkObservation {
            profile_id: self.profile.id.clone(),
            venue_id: self.profile.venue.clone(),
            pool_id: self.pool_id.clone(),
            observation_id: self.state_observation_id.clone(),
            slot: self.slot,
            base_asset_id: self.base_asset_id.clone(),
            quote_asset_id: self.quote_asset_id.clone(),
            atomic_price: AtomicPrice::new(
                u128::from(self.virtual_quote_reserves.get()),
                u128::from(self.virtual_base_reserves.get()),
            )?,
        })
    }

    /// Calculates an exact-base Pump curve quote and retains identity on success or refusal.
    #[must_use]
    pub fn calculate(&self, request: &QuoteRequest) -> QuoteCalculation {
        let calculation_binding = binding(
            request,
            &self.profile,
            &self.state_observation_id,
            &self.fee_observation_id,
            self.slot,
        );
        let outcome = match self.quote_result(request) {
            Ok(quote) => QuoteOutcome::Success(Box::new(quote)),
            Err(refusal) => QuoteOutcome::Refused(refusal),
        };
        QuoteCalculation {
            binding: calculation_binding,
            requested_size: request.size,
            outcome,
        }
    }

    fn quote_result(&self, request: &QuoteRequest) -> Result<SpotQuote, QuoteRefusal> {
        validate_common(
            request,
            &self.profile,
            &self.pool_id,
            &self.base_asset_id,
            &self.quote_asset_id,
            &self.state_observation_id,
            &self.lifecycle,
            ProtocolFamily::PumpCurve,
        )?;
        // Current SDK fixes standard curves to one billion whole tokens at six decimals for fee
        // tier selection; only mayhem mode uses the observed mint supply.
        let fee_supply = if self.is_mayhem_mode {
            self.base_mint_supply.get()
        } else {
            1_000_000_000_000_000
        };
        let market_cap = market_cap(
            u128::from(self.virtual_quote_reserves.get()),
            fee_supply,
            u128::from(self.virtual_base_reserves.get()),
        )?;
        let schedule = self.fee_policy.select(market_cap).map_err(map_fee_error)?;
        let binding = binding(
            request,
            &self.profile,
            &self.state_observation_id,
            &self.fee_observation_id,
            self.slot,
        );

        match request.size {
            QuoteSize::ExactBaseOutBuy(base_out) => {
                self.quote_buy(binding, schedule, base_out, request.size)
            }
            QuoteSize::ExactBaseInSell(base_in) => {
                self.quote_sell(binding, schedule, base_in, request.size)
            }
            QuoteSize::ExactQuoteInBuy(_) | QuoteSize::ExactQuoteOutSell(_) => {
                Err(QuoteRefusal::UnsupportedSizeKind)
            }
        }
    }

    fn quote_buy(
        &self,
        binding: QuoteBinding,
        schedule: FeeSchedule,
        base_out: AtomQty,
        requested_size: QuoteSize,
    ) -> Result<SpotQuote, QuoteRefusal> {
        if base_out == AtomQty::ZERO {
            return Err(QuoteRefusal::ZeroSize);
        }
        if base_out > self.real_base_reserves {
            return Err(QuoteRefusal::InsufficientRealBase);
        }
        if base_out >= self.virtual_base_reserves {
            return Err(QuoteRefusal::InvalidReserveState);
        }
        let denominator = self.virtual_base_reserves.get() - base_out.get();
        let raw = atoms(mul_div_floor_plus_one(
            u128::from(base_out.get()),
            u128::from(self.virtual_quote_reserves.get()),
            u128::from(denominator),
        )?)?;
        let fees = calculate_fees(raw.get(), schedule).map_err(map_fee_error)?;
        let input_atoms = raw
            .get()
            .checked_add(fees.checked_total().map_err(map_fee_error)?)
            .map(AtomQty::new)
            .ok_or(QuoteRefusal::Arithmetic)?;
        Ok(SpotQuote {
            binding,
            formula: FormulaId::PumpCurveExactBaseOutBuyV1,
            requested_size,
            input: AssetAmount {
                asset_id: self.quote_asset_id.clone(),
                atoms: input_atoms,
            },
            output: AssetAmount {
                asset_id: self.base_asset_id.clone(),
                atoms: base_out,
            },
            raw_quote_atoms: raw,
            fees,
        })
    }

    fn quote_sell(
        &self,
        binding: QuoteBinding,
        schedule: FeeSchedule,
        base_in: AtomQty,
        requested_size: QuoteSize,
    ) -> Result<SpotQuote, QuoteRefusal> {
        if base_in == AtomQty::ZERO {
            return Err(QuoteRefusal::ZeroSize);
        }
        let denominator = u128::from(self.virtual_base_reserves.get())
            .checked_add(u128::from(base_in.get()))
            .ok_or(QuoteRefusal::Arithmetic)?;
        let raw = atoms(mul_div_u128(
            u128::from(base_in.get()),
            u128::from(self.virtual_quote_reserves.get()),
            denominator,
            Rounding::Down,
        )?)?;
        if raw > self.real_quote_reserves {
            return Err(QuoteRefusal::InsufficientRealQuote);
        }
        let fees = calculate_fees(raw.get(), schedule).map_err(map_fee_error)?;
        let output_atoms = raw
            .get()
            .checked_sub(fees.checked_total().map_err(map_fee_error)?)
            .map(AtomQty::new)
            .ok_or(QuoteRefusal::FeesExceedRawOutput)?;
        Ok(SpotQuote {
            binding,
            formula: FormulaId::PumpCurveExactBaseInSellV1,
            requested_size,
            input: AssetAmount {
                asset_id: self.base_asset_id.clone(),
                atoms: base_in,
            },
            output: AssetAmount {
                asset_id: self.quote_asset_id.clone(),
                atoms: output_atoms,
            },
            raw_quote_atoms: raw,
            fees,
        })
    }
}

impl PumpSwapState {
    /// Returns the signed-virtual-adjusted quote reserve used by current `PumpSwap` formulas.
    ///
    /// # Errors
    ///
    /// Refuses a negative or overflowed result and a zero effective reserve.
    pub fn effective_quote_reserves(&self) -> Result<u128, QuoteRefusal> {
        let effective =
            add_signed_reserve(self.raw_quote_reserves.get(), self.virtual_quote_reserves)?;
        if effective == 0 {
            Err(QuoteRefusal::NonpositiveEffectiveQuoteReserve)
        } else {
            Ok(effective)
        }
    }

    /// Reserve-ratio mark without executable-size meaning.
    ///
    /// # Errors
    ///
    /// Refuses invalid effective quote or base reserves.
    pub fn mark(&self) -> Result<MarkObservation, QuoteRefusal> {
        Ok(MarkObservation {
            profile_id: self.profile.id.clone(),
            venue_id: self.profile.venue.clone(),
            pool_id: self.pool_id.clone(),
            observation_id: self.state_observation_id.clone(),
            slot: self.slot,
            base_asset_id: self.base_asset_id.clone(),
            quote_asset_id: self.quote_asset_id.clone(),
            atomic_price: AtomicPrice::new(
                self.effective_quote_reserves()?,
                u128::from(self.base_reserves.get()),
            )?,
        })
    }

    /// Calculates an exact-base `PumpSwap` quote and retains identity on success or refusal.
    #[must_use]
    pub fn calculate(&self, request: &QuoteRequest) -> QuoteCalculation {
        let calculation_binding = binding(
            request,
            &self.profile,
            &self.state_observation_id,
            &self.fee_observation_id,
            self.slot,
        );
        let outcome = match self.quote_result(request) {
            Ok(quote) => QuoteOutcome::Success(Box::new(quote)),
            Err(refusal) => QuoteOutcome::Refused(refusal),
        };
        QuoteCalculation {
            binding: calculation_binding,
            requested_size: request.size,
            outcome,
        }
    }

    fn quote_result(&self, request: &QuoteRequest) -> Result<SpotQuote, QuoteRefusal> {
        let expected_family = match self.profile.family {
            ProtocolFamily::PumpSwapCanonical => ProtocolFamily::PumpSwapCanonical,
            ProtocolFamily::PumpSwapNonCanonical => ProtocolFamily::PumpSwapNonCanonical,
            _ => return Err(QuoteRefusal::ProfileMismatch),
        };
        validate_common(
            request,
            &self.profile,
            &self.pool_id,
            &self.base_asset_id,
            &self.quote_asset_id,
            &self.state_observation_id,
            &self.lifecycle,
            expected_family,
        )?;
        match (&self.profile.family, &self.fee_policy) {
            (ProtocolFamily::PumpSwapCanonical, FeePolicy::MarketCapTiers(_))
            | (ProtocolFamily::PumpSwapNonCanonical, FeePolicy::Flat(_)) => {}
            _ => return Err(QuoteRefusal::MalformedFeeConfiguration),
        }
        let effective_quote = self.effective_quote_reserves()?;
        let market_cap = market_cap(
            effective_quote,
            self.base_mint_supply.get(),
            u128::from(self.base_reserves.get()),
        )?;
        let schedule = self.fee_policy.select(market_cap).map_err(map_fee_error)?;
        let binding = binding(
            request,
            &self.profile,
            &self.state_observation_id,
            &self.fee_observation_id,
            self.slot,
        );

        match request.size {
            QuoteSize::ExactBaseOutBuy(base_out) => {
                self.quote_buy(binding, schedule, effective_quote, base_out, request.size)
            }
            QuoteSize::ExactBaseInSell(base_in) => {
                self.quote_sell(binding, schedule, effective_quote, base_in, request.size)
            }
            QuoteSize::ExactQuoteInBuy(_) | QuoteSize::ExactQuoteOutSell(_) => {
                Err(QuoteRefusal::UnsupportedSizeKind)
            }
        }
    }

    fn quote_buy(
        &self,
        binding: QuoteBinding,
        schedule: FeeSchedule,
        effective_quote: u128,
        base_out: AtomQty,
        requested_size: QuoteSize,
    ) -> Result<SpotQuote, QuoteRefusal> {
        if base_out == AtomQty::ZERO {
            return Err(QuoteRefusal::ZeroSize);
        }
        if base_out >= self.base_reserves {
            return Err(QuoteRefusal::InsufficientRealBase);
        }
        let denominator = self.base_reserves.get() - base_out.get();
        let raw = atoms(mul_div_u128(
            effective_quote,
            u128::from(base_out.get()),
            u128::from(denominator),
            Rounding::Up,
        )?)?;
        let fees = calculate_fees(raw.get(), schedule).map_err(map_fee_error)?;
        let input_atoms = raw
            .get()
            .checked_add(fees.checked_total().map_err(map_fee_error)?)
            .map(AtomQty::new)
            .ok_or(QuoteRefusal::Arithmetic)?;
        Ok(SpotQuote {
            binding,
            formula: FormulaId::PumpSwapExactBaseOutBuyV1,
            requested_size,
            input: AssetAmount {
                asset_id: self.quote_asset_id.clone(),
                atoms: input_atoms,
            },
            output: AssetAmount {
                asset_id: self.base_asset_id.clone(),
                atoms: base_out,
            },
            raw_quote_atoms: raw,
            fees,
        })
    }

    fn quote_sell(
        &self,
        binding: QuoteBinding,
        schedule: FeeSchedule,
        effective_quote: u128,
        base_in: AtomQty,
        requested_size: QuoteSize,
    ) -> Result<SpotQuote, QuoteRefusal> {
        if base_in == AtomQty::ZERO {
            return Err(QuoteRefusal::ZeroSize);
        }
        let denominator = u128::from(self.base_reserves.get())
            .checked_add(u128::from(base_in.get()))
            .ok_or(QuoteRefusal::Arithmetic)?;
        let raw = atoms(mul_div_u128(
            effective_quote,
            u128::from(base_in.get()),
            denominator,
            Rounding::Down,
        )?)?;
        let fees = calculate_fees(raw.get(), schedule).map_err(map_fee_error)?;
        // Current official SDK capacity check retains the LP fee in the quote vault. Protocol and
        // creator components are subtracted from the user's payout but do not loosen this bound.
        let vault_debit = raw
            .get()
            .checked_sub(fees.lp_atoms)
            .map(AtomQty::new)
            .ok_or(QuoteRefusal::FeesExceedRawOutput)?;
        if vault_debit > self.raw_quote_reserves {
            return Err(QuoteRefusal::InsufficientRealQuote);
        }
        let output_atoms = raw
            .get()
            .checked_sub(fees.checked_total().map_err(map_fee_error)?)
            .map(AtomQty::new)
            .ok_or(QuoteRefusal::FeesExceedRawOutput)?;
        Ok(SpotQuote {
            binding,
            formula: FormulaId::PumpSwapExactBaseInSellV1,
            requested_size,
            input: AssetAmount {
                asset_id: self.base_asset_id.clone(),
                atoms: base_in,
            },
            output: AssetAmount {
                asset_id: self.quote_asset_id.clone(),
                atoms: output_atoms,
            },
            raw_quote_atoms: raw,
            fees,
        })
    }
}

fn binding(
    request: &QuoteRequest,
    profile: &ProtocolProfile,
    state_observation_id: &ObservationId,
    fee_observation_id: &ObservationId,
    slot: WireU64,
) -> QuoteBinding {
    QuoteBinding {
        quote_id: request.quote_id.clone(),
        intent_command_id: request.intent_command_id.clone(),
        intended_state_observation: request.intended_state_observation.clone(),
        observed: QuoteObservationClosure {
            state_observation_id: state_observation_id.clone(),
            fee_observation_id: fee_observation_id.clone(),
            slot,
        },
        profile: profile.clone(),
        venue_id: profile.venue.clone(),
        pool_id: request.pool_id.clone(),
    }
}

#[allow(clippy::too_many_arguments)]
fn validate_common(
    request: &QuoteRequest,
    profile: &ProtocolProfile,
    pool_id: &PoolId,
    base_asset_id: &AssetId,
    quote_asset_id: &AssetId,
    state_observation_id: &ObservationId,
    lifecycle: &VenueLifecycle,
    family: ProtocolFamily,
) -> Result<(), QuoteRefusal> {
    if request.expected_profile_id != profile.id || profile.family != family {
        return Err(QuoteRefusal::ProfileMismatch);
    }
    if request.venue_id != profile.venue
        || &request.pool_id != pool_id
        || &request.base_asset_id != base_asset_id
        || &request.quote_asset_id != quote_asset_id
    {
        return Err(QuoteRefusal::MarketIdentityMismatch);
    }
    if request
        .intended_state_observation
        .as_ref()
        .is_some_and(|intended| intended != state_observation_id)
    {
        return Err(QuoteRefusal::IntendedStateMismatch);
    }
    if lifecycle != &VenueLifecycle::Trading {
        return Err(QuoteRefusal::InactiveLifecycle);
    }
    Ok(())
}

const fn map_fee_error(error: FeeError) -> QuoteRefusal {
    match error {
        FeeError::CreatorFeeUnknown => QuoteRefusal::CreatorFeeApplicabilityUnknown,
        FeeError::EmptyTierTable | FeeError::UnorderedTierTable => {
            QuoteRefusal::MalformedFeeConfiguration
        }
        FeeError::RateAboveOneHundredPercent | FeeError::Arithmetic(_) => QuoteRefusal::Arithmetic,
    }
}
