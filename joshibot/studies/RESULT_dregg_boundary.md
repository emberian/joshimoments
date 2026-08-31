# RESULT: the creator-fee boundary — what it actually is, and whether it can be pressed

2026-08-15. Instrument: `studies/dregg_boundary.py`. Reproduce:
`uv run --group research python studies/dregg_boundary.py all`
(sections: `tiers history replay ladder size risk nulls`).

Data: the pump.fun fee program's own `FeeConfig` account (read-only `getAccountInfo`), the four
cluster mints' supplies (`getTokenSupply`), 1,058 decoded PumpSwap swap events from
`state/cluster_tape/`, 96,414 DREGG/SOL swaps with exact integer vault reserves from
`state/bulk_history/` (48 days), and the operator's complete claim ledger in
`.cache/position_history/`. **Nothing signed, nothing sent, no transaction constructed** — the
only network use is read-only Helius RPC (`getAccountInfo`, `getProgramAccounts`, `getTokenSupply`,
`getTransaction`, `getSignaturesForAddress`), which spends credits and not money. Results cached to
`studies/data/dregg_boundary/`, so a re-run is offline.

**The brief's four questions, answered in one line each.** (1) The tier is **spot, per swap, from
live pool reserves, denominated in SOL** — 25 rungs 5 bps apart, no TWAP, no hysteresis, no
ratchet; verified 1,058/1,058 with two rival specifications falsified. (2) The ladder backtest
finds **no arm beats its own window VWAP** and none clears its random-schedule null; what a ladder
buys is a **4× reduction in dispersion**, not edge. (3) Visibility is not the binding constraint —
one tranche is **0.95% of a day's volume** and $353; clip impact is. (4) **The boundary is
unpressable at this desk's size**: the rung is 11.5% away, one tranche moves 2.7%, the push is half
gone within a day, and the fee gain from crossing is cancelled by a fee-base term nobody had
written down — leaving only the escrow mark-down, which is unambiguously negative.

**This is a NULL on the campaign the operator proposed, and it saves a wasted one.** It also
corrects three upstream numbers, two of them against the desk.

---

## 0. What this found, in ten lines

1. **The fee schedule is not a three-step ladder in USD FDV.** It is a **25-rung step function in
   SOL**, read from `FeeConfig` at `5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx`. Rungs are 5 bps
   apart. `PROGRAM.md` §0's "0.95% under $300k, 0.60% to $1M, 0.35% above" does not exist on chain.
2. **It is evaluated fresh on every single swap from that swap's entry reserves.** DREGG's applied
   rate flipped 80→75→80→75 bps **inside four seconds** on 2026-08-14. No TWAP can do that; no
   ratchet can go back up. Predicting the applied rate from `quote × supply / base` is **exact on
   1,058 of 1,058 swaps across four pools**, while post-swap reserves miss 21 and dropping the
   virtual-reserve term misses 34 — the agreement is discriminating, not vacuous.
3. **DREGG is already on the good side of the boundary the operator wanted to cross.** Market cap
   **3,888 SOL** ($293,383 at $75.45/SOL), creator fee **80 bps**. The nearest rung *below* is
   3,440 SOL (−11.5%); the nearest *above* is 4,420 SOL = **$333,485**, not $300,000. There was
   never anything above us to press down through.
4. **Crossing a rung is a wash on fee income**, because of a term nobody had written down: creator
   fee = rate × **SOL volume**, and most flow is denominated in *tokens*, so the fee base falls
   with the price. Measured base-denominated share of quote volume **0.4996**, giving a closed-form
   **break-even distance** `d* = ln(85/80) / 0.4996 = 12.14%`. The rung below is **11.5–12.4%**
   away depending on the hour. The two terms cancel to within a few tenths of a percent and the
   sign flips with the day's price — so the fee arithmetic gives **no reason to press in either
   direction**, and the decision falls entirely to the terms that do not cancel: the escrow mark
   and the impact persistence.
5. **And the press is transient.** A single-tranche clip lands at −2.7%, is **half gone within a
   day** and indistinguishable from zero at three. Holding a price under a rung is a subscription,
   not a trade, and the entire realised inventory in DREGG's history is 3,613,087 tokens ($1,060).
6. **The sign of the joint position is REVERSED from `RESULT_toll_positioning.md` §5.** With the
   real table and the base term restored, a rally *up* through 4,420 SOL is **+0.37% on fee income**
   (another cancellation) and adds **+$2,367** of escrow mark. The desk is **long its own price
   essentially everywhere**. "Treat organic dips under the boundary as fee-accretive" should be
   retired.
7. **CORRECTION: the realised take is 1.00× the published ladder, not 0.93×.** 48 days of exact
   per-swap reconstruction gives **742.35 SOL** of creator fee; the operator's on-chain receipts
   over the same window are **752.98 SOL**, and the residual is a **constant 9.15 ± 0.36 SOL over
   213 claims** — the bonding-curve phase, which no AMM swap can reconstruct.
8. **CORRECTION: there are not two fee streams, and none of them died.** The "social PDA"
   (`8buZeg…`, 287 SOL, reported in `RESULT_toll_positioning.md` §0(8)/§2 as 38% of lifetime income
   and *dead*) is the **second hop of the DREGG pipe**: an operator wallet (`PmpDh2BQ…`) sweeps the
   creator-fee vault ATA into it. Its August "death" is the sweeper's cadence changing. **The
   strongest decay evidence in that study is an accounting artifact.**
9. **The desk trades its own coin at 25 bps where everyone else pays 105**, because 80 of the
   105 is its own creator fee. Nobody had priced this. It is the single largest execution
   advantage on the desk and it applies to every DREGG trade forever. **It is also the closest
   thing to a temptation this file found, and the arithmetic forbids it**: a wash round trip
   collects 2 × 80 bps of creator fee and pays 2 × 105 bps of taker fee, netting **−50 bps** —
   the 25 bps figure already has the creator recapture inside it. The bright line against
   self-matched volume costs nothing to hold because there was never anything on the other side
   of it.
