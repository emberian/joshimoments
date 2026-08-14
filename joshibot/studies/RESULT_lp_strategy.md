# RESULT: how to run a DLMM pool — width, rebalancing, fee tier, pair selection

2026-08-14. Script: `studies/lp_strategy.py`
(`uv run python studies/lp_strategy.py`, or `--measure --selftest --eta --pairs --hedge
--width --rebalance --fee --rail --exit --crossover --il --live --json`).
Every number below is produced by that script from `state/cluster_tape/` and, for the live
book check, the public Meteora data API. This study owns exactly two files and writes
nothing anywhere.

**Objective, as corrected by the operator mid-study.** Maximise **fee harvest per unit of
capital, subject to never being forced to exit at a bad moment** — not "minimise
impermanent loss". The desk expects to choose its exit over days and is content to hold
inventory meanwhile. That correction changes the answers, and where it does, both answers
are given with the crossover between them stated (§11).

**Sources and what each is trusted for.**

| source | window | trusted for |
|---|---|---|
| `state/cluster_tape/swaps/*.jsonl` | 2026-08-13 → 08-14, 2,937 swaps over 6 pools | per-swap vault reserves — marginal prices, volumes, realised fees, trade sizes. The only ground truth here |
| `dlmm.datapi.meteora.ag` | live at run time | the operator's open positions (ranges, active bin, per-token value) |
| `RESULT_power_gate.md` §2 | quoted | the 5.552% measured DLMM fee rate, the $842.49 / `w_eff` 0.894 reference position, 32.1%/day realised |
| `RESULT_circuit_theory.md` | quoted and independently reproduced | the `η > VR` rule, bounce-free VR, decoded 1.44% PumpSwap taker fee |
| `RESULT_edge_creation.md` | quoted | duty cycles (99.4% / 49.4%), the −$130.80 / −$595.14 realised record |
| `RESULT_lp_history.md` | quoted | 42 positions, position rent 0.057 SOL, the ladder reading |

The common ratio window is **5.78 hours**. Re-running will move digits. If it moves a
verdict, that is a finding and this document is wrong.

---

## 0. THE HEADLINE, AND IT REVERSES THE BRIEF I WAS GIVEN

The brief said the edge is measured and the open question is how to run it. Three things
found here say the harder question is whether to run it at all:

1. **The mean-reversion premise, which was the load-bearing assumption behind every
   "impermanent loss is temporary" argument, does not survive a bounce-free measurement.**
   This file's ratio series is built from post-swap vault reserves — marginal prices, no
   bid-ask bounce — and its adjacent-horizon variance ratios run to **1.00 and above past
   fifteen minutes**. `RESULT_circuit_theory.md` gets the same answer from per-swap vault
   balances on four of four pools (VR 0.80–1.01 at 15m–1h). The 7.2–8.9 h half-lives in
   `RESULT_swing_cluster.md` came from last-trade closes and are the outlier. **Treat the
   ratio as a random walk at the holding horizon.**
2. **`η` measured independently here reproduces `RESULT_circuit_theory.md` exactly:
   0.667 against their 0.59–0.70.** Two derivations — DLMM bin algebra here, the circuit
   frame there — land on the same inequality and the same number. With `η < 1` and
   `VR ≈ 1`, no rebalance policy makes the pool +EV: **a perfect duty cycle still leaves it
   at or below break-even.**
3. **Concentration is pure leverage on a sign set elsewhere.** `4/w_eff` multiplies fees
   and losses identically. The realised record is negative (−$595.14 vs hold across 10
   closed positions), so narrowing has been levering the wrong sign.

What survives, and it is not nothing: the **duty-cycle rule** is real, regime-independent,
and worth 20–55% of fee income; the **concentrated-IL formula** is exact and corrects a
3.4–12.2× understatement; and the **exit/laddering structure** for dated cash is
actionable today.

---

## 1. THE MODEL, AND ITS THREE VALIDATIONS

A Meteora "Spot" position puts equal liquidity `L` in every bin. A bin at price `p`
satisfies `x·p + y = L`, so **crossing one bin trades exactly `L` of quote value regardless
of the price**. With `δ = ln(1+bin_step/1e4)` and `ℓ = L/δ` (quote value traded per unit of
log price), a position spanning `a` below and `b` above the current price is completely
described by `(a, b, ℓ)`:

```
    VALUE(m)  =  ℓ·[ a + m + 1 − e^(m−b) ]           m ∈ [−a, b], quote units
    HOLD(m)   =  ℓ·[ a + (1 − e^(−b))·e^m ]
    IL(m)     =  ℓ·( 1 + m − e^m )                   ≈ −ℓ·m²/2
    VOLUME    =  ℓ · (total variation of the pool's log price, clipped to the range)
    FEES      =  f_lp · VOLUME
```

`IL` is **exact**, **path-independent** (only the net displacement enters), and **symmetric
in sign to second order**. Outside the range it continues on a second branch that the
full-range formula does not have.

**Validation 1 — the discrete bin ladder.** A bin-level simulator with per-bin reserves
reproduces the continuum value and volume to 1% at every displacement tested, and the
residual is exactly the `O(bin_step/2)` discretisation term.

**Validation 2 — the operator's live book.** For a Spot position the split of value between
the two tokens is forced to be `a : (1 − e^(−b))` — a pure function of the range and the
active price, using **no deposit information at all**. Read live:

