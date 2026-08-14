# Should the desk be the thing that gets crossed?

**Study:** `studies/jupiter_programs.py` — read-only Helius RPC plus Jupiter's public quote API.
Signs nothing, sends nothing. Re-run bare for everything, `--only inventory,interface,fillers,book,otoco,quotes,flash`
for a section.

**Method note that matters:** every Jupiter and lender claim below is checked against the
**program's own on-chain Anchor IDL**, read out of the IDL PDA, plus the live account and
transaction record. Not documentation. The IDL is the interface the validator actually runs
against, so where this report and a blog post disagree, this report is quoting the artifact.

**Prices:** SOL = **$75.75** (Jupiter quote 0.1 SOL → 7.573 USDC at 04:00Z; agrees with
`RESULT_execution_landing.md`'s independent $75.75 spot check). All dollar figures use it.

---

## The headline

The operator's mechanism is **real and correctly reasoned**. A resting Jupiter order is filled by
a counterparty who pays the gas, runs the latency race, and eats the revert. We verified the fill
path end to end: the filler bears the cost, and we bear none of it.

**And we should still not do it, for three reasons that are each independently sufficient.**

1. **The problem it solves has evaporated.** This study was commissioned on the premise that
   ambient landing runs 1%–52% and true friction could be 2–10× what shadow reports. While it was
   running, `studies/RESULT_execution_landing.md` **retracted that statistic** and `scripts/sim2real.py`
   now prints `***RETRACTED — DO NOT USE THESE NUMBERS***`. The corrected landing rate for a
   transaction shaped like ours is **95%–97%**. Maker-side execution is a cure for a 3–5% disease.

2. **The counterparty is not a market, it is one process.** Over **100.9 hours** and **143 fill
   instructions**, the number of distinct addresses that filled a Jupiter limit order was **one**:
   `j1opmdubY84LUeidrPCsSGskTCYmeJVzds1UWm6nngb` — 100.0%, a vanity address matching the program's
   own `j1o` prefix. The IDL permits anyone to fill; in practice a single Jupiter keeper does. We
   would be swapping a 95–97% landing rate we control for a dependency on a vendor process we
   cannot see, cannot page, and cannot replace.

3. **The option is priced, and it is more expensive than the spread.** A resting order is a free
   option written to the market, and we measured both sides. On weave at 0.5 SOL we save **1.27%**
   by not crossing, and give it back in written optionality after **10.8 minutes** of resting. On
   nosis, after **36 seconds**. Full table in §6.

**Flashloans: no.** Kamino's facility is real, permissionless, and genuinely free (**0.0000 bps**
actually charged, measured on 176–398 real cycles), and gas is far cheaper than the circuit model
assumed. But the only cycle with a positive residual needs the DREGG/nosis leg, and **Jupiter
returns `NO_ROUTES_FOUND`** for it. Meanwhile the capital-efficiency case is already solved on
chain: Meteora DLMM ships a native `rebalance_liquidity` instruction (543k CU), so there is no
pre-funding problem for a flashloan to fix — and at $12–$181 optimal clip sizes we were never
capital constrained anyway.

---

## 1. Program inventory, verified

`executable=true` is a near-worthless liveness test — a program nobody has called since 2025 is
still executable forever. So each ID is checked for existence **and** for when it last appeared in
a real transaction.

