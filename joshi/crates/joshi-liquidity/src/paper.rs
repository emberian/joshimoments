//! A paper episode: one declared hypothesis, executed on declared rules, against polled states.
//!
//! Ember's loop is: she spots a coin, states a hunch in her own words, and wants the machine to
//! watch the venue and work the hunch on paper — enter on a declared trigger, exit at a declared
//! lift, stop, or clock — so the hunch can be judged later without money and without hindsight.
//! This module is that episode, as a pure state machine over states somebody else polled. It has
//! no network, and nothing in it can construct, sign, simulate, or submit anything.
//!
//! What keeps it honest, by construction rather than by policy:
//!
//! * **The hypothesis and every rule are declared before the first poll and serialized verbatim.**
//!   The desk executes; it never fits. A trigger is judged only against states observed after the
//!   declaration, and the record shows exactly which observed values satisfied it.
//! * **Every number a rule acted on is a would-quote from the deployed integer arithmetic** —
//!   [`ExactCurveState::buy_with_quote_in`] / [`ExactCurveState::sell_base_in`], the walk that
//!   reproduced six landed fills to the atom — carrying its state slot, commitment, clocks, fee
//!   tier, and the arithmetic's own name.
//! * **The would-PnL is named as arithmetic.** Its serialization leads with what it is not, and
//!   the unmodeled-risk list is emitted from a constant in this module, so no caller can trim it.
//! * **A quote that cannot be computed is a recorded refusal**, never a gap-filled number, and an
//!   episode that ends without an exit quote states that its would-PnL is absent and why.
//! * **The episode carries its own falsifiers**: the declared poll cadence, the largest observed
//!   gap between polls, and the statement that every move inside a gap — including a move through
//!   the declared stop — was invisible. An earlier paper desk armed a stop at -16.5% and "filled"
//!   at -64.7% across a 43-second observation gap; this desk writes that possibility into every
//!   episode instead of waiting to be surprised by it.

use core::fmt::Write as _;

use joshi_market_math::{
    fee::{CreatorFee, FeeBreakdown, FeeSchedule},
    quote::AtomicPrice,
    render::{array, integer, object, quoted},
    stack::{ExactCurveState, ExactRatio, PriceObject, StackRefusal},
    would_quote::{ChainSecond, ChainToReceiptAge, LocalReceipt},
};
use thiserror::Error;

use crate::{
    readout::{FeeRateSource, VenueKind},
    round_trip::DeclaredFixedCosts,
};

/// Stable contract of the rendered paper-episode artifact.
pub const PAPER_EPISODE_CONTRACT: &str = "joshi.liquidity.paper_episode.v1";

/// The only authority a paper desk holds.
pub const PAPER_EPISODE_AUTHORITY: &str = "read_only_no_execution";

/// What an episode refuses to be, stated in the artifact before any number.
pub const NOT_A_TRADING_RESULT: &str = "This episode is arithmetic about polled venue states, \
executed on rules declared before the first poll. No order existed; nothing was signed, \
submitted, filled, or could have been. The would-PnL is what the deployed integer formulas say \
those states were worth to this clip at the polled instants, minus the declared costs, and it \
models none of the listed unmodeled risks, every one of which moves the real number against the \
trade. A green would-PnL is a reason to look harder at the hypothesis, not a result.";

/// What the would-PnL is, kept as the first field of the number it describes.
pub const WOULD_PNL_IS: &str = "Arithmetic over two would-quotes and a declared cost list. Not a \
realized profit, not a backtest fill, not an expectation.";

/// The order rules are checked in at every poll. Fixed here, not configurable, so no episode can
/// quietly prefer the flattering label when two rules cross at one poll.
pub const RULE_PRIORITY: &str = "stop_loss, then take_profit, then max_hold, in that order at \
every poll; when more than one rule crosses at the same poll the earliest in this order names \
the exit";

/// The arithmetic every would-quote in an episode names as its provenance.
pub const ARITHMETIC_PROVENANCE: &str = "joshi-market-math exact stack: integer arithmetic in the \
deployed operation order (ExactCurveState::buy_with_quote_in / sell_base_in), the walk that \
reproduced six landed fills to the atom in Study M0";

/// Every risk a would-PnL does not model. Emitted from this constant at serialization, so no
/// caller can shorten the list or leave it out.
#[must_use]
pub fn unmodeled_risks() -> [&'static str; 6] {
    [
        "landing delay: a real order lands seconds after the decision state; chain-to-receipt \
         alone measured about 12 seconds at finalized commitment",
        "landing failure: the retained corpus structurally contains zero failed transactions, so \
         the landing rate is unknowable from anything this system has; a paper fill assumes every \
         transaction lands, which no venue offers",
        "competition: nothing here contends with other participants for the same move; their \
         fills would change the state before a real order reached it",
        "adverse selection between decision-state and landed-state: a measured pool drifted 9-10 \
         bps in 30 seconds, which alone can exceed a pool's whole fee floor",
        "poll blindness: the venue was sampled at the declared cadence, and every move that began \
         and completed between two polls is invisible, including a move through the declared \
         stop; a stop on this desk is a rule about observed states, not a guaranteed price",
        "priority fee and tip under contention: the declared network cost is a base fee, and a \
         contested block costs more",
    ]
}

/// The operator's hunch, in the operator's words, dated before the desk saw any state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeclaredHypothesis {
    /// Exactly as uttered. A blank here is refused: a later reader would take the blank as "there
    /// was no hypothesis", and an episode without one is not testing anything.
    pub operator_words_verbatim: String,
    pub declared_by: String,
    pub declared_at_unix_ms: i64,
}

/// When the desk enters, declared in advance.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EntryRule {
    /// Enter at the first evaluated poll.
    Immediate,
    /// Enter at the first poll whose marginal pool price sits at least `trigger_bps` under the
    /// episode's first observed marginal pool price. The reference is fixed by the first poll —
    /// never re-anchored — and the dip is floored, so a partial dip never triggers.
    MicrodipBps { trigger_bps: u32 },
    /// Enter at the first poll whose marginal pool price sits at least `trigger_bps` over the
    /// episode's first observed marginal pool price. The reference is fixed by the first poll —
    /// never re-anchored — and the rise is floored, so a partial rise never triggers. The
    /// momentum mirror of the microdip: the two differ only in trigger direction.
    BreakoutBps { trigger_bps: u32 },
}

/// When the desk exits, declared in advance. All three are always armed.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExitRules {
    /// Exit when the would-sell valuation of the held base, net of the entry cost and every
    /// declared fixed cost, reaches this many basis points of the entry cost.
    pub take_profit_net_bps: u32,
    /// Exit when that same net valuation falls to or below minus this many basis points.
    pub stop_loss_net_bps: u32,
    /// Exit at the first poll at or after this much local wall-clock time held.
    pub max_hold_ms: i64,
}

/// Every rule of one episode. Serialized verbatim into the episode so it can be judged later.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DeclaredRules {
    pub entry: EntryRule,
    /// Give up waiting for entry after this much local wall-clock time from open. Checked before
    /// the entry rule at each poll: a trigger on a poll at or after the deadline does not enter.
    pub entry_deadline_ms: i64,
    pub exit: ExitRules,
    /// The cadence the driver declared it would poll at. The falsifiers report what it measured.
    pub poll_cadence_ms: i64,
    /// Abandon the episode after this many consecutive polls that produced no evaluable state.
    pub abandon_after_consecutive_failed_polls: u32,
}

/// The venue an episode is bound to, and what binds it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VenueBinding {
    pub venue: VenueKind,
    /// Account the state is read from.
    pub venue_account: String,
    /// What binds that account to the mint, stated rather than assumed.
    pub binding: String,
}

/// The chain's clock for a polled slot, keeping three different absences apart.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ChainClock {
    /// The driver declared it would not spend a request on this slot's block time. An economy,
    /// not an absence of the chain's clock.
    NotRequested,
    /// The provider was asked and stated no block time. An absent record, never an age of zero.
    ProviderStatedNone,
    /// The feed the state came from carries no chain clock at all, for any frame. Not an economy
    /// and not a provider's silence about one slot: a structural property of the source, measured
    /// rather than assumed. A retained `PumpPortal` trade tape is the case this exists for — 0 of
    /// 1734 frames carried a timestamp, a `blockTime` or a slot — and the only time axis such a
    /// state has is the recorder's own receive instant.
    FeedStatesNoClock,
    Stated(ChainSecond),
}

/// Where and when one polled state was true, as far as the read can say.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateProvenance {
    /// Slot the provider stated it evaluated the read at.
    pub context_slot: u64,
    /// Commitment named in the request. The response body does not restate it.
    pub requested_commitment: String,
    pub chain: ChainClock,
    /// When this process finished receiving the response.
    pub local_receipt: LocalReceipt,
}

impl StateProvenance {
    /// The chain-to-receipt interval, when the chain's clock was stated for this slot.
    ///
    /// # Errors
    ///
    /// Refuses clocks whose difference overflows.
    pub fn chain_to_receipt(
        &self,
    ) -> Result<Option<ChainToReceiptAge>, joshi_market_math::would_quote::WouldQuoteError> {
        match self.chain {
            ChainClock::Stated(second) if second.slot == self.context_slot => {
                ChainToReceiptAge::measure(second, &self.local_receipt).map(Some)
            }
            _ => Ok(None),
        }
    }
}

/// One reconstructed venue state handed to the desk by whatever polled it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolledState {
    pub state: ExactCurveState,
    pub fee_source: FeeRateSource,
    pub provenance: StateProvenance,
}

/// Everything an episode needs declared before its first poll.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EpisodeOpening {
    pub episode_id: String,
    pub mint: String,
    pub venue: VenueBinding,
    pub hypothesis: DeclaredHypothesis,
    /// The clip the hypothesis is worked at, in quote atoms. The entry walk may spend slightly
    /// less on a bonding curve, where the deployed instruction is denominated in base out.
    pub declared_clip_quote_atoms: u128,
    pub rules: DeclaredRules,
    pub costs: DeclaredFixedCosts,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    pub opened_at_unix_ms: i64,
}

/// Which exit rule closed a position.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExitRuleName {
    StopLoss,
    TakeProfit,
    MaxHold,
}

impl ExitRuleName {
    /// Stable machine label.
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::StopLoss => "stop_loss",
            Self::TakeProfit => "take_profit",
            Self::MaxHold => "max_hold",
        }
    }
}

/// The would-sell valuation one holding poll produced, exactly as the exit rules saw it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HoldingValuation {
    /// What selling the whole held base back would return at this state, after venue fees.
    pub would_sell_quote_out_atoms: u128,
    /// That, minus the entry cost and every declared fixed cost. Signed.
    pub net_quote_atoms: i128,
    /// The net as basis points of the entry cost, floored toward negative infinity — which
    /// understates a gain and overstates a loss, so the rounding errs against the trade.
    pub net_of_all_in_cost_bps: i128,
}

/// What the desk concluded from one poll.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PollEvaluation {
    /// Waiting for the entry rule. `dip_bps` is the observed dip against the reference for a
    /// microdip rule, `rise_bps` the observed rise over it for a breakout rule; both are `None`
    /// for an immediate rule or on the reference-setting poll itself.
    AwaitingEntry {
        dip_bps: Option<u128>,
        rise_bps: Option<u128>,
    },
    EntryTriggered,
    Holding {
        valuation: HoldingValuation,
    },
    /// The venue refused to value the held base at this state. Recorded, never smoothed over.
    ValuationRefused {
        refusal: String,
    },
    ExitTriggered {
        rule: ExitRuleName,
    },
    /// The declared entry deadline passed before the entry rule triggered.
    EntryDeadlinePassed,
}

