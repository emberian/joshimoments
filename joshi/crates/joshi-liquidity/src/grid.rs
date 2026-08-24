//! A declared grid-ladder family swept over one retained tape, with the sweep as the interface.
//!
//! The operator's ask was a gridbot; the correction that governs this module was: no hardcoded
//! parameters — sweep an ensemble and show the surface. So there is no single (spacing, clip,
//! band) anywhere in here. [`GridSweepPanelV1::build`] takes declared AXES, runs every cell of
//! spacing x band x clip through the same exact venue arithmetic the desk uses, and the artifact
//! is the whole surface with its own contradictions attached:
//!
//! * **Two baselines per cell, built here and unremovable**: buy-and-hold of the cell's whole
//!   committed capital, and the grid's own initial inventory left untouched (half deployed, half
//!   idle). A grid that does not beat the second did nothing; one that does not beat the first
//!   was a worse way to be long.
//! * **Behaviour identity is computed, not narrated.** Cells whose fills are identical on this
//!   tape collapse into one stated equivalence class: a parameter grid finer than the tape's own
//!   price granularity is one behaviour written down many times, and the panel says which rows
//!   are the same row.
//! * **Structural losers are flagged before replay.** A cell whose rung spacing is at or under
//!   the venue's own round-trip cost for its clip cannot profit on any tape; the flag is
//!   computed from the anchor state before a single event is replayed, and the replay then shows
//!   the loss anyway.
//! * **The time split is declared and never random.** Parameters are chosen on the first window
//!   by a selection rule fixed in this file, evaluated once on the held-out later window, and no
//!   in-sample number is rendered without the held-out number beside it.
//! * **One tape of one coin fits nothing**, and the panel's own vocabulary says so; the
//!   in-sample surface is labelled in-sample, the declarer's prior knowledge of the tape is a
//!   required field, and every haircut and blindness statement of the replay module applies.
//!
//! Nothing here reads a network, signs, or submits. Every number is a would-quote of the
//! deployed integer arithmetic against a state some recorder retained.

use core::fmt::Write as _;

use joshi_market_math::{
    render::{array, integer, object, quoted},
    stack::{ExactCurveState, ExactRatio},
};
use ruint::aliases::U256;
use thiserror::Error;

use crate::{
    paper::{DeclaredHypothesis, VenueBinding, unmodeled_risks},
    replay::{
        DRIFT_WINDOW_MS, M0_CHAIN_TO_RECEIPT_MS, M0_DRIFT_BPS_PER_WINDOW, NOT_A_BACKTEST,
        RULES_ARE_NOT_BLIND, TapeDrift, unmodeled_by_the_haircut,
    },
    round_trip::{DeclaredFixedCosts, self_round_trip},
};

/// Stable contract of the rendered sweep artifact.
pub const GRID_PANEL_CONTRACT: &str = "joshi.liquidity.grid_sweep_panel.v1";

/// The only authority this module holds.
pub const GRID_AUTHORITY: &str = "read_only_no_execution";

/// The whole strategy family, verbatim, so no cell can carry an unstated rule.
pub const GRID_RULES_VERBATIM: &str = "grid ladder v1. The anchor is the marginal pool price of \
the window's first evaluable event, never re-anchored. Levels sit at anchor * (1 + j*spacing/10^4) \
for j = -n..n where n = floor(half_band/spacing). The 2n rungs are the intervals between adjacent \
levels; rung k (k=1 at the top) sells at level n+1-k and buys at level n-k, one spacing lower. At \
the first evaluable event the n rungs above the anchor are funded with base — ONE walk of \
n*clip quote through the deployed buy — and the n rungs below hold one clip of quote each. At \
every later evaluable event, in tape order: every base rung whose sell level the marginal price \
is at or above sells its whole allotment (one combined walk per event, sells before buys); every \
quote rung whose buy level the price is at or below buys exactly one clip (one combined walk, \
base split evenly across the fired rungs, the division remainder held as dust). Proceeds above \
the clip are banked, never compounded: a rung always re-buys exactly one clip. If banked cash \
cannot fund every fired buy, the highest buy levels fire first and the starvation is counted. At \
the window's last evaluable event every held base atom, dust included, is sold in one walk; a \
remainder the venue refuses to quote is valued at zero. Committed capital is 2n*clip; every fill \
is a would-quote against the retained event's own state; the tape's later events do not contain \
this clip's own impact, which is listed as unmodeled. No leverage, no borrowing, no re-anchoring, \
no rule not written in this paragraph.";

/// The selection rule the held-out report is bound to, fixed here so it cannot be re-fit.
pub const SELECTION_RULE_VERBATIM: &str = "selection: on the FIRST window only, the cell with \
the greatest net-of-all-in-cost minus its own adverse-draw haircut; ties broken toward wider \
spacing, then wider band, then larger clip — fewer, bigger, more conservative moves. The chosen \
cell is then run once on the held-out window, fresh-anchored at that window's first evaluable \
event, and that single number is the only out-of-window claim this panel makes.";

/// Why the surface is not a forecast, stated once and rendered everywhere it matters.
pub const ONE_TAPE_FITS_NOTHING: &str = "ONE TAPE OF ONE COIN FITS NOTHING. Every cell of this \
surface is arithmetic on the same single retained tape; the best cell is the largest of N draws \
from one sample, 'tuned on this tape' can never be read as 'expected forward', and the held-out \
window is the same coin on the same afternoon — a weaker check than a different tape, stated as \
such. The full-tape and first-window surfaces are IN-SAMPLE by construction. Reading the \
held-out surface and preferring a different cell than the pre-named one is fitting on the \
held-out window.";

// --- tape input ---------------------------------------------------------------------------------

/// One evaluable event, with the two clocks a polled tape keeps apart.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GridTapeEvent {
    /// Ordinal in the deduplicated tape. The tape's only order.
    pub ordinal: u64,
    /// When the venue printed the event, as the tape states it.
    pub event_unix_ms: i64,
    /// When a live process could first have seen it: the recorder's receive instant for a socket
    /// tape, the retaining poll's receive instant for a polled tape.
    pub available_unix_ms: i64,
    /// The post-trade venue state the event left.
    pub state: ExactCurveState,
}

/// One frame of the tape: an evaluable event or a recorded refusal. Never an interpolation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GridFrame {
    Event(GridTapeEvent),
    Refused {
        ordinal: u64,
        event_unix_ms: i64,
        reason: String,
    },
}

impl GridFrame {
    const fn ordinal(&self) -> u64 {
        match *self {
            Self::Event(GridTapeEvent { ordinal, .. }) | Self::Refused { ordinal, .. } => ordinal,
        }
    }

    const fn event_unix_ms(&self) -> i64 {
        match *self {
            Self::Event(GridTapeEvent { event_unix_ms, .. })
            | Self::Refused { event_unix_ms, .. } => event_unix_ms,
        }
    }
}

/// What the loader measured about the tape's own coverage, carried verbatim into the panel.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TapeCoverage {
    /// Pages or socket frames the loader read.
    pub pages_read: u32,
    /// Events dropped as duplicates of an already-retained identity.
    pub duplicates_dropped: u32,
    /// Gaps where retained coverage is provably discontinuous, each with its own statement.
    pub gaps: Vec<String>,
    /// The loader's own account of arrival semantics — what the availability clock means here.
    pub availability_statement: String,
}

/// Fills reconciled across two independent recordings of the same market, when both exist.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TwoSourceReconciliationV1 {
    pub socket_tape_id: String,
    pub polled_tape_id: String,
    pub overlap_start_unix_ms: i64,
    pub overlap_end_unix_ms: i64,
    pub matched_by_signature: u32,
    pub socket_only: u32,
    pub polled_only: u32,
    /// Matched fills whose stated base legs disagree beyond one atom.
    pub base_leg_disagreements: u32,
    pub statement: String,
}

// --- declaration --------------------------------------------------------------------------------

/// The sweep's axes. Reasons are required: a bound without a reason is a hardcoded parameter
/// wearing a vector.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridSweepAxes {
    pub spacings_bps: Vec<u32>,
    pub spacing_reason: String,
    pub half_bands_bps: Vec<u32>,
    pub band_reason: String,
    pub clips_quote_atoms: Vec<u128>,
    pub clip_reason: String,
}

/// Everything one sweep needs declared before its first frame is read.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridSweepDeclaration {
    pub panel_id: String,
    pub tape_id: String,
    pub tape_provenance: String,
    pub tape_digest_sha256: String,
    pub mint: String,
    pub venue: VenueBinding,
    pub hypothesis: DeclaredHypothesis,
    pub costs: DeclaredFixedCosts,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    /// What the declarer already knew about this tape. Refused blank; see the replay module.
    pub what_was_known_about_this_tape: String,
    /// Every number declared that the tape does not state, named so a reader can attack them.
    pub stated_but_not_in_the_tape: Vec<String>,
    pub coverage: TapeCoverage,
    pub reconciliation: Option<TwoSourceReconciliationV1>,
    /// The time split, as a fraction of the tape's event-time span. Declared, never random.
    pub split_numerator: u32,
    pub split_denominator: u32,
}

// --- cells and outcomes -------------------------------------------------------------------------

/// One cell of the sweep.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GridCellSpec {
    pub spacing_bps: u32,
    pub half_band_bps: u32,
    pub clip_quote_atoms: u128,
}

impl GridCellSpec {
    /// Stable machine name.
    #[must_use]
    pub fn name(&self) -> String {
        format!(
            "s{}_b{}_c{}",
            self.spacing_bps, self.half_band_bps, self.clip_quote_atoms
        )
    }
}

/// A cell structurally unable to profit, computed from the anchor state before any replay.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FloorFlag {
    pub venue_round_trip_bps: u128,
    pub fixed_cost_bps: u128,
    pub floor_bps: u128,
    pub statement: String,
}

/// What one fill was.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GridFillKind {
    InitialInventory,
    RungBuy,
    RungSell,
    FinalLiquidation,
}

impl GridFillKind {
    const fn label(self) -> &'static str {
        match self {
            Self::InitialInventory => "initial_inventory",
            Self::RungBuy => "rung_buy",
            Self::RungSell => "rung_sell",
            Self::FinalLiquidation => "final_liquidation",
        }
    }
}

/// One would-fill of the ladder, priced at one retained event.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GridFill {
    pub event_ordinal: u64,
    pub kind: GridFillKind,
    pub rungs: u32,
    pub quote_atoms: u128,
    pub base_atoms: u128,
    /// How long after the venue printed the event a live process could first have seen it.
    pub availability_delay_ms: i64,
}

/// One completed run of one cell over one window.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridRunOutcome {
    pub rungs_per_side: u32,
    pub committed_quote_atoms: u128,
    pub fills: Vec<GridFill>,
    pub transactions: u32,
    pub rung_sells: u32,
    pub rung_buys: u32,
    /// Buys that could not fire because banked cash was exhausted. Nonzero only below the floor.
    pub cash_starved_rungs: u32,
    /// Venue refusals met while the ladder ran, with the rungs left armed.
    pub refused_walks: u32,
    /// Base atoms left unsold because the venue refused the final quote. Valued at zero.
    pub unsold_base_atoms: u128,
    /// Cash held the moment the window ended, before the terminal inventory was valued.
    pub terminal_cash_quote_atoms: u128,
    /// What liquidating every held base atom returned at the window's last state. On a collapse
    /// tape this is the number that tells the truth: a ladder that "only" lost flow `PnL` still
    /// ends holding tokens worth this little.
    pub terminal_base_value_quote_atoms: u128,
    pub end_quote_atoms: u128,
    pub fixed_cost_atoms: u128,
    pub net_quote_atoms: i128,
    pub net_of_all_in_cost_bps: i128,
    pub venue_only_net_bps: i128,
}

