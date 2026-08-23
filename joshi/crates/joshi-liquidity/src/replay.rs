//! Replaying one retained tape through N declared rule variants, side by side.
//!
//! A live paper episode is unrepeatable and comparable to nothing: it happened once, on states
//! nobody can produce again, so no rule can be judged against another rule or against doing
//! nothing. A retained event tape is repeatable. This module feeds one tape's frames to the same
//! [`crate::paper::PaperDeskV1`] the live desk uses — the same declared-rule state machine, the
//! same exact integer walks — once per declared variant, and puts the resulting episodes beside
//! each other in one artifact.
//!
//! What keeps a replay honest, by construction rather than by policy:
//!
//! * **The baseline is unremovable.** [`ReplayPanelV1::build`] constructs "enter at the first
//!   evaluable frame, exit at max hold" itself, from the panel's own shared clock, and no caller
//!   can supply it, replace it, or leave it out. A variant that does not beat that is noise
//!   wearing a parameter, and the comparison is a field of every variant rather than a paragraph
//!   a reader has to assemble.
//! * **A replay cannot satisfy the live desk's declared-before-the-first-poll guard**, because
//!   the tape was recorded before the rules were written. Rather than quietly restating the
//!   declaration instant, this module writes that fact into the hypothesis text of every episode
//!   it opens, from a constant here, and carries the real declaration instant in the panel.
//! * **Every frame is a poll or a recorded refusal.** Nothing is interpolated. A frame that
//!   cannot support a state is a refusal with its reason, and the refusals reach the panel with
//!   their counts.
//! * **The haircut is structural.** Every variant's result carries a drift-based bound derived
//!   from this tape's own inter-event timing and this tape's own measured 30-second drift, and
//!   the verdict field says in words that a result inside the haircut is not a result. The
//!   haircut bounds drift only: landing *failure* is unscoreable from anything this system has,
//!   and no landing probability is invented here.
//! * **The declared state composition is falsified against the tape.**
//!   [`ReserveEvolutionCheck`] walks each consecutive pair of retained states through the same
//!   deployed arithmetic the would-quotes use and asks whether it reproduces the next frame's
//!   stated reserves. A wrong reserve composition or a wrong fee rate does not reproduce them.

use core::fmt::Write as _;

use joshi_market_math::{
    quote::AtomicPrice,
    render::{array, integer, object, quoted},
    stack::{ExactCurveState, ExactRatio},
    would_quote::LocalReceipt,
};
use thiserror::Error;

use crate::{
    paper::{
        ChainClock, DeclaredHypothesis, DeclaredRules, EntryRule, EpisodeOpening, EpisodeOutcome,
        ExitRules, PaperDeskV1, PaperEpisodeV1, PaperError, PollKind, PolledState, StateProvenance,
        VenueBinding, unmodeled_risks,
    },
    readout::FeeRateSource,
    round_trip::{DeclaredFixedCosts, self_round_trip},
};

/// Stable contract of the rendered comparison artifact.
pub const REPLAY_PANEL_CONTRACT: &str = "joshi.liquidity.replay_panel.v1";

/// The only authority a replay holds.
pub const REPLAY_AUTHORITY: &str = "read_only_no_execution";

/// What a panel refuses to be, stated before any number.
pub const NOT_A_BACKTEST: &str = "This panel is arithmetic over bytes a recorder retained, \
executed on rules declared before the replay and after the tape. No order existed at any point; \
nothing was signed, submitted, filled, or could have been. Every number is what the deployed \
integer formulas say a retained state was worth to this clip, and a replay sees only the frames \
the tape retained: every move that began and completed between two frames is invisible, \
including a move through a declared stop. This is not a backtest, not a simulation of execution, \
and not evidence about any future tape.";

/// The disclosure this module writes into the hypothesis of every episode it opens.
///
/// A live episode's hypothesis must be dated before the first poll, and the desk refuses one that
/// is not. A replay structurally cannot satisfy that: the tape was recorded first. Restating the
/// declaration instant silently would make the episode artifact lie to a later reader, so the
/// restatement is disclosed inside the field a reader trusts most, emitted from here.
pub const REPLAY_HYPOTHESIS_DISCLOSURE: &str = " [REPLAY DISCLOSURE, emitted by \
joshi.liquidity.replay_panel.v1 and not by the operator: the words before this bracket are the \
operator's, verbatim. Every rule in this episode was declared AFTER the tape it is replayed \
against was recorded. The live desk's guard — a hypothesis must be dated before the first poll — \
cannot bind on a replay, so this episode's declaration instant is restated as the tape's own \
first retained frame and the real declaration instant is carried in the panel. Nothing here is \
out-of-sample.]";

/// Which price object every number in a panel is, which leg it walked, and what it walked against.
pub const PRICED_FROM: &str = "Every number in this panel is a would-quote of the exact-size \
price object, walked in one of the two legs the deployed instructions take — buy_exact_quote_in \
for an entry, sell_exact_base_in for an exit — through joshi-market-math's exact integer stack in \
the deployed operation order, the same arithmetic the live desk uses. What each walk is against \
is the RESERVE pair the frame states, post-trade, and nothing else. A trade frame also states its \
own solAmount and tokenAmount; those are the RESERVE-DELTA leg, which differs from the trader's \
leg by exactly the pool fee, and no price here is computed from either of them. A frame that \
cannot support such a state is a recorded refusal, never an interpolation, and a rule that fires \
at a state the venue refuses to quote closes the episode with the refusal in it.";

/// Why "declared before the replay" is a much weaker claim than "declared before the first poll".
pub const RULES_ARE_NOT_BLIND: &str = "A live episode's rules are blind: the states they will be \
judged against do not exist yet. A replay's rules are not. The tape already existed when they \
were written, and whoever wrote them may have read its summary, its drawdown, or its whole trace \
first. That is contamination, not a technicality: a rule chosen after seeing the shape of the \
data it will be scored on is fitted whether or not anyone searched. This panel therefore carries \
what its declarer already knew about this tape, in the declarer's own words, and refuses to be \
built without it.";

/// What the desk's `contextSlot` means on a replayed frame.
pub const TAPE_ORDINAL_IS_NOT_A_SLOT: &str = "the contextSlot on every replayed poll is the \
frame's ordinal in the retained tape, not a chain slot: this feed states no slot on any frame. \
The desk's slot-went-backwards check therefore checks tape order, which is monotone by \
construction, and refutes nothing here.";

/// The commitment a replayed state carries.
pub const TAPE_COMMITMENT: &str = "none: a retained websocket trade frame states no commitment \
and no slot, so no commitment can be attributed to the state it supports";

/// Identity of the clock a replayed receipt carries.
pub const TAPE_CLOCK_ID: &str = "retained_tape_receive_instant: the recorder's wall clock at the \
moment the frame finished arriving; there is no monotonic component across a replay and none is \
claimed";

/// How a replay samples, stated because the episode's cadence field cannot say it.
pub const SAMPLING_IS_EVENT_DRIVEN: &str = "a replay is event-driven, not polled: every retained \
frame is exactly one poll, in tape order. The episodes' declaredPollCadenceMs is a floor of 1 ms \
and carries no information; the sampling this replay actually had is the tape's own arrival \
process, whose measured gaps are stated in this panel.";

/// The baseline every panel carries, in words, so it cannot be quietly redefined.
pub const BASELINE_RULE_VERBATIM: &str = "baseline: enter at the first evaluable retained frame \
and exit at the shared max hold. Its take-profit is set to 4,294,967,295 bps and its stop to \
10,000 bps (a total loss) precisely so that neither can fire before the clock does. Every other \
variant is judged against this and against doing nothing.";

/// The name the baseline variant always carries.
pub const BASELINE_NAME: &str = "baseline_immediate_exit_at_max_hold";

/// Study M0's measured state drift on a real pool: 9-10 basis points per 30 seconds. The haircut
/// takes the worse end, and uses this tape's own measured drift instead when that is worse.
pub const M0_DRIFT_BPS_PER_WINDOW: u128 = 10;

/// The window Study M0 measured that drift over.
pub const DRIFT_WINDOW_MS: i64 = 30_000;

/// Chain-to-receipt measured at finalized commitment in Study M0. A real order is decided on a
/// state at least this old and lands at least this long after the decision, once per leg.
pub const M0_CHAIN_TO_RECEIPT_MS: i64 = 12_000;

/// What the haircut does not bound, emitted from here so no caller can shorten it.
#[must_use]
pub fn unmodeled_by_the_haircut() -> [&'static str; 5] {
    [
        "landing failure: the retained corpus structurally contains zero failed transactions, so \
         the landing rate is unknowable from anything this system has. The haircut bounds drift; \
         it invents no landing probability and bounds no landing risk at all",
        "competition: nothing in a replay contends with anyone for the same move, and the tape \
         records the fills of participants who would have been contending",
        "market impact of the replayed clip itself: every would-quote is walked against a state \
         the tape retained, and the tape's later frames do not contain this clip's own trade",
        "frames the recorder never saw: a socket with no replay cursor cannot say whether a gap \
         held one trade or a hundred, and the reserve-evolution check cannot tell a missed frame \
         apart from a wrong declaration",
        "in-sample selection: a panel of N variants over one tape reports the best of N on that \
         tape, which is not evidence that the best of N is better",
    ]
}

/// One retained frame, as the replay sees it.
///
/// The replay builds every state's provenance itself, so no caller can attribute a chain slot, a
/// commitment, or a chain clock to a frame that states none.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TapeFrame {
    /// The frame supports a state the deployed arithmetic can be walked against.
    State {
        /// Ordinal in the retained tape. The tape's only order.
        ordinal: u64,
        /// The recorder's wall clock at receipt. The tape's only time axis.
        receive_unix_ms: i64,
        state: ExactCurveState,
        fee_source: FeeRateSource,
    },
    /// The frame supports no state, and says why. Never interpolated.
    Refused {
        ordinal: u64,
        receive_unix_ms: i64,
        reason: String,
    },
}

impl TapeFrame {
    /// The frame's ordinal in the retained tape.
    #[must_use]
    pub const fn ordinal(&self) -> u64 {
        match *self {
            Self::State { ordinal, .. } | Self::Refused { ordinal, .. } => ordinal,
        }
    }

    /// The recorder's wall clock at receipt.
    #[must_use]
    pub const fn receive_unix_ms(&self) -> i64 {
        match *self {
            Self::State {
                receive_unix_ms, ..
            }
            | Self::Refused {
                receive_unix_ms, ..
            } => receive_unix_ms,
        }
    }

    /// The state this frame supports, when it supports one.
    #[must_use]
    pub const fn state(&self) -> Option<&ExactCurveState> {
        match self {
            Self::State { state, .. } => Some(state),
            Self::Refused { .. } => None,
        }
    }

    fn polled(&self) -> Option<PolledState> {
        match self {
            Self::Refused { .. } => None,
            Self::State {
                ordinal,
                receive_unix_ms,
                state,
                fee_source,
            } => Some(PolledState {
                state: *state,
                fee_source: fee_source.clone(),
                provenance: StateProvenance {
                    context_slot: *ordinal,
                    requested_commitment: TAPE_COMMITMENT.to_owned(),
                    chain: ChainClock::FeedStatesNoClock,
                    local_receipt: LocalReceipt {
                        clock_id: TAPE_CLOCK_ID.to_owned(),
                        monotonic_ns: 0,
                        wall_unix_ms: *receive_unix_ms,
                    },
                },
            }),
        }
    }
}

