//! What one coin's live state costs, assembled before anybody commits to it.
//!
//! Study M0 measured two venues on the same evening. A live bonding curve holding 42 SOL had a fee
//! floor of 247 basis points and could absorb about 1.12 SOL before an eight-percent move stopped
//! paying for the trip. A graduated `PumpSwap` pool holding 1,493 SOL had a fee floor of 60 basis
//! points and could absorb about 54 SOL at the same lift. That is roughly fifty times the tradeable
//! clip, from four times on fees and thirty-five times on depth — and both numbers are readable
//! from one account read *before* anything is committed. This module is that readout.
//!
//! Four things it insists on.
//!
//! **Every price says which price it is.** The reserve ratio, the average price a stated clip would
//! pay, and what a whole position would fetch are three different numbers, and this carries the
//! [`PriceObject`] tag on each rather than emitting a column called `price`.
//!
//! **The break-even clip is an interval, not a ceiling.** With any fixed cost at all the hurdle is
//! U-shaped: below roughly 0.0004 SOL on a bonding curve the network fee eats the trade, and above
//! some size the curve does. [`crate::round_trip::feasible_clips_within_declared_lift`] finds both
//! ends and this reports both.
//!
//! **A rate comes from the program that charges it.** The bonding-curve `Global` account declared a
//! 5 basis-point creator fee on 2026-08-21 while the deployed fee program applied 30, and a
//! frontend's reserve fields were off by 158 times on a live coin. [`FeeRateSource`] has exactly one
//! variant for that reason.
//!
//! **A readout without its age is a lie by omission.** M0 measured a pool mark drifting 35.6 basis
//! points in 49 seconds and a curve's marginal price falling about 3,575 in 13.6 minutes. The
//! binding uncertainty on any of these numbers is not quote error, it is how long ago the state was
//! true, so [`StateAge`] is not optional and [`MeasuredDrift`] says how fast this venue has actually
//! been moving.
//!
//! Nothing here reads the network, and nothing here is a fill, an order, an execution estimate, or
//! advice. It is arithmetic over one observed state.

use core::fmt::Write as _;

use joshi_market_math::{
    fee::CreatorFee,
    quote::AtomicPrice,
    stack::{ExactCurveState, ExactRatio, PriceObject, VenueFormula},
    would_quote::{ChainSecond, ChainToReceiptAge, LocalReceipt, WouldQuoteError},
};

use crate::{
    round_trip::{
        CrackleHurdle, DeclaredFixedCosts, FeasibleClipRange, RoundTripError, SelfRoundTrip,
        crackle_hurdle, feasible_clips_within_declared_lift, self_round_trip,
        smallest_quotable_clip,
    },
    tier::{TierBasis, TierDirection, TierStanding},
};

/// Lamports in one SOL, used only for rendering.
const LAMPORTS_PER_SOL: u128 = 1_000_000_000;

/// Which deployed program the observed state belongs to.
///
/// This is the lever the whole readout exists to expose. It is not a label on a chart: the two
/// venues charge different rates through different operation orders against different reserve sets,
/// and on M0's evening the choice between them was worth about fifty times on tradeable clip.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VenueKind {
    /// Pump bonding curve, still trading. The curve states its own reserves.
    PumpBondingCurve,
    /// Graduated `PumpSwap` pool. Its reserves are two vault balances plus a located term.
    PumpSwapPool,
}

impl VenueKind {
    /// The deployed operation order this venue's instruction uses.
    #[must_use]
    pub const fn formula(self) -> VenueFormula {
        match self {
            Self::PumpBondingCurve => VenueFormula::PumpBondingCurve,
            Self::PumpSwapPool => VenueFormula::PumpSwapExactQuoteIn,
        }
    }

    /// Stable machine label.
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::PumpBondingCurve => "pump_bonding_curve",
            Self::PumpSwapPool => "pumpswap_pool",
        }
    }
}

/// How the effective quote reserve was arrived at, so a reader can audit the number rather than
/// take it.
///
/// The two venues compose it differently, and the `PumpSwap` composition is the one that has
/// already been got wrong: omitting the located term at byte 245 overstates base-out by about 119
/// basis points, four times the pool's whole round-trip fee, in the flattering direction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QuoteReserveComposition {
    /// The bonding curve states its virtual quote reserve directly, in its own account.
    CurveVirtualReserve { virtual_quote_atoms: u128 },
    /// A pool's quote vault balance plus a term this decoder can locate but cannot name.
    VaultBalancePlusLocatedTerm {
        quote_vault_atoms: u128,
        located_term_atoms: u128,
        /// Byte offset the term was read at. The offset is the only identity it has.
        located_term_offset: usize,
    },
}

impl QuoteReserveComposition {
    /// The effective quote reserve these components sum to.
    #[must_use]
    pub const fn effective_quote_atoms(&self) -> u128 {
        match *self {
            Self::CurveVirtualReserve {
                virtual_quote_atoms,
            } => virtual_quote_atoms,
            Self::VaultBalancePlusLocatedTerm {
                quote_vault_atoms,
                located_term_atoms,
                ..
            } => quote_vault_atoms + located_term_atoms,
        }
    }
}

/// Where a fee rate came from.
///
/// One variant, on purpose. The Pump fee program's own configuration account is the only source
/// this crate will accept a rate from, because the two obvious alternatives have both been measured
/// wrong on this codebase's own evidence: the bonding-curve `Global` account understated the creator
/// leg by 25 basis points, and the pump frontend index misreported live reserves by up to 158 times.
/// Widening this enum is how anyone would have to argue for changing that.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FeeRateSource {
    /// Read from the fee program's configuration account for this venue's own program.
    FeeProgramConfig {
        /// The configuration account the rates were read from.
        config_address: String,
        /// Whether every retained tier table selected the same rates at this market cap. When they
        /// did not, the caller had to choose, and that choice is not evidence.
        tables_agreed: bool,
        /// Market cap, in quote atoms, the tier was selected at.
        selected_at_market_cap_quote_atoms: u128,
    },
}