/// One poll, evaluated or refused.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PollKind {
    /// The driver could not produce an evaluable state, and said why.
    Refused { reason: String },
    Observed {
        context_slot: u64,
        chain: ChainClock,
        /// The reserve ratio at this poll. A mark; the price of no real trade.
        marginal_price: AtomicPrice,
        evaluation: PollEvaluation,
    },
}

/// One entry in the episode's poll trace.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PollRecord {
    pub seq: u32,
    /// Local wall clock at receipt (for observed polls) or at the recorded failure.
    pub wall_unix_ms: i64,
    pub kind: PollKind,
}

/// Whether an intent opened or closed the paper position.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntentKind {
    Entry,
    Exit,
}

/// The rule that fired and the observed values that satisfied it, both in words.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TriggerRecord {
    pub rule_verbatim: String,
    pub observed: String,
}

/// Which direction a would-quote walked.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QuoteDirection {
    BuyExactQuoteIn,
    SellExactBaseIn,
}

impl QuoteDirection {
    /// Stable machine label.
    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::BuyExactQuoteIn => "buy_exact_quote_in",
            Self::SellExactBaseIn => "sell_exact_base_in",
        }
    }
}

/// One would-quote as an intent recorded it: the exact walk, and where its state came from.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PaperWouldQuote {
    /// Which of the seven price objects this is. Always an exact-size quote.
    pub price_object: PriceObject,
    pub direction: QuoteDirection,
    /// Quote atoms in (buy) or out (sell), fees included.
    pub quote_atoms: u128,
    /// Base atoms out (buy) or in (sell).
    pub base_atoms: u128,
    /// Constant-product consideration before any fee component.
    pub raw_quote_atoms: u128,
    pub fees: FeeBreakdown,
    pub schedule: FeeSchedule,
    pub fee_source: FeeRateSource,
    pub provenance: StateProvenance,
    /// The arithmetic's own name. Always [`ARITHMETIC_PROVENANCE`].
    pub arithmetic: &'static str,
}

/// A quote the venue refused, recorded in the intent instead of any number.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuoteRefusalRecord {
    pub refusal: String,
}

/// One entry or exit intent, with its would-quote or its explicit refusal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PaperIntent {
    pub kind: IntentKind,
    /// The poll this intent fired at.
    pub poll_seq: u32,
    pub trigger: TriggerRecord,
    pub quote: Result<PaperWouldQuote, QuoteRefusalRecord>,
}

/// Two would-quotes and a declared cost list. Named as arithmetic, serialized with the
/// unmodeled-risk list adjacent to the headline number.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WouldPnl {
    /// Quote atoms the entry walk consumed, fees included.
    pub entry_quote_in_atoms: u128,
    /// Quote atoms the exit walk returned, after every fee component.
    pub exit_quote_out_atoms: u128,
    /// Every declared cost outside the venue, totalled.
    pub declared_fixed_cost_atoms: u128,
    /// Exit minus entry, venue fees only. A stated control.
    pub venue_only_net_quote_atoms: i128,
    /// Exit minus entry minus the declared fixed costs. Signed.
    pub net_quote_atoms: i128,
    /// The headline: the net as basis points of the entry cost, floored toward negative
    /// infinity, which errs against the trade in both directions.
    pub net_of_all_in_cost_bps: i128,
}

/// How an episode ended. Every variant is explicit; no episode ends silently.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EpisodeOutcome {
    /// The entry rule never triggered, or the venue refused the entry quote.
    NeverEntered { reason: String },
    /// An exit rule closed the position. The would-PnL exists.
    Closed { rule: ExitRuleName },
    /// The episode could not honestly continue. When a position was open on paper, the would-PnL
    /// is absent and `would_pnl_absent_because` says exactly why nothing was substituted for it.
    Abandoned {
        reason: String,
        would_pnl_absent_because: String,
    },
}

/// What the episode itself says could have made its numbers wrong.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EpisodeFalsifiers {
    pub declared_poll_cadence_ms: i64,
    pub poll_count: u32,
    pub refused_poll_count: u32,
    /// Largest wall-clock gap between consecutive polls, the open-to-first-poll gap included.
    /// `None` when no poll happened at all.
    pub largest_observed_gap_ms: Option<i64>,
    /// What the gaps mean, stated in the artifact rather than left to the reader.
    pub blindness: String,
    /// Chain-to-receipt interval at the entry decision, when the chain stated a clock.
    pub entry_chain_to_receipt: Option<ChainToReceiptAge>,
    /// The same at the exit decision.
    pub exit_chain_to_receipt: Option<ChainToReceiptAge>,
}

/// One finished paper episode. Everything a later reader needs to judge the hypothesis, the
/// rules, and the desk itself, in one artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PaperEpisodeV1 {
    pub episode_id: String,
    pub mint: String,
    pub venue: VenueBinding,
    pub hypothesis: DeclaredHypothesis,
    pub declared_clip_quote_atoms: u128,
    pub rules: DeclaredRules,
    pub costs: DeclaredFixedCosts,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    pub opened_at_unix_ms: i64,
    pub closed_at_unix_ms: i64,
    pub polls: Vec<PollRecord>,
    pub intents: Vec<PaperIntent>,
    pub outcome: EpisodeOutcome,
    /// Present only when an exit would-quote exists. An absent would-PnL is stated in the
    /// outcome, never approximated.
    pub would_pnl: Option<WouldPnl>,
    pub falsifiers: EpisodeFalsifiers,
}

/// What the desk did with one poll.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DeskStep {
    AwaitingEntry,
    Entered,
    /// Holding. The valuation is `None` when this poll produced no fresh one.
    Holding {
        net_of_all_in_cost_bps: Option<i128>,
    },
    Exited {
        rule: ExitRuleName,
    },
    NeverEntered,
    Abandoned,
}

enum Phase {
    AwaitingEntry {
        reference: Option<AtomicPrice>,
    },
    Holding {
        entry_receipt_ms: i64,
        entry_quote_in_atoms: u128,
        held_base_atoms: u128,
    },
    Closed,
}

/// The live desk for one episode: a pure state machine fed polls by a driver.
///
/// The desk records everything it is fed and everything it decides. It cannot be finished without
/// an outcome, so no episode ends silently, and it computes nothing from a state it was not
/// handed, so nothing in the record can be retro-fitted.
pub struct PaperDeskV1 {
    opening: EpisodeOpening,
    fixed_cost_atoms: u128,
    polls: Vec<PollRecord>,
    intents: Vec<PaperIntent>,
    outcome: Option<EpisodeOutcome>,
    would_pnl: Option<WouldPnl>,
    consecutive_failed_polls: u32,
    last_context_slot: Option<u64>,
    phase: Phase,
}

impl PaperDeskV1 {
    /// Opens an episode from a full declaration.
    ///
    /// # Errors
    ///
    /// Refuses a blank hypothesis, episode id, mint, or venue account; a hypothesis declared
    /// after the open; a zero clip; degenerate rules (zero cadence, thresholds, deadlines, or a
    /// stop or microdip beyond 10,000 bps); and declared costs whose total overflows.
    pub fn open(opening: EpisodeOpening) -> Result<Self, PaperError> {
        if opening.hypothesis.operator_words_verbatim.trim().is_empty() {
            return Err(PaperError::BlankHypothesis);
        }
        if opening.episode_id.trim().is_empty()
            || opening.mint.trim().is_empty()
            || opening.venue.venue_account.trim().is_empty()
            || opening.venue.binding.trim().is_empty()
        {
            return Err(PaperError::BlankIdentity);
        }
        if opening.hypothesis.declared_at_unix_ms > opening.opened_at_unix_ms {
            return Err(PaperError::HypothesisDeclaredAfterOpen);
        }
        if opening.declared_clip_quote_atoms == 0 {
            return Err(PaperError::ZeroClip);
        }
        let rules = &opening.rules;
        if rules.poll_cadence_ms <= 0
            || rules.entry_deadline_ms <= 0
            || rules.exit.max_hold_ms <= 0
            || rules.exit.take_profit_net_bps == 0
            || rules.exit.stop_loss_net_bps == 0
            || rules.abandon_after_consecutive_failed_polls == 0
        {
            return Err(PaperError::DegenerateRule);
        }
        if rules.exit.stop_loss_net_bps > 10_000 {
            return Err(PaperError::DegenerateRule);
        }
        if let EntryRule::MicrodipBps { trigger_bps } | EntryRule::BreakoutBps { trigger_bps } =
            rules.entry
            && (trigger_bps == 0 || trigger_bps > 10_000)
        {
            return Err(PaperError::DegenerateRule);
        }
        let fixed_cost_atoms = opening
            .costs
            .total_quote_atoms()
            .map_err(|_| PaperError::Arithmetic)?;
        if i128::try_from(fixed_cost_atoms).is_err() {
            return Err(PaperError::Arithmetic);
        }
        Ok(Self {
            opening,
            fixed_cost_atoms,
            polls: Vec::new(),
            intents: Vec::new(),
            outcome: None,
            would_pnl: None,
            consecutive_failed_polls: 0,
            last_context_slot: None,
            phase: Phase::AwaitingEntry { reference: None },
        })
    }

    /// Whether the episode has reached an outcome.
    #[must_use]
    pub const fn is_closed(&self) -> bool {
        self.outcome.is_some()
    }

    /// Feeds one evaluable polled state to the desk.
    ///
    /// # Errors
    ///
    /// Refuses a poll after the episode closed, and a state whose formula does not match the
    /// episode's venue — both are driver bugs, not market facts, so they are errors rather than
    /// recorded refusals. Everything the *market* refuses becomes a record in the episode.
    pub fn on_observed_poll(&mut self, poll: &PolledState) -> Result<DeskStep, PaperError> {
        if self.is_closed() {
            return Err(PaperError::EpisodeAlreadyClosed);
        }
        if poll.state.formula != self.opening.venue.venue.formula() {
            return Err(PaperError::FormulaDoesNotMatchVenue);
        }
        let receipt_ms = poll.provenance.local_receipt.wall_unix_ms;
        if let Some(last) = self.last_context_slot
            && poll.provenance.context_slot < last
        {
            return Ok(self.record_failed_poll(
                receipt_ms,
                format!(
                    "the provider's context slot went backwards, from {last} to {}; this \
                     observation was not evaluated",
                    poll.provenance.context_slot
                ),
            ));
        }
        let marginal = match poll.state.marginal_pool_price() {
            Ok(price) => price,
            Err(refusal) => {
                return Ok(self.record_failed_poll(
                    receipt_ms,
                    format!("the polled state admits no marginal price: {refusal}"),
                ));
            }
        };
        self.last_context_slot = Some(poll.provenance.context_slot);
        self.consecutive_failed_polls = 0;
        let seq = self.next_seq();
        match &self.phase {
            Phase::Closed => unreachable!("closed episodes were refused above"),
            Phase::AwaitingEntry { reference } => {
                Ok(self.evaluate_entry(seq, poll, marginal, *reference))
            }
            Phase::Holding {
                entry_receipt_ms,
                entry_quote_in_atoms,
                held_base_atoms,
            } => {
                let held = (*entry_receipt_ms, *entry_quote_in_atoms, *held_base_atoms);
                Ok(self.evaluate_holding(seq, poll, marginal, held))
            }
        }
    }