/// One rule variant, declared before the replay and recorded verbatim.
///
/// The entry rule and the two thresholds are the caller's. The shared clock — max hold, entry
/// deadline, abandonment threshold, cadence — is the panel's, so that a variant cannot win by
/// quietly holding longer than the baseline.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeclaredVariant {
    /// Stable machine name. Must be unique in the panel and must not be the baseline's.
    pub name: String,
    /// Why this variant was declared, in the declarer's own words, before the replay.
    pub declared_because: String,
    pub entry: EntryRule,
    pub take_profit_net_bps: u32,
    pub stop_loss_net_bps: u32,
}

/// Everything one panel needs declared before its first frame is read.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayDeclaration {
    pub panel_id: String,
    /// Identity of the retained tape, as the catalog names it.
    pub tape_id: String,
    /// How the tape was retained and where it was read back from, in the driver's words.
    pub tape_provenance: String,
    /// Digest over exactly the ordered frame bytes this panel replayed.
    pub tape_digest_sha256: String,
    pub mint: String,
    pub venue: VenueBinding,
    /// The operator's words. The replay disclosure is appended to them by this module.
    pub hypothesis: DeclaredHypothesis,
    pub declared_clip_quote_atoms: u128,
    pub costs: DeclaredFixedCosts,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    /// The clock every variant, baseline included, is held to.
    pub shared_max_hold_ms: i64,
    pub shared_entry_deadline_ms: i64,
    pub abandon_after_consecutive_refused_frames: u32,
    /// Every number the replay had to declare that the tape does not state — the fee schedule,
    /// the reserve composition, the creator-fee applicability. Named so a reader can attack them.
    pub stated_but_not_in_the_tape: Vec<String>,
    /// What the declarer already knew about this tape when these rules were written. See
    /// [`RULES_ARE_NOT_BLIND`]; a blank one is refused, because a blank would read as "nothing",
    /// which for a replay is almost never true.
    pub what_was_known_about_this_tape: String,
    /// Whether this panel is a parameter sweep. A sweep is legitimate; presenting one as a
    /// finding is not, so the flag is a field and its consequence is printed.
    pub is_a_sweep: bool,
}

/// The tape's own measured drift, over the same window Study M0 measured its pool over.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TapeDrift {
    pub window_ms: i64,
    pub windows_measured: u32,
    pub windows_unmeasurable: u32,
    pub median_abs_bps: u128,
    pub p90_abs_bps: u128,
    pub max_abs_bps: u128,
}

/// Whether the declared state composition reproduces the tape's own reserve evolution.
///
/// Each consecutive pair of retained states is a trade this replay did not make. Walking the
/// earlier state through the deployed arithmetic by the base amount the pair moved must land on
/// the later state's quote reserve. A wrong reserve composition, a wrong fee rate, or a missed
/// frame breaks it — and the tape alone cannot tell those apart, which is stated rather than
/// resolved.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReserveEvolutionCheck {
    pub consecutive_state_pairs: u32,
    pub sell_pairs: u32,
    pub sell_pairs_reproduced_to_the_atom: u32,
    pub buy_pairs: u32,
    pub buy_pairs_reproduced_within_two_atoms: u32,
    /// Pairs the deployed arithmetic refused outright, and pairs that moved no base at all.
    pub unwalkable_pairs: u32,
    pub worst_quote_error_atoms: u128,
    pub statement: String,
}

/// Everything the panel measured about the tape itself, before any rule was applied.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TapeSummary {
    pub tape_id: String,
    pub provenance: String,
    pub digest_sha256: String,
    pub frame_count: u32,
    pub state_frame_count: u32,
    pub refused_frame_count: u32,
    pub first_receive_unix_ms: i64,
    pub last_receive_unix_ms: i64,
    pub observed_span_ms: i64,
    pub largest_gap_ms: i64,
    pub median_gap_ms: i64,
    pub p90_gap_ms: i64,
    pub drift: TapeDrift,
    pub evolution: ReserveEvolutionCheck,
    /// The venue's own round-trip cost for the declared clip at the first evaluable state, in
    /// basis points, ceiled. The floor every variant's net has to clear before it is anything.
    pub venue_round_trip_floor_bps: Option<u128>,
}

/// The drift bound one variant's result has to clear before it is a result at all.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Haircut {
    /// Basis points of drift per [`DRIFT_WINDOW_MS`], and where that rate came from. A CENTRAL
    /// rate: the typical blind window, not an unlucky one.
    pub drift_bps_per_window: u128,
    pub rate_source: String,
    /// The same, at this tape's ninetieth percentile window instead of its median. A landed order
    /// is not drawn from the middle of that distribution when it is adverse selection that fills
    /// it, so a result that clears the central bound and not this one is not robust.
    pub adverse_drift_bps_per_window: u128,
    /// Blind time around the two decisions that this tape itself measures.
    pub tape_gap_exposure_ms: i64,
    /// Blind time a real order adds on top, once per leg, from Study M0's chain-to-receipt.
    pub landing_delay_exposure_ms: i64,
    pub total_exposure_ms: i64,
    /// The bound, in basis points, ceiled so it errs against the trade.
    pub total_bps: u128,
    /// The same bound at the adverse rate. Always at least [`Self::total_bps`].
    pub adverse_draw_bps: u128,
    /// Whether the tape-gap exposure is measured or only a stated floor, and why.
    pub exposure_statement: String,
}

/// One variant's result and its comparison, computed rather than narrated.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VariantResult {
    pub name: String,
    pub declared_because: String,
    pub rules: DeclaredRules,
    pub episode: PaperEpisodeV1,
    /// The headline, when the episode produced a would-PnL.
    pub net_of_all_in_cost_bps: Option<i128>,
    /// The same net with the declared costs outside the venue put back. A stated control.
    pub venue_only_net_bps: Option<i128>,
    /// Entry and exit intents the rules fired.
    pub trigger_event_count: u32,
    pub evaluated_frame_count: u32,
    pub refused_frame_count: u32,
    /// Every distinct refusal this variant met, with its count, in tape order of first sight.
    pub refusals: Vec<RefusalCount>,
    pub haircut: Haircut,
    pub versus_baseline: Comparison,
}

/// One distinct refusal and how often it happened.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RefusalCount {
    pub reason: String,
    pub count: u32,
}

/// A variant against the baseline and against doing nothing.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Comparison {
    /// This variant *is* the baseline.
    IsTheBaseline,
    /// One of the two episodes produced no would-PnL, so no difference exists to state.
    NotComparable { because: String },
    Measured {
        /// This variant's net minus the baseline's net, in basis points.
        excess_over_baseline_bps: i128,
        /// Against the central drift haircut.
        beats_baseline_outside_haircut: bool,
        /// Against the adverse-draw haircut, which is the one a result has to clear to be robust.
        beats_baseline_outside_adverse_draw: bool,
        beats_doing_nothing_outside_haircut: bool,
        verdict: String,
    },
}

/// Two or more declared variants that produced the same episode on this tape.
///
/// A parameter grid finer than the tape's own price granularity does not describe two strategies;
/// it describes one strategy written down twice. A panel that did not say so would present N rows
/// as N results.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndistinguishableGroup {
    pub names: Vec<String>,
    pub net_of_all_in_cost_bps: Option<i128>,
    pub statement: String,
}

/// N variants over one tape, side by side, with the baseline in the middle of the comparison.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayPanelV1 {
    pub panel_id: String,
    pub mint: String,
    pub venue: VenueBinding,
    /// The operator's words, exactly as declared, without the appended disclosure.
    pub operator_words_verbatim: String,
    pub declared_by: String,
    /// When the rules were really declared, which for a replay is after the tape.
    pub rules_declared_at_unix_ms: i64,
    pub rules_declared_after_tape_closed: bool,
    pub declared_clip_quote_atoms: u128,
    pub costs: DeclaredFixedCosts,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    pub tape: TapeSummary,
    /// Every number this replay had to declare that the tape does not state, named so a reader
    /// can attack them. The fee schedule, the reserve composition, and the creator-fee
    /// applicability all live here.
    pub stated_but_not_in_the_tape: Vec<String>,
    /// What the declarer already knew about this tape when the rules were written.
    pub what_was_known_about_this_tape: String,
    /// Always present, always constructed by [`ReplayPanelV1::build`].
    pub baseline: VariantResult,
    pub variants: Vec<VariantResult>,
    /// Declared variants that this tape could not tell apart, computed rather than narrated.
    pub indistinguishable: Vec<IndistinguishableGroup>,
    pub is_a_sweep: bool,
    pub blindness: String,
    /// The one-line answer, computed from the variants rather than written by a caller.
    pub headline: String,
}

/// Exactly why a panel refused to be built.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ReplayError {
    #[error("the tape holds no frames; an empty read is not an empty tape")]
    EmptyTape,
    #[error("the tape holds no frame that supports a state, so nothing could be replayed")]
    NoEvaluableFrame,
    #[error("the tape's frames are not in nondecreasing receive order at ordinal {ordinal}")]
    TapeOutOfOrder { ordinal: u64 },
    #[error("the tape mixes venue formulas, which one episode cannot be replayed across")]
    MixedFormulas,
    #[error("no variant was declared; a panel of one baseline compares nothing")]
    NoVariants,
    #[error("variant name {name} is declared twice, or collides with the baseline's")]
    DuplicateVariantName { name: String },
    #[error("a declared identity or provenance string is blank")]
    BlankIdentity,
    #[error(
        "the panel does not state what its declarer already knew about this tape; a replay's \
         rules are not blind and a blank there would read as \"nothing\", which is almost never \
         true"
    )]
    PriorKnowledgeNotStated,
    #[error(
        "the shared clock is degenerate: max hold, entry deadline, and the abandonment threshold must be positive"
    )]
    DegenerateSharedClock,
    #[error(transparent)]
    Paper(#[from] PaperError),
}

