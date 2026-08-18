# Wave 5 — learning and field lab research specification

Status: retained research specification, subordinated on 2026-08-17 to the primary execution plan
[`WAVE5_LIVING_INSTRUMENT.md`](WAVE5_LIVING_INSTRUMENT.md). No trading, liquidity deployment,
transaction construction, signing, submission, or autonomous economic authority.

This document preserves the detailed estimator packages, artifact contracts, baselines,
falsifiers, compute budgets, routed-liquidity acquisition envelope and transfer limits developed
for Wave 5. It is **not** the current critical path. In particular:

- the old `W5.A` price-object spine is now a set of independent per-venue/profile capabilities;
- the epistemic position book begins early rather than hiding inside late model-registry work;
- cockpit, scientific memory and earlier-only retrieval do not wait for forecast or fill skill;
- the advanced model and coupled-controller packages are an incubator with local entry gates; and
- the project reports independent maturity/health vectors rather than one `Wave 5 complete` flag.

Wave 4 ended at an honest `useful_partial`. The living-instrument plan owns the missing nonfixture
circulation, daily product, memory and first witness. This specification applies only after the
named evidence, dataset, mechanics and known-truth prerequisites for a research package actually
exist.

## Executive decision

Build the lab, but do not build a generic ML platform and do not build an autonomous trader.

The useful objective is an **operator exocortex with a scientific memory**:

```text
market census -> selective hot observation -> witnessed operator scene
              -> episode/choice/gesture/interview record
              -> immutable point-in-time dataset
              -> descriptive field and learned estimate artifacts
              -> chronological evaluation
              -> explanation in Glass
              -> shadow policy branch only
              -> later outcome and falsification
```

The target is not one next-return predictor. It is Ember's composite process of market selection,
attention, interpretation, entry, management, partial realization, runner retention, exit,
flat-watching, re-entry, and coupled spot/LP inventory control. The system should first make that
process observable and retrievable. It may then estimate local response, risk, and opportunity
conditional on the information actually available at a decision.

The ambitious program is warranted because the durable residue is valuable even if every learned
trading hypothesis fails: point-in-time market memory, exact episode accounting, scene retrieval,
typed chart/social/route fields, coverage-aware research, and a better operator surface. Wave 5 is
not warranted if its only acceptable outcome is profitable autonomous execution.

## 1. Non-negotiable research constitution

1. **The decision is the unit of evaluation; the episode is the unit of behavior.** An isolated
   chart row is neither. Choice sets, abstentions, runners, flat intervals, and re-entry survive.
2. **Selection is part of the phenomenon.** Preserve the census → surface → render → viewport →
   inspection → arm → choice/abstention denominators. Ember's attended slice is adaptive sensing,
   not a random sample of the market.
3. **Knowledge time is enforced, not documented after the fact.** Every join selects the effective,
   non-retracted version whose evidence was available by the decision cutoff and whose event/slot
   validity covers the queried instant. Outcomes have their own later availability cutoff.
4. **Epistemic types do not coerce.** Observed facts, deterministic protocol projections,
   descriptive fields, fitted estimates, latent explanations, operator perceptions, presentation
   interventions, shadow proposals, and landed outcomes remain visibly different artifacts.
5. **A price is a typed object.** Mark, marginal quote, exact-size route quote, fill, full
   liquidation, and stress value do not substitute for one another.
6. **A field is not a metaphor.** Every field names its domain, carrier, topology, units, reference
   measure, clock, observation operator, coverage, cutoff, and transformation law. There is no
   canonical scalar called pressure, momentum, quality, conviction, or alpha.
7. **Observed response is not causal reaction.** A response kernel, Hawkes fit, wallet graph,
   chart embedding, cluster, LLM interpretation, or ghost replay earns only its declared claim.
8. **One household inventory underlies every book.** Slow edge, medium LP schedule, and fast spot
   policies have separate causes and clocks but share exact balances, reservations, terminal
   liquidation, and opportunity constraints. Internal transfers cannot create PnL.
9. **Simple models remain live controls.** Complex models must beat appropriate seasonal,
   persistence, concentration, analog, exact-mechanics, and do-nothing baselines prospectively.
10. **No Wave 5 artifact carries economic authority.** It may request attention, render evidence,
    record an operator declaration, or create a hypothetical branch. It cannot build, sign, or
    submit an action.

## 2. Optional full-stack research capstone

This section is a non-normative capstone example under the primary living-instrument plan. It is
not the definition of Wave 5 product success, and none of its advanced packages is a universal
prerequisite. If the named local capabilities mature, one registered question may eventually walk
end to end through:

- a repeated production snapshot export with source and coverage closure;
- a deterministic point-in-time decision dataset with the witnessed choice universe;
- versioned feature, field, label, model, prediction, evaluation, and explanation artifacts;
- an earlier-only baseline and at least one more ambitious candidate;
- rolling chronological evaluation with calibration and decomposed uncertainty;
- an actual witnessed presentation and optional operator gesture/interview;
- a read-only active-sensing decision with an auditable inclusion denominator;
- a coupled spot/LP/ghost-edge shadow branch over one exact portfolio state; and
- later outcome ingestion, drift/coverage monitoring, and a promotion or rejection record.

No part of that path may depend on a notebook's hidden state, a mutable “latest features” table, a
manually copied CSV, an unversioned prompt, or a model service that cannot reproduce its inputs.

## 3. Historical research-package dependency sketch

The following diagram records the original research-program decomposition. It is superseded as an
execution DAG by `WAVE5_LIVING_INSTRUMENT.md`: `W5.A` is now per-capability, the epistemic book is
early, and every advanced package has local prerequisites rather than one global join.

```text
Wave 4 evidence/projections/exports
  |
  +--> W5.A price-object calibration and Book baseline spine
         |
         +--> W5.0 registry and artifact spine
  |      |
  |      +--> W5.1 production dataset releases --> W5.4 baselines/retrieval
  |      |                                  |      W5.5 kernels/survival/points
  |      |                                  |      W5.6 graph/field models
  |      |                                  |      W5.7 chart/social ensembles
  |      |                                  +----> W5.8 registry/inference/evaluation
  |      |
  |      +--> W5.2 operator supervision --> W5.9 presentation experiments
  |      +--> W5.3 known-truth lab -------> every estimator gate
  |
  +--> W5.10 active sensing/census-to-hot --> witnessed scenes and new datasets
  +--> W5.11 coupled shadow controllers ----> prospective evaluation only
  +--> W5.12 drift/coverage observatory ----> refuse, retrain proposal, or demotion
  +--> W5.13 explanation adapter -----------> Glass, with evidence classes intact

Far-future W5.F formal seam observes stable contracts; it is not on the critical path.
```

