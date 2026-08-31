#!/usr/bin/env python3
"""circuit_theory.py -- the rest of the EE/physics toolbox, applied to an AMM.

Builds on `studies/circuit_model.py` / `studies/RESULT_circuit_model.md`, which established
the mapping and is NOT re-derived here:

    pool          = nonlinear capacitor,  C = w_x w_y . TVL  (= TVL/4 at even weights)
    DLMM          = series stack of battery cells, C = inf inside a bin, 0 at an edge,
                    coarse-grained C = T/W over a position of value T and log-width W
    fee           = back-to-back diode pair, dissipation linear in |flow|, dead-zone = the band
    liquidity     -> CAPACITANCE, not conductance.  Only ohmic element is behavioural, R = tau/C
    energy ledger = fee (dissipated) + 1/2 C dV^2 (stored) + gas, closes to 94-98%

This file asks what ELSE transfers.  Every section either DERIVES the analogue and states its
falsification, or DEMOTES the analogy explicitly.  Sections that are demoted still compute the
number that demotes them -- a demotion with an order of magnitude attached is worth more than a
shrug.

stdlib only; every network call keyless (DexScreener, GeckoTerminal, Meteora datapi).
Local data: state/cluster_tape/swaps/*.jsonl (per-swap vault pre/post -> exact marginal price).

Usage:
    python studies/circuit_theory.py all
    python studies/circuit_theory.py {identities,arb,available,filter,power,route,control,demote}
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Sequence

# --------------------------------------------------------------------------------------
# universe -- inherited verbatim from studies/circuit_model.py (labels already corrected
# there for the weave/SOLVE transposition in the swing study's scratchpad)
# --------------------------------------------------------------------------------------

MINTS: dict[str, str] = {
    "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
}
SOL = "So11111111111111111111111111111111111111112"
SYM = {v: k for k, v in MINTS.items()} | {SOL: "SOL"}

# Constant-product pools with on-chain-exact marginal price in the tape (replay_sufficient).
CPMM_POOLS: dict[str, str] = {
    "DREGG/SOL": "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU",
    "nosis/SOL": "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc",
    "weave/SOL": "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
    "SOLVE/SOL": "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr",
}
DLMM_POOLS: dict[str, str] = {
    "weave/nosis": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
    "DREGG/nosis": "FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD",
}
# The operator's LIVE positions at 2026-08-14 00:0x UTC, read from the Meteora datapi via
# scripts/meteora_lp_report.py.  Pool addresses differ from the ones RESULT_power_gate.md
# measured -- the book turned over between the two reads, which is itself a finding (sec.7).
OPERATOR_POOLS: dict[str, str] = {
    "weave/SOL(dlmm)": "6RRecgQPELvZfoaDECEbsPQaR2WHnDQAPCvMPoFmsr3X",
    "nosis/weave": "5fJBZY6hCG3ykS2nNCJCXXrFtgcGSDByGccq4ucVea9i",
    "weave/SOLVE": "9M1oU7cvRKiNo3e6iuCnApVe5RYehQ9RNv5dhtiKTrA7",
}

TAPE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "cluster_tape", "swaps")

# fee legs.  PumpSwap LP leg is INHERITED AS AN ASSUMPTION from RESULT_circuit_model.md
# (0.20% LP + 0.05% protocol; the creator leg does not reach the LP).  Every result that
# uses it is swept over PUMPSWAP_LP_SWEEP.
PUMPSWAP_LP = 0.0020
PUMPSWAP_LP_SWEEP = (0.0010, 0.0020, 0.0025, 0.0050)
PUMPSWAP_TAKER = 0.0025 + 0.0095  # LP+protocol+creator at FDV < $300k; the arb's cost per leg
USER_AGENT = {"User-Agent": "joshibot-research/0.1 (studies/circuit_theory.py)"}

BAR = "=" * 88
SUB = "-" * 88


# --------------------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------------------


def _get(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _get_retry(url: str, tries: int = 5, timeout: int = 30) -> Any | None:
    """GeckoTerminal rate-limits at ~30 req/min and answers 429; back off properly."""
    for k in range(tries):
        try:
            return _get(url, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(8.0 * (k + 1))
                continue
            if k == tries - 1:
                return None
            time.sleep(1.5 * (k + 1))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            if k == tries - 1:
                return None
            time.sleep(1.5 * (k + 1))
    return None


# --------------------------------------------------------------------------------------
# small numerics
# --------------------------------------------------------------------------------------


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _sd(xs: Sequence[float]) -> float:
    return statistics.pstdev(xs) if len(xs) > 1 else float("nan")


def _fmt(x: float, n: int = 4) -> str:
    if x != x:
        return "n/a"
    if x == 0:
        return "0"
    a = abs(x)
    if a >= 1e6 or a < 1e-4:
        return f"{x:.{n}e}"
    return f"{x:,.{n}f}"


# ======================================================================================
# SECTION 1.  EXACT IDENTITIES
#   what the capacitor picture buys once you write impermanent loss in the same variables
# ======================================================================================


def il_exact(C: float, dV: float) -> float:
    """Impermanent loss of a constant-product LP, EXACT, in dollars.

    Start at reserves (x0,y0), price p0 = y0/x0, quote-side charge Q = y0, C = y0/2.
    Move to p1 = p0 e^{dV} with the invariant held.  Then

        LP value (in quote)   = 2 sqrt(k p1) = 2 y0 e^{dV/2}
        HODL value (in quote) = x0 p1 + y0   = y0 (1 + e^{dV})
        IL = LP - HODL        = -y0 (e^{dV/2} - 1)^2 = -2C (e^{dV/2} - 1)^2

    so the loss is  +2C (e^{dV/2} - 1)^2, and to second order that is exactly 1/2 C dV^2 --
    the SAME capacitor energy that appears in the per-swap ledger as the *stored* term.
    """
    return 2.0 * C * (math.exp(dV / 2.0) - 1.0) ** 2


def stored_energy(C: float, dV: float) -> float:
    """The ledger's stored term, 1/2 C (dV)^2."""
    return 0.5 * C * dV * dV


def cmd_identities(_args: argparse.Namespace) -> None:
    print(BAR)
    print("1.  IMPERMANENT LOSS *IS* THE STORED CAPACITOR ENERGY")
    print(BAR)
    print(
        """
RESULT_circuit_model.md sec.6 split each swap into  fee (DISSIPATED, LP income) + 1/2 C dV^2
(STORED, returned on reversal) + gas.  It never connected the stored term to impermanent
loss.  They are the same object:

    IL(dV)  =  2C (e^{dV/2} - 1)^2  =  1/2 C dV^2 + O(dV^3)              [EXACT, closed form]

So "impermanent" is not a euphemism, it is the word for STORED: the trader's price-impact
payment does not vanish, it sits in the capacitor as the LP's inventory displacement, and it
is returned to whoever pushes the price back -- not necessarily to whoever paid it.  That
last clause is the whole risk: the pool is a REACTIVE element that does not conserve the
payer.

Numerical check of the exact form against a brute-force reprice of x.y=k reserves, and of
the quadratic against the exact:
"""
    )
    print(f"{'dV (bps)':>10} {'IL exact ($)':>16} {'brute force ($)':>18} {'rel err':>12} "
          f"{'1/2 C dV^2':>14} {'quad/exact':>12}")
    C = 14_402.0  # DREGG/SOL capacitance, TVL/4 at the circuit-model snapshot
    y0 = 2.0 * C
    x0 = 1.0
    k = x0 * y0
    for bps in (1, 10, 100, 344, 1000, 3000):
        dV = bps / 1e4
        p1 = (y0 / x0) * math.exp(dV)
        x1 = math.sqrt(k / p1)
        y1 = math.sqrt(k * p1)
        lp = x1 * p1 + y1
        hodl = x0 * p1 + y0
        brute = hodl - lp
        exact = il_exact(C, dV)
        quad = stored_energy(C, dV)
        rel = abs(exact - brute) / brute if brute else 0.0
        print(f"{bps:>10} {exact:>16,.4f} {brute:>18,.4f} {rel:>12.2e} {quad:>14,.4f} "
              f"{quad / exact:>12.4f}")
    print(
        """
The exact column reproduces brute force to machine precision -- it is an identity, not a fit.
The quadratic column is the ledger's stored term and it is the same number to 2nd order, with
the gap growing as dV^3, which is precisely the 2-6% gap RESULT_circuit_model.md sec.6 already
measured and attributed to the third-order term.  Same gap, same cause, now on both sides of
the same equation.

CONSEQUENCE -- the master ledger for an LP over any window [0,T], with NO free parameter:

    LP net vs HODL  =  f . N_T  -  2C (e^{dV_T/2} - 1)^2
                    =  f . N_T  -  1/2 C (dV_T)^2  + O(dV^3)

      f    = LP fee rate                  (known per venue)
      N_T  = notional traded through the pool over the window   (MEASURED, from the tape)
      C    = capacitance = w_x w_y . TVL, or T/W for a DLMM     (MEASURED)
      dV_T = NET log-price displacement over the window         (MEASURED)

Everything else in this file is a statement about when the first term beats the second.
"""
    )

    print(SUB)
    print("POWER FACTOR -- naming, not content, and labelled as such")
    print(SUB)
    print(
        """
An AC circuit splits apparent power into REAL (dissipated, watts) and REACTIVE (sloshed,
VAR); the ratio is the power factor.  A swap splits identically: the fee is real power, the
impact is reactive.  For a trade of size Phi,

    power factor  =  f.Phi / (f.Phi + Phi^2/2C)  =  1 / (1 + Phi/(2 f C))

and it is the fraction of the trader's cost that is permanently gone.  This is a NAME for
something the sec.6 ledger already had, and nothing follows from it that did not follow from
the ledger.  DEMOTED to vocabulary.  The one non-vacuous corollary is the crossover size
Phi = 2fC, where a trader's impact cost first exceeds their fee -- which is the same
quantity that turns out to set optimal depth in sec.5.
"""
    )
    for name, tvl, f in (("DREGG/SOL", 57_608.0, PUMPSWAP_LP), ("nosis/SOL", 46_798.0, PUMPSWAP_LP),
                         ("weave/nosis DLMM (T/W)", 842.0 / 1.005, 0.054)):
        Cx = tvl / 4.0 if "DLMM" not in name else tvl
        print(f"    {name:24s}  C = ${Cx:>10,.0f}   Phi(pf=1/2) = 2fC = ${2 * f * Cx:>10,.2f}")
    print()


# ======================================================================================
# SECTION 2.  THE MARGINAL-ARBITRAGE WASH THEOREM
# ======================================================================================


def simulate_band_pool(
    eps: float,
    n_steps: int,
    seed: int = 0,
) -> dict[str, float]:
    """Reflected-band pool in BAND UNITS: fee f = 1, capacitance C = 1.

    Brownian motion is scale-free, so the only parameter that survives is

        eps  ==  sigma sqrt(dt) / f          block move over band width

    the same dimensionless group the fast-block LVR literature calls `P_trade` up to a
    constant (arXiv:2305.14604: P_trade = sigma sqrt(dt/2) / gamma = eps/sqrt(2)).
    eps -> 0 is the continuous-time limit where the theorem is stated; eps >~ 1 is the
    jump regime where every block gaps the band.

    The external price steps by N(0, eps).  The arb moves the pool only while the marginal
    trade clears the fee, leaving the mispricing at exactly +-1.  Exact per-trade accounting:

        notional      = C . move                         (move = |z| - 1)
        fee to LP     = f . C . move        = C . move
        arb GROSS     = C (move^2/2 + move)
        arb NET       = C move^2 / 2
        LP vs rebal.  = fee - arb gross     = - arb NET                     [exact identity]
    """
    rng = random.Random(seed)
    V_ext = 0.0
    V_pool = 0.0
    tv = 0.0  # total variation of the pool price = the boundary local time
    fees = 0.0
    arb_net = 0.0
    qv_ext = 0.0
    crossings = 0
    for _ in range(n_steps):
        dv = rng.gauss(0.0, eps)
        V_ext += dv
        qv_ext += dv * dv
        z = V_ext - V_pool
        if z > 1.0 or z < -1.0:
            move = abs(z) - 1.0
            fees += move
            arb_net += 0.5 * move * move
            V_pool += move if z > 0 else -move
            tv += move
            crossings += 1
    return {
        "fees": fees,
        "arb_net": arb_net,
        "lp_vs_rebalancer": -arb_net,
        "tv": tv,
        "qv_ext": qv_ext,
        "dV": V_pool,
        "crossings": float(crossings),
        "il": il_exact(1.0, V_pool),
    }


