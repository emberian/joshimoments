# RESULT: the two gating numbers — injection power, and the DLMM concentration question

2026-08-13, 23:54 UTC. Script: `studies/power_gate.py` (`python studies/power_gate.py`, or
`--q1` / `--q2` / `--offline` / `--json`). Every number below is reproduced by that script
against live data; nothing here is carried over from a summary.

**Sources, and what each is trusted for.**

| source | window used | trusted for |
|---|---|---|
| `state/cluster_tape/swaps/*.jsonl` | 2026-08-12T21:25:00Z → 2026-08-13T23:53:47Z, 9,908 records | per-swap pre/post vault reserves — price paths, print rates, realized fee rates, residual noise. The only ground truth in the file |
| `dlmm.datapi.meteora.ag` | live at run time | the operator's open DLMM positions (bin ranges as prices, lifetime fees, value), pool configs |
| `api.dexscreener.com` | live at run time | pool TVL / 24h volume / 24h trade counts |
| `state/scalper/decisions.jsonl` | 2,079 decisions over 3.36 h, live shadow run | the policy's realized injection rate, sizes, and target pool depths |
| `shitcoims_scalper/policy.py` | read, not re-derived | the sizing law `B* = sqrt(priority·Y)`, `rho_max_bps = 200`, bankroll cap 0.5 SOL, priority 500,000 lamports |
| `studies/RESULT_circuit_model.md` §3.2 | quoted | the fee-band (dead-zone) widths, 186–342 bps |

The tape is accumulating while this runs, and DexScreener/Meteora are live, so **every table below
is pinned to the single run at 2026-08-13 23:54 UTC** and a re-run will not reproduce the last
digit. Per-pool windows differ and are stated with every number: nosis/SOL 2.97 h / 460 swaps,
weave/SOL 3.02 h / 123 swaps, DREGG/SOL 7.44 h / 57 swaps, SOLVE/SOL 26.09 h / 142 swaps. Two
re-runs 7 minutes apart moved the token-token turnover median by 3% and the weave/nosis realized
yield by 0.6pp. **Re-running should move digits and no verdicts. If it moves a verdict, that is a
finding and this document is wrong.**

---

# Q1 — THE POWER GATE FOR THE RANDOMIZED-INJECTION EXPERIMENT

## 1.1 The estimand, stated precisely

A constant-product pool's marginal price is an exact function of its reserves, so for a buy of
`B` SOL into a pool holding `Y` SOL,

```
    m(B, Y)  =  Δ log P  =  2 · ln(1 + B/Y)        exact, not an approximation
```

The Onsager/impact element is the coefficient in

```
    Δ log P_b(t → t+h)  =  L_ba · m_a(B, Y_a)  +  ε
```

where `a` is the injected pool and `b` the response pool.

- **Off-diagonal `L_ba`, a ≠ b.** This is the actual estimand of PROGRAM.md §8 — the element
  whose observational identification Capponi–Cont could not achieve because propagation and
  common flow are confounded. The null `L_ba = 0` is the interesting null.
- **Diagonal `L_aa(h)`.** Testing `L_aa ≠ 0` is vacuous: `m` is algebra and the displacement is
  guaranteed. The content is *persistence* — the null is `L_aa(h) = 1` (nothing relaxes) against
  the alternative that a fraction relaxes. Reported below as "detect a departure `dK` from full
  persistence".

**Test.** Two-sample mean difference between injected instants and matched non-injected instants,
80% power, α = 0.05 two-sided, `(z_{α/2} + z_β)² = 7.8489`. Control instants are free — any
non-injected decision point — so the treated arm carries the whole cost and the balanced-arm
figure is 2×. Randomization makes the difference causal; that is the whole point of the design.

**Two readings of the same experiment, and one is strictly better.** If the response is read at
`t+h` on the calendar, a pool that did not print contributes an exact zero, so the effect is
attenuated to `P_obs · L · m` while the variance carries the mixture — `n_calendar = n_event /
P_obs`. Reading the response at pool *b*'s **next print** (event time) removes the censoring at
the cost of a variable horizon. Both are tabulated; event time is the design to run.

## 1.2 What the scalper is actually injecting, read from its own propensity log

Before pricing the experiment, check the premise. From `state/scalper/decisions.jsonl`
(2,079 decisions over 3.36 h, live shadow run):

| | |
|---|---|
| enters | 197, of which **57 are ε-explored** |
| explored-entry rate | **408/day** |
| size (SOL) | min 0.000, p25 **0.0791**, median **0.1065**, p75 **0.1355**, max 0.500 |
| target pool depth | min 0.00, median **22.7 SOL**, max 1,965.7 SOL |
| distinct mints touched | 1,394 |

The size distribution confirms the brief's 0.07–0.25 SOL exactly, and the reason is visible:
`B* = sqrt(0.0005 × 22.7) = 0.1065 SOL`, the median, to four digits.