The graph is intentionally a DAG for one release. New observations create a new release; they do
not mutate an old one. Iteration happens by adding versioned artifacts and prospective evaluation
windows, not by reopening scored history.

## 4. Concrete lanes

### W5.A — price-object calibration and Book baseline package

For a mechanics-dependent study, select only the named Pump curve, PumpSwap, DLMM, route or LP
profile capabilities it actually consumes. A profile may independently acquire the following
objects; this is not an ordered all-venues gate on model capacity:

```text
exact source bytes + coherent account closure
  -> versioned venue state/profile
  -> mark + marginal + direction × size quotes/refusals
  -> attempted simulation/transaction when lawfully observed
  -> finalized landed fill/effect or explicit failure
  -> whole-position and stressed liquidation
  -> durable projection and witnessed Glass price stack
  -> manifested calibration rows
```

This lane also freezes one bounded prospective market census with a random cold-mint stratum and
authoritative signed-flow semantics. Its initial products are multi-price signature plots, event-
and wall-time sign ACFs, seasonal/activity baselines, repeated-wallet/route versus residual flow,
exact quote/fill/landing shortfall, and an observed AMM response atlas with deterministic protocol
motion shown separately. It does not fit Hawkes, propagator, HDIM, latent-liquidity, or policy
models yet.

When naturally available, a named LP study may add one real provider path and management episode:
position versions, fills, fees, claims, edits, withdrawal basket, per-leg quotes/refusals, terminal
liquidation, witnessed scenes, partial/full exit, flat-watch, and possible re-entry. This makes
exact accounting and episode machinery confront a prospective path before controller optimization.

Gate for each dependent study: cross-runtime encodings agree; state age, route, coverage and
finality are explicit; and every consumed price/accounting object has the required named
capability. Failure blocks only claims that consume that profile. Use `RL-C0…RL-C6` for routed-
liquidity causal claims; `M0…M7` remains the Book-study namespace.

### W5.0 — hypothesis, estimand, and artifact spine

Extend the existing SQLite/CAS, manifested-Parquet and typed-admission authority with the semantic
research manifest families in section 5. Do not build a second file catalog, model database or
research truth registry.

Deliverables:

- `StudyRegistration` for each question before its confirmation interval;
- schemas and validators for the common artifacts in section 5;
- content-addressed artifact bytes in the existing CAS, with occurrence IDs separate from content
  digests and store-resolved admission;
- a CLI to register, validate, inspect, compare, and refuse artifacts;
- a machine-readable claim ladder `H0` exact settlement through `H5` policy; and
- an append-only `PromotionDecision` recording who/what admitted, rejected, froze, or superseded a
  candidate and why.

The authority must accept exploratory registrations. Exploration is prominently labeled, can
generate later hypotheses, and cannot be relabeled confirmation. A confirmatory registration
freezes its estimand, eligible universe, split, metrics, baselines, multiplicity family,
falsifiers, and stop/go thresholds before the scored interval opens.

Gate: a dependency cycle, missing digest, unknown unit, mutable path, future cutoff, or prohibited
claim prevents admission.

### W5.1 — production point-in-time dataset factory

Extend the existing `joshi.analysis.snapshot/v1` workbench into scheduled, reproducible jobs that
consume only Wave 4 immutable exports. Keep DuckDB/PyArrow/Parquet as the durable boundary and
Polars or NumPy/SciPy as in-process tools when a named job benefits.

Deliverables:

- decision-candidate, episode, route-exercise, social-transition, liquidity-state, and
  operator-scene dataset specifications;
- complete witnessed choice sets and separate market-census/risk-set tables;
- bitemporal join primitives with adversarial tests for revisions, retractions, identity versions,
  lifecycle/topology changes, future labels, source gaps, and administrative censoring;
- deterministic train/calibration/evaluation partition manifests;
- dataset quality reports with exact row/universe counts, missingness reasons, coverage windows,
  gap IDs, support cells, and as-known cutoffs; and
- one command that rematerializes a release byte-for-byte from registered inputs.

Features and labels are separate releases. Outcome materialization may run only after its horizon
and required source availability close. An unobserved outcome is `right_administrative`,
`source_loss`, `interval`, `competing_event`, or another typed state—not zero and not an implicit
negative.

Gate: run daily for 30 consecutive eligible days with no unexplained row/universe drift, no
future-information acceptance, reproducible logical digests, and explicit refusal on incomplete
required closure. Optional empty relations remain truthful empty relations.

### W5.2 — operator supervision and high-resolution scene memory

Turn Ember's actual working vocabulary into structured, revisable supervision without forcing it
into premature labels.

Deliverables:

- low-friction scene-bound marks for disposition, crackle type, why-now, intended horizon,
  confidence/urgency when volunteered, willingness to convert each asset, alternatives considered,
  and `cannot_articulate_yet`;
- chart drawings anchored in semantic coordinates—feed/venue, price object, event interval,
  price/size units, mint, episode, and scene—with a stored pixel-to-data transform and renderer
  version;
- optional voice/text utterances, consent and transcript provenance, and structured interpretations
  that never replace the source utterance;
- replay interviews that first hide outcomes, record the contemporaneous account, then optionally
  reveal outcomes in a separately marked retrospective phase; and
- compensation/supersession links instead of in-place correction.

Labels are multi-valued observations: Ember may simultaneously see a microdip, a social transition,
a runner candidate, and inadequate evidence. A later model may propose a taxonomy; only Ember can
adopt it as operator vocabulary. Interview-derived labels carry `outcome_visible` and cannot train
a decision-time model unless the feature specification explicitly uses only pre-outcome content.

Gate: Ember recognizes the replayed scene and can correct the machine's interpretation without
clerical friction. If capture changes the behavior being studied or impairs urgent inspection,
reduce it.

### W5.3 — estimator-specific known-truth generators

Begin with small deterministic generators and adversarial fixtures for each estimator. They are
contract and estimator test benches, not evidence that the real market follows a simulator. Build
a reusable hybrid laboratory only after repeated duplication establishes that it is cheaper and
clearer than the small generators.

A future shared scenario library may selectively combine the relevant subset of:

- exact CPMM/DLMM-like reserve or bin transitions, fees, capacity, rounding, and refusal;
- router switching, split paths, route loss, arbitrage latency, same-slot ordering, and MEV stress;
- lifecycle and graph topology creation/destruction;
- seasonal, overdispersed, self-exciting, inhibiting, and common-cause event processes;
- wallets and social actors with known aliases, false cluster cues, territory spillovers, and
  latent confounding;
- adaptive census-to-hot observation with known inclusion probabilities and source outages;
- operator-like partial labels, omitted attention, and presentation-dependent observation; and
- same-shaped charts generated by different mechanisms plus different-shaped charts generated by
  the same mechanism.

Every estimator gets a recovery case, a non-identifiability case in which it must return an
equivalence set or refusal, and a failure case that defeats a tempting shortcut. Exact topology
goldens preserve tail `-1`, head `+1`, `B1 @ B2 == 0`, unit/carrier homogeneity, orientation
equivariance, and checked refusal rather than narrowing wide atom domains to `int64`.

Gate: the pipeline recovers quantities inside predeclared tolerance where identifiable and refuses
or widens uncertainty where truth is deliberately not identifiable. Good real-data fit cannot
waive this gate.

### W5.4 — analog, chart-shape, and retrieval baselines

Make the memory useful before asking it to predict.

Start with:

- earlier-only episode retrieval by exact lifecycle, liquidity, size, route, attention, and
  operator context;
- normalized descriptive chart vectors with named price object and sampling policy;
- dynamic-time-warping or fixed-distance nearest neighbors with missingness-aware comparison;
- simple shape summaries such as return path, range, drawdown, realized variation, jump count,
  volume/flow imbalance, quote capacity, and age; and
- semantic retrieval over operator utterances/social text only when the embedding model, prompt or
  encoder, input cutoff, and text coverage are registered.

Retrieval output says “earlier episodes similar under specification S,” never “will do the same.”
The returned neighbors include later outcomes only in retrospective mode. A witnessed decision
view can show the earlier evidence available at those analog decisions without leaking their
future into the current model input.

Gate: invariance to row order and future rows, stable neighbor identities under deterministic
replay, interpretable distance components, and useful operator retrieval versus simple filters.

### W5.5 — response kernels, survival, and point-process studies

Promote the existing synthetic prototypes into production research artifacts only after the named
W5.1 data release and that estimator's W5.3 recovery/refusal adversaries pass.

Candidate estimands include marked caller/wallet response over trade intensity, signed flow,
liquidity response, attention and typed prices; competing risks for send/fade/migration/route loss;
and time-varying episode hazards for exit, partial realization, runner retention, zap, and re-entry.

Required order:

1. seasonal Poisson, negative-binomial, empirical hazard, Kaplan–Meier/Aalen–Johansen, and simple
   covariate survival baselines;
2. event/wall-time sign ACF, IID/shuffled sign controls, and simple DAR/Markov persistence;
3. descriptive nonparametric response kernels with overlap/support and time-varying baseline;
4. a linear signed-flow propagator baseline that separates known instantaneous AMM curve motion
   from subsequent response, followed by a frozen-predictor TIM/HDIM-style asymmetry challenger;
5. multiplicative or additive hazard candidates and an actual marked Hawkes likelihood; and
6. only then multivariate or context-conditioned kernels with interactions and nonstationarity.

All long-form marks join bitemporally to the selected identity/topology/regime version. General
events need not fabricate a choice, wallet, territory, size, or healthy coverage-window ID.
Administrative censoring is not source loss. Hawkes parameters remain candidate self-excitation
descriptions, not contagion or causal influence. The existing `hawkes_window_excitation_candidate`
is a fixed-window arrival screen; it may serve as a diagnostic but may not be renamed or promoted as
a Hawkes fit. Likewise an observed recovery ratio is not propagator resilience.

Gate: out-of-window likelihood/calibration and residual diagnostics beat the named seasonal and
overdispersion baselines; parameter recovery succeeds in known-truth cases; conclusions survive
coverage and common-cause sensitivity. Otherwise retain only the descriptive kernel.

### W5.6 — graph, topology, and dynamic-field studies

Represent the market as several typed, changing domains rather than one wallet network:

- wallet/asset transfer and co-participation graphs;
- caller/social/territory attention graphs with selected identity versions;
- venue/pool/route graphs with direction × size capacity and refusal;
- episode/lifecycle state-transition complexes; and
- the operator surface and observed attention path.

Initial observables are participant concentration, signed net flow, cycle counts, component
turnover, route capacity, divergence, circulation, fixed-topology Hodge components, local
susceptibility, observed response per flow, and gap sensitivity. They are vectors over declared
carriers and units. “Energy” is reserved for a defined squared norm, not a market substance;
“impact” is reserved for an identified intervention or explicitly named observational response.

A topology epoch fixes nodes, oriented edges, faces, carrier assets, reference domain, units, and
construction version. Topology changes create boundaries or mapped transitions; matrices are not
silently padded across epochs. Asset flows in canonical `decimal256(39,0)` domains may not be
narrowed to an `int64` prototype. The real adapter must widen or refuse.

Gate: field models beat net-flow, concentration, route-capacity, and cycle baselines on a held-out
decision-relevant outcome; preserve units and gauge/equivalence tests; and remain useful when one
layer is ablated. If not, ship the simpler observables.

### W5.7 — chart, social, and multimodal ensembles

Only after W5.4 establishes an interpretable baseline, compare sequence, image, graph, and text
representations.

Candidate components:

- event-time and wall-time chart sequence models over typed price/quote/flow channels;
- rendered chart encoders whose renderer, viewport, overlays, and pixel-to-data transform are part
  of the input manifest;
- social-text classifiers or LLM extractors for claims, actor roles, callout type, stance,
  novelty, community transition, and uncertainty;
- graph/field encoders over fixed topology epochs; and
- late-fusion ensembles that retain each component's prediction, availability, calibration,
  support, and missingness rather than forcing all inputs into one latent score.

LLM output is a versioned latent interpretation with model/build, prompt/template, decoding
configuration, source text IDs, availability cutoff, structured schema, citations, and abstention.
It cannot establish identity, truth of a claim, causality, or future price. Licensed/private text
and deletion obligations remain explicit inputs to retention policy.

Gate: each modality must add prospective, calibrated decision-level value beyond W5.4 and the
other modalities, survive missing-modality evaluation, and avoid learning renderer, provider, or
post-outcome artifacts. Otherwise omit it from the ensemble.

