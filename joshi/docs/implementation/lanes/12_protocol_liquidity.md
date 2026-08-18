# Implementation lane 12 — exact protocol quote and liquidity semantics

Status: Wave 2 read-only foundation implemented; no economic authority, network adapter, policy,
transaction builder, signer, or submission surface.

## Delivered boundary

This lane adds two pure crates and one language-neutral fixture family:

| Artifact | Responsibility |
| --- | --- |
| `crates/joshi-market-math` | versioned protocol profiles, intended-versus-observed quote identity, Pump curve and PumpSwap exact-base formulas, dynamic/flat fee selection, typed refusals, ratio marks, and exact full-position liquidation promotion |
| `crates/joshi-liquidity` | Meteora DLMM Q64.64 prices, dynamic fees, per-bin position inventory, observed fee/reward claims, add/remove projections, in-place rebalance budgets, close/reopen distinction, and deterministic chunk plans |
| `fixtures/protocol` | immutable finalized-chain observations plus visibly separate synthetic rounding/refusal vectors, with every integer encoded as a decimal string |

The crates reuse `joshi-domain` `AssetId`, `CommandId`, `ObservationId`, `PoolId`, `PositionId`,
`ProtocolProfileId`, `QuoteId`, and `VenueId`. Atomic account quantities reuse
`joshi-accounting::amount::AtomQty`. This lane does not mint competing cross-crate identities.

The public semantic contract versions are `joshi.market-math.v1` and `joshi.liquidity.v1`.
Mutable internal structs are deliberately not wire DTOs. Integration should publish a separate,
versioned projection envelope with canonical input/output digests rather than adding display-oriented
serialization to these calculation types.

## Capability boundary

Neither crate can:

- open a provider connection or read credentials;
- select a coin, route, position, strategy, or risk budget;
- create an instruction, transaction, signer request, or wallet capability;
- simulate or submit a transaction;
- claim that an operation is available in Meteora's web interface; or
- turn a mark, modeled add, or rebalance budget into executable value.

The only production dependencies are the local domain/accounting crates, `thiserror`, and `ruint`.
There is no Solana client or venue SDK dependency in the reachable graph.

## Source and dependency profile

The implemented operation graphs were checked against the current official sources below. These
versions identify comparator behavior; a retained state observation still determines each result.

| Source | Pinned identity | Package integrity / license | Use |
| --- | --- | --- | --- |
| Pump public docs | commit `9c82f61cb711b044a17f770ab8ce9f9bdf78f333` | repository source | account meanings, lifecycle, effective PumpSwap reserves, canonical versus noncanonical fee behavior |
| `@pump-fun/pump-sdk` | 1.36.0 | npm SHA-512 `X8rf+Wm/p/jhBj6zbwouM9blJ3UW8XJFSL7YTT8osBnpHsOH0ccT0DjCkIi6AAT7b6jf1nM3MXk7l78Fuf1M0g==`; MIT | curve formula/fee-order comparator |
| `@pump-fun/pump-swap-sdk` | 1.19.0 | npm SHA-512 `ayLO7ESmPOpZfz1hQSiGJBanJVaQTQB/+8yRHiuZnaHIRMTwOYknH1EZr++tPNa+kYJgg8kccU98Jp9RGOdZLQ==`; MIT | PumpSwap exact-base and real-vault capacity comparator |
| Meteora DLMM SDK | commit `fb02e51ae677bbd18e76543f702dae40632426db`, package 1.9.14 | npm SHA-512 `3xJGBaYgkHWSZ7sjfaMYTuCUE9/FGibIwhoNKSaP3iXX3kZck4b3qrtFwDl/1+JaflTeiZQY4zO25e+u2V/9ug==`; ISC | Q64.64, U256 rounding, fees, position entitlement, current helper/chunk comparator |
| `ruint` | 1.20.0 | crates.io lock; MIT; Rust 1.90 minimum | owned checked U256 intermediates only |

The official TypeScript SDKs are not linked into production. They remain quarantined comparators:
their public helpers include JavaScript-number slippage boundaries, network/transaction facilities,
and higher-level assumptions that do not belong in financial truth. The published Meteora repository
also does not expose every current deployed handler body. SDK agreement is therefore necessary but
not sufficient; fixed finalized-chain observations and read-only simulation must complete the
differential profile.

No unclear-license SDK or copied implementation source was added to the repository. The Rust code
owns its small operation graphs and records the source revision that each graph is intended to match.

## Quote identity and three different values

