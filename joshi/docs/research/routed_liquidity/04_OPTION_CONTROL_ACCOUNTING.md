# Routed liquidity lane 04 — option, control, and accounting model

Status: pre-engineering research, 2026-08-17. No execution authority.

## Executive finding

Routed liquidity should be treated as one path-dependent portfolio control problem operating at
three clocks, not as a sequence of profitable or unprofitable “cycles”:

1. a **slow edge policy** decides whether a routeable liquidity edge should be proposed, shadowed,
   installed, paused, retired, or left absent;
2. a **medium schedule policy** decides which finite bins or ranges are funded, what inventory is
   acceptable, when fees are merely observed versus collected, and whether capital should be
   added, removed, or redistributed; and
3. a **fast spot policy** separately decides whether to crackle, hedge, reduce, zap, remain flat,
   or re-enter.

All three consume or transform the same assets. They therefore share one finalized accounting
projection and one portfolio constraint set. “LP inventory,” “hedge inventory,” and “crackle
inventory” may be prospective reservations or retrospective attribution, but they are not three
balances. A token atom cannot simultaneously fund a bin, satisfy a SOL reserve, and be available
for a fast spot action.

The economic hypothesis is coherent but unproven. A routeable LP sells a bounded, funded form of
immediacy and price-contingent inventory transfer to incoming flow. Fees may pay for the separate
stabilization service needed to keep household inventory inside an acceptable region. That is not
free yield: informed flow, relative-price movement, correlation breaks, hedge friction, capital
lock-up, and terminal liquidation can consume more value than fees provide.

The next valid step is an instrumented, read-only shadow comparison. It must use exact inventory,
same-cutoff quotes, explicit missingness, a predeclared terminal-liquidation method, and policies
that cannot see future state. This lane does not justify installing liquidity, building
transactions, or automating either the medium or fast policy.

## 1. Scope and language

This lane owns the joint economic and control semantics for a possible routed-liquidity system. It
does not choose a pool, bin step, width, fee, hedge ratio, crackle trigger, or allocation amount. It
does not establish that any current program or UI supports a modeled action.

Use these terms precisely:

- An **edge** is a versioned proposal to make a particular asset pair, venue, pool/profile, and
  funded schedule eligible to serve routed external or household flow. It is not a trade and has
  no natural round-trip boundary.
- An **edge tenure** is an interval from installation to retirement, possibly containing pauses,
  schedule versions, deposits, withdrawals, fills, fees, hedges, and unrelated spot episodes.
- A **schedule version** is an observation-bound finite bin/range allocation and its intended
  conversion roles. An add, remove, or in-place rebalance creates a new version even if position
  identity survives.
- A **principal transfer** is the inventory exchange attributable to routed flow, excluding fees.
- A **stabilization action** is a separately authorized spot or schedule action intended to bring
  current and reachable inventory back toward an acceptable set. It is not automatically a hedge,
  and its economic quality must be evaluated independently.
- A **fast episode** retains the existing episode → inventory epoch → clip/lot semantics. It may
  overlap an edge tenure without becoming an “LP cycle.”
- **External flow** originates outside the consolidated controlled domain. **Self-routed flow**
  originates inside it and touches owned liquidity. They have different accounting meaning.
- The **controlled domain** is the explicit set of wallets, token accounts, LP positions, fee and
  reward rights, recoverable-rent claims, and unsettled effects included in one balance sheet.

“Exact” in this document means exact integer/rational calculation from a named observation and
formula profile. It does not mean current, causal, landed, or known when an input is missing.

## 2. Why a cycle is the wrong unit

A deposit followed by a withdrawal is a custody path, not necessarily a completed economic trade.
The withdrawal can return two risky assets, unclaimed rewards, and recoverable rent. A rebalance can
retain position identity while materially changing future conversions. A fast hedge can remain
open after an edge retires. Conversely, one long-lived edge can serve hundreds of unrelated flow
events and coexist with several crackle episodes.

Calling any of these a cycle causes predictable errors:

- it chooses a favorable boundary after inventory happens to return near its starting mix;
- it calls withdrawn tokens realized proceeds without liquidating them;
- it makes self-routed fees look like external income;
- it loses the mark-to-terminal effect of inventory still held;
- it hides the opportunity cost of capital throughout an edge tenure;
- it assigns a fast graph-driven exit or re-entry to the LP simply because the mint overlaps; and
- it allows fees from one interval to offset an unrelated inventory loss without a declared common
  horizon and benchmark.

Evaluation therefore begins from a common portfolio snapshot at `t0`, ends at a predeclared horizon
`H`, and liquidates or explicitly leaves unknown every residual through the same terminal method.
Sub-interval diagnostics are useful, but none may change the outer boundary after observing the
answer.

## 3. One inventory, three policy clocks

### 3.1 Slow edge-install/retire policy

The slow policy answers whether the portfolio should offer an edge at all. Its information set can
include long-window external route demand, venue/profile compatibility, capital opportunity cost,
observed fee regimes, flow toxicity, correlation structure, operational health, and the value of
the fast policy as a stabilizer.

Its proposed lifecycle is:

```text
absent -> proposed -> shadow -> installed -> paused -> retiring -> retired
                          |          |          |
                          +----------+----------+-> rejected/abandoned
```

`paused` means no additional intended service or risk increase under the slow policy; it does not
assert that already funded bins cannot fill. `retiring` means conversion capacity and inventory are
being reduced under explicit bounds; it does not mean the returned assets have been sold.

Slow actions are policy transitions: propose an edge, approve a capital ceiling, install or pause
eligibility, begin retirement, or terminate evaluation. They may authorize a later bounded medium
intent, but they do not themselves manufacture an LP action.

### 3.2 Medium bin/range/fee/rebalance policy

The medium policy shapes the funded contingent trade schedule while the edge exists. It owns:

- pair orientation and named asset roles;
- finite lower/upper bins and per-bin weights;
- maximum current and edge-traversal inventory by asset;
- additions, partial removals, and in-place redistribution proposals;
- top-up maxima, withdrawal minima, claim flags, rent and friction budgets;
- acceptable observed fee profiles and route competitiveness;
- response to active-bin movement, fee-state change, volume drought, or toxic flow; and
- retirement chunking when a single coherent transformation is unsupported.

“Fee policy” usually means an acceptance/selection rule over observed venue fees, fee collection,
and fee attribution. It must not imply that this portfolio can mutate pool fee parameters. A
program-governed or immutable fee is an observed state. Any future authority to change a fee would
be a separate capability with its own evidence and review.

