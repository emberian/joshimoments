# Wave 6 — prospective epistemic campaigns

Status: research protocol and promotion gates. This document creates no collector, model,
presentation, action, wallet, execution, or economic authority. In particular, it does not claim
that any M0–M7 study has been run. The current traceability audit says none is “implemented and
walking”; a fixture, exact calculator, or contract is not a prospective result
([traceability](../routed_liquidity/07_BOOK_TO_JOSHI_TRACEABILITY.md#6-study-m0m7-traceability)).

The purpose of a campaign is to turn a small number of desk-native, decision-relevant questions
into bounded prospective observations. It is not to create a prediction market, a trading desk,
a firm, a capital pool, a score-priced reputation system, or a controller. A submitted forecast is
only a sealed read-only research artifact; an adjudicated score is only a property of that
artifact against its registered target.

## 1. Non-negotiable boundary

Each campaign inherits the B0–B4 spine and its current durable ceiling from
[Wave 5 epistemic admission](../../implementation/wave5/14_EPISTEMIC_ADMISSION.md) and
[the epistemic-book contract](../../implementation/wave5/07_EPISTEMIC_BOOK.md). Until the private
store adapter supplies the cited receipts, all artifacts are
`contract_draft_fixture_validated` or `unverified_semantic`, never prospective support.

The following separation is absolute:

```text
operating plane: acquisition -> census -> scene -> retrieval -> presentation -> operator action
                                                      X
research plane:  registration -> frozen occurrence -> sealed forecasts -> reveal
                              -> adjudication -> score -> earlier-only support
```

There is no arrow from the research plane to initial acquisition, source priority, census scope,
hot lease, refresh cadence, retrieval, ranking, prompt, notification, Glass layout, action
affordance, wallet, transaction, signer, or submission. A campaign cannot ask the operator to
inspect an asset, make an asset more prominent, or suppress an ordinary product surface. It also
cannot change the observed action set or reserve capital. The existing `read_only_no_execution`
authority is the maximum authority for every campaign artifact.

This matters especially for the operator campaigns: an operator act is retained immediately, a
missing presentation is a typed gap, and a later presentation may repair neither the original act
nor its available information ([scientific memory](../../implementation/wave5/06_SCIENTIFIC_MEMORY.md)).
Likewise, an analog retrieved for a decision may use only earlier decision cutoffs and
outcome-free features; a later outcome, ontology correction, or identity revision cannot influence
candidate selection or tie-breaking ([analog memory](../../implementation/wave5/08_ANALOG_MEMORY.md)).

## 2. A campaign occurrence: frozen before its target

A campaign is one versioned `ClaimDefinition` applied to a sequence of `ClaimOccurrence`s. The
definition fixes the target algebra, units, price/route functional, horizon, censoring policy,
score, comparison baseline, study cells, and promotion thresholds. A changed target, threshold,
route profile, source version, score, or producer is a new definition/version, not a rewrite.

For occurrence `o`, the private admission adapter must atomically bind all of the following before
the target window opens:

| frozen object | minimum content |
| --- | --- |
| subject and universe | canonical subject ID plus the complete eligible roster/census rule, inclusion/exclusion reasons, random cold-stratum rule where applicable, and frozen universe digest. An observed hot list alone is never the universe. |
| scene and conditioning | exact committed scene digest, lifecycle/regime, direction, standardized size, route/quote profile, state/topology/source versions, and all declared filters. |
| evidence closure | sorted raw and derived input manifest; `available_at`, `valid_at`, authority/domain/carrier/unit, coverage intervals and typed gaps for every input; maximum input availability and manifest digest. |
| mechanics closure | only the named M0 price/quote, state, position, route, fill, or terminal-manifest capability actually consumed. Unsupported capability means `unsupported`, not a proxy mark. |
| clocks | `max_input_availability <= information_cutoff <= occurrence_commit_at <= issue_deadline < target_origin < horizon_at < knowledge_deadline`; event and information clocks remain separately recorded. |
| outcome protocol | outcome evidence sources, observation cadence, tie/event-order rule, gap/interval policy, correction lineage, and the exact disposition allowed at adjudication. |

The submission input cutoff equals the occurrence information cutoff and its input digest equals
the frozen occurrence manifest. A provider response, price, quote, correction, interview, or
outcome that becomes available later may only create a later registered revision/landmark
occurrence; it cannot fill the old preimage. This is the B0 rule, not an aspiration.

An occurrence is refused before issuance when its scene/universe/evidence/capability closure is
missing, incoherent, or late. Absence is not repaired with an inferred value, a current route, a
current identity, or a post-hoc “similar” candidate.

## 3. Initial claim family

The family is deliberately small. All claims are H3 prospective forecast-quality questions about
an H2/H1-defined target; none establishes causal impact, profitability, private information,
operator skill, or an H5 policy. M0–M7 below use the Book-study namespace from
[the microstructure beacon](../../microstructure/trades_quotes_prices/JOSHI_BEACON.md#research-program),
not the separately named routed-liquidity causal namespace.

| campaign | exact claim target | primary score / relation to M0–M7 | initial eligibility |
| --- | --- | --- | --- |
| **C1 directional response** | Given frozen pre-event state `x_o`, signed event class `e_o`, price functional `P` (mark, marginal, or exact direction × size executable quote, named rather than interchangeable), lag `h`, and deadband `d`, forecast `Y in {down, neutral, up}` from the signed change `P(t_o+h)-P(t_o)` after the registered deterministic-curve component is separately retained. A route/lifecycle boundary before `h` is its own registered competing category, never a zero return. | Multiclass Brier and log score versus a lifecycle/cell base rate; score increment only against the same occurrence baseline. This is the prospective counterpart of descriptive M2, not caused impact. | Requires M0 coherent state/price closure and an admitted `MarketEvent` + `StateAtEvent`; otherwise shadow only. |
| **C2 hazard / time-to-event** | Given `x_o` and horizon bins `0 < h_1 < ... < h_k`, forecast the first category and bin among `{up threshold, down/drawdown threshold, route/capacity loss, lifecycle boundary, healthy survival through H}`. Thresholds use the same frozen exact-size `P`, direction, size, route set, fees/freshness and interval/tie rule. | Categorical Brier/log score on the joint first-event × time-bin outcome; report cause-specific calibration and all censoring. Addresses M1/M2/M3 as forecast questions, never a fitted causal kernel claim. | Requires C1 closure plus complete event cadence/coverage sufficient to distinguish threshold crossing from interval censoring. |
| **C3 liquidity / route activation** | For frozen asset, direction, exact size `q`, declared route set `R`, quote/refusal profile `Q`, and predicate `A`, forecast whether at least one *eligible external* route becomes or remains `active` at each named checkpoint: a current valid quote/refusal proves the stated capacity, slippage, freshness and route-health predicate. A route answer is not a fill. | Binary Brier/log at each checkpoint plus survival-style score for first loss/activation; complete denominator includes no-quote, refusal, source loss and route gaps. Relates to M0 geometry and may later describe M1 observed routing, but does not infer route diversion. | May be the first live family once named quote capability exists; landed-flow or fill claims stay disabled. |
| **C4 provider adverse-selection state** | For one prospectively registered LP position/version and exact remaining inventory, forecast the first state before `H`: `{registered adverse-selection/inventory-conversion threshold, adverse route/liquidation state, benign covered survival}`. The threshold is a named observed/replay diagnostic and terminal liquidation manifest, not “LP profit”; fees, rewards, principal, self-flow and external flow remain separate. | Multiclass Brier/log conditional on admissible full-path closure; report a score only for the registered state target. It is not evidence that the LP caused or avoided price movement, and a counterfactual policy value stays a separately labeled frozen replay. | Shadow only until per-bin inventory, external/self-flow, claims/edits/costs, withdrawal basket, whole-position liquidation and terminal evidence close (M5 prerequisites). |
| **C5 recognition and disposition** | Given a frozen committed scene and predeclared observational vocabulary, forecast (a) whether an independently retained `notice`, `inspect`, `mark`, or `watch_flat` act occurs within `H_r`; or, for an already instrumented choice protocol, (b) the first declared disposition in its complete, frozen choice set: `{remain_flat, take_some, keep_remainder, close, reentry, cannot_articulate_yet, no recorded disposition}`. It predicts an observed declaration/recognition occurrence, not a fill, PnL, correctness, or a latent mental state. | Binary/multiclass Brier/log with `missing_presentation`, no-act telemetry gap, and incomplete-choice-set handled as registered non-scoreable/censored dispositions. Relevant to M6/M7 episode research, but no prediction may solicit, prime, rank, or time the act. | Only shadow until the scene/presentation receipt and the independent choice protocol close; ordinary `no_trade` is not inferred as abstention. |

No campaign is a generic “price will rise” claim. `P`, `q`, direction, route set, state, horizon,
event order, and observation/censoring rule are part of the claim identity. A mark may be a useful
typed target in C1, but it cannot be silently substituted for an executable quote, fill, or
liquidation value. This follows the M0 price-stack requirement and the microstructure transfer
limits ([M0](../../microstructure/trades_quotes_prices/JOSHI_BEACON.md#study-m0--exact-venue-price-geometry),
[transfer limits](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md)).

## 4. Submission, blindness, and reveal

Each occurrence names its eligible first-round forecasters at registration: the fixed cell base
rate, at most the registered mechanics/analog baselines, named model/producer versions, and an
optional voluntarily offered operator forecast. Eligibility never depends on a forecast value,
availability after issue, or a favorable prior result. Missing, abstain, unsupported and refused
are explicit submissions/dispositions; they are not probability zero and cannot be quietly
replaced by a model.

First rounds are mutually blind. The sealed namespace records the sorted eligible set, the exact
minimum component count, and `reveal_not_before`. Before first reveal every submission must prove:

```text
max input availability <= submission cutoff == occurrence cutoff <= occurrence commit
  <= submission production <= submission receipt <= issue deadline < target origin
```

The store must read an empty precommit visibility set for every first-round submission and prove
that no reveal exists. It seals exactly one canonical payload per eligible forecaster. Only when
*every* eligible forecaster has sealed an exact first round may the store write the unique reveal;
a required-count subset cannot force reveal. A revision is a new prospectively registered landmark
occurrence and names every visible parent forecast and ensemble. It never masquerades as a blind
first round.

Reveal has two scopes:

1. The durable research partition may reveal the sealed first rounds after closure of the namespace
   to construct the registered shadow comparison. It remains inaccessible to all operating-plane
   services and cannot enter prompts, rankers, notifications, or Glass.
2. Operator-facing retrospective scorecards may show a forecast only after admissible adjudication
   and after the initial target window. They show the target, coverage, censoring and support
   alongside it. They do not show a live recommendation or counterfactual action.

This preserves experimental blindness even if research staff can inspect a sealed journal: the
capability boundary, not an instruction to behave, prevents initial forecasts from changing
acquisition, presentation, or action.

## 5. Adjudication, censorship, and scoring

Outcome observation, forecast adjudication, and wallet/financial settlement are separate
artifacts. No score posts a wallet effect, and no landed effect proves a forecasted policy caused
an outcome. The adjudicator uses only registered evidence available by `knowledge_deadline`,
preserves coverage and correction lineage, and append-writes rather than updates the result.

| adjudication state | treatment |
| --- | --- |
| `resolved_observed` / `healthy_no_event_through_horizon` | Score when the full registered outcome and coverage rule is satisfied. Healthy survival requires nonempty complete horizon evidence. |
| `resolved_frozen_replay` | May score only a definition that explicitly permits replay and carries the complete terminal/replay/whole-position prerequisites. It stays an assumption-bound replay result, not settlement. |
| `administrative_censored`, `source_loss_censored`, `interval_censored`, `left_truncated`, `competing_event`, `route_or_liquidation_refusal`, `intervention_invalidated`, `conflicting`, `unsupported`, `open` | Retain in the occurrence denominator with typed scope/reason; do not score as a loss, success, zero, neutral return, or no-event. A definition may register a compatible interval/survival score later, but cannot improvise one after viewing outcomes. |

For the initial categorical family, score a forecast probability vector `p` with exact registered
category ordering using Brier loss `sum_i (p_i - 1{Y=i})^2` and, where every submitted probability
is strictly positive under the declared convention, log loss. Report the base-rate increment only
for the same scored occurrences. Report each of: complete issued denominator, sealed-submission
coverage, adjudicable coverage, scoreable coverage, abstention/refusal/unsupported count,
censoring by reason, calibration, and results by frozen cell. A lower average loss is a conditional
H3 result, not intrinsic information, profit, or causal usefulness.

Time-to-event claims use their prospectively defined joint cause × time-bin categorical outcome
initially. A later integrated Brier/time-dependent log-score version needs a distinct definition
with its own censoring/weighting assumptions. This is deliberately conservative about the
distinction between forecast quality and actionability made in
[Information, capital, and time](../field_models/INFORMATION_CAPITAL_TIME.md#41-forecast-score-increment)
and [the Forecast mechanism note](../field_models/FORECAST_MECHANISM_NOTE.md#33-actionability).

## 6. Dependence-safe support and ensembles

An ensemble is an H3 research comparator, not a forecaster with independent evidence and not an
action signal. It is constructed only in shadow mode from same-definition, same-occurrence,
same-conditioning first rounds after the permitted reveal. Its components are visible in full.

Initial ensemble discipline:

- use the deterministic equal-weight combination specified in the epistemic-book contract; every
  component has a unique primary lineage and duplicate producer/model/parent lineage is refused;
- do not add two prompts, checkpoints, analog views, or base-rate projections that share a primary
  lineage merely to manufacture apparent ensemble breadth;
- retain component scores and the base rate beside ensemble scores; do not select components or
  weights on the current target or a current outcome;
- estimate any learned weights only from uniquely identified, fully matured, embargoed occurrences
  strictly earlier than the current occurrence cutoff, with the complete denominator and no
  overlap/reuse; apply the frozen weights to a later untouched chronological block;
- do not pool near-simultaneous events, correlated assets, one parent flow, one operator episode,
  or overlapping horizons as independent observations. These are one dependence cluster for
  summaries or are separated/embargoed prospectively; and
- require the book's repeated-support floor before a support label: at least 40 unique scored
  occurrences, exactly partitioned into at least two chronological nonadjacent windows with at
  least 20 per window, with every outcome availability and embargo strictly earlier than a
  consuming occurrence cutoff.

The floor is a gate against obvious self-confirmation, not proof of generalization. Any report
must name the frozen definition/cell, windows, clusters, coverage, and the fact that the ensemble
was shadow-only. An ensemble cannot become a source for candidate acquisition or operator
presentation even after it crosses the floor.

## 7. Live and shadow campaign protocol

`Shadow` means actual prospective data and sealed forecasts may be collected, but no campaign
output is available to operating surfaces or action. `Live` means the occurrence is created from
live admitted evidence under the same restriction; it does **not** mean trading, recommendations,
or economic deployment.

| phase | protocol | gate to advance |
| --- | --- | --- |
| **P0 fixture / unverified** | Validate canonical definition bytes and adversarial cases: late evidence, altered same-ID bytes, peer-visible first round, incomplete reveal, future support, route/price substitution, and censor-to-zero laundering. | Strict semantic refusal works, but no receipt exists. Status remains `contract_draft_fixture_validated`; no empirical language. |
| **P1 shadow walk** | Run a selected C1/C3 occurrence through the private adapter using admitted real-time evidence, frozen universe and B0 clocks. Keep output confined to the research partition; exercise restart/idempotence and all typed adjudication states. | Durable occurrence/seal/reveal/adjudication receipts, coherent coverage/capability closure, and a complete issued-denominator audit. A single mature outcome validates workflow only. |
| **P2 live prospective journal** | Admit live C1/C3 occurrences and voluntary C5 only from ordinary independently operating product flow. Seal all listed first rounds before target origin; collect outcomes and score only admissible closures. C2 may enter after observation cadence is proven. | No forecast-to-operating-plane data path; independent audit confirms frozen universes, empty first-round visibility, all-eligible reveal, late-input refusal, and transparent censored denominator. |
| **P3 scored shadow comparison** | Publish internal retrospective scorecards and fixed-component shadow ensembles, with components/base rate/coverage/censoring. C4 remains shadow until its full LP path closes. | Each score has exact occurrence/submission/adjudication receipts; score reproducibility and correction lineage pass; no scorecard feeds product ranking or action. |
| **P4 prospectively supported, narrow** | Permit the phrase “prospectively supported in the registered cell” only for a fixed definition/producer/cell after the repeated, embargoed, earlier-only support floor in section 6 and a later untouched confirmation window both meet the predeclared reporting rule. | It remains H3, cell-bounded and shadow-only. Failure, censoring, drift, and negative-control results remain visible; no controller/policy promotion follows. |

P4 is intentionally not a global “validated model” badge. C1/C3 are the likely first protocols
because their mechanics can be bounded by named quote capability. C2 requires honest cadence;
C4 needs a complete LP path; and C5 requires a real presentation and complete choice closure.
Campaign registration must be stopped or versioned—not broadened after outcomes—when coverage
fails, a source changes semantics, an eligible universe cannot be frozen, a target becomes
action-contaminated, or a required capability is lost.

## 8. The internal information-use / capital-time book

The book is an internal, append-only research ledger of **claims on measurement attention**, not
financial positions. One row corresponds to a definition/occurrence/submission/adjudication chain
and carries:

```text
claim identity and frozen cell
evidence/coverage/clock/capability closures
sealed forecast and later adjudication/score/support state
resource vector: source and operator time, qualified-focus time, data cost, latency,
                 asset-specific observed capital-time/inventory-time where actually relevant,
                 fees, unresolved exposure and coverage burden
```

It reports the pair `(information vector, resource/consequence vector)` by registered cell: proper
score increment, calibration, persistence and coverage beside attention, latency, data cost, and
separately typed capital-/inventory-time. It preserves carrier, owner, custody state and clock;
it never adds asset-hours across assets or divides score by a mechanically favorable collateral
denominator. Ratios, if later registered, are views over sums with named numerator, denominator,
zero case and scalarization—not a universal `information efficiency` price
([information-use frontier](../field_models/INFORMATION_CAPITAL_TIME.md#2-primary-object-an-information-use-frontier)).

There are no deposits, shares, odds, payouts, orders, matching, capital allocation, customer
balances, collateral, yield, profit split, or performance compensation in this book. “Open” means
an unresolved research target; “settled” means adjudicated for scoring; “position” means a
versioned epistemic commitment. It can therefore help decide which *measurement protocol* is worth
continuing under explicitly reported attention, data, coverage and risk burden without pretending
to be a market or a firm.

## 9. Required audit record

Every campaign report must link the definition digest/version, occurrence IDs, universe/evidence/
capability closure digests, B0 and reveal receipts, complete denominator, adjudication lineage,
score build, support windows/embargoes, dependence clusters, component lineage, and operating-plane
non-interference attestation. It must visibly state the strongest honest status: fixture,
shadow-walking, prospective-scored, or narrowly prospective-supported. It must also link the
negative, censored, refused, unsupported and unresolved cases.

Anything less is useful exploratory work at most. It is not a prospective claim, an information
mechanism result, or authorization to acquire differently, present differently, or act.
