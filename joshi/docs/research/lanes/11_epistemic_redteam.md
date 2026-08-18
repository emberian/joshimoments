# Lane 11 — epistemic red team

Status: research and design, before implementation or capital authorization.

This lane asks how Joshi could make Ember's composite human–machine process look valuable when
it is not. It accepts the project frame's central correction: a null on a crude projection does
not identify the value of an adaptive selection–execution–management process. It rejects the
opposite mistake too. Once the target is rich, adaptive, partly tacit, and allowed to change as
we study it, almost any history can be explained after the fact. High-resolution observation is
necessary for honest inference, not a license to protect the thesis from refutation.

The purpose of the red team is not to demand a premature scalar `alpha` test. It is to make each
claim precise enough that evidence can hurt it.

## 1. Claims that must not be allowed to collapse into one another

The project can succeed at one level and fail at another. Every report should name the level it
supports.

1. **Instrument validity:** the system faithfully records what was available, seen, intended,
   quoted, sent, filled, held, and later known.
2. **Decision-support value:** the glass improves attention, accounting, reaction time, recall,
   or loss containment even before it identifies a profitable strategy.
3. **Composite-policy value:** Ember's prospective selection plus timing plus management beats a
   relevant attainable alternative net of all costs and forgone opportunities.
4. **Partial automation value:** a particular synthesized component preserves or improves the
   value of the human process on new episodes.
5. **Scale value:** the component continues to work as candidate rank, throughput, position
   count, capital, or autonomous coverage expands.

Evidence for claim 1 is not evidence for claim 3. Evidence that Ember's top three choices work is
not evidence for claim 5. A profitable book does not validate a causal story about why it worked.
Conversely, a strategy can remain unresolved while the instrument is demonstrably useful.

The strategy object must be versioned. The operator, UI, taxonomy, surfacing system, execution
path, market regime, and capital constraints all change the policy. Without those versions there
is no stable referent for “the strategy improved.”

## 2. The principal ways the project can fool us

### 2.1 Selection, denominator loss, and hindsight

Ember's attention is both a potentially valuable sensor and a selection mechanism. The process
will appear prescient if we retain memorable winners but cannot reconstruct:

- all candidates that existed;
- which candidates Pump or Joshi surfaced and in what order;
- what was actually in the viewport;
- which coins were opened, briefly inspected, dismissed, armed, traded, or forgotten;
- what was known before each gesture rather than enriched afterward;
- unsuccessful episodes that quietly disappeared from the product or data source.

Retrospectively labeling RADON as “the kind that might send” is not the same evidence as recording
that disposition before it sent. A flexible episode narrative can always move the decision time
to just before the favorable segment. The defense is not random trading. It is a prospective,
timestamped attention funnel and outcome-blind intent labels, including rejections.

### 2.2 Endogenous attention

The world causes attention and attention changes behavior. A coin may be opened because it is
already moving, repeatedly revisited because it survived, or promoted to a runner because the
position is already profitable. Those actions may still add value, but their outcomes cannot be
credited wholly to the operator's earliest selection.

At each gesture, comparisons must start from the same information state and risk set. Useful
contrasts include:

- surfaced but never viewed;
- viewed but not opened;
- opened but rejected;
- armed but never triggered;
- immediate entry versus the actual delayed entry;
- actual exit versus continuing to hold;
- actual flat interval and re-entry versus uninterrupted exposure;
- actual partial exit versus selling all or retaining all.

These are attribution aids, not automatically causal estimates. The fact that the actual action
beat a shadow action does not prove the action rule generalizes; it establishes what part of the
episode deserves further study.

### 2.3 Hindsight in exits, flat intervals, and re-entry

Exit-and-re-enter episodes are especially easy to misaccount. Splitting one path into several
green clips can look like skill while the inventory lost money in aggregate. Selling at a loss
and repurchasing lower can manufacture an attractive new cost basis without recovering the old
loss. Re-entering after a rally can make the flat interval look wise if the comparison begins at
the new entry instead of the prior exit.

Every episode therefore needs one continuous clock, including time watched while flat, and all
round-trip costs. At every exposure-changing gesture, freeze at least these shadow paths:

