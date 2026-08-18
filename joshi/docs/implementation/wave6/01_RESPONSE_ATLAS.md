# Wave 6 response atlas research prototype

## Outcome and boundary

This package is a bounded, offline contract probe for point-in-time signed-flow response surfaces.
It conditions descriptive response summaries on the exact base asset, venue, lifecycle version,
wallet/cluster/caller context version, mark direction, size bucket, horizon, and topology epoch.
It does not register a CLI, publish an online model, choose an action, or claim profitability.
Its positive ceiling is `intrinsic_contract / fixture_recovered`: all identities, clocks, version
spellings, coverage assertions, and commit sequences are caller-supplied fixture material, not
store-resolved evidence. It is not an `observed_atlas` or a release authority.

The estimand is an arithmetic mean of witnessed post-mark signed-flow component totals among anchors
whose complete component decomposition was available by the fit cutoff. It is an observed
conditional association. It is not reaction impact, a counterfactual execution effect, a bare
propagator kernel, or evidence of social causation. Correlated signed flow means a response curve
can include predecessors, descendants, selection, and changing liquidity; the formal
microstructure model therefore explicitly warns that response is generally not the underlying
impact kernel.

## Typed inputs

`RESPONSE_COMPONENT_OBSERVATION_SCHEMA` requires exactly three rows for each `(event_id,
horizon_us)` anchor:

- `same_wallet`
- `same_cluster_other_wallet`
- `external`

Each row carries exact atom units; event, response, availability, and information-cut clocks;
lifecycle, caller-context, and topology valid/available/retracted clocks; stable wallet, cluster,
caller-class, and version identities; a half-open size bucket; and coverage window/gap identity.
An observed component has a signed `int64` atom value and no gap ID. A gap has a null value and an
exact gap ID. Omitting a component is invalid: callers must distinguish a declared gap from an
incomplete export. Boolean, floating, nonfinite, mixed-unit, and schema-coerced numerics are not
accepted by the exact Arrow contract.

Every eligible response anchor enrolls one risk subject. `RISK_OUTCOME_SCHEMA` supplies an optional
terminal update for that subject with exactly one of:

- an exact `migration`, `liquidity_exhaustion`, or `venue_exit` competing event;
- healthy administrative right censoring at the registered horizon; or
- right censoring at a named source gap.

Right-censored rows cannot manufacture a no-event label. Source loss must cite its gap, while
administrative censoring must not. Outcome time and `outcome_known_at` are separate. A terminal
update not known by the fit cutoff is semantically unread future data: the enrolled subject remains
explicitly pending in the denominator and risk set.

## Point-in-time and identity rules

After enforcing the exact relation schemas, the builder selects the as-of relation before semantic
validation. A response anchor enters only when all three component rows were available by the fit
cutoff. An anchor with zero available rows is wholly future and absent at the cut. An anchor with
one or two available components is an incomplete current export and fails regardless of whether a
later row is also supplied; future presence cannot turn a current `CoverageError` into silent
exclusion. Only complete admitted rows are checked for units, duplicate identities,
lifecycle/caller/topology consistency, and temporal semantics. Only terminal outcomes known by the
cutoff are validated. Thus invalid units, topology, labels, duplicate identities, or incomplete
closure in wholly future-ineligible rows cannot poison an earlier build. Lifecycle, caller, and
topology versions on admitted rows must have been valid at the mark and available and unretracted
at its information cut. The information cut must precede the response horizon.

Occurrence IDs and semantic `(event, horizon, component)` and `(event, horizon, risk)` identities
must be unique. All components and horizons of one event must agree on asset, unit, venue,
lifecycle, caller context, size, and topology. This prevents silent cross-unit or cross-topology
aggregation. Eligible logical inputs are hashed in primary-key order. Response feature identity is
computed only from admitted response observations. Risk identity is a separate label release over
the enrolled response subjects plus terminal outcomes known at the cut. Changing outcome knowledge,
event kind, or censoring status therefore cannot change any response row, digest, or cell ID.
Surface and risk cell IDs are content-addressed from their respective digest, cutoff, dimensions,
and component/cause, so input row permutation does not change either IDs or output order.

Risk enrollment and terminal membership are a strict semijoin to response anchors admitted at the
same cutoff. A terminal row—even one claiming it was already known—has no risk membership while its
response anchor is future-only or absent. Supplying versus physically removing those future
response rows therefore yields identical risk cells and refusals. If the anchor enters at a later
cutoff, its terminal row becomes eligible and is then validated or explicitly refused; future
response-row presence cannot grant early label authority.

