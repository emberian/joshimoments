# RESULT: the AMM cluster as an electrical circuit — what is exact, what is analogy, what is measurable

2026-08-13. Instrument: `studies/circuit_model.py` (stdlib only, keyless APIs — DexScreener and
GeckoTerminal). Universe and pool addresses inherited from `studies/RESULT_swing_cluster.md`.

Unless a table says otherwise, every live number below comes from **one consolidated run at
2026-08-13 21:14 UTC** (`python studies/circuit_model.py all`), so the tables are mutually
consistent rather than stitched from different minutes. The polled series in §8 is a separate
21-minute window (16:48–17:09 UTC), and §7.2 deliberately reports **two** runs because the
disagreement between them is itself the finding. Every number was produced by that script or by
algebra reproduced inside it. §3 discipline applies to this study as it does to everything else.

---

## 0. What this found, in six lines

1. **Three of the five correspondences are exact identities, two are wrong as stated in the brief.**
   A CFMM pool is exactly a nonlinear capacitor with `C = w_x w_y · TVL` (= TVL/4 at 50/50),
   verified numerically to 6 digits. The fee is **not** an `I²R` resistor — dissipation is linear
   in |flow| — so it is a **back-to-back diode pair**, and the no-trade band is literally the diode
   dead-zone. Liquidity sets **capacitance, not conductance**. The only genuine ohmic resistance in
   the system is behavioural.
2. **The curl is at the edge of what public quotes can measure.** Two independent aggregators
   disagree about the same pool's price by a median 105–146 bps against fee bands of 186–342 bps,
   and the *verdict on a given cycle flips between runs 4 hours apart.* One cycle
   (`DREGG→SOL→DREGG`) survives a two-source agreement test at 21:14 and failed it at 16:57.
3. **Even taken at face value, the largest standing residual is worth $0.37 to $9.86 per loop.** The
   depth-and-gas term dominates the fee term on any loop containing a thin leg. This reproduces
   Schneider & Lillo's own equities finding — symmetry violations exist and are unprofitable — in a
   completely different market, with a completely different instrument.
4. **Over 21 minutes of polling, KVL holds wherever it is measurable.** On the one 2-cycle whose
   both legs actually trade (`weave→SOL→weave`), the curl sat inside the fee band **100% of 63
   samples**, mean +14 bps against a 226 bps band. The cycles that look violated are exactly the
   ones containing a pool that did not trade once during the window.
5. **The swing study's structural claim is falsified on the half of it that needs no fee
   assumption.** Median token-token turnover is **30.6%/day** against **258.1%/day** for token/SOL.
   The token-token fee tier must be **8.4× higher** (10.4× above a $100 TVL floor) just to break
   even on gross fee income per unit TVL.
6. **The one robust pair in the swing study is not circuit-coupled at all.** SOLVE has degree 1 in
   the live pool graph, so no cycle passes through it and no arbitrage constrains its price. The
   7.2h DREGG/SOLVE half-life cannot be an arbitrage RC constant. It is a statement about demand —
   and it hands the §10 experiment a free negative control.

Reproduce: `python studies/circuit_model.py all`.

---

## 1. The universe as a graph

18 pools touch the four mints; 10 clear a $100 liquidity floor (21:14 UTC):

| pair | dex | TVL | vol24 | tx24 | pool |
|---|---|---|---|---|---|
| DREGG/SOL | pumpswap | $57,608 | $25,544 | 597 | `2XHrhkxf…` |
| nosis/SOL | pumpswap | $46,798 | $582,941 | 7,089 | `7nv2RtGX…` |
| weave/SOL | pumpswap | $27,998 | $176,655 | 3,376 | `GA1nQL5R…` |
| SOLVE/SOL | pumpswap | $15,878 | $4,468 | 100 | `BQHANwBn…` |
| nosis/SOL | meteora DLMM | $11,977 | $156,212 | 1,419 | `C889ex3M…` |
| weave/SOL | meteora DLMM | $1,306 | $6,163 | 278 | `77Nm2cKt…` |
| weave/nosis | meteora DLMM | $812 | $367 | 22 | `QQnW4Zw3…` |
| DREGG/SOL | meteora DLMM | $689 | $6 | 4 | `BV1oUHBT…` |
| DREGG/Circuit | meteora DYN2 | $663 | $46 | 44 | `9qYS6Ed9…` |
| DREGG/nosis | meteora DLMM | $433 | $688 | 46 | `FNxnyS3h…` |

Below the floor and excluded, but named because their absence is a result: `SOLVE/DREGG` ($0 TVL,
5 tx24), `weave/DREGG` ($0 TVL), and three DYN2 shells on DREGG.

**A label correction.** `RESULT_swing_cluster.md`'s scratchpad script had weave and SOLVE transposed
in its `MINTS` dict. The study's *table* is correct and is what this study follows:
`8PecVcCG… = weave` (FDV $128k), `GwyWFsDK… = SOLVE` (FDV $44k). Verified against the symbols
DexScreener returns per mint.

**The topology, which decides everything downstream:**

```
                 weave ─────────── nosis
                   │  \  ($812)   /  │
        ($28k+$1.3k)│   \        /   │($46.8k+$12.0k)
                   │    \      /($433)
                   └──── SOL ──┴─ DREGG ($57.6k+$689) ── Circuit ($663)
                          │
                          │ ($15.9k)
                        SOLVE          ← degree 1. no cycle. no KVL constraint.
```

Cycle rank `E − N + 1 = 10 − 6 + 1 = 5`. The instrument enumerates exactly five: three **2-cycles**
(the same pair on two venues — the degenerate KVL loop, `DREGG/SOL`, `nosis/SOL`, `weave/SOL`) and
two **triangles** (`DREGG→SOL→nosis→DREGG`, `SOL→nosis→weave→SOL`).

**SOLVE is a leaf, and Circuit is a leaf.** SOLVE's only live pool is SOLVE/SOL; the SOLVE/DREGG
DLMM has $0 TVL and 5 trades in 24h. No cycle passes through SOLVE, so no-arbitrage says *nothing
whatever* about the DREGG/SOLVE ratio. §5 returns to what that does to the swing study's headline.

---

## 2. Pool = capacitor. Exact.

### 2.1 Constant product

A pool with reserves `(x, y)`, `x·y = k`, marginal price of X in Y units `p = y/x`.

Choose the **potential** `V ≡ ln p`. This is not an aesthetic preference. KVL is the statement that
a potential exists — that a path integral is path-independent — and prices compose
*multiplicatively* along a path. Only in logs is the composition additive, so only in logs is there
a potential at all.

Choose the **charge** `Q ≡ y`, the quote-side reserve measured in value.

From `x = k/y`: `p = y/x = y²/k`, so

```
    V = 2 ln y − ln k          ⟺          y = √k · e^{V/2}
```

and therefore

```
    C(V) ≡ dQ/dV = y/2 = Q/2.
```

A constant-product AMM is **exactly** the capacitor obeying `C(V) = Q(V)/2` — capacitance
proportional to stored charge, hence exponential in the potential. Since such a pool is 50/50 by
value, `y = TVL/2`:

```
    C = TVL/4          (units: dollars per unit of log-price)
```

Capacitance is measured **in dollars**, and it is one quarter of the pool's TVL. Nothing is fitted.

*General geometric-mean pool* (`x^{w_x} y^{w_y} = k`, `w_x + w_y = 1`): the same derivation gives
`V = const + (ln y)/w_x`, hence

```
    C = w_x · y = w_x w_y · TVL
```

