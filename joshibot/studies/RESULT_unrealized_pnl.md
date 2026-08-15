# Unrealized PnL — cost basis per (wallet, coin), and what its distribution is good for

**The operator's question, verbatim:** *"have we ever tried learning a model against the
distribution of unrealized profit (this feeds into wallet correlation analysis, we could be
hypothesizing a wallet is controlled by a given actor...)"*

**Answer: never, until now.** Every study in `studies/` prices *flow* — who bought, who sold, how
much SOL moved. None of them carried a wallet's own entry price forward. This builds the missing
object and runs it at the four questions it was commissioned for.

Run 2026-08-15 against the ten-day all-pump.fun corpus (2026-08-05 .. 2026-08-14), on
**71,562,170 basis rows** covering **1,228,382 wallets** across **67,658 coins**.
**Spend: $0.00** — no BigQuery, no network, everything on disk.

---

## 0. Verdicts, in one place

| # | Question | Verdict |
|---|---|---|
| 1 | Does cost-basis density predict where price stalls and reverses? | **NULL, twice over** |
| 2 | Is realization policy an *actor* fingerprint? | **Mostly no — and the confound it was built to survive turned out not to exist** |
| 3 | Is the loss-tail shape a PvP/community discriminator? | **Feature delivered; strong separation, handed to the `pvp_vamps` lane** |
| 4 | Rug-fuel gauge on the operator's four coins | **Near zero on bought supply; the exposure is airdropped supply, which is a different object** |
| + | *Beyond the brief:* is unrealized PnL a live state variable at all? | **Yes — sell hazard peaks at break-even and falls 4–5× in both directions** |

### 0.1 The object itself, since nobody had looked at it

**Where sells happen** — 19,867,171 priced realizations:

| p10 | p25 | median | p75 | p90 | p99 | in profit |
|---|---|---|---|---|---|---|
| −51.7% | −17.6% | **+2.8%** | +28.2% | +105.0% | +5432% | **57.4%** |

**Where the money actually is** — the standing book, i.e. every live position at the corpus
edge, 2,303,133 of them:

| p05 | p25 | median | p75 | p95 | positions in profit | supply in profit |
|---|---|---|---|---|---|---|
| −99.3% | −96.6% | **−71.4%** | −43.2% | +24.4% | **7.8%** | **8.5%** |

The gap between those two tables is the whole shape of this market. **Realizations are roughly
symmetric around break-even and 57% of them are green; the surviving book is 92% red at a median
of −71%.** Winners realize and leave; losers stay and become the book.

Two more, because they bear on every behavioural claim below:

* **23.1%** of buys are made by a wallet already underwater on that coin (averaging down);
  **42.4%** of sells are made underwater.
* **Half of all sells happen in the same slot the position opened** (48.0%), and the median
  holding time before a sell is **3 seconds**. Whatever "realization policy" means here, it is
  mostly the policy of very fast bots, not of people watching a chart.

---

## 1. The instrument

### 1.1 What was built

For every (coin, wallet) in the cohort, the **average-cost basis trajectory**: basis and position
after every one of that wallet's fills, and therefore its unrealized PnL at the instant it acted.
On a sell that is the **realization point** — the level of unrealized profit at which the wallet
chose to take money off the table.

Cohort: coins with **≥30 curve touches**, which is Marino/Lillo's own conditioning (surviving to 30
swaps quadruples the graduation base rate) and the cheapest liveness filter in the literature.
67,710 of 266,928 born-in-window coins clear it.

### 1.2 Average cost, not FIFO — and the sensitivity is measured

The choice is not a tax question and it is not arbitrary. **Average cost is the representation the
agent acts on:** every retail pump.fun front end and every Telegram execution bot displays exactly
one P/L number per position, computed as average cost, and a take-profit preset is typed against
that number. FIFO models a tax lot; nothing in this market has a tax lot.

It is also the only convention that closes as a **window function**. Under average cost the
per-unit basis `b` changes on buys and never on sells:

```
buy of D at price p, from position q:   b' = b·q/(q+D) + p·D/(q+D)
sell of D:                              b' = b
```

which is a linear recursion `b_n = a_n·b_{n-1} + c_n`, with closed form
`b_n = A_n · Σ_{i≤n} c_i/A_i` where `A_n = Π_{i≤n} a_i`. Both are window aggregates (`A` evaluated
as `exp(cumsum(log a))`), so a sequential scan over 10⁸ rows becomes a SQL query. `a_n = 0` exactly
when a wallet buys from a flat book, which is the natural **episode** boundary — the series is
partitioned there rather than letting a zero poison the running product, which is also the correct
semantics (a wallet that fully exits and re-enters has a new entry price, not a blended one).