### W5.8 — model registry, versioned inference, and evaluation

The model registry is initially a set of admitted artifacts and reproducible jobs, not an online
model server. A model package contains portable parameters only if its framework format is bounded
and independently validated; framework-native serialization is not the durable source of truth.

Deliverables:

- reproducible training jobs and canonical `ModelPackage` manifests;
- batch `InferenceRun` artifacts keyed to exact decision/candidate/universe and cutoff;
- rolling-origin train/calibration/evaluation plans with horizon embargo and episode/group overlap
  exclusion;
- calibration artifacts and reliability reports by lifecycle, regime, size, direction, coverage,
  and operator-selection stratum;
- scale-decay and attention-hour value curves; and
- automatic baseline, ablation, negative-control, leakage, and future-row-invariance comparisons.

Evaluation is keyed to the decision and its complete choice set. Ranking measures coexist with
proper scoring rules, calibration, abstention/coverage curves, survival/competing-risk metrics,
tail error, and shadow portfolio consequences. Random row cross-validation is prohibited.
Training, calibration, and final evaluation intervals are disjoint. Pair, territory, operator
episode, lifecycle, and topology grouping are applied where they can transmit information.
The multidimensional information-use frontier and its capital-time, persistence, presentation,
and identification estimands are specified in
[`INFORMATION_CAPITAL_TIME.md`](../research/field_models/INFORMATION_CAPITAL_TIME.md).

Uncertainty remains a bundle:

```text
sampling/model | irreducible/outcome | censoring | source coverage
selection/support | topology/identity | regime drift | scenario/sensitivity
```

One interval may summarize a specifically defined component, but Glass cannot present it as total
uncertainty.

Gate: deterministic rerun, known-truth tests, baseline superiority, chronological calibration,
acceptable worst-stratum behavior, and a full model card. No aggregate metric can hide failure in
the action size, regime, or coverage cells where the model will be shown.

### W5.9 — presentation-policy experiments

Treat Glass layout and explanation as interventions on the operator, not neutral output.

Start with manual, versioned assignments among graph-first, chart/analog-first, ladder-first,
fee/markout-first, and coupled-capital-first presentations. All retain the safety strip, authority,
as-of/coverage, exact asset direction, quote/refusal, and source-health elements. A staged
presentation scene is not proof of exposure; receipt, mount, visibility, semantic focus, and
control events are separate observations.

Offline replay can randomize presentation under a registered usability protocol. Prospective
read-only randomization requires Ember's explicit consent, bounded burden, immediate opt-out, and a
policy that cannot hide safety evidence or change economic authority. Do not optimize directly on
PnL. Initial outcomes are orientation corrections, time to relevant evidence, useful retrieval,
unwanted conversion recognized, source-gap resolution, operator rating, and abandonment of the
surface.

Gate: a presentation earns wider use only if it improves a predeclared usefulness/safety outcome
without increasing correction, over-management, or capture burden. A profitable episode is not
evidence that the layout caused it.

### W5.10 — active sensing and census-to-hot policies

The first online policy is a **read acquisition policy**. It allocates finite observation and
operator-attention budgets without trading.

Keep a cheap, broad census over the eligible universe and a richer hot scope for selected
candidates. Each `ScopeLeaseDecision` records the complete eligible set, cheap census features,
policy/build, budget and acquisition cost, selected sources/entities, selection probability when
known, exploration mechanism, TTL, reason, cutoff, and subsequent coverage. Human nominations are
a separate selection mechanism and remain in the denominator.

Begin with transparent policies: fixed random sample, lifecycle/coverage strata, recency/novelty,
and operator watchlist. Then compare uncertainty sampling or value-of-information heuristics.
Always retain a census/random control slice so the hot surface does not become the only known
market. Unknown or deterministic inclusion probabilities block inverse-propensity claims; they do
not become estimated after the fact. Off-policy evaluation is limited to logged support and is not
a license to extrapolate into unseen market regions.

Gate: the candidate policy improves registered information yield or operator usefulness per
acquisition/attention cost while preserving census coverage and underrepresented lifecycle
strata. If it only rediscovers what Ember already selects, keep it as an assistive watchlist.

### W5.11 — ghost-edge and coupled spot/LP shadow controllers

Build one read-only coordinator over three separate clocks:

- slow: edge absent/proposed/shadow/installed/paused/retiring/retired;
- medium: hold/add/remove/redistribute/claim/refuse as modeled schedule transformations; and
- fast: observe/arm/buy/sell/partial-realize/runner/zap/flat-watch/re-enter/refuse as hypothetical
  spot effects.

The coordinator consumes one reconciled portfolio, acceptable-inventory set, simultaneous
reservations, exact route/bin projections, route/quote freshness, and operator policy versions. It
emits separate `ShadowPolicyDecision` occurrences and exposes conflicts. It cannot silently net a
crackle buy against an LP-driven reduction or call a withdrawal a sale.

The first ghost-edge controller is deliberately simple: a frozen directional schedule competes
only when its exact-size output exceeds the observed best competing plan by a registered hurdle;
otherwise it is absent. Sequential inventory updates, external-flow versus self-flow, route-share
brackets, repricing/arbitrage scenarios, toxicity/ITR or LVR-like diagnostics, capital-time,
schedule friction, and terminal liquidation follow the routed-liquidity contracts. The actual
no-edge/operator path, fast-only path, unchanged schedule, and joint path remain visible.

The first spot controller is equally plain: on an operator-nominated candidate, wait for a
predeclared quote-relative dip, create a shadow entry only if exact reserve/quote/coverage bounds
pass, then apply frozen partial-exit/runner/flat-watch/re-entry rules. This is a mechanism and
accounting baseline, not a claim that microdips are profitable.

Gate: deterministic branches reconcile to exact native quantities and terminal liquidation;
every credible partial ordering respects the acceptable-inventory set or visibly refuses; and a
prospectively frozen joint policy beats do-nothing, fast-only, edge-only, unchanged-schedule, and
actual-operator baselines after coverage, friction, capacity, and attention cost. Passing this gate
permits a better shadow, not a live action.

### W5.12 — drift, coverage, and support observatory

Monitor the evidence and model boundary before monitoring headline score.

