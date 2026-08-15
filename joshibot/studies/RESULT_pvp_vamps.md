# RESULT: PvP and vamps — the state is real, the arena is not, and the drain is 3% of nothing

Run 2026-08-15 against the ten-day all-pump.fun corpus, plus a live case study collected the
same afternoon.

```
uv run --group research python -m studies.pvp_vamps flow        # ~65 s, the whole tape
uv run --group research python -m studies.pvp_vamps rotation
uv run --group research python -m studies.pvp_vamps panel
uv run --group research python -m studies.pvp_vamps classify --null-draws 24
uv run --group research python -m studies.pvp_vamps arena
uv run --group research python -m studies.pvp_vamps transition
uv run --group research python -m studies.pvp_vamps vamp --null-draws 30
uv run --group research python -m studies.pvp_vamps regimes
uv run --group research python -m studies.pvp_vamps burst
uv run --group research python -m studies.pvp_vamps opnow
uv run --group research python -m studies.pvp_vamps duel-fetch --pattern glasses --day 2026-08-15
uv run --group research python -m studies.pvp_vamps duel --pattern glasses
```

Code: `studies/pvp_vamps.py`. Artifacts under `studies/data/pvp_vamps/` (gitignored); trade
tapes cached under `.cache/pvp_vamps/`.

**Spend: $0.00.** No BigQuery. The corpus was already bought; every live endpoint used
(`swap-api.pump.fun/v2/coins/<mint>/trades`, `/v1/coins/<mint>/candles`,
`frontend-api-v3.pump.fun/coins/<mint>`) is keyless and free.

---

## 0. The one-paragraph answer

**PvP is measurable, it is mostly coin age wearing a costume, it is the wrong state to own an
arena in and the right state to scalp, and a vamp really does drain its host — of about three
percent of the clone's own funding, which is nothing.** A five-column PvP meter built from
wallet-level flow scores **AUC 0.880** for "this coin stops trading within an hour" against
the incumbent `recycled_30m`'s **0.720**, survives a matched block-permutation null 24 of 24
draws, and adds a real if small **+0.005 AUC** over market cap, age and activity. But
conditional on age band its univariate AUC collapses to **0.485–0.560**, and inside the
under-30-minute band where the decisions actually happen the incumbent `recycled_30m` **beats
it 0.622 to 0.505** — so the headline is age, and the honest incremental claim is the small
one. The brief's strong hypothesis, that PvP coins are the eta-favourable LP arena, is
**refuted with a sign and a mechanism**: PvP raises realized variance **127×** and collapses
pool depth **18×** while forward volume barely moves, so `eta = 2fN/(C·RV)` falls monotonically
from **0.585 to 0.085** across deciles 0→8, and the apparent recovery in the top decile is the
GHOST_TOWN artifact (`RV → 0` because nothing trades) which a fee floor deletes. The same
state read from the other book inverts: oracle harvestable wiggle amplitude net of friction
rises by three and a half orders of magnitude (**0.00033 → 1.139**) across the same deciles, and the share of buckets
where a round trip clears friction at all goes from **50% to 96%**. **PvP is a negative
selector for the toll book and a positive selector for the wiggle book.** The vamp drain is
directionally real — a clone takes **3.4%** of its own buying from wallets that just sold its
host, **32× the naive null and 4.2× a size- and time-matched rotation null** — and it does not
predict host deterioration once size and age are matched (p = 0.068 / 0.096, n = 87 pairs).
And PvP-transition is **not** an early exit signal: it fires before the price break on 31.6% of
qualifying coins against a matched null's 25.9%, with a **median lead of exactly zero**.

Two things that were not in the brief and matter more than parts of it:

1. **The graduation cliff caught a real bug, and the operator caught it by asking why the
   cliff was not a cliff.** Reconstructed curve raises had median 80.98 SOL against pump.fun's
   85 SOL threshold with an IQR of [65, 101] — a hump, where a fixed protocol constant has to
   be a spike. The cause was the create transaction: the curve's net token delta on that row
   is `supply − dev_buy`, which biased every price on every coin and, through the sign filter,
   **silently deleted every dev buy in the corpus**. Fixed, the reconstructed graduation raise
   reads **85.01 SOL at the 25th, 50th and 75th percentiles** and the reserved pool supply
   reads **20.7% of opening = 206.9e6 tokens** — two protocol constants, four significant
   figures, off token balances alone. §1.3.
2. **A live duel, at one-second resolution, with wallet identities** — twenty-two `glasses`
   branches on 2026-08-15, the original peaking at 17:19:31Z and falling 89% in eight minutes,
   with three derivative launches inside twelve minutes of the top. The cascade that made it
   run is a **198 SOL buy burst inside one minute** on a coin that had been doing 1–3 SOL/min,
   arriving **four minutes before the top and three seconds before the first rival launch**.
   Chain first, by the width of a launch transaction. §9.

---

## 1. The instrument

### 1.1 Exact SOL from the token leg alone

A pump.fun bonding-curve trade carries only the token leg on chain: the curve holds native SOL
in the PDA's lamports, which is not a token balance. `studies/operator_crime.py` uses that to
get log-price up to a constant, which is enough for volatility and drawdown. It is not enough
here — a vamp drain is SOL-weighted and `eta`'s fee term is proportional to volume — so the
identity is taken one step further. On a constant product `v_sol · v_tok = K`:

```
sol_lamports_paid  =  K · (1/v_tok_after − 1/v_tok_before)
```

which is the **exact** SOL leg, recovered from the token leg alone. Both curve configurations
in this corpus share the same virtual reserves (`v_tok_virt = 1.073e15` raw,
`v_sol_virt = 3e10` lamports, `K = 3.219e25`); they differ only in opening real supply
(7.931e14 raw for the older config, 1.0e15 for the newer), so `OFFSET(mint) = 1.073e15 −
initial_curve_balance`. `RESULT_callout_volatility.md` §2.3 recovered the same two constants
independently from 27,076 board observations; this module re-derives the offset per mint from
the curve's own opening balance rather than assuming the median.

For a migrated coin the counterparty is a PumpSwap pool holding both legs, so the pool's WSOL
vault delta *is* the SOL leg and no identity is needed. Every trade row records which route
priced it.

| | |
|---|---|
| cohort | coins with ≥100 counterparty touches, born inside the corpus window |
| coins | **33,880** |
| priced trade legs | **58,718,411** |
| distinct wallets | **1,110,501** |
| gross SOL priced | **32.05M SOL** (11.98M curve route, 20.07M pool route) |
| build time / size | 65 s, 1.3 GB parquet |

### 1.2 Counterparty identification, and the transaction that is not a trade

The counterparty is identified per mint as an owner touching ≥20% of that mint's transactions
and ≥10 of them. On a bonding-curve coin that is the curve and nothing else; on a migrated coin
it admits both the curve and the PumpSwap pool, which is what makes a coin that migrated
mid-window priceable on both sides of the event (2,612 mints have more than one). A transaction
carrying **two** counterparty legs is the migration transfer and is dropped — pricing it as a
trade books the entire remaining curve supply as one enormous buy at a near-zero price. Where
only one side of that transfer was identified, a residual guard drops any single leg moving
more than 30% of supply.

Mints and owners are dictionary-encoded to int32 in the first pass. That is not cosmetic: the
un-encoded slice is 127M rows of two base58 strings and spilled **52 GB** to temp on a 16 GB
budget before being killed; encoded, the whole build fits in memory and runs in 65 seconds.

### 1.3 The graduation cliff, the bug it caught, and the residual it bounds

The only external anchor this pricing has is the protocol's own constant. pump.fun completes a
curve at exactly **85 SOL raised**, reserving **206.9e6 tokens** for the pool — `v_tok` from
1.073e15 to 2.799e14. So two numbers reconstructed from the tape have to reproduce two protocol
constants, and they have to do it as a **spike**, not as a hump.

