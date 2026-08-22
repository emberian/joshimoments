//! What a round trip costs, as a function of size, at one observed state.
//!
//! Two different questions get called "the round-trip cost" and they have different answers.
//!
//! **What does it cost to change my mind immediately?** Buy, then sell the whole thing back before
//! anything else happens. On a constant-product venue the traversal *reverses exactly*: the buy
//! walks the reserve one way and the sell walks it back, so what remains is fees and integer dust.
//! This number is nearly flat in size. [`SelfRoundTrip`] computes it.
//!
//! **How far must the chart move before my clip is free?** That is a different number and it is
//! not flat. Entry pays above the marginal price by the traversal, exit receives below it by the
//! traversal again, and both gaps are charged against a mark that has to make them up. [`CrackleHurdle`]
//! computes it, and it is the one that gates a crackle.
//!
//! The second is expressed as a *declared path*: other participants buy some net amount, walked
//! through the venue's own deployed formula. The resulting lift of the marginal price is an
//! output, not an assumption, and no invariant is imposed by hand. Nothing here is a fill, a
//! forecast, or advice.

use joshi_market_math::stack::{ExactCurveState, ExactRatio, StackRefusal};
use thiserror::Error;

/// Costs that do not scale with clip size, stated as inputs with their own provenance.
///
/// These are not measured by this crate. A caller supplies what it observed, and the artifact
/// carries the label so nobody reads a plausible default as evidence. They matter enormously at
/// small size and not at all at large size, which is exactly why they cannot be left out.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeclaredFixedCosts {
    /// Where these numbers came from, in the caller's own words.
    pub provenance: String,
    /// Network fee for one landed transaction, in quote atoms.
    pub per_transaction_quote_atoms: u128,
    /// How many transactions the round trip needs to land.
    pub transactions: u32,
    /// Any flat router, frontend, or tip charge on the path, in quote atoms, for the whole trip.
    pub flat_route_quote_atoms: u128,
    /// Rent for an associated token account that the trip must fund and does not recover.
    pub unrecovered_rent_quote_atoms: u128,
}

impl DeclaredFixedCosts {
    /// A round trip that pays nothing outside the venue. Useful only as a stated control.
    #[must_use]
    pub fn none(provenance: impl Into<String>) -> Self {
        Self {
            provenance: provenance.into(),
            per_transaction_quote_atoms: 0,
            transactions: 0,
            flat_route_quote_atoms: 0,
            unrecovered_rent_quote_atoms: 0,
        }
    }

    /// Total quote atoms the trip pays outside the venue.
    ///
    /// # Errors
    ///
    /// Refuses an overflowing total.
    pub fn total_quote_atoms(&self) -> Result<u128, RoundTripError> {
        self.per_transaction_quote_atoms
            .checked_mul(u128::from(self.transactions))
            .and_then(|value| value.checked_add(self.flat_route_quote_atoms))
            .and_then(|value| value.checked_add(self.unrecovered_rent_quote_atoms))
            .ok_or(RoundTripError::Arithmetic)
    }
}

/// Buy and immediately sell the whole thing back, at one state, with nothing in between.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfRoundTrip {
    pub quote_in_atoms: u128,
    pub base_out_atoms: u128,
    pub quote_returned_atoms: u128,
    /// Quote atoms lost inside the venue, before any network or route cost.
    pub venue_loss_atoms: u128,
    /// Venue loss as a fraction of what was put in.
    pub venue_cost: ExactRatio,
    /// Venue loss plus every declared cost outside the venue, as a fraction of what was put in.
    pub all_in_cost: ExactRatio,
}

/// The mark lift a clip has to clear before it is free, under a declared path.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrackleHurdle {
    pub clip_quote_in_atoms: u128,
    pub base_held_atoms: u128,
    /// The clip as a fraction of the effective quote reserve it was walked against. This is the
    /// dimensionless coordinate the hurdle actually depends on.
    pub clip_fraction_of_quote_reserve: ExactRatio,
    /// Smallest net quote inflow from other participants, walked through the deployed formula,
    /// after which selling the whole holding returns the clip and every declared cost.
    pub other_net_quote_inflow_atoms: u128,
    /// The lift of the marginal pool price that inflow produces. An output of the walk.
    pub mark_lift: ExactRatio,
    /// What the holding fetches at that lifted state.
    pub proceeds_at_hurdle_atoms: u128,
}