def cmd_arb(_args: argparse.Namespace) -> None:
    print(BAR)
    print("2.  THE MARGINAL-ARBITRAGE WASH THEOREM  (and where LVR actually lives)")
    print(BAR)
    print(
        """
DERIVATION.  Let the external log-price be m, the pool's V, mispricing z = m - V.  An arb can
profitably move the pool only while the marginal trade clears the fee, i.e. until z = +-f.  So
z is Skorokhod-reflected Brownian motion on [-f, f] and the pool price moves ONLY by the
boundary local time.

  (a)  Local time.  For reflected BM on a box of width L = 2f with variance rate sigma^2,
       Ito on z^2 in stationarity gives the pushing rate at EACH boundary = sigma^2/(2L).
       Total variation rate of the POOL price:

               d TV / dt  =  sigma^2 / (2f)                                          [exact]

  (b)  Fee income.  Moving the pool by dV takes notional dQ = C dV, so

               fee rate  =  f . C . sigma^2/(2f)  =  1/2 C sigma^2       <-- f CANCELS

  (c)  Adverse selection.  Per unit of notional the LP transacts at a price exactly f away
       from the external one and is paid exactly f.  Writing the arb's books explicitly for a
       push that moves the pool by `move` starting from mispricing z = move + f:

               notional  = C.move       fee to LP = f.C.move
               arb gross = C(move^2/2 + f.move)     arb NET = 1/2 C move^2
               LP vs the rebalancing benchmark = fee - arb gross = - arb NET     [IDENTITY]

       THE LP'S LOSS TO ARBITRAGE IS EXACTLY THE ARBITRAGEUR'S NET PROFIT.  Not proportional
       to it, not bounded by it -- equal.  This is the cleanest thing in this file and it
       needs no distributional assumption whatsoever.

  (d)  The continuous limit.  On a continuous path every arb is MARGINAL (move -> 0), so
       arb NET -> 0 and the LP breaks exactly even on arbitrage flow -- at every fee tier and
       every volatility.  On a jump to mispricing z > f,

               arb NET = LP loss = 1/2 C (z - f)^2                                    [exact]

       -- the capacitor energy of the EXCESS over the band, and nothing else.

THE THEOREM.  All LP profit comes from non-arbitrage (taker) flow.  All LP loss to arbitrage
is supported on price moves that GAP the band:

        LP loss to arbitrage  =  1/2 C . SUM over gaps of ( |z| - f )_+^2

A strictly sharper object than "LVR = sigma^2 V/8": the LP's adverse selection is not a
functional of total variance, it is a functional of the part of the variance delivered in
single moves larger than the fee band.  The two agree only in the zero-fee limit.

RECONCILIATION with the LVR literature (studies/RESULT_lp_literature.md).  The textbook
constant-product LVR rate is sigma^2 . V_pool / 8.  With C = V_pool/4 that is exactly

        LVR rate  =  1/2 C sigma^2   ==   the fee rate in (b).

Identical -- which is why they cancel.  The zero-fee LVR benchmark and the fee income of a
band pool are the SAME NUMBER, and the fee tier cancels out of both.

THE ONE PARAMETER THAT SURVIVES.  Brownian motion is scale-free, so after fixing f = C = 1
the only free quantity is

        eps  ==  sigma sqrt(dt) / f          (block move / band width)

with dt the block time.  eps -> 0 is the theorem's regime; eps ~ 1 is "every block gaps the
band".  This is exactly the group the fast-block literature calls P_trade = eps/sqrt(2)
(arXiv:2305.14604), so the sweep below is a check of that result as well as of this one.
Real values: Solana 400 ms at sigma = 20%/day gives sigma sqrt(dt) = 4.3e-4, so eps = 0.22 at
a 0.20% fee and eps = 0.008 at 5.5%; Ethereum's 12 s at a 0.30% fee gives eps = 0.79.
"""
    )

    print(
        """
AND ONE MORE IDENTITY, WHICH IS THE REAL RESULT OF THIS SECTION.  Telescope z^2 across a
push: the pool goes from mispricing |z| to exactly f, so z^2 drops by move^2 + 2 f move, which
is 2/C times the arb's GROSS take.  Summing over the path and taking expectations (the
Sigma 2 z dv term is a martingale):

        1/2 C . QV     =     fee income     +     arbitrageur net profit     +  O(C f^2)
        \\_________/           \\________/           \\__________________/
           LVR              recaptured by LP        kept by the arbitrageur

EXACT, up to a bounded boundary term, at ANY block time and ANY fee tier.  LVR is not a loss,
it is a BUDGET, and the fee tier decides how it is split.  "Fast blocks move LVR from
arbitrageurs into your fee income" is usually stated as an asymptotic; it is an accounting
identity, and the block time only sets the split.
"""
    )
    print(SUB)
    print("Monte Carlo in band units.  QV held at ~1,000 band^2 per path, 8 paths per row.")
    print(SUB)
    print(f"{'eps':>8} {'n steps':>10} {'crossings':>10} {'fee/(QV/2)':>12} {'arb/(QV/2)':>12} "
          f"{'SUM':>8} {'eps/sqrt2':>11} {'arb / that':>11} {'2f.TV/QV':>10}")
    for eps in (2.0, 1.0, 0.5, 0.3, 0.2, 0.1, 0.05, 0.02):
        n = max(2000, int(1000.0 / (eps * eps)))
        agg = {"fees": 0.0, "arb_net": 0.0, "tv": 0.0, "qv_ext": 0.0, "crossings": 0.0}
        for s in range(8):
            r = simulate_band_pool(eps, n, seed=1000 + s)
            for k in agg:
                agg[k] += r[k]
        half_qv = 0.5 * agg["qv_ext"]
        fr, ar = agg["fees"] / half_qv, agg["arb_net"] / half_qv
        print(f"{eps:>8.3f} {n:>10,} {agg['crossings']:>10,.0f} {fr:>12.4f} {ar:>12.4f} "
              f"{fr + ar:>8.4f} {eps / math.sqrt(2):>11.4f} "
              f"{ar / (eps / math.sqrt(2)):>11.3f} {2 * agg['tv'] / agg['qv_ext']:>10.4f}")
    print(
        """
Four things to read.

  * `SUM` is the budget identity and it is 1.00 at EVERY eps, from the jump regime to the
    continuous one -- 0.2% to 3%, which is Monte Carlo error on QV plus the O(f^2) boundary
    term.  Nothing was tuned to make that column flat.
  * `fee/(QV/2)` converges to 1 as eps -> 0.  That is (b): the fee tier cancels and the LP's
    arbitrage revenue is exactly the LVR rate 1/2 C sigma^2, whatever f is.
  * `arb/(QV/2)` -- which by the identity in (c) is MINUS the LP's P&L against the rebalancing
    benchmark -- goes to 0 LINEARLY in eps.  The fast-block literature's asymptote is
    ARB = LVR . P_trade with P_trade = eps/sqrt(2); the `arb / that` column shows the ratio
    settling at ~0.8, i.e. the right scaling with a coefficient 20% below theirs.  An
    independent derivation (local time, not their argument) reproducing the exponent and
    landing 20% off the constant is what agreement looks like at this level of care; the
    constant is not something either derivation pins down for a real fee schedule.
  * `2f.TV/QV` is eta on pure arbitrage flow and it is 1.00 by construction in the limit.

At Solana's own eps the arbitrageur keeps ~10-15% of LVR at a 0.20% fee and under 1% at 5.5%;
the rest is recaptured by the LP as fees.  RESULT_lp_literature.md sec.2(c) quotes ~1.5% of
headline LVR at memecoin parameters and flags it as theory extrapolated outside its validated
regime -- this sweep says the extrapolation is fine, and that the FEE TIER, not the block
time, is what puts you deep into the recaptured regime.  Solana's 400 ms buys you eps = 0.22;
a 5.5% fee tier on the same chain buys you eps = 0.008.

Direct check of the jump formula (d), deterministic, one gap of size z into a band of f = 1:
"""
    )
    print(f"{'z (bands)':>11} {'arb net':>12} {'1/2 (z-1)^2':>14} {'LP loss':>12} {'fee to LP':>12}")
    for z in (1.0, 1.5, 2.0, 5.0, 10.0):
        move = max(z - 1.0, 0.0)
        print(f"{z:>11.2f} {0.5 * move * move:>12.5f} {0.5 * (z - 1) ** 2:>14.5f} "
              f"{0.5 * move * move:>12.5f} {move:>12.5f}")
    print(
        """
Exact by construction, and note the shape: the LP's loss is QUADRATIC in the gap while the
fee is LINEAR, so a pool survives many small gaps and is killed by one large one.  A 10-band
gap costs the LP 40x the fee it pays.  That is the whole reason a bounded LP position dies of
one-directional drift rather than of ordinary volatility, which is the correction
RESULT_lp_literature.md sec.0 made on other grounds.
"""
    )
    print(
        """
FALSIFICATION.  On the cluster tape, tag every swap that is an atomic multi-pool route (the
tape already carries `counterparty` and `leg_discriminators`, so this is free) and compute the
LP's realised P&L on that subset alone.  The theorem says it is zero up to the jump term.  If
arbitrage flow is measurably profitable for the LP on a continuous path, the theorem is dead.

WHAT THIS OVERTURNS, in a live study.  RESULT_power_gate.md sec.2.5 carries a CRUDE model
concluding that arbitrage REVENUE is invariant to the fee tier, and infers that "half the edge
is competition-invariant".  The revenue half of that is now exact (it is (b) above, and the
crude version's sigma^2 . depth/2 is right).  The INFERENCE does not survive: that revenue is
matched dollar-for-dollar by adverse selection, so its contribution to PROFIT is zero and it
is not edge at all.  A rival who takes only the taker flow takes 100% of the profit while
leaving 36% of the revenue.  Same falsification as theirs (open a cheap rival pool and
measure), different prediction about what the number means.
"""
    )


# ======================================================================================
# SECTION 3.  AVAILABLE POWER  (the Johnson-Nyquist question)
# ======================================================================================


