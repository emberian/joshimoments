# RESULT: seasonality — the operations calendar, and the null where a trading rule would be

2026-08-15. Instrument: `studies/seasonality.py`. Reproduce:
`uv run --group research python studies/seasonality.py all`
(sections: `calibrate chain launch wiggle_pools landing fees calendar`; `wiggle` — the corpus
cohort — is excluded from `all` on purpose, see §7).

Data: `state/bulk_pump/daily/` (106,639,238 transactions, **ten UTC days**, every pump.fun
coin), `state/bulk_history/parquet/` (our 9 pools, **48 days**), and
`.cache/position_history/ledger.json` (the operator's claim receipts, used to *correct* the
brief rather than to answer it). Read-only throughout; nothing signed, nothing sent.

**The operator's framing was "any hypothesis simple enough to phrase likely isn't predictive.
we should still look anyway the best we can." Both halves survive contact with the data.**
There is enormous, unmistakable diurnal structure in this market — and none of it is a
trading edge, because it is visible to everyone with a clock. What it *is* good for is
operations, which are not adversarial: nobody arbitrages away the fact that the chain's p90
fee is **66% higher at 15:00 UTC than at 07:00** (median fee, 44% higher).

---

## 0. The null, calibrated before it is used

The tempting null — circularly rotate the whole series — is **useless here**, and it is worth
saying why because it is the obvious thing to reach for. A genuine 24 h cycle survives
rotation with its amplitude intact and only its phase moved. The null would reproduce the
effect and nothing could ever be rejected.

The null used instead **re-phases each day independently**. Within-day autocorrelation and
each day's own shape survive; what is destroyed is the *alignment of phase across days*,
which is exactly and only what "locked to the clock" asserts. The statistic is the dispersion
of the day-normalised hour-of-day profile.

A null is worth nothing until you have shown it rejects what it should and tolerates what it
should, so it is run against three synthetic worlds first (`seasonality.py calibrate`,
60 simulations each):

| world | days | rejects at α = 0.05 | median p |
|---|---|---|---|
| i.i.d. noise | 10 | 8.3% | 0.493 |
| **strong within-day autocorrelation (ρ = 0.85), phases independent across days** | 10 | **8.3%** | 0.545 |
| true 24 h sinusoid, amplitude 0.15 | 10 | **100%** | 0.005 |
| true 24 h sinusoid, amplitude 0.15 | 48 | **100%** | 0.005 |

The second row is the one that matters: a metric can be smooth and bursty without being
locked to the clock, and this null does not mistake one for the other. Size is mildly liberal
(~8% at a nominal 5%, within about one standard error at 60 simulations), which is one more
reason the calendar is reported after BY-FDR rather than test by test. Power is complete at
the amplitudes actually observed below (0.12–0.16).

Confidence intervals resample **days**, because a day is the unit that repeats. Hours inside
a day are not independent and treating them as such would shrink every interval for free.

---

## 1. The chain clock — and it is enormous

Ten days, all four metrics at the p-floor of 2,000 phase-scrambles (p = 0.0005).

| metric | peak | trough | peak−trough, as % of the day's mean | amplitude | p |
|---|---|---|---|---|---|
| transactions per hour | **19h** UTC | 09h | **40.4%** | 0.122 | 0.0005 |
| median fee paid | **15h** UTC | 09h | **47.2%** | 0.128 | 0.0005 |
| p90 fee paid | **15h** UTC | 07h | **50.7%** | 0.156 | 0.0005 |
| compute units consumed | **19h** UTC | 09h | **42.4%** | 0.129 | 0.0005 |

