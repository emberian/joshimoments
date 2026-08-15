# RESULT: crime signatures — can you see a manufactured price path from inside it?

*Study code: `studies/crime_signatures.py`. Production detector: `shitcoims_scalper/crime_detect.py`
(+ `tests/test_crime_detect.py`). Artifacts: `state/crime/`. Run 2026-08-15.*

The operator's description, verbatim, is the specification:

> "'criming' a token... one thing i've seen is a token that shoots to millions mcap, crawls
> ~linearly up to 20M with small amount of real trading activity (extremely small) and then
> the rug rips."

The deliverable asked for is an **exit signal first**, an avoid-filter second, and a taxonomy
of manipulators third — explicitly *not* an entry strategy for riding manufactured pumps.

---

## 0. Headline

**The verdict, in the operator's own terms: the pattern is real, it is detectable only
post-hoc, and it is not actionable as an exit signal. It is worth keeping as an avoid-filter
and as a taxonomy. Do not wire it to a sell.**

The composite crime score — displacement-per-flow, linearity, drift/vol, flow regularity,
burstiness, each as a percentile of 165,763 ambient coin-hours — **does not beat its own
rotation or mint-swap null in any of the 12 pre-registered cells, at any of 4 window lengths,
or in any of 18 post-hoc cells.** Precision at every operating threshold, in every cell, is
**exactly zero**: not one alert was followed by an irreversible collapse inside any horizon.
Against the cliff label it is not merely uninformative but **inverted** — AUC 0.259–0.489, five
of six cells below 0.5. A coin in the last 24 hours before a rug looks *less* like a
manufactured climb than the average coin-hour does.

Six things were established, and they are worth more than the failed detector:

1. **The detector is structurally blind where the money is.** 16 of 23 mechanical cliffs happen
   in the pool's **first 0–45 hours** — inside the feature window — including every one of the
   largest (LEGENDS $1.44B, Jimothy $50M, MOONDOGECOIN $25M, TJR $23M). No scorable cliff peaked
   above $4.8M. A 6-hour window recovers 19 of 23, and still beats no null (§5.3).
2. **The operator's pattern is a *minority* of rugs.** One of seven scorable cliffs is a metered
   climb. Five are ordinary deaths on unremarkable statistics.
3. **The more dangerous archetype is GHOST_TOWN, and it *is* visible in advance.** `$TOPG`:
   −98.3% in a single hour from $3.0M, with starvation at the 92nd percentile and leverage at
   the 91st. Nobody was trading it; the quoted market cap was a fossil. `ΔV = ΔQ/C` with `C → 0`.
   There is no exit at the quoted price at all — and unlike metering, it reads off
   `dead_hour_frac` and `turnover` alone (§7.1).
4. **A rug is a frenzy, not a lone wallet.** One day of chain identity across 258 pools ($2.84):
   coins rugging that day carried **2,256–3,197 distinct signers** against a control median of
   207, with *lower* sell-side concentration and *burstier* arrivals. Whatever is coordinated
   happens during accumulation, not at the rip (§7.2).
5. **The sentinel's rug thresholds sit at the wrong end of the irreversibility curve.** A 20%
   quote collapse is irreversible **0.7%** of the time in this cohort — 140 recoverable dips per
   real rug. An 80% fall, 51.6% (§4.1).
6. **The one result that looked shippable was an artifact, and the control that killed it is the
   most reusable thing here.** `rv_hourly` scored **AUC 0.926** against "down 50% in 72 h",
   surviving BY-FDR over 22 tests. Standardising the threshold by each coin's own volatility
   collapses it to **0.334–0.418**, below chance. The entire signal was "this coin moves a lot"
   (§5.5).

**The four held coins are clean.** weave, nosis, DREGG and SOLVE all read 0.26–0.48 today
against a cohort median of 0.30. Their swap tapes are burstier than a Poisson process
(inter-arrival CV 1.5–2.9, reference 1.0) and they sit mid-distribution on every concentration
statistic in a same-day cross-section of 122 other coins. **One finding is reported rather than
suppressed: DREGG crossed 0.80 for twelve hours on 2026-07-16, peaking at 0.896 — above the
cohort's 99th percentile.** It did not rug. That false positive is diagnostic, and it is the
strongest single argument in this document against automating the score: a straight-line path
on thin flow is also what a small honest community looks like, and this desk *is* one (§6.1).

---

## 1. Why the pattern is measurable at all, and what that buys

This is the one place the project's circuit frame does real work rather than decorating a
result, so it is worth stating exactly.

A CFMM pool is a nonlinear capacitor: reserves are charge, marginal price is voltage, and
`C = w_x·w_y·TVL` — `TVL/4` at 50/50 — verified to six significant figures in
`studies/RESULT_circuit_model.md`. The consequence is a conservation law, not a heuristic:

> **A CFMM price cannot move without flow through the curve.** `ΔV = ΔQ / C`.

So "price up on extremely small real trading activity" is not a description of sentiment. It
is a statement that one of three things is true, and all three are adversarial:

1. the same actor is on both sides, so the flow is real at the curve and fictional as
   inventory;
2. supply is being **metered** by a controller who is the only seller, so a trickle of buys
   walks the price up a curve nobody is defending;
3. `C` is tiny — the pool is thin — so the displacement is real and worthless, which is
   itself the setup for (1) and (2).

The measurable that follows is **displacement per unit flow**, `|Δ ln p| / turnover`, and —
this is the part the identity gives you for free — its *stability*. A controller with a
schedule produces a schedule. Organic price discovery does not.

That is the whole reason a detector can work on price and volume alone, which matters because
price and volume are the only two quantities with keyless history
(`RESULT_deterioration.md` §2.1).

---

## 2. The cohort, and the survivorship problem that defines it

### 2.1 Why a GeckoTerminal cohort alone is the wrong sample

GT's pool *listings* are ordered by current volume. A coin that rugged three weeks ago has no
current volume, so it is not in any listing, so it is not in any cohort built from listings. A
rug study built that way is a study of coins that did not rug. `RESULT_deterioration.md` §4.1
flagged exactly this and reported its death rates as lower bounds; here it would be fatal
rather than conservative.

The fix is a **second enumerator that does not condition on being alive**. The pump.fun boards
tape (`state/boards/`, 87,202 rows over two days) is one: the market-cap and last-reply boards
carry coins that are already dead, with their all-time-high market cap attached. Screening it
gives **10,571 distinct mints, 621 of which ever touched $1M**.

The cohort is therefore the union of two enumerators with opposite biases:

