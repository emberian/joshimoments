# Wave 6 — active sensing and presentation experiments

Status: research design; read-only observation and presentation only. This document grants no
transaction construction, wallet access, signing, submission, liquidity installation, portfolio
reservation, or autonomous economic authority.

## 1. Decision

Wave 6 should first preserve one **sealed, model-blind baseline epoch**, then study active sensing
and presentation only in separately registered post-baseline epochs.

```text
registered ordinary-use baseline
  -> fixed acquisition and Glass versions
  -> complete census, cold/random/manual/portfolio floors
  -> sealed first-round forecast journal
  -> baseline closes without outcome-responsive extension
  -> separately registered sensing or presentation epoch
  -> assignment before source I/O or reveal
  -> intended decision/intervention
  -> applied, coverage, exposure and nonresponse receipts
  -> outcome closure at the registered knowledge deadline
  -> ITT or explicitly descriptive analysis
  -> only after matured support and cost evidence: registered VOI epoch
```

This order extends, rather than replaces, the [Wave 5 living instrument](../../planning/WAVE5_LIVING_INSTRUMENT.md).
The [source registry](../../implementation/wave5/02_SOURCE_REGISTRY.md),
[collector acquisition boundary](../../implementation/wave5/01_COLLECTOR_ACQUISITION.md), and
[deterministic census-to-hot policy](../../implementation/lanes/21_acquisition_policy.md) remain
the only source, budget and collector-control authorities. The
[Wave 5 Glass sensorium](../../implementation/wave5/03_GLASS_SENSORIUM.md) and
[routed-liquidity Glass contract](../routed_liquidity/05_GLASS_OPERATOR.md) remain the UI and
no-authority boundary. Forecast and information claims inherit the
[epistemic position book](../field_models/EPISTEMIC_POSITION_BOOK.md) and
[information-use frontier](../field_models/INFORMATION_CAPITAL_TIME.md).

Active sensing means allocating bounded **read and attention resources**. Presentation means
changing the order, grouping, salience or explanation of already eligible as-known evidence. They
are different interventions. Neither may reserve assets, alter execution capability, choose a
trade, build an instruction, sign, submit, or claim a landed effect.

## 2. Non-negotiable invariants

1. **Baseline first.** The baseline registration and its exact source, policy, budget, Glass,
   safety and study digests exist before the epoch begins. No active-sensing or presentation arm is
   interleaved with it.
2. **No model influence during the initial journal.** Forecasts, embeddings, model scores,
   disagreement, uncertainty, explanations, retrieved analog rankings and VOI estimates cannot
   affect acquisition, hot leases, cadence, prompts, alerts, ranking, omissions, presentation,
   action affordances or operator attention. Model outputs remain sealed until admissible outcome
   adjudication and retrospective scorecards.
3. **Separate post-baseline registrations.** Each changed sensing rule, floor, assignment scheme,
   presentation policy, safety invariant or analysis contract creates a new epoch. Editing a live
   epoch is prohibited; terminate it and register a successor.
4. **Census is not an arm.** The broad declared census and its gaps continue for every epoch. A hot
   or presented subset never becomes the denominator for itself.
5. **Floors are protected.** Cold, randomized, explicit-manual and portfolio scopes receive
   separately frozen minimum allocations outside experimental competition. Overload degrades or
   stops the candidate arm before consuming a protected floor.
6. **One budget ledger.** A sensing artifact can allocate only an already store-qualified
   `RunBudget`; it cannot mint provider allowance, borrow across dimensions or reinterpret a
   planning profile as permission for I/O.
7. **Intention is not receipt.** Assignment, desired scope, local collector apply, provider
   acknowledgement, healthy coverage, staged presentation, mount, visibility, focus, comprehension
   and operator response remain separate events.
8. **Safety truth is constant.** Authority, identity, source health, freshness, gaps, refusals,
   exact inventory/exposure and other registered safety-critical content cannot be hidden or made
   less accessible by an experimental presentation.
9. **Point-in-time truth.** Inputs require both `valid_at` and `known_by` closure. A later outcome,
   provider correction, interview, family/identity join or model trained through the future cannot
   enter an as-known assignment.
10. **No automatic promotion.** A high score, attractive VOI estimate, favorable PnL, increased
    activity or operator acceptance never widens authority or budgets. Promotion is a distinct
    human-reviewed registration.