| position | a | b | predicted quote share | observed | error |
|---|---|---|---|---|---|
| weave/SOL | 0.000 | 0.396 | 0.00% | 0.00% | −0.00pp |
| nosis/weave | 0.148 | 0.709 | 22.53% | 26.53% | +4.00pp |
| weave/SOLVE | 0.772 | 0.574 | 63.87% | 61.47% | −2.40pp |

**Validation 3 — the fee wiring, which is the bug this file was built not to have.** A
prior simulator credited down-move fees to the fee bucket *and* subtracted them from LP
reserves, so LPs only earned on up-moves and half of fee income vanished on chop. Here fees
live in buckets the swap math never reads, and `--selftest` asserts, across 25 checks:

- an up-then-down round trip accrues a strictly positive fee **in both tokens**;
- the base-side fee is created **only** by the down leg (zero after the up leg alone);
- the round trip restores **every bin reserve exactly**;
- the up-leg fee equals `6 × L × f/(1−f)` to 6 decimal places;
- a chop path earns **20×** a one-way path to the same final price;
- a one-sided redeploy and a swap-recenter produce **different** inventory outcomes (so a
  rebuild cannot launder value into or out of the benchmark).

**If `--selftest` does not print ALL PASS, nothing below is trustworthy.**

---

## 2. THE DECISION RULE — `η·D > VR`

`RESULT_circuit_theory.md` derives the parameter-free condition `η > VR`, where
`η = 2fN/(C·RV) = fees/LVR` and `VR = (net move)²/RV`. This study reached the identical
inequality from the bin algebra: `Π = f_lp·ℓ·TV − ℓ·m²/2 > 0 ⟺ 2f_lp·TV/RV > VR`. Same rule,
two routes. On pure arbitrage flow the band model gives `TV = RV/(2f)`, hence `η = 1`
exactly — **0.90 after Meteora's 10% protocol cut**, which is the entire margin a
martingale pair has, and it is negative.

**This study adds one term the theory does not carry: DUTY CYCLE.** Fees accrue only while
in range; divergence accrues always, and past the range edge the position is 100% of one
token and the loss stops being sub-linear at all. So

```
    +EV   ⟺   η · D  >  VR          ⟹   REQUIRED DUTY CYCLE   D* = VR / η
```

**Measured, on the operator's own weave/nosis tape window:**

| | |
|---|---|
| window | 5.33 h, 77 swaps, 37 distinct fee payers |
| C = ℓ | $942 (from $842.49 / `w_eff` 0.894) |
| volume in | $2,112 → $9,517/day |
| fees at `f_lp` = 5.4% | $114.07 |
| σ at the band horizon (3.2 min) | 127.9%/day → RV = 0.3629 |
| LVR = C·RV/2 | $170.97 |
| **η = fees/LVR** | **0.667** — vs `RESULT_circuit_theory.md`'s 0.59–0.70, reproduced independently |
| net ratio move | **−26.93%** → VR realised 0.200 |
| IL vs HOLD (exact formula) | **−$31.30** |
| fees − IL(hold) | **+$82.77** |
| fees − LVR | **−$56.90** |

**Those two bottom lines disagree in sign and both are correct.** LVR benchmarks against a
*continuously rebalanced* portfolio; IL benchmarks against *holding*. They differ by exactly
`VR`, which on this window was 0.20. "Fees minus adverse selection is negative" and "the
position beat holding" are both true of the same position. **This desk holds the tokens
anyway, so hold is the right benchmark** — and the LVR-negative reading should not be quoted
as a loss without that qualifier. It does not rescue the programme, because the realised
record is against hold too: −$595.14 across 10 closed positions.

**Required duty cycle `D* = VR/η`, against the two duty cycles measured on chain:**

| η | VR=0.20 | VR=0.50 | VR=0.80 | **VR=1.00** | VR=1.20 | verdict at D = 99.4% / 49.4% |
|---|---|---|---|---|---|---|
| 0.59 | 0.34 | 0.85 | 1.36 | **1.69** | 2.03 | −EV / −EV |
| 0.667 | 0.30 | 0.75 | 1.20 | **1.50** | 1.80 | −EV / −EV |
| 0.90 | 0.22 | 0.56 | 0.89 | **1.11** | 1.33 | −EV / −EV |
| 1.08 | 0.19 | 0.46 | 0.74 | **0.93** | 1.11 | +EV / −EV |

**The DREGG/nosis post-mortem falls straight out of this table.** That pool harvested
*better* per hour in service than weave/nosis (67.6%/day vs 57.6%/day) — a higher η — and
still lost $215.63, because its duty cycle was 49.4%. Halving `D` halves the left side and
does nothing to the right. It did not fail on pair choice, fee tier, or width.

---

## 3. WHERE THE REVERSION LIVES — the measurement that changes the conclusions

Variance ratio between **adjacent** sampling horizons, on bounce-free marginal-price ratios:

| pair | 30→60s | 60→300s | 300→900s | 900→1800s | overall 30s→30m |
|---|---|---|---|---|---|
| DREGG/SOLVE | 1.00 | 1.17 | 1.22 | 0.99 | 1.41 |
| DREGG/nosis | 0.95 | 0.81 | 0.74 | **1.37** | 0.78 |
| DREGG/weave | 1.14 | 1.06 | 1.00 | 0.88 | 1.06 |
| SOLVE/nosis | 0.95 | 0.76 | 0.71 | **1.24** | 0.64 |
| SOLVE/weave | 1.13 | 1.01 | 0.90 | 0.67 | 0.69 |
| nosis/weave | 0.99 | 0.84 | 0.48 | **1.11** | 0.44 |

