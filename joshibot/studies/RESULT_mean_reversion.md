# Do the cluster ratios mean-revert at a day-to-few-day horizon?

2026-08-14. The premise the whole LP strategy rests on, measured for the first time.
`studies/RESULT_lp_literature.md` §6.5 records it as untested for *any* memecoin population:
*"the day-to-day mean-reversion premise is neither supported nor refuted."*

Code: `studies/mean_reversion.py` (deterministic given `--seed`, no network at run time) ·
`scripts/fetch_mean_reversion_data.py` (the networked half) · `tests/test_mean_reversion.py`
(three synthetic worlds and a 19-row falsification matrix). Reproduce with

```
uv run python scripts/fetch_mean_reversion_data.py       # writes the cache
uv run python studies/mean_reversion.py --seed 20260814
```

**Helius credits spent: 0.** §2.3 — the budget could not have bought the thing that is missing.

---

## 1. The answer

| pair | verdict at the day-to-few-day horizon |
|---|---|
| **weave/SOL** | **UNRESOLVABLE-AT-THIS-N** |
| **weave/nosis** | **UNRESOLVABLE-AT-THIS-N** |
| **weave/SOLVE** | **UNRESOLVABLE-AT-THIS-N** |
| **DREGG/SOL** | **UNRESOLVABLE-AT-THIS-N** |

Not "indistinguishable from a random walk" — **unresolvable**, which is a stronger and less
comfortable statement. At 24 hours and beyond, on all four pairs, the smallest variance ratio
this sample could have distinguished from a random walk at 80% power lies **below `1/q`, the
value a perfectly reverting process produces**. No mean reversion of *any* speed would have
been visible. The test never had a chance, and reporting "no evidence of reversion" would have
implied it did.

What *is* resolved, and holds for every pair: **at 2 to 12 hours the ratios are
indistinguishable from random walks.** 0 of 52 confirmatory hypotheses survive BH-FDR at
q = 0.10; 0 of 32 exploratory ones do; the smallest p-value anywhere in the confirmatory
family is 0.092, against a BH threshold of 0.0019.

**Two methodological findings are worth more than the null itself**, because both would have
turned this study into a false positive and both generalise to anything else measured on a
young token:

1. **The variance-ratio null is not centred on 1 on a post-launch price series** — it sits as
   low as **0.735** — purely because volatility is front-loaded after launch. Time-shuffling
   the identical magnitudes restores it to 1.000; SOL/USD, with a flat volatility profile,
   never leaves 1. Any test using the asymptotic Lo-MacKinlay reference distribution reads that
   bias as mean reversion (§5.2).
2. **The homoskedastic statistic would have produced a paper.** On the 5-minute grid, **16 of
   32** variance ratios clear |z| > 1.96 under the textbook statistic and **1 of 32** under the
   heteroskedasticity-robust one (§5.1).

And a prior belief did not survive: **`RESULT_swing_cluster.md`'s "robust reversion" in
DREGG/SOLVE — ρ̂ = 0.901, half-life 6.6→7.2h — does not replicate.** On a longer, overlapping
window the coefficient is 0.974, the half-life 26.2 hours, and it sits inside a simulated
random-walk null (p = 0.103). §10.

The one immediately actionable measurement is the numeraire question, and it resolves to
*the choice does not matter* — under ±0.2% of LP variance either way (§11).

---

## 2. Data

### 2.1 What was used

Price series from **GeckoTerminal OHLCV**, full pool history, at 1-minute, 5-minute and 1-hour
granularity. Memecoin pools are requested with `currency=token&token=base`, so the series is the
memecoin priced **in SOL** — the quantity the LP thesis is about — not a USD figure with a SOL
conversion already folded in.

| series | pool | dex | created | liquidity | 24h volume | 24h txs |
|---|---|---|---|---|---|---|
| weave/SOL | `GA1nQL5R…` | pumpswap | 2026-08-03 22:44Z | $29,793 | $99,307 | 1,810 |
| nosis/SOL | `7nv2RtGX…` | pumpswap | 2026-08-09 07:46Z | $51,492 | $615,351 | 6,951 |
| DREGG/SOL | `2XHrhkxf…` | pumpswap | 2026-06-27 15:20Z | $55,818 | $19,911 | 425 |
| SOLVE/SOL | `BQHANwBn…` | pumpswap | 2026-07-20 23:44Z | $14,766 | $6,322 | 136 |
| SOL/USDC | `Czfq3xZZ…` | orca | 2023-07-05 14:34Z | $26,267,693 | $50,808,006 | 26,396 |

**Mints, never symbols.** The trap is real — two distinct tokens use the symbol "nosis"
(`FPfi9q1A…` is the healthy one; `emusQFua…` is the $719k-volume-on-$1.4k-liquidity wash shape
flagged in `RESULT_lp_history.md`). Nothing here reads a symbol. Pool addresses come from
`shitcoims_cluster/pools.py`, which resolved them on chain by reading each pool's vault mints,
and the fetcher independently re-verifies every pool's base-token mint against the expected
mint and **raises** on a mismatch rather than relabelling.

**SOLVE resolved: `GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump`** — from `pools.py`'s
on-chain vault resolution for pool `BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr`, re-confirmed
against GeckoTerminal's `base_token` for the same pool at fetch time. Note `pools.py`'s own
warning: an earlier session scratchpad has **weave and SOLVE transposed**, and the
FDV/liquidity columns in `RESULT_swing_cluster.md` match the on-chain assignment, not the
scratchpad's.

A **chain control** comes from `state/cluster_tape/`: 2,859 successful swaps across the four
pools over ~1.5 days (nosis 2,317 · weave 296 · SOLVE 165 · DREGG 81), each carrying exact
post-swap vault balances as integers. A constant-product pool's *marginal* price is
`sol_reserve / token_reserve` — a state variable, not a trade price, so it has no bid-ask bounce
at all. Raw amounts stay integers into the cache and the ratio is formed only at analysis time.

Everything is JSONL with provenance on every row. Chain time (block time / candle bucket start)
is the origin throughout; ingest time is recorded separately and never used.

### 2.2 What was NOT used, and why

