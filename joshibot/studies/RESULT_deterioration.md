# Deterioration: is this coin ready to ditch?

*Study code: `studies/deterioration.py`. Cache: `state/deterioration/`. Run 2026-08-14, keyless
sources only, no Helius credits spent.*

The operator holds four techproject coins — weave, nosis, DREGG, SOLVE — and wants a read on
when one is deteriorating enough to exit. This is the instrument, its honest evaluation, and
today's reading.

---

## 0. Headline

*(filled in below — see §5 for the verdict and §6 for the live read)*

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

*(filled in)*

---

## 5. Results

*(filled in)*

---

## 6. Live read: the operator's four coins

*(filled in)*

---

## 7. Falsifications

*(filled in)*
