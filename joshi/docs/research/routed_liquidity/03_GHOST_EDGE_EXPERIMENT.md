# Ghost-edge experiment: when would hypothetical liquidity enter a route?

Status: proposed read-only study. No pool deployment, transaction construction, signing, routing
integration, or capital authority.

## 1. Question, estimand, and non-claim

Ember's hypothesis is narrower and more interesting than “LPs earn fees”:

> A nonlinear A/B liquidity schedule may be uncompetitive in most of the market but become part of
> a best route in particular state × direction × size regions.

A **ghost edge** is a versioned hypothetical quote operator with explicit inventory and fee rules.
It is inserted into a frozen, point-in-time copy of the route graph, never advertised to a router
and never deployed. The primary estimand is the **mechanical activation surface**:

```text
G(state cut, pair, direction, input atoms, ghost state, schedule, route policy)
  = best net output with ghost - best net output without ghost
```

The edge is active when a deterministic route search allocates it nonzero flow and `G > 0` after
all modeled fees and transfer costs. Report the winning margin in output atoms as well as the
indicator. “Jupiter-competitive” means competitive against a contemporaneous, witnessed Jupiter
quote or against an offline route atlas first demonstrated to reproduce the witnessed route and
leg arithmetic. It never means that Jupiter would actually discover, retain, or send order flow to
an undeployed pool.

This is not a causal counterfactual. Adding a venue can change router discovery, users' orders,
arbitrage, competing liquidity, MEV, token attention, and the state process itself. Historical
replay can establish where the proposed edge was mechanically useful under stated assumptions. It
cannot establish the order flow, fee income, or PnL that would have occurred.

The smallest credible study has two products:

1. **isolated activation atlas** — reset the ghost state for every quote and map local
   state × direction × size competitiveness; and
2. **sequential shadow inventory** — process a preregistered demand sequence, update ghost
   inventory after each accepted shadow route, and expose path dependence and terminal risk.

The first may proceed once quote parity is exact. The second may proceed only after the first has
identified a small, frozen schedule family and after its ordering assumptions are registered.

## 2. Atomic study unit

One `GhostRouteCut` binds all of the following, by identity and digest:

- pair `(asset_a_id, asset_b_id)` with mint/program identities, decimals, token extensions, and
  exact atom domains;
- direction and exact input atoms; exact-output requests are a separate size semantic;
- a route-state snapshot at one chain commitment/slot range and one wall-clock knowledge cut;
- all competing edge states and protocol profiles admitted to that route search;
- one ghost schedule version and its inventory immediately before the request;
- one route-search implementation/configuration and one cost/transfer model;
- an optional Jupiter quote occurrence made for the same assets, direction, size, slippage mode,
  and sufficiently close state cut;
- a complete coverage vector, including absent edges and refusals; and
- output route, leg quantities, fees, terminal ghost inventory, and all assumption/scenario IDs.

Do not key the study by minute bars or displayed price. One route cut can have several sizes and
schedules, but each result must retain the exact shared state identity. A later quote, correction,
or account version creates another occurrence even when the numeric values happen to match.

## 3. Exact required inputs

### 3.1 Point-in-time route atlas

The study consumes the lane-01 route-atlas/state-cut product rather than reconstructing venue
state from charts. For every admitted venue edge it needs:

- venue, pool/market, asset pair, direction, program/profile/version, and lifecycle state;
- raw state observation IDs/digests, account hashes, slots, commitment, and coherent-read proof;
- exact reserves, bins/ticks/order levels and capacities needed by the native quote operator;
- every fee component, fee side, transfer fee/hook, minimums, rounding rule, and partial-fill rule;
- quote availability/refusal reason, freshness/expiry, and coverage scope/window/gap identities;
- edge discovery provenance, including why a venue known to the census is absent from the route
  graph; and
- gas/priority/rent costs only where they are actually attributable to the hypothetical quote.

Economic integers cross boundaries as decimal strings or the canonical wide Arrow decimals. The
study must not narrow canonical `u64`, `u128`, or signed-atom domains into Python/SQL `int64`. An
out-of-range value is a typed refusal and an adversarial fixture, never a cast.

### 3.2 Witnessed Jupiter comparator

Each prospective comparator stores the request and response bytes or canonical lossless
projection; quote occurrence ID; request/response availability times; router/API/build identity;
context slot; input/output/threshold atoms; route plan and allocation percentages; per-leg venue,
mint, amount and fee fields; price-impact metadata as metadata rather than truth; latency; and
coverage/refusal status. A Jupiter response without a sufficiently bounded state relationship is a
separate observation, not a golden target.

