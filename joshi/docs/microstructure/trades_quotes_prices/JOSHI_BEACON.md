# JOSHI beacon

## The practical translation

The book does not hand JOSHI a memecoin strategy. It changes what the apparatus must regard as a
well-posed question.

The central lesson is that price, flow, liquidity, attention, and execution are a coupled process.
A chart shape detached from the event stream, a mark detached from executable size, or a fill
detached from the choice/attention path cannot answer Ember's question about the composite
human–machine strategy.

The JOSHI translation is:

```text
observe venue-native state and the attention path
  -> preserve exact clocks, coverage, and operator scene
  -> separate observed response from causal reaction
  -> model intensity, signed flow, state adaptation, and execution jointly
  -> reconcile fees, fills, residual inventory, and full liquidation
  -> compare prospectively declared management paths
  -> only then consider a policy or learning algorithm
```

## Five design consequences

### 1. There is no universal `price`

The cockpit must type and label:

- chart/last-trade mark;
- venue marginal price;
- executable buy/sell quote for exact size;
- instruction maximum/minimum;
- actual average fill;
- full-position liquidation value; and
- stressed liquidation under declared route/state changes.

Chapter 22's warning about infinitesimal marks is immediately applicable to runners and LPs
[pp. 418–419]. This is not a later accounting refinement; it changes which opportunities are real.

### 2. Event time and wall time are both first-class

Hawkes/activity questions live in wall time. Sign memory and many impact relations are easier in
event time. Solana execution adds slot, transaction, instruction, receive, send, landing, and
finality order. JOSHI must support multiple clocks without inventing a total order.

### 3. Observed response is not caused impact

The reaction/prediction identity [pp. 210–211] should appear in the study API and UI language.
Allowed labels include `observed_post_trade_response`, `matched_control_estimate`, and
`modeled_reaction`. `impact_caused` is unavailable from one historical path.

### 4. Provider/LP revenue is a path, not a fee counter

Fee income must be joined to inventory conversion, adverse post-event response, withdrawal state,
liquidation route, rebalancing, network cost, and missed alternatives. Chapters 16–17 supply the
economic decomposition even though their queue formulas do not transfer.

### 5. The first model is a baseline to break

Poisson, Hawkes, linear propagator, square-root scaling, and simple inventory rules are useful
because their failures say what structure is missing. They should never be promoted merely because
they fit an in-sample curve.

## Concept-to-apparatus map