`QuoteRequest` names the quote occurrence, optional operator command, intended state observation,
expected protocol profile, venue, pool, asset pair, direction, size semantics, and atomic size. A
calculator always returns `QuoteCalculation`, which binds that intent to the state and fee
observations actually used and their chain slot. The binding survives refusal. A stale intended
observation is `IntendedStateMismatch`; it is not silently recalculated against newer state.

The types prevent three values from collapsing:

| Type | Meaning | What it cannot claim |
| --- | --- | --- |
| `MarkObservation` | reduced exact reserve ratio at one observation | capacity, fees, impact, expiry, or fillability |
| `SpotQuote` | exact size, direction, protocol profile, state closure, raw consideration, separately rounded fee components, and user input/output | that a transaction was built, landed, or filled |
| `ExecutableLiquidation` | a `SpotQuote` proven to be an exact-base-in sell for the entire named atomic holding | actual landed proceeds or validity after its observation |

A mark cannot be promoted to liquidation. A partial quote cannot be promoted to whole-position
liquidation. Actual wallet effects remain the accounting authority after a fill.

Current result artifacts bind a chain slot but do not yet carry receipt/expiry monotonic clocks or a
canonical artifact digest. Those belong in the evidence-to-projection adapter, not in display code.

## Pump curve arithmetic

All reserve, supply, size, fee, and output values are integer atoms. U256 multiplication is used
where the product can exceed `u128`; every result is checked before narrowing to the on-chain `u64`
amount boundary.

For fee-tier selection:

```text
market_cap_quote_atoms = floor(
  virtual_quote_reserves * fee_tier_supply / virtual_base_reserves
)
```

The current official SDK uses observed mint supply for mayhem curves and the fixed standard Pump
supply `1_000_000_000_000_000` atoms otherwise. `PumpCurveState.is_mayhem_mode` therefore controls
this operand explicitly. The fee policy may be the observed legacy/global flat schedule or a
strictly increasing on-chain tier table. Below the first threshold the first tier wins; otherwise
the highest threshold not exceeding market cap wins.

Every fee component is computed separately:

```text
component_fee = ceil(raw_quote * component_bps / 10_000)
```

Creator applicability is `NotApplicable`, `Charged(rate)`, or `Unknown`; unknown refuses. The
calculator never assumes that a default creator, new curve, mayhem mode, or future state does or does
not pay creator fees.

Exact-base-out buy for `q` token atoms preserves the official literal order:

```text
raw_quote = floor(q * virtual_quote / (virtual_base - q)) + 1
input      = raw_quote + protocol_fee + applicable_creator_fee
```

The `+1` remains even when division is exact. A zero request, request beyond real base reserves, or
request reaching virtual base reserves refuses. The official convenience SDK clamps one helper at
real reserves; Joshi refuses because an intent for exact output cannot truthfully be reported as a
different filled size.

Exact-base-in sell preserves:

```text
raw_quote = floor(base_in * virtual_quote / (virtual_base + base_in))
output    = raw_quote - protocol_fee - applicable_creator_fee
```

The projection refuses if observed real quote inventory cannot cover raw consideration or if fees
exceed output. Exact-quote buy/sell paths have different inversion and correction order in the
official SDK. They currently return `UnsupportedSizeKind`; they are not synthesized by inverting
these formulas.

## PumpSwap arithmetic

Price formation always uses:

```text
effective_quote_reserve = raw_quote_vault_reserve + virtual_quote_reserves
```

The virtual term is a checked signed `i128` input. Negative, zero, overflowing, or narrowing-invalid
effective reserves refuse. A current zero value is not hardcoded.

Canonical pools require an observed market-cap tier policy. Noncanonical pools require a flat
policy. Supplying the wrong policy/profile combination is `MalformedFeeConfiguration` rather than a
fallback. Canonical market cap is:

```text
floor(effective_quote_reserve * base_mint_supply / base_reserve)
```

Exact-base-out buy:

```text
raw_quote_in = ceil(effective_quote_reserve * base_out
                    / (base_reserve - base_out))
input = raw_quote_in + ceil(lp) + ceil(protocol) + applicable ceil(creator)
```

Exact-base-in sell:

```text
raw_quote_out = floor(effective_quote_reserve * base_in
                      / (base_reserve + base_in))
output = raw_quote_out - ceil(lp) - ceil(protocol) - applicable ceil(creator)
```

The current official 1.19.0 SDK checks real payout capacity as
`raw_quote_vault >= raw_quote_out - lp_fee`: the LP component remains in the vault while protocol and
creator components do not loosen that capacity bound. A golden vector specifically prevents the
more conservative but incorrect `raw_vault >= raw_quote_out` substitution.

