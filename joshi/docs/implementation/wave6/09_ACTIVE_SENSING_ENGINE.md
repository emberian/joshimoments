# Wave 6 active-sensing semantic engine

Status: implemented semantic prototype. This component validates registrations and produces
deterministic records. It does not acquire data, change collector state, stage or render a user
interface, reserve assets, construct transactions, sign, submit, or infer that an intended action
was applied.

The implementation follows
[`04_ACTIVE_SENSING_PRESENTATION.md`](../../research/wave6/04_ACTIVE_SENSING_PRESENTATION.md).
It lives entirely in `analysis/src/joshi_analysis/wave6_active_sensing` with adversarial tests in
`analysis/tests/wave6_active_sensing`.

## Boundary

Every admission function returns `UnverifiedSemantic`. The wrapper says that canonical semantics
were checked; it explicitly does not claim source I/O, collector application, provider
acknowledgement, coverage, render, visibility, focus, comprehension, causality, or an economic
effect. There is no callback, connector, HTTP client, collector handle, renderer handle, wallet,
transaction builder, signer, or submit route in the package.

This remains an intrinsic semantic contract over caller-fed values, not a store-resolved claim.
IDs, digests, clocks, evidence references, receipts, coverage states, human acceptance, and
resolution booleans remain unverified until a separate sole-store adapter resolves them. The
engine proves relationships among all values supplied to one admission call and deliberately says
nothing stronger.

The engine exposes these pure operations:

- `admit_baseline` seals a model-blind ordinary-use registration.
- `admit_baseline_closure` binds the fixed denominator and refuses an outcome-responsive stop or
  extension.
- `admit_experiment` proves that a complete baseline closed before a separately registered epoch.
- `admit_sensing_decision` validates an immutable pre-I/O `joshi.sensing_decision/v1` occurrence.
- `admit_presentation_intervention` validates a pre-reveal
  `joshi.presentation_intervention/v1` prescription.
- `admit_coverage_report` closes every originally assigned unit without substitution or
  post-exposure conditioning.

`deterministic_artifacts()` builds and admits a fixed synthetic chain containing a baseline,
baseline closure, sensing epoch, sensing decision, coverage/support report, presentation epoch,
and presentation intervention. Repeated construction produces identical canonical dictionaries
and SHA-256 semantic digests.

## Epoch isolation and model blindness

`BaselineEpochRegistrationV1` freezes the acquisition, source-registry, run, surface, cockpit,
presentation, safety, consent, retention, floor, and budget digests before its start. Its literal
values are:

```text
model_influence = prohibited
authority = read_record_replay_only
effect_ceiling = observe_only
```

Journal input origins containing model, forecast, embedding, score, uncertainty, VOI, or analog
lineage refuse. The journal stays sealed through the outcome-knowledge deadline. A complete closure
cannot precede the fixed half-open end and a closure cannot select a new denominator or react to an
outcome.

`ExperimentEpochRegistrationV1` must name the exact sealed baseline and its closure time. Its
registration time is after closure and before its own start. A sensing-only epoch refuses
presentation records; a presentation-only epoch refuses sensing records; `joint` is the only shape
that admits both. The registration now carries the complete `CensusDenominator`, sorted eligible
assignment-unit and public-subject identities, registered study cells, and an exact arm-to-policy
digest map in addition to probabilities. Floor members must be a subset of this registered subject
universe. Material changes therefore require a successor registration rather than mutation of a
live artifact.

## Exact artifacts

`SensingDecisionV1` contains all registered identity, predecessor, epoch, cutoff, unit,
denominator, eligibility, reason, assignment, request, floor, budget, cost-basis, comparator, and
authority families. Admission requires:

- exact rational assignment probability and committed draw artifacts for randomized assignments;
- complete as-known evidence bounded by both availability time and store commit sequence;
- complete cold, random, manual, and portfolio status vectors for every registered
  source-operation;
- exact equality with the registered denominator plus membership of the assignment unit, public
  subject, and study cell in the registered sets;
- equality of the assigned arm digest, decision policy digest, and registered arm-policy digest;
- source-registry, run-budget, denominator, coverage, and policy occurrence resolution before I/O;
- worst-case cost plus in-flight overshoot reserved inside the relevant floor or candidate ceiling;
- request start after decision production and request expiry no later than the fixed TTL; and
- literal `read_only_no_execution` authority.

Reasons are typed and sorted. Manual reasons bind an operator command, exact scene/view, and durable
acceptance receipt. A reason may retain both operator acceptance and a model proposal ID, proposal
content digest, and lineage evidence; operator acceptance does not erase the model origin. Such
joint lineage refuses a manual-floor assignment. Model lineage cannot be renamed as manual or
deterministic and is admissible for allocation only as `candidate_voi` in a separately gated VOI
epoch.

`PresentationInterventionV1` contains the registered identity, epoch, unit, as-of vector, evidence,
assignment, policy, safety, accessibility, burden, and authority families. The record is a staged
prescription: `receipt_not_yet_claimed` and `reveal_not_started` must both remain true. Planned and
omitted sets exactly close the eligible evidence set. Semantic order is an exact permutation of
the planned set. The arm may vary registered placement, ordering, grouping, salience, and
progressive disclosure, but it must preserve the same eligible evidence, safety digest,
accessibility capability, sensing regime, and read-only interaction boundary.

