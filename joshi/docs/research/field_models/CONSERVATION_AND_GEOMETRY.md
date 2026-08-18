# Conservation, exact transitions, and venue geometry

## 1. Conservation is boundary-relative

The strongest theorem available to JOSHI is not about price. It is commodity accounting after a
boundary and event closure are declared.

For asset `a`, account set `B`, and canonical chain boundary `k`, define atomic mass

```math
M_a^B(k):=\sum_{u\in B} b_{u,a}(k).
```

For interval `(k_0,k_1]`, classify every reconciled posting by whether it crosses `B`, stays inside
`B`, mints/burns `a`, converts custody representation under a declared conversion, or remains
unresolved. Then

```math
M_a^B(k_1)-M_a^B(k_0)
=\Phi_{a,in}^B-\Phi_{a,out}^B+\Gamma_{a,mint}^B-\Gamma_{a,burn}^B
 +\Gamma_{a,convert}^B+\varepsilon_a^B.
```

All terms are signed integers in atoms of `a`. Internal transfers cancel when both endpoints are
inside `B`. `epsilon` is not statistical noise: it is a typed reconciliation defect until resolved.

### 1.1 What this theorem says

- exact token quantity can be conserved and reconciled;
- fees are transfers to named accounts when those effects are observed;
- LP adds/removes move custody and transform contingent inventory but do not create PnL by label;
- partial exits and re-entry remain exact flows across inventory epochs; and
- an external manual trade can be joined from landed effects even if intent is absent.

### 1.2 What it does not say

- economic value is conserved;
- SOL-equivalent wealth is invariant;
- a mark represents liquidation;
- an LP position retains its initial token composition;
- a social audience, community, or attention mass is conserved; or
- a counterfactual action shares the actual future.

## 2. Transaction-local settlement theorem

Let `Delta_e(u,a)` be the exact reconciled balance change caused by landed economic event `e` at
account `u`. For a closed account set containing every affected holder of `a`:

```math
\sum_u \Delta_e(u,a)=m_e(a)-d_e(a),
```

where `m_e` and `d_e` are exact mint and burn effects. If the set omits fee vaults, reward vaults,
rent recipients, wrapped-native accounts, or inner instructions, the residual measures the missing
boundary; it is not evidence that conservation failed.

For a declared portfolio boundary, one should expect nonzero external flux. For a protocol
boundary, one should expect swap, fee, LP, and migration flows across sub-boundaries. The useful
property is that the decomposition closes at the chosen scope.

### Falsifier/gate C0

Given retained pre/post balances and decoded effects, any unexplained residual above exact known
rounding/withheld-token semantics rejects the reconstruction. Strategy studies stop at this gate;
the residue is a forensic fixture, not a PnL observation.

## 3. Event transition algebra

The native market is a jump system. Let `z_{e-}` be the exact relevant state closure before event
`e`, and let `F_profile` be the profile-bound transition:

```math
z_{e+}=F_{profile}(z_{e-},m_e),
```

where `m_e` is a typed mark containing action kind, exact atoms, accounts, fees, bounds, and other
instruction inputs. `F` may refuse. It can contain integer floors/ceilings, fixed-width overflow,
bin loops, account constraints, and conditional branches.

Continuous-time notation is derived later by aggregation. It may not replace this transition in:

- quote calculation;
- ledger reconciliation;
- protocol conformance;
- transaction simulation;
- LP entitlement; or
- any study whose economic hurdle is comparable to atomic rounding or fees.

## 4. Valid-state sets versus conserved invariants

The phrase **AMM invariant manifold** is easy to abuse. Separate two objects.

### 4.1 Valid-state set

For venue/profile `v`, define

```math
\mathcal M_v:=\{z:\operatorname{Validate}_v(z)=\mathrm{ok}\}.
```