/// The clock a piece of state carries, and the age that follows from it.
///
/// The chain end has whole-second resolution, so an age is an interval and never a scalar.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateAge {
    /// Slot the provider stated it evaluated the read at.
    pub context_slot: u64,
    /// Commitment named in the request. The response body does not restate it.
    pub requested_commitment: String,
    /// The chain's whole-second report for that slot. `None` is an absent record — the provider
    /// stated no block time — and never a zero.
    pub chain_second: Option<ChainSecond>,
    /// When this process finished receiving the response.
    pub local_receipt: LocalReceipt,
}

impl StateAge {
    /// The interval between chain time and local receipt.
    ///
    /// # Errors
    ///
    /// Refuses clocks whose difference overflows. Returns `Ok(None)` when the provider stated no
    /// block time, which is an absent record rather than a failure.
    pub fn chain_to_receipt(&self) -> Result<Option<ChainToReceiptAge>, WouldQuoteError> {
        self.chain_second
            .map(|chain| ChainToReceiptAge::measure(chain, &self.local_receipt))
            .transpose()
    }

    /// How long ago this state was received, at a stated wall clock, in milliseconds.
    ///
    /// This is the part of the age the reader controls: it grows for as long as the readout sits on
    /// screen unread.
    #[must_use]
    pub const fn since_receipt_ms(&self, now_unix_ms: i64) -> i64 {
        now_unix_ms.saturating_sub(self.local_receipt.wall_unix_ms)
    }
}

/// Which way a mark moved between two observations.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriftDirection {
    Up,
    Down,
    Unchanged,
}

/// Two observations of one venue, and what actually moved between them.
///
/// This is a measurement of one window on one venue during one period. It bounds nothing in
/// general, and saying so is the point: it is here so a reader can see whether the state they are
/// about to act on belongs to a market that moves 14 basis points every two seconds or one that has
/// not printed a trade all window.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MeasuredDrift {
    pub first: StateAge,
    pub second: StateAge,
    pub elapsed_slots: u64,
    /// Elapsed local wall time between the two receipts, in milliseconds.
    pub elapsed_local_ms: i64,
    pub direction: DriftDirection,
    /// Absolute change in the marginal pool price, as a fraction of the first observation.
    pub magnitude: ExactRatio,
}

impl MeasuredDrift {
    /// Measures the change in the marginal pool price between two observations of one venue.
    ///
    /// # Errors
    ///
    /// Refuses a zero reserve on either side and propagates wide-arithmetic failure.
    pub fn measure(
        first: (&ExactCurveState, StateAge),
        second: (&ExactCurveState, StateAge),
    ) -> Result<Self, ReadoutError> {
        let (before, first_age) = first;
        let (after, second_age) = second;
        // Cross-multiply so no division rounds before the comparison.
        let low = before
            .effective_quote_atoms
            .checked_mul(after.base_atoms)
            .ok_or(ReadoutError::Arithmetic)?;
        let high = after
            .effective_quote_atoms
            .checked_mul(before.base_atoms)
            .ok_or(ReadoutError::Arithmetic)?;
        let direction = match high.cmp(&low) {
            core::cmp::Ordering::Greater => DriftDirection::Up,
            core::cmp::Ordering::Less => DriftDirection::Down,
            core::cmp::Ordering::Equal => DriftDirection::Unchanged,
        };
        let magnitude = ExactRatio::new(high.abs_diff(low), low).map_err(ReadoutError::Stack)?;
        Ok(Self {
            elapsed_slots: second_age
                .context_slot
                .saturating_sub(first_age.context_slot),
            elapsed_local_ms: second_age
                .local_receipt
                .wall_unix_ms
                .saturating_sub(first_age.local_receipt.wall_unix_ms),
            first: first_age,
            second: second_age,
            direction,
            magnitude,
        })
    }

    /// The measured move scaled to basis points per minute over this one window.
    ///
    /// `None` when the window had no local duration, because a rate over zero time is not a number.
    ///
    /// # Errors
    ///
    /// Propagates wide-arithmetic failure.
    pub fn bps_per_minute(&self) -> Result<Option<u128>, ReadoutError> {
        if self.elapsed_local_ms <= 0 {
            return Ok(None);
        }
        let bps = self.magnitude.bps_ceil().map_err(ReadoutError::Stack)?;
        let elapsed =
            u128::try_from(self.elapsed_local_ms).map_err(|_| ReadoutError::Arithmetic)?;
        Ok(bps
            .checked_mul(60_000)
            .ok_or(ReadoutError::Arithmetic)?
            .checked_div(elapsed))
    }
}

/// The clip the operator actually asked about, walked against this state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntendedClip {
    /// Buy and sell straight back with nothing in between. What changing your mind costs.
    pub abort: SelfRoundTrip,
    /// How far the mark must lift for this clip to return everything it consumed, network cost
    /// included.
    pub hurdle: CrackleHurdle,
    /// The same hurdle with every declared cost outside the venue removed, as a stated control.
    pub hurdle_venue_only: CrackleHurdle,
    /// Average price this clip would pay. Not a mark, and not a fill.
    pub average_price: AtomicPrice,
    /// Which of the seven price objects that average is.
    pub average_price_object: PriceObject,
}