/// One buy-and-hold control over the same window and the same committed capital.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HoldOutcome {
    pub deployed_quote_atoms: u128,
    pub committed_quote_atoms: u128,
    pub exit_quote_atoms: u128,
    pub fixed_cost_atoms: u128,
    pub net_of_all_in_cost_bps: i128,
}

/// The drift bound one cell's result has to clear, priced over its own measured blind time.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridHaircut {
    pub central_rate_bps_per_window: u128,
    pub adverse_rate_bps_per_window: u128,
    pub rate_source: String,
    /// Sum over this cell's fills of the fill's own availability delay.
    pub availability_exposure_ms: i64,
    /// Study M0's chain-to-receipt, once per transaction.
    pub landing_exposure_ms: i64,
    pub total_exposure_ms: i64,
    pub central_bps: u128,
    pub adverse_bps: u128,
    pub statement: String,
}

/// One cell's row on one surface.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridCellResult {
    pub spec: GridCellSpec,
    pub name: String,
    pub below_floor: Option<FloorFlag>,
    pub run: Result<GridRunOutcome, String>,
    pub full_hold: Result<HoldOutcome, String>,
    pub half_hold: Result<HoldOutcome, String>,
    pub excess_over_full_hold_bps: Option<i128>,
    pub excess_over_half_hold_bps: Option<i128>,
    pub haircut: Option<GridHaircut>,
    pub beats_full_hold_outside_adverse: bool,
    pub beats_half_hold_outside_adverse: bool,
    pub beats_doing_nothing_outside_adverse: bool,
    pub verdict: String,
    /// Index into the surface's behaviour classes.
    pub behaviour_class: u32,
}

/// Cells one window could not tell apart: identical fills, to the atom, at the same events.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BehaviourClass {
    pub class: u32,
    pub names: Vec<String>,
    pub net_of_all_in_cost_bps: Option<i128>,
    pub statement: String,
}

/// Which window a surface was computed over.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WindowLabel {
    FullTape,
    FirstWindow,
    HeldOutWindow,
}

impl WindowLabel {
    const fn label(self) -> &'static str {
        match self {
            Self::FullTape => "full_tape_in_sample",
            Self::FirstWindow => "first_window_in_sample",
            Self::HeldOutWindow => "held_out_window",
        }
    }
}

/// The whole sweep over one window.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridSurface {
    pub window: WindowLabel,
    pub window_start_unix_ms: i64,
    pub window_end_unix_ms: i64,
    pub evaluable_events: u32,
    pub refused_frames: u32,
    pub anchor_statement: String,
    pub cells: Vec<GridCellResult>,
    pub classes: Vec<BehaviourClass>,
    pub label: String,
}

/// The one out-of-window claim, bound to the declared selection rule.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeldOutReport {
    pub selection_rule: String,
    pub chosen_cell: Option<String>,
    pub first_window_net_bps: Option<i128>,
    pub first_window_score_bps: Option<i128>,
    /// Buy-and-hold over the FIRST window, printed beside the held-out one so a regime break
    /// between the windows is a pair of numbers, not a paragraph.
    pub first_window_full_hold_bps: Option<i128>,
    pub held_out_net_bps: Option<i128>,
    pub held_out_full_hold_bps: Option<i128>,
    pub held_out_half_hold_bps: Option<i128>,
    pub statement: String,
}

/// The tape as the sweep measured it, before any cell ran.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridTapeSummary {
    pub tape_id: String,
    pub provenance: String,
    pub digest_sha256: String,
    pub frame_count: u32,
    pub evaluable_count: u32,
    pub refused_count: u32,
    pub first_event_unix_ms: i64,
    pub last_event_unix_ms: i64,
    pub span_ms: i64,
    pub median_event_gap_ms: i64,
    pub p90_event_gap_ms: i64,
    pub largest_event_gap_ms: i64,
    pub median_availability_delay_ms: i64,
    pub p90_availability_delay_ms: i64,
    pub largest_availability_delay_ms: i64,
    pub drift: TapeDrift,
    pub distinct_marginal_prices: u32,
    pub nonzero_moves: u32,
    pub min_nonzero_move_bps: u128,
    pub median_nonzero_move_bps: u128,
    pub granularity_statement: String,
}

/// The artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GridSweepPanelV1 {
    pub panel_id: String,
    pub mint: String,
    pub venue: VenueBinding,
    pub operator_words_verbatim: String,
    pub declared_by: String,
    pub rules_declared_at_unix_ms: i64,
    pub costs: DeclaredFixedCosts,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    pub what_was_known_about_this_tape: String,
    pub stated_but_not_in_the_tape: Vec<String>,
    pub coverage: TapeCoverage,
    pub reconciliation: Option<TwoSourceReconciliationV1>,
    pub axes: GridSweepAxes,
    pub tape: GridTapeSummary,
    pub split_numerator: u32,
    pub split_denominator: u32,
    pub split_instant_unix_ms: i64,
    pub full: GridSurface,
    pub first: GridSurface,
    pub held_out: GridSurface,
    pub held_out_report: HeldOutReport,
    pub headline: String,
    pub blindness: String,
}

/// Exactly why a panel refused to be built.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum GridError {
    #[error("the tape holds no frames; an empty read is not an empty tape")]
    EmptyTape,
    #[error("the tape holds no evaluable event, so nothing could be replayed")]
    NoEvaluableEvent,
    #[error("the tape's frames are not in nondecreasing event order at ordinal {ordinal}")]
    TapeOutOfOrder { ordinal: u64 },
    #[error("the tape mixes venue formulas, which one ladder cannot replay across")]
    MixedFormulas,
    #[error("an availability clock precedes its own event at ordinal {ordinal}")]
    AvailabilityBeforeEvent { ordinal: u64 },
    #[error("a sweep axis is empty, unsorted, or holds a zero; an ensemble of nothing is a point")]
    DegenerateAxis,
    #[error("a sweep axis has no stated reason; a bound without a reason is a hardcoded number")]
    AxisReasonNotStated,
    #[error("a half band at or above 10000 bps puts a level at or below zero price")]
    BandTooWide,
    #[error("a declared identity or provenance string is blank")]
    BlankIdentity,
    #[error(
        "the panel does not state what its declarer already knew about this tape; see the replay \
         module's refusal of exactly this"
    )]
    PriorKnowledgeNotStated,
    #[error("the declared split is degenerate; it must satisfy 0 < numerator < denominator")]
    DegenerateSplit,
    #[error("checked arithmetic failed while building the panel")]
    Arithmetic,
}

// --- build --------------------------------------------------------------------------------------

impl GridSweepPanelV1 {
    /// Sweeps every declared cell over the full tape, the first window, and the held-out window.
    ///
    /// # Errors
    ///
    /// Refuses the degenerate declarations listed on [`GridError`]; a cell that cannot run on a
    /// window is a stated row, never a panel refusal.
    #[allow(clippy::too_many_lines)] // One panel, built in the order its parts bind.
    pub fn build(
        declaration: &GridSweepDeclaration,
        frames: &[GridFrame],
        axes: &GridSweepAxes,
    ) -> Result<Self, GridError> {
        if frames.is_empty() {
            return Err(GridError::EmptyTape);
        }
        if declaration.panel_id.trim().is_empty()
            || declaration.tape_id.trim().is_empty()
            || declaration.tape_provenance.trim().is_empty()
            || declaration.tape_digest_sha256.trim().is_empty()
        {
            return Err(GridError::BlankIdentity);
        }
        if declaration.what_was_known_about_this_tape.trim().is_empty() {
            return Err(GridError::PriorKnowledgeNotStated);
        }
        if declaration.split_numerator == 0
            || declaration.split_numerator >= declaration.split_denominator
        {
            return Err(GridError::DegenerateSplit);
        }
        check_axes(axes)?;
        let mut previous = frames[0].event_unix_ms();
        for frame in frames {
            if frame.event_unix_ms() < previous {
                return Err(GridError::TapeOutOfOrder {
                    ordinal: frame.ordinal(),
                });
            }
            previous = frame.event_unix_ms();
            if let GridFrame::Event(event) = frame
                && event.available_unix_ms < event.event_unix_ms
            {
                return Err(GridError::AvailabilityBeforeEvent {
                    ordinal: event.ordinal,
                });
            }
        }
        let events: Vec<&GridTapeEvent> = frames
            .iter()
            .filter_map(|frame| match frame {
                GridFrame::Event(event) => Some(event),
                GridFrame::Refused { .. } => None,
            })
            .collect();
        let Some(first_event) = events.first() else {
            return Err(GridError::NoEvaluableEvent);
        };
        if events
            .iter()
            .any(|event| event.state.formula != first_event.state.formula)
        {
            return Err(GridError::MixedFormulas);
        }
        let tape = summarise(declaration, frames, &events);
        let rates = haircut_rates(&tape.drift);
        let split_instant = tape
            .first_event_unix_ms
            .checked_add(
                tape.span_ms
                    .checked_mul(i64::from(declaration.split_numerator))
                    .ok_or(GridError::Arithmetic)?
                    / i64::from(declaration.split_denominator),
            )
            .ok_or(GridError::Arithmetic)?;
        let cells = cell_specs(axes);
        let refused_before = |cutoff: i64, from: i64| {
            u32::try_from(
                frames
                    .iter()
                    .filter(|frame| {
                        matches!(frame, GridFrame::Refused { .. })
                            && frame.event_unix_ms() >= from
                            && frame.event_unix_ms() < cutoff
                    })
                    .count(),
            )
            .unwrap_or(u32::MAX)
        };
        let full_events: Vec<GridTapeEvent> = events.iter().map(|event| **event).collect();
        let first_events: Vec<GridTapeEvent> = events
            .iter()
            .filter(|event| event.event_unix_ms < split_instant)
            .map(|event| **event)
            .collect();
        let held_events: Vec<GridTapeEvent> = events
            .iter()
            .filter(|event| event.event_unix_ms >= split_instant)
            .map(|event| **event)
            .collect();
        let full = surface(
            WindowLabel::FullTape,
            &full_events,
            refused_before(i64::MAX, i64::MIN),
            &cells,
            declaration,
            &rates,
        );
        let first = surface(
            WindowLabel::FirstWindow,
            &first_events,
            refused_before(split_instant, i64::MIN),
            &cells,
            declaration,
            &rates,
        );
        let held_out = surface(
            WindowLabel::HeldOutWindow,
            &held_events,
            refused_before(i64::MAX, split_instant),
            &cells,
            declaration,
            &rates,
        );
        let held_out_report = held_out_report(&first, &held_out);
        let headline = headline(&full, &held_out_report, cells.len());
        let blindness = format!(
            "A replay sees only the events the tape retained. This tape retained {} evaluable \
             events over {} ms (event-clock gaps median {} / p90 {} / max {} ms), and a live \
             process could first have seen each event a median {} ms — p90 {} ms, worst {} ms — \
             after the venue printed it. Every rung crossing that began and completed between \
             two retained events is invisible to every cell, and no rule here could really have \
             reacted faster than the availability clock allows; the haircut prices exactly that \
             blind time per fill. {}",
            tape.evaluable_count,
            tape.span_ms,
            tape.median_event_gap_ms,
            tape.p90_event_gap_ms,
            tape.largest_event_gap_ms,
            tape.median_availability_delay_ms,
            tape.p90_availability_delay_ms,
            tape.largest_availability_delay_ms,
            declaration.coverage.availability_statement
        );
        Ok(Self {
            panel_id: declaration.panel_id.clone(),
            mint: declaration.mint.clone(),
            venue: declaration.venue.clone(),
            operator_words_verbatim: declaration.hypothesis.operator_words_verbatim.clone(),
            declared_by: declaration.hypothesis.declared_by.clone(),
            rules_declared_at_unix_ms: declaration.hypothesis.declared_at_unix_ms,
            costs: declaration.costs.clone(),
            base_decimals: declaration.base_decimals,
            quote_decimals: declaration.quote_decimals,
            what_was_known_about_this_tape: declaration.what_was_known_about_this_tape.clone(),
            stated_but_not_in_the_tape: declaration.stated_but_not_in_the_tape.clone(),
            coverage: declaration.coverage.clone(),
            reconciliation: declaration.reconciliation.clone(),
            axes: axes.clone(),
            tape,
            split_numerator: declaration.split_numerator,
            split_denominator: declaration.split_denominator,
            split_instant_unix_ms: split_instant,
            full,
            first,
            held_out,
            held_out_report,
            headline,
            blindness,
        })
    }
}

