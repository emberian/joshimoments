# RESULT: the failure stream — 922,430 reverted transactions, read as intelligence

2026-08-15. Instrument: `studies/failure_stream.py`. Reproduce:
`uv run --group research python studies/failure_stream.py all`
(sections: `panel taxonomy race fingerprint rpc surge practical holdout`).

Data: `state/bulk_history/parquet/` — 48 days, 9 pools, 3,384,841 pool-touching transactions
of which **922,430 failed** (of 3,384,843 and 922,432 in the raw export; two failures carry a
single vault leg instead of two and are dropped by the panel's `len(vaults) = 2` filter) — plus
a read-only Helius `getTransaction` sample of 2,266 transactions, and `state/cluster_tape/swaps/` (49,941 attempt rows) as a held-out window on
days the bulk export does not cover. **Nothing signed, nothing sent, no transaction
constructed.** Results cache to `studies/data/failure_stream/`; a re-run is offline.

**The one-line answer to the operator's idea: it works, and it does not pay off where it
was expected to.** The exhaust genuinely reverse-engineers competitors — it names programs,
names the wallets behind them, recovers their exact fee bids, and separates the ones racing
us from the ones aborting on their own clock. What it does *not* do is predict price.
Twenty-one pre-registered tests of "does a failure surge forecast anything the successful
stream does not", one survives multiplicity, and it has the wrong sign to trade.

The usable output is an **execution** finding, not a signal: on our pools the median
transaction that *lands* a fill bids **264,872 µlamports/CU** and the median transaction
that *fails* bids **4,185** — a 63× gap. Landing here is a fee-market outcome and we can
read the price of admission directly.

---

## 0. Two premises of the brief are false, and that is the first result

**(1) The corpus contains zero failures.** `state/bulk_pump/daily/` is 106,639,238 rows over
ten UTC days and `COUNT(*) WHERE err <> ''` is **0 on every day**:

| day | rows | failures |
|---|---|---|
| 2026-08-05 … 2026-08-14 | 106,639,238 | **0** |

This is not a bug, it is the export's design colliding with the SVM's. The query keeps a
transaction only when a pump-mint balance *changed*; a reverted transaction's balances roll
back, so `pre == post` and the row is filtered out before `err` is ever read. The `err`
column is present, typed, documented in `scripts/pump_history.py` — and constant. Any study
planning to read failures out of the corpus is planning against a column that cannot vary.
The docstring's schema table should say so.

**(2) The live cluster tape's `attempt` rows carry no fee payer and no compute units.**
`shitcoims_cluster.parse.Attempt` says it in its own docstring — the row is emitted from the
`getSignaturesForAddress` listing alone, *precisely* to avoid the `getTransaction` that a
signer would require. 61,000 attempt rows, zero signers, zero CU, zero fee. So "the heavy
fee-payers on our pools" cannot be enumerated from the tape the brief points at. The prior
"10 fee-payers = 46.6% of failures" (`RESULT_execution_landing.md`) came from a 2,390-row RPC
sample, not from the tape.

**What does carry it** is `state/bulk_history/parquet/`, which nobody had looked at for this
purpose: 48 days of our own pools with `fee_lamports` and `compute_units` on **every** failure,
plus `tx_index` (position inside the block) and `vaults`. And the vaults are a free gift —
on a failed transaction `pre_raw == post_raw` on both legs (verified 839,614/839,614 on
2026-08-11), so **every failure carries the pool's exact integer reserves at its own slot**.
The price the failing machine saw is *observed*, not interpolated.

---

## 1. The taxonomy

922,430 failures, 27.3% of all transactions touching our pools. The distribution is grossly
concentrated in one pool and every claim below inherits that:

| pool | rows | failures | fail rate | share of all failures |
|---|---|---|---|---|
| nosis/SOL | 2,714,334 | 757,842 | 27.9% | **82.2%** |
| DREGG/SOL | 525,137 | 128,276 | 24.4% | 13.9% |
| weave/SOL | 76,901 | 18,733 | 24.4% | 2.0% |
| weave/SOL (DLMM) | 41,042 | 10,556 | 25.7% | 1.1% |
| weave/DREGG (5%) | 10,778 | 3,619 | 33.6% | 0.4% |
| SOLVE/SOL | 15,071 | 2,509 | 16.6% | 0.3% |
| DREGG/nosis, weave/nosis, weave/DREGG (0.2%) | 1,578 | 895 | 55–66% | 0.1% |

**99.1% of failures are `custom program error`** — a program deliberately returning an error
code, not the runtime refusing. The runtime classes are rounding errors: `insufficient_funds`
3,997 (0.4%), `Program failed to complete` 1,995 (0.2%), `Computational budget exceeded` 664
(0.1%), `max loaded accounts data size cap` 569 (0.1%). Every one of them landed on chain and
paid: `getSignaturesForAddress` returns confirmed signatures only, and Agave charges the fee
payer before execution.

The top signatures, written `i<instruction index>:0x<program error code>`:

| signature | n | share | pools | med fee | med CU | IQR CU |
|---|---|---|---|---|---|---|
| `i3:0x51` | 115,485 | 12.5% | 4 | 7,208 | 31,983 | [31.8k, 39.7k] |
| `i3:0x1770` | 83,112 | 9.0% | 9 | 9,010 | 209,830 | [201.6k, 217.1k] |
| `i4:0x3c` | 78,608 | 8.5% | 4 | 6,213 | 97,985 | [90.7k, 108.0k] |
| `i4:0x1780` | 68,422 | 7.4% | 4 | 6,426 | 28,493 | [24.2k, 38.9k] |
| `i5:0x1` | 50,898 | 5.5% | 8 | 7,962 | 25,562 | [23.3k, 33.3k] |
| `i5:0x1388` | 38,574 | 4.2% | 5 | 6,405 | 27,199 | [15.9k, 71.7k] |
| `i3:0x3` | 29,718 | 3.2% | 4 | 9,221 | **1,638** | [1,637, 1,639] |

Look at `i3:0x3`: 29,718 failures with an interquartile range of **two compute units**. That
is not a distribution, that is a machine. The CU column alone separates deployed software
from noise.

### 1.1 Naming the slippage class without an IDL

The obvious next question — which of these is "slippage exceeded"? — has no honest answer from
a lookup table we do not have. An Anchor error `0x1780` is the 16th custom error in *some*
program's IDL, and guessing which is a fabrication.

So the codes are identified **behaviourally**, by what the price was doing in the seconds
before each failure fired, against two controls. Matching on the pool-**hour** asks "does this
code fire in volatile hours?", which a code that merely fires in *busy* minutes also passes.
Matching on the pool-**minute** asks "inside the very same minute, was this sender on a staler
quote than the ones that landed?". Only the second is evidence about the sender.

Units are basis points of |log price move| over the 5 s before the transaction, in excess of
control; the test is a paired sign test over pool-minutes, BY-FDR at q = 0.10 across 18 codes.

| signature | hour-matched | **minute-matched** | 95% CI | minutes | p | BY |
|---|---|---|---|---|---|---|
| `i1:0x1` | +591 | **+381** | [316, 457] | 1,482 | <1e-4 | yes |
| `i2:0x1` | +549 | **+284** | [242, 332] | 2,731 | <1e-4 | yes |
| `i3:0x1798` | +427 | **+222** | [172, 274] | 177 | <1e-4 | yes |
| `i3:0x1770` | +438 | **+217** | [172, 264] | 2,055 | <1e-4 | yes |
| `i6:0x5600000c` | +365 | **+199** | [150, 256] | 283 | <1e-4 | yes |
| `i4:0x3c` | +670 | **+195** | [148, 254] | 728 | <1e-4 | yes |
| `i5:0x1` | +95 | +167 | [123, 220] | 948 | <1e-4 | yes |
| `i5:0x1388` | +479 | +63 | [36, 96] | 1,141 | <1e-4 | yes |
| `i3:0x51` | +88 | +31 | [12, 47] | 564 | 0.77 | . |
| `i4:0x1780` | **−234** | **−5** | [−36, +40] | 657 | <1e-4 | yes |
| `i4:0x51` | −15 | −4 | [−24, +15] | 236 | 0.005 | yes |
| `i5:0x51` | +23 | −17 | [−47, +13] | 78 | 0.002 | yes |

Two populations, cleanly. `i1:0x1`, `i2:0x1`, `i3:0x1770`, `i3:0x1798`, `i4:0x3c`,
`i6:0x5600000c` fire on quotes that went stale — 200–380 bps of extra 5-second move than the
transactions that landed beside them in the *same minute*. `i4:0x1780`, `i4:0x51`, `i5:0x51`
fire on *quieter*-than-average moments: machines reverting on their own schedule, not the
market's. (For those three the sign test is significant with a near-zero mean because the
distribution is skewed — a majority of pool-minutes negative, a thin positive tail.)