10. **What the ladder is actually for is variance.** Across 28 rolling 14-day windows, a 14-rung
    TWAP has **10.9% dispersion against a single clip's 46.8%** on the same inventory, at an
    indistinguishable mean. For forced, unhedgeable flow that is the whole prize — and it is a
    second-moment claim, which the multiple-comparison penalty does not touch.

---

## 1. The tier mechanics — the answer, from the program's own bytes

`FeeConfig` layout, from pump.fun's published `idl/pump_fees.json`:

```
FeeConfig { bump: u8, admin: pubkey, flat_fees: Fees,
            fee_tiers: Vec<FeeTier>, stable_fee_tiers: Vec<FeeTier> }
FeeTier   { market_cap_lamports_threshold: u128, fees: Fees }
Fees      { lp_fee_bps: u64, protocol_fee_bps: u64, creator_fee_bps: u64 }
```

Decoded live from `5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx` on 2026-08-15:

| # | mcap ≥ (SOL) | lp | proto | **creator** | | # | mcap ≥ (SOL) | lp | proto | **creator** |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| 0 | 0 | 2 | 93 | **30** | | 13 | 44,210 | 20 | 5 | **35** |
| 1 | 420 | 20 | 5 | **95** | | 14 | 49,120 | 20 | 5 | **30** |
| 2 | 1,470 | 20 | 5 | **90** | | 15 | 54,030 | 20 | 5 | **28** |
| 3 | 2,460 | 20 | 5 | **85** | | 16 | 58,940 | 20 | 5 | **25** |
| 4 | **3,440** | 20 | 5 | **80** ← DREGG | | 17 | 63,860 | 20 | 5 | **23** |
| 5 | **4,420** | 20 | 5 | **75** | | 18 | 68,770 | 20 | 5 | **20** |
| 6 | 9,820 | 20 | 5 | **70** | | 19 | 73,681 | 20 | 5 | **18** |
| 7 | 14,740 | 20 | 5 | **65** | | 20 | 78,590 | 20 | 5 | **15** |
| 8 | 19,650 | 20 | 5 | **60** | | 21 | 83,500 | 20 | 5 | **13** |
| 9 | 24,560 | 20 | 5 | **55** | | 22 | 88,400 | 20 | 5 | **10** |
| 10 | 29,470 | 20 | 5 | **50** | | 23 | 93,330 | 20 | 5 | **8** |
| 11 | 34,380 | 20 | 5 | **45** | | 24 | 98,240 | 20 | 5 | **5** |
| 12 | 39,300 | 20 | 5 | **40** | | | | | | |

**Tier 0 is a cliff, not a floor.** Under 420 SOL of market cap the creator takes 30 bps and the
*protocol* takes 93. "Press the price down to maximise the fee" has a hard bottom at which the fee
business is destroyed rather than maximised. (There is also a parallel `stable_fee_tiers` array
for stablecoin-quoted pools, thresholds in 6-decimal USD; irrelevant to DREGG.)

### The input, and the update cadence

pump.fun's `docs/FEE_PROGRAM_README.md` gives the reference implementation:

```
poolMarketCap = quoteReserve * baseMintSupply / baseReserve
calculateFeeTier: last tier whose marketCapLamportsThreshold <= marketCap
```

`get_fees(is_pump_pool, market_cap_lamports, trade_size_lamports, is_new_quote_mint)` takes market
cap as a **caller-supplied argument**, computed by the AMM from live reserves. There is nowhere to
cache a tier: the `Pool` account has no fee-tier and no high-water-mark field.

**Measured, not assumed.** Predicting `coin_creator_fee_basis_points` on every decoded swap in the
live tape, with each pool's *exact* mint supply:

| specification | correct | verdict |
|---|---|---|
| **pre-swap reserves + virtual, exact mint supply** | **1,058 / 1,058** | **EXACT** |
| pre-swap reserves, virtual-reserve term dropped | 1,024 / 1,058 | 34 misses |
| post-swap reserves + virtual | 1,037 / 1,058 | 21 misses |

Per pool: DREGG/SOL 778/778, weave/SOL 115/115, nosis/SOL 81/81, SOLVE/SOL 34/34. The four pools
have four *different* supplies — nosis has burned 2.66% — and the boundary each one flips at moves
with its own supply exactly as the formula says: nosis flips 90→85 bps at a price×10⁹ of 2,527, not
at the nominal 2,460, because `2,460 / 0.973412 = 2,527.2`. Getting that right on a token that is
not ours is the check that the formula is the *program's*, not a curve fitted to DREGG.

**Spot, no hysteresis, no ratchet — measured three ways.** DREGG's applied rate flipped 23 times in
25.8 hours of tape; it flips in *both* directions; and on 2026-08-14T08:50 it went
80→75→80→75 bps across four seconds. A 24-hour TWAP cannot produce that, a ratchet cannot go back
up, and the fee amounts confirm the rate is applied to the state the swap *finds*, not the state it
leaves. On one arbitrary real transaction the creator vault received **2,245,946 lamports** against
`80 bps × (280,181,646 / 0.998) = 2,245,937` predicted — **9 lamports of integer rounding on 0.0022
SOL**, i.e. 4 parts per million.

**So: a wick below a boundary is worth exactly the volume that trades during the wick.** Under a
TWAP the answer would have been "nothing"; under spot with no hysteresis, oscillation is worth as
much as sitting, per unit of volume. That is the good case for the operator's thesis, and §5 shows
it still does not pay.

### Where DREGG sits

State at the last decoded swap, 2026-08-15 05:57 UTC (it moves; the study reads the live tape):

