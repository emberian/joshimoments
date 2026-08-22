//! The executable price stack: seven differently-typed price objects over one venue state.
//!
//! There is no universal `price`. A chart mark, the pool's marginal ratio, the average price an
//! exact clip would pay, the bound written into the instruction, a fill somebody else got, the
//! proceeds of liquidating a whole position, and the proceeds of liquidating it into a declared
//! worse state are seven different numbers about the same mint at the same instant. This module
//! computes them from one observed state and refuses to emit any of them without saying which it
//! is.
//!
//! Everything here is integer arithmetic over reserves and basis points, in the operation order
//! the deployed programs use. Nothing is a fill, an order, an execution estimate, or advice, and
//! nothing here can construct, sign, simulate, or submit a transaction.

use crate::{
    fee::{CreatorFee, FeeBreakdown, FeeSchedule},
    quote::{AtomicPrice, QuoteRefusal},
    wide::{Rounding, mul_div_u128},
};

const BASIS_POINTS_DENOMINATOR: u128 = 10_000;

/// Which of the seven price objects a number is.
///
/// The corpus's rule is that a column called `price` is not readable. Every price this module
/// emits carries one of these tags, and the tags are not interchangeable: a mark is not a quote,
/// a quote is not a fill, and a mark is never a liquidation value.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum PriceObject {
    /// Last trade printed by some participant. Not ours, and not executable at any size.
    ChartMark,
    /// The reserve ratio. The price of an infinitesimal trade and of no real one.
    MarginalPoolPrice,
    /// Average price the stated clip would pay or receive, at this state, with fees.
    ExactSizeQuote,
    /// `max_sol_cost` / `min_sol_output` as an instruction would carry it.
    InstructionBound,
    /// A price somebody's transaction actually landed at.
    ActualFill,
    /// Average price the whole position would receive if sold at once, at this state.
    FullPositionLiquidation,
    /// The same, in a state declared worse by an explicit, stated scenario.
    StressedLiquidation,
}

impl PriceObject {
    /// Stable machine label. Never abbreviate this to `price` at a boundary.
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::ChartMark => "chart_mark",
            Self::MarginalPoolPrice => "marginal_pool_price",
            Self::ExactSizeQuote => "exact_size_quote",
            Self::InstructionBound => "instruction_bound",
            Self::ActualFill => "actual_fill",
            Self::FullPositionLiquidation => "full_position_liquidation",
            Self::StressedLiquidation => "stressed_liquidation",
        }
    }
}

/// An exact ratio kept unrounded, so a reader can see what rounding would cost.
///
/// Basis points are a rendering of this, not the value. Both rounding directions are offered and
/// neither is called "the" answer.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExactRatio {
    numerator: u128,
    denominator: u128,
}

impl ExactRatio {
    /// Creates a ratio with a nonzero denominator.
    ///
    /// # Errors
    ///
    /// Refuses a zero denominator, which has no value to report.
    pub const fn new(numerator: u128, denominator: u128) -> Result<Self, StackRefusal> {
        if denominator == 0 {
            Err(StackRefusal::UndefinedRatio)
        } else {
            Ok(Self {
                numerator,
                denominator,
            })
        }
    }

    #[must_use]
    pub const fn numerator(self) -> u128 {
        self.numerator
    }

    #[must_use]
    pub const fn denominator(self) -> u128 {
        self.denominator
    }

    /// The ratio in basis points, truncated.
    ///
    /// # Errors
    ///
    /// Propagates wide-arithmetic failure.
    pub fn bps_floor(self) -> Result<u128, StackRefusal> {
        mul_div_u128(
            self.numerator,
            BASIS_POINTS_DENOMINATOR,
            self.denominator,
            Rounding::Down,
        )
        .map_err(|_| StackRefusal::Arithmetic)
    }

    /// The ratio in basis points, rounded away from zero.
    ///
    /// # Errors
    ///
    /// Propagates wide-arithmetic failure.
    pub fn bps_ceil(self) -> Result<u128, StackRefusal> {
        mul_div_u128(
            self.numerator,
            BASIS_POINTS_DENOMINATOR,
            self.denominator,
            Rounding::Up,
        )
        .map_err(|_| StackRefusal::Arithmetic)
    }
}

