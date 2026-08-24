//! Recovering the reserve pair a polled trade row walked, from the row's own three stated legs.
//!
//! A polled trades page states no reserve on any row. It states three things per fill: the
//! trader's quote leg (`quoteAmount`), the base leg (`baseAmount`), and the pool's post-trade
//! marginal price (`priceSol`), the last to roughly forty decimal digits. Those three numbers
//! overdetermine the pre-trade reserve pair under the deployed `PumpSwap` arithmetic: the base
//! leg pins the reserve pair to a narrow band through the exact constant-product floor, and the
//! stated post-trade price — carrying far more digits than one atom of either reserve moves it —
//! selects the pair inside that band. This module solves for that pair with exact integer
//! arithmetic and refuses every row the algebra cannot pin.
//!
//! What keeps the derivation honest:
//!
//! * **The solution is checked, never assumed.** Every derived pair is walked back through the
//!   deployed formula ([`ExactCurveState::buy_with_quote_in`] / [`ExactCurveState::sell_base_in`])
//!   and must reproduce the row's stated legs to the atom, and its post-trade marginal must sit
//!   inside the half-open interval the row's own truncated price literal denotes.
//! * **An under-determined row is a refusal, not a guess.** A dust-sized fill moves the price by
//!   less than the literal resolves, so many reserve pairs reproduce it; such a row is refused
//!   with the width of the ambiguity, and nothing downstream sees a state for it.
//! * **Consecutive derivations falsify each other.** [`check_derived_evolution`] walks each
//!   derived post-state through the next row's stated legs and asks whether it lands on the next
//!   derived post-state. A wrong declared fee schedule, a wrong derivation, or a fill the page
//!   never showed all break specific pairs, and the count of broken pairs is the finding.
//!
//! Nothing here reads a network. Input is bytes a recorder retained; output is arithmetic.

use joshi_market_math::{
    fee::{CreatorFee, FeeSchedule},
    stack::{ExactCurveState, StackRefusal, VenueFormula},
    wide::{Rounding, mul_div_u128},
};
use ruint::aliases::U256;
use thiserror::Error;

/// Which leg the trader took, as the provider states it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TradeDirection {
    Buy,
    Sell,
}

impl TradeDirection {
    /// Stable machine label.
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Buy => "buy",
            Self::Sell => "sell",
        }
    }
}

/// The most significant digits a stated price is compared through.
///
/// Thirty significant digits resolve one part in 10^30 — so much finer than one atom of either
/// reserve that the price interval admits essentially one integer reserve pair — while the
/// numerator still fits a `u128` and every cross-multiplication fits the U256 intermediates.
pub const PRICE_DIGITS_KEPT: u32 = 30;

/// Widest power-of-ten denominator the exact comparisons accept after truncation.
const MAX_DENOMINATOR_POW10: u32 = 33;

/// Hard ceiling on the local integer search, in quote atoms either side of the algebraic centre.
/// A row whose admissible band is wider than this cannot be pinned and is refused instead. The
/// scan is an O(1)-per-atom modular walk, so even this ceiling is under a second; the band
/// grows as the inverse square of the fill size, so what it excludes is sub-dust.
const MAX_SEARCH_HALF_WIDTH: u128 = 134_217_728;

/// A provider price literal as an exact half-open rational interval, in atom units.
///
/// The provider prints its decimal to more digits than any atom of reserve moves it. The literal
/// is treated as a truncation: the true ratio lies in `[numerator/denominator,
/// (numerator+1)/denominator)`. Truncating the literal further (to [`PRICE_DIGITS_KEPT`]
/// significant digits) only widens that interval, so the true pair always remains inside it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StatedPostPrice {
    /// Numerator of the interval's lower end, in quote atoms per base atom.
    pub numerator: u128,
    /// Power-of-ten denominator.
    pub denominator: u128,
    /// Significant digits the comparison kept.
    pub digits_kept: u32,
    /// Significant digits the literal stated beyond the kept ones. Dropped, and said so.
    pub digits_dropped: u32,
}

/// One derived reserve pair, verified against the row that produced it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DerivedTradeState {
    /// The reserve pair the trade walked from.
    pub pre: ExactCurveState,
    /// The reserve pair the trade left, from the deployed walk. This is the state a replay
    /// prices against, exactly as a retained websocket frame states post-trade reserves.
    pub post: ExactCurveState,
    /// How many quote atoms either side of the algebraic centre the exact search covered.
    pub searched_half_width: u128,
    /// Distinct admissible pre-quote values the search found. Always 1 here; more is a refusal.
    pub admissible: u32,
}

/// Exactly why a row could not be turned into a reserve pair. Refused, never guessed.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum DeriveRefusal {
    #[error("{literal:?} is not a plain nonnegative decimal literal")]
    NotADecimalLiteral { literal: String },
    #[error("{literal:?} states a zero price, which no reserve pair produces")]
    ZeroPrice { literal: String },
    #[error(
        "{literal:?} scales to a comparison denominator wider than 10^{MAX_DENOMINATOR_POW10}, \
         which the exact cross-multiplications refuse rather than round"
    )]
    PriceOutOfExactRange { literal: String },
    #[error("a stated leg is zero; a fill that moved nothing pins nothing")]
    ZeroLeg,
    #[error("the declared fee schedule consumes the whole stated quote leg")]
    FeeExceedsLeg,
    #[error("the creator-fee applicability is unknown, so the deployed fee walk cannot be taken")]
    CreatorFeeUnknown,
    #[error(
        "no raw consideration under the declared fee schedule returns the stated quote leg; the \
         nearest miss is {nearest_miss_atoms} atoms away"
    )]
    NoRawMatchesTheSellLeg { nearest_miss_atoms: u128 },
    #[error(
        "the stated legs sit on the wrong side of the stated post price for a {direction} under \
         the declared fee schedule; no reserve pair is consistent with all three"
    )]
    LegsContradictPrice { direction: &'static str },
    #[error(
        "the admissible pre-quote band is about {band_quote_atoms} atoms wide, beyond the \
         {MAX_SEARCH_HALF_WIDTH}-atom search ceiling: this fill is too small to pin the pool, \
         and a guessed pair would be fabrication"
    )]
    TooSmallToPin { band_quote_atoms: u128 },
    #[error(
        "no reserve pair inside the searched band reproduces the stated legs and price to the \
         atom under the declared fee schedule"
    )]
    NoStateReproducesTheRow,
    #[error(
        "{candidates} materially different reserve pairs reproduce the stated legs and price, \
         so the row under-determines the pool and is refused rather than picked from"
    )]
    Ambiguous { candidates: u32 },
    #[error("checked arithmetic failed while deriving")]
    Arithmetic,
    #[error(transparent)]
    Stack(#[from] StackRefusal),
}

/// Parses a provider price literal into the exact interval it denotes, in atom units.
///
/// The literal states quote per base in whole units; atoms differ by
/// `10^(quote_decimals - base_decimals)`. The literal's own digits are shifted, never a float.
///
/// # Errors
///
/// Refuses non-decimal literals, zero prices, and prices outside the exact comparison range.
pub fn stated_post_price(
    literal: &str,
    quote_decimals: u8,
    base_decimals: u8,
) -> Result<StatedPostPrice, DeriveRefusal> {
    let trimmed = literal.trim();
    let not_decimal = || DeriveRefusal::NotADecimalLiteral {
        literal: literal.to_owned(),
    };
    if trimmed.is_empty() || trimmed.starts_with('-') || trimmed.starts_with('+') {
        return Err(not_decimal());
    }
    let (whole, fraction) = match trimmed.split_once('.') {
        Some((whole, fraction)) => (whole, fraction),
        None => (trimmed, ""),
    };
    if (whole.is_empty() && fraction.is_empty())
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || !fraction.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(not_decimal());
    }
    // Value = digits / 10^fraction_len, in whole units. In atom units multiply by
    // 10^(quote_decimals - base_decimals).
    let mut digits: Vec<u8> = whole
        .bytes()
        .chain(fraction.bytes())
        .map(|byte| byte - b'0')
        .skip_while(|&digit| digit == 0)
        .collect();
    if digits.is_empty() {
        return Err(DeriveRefusal::ZeroPrice {
            literal: literal.to_owned(),
        });
    }
    let mut denominator_pow = i64::try_from(fraction.len()).map_err(|_| not_decimal())?
        - (i64::from(quote_decimals) - i64::from(base_decimals));
    while denominator_pow < 0 {
        digits.push(0);
        denominator_pow += 1;
    }
    let mut dropped = 0_u32;
    let kept_len = usize::try_from(PRICE_DIGITS_KEPT).unwrap_or(30);
    while digits.len() > kept_len && denominator_pow > 0 {
        digits.pop();
        denominator_pow -= 1;
        dropped += 1;
    }
    let denominator_pow = u32::try_from(denominator_pow).map_err(|_| not_decimal())?;
    if denominator_pow > MAX_DENOMINATOR_POW10 || digits.len() > 38 {
        return Err(DeriveRefusal::PriceOutOfExactRange {
            literal: literal.to_owned(),
        });
    }
    let mut numerator = 0_u128;
    for digit in &digits {
        numerator = numerator
            .checked_mul(10)
            .and_then(|value| value.checked_add(u128::from(*digit)))
            .ok_or(DeriveRefusal::PriceOutOfExactRange {
                literal: literal.to_owned(),
            })?;
    }
    if numerator == 0 {
        return Err(DeriveRefusal::ZeroPrice {
            literal: literal.to_owned(),
        });
    }
    Ok(StatedPostPrice {
        numerator,
        denominator: 10_u128
            .checked_pow(denominator_pow)
            .ok_or(DeriveRefusal::Arithmetic)?,
        digits_kept: u32::try_from(digits.len()).unwrap_or(u32::MAX),
        digits_dropped: dropped,
    })
}

