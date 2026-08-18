# Field models without physics theater

Status: exploratory formalization; read-only research; no strategy or authority implication.

## Purpose

This corpus asks whether a **dynamic stratified market field** is a useful language for JOSHI.
It does not assume that a market is a fluid, that attention is conserved, that price is pressure,
or that one partial differential equation can represent Pump, PumpSwap, Meteora, social activity,
wallet behavior, and Ember's operator process.

The admissible meaning of *field* is deliberately modest:

> a typed quantity indexed by a declared domain, clock, observation policy, and unit.

Examples include an exact asset balance over accounts, token inventory over DLMM bins, an
executable quote curve over trade size, marked trade counts over event time, or viewport seconds
over the product's candidate set. Some are exact. Some are estimates. Some are latent hypotheses.
They must not share an authority level merely because they can be drawn as heatmaps.

The source-book bridge is the completed
[`trades_quotes_prices`](../../microstructure/trades_quotes_prices/README.md) corpus. Its most
important constraints survive here:

- price, flow, liquidity, state, and execution are coupled;
- observed response is not caused impact;
- venue mechanics precede statistical analogy;
- persistent flow can coexist with weak return predictability;
- provider revenue must include selection, inventory, and liquidation; and
- historical insertion of a different action does not preserve the observed future.

The project bridge is [`PROJECT.md`](../../PROJECT.md): the target is Ember's composite
selection–execution–management process, and the atomic behavioral unit is an operator episode,
not a position or one market event.

## Non-negotiable hierarchy

Every object in this corpus belongs to exactly one rung unless a stronger rung is explicitly
earned:

| rung | authority | examples | permitted claim |
| --- | --- | --- | --- |
| **H0: settlement identities** | exact after finalized reconciliation and boundary declaration | atomic asset postings, internal-transfer cancellation, flat-to-flat inventory epoch | what balances changed and whether a declared boundary closes |
| **H1: protocol kinematics** | exact only under a named program/profile/state closure | Pump/PumpSwap integer quote map, DLMM bin/share arithmetic, transaction state transition | what the profiled program computes or a landed transaction changed |
| **H2: descriptive fields** | observation-policy-dependent summaries | signed-flow measure, quote surface, bin concentration, attention occupancy, graph edge counts | what was observed and how it was aggregated |
| **H3: fitted constitutive operators** | statistical model with held-out scope | intensity, response kernel, transition hazard, state-dependent resilience | conditional forecast or compression under a declared regime |
| **H4: latent/abductive fields** | equivalence class of explanations | latent liquidity, community coherence, actor clusters, unspoken operator predicate | which hidden mechanisms remain compatible with observations |
| **H5: policy/controller** | prospective decision object | attention ranking, crackle trigger, LP edit policy, runner management | how a declared policy would act under its support and safety envelope |

No amount of fit promotes H2 to H0, H3 to causal mechanism, H4 to identity, or H5 to safe live
authority. A learned operator is not a conservation law.

## The state is stratified, not flattened

JOSHI's market state has coupled but non-interchangeable strata:

```text
S(t) = (
  ledger settlement,
  venue-native microstate,
  route and execution state,
  market event flow,
  launch/migration topology,
  wallet/identity graph,
  social/community graph,
  product surface and attention funnel,
  operator episode and portfolio state,
  source coverage and knowledge state
)
```

Each stratum has its own entities, clocks, units, transition rules, missingness, and epistemic
status. Couplings are typed maps or events. They are not license to put all columns into one
continuous state vector and call it a market fluid.

## Corpus map

- [`STATE_SPACE.md`](STATE_SPACE.md) defines domains, strata, clocks, observables, latent objects,
  topology, and price objects.
- [`CONSERVATION_AND_GEOMETRY.md`](CONSERVATION_AND_GEOMETRY.md) formalizes exact settlement,
  marked balance laws, AMM state manifolds, DLMM discrete geometry, and launch/migration maps.
- [`FIELDS_AND_OPERATORS.md`](FIELDS_AND_OPERATORS.md) defines compressible measures, marked
  fluxes, source/sink/reaction terms, graph flows, memory, response kernels, and candidate
  constitutive operators.
- [`IDENTIFIABILITY_AND_UNITS.md`](IDENTIFIABILITY_AND_UNITS.md) specifies unit discipline,
  observation maps, gauge/equivalence issues, estimands, negative controls, and falsifiers.
- [`ANALOGY_REDTEAM.md`](ANALOGY_REDTEAM.md) attacks fluid, pressure, viscosity, turbulence,
  vorticity, shock, temperature, and field analogies before they become design assumptions.
- [`JOSHI_LANES.md`](JOSHI_LANES.md) maps the hierarchy into evidence, schema, glass, studies,
  strategy families, promotion gates, and open questions.

## Compact notation

| symbol | meaning | authority by default |
| --- | --- | --- |
| `a in A` | exact asset identity: network, token program, mint/native identifier | H0 |
| `u in U` | account/custody location | H0 when chain-derived |
| `v in V` | typed venue/pool/curve | H1 |
| `c in C` | mint/coin identity; never ticker alone | H0/H1 |
| `e in E` | source-native event with complete locator | H0–H2 by event kind |
| `k` | chain/event index with declared order | H0–H2 |
| `t` | wall/monotonic time with named clock | H2 |
| `z_v` | venue-native exact state | H1 |
| `b_{u,a}` | atomic balance of asset `a` at account `u` | H0 |
| `N(dm,dt)` | marked event-counting measure | H2 |
| `mu_t` | measure on a declared domain and reference measure | H2 unless explicitly exact |
| `Q_v(z,q)` | size-specific quote calculation at state `z` | H1 |
| `K(t,u;x)` | fitted response/memory kernel conditioned on state `x` | H3 |
| `Lambda(t|H_t)` | conditional event intensity | H3 |
| `L_t` | latent state, never a source column | H4 |
| `pi(a|h)` | declared policy mapping observed history to an act | H5 |

`A`, `E`, `I`, `L`, `Q`, and `S` are overloaded letters in the surrounding literature. Every
study must publish a local symbol table rather than relying on this shorthand.

## Admission rule for an analogy

A metaphor may enter an analysis only if it supplies all eight items:

1. **domain:** nodes, bins, price coordinate, wallets, candidates, or another explicit set;
2. **measure:** what is counted or weighted;
3. **unit:** atoms, events, seconds, pixels, quote atoms/base atom, or dimensionless ratio;
4. **clock:** slot, chain order, event time, source time, receive time, or wall time;
5. **observation map:** which retained evidence yields the quantity;
6. **operator:** exact transition or fitted transformation;
7. **falsifier:** an observable way the proposed relation can fail; and
8. **residue:** what instrument remains useful if the analogy fails.

If any item is missing, use ordinary market language. “Bursty signed flow with route loss” is
better than “turbulent liquidity vortex.”

## Scope boundary

This corpus does not:

- propose transaction construction, signing, or execution;
- select an LP policy, crackle rule, price predictor, or universal market circuit;
- treat continuous notation as more real than exact integer state transitions;
- infer creators, communities, or wallet controllers from one generic graph;
- make market attention or liquidity a conserved substance;
- claim that a fitted Hawkes kernel identifies contagion;
- claim that a response kernel identifies mechanical impact; or
- use physics vocabulary as evidence of sophistication.

Its goal is narrower: give JOSHI a language that can preserve exact mechanics and multiple
interacting forms of flow while remaining capable of saying that the field picture added nothing.