- do nothing from here;
- liquidate fully from here;
- retain the pre-gesture exposure;
- take the actual action at the first realistically executable quote;
- for an exit, remain flat through the episode's eventual end;
- for a re-entry, the uninterrupted-hold path from the preceding exit.

The report should show value added and value destroyed by each interval, plus exposure-weighted
time, saved downside, forgone upside, realized cash, live liquidation value, and opportunity cost.
The correct unit remains the episode, not the prettiest clip within it.

### 2.4 Regime luck and dependency masquerading as sample size

Thousands of trades in one attention wave, one Solana congestion state, one SOL trend, or one
memetic episode are not thousands of independent tests. A strategy can look stable because all
of its successes are children of one market event. Results must be grouped by calendar session,
market state, narrative family, creator/community cluster, and coin—not merely by fill.

A chronological holdout from the same afternoon tests code reuse more than regime transfer. The
claim should weaken explicitly as evidence becomes less independent. The minimum useful regime
unit should be learned from dependency and event structure rather than asserted to be “one day.”

### 2.5 Correlated tail risk hidden by frequent small wins

Crackles and retained runners can generate many small realized wins while preserving a shared,
unrealized crash exposure. One −30% loss erases one hundred +0.3% net wins. Worse, losses may be
correlated: congestion, a Pump change, SOL drawdown, attention reversal, or common wallet behavior
can gap many coins together exactly when liquidity vanishes.

Win rate and average closed-trade PnL are inadmissible as primary book metrics. At minimum, report:

- total episode and book value, marking every live remainder at a size-specific liquidation quote;
- maximum simultaneous exposure and narrative/community concentration;
- drawdown, expected shortfall, worst executable gap, and time to recover;
- PnL with residual runners assigned zero recovery as an adversarial bound;
- PnL under clustered rather than independent tail events;
- capital turnover and the opportunity value of unavailable SOL.

No stop-loss should be treated as a bound unless the observation, submission, landing, and fill
path actually makes it one. On these assets a stop is an intent, not a price guarantee.

### 2.6 Mark, quote, transaction, and fill substitution

A chart mark answers none of the following: could the intended size have sold, through which
venue, at what dynamic fee, with what impact, after how much delay, and did the transaction land?
Using the same observed price for trigger and fill grants impossible execution. Using a later
quote to price an earlier decision leaks the future. Dropped transactions do not appear on chain,
so chain-only reconciliation cannot measure submission failure.

Each proposed action needs a causal chain:

```text
source event received
  -> state computed
  -> intent recorded
  -> executable quote requested and received
  -> transaction built/signed/submitted
  -> landed or expired
  -> fill and wallet state reconciled
```

Missing links remain missing; they are never replaced by marks. Shadow returns should carry a
latency and adverse-fill envelope. Live returns must use actual wallet deltas and all fees.

### 2.7 Survivorship and disappearing liquidity

Coins leaving a board, API, chart, or quote service are not ordinary missing observations. Their
disappearance is often the outcome. Dropping them conditions on being sellable. Carrying forward
their last price is an optimistic assumption unless independently validated. A “runner cemetery”
can likewise disappear from active screens while still consuming capital.

The census frame must originate from enumerable events rather than currently ranked assets.
Board exit, trading death, route loss, and unquotability are competing outcomes. Reports should
show optimistic and adversarial recovery bounds until terminal wallet value is observed.

### 2.8 Narrative leakage and mutable metadata

Names, images, creator fields, community associations, profile links, fee recipients, and model
summaries can change after launch. Today's metadata can make an early fancoin look obviously
connected to a creator when that connection was not visible then. A later viral phrase can leak
into embeddings, labels, search results, or an LLM's pretrained knowledge.

Every raw artifact needs observation time, source time when available, content hash, and source.
Derived identity edges and social-transition labels need `valid_from`, `observed_at`, provenance,
confidence, and model/prompt version. Historical replay must use only the version available at the
replay time. A current API response is not historical truth.

For LLM studies, the model must not see later posts, later metadata, future chart pixels, outcome
language, token popularity in its prompt, or retrieval results created after the decision time.
The safest early use is annotation and retrieval, with the raw evidence preserved—not an opaque
score treated as a feature of the past.