/// One row's legs on the CURVE's own side of the fee: the raw constant-product consideration,
/// the part of the fee that stays in the pool, and the base moved.
///
/// A provider may state the trader's leg or the curve's leg, and one tape has been measured
/// mixing the two row by row; whoever loads the tape resolves the stated quote into curve legs
/// under each declared convention and lets exact reproduction pick. The reserve evolution
/// depends only on these.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CurveLegs {
    pub direction: TradeDirection,
    /// Constant-product consideration, before any fee component.
    pub raw_quote_atoms: u128,
    /// The fee component that stays in the pool and raises the quote reserve.
    pub lp_retained_atoms: u128,
    pub base_atoms: u128,
}

/// Derives the reserve pair one `PumpSwap` trade walked, from its curve legs and stated post
/// price. This is the core solver; the constraints it enforces — the deployed constant-product
/// floor on the base leg and containment in the price literal's exact interval — are the
/// deployed formula's own defining relations, so nothing further exists to verify against.
///
/// `schedule_for_pricing` is stamped onto the returned states for DOWNSTREAM would-quotes only;
/// it plays no part in the derivation.
///
/// # Errors
///
/// Refuses zero legs, contradictory legs, rows too small to pin the pool, rows no pair
/// reproduces, and rows more than one materially different pair reproduces.
pub fn derive_pumpswap_state_from_curve_legs(
    legs: &CurveLegs,
    price: &StatedPostPrice,
    schedule_for_pricing: FeeSchedule,
) -> Result<DerivedTradeState, DeriveRefusal> {
    if legs.raw_quote_atoms == 0 || legs.base_atoms == 0 {
        return Err(DeriveRefusal::ZeroLeg);
    }
    let (chosen, searched, admissible) = match legs.direction {
        TradeDirection::Buy => solve_buy(
            legs.raw_quote_atoms,
            legs.lp_retained_atoms,
            legs.base_atoms,
            price,
        )?,
        TradeDirection::Sell => {
            let mut candidates = Vec::new();
            let searched = solve_sell_scan(
                legs.raw_quote_atoms,
                legs.lp_retained_atoms,
                legs.base_atoms,
                price,
                &mut candidates,
            )?;
            settle(candidates, searched)?
        }
    };
    assemble(legs, &chosen, searched, admissible, schedule_for_pricing)
}

/// The derived pre and analytically evolved post states, stamped with the pricing schedule.
fn assemble(
    legs: &CurveLegs,
    chosen: &Candidate,
    searched: u128,
    admissible: u32,
    schedule: FeeSchedule,
) -> Result<DerivedTradeState, DeriveRefusal> {
    let pre = ExactCurveState {
        formula: VenueFormula::PumpSwapExactQuoteIn,
        base_atoms: chosen.pre_base,
        effective_quote_atoms: chosen.pre_quote,
        schedule,
    };
    let post = evolve(&pre, legs).ok_or(DeriveRefusal::Arithmetic)?;
    Ok(DerivedTradeState {
        pre,
        post,
        searched_half_width: searched,
        admissible,
    })
}

/// Applies one row's curve legs to a state, exactly as the deployed step moves the reserves.
#[must_use]
pub fn evolve(state: &ExactCurveState, legs: &CurveLegs) -> Option<ExactCurveState> {
    let (base_atoms, effective_quote_atoms) = match legs.direction {
        TradeDirection::Buy => (
            state.base_atoms.checked_sub(legs.base_atoms)?,
            state
                .effective_quote_atoms
                .checked_add(legs.raw_quote_atoms)?
                .checked_add(legs.lp_retained_atoms)?,
        ),
        TradeDirection::Sell => (
            state.base_atoms.checked_add(legs.base_atoms)?,
            state
                .effective_quote_atoms
                .checked_add(legs.lp_retained_atoms)?
                .checked_sub(legs.raw_quote_atoms)?,
        ),
    };
    Some(ExactCurveState {
        base_atoms,
        effective_quote_atoms,
        ..*state
    })
}

/// Derives the reserve pair one `PumpSwap` trade row walked, reading the stated quote as the
/// TRADER's leg under the given fee schedule — total quote in on a buy, quote received after
/// every fee on a sell — and verifying the result by walking the deployed instruction whole.
///
/// # Errors
///
/// Refuses zero legs, contradictory legs, rows too small to pin the pool, rows no pair
/// reproduces, and rows more than one materially different pair reproduces.
pub fn derive_pumpswap_state(
    direction: TradeDirection,
    trader_quote_atoms: u128,
    base_atoms: u128,
    price: &StatedPostPrice,
    schedule: FeeSchedule,
) -> Result<DerivedTradeState, DeriveRefusal> {
    if trader_quote_atoms == 0 || base_atoms == 0 {
        return Err(DeriveRefusal::ZeroLeg);
    }
    match direction {
        TradeDirection::Buy => {
            let (raw, lp) = buy_split(trader_quote_atoms, schedule)?;
            let legs = CurveLegs {
                direction,
                raw_quote_atoms: raw,
                lp_retained_atoms: lp,
                base_atoms,
            };
            let derived = derive_pumpswap_state_from_curve_legs(&legs, price, schedule)?;
            let walked = derived.pre.buy_with_quote_in(trader_quote_atoms)?;
            if walked.base_out_atoms != base_atoms || walked.next != derived.post {
                return Err(DeriveRefusal::NoStateReproducesTheRow);
            }
            Ok(derived)
        }
        TradeDirection::Sell => {
            let mut candidates = Vec::new();
            let mut widest = 0_u128;
            let mut last_refusal = DeriveRefusal::NoStateReproducesTheRow;
            for raw in sell_raws(trader_quote_atoms, schedule)? {
                let lp = fee_up(raw, u128::from(schedule.lp.get()))?;
                match solve_sell_scan(raw, lp, base_atoms, price, &mut candidates) {
                    Ok(searched) => widest = widest.max(searched),
                    Err(refusal) => last_refusal = refusal,
                }
            }
            if candidates.is_empty() {
                return Err(last_refusal);
            }
            let (chosen, _, admissible) = settle(candidates, widest)?;
            let pre = ExactCurveState {
                formula: VenueFormula::PumpSwapExactQuoteIn,
                base_atoms: chosen.pre_base,
                effective_quote_atoms: chosen.pre_quote,
                schedule,
            };
            let walked = pre.sell_base_in(base_atoms)?;
            if walked.quote_out_atoms != trader_quote_atoms {
                return Err(DeriveRefusal::NoStateReproducesTheRow);
            }
            Ok(DerivedTradeState {
                pre,
                post: walked.next,
                searched_half_width: widest,
                admissible,
            })
        }
    }
}

/// One fee component, ceiled on its base exactly as the deployed instruction ceils it.
fn fee_up(base: u128, bps: u128) -> Result<u128, DeriveRefusal> {
    mul_div_u128(base, bps, 10_000, Rounding::Up).map_err(|_| DeriveRefusal::Arithmetic)
}

fn creator_bps(schedule: FeeSchedule) -> Result<u128, DeriveRefusal> {
    match schedule.creator {
        CreatorFee::NotApplicable => Ok(0),
        CreatorFee::Charged(rate) => Ok(u128::from(rate.get())),
        CreatorFee::Unknown => Err(DeriveRefusal::CreatorFeeUnknown),
    }
}

/// The deployed `BuyExactQuoteIn` fee split of a stated total quote input.
fn buy_split(quote_in: u128, schedule: FeeSchedule) -> Result<(u128, u128), DeriveRefusal> {
    let lp = fee_up(quote_in, u128::from(schedule.lp.get()))?;
    let after_lp = quote_in
        .checked_sub(lp)
        .ok_or(DeriveRefusal::FeeExceedsLeg)?;
    let protocol = fee_up(after_lp, u128::from(schedule.protocol.get()))?;
    let creator = fee_up(after_lp, creator_bps(schedule)?)?;
    let raw = after_lp
        .checked_sub(protocol)
        .and_then(|value| value.checked_sub(creator))
        .ok_or(DeriveRefusal::FeeExceedsLeg)?;
    if raw == 0 {
        return Err(DeriveRefusal::FeeExceedsLeg);
    }
    Ok((raw, lp))
}

/// The raw considerations whose deployed sell fee split returns exactly the stated quote out.
fn sell_raws(quote_out: u128, schedule: FeeSchedule) -> Result<Vec<u128>, DeriveRefusal> {
    let total_bps = u128::from(schedule.lp.get())
        + u128::from(schedule.protocol.get())
        + creator_bps(schedule)?;
    if total_bps >= 10_000 {
        return Err(DeriveRefusal::FeeExceedsLeg);
    }
    let centre = mul_div_u128(quote_out, 10_000, 10_000 - total_bps, Rounding::Down)
        .map_err(|_| DeriveRefusal::Arithmetic)?;
    let creator = creator_bps(schedule)?;
    let mut raws = Vec::new();
    let mut nearest = u128::MAX;
    for candidate in centre.saturating_sub(8)..=centre.saturating_add(8) {
        if candidate == 0 {
            continue;
        }
        let fee = fee_up(candidate, u128::from(schedule.lp.get()))?
            .checked_add(fee_up(candidate, u128::from(schedule.protocol.get()))?)
            .and_then(|value| value.checked_add(fee_up(candidate, creator).ok()?))
            .ok_or(DeriveRefusal::Arithmetic)?;
        let Some(out) = candidate.checked_sub(fee) else {
            continue;
        };
        if out == quote_out {
            raws.push(candidate);
        } else {
            nearest = nearest.min(out.abs_diff(quote_out));
        }
    }
    if raws.is_empty() {
        return Err(DeriveRefusal::NoRawMatchesTheSellLeg {
            nearest_miss_atoms: nearest,
        });
    }
    Ok(raws)
}