    /// Records a poll the driver could not turn into an evaluable state.
    ///
    /// # Errors
    ///
    /// Refuses a poll after the episode closed.
    pub fn on_failed_poll(
        &mut self,
        wall_unix_ms: i64,
        reason: impl Into<String>,
    ) -> Result<DeskStep, PaperError> {
        if self.is_closed() {
            return Err(PaperError::EpisodeAlreadyClosed);
        }
        Ok(self.record_failed_poll(wall_unix_ms, reason.into()))
    }

    /// Attaches the chain's whole-second clock to every record of the matching slot whose clock
    /// was `NotRequested`. Returns how many records it reached.
    pub fn attach_chain_second(&mut self, chain: ChainSecond) -> usize {
        let mut attached = 0;
        for poll in &mut self.polls {
            if let PollKind::Observed {
                context_slot,
                chain: clock,
                ..
            } = &mut poll.kind
                && *context_slot == chain.slot
                && *clock == ChainClock::NotRequested
            {
                *clock = ChainClock::Stated(chain);
                attached += 1;
            }
        }
        for intent in &mut self.intents {
            if let Ok(quote) = &mut intent.quote
                && quote.provenance.context_slot == chain.slot
                && quote.provenance.chain == ChainClock::NotRequested
            {
                quote.provenance.chain = ChainClock::Stated(chain);
                attached += 1;
            }
        }
        attached
    }

    /// Records that the provider was asked for this slot's block time and stated none, on every
    /// record of the matching slot whose clock was `NotRequested`. Returns how many records it
    /// reached. Keeping "asked and absent" apart from "never asked" is the point.
    pub fn mark_chain_clock_absent(&mut self, slot: u64) -> usize {
        let mut marked = 0;
        for poll in &mut self.polls {
            if let PollKind::Observed {
                context_slot,
                chain: clock,
                ..
            } = &mut poll.kind
                && *context_slot == slot
                && *clock == ChainClock::NotRequested
            {
                *clock = ChainClock::ProviderStatedNone;
                marked += 1;
            }
        }
        for intent in &mut self.intents {
            if let Ok(quote) = &mut intent.quote
                && quote.provenance.context_slot == slot
                && quote.provenance.chain == ChainClock::NotRequested
            {
                quote.provenance.chain = ChainClock::ProviderStatedNone;
                marked += 1;
            }
        }
        marked
    }

    /// Ends the episode without an exit, stating why. When a position was open on paper, the
    /// would-PnL is recorded as absent rather than computed from anything unpolled. A closed
    /// episode is left as it is.
    pub fn abandon(&mut self, reason: impl Into<String>) {
        if self.is_closed() {
            return;
        }
        let absent_because = match self.phase {
            Phase::Holding { .. } => {
                "a paper position was open and no honest exit state exists; a would-PnL computed \
                 from any other state would be fabricated, so there is none"
            }
            _ => "no paper position was ever open, so there is no would-PnL to state",
        };
        self.outcome = Some(EpisodeOutcome::Abandoned {
            reason: reason.into(),
            would_pnl_absent_because: absent_because.to_owned(),
        });
        self.phase = Phase::Closed;
    }

    /// Finishes the episode into its immutable artifact.
    ///
    /// # Errors
    ///
    /// Refuses an episode that has not reached an outcome. Ending an episode takes an explicit
    /// exit, deadline, or abandonment; there is no silent way out.
    pub fn finish(self, closed_at_unix_ms: i64) -> Result<PaperEpisodeV1, PaperError> {
        let Some(outcome) = self.outcome else {
            return Err(PaperError::EpisodeStillOpen);
        };
        let falsifiers = falsifiers(
            &self.opening,
            &self.polls,
            &self.intents,
            self.opening.opened_at_unix_ms,
        );
        Ok(PaperEpisodeV1 {
            episode_id: self.opening.episode_id,
            mint: self.opening.mint,
            venue: self.opening.venue,
            hypothesis: self.opening.hypothesis,
            declared_clip_quote_atoms: self.opening.declared_clip_quote_atoms,
            rules: self.opening.rules,
            costs: self.opening.costs,
            base_decimals: self.opening.base_decimals,
            quote_decimals: self.opening.quote_decimals,
            opened_at_unix_ms: self.opening.opened_at_unix_ms,
            closed_at_unix_ms,
            polls: self.polls,
            intents: self.intents,
            outcome,
            would_pnl: self.would_pnl,
            falsifiers,
        })
    }

    fn next_seq(&self) -> u32 {
        u32::try_from(self.polls.len()).unwrap_or(u32::MAX)
    }

    fn record_failed_poll(&mut self, wall_unix_ms: i64, reason: String) -> DeskStep {
        let seq = self.next_seq();
        self.polls.push(PollRecord {
            seq,
            wall_unix_ms,
            kind: PollKind::Refused { reason },
        });
        self.consecutive_failed_polls += 1;
        if self.consecutive_failed_polls
            >= self.opening.rules.abandon_after_consecutive_failed_polls
        {
            let failures = self.consecutive_failed_polls;
            self.abandon(format!(
                "{failures} consecutive polls produced no evaluable state, which is the declared \
                 abandonment threshold; the poll trace carries each recorded reason"
            ));
            return DeskStep::Abandoned;
        }
        match self.phase {
            Phase::AwaitingEntry { .. } => DeskStep::AwaitingEntry,
            Phase::Holding { .. } => DeskStep::Holding {
                net_of_all_in_cost_bps: None,
            },
            Phase::Closed => DeskStep::Abandoned,
        }
    }

    #[allow(clippy::too_many_lines)] // One entry decision, in the order the rules bind it.
    fn evaluate_entry(
        &mut self,
        seq: u32,
        poll: &PolledState,
        marginal: AtomicPrice,
        reference: Option<AtomicPrice>,
    ) -> DeskStep {
        let receipt_ms = poll.provenance.local_receipt.wall_unix_ms;
        let waited_ms = receipt_ms.saturating_sub(self.opening.opened_at_unix_ms);
        if waited_ms >= self.opening.rules.entry_deadline_ms {
            self.push_observed(seq, poll, marginal, PollEvaluation::EntryDeadlinePassed);
            self.outcome = Some(EpisodeOutcome::NeverEntered {
                reason: format!(
                    "the declared entry deadline of {} ms passed ({waited_ms} ms waited over {} \
                     polls) before the entry rule triggered; the deadline is checked before the \
                     rule, so a trigger at this poll would not have entered either",
                    self.opening.rules.entry_deadline_ms,
                    self.polls.len(),
                ),
            });
            self.phase = Phase::Closed;
            return DeskStep::NeverEntered;
        }
        let (triggered, dip_bps, rise_bps, trigger) = match self.opening.rules.entry {
            EntryRule::Immediate => (
                true,
                None,
                None,
                TriggerRecord {
                    rule_verbatim: "entry: immediate — enter at the first evaluated poll"
                        .to_owned(),
                    observed: format!(
                        "first evaluated poll, seq {seq}, at slot {}",
                        poll.provenance.context_slot
                    ),
                },
            ),
            EntryRule::MicrodipBps { trigger_bps } => {
                let Some(reference) = reference else {
                    self.phase = Phase::AwaitingEntry {
                        reference: Some(marginal),
                    };
                    self.push_observed(
                        seq,
                        poll,
                        marginal,
                        PollEvaluation::AwaitingEntry {
                            dip_bps: None,
                            rise_bps: None,
                        },
                    );
                    return DeskStep::AwaitingEntry;
                };
                let dip = dip_bps_under_reference(reference, marginal);
                let dip_value = dip.unwrap_or(0);
                (
                    dip_value >= u128::from(trigger_bps),
                    Some(dip_value),
                    None,
                    TriggerRecord {
                        rule_verbatim: format!(
                            "entry: microdip — enter at the first poll whose marginal pool price \
                             sits at least {trigger_bps} bps under the first observed marginal \
                             pool price; the dip is floored, so a partial dip never triggers"
                        ),
                        observed: format!(
                            "dip of {dip_value} bps at poll {seq}, slot {}, against the \
                             reference {}/{} set by poll 0",
                            poll.provenance.context_slot,
                            reference.numerator_quote_atoms(),
                            reference.denominator_base_atoms(),
                        ),
                    },
                )
            }
            EntryRule::BreakoutBps { trigger_bps } => {
                let Some(reference) = reference else {
                    self.phase = Phase::AwaitingEntry {
                        reference: Some(marginal),
                    };
                    self.push_observed(
                        seq,
                        poll,
                        marginal,
                        PollEvaluation::AwaitingEntry {
                            dip_bps: None,
                            rise_bps: None,
                        },
                    );
                    return DeskStep::AwaitingEntry;
                };
                let rise = rise_bps_over_reference(reference, marginal);
                let rise_value = rise.unwrap_or(0);
                (
                    rise_value >= u128::from(trigger_bps),
                    None,
                    Some(rise_value),
                    TriggerRecord {
                        rule_verbatim: format!(
                            "entry: breakout — enter at the first poll whose marginal pool price \
                             sits at least {trigger_bps} bps over the first observed marginal \
                             pool price; the rise is floored, so a partial rise never triggers"
                        ),
                        observed: format!(
                            "rise of {rise_value} bps at poll {seq}, slot {}, against the \
                             reference {}/{} set by poll 0",
                            poll.provenance.context_slot,
                            reference.numerator_quote_atoms(),
                            reference.denominator_base_atoms(),
                        ),
                    },
                )
            }
        };
        if !triggered {
            self.push_observed(
                seq,
                poll,
                marginal,
                PollEvaluation::AwaitingEntry { dip_bps, rise_bps },
            );
            return DeskStep::AwaitingEntry;
        }
        self.push_observed(seq, poll, marginal, PollEvaluation::EntryTriggered);
        match poll
            .state
            .buy_with_quote_in(self.opening.declared_clip_quote_atoms)
        {
            Err(refusal) => {
                self.intents.push(PaperIntent {
                    kind: IntentKind::Entry,
                    poll_seq: seq,
                    trigger,
                    quote: Err(QuoteRefusalRecord {
                        refusal: refusal.to_string(),
                    }),
                });
                self.outcome = Some(EpisodeOutcome::NeverEntered {
                    reason: format!(
                        "the entry rule triggered at poll {seq} but the venue refused to quote \
                         the declared clip at that state: {refusal}; the refusal is recorded and \
                         nothing was substituted for it"
                    ),
                });
                self.phase = Phase::Closed;
                DeskStep::NeverEntered
            }
            Ok(buy) => {
                self.intents.push(PaperIntent {
                    kind: IntentKind::Entry,
                    poll_seq: seq,
                    trigger,
                    quote: Ok(PaperWouldQuote {
                        price_object: PriceObject::ExactSizeQuote,
                        direction: QuoteDirection::BuyExactQuoteIn,
                        quote_atoms: buy.quote_in_atoms,
                        base_atoms: buy.base_out_atoms,
                        raw_quote_atoms: buy.raw_quote_atoms,
                        fees: buy.fees,
                        schedule: poll.state.schedule,
                        fee_source: poll.fee_source.clone(),
                        provenance: poll.provenance.clone(),
                        arithmetic: ARITHMETIC_PROVENANCE,
                    }),
                });
                self.phase = Phase::Holding {
                    entry_receipt_ms: poll.provenance.local_receipt.wall_unix_ms,
                    entry_quote_in_atoms: buy.quote_in_atoms,
                    held_base_atoms: buy.base_out_atoms,
                };
                DeskStep::Entered
            }
        }
    }