Note the hour-matched column runs 2–3× larger than the minute-matched one throughout. That
gap is the confound made visible: most of what a loose control attributes to "this code fires
when it is volatile" is really "this code fires when it is busy".

---

## 2. Race loss vs designed abort — exact, from `tx_index`

`tx_index` is position *inside the block*, which no RPC call returns and which the bulk export
carries for free. It makes an otherwise fuzzy question exact: a failure whose own block also
contains a **successful swap on the same pool at a lower index** lost a race we can watch.

- Failures sharing a block with a landed fill: **33.2%**; failure after that fill: **25.5%**.
- Non-failing reference transactions, same statistic: 18.8% / 12.4%.

By signature, against the reference base rate:

| signature | n | shares block w/ fill | beaten in block | lift |
|---|---|---|---|---|
| `i3:0x1798` | 14,488 | 66.0% | 47.1% | **3.50×** |
| `i3:0x3` | 29,718 | 59.7% | 40.9% | **3.17×** |
| `i2:0x1` | 19,181 | 46.9% | 38.7% | **2.49×** |
| `i6:0x5600000c` | 12,888 | 45.8% | 35.2% | **2.43×** |
| `i1:0x1` | 16,838 | 36.0% | 31.9% | 1.91× |
| `i5:0x3c` | 29,720 | 31.1% | 22.1% | 1.65× |
| `i4:0x1780` | 68,422 | 18.5% | 12.7% | **0.98×** |
| `i2:0x1772` | 24,344 | 18.4% | 13.0% | **0.98×** |
| `i5:0x1` | 50,898 | 15.8% | 10.6% | **0.84×** |

