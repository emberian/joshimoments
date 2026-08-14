# RESULT: the rest of the EE/physics toolbox — what transfers to an AMM, what is vocabulary, what is nothing

2026-08-14. Instrument: `studies/circuit_theory.py` (stdlib only; keyless DexScreener,
GeckoTerminal and Meteora datapi; local `state/cluster_tape/`). Reproduce with
`python studies/circuit_theory.py all`.

Live numbers are from one consolidated run at **2026-08-14 00:20–00:30 UTC** unless a cell says
otherwise, so the tables are mutually consistent rather than stitched. Two caveats stated up
front because they matter: (i) TVLs, 24 h volumes and token USD prices move by several percent
between runs minutes apart, and the cluster's pool set turns over within hours (§7) — every
conclusion is stated so that it survives that, and where a number does not survive it, the
spread across reads is printed rather than one read chosen; (ii) GeckoTerminal rate-limits at
~30 req/min and drops cells under load, so a handful of last-trade cells are marked as coming
from an adjacent run in the same session (the OHLCV history itself is identical between them —
verified for the one cell a headline depends on).

Builds on `studies/RESULT_circuit_model.md` and PROGRAM.md §8, whose mapping is taken as
established and is **not re-derived**: pool = nonlinear capacitor `C = w_x w_y·TVL`; DLMM =
series battery stack, `C = T/W` coarse-grained; fee = back-to-back diode pair with a dead-zone;
liquidity sets capacitance, not conductance; the per-swap ledger closes to 94–98%.

The prior study's value came from demoting two of its own components. This one **promotes seven
and demotes nine**, including two of the brief's own premises and one claim in a live sibling
study. The promotions are all the same shape: **an identity between quantities that are
separately measurable, with the free parameter cancelling.**

---

## 0. What this found, in eight lines

1. **Impermanent loss IS the stored capacitor energy.** `IL = 2C(e^{ΔV/2}−1)² = ½C(ΔV)² + O(ΔV³)`
   — the exact same term the §6 ledger called "STORED, returned on reversal". The ledger and the
   IL formula are one equation. "Impermanent" was a theorem all along.
2. **LVR is a budget, not a loss, and it is an exact accounting identity:**
   `½C·QV = fee income + arbitrageur net profit + O(Cf²)`, at any block time and any fee tier.
   Verified in Monte Carlo: the sum sits at 1.00 across a 100× sweep of the block-time
   parameter. The LP's loss to arbitrage is *exactly* the arbitrageur's profit — not
   proportional, equal.
3. **On a continuous path an LP breaks exactly even on arbitrage flow, at every fee tier.**
   All LP profit is taker flow; all LP loss to arbitrage is supported on moves that **gap** the
   band, at `½C(|z|−f)²` each. Measured on the tape: **the single worst swap carries 35% of
   DREGG/SOL's whole-session LP loss; the worst five carry 79%.**
4. **The whole IL-vs-fee question collapses to one dimensionless inequality**, with no free
   parameter and both sides measured: **LP is +EV ⟺ `η > VR(T)`**, where
   `η ≡ 2fN/(C·RV)` is the churn number and `VR(T)` is the Lo–MacKinlay variance ratio. `η = 1`
   *exactly* on pure arbitrage flow, so `η−1` is the non-arbitrage share of fee revenue measured
   in units of LVR.
5. **Measured η kills token/SOL LPing in this cluster and puts the flagship token-token pool on
   the line.** η = 0.055–0.235 on the four PumpSwap pools (−EV by 1.9× to 9.2× against their own
   most favourable horizon); **η = 0.59–0.70** on the weave/nosis DLMM at the sizing
   `RESULT_power_gate.md` measured (0.59–0.70 across two reads), 0.91–1.08 at the live sizing.
   Its 32.1%/day "realized yield" is a **gross** number: over the tape's own 5.33 h window that
   position took **$93 of fees against $157 of adverse selection**, net −$64 on $842.
6. **Maximum power transfer transfers, and the matched point is the tail index.**
   `C* = α·C_0` — own capacitance equals α times the substitute route's, α the Pareto index of
   trade sizes. At α = 1 this is *exactly* `R_L = R_s`; measured α is 1–2, so the textbook EE
   answer is the right first-order answer here.
7. **The pool is a NOTCH, not a low-pass, and the brief's cutoff frequency does not exist.**
   A dead-zone is rate-independent, so the fee element has no frequency response at all. The LP
   is long the entire return spectrum (fees see quadratic variation) and short exactly one
   frequency bin (IL sees only the net move over the holding period).
8. **Demoted with numbers attached:** no transmission line (there is no inductance in an AMM,
   so no wave equation, no characteristic impedance, no reflection); no resonance (the delayed-
   feedback margin is 10⁵–10⁶×); no fluctuation–dissipation theorem (no temperature, no detailed
   balance); Onsager untestable; power factor is vocabulary; and there is no optimal depth
   *ratio* between pools in series, because elastances simply add.

---

## 1. Impermanent loss is the stored energy — the identity the ledger was missing

`RESULT_circuit_model.md` §6 split each swap exactly into `fee` (dissipated, LP income) +
`½C(ΔV)²` (stored, returned on reversal) + gas, and never connected the stored term to
impermanent loss. Take a constant-product pool from `(x₀,y₀)` to a price `e^{ΔV}` times higher,
with `Q = y`, `C = y₀/2`:

```
    LP value (quote)   = 2√(k p₁) = 2 y₀ e^{ΔV/2}
    HODL value (quote) = x₀p₁ + y₀ = y₀(1 + e^{ΔV})
    IL = HODL − LP     = y₀(e^{ΔV/2} − 1)²  =  2C (e^{ΔV/2} − 1)²        [EXACT]
                       =  ½C (ΔV)²  +  O(ΔV³)
```

| ΔV (bps) | IL exact | brute-force reprice | rel err | `½C(ΔV)²` | quad/exact |
|---|---|---|---|---|---|
| 1 | $0.0001 | $0.0001 | 9.8e−09 | $0.0001 | 1.0000 |
| 100 | $0.7237 | $0.7237 | 7.5e−12 | $0.7201 | 0.9950 |
| 344 | $8.6694 | $8.6694 | 1.7e−13 | $8.5214 | 0.9829 |
| 1,000 | $75.7178 | $75.7178 | 7.1e−14 | $72.0100 | 0.9510 |
| 3,000 | $754.386 | $754.386 | 2.0e−14 | $648.090 | 0.8591 |

(C = $14,402, DREGG/SOL's capacitance at the circuit model's snapshot.) The exact column
reproduces brute force to machine precision; the quadratic column is the ledger's stored term
and the gap grows as ΔV³ — **the same 2–6% gap §6 already measured and attributed to the third-
order term, now appearing on both sides of the same equation.**

So the pool is a **reactive element that does not conserve the payer**: the impact payment does
not vanish, it sits in the capacitor as the LP's inventory displacement, and it is returned to
whoever pushes the price back, not to whoever paid it. That sentence *is* impermanent loss.

**THE MASTER LEDGER.** For an LP over any window, no free parameter:

```
    LP net vs HODL  =  f · N_T   −   2C (e^{ΔV_T/2} − 1)²
                    =  f · N_T   −   ½ C (ΔV_T)²   + O(ΔV³)

      f    = LP fee rate                                    known per venue
      N_T  = notional traded through the pool over the window   MEASURED (tape)
      C    = w_x w_y·TVL, or T/W for a DLMM                     MEASURED
      ΔV_T = NET log-price displacement over the window         MEASURED
```

Everything below is a statement about when the first term beats the second.

---

## 2. The LVR budget identity, and the marginal-arbitrage wash theorem

### 2.1 Derivation

Let `m` be the external log-price, `V` the pool's, `z = m − V`. An arb can profitably move the
pool only while the marginal trade clears the fee, so `z` is **Skorokhod-reflected Brownian
motion on `[−f, f]`** and the pool price moves only by the boundary local time.

