# Epistemic position book for JOSHI

Status: design synthesis; read-only research; no strategy, profitability, deposit, synthetic-asset,
portfolio-authority, or execution-authority implication.

## 1. Decision

JOSHI should eventually maintain an internal **forecast registry, scorebook, ensemble, and
information-allocation laboratory**. It should not imitate a literal artificial prediction market.

The useful internal object is an epistemic position book:

```text
registered claim occurrence
  -> sealed human/model forecast submissions
  -> append-only outcome adjudication
  -> proper scoring and calibration
  -> dependence-aware ensemble
  -> value-of-information study
  -> separately versioned shadow policy comparison
```

There are no event securities, artificial bankrolls, deposits, leverage, orders, market maker,
funding rate, or transferable payout in this book. A forecast is a bounded H3 claim about a named
future target. It is not a financial position, portfolio reservation, recommendation, or
authorization.

This deliberately extracts the useful question from
[`FORECAST_MECHANISM_NOTE.md`](FORECAST_MECHANISM_NOTE.md)—how an institution can improve
prospective information discovery—without inheriting Forecast Protocol's publicly incomplete
leverage, pooled-capital, price-formation, or settlement mechanism. It also adopts the
information/resource frontier from
[`INFORMATION_CAPITAL_TIME.md`](INFORMATION_CAPITAL_TIME.md): proper-score gain, replay value,
capital-time, inventory-time, attention, latency, friction, and risk remain a vector rather than
one gameable `information per capital` scalar.

## 2. What the components mean

| Component | Question answered | What it cannot establish |
| --- | --- | --- |
| forecast registry | what exactly was believed, by whom, from which as-known inputs, before which cutoff | truth, independence, usefulness, or authority |
| proper scorebook | whether a probabilistic submission was calibrated/informative after admissible adjudication | causal value, profitability, or portfolio fit |
| ensemble | how compatible forecasts combine under one frozen aggregation contract | new evidence or independent votes merely from member count |
| information allocator | which additional observation, representation, model run, or operator prompt is worth studying | permission to spend capital or widen sensing without a budget |
| shadow position policy | which attainable action branches have which outcome/resource vectors | actual counterfactual market path or live safety |
| literal prediction market | what executable event-security price strategic, budget-constrained traders form | a pure posterior, even when such a market is genuine |

Information acquisition, belief expression, aggregation, decision use, and market price revelation
are separate mechanisms. Leverage or an artificial stake creates no evidence. Volume, forecast
dispersion, price movement, trader profit, and entropy reduction are not substitutes for
prospectively measured score or decision improvement.

## 3. Authority placement

The field hierarchy remains binding:

| Rung | Relevant object |
| --- | --- |
| H0 settlement identities | finalized asset effects, quantities, custody, and reconciliation |
| H1 protocol kinematics | exact profiled quotes, DLMM inventory/bin math, and landed transitions |
| H2 descriptive fields | observed market, social, attention, coverage, and resource summaries |
| H3 fitted operators | forecast submissions, calibration, ensemble, score increments, and estimated information value |
| H4 latent/abductive objects | hypothesized regime, private information, community state, actor motive, or unspoken predicate |
| H5 policy/controller | a declared mapping from an observed history and constraint set to a proposed act |

An H3 forecast never enters the finalized financial projection as observed or deterministic truth.
The existing projection intentionally admits only evidence-backed observations and deterministic
calculations; see [`15_projection.md`](../../implementation/lanes/15_projection.md). A future
forecast/ensemble artifact therefore remains a separate latent-estimate family with estimator,
build, input cutoff, support, uncertainty, and claim scope.

The boundary is strict:

```text
forecast submission
  != ensemble forecast
  != shadow action comparison
  != operator gesture
  != portfolio reservation
  != transaction intent
  != signed/submitted transaction
  != landed wallet effect
```

No score, ensemble weight, disagreement threshold, or information value may widen a hot scope,
portfolio budget, reserve exception, policy lease, or execution capability by itself.

## 4. Common claim contract

Separate a reusable **claim definition** from a time-local **claim occurrence**. A definition says
what kind of target is forecast and how it matures. An occurrence freezes the exact subject,
information state, attainable branches, and horizon for one prospective evaluation.

### 4.1 Claim definition

Every definition needs:

| Field family | Required meaning |
| --- | --- |
| identity | contract, schema, claim-definition ID/version, semantic digest, producer/build |
| target | named event vector, time-to-event object, executable outcome distribution, or branch-value vector |
| domain and unit | exact subject domain; asset IDs; native atoms/rationals; probability/quantile representation; reporting numeraire when used |
| conditioning | lifecycle/regime, direction, exact size, horizon, downstream frozen policy, and any allowed intervention |
| outcome space | exhaustive mutually distinguishable resolved states, including competing events where appropriate |
| adjudication | eligible observations/replay method, maturity rule, outcome deadline, correction policy, and resolver version |
| censoring | administrative, source-loss, left/interval, route/refusal, intervention, conflict, and unresolved treatment |
| scoring | proper score, orientation, probability floor or quantile grid, abstention treatment, and comparison baseline |
| support | eligible population/cell, required coverage, prohibited inputs, and known transfer limits |
| authority | `read_only_no_execution` and the restricted inference/decision claim scope |

A memecoin price is not an event probability. JOSHI claims must name a future executable return,
competing transition, liquidity state, terminal inventory, social transition, or frozen-policy
branch outcome. Open-ended theses become a family of fixed-horizon claims; they do not remain
unresolvable forever.

### 4.2 Claim occurrence

Every occurrence freezes:

- claim-occurrence ID and definition digest;
- scene, decision, exact witnessed choice-universe digest, and portfolio-domain identity;
- candidate/mint, episode, inventory epoch, lot, position, schedule, pool/profile, edge-tenure, or
  policy-branch references required by the definition;
- event/decision time, issue deadline, information cutoff, full as-of vector, and outcome
  availability deadline;
- sorted evidence and derived-input manifest, coverage windows/gaps, source/topology versions, and
  maximum input availability;
- exact starting quantities, branch sizes, protected reserves, simultaneous commitments, and
  attainable action set when the target is decision-conditional;
- terminal-liquidation/FX/fee/latency/failure manifest where financial value is a target;
- registered study cell: decision kind × target × lifecycle/regime × direction × size × horizon ×
  downstream policy × support state; and
- visibility regime: sealed first round, ensemble-visible revision, operator-visible, or
  retrospective-only.

The occurrence must exist before target release. A later provider peak, identity correction,
interview, or terminal route cannot be written backward into its input closure.

### 4.3 Forecast submission

A submission binds:

- immutable submission/revision ID and claim-occurrence ID;
- forecaster identity, producer/model/prompt/training/calibration lineage, input closure, and
  production cutoff;
- probability vector, predictive distribution, registered quantiles/intervals, or explicit
  `abstain` / `missing` / `unsupported` / `refused` state;
- support and uncertainty statement;
- parent forecasts or ensemble actually visible before the revision; and
- restricted H3 claim scope and `read_only_no_execution` authority.

Probabilities may use canonical decimal or fixed-point ppm wire forms. Financial targets remain
exact atoms/rationals until a named valuation projects them. Statistical scoring may use bounded
analytical floating arithmetic after the target and financial inputs are frozen; its output is a
fitted analytical measure, never ledger truth. Missingness is not probability zero.

## 5. Position-family claim contracts

All position claims start from the episode and consolidated-portfolio semantics in
[`PROJECT.md`](../../PROJECT.md),
[`06_portfolio_lp.md`](../lanes/06_portfolio_lp.md), and
[`08_accounting.md`](../../implementation/lanes/08_accounting.md). The same asset atom cannot be
separately owned by a crackle, runner, LP, and routed book merely because those are useful policy
attributions.

### 5.1 Spot and crackle

Two targets should remain distinct.

1. **State/competing-risk forecast.** For one candidate, exact size, decision cutoff, and fixed
   horizon: net executable profit target first, registered drawdown first, quote/liquidity exit,
   lifecycle boundary, or healthy survival without an event. A crossed target inferred only across
   an observation gap is interval-censored or conflicting, not known.
2. **Frozen-policy outcome forecast.** Distribution of terminal-liquidated wealth under a named
   shadow crackle entry/management rule versus staying liquid or another predeclared branch. It
   includes exact quote/refusal, latency, failure, fee, impact, and terminal rules.

Selection, entry waiting, partial realization, full exit, flat watching, and re-entry are separate
decision events inside an episode. Changing entry while holding later discretionary actions fixed
is a pathwise replay, not the causal value of entry timing.

### 5.2 Retained runner