The reversion is concentrated in the **30s → 300s decade** — transient price impact from
individual swaps, reverting within minutes. The 900→1800s column, which is where the desk's
holding horizon *starts*, sits at or above 1.00 on three of six pairs and the CI on every
one of them spans 1.

`RESULT_circuit_theory.md` reaches the same place with a different instrument (per-swap
vault balances, VR 0.80–1.01 at 15m–1h on four of four pools; SOLVE/SOL at 4h reads 1.50
bounce-free against 0.587 from closes). **Two independent bounce-free measurements now
agree, and the last-trade-close half-lives are the outlier.**

**Working assumption for everything below: VR = 1 at the holding horizon.** The measurement
that would overturn it is nine days of tape and a bounce-free multi-day VR — the same nine
days `RESULT_power_gate.md` already asked for, and now the highest-value outstanding item
in the programme, because it is the difference between two rebalance policies that differ
by 20–40% of fee income.

---

## 4. THE REBALANCE RULE — the deliverable

**It is a duty-cycle controller.** And it is two decisions, which is why it looked hard:

**Decision 1 — REDEPLOY.** Move the range to the current price, depositing the token you
already hold, one-sided. No swap, no inventory change. Cost **$0.015** in gas (two
transactions; the 0.057 SOL of position rent is *recovered* on close, so it is locked
balance, not cost). Against a position earning 10%/day on $500 that is repaid in **26
seconds**.

**Decision 2 — RE-CENTER WITH A SWAP.** Buy back to a two-sided shape. This costs a real
swap — **2.88% round trip**, the decoded PumpSwap taker fee of 1.44% on each leg, *not* the
0.20% LP leg, and using the LP figure here understates it 7× — and it crystallises the
inventory rotation.

**Simulated, three regimes, $1,000, ±0.35 range, 3 days, calibrated to the tape** (σ scaled
so simulated TV matches the pool's realised TV; taker arrivals set to the measured residual
of $2,815/day = 30% of flow):

| policy | trigger d | rebuilds | in-range | fees | costs | HARVEST | PnL vs hold |
|---|---|---|---|---|---|---|---|
| *random walk* | | | | | | | |
| none | — | 0 | 30.5% | 642 | 0 | 642 | −1085 |
| one_sided | 0.00 | 111 | **93.5%** | 1362 | 1.7 | **1360** | −810 |
| one_sided | 0.30 | 7.1 | 66.0% | 1127 | 0.1 | 1126 | −902 |
| swap | 0.00 | 15.1 | 99.0% | 1558 | **119** | 1439 | −698 |
| *OU, 8 h half-life* | | | | | | | |
| none | — | 0 | 58.9% | 1234 | 0 | 1234 | **+1104** |
| one_sided | 0.00 | 86 | **94.7%** | 1463 | 1.3 | **1461** | +739 |
| one_sided | 0.60 | 1.1 | 64.0% | 1257 | 0.02 | 1257 | +915 |
| swap | 0.00 | 13.6 | 99.1% | 1537 | 104 | 1433 | +661 |
| *trend, −50%/day* | | | | | | | |
| none | — | 0 | 26.8% | 569 | 0 | 569 | +26 |
| one_sided | 0.00 | 113 | **93.6%** | 1202 | 1.7 | **1200** | +375 |
| swap | 0.00 | 15.9 | 99.0% | 1353 | 93 | 1260 | +447 |

### THE RULE

1. **Never sit out of range.** Doing nothing costs **20% to 55% of fee income in every
   regime**, because in-range time collapses to 27–59%. This is the only unconditional
   result in the section and it is worth more than everything else in it.
2. **Redeploy ONE-SIDED, not by swapping.** One-sided captures **87–95%** of the fee income a
   swap-recenter does, at **1/50th to 1/80th the cost** ($1.31–1.72 vs $93–119 over three
   days) and with zero inventory rotation. The swap's 5% edge in fees does not pay for 2.88% round-trip
   friction on a book that rebuilds more than once a day.
3. **Trigger: `d = 0` to `0.15` beyond the range edge**, targeting **duty cycle > 95%** —
   *under the working assumption VR = 1*. With no reversion there is nothing to wait for,
   the option that justified waiting is worth zero, and duty cycle is the only lever.
4. **REVERSION-CONTINGENT FALLBACK, labelled as such.** If a multi-day bounce-free VR comes
   back materially below 1, move to `d = 0.3–0.6`. That is the minimax-regret answer across
   the three regimes (best three: `swap` d=0.60 at 62%, `one_sided` d=0.30 at 64%,
   `one_sided` d=0.60 at 68%; both corners sit at the bottom of the table), and it is also
   where the closed form `d* = 2y/θ` lands for y = 15–30%/day against an 8 h half-life. It
   is a compromise that gives the reversion regime one third of the weight, and the
   evidence no longer supports that weight.
5. **Exit, as opposed to re-center, on the rail firing** — §7. That is a different question.

### WHAT DIES IF THE RATIO IS A RANDOM WALK