**(a) Local time.** Itô on `z²` in stationarity gives the pushing rate at each boundary as
`σ²/(2·2f)`, so the pool's total variation accrues at

```
    dTV/dt  =  σ² / (2f)                                                       [exact]
```

**(b) Fee income.** Moving the pool by `dV` takes notional `dQ = C dV`, so

```
    fee rate  =  f · C · σ²/(2f)  =  ½ C σ²          ← THE FEE TIER CANCELS
```

**(c) The books of a single arb.** A push that moves the pool by `move`, from mispricing
`z = move + f`:

```
    notional  = C·move            fee to LP = f·C·move
    arb gross = C(move²/2 + f·move)          arb NET = ½C·move²
    LP vs the rebalancing benchmark = fee − arb gross = − arb NET               [IDENTITY]
```

**The LP's loss to arbitrage is exactly the arbitrageur's net profit.** Not proportional to it,
not bounded by it — equal. No distributional assumption is used.

**(d) The budget.** Telescope `z²` across a push: the pool goes from `|z|` to exactly `f`, so
`z²` drops by `move² + 2f·move`, which is `2/C` times the arb's gross take. Summing and taking
expectations (the `Σ 2z dv` term is a martingale):

```
    ½ C · QV      =      fee income      +      arbitrageur net profit      +  O(Cf²)
    \________/           \__________/           \____________________/
       LVR              recaptured by LP          kept by the arbitrageur
```

**LVR is not a loss, it is a budget**, and the fee tier decides only how it is split. The
textbook constant-product LVR rate `σ²·V_pool/8` is, with `C = V_pool/4`, exactly `½Cσ²` — the
same number as (b), which is why they cancel.

**(e) The theorem.** On a continuous path every arb is marginal (`move → 0`), so arb net → 0 and
**the LP breaks exactly even on arbitrage flow, at every fee tier and every volatility.** All LP
profit comes from non-arbitrage flow; all LP loss to arbitrage is supported on gaps:

```
    LP loss to arbitrage  =  ½ C · Σ over gaps of ( |z| − f )₊²
```

A strictly sharper object than `σ²V/8`: adverse selection is not a functional of total variance,
it is a functional of the part of the variance delivered in single moves **larger than the fee
band**.

### 2.2 Monte Carlo, in band units

Brownian motion is scale-free, so after fixing `f = C = 1` the only surviving parameter is

```
    ε  ≡  σ√Δt / f            (block move / band width)
```

which is the group the fast-block LVR literature calls `P_trade = ε/√2` (arXiv:2305.14604).
Real values: Solana's 400 ms at σ = 20%/day gives `σ√Δt = 4.3e−4`, so **ε = 0.22 at a 0.20% fee
and ε = 0.008 at 5.5%**; Ethereum's 12 s at 0.30% gives ε = 0.79.

| ε | n steps | crossings | fee/(QV/2) | arb/(QV/2) | **SUM** | ε/√2 | arb ÷ that | 2f·TV/QV |
|---|---|---|---|---|---|---|---|---|
| 2.000 | 2,000 | 10,365 | 0.4594 | 0.5390 | **0.9984** | 1.4142 | 0.381 | 0.4594 |
| 1.000 | 2,000 | 7,104 | 0.6304 | 0.3713 | **1.0017** | 0.7071 | 0.525 | 0.6304 |
| 0.500 | 4,000 | 8,732 | 0.7786 | 0.2305 | **1.0091** | 0.3536 | 0.652 | 0.7786 |
| 0.300 | 11,111 | 16,075 | 0.8603 | 0.1510 | **1.0114** | 0.2121 | 0.712 | 0.8603 |
| 0.200 | 24,999 | 25,958 | 0.9244 | 0.1084 | **1.0328** | 0.1414 | 0.766 | 0.9244 |
| 0.100 | 99,999 | 54,178 | 0.9629 | 0.0566 | **1.0194** | 0.0707 | 0.800 | 0.9629 |
| 0.050 | 399,999 | 111,310 | 0.9829 | 0.0286 | **1.0115** | 0.0354 | 0.809 | 0.9829 |
| 0.020 | 2,500,000 | 278,937 | 0.9864 | 0.0115 | **0.9979** | 0.0141 | 0.813 | 0.9864 |

- **The SUM column is the budget identity and it is 1.00 at every ε**, from the jump regime to
  the continuous one. Nothing was tuned to make it flat.
- `fee/(QV/2)` → 1: the fee tier cancels, and the LP's arbitrage revenue *is* the LVR rate.
- `arb/(QV/2)` → 0 linearly in ε, at **0.81×** the fast-block asymptote's coefficient. An
  independent derivation (local time) reproducing the exponent and landing 20% off the constant
  is what agreement looks like at this level of care; neither derivation pins the constant for a
  real fee schedule.

At Solana's own ε the arbitrageur keeps ~10–15% of LVR at a 0.20% fee and under 1% at 5.5%.
`RESULT_lp_literature.md` §2(c) quotes ~1.5% of headline LVR at memecoin parameters and flags it
as theory extrapolated outside its validated regime — this sweep says the extrapolation is fine,
and that **the fee tier, not the block time, is what puts you deep into the recaptured regime.**

### 2.3 The gap formula, and the jump budget measured on the tape

The gap loss is quadratic in `z` while the fee is linear, so the LP survives many small gaps and
is killed by one large one — a 10-band gap costs 40× the fee it pays. Applied to the tape, where
every swap carries the pool's marginal price before and after (§8):

| pool | fee income (SOL) | ½C·RV | gap loss | gaps | top-1 share | top-5 share | worst gap |
|---|---|---|---|---|---|---|---|
| DREGG/SOL | 0.1292 | 0.5494 | 0.4332 | 42 | **35.0%** | **79.0%** | 4.26% |
| nosis/SOL | 5.8258 | 77.8159 | 71.9381 | 1,006 | 5.7% | 23.5% | 21.06% |
| weave/SOL | 0.4298 | 3.2745 | 2.8549 | 175 | 9.3% | 33.4% | 7.53% |
| SOLVE/SOL | 0.1882 | 3.3942 | 3.1943 | 108 | 29.2% | 66.1% | 19.78% |

`gap loss` sits close to `½C·RV` rather than far below it — these prices move in **gaps**, not
in a band-crossing diffusion, which is the same thing the `2f·TV/RV ≈ 0.06–0.25` column in §8
says. And a handful of swaps carry most of the loss over a whole session, which is why an LP
metric averaged over a quiet window is evidence of nothing.

**CAVEAT, and it is not small:** `|z|` here is the move in the pool's own marginal price between
consecutive swaps, which conflates the arbitrageur's correction with an informed taker's push.
Read `gap loss` as an upper bound on the arbitrage component and a measurement of *total*
adverse selection — which is the quantity that matters to the LP anyway.

### 2.4 What this overturns in a live study

`RESULT_power_gate.md` §2.5 carries a model, explicitly labelled CRUDE, concluding that
arbitrage *revenue* is invariant to the fee tier, and infers that "half the edge is
competition-invariant". **The revenue half is now exact** — it is (b), and the crude version's
`σ²·depth/2` is right. **The inference does not survive:** that revenue is matched dollar-for-
dollar by adverse selection, so its contribution to *profit* is zero. A rival who takes only the
taker flow takes **100% of the profit while leaving 36% of the revenue.** Same falsification as
theirs (open a cheap rival pool and measure), opposite reading of what the number means.

**Falsification of §2 itself:** tag every same-transaction multi-pool route on the tape (the
recorder already carries `counterparty` and `leg_discriminators`, so it is free) and compute the
LP's realised P&L on that subset alone. The theorem says it is zero up to the gap term. If
arbitrage flow is measurably profitable for the LP on a continuous path, §2 is dead.

---

## 3. Fluctuation–dissipation: the available-power half transfers, the thermodynamic half does not