/// Everything one mint's live state says about what a trade on it would cost.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreTradeReadout {
    pub mint: String,
    pub venue: VenueKind,
    /// Account the state was read from.
    pub venue_account: String,
    /// What binds that account to this mint, stated rather than assumed.
    pub venue_binding: String,
    pub state: ExactCurveState,
    pub composition: QuoteReserveComposition,
    pub fee_source: FeeRateSource,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    /// The reserve ratio. The price of an infinitesimal trade and of no real one.
    pub marginal_pool_price: AtomicPrice,
    /// Smallest clip this venue turns into at least one base atom. The left wall.
    pub smallest_quotable_clip_atoms: u128,
    /// Size the fee floor was probed at, which is a declared input and not a venue fact.
    pub fee_floor_probe_quote_atoms: u128,
    /// The probe as a fraction of the effective quote reserve, so a reader can check that
    /// traversal really is negligible at it.
    pub fee_floor_probe_fraction: ExactRatio,
    /// Round trip at the probe size with venue fees only. This is the fee floor.
    pub fee_floor: SelfRoundTrip,
    pub declared_lift_bps: u128,
    /// Both ends of the break-even clip interval at that lift, or exactly why there is none.
    pub break_even_clips: Result<FeasibleClipRange, RoundTripError>,
    pub intended: Option<IntendedClip>,
    /// Where this market cap sits on every retained fee-tier ladder, when the caller supplied
    /// them.
    ///
    /// `None` means the tables were not handed to this readout, never that the venue has no tiers.
    /// The rates in [`Self::state`] came from a tier row either way; this is what says *which*
    /// row, how far the next one is, and which table was believed when they disagreed. Attach it
    /// with [`Self::with_tier_standing`].
    pub tier: Option<TierStanding>,
    pub costs: DeclaredFixedCosts,
    pub age: StateAge,
    pub drift: Option<MeasuredDrift>,
    /// What this readout could not reconstruct. An empty list would mean the work was not done.
    pub unsupported: Vec<String>,
}

/// Everything [`PreTradeReadout::build`] needs that is a declaration rather than a measurement.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadoutRequest {
    /// The mark lift the operator thinks this coin has in it, in basis points. An input.
    pub declared_lift_bps: u128,
    /// Size the fee floor is probed at.
    pub fee_floor_probe_quote_atoms: u128,
    /// The clip the operator wants a hurdle for, if they have one in mind.
    pub intended_clip_quote_atoms: Option<u128>,
    /// Costs outside the venue, with the caller's own provenance attached.
    pub costs: DeclaredFixedCosts,
}

impl PreTradeReadout {
    /// Assembles the readout for one observed state.
    ///
    /// # Errors
    ///
    /// Refuses a state whose reserves do not admit a marginal price, a fee-floor probe the venue
    /// will not quote, and an intended clip the venue will not quote. A declared lift inside which
    /// no clip breaks even is *not* an error — it is an answer, and it is carried in
    /// [`Self::break_even_clips`].
    #[allow(clippy::too_many_arguments)]
    pub fn build(
        mint: impl Into<String>,
        venue: VenueKind,
        venue_account: impl Into<String>,
        venue_binding: impl Into<String>,
        state: ExactCurveState,
        composition: QuoteReserveComposition,
        fee_source: FeeRateSource,
        decimals: (u8, u8),
        request: &ReadoutRequest,
        age: StateAge,
        drift: Option<MeasuredDrift>,
        unsupported: Vec<String>,
    ) -> Result<Self, ReadoutError> {
        if composition.effective_quote_atoms() != state.effective_quote_atoms {
            return Err(ReadoutError::CompositionDoesNotMatchState {
                composed: composition.effective_quote_atoms(),
                stated: state.effective_quote_atoms,
            });
        }
        if state.formula != venue.formula() {
            return Err(ReadoutError::FormulaDoesNotMatchVenue);
        }
        let venue_only = DeclaredFixedCosts::none("venue fees only, stated control");
        let smallest_quotable_clip_atoms =
            smallest_quotable_clip(&state, state.effective_quote_atoms / 2)
                .map_err(ReadoutError::RoundTrip)?;
        let probe = request
            .fee_floor_probe_quote_atoms
            .max(smallest_quotable_clip_atoms);
        let intended = request
            .intended_clip_quote_atoms
            .map(|clip| -> Result<IntendedClip, ReadoutError> {
                let buy = state.buy_with_quote_in(clip).map_err(ReadoutError::Stack)?;
                Ok(IntendedClip {
                    abort: self_round_trip(&state, clip, &request.costs)
                        .map_err(ReadoutError::RoundTrip)?,
                    hurdle: crackle_hurdle(&state, clip, &request.costs)
                        .map_err(ReadoutError::RoundTrip)?,
                    hurdle_venue_only: crackle_hurdle(&state, clip, &venue_only)
                        .map_err(ReadoutError::RoundTrip)?,
                    average_price: AtomicPrice::new(buy.quote_in_atoms, buy.base_out_atoms)
                        .map_err(|error| ReadoutError::Stack(error.into()))?,
                    average_price_object: PriceObject::ExactSizeQuote,
                })
            })
            .transpose()?;
        Ok(Self {
            mint: mint.into(),
            venue,
            venue_account: venue_account.into(),
            venue_binding: venue_binding.into(),
            marginal_pool_price: state.marginal_pool_price().map_err(ReadoutError::Stack)?,
            smallest_quotable_clip_atoms,
            fee_floor_probe_quote_atoms: probe,
            fee_floor_probe_fraction: ExactRatio::new(probe, state.effective_quote_atoms)
                .map_err(ReadoutError::Stack)?,
            fee_floor: self_round_trip(&state, probe, &venue_only)
                .map_err(ReadoutError::RoundTrip)?,
            declared_lift_bps: request.declared_lift_bps,
            break_even_clips: feasible_clips_within_declared_lift(
                &state,
                request.declared_lift_bps,
                &request.costs,
            ),
            intended,
            tier: None,
            costs: request.costs.clone(),
            state,
            composition,
            fee_source,
            base_decimals: decimals.0,
            quote_decimals: decimals.1,
            age,
            drift,
            unsupported,
        })
    }