| program | ID | exec | last tx | status |
|---|---|---|---|---|
| Aggregator v6 | `JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4` | ✓ | seconds ago | **current** |
| Aggregator v4 | `JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB` | ✓ | minutes ago | legacy, still carrying traffic |
| Aggregator v3 | `JUP3c2Uh3WA4Ng34tw6kPd2G4C5BB21Xo36Je1s32Ph` | ✓ | 2026-07-28 (398 h) | effectively dead |
| Aggregator v2 | `JUP2jxvXaqu7NQY1GmNF4m1vodw12LVXYxbFL2uJvfo` | ✓ | 2025-09-23 (7,785 h) | dead |
| **Limit Order v2 / Trigger** | `j1o2qRpjcyUwEvwtcfhEQefh773ZgjxcVRry7LDqg5X` | ✓ | seconds ago | **current** |
| Limit Order v1 | `jupoNjAxXgZ4rjzxzPMP4oxduvQsQtZzyknqvzYNrNu` | ✓ | ~12 h | winding down |
| DCA / Recurring | `DCA265Vj8a9CEuX1eb1LWRnDT7uK6q1xMipnNyatn23M` | ✓ | ~1 h | current |
| Perps | `PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu` | ✓ | seconds ago | current |
| Vote / governance | `voTpe3tHQ7AjQHMapgSue2HJFAh2cGsdokqN3XqmVSj` | ✓ | minutes ago | current |
| Jupiter Lend flashloan | `jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS` | ✓ | seconds ago | current |
| Jupiter Lend lending | `jup3YeL8QhtSx1e253b2FDvsMNC87fDrgQZivbrndc9` | ✓ | seconds ago | current |
| Kamino Lend | `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD` | ✓ | seconds ago | **current, flashloans live** |
| Save (ex-Solend) | `So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo` | ✓ | seconds ago | **moribund: ~0.5 tx/min** |
| MarginFi v2 / Project 0 | `MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA` | ✓ | seconds ago | current, ~25 tx/min |
| Port Finance | `Port7uDYB3wk6GJAw4KT1WpTeMtSu9bTcChBHkX2LfR` | ✓ | 2026-07-28 | dead |
| Drift v2 | `dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH` | ✓ | minutes ago | current |
| PumpSwap AMM | `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA` | ✓ | seconds ago | our token/SOL pools |
| Meteora DLMM | `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo` | ✓ | seconds ago | our token/token pools |

**"Trigger" is not a new program.** The IDL at `j1o2q…` self-identifies as **`limit_order_2` v0.1.0**.
Trigger is Jupiter's API surface *over Limit Order v2* — the same eight instructions. Anything the
Trigger API appears to offer that `limit_order_2` cannot express is not on chain. This is the whole
of §5.

All are usable from a plain wallet with no allowlist. The one gate we found is an **API-side $5
minimum order size** (§4), not a program-side one.

---

## 2. What the deployed program actually is

Eight instructions: `initialize_order`, `fill_order`, `flash_fill_order`, `pre_flash_fill_order`,
`cancel_order`, `cancel_dust_order`, `update_fee`, `withdraw_fee`.

The `Order` account, in full:

```
maker, input_mint, output_mint, input_token_program, output_token_program,
input_mint_reserve, unique_id, ori_making_amount, ori_taking_amount,
making_amount, taking_amount, borrow_making_amount, expired_at,
fee_bps, fee_account, created_at, updated_at, bump, slippage_bps
```

Read that list for what is **absent**: no trigger price, no direction, no oracle account, no
reference to a linked order. The only condition this program can enforce is *"a taker delivered at
least `taking_amount`"*. That is a limit order and nothing else.

`ori_making_amount` alongside `making_amount` is the partial-fill ledger — the remaining amounts
decrement as the order is worked, so **partial fills are supported at the program level**. 1.07% of
the live book is partly filled and still resting.

### Is filling permissionless?

In `fill_order`, `jupiter_program` and `system_program` carry hard `address` pins. **`taker` carries
none** — it is `signer, writable` with no address constraint, no PDA seeds, no `relations`. The
interface names no privileged filler.

*Falsification:* an IDL cannot show `constraint = …` checks inside the handler body, so this is
necessary evidence, not sufficient. §3 tests it against practice, and practice says something the
IDL does not.

### The filler needs no capital

`pre_flash_fill_order` takes the **Instructions sysvar**. A filler may borrow the maker's own
escrowed input inside one transaction and repay by the end of it (`borrow_making_amount` is the
accounting field). A filler therefore does not need inventory to fill us. That is genuinely good
for a maker — it widens who *could* compete. It makes what §3 found more damning, not less.

---

## 3. Who fills, in fact

Sampled across **6,000 signatures spanning 100.9 hours**, stride-sampled so the window is covered
rather than the newest minutes.