FIFO sensitivity is reported in §2.2 rather than asserted.

### 1.3 Where the price comes from, and the two marks

`studies/operator_crime.py` established the affine identity — on a pump.fun bonding curve
`log p = log k − 2·log v_tok`, verified to 0.118% median against the boards tape.
`studies/pvp_vamps.py` took it to the exact SOL leg, `sol = K·(1/v_tok_after − 1/v_tok_before)`.
This module uses that, with the **per-mint** offset `v_tok = curve_balance + (1.073e15 −
initial_curve_balance)` because two curve configurations are present in this corpus.

**Two routes, and the split is not a detail.** In this cohort 30,742 mints trade only against a
bonding curve and 2,230 against a PumpSwap pool — and the 6.8% that migrated carry **~70% of all
fills**, because graduation is exactly the event that produces sustained volume. All four of the
operator's coins are in that 6.8%.

* **Cost basis is exact on both routes.** On the curve it is the constant-product identity; in a
  pool it is the pool's own observed WSOL vault delta. Neither needs a reserve *level*.
* **The mark is the harder half.** In a pool it would need reserve levels, and those are *not*
  recoverable here: a running sum of vault deltas is offset by whatever the vault held before its
  first observed transaction, and a boosted PumpSwap pool prices against
  `pool_quote + virtual_quote_reserves` with the virtual term living in `log_messages`, which is
  empty for this corpus. So the pool route is marked at **last traded price**.

**That substitution is validated, not assumed.** On the curve route both marks exist, so their
disagreement is measurable — and it is the error bar the pool route inherits. See §2.1.

### 1.4 Transfers are events, not trades

A wallet-to-wallet transfer has no counterparty leg, carries no price, and is not a fill — but it
moves the position. Dropping it makes a sybil's bag appear from nowhere and drives reconstructed
positions negative; pricing it at spot makes every airdrop recipient look like a genius. Transfers
are therefore kept as **acquisitions at zero cost**, which preserves total cost and is the
conservative reading for §4, and every (mint, wallet) carries `xfer_in_raw` so the free-supply
stratum is always separable from the bought-supply stratum. §4 never adds them together.

### 1.5 Left censoring, counted

A (coin, wallet) series whose first observed event is a *disposal* has no observable entry price.
Those rows get no episode and are dropped. For cohort coins — which are born in-window — the hole
is tiny (§2.2). For the operator's four coins, which all predate the window, it is the binding
limitation and §4 is built around it rather than over it.

---

## 2. Instrument checks

Run over the full ten-day corpus, 2026-08-05 .. 2026-08-14.

