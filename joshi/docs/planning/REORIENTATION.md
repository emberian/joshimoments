# Reorientation — moving forward from the base we have, not the plan we wrote

Status: historian's proposal, 2026-08-24. Written for Ember and the primary agent to read
together. It proposes; it does not decree. Sources and the list of what was deliberately not
read are at the end. Ember's verbatim words are ground truth over every summary here,
including this one.

The question this answers: the project began as ideation under survival pressure. It now has a
real base — durable evidence catalogs, an honest one-command cockpit, measurement instruments,
a formal microstructure program, and a corpus of measured findings, many of which refuted the
founding assumptions. Where does each founding idea actually stand, what does the base make
possible that the ideation never imagined, and what should the next program be?

---

## 1. The founding ideation, item by item

### 1a. Microdip-scalp automation — "IT'S GOTTA BE REACTIVE AFTER MY DECISION"

Her August spec, verbatim: *"i select coins that the automation will watch for a microdip, buy
it, scalp as soon as a extremely minimal +PnL is taken. IT'S GOTTA BE REACTIVE AFTER MY
DECISION."* And the bottleneck she later clarified (2026-08-22): *"i literally couldn't push
buttons fast enough to capture the opportunity before it scrolled past me."*

**Split verdict — and the split matters.**

- **"After my decision" — KEPT, and strengthened.** Every measurement made without her
  decision in the loop came back null or negative (see 1b-1c and the replay result below).
  Meanwhile the case that the decision point is real got stronger: post-callout dips exist
  (6/6 sampled callouts dipped, median 28%), they live below candle resolution (of 113,859
  mints whose minute candles show no drawdown, 57.7% had one at event resolution; confirmed
  live at 45.16% event-res vs 1.27% candle on our own tape), and the supply of workable
  half-hours is enormous (~34,000 qualifying half-hours/day across the census; the binding
  constraint is attention, not supply). The founding sentence located the value correctly:
  in the handoff from her judgment to a fast reactor.
- **"Extremely minimal +PnL" — REFUTED as written, by arithmetic.** A minimal scalp must
  clear a venue fee floor of 247 bps on the bonding curve or 60-249 bps on a pool depending
  on fee tier row, plus a state-age cost worth two to four minutes of typical drift. "As soon
  as any +PnL exists" is below the floor; it donates. The corrected form is: react to the
  microdip, exit at a lift that clears the *measured* floor for that venue's tier at that
  clip — and her natural 8-20% lifts clear a 0.6-2.5% floor comfortably, so the corrected
  form is still her strategy, just priced.
- **The mechanical automation half without her — REFUTED so far.** Replaying the retained
  tape through five declared strategy variants: **0 of 5, on any coin, cleared its own drift
  haircut against a net of zero.** Nothing beat doing nothing. A +244 bps row sat inside a
  777 bps central haircut (2,132 bps at the adverse draw). Every joshibot mechanical probe
  (board grids, bandits, fixed brackets) found the same null in its own scope.

**Still untested: the composite loop itself.** Study M6 — she nominates, the machine watches,
enters the dip, exits above the floor — has never run, even on paper. That is not a gap in
the founding idea; it is the one experiment the whole base was built to make honest.

### 1b. Callout-following

**REFUTED as direction, with numbers, twice over.** joshibot's callout_edge study (314
callouts, 222 mints, temporal split): buying on a callout returned **-11.9% at 1h and -43.6%
at 8h**, and louder is worse — two or more callers within ten minutes: median **-89.7% at
8h**; caller with >10k followers: -65.8%. The callout feature block scored AUC 0.471
(chance) where free numeric columns scored 0.796, and *adding* callouts to the free columns
lowered the score.

**KEPT as a clock and a discovery surface.** A callout is a t=0 that aligns coins — the first
common origin this project has ever had, which is what makes cross-sectional questions
("what does minute 3 look like across 10,000 coins") askable at all. And the entry-window
pilot says the window after that clock is real: 6/6 sampled callouts dipped below the callout
price (median 28%), and 6/6 clear the fee hurdle entering at the trough versus 2/6 entering
at the callout price. **The edge is in waiting** — which is her loop, not the feed's.
(Honest floor: n=6, occurrence-vs-availability confound unresolved.)

### 1c. Caller quality