The first build gave a median raise of **80.98 SOL** with an IQR of **[65.4, 101.3]**. The
operator's response to that — *"the fact that that number doesn't exactly reproduce the
graduation cliff indicates we still have bugs don't we??"* — is why this section exists. **A
5% miss on a hard protocol constant is a bug report, not a tolerance**, and there was a bug.

**The create transaction.** A pump.fun create writes the whole supply into the curve **and**
executes the dev buy in one transaction, so the curve's *net* token delta on that row is
`supply − dev_buy`, not `supply`. Two failures followed from taking that net at face value:

1. `bal0 = max(cumulative sum)` understates the opening balance by whatever part of the dev buy
   is never sold back, which shifts `OFFSET` and biases **every price on the coin**. The smear
   is directly visible: `bal0/1e15` piles up at 1.0000 and then trails 0.9999, 0.9998, 0.9997 —
   one bucket per dev-buy size.
2. On that first row `bal_before = bal_after − cp_delta` evaluates to ≈0, so `v_tok_before` is
   the bare offset, the implied SOL leg comes out large and **negative** against a positive
   token leg, and the sign filter **silently deleted every dev buy in the corpus**.

Both are fixed by reconstructing the gross opening balance from the transaction's own legs
(`bal0_gross = bal_after(first tx) + Σ trader deltas in that tx`) and using
`v_tok_before = V_TOK_VIRT` on the create, which is what it is by definition. After the fix
`bal0` snaps to exactly 1.0000 for **31,473 of 36,651** (mint, counterparty) pairs.

**And then the check passes, exactly.** On 1,975 graduated coins with ≥50 curve trades, the
endpoint identity `K·(1/v_final − 1/v_initial)` reads:

| | |
|---|---|
| reconstructed raise, **q25 / q50 / q75** | **85.01 / 85.01 / 85.01 SOL** |
| curve balance left at graduation, median | **20.7% of opening** = 206.9e6 tokens |

**Two protocol constants, four significant figures, flat across the interquartile range.** That
is the cliff. The pricing identity is correct and the offsets are correct.

**The residual, measured rather than assumed.** The *path sum* — adding up the per-trade SOL
legs — does **not** equal the endpoint identity for every coin: the ratio runs 1.000 at p10,
1.002 at p25, **1.238 at the median**, 1.90 at p90. A signed path sum telescopes exactly when
no step is missing, so the excess is the SOL of steps this tape drops: transactions filtered by
the sign guard (0.44% of legs), by the 30%-of-supply migration guard, by `n_cp_legs > 1`, and
curve movements carrying no trader leg at all. Each dropped **buy** leaves a gap that the
following trades price from the true balance, so the sum runs high.

**What that does and does not affect, quantified:** the gap is **3.18% of gross SOL volume** at
the median. It looks large as a ratio only because it is being compared to a *net* raise — 85
SOL of net accumulation out of hundreds of SOL of gross churn — and **no conclusion in this
document rests on a net SOL quantity.** `eta`'s numerator is gross volume (accurate to ~3%,
and a common scale factor cannot change a monotone ranking across deciles); the drain shares,
the rotation buy share and the wiggle statistics are SOL-over-SOL or log-price quantities in
which the factor cancels exactly. It is recorded as an open defect rather than hidden, and the
fix is to price the dropped steps rather than to drop them.

---

## 2. The rotation cohort — the object the folk word is about

The brief asked for the rotation set to be built explicitly and reported with its size and
stability, and it turns out to be the single largest structure in the corpus.

**Definition (strictly trailing, so a coin's own crowd never votes itself into the cohort that
then describes it):** the **hot set** at hour *h* is the top 200 mints by buy SOL in that hour.
A wallet is in the **rotation cohort** `R(h)` if it traded ≥3 distinct hot coins during hours
`[h−6, h−1]`.

| | |
|---|---|
| cohort size, per hour | **median 25,528** (p10 17,370, p90 32,172) |
| distinct wallets ever in the cohort | **324,582** of 1,071,592 buyers (30.3%) |
| **share of all buy SOL in the corpus done by the cohort** | **54.3%** |
| Jaccard stability, 1 hour | **0.773** |
| Jaccard stability, 6 hours | 0.245 |
| Jaccard stability, 24 hours | 0.226 |

Two readings. **Mercenary rotation is not a metaphor; it is the majority of the money.** And
the stability profile — 0.77 at an hour, flat at ~0.23 from six hours out — is a *persistent
core plus a churning skin*, not a fixed club and not a random draw. Anything built on "the
rotation wallets" has to be rebuilt hourly; a list a day old retains under a quarter of its
membership.

**A caveat that inverts the folk definition.** PvP is supposed to mean "no outside money
enters". Measured as cash flow (§11 E), the rotation cohort is a net SOL **payer** in 81.3% of
hours, median **−2,643 SOL/hour**, i.e. −4.8% of its own gross. From the coins' point of view
the rotators *are* the outside money. (This is cash flow, not PnL — the cohort's token
inventory is not marked, so this says where SOL went, not who won.)

---

## 3. The PvP classifier, and the audit that deflates it

### 3.1 The columns

One column per clause of the operator's definition, all computed on a coin's own trailing
30-minute bucket, all causal:

| column | the clause it encodes |
|---|---|
| `rotation_share` | mercenary rotation — share of buy SOL from `R(h)` |
| `new_money_share` | outside money entering (**inverse** of PvP) |
| `roundtrip_frac` | everybody exit-planning — share of buy SOL from wallets that left the bucket flat |
| `hold_med_s` | short holds — median completed round trip in the bucket |
| `float_turnover` | volume without accumulation — gross token volume / circulating supply |
| `recycled_30m` | **the incumbent**, reproduced exactly per `studies/caller_wallets.py` |

Panel: **117,569 (coin, 30-min bucket) rows on 33,775 coins**; 90,217 rows / 33,527 coins after
the ≥20-wallet gate. Temporal split on **birth time** so a coin never straddles: 63,152 train /
21,809 coins, 27,065 test / 11,718 coins.

### 3.2 The ladder

Gradient-boosted trees on tabular features — PROGRAM.md §3.4's mandated baseline and MELT's
measured winner. No class weighting (MELT's weighted BCE decalibrates the probabilities an EV
decision needs). Mint-clustered bootstrap CIs, 400 draws.

**Label `dead_1h`** (base rate 0.129 train / 0.213 test):

| block | AUC [95% CI] | AUPRC | bits/row |
|---|---|---|---|
| **baseline: `recycled_30m` alone** | **0.720** [0.707, 0.731] | 0.345 | – |
| free (mcap, age, gross SOL, wallets, absorption) | 0.888 [0.880, 0.895] | 0.728 | +0.267 |
| **PvP block without `recycled_30m`** | **0.880** [0.873, 0.887] | 0.682 | +0.265 |
| PvP block + `recycled_30m` | 0.881 [0.873, 0.887] | 0.683 | +0.267 |
| free + `recycled_30m` | 0.888 [0.880, 0.895] | 0.727 | +0.268 |
| **free + PvP block** | **0.893** [0.885, 0.900] | 0.738 | **+0.281** |
| free + PvP + `recycled_30m` | 0.893 [0.885, 0.900] | 0.738 | +0.282 |

**Label `dead_4h`** (base 0.164 / 0.297): baseline 0.682, free 0.833, PvP-without-incumbent
0.830, free + PvP **0.837**, free + `recycled_30m` 0.834.

Three readings, in decreasing order of how much they should change anything.

**The PvP block beats the incumbent badly as a standalone and adds little over the free
columns.** 0.880 vs 0.720 marginally; +0.005 / +0.004 incrementally. `recycled_30m` adds
+0.000 / +0.001 over the same free columns. So the folk definition's other four clauses are
worth more than the incumbent, and both are worth much less than market cap and age.