fn wide(value: u128) -> U256 {
    U256::from(value)
}

fn narrow(value: U256) -> Result<u128, DeriveRefusal> {
    u128::try_from(value).map_err(|_| DeriveRefusal::Arithmetic)
}

/// One admissible pre-trade pair the exact scan found.
struct Candidate {
    pre_quote: u128,
    pre_base: u128,
}

/// Collects candidates over the scanned band and enforces the one-pair rule.
fn settle(
    mut candidates: Vec<Candidate>,
    searched_half_width: u128,
) -> Result<(Candidate, u128, u32), DeriveRefusal> {
    if candidates.is_empty() {
        return Err(DeriveRefusal::NoStateReproducesTheRow);
    }
    candidates.sort_by_key(|candidate| candidate.pre_quote);
    let spread_quote = candidates[candidates.len() - 1]
        .pre_quote
        .abs_diff(candidates[0].pre_quote);
    let spread_base = candidates[candidates.len() - 1]
        .pre_base
        .abs_diff(candidates[0].pre_base);
    let count = u32::try_from(candidates.len()).unwrap_or(u32::MAX);
    // Candidates within one part per billion of either reserve are one state to every
    // downstream would-quote at desk clip sizes; anything wider under-determines the pool.
    let same_state = spread_quote <= (candidates[0].pre_quote / 1_000_000_000).max(2)
        && spread_base <= (candidates[0].pre_base / 1_000_000_000).max(2);
    if !same_state {
        return Err(DeriveRefusal::Ambiguous { candidates: count });
    }
    // The smallest admissible pre-quote: the shallowest pool, whose traversal is the worst, so
    // the tie inside atom-level ambiguity errs against every trade priced on it.
    let chosen = candidates.remove(0);
    Ok((chosen, searched_half_width, count))
}

/// The exact scan for a buy's pre-trade pair, from curve legs alone.
fn solve_buy(
    raw: u128,
    lp: u128,
    base_out: u128,
    price: &StatedPostPrice,
) -> Result<(Candidate, u128, u32), DeriveRefusal> {
    let (num, den) = (price.numerator, price.denominator);
    // Line intersection of the exact base-leg constraint b = floor(B*raw/(Q+raw)) with the
    // stated post price (Q+raw+lp)/(B-b): Q_hat = raw*den*(raw+lp) / (b*num - raw*den).
    let line = wide(base_out) * wide(num);
    let slope = wide(raw) * wide(den);
    if line <= slope {
        return Err(DeriveRefusal::LegsContradictPrice { direction: "buy" });
    }
    let denom_line = line - slope;
    let q_hat = narrow(
        wide(raw) * wide(den) * wide(raw.checked_add(lp).ok_or(DeriveRefusal::Arithmetic)?)
            / denom_line,
    )?;
    // Width of the pre-quote band the floor in the base leg admits, mapped through the slope
    // difference of the two constraints: (Q_hat + raw) * num / (b*num - raw*den).
    let band = narrow(wide(q_hat.saturating_add(raw)) * wide(num) / denom_line)?;
    let half_width = band.saturating_mul(2).max(512);
    if half_width > MAX_SEARCH_HALF_WIDTH {
        return Err(DeriveRefusal::TooSmallToPin {
            band_quote_atoms: band,
        });
    }
    let start = q_hat.saturating_sub(half_width).max(1);
    let end = q_hat.saturating_add(half_width);
    let mut walk = PriceWalk::start(
        start
            .checked_add(raw)
            .and_then(|value| value.checked_add(lp))
            .ok_or(DeriveRefusal::Arithmetic)?,
        num,
        den,
    )?;
    let mut candidates = Vec::new();
    let mut pre_quote = start;
    while pre_quote <= end {
        if walk.admits() {
            let post_quote = pre_quote
                .checked_add(raw)
                .and_then(|value| value.checked_add(lp))
                .ok_or(DeriveRefusal::Arithmetic)?;
            let traversal = pre_quote
                .checked_add(raw)
                .ok_or(DeriveRefusal::Arithmetic)?;
            // Pre-base range the exact base leg admits: b*(Q+raw) <= B*raw < (b+1)*(Q+raw),
            // intersected with the price interval shifted to pre-base by the base leg.
            if let (Ok(leg_lo), Ok(leg_hi_bound), Some((price_lo, price_hi))) = (
                mul_div_u128(base_out, traversal, raw, Rounding::Up),
                mul_div_u128(base_out.saturating_add(1), traversal, raw, Rounding::Up),
                price_interval(post_quote, num, den),
            ) {
                let lo = leg_lo.max(price_lo.saturating_add(base_out));
                let hi = leg_hi_bound
                    .saturating_sub(1)
                    .min(price_hi.saturating_add(base_out));
                if lo <= hi {
                    push_candidates(&mut candidates, pre_quote, lo, hi)?;
                }
            }
        }
        walk.advance();
        pre_quote += 1;
    }
    settle(candidates, half_width)
}

/// The exact scan for a sell's pre-trade pair at one raw consideration, pushing every
/// admissible pair into the caller's list. Returns the half-width it covered.
fn solve_sell_scan(
    raw: u128,
    lp: u128,
    base_in: u128,
    price: &StatedPostPrice,
    candidates: &mut Vec<Candidate>,
) -> Result<u128, DeriveRefusal> {
    if raw == 0 || base_in == 0 {
        return Err(DeriveRefusal::ZeroLeg);
    }
    let (num, den) = (price.numerator, price.denominator);
    let leaving = raw.checked_sub(lp).ok_or(DeriveRefusal::Arithmetic)?;
    // Line intersection of raw = floor(b*Q/(B+b)) with the stated post price
    // (Q-(raw-lp))/(B+b): Q_hat = raw*den*(raw-lp) / (raw*den - b*num).
    let slope = wide(raw) * wide(den);
    let line = wide(base_in) * wide(num);
    if slope <= line {
        return Err(DeriveRefusal::LegsContradictPrice { direction: "sell" });
    }
    let denom_line = slope - line;
    let q_hat = narrow(wide(raw) * wide(den) * wide(leaving) / denom_line)?;
    // Width of the pre-quote band the floor in the raw leg admits — b*Q/(raw*(raw+1)) atoms
    // of post-base — mapped through the slope difference of the two constraints.
    let band = narrow(
        wide(base_in) * wide(q_hat) * wide(num)
            / (wide(raw.checked_add(1).ok_or(DeriveRefusal::Arithmetic)?) * denom_line),
    )?;
    let half_width = band.saturating_mul(2).max(512);
    if half_width > MAX_SEARCH_HALF_WIDTH {
        return Err(DeriveRefusal::TooSmallToPin {
            band_quote_atoms: band,
        });
    }
    let start = q_hat
        .saturating_sub(half_width)
        .max(leaving.saturating_add(1));
    let end = q_hat.saturating_add(half_width);
    let mut walk = PriceWalk::start(start - leaving, num, den)?;
    let mut pre_quote = start;
    while pre_quote <= end {
        if walk.admits() {
            let post_quote = pre_quote - leaving;
            // Post-base range the exact raw leg admits: raw*(B+b) <= b*Q < (raw+1)*(B+b),
            // intersected with the price interval.
            if let (Ok(leg_hi), Ok(leg_lo_bound), Some((price_lo, price_hi))) = (
                mul_div_u128(base_in, pre_quote, raw, Rounding::Down),
                mul_div_u128(
                    base_in,
                    pre_quote,
                    raw.checked_add(1).ok_or(DeriveRefusal::Arithmetic)?,
                    Rounding::Down,
                ),
                price_interval(post_quote, num, den),
            ) {
                let lo = leg_lo_bound.saturating_add(1).max(price_lo);
                let hi = leg_hi.min(price_hi);
                if lo <= hi && lo > base_in {
                    push_candidates(candidates, pre_quote, lo - base_in, hi - base_in)?;
                }
            }
        }
        walk.advance();
        pre_quote += 1;
    }
    Ok(half_width)
}

/// The closed post-base range whose ratio against `post_quote` sits inside the literal's
/// half-open interval: `num*B <= post_quote*den < (num+1)*B`. `None` when no integer does.
fn price_interval(post_quote: u128, num: u128, den: u128) -> Option<(u128, u128)> {
    let hi = mul_div_u128(post_quote, den, num, Rounding::Down).ok()?;
    let lo = mul_div_u128(post_quote, den, num.checked_add(1)?, Rounding::Down)
        .ok()?
        .checked_add(1)?;
    if hi == 0 || lo > hi {
        return None;
    }
    Some((lo, hi))
}

/// Walks `x = post_quote * den` divided by `num` incrementally as the pre-quote steps by one
/// atom, keeping quotient and remainder in `u128` without ever forming `x`.
///
/// The price interval for a given post-quote is nonempty exactly when `floor(x/(num+1)) <
/// floor(x/num)`, which with `x = q*num + r` is exactly `r < q` — one comparison per atom.
struct PriceWalk {
    q: u128,
    r: u128,
    num: u128,
    step_q: u128,
    step_r: u128,
}

impl PriceWalk {
    fn start(post_quote: u128, num: u128, den: u128) -> Result<Self, DeriveRefusal> {
        let x = wide(post_quote) * wide(den);
        Ok(Self {
            q: narrow(x / wide(num))?,
            r: narrow(x % wide(num))?,
            num,
            step_q: den / num,
            step_r: den % num,
        })
    }

