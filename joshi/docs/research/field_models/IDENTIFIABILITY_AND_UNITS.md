# Units, observation maps, identifiability, and falsification

## 1. Unit discipline is part of the model

A field equation is malformed when terms do not share dimensions. A study artifact should carry a
machine-readable unit signature even when the analysis uses normalized variables.

### 1.1 Base dimensions

Use distinct symbolic dimensions:

```text
[A_a]       atoms of exact asset a
[T_wall]    wall/monotonic duration
[T_event]   declared event count/index
[K_slot]    Solana slot/order coordinate
[P_y/x]     quote-asset y atoms per base-asset x atom
[C]         event count
[W_obs]     wallet/address evidence count
[U_social]  stable social-account evidence count
[V_px]      viewport pixels
[E_episode] episode count
[R_ref]     external reference-unit observation
```

`[T_event]` and `[T_wall]` cannot be substituted. `[W_obs]` is not people. `[R_ref]` is not an asset
unless an actual settled asset has that identity.

### 1.2 Common derived dimensions

| quantity | dimension |
| --- | --- |
| base trade flux | `[A_base]/[T_wall]` or `[A_base]/[T_event]` |
| event intensity | `[C]/[T_wall]` |
| Q64.64 bin price | exact fixed-point representation of `[P_y/x]` |
| whole-unit price | `[P_y/x]` adjusted by exact decimal exponents |
| quote cost `C(q)` | `[A_quote]` |
| average executable price | `[A_quote]/[A_base]` |
| response in log price | dimensionless, with explicit price object |
| LP bin entitlement | separate `[A_X]` and `[A_Y]` |
| viewport exposure | `[V_px]*[T_wall]` or card-seconds under declared rule |
| capital-time | `[A_asset]*[T_wall]` before valuation |
| graph flow | edge-specific: atoms, events, accounts, or assertions per time |
| entropy/HHI/participation ratio | dimensionless after a declared normalization |

### 1.3 Forbidden arithmetic

- adding token atoms from different assets;
- subtracting event time from wall time;
- averaging prices with different quote assets without an observed conversion;
- adding viewport seconds to post counts as “attention”;
- comparing DLMM 1e9 fee rates with Pump basis points as raw numbers;
- multiplying a marginal mark by inventory and calling it executable value;
- treating a normalized embedding coordinate as a physical unit; and
- using display-rounded decimals in exact transition or trigger logic.

## 2. Dimensionless groups must be earned

Dimensionless coordinates can improve cross-market comparison, but the denominator is a model
choice. Admissible candidates include:

```math
\text{reserve fraction}=q/x_{available},
```

```math
\text{participation}=q/V_T,
```

```math
\text{cost displacement}
=\frac{\bar p(q)-p_{marg}}{p_{marg}},
```

```math
\text{time-to-lifecycle scale}=\tau/\widehat T_{stage},
```

```math
\text{coverage fraction}=\text{eligible observed interval}/\text{declared interval}.
```

Each can fail:

- reserve fraction ignores routed/external liquidity;
- participation needs a complete contemporaneous volume denominator;
- marginal-price normalization is unstable near refusal/bin boundaries;
- lifecycle scaling can leak future duration;
- coverage fraction can be high while semantic parsing is dead.

Do not invent a market “Reynolds number” by combining quantities until dimensional cancellation,
mechanistic motivation, held-out regime ordering, and added predictive/descriptive value are shown.

## 3. Observation and selection operators

Let `W_t` be world state, `O_h` source acquisition under configuration `h`, `R_g` product rendering
under UI version `g`, and `A_Ember` the operator's attention/action process:

```math
Y_t=O_h(W_{\le t}),
```

```math
B_t=R_g(Y_{\le t},\text{filters/ranking}),
```

```math
(V_t,A_t)=A_{Ember}(B_{\le t},H_t,I_t,D_t).
```

Hot-scope acquisition then depends on `V_t,A_t`, changing future `O_h`. This makes the observation
map endogenous and high-resolution missingness not at random.

### Consequences

1. A hot-scope field estimates the attended/surfaced process unless a census denominator is joined.
2. Board rank and viewport are causes of observation/attention and possible consequences of market
   state; they are not harmless covariates.