| | value |
|---|---|
| market cap | **3,888 SOL** = $293,383 at $75.45/SOL |
| applied | lp 20 / protocol 5 / **creator 80** bps |
| rung below | 3,440 SOL ($259,545), **−11.5%** → creator 85 bps |
| rung above | 4,420 SOL (**$333,485**), **+13.7%** → creator 75 bps |

The inherited model put the live boundary at $300,000 of FDV, which is where DREGG *is*. The real
one is $333,485 **today** — and because the threshold is in lamports, that dollar figure moves with
SOL. A 10% SOL rally re-rates DREGG's creator fee with no DREGG price move at all. **Every
dashboard showing FDV in dollars is showing the wrong number for this decision.**

---

## 2. 48 days reconstructed, and reconciled against money that moved

96,414 DREGG/SOL swaps, 2026-06-27 15:20 → 2026-08-13 23:59, exact integer pre/post vault balances.
`RESULT_bulk_history.md`'s two do-not-backtest windows are on SOLVE/SOL and weave/DREGG; neither
touches DREGG/SOL, so the series is used whole.

The gross the fee is charged on is **not** the vault delta: a sell's vault gives up
`gross × (1 − lp/10⁴)` because the LP fee stays in the pool, and a buy's vault receives
`quote_in × (1 + lp/10⁴)`. Both verified on the tape — the sell ratio sits at 0.99799999 and the
buy ratio at 0.99999999 under the correct reading, and at 0.998 under the wrong one.

| creator bps | swaps | share | quote SOL | share | fee SOL |
|---:|---:|---:|---:|---:|---:|
| 95 | 3,726 | 3.9% | 2,681.5 | 2.7% | 25.47 |
| 90 | 642 | 0.7% | 611.5 | 0.6% | 5.50 |
| 85 | 3,147 | 3.3% | 2,936.0 | 2.9% | 24.96 |
| 80 | 8,039 | 8.3% | 6,973.5 | 6.9% | 55.79 |
| 75 | 50,662 | 52.5% | 51,236.8 | 51.0% | 384.28 |
| 70 | 25,987 | 27.0% | 30,739.8 | 30.6% | 215.18 |
| 65 | 2,549 | 2.6% | 4,402.8 | 4.4% | 28.62 |
| 60 | 17 | 0.0% | 15.8 | 0.0% | 0.09 |
| **30** (tier 0, sub-420-SOL) | 1,645 | 1.7% | 820.8 | 0.8% | 2.46 |
| **TOTAL** | **96,414** | | **100,418.5** | | **742.35** |

Blended realised take **73.93 bps**.

### The reconciliation

| | SOL |
|---|---:|
| reconstructed creator fee, AMM only | 742.35 |
| drained from the vault ATA `2dQa7pRL…` | 466.61 |
| drained from the creator PDA `8buZeg…` | 286.36 |
| **operator receipts, both hops** | **752.98** |
| residual | **+10.62 (+1.43%)** |

The residual is not noise: tracked claim by claim it is a **constant 9.15 ± 0.36 SOL from
2026-07-01 onward, over 213 claims**. A constant offset established in week 0 is the bonding-curve
creator fee, which no post-graduation AMM swap can reconstruct. Everything after graduation
reconciles to within a third of a percent.

**Two upstream corrections fall out of this.**

- **`RESULT_toll_positioning.md` §3's "realised take tracks the ladder at 0.93×" is superseded: it
  is 1.00×.** That study divided first-match-attributed claims by a *vendor* volume series; this
  divides exact receipts by exact reconstructed accrual. The operator receives essentially every
  lamport the ladder charges. (The mechanism of the old error is the same class as the one it
  itself corrected: an estimate over a proxy denominator.)
- **`RESULT_toll_positioning.md` §0(8)/§2's "one of the desk's two fee streams — 38% of lifetime
  income — already went to zero" is withdrawn.** Chain query on the vault's own recent history: the
  three drains found are all signed by `PmpDh2BQCMMseKYPxseWTSoX3aAouHE4sWyFWTdkqYE`, an **operator
  wallet**, and all three credit `8buZeg…`. The "social PDA" is a sweep destination, not a second
  toll. Its 142.5 → 141.8 → 2.9 SOL/month collapse is the operator's own sweeper switching to
  claiming direct from the ATA. **Nothing died.** That paragraph was the strongest single piece of
  toll-death evidence in the file and it should not be carried forward.

Trailing-14d of the bulk tape: volume **493.4 SOL/day ($37,230)**, creator fee **3.73 SOL/day
($281)** — both within 1% of `toll_positioning`'s independent vendor-sourced figures, which is a
useful cross-check that the two instruments see the same market.

---

## 3. The replay engine, validated before it is believed

A constant-product replay of the pool with our orders interleaved. Exogenous orders are taken from
the tape **in their natural units** — a historical sell is a quantity of DREGG, a historical buy a
quantity of SOL — so that when our order moves the price, everyone else still trades the size they
actually traded.

Zero-intervention replay against the real path, 96,414 swaps, one-way, never re-synced:

| | base | quote |
|---|---:|---:|
| replayed final | 78,007,388,470,903 | 377,815,319,394 |
| on-chain final | 78,046,187,303,184 | 377,712,326,487 |
| **drift** | **−497 ppm** | **+273 ppm** |

Under 5 bps of accumulated drift over 48 days of float arithmetic against the program's exact
integer math, and the replayed creator fee (742.311 SOL) reproduces §2's direct reconstruction
(742.35) through a completely different code path. Every number in §4 is a *difference* between two
runs of this engine, so the drift cancels.

**The assumption that is not free**, stated rather than buried: exogenous flow does not react to
our price. That over-states how long our impact persists, because in reality the DLMM pools and the
router arbitrage it back. It can therefore only make the re-rate and the mark *larger* in
magnitude — which makes §4's negative re-rate smaller and builds no positive case for pressing.