Artifacts report source delivery lag/gaps, schema/profile changes, feature missingness, universe
size/composition, lifecycle and topology transitions, identity/territory uncertainty, prediction
support, calibration drift, residual drift, route/refusal drift, label maturity, and operator
selection shift. Compare current windows to the exact admitted training/reference release using
effect sizes and control charts suited to serial dependence; do not promote p-value alarms alone.

Actions are typed: `healthy`, `warn`, `suppress_explanation`, `refuse_inference`,
`request_recalibration`, `request_retrain`, `demote`, or `retire`. Automatic retraining and automatic
promotion are prohibited. A source outage may suppress a model while exact accounting remains
healthy.

Gate: injected source gaps, delayed labels, schema changes, unseen categories, out-of-support
sizes, and calibration breaks trigger the expected refusal/demotion without rewriting prior
artifacts.

### W5.13 — model-to-Glass explanation without truth laundering

Glass receives a versioned `ExplanationBundle`, not free-form model prose. Each statement is a
typed claim with:

- subject, decision/scene, model/prediction/evaluation IDs and digests;
- authority rung and claim kind (`observed`, `deterministic`, `descriptive`, `fitted`, `latent`,
  `operator`, `counterfactual`, or `shadow`);
- exact value/vector, unit, horizon, route/price object, domain/topology, and cutoff;
- support, uncertainty components, coverage/gaps, calibration stratum, and relevant baseline;
- source citations and any negative evidence, contradiction, refusal, or omitted component;
- permitted wording and prohibited inference; and
- explanation renderer/template/build plus occurrence ID and digest.

The UI renders these classes separately. It may say “three earlier episodes are similar under
distance S,” “this fitted hazard is calibrated on stratum R,” or “the ghost schedule would quote
better on this frozen cut.” It may not turn them into “the coin will send,” “this caller caused the
move,” “the LP stabilized price,” or “execute.” An LLM may paraphrase an admitted bundle only if
every sentence maps back to claim IDs; unsupported prose is refused.

Gate: adversarial examples cannot promote fitted or counterfactual content into fact, hide a gap,
replace exact units with a score, or imply authority. The semantic table remains available when a
visual or prose explanation fails.

### W5.F — far-future formal-methods seam

Do not implement Lean in Wave 5. Preserve a narrow seam for formal work after contracts stabilize:

- a typed transition-system IR for evidence revisions, bitemporal selection, episode state,
  topology epochs, portfolio reservations, and slow/medium/fast shadow transitions;
- temporal properties such as no-future-input, no-double-reservation, no-shadow-to-ledger
  mutation, receipt-before-witnessed-exposure, and every landed effect reconciles or remains a
  named residual;
- bounded SMT/model-checking or TLA+/Alloy-style counterexample search for partial-operation and
  concurrency paths;
- program synthesis from partial operator specifications only inside the known-truth lab, with
  generated candidates treated as hypotheses; and
- circuit/hybrid-system abduction returning equivalence classes, gauges, and discriminating
  experiments rather than one asserted hidden cause.

Formal methods can prove properties of a frozen model and implementation relation. They cannot
prove market causality, model calibration, profitability, or that the formalized acceptable set
matches Ember's actual intent. The seam is documentation plus stable typed boundaries until a
repeated failure justifies mechanization.

## 5. Artifact contracts

All artifacts use canonical bytes, an occurrence ID distinct from the content digest, schema and
producer/build identity, `created_at`, full input IDs/digests, and append-only supersession. Hashes
are algorithm-qualified. Timestamps name clock and precision. Exact atom domains preserve their
full width.

### 5.1 `StudyRegistration`

Required closure:

```text
study occurrence ID + registration digest + version/supersedes
exploratory | confirmatory | replication
authority rung and exact permitted/prohibited claims
question, target object, estimand, treatment/exposure/action, comparator
eligible universe/risk set, decision/episode unit, interference neighborhood
choice-set and operator-selection definitions
outcomes, competing events, horizons, price/route/liquidation objects
feature/label specifications and availability rules
baselines, negative controls, counterexamples and falsifiers
train/calibration/evaluation intervals, groups, embargo and multiplicity family
metrics, uncertainty procedure, support/coverage thresholds, stop/go rules
operator/presentation burden and maximum compute/storage budget
author, registration time, scored interval open/close, status
```

### 5.2 `DatasetRelease`

Required closure:

```text
dataset occurrence ID + logical/content digest + spec/schema/build/config digests
study registration ID/digest
input snapshot IDs and table logical digests
catalog/source/chain/projection as-of vector and knowledge mode
event-valid and availability cutoffs; outcome cutoff separately when labels exist
eligibility, census, risk-set, choice-universe and universe-digest rules
primary/entity keys, row/table counts, exact partitions and deterministic ordering
coverage scopes/window/gap IDs; missingness, censoring and competing-risk taxonomy
feature or label spec references, never an implicit mixture
quality checks, refusal state and temporal partition manifest
```

### 5.3 `FeatureFieldRelease`

Each feature or long-form field component adds:

```text
feature/field ID and semantic version
authority rung; observed/deterministic/descriptive/fitted status
domain and entity carrier; topology epoch/version/orientation
physical and semantic units, asset/numeraire/reference measure
event clock/order, lookback/aggregation, availability cutoff and validity interval
formula or estimator/build/config; mechanical component versus learned residual
eligible-input logical digest, separately from supplied-source digest
coverage/missingness/support and uncertainty components
gauge/equivalence class, invariance tests, baseline, falsifier and valid scope
```

Labels never inhabit this artifact. A field bundle cannot mix carrier assets/units/domains merely
because rows share a topology label.

### 5.4 `LabelRelease`

Labels bind decision/episode/candidate, outcome definition, event and availability time, horizon,
price/route/liquidation object, censoring kind and bounds, competing event, source coverage, label
build, and maturity state. Later revisions append a new version. Retrospective operator labels and
landed accounting outcomes remain distinct columns/artifacts.

### 5.5 `ModelPackage`, `InferenceRun`, and `EvaluationReport`

`ModelPackage` binds algorithm/family, portable parameters or bounded loader, source/build/env lock,
training release/partitions, feature schema/order/units, objective, seed/determinism, baselines,
known limitations, and admitted use. `InferenceRun` binds model, feature release, exact
decision/candidate/choice-universe, cutoff, prediction vector, uncertainty bundle, calibration
artifact, support/refusal, and output content digest. `EvaluationReport` binds scored label release,
chronological partition, metrics/strata, calibration, abstention, scale decay, baselines, ablations,
negative controls, sensitivity, failures, and claim decision.