**Two independent measurements agree.** The codes with elevated pre-failure price movement are
the codes that get beaten inside the block; the codes at or below 1.00× lift are the ones with
flat or negative pre-move. Nothing forced that — one statistic is built from prices, the other
from block positions — and it is the strongest internal evidence that the taxonomy is real and
not an artefact of how the codes were cut.

`i5:0x1` is the interesting exception: 0.84× on block competition but +167 bps of stale quote.
That is a machine whose quotes go stale but which is not competing for *our* fills — it is
racing on a different venue and our pool is a leg it reads.

---

## 3. Identity, reconstructed from exhaust

There is no signer column. So the fingerprint is
`(instruction index, error code, log₂ compute bucket, log₂ fee bucket)` — a bot's compute
budget and its fee schedule are written by its author and change only on redeploy.

- 6,570 cells over 922,430 failures. Top 1 cell = 5.2%, top 10 = **27.9%**, top 25 = 44.8%,
  top 100 = **69.9%**.
- Herfindahl 0.0119 → **84 equivalent machines** produce all 922,430 failures on our pools.
- 2,340 cells are seen on ≥ 3 distinct days and they account for **91.4%** of all failures:
  the stream is overwhelmingly produced by *deployed software with a memory*, not one-off
  senders.

And they run for a long time — the top cells by volume, with how long each has been alive:

| cell | n | days seen | span (d) | pools | top pool |
|---|---|---|---|---|---|
| `i4:0x3c \| cu16.5 \| f12.5` | 48,008 | 30 | 44.3 | 4 | nosis/SOL |
| `i3:0x51 \| cu15.0 \| f13.0` | 32,016 | 15 | 44.1 | 2 | nosis/SOL |
| `i3:0x51 \| cu15.0 \| f12.5` | 30,052 | 15 | 46.2 | 2 | nosis/SOL |
| `i3:0x3c \| cu16.5 \| f12.5` | 29,561 | 24 | 44.1 | 4 | nosis/SOL |
| `i3:0x1770 \| cu17.5 \| f13.0` | 25,452 | 10 | 44.7 | 4 | nosis/SOL |
| `i3:0x3 \| cu10.5 \| f13.0` | 23,577 | 6 | **11.4** | 3 | nosis/SOL |
| `i2:0x1772 \| cu15.0 \| f12.5` | 18,615 | 5 | 43.3 | 4 | nosis/SOL |
| `i4:0x1780 \| cu14.5 \| f12.5` | 16,442 | 4 | **13.1** | 4 | nosis/SOL |
| `i4:0x1780 \| cu15.0 \| f12.5` | 11,897 | 3 | **2.9** | 3 | nosis/SOL |

Spans of 43–46 days on a 48-day window: those are machines that were running before we
started looking and are still running. The short-span rows are the interesting ones — the
`i4:0x1780` pair at 2.9 and 13.1 days is a bot that arrived, ran hard, and left, and §6 shows
that turnover is the normal state.

### 3.1 The fingerprint is real — validated, not assumed

A 2,266-transaction read-only `getTransaction` sample (stratified: 800 from the top cells,
866 uniform over the whole failure stream, 600 from landed swaps), with the tape's
`fee_lamports` reproduced **exactly on 2,342 of 2,342** joined rows as a check.

**2.5% of sampled transactions touched more than one of our pools** (max 3) — multi-leg
arbitrage, and the reason 2,266 transactions join to 2,342 rows. Every statistic below is
deduplicated to the transaction first; leaving the expansion in would have silently
overweighted exactly the multi-pool arbitrageurs the roster is about.

**Median top-payer share inside a fingerprint cell: 54.4%. Baseline — the single most common
payer in an unstratified sample: 8.4%.** Six-fold concentration, and several cells are pure:

| cell | sampled | distinct payers | top payer share |
|---|---|---|---|
| `i2:0x1772 \| cu15.0 \| f12.5` | 61 | **1** | 100% |
| `i3:0x1770 \| cu17.5 \| f13.0` | 65 | **1** | 100% |
| `i3:0x3 \| cu10.5 \| f13.0` | 58 | **1** | 100% |
| `i4:0x1780 \| cu14.5 \| f12.5` | 55 | **1** | 100% |
| `i4:0x1780 \| cu15.0 \| f12.5` | 52 | **1** | 100% |
| `i3:0x51 \| cu15.5 \| f13.0` | 59 | 10 | 22% |

So the operator's idea is *correct as stated*: four public columns that everyone throws away
identify individual machines, and the identification can be checked.

### 3.2 The roster

Every program that failed ≥ 20 times in the sample, with the profile the exhaust gives it.
`beaten` = share whose block already contained a landed fill ahead of them; `pre5` = mean
|price move| in the 5 s before firing; `bid` = median `SetComputeUnitPrice`, µlamports/CU;
`CU use` = consumed ÷ requested.