### 2.9 Interview confabulation

Post-zap interviews will be rich and useful, but an outcome-aware person can sincerely invent a
cleaner rationale than they possessed at the time. Outcome knowledge also changes the vocabulary
used to describe a scene.

Keep three layers distinct:

1. immediate, low-friction contemporaneous note, including “nothing articulable”;
2. later replay interview, explicitly marked outcome-aware;
3. analyst interpretation, versioned separately from both.

Compare immediate and retrospective accounts rather than reconciling them into one canonical
story. For selected interviews, hide post-decision outcomes while replaying the frozen scene and
ask for the disposition again. Disagreement is data about tacitness, memory, or policy drift—not a
reason to overwrite the original record.

### 2.10 Repeated experimentation and researcher degrees of freedom

The evolving ontology, many horizons, many books, visual patterns, prompts, embeddings, outcomes,
and stop rules create an enormous garden of forking paths. “We are not doing crude null testing”
cannot mean “we do not account for search.” Exploration may be permissive, but it must produce an
exploration ledger: every attempted rule, transformation, cohort, prompt, and result, including
failed ones.

Before a claim becomes confirmatory, freeze:

- the policy and UI version;
- the eligible universe and attention-stage denominator;
- the primary economic and safety outcomes;
- the fill model or live reconciliation rule;
- the holdout interval and stopping rule;
- the strategy-specific falsifier.

Discovery and confirmation may happen repeatedly, but never on the same episodes. A new taxonomy
or corrected instrument begins a new claim version; it does not silently rewrite the prior test.

### 2.11 UI-induced behavior change

Joshi is part of the policy. Faster charts may improve decisions; PnL colors may cause premature
selling; an `ARM CRACKLE` button may create trades that would never have been contemplated; alerts
may redirect attention away from better opportunities. Comparing “before Joshi” with “after
Joshi” confounds the operator, market, interface, and data quality.

Instrument viewport, notification, latency, and gesture affordances as treatment versions. Use
staged rollouts, shadow suggestions, and occasional reversible UI variants where burden permits.
The relevant product metric is not clicks or trades. It is decision quality and attention value,
with trade frequency itself allowed to be harmful.

### 2.12 Scale dilution and market impact

The operator's top few choices, Joshi's top fifty, and every eligible coin are different policies.
Selection quality can fall, simultaneous tails can rise, and our own turnover can become material.
Scale must be measured as a response surface over:

- rank or operator priority;
- number of concurrent hot subscriptions;
- trades per hour and capital turnover;
- clip size relative to executable depth;
- human review time per candidate;
- autonomy level.

The first 13 hand-selected wins or losses cannot be multiplied by 240 to estimate 2,000 mechanical
trades a day. Capacity should be expanded one rung at a time, with the prior rung retained as a
control. A result that works only for one or two choices per attentive session may still be a
valuable personal workstation result; it is not a market-wide autonomous strategy.

### 2.13 Accounting boundaries and cross-book leakage

Moving tokens from crackle to runner, from wallet to LP, or from one named disposition to another
cannot realize economic value by relabeling it. Likewise, creator-fee income or unrelated wallet
flows cannot subsidize trading PnL while being attributed to the trading strategy.

Every asset and liability should have a stable lot lineage across books. Book-level results must
reconcile to wallet-level changes, with deposits, withdrawals, distributions, fees, locked assets,
and external custody separated. A position transferred between books carries its live value and
remaining basis at the transfer instant; it is not reborn at zero.

## 3. Strategy-family falsifiers

These are not claims that must be tested immediately. They are what would count as meaningful
disconfirmation once the apparatus has enough prospective, executable, cross-regime coverage.

### 3.1 Active episode management: exit, watch flat, and re-enter

**Claim:** graph-watching and exposure changes add value after selection, including avoided
drawdowns and profitable re-entry, net of extra friction and missed upside.

