# Lane 06 — Routed-liquidity dynamics and causality

Status: research formalization; no implementation, liquidity deployment, trading, or authority.

## Executive finding

Installing shaped liquidity on an external venue **can mechanically change the set of available
quotes**. It can alter realized Pump/PumpSwap dynamics only through additional mechanisms:

1. order routers send or split flow through the external venue;
2. arbitrage transfers price/state changes between venues;
3. LP inventory absorbs one side of flow until its active capacity changes or exhausts;
4. pool creation/liquidity itself changes attention or actor behavior; or
5. the intervention changes MEV, failure, latency, or liquidity-provider adaptation.

The sign is not known in advance. External liquidity may attenuate exact-size aggregate quote
movement, leave the canonical Pump chart unchanged, divert canonical prints while merely moving the
same aggregate price, import a shock from another venue, create route-switch discontinuities, or
transfer losses from takers to the LP. Greater displayed depth is not a stabilization theorem.

The admissible claim is therefore a vector:

```text
treatment: exact external venue/pool/position/bin state and timing
mechanism: direct route | split route | arbitrage | attention | adaptation | MEV
direction: buy token | sell token
size: exact atomic trade or liquidation size
route: canonical | external | split | best attainable | observed landed
outcome: canonical print | venue quote | aggregate quote | fill | capacity |
         route share | inventory transformation | volatility/tails | LP economics
horizon: instantaneous frozen state | landing | seconds/minutes | lifecycle
```

No scalar `pressure`, `resistance`, or `stability` variable is canonical. When those words appear
below they are locally defined measurements, following the anti-cargo-cult rules in
[`ANALOGY_REDTEAM.md`](../field_models/ANALOGY_REDTEAM.md).

### Boundary with the adjacent routed-liquidity lanes

- [`02_VENUE_ROUTABILITY.md`](02_VENUE_ROUTABILITY.md) decides which venue primitive can express a
  shaped edge and what current indexing/account/fee constraints can make it routable.
- [`03_GHOST_EDGE_EXPERIMENT.md`](03_GHOST_EDGE_EXPERIMENT.md) estimates fixed-demand mechanical
  activation for an undeployed edge. Its output can support `M0` below but is explicitly not a
  causal market path.
- [`05_GLASS_OPERATOR.md`](05_GLASS_OPERATOR.md) defines how exact route, bin, fee, inventory,
  markout, and ghost evidence can be shown without becoming a scalar edge score or action control.

This lane begins where those mechanical/product questions stop: whether a real or naturally
occurring installed edge changed other venues, aggregate execution, actors, and who bore the risk.

## 1. The exact causal claim

Let `Z_t` denote an installed external-liquidity intervention for one exact mint/quote-asset market.
It includes:

```text
external venue and deployed program/profile
pool and position identities
asset pair and token programs
creation/activation/add/remove transaction locators
per-bin or reserve state, active range, and directionality
fees, volatility state, rewards, and route eligibility
LP owner/portfolio boundary where known
knowledge and availability time to routers and traders
planned versus actual changes and intervention horizon
```

The strongest claim under study is:

> Relative to the market path under a declared no-installation or alternate-shape condition,
> `Z_t` changes subsequent canonical and/or aggregate price/quote dynamics through routing,
> arbitrage, inventory absorption, or behavioral response.

This contains several separable claims:

| ID | claim | epistemic status before a study |
| --- | --- | --- |
| `M0` | Adding the pool/position changes frozen exact-size quote possibilities. | Mechanical H1/H2 question; often calculable if all venue/router state is known. |
| `M1` | Routers or users actually direct flow through it. | Descriptive landed-flow question. |
| `M2` | Canonical Pump/PumpSwap flow/state changes because flow was diverted or arbitrage linked venues. | Causal network-interference question. |
| `M3` | Canonical or aggregate executable-price variation/tails decrease. | Causal outcome claim with price-object choice. |
| `M4` | Deviations restore toward a reference more quickly. | Conditional response claim; the reference and shock origin must be identified. |
| `M5` | The market is economically safer or better. | Normative/distributional claim requiring taker, holder, and LP outcomes. |
| `M6` | The LP benefits while stabilizing the market. | Joint policy/PnL claim; neither follows from depth or M3. |

Evidence for `M0` does not establish `M1–M6`. Lower canonical print variance does not establish M3
if trades were diverted and aggregate executable quotes remain equally volatile. Positive fees do
not establish M6 if the LP acquired the depreciating token or sold the appreciating one.

## 2. Market, route, and price objects

### 2.1 Venue set

For one exact pair, let:

```text
v_c       canonical Pump curve or canonical PumpSwap pool
v_e       external pool, e.g. one Meteora DLMM pool
V_t       all prospectively known eligible venues at t
R_t(q,d)  prospectively available route plans for size q and direction d
```

Canonicality is a protocol/source assertion, not “the venue with most volume.” `V_t` and `R_t`
are point-in-time sets. A pool discovered later cannot enter an earlier route counterfactual.

### 2.2 Direction

Use trader direction relative to the focal token `X` and quote asset `Y`:

- `d=+`: acquire `X`, pay `Y`;
- `d=-`: sell `X`, receive `Y`.

LP direction is the opposite inventory transformation. If traders buy `X` from an external pool,
that pool/its LPs lose `X` and acquire `Y` plus fees. Never call the same event “buy pressure” in
both perspectives.

### 2.3 Exact venue and route quote functions

A size is a typed object:

```text
(size_asset, exact_input | exact_output, atoms)
```

Exact-input and exact-output routes are separate operators. Some venue/router profiles support one
and not the other. Never invert or interpolate an unsupported operator merely to fill a surface.
Every study should include Ember-relevant exact-input sizes and, where all compared routes support
it, a common base-token grid.

For state closure `z_{v,t}`, direction `d`, and exact base-token size `q`, define:

```math
C_{v,t}^{+}(q)=\text{total Y atoms required to receive q X atoms},
```

```math
C_{v,t}^{-}(q)=\text{net Y atoms received for selling q X atoms}.
```

Each result binds fees, refusal, state/profile, token rules, and observation clock. For route plan
`r`, define `C_{r,t}^d(q)` from the actual router quote artifact or a profile-complete independent
calculation. A split route is an explicit allocation and ordered instruction plan, not the minimum
of venue marks.

The displayed `C^+` surface uses exact X output and `C^-` uses exact X input. A route without the
required exact-output support is a typed refusal on the common base grid. Complementary exact-input
buy and exact-output sell surfaces should be reported under their own size semantics; their values
cannot be mixed into these equations.

For the frozen aggregate envelope:

```math
C_{A,t}^{+}(q)=\min_{r\in R_t(q,+)} C_{r,t}^{+}(q),
```

```math
C_{A,t}^{-}(q)=\max_{r\in R_t(q,-)} C_{r,t}^{-}(q).
```

This ideal envelope is useful only if all route costs, account constraints, state overlap,
transaction feasibility, and route expiry are represented. The router's returned quote and route
plan remain the operational observation. A mathematical allocation over independently quoted pools
can be infeasible when legs share state or transaction/account limits.

### 2.4 Canonical Pump chart prints

Define a canonical print as the exact price projection of one landed trade attributed to `v_c`
under the chart's declared convention:

```math
P^{print,c}_i
=\operatorname{PriceConvention}(\text{canonical venue trade }i).
```

Possible conventions—gross consideration, net user effects, reserve ratio, event-reported price,
or chart-derived candle—are not interchangeable. A routed Jupiter transaction with a PumpSwap leg
can create a canonical PumpSwap print even if only part of the user's swap executed there.

The canonical chart is a projection of canonical venue events. It can change because:

- canonical reserve state changes;
- the number/composition of trades reaching the venue changes;
- split-route leg sizes change;
- arbitrage trades arrive; or
- the chart's event inclusion/convention changes.

It does not directly display external-pool trades, aggregate routing capacity, or whole-position
liquidation.

### 2.5 Aggregate price and quote objects

Keep separate:

| object | definition | principal use |
| --- | --- | --- |
| canonical transaction print | one `v_c` landed trade under declared chart convention | reproduce/interpret Pump chart |
| canonical marginal mark | reserve/state local price at `v_c` | native state context, no capacity claim |
| external bin/marginal mark | active-bin/local price at `v_e` | external state context |
| canonical exact-size quote | `C_{v_c,t}^d(q)` | venue-specific executable geometry |
| external exact-size quote | `C_{v_e,t}^d(q)` | shaped-liquidity geometry |
| aggregate route quote | `C_{A,t}^d(q)` or actual router quote | attainable cross-venue cost at exact size/cutoff |
| landed user fill | reconciled user asset effects for the whole route | execution/accounting truth |
| consolidated trade statistic | declared volume/venue-weighted statistic over covered prints | descriptive market statistic |
| full liquidation | best supported sell route for the exact holding | exposure, not mark |

There is no singular aggregate price independent of size, route universe, fees, clock, and
aggregation convention.

## 3. Operational meanings for the proposed dynamics vocabulary

### 3.1 Adverse quote displacement

Choose a declared reference price `p_ref,t` in `Y atoms/X atom`. For buy and sell directions define
nonnegative finite-size displacement:

```math
\delta_{r,t}^{+}(q)
=\log\left(\frac{C_{r,t}^{+}(q)/q}{p_{ref,t}}\right),
```

```math
\delta_{r,t}^{-}(q)
=\log\left(\frac{p_{ref,t}}{C_{r,t}^{-}(q)/q}\right).
```

Fees can make displacement positive at tiny size; a stale or external reference can make it
negative. Preserve the raw quote and reference rather than coercing the sign. A reference may be
the route's marginal price, canonical pre-event state, or a cross-venue mark, but conclusions must
be tested across reasonable choices.

### 3.2 Conductance

Directional route conductance is a finite-difference capacity response, not a scalar property of a
coin:

```math
G_{r,t}^{d}([q_1,q_2])
=\frac{q_2-q_1}
       {\delta_{r,t}^{d}(q_2)-\delta_{r,t}^{d}(q_1)}.
```

Units are X atoms per unit log displacement. It is defined only when the denominator is positive
and both quotes exist. Report the interval, direction, route, reference, state, and fees. Near route
switches, bin boundaries, fixed-fee regions, or refusal, conductance can be discontinuous or
undefined.

A more robust companion is capacity within displacement budget `eta`:

```math
K_{r,t}^{d}(\eta)
=\sup\{q:C_{r,t}^{d}(q)\text{ exists and }\delta_{r,t}^{d}(q)\le\eta\}.
```

This is measured in X atoms and is often easier to communicate than `G`.

### 3.3 Resistance

Directional route resistance is the reciprocal finite-difference slope:

```math
R_{r,t}^{d}([q_1,q_2])
=\frac{\delta_{r,t}^{d}(q_2)-\delta_{r,t}^{d}(q_1)}{q_2-q_1}.
```

Units are log displacement per X atom. It is not “market reluctance,” social resistance, or an LP
profit measure. A high value can reflect shallow inventory, fees, route constraints, stale state,
or a bin/refusal boundary.

### 3.4 Obstruction

Use two distinct objects.

**Frozen quote obstruction/dampening** for treatment `Z` versus comparison `0`:

```math
O_{quote}^{d}(q,\eta)
=\delta_{A,0}^{d}(q)-\delta_{A,Z}^{d}(q),
```

or equivalently the change in `K_A^d(eta)`. Positive `O_quote` means the installed state offers a
less adverse frozen aggregate quote for that direction and size. “Obstruction to price movement”
is a poor label here; the LP is facilitating the trade while increasing the size needed to move
the aggregate quote.

**Realized canonical-flow diversion** over interval `H`:

```math
D_c^d(H)=1-
\frac{\text{focal signed X atoms landed at }v_c}
     {\text{focal signed X atoms landed across eligible venues}},
```

with split legs and actor/arbitrage classification retained. This describes observed allocation,
not the causal change relative to no external pool.

Do not merge quote capacity and realized diversion into one obstruction score.

### 3.5 Absorption

External liquidity **absorbs** flow only in the inventory-accounting sense. Over interval `H`,

```math
A_{e}^{X}(H)=-\Delta X_{external\ pool,swaps}(H),
```

signed from the trader-demand perspective, with LP adds/removes, fees, transfers, and migration
excluded or shown separately. A buy wave yields positive trader acquisition and negative pool X;
a sell wave yields pool acquisition of X.

An absorption share can be reported:

```math
a_e^d(H)=
\frac{|\text{direction-d X atoms executed at }v_e|}
     {|\text{direction-d X atoms across eligible venues}|}.
```

This says where flow executed. It does not say the market stabilized, the LP profited, or the
counterfactual canonical venue would have received the same orders.

### 3.6 Bin exhaustion

For a DLMM route and direction, bin exhaustion is an exact discrete event/state transition:

- the direction-relevant executable asset in bin `j` is depleted to the profile's boundary;
- the swap traversal crosses to another initialized bin;
- the next required bin/account is absent or outside transaction constraints; or
- the intended-size quote refuses because traversable direction-specific inventory ends.

Report:

```text
pre/post active bin and arrays
visited bins and exact asset changes
direction and size
fees/volatility state
remaining capacity surface
route continuation/refusal
LP add/remove in the same interval
```

Low TVL, leaving an LP's chosen range, and exhausting market-wide external capacity are different.

### 3.7 Stabilization

Stabilization is a predeclared outcome vector, never “the chart looks smoother”:

```text
canonical print variation/jump tails
canonical exact-size quote variation
aggregate exact-size quote variation
mark-to-liquidation gap
route availability/refusal duration
state/quote recovery after shocks
canonical versus external flow concentration
total transaction failure/latency/MEV cost
holder/taker/LP economic outcomes
```

An intervention can stabilize one component and destabilize another. A narrow claim should be
worded, for example:

> For token-buy size `q`, the installed external shape reduced the 99th percentile of one-minute
> aggregate quote displacement under route universe `R` during the scoped post-intervention regime,
> without improving canonical-only print variance.

### 3.8 Restoring response

For shock event `s` at `t_0`, outcome `Y` (preferably an exact-size quote/log quote), and pre-shock
reference `Y_{0-}`, define signed observed recovery:

```math
\operatorname{Restore}_Y(\tau)
=-\operatorname{sgn}(Y_{0+}-Y_{0-})
  \{Y_{t_0+\tau}-Y_{0+}\}.
```

Positive values move back toward the pre-shock reference. Also report overshoot, time within a
tolerance band, quote availability, and subsequent flow. This is an observed response. It does not
prove the external LP caused restoration; arbitrage, opposite flow, attention decay, or common
market movement can do so.

### 3.9 Imported shock

An imported-shock candidate requires:

1. a state/price/flow change first evidenced on an external venue or reference market;
2. later or same-atomic-sequence arbitrage/routing into `v_c`;
3. exact chain ordering and route/account evidence;
4. no earlier canonical/common-source event under healthy coverage; and
5. a matched baseline for ordinary cross-venue lead–lag.

Define the candidate transmission response of canonical quote `Y_c` to external shock mark `m_e`:

```math
R_{c\leftarrow e}^{obs}(\tau,q)
=E[m_e\{Y_c(t+\tau,q)-Y_c(t^-,q)\}\mid X_{t^-},\text{coverage}].
```

It remains observed association. A global SOL move, platform callout, or provider latency can make
the apparent external origin false.

## 4. Mechanism map

```text
external pool/shape Z
   |
   +--> frozen route set and exact quote surfaces ----------------------+
   |                                                                  |
   +--> router/Jupiter eligibility, ranking, split plan                |
   |       -> user flow diverted/split -> canonical/external state ----+
   |                                                                  |
   +--> cross-venue price discrepancy -> arbitrage --------------------+
   |                                                                  |
   +--> LP inventory/fees -> add/remove/recenter response -------------+
   |                                                                  |
   +--> public pool/liquidity signal -> attention/actor adaptation ----+
   |                                                                  v
   +--> transaction account graph -> MEV/failure/landing --------> observed
                                                                      prices,
market regime, lifecycle, SOL, ranking, social events, other venues -> quotes,
                                                                      flow,
                                                                      LP PnL
```