A runner claim binds exact remaining lots/quantity and current basis quality; recovered capital
does not make it costless. Useful fixed-horizon targets include:

- terminal wealth difference between retaining the exact remainder and liquidating it at the
  decision cutoff under one common terminal manifest;
- probability of a registered right-tail threshold before drawdown, route loss, or horizon;
- executable downside, unrouteable-residual, and liquidity-exit states;
- current and forecast inventory-time, off-target inventory-time, and review/attention burden; and
- capital-recycling opportunity branches when the released assets have a prospectively named use.

Evaluate the frozen local partial/full/none exposure choice separately from the complete adaptive
runner episode. Actual later discretion cannot be credited retrospectively to the earlier partial
exit unless that future rule was already part of the claim.

### 5.3 LP position and schedule

An LP claim binds exact position identity, pool/profile, schedule version, active/bin state,
principal/fee/reward separation, pair orientation, observation slot/cutoff, and a complete terminal
method. Useful targets include:

- external-flow fee/reward distribution with self-routed accrual excluded from external revenue;
- active-bin movement, finite-range traversal, route loss, and terminal per-asset composition;
- full-liquidation outcome and unrouteable residuals;
- hold-current-schedule versus partial remove, add, in-place redistribution, or close/reopen under
  explicitly modeled transformations; and
- one named adverse-selection diagnostic, such as registered `LVR_grid` or aggregated
  inventory-transfer regret, without adding overlapping diagnostics twice.

An observed schedule edit is a competing intervention for an actual-path hold claim. It can remain
evaluable only through a separately supported frozen replay. LP withdrawal is a custody change,
not a sale; modeled rebalance is not proof of UI/program support; a mark is not a size-specific
liquidation quote.

### 5.4 Routed-liquidity joint control

Use the three-clock semantics in
[`04_OPTION_CONTROL_ACCOUNTING.md`](../routed_liquidity/04_OPTION_CONTROL_ACCOUNTING.md):

- a slow edge install/pause/retire policy;
- a medium finite-bin/range/add/remove/rebalance policy; and
- a separate fast spot/hedge/crackle policy.

Useful claims are:

- installed edge versus absent edge joint surplus at a common horizon;
- external route-demand, external-fee, and edge-tenure survival distributions;
- medium schedule version's reachable-inventory, fee, edit-friction, and constraint outcomes;
- fast stabilization action's landing, latency, cost, and inventory-improvement distribution; and
- probability or bounds for acceptable-inventory, dated/transaction-reserve, terminal-liquidity,
  route-capacity, and attention-budget violations.

The primary outcome is a vector: consolidated terminal-liquidated wealth; external service
revenue; stabilization/schedule friction; exact asset-specific capital-time and inventory-time;
reachable/current inventory; reserves and acceptable-set violations; drawdown/tail scenarios;
unrouteable residuals; and attention. Internal book credits cancel, self-routed owned fees are
internal transfers, and the tenure is not collapsed into a favorable LP “cycle.”

## 6. Outcome adjudication, financial settlement, and censoring

Keep three artifacts separate:

1. **Outcome observation:** retained market, route, social, position, episode, or operator facts.
2. **Forecast adjudication:** how the registered target matured under the definition and available
   evidence.
3. **Financial settlement:** independently finalized wallet effects and reconciled inventory.

A forecast score cannot post a wallet effect. A landed effect cannot prove that the forecasted
policy caused the outcome. Counterfactual branch values remain replay estimates and never become
realized PnL.

Adjudication should use tagged outcomes such as:

- `resolved_observed`;
- `resolved_frozen_replay`, carrying the replay manifest and assumptions;
- `healthy_no_event_through_horizon`;
- `administrative_censored`;
- `source_loss_censored` with exact gap scope;
- `left_truncated` or `interval_censored`;
- `competing_event` with event kind;
- `route_or_liquidation_refused`;
- `intervention_invalidated_actual_path`;
- `conflicting`;
- `unsupported`; or
- `open_not_mature`.

Unavailable outcomes are not zero or failure. Source loss is generally informative. The MVP leaves
censored, conflicting, refused, and unsupported occurrences unscored while reporting their full
denominator. Later integrated survival scores or censoring weights require observed censoring
support and a registered estimator; they may not be introduced merely to increase sample size.

Outcome corrections append a new adjudication version with evidence and supersession. The original
claim and forecast never mutate. A score artifact names the exact adjudication version, score rule,
orientation, baseline, supported cohort, and calculation build.