These invariants follow the field hierarchy in
[`README.md`](../field_models/README.md): acquisition and attention summaries are H2, forecast or
VOI estimates are H3, and an allocation rule is H5 even when it controls only reads. H5 status does
not imply execution authority. They also preserve the separate product-surface and
coverage/knowledge strata in [`STATE_SPACE.md`](../field_models/STATE_SPACE.md): surfaced,
rendered, visible, focused and acted-on sets are not interchangeable, and every observed stratum
remains conditional on source coverage.

## 3. Epoch protocol

### 3.1 `BaselineEpochRegistrationV1`

The baseline is an ordinary-use measurement epoch, not a convenient retrospective slice. Its
canonical contract is `joshi.wave6.baseline_epoch/v1`. It freezes:

- `baselineEpochId`, occurrence ordinal, registration time and exact predecessor;
- protocol/schema, producer, build, source-tree and configuration digests;
- start, half-open end, maximum duration, outcome knowledge deadline and close rule;
- exact `DailyUseSurfaceProfile`, immutable cockpit publication and presentation-policy digests;
- source-registry, acquisition-policy, collector-plan and registered-run references;
- complete declared census families, eligible-membership artifacts, universe digests, subject
  counts, availability/commit cutoffs, and coverage evidence;
- exact cold, random, manual and portfolio floor schedules by source, operation, fidelity, cadence
  and every budget dimension;
- fixed non-model selection rules and stable tie-breaking;
- eligible operator sessions, decision kinds, study cells, cluster/interference units and minimum
  outcome closure required for descriptive reporting;
- the initial-journal claim definitions, issue deadlines, sealing rule and a literal
  `modelInfluence = prohibited`;
- safety-content digest, accessibility mode set, burden ceilings, privacy/retention class and
  consent version; and
- literal `authority = read_record_replay_only` and `effectCeiling = observe_only`.

The baseline uses Wave 5's fixed census/warm surface and deterministic recency/stable-identity or
explicit operator selection. An activity-blind stratified cold schedule and randomized control
schedule may be frozen at registration; they do not adapt within the epoch. The epoch does not end
early because a result looks favorable and does not extend because it looks weak. Premature stop,
source loss, UI build change or operator withdrawal closes it as incomplete with the denominator
preserved.

The first approximately twenty mature journal occurrences remain a contract, censoring and burden
validation set. They are not sufficient evidence for stable calibration, model skill or VOI.

### 3.2 Post-baseline `ExperimentEpochRegistrationV1`

Every active-sensing or presentation epoch uses `joshi.wave6.experiment_epoch/v1` and names the
closed baseline registration/digest. The registration freezes:

- one primary hypothesis, estimand vector, falsifiers, analysis population and stopping rule;
- `sensing_only`, `presentation_only`, or an explicitly factorial `joint` intervention kind;
- start/end/knowledge deadlines and non-overlap, washout or carryover treatment;
- assignment unit, cluster/interference unit, eligible universe, strata/blocks and allocation
  probabilities;
- all candidate and baseline policy/config digests;
- acquisition and attention budgets plus protected floors;
- required coverage, support and nonresponse states;
- safety, accessibility, consent, privacy and burden invariants; and
- whether analysis may claim randomized ITT, another identified estimand, or association only.

A sensing policy and a presentation policy may share an epoch only under a prospectively registered
factorial design. Otherwise presentation is held fixed during sensing experiments and sensing is
held fixed during presentation experiments. An unregistered interaction invalidates the isolated
causal claim and leaves only a bundled regime comparison.

### 3.3 Epoch closure

Closing an epoch appends a manifest of all eligible units, assignments, decisions/interventions,
applications, coverage, exposures, nonresponses, gaps, withdrawals and outcome states. It reports
planned and actual budget use separately and binds provider-observed billing without calling it an
invoice. Outcome maturation uses the registered knowledge deadline. Unsupported, conflicting,
source-loss, interval-censored, withdrawn and open cases remain in the denominator.

No analysis job may reopen allocation, replace a nonresponding unit, or alter inclusion
probabilities. Corrections append a new closure/adjudication version and cite the superseded one.

## 4. Exact sensing artifact

### 4.1 `SensingDecisionV1`

`SensingDecisionV1` is the immutable pre-I/O allocation occurrence. Its contract string is
`joshi.sensing_decision/v1`. Every field below is required unless explicitly marked optional.

