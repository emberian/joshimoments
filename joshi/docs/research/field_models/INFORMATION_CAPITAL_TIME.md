# Decision-relevant information and capital-time

Status: exploratory methods note; read-only research; no strategy, causal, profitability, or
economic-authority implication.

## 1. Question and scope

This note makes one Wave 5 question testable:

> How much decision-relevant information does a source, representation, fitted operator, or Glass
> presentation carry or reveal, relative to the capital, inventory, time, friction, attention, and
> risk involved in using it?

The answer is not one scalar. JOSHI's field vocabulary requires every quantity to retain its
domain, carrier, unit, clock, observation operator, coverage, knowledge cutoff, authority rung,
and support. In particular:

- information about a competing-risk transition is not commensurate with information about an
  executable price distribution;
- capital-time in atoms of different assets cannot be added;
- viewport time, active controls, and self-reported attention are different observation-defined
  measures;
- a proper-score increment is an H3 fitted-model result, not a source fact;
- a presentation intervention is distinct from the evidence it presents; and
- realized value, replay value, forecast quality, attention burden, and risk must remain separate.

This note extends the hierarchy and unit rules in [`README.md`](README.md), the observation and
identification rules in
[`IDENTIFIABILITY_AND_UNITS.md`](IDENTIFIABILITY_AND_UNITS.md), and the marked-flow and operator
language in [`FIELDS_AND_OPERATORS.md`](FIELDS_AND_OPERATORS.md). It supplies methods for the
evaluation and presentation lanes in
The primary execution order is
[`WAVE5_LIVING_INSTRUMENT.md`](../../planning/WAVE5_LIVING_INSTRUMENT.md); the detailed estimator
program remains in
[`WAVE5_LEARNING_FIELD_LAB.md`](../../planning/WAVE5_LEARNING_FIELD_LAB.md).
[`FORECAST_MECHANISM_NOTE.md`](FORECAST_MECHANISM_NOTE.md) applies the same frontier to one dated
public claim about leveraged prediction markets without treating its marketing objective as a
canonical scalar.

## 2. Primary object: an information-use frontier

Fix a registered study cell

```text
c = decision kind × target × lifecycle/regime × direction × exact size
    × horizon × downstream policy × coverage/support state.
```

For a channel, representation, model component, or presentation `z`, report an information vector

```math
\mathcal I_c(z)=
(\Delta\text{proper score},\ \Delta\text{replay regret},\
  \text{persistence surface},\ \text{calibration},\ \text{support/coverage})
```

beside a resource and consequence vector

```math
\mathcal C_c(z)=
(\text{asset-specific capital-time},\ \text{inventory-time},\ \text{attention},
  \text{latency},\ \text{fees},\ \text{turnover},\ \text{risk},\
  \text{unresolved exposure}).
```

The primary artifact is the pair `(I_c, C_c)` across registered cells and simple baselines. A
Pareto surface is often more honest than a total order: one display may reduce orientation errors
but require more navigation; one signal may improve a transition forecast but arrive too late for
the relevant size.

Derived ratios are admissible only when their numerator, denominator, aggregation rule, and zero
case remain attached. Examples include aggregate proper-score gain per standardized asset-hour,
regret reduction per standardized capital-hour, and useful retrievals per qualified-focus minute.
They are views over the frontier, not a canonical `information_efficiency`, `pressure`, `alpha`, or
operator-quality field.

## 3. Carrying information versus revealing it

The distinction is operational.

### 3.1 Information carried by an input

An input `z` carries prospective information for target `Y` when a frozen point-in-time model using
`z` improves chronological held-out forecast performance over the same model/baseline without
`z`. Both arms use the same eligible decisions, cutoffs, target definition, partitions, and
missingness treatment.

This is a model-relative H3 claim. It does not show that `z` causes `Y`, that a human can use `z`,
or that acting on it is profitable. A source may carry information that the presentation fails to
reveal; a renderer artifact may appear to carry information only because it leaks regime or later
outcomes.