**Would genuinely falsify it:** across predeclared prospective episodes and independent regimes,
the actual exposure path fails to improve total episode utility over attainable simple paths
(uninterrupted hold, fixed bracket, or full exit) after fees and opportunity cost; any apparent
benefit comes from choosing episode endpoints afterward; or saved downside is systematically
smaller than forgone upside and added friction. If the operator's exit/re-entry annotations do not
precede the decisions, the claim is unmeasured rather than falsified.

**Worth continuing before profit is proven:** the apparatus reconstructs every interval and
shadow path causally; decisions are captured without impairing reaction; risk exposure becomes
more intentional; and repeated prospective gestures reveal stable distinctions or eliminate bad
ones. Accurate decomposition is itself a continuation result for the instrument, not yet for the
trading claim.

### 3.2 Crackle

**Claim:** conditional on Ember's selection, waiting for a locally meaningful entry and executing
a short management policy produces realizable small net gains with acceptable tails.

**Would genuinely falsify it:** on sealed future episodes, actual or latency-calibrated shadow
entries do not outperform immediate entry or no trade; executable profit opportunities disappear
after current per-mint fees and size impact; the gap/slippage distribution makes the loss budget
unacceptable despite a high win rate; or performance exists only in retrospective labels and not
prospective arms. If the selection funnel was not logged, a mechanical whole-market null does not
falsify this claim—it tests a different policy.

**Worth continuing before profit is proven:** live-quote reconstruction is calibrated; stale-feed
and loss breakers work; the operator can arm and cancel without frictional distraction; selection,
entry timing, and exit management become separately measurable; and the shadow system rejects
most low-quality opportunities rather than manufacturing activity.

### 3.3 Retained runners

**Claim:** realizing some capital while retaining deliberately budgeted exposure preserves enough
convex upside from genuine senders to justify the residual downside and opportunity cost.

**Would genuinely falsify it:** a prospective runner book under an explicit budget underperforms
full liquidation or a simple fixed residual rule on total book value; a cemetery of low-liquidity
remainders dominates the few senders under conservative liquidation marks; discretionary
promotion adds no value over matched mechanical promotion; or correlation makes the book's tail
loss unacceptable. Median runner performance alone cannot falsify a convex strategy, and one giant
winner cannot validate it without concentration and replication analysis.

**Worth continuing before profit is proven:** every promotion is prospective; no remainder is
called free; liquidation value and forgone alternatives are visible; runner exposure stays within
budget; and the book teaches which thesis transitions, sizes, and review horizons are actually in
use.

### 3.4 Fancoin and social transition

**Claim:** point-in-time social and identity evidence can rank incomplete creator/community
transitions early enough to acquire and later exit exposure at executable prices.

**Would genuinely falsify it:** identity and transition states cannot be reconstructed with an
acceptable false-link rate; prospective rankings are no better calibrated than age/liquidity and
existing attention baselines; all apparent signal begins after price/flow already moved; claim,
endorsement, and fee-sweep events cannot be distinguished; competing duplicates make the target
undefined; or the lead time exists but no executable liquidity does. A study of only successful
claims is invalid, not supportive.

**Worth continuing before profit is proven:** the system builds a reliable point-in-time identity
graph; detects transitions with useful warning lead time; represents uncertainty and duplicates;
improves Ember's community situational awareness; and prospective probability/ranking calibration
improves on simple baselines even without trades.

### 3.5 LP inventory

**Claim:** actively managed bin exposure and capital withdrawals produce a better fee/risk/
opportunity tradeoff than passive positions or holding the underlying inventory.

**Would genuinely falsify it:** chain-reconciled fees net of adverse selection, composition change,
rebalancing friction, gas, downtime, and opportunity cost remain inferior to predeclared passive
and hold benchmarks across relevant regimes; in-place rebalance or withdrawal does not materially
improve exposure control; or tail inventory is not bounded by the proposed controls. Fee income by
itself cannot validate the strategy.

**Worth continuing before profit is proven:** position accounting closes to chain; exact bin and
token exposures are legible; proposed actions can be simulated before signing; capital can be
withdrawn without hidden swaps; and the glass prevents known operational mistakes. This can be a
valuable treasury instrument even if the strongest active-LP hypothesis is rejected.

## 4. Adversarial studies to build into the research program

### A. Prospective scene freeze