def cmd_available(_args: argparse.Namespace) -> None:
    print(BAR)
    print("3.  FLUCTUATION-DISSIPATION:  what transfers (available power) and what does not")
    print(BAR)
    print(
        """
THE QUESTION.  Johnson-Nyquist relates a resistor's dissipation to its thermal noise.  Is
there an AMM version relating fee income to price volatility?

WHAT IS EXACT.  From sec.2(b), the arbitrage-driven fee income rate is

        P_fee  =  1/2 C sigma^2                                                       (*)

and the fee tier f -- the strength of the dissipative element -- CANCELS.  That cancellation
is structurally the same fact as Nyquist's: the noise power a resistor can deliver to a
matched load is k_B T . dnu, INDEPENDENT of R, because the source EMF grows as sqrt(R) while
the divider attenuates as 1/R.  Here the band width grows as f while the crossings per unit
time fall as 1/f^2 and the notional per crossing grows as f, so f.TV is f-free.  The
AVAILABLE-POWER structure transfers exactly.

WHAT DOES NOT.  Johnson-Nyquist is an EQUILIBRIUM fluctuation-dissipation theorem: the noise
and the dissipation come from the same microscopic degrees of freedom at one temperature, and
the content is that one constant (T) sets both.  In an AMM the price noise and the fee are
CAUSALLY INDEPENDENT -- the fee tier is a governance parameter and it does not generate the
volatility.  There is no detailed balance, no entropy production, and no equipartition:

    equilibrium kTC noise says   1/2 C <V^2> = 1/2 k_B T   -- a TEMPERATURE
    the AMM band says            <z^2> = f^2/3             -- a GOVERNANCE PARAMETER

so any "AMM temperature" would be k_B T_eff = C f^2 / 3, set by the fee tier and independent
of sigma, which is not a temperature in any useful sense.  DEMOTED: the AMM has an
available-power identity, not a fluctuation-dissipation theorem.  Do not call it FDT.

WHAT THE EXACT HALF BUYS: A MEASUREMENT INSTRUMENT.  Fee revenue is arbitrage revenue PLUS
taker revenue, and taker revenue is non-negative.  So for every venue v on a given pair,

        f_v . vol_v / C_v   >=   sigma^2 / 2                                          (**)

with sigma the variance rate of the EFFICIENT price.  Minimising the left side over venues
gives an upper bound on efficient-price volatility that never touches a price series:

        sigma_eff^2   <=   2 . min_v ( f_v . vol_v / C_v )

Realised volatility measured from thin-pool last-trade prints is inflated by bid-ask bounce
INSIDE the band, which by construction generates no arbitrage flow.  (**) bounds the part
that is real.  A measured RV above the bound is not a falsification of the model, it is a
measurement of the bounce -- and the size of the violation is the size of the bounce.
"""
    )
    pools = fetch_dexscreener_pools()
    if not pools:
        print("  [live fetch failed; skipping the empirical half]")
        return
    ohlcv = {}
    for label, addr in CPMM_POOLS.items():
        ohlcv[label] = fetch_ohlcv(addr)
        time.sleep(2.5)

    print(SUB)
    print("(**) on the live cluster.  LP fee legs: PumpSwap 0.20% ASSUMED; DLMM base fee read")
    print("from the Meteora datapi pool_config, net of the 10% protocol share.")
    print("LIVENESS FLOOR (part of the derivation, not a fudge): the bound only binds on a pool")
    print("that arbitrage actually keeps in line, so require TVL >= $100, vol24 >= $500 and")
    print("turnover >= 20%/day.  Excluded pools are listed so the threshold is visible.")
    print(SUB)
    print(f"{'pair':>12} {'venue':>10} {'TVL':>11} {'vol24':>12} {'C':>11} {'LP fee':>8} "
          f"{'2 f vol/C /day':>15} {'':>4}")
    by_pair: dict[str, list[tuple[str, float]]] = {}
    for p in pools:
        if p["tvl"] < 100 or p["vol24"] <= 0:
            continue
        pair = p["pair"]
        if p["dex"] == "pumpswap":
            C = p["tvl"] / 4.0
            f = PUMPSWAP_LP
        else:
            cfg = fetch_meteora_config(p["addr"])
            if not cfg:
                continue
            # coarse-grained DLMM capacitance needs the position width W, which is not
            # observable pool-wide.  Report the CFMM-equivalent (W = 4), which is the
            # CONSERVATIVE direction for (**): smaller C -> larger bound.
            C = p["tvl"] / 4.0
            f = cfg["base_fee_pct"] / 100.0 * (1.0 - cfg["protocol_fee_pct"] / 100.0)
        bound = 2.0 * f * p["vol24"] / C
        live = p["vol24"] >= 500.0 and p["vol24"] / p["tvl"] >= 0.20
        if live:
            by_pair.setdefault(pair, []).append((p["dex"], bound))
        print(f"{pair:>12} {p['dex']:>10} {p['tvl']:>11,.0f} {p['vol24']:>12,.0f} "
              f"{C:>11,.0f} {f:>8.4%} {bound:>15.4f} {'' if live else 'DEAD':>4}")
    print()
    print("Against two independent volatility measurements: hourly last-trade closes")
    print("(GeckoTerminal) and the pool's OWN MARGINAL PRICE from vault balances in the tape.")
    print()
    print(f"{'pair':>12} {'sigma bound /day':>18} {'sigma last-trade':>18} {'sigma marginal':>16} "
          f"{'LT/bound':>10} {'marg/bound':>12}")
    for pair, rows in sorted(by_pair.items()):
        bound = min(b for _, b in rows)
        series = ohlcv.get(pair)
        lt = float("nan")
        if series:
            rets = log_returns([c for _, c in series][-25:])
            lt = math.sqrt(sum(r * r for r in rets))
        marg = float("nan")
        addr = CPMM_POOLS.get(pair)
        if addr:
            sig = tape_rv_signature(addr)
            if sig:
                marg = math.sqrt(sig[-1][1])  # coarsest sampling = least noise-inflated
        print(f"{pair:>12} {math.sqrt(bound):>18.3f} {lt:>18.3f} {marg:>16.3f} "
              f"{(lt / math.sqrt(bound)) if bound > 0 else float('nan'):>10.2f} "
              f"{(marg / math.sqrt(bound)) if bound > 0 and marg == marg else float('nan'):>12.2f}")
    print(
        """
WHAT THE TWO RIGHT-HAND COLUMNS SETTLE.  A last-trade print on an AMM is an EFFECTIVE price:
buys print above the mid by fee-plus-slippage, sells below it.  That is a bid-ask bounce of
half-width ~f, and it inflates realised variance without generating one dollar of arbitrage
flow.  The pool's marginal price y/x from vault balances has no bounce at all -- it is a state
variable, monotone in cumulative flow.  So the gap between the two columns IS the bounce, and
it is measured here rather than asserted.

The volatility signature plot (RV as a function of sampling interval on the marginal price
series) is printed by `eta` and is the standard microstructure diagnostic for the same thing.

TWO READINGS OF A VIOLATION, and they are not the same claim:

  (1) MEASUREMENT.  The printed volatility is inflated by bounce, the efficient volatility is
      at or below the bound, and (**) is doing its job as an instrument.
  (2) PRICE DISCOVERY.  For a memecoin there may be no external venue at all -- the deepest
      pool IS where the price is made.  Then the pool is not a price FOLLOWER, arbitrage is not
      what moves it, and the arbitrage floor simply does not apply.  This is Schlegel-Kilbourn
      (RESULT_lp_literature.md sec.2b): LVR scales by (1 - marginal-liquidity ratio), which
      goes to zero for a venue that is the reference.

Both readings are good news for the LP and they have OPPOSITE diagnostics, so say which:
under (1) the marginal-price column comes in near the bound; under (2) it stays above it even
with the bounce removed.  Read the `marg/bound` column against `LT/bound` -- the drop between
them is (1), and whatever excess remains is (2) or a wrong fee assumption.

FALSIFICATION of (**) itself: a LIVE pool (past the floor above) whose marginal-price
volatility exceeds the bound after the fee leg is measured rather than assumed, on a pair with
a deeper external venue.  That would mean fee revenue is below the arbitrage floor, which the
derivation forbids.
"""
    )


# ======================================================================================
# SECTION 4.  THE FILTER  -- eta vs VR(T), and the LP's spectrum
# ======================================================================================


def log_returns(closes: Sequence[float]) -> list[float]:
    out = []
    for a, b in zip(closes, closes[1:]):
        if a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def variance_ratio(x: Sequence[float], q: int) -> tuple[float, int]:
    """Lo-MacKinlay variance ratio of the LEVEL series x at horizon q bars.

    VR(q) = Var(x_{t+q} - x_t) / (q Var(x_{t+1} - x_t)), overlapping, with the standard
    unbiased scalings.  Returns (VR, n_overlapping).
    """
    n = len(x) - 1
    if n < 4 * q:
        return float("nan"), 0
    r1 = [x[i + 1] - x[i] for i in range(n)]
    mu = _mean(r1)
    var1 = sum((r - mu) ** 2 for r in r1) / (n - 1)
    m = len(x) - q
    rq = [x[i + q] - x[i] for i in range(m)]
    denom = q * (m) * (1 - q / (len(x) - 1))
    varq = sum((r - q * mu) ** 2 for r in rq) / denom if denom > 0 else float("nan")
    return (varq / var1 if var1 > 0 else float("nan")), m