| program | n | payers | top code | bid | CU use | beaten | pre5 bps |
|---|---|---|---|---|---|---|---|
| `4Qv3mbzcq1bKmrhGG4voS3EemfPd7f838FLUU7wBHSyi` | 370 | 18 | `i3:0x51` | 4,623 | 10% | 12% | 123 |
| `NA247a7YE9S3p9CdKmMyETx8TTwbSdVbVYHHxpnHTUV` | 364 | 21 | `i4:0x3c` | 2,566 | 27% | 23% | 377 |
| `3yGCLwQWdeS6jQvPgPYb7eDW1TQ9otWnuyyZFRC9K6K6` | 153 | **1** | `i4:0x1780` | 2,768 | 8% | 16% | 101 |
| `CZr8VacFkAVKXYgiB5VFmZWE42Bi7XTkNmsMwN5EyzhP` | 150 | **1** | `i3:0x1770` | 10,489 | 73% | 12% | 179 |
| `Prism8hsRo6Ww5jiN5Zeh3YDPLZHqHduCPSAV7JF7qv` | 96 | 8 | `i5:0x1388` | 3,312 | 4% | 14% | 335 |
| `6MWVTis8rmmk6Vt9zmAJJbmb3VuLpzoQ1aHH4N6wQEGh` | 67 | 2 | `i2:0x1772` | 924 | 12% | 24% | 198 |
| **PumpSwap AMM** | 67 | 19 | `i3:0x1798` | 20,477 | 60% | **52%** | **574** |
| `DF3LjmyzuMApbw55YeC52JJArKgQjygKWZFUB9TNqLWn` | 66 | **1** | `i3:0x3` | 40,000 | 2% | 39% | 409 |
| `2VSNUquk7FqkbS27WJpm6J1175EhoLcGtxuExu3wrzVz` | 47 | **1** | `i5:0x1` | 10,304 | 8% | 19% | 352 |
| `31KJbyd5umqKQ9a3NuFWuhV1MLUQkg3FBrn3vE7L9R1t` | 45 | **1** | `i3:0x1770` | 537 | 63% | 24% | 157 |
| `VeLoXemE5sA5Co5NnQM2SKYW5ovddcYrCytHX5gWDyV` | 27 | 2 | `i6:0x5600000c` | 5,703 | 39% | 44% | 505 |
| **Jupiter Aggregator v6** | 20 | 8 | `i2:0x1771` | 10,567 | 66% | **70%** | 299 |

And the wallets, where a program has essentially one operator:

| program | fee payer | share |
|---|---|---|
| `3yGCLwQ…K6K6` | `FUJKrQhxWYu4z59G6JGVfZstjQKi1fY1BZNwoekgs9vL` | 100% |
| `CZr8VacF…zhP` | `XUrKb2aK4jBm77q75EemchVUNRTJyeFQ5KebTJygPhF` | 100% |
| `DF3Ljmyz…LWn` | `Bu79TNqnLb5Pgbn4JA2L5k6sXmmgie5cXyCXi4w5X9RY` | 100% |
| `2VSNUquk…zVz` | `6WJfN1fqrEEMSVKnzZkR4vJTMTxBaqvka2KA7aQHJMfF` | 100% |
| `31KJbyd5…9R1t` | `4NHYHfeMKKWa77v9hSo7k4FxhGopGmwosxsC1baLsoAk` | 100% |
| `6MWVTis8…QEGh` | `8TPWakvWw4xQbk7uAYdNjZiDKKHgv9GE5GebzsbtUaHr` | 99% |
| `VeLoXemE…s2H` | `VLXFRyxhAndY21gS4ys6ZWyJKHeP9DQgoqHhq3ARs2H` | 63% |
| Jupiter v6 | `ENY9JreWWWtq8jSKfLtXpzjBteknLPdahPCwG7ZCVbJe` | 65% |

None of these appears in `wallet_labels.yaml` — they are new, and they are the population that
`RESULT_entity_resolution.md` could not see because the tape has no signer set. (`VeLoXemE`'s
top payer is a vanity address matching its own program prefix, which is its own small tell.)

**How to read the roster.** The two AMM/router rows are qualitatively different from every
third-party row: Jupiter v6 and PumpSwap are `beaten` 75% and 52% of the time, on 736 and 574
bps of preceding move, using 69% and 60% of the compute they requested, bidding 9.8k and 20.5k.
Those are **real trades losing real races**. The third-party programs are beaten 12–24% of the
time on 100–500 bps, use 2–27% of the compute they pay for, and bid 537–5,742. Those are
**arbitrage bots firing at every opportunity and aborting in-program when the arb evaporates**
— a successful no-op whose failure rate is a property of its strategy, not of the network.

**96.0% of failures happen inside a third-party program; only 4.0% inside an AMM.** That is a
replication to within a tenth of a point of `RESULT_execution_landing.md` §1.2 (96.1% / 1.0%
AMM / 3.0% Jupiter), which measured it on 2,390 sampled failures from one pool. Here it is on
922,430 failures over 48 days and 9 pools, sampled independently. Fee-payer concentration
replicates too: the uniform arm has 866 failures from 144 distinct payers with **top-10 =
42.8%** against the prior's 109 payers / 46.6%.