---

## 4. The backtest

**Inventory, and this is the fact that sizes everything else.** The escrow releases
**1,204,362.4868 DREGG every 14 days**, and the operator's wallets hold **749.88 DREGG** in total
across every covered address — twenty-three cents. There is no other DREGG. "No new capital" means
the buy side can only ever spend SOL a sell side already raised, so the whole strategy works
**$357 at a time**.

Three tranches were released in the tape's window (07-11, 07-25, 08-08; `(62,626,849 − 59,013,762)
/ 1,204,362 = 3`, and the next is 2026-08-22). Benchmark: the same 3,613,087 DREGG sold at **each
tranche's own 14-day VWAP** with 25 bps of friction and zero impact = **26.971 SOL**.

| arm | edge | cash | fee_own | vs VWAP | re-rate | mark | TOTAL | $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dump, one clip at unlock | 0% | 20.990 | 0.163 | −21.57% | −0.0806 | −0.009 | 21.06 | 1,589 |
| dump, one clip at unlock | +1.96% | 21.402 | 0.163 | −20.05% | −0.0806 | −0.009 | 21.48 | 1,620 |
| TWAP, 4 rungs | 0% | 24.486 | 0.180 | −8.55% | −0.1383 | −0.694 | 23.83 | 1,798 |
| TWAP, 4 rungs | +1.96% | 24.966 | 0.180 | −6.77% | −0.1383 | −0.694 | 24.31 | 1,834 |
| TWAP, 8 rungs | 0% | 24.055 | 0.178 | −10.15% | −0.0914 | −1.107 | 23.04 | 1,738 |
| TWAP, 14 rungs | 0% | 24.113 | 0.179 | −9.93% | −0.1011 | −1.366 | 22.83 | 1,722 |
| price ladder, 4 @ 3% | 0% | 24.129 | 0.179 | −9.88% | −0.1203 | −0.204 | 23.98 | 1,809 |
| price ladder, 4 @ 6% | 0% | 26.156 | 0.193 | −2.31% | −0.1473 | −0.300 | 25.90 | 1,954 |
| price ladder, 4 @ 6% | +1.96% | 26.669 | 0.193 | −0.41% | −0.1473 | −0.300 | 26.42 | 1,993 |
| price ladder, 8 @ 6% | 0% | 26.838 | 0.198 | **+0.24%** | −0.1521 | −1.396 | 25.49 | 1,923 |
| price ladder, 8 @ 6% | +1.96% | 27.364 | 0.198 | **+2.19%** | −0.1521 | −1.396 | 26.01 | 1,963 |
| boundary-tilted, 4 @ 6% | 0% | 26.156 | 0.193 | −2.31% | −0.1473 | −0.300 | 25.90 | 1,954 |
| **GRID (sell up / buy down) 4 @ 6%** | 0% | 27.581 | 0.523 | **+4.20%** | −0.0911 | −8.888 | 19.13 | 1,443 |
| **GRID 4 @ 6%** | +1.96% | 28.942 | 0.523 | **+9.25%** | −0.0911 | −8.888 | 20.49 | 1,546 |
| GRID 4 @ 12% | 0% | 25.717 | 0.450 | −2.98% | −0.0833 | −10.957 | 15.13 | 1,141 |

`cash` = SOL the fills paid out with all 105 bps deducted. `fee_own` = the creator leg of our own
fills coming back — counted **once**, never folded into `cash` as well. `re-rate` = creator fee on
**everyone else's** flow, changed by our moving the market cap around the rungs; **that column is
the entire thesis, and it is negative in every arm.** `mark` = the 59.0M still-locked DREGG
re-marked at the perturbed final price.

**On the +1.96% arm, which is an upper bound and not a forecast.** That figure is
`RESULT_toll_positioning.md` §4's measured per-fill advantage of a one-sided DLMM sell ladder
*against routing the same clip through two PumpSwap legs* (2 × 1.44% + impact). Here we execute
directly on the PumpSwap pool at 25 bps + impact, which is already far cheaper than that routed
counterfactual, so applying the full +1.96% double-counts most of what that edge was made of — the
avoided router toll. The two columns therefore bracket the truth rather than straddling it: the 0%
arm is the honest central case, the +1.96% arm is the ceiling. Note that it changes no ranking and
no sign anywhere in the table.

### Impact persistence — the measurement the thesis turns on

One tranche dumped in a single clip, perturbed market cap against the untouched path:

| unlock | 1 min | 1 h | 6 h | 1 d | 3 d | 7 d | 14 d |
|---|---:|---:|---:|---:|---:|---:|---:|
| 07-11 | 0.00% | −2.46% | −1.52% | −0.15% | −0.00% | −0.00% | 0.00% |
| 07-25 | 0.00% | −4.22% | −3.16% | −0.66% | −0.00% | 0.00% | 0.00% |
| 08-08 | −3.08% | −2.81% | −2.61% | −1.87% | −0.04% | −0.00% | −0.00% |
| **median** | | **−2.81%** | **−2.61%** | **−0.66%** | **−0.00%** | | |

Impact in a constant-product pool is not permanent: a later *buy* removes base in proportion to the
base already there, so a multiplicative push decays multiplicatively with everyone else's flow.
**A tier press has a half-life measured in hours.** Its value is 5 bps × (volume during those
hours), not 5 bps × a month — which is how every previous version of this arithmetic priced it.

### Rolling windows: three unlock dates is not a sample

Every 14-day window in the tape whose 5-day washout also fits, daily starts, one tranche each,
scored against that window's own VWAP, paired within window:

| arm | mean vs VWAP | median | **sd** | win rate | mean mark | paired t vs dump |
|---|---:|---:|---:|---:|---:|---:|
| dump | −14.65% | −13.20% | **46.82%** | 36% | −0.0002 | — |
| TWAP 4 | −15.17% | −12.48% | **17.44%** | 21% | −0.0002 | −0.08 |
| **TWAP 14** | −13.50% | −13.92% | **10.86%** | 14% | −0.0007 | 0.14 |
| price 4 @ 6% | −4.89% | −11.82% | 49.02% | 50% | −0.0012 | 1.63 |
| tilt 4 @ 6% | −5.67% | −11.82% | 48.35% | 50% | −0.0012 | 1.50 |
| GRID 4 @ 6% | −0.99% | −8.52% | 50.91% | 43% | −0.0208 | 1.03 |

n = 28, windows overlap 14:1, so the paired t is optimistic by roughly √14 ≈ 3.7. Divide and
nothing is close to significant on the **mean**. What *is* large and robust is the **dispersion**:
a 14-rung TWAP has 23% of a single clip's spread, and 62% of a 4-rung TWAP's. That is the finding
the recommendation rests on, and it is a second-moment claim that survives the multiple-comparison
penalty in §7 untouched.

### Nulls

**Random schedule** (same tranche, same clip count, uniformly random times, n=200): random draws
score −10.25% ± 9.61% vs VWAP. The price ladder's −2.31% gives one-sided **p = 0.190**; TWAP 4's
−8.55% gives **p = 0.455**; the dump's −21.57% gives **p = 0.880**. **Nothing clears its own random
schedule.**

**Both controls** (PROGRAM.md §3 rule 12), three synthetic worlds sharing the tape's timestamps,
depth and notional distribution and differing only in the sign process:

| world | dump | TWAP 4 | price 4 @ 6% | GRID 4 @ 6% |
|---|---:|---:|---:|---:|
| known-ZERO (iid signs) | −32.27% | −21.30% | −23.46% | −12.77% |
| known-EFFECT (reverting) | −19.04% | −15.41% | −16.67% | **+6.60%** |
| known-EFFECT (trending) | −27.56% | −17.22% | −15.27% | −19.47% |

The GRID column is the recovery test and it recovers: −12.8% → **+6.6%** → −19.5% as reversion is
switched on and then reversed. **The estimator can see mean reversion when mean reversion is
there**, so its verdict on the real tape is a measurement and not a blind spot. The price-ladder
column barely moves (−23.5 → −16.7 → −15.3), which says a one-sided resting ladder is not a
reversion harvester at all — it is a directional bet wearing a grid's clothes. Every arm is
negative in every world because 1.2M DREGG cannot be sold *at* VWAP; only differences mean
anything.

This is consistent with `RESULT_mean_reversion.md`, which found DREGG/SOL reversion
**unresolvable-at-this-n** at 24h+ and indistinguishable from a random walk at 2–12h. A grid needs
reversion. There is no measured reversion to harvest.

### Temporal split

| window | arm | vs VWAP | re-rate | mark | total SOL |
|---|---|---:|---:|---:|---:|
| first half | dump | −67.30% | −0.0203 | −0.000 | 3.94 |
| first half | TWAP 4 | −15.42% | −0.0575 | −0.000 | 10.20 |
| first half | price 4 @ 6% | −61.12% | −0.0329 | −0.000 | 4.68 |
| first half | GRID 4 @ 6% | +0.21% | −0.0279 | −0.000 | 12.12 |
| second half | dump | +15.77% | −0.0603 | −0.009 | 17.12 |
| second half | TWAP 4 | −2.94% | −0.0809 | −0.694 | 13.64 |
| second half | price 4 @ 6% | +45.72% | −0.1144 | −0.300 | 21.22 |

The rank order **inverts** between halves on every arm except the TWAPs. That is the whole reason
this study does not select an arm on backtest rank.

---

## 5. Why the boundary cannot be pressed, in one inequality

| | |
|---|---|
| one tranche | 1,204,362 DREGG = 4.68 SOL = **$353** |
| pool base reserve | 87,211,250 DREGG → one tranche is **1.38%** of it |
| single-clip impact | **−2.71%** |
| trailing-14d volume | 493.4 SOL/day ($37,230) |
| tranche as share of volume | **0.95% of one day**, 0.07% of a 14-day period |

**Visibility is not a binding constraint, and should stop being priced as one.** The brief asks for
a sell-share-of-volume cap so the community does not see a dev dumping. At 0.1–1.6% of volume the
tranche is under the noise floor of any holder's chart, and it is $353 against
`RESULT_lp_strategy.md`'s measured $538 one-day exit capacity. What *is* visible is the −2.7% print
a single clip leaves. **Cap clip impact, not sell-share-of-volume** — the two constraints bind at
wildly different sizes and only one of them binds here.

### The two fee terms, and the break-even distance

Creator fee = `rate(market cap) × SOL volume`, and **both** factors move with price. A holder
selling N DREGG generates SOL volume proportional to the price, so the fee *base* falls
continuously as the price falls, while the *rate* only rises in 5 bps steps at rungs 28% and 40%
apart around this level. Measured base-denominated share of quote volume: **0.4996** (53.1% of
swaps). So

```
d(log fee) = d(log rate) + 0.4996 × d(log price)
```

Setting that to zero gives a **break-even distance** that depends on nothing but the rung ratio and
the flow mix:

```
d* = ln(85/80) / 0.4996 = 12.14%   (crossing down)
d* = ln(80/75) / 0.4996 = 12.92%   (crossing up)
```

**The rung below is 11.5–12.4% away and the rung above 12.5–13.7%, depending on the hour.** The two
terms cancel to within a few tenths of a percent, and which side of zero the net lands on flips
with the day's price (measured at +0.30% down and +0.37% up in the snapshot run). That
cancellation is a far more robust statement than a sign, and its content is:

> **The fee arithmetic gives no reason to press the boundary in either direction.** The decision
> falls entirely to the two terms that do *not* cancel — the escrow mark, and how long a press
> lasts.

Run it upward anyway, because it reverses a policy. A rally through 4,420 SOL is +0.37% on fee
income *and* marks the escrow **up by 13.7% = $2,367**, which nothing cancels.
`RESULT_toll_positioning.md` §5 concluded that just above a boundary the joint position is locally
**short** its own price. With the real table and the base term restored the position is **long its
own price essentially everywhere**: the escrow is an order of magnitude larger than the fee stream
and the base term cancels the rate term. **Do not treat a fall in DREGG as fee-accretive.**

### The mark-to-market inequality, given the most generous possible framing

Ignoring the base term entirely (i.e. granting the full 5 bps as though the base did not move)
*and* pretending the press were permanent: `distance* = Δrate × volume × horizon / escrow`, escrow
$17,316, volume $37,230/day.

| horizon reading | days | gain $ | distance* |
|---|---:|---:|---:|
| exponential (t½ 12.1 d) | 17.5 | 325 | **1.88%** |
| plateau (RW null, 30 d) | 30.0 | 558 | **3.23%** |
| power-law (1 yr) | 113.5 | 2,113 | **12.20%** |

The rung is 11.5% away. Two of the three readings miss by 4–6×; the third — the most optimistic
tail of a decay fit whose own study calls the band "a finding, not sloppiness" — **marginally
clears (11.5% < 12.2%)**, and that is stated rather than hidden. It clears only under a framing
that has already thrown away both terms that kill it: restore the base term and the gain is a wash;
restore the persistence and 17.5–113.5 days of gain collapses to hours. Getting there also needs
**4.5 tranches (2.1 months of unlocks) sold at once**, which is 2.1 months of income liquidated at
a −11.5% average price to buy a fee bump that is gone by the next day.

> **THE BOUNDARY IS UNPRESSABLE AT THIS DESK'S SIZE.** The operator should not run this campaign.

### The one case that survives: the free tilt

When the market sits **less than one tranche's own impact (2.71%) above a rung**, the tranche we
are contractually selling anyway can carry the price through it. `2.71%` is far inside the 12.14%
break-even, so here the terms do **not** cancel: `+6.06% − 0.4996 × 2.71% = **+4.71%**` on fee
income — robustly positive (unlike the 12% crossing, it does not depend on the hour's price), and
free, because the flow was forced.

Its size, stated plainly: the market sat inside that band on **4.8%** of the 48-day tape's swaps,
the press decays with a half-life under a day, and one day of fee income is 3.95 SOL, so a
successful tilt is worth about **0.19 SOL = $14**. At 4.8% occupancy and 26 unlocks a year that is
roughly **$18/year**. It costs nothing (it is a choice of *which minute* to send a clip that had to
be sent), so implement it — and spend no further attention on it.

### Income statement, 30 days

| line | USD |
|---|---:|
| creator fee, 80 bps on $37,230/day | **8,935** (decay-integrated: 5,200) |
| unlock sales, 2.14 tranches | 757 |
| boundary tilt, expected | 1 |
| boundary press campaign | **0** — measured −EV, do not run |
| **TOTAL vs $4,100 obligations** | **9,692 (2.36×)** |

Every dollar of that is the fee stream and the vesting schedule. **The strategy the brief asked for
adds a rounding error.** The honest recommendation is to put the attention on the volume lever
(`RESULT_toll_positioning.md` §5 lever 1: ~$250/day gross, labour unpriced), which is the same
mechanism — more flow across the same toll — at 400× the size.

---

## 6. The ladder spec, ready to run as a paper book

Not because the backtest found edge — it did not — but because **the unlock is forced flow that has
to be executed somehow**, and among ways to execute it the TWAP is the one with a quarter of the
dispersion at the same mean, plus a free boundary tilt.

```
BOOK: dregg-vest
  inventory        1,204,362.4868 DREGG per tranche, credited at unlock; starts at 0 cash
  clock            every 14 days at 16:31 UTC, anchored 2026-08-22T16:31Z
  venue            PumpSwap DREGG/SOL, pool 2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU
  base rule        14 equal clips, one per day, at a uniformly random minute inside each day
                     -> 86,026 DREGG per clip = 0.33 SOL = $25, clip impact -0.20%
  tilt rule        BEFORE each clip, compute mcap_sol = quote_reserve * mint_supply / base_reserve
                   let b = nearest FeeConfig rung below mcap_sol
                   if 0 < mcap_sol/b - 1 <= 0.0271:  send the WHOLE REMAINING tranche now
                   (this is the only discretionary branch in the book, it fires ~5% of the time,
                    and it is worth ~$14 when it does)
  never            buy DREGG back; rest sell rungs above market; defend any price level;
                   self-match any volume; hold a tranche past its 14-day period
  abort            if clip impact > 1.0% (pool depth collapsed) -> halve the clip and log a defect
                   if FeeConfig account hash changed -> stop and escalate (§7 risk 3)
