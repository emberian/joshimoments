# Transfer limits

## Rule of transfer

Transfer the **question and decomposition** before transferring an equation.

The book's equations usually assume a centralized continuous double auction with standing orders,
best queues, a bid–ask spread, price-time priority, anonymous aggressive orders, and a statistical
regime long enough to estimate stationary responses. Pump bonding curves, PumpSwap, Meteora DLMM,
Solana transaction ordering, retail social attention, and Ember's management process alter those
assumptions in different ways.

Three transfer labels are used:

- **direct concept:** definition or epistemic distinction survives after typing the venue;
- **analogue requiring derivation:** economic idea survives but the state/equation must be rebuilt;
- **invalid direct transfer:** source variable or mechanism is absent.

## Venue comparison

| source-book assumption/object | LOB | Pump bonding curve | PumpSwap | Meteora DLMM | consequence |
| --- | --- | --- | --- | --- | --- |
| standing bid and ask queues | yes | no | no | no conventional queues | `bid`, `ask`, `spread`, and queue imbalance are not universal fields |
| price-time queue priority | common | absent | absent | LP share/bin mechanics, not FIFO order priority | Chs. 5–7, 17, and 21 queue formulas do not transfer |
| aggressive order consumes displayed depth | yes | swap changes virtual/real reserve state | swap traverses constant-product reserve state | swap traverses active/discrete bins | exact-size curve traversal replaces queue depletion |
| passive provider chooses a quote | usually | protocol curve supplies terms | LP deposits into pool curve | LP chooses range/bin distribution and protocol supplies execution | provider control and adverse selection differ materially |
| spread is best ask minus best bid | yes | no | no | no direct LOB spread | use directional quotes, fees, round-trip loss, and route impact separately |
| one centralized matching sequence | exchange event sequence | Solana instruction/transaction order | Solana transaction order plus pool state | Solana order plus bin traversal | slot/landing/MEV and atomicity must enter |
| cancellation event | standing order removed | not analogous | LP add/remove changes reserves | bin liquidity add/remove/rebalance | define protocol-native liquidity edit events |
| visible book approximates current supply schedule | locally | reserve formula is public state | pool reserves are public state | bins encode current deployed liquidity | future trades/LP edits/routes remain latent even when state is public |
| fixed venue through sample | often | lifecycle ends/migrates | may receive migrated liquidity/routing | pools/ranges can change | lifecycle is a first-class regime boundary |

## Pump bonding curves

### What transfers directly

- exact pre-event state and exact-size response must be recorded;
- observed post-trade response is not causal reaction;
- event-time signed flow and wall-time intensity are valid study objects;
- parent-flow splitting/herding is an empirical question; and
- mark, quote, fill, and liquidation are different.

### What requires a new derivation

The local impact of one trade is determined by the deployed integer reserve/fee formula and exact
state. A source-book response function can then study **subsequent** market adaptation, but it must
first subtract or condition on deterministic curve movement. Possible state variables include
virtual/real reserves, fraction of curve completed, fee tier/mode, trade size relative to reserves,
recent signed flow, unique wallets, and time to migration.

### What is invalid

- queue imbalance `V_b/(V_a+V_b)`;
- one-tick queue depletion races;
- time priority at the best;
- half-spread provider gain; and
- Fokker–Planck queue depletion with LOB reinjection.

The curve's migration is a structural break, not an ordinary large price move.

## PumpSwap and routed AMM execution

### What transfers directly

- size-dependent cost and impact-adjusted valuation;
- signed-flow persistence and state-conditioned observed response;
- impact path/decay as descriptive outcomes;
- execution shortfall from decision state to landed asset effect; and
- no-profitable-uninformed-round-trip as a simulator sanity check after fees.

### What requires a new derivation

PumpSwap's reserve geometry, virtual quote reserve, fee configuration, canonical/noncanonical pool
rules, Token-2022 behavior, and route choice define the instantaneous quote. A propagator study must
model residual response after this deterministic transformation and after competing state changes
during landing delay.