**It is nevertheless coin-specific, which is the part that could have failed and did not.**
Permuting the PvP block **across coins within (market-cap × age) quintile bins** — preserving
every column's marginal distribution and destroying only the pairing — gives median AUC 0.827
against the real 0.837 and **beats the real assignment in 0 of 24 draws**. That is the exact
test `RESULT_imitation_signal.md` §5.6 ran on its swarm block, where scrambling made the model
*better* 22 of 24 times. This block does not do that.

**Both controls pass.** Known-zero world (labels permuted): AUC **0.499**. The same world with
a planted `rotation_share → death` effect: **0.576**. i.i.d. label shuffle 0.511, label
rotation 0.428; neither beats the real fit in 24 draws. PROGRAM.md §3.12 exists because a
constant-zero estimator passes a zero control perfectly; this one recovers a planted effect.

### 3.3 The single columns, and the surprise

| column | AUC `dead_1h` | AUC `dead_4h` | BY-FDR q=0.10 |
|---|---|---|---|
| `log_hold` (short holds) | **0.190** → 0.810 inverted | 0.238 → 0.762 | YES |
| `roundtrip_frac` | **0.766** | 0.724 | YES |
| `recycled_30m` *(incumbent)* | 0.720 | 0.682 | YES |
| `log_turnover` | 0.348 → 0.652 | 0.387 → 0.613 | YES |
| `rotation_share` | 0.542 | 0.536 | YES |
| `new_money_share` | 0.508 | 0.513 | 1 of 2 |

**Median hold time is the strongest single column in the study**, at 0.810 inverted against the
incumbent's 0.720, and `roundtrip_frac` is second at 0.766. Both are direct measurements of
"everybody is exit-planning". `rotation_share` — the column that required building the whole
324,582-wallet cohort — is nearly worthless on its own (0.542) and earns its place only inside
the block.

`hold_med_s` is undefined when no wallet completes a round trip in a bucket, and the fill is a
knob. Swept: filling with the bucket length, with zero, or with the observed median moves
free+PvP by **0.0004 AUC** (0.8372 / 0.8372 / 0.8376) and the column's own AUC by 0.012. Not
load-bearing.

### 3.4 The audit that deflates the headline

Because the operator asked for alternative readings rather than a defence of the first one,
the classifier was re-run **within age bands** (§11 B). It should have been the first check and
it was nearly the last:

| age band | n | median PvP score | share in PvP state | `dead_4h` base | **AUC PvP score** | **AUC `recycled_30m`** |
|---|---|---|---|---|---|---|
| <30m | 38,079 | 0.597 | 38.8% | 0.423 | **0.505** | **0.622** |
| 30–60m | 5,051 | 0.541 | 20.4% | 0.070 | 0.497 | 0.521 |
| 1–2h | 5,525 | 0.494 | 10.1% | 0.050 | 0.536 | 0.519 |
| 2–4h | 6,050 | 0.457 | 6.7% | 0.038 | 0.513 | 0.501 |
| 4–12h | 11,818 | 0.417 | 4.8% | 0.035 | 0.526 | 0.570 |
| 12–24h | 9,061 | 0.398 | 3.7% | 0.037 | 0.486 | 0.513 |
| >24h | 14,633 | 0.384 | 2.6% | 0.049 | 0.560 | 0.581 |

**The PvP score falls monotonically with age and its univariate power inside an age band is
0.485–0.560 — chance, near enough.** The marginal 0.88 is age. And inside the band where the
decisions actually happen, coins under thirty minutes old, **the incumbent `recycled_30m`
beats the PvP score 0.622 to 0.505.**

That does not make the classifier useless: age is legitimately predictive and legitimately
available at decision time, and the matched-swap null in §3.2 shows a small residual that is
genuinely about *which coin*. But the sentence "PvP state predicts death" is not supported.
The supported sentences are: *PvP state is a proxy for coin age*, and *conditional on age and
size it adds about half a point of AUC*.

It also inverts the folk model in a way worth stating: **the PvP-est coins are the youngest
ones, not the oldest.** Nothing "descends into" PvP; coins are born there and the survivors
leave.

### 3.5 What an avoid rule actually buys

The operator's framing — *"notice them and either avoid them or find some strategy that figures
out which one is gonna do good"* — is two decisions and needs two numbers. Avoid first, on
`dead_4h` (test base rate 0.297):

| PvP score threshold | rows flagged | precision | recall | lift | median `ret_1h` flagged | unflagged |
|---|---|---|---|---|---|---|
| p50 | 56.8% | 0.370 | 0.708 | 1.25× | **−5.54%** | −0.03% |
| p70 | 35.5% | 0.411 | 0.491 | 1.38× | −4.61% | −0.98% |
| p80 | 23.8% | 0.437 | 0.351 | 1.47× | −3.67% | −2.01% |
| **p90** | 12.3% | **0.479** | 0.198 | **1.61×** | −2.57% | −2.90% |
| p95 | 6.4% | 0.457 | 0.098 | 1.54× | −2.28% | −3.00% |

Note the two gradients run in **opposite directions**. The death lift is monotone up to p90;
the *return* gap is largest at p50 (−5.54% vs −0.03%) and **has vanished by p90** (−2.57% vs
−2.90%). So the high thresholds identify coins that **stop trading**, and the low threshold
identifies coins that **fall**. If the decision is "will I be able to get out", use p90. If the
decision is "will this go down", use the median split — and note the flagged half is over half
the board, which is a statement about the board and not a filter.

### 3.6 Within the PvP state, can you pick the winner?

Conditioning on the top decile of the score (5,697 train / 3,325 test rows) and asking what
separates the coins that go up:

| | `ret_1h > +10%` (base **2.4%**) | `max ret_1h > +20%` (base **1.7%**) |
|---|---|---|
| free | **0.719** | 0.727 |
| free + PvP | 0.696 | **0.744** |
| PvP only | 0.677 | 0.703 |
| label-shuffle null | 0.469 (0/24 beat real) | 0.472 (0/24) |

**Yes, at AUC ~0.72–0.74 — and it is the free columns doing it.** The PvP block's contribution
flips sign across the two labels (−0.023 and +0.017), which is `RESULT_imitation_signal.md`
§6's signature for "no stable conditional information". And the base rate is 2%: at AUC 0.73
and a 2.4% base rate, precision at a 10%-flag threshold is roughly 7%, i.e. thirteen losers per
winner before friction. **Selection inside PvP is measurable and is not a trade.**

### 3.7 Is PvP a state or a gradient?

A 2-component Gaussian mixture on the standardised block separates at **Mahalanobis 3.12** with
weights 0.66 / 0.34, and BIC keeps improving through k=3. But a kernel density estimate of the
composite score finds **2 modes at the finest usable bandwidth and 1 at the two coarser ones**,
and the score is skew +0.13 with excess kurtosis −0.56 — flat-topped, which is what two heavily
overlapping modes look like from the outside. BIC improving with k, on 90k rows of correlated
non-Gaussian columns, is evidence of non-Gaussianity rather than of modes.

**Verdict: a gradient with a fat shoulder, not a switch.** Any threshold is a policy choice,
which is why §3.5 reports the whole threshold curve rather than picking one.

*(The first version of this test reported "39 modes" and a STATE verdict, because scipy's
`bw_method` is a scale factor on the sample standard deviation rather than an absolute
bandwidth — 0.02 against an sd of 0.12 is a bandwidth of 0.0024, and it was counting bin noise.
Recorded rather than quietly fixed, because it flipped the verdict.)*

---

## 4. The arena question — refuted, with a sign and a mechanism