/// The fee-charging convention a venue's deployed instruction actually uses.
///
/// These differ in operation order, not only in rate, and the difference is observable in the
/// atoms of a landed fill. Each variant names the evidence that fixed it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VenueFormula {
    /// Pump bonding curve.
    ///
    /// A buy is denominated in base out: the raw consideration is
    /// `floor(base_out * virtual_quote / (virtual_base - base_out)) + 1`, and each fee component
    /// is `ceil()`ed on that raw consideration and charged *on top of* it. A sell is denominated
    /// in base in: the raw consideration is `floor(base_in * virtual_quote / (virtual_base +
    /// base_in))` and each component is `ceil()`ed on it and deducted from it. The whole fee
    /// leaves the curve; there is no liquidity provider to retain any of it.
    PumpBondingCurve,
    /// `PumpSwap` `BuyExactQuoteIn` / `Sell`.
    ///
    /// On a buy the caller states a total quote input. The LP component is `ceil()`ed on that
    /// total and *stays in the pool*, raising the quote reserve; the protocol and creator
    /// components are `ceil()`ed on what is left after the LP component and leave the pool. The
    /// remainder is the raw consideration. On a sell every component is `ceil()`ed on the raw
    /// consideration and deducted from it, and the LP component again stays in the pool.
    PumpSwapExactQuoteIn,
}

/// The smallest state from which both deployed constant-product formulas evaluate exactly.
///
/// This is deliberately not a claim that a bonding curve and a graduated pool are the same market.
/// It is the answer to a narrower question: what is the minimum tuple a size calculation needs?
/// A base reserve, an effective quote reserve, a fee schedule, and the venue's operation order.
/// Which reserves are "effective" is a venue fact that must be established before this struct is
/// built — a `PumpSwap` pool's effective quote reserve is not its quote vault balance.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExactCurveState {
    pub formula: VenueFormula,
    pub base_atoms: u128,
    pub effective_quote_atoms: u128,
    pub schedule: FeeSchedule,
}

/// One buy walked against one state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BuyLeg {
    /// Total quote atoms the caller parts with, fees included.
    pub quote_in_atoms: u128,
    pub base_out_atoms: u128,
    /// Constant-product consideration, before any fee component.
    pub raw_quote_atoms: u128,
    pub fees: FeeBreakdown,
    pub next: ExactCurveState,
}

/// One sell walked against one state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SellLeg {
    pub base_in_atoms: u128,
    /// Quote atoms the caller actually receives, after every fee component.
    pub quote_out_atoms: u128,
    pub raw_quote_atoms: u128,
    pub fees: FeeBreakdown,
    pub next: ExactCurveState,
}

impl ExactCurveState {
    /// The reserve ratio, and nothing more.
    ///
    /// # Errors
    ///
    /// Refuses a zero base reserve.
    pub fn marginal_pool_price(&self) -> Result<AtomicPrice, StackRefusal> {
        AtomicPrice::new(self.effective_quote_atoms, self.base_atoms).map_err(StackRefusal::Quote)
    }

    /// Walks a buy denominated in the caller's total quote spend.
    ///
    /// On `PumpSwap` this is the deployed `BuyExactQuoteIn` instruction. On the Pump bonding curve
    /// the deployed instruction is denominated in base out, so this searches for the largest base
    /// out whose total cost does not exceed the budget — which is what a client sizing a SOL
    /// budget must do anyway. The search is exact integer bisection over the same formula, so no
    /// approximation of the curve is introduced.
    ///
    /// # Errors
    ///
    /// Refuses a zero or unaffordable size, an unknown creator-fee applicability, an invalid
    /// reserve state, and arithmetic overflow.
    pub fn buy_with_quote_in(&self, quote_in_atoms: u128) -> Result<BuyLeg, StackRefusal> {
        if quote_in_atoms == 0 {
            return Err(StackRefusal::ZeroSize);
        }
        match self.formula {
            VenueFormula::PumpSwapExactQuoteIn => self.pumpswap_buy_exact_quote_in(quote_in_atoms),
            VenueFormula::PumpBondingCurve => self.curve_buy_within_budget(quote_in_atoms),
        }
    }

