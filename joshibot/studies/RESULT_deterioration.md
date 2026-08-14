# Deterioration: is this coin ready to ditch?

*Study code: `studies/deterioration.py`. Cache: `state/deterioration/`. Run 2026-08-14, keyless
sources only, no Helius credits spent.*

The operator holds four techproject coins — weave, nosis, DREGG, SOLVE — and wants a read on
when one is deteriorating enough to exit. This is the instrument, its honest evaluation, and
today's reading.

---

## 0. Headline

**Cohort: 110 coins, 22,805 hourly states, keyless, under two hours of rate-limited fetching.** The
operator's framing was right — condition on survival and the reference class collapses from
21,859 launches a day to something enumerable in an afternoon.

**The lead/lag hypothesis is refuted.** "Price flat while volume erodes underneath" does not
predict forward returns in this cohort: Spearman −0.060 at 24h and **+0.133 at 72h** — opposite
signs, both CIs spanning zero, and the sign flips across consecutive test windows. Not a
market-regime artifact (identical under market adjustment) and not a power failure (the same
pipeline recovers a planted effect of that size at Spearman +0.57–0.67).

**The analogue lookup itself has real but narrow skill.** Brier skill vs climatology **+0.176**
at 24h (95% CI +0.075 to +0.247), outside a zero-world band whose maximum over 8 seeds is
−0.004, surviving temporal split, entity grouping, market adjustment and a random-neighbour
control. But **rank skill on the size of the move is not established** (Spearman +0.053 at
24h, CI containing zero; −0.023 at 72h), and at 72h the decile flagged most likely to crash had
a mean forward return of **+0.287**. The instrument reads *variance*,
not direction. Treating it as a return forecast would have been wrong in the measured window.

**Today:** nosis carries P(≤ −20% in 24h) = **20%** against a 4% base rate, with analogue p10
−47% — and its state is capitulation, not distribution. DREGG is the only one of the four whose
analogues are in-distribution (match quality 1.4×), and it reads calm at 5%. weave shows the
distribution *pattern* the operator suspected (10%) — via a mechanism this study just refuted.
SOLVE reads 2%, on seven distinct coins' worth of evidence.

**Not testable keyless:** liquidity, holder and flow *history* do not exist in any free source.
Cost to close that gap: **≈ $13.50** of BigQuery for a 41-day panel — with a coverage caveat
this repo has already measured (§2.3).

---

## 1. The design, and why the survivor conditioning is the point

The operator's framing is correct and it is the load-bearing design decision, so it is worth
stating precisely rather than in passing.

Training on the population of all pump.fun launches to say something about a coin with 986
holders and a six-week trading history is not a bias to be corrected — it is a category error.
The numbers:

- **~21,859 pump.fun launches per day** (Marino/Lillo, arXiv:2602.14860, verified in
  PROGRAM.md §1.1). Intractable to collect keyless and irrelevant to the question.
