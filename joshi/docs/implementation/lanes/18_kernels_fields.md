# Lane 18 — response kernels and dynamic-field probes

## Outcome and boundary

This lane adds two deterministic, offline contract probes. It does not add a trading policy, a
profitable-strategy claim, a model service, or an online learner.

- `kernel-prototype` estimates marked conditional responses for trade intensity, signed flow,
  liquidity change, attention change, and price return. Its estimand is the equal-weight mean of
  wallet-cluster response means within a declared caller/mark/context/regime/topology/horizon cell.
  It is descriptive and selection-biased, not a counterfactual response to intervention.
- `field-prototype` computes distinct graph and reserve-geometry observables. Wallet flow,
  attention flow, venue reserves, lifecycle/topology epochs, node divergence, cycle circulation,
  and Hodge components never collapse into a single “pressure” number. These are machine field
  estimates and are a different type from operator-perceived configurations, gestures, or chart
  drawings.

Both jobs use generated data with known structure so that contract and recovery failures are
visible before real evidence is admitted.

## Point-in-time contract

Kernel marks carry occurrence identity, exact event-time status, event valid time/slot, arrival
time, a named information cutoff, response time and separate response availability. Context,
identity, regime, and topology references carry the exact version selected as known, their valid
interval, availability, and retraction time. A scene/choice relation is called
`scene_choice_complete`; it deliberately does not claim that a rendered presentation was actually
witnessed. Complete eligible choice members close the universe digest.

The V1 response encoding is deliberately narrow: a registered observable/unit pair with a signed
`int64` value or an explicit coverage gap. Larger atom domains, rationals, intervals, and inexact
event times require a later tagged-value contract rather than silent coercion. Optional caller,
wallet, territory, community, venue, size, and choice fields use statuses and nulls; there are no
sentinel IDs or fabricated zero amounts. Only selected-as-known regime/topology rows enter a fit.

Risk cohorts distinguish exact events, administrative right censoring, and source-loss right
censoring. Source loss requires a gap ID; a healthy administrative horizon does not. Exact event
bounds and risk intervals are half-open. Outcomes have their own `outcome_known_at`, so a future
peak or provider multiple cannot become an event-time feature.

Field inputs use the same bitemporal rule. Each graph edge names its layer, carrier/domain, unit,
topology epoch/version, valid interval, availability, information cutoff, coverage window, and
gap. The incidence orientation is the core ecology convention: tail/source is -1 and head/target
is +1. Hodge fits are per exact layer, carrier, unit, and topology epoch; topology changes are a
boundary, not rows to concatenate. Input identity is computed from the eligible as-known closure,
so appending a later-unavailable record cannot change an earlier result identity.

## Estimates and uncertainty

The nonparametric kernel first averages repeated responses within attributed wallet and then gives
wallets equal weight. Normal intervals over wallet means are retained only as a small-sample
descriptive approximation. Outputs include event and wallet support, effective sample size,
coverage ratio, exact coverage window/gap IDs, mark share, overlap status, and within-topology
regime deltas. An all-gap cell has a null estimate and `no_observed_support`.

The “Hawkes” output is only a symmetric fixed-window arrival log-rate screen. It is not a fitted
Hawkes likelihood, branching ratio, causal effect, or contagion proof. The competing-risk output is
an Aalen–Johansen candidate diagnostic over witnessed synthetic risk sets. Both use a separate
candidate-diagnostic schema and restrictive claim scope.

For graphs, the probe emits node divergence, declared-cycle circulation, per-edge gradient/curl/
harmonic components, and mathematical squared norms. Gap sensitivity bounds are named as such and
are not sampling uncertainty intervals. Venue outputs are observational price response per flow
and recovery. The local susceptibility formula is permitted only for the named synthetic
constant-product profile and formula version; it is not generalized to a real venue or protocol.

## Artifact closure

Canonical jobs write immutable bundles:

- `.artifacts/kernels/kernel-<digest>/kernel_estimates.parquet`
- `.artifacts/kernels/kernel-<digest>/candidate_diagnostics.parquet`
- `.artifacts/fields/field-<digest>/field_observables.parquet`

Every manifest contains a stable artifact occurrence ID distinct from its content/run digest,
estimator and configuration digest, fit policy/cutoff, input contract, locked environment/source
digest, artifact schema descriptor/digest, logical and physical digest, row count, and primary key.
Rows repeat estimator/configuration, eligible input snapshot/logical digest, fit cutoff, maximum
input availability, support, coverage, and claim scope.

## Synthetic gates and limitations

Tests recover a known wallet-cluster response, pure triangular circulation with zero divergence,
Hodge curl with zero harmonic residual, and explicit reserve susceptibility/response/recovery.
They reject incomplete choice universes and topology/context versions unavailable at the relevant
cut; they preserve right censoring, gaps, layer separation, and topology boundaries; and they prove
byte-identical job publication.

These fixtures do not establish external validity, causal identification, stationarity, market
coverage, profitability, or safe scale. Before real estimation, export contracts must provide
event/revision history, identity versions, complete attended choice/presentation evidence where
available, source windows/gaps, reserve/profile closure, and outcome censoring. Promotion requires
synthetic recovery, leakage counterexamples, adequate overlap, predeclared falsification criteria,
and evaluation keyed to decisions—not attractive isolated curves.

## Commands

```bash
uv --directory analysis run --locked joshi-analysis kernel-prototype \
  --output-root analysis/.artifacts/kernels
uv --directory analysis run --locked joshi-analysis field-prototype \
  --output-root analysis/.artifacts/fields
uv --directory analysis run --locked pytest
uv --directory analysis run --locked ruff check .
```