| source concept | required evidence | schema implication | glass | first analysis | possible strategy implication, if earned |
| --- | --- | --- | --- | --- | --- |
| Price object and signature plot | marks, marginal state, exact-size quotes, fills, clocks | `PriceObservation.kind`, size, route, state hash, fee profile | multi-price overlay and scale selector | variance/mean-reversion by price kind and lag | microdip target must survive executable-price signature, not chart alone |
| Event intensity / Hawkes | complete interval attempts, events, source gaps, wall time, exogenous covariates | typed event, occurrence/availability time, coverage interval | activity heat strip with baseline versus residual intensity | Poisson/seasonal baseline, then held-out point-process forecast | promote attention when intensity changes only if false-alarm and common-cause tests pass |
| Long-memory signed flow | exact trade direction, size, venue, wallet/route attribution quality | `SignedFlowEvent`, sign definition, participant edge, lifecycle | cumulative signed flow and lag-memory panel | ACF and conditional hazards by mint/lifecycle; splitting-versus-herding probes | execution/exit timing may condition on persistent flow, not assume mean reversion |
| Queue/state dependence | full venue-native pre-event state | source-specific state snapshot plus derived dimensionless coordinates | state-conditioned response surface | transition/hitting models and calibration | only use a state predictor when action value exceeds quote/fill error |
| Observed/reaction/prediction impact | pre-action scene, focal event, later prices, matched controls, eligibility manifest | causal-estimand type and information cutoff | label observed versus modeled response visibly | cohort/event study with common support and sensitivity analysis | no causal strategy credit from a raw post-buy rally |
| Selective liquidity taking | size-specific state before trade, exact reserves/depth, route | state/size/side in every response row | response by size *and pre-state* | compare raw size curve with state-conditioned curve | size policy based on actual curve, not naïve volume/return correlation |
| Square-root metaorder impact | parent/child linkage, `Q`, `T`, market volume, volatility, path, end time | parent-intent link with evidence quality; participation numerator/denominator | impact path normalized by volume/volatility | fit competing scaling laws out of sample; audit selection | execution splitting baseline only after parent and venue definitions hold |
| Propagator/resilience | signed flow, lagged response, other event types, gaps | event-type vocabulary and projection version | bare/observed response comparison | linear kernel baseline, residuals, state/history-dependent challenger | detect when expected flow is or is not being buffered |
| Asymmetric liquidity | event surprise, state history, price-changing status | prediction at event time and resulting response | surprise × direction response matrix | HDIM/state model versus TIM baseline | reduce confidence when same-direction flow ceases to be buffered |
| Adverse selection | provider fills/fees, subsequent executable value, non-fill opportunity | provider episode and position path | fee-versus-selection waterfall | conditional post-fill response and full P&L | LP/maker changes only under bounded prospective policy |
| Latent liquidity | visible curve plus future arrivals/cancels/trades and wallet/social proxies | assertions with uncertainty, never a latent fact column | future executable-depth scenarios | state-space/latent-factor models with calibration | territory/flow context, not claimed hidden demand |
| Execution shortfall | decision price, all attempts, quote, fill, failure, fees, residual | attempt and landed-effect journals | decision-to-fill waterfall | decompose price move, fees, latency, route, impact, residual | choose manual action affordance and scale; not yet automation |
| Instability / withdrawal | liquidity edits, route loss, quote gaps, volatility/intensity, provider failures | correlated state/gap events | liquidity withdrawal and source-health alarms | tail episode docket and stress replay | fail closed; do not infer “oversold” from vanished liquidity |
| Impact-adjusted valuation | full-size routes, LP withdrawal, all assets, stressed state | liquidation artifact with quality | exposure rail uses liquidation, not mark | mark–quote–fill gaps and stress distributions | runner/LP disposition changes based on executable risk |

## Minimum evidence objects

The book argues for richer semantics, not for a universal event table. The smallest portable objects
are:

### `MarketEvent`

```text
event_id and source-native identity
venue / pool / mint / lifecycle
event kind and versioned decoder
exact event, source-receive, persist, and finality clocks
exact atomic asset/state effects
raw observation hash and coverage interval
participant/wallet attribution plus evidence quality
```

### `StateAtEvent`

```text
pre-state observation/hash and age
venue-native reserve/bin/queue fields
fees and token-program state
executable quote surface for declared sizes
source completeness and missing fields
```

### `ObservedResponse`

```text
focal event and sign definition
pre-event information-manifest hash
price kind and venue
lag in event time and wall time
observed signed change
coverage, censoring, migration, and route status
label: observed association, not causal reaction
```

### `ParentFlowHypothesis`

```text
candidate parent ID
child events
link evidence: operator-declared | wallet-cluster | timing inference | unknown
planned/observed horizon and quantity
denominator volume and coverage
revision history
```

### `LiquidityProviderPath`

```text
initial exact assets and contingent bin inventory
adds/removes/claims/rebalances
fees/rebates/rent/network costs
post-event inventory and executable withdrawal
per-leg liquidation routes and quality
counterfactual branch kept distinct from landed ledger
```

### `OperatorDecisionScene`

```text
surface/choice set and source health
chart and exact-size quote state
social/context evidence actually visible
portfolio/runner/LP exposure
stance, act, episode, inventory epoch
later fill/effect joined without rewriting the scene
```

## Glass implied by the book

### A. Executable price stack

For one mint and direction, show:

```text
last/chart mark
marginal pool price
quote for intended clip
quote for full runner
minimum/maximum instruction bound, when one exists
actual last fill
stressed liquidation
```

The gap between these lines is itself a state variable.

### B. Flow and intensity strip