**REFUTED in every tested cohort.** Caller identity carried no forward information — in
callout_edge, scrambling who said it *raised* test AUC (24 of 24 draws), and caller
followers correlated *negatively* with 8h return (rho = -0.502, n=101 mints). quality_callers
found the operator's felt "about a dollar per pulse" reproduced exactly as the **median**
(+$1.14 at a 0.1 SOL clip) while the **mean was -$0.19** [CI -$0.375, -$0.008]; across 128
exit brackets x 4 reaction latencies, not one configuration had a positive mean. This
session's live check agreed: callers show no forward edge; leaderboards are retrospective
winner lists.

**Residue worth keeping:** the pump.fun *following feed* fires on the trade itself, seconds
to minutes ahead of every echo channel (Jack's fill led the operator's buy by 5m31s on the
one fully-chained example). As a discovery channel — promoting candidates into her attention,
never authorizing a buy — it remains untested rather than refuted. Two roster accounts were
nominally positive at n=61/69: "the next experiment, not a result."

### 1d. Survival-bot framing

**COMPOSTED, deliberately.** The stop-oriented sentinel was never her management policy —
she said repeatedly: stop selling bags merely because they fall; a five-minute horizon is
absurd; a backstop is not judgment. And SESSION_HISTORY's requirement 12 stands: financial
pressure is not evidence, and the project must never imply essential expenses can be
recovered by scaling a promising backtest. What survives from the survival era is the
*containment* discipline (the untested live SellExecutor is the standing scar: authority
deserves more adversarial testing than dashboards get) and requirement 11: the apparatus
must be able to establish that the composite policy is *negative*, if it is.

### 1e. "Crackle" — corrected by Ember twice

The record, because this is the concept the project most repeatedly got wrong:

1. **Not only dip-then-recover** (corrected 2026-08-21). That was the first example she
   happened to give, and an instrument was built on it twice. Sometimes she enters and it is
   simply going up. The data agrees the correction is structural: on the signature-regime
   axis, ~24% of coins mean-revert strongly and ~42% trend — **a dip-and-recover rule is
   wrong on ~42% of coins; a momentum rule is wrong on ~24%.** Direction-agnostic extraction
   is not a style choice; it is what the market looks like.
2. **An entry-window statement, not a shape** (corrected 2026-08-22). From the moment she
   starts watching — usually right after a callout — there is usually a decent-magnitude dip
   *or other variance* worth considering an entry after. It was never a price pattern; whole-
   lifetime shape studies measured the wrong window.

What is common across crackles is therefore not a shape: it is **moves large enough to clear
cost, at a timescale she can act on, repeating often enough to work the coin more than
once.** One more census finding belongs beside this: her 8-20% band covers only 18% of
workable half-hours (42.6% move more than 20%). **Her band describes her exit discipline,
not the market** — never hard-code it.

### 1f. The operator herself

The founding docs said "screen reader, keyboard-only," an agent believed it, and it shaped
real design before she corrected it (2026-08-23): **Ember is primarily visual and uses a
pointer; she uses a screen reader sometimes.** Both channels must be first-class, and the
corrected S2 measurement table now reflects it — with row 8, hands, outranking everything.

---

## 2. What the base can do that the ideation never imagined

The ideation asked for a bot. What got built is an *epistemology* — and that is worth naming
because it is the actual asset:

- **A window, not a photograph.** `joshi-up` takes a cold machine to a paired cockpit in one
  command; the keeper outlives a terminal and records its own shutdown reason; scenes are
  immutable and the operator chooses when to advance; holds survive feed refreshes that
  pump.fun's own feed forgets. The asymmetry the founding bottleneck implied — *the feed
  forgets, JOSHI retains* — exists, read-only, today.
- **Instruments that cannot flatter.** A replay harness whose do-nothing baseline and drift
  haircut are structurally unremovable; a source audit that answers UNDECIDABLE rather than
  passing by default (107 checks, 34 findings, four previously unknown); a pre-trade readout
  that takes the worse branch of disagreeing fee tables and says so; a paper desk "unable to
  lie by construction"; a selection instrument whose scoring rule was pre-registered before
  touching data, with a fixed-seed random-picker test that must fail to show skill.
- **Selection is provably measurable.** Verified with plain sqlite3: an operator act binds to
  exact scene bytes, and the full candidate list she was choosing among reconstructs from
  those bytes. "She took this one and passed those three" is answerable, durably. Nothing in
  the founding ideation imagined the counterfactual being *recoverable*.