    /// Whether the current post-quote admits any post-base inside the price interval.
    const fn admits(&self) -> bool {
        self.r < self.q
    }

    fn advance(&mut self) {
        self.q = self.q.saturating_add(self.step_q);
        self.r += self.step_r;
        if self.r >= self.num {
            self.r -= self.num;
            self.q = self.q.saturating_add(1);
        }
    }
}

/// Pushes both endpoints of one admissible range, refusing as soon as the spread is material.
fn push_candidates(
    candidates: &mut Vec<Candidate>,
    pre_quote: u128,
    pre_base_lo: u128,
    pre_base_hi: u128,
) -> Result<(), DeriveRefusal> {
    for pre_base in [pre_base_lo, pre_base_hi] {
        if candidates
            .last()
            .is_none_or(|held| (held.pre_quote, held.pre_base) != (pre_quote, pre_base))
        {
            candidates.push(Candidate {
                pre_quote,
                pre_base,
            });
        }
    }
    let first = &candidates[0];
    let last = &candidates[candidates.len() - 1];
    let same_state = last.pre_quote.abs_diff(first.pre_quote)
        <= (first.pre_quote / 1_000_000_000).max(2)
        && last.pre_base.abs_diff(first.pre_base) <= (first.pre_base / 1_000_000_000).max(2);
    if same_state {
        Ok(())
    } else {
        Err(DeriveRefusal::Ambiguous {
            candidates: u32::try_from(candidates.len()).unwrap_or(u32::MAX),
        })
    }
}

// --- chain reconstruction across a whole polled tape --------------------------------------------

/// Relative precision, as a negative power of ten, at which a stated price literal is trusted to
/// LOCATE and FALSIFY — never to pin an atom.
///
/// MEASURED 2026-08-24 on the Duck's own polled pages: the provider prints ~40 decimal digits of
/// `priceSol` but only 7-8 of them agree with exact integer reconstruction, so nothing finer
/// than about 1e-7 in that literal is information. Trusting 1e-5 never breaks a true chain on
/// print noise and still catches a wrong leg convention (95 bps = 1e-2) a thousand times over.
pub const PRICE_LOCATOR_REL_POW10: u32 = 5;

/// How many following rows a bootstrap anchor must resolve before it is believed.
const BOOTSTRAP_VALIDATION_ROWS: usize = 6;

/// Rows the exact interval pinning spans. Kept short because the provider's page omits
/// micro-fills, so long stretches of perfectly adjacent rows are rare; the snap-tolerant
/// validation afterwards is what checks depth.
const BOOTSTRAP_PIN_ROWS: usize = 3;

/// Relative slack, as a negative power of ten of the base reserve, within which a row that
/// misses every exact window is SNAPPED to the nearest one rather than breaking the chain.
///
/// MEASURED 2026-08-24 on the Duck's own pages: stretches of rows evolve to the atom and then
/// miss the next exact window by parts in ten million of the reserve — unseen flow the
/// provider's trades page does not return, worst observed about 4e-7 at one break. A snap
/// adopts the row's own exact legs and records the distance, so omitted flow is measured
/// instead of silently absorbed; anything beyond this slack still breaks the chain, and a
/// wrong leg convention (95 bps) sits four orders of magnitude outside it.
pub const CHAIN_SNAP_MAX_REL_POW10: u32 = 6;

/// Widest scan either side of the two-row algebraic centre during bootstrap.
const BOOTSTRAP_HALF_WIDTH: u128 = 131_072;

/// Most anchor candidates one bootstrap pair may produce before it is judged to
/// under-determine the pool and skipped.
const BOOTSTRAP_CANDIDATE_CAP: usize = 4_096;

/// Adjacent pairs tried per segment before the segment is given up as unanchorable.
const BOOTSTRAP_PAIR_ATTEMPTS: usize = 24;

/// One retained row, prepared for chain reconstruction.
#[derive(Clone, Debug)]
pub struct ChainRow {
    /// Retained coverage is provably discontinuous immediately before this row, so no state may
    /// be evolved across it: the chain must re-anchor.
    pub gap_before: bool,
    /// The row's stated post price. A locator and falsifier at [`PRICE_LOCATOR_REL_POW10`] only.
    pub price: StatedPostPrice,
    /// Candidate curve-leg readings of the row's stated quote, in declared precedence order,
    /// each named by the loader (the name typically carries the convention and its fee).
    pub candidates: Vec<(String, CurveLegs)>,
}

/// What the reconstruction concluded about one row.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ChainRowState {
    /// The row's post-trade reserve pair, reached by exact evolution from an anchored state,
    /// under the named leg convention. `snapped_atoms` is how far the pool had drifted off the
    /// row's own exact window when the row was reached — nonzero exactly when fills the pages
    /// never showed moved the pool in between.
    Anchored {
        convention: String,
        post: ExactCurveState,
        snapped_atoms: u128,
    },
    /// No anchored state reaches this row honestly, and the reason is stated.
    Unresolved { reason: String },
}

/// A whole tape's reserve chain, with its own account of where it is blind.
#[derive(Clone, Debug)]
pub struct ChainReconstruction {
    pub rows: Vec<ChainRowState>,
    pub anchored: u32,
    pub unresolved: u32,
    /// Independently anchored runs. More than the gap count means the chain also broke where no
    /// page gap was recorded — fills the pages never showed, or a convention nothing declared.
    pub segments: u32,
    /// Rows reached only by snapping onto their own exact window: each is measured unseen
    /// micro-flow between retained fills.
    pub snapped_rows: u32,
    pub worst_snap_atoms: u128,
    pub statement: String,
}

/// The exact pre-base window one row's legs admit at a given pre-quote, `None` when empty.
/// Products here stay far inside `u128` for any pool this venue can hold, so the arithmetic is
/// plain checked integer work on the hot path.
fn leg_window(legs: &CurveLegs, pre_quote: u128) -> Option<(u128, u128)> {
    match legs.direction {
        TradeDirection::Buy => {
            let traversal = pre_quote.checked_add(legs.raw_quote_atoms)?;
            let lo = legs
                .base_atoms
                .checked_mul(traversal)?
                .div_ceil(legs.raw_quote_atoms);
            let hi = legs
                .base_atoms
                .checked_add(1)?
                .checked_mul(traversal)?
                .div_ceil(legs.raw_quote_atoms)
                .checked_sub(1)?;
            (lo <= hi && lo > legs.base_atoms).then_some((lo, hi))
        }
        TradeDirection::Sell => {
            let product = legs.base_atoms.checked_mul(pre_quote)?;
            let hi = (product / legs.raw_quote_atoms).checked_sub(legs.base_atoms)?;
            let lo = (product / legs.raw_quote_atoms.checked_add(1)?)
                .checked_add(1)?
                .checked_sub(legs.base_atoms)?;
            (lo <= hi && lo > 0).then_some((lo, hi))
        }
    }
}

/// Whether one row's legs hold exactly — to the deployed floor — at a state.
fn legs_hold(state: &ExactCurveState, legs: &CurveLegs) -> bool {
    leg_window(legs, state.effective_quote_atoms)
        .is_some_and(|(lo, hi)| lo <= state.base_atoms && state.base_atoms <= hi)
}

/// Whether a state's marginal ratio sits within the locator tolerance of the stated price.
fn ratio_within(state: &ExactCurveState, price: &StatedPostPrice) -> bool {
    let Some(tolerance) = 10_u128.checked_pow(PRICE_LOCATOR_REL_POW10) else {
        return false;
    };
    let lhs = wide(state.effective_quote_atoms) * wide(price.denominator);
    let rhs = wide(price.numerator) * wide(state.base_atoms);
    let difference = if lhs >= rhs { lhs - rhs } else { rhs - lhs };
    difference * U256::from(tolerance) <= rhs
}

