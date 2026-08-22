# Birth-aligned lifecycle of a pump coin

What the first minutes, hour and day of a coin's life look like when every coin is put on its own
clock, what "goes to zero" decomposes into, whether a candle view carries anything a flow view does
not, and whether anything measured early is informative about what follows.

Scripts: `lifecycle_cohort.py` → `lifecycle_describe.py` → `lifecycle_geometry.py [cutoff]` →
`lifecycle_predict.py [cutoff]`. Whole chain is about 90 seconds against the ten-day artifact.
Nothing is written to the repo but the scripts; derived parquet lands in the scratchpad corpus.

---

## 0. The clock, and what it cost to get one

Coin histories are not comparable on wall-clock time. "What does minute 3 look like across 200,000
coins" is a question; "what does 2026-08-09T14:22Z look like" is not. Every mint here is re-indexed
onto `dt = block_time - t0`.

**t0 is birth, not first-trade.** The corpus has no callout tape, so the origin available is
on-chain. For a mint whose bonding curve is seeded inside the window the create transaction itself
is observed, which is a stronger origin than "the first trade I happened to see" and is exactly the
"first day of a coin's life" that was asked for. The delay from birth to the first *later* curve
event is then a measured quantity rather than a definitional zero: median 0 s, p75 1 s, p90 6 s,
p99 229 s. Choosing first-trade alignment instead would move the clock by under a second on most
coins.

**The live callout-aligned version of this study is the natural sequel and we cannot do it here.**
It needs callout occurrence *and availability* times captured prospectively, which we do not retain.

### Membership funnel — half the `%pump` mints are not in this study

| step | mints | note |
| --- | ---: | --- |
| all `%pump` mints in the corpus | 449,723 | selection is a vanity-suffix convention with unmeasured recall |
| curve seed observed at the mint's first transaction | 332,396 | the rest are **left truncated** — they existed before the window |
| ...and an identified bonding curve (≥1 `curve_constant_product_readout` trade) | 262,386 | the corpus's own venue evidence, validated to a median 4.8e-9 against pump.fun's board |
| ...and standard supply (curve balance never exceeds 1.001e15 raw) | 226,920 | ~13% of born mints launch on a non-standard supply; a different K does not cancel out of a level |
| ...and the curve account is present, at zero, in the create tx | **226,760** | the cohort |

The 26% dropped at step 2 are not a data defect, they are coins born before 2026-08-05. The 20%
dropped at steps 3-4 matter more: a `%pump` suffix does not imply a pump.fun bonding-curve market.
A visible sub-population of these mints shuffles a full 1e15 supply between two accounts with **no
wSOL leg at all** and is swept ~24 hours later. Those are not coins with a market and pooling them
into a lifecycle study would have contaminated every number below.

### The event stream is the curve account's balance path, not `trades.parquet`

Venue identification in `trades.parquet` is per (mint, owner), and a transaction still lands as
`unsupported` when it is multi-venue or the wSOL pairing is ambiguous: on a quarter of these mints
**half** the curve's own balance changes are unpriced there. Reading the curve account's flow rows
directly recovers every state change. 21,063,994 events over the cohort's first seven days.

The create transaction is kept as the t=0 event with its pre-state set to full supply. It carries an
atomic creator buy on 178,709 of 226,760 mints (78.8%), median **3.4% of the sellable curve**
against a 0.4% median ordinary trade. Dropping it — which the obvious "trades after the create"
filter does — leaves every first-hour flow imbalance biased toward selling.

### Right-censoring and the coverage hole

234 of the window's 14,400 minutes are absent, all inside a 14.73-hour hull on 2026-08-12/13. Every
horizon statistic is restricted to mints whose whole horizon lay inside the window **and** clear of
that hull:

| horizon | in-window | usable (also clear of the hole) |
| --- | ---: | ---: |
| 1 h | 225,859 | 211,613 |
| 24 h | 203,847 | 166,234 |
| 7 d | 64,276 | **9,165** |

**The seven-day question is effectively unanswerable in this corpus.** Any 7-day window from a birth
after 2026-08-05 11:42 UTC runs into the hole, so the strict 7-day panel is 9,165 mints all born
inside one 11.7-hour stretch. Both a strict and a lenient 7-day panel are reported and neither is
load-bearing. The first *day* is solid; the first *week* is a hint.