| claim | status under VR = 1 |
|---|---|
| Never sit out of range | **survives, and strengthens** |
| Redeploy one-sided rather than swap | **survives** |
| Establish the sign before levering it | **survives** |
| `d* = 2y/θ` threshold | **dies** — θ = 0, so d* = ∞ and the derivation says "always redeploy" |
| minimax-regret d = 0.3–0.6 | **dies** — it was a compromise weighted toward reversion |
| "waiting keeps the reversion option" | **dies** — there is no option |

### THE CAVEAT THAT LIMITS ALL OF IT

Raising `D` raises `η·D` but cannot raise it past `η`, and `η` is measured at **0.667**. At
VR = 1 a *perfect* duty cycle still leaves the pool below break-even. **A rebalance rule
cannot rescue a pool whose η is below 1; it can only stop a pool with η above 1 from being
thrown away.** Fixing duty cycle is necessary and not sufficient. Anyone reading this
section as "rebalance harder and the programme works" has read it wrong.

---

## 5. THE WIDTH RULE

**First, the thing that overrides the sweep.** `4/w_eff` multiplies *both* sides of the
ledger, so it is pure leverage on the sign of `(η·D − VR)` and cannot change that sign. The
realised sign has been negative. **Establish the sign before choosing the leverage.**

**On magnitude: width barely matters and has no interior optimum.** Harvest falls as roughly
`h^(−0.2)` across the whole sweep in all three regimes — a 50× change in width (2 bins to
100 bins at bin_step 300) moves harvest by less than 2×, and the harvest-best width is
always the narrowest offered. There is no peak. Anyone reporting an optimal DLMM width from
a yield curve this flat is reporting simulation noise.

The reason is structural: fee income splits into an arbitrage part scaling as `ℓ = V/w_eff`
(so `1/width`, favouring narrow without limit) and a taker part that is width-blind once the
pool is deep relative to the size distribution (median $15.39, p90 $70, CV 1.36). The
width-blind part is ~30% of flow and flattens the curve; the other part has no interior
optimum, so the corner is at the narrowest width you can operate.

**The calibration check that makes the sweep readable.** The operator's live nosis/weave
position is `a = 0.355, b = 0.502`, i.e. `h ≈ 0.43`. The simulator at `h = 0.40–0.50` says
**52–56%/day of harvest**. The tape says **32.1%/day** (power_gate, 6.07 h) to **61%/day**
(this study's busier 5.33 h window). **The simulator lands inside the measured range at the
operator's actual width without being fitted to it.**

**The rule, in the form that decides something:**

```
    h* = σ / √N          N = rebuilds per day you can sustain

    N = 2/day  → h = 0.71σ      N = 24/day  → h = 0.20σ
    N = 6/day  → h = 0.41σ      N = 100/day → h = 0.10σ
```

**Cross-check against the operator's own tempo.** `h ≈ 0.43` on a calibrated σ of 0.92/day
gives a centred first-exit rate of `(0.92/0.43)² = 4.6` rebuilds/day. The August campaign
ran 23 positions over roughly three days — about 8/day. Same order from two independent
directions, and the factor of ~2 sits exactly where a modest redeploy threshold puts it.

**The recommendation, which is the conservative half of the objective disagreement.** With
VR = 1 and the realised sign negative, the harvest-optimal corner at 2–7 bins is maximum
leverage on a negative number. **Run wide — `h ≥ 0.5`, which is 34+ bins at bin_step 300,
and is where PnL-vs-hold peaks in all three regimes — until `--eta` shows `η·D > VR` over a
window longer than a day.** The operator's live ranges (30 bins on nosis/weave, 69 on
weave/SOLVE) are already in that band. **Do not narrow them.**

---

## 6. THE FEE TIER

**Derivation.** Split the flow: `Π = f_lp·Q(f) + (f_lp − f)·Vol_arb(f) − jump excess`. Since
`Vol_arb = ℓσ²/(2f)`, the middle term is `−s·ℓσ²/2` with `s` the protocol share —
**completely independent of `f`**. Raising the fee earns not one dollar more from arbitrage;
crossings get rarer in exact proportion as each gets bigger. So the tier is priced entirely
against uninformed flow and jumps, and the first-order condition is

```
    ε*  =  −(1 + Vol_informed / Q)
```

which at the tape's 30/70 split is **ε\* = −1.4 to −1.6, not the textbook −1**. You may
charge more than a plain monopolist because a higher fee also improves your terms of trade
against the flow picking you off.

**But there is no demand curve to solve against, because the flow is not price-minimising.**
Our pool's all-in cost against the measured two-leg SOL substitute (ℓ = $4,698 measured;
PumpSwap taker fee 1.44%/leg decoded):

| trade size | our all-in | substitute all-in | we are |
|---|---|---|---|
| $5.0 | 6.27% | 0.45% – 2.93% | 2.1× dearer |
| $15.4 (median) | 6.82% | 0.56% – 3.04% | 2.2× dearer |
| $26.4 (mean) | 7.40% | 0.68% – 3.16% | 2.3× dearer |
| $100 | 11.31% | 1.46% – 3.94% | 2.9× dearer |
| $500 | 32.53% | 5.72% – 8.20% | 4.0× dearer |

Reproduces `RESULT_circuit_theory.md`'s "median trade pays 2.67× the best available route"
independently. **77 swaps from 37 distinct payers in 5.33 hours went through the dearer
route anyway.** A cost-minimising router does not do that.