/// Every candidate convention whose legs hold exactly at this state — or, when none does, the
/// nearest window within the snap slack — with the evolved post checked against the price
/// locator. The `u128` per match is the snap distance, zero for an exact hold.
fn resolve_row<'a>(
    state: &ExactCurveState,
    row: &'a ChainRow,
) -> Vec<(&'a str, ExactCurveState, u128)> {
    let exact: Vec<(&'a str, ExactCurveState, u128)> = row
        .candidates
        .iter()
        .filter(|(_, legs)| legs_hold(state, legs))
        .filter_map(|(name, legs)| {
            let post = evolve(state, legs)?;
            ratio_within(&post, &row.price).then_some((name.as_str(), post, 0_u128))
        })
        .collect();
    if !exact.is_empty() {
        return exact;
    }
    // Fills the pages never showed drift the pool off the exact window by parts in a billion;
    // adopt the row's own window edge and measure the drift rather than breaking the chain.
    let slack = (state.base_atoms / 10_u128.pow(CHAIN_SNAP_MAX_REL_POW10)).max(4);
    let mut best: Option<(&'a str, ExactCurveState, u128)> = None;
    for (name, legs) in &row.candidates {
        let Some((lo, hi)) = leg_window(legs, state.effective_quote_atoms) else {
            continue;
        };
        let (snapped_base, distance) = if state.base_atoms < lo {
            (lo, lo - state.base_atoms)
        } else if state.base_atoms > hi {
            (hi, state.base_atoms - hi)
        } else {
            (state.base_atoms, 0)
        };
        if distance > slack {
            continue;
        }
        let snapped = ExactCurveState {
            base_atoms: snapped_base,
            ..*state
        };
        let Some(post) = evolve(&snapped, legs) else {
            continue;
        };
        if !ratio_within(&post, &row.price) {
            continue;
        }
        if best.as_ref().is_none_or(|(_, _, held)| distance < *held) {
            best = Some((name.as_str(), post, distance));
        }
    }
    best.into_iter().collect()
}

/// The continuous two-row centre: the pre-quote at which the centres of two adjacent rows' exact
/// leg windows meet, found by integer bisection. `None` when the two windows never cross.
fn two_row_centre(first: &CurveLegs, second: &CurveLegs) -> Option<u128> {
    // Signed comparison of window centres at a candidate pre-quote, computed exactly.
    let offset = |quote: u128| -> Option<core::cmp::Ordering> {
        let (lo1, hi1) = leg_window(first, quote)?;
        let centre1 = lo1.midpoint(hi1);
        let mid = ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms: centre1,
            effective_quote_atoms: quote,
            schedule: zero_schedule(),
        };
        let evolved = evolve(&mid, first)?;
        let (lo2, hi2) = leg_window(second, evolved.effective_quote_atoms)?;
        Some(evolved.base_atoms.cmp(&lo2.midpoint(hi2)))
    };
    let mut low = first.raw_quote_atoms.max(1);
    let mut high = 1_u128 << 87;
    let low_side = offset(low)?;
    if low_side == core::cmp::Ordering::Equal {
        return Some(low);
    }
    // The centre difference is monotone in the pre-quote; bisect to its sign change.
    while low + 1 < high {
        let mid = low.midpoint(high);
        match offset(mid) {
            Some(side) if side == low_side => low = mid,
            Some(_) | None => high = mid,
        }
    }
    // A bisection that ran to its boundary found no crossing: the pair's constraints never
    // meet, and no pool holds a quote reserve this size. Garbage, not a centre.
    (high < 1 << 80).then_some(high)
}

/// One branch of the bootstrap interval propagation: what is still possible for the anchor
/// base, given one convention path through the rows consumed so far.
#[derive(Clone, Copy)]
struct Branch {
    /// Interval for the anchor state's base, in anchor coordinates.
    anchor_lo: u128,
    anchor_hi: u128,
    /// Pre-quote of the next row along this branch's convention path.
    quote: u128,
    /// Cumulative base the path's buys removed and sells added since the anchor.
    bought: u128,
    sold: u128,
}

/// Most simultaneous convention branches one propagation keeps.
const BOOTSTRAP_BRANCH_CAP: usize = 8;

/// Candidate readings per row the PIN considers — the loader's precedence order puts the
/// measured-dominant conventions first, and a row whose true reading is rarer simply fails this
/// pair, costing one attempt. Resolution after anchoring still sees every candidate.
const BOOTSTRAP_PIN_CANDIDATES: usize = 4;

/// Total candidate quotes one pair attempt may scan across its centres, narrowest first, so a
/// sharp pair stays cheap and a weak one is bounded instead of ground through.
const BOOTSTRAP_SCAN_BUDGET: u128 = 262_144;

/// Most centres one pair attempt scans.
const BOOTSTRAP_CENTRE_CAP: usize = 8;

/// Propagates the exact leg windows of up to `depth` rows through one candidate anchor quote,
/// returning the surviving anchor-base interval when exactly one materially remains.
fn propagate_intervals(
    rows: &[ChainRow],
    next: usize,
    depth: usize,
    anchor_quote: u128,
) -> Option<(u128, u128)> {
    let mut branches: Vec<Branch> = vec![Branch {
        anchor_lo: 1,
        anchor_hi: u128::MAX / 4,
        quote: anchor_quote,
        bought: 0,
        sold: 0,
    }];
    for (boundary, row) in rows[next..next + depth].iter().enumerate() {
        let mut advanced: Vec<Branch> = Vec::new();
        for branch in &branches {
            for (_, legs) in row.candidates.iter().take(BOOTSTRAP_PIN_CANDIDATES) {
                let Some((window_lo, window_hi)) = leg_window(legs, branch.quote) else {
                    continue;
                };
                // Unseen micro-flow moves the pool by parts in a billion between almost every
                // pair of retained rows, so each boundary crossed widens the window by a small
                // cumulative allowance; without it no exact pin survives a real tape.
                let inflation = (window_lo / 10_u128.pow(CHAIN_SNAP_MAX_REL_POW10))
                    .max(16)
                    .saturating_mul(u128::try_from(boundary).unwrap_or(u128::MAX) + 1);
                // Map the row's pre-base window into anchor coordinates:
                // anchor_base = pre_base + bought - sold.
                let map = |window: u128| {
                    window
                        .checked_add(branch.bought)
                        .and_then(|value| value.checked_sub(branch.sold))
                };
                let (Some(mapped_lo), Some(mapped_hi)) = (
                    map(window_lo).map(|value| value.saturating_sub(inflation)),
                    map(window_hi).map(|value| value.saturating_add(inflation)),
                ) else {
                    continue;
                };
                let lo = branch.anchor_lo.max(mapped_lo);
                let hi = branch.anchor_hi.min(mapped_hi);
                if lo > hi {
                    continue;
                }
                let (quote, bought, sold) = match legs.direction {
                    TradeDirection::Buy => (
                        branch
                            .quote
                            .checked_add(legs.raw_quote_atoms)
                            .and_then(|value| value.checked_add(legs.lp_retained_atoms)),
                        branch.bought.checked_add(legs.base_atoms),
                        Some(branch.sold),
                    ),
                    TradeDirection::Sell => (
                        branch
                            .quote
                            .checked_add(legs.lp_retained_atoms)
                            .and_then(|value| value.checked_sub(legs.raw_quote_atoms)),
                        Some(branch.bought),
                        branch.sold.checked_add(legs.base_atoms),
                    ),
                };
                let (Some(quote), Some(bought), Some(sold)) = (quote, bought, sold) else {
                    continue;
                };
                if advanced.len() < BOOTSTRAP_BRANCH_CAP {
                    advanced.push(Branch {
                        anchor_lo: lo,
                        anchor_hi: hi,
                        quote,
                        bought,
                        sold,
                    });
                }
            }
        }
        if advanced.is_empty() {
            return None;
        }
        branches = advanced;
    }
    let lo = branches.iter().map(|branch| branch.anchor_lo).min()?;
    let hi = branches.iter().map(|branch| branch.anchor_hi).max()?;
    Some((lo, hi))
}

/// Anchors one segment: finds the post-state of some row `i` by scanning candidate anchor
/// quotes around the two-row algebraic centre and propagating every following row's exact leg
/// window through each, so the interval collapses to atoms or dies.
#[allow(clippy::too_many_lines)] // One anchoring pass, in the order its evidence binds.
fn bootstrap(rows: &[ChainRow], start: usize) -> Option<(usize, ExactCurveState)> {
    let mut attempts = 0_usize;
    let mut index = start;
    while index + 2 < rows.len() && attempts < BOOTSTRAP_PAIR_ATTEMPTS {
        // Never bootstrap across a recorded discontinuity.
        if rows[index + 1].gap_before || rows[index + 2].gap_before {
            index += 1;
            continue;
        }
        attempts += 1;
        let mut depth = 0_usize;
        while depth < BOOTSTRAP_PIN_ROWS
            && index + 1 + depth < rows.len()
            && (depth == 0 || !rows[index + 1 + depth].gap_before)
        {
            depth += 1;
        }
        if depth < 2 {
            index += 1;
            continue;
        }
        let mut centres: Vec<(u128, u128)> = Vec::new();
        for (_, first) in rows[index + 1]
            .candidates
            .iter()
            .take(BOOTSTRAP_PIN_CANDIDATES)
        {
            for (_, second) in rows[index + 2]
                .candidates
                .iter()
                .take(BOOTSTRAP_PIN_CANDIDATES)
            {
                let Some(centre) = two_row_centre(first, second) else {
                    continue;
                };
                // Adaptive scan width: the two windows' spread mapped through their exact
                // slope difference, floored and capped so a weak pair cannot stall the walk.
                // A centre whose windows cannot even be computed — a bisection that ran to its
                // boundary because the pair's constraints never cross — is skipped outright:
                // scanning a full width around garbage is where the walk would go to die.
                let Some(width) = leg_window(first, centre)
                    .zip(leg_window(second, centre))
                    .and_then(|((lo1, hi1), (lo2, hi2))| {
                        let spread = (hi1 - lo1).checked_add(hi2 - lo2)?;
                        let slope = wide(first.base_atoms) * wide(second.raw_quote_atoms);
                        let other = wide(second.base_atoms) * wide(first.raw_quote_atoms);
                        let difference = if slope >= other {
                            slope - other
                        } else {
                            other - slope
                        };
                        if difference == U256::ZERO {
                            return None;
                        }
                        narrow(
                            wide(spread)
                                * wide(first.raw_quote_atoms)
                                * wide(second.raw_quote_atoms)
                                / difference,
                        )
                        .ok()
                    })
                    .map(|width| width.clamp(1_024, BOOTSTRAP_HALF_WIDTH))
                else {
                    continue;
                };
                if std::env::var_os("JOSHI_CHAIN_DEBUG").is_some() {
                    eprintln!(
                        "chain-debug   centre {centre} width {width} (first raw {} b {}, second \
                         raw {} b {})",
                        first.raw_quote_atoms,
                        first.base_atoms,
                        second.raw_quote_atoms,
                        second.base_atoms
                    );
                }
                if centres.len() >= BOOTSTRAP_CENTRE_CAP {
                    continue;
                }
                if !centres
                    .iter()
                    .any(|(held, _)| held.abs_diff(centre) < width)
                {
                    centres.push((centre, width));
                }
            }
        }
        let mut survivors: Vec<(u128, u128, u128)> = Vec::new();
        let debug = std::env::var_os("JOSHI_CHAIN_DEBUG").is_some();
        // A weak pin lets most of the scan survive; the list is decimated evenly rather than
        // abandoned, because the validation pass below is what actually chooses. Narrowest
        // centres scan first, under one budget, so sharp evidence is never crowded out.
        let mut stride = 1_usize;
        let mut seen = 0_usize;
        centres.sort_by_key(|(_, width)| *width);
        let mut budget = BOOTSTRAP_SCAN_BUDGET;
        for (centre, width) in centres {
            let Some(remaining) = budget.checked_sub(width.saturating_mul(2)) else {
                break;
            };
            budget = remaining;
            let from = centre.saturating_sub(width).max(1);
            let to = centre.saturating_add(width);
            for quote in from..=to {
                let Some((lo, hi)) = propagate_intervals(rows, index + 1, depth, quote) else {
                    continue;
                };
                let midpoint = ExactCurveState {
                    formula: VenueFormula::PumpSwapExactQuoteIn,
                    base_atoms: lo.midpoint(hi),
                    effective_quote_atoms: quote,
                    schedule: zero_schedule(),
                };
                if !ratio_within(&midpoint, &rows[index].price) {
                    continue;
                }
                seen += 1;
                if seen.is_multiple_of(stride) {
                    survivors.push((quote, lo, hi));
                }
                if survivors.len() >= BOOTSTRAP_CANDIDATE_CAP {
                    survivors = survivors.into_iter().step_by(2).collect();
                    stride *= 2;
                }
            }
        }
        if debug {
            eprintln!(
                "chain-debug bootstrap index {index}: depth {depth}, survivors {} (stride \
                 {stride})",
                survivors.len()
            );
        }
        if !survivors.is_empty() {
            survivors.sort_unstable();
            // The floors pin the pool to a tube along the constant-price direction, never to a
            // point: stated bases lose their sub-atom remainders and the provider omits
            // micro-fills. Every tube member prices identically to within the locator, and the
            // per-row snaps re-centre the base as the chain walks, so the anchor is chosen by
            // VALIDATION: the sampled member that carries furthest with the least total snap.
            let step = (survivors.len() / 256).max(1);
            let mut validated: Vec<(u128, u128, ExactCurveState)> = Vec::new();
            for (quote, lo, hi) in survivors.iter().step_by(step).copied() {
                let candidate = ExactCurveState {
                    formula: VenueFormula::PumpSwapExactQuoteIn,
                    base_atoms: lo.midpoint(hi),
                    effective_quote_atoms: quote,
                    schedule: zero_schedule(),
                };
                let mut state = candidate;
                let mut resolved = 0_usize;
                let mut wanted = 0_usize;
                let mut total_snap = 0_u128;
                for row in rows.iter().skip(index + 1).take(BOOTSTRAP_VALIDATION_ROWS) {
                    if row.gap_before {
                        break;
                    }
                    wanted += 1;
                    let matches = resolve_row(&state, row);
                    let Some((_, post, snapped)) = matches.first() else {
                        break;
                    };
                    total_snap = total_snap.saturating_add(*snapped);
                    state = *post;
                    resolved += 1;
                }
                if resolved == wanted && resolved >= 2 {
                    validated.push((total_snap, quote, candidate));
                }
            }
            // Of the members that carry furthest, keep the least-snap set and take its median,
            // so the anchor sits in the middle of the tube instead of at a sampled edge.
            if let Some(&(least, _, _)) = validated.iter().min_by_key(|(snap, _, _)| *snap) {
                let mut tied: Vec<(u128, u128, ExactCurveState)> = validated
                    .into_iter()
                    .filter(|(snap, _, _)| *snap == least)
                    .collect();
                tied.sort_by_key(|(_, quote, _)| *quote);
                let (_, _, anchor) = tied[tied.len() / 2];
                return Some((index, anchor));
            }
        }
        index += 1;
    }
    None
}

/// A schedule stamp for internal probe states; the caller re-stamps real outputs.
fn zero_schedule() -> FeeSchedule {
    FeeSchedule {
        lp: joshi_market_math::fee::FeeBps::new(0).expect("zero is a rate"),
        protocol: joshi_market_math::fee::FeeBps::new(0).expect("zero is a rate"),
        creator: CreatorFee::NotApplicable,
    }
}

/// Reconstructs the reserve chain of one polled tape from its rows' exact stated amounts, using
/// each stated price only as a coarse locator and falsifier.
///
/// The provider's price literals carry far fewer true digits than they print, so no single row
/// pins the pool; two adjacent rows' exact integer leg constraints do. Each maximal
/// gap-free run is anchored from such a pair, validated forward, then evolved row by row with
/// the leg convention resolved per row by exact reproduction. A row that no anchored state
/// reaches is stated unresolved, never interpolated.
#[must_use]
#[allow(clippy::too_many_lines)] // One tape walked once, in the order its segments bind.
pub fn reconstruct_pumpswap_chain(
    rows: &[ChainRow],
    schedule_for_pricing: FeeSchedule,
) -> ChainReconstruction {
    let mut out: Vec<ChainRowState> = Vec::with_capacity(rows.len());
    let mut segments = 0_u32;
    let mut index = 0_usize;
    while index < rows.len() {
        let Some((anchor_index, anchor)) = bootstrap(rows, index) else {
            // Nothing in the attempted stretch pins the pool; state that for exactly the rows
            // the attempts covered and keep trying beyond them.
            let stretch = (index + BOOTSTRAP_PAIR_ATTEMPTS).min(rows.len());
            for _ in index..stretch {
                out.push(ChainRowState::Unresolved {
                    reason: "no adjacent pair of retained rows in this stretch pins the pool: \
                             the exact leg constraints of every candidate pair admit no \
                             coherent reserve pair, and nothing was guessed"
                        .to_owned(),
                });
            }
            index = stretch;
            continue;
        };
        segments += 1;
        for _ in index..anchor_index {
            out.push(ChainRowState::Unresolved {
                reason: "before this segment's first anchorable pair; the chain cannot be \
                         evolved backwards through a floor without inventing atoms"
                    .to_owned(),
            });
        }
        // The anchor row itself is anchored at the bootstrap state.
        out.push(ChainRowState::Anchored {
            convention: "anchor".to_owned(),
            post: ExactCurveState {
                schedule: schedule_for_pricing,
                ..anchor
            },
            snapped_atoms: 0,
        });
        let mut state = anchor;
        let mut next = anchor_index + 1;
        while next < rows.len() {
            let row = &rows[next];
            if row.gap_before {
                break; // recorded discontinuity: re-anchor beyond it
            }
            let matches = resolve_row(&state, row);
            let chosen = match matches.len() {
                0 => None,
                1 => Some(matches[0]),
                // One look ahead: prefer the reading the next row can continue from.
                _ => matches
                    .iter()
                    .find(|(_, post, _)| {
                        rows.get(next + 1)
                            .is_some_and(|following| !resolve_row(post, following).is_empty())
                    })
                    .copied()
                    .or(Some(matches[0])),
            };
            let Some((convention, post, snapped_atoms)) = chosen else {
                if std::env::var_os("JOSHI_CHAIN_DEBUG").is_some() {
                    let misses: Vec<String> = rows[next]
                        .candidates
                        .iter()
                        .map(|(name, legs)| {
                            let window = leg_window(legs, state.effective_quote_atoms);
                            match window {
                                None => format!("{name}: no window"),
                                Some((lo, hi)) => {
                                    let miss = if state.base_atoms < lo {
                                        lo - state.base_atoms
                                    } else {
                                        state.base_atoms.saturating_sub(hi)
                                    };
                                    let post_ok = evolve(&state, legs)
                                        .map(|post| ratio_within(&post, &rows[next].price));
                                    format!("{name}: miss {miss} atoms, price_ok {post_ok:?}")
                                }
                            }
                        })
                        .collect();
                    eprintln!(
                        "chain-debug BREAK at chain row {next} (dir {:?}): {}",
                        rows[next]
                            .candidates
                            .first()
                            .map(|(_, legs)| legs.direction),
                        misses.join(" | ")
                    );
                }
                break; // beyond even the snap slack: re-anchor rather than guess
            };
            out.push(ChainRowState::Anchored {
                convention: convention.to_owned(),
                post: ExactCurveState {
                    schedule: schedule_for_pricing,
                    ..post
                },
                snapped_atoms,
            });
            state = post;
            next += 1;
        }
        if next < rows.len() && !rows[next].gap_before {
            out.push(ChainRowState::Unresolved {
                reason: "the anchored chain does not reach this row under any declared \
                         convention: a fill the retained pages never showed sits between, or \
                         the row's stated legs fit no declared reading; the chain re-anchors \
                         after it"
                    .to_owned(),
            });
            next += 1;
        }
        index = next;
    }
    let anchored = out
        .iter()
        .filter(|row| matches!(row, ChainRowState::Anchored { .. }))
        .count();
    let unresolved = out.len() - anchored;
    let snapped: Vec<u128> = out
        .iter()
        .filter_map(|row| match row {
            ChainRowState::Anchored { snapped_atoms, .. } if *snapped_atoms > 0 => {
                Some(*snapped_atoms)
            }
            _ => None,
        })
        .collect();
    let worst_snap = snapped.iter().copied().max().unwrap_or(0);
    let statement = format!(
        "the reserve chain was reconstructed from the rows' own exact stated amounts — adjacent \
         fills pin the pool through the deployed floor arithmetic, every later row evolves the \
         pair exactly under a per-row leg convention chosen by exact reproduction — with the \
         stated price trusted only to one part in 10^{PRICE_LOCATOR_REL_POW10} as locator and \
         falsifier, because this provider's forty printed digits were measured to carry only \
         seven or eight. {anchored} of {} rows anchored across {segments} independent segments; \
         {unresolved} rows stayed unresolved rather than guessed. {} rows were reached only by \
         snapping onto their own exact window (worst {worst_snap} base atoms, bounded at one \
         part in 10^{CHAIN_SNAP_MAX_REL_POW10} of the reserve): each snap is MEASURED unseen \
         flow — fills this provider's trades page does not return, most plausibly micro-fills — \
         and the states it separates are identical to every clip-scale would-quote.",
        out.len(),
        snapped.len()
    );
    ChainReconstruction {
        rows: out,
        anchored: u32::try_from(anchored).unwrap_or(u32::MAX),
        unresolved: u32::try_from(unresolved).unwrap_or(u32::MAX),
        segments,
        snapped_rows: u32::try_from(snapped.len()).unwrap_or(u32::MAX),
        worst_snap_atoms: worst_snap,
        statement,
    }
}

/// Whether consecutive derived states reproduce each other under the stated legs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DerivedEvolutionCheck {
    pub pairs: u32,
    pub reproduced_to_the_atom: u32,
    pub broken: u32,
    pub unwalkable: u32,
    pub worst_quote_error_atoms: u128,
    pub statement: String,
}