    #[allow(clippy::too_many_lines)] // One holding decision, in declared rule priority.
    fn evaluate_holding(
        &mut self,
        seq: u32,
        poll: &PolledState,
        marginal: AtomicPrice,
        held: (i64, u128, u128),
    ) -> DeskStep {
        let (entry_receipt_ms, entry_quote_in_atoms, held_base_atoms) = held;
        let sold = match poll.state.sell_base_in(held_base_atoms) {
            Ok(walked) => walked,
            Err(refusal) => {
                self.push_observed(
                    seq,
                    poll,
                    marginal,
                    PollEvaluation::ValuationRefused {
                        refusal: refusal.to_string(),
                    },
                );
                self.consecutive_failed_polls += 1;
                if self.consecutive_failed_polls
                    >= self.opening.rules.abandon_after_consecutive_failed_polls
                {
                    let failures = self.consecutive_failed_polls;
                    self.abandon(format!(
                        "{failures} consecutive polls produced no evaluable valuation of the \
                         held base; the poll trace carries each recorded refusal"
                    ));
                    return DeskStep::Abandoned;
                }
                return DeskStep::Holding {
                    net_of_all_in_cost_bps: None,
                };
            }
        };
        let Some(valuation) = net_valuation(
            sold.quote_out_atoms,
            entry_quote_in_atoms,
            self.fixed_cost_atoms,
        ) else {
            self.abandon(
                "checked arithmetic failed while valuing the held base, which this desk cannot \
                 continue past honestly",
            );
            return DeskStep::Abandoned;
        };
        let exit = self.opening.rules.exit;
        let held_ms = poll
            .provenance
            .local_receipt
            .wall_unix_ms
            .saturating_sub(entry_receipt_ms);
        let rule = if valuation.net_of_all_in_cost_bps <= -i128::from(exit.stop_loss_net_bps) {
            Some((
                ExitRuleName::StopLoss,
                format!(
                    "net valuation of {} bps at poll {seq} is at or below the declared stop of \
                     -{} bps; the stop fires at the first poll observed through it, and any \
                     depth beyond it inside a poll gap was invisible",
                    valuation.net_of_all_in_cost_bps, exit.stop_loss_net_bps
                ),
            ))
        } else if valuation.net_of_all_in_cost_bps >= i128::from(exit.take_profit_net_bps) {
            Some((
                ExitRuleName::TakeProfit,
                format!(
                    "net valuation of {} bps at poll {seq} is at or above the declared \
                     take-profit of {} bps",
                    valuation.net_of_all_in_cost_bps, exit.take_profit_net_bps
                ),
            ))
        } else if held_ms >= exit.max_hold_ms {
            Some((
                ExitRuleName::MaxHold,
                format!(
                    "held {held_ms} ms at poll {seq}, at or beyond the declared max hold of {} \
                     ms; the position exits at its valuation here, {} bps",
                    exit.max_hold_ms, valuation.net_of_all_in_cost_bps
                ),
            ))
        } else {
            None
        };
        let Some((rule, observed)) = rule else {
            self.push_observed(seq, poll, marginal, PollEvaluation::Holding { valuation });
            return DeskStep::Holding {
                net_of_all_in_cost_bps: Some(valuation.net_of_all_in_cost_bps),
            };
        };
        self.push_observed(seq, poll, marginal, PollEvaluation::ExitTriggered { rule });
        self.intents.push(PaperIntent {
            kind: IntentKind::Exit,
            poll_seq: seq,
            trigger: TriggerRecord {
                rule_verbatim: format!(
                    "exit: take-profit at +{} bps net of all-in cost, stop at -{} bps, max hold \
                     {} ms; priority: {RULE_PRIORITY}",
                    exit.take_profit_net_bps, exit.stop_loss_net_bps, exit.max_hold_ms
                ),
                observed,
            },
            quote: Ok(PaperWouldQuote {
                price_object: PriceObject::ExactSizeQuote,
                direction: QuoteDirection::SellExactBaseIn,
                quote_atoms: sold.quote_out_atoms,
                base_atoms: sold.base_in_atoms,
                raw_quote_atoms: sold.raw_quote_atoms,
                fees: sold.fees,
                schedule: poll.state.schedule,
                fee_source: poll.fee_source.clone(),
                provenance: poll.provenance.clone(),
                arithmetic: ARITHMETIC_PROVENANCE,
            }),
        });
        self.would_pnl = Some(WouldPnl {
            entry_quote_in_atoms,
            exit_quote_out_atoms: sold.quote_out_atoms,
            declared_fixed_cost_atoms: self.fixed_cost_atoms,
            venue_only_net_quote_atoms: valuation
                .net_quote_atoms
                .saturating_add(i128::try_from(self.fixed_cost_atoms).unwrap_or(i128::MAX)),
            net_quote_atoms: valuation.net_quote_atoms,
            net_of_all_in_cost_bps: valuation.net_of_all_in_cost_bps,
        });
        self.outcome = Some(EpisodeOutcome::Closed { rule });
        self.phase = Phase::Closed;
        DeskStep::Exited { rule }
    }

    fn push_observed(
        &mut self,
        seq: u32,
        poll: &PolledState,
        marginal: AtomicPrice,
        evaluation: PollEvaluation,
    ) {
        self.polls.push(PollRecord {
            seq,
            wall_unix_ms: poll.provenance.local_receipt.wall_unix_ms,
            kind: PollKind::Observed {
                context_slot: poll.provenance.context_slot,
                chain: poll.provenance.chain,
                marginal_price: marginal,
                evaluation,
            },
        });
    }
}

/// `(reference - current) / reference` in floored basis points, when the current mark is under
/// the reference. `None` when it is not under, or when the exact ratio cannot be taken.
fn dip_bps_under_reference(reference: AtomicPrice, current: AtomicPrice) -> Option<u128> {
    let cross_reference = reference
        .numerator_quote_atoms()
        .checked_mul(current.denominator_base_atoms())?;
    let cross_current = current
        .numerator_quote_atoms()
        .checked_mul(reference.denominator_base_atoms())?;
    if cross_current >= cross_reference {
        return None;
    }
    ExactRatio::new(cross_reference - cross_current, cross_reference)
        .ok()?
        .bps_floor()
        .ok()
}

/// `(current - reference) / reference` in floored basis points, when the current mark is over
/// the reference. `None` when it is not over, or when the exact ratio cannot be taken.
fn rise_bps_over_reference(reference: AtomicPrice, current: AtomicPrice) -> Option<u128> {
    let cross_reference = reference
        .numerator_quote_atoms()
        .checked_mul(current.denominator_base_atoms())?;
    let cross_current = current
        .numerator_quote_atoms()
        .checked_mul(reference.denominator_base_atoms())?;
    if cross_current <= cross_reference {
        return None;
    }
    ExactRatio::new(cross_current - cross_reference, cross_reference)
        .ok()?
        .bps_floor()
        .ok()
}

/// The signed net valuation, floored toward negative infinity so rounding errs against the trade.
fn net_valuation(
    would_sell_quote_out_atoms: u128,
    entry_quote_in_atoms: u128,
    fixed_cost_atoms: u128,
) -> Option<HoldingValuation> {
    let out = i128::try_from(would_sell_quote_out_atoms).ok()?;
    let entry = i128::try_from(entry_quote_in_atoms).ok()?;
    let fixed = i128::try_from(fixed_cost_atoms).ok()?;
    if entry <= 0 {
        return None;
    }
    let net = out.checked_sub(entry)?.checked_sub(fixed)?;
    let bps = net.checked_mul(10_000)?.div_euclid(entry);
    Some(HoldingValuation {
        would_sell_quote_out_atoms,
        net_quote_atoms: net,
        net_of_all_in_cost_bps: bps,
    })
}

fn falsifiers(
    opening: &EpisodeOpening,
    polls: &[PollRecord],
    intents: &[PaperIntent],
    opened_at_unix_ms: i64,
) -> EpisodeFalsifiers {
    let mut largest_gap: Option<i64> = None;
    let mut previous = opened_at_unix_ms;
    for poll in polls {
        let gap = poll.wall_unix_ms.saturating_sub(previous);
        largest_gap = Some(largest_gap.map_or(gap, |held| held.max(gap)));
        previous = poll.wall_unix_ms;
    }
    let refused = polls
        .iter()
        .filter(|poll| matches!(poll.kind, PollKind::Refused { .. }))
        .count();
    let age_of = |kind: IntentKind| -> Option<ChainToReceiptAge> {
        intents
            .iter()
            .find(|intent| intent.kind == kind)
            .and_then(|intent| intent.quote.as_ref().ok())
            .and_then(|quote| quote.provenance.chain_to_receipt().ok().flatten())
    };
    let blindness = largest_gap.map_or_else(
        || "no poll was ever received, so this episode observed nothing at all".to_owned(),
        |gap| {
            format!(
                "state was sampled at a declared cadence of {} ms and the largest observed gap \
                 between polls was {gap} ms; every move that began and completed inside a gap is \
                 invisible to this episode, including a move through the declared stop — a stop \
                 here is a rule about observed states, not a guaranteed price",
                opening.rules.poll_cadence_ms
            )
        },
    );
    EpisodeFalsifiers {
        declared_poll_cadence_ms: opening.rules.poll_cadence_ms,
        poll_count: u32::try_from(polls.len()).unwrap_or(u32::MAX),
        refused_poll_count: u32::try_from(refused).unwrap_or(u32::MAX),
        largest_observed_gap_ms: largest_gap,
        blindness,
        entry_chain_to_receipt: age_of(IntentKind::Entry),
        exit_chain_to_receipt: age_of(IntentKind::Exit),
    }
}

/// Exactly why the desk refused. Market refusals are recorded in the episode instead; these are
/// declaration and driver errors.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum PaperError {
    #[error("the hypothesis is blank; an episode without operator words is not testing anything")]
    BlankHypothesis,
    #[error("an episode id, mint, venue account, or venue binding is blank")]
    BlankIdentity,
    #[error("the hypothesis is dated after the episode opened, which would allow retro-fitting")]
    HypothesisDeclaredAfterOpen,
    #[error("the declared clip is zero")]
    ZeroClip,
    #[error(
        "a declared rule is degenerate: cadence, deadlines, and thresholds must be positive, and \
         a stop or microdip cannot exceed 10,000 bps"
    )]
    DegenerateRule,
    #[error("the polled state's formula does not match the episode's venue")]
    FormulaDoesNotMatchVenue,
    #[error("the episode has already reached an outcome")]
    EpisodeAlreadyClosed,
    #[error("the episode has not reached an outcome; exit, deadline, or abandon it explicitly")]
    EpisodeStillOpen,
    #[error("checked arithmetic failed")]
    Arithmetic,
    #[error(transparent)]
    Stack(#[from] StackRefusal),
}

// --- rendering ---------------------------------------------------------------------------------