| instruction | txs | failed | fail % | median CU |
|---|---|---|---|---|
| `initialize_order` | 567 | 7 | 1.2% | 64,829 |
| `cancel_order` | 486 | 2 | 0.4% | 21,717 |
| `fill_order` | 143 | 28 | **19.6%** | 165,259 |
| `withdraw_fee` | 4 | 0 | 0.0% | 70,460 |

**Distinct takers across 143 fills: 1.** `j1opmdubY84LUeidrPCsSGskTCYmeJVzds1UWm6nngb`, 100.0%.
Reproduced on an independent 500-tx sample: 59 fills, 1 taker, 100.0%. `flash_fill_order` was not
used once — the keeper funds fills from its own balance and routes through Jupiter v6.

This is the study's most important finding and it is a **distinction between a protocol guarantee
and a vendor convenience**. The protocol guarantees that *anyone may* fill. The market delivers
*exactly one* who does. Those two facts are identical in the IDL and opposite on a P&L:

- The operator's mechanism holds: the keeper eats a **19.6%** fill failure rate that would
  otherwise be ours. That is real and it is not nothing.
- But there is no competitive filler population bidding to fill us faster or tighter. If that one
  process is down, degraded, rate-limited, or simply not interested in a $9 clip on a
  pumpswap token, our order does not fill and **we have no recourse and no second venue.**

### The lifecycle ratio

Over the window: **567 created, 143 filled, 486 cancelled.** Of orders that *terminated*, **22.7%
did so by being filled and 77.3% by being cancelled** (21.2% / 78.8% on the replication sample).

*Falsification / caveat:* this is a **flow ratio, not a cohort** — the orders filled today were
posted days earlier, so this bounds the steady-state fill rate rather than giving a per-order
probability. It is still the right order of magnitude for planning: post four orders, expect to
cancel three.

Cancelling is not free. Each cancel is a transaction we must land (21,717 CU), and it is subject to
exactly the landing risk we were trying to escape. **Maker-side execution does not remove our
transactions from the landing race; it replaces one send (the swap) with two (create + cancel) in
the ~77% of cases where we do not get filled.**

---

## 4. The resting book: 200,785 live orders, decoded

Fetched every `Order` account on the program and decoded it.

> **Decoding note, because it nearly produced a fabricated finding.** `expired_at` is a borsh
> `Option<i64>`: **one** byte when `None`, **nine** when `Some`. Every field after it shifts. A
> fixed-offset decode passed a sanity check on `created_at` (both candidate offsets held plausible
> timestamps) while reporting a **19,166 bps maker fee** — a 190% fee, obvious nonsense, which is
> the only reason it got caught. The corrected decode gives 10 bps. Any figure below that looks
> too clean was re-derived after this fix.

| property | measured |
|---|---|
| **maker fee** | **10 bps on 91.8%** of orders; 81 bps 7.1%; 30 bps 0.5% |
| **rent escrowed** | **0.00348 SOL/order** ($0.26), refunded on cancel/fill — 702 SOL across the book |
| **slippage allowance** | 75.8% at **0 bps**; **24.1% at exactly 69 bps**; rest negligible |
| **expiry** | **98.4% perpetual**, only 1.6% dated |
| **expired yet still resting** | **542 orders**, median **443 days** past expiry, holding 1.886 SOL |
| **partial fills resting** | 2,157 (1.07%) |
| **age** | median **564 days**; 80.7% older than a year |
| **minimum size** | **$5 USD**, enforced API-side (`"Order size must be at least 5 USD"`) |

Two of these are maker failure modes with hard numbers on them:

**Escrow is not auto-returned at expiry.** 542 orders sit expired — median 443 days, max 782 —
still holding their escrow and rent. Expiry only stops an order being *fillable*; it does not
return anything. Someone must still land a `cancel_order`. Funds we post are funds we must
actively retrieve, and retrieving them is another transaction in the landing race.

**24.1% of the book pre-authorises a worse fill.** `slippage_bps` lets the program accept a fill
delivering *less* than `taking_amount`. Three quarters of orders set it to zero; a quarter carry
exactly 69 bps. This is the mechanism behind the UI's "you may get less than $80" warning (§5).

