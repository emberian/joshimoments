# Red team: where the physics analogies fail

## 1. Default posture

Markets contain measurable flows, conservation identities, networks, state-dependent response, and
multi-scale activity. This makes physical language tempting. The danger is not metaphor itself; it
is silently importing physical closure assumptions:

- passive particles rather than strategic agents;
- fixed space rather than endogenous topology;
- conserved mass rather than entry, exit, minting, attention creation, and missing coverage;
- local interactions rather than global feeds and common causes;
- smooth trajectories rather than integer jumps and transaction boundaries;
- stationary constitutive laws rather than reflexive adaptation;
- exogenous measurement rather than a UI/operator that changes the policy; and
- causal propagation rather than selection, anticipation, and adversarial ordering.

The burden of proof is on the analogy. Ordinary statistical or market language is the default.

## 2. Anti-cargo-cult table

| tempting term | narrow admissible measurement map | hidden assumption imported | decisive break/falsifier | preferred label |
| --- | --- | --- | --- | --- |
| **field** | typed function/measure on declared bins, nodes, size, or time | common geometry and meaning | result changes under domain/reference measure or mixes authority rungs | indexed measure/state surface |
| **density** | `d mu/d nu` with explicit measure and units | continuum and stable reference volume | per-bin/per-price/per-log-price versions disagree materially | atoms per bin; events per second |
| **flux** | signed marked sum across a declared edge/boundary | conserved transported substance | source/sink/identity uncertainty dominates, or sign has no native meaning | boundary flow; signed event count |
| **velocity** | displacement of an identity-preserving object per time | persistent particles and spatial path | actors/tokens are created, split, route globally, or coordinate changes | transition rate; participant movement |
| **advection** | measured transport of stable occupancy along graph/lattice edges | local carrying flow | apparent motion is node birth, ranking change, resolver update, or common shock | edge-flow decomposition |
| **compressibility** | changing concentration/capacity over a declared domain | mass conservation plus volume response | total measure changes through source/sink or moving boundary | concentration/capacity change |
| **pressure** | directional marginal/finite-size quote cost under exact state | force-per-area, local equilibrium, equation of state | no area/force units; agents withdraw/adapt; buy/sell routes disagree | quote gradient; directional cost |
| **viscosity** | fitted relation between flow rate and delayed cost/response | local, stable dissipation coefficient | kernel is nonlocal, state/regime-dependent, or response anticipates flow | resilience/impact kernel |
| **diffusion** | variance scaling or transition approximation after jump audit | small IID increments and smooth state | jumps, lifecycle breaks, long memory, or state-dependent increments dominate | variance scaling; jump process |
| **turbulence** | only if scale-local transfer/cascade and robust scaling are measured | Navier–Stokes-like nonlinear cascade | burstiness disappears after seasonality/regime/source controls; no scale-local transfer | bursts; intermittency; nonstationarity |
| **vorticity** | circulation of typed graph flux or curl in a declared coordinate chart | physical rotational flow and coordinate-invariant curl | circulation changes under projection/orientation/identity resolution | cycle flux; phase-plane circulation |
| **shock/front** | documented discontinuity or propagating transition with speed/order | conservation-law wave and local propagation | simultaneous common feed, migration, MEV, or topology update explains event | jump; lifecycle break; cascade candidate |
| **temperature** | none by default; volatility/activity are separate observables | equilibrium ensemble and thermodynamic state | no state equation/equipartition; strategic regime changes | volatility; activity intensity |
| **entropy** | Shannon entropy of declared normalized weights | thermodynamic disorder and irreversible law | value changes with bins/labels/reference measure; no physical heat meaning | concentration entropy/diversity |
| **energy** | exact cost/PnL functional with units and boundary | conserved scalar or Lyapunov law | fees, external inflow, alpha, and repricing change it | execution cost; wealth; objective |
| **potential** | exact/fitted cost function whose derivative/subgradient has stated meaning | path independence and conservative force | route, fee, MEV, hysteresis, or state adaptation makes loops path-dependent | cost surface; local dual |
| **phase transition** | prospectively defined order parameter/change point with finite-sample tests | equilibrium critical phenomenon/universality | transition is lifecycle rule, platform update, or outcome-selected breakpoint | regime/lifecycle transition |
| **criticality** | stability boundary inside a named model | real system poised at universal critical point | seasonality/long memory/model restriction yields same estimate | near model stability boundary |
| **wave** | lagged cross-node response with measured propagation ordering/speed | local transport through medium | global post/feed or provider latency synchronizes nodes | delayed cross-response |
| **invariant manifold** | validated state set or proved first integral for action/profile | smooth conserved surface | integer/fee/LP/migration transition leaves level set | valid-state set; transition graph |

