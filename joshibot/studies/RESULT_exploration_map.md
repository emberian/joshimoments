# RESULT: the map — which stream knows what about which future, and what it is worth

2026-08-15. `studies/exploration_map.py`. A pre-declared grid of **542 cells** over
(stream-feature × target × horizon × cohort), every cell measured with the same dependence
machinery, every cell counted against one Benjamini-Yekutieli budget, every survivor
translated into a round-trip friction it would have to beat.

**539 cells evaluable. 8 survive FDR at q = 0.10. None of them clears friction.**

The map is not all-null, and the shape of what survived is the finding: **these streams know
a great deal about whether a coin will still be visible, and almost nothing about what its
price will do.** Five of the eight survivors are exit-or-death targets. Exactly one return
cell survives every gate — FDR, all three honest nulls, a split-half sign test, and a disjoint
hold-out — and its top decile **loses 0.21% in five minutes**. It beats a coin drawn at random
from the same board by 1.42 percentage points, because that coin loses 1.63%. It is real,
replicated at p = 0.005 out of sample, and it is information about *how fast you lose*, not
about how to win.

**No cell on the map clears friction.** The best breakeven anywhere is 1.93% against the
desk's one measured round trip of 2.26%, and that cell fails stability at 73% censoring. The
best breakeven among survivors is 1.11%, half the friction.

---

## 0. Why a map and not a ninth hypothesis

Every study in this repo so far tested ONE hypothesis against ONE dataset, and eight
consecutive strategy studies came back null. This one asks the prior question — *which
observable stream carries how much information about which future, at which horizon* — so the
next round starts from a map instead of a guess.

The design constraint that mattered most: **an all-null map had to be reachable.** Nothing
here can manufacture a winner out of a large search, because the size of the search is an
input to the correction, and the correction is applied to every declared cell including the
three that came back unevaluable. The repo's two tombstones are built into the machinery
rather than mentioned in the caveats — `RESULT_copytrading.md`, where an i.i.d. null
manufactured a 73× effect that a rotation null killed, and `RESULT_bandit_search.md`, where a
1,458-cell search manufactured a +6% winner from noise at p = 0.455 on permuted worlds.

## 1. What is on the map

| cohort | what it is | mints | instants | grid | features | targets |
|---|---|---|---|---|---|---|
| `dexpool` | graduated DEX pools, hourly, 53.7 days | 110 | 1289 | 1h | 14 | 3 |
| `frozen` | all-time reply boards — **NEGATIVE CONTROL**, near-dead | 98 | 1200 | 30s | 17 | 5 |
| `hot` | recently-traded board: fresh, violent, high churn | 1050 | 1200 | 30s | 19 | 7 |
| `live` | livestreaming board | 347 | 1200 | 30s | 18 | 7 |
| `mcap` | top-market-cap board: graduated, persistent | 79 | 1200 | 30s | 18 | 7 |
| `tape` | swap-level flow, 4 constant-product pools, 24h | 4 | 1436 | 1m | 10 | 3 |

`frozen` is the part of the design worth defending. The all-time reply-count boards hold the
same 50 coins all day and their prices barely move — the median member's price does not change
at all across ten hours, and the cohort's per-30s log-return standard deviation is 0.00016
against 0.198 on `hot`. We know a priori there is nothing there. It rides through the entire
grid as a cohort where a positive result would mean the machinery is broken, which is a
stronger check than any synthetic self-test because it runs on the real data through the real
pipeline. Two placebo FEATURES ride along in every cohort for the same reason: `plc_coin`, a
random constant per coin, and `plc_market`, a random series shared by every coin.

### Stream coverage — where the map has no data at all

| stream | rows | window | overlap with primary | verdict |
|---|---|---|---|---|
| `firehose_new_token` | 9,850 | 08-15 00:41 → 12:56 UTC | **0.00 h** | UNJOINABLE |
| `firehose_migration` | 272 | 08-15 00:48 → 12:56 UTC | **0.00 h** | UNJOINABLE |

The boards session runs 08-14 14:21 → 08-15 00:21 UTC; the firehose starts twenty minutes
after it ends. **The two collectors were never running at the same time**, so no launch-rate
or migration-rate feature can be joined to the boards panel. The market-state channel is
untested here rather than tested and null. This is an operational finding and the fix is
process supervision, not analysis.