**Survivorship warning:** this is by construction the book of orders that have **not** filled.
Orders posted near the market fill and vanish. The 564-day median age describes what a stale order
looks like, **not** the expected life of an order we would post. It is not evidence that our order
would rest for 564 days.

---

## 5. OTOCO: what is guaranteed, and what is a vendor promise

**Verdict: the stop-loss leg is not an on-chain object at all. Neither is the OCO linkage.**

Three independent lines of evidence, in increasing strength:

**(a) There is nowhere to put it.** The `Order` account has no trigger price, no direction, and no
oracle (§2). A program cannot enforce a condition it cannot store.

**(b) No resting order is priced through the market.** Of **1,552** live SOL→USDC sell orders,
**1,552 (100.00%) are priced above market** and **0 (0.00%) at or below**. This is the empirical
signature. A limit sell rests *above* market and waits. A stop sells when price falls *through* a
level — posted as a resting order it would sit *below* market and be taken instantly at that
discount. Their complete absence is the evidence that stops are not resting here.

**(c) The API accepts stop parameters and discards them.** We asked Jupiter's Trigger API to build
orders with `triggerPrice`, `stopLoss`, `orderType: "stopLoss"` and `oco: true`. All four were
accepted with HTTP 200 — and the resulting `initialize_order` instruction data was **byte-for-byte
identical** to the plain order in every case (modulo `unique_id`, randomised by design). They are
silently ignored no-ops.

And the API will happily build an order priced **50% below market**, which would rest on chain
fillable immediately at that discount, with no warning.

### So what is a Jupiter stop-loss, mechanically?

It is a **Jupiter-side watcher**. The stop level lives in Jupiter's infrastructure. When price
crosses it, Jupiter's keeper submits an order — and that submitted order carries a **non-zero
`slippage_bps`** so the fill actually happens against a moving market. That is precisely what *"Stop
loss sells fast, so you may get less than $80"* means: there is **no price guarantee**, only a
bounded concession, and the bound is the `slippage_bps` on the order the keeper writes.

**The consequences are the ones that matter to a trading desk:**

- If Jupiter's keeper is down, rate-limited, or declines to act, **the stop does not exist.** There
  is no on-chain object that fires. Nothing on chain is watching.
- The OCO linkage — first fill cancels the other leg — is a keeper sending a `cancel_order`. It is
  a transaction that must land. If it does not land, **both legs can fill.**
- The "one-triggers" leg is the same: the TP/SL legs do not exist on chain until the entry fills
  and Jupiter creates them.

**A stop that lives only in a vendor's off-chain keeper is not the same object as one enforced by a
program, and it must not be modelled as one.** If the desk ever books a Jupiter stop as a
risk limit, that is a fabricated guarantee of exactly the family as the fabricated cost basis in
`joshibot-fabricated-cost-basis` — a number the system reports as certain that the world does not
owe us.

*Falsification:* this would be overturned by finding a resting order priced through the market in
size, or by an `initialize_order` whose args differ when a trigger field is supplied. We looked for
both; neither exists.

---

## 6. Can we use it on our pairs, and what does it cost?

**Yes, Jupiter quotes and routes all four cluster tokens.** Every quote below is a live API
response.

| pair | 0.1 SOL | 0.5 SOL | 2 SOL | 5 SOL | route |
|---|---|---|---|---|---|
| SOL→WEAVE | 2.37% | 2.74% | 4.11% | 6.74% | Pump.fun AMM |
| SOL→NOSIS | 2.13% | 2.35% | 3.17% | 4.76% | Pump.fun AMM |
| SOL→DREGG | 2.03% | 2.24% | 3.02% | 4.54% | Pump.fun AMM |
| SOL→SOLVE | 2.57% | 3.35% | 6.18% | 11.38% | Pump.fun AMM |

(figures are **round-trip** cost: buy then immediately sell back — the full cost of being the taker)

Degradation is gentle to ~2 SOL and steep after. SOLVE is the thinnest: it more than quadruples
from 0.1 to 5 SOL. **Nothing here supports trading above ~2 SOL a clip.**