| Field family | Exact content |
| --- | --- |
| identity | decision ID, record ordinal, predecessor, contract/schema, created time, producer/build/config digest, semantic digest |
| epoch | experiment epoch ID/digest, closed baseline ID/digest, study registration ID/digest, policy ID/version/digest |
| cutoff | decision event time, `availableThrough`, `commitThrough`, production time, TTL/open and half-open expiry |
| unit | assignment unit kind/key, public subject kind/key, lifecycle/topology version, cluster/interference ID, registered study cell |
| denominator | every cited census occurrence, membership artifact ID, universe digest/count, availability/commit cutoff, source evidence, coverage evidence and product-parity receipt where applicable |
| eligibility | exact eligible-unit artifact/digest/count, inclusion/exclusion predicates, support state, privacy/retention eligibility and no-later-information proof |
| reasons | sorted typed reasons and evidence links; no hidden free-form score; operator reasons bind command, scene/view and durable acceptance receipt |
| assignment | `floor_cold`, `floor_random`, `floor_manual`, `floor_portfolio`, `candidate_randomized`, `candidate_deterministic`, or `candidate_voi`; arm ID/digest; stratum/block; assignment occurrence; known inclusion probability as exact rational; seed-commit/allocation-table digest where randomized |
| request | sorted source/operation requests with desired fidelity, cadence, start/expiry, retry/gap semantics and requested subject count |
| floors | complete cold/random/manual/portfolio floor vectors before and after this decision, satisfaction evidence and explicit overlap attribution |
| budget | parent registered-run/budget digest; reserved maximum requests, pages, ingress bytes, durable bytes, provider credits, event count and wall time; sorted provider-currency/native-unit caps; attention/prompt/time and privacy-retention limits |
| cost basis | method envelope and registry fingerprint, expected range, worst case, maximum in-flight overshoot, measured-cost evidence cutoff and cost-model version; provider price is not authority |
| baseline | contemporaneous fixed-sensing comparator and activity-blind/random control IDs; no-model baseline digest |
| authority | literal `read_only_no_execution`; no wallet, signer, transaction, route-to-submit, quantity-to-submit, slippage, fee-bid or tip field |

The semantic digest covers canonical bytes excluding only the digest field itself. Decimal integers
and rational probabilities use the repository's exact canonical encodings; floating JSON numbers
are not accepted for budgets, counts or probabilities. Unknown fields refuse.

The artifact is admitted only after the source registry, run budget, denominator, coverage,
evidence, operator acceptance when used, and policy occurrence resolve through the sole store at
the declared commit cutoff. A `candidate_voi` decision additionally requires the gate in section
9. A model-origin proposal cannot be relabeled as manual; manual acceptance is a new operator
occurrence with its own scene and receipt.

### 4.2 Required append-only companions

One decision may lead to these distinct records:

```text
SensingDecision
  -> HotScopeIntent / Desired / Degraded / Closed
  -> collector control reservation
  -> local Applied receipt
  -> provider acknowledgement or refusal
  -> scoped coverage windows, gaps and observations
  -> exact budget settlement
  -> SensingOutcomeClosure
```

`Applied` remains only a local control write. A quiet socket, reconnect, heartbeat, empty page,
`304`, authentication failure or provider acceptance is not positive coverage unless the exact
source contract says so. A subject not actually observed keeps its original assignment and receives
a typed nonresponse; it is never silently replaced.

## 5. Floors, budgets and allocation

### 5.1 Protected floors

Every baseline and experiment registration contains four floor schedules. A floor is a complete
vector by source/operation and cannot be expressed only as a percentage of an aggregate currency.

| Floor | Population and purpose | Allocation rule |
| --- | --- | --- |
| cold | activity-blind subjects outside hot/manual/portfolio nomination; measures unattended coverage and selection drift | deterministic stratified schedule over the complete census; at least one subject in every registered nonempty support stratum, or an explicit infeasible state |
| random | probability-sampled eligible subjects; supplies known inclusion probabilities and a causal/control denominator | reserve at least 20% of non-census hot-subject slots and 20% of each applicable read/attention dimension in the initial profile; use a committed draw within frozen strata |
| manual | explicit Ember nominations independent of model suggestions | reserve at least one mint and one wallet slot when those families are eligible, plus an exact per-source budget; unused capacity does not become evidence against manual value |
| portfolio | every registered in-scope exposure, runner, flat-watch/re-entry or routed-liquidity subject requiring observation | guarantee the registered minimum fidelity/cadence for all eligible portfolio subjects; if the run cannot afford it, refuse the epoch or degrade the experimental arm rather than evict portfolio coverage |