Add, remove, in-place rebalance, and close/reopen remain structurally distinct. Swap permission is
false unless a separate spot intent names it. A modeled budget that conserves X and Y is not proof
that deployed program instructions, route accounts, or a UI can enact it.

### 3.3 Fast spot/hedge/crackle policy

The fast policy operates on fresh route and inventory state. It can propose:

- an independent human-armed crackle entry or exit;
- a partial realization and explicit runner retention;
- an inventory reduction or hedge for a named edge exposure;
- a full graph-driven zap, flat-watch interval, and later re-entry;
- cancellation of an unsubmitted conflicting intent; or
- refusal because quotes, state, authority, or reserve headroom are inadequate.

A fast action is not presumed to close an LP loop. A crackle can intentionally increase the same
asset an LP policy would reduce. A hedge can be economically bad even when it restores a target
mix. A graph-driven exit can be valuable for reasons unrelated to edge maintenance. Preserve its
episode and immediate reason rather than laundering it into “rebalance.”

### 3.4 Coordination, precedence, and no silent netting

Each policy has its own ID, version, state, observation cutoff, horizon, permitted action family,
and budget. A coordinator may identify conflicts, but it must not combine unlike intents into one
opaque net transaction. For example, a 100-token crackle buy and a 60-token LP-driven hedge sell
are two causal decisions, not a 40-token buy with a fabricated purpose.

The default precedence is:

1. reconciliation and stale/conflicting-state refusal;
2. protected reserves and explicit authority ceilings;
3. cancellation of still-unsubmitted incompatible risk increases;
4. narrowly defined risk-reducing actions that do not violate another protected constraint;
5. fast operator intent;
6. medium schedule maintenance; and
7. slow expansion.

This ordering is a research proposal, not signer policy. “Risk reducing” must be checked against
the reachable consolidated inventory, not inferred from words such as `withdraw` or `hedge`.

## 4. The exact object being controlled

Let `A` be the set of exact asset identities in the controlled domain. At finalized state `t`, the
accounting projection provides an atomic quantity vector:

```text
Q_t[a] = wallet[a]
       + LP_principal_entitlement[a]
       + claimable_fee_right[a]
       + claimable_reward_right[a]
       + other_controlled_custody[a]
```

Every term must be supported, explicitly unsupported, or absent for a stated reason. Principal,
fees, and rewards remain separate even when denominated in the same asset. Merely depositing into
or withdrawing from LP custody cannot change consolidated `Q_t`.

Submitted but unresolved actions do not change `Q_t`. They create reservations and reachable
states until independent finalized wallet effects land. A finalized effect is already reflected in
the appropriate custody term and must not be added a second time.

The controller also needs a **reachable-inventory surface**, not just the current vector:

```text
Reach_t = {
  Q_t,
  inventory after each materially funded bin crossing,
  inventory after complete lower-edge traversal,
  inventory after complete upper-edge traversal,
  inventory after every concurrently armed fast intent,
  inventory under named partial-failure orderings
}
```

`Reach_t` is a finite scenario set or conservative envelope produced from exact schedules and
bounded intents. It is not a probability distribution unless a separately identified estimator is
introduced.

The slow policy controls installed conversion capacity, the medium policy controls the shape of
that capacity, and the fast policy controls additional spot effects. None controls future external
flow, the relative price path, route selection, landing, or social attention.

## 5. Finite-bin optionality

### 5.1 Pair orientation first

For every explanation choose exact assets `X` and `Y` and define relative price

```text
P = Y atoms, with declared decimal normalization, per X atom
```

The stored financial representation remains the protocol Q64.64/bin form. `P` is explanatory and
must name decimal normalization and observation. Never infer “sell side” from bin sign, screen
position, token symbol, or the words “above” and “below” without naming which asset leaves the LP
when the bin is traversed in which direction.

Every funded bin should admit a sentence of this form:

> Under traversal direction `D`, this bin can transfer at most `q` atoms of `X` from controlled LP
> principal and receive `r` atoms of `Y`, before separately accounted fees and competing flow.

### 5.2 Single-sided finite ladders

A one-sided ladder is closer to a funded sequence of limit-like conversions than to a symmetric
market-making position:

- an **X-offer ladder** begins with X inventory and progressively exchanges bounded slices for Y
  as specified bins traverse. Relative to holding X, converted slices give up later X continuation
  in exchange for earlier Y realization and fees;
- a **Y-offer ladder** begins with Y and progressively acquires X. It commits capital to take the
  other side of X-selling flow and inherits X downside after fills; and
- either ladder saturates at a finite edge. It cannot sell more than funded inventory, cannot buy
  with uncommitted wallet capital, and does not have an unlimited short-option payoff.

Price reversal may convert inventory again, but this is a new path event, not proof that a
profitable cycle completed. Fees, bin dust, path ordering, external prices, and terminal inventory
still determine the result.

The covered-call or cash-secured-put analogy is useful only directionally. An LP bin is not a legal
option contract: it has no fixed expiry, counterparty exercise notice, or standalone upfront
premium, and its price path and inventory mechanics are protocol-specific. The durable statement
is that the LP offers bounded inventory conversion on terms that other flow may choose to consume.

### 5.3 Symmetric or two-sided concentrated liquidity

A two-sided schedule around the active region repeatedly sells the relatively appreciating asset
and buys the relatively depreciating asset while the price remains in range. Relative to holding a
fixed starting basket, that behavior is commonly short local relative-price convexity or “short
gamma”: it can underperform when relative price moves persistently or jumps, while fees compensate
for supplying the path.

It is not delta-neutral by default. Its delta changes with price, bin occupancy, and range. Once a
finite range is fully traversed, inventory can become effectively one-sided and the local
two-sided behavior stops. “Symmetric at installation” therefore says almost nothing about terminal
asset mix.

### 5.4 Who is long and short what

The optionality map should be rendered as an economic analogy, not a claim that the positions are
exchange-traded options:

| Actor or policy | Optionality held or supplied | Consideration / cost | Boundaries |
| --- | --- | --- | --- |
| external trader or router | discretion to consume the posted conversion only when useful | pays the applicable spread/LP, protocol, and other fees | limited by funded bins, route competition, state, and transaction capacity |
| installed LP edge | supplies immediate, state-contingent inventory transfer; bears selection by flow | receives owned share of external LP fees/rewards | loss is bounded by funded inventory but can approach its value; no fee guarantee |
| one-sided X-offer ladder | short X continuation on slices after they convert, relative to holding X | Y proceeds plus fees | finite quantity and range; remaining X retains upside |
| one-sided Y-offer ladder | commits Y to buy X into qualifying flow; short crash continuation relative to waiting | acquired X plus fees | finite committed Y; downside persists after acquisition |
| two-sided finite LP | supplies local relative-price convexity and immediacy | flow fees while competitive/in range | becomes directional at range edges; not generally neutral |
| liquid reserve plus operator | preserves discretion to enter, hedge, or decline later | foregone current fee opportunity | constrained by attention, latency, and future route availability |
| fast stabilizer | buys back or transfers some inventory/relative-price risk through separate trades | pays impact, venue/network fees, and selection cost | works only while the hedge route and authority remain usable |
| retained runner | holds linear right-tail asset exposure; it is not itself an option | current value and opportunity cost remain at risk | limited liability at zero does not make recovered-basis inventory “free” |

The LP is particularly exposed to **pickoff**: flow is more likely to consume stale or attractive
posted liquidity when the external opportunity has already moved. Fees are the price charged for
this service, not evidence that the selection cost was covered.

## 6. Relative price and correlation breaks

An X/Y LP is primarily a path-dependent exposure to the relative price `P_X/P_Y`, but household
obligations can be denominated in SOL or USD. Two assets can rise together in USD while the LP
still converts the stronger asset into the weaker one. They can appear historically correlated and
then break because a creator disavows one coin, a duplicate captures attention, a route migrates,
or SOL moves independently.

At minimum, evaluate the following distinct shocks:

- X falls against Y while Y is stable in the reserve currency;
- Y falls against X;
- both fall in USD but their relative price remains stable;
- both rise in USD while one materially outperforms;
- relative price jumps across several bins without observable intermediate route opportunity;
- liquidity disappears exactly after the LP acquires the weaker asset; and
- a social identity or community link makes apparently different assets fail together.

Historical covariance is only one estimate. The hard portfolio control should use current and
edge-traversal quantities under named scenarios. Unknown correlation or narrative linkage is not
zero concentration.

## 7. Stabilization as an LP-paid service

A profitable joint system need not demand that the passive LP be attractive in isolation. The edge
can purchase a separate stabilization service from the fast or medium policy, provided the joint
ledger remains positive after every cost and the service does not appropriate reserve capital
without authority.

Examples of stabilization include:

- removing future X-to-Y capacity because the household no longer accepts more Y;
- externally selling newly acquired Y back toward an acceptable set;
- using a separate route to hedge relative-price exposure;
- pausing additions while existing bins remain funded; or
- retiring an edge when the cost of maintaining acceptable inventory exceeds expected external
  fee income.

The internal research charge should be explicit:

```text
edge service revenue
  = owned LP fees attributable to external flow
  + external route rebates or rewards with evidenced value

stabilization service cost
  = hedge/reduction venue fees and impact
  + network, priority, transfer, and nonrecoverable account costs
  + schedule-edit friction and time out of service
  + inventory transfer disadvantage under the chosen estimator
  + capital and attention opportunity cost
```

The fast book may receive an attribution credit equal to its prospectively defined service charge,
but that internal charge cancels in the consolidated household. It cannot create total PnL. If
stabilization is only profitable because the fast action is credited with hindsight-best exits, the
hypothesis fails. This service-cost view is diagnostic: when the selected terminal alternative
already prices the same capital or attention opportunity, do not subtract that opportunity a second
time.

## 8. Exact accounting and valuation waterfalls

### 8.1 Landed multi-asset truth comes first

Finalized controlled-wallet effects determine inventory. Program events, route logs, LP fee
records, episodes, and policy labels classify the landed effects but cannot override them. The
commodity ledger balances by asset before any SOL or USD projection.

The following remain different artifacts:

- exact finalized wallet and LP-custody quantities;
- observed or deterministically projected principal, fee, and reward entitlements;
- chart or marginal marks;
- size-specific state-conditioned quotes;
- full-position quote projections;
- hypothetical shadow effects;
- landed fills and post-state; and
- retrospective episode or policy attribution.

The V1 projection contract is finalized and read-only. A fast cockpit will eventually need a
separately named provisional artifact; it must not weaken finalized accounting by treating a
processed quote or pending action as landed truth.

### 8.2 Terminal liquidation waterfall

For reporting numeraire `N`, define `TLV_t^N(Q; M)` under valuation manifest `M`. The manifest fixes
the exact horizon, routes, sizes, state/profile observations, fee assumptions, freshness, network
cost treatment, rent treatment, and FX path.

For each controlled asset and LP position:

1. begin from independently reconciled wallet quantity and current per-bin LP entitlement;
2. keep principal, pending fees, and rewards in separate rows;
3. model withdrawal without a swap, including claim flags and explicit unsupported accrual;
4. add recoverable rent only as a separate claim and subtract irreversible close/remove costs;
5. quote the full resulting amount through a named size-specific route into `N`;
6. subtract venue, protocol, creator, transfer, network, priority, and other included costs exactly
   once;
7. expose minimum-bound versus expected output separately when both exist; and
8. retain every unrouteable, stale, conflicting, or unsupported leg as a named residual.

The scalar `TLV` is `unknown` or `partial`, not a lower-looking numeric total, when any required leg
cannot be valued under `M`. A zero requires an explicit zero-value scenario. A chart mark cannot be
substituted for a full-size route.

### 8.3 Net-PnL waterfall

Choose `t0` and `H` before evaluation. Let `W_t^N = TLV_t^N(Q_t; M_t)`. Let `C^N` be external
contributions into the controlled domain and `D^N` external distributions out, each valued by a
declared contemporaneous manifest rather than a terminal or hindsight-best price. Then:

```text
NetPnL_[t0,H]^N
  = W_H^N
  - W_t0^N
  - C_[t0,H]^N
  + D_[t0,H]^N
```

This is the consolidated terminal-liquidated wealth change. Internal wallet transfers, LP
deposits/withdrawals, self-paid owned fee accrual, and internal policy charges cancel. If a required
external flow cannot be converted to `N`, the reference PnL is unknown while native quantities
remain exact.

The audit waterfall should show, without implying independent additivity:

- starting terminal-liquidated wealth;
- external contributions/distributions;
- landed spot and LP principal exchange effects by native asset;
- LP fees and rewards, external versus self-routed;
- fast crackle/hedge effects and transaction costs;
- schedule-edit, rent, and nonrecoverable costs;
- ending residual quantities and terminal routes; and
- exact reconciliation residual.

Episode PnL and lot basis remain available for fast-policy interpretation. They must reconcile to
the relevant landed effects, but tax/lot choice cannot alter consolidated wealth change.