verified numerically against brute-force perturbation of the invariant at `w_x ∈ {0.3, 0.5, 0.8}`,
agreeing to 6 significant figures. Maximised at 50/50, where it is `TVL/4`. Skewing the weights
makes a pool *less* capacitive at its own price.

### 2.2 Meteora DLMM: a piecewise capacitor, and why "battery bank" is exact rather than cute

A DLMM holds liquidity in bins of constant *multiplicative* width `s = bin_step/10⁴`, i.e. constant
width `δ = ln(1+s)` in the potential. Inside a bin the pool is constant-**sum**: it trades at a
single fixed price until one side of that bin is exhausted. Therefore

```
    inside a bin:      dV = 0  while dQ ≠ 0     ⟹   C = ∞
    at a bin edge:     dV = δ  while dQ = 0     ⟹   C = 0
```

`C(V)` is a comb — a spike at each bin price, zero in between. Coarse-grained over a window spanning
many bins holding value `L_b` each:

```
    C̄ = L_b / δ ,   and over a position of total value T spread across log-width W:   C̄ = T/W .
```

**An element with locally infinite capacitance at a fixed potential, holding finite charge, is an
ideal voltage source with finite capacity — a battery cell.** A DLMM is a *series stack* of such
cells at EMFs spaced `δ` apart: a battery bank in the strict sense, not by resemblance. Discharging
the pool walks down the stack one cell at a time, and "zero slippage within a bin" is precisely a
battery's near-zero internal resistance until exhaustion.

**Two consequences that do real work later.**

*Concentration factor.* A DLMM of TVL `T` over log-width `W` has `C = T/W` against constant
product's `T/4`, so it is deeper by `4/W`. Typical concentrated ranges (`±10%` to `±50%`) give
`W ≈ 0.2–0.8`, a factor of **5× to 20×**. This is what makes "$1 of DLMM TVL" and "$1 of
constant-product TVL" non-comparable. It is **not observable from any keyless endpoint** —
recovering it needs the active bin and the bin liquidity array, i.e. chain reads — so it is carried
as an explicit knob (`dlmm_span`) everywhere it matters, with both bounds always reported.

*Staleness means something different on a DLMM, and this matters for §7.* A constant-product pool's
last-trade price decays into fiction the moment anyone else trades, because the marginal price is a
continuous function of reserves. A DLMM that has not traded **has not moved its active bin**, so its
last print *is* its current marginal price. A quiet DLMM is not a stale quote; it is a parked
battery. That asymmetry is why some of the §7 residuals are credible and others are not.

### 2.3 Conductance from liquidity — the brief's mapping, corrected

The brief proposed "conductance ≈ f(liquidity, fee)". Splitting it is the substantive correction,
and it is worth stating plainly rather than smoothing over.

**Liquidity does not set a conductance. It sets a capacitance.** In a pool, price displacement is
proportional to *accumulated charge*, not to *current*: `V = Q/C`, not `V = IR`. A pool that has
absorbed net buying sits at a displaced potential and stays there — indefinitely, with no current
flowing. That is a capacitor's defining behaviour and not a resistor's. Nothing about the
displacement is dissipative: it is returned in full to whoever trades back, which is exactly the
round-trip identity already recorded in PROGRAM.md §1.4.

**The fee is not an `I²R` resistor either.** Fee dissipation is `f·|Φ|` — *linear* in the value
pushed, not quadratic in a rate. An ohmic resistor dissipates `I²R`; this element takes a constant
fraction of throughput regardless of rate, which is Coulomb friction, i.e. a **back-to-back diode
pair with forward drop `f`**. That is why a fee produces a *dead-zone* — a band of potential across
which no current flows at all — which no resistor ever does. §3.2 shows the fee band falling
straight out of that reading, and §4.4 shows the dead-zone making a fresh, testable prediction that
a resistor model cannot make.

So the circuit is:

| element | what it is | exact? | measurable? |
|---|---|---|---|
| capacitor `C = w_x w_y·TVL` | the pool | exact identity | **yes**, from TVL |
| back-to-back diodes, drop `f` | the swap fee | exact identity | fee tier: partly (§9.3) |
| **resistor `R`** | trader/arbitrageur responsiveness | **the only genuine resistance** | **no — the one free parameter** |
| EMF source | exogenous order flow | analogy (§13) | via the tape |
| fixed series cost `G` | gas | exact | yes |

The one place Ohm's law genuinely holds is behavioural: traders push value flow at a rate increasing
in the mispricing, `I = V/R`. `R` is not a protocol constant; it is a property of a population, and
it is the single free parameter of the whole model. §4 shows it is nevertheless *identified*.

---

## 3. The network: KVL, the curl, and the band

### 3.1 The curl statistic

Tokens are nodes, pools are edges, each pool measures a potential difference
`V_base − V_quote = ln p_pool`. For a cycle `(i → j → k → i)`:

```
    C(cycle) ≡ ln p_{i/j} + ln p_{j/k} + ln p_{k/i} ,        reported in bps (10⁴ × the log).
```

KVL ⟺ `C = 0` ⟺ log-price is a genuine node potential ⟺ no cycle arbitrage. `C` is the discrete
curl of the log-price 1-form on the pool graph; nonzero means the 1-form is not exact and no
consistent set of token prices exists.

The **2-cycle** — the same pair on two venues — is the degenerate case and, in this cluster, the
best-instrumented one, because both legs can have real liquidity. It is reported alongside the
triangles rather than instead of them.

### 3.2 The fee band, derived

An arbitrageur sends notional `Φ` around the loop. Each leg keeps `f_e`, so at infinitesimal size
the loop returns `exp(C) · Π_e (1 − f_e)` per unit sent. Profitable iff that exceeds 1:

```
    C  >  Σ_e ln( 1 / (1 − f_e) )                                            (band, zero size)
```

and by the same argument traversed backwards, `C < −Σ_e ln(1/(1−f_e))`. **The band edges *are* the
fee sum**, exactly, in log space, in the zero-size limit — which is the dead-zone of the diode stack
of §2.3, one diode per leg, forward drops adding in series. That is the whole derivation.

Bands for this cluster (PumpSwap `0.20% LP + 0.05% protocol + FDV-ladder creator fee`; DLMM leg
carried as a swept unknown, midpoint 1.00%):

| cycle | fee band |
|---|---|
| `DREGG→SOL→DREGG` (2-cycle) | **186 bps** |
| `nosis→SOL→nosis`, `weave→SOL→weave` (2-cycles) | **221 bps** |
| `DREGG→SOL→nosis→DREGG` | **307 bps** |
| `SOL→nosis→weave→SOL` | **342 bps** |

A full sensitivity grid over both unknown fee legs is printed by `circuit_model.py snapshot`. Across
the whole swept range (PumpSwap LP leg 0.05–1.00%, DLMM leg 0.20–5.00%) the triangle band runs
186 bps to 871 bps. **The band is the entire result, and one of its two inputs is assumed** — which
is why §9.3 goes to the trouble of estimating the creator leg from the operator's own income.

### 3.3 The band that decides whether money moves

The zero-size band answers "does an arbitrage exist". It does not answer "is it worth doing", and in
this cluster the two answers differ by more than the first one is worth. Pushing `Φ` around the loop
moves every leg against the trade — that is the `½C(ΔV)²` term of §6, summed over legs — and pays a
fixed gas `G`:

```
    profit(Φ)  =  Φ·(|C| − Σf)  −  ½ Φ² Σ_e r_e  −  G ,        r_e ≡ 1/C_e = W_e / TVL_e
```

Maximising over `Φ`:

```
    Φ*      = (|C| − Σf) / Σ r_e                        ← the optimal arb size, in dollars
    profit* = (|C| − Σf)² / (2 Σ r_e)  −  G
```