3. A later UI panel changes which examples and labels enter the corpus.
4. Reweighting human-selected observations by an invented propensity does not recover the market.
5. The correct artifact includes the selection funnel, coverage, and product version.

## 4. Identifiability classes

### 4.1 Point-identified or exact under closure

- finalized atomic balance delta at a closed account boundary;
- direct transaction signer/user under a verified decoder;
- exact account bytes at a retained slot/write version;
- profile-bound deterministic quote from a complete state closure;
- app viewport geometry and gesture in a captured scene; and
- displayed quote/model output in witnessed replay.

These are still conditional on correct identity, program profile, and retained evidence.

### 4.2 Descriptively identifiable

- observed event intensity under healthy scoped coverage;
- signed-flow autocorrelation for the declared event universe;
- mark/quote/fill gaps;
- DLMM bin concentration from observed position state;
- viewport/open/arm funnel transitions; and
- observed response after an event.

These describe the observation policy and sample. They do not identify the hidden mechanism.

### 4.3 Partially identified or bounded

- executable liquidation when routes are incomplete or expire;
- wallet actor count under sybil/multi-wallet uncertainty;
- audience migration under incomplete identity matching;
- opportunity cost among several attainable alternatives;
- counterfactual fill under latency/order uncertainty;
- effect of Ember's selection with unlogged intuition; and
- scale-decay beyond expressed top-k choices.

Report intervals/sensitivity sets rather than one posterior mean when the bound is structural.

### 4.4 Not identified from ordinary observational history

- focal trade reaction impact;
- creator intent from permissionless fee receipt;
- causal social contagion from a Hawkes cross-kernel;
- unique human/controller identity from correlated wallets;
- latent liquidity as a current source fact;
- value of a changed management action holding the adaptive future fixed; and
- the policy Ember would use under a UI/model they never saw.

These require stronger design, intervention, natural experiment, or explicit assumptions. More
model capacity does not resolve them.

## 5. Gauge and equivalence issues

Here **gauge** means a representational degree of freedom that should not change a substantive
claim. It does not imply a physical gauge theory.

### 5.1 Numeraire and price-coordinate gauge

Changing quote asset, decimal normalization, price versus log-price, or inverted pair transforms
the coordinate. A result should state how it transforms.

- atomic price `y/x` has units;
- reciprocal price is nonlinear and changes additive returns;
- log-price shifts under multiplicative unit rescaling but differences do not;
- density per `dp` transforms differently from density per `d log p`; and
- a response kernel in one price coordinate is not numerically invariant in another.

Cross-venue comparison should prefer coordinate-aware quantities such as exact cost in a common
observed numeraire, fractional reserve usage, or log displacement—while retaining source values.

### 5.2 Account-label permutation

If two wallet addresses have identical observed roles/history under the study, swapping their
latent actor labels should not change an anonymous-flow result. A model whose forecast depends on
arbitrary database IDs has learned a label gauge.

Once direct identity evidence distinguishes them, the symmetry is broken only from the evidence's
availability time onward.

### 5.3 Entity-cluster equivalence

The same transaction graph can be explained by:

- one controller with many wallets;
- a coordinated fleet;
- a relayer or router serving unrelated users;
- common response to the same feed; or
- chance overlap in a small coin universe.

Entity models should output an equivalence class or relation-specific posterior. A hard cluster ID
is a hypothesis, not a canonical identity.

### 5.4 Social-state label switching

Latent states such as `coalescing`, `contested`, and `decaying` may permute or split across fitted
models. Anchor them to measurable emissions/transitions and preserve versioning. A semantic label
that only becomes stable after looking at outcomes is narrative leakage.

### 5.5 Territory/family equivalence

Several groupings can fit the same metadata and flow:

- one territory with competing mints;
- overlapping person and trend territories;
- unrelated launches sharing imagery;
- one launch farm without audience coherence.

Downstream conclusions must be sensitive to plausible membership maps. “Canonical coin” is never
a gauge fixing by eventual market cap.

### 5.6 Baseline–kernel equivalence

