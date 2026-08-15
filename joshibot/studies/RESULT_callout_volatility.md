# RESULT: callouts as a VOLATILITY signal — the reframe survives, and then dies to the chain

Run 2026-08-15 against the all-pump.fun corpus, pinned to the callout census window.

```
uv run --group research python -m studies.callout_volatility --build     # one DuckDB pass
uv run --group research python -m studies.callout_volatility --validate  # the instrument
uv run --group research python -m studies.callout_volatility --report --draws 200
```

Full output at `studies/data/callout_volatility_run.txt` (untracked; `studies/data/` is
gitignored). Code: `studies/callout_volatility.py`. Estimator tests:
`tests/test_callout_volatility.py`. Deterministic given `--seed`; no network, no writes
outside `studies/data/callout_volatility/`.

**Spend: $0.** Everything runs off tapes this repo already bought — the 459-callout census
`callout_backfill.py` purchased, the 106.6M-row BigQuery pump corpus, and the boards tape.

---

## 0. The one-paragraph answer

**A callout marks two-sided flow, and it tells you nothing you could not already have read
off the chain ten minutes earlier — and nothing at all about volatility.** Conditional on
market cap and age, callout activity predicts forward two-sided flow and forward wiggle
amplitude enormously — the median called coin sees **33 both-sided trades in the next hour
against 2** for a market-cap- and age-matched control, and offers an oracle-harvestable
**+53.6% at 1 h** where the median control offers **exactly zero**. All 18 flow and wiggle
cells survive BY-FDR, and the effect clears BOTH nulls — the rotation null that scrambles
timing and the mint-swap null that scrambles identity — at each null's own resolution floor
of p = 0.005 over 200 draws. It does **not** predict realized volatility under any
specification: **0 of 9 RV cells survive**, and the sign flips across the two halves of the
window. And when the trades already visible on chain in the ten minutes *before* the callout
are also partialled out, the flow slope loses **58%** of its size and the rotation null's own
median max|z| rises from 1.85 to **5.21** — so the observed 6.17 becomes an ordinary draw,
**p = 0.199**. The signal is real, redundant, and late.

That is a coherent, mechanism-consistent picture rather than three separate results.
`RESULT_caller_wallets.md` measured the callout arriving a median **26 seconds after** the
161-wallet buy burst it echoes, and measured that 51.4% of the feed is referral spam from 13
accounts. A machine echoing a burst is exactly what a marker of flow looks like, and exactly
what a lagged, redundant view of flow looks like. Both halves of this study are that one
fact seen from two directions.

**The operator's reframe was right about the target and wrong about the instrument.** They
were right that the earlier studies asked the wrong question — direction was never their
strategy, and flow is what a wiggle-scalper and an LP both harvest. They were wrong that the
callout feed is the way to see it: the chain shows the same thing sooner, and this study is
the first here to put a number on how much sooner is worth.

**Consequences, in the order they change decisions:**

1. The wiggle book conditions on **observed two-sided flow**, not on callouts
   (`shitcoims_paperdesk.wiggle.CALLOUT_ARM = "ignored"`). The feed stays wired in as a
   **candidate generator** — it routes coins into the desk's view that the boards may never
   carry — which is precisely the role `RESULT_callout_edge.md` §6 left it after the
   direction study. Two independent questions, same verdict about the same feed.
2. **Flow up, volatility flat is the LP-favourable combination**, and nobody had noticed.
   The toll book's gate is `eta = 2 f N / (C · RV)`: fee income is linear in trade count `N`
   and the loss term is linear in realized variance `RV`. A condition that raises `N` while
   leaving `RV` alone raises `eta` directly. §6 works this through; it is the most
   actionable thing in the file and it is not about scalping at all.
3. **The opportunity is not scarce.** §7 counts the wiggle book's own entry conditions over
   the whole corpus rather than over the callout cohort, and the binding constraint on a
   0.1 SOL desk is bankroll and attention, not candidates.

---

## 1. Why this is a different question from the two studies before it

`RESULT_callout_edge.md` and `RESULT_caller_wallets.md` measured `E[return | callout]` and
found an anti-signal with a monotone loudness gradient: buying what the feed names returns
**−11.9% at 1 h** and **−43.6% at 8 h**, two or more callers within ten minutes returns
**−64.7%**, and a caller with over 10k followers returns **−65.8%**. Entity-level Spearman of
follower count against the 8 h return is **ρ = −0.502** on 101 mints.