| arm | screen | mints |
|---|---|---:|
| boards, collapsed (now < 20% of ATH) | ATH ≥ $1M | 339 |
| boards, standing | ATH ≥ $1M | 199 |
| boards + discovery, collapsed | | 43 |
| boards + discovery, standing | | 23 |
| GT discovery, standing | FDV ≤ $250M, or history already cached | 177 |
| **total** | | **781** |

780 of 781 resolved through GT's `tokens/multi` endpoint (30 mints per call, so the pool
lookup for the whole cohort cost 27 calls); **538 are confirmed pump.fun graduations**.

**One trap inside the fix, caught and corrected.** The discovery arm's first screen was
`fdv ≥ $1M` on the *current* snapshot. That is the same survivorship error in a new place: a
coin that reached $1.4B and fell 99.9% now reads as a $1M coin and gets excluded precisely
because it collapsed. The gate is now an upper bound only, and any discovery mint with a
cached history is admitted regardless — membership is decided by **peak** market cap computed
from the series, which is a sample definition rather than a signal and cannot leak into the
score.

**pump.fun's `ath_market_cap` is used as a screen and never as a measurement.** It returns
values up to 1e26 for pre-migration coins — a units bug on their side. The *ratio*
`now / ath` survives it because numerator and denominator share the bug, and every number
reported in this document is computed from OHLCV plus on-chain supply.

### 2.2 The censoring, counted rather than mentioned

This is the finding, not the caveat, so it is stated before the performance table rather than
after it.

The frozen cohort is **294 series considered → 182 in the band** (96 below it) with **23
mechanical cliffs**. Of those cliffs, **16 happen before the detector has a window at all** —
their rip index is 0–45 hours into the pool's own history, and a 48-hour feature window cannot
score an hour that does not have 48 hours behind it.

These are not vendor artifacts. Every one of the sixteen returned **fewer than 1000 candles**,
GT's cap, so the series genuinely begins at the pool's first indexed trade and the cliff
genuinely falls in the pool's first two days:

| symbol | peak mcap | candles | rip at hour |
|---|---:|---:|---:|
| LEGENDS | $1,439,570,981 | 167 | 11 |
| Jimothy | $50,449,452 | 25 | 2 |
| MOONDOGECOIN | $24,869,086 | 377 | 23 |
| TJR | $22,663,147 | 924 | 23 |
| LUKE | $12,299,238 | 579 | 6 |
| BOP | $4,308,442 | 568 | 32 |
| MASON | $3,817,800 | 507 | 13 |
| TikTok | $2,877,350 | 267 | 10 |
| TrumpCoin | $2,851,634 | 768 | 6 |
| OnlyMarms | $2,519,763 | 455 | 0 |
| Bark | $2,392,857 | 141 | 5 |
| toadtard | $2,247,586 | 118 | 6 |
| TRUMP2028 | $2,120,100 | 508 | 9 |
| GENTLE | $1,947,751 | 132 | 45 |
| Fauci | $1,825,835 | 399 | 6 |
| FIW | $1,052,594 | 410 | 0 |

**Every one of the largest cliffs is in this table**, and none of the seven scorable ones peaked
above $4.8M. The detector is structurally blind in exactly the size band where the money is.

Since a pump.fun coin's PumpSwap pool is created at graduation, "hour 6 of the pool" means six
hours after graduation. **The modal cliff is fast, and the operator's described pattern — a
multi-day linear crawl to eight figures — is the minority case.** Every recall number in §5 is
conditional on "we could see the coin at all", and this table is the size of that condition.

It also converts a parameter into a question, which §5.3 answers: if most crimes are shorter
than the window, what does a shorter window buy?

---

## 3. The four signatures, and the honest status of each

### S1 — displacement decoupled from flow

`disp_per_turnover = |Δ ln p| / (volume / mcap)` over the window. The circuit-frame quantity:
ΔV per unit ΔQ, made dimensionless. Measurable on price and volume alone, so it is available
for the whole cohort. **Implemented and evaluated.**

### S2 — linearity

Three separate measurables, because "a schedule" shows up three ways and they distinguish
different bots:

* `r2_linear` / `r2_log` — R² of price against wall clock, in *level* and in *log*. The
  operator's sentence ("crawls ~linearly up to 20M") is a statement about level, and the two
  separate two strategies: a bot buying a **fixed dollar amount** per interval produces
  linearity in level, a bot buying a **fixed percentage** produces it in log.
* `cv_vol`, `fano_vol`, `top_hour_share` — dispersion of hourly volume. A scheduler collapses
  it; real attention is bursty. Low is suspicious, which is the opposite polarity to
  everything else and is handled explicitly in `SCORE_KEYS`.
* `interarrival_cv` — CV of inter-trade gaps at swap resolution, where a swap tape exists.
  **This one has an exact reference value and needs no fitting: a memoryless (Poisson)
  arrival process has CV = 1.** Below 1 the tape is more regular than chance.

**Implemented and evaluated.**

### S3 — concentration and choreography

Needs signers, which price feeds do not carry. Measured on the eleven cluster pools
(§6.2) and, at a cost of $2.84 for one day, on cohort coins straight from BigQuery (§7.2). It is
**deliberately not part of the score**: a feature measured on eleven pools that then decides
alerts on 781 coins would be a claim the data cannot support.

The asymmetry worth measuring is Marino §VIII's — accumulation is spread across many wallets,
distribution is concentrated in one — so the statistic is not "how many wallets" but the
**difference in wallet concentration between the buy side and the sell side**, which is
scale-free and needs no reference population.

### S4 — the terminal event

Labelled mechanically as an **irreversible** collapse (`find_rip`): a ≥60% fall inside 6
hours, from a level sustained for the previous 6 hours, that never recovers past 40% of the
pre-fall price for the next 24 hours. It reports the **last hour the price was still up** —
the last moment an exit was possible at the pre-rip price — and every lead time is measured
against that, which is the conservative choice.

This is a **cliff** label. It is deliberately narrower than
`studies/flow_signals.py`'s four-mode taxonomy (CLIFF / BLEED / SILENCE / DOUBLE) and
corresponds to its CLIFF; the coins that lost 90% slowly (Jotchua, CATE, Jimothy) are a
different exit problem and are covered by this study's second pre-registered label, `bleed`.

---

## 4. Where every threshold came from

Nothing here is asserted. `uv run python -m studies.crime_signatures distributions` prints the
audit trail; `state/crime/distributions.json` is the artifact.

### 4.1 The rip threshold, and what it says about `config.yaml`

