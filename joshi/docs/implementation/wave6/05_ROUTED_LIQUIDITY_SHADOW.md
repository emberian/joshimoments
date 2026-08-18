# Wave 6 — routed-liquidity shadow study

Status: **implemented as an isolated, pure-Python research instrument**
Authority: **read-only / counterfactual; no network, builder, signer, submitter, or live-pool path**

## Outcome

Wave 6 now has a deterministic reference reducer for a narrow question:

> Given a fixed sequence of exact input intents, a coherent direct-venue atlas, an immutable
> finite-bin ghost schedule, and registered routing/arbitrage assumptions, when does the copied
> route policy select the ghost and what inventory, fee rights, diagnostics, and terminal branch
> value follow mechanically?

The implementation is under
[`analysis/src/joshi_analysis/wave6_routed_shadow`](../../../analysis/src/joshi_analysis/wave6_routed_shadow).
Its focused adversarial corpus is under
[`analysis/tests/wave6_routed_shadow`](../../../analysis/tests/wave6_routed_shadow).
It adds no dependency and changes no shared schema or entry point.

This is an instrument, not a finding. It contains no empirical dataset and makes no claim that an
undeployed edge would become a Jupiter candidate, receive the replayed flow, land, attract
arbitrage, or earn future profit.

## Research and exact-math boundary

The contract follows the routed-liquidity research sequence:

- [venue and routability](../../research/routed_liquidity/02_VENUE_ROUTABILITY.md): a dormant bin
  inside a viable route surface is different from an empty pool, and candidate eligibility is
  different from route selection;
- [ghost-edge experiment](../../research/routed_liquidity/03_GHOST_EDGE_EXPERIMENT.md): isolated
  would-quotes, sequential inventory, explicit external-state treatments, bounded arbitrage,
  terminal liquidation, and falsifiers;
- [option/control/accounting](../../research/routed_liquidity/04_OPTION_CONTROL_ACCOUNTING.md): a
  finite schedule supplies bounded inventory-conversion optionality, self-routed fees are not
  external revenue, and the authoritative comparison is a common-horizon terminal branch
  difference; and
- [dynamics and causality](../../research/routed_liquidity/06_DYNAMICS_CAUSALITY.md): frozen-state
  mechanics precede descriptive route-flow work and cannot establish a dynamic causal effect.

The Pump, PumpSwap, and DLMM arithmetic boundary follows
[implementation lane 12](../lanes/12_protocol_liquidity.md):

- Pump exact-base-out buy preserves literal `floor(...) + 1`, even on exact division;
- Pump exact-base-in sell floors raw quote consideration before separately rounded fees;
- PumpSwap adds the signed virtual quote reserve to the raw vault reserve and refuses a
  nonpositive effective reserve;
- PumpSwap sell capacity uses `raw_quote_vault >= raw_quote_out - lp_fee`;
- every Pump fee component is ceiled separately in basis-point units;
- the shaped edge uses Q64.64 Y-per-X prices and integer floor conversion only; and
- DLMM total fees retain their separate `1e9` precision and protocol share is floored in bps.

The Python Pump/PumpSwap functions are pinned reference calculations, not a second production
protocol adapter. They intentionally implement only the exact-base formulas already supported by
the Rust lane. Exact reference helpers also reproduce the fixed-width 19-bit Q64.64 bin-price
operation graph and the current dynamic-fee/net-fee/gross-fee/protocol-share formulas. The shaped
operator accepts the resulting observed/profile-bound Q64.64 prices and total fee rate; it does not
decode deployed state, prove which parameters apply, or establish account closure, token-extension
behavior, or transaction feasibility.

## Evidence ladder

The central defense is structural separation:

| Object | Meaning | It cannot mean |
| --- | --- | --- |
| `VenueQuote` | exact calculation from one observed/copied venue state | Jupiter considered it, chose it, or it filled |
| `WouldQuote` | exact hypothetical ghost calculation | an observed quote, deployed market, candidate, or fill |
| `JupiterWitness.candidate_venue_ids` | candidates retained from one router witness | every possible market or a route choice |
| `JupiterWitness.routed_venue_ids` | route reported by that same witness | finalized execution |
| `RouteDecision` | this registered direct-route policy's copied-state selection | Jupiter's actual selection or a causal prediction |
| `ModeledTransfer` | inventory transition applied to copied state | a landed trade |
| `LandedFill` | independently supplied finalized-chain truth | something the shadow reducer may synthesize |
| `ArbitrageResponse` | a registered before/after scenario action | observation of an arbitrageur or endogenous response |

