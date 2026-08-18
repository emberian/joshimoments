# Dynamic stratified and multiplex state space

## 1. Why one vector is the wrong primitive

A flat feature vector hides three distinctions that are load-bearing for JOSHI:

1. **authority:** finalized asset effects, provider observations, and model outputs are not peers;
2. **geometry:** a bonding curve, constant-product pool, DLMM bin lattice, social graph, and
   attention funnel do not share a natural coordinate system; and
3. **clock:** chain order, wall time, event time, source availability, and operator time are only
   partially aligned.

Define the world at an index `omega` as a collection of stratum states plus typed couplings:

```math
\mathsf S_\omega
= (\mathsf S^{set},\mathsf S^{venue},\mathsf S^{route},\mathsf S^{flow},
   \mathsf S^{life},\mathsf S^{wallet},\mathsf S^{social},\mathsf S^{surface},
   \mathsf S^{operator},\mathsf S^{coverage};\,\mathsf C)_\omega.
```

`omega` is not assumed to be one real-valued time. It can name a chain locator, observation
boundary, scene cutoff, or event index. `C` is a set of typed coupling assertions. The observed
state is a projection of this collection, not the collection itself.

## 2. Base identities and domains

### 2.1 Asset and custody domain

An asset identity is at minimum:

```text
AssetId = (network, token_program, mint_or_native_id)
```

Let:

- `A` be exact asset identities;
- `U` be accounts, vaults, custody locations, and declared off-chain boundary accounts;
- `b(u,a,k) in Z` be the reconciled atomic balance at chain boundary `k`; and
- `P subset U` be a versioned portfolio or venue boundary.

Symbols, display names, decimals, wrapped/native equivalence, and reference-unit values are
projections. They do not alter `A` or the atomic ledger.

### 2.2 Venue domain

`V` is a disjoint union, not one pool table:

```math
\mathcal V
=\mathcal V_{pump}\;\sqcup\;\mathcal V_{pumpswap}\;\sqcup\;
 \mathcal V_{dlmm}\;\sqcup\;\mathcal V_{lob}\;\sqcup\;\mathcal V_{other}.
```

Every `v` carries program, deployment/profile, pool/curve identity, asset pair, lifecycle, and exact
state closure. Venue families may expose different valid actions and state coordinates. The
disjoint union prevents an absent best queue from becoming a zero queue and an absent active bin
from becoming bin `0`.

### 2.3 Market and product subjects

Keep distinct:

- mint/coin identity;
- coin family membership assertion;
- represented person/project/trend/subject;
- territory hypothesis;
- venue and route;
- operator episode;
- inventory epoch; and
- management tranche.

The same mint can occur on several venues. One episode can follow several mints. One territory can
overlap another. No `coin_id -> territory_id -> creator_id` functional dependency is presumed.

### 2.4 Actor and graph domain

`G_wallet` and `G_social` are multiplex temporal graphs with typed nodes and edges:

```text
wallet nodes: signer, profile wallet, recipient, funder, relayer, vault, program account
social nodes: stable platform account, Pump profile, post, reply, community, subject
market nodes: mint, pool, curve, launch, fee route, transaction
operator nodes: episode, scene, gesture, assertion
```

Edge layers remain separate: `signed_trade_as_user`, `fee_paid_by`, `funded`,
`wallet_controls_profile`, `authored`, `mentioned`, `followed`, `routes_fee_to`, `competes_with`,
and `operator_attended` are not weights of one generic adjacency matrix.

## 3. Clock and order bundle

For an event or observation `e`, retain a clock vector:

```math
\tau(e)=(k_{chain},t_{source},t_{request},t_{receive},t_{persist},t_{available},
         t_{render},t_{gesture},t_{finality},t_{enrich}).
```

Components can be absent, intervals, or incomparable. Chain order can be a tuple
`(slot, transaction_index, instruction_path, event_index, write_version)`. Wall times require a
named clock and quality. Event time is an index over a declared event universe, not a timestamp.

Allowed order claims are local:

- chain locators order canonical chain effects within their supported scope;
- monotonic receive clocks order local acquisition transitions;
- scene manifests determine what was available/rendered before a gesture;
- source timestamps express what a source claims, with precision and authority; and
- late backfill can precede in source time while following in knowledge time.

A fitted field over wall time may not silently use final chain order. A causal feature may not use
an event whose `t_source` is early but `t_available` is late.

## 4. The ten strata

### 4.1 Settlement stratum `S_set`

Contents:

- exact atomic balances and postings;
- mint, burn, wrap/unwrap, transfer, fee, rent, reward, and unknown residual classes;
- finalized/canonicality state;
- portfolio and venue boundary manifests; and
- reconciliation residuals.

This is the only stratum with ordinary commodity conservation authority. Reference-value changes,
PnL, marks, and strategy attribution are projections over it.

### 4.2 Venue stratum `S_venue`

Contents are venue-native.

For Pump, candidate coordinates include virtual/real base and quote reserves, completion/migration
state, mint supply, fee configuration, creator applicability, mode flags, and token-program state.

For PumpSwap, candidate coordinates include base/raw quote vault reserves, signed virtual quote
reserve, pool canonicality, mint supply, fee configuration, lifecycle, and token-program state.

For Meteora DLMM, candidate coordinates include active bin, bin step, fee/volatility parameters,
bitmap/array state, and per-bin `(x_j,y_j,L_j)` plus per-position share/checkpoint state.

Coordinates absent from a venue have type `not_applicable`, not numerical zero. Unsupported
decoder fields remain unknown.

### 4.3 Route and execution stratum `S_route`

Contents:

- exact-size quote requests and results;
- venue/path candidates and route availability;
- observation and expiry closure;
- slippage bounds and fee components;
- simulation, construction, signature, send, landing, failure, finality, and reconciliation state;
- priority fee/tip/compute settings when relevant; and
- competing-state and MEV evidence.

This stratum separates the program's quote map from the attainable fill. An intended trade is not a
flux until it changes landed balances.

### 4.4 Event-flow stratum `S_flow`

Contents:

- a marked counting measure over launches, trades, liquidity edits, migrations, fee/claim events,
  posts, replies, callouts, wallet acts, and operator acts;
- event marks such as side, atomic size, venue, state, source, actor evidence, and lifecycle;
- coverage windows and gaps; and
- event-time projections derived from a declared eligible event set.

There is no universal sign. Buy/sell sign, asset delta, liquidity-add/remove sign, audience-arrival
sign, and operator increase/reduce sign are separate marks.

### 4.5 Lifecycle/topology stratum `S_life`

Contents:

- launch and mint creation;
- curve/pool association;
- curve completion and migration;
- canonical/noncanonical route changes;
- duplicate/family/territory membership assertions;
- pool activation/deactivation and route loss; and
- evidence-time and validity-time for every topology edge.

This is a dynamic graph. Migration can change state dimension, venue rules, fee rules, and price
coordinate at once. It is not a smooth return observation.

### 4.6 Wallet stratum `S_wallet`

Contents:

- direct signer/user actions;
- balance and transfer paths;
- profile-wallet assertions;
- fee payer, relayer, funder, bundle, and cluster relations;
- actor/strategy hypotheses with evidence grades; and
- per-wallet/source coverage and left truncation.

The observable primitive is a typed address/action relation. Human, bot, fleet, and common-control
labels are latent equivalence classes unless separately evidenced.

### 4.7 Social stratum `S_social`

Contents:

- immutable/revisioned posts, replies, follows, media, streams, mentions, and community objects;
- platform identities keyed by stable IDs where available;
- fee routing and platform-authorized claim events;
- awareness, participation, endorsement, and community assertions kept separate;
- duplicate competition and audience-overlap summaries; and
- deleted/mutated content as temporal evidence, subject to retention policy.

Social state is nonmonotone. Claim, public participation, audience arrival, fragmentation, and
decay are competing transitions rather than stages on one scalar ladder.

### 4.8 Product-surface and attention stratum `S_surface`