An ensemble retains member predictions and missing-member state. Its combined value does not erase
member provenance or create a universal score.

### 5.6 `PriceCalibrationRelease`

The calibration spine binds exact source/state/profile bytes, asset direction and size grid, all
price-object kinds, quote/refusal and its availability/freshness, attempted simulation/transaction
when observed, landed signature/status/finality/effects, full costs, post-state, whole-position and
stress liquidation, chart/render convention, coverage, and error decomposition. A failed or absent
attempt remains part of the denominator. Legacy Glass decimals, mock projection vectors, or a
calculator result without the observed state cannot populate this release.

### 5.7 `OperatorSupervision` and `PresentationExperiment`

These bind witnessed scene/view and presentation IDs/digests, full as-of vector, eligible and
served items, planned placement/omission, actual receipt/visibility/focus/control events, gesture or
utterance source, semantic coordinates, operator-declared values, capture clock, consent, outcome
visibility, interpretation build, and compensation/supersession. Planned display is not observed
exposure; exposure is not attention; attention is not causal usefulness.

### 5.8 `SensingDecision` and `ShadowPolicyRun`

`SensingDecision` binds census universe/digest, policy/build, costs/budget, selected hot scopes,
known inclusion probabilities or `unknown`, exploration stratum, TTL, cutoff, resulting coverage,
and operator nomination. `ShadowPolicyRun` binds starting reconciled portfolio, three policy
versions, acceptable-inventory and reservation sets, route/bin/quote/calculator artifacts, action
choice sets and refusals, branch state transitions, stochastic seeds if any, terminal horizon and
liquidation manifest, result vector, residuals, and explicit `read_only_no_execution` authority.

### 5.9 `ExplanationBundle`, `DriftReport`, and `PromotionDecision`

The explanation contract is defined in W5.13. `DriftReport` names current/reference releases,
metrics, serial-dependence method, thresholds, affected scopes, evidence gaps, and proposed
suppression/demotion. `PromotionDecision` cites all required gates, reviewer, admitted presentation
scope, expiry/review condition, and exact rejected claims. None can grant transaction authority.

## 6. One walking shadow-policy path

The first end-to-end path should be one pair and one operator-nominated candidate, not the whole
market and not a portfolio optimizer.

1. **Register before scoring.** Freeze the question: can a cheap census plus operator nomination
   identify episodes worth hot observation, and does a simple witnessed microdip/partial-exit rule
   plus a frozen ghost LP schedule improve terminal-liquidated shadow wealth and operator
   usefulness against named baselines? Register horizons, sizes, acceptable inventory, costs,
   outcomes, baselines, and falsifiers.
2. **Cut the census.** Wave 4 exports all eligible candidates at cutoff `t`, source gaps, and the
   exact rendered/available surface. W5.10 chooses hot leases using a fixed stratified policy and
   preserves a random census control.
3. **Witness the scene.** Glass stages a safe presentation, receives it before reveal, records real
   visibility/focus, and offers earlier-only analogs. Ember may nominate, abstain, mark a chart
   region, choose a disposition, or say `cannot_articulate_yet`.
4. **Materialize the decision.** W5.1 freezes the complete candidate/choice universe, operator
   selection, available chart/social/route/LP fields, and coverage. The current outcome is absent.
5. **Infer as an estimate.** The baseline and candidate ensemble emit separate send/fade/exit-risk,
   response, and route-capacity estimates with calibration, support, and uncertainty. No model
   selects or sizes an actual trade.
6. **Explain without recommendation.** Glass shows exact facts, mechanical route/bin results,
   analogs, fitted estimates, disagreements, gaps, and counterfactuals in separate sections.
7. **Fork shadow state.** Starting from one exact household portfolio, create do-nothing,
   actual-operator, simple spot, frozen ghost-edge, and coupled spot/edge branches. Apply exact
   quote latency, sequential inventory, simultaneous reservations, self-route elimination,
   partial-order failures, and terminal liquidation. Every proposed action remains hypothetical.
8. **Advance only from new evidence.** Later snapshots update each branch under its frozen policy;
   no branch sees the subsequent price path when deciding. Exit, partial realization, runner,
   flat-watch, re-entry, LP fill, fee, withdrawal, and residual inventory retain separate events.
9. **Mature outcomes.** After the registered horizons and availability delay, publish a separate
   label release with competing events, administrative/source-loss censoring, landed actual path,
   fixed-demand ghost results, and explicitly model-dependent behavioral results.
10. **Evaluate and interview.** Score decisions and complete episodes chronologically. Replay the
    witnessed scene with outcomes hidden before the later interview. Measure calibration,
    coverage, scale decay, terminal branch results, attention cost, and operator usefulness.
11. **Monitor and decide.** Drift/support gates suppress invalid estimates. The registry records
    continue, revise as exploration, begin a new prospective registration, demote, or retire.

This single path exercises every important boundary. It is successful even when the model loses,
provided it reveals why, preserves exact operator memory, and refuses unsupported claims.

## 7. Baseline ladder

Every study selects the smallest relevant members; “baseline” does not mean one universal model.

| Question | Required simple baselines before sophistication |
| --- | --- |
| candidate/episode outcome | base rate by lifecycle and horizon; persistence/last value; regularized logistic or discrete hazard |
| time to send/fade/exit/re-entry | empirical hazard; Kaplan–Meier/Aalen–Johansen; simple Cox or additive hazard with predeclared covariates |
| event intensity/response | seasonal Poisson; negative-binomial; time-of-day/lifecycle strata; shuffled-mark and shifted-time controls |
| chart shape | exact filters; descriptive vector + scaled Euclidean/DTW kNN; prior-return/variation controls |
| social/text | source/caller base rates; bag-of-words or regularized linear model; content-free source/time control |
| wallet/graph | participant count/concentration; signed net flow; component size; cycle count; label-permutation control |
| route/liquidity | exact native quote; canonical-only/external-only/aggregate route; size-capacity curve; no-edge and unchanged schedule |
| active sensing | census random sample; lifecycle/coverage strata; operator watchlist; cheapest-source policy |
| presentation | existing Glass order; table/text-only; manually selected view; mandatory safety strip in all arms |
| coupled controller | remain flat/do nothing; actual operator; fast-only; edge-only; unchanged LP; liquid SOL/hold; terminal liquidation |

Tree ensembles, neural encoders, Hawkes models, graph embeddings, LLMs, and hybrid controllers are
candidates only after the corresponding row is measured. If a complex candidate cannot beat its
baseline outside training time, the baseline is the promoted result.