- **~60% of tokens live less than one day** (Cernera et al., USENIX Sec'23).
- **Graduation is 0.63% unconditional but 2.55% among tokens with ≥30 swaps** (Marino) — a
  4× move in the base rate from *one weak condition*.

That last number is the whole argument. Conditioning does not merely shrink the sample; it
changes what the sample is *about*. Condition harder — age > 2 days, real volume, real FDV —
and the reference class becomes simultaneously more relevant and small enough to enumerate
with keyless APIs. That is the cohort this study builds.

**Method: k-nearest-neighbour analogy, not a fitted model.** For a coin-state today, retrieve
the most similar historical coin-states and report the distribution of what happened next.
Three reasons, in order of importance:

1. **It is auditable.** The operator can read the analogues and overrule them. A logistic
   regression coefficient cannot be overruled by someone who knows the coins.
2. **It makes no distributional assumption**, which matters at 10⁴ states in a regime that
   shifts in weeks (PROGRAM.md §3 rule 6).
3. **It is the baseline the literature says to beat first.** PROGRAM.md §1.5: EdgeBank, a
   zero-parameter hash table, ranks 2nd across 13 temporal-graph benchmarks, and on the crypto
   benchmark a decayed popularity counter beat both it and TGN by 14 MRR points. Memorisation
   is the thing to beat, not the fallback.

---

## 2. What keyless data actually exists — the binding constraint

This section is a deliverable in its own right, because it determines what any study of this
question can and cannot conclude, and because the answer is more restrictive than it looks.

### 2.1 Inventory, measured not assumed

| quantity | historical? | source | note |
|---|---|---|---|
| price, hourly OHLC | **yes** | GeckoTerminal `/pools/{p}/ohlcv/hour` | 1000 candles = 41.6 days per call |
| volume, hourly USD | **yes** | same call | |
| pool creation time | **yes** | `pool_created_at` on any listing | |
| FDV / market cap | **derived** | `fdv_now × price(t)/price(now)` | exact under constant supply |
| **liquidity** (`reserve_in_usd`) | **no** | GT pool detail | current snapshot only |
| **holders** + top-10 concentration | **no** | GT `/tokens/{a}/info` | current snapshot only |
| buys/sells (transactions) | **no** | GT pool detail / DexScreener | current snapshot only |
| **buyers/sellers (wallets)** | **no** | GT pool detail | current snapshot only |

DexScreener's documented API is snapshot-only — it has no history endpoint at all — and its
chart backend (`io.dexscreener.com/dex/chart/...`) returns **403 to non-browser clients**,
tested at three URL shapes. So GeckoTerminal's OHLCV is the *sole* keyless historical channel,
and it is rate-limited per IP.

**Measured rate reality.** GT's keyless tier is documented at 30 calls/min. Six sibling agents
shared this IP during the run and the effective sustainable rate collapsed to **one call per
~30 s** — a 15× degradation, reached via 429 backoff. The fetcher therefore keeps its pacing
state on disk so concurrent invocations inherit one clock, and uses
additive-increase/multiplicative-decrease so it recovers when siblings finish.

### 2.2 The consequence, stated plainly

**The historical analogue space is a price-and-volume space.** The liquidity half of the
operator's hypothesis is not testable on keyless history. This study does not pretend
otherwise, and it does not paper over the gap with a reconstruction, for a reason worth
recording because it is a trap:

> For a constant-product pool `x·y = k` with token price `p = y/x`, the quote reserve obeys
> `y = √(k·p)`, so `y(t)/y(now) = √(p(t)/p(now))`. This is exact — **under trading alone**.
> Which means the *deviation* between that line and the true past reserve is precisely the net
> LP add/remove. That deviation is the deterioration signal we want, and it is exactly the part
> the identity cannot supply. Feeding the reconstruction to the model would be feeding it a
> deterministic function of price and calling the output a liquidity signal.

The function is implemented (`liquidity_counterfactual`) and is *never* called as a feature.

### 2.3 The fix, and what it costs

Two routes close the gap. Both are named with their real numbers.

**Route 1 — forward accumulation, free, slow.** Every live read appends the full vector
(liquidity, holders, top-10 concentration, transaction-level *and* wallet-level flow) to
`state/deterioration/snapshots.jsonl`. Run daily and the full vector becomes historical in
weeks. Cost: zero. Latency: weeks. This is already wired.

**Route 2 — BigQuery public Solana dataset, cheap, coverage-impaired.** This repo has already
run one: `state/bulk_history/meta/20260812.json` records a real job billing **58,028,195,840
bytes** (0.0528 TiB) for one day of `bigquery-public-data.crypto_solana_mainnet_us.Token
Transfers`. At $6.25/TiB on-demand that is **$0.33 per day-queried**, and because the scan cost
is set by the partition rather than the address filter, the *same* $0.33 covers any number of
pools. A 41-day reserve-and-holder panel across the whole cohort is therefore ≈ **$13.50**; a
full year ≈ **$120**.

That is cheap enough to be the obvious answer, so the caveat matters: the sibling `bulk_history`
lane *measured* the public dataset's coverage and found it unreliable — 2026-08-10 and
2026-08-11 came back `EMPTY` (wsol_ratio 0.000127, 0 of 24 hourly buckets loaded) and
2026-08-12 came back `PARTIAL` at 83% of buckets. The cheap route exists; its completeness has
to be verified per-day before anything is built on it.

**Not recommended:** Helius ($49/mo, 10M credits — the operator's plan is metered and other
lanes need it), and paid Birdeye/Moralis/Bitquery tiers, all of which solve a problem Route 2
solves for $13.50 if the dataset's gaps can be filled.

---

## 3. The instrument, calibrated before it was pointed at anything

*(numbers in this section come from `python -m studies.deterioration selftest`, which runs the
pipeline against synthetic worlds whose answer is known.)*

PROGRAM.md §3 rule 12 is binding and it is the rule most often skipped: **both controls,
always**. A null control alone is worthless because a constant-zero estimator passes it
perfectly. So the pipeline is run against a known-ZERO world (10 independent standard-normal
features, pure-noise outcome) *and* a known-EFFECT world (outcome = `0.35·dvol_24 −
0.15·ret_24h` + noise) before it is allowed near real data.

### 3.1 The pipeline recovers a planted effect

Known-EFFECT world, 250 synthetic coins, 72h horizon, k=40, threshold "forward return ≤ −20%":

| metric | value |
|---|---|
| Brier: kNN / random-k / climatology | 0.1598 / 0.2253 / 0.2240 |
| skill vs climatology | **+0.2863** (95% CI +0.2451, +0.3344; entity bootstrap) |
| Spearman(predicted median, actual) | **+0.6998** (95% CI +0.6588, +0.7370) |
| top-decile death rate vs base | 0.829 vs 0.339 → **2.45× lift** |
| mean forward return, top decile vs all | −0.6441 vs +0.0041 |

So the instrument can see a real effect of this size. That is the half of rule 12 people skip,
and without it a null below would be uninterpretable.

### 3.2 The false-positive band — and it is wider than it looks

Known-ZERO world (features independent of outcome by construction), 8 permutation seeds:

| cohort size | skill vs climatology (max over seeds) | Spearman (max) | top-decile lift (max) |
|---|---|---|---|
| 250 coins | −0.0146 | +0.0497 | **1.21×** |
| 100 coins | −0.0050 | +0.0563 | **1.45×** |
| 120 coins (k=40, 480 test states) | +0.0065 | +0.0946 | **1.79×** |

**Read the last column again.** This pipeline produced a top-decile lift of **1.79× from pure
noise**. Lift is the metric a trading study most wants to quote and it is the least trustworthy
one here: at these cohort sizes the top decile is 40–70 observations and its death rate is
correspondingly unstable. Any reported lift below roughly 1.5× is inside the instrument's own
noise and is not evidence of anything.

The band widens as the cohort shrinks, so it is calibrated at the size actually achieved
(`selftest --mints N`) rather than quoted from a convenient run. Brier skill is the
best-behaved of the three — it never went positive on any zero-world seed at any size — and it
is therefore the metric the verdict rests on.

### 3.3 The extraction pipeline is checked against a series with known answers

Before any of this, `load_series`/`state_at` were run against a hand-built 400-hour series
(flat price then a 50% decay, volume decaying 3%/h, with a deliberate 10-hour candle gap). All
exact: age 16.25 d against 16.25 d expected; the gap forward-filled price and zero-filled volume
(`active_frac_24h` = 0.58 = 14/24 at the gap); drawdown −0.686 = log(0.5035); the FDV
reconstruction returning exactly `fdv_now` at the last candle; and `fwd_72` reproducing
log(0.5^0.72) to five decimals.

That check caught a real bug: pool creation times parsed with `time.mktime` instead of
`calendar.timegm`, which put a **7-hour error into every age in the panel** on this box.

---

## 4. Cohort and panel

### 4.1 How the cohort is assembled, and the one bias that survives

Discovery unions every keyless GeckoTerminal listing — network-wide pools by 24h volume and by
24h transaction count, per-DEX listings for pumpswap / raydium / meteora / orca, trending, new
pools — four pages each, plus the operator's own four mints by construction. Result:

| stage | count |
|---|---|
| distinct Solana pools discovered | **531** |
| after quote-token filter (SOL/USDC only), major-token exclusion, FDV in $20k–$50M | **298** |
| of those, FDV ≤ $2M (the operator's scale band, fetched first) | **173** |

FDV distribution of the 298 candidates: 38 under $100k, 58 at $100k–$500k, 77 at $500k–$2M, 71
at $2M–$10M, 54 at $10M–$50M. DEX mix: pumpswap 149, raydium 58, meteora 56, orca 23, other 12.
The operator's four coins sit at $37k (SOLVE), $145k (weave), $301k (nosis), $348k (DREGG), so
the 96 candidates under $500k are the scale-matched part of the reference class.

**Cohort entry is dated retrospectively, which is the design's load-bearing trick.** A pool
enters the panel at the first hour of *its own history* where it clears age ≥ 2 days, 24h volume
≥ $25k and FDV ≥ $50k — and every state after that is retained, collapse included. A cohort
defined on *today's* numbers would contain only coins that are still healthy today and would
therefore have no examples of the thing the instrument exists to recognise. Entry thresholds sit
an order of magnitude below the operator's stated filter ($100k/day) because their own coins do:
DREGG traded $20k in the last 24h. A reference class that excluded the query point would be
useless.

**The bias that survives, and its direction.** Every GT listing is a *top-N-by-something-today*
list, so a coin that died so completely it fell off every list is not discoverable. That is real
and it cannot be fixed keyless. Its direction is knowable, though, and it is the forgiving one:
missing coins are disproportionately *dead* ones, so **every death rate in this study is a lower
bound and every forward-return distribution is optimistic.** When the instrument says the
analogues died 40% of the time, the truth is worse, not better.

The partial mitigation is that death is still observed *within* surviving coins' histories — a
coin can lose 95% of its volume and 80% of its price and still be listed — so the panel does
contain collapse trajectories. §4.2 measures how many.

### 4.2 The age gate, and the mistake that made it necessary

The first fetch pass ordered candidates by "FDV ≤ $2M, then highest volume" — which reads like
the operator's scale band. It is in fact the exact signature of a pump.fun launch four hours
old. **70 pools fetched, median 4 hourly candles, 69 of 70 with fewer than 72.** The
small-and-busy corner of the cross-section *is* the 21,859-a-day population this study exists
to exclude, and it walks straight back in through a screen built on size and activity alone.

Age separates them and costs nothing — pool creation time is already in the discovery row, so
the gate belongs *before* the API call, not after it. Applying `age ≥ 2 days` to the 298
candidates leaves **171**, with median age **89 days** and 102 of them old enough to fill the
full 41-day OHLCV window.

That is Marino's conditioning argument arriving as an operational fact rather than a citation:
one free filter, applied at the right moment, changes what population you are looking at.

### 4.3 What the panel contains

| | |
|---|---|
| hourly states (4h stride) | **22,805** |
| distinct coins | **110** |
| pools | 141 |
| median span in panel | 38.5 days |
| FDV: p10 / median / p90 | $164k / $5.07M / $31.9M |
| coins whose volume fell ≥95% from their own peak | 17 (**15.5%**) |
| coins down ≥80% in price from peak | 12 (10.9%) |
| median 72h forward return | −0.84% |
| base rate: 72h forward SOL return ≤ −20% | **7.7%** |

**110 coins is the answer to "how big is the survivor cohort", and it is the shape the
operator predicted** — hundreds, not millions, and enumerable keyless in an afternoon.

One structural fact deserves emphasis because it constrains everything downstream: the median
cohort FDV is $5.07M while the operator's coins run $39k–$395k. **Old-and-small is rare.** The
age gate that removes fresh launches also removes most small coins, because a coin that is both
small and old is usually one that has already died and fallen off every listing. So the
operator's own coins sit at roughly the 10th percentile of their own reference class, and the
instrument is extrapolating for at least one of them. §6 measures that per coin rather than
assuming it away.

---

## 5. Results

Protocol for everything below: temporal split (library strictly before the cut, forward windows
closed before the cut, test embargoed by one full horizon), entity-level exclusion enforced at
retrieval (a coin is never its own analogue), test states thinned to one per coin per forward
horizon, entity-level block bootstrap for every confidence interval, no resampling anywhere,
and every number quoted against the null band from §3.2 recomputed on this panel.

### 5.1 The lead/lag hypothesis: **REFUTED, and not narrowly**

The claim was: price lags, volume and liquidity lead; a coin whose price is flat while volume
erodes underneath is being distributed into. Operationalised as
`divergence = z(ret_24h) − z(dvol_24)`, both scales fitted on the library. **If true, its
Spearman correlation with forward return is negative.**

| horizon | Spearman(divergence, forward return) | 95% CI (entity bootstrap) |
|---|---|---|
| 24h | **−0.060** | [−0.143, +0.026] |
| 72h | **+0.133** | [−0.038, +0.293] |

Both confidence intervals contain zero, and **the point estimates have opposite signs at the
two horizons.** Per-window it is worse: at 24h the correlation runs −0.163, −0.029, +0.007
across three consecutive test windows — it does not merely weaken, it changes sign. The 72h
terciles are U-shaped rather than monotone (death rate 12.7% / 3.3% / 17.2% from low to high
divergence), which is what noise looks like when you cut it three ways.

This is a null, and it is a *clean* one: the same pipeline, on the same panel, at the same
sample size, recovers a planted effect of comparable size with Spearman +0.57 to +0.67 (the
known-EFFECT control, run alongside every table here). The instrument was looking, and there was
nothing at this magnitude to find.

**It is also not a market-direction artifact.** Repeating the whole test against market-adjusted
returns (each coin's forward return minus the contemporaneous cohort median) moves the numbers
by less than 0.005: −0.057 at 24h, +0.134 at 72h. The null is about this statistic, not about
the market regime it was measured in.

### 5.2 What *did* survive, both times

Two features are significant at 24h, keep their sign at 72h, and survive market adjustment.
Neither was the hypothesis.

| feature | Spearman @24h [CI] | Spearman @72h [CI] | reading |
|---|---|---|---|
| `active_frac_24h` — share of the last 24 hours with any trade | **−0.078** [−0.140, −0.010] | **−0.175** [−0.296, −0.046] | continuously-traded coins do *worse* forward |
| `drawdown` — log(price / running peak) | **+0.105** [+0.040, +0.170] | +0.158 [−0.012, +0.327] | further below peak → worse forward; momentum, not reversion |

The `drawdown` sign is the one worth arguing about, because it is the opposite of what a
dip-buyer assumes: within this survivor cohort, over 24h horizons, coins deep below their peak
kept falling. That is a *positive* correlation between a more-negative drawdown and a
more-negative forward return, measured out of sample, and it is the single most stable
relationship in the panel. It is also modest — a Spearman of 0.105 is a hint, not a strategy.

`dvol_24`, `ret_24h` and `log_vol_ratio_7d` are individually null at both horizons, which is
worth stating plainly since the first two are the components of the refuted divergence
statistic.

### 5.3 The kNN instrument: real skill on tail risk, none on expected return

| | 24h horizon | 72h horizon |
|---|---|---|
| library / test (thinned) | 3,947 states, 84 coins / 702 | 3,619 states, 81 coins / 190 |
| base rate (library / test) | 3.1% / 6.1% | 6.4% / 11.1% |
| Brier: kNN / random-k / climatology | 0.0481 / 0.0590 / 0.0584 | 0.0837 / 0.0989 / 0.1004 |
| **skill vs climatology** | **+0.176** [+0.075, +0.247] | **+0.167** [−0.015, +0.291] |
| skill vs random-k | +0.184 | +0.154 |
| Spearman(predicted median, actual) | +0.053 [−0.019, +0.138] | −0.023 [−0.220, +0.178] |
| top-decile lift | 4.43× (n=70) | 2.38× (n=19) |
| null band max (8 seeds, this panel) | skill −0.004, ρ +0.047, lift 2.06× | skill +0.016, ρ +0.081, lift **2.50×** |

Threshold for every "death" number above: forward SOL-denominated return ≤ −20%.

Read that table carefully, because it says two different things:

1. **Brier skill is real at 24h.** +0.176 with a bootstrap CI clear of zero, against a
   zero-world band whose maximum over eight seeds is −0.004. It also beats random-k
   neighbours by +0.184, which is the comparison that isolates the *state space* from the
   cohort's base rate. And it survives market adjustment (+0.169 at 24h, +0.197 at 72h,
   the latter's CI now clearing zero at [+0.013, +0.308]) — so this is coin-specific
   information, not a read on where the whole memecoin complex was going.
2. **Rank skill on the size of the move is at best marginal, and absent where it matters.** At
   24h the Spearman is +0.053 against a null-band maximum of +0.047 — technically outside the
   band, but its own bootstrap CI is [−0.019, +0.138] and contains zero, so the two disagree
   and the honest reading is "not established". At 72h it is −0.023, squarely inside the band.
   And at 72h the top decile by P(down) had a mean forward return of **+0.287** against +0.049
   for all test states — the states flagged as most likely to crash were, on average, *up*.

Those are consistent, not contradictory, and the distinction is the whole practical point:
**the instrument detects elevated variance, not lower expected return.** A high P(down) state
is one whose analogues include both −50% and +100% outcomes. Acting on it as if it were a
forecast of a lower mean would have been wrong at 72h in exactly the measured window.

At 72h the lift (2.38×) is *inside* the null band (max 2.50×) and the skill CI crosses zero.
Only the 24h horizon clears everything. The 168h horizon is **not evaluable at all**: with 41
days of history, a 7-day forward window plus a 7-day embargo leaves zero test states, and the
code reports that rather than quietly shrinking the embargo.

### 5.4 Operating points

What a rule would actually have done on the test period, 24h horizon, raw SOL returns:

| exit if P(down) ≥ | states flagged | precision | recall | mean fwd \| flagged | mean fwd \| held |
|---|---|---|---|---|---|
| 0.40 | 8 of 702 (1.1%) | 0.500 | 0.093 | **−11.6%** | +0.9% |
| 0.50 | 2 of 702 (0.3%) | 1.000 | 0.047 | **−58.6%** | +0.9% |

Precision 0.50 against a 6.1% base rate is an 8× lift, and the two states that crossed 0.50 both
crashed. But note the counts: **the high-confidence alarm fires on 0.3–1.1% of coin-days.** This
is not a monitor that will tell you what to do this week. It is a rare, loud alarm, and its
value is precisely that it stays quiet — with n=2 at the 0.50 threshold, that cell is an
anecdote with a decimal point, not an estimate.

---

## 6. Live read: the operator's four coins

Run 2026-08-14 ~06:10 UTC. Library: all 22,805 panel states from 110 coins; every analogue's
outcome is already realised, so there is no lookahead in a live read by construction. Horizon
24h, k=40, SOL-denominated, threshold ≤ −20%. Cohort base rate at 24h: **4%**.

| | weave | nosis | DREGG | SOLVE |
|---|---|---|---|---|
| price | $0.0001482 | $0.0002748 | $0.0003954 | $0.00003943 |
| FDV | $135,174 | $267,528 | $395,443 | $39,436 |
| liquidity | $28,903 | $48,917 | $59,504 | $15,339 |
| pool age | 10.3 d | **4.9 d** | 47.6 d | 24.3 d |
| holders | 442 | **1,825** | 976 | 187 |
| 24h volume | $99,873 | $573,296 | $33,382 | $7,091 |
| 24h price change | +1.4% | **−38.7%** | +11.5% | +4.5% |
| 24h volume change (log) | **−2.05** | −0.47 | −0.54 | −0.08 |
| drawdown from peak (log) | −1.05 | **−1.53** | −1.36 | −0.67 |
| top-10 holder share | 32.4% | 24.8% | 37.5% | **43.0%** |
| divergence z | **+2.86** | **−7.19** | −0.50 | −0.60 |
| **P(≤ −20% in 24h)** | **10%** | **20%** | 5% | 2% |
| analogue median / p10 / p90 | −1.4% / −23.1% / +44.4% | −6.1% / **−47.3%** / +29.9% | +0.4% / −18.5% / +10.4% | +0.3% / −11.5% / +11.8% |
| match quality (vs typical) | 3.2× **extrapolating** | 3.2× **extrapolating** | **1.4× good** | 2.3× extrapolating |

**nosis is the coin the operator described** — 1,825 holders, ~$600k daily volume, days old —
and it carries the highest reading of the four: **P(≤ −20% in 24h) = 20% against a 4% base
rate**, with an analogue p10 of −47%. Its divergence z is −7.19, i.e. the *opposite* of the
distribution pattern: price is falling much faster than volume, which is capitulation, not
quiet distribution. Its nearest analogues (MANLET, CHEEMS ×2, 3place, CASHCAT ×2, RAKO, Bepe)
are coins that had just fallen 33–58% in a day, and their next 24 hours ran from −19% to
+317%. That spread *is* the finding: this state has enormous variance, and §5.3 says the
instrument reads variance rather than direction.

**weave is the one that matches the operator's original intuition.** Its 24h volume is down to
about 13% of the prior day (dvol −2.05) while price is flat-to-up, giving the highest divergence
z in the group (+2.86) — textbook "price holding up while support erodes". P(≤ −20%) = 10%,
2.5× base. **And §5.1 is exactly the finding that this pattern does not predict what it looks
like it predicts.** The elevated reading here comes from the kNN's whole state vector, not from
the divergence term, which the panel says is uninformative. Reported because it is what the
operator asked about, and flagged because the study refuted the mechanism behind it.

**DREGG is the quiet one, and the only one the instrument is entitled to speak about.** Match
quality 1.4× typical — inside the library's own distribution — P(≤ −20%) = 5% against a 4%
base, analogue p10 −18.5%. No signal. Its analogues are dominated by MANIFEST, a $7M coin
matched on turnover and dynamics rather than size.

**SOLVE reads calm and the reading should be discounted anyway.** P(≤ −20%) = 2%, *below* base
rate. But all eight nearest analogues are the same coin (VOID/SOL) at eight different dates —
so the "40 neighbours" are a handful of independent observations wearing forty hats. At $39k FDV
SOLVE sits below the library's 10th percentile and there is genuinely nothing else nearby. The
instrument now prints this (`analogues drawn from N distinct coins`) rather than letting a
confident-looking percentile stand.

### 6.1 The wallet-vs-transaction divergence — a correction the operator will want

The operator's observation was that on nosis, **73% of wallets were net sellers while only 54%
of transactions were sells**. That distinction is real and worth carrying. But the keyless field
that looks like it measures it does not:

> GeckoTerminal's `buyers` / `sellers` are counts of **distinct wallets that bought** and
> **distinct wallets that sold** in the window. A wallet that did both is counted in **both**.
> That is not a net-direction classification, and it cannot be turned into one without per-wallet
> position netting, which is chain-level work.

Measured today, the two statistics on nosis are 53% (transaction-level) and 53% (wallet-level) —
no gap at all. That is not evidence that the operator's 73% has gone away; it is evidence that
**my number is measuring something else**. The real net-seller fraction needs the swap tape,
which this repo already collects for the cluster in `state/bulk_history/` and
`state/cluster_tape/`. It is one join away and it is not in this study.

### 6.2 Sell pressure against scale-matched peers today (descriptive, unvalidated)

A raw 53% sell share means nothing without knowing what a comparable coin looked like on the
same day, so `deterioration peers` puts a percentile on it. Peers are pools within 0.25×–4× FDV,
transaction-level from DexScreener in bulk, wallet-level from GeckoTerminal one call each.

| | tx sell share (percentile) | wallet sell share (percentile) | peers (tx / wallet) |
|---|---|---|---|
| weave | 46.8% (**28th**) | 51.2% (57th) | 32 / 7 |
| nosis | 52.5% (**88th**) | 52.6% (57th) | 41 / 7 |
| DREGG | 55.1% (**96th**) | 52.8% (86th) | 45 / 7 |
| SOLVE | 51.0% (88th) | 51.2% (62nd) | 16 / 8 |

**This disagrees with §6's kNN read, and the disagreement should not be resolved by picking a
favourite.** DREGG is the calmest coin on the kNN reading (P = 5%, well-matched analogues) and
carries the *highest* peer-relative transaction sell share of the four (96th percentile). weave
is the reverse: elevated kNN reading, lowest peer-relative selling (28th).

The honest resolution is that **only one of these two instruments has been tested against
forward outcomes.** The kNN numbers come with a temporal split, an entity-level bootstrap and a
measured null band. The peer percentiles are a same-day cross-section with *no forward
validation whatsoever* — nothing in this study establishes that a high peer-relative sell share
predicts anything at all. They are here because the operator asked a specific question about
flow and this is the honest answer to it, not because they constitute a signal. The
wallet-level column additionally rests on 7–8 peers, which is too few to read a percentile off
with any confidence.

Testing it requires forward data that does not exist yet, and the fix is running: every read
appends the full vector to `state/deterioration/snapshots.jsonl`. Run `peers` daily for three
weeks and the test becomes available.

---

## 7. Falsifications

Each claim above, with the test that could have killed it and what the test said.

| # | claim | falsification | outcome |
|---|---|---|---|
| 1 | price lags, volume leads | Spearman(divergence, forward return) < 0, stably, out of sample | **REFUTED** — signs opposite at 24h/72h, CIs span zero, sign flips across test windows |
| 2 | ... it is at least directionally right, just weak | same test on market-adjusted returns | still null (−0.057 / +0.134); not a regime artifact |
| 3 | the pipeline could have found it if it were there | plant an effect of comparable size, re-run everything | **recovered**: Spearman +0.57–0.67, skill +0.18–0.24 |
| 4 | kNN skill is real, not noise | zero-world control, 8 permutation seeds, band recomputed on this panel | **survives at 24h**: skill +0.176 vs band max −0.004 |
| 5 | ... and it is not just reading the market | market-adjusted returns (coin minus contemporaneous cohort median) | **survives**: +0.169 @24h, +0.197 @72h |
| 6 | ... and it is not the cohort's base rate leaking in | random-k neighbours from the same library | **survives**: +0.184 over random-k |
| 7 | ... and not an artifact of overlapping windows | thin test to one state per coin per horizon; entity bootstrap | 702 kept from **6,520** unthinned (thinned to one per coin per 24h, then capped by coin); CI still clears zero |
| 8 | ... and not leakage across the split | library forward windows must close before the cut; test embargoed one horizon | enforced in `temporal_split`, not asserted |
| 9 | ... and not a coin predicting itself | same-mint exclusion at retrieval, not just at split time | enforced in `Library.nearest` |
| 10 | the top-decile lift is impressive | compare to the lift the same pipeline produces on pure noise | **partly refuted**: 4.43× clears the band at 24h, but 2.38× at 72h is *inside* it (band max 2.50×) |
| 11 | a high P(down) means expect a worse return | mean forward return of the flagged decile | **REFUTED at 72h**: +0.287 flagged vs +0.049 all. It reads variance, not direction |
| 12 | the live analogues are analogues | mean neighbour distance vs typical library neighbour distance | 3 of 4 coins **extrapolating** (2.3–3.2×); only DREGG in-distribution at 1.4× |
| 13 | 40 neighbours are 40 observations | count distinct coins supplying them | **refuted for SOLVE**: 7 coins, now printed as a warning |
| 14 | the 168h horizon just needs more data | attempt it | **not evaluable**: 41 days of history leaves zero test states after embargo; reported, not silently patched |
| 15 | reported death rates are unbiased | can a fully-dead coin be discovered keyless? | **no** — every death rate here is a **lower bound** (§4.1) |

### 7.1 What would change the verdict

- **Liquidity history.** The half of the hypothesis that could not be tested. $13.50 of BigQuery
  (§2.3), subject to verifying the public dataset's per-day coverage, which this repo has
  already measured as unreliable.
- **A longer window.** 41 days is one regime. The 168h horizon is unreachable and the 72h
  horizon has 190 test states. Paging GT's OHLCV back with `before_timestamp` doubles the
  history at double the call cost, and the rate limit — not the money — is the binding
  constraint.
- **More small-and-old coins.** The cohort's median FDV is $5.07M against the operator's
  $39k–$395k. Three of four live reads are extrapolations. This is the single highest-value fix
  and it is a discovery problem, not a modelling one.
- **Wallet-level net direction** from the swap tape (§6.1), which would let the operator's
  actual observation be tested rather than approximated.

---

## 8. What the operator should take from this

1. **The reference class is real and it is small.** 110 coins, built in an afternoon with no
   API key. The conditioning insight was right and it is what made the data collectable.
2. **The specific mechanism was wrong.** Price-flat-while-volume-erodes does not predict forward
   returns in this cohort at 24h or 72h. It is worth knowing that the intuition is not free.
3. **Something weaker is real.** The analogue lookup has genuine, replicated skill on *tail
   risk* at 24h — outside its own noise band, surviving a temporal split, entity grouping,
   market adjustment and a random-neighbour control. It has **no** skill on expected return.
   Treat a high reading as "this coin's variance just went up", never as "this coin will fall".
4. **Today: nosis is the one to watch** (P = 20% vs 4% base, analogue p10 −47%), and its state
   is capitulation rather than distribution. **DREGG is quiet and is the only read the
   instrument is actually qualified to give** (in-distribution analogues). weave shows the
   distribution *pattern* the operator suspected, at 10% — reported, with the caveat that this
   study just refuted the pattern's predictive content. SOLVE reads calm on seven coins'
   worth of evidence.
5. **The instrument gets better by running.** Every read appends the full vector — liquidity,
   holders, concentration, both flow statistics — to `state/deterioration/snapshots.jsonl`. In
   three weeks that turns the untestable half of this study into a testable one, for free.