The treatment is not one arrow. Pool creation, initial shape, later LP edits, router discovery, and
route use can occur at different times. Treat them as separate events and intermediate variables.

## 5. Why routing makes the treatment endogenous

### 5.1 Jupiter rerouting and splitting

An aggregator can respond to external liquidity by:

- including/excluding the pool from its route universe;
- changing which venue wins at each size/direction;
- splitting one user order across venues;
- changing route when accounts, fees, state, or transaction limits change;
- preferring a route for expected output that lands differently under contention; and
- updating solver/version behavior during the study.

Thus external liquidity has no route effect until it is discoverable and eligible under the actual
router configuration. A route returned for `q_1` says nothing about `q_2` or the opposite direction.
The route plan itself is post-treatment and cannot be naively controlled away when estimating the
total effect.

Required router observations include quote request, exact size/direction, input account/asset,
context slot, returned legs/allocations, expected and minimum output, fees, solver/API version,
request/receive latency, expiry, transaction constraints, and landed leg reconciliation.

### 5.2 Arbitrage transmission

If venues diverge beyond executable costs, arbitrage can:

- move the canonical state toward the external venue;
- move the external state toward canonical;
- route through both in one atomic transaction;
- import a shock from another venue/reference;
- create extra canonical prints and volume; or
- stop at inventory, fee, latency, or MEV boundaries.

Arbitrage can damp aggregate cross-venue discrepancy while increasing each venue's print count and
short-horizon variance. Classify direct user flow and candidate arbitrage separately when evidence
supports it; retain ambiguous bundles rather than assigning intent from a round trip alone.

### 5.3 Actor and LP adaptation

After observing the installed shape, actors can change size, timing, venue, sandwich/backrun,
liquidity, or social behavior. The LP can remove/recenter precisely when volatility rises. These
responses are part of the treatment's equilibrium effect, not nuisance if the claim is “changes
market dynamics.” They invalidate a fixed material-law interpretation.

### 5.4 MEV and landing

More routable liquidity can change account sets, transaction size, expected arbitrage, priority
fees, and adversarial interest. Same-slot order can determine which venue absorbs flow and which LP
is selected. A quote improvement that raises failed/sandwiched realized cost is not execution
stabilization.

## 6. Causal estimands

Let `Y_{c,t}^d(q;Z)` be a canonical outcome and `Y_{A,t}^d(q;Z)` an aggregate outcome under
intervention history `Z`. Potential outcomes are network-valued: treatment of one pool affects
routes, arbitrage, actors, and possibly related mints. Ordinary no-interference assumptions fail.

### 6.1 Frozen mechanical quote effect

```math
\tau_{mech}^d(q)
=\delta_{A}^{d}(q;z_c,z_e=Z)-\delta_{A}^{d}(q;z_c,z_e=\varnothing),
```

holding canonical state, route solver/version, and all other venue states fixed.

This is identifiable by exact calculation only if the hypothetical external state is fully
specified and router feasibility can be reproduced. It answers M0, not market adaptation.

### 6.2 Route-allocation effect

For a fixed incoming set of order requests `U` and router policy `rho`:

```math
\tau_{route}(Z;U,\rho)
=\text{canonical/external leg allocation with Z}
-\text{allocation without Z}.
```

Replaying historical requests is pathwise and assumes request set `U` would not change. It is not
the total effect because lower cost may create or resize orders and later states diverge.

### 6.3 Canonical dynamic effect

```math
\tau_c^d(q,h)
=E[Y_{c,t+h}^d(q;Z)-Y_{c,t+h}^d(q;0)]
```

for canonical prints, state, or exact-size quotes. The outcome, horizon, and treatment onset must be
fixed prospectively. This estimand permits canonical dynamics to change through routing/arbitrage.

### 6.4 Aggregate dynamic effect

```math
\tau_A^d(q,h)
=E[Y_{A,t+h}^d(q;Z)-Y_{A,t+h}^d(q;0)].
```

This is the central dampening claim. It is size- and route-universe-specific and harder than the
canonical effect because route availability and solver behavior are treatment-dependent.

### 6.5 Shock-response effect

For prospectively classified shock family `s`:

```math
\tau_{restore}^d(q,\tau)
=E[\operatorname{Restore}_{Y_A}(\tau;Z)
   -\operatorname{Restore}_{Y_A}(\tau;0)\mid s,X_{pre}].
```

The shock must not be defined by the subsequent recovery. Separate canonical-origin, external-origin,
social/platform, SOL-wide, migration, and liquidity-removal shocks.

### 6.6 Distributional economic effect

Report separately:

```text
taker execution cost/failure/latency
canonical and external LP fees
external LP inventory conversion and full liquidation
holder mark/liquidation exposure
arbitrage/MEV transfers where observable
capital-time and forgone alternatives
tail route loss and bin exhaustion
```

There is no welfare conclusion from price variance alone. Dampened prints can be financed by LP
losses or by trapping holders behind worse aggregate liquidation.

## 7. Study designs in an honest order

### 7.1 Exact frozen-state shadow study

**Design.** On retained canonical/external states, compute direction × size grids for canonical-only,
external-only, and actual aggregate routes. Compare exact route quotes with/without the external
state while holding all else fixed.

**Identifies.** Mechanical quote/capacity possibility, M0.

**Does not identify.** Router adoption, order creation, arbitrage, actor adaptation, canonical
dynamics, or LP economics.