    /// Walks a buy denominated in exact base out, the form both programs' buy instructions take.
    ///
    /// # Errors
    ///
    /// Refuses a zero size, a size at or above the base reserve, unknown creator-fee
    /// applicability, and arithmetic overflow.
    pub fn buy_exact_base_out(&self, base_out_atoms: u128) -> Result<BuyLeg, StackRefusal> {
        if base_out_atoms == 0 {
            return Err(StackRefusal::ZeroSize);
        }
        if base_out_atoms >= self.base_atoms {
            return Err(StackRefusal::SizeExceedsReserve);
        }
        let denominator = self.base_atoms - base_out_atoms;
        let raw = match self.formula {
            // The bonding curve's literal `+ 1`, which is not ceiling division.
            VenueFormula::PumpBondingCurve => mul_div_u128(
                base_out_atoms,
                self.effective_quote_atoms,
                denominator,
                Rounding::Down,
            )
            .map_err(|_| StackRefusal::Arithmetic)?
            .checked_add(1)
            .ok_or(StackRefusal::Arithmetic)?,
            VenueFormula::PumpSwapExactQuoteIn => mul_div_u128(
                self.effective_quote_atoms,
                base_out_atoms,
                denominator,
                Rounding::Up,
            )
            .map_err(|_| StackRefusal::Arithmetic)?,
        };
        let fees = self.fees_on(raw)?;
        let total = fees.checked_total().map_err(|_| StackRefusal::Arithmetic)?;
        let quote_in_atoms = raw
            .checked_add(u128::from(total))
            .ok_or(StackRefusal::Arithmetic)?;
        let retained = self.retained_in_pool(&fees);
        Ok(BuyLeg {
            quote_in_atoms,
            base_out_atoms,
            raw_quote_atoms: raw,
            fees,
            next: Self {
                base_atoms: self.base_atoms - base_out_atoms,
                effective_quote_atoms: self
                    .effective_quote_atoms
                    .checked_add(raw)
                    .and_then(|value| value.checked_add(retained))
                    .ok_or(StackRefusal::Arithmetic)?,
                ..*self
            },
        })
    }

    /// Walks a sell denominated in exact base in, the form both programs' sell instructions take.
    ///
    /// # Errors
    ///
    /// Refuses a zero size, fees that exceed the raw consideration, unknown creator-fee
    /// applicability, and arithmetic overflow.
    pub fn sell_base_in(&self, base_in_atoms: u128) -> Result<SellLeg, StackRefusal> {
        if base_in_atoms == 0 {
            return Err(StackRefusal::ZeroSize);
        }
        let denominator = self
            .base_atoms
            .checked_add(base_in_atoms)
            .ok_or(StackRefusal::Arithmetic)?;
        let raw = mul_div_u128(
            base_in_atoms,
            self.effective_quote_atoms,
            denominator,
            Rounding::Down,
        )
        .map_err(|_| StackRefusal::Arithmetic)?;
        let fees = self.fees_on(raw)?;
        let total = u128::from(fees.checked_total().map_err(|_| StackRefusal::Arithmetic)?);
        let quote_out_atoms = raw
            .checked_sub(total)
            .ok_or(StackRefusal::FeesExceedProceeds)?;
        let retained = self.retained_in_pool(&fees);
        let leaving = raw
            .checked_sub(retained)
            .ok_or(StackRefusal::FeesExceedProceeds)?;
        Ok(SellLeg {
            base_in_atoms,
            quote_out_atoms,
            raw_quote_atoms: raw,
            fees,
            next: Self {
                base_atoms: denominator,
                effective_quote_atoms: self
                    .effective_quote_atoms
                    .checked_sub(leaving)
                    .ok_or(StackRefusal::ReserveWouldGoNegative)?,
                ..*self
            },
        })
    }