### 3.2 Information revealed by a presentation

A Glass policy reveals information when, holding the eligible as-known evidence fixed, assignment
to that policy improves a registered operator usefulness or safety outcome. Intended policy,
staged scene, durable receipt, mount, viewport visibility, semantic focus, and operator response
are distinct events.

The primary causal candidate is the intention-to-treat contrast under prospective randomized
read-only assignment. Actual exposure is post-assignment and may be incomplete. A complier effect
requires additional instrumental-variable assumptions and is exploratory by default. Without a
randomized or defensible natural assignment, report a presentation-associated contrast, not the
effect of the display.

The safe presentation invariant, authority ceiling, data cutoff, and evidence content must remain
constant across arms. A presentation experiment cannot hide safety evidence, alter execution
authority, or randomize capital.

## 4. Observable estimands

Every estimand below is indexed by the registered study cell and reported with chronological
uncertainty, coverage, and the relevant authority rung.

### 4.1 Forecast-score increment

For a decision `d`, matured target `Y_d`, baseline forecast `p_0`, candidate forecast `p_z`, and
proper loss `S`, define

```math
\Delta S_{z,d}=S(p_0,Y_d)-S(p_z,Y_d).
```

Positive values favor the candidate. Use target-appropriate scores:

- log score and Brier score for a finite event vector;
- integrated Brier score or time-dependent log score for survival/competing risks;
- CRPS or a registered quantile score for a continuous executable outcome; and
- ranking measures only alongside calibrated probabilities and the complete witnessed choice set.

Under log scoring, the mean increment may be expressed in nats, but it is only the held-out gain of
the fitted candidate over its declared baseline. Do not call it intrinsic mutual information.
Report calibration, abstention/coverage curves, worst supported strata, negative controls, and
missing-modality behavior with the mean score.

### 4.2 Attainable replay regret

Let `A_d` be the complete action set actually attainable at cutoff `d`: including abstention,
refusals, exact direction and size, and any common frozen downstream policy. For each separately
registered loss component `L_k`, define

```math
R_{d,k}=L_k(a_d,Y_d)-\min_{a\in A_d}L_k(a,Y_d).
```

Candidate components include terminal-liquidated net cost, downside, unwanted asset conversion,
unresolved exposure, and attention burden. The minimizing action can differ across components; the
result is a regret vector, not evidence for one universal utility.

Replay uses size-specific executable quote/refusal objects, fees, latency rules, landing/failure,
sequential inventory, and a common terminal horizon. It is a pathwise H1/H2-derived contrast under
the frozen replay assumptions. It does not identify the adaptive human policy or market path that
would follow a different action. A future-best action is an evaluation oracle, not a decision rule
available at the cutoff.

For a randomized Glass arm `g`, the presentation usefulness candidate is an ITT contrast such as

```math
E[R_{d,k}\mid assignment=g_1]-E[R_{d,k}\mid assignment=g_0].
```

For nonrandomized operator selections, selected-versus-attainable comparisons remain descriptive
of ranking within supported witnessed choice sets.

### 4.3 Information persistence

One half-life is too lossy. For source or representation `z`, estimate a surface over signal age
`tau` and registered outcome horizon `h`:

```math
P_z(\tau,h)=E[\Delta S_z\mid signal\ age=\tau,\ horizon=h,\ supported\ state].
```

Keep two versions:

1. **Frozen-origin persistence:** information recorded at origin `t` forecasts outcomes at
   increasing horizons without later enrichment.
2. **Residual relevance:** the old information still improves a baseline that also receives data
   legitimately available by `t+tau`.

The second can remove mediated information and therefore is not the total persistence of the
original event. Report both rather than silently conditioning on later state. Stratify by
lifecycle, topology version, coverage, size, direction, and regime. Migration, route loss,
terminal illiquidity, or identity/topology revision is a competing boundary or new estimand, not
an ordinary observation on the same field.