**So the edge is ROUTER-ATTENTION RENT, not pricing power, and the failure mode is a step
function.** Pricing power erodes when a rival undercuts you — gradually, visibly, with a
slope you can respond to. Attention rent ends in one Jupiter deploy, all at once, with no
intermediate state. Consequences:

- **There is no interior optimum to solve for.** The revenue-maximising fee is "as high as
  the flow tolerates", and the tolerance is unobservable until it is zero.
- **Do not size the book to this revenue stream.** A stream that can go to zero between two
  blocks is not something to lever, borrow against, or schedule obligations from (§8).
- **The monitoring target is not a rival's fee. It is whether Jupiter routes this pair
  through us at all** — a free daily quote-API query, and the cheapest early warning in the
  programme.
- **The 5.0% vs 6.0% question is second-order against a binary that size.** Do not spend
  effort there.

**What the fee tier does buy, and this part is derived.** A jump of log size `J` moves the
pool through `ℓ·J` of volume at an average adverse price of `J/2`, netting
`ℓ·J·(f_lp − J/2)`. So the tier is exactly the jump size the pool absorbs before a crossing
loses money — `2·f_lp`:

| base fee | f_lp | break-even jump |
|---|---|---|
| 0.20% | 0.18% | 0.4% |
| 2.00% | 1.80% | 3.6% |
| **6.00%** | **5.40%** | **10.8%** |
| 10.00% | 9.00% | 18.0% |

The four token/SOL pools print median single-swap impacts of 12–42 bps and p90s of
100–243 bps. A 6.0% tier absorbs jumps to 10.8% — into the tail. A 2.0% tier absorbs 3.6%
and gets picked off by the top decile of prints. **That is the defensible argument for a
high tier on memecoin pairs, and it is independent of the monopoly story.**

**RECOMMENDATION: hold 5–6%.** The 2-point "elasticity" available (DREGG/nosis at 5.0%,
159.1%/day turnover; weave/nosis at 6.0%, 120.7%/day → arc ε = −1.51, which lands almost
exactly on ε\* = −1.56) is a coincidence across two different pairs of different ages and
volatilities with n = 2. It is worth zero and is recorded here only so nobody rediscovers it
and believes it.

---

## 7. PAIR RANKING

`Π/V = (σ_band²/2w_eff)·(η_arb − VR)` with `η_arb = 0.90`. Volatility is the fuel; the
variance ratio only decides whether you keep it.

| rank | pair | σ_band %/day | σ_hold %/day | VR (30 min) | gross fee %/day | IL %/day | NET %/day |
|---|---|---|---|---|---|---|---|
| 1 | **nosis/weave** | 127.9 | 93.4 | 0.53 | 81.7 | −48.5 | **+33.3** |
| 2 | SOLVE/weave | 53.0 | 43.3 | 0.67 | 14.0 | −10.4 | +3.6 |
| 3 | SOLVE/nosis | 117.7 | 110.9 | 0.89 | 69.3 | −68.4 | +0.9 |
| 4 | DREGG/weave | 54.9 | 51.5 | 0.88 | 15.1 | −14.8 | +0.3 |
| 5 | DREGG/SOLVE | 22.2 | 22.2 | 1.00 | 2.5 | −2.7 | −0.3 |
| 6 | DREGG/nosis | 120.4 | 121.3 | 1.01 | 72.5 | −81.7 | −9.2 |

**Three things this table says, in order of how much they should change behaviour:**

1. **The VR column is measured at a 30-minute holding horizon because that is the longest
   this tape supports, and that is not the desk's holding horizon.** Set VR = 1 and **every
   pair goes negative**, because `0.90 − 1.00 < 0` — the protocol's 10% cut is more than the
   entire margin a martingale pair has on arbitrage flow. Read this as "which pair if any",
   not "these pairs pay".
2. **`RESULT_swing_cluster.md`'s recommendation to seed DREGG/SOLVE is wrong and this
   ranking says why.** DREGG/SOLVE has the most robust reversion at the hourly scale and
   the *lowest* volatility (22%/day against 128%). Income scales as σ², so it ranks
   **fifth of six** and is negative. **A robustly mean-reverting but quiet pair is the worst
   LP venue, not the best.**
3. **DREGG/nosis ranks last here and `RESULT_edge_creation.md` ranks it second by
   `σ²/band`.** Both are right about different things: it is a loud edge (high σ, high fee
   income per hour in service — 67.6%/day measured) with a variance ratio at or above 1.
   The disagreement is entirely the VR term, i.e. entirely §3's open question.

---

## 8. THE STRUCTURAL CLAIM THAT FAILED: token-token pools are not delta-hedged

The claim was that a weave/nosis position's IL is driven by the relative price only, so a
cluster-wide dump barely moves the ratio and token-token pools are structurally lower-IL.

**It has a closed-form threshold.** With `σ_ratio² = σ_A² + σ_B² − 2ρσ_Aσ_B`, the
token-token pool carries less IL variance than the average of its two SOL-quoted
alternatives exactly when

```
    ρ  >  ρ*  =  (σ_A² + σ_B²) / (4·σ_A·σ_B)   ≥  1/2       (AM-GM)
```

**so the claim cannot hold at any correlation below 0.5, whatever the volatilities.**