For every consequential gesture, freeze the raw scene, candidate set, viewport, portfolio state,
intent, confidence, horizon, executable quotes, and software versions before the outcome. Hash the
bundle and make later enrichment additive. Periodically verify that a replay using the cutoff time
cannot access later records.

### B. Decision ladder and matched risk sets

At each attention stage, retain contemporaneous alternatives and compare adjacent stages rather
than leaping from whole market to traded coin. Match on information actually available then—age,
liquidity, surfacing rank, flow, and market state—not outcome-derived metadata. Report how much
apparent value appears at each arrow of the funnel.

### C. Shadow policy fan-out

From each prospective decision, run a small fixed family of causal shadow actions: no trade,
immediate entry, actual delayed entry, fixed brackets, hold, full exit, actual partial exit, and
flat/re-entry alternatives. Use executable quote streams and the same latency rules. Keep this
family stable during confirmatory windows; exploration can propose the next family's candidates.

### D. Latency and fill attack

Replay every proposed microstrategy under measured receive-to-decision, quote age, build,
submission, landing, and reaction delays. Sweep adverse fill and missing-route assumptions until
the strategy crosses break-even. If tiny changes inside ordinary observed error reverse the
verdict, label the result execution-fragile rather than positive.

When later authorized, randomly assigned tiny execution probes can calibrate shadow fills. Until
then, no simulator should claim more precision than its quote and latency envelope supports.

### E. Death and disappearance attack

Reprice all censored, delisted, unquotable, and stale assets under multiple recovery rules,
including zero. Treat route loss and board exit as outcomes. A strategy whose value exists only
when stale marks are carried indefinitely is rejected for economic use even if its descriptive
signal remains interesting.

### F. Time-travel and metadata canaries

Seed tests where a coin's creator, symbol, image, community, or disposition changes later. Confirm
that historical features and LLM prompts remain unchanged. Compare stored source snapshots with
current API responses and fail closed when historical provenance is unavailable.

### G. Blind and delayed elicitation

On frozen scenes whose outcomes Ember does not know—or new scenes replayed before their horizon
resolves—ask for disposition and intended management. Later compare with the contemporaneous live
decision and outcome-aware interview. This tests whether the emerging vocabulary describes a
repeatable perception rather than only retrospective storytelling.

### H. Policy mutation and known-effect controls

Every analysis pipeline should face both:

- known-zero worlds preserving the dependency and censoring structure that could manufacture its
  result; and
- planted effects with the shape the estimator claims to detect.

Also mutate timestamps, entity grouping, fill direction, fee application, censor handling, and
book transfers. A test suite that only proves “zero stays zero” can pass because the estimator is
dead. A suite that only recovers synthetic effects can still manufacture them on real dependency.

These controls validate instruments. They do not replace evaluation of the composite process.

### I. Sealed chronological confirmation

Exploratory work may use all available history. When a rule, taxonomy, or model is promoted, seal
the next adequate calendar/regime window before it begins, log all changes, and inspect the
primary outcomes only when the stopping rule is met. If the system materially changes mid-window,
close the version and start a new one rather than pooling them.

### J. Scale ladder

Measure operator top-1, top-3, top-10, machine shortlist, and broad automation as distinct rungs.
At each rung, preserve the previous rung, measure marginal candidates, capital occupancy, tail
correlation, market impact, and attention burden. Stop expansion when marginal net value or safety
degrades; do not average a strong narrow rung with a weak broad one.

### K. Crisis and common-cause replay

Replay books through observed congestion, route failure, liquidity disappearance, SOL drawdown,
social reversals, and clustered duplicate collapses. Apply these events simultaneously across
positions. Verify that limits respond to aggregate exposure rather than assuming coin-level
independence.

### L. UI counterfactuals

Before adding a recommendation, badge, alert, PnL color, or one-click action, state the behavioral
change it may induce. Start in shadow where possible. Compare attention allocation, ignored alerts,
trade frequency, reaction time, and decision outcomes across reversible interface versions.

## 5. Stop, park, revise, and continue gates