impl PaperEpisodeV1 {
    /// Renders the episode as deterministic JSON, every integer a string.
    #[must_use]
    pub fn render_json(&self) -> String {
        object(&[
            ("contract", quoted(PAPER_EPISODE_CONTRACT)),
            ("schemaVersion", quoted("1")),
            ("authority", quoted(PAPER_EPISODE_AUTHORITY)),
            ("notATradingResult", quoted(NOT_A_TRADING_RESULT)),
            ("episodeId", quoted(&self.episode_id)),
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
                "hypothesis",
                object(&[
                    (
                        "operatorWordsVerbatim",
                        quoted(&self.hypothesis.operator_words_verbatim),
                    ),
                    ("declaredBy", quoted(&self.hypothesis.declared_by)),
                    (
                        "declaredAtUnixMs",
                        integer(&self.hypothesis.declared_at_unix_ms),
                    ),
                ]),
            ),
            ("declared", self.render_declared()),
            ("openedAtUnixMs", integer(&self.opened_at_unix_ms)),
            ("closedAtUnixMs", integer(&self.closed_at_unix_ms)),
            ("outcome", self.render_outcome()),
            ("wouldPnl", self.render_would_pnl()),
            ("falsifiers", self.render_falsifiers()),
            (
                "intents",
                array(&self.intents.iter().map(render_intent).collect::<Vec<_>>()),
            ),
            (
                "polls",
                array(&self.polls.iter().map(render_poll).collect::<Vec<_>>()),
            ),
            ("arithmeticProvenance", quoted(ARITHMETIC_PROVENANCE)),
        ])
    }

    #[allow(clippy::too_many_lines)] // The declaration renders verbatim, in one place.
    fn render_declared(&self) -> String {
        let entry = match self.rules.entry {
            EntryRule::Immediate => object(&[
                ("kind", quoted("immediate")),
                ("rule", quoted("enter at the first evaluated poll")),
            ]),
            EntryRule::MicrodipBps { trigger_bps } => object(&[
                ("kind", quoted("microdip")),
                ("triggerBps", integer(&trigger_bps)),
                (
                    "rule",
                    quoted(
                        "enter at the first poll whose marginal pool price sits at least \
                         triggerBps under the first observed marginal pool price; the reference \
                         is fixed by the first poll and never re-anchored, and the dip is \
                         floored, so a partial dip never triggers",
                    ),
                ),
            ]),
            EntryRule::BreakoutBps { trigger_bps } => object(&[
                ("kind", quoted("breakout")),
                ("triggerBps", integer(&trigger_bps)),
                (
                    "rule",
                    quoted(
                        "enter at the first poll whose marginal pool price sits at least \
                         triggerBps over the first observed marginal pool price; the reference \
                         is fixed by the first poll and never re-anchored, and the rise is \
                         floored, so a partial rise never triggers",
                    ),
                ),
            ]),
        };
        object(&[
            ("clipQuoteAtoms", integer(&self.declared_clip_quote_atoms)),
            (
                "rules",
                object(&[
                    ("entry", entry),
                    ("entryDeadlineMs", integer(&self.rules.entry_deadline_ms)),
                    (
                        "entryDeadlineNote",
                        quoted(
                            "checked before the entry rule at each poll; a trigger on a poll at \
                             or after the deadline does not enter",
                        ),
                    ),
                    (
                        "exit",
                        object(&[
                            (
                                "takeProfitNetBps",
                                integer(&self.rules.exit.take_profit_net_bps),
                            ),
                            (
                                "stopLossNetBps",
                                integer(&self.rules.exit.stop_loss_net_bps),
                            ),
                            ("maxHoldMs", integer(&self.rules.exit.max_hold_ms)),
                        ]),
                    ),
                    ("rulePriority", quoted(RULE_PRIORITY)),
                    (
                        "evaluation",
                        quoted(
                            "take-profit and stop compare the would-sell valuation of the held \
                             base, net of the entry cost and every declared fixed cost, against \
                             the entry cost; every valuation is a would-quote from the deployed \
                             integer arithmetic at a polled state, never a mark",
                        ),
                    ),
                    ("pollCadenceMs", integer(&self.rules.poll_cadence_ms)),
                    (
                        "abandonAfterConsecutiveFailedPolls",
                        integer(&self.rules.abandon_after_consecutive_failed_polls),
                    ),
                ]),
            ),
            (
                "fixedCosts",
                object(&[
                    ("provenance", quoted(&self.costs.provenance)),
                    (
                        "perTransactionQuoteAtoms",
                        integer(&self.costs.per_transaction_quote_atoms),
                    ),
                    ("transactions", integer(&self.costs.transactions)),
                    (
                        "flatRouteQuoteAtoms",
                        integer(&self.costs.flat_route_quote_atoms),
                    ),
                    (
                        "unrecoveredRentQuoteAtoms",
                        integer(&self.costs.unrecovered_rent_quote_atoms),
                    ),
                ]),
            ),
            ("baseDecimals", integer(&self.base_decimals)),
            ("quoteDecimals", integer(&self.quote_decimals)),
        ])
    }

    fn render_outcome(&self) -> String {
        match &self.outcome {
            EpisodeOutcome::NeverEntered { reason } => object(&[
                ("kind", quoted("never_entered")),
                ("reason", quoted(reason)),
            ]),
            EpisodeOutcome::Closed { rule } => {
                object(&[("kind", quoted("closed")), ("rule", quoted(rule.label()))])
            }
            EpisodeOutcome::Abandoned {
                reason,
                would_pnl_absent_because,
            } => object(&[
                ("kind", quoted("abandoned")),
                ("reason", quoted(reason)),
                ("wouldPnlAbsentBecause", quoted(would_pnl_absent_because)),
            ]),
        }
    }

    fn render_would_pnl(&self) -> String {
        let Some(pnl) = &self.would_pnl else {
            let because = match &self.outcome {
                EpisodeOutcome::Abandoned {
                    would_pnl_absent_because,
                    ..
                } => would_pnl_absent_because.clone(),
                EpisodeOutcome::NeverEntered { .. } => {
                    "no paper position was ever open, so there is no would-PnL to state".to_owned()
                }
                EpisodeOutcome::Closed { .. } => {
                    "absent despite a closed outcome, which is a desk defect worth reporting"
                        .to_owned()
                }
            };
            return object(&[("status", quoted("absent")), ("because", quoted(&because))]);
        };
        let unmodeled = unmodeled_risks()
            .iter()
            .map(|risk| quoted(risk))
            .collect::<Vec<_>>();
        object(&[
            ("status", quoted("computed")),
            ("isArithmeticNotAResult", quoted(WOULD_PNL_IS)),
            ("netOfAllInCostBps", integer(&pnl.net_of_all_in_cost_bps)),
            ("unmodeledRisks", array(&unmodeled)),
            ("entryQuoteInAtoms", integer(&pnl.entry_quote_in_atoms)),
            ("exitQuoteOutAtoms", integer(&pnl.exit_quote_out_atoms)),
            (
                "declaredFixedCostAtoms",
                integer(&pnl.declared_fixed_cost_atoms),
            ),
            ("netQuoteAtoms", integer(&pnl.net_quote_atoms)),
            (
                "venueOnlyNetQuoteAtoms",
                integer(&pnl.venue_only_net_quote_atoms),
            ),
            (
                "roundingNote",
                quoted(
                    "netOfAllInCostBps is floored toward negative infinity, which understates a \
                     gain and overstates a loss; the rounding errs against the trade",
                ),
            ),
        ])
    }

    fn render_falsifiers(&self) -> String {
        let f = &self.falsifiers;
        let age = |value: &Option<ChainToReceiptAge>| -> String {
            value.map_or_else(
                || {
                    object(&[(
                        "status",
                        quoted(
                            "not stated: the chain's whole-second clock for the decision slot \
                             was not requested or not stated by the provider; an absent record, \
                             not an age of zero",
                        ),
                    )])
                },
                |age| {
                    object(&[
                        ("earliestMs", integer(&age.earliest_ms)),
                        ("latestMs", integer(&age.latest_ms)),
                        (
                            "note",
                            quoted(
                                "an interval, because blockTime has whole-second resolution; it \
                                 measures chain-report-to-local-receipt, not state age, and the \
                                 state may be older than its read",
                            ),
                        ),
                    ])
                },
            )
        };
        object(&[
            (
                "declaredPollCadenceMs",
                integer(&f.declared_poll_cadence_ms),
            ),
            ("pollCount", integer(&f.poll_count)),
            ("refusedPollCount", integer(&f.refused_poll_count)),
            (
                "largestObservedGapMs",
                f.largest_observed_gap_ms
                    .map_or_else(|| quoted("no poll was received"), |gap| integer(&gap)),
            ),
            ("blindness", quoted(&f.blindness)),
            ("entryChainToReceipt", age(&f.entry_chain_to_receipt)),
            ("exitChainToReceipt", age(&f.exit_chain_to_receipt)),
        ])
    }

    /// Renders the episode as a card a person reads, headline honesty first.
    #[must_use]
    #[allow(clippy::too_many_lines)] // One card, printed in the order a reader needs it.
    pub fn render_card(&self) -> String {
        let mut card = String::new();
        let _ = writeln!(card, "PAPER EPISODE  {PAPER_EPISODE_CONTRACT}");
        let _ = writeln!(card, "authority      {PAPER_EPISODE_AUTHORITY}");
        let _ = writeln!(card, "episode        {}", self.episode_id);
        let _ = writeln!(card, "mint           {}", self.mint);
        let _ = writeln!(
            card,
            "venue          {} at {}",
            self.venue.venue.label(),
            self.venue.venue_account
        );
        let _ = writeln!(
            card,
            "hypothesis     \"{}\"\n               declared by {} at unix ms {}",
            self.hypothesis.operator_words_verbatim,
            self.hypothesis.declared_by,
            self.hypothesis.declared_at_unix_ms
        );
        let _ = writeln!(
            card,
            "clip           {} quote atoms ({} SOL at {} decimals)",
            self.declared_clip_quote_atoms,
            render_decimal(self.declared_clip_quote_atoms, self.quote_decimals),
            self.quote_decimals
        );
        match &self.outcome {
            EpisodeOutcome::NeverEntered { reason } => {
                let _ = writeln!(card, "outcome        NEVER ENTERED: {reason}");
            }
            EpisodeOutcome::Closed { rule } => {
                let _ = writeln!(card, "outcome        closed by {}", rule.label());
            }
            EpisodeOutcome::Abandoned {
                reason,
                would_pnl_absent_because,
            } => {
                let _ = writeln!(card, "outcome        ABANDONED: {reason}");
                let _ = writeln!(
                    card,
                    "               would-PnL absent: {would_pnl_absent_because}"
                );
            }
        }
        match &self.would_pnl {
            None => {
                card.push_str("would-PnL      ABSENT, stated above; nothing was substituted\n");
            }
            Some(pnl) => {
                let _ = writeln!(
                    card,
                    "would-PnL      {} bps net of all-in cost ({} quote atoms on an entry of {})",
                    pnl.net_of_all_in_cost_bps, pnl.net_quote_atoms, pnl.entry_quote_in_atoms
                );
                card.push_str("  arithmetic, not a result. unmodeled, each against the trade:\n");
                for risk in unmodeled_risks() {
                    let _ = writeln!(card, "    - {risk}");
                }
            }
        }
        let _ = writeln!(card, "falsifiers     {}", self.falsifiers.blindness);
        let _ = writeln!(
            card,
            "polls          {} ({} refused)",
            self.falsifiers.poll_count, self.falsifiers.refused_poll_count
        );
        for intent in &self.intents {
            let kind = match intent.kind {
                IntentKind::Entry => "entry",
                IntentKind::Exit => "exit ",
            };
            match &intent.quote {
                Ok(quote) => {
                    let _ = writeln!(
                        card,
                        "{kind}          {} {} quote atoms / {} base atoms at slot {} \
                         ({})\n               triggered: {}",
                        quote.direction.label(),
                        quote.quote_atoms,
                        quote.base_atoms,
                        quote.provenance.context_slot,
                        quote.price_object.label(),
                        intent.trigger.observed
                    );
                }
                Err(refusal) => {
                    let _ = writeln!(
                        card,
                        "{kind}          REFUSED: {}\n               triggered: {}",
                        refusal.refusal, intent.trigger.observed
                    );
                }
            }
        }
        let _ = writeln!(card, "\n{NOT_A_TRADING_RESULT}");
        card
    }
}

