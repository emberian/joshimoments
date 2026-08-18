# Venue and routability contract for state-contingent liquidity edges

**Status:** current venue research, not an implementation or capital-deployment authorization  
**Evidence cutoff:** 2026-08-16  
**Scope:** permissionless Solana liquidity that Jupiter can plausibly route through

## Verdict

Use **Meteora DLMM as the first counterfactual instrument**, not yet as a live venue. It is the
only compared primitive that directly represents a non-uniform, discontinuous schedule of
liquidity across many discrete prices and can resize a position without necessarily closing it.
Compile JOSHI's venue-neutral contingent-trade schedule to DLMM bins, and use **Raydium CLMM** and
**Orca Whirlpool** as differential controls. Raydium now supplies concentrated positions,
volatility-responsive fees, and single-tick limit orders; Orca supplies the simpler and
lower-account-footprint concentrated implementation. Neither has DLMM's per-bin position shape or
in-place range management.

Do not use DAMM v2, Splash, CPMM, or PumpSwap merely because they are easier to create. They are
useful baselines, but they collapse the hypothesis to either one pool-wide range or a full-range
constant-product curve. That would test a different idea.

Three constraints materially weaken the naive version of the hypothesis:

1. **Pool creation does not confer a tollbooth right.** In the ordinary permissionless paths, fee
   income belongs to funded LP positions. A `creator` field is not a durable creator royalty or
   unilateral fee authority. Raydium's optional CPMM creator fee is disabled by ordinary public
   `Initialize`; PumpSwap creator fees are zero on non-canonical pools.
2. **A fully dormant, JOSHI-only pool is likely to cease being routable.** Jupiter rechecks normal
   markets every 30 minutes and removes markets that fail its liquidity tests. Dormant bins inside
   an already-routable shared pool are different from an empty custom pool.
3. **Liquidity can change local execution, not command market-wide flow.** A shaped edge is used
   only when it wins on net output for a particular direction and size and survives index,
   account, compute, and transaction constraints. Increasing a pool's local depth can reduce its
   own price impact; it does not establish that realized market volatility is damped. The router
   may split around it, use an RFQ, or abandon it.

The first deliverable should therefore be a read-only **venue compiler and counterfactual route
probe**, not a pool creator.

## Epistemic labels

- **Known:** current official documentation or public program/source states the behavior.
- **Dynamic:** must be read from current on-chain config, SDK output, or an RPC quote; do not pin a
  prose number.
- **Inference:** consequence of known mechanics that still needs observation against live routes.
- **Gap:** current public evidence does not establish the claim.

## Decisive matrix