## 7. Proper scoring and economic evaluation

Choose the score to match the elicited object:

- Brier or log score for a finite event vector;
- integrated Brier or registered time-dependent log score for sufficiently supported
  survival/competing risks;
- CRPS for a continuous predictive distribution; or
- registered quantile/interval scores for declared quantiles and intervals.

Log scoring requires a prospectively declared probability domain/floor and careful tail review.
The initial book should prefer bounded, legible categorical scoring where practical. Ember should
not be forced to turn a qualitative disposition into `0.63`; coarse probability bins, quantiles,
pairwise comparisons, or abstention are valid only when the claim and evaluation are designed for
that elicitation.

Report:

- absolute score and score increment against a simple as-known baseline;
- calibration/reliability and abstention/coverage curves;
- chronological/regime/family support and worst supported strata;
- uncertainty clustered by episode, mint/family/territory, route/topology, and overlapping market
  window; and
- negative controls, future-shift checks, and missing-modality behavior.

Ranking metrics appear only beside calibrated probabilities and the complete witnessed choice
set. Do not reward a forecaster directly from realized trading PnL: it mixes forecast quality,
policy, feasibility, risk, and luck. Economic evaluation is a separate attainable replay-regret or
branch-value artifact.

Ex-ante capital-at-risk or decision-importance weights may produce a secondary weighted score when
they are frozen before outcomes. Preserve the ordinary unweighted score and denominator; an
outcome-dependent weight breaks the intended comparison. One giant runner cannot establish
calibration, and a median cannot alone refute a deliberately convex book.

## 8. Ensemble aggregation

Only aggregate submissions for the same claim definition/occurrence, horizon, outcome space,
conditioning branch, and adjudication contract. Never average differently sized quote targets,
hold/sell/rebalance recommendations, or forecasts made before and after different information
releases.

The first ensemble is equal-weight and appears beside the registered simple baseline. Every
ensemble is itself an immutable H3 forecast submission with:

- component submission IDs and lineage groups;
- exact eligible/missing/abstaining set;
- aggregation/calibration contract and fit cutoff;
- weights and shrinkage/capping rules;
- training/evaluation partitions and regime support;
- output distribution and uncertainty; and
- ensemble identity/version/digest and `read_only_no_execution` authority.

Only after prospective chronological support should JOSHI consider calibration-weighted pooling,
linear/logit pooling, extremization, stacking, or regime-conditional weights. Weights learned from
a tiny, adjacent, outcome-overlapping sample invite a self-confirming ensemble. Component and
ensemble forecasts are scored separately.

### 8.1 Correlation and Sybil resistance

The unit of evidence is not an account or process invocation. Ten prompts to one model checkpoint,
ten fine-tunes of one leaked dataset, or ten agents reading the same ensemble are not ten
independent sources.

Require each submission to declare:

- model/provider/checkpoint, prompt/template, training/calibration snapshot, parent artifacts, and
  evidence manifest;
- whether peer or ensemble forecasts were visible;
- common source/model/prompt/operator lineage groups; and
- material revisions after shared information releases.

Seal first-round submissions before revealing peers. Later revisions name everything seen and are
not counted as independent. Cluster or cap influence by lineage, report raw and effective member
counts, preserve disagreement, and inspect leave-one-lineage-out contribution. Never award
ensemble power or artificial wealth for forecast volume. An opaque producer remains one
unknown-dependence lineage, not infinite diversity.

## 9. Value-of-information allocation

The first allocation problem concerns read-only observation resources:

- hot-scope breadth/duration and cold/random sensing;
- quote refreshes and route probes;
- social thread, wallet, lifecycle, chart-resolution, and media acquisition;
- deterministic feature/analog jobs and model/LLM runs; and
- bounded operator comparisons, prompts, or staged Glass presentations.

It does not allocate live trading capital. A probe's value is not its predictive uncertainty; it
must be capable of changing a supported decision or safety conclusion enough to justify its data,
latency, attention, privacy, and monetary costs.

For a named scalar decision utility `U`, one conventional candidate is:

```math
EVSI_U(z)
= E_y[\max_{a\in A_d} E(U(a,\theta)\mid D,y,z)]
  - \max_{a\in A_d} E(U(a,\theta)\mid D)
  - Cost_U(z).
```