If a plot title uses the tempting term, its caption should include the narrow measurement map and
authority rung. If that makes the title embarrassing, rename the plot.

## 3. Pressure is not price

### 3.1 Why it seduces

Buy pressure, sell pressure, liquidity pressure, and social pressure feel intuitive. A rising
directional flow often accompanies a changing quote curve. In a convex trading-set approximation,
a marginal price can be a dual variable. None of this produces a physical pressure.

### 3.2 Candidate measurable objects

Use these directly:

```math
\text{signed base flux }J_x(\Delta t),
```

```math
\text{directional average quote }\bar p^\pm(q,t),
```

```math
\text{finite-size cost }\kappa^\pm(q,t),
```

```math
\text{capacity }q_{max}^\pm(\eta,t),
```

```math
\text{observed post-flow response }R(\tau\mid z_t,J_t).
```

They have different units and causal status. A scalar “pressure” would hide whether the state
contains persistent buying, thinning sell capacity, higher fees, route loss, or a platform burst.

### 3.3 Adversarial tests

1. **Direction reversal:** invert base/quote and buy/sell. Does the proposed pressure transform
   coherently?
2. **Same flow, different geometry:** hold signed atoms fixed across two reserve/bin states. If the
   score does not distinguish executable response, it is incomplete.
3. **Same geometry, different flow:** compare states with identical quote surfaces but different
   recent wallet/social histories.
4. **Route fork:** compare two routes with the same marginal mark but different capacity/fees.
5. **Withdrawal event:** LP removal changes quotes without taker flow. A flow-only pressure model
   should fail visibly.
6. **Platform burst:** many coins receive buy flow after a shared rank/feed event. Coin-local
   pressure must not claim endogenous causation.

### Stop rule

Do not create a canonical `pressure` feature. Retain the vector of native quantities. A learned
compression may exist at H3, but it must beat the components out of sample and remain visibly
decomposable.

## 4. Viscosity is not liquidity

### 4.1 Plausible narrow analogy

A temporary-impact or resilience kernel can relate signed flow history to later price/quote
response. A high cost per flow or slow recovery may look like resistance.

### 4.2 Why the constitutive law breaks

- AMM instantaneous cost is exact nonlinear geometry, not dissipation in a medium.
- LPs and arbitrageurs adapt strategically to expected flow.
- the response is nonlocal in time and can depend on actor identity/social information;
- a quote can disappear rather than resist smoothly;
- fees transfer wealth and may depend on state/tiers;
- MEV changes order and selection; and
- liquidity providers can coordinate or withdraw under common signals.

There is no reason for a local relation like `stress = viscosity * strain rate` to hold.

### Adversarial tests

- subtract exact protocol cost before fitting delayed response;
- compare flow-rate-matched events across lifecycle and LP withdrawal states;
- test kernel time homogeneity and state independence;
- test whether predicted recovery survives route/pool changes;
- include anticipated versus surprising flow; and
- evaluate closed-loop mechanical cost for spurious simulator profit.

Use `state-conditioned resilience kernel` or `flow–response operator`, not viscosity.

## 5. Diffusion is a scale-specific approximation

### 5.1 What can be tested

- variogram linearity for a named price object and lag range;
- small-increment conditional moments for a state coordinate;
- Fokker–Planck approximation to a queue or coarse reserve state; and
- graph random-walk baseline for participant movement.

### 5.2 What breaks it here

- discrete swaps and bin crossings;
- launch, completion, migration, route loss, rug/collapse, and revival;
- heavy tails and volatility clustering;
- persistent signed flow;
- state-dependent fees and integer thresholds;
- adaptive attention/hot-scope sampling; and
- an operator who exits/re-enters after graph inspection.

### Gate

Publish the jump mass and higher conditional moments at the proposed scale. If the events carrying
economic loss are in the discarded jump term, the diffusion is a visualization only.

## 6. Turbulence is almost always the wrong word

### 6.1 Burstiness is not turbulence

High volatility, fat tails, clustered events, fragmented liquidity, and complicated charts can all
look turbulent. Fluid turbulence additionally suggests nonlinear inertial transport and an energy
cascade across scales. JOSHI currently has no conserved kinetic energy, physical eddies, inertial
range, or scale-local transfer theorem.

### 6.2 Minimum evidence before the word is admissible

All would be required:

1. a field and domain with physically/statistically meaningful scale hierarchy;
2. a scalar quadratic or other conserved/transferred quantity with units;
3. measured cross-scale transfer rather than merely similar power laws;
4. an interval where injection and dissipation are separated;
5. robustness to event-time/wall-time choice, lifecycle, and source coverage;
6. held-out consequences beyond “activity is bursty”; and
7. a reason adaptive agents/global feeds do not dominate the scaling.

This burden is unlikely to be met. Use `intermittent`, `bursty`, `heavy-tailed`, `multi-scale`, or
`nonstationary` with the exact diagnostic.