Useful summaries may include the last preregistered lag with positive supported gain, integrated
score gain over a fixed lag grid, and sign/calibration stability. None replaces the surface.

### 4.4 Capital-time and inventory-time

Before valuation, capital-time has asset-specific dimension `[A_a][T_wall]`. For exact asset `a`
and declared capital state `B`, retain separate integrals for available, reserved, in-flight,
deployed, and claimable balances:

```math
CT_{a,B}([t_0,t_1])=\int_{t_0}^{t_1} b_{a,B}(t)\,dt.
```

Do not add atom-seconds across assets. For position inventory, retain at least:

```math
IT_a^{signed}=\int q_a(t)\,dt,
\qquad
IT_a^{absolute}=\int |q_a(t)|\,dt,
```

plus off-target inventory-time relative to a registered acceptable set. A DLMM position retains
its per-bin, per-asset inventory measure and contingent conversion geometry; a single marked
notional does not replace it.

An optional quote-valued projection is

```math
CT^{liq}_{r,q}=\int V^{liq}_{r,q}(B_t)\,dt,
```

where `V_liq` names exact numeraire asset, direction, size, route set, quote/refusal profile,
freshness, and state closure. It is derived, may be nonadditive, and is unavailable when liquidation
coverage is absent.

For cross-policy comparison, prefer a predeclared standardized denominator such as
`q_budget × horizon` in one exact carrier asset. Report aggregate ratios of sums:

```math
\frac{\sum_d\Delta S_d}{\sum_d CT_d^{standard}},
\qquad
\frac{\sum_d\Delta R_{d,k}}{\sum_d CT_d^{standard}}.
```

Do not average per-decision ratios. If a presentation changes entry, size, or holding time,
realized capital-time is a post-treatment mediator. Normalizing its causal effect by that realized
denominator changes the estimand and may induce selection. Report realized resource intensity
descriptively beside the standardized contrast. A zero-capital abstention is scored per eligible
opportunity, never as infinite efficiency.

### 4.5 Attention, latency, fees, and risk

These remain a bundle:

| family | directly observable or derived measures | boundary |
| --- | --- | --- |
| attention | viewport-card seconds, open-panel seconds, qualified focus intervals, controls, navigation, task switches, elapsed watch time, optional self-report | viewport is not gaze; focus is not comprehension |
| latency | source-to-available, staged-to-received, mount-to-visible, visible/focus-to-gesture, quote-to-send, send-to-land/fail, land-to-finality | never replace the clock vector with one latency |
| friction | protocol, creator, transfer, LP, network, priority, tip, rent, failed-attempt, route and terminal-liquidation components | gross fee income and household net cost remain separate; self-routed fees are internal transfers |
| realized risk | drawdown path, asset concentration, out-of-band inventory-time, unresolved/trapped inventory, refused liquidation, correlated episode exposure | realized downside is descriptive, not ex ante risk |
| modeled risk | registered tail quantiles, stress liquidation, failure/MEV scenarios, uncertainty and support | scenario/model output remains H3/H4, never settled fact |

Report decision latency from witnessed event clocks and operator burden from physical interaction
evidence. A quick gesture does not prove low cognitive load. Attention measures are alternative
projections, not gauges of one observed cognitive scalar.

### 4.6 Mechanically contingent versus discretionary flow

“Forced flow” is too ambiguous for a binary source column. Add a typed action-origin mark to the
eligible event measure:

```text
operator_discretionary
precommitted_policy
venue_mechanical_inventory_conversion
external_counterparty_or_route
protocol_lifecycle
unknown
```

The mark is assigned from transaction, position, policy, and operator-event provenance available
at the classification cutoff—not inferred from later price or whether the outcome felt unwanted.
An LP fill can mechanically convert inventory under an earlier discretionary schedule; both facts
should survive rather than forcing it into one moral category.

For each origin class `r`, report:

- signed and absolute transfer in each exact carrier asset;
- event intensity under healthy scoped coverage;
- subsequent inventory-time and off-target inventory-time;
- fees earned, fees paid, and internal/self-route eliminations;
- executable markouts at registered horizons;
- time to operator detection, review, or discretionary correction; and
- competing-risk incidence of the next management or lifecycle event.

Observed adverse markout is not causal toxicity, and mechanically contingent does not mean
economically inevitable. Missing attribution remains `unknown`; it cannot enter either side of a
forced/discretionary contrast by imputation.

### 4.7 Glass presentation usefulness

No PnL-only UI objective is admissible. A presentation experiment reports a usefulness and safety
vector:

- time to first registered relevant-evidence event;
- orientation, route-attribution, inventory-direction, and source-gap corrections;
- appropriate abstention and confidence calibration;
- attainable replay-regret components;
- unwanted-conversion recognition and subsequent review;
- navigation/control/focus burden and capture interruption;
- over-management, overtrading, FOMO, alert fatigue, and tool abandonment;
- accessibility, pain, error/refusal rate, and sustained usability;
- useful analog/retrieval events and later operator rating; and
- PnL only by digest link to independently reconciled accounting.

Every item names its outcome availability time and authority. The presentation artifact also
records eligible, shown, omitted, rendered, viewport-visible, focused, and acted-on sets. A staged
scene is not observed exposure, exposure is not attention, and attention is not causal usefulness.

## 5. Identification, censoring, selection, and reflexivity

### 5.1 Selection and support

Operator attention and hot-scope acquisition are endogenous observation operators. Preserve the
broad census, exact funnel and choice set, inspected-but-rejected alternatives, operator
availability, and a random or stratified cold slice. Unknown human or deterministic inclusion
probabilities do not become propensities after the fact. OPE and inverse weighting are limited to
logged support with known probabilities and adequate effective sample size.

Matching can reduce measured imbalance within supported scenes; it does not make unlogged
intuition ignorable. Human top-`k`, machine-nominated breadth, and unattended census performance
are different curves.

### 5.2 Censoring and competing boundaries

Outcomes distinguish:

- healthy administrative horizon censoring;
- source-loss censoring with exact gap scope;
- left truncation and interval censoring;
- quote, route, or terminal-liquidation refusal;
- lifecycle/migration and topology/identity revision;
- competing send/fade, exit/re-entry, management, route-loss, and protocol events; and
- unresolved inventory at the study deadline.

Unavailable outcomes are not zero. Source loss can depend on activity or failure and is generally
informative. Weighting is appropriate only when the censoring mechanism is observed with support;
otherwise publish bounds/sensitivity and the unresolved denominator. A later provider peak or
interview cannot be written backward into an as-known feature.

### 5.3 Replay and causal limits

Executable replay identifies a frozen-path or frozen-policy contrast under declared quote,
latency, ordering, failure, price-taker, and terminal-liquidation assumptions. It cannot identify
the market path, Ember's adaptive management, competing-agent response, or MEV under a changed
action. As proposed breadth or size grows, own impact and interference become more—not less—likely.

Cluster uncertainty by operator episode, mint/family/territory, route/topology, and overlapping
market window wherever they can transmit shared futures. Chronological partitions require outcome
embargo and removal of overlapping information paths.

### 5.4 Reflexive observation and presentation

Glass, hot acquisition, and model explanations participate in the process they measure. A display
changes attention and labels; a manual action can change venue state and later social/market
response; a hot lease changes observation density. Treat every material sensing, model, and UI
version as an intervention/regime boundary. Retain concurrent simple baselines and evaluate new
versions prospectively.

Read-only presentation randomization can identify an assignment effect on operator outcomes when
consent, stable safety content, correct randomization, interference handling, and outcome capture
hold. It does not identify the value of the underlying source separately unless source availability
or content is independently varied under an ethical registered design.

## 6. Minimal prospective instrumentation

For every consequential decision, abstention, and registered non-action, capture the following.