/// One point of the cost surface: a declared size and what it costs there.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CostPoint {
    pub self_round_trip: SelfRoundTrip,
    pub hurdle: CrackleHurdle,
}

/// The cost surface over a declared ladder of sizes, and where it stops being flat.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CostCurve {
    pub points: Vec<CostPoint>,
}

impl CostCurve {
    /// Walks every declared size against one state.
    ///
    /// The sizes are the caller's; this does not invent a ladder, because which sizes matter is an
    /// operator fact and not a property of the pool.
    ///
    /// # Errors
    ///
    /// Refuses an empty or unsorted ladder and propagates every exact-arithmetic refusal.
    pub fn walk(
        state: &ExactCurveState,
        clip_quote_in_atoms: &[u128],
        costs: &DeclaredFixedCosts,
    ) -> Result<Self, RoundTripError> {
        if clip_quote_in_atoms.is_empty() {
            return Err(RoundTripError::EmptySizeLadder);
        }
        if clip_quote_in_atoms
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        {
            return Err(RoundTripError::UnorderedSizeLadder);
        }
        let points = clip_quote_in_atoms
            .iter()
            .map(|size| {
                Ok(CostPoint {
                    self_round_trip: self_round_trip(state, *size, costs)?,
                    hurdle: crackle_hurdle(state, *size, costs)?,
                })
            })
            .collect::<Result<Vec<_>, RoundTripError>>()?;
        Ok(Self { points })
    }

    /// The smallest declared size whose hurdle is at least `multiple` times the smallest size's.
    ///
    /// The multiple is the caller's declared threshold. There is no physical knee in a
    /// constant-product curve — the hurdle rises smoothly — so "the knee" is only ever a stated
    /// tolerance for how much worse than the floor is still the floor. Saying so is the point.
    ///
    /// # Errors
    ///
    /// Refuses a multiple below one, and propagates arithmetic failure.
    pub fn knee(&self, multiple: u32) -> Result<Option<&CostPoint>, RoundTripError> {
        if multiple < 1 {
            return Err(RoundTripError::InvalidKneeMultiple);
        }
        let floor = self
            .points
            .first()
            .ok_or(RoundTripError::EmptySizeLadder)?
            .hurdle
            .mark_lift
            .bps_floor()
            .map_err(RoundTripError::Stack)?;
        let threshold = floor
            .checked_mul(u128::from(multiple))
            .ok_or(RoundTripError::Arithmetic)?;
        for point in &self.points {
            if point
                .hurdle
                .mark_lift
                .bps_floor()
                .map_err(RoundTripError::Stack)?
                >= threshold
            {
                return Ok(Some(point));
            }
        }
        Ok(None)
    }
}

/// Buys with `quote_in_atoms` and sells the whole result straight back, at one state.
///
/// # Errors
///
/// Propagates every exact-arithmetic refusal, and refuses a zero input.
pub fn self_round_trip(
    state: &ExactCurveState,
    quote_in_atoms: u128,
    costs: &DeclaredFixedCosts,
) -> Result<SelfRoundTrip, RoundTripError> {
    if quote_in_atoms == 0 {
        return Err(RoundTripError::ZeroSize);
    }
    let buy = state
        .buy_with_quote_in(quote_in_atoms)
        .map_err(RoundTripError::Stack)?;
    let sell = buy
        .next
        .sell_base_in(buy.base_out_atoms)
        .map_err(RoundTripError::Stack)?;
    let venue_loss_atoms = buy
        .quote_in_atoms
        .checked_sub(sell.quote_out_atoms)
        .ok_or(RoundTripError::VenueReturnedMoreThanWasPutIn)?;
    let all_in = venue_loss_atoms
        .checked_add(costs.total_quote_atoms()?)
        .ok_or(RoundTripError::Arithmetic)?;
    Ok(SelfRoundTrip {
        quote_in_atoms: buy.quote_in_atoms,
        base_out_atoms: buy.base_out_atoms,
        quote_returned_atoms: sell.quote_out_atoms,
        venue_loss_atoms,
        venue_cost: ExactRatio::new(venue_loss_atoms, buy.quote_in_atoms)
            .map_err(RoundTripError::Stack)?,
        all_in_cost: ExactRatio::new(all_in, buy.quote_in_atoms).map_err(RoundTripError::Stack)?,
    })
}

