# Wave 6 — operator-model program

Status: research specification only. This defines future evidence and analysis boundaries; it authorizes neither an execution path nor a claim that Ember's language is market truth.

## Purpose

The program studies this composite, scene-bound process:

```text
available market / social / product evidence
  + Ember's memory, portfolio, alternatives, and current state
  -> partly articulable perceived configuration
  -> observable attention, semantic acts, intentions, abstentions, and later accounts
  -> independently reconciled economic effects and later outcomes, when available
```

Its question is narrow: which components of a witnessed scene help describe and prospectively recognize Ember's distinctions without turning those distinctions into causal or economic facts? It is not a universal disposition taxonomy, a predictor, or a scalar “pressure” score.

This follows the field-bundle constraint in [JOSHI_THOUGHT](../../../JOSHI_THOUGHT.md#embers-phenomenology-a-field-bundle-not-a-pressure-score), the field corpus's authority ladder in [FIELDS_AND_OPERATORS](../field_models/FIELDS_AND_OPERATORS.md#8-constitutive-operators), and the existing scene/act/replay boundary in [Wave 5 scientific memory](../../implementation/wave5/06_SCIENTIFIC_MEMORY.md).

## Non-negotiable separations

### A bundle, never an aggregate

At decision cut `d`, preserve a component bundle, not a number:

```text
B_d = (
  timing and signed exact size,
  liquidity susceptibility and resilience,
  caller and actor context,
  wallet and inventory context,
  social and attention context,
  chart and episode-memory context,
  compression and release hypotheses,
  fresh-mint/lifecycle/topology context,
  PvP churn and participant replacement,
  portfolio and competing-opportunity context,
  coverage and scene/presentation context,
  unnamed residual
)
```

Every component is a family of typed observations or hypotheses. It can be unavailable, contradictory, `not_applicable`, or unresolved; it is never silently zero-filled. The components have different domains, units, clocks, and identifiability. A candle, exact-size quote, caller assertion, wallet-cluster hypothesis, social post, and reconciled balance effect are not commensurate forces.

“Pressure” is permitted only as Ember's verbatim language or an explicitly scoped analogy. It never names a universal latent, an API field, a model target, or a displayed aggregate. AMM mechanics make this stricter: exact-size curve/bin traversal and dynamic topology replace LOB queues, spread, and queue depletion; a DLMM bin is not FIFO depth. See [TRANSFER_LIMITS](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md).

### Evidence layers do not overwrite one another

| Layer | Meaning | It is not |
| --- | --- | --- |
| source/chain observation | retained evidence with coverage and clocks | complete market state |
| deterministic projection | replayable calculation from named inputs | causal explanation |
| statistical/latent estimate | versioned conditional distribution or hypothesis set | source truth |
| operator assertion | what Ember said, marked, or selected then | ground-truth label |
| presentation occurrence | prescribed/rendered/visible conditions | attention, comprehension, or persuasion |
| semantic act or intention | evidence-only declaration | transaction, fill, or position change |
| reconciled economic effect | finality- and boundary-qualified balance change | Ember's thesis or a good outcome |
| outcome | later measured path under another cutoff | evidence available at decision time |

An outcome-aware interview cannot repair a contemporaneous assertion. A later ontology assignment is a new assertion. An economic effect joins forward only after independent reconciliation. This is the separation required by [operator language](../lanes/02_operator_language.md#position-capture-acts-before-asking-what-kind-of-act-they-were) and [state-space authority strata](../field_models/STATE_SPACE.md#the-ten-strata).

### Observable, latent, and partially identified state

Let `Y_d` be the observed scene bundle, `P_d` the witnessed presentation/choice context, `H_d` the preceding history, and `z_d` Ember's perceived configuration. The program allows only:

```math
z_d \sim p(z \mid Y_{\le d}, P_d, H_d, portfolio_d, alternatives_d, coverage_d).
```

`z_d` is not assumed unique, stable, complete, or recoverable from ordinary history. The same gesture can arise from different configurations; the same configuration can yield different acts with a changed size, portfolio, urgency, choice set, or opportunity cost.

An operator model may emit an observed projection, a conditional association about an observable emission, a versioned set/distribution of latent alternatives, or an explicit inability to distinguish alternatives. It may not infer “the market was under pressure,” “the caller caused the move,” “Ember truly meant X,” or “this is the correct label” from a score. Attention, controller identity, social causation, and counterfactual management value are often bounded or unidentified; see [identifiability classes](../field_models/IDENTIFIABILITY_AND_UNITS.md#4-identifiability-classes).

## Moment-of-use capture

### Component evidence is scoped, optional, and separate

Each component claim is an optional assertion bound to an immutable scene and knowledge cut. It must name both what Ember says mattered and what is only reconstruction.

| Component | Required distinctions | Forbidden shortcut |
| --- | --- | --- |
| Timing / size | event and wall clock; side definition; exact atoms; sequence, burst/pause, splitting; occurrence and availability order | candle direction or rounded notional as flow |
| Liquidity / resilience | direction, exact size, route/venue, quote object, state/profile, refusal, recovery/replenishment | one depth/spread/liquidity scalar |
| Caller / actor | occurrence/content mark, attribution grade, valid/known-by time, overlaps, response-history scope | identity or causal impact as fact |
| Wallet / inventory | address-action relation; direct effects distinct from controller/cluster hypotheses; coverage and turnover rule | wallet count as people/common control |
| Social / attention | source revision/availability, identity uncertainty, rank/surface/viewport/interaction context | callout Boolean or gaze claim |
| Chart / memory | feed and price-object scope, samples/range annotations, visual history, earlier scene/episode links | chart pixels or candle as state |
| Compression / release | named form: opposing flow, absorption, replenishment, thin silence, concentration, capacity contraction, crowding, or other | scalar compression score |
| Fresh mint / lifecycle | mint age, curve/pool/migration regime, topology/profile, route availability, family uncertainty | smooth return across a break |
| PvP / churn | participant overlap/replacement rule, dyadic/graph layer, opposing-flow/turnover definition | volume or coin-level PvP score |
| Portfolio / disposition | exposure/accounting status where permitted, alternatives, urgency, horizon/review condition | meaning inferred from inventory delta |
| Coverage / presentation | source health/gaps, scene/view/presentation IDs, rendered/visible/interacted distinctions | missing equals zero; planned equals seen |

Every component projection identifies asset, unit, reference measure, topology/profile, event and knowledge clock, and authority rung. This is the field rule that a field is an indexed measure, not an atmosphere ([FIELDS_AND_OPERATORS](../field_models/FIELDS_AND_OPERATORS.md#1-a-field-is-an-indexed-measure-not-an-atmosphere)).

### Raw assertion first

The lowest-friction capture produces an immutable contemporaneous assertion containing:

```text
raw occurrence ID and exact bytes/digest
operator/subject/episode IDs where known
scene, view, presentation occurrence/gap, and choice-context references
asserted-at and referred-to time/interval, each with a typed clock
elicitation mode, prompt text/order, and machine-suggestion visibility
verbatim text or deliberate voice reference, or explicit empty response
optional source cues, confidence, urgency, horizon, and why-now
ambiguity and cannot-articulate status; privacy/corpus-use status
correction/supersession links
```

`verbatim`, `opaque token`, `ambiguous`, `cannot_articulate`, `no response`, and `not asked` are different states. An absent note does not mean absent intuition. Confidence is optional operator-reported judgment with its own scale/text—not a default number or a probability inferred from action. “Cannot articulate” is useful positive evidence of a language limit, not an imputed missing value.

A parse or model extraction is a separate derived assertion pointing to the raw bytes. It may offer zero, one, or many candidate component links, but retains parser/model version, ambiguity, and refusal. It cannot replace the phrase.

### Act, intention, effect, and outcome

Preserve this forward-only grammar:

```text
scene / presentation / choice context
  -> observable semantic act
  -> optional stated intention or disposition
  -> independently observed external attempt / reconciliation link
  -> qualified landed economic effect
  -> later outcome and retrospective account
```

An **act** is an evidence event: notice, inspect, compare, mark, nominate, request hot scope, take-some intent, keep-remainder declaration, flat-watch declaration, re-entry intent, zap/escape declaration, or close-episode declaration. An **intention** states desired action, exposure, horizon, avoidance, review condition, or disposition. An **economic effect** is a finality- and account-boundary-qualified reconciliation artifact. An **outcome** is later evidence under another horizon. Each can be absent, contradictory, and linked many-to-many. No later object is inferred from an earlier one.

A partial sale does not prove profit taking or thesis change. A full exit does not close an episode or prove loss of interest. Flat watch plus re-entry is not two independent selections. These are the episode/execution limits in [TRANSFER_LIMITS](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md#embers-episode-runner-and-re-entry-process).

## State-dependent, multi-valued disposition

`disposition` is a contemporaneous assertion about how Ember regards a subject/episode under a specific scene and portfolio state. It is neither a coin property nor an outcome class, and it is not required to be exclusive. Keep these dimensions independent:

```text
entry mode / crackle relation
current stance or disposition
thesis or causal story, if any
horizon or review condition
desired exposure / management intention
attention continuity and flat-watch state
confidence, urgency, ambiguity, unnamed residual
```

At one cut Ember can record multiple compatible or conflicting dispositions, such as “microdip is interesting” and “small catalyst runner only,” or none. Applicability is scoped by subject/episode, valid interval, scene/choice set, portfolio/exposure, presentation policy, and ontology release. A later change appends an assertion; it never mutates prior state. A model can use a time-indexed set, distribution, or transition hypothesis, but not a one-hot target until that restriction is earned.

Any disposition-emission study conditions on choice set, product presentation, portfolio/exposure, episode phase, lifecycle/topology, coverage, and available components. Otherwise it estimates an uncontrolled mixture of market, UI, Ember's memory, and opportunity cost. The UI is part of the composite process ([FIELDS_AND_OPERATORS](../field_models/FIELDS_AND_OPERATORS.md#9-reflexive-coupling)).

## Ontology: append-only proposals, assignments, splits, and merges

An ontology release is a graph, not a mutable label table. A term version has stable term/version IDs; display name; exact defining words; creation/knowledge cutoff; elicitation mode; status (`opaque`, `provisional`, `active`, `split`, `merged`, `retired`, `rejected`); intended dimension; positive/boundary/counterexample assertions; known observables and missing predicates; incompatible interpretations; and consuming model/playbook versions, if any.

Assignments are separate assertions: author, cut, ontology version, raw evidence, and confidence/ambiguity. Historical queries return assignments known then; harmonized queries return later interpretations with provenance. Neither changes raw acts or utterances.

Splits and merges are explicit many-to-many relation artifacts:

```text
term-version A --split_into(reason, cutoff)--> B, C
term-version D --merged_from(reason, cutoff)--> B, C
assignment X --reconsidered_by--> later assignment Y
```

The relation declares whether it is lexical, phenomenological, retrieval-oriented, or model harmonization. A shared string is not a timeless equivalence. Retired terms remain resolvable for old examples and reproducibility; raw assertions/scenes remain the escape hatch. See [Lane 02 ontology versioning](../lanes/02_operator_language.md#ontology-versioning).

## Recognition and replay are tests, not confirmation

### Two-pass replay

1. **Outcome-blinded reconstruction:** reconstruct witnessed scene/presentation through a selected act; hide later price, fills/accounting, social revisions, model output, and labels. Record open recall and recognition as `recognizes`, `does_not`, `uncertain`, or `cannot_reconstruct`.
2. **Outcome-aware reflection:** reveal later effects/outcomes behind a visible boundary; collect lessons, disagreement, renamed/split/merged terms, and alternative stories only as retrospective assertions.

The replay references exact scene/view/presentation digests, visible source closure, hidden/revealed role, pauses, prompts, model assistance, and availability cut. An inadequate presentation witness stays a typed gap, not proof of what Ember saw. The existing hidden-replay/reveal contract remains the lower boundary ([Wave 5 scientific memory](../../implementation/wave5/06_SCIENTIFIC_MEMORY.md#contract-ceiling)).

### Minimum recognition tests

- exact-scene re-recognition without outcomes;
- outcome-blinded pair/triplet contrast: same kind, important difference, neither, cannot tell;
- same-act/different-meaning and different-act/same-disposition cases;
- same-candle/different-component configuration, especially compression alternatives;
- random ordinary/unresolved cases alongside memorable winners and losses;
- test/retest with neutral wording or changed presentation order; and
- prospective use after review, tracking correction, abstention, burden, and button-induced drift.

Agreement is not truth. High recognition may reflect outcome memory, a familiar button, or replay cues; low recognition may reveal state dependence, poor reconstruction, or a nonverbal distinction.

## Model families and permitted claims

Every study declares estimand, observed universe, cuts, selection funnel, coverage, units/topology, baseline, and falsifier. Output is explicitly an observed projection, conditional association, partial bound, or latent hypothesis.

| Family | Allowed output | Must not claim |
| --- | --- | --- |
| component ledger | availability, disagreement, missingness | one market state/pressure score |
| earlier-only retrieval | ranked analogs, reasons, `none analogous` | same mechanism or outcome |
| observable-emission model | held-out conditional calibration of raw/structured emission | private state or true label |
| latent-alternative model | posterior/set of versioned, label-switching alternatives | unique hidden disposition/cause |
| transition model | prospective conditional assertion-transition risk | optimal management/value |
| outcome association | descriptive, selection-qualified association/bounds | alpha, caller impact, policy value |

Retrieval retains query cut, candidate universe, inclusion/exclusion, model version, hidden outcome, and counterexamples; see [Wave 5 analog memory](../../implementation/wave5/08_ANALOG_MEMORY.md).

## Future DTO and artifact boundaries

These are exact responsibility boundaries for future schema work, not permission to add a writer or alter existing Wave 5 contracts. All are strict append-only canonical-byte artifacts carrying a stable ID, schema version, producer/config, creation and knowledge cuts, input refs/digests, privacy/corpus-use status, and supersession/retraction relation where relevant. None contains wallet secrets, signer, transaction-construction, submission, slippage, fee-bid, cancellation, or execution authority.

| Future artifact / DTO | Owns | Must reference | Explicitly excludes |
| --- | --- | --- | --- |
| `operator_raw_assertion` | verbatim/voice ref, response state, optional confidence/urgency, prompt/suggestion exposure | scene, view, presentation/gap, act where applicable | normalized label replacing words; effect/outcome |
| `operator_component_assertion` | component claims, role/direction, ambiguity, operator words | raw assertion, component evidence, ontology version if used | score, causal/economic fact |
| `operator_disposition_assertion` | multi-valued stance/thesis/horizon/review/exposure | episode/subject, scene, raw assertion, prior state if revised | inferred fill; exclusive class requirement |
| `operator_ontology_term` | immutable term version/examples/counterexamples | raw assertions and ontology parents | in-place label edits |
| `operator_ontology_relation` | split/merge/rename/retire/reject/equivalence relation | source and target versions | one-to-one migration assumption |
| `operator_replay_protocol` | selected scenes, hidden/reveal cuts, questions, sampling, presentation policy | scene/presentation/replay refs | future data in blind phase |
| `operator_recognition_response` | contrast/recognition response, raw explanation, prompt/mode | replay pause, ontology version if assigned | proof of label truth |
| `operator_component_projection` | replayable observed/derived component values and coverage | exact source/scene, measure/unit/topology/clock | latent interpretation or UI-only calculation |
| `operator_latent_hypothesis_set` | alternatives/posterior/bounds and emission mapping | model/evaluation cuts, projections, ontology release | source truth, forced state, authority |
| `operator_model_evaluation` | frozen preamble, support, controls, calibration, falsifiers, residue | model/hypothesis, cohorts, baselines | recommendation/economic permission |

Existing `SceneRef`, presentation occurrence/gap, `OperatorAct`, episode/replay/closure, and store receipts remain owned by their current contracts. New artifacts only reference them. Future store admission refuses mismatched/unresolved scene, view, presentation, cut, ontology, or evidence digests instead of substituting current versions. Field projections carry the existing [field-artifact manifest](../field_models/IDENTIFIABILITY_AND_UNITS.md#9-field-artifact-manifest).

## Implementation and research DAG

```text
A. immutable scene/view + coverage + presentation/gap closure
   └─> B. append-only acts and raw assertions; no taxonomy required
       ├─> C. episode/flat-watch/re-entry and reconciled-effect linkage
       ├─> D. component evidence/projections with units, clocks, topology, coverage
       │   └─> E. earlier-only retrieval and outcome-hidden replay
       └─> F. ontology term/assignment/relation graph and contrast sampler
            └─> G. two-pass replay and recognition/ambiguity capture
                 └─> H. frozen prospective cohorts and choice/selection denominators
                      ├─> I. observable-emission and disagreement baselines
                      └─> J. latent-alternative/transition hypotheses with partial-ID reports
                           └─> K. evaluation, falsifiers, and useful-residue decision
```

Gates:

- `A -> B`: missing presentation yields a visible gap, never discarded/fabricated act.
- `B -> C`: intent, external report, landed effect, and outcome remain distinct occurrences.
- `B -> D`: raw assertion is immutable; components use only decision-cut evidence.
- `D/F -> E/G`: replay is outcome-hidden by construction; ontology assignment stays optional and versioned.
- `E/G -> H`: include abstentions, ordinary scenes, unresolved cases, and actual choice denominators.
- `H -> I/J`: chronological/regime-aware holdouts; presentation/sensing versions are interventions; simple baselines remain concurrent.
- `I/J -> K`: accuracy alone cannot advance a model; require calibration, controls, support, coverage limits, falsifier results, and a declared non-model residue.

No DAG edge leads to advisory, routing, signing, submission, or execution. Any such work is a new program with independent authority review.

## Falsifiers and stop conditions

| Claim | Falsifier or restriction |
| --- | --- |
| component is meaningful | no stable unit/domain/clock/coverage rule, or effect below source/quote error |
| compression is useful | same-candle contrast sets cannot distinguish alternatives; scalar adds nothing and changes meaning by regime |
| term is stable | blinded recognition no better than neutral controls, or survives only after outcome reveal |
| model reconstructs perception | predicts button/UI choice but fails phrase, contrast, abstention, or held-out scene behavior |
| caller/wallet/social adds information | gain vanishes with availability, coverage, lifecycle, platform-wide, cluster-uncertainty, or cold-scope controls |
| chart/memory adds information | matched components explain result, feed scope is incomplete, or rendering version reverses it |
| disposition transition matters | association disappears after episode, portfolio, alternatives, attention, and selection controls |
| outcome association is useful | fails calibration/support, is below execution/measurement uncertainty, or uses future joins/winners |
| latent state is responsible | posterior is sensitive to arbitrary label/order/prior/topology without equivalence reporting; probes do not separate alternatives |
| instrumentation helps | prompts slow urgent action, add clerical burden/overtrading, or destroy capture fidelity |

Synthetic known-truth tests include AMM mechanics, topology breaks, gaps, adaptive scope/ranking, ambiguous social/wallet identity, overlapping events, MEV/order ambiguity, operator labels, and outcome-aware relabeling. They should make pressure/causation models hallucinate. The gate tests observable recovery and honest uncertainty, not profitability.

## Smallest prospective study

Run an instrumentation-only episode diary over bounded ordinary use. Preserve notice, mark, compare, flat-watch, re-entry, and abstention—not only trades or winners. Use nonblocking raw assertions, optional opaque tokens, scene/presentation closure, and prompts permitting none, multiple, ambiguous, and cannot-articulate responses.

Then sample outcome-blinded contrasts spanning ordinary, adverse, favorable, unresolved, and same-action/different-meaning cases. Report capture completeness, replay fidelity, recognition/ambiguity, ontology drift, component availability, burden, and what remains unobserved. PnL, label count, or machine-cluster agreement are not success criteria.

If every model fails, retain the useful residue: an exact scene-bound diary of language, episode continuity, component evidence, and replayable counterexamples.

## Source boundaries

- [JOSHI_THOUGHT](../../../JOSHI_THOUGHT.md#embers-phenomenology-a-field-bundle-not-a-pressure-score) — phenomenology and anti-scalar constraints.
- [Wave 5 Glass sensorium](../../implementation/wave5/03_GLASS_SENSORIUM.md) and [scientific memory](../../implementation/wave5/06_SCIENTIFIC_MEMORY.md) — scene/act/replay ownership and no-authority boundary.
- [Operator language](../lanes/02_operator_language.md), [field operators](../field_models/FIELDS_AND_OPERATORS.md), [state space](../field_models/STATE_SPACE.md), and [identifiability](../field_models/IDENTIFIABILITY_AND_UNITS.md) — elicitation, measures, state, and falsification.
- [Microstructure transfer limits](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md) — venue limits on importing LOB concepts.