Over **174,317 coin-hours** (182 coins in the band), the worst 6-hour fall reachable from each
hour:

| quantile | p0.1 | p1 | p5 | p25 | p50 |
|---|---:|---:|---:|---:|---:|
| fall | −0.574 | −0.299 | −0.156 | −0.045 | −0.014 |

And the discriminating table — of the falls at least this deep, what share **never came back**?

| drop | any-fall rate | irreversible rate | **irreversible share** | |
|---:|---:|---:|---:|---|
| 0.20 | 0.02916 | 0.00020 | **0.007** | ← `config.yaml` `quote_collapse_pct` |
| 0.30 | 0.00989 | 0.00020 | 0.020 | |
| 0.40 | 0.00388 | 0.00020 | **0.052** | ← `config.yaml` `liquidity_drop_pct` |
| 0.50 | 0.00178 | 0.00020 | 0.113 | |
| 0.60 | 0.00085 | 0.00020 | **0.236** | ← threshold used here |
| 0.70 | 0.00035 | 0.00012 | 0.344 | |
| 0.80 | 0.00018 | 0.00009 | 0.516 | |

The share rises monotonically with depth, which is what makes it a usable derivation rather
than a coincidence: **a 20% fall is irreversible 0.7% of the time; an 80% fall, 51.6%.**

**The sentinel's live thresholds sit at the wrong end of that curve.** A 20% quote collapse
carries a **140-to-1** ratio of recoverable dips to real rugs in this cohort. That is a
statement about *this* cohort — survived, ≥$1M coins, hourly bars — and the sentinel operates
on live quotes at a much finer resolution where a 20% move means something different. It is
not a claim that the config is wrong. It *is* a measured reason to ask where those numbers
came from and to expect the false-positive rate to be high, which is exactly the failure mode
already recorded against that component (the fabricated-cost-basis incident turned every stop
into a realised loss).

0.60 was chosen where the share crosses roughly one in four. A stricter label (0.80, one in
two) is purer and rarer; the sensitivity is one parameter in `find_rip` and the study
re-runs on it.

### 4.2 The feature calibration

Ambient quantiles over 165,763 coin-hours — these ARE the thresholds, in the sense that the
score is a percentile lookup against them:

| feature | p5 | p25 | p50 | p75 | p90 | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `disp_per_turnover` | 0.060 | 0.437 | 1.276 | 3.353 | 8.594 | 15.39 | 89.57 |
| `path_per_turnover` | 1.797 | 5.824 | 11.73 | 25.01 | 57.70 | 100.0 | 535.2 |
| `r2_linear` | 0.0042 | 0.121 | 0.394 | 0.656 | 0.798 | 0.849 | 0.915 |
| `r2_log` | 0.0043 | 0.122 | 0.398 | 0.662 | 0.803 | 0.854 | 0.917 |
| `drift_vol` | −1.512 | −0.740 | −0.172 | 0.344 | 0.829 | 1.119 | 1.701 |
| `cv_vol` | 0.609 | 0.971 | 1.323 | 1.875 | 2.692 | 3.437 | 5.306 |
| `top_hour_share` | 0.060 | 0.097 | 0.141 | 0.220 | 0.341 | 0.452 | 0.770 |
| `dead_hour_frac` | 0 | 0 | 0 | 0.042 | 0.313 | 0.542 | 0.958 |
| `turnover` (48 h) | 0.0021 | 0.0128 | 0.0549 | 0.171 | 0.633 | 1.243 | 3.944 |
| `rv_hourly` | 0.0042 | 0.0091 | 0.0205 | 0.0418 | 0.0736 | 0.108 | 0.204 |

Three of these are worth reading as facts about the market rather than as calibration, and
each one weakens a naive version of the operator's rule:

* **the median coin-hour has `r2_linear` = 0.39.** Straightness is not rare. Half of all
  coin-hours in this band are as straight as a coin-flip's worth of trend. A detector built on
  linearity alone fires constantly, which is why it is one of five components and not the rule.
* **the median 48-hour turnover is 5.5% of market cap** and the 5th percentile is **0.21%**.
  "Extremely small real trading activity" is the *normal* state of a coin in this band, not
  the exception, so the volume half of the description is not by itself diagnostic either.
* **`dead_hour_frac` is 0 at the median and 0.31 at p90.** Most coins in the band trade every
  hour; the ones that do not are a distinct quarter of the distribution rather than a tail.

The pattern the operator described is real — but each of its two halves, taken alone, describes
the *median* coin in this market. Only the conjunction is rare, which is what a composite score
is for and also why it can be expected to be brittle.

### 4.3 The score's own distribution

| quantile | p50 | p75 | p90 | p95 | p99 |
|---|---:|---:|---:|---:|---:|
| `crime_score` | 0.297 | 0.492 | 0.640 | 0.718 | 0.837 |

So the operating thresholds are, by construction, percentile gates: **0.70 fires on 5.96% of
coin-hours, 0.80 on 1.86%, 0.90 on 0.26%.** For an operator watching twenty coins that is
roughly one 0.80-alert per coin-day — the right order of magnitude for something a human
reads, which is the only reason those three levels were chosen.

---

## 5. Performance: what the detector actually does

### 5.0 Trials counted, declared before the run

| family | levels | cells |
|---|---|---:|
| composite score | 2 splits × 2 labels × 3 horizons | 12 |
| univariate features | 11 features × 2 labels, horizon 24 h | 22 |
| operating thresholds | 0.70 / 0.80 / 0.90 | 3 |
| window sweep | 6 / 12 / 24 / 48 h | 4 |
| **pre-registered total** | | **41** |
| post-hoc (`breakdown`, §5.4) | 2 features × 2 labels × 3 horizons, labelled as post-hoc | 18 |

The score's five components and their equal weights were fixed from the operator's sentence
**before any performance number existed** and are not fitted. That is deliberate: a fitted
weight vector over eleven features and seven cliffs is the overfit
`RESULT_bandit_search.md` already paid for once (a +21.77% board-entry edge that became
+0.0012 when the survivorship came out). An unweighted mean of five ranks cannot overfit — it
can only be right or wrong, and here it is wrong.

### 5.1 The cliff label: a complete null, and an *inverted* one

Cohort 182 coins, 7 scorable cliffs, 80,648 scored coin-hours.