---

## 4. Do failure surges predict anything? Almost entirely no.

Pre-registered: three exposures (all failures / race losses / solo aborts, each standardised
within pool) × seven outcomes, on a 129,725-row pool-minute panel over 9 pools.

```
y_{p,t+h} = a_p + b·z_fail_{p,t} + c·z_swap_{p,t} + d·|ret_{p,t}| + e·log depth
```

`z_swap` is in the model because the honest null is that failures are a noisy copy of activity.
Inference is a **rotation null**: the exposure is circularly shifted inside each pool by ≥ 60
minutes, 500 draws, which preserves the autocorrelation of both series and destroys only their
alignment. (An i.i.d. shuffle has manufactured effects in this repo twice. Nine pools is also
far below the ~30 clusters cluster-robust asymptotics need, so the clustered *t* is decoration
and the rotation *p* is the inference.) BY-FDR at q = 0.10 over all 21.

| exposure | outcome | β | t (clustered) | p (rotation) | BY |
|---|---|---|---|---|---|
| race losses | \|ret\| +15m | **−0.00434** | −1.77 | <1e-4 | **yes** |
| race losses | \|ret\| +1m | −0.00117 | −1.59 | 0.004 | . |
| race losses | \|ret\| +5m | −0.00169 | −1.07 | 0.014 | . |
| all failures | \|ret\| +15m | −0.00227 | −1.78 | 0.018 | . |
| race losses | landed swaps +5m | −0.765 | −0.62 | 0.032 | . |
| race losses | ret +5m | −0.00099 | −1.14 | 0.040 | . |
| solo aborts | \|ret\| +1m | +0.00042 | 0.67 | 0.044 | . |
| all failures | \|ret\| +5m | −0.00095 | −1.23 | 0.074 | . |
| *(13 further rows, p from 0.15 to 0.72)* | | | | | . |

**One survivor of 21, and it is negative.** A one-SD burst of race-losses predicts 43 bps
*less* absolute movement over the following 15 minutes, conditional on the successful-trade
count and the current move. Read plainly: the scramble marks the *end* of a volatile episode,
not its beginning. That is a coherent story and it is still one row out of 21 with a
small coefficient, so it is a lead and not a finding.

**The house base rate is nulls, and this is a null.** The pre-registered family was fixed
before any coefficient was inspected; composition-based exposures (e.g. surges specifically in
the stale-quote codes) were deliberately *not* tested, because adding exposures after seeing
the table is the whole failure mode. That is the next pre-registered test, not this one's
result.

**The survival arm the brief asked for is not identified and was not run.** Failures exist on
9 pools; a hazard model of coin death needs thousands of coins, and the only dataset with
thousands of coins is the corpus, which has zero failures. Fitting `lifelines` to 9 pools to
have fitted it would be theatre.

---

## 5. Where the failure stream *does* pay: our own execution

### 5.1 Congestion is persistent enough to read before sending

Predicting whether the next minute lands in this pool's top failure decile, from this minute's
failure count alone:

| pool | minutes | ρ(1) | ρ(5) | AUC |
|---|---|---|---|---|
| nosis/SOL | 6,734 | 0.542 | 0.221 | **0.902** |
| weave/SOL (DLMM) | 1,835 | 0.395 | 0.086 | 0.759 |
| weave/SOL | 14,476 | 0.418 | 0.129 | 0.710 |
| DREGG/SOL | 68,200 | 0.485 | 0.062 | 0.596 |
| weave/DREGG (5%) | 3,256 | 0.320 | 0.019 | 0.571 |
| SOLVE/SOL | 34,547 | 0.295 | 0.012 | 0.561 |

Mean AUC **0.683**; 0.902 on the busiest pool. ρ(5) collapses to ~0.02–0.22, so the horizon is
**about one minute** — long enough to gate a send, far too short to plan around.

Landing rate is **85.9% averaged over minutes but 18.0% weighted by transaction**. The gap *is*
the phenomenon: failures are concentrated into a few very busy minutes, which is exactly why a
one-minute-ahead gate has anything to gate.