**`tape/` does not cover these tokens.** 617,236 lines across `tape/panel/` and `tape/frames/`,
and a grep for each of the four mints returns **zero hits for all four**. That corpus is a
fresh-pump.fun-launch panel — mints minutes old — a different population from a month-old
graduated token in a $30–56k pool. It cannot answer this question at any n.

**The direct token-token pools are too young.** The weave/nosis DLMM (`QQnW4Zw3…`) was created
2026-08-13 17:49Z and the nosis/DREGG DLMM (`FNxnyS3h…`) at 13:33Z — hours old, tens of trades.
The weave/nosis ratio is therefore formed from the two deep SOL legs, which is the price a
router arbitrages the direct pool toward. Stated rather than hidden: the LP position sits in
the direct pool, the measurement is of the ratio that pool is priced against.

### 2.3 Why zero Helius credits were spent, against a 20,000 budget

**Because the binding constraint is span, and credits cannot buy span.**

A day-to-few-day statistic has at most `history / horizon` independent observations no matter
how finely the price is sampled. weave/SOL's pool is 10.2 days old and nosis/SOL's is 4.8. A
per-swap chain reconstruction would give a *cleaner* price over *exactly the same* 10.2 and 4.8
days and would not add one independent day-scale observation. §1's verdict is a statement about
pool age, and pool age is not for sale.

What credits would have bought is bounce-free resolution — and §9 measures the bounce for free
from the tape already on disk, finding it material at 5-minute sampling and immaterial at
hourly, which is the grid the confirmatory family runs on. So the purchase was unnecessary as
well as unhelpful.

For the record, the price if it had been attempted: the cluster tape recorded **64,683
signatures on the nosis pool in 3 hours 22 minutes** (13,442 failed attempts, 49,452 references,
1,789 swaps) — about 460k/day. At `getTransactionsForAddress`'s 10 credits per 100 transactions,
reconstructing nosis's 4.8-day life alone is **~230,000 credits**, 11.5× the entire budget, for
a series that would still be 4.8 days long.

### 2.4 n at every stage

Bars on the analysis grid, with the fraction forward-filled from an earlier trade:

| series | hourly | stale | 5-minute | stale | 1-minute | stale | span |
|---|---|---|---|---|---|---|---|
| dregg_per_sol | 1,141 | 0.3% | 13,686 | 25.6% | 68,426 | 60.4% | 47.50d |
| solve_per_sol | 581 | 5.0% | 6,963 | 60.2% | 34,808 | 85.4% | 24.17d |
| weave_per_sol | 246 | 15.0% | 2,943 | 55.4% | 14,706 | 78.2% | 10.21d |
| nosis_per_sol | 117 | 0.0% | 1,394 | 0.4% | 6,967 | 12.5% | 4.83d |
| sol_per_usd | 1,999 | 0.0% | 10,989 | 0.0% | 45,237 | 2.8% | 83.25d |

Pairs, after intersecting the two legs (returns = bars − 1):

| pair | hourly returns | span | stale | 5-min returns | stale |
|---|---|---|---|---|---|
| weave/SOL | 245 | 10.21d | 15.0% | 2,942 | 55.4% |
| weave/nosis | 116 | 4.83d | 10.3% | 1,393 | 37.7% |
| weave/SOLVE | 245 | 10.21d | 23.6% | 2,942 | 89.3% |
| DREGG/SOL | 1,140 | 47.50d | 0.3% | 13,685 | 25.6% |
| *DREGG/SOLVE (replication, §10)* | *580* | *24.17d* | *5.3%* | — | — |

The stale column is why the hourly grid carries the confirmatory family. weave/SOLVE at 5-minute
sampling is **89.3% forward-filled** — nine bars in ten are a fact about SOLVE's 136 daily
trades, not about the price. The wild bootstrap preserves those zero returns exactly (a zero
magnitude stays zero under any sign flip), so the null absorbs the missingness instead of the
estimate needing a correction for it.

---

## 3. Method

**Variance ratio** (Lo & MacKinlay 1988), overlapping estimator with their `m` correction, at
q = 2, 3, 6, 12, 24, 48, 72 hours. Both the homoskedastic `z` and the heteroskedasticity-robust
`z*` (their eqs. 20–22) are computed and reported; §5.1–5.2 show why neither is the p-value that
gets corrected.

**Hurst exponent** by three estimators — DFA (order 1), classic R/S, and GPH log-periodogram
regression at bandwidth `m = √n` — because they disagree and the disagreement is the finding.

**Return autocorrelation** at 1h, 6h, 24h, the horizons a ladder actually rebalances on.

**Two nulls, always** (PROGRAM.md §3.13):

- **wild bootstrap** — each observed return multiplied by an independent Rademacher sign,
  preserving the `|r_t|` sequence *exactly*, so the real fat tails, the real volatility
  clustering and the real empty-bar pattern all survive under the null while every odd-order
  serial dependence is destroyed. The null of "a martingale difference with precisely this
  volatility path."
- **white noise at matched L** — iid Gaussian of the same length. Weron's (2002, Physica A
  312:285) setting, which is what makes our Ĥ comparable to his published small-sample spreads.

A **third null** is used as a diagnostic rather than a reference: the same magnitudes
**permuted in time**, which destroys the temporal profile of volatility and nothing else. §5.2.

**Confidence intervals** use a stationary block bootstrap (Politis–Romano, mean block 24 hours),
which preserves the dependence rather than imposing the null.

**The corrected p-value is the bootstrap one, not the asymptotic one.** §5.2 shows the
asymptotic reference distribution is simply the wrong distribution for these series. Both are
reported; only the bootstrap p enters the FDR and only it decides a verdict. An end-to-end test
asserts this, because a regression that swapped them back would turn every null here into a
finding and nothing else in the suite would notice.

**Multiplicity.** The confirmatory family is fixed before looking at the data and is computable
rather than guessed (PROGRAM.md §3.9): 4 pairs × (7 VR horizons + 3 Hurst + 3 ACF lags) =
**52 hypotheses**, BH-FDR at q = 0.10. The 5-minute grid is a **separate exploratory family** of
4 × 8 = 32. The §10 replication is a **third family** of 8, and is additionally charged to the
confirmatory budget as a 60-hypothesis worst case.

**UNRESOLVABLE is a pre-registered outcome with two triggers**, and the second matters more:

1. fewer than 8 non-overlapping spans of the horizon in the sample; or
2. **the minimum detectable variance ratio falls at or below `1/q`** — the value a perfectly
   reverting process produces — so no reversion of any speed was detectable.

A pair's overall verdict is decided only on horizons ≥ 24 hours, so a decisive 2-hour result
cannot be reported as though it settled the day-to-few-day question.

---

## 4. Controls — both worlds, every run

PROGRAM.md §3.12: an estimator that detects nothing passes a zero-control perfectly, so a green
zero-control certifies a broken estimator exactly as readily as a working one. Both worlds run
inside the study itself, shaped like the real DREGG/SOL series (n = 1,140), judged on a
rejection **rate** over 5 independent draws rather than one coin flip.

| world | statistic | rejected | median value | expected | |
|---|---|---|---|---|---|
| known-zero | VR(q=12) | 1/5 | +0.9456 | ≤20% of draws | **PASS** |
| known-zero | ρ(1) | 0/5 | +0.0063 | ≤20% of draws | **PASS** |
| known-zero | H_dfa | 0/5 | +0.4837 | ≤20% of draws | **PASS** |
| known-effect | VR(q=12) | 5/5 | +0.3546 | ≥80%, reverting sign | **PASS** |
| known-effect | ρ(1) | 5/5 | −0.1142 | ≥80%, reverting sign | **PASS** |
| known-effect | H_dfa | 5/5 | +0.1968 | ≥80%, reverting sign | **PASS** |

The known-zero world is a sign-randomised permutation of the *real* magnitudes; the
known-effect world is an OU log-price with a 3-bar half-life and the real empty-bar pattern
imposed, so a green effect control cannot be an artifact of missingness. The test suite adds a
third world of the opposite sign — fractionally integrated noise at d = 0.3, true H = 0.80 — so
"detects reversion" cannot be satisfied by an estimator that always reports reversion.

### 4.1 The control caught a real bug in this study's own code

The first implementation of the heteroskedasticity-robust statistic multiplied by `√n` on top of
a `θ̂` that already carries the `1/n`. Result: **the "robust" statistic rejected a pure
martingale difference 94.2% of the time**, against 7.5% for the homoskedastic statistic it is
supposed to be *more* conservative than. Had it shipped, every series here would have come back
violently significant in whichever direction its point estimate leaned — and every point estimate
here leans reverting. The correct form is `z* = (VR − 1)/√θ̂`, whose sanity anchor is that on iid
data `θ̂ → V_homo/n` and `z*` collapses onto `z`. A single green zero-control would not have
caught it; the *size* check over repeated draws did.

---

## 5. Variance ratios

Hourly grid. `null µ` is the mean of the wild-bootstrap null — **the value a random walk with
this series' own volatility path actually produces**; `shuf µ` is the same null after permuting
the magnitudes in time. `MDE` is the smallest true VR detectable at 80% power, measured from
where the null sits. `spans` is the number of non-overlapping q-hour windows.

**weave/SOL** (n = 245, 10.21d)

| q (h) | VR | null µ | shuf µ | z_homo | z* | p_boot | spans | MDE | detectable half-life | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 0.949 | 0.970 | ~1.00 | −0.80 | −0.35 | 0.933 | 122.5 | 0.575 | 0.4h | random walk |
| 3 | 0.844 | 0.946 | ~1.00 | −1.64 | −0.74 | 0.732 | 81.7 | 0.407 | 0.4h | random walk |
| 6 | 0.734 | 0.838 | ~1.00 | −1.69 | −0.88 | 0.674 | 40.8 | 0.341 | 1.1h | random walk |
| 12 | 0.628 | 0.798 | ~1.00 | −1.55 | −1.00 | 0.591 | 20.4 | 0.133 | 0.7h | random walk |
| 24 | 0.533 | 0.817 | ~1.00 | −1.33 | −1.08 | 0.461 | 10.2 | **−0.136** | **none** | **UNRESOLVABLE** |
| 48 | 0.461 | 0.797 | ~1.00 | −1.07 | −1.06 | 0.487 | 5.1 | **−0.477** | **none** | **UNRESOLVABLE** |
| 72 | 0.607 | 0.817 | ~1.00 | −0.63 | −0.67 | 0.796 | 3.4 | **−0.714** | **none** | **UNRESOLVABLE** |

**weave/nosis** (n = 116, 4.83d)

| q (h) | VR | null µ | z* | p_boot | spans | MDE | detectable | verdict |
|---|---|---|---|---|---|---|---|---|
| 2 | 1.085 | 1.005 | +0.99 | 0.373 | 58.0 | 0.761 | 1.1h | random walk |
| 6 | 0.773 | 0.980 | −0.90 | 0.512 | 19.3 | 0.253 | 0.6h | random walk |
| 12 | 0.665 | 0.977 | −0.88 | 0.508 | 9.7 | −0.127 | none | **UNRESOLVABLE** |
| 24 | 0.679 | 1.003 | −0.61 | 0.701 | 4.8 | −0.602 | none | **UNRESOLVABLE** |
| 48 | 0.416 | 1.007 | −0.84 | 0.576 | 2.4 | −1.204 | none | **UNRESOLVABLE** |
| 72 | 0.156 | 0.986 | −1.01 | 0.234 | 1.6 | −1.149 | none | **UNRESOLVABLE** |

That last row is the study in miniature. VR = 0.156 is a spectacular-looking reversion. There
are **1.6** independent three-day windows in the sample, the null's own 5–95% band is
[0.223, 2.571], and the bootstrap p is 0.234.

**weave/SOLVE** (n = 245, 10.21d)

| q (h) | VR | null µ | z* | p_boot | MDE | detectable | verdict |
|---|---|---|---|---|---|---|---|
| 6 | 0.738 | 0.846 | −0.90 | 0.616 | 0.358 | 1.1h | random walk |
| 12 | 0.627 | 0.816 | −1.04 | 0.517 | 0.154 | 0.9h | random walk |
| 24 | 0.531 | 0.808 | −1.12 | 0.447 | −0.096 | none | **UNRESOLVABLE** |
| 48 | 0.542 | 0.815 | −0.93 | 0.622 | −0.449 | none | **UNRESOLVABLE** |
| 72 | 0.703 | 0.861 | −0.52 | 0.957 | −0.813 | none | **UNRESOLVABLE** |