```

Sizing rationale, all measured above: 14 rungs because dispersion falls monotonically to 14 and the
gas is negligible at $25/clip; random minute-within-day because no arm cleared its random schedule,
so any *specific* minute rule is unpaid overfitting; no buy side because the grid needs reversion
and there is no measured reversion; no resting rungs because the price ladder is a directional bet
whose rank inverts between temporal halves.

### Config contract for the paperdesk — and the three things it currently cannot express

`shitcoims_paperdesk/` is owned by another lane; this is the specification, not an edit. Against
the package as it stands (`Book`/`BOOKS` in `__init__.py`, `_POLICIES` and `policy_for` in
`policy.py:351-359`, the three named attributes in `Desk.__init__` at `desk.py:112-146`):

```python
# shitcoims_paperdesk/__init__.py
class Book(StrEnum):
    ...
    VEST = "vest"                       # + add to BOOKS, or test_every_book_has_a_policy fails

# shitcoims_paperdesk/policy.py  -- register in _POLICIES[Book.VEST]
class VestPolicy(DeskPolicy):
    book = Book.VEST
    policy_id = "paperdesk-vest-v1"
    ranges: ClassVar[dict[str, tuple[float, float]]] = {
        "rungs":            (14.0, 14.0),    # degenerate: measured, not swept
        "tilt_reach":       (0.0271, 0.0271),# one tranche's own impact, from live reserves
        "max_clip_rho_bps": (10.0, 30.0),    # clip as bps of the pool's base side
        "hold_seconds":     (1209600.0, 1209600.0),   # the 14-day period, not a horizon guess
    }