| split | horizon | positives | base rate | AUC | CI95 | rotation p95 | mint-swap p95 | beats every null |
|---|---:|---:|---:|---:|---|---:|---:|---|
| grouped | 6 h | 24 | 0.0003 | 0.489 | [0.205, 0.744] | 0.631 | 0.715 | **no** |
| grouped | 24 h | 78 | 0.0010 | **0.399** | [0.262, 0.541] | 0.562 | 0.665 | **no** |
| grouped | 72 h | 201 | 0.0025 | **0.397** | [0.263, 0.558] | 0.512 | 0.615 | **no** |
| temporal | 6 h | 7 | 0.0002 | **0.323** | [0.040, 0.540] | 0.529 | 0.791 | **no** |
| temporal | 24 h | 25 | 0.0006 | **0.316** | [0.190, 0.457] | 0.439 | 0.794 | **no** |
| temporal | 72 h | 50 | 0.0012 | **0.259** | [0.141, 0.521] | 0.259 | 0.722 | **no** |

**Not one cell beats its null ceiling, and five of six sit below 0.5.** The score is not
uninformative about imminent cliffs — it is *anti*-informative. A coin in the 24 hours before
an irreversible collapse looks, on these five features, *less* like a manufactured climb than
the ambient coin-hour does.

The mechanism is visible in the per-coin traces (`state/crime/` and the trace command in the
module): on SUNUSI, the one METERED_CLIMB in the cohort, `r2_linear` ran **0.90–0.92 at 24–36
hours before the cliff and had collapsed to 0.03 six hours before it**. The crawl does not rip
*while* it is linear. It stops being linear, and then it rips — so a detector that scores the
current window is looking at the wrong window by the time it matters.

No univariate feature survives BY-FDR (q = 0.10, c_m = 3.691, 22 tests) for the cliff label.
The best raw AUCs — `rv_hourly` 0.751 (p = 0.016, q = 0.179) and `turnover` 0.693 — do not
clear the correction.

### 5.2 Lead time, the money metric

This is the number the exit-signal question turns on, so it is reported even though the
detector fails upstream of it.

| threshold | alert rate | precision | coins warned | median lead | p10 lead |
|---|---:|---:|---:|---:|---:|
| 0.70 | 6.01% | **0.0000** | 2 / 7 | 322 h (13.4 d) | 122 h |
| 0.80 | 1.87% | **0.0000** | 0 / 7 | – | – |
| 0.90 | 0.27% | **0.0000** | 0 / 7 | – | – |

**Precision is exactly zero at every operating point in every cell.** Not one alert was
followed by a cliff inside any horizon.

The "2 of 7 warned at 0.70 with a median lead of 322 hours" line has to be read against its own
null, and the arithmetic is damning rather than encouraging: at a 6% alert rate, a coin with
several hundred scorable hours alerts *somewhere* with probability indistinguishable from 1.
Chance predicts 7 of 7. **Two of seven is fewer warnings than a coin-flip would give**, which
is the same inversion the AUC reports, and a 13-day "lead" is not an exit signal — it is the
ambient state of a coin that has been alive for a while.

### 5.3 The window sweep: shortening the window does not rescue it

The censoring in §2.2 forced this question — if most cliffs happen inside a 48-hour warm-up,
what does a shorter window buy? It buys coverage and nothing else. `stride 1`, grouped CV,
cliff label, 24-hour horizon:

| window | coins | scorable cliffs | left-truncated | AUC | null ceiling | recall @ 0.80 | median lead | p10 lead | alert rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 6 h | 194 | **19** | **4** | 0.525 | 0.575 | 0.26 (5/19) | 156 h | 5 h | 2.31% |
| 12 h | 187 | 12 | 11 | 0.572 | 0.607 | 0.25 | 135 h | 11 h | 2.09% |
| 24 h | 184 | 9 | 14 | 0.576 | 0.646 | 0.00 | – | – | 1.88% |
| 48 h | 182 | 7 | 16 | 0.396 | 0.662 | 0.00 | – | – | 1.88% |

A 6-hour window recovers almost all the coverage — **19 of 23 cliffs become scorable instead
of 7** — and the AUC does climb out of the inversion. But **no window beats its own null
ceiling**, and the gap does not close: the best cell is 0.576 against a ceiling of 0.646.
Shorter windows also raise the null ceiling, because a short window is noisier and a rotated
copy of a noisy series matches the real one more often.

The one usable number in the table is the **p10 lead of 5 hours at a 6-hour window**: even in
the tenth-percentile case the warnings that *do* land are hours ahead, not minutes. If the
discrimination existed, the timing would be actionable. It does not, so it is not.

### 5.4 The post-hoc arm, and why it is reported as a failure rather than omitted

Reading the traces after the pre-registered grid had already failed suggested a second
difference rather than a level: *was this a schedule, and has the schedule just stopped?*
`r2_breakdown = r2_linear(t − 24h) × max(0, r2_linear(t − 24h) − r2_linear(t))`, causal on both
halves, multiplicative so both conditions must hold.

18 cells (2 features × 2 labels × 3 horizons), same nulls: **0 of 18 beat the null ceiling.**
Best cell AUC 0.588 (rip, 6 h) against a ceiling of 0.715. It is recorded here because the
alternative — trying it, finding nothing, and not mentioning it — is how a trials count becomes
a lie.

### 5.5 The `bleed` label looked like the one thing that worked. It is an artifact.

The second pre-registered label (forward return ≤ −50%) produced the only cells that beat their
nulls — composite AUC 0.627 (grouped, 6 h) and 0.655 (temporal, 6 h) — and univariate AUCs that
look like a finished product:

| feature (bleed, 24 h) | AUC | p | q (BY) | |
|---|---:|---:|---:|---|
| `rv_hourly` | **0.926** | 8.8e-73 | 7.2e-71 | REJECT-NULL |
| `turnover` | **0.900** | 3.9e-32 | 1.6e-30 | REJECT-NULL |
| `fano_vol` | 0.826 | 2.1e-30 | 5.8e-29 | REJECT-NULL |
| `path_per_turnover` | 0.194 | 3.5e-15 | 7.2e-14 | REJECT-NULL (inverted) |
| `disp_per_turnover` | 0.328 | 2.6e-07 | 4.3e-06 | REJECT-NULL (inverted) |
| `dead_hour_frac` | 0.400 | 0.0034 | 0.046 | REJECT-NULL (inverted) |

An AUC of 0.926 surviving BY-FDR over 22 tests is the kind of number that gets shipped. **It is
a volatility-scaling artifact and it does not survive the obvious control.** A high-`rv` coin is
mechanically more likely to move 50% *in either direction*, and the label only counts one of
them. Standardising the threshold by the coin's own volatility — forward log return
≤ −k · `rv_hourly` · √72, which asks the directional question instead of the magnitude one:

`uv run python -m studies.crime_signatures vol-control` (artifact:
`state/crime/vol_control.json`):

| label | positives | base rate | `rv_hourly` | `turnover` | `fano_vol` | `disp_per_turnover` |
|---|---:|---:|---:|---:|---:|---:|
| fixed −50% | 1,481 | 0.0194 | **0.893** | 0.881 | 0.756 | 0.304 |
| standardised k = 1.0 σ | 9,864 | 0.1299 | **0.418** | 0.436 | 0.434 | 0.545 |
| standardised k = 1.5 σ | 4,224 | 0.0556 | **0.374** | 0.408 | 0.398 | 0.565 |
| standardised k = 2.0 σ | 1,998 | 0.0263 | **0.334** | 0.382 | 0.374 | 0.578 |

**0.893 → 0.334.** The entire signal was "this coin moves a lot", and once that is divided out
the sign flips: conditional on its own volatility, a high-`rv` coin is *less* likely than
average to make a large downward excursion. Nothing about direction was ever measured.

One small thing survives the control and moves the other way. **`disp_per_turnover` — signature
S1, the circuit-frame quantity — goes from 0.304 to 0.578** as the threshold is standardised,
i.e. it was *hurt* by the volatility confound rather than helped by it. 0.578 is not a result
(it clears no null in the pre-registered grid), but it is the only feature in the study whose
standing improves under the control, and it is the one with a mechanism behind it rather than
a correlation. That is where a follow-up should start.

This section is the most reusable thing in the document. **Any future result on this panel that
predicts a fixed-percentage drawdown must be re-run through `vol-control` before it is
believed**, because the table above is the difference between a null and a shipped detector
with an AUC of 0.93 on its front page.

---

## 6. The operator's four coins

### 6.1 Scores — the acid test

Scored on exactly the same code path as every cohort coin, against a calibration fitted on the
cohort and never on them. `uv run python -m studies.crime_signatures held`.

Calibration: 268,870 cohort coin-hours over 274 coins. None of the four is in the calibration.

| coin | history | latest score | peak score | when | hours ≥ 0.80 | hours ≥ 0.70 | mechanical cliff |
|---|---:|---:|---:|---|---:|---:|---|
| weave | 248 h | 0.314 | 0.688 | 2026-08-12 10:00 | 0 / 200 | 0 / 200 | no |
| nosis | 119 h | 0.288 | 0.696 | 2026-08-12 06:00 | 0 / 71 | 0 / 71 | no |
| **DREGG** | 1002 h | 0.265 | **0.896** | 2026-07-16 06:00 | **12 / 954** | 44 / 954 | no |
| SOLVE | 582 h | 0.482 | 0.802 | 2026-07-26 03:00 | 1 / 534 | 31 / 534 | no |

**Today, all four are quiet.** Latest scores 0.26–0.48 against a cohort median of 0.30 and a
0.80 alert gate. Nothing in the current state of any of them reads as a manufactured path.

**The finding that has to be reported prominently rather than buried: DREGG crossed 0.80 for
twelve hours on 2026-07-16, peaking at 0.895 — above the 99th percentile of the whole cohort
(0.835).** The state that produced it: `r2_linear` 0.83–0.85, 48-hour turnover **22.5%** of
market cap against a cohort median of 1.9%, at a market cap around $700k and *falling*.

Read honestly, that is a **false positive, and a diagnostic one**. DREGG did not rip; it is
still trading eleven weeks later. What the detector saw was a near-straight-line price path on
low-but-not-tiny volume — which is also what a small community coin looks like when a handful
of participants trade it on a rhythm. The operator drives volume through his own resistors by
design (PROGRAM.md §8, the DREGG community-activity null: activity → ~1.86× volume with no
durable price effect), and **a detector that keys on "linear path, thin flow" cannot
distinguish a manufactured climb from a small honest community**. That is not a tuning
problem. It is the mechanism's blind spot, and it is the single strongest argument in this
document for never wiring the score to an automatic exit.

SOLVE touched 0.802 exactly once (2026-07-26) at a $46k market cap with 74.8% 48-hour
turnover — below the operator's band and not the pattern.

The four coins' *swap-level* behaviour (§6.2, §7.2) agrees: they sit mid-distribution on every
concentration statistic in a same-day cross-section of 122 other coins, and their tapes are
burstier than a Poisson process rather than more regular.

### 6.2 S3 at swap resolution — the eleven pools that have signers

`state/cluster_tape/` carries 7,412 swaps with signers across eleven pools. This is the only
place in the project where the choreography signature can be measured directly, and the answer
for the operator's own coins is clean.

| pool | swaps | signers | HHI buy | HHI sell | asym | top seller | wash share | inter-arrival CV |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| nosis/SOL | 3,236 | 732 | 0.072 | 0.048 | −0.024 | 0.191 | 0.300 | **2.31** |
| SOLVE/SOL | 1,348 | 302 | 0.016 | 0.022 | +0.006 | 0.057 | 0.344 | **2.90** |
| weave/SOL | 1,323 | 352 | 0.047 | 0.025 | −0.022 | 0.082 | 0.213 | **1.49** |
| DREGG/SOL | 961 | 217 | 0.126 | 0.090 | −0.036 | 0.225 | 0.147 | **1.80** |
| weave/nosis | 173 | 40 | 0.143 | 0.099 | −0.044 | 0.193 | 0.000 | 2.97 |
| weave/DREGG (5%) | 130 | 47 | 0.145 | 0.179 | +0.034 | 0.380 | 0.378 | – |
| weave/SOLVE | 83 | 31 | 0.203 | 0.158 | −0.045 | 0.354 | 0.392 | – |
| DREGG/nosis | 74 | 39 | 0.111 | 0.213 | +0.102 | 0.437 | 0.000 | – |

Read against the mechanism rather than against a threshold:

* **Inter-arrival CV is 1.5–2.9 on all four SOL pools, against a Poisson reference of exactly
  1.0.** The tape is *burstier* than chance, which is what real attention looks like. A
  scheduler would sit below 1. **None of the operator's coins is being clocked.**
* **The dump asymmetry is absent or inverted.** Marino §VIII's signature is accumulation
  spread across wallets and distribution concentrated in one, i.e. `HHI(sell) − HHI(buy) > 0`.
  On the four SOL pools it is **−0.036 to +0.006** — no concentrated seller. The two pools
  where it is positive (DREGG/nosis +0.102, nosis/weave +0.096) have 65–74 swaps, and at that
  count one ordinary LP rebalance sets the number.