**But these land in fresh pump.fun mints at a median depth of 22.7 SOL — not in the cluster.**
They are not nodes of the circuit whose off-diagonals §8 wants, so at *any* n they identify
nothing about this cluster's Onsager matrix. Everything below prices the experiment as if the
injector were already pointed at the cluster pools, which is the most favourable possible
reading of §8's claim.

## 1.3 Injection size is not free, and this is the load-bearing constraint

`B* = sqrt(priority · Y)` with priority = 500,000 lamports, capped by `ρ ≤ 2%` of the SOL side
and by the 0.5 SOL bankroll cap. At the cluster's **measured** depths:

| pool | Y (SOL) | B\* | ρ=2% cap | binding | move at B\* | move at ρ cap |
|---|---|---|---|---|---|---|
| DREGG/SOL | 378.08 | 0.4348 | 7.562 | B\* | **23.0 bps** | 396.1 bps |
| nosis/SOL | 315.64 | 0.3973 | 6.313 | B\* | **25.2 bps** | 396.1 bps |
| weave/SOL | 179.05 | 0.2992 | 3.581 | B\* | **33.4 bps** | 396.1 bps |
| SOLVE/SOL | 98.03 | 0.2214 | 1.961 | B\* | **45.1 bps** | 396.1 bps |

B\* lands at 0.22–0.43 SOL, consistent with the 0.07–0.25 SOL range in the brief (that range
came from shallower pools; the cluster's SOL sides are 98–378 SOL, so B\* runs higher). The
bankroll cap never binds here and the ρ cap never binds — **B\* binds everywhere**, and it sits
**16× below** what the envelope already permits.

## 1.4 Residual noise, measured

sd of log price change over a calendar horizon, swept on a regular grid over each pool's window:

| pool | sd@30s | sd@60s | sd@300s | sd@900s | bootstrap 95% CI on sd@300s | n mult. at CI hi |
|---|---|---|---|---|---|---|
| nosis/SOL | 194.7 bps | 253.5 bps | **590.4 bps** | 1165.3 bps | [359.1, 762.3] | 1.67× |
| weave/SOL | 67.1 | 97.5 | **267.1** | 444.7 | [159.3, 351.3] | 1.73× |
| SOLVE/SOL | 49.2 | 63.6 | **142.1** | 248.1 | [55.4, 220.7] | 2.41× |
| DREGG/SOL | 23.4 | 33.2 | **74.6** | 134.0 | [30.4, 107.2] | 2.07× |

The MAD-based robust scale collapses to ~0 on three of four pools: the return distribution is a
**point mass at zero plus a heavy tail**, not a bell. The mean-difference test's variance is the
plain sd, so the plain sd is what is used — but note what the bootstrap says: σ itself is only
known to about ±35%, and `n` scales as `σ²`, so **every `n` below carries a 1.7–2.4× upward
multiplier at the CI's upper edge**. All n's are therefore order-of-magnitude statements, and
are labelled as such.

## 1.5 Overdispersion, handled rather than assumed

Fano factor of swap counts (variance/mean of bin counts; Fano = 1 ⟺ Poisson):

| pool | Fano@60s | Fano@300s | Fano@3600s (bins) | VR(60→300s) | VR(60→900s) |
|---|---|---|---|---|---|
| nosis/SOL | 5.07 | 6.41 | 0.82 (2) | 1.08 | 1.41 |
| SOLVE/SOL | 10.63 | 11.44 | **11.51 (26)** | 1.00 | 1.02 |
| weave/SOL | 3.51 | 3.96 | 10.32 (3) | 1.50 | 1.39 |
| DREGG/SOL | 1.91 | 2.83 | 8.50 (7) | 1.01 | 1.09 |

The **count** process is strongly overdispersed — SOLVE/SOL's 26-bin hourly Fano of 11.51 is the
only figure here with enough bins to mean much, and it is the same order as the 16.74 in the
brief. So the brief's warning is confirmed at the level it was made.

**But it does not transfer to the price process, and that is measurable.** A Poisson-assuming
calculation would build `σ_h` from the per-swap move and the rate as `σ_h² = λ·h·E[X²]` (compound
Poisson). Measured against that:

| pool | h | λ (/s) | rms per-swap move | σ Poisson-implied | σ measured | variance inflation |
|---|---|---|---|---|---|---|
| nosis/SOL | 300 s | 0.04298 | 213.6 bps | 766.9 bps | 590.4 bps | **0.59×** |
| weave/SOL | 300 s | 0.01132 | 162.3 | 299.1 | 267.1 | **0.80×** |
| SOLVE/SOL | 300 s | 0.00151 | 247.0 | 166.3 | 142.1 | **0.73×** |
| DREGG/SOL | 300 s | 0.00213 | 86.2 | 68.9 | 74.6 | **1.17×** |

**The variance inflation is 0.59–1.17×, not 17×.** Bursts of swaps in these pools are largely
two-sided — arbitrage round trips and router traversals that push and pull the same price — so
the price moves within a burst partially cancel and the sum's variance comes in *below* the
compound-Poisson prediction on three of four pools. A count-level Fano of 11–17 is real and is
the wrong instrument for this question.

Since `σ_h` is measured directly from prices, all of this is **already inside every `n` below**
and the Fano factor is **not** applied a second time. What *is* applied on top is the design
effect from serial dependence between injections, taken as the measured variance ratio
VR(60→300s) = 1.00–1.27.

*Falsification of this paragraph:* simulate the tape's own arrival process at Fano 11 with
one-sided (all-buy) marks and re-run the inflation table; if the inflation goes to ~Fano, the
cancellation story is right and the two-sidedness is doing the work. If it stays near 1, the
compound-Poisson baseline is misspecified and this row should be redone.

## 1.6 Response observability — the censoring §8 was worried about

P(pool prints at least once within h of a uniformly random instant), swept directly over the
window rather than modelled as `1 − e^{−λh}`:

| pool | h=30s | h=60s | h=300s | h=900s |
|---|---|---|---|---|
| nosis/SOL | 60.2% | 83.5% | 100.0% | 100.0% |
| weave/SOL | 20.5% | 34.6% | 90.4% | 100.0% |
| DREGG/SOL | 4.9% | 9.3% | 32.4% | 63.4% |
| SOLVE/SOL | 1.6% | 2.9% | **12.2%** | 30.4% |

§8's concern was real and is now a number: at a 5-minute horizon, **SOLVE/SOL's price is
unobserved 88% of the time** and DREGG/SOL's is unobserved 68% of the time. Reading the response
in event time rather than calendar time recovers exactly this factor (8.2× on SOLVE, 3.1× on
DREGG) and is why the design should not use fixed calendar horizons.

Note what this does *not* say. The brief's framing — "cluster pools print 3–46 times/day" — is
the **token-token DLMM** rate (DexScreener 24 h counts: DREGG/nosis 46, weave/nosis 45,
DREGG/Circuit 43, DREGG/CSR 16). The **token/SOL** pools where an injection would actually land
print 131–3,714 times/day on this tape. So print rate is a real constraint on the token-token
edges of the graph and a mild one on the token/SOL nodes; it is **not** what makes the experiment
fail. Sizing is.

## 1.7 Effect size, anchored on the tape rather than invented

Regression of realized `Δ log P(t → t+h)` on the swap's own exact mechanical displacement:

| pool | h | n | β | se | t | resid sd |
|---|---|---|---|---|---|---|
| nosis/SOL | 300 s | 449 | 0.586 | 0.140 | 4.19 | 632.7 bps |
| SOLVE/SOL | 300 s | 139 | 1.234 | 0.142 | 8.71 | 416.1 bps |
| weave/SOL | 300 s | 112 | 0.816 | 0.215 | 3.79 | 358.5 bps |
| DREGG/SOL | 300 s | 54 | 1.061 | 0.160 | 6.61 | 104.0 bps |

β = 0.59–1.23 at five minutes, every one of them several se above zero and none of them
distinguishable from 1: **the mechanical displacement does not measurably relax**. This is
the *confounded* estimator — a swap arrives because someone wanted to trade, and whatever made
them want to trade also moves the price — which is precisely the confound randomization removes.
It over-states the causal coefficient, so using it as an anchor makes every `n` a **floor**.

Cross-impact, same regression with the response read in a different pool, h = 300 s:

| src → dst | n | frac. response moved | β | 95% CI |
|---|---|---|---|---|
| nosis/SOL → DREGG/SOL | 410 | 34.6% | +0.0001 | [−0.019, +0.019] |
| weave/SOL → DREGG/SOL | 109 | 20.2% | +0.0037 | [−0.008, +0.016] |
| SOLVE/SOL → DREGG/SOL | 64 | 9.4% | +0.0021 | [−0.034, +0.038] |
| nosis/SOL → SOLVE/SOL | 350 | 25.4% | −0.0261 | [−0.099, +0.047] |
| nosis/SOL → weave/SOL | 443 | 90.5% | −0.0389 | [−0.143, +0.065] |
| weave/SOL → SOLVE/SOL | 89 | 19.1% | −0.0587 | [−0.174, +0.056] |
| SOLVE/SOL → nosis/SOL | 47 | 100% | −0.0211 | [−0.297, +0.255] |
| SOLVE/SOL → weave/SOL | 47 | 100% | −0.0145 | [−0.327, +0.298] |
| weave/SOL → nosis/SOL | 112 | 100% | +0.2136 | [−0.692, +1.119] |
| DREGG/SOL → SOLVE/SOL | 54 | 5.6% | −0.0051 | [−0.112, +0.101] |
| DREGG/SOL → weave/SOL | 10 | 100% | −0.2547 | [−1.790, +1.281] |
| DREGG/SOL → nosis/SOL | 10 | 100% | −2.3591 | [−6.712, +1.994] |

Every CI contains zero. The tightest — nosis→DREGG at n=410 — already bounds `|L| < 0.019`. **The
observational data cannot yet see any cross-impact, and where it is tightest it excludes anything
above ~2%.** `L = 0.10` is used as the headline target below because it is a value the data
cannot exclude on most pairs; if the truth is nearer the tightest bound, `n` scales as `1/L²` and
everything below multiplies by ~25.

## 1.8 The gate

`n_event = (z_{α/2} + z_β)² · σ_cond² / (L·m)² · DEFF`, with `σ_cond = σ / sqrt(P_obs)`,
`L = 0.10`, `h = 300 s`, DEFF from the measured variance ratio.

| regime | n (injections), across all 12 ordered pairs |
|---|---|
| **B\* — the scalper's own sizing** | **6,691 – 561,789** |
| **ρ = 2% cap — the envelope's maximum** | **87 – 1,892** |

Ratio ≈ 191×, and the arithmetic reason is exact: `n ∝ 1/B²` and the cap is ~16× B\*.

Own-pool persistence test (no censoring, `P_obs = 1` by construction):

| pool | regime | n to detect dK = 0.25 | dK = 0.50 |
|---|---|---|---|
| DREGG/SOL | B\* | 1,335 | 334 |
| DREGG/SOL | ρ=2% | 4 | 1 |
| SOLVE/SOL | B\* | 1,245 | 311 |
| SOLVE/SOL | ρ=2% | 16 | 4 |
| weave/SOL | B\* | 12,061 | 3,015 |
| weave/SOL | ρ=2% | 86 | 21 |
| nosis/SOL | B\* | 75,049 | 18,762 |
| nosis/SOL | ρ=2% | 303 | 76 |

## 1.9 n → days and dollars, at the measured print rate

Two constraints, both from measured quantities: injections capped at **10% of native swap count**
(otherwise the injector *is* the market and "other flow" is reacting to a pool we took over) and
injected notional capped at **10% of native SOL volume**. Friction per round trip is
`2·swap_fee + 2·priority/B + 2·B/Y` at the all-in PumpSwap 1.10%/leg used in the fee-band table.
SOL ≈ $76.18 at run time.

| inject → respond | regime | n | days (count cap) | days (volume cap) | friction | working capital |
|---|---|---|---|---|---|---|
| **nosis/SOL → DREGG/SOL** | **ρ=2%** | **87** | 0.2 | **1.2** | 34.1 SOL ($2,594) | 6.31 SOL |
| weave/SOL → DREGG/SOL | ρ=2% | 87 | 0.9 | 4.1 | 19.4 SOL ($1,474) | 3.58 SOL |
| nosis/SOL → weave/SOL | ρ=2% | 593 | 1.6 | 8.4 | 232.6 SOL ($17,713) | 6.31 SOL |
| nosis/SOL → SOLVE/SOL | ρ=2% | 825 | 2.2 | 11.7 | 323.6 SOL ($24,637) | 6.31 SOL |
| weave/SOL → nosis/SOL | ρ=2% | 1,892 | 19.3 | 90.2 | 422.0 SOL ($32,135) | 3.58 SOL |
| **nosis/SOL → DREGG/SOL** | **B\*** | **21,521** | 57.9 | 19.3 | 231.1 SOL ($17,599) | 0.40 SOL |
| weave/SOL → DREGG/SOL | B\* | 12,213 | 124.9 | 48.6 | 104.8 SOL ($7,981) | 0.30 SOL |
| DREGG/SOL → nosis/SOL | B\* | 561,789 | 30,535 | 16,966 | 6,497 SOL ($494,713) | 0.43 SOL |

## 1.10 VERDICT Q1

**The experiment as PROGRAM.md §8 describes it — identification from the scalper's own
ε-explored entries at B\* = 0.22–0.43 SOL — is INFEASIBLE, and it fails three ways.**

1. **Underpowered by ~250×.** 6,691–561,789 injections for `L = 0.10` at 80%/α .05. The best
   cell (nosis/SOL → DREGG/SOL) is 21,521 injections, ~58 days at the flow caps, ~$17,600 of
   pure friction; the worst is 561,789 injections and 84 years. `n ∝ 1/B²` and B\* sits 16×
   below the cap the envelope already permits, which is exactly the 250×.
   **Independent cross-check, from a completely different route:** at the scalper's own measured
   408 explored injections/day, that same 21,521 takes **53 days** even ignoring the flow caps.
   Two unrelated constraints, same order of magnitude.

2. **The effect is not there to find at that size — and this is the more interesting failure.**
   At B\* the price displacement is **23–45 bps against fee dead-zones of 186–342 bps**, i.e.
   7–24% of the narrowest band. A diode below its forward drop does not conduct. The circuit
   model's own prediction for arbitrage-mediated cross-impact at B\* is **exactly zero**, so more
   samples buy nothing. Running the experiment at B\* and reporting a null would be a null about
   the sizing, not about the market.

3. **Wrong pools.** The 408/day ε-explored entries land in fresh pump.fun mints at a median depth
   of 22.7 SOL. Those are not nodes of the cluster circuit and have no measurable edges to it, so
   at *any* n they identify nothing about this graph's off-diagonals. Pointing the injector at
   the cluster is a prerequisite, not a detail — and doing so changes the policy, because B\*
   on a 316 SOL pool is 0.40 SOL, not 0.107.

| injection | move | vs. `DREGG→SOL→DREGG` 186 bps | vs. `SOL→nosis→weave→SOL` 342 bps |
|---|---|---|---|
| B\* | 23–45 bps | 0.12–0.24× | 0.07–0.13× |
| ρ = 2% cap | 396.1 bps | **2.13×** | **1.16×** |

**The same experiment at the envelope's maximum permitted size IS feasible.** `ρ = 2%` gives
1.96–7.56 SOL per injection: **87–1,892 injections**, **1.2 days** for the best cell
(inject nosis/SOL, read DREGG/SOL), **34.1 SOL (~$2,594)** of friction, **6.3 SOL** of working
capital cycling per injection. That is a real experiment on a real budget.

**And the right design is not the one §8 imagines.** Because 396 bps straddles the 186–342 bps
bands, the efficient experiment is a **two-point size randomization across the band edge** — half
the injections below it, half above — and the prediction is a **kink in the response, not a
slope**. That is precisely the discriminating test `RESULT_circuit_model.md` §8.2 asked for and
could not run, and it is *cheaper* than the slope version because the contrast is the full
above-band propagation rather than a marginal coefficient.

**Falsifications this section owes.**
- If a purpose-built injector runs 87 injections at ρ=2% into nosis/SOL and DREGG/SOL's response
  CI still contains zero at ±0.10, the effect size anchor `L = 0.10` was too generous and the
  true `L` is below 0.02 (which the observational nosis→DREGG bound already suggests) — in which
  case the required n is ~25× larger and the experiment moves back to infeasible.
- If σ@300s on the response pool measured over a full week comes in above the bootstrap's upper
  edge (762 bps on nosis, 107 bps on DREGG), every n here is understated by more than the stated
  1.7–2.4× and the feasible band narrows.
- If the kink test at the band edge shows a *slope* rather than a kink, the diode model of the
  fee is wrong and §2.3 of the circuit model needs revisiting.

**What §8 should now say.** Not "we already own the identification." The correct sentence is:
*the identification requires a purpose-built injector pointed at the cluster pools at 9–17× the
scalper's sizing (B\* → ρ=2%); the scalper's ε-explored entries are propensity-logged and
counterfactual-ready, which is real and worth keeping, but they land in the wrong pools, are
~250× too small to power this experiment, and sit entirely inside the fee dead-zone where the
model predicts no effect at all.*

---

# Q2 — DOES DLMM CONCENTRATION BEAT THE 8.4× TURNOVER DEFICIT?

## 2.1 The operator's real bin widths — measured, not guessed

From `dlmm.datapi.meteora.ag/positions/{pool}/pnl` against wallet
`Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ`. `W = ln(P_max/P_min)`, concentration `= 4/W`:

| pair | bin_step | base fee | bins | P_min | P_max | ratio | W | **4/W** |
|---|---|---|---|---|---|---|---|---|
| weave/SOL | 100 (1%) | 2.0% | 69 | 1.85734e-06 | 3.65380e-06 | 1.967 | 0.6766 | **5.91×** |
| weave/nosis | 300 (3%) | 6.0% | 35 | 0.377026 | 1.03 | 2.732 | 1.0050 | **3.98×** |

**Measured 4/W is 3.98× and 5.91×** — below the 8.4× deficit, and below the 5–20× literature
range `RESULT_circuit_model.md` §2.2 carried. Taken at face value against the question as posed,
the answer is **no: concentration does not cover the deficit.**

**Range risk is not a tail event here, it is happening on the hour.** The weave/SOL position was
**out of range** when first read (active bin −633 against a position starting at −632), holding
100% weave and 0 SOL, having earned **exactly $0** over its life; ~50 minutes later it was back
in range and had earned $0.751 (1.76%/day on a 46-minute sample; the API's own
`feePerTvl24h` agreed at 1.74%). A DLMM out of range is a
zero-yield directional bet, and `4/W` buys nothing while the price is outside it — so the
concentration factor is an *upper* bound on the depth advantage, realized only for the fraction
of time the position is in range. That fraction is unmeasured and is the single largest
unquantified term in §2.6's comparison.

## 2.2 But the question as posed is malformed, and the tape says so

Fee yield per unit TVL is an identity:

```
    yield  =  turnover  ×  fee_rate  ×  (LP's share of the traded bins)
```

There is no slot in that identity for a `4/W` multiplier. **Concentration is the mechanism by
which a DLMM achieves high turnover — it is already inside the measured vol/TVL, not a factor to
apply on top of it.** `RESULT_circuit_model.md` §9.2 treats it as a multiplier
("yield-per-TVL flatters DLMM by exactly that factor"), and the table row makes the claim survive
"only if 4/W > 8.4". That is double counting.

The tape settles it arithmetically:

| weave/nosis, tape window 3.00 h, 28 priced swaps | |
|---|---|
| realized volume | $741.08 → **$5,929/day** |
| position TVL | $842.49 |
| turnover | **704%/day** |
| fee rate, measured from chain (§2.3) | **5.552%** |
| **predicted** yield = turnover × fee | **39.1%/day** |
| **realized** yield (position lifetime, 6.07 h) | **32.1%/day** |
| ratio realized/predicted | **0.82×** |

A missing 4/W = 3.98× would have shown up here as a factor of four. It does not. **The identity
closes without it.** (The 0.82× gap is the tape window being a busier 3.00 h than the position's
full 6.07 h life — the right direction and the right size.)

## 2.3 The fee tier — the number that actually closes the gap, measured from chain

Meteora DLMM with `collect_fee_mode 0` accrues fees inside the reserve vaults; a `claim_fee2`
instruction withdraws them. So between two consecutive claims,
`fee_rate = claimed_side / side_swapped_in`, read straight off vault deltas:

```
  weave/nosis, window [22:18:31Z → 23:05:25Z], 2,814 s, 8 swaps
     nosis  in = 329,976.94   claimed = 18,172.58   ->  5.507%
     weave  in = 666,341.10   claimed = 37,299.37   ->  5.598%
```

**5.51–5.60%, mean 5.552%.** Independently corroborated by the pool config
(`base_fee_pct = 6.0`, `protocol_fee_pct = 10.0` → LP keeps 5.4%) which this measurement was not
derived from. DREGG/nosis is `bin_step 200`, `base_fee_pct 5.0` (no claim window in the tape yet,
so unmeasured).

`RESULT_circuit_model.md` §9.1 stated the requirement exactly: *"For token-token LP to win on
gross fee income per unit TVL, its fee tier must exceed the token/SOL LP tier by 8.4× to 10.4×.
Against a PumpSwap LP leg of 0.20%, that requires a DLMM tier of 1.7% to 2.1%."*

**Measured: 5.55% against 0.20% — 27.8×.** The requirement is cleared with 2.7× to spare. This is
the checkable number that study asked for, and it is the answer — **not** 4/W.

*Caveat, stated because it is the weakest link:* the 0.20% PumpSwap LP leg is **inherited as an
assumption** from the circuit model and is not measured here. Sensitivity: at 0.25% the ratio is
12.2×; even at the absurd upper bound of 1.10% (the *all-in* PumpSwap take including protocol and
creator legs, which LPs do not receive) it is still 2.8×. The conclusion does not turn on it.

## 2.4 The turnover deficit itself is not stable at n=4

Re-measured live, same method as `RESULT_circuit_model.md` §9.1 (token-token = neither leg is
SOL, which is the classification that reproduces its n=4 set):

```
    token-token   n=4   median turnover    67.3%/day     (DREGG/nosis 159.1, weave/nosis 120.7,
                                                          DREGG/CSR 13.9, DREGG/Circuit 6.6)
    token/SOL     n=8   median turnover   206.7%/day     (0.9 - 1,057.6)
    deficit = 3.07x      (RESULT_circuit_model.md measured 8.4x, hours earlier)
```

The deficit moved from 8.4× to 3.1× in a few hours, driven almost entirely by weave/nosis's
24 h turnover rising from 45.2% to 120.7% as a pool created 6 hours ago accumulated volume. **A
median over four heavy-tailed pools, two of which are dust, is not a settled number** — the
circuit model said so itself ("Sampling. 24h volume on pools doing 22–46 trades/day is one draw
of a heavy-tailed variable") and this is that caveat cashing out. The 8.4× figure should be
carried as ~3–10×, and it does not matter, because 27.8× clears any value in that range.

## 2.5 The monopoly confound, quantified

The operator is ~100% of the weave/nosis LP side. The first thing to check is whether the
"volume" is the operator paying themselves — it is not:

```
  weave/nosis   28 swaps in the tape window,  16 distinct fee payers
                operator-as-swapper: 0  (0.0%)
                multi-hop routed through another pool: 10  (36%)
                  with 7nv2RtGXXVDE (nosis/SOL pumpswap)  7
                  with GA1nQL5RLBYU (weave/SOL pumpswap)  2
                  with C889ex3M6dDe (nosis/SOL meteora)   1
```

The operator appears in the tape **only** as `claim_fee2`, never as a swapper. The flow is
external, and 36% of it is multi-hop traversal — arbitrage and router paths crossing this pool
against the token/SOL pools. So this is monopoly *capture of real flow*, not a wash loop.

**What the monopoly actually changes, decomposed by flow type** — the answer is less than it
looks, and the decomposition is the honest way to say it:

- **Multi-hop / arbitrage traversal (36%).** An arb must consume every bin between the stale
  price and the band edge, so traversal volume is **proportional to depth**. A rival adding equal
  TVL roughly *doubles* that volume and splits it 50/50 — **yield per unit TVL is unchanged.**
  Monopoly buys nothing on this half.
- **Single-hop / taker (64%).** Size-inelastic; the same dollars split two ways — **yield per
  unit TVL halves.** This half is genuine monopoly capture.

Net: a rival at equal TVL and equal fee leaves the operator at **0.68×** of measured yield —
32.1%/day → ~21.8%/day. That is a 32% haircut, not an order of magnitude, and it still beats the
token/SOL alternative by ~10×. (n = 28 swaps: **THIN**, and the split is the least robust number
in this document.)

**The larger rent is the fee tier, not the LP share.** The substitute route weave→SOL→nosis costs
~2.2% all-in (two PumpSwap legs at ~1.10%), so a rival pool priced anywhere below that takes the
single-hop flow outright. The 5.55% tier is defensible only while no such pool exists.

*Offsetting structural argument, labelled **CRUDE** because it is a model and not a measurement:*
for pure arbitrage flow the LP's revenue rate is roughly **invariant to the fee tier** — crossings
per unit time scale as `σ²/w²`, volume per crossing as `w·depth`, and the band `w ≈ 2f`, so
`f × volume ~ σ²·depth/2`, independent of `f`. Under that model a rival at 2% takes the taker
flow but not most of the arbitrage revenue. **Falsification:** open a low-fee weave/nosis pool and
measure whether this pool's fee income falls by ~60% (model right) or by ~100% (model wrong).

## 2.6 Head to head, and what window would settle it

Same capital, measured turnover, LP leg assumed 0.20% on PumpSwap:

| venue | TVL | turnover | fee | yield |
|---|---|---|---|---|
| nosis/SOL (pumpswap) | $49,219 | 1057.6%/day | 0.20% assumed | 2.12%/day |
| nosis/SOL (meteora) | $12,707 | 1024.0%/day | 0.20% assumed | 2.05%/day |
| weave/SOL (pumpswap) | $28,477 | 450.5%/day | 0.20% assumed | 0.90%/day |
| DREGG/SOL (pumpswap) | $57,409 | 40.8%/day | 0.20% assumed | 0.08%/day |
| **weave/nosis (meteora, operator)** | **$842** | **120.7%/day (24h) / 704%/day (tape)** | **5.552% measured** | **32.1%/day realized** |

**Ratio ≈ 15.2× in favour of the token-token position** (32.1% vs 2.12%/day). At a 0.25% PumpSwap
LP leg it is 12.1×; at the absurd 1.10% all-in bound it is 2.8×. The sign does not flip anywhere
in that range.

**THIN SAMPLE, and here is the window that would settle it.** The weave/nosis position is
**6.07 hours old**; the earlier meter's ~20.1%/day was a 3-hour read and this is a 6-hour read of
the same position (now 32.1%/day — the number moved ~60% in three hours, which is the point). The
weave/SOL position is a **different, 0.76-hour-old** position that was out of range and earning
zero minutes before it was in range and earning 1.76%/day, so the earlier ~9.5%/day figure for
weave/SOL describes neither state. From the measured trade-size distribution on weave/nosis
(n = 28 priced swaps, mean $26.47, CV = 1.33, λ ≈ 224/day on the tape window):

| count overdispersion assumed | days for a ±20% CI on the daily yield |
|---|---|
| Fano = 1 (Poisson) | **1.2 days** |
| Fano = 16.74 (the brief's figure) | **8.3 days** |

DexScreener's 24 h count for the same pool is 47/day, well below the tape window's 224/day, so
the conservative reading is the longer implied window: **call it ~9 days at the observed rate,
and do not quote a settled yield before then.** Nothing shorter than a week is evidence; the
three numbers we now have for this one position (20.1%, 32.1%, API's 36.7%) span 1.8×, which is
what a 6-hour sample of a heavy-tailed process looks like.

## 2.7 VERDICT Q2

**The token-token LP edge is REAL — 15.2× the best token/SOL alternative on realized fee yield
per unit TVL (32.1%/day vs 2.12%/day) — but it is a FEE-TIER rent, not a concentration edge and
not a throughput edge, and it is measured on a 6-hour sample.**

Component by component:

| claim | status |
|---|---|
| `RESULT_swing_cluster.md`: token-token pools are plausibly the best LP venue | **Upheld on yield, for the wrong reason.** Its own reasoning (high turnover) is still falsified |
| `RESULT_circuit_model.md`: token-token turnover is 8.4× worse | **Confirmed in sign, unstable in size** — re-measured at 3.07× hours later; carry as 3–10× |
| `RESULT_circuit_model.md`: survives only if `4/W > 8.4` | **Measured 4/W = 3.98× and 5.91×, so no — but the test itself is malformed.** 4/W is already inside measured turnover; the tape's yield identity closes to 0.82× without it, where a missing 4× would be visible |
| `RESULT_circuit_model.md`: needs a DLMM tier of 1.7–2.1% | **Measured 5.55% from chain vault deltas. Requirement cleared 2.7× over** |
| The meter's ~9.5%/day weave/SOL and ~20.1%/day weave/nosis | **Superseded.** weave/SOL is a different, newer position that flipped out of range (earning **0**) and back in (1.76%/day) inside one hour; weave/nosis re-reads at 32.1%/day on a 6.07 h sample. Both remain THIN |
| "Monopoly capture, not a scalable market rate" | **Partly true and now quantified.** Not a wash loop (operator is 0% of swaps, 16 distinct payers over 28 swaps). A rival at equal TVL and fee leaves 0.68× — a 32% haircut, not an order of magnitude. The real rent is the 5.55% tier against a ~2.2% substitute route |

**Where it inverts** — four conditions, all checkable:

1. **A rival opens a weave/nosis pool below ~2.2%.** The single-hop flow (64% of swaps) leaves
   immediately. Under the crude arbitrage model above, the multi-hop half largely stays; that is
   the falsifiable half of the claim.
2. **The position goes out of range.** Already live: the weave/SOL position was measured out of
   range earning exactly zero and back in range earning 1.76%/day inside the same hour. This is
   not a tail risk, it is the modal state transition of a concentrated position, and at `4/W` the
   concentration amplifies it. The **in-range time fraction** is unmeasured and is the single
   largest unquantified term in §2.6's comparison — measuring it needs only the active-bin series
   the cluster tape could already record.
3. **The ratio trends rather than oscillates.** Impermanent loss stops being temporary, and a
   concentrated position amplifies IL by the same `4/W`. `RESULT_swing_cluster.md`'s reversion
   evidence for weave/nosis is ρ̂ = 0.925 debiased at n = 83 — reverting but noisy, and its own
   "re-measure at n ≥ 300" is still outstanding.
4. **Relative volatility collapses.** Arbitrage traversal is driven by `σ²`, so a quiet week
   zeroes the 36% of income that comes from multi-hop flow.

**Recommended next measurement, cheap and decisive:** keep the cluster tape running on
weave/nosis and DREGG/nosis for **9 days**, and recompute §2.2's identity and §2.6's head-to-head
weekly. The tape already records every claim event and every vault delta, so the fee-rate and
turnover measurements are free — the only missing ingredient is calendar time. Add one field to
the recorder while you are there: the DLMM **active bin id** per print, which turns the in-range
fraction from an unquantified term into a measured one at zero marginal cost.

---

## What this changes in PROGRAM.md

Neither edit is made here (this study owns only its own two files); both are stated so the next
session can make them deliberately.

- **§8, "Identification we already own — but the experiment is NOT ready to run."** The power gate
  is now computed and the section's premise is wrong in a specific way: the blocker is not print
  rate, it is **injection size**. The scalper's ε-explored entries are 250× too small and sit
  inside the fee dead-zone. Replace "computing the gate first is mandatory" (done) with the
  design that survives it: a two-point size randomization at ρ = 2%, straddling the fee band,
  87–1,892 injections, ~1.2 days, ~$2,594 — plus the prerequisite of pointing the injector at
  the cluster pools at all, which it currently is not.
- **§8 and `RESULT_circuit_model.md` §9.2 / summary row 8.** The `4/W > 8.4` test is malformed —
  concentration is already inside measured turnover. Replace it with the fee-tier test the same
  study also stated (needs 1.7–2.1%, measured 5.55%), which is the one that decides the question.
- **`RESULT_swing_cluster.md`'s "Next" item 2** ("make the fee harvest a number") is done twice
  over: from the API (32.1%/day, 6.07 h) and independently from chain vault deltas (5.552% fee
  rate × 704%/day turnover = 39.1%/day predicted). Item 1 (re-measure weave/nosis at n ≥ 300)
  remains the binding open question for inversion condition 3.