def cmd_filter(args: argparse.Namespace) -> None:
    print(BAR)
    print("4.  THE FILTER.  The brief's premise is wrong; the corrected version is sharper.")
    print(BAR)
    print(
        """
THE PREMISE, AND THE CORRECTION.  "A pool is a low-pass filter on order flow: high-frequency
two-sided flow is absorbed and returned, low-frequency directional flow moves price
permanently."  Half right, and the half that is wrong matters.

  (i)  From FLOW to PRICE the pool is exactly an INTEGRATOR: V = Q/C with Q the accumulated
       signed flow.  Transfer function 1/(jwC): infinite gain at DC, zero at high frequency.
       So the LP's INVENTORY is precisely the DC component of the order flow.  That much of
       the premise is exact and it is just the capacitor.

  (ii) But the fee is a DIODE, and a dead-zone is RATE-INDEPENDENT.  A backlash/play element
       has NO frequency response at all -- it filters by AMPLITUDE, not frequency.  There is
       therefore NO cutoff frequency, and asking for one is a category error.  What there is:
       a price oscillation of period T has amplitude ~ sigma sqrt(T), so it crosses the band
       iff sigma sqrt(T) > 2f, i.e. above the CORNER PERIOD

               T_corner  =  (2f / sigma)^2                                             [exact]

       Below T_corner the price rattles inside the dead-zone: no trade, no fee, no inventory
       change.  This makes the pool a HIGH-pass on price-driven flow, the opposite sign to the
       premise, and it is a corner PERIOD not a corner frequency because the amplitude-time
       relation is the diffusive one, not a filter's.

THE RESULT THAT REPLACES IT.  Take the master ledger of sec.1 over a window of T bars and
divide through by 1/2 C RV_T (RV_T = realised variance over the window).  Everything
dimensionless:

        LP net  >  0        <==>        eta  >  VR(T)

        eta   ==  2 f N_T / (C . RV_T)          the CHURN NUMBER   (fee side)
        VR(T) ==  (dV_T)^2 / RV_T               the VARIANCE RATIO (loss side)

Both sides are pure numbers, both are measured, and there is no free parameter anywhere.

WHY THIS IS THE FILTER STATEMENT.  VR(T) is, up to a smoothing kernel, the normalised
spectral density of returns at frequency 1/T.  So:

    the LP is LONG the entire return spectrum (fees see total power: quadratic variation)
    and SHORT exactly one frequency bin (IL sees only the net move over the holding period).

The pool is a NOTCH, not a low-pass.  An LP wants a return spectrum with a DIP at the
reciprocal of their holding period, and the optimal holding horizon is

        T*  =  argmin_T VR(T)                                                  [parameter-free]

with the LP's rate per unit capital proportional to (eta - VR(T)) and the break-even
condition VR(T) = eta.  For pure arbitrage flow eta == 1 exactly (sec.2), so eta - 1 is
literally "the non-arbitrage share of fee revenue, measured in units of LVR".

WHAT CONCENTRATION DOES, settled.  A DLMM position has C = T/W instead of TVL/4, i.e. 4/W
times the capacitance.  BOTH terms of the ledger are proportional to C.  So concentration is
pure LEVERAGE on the sign of (eta - VR): it multiplies the answer by 4/W and cannot change it.
That is a cleaner resolution of RESULT_power_gate.md sec.2.2's "the question is malformed"
than that section reached -- 4/W is not a yield multiplier and not double counting, it is
leverage on a signal whose sign is set elsewhere.
"""
    )

    print(SUB)
    print("VR(T) measured, hourly GeckoTerminal closes, cluster ratios and outright pairs")
    print(SUB)
    series: dict[str, list[tuple[int, float]]] = {}
    for label, addr in CPMM_POOLS.items():
        s = fetch_ohlcv(addr)
        if s:
            series[label] = s
        time.sleep(2.5)
    if not series:
        print("  [live fetch failed]")
        return

    def levels(label: str) -> tuple[list[int], list[float]]:
        s = series[label]
        return [t for t, _ in s], [math.log(c) for _, c in s if c > 0]

    tracks: dict[str, list[float]] = {}
    for label in series:
        _ts, lv = levels(label)
        tracks[label] = lv
        # aligned dict for ratio construction
    aligned: dict[str, dict[int, float]] = {
        label: {t: math.log(c) for t, c in series[label] if c > 0} for label in series
    }
    ratios: dict[str, list[float]] = {}
    for a, b in (("DREGG/SOL", "SOLVE/SOL"), ("weave/SOL", "nosis/SOL"),
                 ("DREGG/SOL", "nosis/SOL"), ("weave/SOL", "SOLVE/SOL")):
        if a not in aligned or b not in aligned:
            continue
        common = sorted(set(aligned[a]) & set(aligned[b]))
        if len(common) < 60:
            continue
        name = f"{a.split('/')[0]}/{b.split('/')[0]}"
        ratios[name] = [aligned[a][t] - aligned[b][t] for t in common]

    horizons = (1, 2, 3, 4, 6, 8, 12, 18, 24, 36, 48, 72)
    print(f"{'series':>14} {'n':>5} " + "".join(f"{f'VR({h}h)':>9}" for h in horizons))
    all_series = {**{k: v for k, v in tracks.items()}, **ratios}
    vr_table: dict[str, dict[int, float]] = {}
    for name, lv in all_series.items():
        row = []
        vr_table[name] = {}
        for h in horizons:
            vr, _m = variance_ratio(lv, h)
            vr_table[name][h] = vr
            row.append("      ---" if vr != vr else f"{vr:>9.3f}")
        print(f"{name:>14} {len(lv):>5} " + "".join(row))

    print(
        """
Reading the table: VR < 1 = mean-reverting on that horizon (LP-friendly); VR > 1 = trending
(LP-hostile); VR = 1 = random walk, LP exactly break-even against arbitrage flow.
"""
    )
    print(f"{'series':>14} {'T* = argmin VR':>16} {'VR(T*)':>9} {'first T with VR>1':>19}")
    for name, row in vr_table.items():
        good = {h: v for h, v in row.items() if v == v}
        if not good:
            continue
        tstar = min(good, key=lambda h: good[h])
        over = [h for h in sorted(good) if good[h] > 1.0]
        print(f"{name:>14} {tstar:>14}h {good[tstar]:>9.3f} "
              f"{(str(over[0]) + 'h') if over else 'none in range':>19}")

    print(
        """
THE CAVEAT, AND THEN THE MEASUREMENT THAT SETTLES IT.  Those are LAST-TRADE closes.  An AMM
print is an EFFECTIVE price: buys print above the mid, sells below, by fee-plus-slippage.  That
is a bid-ask bounce of half-width s ~ f, and it biases VR DOWNWARD -- exactly the direction
that flatters an LP.  With bounce variance s^2 per print,

        VR_obs(T)  =  ( sigma^2 T + 2 s^2 ) / ( (sigma^2 + 2 s^2) T )
                   ->  1 / (1 + 2 s^2/sigma^2)     as T grows

so the WHOLE long-horizon level of the table can be an artifact, and the debias factor is
exactly the ratio of last-trade variance to efficient variance.  RESULT_swing_cluster.md hit
the same bias and its Kendall debias killed four of six pairs; this is the same problem in the
frequency domain.

The tape settles it: the pool's MARGINAL price from vault balances has no bounce at all.  Same
statistic, bounce-free, on a 5-minute grid, over the horizons the tape supports:
"""
    )
    qs = (3, 6, 12, 24, 48)
    print(f"{'pool':>12} {'grid pts':>9} {'span h':>8} "
          + "".join(f"{f'VR({q * 5}m)':>10}" for q in qs) + f"{'LT, same T':>12}{'bounce factor':>15}")
    for label, addr in CPMM_POOLS.items():
        _, prices = tape_notional_and_price(addr, SOL)
        if len(prices) < 60:
            continue
        prices.sort()
        g0, g1 = prices[0][0], prices[-1][0]
        grid: list[float] = []
        i, last = 0, prices[0][1]
        t = g0
        while t <= g1:
            while i < len(prices) and prices[i][0] <= t:
                last = prices[i][1]
                i += 1
            grid.append(math.log(last))
            t += 300
        row = []
        for q in qs:
            vr, _m = variance_ratio(grid, q)
            row.append("     ---" if vr != vr else f"{vr:>10.3f}")
        ltv = vr_table.get(label, {})
        lt4 = ltv.get(4, float("nan"))
        vr4, used = float("nan"), 0
        for q in (48, 24, 12):
            v, _ = variance_ratio(grid, q)
            if v == v:
                vr4, used = v, q
                break
        lt_at = ltv.get({48: 4, 24: 2, 12: 1}.get(used, 4), float("nan"))
        lt4 = lt_at
        bf = vr4 / lt4 if lt4 == lt4 and lt4 > 0 and vr4 == vr4 else float("nan")
        print(f"{label:>12} {len(grid):>9} {(g1 - g0) / 3600:>8.1f} " + "".join(row)
              + f"{lt4:>12.3f}{bf:>15.2f}")
    print(
        """
(VR(60m) in the last-trade table is 1.000 by construction -- one bar is one lag -- so the
comparison column is the 4 h one, against the bounce-free VR at the longest horizon the tape
supports.  `bounce factor` is their ratio: how much the last-trade series UNDERSTATES VR.)

WHAT THIS DOES AND DOES NOT SHOW, stated at the resolution the tape actually supports.

  * At 15 min to 1 h the bounce-free VR is 0.80 to 1.01 on ALL FOUR pools.  That is a random
    walk.  There is no intraday mean reversion in this cluster's efficient prices, and any
    LP or swing rule keyed to intraday reversion in the last-trade series is keyed to nothing.
  * Only SOLVE/SOL has enough tape (29.3 h, 353 grid points) to reach the 4 h horizon, and
    there the bounce-free VR is 1.50 -- TRENDING -- against 0.587 from last-trade closes over
    the same horizon.  A factor of 2.56 in the LP-hostile direction, on the one pool where the
    comparison can be made at all.
  * DREGG/SOL reaches 2 h and the two agree (0.851 vs 0.877), so the bounce is NOT inflating
    everything everywhere; where the comparison is possible at short horizon it is clean.

ONE POOL IS ONE POOL.  The SOLVE result is a lead, not a finding, and it is reported because
it points at the thing that would matter most if it held: the reversion that
RESULT_swing_cluster.md measured, and that the token-token LP thesis leans on, sits at
horizons (7-48 h) where NOBODY HAS YET CHECKED IT AGAINST A BOUNCE-FREE PRICE.  The check
needs only calendar time on the tape -- about a week of it -- and it is the single cheapest
way to confirm or kill the desk's central premise.  Every VR standard error here is of order
0.2-0.3; no single cell is significant alone.

THE VERDICT TABLE.  eta from sec.8 against VR from here.  LP is +EV iff eta > VR(T).
"""
    )
    print(f"{'pool':>12} {'eta (measured)':>15} {'best VR in range':>18} {'at T':>7} {'verdict':>28}")
    eta_est = eta_by_pool()
    for label in CPMM_POOLS:
        e = eta_est.get(label, float("nan"))
        row = vr_table.get(label, {})
        good = {h: v for h, v in row.items() if v == v}
        if not good or e != e:
            continue
        tstar = min(good, key=lambda h: good[h])
        v = good[tstar]
        verdict = "+EV" if e > v else f"-EV by {v / e:.1f}x"
        print(f"{label:>12} {e:>15.3f} {v:>18.3f} {tstar:>6}h {verdict:>28}")
    print(
        """
Every token/SOL pool in this cluster is -EV for an LP by an order of magnitude, at the most
LP-favourable holding horizon its own price history offers, using a VR that is BIASED IN THE
LP'S FAVOUR by the bounce.  That is about as robust as a negative gets on this data.

FALSIFICATION of the whole section: measure eta and VR(T) on a held-out window and check that
positions with eta > VR(T) realise positive fee-minus-IL and positions with eta < VR(T)
realise negative.  Sign agreement on >= 20 positions is the bar.  If the sign does not track,
the ledger is wrong and everything above it goes.  The desk has 42 closed positions on chain
and this is the computation to run on them.
"""
    )


# ======================================================================================
# SECTION 5.  MAXIMUM POWER TRANSFER  -- the optimal depth
# ======================================================================================


def hill_alpha(xs: Sequence[float], k_frac: float = 0.25) -> tuple[float, int, float]:
    """Hill estimator of the Pareto tail index alpha, with its asymptotic s.e.

    Uses the top k = k_frac * n order statistics.  Returns (alpha, k, se).
    """
    s = sorted((x for x in xs if x > 0), reverse=True)
    n = len(s)
    if n < 20:
        return float("nan"), 0, float("nan")
    k = max(10, int(k_frac * n))
    k = min(k, n - 1)
    lo = math.log(s[k])
    alpha = k / sum(math.log(v) - lo for v in s[:k])
    return alpha, k, alpha / math.sqrt(k)


_TAPE_CACHE: dict[str, list[dict[str, Any]]] = {}