| object | n |
|---|---|
| basis rows (one per fill or transfer, with the wallet's state at that instant) | **71,562,170** |
| (coin, wallet) pairs | **13,315,146** |
| distinct wallets | **1,228,382** |
| coins | **67,658** |
| sells | **25,286,403** |
| sells carrying a realization point | **20,705,826** (81.9%) |
| left-censored rows dropped (first event is a disposal) | 212,043 (**0.30%**) |
| rows on a book driven negative by unobserved inflow | 863,857 (1.2%) |

### 2.1 The closed form *is* the recursion

`BASIS_SQL` replaces a sequential scan with a cumulative product evaluated in log space. Checked
against a literal Python recursion on 8,000 random (coin, wallet) series (103,160 events):

| stratum | median rel. error | p90 | p99 | max |
|---|---|---|---|---|
| all series | 1.26e−16 | 1.35e−15 | 2.43e−14 | 0.095 |
| clean series (99.6%) | 1.28e−16 | 1.38e−15 | 2.43e−14 | **1.03e−13** |

Floating-point noise. The only divergence is the negative-book stratum (34 of 8,000 series),
which is flagged, and **zero** series tripped the log-space guard.

### 2.2 FIFO vs average cost — the sensitivity, measured

On the same sample, comparing the realized-PnL fraction each convention reports at each sell:

| | value |
|---|---|
| sells where the two agree **exactly** | **61.5%** |
| median gap | **0.0** |
| p90 gap | 0.167 (16.7 percentage points of reported PnL) |
| p99 gap | 3.52 |

So for the majority of sells the convention is irrelevant, and for the top decile it is a
~17pp difference. Wallets that scale in and out repeatedly are where the two part company —
which is exactly why the sample has to be random rather than activity-weighted (§2.5).

### 2.3 Last-trade vs the exact marginal mark

The pool route is marked at last traded price because reserve levels are unrecoverable. On the
curve route both marks exist, so the substitution's error is measurable there — **18,565,260
paired observations**:

| median | p90 | p99 |
|---|---|---|
| **0.41%** | 2.89% | 11.6% |

That is the error bar the pool route inherits, and it is small enough that the pool-route
results are reported without qualification other than this one.

### 2.4 The virtual-reserve offset is a constant, and that is a correction

The obvious derivation — take the curve's own peak observed balance as its funded supply,
`offset = 1.073e15 − max(bal_after)` — is **biased**, and `studies/pvp_vamps.py` found the
mechanism: the create transaction nets the curve's leg to `supply − dev_buy`, because the mint
and the dev buy hit the same account in the same transaction. A curve whose dev buy never comes
back peaks *below* its funded supply, and the derived offset is too large by the shortfall.

Measured here on 65,056 cohort mints: the **median** peak balance is exactly 1e15 and the derived
offset is exactly right — which is why this hides in aggregate. But **7.73% of coins are off by
more than 10%**, and the induced price error is **32.9% at p90 and 92.7% at p99** on affected
coins. That tail is large enough to move any per-coin result, which is most of this study. Every
coin in `coins.parquet` passed `operator_crime`'s BORN predicate (`minted_raw = 1e15` exactly),
so within this cohort the funded supply is 1e15 universally and the offset is exactly 7.3e13.
The first full fold was discarded and rerun after this was found.

### 2.5 Two duckdb sampling pushdowns, both of which produced wrong answers

`USING SAMPLE` attached directly to a `GROUP BY ... HAVING` query gets pushed below the
aggregation. In `check` that returned **33 of the busiest wallets in the corpus** instead of
8,000 random ones — a sample biased precisely toward the wallets where FIFO and average cost
diverge most, i.e. the worst possible sample for the question being asked, and it reported a
median FIFO gap of 0.17 where the true value is 0.0. In `hazard` the same construction returned
nothing at all. Both now sample from a materialised table.

### 2.6 Ground truth: the operator's own reconciled session

PROGRAM.md §0 records the 2026-08-12 live session reconstructed from chain two independent ways,
reconciling to the lamport: **137 buys, 121 sells, 92 mints, −7.47 SOL**. That is the only real
ground truth available for this pipeline, because it came from a completely different instrument.

Against the raw ledger, the operator's wallet made **211 pump-mint legs across 79 mints** that
day (108 buys, 103 sells) — so 79 of 92 mints carry the `%pump` suffix and are in the corpus at
all. Of those 211 legs, **152 (72%) land in the ≥30-touch cohort**, covering 52 of 79 mints, and
they reconstruct to −1.59 SOL net.

The residual is *not* the touch filter. Broken out by cause:

| why a leg is absent | mints | legs |
|---|---|---|
| in cohort | 80 | 213 |
| **not a born-in-window pump coin** | **27** | **64** |
| born in window, <30 curve touches | 5 | 10 |

**The dominant exclusion is coins that predate 2026-08-05**, which is the same left censoring
§1.5 flags — and it is exactly what you would expect of a *sell-only position sentinel*, whose
job was to manage positions opened before the window. The instrument finds the wallet, gets the
trade counts right to within the corpus's own coverage, recovers the sign and the shape (median
realized +3.4%, mean −6.3% — a few catastrophic trades dominating, with the worst round trips
realized at −74% to −94%), and does not pretend to the lamport reconciliation it cannot do.

---

## 3. Q1 — does cost-basis density predict where price stalls and reverses?

### 3.1 The circularity this was built to avoid

Basis density is high at exactly the price levels where a lot of volume traded, and price
revisits levels where it previously dwelt. A naive test therefore finds an "effect" from
autocorrelation alone, with no holder psychology involved. Three separate defences, all
pre-registered:

1. **The density is frozen at a snapshot `t0`** and every reversal is scored strictly after it,
   so no trade contributes to both sides of the comparison.
2. **The statistic is a within-path rank** — the density at reversal levels against the density
   at every level *this same path actually traversed*. That conditions out occupancy entirely.
   The question is not "is the density high where price reversed" (it is, trivially) but "is it
   higher there than at the other levels this path visited".
3. **Two nulls, because one null is a knob** (PROGRAM.md §3 rule 13):
   * **rotation** — give coin *i*'s price path coin *j*'s density profile. Kills any effect that
     is a property of the generic *shape* of a basis distribution rather than of *this* coin's.
   * **occupancy control** — replace the basis density with the pre-`t0` **traded-volume**
     density over the same levels. Basis density *is* volume density minus the people who
     already left; if the basis version does not beat the volume version, the finding is "price
     revisits busy levels" and carries no information about anyone's entry price.

### 3.2 The population, pre-registered