In an intensity model, slow baseline variation, long self-excitation, shared exogenous activity,
and regime switching can generate similar second-order statistics. The fitted branching ratio is
not uniquely identified as endogenous causation without additional structure.

### 5.7 Reaction–prediction equivalence

Observed post-event motion admits many decompositions into focal reaction, advance information,
common causes, and other agents' response. Source-book identity
`observed = reaction + prediction` prevents assigning the whole response to the focal event, but
does not identify the parts.

### 5.8 Route/path equivalence

Two routes can yield similar expected output at observation time while differing in:

- accounts and programs;
- fee/tip/compute costs;
- failure and landing distribution;
- MEV exposure;
- market state changed; and
- downstream price/route reaction.

Equivalent endpoints in a frozen calculator are not equivalent live actions.

### 5.9 LP share-scale representation

Within a mathematical entitlement ratio, simultaneous scaling of position share and bin supply can
leave the ratio unchanged. On chain, the stored integers, rounding, checkpoints, and other LPs'
claims matter. Do not quotient exact state by this model symmetry in the ledger/protocol layer.

### 5.10 Attention normalization

Viewport pixels, card-seconds, opened panels, explicit comparisons, and self-report are alternative
projections, not gauges of one known latent scalar. Results should be reported per measure and
tested for conclusion stability; no normalization makes cognition observed.

## 6. Non-point-in-time joins that invalidate a field

A field artifact is rejected if any feature uses a relation known only later without marking it as
retrospective. High-risk joins include:

- current handle/profile wallet joined to an old post or decision;
- eventual canonical pool attached before migration was known;
- current creator/fee recipient applied to an old curve state;
- eventual coin-family winner applied at launch;
- later wallet-cluster resolution used in an earlier flow field;
- a backfilled post ordered by source time but unavailable at decision time;
- future peak, collapse, or route loss used to define regimes/features;
- an interview label written onto the original action; and
- a model/embedding trained on the evaluation future.

Every join requires both:

```text
valid_at(event/scene time)
known_by(knowledge cutoff)
```

Retrospective analysis can relax `known_by` only when it is explicitly labeled retrospective and
never used to score as-known action quality.

## 7. Core estimands

### E0 — settlement residual

```math
\varepsilon_a^B=\Delta M_a^B-\Phi_{in}+\Phi_{out}-\Gamma_{mint}+\Gamma_{burn}-\Gamma_{convert}.
```

**Use:** validates evidence/accounting.

**Falsifier:** any unexplained nonzero atomic residual.

### E1 — quote/fill state error

For intended quote `Q(z_t,q)` and landed fill at `z_land`:

```math
E_{fill}=\text{actual net atoms}-\text{quoted net atoms},
```

decomposed into state movement, route, fee/profile, transaction cost, and unresolved residual.

**Use:** establishes whether micro-profit studies are measurable.

**Falsifier:** unresolved error comparable to the gross target.

### E2 — executable capacity surface

For cost/slippage bound `eta`, define

```math
q_{max}(\eta,t)=\sup\{q:Q_t(q)\text{ exists and satisfies }\eta\}.
```

Report by direction, route, and freshness.

**Falsifier:** quote expiry/landing error prevents capacity classification.

### E3 — deterministic-adjusted observed response

```math
R^{adapt}(\tau)
=\Delta Y_{observed}(\tau)-\Delta Y_{frozen\ protocol}(0^+),
```

where both terms use compatible price/quote objects. This is still observed residual response, not
causal reaction.

**Falsifier:** the result changes sign/magnitude under reasonable price object, state alignment, or
coverage treatment, or is below quote/source uncertainty.

### E4 — flow-memory increment

Held-out improvement of a state/history model over IID/seasonal/Markov baselines for signed events,
conditioned by lifecycle and actor evidence.

**Falsifier:** no stable chronological gain or gain disappears under cold-scope/participant
controls.

### E5 — liquidity concentration and withdrawal response

Change in exact bin inventory/support and executable withdrawal/liquidation around activity or
volatility events, preserving LP actions and fees.

**Falsifier:** smoothed concentration adds no information beyond exact active-bin/range/quote state,
or state reconstruction is incomplete.

