# RESULT: which pools should exist — deliberate edge creation, measured

2026-08-14. Instrument: `studies/edge_creation.py` (`python studies/edge_creation.py all`).
Ground truth is chain: pool vaults via `getTokenAccountsByOwner` across **both** SPL token
programs, Meteora fee tiers decoded out of the `LbPair` account, and every LP position
reconstructed from its own pool's full transaction history. Prices are GeckoTerminal minute
bars. Flow classification is from `state/cluster_tape/` **and**, independently and better, from
each pool's own on-chain history.

PROGRAM.md §8 asks for "deliberate edge creation": place a pool between two communities lacking
a low-resistance path and become the monopolist wire on a route flow wants to take. This study
tried to turn that into a method and **the method inverted the premise.** The sentence is wrong
in this cluster in a way that is more useful than a confirmation would have been.

---

## 0. What this found, in seven lines

1. **There is no route.** Across all seven token-token pools the desk has ever opened — **593
   swaps** of full on-chain history — **exactly one** was a genuine direct A↔B trade. 84.5% were
   closed arbitrage cycles; 15.3% were a SOL↔token route using the pool as a leg. Direct
   user demand for a token-token wire in this cluster is **0.17% of transactions** and, in the
   tape's own units, **0.04 SOL over 30 hours**.
2. **It could not have been otherwise, and the arithmetic was available in advance.** The two-hop
   route A→SOL→B costs **2.12–2.88%** all-in. The desk's token-token tiers are **5.00–6.00%**
   (decoded on chain, not assumed). A direct pool at the desk's tier is **1.7–2.8× more
   expensive than the route it would replace.** No cost-minimising router will ever prefer it.
   The desk was never selling a cheaper wire.
3. **What it is actually selling is a toll on a cycle it closed.** A new edge does not attract
   A↔B demand; it creates a *loop*, and the loop must be kept consistent by arbitrage. The LP
   is paid the diode forward-drop on every band crossing. That is the real product, it is
   direction-indifferent and prediction-free, and it is exactly PROGRAM.md §8's "own the
   junctions" — but the mechanism is not the one §8 names.
4. **The whole cluster is already wired.** Of the six pairs among {weave, nosis, DREGG, SOLVE},
   **five have pools** and only **nosis/SOLVE is genuinely missing**. Three of the five are
   dead one-sided husks — an edge that exists but conducts one way. In the circuit frame that
   is not a metaphor: capacitance on the drained side is zero, so it is an **open circuit**.