**Gate.** Calculator/router quote disagreement and landing-state error must be well below the
claimed change.

### 7.2 Descriptive landed route-flow study

**Design.** From pool activation onward, reconstruct every direct/split routed leg, canonical and
external state transition, candidate arbitrage bundle, LP edit, and exact inventory change.

**Outputs.** Route share by direction/size, absorption, bin traversal/exhaustion, lead–lag,
canonical print composition, aggregate quote/fill gaps, and LP waterfall.

**Identifies.** What happened under the installed market.

**Does not identify.** What would have happened without it.

### 7.3 Event study around creation, activation, adds/removes, and exhaustion

**Design.** Use separate event times:

```text
pool created on chain
liquidity first active/executable
router first returns the route
first landed external/split trade
material add/remove/recenter
directional bin/range exhaustion
route loss or recovery
```

Plot pre/post canonical and aggregate exact-size quote outcomes, route share, flow, and attention.
Use multiple pre-period windows, pre-trend tests, same-time market controls, and no outcome-selected
event window.

**Threat.** Each event is endogenous: LPs create/add/remove because they anticipate attention,
volatility, inventory demand, or price movement. Pool creation can also signal the market.

**Use.** Mechanism discovery and candidate timing, not causal proof alone.

### 7.4 Matched difference-in-differences

**Treatment unit.** Prefer the full mint × venue-network × intervention episode, not individual
trades.

**Controls.** Prospectively eligible tokens with no external installation during the risk window,
matched on lifecycle, canonical venue/state, age, quote capacity, flow, volatility, migration,
market/SOL regime, board/rank/social state, and intervention propensity.

**Outcomes.** Predeclared canonical and aggregate quote/print/tail measures at exact sizes.

**Requirements.** Parallel pre-trends on the actual outcome; no control later selected because it
stayed calm; staggered-treatment methods that tolerate heterogeneous timing/effects; explicit
treatment crossover; clustered uncertainty at territory/operator/time levels.

**Failure.** If installation is triggered by token-specific latent state whose pre-trend differs,
DiD is not credible. Do not “control” for post-install route share, external volume, or LP inventory
when estimating total effect.

### 7.5 Synthetic control

Construct a weighted donor combination using only pre-intervention features/outcomes and freeze it
before opening the post-period. Donors should be in comparable lifecycle and route-eligibility
regimes and not share the same direct spillover/territory event.

Required placebo tests:

- assign pseudo-install dates to donors;
- leave-one-donor-out sensitivity;
- vary pre-period without selecting by post fit;
- use several size/direction outcomes;
- test spillover exclusion; and
- compare canonical-only versus aggregate outcomes.

A beautiful synthetic match with one treated token cannot separate pool treatment from an
unobserved token-specific announcement at the same time.

### 7.6 Within-token withdrawal/reinstallation or shape-change comparison

Repeated external adds/removes/range changes can create self-controlled contrasts, but treatment
timing is intensely endogenous and carryover is expected. Current state depends on earlier routing,
arbitrage, and LP inventory.

Use event-history/state-space models with exact pre-state and report path dependence. An ABA shape
sequence is not a randomized crossover unless timing/shape were assigned independently of market
state and actors could not anticipate it.

### 7.7 Prospective randomized or scheduled intervention, only under later authority

The strongest feasible design would pre-register a bounded intervention family before outcomes:

- exact pool/profile/LP boundary and capital at risk;
- a small set of shapes differing in direction/range/capacity while matching total committed assets
  where possible;
- independently scheduled activation/change times within safe eligible windows;
- fixed router/quote probes and observation cadence;
- treatment assignment hidden from analysis code, not presumed hidden from the market;
- no concurrent discretionary edits except predeclared safety exits;
- complete LP liquidation and opportunity-cost scoring; and
- abort rules for loss, route anomaly, MEV, or source failure.

Randomization unit must be large enough to respect interference—likely a market/episode/time block,
not a trade. Even then, actors observe the liquidity and adapt; the estimand is the total market
response to the visible intervention. This document does not authorize such a trial.

### 7.8 Encouragement/natural experiment

Router support rollout, exogenous program/account limits, fee-policy changes, or operational
eligibility thresholds might shift route use. They are useful only if:

- assignment/timing is externally documented;
- the event affects outcomes through external route availability rather than another direct path;
- anticipation and concurrent platform changes are controlled; and
- first-stage route/quote changes are strong.

These conditions are demanding. “Jupiter began using the pool” is not an instrument when its solver
selected the pool because its state became attractive.

## 8. Interference and causal boundaries

### 8.1 No independent-token assumption

External liquidity for one token can affect:

- competing/duplicate coins in a territory;
- LP capital available elsewhere;
- router and arbitrage transaction capacity;
- SOL/quote inventory and fee markets;
- attention/ranking and wallet behavior; and
- the same actor's other positions.

Controls sharing the territory, LP, router congestion, or social event may be contaminated. Define
an interference neighborhood and run sensitivity to broader exclusions.

### 8.2 Endogenous pair and pool creation

LPs choose tokens, timing, quote asset, venue, range, and size because of expected volume, fees,
attention, inventory, or beliefs. Successful tokens are more likely to receive external pools.
Conditioning on “has an external pool” therefore selects on expected dynamics.

Required risk set: all token/venue/time states where installation was technically/economically
eligible and observable under healthy coverage, not only created pools.

### 8.3 Lifecycle and migration

Curve completion/migration can simultaneously:

- create/change the canonical pool;
- change fee rules and reserve geometry;
- attract arbitrage and router support;
- alter Pump chart semantics;
- trigger social/board attention; and
- make external pool creation feasible or attractive.

Do not define treatment onset at migration and attribute all post-migration differences to external
liquidity. Stratify or exclude overlapping lifecycle topology changes.

### 8.4 Regime confounds

Predeclare controls for:

- SOL/reference-market moves;
- platform-wide launch/activity bursts;
- time-of-day/week and network congestion;
- fee/config/program/router version;
- social/callout/creator events;
- canonical liquidity and flow state;
- token age/market-cap/capacity bands;
- territory competition/migration; and
- operator/product attention when Ember-selected cases are analyzed.

Regime labels must use information available before the evaluated outcome.

### 8.5 Post-treatment conditioning

Do not control for these when estimating total effect:

- route chosen;
- external volume;
- arbitrage volume;
- external LP inventory;
- post-treatment canonical liquidity;
- post-pool attention/rank; or
- later LP removal.

They are mediators or responses. They can enter mechanism analyses with explicit mediation
assumptions, not a total-effect regression disguised as adjustment.

## 9. Exact observation requirements

### 9.1 Treatment and external-pool closure

- pool/program/profile identities and deployment/version evidence;
- pair, mints, token programs/extensions, quote asset, and decimals;
- pool creation/activation plus every liquidity add/remove/claim/reward/recenter/close event;
- raw position, pair, bitmap, and all relevant BinArray states with coherent slots/write versions;
- active bin, bin step, exact per-bin X/Y, liquidity supply, position shares/checkpoints;
- dynamic/base fee and volatility parameters at quote/trade time;
- direction-specific traversal, visited bins, fee/rounding, and refusal/exhaustion;
- LP boundary, initial assets, external transfers, and final withdrawal when lawfully/observably in
  scope; and
- source gaps and unsupported deployed operation semantics.

### 9.2 Canonical Pump/PumpSwap closure

- exact curve/canonical pool identity and lifecycle topology;
- virtual/real or raw/effective reserve state and all fee configuration;
- mint supply/mode/creator-applicability and token-program state;
- every canonical trade/liquidity/migration event with full transaction/instruction locator;
- pre/post authoritative account state sufficient to detect stream drift;
- chart event/price/candle convention or raw chart-source response; and
- canonical exact-size quotes for the same direction/size grid as external/aggregate quotes.

### 9.3 Router and quote observations

- quote request identity, input/output assets, exact amount/size semantics, slippage/bounds;
- request/receive/available/expiry clocks and context slot/state closure;
- every route leg, venue/pool, allocation percentage/atoms, quoted in/out, fees, account constraints;
- router/API/solver/config version where observable;
- alternative route quotes or explicit absence, including canonical-only/external-only probes;
- transaction construction/simulation artifact if a later reviewed study permits it;
- landed transaction and per-leg reconciliation;
- route refusal, stale quote, provider disagreement, and changed route on repeat; and
- fixed-cadence direction × size probes independent of current activity to avoid sampling only
  trades that happened.

### 9.4 Transaction, ordering, and MEV observations

- source receive plus local monotonic clocks;
- send/ack/processed/confirmed/finalized clocks for controlled attempts, if ever in scope;
- slot, transaction index, instruction path/event index, inner instructions, logs, errors;
- signers, user, fee payer/relayer, priority fee, tip, compute, rent, and all balance effects;
- same-slot competing swaps/LP edits and candidate bundle relationships;
- failed landed transactions and known unlanded attempts from authorized local telemetry;
- candidate arbitrage path with evidence grade, never intent asserted from shape alone; and
- reorg/finality corrections.

### 9.5 Market, social, and product context

- Pump boards/feed membership/rank/order and route/pool visibility;
- launches, migrations, duplicates, territories, and competing coin states;
- posts, callouts, claims, creator/public participation, and source availability time;
- exact product render/viewport/open/arm events for Ember-attended cases;
- SOL and relevant reference/market state with source/clock;
- platform/router/program changes; and
- complete coverage/outage ledger for every source.

### 9.6 Outcome and LP economics

- canonical and aggregate quotes at fixed sizes/horizons, not only marks;
- landed user fill and transaction costs;
- route availability/failure/latency;
- external per-bin inventory path and exact fee/reward accrual;
- withdrawal inventory and exact both-leg liquidation routes;
- LP adds/removes/rebalances and their transaction/transfer costs;
- opportunity/capital-time and competing portfolio exposures;
- tail unrouteable state, dust, or token retained by choice; and
- common terminal horizon plus later resolution.

## 10. What BigQuery can and cannot establish

The exact answer depends on the retained BigQuery dataset, tables, decoder versions, and coverage.
A query result is not assumed authoritative merely because it is in BigQuery.

### 10.1 What an adequate chain warehouse can contribute

With complete raw/decoded Solana coverage and correct point-in-time program decoders, BigQuery can
support:

- landed transaction/signature/slot/instruction ordering available in the warehouse;
- successful and on-chain failed transaction records that the dataset retains;
- Pump/PumpSwap/DLMM pool creation, trade, migration, and liquidity events;
- wallet/signature/account-role and exact token/SOL balance deltas;
- observed route legs inferable from the landed transaction;
- historical realized canonical/external volume and flow allocation;
- candidate arbitrage/bundle patterns, with intent uncertainty;
- LP position/pool events where account/event state is retained; and
- retrospective event studies over landed chain facts.