**Jupiter does not route through our token/token DLMM pools.** WEAVE→NOSIS goes **PumpSwap +
PumpSwap through SOL**, not through the direct `weave/nosis` DLMM pool. Forcing `dexes=Meteora DLMM`
shows why: the DLMM route exists but quotes **13.1%** impact against **2.2%** for the double-hop.
`DREGG→NOSIS` forced to DLMM returns **`NO_ROUTES_FOUND`** outright.

This sharpens the network map's "~100% router-fed" finding: Jupiter **is** feeding our pools, but
it feeds the **PumpSwap token/SOL legs**. Our token/token DLMM liquidity is indexed and passed over.
That is consistent with the swing study's falsification (`RESULT_circuit_model.md` §5: token-token
turnover 30.6%/day vs 258.1%/day for token/SOL) — the router is telling us the same thing the
turnover did.

### Pricing the option we would write

This is the ask: *a resting order is a free option you WRITE to the market — price that.*

Realized volatility from the cluster tape (log returns between consecutive swaps, variance per
second scaled to the hour):

| pool | n | window | σ/hour |
|---|---|---|---|
| DREGG/SOL | 81 | 10.9 h | 2.1% |
| SOLVE/SOL | 165 | 29.3 h | 5.3% |
| weave/SOL | 296 | 6.4 h | 7.5% |
| nosis/SOL | 2,317 | 6.5 h | 27.1% |

A resting order is short an option struck at our limit price: we are filled exactly when the market
has moved to make our price stale, and not filled when it moves away. Using the standard ATM
approximation (premium ≈ `0.4·σ·√T`), against the taker cost we save by not crossing
(`round-trip/2 − 10 bps maker fee`):

| pool | σ/h | size | round trip | saved per leg | **break-even resting time** |
|---|---|---|---|---|---|
| nosis/SOL | 27.1% | 0.5 SOL | 2.38% | 1.09% | **0.6 min** |
| weave/SOL | 7.5% | 0.5 SOL | 2.74% | 1.27% | **10.8 min** |
| weave/SOL | 7.5% | 2 SOL | 4.11% | 1.95% | **25.5 min** |
| SOLVE/SOL | 5.3% | 0.5 SOL | 3.35% | 1.57% | **32.6 min** |
| DREGG/SOL | 2.1% | 0.5 SOL | 2.24% | 1.02% | **1.5 h** |
| DREGG/SOL | 2.1% | 5 SOL | 4.54% | 2.17% | **6.8 h** |

**Rest longer than that and the option costs more than the spread it saved.** On nosis the budget
is under a minute.

And the compensation structure is the worst possible version of this trade: **Jupiter pays the
maker no rebate at all.** We *pay* 10 bps for the privilege. Unlike a CLOB maker who is paid a
rebate, or an LP who earns fees on the flow that crosses them, a Jupiter limit-order maker's only
compensation is the price improvement they name — and they are filled preferentially precisely when
that improvement has gone stale. **We would be writing an option and collecting no premium.**

*Falsification / caveats, stated plainly:* `0.4·σ·√T` is the at-the-money approximation. A resting
order placed away from market is out-of-the-money, so its true premium is **lower** than the table
says and the break-even times are correspondingly **longer** — this table is a lower bound on the
horizon, not a point estimate. The nosis σ is measured over a 6.5-hour window and is extreme (27%/h,
2537% annualised); it should be re-measured over a longer window before being leaned on. But the
weave and DREGG numbers are calm-market figures and they still put the budget in the tens of
minutes, against a book whose median order is 564 days old.

---

## 7. Flashloans

### The facilities, verified

Every program ID below was checked with `getAccountInfo` (executable) and `getSignaturesForAddress`
(liveness). Fees for Kamino are read from its own on-chain `Reserve` accounts
(`config.fees.flashLoanFeeSf`, a U68F60 scaled fraction).