- event-time signed-flow raster;
- wall-time event intensity versus seasonal/state baseline;
- cumulative signed base and quote atoms;
- unique-wallet/route count with identity uncertainty;
- launches/callouts/social/creator events on separate tracks;
- exact coverage and hot-scope promotion boundary.

No single “momentum” number should collapse these.

### C. Response surface

Render observed response by:

- side/sign;
- exact size/participation;
- pre-event liquidity/reserve state;
- lifecycle and venue;
- event surprise under a frozen predictor;
- wall/event lag; and
- source/quote age.

This is the AMM analogue of the book's response/propagator glass, not a claim of causal impact.

### D. LP truth waterfall

```text
fees and rebates
- adverse inventory conversion
- price/route movement while held
- add/remove/rebalance friction
- transaction fees/tips/rent effects
- residual unrouteable or retained assets
= landed and current executable economic path
```

Show current, lower-edge, upper-edge, withdrawal, and liquidation inventory separately for DLMM.

### E. Episode rail

One operator episode may include:

```text
notice -> inspect -> enter -> micro-manage -> partial exit -> runner
       -> full exit -> flat watch -> re-entry -> later partial/full resolution
```

Overlay each inventory epoch without making flatness end attention. This extends the source book's
fixed-metaorder frame to Ember's actual process.

## Research program

### Study M0 — exact venue price geometry

**Question.** How different are mark, marginal price, exact-size quote, landing-state fill, and
full-position liquidation across Pump curve, PumpSwap, and Meteora states?

**Data.** Raw protocol state, exact integer quote profile, quote clocks, external fills, fees,
routes, and failures.

**Output.** A price-object calibration corpus and the executable price stack.

**Continue if.** State can be reconstructed and quote error is materially below the micro-profit
hurdle for at least one scoped venue/size.

**Stop if.** Quote/fill/state uncertainty consumes the target edge. Preserve the exposure tool.

**Book anchors.** Chs. 3, 11, 12, 21–22.

### Study M1 — signed-flow persistence by lifecycle

**Question.** Are buy/sell directions persistent in event time or wall time, and how much is
attributable to repeated wallets/routes versus broad co-movement?

**Design.** Predefine sign, venue, lifecycle, coverage interval, wallet clustering, and lags. Compare
IID, Markov/DAR, seasonal, and shuffled-within-state baselines. Keep a random cold-market stratum so
hot promotion does not create the effect.

**Falsifier.** Held-out autocorrelation/forecast gain is unstable across days/regimes or vanishes
after participant/state controls.

**Useful residue.** Flow coverage and wallet-clustering evidence even if predictability fails.

**Book anchors.** Ch. 10; Secs. 13.2–13.3.

### Study M2 — state-conditioned observed response

**Question.** How does signed post-trade movement vary with trade size, reserve/bin state,
participation, preceding flow, and lifecycle?

**Design.** Estimate `ObservedResponse`, not caused impact. Use exact pre-state and multiple price
objects. Compare raw size curves with state-matched curves; preserve migration/rug/route-loss as
outcomes rather than censoring them.

**Falsifier.** No stable response structure beyond deterministic instantaneous curve movement and
noise, or uncertainty is too large for an action scale.

**Book anchors.** Ch. 11; Figs. 11.3–11.6.

### Study M3 — linear resilience versus history-dependent state

**Question.** Does a linear signed-event kernel forecast future price/state better than a
history-dependent model in which expected and surprising events have different effects?

**Design.** Freeze event vocabulary and train/validation epochs. Compare Poisson/random-walk, linear
propagator, event-type TIM, and small state/HDIM challengers. Report residuals at lifecycle breaks.

**Falsifier.** Kernel is unstable, violates held-out variance/response, or a simple state baseline
matches it.

**Book anchors.** Chs. 13–14.

### Study M4 — attention excitation without causality theater

**Question.** Do selected social, creator, callout, and platform events improve held-out forecasts of
trade/intensity transitions beyond time-of-day, market state, and product ranking?

**Design.** Start with seasonal Poisson/negative-binomial baselines. Add multivariate point-process
terms only after coverage and availability-time audits. Negative controls include future-shifted
events, unrelated mints, and platform-wide bursts.