The closest analogue to `spread` is not one number. It is a tuple:

```text
buy quote cost
sell quote proceeds
protocol/LP/creator/transfer fees
size impact
round-trip state change
route difference
landing and MEV uncertainty
```

### What is invalid

- treating the pool marginal price as both bid and ask;
- using LOB volume-at-best as reserve depth;
- mapping an LP token/share to queue position; and
- applying square-root impact to the protocol's instantaneous curve in place of exact arithmetic.

## Meteora DLMM

### What transfers directly

The economic decomposition of liquidity provision is highly relevant:

```text
fee income
- adverse inventory transformation
- rebalancing and withdrawal cost
- network/routing cost
- residual token risk
- opportunity cost.
```

Impact-adjusted portfolio value, correlated provider withdrawal, and state-dependent liquidity are
also direct questions.

### What requires a new derivation

DLMM liquidity is distributed across discrete price bins. Exact inventory and fee state depend on
active bin, per-bin shares/reserves, bin step, dynamic fees, token program, and traversal. A bin can
serve as a **price bucket** analogue, but not as a FIFO best queue. LPs sharing a bin do not inherit
the source book's queue-position economics.

An LP “rebalance” is not one source-book cancellation plus new limit order. It can involve removal,
custody changes, new bin allocation, possible swaps, network cost, and a changed contingent token
schedule. Each effect must be explicit.

### What is invalid

- half-spread minus response as a complete LP P&L;
- large-tick top-priority profitability;
- queue imbalance and first-depletion probability;
- assuming fee capture implies economic gain; and
- valuing the LP at current aggregate mark without withdrawal and leg liquidation.

## Solana latency, ordering, and MEV

The source book mostly treats an ordered exchange event stream and execution at model time. Solana
adds:

- observation through RPC/indexer/provider with distinct availability;
- transaction construction/simulation state;
- priority fee, compute limits, tips, and route choice;
- send time, leader/slot ordering, landing, possible failure, and finality;
- atomic multi-instruction effects and ambiguous bundles;
- competing transactions that change pool state before landing;
- validator/searcher ordering and sandwich/backrun risk; and
- forks, replay/backfill, and provider gaps.

Therefore `T`, event order, and execution price must be expanded into a clock/state vector. A
shadow order evaluated at observation state is not a fill. A transaction that fails can still pay
fees. A later transaction with the same parameters is not the book's missing counterfactual world.

**Transfer status:** execution shortfall and causal-impact distinctions transfer directly; LOB fill
probability, queue position, and continuous-time scheduling equations require new models.

## Retail social dynamics and platform attention

### Plausible transfers

- point processes for trade/social/creator events;
- multivariate intensity and excitation as predictive models;
- self-referential crowd behavior;
- long-memory flow and herding-versus-splitting questions;
- feedback loops between price movement, attention, and liquidity; and
- ecological participant roles rather than one representative trader.

### Stronger confounds than the source setting

- Pump ranking and recommendation algorithms alter what is seen;
- Ember's viewport and inspection select a tiny endogenous subset;
- creators, callouts, communities, wallets, and humans have uncertain temporal identity;
- posts/metadata can edit or disappear;
- launch, creator claim, fee routing, CTO, livestream, and moderation events have different
  meanings;
- platform-wide trends and coordinated campaigns create common causes;
- bots, routers, sybils, and multi-wallet actors break participant counts; and
- social data access/retention can be incomplete or legally constrained.

A Hawkes cross-kernel from callout to trades can mean causation, anticipation, common ranking,
shared news, or selection into a hot scope. Near-criticality can mean nonstationary launches. JOSHI
must use availability-time controls, negative controls, source-health intervals, and product
surface/choice-set evidence before attaching a social story.

**Invalid direct transfer:** interpreting branching ratio as fraction of socially caused trades or
calling a fitted event kernel “community propagation.”