## Meteora Q64.64 and fee arithmetic

`Q64x64`, `BinId`, `BinStep`, and `DlmmFeeRate` are dimensioned types. No binary float appears in the
financial path.

Bin price reproduces the current official fixed-width operation graph:

```text
bps_q64 = floor((bin_step << 64) / 10_000)
base    = (1 << 64) + bps_q64
price   = q64_pow(base, bin_id)
```

`q64_pow` uses exactly 19 exponent bits, checked `u128` multiply-then-shift operations, the literal
`u128::MAX / value` reciprocal, and the `0x80000` exponent limit. It can return a typed fixed-width
refusal near underflow instead of allowing arbitrary precision to invent an on-chain result.

Current dynamic fee rate preserves its separate 1e9 unit:

```text
base_rate     = base_factor * bin_step * 10 * 10^base_fee_power_factor
variable_rate = ceil(variable_fee_control
                     * (volatility_accumulator * bin_step)^2 / 100_000_000_000)
total_rate    = min(base_rate + variable_rate, 100_000_000)
```

Fee on a requested net input is `ceil(amount * rate / (1e9 - rate))`; fee contained in a gross
amount is `ceil(amount * rate / 1e9)`; protocol share is
`floor(fee * protocol_share_bps / 10_000)`. They are distinct functions and cannot share a generic
"percent" type.

## DLMM position inventory and actions

`DlmmPositionState` binds profile, venue, pool, position, observation, slot, decoded account version,
lifecycle, evidence-bound token identity/decimals/program, range, active bin, bin step, and strictly
ordered bin states. Each bin carries cached/recomputed Q64.64 price, pool X/Y atoms, liquidity
supply, position share, and either directly observed pending accrual or named unsupported fields.

Validation refuses:

- a non-DLMM profile or mismatched venue;
- unknown account version/lifecycle;
- inverted ranges, duplicated/unordered bins, out-of-range bins, or formula/observed price mismatch;
- identical X/Y asset identities;
- nonzero share without supply, share above supply, or nonzero share in empty/closed lifecycle;
- empty, duplicated, or unordered unsupported-field names; and
- any checked U256, `u128`, or `u64` failure.

Principal entitlement is exact per bin:

```text
position_x = floor(position_share * bin_x / liquidity_supply)
position_y = floor(position_share * bin_y / liquidity_supply)
```

Principal, pending fees, and pending rewards remain separate. If any accrual input is unsupported,
aggregate fee and reward values are `None`, not misleading partial totals or zeros. The resulting
pair inventory is an immediate withdrawal projection, not a quote-currency mark or liquidation.

For a nonempty, non-active observed bin, add-share projection uses:

```text
L(x,y,P) = P_q64 * x + (y << 64)             // U256, checked narrow to u128
share    = floor(L(deposit) * supply / L(bin))
```

An add that rounds to zero refuses. Initial-bin share/minimum-liquidity behavior remains an explicit
`InitialLiquidityShare` gap. Deposits into the active bin retain `CompositionFee` as unsupported and
do not publish a misleading share, because current composition-fee semantics depend on deposit
ratio and active state.

Per-bin removal uses exact full share at 10,000 bps and otherwise
`floor(position_share * bps / 10_000)`, then the entitlement formulas above. A nonzero request that
rounds to zero refuses. Closing a position account requires every nonzero bin share to be removed;
fees/rewards are claimed only when requested and directly observed.

The action algebra keeps four meanings structurally distinct:

- `AddLiquidityIntent`: exact deposits into the same position;
- `RemoveLiquidityIntent`: per-bin fractions plus explicit claim/close flags;
- `RebalanceInPlaceIntent`: preserves position identity and checks no-swap asset conservation,
  top-up limits, and withdrawal minima; and
- `CloseReopenIntent`: requires a different new position identity and an independently declared new
  range.

Every current action projection is `ModeledOnly` with named gaps such as composition fee, initial or
rebalanced shares, account limits, transaction costs, close/reopen friction, and interface support.
`DifferentiallyVerifiedProfile` exists as a future evidence grade but is not emitted yet. A required
internal swap is `SwapTraversalUnsupported` rather than an implicit route.

Chunking consumes an externally observed nonzero `ChunkConstraint` bound to profile and observation.
It splits strictly ordered bins without loss or reordering. The kernel does not hardcode the current
SDK's 26-bin helper limit or 70-bin base position width as timeless transaction truth.

## Invariants exercised