def read_tape_sizes(pool_addr: str) -> list[dict[str, Any]]:
    """Per-swap records for a pool: notional in the SOL/quote leg where possible.

    Cached: the nosis/SOL tape alone is ~90 MB and every section wants it.
    """
    if pool_addr in _TAPE_CACHE:
        return _TAPE_CACHE[pool_addr]
    rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(TAPE_DIR, f"{pool_addr}-*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("kind") != "swap":
                    continue
                res = d.get("reserves") or {}
                vaults = res.get("vaults") or []
                if len(vaults) != 2:
                    continue
                v = {x["mint"]: x for x in vaults}
                rows.append({"t": d.get("t_event"), "block": d["chain"]["block_time"],
                             "in_mint": d.get("token_in_mint"), "out_mint": d.get("token_out_mint"),
                             "in_raw": int(d.get("token_in_raw") or 0),
                             "out_raw": int(d.get("token_out_raw") or 0),
                             "vaults": v, "payer": d.get("fee_payer"),
                             "counterparty": d.get("counterparty"),
                             "dex": d.get("dex")})
    rows.sort(key=lambda r: r["block"])
    _TAPE_CACHE[pool_addr] = rows
    return rows


def tape_notional_and_price(pool_addr: str, quote_mint: str) -> tuple[list[float], list[tuple[int, float]]]:
    """Returns (notional per swap in quote units, [(block_time, marginal price)]).

    Marginal price uses POST-trade vault balances: for x.y = k the marginal price of base in
    quote units is exactly y/x.  This is the on-chain read RESULT_circuit_model.md sec.7.3
    named as the fix for its 150 bps resolution ceiling, and the tape now carries it.
    """
    rows = read_tape_sizes(pool_addr)
    notional: list[float] = []
    prices: list[tuple[int, float]] = []
    for r in rows:
        vq = r["vaults"].get(quote_mint)
        if vq is None:
            continue
        base_mint = next((m for m in r["vaults"] if m != quote_mint), None)
        if base_mint is None:
            continue
        vb = r["vaults"][base_mint]
        dq = abs(int(vq["delta_raw"])) / 10 ** vq["decimals"]
        notional.append(dq)
        xb = int(vb["post_raw"]) / 10 ** vb["decimals"]
        yq = int(vq["post_raw"]) / 10 ** vq["decimals"]
        if xb > 0 and yq > 0 and r["dex"] == "pumpswap":
            prices.append((r["block"], yq / xb))
    return notional, prices


def read_notional(pool_addr: str, quote_mint: str) -> list[float]:
    return tape_notional_and_price(pool_addr, quote_mint)[0]


def eta_by_pool(f: float = PUMPSWAP_LP) -> dict[str, float]:
    """eta = 2 f N / (C RV) for each constant-product pool, all three terms from chain."""
    pools = fetch_dexscreener_pools()
    tvl = {p["pair"]: p["tvl"] for p in pools if p["dex"] == "pumpswap"}
    out: dict[str, float] = {}
    for label, addr in CPMM_POOLS.items():
        notional, prices = tape_notional_and_price(addr, SOL)
        if len(prices) < 20:
            continue
        prices.sort()
        lp_ = [math.log(p) for _, p in prices]
        rv = sum((b - a) ** 2 for a, b in zip(lp_, lp_[1:]))
        sol_usd = next((p["price_usd"] / p["price_native"] for p in pools
                        if p["pair"] == label and p["price_native"] > 0), 76.0)
        C = (tvl.get(label, float("nan")) / sol_usd) / 4.0
        if rv > 0 and C == C:
            out[label] = 2 * f * sum(notional) / (C * rv)
    return out


def ratio_rv_from_vaults(tok_a: str, tok_b: str, t0: int, t1: int, grid_s: int = 300) -> float:
    """Realised variance of log(A/B) over [t0,t1], from both pools' EXACT marginal prices.

    Each token's /SOL constant-product pool gives y/x from vault balances, so the ratio is
    free of the bid-ask bounce that contaminates last-trade series.  Returns total RV over the
    window (not annualised), or nan if either leg has too little tape in the window.
    """
    ser = {}
    for tok in (tok_a, tok_b):
        addr = CPMM_POOLS.get(f"{tok}/SOL")
        if not addr:
            return float("nan")
        _, pr = tape_notional_and_price(addr, SOL)
        pr = sorted(p for p in pr if t0 - grid_s <= p[0] <= t1)
        if len(pr) < 10:
            return float("nan")
        ser[tok] = pr
    grid: list[float] = []
    idx = {t: 0 for t in ser}
    last = {t: ser[t][0][1] for t in ser}
    g = t0
    while g <= t1:
        for t in ser:
            while idx[t] < len(ser[t]) and ser[t][idx[t]][0] <= g:
                last[t] = ser[t][idx[t]][1]
                idx[t] += 1
        grid.append(math.log(last[tok_a] / last[tok_b]))
        g += grid_s
    if len(grid) < 5:
        return float("nan")
    return sum((b - a) ** 2 for a, b in zip(grid, grid[1:]))


def measured_hourly_vol() -> dict[str, tuple[float, str]]:
    """sigma per hour for every pair the operator might hold, from the best available source.

    Outright pairs: the pool's own MARGINAL price from vault balances (no bid-ask bounce).
    Token-token pairs: the ratio of the two /SOL last-trade hourly series (carries bounce, so
    an over-estimate -- flagged wherever it is used).
    """
    out: dict[str, tuple[float, str]] = {}
    for label, addr in CPMM_POOLS.items():
        sig = tape_rv_signature(addr, window_s=None)
        if sig:
            # per-day RV at the coarsest scale -> per-hour sigma
            out[label] = (math.sqrt(sig[-1][1] / 24.0), "vaults")
            base = label.split("/")[0]
            out[f"{base}/SOL"] = out[label]
    aligned: dict[str, dict[int, float]] = {}
    for label, addr in CPMM_POOLS.items():
        s = fetch_ohlcv(addr)
        if s:
            aligned[label.split("/")[0]] = {t: math.log(c) for t, c in s if c > 0}
        time.sleep(2.5)
    toks = list(aligned)
    for i, a in enumerate(toks):
        for b in toks[i + 1:]:
            common = sorted(set(aligned[a]) & set(aligned[b]))
            if len(common) < 40:
                continue
            r = log_returns([math.exp(aligned[a][t] - aligned[b][t]) for t in common])
            v = math.sqrt(sum(x * x for x in r) / len(r))
            out[f"{a}/{b}"] = (v, "ratio-LT")
            out[f"{b}/{a}"] = (v, "ratio-LT")
    return out


SIGNATURE_SCALES_S = (0, 60, 300, 900, 3600, 10800)


def tape_rv_signature(pool_addr: str, quote_mint: str = SOL,
                      window_s: int | None = 86400) -> list[tuple[int, float]]:
    """Volatility signature plot on the pool's own MARGINAL price, from vault balances.

    Returns [(sampling interval in seconds, realised variance PER DAY)], interval 0 meaning
    per-swap (tick) sampling.  A falling signature is the classic microstructure-noise
    diagnostic; on an AMM the "noise" is the fee band, which is not noise but a dead-zone.

    `window_s` restricts to the last N seconds of the tape so the number is comparable with a
    24 h aggregator figure.  None uses the whole tape.
    """
    _, prices = tape_notional_and_price(pool_addr, quote_mint)
    if len(prices) < 30:
        return []
    prices.sort()
    if window_s:
        cutoff = prices[-1][0] - window_s
        prices = [(t, p) for t, p in prices if t >= cutoff]
        if len(prices) < 30:
            return []
    span = prices[-1][0] - prices[0][0]
    if span < 3600:
        return []
    out: list[tuple[int, float]] = []
    for dt in SIGNATURE_SCALES_S:
        if dt == 0:
            samp = [p for _, p in prices]
        else:
            samp = []
            grid = prices[0][0]
            i = 0
            last = prices[0][1]
            while grid <= prices[-1][0]:
                while i < len(prices) and prices[i][0] <= grid:
                    last = prices[i][1]
                    i += 1
                samp.append(last)
                grid += dt
        if len(samp) < 5:
            continue
        rets = log_returns(samp)
        rv = sum(r * r for r in rets)
        out.append((dt, rv * 86400.0 / span))
    return out


def cmd_power(_args: argparse.Namespace) -> None:
    print(BAR)
    print("5.  MAXIMUM POWER TRANSFER  --  the optimal pool depth")
    print(BAR)
    print(
        """
THE EE RESULT.  Source EMF E with internal resistance R_s into load R_L delivers
P = E^2 R_L/(R_s+R_L)^2, maximised at R_L = R_s, at 50% efficiency.

THE AMM SETUP, made precise.  Routing cost through a pool for size Phi is fee + impact:

        cost(Phi)  =  f Phi  +  r Phi^2 / 2 ,       r == 1/C = 4/TVL

so 1/C is the ELASTANCE and it is what adds along a route -- exactly the r_e of
RESULT_circuit_model.md sec.3.3.  (It is not the behavioural resistance R = tau/C; keep them
apart.  A router splitting an order across parallel pools sets marginal costs equal, giving
Phi_i proportional to C_i at equal fees -- a current divider in the capacitances.)

A taker takes the cheaper of our pool (f, C) and the best substitute route (f_0, C_0 series-
combined).  The comparison is linear-plus-quadratic, so the boundary is a single SIZE:

        Phi_x  =  2 |f - f_0| / |1/C - 1/C_0|

    if we UNDERCUT on fee and are thinner  ->  we capture every order BELOW Phi_x
    if we CHARGE MORE and are deeper       ->  we capture every order ABOVE Phi_x

Optimising yield per unit capital, y(C) = f . M(Phi_x(C)) / (4C) with M the captured volume,
gives a clean condition with no fee and no depth in it:

        d ln (captured volume) / d ln C   =   1                              [the optimum]

That is the AMM's maximum-power-transfer condition: DEPTH IS OPTIMAL WHERE CAPTURED VOLUME IS
UNIT-ELASTIC IN DEPTH.  It has a unique interior root because captured volume is bounded above
and vanishes as C -> 0.

CLOSED FORM.  Trade sizes are Pareto with tail index alpha (measured below).  Then:

    premium-fee regime (we charge more, we are deeper -- the desk's actual position):

            C*  =  alpha . C_0                                                        (A)

    undercutting regime against a deep substitute (r_0 -> 0):

            Phi_x*  =  Phi_min . alpha^{1/(alpha-1)},     C* = Phi_x* / (2 (f_0 - f))  (B)

    and in case (B) the pool captures at its optimum exactly  (alpha-1)/alpha  of the
    available volume, independent of fees, depth and size scale.

(A) IS THE HEADLINE AND IT IS AN IMPEDANCE-MATCHING RESULT.  In elastance terms r* = r_0/alpha.
At alpha = 1 -- a scale-free size distribution, the heaviest tail with no mean -- this is
EXACTLY R_L = R_s, the textbook matched condition, recovered on the nose.  Every alpha above 1
says: be DEEPER than matched, by exactly the tail index.  So the EE answer is the alpha -> 1
limit of the AMM answer, and the tail index is the entire correction.  That is the sense in
which maximum power transfer transfers: the FORM is exact, the matched point moves, and the
displacement is measurable.
"""
    )

    print(SUB)
    print("alpha, measured.  Trade sizes from state/cluster_tape (quote-leg notional per swap).")
    print("HILL PLOT across tail fraction -- printed in full, because it does NOT plateau and")
    print("a single number would misrepresent what the data supports.")
    print(SUB)
    kfracs = (0.05, 0.10, 0.15, 0.25, 0.40)
    print(f"{'pool':>14} {'n':>6} {'mean':>10} {'median':>10} "
          + "".join(f"{f'a@{int(kf * 100)}%':>10}" for kf in kfracs))
    alphas: list[float] = []
    for label, addr in list(CPMM_POOLS.items()) + list(DLMM_POOLS.items()):
        quote = SOL if label.endswith("/SOL") else MINTS[label.split("/")[1]]
        notional, _ = tape_notional_and_price(addr, quote)
        if len(notional) < 40:
            print(f"{label:>14} {len(notional):>6} {'--- too few swaps ---':>50}")
            continue
        row = []
        for kf in kfracs:
            a, _k, _se = hill_alpha(notional, kf)
            row.append(f"{a:>10.2f}")
            if kf == 0.10:
                alphas.append(a)
        print(f"{label:>14} {len(notional):>6} {_mean(notional):>10.4f} "
              f"{statistics.median(notional):>10.4f} " + "".join(row))
    print(
        """
The Hill estimator is scale-free, so the units (SOL for the /SOL pools, quote token for the
token-token pools) do not matter.  It DRIFTS with the tail fraction -- on the best-sampled
pool (nosis/SOL, n = 2,317) from 2.08 at the top 5% to 0.75 at the top 40% -- which is what a
mixture or a lognormal body looks like, not a clean Pareto.  So:

    alpha is pinned to the range 1 to 2 and NO FINER.  Reported as a range throughout.

That range is enough for the result, because C* = alpha . C_0 depends on alpha LINEARLY: the
whole estimation uncertainty is a factor of 2, against a gap to the desk's current sizing of
two orders of magnitude.  It would not be enough if the question were "is 1.4 or 1.6 right".
"""
    )
    if alphas:
        med_a = statistics.median([a for a in alphas if a == a])
        print(f"    cluster median alpha at the top decile = {med_a:.2f}"
              f"   (used below; range 1-2 carried alongside)\n")
        print(
            """
AND NOTE WHERE THAT LANDS.  alpha ~ 1 is the scale-free limit, and at alpha = 1 the AMM
optimum C* = alpha C_0 is EXACTLY the textbook matched condition r = r_0.  Memecoin trade
sizes are close enough to scale-free that the literal EE answer -- make your pool as deep as
the rest of the route combined -- is the right first-order answer here.  That is a nicer
landing than the derivation had any right to expect, and it should be read as a coincidence
of this market's size distribution, not as a general law.
"""
        )

        print(SUB)
        print("(A) applied to the desk's real choices, at the cluster median alpha")
        print(SUB)
        pools = fetch_dexscreener_pools()
        cmap: dict[str, float] = {}
        for p in pools:
            if p["dex"] == "pumpswap" and p["tvl"] > 100:
                cmap[p["pair"]] = cmap.get(p["pair"], 0.0) + p["tvl"] / 4.0
        print(f"{'token-token pool':>18} {'substitute route':>26} {'C_0 (series)':>14} "
              f"{'C* = a.C_0':>12} {'TVL* (W=1.0)':>14}")
        for a, b in (("weave", "nosis"), ("DREGG", "nosis"), ("weave", "SOLVE"),
                     ("DREGG", "SOLVE")):
            ca = cmap.get(f"{a}/SOL")
            cb = cmap.get(f"{b}/SOL")
            if not ca or not cb:
                continue
            c0 = 1.0 / (1.0 / ca + 1.0 / cb)
            cstar = med_a * c0
            print(f"{a + '/' + b:>18} {f'{a}->SOL->{b}':>26} {c0:>14,.0f} {cstar:>12,.0f} "
                  f"{cstar * 1.0:>14,.0f}")
        print(
            """
TVL* is the position VALUE that realises C*, at the width W of the operator's actual ranges
(W ~ 1.0 for a 30-bin bin_step-300 position, so C = T/W ~ T).  Compare with the positions the
LP report shows OPEN right now, which are two orders of magnitude below this.

WHAT THAT MEANS, said carefully.  The desk is running its token-token pools at ~1% of the
depth that maximises yield per unit capital under this model.  Two readings, and they have
opposite implications:

  (1) The model is right and the desk is leaving money on the table -- but not much of it,
      because y(C) is FLAT near its optimum (it is a maximum, so first-order flat), and the
      binding constraint is that the desk has ~$1.4k of LP capital against a $4.1k/month
      obligation.  Optimal depth is not reachable, so the result is not actionable as sizing.

  (2) The model's premise fails: it assumes takers ROUTE ON COST.  The measured mean trade on
      the operator's token-token pool is ~$26 while the cost-indifference size against the
      SOL substitute route is a couple of hundred dollars -- see below.  At $26 the substitute
      is strictly cheaper and the flow arrives anyway.

Reading (2) is the one with teeth, and it is testable right now.
"""
        )

    print(SUB)
    print("THE ROUTING TEST -- the size at which our pool becomes the cheap route")
    print(SUB)
    print(
        """
Our cost minus the substitute's is  (f - f_0) Phi + (1/C - 1/C_0) Phi^2/2.  When the two terms
have OPPOSITE signs there is a crossover size Phi_x = 2|f-f_0| / |1/C - 1/C_0| and we capture
one side of it; when they have the SAME sign one venue dominates at every size.  Both sides of
the comparison are measured.  If routing is cost-optimal, flow only arrives where we win.
"""
    )
    pools = fetch_dexscreener_pools()
    cmap = {}
    for p in pools:
        if p["dex"] == "pumpswap" and p["tvl"] > 100:
            cmap[p["pair"]] = cmap.get(p["pair"], 0.0) + p["tvl"] / 4.0
    sol_usd = next((p["price_usd"] / p["price_native"] for p in pools
                    if p["pair"] == "DREGG/SOL" and p["price_native"] > 0), 76.0)
    print(f"{'our pool':>13} {'f ours':>8} {'f_0 route':>10} {'C_0':>8} {'C ours':>8} "
          f"{'regime':>28} {'median $':>9} {'cost @ med':>11}")
    for label, addr in DLMM_POOLS.items():
        cfg = fetch_meteora_config(addr)
        if not cfg:
            continue
        a, b = label.split("/")
        ca, cb = cmap.get(f"{a}/SOL"), cmap.get(f"{b}/SOL")
        if not ca or not cb:
            continue
        c0 = 1.0 / (1.0 / ca + 1.0 / cb)
        f0 = 2 * PUMPSWAP_TAKER
        f = cfg["base_fee_pct"] / 100.0
        c_ours = 842.0 / 1.005      # RESULT_power_gate.md's measured position, T/W
        quote = MINTS[b]
        notional, _ = tape_notional_and_price(addr, quote)
        qprice = next((q["price_usd"] for q in pools if q["pair"] == f"{b}/SOL"), float("nan"))
        usd = [x * qprice for x in notional] if qprice == qprice else []
        med = statistics.median(usd) if usd else float("nan")
        if f < f0 and c_ours >= c0:
            tag = "we dominate at EVERY size"
        elif f > f0 and c_ours <= c0:
            tag = "SUBSTITUTE wins EVERY size"
        elif f < f0:
            tag = f"we win below ${2 * (f0 - f) / (1 / c_ours - 1 / c0):,.0f}"
        else:
            tag = f"we win above ${2 * (f - f0) / (1 / c0 - 1 / c_ours):,.0f}"
        if med == med:
            ours = f * med + med * med / (2 * c_ours)
            alt = f0 * med + med * med / (2 * c0)
            ratio = ours / alt if alt > 0 else float("nan")
        else:
            ratio = float("nan")
        print(f"{label:>13} {f:>8.2%} {f0:>10.2%} {c0:>8,.0f} {c_ours:>8,.0f} "
              f"{tag:>28} {med:>9.2f} {ratio:>10.2f}x")
    print(
        f"""
(SOL at ${sol_usd:,.2f} from the DexScreener USD/native ratio.  C ours = $838 is
RESULT_power_gate.md's measured weave/nosis position, T/W = 842/1.005 -- the sizing its 15.2x
headline was measured at.  That pool has since been drained and re-created; see sec.7.)

BOTH POOLS LAND IN THE DEGENERATE REGIME, and that is a CLEANER finding than a threshold.  The
desk's token-token pools are both MORE EXPENSIVE on fee AND THINNER than the SOL substitute
route, so the cost difference

        (f - f_0) Phi   +   (1/C - 1/C_0) Phi^2 / 2

is positive in BOTH terms at every size.  A cost-minimising router should send them NOTHING AT
ANY SIZE.  Even granting the DLMM zero slippage for orders that fit inside one bin -- its best
case, and the right model at these trade sizes -- the fee ALONE is ~2.5x the substitute's
all-in cost, and the substitute's own slippage does not catch up until a few hundred dollars,
far above the median trade.  `cost @ med` is the ratio at the median observed trade.

SO THE FLOW ARRIVING AT THESE POOLS IS NOT COST-ROUTED, and that reframes the desk's edge into
a more fragile claim than RESULT_power_gate.md sec.2.5's "pricing power on a route people
need".  It is not pricing power over a route -- the route is strictly cheaper.  It is a
ROUTER-ATTENTION rent on orders a cost-minimising router would have sent elsewhere.  Rents of
that kind are removed by a software update, not by a competitor building a pool.

Falsifiable both ways.  (i) If it is genuinely inattention, the premium should be paid by
direct-UI swappers and not by aggregator-routed ones; the tape distinguishes them (36% of
weave/nosis swaps were multi-hop routed, RESULT_power_gate.md sec.2.5), and the multi-hop legs
are arbitrage crossing the pool, which by sec.2 is zero-net for the LP anyway.  (ii) If
aggregator routing on this pair improves, single-hop income goes to approximately zero.
Measure the single-hop share of fee revenue now; the model predicts income falls to what
remains.
"""
    )


# ======================================================================================
# SECTION 6.  ROUTES: series/parallel, Thomson, Thevenin, and what does NOT exist
# ======================================================================================


def cmd_route(_args: argparse.Namespace) -> None:
    print(BAR)
    print("6.  MULTI-HOP ROUTES:  Thevenin and Thomson are exact;  the transmission line is not")
    print(BAR)
    print(
        """
THEVENIN, EXACT (and nearly content-free, which is worth saying).  A route A -> ... -> B
through pools e with fees f_e and capacitances C_e presents to a trader, to the order the
sec.1 ledger is exact:

        EMF        =  SUM_e ln p_e          (the composed log-price -- additive only in logs)
        series fee =  SUM_e f_e             (diode drops in series -- the dead-zone widens)
        elastance  =  SUM_e 1/C_e           (impact adds; capacitances add in SERIES)

A route is therefore exactly one synthetic pool, and that synthetic pool is the correct object
to compare a direct pool against.  This is a THEOREM but a small one: it is series composition,
which sec.3.3 of the circuit model already used as SUM r_e.  Promoted as a TOOL, not as a
finding.  Note the asymmetry it makes visible: fees add LINEARLY along a route while elastances
also add linearly, so a long route is penalised twice, and a THIN leg dominates SUM 1/C_e
completely -- which is why "a thin pool destroys an arbitrage rather than creating one".

THOMSON'S PRINCIPLE, EXACT.  Splitting an order across parallel routes to minimise total cost
is exactly minimisation of SUM_e (1/2) r_e Phi_e^2 subject to flow conservation, with
r_e = 1/C_e.  That is the Thomson/Dirichlet variational principle for a resistive network, so
optimal routing on an AMM graph IS a current distribution, and the router's first-order
condition (equal marginal cost on every used path) is Kirchhoff's voltage law on the marginal
system.

    THE ONE-WORD CAVEAT THAT KEEPS THIS HONEST:  the quantity being minimised is STORED, not
    dissipated.  It has the algebraic form of power dissipation and none of the physics.  The
    genuinely dissipated part is the fee, which is LINEAR in flow and therefore contributes a
    term Thomson's principle does not have -- an L1 term on top of the L2 one.  Consequence:
    unlike a resistor network, an AMM router uses a STRICTLY SPARSE set of paths, because an
    L1 penalty kills paths at zero flow.  A resistive network puts current in every branch;
    a router does not.  That is a real, checkable difference and it explains why AMM routes
    are 1-3 hops rather than smeared over the graph.

IMPEDANCE MATCHING BETWEEN POOLS IN SERIES -- the brief's question, answered.  There is NO
optimal depth RATIO between two pools on the same route.  For a route the two elastances add,
so the trader's cost depends on 1/C_1 + 1/C_2 and NOTHING ELSE; at fixed total capital
K = TVL_1 + TVL_2 the sum is minimised at C_1 = C_2 (equal split), but that is a statement about
a route OWNER, not about matching, and there is no interference term, no ratio, and no
reflection.  The whole answer is: 1/C adds, put equal depth in each leg, done.

NO TRANSMISSION LINE.  DEMOTED, and here is the reason with a number rather than a shrug.
A transmission line needs an INDUCTANCE: an element whose potential responds to the RATE OF
CHANGE of current, V = L dI/dt.  No AMM element does this.  Price responds to ACCUMULATED
charge (V = Q/C), never to flow acceleration.  With no L there is no wave equation, no
propagation velocity, no characteristic impedance sqrt(L/C), and no reflection coefficient.
Every "reflection" story about AMMs is therefore analogy with zero content.

THE ONE PLACE AN OSCILLATION COULD HIDE, and it is closed quantitatively.  A pure DELAY in the
arbitrageur response is not an inductance, but delayed feedback around a capacitor CAN ring:

        C dV/dt  =  - V(t - tau_d) / R           oscillates when  tau_d / (RC)  >=  pi/2

RC = tau is the measured relaxation time and tau_d is the arbitrageur's reaction latency:
"""
    )
    print(f"{'pair':>14} {'tau = RC':>12} {'tau_d (1 slot)':>16} {'tau_d/tau':>12} "
          f"{'vs pi/2':>12} {'damping margin':>16}")
    for pair, thalf_h in (("DREGG/SOLVE", 7.2), ("weave/nosis", 8.9)):
        tau = thalf_h * 3600.0 / math.log(2.0)
        for latency, _lname in ((0.4, "1 slot"), (12.0, "12 s (ETH)")):
            ratio = latency / tau
            print(f"{pair:>14} {tau:>10,.0f}s {latency:>14,.1f}s {ratio:>12.3e} "
                  f"{ratio / (math.pi / 2):>12.3e} {(math.pi / 2) / ratio:>15,.0f}x")
    print(
        """
The system is overdamped by five to six orders of magnitude.  There is no resonance, no
ringing, and no Q factor worth defining: Q ~ 1/sqrt(tau_d/tau) would be ~ 10^3, which is not a
resonant circuit, it is a first-order lag.  DEMOTED, with the margin stated so nobody has to
re-derive it: you would need arbitrageur latency comparable to the RELAXATION time -- hours --
before an AMM could ring.  That happens only in a market with no arbitrageurs at all, in which
case the RC reading itself is void.

ONSAGER RECIPROCITY.  Already demoted by RESULT_circuit_model.md sec.13 and the demotion
stands; one thing can be ADDED to it.  At the single-swap bar the AMM's response matrix is
exactly DIAGONAL (sec.10.1 of that study: cross-impact is mechanically zero).  A diagonal
matrix is trivially symmetric, so reciprocity is satisfied with zero information content at
the one time scale where the mechanism is known.  At longer lags the symmetry that does appear
is forced by no-arbitrage (Schneider-Lillo Lemma 3.9), not by microscopic reversibility.  So
Onsager is not merely unproven here, it is UNTESTABLE: the regime where it would say something
is the regime where a different theorem already says the same thing for a different reason.
"""
    )


# ======================================================================================
# SECTION 7.  CONTROL:  the rebalance / recentering rule
# ======================================================================================


def cmd_control(_args: argparse.Namespace) -> None:
    print(BAR)
    print("7.  CONTROL THEORY:  the recentering rule, and where the naive threshold is wrong")
    print(BAR)
    print(
        """
THE PLANT.  A DLMM position of value T over log-width W = 2a, centred on the price.  Inside
the range it is a capacitor of C = T/W and earns fees.  Outside it earns EXACTLY ZERO and is
100% in one token -- a fully discharged battery stack.  Recentering costs kappa, dominated NOT
by gas but by the swap needed to rebalance an inventory that is all on one side.

This is impulse control of a diffusion with a fixed intervention cost, a solved problem class
(Constantinides-Richard, Harrison-Taksar).  DERIVE it rather than quoting the folk cube-root,
and USE THE SEC.4 LEDGER rather than gross fee income -- getting this wrong is exactly the
mistake sec.2 catches in a live study, and the first draft of this section made it too.

  A cycle runs from a recentring to the price leaving the range at +-a.
  Expected cycle length for BM from the centre:      tau = a^2 / sigma^2
  Realised variance over the cycle:                  RV = sigma^2 tau = a^2
  Net displacement at exit:                          (dV)^2 = a^2,   so VR = 1 AT THE EXIT.
  Net over the cycle, from sec.4:  1/2 C RV (eta - VR)  =  1/2 (T/2a) a^2 (eta - 1)
                                                       =  T a (eta - 1) / 4

  average net rate(a) = [ T a (eta-1)/4  -  kappa ] / (a^2 / sigma^2)
                      = sigma^2 [ T(eta-1)/(4a)  -  kappa/a^2 ]

  d/da = 0   =>       a*  =  8 kappa / ( T (eta - 1) )         W* = 2a* = 16 kappa/(T(eta-1))

THREE THINGS FALL OUT, and the (eta-1) is doing all the work:

  * IF eta <= 1 THERE IS NO OPTIMAL BAND.  Every width loses, and the correct action is not to
    hold the position at all.  A rebalance rule cannot rescue a pool whose churn number is
    below 1 -- it can only decide how fast you pay.  Any recentring optimiser that does not
    carry eta is optimising the width of a hole.
  * a* is LINEAR in the recentring cost, NOT the cube root.  The cube-root law
    (Delta ~ cost^{1/3}) is the answer for a QUADRATIC running cost -- a tracking-error penalty
    -- and a concentrated LP's running cost is not that: it is a 1/a foregone-depth term.  The
    folk rule imported from the transaction-cost literature has the wrong EXPONENT here.
  * The chain does not matter as much as the literature thinks.  Cartea-Drissi-Monga measure
    Ethereum recentring at $84.8 per round trip and conclude the strategy needs $1.8M of
    capital; that break-even is gas.  On Solana gas is ~$0.30 -- but the DOMINANT term is the
    rebalance SWAP, kappa ~ (T/2) f_swap + G, so

        a*  =  ( 4 f_swap  +  8G/T ) / (eta - 1)

    ON A LOW-GAS CHAIN THE OPTIMAL HALF-WIDTH IS SET BY THE SWAP FEE, NOT BY GAS, and gas stops
    mattering entirely above T >> 2G/f_swap ~ $30 at a 2.2% route.  The cube-root rule would
    have predicted a Solana band 6.6x narrower than Ethereum's; the correct answer is that
    below ~$30 of position size the two chains differ enormously and above it they are the
    same.  RESULT_lp_literature.md sec.6 items 6-7 record "no closed-form optimal recentering
    rule under fixed transaction costs" and "no measurement of recentering economics on a
    low-gas chain" as open.  This is the closed form; the measurement still needs doing.
"""
    )
    print(f"{'f_swap':>9} {'eta':>6} " + "".join(f"{f'T=${t:,}':>11}" for t in (100, 842, 5000, 50000)))
    for f_swap in (0.011, 0.022, 0.055):
        for eta in (1.5, 3.0):
            row = []
            for T in (100, 842, 5000, 50000):
                kappa = (T / 2) * f_swap + 0.30
                row.append(f"{16 * kappa / (T * (eta - 1)):>11.3f}")
            print(f"{f_swap:>9.2%} {eta:>6.1f} " + "".join(row))
    print(
        """
(body = optimal FULL width W* = 2a*, in log-price units; G = $0.30 throughout)

MEASURED AGAINST THE DESK'S ACTUAL POSITIONS, read live from the Meteora datapi.  eta is
taken at 3.0, which is the token-token estimate from sec.8; at eta = 1.5 every W* doubles.
"""
    )
    rows = fetch_operator_positions()
    if not rows:
        print("  [live position read failed]")
    else:
        print(f"{'pool':>14} {'bins':>5} {'step':>5} {'base fee':>9} {'W actual':>9} {'4/W':>6} "
              f"{'W* (2.2%,eta=3)':>16} {'W*/W':>7} {'range':>7} {'age h':>7} {'earned':>9}")
        for r in rows:
            T = r["value"]
            kappa = (T / 2) * 0.022 + 0.30
            wstar = 16 * kappa / (T * 2.0) if T > 0 else float("nan")
            print(f"{r['pair']:>14} {r['bins']:>5} {r['bin_step']:>5} {r['base_fee']:>9.2%} "
                  f"{r['W']:>9.4f} {4 / r['W']:>6.2f} {wstar:>16.4f} {wstar / r['W']:>7.3f} "
                  f"{r['in_range']:>7} {r['age_h']:>7.2f} ${r['fees']:>8.2f}")
        print(
            """
The desk's ranges are 2-6x WIDER than the rule says at eta = 3, and the direction is the
interesting part: a wider range is the RIGHT error to make if eta is closer to 1 than to 3,
because W* scales as 1/(eta-1).  So this table does not say "narrow your ranges" -- it says
MEASURE ETA FIRST, because that single number moves the answer by more than any width choice
does.  The one thing it does say unconditionally: a position whose W is set by a bin-count
habit rather than by kappa/T is not being sized by anything.
"""
        )
    print(
        """
THE PREDICTION THAT NEEDS NO MODEL AT ALL, and it is the cheapest test in this file.  For BM
started at the centre of a band of half-width a, the expected exit time is EXACTLY

        E[time in range]  =  a^2 / sigma^2                                    [no free parameter]

three independently measured quantities: a from the position's own bin range, sigma from the
pair's realised volatility, and the observed in-range duration from the position history.
RESULT_lp_history.md records 42 positions with holding periods (July: 5h, 18h, 32h, 45h, 99h;
August: 0.1h, 0.8h, 1.2h, 3.6h, 6h -- an order-of-magnitude tempo collapse).  Predicted:
"""
    )
    sig = measured_hourly_vol()
    if rows:
        print(f"{'pool':>14} {'a = W/2':>9} {'sigma/hr MEASURED':>19} {'source':>10} "
              f"{'E[in-range]':>13} {'observed age':>13}")
        for r in rows:
            a = r["W"] / 2
            key = r["pair"]
            s, src = sig.get(key, (float("nan"), "none"))
            pred = a * a / (s * s) if s == s and s > 0 else float("nan")
            print(f"{key:>14} {a:>9.4f} {s:>19.4f} {src:>10} {pred:>11.2f}h "
                  f"{r['age_h']:>12.2f}h")
    print(
        """
sigma is measured, not assumed: for a pair with a live constant-product pool it is the hourly
volatility of the pool's OWN MARGINAL price from vault balances in the tape (no bounce); for a
token-token pair it is the hourly volatility of the ratio built from the two /SOL last-trade
series, which DOES carry bounce and is therefore an over-estimate, biasing E[in-range] DOWN.

FALSIFICATION.  Over >= 20 positions, regress observed in-range duration on a^2/sigma^2 with
sigma measured over each position's own life.  Slope 1, intercept 0.  A slope far from 1 means
the price is not diffusive at the position's scale (drift or jumps dominate), which is exactly
the failure mode that makes concentrated LPing lose.  This is the measurement that turns the
"in-range time fraction" -- named by RESULT_power_gate.md sec.2.7 as "the single largest
unquantified term" -- into a number, and the position history to do it already exists.

WHAT CONTROL THEORY SAYS THAT A NAIVE THRESHOLD DOES NOT.  Three things, all standard, all
with teeth here:

  1. DEAD-ZONE, not a set-point.  The optimal policy is (s,S): act only at the band edge, then
     jump to the interior.  Never chase the price.  A rule that recentres "when the price moves
     x%" from wherever it is has a set-point, not a dead-zone, and it churns.

  2. THE RE-ENTRY POINT IS NOT THE CENTRE.  For a symmetric plant it is, but a DLMM position
     that exits at the LOWER edge is 100% in the base token, and re-centring requires selling
     half of it at the worst price of the excursion.  The asymmetric-cost impulse solution
     re-enters SHORT of centre (biased toward the side you already hold), which reduces the
     rebalance swap.  Quantifying it needs the swap cost as a function of the re-entry offset
     and is a one-dimensional optimisation the desk could run per position.  NOT DONE HERE --
     flagged as the one piece of this section that is derivable and undone.

  3. HYSTERESIS IS ALREADY THERE AND IS NOT FREE.  The fee band is a dead-zone (sec.4) and the
     bin grid is a second one.  Adding a rebalance dead-zone on top gives a cascade of three,
     and the total lost motion adds.  A rebalance threshold TIGHTER than the fee band is pure
     cost -- it cannot capture anything, because inside the band the price does not move at
     all.  That is a hard floor on the threshold and it is not in any of the LP literature:

             rebalance threshold  >  fee band  =  SUM of fees around the rebalance cycle
"""
    )


# ======================================================================================
# SECTION 8.  eta, MEASURED ON CHAIN
# ======================================================================================


def cmd_eta(_args: argparse.Namespace) -> None:
    print(BAR)
    print("8.  eta MEASURED FROM VAULT BALANCES  --  the LP's edge in one dimensionless number")
    print(BAR)
    print(
        """
sec.4 reduced the whole IL/fee question to  eta > VR(T).  eta is measurable from the tape
alone, because the tape carries per-swap vault pre/post for every PumpSwap pool
(`replay_sufficient: true`), and for x.y = k the marginal price is EXACTLY y/x.  This is the
on-chain read RESULT_circuit_model.md sec.7.3 named as the fix for its 150 bps ceiling.

        eta  ==  2 f N / (C . RV)

    N  = notional traded (sum of |quote-leg delta| over swaps)   -- measured
    C  = TVL/4                                                   -- measured
    RV = realised variance of the pool's own MARGINAL price      -- measured, on chain
    f  = LP fee rate                                             -- known (assumed for PumpSwap)

eta == 1 exactly on pure arbitrage flow (sec.2), so (eta - 1) is the non-arbitrage share of
fee revenue in units of LVR, and the LP's net rate is 1/2 C RV (eta - VR).
"""
    )
    pools = fetch_dexscreener_pools()
    tvl = {p["pair"]: p["tvl"] for p in pools if p["dex"] == "pumpswap"}
    print(f"{'pool':>12} {'swaps':>7} {'hours':>7} {'N (quote)':>13} {'TVL $':>10} "
          f"{'RV':>9} {'TV':>9} {'2f TV/RV':>10} {'eta':>9}")
    print(f"{'':>12} {'':>7} {'':>7} {'':>13} {'':>10} {'':>9} {'':>9} "
          f"{'(theory=1)':>10} {'(=1 arb)':>9}")
    results = {}
    for label, addr in CPMM_POOLS.items():
        quote = SOL
        notional, prices = tape_notional_and_price(addr, quote)
        if len(prices) < 20:
            print(f"{label:>12} {len(prices):>7} {'--- too few swaps ---':>60}")
            continue
        prices.sort()
        t0, t1 = prices[0][0], prices[-1][0]
        hours = (t1 - t0) / 3600.0
        lp = [math.log(p) for _, p in prices]
        rets = [b - a for a, b in zip(lp, lp[1:])]
        rv = sum(r * r for r in rets)
        tv = sum(abs(r) for r in rets)
        # quote-leg notional is in SOL; convert both N and TVL to the same unit by working
        # in SOL: TVL_sol = TVL_usd / sol_usd.  Use DexScreener's own usd/native ratio.
        sol_usd = next((p["price_usd"] / p["price_native"] for p in pools
                        if p["pair"] == label and p["price_native"] > 0), 76.0)
        tvl_usd = tvl.get(label, float("nan"))
        C_sol = (tvl_usd / sol_usd) / 4.0
        N = sum(notional)
        f = PUMPSWAP_LP
        eta = 2 * f * N / (C_sol * rv) if rv > 0 and C_sol == C_sol else float("nan")
        results[label] = {"eta": eta, "rv": rv, "tv": tv, "hours": hours, "N": N, "C": C_sol}
        print(f"{label:>12} {len(prices):>7} {hours:>7.1f} {N:>13,.3f} {tvl_usd:>10,.0f} "
              f"{rv:>9.5f} {tv:>9.4f} {2 * f * tv / rv if rv > 0 else float('nan'):>10.4f} "
              f"{eta:>9.4f}")
    print(
        """
The `2f TV/RV` column is a DIRECT test of the local-time relation of sec.2(a): for a pool
whose price is dragged only by marginal arbitrage against a diffusive external price, the
pool's total variation is exactly RV/(2f) and the column reads 1.00.  It does not, and the
direction is informative: a value BELOW 1 means the pool's marginal price moves in fewer,
larger steps than band-crossing arbitrage would produce -- i.e. the price is being moved by
takers who cross several bands at once, or it is gapping.  That is the jump regime of
sec.2(d), where the LP loses.

eta is the same statistic weighted by notional rather than by price movement, and it is the
one that decides the LP's sign.  Sensitivity to the ASSUMED PumpSwap LP fee leg:
"""
    )
    if results:
        print(f"{'pool':>12} " + "".join(f"{f'f={f:.2%}':>12}" for f in PUMPSWAP_LP_SWEEP))
        for label, r in results.items():
            row = []
            for f in PUMPSWAP_LP_SWEEP:
                e = 2 * f * r["N"] / (r["C"] * r["rv"]) if r["rv"] > 0 else float("nan")
                row.append(f"{e:>12.4f}")
            print(f"{label:>12} " + "".join(row))
    print(SUB)
    print("THE JUMP BUDGET -- sec.2(d) applied to the tape, in SOL")
    print(SUB)
    print(
        """
Theorem 2(d): the LP's loss to arbitrage is 1/2 C SUM (|z| - f)_+^2 over moves that GAP the
band.  Every swap in the tape carries the pool's marginal price before and after, so |z| per
swap is measured directly.  Compare against the naive LVR = 1/2 C RV, and against the fee
income f N.  The concentration of the loss is the point.
"""
    )
    print(f"{'pool':>12} {'fee income':>11} {'1/2 C RV':>10} {'gap loss':>10} {'gaps':>6} "
          f"{'top-1 share':>12} {'top-5 share':>12} {'worst gap':>10}")
    for label, addr in CPMM_POOLS.items():
        _, prices = tape_notional_and_price(addr, SOL)
        if len(prices) < 20:
            continue
        prices.sort()
        lp_ = [math.log(p) for _, p in prices]
        rets = [b - a for a, b in zip(lp_, lp_[1:])]
        sol_usd = next((p["price_usd"] / p["price_native"] for p in pools
                        if p["pair"] == label and p["price_native"] > 0), 76.0)
        C_sol = (tvl.get(label, float("nan")) / sol_usd) / 4.0
        f = PUMPSWAP_LP
        rv = sum(r * r for r in rets)
        losses = sorted((0.5 * C_sol * (abs(r) - f) ** 2 for r in rets if abs(r) > f),
                        reverse=True)
        tot = sum(losses)
        N = sum(x for x in read_notional(addr, SOL))
        print(f"{label:>12} {f * N:>11.4f} {0.5 * C_sol * rv:>10.4f} {tot:>10.4f} "
              f"{len(losses):>6} {(losses[0] / tot if tot else 0):>11.1%} "
              f"{(sum(losses[:5]) / tot if tot else 0):>11.1%} "
              f"{max((abs(r) for r in rets), default=0):>10.2%}")
    print(
        """
`gap loss` sits close to `1/2 C RV` rather than far below it, which is the tape saying these
prices move in GAPS, not in a band-crossing diffusion -- consistent with the `2f TV/RV` column
above being ~0.1 rather than ~1.  And the top-5 share is the operational fact: a handful of
swaps carry most of the LP's arbitrage loss over a whole session.  That is why a bounded LP
position is killed by one directional run and not by ordinary churn, and it is why an LP
metric averaged over a quiet window is not evidence of anything.

CAVEAT, and it is not small: |z| here is the move in the pool's OWN marginal price between
consecutive swaps, which conflates the arbitrageur's correction with the informed taker's
push.  The theorem's z is the mispricing against an external reference, and for these tokens
there may be no external reference at all.  So read `gap loss` as an UPPER bound on the
arbitrage component and a measurement of total adverse selection, which is the quantity that
actually matters to the LP anyway.
"""
    )

    print(SUB)
    print("THE TOKEN-TOKEN POOL, which is the one the desk's business rests on")
    print(SUB)
    print(
        """
A DLMM has no reserve-ratio price, so eta needs the pair's efficient volatility from
elsewhere.  Build it from the two /SOL pools' MARGINAL prices (exact, from vaults) aligned on
a 5-minute grid, over exactly the window the token-token tape covers.  C = position value / W
from the operator's own measured range.  N from the tape.  f from the pool config.
"""
    )
    for label, addr in DLMM_POOLS.items():
        a, b = label.split("/")
        cfg = fetch_meteora_config(addr)
        if not cfg:
            continue
        quote = MINTS[b]
        notional, _ = tape_notional_and_price(addr, quote)
        rows = read_tape_sizes(addr)
        if len(rows) < 20 or not notional:
            print(f"  {label}: only {len(rows)} swaps in the tape -- not measurable")
            continue
        t0, t1 = rows[0]["block"], rows[-1]["block"]
        rv = ratio_rv_from_vaults(a, b, t0, t1, grid_s=300)
        if rv != rv:
            print(f"  {label}: could not build the ratio series")
            continue
        f = cfg["base_fee_pct"] / 100.0 * (1.0 - cfg["protocol_fee_pct"] / 100.0)
        qprice = next((p["price_usd"] for p in pools if p["pair"] == f"{b}/SOL"), float("nan"))
        n_usd = sum(notional) * qprice
        print(f"  {label}:  window {(t1 - t0) / 3600.0:.2f} h,  {len(rows)} swaps,  "
              f"N = ${n_usd:,.0f},  f_LP = {f:.3%},  RV(ratio) = {rv:.5f}")
        print(f"{'':>6}{'position value T':>18} {'W':>8} {'C = T/W':>10} {'eta':>9} "
              f"{'verdict':>22}")
        for T, W, src in ((842.0, 1.005, "power_gate 08-13"), (465.58, 0.8572, "live 08-14"),
                          (842.0, 4.0, "as if constant product")):
            C = T / W
            eta = 2 * f * n_usd / (C * rv) if rv > 0 else float("nan")
            print(f"{'':>6}{T:>18,.0f} {W:>8.4f} {C:>10,.0f} {eta:>9.2f} "
                  f"{('+EV vs a random walk' if eta > 1 else '-EV') + '  ' + src:>22}")
        print()
    print(
        """
READ THE CONCENTRATION ROW.  eta is INVERSELY proportional to C, so a MORE concentrated
position has a LOWER eta on the same flow -- concentration is leverage on (eta - VR), and it
levers the loss exactly as hard as the gain (sec.4).  The "as if constant product" row is the
same pool run unconcentrated, and its eta is 4/W times higher.  That is the honest statement
of what 4/W does and it is the opposite sign to the intuition that concentration "earns more".

The conclusion does not turn on the assumed PumpSwap fee: eta is far below 1 across the whole
swept range for every token/SOL pool in this cluster.  At eta < VR(T) the LP is -EV, and VR
would have to be BELOW eta -- i.e. the price would have to be far more mean-reverting than
sec.4 measures -- for the sign to flip.

That is the same verdict marketfabric reached ("LP is -EV") for token/SOL pools, reached here
from an entirely different direction and with the fee tier as the explicit lever.  What it
adds is WHY, and therefore what fixes it: eta is LINEAR in f, so a pool at 5.5% has an eta
27x that of the same pool at 0.20%, on the same flow.  The desk's token-token pools clear
eta > 1 for exactly that reason and nothing else -- not concentration (leverage, sec.4), not
turnover (RESULT_power_gate.md sec.2.2 already closed that identity without it).
"""
    )


# ======================================================================================
# live data adapters
# ======================================================================================


_DEX_CACHE: list[dict] | None = None


def fetch_dexscreener_pools() -> list[dict]:
    global _DEX_CACHE
    if _DEX_CACHE is not None:
        return _DEX_CACHE
    out: dict[str, dict] = {}
    for mint in list(MINTS.values()):
        d = _get_retry(f"https://api.dexscreener.com/token-pairs/v1/solana/{mint}")
        if not d:
            continue
        for p in d:
            if p.get("chainId") != "solana":
                continue
            addr = p.get("pairAddress")
            if not addr or addr in out:
                continue
            bs = (p.get("baseToken") or {}).get("symbol", "?")
            qs = (p.get("quoteToken") or {}).get("symbol", "?")
            liq = p.get("liquidity") or {}
            out[addr] = {
                "addr": addr,
                "dex": p.get("dexId", "?"),
                "pair": f"{bs}/{qs}",
                "tvl": float(liq.get("usd") or 0.0),
                "vol24": float((p.get("volume") or {}).get("h24") or 0.0),
                "txns24": sum((p.get("txns") or {}).get("h24", {}).values()) if (p.get("txns") or {}).get("h24") else 0,
                "price_native": float(p.get("priceNative") or 0.0),
                "price_usd": float(p.get("priceUsd") or 0.0),
                "labels": tuple(p.get("labels") or ()),
            }
        time.sleep(0.35)
    _DEX_CACHE = sorted(out.values(), key=lambda r: -r["tvl"])
    return _DEX_CACHE


_OHLCV_CACHE: dict[str, list[tuple[int, float]]] = {}


def fetch_ohlcv(pool_addr: str, limit: int = 1000) -> list[tuple[int, float]]:
    """Hourly closes, oldest first, in the pool's own token/token units."""
    if pool_addr in _OHLCV_CACHE:
        return _OHLCV_CACHE[pool_addr]
    d = _get_retry(
        f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_addr}"
        f"/ohlcv/hour?aggregate=1&limit={limit}&currency=token"
    )
    if not d:
        _OHLCV_CACHE[pool_addr] = []
        return []
    rows = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    out = [(int(r[0]), float(r[4])) for r in rows if r and r[4]]
    out.sort()
    _OHLCV_CACHE[pool_addr] = out
    return out