A coin enters the **wiggle population** when it has (a) collapsed — drawdown past 60% from its
own peak; (b) survived with two-sided flow — ≥100 fills after the collapse completes, ≥20 on
each side; and (c) ≥50 distinct live holders at the snapshot. `t0` is the first moment after the
peak at which the mark has fallen through the 60% threshold. Curve-route coins only, so the
price path is the exact marginal price rather than a last-trade proxy.

Cell grid: 3 kernel bandwidths × 3 swing thresholds × 2 profile kinds = **18 cells**, BY-FDR
over the grid.

---

## 4. Q2 — is realization policy an *actor* fingerprint?

### 4.1 The confound, and what happened to it

The brief named the confound before any result: **shared tooling produces policy clusters
without shared actors** — a bot ships a default −25% stop and +100% take, ten thousand unrelated
users accept the defaults, and their realization histograms become near-identical.

That confound was designed around, and then **measured, and it does not exist in this market**.
See §4.4. Every classic take-profit and stop-loss level sits within a few percent of its own
smooth baseline. There is exactly one attractor in realization space and it is **break-even**.

### 4.2 The estimator, and the two defects its controls caught

Each wallet is embedded as a normalised histogram of `upnl_at_action` over its sells, in
signed-log PnL coordinates, sqrt-transformed so L2 distance is Hellinger distance. Pairs are
scored by negative distance. Calibrated between two controls rather than reported bare:

* **KNOWN-EFFECT (ceiling)** — a wallet's own coins split into two *disjoint halves*. Same
  actor, same tooling, different coins.
* **KNOWN-ZERO (floor)** — random cross-wallet pairs, and separately pairs with zero coin
  overlap.

Both defects below were caught by the zero control, not by inspection, and both would have been
reported as findings:

1. The first version compared same-actor **halves** against different-actor **wholes**, so the
   same-actor side carried twice the sampling noise. The known-zero world read **AUC 0.333** —
   the metric claimed same-actor pairs were *less* similar than strangers.
2. With halves on both sides it still read **0.538**, because a same-actor pair has *correlated*
   half sizes while a random pair can put a 200-sell wallet against a 12-sell one, and the noisy
   small histogram inflates the distance. That is an activity-level confound wearing an
   actor-identity costume. Negative pairs are now drawn from the same (log₂ size, log₂ size)
   cell as the positives they are scored against, and the zero world reads **0.501**.

### 4.3 The positive control is independent evidence, and that is the point

Candidate same-actor pairs come from the **birth-slot sniper crews** of
`studies/RESULT_operator_crime.md`, whose set reuse runs **51.2× a degree-preserving null**.
Pairs are re-validated here against a curveball null on the bipartite (coin × sniper) incidence,
because on heavy-tailed activity a hypergeometric null validates ~99 false edges per world out
of nothing while a degree-preserving null deletes 100% of them (`RESULT_svn_cotrading.md`).

That evidence channel is **co-occurrence in time**; this one is a PnL-level histogram with no
temporal content at all. The entity-resolution graveyard's rule — never let a temporal rule
validate a temporal test — is therefore satisfied by construction, and it is worth saying out
loud that this is *why* the sniper crews are admissible here.

**One permutation-floor trap, recorded because it produced a fake null.** The first crew run
used 20 permutations against α = 0.02. The permutation p-value has a hard floor of
1/(n+1) = 0.048, so nothing could ever be rejected and the run returned **zero** crew pairs —
which reads exactly like "the crews failed the null". The module now refuses α below the floor.

### 4.4 The confound does not exist — measured, not assumed

`q2` reports the share of sells inside a tolerance band of a round level, and **that number is
uninterpretable on its own**: nineteen levels at a ±2% relative band cover roughly half this
distribution's support by chance, so the measured 27.9% is *below* the chance rate. The test that
means something is **excess over a smooth baseline** — a ±0.2-wide moving median, which a
one-bin spike cannot drag upward. Bin width 0.002, 19,240,639 sells:

| level | observed | smooth baseline | excess |
|---|---|---|---|
| −75% | 14,879 | 14,879 | 1.000 |
| −50% | 26,228 | 25,532 | 1.027 |
| −40% | 30,016 | 30,014 | 1.000 |
| −30% | 37,809 | 37,667 | 1.004 |
| −25% | 41,573 | 41,456 | 1.003 |
| −20% | 47,830 | 47,989 | 0.997 |
| −15% | 55,593 | 55,545 | 1.001 |
| −10% | 64,944 | 65,190 | 0.996 |
| **0% (break-even)** | **374,623** | **76,634** | **4.888** |
| +25% | 45,020 | 45,020 | 1.000 |
| +50% | 18,932 | 18,842 | 1.005 |
| +75% | 11,280 | 10,716 | 1.053 |
| +100% | 7,280 | 7,278 | 1.000 |
| +150% | 3,257 | 3,192 | 1.020 |
| +200% | 1,941 | 1,956 | 0.992 |
| +300% | 772 | 847 | 0.911 |
| +400% | 466 | 440 | 1.059 |
| +500% | 285 | 272 | 1.048 |
| +900% | 85 | 82 | 1.037 |