| Primitive | Shape and dormancy | Fee rights and mutable authority | Creation and lifecycle cost | Jupiter consequence | Decision |
|---|---|---|---|---|---|
| **Meteora DLMM** | Fixed-price bins; explicit weighted distributions and Spot/Curve/Bid-Ask presets; single-sided bins; holes and out-of-range bins can be inactive. `PositionV2` expands from 70 to 1,400 bins and can combine claim/remove/resize/add in a rebalance flow. Base fee and bin step are immutable after pool creation; dynamic fee rises with crossed-bin volatility and decays. | Standard MM fills: 90% of trade fee to LPs, 10% protocol; launch pools: 80/20. Fees accrue only to liquidity in used bins and do not auto-compound. A launch position may separate position owner and fee owner. The ordinary pool creator has no documented perpetual fee cut; special customizable pools may carry creator controls, which must not be inferred for a standard pool. | **Dynamic.** Meteora's creation review returns rent + transaction cost, excluding seed liquidity. More bin arrays and position expansion add rent/instructions; an imbalanced active-bin deposit can incur a composition fee. Existing-position add/remove/resize can avoid repeated position creation but still costs transactions and may need prerequisite bin-array allocation. | Most expressive, but most account-heavy candidate: Jupiter's published estimate is 47 inner-swap accounts before ALT / 19 with shared accounts. New markets are therefore easiest to drop when `maxAccounts` is tight. A JOSHI-only out-of-range pool may fail Jupiter liquidity checks. | **Adopt for shadow compiler; probe adapter and exact-out behavior before any live use.** |
| **Meteora DAMM v2 concentrated** | One bounded constant-product range chosen at pool creation; every position shares it. At a boundary, exact swaps fail unless the partial-fill path is used. Full-range compounding is a different mode. Fee modes include fixed, time, rate-limiter, market-cap schedule, and optional dynamic fee, but public pools choose from configured surfaces. | Default documented split is 20% protocol and the balance to LPs, with an optional referral share from protocol fees. Position NFT controls liquidity and claims. `creator` does not itself grant a royalty; operator/config authorities, not the ordinary creator label, control exceptional pool operations. Static config is not freely mutable by the creator; custom dynamic configuration is authority-gated. | **Dynamic.** UI review reports rent + transaction cost, excluding deposited liquidity. NFT position, vault, pool, and fee-claim operations add account/transaction costs. Concentrated range cannot be resized per position; changing the economic range requires another pool. Quote-compounding can automatically reinvest a configured fee share. | Jupiter treats “Meteora” at roughly 45/18 estimated inner accounts and lists DAMM v2 as eligible for instant routing during a token's grace period. For an established token, normal liquidity checks still govern. | **Probe only for one bounded edge or launch schedule; reject as nonlinear field substrate.** |
| **Raydium CLMM** | Multiple NFT positions can approximate a piecewise density; each position has fixed tick bounds and must be closed/reopened to move them. Current `CreateCustomizablePool` can choose fee side and opt into admin-defined dynamic-fee calibration. Current CLMM also has FIFO single-tick limit orders. Out-of-range positions are dormant and earn nothing. | Current standard split: 84% of trade fee to LPs, 12% buyback, 4% treasury. No ordinary pool-creator royalty is documented. Fee-on side and dynamic-fee opt-in are fixed per pool; dynamic calibration is copied from an admin-created config. Fee tiers/config authorities remain protocol-controlled. | Official UI guidance says about **0.3 SOL** for pool/first-position rent plus priority fees; exact cost varies with tick arrays. A roughly 9 KB tick array is about 0.063 SOL at the documented rent snapshot and persists after liquidity leaves. Position close/open, fee collection, new tick arrays, and limit-order accounts each add friction; fully closed limit-order accounts can return rent. | Published estimate 45/19 inner accounts. Jupiter's published adapter restrictions include Raydium CLMM in ExactOut support. Current limit-order/dynamic-fee additions are new enough that live Jupiter parity must be proved rather than assumed from the program label. | **Primary differential probe; possible second compiler after live adapter conformance.** |
| **Orca Whirlpool concentrated** | Multiple NFT positions approximate a piecewise curve. Ranges are fixed at position creation; move by close/open. One-sided positions are possible when range is away from spot. Adaptive-fee pools use a preset tier plus pool oracle, not creator-chosen arbitrary calibration. | Current Orca-config split: 87% LP, 12% treasury, 1% Climate Fund. NFT holder manages liquidity and claims. The pool creator has no separate royalty or vault right. Pools shown by Orca derive from an Orca Foundation-controlled `WhirlpoolsConfig`; custom configs have their own authority but should not be assumed visible to Orca/Jupiter. | **Dynamic.** Official SDKs return `initializationCost` in lamports for Splash and concentrated creation. Pool/position/tick-array rent depends on required accounts. Token-2022 position metadata makes ordinary position rent refundable; optional Metaplex metadata costs 0.01 SOL. Tick arrays, once initialized, cannot be closed. Fees require harvest; position movement requires close/open. | Lowest account footprint of the concentrated candidates: 30/12 estimated inner accounts. Published Jupiter adapter support includes Whirlpool in ExactOut. Easier to preserve in multi-hop/split routes under account pressure. | **Adopt as the conservative concentrated reference; probe economics, not expressive parity.** |
| **Orca Splash** | Full-range-only Whirlpool position. Always active, no custom state gate, manual fee harvest. | Same Orca-config fee split and NFT ownership; creator has no distinct right. | **Dynamic.** Orca recommends keeping at least 0.1 SOL, but that is funding guidance, not a fixed price. SDK `initializationCost` is authoritative at the read slot. Automatic tick-array setup and no range management make it cheaper operationally than concentrated Whirlpool. | Same Whirlpool adapter family and favorable account footprint, but no nonlinear/dormant shape. | **Control only.** |
| **Raydium CPMM** | Full-range `x*y=k`; no range or single-sided dormant state. LP fees stay in reserves and compound. | Standard current split 84/12/4. Raydium exposes a separate creator-fee mechanism, but ordinary permissionless `Initialize` sets it off; only `InitializeWithPermission` can enable it and choose its side. Fee rates live in shared, admin-mutable `AmmConfig`; a pool cannot migrate configs. | Raydium charges **0.15 SOL** for standard AMM/CPMM creation. Its creation guide separately says to hold about **0.2 SOL** for creation rent, token accounts, and priority fee; do not add these prose numbers blindly—use the UI/SDK message and current configs. LP-token account/deposit/withdraw costs are simpler than NFT CLMM. | 37/14 estimated inner accounts; published ExactOut support. Cheap routing surface, but it tests passive constant product rather than state-contingent conductance. | **Baseline only.** |
| **PumpSwap non-canonical pool** | Full-range AMM; no custom bin/range shape. | Current official fee page gives non-canonical pools 0.25% LP + 0.05% protocol + **0 creator fee**. Dynamic market-cap creator-fee schedules apply to canonical Pump-migration pools and follow coin-creator rights, not the wallet that creates an arbitrary strong-token edge. The protocol warns fees may change. | **Gap/dynamic.** No authoritative fixed non-canonical pool-creation price was found; compute account rent, token accounts, message fee, and priority at the target slot. | Pump AMM is on Jupiter's instant-routing-eligible venue list and has a relatively large account set in the older table (42/17). It offers no shape advantage over CPMM. | **Reject except as a Jupiter-visible full-range control.** |