### 5.2 The price of admission, and it is not what "pay more" implies

Exact bids, recovered by decoding `ComputeBudget::SetComputeUnitPrice` in the RPC sample
(present on 99% of failures and 94% of landed swaps):

| arm | n | p25 | p50 | p75 | p95 |
|---|---|---|---|---|---|
| failed | 1,666 | 1,904 | **4,185** | 11,035 | 57,028 |
| landed | 600 | 48,025 | **264,872** | 1,112,028 | 8,369,721 |

**A 63× median gap in µlamports per compute unit.** Same picture in total fee, matched inside
the same pool-minute so the comparison never crosses a fee regime:

| pool | minutes | med fail | med land | ratio | failures out-bid | p(sign) |
|---|---|---|---|---|---|---|
| nosis/SOL | 2,889 | 7,500 | 67,890 | **9.1×** | 10.1% | <1e-4 |
| weave/SOL | 724 | 14,040 | 55,777 | 4.0× | 24.9% | <1e-4 |
| weave/DREGG (5%) | 112 | 19,973 | 78,263 | 3.9× | 23.2% | <1e-4 |
| weave/SOL (DLMM) | 147 | 7,527 | 25,001 | 3.3× | 24.5% | <1e-4 |
| DREGG/SOL | 4,287 | 11,375 | 35,180 | 3.1× | 29.3% | <1e-4 |
| SOLVE/SOL | 267 | 55,000 | 37,726 | 0.7× | 45.7% | 0.18 |

Pooled, failures out-bid the landed swap in only **22.7%** of the minutes where both occur.

And the compute side, which is where the failing population is wasting money outright:

| arm | median CU requested | median consumed | utilisation |
|---|---|---|---|
| failed | 359,880 | 69,414 | **18.7%** |
| landed | 229,049 | 122,998 | 62.7% |

The priority fee is charged on the *requested* limit. The failing population requests 1.6× the
compute of the landing population and uses under a third as much of it — paying for air, and taking
scheduler room while they do it.

**The operational reading.** Two things that are usually conflated come apart here. Whether a
transaction *lands* is a fee-market outcome and we can read its clearing price directly: the
median successful fill on nosis/SOL paid 67,890 lamports in the same minute a failure paid
7,500. But most *failures* are not bids that lost — they are arb programs whose in-program
precondition failed, and they would have reverted at any price. So "raise the fee to stop
failing" is right for the 4.0% failing inside an AMM and meaningless for the 96.0% that are
not, and only the block-position test (§2) tells you which situation you are in. If our own
sends are failing with an AMM-level code while the minute's landed swaps bid 10× ours, that is
a fee problem. If they are failing at 0.84× block-competition lift, it is not.

**Caveat, stated rather than buried:** `landed` and `failed` are not two arms of an experiment.
A router that lands is a different kind of program from an arb bot that aborts, and part of the
63× gap is that difference rather than a price the same sender faced. The comparison is a
description of what it costs to be in the landing population, not an estimate of the causal
effect of bidding more. `landed` also includes our own sends; without a signer column they
cannot be excluded, and at our volume they are a rounding error in this population.

---

## 6. Held-out window: the taxonomy drifts

The live cluster tape covers 2026-08-09 → 08-15; the bulk export stops 2026-08-13. That leaves
182,842 rows strictly after the training window, on 12 pools instead of 9.

| signature | held-out share | training share | rank in training |
|---|---|---|---|
| `i5:0x1` | **20.3%** | 5.5% | 5 |
| `i5:0x1388` | **11.9%** | 4.2% | 6 |
| `i4:0x3c` | 6.8% | 8.5% | 3 |
| `i4:0x1780` | 6.7% | 7.4% | 4 |
| `i3:0x1770` | 4.7% | 9.0% | 2 |
| `i0:0x8` | 3.2% | 0.5% | 29 |
| `i3:0x51` | **2.8%** | 12.5% | **1** |

**Total-variation overlap between the two error-code distributions: 56.0%.** The *catalogue*
is stable — nine of the held-out top twelve are top-30 in training — but the *mix* moves a
lot in two days. `i3:0x51`, 12.5% of all training failures and rank 1, collapses to 2.8%.