#[allow(clippy::too_many_lines)] // One intent, every provenance field in one object.
fn render_intent(intent: &PaperIntent) -> String {
    let kind = match intent.kind {
        IntentKind::Entry => "entry",
        IntentKind::Exit => "exit",
    };
    let quote = match &intent.quote {
        Ok(quote) => object(&[
            ("status", quoted("quoted")),
            ("priceObject", quoted(quote.price_object.label())),
            ("direction", quoted(quote.direction.label())),
            ("quoteAtoms", integer(&quote.quote_atoms)),
            ("baseAtoms", integer(&quote.base_atoms)),
            ("rawQuoteAtoms", integer(&quote.raw_quote_atoms)),
            (
                "fees",
                object(&[
                    ("lpAtoms", integer(&quote.fees.lp_atoms)),
                    ("protocolAtoms", integer(&quote.fees.protocol_atoms)),
                    ("creatorAtoms", integer(&quote.fees.creator_atoms)),
                ]),
            ),
            (
                "feeSchedule",
                object(&[
                    ("lpBps", integer(&quote.schedule.lp.get())),
                    ("protocolBps", integer(&quote.schedule.protocol.get())),
                    (
                        "creator",
                        quoted(&match quote.schedule.creator {
                            CreatorFee::Charged(rate) => format!("{} bps", rate.get()),
                            CreatorFee::NotApplicable => "not applicable".to_owned(),
                            CreatorFee::Unknown => "unknown".to_owned(),
                        }),
                    ),
                ]),
            ),
            ("feeSource", render_fee_source(&quote.fee_source)),
            ("state", render_provenance(&quote.provenance)),
            ("arithmetic", quoted(quote.arithmetic)),
        ]),
        Err(refusal) => object(&[
            ("status", quoted("refused")),
            ("refusal", quoted(&refusal.refusal)),
            (
                "note",
                quoted("recorded as an explicit refusal; no number was gap-filled in its place"),
            ),
        ]),
    };
    object(&[
        ("kind", quoted(kind)),
        ("pollSeq", integer(&intent.poll_seq)),
        (
            "trigger",
            object(&[
                ("ruleVerbatim", quoted(&intent.trigger.rule_verbatim)),
                ("observed", quoted(&intent.trigger.observed)),
            ]),
        ),
        ("wouldQuote", quote),
    ])
}

fn render_fee_source(source: &FeeRateSource) -> String {
    let FeeRateSource::FeeProgramConfig {
        config_address,
        tables_agreed,
        selected_at_market_cap_quote_atoms,
    } = source
    else {
        let FeeRateSource::CarriedFromPriorReading {
            established_by,
            not_read_here_because,
        } = source
        else {
            unreachable!("the fee-rate source enum has exactly two variants")
        };
        return object(&[
            ("provenance", quoted("carried_from_prior_reading")),
            ("establishedBy", quoted(established_by)),
            ("notReadHereBecause", quoted(not_read_here_because)),
            (
                "note",
                quoted(
                    "these rates were not read at the state they are applied to, and no tier was \
                     selected here; a carried rate is weaker evidence than a read one and is \
                     named so rather than dressed as one",
                ),
            ),
        ]);
    };
    object(&[
        ("configAddress", quoted(config_address)),
        (
            "tablesAgreed",
            if *tables_agreed { "true" } else { "false" }.to_owned(),
        ),
        (
            "selectedAtMarketCapQuoteAtoms",
            integer(selected_at_market_cap_quote_atoms),
        ),
        (
            "note",
            quoted(
                "rates come from the fee program's configuration account, never the Global \
                 account and never a frontend index; the tier row is re-selected at each poll's \
                 market cap",
            ),
        ),
    ])
}

fn render_chain_clock(clock: ChainClock) -> String {
    match clock {
        ChainClock::NotRequested => object(&[(
            "status",
            quoted(
                "not requested: the driver declared it would not spend a request on this slot's \
                 block time; an economy, not an absence of the chain's clock",
            ),
        )]),
        ChainClock::ProviderStatedNone => object(&[(
            "status",
            quoted(
                "the provider stated no block time for this slot; an absent record, never an \
                 age of zero",
            ),
        )]),
        ChainClock::FeedStatesNoClock => object(&[(
            "status",
            quoted(
                "the feed this state came from carries no chain clock on any frame; the only \
                 time axis is the recorder's own receive instant, and no chain age is derivable",
            ),
        )]),
        ChainClock::Stated(second) => object(&[
            ("status", quoted("stated")),
            ("slot", integer(&second.slot)),
            ("blockTimeUnixSeconds", integer(&second.block_time_unix_s)),
            ("resolutionSeconds", quoted("1")),
        ]),
    }
}

fn render_provenance(provenance: &StateProvenance) -> String {
    let age = provenance.chain_to_receipt().ok().flatten().map_or_else(
        || quoted("not measurable from what was requested"),
        |age| {
            object(&[
                ("earliestMs", integer(&age.earliest_ms)),
                ("latestMs", integer(&age.latest_ms)),
            ])
        },
    );
    object(&[
        ("contextSlot", integer(&provenance.context_slot)),
        (
            "requestedCommitment",
            quoted(&provenance.requested_commitment),
        ),
        ("chainClock", render_chain_clock(provenance.chain)),
        (
            "localReceipt",
            object(&[
                ("clockId", quoted(&provenance.local_receipt.clock_id)),
                (
                    "monotonicNs",
                    integer(&provenance.local_receipt.monotonic_ns),
                ),
                (
                    "wallUnixMs",
                    integer(&provenance.local_receipt.wall_unix_ms),
                ),
            ]),
        ),
        ("chainToReceiptAgeMs", age),
    ])
}

#[allow(clippy::too_many_lines)] // One poll record, rendered in full.
fn render_poll(poll: &PollRecord) -> String {
    let kind = match &poll.kind {
        PollKind::Refused { reason } => {
            object(&[("status", quoted("refused")), ("reason", quoted(reason))])
        }
        PollKind::Observed {
            context_slot,
            chain,
            marginal_price,
            evaluation,
        } => {
            let evaluated = match evaluation {
                PollEvaluation::AwaitingEntry { dip_bps, rise_bps } => object(&[
                    ("kind", quoted("awaiting_entry")),
                    (
                        "dipBps",
                        dip_bps.map_or_else(|| quoted("none observed"), |dip| integer(&dip)),
                    ),
                    (
                        "riseBps",
                        rise_bps.map_or_else(|| quoted("none observed"), |rise| integer(&rise)),
                    ),
                ]),
                PollEvaluation::EntryTriggered => object(&[("kind", quoted("entry_triggered"))]),
                PollEvaluation::Holding { valuation } => object(&[
                    ("kind", quoted("holding")),
                    (
                        "wouldSellQuoteOutAtoms",
                        integer(&valuation.would_sell_quote_out_atoms),
                    ),
                    ("netQuoteAtoms", integer(&valuation.net_quote_atoms)),
                    (
                        "netOfAllInCostBps",
                        integer(&valuation.net_of_all_in_cost_bps),
                    ),
                ]),
                PollEvaluation::ValuationRefused { refusal } => object(&[
                    ("kind", quoted("valuation_refused")),
                    ("refusal", quoted(refusal)),
                ]),
                PollEvaluation::ExitTriggered { rule } => object(&[
                    ("kind", quoted("exit_triggered")),
                    ("rule", quoted(rule.label())),
                ]),
                PollEvaluation::EntryDeadlinePassed => {
                    object(&[("kind", quoted("entry_deadline_passed"))])
                }
            };
            object(&[
                ("status", quoted("observed")),
                ("contextSlot", integer(context_slot)),
                (
                    "marginalPrice",
                    object(&[
                        ("object", quoted(PriceObject::MarginalPoolPrice.label())),
                        (
                            "quoteAtoms",
                            integer(&marginal_price.numerator_quote_atoms()),
                        ),
                        (
                            "baseAtoms",
                            integer(&marginal_price.denominator_base_atoms()),
                        ),
                    ]),
                ),
                ("chainClock", render_chain_clock(*chain)),
                ("evaluation", evaluated),
            ])
        }
    };
    object(&[
        ("seq", integer(&poll.seq)),
        ("wallUnixMs", integer(&poll.wall_unix_ms)),
        ("poll", kind),
    ])
}

/// Renders atoms with a decimal point, exactly.
fn render_decimal(atoms: u128, decimals: u8) -> String {
    let scale = 10_u128.checked_pow(u32::from(decimals)).unwrap_or(1);
    let whole = atoms / scale;
    let fraction = atoms % scale;
    if decimals == 0 {
        return whole.to_string();
    }
    format!("{whole}.{fraction:0width$}", width = usize::from(decimals))
}

#[cfg(test)]
mod tests {
    use joshi_market_math::{
        fee::{CreatorFee, FeeBps, FeeSchedule},
        stack::VenueFormula,
    };

    use super::*;

    const OPENED_AT_MS: i64 = 1_000_000;
    const CLIP_ATOMS: u128 = 250_000_000;

    fn schedule() -> FeeSchedule {
        FeeSchedule {
            lp: FeeBps::new(20).expect("valid"),
            protocol: FeeBps::new(5).expect("valid"),
            creator: CreatorFee::Charged(FeeBps::new(30).expect("valid")),
        }
    }