### No additional orderbook recommendation

Raydium AMM v4's OpenBook hybrid is still supported, but Raydium recommends CPMM/CLMM for new
pools; the legacy design carries more accounts and roughly 0.6 SOL of rent in Raydium's current
comparison. Pure OpenBook/Phoenix-style markets may be useful for the **separate spot order book**,
but current public Jupiter market-listing documentation does not establish the same automatic
new-market path for them. Jupiter RFQ is not permissionless: its official integration requires a
hosted webhook, end-to-end onboarding, at least 95% fill reliability, and roughly 250 ms quote
response. None is a substitute for the first permissionless pool experiment. Treat CLOB/RFQ as a
separate execution lane until a live Jupiter V2 quote identifies an exact market and adapter.

## What “Jupiter-routable” actually requires

Jupiter's [market-listing policy](https://developers.jup.ag/docs/swap/routing/market-listing) is the
strongest current public contract:

- Eligible programs include Meteora DLMM, Meteora DAMM v2, Raydium/CLMM/CPMM, Whirlpool, and Pump
  AMM.
- A token's first trading pool can route immediately during a grace period, but creating another
  pool for an already-old token does **not** restart that period.
- Under normal routing, markets are rechecked every 30 minutes. A market remains eligible if
  either its $500 buy-and-sell round trip loses less than 30%, or the price-per-token difference
  between $500 and $1,000 buys is less than 20%.
- Passing those tests puts a market in the candidate universe. It does not guarantee that a quote
  will use it.