impl ReplayPanelV1 {
    /// Replays one tape through the unremovable baseline and every declared variant.
    ///
    /// # Errors
    ///
    /// Refuses an empty tape, a tape with no evaluable frame, a tape out of receive order, a
    /// tape mixing venue formulas, an empty or name-colliding variant list, blank identity, and a
    /// degenerate shared clock. Propagates every declaration the paper desk itself refuses.
    #[allow(clippy::too_many_lines)] // One panel, built in the order its parts bind.
    pub fn build(
        declaration: &ReplayDeclaration,
        frames: &[TapeFrame],
        variants: &[DeclaredVariant],
    ) -> Result<Self, ReplayError> {
        if frames.is_empty() {
            return Err(ReplayError::EmptyTape);
        }
        if variants.is_empty() {
            return Err(ReplayError::NoVariants);
        }
        if declaration.panel_id.trim().is_empty()
            || declaration.tape_id.trim().is_empty()
            || declaration.tape_provenance.trim().is_empty()
            || declaration.tape_digest_sha256.trim().is_empty()
        {
            return Err(ReplayError::BlankIdentity);
        }
        if declaration.what_was_known_about_this_tape.trim().is_empty() {
            return Err(ReplayError::PriorKnowledgeNotStated);
        }
        if declaration.shared_max_hold_ms <= 0
            || declaration.shared_entry_deadline_ms <= 0
            || declaration.abandon_after_consecutive_refused_frames == 0
        {
            return Err(ReplayError::DegenerateSharedClock);
        }
        let mut seen: Vec<&str> = vec![BASELINE_NAME];
        for variant in variants {
            if variant.name.trim().is_empty() || seen.contains(&variant.name.as_str()) {
                return Err(ReplayError::DuplicateVariantName {
                    name: variant.name.clone(),
                });
            }
            seen.push(variant.name.as_str());
        }
        let mut previous = frames[0].receive_unix_ms();
        for frame in frames {
            if frame.receive_unix_ms() < previous {
                return Err(ReplayError::TapeOutOfOrder {
                    ordinal: frame.ordinal(),
                });
            }
            previous = frame.receive_unix_ms();
        }
        let states: Vec<(usize, &ExactCurveState)> = frames
            .iter()
            .enumerate()
            .filter_map(|(index, frame)| frame.state().map(|state| (index, state)))
            .collect();
        let Some((_, first_state)) = states.first().copied() else {
            return Err(ReplayError::NoEvaluableFrame);
        };
        if states
            .iter()
            .any(|(_, state)| state.formula != first_state.formula)
        {
            return Err(ReplayError::MixedFormulas);
        }

        let tape = summarise_tape(declaration, frames, &states)?;
        let haircut_rate = haircut_rate(&tape.drift);

        let baseline_rules = DeclaredRules {
            entry: EntryRule::Immediate,
            entry_deadline_ms: declaration.shared_entry_deadline_ms,
            exit: ExitRules {
                take_profit_net_bps: u32::MAX,
                stop_loss_net_bps: 10_000,
                max_hold_ms: declaration.shared_max_hold_ms,
            },
            poll_cadence_ms: 1,
            abandon_after_consecutive_failed_polls: declaration
                .abandon_after_consecutive_refused_frames,
        };
        let baseline_episode =
            replay_one(declaration, frames, BASELINE_NAME, baseline_rules, &tape)?;
        let baseline_net = net_bps(&baseline_episode);
        let baseline = variant_result(
            BASELINE_NAME.to_owned(),
            BASELINE_RULE_VERBATIM.to_owned(),
            baseline_rules,
            baseline_episode,
            frames,
            &haircut_rate,
            &tape,
            Comparison::IsTheBaseline,
        );

        let mut results = Vec::with_capacity(variants.len());
        for variant in variants {
            let rules = DeclaredRules {
                entry: variant.entry,
                entry_deadline_ms: declaration.shared_entry_deadline_ms,
                exit: ExitRules {
                    take_profit_net_bps: variant.take_profit_net_bps,
                    stop_loss_net_bps: variant.stop_loss_net_bps,
                    max_hold_ms: declaration.shared_max_hold_ms,
                },
                poll_cadence_ms: 1,
                abandon_after_consecutive_failed_polls: declaration
                    .abandon_after_consecutive_refused_frames,
            };
            let episode = replay_one(declaration, frames, &variant.name, rules, &tape)?;
            let mut result = variant_result(
                variant.name.clone(),
                variant.declared_because.clone(),
                rules,
                episode,
                frames,
                &haircut_rate,
                &tape,
                Comparison::IsTheBaseline,
            );
            result.versus_baseline = compare(
                result.net_of_all_in_cost_bps,
                baseline_net,
                &result.haircut,
                &baseline.name,
            );
            results.push(result);
        }

        let indistinguishable = indistinguishable(&results);
        let headline = headline(&baseline, &results, declaration.is_a_sweep);
        let blindness = blindness(&tape);
        Ok(Self {
            panel_id: declaration.panel_id.clone(),
            mint: declaration.mint.clone(),
            venue: declaration.venue.clone(),
            operator_words_verbatim: declaration.hypothesis.operator_words_verbatim.clone(),
            declared_by: declaration.hypothesis.declared_by.clone(),
            rules_declared_at_unix_ms: declaration.hypothesis.declared_at_unix_ms,
            rules_declared_after_tape_closed: declaration.hypothesis.declared_at_unix_ms
                > tape.last_receive_unix_ms,
            declared_clip_quote_atoms: declaration.declared_clip_quote_atoms,
            costs: declaration.costs.clone(),
            base_decimals: declaration.base_decimals,
            quote_decimals: declaration.quote_decimals,
            tape,
            stated_but_not_in_the_tape: declaration.stated_but_not_in_the_tape.clone(),
            what_was_known_about_this_tape: declaration.what_was_known_about_this_tape.clone(),
            baseline,
            variants: results,
            indistinguishable,
            is_a_sweep: declaration.is_a_sweep,
            blindness,
            headline,
        })
    }
}

fn replay_one(
    declaration: &ReplayDeclaration,
    frames: &[TapeFrame],
    variant_name: &str,
    rules: DeclaredRules,
    tape: &TapeSummary,
) -> Result<PaperEpisodeV1, PaperError> {
    let opened_at = tape.first_receive_unix_ms;
    let mut words = declaration.hypothesis.operator_words_verbatim.clone();
    words.push_str(REPLAY_HYPOTHESIS_DISCLOSURE);
    let opening = EpisodeOpening {
        episode_id: format!("{}:{variant_name}", declaration.panel_id),
        mint: declaration.mint.clone(),
        venue: declaration.venue.clone(),
        hypothesis: DeclaredHypothesis {
            operator_words_verbatim: words,
            declared_by: declaration.hypothesis.declared_by.clone(),
            declared_at_unix_ms: opened_at,
        },
        declared_clip_quote_atoms: declaration.declared_clip_quote_atoms,
        rules,
        costs: declaration.costs.clone(),
        base_decimals: declaration.base_decimals,
        quote_decimals: declaration.quote_decimals,
        opened_at_unix_ms: opened_at,
    };
    let mut desk = PaperDeskV1::open(opening)?;
    for frame in frames {
        if desk.is_closed() {
            break;
        }
        if let Some(state) = frame.polled() {
            desk.on_observed_poll(&state)?;
        } else {
            let TapeFrame::Refused {
                receive_unix_ms,
                reason,
                ..
            } = frame
            else {
                unreachable!("a frame with no polled state is a refusal");
            };
            desk.on_failed_poll(*receive_unix_ms, reason.clone())?;
        }
    }
    if !desk.is_closed() {
        desk.abandon(format!(
            "the retained tape ended with the paper position still open after {} frames over {} \
             ms; a would-PnL computed from any state outside this tape would be fabricated, so \
             there is none",
            frames.len(),
            tape.observed_span_ms
        ));
    }
    desk.finish(tape.last_receive_unix_ms)
}

fn summarise_tape(
    declaration: &ReplayDeclaration,
    frames: &[TapeFrame],
    states: &[(usize, &ExactCurveState)],
) -> Result<TapeSummary, ReplayError> {
    let first = frames[0].receive_unix_ms();
    let last = frames[frames.len() - 1].receive_unix_ms();
    let mut gaps: Vec<i64> = Vec::with_capacity(frames.len().saturating_sub(1));
    for pair in frames.windows(2) {
        gaps.push(
            pair[1]
                .receive_unix_ms()
                .saturating_sub(pair[0].receive_unix_ms()),
        );
    }
    gaps.sort_unstable();
    let (_, first_state) = states
        .first()
        .copied()
        .ok_or(ReplayError::NoEvaluableFrame)?;
    let floor = self_round_trip(
        first_state,
        declaration.declared_clip_quote_atoms,
        &declaration.costs,
    )
    .ok()
    .and_then(|trip| trip.venue_cost.bps_ceil().ok());
    Ok(TapeSummary {
        tape_id: declaration.tape_id.clone(),
        provenance: declaration.tape_provenance.clone(),
        digest_sha256: declaration.tape_digest_sha256.clone(),
        frame_count: count(frames.len()),
        state_frame_count: count(states.len()),
        refused_frame_count: count(frames.len() - states.len()),
        first_receive_unix_ms: first,
        last_receive_unix_ms: last,
        observed_span_ms: last.saturating_sub(first),
        largest_gap_ms: gaps.last().copied().unwrap_or(0),
        median_gap_ms: quantile(&gaps, 50).unwrap_or(0),
        p90_gap_ms: quantile(&gaps, 90).unwrap_or(0),
        drift: measure_drift(frames, states),
        evolution: check_reserve_evolution(
            &states.iter().map(|(_, state)| **state).collect::<Vec<_>>(),
        ),
        venue_round_trip_floor_bps: floor,
    })
}