## 8. Chronological evaluation and falsification

### 8.1 Partition protocol

- Use rolling origins with a fixed training interval, later calibration interval, and still later
  untouched evaluation interval.
- Embargo by maximum outcome horizon plus ingestion/revision latency; purge overlapping episode,
  actor/cluster, pair, territory, route, and topology groups where they leak shared futures.
- Report both expanding-window and bounded-window results when drift is plausible.
- Hold out at least one lifecycle/regime transition and test unseen or explicitly unsupported
  topology/identity states.
- Freeze preprocessing, feature selection, hyperparameter search, thresholds, ensemble weights,
  and calibration before opening each evaluation window.
- Multiple exploratory searches share a registered multiplicity family. A promising retrospective
  partition creates a new prospective study; it never becomes its own holdout.

### 8.2 Decision-level outcomes

Measure selection uplift relative to the full eligible universe and matched choice sets, entry
timing conditional on selection, management/exit/re-entry, partial-exit/runner value, abstention,
attention-hours, capital-time, and scale-decay. Separate:

```text
operator selection effect
timing conditional on the selected candidate
management conditional on entered inventory
interaction among selection, timing and management
```

These are not automatically causal. Ember selects what to inspect; an entered position reveals
only outcomes under that path; alternative exit/re-entry paths are partially observed. Off-policy
evaluation is limited to explicit logged choice probabilities and overlap. Matched choice sets,
g-computation, inverse weighting, or doubly robust estimates are sensitivity analyses only when
their assumptions and support are credible. Otherwise report descriptive uplift and bounds.

### 8.3 Promotion metrics

Use proper scoring and decision-relevant diagnostics: log loss/Brier, calibration slope/intercept
and reliability, time-dependent survival calibration, integrated Brier score, competing-risk
calibration, ranking within witnessed universes, abstention/coverage curve, tail error, support
fraction, and exact shadow branch consequences. Block/bootstrap uncertainty respects serial and
territory clustering. Report worst supported strata and sensitivity, not only averages.

### 8.4 Hard falsification gates

Demote or stop when any of the following holds:

- future values, later universe membership, retrospective identity, or outcome-visible annotation
  affects an as-known artifact;
- results disappear against a simple temporal/lifecycle baseline or negative control;
- calibration fails in the intended displayed/action stratum;
- value is confined to missing/unobserved choice sets or unsupported extrapolation;
- estimated benefit disappears under full-size quote, friction, capacity, terminal liquidation,
  self-flow elimination, or attention cost;
- topology/units/gauge changes reverse a supposedly invariant conclusion;
- a causal story has no observed mechanism, fails pre-trends/placebos, or is smaller than coverage
  and measurement uncertainty;
- known-truth tests show false identification or unjustified confidence;
- operator capture or presentation changes behavior more than it assists; or
- the result requires repeatedly redefining regimes, outcomes, or episode boundaries after seeing
  them.

## 9. Promotion ladder

| Stage | Artifact may do | Required evidence | Explicit ceiling |
| --- | --- | --- | --- |
| P0 fixture | validate schema/math/contracts | deterministic goldens and adversarial failures | no real-market claim |
| P1 descriptive research | summarize/retrieve past evidence | point-in-time dataset, coverage, baseline | no prediction or causal claim |
| P2 fitted retrospective | emit registered estimate on held history | chronological holdout, calibration, known-truth tests | research view only |
| P3 prospective shadow | emit estimate before outcomes and score later | repeated prospective windows, support/drift gates | no actual action |
| P4 operator assist | show admitted estimate/explanation in Glass | prospective value plus usefulness/safety evidence | read/record/propose only |
| P5 coupled shadow policy | advance hypothetical spot/LP branches | exact inventory reconciliation, conservative costs, stable prospective advantage | no build/sign/submit |
| P6 tiny-live proposal | ask a separate program whether a bounded experiment is justified | independent safety, authority, protocol, signer, loss-budget, and recovery review | not authorized by Wave 5 |

There is deliberately no automatic promotion. P4 or P5 artifacts expire or demote on coverage,
drift, profile, topology, or model-version change. A model that predicts well but produces an
unusable or misleading surface does not earn P4.

## 10. Compute, storage, and environment budget

Budgets are hard initial ceilings, not performance promises. Record actual wall time, CPU/GPU
time, peak memory, bytes read/written, cache use, and retained artifact size in every run manifest.

| Tier | Purpose | Initial ceiling |
| --- | --- | --- |
| T0 commit/fixture | contract, leakage, unit, synthetic golden tests | 15 minutes, 8 GiB RAM, 2 GiB scratch, CPU only |
| T1 daily production | snapshot validation, dataset/features, baselines, batch inference, drift | 2 hours elapsed, 64 GiB RAM, 250 GiB scratch, 25 GiB newly retained |
| T2 weekly research | rolling evaluation, bootstrap, graph/kernel/ensemble candidates | 12 hours elapsed, 96 GiB RAM, 1 TiB scratch, 100 GiB newly retained |
| T3 isolated accelerator | only a registered chart/text/graph experiment that exceeded measured CPU budget | one 24 GiB-class GPU for at most 8 hours/job, 40 GPU-hours or USD 150/month, whichever comes first |

The default remains the locked local Python environment: DuckDB/PyArrow for exchange and query,
NumPy/SciPy plus statsmodels/scikit-learn for numerical/statistical work, NetworkX for small graph
goldens, and Matplotlib for static research plots. Notebooks are thin viewers; canonical work is a
tested job with a manifest. Julia, JAX/NumPyro/DynaMax, specialized Hawkes packages, or GPU stacks
live in separate probe environments and cannot become the authority by convenience. OCaml/C# or
Rust integration occurs through schema-validated Arrow/Parquet/canonical JSON, not embedded
runtime objects. Rust owns exact evidence, protocol/accounting math, export, and safety; a measured
serving need must exist before porting a model.

Wave 5 stores derived immutable releases, parameters, predictions, evaluations, and explanations;
it does not duplicate Wave 4 raw evidence into a second truth database. Begin with a 2 TiB hot
derived-artifact ceiling and a separately inventoried archive. Retain every artifact cited by a
promotion decision; deduplicate by content digest; expire unregistered scratch; never delete a
registered release merely to satisfy a quota. If three consecutive T1 runs exceed a ceiling,
measure partition/pruning improvements before requesting more infrastructure.