**DREGG/SOL** (n = 1,140, 47.50d) — the longest series in the cluster

| q (h) | VR | null µ | shuf µ | z_homo | z* | p_boot | spans | MDE | detectable | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 1.064 | 1.000 | ~1.00 | **+2.15** | +0.69 | 0.525 | 570.0 | 0.744 | 1.0h | random walk |
| 3 | 1.049 | 0.999 | ~1.00 | +1.12 | +0.37 | 0.582 | 380.0 | 0.623 | 1.2h | random walk |
| 6 | 0.985 | 0.984 | ~1.00 | −0.20 | −0.07 | 0.816 | 190.0 | 0.416 | 1.5h | random walk |
| 12 | 0.811 | 0.970 | 0.996 | −1.70 | −0.67 | 0.707 | 95.0 | 0.171 | 1.0h | random walk |
| 24 | 0.972 | 0.911 | 1.000 | −0.17 | −0.07 | 0.553 | 47.5 | −0.127 | none | **UNRESOLVABLE** |
| 48 | 0.875 | 0.789 | 1.014 | −0.53 | −0.25 | 0.558 | 23.8 | −0.141 | none | **UNRESOLVABLE** |
| 72 | 0.819 | **0.735** | **1.000** | −0.63 | −0.31 | 0.578 | 15.8 | −0.119 | none | **UNRESOLVABLE** |

Read the last row across. VR = 0.819 looks like reversion. The null for this series at this
horizon is centred on **0.735** — so 0.819 is *above* what a random walk produces here, and the
bootstrap p is 0.578. The asymptotic statistic, which assumes the null is centred on 1, reports
z* = −0.31 in the reverting direction. The next section is about that gap.

### 5.1 The homoskedastic statistic would have produced a paper

Counting variance-ratio statistics clearing |z| > 1.96:

| family | homoskedastic z | robust z* |
|---|---|---|
| confirmatory, hourly (28 statistics) | **1** | **0** |
| exploratory, 5-minute (32 statistics) | **16** | **1** |

**Sixteen of thirty-two versus one of thirty-two.** Half the 5-minute variance ratios look
significant under the textbook statistic. Anyone reporting VR point estimates with it on this
data would have written up a comprehensive, entirely spurious mean-reversion result. The single
robust survivor — DREGG/SOL at q = 15 min, z* = −1.99 — has a *bootstrap* p of 0.052, is rank 1
of 32 under BH with a threshold of 0.0031, and is separately accounted for by the measured
bid-ask bounce in §9.

### 5.2 …and the robust statistic is not enough either: the volatility-profile bias

The heteroskedasticity-robust `z*` fixes the *variance* of the null. It does not fix its
*centre*, and on a young memecoin the centre moves a long way.

Measured directly, on each SOL-quoted leg, as the mean of the wild-bootstrap null with the
magnitude sequence **in place** versus **permuted in time** (identical magnitudes, identical
marginal distribution, only the temporal profile of volatility destroyed):

| series | q=12 | q=24 | q=48 | q=72 | first/last decile vol |
|---|---|---|---|---|---|
| dregg_per_sol | 0.990 → 0.996 | 0.866 → **1.000** | 0.796 → **1.014** | **0.712** → **1.000** | 5.39× |
| weave_per_sol | 0.784 → **0.995** | 0.782 → **1.001** | 0.819 → 0.985 | 0.824 → **1.013** | 4.75× |
| solve_per_sol | 0.889 → 0.988 | 0.872 → **1.006** | 0.865 → **1.027** | 0.793 → **1.003** | 4.37× |
| **sol_per_usd** | 1.002 → 0.999 | 0.997 → 0.989 | 1.002 → 0.995 | 1.019 → 0.994 | **1.29×** |

The attribution is complete and unambiguous. Shuffling the same magnitudes returns the null to
1.000 in every case, and SOL/USD — a mature asset whose volatility is flat across the sample —
never leaves 1 to begin with. The mechanism is that the overlapping variance-ratio estimator
underweights returns near the sample boundary (return `t` appears in `min(t, q, n−t+1)` windows),
and a post-launch token has its largest moves at exactly that boundary.

Two checks on the claim:

- **The estimator itself is unbiased.** On iid Gaussian data at n = 245/580/1140 and
  q = 12…72 the null mean is 0.98–1.03, and on synthetic clustered fat-tailed data 0.99–1.06.
  Nothing is wrong with the implementation; the bias lives in the data.
- **A smooth volatility ramp is not enough to produce it.** Independent returns with a
  monotone 30× decline give VR(72) = 0.918; a 10× ramp gives 0.969. The real series reach
  0.71–0.82 at decile ratios of only 4.4–5.4×. It is the *burstiness* — a few enormous moves
  concentrated in the first days — not the smooth trend, that does the damage.

**Consequence, and it is the reason this study's verdicts are what they are:** the asymptotic
Lo-MacKinlay p-value is anti-conservative in the reverting direction on any post-launch memecoin
series, by an amount that grows with the horizon. Only the simulated null is valid. Everything
corrected in §12 uses the bootstrap p-value, and PROGRAM.md §3's "report the null distribution
for every statistic" is the rule that caught it.

This is the same disease PROGRAM.md §3 already documents for Hawkes estimation —
*"non-stationarity pushes it up — concatenated pure-Poisson segments with a varying baseline
yield n̂ ≈ 1 from true zero"* — in a different estimator, pushing the other way. **It should be
assumed to affect any second-moment statistic computed on a token's first weeks**, including
anything the replay harness computes over a launch window.

---

## 6. What this sample could have detected

`MDE` above is the smallest *true* variance ratio distinguishable from a random walk at 80%
power, measured from where the null actually sits (`1 − 2.80·sd/µ_null`), then inverted through
`VR(q) = (1 − φ^q)/(q(1 − φ))` to a mean-reversion half-life. "none" means the MDE fell at or
below `1/q`, the floor a perfectly reverting process produces.

| pair \ horizon | 6h | 12h | **24h** | **48h** | **72h** |
|---|---|---|---|---|---|
| weave/SOL | 1.1h | 0.7h | **none** | **none** | **none** |
| weave/nosis | 0.6h | **none** | **none** | **none** | **none** |
| weave/SOLVE | 1.1h | 0.9h | **none** | **none** | **none** |
| DREGG/SOL | 1.5h | 1.0h | **none** | **none** | **none** |
| *DREGG/SOLVE (§10)* | *2.3h* | *2.8h* | *2.2h* | *none* | *none* |