    fn pumpswap_buy_exact_quote_in(&self, quote_in_atoms: u128) -> Result<BuyLeg, StackRefusal> {
        let lp = component(quote_in_atoms, u128::from(self.schedule.lp.get()))?;
        let after_lp = quote_in_atoms
            .checked_sub(lp)
            .ok_or(StackRefusal::FeesExceedProceeds)?;
        let protocol = component(after_lp, u128::from(self.schedule.protocol.get()))?;
        let creator = match self.schedule.creator {
            CreatorFee::NotApplicable => 0,
            CreatorFee::Charged(rate) => component(after_lp, u128::from(rate.get()))?,
            CreatorFee::Unknown => return Err(StackRefusal::CreatorFeeApplicabilityUnknown),
        };
        let raw = after_lp
            .checked_sub(protocol)
            .and_then(|value| value.checked_sub(creator))
            .ok_or(StackRefusal::FeesExceedProceeds)?;
        let quote_denominator = self
            .effective_quote_atoms
            .checked_add(raw)
            .ok_or(StackRefusal::Arithmetic)?;
        let base_out_atoms = mul_div_u128(self.base_atoms, raw, quote_denominator, Rounding::Down)
            .map_err(|_| StackRefusal::Arithmetic)?;
        if base_out_atoms == 0 {
            return Err(StackRefusal::SizeRoundsToNothing);
        }
        if base_out_atoms >= self.base_atoms {
            return Err(StackRefusal::SizeExceedsReserve);
        }
        Ok(BuyLeg {
            quote_in_atoms,
            base_out_atoms,
            raw_quote_atoms: raw,
            fees: narrow(lp, protocol, creator)?,
            next: Self {
                base_atoms: self.base_atoms - base_out_atoms,
                effective_quote_atoms: quote_denominator
                    .checked_add(lp)
                    .ok_or(StackRefusal::Arithmetic)?,
                ..*self
            },
        })
    }

    /// Largest base out whose total cost fits the budget, by exact bisection over the same formula.
    fn curve_buy_within_budget(&self, budget_atoms: u128) -> Result<BuyLeg, StackRefusal> {
        let mut low = 1_u128;
        let mut high = self.base_atoms - 1;
        if self.buy_exact_base_out(low)?.quote_in_atoms > budget_atoms {
            return Err(StackRefusal::BudgetBelowSmallestSize);
        }
        while low < high {
            let mid = low + (high - low).div_ceil(2);
            if self.buy_exact_base_out(mid)?.quote_in_atoms <= budget_atoms {
                low = mid;
            } else {
                high = mid - 1;
            }
        }
        self.buy_exact_base_out(low)
    }

    fn fees_on(&self, raw: u128) -> Result<FeeBreakdown, StackRefusal> {
        let creator = match self.schedule.creator {
            CreatorFee::NotApplicable => 0,
            CreatorFee::Charged(rate) => component(raw, u128::from(rate.get()))?,
            CreatorFee::Unknown => return Err(StackRefusal::CreatorFeeApplicabilityUnknown),
        };
        narrow(
            component(raw, u128::from(self.schedule.lp.get()))?,
            component(raw, u128::from(self.schedule.protocol.get()))?,
            creator,
        )
    }

    /// The fee component that never leaves the pool, and so raises the reserve.
    const fn retained_in_pool(&self, fees: &FeeBreakdown) -> u128 {
        match self.formula {
            // No provider exists on the curve; the whole fee is swept out.
            VenueFormula::PumpBondingCurve => 0,
            VenueFormula::PumpSwapExactQuoteIn => fees.lp_atoms as u128,
        }
    }
}

fn component(base: u128, bps: u128) -> Result<u128, StackRefusal> {
    mul_div_u128(base, bps, BASIS_POINTS_DENOMINATOR, Rounding::Up)
        .map_err(|_| StackRefusal::Arithmetic)
}

fn narrow(lp: u128, protocol: u128, creator: u128) -> Result<FeeBreakdown, StackRefusal> {
    Ok(FeeBreakdown {
        lp_atoms: u64::try_from(lp).map_err(|_| StackRefusal::Arithmetic)?,
        protocol_atoms: u64::try_from(protocol).map_err(|_| StackRefusal::Arithmetic)?,
        creator_atoms: u64::try_from(creator).map_err(|_| StackRefusal::Arithmetic)?,
    })
}