The 20% random minimum is the initial Wave 6 profile, not a timeless optimum. A successor may
change it only in a new prospective registration with a reason. The exact absolute counts and
budget vectors in the registration govern when rounding or small capacity makes the percentage
ambiguous.

A subject may qualify for several floors, but each source-operation allocation has one primary
class and a sorted list of secondary reasons. Overlap never creates extra budget or double-counts
coverage. Initial precedence is `portfolio > manual > random > cold > candidate`; the random draw
still retains its original assignment flag for ITT reporting if a portfolio transition later
changes actual treatment.

The broad minimal census is reserved before these floors and is never paid for from them. Warm
product membership/order and source-specific recovery also retain their own registered reserves.
Only the remainder is eligible for an experimental candidate policy.

### 5.2 Multidimensional budget

For every source/operation `s`, registration must prove:

```text
census reserve(s)
+ recovery/control reserve(s)
+ cold floor(s)
+ random floor(s)
+ manual floor(s)
+ portfolio floor(s)
+ candidate ceiling(s)
<= registered RunBudget(s)
```

The inequality holds independently for requests, pages, response bytes, durable bytes, provider
credits, events, time, each provider currency and each chain-native asset. Chain-native and
provider-currency collections remain empty in this read-only program unless a separate authority
review changes the source registry; a sensing study cannot do so. Attention also has independent
ceilings for assignments, prompts, closeout minutes, notifications and operator session time.

No dimension borrows from another. Unused protected floor does not roll into a candidate arm during
an epoch. Worst-case response and in-flight overshoot are reserved before I/O. First ceiling
exhausted stops the candidate arm; disk/control pressure can stop the whole collector before its
protected reserve. Intended, reserved, locally observed and provider-billed costs are reported
separately.

### 5.3 Deterministic allocation order

At each registered decision opportunity:

1. materialize the full eligible census and denominator closure;
2. assign portfolio and accepted-manual scopes under their protected rules;
3. execute the precommitted random draw and cold stratified schedule without looking at candidate
   activity or outcome proxies;
4. satisfy source recovery and minimum coverage obligations;
5. allocate only the remaining candidate envelope using the registered rule;
6. rank equal candidates using frozen keys and stable identities;
7. reserve worst-case budget, commit `SensingDecisionV1`, then create a `HotScopeIntent`; and
8. append every desired/applied/coverage/settlement transition without rewriting the decision.

Resource pressure removes or slows the candidate arm first, then cold detail above its minimum. It
never fabricates coverage and never uses performance, PnL or model rank to erase a losing, cold or
unattended census member.

## 6. Exact presentation artifact

### 6.1 `PresentationInterventionV1`

`PresentationInterventionV1` is the immutable assignment and staged prescription committed before
reveal. Its contract string is `joshi.presentation_intervention/v1`.

| Field family | Exact content |
| --- | --- |
| identity | intervention ID, record ordinal, predecessor, contract/schema, created time, producer/build/renderer/config digest, semantic digest |
| epoch | experiment epoch and study registration IDs/digests, closed baseline ID/digest, hypothesis ID, declared estimands/falsifiers |
| unit | operator/session, scene and decision-opportunity IDs; assignment and cluster/interference units; study cell and sequence/period for crossover |
| cutoff | full as-of vector, catalog/source/chain/projection cutoffs, maximum input availability, assignment time, stage deadline and reveal deadline |
| evidence | immutable Glass view ID/digest/mode, eligible evidence/item artifact and digest, exact census/choice-set closure, coverage/gaps/refusals and authority rungs |
| assignment | mechanism, eligible arms and digests, assigned arm, exact rational probability, strata/block, seed-commit/allocation-table digest, manual-selection reason when nonrandom, and concealment/blinding state |
| policy | presentation policy ID/version/digest; eligible, selected, planned-render and omitted item sets; semantic placement/order/salience; filters, toggles, comparison set and progressive-disclosure state |
| safety | invariant safety-content digest, required persistent authority/freshness/gap/refusal/inventory fields, evidence-equivalence assertion and prohibited omissions |
| accessibility | accessibility profile; keyboard/focus order; semantic table/text alternatives; target size; contrast/non-color encoding; reduced-motion; zoom/reflow; live-region policy and renderer capability receipt |
| burden | prompt count, closeout duration, session/study time, interruption class, cooldown, notification ceiling, voluntary skip/withdraw path and capture-failure fallback |
| authority | literal `read_record_replay_only`, `evidence_only` commands and `observe_only` effect ceiling |