Numerical sample sizes should not be invented before measuring episode dependency, tail variance,
and regime duration. Each confirmatory protocol should set its calendar and effective-sample gate
from those measurements *before* outcomes are opened. The following gates define what is being
earned, even before exact thresholds are calibrated.

### Gate 0 — apparatus integrity

**Continue to operator-facing prototyping only if:** wallet accounting reconciles; timestamps and
source provenance survive replay; current and historical metadata are separable; candidate and
viewport denominators are captured; mark/quote/fill are different types; censored assets remain
in the ledger; and known-zero plus known-effect controls behave.

**Stop strategy inference and repair the instrument if:** episode boundaries require outcome-aware
manual reconstruction, collectors do not overlap, trades or transfers are unexplained, future
metadata changes historical features, or synthetic fills are represented as realized PnL.

### Gate 1 — useful, low-distortion decision capture

**Continue if:** Ember can use the glass naturally; gestures and free-form notes precede outcomes;
the product captures exits, flat watching, re-entries, partial exits, and thesis transitions; and
the capture burden does not materially damage reaction.

**Revise or park the interface if:** it drives gratuitous trading, important actions occur outside
it without recovery, annotations are mostly retrospective, or the imposed taxonomy repeatedly
misstates the operator's intent. This gate can justify the workstation even with no profit claim.

### Gate 2 — shadow economic validity

**Continue a strategy family if:** its prospective episodes are replayable under calibrated quote,
latency, fee, and disappearance bounds; losses stay inside the declared hypothetical budget; and
the data reduce uncertainty about at least one decision component or eliminate a plausible policy.

**Park the economic claim if:** every result changes sign under ordinary execution uncertainty,
the strategy cannot be distinguished from an attainable simple baseline at the measured
resolution, or the only favorable outcomes are survivors. Continue the instrument separately if
it still clears Gates 0–1.

### Gate 3 — tightly bounded live validation, only after separate authorization

**Continue beyond minimal capital only if:** every signed intent reconciles to a transaction or
expiry; observed fill error agrees with the shadow envelope; hard aggregate-loss, stale-feed,
position, and runner-budget limits work in drills and reality; and no book can borrow hidden risk
from another.

**Immediately stop live action if:** wallet reconciliation breaks, an unknown transaction appears,
stale state can trigger an order, realized loss exceeds its declared envelope without an explained
gap event, or a safety limit fails. A losing but correctly bounded probe can be useful evidence; an
unbounded profitable one is a safety failure.

### Gate 4 — evidence for the narrow composite policy

**Continue and cautiously size the narrow policy if:** sealed prospective evidence across more
than one effective regime shows favorable total episode utility versus predeclared attainable
baselines, after all positions and opportunity costs are marked, without dependence on one
unrepeatable winner or one mutable classification.

**Revise or park if:** value disappears outside one regime, is entirely creator-fee or external
cash-flow leakage, comes only from endpoints chosen afterward, or violates the declared tail-risk
budget. “Unresolved” must not become permanent permission to trade; a claim version gets a fixed
evidence horizon and then is continued, revised, or parked.

### Gate 5 — automation and scale

**Expand one rung only if:** marginal candidates add nonnegative conservative value, execution and
attention capacity remain adequate, aggregate tails remain within budget, and the new rung does
not degrade the prior rung.

**Stop expansion if:** selection quality decays, correlated exposure rises faster than expected
return, market impact appears, or the operator's useful attention is displaced. A narrow personal
edge is an acceptable terminal product state.

## 6. Evidence worth celebrating before profit is established

To avoid both despair and goalpost-moving, pre-profit progress should be explicit and non-economic:

- **Instrument quality:** causal replay, wallet closure, quote/fill calibration, metadata history,
  complete attention denominators, and measured missingness.
- **Decision quality:** fewer accidental exposures, faster intentional exits, explicit runner and
  LP opportunity budgets, coherent changes of disposition, and reduced forgotten inventory.
- **Bounded loss:** tested aggregate limits, stale-state refusal, accurate exposure, and known
  failure envelopes.
- **Information gain:** a hypothesis is narrowed, a latent distinction becomes prospectively
  usable, an attractive rule is killed, uncertainty about a transition is calibrated, or a model
  recovers a repeatable part of Ember's judgment on unseen scenes.