### 8.4 Inventory-transfer regret

Inventory-transfer regret (`ITR`) is a local execution-quality counterfactual for an LP principal
fill, not actual PnL. Suppose the LP gives exact amount `a` of X and receives principal amount `b`
of Y at event `f`, excluding LP fees. Obtain a contemporaneously feasible, size-specific external
route that excludes the household's own liquidity and would exchange `a` X for expected net output
`q_f(a)` Y under a predeclared latency profile. `q_f(a)` includes that alternative route's impact
and venue fees but excludes separately reported network/account cost. Define:

```text
ITR_f^Y = q_f(a) - b
```

Positive means the principal transfer received less Y than the feasible external alternative;
negative means it received more. Reverse X/Y explicitly for the opposite direction. Conversion to
`N` needs a separate same-cutoff valuation. Aggregate only events with compatible manifests, and
retain unquotable events as missing rather than zero.

LP fee income is shown next to, not hidden inside, ITR. A useful event view is:

```text
principal alternative advantage  = -ITR_f
+ owned external-flow LP fee
- attributable irreversible cost
= local service surplus
```

ITR measures an execution alternative at the fill time. It does not measure the later value of the
inventory received and must not be added to LVR if both encode the same adverse-selection loss.

### 8.5 Loss-versus-rebalancing

LVR requires a named counterfactual; it is not a field recoverable from fee APR. For this project,
use an explicitly discretized, causal estimator `LVR_grid`:

1. start the passive-LP principal branch and a rebalancing branch from the same exact inventory;
2. predeclare an external reference-price event grid and availability latency;
3. make the rebalancing branch follow the same target exposure rule at those reference events,
   using exact rational prices or executable quotes and no future observations;
4. exclude LP fees from the passive principal branch for gross LVR; and
5. terminal-liquidate both branches with one manifest at `H`.

```text
LVR_grid^N(H)
  = TLV_H^N(rebalancing branch)
  - TLV_H^N(passive LP principal branch)

LP_net_vs_rebalancing^N(H)
  = -LVR_grid^N(H)
  + TLV_H^N(external-flow LP fees)
  + TLV_H^N(eligible non-household rewards/rebates)
  - LP-specific irreversible costs^N
```

A positive `LVR_grid` means the rebalancing branch ends richer; preserve a negative value rather
than clipping it to zero. Fees and rewards are valued as separate controlled assets and counted
exactly once.

The conventional frictionless rebalancing branch and an operational branch charged actual route,
impact, latency, and network costs are different benchmarks and must have different IDs. The
operational result may be called rebalancing regret; do not silently market it as canonical LVR.

Finite ranges, jumps over bins, missing reference events, and unrouteable benchmark actions make
the estimator partial or unsupported. Continuous-time language must not be used for a sampled
event-grid result.

### 8.6 Opportunity cost

Opportunity cost is a branch comparison, not an expense posting. For one predeclared feasible
alternative `B` and actual joint policy `A`, rooted at the same snapshot and information cutoff:

```text
BranchScore_P^N(H)
  = TLV_H^N(P)
  - external_contributions_P^N
  + external_distributions_P^N

OpportunityCost_B^N(H)
  = BranchScore_B^N(H) - BranchScore_A^N(H)
```

Keep the signed result: a negative number means the chosen policy beat the alternative. Candidate
alternatives include remaining liquid in SOL, an uninstalled edge, an unchanged schedule, a
specific rejected crackle, and a predeclared passive hold. Never choose the best realized coin or
bottom after the fact. When external contributions and distributions are identical across branches,
the expression reduces to their terminal-liquidation difference.

Several opportunity-cost branches are mutually exclusive explanations and cannot all be deducted
from PnL. Attention cost, capital lock-up, and a rejected intent can be reported separately only
when their overlap and allocation rule were declared prospectively.

### 8.7 What may and may not be added

The authoritative joint surplus against predeclared alternative `B` is the terminal branch
difference, equivalently the negative opportunity cost:

```text
JointEdgeSurplus_B^N(H)
  = BranchScore_joint^N(H)
  - BranchScore_B^N(H)
  = -OpportunityCost_B^N(H)
```

Both branches start from the same inventory and include their own external costs. A diagnostic
waterfall may attribute this difference to external-flow fees, eligible non-household rewards,
chosen adverse-selection measure, stabilization/schedule friction, incremental terminal
liquidation cost, and a named residual. It must reconcile exactly to the branch difference.

Use either LVR or aggregated ITR as the adverse-selection comparator, not both unless a proof
establishes disjoint components. Capital opportunity is already expressed by alternative `B`; it
must not be subtracted from the branch difference again. This statistic does not replace
consolidated `NetPnL`, and internal credits between edge, medium, and fast books must sum to zero.

## 9. Self-routing and internal fee elimination

Routing a household spot action through household-owned LP liquidity may reduce external fee
leakage or intentionally transfer inventory between controlled custody locations. It does not make
the trade free and must not create fee income.

For a self-routed action retain:

- exact spot-wallet before/after effects;
- exact LP principal before/after entitlement;
- total LP fee assessed by the protocol;
- LP fee actually accrued to the controlled position, not an ownership-share guess;
- LP fee paid to other providers;
- protocol, creator, host, transfer, and network fees;
- external route opportunity at the same size and cutoff;
- pool-state change and any effect on future external flow; and
- transaction failure or partial-operation state.

If `F_lp_total` is the assessed LP fee and `F_owned_observed` is the evidenced controlled accrual:

```text
F_lp_external = F_lp_total - F_owned_observed

net household fee leakage
  = F_lp_external
  + protocol_fee
  + creator_or_host_fee
  + transfer_fee
  + network_and_priority_fee
```

This calculation is valid only when asset, event, and accrual closure match and subtraction is
nonnegative. Otherwise the owned offset is unknown. `F_owned_observed` is an internal transfer from
the household trade path into LP custody; it is not external service revenue. Claimed versus
claimable status changes custody timing, not whether the household already controls the right.

Price impact, stale-quote selection, foregone external LP flow, and inventory risk remain even when
fee leakage falls. A strategy that manufactures its own displayed LP fees by self-trading is
strictly no-go: assess it on consolidated wealth after all external costs, and exclude self-flow
fees from evidence that the edge attracts or monetizes external demand.

## 10. Acceptable inventory and shared budgets

### 10.1 An acceptable set, not one magic target

Let `A_t` be a versioned set of inventory states acceptable to the household at horizon `t`. It can
contain:

- per-asset minimum and maximum atoms;
- minimum spendable SOL after pending and concurrently armed commitments;
- dated reserve coverage in the obligation currency;
- maximum current and fully traversed risky-asset exposure;
- maximum mint, narrative, venue, and route concentration;
- maximum amount unliquidatable within named time/impact bands;
- allowed LP fee/reward assets and unsupported-field limits; and
- explicit exceptions for exact dust or intentionally retained runners.

The rule is robust rather than expected-value only:

```text
for every reachable state q in Reach_t(action):
    q must be in A_t
```

If a modeled action can partially land, every credible prefix/post-state is included. A narrowly
authorized repair action may move an already violating portfolio closer to `A_t` without reaching
it immediately, but it may not worsen protected reserve or authority dimensions. This exception
needs a monotone risk measure and cannot be inferred from the action name.

### 10.2 Capital budget

The capital budget constrains exact atomic commitments:

- current funded principal by asset;
- maximum additional deposit or spot spend;
- capital reserved by every armed action under simultaneous trigger;
- minimum liquid SOL and dated reserve;
- recoverable rent and its recovery horizon;
- terminal liquidation capacity and impact; and
- learning-loss authorization distinct from recent gains.

Available balance is computed after reservations. Unused authorization is not an asset, and one
atom cannot be reserved twice.

### 10.3 Rebalance budget

The rebalance budget limits maintenance even if final inventory is acceptable:

- maximum per-action and rolling turnover by asset;
- maximum top-up and minimum withdrawal;
- maximum irreversible venue/network/rent/transfer cost;
- maximum allowed time out of service;
- maximum actions or chunks per horizon;
- maximum allowed path through intermediate inventory states;
- explicit swap permission, default false; and
- minimum expected improvement in distance to `A_t` or future reachable exposure.

Frequent low-notional edits can lose to friction and attention while every individual edit appears
safe. Measure cumulative footprint and schedule-version churn.

### 10.4 Authority budget

Authority is distinct from capital. Every prospective intent needs exact assets, position/pool,
policy version, action family, maximum amounts, fee/impact bounds, TTL, state/freshness binding,
and cancellation rule.

The slow policy cannot authorize fast spot trading merely by installing an edge. The medium policy
cannot smuggle a swap into rebalance. The fast policy cannot broaden range, promote a runner, use a
dated reserve, or increase an edge ceiling. No shadow artifact, projection DTO, or model output
grants any of these capabilities.

## 11. State, observation, and action spaces

### 11.1 State decomposition

Use four disjoint classes:

1. **Landed financial state:** finalized balances/effects, lots, basis quality, episodes/epochs,
   position/bin principal, observed fee/reward rights, reserves, and outstanding durable attempts.
2. **Deterministic state-conditioned projections:** marks, exact quotes/refusals, full-position
   quote projections, edge-traversal inventory, modeled add/remove/rebalance budgets, and terminal
   liquidation under named manifests.
3. **Latent estimates:** external fair value, flow arrival/toxicity regime, correlation break,
   route-selection probability, expected fee revenue, and action success/latency distributions.
4. **Operator perception:** disposition, desired inventory, graph/social interpretation, urgency,
   and annotation grounded in a scene or interview.

Only classes 1 and 2 inhabit the existing exact financial projection. Estimates require estimator,
build, input cutoff, uncertainty, support, and claim scope. Perceptions require scene/gesture or
annotation evidence. A common enum label must not make all four appear equally factual.

### 11.2 Observation space

At decision cutoff `t`, the policy information state may include:

- coherent finalized wallet and LP account observations;
- provisional but separately named pool/route observations for shadow decisions;
- active bin, bin arrays, share, accrual, fee profile, token extensions, and program lifecycle;
- intended-versus-observed quote state, size, route, fee components, slots and wall/monotonic
  freshness;
- route competitors, routed volume and outcome evidence with known coverage gaps;
- external reference quotes excluding owned liquidity;
- SOL/USD reference observations when required by the reserve policy;
- operator episode/disposition/scene and social-transition observations; and
- current policy versions, reservations, constraint set, and unresolved actions.

Missing, stale, conflicting, partial, unsupported, and refused are different observations. The
controller cannot turn any of them into zero or carry them forward without a declared validity
policy.

### 11.3 Action space

Actions remain tagged by clock and semantic family:

| Clock | Policy actions | Financial action produced |
| --- | --- | --- |
| slow | propose, shadow, install, pause, begin retirement, retire, abandon | none directly; may create/cancel bounded medium authorization |
| medium | hold schedule, add, remove, redistribute in place, close/reopen, claim, change acceptance rule | modeled custody/schedule transformation; explicit swap remains separate |
| fast | observe, arm, cancel, buy, sell, hedge, partial realize, keep/promote runner, zap, watch flat, re-enter | separately quoted hypothetical spot effect and later independent landed effect |

An action can also be `refuse(reason)`. Refusal is often the only correct action under stale state,
unsupported fee math, unacceptable reachable inventory, insufficient reserve, policy conflict, or
unresolved prior attempt.

### 11.4 Policy-state products

The full control state is the product of three state machines, not one flattened status:

```text
slow:   absent | proposed | shadow | installed | paused | retiring | retired | abandoned
medium: observed(version) | candidate(version) | shadow_admissible | refused(reason)
        | awaiting_independent_effect | reconciled(new observed version) | superseded
fast:   observing | armed_flat | entry_pending | exposed | exit_pending
        | flat_watching | reentry_armed | resolved
```

The medium `awaiting_independent_effect` state describes a future evidence boundary, not a
transaction facility supplied by this lane. A candidate or shadow-admissible schedule never
replaces observed position state. The fast states reuse the episode semantics and can coexist with
any slow state; for example, a runner may remain exposed after an edge is retired.

## 12. Safe shadow-policy evaluation

### 12.1 Branches and baselines

Every shadow branch begins from the same immutable finalized snapshot and knowledge cutoff. At
minimum compare:

- no edge, assets remain under the declared liquid/hold baseline;
- installed edge with schedule held unchanged;
- the candidate medium maintenance policy;
- candidate edge plus fast stabilization policy;
- candidate fast spot policy without the edge; and
- the actual operator path when prospectively observed.

This factorial shape distinguishes edge value from fast selection value and interaction value. It
does not assume that LP and fast actions form one cycle.

### 12.2 Chronology and reproducibility

Each policy version is frozen before its evaluation interval. Replay exposes only observations
available by the branch cutoff, including real ingest, render, decision, quote, and assumed-send
latencies. The branch records:

- policy/build and exact input manifest;
- quote/protocol/calculator versions;
- reservations and acceptable-inventory set;
- hypothetical action, route, size, bounds, and refusal;
- deterministic effect or named unsupported element;
- terminal horizon and liquidation manifest; and
- canonical digest and, when stochastic, seed/draw manifest.

Hypothetical effects never enter the actual ledger and are never called fills. Re-running the same
branch must be byte-identical.

### 12.3 Endogeneity and support limits

Installing an edge can change whether a router selects the pool, pool state, competitor response,
and subsequent flow. Historical replay of an edge that did not exist cannot honestly assume all
observed market flow would have used it. Likewise, a self-routed hedge changes the same bins whose
future fees are being estimated.

Label three evidence grades:

1. **Conditional inventory replay:** “if this recorded eligible flow had touched the schedule.”
   Useful for arithmetic and stress, not demand estimation.
2. **Route-choice shadow:** reconstruct contemporaneous competitor routes and determine whether the
   candidate would have been eligible/competitive under stated latency. Still partial-equilibrium
   and subject to missing router state.
3. **Prospective installed-edge evidence:** actual external selections and landed effects. This is
   the only direct evidence of attraction, but acquiring it would require a separately authorized
   live experiment outside this lane.

Do not use importance weighting or a learned simulator outside logged support to manufacture
confidence. Unsupported states remain unsupported. Flow generated by household self-routing is
excluded from external-demand and fee-yield denominators.

### 12.4 Conservative execution assumptions

Shadow policies use exact size-specific quotes after the declared decision/build/send latency, not
the triggering mark. They include dynamic fees, impact, network/rent/transfer costs, capacity,
partial operation, route failure, and missing intervals. For LP paths, model funded bin inventory
and protocol rounding. A price that jumps across bins cannot receive fictional intermediate fills
unless retained on-chain evidence establishes them.

The terminal horizon is common across branches. The same liquidation route cannot simultaneously
assume access to owned liquidity in one branch and exclude it in another without declaring that
difference.

### 12.5 Measurements

Record at least:

- consolidated terminal-liquidated net PnL and named residuals;
- external-flow LP fees by asset, excluding self-routed accrual;
- gross `LVR_grid` or ITR and net service surplus, never double-counted;
- current, reachable, and terminal inventory by asset;
- time and magnitude outside the acceptable set;
- capital-time, reserve headroom, rejected-intent opportunity branches, and attention time;
- schedule churn, top-ups, withdrawals, action count, friction, and time out of service;
- quote/refusal freshness, route coverage, hypothetical landing/failure assumptions;
- fast episode results, flat intervals, runners, and re-entry separately from edge attribution;
- regime, narrative/correlation hypotheses, and coverage quality; and
- sensitivity to terminal horizon, reference route, latency, and fee/flow assumptions.

## 13. Scenario and adversarial matrix

| Scenario | Optionality / inventory pressure | Required policy behavior | Required measurement or refusal |
| --- | --- | --- | --- |
| slow monotonic X appreciation versus Y | X-offer slices surrender continuation; two-sided LP trends toward Y | respect maximum X sold; do not call fees sufficient by inspection | edge-traversal inventory, hold-X branch, terminal value, LVR/ITR |
| slow monotonic X collapse | Y-offer bins acquire weakening X | stop additions or retire when reachable X breaches acceptance | current/full-edge X, exit capacity, stressed terminal liquidation |
| high-frequency relative chop | two-sided schedule may repeatedly serve flow | preserve exact path, dynamic fees, and cumulative edit/hedge cost | external fees minus chosen adverse-selection and stabilization measure |
| jump across several bins | funded conversion may occur without observable intermediate hedge chance | no fabricated per-tick stabilizer or fill path | exact on-chain effects or explicit unsupported traversal ordering |
| correlation break / creator disavowal | apparently hedged assets fail asymmetrically | scenario limits override historical covariance | narrative exposure, one-leg-zero and liquidity-disappearance stress |
| both assets fall in USD with stable pair | pair statistics look benign while household reserve erodes | USD obligation constraint remains active | SOL and USD terminal views; dated-reserve coverage |
| toxic informed flow | router selects stale LP immediately before external move | pause/retire under predeclared signal; no hindsight cancellations | causal external reference, ITR or LVR, quote/receive clocks |
| benign external flow and competitive route | edge earns real service fees | distinguish external selection from household routing | external volume denominator and evidenced controlled fee accrual |
| household self-routes through owned bins | displayed LP fees rise without external revenue | count owned fee once as internal offset; maintain separate spot intent | gross fee, owned accrual, external leakage, consolidated wealth |
| volume drought / router exclusion | capital earns no service fee and stays exposed | slow pause/retirement review, not forced churn | capital-time, route coverage, opportunity branch, exit friction |
| fee profile or token extension changes | prior quote/action math may be invalid | refuse stale profile; require new policy version | exact profile/asset observations and typed unsupported state |
| active bin changes between observation and hypothetical landing | conversion surface differs from intent | invalidate or re-evaluate; never silently follow | intended/observed state identity and freshness closure |
| hedge route fails after LP acquires inventory | stabilizer cannot provide promised service | reachable state must remain acceptable without assumed hedge | no-hedge stress, unquotable residual, reserve/loss budget |
| crackle and rebalance reserve the same SOL | double spend or partial policy execution | coordinator exposes conflict and refuses one intent | simultaneous commitment calculation and stable intent IDs |
| remove succeeds, add/rebalance fails | household holds withdrawn basket and edge shape is incomplete | include every prefix state; no atomicity claim | partial-operation inventory, recovery path, action friction |
| withdrawal returns risky tokens | UI may mislabel retirement as exit | retain exposure until explicit landed sale | custody versus economic exposure and full-size liquidation quote |
| external manual wallet trade | policy attribution diverges from actual inventory | ledger advances; attribution becomes unknown/correctable | finalized effect and named reconciliation residual |
| finality rollback or delayed observation | apparent inventory/fee claim can disappear/change | keep provisional and finalized artifacts separate | superseding artifact, as-of vector, no mutation in place |
| pair orientation inversion | “stop selling SOL” can fund the opposite side | fail closed unless mint-direction sentence agrees | exact mint IDs and before/after edge inventory |
| all armed fast actions trigger during market fall | acceptable set can be breached despite each action passing alone | evaluate concurrent worst case | aggregate reservation and portfolio stress |
| terminal route unavailable | winning fee history cannot be converted to reserve asset | scalar performance remains partial/unknown | named unrouteable quantities; never mark-as-liquidation |

## 14. Invariants

### Accounting and valuation