/// Moves each derived post-state by the NEXT row's curve legs — exactly the reserve motion the
/// deployed step takes — and compares the result to the next derived post-state, to the atom.
///
/// A broken pair is a fill the pages never showed, a wrong declared leg convention, or a wrong
/// derivation — and the tape alone cannot tell those apart, which is stated rather than resolved.
#[must_use]
pub fn check_derived_evolution(events: &[(CurveLegs, ExactCurveState)]) -> DerivedEvolutionCheck {
    let mut reproduced = 0_u32;
    let mut broken = 0_u32;
    let mut unwalkable = 0_u32;
    let mut worst = 0_u128;
    for pair in events.windows(2) {
        let (_, previous_post) = &pair[0];
        let (legs, next_post) = &pair[1];
        let Some(predicted) = evolve(previous_post, legs) else {
            unwalkable += 1;
            continue;
        };
        if predicted == *next_post {
            reproduced += 1;
        } else {
            broken += 1;
            worst = worst.max(
                predicted
                    .effective_quote_atoms
                    .abs_diff(next_post.effective_quote_atoms),
            );
        }
    }
    let pairs = u32::try_from(events.len().saturating_sub(1)).unwrap_or(u32::MAX);
    let statement = format!(
        "each derived post-state was moved by the next row's curve legs — the exact reserve \
         motion the deployed step takes — and compared to the next derived post-state: \
         {reproduced} of {pairs} pairs reproduced to the atom, {broken} broke (worst quote error \
         {worst} atoms), {unwalkable} could not be moved. A broken pair is a fill the retained \
         pages never showed, a wrong declared leg convention, or a wrong derivation, and the \
         tape alone cannot tell those apart."
    );
    DerivedEvolutionCheck {
        pairs,
        reproduced_to_the_atom: reproduced,
        broken,
        unwalkable,
        worst_quote_error_atoms: worst,
        statement,
    }
}