/// Operator-declared tolerance written into an instruction bound.
///
/// This is an input, not a measurement. It says how much worse than the quote the caller is
/// willing to have the transaction land, and it is the only number in the stack that comes from a
/// preference rather than from bytes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DeclaredToleranceBps(u16);

impl DeclaredToleranceBps {
    /// Creates a tolerance no greater than 100%.
    ///
    /// # Errors
    ///
    /// Refuses values above 10,000 basis points.
    pub const fn new(value: u16) -> Result<Self, StackRefusal> {
        if value <= 10_000 {
            Ok(Self(value))
        } else {
            Err(StackRefusal::ToleranceAboveOneHundredPercent)
        }
    }

    #[must_use]
    pub const fn get(self) -> u16 {
        self.0
    }
}

/// One declared way the state could be worse when a position is finally liquidated.
///
/// This is a scenario, not a forecast and not a measurement. It is stated as other participants'
/// *net selling*, in base atoms, walked through the same deployed formula — so the worse state is
/// produced by the venue's own arithmetic rather than by a haircut someone chose.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DeclaredStress {
    pub other_net_base_sold_atoms: u128,
}

/// The seven lines, for one mint and one direction, at one observed state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PriceStack {
    pub state: ExactCurveState,
    /// Last landed fill somebody else got, when one was observed. `None` is an absent record and
    /// never evidence that no trade happened.
    pub chart_mark: Option<AtomicPrice>,
    pub marginal_pool_price: AtomicPrice,
    /// Average price of the intended clip, and the clip that produced it.
    pub intended_clip: SizedQuote,
    /// Average price of liquidating the whole runner at this state.
    pub full_runner: SizedQuote,
    /// `max_sol_cost` the intended clip's buy instruction would carry at the declared tolerance.
    pub buy_instruction_max_quote_in_atoms: u128,
    /// `min_sol_output` the full runner's sell instruction would carry at the declared tolerance.
    pub sell_instruction_min_quote_out_atoms: u128,
    /// Average price of liquidating the whole runner after the declared stress.
    pub stressed_liquidation: SizedQuote,
    pub declared_tolerance: DeclaredToleranceBps,
    pub declared_stress: DeclaredStress,
}

/// An average price that only means anything with its size attached.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SizedQuote {
    pub object: PriceObject,
    pub base_atoms: u128,
    pub quote_atoms: u128,
    /// Quote atoms per base atom, averaged over the whole size.
    pub average_price: AtomicPrice,
}

impl SizedQuote {
    fn new(object: PriceObject, base_atoms: u128, quote_atoms: u128) -> Result<Self, StackRefusal> {
        Ok(Self {
            object,
            base_atoms,
            quote_atoms,
            average_price: AtomicPrice::new(quote_atoms, base_atoms)
                .map_err(StackRefusal::Quote)?,
        })
    }
}

impl PriceStack {
    /// Builds the whole stack for one clip and one runner against one observed state.
    ///
    /// # Errors
    ///
    /// Propagates every refusal of the underlying exact arithmetic.
    pub fn build(
        state: ExactCurveState,
        chart_mark: Option<AtomicPrice>,
        clip_quote_in_atoms: u128,
        runner_base_atoms: u128,
        declared_tolerance: DeclaredToleranceBps,
        declared_stress: DeclaredStress,
    ) -> Result<Self, StackRefusal> {
        let buy = state.buy_with_quote_in(clip_quote_in_atoms)?;
        let runner = state.sell_base_in(runner_base_atoms)?;
        let stressed_state = state
            .sell_base_in(declared_stress.other_net_base_sold_atoms)?
            .next;
        let stressed = stressed_state.sell_base_in(runner_base_atoms)?;
        Ok(Self {
            state,
            chart_mark,
            marginal_pool_price: state.marginal_pool_price()?,
            intended_clip: SizedQuote::new(
                PriceObject::ExactSizeQuote,
                buy.base_out_atoms,
                buy.quote_in_atoms,
            )?,
            full_runner: SizedQuote::new(
                PriceObject::FullPositionLiquidation,
                runner.base_in_atoms,
                runner.quote_out_atoms,
            )?,
            buy_instruction_max_quote_in_atoms: widen(
                buy.quote_in_atoms,
                declared_tolerance,
                Rounding::Up,
            )?,
            sell_instruction_min_quote_out_atoms: narrow_bound(
                runner.quote_out_atoms,
                declared_tolerance,
            )?,
            stressed_liquidation: SizedQuote::new(
                PriceObject::StressedLiquidation,
                stressed.base_in_atoms,
                stressed.quote_out_atoms,
            )?,
            declared_tolerance,
            declared_stress,
        })
    }