Every one of those is a statement about **direction**, and the operator's objection to
treating it as the last word is correct. Their live pattern takes no directional view: it
scalps oscillations at the bottom of collapsed coins, and an LP position takes no view by
construction. Both harvest **two-sided flow**. A signal can be worthless for direction and
valuable for flow, and nothing measured so far distinguished those.

The mechanism the earlier work established actively supports the reframe. A callout is not a
cause; it is a **latency-delayed marker of an on-chain burst that already happened**. As a
directional signal that is fatal — you are buying after the buyers. As a flow marker it is
exactly the right shape. So the pre-registered question is:

> Conditional on the free numeric columns (market cap, age — the baselines that score
> AUC 0.796 at 1 h where the callout block scores 0.471), does callout activity predict
> **(a)** realized volatility over the next 1 h / 4 h / 8 h, **(b)** two-sided flow
> persistence, **(c)** wiggle quality — the amplitude and frequency of oscillations clearing
> round-trip friction — at the bottom of collapsed coins?

---

## 2. The instrument, and the identity that made it free

### 2.1 Why not the boards tape

Every prior return study here priced through `state/boards/`. For a **board-entry** event
that is correct: the event is *defined* by board membership. For a **callout** it is wrong
twice over, and `studies/callout_prices.py` had already written down why: a callout mint is
priced only while it sits in some board's top 50, so joining on the board tape conditions
the cohort on attention — which is downstream of the callout and therefore a **collider** —
and it makes "left the boards" look like missing data when it is really the outcome.

So prices come from `state/bulk_pump/daily/`: 106.6M rows, ten UTC days, every pump.fun coin
that moved a balance. It prices a coin whether or not anyone is watching, and it contains
the whole population — which means the **matched control arm** that `RESULT_callout_edge.md`
§9 named as its top open item and could not run is free here rather than a second
collection.

### 2.2 The identity

A pump.fun bonding-curve trade carries only the TOKEN leg on chain: the curve holds native
SOL in the PDA's lamports, not a token balance, so the SOL side is invisible in this corpus.
It does not need to be visible. On a constant product `k = v_sol · v_tok`:

```
price = v_sol / v_tok = k / v_tok²        ⇒        log p = log k − 2 log v_tok
```

and `v_tok = curve_ata_balance + OFFSET`. **Both constants cancel out of every quantity this
study measures**, because volatility, drawdown and wiggle amplitude are all functions of
log-price *differences*. `tests/test_callout_volatility.py` asserts that directly: the same
path on three different `k` values yields identical log-differences to 1e-12.

For a MIGRATED coin the counterparty is a PumpSwap pool holding both legs, so
`log p = log(wsol) − log(tok)` is read off with no constants at all.

### 2.3 The instrument check — the launch parameters, recovered from chain

`--validate` ASOF-joins each boards observation of a non-migrated mint to the last bulk-tape
print at or before it, and reads two numbers the boards vendor serves directly:

| quantity | measured |
|---|---|
| matched board observations | **27,076** |
| `v_tok − curve_ata_balance` | median **exactly 7.30e13**, IQR [7.242e13, 7.397e13] (±1.1%) |
| `v_sol · v_tok` | median **3.219e25**, within 1e-6 of it for **64.3%** of rows |
| `log k` | **58.7337** at p90 |

Those are the published launch parameters — 30 SOL of virtual quote against 1.073e9 virtual
tokens — recovered from chain rather than quoted from documentation. The residual spread is
boards staleness (the snapshot lags the print) plus coins on a different curve
configuration; a different `k` cancels exactly and a different offset is a ≤1.1% scale
effect on a quantity both arms carry. The constants are pinned in a test so a silent edit
shows up as a failure rather than as a shifted volatility.

### 2.4 The counterparty, and what the corpus cannot do

The bonding curve (or, post-migration, the PumpSwap pool) is identified per mint as the
owner appearing in the most of that mint's transactions, tie-broken by largest balance. It is
the only account on the other side of every trade, so the **sign of its token-balance change
is the trade's side** — balance falls, someone bought; balance rises, someone sold — and its
balance level is the price state variable. Over the panel window: **140,948 pump mints, of
which 25,875 are priced through a migrated pool**, and **23.5M priced counterparty prints**.

Three honest limits, all inherited from the corpus and documented in
`scripts/pump_history.py`:

- **Every row is a success.** `err = ''` for all 106.6M rows; the export dropped reverts. No
  failure-rate fingerprint is available.
- **Boosted PumpSwap pools are not replay-grade.** Their virtual quote term lives in
  `log_messages`, which is empty for this window. Vault levels are exact; the curve reserve
  is not derivable.
- **Recall is unmeasured.** Selection is by the `%pump` mint suffix, a convention rather than
  a guarantee. High precision, unknown recall.

---

## 3. Design, and every methodological choice that cost something to learn

**Population.** 426 deduplicated callouts on 318 mints from the census
`state/callouts/backfill-1786717285-1786753261.jsonl`, over 2026-08-14T14:21Z →
2026-08-15T00:21Z. Deduplication is on (mint, caller, minute), because the census was bought
with four overlapping discovery queries and one tweet returned by two of them is one callout
(437 exploded rows → 426). The same discipline matters more in the live store, where the
daemon re-observes a single tweet up to 22 times — an undeduplicated count there would
measure collector cadence rather than callout activity. Bot echoes are *kept* even though
`RESULT_caller_wallets.md` measured 51.4% of the feed as referral spam from 13 accounts: an
echo is still a marker of the burst it echoes, which is exactly the hypothesis under test.

**Control arm.** A control is a mint that (i) traded within five minutes of the same instant
`t0`, (ii) sits in the same log-market-cap and log-age bin, and (iii) carries **no callout
anywhere in the census**, not merely none before `t0` — a coin called out an hour later is a
treated coin observed early, and leaving it in the control arm biases the contrast towards
zero. Each candidate is offered up to eight independent instants drawn from the treated rows
themselves, so the control arm inherits the treated arm's clock exactly; the diurnal envelope
in this market is 3.6–5.4× and an arm sampled on a different clock recovers that instead of
an effect. Instants are drawn before any outcome is computed, so the matching is on the
conditioning variables and never on the outcome.

**Outcomes.**

- `rv` — realized variance of log returns on a **fixed 60-second grid**. Fixed rather than
  trade-driven on purpose: variance measured between consecutive trades is a function of
  trade *arrival*, and trade arrival is the very thing a callout is suspected of marking.
  Measuring the outcome on the same clock as the suspected exposure guarantees a positive
  result and means nothing. A minute with no trade carries the last price forward and
  contributes a zero return, and `active_minutes` is reported alongside so a low RV from a
  dead coin is never confused with a low RV from a calm one.
- `log_two_sided` — `log1p(min(buys, sells))` over the horizon. `min` rather than the sum,
  because a one-way slide prints plenty of trades and has nothing to harvest.