**Not one classic take-profit or stop-loss level is a spike.** Eighteen of nineteen sit between
0.91 and 1.06 of their own baseline — noise. Exactly one level is real, and it is **break-even,
at 4.89×**.

This is a result about the limits of an assumption, and it is worth stating plainly: the
"thousands of users on identical bot defaults" confound that this entire question was designed
to survive is **not present in this corpus**. Either the presets are not clustered on round
numbers, or slippage and impact smear an exactly-typed −25% into a continuum before it reaches
the chain. Both readings kill the confound as a *distinguishable* artifact.

**What the break-even spike is instead.** Partly mechanical: at-break-even sells are 55.9%
same-slot-as-open against 48.0% for all other sells, so instant round trips are over-represented
there — but only mildly, since the base rate is already 48%. The rest is behaviour, and §7
measures it against a proper denominator rather than inferring it from a histogram.

---

## 5. Q3 — the basis-shape feature, for the `pvp_vamps` lane

`studies/RESULT_pvp_vamps.md` shipped the PvP classifier the same afternoon. Building a second
one here would be two lanes fitting the same outcome on the same corpus and calling the
agreement corroboration, so this stage stops at the **feature** and hands it over.

**The note for that lane's coordinator.** Your five-column PvP meter scores AUC 0.880 marginally
but collapses to 0.485–0.560 *conditional on age band*, and inside the under-30-minute band
`recycled_30m` beats it 0.622 to 0.505. Every column in both your PvP block and your free block
is a **flow** or **market-state** quantity — buy/sell counts, recycled share, market cap, age,
activity. None of them can see a holder's entry price, because nothing in this repository could
compute one until now.

The columns below are a different family: they are **holder-state** quantities, and the deepest
one cannot be reconstructed from flow at all. `supply_held_through_50pct_red` asks, for each
wallet still holding, how far the coin fell *after that wallet's own entry* — the deepest price
the coin printed since it bought, against its own basis. A wallet that watched its position go
80% red and is still holding is a different animal from one that never saw red, and no
volume-based feature distinguishes them.

| column | what it is |
|---|---|
| `frac_sells_red`, `frac_sells_deep_red`, `frac_sells_very_deep_red` | share of realizations below 0, −30%, −60% |
| `med_loss_taken`, `p90_loss_taken` | how deep sellers let it get before capitulating |
| `med_gain_taken` | the symmetric take-profit level |
| `solshare_sells_red` | the same, SOL-weighted — one whale is not one voter |
| `supply_underwater`, `supply_underwater_2x` | share of live supply below / far below its basis |
| **`supply_held_through_50pct_red`**, **`supply_held_through_80pct_red`** | share of live supply whose holder has already sat through that drawdown since its own entry |
| `n_live_holders`, `n_survivors` | denominators, so you can weight |

Joinable on `mint` at `state/upnl/q3_basis_shape.parquet`. **Caveat to carry:** these are
measured over the whole observed life of the coin, so they are *not* causal at a 30-minute
decision point as written. Making them live means recomputing at the decision time, which the
`basis` stage supports directly (every row carries `block_time`), but that is your lane's call
and your lane's null.

### 5.1 The feature has real spread, and the deep one has the most

39,702 coins with ≥30 priced sells, split on graduation only to show the columns are not flat.
**This is a descriptive contrast, not a classifier and not a claim about PvP.**

| | non-graduated (n=35,205) | graduated (n=4,497) |
|---|---|---|
| median `frac_sells_deep_red` | 0.224 | 0.200 |
| median `med_loss_taken` | 0.251 | 0.324 |
| median `med_gain_taken` | 0.196 | 0.242 |
| median `supply_underwater` | **1.000** | **1.000** |
| median **`supply_held_through_50pct_red`** | **0.327** | **0.795** |
| median **`supply_held_through_80pct_red`** | **0.000** | **0.451** |

Two things to take from this.

**`supply_underwater` is dead on arrival and that is worth knowing.** At the end of a collapsed
coin's life essentially 100% of live supply is red, on *every* coin — the obvious feature
discriminates nothing. It is reported so nobody builds on it.