    /// Attaches where this market cap sits on every retained fee-tier ladder.
    ///
    /// This is separate from [`Self::build`] because the tier tables are read from the fee
    /// program's configuration account and a caller that never read that account has nothing
    /// honest to attach. A readout without it says so rather than printing a row.
    ///
    /// # Errors
    ///
    /// Refuses a standing located at a market cap other than the one the fee rates were selected
    /// at, because a ladder position and a rate that disagree about the market cap describe two
    /// different coins.
    pub fn with_tier_standing(mut self, standing: TierStanding) -> Result<Self, ReadoutError> {
        let FeeRateSource::FeeProgramConfig {
            selected_at_market_cap_quote_atoms,
            ..
        } = &self.fee_source;
        if standing.market_cap_quote_atoms != *selected_at_market_cap_quote_atoms {
            return Err(ReadoutError::TierStandingMarketCapDiffers {
                standing: standing.market_cap_quote_atoms,
                selected_at: *selected_at_market_cap_quote_atoms,
            });
        }
        self.tier = Some(standing);
        Ok(self)
    }

    /// The readout as text, one labelled line per number.
    ///
    /// Every price line names which of the seven price objects it is, every rate names its source,
    /// and the age lines come before the numbers rather than after them.
    #[must_use]
    #[allow(clippy::too_many_lines)]
    pub fn render_card(&self) -> String {
        let mut out = String::new();
        let quote = |atoms: u128| render_decimal(atoms, self.quote_decimals);
        let base = |atoms: u128| render_decimal(atoms, self.base_decimals);

        let _ = writeln!(out, "mint            {}", self.mint);
        let _ = writeln!(
            out,
            "venue           {} at {}",
            self.venue.label(),
            self.venue_account
        );
        let _ = writeln!(out, "binding         {}", self.venue_binding);

        out.push_str("\nstate age\n");
        let _ = writeln!(
            out,
            "  slot          {} at {}",
            self.age.context_slot, self.age.requested_commitment
        );
        match self.age.chain_to_receipt() {
            Ok(Some(interval)) => {
                let _ = writeln!(
                    out,
                    "  chain to receipt  {} to {} ms (an interval; blockTime has whole-second \
                 resolution)",
                    interval.earliest_ms, interval.latest_ms
                );
            }
            Ok(None) => out.push_str(
                "  chain to receipt  UNSUPPORTED: the provider stated no blockTime for this slot. \
                 An absent record, not an age of zero.\n",
            ),
            Err(error) => {
                let _ = writeln!(out, "  chain to receipt  REFUSED: {error}");
            }
        }
        match &self.drift {
            None => out.push_str(
                "  measured drift    NOT MEASURED. This readout does not say how fast this venue \
                 has been moving.\n",
            ),
            Some(drift) => {
                let bps = drift.magnitude.bps_ceil().map_or_else(
                    |error| format!("REFUSED: {error}"),
                    |value| value.to_string(),
                );
                let _ = writeln!(
                    out,
                    "  measured drift    marginal price {} {} bps over {} slots / {} ms",
                    match drift.direction {
                        DriftDirection::Up => "up",
                        DriftDirection::Down => "down",
                        DriftDirection::Unchanged => "unchanged, by",
                    },
                    bps,
                    drift.elapsed_slots,
                    drift.elapsed_local_ms
                );
                match drift.bps_per_minute() {
                    Ok(Some(rate)) => {
                        let _ = writeln!(
                            out,
                            "                    about {rate} bps per minute over this one window; it \
                         bounds nothing in general"
                        );
                    }
                    Ok(None) => out.push_str("                    window had no duration\n"),
                    Err(error) => {
                        let _ = writeln!(out, "                    REFUSED: {error}");
                    }
                }
            }
        }

        out.push_str("\nreserves\n");
        let _ = writeln!(
            out,
            "  base            {} atoms ({})",
            self.state.base_atoms,
            base(self.state.base_atoms)
        );
        let _ = writeln!(
            out,
            "  effective quote {} atoms ({} SOL)",
            self.state.effective_quote_atoms,
            quote(self.state.effective_quote_atoms)
        );
        match &self.composition {
            QuoteReserveComposition::CurveVirtualReserve {
                virtual_quote_atoms,
            } => {
                let _ = writeln!(
                    out,
                    "    composition   the curve account's own virtual quote reserve, {virtual_quote_atoms} atoms"
                );
            }
            QuoteReserveComposition::VaultBalancePlusLocatedTerm {
                quote_vault_atoms,
                located_term_atoms,
                located_term_offset,
            } => {
                let _ = writeln!(
                    out,
                    "    composition   quote vault {quote_vault_atoms} + {located_term_atoms} at \
                     pool byte {located_term_offset}"
                );
                let _ = writeln!(
                    out,
                    "                  {}",
                    if *located_term_atoms == 0 {
                        "that term is zero on this pool, which is a fact about this pool and not \
                         about the layout"
                    } else {
                        "that term is located, not named; omitting it would overstate base-out by \
                         about 119 bps on the pool Study M0 measured"
                    }
                );
            }
        }
        let _ = writeln!(
            out,
            "  marginal_pool_price  {} / {} quote atoms per base atom",
            self.marginal_pool_price.numerator_quote_atoms(),
            self.marginal_pool_price.denominator_base_atoms()
        );

        out.push_str("\nfees\n");
        let FeeRateSource::FeeProgramConfig {
            config_address,
            tables_agreed,
            selected_at_market_cap_quote_atoms,
        } = &self.fee_source;
        let _ = writeln!(
            out,
            "  lp {} bps, protocol {} bps, creator {}",
            self.state.schedule.lp.get(),
            self.state.schedule.protocol.get(),
            match self.state.schedule.creator {
                CreatorFee::Charged(rate) => format!("{} bps", rate.get()),
                CreatorFee::NotApplicable => "not applicable".to_owned(),
                CreatorFee::Unknown => "UNKNOWN".to_owned(),
            }
        );
        let _ = writeln!(
            out,
            "  source          fee program config {config_address}, tier selected at market cap \
             {selected_at_market_cap_quote_atoms} quote atoms"
        );
        let _ = writeln!(
            out,
            "  tables agreed   {tables_agreed} (never the Global account, never the frontend \
             index)"
        );

        out.push_str(&self.render_tier());

        out.push_str("\ncost\n");
        let _ = writeln!(
            out,
            "  smallest quotable clip  {} atoms ({} SOL)",
            self.smallest_quotable_clip_atoms,
            quote(self.smallest_quotable_clip_atoms)
        );
        let _ = writeln!(
            out,
            "  fee floor       {} bps  (abort cost at a {} SOL probe, {} bps of the quote \
             reserve, venue fees only)",
            render_bps(self.fee_floor.venue_cost.bps_ceil()),
            quote(self.fee_floor_probe_quote_atoms),
            render_bps(self.fee_floor_probe_fraction.bps_ceil()),
        );
        let _ = writeln!(out, "  declared lift   {} bps", self.declared_lift_bps);
        match &self.break_even_clips {
            Ok(range) => {
                let _ = writeln!(
                    out,
                    "  break-even clip interval at that lift, with the declared costs:\n    \
                     smallest  {} SOL  (hurdle {} bps)\n    largest   {} SOL  (hurdle {} bps)",
                    quote(range.smallest.clip_quote_in_atoms),
                    render_bps(range.smallest.mark_lift.bps_ceil()),
                    quote(range.largest.clip_quote_in_atoms),
                    render_bps(range.largest.mark_lift.bps_ceil()),
                );
                out.push_str(
                    "    it is an interval and not a ceiling: below the smallest end the fixed \
                     costs eat the trade\n",
                );
            }
            Err(error) => {
                let _ = writeln!(
                    out,
                    "  break-even clip interval at that lift:  NONE. {error}"
                );
            }
        }
        let _ = writeln!(
            out,
            "  declared costs  {} atoms per transaction x {}, flat route {}, unrecovered rent {}\n    \
             provenance    {}",
            self.costs.per_transaction_quote_atoms,
            self.costs.transactions,
            self.costs.flat_route_quote_atoms,
            self.costs.unrecovered_rent_quote_atoms,
            self.costs.provenance,
        );

        match &self.intended {
            None => out.push_str("\nintended clip   none stated\n"),
            Some(clip) => {
                let _ = writeln!(
                    out,
                    "\nintended clip   {} SOL -> {} base",
                    quote(clip.abort.quote_in_atoms),
                    base(clip.abort.base_out_atoms)
                );
                let _ = writeln!(
                    out,
                    "  {:<22} {} / {} quote atoms per base atom",
                    clip.average_price_object.label(),
                    clip.average_price.numerator_quote_atoms(),
                    clip.average_price.denominator_base_atoms()
                );
                let _ = writeln!(
                    out,
                    "  abort cost      {} bps venue only, {} bps all in",
                    render_bps(clip.abort.venue_cost.bps_ceil()),
                    render_bps(clip.abort.all_in_cost.bps_ceil()),
                );
                let _ = writeln!(
                    out,
                    "  hurdle          {} bps venue only, {} bps with the declared costs",
                    render_bps(clip.hurdle_venue_only.mark_lift.bps_ceil()),
                    render_bps(clip.hurdle.mark_lift.bps_ceil()),
                );
                let _ = writeln!(
                    out,
                    "  which needs     {} SOL of net buying by other participants",
                    quote(clip.hurdle.other_net_quote_inflow_atoms)
                );
                let _ = writeln!(
                    out,
                    "  clip / quote reserve  {} bps",
                    render_bps(clip.hurdle.clip_fraction_of_quote_reserve.bps_ceil()),
                );
            }
        }

        out.push_str("\nnot reconstructed\n");
        if self.unsupported.is_empty() {
            out.push_str("  (nothing listed, which would mean the gaps were not looked for)\n");
        }
        for line in &self.unsupported {
            let _ = writeln!(out, "  - {line}");
        }
        out
    }
}