/// The tape's own absolute price movement over each [`DRIFT_WINDOW_MS`] window it can support.
fn measure_drift(frames: &[TapeFrame], states: &[(usize, &ExactCurveState)]) -> TapeDrift {
    let mut measured: Vec<u128> = Vec::new();
    let mut unmeasurable = 0_u32;
    let mut ahead = 0_usize;
    for (position, (index, state)) in states.iter().enumerate() {
        let opened = frames[*index].receive_unix_ms();
        if ahead < position {
            ahead = position;
        }
        while ahead < states.len()
            && frames[states[ahead].0]
                .receive_unix_ms()
                .saturating_sub(opened)
                < DRIFT_WINDOW_MS
        {
            ahead += 1;
        }
        if ahead >= states.len() {
            break;
        }
        match (
            state.marginal_pool_price(),
            states[ahead].1.marginal_pool_price(),
        ) {
            (Ok(from), Ok(to)) => match abs_bps_between(from, to) {
                Some(bps) => measured.push(bps),
                None => unmeasurable += 1,
            },
            _ => unmeasurable += 1,
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

/// Walks each consecutive pair of retained states through the deployed arithmetic and asks
/// whether it lands on the next frame's stated quote reserve.
///
/// This is the falsifier for everything a replay had to declare about the state itself: the
/// reserve composition, the fee rates, and the atom grid. A declaration that is wrong does not
/// reproduce the tape's own evolution, and the control — the same tape under a different declared
/// composition — is the way to see that.
#[must_use]
pub fn check_reserve_evolution(states: &[ExactCurveState]) -> ReserveEvolutionCheck {
    let mut sells = 0_u32;
    let mut sells_exact = 0_u32;
    let mut buys = 0_u32;
    let mut buys_close = 0_u32;
    let mut unwalkable = 0_u32;
    let mut worst = 0_u128;
    for pair in states.windows(2) {
        let (previous, next) = (&pair[0], &pair[1]);
        let predicted = match next.base_atoms.cmp(&previous.base_atoms) {
            core::cmp::Ordering::Greater => {
                sells += 1;
                previous
                    .sell_base_in(next.base_atoms - previous.base_atoms)
                    .map(|leg| leg.next.effective_quote_atoms)
            }
            core::cmp::Ordering::Less => {
                buys += 1;
                previous
                    .buy_exact_base_out(previous.base_atoms - next.base_atoms)
                    .map(|leg| leg.next.effective_quote_atoms)
            }
            core::cmp::Ordering::Equal => {
                unwalkable += 1;
                continue;
            }
        };
        let Ok(predicted) = predicted else {
            unwalkable += 1;
            continue;
        };
        let error = predicted.abs_diff(next.effective_quote_atoms);
        worst = worst.max(error);
        if next.base_atoms > previous.base_atoms {
            if error == 0 {
                sells_exact += 1;
            }
        } else if error <= 2 {
            buys_close += 1;
        }
    }
    let statement = format!(
        "the tape states post-trade reserves, and this check proves that reading rather than \
         assuming it: walking each earlier retained state through the deployed operation order \
         by the exact base amount the pair moved reproduced the later state's quote reserve to \
         the atom on {sells_exact} of {sells} sell pairs, and to within two atoms on \
         {buys_close} of {buys} buy pairs — the deployed buy instruction is denominated in quote \
         in and this check walks it in base out, which is a different rounding of the same \
         formula. A pair that does not reproduce is either a wrong declared reserve composition, \
         a wrong declared fee rate, or a trade the recorder never saw, and this tape cannot tell \
         those apart: the feed exposes no replay cursor."
    );
    ReserveEvolutionCheck {
        consecutive_state_pairs: count(states.len().saturating_sub(1)),
        sell_pairs: sells,
        sell_pairs_reproduced_to_the_atom: sells_exact,
        buy_pairs: buys,
        buy_pairs_reproduced_within_two_atoms: buys_close,
        unwalkable_pairs: unwalkable,
        worst_quote_error_atoms: worst,
        statement,
    }
}

/// The two drift rates the haircut uses.
///
/// The central rate is Study M0's measured rate or this tape's own median, whichever is worse;
/// never the smaller of the two. The adverse rate does the same against this tape's p90, because
/// a real order that lands into a blind window is not drawn from the middle of that window's
/// distribution when what fills it is adverse selection.
struct HaircutRates {
    central: u128,
    adverse: u128,
    source: String,
}

fn haircut_rate(drift: &TapeDrift) -> HaircutRates {
    let central = M0_DRIFT_BPS_PER_WINDOW.max(drift.median_abs_bps);
    let adverse = M0_DRIFT_BPS_PER_WINDOW.max(drift.p90_abs_bps);
    let which = if drift.median_abs_bps > M0_DRIFT_BPS_PER_WINDOW {
        "this tape's own drift binds; Study M0's measured rate on a real pool is the smaller of \
         the two here"
    } else {
        "Study M0's measured rate on a real pool binds; this tape's own drift is the smaller of \
         the two here"
    };
    HaircutRates {
        central,
        adverse,
        source: format!(
            "central rate {central} bps and adverse rate {adverse} bps per {} ms. Each is the \
             worse of Study M0's measured {M0_DRIFT_BPS_PER_WINDOW} bps on a real pool and this \
             tape's own absolute price movement over the same window — median {} bps, p90 {} \
             bps, worst {} bps over {} windows — and {which}. The rate is scaled linearly in \
             time from the window it was measured over; for a diffusive price that understates a \
             shorter exposure and overstates a longer one, and the exposure here sits close to \
             the measurement window.",
            drift.window_ms,
            drift.median_abs_bps,
            drift.p90_abs_bps,
            drift.max_abs_bps,
            drift.windows_measured
        ),
    }
}

#[allow(clippy::too_many_arguments)] // Every part of one variant's row, named.
fn variant_result(
    name: String,
    declared_because: String,
    rules: DeclaredRules,
    episode: PaperEpisodeV1,
    frames: &[TapeFrame],
    haircut_rate: &HaircutRates,
    tape: &TapeSummary,
    versus_baseline: Comparison,
) -> VariantResult {
    let net = net_bps(&episode);
    let venue_only = episode.would_pnl.and_then(|pnl| {
        let entry = i128::try_from(pnl.entry_quote_in_atoms).ok()?;
        if entry <= 0 {
            return None;
        }
        pnl.venue_only_net_quote_atoms
            .checked_mul(10_000)
            .map(|value| value.div_euclid(entry))
    });
    let mut refusals: Vec<RefusalCount> = Vec::new();
    let mut note = |reason: &str| match refusals.iter_mut().find(|held| held.reason == reason) {
        Some(held) => held.count += 1,
        None => refusals.push(RefusalCount {
            reason: reason.to_owned(),
            count: 1,
        }),
    };
    for poll in &episode.polls {
        match &poll.kind {
            PollKind::Refused { reason } => note(reason),
            PollKind::Observed { evaluation, .. } => {
                if let crate::paper::PollEvaluation::ValuationRefused { refusal } = evaluation {
                    note(refusal);
                }
            }
        }
    }
    for intent in &episode.intents {
        if let Err(refusal) = &intent.quote {
            note(&refusal.refusal);
        }
    }
    let evaluated = episode
        .polls
        .iter()
        .filter(|poll| matches!(poll.kind, PollKind::Observed { .. }))
        .count();
    let haircut = haircut(&episode, frames, haircut_rate, tape);
    VariantResult {
        name,
        declared_because,
        rules,
        net_of_all_in_cost_bps: net,
        venue_only_net_bps: venue_only,
        trigger_event_count: count(episode.intents.len()),
        evaluated_frame_count: count(evaluated),
        refused_frame_count: episode.falsifiers.refused_poll_count,
        refusals,
        haircut,
        versus_baseline,
        episode,
    }
}

/// Blind time around this variant's two decisions, priced at the declared drift rate.
fn haircut(
    episode: &PaperEpisodeV1,
    frames: &[TapeFrame],
    rate: &HaircutRates,
    tape: &TapeSummary,
) -> Haircut {
    let mut unbounded = 0_u32;
    let mut gap_after = |poll_seq: u32| -> i64 {
        let Some(poll) = episode.polls.iter().find(|poll| poll.seq == poll_seq) else {
            unbounded += 1;
            return tape.largest_gap_ms;
        };
        frames
            .iter()
            .find(|frame| frame.receive_unix_ms() > poll.wall_unix_ms)
            .map_or_else(
                || {
                    unbounded += 1;
                    tape.largest_gap_ms
                },
                |frame| frame.receive_unix_ms().saturating_sub(poll.wall_unix_ms),
            )
    };
    let decisions: i64 = episode
        .intents
        .iter()
        .map(|intent| gap_after(intent.poll_seq))
        .sum();
    let decision_count = episode.intents.len();
    let tape_gap_exposure_ms = if decision_count == 0 {
        tape.largest_gap_ms
    } else {
        decisions
    };
    let exposure_statement = if decision_count == 0 {
        "this variant made no decision on this tape, so there is no blind window around one; the \
         exposure below is the tape's largest observed gap, stated so the row carries a bound \
         rather than a blank, and it bounds nothing about a trade that never happened"
            .to_owned()
    } else if unbounded == 0 {
        format!(
            "measured: each of this variant's {decision_count} decisions had a following \
             retained frame, and the exposure is the sum of those two blind windows"
        )
    } else {
        format!(
            "A FLOOR, NOT A MEASUREMENT: {unbounded} of this variant's {decision_count} \
             decisions sat at the last retained frame, with no following frame at all. The blind \
             window after such a decision is unbounded, and the tape's largest observed gap is \
             substituted as a stated floor. The real haircut on this row is larger than the one \
             printed, by an amount this tape cannot say."
        )
    };
    let legs = i64::from(count(episode.intents.len().max(1)));
    let landing_delay_exposure_ms = M0_CHAIN_TO_RECEIPT_MS.saturating_mul(legs);
    let total_exposure_ms = tape_gap_exposure_ms.saturating_add(landing_delay_exposure_ms);
    let priced = |bps_per_window: u128| {
        u128::try_from(total_exposure_ms.max(0))
            .ok()
            .and_then(|exposure| exposure.checked_mul(bps_per_window))
            .and_then(|numerator| {
                u128::try_from(DRIFT_WINDOW_MS)
                    .ok()
                    .map(|window| numerator.div_ceil(window))
            })
            .unwrap_or(u128::MAX)
    };
    Haircut {
        drift_bps_per_window: rate.central,
        rate_source: rate.source.clone(),
        adverse_drift_bps_per_window: rate.adverse,
        tape_gap_exposure_ms,
        landing_delay_exposure_ms,
        total_exposure_ms,
        total_bps: priced(rate.central),
        adverse_draw_bps: priced(rate.adverse),
        exposure_statement,
    }
}

fn compare(
    variant_net: Option<i128>,
    baseline_net: Option<i128>,
    haircut: &Haircut,
    baseline_name: &str,
) -> Comparison {
    let (Some(variant), Some(baseline)) = (variant_net, baseline_net) else {
        return Comparison::NotComparable {
            because: format!(
                "one of the two episodes produced no would-PnL, so no difference exists to \
                 state: this variant's net is {variant_net:?} and {baseline_name}'s is \
                 {baseline_net:?}. A replay never substitutes a number for a missing exit."
            ),
        };
    };
    let Some(excess) = variant.checked_sub(baseline) else {
        return Comparison::NotComparable {
            because: "the difference between the two nets overflows checked arithmetic".to_owned(),
        };
    };
    let bound = i128::try_from(haircut.total_bps).unwrap_or(i128::MAX);
    let adverse = i128::try_from(haircut.adverse_draw_bps).unwrap_or(i128::MAX);
    let beats_baseline = excess > bound;
    let beats_adverse = excess > adverse;
    let beats_nothing = variant > bound;
    let against_nothing = if beats_nothing {
        format!(
            " Against DOING NOTHING it stands too: its own net of {variant} bps clears the \
             {bound} bps central haircut."
        )
    } else {
        format!(
            " Against DOING NOTHING it does NOT stand: its own net of {variant} bps does not \
             clear the {bound} bps central haircut, so whatever it beat the baseline by, it did \
             not beat not trading at all. A variant can clear a bad baseline and still be nothing."
        )
    };
    let verdict = if beats_baseline && beats_adverse {
        format!(
            "{excess} bps over {baseline_name}, outside both this result's {bound} bps central \
             drift haircut and its {adverse} bps adverse-draw haircut. That clears a DRIFT bound \
             on one tape and nothing else: it is not out of sample, it does not bound landing \
             failure, and it is one of N variants on the tape they were declared against."
        )
    } else if beats_baseline {
        format!(
            "{excess} bps over {baseline_name}, outside the {bound} bps CENTRAL drift haircut \
             but INSIDE the {adverse} bps adverse-draw haircut. This result is not robust: it \
             survives a typical blind window and does not survive an unlucky one, and an order \
             that lands into a blind window is not drawn from the middle of it when adverse \
             selection is what fills it."
        )
    } else if excess > 0 {
        format!(
            "{excess} bps over {baseline_name}, which is INSIDE this result's {bound} bps drift \
             haircut. A result inside the haircut is not a result: the same tape's own measured \
             drift over the blind time around these two decisions can account for all of it."
        )
    } else {
        format!(
            "{excess} bps against {baseline_name}: this variant did not beat the baseline at \
             all, before any haircut is applied."
        )
    };
    Comparison::Measured {
        excess_over_baseline_bps: excess,
        verdict: verdict + &against_nothing,
        beats_baseline_outside_haircut: beats_baseline,
        beats_baseline_outside_adverse_draw: beats_adverse,
        beats_doing_nothing_outside_haircut: beats_nothing,
    }
}

/// What makes two replayed episodes the same behaviour: the same net, at the same decision
/// frames, ending on the same rule.
type EpisodeShape = (Option<i128>, Vec<u32>, String);

/// Groups declared variants whose episodes this tape could not tell apart.
///
/// Two variants are the same behaviour here when they exited on the same rule at the same frames
/// with the same net. That happens whenever the declared thresholds sit closer together than the
/// tape's own price moves between frames, which on a fast pool is most of the time.
fn indistinguishable(variants: &[VariantResult]) -> Vec<IndistinguishableGroup> {
    let key = |variant: &VariantResult| -> EpisodeShape {
        (
            variant.net_of_all_in_cost_bps,
            variant
                .episode
                .intents
                .iter()
                .map(|intent| intent.poll_seq)
                .collect(),
            match &variant.episode.outcome {
                EpisodeOutcome::Closed { rule } => rule.label().to_owned(),
                EpisodeOutcome::NeverEntered { .. } => "never_entered".to_owned(),
                EpisodeOutcome::Abandoned { .. } => "abandoned".to_owned(),
            },
        )
    };
    let mut groups: Vec<(EpisodeShape, Vec<String>)> = Vec::new();
    for variant in variants {
        let this = key(variant);
        if let Some((_, members)) = groups.iter_mut().find(|(held, _)| *held == this) {
            members.push(variant.name.clone());
        } else {
            groups.push((this, vec![variant.name.clone()]));
        }
    }
    groups
        .into_iter()
        .filter(|(_, members)| members.len() > 1)
        .map(|(key, names)| {
            let net = key.0;
            IndistinguishableGroup {
                statement: format!(
                    "{} declared variants produced the same episode on this tape — the same exit \
                     rule at the same frames for the same net. Whatever separates their declared \
                     thresholds is finer than this tape's own price moves between frames, so \
                     these rows are one behaviour written down {} times and not {} results.",
                    names.len(),
                    names.len(),
                    names.len()
                ),
                net_of_all_in_cost_bps: net,
                names,
            }
        })
        .collect()
}

fn headline(baseline: &VariantResult, variants: &[VariantResult], is_a_sweep: bool) -> String {
    let winners: Vec<&str> = variants
        .iter()
        .filter(|variant| {
            matches!(
                variant.versus_baseline,
                Comparison::Measured {
                    beats_baseline_outside_haircut: true,
                    ..
                }
            )
        })
        .map(|variant| variant.name.as_str())
        .collect();
    let robust: Vec<&str> = variants
        .iter()
        .filter(|variant| {
            matches!(
                variant.versus_baseline,
                Comparison::Measured {
                    beats_baseline_outside_adverse_draw: true,
                    ..
                }
            )
        })
        .map(|variant| variant.name.as_str())
        .collect();
    let standing: Vec<&str> = variants
        .iter()
        .filter(|variant| {
            matches!(
                variant.versus_baseline,
                Comparison::Measured {
                    beats_doing_nothing_outside_haircut: true,
                    ..
                }
            )
        })
        .map(|variant| variant.name.as_str())
        .collect();
    let against_nothing = format!(
        " Against DOING NOTHING — a net of zero — {} of {} variants clear their own central \
         haircut{}.",
        standing.len(),
        variants.len(),
        if standing.is_empty() {
            String::new()
        } else {
            format!(": {}", standing.join(", "))
        }
    );
    let baseline_net = baseline.net_of_all_in_cost_bps.map_or_else(
        || "absent".to_owned(),
        |net| format!("{net} bps net of all-in cost"),
    );
    if winners.is_empty() {
        return format!(
            "NO VARIANT BEAT THE BASELINE OUTSIDE ITS HAIRCUT. The baseline — {BASELINE_NAME} — \
             produced {baseline_net}, and not one of the {} declared variants exceeded it by \
             more than its own drift haircut. On this tape, on these rules, none of these \
             strategies is distinguishable from entering immediately and holding to the clock. \
             That is the result.{against_nothing}",
            variants.len()
        );
    }
    let mut sentence = format!(
        "{} of {} declared variants exceeded the baseline ({baseline_net}) by more than their \
         own CENTRAL drift haircut: {}. {} of them also cleared the ADVERSE-DRAW haircut{}. ",
        winners.len(),
        variants.len(),
        winners.join(", "),
        robust.len(),
        if robust.is_empty() {
            ", so not one of these results is robust to an unlucky blind window rather than a \
             typical one"
                .to_owned()
        } else {
            format!(": {}", robust.join(", "))
        }
    );
    if is_a_sweep {
        sentence.push_str(
            "THIS PANEL IS A SWEEP. The best of N variants on the one tape they were declared \
             against is not evidence that the best of N is better; it is the largest of N draws \
             from one sample. Nothing here is out of sample.",
        );
    } else {
        sentence.push_str(
            "This clears a DRIFT bound on one tape. It is in-sample, it bounds no landing risk, \
             and it says nothing about any other tape.",
        );
    }
    sentence.push_str(&against_nothing);
    sentence
}

fn blindness(tape: &TapeSummary) -> String {
    format!(
        "A replay sees only the frames the tape retained. This tape retained {} frames over {} \
         ms, with a median gap of {} ms, a p90 gap of {} ms and a largest gap of {} ms. Every \
         move that began and completed inside a gap is invisible to every variant in this panel, \
         including a move through a declared stop — a stop here is a rule about retained frames, \
         not a guaranteed price. The feed exposes no replay cursor, so nothing can ever say how \
         many trades a gap held. {SAMPLING_IS_EVENT_DRIVEN} {TAPE_ORDINAL_IS_NOT_A_SLOT}",
        tape.frame_count,
        tape.observed_span_ms,
        tape.median_gap_ms,
        tape.p90_gap_ms,
        tape.largest_gap_ms
    )
}

fn net_bps(episode: &PaperEpisodeV1) -> Option<i128> {
    episode.would_pnl.map(|pnl| pnl.net_of_all_in_cost_bps)
}

/// `|a - b| / a` in floored basis points. `None` when the exact ratio cannot be taken.
fn abs_bps_between(from: AtomicPrice, to: AtomicPrice) -> Option<u128> {
    let cross_from = from
        .numerator_quote_atoms()
        .checked_mul(to.denominator_base_atoms())?;
    let cross_to = to
        .numerator_quote_atoms()
        .checked_mul(from.denominator_base_atoms())?;
    ExactRatio::new(cross_from.abs_diff(cross_to), cross_from)
        .ok()?
        .bps_floor()
        .ok()
}

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

// --- rendering ---------------------------------------------------------------------------------

impl ReplayPanelV1 {
    /// Renders the panel as deterministic JSON, every integer a string.
    #[must_use]
    #[allow(clippy::too_many_lines)] // One artifact, rendered in the order it is read.
    pub fn render_json(&self) -> String {
        let mut rows = vec![render_variant(&self.baseline)];
        rows.extend(self.variants.iter().map(render_variant));
        object(&[
            ("contract", quoted(REPLAY_PANEL_CONTRACT)),
            ("schemaVersion", quoted("1")),
            ("authority", quoted(REPLAY_AUTHORITY)),
            ("notABacktest", quoted(NOT_A_BACKTEST)),
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
                    (
                        "rulesDeclaredAfterTapeClosed",
                        if self.rules_declared_after_tape_closed {
                            quoted("true")
                        } else {
                            quoted("false")
                        },
                    ),
                    ("replayDisclosure", quoted(REPLAY_HYPOTHESIS_DISCLOSURE)),
                    (
                        "declaredClipQuoteAtoms",
                        integer(&self.declared_clip_quote_atoms),
                    ),
                    ("costProvenance", quoted(&self.costs.provenance)),
                    ("baseDecimals", integer(&self.base_decimals)),
                    ("quoteDecimals", integer(&self.quote_decimals)),
                    ("rulesAreNotBlind", quoted(RULES_ARE_NOT_BLIND)),
                    (
                        "whatWasKnownAboutThisTapeBeforeDeclaring",
                        quoted(&self.what_was_known_about_this_tape),
                    ),
                    (
                        "isASweep",
                        if self.is_a_sweep {
                            quoted("true")
                        } else {
                            quoted("false")
                        },
                    ),
                ]),
            ),
            ("pricedFrom", quoted(PRICED_FROM)),
            ("tape", render_tape(&self.tape)),
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
            ("baselineRule", quoted(BASELINE_RULE_VERBATIM)),
            ("variants", array(&rows)),
            (
                "indistinguishableVariants",
                array(
                    &self
                        .indistinguishable
                        .iter()
                        .map(|group| {
                            object(&[
                                (
                                    "names",
                                    array(
                                        &group
                                            .names
                                            .iter()
                                            .map(|name| quoted(name))
                                            .collect::<Vec<_>>(),
                                    ),
                                ),
                                (
                                    "netOfAllInCostBps",
                                    group
                                        .net_of_all_in_cost_bps
                                        .map_or_else(|| quoted("absent"), |net| integer(&net)),
                                ),
                                ("statement", quoted(&group.statement)),
                            ])
                        })
                        .collect::<Vec<_>>(),
                ),
            ),
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
        let _ = writeln!(out, "{REPLAY_PANEL_CONTRACT}  {}", self.panel_id);
        let _ = writeln!(out, "mint    {}", self.mint);
        let _ = writeln!(
            out,
            "venue   {} {}",
            self.venue.venue.label(),
            self.venue.venue_account
        );
        let _ = writeln!(
            out,
            "tape    {} frames ({} evaluable, {} refused) over {} ms; gaps median {} / p90 {} / \
             max {} ms",
            self.tape.frame_count,
            self.tape.state_frame_count,
            self.tape.refused_frame_count,
            self.tape.observed_span_ms,
            self.tape.median_gap_ms,
            self.tape.p90_gap_ms,
            self.tape.largest_gap_ms
        );
        let _ = writeln!(out, "digest  {}", self.tape.digest_sha256);
        let _ = writeln!(
            out,
            "drift   over {} ms windows: median {} bps, p90 {} bps, worst {} bps ({} windows)",
            self.tape.drift.window_ms,
            self.tape.drift.median_abs_bps,
            self.tape.drift.p90_abs_bps,
            self.tape.drift.max_abs_bps,
            self.tape.drift.windows_measured
        );
        let _ = writeln!(
            out,
            "evolve  {} of {} sell pairs reproduced to the atom, {} of {} buy pairs within two; \
             worst quote error {} atoms",
            self.tape.evolution.sell_pairs_reproduced_to_the_atom,
            self.tape.evolution.sell_pairs,
            self.tape.evolution.buy_pairs_reproduced_within_two_atoms,
            self.tape.evolution.buy_pairs,
            self.tape.evolution.worst_quote_error_atoms
        );
        let _ = writeln!(
            out,
            "floor   venue round trip on the declared clip at the first retained state: {}",
            self.tape
                .venue_round_trip_floor_bps
                .map_or_else(|| "refused".to_owned(), |bps| format!("{bps} bps"))
        );
        let _ = writeln!(out);
        let _ = writeln!(
            out,
            "{:<38} {:>9} {:>9} {:>11} {:>8} {:>8} {:>7} {:>4}  outcome",
            "variant", "net bps", "venue bps", "vs base", "haircut", "adverse", "trigs", "refs"
        );
        let _ = writeln!(
            out,
            "{:<38} * clears the central drift haircut, ** also clears the adverse-draw haircut",
            ""
        );
        for variant in core::iter::once(&self.baseline).chain(self.variants.iter()) {
            let _ = writeln!(out, "{}", render_row(variant));
        }
        let _ = writeln!(out);
        for variant in core::iter::once(&self.baseline).chain(self.variants.iter()) {
            let _ = writeln!(out, "{:<38} {}", variant.name, variant.declared_because);
            if let Comparison::Measured { verdict, .. }
            | Comparison::NotComparable { because: verdict } = &variant.versus_baseline
            {
                let _ = writeln!(out, "{:<38} {verdict}", "");
            }
            if !variant.haircut.exposure_statement.starts_with("measured") {
                let _ = writeln!(out, "{:<38} {}", "", variant.haircut.exposure_statement);
            }
            for refusal in &variant.refusals {
                let _ = writeln!(
                    out,
                    "{:<38} refusal x{}: {}",
                    "", refusal.count, refusal.reason
                );
            }
        }
        let _ = writeln!(out);
        for group in &self.indistinguishable {
            let _ = writeln!(
                out,
                "SAME      {} :: {}",
                group.names.join(" = "),
                group.statement
            );
        }
        if !self.indistinguishable.is_empty() {
            let _ = writeln!(out);
        }
        let _ = writeln!(out, "HEADLINE  {}", self.headline);
        let _ = writeln!(out);
        let _ = writeln!(out, "not blind     {RULES_ARE_NOT_BLIND}");
        let _ = writeln!(out, "known first   {}", self.what_was_known_about_this_tape);
        for stated in &self.stated_but_not_in_the_tape {
            let _ = writeln!(out, "declared      {stated}");
        }
        let _ = writeln!(out, "priced from   {PRICED_FROM}");
        let _ = writeln!(out, "haircut rate  {}", self.baseline.haircut.rate_source);
        let _ = writeln!(out, "blindness     {}", self.blindness);
        let _ = writeln!(out, "evolution     {}", self.tape.evolution.statement);
        let _ = writeln!(out, "not a backtest {NOT_A_BACKTEST}");
        for risk in unmodeled_by_the_haircut() {
            let _ = writeln!(out, "unmodeled     {risk}");
        }
        out
    }
}

fn render_row(variant: &VariantResult) -> String {
    let outcome = match &variant.episode.outcome {
        EpisodeOutcome::Closed { rule } => rule.label().to_owned(),
        EpisodeOutcome::NeverEntered { .. } => "never_entered".to_owned(),
        EpisodeOutcome::Abandoned { .. } => "abandoned".to_owned(),
    };
    let show =
        |value: Option<i128>| value.map_or_else(|| "absent".to_owned(), |value| format!("{value}"));
    let versus = match &variant.versus_baseline {
        Comparison::IsTheBaseline => "baseline".to_owned(),
        Comparison::NotComparable { .. } => "n/a".to_owned(),
        Comparison::Measured {
            excess_over_baseline_bps,
            beats_baseline_outside_haircut,
            beats_baseline_outside_adverse_draw,
            ..
        } => format!(
            "{excess_over_baseline_bps}{}",
            match (
                *beats_baseline_outside_haircut,
                *beats_baseline_outside_adverse_draw
            ) {
                (true, true) => "**",
                (true, false) => "*",
                _ => "",
            }
        ),
    };
    format!(
        "{:<38} {:>9} {:>9} {:>11} {:>8} {:>8} {:>7} {:>4}  {outcome}",
        variant.name,
        show(variant.net_of_all_in_cost_bps),
        show(variant.venue_only_net_bps),
        versus,
        variant.haircut.total_bps,
        variant.haircut.adverse_draw_bps,
        variant.trigger_event_count,
        variant.refused_frame_count,
    )
}

fn render_tape(tape: &TapeSummary) -> String {
    object(&[
        ("tapeId", quoted(&tape.tape_id)),
        ("provenance", quoted(&tape.provenance)),
        ("digestSha256", quoted(&tape.digest_sha256)),
        ("frameCount", integer(&tape.frame_count)),
        ("stateFrameCount", integer(&tape.state_frame_count)),
        ("refusedFrameCount", integer(&tape.refused_frame_count)),
        ("firstReceiveUnixMs", integer(&tape.first_receive_unix_ms)),
        ("lastReceiveUnixMs", integer(&tape.last_receive_unix_ms)),
        ("observedSpanMs", integer(&tape.observed_span_ms)),
        ("largestGapMs", integer(&tape.largest_gap_ms)),
        ("medianGapMs", integer(&tape.median_gap_ms)),
        ("p90GapMs", integer(&tape.p90_gap_ms)),
        ("clock", quoted(TAPE_CLOCK_ID)),
        ("commitment", quoted(TAPE_COMMITMENT)),
        ("contextSlotMeaning", quoted(TAPE_ORDINAL_IS_NOT_A_SLOT)),
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
            "reserveEvolutionCheck",
            object(&[
                (
                    "consecutiveStatePairs",
                    integer(&tape.evolution.consecutive_state_pairs),
                ),
                ("sellPairs", integer(&tape.evolution.sell_pairs)),
                (
                    "sellPairsReproducedToTheAtom",
                    integer(&tape.evolution.sell_pairs_reproduced_to_the_atom),
                ),
                ("buyPairs", integer(&tape.evolution.buy_pairs)),
                (
                    "buyPairsReproducedWithinTwoAtoms",
                    integer(&tape.evolution.buy_pairs_reproduced_within_two_atoms),
                ),
                ("unwalkablePairs", integer(&tape.evolution.unwalkable_pairs)),
                (
                    "worstQuoteErrorAtoms",
                    integer(&tape.evolution.worst_quote_error_atoms),
                ),
                ("statement", quoted(&tape.evolution.statement)),
            ]),
        ),
        (
            "venueRoundTripFloorBps",
            tape.venue_round_trip_floor_bps
                .map_or_else(|| quoted("refused"), |bps| integer(&bps)),
        ),
    ])
}

fn render_variant(variant: &VariantResult) -> String {
    object(&[
        ("name", quoted(&variant.name)),
        ("declaredBecause", quoted(&variant.declared_because)),
        ("rules", render_rules(&variant.rules)),
        (
            "netOfAllInCostBps",
            variant.net_of_all_in_cost_bps.map_or_else(
                || quoted("absent: this episode produced no would-PnL"),
                |net| integer(&net),
            ),
        ),
        (
            "venueOnlyNetBps",
            variant
                .venue_only_net_bps
                .map_or_else(|| quoted("absent"), |net| integer(&net)),
        ),
        ("triggerEventCount", integer(&variant.trigger_event_count)),
        (
            "evaluatedFrameCount",
            integer(&variant.evaluated_frame_count),
        ),
        ("refusedFrameCount", integer(&variant.refused_frame_count)),
        (
            "refusals",
            array(
                &variant
                    .refusals
                    .iter()
                    .map(|refusal| {
                        object(&[
                            ("reason", quoted(&refusal.reason)),
                            ("count", integer(&refusal.count)),
                        ])
                    })
                    .collect::<Vec<_>>(),
            ),
        ),
        ("haircut", render_haircut(&variant.haircut)),
        (
            "versusBaseline",
            render_comparison(&variant.versus_baseline),
        ),
        ("episode", variant.episode.render_json()),
    ])
}

fn render_rules(rules: &DeclaredRules) -> String {
    let entry = match rules.entry {
        EntryRule::Immediate => quoted("immediate: enter at the first evaluable retained frame"),
        EntryRule::MicrodipBps { trigger_bps } => quoted(&format!(
            "microdip: enter at the first retained frame whose marginal pool price sits at least \
             {trigger_bps} bps under the first retained frame's, floored so a partial dip never \
             triggers"
        )),
    };
    object(&[
        ("entry", entry),
        ("entryDeadlineMs", integer(&rules.entry_deadline_ms)),
        ("takeProfitNetBps", integer(&rules.exit.take_profit_net_bps)),
        ("stopLossNetBps", integer(&rules.exit.stop_loss_net_bps)),
        ("maxHoldMs", integer(&rules.exit.max_hold_ms)),
        ("sampling", quoted(SAMPLING_IS_EVENT_DRIVEN)),
        (
            "abandonAfterConsecutiveRefusedFrames",
            integer(&rules.abandon_after_consecutive_failed_polls),
        ),
    ])
}

fn render_haircut(haircut: &Haircut) -> String {
    object(&[
        ("driftBpsPerWindow", integer(&haircut.drift_bps_per_window)),
        (
            "adverseDriftBpsPerWindow",
            integer(&haircut.adverse_drift_bps_per_window),
        ),
        ("driftWindowMs", integer(&DRIFT_WINDOW_MS)),
        ("rateSource", quoted(&haircut.rate_source)),
        ("tapeGapExposureMs", integer(&haircut.tape_gap_exposure_ms)),
        (
            "landingDelayExposureMs",
            integer(&haircut.landing_delay_exposure_ms),
        ),
        ("totalExposureMs", integer(&haircut.total_exposure_ms)),
        ("totalBps", integer(&haircut.total_bps)),
        ("adverseDrawBps", integer(&haircut.adverse_draw_bps)),
        ("exposureStatement", quoted(&haircut.exposure_statement)),
        (
            "meaning",
            quoted(
                "a result whose margin is inside this bound is not a result: this tape's own \
                 measured drift over the blind time around the two decisions can account for all \
                 of it. The bound prices DRIFT over the gap this tape measured plus Study M0's \
                 measured chain-to-receipt per leg. It does not bound landing failure, which is \
                 unscoreable from a corpus that structurally contains zero failed transactions.",
            ),
        ),
    ])
}

fn render_comparison(comparison: &Comparison) -> String {
    match comparison {
        Comparison::IsTheBaseline => object(&[
            ("status", quoted("is_the_baseline")),
            ("rule", quoted(BASELINE_RULE_VERBATIM)),
        ]),
        Comparison::NotComparable { because } => object(&[
            ("status", quoted("not_comparable")),
            ("because", quoted(because)),
        ]),
        Comparison::Measured {
            excess_over_baseline_bps,
            beats_baseline_outside_haircut,
            beats_baseline_outside_adverse_draw,
            beats_doing_nothing_outside_haircut,
            verdict,
        } => object(&[
            ("status", quoted("measured")),
            ("excessOverBaselineBps", integer(excess_over_baseline_bps)),
            (
                "beatsBaselineOutsideHaircut",
                quoted(if *beats_baseline_outside_haircut {
                    "true"
                } else {
                    "false"
                }),
            ),
            (
                "beatsBaselineOutsideAdverseDraw",
                quoted(if *beats_baseline_outside_adverse_draw {
                    "true"
                } else {
                    "false"
                }),
            ),
            (
                "beatsDoingNothingOutsideHaircut",
                quoted(if *beats_doing_nothing_outside_haircut {
                    "true"
                } else {
                    "false"
                }),
            ),
            ("verdict", quoted(verdict)),
        ]),
    }
}

// --- reconstructing atoms from a feed's decimal literals -----------------------------------------

/// An atom count recovered from a decimal literal a feed stated in whole units.
///
/// A feed that states reserves in whole units rather than atoms has already thrown away whichever
/// digits its own serializer could not hold. Recovering the atom count is a reconstruction, and
/// this type carries how far off the atom grid the literal actually sat rather than hiding it in
/// a rounding.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReconstructedAtoms {
    /// The atom count the literal was rounded to, half away from zero.
    pub atoms: u128,
    /// Distance from the literal to that atom, in millionths of an atom, rounded up. Zero means
    /// the literal named an exact atom count and nothing was reconstructed.
    pub off_grid_micro_atoms: u128,
}

