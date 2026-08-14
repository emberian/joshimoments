# How do you actually land a transaction on Solana?

**Study:** `studies/execution_landing.py` — read-only over `state/cluster_tape/`, plus one cached
RPC probe (4,316 + 1,742 `getTransaction` calls) whose results live in
`.cache/execution_landing/`. Re-run with `--probe` to refresh, bare to re-analyse.

**Data:** 79,102 tape rows over six cluster pools (2,937 swaps, 57,097 references, 7 liquidity,
19,061 attempts), spanning 2026-08-12 to 2026-08-14. Prices: **SOL = $75.75**, checked against
Coinbase spot (`75.755`) and Kraken last (`75.75`) at 2026-08-14T03:40Z.

---

## The headline

`scripts/sim2real.py` reports ambient landing rates of **1%–52%** and warns that true friction
could be 2–10× what the shadow model says. That warning is directionally right about the *model*
— the shadow marker genuinely has no failure branch — but the **number is wrong by an order of
magnitude, and in our favour**.

Decomposed properly, the landing rate for a transaction shaped like ours is **95–97%**, not 12%.
The 12% is a measurement of other people's arbitrage-bot spam.

| reference class | est. swaps | est. failures | landing rate |
|---|---|---|---|
| direct AMM call (no aggregator) | 980 | 48 | **95.3%** |
| Jupiter route | 489 | 340 | 59.0% |
| third-party (private arb programs) | 1,469 | 18,673 | 7.3% |

The path is not what is doing the work. Splitting each path at the compute-unit price where the
dose-response turns over:

| | est. swaps | est. failures | landing rate |
|---|---|---|---|
| direct-AMM, bid < 50k µL/CU | 348 | 19 | **94.8%** |
| direct-AMM, bid ≥ 50k | 631 | 29 | **95.6%** |
| Jupiter, bid < 50k | 139 | 330 | **29.6%** |
| Jupiter, bid ≥ 50k | 350 | 10 | **97.2%** |
| third-party, bid < 50k | 326 | 16,256 | 2.0% |
| third-party, bid ≥ 50k | 1,143 | 2,417 | 32.1% |

**Above the cliff both honest paths land alike — 95.6% and 97.2%.** The headline path gap is mostly
a bid gap wearing a path costume. What the direct AMM call actually buys is *insurance against
underbidding*: it holds 94.8% below the cliff, where Jupiter falls to 29.6%.

All population-reweighted from a stratified probe of 4,316 transactions; strata are (pool × row-kind)
and each sampled transaction carries its cell's `population/sample` weight.

A bid at the cliff costs **$0.001 in total fee** — 1.1 bps of a $9 clip, 0.07 bps of a $150 one; the
*increment* from a losing 30k bid to a winning 50k one is 3,200 lamports, **$0.00024**. Ambient
traffic fails because it bids nothing, not because bidding is expensive.

**The landing policy is at the bottom (§8).** Its one-line summary: bid 100k–300k microlamports/CU
(costing $0.0016–$0.0040, i.e. 1.8–4.5 bps of a $9 clip), call the AMM directly, set the compute-unit
limit from a simulation rather than a constant, sign once and rebroadcast the same bytes, and skip
Jito for v1.

---

## 1. The denominator is broken three ways

### 1.1 `sim2real` drops 57,097 successful transactions

The tape emits four row kinds (`shitcoims_cluster/parse.py`):

- `swap` — moved this pool's vaults
- `liquidity` — added/removed liquidity
- `reference` — landed fine, the pool address appeared in the transaction, **zero delta on our
  vaults**. Per the docstring at `parse.py:153-157`: "routers carrying the pool in an
  address-lookup table and filling somewhere else."
- `attempt` — the signature listing carried a non-null `err`

`sim2real` computes `swap / (swap + attempt)`. A `reference` row is a **success**; it is counted in
neither column. Restoring it:

| pool | swap | reference | liq | attempt | sim2real | landed |
|---|---|---|---|---|---|---|
| DREGG/SOL | 81 | 133 | 0 | 85 | 48.8% | 71.6% |
| DREGG/nosis | 1 | 178 | 2 | 69 | **1.4%** | **72.4%** |
| SOLVE/SOL | 165 | 6 | 0 | 152 | 52.1% | 52.9% |
| nosis/SOL | 2,317 | 55,168 | 0 | 16,979 | **12.0%** | **77.2%** |
| weave/SOL | 296 | 1,179 | 0 | 1,092 | 21.3% | 57.5% |
| weave/nosis | 77 | 433 | 5 | 684 | 10.1% | 43.0% |
| **ALL** | 2,937 | 57,097 | 7 | 19,061 | **13.4%** | **75.9%** |