`A_d` is the complete action set actually attainable at the cutoff, including abstention,
refusals, exact direction/size, simultaneous reservations, and a common frozen downstream policy.
Because `U` and its shadow prices are normative, JOSHI's primary artifact remains a vector:

```text
forecast-score increment
attainable replay-regret change
calibration/support/coverage change
asset-specific capital/inventory-time
attention and latency
fees/turnover
tail risk, reserve violations, and unresolved exposure
```

Use a Pareto frontier across registered study cells and simple baselines. An optional ratio uses a
predeclared standardized denominator such as exact carrier-asset budget × horizon and reports a
ratio of sums, never an average of per-decision ratios. A zero-capital abstention is scored per
eligible opportunity, not as infinite information efficiency. If a presentation changes entry,
size, or holding time, realized capital-time is a post-treatment mediator and stays descriptive
beside the standardized causal contrast.

Estimate presentation/retrieval value through safe prospective staged reveals or randomized
read-only assignments with the safety view and authority fixed. Do not randomize capital to make
VOI convenient. Information carried by a source/model is a held-out ablation claim; information
revealed to Ember is a presentation-intervention claim. Neither implies the other.

## 10. Exact accounting and capital-time boundary

The independently finalized ledger in [`08_accounting.md`](../../implementation/lanes/08_accounting.md)
remains the inventory authority. Forecasts read exact quantities, lot basis quality, episode/epoch
attribution, runner state, LP inventory, fees/rewards, quotes/refusals, and projection residuals;
they cannot rewrite any of them.

For asset `a` and capital state `B`, retain exact piecewise state intervals sufficient to derive:

```math
CT_{a,B}([t_0,t_1])=\int_{t_0}^{t_1} b_{a,B}(t)\,dt,
```

with `B` distinguishing at least available, reserved, in-flight, deployed, and claimable. For
inventory:

```math
IT_a^{signed}=\int q_a(t)\,dt,
\qquad
IT_a^{absolute}=\int |q_a(t)|\,dt,
```

plus off-target inventory-time against a registered acceptable set. Before valuation these have
asset-specific unit `[A_a][T_wall]` and cannot be added across assets. A quote-valued capital-time
projection names numeraire, direction, exact size, route set, fee/refusal/freshness profile, and
state closure; it is unavailable when liquidation coverage is missing.

Hard feasibility uses exact current and reachable quantities, not expected values:

- one atom cannot satisfy two simultaneous reservations;
- dated and transaction reserves remain protected under all credibly reachable states;
- an LP's fully traversed finite-bin exposure accompanies current inventory;
- recovered basis cannot make a runner's current value, downside, or opportunity cost disappear;
- internal custody moves and book credits create no consolidated PnL;
- self-routed owned LP fees are eliminated as internal transfers; and
- missing, stale, conflicting, unsupported, refused, or unrouteable never becomes zero.

Forecast branch economics use one starting portfolio snapshot, a common terminal horizon, exact
external contributions/distributions, and one terminal-liquidation manifest. Opportunity branches
are comparisons, not expenses to subtract repeatedly. A forecasted branch distribution never
becomes landed PnL.

## 11. Why not an artificial prediction market

A literal internal market would require event securities, collateral/budget issuance, order or
cost-function pricing, a market maker or counterparties, an outcome oracle/dispute policy, payout
and solvency rules, and strategic-behavior assumptions. JOSHI currently has one operator, highly
correlated model/prompt agents, a shared sensorium, sparse specialized claims, action-dependent
outcomes, and frequent censoring/route refusal.

Artificial bankroll would therefore mix:

- forecast confidence with assigned wealth and risk preference;
- duplicated agents with apparent liquidity/consensus;
- information with strategic timing and copied forecasts;
- calibration with trading profit and mechanism subsidy;
- a selected action's effect with an exogenous outcome; and
- adjudication ambiguity with a payout dispute.

Even a genuine prediction-market price is a size- and institution-dependent quote formed from
beliefs, preferences, budgets, noise, rules, and friction—not a pure posterior. A market mechanism
becomes worth reconsidering only if JOSHI has many genuinely distinct information producers,
private heterogeneous evidence, fixed adjudicable targets, enough repeated participation, and a
specific reason price formation outperforms direct proper scoring and aggregation. It may never be
needed.

## 12. MVP-to-future-firm ladder

### Stage 0 — contract and instrumentation only