Historical Jupiter quotes generally cannot be recreated from current APIs. Dense historical work
therefore uses the manifested offline atlas; sparse prospectively captured Jupiter quotes calibrate
coverage and route parity. The API is not called once per ghost schedule.

### 3.3 Ghost schedule

`GhostScheduleSpec/v1` is immutable and contains:

- asset pair and permitted directions;
- schedule family and formula/profile version;
- initial A and B atoms and a hard inventory/capital budget;
- price-support domain and exact piecewise parameters (for example bins/segments), with no
  interpolation left to a plotting library;
- swap and protocol fee schedule, fee side, rounding and minimum output;
- per-request and cumulative capacity constraints;
- behavior at depleted segments, partial-fill rule, and refusal taxonomy;
- inventory update function and invariant checks;
- repricing/arbitrage scenario ID; and
- specification digest and the preregistered parameter-search family from which it came.

V1 should compare only a few interpretable families: constant-product matched to the same initial
capital, a symmetric piecewise/bin schedule, and an asymmetric schedule with independently chosen
A→B and B→A support. A flexible optimizer is intentionally absent. If thousands of knot locations
are searched until one wins, the output is model selection, not evidence for a liquidity shape.

## 4. Knowledge time, event time, and coverage

Every input relation is bitemporal:

```text
valid interval / slot interval: when the fact applied on chain
available_at + catalog_commit: when Joshi could have used it
supersession/retraction: whether that version remained the selected as-known version
```

A route cut is valid only if all selected state versions cover the requested event time/slot, were
available by the cut, were not retracted by the cut, and satisfy the route-atlas coherent-read
rule. The manifest closes source cursors, chain bounds, projection versions/state digests, and the
maximum availability time. Quotes, routes, outcomes, and later markouts each have their own
availability cutoff.

Coverage states are at least `observed_complete`, `observed_partial`, `known_absent`,
`source_gap`, `stale`, `provider_conflict`, `unsupported_profile`, and `numeric_refusal`. Missing
edges are not zero liquidity. A route is not called globally best when the competing universe is
partial. Report activation under the observed subgraph and retain a distinct `universe_complete`
flag. The study never forward-fills through a source gap, migration boundary, pool upgrade,
Token-2022 fee epoch, or topology change.

Route and result manifests must name the source snapshot ID/logical digest, atlas build and
configuration digest, quote-operator registry digest, schedule digest, state cut, coverage
window/gap IDs, and the exact eligible input closure. Artifact occurrence IDs remain distinct from
content digests.

## 5. Size grid and candidate-pair enrollment

### 5.1 Route quote sizes

For each pair and direction, construct the size grid using information available at enrollment:

1. exact operator-relevant sizes Ember would contemplate, expressed in input atoms;
2. a `1, 2, 5 × 10^k` log grid across the predeclared budget domain;
3. reserve/depth fractions derived only from the current cut, capped before a route can consume an
   unsafe fraction of witnessed capacity;
4. one-atom neighbors around native bin, tick, capacity, minimum-output, and fee-tier boundaries;
5. the ghost schedule's segment boundaries; and
6. an explicit one-atom case to expose rounding pathologies.

Deduplicate exact atom sizes and record why each size is present. Use both directions. Never create
new grid points after looking at future activation or PnL. Do not compare different quote assets by
their raw atom counts; use asset identity and a separately witnessed valuation when aggregation is
needed.

### 5.2 Pair selection without outcome leakage

At an enrollment time, form the candidate universe from the contemporaneous census, then apply
only registered eligibility facts: supported token programs/profiles; sufficient state coverage;
minimum observed route activity/depth; lifecycle stratum; quote-asset stratum; and capital/risk
ceiling. Sample or stratify across high/low route concentration, lifecycle, depth, volatility, and
existing venue count. Retain every eligible pair and the selection probability even if only a
budgeted subset is simulated.

Do not select pairs because they later routed well, had high future volume, survived, migrated,
sent, or would have paid the ghost. Do not use a future “top pairs” table to backfill the historical
universe. A pair remains in its enrolled cohort through delisting, failure, or disappearance;
those are outcomes/censoring, not reasons to erase it.

The discovery cohort may be used to narrow schedule families. The confirmatory cohort and dates
are then frozen, and no pair, size, parameter, repricing rule, or stop threshold moves in response
to confirmatory results.