`intelligence.sqlite3` holds 15,197 observations against **110,048 observation conflicts** —
consistent with the collector problems another agent is working; not used here.

## 2. Six defects found before any number was believed

### 2.1 The price basis embedded SOL/USD

`usd_market_cap` moved 1.41% across the window for reasons having nothing to do with any coin.
For coins still on the bonding curve the virtual reserves give an exact SOL-denominated cap
(`(vsol/1e9)/(vtok/1e6)*1e9`), reproducing `usd_market_cap` at an implied SOL/USD of p10 74.85
/ p50 75.14 / p90 75.56 over 145,833 rows. For **graduated** coins the same field is stale
garbage — implied SOL/USD runs from 6 to 1.1e6 — so their USD cap is deflated by the
cross-sectional median rate from the curve cohort at that instant. Everything downstream is
SOL-denominated.

### 2.2 The time axis had a 3.3-hour hole in it

The collector stopped between tape files. With the axis taken as the sorted observed instants,
"index + 10" means five minutes inside a session and three hours across the gap — every
forward return spanning the break silently mislabelled. The tape is split into contiguous
**sessions** with a uniform grid inside each, which makes the index arithmetic true by
construction and hands over a held-out window for free.

### 2.3 Entry priced at the instant the feature is read — worth ρ = −0.228 of pure fiction

This is the one that would have produced a headline. A trailing-return feature ending at *t*
and a forward return starting at *t* share the price `lp[t]`, once with each sign.
Microstructure bounce alone makes them dependent, and **none of the permutation nulls here can
see it**: xsec, rot and mint all break the coin's own pairing, so the artefact reads as
significant under every one of them.

On a pure random walk with bounce and no predictability whatsoever, the measured Spearman
between trailing and forward return is **−0.228**. Entering one grid step later takes it to
**−0.000**. That is a large, clean "mean reversion" finding made entirely of nothing. Every
forward return in this map is entered one grid step after the feature is observed — which is
also the only thing a desk can do, since you cannot trade on a price in the same instant you
learn it.

### 2.4 A median with no quorum rescaled a whole instant

One instant of 2,162 had exactly **one** bonding-curve member, with broken reserves, and the
"median" implied SOL price was that single coin: **$500,187**, which would have rescaled every
graduated coin's price at that instant. The deflator now requires a quorum of five and a
sanity band, else carries the last good rate.

### 2.5 Cohort membership leaked backwards in time

Membership was computed from a tape-wide map of which boards a coin was ever seen on. A coin
that first reached the market-cap board on day two therefore joined the `mcap` cohort on day
one — both a look-ahead and a silent mutation of a finished run's panels (`hot` moved
1050 → 1149 when the tape grew). Membership is now decided by the boards a coin was on
*during that session*.

### 2.6 A cohort vanished because a filter keyed on a metadata label

`state/bulk_history/` was re-pulled by another agent mid-study. Every row came back relabelled
`grade: "summary"` with `replay_sufficient: false`, while the vault pre/post balances stayed
fully intact. The tape filter required `grade == "replay"`, so the entire cohort silently
disappeared from the grid (542 → 512 cells) with no error. Filters now key on **the data the
computation needs** — two vault balances, positive — and validity is certified independently
by the price-basis check below. DLMM pools are excluded on a data-model fact (Meteora's price
is the active bin, not the vault ratio), not on a label.

> **Tape price basis.** Vault-derived one-minute returns vs returns implied by the *executed*
> swap prices on `nosis/SOL` over 5,897 consecutive pairs: correlation **0.724**, median
> absolute gap **0.172%**. The reserve defect in `RESULT_copytrading.md` §2 biases price
> LEVELS; every target here is a log ratio, in which a constant proportional offset cancels
> exactly.

## 3. What the nulls actually do, measured

Four nulls; the decision rule is the **max** of the honest ones — a cell must beat every null
that applies to it, not the friendliest.

| null | preserves | breaks |
|---|---|---|
| `iid` | marginals only | everything — DIAGNOSTIC ONLY, never decisive |
| `xsec` | the market factor exactly; the instant | which coin got which future |
| `rot` | every coin's own autocorrelation | the temporal alignment |
| `mint` | autocorrelation AND the market factor | the coin's link to its own future |