* **Buy-side concentration is low**: the largest buyer holds 1.6–12.6% of squared buy share.
  With 217–732 distinct signers per pool these are crowds, not choreography.
* **Wash share (0.15–0.39) is the one statistic that looks high, and it should not be read as
  wash trading.** It counts volume from wallets whose net position barely moved relative to
  their gross — which is the definition of a scalper doing round trips, and this desk *runs* a
  scalper. Without funding-tree ancestry the statistic cannot separate "one actor on both
  sides" from "many actors round-tripping", and it is reported rather than interpreted.

A cross-check worth recording: buy/sell side was derived from the **sign of the quote vault's
`delta_raw`**, which is exact and defined on token-token pools where the tape's own `side`
field is absent. It agreed with the tape's `side` on **6,855 of 6,855** rows where both exist —
zero disagreements.

---

## 7. The manipulator taxonomy

### 7.1 Archetypes from price alone

With this many cliffs this is a **description, not a clustering**, and it is written that way
on purpose: k-means over seven coins would produce clusters and they would mean nothing. The
axes come from the mechanism rather than from the data, and each coin's pre-rip profile is
reported as percentiles of the ambient distribution so the operator can recognise the shape
instead of trusting a label.

* **metering** — is the ascent a schedule? (`r2_linear` high, `cv_vol` low)
* **starvation** — is anybody there? (`dead_hour_frac` high, `turnover` low)
* **leverage** — how far does a dollar move it? (`disp_per_turnover` high)

| coin | peak mcap | mcap at rip | fall | hrs | metering | starvation | leverage | peak score | strategy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Himgajria | $4,793,403 | $3,822,007 | −0.694 | 6 | 0.45 | 0.64 | 0.53 | 0.443 | ORDINARY_DEATH |
| DEXBULL | $4,492,805 | $2,191,951 | −0.636 | 5 | 0.30 | 0.33 | 0.17 | 0.393 | ORDINARY_DEATH |
| LOUIE | $3,130,214 | $541,352 | −0.659 | 6 | 0.41 | 0.33 | 0.05 | 0.567 | ORDINARY_DEATH |
| **$TOPG** | $2,997,467 | $2,744,356 | **−0.983** | **1** | 0.18 | **0.92** | **0.91** | 0.636 | **GHOST_TOWN** |
| **SUNUSI** | $2,404,830 | $740,109 | −0.917 | 2 | **0.76** | 0.36 | 0.28 | 0.656 | **METERED_CLIMB** |
| WORLDCUP | $2,227,046 | $379,161 | −0.803 | 4 | 0.62 | 0.38 | 0.22 | 0.725 | ORDINARY_DEATH |
| LOL | $1,496,052 | $983,113 | −0.657 | 1 | 0.34 | 0.57 | 0.44 | 0.718 | ORDINARY_DEATH |
| *16 more* | up to $1.44B | – | – | – | – | – | – | – | LEFT_TRUNCATED |

**Counts: 1 METERED_CLIMB, 1 GHOST_TOWN, 5 ORDINARY_DEATH, 16 LEFT_TRUNCATED.**

Three things this says, in descending order of confidence:

1. **The operator's pattern exists and it is rare.** Exactly one of seven scorable cliffs is a
   metered climb. That does not mean he is wrong — he described something he has *seen*, and
   SUNUSI is it, complete with `r2_linear` at 0.90–0.92 a day before the cliff. It means the
   pattern is a minority of rugs, so a detector tuned to it will have low recall against rugs
   in general even if it has high precision against *that* rug.
2. **`$TOPG` is the cleanest single example of a different crime**, and it is the one worth
   naming: **−98.3% in a single hour** from $3.0M, with starvation at the 92nd percentile and
   leverage at the 91st. Nobody was trading it. The quoted market cap was a fossil — a price
   nobody had tested — and the "rug" is just the first real seller discovering that the
   capacitance was gone. In the circuit frame this is the purest possible statement of
   `ΔV = ΔQ/C` with `C → 0`. **For an operator, GHOST_TOWN is the more dangerous archetype
   than METERED_CLIMB, because there is no exit at the quoted price at all** — and, unlike
   metering, it is visible in advance from `dead_hour_frac` and `turnover` alone.
3. **Most cliffs are not distinctive.** Five of seven are ORDINARY_DEATH: the coin simply
   lost, on unremarkable statistics. There is no manipulator to detect because there may not
   have been one.

**And the honest fourth: the modal cliff is not in this table at all.** Sixteen of twenty-three
happen inside the detector's warm-up, including every one of the largest (LEGENDS at $1.44B,
Jimothy at $50M, MOONDOGECOIN at $25M, TJR at $23M). Whatever taxonomy governs *those* is not
measured here, and §5.3 is the attempt to reach them.

### 7.2 S3 on the cohort — one day of chain identity, $2.84

The cluster tape gives signers for eleven pools that all belong to one community. To ask
whether a *ripping* coin looks different from an ordinary one, the signers have to come from
somewhere wider, and BigQuery has them.

**The cost structure is the finding that makes this cheap, and it is counter-intuitive:
adding pools to the scan is free.** The same query over 4 pools and over 46 pools both
dry-run at 415.8 GB, because the bytes are set by the columns read, not by the `EXISTS`
filter. So the control arm costs $0.00 and there is never a reason to pull a treatment arm
without one.

Pulled: **2026-08-11**, 258 pools (29 that ever cliffed, 221 controls, the cluster), all
successful transactions touching a WSOL vault owned by one of them, **aggregated in BigQuery**
to one row per `(pool, signer)` plus per-pool inter-arrival moments — 93,015 rows, 499.4 GB,
**$2.84**.

Three arms, because a coin that cliffed three weeks ago is a corpse on this day rather than a
crime in progress, and pooling those would blunt the contrast the day was bought for:

| arm | n | swaps (med) | signers (med) | HHI buy | HHI sell | asym | top seller | wash | inter-arr CV |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **ripping** (same-day cliff) | 3 | 14,449 | 2,256 | 0.050 | 0.052 | −0.010 | 0.223 | 0.317 | 2.51 |
| control | 122 | – | 207 | 0.065 | 0.069 | +0.000 | 0.172 | 0.271 | 1.88 |

Permutation p (exact where the combinatorics allow), then BY-FDR at q = 0.10 over the nine
statistics: `swaps_per_signer` p = 0.035, `distinct_signers` p = 0.022, everything else
p > 0.10 — and **nothing survives the multiplicity correction** (c_m = 2.829, 0 of 9).

