# Lane 07: estimation and learning from an adaptive human-attended slice

Status: research direction, not an engineering plan or a claim of profitable strategy.

## Executive finding

The central statistical object is not a feature-to-return predictor. It is a changing,
partially observed, sequential policy in which Ember's attention is both:

- a valuable sensor that concentrates expensive inspection on a small part of the market; and
- a non-random sampling mechanism that makes naive comparisons invalid.

The system therefore needs to measure the complete attention funnel and whole episodes before it
tries to learn a rule. A coin can be noticed, inspected, armed, entered, partially exited, watched
while flat, re-entered, promoted to a runner, and eventually zapped. Treating any inventory interval
as an independent position destroys the management policy that this lane is supposed to estimate.

The first useful estimators are deliberately modest: standardized counterfactual replay on matched
choice sets, empirical outcome distributions, transition hazards, and retrieval of past scenes. More
ambitious methods—off-policy evaluation, multimodal models, program synthesis, and hybrid-system
abduction—become credible only after their inputs and support are visible in the tape.

"Model-free" here means **delaying commitment to a predictive family while preserving the evidence
needed to try many families later**. It cannot mean assumption-free. Outcomes, horizons, matching,
price-taker replay, local stationarity, and the meaning of an episode are already models. Those
assumptions must be explicit and sensitivity-tested rather than smuggled into a backtest.

## 1. What the old repository establishes—and what it does not

The old studies are useful compost because they expose several failure modes unusually clearly.
They are not evidence about the newly specified composite policy.

### 1.1 Facts worth retaining

- `studies/RESULT_bandit_search.md` used a 9.99-hour, 30-second board tape with 77,623 rows,
  35,808 board entries, and 8,879 mints. It correctly refused importance weighting because no
  behavior-policy propensities existed.
- That study's 1,944-cell entry search was null on the variables it could see. The selected test
  arm acted on only 26 mints, and the entire tape occupied one market session. This is a valid null
  for that low-dimensional grid in that window, not for Ember's selection process.
- 55.9% of the simulated resolutions in that study were stale-price mark-outs. The earlier
  `RESULT_board_entry.md` had incorrectly read informative censoring as strengthening its result;
  `RESULT_bandit_search.md` corrected it. Disappearance and loss of a live quote are outcomes, not
  harmless censoring.
- The same search found that live-quote-triggered exits were the only exit family not clearly
  negative, but their small advantage disappeared under 1–2% adverse fill. This establishes that
  executable quotes and observation latency can dominate a micro-profit estimand.
- `RESULT_callout_volatility.md` extrapolated 13 hand-selected, under-five-minute operator trades to
  roughly 2,000 mechanical trades per day, while explicitly acknowledging a roughly 240-fold
  selection-at-scale extrapolation. Its mechanical desk's first closes were negative and included a
  stop that armed near -16.5% but filled near -64.7% after a 43-second observation gap. The useful
  result is the failure mode, not either PnL estimate.
- `RESULT_llm_filter.md` showed that repeated board entries were mistakenly treated as independent
  rows before mint-level deduplication, and that the evaluable long-horizon cohort was mostly mature,
  graduated coins rather than fresh launches. Entity grouping and population definition are
  load-bearing.
- `RESULT_unrealized_pnl.md` already uses a fully flat wallet followed by a buy as an accounting
  episode boundary. That is correct for wallet cost basis, but it is too narrow for this project:
  Ember may remain in the same strategic episode while deliberately flat and watching for re-entry.

### 1.2 What was never observed

The old tapes do not reconstruct, at decision time:

- the market universe, candidate ranking, viewport, and alternatives Ember actually saw;
- why Ember opened one graph and ignored another;
- graph watching, intended exit, flat-but-watching intervals, or intended re-entry;
- a partial profit's simultaneous cash-management and thesis-transition meanings;
- whether a retained remainder was deliberate, forgotten, or constrained by execution;
- Ember's contemporaneous disposition, horizon, confidence, or unarticulated uncertainty;
- size-specific executable counterfactual quotes at the moment of most decisions; or
- a stable social scene, identity graph, and raw text/image evidence as known at the time.

No estimator can reconstruct these variables from final wallet transactions. In particular, a
negative result for a mechanical `drawdown × board × depth × clock` rule cannot refute a policy that
uses information eliminated before the rule is evaluated.

### 1.3 A correction to the old OPE conclusion