Safety fields for authority, freshness, gaps, refusals, and inventory/exposure must remain
persistent and prohibited from omission. Evidence-only controls reject wallet, transaction,
signing, submission, trade, swap, and route commands. A failed presentation therefore has only the
registered fixed-safety-baseline fallback; the semantic artifact itself never mounts that fallback.

## Floors and budget ledger

`FloorPlan` independently represents cold, random, explicit-manual, and portfolio allocations.
Each source-operation subject has one primary floor. Every floor carries sorted per-source-operation
budget vectors that must reconcile its aggregate, and the random minimum is recomputed separately
for each registered source-operation capacity. A floor decision derives class, family, and stratum
from the exact registered `FloorMember`; an operator reason or caller assignment enum cannot make a
nonmember consume the reserve. Candidate assignments refuse a subject that is already a protected
primary member for the requested source-operation. The plan refuses:

- a nonempty support stratum with neither a cold member nor an explicit infeasible state;
- less than the initial 20% random absolute slot allocation;
- less than 20% of any applicable non-census read or attention dimension;
- an eligible mint or wallet family missing from the manual floor;
- an in-scope portfolio subject missing from the portfolio floor; or
- duplicate primary attribution that could double-count overlap.

`BudgetEnvelope` recomputes, in every dimension:

```text
census + recovery + cold + random + manual + portfolio + candidate <= RunBudget
```

Dimensions include requests, pages, ingress bytes, durable bytes, provider credits, events, wall
time, attention assignments, prompts, closeout time, notifications, and operator-session time. No
dimension borrows from another. Currency and chain-native caps must remain empty in this read-only
prototype. A decision separately reserves expected cost, worst case, and maximum in-flight
overshoot. Unused floor capacity is not added to the candidate ceiling.

## Coverage, nonresponse, accessibility, and burden

`CoverageSupportReportV1` retains the full census count, denominator digest and occurrence IDs,
every assigned occurrence, exact planned/actual/provider-observed budget vectors, known-probability
state, effective-sample-size rational, worst-supported strata, and version drift. Every assigned
unit has exactly one typed `NonresponseState` and one outcome closure state. Unsupported,
conflicting, source-loss, interval-censored, withdrawn, and open cases can remain unanalyzed, but
they remain in the assigned report. Passing a report with an omitted, replaced, or invented
assignment refuses. Admission re-runs each supplied sensing or presentation assignment against the
report's exact experiment registration, so a self-valid artifact from another epoch refuses. Each
outcome binds the sealed assignment artifact ID/digest, arm, policy, study cell, assignment class,
denominator, assignment-unit key, and public subject. Reclassification of any of those fields
refuses. Census occurrence IDs use ordered exact equality with the registered denominator; neither
missing nor invented IDs are accepted.

Accessibility requires actual critical-task evidence for keyboard operation, focus stability,
screen-reader use, reduced motion, semantic text/table alternatives, non-color encoding, 200%
zoom/reflow, at least 44 CSS-pixel targets, restrained live regions, and nonprecision input. The
initial burden contract permits no more than two assignments per session, a 90-second optional
closeout per assignment, 15 study minutes in seven days, and zero unsolicited research
notifications. Skip, withdrawal, and fixed baseline fallback paths are mandatory.

## VOI and gaming defenses

`VoiGateEvidence` admits forecast-informed sensing only when the exact claim family and cells have:

- more than the initial twenty mechanism-validation occurrences;
- repeated nonadjacent, chronological, matured, outcome-embargoed prospective support;
- supported calibration and proper-score increment over a simple baseline;
- passing negative controls and uncertainty beyond measurement error;
- completed non-VOI cost/coverage epochs with pre-registration fit and cost cutoffs;
- preserved census, floors, and assignment probabilities; and
- a reviewed action set containing abstention/refusals, common downstream policy, declared utility,
  estimator, and support boundary.

Before that conjunction, model-origin reasons refuse. After it, the result is still only
`UnverifiedSemantic` and grants read/attention allocation semantics, never portfolio or execution
authority.

Primary outcome names containing click, dwell, open, activity, trade count, operator acceptance,
or PnL refuse. Presentation salience likewise cannot depend on outcomes, activity, clicks, dwell,
trades, or PnL. Fixed stopping, complete denominators, typed nonresponse, cold/random controls, and
digest-bound assignments prevent favorable feedback from rewriting the experiment.

## Verification

Focused verification is:

```bash
cd analysis
uv run pytest -q tests/wave6_active_sensing
uv run ruff check src/joshi_analysis/wave6_active_sensing tests/wave6_active_sensing
```

The adversarial suite covers deterministic replay, baseline contamination, experiment
interleaving, model-induced selection and manual laundering, starvation of every protected floor,
future support/cost input, pre-gate VOI, presentation safety/intervention leakage, execution-control
leakage, exact floor membership, joint operator/model lineage, cross-experiment assignments,
assignment/outcome reclassification, missing or invented denominator occurrences and subjects,
nonresponse retention, multidimensional budget overflow, source-specific floor accounting,
cross-dimension borrowing, feedback gaming, accessibility failure, burden overflow, and sealed
baseline digest substitution.