### Cargo-cult falsifier

If a supposed turbulent regime is identified only after price explodes, or a log-log line is fitted
without alternatives and finite-size error, the claim is rejected.

## 7. Vorticity and circulation are coordinate traps

### 7.1 Limited graph definition

For a directed cycle `gamma` in one typed graph layer, a cycle flux can be defined:

```math
\Gamma_\gamma=\sum_{e\in\gamma}\operatorname{orientation}_\gamma(e)f_e.
```

This can describe token circulation among accounts or repeated participant movement among coin
family members. It does not establish a rotating market force.

### 7.2 Limited phase-plane definition

One may plot trajectories in a chosen two-dimensional projection, such as signed flow versus
executable-capacity change, and measure oriented loop area. The loop is coordinate-, smoothing-,
clock-, and lag-dependent. It can arise from hysteresis, delayed measurement, lifecycle forcing,
or plotting two filtered versions of the same signal.

### 7.3 Required attacks

- reverse edge orientation and coordinate order;
- change price to log-price and bin to log-bin coordinate;
- vary lag/filter without tuning on outcome;
- separate repeated identities from new arrivals;
- compare against phase-randomized/state-shuffled controls; and
- remove migration/topology-update intervals.

Use `cycle flux`, `hysteresis loop`, or `lead–lag phase portrait`. Do not create a `vorticity`
column.

## 8. Shocks, fronts, and waves

A migration, fee-tier crossing, one-bin traversal, route disappearance, social claim, callout, or
large trade can create a jump. Calling it a shock/front/wave imports local propagation.

### Measurement map for a propagation candidate

```text
origin event with occurrence and availability bounds
ordered affected nodes/venues/coins
state/quote change per node
distance or graph path with meaning
latency distribution and source coverage
common-feed/common-cause covariates
directional response kernel
```

### Breaks

- Pump's ranking/feed broadcasts globally;
- bots can observe the same source simultaneously;
- Solana transactions share a slot or bundle;
- one migration rewires the route graph instantly;
- provider delivery latency creates apparent order; and
- later entity/family joins create retrospective propagation paths.

Without an origin and transport test, use `joint transition`, `common burst`, or `ordered response`.

## 9. Temperature, entropy, and equilibrium

### 9.1 Volatility is not temperature

Volatility is a scale-, price-, and sampling-dependent statistic. Activity intensity is an event
rate. Neither supplies an equilibrium ensemble, equipartition law, or state equation. A market can
have high activity and low executable volatility, or a quote can disappear with few trades.

Never name a canonical `market_temperature`.

### 9.2 Shannon entropy is allowed, thermodynamics is not implied

Entropy of normalized bin, wallet, community, or attention weights can summarize concentration.
It depends on:

- category definition;
- binning/reference measure;
- identity resolver;
- coverage;
- whether weights use count, atoms, time, or value; and
- the zero/unknown treatment.

Report the underlying distribution and at least one simpler concentration statistic. An entropy
increase is not an irreversible law or necessarily diversification.

### 9.3 Equilibrium language

Competitive break-even models can serve as benchmarks. Pump launches and social transitions are
young, path-dependent, strategically manipulated, and lifecycle-driven. “Far from equilibrium” is
usually just a decorative way to say nonstationary. State the actual failed stationarity or
break-even condition.

## 10. Criticality and phase-transition theater

### 10.1 Hawkes near-criticality

A fitted kernel norm near one can reflect:

- genuine feedback inside the linear model;
- omitted seasonality/common causes;
- power-law memory represented by a restrictive kernel;
- pooling different lifecycle regimes;
- hot-scope selection;
- finite-window bias; or
- source retries/duplicates.

Call it `near the fitted model's stability boundary`, not a critical market, unless these challengers
are defeated.

### 10.2 Social transition

Community coalescence, creator participation, audience arrival, fragmentation, and decay are real
candidate transitions. They are nonmonotone competing events and may be driven by platform rules or
human decisions. A one-dimensional order parameter selected after a successful send is not a phase
transition.

### Minimum gate

- prospectively defined observable/order parameter;
- transition/risk set independent of eventual success;
- finite-size and censoring treatment;
- alternative change-point/lifecycle explanations;
- chronological replication; and
- executable relevance at the time the transition is detectable.

## 11. Adaptive agents break material laws

A material has the same constitutive response when probed under the same state, within its regime.
Market participants learn the probe and each other:

- LPs widen/remove/recenter;
- arbitrageurs couple venues;
- wallets split or route differently;
- creators/communities respond to price and tooling;
- platform ranking changes exposure;
- Ember revises disposition and exits/re-enters; and
- competing systems react to public flow and priority fees.