That is a load-bearing caveat for anything built on this: a machine census from the failure
stream has a **half-life of days**, because the machines themselves come and go. The
persistence result survives out of sample (lag-1 autocorrelation of the failure count 0.207 on
12 pools including several very quiet ones, against 0.30–0.54 per pool in training); the
composition does not.

---

## 7. What this changes, and what to record next

**Ranked by value per unit of work.**

1. **Put `fee_payer` and the failing program on the `attempt` row.** It costs one
   `getTransaction` per failure, which is exactly the cost the row was designed to avoid — but
   the tape already fetches `getTransaction` for every *success*, and on the busiest pool
   failures are 60% of the listing. A middle option that costs almost nothing: fetch the
   transaction only for failures whose block also contains one of our own sends. §3 shows what
   identity buys; §6 shows it decays in days, so it has to be collected continuously or not at
   all.
2. **Correct `scripts/pump_history.py`'s schema table.** `err` is documented as though it
   varies. It is constant, for a structural reason worth one sentence in the docstring, and the
   next study to plan around it will otherwise lose the same afternoon.
3. **A pre-send gate is worth building and is cheap.** One minute of failure-count history,
   AUC 0.68–0.90 for the next minute being a top-decile failure minute, plus the minute's
   median landed fee as the bid to clear. Both come from data the recorder already writes. The
   honest expectation is that it prevents a handful of wasted fees per day, not that it makes
   money.
4. **Do not build a signal out of failure surges.** 1 of 21, negative, on 9 pools. If it is
   revisited, the pre-registered next test is composition (stale-quote codes vs solo-abort
   codes as separate exposures) on a window that includes more than one dominant pool — 82.2%
   of this evidence is nosis/SOL.

**What would falsify the main claims.**

- *The fingerprint names machines* — falsified if the median top-payer share inside a top cell
  drops below ~20% (near the 8% baseline) on a fresh RPC sample from a later window.
- *Two populations, racers and self-aborters* — falsified if the block-competition lift and the
  minute-matched pre-move stop agreeing in sign across signatures on the next 10 days.
- *No forward price signal* — falsified if any of the 21 pre-registered rows reaches rotation
  p < 0.01 with the same sign on a disjoint window. One row currently does; a second window
  would settle it.
- *The 63× bid gap* — falsified if the median landed CU price falls within 3× of the median
  failed CU price in a later sample, which would mean the two populations had merged.

---

## Appendix: instrument notes

- **The panel** is one DuckDB pass over 48 day-files → `studies/data/failure_stream/panel.parquet`
  (3,384,841 rows, 11 s). Every raw amount is read as `BIGINT`, never `float`, per the
  `shitcoims_cluster.tape` rule; the log price ratio is the only place a float appears.
- **Pool orientation is derived, not hardcoded.** The `X/SOL` pools name the mint that is not
  WSOL (`DREGG`, `NOSIS`, `WEAVE`, `SOLVE`), and those names then orient the token/token DLMM
  pools from their labels. Adding a pool needs no code change.
- **Prices are vault ratios.** `curve_source` is `absent` and `replay_sufficient` is `false` on
  every row of this export — the virtual-reserve term of a boosted PumpSwap pool lives in
  `log_messages`, which is empty for this window. So the price *level* is not the pool's true
  quote for a boosted pool. Everything here is a log *difference*, which the missing constant
  affects only through the boost term's slow drift; magnitudes are attenuated, signs are not.
- **The rotation null** was re-implemented via Frisch-Waugh-Lovell after a naive version spent
  an hour refitting the full design 10,500 times. Residualise `y` on the controls once through
  a QR, then each rotation is one projection: identical coefficients, ~100× faster.
- **The RPC sample** is read-only Helius `getTransaction` at concurrency 4, cached to
  `studies/data/failure_stream/rpc_sample.jsonl` and resumable; 2,266 fetched. `SetComputeUnitLimit`
  and `SetComputeUnitPrice` are decoded from the base58 instruction data directly, which is
  where the exact bid comes from — `fee_lamports` alone cannot separate the priority price from
  the signature count.