`shitcoims_replay/ope.py` contains useful fail-closed primitives for IPS, SNIPS, doubly robust
estimation, overlap, and effective sample size. The claim in `RESULT_bandit_search.md` that logging
the desk's propensities would make the methodological problem "dissolve," however, is too strong.

Action propensities help only when:

1. the behavior policy genuinely randomized among the recorded actions conditional on the recorded
   history;
2. every action the target policy might take has support;
3. the reward and follow-up horizon are observed;
4. delayed, sequential decisions are handled as trajectories rather than independent rows;
5. market impact and interference are negligible or modeled; and
6. the conditioning history contains the information that drove the randomized system policy.

Ember's own adaptive attention is not naturally a known randomized policy, and asking a human to
invent a probability after choosing does not create a propensity. System-side exploration can have
known propensities; human judgment generally cannot. Even valid sequential importance ratios can
have catastrophic variance across a long episode. OPE is one instrument, not a substitute for the
market census, matched choice sets, shadow outcomes, or prospective scene capture.

## 2. Formal object and units

At event time \(t\), distinguish:

- \(S_t\): the latent market and social state;
- \(C_t\): the coarse whole-market census available to the system;
- \(B_t\): the product's surfaced candidate set and ordering;
- \(V_t\): what entered Ember's viewport;
- \(O_t\): the high-resolution observation assembled for inspected coins;
- \(H_t\): Ember's internal history, including knowledge and intuitions not necessarily verbalized;
- \(A_t\): a gesture or trading action;
- \(X_t\): the requested quote, submission, landing, fill, and reconciliation outcome;
- \(I_t\): inventory, cash, reserved capital, and outstanding intentions; and
- \(D_t\): the current disposition and thesis state, allowed to be unknown or free-form.

The logging system observes only projections of \(S_t\) and \(H_t\). Its job is to expand those
projections without pretending they are complete.

The primary unit is the **operator episode**: a coin-level interval beginning when a coin becomes a
live object of consideration and ending when Ember explicitly resolves it or an expiry policy closes
the episode. An episode may contain:

- zero or several buys;
- several partial or full sells;
- multiple inventory intervals separated by flat-but-watching intervals;
- disposition changes; and
- allocations of realized cash into other episodes.

We also need three nested units for different questions:

1. **Scene/choice event** for selection and attention.
2. **Decision event** for local action comparisons.
3. **Episode/portfolio path** for realized value and sequential management.

Rows from the same mint, person/narrative family, episode, and time block are dependent. Resampling
or splits must respect all relevant levels; treating board re-entries as IID is specifically
forbidden.

## 3. Outcome and value semantics

For a candidate coin \(c\), decision time \(t\), size \(q\), horizon \(h\), and fully specified
management policy \(\pi\), define

\[
G(c,t,q,h;\pi)
\]

as the net change in marked wealth under **size-specific executable** buys and sells, including
dynamic venue fees, price impact, network costs, landing failures, and an explicit terminal
liquidation rule. A chart price is not an admissible substitute.

For an actual episode ending or marked at \(T\), use a self-financing wealth account:

\[
W_T = \text{cash}_T + Q^{sell}_T(\text{remaining tokens})
      - \text{cash committed at episode start} - \text{explicit opportunity charges}.
\]

Report both dollar/SOL value and resource use: capital-time, downside, turnover, attention, and
unresolved exposure. A scalar risk-adjusted utility may be useful later, but the raw components must
remain available because selecting its risk penalty is a normative choice, not a learned fact.

Actual realized episode PnL is descriptive and identifiable if accounting is complete. Whether it
was skill, luck, or compensation for unmeasured risk is a different estimand.

## 4. Primary estimands

### 4.1 Operator selection uplift

Selection is normally not a causal treatment: looking at a coin does not cause its return. The
useful question is whether selection **ranks opportunities** under a common downstream policy.

For each scene, compare Ember's selected or top-\(k\) candidates with contemporaneous controls from
the exact choice set, all evaluated under the same \((q,h,\pi)\):

\[
\Delta_{select}(k;q,h,\pi)
= E[\overline G(\text{Ember top-}k)]
- E[\overline G(\text{matched alternatives})].
\]

There are several distinct funnel contrasts:

- surfaced versus census-eligible: value added by the platform;
- viewport versus merely surfaced: value added by presentation and scrolling;
- opened versus viewed-but-not-opened: early attention;
- armed versus inspected-but-rejected: deliberate selection; and
- traded versus armed-but-unfilled: trigger and execution.