The staged artifact is a prescription, not proof of pixels, viewport intersection, focus, attention
or comprehension. After reveal, append distinct `PresentationReceipt`, `Mount`, `Visibility`,
`Viewport`, `SemanticFocus`, `Control`, `Gesture`, `UsefulnessReport`, `CaptureGap`, `Withdrawal` and
`OutcomeClosure` occurrences. Each cites the intervention ID/digest and preserves event, render,
receive, persistence and availability clocks.

If staging or receipt fails, serve the fixed safety/baseline view and record
`presentation_not_witnessed`; do not block ordinary observation or external manual execution. A
client-side label cannot promote itself to durable exposure evidence. The witnessed replay serves
the exact stored bytes; retrospective outcomes arrive in a distinct view.

### 6.2 Presentation constancy and variation

Across presentation arms, hold constant:

- the eligible as-known evidence and its availability cutoff;
- the safety/authority strip, gaps, refusals and exact material inventory/exposure truth;
- source and sensing policy unless the epoch is explicitly factorial;
- decision kind, choice set, size/direction/horizon and outcome contract; and
- interaction capability: no arm gains an execution or capital effect.

Permitted candidates include graph-first versus table-first, alternate grouping/order, concise
versus expanded explanations, provenance disclosure order, or retrieval ordering. No arm may use
outcome-responsive salience, remove a warning, reorder beneath pointer/focus, imply that a model is
fact, or turn a recommendation into a primary action affordance.

## 7. Assignment, nonresponse and support

### 7.1 Assignment designs

The preferred initial designs are deliberately small:

1. **Sensing micro-lottery.** Within a frozen lifecycle × source-health × family/territory ×
   portfolio-status stratum, randomly assign eligible non-floor subjects to additional read depth
   or the fixed baseline cadence. Randomize before activity inside the treatment window and retain
   exact inclusion probabilities.
2. **Presentation crossover.** Within consenting ordinary-use sessions, randomize two safe policies
   by session or bounded decision block, balance order, register washout, and cluster inference by
   operator episode and overlapping market window. Do not alternate during one urgent gesture.
3. **Parallel clustered presentation.** Assign by session/day or nonoverlapping episode cluster
   when carryover cannot plausibly wash out. Preserve the same evidence and safety content.
4. **Factorial read-only study.** Only after separate sensing and presentation seams work, cross a
   sensing assignment with a presentation assignment to estimate the bundle and interaction. The
   resulting information is never treated as the isolated value of the source without the relevant
   arm contrast.

Portfolio and urgent manual scopes are not withheld for experimental symmetry. Their comparisons
are descriptive unless a safe encouragement or timing design has separately justified assumptions.
Manual policy selection likewise supports association, not a display-effect claim.

Primary analysis is intention-to-treat by registered assignment. Per-protocol or actual-exposure
analysis is secondary and must address the post-assignment selection it introduces. A complier
effect needs a valid instrument, exclusion restriction, monotonicity/support argument and
interference analysis; it is not inferred from a mount receipt.

### 7.2 Typed nonresponse

Every assigned unit ends in exactly one first-level state:

```text
completed_covered
completed_partial_coverage
source_unavailable
source_gap_or_disconnect
budget_refused_before_io
budget_exhausted_after_start
control_not_applied
provider_not_acknowledged
privacy_or_retention_refused
presentation_not_staged
presentation_not_mounted
exposure_capture_incomplete
operator_skipped
operator_withdrew
superseded_by_safety_fallback
outcome_censored_or_unsupported
```

Each state retains assignment, reason evidence, clocks, costs actually incurred and remaining
coverage/outcome status. A skipped report is not a negative usefulness rating. A missing viewport
event is not proof of no view. Authentication failure is unknown product coverage, not absence.
Differential nonresponse by arm is itself a result and a possible stop condition.

### 7.3 Coverage and support report

Every result reports, per arm and registered cell:

- full census count and exact denominator digest;
- eligible, assigned, desired, applied, provider-acknowledged, healthily covered, exposed, focused,
  responded, outcome-matured and analyzed counts;