impl PreTradeReadout {
    /// The fee-tier ladder block: which row this market cap selects and how far the next one is.
    ///
    /// A tier row is not decoration. A graduated pool at a 42.8 SOL market cap selects the same
    /// first row a brand-new coin does and pays 125 basis points a leg, four times what the same
    /// program charges a large pool, so "which row" is the whole lever and "how far to the next
    /// one" is the part that is actionable before the trade.
    #[must_use]
    fn render_tier(&self) -> String {
        let mut out = String::new();
        let quote = |atoms: u128| render_decimal(atoms, self.quote_decimals);
        let Some(standing) = &self.tier else {
            out.push_str(
                "\nfee tier        NOT SUPPLIED. The retained tier tables were not handed to this \
                 readout, so it does not say which row the market cap selects. That is a missing \
                 input and not a venue without tiers.\n",
            );
            return out;
        };
        out.push_str("\nfee tier\n");
        let _ = writeln!(
            out,
            "  market cap      {} SOL ({} quote atoms)",
            quote(standing.market_cap_quote_atoms),
            standing.market_cap_quote_atoms
        );
        let _ = writeln!(
            out,
            "  basis           {}",
            match standing.basis {
                TierBasis::EveryTableAgreed =>
                    "every retained table selected the same rates here, so nothing was chosen",
                TierBasis::WorstOfDisagreeingTables =>
                    "the retained tables disagreed and no retained byte says which applies; the \
                     most expensive was used, which errs against the trade and never for it",
            }
        );
        for (index, position) in standing.per_table.iter().enumerate() {
            let applied = if index == standing.applied_table_index {
                " <- applied"
            } else {
                ""
            };
            let _ = writeln!(
                out,
                "  table {index}         row {} of {} at threshold {} SOL, {} bps a leg{applied}",
                position.row_index + 1,
                position.row_count,
                quote(position.threshold_quote_atoms),
                position
                    .leg_bps()
                    .map_or_else(|| "UNKNOWN".to_owned(), |bps| bps.to_string()),
            );
            if position.below_first_threshold {
                out.push_str(
                    "                  that first row is applying as the deployed fallback, not \
                     because its own threshold was reached\n",
                );
            }
            match position.next {
                None => out.push_str(
                    "                  top row: there is no further threshold to cross\n",
                ),
                Some(next) => {
                    let _ = writeln!(
                        out,
                        "                  next row {} at {} SOL: {} SOL of market cap away ({}), \
                         {} bps a leg, {}",
                        next.row_index + 1,
                        quote(next.threshold_quote_atoms),
                        quote(next.gap_quote_atoms),
                        next.gap_of_market_cap.map_or_else(
                            || "no fraction at a zero market cap".to_owned(),
                            |ratio| format!("{} bps of it", render_bps(ratio.bps_ceil()))
                        ),
                        next.leg_bps()
                            .map_or_else(|| "UNKNOWN".to_owned(), |bps| bps.to_string()),
                        match next.direction {
                            TierDirection::Cheaper => "cheaper there",
                            TierDirection::Dearer => "dearer there",
                            TierDirection::Unchanged => "the same rate there",
                            TierDirection::NotComparable =>
                                "not comparable: a creator component was not observed",
                        }
                    );
                }
            }
        }
        out
    }
}