---

## 1. What the early window actually looks like

### Arrival intensity is an aftershock decay

Events per at-risk mint per minute, by age. The denominator only counts mints whose observation
window covers the bucket.

| age | 0-10 s | 10-30 s | 1-2 min | 5-10 min | 30-60 min | 4-8 h | 24-48 h | 4-7 d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| events/mint/min | 93.1 | 43.6 | 10.9 | 1.61 | 0.107 | 0.0066 | 0.0006 | 0.0001 |
| % of mints active | 100 | 61.0 | 37.0 | 21.4 | 10.1 | 6.6 | 5.3 | 3.3 |

Log-log fit over 30 s to 12 h: **intensity ~ t^-1.35, r² = 0.996.** That is an Omori/aftershock
shape, described, not fitted as a point process. Four orders of magnitude of decay inside one day.

### Participants arrive essentially all at once

Distinct non-curve token-account owners by age (mean / median): by 5 min 28.2 / 7, by 1 h 33.4 / 7,
by 24 h 35.4 / 7. **80% of every account a coin will ever touch in its first day has already touched
it by minute five.** These are account owners, not people: a router or program PDA counts as one.

### Trade sign is strongly persistent

Pooled over the cohort's first hour, in event time, 18.8M consecutive pairs: lag-1 sign
autocorrelation **0.346**, lag-2 0.265, lag-5 0.148, lag-10 0.106. Mean sign +0.050 — mildly
buy-heavy. Per-mint, the median share of consecutive same-sign pairs is 0.68 against a 0.5
coin-flip. Long-memory order flow survives on this venue.

### Trades are small and get smaller

As a fraction of the sellable curve, median / p90 / p99: first 5 min 0.41% / 3.3% / 11.7%; 5 min-1 h
0.21% / 1.75% / 5.1%; 1-24 h 0.22% / 2.1% / 5.0%. Median MODEL SOL leg 0.20 SOL in the first five
minutes, p99 4.4 SOL. *MODEL* — the constant-product integral, not an observed SOL amount; the curve
holds native lamports and this export does not carry them.

### Survival — how long does a coin live