Measured false-positive rates on twelve independent worlds of pure independent random walks —
the hardest case, where in-sample dependence is guaranteed and real dependence is zero:

| null | rejects at p<0.05 |
|---|---|
| `iid` | **100%** |
| `xsec` | **100%** |
| `rot` | 33% |
| `mint` | 8% |
| **max(xsec, rot, mint)** — the decision rule | **8%** |

Two things follow. The i.i.d. null this repo has been burned by twice is not merely optimistic,
it is useless here. And the circular-rotation null is **anticonservative on non-stationary
targets**, because a circular shift is only a valid null under approximate stationarity and a
random walk is not stationary. Neither decides anything alone. The max rule inherits the best
behaviour of the set and keeps its power: it still rejects at p = 0.005 on a planted nonlinear
effect that Spearman cannot see at all (|ρ| = 0.014).

**On the live grid**, the same inflation is visible directly:

| null | rejects at p<0.05 | share |
|---|---|---|
| `iid` | 375 / 539 | 69.6% |
| `xsec` | 356 / 539 | 66.0% |
| `mint` | 209 / 496 | 42.1% |
| `rot` | 98 / 539 | 18.2% |
| **decision rule + BY** | **8 / 542** | **1.5%** |

## 4. The credibility checks, before the results

| check | result |
|---|---|
| `plc_coin` (random constant per coin), 32 cells | max dCor 0.226, **min q = 1.000, 0 survive** |
| `plc_market` (random series shared by all coins), 32 cells | max dCor 0.096, **min q = 1.000, 0 survive** |
| `frozen` negative-control cohort, 83 cells | **0 survive**, max dCor 0.946 |

The `frozen` result is the strongest evidence on this page that the machinery works. **The
eight largest dCor values in the entire 542-cell map are all in the dead cohort** — 0.946,
0.827, 0.801, 0.704, 0.604, 0.594, 0.571, 0.567 — and every one is annihilated by the nulls
(q = 0.90 to 1.000). Ranking by raw dependence would have "discovered" a monster signal in
coins that do not trade. In this data **raw dCor is anti-correlated with tradeable
information**, because degenerate, near-constant series produce the largest distance
correlations.

**One caveat, and the placebo is what exposes it.** Bits were computed with a k-NN (Kraskov)
estimator, bias-corrected against null draws. The largest MI excess anywhere among the 64
placebo cells is **3.691 bits**, on `mcap` / `plc_coin` → `fwd_8h` — a random constant that
knows nothing. The estimator is not robust to this panel's clustering (few coins, many rows
each). **Bits are reported as description only and are used for no inference here**; every
verdict rests on dCor against the nulls, where that same placebo sits at q = 1.000.

## 5. THE MAP — where information lives

Max dCor over the features in each block, and how many of its cells survive FDR.

| cohort | return | board exit | trading death |
|---|---|---|---|
| `dexpool` | 0.477 (**1**/42) | — | — |
| `frozen` | 0.801 (0/67) | — | 0.946 (0/16) |
| `hot` | 0.432 (**1**/75) | 0.293 (**2**/38) | 0.442 (**1**/19) |
| `live` | 0.412 (**1**/72) | 0.236 (0/36) | 0.534 (**1**/18) |
| `mcap` | 0.555 (0/72) | 0.502 (**1**/36) | 0.517 (0/18) |
| `tape` | 0.296 (0/30) | — | — |

Read this as the answer to *where could a strategy exist*. Information about **board exit and
trading death** is broad and strong; information about **return** is narrow, and where it
exists it is concentrated at the shortest horizon. The `tape` cohort — swap-level flow,
including a failed-attempt rate of 94.7% on `nosis` — contributes **nothing**, though with
four pools it is severely underpowered and that is a statement about the test, not the market.

### The eight survivors