    /// The gap between the marginal price and the clip's average price, in basis points.
    ///
    /// The corpus calls the gap between these lines a state variable, not an accounting detail.
    ///
    /// # Errors
    ///
    /// Propagates wide-arithmetic failure.
    pub fn clip_gap_over_marginal(&self) -> Result<ExactRatio, StackRefusal> {
        gap(self.marginal_pool_price, self.intended_clip.average_price)
    }

    /// The gap between the marginal price and what the whole runner would actually fetch.
    ///
    /// # Errors
    ///
    /// Propagates wide-arithmetic failure.
    pub fn runner_gap_under_marginal(&self) -> Result<ExactRatio, StackRefusal> {
        gap(self.full_runner.average_price, self.marginal_pool_price)
    }

    /// The gap between the unstressed and stressed liquidation of the same position.
    ///
    /// # Errors
    ///
    /// Propagates wide-arithmetic failure.
    pub fn stress_gap(&self) -> Result<ExactRatio, StackRefusal> {
        gap(
            self.stressed_liquidation.average_price,
            self.full_runner.average_price,
        )
    }
}

/// `(high - low) / low`, exactly, for two ratios that share no denominator.
fn gap(low: AtomicPrice, high: AtomicPrice) -> Result<ExactRatio, StackRefusal> {
    let cross_high = high
        .numerator_quote_atoms()
        .checked_mul(low.denominator_base_atoms())
        .ok_or(StackRefusal::Arithmetic)?;
    let cross_low = low
        .numerator_quote_atoms()
        .checked_mul(high.denominator_base_atoms())
        .ok_or(StackRefusal::Arithmetic)?;
    ExactRatio::new(cross_high.saturating_sub(cross_low), cross_low)
}

fn widen(
    value: u128,
    tolerance: DeclaredToleranceBps,
    rounding: Rounding,
) -> Result<u128, StackRefusal> {
    let bump = mul_div_u128(
        value,
        u128::from(tolerance.get()),
        BASIS_POINTS_DENOMINATOR,
        rounding,
    )
    .map_err(|_| StackRefusal::Arithmetic)?;
    value.checked_add(bump).ok_or(StackRefusal::Arithmetic)
}

fn narrow_bound(value: u128, tolerance: DeclaredToleranceBps) -> Result<u128, StackRefusal> {
    let cut = mul_div_u128(
        value,
        u128::from(tolerance.get()),
        BASIS_POINTS_DENOMINATOR,
        Rounding::Up,
    )
    .map_err(|_| StackRefusal::Arithmetic)?;
    Ok(value.saturating_sub(cut))
}

/// Exactly why a stack line could not be produced. An absent line is never a zero.
#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum StackRefusal {
    #[error("size is zero")]
    ZeroSize,
    #[error("size is at or above the observed reserve")]
    SizeExceedsReserve,
    #[error("the stated budget buys zero base atoms at this state")]
    SizeRoundsToNothing,
    #[error("the stated budget is below the cost of one base atom")]
    BudgetBelowSmallestSize,
    #[error("separately rounded fees exceed the raw consideration")]
    FeesExceedProceeds,
    #[error("the walk would drive a reserve below zero")]
    ReserveWouldGoNegative,
    #[error("creator-fee applicability is unknown at this observation")]
    CreatorFeeApplicabilityUnknown,
    #[error("declared tolerance exceeds 10,000 basis points")]
    ToleranceAboveOneHundredPercent,
    #[error("a ratio has a zero denominator")]
    UndefinedRatio,
    #[error("checked protocol arithmetic failed")]
    Arithmetic,
    #[error(transparent)]
    Quote(#[from] QuoteRefusal),
}