Measured at 60s on the common window: **implied ρ runs −0.04 to +0.08** — indistinguishable
from zero — against a required 0.5. **0 of 6 pairs hedge.** At ρ = 0 the identity collapses
to `σ_ratio² = σ_A² + σ_B²`, so a token-token pool carries almost exactly **twice** the
IL-driving variance of the average of its legs (measured 1.89–2.01×).
`RESULT_swing_cluster.md`'s hourly 0.11–0.24 and `RESULT_edge_creation.md`'s −0.05 to +0.20
point the same way. **The claim fails at every horizon anyone in this programme has
measured.**

**But the conclusion it was meant to support survives, for the opposite reason.** Fee income
and IL are *both* proportional to σ² of the quoted price. A pool with 2× the variance has 2×
the IL and 2× the arbitrage fee income. Under the harvest objective that is more fuel, not
more cost: **the token-token pool is better precisely because the ratio is noisier than
either leg**, and what decides whether the extra variance is kept is VR, not ρ. "Token-token
is partially delta-hedged" and "token-token harvests more" are contradictory justifications
for the same position, and the tape supports the second.

**One place the hedge might still be real, and this window cannot see it.** A cluster-wide
risk-off event — every token down together against SOL — moves the ratio far less than
either leg. That is a daily-scale correlated shock and 5.8 hours of 60-second returns cannot
contain one. **Falsifiable and cheap:** recompute this table at dt = 3600 over a week
containing a market-wide down day. If ρ jumps above 0.5 only in that window, the hedge is a
*tail* hedge, which would be worth having and worth saying precisely.

**And the hedging that does not exist.** There is no borrow market for these tokens, so
classical delta-neutral LP is unavailable. The only hedges on the table are within-cluster
offsetting positions, and the measurement above says they work on the quiet pairs and invert
on the loud ones — available exactly where you do not need it. **The IL-minimising regime
here has to be reached by sizing and structure, not by hedging.** Anyone proposing a
delta-neutral cluster book should be asked to name the instrument.

---

## 9. INVENTORY / IL ACCOUNTING DONE RIGHT

The full-range constant-product form `V·(2√R/(1+R) − 1)` — which marketfabric's `il_vs_hold`
applies to concentrated positions — is wrong twice: it understates the in-range loss by
`4/w_eff`, and it has **no branch at all** for range exit, where the position is 100% one
token and the loss keeps growing.

| position | a | b | `w_eff` | **4/w_eff** | IL @ +10% | IL @ +25% | full-range @ +25% |
|---|---|---|---|---|---|---|---|
| weave/SOL | 0.000 | 0.396 | 0.327 | **12.23×** | −$12.79 | −$84.18 | −$6.28 |
| nosis/weave | 0.355 | 0.502 | 0.750 | **5.34×** | −$3.01 | −$19.79 | −$3.38 |
| weave/SOLVE | 0.673 | 0.673 | 1.163 | **3.44×** | −$0.47 | −$3.10 | −$0.82 |

On a 25% adverse move the correct concentrated loss is **2.5× to 13×** the full-range
number. `RESULT_edge_creation.md` measures realised divergence at **4.7× and 8.2×** the
constant-product figure on the two closed positions it reconstructs — inside this band, from
chain, independently.

**Numeraire matters and is usually left unstated.** For a token-token pool the quote is not
money. `SpotPosition.il_geomean` re-expresses the loss in the ratio-neutral
`√(P_base·P_quote)` numeraire; on the nosis/weave position the two differ by `e^(−m/2)`,
which at m = 0.5 is 22%. Say which one you mean.

---

## 10. EXIT CAPACITY AND THE DATED CASH

Single swap capped at ρ = 2% of the pool's SOL side; repeated swaps capped by flow at ~5% of
daily volume. `T_exit = S / (0.05 · volume_per_day)`.

| token | SOL side | TVL | ℓ | ρ=2% leg | vol/day | **1-day exit cap** |
|---|---|---|---|---|---|---|
| nosis | $28,453 | $56,906 | $14,226 | $569 | $823,205 | **$41,160** |
| weave | $14,027 | $28,054 | $7,014 | $281 | $61,445 | **$3,072** |
| DREGG | $27,792 | $55,583 | $13,896 | $556 | $10,756 | **$538** |
| SOLVE | $7,627 | $15,255 | $3,814 | $153 | $5,847 | **$292** |

**Obligations: $900 on Aug 28 (T-14), $1,050 on Sep 1 (T-18) — $1,950 against a $1,351 open
book. The obligations are 1.4× the book.** Three answers, in priority order:

1. **The fee stream is the first source and is plausibly sufficient — which is the most
   dangerous sentence in this document.** At the measured 32.1%/day gross the book covers
   $1,950 in 4.5 days; at a defensive one-fifth of that, 23 days, which still clears T-14.
   But a 6-hour sample of a heavy-tailed process is not a forecast, the stream is
   router-attention rent that can stop in one deploy (§6), and the realised programme record
   is −$130.80 net. **Plan as if the fee stream is zero and treat it as upside.**
2. **Exitability is the real constraint and it is comfortable on two tokens, not on four.**
   nosis and weave clear both obligations in a day. **DREGG needs 3.6 days and SOLVE 6.7
   days** to clear the full amount.