`run_shadow_study` never creates a `LandedFill`. A quote intent may carry an independently retained
fill, but the modeled route and fill remain different fields even when their values happen to
match.

The Jupiter witness also requires every routed venue to be in its candidate set. A hypothetical
ghost is admitted only by `ShadowScenario.ghost_assumed_candidate`; that boolean is visibly an
assumption and never edits the witnessed candidate list.

## Exact numeric contract

Financial state uses Python integers inside an explicit unsigned 128-bit envelope. Binary floats,
implicit display decimals, negative atomic quantities, boolean-as-integer values, and overflow of
the envelope refuse. Wire parsing accepts canonical decimal strings only; `01`, `+1`, `1.0`, and
non-ASCII numeric forms refuse.

Canonical study bytes:

- encode all integers as decimal strings;
- encode enums by stable string values;
- order dataclass fields, mappings, lists, and tuples deterministically; and
- refuse binary floats rather than serialize an approximation.

These bytes support repeatable SHA-256 state and result identities. They are a local reference
encoding, not a new shared projection schema.

## Finite-bin operator

`DlmmBinEdge` is a venue-neutral, DLMM-like compiler target. Each bin contains:

```text
bin id
Q64.64 price = Y atoms per X atom
finite X atoms
finite Y atoms
```

At active bin `a`:

- X→Y traverses funded Y at bin IDs `<= a`, descending;
- Y→X traverses funded X at bin IDs `>= a`, ascending;
- a gap or wrong-side schedule refuses rather than interpolating liquidity; and
- a quote must consume the complete exact-in amount or refuse—there is no silent partial fill.

For one X→Y leg:

```text
output_y = floor(input_x * price_q64 / 2^64)
```

The inverse direction uses `floor(input_y * 2^64 / price_q64)`. Per-bin input capacity is solved
with integer inequalities so the floored output cannot overdraw the finite asset balance. A quote
crossing bins retains every leg. Applying it consumes output inventory, adds trade input to bin
principal, records the LP-owned fee separately, and advances a state-bound digest.

Changing only `active_bin_id` can make the same installed schedule quotable, wrong-side, or
dormant. Sequential replay never resets depleted inventory. This is the implemented meaning of a
state-dependent route operator and finite optionality; it is not a claim of on-chain DLMM parity.

## Route and scenario reducer

For each ordered intent, the reducer:

1. optionally applies a registered pre-request arbitrage scenario;
2. calculates every observed direct-venue quote;
3. restricts baseline selection to the witnessed Jupiter candidate IDs;
4. calculates the independent ghost would-quote;
5. selects the ghost only when candidate status is assumed and it strictly beats the best control
   by more than the registered minimum margin;
6. applies only the selected copied-state transition;
7. optionally applies a registered post-request arbitrage scenario; and
8. records before/after ghost inventory without creating execution evidence.

Control ties win deliberately. The tie rule is conservative and deterministic.

Two external-state treatments are explicit:

- `fixed_witnessed_state` requotes controls from their initial witness while the ghost retains its
  sequential inventory; this exposes the inconsistency of observed-external replay; and
- `coupled_copied_state` updates any selected copied control as well as the ghost; this is
  mechanically coherent for touched venues but still holds demand exogenous.

Bounded arbitrage is an enumerated `ArbitrageSpec`, including direction, input, external unwind,
route/priority cost, minimum profit, latency, and before/after ordering. It acts only when the ghost
can quote and registered modeled profit clears the threshold. The external unwind is an input
assumption, not inferred future knowledge.

This V1 compares direct routes only. It does not enumerate multi-hop paths, optimize split routes,
model account/compute constraints, or reconstruct RFQ/JIT behavior. A witnessed multi-leg Jupiter
route remains visible in the witness but is not claimed to be reproduced by the reducer.