    fn pool_state(base_atoms: u128, effective_quote_atoms: u128) -> ExactCurveState {
        ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms,
            effective_quote_atoms,
            schedule: schedule(),
        }
    }

    fn deep_pool() -> ExactCurveState {
        pool_state(1_000_000_000_000_000, 1_500_000_000_000)
    }

    fn provenance(slot: u64, wall_unix_ms: i64) -> StateProvenance {
        StateProvenance {
            context_slot: slot,
            requested_commitment: "finalized".to_owned(),
            chain: ChainClock::NotRequested,
            local_receipt: LocalReceipt {
                clock_id: "joshi-paper-test".to_owned(),
                monotonic_ns: u64::try_from(wall_unix_ms).expect("test clocks are positive")
                    * 1_000_000,
                wall_unix_ms,
            },
        }
    }

    fn polled(state: ExactCurveState, slot: u64, wall_unix_ms: i64) -> PolledState {
        PolledState {
            state,
            fee_source: FeeRateSource::FeeProgramConfig {
                config_address: "test-fee-config".to_owned(),
                tables_agreed: true,
                selected_at_market_cap_quote_atoms: 42,
            },
            provenance: provenance(slot, wall_unix_ms),
        }
    }

    fn rules(entry: EntryRule) -> DeclaredRules {
        DeclaredRules {
            entry,
            entry_deadline_ms: 60_000,
            exit: ExitRules {
                take_profit_net_bps: 100,
                stop_loss_net_bps: 300,
                max_hold_ms: 600_000,
            },
            poll_cadence_ms: 5_000,
            abandon_after_consecutive_failed_polls: 3,
        }
    }

    fn opening(entry: EntryRule, costs: DeclaredFixedCosts) -> EpisodeOpening {
        EpisodeOpening {
            episode_id: "paper-test-1".to_owned(),
            mint: "TestMint111111111111111111111111111111111111".to_owned(),
            venue: VenueBinding {
                venue: VenueKind::PumpSwapPool,
                venue_account: "TestPool1111111111111111111111111111111111".to_owned(),
                binding: "a test fixture; the binding text is carried verbatim".to_owned(),
            },
            hypothesis: DeclaredHypothesis {
                operator_words_verbatim: "hmm this coin is gonna wiggle for a bit".to_owned(),
                declared_by: "ember".to_owned(),
                declared_at_unix_ms: OPENED_AT_MS - 500,
            },
            declared_clip_quote_atoms: CLIP_ATOMS,
            rules: rules(entry),
            costs,
            base_decimals: 6,
            quote_decimals: 9,
            opened_at_unix_ms: OPENED_AT_MS,
        }
    }

    fn desk(entry: EntryRule) -> PaperDeskV1 {
        PaperDeskV1::open(opening(entry, DeclaredFixedCosts::none("test control"))).expect("opens")
    }

    #[test]
    fn open_refuses_a_blank_hypothesis() {
        let mut declaration = opening(EntryRule::Immediate, DeclaredFixedCosts::none("test"));
        declaration.hypothesis.operator_words_verbatim = "   ".to_owned();
        assert_eq!(
            PaperDeskV1::open(declaration).err(),
            Some(PaperError::BlankHypothesis)
        );
    }

    #[test]
    fn open_refuses_a_hypothesis_dated_after_the_open() {
        let mut declaration = opening(EntryRule::Immediate, DeclaredFixedCosts::none("test"));
        declaration.hypothesis.declared_at_unix_ms = OPENED_AT_MS + 1;
        assert_eq!(
            PaperDeskV1::open(declaration).err(),
            Some(PaperError::HypothesisDeclaredAfterOpen)
        );
    }

    #[test]
    fn open_refuses_degenerate_rules() {
        for degenerate in [
            |rules: &mut DeclaredRules| rules.poll_cadence_ms = 0,
            |rules: &mut DeclaredRules| rules.entry_deadline_ms = 0,
            |rules: &mut DeclaredRules| rules.exit.take_profit_net_bps = 0,
            |rules: &mut DeclaredRules| rules.exit.stop_loss_net_bps = 0,
            |rules: &mut DeclaredRules| rules.exit.stop_loss_net_bps = 10_001,
            |rules: &mut DeclaredRules| rules.exit.max_hold_ms = 0,
            |rules: &mut DeclaredRules| rules.abandon_after_consecutive_failed_polls = 0,
            |rules: &mut DeclaredRules| rules.entry = EntryRule::MicrodipBps { trigger_bps: 0 },
            |rules: &mut DeclaredRules| rules.entry = EntryRule::BreakoutBps { trigger_bps: 0 },
            |rules: &mut DeclaredRules| {
                rules.entry = EntryRule::BreakoutBps {
                    trigger_bps: 10_001,
                };
            },
        ] {
            let mut declaration = opening(EntryRule::Immediate, DeclaredFixedCosts::none("test"));
            degenerate(&mut declaration.rules);
            assert_eq!(
                PaperDeskV1::open(declaration).err(),
                Some(PaperError::DegenerateRule)
            );
        }
    }

    #[test]
    fn an_immediate_entry_and_a_lifted_state_close_at_take_profit_with_exact_arithmetic() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::Immediate);
        let step = desk
            .on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        assert_eq!(step, DeskStep::Entered);

        // Reproduce the walk the desk must have taken, with the same arithmetic.
        let buy = state.buy_with_quote_in(CLIP_ATOMS).expect("entry quotes");
        // Other participants buy 100 SOL, walked through the deployed formula.
        let lifted = buy
            .next
            .buy_with_quote_in(100_000_000_000)
            .expect("inflow quotes")
            .next;
        let sold = lifted
            .sell_base_in(buy.base_out_atoms)
            .expect("exit quotes");
        let expected_net = i128::try_from(sold.quote_out_atoms).expect("fits")
            - i128::try_from(buy.quote_in_atoms).expect("fits");
        let expected_bps =
            (expected_net * 10_000).div_euclid(i128::try_from(buy.quote_in_atoms).expect("fits"));
        assert!(expected_bps >= 100, "the scripted lift clears take-profit");

        let step = desk
            .on_observed_poll(&polled(lifted, 101, OPENED_AT_MS + 6_000))
            .expect("poll");
        assert_eq!(
            step,
            DeskStep::Exited {
                rule: ExitRuleName::TakeProfit
            }
        );
        let episode = desk.finish(OPENED_AT_MS + 6_500).expect("finished");
        assert_eq!(
            episode.outcome,
            EpisodeOutcome::Closed {
                rule: ExitRuleName::TakeProfit
            }
        );
        let pnl = episode.would_pnl.expect("would-pnl exists");
        assert_eq!(pnl.entry_quote_in_atoms, buy.quote_in_atoms);
        assert_eq!(pnl.exit_quote_out_atoms, sold.quote_out_atoms);
        assert_eq!(pnl.net_quote_atoms, expected_net);
        assert_eq!(pnl.net_of_all_in_cost_bps, expected_bps);
        assert_eq!(pnl.declared_fixed_cost_atoms, 0);
        assert_eq!(pnl.venue_only_net_quote_atoms, expected_net);
        assert_eq!(episode.intents.len(), 2);
        let entry_quote = episode.intents[0].quote.as_ref().expect("entry quoted");
        assert_eq!(entry_quote.provenance.context_slot, 100);
        assert_eq!(entry_quote.price_object, PriceObject::ExactSizeQuote);
        let exit_quote = episode.intents[1].quote.as_ref().expect("exit quoted");
        assert_eq!(exit_quote.provenance.context_slot, 101);
        assert_eq!(exit_quote.arithmetic, ARITHMETIC_PROVENANCE);
    }

    #[test]
    fn declared_fixed_costs_reduce_the_net_and_the_venue_only_control_states_them() {
        let costs = DeclaredFixedCosts {
            provenance: "test: 7422 lamports per transaction, two transactions".to_owned(),
            per_transaction_quote_atoms: 7_422,
            transactions: 2,
            flat_route_quote_atoms: 0,
            unrecovered_rent_quote_atoms: 0,
        };
        let mut desk = PaperDeskV1::open(opening(EntryRule::Immediate, costs)).expect("opens");
        let state = deep_pool();
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        let buy = state.buy_with_quote_in(CLIP_ATOMS).expect("entry quotes");
        let lifted = buy
            .next
            .buy_with_quote_in(100_000_000_000)
            .expect("inflow quotes")
            .next;
        desk.on_observed_poll(&polled(lifted, 101, OPENED_AT_MS + 6_000))
            .expect("poll");
        let episode = desk.finish(OPENED_AT_MS + 6_500).expect("finished");
        let pnl = episode.would_pnl.expect("would-pnl exists");
        assert_eq!(pnl.declared_fixed_cost_atoms, 14_844);
        assert_eq!(pnl.venue_only_net_quote_atoms - pnl.net_quote_atoms, 14_844);
    }

    #[test]
    fn a_microdip_entry_waits_through_a_partial_dip_and_enters_at_the_triggering_state() {
        let mut desk = desk(EntryRule::MicrodipBps { trigger_bps: 150 });
        let reference = deep_pool();
        // Poll 0 sets the reference and cannot enter.
        assert_eq!(
            desk.on_observed_poll(&polled(reference, 100, OPENED_AT_MS + 1_000))
                .expect("poll"),
            DeskStep::AwaitingEntry
        );
        // A dip of about 100 bps: others sell, walked through the deployed formula.
        let shallow = reference
            .sell_base_in(3_400_000_000_000)
            .expect("walk")
            .next;
        assert_eq!(
            desk.on_observed_poll(&polled(shallow, 101, OPENED_AT_MS + 6_000))
                .expect("poll"),
            DeskStep::AwaitingEntry
        );
        // A dip past 150 bps triggers, and the entry is quoted at THIS state, not the reference.
        let deep = reference
            .sell_base_in(9_000_000_000_000)
            .expect("walk")
            .next;
        assert_eq!(
            desk.on_observed_poll(&polled(deep, 102, OPENED_AT_MS + 11_000))
                .expect("poll"),
            DeskStep::Entered
        );
        let expected = deep.buy_with_quote_in(CLIP_ATOMS).expect("quotes");
        let episode = {
            let mut desk = desk;
            desk.abandon("test ends here");
            desk.finish(OPENED_AT_MS + 12_000).expect("finished")
        };
        let entry = &episode.intents[0];
        let quote = entry.quote.as_ref().expect("entry quoted");
        assert_eq!(quote.provenance.context_slot, 102);
        assert_eq!(quote.quote_atoms, expected.quote_in_atoms);
        assert_eq!(quote.base_atoms, expected.base_out_atoms);
        assert!(entry.trigger.observed.contains("against the reference"));
    }

    #[test]
    fn a_breakout_entry_waits_through_a_partial_rise_and_enters_at_the_triggering_state() {
        let mut desk = desk(EntryRule::BreakoutBps { trigger_bps: 150 });
        let reference = deep_pool();
        // Poll 0 sets the reference and cannot enter.
        assert_eq!(
            desk.on_observed_poll(&polled(reference, 100, OPENED_AT_MS + 1_000))
                .expect("poll"),
            DeskStep::AwaitingEntry
        );
        // A rise of well under 150 bps: others buy, walked through the deployed formula.
        let shallow = reference
            .buy_with_quote_in(3_400_000_000)
            .expect("walk")
            .next;
        assert_eq!(
            desk.on_observed_poll(&polled(shallow, 101, OPENED_AT_MS + 6_000))
                .expect("poll"),
            DeskStep::AwaitingEntry
        );
        // A rise past 150 bps triggers, and the entry is quoted at THIS state, not the reference.
        let lifted = reference
            .buy_with_quote_in(90_000_000_000)
            .expect("walk")
            .next;
        assert_eq!(
            desk.on_observed_poll(&polled(lifted, 102, OPENED_AT_MS + 11_000))
                .expect("poll"),
            DeskStep::Entered
        );
        let expected = lifted.buy_with_quote_in(CLIP_ATOMS).expect("quotes");
        let episode = {
            let mut desk = desk;
            desk.abandon("test ends here");
            desk.finish(OPENED_AT_MS + 12_000).expect("finished")
        };
        let entry = &episode.intents[0];
        assert!(entry.trigger.rule_verbatim.contains("breakout"));
        assert!(entry.trigger.observed.contains("rise of"));
        let quote = entry.quote.as_ref().expect("entry quoted");
        assert_eq!(quote.provenance.context_slot, 102);
        assert_eq!(quote.quote_atoms, expected.quote_in_atoms);
        assert_eq!(quote.base_atoms, expected.base_out_atoms);
        // The waiting poll recorded the partial rise, and never a dip.
        let PollKind::Observed { evaluation, .. } = &episode.polls[1].kind else {
            panic!("expected an observed poll");
        };
        let PollEvaluation::AwaitingEntry { dip_bps, rise_bps } = evaluation else {
            panic!("expected an awaiting-entry evaluation");
        };
        assert_eq!(*dip_bps, None);
        let rise = rise_bps.expect("a partial rise was observed");
        assert!(rise > 0 && rise < 150, "partial rise, under the trigger");
    }

    #[test]
    fn a_price_under_the_reference_never_triggers_a_breakout() {
        let mut desk = desk(EntryRule::BreakoutBps { trigger_bps: 1 });
        let reference = deep_pool();
        desk.on_observed_poll(&polled(reference, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        let dipped = reference
            .sell_base_in(9_000_000_000_000)
            .expect("walk")
            .next;
        assert_eq!(
            desk.on_observed_poll(&polled(dipped, 101, OPENED_AT_MS + 6_000))
                .expect("poll"),
            DeskStep::AwaitingEntry
        );
        desk.abandon("test ends here");
        let episode = desk.finish(OPENED_AT_MS + 7_000).expect("finished");
        let PollKind::Observed { evaluation, .. } = &episode.polls[1].kind else {
            panic!("expected an observed poll");
        };
        assert_eq!(
            *evaluation,
            PollEvaluation::AwaitingEntry {
                dip_bps: None,
                rise_bps: Some(0),
            }
        );
    }

    #[test]
    fn the_stop_names_the_exit_when_stop_and_max_hold_cross_at_the_same_poll() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::Immediate);
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        let buy = state.buy_with_quote_in(CLIP_ATOMS).expect("entry quotes");
        // Others dump hard; the poll also lands past the declared max hold.
        let dumped = buy
            .next
            .sell_base_in(50_000_000_000_000)
            .expect("walk")
            .next;
        let step = desk
            .on_observed_poll(&polled(dumped, 200, OPENED_AT_MS + 700_000))
            .expect("poll");
        assert_eq!(
            step,
            DeskStep::Exited {
                rule: ExitRuleName::StopLoss
            }
        );
        let episode = desk.finish(OPENED_AT_MS + 700_500).expect("finished");
        assert_eq!(
            episode.outcome,
            EpisodeOutcome::Closed {
                rule: ExitRuleName::StopLoss
            }
        );
        let pnl = episode.would_pnl.expect("a stop still has an exit quote");
        assert!(pnl.net_of_all_in_cost_bps <= -300);
    }

    #[test]
    fn the_entry_deadline_passes_before_a_trigger_and_nothing_enters() {
        let mut desk = desk(EntryRule::MicrodipBps { trigger_bps: 9_000 });
        let state = deep_pool();
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        desk.on_observed_poll(&polled(state, 101, OPENED_AT_MS + 30_000))
            .expect("poll");
        let step = desk
            .on_observed_poll(&polled(state, 102, OPENED_AT_MS + 61_000))
            .expect("poll");
        assert_eq!(step, DeskStep::NeverEntered);
        let episode = desk.finish(OPENED_AT_MS + 61_500).expect("finished");
        let EpisodeOutcome::NeverEntered { reason } = &episode.outcome else {
            panic!("expected never-entered, got {:?}", episode.outcome);
        };
        assert!(reason.contains("entry deadline"));
        assert!(episode.would_pnl.is_none());
        assert!(episode.intents.is_empty());
        let json: serde_json::Value =
            serde_json::from_str(&episode.render_json()).expect("valid json");
        assert_eq!(json["wouldPnl"]["status"], "absent");
        assert!(
            json["wouldPnl"]["because"]
                .as_str()
                .expect("stated")
                .contains("no paper position was ever open")
        );
    }

    #[test]
    fn consecutive_failed_polls_abandon_with_an_explicitly_absent_would_pnl() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::Immediate);
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        assert_eq!(
            desk.on_failed_poll(OPENED_AT_MS + 6_000, "provider timeout")
                .expect("recorded"),
            DeskStep::Holding {
                net_of_all_in_cost_bps: None
            }
        );
        desk.on_failed_poll(OPENED_AT_MS + 11_000, "provider timeout")
            .expect("recorded");
        assert_eq!(
            desk.on_failed_poll(OPENED_AT_MS + 16_000, "provider timeout")
                .expect("recorded"),
            DeskStep::Abandoned
        );
        assert!(desk.is_closed());
        let episode = desk.finish(OPENED_AT_MS + 16_500).expect("finished");
        assert!(episode.would_pnl.is_none());
        let EpisodeOutcome::Abandoned {
            would_pnl_absent_because,
            ..
        } = &episode.outcome
        else {
            panic!("expected abandonment, got {:?}", episode.outcome);
        };
        assert!(would_pnl_absent_because.contains("fabricated"));
        assert_eq!(episode.falsifiers.refused_poll_count, 3);
    }

    #[test]
    fn a_refused_entry_quote_never_enters_and_records_the_refusal_verbatim() {
        // A clip the pool turns into zero base atoms: the walk refuses, and the desk records
        // the refusal instead of entering with any substitute number.
        let mut declaration = opening(EntryRule::Immediate, DeclaredFixedCosts::none("test"));
        declaration.declared_clip_quote_atoms = 1_000;
        let mut desk = PaperDeskV1::open(declaration).expect("opens");
        let state = pool_state(1_000, 1_000_000_000);
        let step = desk
            .on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        assert_eq!(step, DeskStep::NeverEntered);
        let episode = desk.finish(OPENED_AT_MS + 1_500).expect("finished");
        assert_eq!(episode.intents.len(), 1);
        assert!(episode.intents[0].quote.is_err());
        let json: serde_json::Value =
            serde_json::from_str(&episode.render_json()).expect("valid json");
        assert_eq!(json["intents"][0]["wouldQuote"]["status"], "refused");
    }

    #[test]
    fn a_slot_going_backwards_is_a_recorded_refusal_not_an_evaluation() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::MicrodipBps { trigger_bps: 150 });
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        let step = desk
            .on_observed_poll(&polled(state, 90, OPENED_AT_MS + 6_000))
            .expect("poll");
        assert_eq!(step, DeskStep::AwaitingEntry);
        desk.abandon("test ends here");
        let episode = desk.finish(OPENED_AT_MS + 7_000).expect("finished");
        let PollKind::Refused { reason } = &episode.polls[1].kind else {
            panic!("expected a recorded refusal");
        };
        assert!(reason.contains("went backwards"));
    }

    #[test]
    fn a_state_that_refuses_valuation_is_recorded_and_counts_toward_abandonment() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::Immediate);
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        // A reserve so large the sell walk overflows: the valuation refuses and is recorded.
        let absurd = pool_state(u128::MAX - 1, 1_500_000_000_000);
        let step = desk
            .on_observed_poll(&polled(absurd, 101, OPENED_AT_MS + 6_000))
            .expect("poll");
        assert_eq!(
            step,
            DeskStep::Holding {
                net_of_all_in_cost_bps: None
            }
        );
        desk.abandon("test ends here");
        let episode = desk.finish(OPENED_AT_MS + 7_000).expect("finished");
        let PollKind::Observed { evaluation, .. } = &episode.polls[1].kind else {
            panic!("expected an observed poll");
        };
        assert!(matches!(
            evaluation,
            PollEvaluation::ValuationRefused { .. }
        ));
    }

    #[test]
    fn the_largest_poll_gap_is_measured_and_written_into_the_blindness_sentence() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::MicrodipBps { trigger_bps: 9_000 });
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        desk.on_observed_poll(&polled(state, 101, OPENED_AT_MS + 9_000))
            .expect("poll");
        desk.on_observed_poll(&polled(state, 102, OPENED_AT_MS + 10_000))
            .expect("poll");
        desk.abandon("test ends here");
        let episode = desk.finish(OPENED_AT_MS + 10_500).expect("finished");
        assert_eq!(episode.falsifiers.largest_observed_gap_ms, Some(8_000));
        assert!(episode.falsifiers.blindness.contains("8000 ms"));
        assert!(
            episode
                .falsifiers
                .blindness
                .contains("not a guaranteed price")
        );
    }

    #[test]
    fn finish_refuses_an_episode_that_never_reached_an_outcome() {
        let mut desk = desk(EntryRule::MicrodipBps { trigger_bps: 150 });
        desk.on_observed_poll(&polled(deep_pool(), 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        assert_eq!(
            desk.finish(OPENED_AT_MS + 2_000).err(),
            Some(PaperError::EpisodeStillOpen)
        );
    }

    #[test]
    fn attach_chain_second_fills_only_clocks_that_were_not_requested() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::Immediate);
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        let attached = desk.attach_chain_second(ChainSecond {
            slot: 100,
            block_time_unix_s: (OPENED_AT_MS / 1_000) - 12,
        });
        // The poll record and the entry intent's provenance both carry slot 100.
        assert_eq!(attached, 2);
        assert_eq!(
            desk.attach_chain_second(ChainSecond {
                slot: 100,
                block_time_unix_s: 0,
            }),
            0,
            "a stated clock is never overwritten"
        );
        desk.abandon("test ends here");
        let episode = desk.finish(OPENED_AT_MS + 2_000).expect("finished");
        let age = episode
            .falsifiers
            .entry_chain_to_receipt
            .expect("entry age measurable once the clock is attached");
        assert!(age.earliest_ms > 0);
        assert_eq!(age.latest_ms - age.earliest_ms, 1_000);
    }

    fn assert_no_bare_numbers(value: &serde_json::Value, path: &str) {
        match value {
            serde_json::Value::Number(number) => {
                panic!("bare JSON number {number} at {path}; integers must be strings")
            }
            serde_json::Value::Array(items) => {
                for (index, item) in items.iter().enumerate() {
                    assert_no_bare_numbers(item, &format!("{path}[{index}]"));
                }
            }
            serde_json::Value::Object(fields) => {
                for (key, item) in fields {
                    assert_no_bare_numbers(item, &format!("{path}.{key}"));
                }
            }
            _ => {}
        }
    }

    #[test]
    fn the_rendered_episode_carries_no_bare_json_number_and_leads_with_honesty() {
        let state = deep_pool();
        let mut desk = desk(EntryRule::Immediate);
        desk.on_observed_poll(&polled(state, 100, OPENED_AT_MS + 1_000))
            .expect("poll");
        let buy = state.buy_with_quote_in(CLIP_ATOMS).expect("entry quotes");
        let lifted = buy
            .next
            .buy_with_quote_in(100_000_000_000)
            .expect("inflow quotes")
            .next;
        desk.on_observed_poll(&polled(lifted, 101, OPENED_AT_MS + 6_000))
            .expect("poll");
        let episode = desk.finish(OPENED_AT_MS + 6_500).expect("finished");
        let rendered = episode.render_json();
        let json: serde_json::Value = serde_json::from_str(&rendered).expect("valid json");
        assert_no_bare_numbers(&json, "$");
        assert_eq!(json["contract"], PAPER_EPISODE_CONTRACT);
        assert_eq!(json["authority"], PAPER_EPISODE_AUTHORITY);
        assert_eq!(json["wouldPnl"]["status"], "computed");
        assert_eq!(
            json["wouldPnl"]["unmodeledRisks"]
                .as_array()
                .expect("a list")
                .len(),
            unmodeled_risks().len()
        );
        assert_eq!(
            json["hypothesis"]["operatorWordsVerbatim"],
            "hmm this coin is gonna wiggle for a bit"
        );
        // The headline number and the unmodeled list are adjacent, and the disclaimer precedes
        // the number, in the byte order of the artifact itself.
        let is_at = rendered.find("isArithmeticNotAResult").expect("present");
        let net_at = rendered.find("netOfAllInCostBps").expect("present");
        let risks_at = rendered.find("unmodeledRisks").expect("present");
        assert!(is_at < net_at && net_at < risks_at);
        // The card leads with the contract and states the not-a-result text.
        let card = episode.render_card();
        assert!(card.starts_with("PAPER EPISODE"));
        assert!(card.contains(NOT_A_TRADING_RESULT));
    }
}