Remote/cloud use requires a registered job, encrypted immutable input release, no wallet/provider
keys, explicit data-retention region, egress/cost ceiling, and returned artifact verification. A
GPU is justified only after an interpretable CPU baseline and small-scale learning curve show that
the model—not broken data—benefits from scale.

### 10.1 Routed-liquidity acquisition envelope

The current routed-liquidity data audit constrains the plan more sharply than the generic T1/T2
ceilings. Public Solana BigQuery is a landed-signature/program index and independent rendering, not
a historical quote or point-in-time pool-state archive. Wave 5 must reject a historical ghost-edge
dataset that contains only BigQuery rows. Credible route work needs Wave 4 forward-captured complete
pool-account writes plus contemporaneous Jupiter/direct-venue quote witnesses tied to state/slot
and receipt clocks.

Use the audited two-stage path when historical candidates are needed: clustered program/pool
signature discovery, then narrow raw transaction hydration and a signature-clustered BigQuery
cross-check. Start with one closed UTC day and a `10 GiB` maximum-billed dry-run/query cap. The
measured base planning envelope is roughly `10 GB` scanned, `60 MB` raw transaction download, and
`100 MB/day` compacted transactions + forward state + quote witnesses; the compact uncertainty
range is approximately `5 MB–5.5 GB/day`. Run a seven-day feasibility scope of three mints,
10–30 pools, both directions, and three decision-relevant sizes before requesting 30 days.

The routed dataset is admitted only if at least 99% of candidate signatures hydrate or have bounded
gaps, the RPC/BigQuery conformance sample agrees at least 99.5% with every discrepancy classified,
all direct-quote state accounts are present, ALT/CPI variants round-trip, and quote witnesses bind
to reproducible state rather than nearest wall time. A 30-day release requires effective paired
opportunities and a later temporal holdout; 90 days is conditional on a surviving registered edge
or sparse-regime question, never the default snarf. Failure shelves ghost-edge claims while leaving
descriptive route archaeology available.

## 11. Subordinate research-package sequencing

These phases describe one possible order after the corresponding living-instrument data and
capabilities exist. They do not govern ignition, cockpit or scientific-memory implementation; the
primary plan's phases and independent maturity vector take precedence. Thirty-day support and a
coupled shadow are study-specific gates, not project-wide completion requirements.

### Phase A — trustworthy production memory

Validate W5.A, then build W5.0–W5.3. Materialize one decision/episode dataset repeatedly, capture
operator marks and chart drawings, and make the known-truth lab attack every temporal/unit/topology
contract. Do not let routed-liquidity detail displace the market-wide price/flow/response spine.

Exit gate: at least one admitted real price/state/quote/fill/liquidation calibration family, one
bounded prospective signed-flow census with a cold stratum, 30 eligible daily releases,
deterministic reruns, zero accepted leakage fixtures, truthful empty/gapped states, and
operator-recognizable replay.

### Phase B — useful simple exocortex

Build W5.4, the baseline parts of W5.5/W5.6, W5.8, and a minimal W5.13. Ship earlier-only analog
retrieval and exact descriptive field bundles to replay Glass.

Exit gate: retrieval beats manual filters on a registered usefulness measure, explanations retain
claim types/units/cutoffs, and no predictive claim is needed for the surface to be useful.

### Phase C — calibrated candidate models

Run response/survival, graph/field, chart, social, and multimodal candidates against the baseline
ladder. Use W5.3 for recovery/refusal and W5.8 for rolling evaluation.

Exit gate: at least one candidate has repeated chronological calibration and incremental value in
its intended support; all others are explicitly rejected, retained as descriptive tools, or kept
exploratory.

### Phase D — learn what to observe and show

Build W5.9, W5.10, and W5.12. Start with manual presentation assignment and stratified/random
census controls. Let active sensing spend only read/attention budgets.

Exit gate: improved information or operator usefulness per cost without census collapse,
underrepresented-regime loss, increased correction, or hidden safety truth.

### Phase E — optional coupled walking-shadow capstone

If its local mechanics, inventory and evidence gates mature, build W5.11 and run the path in section
6 over prospectively frozen intervals. Couple ghost-edge
and spot branches through exact inventory, reservations, opportunity, and terminal liquidation.

Exit gate: semantic/accounting closure and stable prospective evidence after conservative costs.
The only Wave 5 decision is continue/demote the shadow. Any tiny-live proposal is a new program.

## 12. What must not be built in Wave 5

- no generic feature-store service, Kafka/event-bus sprawl, distributed training platform, graph
  database, vector database, Kubernetes model mesh, or always-on model server;
- no autonomous entry, exit, LP installation, add/remove/rebalance, hedge, transaction builder,
  signer, wallet key path, or “temporary” live bot;
- no one scalar market pressure, coin score, alpha, edge quality, toxicity, confidence, or total
  uncertainty that erases typed components;
- no mutable latest-feature table, notebook-only result, pickle-as-truth, or silent online model
  update;
- no random row cross-validation, future peak/multiple label in an event-time feature, outcome-
  visible interview leakage, retrospective universe reconstruction, or current identity join;
- no hindsight-best episode boundary, coin, route, LP width, exit, regime, or terminal horizon
  presented as a tested strategy;
- no provider forecast, chart candle, simulation, ghost replay, or LLM prose laundered into landed
  fact or causal truth;
- no importance-weighted or synthetic counterfactual beyond logged support presented as observed;
- no self-routed fee counted as external revenue and no internal book credit counted as household
  PnL; and
- no formal proof theater: proving code properties cannot establish a profitable strategy or a
  correct social-market ontology.

## 13. Research-package decision boundary

Under the primary living-instrument plan, each lab package proceeds only when its local exact,
point-in-time evidence and known-truth gates exist. It earns complexity one model, one estimand and
one prospective window at a time; its failure cannot demote the cockpit, scientific memory or
epistemic journal.

If the sophisticated models fail, keep the evidence substrate, operator vocabulary, analog memory,
exact route/LP/spot glass, baselines, and coverage observatory. If active sensing fails, keep the
broad census and human nomination. If ghost/coupled controllers fail, keep exact inventory and
terminal branch accounting. If explanation fails, show typed tables and source artifacts.

That asymmetry is the reason to build the lab: every speculative layer is removable, while the
underlying instrument remains useful. The project becomes foolish only if it mistakes the
speculative layer for the foundation or uses retrospective success to skip the prospective gates.