| facility | program ID | permissionless | fee | setup |
|---|---|---|---|---|
| **Kamino KLend** | `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD` | yes | **0.1 bps** SOL/USDC/USDT, **0** on most | none (ATA only) |
| MarginFi v2 / "Project 0" | `MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA` | yes (since 2024-03) | **0** | account, 0.017 SOL rent |
| Jupiter Lend flashloan | `jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS` | yes | 0, admin-settable | none |
| Save (ex-Solend) | `So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo` | yes | **5 bps** main pool | none |
| Drift v2 `beginSwap`/`endSwap` | `dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH` | yes | 0 | **6-program whitelist between brackets — rules it out** |
| Port Finance | `Port7uDYB3wk6GJAw4KT1WpTeMtSu9bTcChBHkX2LfR` | legacy callback | 30 bps | dead: last tx 2026-07-28 |

Kamino's fee distribution across all **560** reserves: **503 at 0.0000 bps**, 39 at 0.1 bps
(including the main-market SOL reserve `d4A2prbA2whesmvHaL88BH6Ewn5N4bTSU2Ze8P6Bc4Q`), 3 at 30 bps,
1 at 1,000 bps, and **14 disabled**.

> The disable is an exact sentinel, not a big number: `flash_loan_fee_sf == u64::MAX` →
> `LendingError::FlashLoansDisabled`. Scaled by 2^60 that reads as *exactly* 160,000.0000 bps, so a
> naive "fee > 100 bps means disabled" heuristic gets the right answer for the wrong reason and
> would misclassify the genuine 1,000 bps reserve. The script matches the raw u64.

Enforcement is `flash_borrow_reserve_liquidity` + `flash_repay_reserve_liquidity` with the
**Instructions sysvar** and a `borrowInstructionIndex: u8`: repay names the index of its borrow.
Both must be **top-level** (`get_stack_height() > TRANSACTION_LEVEL_STACK_HEIGHT` → `FlashBorrowCpi`
/ `FlashRepayCpi`), amounts and account lists must match byte-for-byte, and only one flash borrow
per transaction is allowed (`MultipleFlashBorrows`). Arbitrary third-party instructions **may** run
between the pair — the scan `continue`s past anything that is not a Kamino flash instruction. Save
is live but costs 5 bps and permits only one asset per transaction; Drift is disqualified by a hard
whitelist (OpenBook, Jupiter v3/v4/v6, DFlow, Titan) that excludes Meteora and PumpSwap entirely.

> **Discriminator trap, recorded because it produced a confident wrong answer.** Anchor derives an
> instruction discriminator from the **snake_case** Rust fn name, while the legacy IDL spells it
> camelCase. Hashing `global:flashBorrowReserveLiquidity` yields eight bytes matching nothing — a
> first scan of 1,280 transactions reported **0 flashloans, 0.00%**, which read as a clean finding.
> Hashing `global:flash_borrow_reserve_liquidity` against the *same* sample found **398 (31.1%)**.

### Measured from real transactions

| | value |
|---|---|
| share of all Kamino traffic that is a flashloan | **31.1%** (398/1,280); 35.2% on replication |
| fee **actually** charged (`repay − borrow`) | **0.0000 bps** — median, min *and* max |
| success rate | **7.2%** (22/306); 8.5% on replication |
| CU, successful cycle | median **464,310**, p90 555,416 |
| CU, failed cycle | median 208,032, p90 379,327 |
| tx fee, failed | median **10,420 lamports** ($0.0008) |
| **all-in cost per successful cycle** | **0.000882 SOL ≈ $0.067** |

Two things fall out of this that change how the desk should think:

**The 7.2% success rate independently corroborates the landing retraction.** `RESULT_execution_landing.md`
decomposes cluster failures and finds *third-party private arb programs land 7.3%* — from the
cluster tape. We measured **7.2%** from Kamino's transaction record, a completely different dataset
and a completely different method. Two independent instruments agreeing to a tenth of a point on
"arb bots abort constantly and that is normal" is strong evidence the retraction is right and the
original 1%–52% framing was measuring other people's spam.

**A failed flashloan is nearly free.** The loan never happens; only the fee burns, median 10,420
lamports. This is the pattern's real attraction: it converts execution risk into a cheap revert.
Which means **the circuit model's gas assumption was too pessimistic** — it charged **$0.30** per
loop; the measured all-in cost per *successful* loop is **$0.067**, roughly 4.5× cheaper.

### Is a zap across our own pools worth anything?