#[cfg(test)]
mod tests {
    use joshi_market_math::fee::FeeBps;

    use super::*;

    fn schedule(lp: u16, protocol: u16, creator: u16) -> FeeSchedule {
        FeeSchedule {
            lp: FeeBps::new(lp).expect("lp"),
            protocol: FeeBps::new(protocol).expect("protocol"),
            creator: CreatorFee::Charged(FeeBps::new(creator).expect("creator")),
        }
    }

    /// A graduated pool about the size the Duck's own tape implies.
    fn pool(schedule_used: FeeSchedule) -> ExactCurveState {
        ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms: 297_431_224_690_113,
            effective_quote_atoms: 87_554_112_907,
            schedule: schedule_used,
        }
    }

    /// Renders a post-state's marginal price exactly the way the provider prints it: quote per
    /// base in whole units, by long division, truncated at `digits` fractional digits.
    fn provider_price_literal(state: &ExactCurveState, digits: usize) -> String {
        // Whole-unit price = quote_atoms / (base_atoms * 10^(9-6)).
        let numerator = state.effective_quote_atoms;
        let denominator = state.base_atoms.checked_mul(1_000).expect("denominator");
        let mut out = format!("{}.", numerator / denominator);
        let mut remainder = numerator % denominator;
        for _ in 0..digits {
            remainder *= 10;
            out.push(char::from(
                b'0' + u8::try_from(remainder / denominator).expect("digit"),
            ));
            remainder %= denominator;
        }
        out
    }

    #[test]
    fn a_parsed_price_interval_contains_the_ratio_it_was_printed_from() {
        let state = pool(schedule(20, 5, 5));
        let literal = provider_price_literal(&state, 40);
        let price = stated_post_price(&literal, 9, 6).expect("parses");
        assert!(price.digits_dropped > 0, "forty digits exceed the kept 30");
        let (lo, hi) = price_interval(
            state.effective_quote_atoms,
            price.numerator,
            price.denominator,
        )
        .expect("the interval admits the true pair");
        assert!(lo <= state.base_atoms && state.base_atoms <= hi);
    }

    #[test]
    fn what_a_price_literal_cannot_be_is_refused() {
        assert!(matches!(
            stated_post_price("-1.5", 9, 6),
            Err(DeriveRefusal::NotADecimalLiteral { .. })
        ));
        assert!(matches!(
            stated_post_price("1e-7", 9, 6),
            Err(DeriveRefusal::NotADecimalLiteral { .. })
        ));
        assert!(matches!(
            stated_post_price("0.000000000", 9, 6),
            Err(DeriveRefusal::ZeroPrice { .. })
        ));
        assert!(matches!(
            stated_post_price("", 9, 6),
            Err(DeriveRefusal::NotADecimalLiteral { .. })
        ));
    }

    #[test]
    fn a_buy_row_written_by_the_deployed_walk_derives_back_to_the_exact_reserve_pair() {
        for (lp, protocol, creator) in [(20, 5, 5), (20, 10, 95)] {
            let fees = schedule(lp, protocol, creator);
            let state = pool(fees);
            for quote_in in [50_000_000_u128, 250_000_000, 1_290_251_742, 5_000_000_000] {
                let walked = state.buy_with_quote_in(quote_in).expect("walks");
                let literal = provider_price_literal(&walked.next, 40);
                let price = stated_post_price(&literal, 9, 6).expect("parses");
                let derived = derive_pumpswap_state(
                    TradeDirection::Buy,
                    quote_in,
                    walked.base_out_atoms,
                    &price,
                    fees,
                )
                .expect("derives");
                assert_eq!(
                    derived.pre, state,
                    "fees {lp}/{protocol}/{creator} q {quote_in}"
                );
                assert_eq!(derived.post, walked.next);
            }
        }
    }

    #[test]
    fn a_sell_row_written_by_the_deployed_walk_derives_back_to_the_exact_reserve_pair() {
        for (lp, protocol, creator) in [(20, 5, 5), (20, 10, 95)] {
            let fees = schedule(lp, protocol, creator);
            let state = pool(fees);
            for base_in in [
                150_000_000_000_u128,
                900_000_000_000,
                4_420_867_264_271,
                17_000_000_000_000,
            ] {
                let walked = state.sell_base_in(base_in).expect("walks");
                let literal = provider_price_literal(&walked.next, 40);
                let price = stated_post_price(&literal, 9, 6).expect("parses");
                let derived = derive_pumpswap_state(
                    TradeDirection::Sell,
                    walked.quote_out_atoms,
                    base_in,
                    &price,
                    fees,
                )
                .expect("derives");
                assert_eq!(
                    derived.pre, state,
                    "fees {lp}/{protocol}/{creator} b {base_in}"
                );
                assert_eq!(derived.post, walked.next);
            }
        }
    }

    #[test]
    fn even_a_dust_fill_derives_exactly_when_the_literal_carries_forty_digits() {
        let fees = schedule(20, 5, 5);
        let state = pool(fees);
        let walked = state.buy_with_quote_in(200_000).expect("walks");
        let literal = provider_price_literal(&walked.next, 40);
        let price = stated_post_price(&literal, 9, 6).expect("parses");
        let derived = derive_pumpswap_state(
            TradeDirection::Buy,
            200_000,
            walked.base_out_atoms,
            &price,
            fees,
        )
        .expect("a forty-digit price pins the pool even for a dust fill");
        assert_eq!(derived.pre, state);
    }

    #[test]
    fn a_short_price_literal_is_refused_rather_than_guessed_from() {
        let fees = schedule(20, 5, 5);
        let state = pool(fees);
        let walked = state.buy_with_quote_in(1_290_251_742).expect("walks");
        // The same price cut to seven significant digits: the interval it denotes admits many
        // reserve pairs, and picking one would be fabrication.
        let literal = provider_price_literal(&walked.next, 13);
        let price = stated_post_price(&literal, 9, 6).expect("parses");
        let refused = derive_pumpswap_state(
            TradeDirection::Buy,
            1_290_251_742,
            walked.base_out_atoms,
            &price,
            fees,
        );
        assert!(
            matches!(
                refused,
                Err(DeriveRefusal::Ambiguous { .. }
                    | DeriveRefusal::TooSmallToPin { .. }
                    | DeriveRefusal::NoStateReproducesTheRow)
            ),
            "a seven-digit price pinned the pool anyway: {refused:?}"
        );
    }

    #[test]
    fn a_wrong_declared_fee_schedule_does_not_reproduce_the_row() {
        let fees = schedule(20, 10, 95);
        let state = pool(fees);
        let walked = state.buy_with_quote_in(1_290_251_742).expect("walks");
        let literal = provider_price_literal(&walked.next, 40);
        let price = stated_post_price(&literal, 9, 6).expect("parses");
        let wrong = derive_pumpswap_state(
            TradeDirection::Buy,
            1_290_251_742,
            walked.base_out_atoms,
            &price,
            schedule(20, 5, 5),
        );
        match wrong {
            Err(_) => {}
            Ok(derived) => assert_ne!(
                derived.pre, state,
                "the control schedule reproduced the true pair, so the check proves nothing"
            ),
        }
    }

    fn buy_legs(walked: &joshi_market_math::stack::BuyLeg) -> CurveLegs {
        CurveLegs {
            direction: TradeDirection::Buy,
            raw_quote_atoms: walked.raw_quote_atoms,
            lp_retained_atoms: u128::from(walked.fees.lp_atoms),
            base_atoms: walked.base_out_atoms,
        }
    }

    #[test]
    fn derived_states_along_one_walked_chain_reproduce_their_own_evolution() {
        let fees = schedule(20, 5, 5);
        let mut state = pool(fees);
        let mut events = Vec::new();
        for step in 0..12_u32 {
            if step % 3 == 2 {
                let base_in = state.base_atoms / 300;
                let walked = state.sell_base_in(base_in).expect("sell walks");
                events.push((
                    CurveLegs {
                        direction: TradeDirection::Sell,
                        raw_quote_atoms: walked.raw_quote_atoms,
                        lp_retained_atoms: u128::from(walked.fees.lp_atoms),
                        base_atoms: base_in,
                    },
                    walked.next,
                ));
                state = walked.next;
            } else {
                let quote_in = state.effective_quote_atoms / 200;
                let walked = state.buy_with_quote_in(quote_in).expect("buy walks");
                events.push((buy_legs(&walked), walked.next));
                state = walked.next;
            }
        }
        let check = check_derived_evolution(&events);
        assert_eq!(check.pairs, 11);
        assert_eq!(check.reproduced_to_the_atom, 11);
        assert_eq!(check.broken, 0);
    }

    #[test]
    fn a_missing_fill_breaks_exactly_the_pair_that_spans_it() {
        let fees = schedule(20, 5, 5);
        let state = pool(fees);
        let first = state.buy_with_quote_in(400_000_000).expect("walks");
        let hidden = first.next.buy_with_quote_in(900_000_000).expect("walks");
        let third = hidden.next.buy_with_quote_in(300_000_000).expect("walks");
        let events = vec![
            (buy_legs(&first), first.next),
            (buy_legs(&third), third.next),
        ];
        let check = check_derived_evolution(&events);
        assert_eq!(check.broken, 1, "{}", check.statement);
        assert!(check.worst_quote_error_atoms > 0);
    }

    /// Builds the chain-row candidates exactly the way a polled-tape loader does, from a stated
    /// quote under a mixed provider convention, with a truncated eight-digit price.
    fn chain_row_from(
        walked_raw: u128,
        base: u128,
        direction: TradeDirection,
        stated_quote: u128,
        post: &ExactCurveState,
        gap_before: bool,
    ) -> ChainRow {
        let _ = walked_raw;
        let fee_of = |raw: u128| (raw * 95).div_ceil(10_000);
        let legs = |raw: u128| CurveLegs {
            direction,
            raw_quote_atoms: raw,
            lp_retained_atoms: 0,
            base_atoms: base,
        };
        let mut candidates = vec![("curve_leg_stated".to_owned(), legs(stated_quote))];
        match direction {
            TradeDirection::Buy => {
                let centre = stated_quote * 10_000 / 10_095;
                for raw in centre.saturating_sub(4)..=centre.saturating_add(4) {
                    if raw > 0 && raw + fee_of(raw) == stated_quote {
                        candidates.push(("trader_leg_row_fee_on_top".to_owned(), legs(raw)));
                    }
                }
            }
            TradeDirection::Sell => {
                let centre = stated_quote * 10_000 / (10_000 - 95);
                for raw in centre.saturating_sub(4)..=centre.saturating_add(4) {
                    if raw > fee_of(raw) && raw - fee_of(raw) == stated_quote {
                        candidates.insert(0, ("trader_leg_row_fee_deducted".to_owned(), legs(raw)));
                    }
                }
            }
        }
        // Fourteen fractional digits of a ~3e-7 price is about eight significant digits: the
        // precision this provider was measured to actually carry under its forty printed ones.
        let price =
            stated_post_price(&provider_price_literal(post, 14), 9, 6).expect("price parses");
        ChainRow {
            gap_before,
            price,
            candidates,
        }
    }

    /// The polled reality: no LP retention, a 95 bps fee that leaves the pool, and a provider
    /// that states the curve leg on some buys, the fee-on-top total on others, and the
    /// fee-deducted receipt on sells — with a hidden fill in the middle of the tape.
    pub(crate) fn mixed_chain_fixture() -> (Vec<ChainRow>, Vec<ExactCurveState>) {
        let fees = schedule(0, 0, 95);
        let mut state = pool(fees);
        let mut rows: Vec<ChainRow> = Vec::new();
        let mut truth: Vec<ExactCurveState> = Vec::new();
        let fee_of = |raw: u128| (raw * 95).div_ceil(10_000);
        for step in 0..12_u32 {
            if step % 3 == 1 {
                let base_in = state.base_atoms / 250;
                let walked = state.sell_base_in(base_in).expect("sell walks");
                let stated = walked.raw_quote_atoms - fee_of(walked.raw_quote_atoms);
                rows.push(chain_row_from(
                    walked.raw_quote_atoms,
                    base_in,
                    TradeDirection::Sell,
                    stated,
                    &walked.next,
                    false,
                ));
                truth.push(walked.next);
                state = walked.next;
            } else {
                let gap_before = step == 8;
                if gap_before {
                    // A fill the pages never showed: move the pool off-tape first.
                    state = state
                        .buy_with_quote_in(state.effective_quote_atoms / 400)
                        .expect("hidden walks")
                        .next;
                }
                let quote_in = state.effective_quote_atoms / 180;
                let walked = state.buy_with_quote_in(quote_in).expect("buy walks");
                let stated = if step % 2 == 0 {
                    walked.raw_quote_atoms
                } else {
                    walked.raw_quote_atoms + fee_of(walked.raw_quote_atoms)
                };
                rows.push(chain_row_from(
                    walked.raw_quote_atoms,
                    walked.base_out_atoms,
                    TradeDirection::Buy,
                    stated,
                    &walked.next,
                    gap_before,
                ));
                truth.push(walked.next);
                state = walked.next;
            }
        }
        (rows, truth)
    }

    #[test]
    fn a_chain_of_mixed_convention_rows_with_eight_digit_prices_reconstructs_exactly() {
        let fees = schedule(0, 0, 95);
        let (rows, truth) = mixed_chain_fixture();
        let chain = reconstruct_pumpswap_chain(&rows, fees);
        assert_eq!(chain.rows.len(), truth.len());
        assert!(
            chain.segments >= 2,
            "the recorded gap must split the chain: {}",
            chain.statement
        );
        let mut anchored = 0;
        for (index, row) in chain.rows.iter().enumerate() {
            if let ChainRowState::Anchored { post, .. } = row {
                anchored += 1;
                // The floors pin the pool to a tube, never to the atom: stated bases lose
                // their sub-atom remainders and the pin windows carry the micro-flow
                // allowance, so the chain's own stated resolution — one part in 10^7 — is the
                // honest bound, orders below what any clip-scale quote can see.
                let close = post.base_atoms.abs_diff(truth[index].base_atoms)
                    <= (truth[index].base_atoms / 10_000_000).max(2)
                    && post
                        .effective_quote_atoms
                        .abs_diff(truth[index].effective_quote_atoms)
                        <= (truth[index].effective_quote_atoms / 10_000_000).max(2);
                assert!(
                    close,
                    "row {index} anchored materially off the true pair: derived {}/{} vs true \
                     {}/{}: {}",
                    post.effective_quote_atoms,
                    post.base_atoms,
                    truth[index].effective_quote_atoms,
                    truth[index].base_atoms,
                    chain.statement
                );
            }
        }
        assert!(
            anchored >= 9,
            "most rows must anchor, got {anchored}: {}",
            chain.statement
        );
    }

    #[test]
    fn curve_legs_alone_derive_the_pair_regardless_of_which_leg_the_provider_stated() {
        // A provider that states the CURVE leg (raw consideration) rather than the trader's
        // total: the core solver recovers the same pair from the raw legs directly.
        let fees = schedule(20, 10, 95);
        let state = pool(fees);
        let walked = state.buy_with_quote_in(1_290_251_742).expect("walks");
        let literal = provider_price_literal(&walked.next, 40);
        let price = stated_post_price(&literal, 9, 6).expect("parses");
        let derived = derive_pumpswap_state_from_curve_legs(&buy_legs(&walked), &price, fees)
            .expect("curve legs derive");
        assert_eq!(derived.pre, state);
        assert_eq!(derived.post, walked.next);
        let sold = state.sell_base_in(4_420_867_264_271).expect("sell walks");
        let sell_literal = provider_price_literal(&sold.next, 40);
        let sell_price = stated_post_price(&sell_literal, 9, 6).expect("parses");
        let derived_sell = derive_pumpswap_state_from_curve_legs(
            &CurveLegs {
                direction: TradeDirection::Sell,
                raw_quote_atoms: sold.raw_quote_atoms,
                lp_retained_atoms: u128::from(sold.fees.lp_atoms),
                base_atoms: sold.base_in_atoms,
            },
            &sell_price,
            fees,
        )
        .expect("sell curve legs derive");
        assert_eq!(derived_sell.pre, state);
        assert_eq!(derived_sell.post, sold.next);
    }
}