fn render_bps(value: Result<u128, joshi_market_math::stack::StackRefusal>) -> String {
    value.map_or_else(|error| format!("REFUSED({error})"), |bps| bps.to_string())
}

/// Renders an atom count in whole units at a stated number of decimals. Rendering only.
#[must_use]
pub fn render_decimal(atoms: u128, decimals: u8) -> String {
    let scale = 10_u128.pow(u32::from(decimals));
    format!(
        "{}.{:0width$}",
        atoms / scale,
        atoms % scale,
        width = usize::from(decimals)
    )
}

/// Renders lamports as SOL. Rendering only.
#[must_use]
pub fn render_sol(lamports: u128) -> String {
    render_decimal(lamports, 9)
}

/// The number of lamports in one SOL, exposed so a caller does not restate it.
#[must_use]
pub const fn lamports_per_sol() -> u128 {
    LAMPORTS_PER_SOL
}

/// Exactly why a readout could not be assembled. An absent line is never a zero.
#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum ReadoutError {
    #[error(
        "the stated composition sums to {composed} quote atoms but the state carries {stated}; \
         these must be the same number or the readout is describing a reserve nobody observed"
    )]
    CompositionDoesNotMatchState { composed: u128, stated: u128 },
    #[error("the state's operation order is not the one this venue's deployed instruction uses")]
    FormulaDoesNotMatchVenue,
    #[error("checked arithmetic failed")]
    Arithmetic,
    #[error(
        "the tier standing was located at market cap {standing} but the fee rates were selected at \
         {selected_at}; these describe two different coins"
    )]
    TierStandingMarketCapDiffers { standing: u128, selected_at: u128 },
    #[error(transparent)]
    Tier(#[from] crate::tier::TierError),
    #[error(transparent)]
    RoundTrip(#[from] RoundTripError),
    #[error(transparent)]
    Stack(#[from] joshi_market_math::stack::StackRefusal),
}

#[cfg(test)]
mod tests {
    use super::*;
    use joshi_market_math::fee::FeeBps;

    fn schedule(lp: u16, protocol: u16, creator: u16) -> joshi_market_math::fee::FeeSchedule {
        joshi_market_math::fee::FeeSchedule {
            lp: FeeBps::new(lp).expect("lp"),
            protocol: FeeBps::new(protocol).expect("protocol"),
            creator: CreatorFee::Charged(FeeBps::new(creator).expect("creator")),
        }
    }

    /// The graduated pool Study M0 measured, at the state its fixture recorded.
    fn pool_state() -> ExactCurveState {
        ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms: 11_998_257_118_876,
            effective_quote_atoms: 1_493_137_675_872,
            schedule: schedule(20, 5, 5),
        }
    }

    fn receipt(wall_unix_ms: i64) -> LocalReceipt {
        LocalReceipt {
            clock_id: "test".to_owned(),
            monotonic_ns: 0,
            wall_unix_ms,
        }
    }

    fn age(slot: u64, chain: Option<i64>, wall_unix_ms: i64) -> StateAge {
        StateAge {
            context_slot: slot,
            requested_commitment: "finalized".to_owned(),
            chain_second: chain.map(|block_time_unix_s| ChainSecond {
                slot,
                block_time_unix_s,
            }),
            local_receipt: receipt(wall_unix_ms),
        }
    }

    fn request() -> ReadoutRequest {
        ReadoutRequest {
            declared_lift_bps: 800,
            fee_floor_probe_quote_atoms: 1_000_000,
            intended_clip_quote_atoms: Some(1_000_000_000),
            costs: DeclaredFixedCosts {
                provenance: "network fee observed on a landed swap in Study M0's fixture"
                    .to_owned(),
                per_transaction_quote_atoms: 7_422,
                transactions: 2,
                flat_route_quote_atoms: 0,
                unrecovered_rent_quote_atoms: 0,
            },
        }
    }

    fn readout(
        state: ExactCurveState,
        venue: VenueKind,
        composition: QuoteReserveComposition,
    ) -> PreTradeReadout {
        PreTradeReadout::build(
            "mint",
            venue,
            "venue",
            "binding",
            state,
            composition,
            FeeRateSource::FeeProgramConfig {
                config_address: "config".to_owned(),
                tables_agreed: true,
                selected_at_market_cap_quote_atoms: 0,
            },
            (6, 9),
            &request(),
            age(440_832_401, Some(1_787_368_851), 1_787_368_862_968),
            None,
            vec!["a stated gap".to_owned()],
        )
        .expect("readout builds")
    }

    fn pool_readout() -> PreTradeReadout {
        readout(
            pool_state(),
            VenueKind::PumpSwapPool,
            QuoteReserveComposition::VaultBalancePlusLocatedTerm {
                quote_vault_atoms: 1_475_553_170_584,
                located_term_atoms: 17_584_505_288,
                located_term_offset: 245,
            },
        )
    }

    #[test]
    fn the_two_venues_fee_floors_are_the_ones_study_m0_measured() {
        // 247 basis points on the curve against 60 on the pool. Four times, before depth is even
        // considered, and this is the number the readout exists to put in front of a reader.
        let curve = readout(
            ExactCurveState {
                formula: VenueFormula::PumpBondingCurve,
                base_atoms: 764_844_374_721_589,
                effective_quote_atoms: 42_086_993_781,
                schedule: schedule(0, 95, 30),
            },
            VenueKind::PumpBondingCurve,
            QuoteReserveComposition::CurveVirtualReserve {
                virtual_quote_atoms: 42_086_993_781,
            },
        );
        assert_eq!(curve.fee_floor.venue_cost.bps_ceil(), Ok(247));
        assert_eq!(pool_readout().fee_floor.venue_cost.bps_ceil(), Ok(60));
    }

    #[test]
    fn the_break_even_clip_is_an_interval_and_the_pool_carries_about_fifty_times_the_curve() {
        let pool = pool_readout();
        let range = pool.break_even_clips.as_ref().expect("a clip fits");
        assert!(
            range.smallest.clip_quote_in_atoms < range.largest.clip_quote_in_atoms,
            "an interval, not a ceiling"
        );
        // Study M0 read about 54.1 SOL at an eight-percent lift on this state.
        assert!(
            (54_000_000_000..55_000_000_000).contains(&range.largest.clip_quote_in_atoms),
            "largest was {}",
            range.largest.clip_quote_in_atoms
        );
        // And the small end exists at all, which is the whole point of the U shape: with a fixed
        // cost, a clip can be too small as well as too large.
        assert!(range.smallest.clip_quote_in_atoms > 1);
    }

    #[test]
    fn a_readout_with_no_tier_tables_says_they_were_not_supplied_rather_than_printing_a_row() {
        let card = pool_readout().render_card();
        assert!(card.contains("fee tier        NOT SUPPLIED"));
        assert!(card.contains("missing input and not a venue without tiers"));
    }

    #[test]
    fn a_tier_standing_located_at_another_market_cap_is_refused_rather_than_attached() {
        use crate::tier::{TierBasis, TierLadder, TierRow, TierStanding};
        let ladder = TierLadder::new(vec![TierRow {
            threshold_quote_atoms: 0,
            schedule: schedule(20, 5, 5),
        }])
        .expect("ordered");
        // The readout's rates were selected at market cap 0; this standing is about 42.8 SOL.
        let standing =
            TierStanding::locate(&[ladder], 42_800_000_000, 0, TierBasis::EveryTableAgreed)
                .expect("locates");
        let error = pool_readout()
            .with_tier_standing(standing)
            .expect_err("a standing about a different market cap must refuse");
        assert!(matches!(
            error,
            ReadoutError::TierStandingMarketCapDiffers { .. }
        ));
    }

    #[test]
    fn an_attached_standing_renders_the_applied_row_and_the_distance_to_the_next() {
        use crate::tier::{TierBasis, TierLadder, TierRow, TierStanding};
        let ladder = TierLadder::new(vec![
            TierRow {
                threshold_quote_atoms: 0,
                schedule: schedule(2, 93, 30),
            },
            TierRow {
                threshold_quote_atoms: 420_000_000_000,
                schedule: schedule(20, 5, 95),
            },
        ])
        .expect("ordered");
        // Selected at market cap 0, which is what `readout()` states, so the two agree.
        let standing = TierStanding::locate(
            &[ladder.clone(), ladder],
            0,
            0,
            TierBasis::WorstOfDisagreeingTables,
        )
        .expect("locates");
        let card = pool_readout()
            .with_tier_standing(standing)
            .expect("the market caps agree")
            .render_card();
        assert!(card.contains("row 1 of 2"));
        assert!(card.contains("125 bps a leg <- applied"));
        assert!(card.contains("errs against the trade and never for it"));
        assert!(
            card.contains("no fraction at a zero market cap"),
            "a fraction of a zero market cap is an absence, not a zero: {card}"
        );
    }

    #[test]
    fn a_composition_that_does_not_sum_to_the_state_is_refused_rather_than_rendered() {
        let error = PreTradeReadout::build(
            "mint",
            VenueKind::PumpSwapPool,
            "venue",
            "binding",
            pool_state(),
            QuoteReserveComposition::VaultBalancePlusLocatedTerm {
                quote_vault_atoms: 1_475_553_170_584,
                // The exact mistake this guard exists for: the located term left out.
                located_term_atoms: 0,
                located_term_offset: 245,
            },
            FeeRateSource::FeeProgramConfig {
                config_address: "config".to_owned(),
                tables_agreed: true,
                selected_at_market_cap_quote_atoms: 0,
            },
            (6, 9),
            &request(),
            age(1, None, 0),
            None,
            Vec::new(),
        )
        .expect_err("a composition that does not sum to the state must refuse");
        assert!(matches!(
            error,
            ReadoutError::CompositionDoesNotMatchState { .. }
        ));
    }

    #[test]
    fn a_state_walked_with_the_wrong_venues_operation_order_is_refused() {
        let error = PreTradeReadout::build(
            "mint",
            VenueKind::PumpBondingCurve,
            "venue",
            "binding",
            pool_state(),
            QuoteReserveComposition::CurveVirtualReserve {
                virtual_quote_atoms: 1_493_137_675_872,
            },
            FeeRateSource::FeeProgramConfig {
                config_address: "config".to_owned(),
                tables_agreed: true,
                selected_at_market_cap_quote_atoms: 0,
            },
            (6, 9),
            &request(),
            age(1, None, 0),
            None,
            Vec::new(),
        )
        .expect_err("the pool formula is not the curve formula");
        assert!(matches!(error, ReadoutError::FormulaDoesNotMatchVenue));
    }

    #[test]
    fn an_age_without_a_chain_second_is_absent_and_never_zero() {
        let with_chain = age(1, Some(1_787_368_851), 1_787_368_862_968);
        let interval = with_chain
            .chain_to_receipt()
            .expect("measures")
            .expect("a chain second was stated");
        assert_eq!(interval.earliest_ms, 10_968);
        assert_eq!(interval.latest_ms, 11_968);
        assert_eq!(interval.width_ms(), 1_000, "the chain second's resolution");

        let without = age(1, None, 1_787_368_862_968);
        assert_eq!(without.chain_to_receipt(), Ok(None));
        assert_eq!(without.since_receipt_ms(1_787_368_872_968), 10_000);
    }

    #[test]
    fn drift_is_measured_in_the_direction_it_actually_moved() {
        let before = pool_state();
        let after = ExactCurveState {
            effective_quote_atoms: before.effective_quote_atoms * 101 / 100,
            ..before
        };
        let up = MeasuredDrift::measure(
            (&before, age(100, None, 0)),
            (&after, age(150, None, 60_000)),
        )
        .expect("measures");
        assert_eq!(up.direction, DriftDirection::Up);
        // The exact ratio is kept unrounded, so both rounding directions are available and the
        // one-atom truncation in the state above is visible rather than hidden.
        assert_eq!(up.magnitude.bps_floor(), Ok(99));
        assert_eq!(up.magnitude.bps_ceil(), Ok(100));
        assert_eq!(up.elapsed_slots, 50);
        assert_eq!(up.bps_per_minute(), Ok(Some(100)));

        let down = MeasuredDrift::measure(
            (&after, age(100, None, 0)),
            (&before, age(150, None, 60_000)),
        )
        .expect("measures");
        assert_eq!(down.direction, DriftDirection::Down);

        let flat =
            MeasuredDrift::measure((&before, age(100, None, 0)), (&before, age(100, None, 0)))
                .expect("measures");
        assert_eq!(flat.direction, DriftDirection::Unchanged);
        // A rate over no elapsed time is not a number, and is not reported as zero.
        assert_eq!(flat.bps_per_minute(), Ok(None));
    }

    #[test]
    fn the_card_labels_every_price_object_and_never_prints_a_bare_price() {
        let card = pool_readout().render_card();
        assert!(card.contains("marginal_pool_price"));
        assert!(card.contains("exact_size_quote"));
        assert!(card.contains("fee program config"));
        assert!(card.contains("never the Global account, never the frontend index"));
        assert!(card.contains("an interval and not a ceiling"));
        assert!(card.contains("a stated gap"));
        assert!(
            !card.contains("\nprice "),
            "a column called price is not readable"
        );
    }

    #[test]
    fn a_readout_that_lists_no_gaps_says_so_rather_than_looking_complete() {
        let mut readout = pool_readout();
        readout.unsupported.clear();
        assert!(
            readout
                .render_card()
                .contains("which would mean the gaps were not looked for")
        );
    }

    #[test]
    fn rendering_a_decimal_keeps_every_atom() {
        assert_eq!(render_sol(1_493_137_675_872), "1493.137675872");
        assert_eq!(render_sol(1), "0.000000001");
        assert_eq!(render_decimal(1_000_000, 6), "1.000000");
        assert_eq!(lamports_per_sol(), 1_000_000_000);
    }
}