_MET_CACHE: dict[str, dict | None] = {}


def fetch_meteora_config(pool_addr: str) -> dict | None:
    if pool_addr in _MET_CACHE:
        return _MET_CACHE[pool_addr]
    d = _get_retry(f"https://dlmm.datapi.meteora.ag/pools/{pool_addr}")
    cfg = None
    if d and isinstance(d.get("pool_config"), dict):
        cfg = dict(d["pool_config"])
        cfg["tvl"] = d.get("tvl")
        cfg["dynamic_fee_pct"] = d.get("dynamic_fee_pct")
        cfg["current_price"] = d.get("current_price")
    _MET_CACHE[pool_addr] = cfg
    return cfg


OPERATOR_WALLET = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"


_POS_CACHE: list[dict] | None = None


def fetch_operator_positions() -> list[dict]:
    """Live DLMM positions, read from the Meteora datapi (read-only, keyless).

    Endpoints as used by scripts/meteora_lp_report.py:
        GET /portfolio/open?user=<wallet>              -> pools[] with binStep/baseFee/balances
        GET /positions/<pool>/pnl?user=<wallet>        -> positions[] with min/max price, bins
    """
    global _POS_CACHE
    if _POS_CACHE is not None:
        return _POS_CACHE
    out: list[dict] = []
    d = _get_retry(f"https://dlmm.datapi.meteora.ag/portfolio/open"
                   f"?user={OPERATOR_WALLET}&page=1&page_size=50")
    for pool in (d or {}).get("pools", []):
        addr = pool.get("poolAddress")
        if not addr:
            continue
        q = _get_retry(f"https://dlmm.datapi.meteora.ag/positions/{addr}/pnl"
                       f"?user={OPERATOR_WALLET}&status=open&page_size=50")
        for it in (q or {}).get("positions", []):
            try:
                lo, hi = float(it["minPrice"]), float(it["maxPrice"])
                if lo <= 0 or hi <= lo:
                    continue
                lb, ub = int(it["lowerBinId"]), int(it["upperBinId"])
                active = it.get("poolActiveBinId")
                fees = float(((it.get("allTimeFees") or {}).get("total") or {}).get("usd") or 0.0)
                unclaimed = float(((it.get("unclaimedFees") or {}).get("total") or {}).get("usd")
                                  or pool.get("unclaimedFees") or 0.0)
                created = float(it.get("createdAt") or 0.0)
                updated = float(it.get("updatedAt") or time.time())
                out.append({
                    "pair": f"{pool.get('tokenX', '?')}/{pool.get('tokenY', '?')}",
                    "pool": addr,
                    "bins": ub - lb + 1,
                    "bin_step": pool.get("binStep"),
                    "base_fee": float(pool.get("baseFee") or 0.0) / 100.0,
                    "W": math.log(hi / lo),
                    "value": float(pool.get("balances") or 0.0),
                    "fees": fees + unclaimed,
                    "age_h": (updated - created) / 3600.0 if created else float("nan"),
                    "in_range": "yes" if (active is None or lb <= active <= ub) else "NO",
                    "at_edge": (active is not None and active in (lb, ub)),
                })
            except (TypeError, ValueError, KeyError):
                continue
    _POS_CACHE = out
    return out


# ======================================================================================
# main
# ======================================================================================


def cmd_all(args: argparse.Namespace) -> None:
    for fn in (cmd_identities, cmd_arb, cmd_available, cmd_filter, cmd_power, cmd_eta,
               cmd_route, cmd_control):
        fn(args)
        print()


CMDS = {
    "identities": cmd_identities,
    "arb": cmd_arb,
    "available": cmd_available,
    "filter": cmd_filter,
    "power": cmd_power,
    "eta": cmd_eta,
    "route": cmd_route,
    "control": cmd_control,
    "all": cmd_all,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=sorted(CMDS), nargs="?", default="all")
    args = ap.parse_args()
    CMDS[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