fn check_axes(axes: &GridSweepAxes) -> Result<(), GridError> {
    if axes.spacing_reason.trim().is_empty()
        || axes.band_reason.trim().is_empty()
        || axes.clip_reason.trim().is_empty()
    {
        return Err(GridError::AxisReasonNotStated);
    }
    let ordered_u32 = |values: &[u32]| {
        !values.is_empty()
            && values.windows(2).all(|pair| pair[0] < pair[1])
            && values.iter().all(|&value| value > 0)
    };
    if !ordered_u32(&axes.spacings_bps)
        || !ordered_u32(&axes.half_bands_bps)
        || axes.clips_quote_atoms.is_empty()
        || axes
            .clips_quote_atoms
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || axes.clips_quote_atoms.contains(&0)
    {
        return Err(GridError::DegenerateAxis);
    }
    if axes.half_bands_bps.iter().any(|&band| band >= 10_000) {
        return Err(GridError::BandTooWide);
    }
    Ok(())
}

fn cell_specs(axes: &GridSweepAxes) -> Vec<GridCellSpec> {
    let mut cells = Vec::new();
    for &spacing_bps in &axes.spacings_bps {
        for &half_band_bps in &axes.half_bands_bps {
            if half_band_bps < spacing_bps {
                continue; // no whole rung fits; the axis product states this cell away
            }
            for &clip_quote_atoms in &axes.clips_quote_atoms {
                cells.push(GridCellSpec {
                    spacing_bps,
                    half_band_bps,
                    clip_quote_atoms,
                });
            }
        }
    }
    cells
}

// --- tape summary -------------------------------------------------------------------------------

fn quantile<T: Copy>(sorted: &[T], percent: usize) -> Option<T> {
    if sorted.is_empty() {
        return None;
    }
    let index = (sorted.len() * percent / 100).min(sorted.len() - 1);
    sorted.get(index).copied()
}

fn count(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}

/// `|a - b| / a` in floored basis points between two marginal prices, exactly.
fn abs_move_bps(from: &ExactCurveState, to: &ExactCurveState) -> Option<u128> {
    let cross_from = from.effective_quote_atoms.checked_mul(to.base_atoms)?;
    let cross_to = to.effective_quote_atoms.checked_mul(from.base_atoms)?;
    ExactRatio::new(cross_from.abs_diff(cross_to), cross_from)
        .ok()?
        .bps_floor()
        .ok()
}

fn measure_drift(events: &[&GridTapeEvent]) -> TapeDrift {
    let mut measured: Vec<u128> = Vec::new();
    let mut unmeasurable = 0_u32;
    let mut ahead = 0_usize;
    for (position, event) in events.iter().enumerate() {
        if ahead < position {
            ahead = position;
        }
        while ahead < events.len()
            && events[ahead]
                .event_unix_ms
                .saturating_sub(event.event_unix_ms)
                < DRIFT_WINDOW_MS
        {
            ahead += 1;
        }
        if ahead >= events.len() {
            break;
        }
        match abs_move_bps(&event.state, &events[ahead].state) {
            Some(bps) => measured.push(bps),
            None => unmeasurable += 1,
        }
    }
    measured.sort_unstable();
    TapeDrift {
        window_ms: DRIFT_WINDOW_MS,
        windows_measured: count(measured.len()),
        windows_unmeasurable: unmeasurable,
        median_abs_bps: quantile(&measured, 50).unwrap_or(0),
        p90_abs_bps: quantile(&measured, 90).unwrap_or(0),
        max_abs_bps: measured.last().copied().unwrap_or(0),
    }
}

fn summarise(
    declaration: &GridSweepDeclaration,
    frames: &[GridFrame],
    events: &[&GridTapeEvent],
) -> GridTapeSummary {
    let mut gaps: Vec<i64> = events
        .windows(2)
        .map(|pair| pair[1].event_unix_ms.saturating_sub(pair[0].event_unix_ms))
        .collect();
    gaps.sort_unstable();
    let mut delays: Vec<i64> = events
        .iter()
        .map(|event| event.available_unix_ms.saturating_sub(event.event_unix_ms))
        .collect();
    delays.sort_unstable();
    let mut moves: Vec<u128> = Vec::new();
    let mut distinct = 1_u32;
    for pair in events.windows(2) {
        match abs_move_bps(&pair[0].state, &pair[1].state) {
            Some(0) | None => {}
            Some(bps) => {
                moves.push(bps);
            }
        }
        if pair[0].state.effective_quote_atoms != pair[1].state.effective_quote_atoms
            || pair[0].state.base_atoms != pair[1].state.base_atoms
        {
            distinct += 1;
        }
    }
    moves.sort_unstable();
    let min_move = moves.first().copied().unwrap_or(0);
    let median_move = quantile(&moves, 50).unwrap_or(0);
    let first = events.first().map_or(0, |event| event.event_unix_ms);
    let last = events.last().map_or(0, |event| event.event_unix_ms);
    GridTapeSummary {
        tape_id: declaration.tape_id.clone(),
        provenance: declaration.tape_provenance.clone(),
        digest_sha256: declaration.tape_digest_sha256.clone(),
        frame_count: count(frames.len()),
        evaluable_count: count(events.len()),
        refused_count: count(frames.len() - events.len()),
        first_event_unix_ms: first,
        last_event_unix_ms: last,
        span_ms: last.saturating_sub(first),
        median_event_gap_ms: quantile(&gaps, 50).unwrap_or(0),
        p90_event_gap_ms: quantile(&gaps, 90).unwrap_or(0),
        largest_event_gap_ms: gaps.last().copied().unwrap_or(0),
        median_availability_delay_ms: quantile(&delays, 50).unwrap_or(0),
        p90_availability_delay_ms: quantile(&delays, 90).unwrap_or(0),
        largest_availability_delay_ms: delays.last().copied().unwrap_or(0),
        drift: measure_drift(events),
        distinct_marginal_prices: distinct,
        nonzero_moves: count(moves.len()),
        min_nonzero_move_bps: min_move,
        median_nonzero_move_bps: median_move,
        granularity_statement: format!(
            "this tape's price moves in steps: {} distinct marginal prices over {} evaluable \
             events, smallest nonzero inter-event move {} bps, median {} bps. Ladder spacings \
             closer together than the moves the tape actually takes cannot produce different \
             fills, and the behaviour classes below are where that collapse actually happened.",
            distinct,
            events.len(),
            min_move,
            median_move
        ),
    }
}

// --- haircut ------------------------------------------------------------------------------------

struct HaircutRates {
    central: u128,
    adverse: u128,
    source: String,
}

fn haircut_rates(drift: &TapeDrift) -> HaircutRates {
    let central = M0_DRIFT_BPS_PER_WINDOW.max(drift.median_abs_bps);
    let adverse = M0_DRIFT_BPS_PER_WINDOW.max(drift.p90_abs_bps);
    HaircutRates {
        central,
        adverse,
        source: format!(
            "central rate {central} bps and adverse rate {adverse} bps per {} ms: each the worse \
             of Study M0's measured {M0_DRIFT_BPS_PER_WINDOW} bps on a real pool and this tape's \
             own absolute move over the same window (median {} bps, p90 {} bps, worst {} bps \
             over {} windows), scaled linearly in exposure time.",
            drift.window_ms,
            drift.median_abs_bps,
            drift.p90_abs_bps,
            drift.max_abs_bps,
            drift.windows_measured
        ),
    }
}

fn haircut_for(outcome: &GridRunOutcome, rates: &HaircutRates) -> GridHaircut {
    let availability: i64 = outcome
        .fills
        .iter()
        .map(|fill| fill.availability_delay_ms.max(0))
        .sum();
    let landing = M0_CHAIN_TO_RECEIPT_MS.saturating_mul(i64::from(outcome.transactions));
    let total = availability.saturating_add(landing);
    let price = |rate: u128| {
        u128::try_from(total.max(0))
            .ok()
            .and_then(|exposure| exposure.checked_mul(rate))
            .and_then(|numerator| {
                u128::try_from(DRIFT_WINDOW_MS)
                    .ok()
                    .map(|window| numerator.div_ceil(window))
            })
            .unwrap_or(u128::MAX)
    };
    GridHaircut {
        central_rate_bps_per_window: rates.central,
        adverse_rate_bps_per_window: rates.adverse,
        rate_source: rates.source.clone(),
        availability_exposure_ms: availability,
        landing_exposure_ms: landing,
        total_exposure_ms: total,
        central_bps: price(rates.central),
        adverse_bps: price(rates.adverse),
        statement: format!(
            "blind time this cell's {} fills actually carried: {} ms of measured \
             availability delay (the tape could not have shown a live process each fill any \
             sooner) plus {} ms of Study M0 chain-to-receipt, once per transaction. A cell that \
             churns more rungs carries a proportionally larger bound; that is the cost of \
             churn, not a penalty.",
            outcome.fills.len(),
            availability,
            landing
        ),
    }
}

// --- the ladder engine --------------------------------------------------------------------------

#[derive(Clone, Copy)]
struct Anchor {
    quote: u128,
    base: u128,
}