Re-pricing `RESULT_circuit_model.md` §3's table with the measured $0.067 gas instead of $0.30 moves
`DREGG→SOL→DREGG` from **−$0.18 to about +$0.06** at `W=4.0`. So gas was never the binding
constraint. **It still is not worth building**, for a reason gas cannot fix:

1. **The profitable cycle is not routable.** The only clearly positive residual,
   `DREGG→SOL→nosis→DREGG` (+$0.37 to +$9.86), needs the **DREGG/nosis** leg — and Jupiter returns
   **`NO_ROUTES_FOUND`** for `DREGG→NOSIS` on DLMM (§6). Jupiter's free route sends it
   PumpSwap→PumpSwap **through SOL**, which degenerates the triangle into a double round-trip
   through SOL and is guaranteed to lose. Executing the real cycle means CPI'ing Meteora DLMM
   directly — building and maintaining our own router — for a $0.37–$9.86 gross residual whose
   own study calls it *"entirely dependent on an unmeasured DLMM concentration factor."*
2. **The measurement cannot resolve the trade.** The residual is measured at 105–146 bps of
   aggregator disagreement against fee bands of 186–342 bps, and *the verdict on a given cycle
   flips between runs four hours apart.* We would be building an execution path to harvest a
   quantity our instrument cannot sign.
3. **A +$0.06 edge is not an edge.** It is noise around zero on a residual that is itself noise.

### The capital-efficiency case — the more plausible one — is already solved

The stronger argument was atomic LP re-centering without pre-funding both legs. Two findings kill it:

- **Meteora DLMM already ships `rebalance_liquidity`** as a native instruction. Measured on chain:
  median **543,242 CU**, p90 609,448. Re-centering a position is *already* one atomic instruction.
  There is no pre-funding problem for a flashloan to solve.
- **We are not capital constrained.** Optimal clip size on the only live residual is **$12–$181**.
  A desk trading $9 clips does not need a flashloan to find $181.

### The transaction budget — and the constraint that is actually binding

Solana's ceiling is **1,400,000 CU/tx** (`MAX_COMPUTE_UNIT_LIMIT`; a larger request is silently
clamped, not rejected). Measured components:

| component | median CU | source |
|---|---|---|
| Kamino borrow+repay **bracket alone** | **57,397** (borrow 31.8k + repay 25.4k) | live simulation, 12 accounts, 557 bytes |
| flashloan **full cycle** incl. route | 464,310 | measured, real mainnet txs |
| DLMM `rebalance_liquidity` | 543,242 | measured, real mainnet txs |
| DLMM `remove_liquidity_by_range2` + `claim_fee2` | 313,785 | measured, real mainnet txs |
| single swap | 123,615 (p90 339,095) | `scripts/sim2real.py` |

Flashloan + rebalance ≈ **1.01M CU** median, ~1.16M p90 — it fits, with ~20% headroom.
*Labelled estimate:* CU does not add exactly across composed instructions.

**But CU is not the wall. The 64-account-lock limit is.** A composed flashloan + 2 swaps + LP
rebalance needs an estimated **55–75 unique accounts**, and the cap is 64. Evidence that this is a
real, live constraint rather than a theoretical one: in mainnet slot 439,154,940 (970 non-vote
transactions), accounts-per-tx **p99 = 64, max = 64, with 55 transactions sitting at exactly 64 and
none above** — the cap is visibly clipping real traffic. In the same block, p99 CU was 199,014 and
**not one transaction exceeded 1M CU**. Address lookup tables compress *bytes*, not locks: an
ALT-referenced account still takes a full lock, and program IDs, the fee payer and all signers must
remain static.

So the honest CU verdict is inverted from where one would expect it: **the budget is not the
blocker, and neither is transaction size — the account cap is, and the absence of a trade is.**

**One operational finding worth extracting regardless of the flashloan verdict.** Solana's cost
tracker charges each writable account the transaction's **requested** CU limit, not what it
consumes, against a 40M-per-account-per-block budget. A transaction requesting 1.4M "just in case"
consumes 1.4M of a hot pool's budget — about 28 such transactions can touch that pool per block,
versus ~400 if it requests a tight 100k. **The executor should request a tight CU limit**, sized
from the measured 123,615 median / 339,095 p90 swap cost. On our own thin pools, where we are one
of few participants, this is cheap self-protection.