```

Three structural gaps, each of which the book needs and the package does not have:

1. **A calendar trigger.** All time logic in `desk.py` is relative (`deadline_unix = now + hold_seconds`)
   or a min-interval throttle. "Every 14 days at 16:31 UTC" has no expression in `DeskConfig`, in
   `DeskPolicy.ranges`, or in `Desk.step`. Smallest sufficient addition: a `schedule_unix:
   Iterable[float]` on the book, consumed by `Desk.step`.
2. **Non-zero starting inventory.** `PaperPosition` can only be created by `MintBook._fill_pending`,
   which always pays `curve_buy`, and `close_row` (`ledger.py:133-219`) raises
   `ValueError("a close row without a spend cannot be divided by")` when `spend_lamports <= 0`.
   A vested tranche has **no cost basis** — and given `PROGRAM.md` §0, fabricating one is the single
   defect that cost this desk 7.47 SOL. The right shape is an explicit `basis_source:
   "vested_zero_cost"` and a `net_return` denominated in **proceeds**, not spend.
3. **Multiple simultaneous clips per mint.** `MintBook.pending` is `dict[str, dict]` — one entry per
   mint — so two live clips on DREGG are unrepresentable. A ladder needs a list.

What the book can reuse unchanged: `curve_sell(state, tokens_raw, fee_bps=…)` in
`shitcoims_scalper/shadow.py:31-48` is already the exact constant-product fill against observed
reserves, and `ClusterTapeSource` already tails `state/cluster_tape/swaps/<pool>-YYYYMMDD.jsonl`
with `PoolSwap.quote_reserve` / `base_reserve`.

**But there is a live defect in the fill simulation that this study can name exactly, and it is
not confined to the new book.** `friction.py` sets `EFFECTIVE_TAKE_BPS["DREGG/SOL"] = 20`,
measured by `scripts/sim2real.py` as the shortfall of each real swap's output against a zero-fee
constant product from the pre-reserves. On a PumpSwap pool **that measurement recovers the LP fee
and nothing else** — §2 verifies it, sell ratio 0.99799999 — because the LP fee is the only leg
that comes out of the *vault*. The protocol (5 bps) and creator (75–95 bps) legs are transferred
from the **user's** token account, so they never appear in a vault-shortfall estimator. The taker
therefore pays **105 bps** where the paperdesk charges 20, and `MintBook._close_observed` /
`_fill_pending` **overstate every simulated PumpSwap fill by 85 bps** on both legs of a round trip.

The correct constants, all verified on chain:

| who | what they pay per leg on DREGG/SOL | why |
|---|---:|---|
| the paperdesk today | 20 bps | vault shortfall = LP fee only |
| **any taker** | **105 bps** | lp 20 + protocol 5 + creator 80 |
| **this operator** | **25 bps** | the creator 80 returns to their own vault |

SOLVE/SOL (also 20 in the table) has the same defect. nosis/SOL and weave/SOL at 407/909 bps are
DLMM pools where the shortfall genuinely is the whole take, and are unaffected.

---

## 7. Failure modes, priced

| # | mode | priced | observable | response |
|---|---|---|---|---|
| 1 | **Volume decay kills the fee base** | t½ 12.1 d [9.1–18.4] fitted, but the RW null beat every decay model OOS; $281/day now, $5.2k–$8.9k/month | 7-day rolling creator fee **from the tape**, not from claims — claims lag and lump | the escrow outlives the stream; sell tranches on schedule regardless of price and never hold one for a re-rate |
| 2 | **A holder front-runs the visible ladder** | worst case the whole tranche fills 2.7% lower = **$10** | realised price per tranche against that period's VWAP — the tape already carries every fill | at $353 the defence costs more than the attack; **do not build one**. This is also why the spec rests no rungs above market |
| 3 | **The tier table changes** | the entire fee business, **$8.9k/month**, in one deploy. It has changed once (Project Ascend, 2025-09-01) and pump.fun has said publicly it intends to replace Dynamic Fees V1 during 2026 | **hash the `FeeConfig` account daily** — one `getAccountInfo` — and alert on change | never hard-code the ladder. *(Two places did; both corrected in this change — see §8.)* |
| 4 | **The boundary is unpressable at our size** | not a risk, the measured result (§5); the failure mode is *spending money to discover it* | — | the press is a **tilt on forced flow**, never a campaign |
| 5 | **SOL/USD moves the boundary with no token move** | a 10% SOL rally moves every rung's dollar value 10% and can re-rate the fee with DREGG flat. Nobody had this written down | track market cap **in SOL** | every USD-FDV dashboard is the wrong instrument for this decision |
| 6 | **Falling under 420 SOL of market cap** | creator 80 → **30 bps** and protocol 5 → 93, i.e. the protocol takes the fee business. −89.2% from here, and it is a cliff, not a slope | market cap in SOL against 420 | the only price level worth defending is this one, and it is nowhere near |

---

## 8. What this changes upstream

- **`PROGRAM.md` §0** — the inverse ladder is real but the numbers are wrong: it is 25 rungs 5 bps
  apart keyed on **SOL** market cap, not 3 rungs keyed on USD FDV. The "$300k boundary" does not
  exist. The corollary "a falling price partially hedges the rate" survives *directionally* but is
  roughly cancelled by the fee-base term (§5) and swamped by the escrow mark.
- **`RESULT_toll_positioning.md` §3** — realised take is **1.00×** the ladder, not 0.93×.
- **`RESULT_toll_positioning.md` §5 lever 2 and §9 item 2** — "at FDV $305k the position is locally
  short its own price; never defend $300k; treat organic dips as fee-accretive" is **reversed**.
  The position is long its own price essentially everywhere. Falsifiable claim #6 in that file
  ("the joint position is locally short its own price just above $300k FDV") is hereby falsified —
  by the free natural experiment it asked for, run early.
- **`RESULT_toll_positioning.md` §0(8), §2, §6** — the dead "social" fee stream is not a stream and
  is not dead (§2). The decay argument now rests only on the volume series.
- **`shitcoims_netmap/physics.py`** — `PUMPSWAP_CREATOR_LADDER` (the 3-step USD table) is replaced
  by `PUMPSWAP_CREATOR_TIERS_SOL` (the real 25-rung on-chain table) plus
  `creator_fee_at_mcap_sol()`; `pumpswap_fee(fdv_usd, sol_usd=…)` now converts and documents that
  USD is the wrong unit. `tests/test_netmap.py` updated with the corrected expectations and two new
  tests (the SOL-vs-USD invariance, and the tier-0 cliff). **This was live code producing wrong fee
  bands for every PumpSwap edge in the netmap.**
- **`studies/circuit_model.py`** — same correction to its own copy of the ladder.
- **`shitcoims_paperdesk/friction.py:70`** — `EFFECTIVE_TAKE_BPS["DREGG/SOL"] = 20` should be 25 for
  the operator and 105 for anyone else (§6). Not edited here; that package belongs to another lane.

---

## 9. Falsifiable claims

| # | claim | falsified by | status |
|---|---|---|---|
| 1 | The applied creator fee is `FeeConfig.fee_tiers` looked up on `quote × supply / base` at the swap's entry reserves | any decoded swap whose applied bps differs from that prediction | 1,058/1,058 exact, 4 pools, 2 rivals falsified |
| 2 | No TWAP, no hysteresis, no ratchet | an observed flip that a spot rule cannot produce, or a rate that fails to return when the price does | 23 flips, both directions, 4 s apart |
| 3 | Thresholds are in SOL, so the USD boundary moves with SOL | a token changing tier at a fixed USD market cap across a SOL move | derived from the u128 field + verified across 4 supplies |
| 4 | The operator receives 1.00× the ladder | a multi-week window where receipts / reconstructed accrual departs 1.00 by >2% | 47 days, residual constant 9.15 ± 0.36 SOL |
| 5 | Both fee "streams" are one pipe | a drain of `2dQa7pRL…` crediting a non-operator wallet | 3/3 recent drains signed by an operator wallet, all crediting `8buZeg…` |
| 6 | Pressing the 3,440 SOL rung is −EV | 30 days of volume at a level that makes `Δrate × V × H > distance × escrow` at 12.4% — i.e. roughly 5× current volume | measured under 3 decay readings |
| 7 | A single-clip tranche's impact half-life is under a day | a clip whose perturbation is still >1% at 3 days | 3 unlocks, median −0.00% at 3 d |
| 8 | No execution arm beats its window VWAP on the mean | an arm clearing its random-schedule null at p<0.05 on fresh windows | 28 rolling windows, 10 arms, none clears |
| 9 | A 14-rung TWAP has ≤¼ the dispersion of a single clip | new windows where the sd ratio exceeds 0.5 | 10.86% vs 46.82%, n=28 |
| 10 | The operator's own trading friction on DREGG is 25 bps | a DREGG swap by an operator wallet where the creator leg does not return | verified to 9 lamports on a live tx |

---

## 10. What to do

1. **Do not run the boundary campaign.** It is −EV under every decay reading, unreachable at 12.4%
   for a $357 tranche, and the press evaporates in hours. (§5.)
2. **Retire "never defend $300k / dips are fee-accretive."** The position is long its own price.
   Nothing needs *defending* either — just stop treating a fall as good news. (§5.)
3. **Run the unlock through a 14-clip daily TWAP with the free boundary tilt**, next tranche
   2026-08-22T16:31Z. Not for edge — for a quarter of the dispersion on flow that must move. (§6.)
4. **Hash the `FeeConfig` account daily.** One `getAccountInfo`, and it is the only early warning
   the desk can have on the risk that takes 100% of the fee business. (§7 risk 3.)
5. **Price every DREGG trade at 25 bps, not 105.** The creator recapture is the desk's largest
   structural execution advantage and it was not in any model. Fix
   `paperdesk/friction.py` when that lane is free. (§6.)
6. **Put the attention on the volume lever instead.** Same mechanism — more flow over the same toll
   — at ~$250/day gross against this study's ~$19/year. (§5.)

---

*Nulls and trials: `dregg_boundary.py nulls` prints the register — 20 scored configurations (10
arms × 2 execution edges) plus 28 rolling windows and 3 synthetic worlds, far over PROGRAM.md §3
rule 9's ~7-configuration budget for a **selection** claim, which is why no arm is selected on
backtest rank and the recommendation is a second-moment claim instead. Both controls run
(known-ZERO and two known-EFFECT worlds; the estimator recovers a planted effect). Random-schedule
null on 200 draws. Temporal split, and the rank inverts between halves. Nothing was run and
discarded. Three upstream numbers moved because of this file and two moved against the desk: the
crossing re-rate 35 bps → 5 bps, the pressable distance 1.8% → 12.4%-and-negative, and the realised
take 0.93× → 1.00×.*