`RESULT_circuit_theory.md` §4.2: LP is +EV ⟺ `eta > VR(T)`, `eta = 2fN/(C·RV)`.
`RESULT_callout_volatility.md` §6 found the one condition that lifts `N` while leaving `RV`
alone, and §9 flagged the **size-weighted** version of `N` as "the single highest-value
follow-up in this file" — fees are proportional to volume, not to trade count. This section is
that follow-up, conditional on PvP state. `C = w_x w_y · TVL = TVL/4 = v_sol/2`, read off the
same identity the tape is priced with.

| PvP decile | n | forward vol (SOL) | LP fees/h (SOL) | C (SOL) | RV | **eta (LP)** | VR(5/1) | eta>VR **and paying** | `dead_4h` | median `ret_1h` |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 6,458 | 67.8 | 0.136 | **364.4** | **0.0009** | **0.585** | 1.19 | 26.1% | 5.1% | **+1.7%** |
| 1 | 6,458 | 72.9 | 0.146 | 109.9 | 0.0112 | 0.253 | 0.94 | 26.5% | 5.5% | +0.8% |
| 2 | 6,459 | 76.3 | 0.153 | 61.9 | 0.036 | 0.154 | 1.01 | 15.6% | 4.9% | −1.1% |
| 3 | 6,458 | 119.1 | 0.238 | 60.6 | 0.048 | 0.147 | 1.19 | 11.8% | 4.8% | −1.8% |
| 4 | 6,458 | 96.9 | 0.194 | 47.0 | 0.061 | 0.136 | 1.15 | 11.2% | 5.0% | −4.1% |
| 5 | 6,459 | 83.1 | 0.166 | 35.0 | 0.088 | 0.118 | 1.00 | 9.7% | 5.1% | −8.1% |
| 6 | 6,458 | 74.6 | 0.149 | 28.6 | 0.114 | 0.104 | 0.96 | 9.7% | 6.0% | −12.3% |
| 7 | 6,459 | 56.7 | 0.114 | 23.9 | 0.135 | 0.090 | 0.89 | 9.3% | 8.1% | −17.6% |
| 8 | 6,458 | 38.4 | 0.077 | 20.3 | 0.109 | **0.085** | 0.73 | 10.9% | 9.7% | −20.7% |
| 9 | 6,459 | **5.9** | **0.012** | 15.2 | 0.007 | 0.194 | 0.65 | **5.3%** | 15.0% | −7.6% |

**Verdict: the strong hypothesis is refuted, and the components say exactly why.** Across
deciles 0→8, forward volume is roughly flat (67.8 → 38.4 SOL) while **realized variance rises 127×**
(0.00086 → 0.1089) and **capacitance falls 18.0×** (364 → 20 SOL). `eta` is `volume / (C · RV)`, so
both moving denominators push it down: **0.585 → 0.085, monotone, 6.9-fold.** Flow-up-at-flat-
RV is a real and valuable condition; PvP is *flow-flat-at-RV-exploding*, which is the same ratio
driven the wrong way. **The arena-owner edge lives in the LOW-PvP state.**

**The top decile is a trap and it has a name.** `frac(eta > VR)` is U-shaped — 41% at decile 0,
17% at decile 5, 47% at decile 9 — because `eta → ∞` as `RV → 0`, and `RV → 0` exactly when
nothing trades. Unguarded, the criterion scores **GHOST_TOWN as the best arena on the board**
(`RESULT_crime_signatures.md` §7.1, `ΔV = ΔQ/C` with `C → 0`: there is no exit at the quoted
price at all). Adding an absolute fee floor of 0.05 SOL/h — stated, not tuned — deletes it:
the guarded column falls to **5.3%** in decile 9, the lowest on the board.

### 4.1 The window, characterised

Contiguous runs of paying, eta-favourable 30-minute buckets, 4,974 episodes:

| | all | low-PvP half | high-PvP half |
|---|---|---|---|
| median length | **1 bucket (30 min)** | 1 | 1 |
| p90 length | 2 buckets (60 min) | | |
| median LP fees per episode | 0.384 SOL | **0.470 SOL** | 0.314 SOL |
| ended in ghost town | 3.7% | 3.0% | **4.5%** |

**There is no durable arena.** The median eta-favourable window is one bucket and p90 is two;
it does not persist long enough to be a position, and the high-PvP half earns 33% less per
episode and dies into a ghost town 52% more often. The competing-risk shape the brief asked
about is real but small at this guard level.

**PvP state does predict the window** (AUC 0.833 alone, 0.873 with free columns against free's
0.860, `recycled_30m` 0.605) — it predicts it with the wrong sign for an LP.

---

## 5. The same state, the other book — the flip