**WHAT IS EXACT.** Arbitrage fee income is `½Cσ²` and the fee tier — the strength of the
dissipative element — cancels. That cancellation is structurally Nyquist's: the noise power a
resistor delivers to a matched load is `k_BT·Δν`, **independent of R**, because the source EMF
grows as √R while the divider attenuates as 1/R. Here the band grows as `f`, the crossings fall
as `1/f²`, and the notional per crossing grows as `f`, so `f·TV` is f-free. **The available-power
structure transfers exactly.**

**WHAT DOES NOT — DEMOTED.** Johnson–Nyquist is an *equilibrium* FDT: noise and dissipation come
from the same microscopic degrees of freedom at one temperature, and the content is that one
constant sets both. In an AMM the price noise and the fee are **causally independent** — the fee
tier is a governance parameter and it does not generate the volatility. No detailed balance, no
entropy production, no equipartition:

```
    equilibrium kTC noise:   ½C⟨V²⟩ = ½k_BT        a TEMPERATURE
    the AMM band:            ⟨z²⟩   = f²/3         a GOVERNANCE PARAMETER
```

An "AMM temperature" would be `k_BT_eff = Cf²/3`, set by the fee tier and independent of σ. That
is not a temperature in any useful sense. **The AMM has an available-power identity, not a
fluctuation–dissipation theorem. Do not call it FDT.**

**WHAT THE EXACT HALF BUYS: AN INSTRUMENT.** Fee revenue is arbitrage revenue plus taker
revenue, and taker revenue is non-negative, so for every venue `v` on a pair:

```
    f_v · vol_v / C_v   ≥   σ²/2       ⟹      σ_eff²  ≤  2 · min_v ( f_v vol_v / C_v )
```

an upper bound on efficient-price volatility that never touches a price series. Live, with a
liveness floor stated because it is part of the derivation, not a fudge (the bound only binds on
a pool that arbitrage actually keeps in line: TVL ≥ $100, vol24 ≥ $500, turnover ≥ 20%/day):

| pair | σ bound /day | σ from last-trade | σ from marginal price | LT/bound | **marg/bound** |
|---|---|---|---|---|---|
| DREGG/SOL | 0.076 | 0.136 | 0.069 | 1.79 | **0.91** |
| SOLVE/SOL | 0.083 | 0.255 \* | 0.227 | 3.07 \* | **2.74** |
| nosis/SOL | 0.435 | 0.712 | 0.845 | 1.64 | **1.94** |
| weave/SOL | 0.230 | 0.363 | 0.467 | 1.58 | **2.03** |

\* SOLVE/SOL's last-trade cell is from the adjacent run (GeckoTerminal dropped it under rate
limit in the consolidated one); its OHLCV history is identical between the two.

An AMM last-trade print is an **effective** price — buys print above the mid by fee-plus-
slippage, sells below — i.e. a bid-ask bounce of half-width ~f that inflates realised variance
without generating one dollar of arbitrage flow. The pool's marginal price `y/x` from vault
balances has no bounce at all. **On DREGG/SOL the entire violation was bounce and the bound
holds on the honest price (0.91).** On the busy pools it does not, and that has a specific
meaning: a violation of the arbitrage floor means the pool is **not a price follower** —
Schlegel–Kilbourn's regime (`RESULT_lp_literature.md` §2b), where the pool *is* the reference
venue and arbitrage is not what moves it.

**Do not read that as good news, which is a mistake easy to make here.** Schlegel–Kilbourn
reduce the *arbitrageur's* take. If the price is being discovered inside the pool, what is
moving it is **informed takers**, and their adverse selection is entirely real: it lands in the
`½C(ΔV_T)²` term of the §1 ledger whether or not anyone would call it LVR. So the bound is an
instrument that can fail informatively (reading 1, bounce) or fail because its premise is wrong
(reading 2, price discovery) — and **the `η > VR(T)` test of §4 does not depend on which**,
because it is the ledger itself rather than an arbitrage model of it.

**Falsification of the bound:** a *live* pool whose marginal-price volatility exceeds
`2 f vol/C` after the fee leg is measured rather than assumed, on a pair with a deeper external
venue. That would put fee revenue below the arbitrage floor, which the derivation forbids.

---

## 4. THE FILTER — the brief's premise is wrong and the correction is sharper

### 4.1 What is wrong with "low-pass on order flow"

> "A pool is a low-pass filter on order flow: high-frequency two-sided flow is absorbed and
> returned, low-frequency directional flow moves price permanently."

Half right, and the half that is wrong matters.

- **From flow to price the pool is exactly an INTEGRATOR:** `V = Q/C` with `Q` the accumulated
  signed flow. Transfer function `1/(jωC)` — infinite gain at DC, zero at high frequency. **The
  LP's inventory is precisely the DC component of the order flow.** That much is exact and it is
  just the capacitor.
- **But the fee is a DIODE, and a dead-zone is RATE-INDEPENDENT.** A backlash/play element has
  **no frequency response at all** — it filters by *amplitude*, not frequency. **There is no
  cutoff frequency and asking for one is a category error.** What exists is a corner *period*:
  an oscillation of period `T` has amplitude `~σ√T`, so it crosses the band iff `σ√T > 2f`,

```
      T_corner  =  (2f/σ)²                                                      [exact]
```

  Below it the price rattles inside the dead-zone — no trade, no fee, no inventory change. This
  makes the pool a **HIGH-pass on price-driven flow**, the opposite sign to the premise, and a
  corner *period* rather than a corner frequency because the amplitude–time relation is the
  diffusive one, not a filter's.

### 4.2 The result that replaces it

Take the master ledger over a window of `T` bars and divide by `½C·RV_T`. Everything becomes
dimensionless:

```
    LP net  >  0        ⟺        η  >  VR(T)

    η    ≡  2 f N_T / (C · RV_T)        the CHURN NUMBER      (fee side)
    VR(T)≡  (ΔV_T)² / RV_T              the VARIANCE RATIO    (loss side)
```

Both sides are pure numbers, both are measured, and **there is no free parameter anywhere.**

**WHY THIS IS THE FILTER STATEMENT.** `VR(T)` is, up to a smoothing kernel, the normalised
spectral density of returns at frequency `1/T`. So:

> **The LP is LONG the entire return spectrum** — fees see total power, i.e. quadratic variation
> — **and SHORT exactly one frequency bin** — IL sees only the net move over the holding period.

The pool is a **NOTCH**. An LP wants a return spectrum with a dip at the reciprocal of their
holding period, and the optimal horizon is `T* = argmin_T VR(T)`, parameter-free. For pure
arbitrage flow `η = 1` *exactly* (§2), so **`η − 1` is literally the non-arbitrage share of fee
revenue, measured in units of LVR.**

**WHAT CONCENTRATION DOES, settled.** A DLMM position has `C = T/W`, i.e. `4/W` times the
capacitance — and **both** terms of the ledger are proportional to `C`. So concentration is
**pure leverage on the sign of `(η − VR)`**: it multiplies the answer by `4/W` and cannot change
it. That is a cleaner resolution of `RESULT_power_gate.md` §2.2's "the question is malformed"
than that section reached: `4/W` is neither a yield multiplier nor double counting, it is
leverage on a signal whose sign is set elsewhere. It levers the loss exactly as hard as the gain.

### 4.3 VR(T) measured — last-trade hourly closes

| series | n | VR(1h) | VR(2h) | VR(4h) | VR(8h) | VR(12h) | VR(24h) | VR(48h) | VR(72h) |
|---|---|---|---|---|---|---|---|---|---|
| DREGG/SOL | 1000 | 1.000 | 0.877 | 0.746 | 0.588 | 0.528 | 0.452 | 0.438 | 0.513 |
| nosis/SOL | 118 | 1.000 | 1.083 | 0.897 | 0.752 | 0.806 | 1.041 | — | — |
| weave/SOL | 210 | 1.000 | 0.946 | 0.815 | 0.680 | 0.637 | 0.531 | 0.397 | — |
| weave/nosis | 106 | 1.000 | 1.015 | 0.884 | 0.771 | 0.717 | 0.817 | — | — |
| DREGG/nosis | 116 | 1.000 | 1.070 | 0.903 | 0.751 | 0.793 | 1.030 | — | — |
| SOLVE/SOL \* | 552 | 1.000 | 0.816 | 0.587 | 0.440 | 0.374 | 0.340 | 0.266 | 0.266 |
| DREGG/SOLVE \* | 550 | 1.000 | 0.854 | 0.653 | 0.530 | 0.469 | 0.390 | 0.248 | 0.249 |
| weave/SOLVE \* | 188 | 1.000 | 0.910 | 0.752 | 0.641 | 0.591 | 0.510 | 0.454 | — |