1. Financial amounts never pass through binary floating point or JSON numeric tokens.
2. Every formula is bound to a protocol profile and exact retained observation closure.
3. Intended and observed state identities remain visible on refusal.
4. Venue, pool, profile, asset pair, lifecycle, direction, and size mismatches refuse.
5. Pump fee components round separately; creator applicability cannot default from missing data.
6. Curve buy preserves literal floor-plus-one, including exact division.
7. PumpSwap signed virtual reserve participates in price but cannot manufacture real payout capacity.
8. Canonical PumpSwap cannot consume a flat fee policy; noncanonical PumpSwap cannot consume tiers.
9. Mark, size quote, full liquidation, landed fill, and LP pair inventory are different types.
10. Q64.64 reproduces fixed-width reciprocal, exponent, multiplication, shift, and refusal behavior.
11. DLMM rates retain their 1e9 unit and do not reuse Pump basis-point arithmetic.
12. Position share cannot exceed supply; per-bin entitlement is floored and never exceeds bin assets.
13. Principal, pending fee, reward, and unsupported values never collapse into one amount.
14. Partial removal cannot close a position; rounded-zero adds/removals refuse.
15. In-place rebalance preserves position identity; close/reopen must use a new identity.
16. Rebalance budgets conserve each asset independently and cannot assume a hidden swap.
17. Chunk plans preserve exact order and coverage under an observation-bound limit.
18. SDK/helper or UI availability is never inferred from modeled arithmetic.

Property tests exercise U256 rounding, PumpSwap amount direction, DLMM price monotonicity or typed
fixed-width refusal, and position entitlement bounds. All public fixture integers are decimal
strings and RFC 8785 canonicalization is byte-stable after reparsing.

## Golden vectors

`fixtures/protocol/pump_quotes.json` contains:

- a finalized Pump curve account observation at slot `439760757` for account
  `Hgaf727Ccy1YfWAZ77otqmqW5QY8avMXi4pkbRdiomrH`, including exact reserves, lifecycle, mayhem mode,
  supply, and reduced reserve-ratio mark;
- synthetic curve buy/sell cases for literal `+1`, exact-division `+1`, and separately rounded fees;
- PumpSwap signed-effective-reserve buy/sell cases;
- the exact LP-fee real-vault capacity boundary; and
- typed refusals for unknown creator applicability, unsupported exact-quote sizing, and virtual
  reserve without real payout inventory.

`fixtures/protocol/dlmm.json` contains:

- a finalized mainnet observation of pool
  `HTvjzsfX3yU6BUodCjZ5vZkUrAxMDTrBs3CJaq43ashR` and BinArray
  `2j5ep8wxApESNcqQdtKi6owCURUopnBbGgfRffUQ3CRF`: pool slot `439760560`, finalized BinArray slot
  `439760658`, active bin `-25904`, step `1`, and stored/recomputed price bits
  `1383501207885697265` exactly;
- a hand-auditable single-bin quarter-share vector covering principal, add share, half removal,
  pending fee, and reward separation; and
- a power-factor/dynamic-fee vector covering 1e9 units plus net/gross/protocol rounding.

The README labels finalized observations and synthetic boundaries separately. PumpSwap does not yet
have a complete finalized-chain quote vector because the current evidence lane does not retain an
atomic pool/vault/mint/fee-config observation closure. That omission is recorded rather than
papered over with an aggregator price or a half-observed state.

## Exact observations the source lane must acquire

The calculator must never fetch these itself. The source/evidence lane should retain original bytes
and decode them into a versioned adapter input while preserving the following closure.

### Common closure for every quote or position projection

- network/genesis identity, program ID, deployed-program data hash or upgrade observation, protocol
  profile ID, decoder/source revision, and raw account owner;
- one observation ID per raw account, finalized/confirmed commitment, context slot, account write
  version when available, acquisition receive clock, and an explicit as-of vector;
- asset mint/native identity, token program, decimals, supply observation, and every Token-2022
  extension affecting transfer amount or feasibility;
- requested quote ID, command/scene/choice identity when present, intended state observation,
  direction, exact size semantics, and atoms;
- every state/fee/reward account in the result closure, plus canonical input/result digests and a
  received/expiry monotonic-clock policy; and
- typed absence or unsupported field with reason. A missing account/field is never decoded as zero.

Use one RPC batch or `minContextSlot`/context discipline that proves the accounts form a coherent
view. Merely recording several nearby wall times is insufficient.

### Pump curve

- complete raw curve account, layout/version, virtual and real token/quote reserves, completion and
  migration state, creator, mayhem flag, cashback/fee mode, and quote mint;
- complete raw Global and FeeConfig accounts selected by that curve, including tier thresholds and
  each protocol/creator component, plus the account-selection derivation;