/// Smallest net inflow from other participants at which the clip's round trip breaks even.
///
/// The search is a bisection over the declared path, evaluated only with the deployed integer
/// formula. Monotonicity is what makes the bisection sound: more net buying by others cannot lower
/// what a fixed holding fetches.
///
/// # Errors
///
/// Refuses a zero clip, and refuses rather than guessing when no inflow inside the searched range
/// is enough.
pub fn crackle_hurdle(
    state: &ExactCurveState,
    clip_quote_in_atoms: u128,
    costs: &DeclaredFixedCosts,
) -> Result<CrackleHurdle, RoundTripError> {
    if clip_quote_in_atoms == 0 {
        return Err(RoundTripError::ZeroSize);
    }
    let buy = state
        .buy_with_quote_in(clip_quote_in_atoms)
        .map_err(RoundTripError::Stack)?;
    let target = buy
        .quote_in_atoms
        .checked_add(costs.total_quote_atoms()?)
        .ok_or(RoundTripError::Arithmetic)?;
    let held = buy.base_out_atoms;
    let entry = buy.next;

    let proceeds_after = |inflow: u128| -> Result<u128, RoundTripError> {
        let lifted = if inflow == 0 {
            entry
        } else {
            entry
                .buy_with_quote_in(inflow)
                .map_err(RoundTripError::Stack)?
                .next
        };
        Ok(lifted
            .sell_base_in(held)
            .map_err(RoundTripError::Stack)?
            .quote_out_atoms)
    };

    let ceiling = state
        .effective_quote_atoms
        .checked_mul(16)
        .ok_or(RoundTripError::Arithmetic)?;
    if proceeds_after(ceiling)? < target {
        return Err(RoundTripError::NoInflowInRangeBreaksEven);
    }
    let mut low = 0_u128;
    let mut high = ceiling;
    while low < high {
        let mid = low + (high - low) / 2;
        if proceeds_after(mid)? >= target {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    let lifted = if low == 0 {
        entry
    } else {
        entry
            .buy_with_quote_in(low)
            .map_err(RoundTripError::Stack)?
            .next
    };
    Ok(CrackleHurdle {
        clip_quote_in_atoms: buy.quote_in_atoms,
        base_held_atoms: held,
        clip_fraction_of_quote_reserve: ExactRatio::new(
            buy.raw_quote_atoms,
            state.effective_quote_atoms,
        )
        .map_err(RoundTripError::Stack)?,
        other_net_quote_inflow_atoms: low,
        mark_lift: lift(state, &lifted)?,
        proceeds_at_hurdle_atoms: proceeds_after(low)?,
    })
}

/// The clips whose hurdle is inside a declared mark lift: both ends of the interval.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeasibleClipRange {
    /// Smallest clip that still breaks even. Below it the fixed costs, which do not shrink with
    /// size, are a larger share of a smaller trade than the lift can cover.
    pub smallest: CrackleHurdle,
    /// Largest clip that still breaks even. Above it the traversal is what the lift cannot cover.
    pub largest: CrackleHurdle,
}

/// Which clips break even inside a declared mark lift, at this state.
///
/// This is the inverse of [`crackle_hurdle`] and the form an operator actually asks the question
/// in: *I think this coin lifts eight percent — how much can I put in before the geometry eats
/// it?* Both ends are returned because with any fixed cost at all the answer is an interval and
/// not a ceiling: too small and the network fee eats the trade, too large and the curve does.
///
/// The search is exact, over the deployed formula only. It works because the hurdle falls with
/// size while the fixed cost is being amortized and rises with size once traversal dominates, so
/// each end is found by bisection on its own monotone side of the minimum.
///
/// This is a gross break-even boundary. Clearing it means the trip returned what it consumed, not
/// that it paid anybody.
///
/// # Errors
///
/// Refuses a zero lift, and refuses when no clip at all breaks even inside the declared lift —
/// which is the honest answer, not a size.
pub fn feasible_clips_within_declared_lift(
    state: &ExactCurveState,
    declared_lift_bps: u128,
    costs: &DeclaredFixedCosts,
) -> Result<FeasibleClipRange, RoundTripError> {
    if declared_lift_bps == 0 {
        return Err(RoundTripError::ZeroDeclaredLift);
    }
    let fits = |clip: u128| -> Result<bool, RoundTripError> {
        match crackle_hurdle(state, clip, costs) {
            Ok(hurdle) => Ok(hurdle
                .mark_lift
                .bps_floor()
                .map_err(RoundTripError::Stack)?
                <= declared_lift_bps),
            Err(
                RoundTripError::NoInflowInRangeBreaksEven
                | RoundTripError::Stack(
                    StackRefusal::BudgetBelowSmallestSize | StackRefusal::SizeRoundsToNothing,
                ),
            ) => Ok(false),
            Err(other) => Err(other),
        }
    };
    let ceiling = state.effective_quote_atoms / 2;
    let floor = smallest_quotable_clip(state, ceiling)?;

    // Find any clip that fits, by doubling. Nothing about the venue guarantees one exists.
    let mut probe = floor.max(1);
    while !fits(probe)? {
        probe = probe.saturating_mul(2);
        if probe > ceiling {
            return Err(RoundTripError::NoClipFitsDeclaredLift);
        }
    }

    // Upper end: above the probe the hurdle only rises.
    let mut low = probe;
    let mut high = ceiling;
    if fits(high)? {
        low = high;
    } else {
        while low < high {
            let mid = low + (high - low).div_ceil(2);
            if fits(mid)? {
                low = mid;
            } else {
                high = mid - 1;
            }
        }
    }
    let largest = crackle_hurdle(state, low, costs)?;

    // Lower end: below the probe the hurdle only falls as size rises, so the first fitting clip
    // going up from the floor is the boundary.
    let mut lo = floor;
    let mut hi = probe;
    while lo < hi {
        let mid = lo + (hi - lo) / 2;
        if fits(mid)? {
            hi = mid;
        } else {
            lo = mid + 1;
        }
    }
    Ok(FeasibleClipRange {
        smallest: crackle_hurdle(state, lo, costs)?,
        largest,
    })
}

/// Smallest quote budget the venue will turn into at least one base atom, at this state.
fn smallest_quotable_clip(state: &ExactCurveState, ceiling: u128) -> Result<u128, RoundTripError> {
    if state.buy_with_quote_in(ceiling).is_err() {
        return Err(RoundTripError::NoClipFitsDeclaredLift);
    }
    let mut low = 1_u128;
    let mut high = ceiling;
    while low < high {
        let mid = low + (high - low) / 2;
        if state.buy_with_quote_in(mid).is_ok() {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    Ok(low)
}

/// `(Q1/B1) / (Q0/B0) - 1`, exactly.
fn lift(before: &ExactCurveState, after: &ExactCurveState) -> Result<ExactRatio, RoundTripError> {
    let high = after
        .effective_quote_atoms
        .checked_mul(before.base_atoms)
        .ok_or(RoundTripError::Arithmetic)?;
    let low = before
        .effective_quote_atoms
        .checked_mul(after.base_atoms)
        .ok_or(RoundTripError::Arithmetic)?;
    ExactRatio::new(high.saturating_sub(low), low).map_err(RoundTripError::Stack)
}

/// Exactly why a cost could not be produced.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum RoundTripError {
    #[error("clip size is zero")]
    ZeroSize,
    #[error("the declared size ladder is empty")]
    EmptySizeLadder,
    #[error("the declared size ladder is not strictly increasing")]
    UnorderedSizeLadder,
    #[error("a knee multiple below one has no meaning")]
    InvalidKneeMultiple,
    #[error("a declared lift of zero has no meaning")]
    ZeroDeclaredLift,
    #[error("no clip, however small, breaks even inside the declared lift")]
    NoClipFitsDeclaredLift,
    #[error("no inflow inside the searched range breaks even")]
    NoInflowInRangeBreaksEven,
    #[error("an immediate round trip returned more than it consumed, which the venue cannot do")]
    VenueReturnedMoreThanWasPutIn,
    #[error("checked arithmetic failed")]
    Arithmetic,
    #[error(transparent)]
    Stack(#[from] StackRefusal),
}