These contrasts must not be collapsed. Matching should begin with exact scene/risk-set sampling,
then restrict on only **pre-decision** venue, lifecycle stage, quote availability, liquidity,
market-cap band, age, recent activity, fee hurdle, and board position. Inspected-but-rejected coins
are especially valuable controls because they share more of the hidden attention mechanism, but
their comparison is still selection-descriptive, not a causal effect of clicking `ARM`.

If Ember does not provide a complete ordering, do not manufacture one from click time. Capture a
coarse rank, shortlist, confidence, pairwise preference, or simply an unordered selected set.

### 4.2 Entry-timing value

At arm time \(a\) and actual fill time \(e\), estimate the value of waiting separately from the
value of selecting the coin. Replay, at the actual intended size:

- immediate entry at \(a\);
- the actual entry at \(e\);
- declared microdip alternatives available between \(a\) and expiry;
- no entry; and
- a small set of predeclared latency perturbations.

Two comparisons are necessary:

1. Same calendar-time downstream actions, which isolates the inventory-price consequence of the
   different entry.
2. Same predeclared management rule restarted from each hypothetical fill, which compares complete
   timing policies.

Holding Ember's later discretionary exits fixed after changing the entry is not generally a causal
effect: those exits may themselves depend on the entry, basis, and subsequent experience. Report it
as a pathwise replay contrast, not as "the value of waiting" without qualification.

### 4.3 Exit, flat watching, and re-entry management

The minimal comparison for an observed exit/re-entry cycle uses the same initial inventory and a
common terminal time:

\[
\Delta_{cycle}(T)
= W_T(\text{actual sell--flat--rebuy path})
- W_T(\text{hold through}).
\]

Also replay `sell and never return`, because a profitable sell/rebuy can still be worse than simply
having reduced risk and allocated the cash elsewhere. Report fixed terminal horizons as well as
episode resolution; choosing the episode's actual end alone can make the action define its own
evaluation window.

The flat interval is a first-class controlled state, not the absence of a position. It carries an
active thesis, attention cost, avoided downside or forgone upside, and a possible re-entry trigger.
Entry after a full exit starts a new wallet cost-basis interval but not necessarily a new operator
episode.

These replays assume Ember's order is small enough not to alter the subsequent market path. That
price-taker assumption must be checked against depth and accumulated strategy flow. It becomes
least plausible precisely when a proposed policy is scaled.

### 4.4 Partial exit and retained-runner value

At a partial-exit decision, replay three local exposure choices at the same executable quote:

- sell none;
- sell the actual fraction; and
- sell all.

Mark all three at common horizons and under a frozen, predeclared future rule. Separately evaluate
the actual adaptive runner policy as an episode-level policy. This avoids crediting the partial exit
for later discretionary actions it did not fix.

Preserve, rather than force into one number:

- **realization value:** proceeds and risk removed by the sold fraction;
- **retained-exposure value:** executable value and tail payoff of the runner;
- **recycling value:** what realized cash subsequently enabled elsewhere;
- **opportunity cost:** capital and attention retained in the coin; and
- **risk effect:** change in drawdown and correlated portfolio exposure.

The recycling attribution is path-dependent: if one cash pool funds several later trades, there is
no unique accounting decomposition without an allocation convention. Report sensitivity or bounds;
do not use an arbitrary funding attribution as discovered alpha. A retained bag is never valued at
zero basis merely because earlier proceeds exceeded the original spend.

### 4.5 Value per attention-hour

The aspirational estimand is

\[
AV = \frac{W(\text{human-assisted policy})-W(\text{declared baseline policy})}
           {\text{active attention time}}.
\]

It is not identified by comparing profitable attended sessions with unattended hours: Ember chooses
when to look, market conditions affect availability, and "not watching" produces few recorded
decisions. Report active minutes, elapsed session time, interruption burden, and the marginal value
of the first, second, and later attention hours rather than only an average.

Better designs are UI-level crossover experiments, shadow baseline policies run concurrently, and
matched availability windows. They can randomize a retrieval panel or prompt without randomizing
capital. Even then, the result is the value of that assistance configuration, not an intrinsic wage
for human intuition.

### 4.6 Scale-decay curves

The old projection assumed that per-trade value stayed constant as breadth increased by orders of
magnitude. The target is instead a curve:

\[
m(k)=\text{net value per acted candidate among the top }k,
\qquad
T(k)=k\,m(k)-\text{capital, impact, and attention costs}.
\]

Estimate separate curves for:

- additional human selections per unit time;
- retrieval-supported human selections;
- machine-nominated candidates accepted by Ember;
- shadow-only automation; and
- any later executable automation.

Selection quality may decline while total value rises, and capital concurrency may bind before
either. Report turnover, pool capacity, correlated tail exposure, and feedback delay with both
curves.

The human top-\(k\) curve is not observable beyond the ranks Ember actually expresses. Machine
performance on the rest of the census is not a continuation of that curve. Lower-rank labels must
come from cheap shadow exploration, diverse-case elicitation, or explicit operator comparison—not
linear extrapolation from the first few choices.

### 4.7 Regime dependence

Market regime and operator regime both matter. Market covariates include launch rate, liquidity,
volatility, fee tier distribution, migration rate, social activity, narrative concentration, and
SOL conditions. Operator state may include bankroll constraints, recent realized outcomes,
attention duration, and current portfolio load; it should be recorded minimally and respectfully,
with `unknown` always valid.

Define regimes only from information available before the evaluated decision. Use rolling estimates,
predeclared covariate strata, or change points fitted without future returns. Pool across regimes
hierarchically while preserving regime-specific estimates; a global mean can hide sign reversals.
Chronological holdouts must span nonadjacent sessions and, eventually, weeks. A split inside one
ten-hour session is not a regime test.

## 5. Methods in an honest order

### 5.1 Whole-market census plus high-resolution attended slice

The census provides denominators, base rates, choice sets, and coarse outcomes. The hot slice
provides event-by-event market state, quotes, media, social structure, and operator decisions. The
two must share identifiers and clocks. Without the census, attention bias is unknowable; without
the hot slice, the variables carrying Ember's judgment are projected away.

This is adaptive sampling with missing-not-at-random detail. Inclusion probabilities are known only
for system-randomized probes, not ordinary human attention. Weighting the hot slice as if it were a
random sample would be false precision. Instead, estimate within supported strata, report coverage,
and use the census for matched risk sets and bounds.

### 5.2 Matched choice sets and shadow outcomes

At each scene, preserve the actual candidates and follow standardized shadow outcomes for selected
and nearby unselected coins. This often provides better counterfactual evidence than OPE because
market paths for untraded alternatives are observable. Matching should be local in event time and
should retain the full distribution, not only a propensity score.

Limitations remain:

- unselected candidates may have missing high-resolution data;
- matching cannot remove unlogged intuition;
- an action's own market impact makes its no-action path unobserved; and
- management counterfactuals are only as real as the quote/replay model.

Sensitivity to matching specification and explicit no-overlap cases are part of the result.

### 5.3 Multi-state survival and competing risks

Use survival methods for time-to-transition questions, not as a universal return model. Relevant
states and competing events include:

- live quote, loss of quote, board disappearance, migration, and terminal collapse;
- inspected, armed, inventory, flat-watching, runner, resolved, and abandoned;
- unofficial fancoin, community formation, verified claim, public participation, fragmentation,
  persistence, and decay.

Board exit, collapse, claim, endorsement, and duplicate-coin migration are competing events rather
than independent censoring. Recurrent board appearances and re-entries require multi-state or
recurrent-event treatment. Handle delayed entry and left truncation explicitly. A hazard model can
estimate the distribution of the next event conditional on observed history; it does not establish
that a social claim caused the price path.

### 5.4 Analog retrieval before prediction

The first learning product should retrieve causally prior scenes that resemble the present one and
show their heterogeneous subsequent episodes. Similarity may combine:

- raw and normalized multiresolution chart paths;
- order-flow and executable-liquidity state;
- lifecycle, venue, fee, and portfolio context;
- post/thread text, author and community graph structure;
- images, names, represented entities, and competing coin families; and
- operator disposition and prior gestures.

Embeddings and feature extractors must be versioned, fitted only on past data for evaluation, and
linked back to raw evidence. Retrieval is descriptive unless a target policy and outcome are fixed.
Ember's judgments of which analogs are genuinely relevant are high-value labels, including "none of
these are analogous."

### 5.5 Multimodal and transition models

Later models can target distinct objects:

- representation of a market/social scene;
- probability and timing of a social-state transition;
- imitation of an operator gesture;
- conditional executable outcome under a fixed management policy; or
- ranking of candidates for attention.

Those targets are not interchangeable. An imitation model can faithfully reproduce bad decisions;
a return model can erase the semantic distinctions Ember uses; and an LLM interpretation can alter
the policy merely by being displayed.

The old `RESULT_llm_filter.md` is a useful negative result about one slow, static board-card glance
on a heavily selected cohort. It does not settle realtime analysis of threads, identities, chart
context, or evolving social transitions. New machine annotations must preserve model, prompt,
inputs, output time, and whether Ember saw them.

### 5.6 Program synthesis from partial specifications

The operator trace can eventually become a partial specification:

- positive action examples and explicit counterexamples;
- state-transition constraints;
- distinctions Ember says must remain separate;
- temporal predicates and permitted action windows;
- retrospective explanations linked to contemporaneous fragments;
- safety invariants; and
- `unknown`, `other`, and abstention cases.

The input language must be learned before the program. An ignored coin is not automatically a
negative example, a failure to re-enter is not a prohibition, and an after-the-fact explanation may
not describe the original decision. Many programs will be observationally equivalent on a small
trace; syntactic simplicity does not make the missing latent predicate irrelevant.

A credible loop is counterexample-guided: synthesize compact advisory rules, replay them on past
choice sets, show disagreements to Ember, add constraints or missing observations, and evaluate the
revised rule on a later chronological block. Behavioral agreement and economic value must both be
reported. Learned policy logic stays separate from a mechanically verified safety envelope such as
quote freshness, exposure limits, and transaction authorization.

### 5.7 Nonlinear hybrid-system and circuit abduction

The circuit intuition is productive if the analogy is assigned correctly. The environment is a
partially observed nonlinear hybrid network:

- continuous state: reserves, price, flow, concentration, inventory, and attention intensity;
- discrete modes: lifecycle and social-transition states;
- changing topology: identities, communities, wallets, narratives, and duplicate coins;
- external inputs: posts, cultural events, calls, claims, and creator behavior; and
- controller inputs: Ember's attention and trade-management actions.

Three inference problems should remain separate:

1. **Sensor/observation design:** which probes make latent distinctions observable?
2. **World-model abduction:** which mode/topology changes could explain an episode?
3. **Controller synthesis:** which policy maps observed history to useful actions?

Abduction produces equivalence classes of explanations, not a unique circuit. Observational traces
often cannot distinguish creator causation from creator response, coordinated flow from common
attention, or a latent social transition from price momentum. Prospective event ordering, natural
experiments, and occasionally system-side exploratory probes supply excitation. The framework is
most valuable for exposing missing sensors and underdetermination; it should not imply stationarity,
linearity, or full observability.

## 6. What must be logged

### 6.1 Time and provenance

- event time, ingest time, local display time, slot/block/transaction ordering, and clock quality;
- raw source payload or immutable reference, parser/schema version, and every derived version;
- explicit gaps, retries, duplicates, late arrivals, corrections, and current knowledge cutoff;
- venue/program/version and identity-resolution evidence as known then.

### 6.2 Census, product, and attention

- eligible universe, surfaced board/feed, exact ordering, filters, and UI version;
- viewport entry/exit, open/close, comparison, dwell, scrolling, search, and dismissal, collected
  with the least intrusive resolution that still answers the question;
- all actions available in the UI, not only the selected action;
- gesture, disposition, horizon, confidence, free-form fragment, and explicit `unknown`;
- whether a recommendation or machine annotation was visible before the action;
- system-randomized probe and its exact propensity, where one exists;
- operator availability/session boundaries and active versus merely open time.

### 6.3 Market and social scene

- raw trades, reserves, route and migration state, fee configuration, liquidity and concentration;
- multiresolution chart source data and, where useful, the rendered scene Ember saw;
- current and size-specific buy and liquidation quotes for actual and shadow sizes;
- posts, replies, authors, immutable social IDs, mentions, media, callouts, communities, and
  competing identity/coin families;
- what was unavailable or unresolved at the time, retained as missing rather than later backfilled.

### 6.4 Actions, execution, and accounting

- request, quote, intended limits, signature/transaction, landing, fill, failure, latency, and
  reconciliation as distinct events;