## Inventory and fee accounting

The ghost inventory retains six exact components:

```text
bin principal X / Y
external-flow LP fee X / Y
household-self-routed LP fee X / Y
```

Protocol fees are not owned inventory. Self-routed LP fees remain disclosed but never enter the
external-service-revenue field. The implementation does not model the other side of a household
self-route, so a run containing such flow is an attribution test, not a complete household branch;
a real consolidated branch must supply the controlled wallet effects independently.

## Diagnostics and terminal economics

Diagnostics do not post to an actual ledger:

- `ToxicityDiagnostic` is the signed change in same-size executable reference output at a named
  horizon; positive means movement in the trader's direction after the fill-time cut;
- `InventoryTransferRegret` is contemporaneous external alternative output minus LP principal
  output, in the explicitly named output asset; and
- `LvrLikeDiagnostic` is the common-manifest terminal score of a registered rebalancing branch
  minus the passive branch. It is discrete and scenario-dependent.

The caller should choose LVR-like or inventory-transfer regret as its adverse-selection
attribution unless disjointness is independently established.

`terminal_liquidate` requires a full-size quote for every non-numeraire asset. Quote size mismatch,
wrong numeraire, missing route, or unavailable route creates a named residual and makes scalar
terminal value `None`. It never substitutes a mark or silently treats the residual as zero.

For complete branches:

```text
BranchScore(P) = terminal_liquidation(P)
               - external_contributions(P)
               + external_distributions(P)

JointEdgeSurplus_B = BranchScore(joint) - BranchScore(B)
```

Both branches must share the exact terminal manifest and numeraire. A partial branch produces no
surplus number. The result is a counterfactual terminal branch difference, not actual PnL or future
expected value.

## Adversarial screens

The implemented non-statistical falsifier screen names:

- activation with an incomplete witnessed route universe;
- activation only below a declared economically relevant input size;
- sequential exhaustion after an earlier activation;
- partial terminal liquidation; and
- surplus sign reversal across registered ordering/repricing scenarios.

The test corpus additionally exercises:

- Pump literal `+1`, separate fee rounding, signed PumpSwap virtual reserves, and the LP-retained
  vault-capacity boundary;
- a nonlinear quote crossing two differently priced bins;
- the same schedule becoming dormant after an active-bin state change;
- refusal after finite capacity depletion without state reset;
- witnessed candidate/routed, modeled selection, modeled transfer, and landed fill remaining
  distinct;
- external versus self-routed fee classification;
- bounded arbitrage as a separate counterfactual response;
- wide values above `int64`, invalid decimal forms, and float refusal;
- partial liquidation instead of residual-to-zero coercion; and
- byte-identical deterministic replay.

These screens do not supply statistical support, coverage, router parity, or external validity.

## Deliberate exclusions

There is no code in this package for:

- RPC, HTTP, WebSocket, Jupiter, or venue API calls;
- pool, position, bin-array, tick-array, or account creation;
- instruction or transaction construction;
- key material, wallet capabilities, signing, simulation, sending, or confirmation;
- route discovery, live index admission, or market listing;
- transaction account/compute/ALT/Token-2022 feasibility;
- empirical flow generation, learned demand, or causal estimation; or
- policy optimization and parameter search.

A positive shadow surplus therefore authorizes nothing. Promotion would first require coherent
prospective observations, exact deployed-profile differential evidence, sparse live Jupiter
comparators, full transaction/landing and terminal-liquidation calibration, frozen cohorts and
scenarios, and a separate authority/security review.

## Verification

Run from `analysis/`:

```text
uv run pytest tests/wave6_routed_shadow
uv run ruff check src/joshi_analysis/wave6_routed_shadow tests/wave6_routed_shadow
```

Result on 2026-08-18:

```text
14 passed
All checks passed!
```

## Decision boundary

Use this package to falsify arithmetic, semantic separation, sequential inventory, and terminal
branch stories on immutable fixtures. Do not use it to say that a venue was live, Jupiter would
route, a transaction would land, arbitrage would arrive, a fee would be earned, volatility would
change, or a live edge should be created.