3. **Structure, which is free.** A token-token position needs *two* exit legs to become SOL
   and its fill direction is a bet on the ratio; a token/SOL position needs one. **Dated
   cash should not sit in token-token pools.** Put it in a **token/SOL sell ladder** — an
   ask-side one-sided position above the current price. It converts to SOL automatically as
   the price rises, earns fees doing it, and needs no timing decision. That is exactly the
   structure `RESULT_lp_history.md` found the operator already running.

### THE ALLOCATION

- **By T-10 (Aug 18): at least $900 — 67% of the book — in token/SOL sell ladders on weave
  or nosis**, not in token-token pools.
- **By T-3 (Aug 25): that fraction FILLED or closed to SOL**, not merely laddered. *A ladder
  that has not filled is not cash.*
- The remaining ~33% can stay in the token-token pools; it has no date on it.
- **DREGG and SOLVE exposure should carry no dated cash at all** — their one-day exit caps
  ($538, $292) are below a single obligation.

*Falsification:* the 5%-of-daily-volume cap is a convention, not a measurement. Replace it by
scoring each historical ladder fill against the market price at that slot
(`RESULT_lp_history.md`'s own item 1), which converts it into a measured impact curve.

---

## 11. THE CROSSOVER — when IL minimisation becomes the right objective

The discriminator is one thing: **can you choose your exit?** Three mechanisms take the
choice away.

**(a) SCALE.** `T_exit = S/(0.05·volume)`. Position size at which the exit window reaches one
day:

| token | vol/day | S(1 day) | S(3 days) | S(7 days) |
|---|---|---|---|---|
| nosis | $823,205 | **$41,160** | $123,481 | $288,122 |
| weave | $61,445 | **$3,072** | $9,217 | $21,506 |
| DREGG | $10,756 | **$538** | $1,613 | $3,764 |
| SOLVE | $5,847 | **$292** | $877 | $2,046 |

**Against the $1,351 open book, per-token exposure is already above the one-day threshold on
DREGG ($538) and SOLVE ($292) and comfortably below it on weave ($3,072) and nosis
($41,160).** The desk is **already in the IL-minimising regime for DREGG and SOLVE** and
still in the harvest regime for weave and nosis. That is not a future crossover, it is a live
split, and it argues for running the two objectives **per token**, not per desk. It moves
with volume, not the calendar — recompute weekly, four numbers off the tape.

**(b) DATED OBLIGATIONS.** The fraction of the book with a date on it is in the
IL-minimising regime by definition. $1,950 of a $1,351 book is dated — **144%**, which is
over 100% and is the real finding of §10.

**(c) CAPITAL EFFICIENCY — this one dissolves rather than binds.** Holding a bag through a
drawdown costs the yield the capital could have earned *only if the bag is idle*. Under the
rebalance rule a bag is never idle: it is a one-sided ladder still earning on one direction.
The opportunity cost of waiting is the gap between one-sided and two-sided capture — a factor
of ~2, not of infinity. The genuinely new content of (c) is the negative: **never let
inventory sit outside a range.**

**What changes at the switch:**

| harvest regime | → | IL-minimising regime |
|---|---|---|
| one-sided redeploy | → | swap-re-center at d < d* |
| width at the operational limit | → | wider, and **closed** rather than redeployed on exit |
| token-token pools | → | prefer hedge factor < 1 pairs (§8 says none qualify) |
| hold through drawdowns | → | size to the exit window, not the fee yield |

**What to watch, so the switch is deliberate rather than discovered afterwards:** per-token
exposure ÷ (0.05 × that token's 24 h volume) — switch that token when it exceeds ~2 days;
fraction of book dated inside 3× the exit window; and the multi-day bounce-free VR, which is
the single largest unmeasured term in the whole strategy.

---

## 12. THE SAFETY RAIL — reverting-hold vs trending-exit

The instinct is a price-prediction rail. Do not build one. Three rails, increasing in value,
and the best forecasts nothing.

**RAIL 1 — DRIFT SIGNIFICANCE.** `t = net move / (per-step sd · √n)`. Exit at t < −2
sustained. Weak: it takes as long to reject a random walk as the drift takes to hurt.

**RAIL 2 — DEPTH DRAWDOWN.** A token in secular decline loses its LPs before it loses its
last buyer, and the SOL-side reserve is a stock, not a flow, so it is far less noisy than
price. **Exit when the SOL side is down >35% from its trailing peak.** Measurable from the
tape today with no new instrumentation.

**RAIL 3 — FEE-FLOW DEATH, the one to run.** The thesis is "harvest volatility", not "the
price recovers", so the correct exit signal is that **the fee stream stopped** — which is
simultaneously the symptom of secular decline (volume dies before price bottoms), the
signature of a Jupiter routing change (§6), and the removal of the reason to hold at all.

> **EXIT WHEN: realised fee accrual over the trailing 24 h falls below 1%/day of position
> value, for 24 consecutive hours, WHILE THE POSITION IS IN RANGE.**

The in-range clause makes it a decline detector rather than a range detector: out of range
you earn zero for a reason you already know how to fix. In range and earning nothing means
the flow is gone. Both inputs are already served by the API the desk reads (`allTimeFees` +
`unclaimedFee`), so it is a monitoring rule, not a project.

**Current rail state (no rail fires — as expected on a quiet window, and NOT evidence the
rails work):**

| token | window | SOL side | peak | drawdown | net move | t(drift) | vol/day |
|---|---|---|---|---|---|---|---|
| nosis | 6.5 h | 374.6 | 454.8 | 17.6% | +35.5% | +0.36 | $823,205 |
| DREGG | 10.9 h | 365.9 | 384.3 | 4.8% | −9.8% | −1.29 | $10,756 |
| weave | 6.4 h | 184.7 | 204.5 | 9.7% | +9.0% | +0.33 | $61,445 |
| SOLVE | 29.3 h | 100.4 | 112.4 | 10.6% | −4.1% | −0.10 | $5,847 |

*A rail that has never fired has never been tested.* Log the values hourly from now; when a
cluster token does decay, check whether RAIL 3 fired before the final leg. If not, it is
decoration.

**What the rails do not cover.** All three are pool-level. None sees a social or
contract-level failure — deploy-key movement, team exit, migration — which is what actually
takes a "strong techproject coin" to zero. The operator's survival filter (12 for 12, zero
delistings) does that job and nothing here replaces it.

---

## 13. THINGS MEASURED HERE THAT WERE PREVIOUSLY ASSUMED

- **The PumpSwap LP fee is 0.200%**, inverted from the constant-product rule per swap, flat
  at p10 and p90 on DREGG/SOL and SOLVE/SOL (n = 81, 165). `RESULT_power_gate.md` §2.3 called
  inheriting this its weakest link. On weave/SOL and nosis/SOL the raw inversion is
  *antisymmetric in the trade side* (+9.1%/−9.3%, +4.6%/−4.4%), which no fee can be; a
  two-parameter reserve offset (curve reserve ≠ vault balance, −20.5%/−27.5% on weave,
  +2.0%/−2.5% on nosis) removes it and returns 0.20% there too. **Those two vaults hold
  20–27% of off-curve balance**, which biases any reserve-derived price *level* and cancels
  in returns.
- **The taker leg is 1.44%**, decoded in `RESULT_edge_creation.md` — *higher* than the 1.10%
  power_gate called an absurd upper bound. A re-centering swap is a taker action and pays it.
- **The band-model check.** Predicted pool TV `σ(τ)²/2f` = 13.62/day against **7.11/day
  realised** on weave/nosis — the model over-predicts fee income by **1.92×**, and every
  simulated figure in this study is haircut by exactly that, measured rather than chosen.
- **The self-consistent band timescale** `τ = (f/σ(τ))²` is **3.2 minutes** for weave/nosis
  and **106 minutes** for DREGG/SOLVE. That, not a convenient sampling interval, is the
  horizon at which fee income must be evaluated.
- **The flow decomposition.** Measured volume $9,517/day, band-model arbitrage $6,702/day,
  **residual uninformed flow $2,815/day = 30%**. `RESULT_power_gate.md` §2.5 got 64%
  single-hop by transaction composition. **The two disagree by 2×** and the fee-tier
  elasticity depends on which is right; neither is settled.

---

## 14. WHAT WOULD FALSIFY THIS, RANKED

1. **A multi-day bounce-free variance ratio materially below 1.** Nine days of tape. It
   decides the rebalance trigger (0 vs 0.3–0.6), flips the pair ranking's sign column, and is
   the single largest unmeasured term in the strategy.
2. **`η` measured over a week rather than 5.33 hours.** η = 0.667 here and 0.59–1.08 there,
   on windows of hours. If η settles above 1 the programme is viable at high duty cycle; if
   below, no policy saves it.
3. **The duty-cycle series.** `RESULT_power_gate.md` already asked for the DLMM active bin id
   per print. That single field turns `D` from a post-mortem number into a live control
   variable, and §2 says `D` is the one term that is a decision rather than a draw.
4. **Whether Jupiter routes this pair through us.** A daily quote-API query. If the answer
   ever becomes no, §6 says the revenue goes to zero in one step, and §10's cash plan with
   it.
5. **The taker/arbitrage split**, 30% here vs 64% there. Classify each DLMM swap by whether
   it moved the pool toward or away from the contemporaneous SOL-implied cross. The tape
   already contains everything needed.
6. **The band model's 1.92× over-prediction.** If the gap is the pumpswap-implied ratio
   carrying both legs' microstructure noise, a true-ratio series should close it. If not, the
   band model is wrong and the fee side of every derivation here needs redoing.

---

## 15. WHAT THIS CHANGES ELSEWHERE (stated, not edited — this study owns only its two files)

- **`RESULT_swing_cluster.md`, "seed the DREGG/SOLVE pool".** Reverse it. §7 ranks
  DREGG/SOLVE fifth of six and negative: it is the *quietest* pair in the cluster and income
  scales as σ². Its robust reversion is a real measurement pointed at the wrong quantity.
- **`RESULT_swing_cluster.md`, the 7.2–8.9 h half-lives.** Superseded by two independent
  bounce-free measurements (§3). They came from last-trade closes and carry bounce.
- **`RESULT_power_gate.md` §2.3's inherited 0.20% PumpSwap leg.** Now measured, and it splits
  into 0.20% LP-received and 1.44% taker-paid. Both numbers are needed and they are used for
  different things.
- **`RESULT_power_gate.md` §2.7's "in-range time fraction is the single largest unquantified
  term".** Correct, and now it has a formula: `D* = VR/η` (§2). It is not merely a term in a
  comparison — it is the control variable.
- **marketfabric's `il_vs_hold`.** Do not use it on a concentrated position. It understates
  by `4/w_eff` (3.4–12.2× on the live book) and has no range-exit branch at all.