| # | cohort | feature | target | dCor | ρ | q (BY) | cens | p_xsec | p_rot | p_mint |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hot` | `log_age_h` | `exit_2h` | 0.286 | −0.311 | **0.019** | 0% | 1e-5 | 1e-5 | 1e-5 |
| 2 | `hot` | `log_stale_s` | `fwd_5m` | 0.236 | −0.113 | **0.019** | 2% | 1e-5 | 1e-5 | 1e-5 |
| 3 | `live` | `log_stale_s` | `fwd_5m` | 0.328 | +0.011 | **0.037** | 3% | 1e-5 | 3e-5 | 1e-5 |
| 4 | `dexpool` | `ret_72h` | `fwd_24` | 0.380 | −0.112 | **0.098** | 73% | 1e-5 | 2.1e-4 | n/a |
| 5 | `hot` | `log_mcap_sol` | `exit_30m` | 0.207 | −0.219 | **0.098** | 0% | 1e-5 | 1.4e-4 | 3e-5 |
| 6 | `hot` | `ret_5m` | `dead_30m` | 0.150 | −0.170 | **0.098** | 8% | 2e-5 | 2.1e-4 | 1e-5 |
| 7 | `live` | `d_rank_5m` | `dead_30m` | 0.249 | −0.052 | **0.098** | 11% | 1e-5 | 2.1e-4 | 1e-5 |
| 8 | `mcap` | `log_age_h` | `exit_2h` | 0.359 | −0.385 | **0.098** | 0% | 1e-5 | 1e-5 | 1.2e-4 |

Five of eight are exit/death targets. Cell 3 (`live`) has ρ = +0.011 — no linear content at
all — and dCor 0.328; whatever it is, it is not monotone, which is exactly the case dCor was
chosen for and Spearman would have missed. Cell 4 carries **73% censoring** and should be read
as a lead, not a measurement.

## 6. The economic translation — nothing clears friction

Top-decile-by-feature portfolio, rebalanced each instant, held for the horizon. `cohort %` is
the comparator a desk actually has: a coin drawn at random from the same board at the same
instant. `breakeven` is the round trip the cell would have to beat.

| cohort | feature | target | trades | top % | cohort % | edge (pp) | breakeven | vs 2.26% | p_edge |
|---|---|---|---|---|---|---|---|---|---|
| `dexpool` | `rv_24h` | `fwd_24` | 1,724 | +1.93 | +0.09 | +1.84 | +1.93% | **no** | 0.001 |
| `frozen` | `log_mcap_sol` | `fwd_8h` | 2,390 | +1.90 | +0.19 | +1.71 | +1.90% | **no** | 0.001 |
| `hot` | `log_stale_s` | `fwd_5m` | 50,511 | **−0.21** | −1.63 | +1.42 | −0.21% | **no** | 0.001 |
| `dexpool` | `ret_72h` | `fwd_24` | 1,724 | +1.11 | +0.09 | +1.02 | +1.11% | **no** | 0.045 |
| `mcap` | `log_age_h` | `fwd_5m` | 6,846 | **+0.01** | −0.91 | +0.92 | +0.01% | **no** | 0.004 |
| `live` | `log_stale_s` | `fwd_5m` | 9,720 | +0.01 | −0.18 | +0.19 | +0.01% | **no** | 0.011 |
| `mcap` | `ret_5m` | `fwd_5m` | 6,725 | −6.18 | −0.93 | −5.24 | −6.18% | **no** | 1.000 |

*(This table prices the FDR survivors plus the strongest cells by raw dependence, so that an
all-null map would still say what the best-looking structure was worth. Most rows here —
including every `frozen` row and `mcap`/`log_age_h` — do **not** survive FDR.)*

**No cell on the map clears friction.** The best breakeven anywhere is 1.93% against a
measured 2.26% round trip — and that cell (`dexpool`/`rv_24h`) carries 73% censoring, fails
the split-half sign test, and does not survive FDR. Three of the eight survivors have a return
target and all three were priced:

| survivor | top % | edge (pp) | breakeven | split-half sign |
|---|---|---|---|---|
| `dexpool` / `ret_72h` → `fwd_24` | +1.11 | +1.02 | **+1.11%** | no |
| `live` / `log_stale_s` → `fwd_5m` | +0.01 | +0.19 | +0.01% | no |
| `hot` / `log_stale_s` → `fwd_5m` | **−0.21** | +1.42 | −0.21% | **yes** |