Validation can include account owner/version, nonnegative or bounded reserves, consistent assets,
ordered bins, position share bounds, lifecycle, fee configuration, and fixed-width arithmetic.
This set is an exact typed state domain if the profile is correct. It need not be smooth, connected,
or a manifold in the differential-geometric sense.

### 4.2 First integral or pricing invariant

A function `I_v(z)` is conserved only for a declared action class `A_0` when

```math
I_v(F_v(z,a))=I_v(z)\quad\text{for every valid }(z,a)\in\mathcal M_v\times A_0.
```

Fees, integer rounding, LP changes, oracle/volatility updates, token extensions, migration, and
program upgrades can make a familiar idealized invariant drift or cease to apply. An equation used
to compute a quote is not automatically a conserved quantity of the extended landed state.

Use `valid-state set`, `quote surface`, or `transition graph` unless an actual first integral has
been proved against the deployed profile.

## 5. Pump bonding-curve geometry

### 5.1 Exact state coordinates

A minimally closed curve state includes:

```text
(virtual_base, virtual_quote, real_base, real_quote,
 mint_supply, completion/migration, fee profile, creator applicability,
 mode flags, asset/token-program state, observation closure)
```

All reserve and trade values are atomic integers. The exact-base-out buy pricing core currently
profiled by JOSHI has the shape

```math
r_y=\left\lfloor\frac{q_x v_y}{v_x-q_x}\right\rfloor+1,
```

before separately rounded applicable fees. Exact-base-in sell has

```math
r_y=\left\lfloor\frac{q_x v_y}{v_x+q_x}\right\rfloor
```

before fee subtraction. These formulas describe a profile-bound quote map, not a timeless Pump law.
Real-reserve capacity, virtual-reserve validity, fee tier, mode, and completion can refuse a quote.

### 5.2 Geometry

At fixed profile and state, the quote surface is a directed map over allowable size:

```math
q_x\mapsto Q_{pump}^{buy}(z,q_x),\qquad
q_x\mapsto Q_{pump}^{sell}(z,q_x).
```

Buy and sell surfaces differ because of direction, fees, capacity, and integer rounding. A smooth
hyperbola is an approximation to the virtual-reserve core only. The deployed transition lives on a
lattice with boundaries:

- `q=0`;
- real-base exhaustion;
- virtual denominator failure;
- real-quote payout failure;
- fee-tier boundary;
- curve completion; and
- migration.

### 5.3 Exact and approximate claims

| claim | status |
| --- | --- |
| a quote is reproducible from a complete named profile/state closure | H1, conformance required |
| virtual reserves define a concave directed size-cost relation on an admissible interval | profile-specific mathematical result |
| one continuous `x*y=k` surface captures landed state including fees/migration | false unless independently proved for a restricted state/action |
| post-trade price response is determined by the curve formula | false; later flow, arbitrage, LP/routes, attention, and MEV intervene |

### Falsifier/gate C1

Golden vectors, read-only simulation, or finalized transitions that disagree at one atom reject the
profile or observation closure. Fitting a smooth curve to displayed marks cannot repair the defect.

## 6. PumpSwap geometry

### 6.1 Extended reserve state

Let `x` be raw base-vault atoms and `y_raw` raw quote-vault atoms. The current profile uses a signed
virtual quote component `y_virtual`, producing an effective pricing reserve

```math
y_{eff}=y_{raw}+y_{virtual}.
```

The effective reserve participates in quote formation; raw vault inventory constrains real payout.
Conflating the two can manufacture liquidity.

For exact base output `q_x`, the core raw quote input has constant-product form

```math
r_y=\left\lceil\frac{y_{eff}q_x}{x-q_x}\right\rceil,
```

with separately rounded LP/protocol/creator fee components. For exact base input on a sell,

```math
r_y=\left\lfloor\frac{y_{eff}q_x}{x+q_x}\right\rfloor,
```

followed by fee and real-payout checks.

### 6.2 Extended-state warning

The ideal fee-free reserve pair suggests level sets of `x*y_eff`. The executed program state also
contains:

- raw versus virtual reserves;
- LP-retained versus transferred fees;
- protocol/creator accounts;
- dynamic fee tier/configuration;
- mint supply and token-program effects;
- transaction failure and competing state; and
- canonical/noncanonical pool rules.

Therefore JOSHI should record the exact transition and a diagnostic invariant residual separately.
It should not enforce constant `k` over the extended state unless a profile-specific proof says so.

### Falsifier/gate C2

The state/quote profile fails if it cannot reproduce official comparator output, read-only
simulation, and finalized asset effects across fee, virtual-reserve, capacity, and boundary cases.
The useful residue is an exact disagreement corpus.

## 7. Meteora DLMM discrete geometry

### 7.1 Price lattice

Let bins be indexed by `j in Z`, with profile-bound bin step `s`. The ideal whole-number relation is

```math
p_j\propto(1+s/10{,}000)^j,
```

while the actual implementation uses fixed-width Q64.64 exponentiation, checked multiplication,
rounding, reciprocal behavior, and refusal near representational boundaries. The exact `p_j` is a
typed fixed-point object, not a binary float.

The native geometry is a graph/lattice:

```text
... <-> j-1 <-> j <-> j+1 <-> ...
                    ^
                 active bin
```

Initialized-bin bitmap/arrays, account limits, activation, and transaction constraints can remove
otherwise adjacent executable transitions.

### 7.2 Per-bin state and LP measure

For bin `j`, retain exact:

```text
(x_j, y_j, liquidity_supply_j, fee/reward growth, initialization, price_j)
```

For position `i`, retain share `s_{i,j}` and checkpoints. Principal entitlement is profile-bound:

```math
x_{i,j}=\left\lfloor\frac{s_{i,j}x_j}{L_j}\right\rfloor,\qquad
y_{i,j}=\left\lfloor\frac{s_{i,j}y_j}{L_j}\right\rfloor,
```

when `L_j>0`, with invalid share/supply states rejected.

An exact discrete inventory measure for the position is

```math
\mu_i^{LP}=\sum_j\left(x_{i,j}\,\delta_{(j,X)}+y_{i,j}\,\delta_{(j,Y)}\right).
```

This measure is commodity-valued. It is not one quote-value density. Fees and rewards remain
separate measures by asset and evidence quality.

### 7.3 Swap traversal

A swap visits an ordered sequence of bins, applying profile-bound per-bin amount, fee, and rounding
operators until requested size is satisfied or capacity/refusal is reached. The transition is a
finite path on the lattice, not a differential displacement.

Consequences:

- active-bin movement is a discrete boundary crossing;
- an LP range is a contingent conversion schedule;
- add/remove/rebalance are different state operators;
- in-place reweighting is not assumed to be exposed by a UI or deployed instruction;
- a close/reopen changes position identity; and
- withdrawal inventory is not liquidation value.

### 7.4 Continuum limit, if ever used

A density `rho(p)` may approximate bin state only after declaring:

1. the price coordinate and reference measure (`dj`, `dp`, or `d log p`);
2. how atomic `x_j,y_j` become a common commodity/value;
3. the bin-step asymptotic;
4. boundary and active-bin treatment;
5. rounding/fee error relative to the estimand; and
6. a convergence comparison to exact traversal.

If a policy decision changes when exact bins replace the density, the continuum model is outside
support.

### Falsifier/gate C3

Per-bin entitlements must sum without exceeding pool assets; active/inactive composition and
withdrawal projections must match profile comparators/simulation/finalized effects. A smoothed
liquidity curve that passes visual inspection but fails a one-bin boundary is rejected for action.

## 8. LOB geometry remains another stratum

For a genuine LOB, price levels and bid/ask queues define a two-sided discrete book with matching
priority. Queue imbalance, depletion, and spread are valid there. They are not universal
coordinates injected into AMM state. A cross-venue field should use an interface such as exact-size
directional quote/capacity, then preserve each venue's native state beneath it.