## 6. Quote and routing mechanics

### 6.1 Venue-native operators

Each existing edge is evaluated by the exact profile-pinned native operator from Joshi protocol
contracts. Pump/PumpSwap constant-product arithmetic, DLMM traversal, fee ordering, transfer fees,
capacity, and rounding remain venue semantics. A generic smooth approximation is never substituted
inside the main comparison. Unsupported exact-in/exact-out forms refuse rather than invert an
unrelated operator.

Compose a path leg by leg in atoms: output of leg `i` is input to leg `i+1`, after the correct fee
and transfer treatment. If a path uses the same stateful edge twice, the second use sees the first
use's copied state. Enumerate only registered path lengths, intermediate assets, split rules, and
cycle prohibitions. Route tie-breaking is deterministic and versioned.

Before ghost work starts, differential fixtures must show that the offline atlas exactly
reproduces the amount and leg arithmetic of supported direct paths and explains supported Jupiter
route-plan differences. Any unexplained one-atom mismatch blocks the affected profile.

### 6.2 Isolated activation

For each cut/direction/size:

1. find the best admissible baseline route and its net output;
2. clone the same graph, insert one schedule/state ghost edge, and rerun the same search;
3. report whether the ghost carries flow, its share of a split route, and the net-output margin;
4. solve, by exact bounded search, the maximum additional ghost fee that leaves the chosen route
   weakly competitive; and
5. discard neither refusals nor cases where another edge is unobserved.

The ghost resets to its registered initial inventory for every isolated quote. These rows map
local opportunity; their fees cannot be summed into a portfolio return.

### 6.3 Sequential shadow inventory

The sequential experiment has a distinct manifest and consumes only a sequence fixed before its
outcomes are evaluated. Suitable demand sources are prospectively witnessed operator quote intents
or a preregistered sample of market swaps translated into exact input intents. Preserve original
order and timestamps.

At request `j`, route against ghost inventory `I[j]`. If the registered shadow policy chooses a
route using the ghost, apply all leg transitions to copied states, record fees and transferred
inventory, and set `I[j+1]`. Otherwise inventory is unchanged. Never reset depleted inventory
inside a run. Two traces with opposite direction/order are different experiments.

The study must report two external-state treatments:

- **observed-external replay:** competing venues refresh from their next witnessed state while
  only the ghost retains counterfactual inventory. This is useful but internally inconsistent if
  displaced flow materially affected those observed states.
- **coupled copied-state replay:** chosen shadow routes update every copied venue they touch;
  unrelated witnessed market events are then injected under an explicit ordering rule. This is
  mechanically coherent but still treats public demand as exogenous.

Disagreement is a model-risk interval, not an invitation to pick the favorable trace.

## 7. Repricing, arbitrage, route endogeneity, and ordering

Run at least these preregistered ghost-state scenarios:

1. **No arbitrage until next request.** Inventory moves only through shadow demand. This exposes
   maximum drift and is not a realistic profitability forecast.
2. **Instant frictionless projection.** After each fill, a hypothetical arbitrage trade projects
   the ghost marginal price to the contemporaneous reference band. This is an optimistic liquidity
   bound and often a pessimistic LVR bound.
3. **Bounded arbitrage queue.** Arbitrage arrives after a registered latency distribution, pays
   route and priority costs, has a capacity cap, and acts only when executable profit is positive.
4. **Adverse repricing stress.** The next observed reference innovation is ordered before the
   provider's favorable flow when timing is unresolved.

Reference prices are size-specific routed liquidation/acquisition quotes where available, not
chart marks. Arbitrage transfers and fees are itemized separately from organic shadow requests.
Repricing never creates inventory or value without a balancing trade.

Adding a real edge is endogenous: it can alter router topology, split optimization, arbitrage
attention, sandwich incentives, competing LP response, and even demand. Consequently report all
results as fixed-demand mechanical simulations. Do not write “orders would have routed” or “the LP
would have earned.” The truthful statement is “this registered router selected the ghost when
replaying these fixed intents against this state model.”

For same-slot or weakly timed events, evaluate a bounded ordering set: observed order when known;
ghost request before/after external swap; arbitrage before/after; and fee/reprice before/after when
the protocol permits it. Cap factorial explosion with registered partial-order constraints. Report
best, worst, and central registered ordering. Sandwich/backrun proceeds are not assumed available
to the LP. Known MEV transactions may be injected as external events; unknown MEV is an uncertainty
scenario, not zero.