Freeze one decision kind, target vector, standardized size/horizon, simple baseline, censoring
contract, and exact evidence/outcome closure. Reuse the immutable cutoff/universe/calibration
patterns already demonstrated in
[`11_ml_exocortex_foundation.md`](../../implementation/lanes/11_ml_exocortex_foundation.md), but do
not overload its candidate-ranking artifact into this broader claim registry.

### Stage 1 — prospective forecast journal

Log one spot competing-risk occurrence and, when naturally triggered, one runner
retain-versus-liquidate occurrence. Collect a sealed Ember elicitation, base-rate forecast, and at
most one or two simple model/analog baselines. Permit abstention. Render no recommendation and fit
no performance weights.

Define LP and routed-liquidity claim schemas now but leave them disabled until schedule/state,
external-flow/self-flow, terminal-liquidation, and replay support close honestly.

### Stage 2 — adjudication and scorecards

Append mature outcome artifacts, preserve all censored/refused/conflicting denominators, and report
proper score, baseline increment, calibration, support, coverage, and collection burden. The first
twenty prospective episodes may validate the mechanism and operator affordance; they cannot
establish fine-grained calibration or stable regime skill.

### Stage 3 — fixed ensemble

Publish an equal-weight ensemble beside every component and baseline. Seal inputs before ensemble
publication. Keep member lineage and effective member count visible. Advance only after repeated
chronological, outcome-embargoed, nonadjacent evaluation supports the claim family.

### Stage 4 — read-only information allocator

Allocate bounded sensing/model/attention experiments, not capital. Evaluate staged-reveal and
baseline-ablation effects on score, attainable replay regret, errors, latency, attention, and risk.
Retain a cold/random observation slice and complete choice denominator.

### Stage 5 — shadow position-policy laboratory

Let a separately versioned H5 shadow policy consume named forecast/ensemble artifacts plus exact
portfolio constraints. Compare complete attainable spot, runner, LP, and routed branches at common
horizons. It may refuse or nominate; it cannot reserve assets, build instructions, sign, or submit.

### Stage 6 — operator-visible decision support

Show a forecast only after supported chronological calibration and incremental shadow decision
value survive negative controls and measurement sensitivity. Rendering changes Ember's attention
policy, so every material Glass version is a prospective intervention epoch with visibility and
usefulness evidence. Safety/provenance/exposure truth remains non-hideable.

### Stage 7 — future forecasting firm

A mature organization separates claim governance, source acquisition, producer/model lineage,
sealed forecast collection, adjudication, calibration, ensemble, information-budget allocation,
portfolio-policy research, and independent safety review. Forecast operations still do not own a
signer or execution capability. Any later monetary authority follows the separate reviewed graph
defined by JOSHI's foundation.

## 13. Promotion, parking, and durable residue

Park or narrow a claim family when:

- its outcome is mostly ambiguous, differentially censored, unrouteable, or definition-unstable;
- information cutoffs, choice denominators, lineages, or terminal manifests cannot be proved;
- elicitation or display changes Ember's ordinary process enough to erase the intended estimand;
- score gain disappears against simple mechanics, seasonal/state, provider/renderer, future-shift,
  or chronological-regime controls;
- calibration/support fails at the sizes, directions, lifecycles, or regimes where it would be
  shown;
- ensemble gain is duplicated lineage or adjacent-window overfit;
- replay advantage is smaller than quote/fill uncertainty or vanishes after fees, failures,
  terminal liquidation, self-flow elimination, and plausible ordering/MEV sensitivity;
- information rarely changes an attainable shadow decision or increases over-management,
  attention burden, reserve violations, or unresolved exposure; or
- scaling changes market impact, route capacity, correlation, attention, or interference beyond
  registered support.

H3 promotion requires prospective chronological score gain, calibration, negative controls,
support, coverage, and an effect larger than measurement uncertainty. H5 study status additionally
requires the complete attainable action set, common path scoring, presentation-intervention
logging, scale/capacity/tail analysis, and an independently maintained safety boundary. Neither is
execution authority.

This book remains useful if every forecast and policy candidate fails. It leaves a faithful record
of what Ember and the models believed, where outcomes could not be known, which information arrived
too late or cost too much attention, how capital/inventory-time was actually occupied, and which
simple baselines survived. That durable residue is evidence about JOSHI's composite operator
system, not a null verdict on an impoverished proxy.