The best surviving breakeven is 1.11%, half the friction, and it is the one that fails
stability. The only survivor whose sign holds across halves has a *negative* absolute return.

The `hot`/`log_stale_s` row is the clearest statement of what this map found. Fifty thousand
trades, q = 0.019, replicated out of sample, stable across halves — and the top decile still
**loses 0.21%** in five minutes. The entire +1.42pp edge is the difference between losing 0.21%
and losing 1.63%. **On the recently-traded board, the informative thing to know is which coins
are bleeding fastest, and the reward for knowing it is to bleed slower.**

### Split-half stability

| cohort | feature | target | ρ h1 | ρ h2 | edge% h1 | edge% h2 | sign holds |
|---|---|---|---|---|---|---|---|
| `hot` | `log_stale_s` | `fwd_5m` | −0.192 | −0.118 | +1.62 | +1.24 | **yes** |
| `mcap` | `log_age_h` | `fwd_5m` | −0.546 | −0.563 | +1.08 | +0.75 | **yes** |
| `dexpool` | `rv_24h` | `fwd_24` | −0.087 | +0.006 | −0.97 | +2.77 | **no** |
| `dexpool` | `ret_72h` | `fwd_24` | +0.004 | −0.041 | +0.25 | +1.27 | no |
| `live` | `log_stale_s` | `fwd_5m` | −0.059 | +0.019 | +0.16 | +0.22 | **no** |
| `frozen` | `n_boards` | `fwd_2h` | +0.272 | −0.049 | +0.65 | +0.02 | **no** |

The two stable return-cells are the two whose economics say they cannot pay for themselves.
Every `frozen` control cell flips sign, as it must.

### Held-out replication

Pre-specified short list fixed by the primary run, re-measured on a **disjoint later collection session, 08-15 07:34 → 12:56 UTC (5.37 h)**. No new multiplicity.

| cohort | feature | target | dCor primary | dCor held-out | p held-out | same sign |
|---|---|---|---|---|---|---|
| `hot` | `log_stale_s` | `fwd_5m` | 0.236 | 0.188 | **0.0050** | yes |
| `mcap` | `log_age_h` | `exit_2h` | 0.359 | 0.291 | **0.0101** | yes |
| `hot` | `log_age_h` | `exit_2h` | 0.286 | 0.223 | **0.0201** | yes |
| `hot` | `log_mcap_sol` | `exit_30m` | 0.207 | 0.191 | **0.0253** | yes |
| `hot` | `ret_5m` | `dead_30m` | 0.150 | 0.119 | 0.0750 | yes |
| `live` | `log_stale_s` | `fwd_5m` | 0.328 | 0.229 | 0.5300 | yes |
| `live` | `d_rank_5m` | `dead_30m` | 0.249 | 0.154 | 0.4050 | no |
| `frozen` | `n_boards` | `dead_30m` | 0.946 | 0.721 | 0.5150 | yes |
| `frozen` | `log_mcap_sol` | `fwd_2h` | 0.571 | 0.759 | 0.4950 | no |

**Four survivors replicate at p < 0.05 with the same sign** — including the one return-cell,
`hot`/`log_stale_s` → `fwd_5m`, at p = 0.0050. Both `live` survivors fail to replicate. The
`frozen` control cells, with the largest dCor in the table, fail as they must. `fwd_8h` cells
could not be tested: the horizon exceeds the held-out window, which is a coverage fact about
the hold-out, not a failed replication.

This is the first time anything in this repo has survived a genuine temporal hold-out.
`RESULT_board_entry.md` closes by asking for exactly this and could not do it.

## 7. Time in view, and how it ends

| cohort | n | median min in view | duty | exit down | exit flat/up | CIF(down) @30m | @2h | @8h |
|---|---|---|---|---|---|---|---|---|
| `hot` | 1050 | 162.0 | **19%** | 51% | 42% | 0.232 | 0.339 | 0.446 |
| `live` | 347 | 47.5 | 96% | 8% | 78% | 0.032 | 0.053 | 0.082 |
| `mcap` | 79 | ∞ | 100% | 14% | 23% | 0.000 | 0.079 | 0.106 |
| `frozen` | 98 | ∞ | 100% | 0% | 0% | 0.000 | 0.000 | 0.000 |
| `dexpool` | 110 | 55,500 | — | 20% | 48% | 0.000 (24h) | 0.009 (72h) | 0.019 (168h) |