**`supply_held_through_50pct_red` separates 2.4×, and the 80% version separates a median of zero
from a median of 0.45.** In the median non-graduated coin, no surviving supply has sat through an
80% drawdown since its own entry; in the median graduated coin, nearly half has. That is the
folk claim — *mercenaries stop out instantly, communities hold red* — appearing as a measured
quantity for the first time, and it is a holder-state quantity that no flow feature can see.

It is also **not** the PvP question, and this lane does not answer that. Graduation is a poor
proxy for community-versus-mercenary and the contrast above is confounded by coin size, age and
volume, all of which the `pvp_vamps` lane already controls for and this one deliberately does
not. The deliverable is the column, not the conclusion.

---

## 6. Q4 — the rug-fuel gauge

`rugfuel(θ)` = the fraction of live supply whose cost basis sits below `θ × spot`. It measures
how much supply *could* be dumped at a large multiple of what it cost — the fuel, not the match.
It says nothing about intent.

**Three gauges, never added together.** Conflating them is what makes this number useless:

* `rugfuel_NNN` — all live supply below `θ × spot`, free supply included.
* `rugfuel_paid_NNN` — only supply the holder actually **bought** below `θ × spot`. This is the
  accumulator sitting on a large multiple, which is what the phrase usually reaches for.
* `zero_basis_share` — supply that arrived by transfer and cost its holder nothing: airdrops and
  bundler distributions. Free, yes — but a scheduled holder airdrop and a hidden accumulation
  are different objects.

**Attested own supply is never counted as threat.** The operator's wallets from
`wallet_labels.yaml` are excluded from the threat numerator and reported separately, because a
scheduled, publicly-attested unlock is a known overhang rather than an ambush.

**Left censoring is the binding limitation on the four operator coins**, stated up front rather
than buried. All four were born before the corpus window, so any holder who acquired before
2026-08-05 has no observable basis. The gauge is therefore reported on the *observable* stratum
with its holder count attached, plus a **hard bound on the censored stratum taken from the price
path itself**: a holder who acquired in-pool at any point in the observed history paid at least
the lowest price the pool printed, so nobody — observed or not — can be up more than
`spot / min_price`. `state/bulk_history` extends that bound from 10 days to ~48 for these exact
pools, which is what `bounds` computes. The bound does **not** cover supply that arrived
off-pool (airdrop, escrow release, OTC); that stratum is exactly `zero_basis_share`.

**Two schema traps, both hit.** `spot` must be dust-robust: on the pool route the mark is the
last traded price, and the last trade on a quiet coin is routinely a 0.0001-SOL dust print whose
effective price is meaningless — filtering fills below 0.01 SOL moved DREGG's implied all-time
low by more than two orders of magnitude, which would otherwise have been reported as a 176×
overhang. And `err` in `state/bulk_history` is **NULL on success**, the exact opposite of the
`bulk_pump` corpus where it is an empty string and never NULL; testing one convention against
the other silently returns zero rows, which is what the first run of `bounds` did.

### 6.1 The cohort baseline — cheap supply is rare

17,799 coins with ≥20 observed live holders:

| | median | p90 | p95 | p99 |
|---|---|---|---|---|
| `rugfuel_paid_010` (bought below 10% of spot) | 0.000 | **0.000** | 0.000 | 0.075 |
| `rugfuel_paid_050` (bought below 50% of spot) | 0.000 | 0.000 | — | 0.519 |
| `zero_basis_share` (arrived free) | 0.000 | 0.511 | — | 0.997 |

**Only 2.39% of coins have *any* supply bought below a tenth of spot.** After a collapse nobody is
sitting on a 10×, which is the whole reason the gauge is informative when it is not zero.

### 6.2 The operator's four coins, scored today

Snapshot at the corpus edge, 2026-08-14. Percentiles are against the 17,799-coin cohort above.

| coin | observed holders | **bought <10% of spot** | pct | bought <50% of spot | pct | arrived free | pct | max multiple, any holder (10 d) |
|---|---|---|---|---|---|---|---|---|
| **weave** | 590 | **17.9%** | **99.2** | **49.1%** | 98.9 | 6.2% | 83.1 | 21.7× |
| **nosis** | 2,616 | 1.4% | 98.6 | 21.0% | 98.1 | 20.3% | 85.6 | 8.0× |
| **SOLVE** | 116 | 0.0% | — | 3.3% | 96.7 | 12.0% | 84.5 | 1.6× |
| **DREGG** | 204 | 0.0% | — | 1.5% | 96.3 | **30.9%** | 87.1 | **1.1×** |

