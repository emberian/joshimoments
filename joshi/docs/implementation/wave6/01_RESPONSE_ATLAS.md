# Wave 6 response atlas research prototype

## Outcome and boundary

This package is a bounded, offline contract probe for point-in-time signed-flow response surfaces.
It conditions descriptive response summaries on the exact base asset, venue, lifecycle version,
wallet/cluster/caller context version, mark direction, size bucket, horizon, and topology epoch.
It does not register a CLI, publish an online model, choose an action, or claim profitability.

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

`RISK_OUTCOME_SCHEMA` closes every anchor with exactly one of:

- an exact `migration`, `liquidity_exhaustion`, or `venue_exit` competing event;
- healthy administrative right censoring at the registered horizon; or
- right censoring at a named source gap.

Right-censored rows cannot manufacture a no-event label. Source loss must cite its gap, while
administrative censoring must not. Outcome time and `outcome_known_at` are separate, and only
outcomes known by the fit cutoff enter a risk summary.

## Point-in-time and identity rules

The builder validates all supplied records, then admits a response anchor only when every component
was available by the fit cutoff. Lifecycle, caller, and topology versions must have been valid at
the mark and available and unretracted at its information cut. The information cut must precede
the response horizon. A future response or outcome cannot affect the eligible input digest, cell
identity, support, or estimate.

Occurrence IDs and semantic `(event, horizon, component)` and `(event, horizon, risk)` identities
must be unique. All components and horizons of one event must agree on asset, unit, venue,
lifecycle, caller context, size, and topology. This prevents silent cross-unit or cross-topology
aggregation. Eligible logical inputs are hashed in primary-key order. Surface and risk cell IDs are
content-addressed from the eligible digest, cutoff, dimensions, and component/cause, so input row
permutation does not change either IDs or output order.

## Outputs

`build_response_atlas` returns a frozen `ResponseAtlas` containing two exact Arrow tables.

`response_surfaces` emits wallet-, cluster-, and caller-class-level cells. Each cell has separate
`same_wallet`, `same_cluster_other_wallet`, `external`, and `total` rows. Component estimates use
the same complete-anchor support, so the total equals the sum of the three component estimates.
Partially observed anchors remain in coverage counts and gap identity, but no known component is
silently combined with zero for an unknown component. An all-gap cell has a null estimate and
`no_complete_anchor_support`.

`competing_risks` emits one row for every registered cause in each eligible context cell, including
zero-count causes. It reports the at-risk cohort, focal and other competing-event counts,
administrative and source-gap censoring separately, exact coverage IDs, and the raw observed cause
fraction. The fraction is not a censoring-adjusted cumulative incidence estimate, a calibrated
probability, or a decision score.

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

The adversarial suite covers future response/outcome/context leakage, incomplete component and risk
closure, gaps versus zero, competing risks versus censoring, mixed units and topology, nonfinite and
boolean numeric columns, duplicate occurrence and semantic identities, component additivity, and
deterministic IDs under input permutation.

## Deferred work

This prototype does not estimate uncertainty, causal effects, a Hawkes model, a propagator,
censoring-adjusted incidence, optimal execution, or a strategy. It does not solve identity
uncertainty, partial wallet attribution, parent/metaorder inference, inexact timestamps, atom domains
beyond signed `int64`, cross-venue routing, or real-source admission. Those require new typed
contracts and prospective evaluation rather than broadening this V1 surface silently.