5. **The ranking statistic is parameter-free and needs no pairwise history.** Measured on all
   six pairs, `σ_AB / √(σ_A² + σ_B²) ∈ [0.927, 1.024]` — these tokens are near-independent
   (implied ρ −0.05 to +0.20, which independently reproduces RESULT_swing_cluster.md's 0.11–0.24).
   So **an edge's earning power is set by its loudest endpoint**, computable from single-token
   volatility alone. Turnover ranks by `σ²/band`: **Spearman 0.829 on n=6** against measured
   turnover, versus 0.500 for `σ²` alone.
6. **The DREGG/nosis post-mortem reproduces to −$215.63** from chain (the operator's −$214, to
   the dollar) and it does **not** decompose the way the folk story says. The pool was not a bad
   wire: **per hour in service** it harvested **67.6%/day**, *more* than weave/nosis's 57.6%. It
   died of **range exit** — flow stopped 1.88 h before the close, a **49.4% duty cycle**, while
   the ratio kept moving against it the whole time.
7. **And the uncomfortable one.** Across **10 closed positions**, ~50 hours of operation and
   **$879 of harvested fees**, the desk's token-token edge programme is **−$130.80 net** and
   **−$595.14 against simply holding the deposited baskets**. 6 of 10 beat HODL; the aggregate
   did not. The "31.6%/day harvest" is real and it is not the same statement as "this made money."

Reproduce: `python studies/edge_creation.py all`.

---

## 1. The graph, from chain, at 2026-08-14 03:5x UTC

Both aggregators lag and both misreport. DexScreener omitted the SOLVE/DREGG pool and one of the
two weave/DREGG pools entirely. GeckoTerminal reports `$444.96` of reserve in DREGG/nosis whose
nosis vault reads **exactly zero**. And the pump.fun mints are **Token-2022** while the SOL side
is classic SPL, so a `getTokenAccountsByOwner` query against one program returns exactly half of
every pool — which reads as a one-sided pool and is wrong in the most misleading available
direction. `graph` queries both programs.

| pair | venue | fee (decoded) | vault A | vault B | pool |
|---|---|---|---|---|---|
| nosis/SOL | pumpswap | 1.44% | SOL 375.8 | nosis 76,807,872 | `7nv2RtGX…` |
| DREGG/SOL | pumpswap | 1.44% | DREGG 79,785,500 | SOL 369.5 | `2XHrhkxf…` |
| weave/SOL | pumpswap | 1.44% | SOL 189.7 | weave 98,293,406 | `GA1nQL5R…` |
| nosis/SOL | meteora | 2.00% | SOL 166.6 | nosis 12,742,788 | `C889ex3M…` |
| SOLVE/SOL | pumpswap | 1.44% | SOL 97.3 | SOLVE 201,922,042 | `BQHANwBn…` |
| weave/nosis | meteora | **6.00%** | nosis 17,798.8 | weave 65,879.9 | `QQnW4Zw3…` |
| weave/SOL | meteora | 2.00% | SOL 7.2 | weave 80,681 | `77Nm2cKt…` |
| weave/DREGG **B** | meteora | **0.20%** | DREGG 317.8 | weave 1,336.0 | `A8ga6XM3…` |
| **weave/nosis #2** | meteora | **6.00%** | nosis 637,716 | weave 1,400,345 | `5fJBZY6h…` |
| SOLVE/DREGG | meteora | 5.00% | DREGG 9,002 | **SOLVE 0** | `HE9UXD4a…` |
| DREGG/nosis | meteora | 5.00% | DREGG 10,889 | **nosis 0** | `FNxnyS3h…` |
| **weave/SOLVE** | meteora | **5.00%** | SOLVE 1,760,263 | weave 249,640 | `9M1oU7cv…` |
| weave/DREGG **A** | meteora | 5.00% | DREGG 197,860 | **weave 0** | `GxnCwxTi…` |

**Four of these are not in `shitcoims_cluster/pools.py`** and the collector is not watching them:
`5fJBZY6h`, `9M1oU7cv`, `A8ga6XM3`, `GxnCwxTi`. Three are edges the desk provides liquidity to.
That is the same blind spot commit `3c7b49b` fixed for `77Nm2cKt`, recurring — and it recurs
because the desk opens pools faster than the universe table is edited. **This is a defect, not a
finding**, and it is the cheapest thing in this document to fix.

**The 26-minute burst.** At **02:18:32** the desk closed weave/nosis `QQnW4Zw3`. At **02:28** it
re-funded the small weave/SOL DLMM. At **02:40:12** it opened a *second* weave/nosis pool
`5fJBZY6h` at the same 6.00% tier. At **02:44:12** it opened **weave/SOLVE `9M1oU7cv`**
(`initializeLbPair2` + `initializePosition`, 294,117 weave + 1,560,397 SOLVE ≈ $106). Neither
aggregator had indexed weave/SOLVE ~45 minutes later; it was found by walking the fund wallet.

**Degrees (both vault sides funded):** weave 5, SOL 4, DREGG 3, **nosis 2**, **SOLVE 2**.
The prompt's claim is confirmed exactly: weave/SOLVE took SOLVE from degree 1 to degree 2 and
closed the triangle `weave → SOLVE → SOL → weave`. RESULT_circuit_model.md §5's negative control
("SOLVE has degree 1, no cycle passes through it, so the 7.2 h DREGG/SOLVE half-life cannot be an
arbitrage RC constant") **has now been consumed by the operator's own action** — §5 should be
annotated: the free negative control expired at 02:44 UTC on 2026-08-14.

### The missing edge

| pair | state |
|---|---|
| nosis/weave | live (two pools, 6.00%) |
| weave/SOLVE | live (opened 02:44) |
| DREGG/weave | live at 0.20% (`A8ga6XM3`), dead at 5.00% (`GxnCwxTi`) |
| DREGG/nosis | **dead** — one-sided |
| DREGG/SOLVE | **dead** — one-sided |
| **nosis/SOLVE** | **MISSING — the only unbuilt edge in the cluster** |

Every dead edge has the same shape: **all DREGG, no counterparty token.** DREGG/nosis holds
10,889 DREGG and 0 nosis. SOLVE/DREGG holds 9,002 DREGG and 0 SOLVE. weave/DREGG A holds 197,860
DREGG and 0 weave. Every pool the desk opened pairing DREGG against a cluster token ended as a
100% DREGG holding. That is one fact stated three times: **over this window DREGG fell against
everything in its own cluster, and every edge the desk built was the ramp it fell down.**

---

## 2. Who actually crosses a token-token edge

The classification: for each swap through pool A/B, count how many **token/SOL** pools the *same
transaction* touched. Two or more closes a cycle — the trader ends flat in every token, which is
Kirchhoff's current law and Schneider & Lillo's round-trip condition — so it is an arbitrageur.
Exactly one makes A/B a leg of a SOL↔token route. Zero is a genuine A↔B trade.

Full on-chain history of every desk token-token pool:

| pool | n | CYCLE | LEG | DIRECT |
|---|---|---|---|---|
| weave/DREGG A | 372 | 321 (86.3%) | 50 (13.4%) | **1 (0.3%)** |
| weave/DREGG B (0.20%) | 32 | 21 (65.6%) | 11 (34.4%) | 0 |
| SOLVE/DREGG | 24 | 23 (95.8%) | 1 (4.2%) | 0 |
| DREGG/nosis | 46 | 39 (84.8%) | 7 (15.2%) | 0 |
| weave/nosis | 96 | 78 (81.2%) | 18 (18.8%) | 0 |
| weave/nosis #2 | 19 | 15 (78.9%) | 4 (21.1%) | 0 |
| weave/SOLVE (40 min old) | 4 | **4 (100%)** | 0 | 0 |
| **total** | **593** | **501 (84.5%)** | **91 (15.3%)** | **1 (0.17%)** |

The tape agrees where it overlaps and is *worse*: it reports 3 DIRECT on weave/nosis where chain
reports 0, because the poller can miss the sibling leg of an atomic route and orphan the row. So
the tape's DIRECT column is an upper bound, and even the upper bound is ~zero.

**The independent confirmation, and it is the cleanest evidence in this study.** `A8ga6XM3` is a
weave/DREGG pool at a **0.20%** fee — eleven times cheaper than the two-hop route, and the only
price at which the "monopolist wire" story could be true. It has both sides funded. It has done
**$0 of volume in the last 24 hours**. In its one active hour it took 32 swaps, and **21 of them
were arbitrage cycles and 11 were routing legs — zero direct.** A pool priced to win every A↔B
trade in the cluster captured none, because there were none to capture.

**The revealed two-hop demand, measured the way the brief asked.** Over 30 hours of tape,
2,807 transactions, the atomic multi-pool routes decompose to: **75.2 SOL** traversing closed
cycles, **3.65 SOL** of SOL↔token routes using a token-token pool as a leg, and **0.04 SOL** —
one transaction — going token→SOL→token. That last number *is* the revealed demand for a direct
route between two cluster tokens. At $76/SOL it is about **two or three dollars a day**.

---

## 3. The post-mortem: DREGG/nosis vs weave/nosis

Both from chain, both complete, and they are a near-perfect natural experiment: the desk closed
DREGG/nosis at **17:31:03** and opened weave/nosis at **17:46:38**, fifteen minutes later, with
recycled capital.

### DREGG/nosis (`FNxnyS3h`), 13:36:13 → 17:31:03, 3.91 h

```
13:31:57  initializeLbPair2                     pool created
13:36:13  addLiquidityByStrategy2      621,928 nosis + 977,570 DREGG     $616.75
15:00:31  claimFee2                     55,447 DREGG                      $18.80
15:38:42  last swap                     <- flow stops here, 1.88 h before close
16:07:17  claimFee2                     44,361 DREGG                      $15.64
17:31:03  removeLiquidityByRange2    1,632,183 nosis +       0 DREGG     $365.70
                                                                 -------------
                                            net                        −$215.63
```

The operator's figure was −$214; this reconstruction gives **−$215.63**. Decomposed:

| component | $ | what it is |
|---|---|---|
| HODL counterfactual | **−$123.57** | the basket fell 20% — would have happened holding |
| fees harvested | **+$35.42** | **67.6%/day** per hour in service; **35.3%/day** over the position's life |
| divergence | **−$127.48** | the LP structure, on a ratio that moved −60.2 log-% |
| **LP vs HODL** | **−$92.06** | what the *pool* cost, over and above the market |

Fee coverage — fees ÷ divergence — was **0.28**.

### weave/nosis (`QQnW4Zw3`), 17:46:38 → 02:18:32, 8.53 h

| | |
|---|---|
| deposit | 1,842,745 nosis + 2,309,235 weave = **$726.84** |
| fees (6 claims; the last split out of the bundled close: 58,670 weave = $9.23) | **+$147.98** |
| withdrawal (principal only) | 103,096 nosis + 5,882,401 weave = **$970.22** |
| **net** | **+$391.36** |
| HODL counterfactual | **+$430.99** |
| **LP vs HODL** | **−$39.63** |
| fee coverage | **0.79** |

### The diagnosis, and it is not the one everyone tells

**Both positions lost to HODL.** weave/nosis "worked" because weave and nosis both rose 59% as a
basket while the pool was open; DREGG/nosis "failed" because its basket fell 20%. That is
*market direction*, not edge quality, and it is not a decision the desk made when it chose the
endpoints.

Three candidate explanations, tested:

- **"DREGG/nosis had no flow."** *False, and it is the reverse.* It turned over **1,396%/day**
  against weave/nosis's **892%/day**, and **per hour in service** it harvested **67.6%/day**
  against weave/nosis's **57.6%/day**. It was the *better* wire on both counts. What it realised
  over its life was **35.3%/day** against **57.3%/day** — and the entire gap is the 49.4% duty
  cycle. Same fee tier region, same counterparty token, better flow per hour, half the hours.
- **"weave/nosis reverts and DREGG/nosis trends."** *False.* Both trended hard. The ratio moved
  −60.2 log-% (DREGG/nosis) and −50.8 log-% (weave/nosis). Against their measured σ (92.7% and
  95.9% per √day) those are **1.6σ and 0.9σ** moves. The realised difference between the
  "success" and the "failure" is **less than one standard deviation of the same variable.**
- **"DREGG/nosis range-exited and stopped earning."** *True, and observed as a sequence rather
  than inferred from a correlation.* The pool's last swap was at **15:38:42**; the position was
  closed at **17:31:03**. For **1.88 h — 48% of its life — the pool took zero flow while the
  ratio kept moving against it.** Duty cycle **49.4%**, against weave/nosis's **99.4%**.

That is the mechanism, and it is exactly the circuit frame taken literally: a DLMM whose
liquidity has all converted to one token has **C = 0** on the drained side (RESULT_circuit_model
§2.2 — capacitance is infinite inside a bin and zero at an edge). It is not a high-resistance
wire. It is an **open circuit**. Fee income accrues only while the pool is in service;
divergence accrues always. So:

```
    net vs HODL   ≈   duty × fee_rate   −   divergence_rate
```

and duty is the only term in that expression that is a *decision* rather than a draw.

**Amplification, measured.** For a full-range constant-product pool the impermanent loss of a
ratio move `r` is `2√r/(1+r) − 1`: **−4.38%** for DREGG/nosis and **−3.13%** for weave/nosis.
Realised divergence was **−20.67%** and **−25.81%** of deposit — **4.7× and 8.2×** the
constant-product figure. Concentration buys fee income and buys divergence at the same time,
and once the range is exited the loss stops being sub-linear at all: the position is a 100%
holding of the loser and every further move costs full freight.

### What it is NOT, and what would be a better benchmark

RESULT_lp_history.md established that these positions are **ladders, not yield farms**. That
reading survives here and sharpens: weave/DREGG A took **seven** deposits including one of
4,651,730 weave with **zero DREGG** — a purely one-sided sell ladder — and every one of its 41
fee claims came back in DREGG only, i.e. 100% of flow was DREGG-in/weave-out. It sold 66.4M weave
for 16.9M DREGG over 50 hours and got paid **$663** of fees for doing it — **75% of the desk's
entire token-token fee income comes from that one pool.**

Under the *ladder* benchmark the right question is not "did it beat HODL" but "did it beat
market-selling the same size", and this study cannot answer that — it needs per-fill comparison
against the market price at that slot, which is RESULT_lp_history.md's "next experiment #1" and
remains unrun. **Everything below about expected value is stated against HODL, and HODL is the
wrong benchmark for a desk that wanted to rotate inventory anyway.** Both numbers are reported
because neither alone is honest.

---

## 4. The full record: every token-token position the desk has opened

| pool | # | opened UTC | h | dep $ | fees $ | net $ | HODL $ | LP−HODL $ | cover | duty | swaps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| weave/DREGG B | 1 | 08-11 14:23 | 0.99 | 537.78 | 1.68 | −27.30 | −49.45 | **+22.15** | 0.08 | 93.4% | 32 |
| weave/DREGG A | 1 | 08-11 15:29 | 22.93 | 1575.07 | 264.95 | −68.53 | +365.30 | **−433.83** | 0.38 | 94.1% | 119 |
| SOLVE/DREGG | 1 | 08-11 20:38 | 14.81 | 182.17 | 4.08 | +36.37 | +33.66 | +2.71 | 2.99 | **1.8%** | 2 |
| SOLVE/DREGG | 2 | 08-12 11:35 | 13.27 | 480.70 | 26.57 | −55.27 | −81.59 | +26.32 | 108.3 | 66.9% | 22 |
| weave/DREGG A | 2 | 08-12 18:10 | 2.31 | 469.42 | 134.82 | +47.08 | −31.25 | **+78.32** | 2.39 | 68.9% | 76 |
| weave/DREGG A | 3 | 08-12 20:37 | 1.70 | 1556.96 | 122.41 | −161.58 | −168.63 | +7.05 | 1.06 | 59.9% | 34 |
| weave/DREGG A | 4 | 08-12 22:26 | 1.33 | 1109.44 | 9.58 | −469.88 | −227.99 | **−241.88** | 0.04 | 63.6% | 8 |
| weave/DREGG A | 5 | 08-12 23:48 | 13.75 | 631.63 | 131.52 | +392.58 | +316.88 | +75.70 | 2.36 | 94.0% | 102 |
| DREGG/nosis | 1 | 08-13 13:36 | 3.91 | 616.75 | 35.42 | −215.63 | −123.57 | **−92.06** | 0.28 | 49.4% | 46 |
| weave/nosis | 1 | 08-13 17:46 | 8.53 | 726.84 | 147.98 | +391.36 | +430.99 | −39.63 | 0.79 | 99.4% | 96 |
| weave/nosis #2 | 1 | 08-14 02:40 | — | 436.01 | — | *open* | | | | | 19 |
| weave/SOLVE | 1 | 08-14 02:44 | — | 106.13 | — | *open* | | | | | 4 |

**6 of 10 closed positions beat HODL. Total net −$130.80. Total LP−HODL −$595.14. Total fees
+$879.00.**

Read that row carefully, because it is the study's least comfortable sentence: **the fee harvest
is real, large, and it did not clear the divergence it was paid to bear.** RESULT_swing_cluster's
"26–159%/day turnover, mechanically confirmed" and RESULT_power_gate's "realized 32.1%/day" are
both *correct and unchanged*. They are statements about the numerator.

Caveats that are real and must travel with the table:

- **n = 10 positions over 3 days.** The dispersion in daily LP−HODL rate runs from −394%/day to
  +173%/day. At that variance, ten observations cannot separate skill from draw, and the
  aggregate −$595 is *itself* one draw. This is a measurement, not a verdict on the strategy.
- **"Position" here means EPISODE** — a maximal run of nonzero desk exposure in one pool.
  Meteora positions are per-range NFTs and the desk sometimes runs two at once; separating them
  needs instruction-level position-key tracking. RESULT_lp_history.md hit the same wall and
  excluded 12 of 42 positions; this study merges instead of excluding, which is the more
  complete choice and the less granular one.
- **Deposits are recycled** between pools (SOLVE/DREGG position 1 was funded by a weave/DREGG A
  fee claim eight minutes earlier), so the capital at risk was never the $7,887 the deposit
  column sums to.
- **Bundled close transactions were split** into principal and fee by walking inner instructions
  per top-level index. Not splitting them would inflate the fee yield and shrink the divergence
  simultaneously — flattering the strategy twice from one error.

---

## 5. The ranking statistic, and why it needs no pairwise data

The problem with ranking a *missing* edge is that it has no history. The way out is a
decomposition that turned out to hold tightly:

| pair | σ_AB | √(σ_A² + σ_B²) | ratio | implied ρ |
|---|---|---|---|---|
| DREGG/SOLVE | 32.7% | 31.9% | 1.024 | −0.049 |
| DREGG/nosis | 92.7% | 93.1% | 0.996 | +0.018 |
| DREGG/weave | 47.2% | 50.9% | 0.927 | +0.195 |
| SOLVE/nosis | 92.5% | 94.3% | 0.981 | +0.073 |
| SOLVE/weave | 51.5% | 53.0% | 0.972 | +0.068 |
| nosis/weave | 95.9% | 102.3% | 0.938 | +0.148 |

(15-minute sampling over the 19.8 h in which all four tokens have genuine minute bars; own
volatilities: **nosis 90.9%, weave 46.8%, SOLVE 24.8%, DREGG 20.0%** per √day.)

`σ_AB ≈ √(σ_A² + σ_B²)` to within 7% on all six pairs, because the implied correlations are
−0.05 to +0.20 — an independent reproduction of RESULT_swing_cluster.md's measured 0.11–0.24
from a different estimator on different data. **A candidate edge can therefore be ranked from
single-token volatility alone**, which is exactly what you have for a pool that does not exist.

### Turnover model

Derived in `edge_creation.py:turnover_model`. A ratio with daily vol σ crosses a band of
half-width `band` about `σ²/band²` times a day; each crossing is arbitraged by a trade that
moves the pool by roughly one band, and moving a constant-product pool of value `T` by `d ln p`
takes `T·d ln p/4` of notional (RESULT_circuit_model.md §6). So

```
    volume/day / TVL   =   κ · σ² / (4 · band) ,        band = f_own + 2.88%
```

Fitted on all seven pools the desk has run:

| pool | σ | band | σ²/band | measured turnover/day | κ | hours of flow |
|---|---|---|---|---|---|---|
| weave/DREGG A | 47.2% | 7.88% | 2.83 | 595% | 8.42 | 49.9 |
| weave/DREGG B | 47.2% | **3.08%** | 7.23 | 3,403% | 18.82 | 0.9 |
| SOLVE/DREGG | 32.7% | 7.88% | 1.36 | 221% | 6.51 | 21.6 |
| DREGG/nosis | 92.7% | 7.88% | 10.91 | 1,396% | 5.12 | 1.9 |
| weave/nosis | 95.9% | 8.88% | 10.36 | 892% | 3.45 | 8.5 |
| weave/nosis #2 | 95.9% | 8.88% | 10.36 | 3,936% | 15.20 | 0.4 |
| weave/SOLVE | 51.5% | 7.88% | 3.37 | 747% | 8.88 | 0.4 |

**Spearman(σ²/band, measured turnover) = 0.829 on n = 6** (weave/nosis #2 dropped: it shares σ
with weave/nosis and would double-count). The same test on **σ² alone scores 0.500** — the band
term earns its place. κ spans 3.45–18.82, and the three well-sampled pools (>8 h) give 3.45,
6.51, 8.42. **This ranks; it does not price.** n=6 is exactly the 5% Spearman critical value, and
κ moving 5× across the sample is the honest statement that the level is not identified. That is
the SEISMIC lesson from PROGRAM.md §1.5 applied to our own model: rank survives a miscalibrated
scalar, a point estimate does not.

---

## 6. The ranking, with the arithmetic

| edge | state | σ /√day | band | σ²/band | fee yield/day | full-range LVR/day | TVL floor |
|---|---|---|---|---|---|---|---|
| nosis/weave | live (2 pools) | 95.9% | 7.88% | 11.67 | 45–111% | 11.50% | $97 |
| **DREGG/nosis** | **dead (one-sided)** | 92.7% | 7.88% | 10.92 | 42–103% | 10.75% | $97 |
| **nosis/SOLVE** | **MISSING** | 92.5% | 7.88% | 10.85 | 42–103% | 10.69% | $97 |
| SOLVE/weave | live (opened 02:44) | 51.5% | 7.88% | 3.36 | 13–32% | 3.31% | $97 |
| DREGG/weave | dead at 5%, live at 0.2% | 47.2% | 7.88% | 2.82 | 11–27% | 2.78% | $97 |
| DREGG/SOLVE | dead (one-sided) | 32.7% | 7.88% | 1.35 | 5–13% | 1.33% | $97 |

Fee yield assumes a 5.00% tier (bin step 200, base factor 25,000 — the desk's default) with the
10% protocol share, at κ ∈ [3.45, 8.42].

**Rank 1 — nosis/SOLVE, the only genuinely missing edge.** σ 92.5%/√day, essentially tied with
the two best existing edges, and it is unbuilt. At $700 of TVL the model puts gross fee income at
**$294–$721/day**. It also has a topological property none of the others do: **every live
token-token edge in this cluster currently passes through weave** (degree 5 — it is the hub of
the token-token layer, while nosis and SOLVE sit at degree 2 apiece). nosis/SOLVE would be the
first live token-token edge that does not touch weave, which makes it the only candidate that
adds a cycle rather than another spoke.

**Rank 2 — DREGG/nosis, which the desk just closed.** σ 92.7%, statistically indistinguishable
from nosis/SOLVE, and it is the *second-best edge in the cluster by this metric*. The desk killed
it after 3.91 hours because it lost $216. This study's reading is that it was killed for the
wrong reason: it failed on **duty cycle**, which is a range-placement decision, not on endpoint
choice, which is the edge-placement decision. Re-opening it and *managing the range* is a
strictly better experiment than never re-opening it.

**Ranks 3–6 are a different animal.** SOLVE/weave (just opened), DREGG/weave and DREGG/SOLVE all
sit at σ 33–52%, i.e. **σ²/band 3–8× lower**, and their fee yields land in the 5–32%/day band
where the cost side plausibly dominates. weave/SOLVE, opened 40 minutes before this was written,
is a **rank-4 edge**. It will earn; the model does not say it will clear its divergence.

### The cost side, which decides the sign

Realised divergence ran **4.7×** and **8.2×** the full-range constant-product IL. Applying that
band to the LVR column: for a σ ≈ 0.93 pair the cost is roughly **50–90%/day** against a fee
yield of **42–103%/day**. **The expected value of the best missing edge straddles zero** — which
is precisely what the realised record shows (6/10 beat HODL; the aggregate did not). Anyone
reporting a point estimate for this number is reporting noise.

### Minimum viable TVL, derived

From RESULT_circuit_model.md §3.3: an arb of size Φ around the loop earns
`Φ(|C| − Σf) − ½Φ²Σr − G` with `r_e = W_e/TVL_e`, maximised at `Φ* = (|C| − Σf)/Σr` for
`profit* = (|C| − Σf)²/(2Σr) − G`. A brand-new pool is by construction the thinnest leg, so
`Σr ≈ W/TVL_new`, and requiring `profit* > 0`:

```
    TVL_min   >   2 · G · W / (|C| − Σf)²
```

Taking the excess `|C| − Σf` as one band width — the smallest excursion that trades at all, and
therefore the *largest* floor — with `G = $0.30` (RESULT_circuit_model §3.3) and the DLMM span
`W` that RESULT_swing_cluster.md's measured `4/W = 3.98–5.91` implies (`W = 0.68–1.00`):

| your fee | band | W = 4.0 | **W = 1.0** | W = 0.2 |
|---|---|---|---|---|
| 0.20% | 3.08% | $2,530 | **$632** | $126 |
| 0.50% | 3.38% | $2,101 | **$525** | $105 |
| 1.00% | 3.88% | $1,594 | **$399** | $80 |
| 2.00% | 4.88% | $1,008 | **$252** | $50 |
| 5.00% | 7.88% | $387 | **$97** | $19 |
| 6.00% | 8.88% | $304 | **$76** | $15 |

**Note the direction, which is the opposite of intuition: a cheaper pool needs MORE capital.**
The band *is* the arbitrageur's entire margin, so halving the fee halves the margin and squares
into a 4× higher capital floor. The floor does not depend on σ at all — σ decides how *often* the
edge is crossed, the band decides whether a crossing is worth anyone's gas.

The one falsification test available: `A8ga6XM3` (weave/DREGG at **0.20%**) was funded with
**$537.78** against a W=1.0 floor of **$632**. It is the only desk pool below its own floor, and
it is the only desk pool currently showing **$0 of 24-hour volume**. One observation, but it is
the right one, and it was predicted by the formula rather than fitted to it.

---

## 7. Falsifiable claims, each with its falsification and its inversion

**C1. Direct token↔token demand in this cluster is ~0.**
*Falsification:* run `edge_creation.py flow` weekly; a DIRECT share above 5% on ≥100 swaps at any
pool refutes it. *Inverts on:* an aggregator or wallet UI that quotes token-token pairs natively
(so users route A→B without thinking about SOL), or a second cluster token becoming a numeraire
that people hold and spend. Then the "cheaper wire" strategy becomes real and the fee tier should
drop below 2.12%.

**C2. The product is the arbitrage toll on a closed cycle, not captured user flow.**
*Falsification:* a token-token pool priced *below* the two-hop cost that then captures a majority
of A↔B volume — `A8ga6XM3` was that experiment and it captured zero. *Inverts on:* the two-hop
cost rising (a creator-fee tier change, or the PumpSwap protocol share) above the token-token
tier, which would flip the router's preference in one step. The creator ladder is **inverse to
FDV**, so a *falling* DREGG price mechanically raises the two-hop cost — the desk's own token
declining is what would make its token-token pools competitive as wires.

**C3. σ_AB ≈ √(σ_A² + σ_B²), so an edge's earning power is set by its loudest endpoint.**
*Falsification:* the ratio column leaving [0.85, 1.15] on any pair over a ≥3-day window.
*Inverts on:* the cluster becoming genuinely correlated — a shared narrative, a shared holder
base actually trading them as one basket, or a market-wide risk event. At ρ = 0.8 the
decomposition breaks and pairwise history becomes mandatory again. **This is the claim most
likely to fail**, because ρ is exactly the parameter a community-cluster ought to have high.

**C4. Turnover ranks by σ²/band (Spearman 0.829, n=6).**
*Falsification:* Spearman below 0.5 once n ≥ 12 pools. The sample doubles every few days at the
desk's current tempo, so this is answerable inside a week and should be re-run before it is
believed. *Inverts on:* routing flow (the LEG class, 15%) growing large enough to dominate, since
it is driven by aggregator behaviour and not by σ at all.

**C5. Duty cycle, not endpoint choice, is what killed DREGG/nosis.**
*Established as a sequence* (flow stopped 15:38:42, position closed 17:31:03) but **not
established as a general law** — the n=10 record has too much dispersion to identify duty cycle
as *the* driver, and this document does not claim it does. *Falsification:* the proper test is a
duty-cycle-controlled comparison, which needs ~30 positions. *Inverts on:* a range-management
rule that raises duty cycle failing to improve LP−HODL — which would mean the loss is coming from
adverse selection at the band edges rather than from time out of service.

**C6. A cheaper pool needs more TVL (floor ∝ 1/band²).**
*Falsification:* a sub-1% token-token pool trading actively at TVL well under $400.
*Inverts on:* gas falling (Jito bundles at lower priority fees) or a searcher batching multiple
loops into one transaction, which amortises `G` and lowers every floor proportionally.

---

## 8. What to do, in cost order

1. **Add the four unwatched pools to `shitcoims_cluster/pools.py`** — `5fJBZY6h` (weave/nosis #2),
   `9M1oU7cv` (weave/SOLVE), `A8ga6XM3` (weave/DREGG 0.20%), `GxnCwxTi` (weave/DREGG 5%). Three
   are edges the desk earns on and cannot see. Zero cost, and it is the same defect commit
   `3c7b49b` already fixed once. *(Not done here — this study owns only its own two files.)*
2. **Instrument duty cycle live.** It is one number per open position — time since last swap
   against position age — and it is the only term in `net ≈ duty × fee − divergence` the desk
   controls. `edge_creation.py positions` computes it retrospectively; the netmap should show it
   at a glance. RESULT_swing_cluster.md already observed range exit costing an hour of income;
   this study shows it costing a position.
3. **Open nosis/SOLVE at 5.00% with ≥$200** (2× the $97 floor). It is the only missing edge, it
   ranks first among unbuilt options, and it completes K4 on the cluster. Size it as an
   experiment, not a position: the model says its EV straddles zero, so the thing being bought is
   **an observation at a known σ**, and at $200 the tuition is bounded.
4. **Score the ladders against market-selling.** Every EV number in this document is against
   HODL, and RESULT_lp_history.md established HODL is the wrong benchmark for what these
   positions actually are. Per-fill comparison against the market price at that slot is the
   measurement that would decide whether the programme is good or bad, and it is still unrun.
   It is the highest-value thing on this list and the only one that changes the verdict.
5. **Re-run C3 and C4 at n ≥ 12.** Both are one-week questions at the current tempo, both are
   currently at the edge of significance, and both are load-bearing for every recommendation
   above.

---

## 9. What this changes upstream

- **PROGRAM.md §8's "deliberate edge creation" needs its mechanism corrected.** "Placing a pool
  between two communities that lack a low-resistance path makes us the monopolist wire on a route
  flow wants to take" is measurably not what happens: there is no route, the desk's pools are
  more expensive than the alternative, and 84.5% of the flow is arbitrage on a cycle. The move is
  real and it does earn — but it is *toll-booth-on-a-loop*, not *monopolist-wire-on-a-route*, and
  the two have different design rules. A wire wants a **low** fee and gets a **higher** capital
  floor; a toll booth wants a **high** fee and gets a **lower** floor. The desk has been building
  toll booths and describing them as wires, and the pricing it chose (5–6%) is the one the toll
  booth wants — so the instinct was right and the story was wrong.
- **RESULT_circuit_model.md §5's free negative control expired at 02:44 UTC on 2026-08-14.**
  SOLVE is no longer degree 1; a cycle now passes through it. The prediction §5 makes is now
  live and testable: the DREGG/SOLVE ratio's reversion should get *faster* now that the pair's
  combined capacitance has risen. Nothing has to be built to test it — only measured, before the
  memory of the pre-intervention regime ages out.
- **RESULT_swing_cluster.md's harvest numbers are confirmed and reframed.** 26–159%/day turnover
  and 32.1%/day realised yield are all correct. They are the numerator. This study supplies the
  denominator, and the sign of the difference is not the sign of the numerator.