But the *direction* is the result, and it is the opposite of the hypothesis:

> **On the day a coin rips, it is not thinly traded by one actor. It is a frenzy.**
> GENTLE: 30,232 swaps across **3,197 distinct signers**. LOUIE: 14,449 swaps across 2,256.
> The median control coin that day had 207 signers.
> Sell-side concentration on the ripping coins (HHI 0.052, top seller 22%) is *lower* than the
> control median, and the inter-arrival CV is *higher* (2.51 vs 1.88) — burstier, not
> scheduled.

That does not refute manipulation. It relocates it: whatever is coordinated happens **before**
the day of the rip, and the rip itself is mass participation — thousands of wallets buying
while somebody distributes into them. It also explains why a concentration statistic measured
*at* the rip finds nothing, and it is a direct argument that the choreography signature has to
be measured on the *accumulation window*, which is exactly what one day of chain data cannot
see and what the cluster tape's forward recording can.

**Why this was not extended.** Rips in this cohort are spread across 15 distinct days with at
most two per day, so a treatment-and-control comparison with real power needs most of those
days, at ~$2.8 each. That is the wrong side of the budget, and it is a genuine finding about
method: **at this rip dispersion, retrospective wide BigQuery pulls do not pay, and
pre-registering pools and recording forward (the cluster tape's model) does.** Total BigQuery
spend attributable to this study: **854 GB, $4.86** across the two failed designs and the
count query, plus **$2.84** for the day that worked — **$7.70**, under the ~$10 cap.

---

## 8. Output contract — `state/crime/alerts.jsonl`

Defined here for the sentinel's advisory layer and the paperdesk to consume. **Neither was
edited by this study**; the contract is published and they adopt it when they choose to.
Emitters live in `shitcoims_scalper/crime_detect.py` (`alert_row`, `defect_row`,
`heartbeat_row`, `append_rows`) so the consumer and the study share one implementation.

`kind` is a **closed set** — a consumer may switch on it exhaustively:
`crime_alert`, `crime_clear`, `defect`, `watch_open`, `watch_close`, `heartbeat`.

```json
{
  "schema": "crime.alert.v1",
  "kind": "crime_alert",
  "run_id": "crime-1786774000-88152",
  "alert_id": "ca-3f9a1c...",
  "t_ingest": 1786774001.42,
  "t_event": 1786770000,
  "t_event_source": "vendor:geckoterminal.ohlcv.hour",
  "mint": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
  "symbol": "DREGG",
  "pool": "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU",
  "crime_score": 0.84,
  "severity": "high",
  "p_rip_h24": null,
  "action": "reduce",
  "arm": "held",
  "mcap_usd": 331472.0,
  "thresholds": {"crime_score": 0.80, "window_hours": 48, "rip_drop": 0.6,
                 "rip_window_h": 6, "rip_hold_h": 24, "rip_recover": 0.4},
  "components": {"disp_per_turnover": 0.91, "r2_linear": 0.88, "drift_vol": 0.79,
                 "cv_vol": 0.83, "top_hour_share": 0.80},
  "evidence": {"disp_per_turnover": 12.4, "r2_linear": 0.86, "drift_vol": 1.31,
               "cv_vol": 0.61, "top_hour_share": 0.09, "turnover": 0.0042,
               "dead_hour_frac": 0.15, "rv_hourly": 0.011, "disp_log": 0.42,
               "vol_usd": 1391.0},
  "calibration": {"n_states": 84461, "t_first": 1783200000, "t_last": 1786770000,
                  "keys": ["disp_per_turnover", "r2_linear", "drift_vol", "cv_vol",
                           "top_hour_share"]}
}
```

Contract rules, each one earned somewhere in this repo:

* **Two clocks, and `t_event_source` is mandatory.** `t_event` is the vendor's candle hour;
  `t_ingest` is ours. A row with no vendor clock says so explicitly
  (`"absent:local_row_has_no_source_clock"`) instead of carrying a null with no reason.
  Consumers join on `t_event` only — backfill paginates newest-first and ingest order ran
  *backwards* against chain order at Spearman −0.77 on real data
  (`shitcoims_netmap/tapefeed.py`).
* **`action` is always `"reduce"`.** There is no buy side to this contract. A consumer that
  finds itself inverting the score is outside the contract.
* **`severity` is a band, never a probability.** `p_rip_h24` is the calibrated hazard and is
  `null` until an evaluation that produced one is on disk. **A consumer finding it null must
  not substitute a guess** — as of this run it is null, because §5 does not support one.
* **Every threshold that produced the row travels with the row** (PROGRAM.md §3.7), so a
  stored alert is interpretable after the defaults change.
* **`components` and `evidence` are both present**: percentile ranks *and* raw values, so a
  human who knows the coin can overrule the score without re-deriving it.
* **`alert_id` is stable** across runs for the same `(mint, t_event, threshold)` and changes
  when the threshold does — so re-emitting is idempotent and a threshold change is visible
  rather than silent.
* **`defect` instead of imputation.** No cached OHLCV, a history shorter than the window, a
  supply we could not read: all emit a `defect` row naming the reason. Nothing is filled in.
* **`heartbeat` is positive evidence of liveness.** Absence of alerts means nothing without
  one; the resolution table is `shitcoims_scalper/firehose.py`'s.
* **JSONL, `sort_keys=True`, never CSV.** Memecoin symbols contain commas, quotes and
  newlines by design (PROGRAM.md §3.11); a test asserts a symbol of `we,ird"\nname` survives
  the round trip.

---

## 9. Method notes: six traps, paid for

Recorded because each one produced a wrong number first and would have been invisible in the
output.

**1. The rip label fired five hours early.** The naive scan reports the *earliest* hour from
which a 60% fall is reachable within the window, which on a flat-then-cliff path sits up to
`window_h` hours before anything happened — on a bar where the coin was still at its high.
A synthetic-cliff test caught it (`test_rip_fires_on_an_irreversible_collapse`: expected
index 39, got 34). `find_rip` now walks the reference forward to the last bar still within 90%
of the pre-fall level and re-checks every condition there. Left uncorrected it would have
*inflated* every lead time by up to six hours — flattering, and wrong.

**2. `err IS NULL` silently matches nothing on BigQuery's Solana table, and the dry run says
0 bytes.** `err` is a non-nullable `STRING`; a successful transaction carries `''`. The dry
run then reports **0 GB**, which reads exactly like a free query rather than like an empty
one. Measured on five minutes of 2026-07-30 chain time: 824,013 rows with `err = ''` against
~62,000 carrying an error string. The predicate is `err = ''`.

**3. `bq --max_rows` truncates silently, and it costs a full scan to find out.** The first
signer pull hit a 2,000,000-row cap *after* the 415.8 GB scan had been billed. The fix is a
cheap `COUNT(*)` first (34.9 GB, $0.20 — it touches far fewer columns), then a row cap set
from the count, then an assertion that the returned row count equals the counted one.

**4. Watch windows moved a headline number by 14×.** The inter-trade CV on nosis/SOL read
**33.4** — spectacularly bursty — until gaps that straddle a `watch_close`/`watch_open` pair
were excluded. Inside coverage it reads **2.31**. The 33.4 was measuring the recorder being
switched off. This is the discipline in `shitcoims_netmap/tapefeed.py` doing exactly the job
it was written for, on a statistic nobody had applied it to before.

**5. The survivorship fix reintroduced survivorship one screen later.** Building the cohort
from a death-carrying enumerator and *then* filtering the other arm on current FDV ≥ $1M
excludes every coin that collapsed below $1M — which is all of them. The screen is now an
upper bound, and membership is decided by peak market cap computed from the series. §2.1.

**6. A fixed-percentage drawdown label rewards volatility, not direction.** `rv_hourly` at
AUC 0.926 with q = 7e-71 is exactly what a shippable result looks like, and it was measuring
nothing but "this coin moves a lot". §5.5 has the control and `vol-control` is now a command.
This one is a trap the whole repo can step in, not just this study.

**One more, not a trap but a fact worth carrying forward: adding pools to a BigQuery scan is
free.** 4 pools and 46 pools both dry-run at 415.8 GB, because the cost is set by the columns
read, not by the `EXISTS` filter. There is therefore no reason to ever pull a treatment arm
without a control arm — and the control arm in §7.2 cost $0.00 extra.

---

## 10. What this does not establish

Listed as things a reader might otherwise assume, not as ritual hedging.

1. **A null at this cohort size is weak evidence of absence, and it is stated as such.** The
   cohort is 781 screened mints, 182 in the band, **23 mechanical cliffs of which 16 are
   unscorable**. Every number in §5.1 rests on the seven that remain. Seven coins cannot
   refute a detector; what they *can* do is fail to support one, and a confidence interval
   from resampling seven entities is honest about that in width rather than narrow by
   accident. The *inversion* (five of six cells below 0.5) is more informative than the
   failure to clear the null, because a sign is easier to establish than a magnitude — but it
   is still seven coins.

2. **It does not establish a hazard.** `p_rip_h24` in the alert contract is `null` and must
   stay null. The score is a percentile, and a percentile is not a probability of anything.
   Given §5 there is nothing to calibrate it against.

3. **It says nothing about sub-$1M coins.** The band filter is a sample definition. Below $1M
   the pattern has no room to express itself and the reference class is the 21,859-launches-a-
   day population that `RESULT_deterioration.md` §1 argues is a category error to train on.

4. **S3 does not generalise from the cluster.** Eleven pools with signers, of which four have
   more than 1,000 swaps. The BigQuery arm (§7.2) widens this to cohort coins for two days and
   is the right way to widen it further, but two days is two days.

5. **No funding-tree ancestry.** The brief asked for funding-commonality among the "buyers",
   and this study does not have it. `studies/entity_resolution.py` has the validated machinery
   (pair precision 1.000, recall 0.762 against a planted world) but it needs a funding-edge
   store the cohort does not have. Wash share is reported *without* it and is therefore not
   separable from ordinary round-tripping.

6. **The bleed label is refuted, not merely different.** It was pre-registered because there
   are two ways to lose money and reporting only the one that came out well is the single most
   common way a study like this lies. It then came out well, and §5.5 shows why that was an
   illusion. Nothing in this document rests on it.

7. **The grouped-CV design trades a real guarantee away.** A fold's calibration can contain
   states later in wall-clock time than the states it scores. It was chosen because the
   temporal split leaves *one* positive coin in the test half — an AUC against one positive
   coin is that coin's fingerprint. Both are reported; where they disagree, the temporal one
   is the one to believe and the grouped one is the one with enough data to be worth reading.

8. **`config.yaml`'s rug thresholds are not shown to be wrong.** §4.1 measures them against
   *this* cohort on *hourly* bars. The sentinel runs on live quotes at seconds resolution
   where a 20% move means something different. The measurement is a reason to ask where those
   numbers came from, not a verdict on them.

---

## 11. What to do with this

**Ship, as an avoid-filter and a lens — not as a trigger.**

1. **Do not wire the score to an exit.** Precision is zero at every operating point and the
   score is inverted against imminent cliffs. Automating it would sell into the wrong hours and
   would have fired on DREGG for twelve hours in July.
2. **Do ship `dead_hour_frac` + `turnover` as a GHOST_TOWN *position* filter**, which is a
   different and much better-founded claim than the crime score. `$TOPG` lost 98.3% in one hour
   because there was nobody on the other side; that state is measurable *now*, needs no forward
   window, and says something an operator can act on without any prediction at all: **the
   quoted market cap of a coin with no flow is not a price you can get.** This is a statement
   about `C`, not about the future, which is exactly the kind of claim PROGRAM.md §8 says to
   prefer — state estimation, not label prediction.
3. **Keep the alert stream running at `severity: "watch"`** (`state/crime/alerts.jsonl`, §8).
   The rows cost nothing, they carry their own thresholds, and the cohort is the binding
   constraint: 23 cliffs is what forced every "no". Accumulating labelled cliffs forward is the
   only thing that changes the answer.
4. **Re-run `vol-control` on anything that predicts a drawdown.** §5.5.
5. **The next real experiment is on the accumulation window, not the rip.** §7.2 showed the rip
   itself is a frenzy of thousands of wallets, so concentration measured *at* the collapse can
   only find nothing. Whatever is coordinated happened days earlier — and that needs signers
   during accumulation, which retrospective BigQuery cannot afford at this rip dispersion
   (~$2.8/day, ≤2 rips per day) and forward recording can. **Pre-register a watchlist of
   in-band coins and record their swap tape forward**, exactly as the cluster tape already does
   for the desk's eleven pools. That is the cheap version of the experiment this study could
   not run.
6. **Shorten the window to 6 hours if any of this is revisited.** It recovers 19 of 23 cliffs
   instead of 7 (§5.3) at an alert rate of 2.31%. It still beats no null today, but every
   future test gets 2.7× the positives for free.