so the honest band — the one that decides whether anything happens — is

```
    |C|  >  Σ_e f_e  +  √( 2 G Σ_e r_e )                                                  (★)
```

**The fee sum is only the first term, and in this cluster it is not the big one.** With `G = $0.30`
(config caps priority fee at 0.005 SOL; a 3-leg atomic route taken at ~0.004 SOL at $76/SOL):

| cycle | curl | fee band | full band `W=4.0` | Φ* | profit | full band `W=0.2` | Φ* | profit |
|---|---|---|---|---|---|---|---|---|
| `DREGG→SOL→nosis→DREGG` | 1,426 | 307 | **1,058** | $12 | **+$0.37** | **499** | $181 | **+$9.86** |
| `DREGG→SOL→DREGG` | −559 | 186 | **779** | $6 | −$0.18 | **333** | $104 | **+$1.64** |
| `nosis→SOL→nosis` | 111 | 221 | 380 | — | −$0.30 | 300 | — | −$0.30 |
| `weave→SOL→weave` | −66 | 221 | 660 | — | −$0.30 | 354 | — | −$0.30 |
| `SOL→nosis→weave→SOL` | −209 | 342 | 898 | — | −$0.30 | 511 | — | −$0.30 |

(bps except the dollar columns; `W` is the DLMM log-width knob of §2.2, `W=4.0` = no concentration.)

**The whole economic content of the largest standing residual in this cluster is between thirty-seven
cents and ten dollars per loop**, and which it is depends entirely on an unmeasured DLMM
concentration factor. The thin `$433` DREGG/nosis leg contributes `r = W/433`, dominating `Σ r_e` by
two orders of magnitude over the `$57.6k` and `$46.8k` legs. **A thin pool does not create an
arbitrage; it destroys one, by making the loop uneconomic at any size.** That is also the mechanism
by which these residuals persist: nobody is being irrational, the trade is not worth the gas.

---

## 4. RC relaxation: what is measurable, what is free, and the one parameter-free prediction

### 4.1 The time constant

With the capacitor of §2.1 and the behavioural resistor of §2.3, `τ = R·C`. Capacitances add in
**parallel** across venues on the same pair, in **series** along a path between two tokens:

| pair | `C = TVL/4`, parallel-combined |
|---|---|
| nosis/SOL | $14,694 |
| DREGG/SOL | $14,574 |
| weave/SOL | $7,326 |
| SOLVE/SOL | $3,969 |
| weave/nosis | $203 |
| DREGG/nosis | $108 |

Series along the SOL path, against the two half-lives measured in `RESULT_swing_cluster.md`:

| pair | `C_series` | measured `t½` |
|---|---|---|
| DREGG/SOLVE | $3,120 | 7.2 h (n=499, debiased ρ 0.908) |
| weave/nosis | $4,889 | 8.9 h (n=83, "reverting, noisy") |

**What is measurable and what is free.** `C` is measured, exactly, from TVL. `τ` is measured, from
the panel. Therefore `R = τ/C` is **identified, not fitted** — the model has one free parameter and
the data determines it. That is the only defensible sense in which "the measured half-life is an RC
constant": it is a *measurement of R*, given C.

### 4.2 The parameter-free prediction

If a single trading population services the whole cluster, `R` is common across pairs and cancels:

```
    t½(DREGG/SOLVE) / t½(weave/nosis)   ==   C_series(DREGG/SOLVE) / C_series(weave/nosis)
```

with no fitted parameter, both sides independently measured:

```
    predicted   3,120 / 4,889 = 0.638
    measured      7.2 / 8.9   = 0.809
    ratio of ratios              1.27
```

**This is a coincidence-grade check and must be read as one.** One degree of freedom, checked once,
using today's TVL against half-lives fitted over weeks of very different TVL, on a pair the source
study itself called "reverting, noisy" at n=83. It is reported because 1.27 is the kind of number
worth going and testing properly, not because it establishes anything.

**Falsification, stated in advance:** on ≥6 pairs with ≥300 hourly observations each and TVL
averaged over each estimation window, the rank correlation between `C_series` and `t½` must be
significantly positive. If it is not, the RC reading is dead.

### 4.3 Implied response conductance, and its sanity check

```
    1/R = C/τ  =  $0.0834/s per unit log-price     (DREGG/SOLVE)
                  $0.1058/s per unit log-price     (weave/nosis)
```

At a 10% mispricing this predicts **$721–914/day** of restoring flow. Measured 24h volumes are
$26.3k (DREGG, all pools) and $4.5k (SOLVE). So the model implies restoring flow is ~3% of DREGG's
volume and ~16–20% of SOLVE's. **Not falsified, and the check had teeth** — a predicted restoring
flow exceeding total observed volume would have killed the model on the spot, and the numbers were
not chosen to avoid that.

### 4.4 The dead-zone correction, and a new testable prediction about the swing study's own data

Because the fee element is a diode and not a resistor (§2.3), this is not a clean RC circuit. Inside
the band no current flows and the potential is **frozen**; outside it, the potential relaxes at
`τ = RC`. A single AR(1) fitted across a mixed sample is therefore a mixture of a random walk and an
exponential, and is **biased toward ρ = 1**.

**Prediction:** in the swing panel, the AR(1) coefficient of the log-ratio should be *closer to 1*
in the small-|z| subsample and *smaller* in the large-|z| subsample, with the crossover near the
round-trip friction (the swing study puts that at 4–6%). Cheap, uses data already in hand, and does
not require the tape. If ρ is flat in |z|, the reversion is not friction-gated and the diode reading
is wrong.

**But see §8.2 before running it** — the naive version of this test is confounded, and the confound
is the reason to design it carefully rather than a reason to skip it.

---

## 5. The topological result: the one robust pair is not circuit-coupled

`RESULT_swing_cluster.md`'s single surviving finding is DREGG/SOLVE: n=499, debiased ρ 0.908,
half-life 7.2h, "robust reversion". §1 shows **SOLVE has degree 1**. No cycle passes through it. KVL
therefore places no constraint at all on the DREGG/SOLVE ratio, and no arbitrage exists that would
restore it.

**So the 7.2h half-life cannot be an arbitrage relaxation time.** Whatever restores that ratio, it
is not the mechanism this document formalises. Candidates: (a) mean-reverting *demand* — traders who
buy the cheap one because it is cheap, which is still `I = V/R` and still gives `τ = RC`, but with
`R` a preference rather than a no-arbitrage force; or (b) no restoring force at all, the measured
reversion being the thin-pool bid-ask bounce the source study already flagged.

This matters beyond bookkeeping. The desk structure the swing study proposes — seed the SOLVE/DREGG
Meteora pool and rotate inventory through it — would **create the missing edge and close a cycle.**
That is a real, testable intervention: seeding it should induce arbitrage coupling that does not
currently exist, and the model predicts DREGG/SOLVE ratio reversion gets *faster* (smaller τ) once
the pool is funded, because the added edge raises the pair's combined capacitance. It is also the
one action in this document that changes the system rather than measuring it, and should be sized
accordingly.

---

## 6. The energy ledger, exact, on real pools

For `x·y = k` with fee `f`, a trader sending `Δy` of quote receives `Δx = x·Δy(1−f)/(y + Δy(1−f))`,
worth `p₀Δx` at the pre-trade mid. Writing `ρ = Δy(1−f)/y`:

```
    Δy − p₀Δx  =  Δy·[ 1 − (1−f)/(1+ρ) ]  =  f·Δy  +  Δy²/y  + O(3)
```

and the second term is **exactly** the energy stored in the capacitor:

```
    ΔV = 2Δy/y ,   C = y/2   ⟹   ½C(ΔV)² = ½·(y/2)·(2Δy/y)² = Δy²/y .   ∎
```

So the trader's wealth change decomposes with no residual:

```
  trader wealth change  =  −[ f·Δy ]        LP fee — DISSIPATED, gone; this is the LP's income
                          −[ ½C(ΔV)² ]      price impact — STORED in the pool, returned on reverse
                          −[ gas ]          DISSIPATED to validators
```

Verified numerically on every live constant-product pool at a $500 buy (`circuit_model.py ledger`):

| pair | TVL | fee | impact | `½C(ΔV)²` | agree | ΔV |
|---|---|---|---|---|---|---|
| DREGG/SOL | $57,608 | $4.25 | $8.39 | $8.53 | 98.3% | 344 bps |
| nosis/SOL | $46,798 | $6.00 | $10.21 | $10.43 | 97.9% | 422 bps |
| weave/SOL | $27,998 | $6.00 | $16.84 | $17.43 | 96.5% | 706 bps |
| SOLVE/SOL | $15,878 | $6.00 | $28.94 | $30.74 | 93.8% | 1,245 bps |

The 2–6% gap is the third-order term at non-infinitesimal size, and it grows monotonically as the
pool thins — exactly as a truncated expansion must. This is an identity, not a fit.

**For an arb cycle.** The arb ends flat in every intermediate token — that is Kirchhoff's *current*
law, and it is the same condition as Schneider & Lillo's round-trip `∫ẋ dt = 0`. Its profit is the
stored energy it discharges, less what it pays out:

```
    stored EMF energy  =  arb profit  +  Σ fees to LPs  +  gas to validators
```