### E6 — topology-transfer residual

Difference between post-migration exact state and the pushforward of pre-migration state under a
declared map.

**Falsifier:** identity/asset mapping is ambiguous or later knowledge is required.

### E7 — audience/territory movement

Change in prospectively known participant overlap and activity share among family members, with
stable identity and healthy coverage.

**Falsifier:** directed movement collapses to platform-wide rotation, new-account arrival, family
resolver revision, or coverage asymmetry.

### E8 — attention routing value

For a common downstream shadow policy, compare candidate outcome distributions at consecutive
funnel stages: census, surfaced, viewport, opened, armed.

**Falsifier:** no prospective incremental ranking value or the panel consumes more useful attention
than it produces.

### E9 — episode-management contrast

At common horizon, compare actual exit/flat/re-entry or partial/runner path with attainable declared
alternatives using exact execution/liquidation semantics.

**Falsifier:** advantage disappears under common terminal time, residual liquidation, costs, and
selection controls, or changed paths require the observed future unchanged.

### E10 — scale-dilution curve

Estimate net value, prediction quality, capacity, correlated exposure, and attention burden as
breadth expands from Ember's expressed choices toward machine-nominated scope.

**Falsifier:** per-candidate structure or total value collapses before intended scale, or expansion
changes market/attention feedback beyond support.

## 8. Negative controls and adversarial tests

### 8.1 Temporal controls

- future-shift social events;
- availability-time versus source-time features;
- shuffled event marks within lifecycle/state blocks;
- false migration joins offset to a nearby pool; and
- model trained through versus strictly before evaluation cutoff.

### 8.2 Cross-sectional controls

- unrelated mints during the same platform burst;
- matched unselected candidates from the actual scene;
- anonymous flow matched to watched-wallet flow;
- alternative family membership maps; and
- cold-market census sample not promoted by attention.

### 8.3 Source/coverage controls

- known outage intervals;
- provider disagreement;
- repeated cached payloads;
- parser quarantine windows;
- missing-key subscriptions despite global heartbeat; and
- deliberate downsampling whose selection is independent of activity.

### 8.4 Protocol controls

- one-atom and exact-division rounding edges;
- reserve/fee-tier/capacity boundaries;
- DLMM one-bin traversal and active-bin crossing;
- route with same mark but different size capacity;
- failed/unlanded transaction; and
- same-slot competing transaction before/after focal action.

### 8.5 Operator/UI controls

- panel hidden versus visible when safe to randomize presentation;
- retrieval order randomized without randomizing capital;
- explicit `none analogous` and `not articulable` cases;
- prospective annotation versus retrospective interview; and
- alert dedupe versus preserved underlying events.

## 9. Field-artifact manifest

Every persisted field estimate should include:

```text
field_id, field_kind, authority_rung
domain and topology version
subject/venue/lifecycle scope
value unit and reference measure
clock/event-order definition
observation and coverage manifest
knowledge cutoff and production time
protocol/parser/model/UI versions
aggregation/coarse-graining operator
exact mechanical components used
missingness and state-completeness grade
uncertainty/bounds
baseline and negative-control results
known gauge/equivalence class
falsifier status and support boundary
supersedes/retracts
```

An image or tensor without this manifest is exploratory scratch, not evidence.

## 10. Promotion rules

### H0/H1 promotion

Requires exact unit typing, complete closure, golden/adversarial fixtures, official/deployed
comparators where available, and zero unexplained reconciliation residual.

### H2 promotion

Requires replayable projection, explicit coverage, stable aggregation definition, and visual/raw
spot checks. It may be useful even with no predictive value.

### H3 promotion

Requires chronological held-out improvement over a simple baseline, calibration, negative
controls, regime/support statement, and effect larger than measurement/quote error.

### H4 promotion

Requires explicit observational equivalence, sensitivity to alternative priors/labels/topologies,
prospective probes, and refusal to render latent inference as fact.

### H5 promotion

Requires H0–H3 closure for its action domain, prospective policy declaration, attainable execution,
complete path scoring, UI-intervention logging, scale/capacity/tail analysis, and an independent
safety capability envelope. This still does not authorize live execution.