- cold/random/manual/portfolio/candidate allocation and overlap;
- coverage duration, cadence, gaps, finality/correction and state-completeness grade;
- inclusion probabilities, effective sample size and cluster/window overlap;
- cost and attention vectors, not one efficiency score;
- every nonresponse/censoring category and worst supported strata; and
- drift across source, renderer, UI, topology, lifecycle and operator-process versions.

Unknown or deterministic inclusion probabilities cannot be invented after the fact. Weighting and
off-policy evaluation are allowed only on logged support with known probabilities and adequate
effective sample size.

## 8. Causal questions and falsifiers

### 8.1 Active sensing

The first causal estimand is narrow: assignment to additional read depth changes **retained
observation and downstream registered information/usefulness outcomes** for eligible subjects under
the registered source, budget and coverage regime. It is not the causal effect of market attention
or trading.

Candidate outcomes include observation yield, exact closure gained, source-loss rate, target
adjudicability, later proper-score increment of a fixed model, retrieval usefulness, time to a
registered relevant-evidence event and attention/burden. If the resulting information is shown to
Ember, that reveal is a second intervention or part of a registered joint bundle.

Reject, narrow or stop the sensing claim when:

- the candidate fails to improve supported closure, score or usefulness over fixed cold/random and
  simple cheapest-source baselines;
- apparent gain disappears when the full assigned denominator and nonresponse are restored;
- costs, gaps, privacy burden or latency exceed the registered frontier;
- activity-conditioned acquisition manufactures the apparent event acceleration;
- results reverse or vanish in the cold/random slice, chronological holdout or source-health
  strata;
- improvement depends on future joins, outcome-informed TTL, provider/renderer leakage or
  post-assignment relabeling;
- effective sample size or support is inadequate for the cells where the policy would operate; or
- hot observation displaces portfolio/manual floors or makes the broad instrument less useful.

### 8.2 Presentation

The primary causal estimand is ITT: assignment to one safe presentation policy changes a registered
operator usefulness/safety vector while eligible evidence and authority remain fixed. Outcomes may
include orientation/source-gap corrections, appropriate abstention, time to relevant evidence,
attainable replay-regret components, unwanted-conversion recognition, navigation burden,
over-management, alert fatigue, accessibility/pain and tool abandonment. PnL is only an
independently reconciled secondary link and never proves causality by itself.

Reject, narrow or stop a presentation claim when:

- ITT improvement is absent, below measurement uncertainty or confined to self-report while errors
  or burden worsen;
- an effect appears only after conditioning on mount, focus, action, survival or complete capture;
- renderer latency, missing content, source coverage or safety-content differences explain the arm
  contrast;
- sequence, learning, novelty or carryover effects overwhelm the registered crossover estimand;
- graph/heatmap salience induces unsupported continuity, route or confidence inferences;
- faster gestures increase mistakes, unwanted conversion, overtrading, FOMO or unresolved
  exposure;
- keyboard, screen-reader, reduced-motion, touch, zoom/reflow or pain results are worse in any
  critical task; or
- the exact staged presentation and witnessed scene cannot be proved.

### 8.3 Controls

Minimum controls include activity-blind cold/random subjects, future-shift features, unrelated
same-window subjects, provider/source-health strata, cached-payload/parser-quarantine windows,
renderer-version controls, hidden-versus-visible safe panels, randomized retrieval order, explicit
`none_analogous`/`cannot_articulate_yet`, and chronological outcome embargo. Inference clusters by
episode, mint/family/territory, route/topology and overlapping market window where shared futures
or spillovers are possible.

## 9. VOI gate

Forecast-informed sensing is prohibited until all of the following are simultaneously true for the
exact claim family and study cells:

1. B3 scorecards contain repeated, matured, chronological, outcome-embargoed and nonadjacent
   prospective occurrences beyond the initial mechanism-validation set;
2. the candidate has supported calibration and proper-score increment over a lifecycle/state or
   simple-mechanics baseline, with negative controls and uncertainty larger than neither quote nor
   measurement error;
3. source/method costs, in-flight overshoot, coverage, gap/nonresponse and attention burden have
   been measured in completed non-VOI epochs;
4. the complete census, cold/random/manual/portfolio floors and known assignment probabilities can
   be preserved;
5. any EVSI claim names the complete attainable action set, abstention/refusals, exact
   direction/size, common downstream policy and a declared utility; and
6. a separately reviewed `candidate_voi` epoch freezes the estimator, fit cutoff, cost evidence,
   budget, TTL, inclusion rule, assignments, support boundary and stop conditions.