**"The desk harvests dissipation", stated in SOL.** As an LP, the desk's income is `f × (value routed
through its bins)`, in SOL-equivalent, and it is *irreversible*: unlike impact, it never comes back
to the trader. That is the precise content of the phrase, and it is a claim about a flow. The data
that verifies it:

- **numerator:** on-chain fee-claim transactions on the operator's Meteora positions, summed in
  lamports over a window;
- **denominator:** routed volume through those exact pools over the same window, from the tape;
- **test:** the ratio must equal the pool's configured fee tier, to within rounding.

A closed, falsifiable audit — which simultaneously **measures the DLMM fee tier**, the single
largest unknown in §3, as a by-product. It is the highest-value cheap measurement this study
identifies, and it is already `RESULT_swing_cluster.md`'s "Next #2".

---

## 7. Empirical part 1: the curl right now, and what the instrument can actually resolve

### 7.1 Raw curl (DexScreener last-trade prices, 21:14 UTC)

| cycle | curl | fee band | excess | thinnest leg |
|---|---|---|---|---|
| `DREGG→SOL→nosis→DREGG` | **1,426 bps** | 307 | +1,120 | $433 |
| `DREGG→SOL→DREGG` | **−559 bps** | 186 | +373 | $689 |
| `nosis→SOL→nosis` | 111 bps | 221 | −110 | $11,977 |
| `SOL→nosis→weave→SOL` | −209 bps | 342 | −133 | $812 |
| `weave→SOL→weave` | −66 bps | 221 | −156 | $1,306 |

Two apparent standing EMFs, the larger a 14.3% loop residual on the triangle the brief names. The
three cycles inside the band are the three whose legs all trade.

### 7.2 The control: two aggregators, and a verdict that is not stable

Same pools, same minute (`circuit_model.py crosscheck`, 21:14 UTC):

| pair | dex | DexScreener | GeckoTerminal | disagree | tx m15 | tx h1 | tx h24 |
|---|---|---|---|---|---|---|---|
| DREGG/SOL | pumpswap | 4.836e-06 | 4.839e-06 | +6 bps | 3 | 6 | 601 |
| nosis/SOL | pumpswap | 3.354e-06 | 3.398e-06 | +130 bps | 36 | 183 | 7,084 |
| weave/SOL | pumpswap | 1.826e-06 | 1.855e-06 | +155 bps | 3 | 39 | 3,372 |
| SOLVE/SOL | pumpswap | 5.517e-07 | 5.572e-07 | +100 bps | 1 | 5 | 100 |
| nosis/SOL | DLMM | 3.317e-06 | 3.310e-06 | −20 bps | 3 | 38 | 1,416 |
| weave/SOL | DLMM | 1.838e-06 | 1.855e-06 | +90 bps | 1 | 15 | 278 |
| weave/nosis | DLMM | 0.5559 | 0.5498 | −110 bps | 3 | 9 | 22 |
| DREGG/SOL | DLMM | 5.114e-06 | 5.085e-06 | −57 bps | 0 | **0** | 3 |
| **DREGG/nosis** | DLMM | **1.2502** | **0.7871** | **−4,627 bps** | 0 | **0** | 40 |
| DREGG/Circuit | DYN2 | 2.1293 | 0.4522 | **−15,493 bps** | 0 | **0** | 44 |

**Median |disagreement| 105 bps; maximum 15,493 bps.** Fee bands are 186–342 bps. The same curl from
each source:

| cycle | DexScreener | GeckoTerminal | spread | band | verdict (21:14) | verdict (16:57) |
|---|---|---|---|---|---|---|
| `DREGG→SOL→DREGG` | −559 | −496 | 63 | 186 | **EMF survives both, same sign** | *unresolvable* (spread 233) |
| `nosis→SOL→nosis` | 111 | 261 | 150 | 221 | inside band on one source | inside band on one source |
| `weave→SOL→weave` | −66 | 0 | 66 | 221 | inside band on one source | inside band on one source |
| `DREGG→SOL→nosis→DREGG` | 1,426 | **5,929** | 4,503 | 307 | **unresolvable** | **unresolvable** (spread 4,309) |
| `SOL→nosis→weave→SOL` | −209 | −73 | 136 | 342 | inside band on one source | *unresolvable* (spread 405) |

**Read the last two columns together — that is the finding.** Four hours apart, the same instrument
gives different verdicts on two of five cycles. At 16:57 nothing survived; at 21:14 one cycle did.
The instrument is operating at its resolution limit, and a single-shot "we found a standing arb"
from public quotes is not a measurement.

**What is nevertheless credible, and why.** `DREGG→SOL→DREGG` is a 2-cycle between the $57.6k
PumpSwap pool and the $689 DLMM that has traded **3 times in 24 hours**. By §2.2, a DLMM that has
not traded has not moved its active bin, so its quote is not stale in the way a constant-product
last-trade is — it is a parked battery sitting genuinely 5% off the CFMM price. Both aggregators
agree to 63 bps. This one is probably real, and §3.3 prices it at −$0.18 to +$1.64.

**What is not credible.** `DREGG→SOL→nosis→DREGG` rests on the DREGG/nosis DLMM, where the two
aggregators disagree by **4,627 bps about a pool that neither has seen trade in an hour**. For a
DLMM that is not staleness — it means at least one aggregator is *not reading the active bin*. Until
the active bin is read from chain, that triangle's residual is a statement about aggregator
implementations.

The general diagnosis is structural: **an aggregator quote is a last-trade price, and KVL is a
statement about marginal prices.** For constant product on a pool trading 40 times a day the two are
unrelated at the bps scale the band lives on.

### 7.3 A third channel, and why it also fails — but usefully

DexScreener also returns `liquidity.base` and `liquidity.quote`, and for constant product the
marginal price is exactly `quote/base`. That should be the honest marginal price. It is not:

Measured over all 63 poll samples (mean gap, its stability, and the lead–lag structure):

| pool | mean gap | sd | min / max | corr(Δlog) lag 0 | lag ±1 |
|---|---|---|---|---|---|
| weave/SOL | **−896 bps** | 58.2 | −968 / −835 | +1.00 | −0.08 |
| nosis/SOL | **−493 bps** | 60.0 | −592 / −401 | +0.99 | −0.01 |
| DREGG/SOL | **+103 bps** | 13.3 | +98 / +154 | — (1 move in window) | — |
| SOLVE/SOL | +65 bps | 67.4 | −19 / +119 | — (2 moves in window) | — |

The two channels move in **lockstep** (corr +0.99 to +1.00 at lag 0, no lead-lag at ±1 sample) but
sit at a **persistent multiplicative offset** whose spread over 21 minutes (58–67 bps) is an order of
magnitude smaller than its level (up to 896 bps). It is a bias, not noise. The offset's
magnitude orders with the pool's cumulative turnover, which is what unclaimed fee balances sitting
in the pool token accounts would look like. The consequence is sharp and decides how the field may
be used:

- **Levels are unusable.** An 8.5% bias is an order of magnitude wider than any fee band, so a curl
  built from reserve ratios measures DexScreener's accounting, not the market. (This is visible in
  the tool's `hybrid` price source, which reports *five* cycles outside the band where `last`
  reports two — all of the extra ones are the bias.)
- **Changes are clean.** A constant multiplicative bias cancels *exactly* in first differences, so
  `d log p` from this field is usable — and that is precisely the input the estimator of §10 needs.
  **The channel that fails for §7 is the channel that works for §10.**

**What would fix §7:** read pool state from chain. Constant-product marginal price is `y/x` from the
vault balances; DLMM marginal price is the active bin from the pool account. Both are single RPC
reads and both are exact. Until that exists, **no curl measurement in this cluster should be
believed at better than ~150 bps.**

---

## 8. Empirical part 2: 21 minutes of polling

`circuit_model.py poll --minutes 21 --interval 20`, 2026-08-13 16:48–17:09 UTC, **63 samples,
median spacing 20.0s**. Price source `last` (the `hybrid` rows are dominated by the §7.3 bias and
are reported by the tool but not read as market data).

### 8.1 Distribution

| cycle | n | mean | sd | min | max | band | % outside | ρ | ρ debiased | implied t½ |
|---|---|---|---|---|---|---|---|---|---|---|
| `weave→SOL→weave` | 63 | **+14** | 63 | −49 | 108 | 226 | **0%** | 0.905 | 0.967 | 6.9 m |
| `nosis→SOL→nosis` | 63 | −71 | 145 | −366 | 429 | 226 | **13%** | 0.574 | 0.619 | 0.5 m |
| `SOL→nosis→weave→SOL` | 63 | 148 | 387 | −583 | 707 | 352 | 38% | 0.872 | 0.932 | 3.3 m |
| `DREGG→SOL→nosis→DREGG` | 63 | 846 | 604 | −370 | 1,641 | 317 | 84% | 0.946 | 1.010 | ≥ random walk |
| `DREGG→SOL→DREGG` | 63 | −709 | 167 | −893 | −555 | 191 | 100% | 0.958 | 1.023 | ≥ random walk |

(bps; ρ debiased by the same Kendall correction `(ρ̂ + 1/n)/(1 − 3/n)` the swing study used.)

**The headline is the top row.** `weave→SOL→weave` — the one 2-cycle where *both* legs traded during
the window (3,376 and 278 trades/day) — sat **inside its fee band for all 63 samples**, mean +14 bps
against a 226 bps band, sd 63 bps. That is KVL holding, tightly, for 21 minutes, exactly where the
model says it should. `nosis→SOL→nosis`, the other well-traded 2-cycle, is outside 13% of the time
with mean −71 bps.

The two cycles that are outside the band 84–100% of the time are the two containing the DLMM pools
with 3 and 40 trades/day, and both have debiased ρ ≥ 1 — i.e. **statistically indistinguishable from
a frozen quote**, which is what §8.3 shows they literally are.

### 8.2 Do excursions relax? — and the confound that makes the obvious test worthless

For each cycle, conditioning on `|curl| > band` and measuring the next step's change in `|curl|`:

| cycle | n outside | runs | median run | E[Δ\|C\|] outside | E[Δ\|C\|] inside |
|---|---|---|---|---|---|
| `nosis→SOL→nosis` | 8 | 4 | 40 s | **−125.6** | +22.1 |
| `SOL→nosis→weave→SOL` | 24 | 3 | 40 s | **−54.8** | +36.6 |
| `DREGG→SOL→nosis→DREGG` | 53 | 2 | 530 s | +16.1 | +40.6 |
| `DREGG→SOL→DREGG` | 63 | 1 | 1,260 s (censored) | −5.4 | — |
| `weave→SOL→weave` | 0 | 0 | — | — | −0.3 |

On the two well-traded cycles the sign pattern is exactly what a dead-zone predicts: strongly
restoring outside the band (−125.6 and −54.8 bps per 20s step), mildly *anti*-restoring inside it.

**And that is not evidence, because the test is confounded by construction.** Conditioning on
`|x| > threshold` and looking at the next step produces negative drift for *any* mean-zero
stationary series, restoring force or not — it is regression to the mean, and thin-pool bid-ask
bounce alone manufactures it. The "inside band" column is not a clean control either, since
conditioning on small `|x|` produces positive drift by the same mechanism.

**The discriminating test the dead-zone actually implies** is not a sign difference but a **kink at
the band specifically**: `E[Δ|C|]` should be flat in `|C|` below the band and turn sharply negative
above it, with the break located at `Σf` and nowhere else. That is a threshold-regression question,
it needs hundreds of *informative* samples, and §8.3 shows this window supplied roughly a dozen. It
is stated here so that whoever runs it does not run the confounded version. The same caution applies
verbatim to §4.4's |z|-split of the swing panel.

### 8.3 Why 20-second sampling was ~10–50× oversampled

Fraction of the 62 consecutive sample-pairs in which a pool's price did not change at all:

| pool | frozen |
|---|---|
| nosis/SOL pumpswap | 61% |
| weave/SOL pumpswap | 94% |
| DREGG/SOL pumpswap | 95% |
| weave/nosis DLMM | 95% |
| SOLVE/SOL pumpswap | 97% |
| nosis/SOL DLMM | 90% |
| weave/SOL DLMM, DREGG/SOL DLMM, DREGG/nosis DLMM, DREGG/Circuit | **100%** |

**Four of ten pools did not move once in 21 minutes.** The median pool moved on 5% of steps. So the
63-sample series contains on the order of **10–25 independent price events**, not 63, and every
autocorrelation and half-life in §8.1 should be read against that effective sample size rather than
`n=63`. The implied half-lives of 0.5–6.9 minutes are consistent with quote arrival, not with
economics, and the `≥ random walk` rows are consistent with nothing happening at all.

**This is a design finding for the tape.** Polling a quote at fixed wall-clock intervals on pools
that trade 3–46 times a day mostly samples the *absence* of information. The tape should record
**event-time** (per swap), and any relaxation estimate should be run in event time or on
volume-clock bars. The 20s poll was the right thing to try and the wrong thing to keep.

---

## 9. Empirical part 3: dissipation audit

### 9.1 Turnover — the half of the claim that needs no fee assumption

Fee yield per unit TVL is `turnover × fee_lp`. Turnover is measured; the fee tier is assumed. So
test the claim first on turnover, where nothing is assumed:

| | pair | dex | TVL | vol24 | turnover/day |
|---|---|---|---|---|---|
| | nosis/SOL | DLMM | $11,977 | $156,212 | **1,304.3%** |
| | nosis/SOL | pumpswap | $46,798 | $582,941 | **1,245.7%** |
| | weave/SOL | pumpswap | $27,998 | $176,655 | **631.0%** |
| | weave/SOL | DLMM | $1,306 | $6,163 | **471.9%** |
| **TT** | **DREGG/nosis** | DLMM | $433 | $688 | **159.1%** |
| **TT** | **weave/nosis** | DLMM | $812 | $367 | **45.2%** |
| | DREGG/SOL | pumpswap | $57,608 | $25,544 | 44.3% |
| | SOLVE/SOL | pumpswap | $15,878 | $4,468 | 28.1% |
| **TT** | DREGG/CSR | DYN2 | $15 | $2 | 16.0% |
| | weave/SOL | DLMM | $34 | $3 | 8.5% |
| **TT** | DREGG/Circuit | DYN2 | $663 | $46 | 6.9% |
| | DREGG/SOL | DLMM | $689 | $6 | 0.9% |

```
    token-token   n=4   median turnover    30.6%/day    (range   6.9% – 159.1%)
    token/SOL     n=8   median turnover   258.1%/day    (range   0.9% – 1,304.3%)