- token lots, fees, transfers, inventory, cash, reserved capital, and executable liquidation value;
- episode ID and inventory-interval ID separately;
- actual exit intent versus resulting fill; partial versus full exit; flat-but-watching state;
- re-entry intent and whether it expired, was canceled, or simply never became attractive;
- disposition/thesis transition independently of inventory change;
- portfolio state, concurrency, risk limits, and relevant alternatives forgone.

### 6.5 Counterfactual support and interviews

- scheduled shadow quotes after selections, rejections, entries, exits, and partial exits;
- contemporaneous matched controls and their outcome coverage;
- immediate, low-friction fragments such as "what changed?" with `nothing articulable` valid;
- replay-backed post-resolution interviews stored separately from the immediate account;
- links from later interpretations to the exact earlier evidence, never overwriting it.

## 7. Identifiability boundary

| Question | What the proposed tape can support | What remains unidentifiable without more design |
|---|---|---|
| What did the composite policy earn? | Exact descriptive episode/portfolio accounting if fills and holdings reconcile | Skill versus luck and compensation for latent risk |
| Did selection rank opportunities? | Selected versus contemporaneous alternatives under a common replay policy, within overlap | Performance on candidates Ember never ranked; value of unlogged intuition as a separable cause |
| Did waiting improve entry? | Pathwise executable replay at observed size under a price-taker assumption | How Ember's later discretionary policy would have changed under another entry |
| Did exit/re-entry add value? | Actual cycle versus hold/sell alternatives at common horizons | Market path under material own impact; latent visual cue if not captured |
| Did partial realization help? | Local fraction counterfactuals and actual runner episode value | Unique attribution of recycled cash and downstream adaptive actions |
| What is an attention-hour worth? | Assisted-versus-shadow baseline in supported sessions | Counterfactual performance had Ember attended at other times or with different fatigue |
| How does value scale? | Curve over explicitly ranked, probed, or shadow-evaluated breadth | Linear continuation across uninspected market and impact at untried turnover |
| Does a social transition predict another? | Prospective transition hazards with competing risks | Causal effect of endogenous claims/endorsements absent an intervention or natural experiment |
| Can OPE score another policy? | Supported system-randomized actions with known conditional propensities and observed rewards | Deterministic unsupported human choices, unseen histories, and long sequential policies with collapsed ESS |

When a row's conditions fail, return `not identifiable` or a bound. Do not substitute a model's
point prediction and call the question answered.

## 8. Exploration, confirmation, and falsification

### 8.1 Separate evidence streams

Maintain an append-only hypothesis registry. Exploratory work may invent dispositions, similarities,
horizons, outcomes, and models. A confirmatory claim freezes, before opening its evaluation block:

- population and choice event;
- action/policy being compared;
- outcome, size, terminal horizon, and accounting convention;
- matching/features and missing-data treatment;
- unit of independence and uncertainty method;
- regime definition;
- search/trials budget; and
- apparatus-quality gates.

Use later chronological blocks for confirmation, grouping mint, episode, entity/narrative family,
and overlapping time as appropriate. Repeatedly looking at the same future block converts it into
training data. Maintain known-zero worlds, planted-effect controls at economically relevant sizes,
and replay invariants.

### 8.2 Apparatus gates before strategy conclusions

The pilot should measure achievable quality first; thresholds are then frozen before strategy
evaluation. At minimum, refuse an inference when:

- decision-time choice sets or action availability are missing non-randomly;
- executed fills do not reconcile to wallet/token accounting;
- replay error or quote staleness is comparable to the claimed micro-profit;
- crashes and disappearing coins disproportionately lose their outcome paths;
- event/ingest ordering permits future enrichment to leak backward;
- matched alternatives lack common support;
- entity duplication makes one coin or episode count as many observations;
- a known-zero control manufactures the claimed effect or a planted effect cannot be recovered; or
- an OPE result has collapsed effective sample size or unsupported actions.

### 8.3 Component-level falsification gates

The composite thesis must be allowed to decompose rather than be protected or rejected wholesale.
On adequately powered, prospective chronological blocks:

- If armed coins do not outrank inspected/rejected alternatives under any predeclared common
  management policy, the represented selection-uplift claim fails for those regimes.
- If actual waiting does not beat immediate entry or no-entry after executable costs, the measured
  microdip-timing component is unsupported even if selection remains valuable.
- If sell–flat–re-enter paths consistently underperform hold-through and sell-only controls at common
  horizons, the measured cycling component is unsupported.