/// Exactly why a decimal literal could not be turned into an atom count.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ReconstructionRefusal {
    #[error("{literal:?} is not a plain decimal literal")]
    NotADecimalLiteral { literal: String },
    #[error("{literal:?} is negative; a reserve is not")]
    Negative { literal: String },
    #[error(
        "{literal:?} carries an exponent; this refuses to reconstruct one rather than guess at \
         what the feed's serializer did to the digits"
    )]
    ExponentNotSupported { literal: String },
    #[error("{literal:?} scaled to {decimals} decimals overflows an atom count")]
    Overflows { literal: String, decimals: u8 },
}

/// Recovers an exact atom count from a decimal literal stated in whole units.
///
/// The literal's own digits are shifted, never its value through a float: a feed's shortest
/// round-trip decimal is the most information the feed ever had, and parsing it as a float and
/// scaling introduces an error this cannot see. Digits past the atom grid are a fact about the
/// feed, not a fact about the venue, so they are reported rather than silently dropped.
///
/// # Errors
///
/// Refuses anything that is not a plain nonnegative decimal literal, refuses exponent notation
/// rather than guessing at it, and refuses a scaled value that overflows an atom count.
pub fn atoms_from_decimal_literal(
    literal: &str,
    decimals: u8,
) -> Result<ReconstructedAtoms, ReconstructionRefusal> {
    let trimmed = literal.trim();
    if trimmed.is_empty() {
        return Err(ReconstructionRefusal::NotADecimalLiteral {
            literal: literal.to_owned(),
        });
    }
    if trimmed.starts_with('-') {
        return Err(ReconstructionRefusal::Negative {
            literal: literal.to_owned(),
        });
    }
    let body = trimmed.strip_prefix('+').unwrap_or(trimmed);
    // Scan in order, so that the first thing wrong with the literal is the thing reported.
    for byte in body.bytes() {
        if byte.is_ascii_digit() || byte == b'.' {
            continue;
        }
        return Err(if byte == b'e' || byte == b'E' {
            ReconstructionRefusal::ExponentNotSupported {
                literal: literal.to_owned(),
            }
        } else {
            ReconstructionRefusal::NotADecimalLiteral {
                literal: literal.to_owned(),
            }
        });
    }
    let (whole, fraction) = match body.split_once('.') {
        Some((whole, fraction)) => (whole, fraction),
        None => (body, ""),
    };
    if whole.is_empty() && fraction.is_empty() {
        return Err(ReconstructionRefusal::NotADecimalLiteral {
            literal: literal.to_owned(),
        });
    }
    if !whole.bytes().all(|byte| byte.is_ascii_digit())
        || !fraction.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(ReconstructionRefusal::NotADecimalLiteral {
            literal: literal.to_owned(),
        });
    }
    let places = usize::from(decimals);
    let mut digits = String::with_capacity(whole.len() + places);
    digits.push_str(whole);
    let remainder = if fraction.len() <= places {
        digits.push_str(fraction);
        for _ in fraction.len()..places {
            digits.push('0');
        }
        ""
    } else {
        digits.push_str(&fraction[..places]);
        &fraction[places..]
    };
    let mut atoms: u128 = digits
        .parse()
        .map_err(|_| ReconstructionRefusal::Overflows {
            literal: literal.to_owned(),
            decimals,
        })?;
    if remainder.is_empty() {
        return Ok(ReconstructedAtoms {
            atoms,
            off_grid_micro_atoms: 0,
        });
    }
    // The remainder is the fraction of one atom the feed's literal sat above the atom below it.
    let mut micro: u128 = 0;
    let mut trailing = false;
    for (place, byte) in remainder.bytes().enumerate() {
        let digit = u128::from(byte - b'0');
        if place < 6 {
            micro = micro * 10 + digit;
        } else if digit != 0 {
            trailing = true;
        }
    }
    for _ in remainder.len()..6 {
        micro *= 10;
    }
    let rounds_up = remainder.as_bytes()[0] >= b'5';
    let off_grid_micro_atoms = if rounds_up {
        1_000_000 - micro
    } else {
        micro + u128::from(trailing)
    };
    if rounds_up {
        atoms = atoms
            .checked_add(1)
            .ok_or_else(|| ReconstructionRefusal::Overflows {
                literal: literal.to_owned(),
                decimals,
            })?;
    }
    Ok(ReconstructedAtoms {
        atoms,
        off_grid_micro_atoms,
    })
}

