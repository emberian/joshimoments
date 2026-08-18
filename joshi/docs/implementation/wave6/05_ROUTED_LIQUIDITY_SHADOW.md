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
| `VenueQuote` | exact calculation from one observed/copied venue state and source cut | Jupiter considered it, chose it, or it filled |
| `WouldQuote` | exact hypothetical ghost calculation retaining its own source cut | an observed quote, deployed market, candidate, or fill |
| `JupiterWitness.candidate_venue_ids` | candidates retained from one router witness | every possible market or a route choice |
| `JupiterWitness.routed_venue_ids` | route reported by that same witness | finalized execution |
| `RouteDecision` | this registered direct-route policy's selection, or a typed unknown result | Jupiter's actual selection or a causal prediction |
| `ModeledTransfer` | inventory transition applied to copied state | a landed trade |
| `LandedFill` | independently supplied finalized-chain truth | something the shadow reducer may synthesize |
| `ArbitrageResponse` | a registered before/after scenario action | observation of an arbitrageur or endogenous response |

`run_shadow_study` never creates a `LandedFill`. A quote intent may carry an independently retained
fill, but the modeled route and fill remain different fields even when their values happen to
match.

The Jupiter witness also requires every routed venue to be in its candidate set. A hypothetical
ghost is admitted only by `ShadowScenario.ghost_assumed_candidate`; that boolean is visibly an
assumption and never edits the witnessed candidate list. `universe_complete=true` is structurally
invalid with partial, stale, unsupported, or `SOURCE_GAP` coverage. A qualified modeled selection
requires observed-complete coverage, one supplied quote or typed refusal for every witnessed
candidate, and at least one successful comparable baseline. Otherwise the result is typed unknown,
publishes no margin, and applies no organic or arbitrage transition.

Every baseline state and ghost schedule carries a required `SourceCut`: source-cut ID, exact slot,
profile ID, and topology epoch. A `VenueQuote` receives its slot from that state, never from the
request's Jupiter witness. Selection requires byte-for-byte equality between every emitted
reference-state cut, the ghost cut when assumed eligible, and the Jupiter cut. A mismatched
reference therefore remains
visibly at (for example) slot 99 and yields `unknown_incompatible_source_cut`; it cannot be relabeled
as the Jupiter slot 101.

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

The digest is not an authorization token. `apply` derives direction from the exact asset
orientation, recalculates the complete quote from current state and gross input, and requires exact
equality across state identity, assets, totals, fee split, legs, and pre-state content digest.
Quote construction also requires leg inputs and outputs to reconcile to quote totals. Copying a
legitimate digest onto altered legs or output cannot mutate state.

Changing only `active_bin_id` can make the same installed schedule quotable, wrong-side, or
dormant. Sequential replay never resets depleted inventory. This is the implemented meaning of a
state-dependent route operator and finite optionality; it is not a claim of on-chain DLMM parity.

## Route and scenario reducer

For each ordered intent, the reducer:

1. calculates every observed direct-venue quote/refusal;
2. proves observed-complete coverage and closure over every witnessed candidate;
3. requires at least one successful comparable baseline rather than treating no baseline as zero;
4. optionally applies a registered zero-latency pre-request arbitrage scenario;
5. calculates the independent ghost would-quote;
6. selects the ghost only when candidate status is assumed and it strictly beats the best control
   by more than the registered minimum margin;
7. applies only the selected copied-state transition;
8. optionally applies a registered zero-latency post-request arbitrage scenario; and
9. records before/after ghost inventory without creating execution evidence.

Control ties win deliberately. The tie rule is conservative and deterministic.

Two external-state treatments are explicit:

- `fixed_witnessed_state` requotes controls from their initial witness while the ghost retains its
  sequential inventory; this exposes the inconsistency of observed-external replay; and
- `coupled_copied_state` updates any selected copied control as well as the ghost; this is
  mechanically coherent for touched venues but still holds demand exogenous.

Bounded arbitrage is an enumerated `ArbitrageSpec`, including direction, explicit input/output,
unwind, cost and profit asset identities, exact amounts, latency, and before/after ordering. Request
and modeled arrival slots are retained. This reducer has no arrival-state tape, so nonzero latency
is a typed `latency_state_unavailable` refusal; it is never applied immediately against stale
request state. A zero-latency scenario acts only when units match, the route denominator is closed,
the ghost can quote, and registered input-asset profit clears the threshold. The external unwind is
an input assumption, not inferred future knowledge.

This V1 compares direct routes only. It does not enumerate multi-hop paths, optimize split routes,
model account/compute constraints, or reconstruct RFQ/JIT behavior. A witnessed multi-leg Jupiter
route remains visible in the witness but is not claimed to be reproduced by the reducer.

## Inventory and fee accounting

The ghost inventory retains exact components and intrinsic reconciliation evidence:

```text
bin principal X / Y
external-flow LP fee X / Y
household-self-routed LP fee X / Y
household self-route counterparty delta X / Y
one content-identified counterleg per household self-route
```