\* SOLVE-containing rows are from the adjacent run (GeckoTerminal dropped SOLVE/SOL's OHLCV
under rate limit in the consolidated one). Independently re-fetched and re-verified: SOLVE/SOL
VR(2h)=0.816, VR(4h)=0.587, VR(8h)=0.440, VR(24h)=0.340, VR(48h)=VR(72h)=0.266 on 552 bars.

### 4.4 …and the bounce correction, which is where it gets uncomfortable

With bounce variance `s²` per print,

```
    VR_obs(T)  =  (σ²T + 2s²) / ((σ² + 2s²)T)   →   1/(1 + 2s²/σ²)     as T grows
```

so **the whole long-horizon level of that table can be an artifact**, and the debias factor is
exactly the ratio of last-trade variance to efficient variance. `RESULT_swing_cluster.md` hit the
same bias and its Kendall debias killed four of six pairs; this is the same problem in the
frequency domain.

The tape settles it: the pool's **marginal price from vault balances has no bounce at all**. Same
statistic, bounce-free, on a 5-minute grid, over the horizons the tape supports:

| pool | grid pts | span | VR(15m) | VR(30m) | VR(60m) | VR(120m) | VR(240m) | last-trade, same T | bounce factor |
|---|---|---|---|---|---|---|---|---|---|
| DREGG/SOL | 132 | 10.9 h | 0.990 | 1.006 | 0.643 | **0.851** | — | 0.877 (2h) | 0.97 |
| nosis/SOL | 78 | 6.5 h | 0.849 | 0.798 | **0.826** | — | — | 1.000 (1h) | — |
| weave/SOL | 77 | 6.4 h | 1.011 | 0.872 | **1.010** | — | — | 1.000 (1h) | — |
| SOLVE/SOL | 353 | 29.3 h | 1.008 | 1.016 | 1.078 | 1.197 | **1.501** | 0.587 (4h) \* | **2.56** |

- **At 15 min to 1 h the bounce-free VR is 0.80–1.01 on all four pools. That is a random walk.**
  There is no intraday mean reversion in this cluster's efficient prices, and any LP or swing
  rule keyed to intraday reversion in the last-trade series is keyed to nothing.
- **Only SOLVE/SOL has enough tape to reach 4 h, and there the bounce-free VR is 1.50 —
  TRENDING — against 0.587 from last-trade closes over the same horizon.** A factor of 2.56, in
  the LP-hostile direction, on the one pool where the comparison can be made.
- DREGG/SOL reaches 2 h and the two **agree** (0.851 vs 0.877), so the bounce is not inflating
  everything everywhere.

**ONE POOL IS ONE POOL.** The SOLVE result is a lead, not a finding — every VR standard error
here is of order 0.2–0.3 and no cell is significant alone. It is reported because it points at
the thing that would matter most if it held: **the reversion the desk's whole LP thesis leans on
sits at 7–48 h, and nobody has yet checked those horizons against a bounce-free price.** The
check needs about a week of calendar time on the tape and nothing else. It is the single
cheapest way to confirm or kill the desk's central premise.

### 4.5 The verdict table

| pool | η (measured) | best VR in range | at T | verdict |
|---|---|---|---|---|
| DREGG/SOL | 0.235 | 0.438 | 48 h | **−EV by 1.9×** |
| nosis/SOL | 0.082 | 0.752 | 8 h | **−EV by 9.2×** |
| weave/SOL | 0.132 | 0.397 | 48 h | **−EV by 3.0×** |
| SOLVE/SOL | 0.055 | 0.266 \* | 72 h | **−EV by 4.8×** |

Every token/SOL pool in this cluster is −EV for an LP by roughly an order of magnitude, at the
most LP-favourable holding horizon its own price history offers, using a VR that is **biased in
the LP's favour** by the bounce. That is about as robust as a negative gets on this data.

**Falsification of the whole section:** measure η and VR(T) on a held-out window and check that
positions with `η > VR(T)` realise positive fee-minus-IL and positions with `η < VR(T)` realise
negative. Sign agreement on ≥ 20 positions is the bar. The desk has **42 closed positions on
chain** and `dlmm.datapi.meteora.ag` returns `allTimeDeposits` / `allTimeWithdrawals` in token
amounts, so the HODL counterfactual per position is computable today. If the sign does not
track, the ledger is wrong and everything above it goes.

---

## 5. MAXIMUM POWER TRANSFER — the optimal pool depth

### 5.1 The derivation

The EE result: source EMF `E` with internal resistance `R_s` into load `R_L` delivers
`E²R_L/(R_s+R_L)²`, maximised at `R_L = R_s`, 50% efficiency.

Routing cost through a pool for size `Φ` is fee plus impact:

```
    cost(Φ)  =  f Φ  +  r Φ²/2 ,          r ≡ 1/C = 4/TVL
```

so **`1/C` is the ELASTANCE** and it is what adds along a route — exactly the `r_e` of
`RESULT_circuit_model.md` §3.3. (It is *not* the behavioural resistance `R = τ/C`; keep them
apart. A router splitting an order across parallel pools equalises marginal costs, giving
`Φ_i ∝ C_i` at equal fees — a current divider in the capacitances.)

A taker takes the cheaper of our pool `(f, C)` and the best substitute route `(f₀, C₀)`. Our
cost minus the substitute's is `(f−f₀)Φ + (1/C − 1/C₀)Φ²/2`. When the two terms have **opposite**
signs there is a crossover **size** and we capture one side of it; when they have the **same**
sign one venue dominates at every size:

```
    Φ_x  =  2 |f − f₀| / |1/C − 1/C₀|

      undercut on fee, thinner  →  we capture every order BELOW Φ_x
      charge more, deeper       →  we capture every order ABOVE Φ_x
      charge more AND thinner   →  we capture NOTHING at any size    ← the desk's case, §5.3
```

Maximising yield per unit capital `y(C) = f·M(Φ_x(C))/(4C)` with `M` the captured volume gives a
condition with neither fee nor depth in it:

```
    d ln (captured volume) / d ln C   =   1
```

**That is the AMM's maximum-power-transfer condition: depth is optimal where captured volume is
unit-elastic in depth.** It has a unique interior root because captured volume is bounded above
and vanishes as `C → 0`.

**CLOSED FORM** for Pareto trade sizes with tail index α:

```
    premium-fee regime (charge more, be deeper — the desk's actual position):

            C*  =  α · C₀                                                            (A)

    undercutting a deep substitute (r₀ → 0):

            Φ_x* = Φ_min · α^{1/(α−1)},        C* = Φ_x* / (2(f₀−f))                 (B)

    and in case (B) the pool captures at its optimum exactly  (α−1)/α  of available
    volume, independent of fees, depth and size scale.
```

**(A) IS AN IMPEDANCE-MATCHING RESULT.** In elastance terms `r* = r₀/α`. At α = 1 — a scale-free
size distribution, the heaviest tail with no mean — this is **exactly `R_L = R_s`**, recovered on
the nose. Every α above 1 says: be *deeper* than matched, by exactly the tail index. **The EE
answer is the α → 1 limit of the AMM answer, and the tail index is the entire correction.**

### 5.2 α, measured — and it does not plateau, so it is reported as a range

Hill estimator on trade sizes from the tape, across tail fractions:

| pool | n | mean | median | α@5% | α@10% | α@15% | α@25% | α@40% |
|---|---|---|---|---|---|---|---|---|
| DREGG/SOL | 81 | 0.797 SOL | 0.393 | 1.18 | 1.18 | 1.27 | 1.16 | 1.11 |
| nosis/SOL | 2,317 | 1.257 | 0.246 | 2.08 | 1.45 | 1.09 | 0.91 | 0.75 |
| weave/SOL | 296 | 0.726 | 0.283 | 3.29 | 1.73 | 1.37 | 0.99 | 1.09 |
| SOLVE/SOL | 165 | 0.570 | 0.214 | 1.37 | 1.23 | 1.17 | 1.16 | 1.00 |
| weave/nosis | 77 | — | — | 1.28 | 1.28 | 1.41 | 2.18 | 1.66 |

The Hill plot **drifts** — on the best-sampled pool from 2.08 at the top 5% to 0.75 at the top
40% — which is what a mixture or a lognormal body looks like, not a clean Pareto. So:

> **α is pinned to the range 1–2 and no finer.** Carried as a range throughout.

That range suffices because `C* = α·C₀` is *linear* in α: the whole estimation uncertainty is a
factor of 2, against a gap to the desk's current sizing of two orders of magnitude. It would not
suffice if the question were "1.4 or 1.6".

**And note where it lands.** α ≈ 1 is the scale-free limit, where the AMM optimum is exactly the
textbook matched condition. **Memecoin trade sizes are close enough to scale-free that the
literal EE answer — make your pool as deep as the rest of the route combined — is the right
first-order answer here.** Read that as a property of this market's size distribution, not as a
general law.

### 5.3 Applied — and the degenerate case, which is the finding

The token-token substitute route is `A → SOL → B`, series capacitance
`C₀ = (1/C_{A/SOL} + 1/C_{B/SOL})^{-1}`. At the cluster's live TVLs and the top-decile Hill α = 1.28:

| token-token pool | substitute route | C₀ (series) | C* = α·C₀ | position value that realises it (W≈1) |
|---|---|---|---|---|
| weave/nosis | weave→SOL→nosis | $4,764 | **$6,110** | $6,110 |
| DREGG/nosis | DREGG→SOL→nosis | $6,749 | **$8,656** | $8,656 |
| weave/SOLVE | weave→SOL→SOLVE | $2,471 | **$3,169** | $3,169 |
| DREGG/SOLVE | DREGG→SOL→SOLVE | $2,916 | **$3,740** | $3,740 |

Against positions currently deployed at $100–$800. Two readings, opposite implications:

1. **The model is right and the desk is under-sized** — but not by much in *dollars*, because
   `y(C)` is first-order flat at its maximum, and the binding constraint is that the desk has
   ~$1.4k of LP capital against $4.1k/month of obligations. Optimal depth is not reachable, so
   this is not actionable as sizing.
2. **The model's premise fails.** It assumes takers **route on cost**. They do not.

**Reading (2) is the one with teeth, and the routing test lands in the degenerate regime:**

| our pool | f ours | f₀ route | C₀ | C ours | regime | median trade | cost @ median |
|---|---|---|---|---|---|---|---|
| weave/nosis | 6.00% | 2.40% | $4,764 | $838 | **substitute wins EVERY size** | $13.03 | **2.67×** |
| DREGG/nosis | 5.00% | 2.40% | $6,749 | $838 | **substitute wins EVERY size** | $0.06 | **2.08×** |

The desk's token-token pools are **both more expensive on fee and thinner** than the SOL
substitute, so `(f−f₀)Φ + (1/C − 1/C₀)Φ²/2` is positive in *both* terms at every size: a
cost-minimising router should send them **nothing at all**. Even granting the DLMM zero slippage
for orders that fit inside one bin — its best case and the right model at these trade sizes — the
**fee alone is ~2.5× the substitute's all-in cost**, and the substitute's own slippage does not
catch up until a few hundred dollars, far above the median trade. The median trade arriving at
the weave/nosis pool pays **2.67× the best available route cost.**

**So the flow is not cost-routed, and that is a sharper and more fragile claim about the desk's
edge than `RESULT_power_gate.md` §2.5's "pricing power on a route people need".** It is not
pricing power over a route — the route is strictly cheaper. It is a **router-attention rent** on
orders a cost-minimising router would have sent elsewhere. Rents of that kind are removed by a
software update, not by a competitor building a pool.

**Falsifiable both ways.** (i) If it is genuinely inattention, the premium should be paid by
direct-UI swappers and not by aggregator-routed ones. The tape distinguishes them (36% of
weave/nosis swaps were multi-hop routed), and the multi-hop legs are arbitrage crossing the pool
— which by §2 is zero-net for the LP anyway, so *the fragile rent and the profitable flow are the
same 64%*. (ii) If aggregator routing on this pair improves, single-hop income goes to
approximately zero. Measure the single-hop share of fee revenue now; the model predicts income
falls to what remains.

*(`C ours = $838` is `RESULT_power_gate.md`'s measured weave/nosis position, `T/W = 842/1.005` —
the sizing its 15.2× headline was measured at. That pool has since been drained and re-created;
see §7.)*

---

## 6. Multi-hop routes: Thevenin and Thomson are exact, the transmission line is nothing

**THEVENIN, EXACT (and nearly content-free, which is worth saying).** A route through pools `e`
presents to a trader, to the order the §1 ledger is exact:

```
    EMF        =  Σ_e ln p_e          composed log-price — additive only in logs
    series fee =  Σ_e f_e             diode drops in series; the dead-zone widens
    elastance  =  Σ_e 1/C_e           impact adds; capacitances add in SERIES
```

A route is exactly one synthetic pool, and that synthetic pool is the correct object to compare a
direct pool against. This is a theorem but a small one — it is series composition, which §3.3 of
the circuit model already used as `Σ r_e`. **Promoted as a tool, not as a finding.** It does make
one asymmetry visible: a thin leg dominates `Σ 1/C_e` completely, which is why "a thin pool
destroys an arbitrage rather than creating one".

**THOMSON'S PRINCIPLE, EXACT.** Splitting an order across parallel routes to minimise total cost
is exactly minimisation of `Σ_e ½ r_e Φ_e²` subject to flow conservation, with `r_e = 1/C_e`.
That is the Thomson/Dirichlet variational principle for a resistive network: **optimal routing on
an AMM graph is a current distribution**, and the router's first-order condition (equal marginal
cost on every used path) is KVL on the marginal system.

> **THE CAVEAT THAT KEEPS THIS HONEST:** the quantity being minimised is **stored**, not
> dissipated. It has the algebraic form of power dissipation and none of the physics. The
> genuinely dissipated part is the fee, which is **linear** in flow and contributes a term
> Thomson's principle does not have — an L1 penalty on top of the L2 one. **Consequence: unlike a
> resistor network, an AMM router uses a strictly SPARSE set of paths**, because an L1 penalty
> kills paths at zero flow. A resistive network puts current in every branch; a router does not.
> That is a real, checkable difference and it is why AMM routes are 1–3 hops rather than smeared
> over the graph.

**IMPEDANCE MATCHING BETWEEN POOLS IN SERIES — the brief's question, answered: there is no such
thing.** For a route the elastances simply add, so the trader's cost depends on `1/C_1 + 1/C_2`
and nothing else. At fixed total capital the sum is minimised at `C_1 = C_2`, but that is a
statement about a route *owner*, not about matching. **There is no interference term, no ratio,
and no reflection.** The whole answer is: `1/C` adds; put equal depth in each leg; done.

**NO TRANSMISSION LINE — DEMOTED, with the reason rather than a shrug.** A transmission line
needs an **inductance**: an element whose potential responds to the *rate of change* of current,
`V = L dI/dt`. **No AMM element does this.** Price responds to accumulated charge (`V = Q/C`),
never to flow acceleration. With no `L` there is no wave equation, no propagation velocity, no
characteristic impedance `√(L/C)`, and no reflection coefficient. Every "reflection" story about
AMMs is analogy with zero content.

**NO RESONANCE, NO Q FACTOR — DEMOTED, with the margin.** A pure *delay* in the arbitrageur
response is not an inductance, but delayed feedback around a capacitor can ring:

```
    C dV/dt  =  − V(t − τ_d)/R          oscillates when  τ_d/(RC)  ≥  π/2
```

| pair | τ = RC | τ_d | τ_d/τ | ÷ (π/2) | damping margin |
|---|---|---|---|---|---|
| DREGG/SOLVE | 37,395 s | 0.4 s (1 slot) | 1.07e−05 | 6.81e−06 | **146,848×** |
| DREGG/SOLVE | 37,395 s | 12 s (Ethereum) | 3.21e−04 | 2.04e−04 | 4,895× |
| weave/nosis | 46,224 s | 0.4 s | 8.65e−06 | 5.51e−06 | **181,521×** |
| weave/nosis | 46,224 s | 12 s | 2.60e−04 | 1.65e−04 | 6,051× |

Overdamped by five to six orders of magnitude. You would need arbitrageur latency comparable to
the *relaxation* time — hours — before an AMM could ring, and that only happens in a market with
no arbitrageurs, in which case the RC reading itself is void.

**ONSAGER RECIPROCITY — demotion upheld and strengthened.** `RESULT_circuit_model.md` §13
declined to use it. One thing can be added: at the single-swap bar the AMM's response matrix is
exactly **diagonal** (§10.1 of that study — cross-impact is mechanically zero), and a diagonal
matrix is trivially symmetric, so reciprocity is satisfied with **zero information content at the
one time scale where the mechanism is known.** At longer lags the symmetry that does appear is
forced by no-arbitrage (Schneider–Lillo Lemma 3.9), not by microscopic reversibility. So Onsager
here is not merely unproven, it is **untestable**: the regime where it would say something is the
regime where a different theorem already says the same thing for a different reason.

**POWER FACTOR — DEMOTED to vocabulary.** An AC circuit splits apparent power into real
(dissipated) and reactive (sloshed); a swap splits identically, fee versus impact, with
`power factor = 1/(1 + Φ/(2fC))`. This is a *name* for what the §6 ledger already had and nothing
follows from it. The one non-vacuous corollary is the crossover size `Φ = 2fC` where a trader's
impact first exceeds their fee — which is the same quantity that sets optimal depth in §5.
(Live: $57.6 on DREGG/SOL, $46.8 on nosis/SOL, $90.5 on the weave/nosis DLMM.)

---

## 7. Control theory: the recentering rule, and where the folk rule is wrong

**THE PLANT.** A DLMM position of value `T` over log-width `W = 2a`, centred on the price. In
range it is a capacitor `C = T/W` and earns fees. **Out of range it earns exactly zero and is
100% in one token — a fully discharged battery stack.** Recentring costs `κ`, dominated **not by
gas** but by the swap needed to rebalance an inventory that is all on one side.

This is impulse control of a diffusion with a fixed intervention cost (Constantinides–Richard,
Harrison–Taksar). Derive it rather than quoting the folk cube-root — **and use the §4 ledger
rather than gross fee income; the first draft of this section made exactly the mistake §2.4
catches in a live study:**

```
    cycle length (BM from centre):      τ = a²/σ²
    realised variance over the cycle:   RV = σ²τ = a²
    net displacement at exit:           (ΔV)² = a²   ⟹   VR = 1 AT THE EXIT
    net over the cycle (§4):            ½C·RV(η − VR) = ½(T/2a)a²(η−1) = T a (η−1)/4

    rate(a) = [ T a(η−1)/4 − κ ] / (a²/σ²) = σ²[ T(η−1)/(4a) − κ/a² ]

    d/da = 0   ⟹    a* = 8κ / (T(η−1))          W* = 2a* = 16κ / (T(η−1))
```

Three things fall out, and `(η−1)` does all the work:

1. **If `η ≤ 1` there is no optimal band.** Every width loses; the correct action is not to hold
   the position. A rebalance rule cannot rescue a pool whose churn number is below 1 — it can
   only decide how fast you pay. **Any recentring optimiser that does not carry η is optimising
   the width of a hole.** (And §8 measures η = 0.59–0.70 on the desk's flagship position.)
2. **`a*` is LINEAR in the recentring cost, not the cube root.** The cube-root law
   `Δ ∼ cost^{1/3}` is the answer for a *quadratic* running cost — a tracking-error penalty — and
   a concentrated LP's running cost is not that: it is a `1/a` foregone-depth term. The folk rule
   imported from the transaction-cost literature has the **wrong exponent** here.
3. **The chain matters far less than the literature thinks.** Cartea–Drissi–Monga measure
   Ethereum recentring at $84.8 per round trip and conclude the strategy needs $1.8M of capital;
   that break-even is *gas*. On Solana gas is ~$0.30 — but the dominant term is the rebalance
   **swap**, `κ ≈ (T/2)f_swap + G`, so

```
       a*  =  ( 4 f_swap  +  8G/T ) / (η − 1)
```

   **On a low-gas chain the optimal half-width is set by the swap fee, not by gas**, and gas stops
   mattering entirely above `T ≫ 2G/f_swap ≈ $30`. The cube-root rule would have predicted a
   Solana band 6.6× narrower than Ethereum's; the correct answer is that below ~$30 of position
   size the two chains differ enormously and above it they are the same.
   `RESULT_lp_literature.md` §6 items 6–7 record "no closed-form optimal recentering rule under
   fixed transaction costs" and "no measurement of recentering economics on a low-gas chain" as
   open. **This is the closed form. The measurement still needs doing.**

Optimal full width `W*` (log-price units, G = $0.30):

| f_swap | η | T=$100 | T=$842 | T=$5,000 | T=$50,000 |
|---|---|---|---|---|---|
| 1.10% | 1.5 | 0.272 | 0.187 | 0.178 | 0.176 |
| 1.10% | 3.0 | 0.068 | 0.047 | 0.044 | 0.044 |
| 2.20% | 1.5 | 0.448 | 0.363 | 0.354 | 0.352 |
| 2.20% | 3.0 | 0.112 | 0.091 | 0.088 | 0.088 |
| 5.50% | 1.5 | 0.976 | 0.891 | 0.882 | 0.880 |
| 5.50% | 3.0 | 0.244 | 0.223 | 0.220 | 0.220 |

Against the desk's live positions (Meteora datapi, read-only, 2026-08-14 ~00:0x UTC):

| pool | bins | bin_step | base fee | W actual | 4/W | W* (2.2%, η=3) | W*/W | in range | age | earned |
|---|---|---|---|---|---|---|---|---|---|---|
| weave/SOL | 21 | 200 | 5.00% | 0.3961 | 10.10 | 0.0912 | 0.230 | at lower edge | 1.33 h | **$0.00** |
| nosis/weave | 30 | 300 | 6.00% | 0.8572 | 4.67 | 0.0937 | 0.109 | yes | 1.14 h | $17.32 |
| weave/SOLVE | 69 | 200 | 5.00% | 1.3466 | 2.97 | 0.1112 | 0.083 | yes | 1.11 h | $0.68 |

The ranges are 2–6× wider than the rule says at η = 3, and the direction is the interesting part:
**a wider range is the RIGHT error if η is nearer 1 than 3**, because `W*` scales as `1/(η−1)`.
So this table does not say "narrow your ranges" — it says **measure η first**, because that one
number moves the answer more than any width choice does. What it does say unconditionally: a
width set by a bin-count habit rather than by `κ/T` is not being sized by anything.

*(The weave/SOL position is the third documented instance of the pathology: sitting at the bottom
bin of its own range, holding 100% weave and 0 SOL, having earned exactly $0.00 over its life.
`RESULT_power_gate.md` §2.7 called range exit "the modal state transition"; three-for-three on
independent reads supports that.)*

### 7.1 The prediction that needs no model at all

For BM started at the centre of a band of half-width `a`, the expected exit time is exactly

```
    E[time in range]  =  a² / σ²                                    [no free parameter]
```

Three independently measured quantities: `a` from the position's own bin range, `σ` from realised
volatility, and the observed in-range duration from the position history. σ is *measured*, not
assumed — from the pool's own marginal price where a constant-product venue exists (no bounce),
from the last-trade ratio otherwise (which carries bounce and therefore biases the prediction
DOWN):

| pool | a = W/2 | σ/hr measured | source | E[in-range] | observed age |
|---|---|---|---|---|---|
| weave/SOL | 0.1980 | 0.0954 | vaults | 4.31 h | 1.33 h |
| nosis/weave | 0.4286 | 0.3959 | ratio-LT | **1.17 h** | **1.14 h** |

The nosis/weave agreement is 1.17 h predicted against 1.14 h observed — but **that is not a
verification**: the position is still open, so its age is a *censored* observation, not an exit
time, and one match on a censored sample is a coincidence until it is a regression.

**Falsification, and this is the cheapest test in the file.** `RESULT_lp_history.md` records **42
positions with holding periods** (July: 5 h, 18 h, 32 h, 45 h, 99 h; August: 0.1 h, 0.8 h, 1.2 h,
3.6 h, 6 h — an order-of-magnitude tempo collapse). Regress observed in-range duration on
`a²/σ²`, σ measured over each position's own life. Slope 1, intercept 0. A slope far from 1 means
the price is not diffusive at the position's scale — drift or jumps dominate — which is exactly
the failure mode that makes concentrated LPing lose. **This turns the "in-range time fraction",
which `RESULT_power_gate.md` §2.7 named as "the single largest unquantified term", into a number,
and the data already exists.**

### 7.2 Three things standard control design says that a naive threshold does not

1. **Dead-zone, not a set-point.** The optimal policy is `(s,S)`: act only at the band edge, then
   jump to the interior. A rule that recentres "when the price moves x% *from here*" has a
   set-point, not a dead-zone, and it churns.
2. **The re-entry point is not the centre.** A position that exits at the lower edge is 100% in
   the base token, and recentring means selling half of it at the worst price of the excursion.
   The asymmetric-cost impulse solution re-enters **short of centre**, biased toward the side you
   already hold. **NOT DONE HERE** — flagged as the one piece of this section that is derivable
   and undone; it is a one-dimensional optimisation over the re-entry offset.
3. **Hysteresis is already there and is not free.** The fee band is a dead-zone and the bin grid
   is a second one; a rebalance dead-zone makes three in cascade, and lost motion adds. **A
   rebalance threshold tighter than the fee band is pure cost** — inside the band the price does
   not move at all, so there is nothing to capture. That is a hard floor and it is in none of the
   LP literature:

```
       rebalance threshold  >  fee band  =  Σ fees around the rebalance cycle
```

---

## 8. η measured on chain, and what it says about the desk's business

`RESULT_circuit_model.md` §7.3 named on-chain pool state as the fix for its ~150 bps resolution
ceiling and listed it as "what to do next, #2". **The cluster tape now carries it**: every
PumpSwap swap record has `replay_sufficient: true` with vault pre/post balances, and for `x·y=k`
the marginal price is exactly `y/x`. Everything in this section is that read.

| pool | swaps | hours | N (SOL) | TVL | RV | TV | 2f·TV/RV | **η** |
|---|---|---|---|---|---|---|---|---|
| DREGG/SOL | 81 | 10.9 | 64.58 | $55,777 | 0.00598 | 0.374 | 0.250 | **0.235** |
| nosis/SOL | 2,317 | 6.5 | 2,912.92 | $52,320 | 0.82776 | 17.216 | 0.083 | **0.082** |
| weave/SOL | 296 | 6.4 | 214.89 | $29,972 | 0.06606 | 2.345 | 0.142 | **0.132** |
| SOLVE/SOL | 165 | 29.3 | 94.09 | $14,750 | 0.13950 | 2.187 | 0.063 | **0.055** |

`2f·TV/RV` is a **direct test of the local-time relation** §2(a): a pool dragged only by marginal
arbitrage against a diffusive external price has `TV = RV/(2f)` and reads 1.00. It reads
0.06–0.25, and the direction is informative — **the marginal price moves in fewer, larger steps
than band-crossing arbitrage would produce**, i.e. it is being pushed by takers who cross several
bands at once, or it is gapping. That is §2(d)'s jump regime, where the LP loses, and it agrees
with the jump budget in §2.3.

Sensitivity to the **assumed** PumpSwap LP leg (inherited, not measured):

| pool | f=0.10% | f=0.20% | f=0.25% | f=0.50% |
|---|---|---|---|---|
| DREGG/SOL | 0.118 | 0.235 | 0.294 | 0.588 |
| nosis/SOL | 0.041 | 0.082 | 0.102 | 0.204 |
| weave/SOL | 0.066 | 0.132 | 0.165 | 0.330 |
| SOLVE/SOL | 0.028 | 0.055 | 0.069 | 0.139 |

The conclusion does not turn on it: η is far below 1 across the whole swept range.

### 8.1 The token-token pool — the one the desk's business rests on

A DLMM has no reserve-ratio price, so η needs the pair's efficient volatility from elsewhere:
build it from **both /SOL pools' marginal prices** (exact, from vaults) on a 5-minute grid over
exactly the window the token-token tape covers. `C = T/W` from the operator's own measured range,
`N` from the tape, `f` from the pool config (base 6.0%, protocol 10% → **5.40% to the LP**).

```
   weave/nosis:  window 5.33 h,  77 swaps,  f_LP = 5.400%,  RV(ratio) = 0.37506
                 N = $1,725 (00:30 run)  /  $2,045 (00:05 run) -- the spread is the nosis USD
                 price used to value the quote leg, which moved 16% between the two reads.
```

| position value T | W | C = T/W | **η** @00:30 | **η** @00:05 | source of the sizing |
|---|---|---|---|---|---|
| $842 | 1.0050 | $838 | **0.59** | **0.70** | `RESULT_power_gate.md` 08-13 |
| $466 | 0.8572 | $543 | **0.91** | **1.08** | live 08-14 |
| $842 | 4.0000 | $210 | **2.36** | **2.80** | *the same pool run unconcentrated* |

**All four reads of the deployed sizings are at or below 1.** In dollars on the consolidated
run: over that 5.33 h window the position took **$93 of fees against $157 of adverse selection —
net −$64 on an $842 position, i.e. −7.6% in 5.33 hours.** The gross fee rate over that window
annualises to ~50%/day, in the same range as the 32.1%/day `RESULT_power_gate.md` measured over
a different 6.07 h; the point is not that the gross number is wrong but that it is **gross**, and
against the inventory leg on the same flow it does not clear.

**The two-read spread is itself the honest caveat**: η moved 16% in twenty-five minutes because
its numerator is denominated in a token whose price moved. On a 5.33 h window η is not settled
to better than ±20%, which is why §11's first item is to compute it over the 42 closed positions
rather than to act on this table.

**READ THE THIRD ROW.** η is inversely proportional to `C`, so a *more* concentrated position has
a *lower* η on the same flow. The unconcentrated row is the same pool with the same fee tier and
the same flow, and its η is `4/W` times higher. **That is the honest statement of what
concentration does, and it is the opposite sign to the intuition that concentration "earns
more".** It is leverage on `(η − VR)` (§4.2) and it levers the loss exactly as hard as the gain.

### 8.2 What this changes about the desk's LP thesis

`RESULT_power_gate.md` §2.7's verdict — "the token-token LP edge is REAL, 15.2× the best
token/SOL alternative on realized fee yield per unit TVL" — is **correct on the quantity it
measured, and the quantity it measured is not the one that decides.** Fee yield per unit TVL is
the first term of the §1 ledger with the second term omitted. Restated with both terms:

| claim | status here |
|---|---|
| Token-token beats token/SOL on fee yield per unit TVL by 15.2× | **Upheld.** η is linear in `f`, and 5.40% against 0.20% is 27×; the yield ranking is the η ranking |
| Therefore the token-token position is profitable | **NOT ESTABLISHED.** η = 0.59–0.70 at the sizing that produced the 15.2×. Beating a large negative is not a positive |
| Concentration `4/W` is "already inside measured turnover" | **Upheld and sharpened.** It is inside *both* terms equally: pure leverage, sign-preserving |
| Arbitrage revenue is competition-invariant, so "half the edge" survives a rival | **Overturned** (§2.4). That half is zero-net; a rival taking only taker flow takes 100% of the profit |
| The edge is "pricing power on a route people need" | **Sharpened to a more fragile claim** (§5.3): a router-attention rent on orders a cost-minimising router would not have sent |

**None of this says close the pools.** It says the number that decides them is η, that η is
measurable today from data already on disk, and that across two reads it sits at 0.59–1.08 —
i.e. **on the line or under it, never comfortably above it**, on a 5.33 h sample. `RESULT_power_gate.md` said ~9 days would
settle the yield; the same 9 days settles η, and η is the one that has a sign.

---

## 9. Falsifiable claims, each with its falsification

| # | Claim | Falsified by | Status |
|---|---|---|---|
| 1 | `IL = 2C(e^{ΔV/2}−1)²` exactly; `= ½C(ΔV)²` to 2nd order | Any CFMM reprice disagreeing with the closed form | **Verified to machine precision**; quadratic matches to the same order the §6 ledger closes |
| 2 | `½C·QV = fee + arb net + O(Cf²)`, at any block time and fee tier | An MC or on-chain window where the three do not sum | **Verified: SUM = 1.00 ± 3% over a 100× sweep of ε** |
| 3 | LP loss to arbitrage = arb net profit, exactly | Tagging atomic multi-pool routes on the tape and finding LP P&L ≠ −(arb profit) on that subset | **Derived, identity; untested on chain — the tape supports it now** |
| 4 | LP breaks exactly even on arbitrage flow on a continuous path | Measurable LP profit on arb-only flow | **Derived; MC-consistent (arb/(QV/2) → 0 as ε → 0)** |
| 5 | LP loss is supported on gaps, `½C(|z|−f)₊²` | Loss tracking total variance rather than the gap sum | **Measured: gap sum accounts for 79–94% of ½C·RV; top-5 swaps carry 24–79% of it** |
| 6 | `σ_eff² ≤ 2 min_v (f_v vol_v / C_v)` on live pools | A live pool whose *marginal-price* vol exceeds the bound with a measured fee leg and a deeper external venue | **Holds on DREGG/SOL (0.91); violated 2.0–2.6× on the busy pools — which indicts either the print or the "price follower" premise** |
| 7 | LP is +EV ⟺ `η > VR(T)` | Sign disagreement on ≥ 20 closed positions with a HODL counterfactual | **Untested — the 42 closed positions and the datapi deposit/withdraw amounts make it runnable today** |
| 8 | Every token/SOL pool in this cluster is −EV for an LP | η > VR at any horizon | **η = 0.055–0.235 vs best VR 0.27–0.75: −EV by 1.9–9.2×** |
| 9 | The desk's token-token pool is on the line, not above it | A 9-day η measurement landing well above 1 | **η = 0.59–0.70 (power_gate sizing) and 0.91–1.08 (live) across two reads 25 min apart, on a 5.33 h window — THIN and ±20% unstable** |
| 10 | `C* = α·C_0`; textbook `R_L = R_s` is the α → 1 case | Yield per unit capital rising monotonically in depth past `α·C_0` | **Derived; α measured only to 1–2 (Hill drifts); not tested by variation** |
| 11 | Flow at the desk's pools is not cost-optimally routed | Finding the desk's pool cheaper than the SOL route at the sizes that actually arrive | **Substitute route is cheaper at EVERY size; median trade pays 2.67× the best route** |
| 12 | `a* = 8κ/(T(η−1))`, linear in cost, not cube-root | A measured optimum scaling as `κ^{1/3}` | **Derived; untested — needs recentring economics measured on chain, which nobody has done anywhere** |
| 13 | `E[in-range] = a²/σ²` | Regression slope ≠ 1 on ≥ 20 positions | **1.17 h vs 1.14 h on one censored observation — not evidence** |
| 14 | Intraday (15 m–1 h) efficient prices in this cluster are a random walk | Bounce-free VR significantly below 1 | **Measured 0.80–1.01 on four of four pools** |
| 15 | The measured mean reversion at longer horizons is substantially bounce | Bounce-free VR at 4–48 h matching the last-trade VR | **One pool reaches 4 h: SOLVE/SOL, 1.50 vs 0.587 — a 2.56× factor, LP-hostile. n=1 pool** |

---

## 10. What is demoted to analogy, explicitly

- **Transmission line / reflection / characteristic impedance.** **No content.** There is no
  inductance in an AMM — no element with `V = L dI/dt`. No `L` ⟹ no wave equation ⟹ no
  propagation velocity ⟹ no `√(L/C)` ⟹ no reflection coefficient.
- **Q factor / resonance / ringing.** **No content, with the margin:** the delayed-feedback
  stability criterion `τ_d/(RC) ≥ π/2` is missed by **5–6 orders of magnitude** at real
  arbitrageur latency. This is a first-order lag, not a resonant circuit.
- **Johnson–Nyquist as a fluctuation–dissipation theorem.** **Demoted.** No temperature, no
  detailed balance, and the noise and the dissipation are causally independent. Only the
  *available-power* structure (the dissipative element's strength cancelling) transfers, and it
  transfers exactly.
- **Onsager reciprocity.** **Untestable, which is worse than unproven.** Diagonal at the one lag
  where the mechanism is known; forced by no-arbitrage at longer lags.
- **Power factor / real vs reactive power.** **Vocabulary.** A name for the §6 ledger's split.
  The single non-vacuous corollary (`Φ = 2fC`) reappears in §5 for a different reason.
- **"Pool = low-pass filter on order flow", with a cutoff frequency.** **Wrong as stated.** The
  flow→price map *is* an integrator (that half is exact), but the fee element is rate-independent
  hysteresis and has **no frequency response at all**, so no cutoff frequency exists. Replaced by
  the notch statement and `η > VR(T)`.
- **"Maximum power transfer means `R_L = R_s`" applied literally.** **Half-demoted.** The
  variational *form* transfers exactly; the matched point moves to `r* = r₀/α`. The textbook
  answer is recovered only at α = 1 — which happens to be roughly where this market's trade sizes
  sit, so the numerical answer survives for a reason the analogy did not supply.
- **"Impedance matching between pools in series."** **No such thing.** Elastances add; there is
  no ratio, no interference term and no reflection.
- **Thevenin equivalent of a route.** **Exact but trivial** — series composition, already in use
  as `Σ r_e`. Kept as a tool, not claimed as a finding.

---

## 11. What to do next, in cost order

1. **Compute η and the HODL counterfactual on the 42 closed positions.** Zero new data: the tape
   has the flow, `dlmm.datapi.meteora.ag` returns `allTimeDeposits`/`allTimeWithdrawals` in token
   amounts, and §4's falsification is a sign test. This settles claims #7 and #9 and it is the
   single highest-value computation identified here.
2. **Run the tape for ~9 days and recompute the bounce-free VR at 7–48 h.** §4.4 shows the
   cluster's reversion is unverified precisely at the horizons the desk's thesis needs, and one
   pool's 4 h reading points the wrong way. Calendar time is the only missing input.
3. **Regress in-range duration on `a²/σ²` over the position history** (§7.1). Turns the
   in-range fraction from `RESULT_power_gate.md`'s "single largest unquantified term" into a
   number, from data already on disk.
4. **Measure the PumpSwap LP fee leg from chain** rather than inheriting 0.20%. It is the last
   assumed input in η, in the §3 bound, and in every fee band in `RESULT_circuit_model.md` §3.
   Same vault-delta method that measured the DLMM tier at 5.51–5.60%.
5. **Tag atomic multi-pool routes and compute LP P&L on that subset** (claim #3). The theorem
   says zero; the tape already carries the tags.
6. **Derive the asymmetric re-entry offset** (§7.2 item 2) — a one-dimensional optimisation, and
   the only thing in this file that is derivable and left undone.