---

## 8. Recommendation

**Do not move the desk to maker-side execution.** The mechanism is real — the filler does bear the
gas, the race, and the revert, and we verified that end to end. But:

- the landing problem it was meant to solve was **retracted mid-study** (95–97%, not 1%–52%);
- the counterparty is **one vendor keeper**, 100% of 143 fills, not a market;
- we would **pay 10 bps to write an option** with a break-even horizon of **0.6 minutes to 6.8
  hours** depending on the pair, and receive **no premium** for it;
- ~**77%** of orders terminate by cancellation, which *adds* transactions to the landing race
  rather than removing them;
- **we cannot chase.** Every strategy the desk runs is reactive to callouts and flow. A resting
  order is a commitment to a price made before the information arrives.

**What is worth taking from this study anyway:**

1. **`RESULT_execution_landing.md`'s bid finding is the actual answer to the landing question.**
   Jupiter-routed transactions land **29.6%** below 50k µL/CU and **97.2%** at or above it. That is
   a one-line configuration change with a 3× effect — vastly better return than re-architecting to
   maker-side execution. Verify the executor's compute-unit price floor sits above 50k.
2. **Use limit orders as a specialist tool, not an execution model.** They are legitimately good
   for a patient, pre-decided exit on a low-vol name — DREGG at 5 SOL tolerates a 6.8-hour rest.
   They are actively harmful on nosis, where the budget is 36 seconds.
3. **Never model a Jupiter stop-loss as a risk control.** It is an off-chain vendor watcher with no
   on-chain existence and no price guarantee. If the desk wants a stop that is enforced, it has to
   be our own process watching, and it should be described that way in every report.
4. **Do not build flashloan zaps.** Free money on the borrow, but no trade to put it into.
5. **Request a tight compute-unit limit in the executor.** Unrelated to everything above, but it
   fell out of the same measurement: the cost tracker charges every writable account our
   *requested* CU against a 40M/block budget, so an over-generous request throttles the very pools
   we trade. Size the request off the measured 123,615 median / 339,095 p90 swap.

**The strategic instinct underneath the question was right, though, and worth naming.** *Be the
thing that gets crossed rather than the thing crossing* is correct — it is simply that Jupiter's
limit order is the **worst-paying** way to express it. It charges 10 bps, pays no rebate, and hands
the option away for free. The version that pays is the one the desk **already owns**: the LP
position. An LP is crossed continuously, earns a fee on every crossing, and requires no keeper's
permission to be filled. The same instinct, pointed at `studies/lp_strategy.py` instead of at a
resting order, is where this should go.

---

## Falsification summary

| claim | how it dies |
|---|---|
| Filling is permissionless in the interface | an `address` pin or a body `constraint` on `taker`; we can only rule out the former |
| One keeper does all filling | any second taker address in a wider window; 0 found in 143 + 59 fills over 100.9 h |
| Stops do not rest on chain | one resting order priced through market in size; **0 of 1,552** |
| OTOCO fields are no-ops | `initialize_order` args differing when supplied; byte-identical in 4/4 |
| Maker fee is 10 bps | a different modal `fee_bps`; 91.8% of 200,785 orders |
| Kamino flashloans are free | a nonzero `repay − borrow`; median = min = max = 0.0000 bps on 398 cycles |
| Break-even rest is minutes | a lower realized σ; ours is tape-measured, and OTM placement lengthens it |
| DREGG/nosis is unroutable | a Jupiter route appearing; currently `NO_ROUTES_FOUND` |

**Known weaknesses of this study.** The filler-concentration result is 100.9 hours on one program —
it would not catch a keeper rotation on a monthly cadence. The volatility estimates come from
6.4–29.3 hour windows and nosis in particular needs re-measuring. The resting-book snapshot is
survivorship-biased by construction and is used only for failure modes, never for expected fill
time. The CU sum for flashloan + rebalance is arithmetic on separately-measured medians, not a
simulated composed transaction.