The Bouchaud queue, Hawkes, response, propagator, and latent-liquidity models remain source-specific
baselines; see
[`TRANSFER_LIMITS.md`](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md).

## 9. Launch and migration topology maps

### 9.1 Lifecycle graph

Represent a coin's trade topology as a temporal directed multigraph:

```text
mint/launch
  -> Pump curve state
  -> completion candidate
  -> migration transaction/effects
  -> one or more pool/route assertions
  -> route/pool activation, loss, replacement, or coexistence
```

Each arrow has:

- source-native evidence and full locator;
- valid and observed intervals;
- asset map;
- custody/state map;
- price-coordinate map, if meaningful;
- confidence/canonicality;
- coverage/missingness; and
- whether the map is exact, inferred, many-to-one, or one-to-many.

### 9.2 Pushforward and discontinuity

If topology edge `g:v->v'` has an asset/state map, one can define a pushforward `g_# mu` of the
subset whose identity is preserved. The residual is explicit:

```math
\Delta_{migration}=\mu_{after}-g_\#\mu_{before}.
```

This residual may contain fees, unobserved accounts, initialization, supply changes, custody
rearrangement, or an incorrect association. It should not be called price impact.

Price series may need a splice artifact containing both old/new venue price objects and exact-size
quotes. A single adjusted candle conceals the topology change.

### Falsifier/gate C4

A migration map is not admitted as canonical when asset conservation fails, route association is
ambiguous, or the map uses a later-discovered pool in an earlier knowledge-cutoff view. Preserve
the competing topology assertions.

## 10. Source, sink, and reaction taxonomy

Terms are boundary-relative bookkeeping labels:

| domain | transport/flux | source | sink | reaction/conversion |
| --- | --- | --- | --- | --- |
| asset ledger | transfer across declared accounts | mint or external inflow | burn or external outflow | swap/wrap/LP custody transformation, with every asset leg explicit |
| venue inventory | user/LP/fee movement across venue boundary | LP add or migration in | LP remove, payout, migration out | protocol exchange of asset composition |
| DLMM bin lattice | swap traversal and LP redistribution | add into bin | remove from bin | active-bin conversion/fee accrual |
| market event tape | events entering observation interval | launch/new object/coverage open | terminal/coverage close | event-type transition; not conserved |
| attention funnel | candidates or interaction occupancy entering a stage | board/render/hot-scope exposure | viewport exit/dismiss/expiry | view -> inspect -> arm, with duplication possible |
| social graph | posts/participants/relations appearing on nodes/edges | new account/post/arrival assertion | deletion/departure/coverage end | mention/reply/follow/participation transition |
| episode process | subject/intent enters active attention | episode open/reopen | explicit resolve/expiry policy | stance/act/inventory-epoch transition |

Only the first rows can support commodity conservation, and only with correct boundaries. In
attention/social domains, source/sink language does not imply that one person's attention left one
coin to enter another. Directed movement requires identity-preserving temporal evidence.

## 11. Geometry verification matrix

| object | exact test | descriptive test | stop condition |
| --- | --- | --- | --- |
| portfolio/venue asset boundary | atomic balance closure | residual rate by event/profile/source | unexplained residual comparable to action size |
| Pump quote surface | integer goldens/simulation/fills | quote–fill error by state/latency | error consumes micro-profit hurdle |
| PumpSwap extended state | raw/effective reserve and fee conformance | route/landing residual | payout capacity or fee semantics unresolved |
| DLMM position measure | share/entitlement/withdrawal conformance | exact-bin versus smoothed error | missing bins/accruals change economic conclusion |
| migration map | asset/custody/topology reconciliation | splice/route continuity | later knowledge or ambiguous pool is required |
| graph topology | typed-edge evidence and bitemporal join checks | stability under edge-layer ablation | generic graph relation drives conclusion |