Protocol fees are not owned inventory. Self-routed LP fees remain disclosed but never enter the
external-service-revenue field. Every household self-route records the paired wallet/custody
counter-effect from the same exact quote. `consolidated()` includes that signed counter-effect, so
an owned fee cannot manufacture household wealth; an externally paid protocol component remains a
real household cost. This closes the local two-sided fixture algebra, but it is not a
store-reconciled household balance sheet.

`AssetInventory` is itself fail closed: any nonzero self-fee requires retained counterlegs whose
LP-fee amounts and signed input/output counterparty deltas reconcile exactly. Thus a public
`AssetInventory(x_atoms=100, self_fee_x_atoms=10, ...)` with no counterleg refuses instead of
consolidating to 110. Duplicate quote identities or a one-atom counterparty mismatch also refuse.

Each `ShadowScenario` freezes one of `none`, inventory-transfer regret, or LVR-like as its
adverse-selection attribution. The independent diagnostic calculators remain non-posting; a caller
cannot ask the ITR helper to operate on an LVR-like run or vice versa.

The scenario display ID is not an attachment authority. `ShadowScenario.content_digest`
recomputes an identity over the exact candidate assumption, margin, copied-state policy,
arbitrage registrations, and adverse-selection choice. `ShadowRun.registration_digest` then binds
that policy identity to the schedule, initial inventory, ordered quote intents and Jupiter
witnesses, and every emitted reference/ghost source cut. Reusing a scenario ID does not make a
diagnostic portable to a different policy, input sequence, source cut, or registered run.

## Diagnostics and terminal economics

Diagnostics do not post to an actual ledger:

- `ToxicityDiagnostic` is the signed change in same-size executable reference output at a named
  horizon; positive means movement in the trader's direction after the fill-time cut;
- `InventoryTransferRegret` is contemporaneous external alternative output minus LP principal
  output, in the explicitly named output asset; and
- `LvrLikeDiagnostic` is the common-manifest terminal score of a registered rebalancing branch
  minus the passive branch. It is discrete and scenario-dependent.

`audit_adverse_selection` enforces that frozen choice. An ITR run must supply exactly one ITR
diagnostic and no LVR-like diagnostic; an LVR-like run has the inverse requirement. Supplying
neither, supplying both, using the wrong helper, or attaching a diagnostic from another scenario
refuses. A `none` run accepts neither. These objects remain non-posting and cannot be added again to
branch surplus.

Both diagnostic types retain the recomputed scenario-content and run-registration digests plus an
immutable diagnostic-kind discriminator. The audit recomputes both digests from the supplied run
and requires the exact runtime class and discriminator for each named slot. An ITR instance passed
through the nominal `lvr` parameter therefore refuses before attribution or attachment; annotations
are not trusted as runtime evidence.

`LiquidationManifest` binds one horizon, profile, numeraire, and canonically ordered full quote
universe. Quote occurrence IDs and asset/size keys must be unique. Its SHA-256 identity is
recomputed from those contents and deliberately excludes the caller's display `manifest_id`.
Different branch sizes can use the same manifest when it contains both exact-size quotes.

`terminal_liquidate` requires a matching full-size quote for every non-numeraire asset. Quote size
mismatch, missing route, unavailable route, zero expected output, or costs consuming the entire
output creates a named residual and makes scalar terminal value `None`. It never substitutes a mark
or silently treats a residual as zero. Each result also recomputes a content digest over the
manifest identity, exact inventory, components, and residuals.

For complete branches:

```text
BranchScore(P) = terminal_liquidation(P)
               - external_contributions(P)
               + external_distributions(P)

JointEdgeSurplus_B = BranchScore(joint) - BranchScore(B)
```

Both branches must share byte-identical recomputed terminal-manifest content and numeraire; matching
caller labels are irrelevant. A partial branch produces no surplus number. The result is a
counterfactual terminal branch difference, not actual PnL or future expected value.

## Adversarial screens

The implemented non-statistical falsifier screen names:

- activation with an incomplete witnessed route universe;
- a missing candidate quote/refusal or no successful comparable baseline;
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
- omitted, duplicate, or mismatched household counterlegs refusing at public inventory creation;
- mutually exclusive run-bound ITR/LVR helpers and an exact-one attribution audit;
- same display ID with different policy or registered run, and wrong runtime diagnostic types,
  refusing attachment while identical-run positive cases pass;
- baseline slots retained from exact source cuts, with mismatched Jupiter/reference cuts producing
  a typed unknown rather than slot stamping or selection;
- bounded arbitrage as a separate counterfactual response;
- billion-slot latency and asset-unit mismatches refusing rather than acting immediately;
- a forged quote with the genuine public pre-state digest refusing on full recomputation;
- wide values above `int64`, invalid decimal forms, and float refusal;
- partial liquidation instead of residual-to-zero coercion;
- duplicate liquidation quote IDs, caller manifest aliases, and zero-output liquidation; and
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
23 passed
All checks passed!
```

## Decision boundary

Use this package to falsify arithmetic, semantic separation, sequential inventory, and terminal
branch stories on immutable fixtures. Do not use it to say that a venue was live, Jupiter would
route, a transaction would land, arbitrage would arrive, a fee would be earned, volatility would
change, or a live edge should be created.