Thus an estimated `J=F(state)` can change because displaying or acting on it changes state and
agent policy. Constitutive estimates must be versioned by product, execution footprint, regime,
and breadth. Scale is not a passive extrapolation.

### Falsifier

A field relationship that disappears after the panel/policy is introduced may have been real under
the old composite process and still be unusable under the new one. This falsifies stationarity and
deployment value, not necessarily the historical description.

## 12. Reflexivity breaks observer independence

Even a read-only JOSHI display changes Ember's attention. Consequential UI leakage includes:

- a scalar score collapsing uncertain evidence into confidence;
- heatmaps making high-coverage mints look intrinsically active;
- famous-wallet badges inducing FOMO;
- a `pressure` arrow implying causation/action;
- smoothed fields concealing exact bin/route boundaries;
- model annotations changing the later labels used to retrain the model; and
- hidden source gaps rendering silence as calm.

Every field visualization needs:

```text
native observable decomposition
source/coverage watermark
authority rung
size/route/clock
uncertainty and unsupported state
whether Ember saw it before a later label/action
```

Model panels should be visually subordinate until natural use shows they improve decisions without
distorting attention.

## 13. MEV breaks naive locality and causality

A same-slot sequence can contain focal action, competing swaps, arbitrage, sandwich/backrun, and LP
or route changes. Provider time can differ from leader execution order. As a result:

- “before” by receive time can be after by chain order;
- observed fill selection depends on transaction configuration;
- the focal trade's mechanical state effect and other actors' response can be atomic/entangled;
- failed attempts are censored from successful-fill samples; and
- a route-level field can hide cross-venue adversarial response.

No local continuum derivative can repair missing order. Require chain locator, send/receive clocks,
transaction-attempt state, and explicit same-slot/bundle uncertainty.

## 14. Endogenous boundaries break divergence stories

A changing total inside a domain may reflect:

- new mint/node launch;
- migration to a new venue;
- board/filter/rank membership change;
- hot-scope activation;
- resolver adding a family member;
- account/profile identity revision;
- source outage/recovery; or
- position/episode boundary change.

Before interpreting source/sink or divergence, decompose:

```text
within-domain transition
boundary crossing
domain/topology change
observation/coverage change
resolver/model revision
unresolved residual
```

## 15. Causal feedback breaks one-way kernels

The observed loop is bidirectional:

```text
social/attention -> trades/liquidity/price
price/flow -> ranking/social attention/creator acts
JOSHI glass -> Ember attention/manual acts
Ember/manual acts -> market state and future training data
```

A unidirectional cross-kernel is a forecasting approximation. It does not establish one-way cause.
Required alternatives include common platform state, reverse lags, future-shift controls, unrelated
mints, and model classes with reciprocal/history-dependent coupling.

## 16. Exact adversarial fixtures

The field program should preserve fixtures that defeat pretty but invalid models:

1. **Atom closure:** internal transfers plus fees across nested portfolio/venue boundaries.
2. **Pump exact-division buy:** literal floor-plus-one differs from smooth/ceil intuition.
3. **Fee-tier edge:** one-atom state change alters fee selection.
4. **Virtual versus real reserve:** pricing capacity exists while payout capacity refuses.
5. **DLMM one-bin boundary:** smoothed density predicts a fill the exact traversal changes/refuses.
6. **Position share rounding:** per-bin floors create residuals a continuous pro-rata model misses.
7. **Migration splice:** same mint, new venue/topology, later-discovered canonical mapping.
8. **Same-slot reorder:** identical focal intent under two competing transaction orders.
9. **Coverage birth:** hot lane opens after a burst and creates apparent source intensity.
10. **Identity revision:** later wallet/social mapping would create a false historical graph flow.
11. **Platform burst:** many unrelated mints move after one ranking/feed change.
12. **UI intervention:** displaying a high-score badge changes inspection/arm rate and label mix.
13. **Runner liquidation:** marginal mark shows profit while full-size route shows loss/absence.
14. **Exit/re-entry:** frozen historical future credits an unattainable management path.

A proposed field/operator should publish which fixtures it survives and which are outside scope.

## 17. Language gate

Before merging a document, schema, chart, or model containing one of these terms—`pressure`,
`viscosity`, `turbulence`, `vorticity`, `temperature`, `shock`, `wave`, `criticality`, `phase
transition`, `potential`, `energy`, or `invariant manifold`—reviewers should ask:

1. Is the measurement map present?
2. Are units and clocks explicit?
3. Is the exact venue mechanism separated?
4. Is the topology fixed or modeled?
5. Are source/sink/coverage effects separated?
6. Does the term add a falsifiable relation beyond ordinary language?
7. Are adaptive agents, reflexivity, and MEV in scope?
8. Can the same claim be made more precisely without the metaphor?

If question 6 is no or question 8 is yes, remove the physics term.