**No pair the operator trades has any day-scale power at all.** Even DREGG/SOL, with 47.5 days
and 1,140 hourly returns, could not have detected reversion of any speed at 24 hours — because
its null is displaced to 0.911–0.735 there by the volatility profile, and the displacement eats
the entire detectable range. Reversion with a 6-hour half-life, the kind of thing the desk
believes in, would have been invisible on every one of the four pairs at every horizon of 12
hours or more.

An earlier draft of this document reported DREGG/SOL as able to detect an 8.5-hour half-life at
72 hours. That was computed by centring the MDE on 1 instead of on the measured null, and it was
wrong by the exact size of the §5.2 bias. It is recorded here because it is the mistake this
study is most likely to be repeated by.

---

## 7. Hurst — three estimators, and the reason for three

Hourly grid, null simulated at **this** sample's length, per Weron.

| pair | L | DFA | R/S | GPH | wild-null sd (DFA / R/S / GPH) |
|---|---|---|---|---|---|
| weave/SOL | 245 | 0.456 | 0.568 | 0.362 | 0.087 / 0.049 / 0.185 |
| weave/nosis | 116 | 0.446 | 0.585 | 0.315 | 0.118 / 0.081 / 0.303 |
| weave/SOLVE | 245 | 0.453 | 0.533 | 0.371 | 0.076 / 0.047 / 0.194 |
| DREGG/SOL | 1,140 | 0.492 | 0.525 | **0.825** | 0.061 / 0.029 / 0.196 |

**Every one is inside its own null.** The largest wild-bootstrap p is 0.90, the smallest 0.092.

**R/S does not sit at 0.5 on noise.** Its white-noise null *mean* at our lengths is 0.590
(L = 245), 0.605 (L = 116), 0.582 (L = 245), 0.565 (L = 1,140). Every raw R/S number in the
table — 0.533 to 0.585 — reads as "trending" against 0.5, and every one is at or *below* its
own null. Three of the four move to the reverting side once the null is respected. This is why
the null is simulated at each L instead of comparing to a half.

**GPH produced the only nominally significant statistic in the study, and it is exactly the one
Weron says not to trust.** DREGG/SOL reads H = 0.825 with a white-noise null p of 0.012 —
*trending*, the opposite of the thesis. It dies three ways: against the
heteroskedasticity-preserving wild null it is p = 0.092; it is rank 1 of 52 under BH-FDR with a
threshold of 0.0019; and DFA and R/S on the identical series read 0.492 and 0.525. Weron's
measured white-noise standard deviation for GPH at L = 1024 is 0.14 against 0.05–0.07 for
DFA/R/S; ours at L = 1,140 is 0.123 against 0.039 and 0.029 — a clean reproduction of his result
on our own code.

Detectable |H − 0.5| at 80% power: DREGG/SOL 0.170 (DFA), 0.081 (R/S), 0.549 (GPH);
weave/nosis 0.331, 0.226, **0.848**. A GPH Hurst exponent on 116 hourly bars is not a
measurement.

---

## 8. Return autocorrelation

Hourly returns, wild-bootstrap null band (95%) and stationary-block-bootstrap CI.

| pair | lag | ρ | null 95% | block-boot CI | p | spans | MDE |
|---|---|---|---|---|---|---|---|
| weave/SOL | 1h | −0.035 | [−0.273, +0.270] | [−0.129, +0.090] | 0.848 | 245 | ±0.416 |
| weave/SOL | 6h | −0.000 | [−0.082, +0.076] | [−0.070, +0.071] | 0.954 | 40.8 | ±0.114 |
| weave/SOL | 24h | +0.016 | [−0.110, +0.105] | [−0.098, +0.143] | 0.760 | 10.2 | ±0.159 |
| weave/nosis | 1h | +0.066 | [−0.176, +0.150] | [−0.077, +0.145] | 0.389 | 116 | ±0.234 |
| weave/nosis | 6h | −0.043 | [−0.134, +0.118] | [−0.145, +0.082] | 0.595 | 19.3 | ±0.185 |
| weave/nosis | 24h | −0.007 | [−0.116, +0.099] | [−0.144, +0.164] | 0.999 | 4.8 | ±0.156 |
| weave/SOLVE | 1h | −0.051 | [−0.270, +0.264] | [−0.144, +0.054] | 0.774 | 245 | ±0.395 |
| weave/SOLVE | 6h | −0.021 | [−0.092, +0.091] | [−0.099, +0.079] | 0.714 | 40.8 | ±0.136 |
| weave/SOLVE | 24h | +0.022 | [−0.105, +0.097] | [−0.102, +0.124] | 0.656 | 10.2 | ±0.151 |
| DREGG/SOL | 1h | +0.065 | [−0.183, +0.174] | [−0.122, +0.162] | 0.520 | 1140 | ±0.263 |
| DREGG/SOL | 6h | **−0.074** | [−0.093, +0.093] | [−0.118, +0.033] | 0.136 | 190 | ±0.133 |
| DREGG/SOL | 24h | **−0.102** | [−0.135, +0.126] | [−0.114, +0.047] | 0.178 | 47.5 | ±0.207 |

The two largest values in the study are DREGG/SOL at 6h (−0.074) and 24h (−0.102). Both sit
inside their null bands, both have block-bootstrap CIs straddling zero, and both rank 2nd and
4th of 52 under BH with thresholds of 0.0038 and 0.0077.

Note the null bands *widen* at short lags rather than narrowing — the 1-hour band on weave/SOL is
[−0.273, +0.270] on 245 observations, four times the 1/√n ≈ 0.064 a Bartlett band would draw.
That width is the fat tails and volatility clustering carried into the null, which is what the
wild bootstrap is for. A textbook band would have called weave/nosis's +0.066 at 1h significant.

---

## 9. The bid-ask-bounce control

GeckoTerminal closes are **trade** prices, which bounce across the fee and manufacture exactly
the negative serial correlation this study is looking for. The chain tape's marginal price has
no bounce by construction. Same window, same grid:

| series | grid | ρ₁ trade price | n | ρ₁ chain marginal | n | bounce contribution |
|---|---|---|---|---|---|---|
| dregg_per_sol | 60s | −0.011 | 644 | +0.006 | 658 | −0.017 |
| dregg_per_sol | 300s | **−0.085** | 130 | **+0.021** | 132 | **−0.105** |
| solve_per_sol | 60s | −0.019 | 1,761 | +0.008 | 1,761 | −0.027 |
| solve_per_sol | 300s | −0.016 | 353 | −0.006 | 353 | −0.010 |
| nosis_per_sol | 60s | −0.149 | 387 | **−0.133** | 388 | −0.016 |
| nosis_per_sol | 300s | −0.158 | 77 | **−0.154** | 78 | −0.004 |
| weave_per_sol | 60s | +0.147 | 378 | +0.148 | 383 | −0.001 |

1. **The one robust exploratory result is bounce.** DREGG's 5-minute trade-price series carries
   ρ₁ = −0.085 that is absent from the marginal price. A pure MA(1) bounce of that size implies
   `VR(q) ≈ 1 + 2ρ₁(1 − 1/q)` = **0.86 at q = 3**, and the measured 5-minute VR(15min) for
   DREGG/SOL is 0.919. The bounce accounts for all of it. The single statistic that survived the
   robust z at 5-minute sampling (z* = −1.99, bootstrap p = 0.052, dead at BH) is microstructure.
2. **nosis's short-horizon reversion is real.** ρ₁ = −0.133 in the *marginal* price at 1-minute
   sampling, essentially unchanged from the trade price. Genuine impact-decay microstructure in
   the busiest pool in the cluster (6,951 trades/day) — a minute-scale phenomenon with no
   bearing on a day-scale LP thesis.
3. **weave trends at one minute** (ρ₁ = +0.147 in both series), the opposite sign from the
   thesis and again microstructure.

Caveat: the overlap window is ~1.5 days and n runs from 77 to 1,761. Directional diagnostics
sized well enough to explain a 5-minute artifact, not measurements in their own right.

---

## 10. The desk's one prior positive reversion claim does not replicate

`RESULT_swing_cluster.md` reported DREGG/SOLVE at AR(1) ρ̂ = 0.901, Kendall-debiased 0.908,
half-life 6.6 → 7.2 hours over n = 499 hourly bars, and called it **"robust reversion"** — the
only positive reversion result this desk has, and the basis for the recommendation to seed a
DREGG/SOLVE pool. It carried no null: ρ̂ was compared with 1 by eye.

That comparison is not valid. **The OLS AR(1) coefficient is biased downward on a random walk**,
severely and asymmetrically — the entire content of the Dickey–Fuller literature — so a number
below 1 says nothing until you know what a unit root produces at that n.

| | prior study | this study |
|---|---|---|
| n (hourly bars) | 499 | **581** |
| span | 20.8d | **24.17d** |
| ρ̂ | 0.901 | **0.9739** |
| ρ̂ debiased (Kendall) | 0.908 | **0.9807** |
| implied half-life | 6.6 → 7.2h | **26.2h** |
| random-walk null | *not computed* | median **0.9890**, 5th pct **0.9669** |
| one-sided p vs that null | — | **0.103** |
| verdict | "robust reversion" | **INDISTINGUISHABLE-FROM-RANDOM-WALK** |

The point estimate does not reproduce on a longer, heavily overlapping window (0.901 → 0.974),
and the reproduced value sits inside the simulated null. Why the two differ is **not resolved
here** — candidates are a different treatment of empty hours (dropping rather than
forward-filling shortens the effective sampling interval and biases ρ̂ down), a USD- rather than
SOL-denominated series, or a different pool for one leg. Whichever it is, the claim as written
is not supported by the data now in the cache.

**But the variance ratios on the same pair are the strongest evidence in the study**, and they
must be reported even though they were not what this test was looking for:

| q (h) | VR | null µ | z* | p_asym | **p_boot** | spans | MDE | detectable |
|---|---|---|---|---|---|---|---|---|
| 2 | 0.857 | 0.962 | −2.35 | 0.019 | 0.088 | 290.0 | 0.819 | 1.5h |
| 3 | 0.697 | 0.950 | **−3.21** | **0.0013** | **0.011** | 193.3 | 0.722 | 1.9h |
| 6 | 0.575 | 0.944 | −2.69 | 0.007 | 0.035 | 96.7 | 0.531 | 2.3h |
| 12 | 0.481 | 0.934 | −2.37 | 0.018 | 0.057 | 48.3 | 0.362 | 2.8h |
| 24 | 0.389 | 0.927 | −2.11 | 0.035 | 0.079 | 24.2 | 0.154 | **2.2h** |
| 48 | 0.247 | 0.902 | −1.88 | 0.060 | 0.095 | 12.1 | −0.165 | none |
| 72 | 0.254 | 0.867 | −1.56 | 0.119 | 0.104 | 8.1 | −0.244 | none |

**DREGG/SOLVE is the only pair in the cluster with genuine 24-hour power** (it could have
detected a 2.2-hour half-life there) and it shows VR = 0.389 with a bootstrap p of 0.079.
Within its own 8-test family, BH rejects exactly one hypothesis: VR at q = 3h. Charged to the
confirmatory budget as a 60-hypothesis family, **nothing survives**.

**And the effect is not a property of the pair.** Running the same variance ratios on each leg
separately:

| series | VR(3h) | z* | VR(6h) | z* | VR(24h) | z* |
|---|---|---|---|---|---|---|
| **SOLVE/SOL alone** | **0.626** | **−3.77** | **0.490** | **−3.07** | **0.339** | **−2.23** |
| DREGG/SOL alone | 1.049 | +0.37 | 0.985 | −0.07 | 0.972 | −0.07 |
| DREGG/SOLVE | 0.697 | −3.21 | 0.575 | −2.69 | 0.389 | −2.11 |

**SOLVE/SOL on its own is stronger than the pair.** So this is not two community tokens
reverting toward each other — it is SOLVE's own SOL price reverting at short horizons, and the
DREGG leg dilutes rather than creates it. SOLVE is the thinnest pool in the cluster ($14,766 of
liquidity, 136 trades/day, 60% of its 5-minute bars forward-filled), so thin-pool impact decay
is the leading explanation and a genuine ratio relationship is not.