- mint account at the same as-of boundary, actual supply, decimals, token program/extensions, and
  the exact standard-versus-mayhem fee-tier supply rule input;
- whether creator fees apply under new/existing/default-creator semantics, as an observed/derived
  profile fact rather than a guessed zero; and
- fixed read-only program simulation and later finalized transaction effects for zero, one atom,
  exact-divisible buy, near-real-reserve buy, sell, fee-tier boundary, standard, mayhem, non-SOL
  quote-mint, and migrated/complete refusal cases.

### PumpSwap

- raw Pool account including pool index/canonical identity, base/quote mints, coin creator,
  virtual-quote reserve, lifecycle/status, and every profile field;
- raw base and quote vault token accounts at the same context slot, not API TVL or a running delta;
- base mint supply and both mint token-program/extension observations;
- raw GlobalConfig plus the exact FeeConfig account selected for canonical pools, all tiers and
  thresholds, and the flat components for noncanonical pools;
- creator versus coin-creator identity and applicability, including default-address semantics;
- exact-base and exact-quote buy/sell SDK comparator outputs, program simulation results, instruction
  limits, slippage bounds as integers, and observed real-vault failure boundaries; and
- at least one fixed finalized canonical pool vector with nonzero fee components and, when one exists
  on chain, a nonzero virtual-quote-reserve vector. Zero today is still an observed field.

### Meteora DLMM

- raw LbPair account with status, pair type, activation type/point, active bin, bin step, base factor,
  base-fee power factor, variable-fee control, volatility accumulator/reference, protocol share,
  collect-fee mode, token mints, reserves, reward state, and bitmap-extension identity;
- raw mint and reserve token accounts at one coherent context, including transfer-fee epoch/config,
  transfer hooks, withheld amounts, and decimals;
- every BinArray required by the position/action, its index/version, and for each relevant bin the
  raw amounts, cached price (including zero/uninitialized distinction), liquidity supply, fee growth,
  reward/limit-order alias fields, and initialized state;
- complete raw Position account, deployed layout/version, position range/length, per-bin shares,
  fee checkpoints, reward checkpoints, claimed totals, owner/operator/lock fields, and lifecycle;
- reward mint/vault identities and raw pending/claimed amounts per reward asset;
- fee/clock observations needed to derive pending accrual. Until the deployed derivation is fully
  profiled, retain directly observed pending values or explicit unsupported fields;
- read-only simulation and finalized-effect vectors for existing-bin add, initial-bin add, active-bin
  composition fee, partial/full remove, claim/no-claim, close-if-empty, in-place rebalance, and
  close/reopen—including rounded dust and failed cases;
- exact account/bin limits from the named instruction/profile and simulation, rather than treating
  SDK constants `26`, `70`, or `91` as universal; and
- whether the deployed instruction set supports the modeled in-place rebalance and which accounts it
  mutates. Record this as program/profile evidence, separately from whether a particular UI exposes
  it.

## Deliberate gaps and next adapter

- Pump exact-quote paths are refused until their distinct operation graphs and goldens are added.
- Pump/PumpSwap Token-2022 transfer fees, transfer hooks, cashback, and non-SOL quote-mint execution
  effects are not yet projected.
- DLMM swap traversal, bitmap search, exact-out dust, host fee, composition fee, initial liquidity,
  fee-growth/reward-checkpoint derivation, and transaction feasibility are not implemented.
- Add share is published only for a nonempty, non-active observed bin. Active and initial bins retain
  explicit gaps.
- A rebalance result is an asset-conservation budget, not a claim that share math, account limits,
  friction, or UI/deployed support succeeded.
- Position inventory remains an X/Y withdrawal projection. Reference-unit mark and executable
  liquidation require separate size-specific market quotes for both legs and must retain their own
  observations/expiry.
- No internal type is the integration wire artifact. The next adapter should emit a contract/version
  envelope with exact asset definitions, atomic strings, rational marks, requested/observed closure,
  result/refusal, unsupported fields, reconciliation status, and superseding correction identity.
  Display decimals must never feed back into these inputs.

## Verification

Focused gates:

```sh
cargo test --locked -p joshi-market-math -p joshi-liquidity --all-targets
cargo clippy --locked -p joshi-market-math -p joshi-liquidity --all-targets -- -D warnings
cargo doc --locked -p joshi-market-math -p joshi-liquidity --no-deps
```

At handoff, market math has nine passing tests and liquidity has eight, including finalized-chain
goldens, synthetic formula/refusal vectors, canonical-wire checks, and generated properties. The
root integrator owns the shared manifest/lock and the final whole-workspace gate.