## Outputs

`build_response_atlas` returns a frozen `ResponseAtlas` containing three exact Arrow tables.

`response_surfaces` emits wallet-, cluster-, and caller-class-level cells. Each cell has separate
`same_wallet`, `same_cluster_other_wallet`, `external`, and `total` rows. Component estimates use
the same complete-anchor support, so the total equals the sum of the three component estimates.
Each row stores an arbitrary-width signed decimal `response_sum_atoms` string and a reduced exact
`response_mean_numerator_atoms / response_mean_denominator`; it does not narrow exact atoms to a
binary float. Python integer arithmetic computes component and total sums, including sums wider
than the input `int64` domain.
Partially observed anchors remain in coverage counts and gap identity, but no known component is
silently combined with zero for an unknown component. An all-gap cell has a null estimate and
`no_complete_anchor_support`.

`competing_risks` emits one row for every registered cause in each eligible context cell, including
zero-count and all-pending causes. It reports the full enrolled cohort, terminal-known and pending
counts, stable subject and pending-subject IDs, focal and other competing-event counts,
administrative and source-gap censoring separately, exact coverage IDs, and the raw observed cause
fraction over the full issued denominator. Pending is neither no-event nor censoring. The fraction
is not a censoring-adjusted cumulative incidence estimate, a calibrated probability, or a decision
score.

`risk_refusals` is normally empty. If a terminal relation known at the cut violates the risk schema,
identity, event/censoring, coverage, or temporal contract, the builder still returns the independently
valid response surface, emits no risk cells, and writes one deterministic typed refusal with a
stable reason code and, when the rejected relation has the exact Arrow schema, the count and logical
digest of only those terminal rows both known at the cutoff and semijoined to admitted anchors.
Unrelated future-only or not-yet-known terminal rows cannot alter that refusal. Invalid label bytes
therefore cannot veto response construction or be silently recast as pending. A refusal is not a
coverage gap, a censored subject, or a risk estimate.

Both outputs repeat the estimator/configuration identity, eligible input identity, fit cutoff,
maximum admitted availability, commit sequence, units, support, coverage, topology identity, and a
machine-readable claim boundary:

```text
descriptive_point_in_time_signed_flow_association_not_causal_or_strategy_claim
descriptive_observed_competing_risk_fraction_not_causal_probability_or_strategy_claim
```

## Prototype use and gates

The synthetic fixture has two venue/lifecycle/topology contexts, two horizons, wallet-to-cluster-to-
caller nesting, known component totals, an explicit response gap, three competing causes, healthy
administrative censoring, and source-gap censoring.

```python
from joshi_analysis.wave6_response_atlas import (
    build_response_atlas,
    synthetic_response_atlas_inputs,
)

observations, risks, fit_cutoff = synthetic_response_atlas_inputs()
atlas = build_response_atlas(observations, risks, fit_cutoff)
```

Focused gates:

```bash
uv --directory analysis run --locked pytest tests/wave6_response_atlas
uv --directory analysis run --locked ruff check \
  src/joshi_analysis/wave6_response_atlas tests/wave6_response_atlas
```

The adversarial suite covers malformed future response and terminal bytes, future-only anchor
presence versus physical removal with the same already-known terminal row, later-cutoff admission,
paired incomplete-current anchors with and without a later row, isolated refusal of invalid known
risk labels, response/label identity separation, full all-pending denominators, exact means above
`2**53`, current context leakage, incomplete admitted component closure, gaps versus zero,
competing risks versus censoring, mixed units and topology, nonfinite and boolean numeric columns,
duplicate admitted identities, exact component additivity, and deterministic IDs under input
permutation.

## Deferred work

This prototype does not estimate uncertainty, causal effects, a Hawkes model, a propagator,
censoring-adjusted incidence, optimal execution, or a strategy. It does not solve identity
uncertainty, partial wallet attribution, parent/metaorder inference, inexact timestamps, input atom
domains beyond signed `int64`, cross-venue routing, store resolution, or real-source admission. Exact
wide sums are serialized decimal integers, not proof that a source supplied a wider admitted atom
domain. These limitations require new typed contracts and prospective evaluation rather than
broadening this V2 fixture surface silently.