```

**Robustness to the liquidity floor** (§3 rule 7 — report the threshold with the number), because
the medians above include pools whose 24h volume is a handful of dollars:

| TVL floor | token-token median | token/SOL median | deficit |
|---|---|---|---|
| $0 (all pools with volume) | 30.6%/d (n=4) | 258.0%/d (n=8) | **8.4×** |
| $100 | 45.2%/d (n=3) | 471.9%/d (n=7) | **10.4×** |
| $400 | 45.2%/d (n=3) | 471.9%/d (n=7) | **10.4×** |

Dropping the dust pools makes the gap **worse**, not better. The conclusion does not depend on where
the threshold is set, which is the only reason it is worth stating at n=4.

**The swing study's structural claim is falsified on turnover.** Token-token pools do *not* have
structurally higher throughput per unit TVL; they have **8.4× less**. The DREGG/nosis pool the study
singled out (159%/day, the source of its "159%/day → several %/day on capital" argument) is the best
token-token pool in the cluster and is still beaten by four token/SOL pools, the top one by 8×.

For token-token LP to win on gross fee income per unit TVL, its fee tier must exceed the token/SOL
LP tier by **8.4× to 10.4×**. Against a PumpSwap LP leg of 0.20%, that requires a DLMM tier of
**1.7% to 2.1%**. Not impossible — DLMM tiers do reach that on volatile pairs — but it is now a
specific checkable number rather than an impression, and §6's fee-claim audit measures it directly.

**What the swing study got right, and where its arithmetic went.** Its 159%/day figure for
DREGG/nosis is confirmed exactly. What was missing was the comparison: it never computed the same
statistic for the token/SOL pools, and those are an order of magnitude higher. The conclusion
"mechanically confirmed" applied to the wrong quantity — turnover was confirmed, superiority was not
tested.

### 9.2 Three things this table does not settle, each of which moves the answer

- **DLMM concentration (§2.2).** A concentrated position's `$1` of TVL is `4/W ≈ 5–20×` the depth of
  `$1` of constant product. Yield-per-TVL flatters DLMM by exactly that factor, and it is unmeasured
  here. This works *in favour* of the token-token thesis and could plausibly cover the 8.4× gap on
  its own. **This single unmeasured number decides the question** — which is a reason to measure it,
  not a reason to believe either side. Note it also partly cuts the other way: three of the four
  highest-turnover pools are themselves DLMMs.
- **Impermanent loss.** The swing study's actual argument is that IL is *temporary* on a
  mean-reverting ratio. That is a claim about the sign of IL over a cycle, not about fee income, and
  nothing here tests it. §5 has already weakened its foundation for the one pair it was measured on.
- **Sampling.** 24h volume on pools doing 22–46 trades/day is one draw of a heavy-tailed variable.

### 9.3 An independent estimator of the creator fee rate

The fee band depends on the PumpSwap creator leg, which PROGRAM.md §0 gives as an inverse-FDV ladder
(0.95% / 0.60% / 0.35%) against a widely-quoted flat 0.05%. Creator fees are a fixed rate on volume,
so the operator's own income divided by measured volume estimates the rate:

```
    DREGG 24h volume, all pools, measured:      $26,300
    operator DREGG creator income (PROGRAM §0):  $213 – $313/day
    implied rate                              =  0.81% – 1.19%

        0.05%  (flat)                → EXCLUDED
        0.60%  (ladder, FDV > $300k) → EXCLUDED
        0.95%  (ladder, FDV < $300k) → CONSISTENT
```

**Crude, and offered as crude:** the two figures are from different days and DREGG volume is
heavy-tailed. It separates 0.05% from ~1% and nothing finer. But that is the discrimination that
matters — a 19× difference in the dominant term of every fee band in §3 — and the desk's own income
statement resolves it. A pleasing side effect: the desk's P&L is an instrument.

---

## 10. The estimator the swap-level tape will enable

### 10.1 The specification, and why this problem is not the literature's problem

At `N = 4` tokens plus SOL, over bars of length `Δt`, with `dQ` the signed value flow into each pool
and `dP` the vector of log-price changes:

```
    dP_t  =  L · dQ_t  +  ε_t
```

Two things make this a *different* problem from every paper in the reading list, and both should be
said before any estimation happens.

**(i) `L` is not an estimand at short lag — it is known.** In an equity market the impact matrix must
be inferred because the mechanism is hidden. Here the mechanism is the pool, and §2 gives the answer
in closed form. At `Δt` short enough that no arbitrage has acted, a swap moves *only its own pool*:

```
    L(Δt → 0)  =  diag(1/C_e)  =  diag(4/TVL_e)   in POOL space,   and cross-impact is EXACTLY ZERO.
```

**(ii) The Laplacian appears only after relaxation.** Once arbitrage has restored KVL, log-prices
become genuine node potentials and an injection at node `i` distributes across the network as a
resistive current divider:

```
    V  =  𝓛⁺ J ,        𝓛 = graph Laplacian with edge conductances g_e ,   J = injection vector