Contents:

```text
census eligible
  -> source surfaced and ranked
  -> client rendered
  -> viewport visible
  -> interacted with
  -> compared/shortlisted/dismissed/armed
```

Each set and ordering is preserved per scene. Viewport occupancy is physical UI evidence, not gaze
or comprehension. Active attention, internal salience, and Ember's unspoken intuition remain
partially latent.

### 4.9 Operator/portfolio stratum `S_operator`

Contents:

- episode, inventory epoch, lots, optional tranches, and flat-watching intervals;
- playbook/entry mode, stance, thesis, horizon/review condition, and management act;
- exact portfolio state, reservations, competing opportunities, and current executable exposure;
- raw gestures, utterances, annotations, corrections, and interviews; and
- actual external actions joined after reconciliation.

Operator state is part of the composite policy. It cannot be reduced to market state or treated as
measurement noise.

### 4.10 Coverage and knowledge stratum `S_coverage`

Contents:

- acquisition manifests and source health;
- observation/blob/assertion/derivation provenance;
- parse/quarantine/drift state;
- known gaps, late arrival, and backfill;
- witnessed, knowledge-cutoff, and retrospective watermarks; and
- the exact information manifest used by a model or scene.

Every other observed stratum is conditional on this one. Collector silence becomes a zero only
inside healthy, correctly scoped coverage where silence has that meaning.

## 5. Observed and latent state

Let `W_omega` denote the inaccessible world state and let acquisition/product version `h` define an
observation operator:

```math
O_h: W_\omega \longrightarrow Y_\omega^{(h)}.
```

`O_h` includes source access, polling/subscription, decoder, retention, coverage, scene rendering,
and hot-scope selection. It is adaptive: prior observations and Ember's attention change which
future details are acquired. Therefore missing high-resolution state is generally not missing at
random.

### Direct observables

Examples, when adequately evidenced:

- finalized atomic balance deltas;
- raw account bytes at a slot/write version;
- transaction locator and signer roles;
- exact provider response and receive time;
- board membership/order in one retained response;
- app render and viewport geometry;
- exact operator gesture/utterance; and
- source content bytes/revision at observation time.

### Derived observables

Examples:

- decoded trade sign and fee components;
- exact protocol quote from a complete state closure;
- size-specific liquidation quote;
- signed-flow bin or event-time ACF;
- bin concentration/entropy;
- current family-membership projection; and
- observed-response surface.

These require versioned transformations and may be corrected.

### Latent objects

Examples:

- future undeployed liquidity and trader intentions;
- the focal trade's reaction impact;
- creator awareness before an evidenced act;
- community coherence or audience allegiance;
- human/controller identity behind wallet clusters;
- Ember's complete internal predicate for an action; and
- future counterfactual policy path after a changed action.

Latent objects can be modeled but never backfilled as if observed. An H4 object must expose at
least one observational equivalence class and one probe that could shrink it.

## 6. Dynamic topology

### 6.1 Launch/migration graph

Let `T_life(t)=(N_t,E_t)` contain typed nodes for mint, curve, pool, route, coin family, and
territory. Edge events append or revise assertions such as:

```text
mint_created
trades_on_curve
curve_completed
migrated_to_pool
canonical_pool_for
routable_via
competes_with
succeeds_or_derives_from
```

An edge has valid time and observed time. `migrated_to_pool` is not necessarily invertible: one
source state can link to several candidate pools or routes, and evidence can arrive late. Asset
identity may persist while venue state coordinates change discontinuously.

### 6.2 Multiplex wallet/social graph

For relation layer `r`, define adjacency `A_t^r` only over compatible node types. Cross-layer
couplings are typed compositions, for example:

```text
stable social account
  --attributed profile wallet--> wallet
  --signed trade as user-------> mint
  --member-of candidate-------> territory
```

The composition is no stronger than its weakest edge and cutoff. A graph embedding that discards
layer, evidence grade, or bitemporal validity may be useful for retrieval but cannot serve as an
identity resolver.