Before this gate, VOI is offline exploratory analysis only. Uncertainty, disagreement, novelty,
entropy, forecast score or a proposed VOI value cannot alter a live read. After the gate, the
primary output remains the multidimensional information/resource frontier—score, attainable replay
regret, support/coverage, capital/inventory-time, attention, latency, fees, risk and unresolved
exposure. A ratio is a secondary predeclared view, never the objective optimized in isolation.

EVSI allocates observation, model and attention resources only. It grants no portfolio budget,
reservation, trade, LP, route, signer or submission authority.

## 10. Accessibility, consent and burden

The study must remain usable as the ordinary instrument:

- participation, optional utterance/transcript and retrospective interview consent are separately
  versioned; skip and withdrawal are always available without loss of ordinary evidence access;
- no research question, annotation or forecast elicitation blocks urgent inspection or the direct
  escape to external manual execution;
- critical controls are keyboard reachable, at least 44×44 CSS pixels, visibly focused and stable;
- tables/text summaries are authoritative equivalents for charts, graphs, heatmaps, ladders and
  waterfalls; no hover-only or color-only evidence exists;
- screen-reader landmarks/order, live-region restraint, reduced motion, 200% text/reflow and
  nonprecision input work in every arm;
- a live update may change values but cannot reorder beneath pointer, focus, inspection or a
  gesture; new order requires explicit acceptance;
- safety, gap, refusal and authority information remains present at scan level; density changes
  explanation, not evidence availability; and
- capture or presentation failure surfaces a typed gap but never traps the operator in the study.

The initial burden ceiling is at most two presentation assignments in one ordinary session, one
optional closeout of at most 90 seconds per assignment, no more than 15 total study minutes per
seven-day window, and no unsolicited notification solely to complete research. Ember may lower any
ceiling immediately. Raising one requires a new consented epoch and an earlier burden report.
Manual sensing requests and ordinary product annotations do not count as experimental compliance,
but their physical burden is still reported.

An arm fails accessibility if any critical task lacks actual keyboard, screen-reader,
reduced-motion, zoom/reflow or large-target evidence. DOM tests alone cannot establish operator
accessibility or pain reduction.

## 11. Reflexivity and gaming red team

The observation map is endogenous, as formalized in
[`IDENTIFIABILITY_AND_UNITS.md`](../field_models/IDENTIFIABILITY_AND_UNITS.md), and the UI is part of
the composite policy described by [`FIELDS_AND_OPERATORS.md`](../field_models/FIELDS_AND_OPERATORS.md).
Treat each material sensing or presentation version as a regime boundary.

| Attack or feedback loop | Required defense |
| --- | --- |
| optimize clicks, dwell, opens or trade count | exclude them as success metrics; report physical burden and registered usefulness/safety outcomes |
| select high-activity/easy-outcome subjects, then claim better information | retain complete census plus cold/random floors; analyze assigned denominator and support |
| call a model suggestion “manual” after Ember clicks it | retain model-proposal lineage; require a new operator acceptance occurrence; initial journal rejects the path entirely |
| spend protected floors on candidate reads or count overlap twice | primary allocation class, exact budget vectors, floor-satisfaction receipts and independent audit |
| retry or replace failed treatment units until one responds | no substitution; typed nonresponse and original assignment remain |
| adapt TTL/cadence after seeing favorable events | fixed decision TTL/cadence; successor decision uses only inputs known at its cutoff |
| show a score/explanation that creates a label later learned as predictive | model-blind initial journal; exposure-version regimes, hidden/crossover control and later-label exclusion |
| presentation creates FOMO/manual flow, then market response validates it | retain manual action and landed-effect clocks; cluster/spillover analysis; never call response exogenous |
| random floor is technically present but too sparse to challenge the policy | absolute counts plus per-dimension minimums, effective-sample-size gate and worst-stratum report |
| choose a favorable metric, numeraire or denominator after outcome | freeze vector estimands and denominator; ratios of sums only as secondary views |
| suppress censored, refused, inaccessible or abandoned cases | immutable eligible denominator and exhaustive nonresponse/accessibility tables |
| use repeated prompts/checkpoints as independent evidence | lineage groups, effective member count and leave-one-lineage-out checks |
| change renderer/source version inside an arm | terminate epoch or analyze as an explicit bundled regime boundary |
| alerting increases observation density and apparent event intensity | preserve assignment time, baseline cadence and cold/random observation; test activity acceleration against coverage |
| optimize toward current portfolio and forget the broad market | protected census/cold/random coverage and portfolio reported as a distinct floor, not the universe |