```

So **cross-impact in an AMM network is entirely the arbitrageurs' doing**, and the estimation target
is not "the impact matrix" but *the relaxation from `diag` to `𝓛⁺`, and its time constant*. That is
a sharper and more falsifiable object than a dense `L`, and it is only visible with swap-level
timestamps — exactly what the tape provides and what hourly OHLCV cannot.

**A prediction that falls out and is testable on the tape alone:** the estimated off-diagonal of `L`
must be **zero at the shortest bar** and grow with `Δt` toward the Laplacian prediction, crossing
over at `τ = RC` from §4. If off-diagonals are non-zero at the single-swap bar, they are not
propagation — because §10.1(i) makes non-atomic instantaneous propagation *mechanically impossible*.
Which brings us to the confound.

### 10.2 The Capponi–Cont confound, applied to us

Their warning transfers exactly, and their own numbers set the bar. Verbatim, §3.2:

> "the mere presence of statistically significant off-diagonal terms in β does not provide a causal
> justification for the existence of cross-impact. Since the correlation in order flows has not been
> taken into account, these coefficients cannot be interpreted as evidence of cross-impact."

What happened when they tested it (§3.2–3.4, all grep-verified against the source):

- Naive spec: mean diagonal **2.64**, mean off-diagonal **0.032** — off-diagonals **1.2%** of the
  diagonal — yet **58.7% of 4,422** off-diagonals significant at 1%, and the joint F-test rejected
  for **all 67** stocks. Significance was abundant and meaningless.
- A single common factor explained **28.27%** of 1-minute order-flow-imbalance variance, correlated
  **87.26%** with the first return factor.
- After purging it: adjusted R² rose **43.31% → 43.84%**, i.e. **+0.5pp**, while parameters went
  **134 → 4,489**. And **84.46%** of off-diagonals flipped sign to negative, up from 23.09%.
- Rolling windows: "the cross-impact coefficient is unstable and changes sign randomly through time."

**Our exposure is worse than theirs, for four cluster-specific reasons.** (a) `N=5` on *one community
cluster* means flow commonality is near-total — these four tokens share a holder base by
construction, and the swing study's hourly return correlations of 0.11–0.24 were explicitly a floor.
(b) A single SOL price move mechanically moves all four token/SOL pools' USD prices: a common factor
with a *known* mechanism, which must be projected out before anything else. (c) Their one-factor
assumption is asserted, not tested, and they never check whether PC2/PC3 kill the residual
off-diagonals; at `N=5` we cannot afford that gap. (d) **Arbitrageurs' own flow appears
simultaneously on both sides of the regression** — an arb trade is a `dQ` in two pools and a `dP` in
two pools, in the same transaction — manufacturing off-diagonal correlation with no propagation
whatsoever.

Point (d) is not in their paper and is the dominant confound here. **The mitigation is exact and
available only to us: same-transaction multi-pool swaps are identifiable on chain**, so atomic arb
legs can be tagged and either excluded or entered as a separate regressor. Cleaner than anything
observational, and it exists because we have transaction-level ground truth.

**Protocol to copy verbatim, with their numbers as the benchmark:** PCA the flow correlation matrix
and report the first-eigenvalue share; regress each token's flow on PC1 (their Eq. 26); regress
returns on PC1 + own residual + all others' residuals (Eq. 27) against the nested own-residual-plus-
PC1 model (Eq. 28); report the **adjusted-R² delta** and the **parameter-count ratio**; report the
fraction of off-diagonals that **flip sign** between specs; re-run on rolling sub-samples and check
sign stability.

### 10.3 The identification we have and they did not

Capponi & Cont propose **no** instrument, no exogenous flow, no natural experiment, and no randomised
design — their entire remedy is conditioning on an observed common factor. (Checked directly: the
words `instrument`, `exogen`, `natural experiment`, `randomi[sz]` do not appear in the paper in any
relevant sense.) Conditioning on a factor estimated from the same data is weaker than an experiment,
and they concede as much implicitly by leaving `cov(ε, OFI) = 0` an untested assumption.

**We can run the experiment.** PROGRAM.md §5 already requires every desk action to be
propensity-logged with the policy state that generated it, and the scalper already ε-explores. That
makes our own entries **randomised injections of known size, at known times, with a known
propensity** — an instrument in the textbook sense.

**The design:**

1. **Injection.** On each eligible decision, with probability `ε`, execute a dust-sized swap into a
   randomly chosen cluster pool `e`, size drawn from a fixed distribution, *independent of any
   signal*. Log `(t, e, size, ε, policy_state)` at decision time — not after; none of it is
   reconstructible later.
2. **Exclusion restriction, and why it holds.** The randomisation is by construction independent of
   every token's fundamentals and of other traders' flow. This is the assumption Capponi & Cont must
   make and cannot test; ours is true because we generated the randomness.
3. **First stage.** `dQ_e` responds to the injection one-for-one, exactly, without estimation — we
   know the size we sent. The first stage is not weak; it is an identity.
4. **Reduced form.** Measure `dP_j(t + h)` for every token `j ≠ e` and every horizon `h`, against
   hour-matched non-injection controls. The `h`-profile *is* the relaxation curve of §10.1, and its
   time constant is a second, independent measurement of `τ = RC` — one that does not depend on the
   AR(1) fit §4 leans on, and can therefore falsify it.
5. **The two-sided test.** Zero response at `h → 0`, growing toward the Laplacian prediction at
   `h ≫ τ`, confirms the model. A response at `h → 0` falsifies it — because §10.1 makes
   instantaneous non-atomic propagation mechanically impossible, so any such response is leakage in
   the measurement, not physics.
6. **Power, honestly, and this gate is not optional.** The injection must be dust (PROGRAM.md §5's
   envelope caps bind), so the response is small. The required `n` must be computed from the pools'
   measured minute-scale volatility **before** spending anything — the same feasibility gate
   PROGRAM.md §4.1 imposes on the SVN signal after that lane's power claim collapsed under
   arithmetic. **This gate has not been computed and this experiment is not ready to run.**
   §8.3 sharpens why: on pools that print 3–46 times a day, the number of *informative* observations
   per unit wall-clock is one to two orders of magnitude below the number of samples.
7. **Both controls (§3 rule 12).** A known-zero world: **inject into SOLVE/SOL.** §5 establishes
   SOLVE is a genuine graph leaf, so the model's own mechanics require zero cross-response; if one
   appears, the estimator is broken. And a known-effect world: inject into a pool on a live cycle,
   where §2's algebra predicts the response *quantitatively*, not merely in sign.

Item 7 is the payoff of §5: **the topology hands this experiment a free negative control that exists
in nature**, costs nothing extra, and would not have been visible without drawing the graph.

---

## 11. Prior art: what each paper actually licenses

All three were read in full and every quote below was grep-verified against the source `.txt`.

### Tomas, Mastromatteo & Benzaquen — *How to build a cross-impact model from first principles*

**The brief claimed** their liquidity-weighted construction "is essentially the conductance matrix."
**Demoted, with the useful part kept.**

Their "liquidity" is `Ω = Cov(q)`, the **order-flow covariance** — realised trading activity — not
pool depth and not fee. Nothing in the paper licenses reading `Ω` as a function of depth. The words
*graph, network, Laplacian, circuit, conductance, node, edge, Kirchhoff* appear **zero** times.

What it does license — and it is exactly the four properties a conductance matrix needs:

- **Symmetry** (Axiom 7), forced by absence of dynamic arbitrage: "Axioms 6 and 7 together are
  sufficient to guarantee absence of statistical arbitrages."
- **Positive semi-definiteness** (Axiom 6), because `E[C(ξ)] = ξᵀΛξ` is the expected cost of trading
  portfolio `ξ` — so PSD ⟺ no negative-cost trade.
- **A liquidity-congruence normal form.** In the proof of Prop. 3.1, with `Ω = LLᵀ`:
  `Λ = L^{−T} √(Lᵀ Σ L) L^{−1}` — a two-sided normalisation by the square root of the liquidity
  matrix. Prop. 3.1: a symmetric, PSD, covariance-consistent cross-impact model is `Λ_kyle` up to a
  constant. **This is the structural claim to cite, and only this.**
- **Divergence as liquidity vanishes:** Lemma A.4 gives `‖Π_V Λ_kyle Π_V‖ = ε^{−1}‖…‖ → ∞`.

**The honest statement:** the circuit/Laplacian reading is *ours*. What they establish is that any
no-arbitrage cross-impact matrix must be symmetric, PSD, and a congruence by the square root of a
liquidity matrix — the algebraic signature of a weighted graph Laplacian, and exactly the signature
`𝓛` has in §10.1. **The correspondence is one of properties, not of objects.** Their warning
transfers too, and it constrains §10: "a pure no-arbitrage framework … is not sufficiently
restrictive to prescribe a calibration methodology." KVL alone will not pin down `L`.

### Schneider & Lillo — *Cross-impact and no-dynamic-arbitrage*

**The brief claimed** no-arb constraints on impact = the KVL constraint. **Upheld structurally, with
the language flagged as ours.**

Their round-trip condition is a closed loop: a strategy with `∫₀ᵀ ẋ dt = 0` must have `C(Π) ≥ 0`
(Eqs. 4–5, 7). Example 3.8 constructs an explicit three-phase closed loop whose cost is
`C(Π) = (T²/18)·vᵃvᵇ(η^{ba} − η^{ab})` — **the loop's cost is exactly its antisymmetric part, i.e.
its circulation** — and Lemma 3.9 concludes `η^{ij} = η^{ji} ∀ i,j`. That is a curl-vanishing
condition in everything but name. *Kirchhoff, circuit, electrical* appear **zero** times (grepped):
the potential-theoretic reading is our contribution, and the analogy is structural rather than
borrowed.

**Their empirical conclusion is our result, in a different market** — the strongest external
corroboration in this document:

> "violations of the no-arbitrage conditions related to impact symmetry, these are unprofitable
> because of slippage costs such as the bid-ask spread which are neglected"

quantified at `C^cross/C^slippage ~ 1·10⁻⁴` at short horizon and `~0.005` at `T=100`. §3.3 and §7
find the same on Solana AMMs: **the violations are real and the money is not there.** Two unrelated
markets, two unrelated instruments, same verdict.

Two things they state that we inherit. Their constraints are **necessary, not sufficient** ("The
conditions of linearity and symmetry of cross-impact are necessary for absence of arbitrage, but are
they also sufficient?" — answered no). And an exception directly relevant to §10.1: asymmetric
cross-impact is arbitrage-free if the kernel vanishes at zero lag — which is precisely the AMM case,
where cross-impact **is** exactly zero at zero lag. Their exception is our theorem.

### Capponi & Cont — *Multi-asset market impact and order flow commonality*

Fully applied in §10.2. The sentence that governs our estimator:

> "The mere presence of positive covariation between the returns of an asset and the order flow of
> another asset is not sufficient to provide a causal justification for the existence of cross-impact
> as a separate phenomenon from, for example, correlation between the order flow of the two assets."

Their remedy is observational (PCA-purge the flow common factor). §10.3 is strictly stronger, and the
reason is not cleverness — it is that we generate the randomness ourselves.

---

## 12. Falsifiable claims, each with its falsification

| # | Claim | Falsified by | Status |
|---|---|---|---|
| 1 | `C = w_x w_y·TVL` exactly for a geometric-mean CFMM | Any pool where `½C(ΔV)²` fails to match brute-force impact cost as size → 0 | Verified to 6 s.f. symbolically-numerically; 93.8–98.2% at $500 with the gap growing as pools thin, i.e. the third-order term |
| 2 | A DLMM's `C` is `T/W`, `4/W`× a CFMM of equal TVL | Reading the active bin + bin-liquidity array on chain and finding depth-at-mid inconsistent with `T/W` | **Untested — needs chain reads** |
| 3 | Band edges are `Σ ln(1/(1−f_e))` at zero size, `+√(2G Σr_e)` at economic size | An executed cycle arb profiting at a curl inside the computed band | Derived; not adversarially tested |
| 4 | `t½` ∝ `C_series` at common `R` across pairs | Rank correlation of `C_series` vs `t½` not significantly positive over ≥6 pairs at ≥300 hourly obs, TVL averaged over window | **1 d.o.f., checked once, ratio-of-ratios 1.27 — coincidence-grade** |
| 5 | Reversion is friction-gated: `E[Δ\|C\|]` has a kink **at the band** | No kink at `Σf` in a threshold regression | Sign pattern present (§8.2) but the naive test is confounded; needs the kink version |
| 6 | Cross-impact is exactly zero at the single-swap bar; off-diagonals grow with `Δt` toward `𝓛⁺` | Non-zero off-diagonal `L` at single-swap resolution after excluding same-transaction atomic routes | **Untested — needs the tape** |
| 7 | Injecting into SOLVE/SOL produces zero cross-response (leaf node) | Any measured cross-response — which indicts the estimator, not the market | **Untested — needs the experiment** |
| 8 | Token-token LP beats token/SOL per unit TVL | Median turnover comparison | **FALSIFIED on turnover: 30.6% vs 258.1%/day, an 8.4× deficit (10.4× above a $100 TVL floor).** Survives only if `4/W > 8.4`, measurable and unmeasured |
| 9 | PumpSwap creator fee is ~0.95%, not 0.05% | Fee-claim transactions summed against routed volume | Implied 0.81–1.19%; excludes 0.05% and 0.60%. Crude |
| 10 | Seeding SOLVE/DREGG closes a cycle and *speeds up* DREGG/SOLVE reversion | Post-seeding `t½` not decreasing | **Untested — the one claim requiring an intervention** |

---

## 13. What is demoted to analogy, explicitly

The brief asked for each correspondence to be exact or explicitly demoted. Kept honest:

- **"Exogenous order flow = EMF injection."** **Analogy.** There is no conserved quantity making an
  uninformed buy an electromotive force; it is a charge injection at a node. Evocative, but nothing
  derivable follows from the EMF label that does not follow from "charge injection".
- **"Fees = `I²R` dissipation."** **Wrong as stated; corrected in §2.3.** Dissipation is linear in
  |flow|, not quadratic in a rate. The element is a diode pair, not a resistor. The LP still
  harvests the dissipation — that part stands, and §6 makes it exact — but the functional form is
  different, and the difference is precisely what produces a no-trade band.
- **"Conductance ≈ f(liquidity, fee)."** **Wrong as stated; corrected in §2.3.** Liquidity sets
  capacitance; fee sets a diode drop; the only real resistance is behavioural. Merging them into one
  "conductance" conflates a reversible element with an irreversible one, and the entire §6 ledger
  depends on keeping them apart.
- **"The measured half-life is an RC constant."** **Half-demoted.** It is `τ = RC` with `C` measured
  and `R` behavioural — but for DREGG/SOLVE specifically, §5 shows there is **no cycle**, so the
  restoring force cannot be arbitrage. It is mean-reverting demand, which obeys the same algebra for
  a different reason. The distinction matters the moment anyone predicts the effect of adding a pool.
- **"Onsager matrix."** **Deliberately not used as a claim.** Onsager reciprocity is a
  fluctuation–dissipation result requiring microscopic reversibility. What §10 has is a symmetric PSD
  response matrix forced by *no-arbitrage* (Tomas Axioms 6–7; Schneider–Lillo Lemma 3.9). Symmetry
  from no-arbitrage is not symmetry from detailed balance, and the two should not be run together
  merely because both yield a symmetric matrix. §10 says "linear response", which is all that is
  earned.

---

## 14. What to do next, in cost order

1. **Design and run the kink version of claim #5** on the swing panel already in hand — zero new
   data, zero API calls. §8.2 shows why the naive version is worthless; the threshold-regression
   version discriminates the diode reading from ordinary mean reversion.
2. **On-chain pool state in the tape** (§7.3): vault balances for constant product, active bin for
   DLMM. One RPC read per pool, and it is what makes the curl measurable at all. Without it, §7's
   ceiling of ~150 bps stands and the DREGG/nosis triangle is permanently unresolvable.
3. **Record in event time, not wall-clock time** (§8.3). Four of ten pools did not move once in 21
   minutes; fixed-interval polling mostly samples the absence of information.
4. **The fee-claim audit** (§6): verifies "the desk harvests dissipation" as a number *and* measures
   the DLMM fee tier — the largest unknown in every band in §3.
5. **Measure `4/W` on the operator's own positions.** §9.2 shows this single number decides the
   token-token LP question, and it is a read of the operator's own accounts.
6. **Compute the injection experiment's power gate before running it** (§10.3 item 6). PROGRAM.md
   §4.1 is a standing lesson about exactly this, and it was paid for once already.