### 6.3 Endogenous boundaries

Domains change because:

- a coin launches or migrates;
- a pool/bin activates or disappears;
- a route becomes available or unavailable;
- a social account, post, or community appears/deletes;
- the product changes ranking/filtering;
- Ember opens/closes a hot scope; or
- an episode expands to a family or competing opportunity.

Every aggregate over a changing domain must separate movement of existing mass from entry/exit of
domain elements. Otherwise a board refresh looks like attention transport and a migration looks
like a price shock.

## 7. Price is a family of typed functionals

### 7.1 Transaction and accounting prices

- `p_fill`: exact ratio of landed asset effects for one economic fill, with fees represented
  separately or under a declared convention;
- `p_basis`: accounting projection from lots and exact costs;
- `p_reference`: external price observation with source, pair, and time; and
- `p_mark`: contextual display/statistical point with no capacity claim.

### 7.2 AMM marginal and size prices

Given exact venue state `z`, action direction `d`, and base size `q`, an exact quote operator gives:

```math
Q_v(z,d,q)=(\text{input atoms},\text{output atoms},\text{fees},\text{refusal}).
```

The average executable price is a secant ratio for that exact size. A marginal price is a local
derivative or finite-difference property of the frozen quote map and can fail to exist under integer
rounding, fee discontinuities, bin boundaries, or refusal. It never establishes fillability after
landing delay.

### 7.3 Price as a dual field

Where a venue state defines a convex or locally smooth feasible trading set `C(z)`, a marginal
price can be represented as a supporting covector or subgradient normal to `C(z)`. This gives a
precise, limited sense in which price is a **dual variable**: it converts an infinitesimal asset
perturbation into a local quote-asset cost.

Limits:

- the exact on-chain map is discrete and rounded;
- fees make buy and sell duals direction-dependent;
- route choice yields several feasible sets;
- the relevant size may not be infinitesimal; and
- the market-wide social value of a memecoin is not the AMM's dual variable.

### 7.4 Price as clearing field

In a LOB or latent-liquidity model, a clearing price can be a zero/crossing of signed supply-demand
density. In an AMM, the program deterministically quotes against deployed inventory; it does not
discover the zero of all latent intentions. External arbitrage may couple venues toward a common
band, but that is an empirical network process with latency, fees, and capacity.

Therefore `price_as_clearing_field` is admissible only when the study names:

1. the supply/demand objects;
2. whether they are visible or latent;
3. the clearing institution;
4. the quote asset/numeraire;
5. the size scale; and
6. the observation/counterfactual assumptions.

## 8. State-completeness levels

Every field artifact should state the strongest available closure:

| level | closure |
| --- | --- |
| `event_only` | event decoded, pre/post venue state unavailable |
| `single_state` | one venue account snapshot, related accounts possibly asynchronous |
| `coherent_state` | required accounts observed under a defensible slot/context closure |
| `quote_complete` | coherent state plus fees/token rules/route needed for exact quote |
| `settlement_complete` | finalized landed effects reconcile at declared boundary |
| `scene_complete` | as-known source/quote/portfolio/viewport manifest available |
| `episode_complete` | scene/action/fill/management/exposure path closes through horizon |

A high-level statistical model may consume lower closure, but it must retain the deficit. No
imputation changes the closure label.

## 9. Minimal validity invariants

1. Every quantity is keyed by domain, unit, clock, source/cutoff, and authority rung.
2. Absent venue coordinates are never encoded as observed zero.
3. Atomic asset identity does not depend on display symbol or decimal formatting.
4. Settlement, attribution, and valuation remain separate projections.
5. Graph relation layers are never pooled without a declared composition map.
6. Lifecycle/migration changes state topology and is not silently differenced as an ordinary
   return.
7. A field over an adaptively observed hot scope does not claim whole-market coverage.
8. A marginal price does not stand in for an exact-size quote, fill, or liquidation.
9. A latent object is stored as a versioned assertion/derivation, never as source truth.
10. Operator state and product surfacing remain inside the composite-process model.