P(the coin's last curve event is at age ≥ A). No silence threshold enters this table; it is the
survival function of the last observed event.

| age | 1 s | 30 s | 1 min | 5 min | 15 min | 1 h | 6 h | 24 h | 3 d | 6 d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| % still transacting | 80.5 | 70.8 | 63.4 | 36.8 | 27.7 | 20.7 | 14.3 | 8.0 | 4.7 | 1.2 |
| evaluable mints | 213,382 | 213,371 | 213,361 | 213,248 | 212,996 | 211,613 | 201,661 | 166,234 | 94,700 | 29,755 |

**Nearly one coin in five is finished within one second of being created.** Two in three are
finished within five minutes. The denominator shrinks with age because of censoring, and is printed
so that shrinkage cannot be mistaken for mortality.

Reading "last event" as death is licensed by the **resurrection hazard**, measured rather than
assumed. Among silences of at least *g* that we could have observed ending:

| silent for | 5 min | 30 min | 1 h | 6 h | 12 h | 24 h |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| % that ever traded again | 56.2 | 37.8 | 31.4 | 16.6 | 11.5 | **6.1** |

A one-hour gap is a pause, not a death — a third of them end. Six hours is the first threshold at
which silence is mostly terminal, and it is the one the outcome table uses.

---

## 2. The outcome vocabulary — "goes to zero" is at least four things

At 24 hours, on the 166,234 mints whose full first day is usable:

| outcome | mints | % | median events | median peak curve sold |
| --- | ---: | ---: | ---: | ---: |
| **D** traded, then silent inside 24 h (≥6 h quiet) | 118,613 | 71.35 | 20 | 21.2% |
| **A** never traded after the create transaction | 29,721 | 17.88 | 1 | 0 |
| **E** still transacting at 24 h — *not censored, the tape continued* | 16,743 | 10.07 | 128 | 48.6% |
| **B** graduated to a pool | 937 | 0.56 | 650 | full drain |
| **C** curve exhausted, no pool seen | 220 | 0.13 | 8 | full drain |

At 7 days (strict panel, 9,165 mints, one birth stretch — read as a hint): D 78.5%, A 20.3%,
B 0.63%, E 0.44%, C 0.16%.

**The thing that "goes to zero" actually means, mechanically.** On a bonding curve the launch price
is a hard floor: the curve account cannot hold more than the supply it was seeded with, so the model
price cannot go below its launch value before migration. "Zero" is a return *to the launch price*,
which happens when every token bought has been sold back into the curve. Where the curve balance
ends up, on the same 166,234 mints:

| final curve balance | mints | % |
| --- | ---: | ---: |
| ≥99.9% of supply back on the curve — fully unwound | 138,649 | **83.41** |
| 99-99.9% | 12,026 | 7.23 |
| 95-99% | 8,585 | 5.16 |
| 80-95% | 4,917 | 2.96 |
| 20.7-80% | 942 | 0.57 |
| at or below the migration floor | 1,115 | 0.67 |

Of the 174,446 mints that ever sold at least 0.1% of supply, **80.4% came all the way back**, with a
median time from first departure to full unwind of **48 seconds** (q25 14 s, q75 370 s, q90 5,405 s).

**The peak is at the beginning.** Median seconds from birth to the deepest curve depletion, by how
far the curve got sold: <1% band 0 s, 1-5% 12 s, 5-20% 2 s, 20-50% 2 s, 50-95% 23 s, ≥95% 415 s. For
every band short of migration the high is reached within seconds and the rest of the life is the
retrace.

---

## 3. Does the candle view add anything the flow view lacks?

### The identity, measured not asserted

On 21,015,948 events the regression of the model log-price change on the log reserve change has
slope **exactly -2.0** with **r² exactly 1.0**. That is the definition of the readout restated on
real data, and it is printed so the next result cannot be mistaken for a discovery.

Net signed taker flow telescopes into the reserve displacement exactly on **99.89%** of mints (the
0.11% are curve accounts closed and reopened). The correlation between a mint's first-five-minute
log return and its reserve displacement is **1.0 to twelve decimal places**.

So: on a bonding curve, a price shape is a re-encoding of the cumulative flow that produced it. Any
geometry computed on curve-priced coins is partly arithmetic on flow, and cannot be treated as
independent evidence about it.

### Candle features are monotone relabellings of flow features

Spearman between each candle statistic over the first five minutes and its flow counterpart:

| candle feature | flow counterpart | Spearman |
| --- | --- | ---: |
| minute-close log return | reserve level at cutoff | 0.9963 |
| maximum up-excursion | peak reserve depletion | 0.99996 |
| bar trade count | event count | **1.000000** |
| minute-close max drawdown | event-resolution drawdown | 0.617 |

The first three are the same object under a fixed monotone map — they cannot separate any pair of
coins the flow feature does not already separate. Their single-feature AUCs are *identical to four
decimals* in stage 4, which is the same fact said twice.

The fourth is where they diverge, and **it diverges in the direction of loss, not gain.** Of the
113,859 mints whose minute candles show no drawdown at all, **57.7% actually had one** at event
resolution. Median event-resolution drawdown 0.182 log (-16.7% from the running high) against a
median candle drawdown of exactly zero; p90 0.974 log (-62%).

**That is Ember's dip, and a one-minute chart does not show it.** The dip-and-recover she watches for
after a callout is, on the median coin, a ~17% move that lives entirely inside a single candle.

### And most coins do not have a chart

Bars are minutes with at least one trade, no forward fill. Median bars in the first five minutes:
**2**. Median in the first *hour*: **2**. p90 in the first hour: 7. **77.1% of the cohort has three
or fewer candles in its entire first hour.** There is no shape to classify. Whatever a chart-shape
model would learn on this population, it would be learning it from two rectangles.

### Verdict

The candle view is a strict lossy function of the flow view on this venue. It adds nothing and
discards the intra-minute excursion that is the object of interest. This is scoped to the bonding
curve: after migration the pool fill price is an observed exchange rate at two vaults, the identity
breaks, and the comparison would have to be redone.

---

## 4. Is anything predictive?

**Declared before looking.** Cutoff 300 s; every feature a pure function of events with dt < 300.
Targets are characterisation targets with **no action attached** — none is a return and nothing here
is a trading rule. Split by **birth day**, earlier trains and later tests, with a one-day buffer so
no training coin's outcome window overlaps a test coin's birth; a random split would leak through
within-day platform-wide attention.

| target | definition | train | test | base rate (test) |
| --- | --- | --- | --- | ---: |
| T1 ALIVE_1H | ≥1 curve event in (300 s, 1 h] | days 0-5, n=133,890 | days 7-9, n=53,658 | 0.3083 |
| T2 ALIVE_24H | ≥1 curve event in (300 s, 24 h] | days 0-3, n=85,730 | day 5, n=24,481 | 0.3424 |
| T3 GRADUATE | ever seen trading against an AMM pool | days 0-5 | days 7-9 | 0.0059 |
| T4 TRACTION | ≥100 curve events in (300 s, 24 h] | days 0-3 | day 5 | 0.0391 |

Model: quartile bins from the **training fold only**, one shrunk cell mean per bin combination
(pseudo-count 20), nothing else. Deliberately stupid — a cell model cannot manufacture a signal that
is not in the data. Negative control (uniform random score) returns AUC 0.48-0.53 on every target.

### The strongest single predictor is an accounting identity

| state at 5 minutes | mints | % of cohort | alive at 1 h | alive at 24 h | graduate |
| --- | ---: | ---: | ---: | ---: | ---: |
| curve fully unwound — nobody holds any | 121,661 | 53.65 | **2.59%** | 4.73% | 0.002% |
| tokens still outstanding | 105,099 | 46.35 | **61.38%** | 70.56% | 1.218% |

A coin nobody holds cannot produce a sell, and a sell is the event being predicted. That single bit
is worth test AUC 0.889 on T1 and it is arithmetic, not insight. **It is the deterministic protocol
component the promotion questions demand be represented explicitly**, and everything below is an
increment *over* it.

### Ablation, test-fold AUC (cutoff 300 s)

| model | T1 alive 1 h | T2 alive 24 h | T3 graduate | T4 traction |
| --- | ---: | ---: | ---: | ---: |
| constant = training base rate | 0.5000 | 0.5000 | 0.5000 | 0.5000 |
| persistence baseline (events in the last minute) | 0.6670 | 0.6553 | 0.7915 | 0.9233 |
| **state only** (reserve level at cutoff) | 0.8730 | 0.8982 | 0.8547 | 0.8762 |
| A: candle / price shape only | 0.8991 | 0.9210 | 0.9222 | 0.9278 |
| B: flow structure only, no price information | 0.8700 | 0.8737 | 0.9472 | 0.9129 |
| state + A — does chart shape add? | 0.9015 | 0.9207 | 0.9419 | 0.9329 |
| **state + B — does flow structure add?** | **0.9281** | **0.9399** | 0.9339 | **0.9451** |
| state + A + B | 0.9275 | 0.9413 | 0.9291 | 0.9333 |

Read three things off this table.

1. **Something is predictive, and it is not large.** Over the deterministic protocol state, flow
   structure (participant count, event count, sign imbalance, sign run rate) buys +0.055 AUC on T1
   and +0.042 on T2. Over the persistence baseline the T4 gain is only +0.022. Brier improves from
   0.122 to 0.095 on T1. The state+B model is well calibrated across deciles on T1 and T2 and
   under-confident in the middle deciles on T2.
2. **Adding the candle set to the flow set never helps.** state+A+B ≤ state+B on three of four
   targets and ties on the fourth. That is the identity above expressing itself in a held-out score.
3. **"A beats B" on T3 is not chart shape winning.** The A features that carry it are maximum
   up-excursion and realised range, which *are* peak reserve depletion and path length — flow
   quantities wearing chart names. `c_log_max_up` and `f_peak_sold_frac` have identical AUCs on
   every target because they are the same number.

Useless features, worth recording: owner concentration (Herfindahl 0.508, top-owner share 0.511 on
T1) carries nothing, and maximum *down*-excursion carries nothing (0.502) because on a pre-migration
curve there is no down: launch price is the floor.

### How much watching is enough

Same fixed outcome window (≥1 event in (1800 s, 24 h], test day 5, base rate 0.2099), three cutoffs:

| watched for | state only | state + B flow | state + A + B |
| --- | ---: | ---: | ---: |
| 60 s | 0.7887 | 0.8441 | 0.8401 |
| 300 s | 0.8407 | 0.8876 | 0.8875 |
| 1800 s | 0.8684 | 0.9206 | 0.9213 |

Thirty minutes of watching is worth about +0.08 AUC over one minute, and most of that is already
there at five. Candles never add anything at any cutoff.

---

## 5. The promotion questions

**What is the target, price object, horizon, and action?** Target: survival and traction of a coin,
as counts of curve events in a declared future window. Price object: `curve_constant_product_readout`
only, a validated MODEL of a marginal price, never pooled with `amm_pool_vault_fill`. Horizon:
1 h and 24 h from a 300 s cutoff. **Action: none.** These are characterisation targets; no rule,
signal or sizing is attached and none should be inferred from an AUC.

**Was every feature available at the decision cutoff?** Yes, by construction: every feature is an
aggregate over events with dt < cutoff, no full-sample standardisation, and the split is by birth
day. The one thing that *looks* like a feature and is not, is the terminal reserve level used as an
outcome-window quantity — it is used only as a cutoff-time state.

**What source/coverage process determines inclusion?** A five-step funnel from 449,723 `%pump` mints
to 226,760, printed above. The binding limits are inherited: `LIKE '%pump'` is a vanity convention
with unmeasured recall, `err` is structurally empty so there are zero failed transactions and no
adverse-selection study is possible on these bytes, and native SOL is not carried so every curve SOL
amount is a model.

**What deterministic protocol component should be removed or represented explicitly?** The reserve
level. It is represented explicitly as `state only` and every other model is scored as an increment
over it. Half the apparent predictability of "will it trade again" is the accounting fact that a
coin nobody holds cannot be sold.

**What simple baseline corresponds to random walk / seasonal intensity / exact curve / current
policy?** Constant base rate (0.5000), a persistence baseline of events in the last minute before
the cutoff (0.655-0.923 depending on target), and the exact-curve state (0.855-0.968). All three are
reported for every target. **Ember's current policy is not represented and cannot be** — there is no
record of which coins she looked at, which is the same gap that blocks the callout-aligned clock.

**How are transaction costs, failure, capacity, and residual inventory scored?** They are not, and
they cannot be here. The corpus contains **zero failed transactions by construction**; every fill
landed. Capacity is unaddressed — the median trade is 0.4% of the curve, so any hypothetical
participation would move the state it conditions on. Residual inventory is unaddressed. This is
exactly why nothing above has an action attached.

**Which held-out regime can reject the claim?** The test folds are strictly later birth days, and
for T1/T3 the test fold spans the 2026-08-12 coverage hole and its aftermath. Base rates drift
across days (alive-at-1h 33.4% on day 0 to 27.5% on day 7, back to 32.7% on day 9) and the ranking
of models is stable across that drift. A stronger rejection test would be a different month and a
different platform-fee regime, which this corpus cannot supply.

**What useful instrument remains if prediction fails?** Three, and they are the actual deliverable:
(1) the **birth-aligned clock and cohort**, which makes any cross-sectional question askable at all;
(2) the **outcome vocabulary with base rates** — 17.9% never trade after create, 71.4% trade then go
quiet inside a day, 0.56% graduate, and 83.4% end with the curve fully unwound — which is the
denominator every later claim needs; (3) the **measurement that minute candles hide the median
coin's 17% drawdown**, which says that whatever instrument gets built for watching a coin after a
callout must be event-resolution, not bar-resolution.

---

## 6. What this does not say

- Nothing here is about **pool-priced coins**. The identity that makes candles redundant is a
  property of the bonding curve. Post-migration, a fill price is an observed ratio of two integer
  balance changes at the pool's own vaults and the argument has to be rebuilt.
- Nothing here is about **Ember's coins**. The cohort is every born mint; her viewport selects a
  tiny endogenous subset and the base rates in a callout-selected sample will differ, probably a
  lot.
- "**Still transacting at 24 h**" is not censoring — those mints' tapes continued and they were
  active. "**Dead**" always means an observed silence past a threshold justified by a measured
  resurrection hazard, never a tape that ran out.
- The **7-day panel is 9,165 mints from one 11.7-hour birth stretch**. Treat the first-week column
  as a hint and re-run it against a corpus with a longer clean window.
- Every SOL figure marked MODEL is the constant-product integral, and every price is the validated
  readout. They are never coalesced with an observed amount and must not be downstream of a join
  that drops the `price_kind`.