These capabilities must be verified table by table. Decoded event tables can omit unknown
instructions, inner effects, account versions, failed cases, or upgrade-era fields.

### 10.2 What BigQuery alone cannot recover

BigQuery chain history alone generally cannot establish:

- the exact Jupiter quote and route alternatives available before a decision;
- routes considered but not returned or taken;
- fixed-cadence direction × size quote surfaces and refusal boundaries;
- local request/receive/render/gesture/send latency;
- unsubmitted or unlanded transaction attempts;
- private/ephemeral router solver state or version behavior not present on chain;
- which quote/state Ember or another user actually saw;
- Pump chart/backend inclusion and candle semantics unless separately captured;
- board/feed rank, viewport, social events, callouts, or operator intent;
- complete historical account state at arbitrary pre-trade cutoffs if raw snapshots/write versions
  were not retained;
- alternate no-installation routing and market path;
- participant/LP intent, private inventory constraints, or reason for add/remove;
- complete MEV searcher/leader opportunity set;
- exact counterfactual LP PnL under another shape; or
- a causal stabilization effect.

Even perfect landed-chain history observes only the realized equilibrium path. It cannot show which
orders would not have existed under higher cost, which router would have been selected without the
external pool, or how actors would have adapted.

### 10.3 BigQuery-specific audit before analysis

1. Inventory raw versus decoded tables and retention windows.
2. Verify canonical transaction and instruction locators.
3. Measure missing/duplicate/late partitions and reorg treatment.
4. Pin decoder/profile versions and unknown-instruction rates by time.
5. Determine whether account pre/post data and inner instructions close assets.
6. Reconcile sampled transactions to RPC/raw evidence.
7. Prove whether failed transactions and all target programs are retained.
8. Record knowledge-time limitation: warehouse ingestion time is not historical market availability.

## 11. Adversarial examples

### A. Canonical calm by diversion

Jupiter sends trades to the external pool. Canonical PumpSwap prints become sparse and their candle
variance falls, while aggregate exact-size quotes move identically or more. The canonical chart is
calmer; the market is not stabilized.

### B. Narrow-bin cliff

A tight DLMM range offers excellent conductance for small buys. One burst exhausts the active bins,
the route refuses or jumps to distant liquidity, and the next order sees a larger discontinuity than
without the pool.

### C. Toxic-flow sponge

The external LP buys token from informed/urgent sellers, slowing the aggregate quote decline while
accumulating a collapsing asset. Holders see smoother marks; the LP realizes the loss on withdrawal.
Stabilization is a transfer, not free welfare.

### D. Upside sale and forgone convexity

During a send, external bins sell X into buys and cap near-term aggregate displacement. The LP earns
fees but gives up the token's upside. Lower volatility can coincide with worse LP economic outcome.

### E. Imported external shock

The external pair moves first because of an LP withdrawal, stale/wrong shape, external order, or
reference-market move. Arbitrage transmits the movement into canonical PumpSwap, creating a shock
channel that did not previously exist.

### F. Fragmented capital

The same owner moves liquidity from canonical or another useful venue into the external pool.
Displayed venue count rises, but aggregate direction-specific capacity stays flat or falls.

### G. Router flip instability

Two routes have nearly equal quoted output. Tiny state/fee changes switch the winning route, creating
discontinuous allocations, different MEV exposure, and noisy canonical leg sizes despite a smooth
aggregate mark.

### H. Demand elasticity

Lower execution cost attracts more/larger trades. Per-unit response falls, but total canonical plus
external volume and price variation rise. The liquidity changed demand rather than passively
absorbing a fixed order set.

### I. Arbitrage ping-pong

Fees, rounding, latency, or route/state updates produce repeated cross-venue arbitrage. Cross-venue
price gaps shrink, while transaction prints and short-scale venue variance increase.

### J. MEV attraction

The new route makes sandwiches/backruns or priority competition more profitable. Quoted aggregate
cost improves, but landed cost/failure/tail latency worsens.

### K. Social signal confound

Pool creation or visible liquidity is interpreted as legitimacy/commitment, attracts attention,
and changes demand. A pre/post result attributes the move to mechanical depth even though the signal
path dominates.

### L. Procyclical withdrawal

The LP removes or recenters during volatility. Estimated normal-period resistance disappears in
the tail; the withdrawal itself accelerates route loss or price discrepancy.

### M. Inactive or wrong-side shape

Nominal TVL is large but bins relevant to the tested direction/size are inactive or out of range.
The scalar depth claim is false even before causality.

### N. Split-route chart illusion

A user swap is split. Pump records one smaller canonical leg, the external venue records another,
and the user's landed average differs from both prints. Comparing the Pump chart to user PnL creates
a fictional response.

### O. Survivor-selected pool

Only external pools that stayed active and liquid enter the dataset. Exhausted, abandoned,
unrouteable, or loss-heavy LPs disappear, making added liquidity look reliably stabilizing and
profitable.

## 12. Falsifiers by claim