For current integrations, [`GET /swap/v2/order`](https://developers.jup.ag/docs/changelog) is a
meta-aggregator across Metis and RFQ/other routers; [`GET
/swap/v2/build`](https://developers.jup.ag/docs/api-reference/swap/build) is the composable,
Metis-only instruction path. An `/order` result can beat or entirely bypass the on-chain edge with
an RFQ. `/build` accepts DEX filters and `maxAccounts`, currently capped at 64, and exposes the
actual route plan.

The following account numbers are Jupiter's published **estimates for inner swaps**, not whole
transactions. The minimum assumes a mature shared-account/ALT route; the maximum is the simpler
new-market path. Setup, cleanup, routing-program, ATA, and top-level accounts are additional.

| Adapter label | New/simple max | Mature/shared min |
|---|---:|---:|
| Meteora DLMM | 47 | 19 |
| Meteora (DAMM family) | 45 | 18 |
| Raydium CLMM | 45 | 19 |
| Raydium CPMM | 37 | 14 |
| Orca Whirlpool | 30 | 12 |
| Pump AMM | 42 | 17 |

Jupiter's older Metis page is now explicitly superseded by V2, but it remains the only official
page that publishes this adapter table and says ExactOut is supported only for Orca Whirlpool,
Raydium CLMM, and Raydium CPMM. Treat that as a **current conformance question**, not a timeless V2
guarantee. Likewise, the existence of `routePlan[].bps` proves split-route representation, but no
venue has a right to a split. Jupiter's current JIT description says on-chain re-optimization is
limited to candidates chosen off-chain; it cites the 64-account ceiling and an average around
600,000 CU as binding constraints.

### Route-abandonment taxonomy

A candidate edge can disappear because:

1. its market fails or has not yet passed indexing/liquidity checks;
2. no active liquidity covers the current state or requested direction;
3. net output after pool, transfer, platform, and token-extension fees loses to another path;
4. the requested size exhausts bins/range or violates a range/partial-fill rule;
5. the requested mode, especially ExactOut, is not supported by Jupiter's adapter;
6. its account set does not fit `maxAccounts`, transaction size, ALT, or the current candidate set;
7. compute, stale state, missing tick/bin arrays, or Token-2022 remaining accounts make the route
   unreliable;
8. `/order` selects an RFQ or a different router even though Metis could quote the pool.

**Inference:** increasing a dynamic fee to “obstruct” a state generally makes the pool less likely
to be selected. One cannot both repel a route and collect its fee. A shallow state-local tranche
may win a small split and lose the rest; that is the useful notion of nonlinear conductance.

## Creator, LP, and authority rights

Keep these identities separate in every artifact:

```text
pool initializer != LP position owner != fee owner
                 != config/operator authority != protocol-fee owner
                 != token/coin creator
```

- **DLMM:** fees follow per-bin position shares; optional operator and fee-owner fields delegate
  position actions/claims. They do not mint a royalty on other LPs.
- **DAMM v2:** the NFT owns the position. Static/dynamic/custom config and operator privileges are
  separate authority surfaces.
- **Orca:** the NFT owns the position; Orca's config authorities set protocol surfaces. The creator
  of a pool under that config is not the config authority.
- **Raydium CLMM:** position NFT owns liquidity/fees; admin configs set fee tiers/dynamic surfaces.
- **Raydium CPMM:** LP tokens own the reserve share. The durable pool-creator fee exists only if a
  permissioned initialization enabled it; ordinary permissionless creation does not.
- **PumpSwap:** canonical coin pools can pay the coin creator; arbitrary non-canonical pools do not.

JOSHI must derive these rights from decoded accounts and instruction path. It must never infer
them from who paid creation rent or from a UI's “creator” label.

## State-contingent shape and lifecycle semantics

### What can be dormant

- A **single-sided ask range above spot** is inventory offered only after price enters it.
- A **single-sided bid range below spot** is quote inventory committed to buy only after price
  falls into it.
- A hole between funded bins/ranges carries no quote. In DLMM this can be an explicit gap; in CLMM
  it is the gap between layered positions.
- An out-of-range position remains owned but earns no fees. It may return to service if price
  re-enters.

Dormancy is not costless optionality. While a quote is posted, takers/arbitrageurs have the right,
not the obligation, to trade when JOSHI's price is favorable to them. Relative to continuously
holding both assets, an in-range passive LP is locally **short gamma/adverse-selection optionality**
and receives fees as compensation. Narrower concentration increases local inventory response.
Outside the range, gamma becomes zero and the position is left in one asset. Single-sided finite
bins bound the amount and price interval: they resemble a strip of prepaid resting limit orders,
not a free option owned by the LP.

The operator retains a separate operational option to remove or redistribute unfilled liquidity,
but landing latency, priority fees, and hostile flow determine whether it can be exercised before a
fill. Coordinating spot inventory can delta-reduce the combined portfolio; it does not erase the
LP's path-dependent fills, markouts, fees, or hedge friction. The pool and spot book must share one
inventory and PnL ledger.

### Venue-neutral schedule first

Represent the desired edge before compiling it to a venue:

```text
price interval; direction; maximum source inventory; fee policy;
activation predicate; intended duration; withdrawal/rebalance policy;
expected route sizes; permitted account/compute budget; state/source slot
```

The compiler may emit DLMM bin weights, layered CLMM ranges, or explicit spot orders. Full-range
venues cannot claim conformance with a schedule that contains holes, direction-local activation,
or non-monotone weights.

## Cost model: fixed, recoverable, and dynamic

Do not store a single “creation cost.” Produce an itemized quote at one slot:

```text
nonrecoverable protocol creation charge
+ base signature fee
+ priority fee at stated CU price and requested CU limit
+ rent-exempt lamports by account and byte length
+ ATA / NFT mint / metadata / bin-array / tick-array initialization
+ seed inventory and any active-bin composition fee
+ expected first harvest, resize, close/open, and withdrawal friction
- rent recoverable on each valid close path
```

Solana's current base fee is 5,000 lamports per signature; priority fee is requested CU limit times
CU price, not actual consumption. Both can be charged on a failed transaction. Account rent is
queried through `getMinimumBalanceForRentExemption` for the current account length. Pool SDK/UI
numbers are previews, not protocol constants. In particular:

- Raydium's 0.15 SOL CPMM creation charge is nonrecoverable; the rest must be decomposed.
- Orca Token-2022 position accounts can return rent on close, but initialized tick arrays persist.
- Raydium CLMM tick-array rent persists; its documented ~0.3 SOL varies with range/tick spacing.
- DLMM dynamic-position growth and bin arrays make rent state-dependent; fee claims do not
  auto-compound.
- DAMM v2's compounding mode can reduce harvest/redeposit work, but it removes arbitrary bin shape.

## Token-extension gate

No venue-level “Token-2022 supported” boolean is sufficient. At the target slot, record each mint's
program and extensions and exercise the exact venue quoter with all remaining accounts.

- Meteora's current DLMM SDK has Token-2022 paths, while the DAMM v2 creation UI explicitly warns
  that some extensions are unsupported.
- Orca gates some Token-2022 behavior through config extension/token-badge authority. Position NFTs
  use Token-2022 safely; that does not imply every traded-mint extension is accepted.
- Raydium CPMM and CLMM document Token-2022 support with transfer-fee/hook caveats;
  non-transferable mints cannot form an ordinary transferable market.
- Transfer fees can apply on pool ingress/egress independently of AMM fees. Transfer hooks add
  accounts and mutable external behavior, worsening both quote and route-account risk.

Unsupported, unknown, changing-hook, permanent-delegate, or freeze-capable mints should fail the
probe closed. The route model must compare what the taker actually receives, not the curve's gross
output.

## Read-only conformance and cost probe

This sequence creates no pool, signs nothing, and submits no transaction.

### 1. Freeze an observation manifest

For two existing representative pools per candidate venue—one ordinary and one using the target
feature—record finalized slot, program-data hash, pool/config/authority accounts, mint programs and
extensions, fee state, active price/bin/tick, initialized arrays, LP/creator rights, and all raw
account hashes. Use official APIs only for discovery; make on-chain accounts the evidence.

### 2. Compile hypothetical initialization messages offline

Use pinned official SDKs to build **instructions only** for one common pair/initial price/fee and a
small set of shapes. Supply fresh ephemeral public keys but no private key or signature. For every
venue record:

- all accounts, writable/signing flags, byte lengths, and whether an account can later close;
- message bytes, static keys, ALT assumptions, and predicted CU/account-data requirements;
- SDK-reported `initializationCost` where exposed, especially Orca;
- `getMinimumBalanceForRentExemption(length)` for each created account and `getFeeForMessage` for
  the unsigned compiled message at the same blockhash/slot.

Compare the itemized sum with Raydium's fixed 0.15 SOL charge and published approximate UI funding
requirements. Any unexplained remainder is a failed cost conformance result. Do not use
`simulateTransaction` against mainnet and do not submit the message.

### 3. Compile lifecycle operations offline

Against the existing representative pools, build but do not sign add, partial remove, fee harvest,
range resize/rebalance, close/open replacement, and single-tick/limit-order operations where
supported. Record instruction count, accounts, message size, prerequisite arrays, rent in/out, and
whether a half-completed multi-message sequence can leave inventory exposed. This exposes the true
cost difference between DLMM in-place rebalance and CLMM close/open.

### 4. Differential quote conformance

At the same frozen state, run official venue quoters over both directions and an amount grid from
small split tranche through the Jupiter liquidity-test sizes. For DLMM, compare explicit per-bin
weights, start/end bin, crossed arrays, base/dynamic/composition fees, and partial exhaustion. For
CLMM, compare tick traversal, transfer fees, limit-order participation, and range exhaustion. Every
integer output must reproduce on a second official implementation or from public program math.

### 5. Observe existing Jupiter-visible twins

Without a wallet connection, use the public Jupiter UI to quote the representative pair and capture
the displayed route at the same amount grid in both directions. Record whether each exact pool ID
appears, is split, or is absent and compare its net official quote with the winner. Repeat after
varying amount and at quiet/volatile states.

Automated `/swap/v2/build` route inspection currently requires a Jupiter API key. This lane does
not authorize obtaining or using one. Record the automated test as blocked rather than silently
falling back to legacy or scraped endpoints. If credentials are separately authorized later, the
test must vary `maxAccounts`, DEX filters, direction, amount, and swap mode and preserve the full
`routePlan` and message account set.

### 6. Counterfactual-only insertion

Insert a hypothetical JOSHI schedule into an offline route graph alongside the observed venue
quotes. Compute where it would beat the winner after every fee and account-cost constraint, and
where it would be dormant, exhausted, or bypassed. Label this `would_quote`, never `jupiter_routed`.
A not-yet-created pool cannot have its exact Jupiter index/ALT/adapter behavior tested. Existing
twins establish venue compatibility, not future-market admission.

### 7. Falsification gates

Reject or redesign the venue if any of these holds:

- its shape compiler cannot reproduce the intended bounded inventory schedule exactly;
- rent/rebalance/harvest friction consumes the modeled fee advantage;
- the representative feature is absent from live Jupiter routes despite winning venue-native net
  output;
- state dormancy causes the entire market to fail Jupiter's published liquidity checks;
- account pressure drops it from plausible split routes;
- exact-out or transfer-extension behavior diverges across official quoter/program effects;
- fees do not beat adverse markout plus inventory and spot-hedge cost in replay.

Only after those gates pass would a devnet instruction-mechanics test be useful. Devnet cannot
validate production Jupiter indexing or mainnet economics.

## Primary-source register

Checked 2026-08-16:

- Jupiter: [market listing and liquidity checks](https://developers.jup.ag/docs/swap/routing/market-listing),
  [Swap V2 build](https://developers.jup.ag/docs/api-reference/swap/build), [Metis-to-V2
  migration](https://developers.jup.ag/docs/swap/migration/metis-to-build), [legacy account and
  ExactOut adapter table](https://developers.jup.ag/docs/swap/v1/get-quote), [JIT routing
  constraints](https://developers.jup.ag/blog/jit-swap), and [RFQ integration
  requirements](https://developers.jup.ag/docs/swap/routing/rfq-integration).
- Meteora: [pool creation](https://docs.meteora.ag/user-guides/creating-a-liquidity-pool), [DLMM
  formulas and fee splits](https://docs.meteora.ag/core-products/dlmm/formulas), [dynamic
  positions](https://docs.meteora.ag/core-products/dlmm/dynamic-positions), [DLMM account
  authorities](https://docs.meteora.ag/developer-guides/dlmm/program/accounts), [DAMM v2
  concentrated liquidity](https://docs.meteora.ag/core-products/damm-v2/concentrated-liquidity),
  [DAMM v2 fee overview](https://docs.meteora.ag/core-products/damm-v2/fees/overview), and [pool fee
  configs](https://docs.meteora.ag/developer-guides/damm-v2/pool-fee-configs).
- Raydium: [protocol fees](https://docs.raydium.io/raydium/protocol/protocol-fees), [CPMM
  creation](https://docs.raydium.io/user-flows/create-cpmm-pool), [CPMM fee/creator
  rights](https://docs.raydium.io/products/cpmm/fees), [CLMM creation](https://docs.raydium.io/user-flows/create-clmm-pool),
  [CLMM accounts and dynamic/limit-order state](https://docs.raydium.io/products/clmm/accounts),
  and [account/rent model](https://docs.raydium.io/solana-fundamentals/account-model).
- Orca: [Splash](https://docs.orca.so/create/pools/splash), [pool creation SDK and dynamic
  initialization cost](https://docs.orca.so/developers/sdks/pools/create-pool), [position
  ownership and fixed ranges](https://docs.orca.so/developers/architecture/tokenized-positions),
  [fee/adaptive-fee mechanics](https://docs.orca.so/developers/architecture/whirlpool-fees),
  [current parameters and split](https://docs.orca.so/developers/architecture/whirlpool-parameters),
  and [config authority](https://docs.orca.so/developers/architecture/account-architecture).
- Pump: [current fee schedule](https://pump.fun/docs/fees) and [official PumpSwap account/program
  documentation](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_README.md).
- Solana: [fee and compute-budget mechanics](https://solana.com/docs/core/fees/compute-budget) and
  [`getMinimumBalanceForRentExemption`](https://solana.com/docs/rpc/http/getminimumbalanceforrentexemption).