- `wiggle_net` — the zigzag (directional-change) filter at the coin's own round-trip cost
  from `shitcoims_paperdesk.friction` (the corrected module: full three-leg taker costs,
  ~2.4% at the operator's 0.1 SOL clip), reporting `amplitude − swings × friction`. **This
  is an ORACLE bound**: the filter turns at the exact extremes, so no live rule attains it.
  That is the right outcome anyway — a null on the oracle is a null on every rule inside it —
  and every number derived from it is labelled a ceiling.

**Estimator.** Frisch–Waugh: residualise exposure and outcome on log market cap and log age,
regress one residual on the other, cluster the sandwich on **mint**. Below 20 clusters the
estimator returns `nan` rather than a number — measured necessity, not caution: an earlier
null specification whose exposure varied over five mints reported |z| in the twenties out of
nothing, and that pathology is what produced the first, discarded, version of §5's table.

**Corrections.** BY-FDR at q = 0.10 over the declared family of **27** (3 exposures × 3
outcomes × 3 horizons). Benjamini–**Yekutieli**, not Hochberg: the outcomes are nested
windows of one tape and are dependent by construction, so BH's independence assumption is
not available.

**Nulls — two, and a recovery arm.**

| null | what it scrambles | what it therefore asks |
|---|---|---|
| A rotation | every callout time by one common circular offset | does the **timing** carry information? |
| B mint swap | which coin each callout names, matched on mcap and age | does the **identity** carry information? |
| A + planted 0.5 | (rotation, with a proportional effect added) | can the estimator recover a real effect at all? |

PROGRAM.md §3.13: a single null is a knob, not a test — measured on co-trading, two nulls at
nominally comparable thresholds differed 16× in edge count and agreed on 29% of edges on a
world where the clusters were *planted*. Only findings clearing both are carried forward.
§3.12: a green known-zero arm certifies a constant-zero estimator exactly as readily as a
working one, and this tree has shipped that failure twice, so the planted arm is mandatory.

**The null rebuilds the whole cohort**, rather than re-labelling the real one. That is not a
detail. A null that keeps the real treated instants and only relabels them leaves nearly
every row unexposed, so its statistic is computed off a handful of accidentally-exposed rows;
the first version of this study did exactly that and produced a "null distribution" with a
median max|z| of 2.72 and a p95 of **12.73**, which is not a null distribution, it is the
sandwich running out of clusters. Re-drawing the instants gives the null cohort the same
shape as the real one, and only then is the comparison a comparison.

---

## 4. Cohort

| stage | n |
|---|---|
| callouts in the census window | 426 (deduplicated on mint × caller × minute) |
| ... on distinct mints | 318 |
| mints that traded ≥ 5 times in the window | 15,113 |
| mints materialised into the panel | 15,128 (14,876 offered for matching) |
| **treated rows surviving pricing** | **337** |
| **matched control rows** | **432** (579 requested slots unfilled) |
| total rows / distinct mints | 769 / 679 |

---

## 5. The numbers

Transcribed from `studies/data/callout_volatility_run.txt`.

### 5.1 Arm contrast — description, not the estimator

Treated minus matched control, mint-clustered SE. Reported first because it is the most
legible view and last in authority: unfilled bins mean the contrast is matched more weakly
than the regression is conditioned.

| outcome | n_t | n_c | median treated | median control | diff | z |
|---|---|---|---|---|---|---|
| `rv_1h` | 324 | 425 | 0.04843 | 0.00180 | 3.93 | 3.54 |
| `rv_4h` | 324 | 425 | 0.15809 | 0.00671 | 5.51 | 3.96 |
| `rv_8h` | 324 | 425 | 0.17574 | 0.00997 | 5.59 | 4.01 |
| `log_two_sided_1h` | 337 | 432 | 3.5264 | 1.0986 | 3.48 | **14.89** |
| `log_two_sided_4h` | 337 | 432 | 4.0604 | 1.6094 | 3.76 | **15.73** |
| `log_two_sided_8h` | 337 | 432 | 4.1589 | 1.6094 | 3.83 | **16.05** |
| `wiggle_net_1h` | 337 | 432 | 0.4294 | 0 | 10.37 | **8.15** |
| `wiggle_net_4h` | 337 | 432 | 1.3592 | 0 | 12.98 | **7.92** |
| `wiggle_net_8h` | 337 | 432 | 1.4590 | 0 | 13.51 | **8.05** |

In readable units: **the median called coin sees 33 both-sided trades in the next hour
against 2 for its matched control**, and offers an oracle-harvestable **+53.6% at 1 h and
+289% at 4 h** where the median control offers **exactly zero** — its price never completes
one round trip clearing friction. Realized variance is 27× higher too, and §5.2 is where
that stops being true.

### 5.2 The declared family — conditional on log market cap and log age

27 cells; BY-FDR at q = 0.10. Only the primary exposure's rows are shown in full here; the
run file has all 27.

| exposure → outcome | slope | se | z | p | BY |
|---|---|---|---|---|---|
| `log1p_callouts` → `rv_1h` | 2.47 | 1.61 | 1.54 | 0.124 | – |
| `log1p_callouts` → `rv_4h` | −0.32 | 1.92 | −0.17 | 0.869 | – |
| `log1p_callouts` → `rv_8h` | −0.36 | 1.92 | −0.19 | 0.853 | – |
| `log1p_callouts` → `log_two_sided_1h` | 1.478 | 0.289 | **5.12** | 0.0000 | YES |
| `log1p_callouts` → `log_two_sided_4h` | 1.351 | 0.296 | **4.57** | 0.0000 | YES |
| `log1p_callouts` → `log_two_sided_8h` | 1.338 | 0.294 | **4.55** | 0.0000 | YES |
| `log1p_callouts` → `wiggle_net_1h` | 8.52 | 1.32 | **6.47** | 0.0000 | YES |
| `log1p_callouts` → `wiggle_net_4h` | 10.24 | 1.97 | **5.20** | 0.0000 | YES |
| `log1p_callouts` → `wiggle_net_8h` | 10.47 | 2.03 | **5.17** | 0.0000 | YES |

The two secondary exposures agree in sign and significance throughout and add nothing
qualitatively: `recency_s` and `cadence_s` both enter **negative** on flow and wiggle (a
callout more recently, and a faster stream, mean more forward two-sided flow) at |z| 3.2–6.6,
and both are flat on every `rv` cell (|z| 0.4–1.5). **18 of 18 flow and wiggle cells survive
BY-FDR; 0 of 9 `rv` cells do.**

**Verdict (a) — realized volatility: NULL.** Not a weak positive; a null with a flat
gradient, in every specification, at every horizon, on both exposures that are not the
primary one. §5.4 adds that its sign is not even stable across two halves of one afternoon.

**Verdict (b) — two-sided flow persistence: POSITIVE, and large.**

**Verdict (c) — wiggle quality: POSITIVE, and larger.**

### 5.3 The confound — the same family with prior on-chain flow ALSO partialled out

`RESULT_caller_wallets.md` measured the callout arriving a median **26 s after** the buy
burst it echoes. So the question that decides whether the feed is worth opening is whether
anything survives once that burst is itself a control column. `pre_flow` is `log1p` of the
mint's trades in the ten minutes *before* `t0`.

| exposure → outcome | slope | se | z | p | BY |
|---|---|---|---|---|---|
| `log1p_callouts` → `rv_1h` | 1.61 | 1.45 | 1.12 | 0.264 | – |
| `log1p_callouts` → `log_two_sided_1h` | 0.615 | 0.136 | 4.52 | 0.0000 | YES |
| `log1p_callouts` → `wiggle_net_1h` | 6.16 | 0.999 | 6.17 | 0.0000 | YES |

The parametric table says the effect survives — and **the null says it does not**, and the
null is the arbiter. §5.5 has the arithmetic: under the flow-controlled specification the
rotation null's own median max|z| rises from **1.85 to 5.21** and its p95 to **7.26**, so an
observed 6.17 is an ordinary draw (**p = 0.199**) rather than an exceptional one. Partialling
out a column this strongly correlated with the exposure inflates the residual variance, the
cluster sandwich does not know it, and the permutation distribution does. This is precisely
the regime PROGRAM.md §3.10 ("run the null") exists for: when the parametric and the
resampled answers disagree, the resampled one is the measurement, because it is calibrated
on this data and the sandwich's asymptotics are not.

Note also the coefficient's collapse in size: **the callout column loses 58% of its flow
slope** (1.478 → 0.615) the moment the burst it echoes is controlled.

**Verdict: the callout adds nothing over the flow it is a late view of.**

### 5.4 Per-window — the only regime check ten hours can support

| half | rows | `rv_1h` | `log_two_sided_1h` | `wiggle_net_1h` |
|---|---|---|---|---|
| 1 | 383 | −0.16 (z −0.2) | 1.393 (z 3.4) | 10.39 (z 4.9) |
| 2 | 386 | +4.58 (z +1.7) | 1.713 (z 4.2) | 7.54 (z 4.7) |

Flow and wiggle are stable in sign, magnitude and significance across both halves. **`rv`
flips sign.** A coefficient that changes sign across two halves of one afternoon is not a
finding whatever its pooled z says, and this is the second independent reason to read (a) as
a null rather than as an underpowered positive.

### 5.5 The nulls

| null | draws | median | p95 | max | observed | p |
|---|---|---|---|---|---|---|
| A rotation (timing) | 200 | 1.85 | 2.96 | 4.20 | 6.47 | **0.0050** |
| B mint swap (identity) | 200 | 3.30 | 4.94 | 6.10 | 6.47 | **0.0050** |
| A rotation + planted 0.5 | 50 | 3.13 | 4.50 | 4.82 | — | — |
| A rotation, flow controlled | 200 | **5.21** | 7.26 | 8.54 | 6.17 | **0.199** |

- **Both primary nulls are cleared**, each at its own resolution floor of `1/(1 + draws)`.
  The observed 6.47 exceeds every one of 200 rotation draws and 199 of 200 swap draws.
- **The planted arm recovers.** A 50% proportional effect moves the rotation null's median
  from 1.85 to 3.13, so the estimator is not a constant-zero machine passing its zero
  control by being broken — the failure PROGRAM.md §3.12 exists to catch, and which this
  tree has shipped twice.
- **The two nulls disagree in width by a factor of ~1.8** at matched cohort shape (medians
  1.85 vs 3.30), which is the §3.13 point restated: reporting only the rotation null would
  have made the finding look nearly twice as strong as the intersection supports.
- **The flow-controlled null is where the study turns.**

### 5.6 Censoring and survival

| horizon | share of rows whose window runs past the corpus end |
|---|---|
| 1 h | 21.2% |
| 4 h | 51.5% |
| 8 h | **87.4%** |

Fitted with `lifelines`: **treated coins have a median active time of 441 min against 335
min for matched controls** (n = 325 / 429), where a coin still trading at the corpus edge is
declared censored rather than dead. Called coins live longer, which is consistent with (b)
and with nothing else here — it is a flow statement, not a return statement, and
`RESULT_callout_edge.md` already established that living longer and going up are different
things on this population.

---

## 6. The unexpected result, and it is about the LP book

The toll book's gate is exact, from `RESULT_circuit_theory.md` §4.2:

```
eta = 2 f N / (C · RV)          enter when   eta · D > VR
```

Fee income is linear in the **trade count `N`**; the loss-versus-rebalancing term is linear
in **realized variance `RV`**. This study measures a condition under which `N` rises
enormously — the median called coin sees 33 both-sided trades an hour against a matched
control's 2 — while `RV` does not move at all once market cap and age are controlled.

**That combination moves the RATIO, which is what no knob turned so far has been able to
do.** Concentration cannot: `C = T/W` scales the fee ledger and the loss ledger by the same
`4/W`, so narrowing the range levers the loss exactly as hard as the gain and is
sign-preserving (`RESULT_lp_strategy.md` §2 — the part that keeps getting hoped away).
Width, rebalance trigger and duty cycle are all inside the same identity. A market condition
that lifts `N` while leaving `RV` alone is a *different kind of object* from all of them,
and this is the first measurement in this repo that identifies one.

Three caveats before anyone acts on it, in order of severity:

1. **It is measured on bonding-curve coins, and the toll book is an LP book on graduated
   pools.** Nothing here says the flow burst survives migration.
2. **`RV` flat is measured on a one-minute grid over one to eight hours; the toll gate wants
   `RV` at the LP holding horizon** (days), where this study says nothing.
3. **`N` here is a trade COUNT, and fees are proportional to VOLUME.** A burst of dust buys
   raises `N` without raising fee income. §9 flags the size-weighted version as one query
   away, and it is the single highest-value follow-up in this file.

It is a lead, not a result. But it is a lead pointing at the one book on the desk whose gate
currently refuses essentially everything, and it arrived from a study about scalping.

---

## 7. The opportunity count — the operator's "at scale" question

Counted over the **whole corpus**, not over the study cohort. Counting inside the cohort
would answer "how many candidates exist among coins people tweeted about", which is a much
smaller and different question. A candidate-minute is a minute at which a coin satisfies
every condition the wiggle book's entry rule checks and the corpus can see: collapsed ≥70%
from its own running peak, pool depth ≥5 SOL (the ghost-town floor), and ≥2 buys **and** ≥2
sells in the trailing ten minutes.

| measure | 10.0 h window | linear projection to 24 h |
|---|---|---|
| candidate-minutes | 48,890 | 117,336 |
| coin-hours (episodes a book could take a position in) | 4,408 | **10,586** |
| distinct coins | 2,288 (**6.6%** of the 34,719 that traded at all) | **5,495** |

**The opportunity is not scarce, and candidate supply is not the binding constraint.** The
boards feed alone, over the same window, carries **4,934 distinct mints** that are at some
observation both collapsed ≥60% and traded within the last 180 s — and **2,687** even at the
strictest corner of the jitter box (≥85% collapsed, traded within 30 s). The desk saturated
its eight position slots within three minutes of being restarted with this book live.

### 7.1 What it would earn at the operator's own seed — a PROJECTION, labelled

The seed is the operator's measured live performance, not this desk's: **7/13 winners and
+$3.09 over 36 h** under a five-minute hold, which is **+$0.238 per round trip**, or
**+3.14%** on a ~$7.58 (0.1 SOL) clip. Their own throughput was 8.7 round trips a day.

The book's throughput is bounded by concurrency and the clock, not by candidates:

| configuration | round trips/day | at +3.14%/trade on 0.1 SOL |
|---|---|---|
| operator, measured | 8.7 | +$2.06/day |
| desk, 8 concurrent × 5 min, theoretical saturation | 2,304 | +7.2 SOL/day ≈ **+$549/day** |
| **desk, MEASURED live** (10 closes in the 7 min after the bounce, 8 slots full) | **~2,057** | ≈ +$490/day |
| desk, 4 concurrent × 5 min | 1,152 | +3.6 SOL/day ≈ +$274/day |

The measured row is the one to read: with this book live under launchd the desk filled all
eight slots inside three minutes and turned them over ten times in seven, at a **median hold
of 5.1 minutes and a maximum of 6.5** — the clock holds, and throughput is already ~89% of
its theoretical ceiling. Exits so far: 7 deadline, 3 stop-loss, which is the intended
shape (the clock does the work; the stop is the tail).

**Every assumption in that table is doing work, and three of them are load-bearing:**

1. **+3.14%/trade is the operator's number on 13 hand-picked trades, and this book would run
   ~240× as many chosen by a rule.** That is the assumption most likely to break, and it
   breaks in the obvious direction: a discretionary trader takes the setups they like, and
   selection quality at 2,000 trades a day is not selection quality at 8. The seed is net of
   friction (it is realized chain P&L), so this is not a gross-to-net error — it is a
   selection-at-scale error, and it is the whole reason the desk is a paper desk.
2. **This desk's own first 11 closes are −14.08%** (as of 2026-08-15T16:05Z, 8 deadline
   exits and 3 stops), and its first close was **−65.6%** (a stop armed at −16.5% that filled at −64.7% because the coin gapped
   through between observations — the finding that produced this book's marking-cadence
   entry condition and the desk's refresh-priority fix). n = 10 is noise, and it is noise
   pointing the other way from the projection.
3. **A 0.1 SOL clip at 2,000 trades a day is 200 SOL of daily turnover** against a desk
   bankroll of 5 SOL per book. The clip is small; the *turnover* is not, and nothing here
   has measured whether the market absorbs our own flow at that rate. The GHOST_TOWN guard
   prices one clip's impact, not a day of them.

The right reading of this table is its **shape**, not its levels: the operator's throughput
is ~0.4% of what a mechanical version of their own rule could run, and the constraint on
closing that gap is bankroll and discipline rather than opportunity. Whether the edge
survives at that throughput is exactly what the paper desk is now running to find out, and
`shitcoims_paperdesk.report`'s WIGGLE section is where the answer will appear — as the
holding-time distribution first and the P&L second, because the leak being fixed is
behavioural.

---

## 8. What this changes

1. **The wiggle book conditions on flow, not on callouts.**
   `shitcoims_paperdesk.wiggle.CALLOUT_ARM = "ignored"`. The feed stays wired in as a
   candidate generator; `callout_n_60m` is logged on every decision and gates none of them,
   and because the epsilon arm gives overlap on the action it stays identifiable
   off-policy — so the ledger can overturn this verdict without anyone re-running the study.
2. **`RESULT_callout_edge.md` §9 item 1 is discharged.** The matched control arm it named as
   its top open item is §5.1, and it comes out the same way its own §6 predicted: the feed's
   value is that it hands you a population, and the judgement has to come from the numbers.
   Two independent questions — direction, then volatility — one answer about the same feed.
3. **Do not build a callout-driven volatility strategy.** Same shape as
   `RESULT_callout_edge.md` §9 item 5, for a different reason: not because the signal is
   absent, but because it is late and redundant.
4. **Look at `N` at flat `RV` for the LP book** (§6), size-weighted (§9).

### 8.1 The book this parameterised, for the record

`shitcoims_paperdesk.wiggle.WiggleBook` — the desk's fourth book, live under
`com.shitcoims.paperdesk` since 2026-08-15T15:50Z. Its opening rules, and where each number
comes from:

| | rule | jitter box | source |
|---|---|---|---|
| EXIT | hard clock | **240–420 s** | the operator's 36 h reconstruction: 7/13 and +$3.09 under 5 min, 1/20 and −$61 beyond |
| EXIT | take-on-wiggle-up | +3% to +9% | must clear ~2.4% round-trip friction; below it a "win" books a loss |
| EXIT | stop | −10% to −25% | wide *because* the clock is the real exit |
| ENTRY | collapse | drawdown ≥ 0.60–0.85 | the brief's conditioning; `drawdown_known` asserted, never inferred from `-1.0` |
| ENTRY | GHOST_TOWN depth | pool ≥ 5–25 SOL | derived: at a 0.1 SOL clip, 5 SOL = 2.00% own-exit impact (PROGRAM.md §1.4 ceiling), 25 SOL = 0.40% |
| ENTRY | GHOST_TOWN staleness | last trade ≤ 30–180 s | `RESULT_crime_signatures.md` §7.1: a fossil quote is thin *and* stale |
| ENTRY | own-exit impact | ≤ take_profit ÷ 3–8 | the guard restated as the thing it protects |
| ENTRY | two-sidedness | ≥ 0.25–0.60 of direction flips | **this study's surviving variable**; needs ≥3 observations, otherwise unmeasured and not pretended otherwise |
| ENTRY | marking cadence | ≥ 0.5–2.0 obs/min | learned live: a stop armed at −16.5% filled at **−64.7%** because the next observation came 43 s later |
| ENTRY | callouts | **logged, gates nothing** | this study, §5.3 |
| SIZE | clip | 0.1 SOL, capped by pool impact | the operator's own sizing; *not* `B* = sqrt(priority·Y)`, which lands at 0.03–0.06 SOL here |

The tripwire that matters: a drawn horizon beyond `MAX_HOLD_S` (900 s) becomes a **defect
row rather than a position**. Discipline drift would enter this system as a widened jitter
box, and that is the one place it can be caught mechanically.

---
## 9. Trials accounting and honest limits

Configurations evaluated: **27 declared cells**, each fitted twice (with and without the
flow control) = 54, plus 9 arm contrasts, 3 per-window cells × 2 halves, and 4 null
distributions. Call it **~75 configurations**. PROGRAM.md §3.9: past ~7 independent
configurations an in-sample Sharpe of 1 corresponds to an out-of-sample zero. Applied here
that is an argument *for* the two verdicts offered — the flow/wiggle effect is large,
monotone across three horizons and three exposures, and clears two independent nulls at
their resolution floor; the RV null is flat everywhere, in every specification, in both
halves of the window. Neither rests on a marginal cell.

Limits, stated plainly:

- **One 10-hour window of one day.** Regime shift in this market is measured in weeks
  (PROGRAM.md §3.6). §5.4 splits the window in half as the only regime check ten hours can
  support. Nothing here is a claim about next Tuesday, and
  `shitcoims_paperdesk.wiggle.CALLOUT_ARM` is written as a verdict with an expiry date.
- **The corpus ends before the census does.** `state/bulk_pump/daily/` stops at
  2026-08-15T00:00Z, so the longer horizons are heavily administratively censored — the
  share is printed per horizon in §5.6 and it is severe at 8 h (87.4%). Read the 1 h column
  as the measurement and the 4 h / 8 h columns as consistency checks.
- **The arm contrast is descriptive; the regression is the estimator.** The matched control
  arm does not fill every requested slot, because a treated row's (mcap, age) bin sometimes
  has no live coin in it at that instant. An unfilled bin means the contrast is matched more
  weakly than the regression is conditioned, so §5.1 is reported as description and every
  verdict rests on §5.2 and §5.3.
- **Two-sidedness is buy/sell COUNTS, not size.** The corpus gives the counterparty's
  balance change, so a 0.01 SOL dust buy and a 10 SOL buy count the same. A size-weighted
  version is a strictly better outcome variable and is one query away; it is not in this run.
- **The wiggle numbers are an oracle ceiling.** Stated everywhere they appear, and it is the
  single easiest number in this file to misread as a return.
- **`log_two_sided` and `wiggle_net` are not independent.** More trades give the zigzag more
  chances to cross its threshold. They are reported as two views of one thing rather than as
  two confirmations, and BY (not BH) is the correction precisely because of it.
- **The flow control is one window length, chosen once.** `pre_flow` counts the ten minutes
  before `t0` because `RESULT_caller_wallets.md` put the callout a median 26 s behind its
  burst and ten minutes is an order of magnitude past that. It was not tuned, and no other
  width was tried and discarded — but it is a knob, and a shorter one would leave more for
  the callout column to explain.
- **Recall on the corpus is unmeasured** (§2.4), and the counterparty is identified by a
  heuristic (§2.4) rather than by a program-derived PDA. Neither is likely to bite an
  aggregate over 140,948 mints; both would bite a claim about a particular coin.