/// Compares the event's marginal price against `anchor * (10^4 + offset_bps) / 10^4`, exactly.
fn against_level(state: &ExactCurveState, anchor: Anchor, offset_bps: i64) -> core::cmp::Ordering {
    let scale = 10_000_i64 + offset_bps;
    debug_assert!(scale > 0, "band width is checked at declaration");
    let scale = u128::try_from(scale.max(1)).unwrap_or(1);
    let lhs =
        U256::from(state.effective_quote_atoms) * U256::from(anchor.base) * U256::from(10_000_u32);
    let rhs = U256::from(anchor.quote) * U256::from(scale) * U256::from(state.base_atoms);
    lhs.cmp(&rhs)
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum RungHolding {
    Base { allotment: u128 },
    Quote,
}

/// Runs one cell's declared ladder over one window of evaluable events.
#[allow(clippy::too_many_lines)] // One declared state machine, in the order its rules bind.
fn run_grid(
    events: &[GridTapeEvent],
    spec: &GridCellSpec,
    costs: &DeclaredFixedCosts,
) -> Result<GridRunOutcome, String> {
    if events.len() < 2 {
        return Err(format!(
            "the window holds {} evaluable events; a ladder needs at least an anchor event and a \
             final event, and nothing was substituted",
            events.len()
        ));
    }
    let rungs_per_side = spec.half_band_bps / spec.spacing_bps;
    if rungs_per_side == 0 {
        return Err("no whole rung fits inside the half band at this spacing".to_owned());
    }
    let n = u128::from(rungs_per_side);
    let committed = spec
        .clip_quote_atoms
        .checked_mul(2 * n)
        .ok_or("committed capital overflows")?;
    let first = &events[0];
    let anchor = Anchor {
        quote: first.state.effective_quote_atoms,
        base: first.state.base_atoms,
    };
    let initial_spend = spec.clip_quote_atoms * n;
    let initial = first
        .state
        .buy_with_quote_in(initial_spend)
        .map_err(|refusal| {
            format!("the venue refused the initial inventory walk at the anchor state: {refusal}")
        })?;
    let per_rung = initial.base_out_atoms / n;
    if per_rung == 0 {
        return Err(
            "the initial inventory splits to zero base atoms per rung at this clip".to_owned(),
        );
    }
    let mut dust = initial.base_out_atoms - per_rung * n;
    let mut cash = committed - initial_spend;
    let mut fills = vec![GridFill {
        event_ordinal: first.ordinal,
        kind: GridFillKind::InitialInventory,
        rungs: rungs_per_side,
        quote_atoms: initial.quote_in_atoms,
        base_atoms: initial.base_out_atoms,
        availability_delay_ms: first.available_unix_ms.saturating_sub(first.event_unix_ms),
    }];
    let mut transactions = 1_u32;
    let mut rung_sells = 0_u32;
    let mut rung_buys = 0_u32;
    let mut cash_starved = 0_u32;
    let mut refused_walks = 0_u32;
    // Rung k (1-based, k=1 at the top) sells at level n+1-k and buys at level n-k.
    let mut rungs: Vec<RungHolding> = (1..=2 * rungs_per_side)
        .map(|k| {
            if k <= rungs_per_side {
                RungHolding::Base {
                    allotment: per_rung,
                }
            } else {
                RungHolding::Quote
            }
        })
        .collect();
    let spacing = i64::from(spec.spacing_bps);
    let side = i64::from(rungs_per_side);
    let sell_offset = |k: usize| (side + 1 - i64::try_from(k).unwrap_or(i64::MAX)) * spacing;
    let buy_offset = |k: usize| (side - i64::try_from(k).unwrap_or(i64::MAX)) * spacing;
    for event in &events[1..] {
        let delay = event.available_unix_ms.saturating_sub(event.event_unix_ms);
        // Sells before buys, as declared. One combined walk per direction per event.
        let selling: Vec<usize> = rungs
            .iter()
            .enumerate()
            .filter(|(index, holding)| {
                matches!(holding, RungHolding::Base { .. })
                    && against_level(&event.state, anchor, sell_offset(index + 1))
                        != core::cmp::Ordering::Less
            })
            .map(|(index, _)| index)
            .collect();
        if !selling.is_empty() {
            let total: u128 = selling
                .iter()
                .map(|&index| match rungs[index] {
                    RungHolding::Base { allotment } => allotment,
                    RungHolding::Quote => 0,
                })
                .sum();
            match event.state.sell_base_in(total) {
                Ok(walked) => {
                    cash = cash
                        .checked_add(walked.quote_out_atoms)
                        .ok_or("cash overflows")?;
                    for &index in &selling {
                        rungs[index] = RungHolding::Quote;
                    }
                    rung_sells += count(selling.len());
                    transactions += 1;
                    fills.push(GridFill {
                        event_ordinal: event.ordinal,
                        kind: GridFillKind::RungSell,
                        rungs: count(selling.len()),
                        quote_atoms: walked.quote_out_atoms,
                        base_atoms: total,
                        availability_delay_ms: delay,
                    });
                }
                Err(_) => refused_walks += 1, // rungs stay armed; the refusal is counted
            }
        }
        // Buys: highest buy levels first, as declared, so starvation is deterministic.
        let buying: Vec<usize> = rungs
            .iter()
            .enumerate()
            .filter(|(index, holding)| {
                **holding == RungHolding::Quote
                    && against_level(&event.state, anchor, buy_offset(index + 1))
                        != core::cmp::Ordering::Greater
            })
            .map(|(index, _)| index)
            .collect();
        if !buying.is_empty() {
            let affordable = usize::try_from(cash / spec.clip_quote_atoms).unwrap_or(usize::MAX);
            let fired = &buying[..buying.len().min(affordable)];
            cash_starved += count(buying.len() - fired.len());
            if !fired.is_empty() {
                let spend = spec.clip_quote_atoms * fired.len() as u128;
                match event.state.buy_with_quote_in(spend) {
                    Ok(walked) => {
                        cash -= spend;
                        let share = walked.base_out_atoms / fired.len() as u128;
                        dust += walked.base_out_atoms - share * fired.len() as u128;
                        for &index in fired {
                            rungs[index] = RungHolding::Base { allotment: share };
                        }
                        rung_buys += count(fired.len());
                        transactions += 1;
                        fills.push(GridFill {
                            event_ordinal: event.ordinal,
                            kind: GridFillKind::RungBuy,
                            rungs: count(fired.len()),
                            quote_atoms: spend,
                            base_atoms: walked.base_out_atoms,
                            availability_delay_ms: delay,
                        });
                    }
                    Err(_) => refused_walks += 1,
                }
            }
        }
    }
    let last = &events[events.len() - 1];
    let held: u128 = rungs
        .iter()
        .map(|holding| match holding {
            RungHolding::Base { allotment } => *allotment,
            RungHolding::Quote => 0,
        })
        .sum::<u128>()
        + dust;
    let mut unsold = 0_u128;
    let terminal_cash = cash;
    let mut terminal_base_value = 0_u128;
    if held > 0 {
        if let Ok(walked) = last.state.sell_base_in(held) {
            terminal_base_value = walked.quote_out_atoms;
            cash = cash
                .checked_add(walked.quote_out_atoms)
                .ok_or("cash overflows")?;
            transactions += 1;
            fills.push(GridFill {
                event_ordinal: last.ordinal,
                kind: GridFillKind::FinalLiquidation,
                rungs: 0,
                quote_atoms: walked.quote_out_atoms,
                base_atoms: held,
                availability_delay_ms: last.available_unix_ms.saturating_sub(last.event_unix_ms),
            });
        } else {
            unsold = held; // valued at zero, which errs against the trade, and stated
            refused_walks += 1;
        }
    }
    let fixed = costs
        .per_transaction_quote_atoms
        .checked_mul(u128::from(transactions))
        .and_then(|value| value.checked_add(costs.flat_route_quote_atoms))
        .and_then(|value| value.checked_add(costs.unrecovered_rent_quote_atoms))
        .ok_or("fixed costs overflow")?;
    let net = i128::try_from(cash).map_err(|_| "cash exceeds i128")?
        - i128::try_from(committed).map_err(|_| "committed exceeds i128")?
        - i128::try_from(fixed).map_err(|_| "fixed exceeds i128")?;
    let committed_i = i128::try_from(committed).map_err(|_| "committed exceeds i128")?;
    let bps = net
        .checked_mul(10_000)
        .ok_or("net overflows")?
        .div_euclid(committed_i);
    let venue_only = (i128::try_from(cash).map_err(|_| "cash exceeds i128")? - committed_i)
        .checked_mul(10_000)
        .ok_or("net overflows")?
        .div_euclid(committed_i);
    Ok(GridRunOutcome {
        rungs_per_side,
        committed_quote_atoms: committed,
        fills,
        transactions,
        rung_sells,
        rung_buys,
        cash_starved_rungs: cash_starved,
        refused_walks,
        unsold_base_atoms: unsold,
        terminal_cash_quote_atoms: terminal_cash,
        terminal_base_value_quote_atoms: terminal_base_value,
        end_quote_atoms: cash,
        fixed_cost_atoms: fixed,
        net_quote_atoms: net,
        net_of_all_in_cost_bps: bps,
        venue_only_net_bps: venue_only,
    })
}

/// Buy-and-hold over the same window: deploy at the first event, sell at the last, two
/// transactions, the rest of the committed capital idle.
fn run_hold(
    events: &[GridTapeEvent],
    deployed: u128,
    committed: u128,
    costs: &DeclaredFixedCosts,
) -> Result<HoldOutcome, String> {
    if events.len() < 2 {
        return Err("the window holds fewer than two evaluable events".to_owned());
    }
    let entry = events[0]
        .state
        .buy_with_quote_in(deployed)
        .map_err(|refusal| format!("the venue refused the entry walk: {refusal}"))?;
    let exit = events[events.len() - 1]
        .state
        .sell_base_in(entry.base_out_atoms)
        .map_err(|refusal| format!("the venue refused the exit walk: {refusal}"))?;
    let fixed = costs
        .per_transaction_quote_atoms
        .checked_mul(2)
        .and_then(|value| value.checked_add(costs.flat_route_quote_atoms))
        .and_then(|value| value.checked_add(costs.unrecovered_rent_quote_atoms))
        .ok_or("fixed costs overflow")?;
    let end = committed - deployed + exit.quote_out_atoms;
    let committed_i = i128::try_from(committed).map_err(|_| "committed exceeds i128")?;
    let net = i128::try_from(end).map_err(|_| "end exceeds i128")?
        - committed_i
        - i128::try_from(fixed).map_err(|_| "fixed exceeds i128")?;
    Ok(HoldOutcome {
        deployed_quote_atoms: deployed,
        committed_quote_atoms: committed,
        exit_quote_atoms: exit.quote_out_atoms,
        fixed_cost_atoms: fixed,
        net_of_all_in_cost_bps: net
            .checked_mul(10_000)
            .ok_or("net overflows")?
            .div_euclid(committed_i),
    })
}

/// The structural floor for one cell at one anchor state, before any replay.
fn floor_flag(
    spec: &GridCellSpec,
    anchor_state: &ExactCurveState,
    costs: &DeclaredFixedCosts,
) -> Option<FloorFlag> {
    let venue_bps = self_round_trip(anchor_state, spec.clip_quote_atoms, costs)
        .ok()
        .and_then(|trip| trip.venue_cost.bps_ceil().ok())?;
    let per_round_trip_fixed = costs.per_transaction_quote_atoms.checked_mul(2)?;
    let fixed_bps = per_round_trip_fixed
        .checked_mul(10_000)?
        .div_ceil(spec.clip_quote_atoms);
    let floor_bps = venue_bps.checked_add(fixed_bps)?;
    if u128::from(spec.spacing_bps) > floor_bps {
        return None;
    }
    Some(FloorFlag {
        venue_round_trip_bps: venue_bps,
        fixed_cost_bps: fixed_bps,
        floor_bps,
        statement: format!(
            "STRUCTURALLY UNPROFITABLE, known before replay: one rung's gross is its {} bps \
             spacing, and one clip-sized round trip at the anchor state costs {venue_bps} bps \
             inside the venue plus {fixed_bps} bps of declared fixed cost — {floor_bps} bps in \
             all. Every completed round trip of this cell loses at least the difference on any \
             tape; the row is replayed so the surface shows the loss instead of a blank.",
            spec.spacing_bps
        ),
    })
}

// --- surfaces -----------------------------------------------------------------------------------

fn surface(
    window: WindowLabel,
    events: &[GridTapeEvent],
    refused_frames: u32,
    cells: &[GridCellSpec],
    declaration: &GridSweepDeclaration,
    rates: &HaircutRates,
) -> GridSurface {
    let anchor_statement = events.first().map_or_else(
        || "this window holds no evaluable event, so no ladder could anchor".to_owned(),
        |event| {
            format!(
                "every cell of this surface is anchored at the window's first evaluable event \
                 (ordinal {}, reserves {} / {}), and the floor flags are computed at that state",
                event.ordinal, event.state.effective_quote_atoms, event.state.base_atoms
            )
        },
    );
    let mut results: Vec<GridCellResult> = cells
        .iter()
        .map(|spec| {
            let below_floor = events
                .first()
                .and_then(|event| floor_flag(spec, &event.state, &declaration.costs));
            let run = run_grid(events, spec, &declaration.costs);
            let rungs = u128::from(spec.half_band_bps / spec.spacing_bps.max(1)).max(1);
            let committed = spec.clip_quote_atoms.saturating_mul(2 * rungs);
            let full_hold = run_hold(events, committed, committed, &declaration.costs);
            let half_hold = run_hold(
                events,
                spec.clip_quote_atoms.saturating_mul(rungs),
                committed,
                &declaration.costs,
            );
            let haircut = run.as_ref().ok().map(|outcome| haircut_for(outcome, rates));
            let net = run.as_ref().ok().map(|outcome| outcome.net_of_all_in_cost_bps);
            let excess = |hold: &Result<HoldOutcome, String>| {
                match (net, hold.as_ref().ok()) {
                    (Some(net), Some(hold)) => net.checked_sub(hold.net_of_all_in_cost_bps),
                    _ => None,
                }
            };
            let excess_full = excess(&full_hold);
            let excess_half = excess(&half_hold);
            let adverse = haircut
                .as_ref()
                .map(|haircut| i128::try_from(haircut.adverse_bps).unwrap_or(i128::MAX));
            let beats = |excess: Option<i128>| {
                matches!((excess, adverse), (Some(excess), Some(bound)) if excess > bound)
            };
            let beats_full = beats(excess_full);
            let beats_half = beats(excess_half);
            let beats_nothing = matches!((net, adverse), (Some(net), Some(bound)) if net > bound);
            let verdict = verdict(
                net,
                excess_full,
                excess_half,
                adverse,
                beats_full,
                beats_half,
                beats_nothing,
                below_floor.as_ref(),
                &run,
            );
            GridCellResult {
                spec: *spec,
                name: spec.name(),
                below_floor,
                run,
                full_hold,
                half_hold,
                excess_over_full_hold_bps: excess_full,
                excess_over_half_hold_bps: excess_half,
                haircut,
                beats_full_hold_outside_adverse: beats_full,
                beats_half_hold_outside_adverse: beats_half,
                beats_doing_nothing_outside_adverse: beats_nothing,
                verdict,
                behaviour_class: 0,
            }
        })
        .collect();
    let classes = assign_classes(&mut results);
    let label = match window {
        WindowLabel::HeldOutWindow => "HELD OUT for the one pre-named choice only; reading this \
                                       surface and preferring a different cell is fitting on the \
                                       held-out window"
            .to_owned(),
        WindowLabel::FullTape | WindowLabel::FirstWindow => {
            format!("IN-SAMPLE. {ONE_TAPE_FITS_NOTHING}")
        }
    };
    GridSurface {
        window,
        window_start_unix_ms: events.first().map_or(0, |event| event.event_unix_ms),
        window_end_unix_ms: events.last().map_or(0, |event| event.event_unix_ms),
        evaluable_events: count(events.len()),
        refused_frames,
        anchor_statement,
        cells: results,
        classes,
        label,
    }
}

#[allow(clippy::too_many_arguments)] // Every input of one verdict, named.
fn verdict(
    net: Option<i128>,
    excess_full: Option<i128>,
    excess_half: Option<i128>,
    adverse: Option<i128>,
    beats_full: bool,
    beats_half: bool,
    beats_nothing: bool,
    below_floor: Option<&FloorFlag>,
    run: &Result<GridRunOutcome, String>,
) -> String {
    let Err(reason) = run else {
        let (Some(net), Some(excess_full), Some(excess_half), Some(adverse)) =
            (net, excess_full, excess_half, adverse)
        else {
            return "a baseline could not be walked on this window, so no comparison exists to \
                    state"
                .to_owned();
        };
        let floor = below_floor.map_or(String::new(), |flag| {
            format!(
                " Flagged before replay: spacing at or under the {} bps structural floor.",
                flag.floor_bps
            )
        });
        return format!(
            "net {net} bps of committed capital. Versus buy-and-hold of the same capital: \
             {excess_full} bps ({}); versus its own initial inventory left untouched: \
             {excess_half} bps ({}); versus doing nothing: {} its own {adverse} bps adverse-draw \
             haircut. A margin inside the haircut is not a result.{floor}",
            if beats_full {
                "outside the adverse haircut"
            } else {
                "NOT outside the adverse haircut"
            },
            if beats_half {
                "outside the adverse haircut"
            } else {
                "NOT outside the adverse haircut"
            },
            if beats_nothing {
                "clears"
            } else {
                "does NOT clear"
            },
        );
    };
    format!("this cell did not run on this window: {reason}")
}

/// What makes two cells the same behaviour on one window: the same fills, to the atom.
type FillKey = Vec<(u64, &'static str, u32, u128, u128)>;

fn assign_classes(results: &mut [GridCellResult]) -> Vec<BehaviourClass> {
    let key = |result: &GridCellResult| -> Option<FillKey> {
        result.run.as_ref().ok().map(|outcome| {
            outcome
                .fills
                .iter()
                .map(|fill| {
                    (
                        fill.event_ordinal,
                        fill.kind.label(),
                        fill.rungs,
                        fill.quote_atoms,
                        fill.base_atoms,
                    )
                })
                .collect()
        })
    };
    let mut groups: Vec<(Option<FillKey>, Vec<usize>)> = Vec::new();
    for (index, result) in results.iter().enumerate() {
        let this = key(result);
        if let Some((_, members)) = groups
            .iter_mut()
            .find(|(held, _)| this.is_some() && *held == this)
        {
            members.push(index);
        } else {
            groups.push((this, vec![index]));
        }
    }
    let mut classes = Vec::new();
    for (class_index, (_, members)) in groups.iter().enumerate() {
        let class = u32::try_from(class_index).unwrap_or(u32::MAX);
        for &member in members {
            results[member].behaviour_class = class;
        }
        if members.len() > 1 {
            let names: Vec<String> = members
                .iter()
                .map(|&member| results[member].name.clone())
                .collect();
            classes.push(BehaviourClass {
                class,
                names: names.clone(),
                net_of_all_in_cost_bps: results[members[0]]
                    .run
                    .as_ref()
                    .ok()
                    .map(|outcome| outcome.net_of_all_in_cost_bps),
                statement: format!(
                    "{} declared cells produced byte-identical fills on this window — the same \
                     walks at the same events for the same atoms. Whatever separates their \
                     parameters is finer than this tape's own price moves between events, so \
                     these rows are ONE behaviour written down {} times, not {} results.",
                    names.len(),
                    names.len(),
                    names.len()
                ),
            });
        }
    }
    classes
}

// --- selection and headline ---------------------------------------------------------------------

fn score(result: &GridCellResult) -> Option<i128> {
    let net = result.run.as_ref().ok()?.net_of_all_in_cost_bps;
    let adverse = i128::try_from(result.haircut.as_ref()?.adverse_bps).ok()?;
    net.checked_sub(adverse)
}

#[allow(clippy::too_many_lines)] // One report, stating both windows side by side.
fn held_out_report(first: &GridSurface, held_out: &GridSurface) -> HeldOutReport {
    let mut best: Option<(usize, i128)> = None;
    for (index, result) in first.cells.iter().enumerate() {
        let Some(candidate) = score(result) else {
            continue;
        };
        let better = match best {
            None => true,
            Some((held_index, held_score)) => {
                let held = &first.cells[held_index];
                candidate > held_score
                    || (candidate == held_score
                        && (
                            result.spec.spacing_bps,
                            result.spec.half_band_bps,
                            result.spec.clip_quote_atoms,
                        ) > (
                            held.spec.spacing_bps,
                            held.spec.half_band_bps,
                            held.spec.clip_quote_atoms,
                        ))
            }
        };
        if better {
            best = Some((index, candidate));
        }
    }
    let Some((chosen_index, chosen_score)) = best else {
        return HeldOutReport {
            selection_rule: SELECTION_RULE_VERBATIM.to_owned(),
            chosen_cell: None,
            first_window_net_bps: None,
            first_window_score_bps: None,
            first_window_full_hold_bps: None,
            held_out_net_bps: None,
            held_out_full_hold_bps: None,
            held_out_half_hold_bps: None,
            statement: "no cell completed a run on the first window, so nothing was chosen and \
                        nothing is claimed out of window"
                .to_owned(),
        };
    };
    let chosen = &first.cells[chosen_index];
    let first_net = chosen
        .run
        .as_ref()
        .ok()
        .map(|outcome| outcome.net_of_all_in_cost_bps);
    let first_full = chosen
        .full_hold
        .as_ref()
        .ok()
        .map(|hold| hold.net_of_all_in_cost_bps);
    let held_row = held_out
        .cells
        .iter()
        .find(|result| result.name == chosen.name);
    let held_net = held_row
        .and_then(|row| row.run.as_ref().ok())
        .map(|outcome| outcome.net_of_all_in_cost_bps);
    let held_full = held_row
        .and_then(|row| row.full_hold.as_ref().ok())
        .map(|hold| hold.net_of_all_in_cost_bps);
    let held_half = held_row
        .and_then(|row| row.half_hold.as_ref().ok())
        .map(|hold| hold.net_of_all_in_cost_bps);
    let show =
        |value: Option<i128>| value.map_or_else(|| "unwalkable".to_owned(), |bps| bps.to_string());
    let statement = match (first_net, held_net) {
        (Some(first_net), Some(held_net)) => format!(
            "the first window chose {} (in-sample net {first_net} bps, score {chosen_score} bps \
             after its adverse haircut); on the held-out window the SAME cell, fresh-anchored, \
             produced {held_net} bps against a buy-and-hold of {} bps there. THE REGIME IS THE \
             EXHIBIT: buy-and-hold made {} bps on the window the parameters were chosen on and \
             {} bps on the window that judged them — a rule fitted to the first regime was \
             fitted to a market that had already stopped existing. The in-sample number is what \
             fitting looks like; the held-out number is the only one with any claim on the \
             future, and it is one window of one tape of one coin.",
            chosen.name,
            show(held_full),
            show(first_full),
            show(held_full),
        ),
        (Some(first_net), None) => format!(
            "the first window chose {} (in-sample net {first_net} bps), and the held-out window \
             could not run it — so this panel makes NO out-of-window claim at all",
            chosen.name
        ),
        _ => "the chosen cell has no stated net, so nothing is claimed".to_owned(),
    };
    HeldOutReport {
        selection_rule: SELECTION_RULE_VERBATIM.to_owned(),
        chosen_cell: Some(chosen.name.clone()),
        first_window_net_bps: first_net,
        first_window_score_bps: Some(chosen_score),
        first_window_full_hold_bps: first_full,
        held_out_net_bps: held_net,
        held_out_full_hold_bps: held_full,
        held_out_half_hold_bps: held_half,
        statement,
    }
}

fn headline(full: &GridSurface, report: &HeldOutReport, cell_count: usize) -> String {
    let ran = full
        .cells
        .iter()
        .filter(|result| result.run.is_ok())
        .count();
    let flagged = full
        .cells
        .iter()
        .filter(|result| result.below_floor.is_some())
        .count();
    let distinct_behaviours = full
        .cells
        .iter()
        .map(|result| result.behaviour_class)
        .collect::<std::collections::BTreeSet<_>>()
        .len();
    let survivors: Vec<&str> = full
        .cells
        .iter()
        .filter(|result| {
            result.beats_full_hold_outside_adverse && result.beats_doing_nothing_outside_adverse
        })
        .map(|result| result.name.as_str())
        .collect();
    let survivors_sentence = if survivors.is_empty() {
        "No cell beat buy-and-hold of its own committed capital outside its adverse-draw \
         haircut on the full tape."
            .to_owned()
    } else {
        format!(
            "{} of {} cells beat buy-and-hold outside their adverse-draw haircut on the full \
             tape ({}) — an IN-SAMPLE fact about one tape.",
            survivors.len(),
            cell_count,
            survivors.join(", ")
        )
    };
    format!(
        "{cell_count} declared cells; {ran} ran on the full tape; {flagged} were flagged \
         structurally unprofitable at the anchor state before any replay; the tape could only \
         tell {distinct_behaviours} behaviours apart. {survivors_sentence} HELD OUT: {} \
         {ONE_TAPE_FITS_NOTHING}",
        report.statement
    )
}

// --- rendering ----------------------------------------------------------------------------------

fn flag(value: bool) -> String {
    quoted(if value { "true" } else { "false" })
}

fn optional_bps(value: Option<i128>) -> String {
    value.map_or_else(|| quoted("absent"), |bps| integer(&bps))
}

impl GridSweepPanelV1 {
    /// Renders the panel as deterministic JSON, every integer a string.
    #[must_use]
    pub fn render_json(&self) -> String {
        object(&[
            ("contract", quoted(GRID_PANEL_CONTRACT)),
            ("schemaVersion", quoted("1")),
            ("authority", quoted(GRID_AUTHORITY)),
            ("notABacktest", quoted(NOT_A_BACKTEST)),
            ("oneTapeFitsNothing", quoted(ONE_TAPE_FITS_NOTHING)),
            ("headline", quoted(&self.headline)),
            ("panelId", quoted(&self.panel_id)),
            ("mint", quoted(&self.mint)),
            (
                "venue",
                object(&[
                    ("kind", quoted(self.venue.venue.label())),
                    ("account", quoted(&self.venue.venue_account)),
                    ("binding", quoted(&self.venue.binding)),
                ]),
            ),
            (
                "declaration",
                object(&[
                    (
                        "operatorWordsVerbatim",
                        quoted(&self.operator_words_verbatim),
                    ),
                    ("declaredBy", quoted(&self.declared_by)),
                    (
                        "rulesDeclaredAtUnixMs",
                        integer(&self.rules_declared_at_unix_ms),
                    ),
                    ("rulesVerbatim", quoted(GRID_RULES_VERBATIM)),
                    ("selectionRuleVerbatim", quoted(SELECTION_RULE_VERBATIM)),
                    ("rulesAreNotBlind", quoted(RULES_ARE_NOT_BLIND)),
                    (
                        "whatWasKnownAboutThisTapeBeforeDeclaring",
                        quoted(&self.what_was_known_about_this_tape),
                    ),
                    ("isASweep", quoted("always: the sweep is the interface")),
                    ("costProvenance", quoted(&self.costs.provenance)),
                ]),
            ),
            ("axes", render_axes(&self.axes)),
            ("tape", render_tape(&self.tape)),
            ("coverage", render_coverage(&self.coverage)),
            (
                "twoSourceReconciliation",
                self.reconciliation.as_ref().map_or_else(
                    || quoted("absent: only one recording exists"),
                    render_reconciliation,
                ),
            ),
            (
                "statedButNotInTheTape",
                array(
                    &self
                        .stated_but_not_in_the_tape
                        .iter()
                        .map(|stated| quoted(stated))
                        .collect::<Vec<_>>(),
                ),
            ),
            (
                "timeSplit",
                object(&[
                    ("numerator", integer(&self.split_numerator)),
                    ("denominator", integer(&self.split_denominator)),
                    ("splitInstantUnixMs", integer(&self.split_instant_unix_ms)),
                    (
                        "meaning",
                        quoted(
                            "parameters are chosen on events before the split instant and the \
                             chosen cell is evaluated once on events at or after it; the split \
                             is a declared fraction of the tape's event-time span, never random",
                        ),
                    ),
                ]),
            ),
            ("fullTapeSurface", render_surface(&self.full)),
            ("firstWindowSurface", render_surface(&self.first)),
            ("heldOutWindowSurface", render_surface(&self.held_out)),
            ("heldOutReport", render_report(&self.held_out_report)),
            ("blindness", quoted(&self.blindness)),
            (
                "unmodeledByTheHaircut",
                array(
                    &unmodeled_by_the_haircut()
                        .iter()
                        .map(|risk| quoted(risk))
                        .collect::<Vec<_>>(),
                ),
            ),
            (
                "unmodeledRisks",
                array(
                    &unmodeled_risks()
                        .iter()
                        .map(|risk| quoted(risk))
                        .collect::<Vec<_>>(),
                ),
            ),
        ])
    }

    /// Renders the panel as the table a person reads, deterministically.
    #[must_use]
    #[allow(clippy::too_many_lines)] // One table, printed in the order it is read.
    pub fn render_text(&self) -> String {
        let mut out = String::new();
        let _ = writeln!(out, "{GRID_PANEL_CONTRACT}  {}", self.panel_id);
        let _ = writeln!(out, "mint     {}", self.mint);
        let _ = writeln!(
            out,
            "venue    {} {}",
            self.venue.venue.label(),
            self.venue.venue_account
        );
        let _ = writeln!(
            out,
            "tape     {} frames ({} evaluable, {} refused) over {} ms; event gaps median {} / \
             p90 {} / max {} ms; availability delay median {} / p90 {} / max {} ms",
            self.tape.frame_count,
            self.tape.evaluable_count,
            self.tape.refused_count,
            self.tape.span_ms,
            self.tape.median_event_gap_ms,
            self.tape.p90_event_gap_ms,
            self.tape.largest_event_gap_ms,
            self.tape.median_availability_delay_ms,
            self.tape.p90_availability_delay_ms,
            self.tape.largest_availability_delay_ms
        );
        let _ = writeln!(out, "digest   {}", self.tape.digest_sha256);
        let _ = writeln!(
            out,
            "drift    over {} ms windows: median {} bps, p90 {} bps, worst {} bps ({} windows)",
            self.tape.drift.window_ms,
            self.tape.drift.median_abs_bps,
            self.tape.drift.p90_abs_bps,
            self.tape.drift.max_abs_bps,
            self.tape.drift.windows_measured
        );
        let _ = writeln!(out, "steps    {}", self.tape.granularity_statement);
        let _ = writeln!(
            out,
            "coverage {} pages read, {} duplicate events dropped, {} provable gaps",
            self.coverage.pages_read,
            self.coverage.duplicates_dropped,
            self.coverage.gaps.len()
        );
        for gap in &self.coverage.gaps {
            let _ = writeln!(out, "gap      {gap}");
        }
        if let Some(reconciliation) = &self.reconciliation {
            let _ = writeln!(
                out,
                "two-src  {} matched by signature, {} socket-only, {} polled-only, {} base-leg \
                 disagreements :: {}",
                reconciliation.matched_by_signature,
                reconciliation.socket_only,
                reconciliation.polled_only,
                reconciliation.base_leg_disagreements,
                reconciliation.statement
            );
        }
        let _ = writeln!(
            out,
            "axes     spacing {:?} bps :: {}",
            self.axes.spacings_bps, self.axes.spacing_reason
        );
        let _ = writeln!(
            out,
            "         half-band {:?} bps :: {}",
            self.axes.half_bands_bps, self.axes.band_reason
        );
        let _ = writeln!(
            out,
            "         clip {:?} quote atoms :: {}",
            self.axes.clips_quote_atoms, self.axes.clip_reason
        );
        let _ = writeln!(
            out,
            "split    first {}/{} of the event-time span chooses; the rest judges (split instant \
             {} ms)",
            self.split_numerator, self.split_denominator, self.split_instant_unix_ms
        );
        for surface in [&self.full, &self.first, &self.held_out] {
            let _ = writeln!(out);
            let _ = writeln!(
                out,
                "== {} :: {} events, {} refused frames :: {}",
                surface.window.label(),
                surface.evaluable_events,
                surface.refused_frames,
                surface.label
            );
            let _ = writeln!(out, "   {}", surface.anchor_statement);
            let _ = writeln!(
                out,
                "   {:<22} {:>5} {:>9} {:>9} {:>9} {:>9} {:>6} {:>6} {:>5} {:>6} {:>5} {:>5}  \
                 flags",
                "cell",
                "rungs",
                "net bps",
                "vs hold",
                "vs half",
                "adverse",
                "sells",
                "buys",
                "tx",
                "tok%",
                "class",
                "floor"
            );
            for result in &surface.cells {
                let _ = writeln!(out, "   {}", render_cell_row(result));
            }
            for class in &surface.classes {
                let _ = writeln!(
                    out,
                    "   SAME  {} :: {}",
                    class.names.join(" = "),
                    class.statement
                );
            }
        }
        let _ = writeln!(out);
        let _ = writeln!(out, "CHOSEN    {}", self.held_out_report.statement);
        let _ = writeln!(out, "HEADLINE  {}", self.headline);
        let _ = writeln!(out);
        let _ = writeln!(out, "rules         {GRID_RULES_VERBATIM}");
        let _ = writeln!(out, "selection     {SELECTION_RULE_VERBATIM}");
        let _ = writeln!(out, "not blind     {RULES_ARE_NOT_BLIND}");
        let _ = writeln!(out, "known first   {}", self.what_was_known_about_this_tape);
        for stated in &self.stated_but_not_in_the_tape {
            let _ = writeln!(out, "declared      {stated}");
        }
        let _ = writeln!(out, "blindness     {}", self.blindness);
        let _ = writeln!(out, "not a backtest {NOT_A_BACKTEST}");
        for risk in unmodeled_by_the_haircut() {
            let _ = writeln!(out, "unmodeled     {risk}");
        }
        out
    }
}

fn render_cell_row(result: &GridCellResult) -> String {
    let (net, sells, buys, transactions) = result.run.as_ref().map_or_else(
        |_| ("absent".to_owned(), 0, 0, 0),
        |outcome| {
            (
                outcome.net_of_all_in_cost_bps.to_string(),
                outcome.rung_sells,
                outcome.rung_buys,
                outcome.transactions,
            )
        },
    );
    // Share of committed capital that came back only as terminal token value: how much of the
    // window's end was inventory rather than cash. The collapse exhibit, one number per row.
    let terminal_tokens = result.run.as_ref().map_or_else(
        |_| "n/a".to_owned(),
        |outcome| {
            outcome
                .terminal_base_value_quote_atoms
                .checked_mul(100)
                .map_or_else(
                    || "n/a".to_owned(),
                    |scaled| (scaled / outcome.committed_quote_atoms.max(1)).to_string(),
                )
        },
    );
    let rungs = result
        .run
        .as_ref()
        .map_or(0, |outcome| outcome.rungs_per_side);
    let show = |value: Option<i128>| value.map_or_else(|| "n/a".to_owned(), |bps| bps.to_string());
    let adverse = result.haircut.as_ref().map_or_else(
        || "n/a".to_owned(),
        |haircut| haircut.adverse_bps.to_string(),
    );
    let mut flags = String::new();
    if result.beats_full_hold_outside_adverse {
        flags.push_str("beats-hold ");
    }
    if result.beats_doing_nothing_outside_adverse {
        flags.push_str("beats-nothing ");
    }
    if let Ok(outcome) = &result.run {
        if outcome.cash_starved_rungs > 0 {
            let _ = write!(flags, "starved:{} ", outcome.cash_starved_rungs);
        }
        if outcome.refused_walks > 0 {
            let _ = write!(flags, "refused:{} ", outcome.refused_walks);
        }
    }
    format!(
        "{:<22} {:>5} {:>9} {:>9} {:>9} {:>9} {:>6} {:>6} {:>5} {:>6} {:>5} {:>5}  {}",
        result.name,
        rungs,
        net,
        show(result.excess_over_full_hold_bps),
        show(result.excess_over_half_hold_bps),
        adverse,
        sells,
        buys,
        transactions,
        terminal_tokens,
        result.behaviour_class,
        if result.below_floor.is_some() {
            "UNDER"
        } else {
            "clear"
        },
        flags.trim_end()
    )
}

fn render_axes(axes: &GridSweepAxes) -> String {
    object(&[
        (
            "spacingsBps",
            array(&axes.spacings_bps.iter().map(integer).collect::<Vec<_>>()),
        ),
        ("spacingReason", quoted(&axes.spacing_reason)),
        (
            "halfBandsBps",
            array(&axes.half_bands_bps.iter().map(integer).collect::<Vec<_>>()),
        ),
        ("bandReason", quoted(&axes.band_reason)),
        (
            "clipsQuoteAtoms",
            array(
                &axes
                    .clips_quote_atoms
                    .iter()
                    .map(integer)
                    .collect::<Vec<_>>(),
            ),
        ),
        ("clipReason", quoted(&axes.clip_reason)),
    ])
}

fn render_coverage(coverage: &TapeCoverage) -> String {
    object(&[
        ("pagesRead", integer(&coverage.pages_read)),
        ("duplicatesDropped", integer(&coverage.duplicates_dropped)),
        (
            "gaps",
            array(
                &coverage
                    .gaps
                    .iter()
                    .map(|gap| quoted(gap))
                    .collect::<Vec<_>>(),
            ),
        ),
        (
            "availabilityStatement",
            quoted(&coverage.availability_statement),
        ),
    ])
}

fn render_reconciliation(reconciliation: &TwoSourceReconciliationV1) -> String {
    object(&[
        ("socketTapeId", quoted(&reconciliation.socket_tape_id)),
        ("polledTapeId", quoted(&reconciliation.polled_tape_id)),
        (
            "overlapStartUnixMs",
            integer(&reconciliation.overlap_start_unix_ms),
        ),
        (
            "overlapEndUnixMs",
            integer(&reconciliation.overlap_end_unix_ms),
        ),
        (
            "matchedBySignature",
            integer(&reconciliation.matched_by_signature),
        ),
        ("socketOnly", integer(&reconciliation.socket_only)),
        ("polledOnly", integer(&reconciliation.polled_only)),
        (
            "baseLegDisagreements",
            integer(&reconciliation.base_leg_disagreements),
        ),
        ("statement", quoted(&reconciliation.statement)),
    ])
}

fn render_tape(tape: &GridTapeSummary) -> String {
    object(&[
        ("tapeId", quoted(&tape.tape_id)),
        ("provenance", quoted(&tape.provenance)),
        ("digestSha256", quoted(&tape.digest_sha256)),
        ("frameCount", integer(&tape.frame_count)),
        ("evaluableCount", integer(&tape.evaluable_count)),
        ("refusedCount", integer(&tape.refused_count)),
        ("firstEventUnixMs", integer(&tape.first_event_unix_ms)),
        ("lastEventUnixMs", integer(&tape.last_event_unix_ms)),
        ("spanMs", integer(&tape.span_ms)),
        ("medianEventGapMs", integer(&tape.median_event_gap_ms)),
        ("p90EventGapMs", integer(&tape.p90_event_gap_ms)),
        ("largestEventGapMs", integer(&tape.largest_event_gap_ms)),
        (
            "medianAvailabilityDelayMs",
            integer(&tape.median_availability_delay_ms),
        ),
        (
            "p90AvailabilityDelayMs",
            integer(&tape.p90_availability_delay_ms),
        ),
        (
            "largestAvailabilityDelayMs",
            integer(&tape.largest_availability_delay_ms),
        ),
        (
            "drift",
            object(&[
                ("windowMs", integer(&tape.drift.window_ms)),
                ("windowsMeasured", integer(&tape.drift.windows_measured)),
                (
                    "windowsUnmeasurable",
                    integer(&tape.drift.windows_unmeasurable),
                ),
                ("medianAbsBps", integer(&tape.drift.median_abs_bps)),
                ("p90AbsBps", integer(&tape.drift.p90_abs_bps)),
                ("maxAbsBps", integer(&tape.drift.max_abs_bps)),
            ]),
        ),
        (
            "priceGranularity",
            object(&[
                (
                    "distinctMarginalPrices",
                    integer(&tape.distinct_marginal_prices),
                ),
                ("nonzeroMoves", integer(&tape.nonzero_moves)),
                ("minNonzeroMoveBps", integer(&tape.min_nonzero_move_bps)),
                (
                    "medianNonzeroMoveBps",
                    integer(&tape.median_nonzero_move_bps),
                ),
                ("statement", quoted(&tape.granularity_statement)),
            ]),
        ),
    ])
}

fn render_surface(surface: &GridSurface) -> String {
    object(&[
        ("window", quoted(surface.window.label())),
        ("label", quoted(&surface.label)),
        ("windowStartUnixMs", integer(&surface.window_start_unix_ms)),
        ("windowEndUnixMs", integer(&surface.window_end_unix_ms)),
        ("evaluableEvents", integer(&surface.evaluable_events)),
        ("refusedFrames", integer(&surface.refused_frames)),
        ("anchorStatement", quoted(&surface.anchor_statement)),
        (
            "cells",
            array(&surface.cells.iter().map(render_cell).collect::<Vec<_>>()),
        ),
        (
            "behaviourClasses",
            array(
                &surface
                    .classes
                    .iter()
                    .map(|class| {
                        object(&[
                            ("class", integer(&class.class)),
                            (
                                "names",
                                array(
                                    &class
                                        .names
                                        .iter()
                                        .map(|name| quoted(name))
                                        .collect::<Vec<_>>(),
                                ),
                            ),
                            (
                                "netOfAllInCostBps",
                                optional_bps(class.net_of_all_in_cost_bps),
                            ),
                            ("statement", quoted(&class.statement)),
                        ])
                    })
                    .collect::<Vec<_>>(),
            ),
        ),
    ])
}

#[allow(clippy::too_many_lines)] // One cell's whole row, rendered in the order it is read.
fn render_cell(result: &GridCellResult) -> String {
    let run = match &result.run {
        Err(reason) => object(&[
            ("status", quoted("did_not_run")),
            ("because", quoted(reason)),
        ]),
        Ok(outcome) => object(&[
            ("status", quoted("ran")),
            ("rungsPerSide", integer(&outcome.rungs_per_side)),
            (
                "committedQuoteAtoms",
                integer(&outcome.committed_quote_atoms),
            ),
            ("transactions", integer(&outcome.transactions)),
            ("rungSells", integer(&outcome.rung_sells)),
            ("rungBuys", integer(&outcome.rung_buys)),
            ("cashStarvedRungs", integer(&outcome.cash_starved_rungs)),
            ("refusedWalks", integer(&outcome.refused_walks)),
            ("unsoldBaseAtoms", integer(&outcome.unsold_base_atoms)),
            (
                "terminalCashQuoteAtoms",
                integer(&outcome.terminal_cash_quote_atoms),
            ),
            (
                "terminalBaseValueQuoteAtoms",
                integer(&outcome.terminal_base_value_quote_atoms),
            ),
            (
                "terminalInventoryMeaning",
                quoted(
                    "how the window actually ended: cash still held, beside what liquidating \
                     every remaining token returned at the last retained state. A ladder that \
                     rode a collapse ends mostly in the second number, and unsold dust the \
                     venue refused to quote is valued at zero.",
                ),
            ),
            ("endQuoteAtoms", integer(&outcome.end_quote_atoms)),
            ("fixedCostAtoms", integer(&outcome.fixed_cost_atoms)),
            ("netQuoteAtoms", integer(&outcome.net_quote_atoms)),
            (
                "netOfAllInCostBps",
                integer(&outcome.net_of_all_in_cost_bps),
            ),
            ("venueOnlyNetBps", integer(&outcome.venue_only_net_bps)),
            (
                "fills",
                array(
                    &outcome
                        .fills
                        .iter()
                        .map(|fill| {
                            object(&[
                                ("eventOrdinal", integer(&fill.event_ordinal)),
                                ("kind", quoted(fill.kind.label())),
                                ("rungs", integer(&fill.rungs)),
                                ("quoteAtoms", integer(&fill.quote_atoms)),
                                ("baseAtoms", integer(&fill.base_atoms)),
                                ("availabilityDelayMs", integer(&fill.availability_delay_ms)),
                            ])
                        })
                        .collect::<Vec<_>>(),
                ),
            ),
        ]),
    };
    let hold = |held: &Result<HoldOutcome, String>| match held {
        Err(reason) => object(&[
            ("status", quoted("unwalkable")),
            ("because", quoted(reason)),
        ]),
        Ok(outcome) => object(&[
            ("status", quoted("walked")),
            ("deployedQuoteAtoms", integer(&outcome.deployed_quote_atoms)),
            (
                "committedQuoteAtoms",
                integer(&outcome.committed_quote_atoms),
            ),
            ("exitQuoteAtoms", integer(&outcome.exit_quote_atoms)),
            ("fixedCostAtoms", integer(&outcome.fixed_cost_atoms)),
            (
                "netOfAllInCostBps",
                integer(&outcome.net_of_all_in_cost_bps),
            ),
        ]),
    };
    object(&[
        ("name", quoted(&result.name)),
        ("spacingBps", integer(&result.spec.spacing_bps)),
        ("halfBandBps", integer(&result.spec.half_band_bps)),
        ("clipQuoteAtoms", integer(&result.spec.clip_quote_atoms)),
        (
            "belowVenueFloor",
            result.below_floor.as_ref().map_or_else(
                || quoted("no: spacing clears the structural floor at the anchor state"),
                |flag| {
                    object(&[
                        ("venueRoundTripBps", integer(&flag.venue_round_trip_bps)),
                        ("fixedCostBps", integer(&flag.fixed_cost_bps)),
                        ("floorBps", integer(&flag.floor_bps)),
                        ("statement", quoted(&flag.statement)),
                    ])
                },
            ),
        ),
        ("run", run),
        ("baselineBuyHoldFull", hold(&result.full_hold)),
        ("baselineInitialInventoryUntouched", hold(&result.half_hold)),
        (
            "excessOverFullHoldBps",
            optional_bps(result.excess_over_full_hold_bps),
        ),
        (
            "excessOverHalfHoldBps",
            optional_bps(result.excess_over_half_hold_bps),
        ),
        (
            "haircut",
            result.haircut.as_ref().map_or_else(
                || quoted("absent: the cell did not run"),
                |haircut| {
                    object(&[
                        (
                            "centralRateBpsPerWindow",
                            integer(&haircut.central_rate_bps_per_window),
                        ),
                        (
                            "adverseRateBpsPerWindow",
                            integer(&haircut.adverse_rate_bps_per_window),
                        ),
                        ("rateSource", quoted(&haircut.rate_source)),
                        (
                            "availabilityExposureMs",
                            integer(&haircut.availability_exposure_ms),
                        ),
                        ("landingExposureMs", integer(&haircut.landing_exposure_ms)),
                        ("totalExposureMs", integer(&haircut.total_exposure_ms)),
                        ("centralBps", integer(&haircut.central_bps)),
                        ("adverseBps", integer(&haircut.adverse_bps)),
                        ("statement", quoted(&haircut.statement)),
                    ])
                },
            ),
        ),
        (
            "beatsFullHoldOutsideAdverse",
            flag(result.beats_full_hold_outside_adverse),
        ),
        (
            "beatsHalfHoldOutsideAdverse",
            flag(result.beats_half_hold_outside_adverse),
        ),
        (
            "beatsDoingNothingOutsideAdverse",
            flag(result.beats_doing_nothing_outside_adverse),
        ),
        ("verdict", quoted(&result.verdict)),
        ("behaviourClass", integer(&result.behaviour_class)),
    ])
}

fn render_report(report: &HeldOutReport) -> String {
    object(&[
        ("selectionRule", quoted(&report.selection_rule)),
        (
            "chosenCell",
            report
                .chosen_cell
                .as_ref()
                .map_or_else(|| quoted("none"), |name| quoted(name)),
        ),
        (
            "firstWindowNetBps",
            optional_bps(report.first_window_net_bps),
        ),
        (
            "firstWindowScoreBps",
            optional_bps(report.first_window_score_bps),
        ),
        (
            "firstWindowFullHoldBps",
            optional_bps(report.first_window_full_hold_bps),
        ),
        ("heldOutNetBps", optional_bps(report.held_out_net_bps)),
        (
            "heldOutFullHoldBps",
            optional_bps(report.held_out_full_hold_bps),
        ),
        (
            "heldOutHalfHoldBps",
            optional_bps(report.held_out_half_hold_bps),
        ),
        ("statement", quoted(&report.statement)),
    ])
}

#[cfg(test)]
mod tests {
    use joshi_market_math::{
        fee::{CreatorFee, FeeBps, FeeSchedule},
        stack::VenueFormula,
    };

    use super::*;
    use crate::readout::VenueKind;

    const OPEN_MS: i64 = 1_787_600_000_000;
    const STEP_MS: i64 = 2_000;

    fn schedule() -> FeeSchedule {
        FeeSchedule {
            lp: FeeBps::new(20).expect("lp"),
            protocol: FeeBps::new(5).expect("protocol"),
            creator: CreatorFee::Charged(FeeBps::new(5).expect("creator")),
        }
    }

    fn pool() -> ExactCurveState {
        ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms: 297_431_224_690_113,
            effective_quote_atoms: 87_554_112_907,
            schedule: schedule(),
        }
    }

    /// A tape that chops: other participants buy the price up several rungs, sell it back down
    /// through them, and repeat, every state the deployed arithmetic's own successor.
    fn chop_frames(cycles: usize, legs_per_side: usize) -> Vec<GridFrame> {
        let mut state = pool();
        let mut frames = Vec::new();
        let mut ordinal = 0_u64;
        let mut push = |state: ExactCurveState, ordinal: &mut u64| {
            let event_unix_ms = OPEN_MS + i64::try_from(*ordinal).expect("ordinal") * STEP_MS;
            frames.push(GridFrame::Event(GridTapeEvent {
                ordinal: *ordinal,
                event_unix_ms,
                available_unix_ms: event_unix_ms + 40,
                state,
            }));
            *ordinal += 1;
        };
        push(state, &mut ordinal);
        for _ in 0..cycles {
            for _ in 0..legs_per_side {
                state = state
                    .buy_with_quote_in(state.effective_quote_atoms / 90)
                    .expect("buy walks")
                    .next;
                push(state, &mut ordinal);
            }
            for _ in 0..legs_per_side {
                state = state
                    .sell_base_in(state.base_atoms / 88)
                    .expect("sell walks")
                    .next;
                push(state, &mut ordinal);
            }
        }
        frames
    }

    fn axes() -> GridSweepAxes {
        GridSweepAxes {
            spacings_bps: vec![50, 100, 105, 400],
            spacing_reason: "spans the venue floor: below it, at it, and multiples above"
                .to_owned(),
            half_bands_bps: vec![600],
            band_reason: "the declared prior chop band".to_owned(),
            clips_quote_atoms: vec![250_000_000],
            clip_reason: "the measured hurdle clip".to_owned(),
        }
    }

    fn declaration() -> GridSweepDeclaration {
        GridSweepDeclaration {
            panel_id: "panel".to_owned(),
            tape_id: "tape".to_owned(),
            tape_provenance: "a synthetic tape written by this test".to_owned(),
            tape_digest_sha256: "deadbeef".to_owned(),
            mint: "mint".to_owned(),
            venue: VenueBinding {
                venue: VenueKind::PumpSwapPool,
                venue_account: "pool".to_owned(),
                binding: "synthetic".to_owned(),
            },
            hypothesis: DeclaredHypothesis {
                operator_words_verbatim: "it chops in a band".to_owned(),
                declared_by: "ember".to_owned(),
                declared_at_unix_ms: OPEN_MS + 10_000_000,
            },
            costs: DeclaredFixedCosts {
                provenance: "a landed fill".to_owned(),
                per_transaction_quote_atoms: 7_422,
                transactions: 2,
                flat_route_quote_atoms: 0,
                unrecovered_rent_quote_atoms: 0,
            },
            base_decimals: 6,
            quote_decimals: 9,
            what_was_known_about_this_tape: "every state in this tape is the deployed \
                                             arithmetic's own successor, written by this test"
                .to_owned(),
            stated_but_not_in_the_tape: vec!["the fee schedule".to_owned()],
            coverage: TapeCoverage {
                pages_read: 1,
                duplicates_dropped: 0,
                gaps: Vec::new(),
                availability_statement: "synthetic: availability is event time plus 40 ms"
                    .to_owned(),
            },
            reconciliation: None,
            split_numerator: 1,
            split_denominator: 2,
        }
    }

    fn panel() -> GridSweepPanelV1 {
        GridSweepPanelV1::build(&declaration(), &chop_frames(6, 4), &axes()).expect("builds")
    }

    #[test]
    fn a_chopping_tape_fills_rungs_in_both_directions_and_banks_the_spacing() {
        let panel = panel();
        let wide = panel
            .full
            .cells
            .iter()
            .find(|cell| cell.spec.spacing_bps == 100)
            .expect("the 100 bps cell exists");
        let run = wide.run.as_ref().expect("the cell runs");
        assert!(run.rung_sells > 0, "no rung ever sold: {run:?}");
        assert!(run.rung_buys > 0, "no rung ever bought: {run:?}");
        assert!(
            run.transactions >= 4,
            "chop should produce repeated walks: {run:?}"
        );
    }

    #[test]
    fn the_ladder_is_inventory_bounded_and_the_ledger_reconciles_to_the_atom() {
        let panel = panel();
        for cell in &panel.full.cells {
            let Ok(run) = &cell.run else { continue };
            // End cash equals committed plus net plus fixed, exactly.
            let reconciled = i128::try_from(run.end_quote_atoms).expect("cash")
                - i128::try_from(run.committed_quote_atoms).expect("committed")
                - i128::try_from(run.fixed_cost_atoms).expect("fixed");
            assert_eq!(reconciled, run.net_quote_atoms, "{}", cell.name);
            assert!(
                run.cash_starved_rungs == 0 || cell.below_floor.is_some(),
                "{} starved above the floor",
                cell.name
            );
        }
    }

    #[test]
    fn a_spacing_under_the_venue_floor_is_flagged_before_replay_and_still_replayed() {
        let panel = panel();
        let under = panel
            .full
            .cells
            .iter()
            .find(|cell| cell.spec.spacing_bps == 50)
            .expect("the 50 bps cell exists");
        let flag = under.below_floor.as_ref().expect("flagged before replay");
        assert!(u128::from(under.spec.spacing_bps) <= flag.floor_bps);
        assert!(under.run.is_ok(), "flagged cells still run");
        let clear = panel
            .full
            .cells
            .iter()
            .find(|cell| cell.spec.spacing_bps == 400)
            .expect("the 400 bps cell exists");
        assert!(
            clear.below_floor.is_none(),
            "400 bps clears a ~60 bps floor"
        );
    }

    #[test]
    fn cells_the_tape_cannot_tell_apart_collapse_into_one_stated_class() {
        let panel = panel();
        // 100 and 105 bps at the same band and clip produce the same rung count and, on a tape
        // whose legs move ~110 bps, the same fills.
        let class_of = |spacing: u32| {
            panel
                .full
                .cells
                .iter()
                .find(|cell| cell.spec.spacing_bps == spacing)
                .expect("cell exists")
                .behaviour_class
        };
        if class_of(100) == class_of(105) {
            assert!(
                panel
                    .full
                    .classes
                    .iter()
                    .any(|class| class.names.len() >= 2),
                "identical cells must be stated as one behaviour"
            );
        }
        // Whether or not these two collapsed on this tape, the mechanism must have partitioned
        // every cell into exactly one class.
        for cell in &panel.full.cells {
            assert!(
                panel
                    .full
                    .cells
                    .iter()
                    .filter(|other| other.behaviour_class == cell.behaviour_class)
                    .count()
                    >= 1
            );
        }
    }

    #[test]
    fn the_baselines_are_built_by_the_panel_and_the_ladder_is_judged_against_both() {
        let panel = panel();
        for cell in &panel.full.cells {
            if cell.run.is_ok() {
                assert!(cell.full_hold.is_ok(), "{}", cell.name);
                assert!(cell.half_hold.is_ok(), "{}", cell.name);
                assert!(cell.excess_over_full_hold_bps.is_some());
                assert!(cell.excess_over_half_hold_bps.is_some());
                assert!(cell.verdict.contains("buy-and-hold"));
            }
        }
    }

    #[test]
    fn the_held_out_report_never_states_an_in_sample_number_without_the_held_out_one() {
        let panel = panel();
        let report = &panel.held_out_report;
        assert!(report.chosen_cell.is_some());
        assert_eq!(report.selection_rule, SELECTION_RULE_VERBATIM);
        if report.first_window_net_bps.is_some() {
            assert!(
                report.held_out_net_bps.is_some()
                    || report.statement.contains("NO out-of-window claim"),
                "{}",
                report.statement
            );
        }
        assert!(panel.headline.contains("HELD OUT"));
        assert!(panel.headline.contains("ONE TAPE OF ONE COIN FITS NOTHING"));
    }

    #[test]
    fn the_split_is_the_declared_fraction_of_the_event_time_span_and_never_random() {
        let panel = panel();
        let expected = panel.tape.first_event_unix_ms + panel.tape.span_ms / 2;
        assert_eq!(panel.split_instant_unix_ms, expected);
        assert_eq!(
            panel.first.evaluable_events + panel.held_out.evaluable_events,
            panel.full.evaluable_events
        );
        assert!(panel.first.label.contains("IN-SAMPLE"));
        assert!(panel.held_out.label.contains("HELD OUT"));
    }

    #[test]
    fn the_haircut_charges_every_fill_for_its_measured_availability_delay() {
        let panel = panel();
        for cell in &panel.full.cells {
            let (Ok(run), Some(haircut)) = (&cell.run, cell.haircut.as_ref()) else {
                continue;
            };
            let expected: i64 = run
                .fills
                .iter()
                .map(|fill| fill.availability_delay_ms)
                .sum();
            assert_eq!(haircut.availability_exposure_ms, expected);
            assert_eq!(
                haircut.landing_exposure_ms,
                M0_CHAIN_TO_RECEIPT_MS * i64::from(run.transactions)
            );
            assert!(haircut.adverse_bps >= haircut.central_bps);
        }
    }

    #[test]
    fn a_panel_without_prior_knowledge_or_axis_reasons_is_refused() {
        let frames = chop_frames(2, 3);
        let mut blind = declaration();
        blind.what_was_known_about_this_tape = "  ".to_owned();
        assert_eq!(
            GridSweepPanelV1::build(&blind, &frames, &axes()),
            Err(GridError::PriorKnowledgeNotStated)
        );
        let mut unreasoned = axes();
        unreasoned.spacing_reason = String::new();
        assert_eq!(
            GridSweepPanelV1::build(&declaration(), &frames, &unreasoned),
            Err(GridError::AxisReasonNotStated)
        );
        let mut wild = axes();
        wild.half_bands_bps = vec![600, 10_000];
        assert_eq!(
            GridSweepPanelV1::build(&declaration(), &frames, &wild),
            Err(GridError::BandTooWide)
        );
        assert_eq!(
            GridSweepPanelV1::build(&declaration(), &[], &axes()),
            Err(GridError::EmptyTape)
        );
    }

    #[test]
    fn the_same_tape_and_the_same_axes_render_the_same_bytes() {
        let frames = chop_frames(4, 4);
        let first = GridSweepPanelV1::build(&declaration(), &frames, &axes()).expect("builds");
        let second = GridSweepPanelV1::build(&declaration(), &frames, &axes()).expect("builds");
        assert_eq!(first, second);
        assert_eq!(first.render_json(), second.render_json());
        assert_eq!(first.render_text(), second.render_text());
    }

    #[test]
    fn the_panel_renders_parseable_json_with_all_three_surfaces_and_the_report() {
        let panel = panel();
        let value: serde_json::Value =
            serde_json::from_str(&panel.render_json()).expect("valid JSON");
        assert_eq!(value["contract"], GRID_PANEL_CONTRACT);
        assert!(value["fullTapeSurface"]["cells"].as_array().is_some());
        assert!(
            value["firstWindowSurface"]["label"]
                .as_str()
                .expect("label")
                .contains("IN-SAMPLE")
        );
        assert!(value["heldOutReport"]["selectionRule"].as_str().is_some());
        assert_eq!(
            value["declaration"]["isASweep"],
            "always: the sweep is the interface"
        );
    }
}