| claim | evidence that would falsify or demote it |
| --- | --- |
| external liquidity changes frozen route geometry (`M0`) | no eligible route/quote change for the declared direction × size, or calculator/route error is as large as the change |
| it receives/diverts flow (`M1`) | router never returns it, no landed legs or arbitrage use it under healthy coverage, or nominal bins are inactive/wrong-side |
| it changes canonical dynamics (`M2`) | no reproducible canonical state/flow/quote difference after point-in-time matched controls; apparent change begins before activation/eligibility |
| it dampens aggregate dynamics (`M3`) | only canonical prints calm; aggregate exact-size quote/fill variance/tails do not improve or worsen |
| it restores after shocks (`M4`) | recovery is unchanged after matched shocks, driven by opposite/common flow, unstable across reference/outcome, or below state/clock error |
| it improves market safety/value (`M5`) | failure/MEV/tail route loss/holder liquidation or distributional losses offset the narrow variance change |
| it benefits the LP (`M6`) | fees fail to compensate inventory conversion, withdrawal/liquidation, costs, tails, and opportunity under prospective full-path accounting |

### Strong no-mechanism gate

If there is no route eligibility/use, no arbitrage linkage, no relevant external inventory
transformation, and no evidenced attention/adaptation channel, the installed liquidity cannot have
caused canonical dynamics through the proposed mechanism. A contemporaneous move is confounding or
an unmeasured mechanism until shown otherwise.

### Measurement stop gate

Stop causal claims when:

- pre/post venue state cannot be reconstructed;
- route alternatives and quote surfaces were not captured;
- canonical chart semantics are unknown;
- source/availability clocks cannot order the event;
- migration, social news, or regime change overlaps treatment without support;
- treated/control pre-trends fail;
- interference contaminates the donor/control set; or
- the effect is no larger than quote/fill/decoder/coverage uncertainty.

Preserve the exact route/inventory/LP accounting instrument even when causal estimation stops.

## 13. Non-gameable reporting bundle

Every result should contain:

1. treatment manifest and point-in-time route eligibility;
2. canonical and external native state before/after;
3. direction × size × route quote surfaces, with refusal;
4. canonical prints **and** canonical/aggregate exact-size quotes;
5. actual landed route/split legs and fill;
6. LP inventory/fees/withdrawal/liquidation path;
7. event/availability/chain clocks and coverage;
8. lifecycle, SOL, platform, social, and router regime;
9. pre-trends, donor/control construction, placebos, and negative controls;
10. actor adaptation, arbitrage, and MEV evidence/uncertainty;
11. mean, tail, route-loss, and capacity outcomes; and
12. explicit claims M0–M6 earned, rejected, or unidentifiable.

Do not report only TVL, a canonical candle chart, fee yield, or a before/after volatility number.

## 14. Research sequence for JOSHI

### R1 — static route geometry

Establish exact canonical/external/aggregate quote surfaces and route/refusal behavior at several
directions and sizes. This is useful executable exposure glass even if all dynamic claims fail.

### R2 — landed routing and LP truth

Reconstruct route legs, absorption, bins, adds/removes, fees, inventory transformation, withdrawal,
and liquidation. Determine whether the external pool is actually economically active.

### R3 — event atlas

Catalog pool creation, activation, router eligibility, first route use, shape edits, exhaustion,
withdrawal, migration, and route loss with canonical and aggregate outcomes. Use it to freeze shock
and event definitions.

### R4 — observational causal candidates

Run matched risk-set, event-study, DiD, and synthetic-control analyses with canonical/aggregate
outcomes, interference exclusions, and placebo tests. Treat failures as causal-boundary evidence.

### R5 — prospective observational replication

Before any intervention, prospectively freeze eligible installations, covariates, size grids,
router probes, outcomes, and analysis windows. Observe naturally occurring installations and all
failures/non-installations.

### R6 — later bounded intervention decision

Only after R1–R5 establish measurement quality and a meaningful unresolved causal question should a
separate authority/safety review consider whether a tiny scheduled shape intervention is justified.
This lane supplies no such authority.

## 15. Questions that remain open

1. Which external venue/pair shapes are actually eligible for the router at Ember-relevant sizes?
2. Does route eligibility lag pool creation, and how is that availability observed?
3. Can canonical-only, external-only, and aggregate quote probes be collected at fixed cadence
   without activity-dependent missingness?
4. Which Pump chart convention is used before/after migration and for routed PumpSwap legs?
5. Can landed Jupiter split allocations be reconstructed exactly across nested instructions and
   balance effects?
6. How accurately can candidate arbitrage be identified without inventing actor intent?
7. Does external liquidity add net capacity or relocate the same LP/portfolio capital?
8. At what direction × size does a given DLMM shape switch from useful capacity to bin cliff?
9. Does dynamic fee response stabilize LP inventory, discourage flow, or cause route switching?
10. Are canonical print, canonical quote, aggregate quote, and user-fill effects different in sign?
11. Which shocks originate externally versus share a Pump/social/SOL common cause?
12. Do LP withdrawals lead stress, respond to it, or both?
13. Does reduced execution cost expand demand enough to offset per-unit dampening?
14. Does a route reduce ordinary variance while worsening exhaustion/MEV/liquidation tails?
15. Is any benefit robust after full LP economic accounting and capacity scaling?

## Decision boundary

The rational near-term objective is not to prove that external liquidity “puts a wall” in front of
Pump price motion. It is to build a point-in-time, direction × size × route account of:

```text
what quotes changed mechanically
where flow actually executed
how arbitrage linked states
which inventory absorbed it
when exact bins/routes exhausted
what canonical versus aggregate prices showed
who bore the resulting costs and tail risk
```

If that account is reliable, a causal study becomes possible. If it is not, the obstruction story
is unmeasured metaphor. If the study succeeds, the result will still be local to a shape, direction,
size, route universe, lifecycle, and regime—not a universal scalar law of liquidity.