## 8. Outputs

### 8.1 Activation atlas

Emit one row per cut × direction × size × schedule × scenario with:

- baseline and ghost route identities and complete leg lists;
- baseline/ghost net output atoms and activation margin atoms;
- active indicator, ghost input/output atoms, split-route share in ppm, and capacity used;
- maximum competitive **fee premium** in exact bps/atoms under a named search convention;
- route-universe completeness, quote freshness, refusal, and coverage identities;
- local state descriptors known at the cut (inventory imbalance, witnessed depth, volatility
  window, lifecycle/topology stratum), never future labels; and
- estimator/build/config/input/schedule digests and restrictive mechanical-simulation claim scope.

Plot activation as separate A→B and B→A state × log-size surfaces. Never average directions or
sizes into one “edge quality” score.

### 8.2 Sequential book

For every event and terminal checkpoint emit:

- chosen route and ghost route share;
- pre/post A and B inventory, inventory transferred by direction, and schedule segment occupancy;
- gross fees by asset, arbitrage flows, external flows, and rejected/depleted requests;
- executable adverse markouts at preregistered horizons with their own availability and censoring;
- **toxicity** as signed post-fill executable reference movement conditional on direction, with
  horizon and unit named;
- **LVR-like model diagnostic** as the difference between registered continuous-rebalancing
  reference value and the discrete ghost trace, explicitly scenario-dependent and not accounting
  PnL;
- opportunity cost versus the matched-capital baselines; and
- terminal liquidation quotes in both assets, residual unliquidatable inventory, all costs, and
  liquidation coverage. No mark-to-mid substitutes for terminal executable value.

Aggregate by pair, week, regime, direction, size band, and schedule only after retaining row-level
results. Report ghost route share separately by eligible-request count, same-asset input volume,
and within-request split allocation; never aggregate unlike asset atoms without a witnessed
valuation. Show concentration: one pair or one brief event must not masquerade as a general
surface.

## 9. Baselines and falsifiers

Run these simple baselines before any fitted nonlinear schedule:

- no ghost edge;
- matched-capital constant product with the same fee and initial reference price;
- symmetric uniform/bin liquidity across the registered support;
- a flat reference-price RFQ with a hard inventory cap (diagnostic only);
- the best already-observed direct venue and the complete route-atlas best path;
- zero-fee ghost, which bounds whether geometry can matter at all; and
- shuffled state cuts/directions as a negative control for spurious activation maps.

Counterexamples the experiment must contain include:

- a schedule that appears competitive only because an edge is missing from the atlas;
- one-atom rounding activation that disappears at every economically relevant size;
- A→B activation followed by depletion and no B→A recovery;
- high nominal fee income overwhelmed by adverse repricing and terminal liquidation;
- a split path that violates edge capacity when legs are evaluated independently;
- a path that wins only under mixed-slot venue state;
- a ghost that wins isolated quotes but loses after sequential inventory updates;
- a result reversed by reasonable arbitrage latency/order scenarios;
- a schedule selected on future-volume survivors that fails in a true enrollment cohort; and
- an `int64` narrowing case that must refuse the Python prototype rather than wrap or truncate.

Falsify the practical hypothesis if activation disappears under complete universes and exact
operators; exists only below usable minimum size; requires fees below cost; is confined to a single
future-selected pair; cannot survive sequential inventory/terminal liquidation; or changes sign
under every plausible ordering/repricing scenario. A null is informative only after the eligible
state, size, direction, and schedule support are documented.

## 10. Historical and prospective phases

Historical work is exploratory. Use only state and demand tapes whose coverage is manifested, and
freeze an enrollment cutoff before deriving future outcomes. It may eliminate broken schedules,
identify unsupported protocols, and set compute budgets. It may not supply the confirmatory claim.

Prospective work preregisters pair universe, schedule specs, size grid, route policy, state-cut
cadence/event trigger, repricing/order scenarios, exclusions, coverage threshold, and stop/go
criteria. Capture sparse live Jupiter comparators and the full atlas inputs as they occur. Seal raw
days before running outcome joins. Hold back at least the final nonoverlapping time block and a
pair-level subset so neither temporal persistence nor one token family is mistaken for
generalization.

## 11. Staged sample and compute/storage envelope

`N` below means an eligible coherent route cut delivered by lane 01, not every observed slot. The
upper-bound evaluation count is approximately:

```text
N × 2 directions × size count × schedule count × repricing/order scenarios
```

Baseline route caching and pruning may reduce work but must not alter results. Derived rows are
expected to occupy roughly 0.1–0.5 KiB each in columnar form depending on retained leg detail; raw
state/Jupiter evidence is budgeted separately and never discarded to meet this estimate.

| Gate | Scope | Maximum dense evaluations | Derived envelope | Decision |
| --- | --- | ---: | ---: | --- |
| 1 day | 3 pairs; ≤500 cuts; 12 sizes; 6 schedules; 3 scenarios | 216,000 | ~0.02–0.11 GiB plus raw evidence | arithmetic, schema, coverage and route-parity shakeout |
| 7 days | ≤12 pairs; ≤10,000 cuts; 16 sizes; 8 schedules; 4 scenarios | 10.24 million | ~1–5 GiB | find whether stable activation regions exist and shortlist ≤6 schedules |
| 30 days | ≤30 pairs; ≤60,000 cuts; 16 sizes; ≤6 schedules; 5 scenarios | 57.6 million | ~6–29 GiB | exploratory sequential inventory and parameter freeze |
| 90 days | frozen prospective cohort; ≤180,000 cuts; 16 sizes; ≤3 schedules; 5 scenarios | 86.4 million | ~9–43 GiB | confirmatory mechanical robustness and live-test eligibility review |

These are hard caps, not collection targets. If lane 01 yields fewer complete cuts, report lower
support. If it yields more, stratified deterministic sampling preserves enrollment probabilities.
Run exact native quote operators in bounded local workers over immutable Parquet snapshots; write
partitioned results by experiment/pair/day and a compact manifest/index. Jupiter calls remain a
sparse prospective calibration stream. No GPU, vector database, online model service, or
operational-store write is warranted.

Sequential replays are more expensive and should consume only the shortlisted schedules: at most
10,000, 100,000, and 500,000 demand events at the 7/30/90-day gates respectively, each under the
registered ordering scenarios. Checkpoint copied inventory/state so replay remains deterministic;
never checkpoint over an unclosed gap.

## 12. Stop/go gates

### Stop before seven days

Stop the affected profile immediately for any unexplained one-atom native/Jupiter leg mismatch,
mixed-state acceptance, silent partial fill, numeric narrowing, nonreproducible manifest, or missing
competing-path coverage. Stop the whole experiment if the lane-01 atlas cannot produce coherent
as-known cuts and exact refusal/coverage semantics.

### Go from 1 to 7 days

Proceed only with zero unexplained arithmetic mismatches; deterministic replay hashes; successful
wide-integer refusal fixtures; all candidate pairs enrolled without future facts; and at least two
directions and economically relevant sizes represented. This authorizes more shadow computation,
nothing else.

### Go from 7 to 30 days

Proceed only if activation with positive net-output margin appears in complete route universes,
survives the matched-capital constant-product and uniform/bin baselines, occurs above the usable
minimum size, and repeats across at least three pairs and two nonoverlapping time blocks. Freeze no
more than six schedules. Otherwise stop or redesign the hypothesis before adding complexity.

### Go from 30 to 90 days

Proceed only if shortlisted schedules retain activation after sequential inventory, explicit
arbitrage/repricing, ordering stress, all costs, and terminal executable liquidation; no single pair
contributes more than half of aggregate simulated surplus; and missing/unsupported cuts cannot
reverse the result under the registered worst bound. Freeze the prospective cohort, schedules,
scenarios, metrics, and thresholds before opening the 90-day data.

### Eligibility review before any live pool

The 90-day result can at most make a separately authorized, capped live experiment eligible. It
does so only if the held-out period and held-out pairs reproduce a nontrivial activation region;
the lower registered uncertainty/sensitivity bound on aggregate terminal-liquidated simulated
surplus is positive in both observed-external and coupled-state treatments; activation is not
rounding-, gap-, or single-regime-driven; inventory and worst-scenario liquidation remain inside a
predeclared loss/capital budget; and exact deployed-program, transaction, custody, monitoring,
legal, MEV, and emergency-exit reviews are complete.

Failure means stop, not tune on the holdout. Passing is not permission to deploy. Any live pool
would need a new protocol/profile conformance study, explicit wallet authority, human approval,
tiny capital, abort controls, accounting reconciliation, and a design that treats its own order
flow and competitors' response as newly observed—not as facts proven by this ghost replay.