The "1% landing rate" on DREGG/nosis is one swap against 178 successful router transactions. It is
not a landing rate at all.

Neither bound is the number we want. `sim2real`'s statistic assumes every failure was aimed at this
pool and no success was; the `landed` column assumes the reverse. The truth needed the transaction
bodies.

### 1.2 96% of the failures are not swaps — they are arb bots aborting on purpose

Fetching `getTransaction` for 2,390 sampled failures and reading the program at the failing
instruction index:

- **1.0%** failed inside an AMM program
- **3.0%** failed inside Jupiter
- **96.1%** failed inside a third-party program

The top ten failing programs — `Prism8hsRo6Ww5jiN5Zeh3YDPLZHqHduCPSAV7JF7qv`,
`DRSw8uSW9De7eCKSM9qXm7aD2QKrvcJnA7Hf4Uu3ezYM`, `4Qv3mbzcq1bKmrhGG4voS3EemfPd7f838FLUU7wBHSyi`,
`King7ki4SKMBPb3iupnQwTyjsq294jaXsgLmJo8cb7T` and six more — account for 1,420 of 2,390. None is a
published DEX. Nine of the ten land a swap on our pools between **0.8% and 14%** of the times they
touch them; the tenth (`2VSNUquk7Fqk…`) is a router that succeeds 77% of the time but almost always
fills elsewhere, so it shows up as `reference` rather than `swap`.
In the matched-slot sample, **109 distinct fee-payers produced 1,051 failures and the top ten
produced 46.6% of them.**

That is the signature of speculative arbitrage: fire at every opportunity, abort in-program when the
arb evaporated, eat the fee. Those programs are *designed* to revert. Their failure rate is a
property of their strategy, not of the network.

This is corroborated externally. Helius measured revert rates by address activity
(2025-01-06→13): addresses doing **1–5 transactions/day revert 1.4%**; addresses doing **>10,000/day
revert 66.7%**, and addresses above 100,000/day are **95.2% of all reverted transactions**
(<https://www.helius.dev/blog/solana-executive-overview>). Zheng et al. (arXiv:2504.18055, ACM
10.1145/3728943, 2.9B non-vote transactions) classify bot vs human and get **58.43% vs 6.22%** —
with humans at ~0.4% of classified volume, so any blended figure is a bot metric wearing a network
costume. Our 96.1% is the same fact seen from a single pool.

### 1.3 The tape is structurally blind to the free half

`attempt` rows are emitted from the `getSignaturesForAddress` listing when `err` is non-null
(`shitcoims_cluster/record.py:204-206`), with no `getTransaction` at all — which is why they carry
no `fee_lamports` and no `compute_units`. Two consequences:

**Every one of the 19,061 attempts landed on chain and paid a fee.** All 19,061 errors in the tape
are `InstructionError`; there is not a single `BlockhashNotFound`, `AccountInUse`, or
`WouldExceedMaxAccountCostLimit`. That is not luck — those are pre-execution errors and Agave's SVM
draws the line at fee-payer validation: `Ok(ProcessedTransaction)` is committed and charged,
`Err(TransactionError)` is never committed and free
(<https://github.com/anza-xyz/agave/blob/master/svm/src/transaction_processing_result.rs>; the
`Executed` variant's own doc comment says state changes roll back "except deducted fees"). Solana's
fee docs state it plainly: *"The total fee is deducted from the fee payer before execution begins.
If the transaction fails, the fee is still charged."*
(<https://github.com/solana-foundation/solana-com/blob/main/apps/docs/content/docs/en/core/fees/fee-structure.mdx>)

**A dropped transaction leaves no trace.** `getSignaturesForAddress` returns *confirmed* signatures
only (<https://solana.com/docs/rpc/http/getsignaturesforaddress>). A transaction that expired,
was dropped by the leader, or was never forwarded has no ledger entry to find.

So the tape measures the **fee-burning** branch exactly and the **free** branch not at all.

> **What the tape cannot answer, and what would.** Our drop rate — the probability a signed
> transaction never lands anywhere. No chain-derived dataset can produce it, ours or anyone's; the
> only published attempt found was RockawayX's unreplicated 2024 remark that ~50% of transactions
> included in a block are not finalized. The measurement requires logging every signature at submit
> time and reconciling against inclusion inside the 151-slot window. That is §8's first
> instrumentation item and it is not optional.

---

## 2. Contention is the mechanism

A writable-account lock is exclusive, so two swaps on one pool in one block execute in sequence and
the second prices against reserves the first already moved. Sorting slots by how many transactions
reference the pool:

| nosis/SOL | slots | swap | ref | attempt | landed | swap-vs-attempt |
|---|---|---|---|---|---|---|
| 1 tx/slot | 2,927 | 742 | 1,745 | 440 | 85.0% | 62.8% |
| 2 | 1,507 | 191 | 2,444 | 379 | 87.4% | 33.5% |
| 3–4 | 1,798 | 162 | 5,307 | 751 | 87.9% | 17.7% |
| 5–8 | 1,620 | 214 | 8,603 | 1,234 | 87.7% | 14.8% |
| 9–16 | 1,026 | 246 | 9,052 | 2,707 | 77.5% | 8.3% |
| 17+ | 1,101 | 762 | 28,017 | 11,468 | 71.5% | 6.2% |

`weave/SOL` is starker: 85.4% landed alone in a slot, **7.5%** at 17+.

`SOLVE/SOL` is the cleanest instrument in the whole tape — it has only 6 reference rows in 323, so
router noise is absent and `swap-vs-attempt` *is* the intent-conditional rate: **91.0% alone in a slot,
22.7% at 3–4 transactions per slot.**

The duty cycle matters as much as the conditional rate. Even on the busiest pool, **82.1% of slots
contain no pool-referencing transaction at all**; on the other five pools it is 98.5–99.9%. A send
placed at an arbitrary moment is overwhelmingly likely to be alone. The scalper's liveness filter
(`max_trade_recency_s` drawn from 5–30s, `shitcoims_scalper/policy.py`) deliberately fires *after*
activity, which is exactly the adverse selection to watch — but the tape's own conditional rates by
gap-since-last-activity are non-monotone once router bursts are separated out, and I do not
consider that question answered here.

---

## 3. The fee identity, verified on our own money

```
fee_lamports = 5000 * n_signatures + ceil(cu_price_microlamports * cu_LIMIT / 1_000_000)
```

**4,130 of 4,130 sampled transactions match exactly. Zero mismatches.**

The load-bearing word is **LIMIT**. You are charged on the compute units you *requested*, not the
ones you *consumed*. Solana's fee docs give the same formula
(`micro_lamport_fee = compute_unit_price * compute_unit_limit`, then
`prioritization_fee = ceil(micro_lamport_fee / 1_000_000)`), with 5,000 lamports per signature and
100% of the priority fee going to the validator since SIMD-0096 activated 2025-02-12. Verifying it
against 4,130 real transactions on our exact pools costs nothing and removes the whole class of
"the docs might be stale" doubt.

### What that costs the ambient trader

| path / kind | n | consumed p50 | p99 | max | limit p50 | limit÷consumed p50 |
|---|---|---|---|---|---|---|
| direct-AMM swap | 238 | 103,488 | 135,691 | 141,570 | **200,000** | **1.78×** |
| jupiter swap | 230 | 142,371 | 894,166 | 1,275,051 | 200,000 | 1.25× |
| third-party attempt | 2,297 | 116,554 | 294,822 | 513,695 | 299,369 | 3.25× |

**88.7% of direct-AMM swaps over-request by more than 1.5×**, wasting a median of 87,475 CU of paid
budget. The `limit p50 = 200,000` is not a coincidence: pump.fun's own frontend ships
`AMM_BUY_SELL_DEFAULT_UNITS = 200_000`
(<https://github.com/pump-fun/pump-fun-skills/blob/main/swap/scripts/lib/constants.mjs>). Copying
that constant means paying ~1.8× the necessary priority fee on every swap.

An independent measurement over 82,265 successful mainnet transactions in 75 blocks
(2026-08-14 00:04–03:36 UTC) puts whole-transaction PumpSwap CU at p50 **102,012** / p90 171,459,
against our 103,488 / 122,786 on our own pools. **Two independent samples, 1.5% apart on the
median.** Published buffer guidance: Anza and the Solana cookbook say 10%
(`Math.floor(computeUnits * 1.1)`,
<https://solana.com/developers/cookbook/transactions/optimize-compute>), Jupiter says *"at least a
1.2x buffer"*, and Helius's Rust SDK ships `CU_BUFFER_MULTIPLIER_DEFAULT: f32 = 1.25`.

**Compute exhaustion is not a real failure mode for us.** Across all 19,061 tape failures there are
**35 `ComputationalBudgetExceeded` (0.18%)**. Zheng et al.'s taxonomy over 1.5B failures puts "out
of resource" at **0.49%** and price/slippage + validity expiry at 84.9% combined. Both say the same
thing: failures are lost races, not exhausted budgets.

---

## 4. The bid buys landing, and it is nearly free

Landing rate against `cu_price`, population-reweighted:

| bid (µL/CU) | Jupiter | direct-AMM | third-party |
|---|---|---|---|
| 1–10k | 23.0% | 100% (n=1) | 0.7% |
| 10–50k | **26.6%** | 93.8% | 4.3% |
| 50–100k | **100%** | 90.7% | 13.9% |
| 100–300k | 98.3% | 99.4% | 22.6% |
| 300k–1M | 91.1% | 100% | 39.7% |
| >1M | 100% | 86.0% | 52.7% |

On the Jupiter path there is a **cliff between 10–50k and 50–100k**: 26.6% → 100%. On the
third-party path the response is monotone across two orders of magnitude, 0.7% → 52.7%. The
direct-AMM path is robust everywhere (≥86%) — its landing does not depend much on the bid, which is
consistent with those transactions rarely being in a race at all.

Collapsing to either side of the cliff makes the point sharply:

| | est. swaps | est. failures | landing |
|---|---|---|---|
| direct-AMM, bid < 50k | 348 | 19 | 94.8% |
| direct-AMM, bid ≥ 50k | 631 | 29 | 95.6% |
| Jupiter, bid < 50k | 139 | 330 | **29.6%** |
| Jupiter, bid ≥ 50k | 350 | 10 | **97.2%** |

Jupiter's landing rate more than triples across a threshold that costs a fortieth of a cent to
clear. Direct-AMM barely moves. **The bid is the lever; the path is the fallback.**

The mechanism is §2's duty cycle. A direct AMM call is typically the only transaction touching that
pool in that slot — 82% of slots are empty even on the busiest pool, 98.5–99.9% on the others — so
there is no race to lose and the bid does not matter. A Jupiter route's `minOut` is checked across
the whole route against a quote built some slots earlier, so it is exposed to *any* pool on the
route moving, and buying a better queue position is what protects it. Consistent, but not
established: this is an interpretation of the tables, not a separate measurement.

And 94% of sampled Jupiter failures are `Custom(6001)` = `SlippageToleranceExceeded`
(<https://github.com/jup-ag/instruction-parser/blob/main/src/idl/jupiter.ts>). The sampled
direct-AMM failures are PumpSwap `Custom(6004) = ExceededSlippage` and
`Custom(6040) = BuySlippageBelowMinBaseAmountOut`. **Failure on this venue is a slippage revert,
i.e. losing a race, and the bid is how you enter the race.**

### `getRecentPrioritizationFees` is the wrong instrument, measured

The RPC everyone reaches for when sizing a bid, called live against our own pools
(`--fee-oracle`, 2026-08-14T04:00Z, 150-slot window):

| query | slots | fraction returning **zero** | p99 | max |
|---|---|---|---|---|
| global (no accounts) | 150 | **100.0%** | 0 | 0 |
| DREGG/SOL | 150 | **100.0%** | 0 | 0 |
| SOLVE/SOL | 150 | **100.0%** | 0 | 0 |
| weave/SOL | 150 | 99.3% | 0 | 38,985 |
| nosis/SOL | 150 | 98.7% | 15,000 | 100,000 |

It reports, per slot, the **minimum** prioritization fee among transactions that locked those
accounts. Nearly every block contains someone paying nothing, so the minimum is nearly always zero.
**Used as a bid estimator it answers "bid 0" to every question** — and §4's dose-response says a
zero bid lands 57% on the Jupiter path and 3.8% on the bot path.

The instrument that works is already in the tape: the percentiles of the bids that actually
*landed*. That is what the ladder below reports, and what §8's rule reads from.

### The bid ladder among landed swaps (µL/CU)

| pool | n | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|
| DREGG/SOL | 81 | 30,000 | 157,159 | 500,000 | 4,166,666 |
| SOLVE/SOL | 165 | 30,000 | 53,805 | 263,157 | 970,147 |
| nosis/SOL | 700 | 60,000 | 229,249 | 1,056,415 | 3,636,363 |
| weave/SOL | 296 | 25,000 | 151,813 | 729,071 | 2,500,374 |
| **ALL** | 1,320 | 30,000 | 158,832 | 734,651 | 3,023,760 |

### What it costs (at a 160,000 CU limit, SOL=$75.75)

| cu_price | fee lamports | fee $ | bps of $9 | bps of $50 | bps of $150 |
|---|---|---|---|---|---|
| 0 | 5,000 | 0.0004 | 0.4 | 0.1 | 0.03 |
| 30,000 | 9,800 | 0.0007 | 0.8 | 0.1 | 0.05 |
| 50,000 | 13,000 | 0.0010 | 1.1 | 0.2 | 0.07 |
| **100,000** | **21,000** | **0.0016** | **1.8** | **0.3** | **0.11** |
| **300,000** | **53,000** | **0.0040** | **4.5** | **0.8** | **0.27** |
| 1,000,000 | 165,000 | 0.0125 | 13.9 | 2.5 | 0.83 |
| 3,000,000 | 485,000 | 0.0367 | 40.8 | 7.3 | 2.45 |

**This is the whole argument.** Moving from the losing side of the Jupiter cliff (30k) to
comfortably above it (300k) costs **43,200 lamports = $0.0033 = 3.6 bps of a $9 clip**. People fail
because they bid nothing, not because bidding is expensive. At our size the budget constraint never
binds; the only reason not to bid higher is that the curve is already flat.

### Does the bid *cause* the landing? Honestly: not established here.

Within-slot matched test — slot as a fixed effect, so network load, leader identity and time of day
all cancel:

| restriction | slots | winner bid higher / lower | sign-test p | AUC |
|---|---|---|---|---|
| all transactions | 169 | 123 / 37 | **5.5e-12** | 0.735 |
| jupiter + direct-AMM only | **13** | 7 / 5 | 0.774 | 0.640 |

The unrestricted result is overwhelming and **confounded**: mixed slots are dominated by bot-vs-bot,
and "higher bid" is collinear with "different program". Restricting to comparable execution paths
leaves 13 slots, which is underpowered — it neither confirms nor refutes.

> **What would settle it:** randomising our own bid across a fixed ladder on real sends and logging
> the propensity. That is the same design `shitcoims_scalper/policy.py` already uses for its
> liveness thresholds, applied to `cu_price`. Nothing in a third-party tape can substitute for it,
> because we cannot observe what anyone else's software would have done at a different bid.

---

## 5. Sandwiches: the theory, and then the count

### 5.1 The threshold, derived and then found in the literature

For a constant-product pool with SOL side `Y`, LP fee `φ`, victim clip `B` and slippage tolerance
`s`, the attacker's optimal frontrun pushes the victim's execution to exactly their limit and no
further. Solving the constraint numerically (§G of the script) gives a striking result: **`s`
cancels out of the profitability condition.** The attacker must move the pool by `s`, which costs
him the LP fee on ~`Y·s/2` of capital twice; his revenue is ~`B·s`. Both are linear in `s`, so:

```
a sandwich is profitable only when   B  >  φ · Y
```

The numeric solve reproduces `φ·Y` to within 0.4% at every depth and every `s` from 0.5% to 15%.
This is not novel — it is Heimbach/Schertenleib/Wattenhofer (arXiv:2306.05756) Lemma 2, *"a
profitable attack only exists if the victim's trade size δ exceeds a fee dependent threshold
δ_min = f(1−p)x/(1−f)²"* — but deriving it independently and landing on the published lemma is the
strongest check available that the model is right.

At φ = 25 bps and our measured depths:

| pool | median SOL side | sandwich threshold `φ·Y` | in dollars |
|---|---|---|---|
| SOLVE/SOL | 101.1 | 0.253 SOL | **$19.15** |
| weave/SOL | 183.4 | 0.459 SOL | **$34.73** |
| DREGG/SOL | 376.5 | 0.941 SOL | **$71.30** |
| nosis/SOL | 382.4 | 0.956 SOL | **$72.44** |

**A $9 clip is below the attack floor on every one of our pools.** A $50 clip is above it on
SOLVE and weave. A $150 clip is above it everywhere.

Above the threshold, `slippage_bps: 1500` is exactly as bad as PROGRAM.md §1.4 says: a $150 clip
(1.98 SOL at $75.75) into the 101-SOL pool loses **$19.75 (1,317 bps)** at 15% versus **$1.33
(89 bps)** at 1%. That same clip is 1.96% of that pool's SOL side — right at the `rho_max = 200 bps`
ceiling `policy.py` already enforces, so the impact cap and the sandwich cap bind at nearly the same
place there and diverge on the deeper pools. The
correct statement is sharper than "1500 bps hands them their optimum": **slippage sets how much they
take; depth versus clip sets whether they bother.** Both need fixing, and they are different fixes —
tighten `slippage_bps`, and cap size at `φ·Y` when you want structural immunity rather than a
bounded loss.

### 5.2 How many sandwiches actually happened on our pools? Zero.

The tape carries no transaction index, but it carries pre/post vault balances, and a writable-account
lock is exclusive — so swaps on one pool in one block chain: `post` of one is `pre` of the next.
Following that chain reconstructs the exact intra-slot execution order. **It closes for 382 of 382
multi-swap slots**, which is the check that the reconstruction is right.

Two detectors over 2,859 chainable swaps:

| detector | result |
|---|---|
| round-trip wrapping other traders, same slot | **0 candidates** |
| same, within 1 slot | **0** |
| same, within 5 slots | **0** |
| same, within 50 slots | 12 candidates, **all with negative attacker PnL** |
| signature-only: any counterparty on both sides of one slot | **0 of 172 slots with ≥3 swaps** |

The 50-slot row is the control: relax the window far enough and the detector starts firing, and
everything it catches *loses money* — which is what an ordinary round-tripping trader looks like,
not an attacker. A detector whose only hits are unprofitable is measuring noise, and knowing where
that begins bounds the strict result.

**Exposure:** 831 ambient trades on these pools exceeded `B > φ·Y` and were therefore worth
attacking. None was attacked. By the rule of three, the 95% upper bound on the per-attackable-trade
attack rate is **0.36%**.

This directly contradicts the ambient narrative — the top ten most-sandwiched Solana pools are all
PumpSwap, and 129,052 sandwiches were recorded network-wide in the 30 days to 2026-08-13 — and the
reconciliation is depth. Our pools are graduated and 101–382 SOL deep; the sandwiched population is
thin pools where `φ·Y` is a couple of dollars. **No published measurement of pump.fun/PumpSwap
swap-level sandwich or failure rates exists** (searched Dune, Blockworks, Helius, Bitquery, arXiv),
so this is, as far as I can tell, an original measurement — on four pools over ~30 hours.

**Falsification.** This claim dies if the same detector run on a fresh tape window finds even one
same-slot round-trip with positive attacker PnL wrapping a third party. It is also evadable in a
way I cannot rule out: ~93% of Solana sandwiches are now reported to be "wide" (frontrun and backrun
in *different* blocks), and a wide sandwich using two different wallets defeats both detectors here.
The honest scope is: **no atomic same-slot sandwich, and no profitable round-trip attacker within 5
slots, on these four pools in this window.**

---

## 6. Why transactions fail, priced

| | outcome | base fee | priority fee | Jito tip | in our tape? |
|---|---|---|---|---|---|
| A | landed + succeeded | paid | paid | paid | yes (`swap`/`reference`) |
| B | **landed + failed** | **paid** | **paid** | rolled back | yes (`attempt`) — all 19,061 |
| C | **never landed** | zero | zero | zero | **structurally invisible** |

The B/C line is fee-payer validation: *"If account loading fails but the fee payer was successfully
validated, the transaction becomes a `FeesOnly` result: the fee is still collected but no
instructions execute"* (<https://solana.com/docs/core/transactions/transaction-pipeline>).

Three corrections worth carrying:

- **`InsufficientFundsForRent` is a post-execution check and therefore always costs a fee.** It is
  routinely filed under "didn't land". It did.
- **SIMD-0191 (activated) moved loading failures from free to fee-charged** — exceeding the loaded
  account-data cap, and invalid/non-executable program accounts, now bill you. Its own Impact
  section: *"Users must be more careful when constructing transactions to ensure they are executable
  if they do not want to waste fees."*
- **A Jito tip is rolled back on a landed-but-failed transaction** — it is an ordinary SOL transfer,
  so only the fee survives. And a bundle that reverts never lands at all, so tip *and* fee are zero.

**Error codes are `(program_id, code)` pairs, never codes alone.** `Custom(6004)` is
`MintDoesNotMatchBondingCurve` on pump.fun's curve and `ExceededSlippage` on PumpSwap. The
instruction index in `InstructionError(i, …)` names the *outermost* instruction while the code comes
from the *innermost* program on the CPI stack, so joining index → `programIdIndex` mis-decodes
essentially every routed swap. Read `meta.logMessages` instead.

Slippage codes for the venues we touch: pump.fun curve **6002** (buy) / **6003** (sell) / 6042;
PumpSwap **6004** / 6040; Jupiter v6 **6001**; Raydium AMM v4 **30**; Raydium CPMM 6005.

**Blockhash and retry.** `MAX_PROCESSING_AGE = 150` slots, ~60s wall
(<https://github.com/anza-xyz/solana-sdk/blob/master/clock/src/lib.rs>; 151 hashes are "recent
enough"). The status-cache dedup key is `(message_hash, recent_blockhash)` and the cache holds 300
rooted slots — **2× the execution window** — so rebroadcasting the *same signed bytes* can never
double-execute, while re-signing with a **new** blockhash before the old one expires creates two
independently executable transactions. That is the double-fill. SIMD-0525 stages slot times down to
200ms while leaving `MAX_PROCESSING_AGE` at 150 *slots*, halving the wall-clock window: drive expiry
off `lastValidBlockHeight` and `getBlockHeight`, never `time.time()`.

**One live trap:** `preflightCommitment` defaults to `finalized`
(<https://solana.com/docs/rpc/http/sendtransaction>). Fetch the blockhash at `confirmed`, leave the
default, and preflight simulates against a bank that has never seen your blockhash and rejects a
perfectly good order.

---

## 7. Jito: no, for v1 — with the trigger to revisit

**What is genuinely attractive.** A bundle is all-or-nothing (`all_or_nothing: true`,
`drop_on_failure: true` in `bundle_consumer.rs`), so a reverting swap never lands and costs
**nothing** — it converts outcome B into outcome C. `bundleOnly=true` gets this for a single
transaction. The tip market is cheap: the live tip floor at 2026-08-14T03:28Z was p25 **1,000
lamports** (the enforced minimum), p50 1,899, p75 6,118; an independent sample of 400 recently
landed bundles gave p50 2,277 with **85.5% at or below 10,000 lamports**. And 90.25% of those
bundles held exactly one transaction, i.e. our use case is the modal use case.

**Why not, at our numbers.** Our measured direct-AMM failure rate is **4.7%**. Revert protection
therefore saves `0.047 × ~21,000 lamports ≈ 990 lamports ≈ $0.00007` per send. Against that: a
1 req/s/IP/region rate limit, no preflight, the uncled-block caveat where bundles get "unbundled"
and lose atomicity, and a leader-client dependency whose headline number is contested (~97% of stake
runs *some* bundle-accepting client; ~54% runs a Jito-branded one). Sandwich protection buys nothing
we can measure either — §5.2 bounds our attack rate at ≤0.36%.

**Revisit if** the instrumented landed-and-failed rate exceeds 15%, *or* if the §5.2 detector ever
fires on our own fills. Both are cheap to watch and both are in §8's instrumentation list.

**If we do adopt it:** tip in the *same transaction* as the swap (so a failure cannot cost the tip),
add a `jitodontfront`-prefixed read-only account (the block engine rejects any bundle where such a
transaction is not at index 0), and dual-route rather than sending Jito-only.

---

## 8. The landing policy

For a $9–$150 clip on a 100–400 SOL PumpSwap pool.

### Execution path
**Call the AMM directly.** Measured landing 95.3% vs 59.0% through Jupiter. 94% of sampled Jupiter
failures are `6001` — a quote that went stale between build and execution. Failing Jupiter
transactions also consume markedly more compute than landing ones (median 265,860 CU vs 142,371),
which is what a wider route looks like; that is suggestive of route width as the mechanism, not
proof of it. PROGRAM.md §1.4 already says we only ever want one pool, so if the aggregator is kept
for quoting, restrict it to a single direct route.

*Confound, stated:* these are other people's Jupiter transactions with other people's slippage
settings and other people's bids. A Jupiter call with our own `minOut` and a 100k+ bid would not
necessarily fail at 41% — the dose-response in §4 shows the Jupiter path itself landing 91–100%
above 50k µL/CU. The honest reading is that **path and bid are not separately identified here**, and
the direct-AMM recommendation is the one that is safe under either explanation.

### Compute-unit limit
`simulateTransaction` (with `replaceRecentBlockhash: true`), then `limit = ceil(consumed × 1.15)`.
Static fallback **160,000** — 13% above the largest direct-AMM consumption observed in 238 swaps
(141,570) and 18% above p99. **Do not ship pump.fun's own 200,000 constant**: it is 1.78× the median
consumption, and you are charged on the limit.

### Priority fee
`cu_price = clamp(pool p75 of landed bids, 100_000, 3_000_000)` µL/CU. The 100,000 floor sits well
clear of the 50k Jupiter cliff and coincidentally equals pump.fun's own frontend floor. At a 160,000
CU limit this is 21,000–485,000 lamports, i.e. **$0.0016–$0.037**, or 1.8–40.8 bps of a $9 clip and
0.11–2.45 bps of a $150 one. Recompute p75 per pool from the tape rather than hardcoding.

### Retry and blockhash
Fetch the blockhash at `confirmed`. **Sign once.** Rebroadcast the identical serialized bytes every
~400ms with `skipPreflight: true`, `maxRetries: 0`, `preflightCommitment: "confirmed"`; poll
`getSignatureStatuses` with `searchTransactionHistory: false`; exit when `getBlockHeight("confirmed")`
passes `lastValidBlockHeight`. Only then re-price and sign a new transaction.

**No bid escalation.** Changing `cu_price` requires re-signing, and re-signing inside the validity
window is the double-fill. The cost table is why this is fine: bid at the top of the useful range
once — it is under 15 bps even on the smallest clip.

### Slippage
Compute `minOut` from live reserves; ~100 bps plus a drift allowance, not 1500. `config.yaml` still
carries `slippage_bps: 1500` (this study does not own that file). Above `B > φ·Y` the loss is `s·B`
and someone will take it; below it, no setting matters.

### Sizing interaction
`B* = sqrt(priority × Y)` (`shitcoims_scalper/policy.py:97`) is sensitive to the priority-fee
constant, which the shadow model sets to 500,000 lamports. Our measured median network fee is
**55,000** and the policy above budgets 21,000–53,000. At Y = 100 SOL that moves B* from 0.22 SOL
to **0.046–0.073 SOL** — a 3–5× reduction in optimal clip. That is a real consequence of this study
for `shitcoims_scalper`, and it is not mine to change.

### Expected landing rate
**95–97%.** Direct-AMM above the cliff measures 95.6% (est. 631 vs 29, raw n=223); Jupiter above the
cliff measures 97.2% (est. 350 vs 10, raw n=171). Take **95%** as the planning number: it is the
lower of the two and it does not depend on which explanation of the path gap turns out to be right.

**Falsification: if the instrumented landed-and-succeeded rate over the first 100 real sends is
below 85%, the direct-AMM reference class is wrong and this policy is refuted.**

### Instrument these, from send #1

The tape can never supply them; only our own sends can.

1. **Every signature at submit time**, with `t_submit`, `blockhash`, `lastValidBlockHeight`,
   `cu_price`, `cu_limit`, simulated CU, quoted `minOut`, and pool reserves at quote. Reconcile
   against inclusion within 151 slots. **This is the only way to measure outcome C.** Without it we
   cannot tell a 95% landing rate from a 95% *conditional-on-landing* success rate over a 60% send
   rate.
2. **Outcome, in three buckets, never two:** succeeded / landed-and-failed (`meta.err` set,
   `meta.fee` charged, token balances unchanged) / never-landed. Log `meta.fee` and
   `computeUnitsConsumed` on every landed transaction so §3's identity keeps verifying, and so the
   next CU-limit rule is fitted rather than assumed.
3. **`meta.logMessages` on every failure**, not just the error code. `(program_id, code)` is the
   key; the raw code is ambiguous across programs.
4. **Randomised `cu_price`** across a fixed ladder with the propensity logged, exactly as
   `policy.py` already randomises its thresholds. This is what turns §4's confounded correlation
   into a causal estimate, and it costs single-digit basis points to run.
5. **Slot contention at send time** — how many transactions referenced the pool in the target slot —
   so §2's decline can be checked against our own fills rather than ambient traffic.
6. **Run §5.2's detector on our own fills weekly.** One positive hit flips the Jito decision.

---

## Appendix: what is asserted vs measured

**Measured on our data, reproducible by re-running the script:** every number in §1, §2, §3, §4
(including the live `getRecentPrioritizationFees` table, `--fee-oracle`), §5.1's grid and
thresholds, §5.2, and §8's expected landing rate.

**Externally cited, not verified by us:** the Helius and Zheng et al. failure-rate decompositions,
the Jito tip-floor snapshot, Agave/Anchor/IDL error tables, blockhash constants, SIMD-0096/0191/0525,
and the independent 82,265-transaction CU sample (which does agree with ours to 1.5% on the
PumpSwap median).

**Estimates, labelled:** SOL at $75.75 is a spot reading at one instant and every dollar figure
scales with it. `φ = 25 bps` is PumpSwap's nominal take; `scripts/sim2real.py` measures ~20 bps
realised on DREGG/SOL and SOLVE/SOL, which would move the `φ·Y` thresholds down ~20%. The
population-reweighted path landing rates carry stratum weights up to ~24× on the largest cell, so
their effective sample size is well below the raw 4,316.

**Known gaps:**
- Our drop rate (outcome C) — unmeasurable from any tape.
- Whether the bid *causes* landing at fixed execution path — 13 matched slots, underpowered.
- `Custom(5000)` is 20.1% of all tape failures and remains unidentified; it is emitted by
  `Prism8hsRo6Ww5jiN5Zeh3YDPLZHqHduCPSAV7JF7qv` and friends, and per Anchor's ranges a bare 5000 is
  not a user error code, so those programs number their own errors. It does not affect the policy
  because none of them is a path we would take.
- Wide (multi-slot, multi-wallet) sandwiches are invisible to §5.2.
- One window, six pools, ~30 hours. Every rate here should be re-measured before the next size-up.