## Ember's episode, runner, and re-entry process

The book's execution theory typically assumes a parent objective `Q` and horizon `T` are fixed, then
optimizes child execution. Ember's process can revise the objective:

- enter for a small crackle;
- observe new evidence and retain more exposure;
- take partial profit and keep a runner;
- fully exit while attention continues;
- re-enter after a later scene; or
- rotate SOL toward another opportunity.

This creates two state machines:

```text
operator episode: attention/intent continuity
inventory epoch: flat-to-flat asset/basis continuity
```

One episode can contain multiple inventory epochs. One inventory epoch can contain several
management tranches. A parent-metaorder label is appropriate only for a prospectively intended
execution sequence, not the whole episode.

### Direct transfers

- execution costs are path dependent;
- action speed trades impact against signal decay/opportunity;
- partial size changes impact and residual risk;
- historical phantom actions need market-reaction modeling; and
- full-size liquidation, not mark, is the exposure value.

### New JOSHI objects

- stance/disposition and its revision;
- episode scene and choice set;
- partial realization plus runner;
- exact-flat watch interval;
- re-entry with fresh accounting basis;
- opportunity set/competing SOL allocation; and
- operator override as part of the composite policy.

The book cannot answer whether Ember's discretionary revisions are valuable. It tells us how not to
erase them while measuring.

## Result-by-result transfer table

| source result | transfer status | JOSHI use |
| --- | --- | --- |
| Variogram/signature plot | direct after price typing | diagnose scale and microstructure noise separately for mark, marginal, quote, and fill |
| Hawkes event intensity | analogue requiring coverage/causal controls | held-out event-rate forecast, not causal social label |
| Long-memory signed flow | direct question, new participant model | lifecycle/wallet/route-conditioned ACF and prediction |
| Queue imbalance predicts next depletion | invalid on AMMs | no use until a genuinely two-sided executable-depth analogue is defined |
| Fokker–Planck queue dynamics | invalid directly; method transfers | protocol-native state transitions and jump processes |
| Observed = reaction + prediction | direct causal identity | mandatory study labels and counterfactual uncertainty |
| Concave single-order response | analogue requiring exact curve subtraction | state-conditioned post-trade response |
| Square-root metaorder impact | baseline to challenge | compare against exact AMM curve plus later adaptation; never replace quote math |
| Propagator diffusive balance | analogue, regime-dependent | test whether persistent flow is offset by adaptive liquidity/arbitrage |
| Asymmetric liquidity | analogue requiring event/state semantics | expected-versus-surprising event response |
| Kyle lambda | invalid as universal coefficient | optional local descriptive slope only |
| MRR half-spread relations | invalid mechanically on AMMs | conceptual break-even comparator for provider economics |
| Market-making P&L decomposition | direct economic concept | LP fee/selection/inventory/liquidation waterfall |
| Latent V-shaped liquidity | model analogy | scenario model for future supply, never current fact |
| Nonnegative closed-loop impact cost | simulator invariant analogue | reject counterfactual engines that create frictionless mechanical profit |
| Optimal execution schedules | new derivation required | inform later manual/automated scheduling only after actual impact/fill calibration |
| Mark-to-market fragility | direct | exposure and risk use exact-size liquidation/stress |

## Conditions that forbid transfer

Stop using a source-book result for a given study when any of these holds:

1. its defining object does not exist on the venue;
2. the result is smaller than quote/fill/source error;
3. lifecycle changes dominate the supposed stationary regime;
4. adaptive hot-scope selection destroys the denominator;
5. participant identity is inferred from a mutable wallet/profile join;
6. the event time is observed after the decision but backdated to its occurrence;
7. the counterfactual assumes the changed trade leaves later state unchanged;
8. the source formula and the empirical response are collapsed;
9. LP revenue omits residual inventory/liquidation; or
10. a fitted descriptive model is promoted because its vocabulary sounds causal.