1. One asset atom has one current custody location and one consolidated quantity effect.
2. Internal transfers, LP deposits/withdrawals, and the owned portion of self-routed fees cannot
   create consolidated PnL.
3. Principal, fee, reward, rent, and irreversible cost are separate components.
4. Current holdings equal independent finalized balances or expose an exact named residual.
5. An LP close or retirement is not a sale; residual tokens remain valued and risked.
6. Mark, quote, instruction bound, hypothetical effect, fill, and post-state remain distinct.
7. Every reference-unit result names a valuation manifest; missing liquidation legs do not become
   zero.
8. Net PnL, LVR, ITR, opportunity cost, and internal attribution are different estimands.
9. LVR and ITR are not both deducted unless their components are proven disjoint.
10. Episode/lot allocation cannot change consolidated terminal wealth.

### Inventory and control

11. Current and every materially reachable funded/armed inventory state are evaluated against the
    acceptable set.
12. Capital reservations assume all compatible armed actions may trigger; no double reservation.
13. Slow, medium, and fast policies retain separate version, cause, TTL, and action identity.
14. Unlike intents are never silently netted or relabeled.
15. Add/remove/rebalance defaults to no swap; a swap is a separate fast or explicit spot intent.
16. A schedule edit cannot claim deployed/UI support from pure modeled arithmetic.
17. A stale, conflicting, unsupported, or unquotable state produces visible refusal.
18. A repair exception demonstrably reduces a declared violation and cannot bypass another
    protected reserve or authority ceiling.
19. Fast episode transitions—partial realization, runner, zap, flat watch, and re-entry—remain
    intact even when the asset overlaps an edge.
20. No projection, shadow result, or policy recommendation carries signing or submission authority.

### Evaluation

21. Branches share starting state, causal cutoff, terminal horizon, and compatible liquidation
    method.
22. A shadow result cannot be called a fill or actual fee income.
23. Self-routed flow is excluded from evidence of external demand and external service revenue.
24. Unsupported route-choice counterfactuals cannot be extrapolated as observed volume.
25. Policies, thresholds, and regime partitions are frozen before the scored interval.
26. Re-running an identical branch produces the same canonical bytes and result/refusal.
27. Saved loss, avoided LVR, and opportunity cost never post to the actual ledger.

## 15. Failure modes this model must prevent

1. **Cycle cherry-picking:** moving start/end boundaries until inventory looks flat or profitable.
2. **LP-as-bond:** treating fee APR as return without inventory freight and terminal liquidation.
3. **Symmetry fiction:** assuming a finite-range LP remains balanced or delta-neutral.
4. **One-sided-option inversion:** calling an X-offer ladder downside insurance when it actually
   sells X continuation, or reversing asset orientation.
5. **Correlation camouflage:** paired assets appear diversified until one social narrative breaks.
6. **Stabilization alchemy:** internal edge-to-fast charges manufacture consolidated profit.
7. **Self-fee wash:** household flow creates owned LP fees and is counted as external yield.
8. **Double adverse-selection deduction:** LVR and ITR subtract the same loss twice.
9. **Best-alternative regret:** hindsight winner is used as opportunity cost.
10. **Residual deletion:** unavailable terminal routes make risky tokens disappear from PnL.
11. **Rebalance laundering:** a hidden swap or unbounded top-up is called maintenance.
12. **Book-level overspend:** slow, medium, and fast books each reserve the same wallet SOL.
13. **Name-based safety:** any withdrawal or hedge is presumed risk reducing without reachable-state
    analysis.
14. **Fast-policy capture:** every human crackle or zap is credited to LP stabilization after the
    outcome.
15. **Edge-demand hallucination:** all historical market volume is assumed to route through a
    counterfactual edge.
16. **Fictional jump fills:** a candle crossing several bins is treated as known per-bin volume.
17. **Fee configurability fiction:** observed pool fees are presented as operator-set controls.
18. **Half-transition blindness:** remove/add prerequisites and partial outcomes are modeled as one
    atomic rebalance.
19. **Provisional-final collapse:** fast observed state mutates finalized accounting truth.
20. **Policy overfitting:** bin shape and hedge triggers are tuned repeatedly on the scored path.

## 16. Smallest useful experiment

Run an instrument-only **joint policy shadow**, with no builders, signers, transaction submission,
or claim that the edge would have attracted flow.

### Preparation

1. Select one exact asset pair and one existing or historically observed DLMM position whose raw
   position/bin state can be reconstructed.
2. Reconcile the full controlled-domain quantities, including wallet, LP principal, fee/reward
   rights, rent, and unclassified residuals.
3. Ask Ember for an acceptable-inventory region in plain language, then translate it into exact
   scenario constraints and replay the translation back in mint-direction sentences.
4. Freeze one deliberately simple slow policy, one medium schedule policy, and one optional fast
   stabilization rule. Preserve Ember's independent crackle actions rather than forcing them into
   the stabilizer.
5. Predeclare the evaluation horizon, reference numeraires, terminal-liquidation manifest,
   external-flow definition, opportunity baseline, latency, and all go/no-go parameters below.

### Shadow procedure

1. At each coherent observation, emit current and lower/upper-edge inventory and constraint
   headroom.
2. Replay actual eligible flow when known. Label counterfactual eligibility and unknown route
   selection separately.
3. Produce independent medium and fast intents with stable IDs. Let the coordinator expose
   conflicts and reservations; execute neither.
4. Record exact state-conditioned quotes/refusals after the declared action latency.
5. Maintain branches for no-edge, unchanged schedule, medium policy, fast-only policy, and joint
   policy.
6. Attribute external versus self-routed fees, ITR or `LVR_grid`, stabilization cost, schedule
   friction, capital-time, and fast episodes without posting counterfactual values to the ledger.
7. Terminal-liquidate every branch at the common horizon. Preserve unrouteable legs and sensitivity
   to route/latency/horizon.
8. Review the inventory sentences and policy conflicts with Ember. Vocabulary corrections append a
   policy/perception version rather than rewriting the observation tape.

### What this experiment can establish

It can establish arithmetic closure, whether the three-clock policy is legible, whether schedules
express Ember's inventory intent, whether constraints refuse the right cases, and whether a
conditional joint surplus survives conservative costs on observed paths.

It cannot establish that an uninstalled edge would attract the replayed flow, that shadow actions
would land, or that profitability generalizes. Those require prospective evidence and, much later,
a separately authorized tiny-live design.

## 17. Go/no-go gates

There are two decisions: whether to continue instrumented shadow research and whether evidence is
strong enough to propose a separately reviewed live experiment. This document can only satisfy the
first.