`duty` is the share of the in-view span a coin was actually on a board. **On `hot` it is 19%** —
these coins flicker on and off constantly, and "162 minutes in view" is a window, not
continuous presence. `frozen` never exits at all, which is why its exit targets are degenerate
and were dropped.

Competing risks (Aalen-Johansen, leaving ≥10% down vs leaving flat-or-up): **on `hot`, 23% of
coins are gone-and-down within thirty minutes and 45% within eight hours.**

Splitting each cohort at its median drawdown-from-ATH, on the exit hazard:

| cohort | median drawdown | median min, deep | median min, shallow | log-rank p |
|---|---|---|---|---|
| `hot` | 0.216 | 393.5 | 64.5 | 8.9e-14 |
| `live` | 0.018 | 234.2 | 10.5 | 1.3e-28 |
| `mcap` | 0.002 | 600.0 | 183.5 | 8.9e-06 |
| `frozen` | 0.323 | 600.0 | 600.0 | 1.00 |

**Deep-drawdown coins stay in view six times longer than shallow ones.** This tensions with
`RESULT_board_entry.md`, which reported deep-drawdown entries as *more* censored (65→81% vs
48→77%). The definitions differ — that study measured censoring of a fixed-horizon forward
return from a board-entry event; this measures total time in view over the window, on a cohort
filtered to ≥4 minutes of life. Both cannot be casually cited together, and the difference
should be resolved before either is built on. `frozen` returns p = 1.00, as a dead control
should.

## 8. Nulls and trials accounting

**Declared cells: 542**, written to `studies/data/exploration_map/grid_declared.json` before
the run. Every declared cell enters the FDR budget, including the **3 unevaluable** ones,
which are entered at p = 1 rather than dropped — dropping them would shrink the denominator
using knowledge gained from the data, which is the bandit study's mistake in a quieter form.

**Correction: Benjamini-Yekutieli**, not BH. The cells share panels, features, and targets at
nested horizons, so they are arbitrarily dependent and BH's independence/PRDS assumption is
not available. Price: the harmonic factor **c(542) = 6.873** — the rank-1 cell needs
p ≤ 0.10/(542 × 6.873) = **2.7e-5**.

**Permutations are sequential in three stages** so p-value resolution matches what the
correction needs: 199 draws for every cell, 4,999 for cells at p ≤ 0.05 (75 cells), 99,999 for
cells at p ≤ 0.0015 (15 cells). Before spending the expensive stage, the code checks whether
it could change any verdict — it compares the BY rejection set as it stands against the best
case where every floor cell's p goes to zero, and skips the stage when they agree. Here they
did not agree, so the stage ran (6,468 s).

**Nulls per cell: three or four** (`mint` where it lands on ≥50% of rows; the mint-block
permutation is done within entry-time blocks so a swap actually lands on a staggered cohort).

**Things tried and abandoned, recorded rather than dropped:**

1. A process-parallel runner. `ProcessPoolExecutor` is unavailable in this sandbox — workers
   are reaped, `BrokenProcessPool` — so the grid runs on threads.
2. The first null implementation transformed the whole (M × T) panel per permutation and then
   indexed 800 sampled rows out of it. Correct, and ~30× too slow to afford the 99,999-draw
   stage. It survives as `null_panel`, the readable reference, and `selftest` checks the fast
   `NullDraw` path against it distributionally on all four nulls.
3. **BigQuery was not spent against. Total spend for this study: $0.** The obvious use — a
   held-out day to replicate the boards findings — is not purchasable at any price, because
   board membership is a pump.fun API artefact and is not on-chain. The held-out window came
   from the collector, for free.
4. **`state/bulk_pump/` was not used.** 25 GB, 35,255 parquet parts, 10 days (08-05→08-14).
   The schema is raw transactions — `signature`, `block_slot`, `block_time`, `tx_index`,
   `fee_lamports`, `err`, and pre/post token-balance lists. There is no mint, no pool, and no
   price; deriving a bonding-curve price panel means identifying curve accounts and
   reconstructing reserves from balance deltas across 25 GB. That is a re-architecture, not a
   cell, so per instruction it was left alone. **It is the highest-value next input** — see §9.