- If partial-exit policies do not improve the declared portfolio objective relative to full-exit and
  retain-all controls, runner management is unsupported under that objective; a rare-tail hypothesis
  may require a longer horizon rather than a favorable retelling.
- If \(m(k)\) reaches zero before useful breadth and total value cannot overcome concurrency and
  impact costs, market-wide automation is unsupported even if Ember's top few selections work.
- If signs reverse across held-out regimes, report a conditional policy or abstain; do not average
  the reversal into a universal rule.

A null with insufficient high-quality episodes is "not resolved." A null on a verified,
well-supported projection is a real component finding. Neither is a verdict about variables the
apparatus still cannot see.

## 9. Smallest useful experiment

Run an **observation-only prospective episode pilot** for seven calendar days or 30 naturally armed
episodes, whichever is later. Do not create trades to satisfy the sample count and do not automate
execution in this phase.

For every session:

1. Capture the whole census and product surface at coarse resolution.
2. When a coin enters the viewport or is opened, preserve the actual choice set and scene.
3. When Ember arms a coin, promote it to high-resolution market/social capture and begin
   size-specific shadow quotes.
4. Preserve every manual wallet action and explicitly distinguish partial exit, full exit,
   flat-watching, re-entry, runner transition, and resolution.
5. At each consequential gesture, collect an optional one-sentence contemporaneous fragment.
6. Continue counterfactual quote paths for the armed coin and a small matched set of viewed or
   surfaced alternatives.
7. Reconcile fills and generate a replayable episode dossier, including later interview material.

The pilot's deliverable is not an EV estimate. It is:

- audited episode boundaries and cash/inventory reconciliation;
- coverage and latency distributions for each required observation;
- examples of actual exit/re-entry and runner transitions represented without distortion;
- matched-choice-set coverage;
- replay error relative to the economic scale of a crackle;
- a list of latent distinctions Ember used that the schema failed to express; and
- a frozen protocol for the first prospective evaluation block.

Only after this passes should the project accumulate a first evaluation cohort—roughly 100 natural
armed episodes across multiple nonadjacent weekly blocks is a planning target, not a promise of
statistical power. Rare runner tails, fancoins, and re-entry patterns may require far more time. The
power analysis must use pilot event frequencies, within-mint dependence, outcome variance, and
missingness rather than an IID rule of thumb.

## 10. Dependencies on other lanes

- **Census and sensorium:** complete candidate denominator, platform-equivalent feeds, viewport and
  raw social/media capture.
- **Event tape and temporal semantics:** immutable event/ingest time, versioned enrichment, identity
  resolution, and replayable provenance.
- **Execution and quote replay:** exact fee/configuration reads, size-specific routes, landing and
  fill semantics, and quantified replay error.
- **Episode/accounting model:** lots, cash flows, inventory intervals, flat-watching, partial exits,
  runners, opportunity cost, and portfolio constraints.
- **Operator interaction and interviews:** evolving disposition/gesture language and unobtrusive
  immediate/retrospective elicitation.
- **Social-transition lane:** prospective identity/community states and competing fancoin families.
- **Safety and portfolio lane:** verified limits remain outside learned policy logic.

## 11. Unresolved design questions

1. What explicit resolution gesture ends an episode when Ember remains interested but no longer
   watches actively?
2. Which common management policies are useful diagnostic standards without repeating the old error
   of treating them as Ember's strategy?
3. How much viewport/dwell capture is informative without becoming intrusive or distracting?
4. Can high-resolution shadow quotes be retained for enough unselected alternatives to establish
   overlap without making the hot lane equivalent to an expensive full-market firehose?
5. How should downstream uses of recycled cash be bounded or attributed across simultaneous
   episodes?
6. What is the smallest useful ranking gesture—top set, pairwise preference, confidence, or ordered
   shortlist—that remains natural during live use?
7. How should opportunity cost and risk be reported before Ember chooses a scalar portfolio
   objective?
8. Which social and chart representations support analog retrieval while keeping the raw scene
   inspectable?
9. What price-impact threshold makes a counterfactual replay cease to be credible as breadth grows?
10. How can exploratory surfacing add coverage without changing Ember's natural attention process so
    much that the object being measured disappears?

The lane's recommended posture is therefore: **instrument first, estimate supported contrasts
second, synthesize only after the input language exists, and let each component fail independently.**