**Falsifier.** Improvements disappear out of sample, under negative controls, or after common
platform/market covariates.

**Book anchors.** Ch. 9 and Ch. 20.

### Study M5 — LP adverse selection and inventory conversion

**Question.** Do fees compensate for exact inventory transformation and liquidation risk for the
specific Meteora position/policy?

**Design.** Prospective position versions; per-bin inventory; exact claims/adds/removes; full
withdrawal and leg liquidation; external/manual rebalances; opportunity baselines; correlated tail
episodes. Compare no-change, prospective remove/add, and in-place edit policies only from the same
knowledge cutoff.

**Falsifier.** Net results remain negative or tail loss dominates after fee, friction, capacity, and
selection accounting; rebalancing is unavailable/too costly for the intended cadence.

**Useful residue.** LP exposure and contingent inventory calculator.

**Book anchors.** Chs. 16–17, with strong transfer limits.

### Study M6 — crackle microdip feasibility

**Question.** After Ember nominates a coin, is there an attainable small entry/exit policy whose
edge survives quote geometry, delay, fees, failure, state reaction, and selection?

**Design.** Start at nomination time. Record intended trigger, exact-size quotes, shadow attempt
clock, executable exit ladder, management changes, and actual manual intervention. Compare wait,
enter, partial, full exit, and remain-flat branches without replaying the observed future as fixed.

**Falsifier.** Apparatus error or economic hurdle is of the same order as gross edge; wins depend on
outcome-selected trigger/exit changes; tail loss overwhelms crackles.

**Book anchors.** Chs. 11–14 and 21.

### Study M7 — partial exits, runners, and re-entry

**Question.** For prospectively declared management dispositions, what joint distribution of
realized cash, remaining executable value, downside, and retained upside results?

**Design.** Episode continues through flat watching; accounting epochs reset at flat. Compare
attainable partial/full/hold paths at common cutoffs. Treat Ember interventions as policy evidence,
not nuisances.

**Falsifier.** The apparent runner advantage vanishes after full residual liquidation, selection,
and common horizon, or the disposition cannot be declared before outcomes.

**Book anchors.** Chs. 12, 21–22; JOSHI extension beyond the book.

## Strategy-family implications

### Crackle

The book strengthens the strategy's *measurement* case and weakens any simple mean-reversion story.
Persistent order flow can coexist with flat return predictability because liquidity adapts; a
microdip may continue, revert, or become unquotable depending on state. The action unit is a
state-conditioned quote/fill path after Ember's nomination.

### Runner

Concave size impact and the mark/liquidation gap make partial realization economically distinct
from all-or-none liquidation. The runner must retain real basis and full-size executable risk.
“Cash recovered” is not “free.”

### Exit, flat watch, and re-entry

Execution models begin with a fixed desired parent trade; Ember's process revises the desired
position. The episode state must therefore sit above execution. A full exit can be locally optimal
and re-entry later can still belong to one behavioral hypothesis.

### Fancoins and social transitions

Point-process and self-referential models offer a vocabulary for audience arrival, imitation, and
feedback. They do not let a fitted Hawkes norm become “community virality” or a fee claim become
creator endorsement. Identity, awareness, endorsement, and attention remain separately evidenced.

### Meteora LP

The closest source-book analogy is competitive liquidity provision: fee/spread-like income versus
adverse selection and inventory risk. Queue priority and bid–ask formulas do not transfer. DLMM
analysis must use exact bins, dynamic fees, withdrawal, and token liquidation.

### Complete Pump alternative

The book reinforces why the product surface matters: the choice set and event context generate
which flows enter the sample. A technically excellent market tape without the actual attention
surface can study post-selection management, not Ember's whole policy.

## Promotion rule

A source-book idea moves toward product policy only when:

1. the venue-native object has a precise definition;
2. source coverage and availability time are measured;
3. the effect survives a prospective held-out test and attainable baseline;
4. quote/fill/fee error is smaller than the economic claim;
5. correlated tail states and capacity are included;
6. Ember's natural interventions are represented; and
7. a failed strategy still leaves an instrument Ember uses.

Until then it belongs in glass or analysis, not an arm button.