Long-window bound from `state/bulk_history`, which covers these exact pools for longer than the
corpus does. This bounds *any* in-pool acquirer, observed or censored:

| coin | days covered | swaps | max multiple (1st pct) | max multiple (true min) |
|---|---|---|---|---|
| DREGG | 47.4 | 84,558 | 16.0× | 47.9× |
| SOLVE | 24.0 | 11,271 | 2.4× | 3.4× |
| weave | 10.1 | 14,288 | 33.6× | 54.4× |
| nosis | 4.7 | 71,169 | 10.3× | 18.8× |

**Read it like this.**

* **weave is the one to look at, and it is not close.** 17.9% of its observed live supply was
  bought below a tenth of today's price, in a cohort where 97.6% of coins have exactly zero —
  the 99.2nd percentile. Half its observed supply (49.1%) is below half of spot. The mechanism is
  simply that weave ran 21.7× inside the window and a large cohort of early buyers has not sold.
  This is a **structural** statement about who holds the coin, not a prediction and not an
  accusation; it says the coin currently carries an unusually large body of holders for whom
  selling at almost any price is a large gain.
* **nosis is second, and mostly through the 50% threshold** (21.0%, 98.1st pct) rather than the
  10% one. It also carries 20.3% free supply.
* **SOLVE and DREGG carry essentially no bought-cheap supply.** DREGG's ten-day bound is **1.12×**
  — inside the observed window no holder at all, observed or censored, can be up more than 12%.
  The 48-day bound is 16×, so that statement is about the window, not about DREGG's whole life.
* **DREGG's exposure is 30.9% free supply, and it is a known structure, not a discovery.**
  `wallet_labels.yaml` documents holder airdrops of exactly 744.046875 DREGG to 886 recipients
  and 22,778.0 to 77 more, median value ~$0.24. That is what `zero_basis_share` is made of.

**On the operator's escrow, precisely.** The brief notes the operator's own escrow holds 6.26% of
DREGG at low basis, attested and scheduled. **It is not in these numbers.** The five attested
wallets in `wallet_labels.yaml` hold **0.0%** of observed DREGG supply at the window edge, and a
Streamflow escrow is a program account that is not one of them; supply that never traded in the
window has no basis row and does not enter the gauge at all. So the 30.9% is *other people's*
airdropped supply, and the escrow sits in the censored stratum where the only thing that binds it
is the price-path bound. Attested own supply is never counted as threat here, and in this case it
was never counted at all.

---

## 7. Beyond the brief — is unrealized PnL a live state variable at all?

The realization histogram §4 is built on is a distribution over **actions**. It says where sells
happen; it does not say the PnL level caused them, because it has **no denominator**. A wallet
that sells at +40% may simply have been holding while the price was at +40%.

`hazard` supplies the denominator. It lays a fixed 60-second clock over each coin and emits one
row per tick that each wallet-episode was alive for, carrying that wallet's own unrealized PnL at
that tick and whether it sold during the tick. That is a discrete-time hazard with a real risk
set, and its shape in PnL is the thing a reactive exit rule would have to exploit.

**Volatility control**, per PROGRAM.md §3 (anything drawdown-adjacent gets one): a wallet deep in
the red is disproportionately holding a coin that is moving violently, and a violent coin has
more selling of every kind. The hazard is reported raw and stratified by the coin's own trailing
realized volatility, so "red wallets sell more" cannot be read off a difference that is really
"volatile coins trade more".

### 7.1 The answer: yes, and the state that matters is *proximity to break-even*

1,500 coins, 618,783 wallet-episodes, 15.0M risk-set ticks.

| unrealized PnL | ticks | P(sell within 60 s) | wallets |
|---|---|---|---|
| < −80% | 1,800,906 | 0.331% | 24,538 |
| −80 .. −50% | 1,761,061 | 0.486% | 41,830 |
| −50 .. −25% | 1,395,095 | 0.706% | 54,608 |
| −25 .. −5% | 1,242,553 | 1.378% | 70,770 |
| **−5 .. +5%** | 1,325,353 | **2.234%** | 93,917 |
| +5 .. +25% | 1,488,866 | 1.458% | 89,113 |
| +25 .. +100% | 1,440,206 | 1.336% | 74,342 |
| +100 .. +400% | 706,814 | 1.176% | 32,051 |
| > +400% | 1,860,712 | 0.479% | 28,324 |

**An inverted U with its peak at break-even.** The hazard is **6.7× higher** at break-even than
in the deep-red bucket and **4.7× higher** than in the deep-green bucket. It is monotone in
|PnL| on both sides.