- **A resident.** A jailed Agent SDK inhabitant that pairs like the cockpit and writes
  durable notes; its first act was to report the photograph was six hours stale. The seed of
  the autoscience/living-memory ambition already runs.
- **The corpus, mastered.** 106.6M rows queryable in 30-50ms; a coin's life measured from
  birth (intensity decays t^-1.35; 80% of all accounts a coin will ever touch in 24h arrive
  by minute 5; nearly one in five coins is finished within a second; "goes to zero" is
  mechanical — 83.4% end with >=99.9% of supply back on the curve).
- **The governing corpus.** docs/microstructure/trades_quotes_prices holds the analysis to a
  standard the ideation had no vocabulary for: no universal price, flow as signal and price
  as readout on a curve, both clocks first-class, observed response never causal impact.

**And the honest debit on the same ledger:** the machinery ran ahead of its questions. The
FORMAL_MODEL names six minimum semantic types (MarketObservation, PriceObservation,
SignedFlowEvent, ImpactStudyRow, LiquidityProviderEpisode, OperatorEpisode) and says
*"anything substantially more should be earned by one concrete JOSHI study."* Across 38
crates and 177k lines, **zero of the six exist** — what exists instead is five
registration/receipt ceremony types around "episode" and no type saying what an episode is.
The apparatus grew the paperwork around every concept and never the concept. PILLARS.md made
the same diagnosis from the other side: nine ceilings blocked by one missing edge, counted
nine times. The vertical-slice rule ("a real observation, from a real source, on a rendered
surface, read back after restart") is the standing antidote — keep it.

---

## 3. The honest economics, in one place

- **Fee floors:** bonding curve 247 bps round trip; graduated pool 60 bps *or* 249 bps —
  because "graduated" predicts nothing; the lever is which fee tier row the market cap
  selects. The two PumpSwap tier tables disagree over a wide populated band; the readout
  takes the worse branch, erring against the trade.
- **Clip ceilings at an 8% lift:** 0.81 SOL (~$108) on the curve or a first-tier pool;
  54-58 SOL (~$5,250) on a well-tiered pool. ~50x difference in tradeable clip — venue and
  tier choice is worth more than any execution refinement this project could build. The
  hurdle is U-shaped: below ~0.0003 SOL the network fee eats the trade.
- **State age beats arithmetic:** 11-13s chain-to-receipt at finalized; a pool drifted
  9-10 bps in 30s, so a 60 bps floor is two to four minutes of drift. Commitment depth is a
  priced decision.
- **Nothing mechanical beat doing nothing** (replay, 1a above) — and the parameter grid was
  finer than the tape's price granularity, so five declared strategies were two behaviours.
- **Her lifts clear the floor; her selection is the open question.** 8-20% gross against a
  0.6-2.5% floor leaves real room *if* the entries are as good as they feel. That "if" is
  the least-measured, highest-leverage object in the project: **~110 scored scenes to detect
  skill (~85 at k=8); ~891 to detect an economically meaningful net edge, as a lower bound.**
  Showing she picks well is cheap; showing it is worth trading is ~10x more expensive. And
  the deputy's correction stands: against another coin in the same scene the fee cancels, so
  **strong skill with a negative tradeable edge is a likely real outcome** — she may pick
  the best coin in a room not worth trading — and the instrument says that verdict in words.
- **The old books were often negative** under reconstructed wallet boundaries. That is not a
  verdict on the composite policy (which was never observed), but it is the reason the
  burden of proof sits where it sits.

---

## 4. Drift risks — this project's own recorded failure modes

These are not generic cautions; each one already happened here at least once.

1. **Estimand compression.** Each subagent needs a bounded task, so latent context gets
   compressed into a convenient local target, and the local target quietly becomes the
   strategy (buy-a-callout, hold-five-minutes, one crime signature). Antidote: every lane
   brief traces its estimand back to the composite loop, and lanes return evidence into a
   decision register, not architecture.
2. **Instruments before questions.** 38 crates before one byte of real market data; ceremony
   types without the concept. Antidote: the FORMAL_MODEL's earn-rule and the slice rule.
   New apparatus is admitted by the concrete study that needs it.
3. **Result prose leaking into product.** "Entry prediction is dead," the wiggle/down/up
   vocabulary, study verdicts embedded in glass. Antidote: scoped findings stay scoped;
   ordinary acts stay uninterpreted at capture time (the hold gesture already obeys this).
4. **Overriding her words with the first example she gave.** The dip-then-recover instrument
   was built twice after the correction existed. Antidote: her verbatim corrections live in
   GOAL.md and this file; check new instruments against the *latest* correction, not the
   founding phrasing.
5. **The operator-model mistake.** A wrong line in a doc propagated into design. Antidote:
   claims about Ember are cited to her words with a date, like any other measurement.
6. **False freshness claims.** "The corpus has never been read" was asserted and was false —
   joshibot had ~ten completed studies against those exact bytes. Framing is port-and-
   re-verify, never first contact.
7. **Authority under-tested relative to analysis.** The old live SellExecutor had no direct
   tests on its double-submit path. Standing rule: economic authority stays out until its
   own separately-argued day, and arrives with adversarial testing stronger than anything
   the read paths get.

---

## 5. Proposed forward program

Five thrusts, ranked by my judgment with the argument attached. The ranking principle: **the
base is finished enough that the scarcest input is now Ember's attended time, so the program
should spend engineering to maximize what each hour in the chair yields — and hedge with the
things that are valuable even if every strategy family parks.**

### Thrust A — the attended selection campaign (Ember in the chair). Rank 1.

**Builds on:** joshi-up, the `;` hold gesture, the pre-registered selection instrument, the
candidate finder, the pre-trade readout, the S2 runbook's corrected measurement table.
**Question:** does Ember's selection carry skill, and is it worth trading? This is the one
place current evidence says alpha could live (callers null, mechanics null, strongest corpus
predictor an accounting identity) — and it is the founding premise "I select" finally under
measurement.
**Shape:** regular short sessions — sit down via joshi-up, work the feed as she naturally
would, hold what she'd work, journal in her own words. Each session also feeds the S2
accessibility measurement (row 8: hands) and shakes out the cockpit. At perhaps 10-20 scored
scenes per session, the ~110-scene skill verdict is weeks of casual sitting, not a project.
**Refuted by:** the instrument's own guarantees — a no-shift verdict at ~110 scenes; or the
skill-without-tradeable-edge verdict, which is a *real and useful* outcome (it redirects the
project toward venue/tier selection and away from entry timing).
**Cost:** near-zero engineering (integrate the focus-architecture deputy, then sit). Her
time is the budget; design sessions so the ~891-scene tradeability number is reachable
without burning her out — and say plainly that the first ten holds prove nothing.

### Thrust B — the reactive hand, on paper (close her named bottleneck). Rank 2.

**Builds on:** keeper, hot-lease design (S4), the live event-resolution tape, the paper desk
(would-quotes from M0 arithmetic, unable to lie), cockpit wiring, the M6 study design.
**Question:** her founding sentence, finally tested — after she nominates, can a watcher see
the entry window in time and would the declared react-enter-exit rule clear the measured
floor? This is M6 run as paper episodes: hold → armed watch on that coin's event tape →
entry-window annunciation → auto-opened paper episode with her declared rule, would-PnL
carrying state age, fee tier, and the drift haircut. **No execution authority** — this
produces exactly the evidence a future authority conversation would demand, and nothing else
can produce it.
**Refuted by:** paper episodes that net negative after the haircut even entering at the
trough; or annunciation latency exceeding the window (the dip is minutes-scale post-callout;
the pipeline's 11-13s receipt age must be priced in, and might eat it — that is a finding
either way).
**Cost:** moderate engineering, all on existing parts. The riskiest piece (a per-coin live
subscription with honest gaps) is S4, already specified.

### Thrust C — living memory and portfolio truth (the hedge that is also her ask). Rank 3.

**Builds on:** the exocortex plan (her words: *"'on this day we discussed this about these
charts' should be something that gets stored inside joshi as a sorta evolving journally
exocortex"*), the command ledger that already has every property the journal needs, the
portfolio statement engine (landed; route and rail spec'd), the resident.
**Question:** does living in JOSHI change decisions? The named dollar cost is real — she
held 5.28M SOLVE through a spike she wanted to sell into because nothing was watching, and a
morning's LP analysis lived only in a chat transcript. SESSION_HISTORY requirement 10
licenses this thrust unconditionally: perception, accounting, replay and containment are
valuable **even if every strategy family is parked.** This is also where "portfolio
understanding beyond memecoins" lives: the statement already treats DLMM positions and the
unobservable resting order honestly; the LP-as-inventory-management steer (never answered by
the old fees-vs-hold studies) starts here as *exposure truth first, policy later* (M5's
"useful residue" ordering).
**Refuted by:** disuse — mornings still starting elsewhere, entries written and never read
back. Instrument that honestly: the readback is durable, so "did a past entry ever get
re-read before a related decision" is itself measurable.
**Cost:** small-to-moderate; mostly integrating landed pieces. The resident makes this
compound: it can surface "on this day" recalls without ranking anything (Pillar 7's
restriction stands).

### Thrust D — the entry-window study at scale. Rank 4.

**Builds on:** the authed callout routes (createdAt / peakTimestamp / multiple with the
multiple=1 floor), the corpus's first-trade t=0, the n=6 pilot, the fee-floor readout.
**Question:** across hundreds of callouts, how often does the post-callout window contain a
dip or variance that clears the venue's measured floor at her clip, with what timing
distribution? This is the founding "crackle as entry window" turned into its first real
number — and it directly sharpens Thrust B's trigger design (how long to arm the watch, what
magnitude to wait for).
**Refuted by:** the window failing to clear the floor at scale; or the occurrence-vs-
availability confound proving unresolvable, in which case the study honestly downgrades to
descriptive and the live capture (which retains availability time) becomes the only path.
**Cost:** cheap — bounded requests plus corpus queries; the collection method is proven.

### Thrust E — resident autoscience and regime conditioning. Rank 5, conditional.

**Builds on:** the resident, the regime tag, the signature instrument.
**Why last:** the machinery-before-questions failure mode lives here. Regime persists a few
hundred events ahead and only on worked coins (split-half rho 0.51 there, ~0 pooled; the two
clocks disagree at chance) — a conditioning layer on that is not yet earned. The resident's
current honest jobs are witness and auditor: staleness alarms, source-audit narration,
"on this day" recall for Thrust C. Promote it to proposing studies only when A/B/D generate
questions faster than we can process them — which would be a good problem, and the trigger
should be that felt backlog, not ambition.

**Standing conditions over all five:** no economic authority anywhere; model output does not
influence acquisition, ranking, presentation or action (Pillar 7); requirement 12 — reserves
and a bounded learning-loss budget visible before any later live experiment is even
discussed; and requirement 11 — the program above is explicitly capable of concluding the
composite policy is negative, and that conclusion would be a success of the instrument, not
a failure of the project.

---

## 6. Confidence, and what I did not read

**High confidence** (multiple independent sources, numbers restated from the documents that
measured them): the item-by-item verdicts in §1; the economics in §3; the drift catalog in
§4 (every item cites a recorded incident).

**Medium confidence:** the ranking in §5. It rests on a judgment call — that attended time
is now the scarcest input — which Ember can simply overrule; the thrusts themselves are
grounded, their order is argued taste. Also medium: my joshibot readings — I read eight of
the ~40 RESULT studies (quality_callers, callout_edge, callout_volatility, seasonality,
mean_reversion, llm_filter, unrealized_pnl, and pump_history.py's documentation) and took
GOAL.md's word for the rest having been re-derived and matched.

**Not read, deliberately:** JOSHI_THOUGHT.md (1,398 lines); FORMAL_MODEL.md in full (I read
its closing interface and earn-rule, plus GOAL.md's findings about it); EMPIRICAL_CLAIMS,
CHAPTER_NOTES, BOOK_MAP, GLOSSARY; the wave4/5/6 closeouts and docs/decisions/; the ~32
joshibot studies not listed above; joshibot's JOSHI.md V2 draft (SESSION_HISTORY's account
taken as sufficient); and the raw cv transcripts — her verbatim words quoted here come
through SESSION_HISTORY.md, GOAL.md and EXOCORTEX.md, which are themselves reconciled
records. If any quote matters enough to act on, `cv` can recover the original context.
PLANS-BREADCRUMBS.md, named in my brief, does not exist in the tree.

The one-sentence version of this whole document: **the ideation said "build a bot that
trades like me"; the measurements said "nothing mechanical has an edge and nobody ever
measured *you*"; the base now makes measuring you cheap — so sit in it, hand it your
decisions on paper, and let the instruments say whether the founding hunch was alpha,
discipline, or a story.**