For completeness: **SOL/USD itself** shows VR(6h) = 0.784 with z* = −2.52 over 1,998 hourly bars
in a $26M pool with a flat volatility profile and no bounce. Either major-asset intraday
reversion is real at this horizon, or a residual bar-construction artifact affects everything
here. That is unresolved and worth its own look before anyone trades a reversion signal.

One direction must be flagged on the AR(1) null: observation noise biases the coefficient
*down*, and the null contains none, so it is **anti-conservative** — it makes reversion easier
to claim, not harder. §9 sizes that noise at ρ₁ ≈ −0.105 on DREGG's 5-minute returns, scaling to
roughly −0.009 at hourly, too small to manufacture a 7-hour half-life on its own.

---

## 11. The memecoin–SOL correlation and the quote-asset break-even

`RESULT_lp_literature.md` §4: `σ²_ratio = σ_A² + σ_B² − 2ρσ_Aσ_B`, LVR ∝ σ²_ratio, so quoting
against SOL rather than a stablecoin reduces adverse selection **iff ρ > σ_SOL/(2σ_meme)** — and
at the literature's assumed σ_meme = 200%/yr, σ_SOL = 80%/yr that break-even is ρ ≈ 0.20.

Measured on the hourly grid against a $26M Orca SOL/USDC pool:

| token | n | span | σ_meme | σ_SOL | **break-even ρ\*** | measured ρ | ρ 95% CI | variance change | side |
|---|---|---|---|---|---|---|---|---|---|
| weave | 245 | 10.2d | 23.26%/h (2,178%/yr) | 0.390%/h (36.5%/yr) | **0.008** | −0.020 | [−0.165, +0.126] | **−0.10%** | fails |
| nosis | 116 | 4.8d | 32.73%/h (3,065%/yr) | 0.374%/h (35.0%/yr) | **0.006** | −0.064 | [−0.165, +0.083] | **−0.16%** | fails |
| DREGG | 1,140 | 47.5d | 10.00%/h (936%/yr) | 0.491%/h (46.0%/yr) | **0.025** | +0.044 | [−0.033, +0.128] | **+0.19%** | passes |
| SOLVE | 580 | 24.2d | 10.79%/h (1,010%/yr) | 0.427%/h (40.0%/yr) | **0.020** | +0.035 | [−0.022, +0.097] | **+0.12%** | passes |

**The literature's ρ ≈ 0.20 break-even does not apply to these tokens and is wrong by an order
of magnitude, in the direction that makes the question moot.** It assumes σ_meme = 200%/yr.
These four run **936% to 3,065%/yr** — 5–15× that — so the break-even is 0.006–0.025, not 0.20.
DREGG and SOLVE clear theirs; weave and nosis miss theirs. Every measured ρ has a 95% CI
straddling zero, so none of the four correlations is itself distinguishable from zero.

**The honest headline is that the choice does not matter.** The last column is what the LP
actually cares about — the change in the pool's price variance, hence in LVR, from quoting in
SOL instead of dollars — and it runs from **−0.16% to +0.19%**, with bootstrap CIs spanning
roughly ±0.5%. The reason is structural and independent of the correlation estimate: the effect
is bounded by about `(σ_SOL/σ_meme)²`, and at these volatilities that ratio is 0.012–0.049, so
its square is at most a quarter of one percent. Whatever the numeraire question is worth on a
blue-chip pair, on a token 20–80× more volatile than SOL it is rounding error.

Two properties worth recording. The correlation form and the direct variance comparison are
algebraically the same test — `Var[r_usd] − Var[r_sol] = σ_SOL² + 2Cov[r_sol, r_SOL/USD]` — so
disagreement would mean the code is wrong; they agree on all four. And the bid-ask bounce
attenuates the reported ρ while dividing the break-even ρ\* by the identical factor, so **the
pass/fail decision is bounce-robust while the reported ρ is a lower bound** on the true
correlation. Neither number should be quoted alone.

---

## 12. FDR outcome

| family | hypotheses | q | rejected | smallest p |
|---|---|---|---|---|
| confirmatory (hourly): 4 pairs × (7 VR + 3 Hurst + 3 ACF) | **52** | 0.10 | **0** | 0.092 (H_gph, DREGG/SOL) |
| exploratory (5-minute): 4 pairs × 8 VR | **32** | 0.10 | **0** | 0.052 (VR 15min, DREGG/SOL) |
| replication (§10): DREGG/SOLVE, 7 VR + 1 AR(1) | **8** | 0.10 | **1** (VR q=3h) | 0.011 |
| replication charged to the confirmatory budget | **60** | 0.10 | **0** | 0.011 |

The 5-minute family's smallest p is explained by the measured bid-ask bounce (§9). The
replication family's single survivor is a 3-hour horizon on a pair that is not traded, and is
stronger in the SOLVE leg alone than in the pair (§10).

BH assumes positive dependence across a family whose members (VR at 2h and 3h on one series)
are strongly dependent. With zero rejections in the pre-registered families the correction is
not load-bearing; it would be if anything were near threshold.

---

## 13. Falsification matrix

Every control has a deliberately broken estimator and a test that the control **fails** against
it. A test that cannot fail is not evidence. All 19 mutations behave as required.

| # | mutation | control it must break | result |
|---|---|---|---|
| 1 | VR hard-coded to 1 | known-effect VR (OU) | FAILS ✓ |
| 2 | VR hard-coded to 1 | known-effect VR (long memory) | FAILS ✓ |
| 3 | Lo-MacKinlay `m` correction dropped | known-zero VR (null no longer centred on 1) | FAILS ✓ |
| 4 | H hard-coded to 0.5 | known-effect Hurst (OU) | FAILS ✓ |
| 5 | H hard-coded to 0.5 | known-effect Hurst (long memory) | FAILS ✓ |
| 6 | log price fed where returns expected | known-zero Hurst | FAILS ✓ |
| 7 | ρ hard-coded to −0.5 | known-zero autocorrelation | FAILS ✓ |
| 8 | ρ hard-coded to 0 | known-effect autocorrelation | FAILS ✓ |
| 9 | mean not subtracted | ACF-removes-the-mean (drifting series) | FAILS ✓ |
| 10 | wild bootstrap resamples with replacement | preserves-volatility check | FAILS ✓ |
| 11 | wild bootstrap does not randomise | randomises check | FAILS ✓ |
| 12 | block length forced to 1 | preserves-clustering check | FAILS ✓ |
| 13 | raw p ≤ q, no BH step-up | FDR control under a complete null | FAILS ✓ |
| 14 | procedure never rejects | BH power check | FAILS ✓ |
| 15 | homoskedastic z in the robust slot | robust-beats-homoskedastic size check | FAILS ✓ |
| 16 | **the time-shuffle leaves the order untouched** | **volatility-profile diagnostic (§5.2)** | FAILS ✓ |
| 17 | AR(1) ρ fixed at 1 | known-effect replication test | FAILS ✓ |
| 18 | AR(1) ρ fixed at 0.5 | known-zero replication test | FAILS ✓ |
| 19 | break-even comparison inverted | quote-asset direction check | FAILS ✓ |