### 17.1 Hard semantic and safety gates

All must pass; these are zero-tolerance conditions:

- zero unexplained mutation of finalized balances by classification or counterfactual code;
- zero duplicate reservation, unauthorized action, hidden swap, or silent intent netting across
  the adversarial corpus;
- zero self-routed owned fees classified as external revenue;
- zero mark-to-liquidation, withdrawal-to-sale, shadow-to-fill, or provisional-to-final coercion;
- 100% deterministic replay of exact inputs to identical output/refusal bytes;
- every affected asset reconciled exactly or visibly blocked by a named residual;
- every policy decision bound to a complete version/cutoff/freshness/authority manifest; and
- every scenario action remains inside the acceptable set or uses an explicit monotone repair
  exception.

Any failure is no-go regardless of apparent PnL.

### 17.2 Parameters that must be pinned before scoring

Do not invent favorable values after replay. Predeclare:

- `delta_edge`: minimum economically meaningful joint surplus per capital-time after attention and
  operational burden;
- `alpha`: confidence level and interval method compatible with serial dependence;
- `epsilon_inventory`: maximum acceptable upper confidence bound on time/probability outside the
  acceptable set;
- `B_loss`: maximum terminal-liquidated loss under each hard stress;
- `B_rebalance`: rolling turnover/friction/action ceiling;
- `B_capital`: maximum funded plus concurrently reserved capital;
- `epsilon_unknown`: maximum share of capital-time or terminal value with unknown/unquotable
  valuation before economics are declared inconclusive;
- `n_external` and effective-support rules for external routed events; and
- maximum operator attention/intervention burden per capital-time.

### 17.3 Economic continuation gate

Continue from arithmetic shadow to longer prospective shadow only if:

```text
lower_confidence_bound(JointEdgeSurplus / capital_time) > delta_edge
upper_confidence_bound(inventory violation rate)       <= epsilon_inventory
worst named stress terminal loss                       <= B_loss
observed rebalance use                                 <= B_rebalance
funded + reserved capital                              <= B_capital
unknown/unquotable share                               <= epsilon_unknown
```

In addition:

- the positive result survives terminal liquidation and at least the predeclared no-edge and
  liquid-SOL/hold alternative;
- it remains positive after excluding self-routed flow and all internal policy credits;
- it does not rely on adding both LVR and ITR as separate benefits/costs;
- sensitivity to plausible latency, fee, and route assumptions does not consume the margin;
- no single unmodeled tail observation dominates the conclusion; and
- contribution of edge, medium policy, fast-only policy, and their interaction is reported rather
  than assigned post hoc.

If data support is below `n_external`, the correct result is “economics not identified,” not go or
negative EV.

### 17.4 Gate to even proposing tiny live work

Shadow success is insufficient. A future proposal additionally needs:

- a coherent current source closure for position, bin, fee/reward, route, asset, and quote state;
- differential evidence for every protocol formula and modeled action actually in scope;
- independently validated transaction postconditions and partial-failure recovery;
- a signer/capability system, hard capital/authority ceilings, kill and cancellation semantics,
  and crash/restart reconciliation owned by a security lane;
- prospective route-choice evidence or an explicit tiny-live objective limited to measuring it;
- a precommitted loss budget whose loss is acceptable even if the edge earns no fees and the hedge
  route disappears; and
- a separate operator review that authorizes exact assets, program/profile, amounts, duration, and
  exit conditions.

This lane grants none of those authorities.

## 18. Connections to existing semantics

- **[Episode and accounting](../lanes/01_episode_accounting.md):** fast spot activity keeps the
  existing episode, inventory epoch, lot, basis-quality, partial realization, runner, exact-flat,
  watching-flat, and re-entry semantics. The separate
  **[crackle lane](../lanes/05_crackle_execution.md)** supplies the fast-policy state machine. Edge
  tenure and schedule version are orthogonal attribution dimensions.
- **[Exact accounting core](../engineering/20_numeric_accounting_core.md):** finalized wallet
  effects lead classification; multi-asset quantities, rational basis, cash recovery, and unknown
  incoming basis remain unchanged. LP custody is not a realization event.
- **[Market math](../../implementation/lanes/12_protocol_liquidity.md):** marks, size-specific
  state-conditioned quotes/refusals, instruction bounds, and full-position quote projections
  remain distinct. A quote is not landed execution or causal price impact.
- **[Liquidity kernel](../../implementation/lanes/12_protocol_liquidity.md):** position/bin
  inventory, principal versus fee/reward accrual, add/remove, in-place rebalance versus close/reopen,
  chunk constraints, and explicit unsupported fields are the schedule substrate. Every current
  action result is modeled-only.
- **[Projection](../../implementation/lanes/15_projection.md):** Glass receives exact asset
  definitions, atomic/rational readings, evidence, freshness, coverage, residuals, result digest,
  and the literal `read_only_no_execution` authority. Latent estimates and operator perception
  require separate artifacts.
- **[Portfolio controls](../lanes/06_portfolio_lp.md):** one consolidated balance sheet, current and
  contingent exposure, reserve coverage, narrative concentration, and simultaneous reservations
  govern all books.

## 19. Open research decisions

- What exact external-flow evidence can distinguish route eligibility, router selection, and
  landed use without inferring from aggregate pool volume?
- Which external reference route should define ITR when routes share the same underlying pool or
  owned liquidity?
- Is event-grid LVR useful for these finite ladders, or is size-specific ITR plus terminal branch
  comparison more interpretable?
- How should an acceptable-inventory set be elicited visually without pretending Ember thinks in
  atomic inequalities?
- Which fast actions are independent crackles, which are genuine stabilization services, and when
  may one action receive both attributions prospectively?
- How should LP fee rights be recognized when fee-growth derivation or reward transfer semantics
  are unsupported?
- Which correlation/narrative stresses are important enough to be hard controls rather than
  analytical overlays?
- Can an in-place rebalance be independently decoded and simulated well enough to dominate a
  remove/add sequence after partial-failure risk?
- What amount of external event support is sufficient when flow is clustered, adversarial, and
  regime-dependent?
- What should retirement mean when withdrawal is safe but terminal liquidation is unavailable?

## Decision boundary

Do not optimize bin widths, install an edge, or automate stabilization from this document. First
show that one exact accounting projection can carry the three policy clocks without double-using
inventory, that the operator recognizes the finite-bin optionality and pair orientation, and that
the shadow waterfalls reconcile under adversarial paths. Only then is it rational to decide whether
routed liquidity deserves a longer prospective study.