That is the mechanism behind the +4.89× break-even spike in the realization distribution
(§4.4). The spike is *not* just "price passes through break-even so sells happen there" — the
conditional probability of selling is genuinely highest there, against a proper denominator.

### 7.2 It survives the volatility control, in the stratum where the control is meaningful

| PnL bucket | low-vol tercile | **mid-vol tercile** | high-vol tercile |
|---|---|---|---|
| < −80% | 3.51% *(n=56k)* | 0.248% | 0.208% |
| −80 .. −50% | 0.692% | 0.555% | 0.384% |
| −50 .. −25% | 0.690% | 0.941% | 0.472% |
| −25 .. −5% | 2.997% | 1.712% | 0.759% |
| **−5 .. +5%** | 2.854% | **2.227%** | 1.150% |
| +5 .. +25% | 0.908% | **2.925%** | 1.333% |
| +25 .. +100% | 0.933% | 2.472% | 0.818% |
| +100 .. +400% | 0.892% | 2.009% | 0.636% |
| > +400% | 0.383% | 2.275% | 0.664% |

**Read the middle column and distrust the outer two**, and the reason is composition, not noise.
The low-vol tercile has 1.62M ticks above +400% and 56k below −80%; the high-vol tercile is the
mirror. Calm coins are the ones that ran up and stayed up, so the extreme buckets in the outer
terciles are nearly empty of the wallets that would populate them — the 3.51% in the low-vol
deep-red cell rests on 56k ticks from a handful of coins. In the middle tercile, where every
bucket carries 69k–874k ticks, the shape is intact: **0.25% → 2.23% at break-even → 2.93% just
above it, then falling**. The peak shifts one bucket right of break-even, which is if anything
the more sensible reading — a wallet takes the first green it sees.

**What this is worth, stated conservatively.** It is a population hazard, not an edge. It says
the cost-basis distribution of a coin's holders is a *live* predictor of near-term sell pressure:
supply sitting near break-even is the supply most likely to hit the bid in the next minute, and
supply far red or far green is comparatively inert. That is a usable state variable for a
reactive exit — approaching a price level where a large mass of basis sits is approaching a
region of elevated sell hazard — and it is the *only* thing in this study that survived its
controls in that direction. But §3 shows that the same idea framed as "reversal levels align
with basis-density modes" does **not** survive, so the honest version of the claim is the narrow
one: elevated hazard, measured; price prediction, not established.

---

## 8. What this does not establish

* **The window is ten days.** Every base rate here is a ten-day base rate in one regime, and
  PROGRAM.md §3 rule 6 is explicit that this market shifts in weeks.
* **The cohort excludes coins born before 2026-08-05.** That is the dominant exclusion, not the
  ≥30-touch filter — see §2.4. Any wallet trading older coins is partially observed, and the
  operator's own four coins are entirely in that stratum.
* **The pool route is marked at last trade**, not at a true marginal price, because pool reserve
  *levels* are unrecoverable from this corpus. The substitution's error is measured (§2.1) but it
  is not zero.
* **Recall of the corpus itself is unmeasured.** The `%pump` suffix is a convention, not a
  guarantee (`scripts/pump_history.py`): high precision, unknown recall.
* **The sniper crews are a proxy for actors, not actors.** A crew could be one operator running
  many wallets, or several independent bots racing the same launches. A weak crew signal is
  therefore consistent with either "policy does not identify actors" or "co-sniping does not
  identify actors", and this study cannot separate those two.
* **Nothing here is a trading rule.** §7 is a population hazard, not an edge; it is measured
  against no fee, no slippage, and no adverse selection.

---

## 9. Reproduce

```
uv run --group research python -m studies.unrealized_pnl flow      # trade legs with exact SOL
uv run --group research python -m studies.unrealized_pnl basis     # the average-cost trajectory
uv run --group research python -m studies.unrealized_pnl check     # falsify it; FIFO sensitivity
uv run --group research python -m studies.unrealized_pnl describe  # the distribution + round-number test
uv run --group research python -m studies.unrealized_pnl hazard    # P(sell | unrealized PnL)
uv run --group research python -m studies.unrealized_pnl q1        # basis density vs reversals
uv run --group research python -m studies.unrealized_pnl q2        # the fingerprint, both controls
uv run --group research python -m studies.unrealized_pnl q3        # the basis-shape feature
uv run --group research python -m studies.unrealized_pnl q4        # the rug-fuel gauge
uv run --group research python -m studies.unrealized_pnl bounds    # long-window censoring bound
```

Everything reads the on-disk corpus; nothing touches the network, signs anything, or reads the live
sentinel's state. **Spend: $0.** Outputs land in `state/upnl/`.