- **Product fit:** the glass is sufficiently natural that it captures rather than deforms the
  process being studied.

These results justify further research. They do not authorize claims of profitability, autonomous
deployment, or linear scale.

## 7. What the old negative and null work contributes

The old studies are valuable as adversarial fixtures and measurement lessons, not as a verdict on
the process described in `PROJECT.md`.

- `RESULT_board_entry.md` initially interpreted survivor-only long-horizon returns as encouraging.
  `RESULT_bandit_search.md` retained censored cases and showed that 55.9% of resolutions were stale
  mark-outs; only 20% had a live quote at eight hours. This is the canonical disappearance test.
- The same bandit study found that the only weakly favorable bracket rules died under 1–2% adverse
  fill and that delayed feedback destroyed the apparent contextual-bandit result. This is a useful
  execution and learnability bound. Its grid tested board features, not Ember's unrecorded scene
  judgment.
- `RESULT_callout_volatility.md` measured the precise scale fallacy to avoid: 13 hand-selected,
  short-duration trades were projected roughly 240-fold into a mechanical book while that book's
  first closes pointed the other way. It also showed that callouts were late views of prior flow,
  making them plausible surfacing evidence rather than an independent causal trigger.
- `RESULT_exploration_map.md` searched 542 declared cells, found no return feature clearing measured
  friction, and found more information about disappearance than direction. It also caught
  same-instant microstructure bounce, backward-leaking cohort membership, non-overlapping
  collectors, and metadata-label fragility. This bounds what the existing coarse streams show; it
  does not bound information discarded before Ember's attention was recorded.
- `RESULT_control_arm.md` showed how “13 of 14 survived” nearly vanished after left-truncation,
  entry-age, liquidity-threshold, and arm-definition checks. It also found that choosing the 12
  most-touched tokens selected for continued survival. This is the template for conditioning on
  when a coin became eligible and preserving rejections.
- `RESULT_unrealized_pnl.md` recorded multiple manufactured effects: a busy-wallet sampling bug,
  future-bucket mark leakage, an autocorrelation-destroying null, a statistic blind to a monotone
  alternative, and a 60-second aggregation artifact. Its narrower within-(coin, instant) result
  suggests that position age changes realization behavior, but explicitly does not supply a
  trading rule. It is a strong argument for event-time data and against pooled dispositions.
- `RESULT_execution_landing.md` demonstrated that chain-visible failures omit never-landed sends
  and that ambient third-party traffic is not our execution denominator. It motivates submit-time
  signature logging and own-path calibration rather than imported landing claims.
- `RESULT_position_history.md` could not reconstruct a UI PnL headline, found trading negative in
  four of five wallets, and showed how fee income, locked assets, external custody, and trading can
  be mixed by an ill-chosen accounting boundary. It is the cross-book reconciliation fixture.

The correct composting move is to preserve these failure cases as regression tests. The wrong move
is either to repeat their coarse policies as if they represented Ember, or to discard their hard-
won lessons because their strategic questions were misframed.

## 8. Unresolved questions for reconciliation

1. What is the least burdensome way to capture viewport and attention without changing them more
   than we can measure?
2. What endpoint terminates an episode when Ember may remain interested while flat for days?
3. Which simple shadow policies are genuinely attainable and decision-relevant, rather than straw
   benchmarks?
4. How should attention time and forgone opportunities enter utility without inventing a false
   dollar precision?
5. What constitutes an independent regime for crackle, runners, fancoin transitions, and LPs?
6. How can historical LLM replay be protected from model pretraining knowledge of events that
   occurred after the scene?
7. What conservative recovery value should apply to temporarily unquotable assets, and when does
   temporary become terminal?
8. How should strategy versions be closed when Ember learns during the evidence window—which is
   the intended behavior of the project?
9. Which outcomes justify the workstation as a decision instrument even if every trading family is
   eventually parked?

The final red-team criterion is simple: Joshi should make it progressively harder to tell an
attractive story that the prospective event tape, wallet, and counterfactuals do not support. If
it instead becomes a more elaborate way to narrate winners and rename losses, the project has
failed at the level that matters most.