PvP raises realized variance 127×. **RV is a cost to an LP and a raw material to a two-sided
scalper**, and the operator's live book is the wiggle book. Oracle zigzag on the minute grid:
consecutive same-sign log-returns grouped into monotone runs, each run credited its amplitude
less one round trip of friction (2.4% at the operator's 0.1 SOL clip). This is a **ceiling** —
the filter turns at the exact extremes — the same convention `RESULT_callout_volatility.md`
uses.

| PvP decile | median `wiggle_net` (oracle) | median swings | share of buckets with any harvestable wiggle | median pool (SOL) |
|---|---|---|---|---|
| 0 | **0.00033** | 11 | **50.1%** | 554 |
| 1 | 0.283 | 11 | 76.6% | 135 |
| 2 | 0.421 | 9 | 84.8% | 101 |
| 3 | 0.545 | 9 | 87.4% | 70 |
| 4 | 0.769 | 8 | 94.0% | 57 |
| 5 | 1.005 | 7 | 96.0% | 45 |
| 6 | 1.067 | 5 | 96.4% | 35 |
| 7 | 1.099 | 4 | 93.3% | 31 |
| 8 | **1.139** | 3 | **96.5%** | 29 |
| 9 | 0.889 | 3 | 92.0% | 29 |

Spearman ρ(PvP score, oracle wiggle) = **+0.363**.

**Read the two tables together: they are the same measurement with the sign of the book
flipped.** The state that takes `eta` from 0.585 to 0.085 takes harvestable amplitude from
0.00033 to 1.139 (3,460×), and takes the probability that a round trip clears friction *at all* from a
coin flip to 96.5%. Decile 0 — the eta-favourable arena — is the deadest possible place for a
scalper: eleven direction changes a bucket and essentially none of them big enough to pay for
themselves.

Three caveats, in order of severity. **It is an oracle**, and the single easiest number here to
misread as a return — `RESULT_callout_volatility.md` §7.1's projection from the operator's own
seed is what a live rule got, and this desk's own first eleven closes on that book were −14.08%.
**Depth falls with the gradient**: median pool goes 554 → 29 SOL, so at a 0.1 SOL clip own-exit
impact runs 0.02% → 0.35%, still inside the GHOST_TOWN guard's 5-SOL floor but the guard is now
doing real work rather than none. And **amplitude is trivially correlated with volatility** —
the non-trivial part is the friction-clearing share, which is why that column is in the table.

---

## 6. PvP transition as an exit signal — a null

For coins that built a genuine holder base (≥30% new money and ≥120 s median hold in their
first two buckets, ≥100 wallets — **3,325 of 33,527**), does the flow turn mercenary *before*
the price breaks?

| | observed | matched-swap null |
|---|---|---|
| coins that broke (−50% from running peak) | 2,345 | |
| PvP fired at or before the break | **31.6%** | **25.9%** |
| **median lead** | **0 s** | 0 s |
| p90 lead | 1,800 s | |
| share of leads that are exactly zero | **84.6%** | |

**The lead-time distribution is the money metric and it is zero.** PvP crosses its threshold in
the *same 30-minute bucket* as the price break 84.6% of the time, and the firing rate barely
clears a null that permutes the score across coins within (mcap × age) bins. There is no
early warning here.

**The honest limit, and it is the one that could overturn this:** the panel's resolution is 30
minutes, so any lead shorter than a bucket is invisible by construction. A 10-minute-bucket
re-run is the obvious follow-up and is one parameter away. What this measurement excludes is a
lead of *hours*, which is what an exit signal would need to be worth building.

**Onset as an event does not rescue it** (§11 C): the *change* in PvP score scores AUC 0.561
against the level's 0.555, and adding both `Δscore` and the lagged level to free+PvP moves
`dead_4h` AUC from 0.625 to 0.623. On young coins specifically — the operator's *"watching new
mints and we see PvP start to happen"* — onset fires on 23.9% of buckets and the coins it fires
on go on to do **better**, not worse (median `ret_1h` −2.8% vs −6.9%).

---

## 7. The operator's four coins, scored today

The corpus ends 2026-08-15T00:00Z, so scoring off it answers "how were they last night".
pump.fun's `/v2/coins/<mint>/trades` carries wallet-level trades through the current minute,
keyless, so both are reported. Percentiles are against the 90,217-row corpus distribution.

**Live, 2026-08-15, last four 30-minute buckets each:**

| coin | bucket end (UTC) | PvP pctile | rotation | new money | round-trip | median hold | recycled | gross SOL | wallets |
|---|---|---|---|---|---|---|---|---|---|
| **weave** | 18:11 | **0.005** | 0.000 | 0.613 | 0.000 | – | 0.000 | 4.2 | 8 |
| weave | 17:41 | 0.007 | 0.018 | 0.655 | 0.000 | – | 0.000 | 9.9 | 22 |
| weave | 17:11 | 0.010 | 0.009 | 0.062 | 0.006 | 637 s | 0.006 | 34.9 | 49 |
| weave | 16:41 | 0.110 | 0.338 | 0.751 | 0.265 | 147 s | 0.286 | 54.9 | 70 |
| **nosis** | 18:11 | **0.128** | 0.131 | 0.000 | 0.000 | – | 0.000 | 11.7 | 18 |
| nosis | 17:41 | 0.016 | 0.100 | 0.867 | 0.032 | – | 0.072 | 10.5 | 20 |
| nosis | 17:11 | 0.079 | 0.662 | 0.153 | 0.093 | 1098 s | 0.326 | 59.5 | 62 |
| nosis | 16:41 | 0.084 | 0.678 | 0.234 | 0.052 | 656 s | 0.315 | 72.7 | 41 |
| **DREGG** | 18:12 | **0.341** | **0.797** | 0.003 | 0.000 | – | 0.000 | 9.7 | 10 |
| DREGG | 16:42 | 0.126 | 0.000 | 0.368 | 0.368 | 41 s | 0.371 | 6.6 | 9 |
| **SOLVE** | 18:12 | **0.146** | **0.985** | 1.000 | 0.000 | – | 0.000 | 18.7 | 12 |

**All four are in the bottom third of the corpus's PvP distribution, and weave is in the bottom
one percent.** No coin shows the transition signature. Median holds where they are measurable
run 147–1,098 seconds against a corpus median of 214 s; round-trip fractions are 0.000–0.368
against a corpus median of 0.417.

Two numbers deserve to be read rather than skipped. **DREGG at 18:12 and SOLVE at 18:12 take
79.7% and 98.5% of their buying from wallets that were in the rotation cohort last night** —
that is the one high reading anywhere in the table. It is *not* accompanied by short holds,
round-tripping or recycling, so on this instrument it reads as "the people trading these coins
today are people who trade a lot of coins", which is a different statement from "these coins are
being farmed". At 9.7 and 18.7 SOL of gross flow across 10 and 12 wallets, it is also a very
small sample; a single active wallet moves it.

**The corpus arm agrees, with one exception worth naming.** Scored on the corpus's own last
buckets (2026-08-14), weave runs 0.035–0.082, DREGG 0.000–0.107, nosis 0.163–0.253 — and
**SOLVE runs 0.304–0.817**:

| coin | bucket (UTC) | pctile | rotation | round-trip | median hold | recycled | gross SOL | wallets |
|---|---|---|---|---|---|---|---|---|
| SOLVE | 08-14 07:30 | 0.654 | 0.344 | 0.427 | **6 s** | 0.428 | 18.9 | 17 |
| **SOLVE** | **08-14 21:00** | **0.817** | **0.801** | **0.385** | **23 s** | 0.377 | 85.4 | 39 |
| SOLVE | 08-14 23:30 | 0.304 | 0.994 | 0.000 | – | 0.000 | 16.0 | 12 |

**SOLVE had two genuinely PvP-shaped half hours on 2026-08-14** — 80% rotation-cohort buying, a
23-second median hold, 38.5% of buyers leaving flat, on 85 SOL across 39 wallets — and it did
not persist into the live arm (0.146 today). It is the only reading anywhere in this section
that looks like the state the operator described, it is on the smallest of the four coins, and
n = 39 wallets is small enough that a handful of scalpers produce it. Reported because the
brief asked for the transition metric on these four prominently, whatever it says.

**Two limits on this table, both real.** The "known rotator" set is necessarily stale — the
cohort is built from the corpus, which ends 18 hours before these buckets, so `rotation_share`
here is a **lower bound**. And 8–70 wallets per bucket is a small sample for a share statistic.

---

## 8. Vamp drain — real, specific, and economically trivial

`RESULT_imitation_signal.md` established that swarmed hosts **live longer** (10.7 min vs 1.0
min median survival, log-rank p < 0.0001) and that the swarm carries no return information. It
never measured the flow, because its instrument was launch metadata plus candles and neither
carries a wallet. "Vamp" is a claim about a **directed** quantity, and this is it.

**Definition.** For a (host, clone) pair with clone launch `t_c`, drain is
`Σ_wallets min(host sell SOL in [t_c−30m, t_c+30m], clone buy SOL in [t_c, t_c+30m])`. `min`
rather than a sum or a product: a wallet that sold 5 SOL of host and bought 0.1 SOL of clone
moved 0.1 SOL of attention, not 5.

Families are rebuilt for **2026-08-14** (a day wholly inside the corpus) with
`shitcoims_scalper.swarm_detect`'s own clustering — 33,202 launches, 3,453 families of size ≥2.

| | observed | naive null | **rotation-matched null** |
|---|---|---|---|
| median drain / clone's own buying | **3.37%** | 0.00% | 0.00% |
| mean drain / clone's own buying | 8.36% | 0.26% | 2.01% |
| **ratio, mean over mean** | — | **32.4×** | **4.2×** |
| share of pairs with any drain at all | **82.8%** | 10.4% | 47.9% |
| median shared wallets | **7** | 0 | 0 |
| median drain | **2.93 SOL** | | |
| p (null draw ≥ observed median), 30 draws | — | 0.032 | 0.032 |

The naive null swaps the host for a uniformly random coin trading at the same instant. The
rotation-matched null swaps it for a coin trading at the same instant **with comparable
sell-side flow**, and is the ambient cross-coin rotation between any two coins of that size.

**The drain is real and specific — and the naive-vs-rotation gap is 7.8×, which is this repo's
trap firing for the third time** (`RESULT_caller_wallets.md` §2.1: 20× → 1.20×;
`RESULT_copytrading.md`: 73× → 0.98×). Reporting the naive number alone would have made this
finding look nearly eight times bigger than it is.

**And 3.4% of a median 72 SOL is 2.9 SOL.** A vamp takes about three percent of its own funding
from the host's sellers. By taxonomy the parasite arm (497 pairs) reads 3.1% and the self-farm
arm (19 pairs) 20.4% — a dev cloning their own coin recycles their own crowd, which is the
mechanism working exactly as it should and on the wrong population to matter.

### 8.1 Resolving the tension with the survival finding

Does drain predict host deterioration where swarm-onset predicted survival? High-drain hosts
are **smaller and younger** (median 127 vs 261 SOL gross, 77 s vs 312 s age), so the raw split
is uninterpretable. Matched 1:1 on (log gross SOL, log age) to |SMD| < 0.004, **87 pairs**:

| | high drain | low drain | p |
|---|---|---|---|
| dead at 4 h | 63.2% | 51.7% | 0.127 |
| median `ret_1h` | **−12.0%** | −3.5% | 0.068 |
| median `ret_4h` | **−15.5%** | −3.6% | 0.096 |

**Directionally the drain hurts, and nothing clears 0.05.** With 87 pairs this is a lead, not a
result. The resolution offered is therefore not "drain is a myth" and not "drain kills hosts";
it is:

> **A clone is a marker of the host's attention (which is why swarmed hosts live longer) and a
> claim on about 3% of the money that attention was drawing (which is why the drain is real but
> cannot be what kills anything).** Attention certified and capital taken are different
> quantities, and the imitation lane measured the first while the folk story is about the
> second.

**The selection that bounds this.** Only **709 of 20,642** family edges have *both* coins on
the flow tape — 96.6% of clones never attract 100 counterparty touches. So this measures drain
among clones that actually got funded, which is the only case where drain is possible, and it
is silent about the 96.6% that got nothing. That number is itself worth carrying: **the modal
vamp takes nothing from anybody because nobody shows up.**

---

## 9. The live case: a duel, at one-second resolution

Collected 2026-08-15 17:20–18:15Z while the event was still running, after the operator watched
an **arbitration callout** inside it — not "buy this coin" but a Schelling-point declaration,
verbatim: *"this is the OG, somehow other one is running but this is better ticker and the OG
send it."*

### 9.1 The family

Nineteen `glasses` launches on 2026-08-15 from the firehose, plus three that arrived during
collection. Metadata from `frontend-api-v3.pump.fun/coins/<mint>`, trades from
`swap-api.pump.fun/v2/coins/<mint>/trades` (wallet-level, cursor-paged, keyless).

| mint | name / ticker | created | ATH | ATH $ | now $ | trades |
|---|---|---|---|---|---|---|
| `5dqgLU2W` | catwifglasses / **glasses** | 11:56:10 | **17:19:31** | **44,761** | 4,861 | 4,590 |
| `2jHmZ3uX` | Fat Cat With Glasses / FATCAT | 17:17:54 | 17:19:52 | 5,523 | 2,190 | 237 |
| `aVpzScbe` | catwifglasses / glasses | 17:26:35 | 17:27:10 | 6,629 | 4,272 | 297 |
| `AwPHFvD1` | catwifglasses / glasses | 16:14:15 | 16:14:18 | 4,559 | 2,112 | 98 |
| `A6LJ2v2U` | catwifglasses / glasses | 12:07:31 | 12:07:31 | 5,041 | 2,114 | 72 |
| `C1WEcFMu` | catwifglasses / glasses | 17:15:34 | 17:15:36 | 2,461 | 379 | 10 |
| `CRjnk4uU` | catwifglasses / cwg | 11:56:18 | 16:34:30 | 2,614 | 2,248 | 44 |
| ×12 | *"WHOLE NARRA IS GLASSES NOT PUMP"* / Cloutcat | 16:33–16:35 | | ~2,110 | 2,112 | 2–50 |

The host took **1,177 SOL of buying from 1,234 wallets over 5.4 hours** and graduated. The
twelve identical `Cloutcat` launches at 16:33–16:35 are a *meta-level* object this taxonomy has
no name for: a coin whose **name is an argument about the duel**.

### 9.2 The launch clustering

Derivative launches relative to the host's top:

```
-323 min  5dqgLU2W (the host itself), BnPuY2CJ, CRjnk4uU
-312      A6LJ2v2U
-261      5KdwtCs3
-187      CgzTBnW8
 -65      AwPHFvD1
 -46      × 12   "WHOLE NARRA IS GLASSES NOT PUMP"
  -3.9    C1WEcFMu
  -1.5    2jHmZ3uX  (FATCAT)
  +7.1    aVpzScbe
 +29.4    7oNzbyQ1  (PUPSUN)
 +30.1    BJBMdKyy  (FAT)
```

**Five derivative launches inside ±30 minutes of the top, three inside ±8 minutes.** Rival
launches cluster *just before* the host tops — consistent with §8's reading of a clone as an
attention marker rather than a cause.

### 9.3 The drain, on one event

| pair | shared wallets | drain (SOL) | drain / clone's buying |
|---|---|---|---|
| host → FATCAT | **28 of 111** (25% of its crowd) | 1.33 | **2.7%** |
| host → aVpzScbe | 1 of 9 | 0.00 | 0.0% |
| aVpzScbe → host *(reverse)* | | 1.19 | |
| host → all others | 0–3 | 0.00 | 0.0% |

**A quarter of FATCAT's crowd came from the host and brought 2.7% of its money.** The corpus
statistic is 3.4%. Shared attention, not shared capital — the same answer, on n=1, from a
completely different instrument.

### 9.4 The cascade, and what moved first

Per-minute host flow around the top:

| min vs top | buy SOL | sell SOL | trades | price vs top |
|---|---|---|---|---|
| −8 | 8.7 | 4.1 | 23 | −74.4% |
| −7 | 3.5 | 4.2 | 13 | −74.9% |
| **−6** | **0.9** | 2.8 | **3** | −76.2% |
| **−5** | **198.2** | **162.5** | **267** | **−62.4%** |
| −4 | 55.6 | 52.9 | 148 | −49.1% |
| −3 | 78.1 | 51.1 | 131 | **−7.5%** |
| −2 | 76.1 | 76.4 | 140 | −10.7% |
| −1 | 61.6 | 56.4 | 133 | −2.3% |
| **0** | 35.2 | 38.8 | 93 | **peak** |
| +1 | 36.2 | 47.9 | 92 | −30.1% |
| +3 | 32.8 | 36.7 | 93 | −47.8% |
| +8 | 9.3 | 18.6 | 36 | −57.9% |

**The coin went from 0.9 SOL/min and three trades to 198 SOL/min and 267 trades inside one
minute, and its price went +289% over the next three.** The operator's "+30%" is a conservative
slice of it.

**Chain first, and it is not close.** The burst minute is 17:14:31–17:15:31Z. The first rival
launch (`C1WEcFMu`) is at **17:15:34 — three seconds after that minute closed**. FATCAT is
2.5 minutes later. The top is four minutes later. Every social and derivative object in this
event is downstream of a flow burst that is fully visible on chain, which is the same ordering
`RESULT_caller_wallets.md` §4 measured for callouts (26 s behind a 161-wallet burst) and
`RESULT_callout_volatility.md` §5.3 measured for flow (the callout column loses 58% of its
slope once the burst is controlled). **Three studies, three mechanisms, one ordering.**

**What this case cannot do.** The arbitration callout's own timestamp is not recoverable: every
pump.fun replies/comments endpoint probed returns 404 (`/replies/<mint>`, `/replies?mint=`,
`/coins/<mint>/replies`, `/threads/<mint>`, `/comments/<mint>`, and the v2 equivalent), and the
coin's `reply_count` is 0. So the callout's position is *bracketed* — the operator saw it
minutes before ~17:20Z, and the chain event is at 17:14:31 — rather than measured. If the
surface it lived on is identifiable, that gap closes with one collector.

### 9.5 The latency-decay curve, on one event

Neither pre-specified detector catches this. **Swarm onset at k=3** fires at 11:56:18 — the
third same-name launch, at birth, 323 minutes early, a different event entirely. **Drain
reversal** fires at 17:28:03, **8.5 minutes after** the top, when the money is already leaving.
What visibly does fire is a **flow burst on the host's own tape**, and declaring that rule
after seeing the event is exactly the hazard PROGRAM.md §9 rung 3 names, so it is written down
as a rule (60-second window ≥ 20 SOL and ≥ 8× the trailing 30-minute rate, coin at least 30
minutes old) and then §10 runs it over the whole corpus.

On this event it fires at **17:02:47, 16.75 minutes before the top**:

| reaction latency | raw +60 s | raw +120 s | raw +300 s | raw +900 s |
|---|---|---|---|---|
| 0 s | +17.3% | +52.6% | +71.6% | **+514%** |
| 1 s | +10.4% | +40.9% | +58.5% | +461% |
| **5 s** | +33.8% | +70.9% | **+92.8%** | **+586%** |
| 15 s | +45.1% | +52.4% | +64.8% | +512% |
| 30 s | +39.6% | +79.9% | +59.3% | +559% |
| 60 s | +30.1% | +62.3% | +36.7% | +416% |
| 120 s | +24.7% | +33.7% | −3.7% | +378% |
| 300 s | −6.6% | −14.3% | +22.7% | +134% |

**On this event the decay is slow — a 60-second reaction still captures +416% at fifteen
minutes.** That is one event, selected retrospectively, with a five-knob detector fitted to it
after the fact. §10 is the only version of this number worth acting on.

---

## 10. The latency-decay curve, as a population statistic

The same rule, the same constants, over every coin in the corpus: **3,805 events on 1,659
coins**. Two controls, because one is a knob — and here the difference between them is the
entire result.

| arm | median +300 s | median +900 s | median +3600 s | share beating friction @300 s |
|---|---|---|---|---|
| **burst entry** (0 s latency) | **−2.04%** | **−6.21%** | **−15.91%** | 0.314 |
| control: any minute, same coin | +0.00% | +0.00% | +0.00% | 0.117 |
| **control: active minute, same coin** | **−4.75%** | **−11.85%** | **−25.36%** | 0.297 |

The naive control is nearly worthless and it is worth saying why: most minutes of most coins
have no trade, a no-trade minute marks at exactly 0.00%, and an arm of dead rows "beats" an arm
of live rows that are merely falling. That is `RESULT_imitation_signal.md` §5.9's artifact —
the most seductive one in this dataset — and against it the burst looks like a losing trade.
The **active-minute** control (a random minute on the same coin that also cleared the rule's
own 20-SOL volume floor) isolates *burst* from *busy*, and against it the burst is **better by
+2.7 pp at five minutes, +5.6 pp at fifteen, and +9.5 pp at an hour**.

**Both statements are true and both matter.** In absolute terms a burst entry loses 2% in five
minutes and 16% in an hour — **there is no long trade here**, exactly as the brief predicted for
taker-side entries. Relative to the state it is drawn from, a burst is a materially *better*
moment than an ordinary busy minute on the same coin — which is a statement about **exits**:
the worst moment to be holding one of these is not the burst, it is the ordinary high-volume
minute after it.

### 10.1 The decay curve, paired and clustered on the coin

The two arms are two instants on the **same coin**, so the comparison that counts is paired.
1,056 coins carry both; median difference (burst minus active-minute control), 400-draw
bootstrap over coins:

| reaction latency | +300 s | +900 s | +3600 s |
|---|---|---|---|
| **0 s** | **+8.02%** [+5.43, +10.34] | **+12.58%** [+7.83, +16.86] | **+12.36%** [+8.03, +16.40] |
| 1 s | +7.97% [+5.43, +10.33] | +11.96% [+7.33, +16.51] | +12.24% [+8.34, +16.49] |
| 5 s | +7.25% [+5.07, +9.35] | +11.21% [+6.64, +15.44] | +11.68% [+8.30, +15.92] |
| 15 s | +7.23% [+4.90, +9.57] | +10.61% [+7.05, +14.24] | +12.21% [+7.64, +16.57] |
| **60 s** | **+3.97%** [+2.01, +6.00] | +8.22% [+4.16, +11.48] | +9.09% [+4.80, +13.72] |
| **300 s** | **+0.00%** [+0.00, +0.00] | +4.97% [+2.00, +7.74] | +7.06% [+2.61, +10.86] |

**Every interval excludes zero, and there is a real decay: the five-minute edge halves between
15 and 60 seconds and is gone by 300.** The fifteen-minute and one-hour edges decay more slowly
(−16% and −26% at a minute) but follow the same shape.

**So the answer to "tradeable at our latency or bot-only" is: our latency is fine, and the
signal is still not an entry.** At the pumpportal stack's 1–2 s the curve has lost ~1% of its
value (+7.97% vs +8.02% at five minutes); at a human's 300 s it has lost all of it at the short
horizon. Being early is worth something *relative to the alternative moment on the same coin* —
but the absolute level is negative at every latency, so what the curve prices is **when to be
out**, not when to be in. A rule that reacts inside a minute captures essentially the whole of
a real effect whose sign forbids the obvious use.

The `catwifglasses` event's +586% sits in the extreme right tail of this distribution. One draw
in 3,805.

---

## 11. Five other readings of "PvP"

The brief defined PvP as a property of a **coin**. That is a choice, and the operator's push —
*"we gotta explore creatively instead of just narrowmindedly refuting what the coordinator
said"* — produced four alternatives that are at least as consistent with how the word is used.
Two of them changed the study's conclusions.

**A — a market-wide state ("the board is PvP tonight"). NULL.** Hourly corpus-wide rotation
share runs p10 0.442 / median 0.539 / p90 0.632 and new-money share p10 0.268 / median 0.344 /
p90 0.427 — a real but narrow band. Board-level PvP is barely persistent (autocorrelation 0.303
at 1 h, 0.158 at 6 h, **0.022 at 24 h**), and coins born in the highest board-PvP quartile are
statistically indistinguishable from coins born in the lowest: graduation 12.6% vs 12.7%, dead
at 4 h **41.8% vs 45.0%** (if anything better), median `ret_1h` −3.4% vs −2.8%. **"Tonight is a
PvP night" is not a state with consequences on this corpus.**

**B — a lifecycle phase. THIS ONE LANDED, and it deflates §3.** Reported in full at §3.4. The
PvP score is monotone in age and carries 0.485–0.560 within an age band.

**C — onset as an event rather than a level. NULL.** Reported at §6.

**D — the wiggle flip. THIS ONE LANDED, and it is the most decision-relevant result in the
study.** Reported in full at §5.

**E — a property of the pack, not the coin. NULL as a forecaster, interesting as a
description.** The rotation cohort's net SOL cash flow is **negative in 81.3% of hours**, median
**−2,643 SOL/hour** (−4.8% of its own gross). It does not forecast anything: correlations of
pack cash flow against board PvP and against total buy volume 1–6 hours ahead run **−0.049 to
+0.157**, i.e. nothing. *(This is cash flow, not PnL — the cohort's token inventory is unmarked,
so it says where SOL went, not who won. Marking it is a real follow-up and needs a price for
every wallet's residual bag.)*

---

## 12. The anti-edge section, stated plainly

The brief's expected answer was *"the only edges are the arena (LP window) and the exits"*. On
this data it is narrower than that.

- **Taker entries into PvP: no.** §10, on 3,805 events with a matched control: −2.0% at five
  minutes, −15.9% at an hour. The paired edge over the right control is real (+8.0 pp at five
  minutes, CI [+5.4, +10.3], decaying to +4.0 pp at 60 s latency and zero at 300 s) and it is
  an edge over a *worse* alternative, not over zero. The one spectacular case is one in 3,805.
- **The LP arena in PvP: no, and the sign is backwards.** §4. `eta` falls seven-fold across the
  gradient; the arena is in the *low*-PvP state, the window is 30 minutes at the median, and the
  guarded opportunity in the top decile is the lowest on the board.
- **PvP transition as an exit signal: no at 30-minute resolution.** §6. Median lead exactly
  zero, 84.6% of leads are exactly zero, firing rate 31.6% against a null's 25.9%.
- **Copying or fading the rotation cohort: not tested, and §11 E says don't bother yet** — the
  pack's cash flow forecasts nothing at 1–6 hours.
- **What is left is exactly two things.** An **avoid/exit rule** with an honest operating curve
  (§3.5), whose useful reading is that the high thresholds predict *cessation of trading* and
  the low ones predict *falling price*; and the **wiggle flip** (§5), which is a positive
  selector for a book the desk already runs, at an oracle ceiling that the paper desk is the
  only honest way to price.

---

## 13. What to build, and what not to

1. **Do not build a PvP entry book.** §10 and §12.
2. **Wire the PvP score into the wiggle book's candidate ranking, not its gate.** §5 is a
   monotone gradient across nine deciles on an oracle ceiling; it belongs where
   `RESULT_imitation_signal.md` §9 put the swarm — as a covariate on an existing decision, not
   as a new trade. The paper desk already logs its decisions with propensities, so this is
   overturnable from the ledger without re-running the study.
3. **Keep `recycled_30m` as the incumbent inside the first thirty minutes.** §3.4: within that
   band it beats the whole PvP block 0.622 to 0.505. The PvP block earns its place on older
   coins and in combination, not as a replacement.
4. **Re-run §6 at 10-minute resolution before concluding the transition is coincident.** It is
   one parameter and it is the only limit in this document that could flip a verdict.
5. **The rotation cohort is a reusable object and it is cheap.** 324,582 wallets, 54.3% of all
   buy SOL, rebuilt hourly in 28 seconds. It belongs in the desk's state, not in this study.
6. **Find the surface the arbitration callout lived on.** §9.4 is a complete chain-side
   reconstruction with a hole where the social timestamp should be, and this is the first
   callout subtype in this repo whose mechanism (coordination) differs from the one three
   studies have already refuted (promotion). One collector closes it.
7. **Do not extend the vamp measurement without funding-ancestry clustering.** Same conclusion
   `RESULT_imitation_signal.md` §9 reached: distinct-deployer count bounds independence from
   above, and §8's 3.4% is measured on the 3.4% of clones that got funded at all.

### 13.1 The detector spec, for the coordinator

Requested as a spec, not as wiring. **This is the burst detector of §9.5/§10, and §10 says its
sign is negative for entries — so it is specified here as an exit/avoid trigger and a candidate
router, and must not be wired as a long entry.**

```
INPUT   per-mint trade stream (pumpportal subscribed mints, ~1-2 s), or the firehose
        trade tape; families from swarm_detect are the subscription trigger.
STATE   per mint: rolling 60 s buy-SOL sum; rolling 1800 s buy-SOL sum; first-seen time.
FIRE    age >= 1800 s
        AND buy_sol_60s >= 20 SOL
        AND buy_sol_60s >= 8 x max(buy_sol_1800s / 30, 1.0 SOL)
        AND no fire on this mint in the last 3600 s
EMIT    evidence only: {mint, t_fire, buy_sol_60s, baseline_rate, age_s, pool_sol}.
        Never a verdict, same contract as state/swarms/candidates.jsonl.
USE     (a) exit/avoid: a position held into the NEXT ordinary busy minute is the worst
            case measured (paired, coin-clustered: -8.0 pp at 5 min vs the burst minute
            itself, CI [-10.3, -5.4], n = 1,056 coins);
        (b) candidate routing into the wiggle book, which conditions on two-sided flow.
DO NOT  open a long on the fire. Measured: -2.0% at 5 min, -15.9% at 1 h, n = 3,805.
LATENCY the paired edge decays from +8.0 pp (0 s) to +4.0 pp (60 s) to 0.0 pp (300 s) at the
        5-minute horizon, so a 1-2 s reaction captures ~99% of it -- and the absolute sign
        still forbids using it as an entry.
CALIBRATION  3,805 fires on 1,659 coins over 10 days = ~16 fires/hour corpus-wide.
```

---

## 14. Trials accounting, spend, and limits

**Configurations evaluated:** 7 column blocks × 2 labels = 14 in §3.2, plus 12 univariate cells
under BY-FDR, 6 avoid thresholds × 2 labels, 3 blocks × 2 labels in §3.6, 10 PvP deciles × 2
books in §4/§5, 1 transition specification with an 8-draw null, 2 drain nulls × 30 draws, 6
latencies × 3 horizons × 3 arms in §10, and 5 alternative readings in §11. Call it **~120
substantive configurations.** PROGRAM.md §3.9: past ~7 independent configurations an in-sample
Sharpe of 1 is an out-of-sample zero.

Applied honestly, that is an argument for the negatives and against the marginals. What is
offered as real here is either a **null** (the arena, the transition, the market-wide state,
onset), or **large and monotone across many cells** (the eta gradient over ten deciles, the
wiggle gradient over ten deciles, the age gradient over seven bands), or a **structural count
that needs no model** (54.3% of buy SOL, 709 of 20,642 family edges, the 85-SOL cliff). The one
marginal positive — the PvP block's +0.005 incremental AUC — is reported with the null that
supports it and the age audit that shrinks it.

**Spend: $0.00.** No BigQuery, no Apify. ~9,000 free pump.fun API calls, browser-UA, ≥120 ms
apart, with exponential backoff.

### Limits, in the order they would bite

1. **The PvP score is largely age** (§3.4). Within-band univariate AUC is 0.485–0.560. Every
   marginal number in §3.2 should be read with that beside it.
1b. **The per-trade path sum over-counts net SOL by a median 24%** (§1.3), which is 3.18% of
   gross volume. Every conclusion here uses gross SOL, SOL-over-SOL ratios, or log price, so
   the defect is bounded and does not move a sign — but it is a defect and the fix is to price
   the dropped steps.
2. **The transition null is resolution-limited** (§6). A lead shorter than 30 minutes is
   invisible by construction. This is the limit most likely to change a verdict.
3. **The wiggle result is an ORACLE ceiling** (§5). The filter turns at exact extremes. This
   desk's own first eleven closes on the live wiggle book were −14.08%.
4. **The vamp measurement conditions on the clone getting funded.** 19,933 of 20,642 family
   edges are dropped because the clone never reached 100 counterparty touches (§8).
5. **The host-deterioration test is 87 matched pairs and nothing clears 0.05** (§8.1).
6. **`eta` is computed at a stated LP fee of 0.20%** and scales linearly in it; the cross-decile
   *ranking* is fee-independent, the levels are not. And `C` for a bonding curve is not an
   LP-able object at all — §4 is a statement about the arena's shape, not about a position
   anyone could have taken on a pre-migration coin.
7. **Ten days, one regime.** PROGRAM.md §3.6: this market shifts in weeks. The temporal split is
   within those ten days and is not a claim about next Tuesday.
8. **Recall on the corpus is unmeasured** (`scripts/pump_history.py`): selection is by the
   `%pump` mint suffix, a convention rather than a guarantee. High precision, unknown recall.
9. **The four operator coins were born before the corpus window**, so their curve-era history is
   absent and their `pool_sol` reads 0 on the corpus arm; §7's live arm exists because of this.
10. **The arbitration callout has no timestamp** (§9.4). Every claim about ordering in §9 is
    chain-side; the social side is bracketed, not measured.
11. **`hold_med_s`'s undefined-fill is a knob** (§3.3), swept, worth 0.0004 AUC.
12. **The live §7 table is 8–70 wallets per bucket** and its `rotation_share` is a lower bound
    because the cohort is 18 hours stale.