1. **Decision closure:** decision, episode, inventory-epoch and position IDs; exact as-of vector;
   census and choice-universe digests; attainable action set; direction, exact size, horizon,
   downstream policy, regime, portfolio state, and acceptable-inventory set.
2. **Input closure:** each source/feature/field/model component's occurrence ID, content digest,
   authority rung, domain/carrier/unit/topology, valid and availability intervals, coverage
   windows/gaps, support, and baseline/candidate eligibility.
3. **Pre-outcome inference:** frozen baseline and candidate predictions, calibration artifact,
   uncertainty bundle, abstention/refusal, and inference cutoff before any target release.
4. **Presentation closure:** assignment mechanism/stratum, policy/config digest, scene/view digest,
   staged receipt, mount, actual visibility/viewport/focus/control events, omissions, accessibility
   mode, and client/render clocks.
5. **Operator evidence:** nomination, comparison, disposition, confidence or
   `cannot_articulate_yet`, gesture/abstention/correction time, optional contemporaneous fragment,
   and later outcome-hidden interview linked without rewriting the original decision.
6. **Execution and origin evidence:** exact quotes/refusals, requests, attempts, landing/failure,
   fills, all fee components, route/MEV evidence, transaction/position provenance, and typed
   action-origin classification.
7. **State intervals:** every balance, reservation, in-flight, position/bin, acceptable-set, and
   inventory state transition needed to integrate exact asset atom-seconds.
8. **Outcome release:** fixed horizons, executable liquidation objects, common terminal rule,
   competing events, censoring kind/bounds, outcome knowledge deadline, coverage, and revisions in
   a separate append-only label artifact.
9. **Prospective controls:** broad census and cold/random sensing slice, frozen simple forecast and
   do-nothing/replay baselines, plus small consented presentation crossovers that cannot change
   authority or hide safety truth.
10. **Usefulness closeout:** physical attention/latency measures, corrections/errors, capture
    burden, operator usefulness report, abandonment reason when voluntarily supplied, and links to
    reconciled—not client-entered—economic outcomes.

The smallest credible first study can use one decision kind, one target vector, one standardized
size/horizon, one baseline/candidate ablation, and two safe presentation policies. It still needs
the complete census/choice denominator and later outcome closure. A larger model does not repair a
missing denominator.

## 7. Falsification and promotion gates

Reject or narrow an information/capital-time claim when:

- score gain disappears against a seasonal/state/simple-mechanics baseline, future-shift control,
  renderer/provider control, or chronological regime holdout;
- calibration, support, or coverage fails in the size/direction/lifecycle cells where it would be
  shown;
- apparent persistence is later enrichment, topology leakage, or source-selection feedback;
- replay advantage is smaller than quote/fill error or disappears under fees, failures, terminal
  liquidation, self-flow elimination, or plausible ordering/MEV sensitivity;
- a capital-time ratio changes sign under valid asset, numeraire, liquidation, or denominator
  choices while the underlying vector was hidden;
- forced/discretionary attribution depends on future outcome or has too much `unknown` support;
- Glass usefulness disappears under assignment analysis or increases corrections,
  over-management, accessibility burden, or capture interruption;
- censoring bounds include no useful effect, or observation loss is differential and unmodeled;
  or
- scaling changes impact, attention, route capacity, or interference beyond the registered
  support.

H3 promotion requires prospective chronological gain, calibration, negative controls, explicit
support, and an effect larger than measurement uncertainty. H5 study status additionally requires
complete attainable-action and path scoring, UI-intervention logging, scale/capacity/tail analysis,
and an independent safety capability boundary. Neither status authorizes execution.

## 8. Durable residue

This program remains useful if every predictive or profitability candidate fails. It leaves exact
capital/inventory-time accounting, witnessed evidence and presentation closure, honest censoring,
operator-usefulness measures, and a map of where information arrives too late, costs too much
attention, or fails outside a narrow state. That is evidence about the composite operator system,
not a null verdict about the unobserved market.