The day-normalised profiles (1.000 = that day's own mean):

| hour UTC | tx/h | median fee | p90 fee | compute |
|---|---|---|---|---|
| 00 | 0.98 | 0.92 | 1.00 | 0.99 |
| 03 | 1.07 | 0.88 | 0.88 | 1.08 |
| **06** | 0.84 | 0.98 | **0.79** | 0.84 |
| **07** | 0.84 | 0.92 | **0.77** | 0.82 |
| **09** | **0.83** | **0.85** | 0.82 | **0.81** |
| 12 | 0.94 | 0.97 | 0.96 | 0.94 |
| **15** | 1.06 | **1.32** | **1.27** | 1.07 |
| 17 | 1.10 | 1.26 | 1.23 | 1.13 |
| **19** | **1.23** | 1.10 | 1.26 | **1.23** |
| 21 | 1.13 | 0.91 | 1.05 | 1.12 |
| 23 | 1.06 | 0.91 | 0.98 | 1.05 |

Two clocks, not one, and they are 4 hours apart. **Fees peak at 15:00 UTC; activity and
compute peak at 19:00 UTC.** The fee peak lands on the US equities open (11:00 ET) and the
activity peak on the US afternoon. The quiet window is unambiguous and wide: **06:00–10:00
UTC**, where the p90 fee runs 14–23% below the day's own mean and activity 16–19% below.

That fee/activity split is not a curiosity, it is the operationally useful part. The cheapest
hour to transact is *not* the quietest hour for volume — 03:00 UTC has 7% above-average
activity at 12% below-average fees. Congestion pricing and congestion are different series.

---

## 2. The launch clock — the largest, cleanest pattern in the data

449,731 distinct pump mints in the corpus. The first corpus day is dropped, because a coin's
first *sighting* is not its birth and day one would otherwise show the entire back catalogue
arriving at once as a launch spike; that leaves **383,413 coins with an observed launch** over
9 days, **1,775 launches per hour** on average.

| | |
|---|---|
| peak | **19h UTC**, 1.36× the day's mean (bootstrap spread −2…+0 h) |
| trough | **06h UTC**, 0.70× |
| peak−trough | **65.4%** of the day's mean — the widest swing of any metric here |
| p (phase-scramble) | **0.0005** (the floor at 2,000 draws) |

Coin creation is the most human act in this market — a person decides to launch — and it has
the most human clock: a broad plateau from 14:00 to 22:00 UTC and a deep trough at 05:00–09:00.

### 2.1 And the hour of birth predicts survival — backwards

Purely descriptive (this was *not* entered into the multiplicity family below, because it is a
cross-sectional contrast rather than a diurnal amplitude test), but it inverts the obvious
guess:

| birth hour UTC | coins | median prints | reaching ≥ 200 prints |
|---|---|---|---|
| 00h | 15,054 | 16 | 15.1% |
| 03h | 14,192 | 12 | 15.2% |
| **06h** (launch trough) | 11,197 | 16 | **17.0%** |
| 09h | 11,555 | 12 | 15.3% |
| 12h | 15,021 | 12 | 14.7% |
| **15h** | 19,220 | 11 | **12.6%** |
| **18h** (launch peak) | 20,737 | 11 | **12.9%** |
| 21h | 17,841 | 19 | 16.4% |

**Coins born in the busiest launch hours are the *least* likely to survive** — 12.6% at 15:00
against 17.0% at 06:00, a 35% relative difference in survival for a coin launched into the
crowd. The peak hour is when the spam is, not when the quality is. Mean across hours 14.6%.

---

## 3. The wiggle clock — the null, and it is the important one

This is the metric that would actually be tradeable, and it is measured two ways.

**On our own 9 pools, 47 days, exact integer vault reserves** — 3,372,421 priced prints on the
5 SOL-quoted pools, 1,643 pool-hours with ≥ 8 prints, of which **85.1% contain at least one
oscillation clearing the coin's own round-trip friction** (`shitcoims_paperdesk.friction` at
the operator's 0.1 SOL clip — the same module the desk trades on, so these numbers are
comparable with the desk's).

| metric | days | peak | trough | p |
|---|---|---|---|---|
| **`wiggle_net` per pool-hour (oracle bound)** | 47 | 09h | 03h | **0.7016** |
| friction-clearing swings per pool-hour | 47 | 00h | 05h | 0.0355 (does not survive BY) |

**`wiggle_net` is a flat null at p = 0.70, with 47 days of power behind it.** The bootstrap
peak spread is −9…+0 h, which is another way of saying the profile has no peak to find. The
swing *count* is marginal at p = 0.036 and does not survive multiplicity.

This is the single most decision-relevant line in the study, and it is worth being precise
about how much power stands behind it: §0 shows this null detects a 24 h cycle of amplitude
0.15 **100% of the time at ten days**, and this test had forty-seven. A pattern of the size
that governs launches, fees and transaction counts would have been found here several times
over. It is not there.

`wiggle_net` is an **oracle bound** — it assumes turning at the exact extremes, which no live
rule achieves. That makes the null stronger, not weaker: a null on the oracle is a null on
every rule inside it.

---

## 4. The congestion clock — nothing survives on our own pools

47 days, 2,094 pool-hours, 3,384,841 transactions.

| metric | days | peak | trough | p | BY |
|---|---|---|---|---|---|
| failure share of pool traffic | 47 | 16h | 03h | 0.0330 | no |
| median fee on our pools | 47 | 07h | 10h | 0.6217 | no |
| pool depth = the AMM's spread | 47 | 21h | 13h | 0.7206 | no |

Depth is the spread here, and that is not a substitution — there is no order book on an AMM
and no quoted spread; what a taker pays above mid is entirely price impact, and impact is a
function of the quote reserve. So the quote vault *is* the spread series, and it has no clock
at all (p = 0.72, amplitude 0.026 — the profile is flat to within ±3%).

The failure share is the near-miss: 16:00 UTC runs +5.6 points and 03:00 −5.1 points against
the day's own mean, at p = 0.033, which does not clear BY-FDR across eleven hypotheses. Note
this is the *chain-level* congestion pattern showing faintly through a 9-pool sample — §1
finds the same shape market-wide at p = 0.0005. The honest reading is that our pools are too
few and too idiosyncratic to recover a pattern that is unambiguous in the population.

### 4.1 The week, on the only series that has one

DREGG/SOL is the only pool with more than one week of history, and it has 6.9. This is
**description of seven weekdays, not inference about a weekly cycle.**

| day | weeks | mean failure share | sd across weeks | mean tx/day |
|---|---|---|---|---|
| Mon | 7 | 31.5% | 10.2% | 3,887 |
| Tue | 7 | 32.1% | 9.6% | 12,142 |
| Wed | 7 | 29.9% | 6.6% | 22,068 |
| Thu | 7 | 27.0% | 16.6% | 18,906 |
| Fri | 6 | 29.7% | 8.4% | 5,988 |
| **Sat** | 7 | **21.2%** | 7.9% | 5,631 |
| Sun | 7 | 26.6% | 7.6% | 7,253 |

Saturday is 10.9 points quieter than Tuesday, against a within-weekday standard deviation of
9.6 points across weeks. **The instrument prints "separable" on the crude spread > sd test and
that verdict should be ignored** — with seven observations per weekday the standard error of a
weekday mean is ~3.6 points, so a 10.9-point gap is roughly two standard errors *before* any
adjustment for the 21 pairwise comparisons on the table, and it rests on one pool. Recorded as
a hypothesis for the next 40 days of collection, not as a finding.

---

## 5. The income clock — and why the claims ledger cannot answer this question

**The brief asked for "fee income arrival (the DREGG claims ledger)". The claims ledger cannot
answer it, and using it would have produced a confident wrong answer.** A claim is a
transaction *the operator sends*. Its timestamp is a human's sleep schedule, not the market's
clock, and there are 260 of them against 96,414 swaps. Measured, so that nobody has to take
this on faith — claims by hour of day:

```
[7, 14, 12, 5, 7, 8, 5, 7, 6, 5, 5, 3, 8, 13, 14, 16, 13, 21, 13, 17, 18, 19, 11, 13]
```

Mode 17:00 UTC, 8% of claims in the modal hour, and the six quietest hours still hold 11%.
That is a nearly flat human calendar with a mild evening lean. Reading seasonality out of it
would measure when the operator is awake.

What the desk actually wants is when the fee **accrues**, and the creator fee is a fixed share
of swap volume, so the accrual clock *is* the volume clock — exactly derivable from the 48-day
tape:

| pool | quote-leg flow over 48 days (SOL) |
|---|---|
| DREGG/SOL | 100,418.7 |
| nosis/SOL | 86,548.9 |
| weave/SOL | 13,357.2 |
| SOLVE/SOL | 7,004.1 |
| weave/SOL (DLMM) | 106.1 |

**DREGG/SOL quote-leg flow per hour: peak 14h UTC at 1.68× the day's mean, trough 09h at
0.62×, p = 0.0005, amplitude 0.288 — the largest surviving amplitude in the study.** A
secondary peak at 17:00 (1.57×) and a broad 20:00–21:00 shoulder (1.24–1.32×).

Fee income arrives **2.7× faster at 14:00 UTC than at 09:00 UTC**. That is the single most
usable number in this report.

---

## 6. The operations calendar

Eleven diurnal hypotheses, Benjamini-Yekutieli at q = 0.10. **Six survive, and the split
between the survivors and the nulls is the whole result.**

| metric | days | peak | trough | amplitude | p | BY |
|---|---|---|---|---|---|---|
| DREGG/SOL quote-leg flow per hour | 47 | **14h** | 09h | 0.288 | 0.0005 | **yes** |
| new coins per hour | 9 | **19h** | 06h | 0.202 | 0.0005 | **yes** |
| p90 fee paid (chain-wide) | 10 | **15h** | 07h | 0.156 | 0.0005 | **yes** |
| compute units consumed (chain-wide) | 10 | **19h** | 09h | 0.129 | 0.0005 | **yes** |
| median fee paid (chain-wide) | 10 | **15h** | 09h | 0.128 | 0.0005 | **yes** |
| transactions per hour (chain-wide) | 10 | **19h** | 09h | 0.122 | 0.0005 | **yes** |
| friction-clearing swings per pool-hour | 47 | 00h | 05h | 0.214 | 0.0355 | no |
| failure share of pool traffic | 47 | 16h | 03h | 0.029 | 0.0330 | no |
| median fee on our pools | 47 | 07h | 10h | 0.150 | 0.6217 | no |
| **`wiggle_net` per pool-hour** | 47 | 09h | 03h | 0.227 | **0.7016** | **no** |
| pool depth / AMM spread | 47 | 21h | 13h | 0.026 | 0.7206 | no |

(Amplitudes are comparable *within* the day-normalised group and within the day-demeaned group
— `wiggle_net` and failure share are demeaned, everything else normalised — but not across the
two.)

**Every survivor is a measure of how much is happening. Every null is a measure of how good
the opportunity is.** Volume, launches, fees and compute are locked to the clock at the p-floor
in both the 10-day population and the 47-day pool series. Wiggle quality, spread, and landing
odds are not locked to the clock at all, with more days of data behind them. That is exactly
the operator's prior — *"any hypothesis simple enough to phrase likely isn't predictive"* —
and it is the most useful thing here, because it says where **not** to spend effort.

**The calendar itself:**

| when (UTC) | what is true | what to do with it |
|---|---|---|
| **06:00–10:00** | chain quietest: p90 fee 14–23% below the day's mean, activity 16–19% below, launches at 0.70× | **do discretionary chain work here** — claims, rebalances, position moves, anything that pays gas but is not time-critical |
| **14:00** | DREGG fee accrual peaks at **1.68×**; second peak 17:00 at 1.57× | expect income; do **not** infer a trading window from it |
| **15:00** | chain fees peak, median +32% and p90 +27% | **avoid non-urgent sends**; if we must send, expect to clear a materially higher bid (see `RESULT_failure_stream.md` §5.2 for what actually clears) |
| **19:00–20:00** | activity and compute peak (1.23×), launches peak (1.36×) | most new coins to look at, most competition for blockspace |
| **any hour** | wiggle quality, spread and landing odds have **no clock** | **do not schedule harvesting.** Watch a trigger, not the time of day |
| Saturday | possibly quieter (21.2% vs 32.1% failure share on DREGG) | too weak to act on; collect 40 more days |

**What would falsify each survivor**, on the next ten days — the nightly top-up path already
collects everything needed, and `seasonality.py` is offline-reproducible from cache:

| claim | falsified if, on the next 10 days |
|---|---|
| DREGG fee accrual peaks at 14h | the peak moves > 4 h from 14:00 UTC, or phase-scramble p > 0.10 |
| launches peak at 19h | the peak moves > 4 h from 19:00 UTC, or p > 0.10 |
| chain fees peak at 15h (median and p90) | either peak moves > 4 h from 15:00 UTC, or p > 0.10 |
| activity and compute peak at 19h | either peak moves > 4 h from 19:00 UTC, or p > 0.10 |
| **wiggle quality has no clock** | `wiggle_net` reaches p < 0.01 **with the same peak hour** on a disjoint window. One re-run cannot resurrect a null; a consistent peak across two disjoint windows would |

---

## 7. Limits, and what was not done

- **Ten days is 1.43 weeks.** Nothing weekly is claimed from the corpus. The one weekly table
  is one pool over 6.9 weeks and is labelled description.
- **The population-level wiggle cohort was not run.** `seasonality.py wiggle` builds a sampled
  3,000-mint price cohort from the corpus and applies the same zigzag; it is deliberately
  excluded from `all` because it is a ten-day corpus fold and this machine is shared. §3's
  wiggle result is therefore *our nine pools*, not the coin population the operator would
  harvest. Run it alone, or on persvati (24 cores, 73 GB free, corpus present at
  `~/corpus/bulk_pump/`), with `uv run --group research python studies/seasonality.py wiggle`.
  **This is the one place where a different answer is genuinely plausible**, because the
  harvest target is the long tail of collapsed coins and not the pools we happen to be long.
- **Only diurnal amplitude was multiplicity-controlled.** The birth-hour survival contrast
  (§2.1) and the weekday table (§4.1) are descriptive and were kept out of the family
  deliberately rather than quietly included.
- **Hour of day is UTC throughout.** No claim is made about which population's waking hours
  produce the 19:00 peak; the shape is consistent with US afternoon but the study cannot
  distinguish that from any other explanation of the same shape.

## Appendix: the resource episode, recorded because it is a reusable lesson

This study's corpus passes had to be rebuilt three times, and the reasons are worth keeping.

**`SET memory_limit` does not bound a DuckDB process.** A whole-corpus `UNNEST` aggregate with
`memory_limit='6GB'` reached **14.3 GB of RSS**. The limit governs DuckDB's own buffer manager;
it does not govern the `UNNEST` expansion of a 3 GB list column, nor the Arrow→pandas
materialisation on the way out. The memory knob for `UNNEST` is **threads** — one buffer each.

**Tightening a memory limit is not monotonically safer.** Measured on the largest corpus day:

| setting | peak RSS | outcome |
|---|---|---|
| threads=6, limit 6 GB | 8.6 GB | killed, over ceiling |
| threads=2, limit 3 GB | 4.7 GB | `OutOfMemoryException` on the largest day |
| threads=1, limit **4 GB** | 5.6 GB, 111 s | **completes** — the setting shipped |
| threads=1, limit 3500 MB | 6.7 GB | *worse on both axes*: fell off a spill cliff, days went from ~2 min to >20, `/tmp` grew past 5.6 GB, and peak RSS went **up**, because re-read traffic costs more memory than the buffer it was meant to save |

**Fold per day, and make the cache atomic.** Each corpus day is folded separately and written
to a `.partial` file that is `rename`d on success, so a kill costs one day rather than the run.
The first version checked only for existence, and a killed `COPY` left a zero-byte file that
poisoned the cache and failed three frames deep inside pyarrow with a message about a
`<Buffer>` — nowhere near the actual cause.