**Three checks could not be falsified and were rewritten. That is the most useful output of
building the matrix.**

- **The zero-world checks were pure self-consistency.** Their only assertion was `p > 0.05` from
  a bootstrap computed with the *same* estimator on both sides — which any estimator passes,
  however wrong, because a constant estimator's null is also constant. They now also assert
  where the statistic sits (the VR null must be centred on 1; |ρ| must be inside its own null
  width), which is what makes mutations 3, 6 and 7 detectable at all.
- **Removing DFA's local detrending was not a falsification.** Detrending changes the constant
  in `F(s)`, not the exponent, so DFA-0 still reads H = 0.5 on a random walk. The mutation that
  does break it is feeding the log price where returns are expected (#6) — also the commonest
  way a Hurst exponent gets misused in practice.
- **An uncentred autocorrelation did not break the zero-world ACF check**, because those returns
  are already near-zero-mean. It needed a dedicated drifting-series control (#9).

The suite also runs the study's own `run_controls` end to end and asserts **both** worlds pass;
runs `run_study` end to end on a synthetic cache and asserts the FDR family is built from the
**bootstrap** p-values; and machine-checks that no control exists without a matching mutation.

**Reproducibility.** 59 tests, all passing. Two `--quick` runs at the same seed produce
byte-identical `results.json`; a different seed changes the nulls, so the determinism is real
rather than a frozen cache. Adding the §10 replication changed *nothing* elsewhere in the
output, which is the design working: every null draw is keyed by a stable digest of its own
name, so extending the study cannot silently perturb a result already reported.

**Gate status at the time of writing.** `scripts/check.sh` fails, and none of it is this lane:
188 ruff findings across `scripts/lp/*`, `studies/deterioration.py`, `studies/circuit_theory.py`,
`shitcoims_tape/__init__.py` and `tests/test_scalper.py`; one failing test in
`tests/test_netmap.py`; and the Lean axiom audit naming three theorems
(`exposure_monotone`, `tripped_breaker_admits_nothing`, `tripped_breaker_is_absorbing`) that no
longer exist in the kernel. The three files added here are ruff-clean and all 1,055 other tests
pass.

---

## 14. What the data cannot support

1. **No day-scale statement about any of the four traded pairs, in either direction.** §6: at
   24 hours and beyond the detectable effect is below the estimator's floor on all four. This is
   not a weak negative; it is *no measurement*.
2. **No refutation of reversion at any speed at the day scale.** The strongest thing this study
   rules out is reversion faster than ~1 hour on weave/SOL, weave/SOLVE and DREGG/SOL at 6–12h.
3. **No statement about the direct token-token pools.** Both DLMMs are hours old. The ratios
   here come from the deep SOL legs; the LP position and the measurement sit on different venues
   related by arbitrage, not identity.
4. **Trade prices, not marginal prices, at hourly resolution.** §9 sizes the bounce as
   immaterial at hourly and material at 5-minute, on a ~1.5-day overlap with n as low as 77.
5. **One regime.** 47 days at most, all of it 2026-06-27 → 2026-08-14, one community's tokens.
   PROGRAM.md §3.6: memecoin regimes shift in weeks. Nothing here is a prior for next month.
6. **The SOL/USD VR(6h) = 0.784, z* = −2.52 anomaly is unexplained** (§10). Until it is, a
   residual artifact affecting all second-moment statistics here cannot be excluded.
7. **Why the §10 point estimate differs from the prior study's is unresolved.** Three candidate
   explanations, none tested.
8. **Nothing here says whether LPing these pairs is +EV.** `RESULT_lp_literature.md` §0 is the
   binding correction: an LP breaks even under mean reversion and loses under drift, so *fees
   are the only thing that pays*. A reverting ratio would have meant the inventory leg does not
   hurt; it would never have meant the position earns. This study tested the premise, not the
   strategy.

---

## 15. What would settle it, in cost order

1. **Wait. It is free and it is the only input that matters.** Re-run this script at 90 days;
   it is deterministic and the fetcher is idempotent. Note that waiting fixes the §5.2 bias too,
   for a second reason: the launch volatility burst becomes a smaller fraction of the sample, so
   the null drifts back toward 1 and the detectable range reopens. **Set a reminder for
   2026-10-01 and spend nothing now.**
2. **Extend the chain tape to run continuously on the four SOL pools.** DREGG and SOLVE are
   136–425 transactions/day: a continuous recorder costs a few hundred credits a day, turns
   §9's 1.5-day n=77 diagnostic into a measurement, and builds the bounce-free marginal-price
   series that §14.4 wants. nosis at ~460k signatures/day stays out of reach and should be
   sampled, not tailed.
3. **Resolve the SOL/USD anomaly before anything else is built on a variance ratio.** It is one
   series, already cached, and it decides whether §10's residual signal is a market fact or an
   instrument fact.
4. **Pool the pairs hierarchically** rather than testing four short series one at a time — the
   regime PROGRAM.md §1.5 says loses to partial pooling by 5× in precision. Pesaran–Smith
   applies (the slopes are heterogeneous), so this is the Swamy random-coefficients route, not
   naive pooling.
5. **Do not spend the credit budget on this question.** It buys resolution; the constraint is
   span. It is the right budget for a question about *cross-sectional breadth* — the co-trading
   and funding-tree signals in PROGRAM.md §4 — where more addresses genuinely is more
   information.