#[cfg(test)]
mod tests {
    use joshi_market_math::{
        fee::{CreatorFee, FeeBps, FeeSchedule},
        stack::VenueFormula,
    };

    use super::*;
    use crate::readout::VenueKind;

    const OPEN_MS: i64 = 1_787_450_485_000;
    const STEP_MS: i64 = 500;

    fn schedule(lp: u16, protocol: u16, creator: u16) -> FeeSchedule {
        FeeSchedule {
            lp: FeeBps::new(lp).expect("lp"),
            protocol: FeeBps::new(protocol).expect("protocol"),
            creator: CreatorFee::Charged(FeeBps::new(creator).expect("creator")),
        }
    }

    /// Study M0's graduated pool, at the state its fixture recorded.
    fn pool_state() -> ExactCurveState {
        ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms: 11_998_257_118_876,
            effective_quote_atoms: 1_493_137_675_872,
            schedule: schedule(20, 5, 5),
        }
    }

    /// A tape whose every state is the deployed arithmetic's own successor to the state before
    /// it: buys lift the mark for the first stretch, then sells give it back.
    fn evolved_states(steps: usize) -> Vec<ExactCurveState> {
        let mut state = pool_state();
        let mut states = vec![state];
        for step in 0..steps {
            let leg = if step < steps / 2 {
                state
                    .buy_exact_base_out(state.base_atoms / 400)
                    .expect("buy walks")
                    .next
            } else {
                state
                    .sell_base_in(state.base_atoms / 400)
                    .expect("sell walks")
                    .next
            };
            state = leg;
            states.push(state);
        }
        states
    }

    fn frames_from(states: &[ExactCurveState]) -> Vec<TapeFrame> {
        states
            .iter()
            .enumerate()
            .map(|(index, state)| TapeFrame::State {
                ordinal: u64::try_from(index).expect("ordinal fits"),
                receive_unix_ms: OPEN_MS + i64::try_from(index).expect("index fits") * STEP_MS,
                state: *state,
                fee_source: carried(),
            })
            .collect()
    }

    fn carried() -> FeeRateSource {
        FeeRateSource::CarriedFromPriorReading {
            established_by: "a prior reading".to_owned(),
            not_read_here_because: "a replay reads no account".to_owned(),
        }
    }

    fn declaration() -> ReplayDeclaration {
        ReplayDeclaration {
            panel_id: "panel".to_owned(),
            tape_id: "tape".to_owned(),
            tape_provenance: "a reopened catalog".to_owned(),
            tape_digest_sha256: "deadbeef".to_owned(),
            mint: "mint".to_owned(),
            venue: VenueBinding {
                venue: VenueKind::PumpSwapPool,
                venue_account: "pool".to_owned(),
                binding: "the frame states the mint and the pool".to_owned(),
            },
            hypothesis: DeclaredHypothesis {
                operator_words_verbatim: "it dips then rips".to_owned(),
                declared_by: "ember".to_owned(),
                // After the tape, which is what a replay always is.
                declared_at_unix_ms: OPEN_MS + 10_000_000,
            },
            declared_clip_quote_atoms: 50_000_000,
            costs: DeclaredFixedCosts {
                provenance: "a landed fill".to_owned(),
                per_transaction_quote_atoms: 7_422,
                transactions: 2,
                flat_route_quote_atoms: 0,
                unrecovered_rent_quote_atoms: 0,
            },
            base_decimals: 6,
            quote_decimals: 9,
            shared_max_hold_ms: 10_000,
            shared_entry_deadline_ms: 20_000,
            abandon_after_consecutive_refused_frames: 25,
            stated_but_not_in_the_tape: vec!["the fee rates".to_owned()],
            what_was_known_about_this_tape: "this tape is synthetic: every state in it is the \
                                             deployed arithmetic's own successor to the one \
                                             before it, written by this test"
                .to_owned(),
            is_a_sweep: false,
        }
    }

    fn variants() -> Vec<DeclaredVariant> {
        vec![
            DeclaredVariant {
                name: "immediate_tp_60".to_owned(),
                declared_because: "the venue's own floor".to_owned(),
                entry: EntryRule::Immediate,
                take_profit_net_bps: 60,
                stop_loss_net_bps: 300,
            },
            DeclaredVariant {
                name: "microdip_100_tp_100".to_owned(),
                declared_because: "a deep dip".to_owned(),
                entry: EntryRule::MicrodipBps { trigger_bps: 100 },
                take_profit_net_bps: 100,
                stop_loss_net_bps: 300,
            },
        ]
    }

    fn panel() -> ReplayPanelV1 {
        let states = evolved_states(60);
        ReplayPanelV1::build(&declaration(), &frames_from(&states), &variants())
            .expect("the panel builds")
    }

    #[test]
    fn the_baseline_is_built_by_the_panel_and_cannot_be_declared_away() {
        let panel = panel();
        assert_eq!(panel.baseline.name, BASELINE_NAME);
        assert_eq!(panel.baseline.rules.entry, EntryRule::Immediate);
        assert_eq!(panel.baseline.rules.exit.take_profit_net_bps, u32::MAX);
        assert_eq!(panel.baseline.rules.exit.stop_loss_net_bps, 10_000);
        assert_eq!(panel.baseline.rules.exit.max_hold_ms, 10_000);
        assert_eq!(panel.baseline.versus_baseline, Comparison::IsTheBaseline);

        // A caller cannot supply a second baseline under the same name.
        let mut declared = variants();
        declared[0].name = BASELINE_NAME.to_owned();
        let states = evolved_states(20);
        assert!(matches!(
            ReplayPanelV1::build(&declaration(), &frames_from(&states), &declared),
            Err(ReplayError::DuplicateVariantName { .. })
        ));
    }

    #[test]
    fn the_baseline_exits_on_the_clock_and_nothing_else() {
        let panel = panel();
        assert!(
            matches!(
                panel.baseline.episode.outcome,
                EpisodeOutcome::Closed {
                    rule: crate::paper::ExitRuleName::MaxHold
                }
            ),
            "baseline closed as {:?}",
            panel.baseline.episode.outcome
        );
    }

    #[test]
    fn every_verdict_is_the_haircut_comparison_and_not_a_narration() {
        let panel = panel();
        for variant in &panel.variants {
            let Comparison::Measured {
                excess_over_baseline_bps,
                beats_baseline_outside_haircut,
                beats_baseline_outside_adverse_draw,
                beats_doing_nothing_outside_haircut,
                ..
            } = variant.versus_baseline
            else {
                continue;
            };
            let bound = i128::try_from(variant.haircut.total_bps).expect("bound fits");
            let adverse = i128::try_from(variant.haircut.adverse_draw_bps).expect("adverse fits");
            assert!(
                adverse >= bound,
                "the adverse bound is never the looser one"
            );
            assert_eq!(
                beats_baseline_outside_adverse_draw,
                excess_over_baseline_bps > adverse
            );
            assert_eq!(
                beats_baseline_outside_haircut,
                excess_over_baseline_bps > bound,
                "{} claimed {beats_baseline_outside_haircut} at {excess_over_baseline_bps} bps \
                 against a {bound} bps haircut",
                variant.name
            );
            assert_eq!(
                beats_doing_nothing_outside_haircut,
                variant.net_of_all_in_cost_bps.expect("a measured net") > bound
            );
        }
    }

    #[test]
    fn every_measured_verdict_states_the_comparison_against_doing_nothing() {
        let panel = panel();
        assert!(
            panel.headline.contains("Against DOING NOTHING"),
            "{}",
            panel.headline
        );
        for variant in &panel.variants {
            if let Comparison::Measured { verdict, .. } = &variant.versus_baseline {
                assert!(
                    verdict.contains("Against DOING NOTHING"),
                    "{}: {verdict}",
                    variant.name
                );
            }
        }
    }

    #[test]
    fn the_haircut_prices_the_landing_delay_as_well_as_the_tape_gap() {
        let panel = panel();
        let haircut = &panel.baseline.haircut;
        assert_eq!(
            haircut.landing_delay_exposure_ms,
            M0_CHAIN_TO_RECEIPT_MS * 2,
            "one leg in and one leg out"
        );
        assert_eq!(
            haircut.total_exposure_ms,
            haircut.tape_gap_exposure_ms + haircut.landing_delay_exposure_ms
        );
        assert!(haircut.total_bps > 0, "a haircut of nothing is not a bound");
        // Ceiled, so it errs against the trade.
        let expected = u128::try_from(haircut.total_exposure_ms).expect("exposure fits")
            * haircut.drift_bps_per_window;
        assert_eq!(
            haircut.total_bps,
            expected.div_ceil(u128::try_from(DRIFT_WINDOW_MS).expect("window fits"))
        );
    }

    #[test]
    fn the_worse_of_study_m0_and_this_tapes_own_drift_binds() {
        let panel = panel();
        assert!(
            panel.baseline.haircut.drift_bps_per_window
                >= M0_DRIFT_BPS_PER_WINDOW.min(panel.tape.drift.median_abs_bps),
            "the haircut took the smaller rate"
        );
        assert_eq!(
            panel.baseline.haircut.drift_bps_per_window,
            M0_DRIFT_BPS_PER_WINDOW.max(panel.tape.drift.median_abs_bps)
        );
    }

    #[test]
    fn the_replay_disclosure_reaches_every_episode_and_the_operator_words_survive_it() {
        let panel = panel();
        for variant in core::iter::once(&panel.baseline).chain(panel.variants.iter()) {
            let words = &variant.episode.hypothesis.operator_words_verbatim;
            assert!(words.starts_with("it dips then rips"), "{words}");
            assert!(words.ends_with(REPLAY_HYPOTHESIS_DISCLOSURE), "{words}");
        }
        assert_eq!(panel.operator_words_verbatim, "it dips then rips");
        assert!(panel.rules_declared_after_tape_closed);
    }

    #[test]
    fn a_replayed_state_never_claims_a_chain_slot_a_commitment_or_a_clock() {
        let panel = panel();
        for intent in &panel.baseline.episode.intents {
            let quote = intent.quote.as_ref().expect("the venue quoted");
            assert_eq!(quote.provenance.chain, ChainClock::FeedStatesNoClock);
            assert_eq!(quote.provenance.requested_commitment, TAPE_COMMITMENT);
            assert_eq!(quote.provenance.local_receipt.clock_id, TAPE_CLOCK_ID);
            assert_eq!(quote.provenance.local_receipt.monotonic_ns, 0);
            assert_eq!(
                quote.provenance.chain_to_receipt(),
                Ok(None),
                "no chain age is derivable from a tape"
            );
        }
    }

    #[test]
    fn a_refused_frame_reaches_the_panel_as_its_own_reason_and_nothing_is_substituted() {
        let states = evolved_states(30);
        let mut frames = frames_from(&states);
        frames.insert(
            3,
            TapeFrame::Refused {
                ordinal: 999,
                receive_unix_ms: OPEN_MS + 3 * STEP_MS,
                reason: "the frame states pool \"raydium\", whose fee convention is unestablished"
                    .to_owned(),
            },
        );
        let panel = ReplayPanelV1::build(&declaration(), &frames, &variants()).expect("builds");
        assert_eq!(panel.tape.refused_frame_count, 1);
        let found = panel
            .baseline
            .refusals
            .iter()
            .any(|refusal| refusal.reason.contains("raydium"));
        assert!(found, "{:?}", panel.baseline.refusals);
        assert!(panel.baseline.refused_frame_count >= 1);
    }

    #[test]
    fn a_variant_that_never_entered_is_not_comparable_and_says_so() {
        // A microdip far deeper than this tape ever falls never triggers.
        let declared = vec![DeclaredVariant {
            name: "microdip_9000".to_owned(),
            declared_because: "a dip this tape never takes".to_owned(),
            entry: EntryRule::MicrodipBps { trigger_bps: 9_000 },
            take_profit_net_bps: 100,
            stop_loss_net_bps: 300,
        }];
        let states = evolved_states(60);
        let panel =
            ReplayPanelV1::build(&declaration(), &frames_from(&states), &declared).expect("builds");
        let variant = &panel.variants[0];
        assert_eq!(variant.net_of_all_in_cost_bps, None);
        assert!(matches!(
            variant.versus_baseline,
            Comparison::NotComparable { .. }
        ));
        assert!(panel.headline.contains("NO VARIANT BEAT THE BASELINE"));
    }

    #[test]
    fn the_same_tape_and_the_same_rules_render_the_same_bytes() {
        let states = evolved_states(60);
        let frames = frames_from(&states);
        let first = ReplayPanelV1::build(&declaration(), &frames, &variants()).expect("builds");
        let second = ReplayPanelV1::build(&declaration(), &frames, &variants()).expect("builds");
        assert_eq!(first.render_json(), second.render_json());
        assert_eq!(first.render_text(), second.render_text());
        assert_eq!(first, second);
    }

    #[test]
    fn the_panel_renders_parseable_json_carrying_its_refusals_to_state_its_own_limits() {
        let panel = panel();
        let rendered = panel.render_json();
        let value: serde_json::Value = serde_json::from_str(&rendered).expect("valid JSON");
        assert_eq!(value["contract"], REPLAY_PANEL_CONTRACT);
        assert_eq!(value["variants"].as_array().expect("variants").len(), 3);
        assert_eq!(value["variants"][0]["name"], BASELINE_NAME);
        assert_eq!(
            value["unmodeledByTheHaircut"]
                .as_array()
                .expect("the list")
                .len(),
            unmodeled_by_the_haircut().len()
        );
        assert_eq!(
            value["unmodeledRisks"].as_array().expect("the list").len(),
            unmodeled_risks().len()
        );
        assert_eq!(value["declaration"]["rulesDeclaredAfterTapeClosed"], "true");
    }

    #[test]
    fn the_evolution_check_reproduces_a_tape_the_deployed_arithmetic_itself_wrote() {
        let states = evolved_states(60);
        let check = check_reserve_evolution(&states);
        assert_eq!(check.consecutive_state_pairs, 60);
        assert_eq!(check.sell_pairs_reproduced_to_the_atom, check.sell_pairs);
        assert_eq!(
            check.buy_pairs_reproduced_within_two_atoms, check.buy_pairs,
            "the buy leg is walked in base out and differs only in rounding"
        );
        assert!(check.sell_pairs > 0 && check.buy_pairs > 0);
    }

    #[test]
    fn a_wrong_reserve_composition_does_not_reproduce_the_tape() {
        let states = evolved_states(60);
        let control: Vec<ExactCurveState> = states
            .iter()
            .map(|state| ExactCurveState {
                effective_quote_atoms: state.effective_quote_atoms - 17_584_505_288,
                ..*state
            })
            .collect();
        let check = check_reserve_evolution(&control);
        assert_eq!(
            check.sell_pairs_reproduced_to_the_atom, 0,
            "a wrong quote reserve reproduced the evolution anyway, so the check proves nothing"
        );
        assert!(check.worst_quote_error_atoms > 0);
    }

    #[test]
    fn a_tape_out_of_receive_order_an_empty_one_and_a_mixed_one_are_all_refused() {
        assert_eq!(
            ReplayPanelV1::build(&declaration(), &[], &variants()),
            Err(ReplayError::EmptyTape)
        );
        let states = evolved_states(10);
        assert_eq!(
            ReplayPanelV1::build(&declaration(), &frames_from(&states), &[]),
            Err(ReplayError::NoVariants)
        );
        let mut frames = frames_from(&states);
        frames.swap(2, 6);
        assert!(matches!(
            ReplayPanelV1::build(&declaration(), &frames, &variants()),
            Err(ReplayError::TapeOutOfOrder { .. })
        ));
        let mut mixed = frames_from(&states);
        mixed[4] = TapeFrame::State {
            ordinal: 4,
            receive_unix_ms: OPEN_MS + 4 * STEP_MS,
            state: ExactCurveState {
                formula: VenueFormula::PumpBondingCurve,
                base_atoms: 764_844_374_721_589,
                effective_quote_atoms: 42_086_993_781,
                schedule: schedule(0, 95, 30),
            },
            fee_source: carried(),
        };
        assert_eq!(
            ReplayPanelV1::build(&declaration(), &mixed, &variants()),
            Err(ReplayError::MixedFormulas)
        );
        let mut refused_only = declaration();
        refused_only.tape_digest_sha256 = "  ".to_owned();
        assert_eq!(
            ReplayPanelV1::build(&refused_only, &frames_from(&states), &variants()),
            Err(ReplayError::BlankIdentity)
        );
    }

    #[test]
    fn a_panel_that_will_not_say_what_it_already_knew_about_the_tape_is_refused() {
        let mut blind = declaration();
        blind.what_was_known_about_this_tape = "   ".to_owned();
        let states = evolved_states(10);
        assert_eq!(
            ReplayPanelV1::build(&blind, &frames_from(&states), &variants()),
            Err(ReplayError::PriorKnowledgeNotStated)
        );
    }

    #[test]
    fn a_tape_of_nothing_but_refusals_is_refused_rather_than_replayed_against_a_guess() {
        let frames: Vec<TapeFrame> = (0..4_u32)
            .map(|index| TapeFrame::Refused {
                ordinal: u64::from(index),
                receive_unix_ms: OPEN_MS + i64::from(index) * STEP_MS,
                reason: "no reconstructable reserve pair".to_owned(),
            })
            .collect();
        assert_eq!(
            ReplayPanelV1::build(&declaration(), &frames, &variants()),
            Err(ReplayError::NoEvaluableFrame)
        );
    }

    #[test]
    fn a_sweep_says_in_its_own_headline_that_best_of_n_is_not_evidence() {
        let states = evolved_states(60);
        let mut sweeping = declaration();
        sweeping.is_a_sweep = true;
        let panel =
            ReplayPanelV1::build(&sweeping, &frames_from(&states), &variants()).expect("builds");
        if panel.variants.iter().any(|variant| {
            matches!(
                variant.versus_baseline,
                Comparison::Measured {
                    beats_baseline_outside_haircut: true,
                    ..
                }
            )
        }) {
            assert!(
                panel.headline.contains("THIS PANEL IS A SWEEP"),
                "{}",
                panel.headline
            );
        } else {
            assert!(panel.headline.contains("NO VARIANT BEAT THE BASELINE"));
        }
    }

    // --- reconstructing atoms from decimal literals ---------------------------------------------

    #[test]
    fn a_literal_on_the_atom_grid_reconstructs_exactly() {
        // The token-side literal every pump-amm frame of the 2026-08-22 tape stated.
        assert_eq!(
            atoms_from_decimal_literal("1028585269.169778", 6),
            Ok(ReconstructedAtoms {
                atoms: 1_028_585_269_169_778,
                off_grid_micro_atoms: 0
            })
        );
        assert_eq!(
            atoms_from_decimal_literal("1735.639430012", 9),
            Ok(ReconstructedAtoms {
                atoms: 1_735_639_430_012,
                off_grid_micro_atoms: 0
            })
        );
        assert_eq!(
            atoms_from_decimal_literal("7", 9),
            Ok(ReconstructedAtoms {
                atoms: 7_000_000_000,
                off_grid_micro_atoms: 0
            })
        );
    }

    #[test]
    fn a_literal_off_the_atom_grid_is_rounded_and_the_distance_is_reported() {
        // MEASURED 2026-08-22: not one of the eleven bonding-curve frames stated a virtual SOL
        // reserve that sat on the lamport grid, and the worst sat 0.363477 lamports off it.
        assert_eq!(
            atoms_from_decimal_literal("31.295412217970163", 9),
            Ok(ReconstructedAtoms {
                atoms: 31_295_412_218,
                off_grid_micro_atoms: 29_837
            })
        );
        assert_eq!(
            atoms_from_decimal_literal("31.690424707900146", 9),
            Ok(ReconstructedAtoms {
                atoms: 31_690_424_708,
                off_grid_micro_atoms: 99_854
            })
        );
        // Rounding down keeps the distance below it, and a digit past the sixth ceils it.
        assert_eq!(
            atoms_from_decimal_literal("1.0000000001", 9),
            Ok(ReconstructedAtoms {
                atoms: 1_000_000_000,
                off_grid_micro_atoms: 100_000
            })
        );
        // A digit past the sixth of the remainder ceils the reported distance rather than
        // dropping it, so an off-grid literal never reports as on-grid.
        assert_eq!(
            atoms_from_decimal_literal("1.0000000000000001", 9),
            Ok(ReconstructedAtoms {
                atoms: 1_000_000_000,
                off_grid_micro_atoms: 1
            })
        );
    }

    #[test]
    fn what_a_literal_cannot_be_is_refused_rather_than_guessed_at() {
        assert!(matches!(
            atoms_from_decimal_literal("-1.5", 9),
            Err(ReconstructionRefusal::Negative { .. })
        ));
        assert!(matches!(
            atoms_from_decimal_literal("1e-7", 9),
            Err(ReconstructionRefusal::ExponentNotSupported { .. })
        ));
        assert!(matches!(
            atoms_from_decimal_literal("", 9),
            Err(ReconstructionRefusal::NotADecimalLiteral { .. })
        ));
        assert!(matches!(
            atoms_from_decimal_literal("1.2.3", 9),
            Err(ReconstructionRefusal::NotADecimalLiteral { .. })
        ));
        assert!(matches!(
            atoms_from_decimal_literal("nope", 9),
            Err(ReconstructionRefusal::NotADecimalLiteral { .. })
        ));
        assert!(matches!(
            atoms_from_decimal_literal(&"9".repeat(60), 9),
            Err(ReconstructionRefusal::Overflows { .. })
        ));
    }
}