## 9. What survives, and what to do next

**The shortlist that survives everything — FDR, every applicable null, split-half sign, and a
disjoint hold-out — is ONE return cell, and it is not a strategy:**

- `hot` / `log_stale_s` → `fwd_5m`: q = 0.019, hold-out p = 0.0050 same sign, split-half sign
  stable (ρ −0.192 / −0.118), 2% censoring, 50,511 trades — **and a top-decile return of
  −0.21%.**

Plus three exit/death cells that also clear FDR and replicate out of sample, none of which is
a price signal:

- `hot` / `log_age_h` → `exit_2h` (q = 0.019, hold-out p = 0.0201)
- `mcap` / `log_age_h` → `exit_2h` (q = 0.098, hold-out p = 0.0101)
- `hot` / `log_mcap_sol` → `exit_30m` (q = 0.098, hold-out p = 0.0253)

The other four survivors fail at least one gate: `live`/`log_stale_s` → `fwd_5m` and
`live`/`d_rank_5m` → `dead_30m` do not replicate (p = 0.53, 0.41); `dexpool`/`ret_72h` →
`fwd_24` fails split-half at 73% censoring and has no hold-out; `hot`/`ret_5m` → `dead_30m`
replicates only at p = 0.075.

**The honest reading is that the entry-selection question is answered and the answer is no.**
Across 542 cells, six streams, five horizons and four target families, the best net edge
available to a desk choosing *which coin to buy* is under a tenth of the friction it would pay
to act on it. Given eight prior consecutive strategy nulls, this map is the ninth, and it is
the one that says *why*: the observable streams are informative about **visibility and
survival**, not about **price**.

That points somewhere specific, and it is not "test another entry signal":

1. **Position management, not entry selection.** Every replicated cell is about exit, death, or
   how fast a coin bleeds. That is the input to a *stop and hold-time policy* for positions
   already open, where the 2.26% round trip is already sunk and a 1.42pp reduction in bleed is
   worth its full value. This is the only place on the map where the surviving information can
   be converted into money.
2. **Fix the collector overlap before any market-state hypothesis.** The firehose channel is
   untested, not null. Running both collectors concurrently costs nothing and unlocks a whole
   column of the map.
3. **`state/bulk_pump/` is the next real input**, and it overlaps the boards window (08-14).
   Reconstructing bonding-curve reserves from its pre/post balances would give swap-level
   ground truth *underneath* the `hot` cohort — actual trade direction, size, and signer, at
   the exact instants where the only surviving return-cell lives. Budget it as its own study.
4. **Do not build on `dexpool`/`rv_24h`.** It has the best breakeven on the map and it fails
   the split-half sign test at 73% censoring. It is the cell most likely to waste a week.
5. **Resolve the drawdown/censoring contradiction with `RESULT_board_entry.md`** (§7) before
   either result is cited in support of a trade.

**And the desk-level conclusion the brief asked for:** on this evidence the observable streams
do not support an entry-selection strategy at these horizons, and the all-toll posture is the
correct default. The map's contribution is that this is now a measurement over a declared grid
with a multiplicity budget and a hold-out, rather than the accumulated impression of eight
studies that each looked somewhere different.

---

## Reproducing

```
uv run --group research python studies/exploration_map.py selftest   # 39 calibration checks
uv run --group research python studies/exploration_map.py all --jobs 8
```

`selftest` runs **39 checks** and is a gate, not a formality: `all` refuses to run the grid if it fails. It covers
statistic identities, BY behaviour on planted needles, known-zero and known-effect panels, the
market-factor placebo, the spurious-regression false-positive rates quoted in §3, the
microstructure-bounce artefact of §2.3, the fast-null/reference-null equivalence, and the
k-NN MI estimator against the closed-form Gaussian truth.

Full artefacts (gitignored, regenerate with the above): `studies/data/exploration_map/` —
`grid_declared.json`, `map.json` (all 542 cells with every null's p), `economics.json`,
`survival.json`, `replication.json`, `report_tables.md` (the full 45-row ranked table).

Read-only over `state/`. Signs nothing, sends nothing, spends nothing.