Audit checks should include byte-level replay of assignments, impossible model-input sentinels in
the initial-journal path, budget/floor recomputation, outcome-shift tests, duplicate/noncanonical
record refusal, changed same-ID conflict, and proof that presentation controls cannot invoke a
wallet, transaction builder, signer or submit route.

## 12. Stop, park and residue

Stop an active epoch immediately when:

- a safety-critical field differs across presentation arms or execution authority appears;
- a registered floor, run budget, privacy/retention limit or protected control reserve is crossed;
- randomization, canonical assignment replay or assignment-before-I/O/reveal cannot be proved;
- operator consent is withdrawn, urgent use is impeded, or accessibility/pain burden breaches its
  ceiling;
- widespread source/renderer failure destroys the registered treatment contrast; or
- unregistered model influence enters the initial journal or a pre-VOI sensing decision.

Park or narrow the candidate after closure when support is too sparse, nonresponse is differential,
cost exceeds benefit, the cold/random slice contradicts it, effects vanish under controls, UI
reflexivity dominates, burden increases, or scaling changes capacity/interference beyond support.

Failure preserves useful residue:

- the broad census, field-specific gaps and fixed cheap acquisition baseline;
- cold/random/manual/portfolio coverage and measured cost envelopes;
- exact scenes, presentations, exposures, annotations and accessibility evidence;
- source/coverage, nonresponse and burden atlases;
- operator-usefulness vectors and negative/contradiction fixtures; and
- the sealed forecast journal and retrospective scorecards.

If active sensing fails, keep census plus human nomination. If presentation fails, keep the
accessible evidence/safety view. If VOI fails, keep measured costs and calibrated components. None
of these failures weaken the living instrument.

## 13. Build and study sequence

1. **Freeze contracts offline.** Implement strict canonical schemas and adversarial fixtures for
   baseline/experiment epochs, `SensingDecisionV1`, `PresentationInterventionV1`, companion
   receipts, nonresponse and closure. Prove unknown-field, later-evidence, digest, predecessor,
   duplicate and authority-widening refusal.
2. **Replay the baseline path.** Against dynamic fixtures, close census → protected floors → fixed
   hot scopes → immutable Glass → scene/exposure → budget/coverage closure across crash/restart.
   Inject model sentinels and prove they cannot affect source control or presentation bytes.
3. **Run the sealed baseline.** Use one fixed source/acquisition/Glass stack for the registered
   window. Keep the initial forecast journal mutually blind. Close honest gaps, burden and first
   matured/censored occurrences without fitting an allocation policy.
4. **Exercise non-model sensing.** Run a small post-baseline sensing micro-lottery with fixed Glass,
   known probabilities, cold/random/manual/portfolio floors and only a provider-promoted C1/C2 or
   later separately reviewed canary ceiling. Demonstrate assignment, apply, gap, cost and restart
   closure before expanding.
5. **Exercise presentation.** With sensing fixed, run one two-arm accessible presentation study.
   Prove receipt-before-reveal, exact witnessed replay, safety equivalence, fallback, crossover or
   cluster accounting and voluntary closeout burden.
6. **Close causal reports.** Publish ITT denominators, nonresponse, coverage/support, accessibility,
   costs, uncertainty, falsifiers and regime limits. Do not promote from favorable screenshots or
   one operator anecdote.
7. **Repeat chronologically.** Replicate across nonadjacent windows and source/market regimes while
   retaining simple and cold/random controls. Measure drift after each material source or Glass
   change as a new epoch.
8. **Open VOI only if earned.** After repeated matured B3 support plus measured cost/coverage and
   the section 9 gate, register a bounded `candidate_voi` epoch. Keep it read-only, floor-protected,
   shadow-evaluated and independently stoppable.
9. **Consider operator-visible models separately.** Even a successful sensing allocator does not
   pass the epistemic book's operator-visibility gate. Forecast display requires its own supported
   calibration, incremental shadow-decision, negative-control, usefulness and safety evidence.

The first successful Wave 6 result may be negative: a sealed baseline and a well-powered random
slice can show that adaptation or a novel layout adds no supported value. That is a valid result
because the instrument, denominator and no-authority boundary survive it.
