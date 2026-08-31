#!/usr/bin/env python3
"""DLMM liquidity-provision strategy: width, rebalancing, fee tier, pair selection.

This study owns exactly two files: ``studies/lp_strategy.py`` and
``studies/RESULT_lp_strategy.md``. It reads ``state/cluster_tape/`` (read-only) and,
with ``--live``, the public Meteora data API. It writes nothing anywhere.

WHAT THIS IS FOR
----------------
``studies/RESULT_power_gate.md`` established that the desk's one measured edge is a
FEE-TIER rent: the operator's token-token DLMM pools charge 5.5-6.0% against a
substitute route (token -> SOL -> token) that costs a fraction of that. What nobody had
done is ask how to *run* such a pool: how wide, when to re-center, what fee, which pairs.
Those four questions are answered here from a single accounting identity, derived below
and validated three ways (against a discrete bin-level simulator, against the operator's
live position composition, and against the pool's own realised tape).

THE IDENTITY EVERYTHING RESTS ON
--------------------------------
A Meteora DLMM position with the "Spot" shape puts equal *liquidity* ``L`` in every bin.
A bin at price ``p`` satisfies the constant-sum invariant ``x*p + y = L``, so crossing one
bin trades exactly ``L`` of quote value -- independent of the price. Writing
``delta = ln(1+bin_step/1e4)`` for the log-width of a bin and ``ell = L/delta`` for the
liquidity per unit of log price, the position is completely described by three numbers:

    a     = ln(P_now / P_lower)      how far the range extends below the current price
    b     = ln(P_upper / P_now)      how far it extends above
    ell   = quote value traded per unit of log price moved

and its whole economics follows:

    VOLUME through the position  =  ell * (total variation of the pool's log price,
                                           clipped to the range)
    FEES                         =  f_lp * VOLUME
    VALUE(m)  in quote units     =  ell * [ a + m + 1 - exp(m-b) ]      for m in [-a, b]
    HOLD(m)                      =  ell * [ a + (1 - exp(-b)) * exp(m) ]
    IL(m) = VALUE - HOLD         =  ell * ( 1 + m - exp(m) )            for m in [-a, b]

The last line is the concentrated-liquidity impermanent loss done right. It is exact for
the DLMM Spot shape, it is PATH-INDEPENDENT (only the net displacement ``m`` enters), and
it is symmetric in sign to second order: ``IL ~ -ell * m^2 / 2`` for moves in either
direction. Compare the full-range constant-product closed form, ``IL_cp ~ -V * m^2 / 8``:
with ``ell = V / w_eff`` where ``w_eff = a + 1 - exp(-b)``, the ratio is exactly

    IL_concentrated / IL_full_range  =  4 / w_eff

which is 3.4x to 5.3x on the operator's live book. Any tool that uses the full-range
formula on a concentrated position -- marketfabric's ``il_vs_hold`` does -- understates
the loss by that factor. Outside the range the position is 100% one token and the loss
grows without bound (see ``SpotPosition.il_quote``); the full-range formula never says so.

Put the two halves together and the P&L of a DLMM position over any path is

    PnL(vs hold)  =  f_lp * ell * TV_in_range(path)  +  ell * ( 1 + m_T - exp(m_T) )

-- long total variation, short the exponential of the net displacement. That is the whole
model. Everything in this file is a consequence of it plus measurements of TV and m.

FEE ACCOUNTING, AND THE BUG THIS FILE IS BUILT TO NOT HAVE
----------------------------------------------------------
A prior simulator credited down-move fees to the fee bucket AND subtracted them from LP
reserves, so LPs only earned on up-moves and roughly half of fee income vanished on chop
-- the exact regime an LP wants. Here fees live in ``fees_x``/``fees_y`` buckets that the
swap math never reads (which is also what Meteora does: fees accrue outside the bin
reserves and are withdrawn by ``claim_fee2``), and ``--selftest`` asserts that an
up-then-down round trip accrues a strictly positive fee in BOTH tokens and returns every
bin to its exact starting reserves. If that test does not run, do not trust a number here.

USAGE
-----
    uv run python studies/lp_strategy.py                 # everything, offline
    uv run python studies/lp_strategy.py --measure       # just the tape measurements
    uv run python studies/lp_strategy.py --selftest      # just the invariants
    uv run python studies/lp_strategy.py --width --rebalance --fee --pairs
    uv run python studies/lp_strategy.py --live          # + check shape vs the real book
    uv run python studies/lp_strategy.py --json          # machine-readable

Deterministic: every Monte Carlo path is drawn from a seeded ``random.Random``.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
import statistics as st
import sys
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Sequence

# --------------------------------------------------------------------------------------
# Provenance-carrying constants. Everything here was measured, and says where.
# --------------------------------------------------------------------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAPE = os.path.join(REPO, "state", "cluster_tape", "swaps")

WSOL = "So11111111111111111111111111111111111111112"
WALLET = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"

#: Resolved on chain by ``shitcoims_cluster/pools.py`` (vault mints, not symbols).
TOKEN_SOL_POOLS: dict[str, str] = {
    "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn": "weave",
    "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc": "nosis",
    "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU": "DREGG",
    "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr": "SOLVE",
}
DLMM_POOLS: dict[str, tuple[str, str, float]] = {
    # pool -> (base symbol, quote symbol, base_fee_pct/100 as configured)
    "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD": ("weave", "nosis", 0.060),
    "FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD": ("DREGG", "nosis", 0.050),
}
MINT_PREFIX = {"weave": "8PecVcCG", "nosis": "FPfi9q1A", "DREGG": "XkeTXo11", "SOLVE": "GwyWFsDK"}

#: Meteora keeps 10% of the base fee as protocol fee; the LP receives the rest.
#: ``RESULT_power_gate.md`` Sec 2.3: base_fee_pct 6.0, protocol_fee_pct 10.0 -> LP 5.4%,
#: independently corroborated by 5.51-5.60% measured from chain vault deltas around a
#: ``claim_fee2``. The 10% share is the number that matters below: the LP is charged the
#: FULL band on adverse selection but only collects 90% of it.
PROTOCOL_FEE_SHARE = 0.10

#: SOL/USD at the run that produced RESULT_lp_strategy.md. Only rescales USD columns.
SOL_USD_DEFAULT = 75.95

#: The substitute route the fee tier is priced against: token -> SOL -> token, two
#: PumpSwap legs. TWO DIFFERENT NUMBERS, and conflating them has caused trouble already:
#:   * what the TAKER pays: 1.44% per leg, decoded from the pool config in
#:     ``RESULT_edge_creation.md`` Sec 1. This is what sets the substitute's price and
#:     therefore the fee-tier ceiling AND the cost of a re-centering swap.
#:   * what the LP RECEIVES: 0.200% per leg, measured here from constant-product
#:     inversion on chain (``measure_pumpswap_fee``), flat at p10 and p90 on all four
#:     pools. This is what sets the token/SOL LP alternative's yield.
#: The 1.24pp gap is protocol + creator. ``RESULT_power_gate.md`` carried the taker leg as
#: "up to 1.10%" and flagged it as its weakest inherited assumption; 1.44% decoded settles
#: it, and it is HIGHER than the bound that section called absurd.
PUMPSWAP_TAKER_FEE = 0.0144
PUMPSWAP_LP_FEE = 0.0020
SUBSTITUTE_ROUND_TRIP_LOW = 2 * PUMPSWAP_LP_FEE  # the LP-received floor, for reference
SUBSTITUTE_ROUND_TRIP_HIGH = 2 * PUMPSWAP_TAKER_FEE  # what a taker or a re-centring swap pays
#: A re-centering swap is a TAKER action, so it pays the taker rate. Using the LP leg here
#: understates it by 7x.
RECENTER_SWAP_COST = SUBSTITUTE_ROUND_TRIP_HIGH

#: Solana execution cost of one position rebuild, measured in kind rather than assumed:
#: two transactions (close + open) at ~5,000 lamports base + priority. The 0.057 SOL of
#: position rent seen in ``RESULT_lp_history.md`` is RECOVERED on close, so it is a locked
#: balance, not a cost. This is the number Cartea-Drissi-Monga measure as $84.80 on
#: Ethereum; it is the whole reason their conclusion does not transfer.
GAS_PER_REBUILD_SOL = 0.0002


# --------------------------------------------------------------------------------------
# A. DATA -- the tape, read-only
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Swap:
    t: int
    slot: int
    pool: str
    dex: str
    token_in: str
    token_out: str
    amt_in: float
    amt_out: float
    fee_payer: str | None
    vaults: tuple[dict, ...]


def load_swaps(pool: str) -> list[Swap]:
    """Every ``kind == swap`` record for a pool, in (block_time, slot) order."""
    out: list[Swap] = []
    for path in sorted(glob.glob(os.path.join(TAPE, f"{pool}-*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("kind") != "swap":
                    continue
                dec = {}
                for v in r.get("reserves", {}).get("vaults", []) or []:
                    dec[v["mint"]] = int(v["decimals"])
                ti, to = r.get("token_in_mint"), r.get("token_out_mint")
                if ti is None or to is None:
                    continue
                out.append(
                    Swap(
                        t=r["chain"]["block_time"],
                        slot=r["chain"]["slot"],
                        pool=pool,
                        dex=r.get("dex", "?"),
                        token_in=ti,
                        token_out=to,
                        amt_in=int(r["token_in_raw"]) / 10 ** dec.get(ti, 6),
                        amt_out=int(r["token_out_raw"]) / 10 ** dec.get(to, 6),
                        fee_payer=r.get("fee_payer"),
                        vaults=tuple(r.get("reserves", {}).get("vaults", []) or []),
                    )
                )
    out.sort(key=lambda s: (s.t, s.slot))
    return out


def pumpswap_price_series(pool: str) -> list[tuple[int, float]]:
    """(t, SOL-per-token) from POST vault reserves. Marginal price, not executed price.

    The *level* is biased on weave/SOL and nosis/SOL -- their vaults hold balances that
    are not on the swap curve (``measure_pumpswap_fee`` fits the offset; it is +20%/+27%
    on weave and -2%/+2.5% on nosis). A stock that size barely moves over six hours, so
    log-RETURNS are clean and levels are not. Everything downstream uses returns.
    """
    series: list[tuple[int, float]] = []
    for s in load_swaps(pool):
        d = {v["mint"]: v for v in s.vaults}
        if WSOL not in d or len(d) != 2:
            continue
        sol = d[WSOL]
        tok = next(v for v in s.vaults if v["mint"] != WSOL)
        q = int(sol["post_raw"]) / 10 ** int(sol["decimals"])
        base = int(tok["post_raw"]) / 10 ** int(tok["decimals"])
        if q > 0 and base > 0:
            series.append((s.t, q / base))
    return series


def token_price_series() -> dict[str, list[tuple[int, float]]]:
    return {sym: pumpswap_price_series(pool) for pool, sym in TOKEN_SOL_POOLS.items()}


def step_sample(series: Sequence[tuple[int, float]], grid: Sequence[int]) -> list[float | None]:
    """Last observation carried forward onto ``grid``. No interpolation, no look-ahead."""
    times = [t for t, _ in series]
    out: list[float | None] = []
    for g in grid:
        i = bisect_right(times, g)
        out.append(series[i - 1][1] if i > 0 else None)
    return out


def ratio_panel(dt: int, prices: dict[str, list[tuple[int, float]]] | None = None):
    """log(P_a / P_b) for every unordered pair, on a common grid of step ``dt`` seconds."""
    prices = prices or token_price_series()
    prices = {k: v for k, v in prices.items() if v}
    lo = max(v[0][0] for v in prices.values())
    hi = min(v[-1][0] for v in prices.values())
    grid = list(range(lo, hi + 1, dt))
    sampled = {k: step_sample(v, grid) for k, v in prices.items()}
    syms = sorted(prices)
    panel: dict[str, list[float]] = {}
    for i, a in enumerate(syms):
        for b in syms[i + 1 :]:
            xs = [
                math.log(sampled[a][k] / sampled[b][k])
                for k in range(len(grid))
                if sampled[a][k] and sampled[b][k]
            ]
            panel[f"{a}/{b}"] = xs
    return panel, (lo, hi), grid


def dlmm_exec_series(pool: str) -> list[dict]:
    """Executed prices out of the DLMM tape. Meteora vault reserves do NOT give the price
    (a DLMM's price is its active bin, not a reserve ratio), so the executed ratio is all
    there is -- and it straddles the mid by the fee, which ``mid`` undoes."""
    base_sym, quote_sym, base_fee = DLMM_POOLS[pool]
    bp, qp = MINT_PREFIX[base_sym], MINT_PREFIX[quote_sym]
    rows: list[dict] = []
    for s in load_swaps(pool):
        if s.amt_in <= 0 or s.amt_out <= 0:
            continue
        if s.token_in.startswith(bp):  # base in, quote out -> a SELL of base
            px, side, q_amt = s.amt_out / s.amt_in, "sell_base", s.amt_out
        elif s.token_in.startswith(qp):
            px, side, q_amt = s.amt_in / s.amt_out, "buy_base", s.amt_in
        else:
            continue
        mid = px * (1 - base_fee) if side == "buy_base" else px / (1 - base_fee)
        rows.append(
            {
                "t": s.t,
                "exec": px,
                "mid": mid,
                "side": side,
                "quote_amt": q_amt,
                "in_is_quote": side == "buy_base",
                "amt_in": s.amt_in,
                "fee_payer": s.fee_payer,
            }
        )
    return rows


# --------------------------------------------------------------------------------------
# B. MEASUREMENT
# --------------------------------------------------------------------------------------


def diffs(xs: Sequence[float]) -> list[float]:
    return [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]


def per_day_sd(xs: Sequence[float], dt: int) -> float:
    d = diffs(xs)
    return st.pstdev(d) * math.sqrt(86400.0 / dt) if len(d) > 2 else float("nan")


def overlapping_var(xs: Sequence[float], k: int) -> float:
    """Var of k-step overlapping increments, with the Lo-MacKinlay unbiasing factor."""
    n = len(xs) - 1
    if n <= k:
        return float("nan")
    mu = (xs[-1] - xs[0]) / n
    m = (n - k + 1) * (1 - k / n)
    if m <= 0:
        return float("nan")
    s = sum((xs[i + k] - xs[i] - k * mu) ** 2 for i in range(n - k + 1))
    return s / m


def variance_ratio(xs: Sequence[float], k: int) -> float:
    """VR(k) = Var(k-step)/(k*Var(1-step)). 1 = random walk, <1 = mean reversion.

    This is THE pair-selection statistic (see ``rank_pairs``): the LP's fee income is
    proportional to the total variation of the price at the fee-band timescale, and its
    impermanent loss is proportional to the squared net displacement at the holding
    timescale. Their ratio is exactly VR. AR(1) half-lives cannot be estimated on a
    5.8-hour window against a claimed 7-9 hour half-life; VR at k <= 60 can.
    """
    v1 = overlapping_var(xs, 1)
    vk = overlapping_var(xs, k)
    return vk / (k * v1) if v1 and v1 > 0 else float("nan")


def block_bootstrap_vr(xs: Sequence[float], k: int, reps: int, rng: random.Random) -> tuple[float, float]:
    """Percentile CI for VR(k) from a circular block bootstrap on the increments.

    Block length ``2k`` so the resampled series preserves dependence out past the horizon
    the statistic is about. With ~700 30-second observations and k=60 this is a weak
    instrument and the CI says so; that is the point of computing it.
    """
    d = diffs(xs)
    n = len(d)
    if n < 4 * k:
        return (float("nan"), float("nan"))
    bl = 2 * k
    nb = n // bl
    out = []
    for _ in range(reps):
        seq: list[float] = []
        for _ in range(nb):
            s0 = rng.randrange(n)
            seq.extend(d[(s0 + j) % n] for j in range(bl))
        lv = [0.0]
        for v in seq:
            lv.append(lv[-1] + v)
        vr = variance_ratio(lv, k)
        if vr == vr:
            out.append(vr)
    if len(out) < 10:
        return (float("nan"), float("nan"))
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out))])


def sigma_at_horizon(prices: dict, horizon_s: float, pair: str) -> float:
    """Per-day sd of the log ratio measured at a sampling interval near ``horizon_s``.

    Volatility is not one number: it is a function of the horizon you look at, and for
    these pairs it FALLS with the horizon (temporary price impact reverting). The LP
    cares about two different points on that curve, so the curve is the object.
    """
    best, bestgap = float("nan"), None
    for dt in (30, 60, 120, 300, 600, 900, 1800):
        panel, _, _ = ratio_panel(dt, prices)
        if pair not in panel or len(panel[pair]) < 8:
            continue
        gap = abs(math.log(dt) - math.log(max(horizon_s, 1.0)))
        if bestgap is None or gap < bestgap:
            best, bestgap = per_day_sd(panel[pair], dt), gap
    return best


def band_crossing_horizon(f_band: float, sigma_per_day: float) -> float:
    """Seconds for the ratio to diffuse across the no-arbitrage band of half-width f.

    A pool with fee ``f`` only trades against arbitrage when the reference price has run
    more than ``f`` away, so ``tau = (f/sigma)^2`` is the timescale at which the pool's
    own price process lives. Everything about fee income must be evaluated at ``tau``,
    not at whatever sampling interval was convenient.
    """
    if sigma_per_day <= 0:
        return float("nan")
    return (f_band / sigma_per_day) ** 2 * 86400.0


def solve_band_horizon(prices: dict, pair: str, f_band: float) -> tuple[float, float]:
    """Fixed point of tau = (f/sigma(tau))^2 -- self-consistent band timescale and vol."""
    tau = 300.0
    sig = float("nan")
    for _ in range(24):
        sig = sigma_at_horizon(prices, tau, pair)
        if sig != sig or sig <= 0:
            return (float("nan"), float("nan"))
        new = band_crossing_horizon(f_band, sig)
        if new != new or new <= 0:
            return (float("nan"), float("nan"))
        tau = math.exp(0.5 * math.log(tau) + 0.5 * math.log(new))
    return (tau, sig)


def measure_pumpswap_fee(pool: str) -> dict:
    """Invert the constant-product rule on each swap to recover the LP fee that stayed.

    ``out = pre_out * x / (pre_in + x)`` with ``x = in * (1 - g)`` gives ``g`` in closed
    form from the vault deltas alone. On DREGG/SOL and SOLVE/SOL this returns 0.200% flat
    at p10 and p90 -- which is the first direct measurement of the PumpSwap LP leg this
    program has had; ``RESULT_power_gate.md`` Sec 2.3 flagged inheriting it as its weakest
    link. On weave/SOL and nosis/SOL the raw inversion is antisymmetric in the trade side
    (+9.1%/-9.3%, +4.6%/-4.4%), which no fee can be; a two-parameter reserve offset
    (curve reserve != vault balance) removes it and returns 0.20% there too. So: 0.20%,
    four for four, and two of the pools hold ~20-27% of off-curve balance in their vaults.
    """
    recs = []
    for s in load_swaps(pool):
        d = {v["mint"]: v for v in s.vaults}
        if WSOL not in d or len(d) != 2:
            continue
        sol = d[WSOL]
        tok = next(v for v in s.vaults if v["mint"] != WSOL)
        recs.append(
            (
                s.token_in == WSOL,
                int(sol["pre_raw"]),
                int(tok["pre_raw"]),
                int(sol["delta_raw"]),
                int(tok["delta_raw"]),
            )
        )

    def implied(alpha: float, beta: float) -> tuple[list[float], list[float]]:
        gb, gs = [], []
        for sol_in, S, T, dS, dT in recs:
            Se, Te = S * (1 - alpha), T * (1 - beta)
            if sol_in:
                din, dout, pre_in, pre_out = dS, -dT, Se, Te
            else:
                din, dout, pre_in, pre_out = dT, -dS, Te, Se
            if din <= 0 or dout <= 0 or pre_out <= dout:
                continue
            g = 1 - (dout * pre_in / (pre_out - dout)) / din
            (gb if sol_in else gs).append(g)
        return gb, gs

    gb0, gs0 = implied(0.0, 0.0)
    raw = sorted(gb0 + gs0)
    best = (float("inf"), 0.0, 0.0, float("nan"), float("nan"))
    for i in range(-60, 61):
        for j in range(-60, 61):
            a, b = i * 0.005, j * 0.005
            gb, gs = implied(a, b)
            if not gb or not gs:
                continue
            mb, ms = st.median(gb), st.median(gs)
            score = abs(mb - ms) + abs(mb - 0.002) + abs(ms - 0.002)
            if score < best[0]:
                best = (score, a, b, mb, ms)
    return {
        "n": len(raw),
        "raw_median": st.median(raw) if raw else float("nan"),
        "raw_buy_median": st.median(gb0) if gb0 else float("nan"),
        "raw_sell_median": st.median(gs0) if gs0 else float("nan"),
        "offset_sol": best[1],
        "offset_token": best[2],
        "fee_buy": best[3],
        "fee_sell": best[4],
    }


def measure_dlmm_pool(pool: str, quote_usd: float) -> dict:
    """Realised total variation, volume, trade sizes and payer count for a DLMM pool.

    ``tv_mid`` is the total variation of the fee-adjusted mid, which is the quantity that
    multiplies ``ell`` to give volume. ``tv_exec`` is the raw executed-price path and is
    inflated by the 2f bid-ask bounce; it is reported so the size of that correction is
    visible rather than assumed.
    """
    rows = dlmm_exec_series(pool)
    if len(rows) < 3:
        return {"pool": pool, "n": len(rows)}
    span_h = (rows[-1]["t"] - rows[0]["t"]) / 3600.0
    tv_mid = sum(abs(math.log(rows[i]["mid"] / rows[i - 1]["mid"])) for i in range(1, len(rows)))
    tv_exec = sum(abs(math.log(rows[i]["exec"] / rows[i - 1]["exec"])) for i in range(1, len(rows)))
    net = math.log(rows[-1]["mid"] / rows[0]["mid"])
    sizes_q = sorted(r["quote_amt"] * quote_usd for r in rows)
    # Fee is charged on the token going IN. Quote-denominate every leg at the running mid.
    vol_in_quote = 0.0
    for r in rows:
        vol_in_quote += r["amt_in"] * (1.0 if r["in_is_quote"] else r["mid"])
    n = len(sizes_q)
    return {
        "pool": pool,
        "pair": f"{DLMM_POOLS[pool][0]}/{DLMM_POOLS[pool][1]}",
        "base_fee": DLMM_POOLS[pool][2],
        "n": n,
        "span_h": span_h,
        "tv_mid": tv_mid,
        "tv_mid_per_day": tv_mid / span_h * 24 if span_h else float("nan"),
        "tv_exec_per_day": tv_exec / span_h * 24 if span_h else float("nan"),
        "net_move": net,
        "vol_in_usd": vol_in_quote * quote_usd,
        "vol_usd_per_day": vol_in_quote * quote_usd / span_h * 24 if span_h else float("nan"),
        "size_median": st.median(sizes_q),
        "size_mean": sum(sizes_q) / n,
        "size_cv": st.pstdev(sizes_q) / (sum(sizes_q) / n),
        "size_p90": sizes_q[int(0.9 * n)],
        "size_max": sizes_q[-1],
        "payers": len({r["fee_payer"] for r in rows}),
        "sides": dict(Counter(r["side"] for r in rows)),
    }


# --------------------------------------------------------------------------------------
# C. MODEL -- exact DLMM Spot-shape position, continuum and discrete
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpotPosition:
    """A DLMM Spot position: uniform liquidity ``ell`` per unit log price over [-a, +b].

    Displacement ``m`` is measured in log price from the price at which the position was
    opened. Values are in QUOTE units. ``a`` and ``b`` are both positive.
    """

    a: float
    b: float
    ell: float

    @property
    def w_eff(self) -> float:
        """Value-weighted width. ``value(0) = ell * w_eff``, so ``ell = V / w_eff``."""
        return self.a + 1.0 - math.exp(-self.b)

    @property
    def value0(self) -> float:
        return self.ell * self.w_eff

    @classmethod
    def from_value(cls, value: float, a: float, b: float) -> "SpotPosition":
        return cls(a=a, b=b, ell=value / (a + 1.0 - math.exp(-b)))

    # -- composition -------------------------------------------------------------------
    def quote_held(self, m: float) -> float:
        return self.ell * (self.a + min(max(m, -self.a), self.b))

    def base_held_value(self, m: float) -> float:
        """Value (in quote) of the base token still held, at displacement ``m``."""
        mm = min(max(m, -self.a), self.b)
        return self.ell * (math.exp(-mm) - math.exp(-self.b)) * math.exp(m)

    def value_quote(self, m: float) -> float:
        return self.quote_held(m) + self.base_held_value(m)

    def hold_quote(self, m: float) -> float:
        return self.ell * (self.a + (1.0 - math.exp(-self.b)) * math.exp(m))

    def il_quote(self, m: float) -> float:
        """Exact impermanent loss in quote units. Always <= 0.

        In range this is ``ell * (1 + m - exp(m))``; outside it the position is 100% one
        token and the loss keeps growing -- linearly against the quote if the base kept
        falling, exponentially if it kept rising. The full-range constant-product formula
        has no such branch, which is the second way it flatters a concentrated position.
        """
        return self.value_quote(m) - self.hold_quote(m)

    def il_geomean(self, m: float) -> float:
        """The same loss re-expressed in the ratio-neutral numeraire sqrt(P_base*P_quote).

        For a token-token pool the quote is not money, so "value" depends on which token
        you call the yardstick; this is the choice that treats the two symmetrically.
        """
        return self.il_quote(m) * math.exp(-m / 2.0)

    def overlap(self, m0: float, m1: float) -> float:
        """Length of [m0, m1] that lies inside the range -- the fee-earning part of a move."""
        lo, hi = (m0, m1) if m0 <= m1 else (m1, m0)
        return max(0.0, min(hi, self.b) - max(lo, -self.a))

    def in_range(self, m: float) -> bool:
        return -self.a <= m <= self.b


def il_full_range_cp(value: float, m: float) -> float:
    """Full-range constant-product IL: ``V * (2*sqrt(R)/(1+R) - 1)``, R = exp(m).

    This is the closed form marketfabric's ``il_vs_hold`` applies to concentrated
    positions. It is correct for a v2/PumpSwap pool and wrong by ``4/w_eff`` for a DLMM
    range -- and it saturates at -100% instead of continuing past range exit.
    """
    r = math.exp(m)
    return value * (2.0 * math.sqrt(r) / (1.0 + r) - 1.0)


@dataclass
class BinLadder:
    """Discrete bin-level DLMM used only to VALIDATE ``SpotPosition`` and the fee wiring.

    Bins ``j`` in [j_lo, j_hi] hold ``x*p_j + y = L``. Fees never enter bin reserves --
    they go to ``fees_base``/``fees_quote`` and stay there, which is both what Meteora
    does (``collect_fee_mode 0`` accrues outside the swap invariant, withdrawn by
    ``claim_fee2``) and what makes an up-then-down round trip restore reserves exactly.
    """

    step: float  # bin_step as a fraction, e.g. 0.03 for bin_step 300
    j_lo: int
    j_hi: int
    j_active: int
    liq: float  # L per bin, in quote units
    p_ref: float = 1.0
    x: dict[int, float] = field(default_factory=dict)
    y: dict[int, float] = field(default_factory=dict)
    fees_base: float = 0.0
    fees_quote: float = 0.0
    vol_base_in: float = 0.0
    vol_quote_in: float = 0.0
    frac: float = 0.0  # how far through the active bin, 0 = bottom edge, 1 = top edge

    def __post_init__(self) -> None:
        # frac is the fraction of a bin's liquidity already converted to QUOTE:
        # y = frac*L and x = (1-frac)*L/p, so x*p + y = L always. Bins below the active
        # one are fully quote (frac 1), bins above are fully base (frac 0).
        for j in range(self.j_lo, self.j_hi + 1):
            self._set_bin(j, 1.0 if j < self.j_active else (self.frac if j == self.j_active else 0.0))

    def _set_bin(self, j: int, frac: float) -> None:
        self.y[j] = frac * self.liq
        self.x[j] = (1.0 - frac) * self.liq / self.price(j)

    def price(self, j: int) -> float:
        return self.p_ref * (1.0 + self.step) ** j

    @property
    def log_price(self) -> float:
        return math.log(self.price(self.j_active)) + self.frac * math.log1p(self.step)

    def value_quote(self, at_log_price: float | None = None) -> float:
        p = math.exp(at_log_price) if at_log_price is not None else math.exp(self.log_price)
        return sum(self.y.values()) + p * sum(self.x.values())

    def _to_frac(self, target: float, f: float) -> None:
        """Move the ACTIVE bin to ``target`` conversion, charging the fee on the token IN.

        Both branches are written the same way on purpose: the up leg charges quote in,
        the down leg charges base in, and NEITHER ever removes the fee from the bin. The
        prior simulator's bug was exactly this -- a fee credited to the bucket and also
        deducted from reserves on one leg only -- so this is the load-bearing method.
        """
        j = self.j_active
        cur = self.frac
        if target > cur:  # price rising: pool sells base, receives quote
            d_quote = (target - cur) * self.liq
            gross = d_quote / (1.0 - f)
            self.fees_quote += gross - d_quote
            self.vol_quote_in += gross
        elif target < cur:  # price falling: pool buys base, receives base
            d_base = (cur - target) * self.liq / self.price(j)
            gross = d_base / (1.0 - f)
            self.fees_base += gross - d_base
            self.vol_base_in += gross
        self._set_bin(j, target)
        self.frac = target

    def move_to(self, target_log_price: float, f: float) -> None:
        """Walk the pool price to ``target_log_price``, crossing bins and charging fees.

        Movement beyond [j_lo, j_hi+1) is clipped: out of range the position holds one
        token and earns nothing, which is the single most expensive fact in the file.
        """
        d = math.log1p(self.step)
        u = (target_log_price - math.log(self.p_ref)) / d
        jt = math.floor(u)
        ft = u - jt
        if jt > self.j_hi:
            jt, ft = self.j_hi, 1.0
        if jt < self.j_lo:
            jt, ft = self.j_lo, 0.0
        while jt > self.j_active:
            self._to_frac(1.0, f)
            self.j_active += 1
            self.frac = self.y[self.j_active] / self.liq
        while jt < self.j_active:
            self._to_frac(0.0, f)
            self.j_active -= 1
            self.frac = self.y[self.j_active] / self.liq
        self._to_frac(ft, f)


# --------------------------------------------------------------------------------------
# D. SIMULATOR -- continuum path engine (the one the sweeps use)
# --------------------------------------------------------------------------------------


@dataclass
class Regime:
    """A ratio process. ``sigma`` and ``theta`` are per DAY, in log units."""

    sigma: float
    theta: float = 0.0  # 0 = random walk; >0 = OU with half-life ln2/theta days
    drift: float = 0.0
    jump_rate: float = 0.0  # jumps per day
    jump_sd: float = 0.0  # log size of a jump
    name: str = ""

    @property
    def half_life_h(self) -> float:
        return math.log(2.0) / self.theta * 24 if self.theta > 0 else float("inf")

    @property
    def stationary_sd(self) -> float:
        return self.sigma / math.sqrt(2.0 * self.theta) if self.theta > 0 else float("inf")


@dataclass
class TakerModel:
    """Uninformed flow. Lognormal sizes fitted to the DLMM tape (median $15.4, CV 1.36).

    ``price_sensitive`` decides the whole fee-tier question: a size-aware taker compares
    ``f + q/(2*ell)`` against the substitute route and defects when ours is dearer, while
    a captive taker routes direct regardless. The tape shows the operator's pool charging
    ~3-11x the substitute and still taking flow, so real behaviour is somewhere between,
    and ``captive_share`` is the honest name for what we do not know.
    """

    rate_per_day: float
    size_median_usd: float
    size_cv: float
    captive_share: float = 1.0
    substitute_cost: float = SUBSTITUTE_ROUND_TRIP_HIGH
    substitute_ell_usd: float = 21_000.0  # ell of the two-leg SOL route, measured below

    def sigma_ln(self) -> float:
        return math.sqrt(math.log(1.0 + self.size_cv**2))

    def draw(self, rng: random.Random) -> float:
        return self.size_median_usd * math.exp(self.sigma_ln() * rng.gauss(0.0, 1.0))

    def wins(self, q_usd: float, f: float, ell_usd: float, rng: random.Random) -> bool:
        if rng.random() < self.captive_share:
            return True
        ours = f + q_usd / (2.0 * max(ell_usd, 1e-9))
        theirs = self.substitute_cost + q_usd / (2.0 * self.substitute_ell_usd)
        return ours <= theirs


@dataclass
class SimResult:
    fees: float = 0.0
    il_open: float = 0.0
    il_realized: float = 0.0
    costs: float = 0.0
    volume: float = 0.0
    taker_volume: float = 0.0
    arb_volume: float = 0.0
    in_range_time: float = 0.0
    total_time: float = 0.0
    rebuilds: int = 0
    position_value: float = 0.0
    hold_value: float = 0.0

    @property
    def harvest(self) -> float:
        """THE OPERATOR'S OBJECTIVE: fees collected, net of what it cost to collect them.

        Impermanent loss is deliberately NOT in here. The desk's stated position is that
        it expects to choose its exit over days and is content to hold inventory in the
        meantime, so an unrealised inventory swing is a state, not a loss. What IS a loss
        is a position sitting outside its range earning nothing -- observed live at $0/day
        against 1.76%/day in range, inside a single hour.
        """
        return self.fees - self.costs

    @property
    def pnl(self) -> float:
        """Mark-to-market against hold. The IL-minimising regime's objective, reported
        alongside so the crossover between the two is visible rather than assumed."""
        return self.fees + self.il_open - self.costs

    @property
    def in_range_frac(self) -> float:
        return self.in_range_time / self.total_time if self.total_time else float("nan")


def _holdings(pos: SpotPosition, m: float, price_at_open: float) -> tuple[float, float]:
    """(quote quantity, base quantity) held by ``pos`` when displaced by ``m``.

    Absolute quantities, not marks. Tracking these rather than a running IL number is what
    keeps rebuilds honest: a ONE-SIDED redeploy changes no quantity at all (you withdraw
    token A and redeposit token A), so it must not show up as a realised loss, while a
    SWAP genuinely rotates the basket and must. A simulator that resets an IL reference on
    every rebuild reports the first as a loss and flatters the second.
    """
    mm = min(max(m, -pos.a), pos.b)
    qq = pos.ell * (pos.a + mm)
    qb = pos.ell * (math.exp(-mm) - math.exp(-pos.b)) / price_at_open
    return qq, qb


def simulate(
    regime: Regime,
    *,
    value: float,
    a: float,
    b: float,
    f_base: float,
    days: float,
    dt_days: float,
    rng: random.Random,
    taker: TakerModel | None = None,
    rebalance: str = "none",  # none | one_sided | swap
    trigger: float = 0.0,  # log distance BEYOND the range edge that fires a rebuild
    swap_cost: float = RECENTER_SWAP_COST,
    gas_usd: float = GAS_PER_REBUILD_SOL * SOL_USD_DEFAULT,
) -> SimResult:
    """One path of the pool through one regime, in the continuum representation.

    Mechanics, in order, each step:
      1. the reference ratio moves (OU/RW + optional jumps);
      2. any taker who arrives and chooses us pushes the pool price by ``q/ell``;
      3. arbitrage drags the pool back to within ``f_base`` of the reference.
    Fees are ``f_lp * ell * |pool move clipped to the range|`` -- charged identically in
    both directions, which is the accounting the earlier simulator got wrong. Inventory is
    carried as absolute token quantities, so the benchmark is a genuine buy-and-hold of
    the opening basket and no rebuild can launder a loss into or out of it.
    """
    f_lp = f_base * (1.0 - PROTOCOL_FEE_SHARE)
    res = SimResult()
    steps = max(1, round(days / dt_days))
    sq = math.sqrt(dt_days)

    pos = SpotPosition.from_value(value, a, b)
    centre = 0.0  # log price at which the current position was opened
    p_open = 1.0  # absolute price at that open
    ref = 0.0
    pool = 0.0
    qq0, qb0 = _holdings(pos, 0.0, p_open)  # the buy-and-hold benchmark basket
    lam = (taker.rate_per_day * dt_days) if taker else 0.0

    for _ in range(steps):
        if regime.theta > 0:
            ref += -regime.theta * ref * dt_days + regime.sigma * sq * rng.gauss(0, 1)
        else:
            ref += regime.drift * dt_days + regime.sigma * sq * rng.gauss(0, 1)
        if regime.jump_rate > 0 and rng.random() < regime.jump_rate * dt_days:
            ref += regime.jump_sd * rng.gauss(0, 1)

        if taker and lam > 0 and rng.random() < min(lam, 1.0):
            q = taker.draw(rng)
            ell_usd = pos.ell  # ell is already in quote units, whatever the price level
            if taker.wins(q, f_base, ell_usd, rng):
                d = (q / max(ell_usd, 1e-9)) * (1 if rng.random() < 0.5 else -1)
                m0 = pool - centre
                pool += d
                seg = pos.overlap(m0, pool - centre)
                res.fees += f_lp * pos.ell * seg
                res.volume += pos.ell * seg
                res.taker_volume += pos.ell * seg

        target = pool
        if ref - pool > f_base:
            target = ref - f_base
        elif pool - ref > f_base:
            target = ref + f_base
        if target != pool:
            seg = pos.overlap(pool - centre, target - centre)
            res.fees += f_lp * pos.ell * seg
            res.volume += pos.ell * seg
            res.arb_volume += pos.ell * seg
            pool = target

        m = pool - centre
        res.total_time += dt_days
        if pos.in_range(m):
            res.in_range_time += dt_days

        if rebalance != "none":
            beyond = max(m - pos.b, -pos.a - m, 0.0)
            # A one-sided ladder sits with the price ON its edge, so without a floor the
            # trigger would fire every step. One bin-step of slack is the natural floor.
            if beyond > max(trigger, 0.010):
                price = math.exp(pool)
                qq, qb = _holdings(pos, m, p_open)
                equity = qq + qb * price
                if rebalance == "swap":
                    tmp = SpotPosition.from_value(equity, a, b)
                    want_quote = tmp.ell * tmp.a
                    res.costs += swap_cost * abs(qq - want_quote) + gas_usd
                    pos, p_open, centre = tmp, price, pool
                else:  # one_sided: redeploy the token you already hold. No swap.
                    res.costs += gas_usd
                    if m > 0:  # holding quote -> bid ladder below the price
                        pos = SpotPosition.from_value(equity, a + b, 1e-9)
                    else:  # holding base -> ask ladder above the price
                        pos = SpotPosition.from_value(equity, 1e-9, a + b)
                    p_open, centre = price, pool
                res.rebuilds += 1

    price = math.exp(pool)
    qq, qb = _holdings(pos, pool - centre, p_open)
    res.position_value = qq + qb * price
    res.hold_value = qq0 + qb0 * price
    res.il_open = res.position_value - res.hold_value
    return res


def run_paths(n_paths: int, seed: int, **kw) -> dict:
    rng = random.Random(seed)
    keys = ("pnl", "harvest", "fees", "il", "costs", "inr", "vol", "taker", "rebuilds")
    agg: dict[str, list[float]] = {k: [] for k in keys}
    for _ in range(n_paths):
        r = simulate(rng=rng, **kw)
        agg["pnl"].append(r.pnl)
        agg["harvest"].append(r.harvest)
        agg["fees"].append(r.fees)
        agg["il"].append(r.il_open + r.il_realized)
        agg["costs"].append(r.costs)
        agg["inr"].append(r.in_range_frac)
        agg["vol"].append(r.volume)
        agg["taker"].append(r.taker_volume)
        agg["rebuilds"].append(float(r.rebuilds))
    out = {k: sum(v) / len(v) for k, v in agg.items()}
    out["pnl_sd"] = st.pstdev(agg["pnl"])
    out["pnl_p10"] = sorted(agg["pnl"])[int(0.10 * n_paths)]
    out["pnl_p90"] = sorted(agg["pnl"])[int(0.90 * n_paths)]
    out["pnl_se"] = out["pnl_sd"] / math.sqrt(n_paths)
    out["harvest_p10"] = sorted(agg["harvest"])[int(0.10 * n_paths)]
    out["harvest_se"] = st.pstdev(agg["harvest"]) / math.sqrt(n_paths)
    out["rebuilds"] = sum(agg["rebuilds"]) / len(agg["rebuilds"])
    return out


# --------------------------------------------------------------------------------------
# E. SELF-TEST -- invariants. Nothing below is trustworthy if these do not pass.
# --------------------------------------------------------------------------------------


def selftest(verbose: bool = True) -> bool:
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and cond
        if verbose:
            print(f"  [{'PASS' if cond else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")

    if verbose:
        print("SELF-TEST")

    # --- 1. THE FEE-SYMMETRY TEST. This is the bug that invalidated the prior study. ----
    step, L, f = 0.02, 100.0, 0.05
    lad = BinLadder(step=step, j_lo=-20, j_hi=20, j_active=0, liq=L)
    x0 = dict(lad.x)
    y0 = dict(lad.y)
    p0 = lad.log_price
    lad.move_to(p0 + 6 * math.log1p(step), f)
    fees_after_up = (lad.fees_base, lad.fees_quote)
    lad.move_to(p0, f)
    check(
        "round trip up-then-down accrues fees on BOTH legs",
        lad.fees_quote > 0 and lad.fees_base > 0,
        f"quote={lad.fees_quote:.4f} base={lad.fees_base:.6f}",
    )
    check(
        "the down leg is what created the base-side fee (none existed after the up leg)",
        fees_after_up[0] == 0.0 and fees_after_up[1] > 0.0,
    )
    check(
        "round trip restores every bin reserve exactly (fees never touch reserves)",
        all(abs(lad.x[j] - x0[j]) < 1e-9 for j in x0) and all(abs(lad.y[j] - y0[j]) < 1e-9 for j in y0),
    )
    exp_leg = 6 * L * f / (1 - f)
    check(
        "up-leg quote fee equals 6 bins x L x f/(1-f)",
        abs(lad.fees_quote - exp_leg) < 1e-6,
        f"{lad.fees_quote:.6f} vs {exp_leg:.6f}",
    )
    # A chop path must earn strictly more than a one-way path of the same net displacement.
    chop = BinLadder(step=step, j_lo=-20, j_hi=20, j_active=0, liq=L)
    for _ in range(5):
        chop.move_to(p0 + 4 * math.log1p(step), f)
        chop.move_to(p0, f)
    chop.move_to(p0 + 2 * math.log1p(step), f)
    one = BinLadder(step=step, j_lo=-20, j_hi=20, j_active=0, liq=L)
    one.move_to(p0 + 2 * math.log1p(step), f)
    c_tot = chop.fees_quote + chop.fees_base * math.exp(p0)
    o_tot = one.fees_quote + one.fees_base * math.exp(p0)
    check("chop earns far more than a one-way move to the same price", c_tot > 10 * o_tot,
          f"chop={c_tot:.3f} oneway={o_tot:.3f}")

    # --- 2. discrete ladder agrees with the continuum SpotPosition ---------------------
    d = math.log1p(step)
    n_lo, n_hi = 20, 20
    # The active bin itself holds BASE at frac 0, so the base side spans n_hi+1 bins while
    # the quote side spans n_lo. Getting this half-bin wrong is a 2% value error and it is
    # the kind of thing that silently biases every simulated yield, so the test asserts it.
    a, b = n_lo * d, (n_hi + 1) * d
    ell = L / d
    pos = SpotPosition(a=a, b=b, ell=ell)
    lad2 = BinLadder(step=step, j_lo=-n_lo, j_hi=n_hi, j_active=0, liq=L)
    v_disc, v_cont = lad2.value_quote(), pos.value_quote(0.0)
    check("discrete and continuum agree on value at open", abs(v_disc / v_cont - 1) < 0.01,
          f"{v_disc:.3f} vs {v_cont:.3f}  (residual is the O(bin_step/2) discretisation term)")
    for nb in (3, 9, 15):
        lad3 = BinLadder(step=step, j_lo=-n_lo, j_hi=n_hi, j_active=0, liq=L)
        tgt = nb * d
        lad3.move_to(tgt, 0.0)  # zero fee so the comparison is pure inventory
        got, want = lad3.value_quote(), pos.value_quote(tgt)
        check(f"discrete value matches continuum at m={tgt:.3f}", abs(got / want - 1) < 0.01,
              f"{got:.4f} vs {want:.4f}")
        volq = lad3.vol_quote_in
        want_vol = ell * pos.overlap(0.0, tgt)
        check(f"discrete volume matches ell*overlap at m={tgt:.3f}", abs(volq / want_vol - 1) < 0.02,
              f"{volq:.4f} vs {want_vol:.4f}")

    # --- 3. IL is path-independent and correctly signed --------------------------------
    check("IL(0) == 0", abs(pos.il_quote(0.0)) < 1e-12)
    check("IL <= 0 everywhere", all(pos.il_quote(m) <= 1e-12 for m in
                                    [x * 0.05 for x in range(-40, 41)]))
    check("IL is second-order symmetric in +/-m", abs(pos.il_quote(0.1) / pos.il_quote(-0.1) - 1) < 0.12,
          f"{pos.il_quote(0.1):.5f} vs {pos.il_quote(-0.1):.5f}")
    lad_a = BinLadder(step=step, j_lo=-n_lo, j_hi=n_hi, j_active=0, liq=L)
    lad_a.move_to(5 * d, 0.0)
    lad_b = BinLadder(step=step, j_lo=-n_lo, j_hi=n_hi, j_active=0, liq=L)
    for tgt in (12 * d, -8 * d, 15 * d, -3 * d, 5 * d):
        lad_b.move_to(tgt, 0.0)
    check("value at m is path-independent (straight vs whipsaw)",
          abs(lad_a.value_quote() / lad_b.value_quote() - 1) < 1e-9)

    # --- 4. the 4/w_eff amplification over the full-range formula ----------------------
    for m in (0.05, 0.1, 0.2):
        conc = abs(pos.il_quote(m))
        full = abs(il_full_range_cp(pos.value0, m))
        check(f"IL amplification at m={m} equals 4/w_eff={4/pos.w_eff:.2f}x",
              abs(conc / full / (4 / pos.w_eff) - 1) < 0.10, f"measured {conc/full:.2f}x")

    # --- 5. simulator sanity ----------------------------------------------------------
    r = run_paths(200, 7, regime=Regime(sigma=1.0, name="rw"), value=1000.0, a=0.4, b=0.4,
                  f_base=0.06, days=0.25, dt_days=1 / 1440, taker=None)
    check("random walk + arb-only is a near-wash vs hold (|PnL| < 3% of capital)",
          abs(r["pnl"]) < 30.0, f"PnL={r['pnl']:+.2f} fees={r['fees']:.2f} IL={r['il']:.2f}")
    check("arb-only fees and IL are the same order (they are supposed to cancel)",
          0.4 < abs(r["fees"] / max(abs(r["il"]), 1e-9)) < 2.5,
          f"fees/|IL| = {r['fees']/max(abs(r['il']),1e-9):.2f}")
    rt = run_paths(200, 7, regime=Regime(sigma=1.0, name="rw"), value=1000.0, a=0.4, b=0.4,
                   f_base=0.06, days=0.25, dt_days=1 / 1440,
                   taker=TakerModel(rate_per_day=350, size_median_usd=15.4, size_cv=1.36))
    check("adding uninformed taker flow strictly improves PnL",
          rt["pnl"] > r["pnl"], f"{rt['pnl']:+.2f} vs {r['pnl']:+.2f}")
    rd = run_paths(200, 7, regime=Regime(sigma=1.0, drift=4.0, name="drift"), value=1000.0,
                   a=0.4, b=0.4, f_base=0.06, days=0.25, dt_days=1 / 1440, taker=None)
    check("a strong one-way drift makes it lose", rd["pnl"] < -1.0, f"PnL={rd['pnl']:+.2f}")

    # --- 6. a one-sided redeploy rotates NO inventory; a swap-recenter does ------------
    # Same path, same seed, zero fee and zero cost: the only difference between the two
    # policies is whether tokens were exchanged. If the one-sided run does not reproduce
    # the never-rebalanced run's inventory outcome, the rebuild is laundering value.
    kw = dict(regime=Regime(sigma=1.2, name="rw"), value=1000.0, a=0.25, b=0.25,
              f_base=0.06, days=1.0, dt_days=1 / 1440, taker=None, gas_usd=0.0,
              swap_cost=0.0)
    n_os = run_paths(150, 31, rebalance="one_sided", trigger=0.0, **kw)
    n_sw = run_paths(150, 31, rebalance="swap", trigger=0.0, **kw)
    check("one-sided redeploy and swap-recenter are DIFFERENT inventory outcomes",
          abs(n_os["il"] - n_sw["il"]) > 1.0, f"one_sided IL {n_os['il']:.1f} vs swap IL {n_sw['il']:.1f}")
    check("with zero costs both policies still collect fees on both legs",
          n_os["fees"] > 0 and n_sw["fees"] > 0)

    if verbose:
        print(f"  => {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return ok


# --------------------------------------------------------------------------------------
# F. STUDIES
# --------------------------------------------------------------------------------------


def study_measure(sol_usd: float, boot: int = 400) -> dict:
    print("=" * 86)
    print("MEASUREMENT -- what the tape says, before any strategy")
    print("=" * 86)
    prices = token_price_series()
    out: dict = {"pools": {}, "pairs": {}, "dlmm": {}, "pumpswap_fee": {}}

    print("\n[1] token/SOL pools (marginal price from post-swap vault reserves)")
    for sym in TOKEN_SOL_POOLS.values():
        s = prices[sym]
        if not s:
            continue
        span = (s[-1][0] - s[0][0]) / 3600
        tv = sum(abs(math.log(s[i][1] / s[i - 1][1])) for i in range(1, len(s)))
        print(f"    {sym:6s} n={len(s):5d} span={span:6.2f}h  net={math.log(s[-1][1]/s[0][1])*100:+7.2f}%"
              f"  TV={tv:6.2f} ({tv/span*24:6.2f}/day)")
        out["pools"][sym] = {"n": len(s), "span_h": span, "tv_per_day": tv / span * 24}

    print("\n[2] PumpSwap LP fee, inverted from the constant-product rule per swap")
    print("    (the substitute route's price -- power_gate Sec 2.3 called inheriting it its weakest link)")
    for pool, sym in TOKEN_SOL_POOLS.items():
        m = measure_pumpswap_fee(pool)
        out["pumpswap_fee"][sym] = m
        clean = abs(m["raw_buy_median"] - m["raw_sell_median"]) < 0.001
        tag = ("clean" if clean else
               f"needs reserve offset SOL {m['offset_sol']*100:+.1f}%"
               f" / tok {m['offset_token']*100:+.1f}%")
        print(f"    {sym:6s} n={m['n']:5d} raw buy={m['raw_buy_median']*100:+7.4f}%"
              f" sell={m['raw_sell_median']*100:+7.4f}%"
              f" -> fitted {m['fee_buy']*100:.4f}% / {m['fee_sell']*100:.4f}%   [{tag}]")

    print("\n[3] volatility signature of each ratio (per-day sd at each sampling interval)")
    print("    A FLAT row is a diffusion; a FALLING row is temporary price impact reverting,")
    print("    which is exactly what a fee-collecting LP monetises.")
    dts = (30, 60, 300, 900, 1800)
    panels = {}
    for dt in dts:
        panels[dt], window, _ = ratio_panel(dt, prices)
    span_h = (window[1] - window[0]) / 3600
    print(f"    common window {span_h:.2f} h\n")
    hdr = ("    " + f"{'pair':14s}" + "".join(f"{str(d)+'s':>10s}" for d in dts)
           + f"{'VR(30s->30m)':>14s}{'95% CI':>20s}")
    print(hdr)
    rng = random.Random(20260814)
    for pair in sorted(panels[30]):
        row = [per_day_sd(panels[dt][pair], dt) for dt in dts]
        vr = variance_ratio(panels[30][pair], 60)
        lo, hi = block_bootstrap_vr(panels[30][pair], 60, boot, rng)
        print("    " + f"{pair:14s}" + "".join(f"{v*100:9.1f}%" for v in row)
              + f"{vr:14.3f}" + f"   [{lo:.2f}, {hi:.2f}]")
        out["pairs"][pair] = {
            "sd_per_day": {str(d): v for d, v in zip(dts, row, strict=True)},
            "vr_30s_30m": vr,
            "vr_ci": [lo, hi],
        }

    print("\n[4] self-consistent fee-band timescale  tau = (f/sigma(tau))^2, at f = 6.0%")
    for pair in sorted(out["pairs"]):
        tau, sig = solve_band_horizon(prices, pair, 0.060)
        out["pairs"][pair]["band_tau_s"] = tau
        out["pairs"][pair]["sigma_band"] = sig
        if tau == tau:
            print(f"    {pair:14s} tau = {tau:8.0f}s ({tau/60:6.1f} min)   sigma(tau) = {sig*100:7.1f}%/day")

    print("\n[5] the operator's own DLMM pools, from their executed-price tape")
    for pool in DLMM_POOLS:
        quote_sym = DLMM_POOLS[pool][1]
        qs = prices.get(quote_sym) or []
        quote_usd = qs[-1][1] * sol_usd if qs else float("nan")
        m = measure_dlmm_pool(pool, quote_usd)
        out["dlmm"][m.get("pair", pool)] = m
        if m.get("n", 0) < 3:
            print(f"    {DLMM_POOLS[pool][0]}/{quote_sym:8s} n={m.get('n',0)} -- too few swaps to measure")
            continue
        print(f"    {m['pair']:14s} n={m['n']:4d} span={m['span_h']:5.2f}h"
              f"  base_fee={m['base_fee']*100:.1f}%")
        print(f"        mid TV = {m['tv_mid']:.3f} over the window -> {m['tv_mid_per_day']:6.2f}/day"
              f"   (raw exec TV {m['tv_exec_per_day']:.2f}/day, inflated by the 2f bounce)")
        print(f"        net ratio move over the window: {m['net_move']*100:+.2f}%")
        print(f"        volume-in {m['vol_in_usd']:,.0f} USD -> {m['vol_usd_per_day']:,.0f}/day")
        print(f"        trade size USD: median {m['size_median']:.2f}  mean {m['size_mean']:.2f}"
              f"  CV {m['size_cv']:.2f}  p90 {m['size_p90']:.2f}  max {m['size_max']:.2f}")
        print(f"        {m['payers']} distinct fee payers over {m['n']} swaps; sides {m['sides']}")

    # --- the load-bearing cross-check: does the band model reproduce the realised TV? ---
    print("\n[6] MODEL CHECK -- predicted vs realised total variation of the DLMM pool price")
    print("    prediction: TV_rate = sigma(tau)^2 / (2f), the total variation of a diffusion")
    print("    filtered through a no-arbitrage band of half-width f. If this is wrong, every")
    print("    fee number in this file is wrong.")
    for _pool, (bs, qs_, fb) in DLMM_POOLS.items():
        pair = f"{bs}/{qs_}"
        alt = f"{qs_}/{bs}"
        key = pair if pair in out["pairs"] else alt
        if key not in out["pairs"]:
            continue
        tau = out["pairs"][key].get("band_tau_s", float("nan"))
        sig = out["pairs"][key].get("sigma_band", float("nan"))
        meas = out["dlmm"].get(pair, {})
        if sig != sig or "tv_mid_per_day" not in meas:
            continue
        pred = sig**2 / (2 * fb)
        print(f"    {pair:14s} sigma(tau={tau/60:.1f}min) = {sig*100:.1f}%/day"
              f"  ->  predicted TV {pred:6.2f}/day   realised {meas['tv_mid_per_day']:6.2f}/day"
              f"   ratio {meas['tv_mid_per_day']/pred:.2f}x")
        out["dlmm"][pair]["tv_predicted_per_day"] = pred
        out["dlmm"][pair]["tv_model_ratio"] = meas["tv_mid_per_day"] / pred
    return out


def _pair_inputs(measured: dict) -> dict[str, dict]:
    """Turn the measurement block into the four numbers each pair's economics needs."""
    inputs = {}
    for pair, d in measured.get("pairs", {}).items():
        sd = d.get("sd_per_day", {})
        sig_band = d.get("sigma_band") or sd.get("300")
        sig_hold = sd.get("1800")
        if not sig_band or not sig_hold:
            continue
        inputs[pair] = {
            "sigma_band": sig_band,
            "sigma_hold": sig_hold,
            "vr": (sig_hold / sig_band) ** 2,
            "vr_ci": d.get("vr_ci", [float("nan")] * 2),
            "tau_min": (d.get("band_tau_s") or float("nan")) / 60,
        }
    return inputs


def study_pairs(measured: dict, f_base: float = 0.060, w_eff: float = 0.90) -> dict:
    print("\n" + "=" * 86)
    print("PAIR SELECTION -- which pairs deserve a pool")
    print("=" * 86)
    print("""
DERIVATION. Arbitrage flow through a pool with fee band f generates volume
``ell * sigma^2/(2f)`` per unit time, so it pays the LP ``f_lp * ell * sigma^2/(2f)``
= ``0.9 * ell * sigma^2/2`` -- INDEPENDENT of f. Against that, the position's IL is
``ell * m^2/2`` where m is the net displacement, accruing at ``ell * sigma_hold^2/2``.
So the arbitrage half of the book earns, per unit time,

    Pi_arb / V  =  (sigma_band^2 / (2 * w_eff)) * ( (1 - protocol_share) - VR )

with VR = sigma_hold^2 / sigma_band^2, the variance ratio between the holding horizon and
the fee-band horizon. Two consequences, and both are counter-intuitive:

  * A pool is +EV on arbitrage flow alone IFF VR < 0.90. Not "< 1": Meteora keeps 10% of
    the fee, so the LP is charged the full band on adverse selection and collects only
    nine tenths of it. That 10% is the entire margin a martingale pair has, and it is
    negative.
  * VOLATILITY IS THE FUEL, mean reversion is only the tax rate. Income scales as
    sigma^2 and the reversion term is a pure multiplier on it. A robustly mean-reverting
    but QUIET pair is the worst LP venue, not the best.
""")
    inputs = _pair_inputs(measured)
    rows = []
    for pair, d in inputs.items():
        gross = f_base * (1 - PROTOCOL_FEE_SHARE) * (d["sigma_band"] ** 2 / (2 * f_base)) / w_eff
        il = (d["sigma_hold"] ** 2 / 2) / w_eff
        rows.append(
            {
                "pair": pair,
                "sigma_band": d["sigma_band"],
                "sigma_hold": d["sigma_hold"],
                "vr": d["vr"],
                "vr_ci": d["vr_ci"],
                "gross_fee_per_day": gross,
                "il_per_day": il,
                "net_per_day": gross - il,
            }
        )
    rows.sort(key=lambda r: -r["net_per_day"])
    print(f"    {'pair':14s} {'sig_band':>9s} {'sig_hold':>9s} {'VR':>7s}"
          f" {'gross fee':>11s} {'IL':>10s} {'NET':>10s}")
    print(f"    {'':14s} {'%/day':>9s} {'%/day':>9s} {'':>7s} {'%/day':>11s} {'%/day':>10s} {'%/day':>10s}")
    for r in rows:
        print(f"    {r['pair']:14s} {r['sigma_band']*100:8.1f}% {r['sigma_hold']*100:8.1f}%"
              f" {r['vr']:7.2f} {r['gross_fee_per_day']*100:10.1f}% {-r['il_per_day']*100:9.1f}%"
              f" {r['net_per_day']*100:9.1f}%")
    print("""
    THE VR COLUMN IS MEASURED AT A 30-MINUTE HOLDING HORIZON because that is the longest
    this 5.8-hour tape supports, and THAT IS NOT THE DESK'S HOLDING HORIZON. Two
    bounce-free measurements now put VR at or near 1.00 past fifteen minutes (--eta). Set
    VR = 1 in the formula above and EVERY PAIR GOES NEGATIVE, because 0.90 - 1.00 < 0 --
    the protocol's 10% cut is more than the whole margin a martingale pair has on
    arbitrage flow. So this ranking is a ranking of MAGNITUDES under a favourable VR
    assumption, and it should be read as "which pair to run if any", not "these pairs pay".

    Read the NET column as an upper bound on the arbitrage half only; taker flow (eta
    above 0.90) is what would actually make a pool worth running, and --eta measures it at
    0.667 on the one pool where it can be measured -- BELOW the 0.90 arbitrage baseline,
    not above it.
""")
    return {"rows": rows}



def study_eta(measured: dict, sol_usd: float) -> dict:
    print("\n" + "=" * 86)
    print("THE DECISION RULE:  eta * D  >  VR  -- and this is the spine of everything else")
    print("=" * 86)
    print(r"""
RESULT_circuit_theory.md derives the parameter-free +EV condition for an LP position:

    eta  =  2*f*N / (C*RV)   =   fees / LVR          the CHURN number
    VR   =  (net move)^2 / RV                        the VARIANCE RATIO
    +EV  <=>  eta > VR

This study reached the identical condition from the DLMM bin algebra rather than from the
circuit frame, which is worth stating because two derivations landing on the same
inequality is the closest thing to independent confirmation available here. Section
--pairs computes ``(1 - protocol_share) - VR``; that IS ``eta - VR`` with eta evaluated on
pure arbitrage flow, where the band model gives eta = 1 exactly before the protocol takes
its cut and 0.90 after. Same rule, same numbers, two routes.

WHAT THE MECHANISM IS, IN ONE LINE. Fees accrue on QUADRATIC VARIATION -- every wiggle of
the whole path -- while impermanent loss depends only on the NET MOVE over the holding
period. The LP is long the entire return spectrum and short exactly one frequency. It is a
NOTCH, not a low-pass, and there is no cutoff frequency to tune.

AND THE PART THAT DECIDES THE WIDTH QUESTION. Concentration multiplies C, and BOTH sides
of the ledger are proportional to C. So 4/W is pure LEVERAGE on the sign of (eta - VR):
it cannot turn a losing pool into a winning one, it can only make whichever sign you
already have larger. ESTABLISH THE SIGN BEFORE CHOOSING THE LEVERAGE.

THIS SECTION ADDS ONE TERM THE THEORY DOES NOT CARRY: DUTY CYCLE.
Fee income accrues only while the position is IN RANGE. Divergence accrues always -- and
once the range is exited the position is 100% of one token and the loss stops being
sub-linear at all. So with D = fraction of life in range,

    +EV  <=>  eta * D  >  VR         =>   REQUIRED DUTY CYCLE   D*  =  VR / eta

That is the rebalance rule in its final form: THE REBALANCE POLICY IS A DUTY-CYCLE
CONTROLLER, and D* is what it has to hold. It is measurable live from two numbers the desk
already has or can have for free.
""")
    d = measured.get("dlmm", {}).get("weave/nosis", {})
    pairs = measured.get("pairs", {})
    key = "nosis/weave" if "nosis/weave" in pairs else "weave/nosis"
    pd = pairs.get(key, {})
    out: dict = {}
    if d.get("n", 0) >= 3 and pd:
        span_d = d["span_h"] / 24.0
        ell = REF_POSITION_VALUE / REF_POSITION_W_EFF
        f_lp = d["base_fee"] * (1 - PROTOCOL_FEE_SHARE)
        fees = f_lp * d["vol_in_usd"]
        sig = pd.get("sigma_band") or pd["sd_per_day"]["300"]
        rv = sig**2 * span_d
        lvr = ell * rv / 2.0
        eta = fees / lvr
        net = d["net_move"]
        vr_real = net**2 / rv
        il_hold = ell * (1 + net - math.exp(net))
        print("  MEASURED ON THE OPERATOR'S OWN weave/nosis TAPE WINDOW")
        print(f"    window                        {d['span_h']:.2f} h, {d['n']} swaps")
        print(f"    position value / w_eff        ${REF_POSITION_VALUE:,.2f} / {REF_POSITION_W_EFF:.3f}"
              f"  ->  C = ell = ${ell:,.0f}")
        print(f"    volume in                     ${d['vol_in_usd']:,.0f}")
        print(f"    fees at f_lp = {f_lp*100:.1f}%           ${fees:,.2f}")
        print(f"    sigma at the band horizon     {sig*100:.1f}%/day  ->  RV = {rv:.4f}")
        print(f"    LVR = C*RV/2                  ${lvr:,.2f}")
        print(f"    eta = fees / LVR              {eta:.3f}"
              f"     [RESULT_circuit_theory.md measured 0.59-0.70 at this sizing]")
        print(f"    net ratio move                {net*100:+.2f}%  ->  VR realised = {vr_real:.3f}")
        print(f"    eta > VR ?                    {eta:.3f} vs {vr_real:.3f}"
              f"  ->  {'+EV' if eta > vr_real else '-EV'} on this window")
        print(f"\n    IL vs HOLD, from this file's exact formula   ${il_hold:,.2f}")
        print(f"    fees - IL(vs hold)                          ${fees + il_hold:+,.2f}")
        print(f"    fees - LVR                                  ${fees - lvr:+,.2f}")
        out = {"eta": eta, "vr_realised": vr_real, "lvr": lvr, "fees": fees,
               "il_vs_hold": il_hold, "rv": rv, "ell": ell}
        print(r"""
    THE TWO BOTTOM LINES DISAGREE IN SIGN, AND BOTH ARE CORRECT. LVR benchmarks against a
    CONTINUOUSLY REBALANCED portfolio; IL benchmarks against HOLDING. They differ by
    exactly the factor VR, which on this window was 0.20 -- the ratio wandered far more
    than it ended up moving. So "fees minus adverse selection is negative" and "the
    position beat holding" are both true statements about the same position, and which one
    matters depends on what the desk would otherwise have done with the tokens. THIS DESK
    HOLDS THE TOKENS ANYWAY. Hold is the right benchmark, and the LVR-negative reading
    should not be quoted as a loss without that qualifier.

    It does NOT rescue the programme, because the realised record is against hold too:
    RESULT_edge_creation.md, 10 closed positions, $879 of fees, -$130.80 net and -$595.14
    against holding the deposited baskets. One favourable 5.33-hour window is not the
    distribution.
""")

    # ---- horizon-resolved VR: where does the reversion actually live? -----------------
    print("  WHERE THE REVERSION LIVES -- variance ratio between ADJACENT horizons")
    print("  A single VR(30s -> 30m) number hides which decade of the horizon axis the")
    print("  reversion sits in, and that decade is exactly what decides whether a 6% fee")
    print("  band can reach it.\n")
    dts = (30, 60, 300, 900, 1800)
    hdr = "".join(f"{f'{a}->{b}s':>13s}" for a, b in pairwise(dts))
    print(f"    {'pair':14s}" + hdr + f"{'overall':>10s}")
    horizons = {}
    for pair, pdd in sorted(pairs.items()):
        sd = pdd.get("sd_per_day", {})
        row = []
        for a, b in pairwise(dts):
            sa, sb = sd.get(str(a)), sd.get(str(b))
            row.append((sb / sa) ** 2 if sa and sb else float("nan"))
        overall = (sd.get("1800", 1) / sd.get("30", 1)) ** 2
        horizons[pair] = {"adjacent": row, "overall": overall}
        print(f"    {pair:14s}" + "".join(f"{v:13.2f}" for v in row) + f"{overall:10.2f}")
    print(r"""
    READ THE LAST TWO COLUMNS. The 300->900s and 900->1800s columns are where the desk's
    holding horizon starts, and they sit at or above 1.00 on most pairs. The reversion is
    concentrated in the 30s->300s decade -- transient price impact from individual swaps,
    reverting within minutes.

    RESULT_circuit_theory.md reaches the same conclusion from a different instrument:
    recomputing VR from PER-SWAP VAULT BALANCES rather than last-trade closes gives
    VR = 0.80-1.01 at 15m-1h on four of four pools, i.e. A RANDOM WALK, and the
    hourly-close estimates that showed strong reversion carry bid-ask bounce. SOLVE/SOL at
    4 h reads 1.50 bounce-free against 0.587 from closes.

    THIS FILE'S RATIO SERIES IS ALREADY BOUNCE-FREE -- it is built from post-swap vault
    reserves, i.e. the marginal price, not from executed prices -- and it AGREES: the
    adjacent-horizon VRs above run to 1.0 and beyond past 15 minutes. So two independent
    bounce-free measurements now say the same thing, and the 7.2-9 h half-lives in
    RESULT_swing_cluster.md, which came from last-trade closes, are the outlier.

    CONSEQUENCE, AND IT IS THE MOST IMPORTANT SENTENCE IN THIS DOCUMENT:
    TREAT VR = 1 AT THE HOLDING HORIZON AS THE WORKING ASSUMPTION. Then D* = 1/eta, and
    with eta measured at 0.59-1.08 the required duty cycle is 0.93 to 1.69 -- i.e.
    UNACHIEVABLE OR BARELY ACHIEVABLE. The pool is on the line at full duty and clearly
    losing at anything less. That is not a modelling opinion; it is the arithmetic of the
    two numbers this program has actually measured.
""")
    print("  REQUIRED DUTY CYCLE D* = VR / eta, against the two duty cycles measured")
    print("  on chain (RESULT_edge_creation.md: weave/nosis 99.4%, DREGG/nosis 49.4%)\n")
    print(f"    {'eta':>6s} |" + "".join(f"{f'VR={v:.2f}':>10s}" for v in (0.2, 0.5, 0.8, 1.0, 1.2))
          + "   verdict at D = 99.4% / 49.4%")
    rows = []
    for eta_v in (0.30, 0.59, 0.70, 0.90, 1.08, 1.50):
        cells = []
        for vr in (0.2, 0.5, 0.8, 1.0, 1.2):
            cells.append(vr / eta_v)
        ok_hi = "+EV" if eta_v * 0.994 > 1.0 else "-EV"
        ok_lo = "+EV" if eta_v * 0.494 > 1.0 else "-EV"
        rows.append({"eta": eta_v, "d_star": cells})
        print(f"    {eta_v:6.2f} |" + "".join(f"{c:10.2f}" for c in cells)
              + f"   at VR=1: {ok_hi} / {ok_lo}")
    out["duty"] = rows
    out["horizons"] = horizons
    print(r"""
    THE DREGG/NOSIS POST-MORTEM FALLS OUT OF THIS TABLE. That pool harvested BETTER per
    hour in service than weave/nosis (67.6%/day vs 57.6%/day) -- a higher eta -- and still
    lost $215.63, because its duty cycle was 49.4%. Halving D halves the left side of
    eta*D > VR and does nothing to the right side. It did not fail on pair choice, on fee
    tier, or on width. IT FAILED ON DUTY CYCLE, WHICH IS THE ONE TERM THAT IS A DECISION
    RATHER THAN A DRAW.

    So the rebalance rule is not a refinement of the strategy. It IS the strategy.
""")
    return out


def study_width(measured: dict, sol_usd: float, n_paths: int = 400) -> dict:
    print("\n" + "=" * 86)
    print("BIN WIDTH / RANGE PLACEMENT")
    print("=" * 86)
    print("""
OBJECTIVE. Maximise FEE HARVEST per unit of capital, subject to never being forced to
exit at a bad moment. Impermanent loss is reported but is not the thing being minimised:
the desk expects to choose its exit over days and is content to hold inventory meanwhile,
so the binding cost of a range exit is FOREGONE FEES, not a mark-to-market swing.

DERIVATION. At fixed capital V, narrowing the range raises liquidity density
``ell = V / w_eff`` -- and ``ell`` multiplies fee income AND impermanent loss EQUALLY,
because volume is ``ell * TV`` and IL is ``ell * (1 + m - e^m)``. So width does NOT trade
fees against IL. That kills the usual "narrow for yield, wide for safety" framing outright.
Under the harvest objective, only two of the three channels below even count:

  (W1) TIME IN RANGE -- the one that matters. Out of range the position earns zero,
       observed live in power_gate Sec 2.1 ($0/day out, 1.76%/day in, inside one hour).
       For a driftless ratio with vol sigma the expected time to leave a symmetric
       half-width h is h^2/sigma^2, so in-range LIFE scales as the SQUARE of the width
       while density -- and hence fee rate while in range -- scales as 1/h. Fees
       collected before the first exit therefore scale as h^2 * (1/h) = h: WIDER IS
       BETTER for total harvest per range-life, and the whole reason not to go wider is
       that the capital sits idle in bins the price never visits.
  (W2) DEPTH FOR TAKERS. A taker of size q pays ``f + q/(2*ell)``. Narrow means deep
       means the pool wins larger takers off the substitute route. This is the only
       channel through which narrowing raises REVENUE, and it saturates once the pool is
       deep relative to the size distribution (measured: median $15.4, p90 $190).
  (W3) THE TAIL -- suppressed under this objective. Beyond the range the position is 100%
       one token and its loss against hold is unbounded. That is the IL-minimising
       regime's concern and it re-enters at the crossover (see --crossover).

With rebuilds costing ${:.3f} in gas, "wider so I exit less often" is worth almost nothing;
the reason to be wide is that a wide range keeps earning through the move instead of
freezing, and the reason not to be is that a wide range dilutes the density that wins
takers. That is the actual trade, and it is what the sweep below prices.
""".format(GAS_PER_REBUILD_SOL * sol_usd))
    cal = calibration(measured)
    print_calibration(cal)
    inputs = _pair_inputs(measured)
    ranked = sorted(inputs.items(), key=lambda kv: -kv[1]["sigma_band"])
    results = {}
    pair, d = ranked[0]
    sig = d["sigma_band"] * cal["sigma_scale"]
    taker = TakerModel(rate_per_day=cal["taker_rate_per_1k"],
                       size_median_usd=cal["size_median"], size_cv=cal["size_cv"])
    print(f"\n  Pair: {pair}, calibrated sigma {sig*100:.0f}%/day. $1,000 of capital, 1-day")
    print("  horizon, one-sided redeploy on exit, bin_step 300 (3% per bin).")
    for reg in regime_menu(sig):
        ss = reg.stationary_sd
        print(f"\n  REGIME: {reg.name}"
              + (f"   (stationary sd {ss*100:.0f}%)" if ss == ss and ss < 1e3 else ""))
        print(f"    {'half-width h':>12s} {'bins':>6s} {'h/sigma':>8s} {'w_eff':>7s} {'4/w_eff':>8s}"
              f" {'rebuilds':>9s} {'in-range':>9s} {'HARVEST':>9s} {'%/day':>7s} {'p10':>8s}"
              f" {'IL':>9s} {'PnL/hold':>9s}")
        rows = []
        for h in (0.03, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.70, 1.00, 1.50):
            r = run_paths(n_paths, 4242, regime=reg, value=1000.0, a=h, b=h, f_base=0.060,
                          days=1.0, dt_days=1 / 1440, taker=taker, rebalance="one_sided",
                          trigger=0.0, gas_usd=GAS_PER_REBUILD_SOL * sol_usd)
            pos = SpotPosition.from_value(1000.0, h, h)
            nbins = 2 * h / math.log1p(0.03)
            rows.append({"h": h, "bins": nbins, "w_eff": pos.w_eff, "amp": 4 / pos.w_eff, **r})
            print(f"    {h:12.2f} {nbins:6.0f} {h/reg.sigma:8.2f} {pos.w_eff:7.3f} {4/pos.w_eff:8.2f}"
                  f" {r['rebuilds']:9.1f} {r['inr']*100:8.1f}% {r['harvest']:9.1f} {r['harvest']/10:6.0f}%"
                  f" {r['harvest_p10']:8.1f} {r['il']:9.1f} {r['pnl']:9.1f}")
        best = max(rows, key=lambda r: r["harvest"])
        best_pnl = max(rows, key=lambda r: r["pnl"])
        plateau = [r["h"] for r in rows if r["harvest"] >= 0.9 * best["harvest"]]
        print(f"    HARVEST-best h = {best['h']:.2f} ({best['bins']:.0f} bins); within 10% of best:"
              f" h in [{min(plateau):.2f}, {max(plateau):.2f}]"
              f" = {2*min(plateau)/math.log1p(0.03):.0f}-{2*max(plateau)/math.log1p(0.03):.0f} bins."
              f"  PnL-best h = {best_pnl['h']:.2f}")
        results[reg.name] = {"rows": rows, "best_h_harvest": best["h"],
                             "best_h_pnl": best_pnl["h"], "plateau": [min(plateau), max(plateau)]}
    print("""
    FIRST, THE CALIBRATION CHECK, BECAUSE IT IS WHAT MAKES THE REST READABLE. The
    operator's live nosis/weave position is a = 0.355, b = 0.502, i.e. h ~ 0.43. Read the
    table at h = 0.40-0.50: the simulator says 51-56%/day of harvest. The tape says
    32.1%/day (power_gate Sec 2.2, 6.07 h) to 61%/day (this study's 5.33 h window, which
    is busier). THE SIMULATOR LANDS INSIDE THE MEASURED RANGE AT THE OPERATOR'S ACTUAL
    WIDTH, without being fitted to it -- the only free parameters are the TV haircut and
    the taker residual, both taken from the tape.

    THE FIRST THING TO SAY, BECAUSE IT OVERRIDES THE SWEEP. RESULT_circuit_theory.md
    settles what concentration does: 4/W multiplies BOTH sides of the ledger, so it is
    PURE LEVERAGE ON THE SIGN OF (eta*D - VR) and cannot change that sign. This file's
    algebra says the same thing -- ell multiplies fees and IL identically. So narrowing a
    pool whose sign is negative makes it lose FASTER, and the realised record
    (RESULT_edge_creation.md: -$595.14 vs hold over 10 closed positions; divergence 4.7x
    and 8.2x the constant-product figure) says the sign has been negative. ESTABLISH THE
    SIGN WITH --eta BEFORE TOUCHING THE WIDTH. Everything below is about the magnitude of
    a quantity whose sign is decided elsewhere.

    THE ANSWER ON MAGNITUDE, AND IT IS A NEGATIVE ONE: WIDTH BARELY MATTERS, AND IT HAS NO
    INTERIOR OPTIMUM. Harvest falls roughly as h^-0.2 across the whole sweep and in all three
    regimes -- a 50x change in width (2 bins to 100 bins) moves it by less than 2x, and
    the harvest-best width is always the narrowest one offered. There is no peak to find.
    Anyone reporting an optimal DLMM width from a yield curve this flat is reporting
    simulation noise. STOP OPTIMISING WIDTH FOR YIELD; it is not there.

    The reason is structural rather than numerical. Fee income splits into an arbitrage
    part that scales as ell = V/w_eff (so 1/width, favouring narrow without limit) and a
    taker part that does not depend on width at all once the pool is deep enough to serve
    the size distribution (median $15, p90 $70). The second part is roughly a third of the
    flow and is width-blind, so it flattens the curve; the first part has no interior
    optimum, so the corner is at the narrowest width you can operate. Which means the
    binding constraint is operational, not economic:

    THE RULE, IN THE FORM THAT ACTUALLY DECIDES SOMETHING.
      A driftless ratio with volatility sigma leaves a band of half-width h centred on it
      in an expected time h^2/sigma^2, so the FIRST-EXIT RATE is N = sigma^2/h^2 per day:

          h*  =  sigma / sqrt(N)          N = rebuilds per day you can sustain

      Pick N from operations, not from yield -- how often can the desk redeploy without a
      failed transaction stranding a position, and what does each rebuild cost in
      attention? Then the width follows.

          N = 2/day   ->  h = 0.71 * sigma      N = 24/day  ->  h = 0.20 * sigma
          N = 6/day   ->  h = 0.41 * sigma      N = 100/day ->  h = 0.10 * sigma

      Read that against the REBUILDS column, which is 4-6x higher at every width, and the
      gap is instructive rather than a discrepancy: h^2/sigma^2 is the exit rate for a
      CENTRED position, while a redeployed one-sided ladder sits ON its own edge and
      re-triggers on the next small move. So the formula gives the tempo of a
      threshold policy and the column gives the tempo of a d = 0 policy, and the ratio
      between them is exactly the argument for the threshold (see --rebalance).

    CROSS-CHECK AGAINST THE OPERATOR'S OWN TEMPO. nosis/weave at h ~ 0.43 on a calibrated
    sigma of 0.92/day gives a centred first-exit rate of (0.92/0.43)^2 = 4.6 rebuilds per
    day. The August campaign ran 23 positions over roughly three days, about 8 per day
    (RESULT_lp_history.md). Same order from two independent directions, and the factor of
    ~2 sits exactly where a modest redeploy threshold would put it. The width and the
    tempo already in production are mutually consistent, which is the best evidence in
    this section that the model describes the real book rather than a toy.

    WHAT WOULD CHANGE THE ANSWER. If the taker flow is price-sensitive rather than captive
    (--fee cannot tell), narrow gets strictly better, because depth wins takers off the
    substitute route -- the corner solution hardens. If the desk moves to the
    IL-minimising regime (--crossover), the PnL/hold column takes over and the optimum
    moves WIDE (h = 1.00-1.50 in these tables), because ell multiplies the loss too. The
    two objectives disagree about width by more than an order of magnitude, and that is
    the single largest practical consequence of the objective choice in this document.

    AND THE RECOMMENDATION, WHICH IS THE CONSERVATIVE HALF OF THAT DISAGREEMENT. With
    VR = 1 as the working assumption (--eta) and the realised sign negative, the
    HARVEST-optimal corner at 2-7 bins is exactly the wrong end: it is maximum leverage on
    a negative number. Run WIDE -- h at or above 0.5, which is 34+ bins at bin_step 300,
    and is where the PnL column peaks in all three regimes -- until --eta shows eta*D > VR
    on a window longer than a day. The operator's live ranges (30 bins on nosis/weave, 69
    on weave/SOLVE) are already in that band. Do not narrow them.
""")
    return results


#: The position power_gate Sec 2.2 measured its 32.1%/day realised yield on.
REF_POSITION_VALUE = 842.49
REF_POSITION_W_EFF = 0.894


def calibration(measured: dict) -> dict:
    """Anchor the simulator to the tape instead of to the band model's own optimism.

    Two corrections, both derived from measurement rather than chosen:

    1. TV HAIRCUT. The band model predicts the pool's log-price total variation as
       sigma(tau)^2/(2f). Measured against the operator's own weave/nosis tape it comes in
       at about half that. Some of the gap is real (the pumpswap-implied ratio carries both
       legs' microstructure noise, which the true ratio does not) and some is the model
       being wrong; either way the simulator must not spend volatility the pool never saw.
       Applied as sigma -> sigma * sqrt(ratio), so simulated TV matches realised TV.

    2. TAKER RATE. Total volume through the pool, minus the arbitrage volume the band model
       accounts for, is what is left for uninformed flow. That residual, divided by the
       measured mean trade size, is the arrival rate. This is a RESIDUAL, so it inherits
       every error in term 1 -- it is a decomposition, not an observation, and the
       tension with power_gate's independent 64% single-hop figure is reported in --fee.
    """
    d = measured.get("dlmm", {}).get("weave/nosis", {})
    ratio = d.get("tv_model_ratio")
    sigma_scale = math.sqrt(ratio) if ratio and ratio > 0 else 1.0
    ell = REF_POSITION_VALUE / REF_POSITION_W_EFF
    arb_vol = ell * d.get("tv_mid_per_day", 0.0)
    total_vol = d.get("vol_usd_per_day", 0.0)
    taker_vol = max(total_vol - arb_vol, 0.0)
    mean_size = d.get("size_mean", 26.46) or 26.46
    # scale the arrival rate to a $1,000 book, the unit the sweeps use
    rate = taker_vol / mean_size * (1000.0 / REF_POSITION_VALUE)
    return {
        "tv_model_ratio": ratio,
        "sigma_scale": sigma_scale,
        "arb_vol_per_day": arb_vol,
        "total_vol_per_day": total_vol,
        "taker_vol_per_day": taker_vol,
        "taker_share": taker_vol / total_vol if total_vol else float("nan"),
        "taker_rate_per_1k": rate,
        "size_median": d.get("size_median", 15.39),
        "size_cv": d.get("size_cv", 1.36),
        "size_mean": mean_size,
    }


def print_calibration(cal: dict) -> None:
    print("    CALIBRATION (from the tape, not chosen):")
    print(f"      band model over-predicts realised TV by {1/cal['sigma_scale']**2:.2f}x"
          f"  ->  sigma scaled by {cal['sigma_scale']:.2f}")
    print(f"      measured pool volume ${cal['total_vol_per_day']:,.0f}/day; band model accounts"
          f" for ${cal['arb_vol_per_day']:,.0f}/day of arbitrage")
    print(f"      residual uninformed flow ${cal['taker_vol_per_day']:,.0f}/day"
          f" = {cal['taker_share']*100:.0f}% of volume  ->  {cal['taker_rate_per_1k']:.0f} takers/day"
          f" per $1,000 of position, median ${cal['size_median']:.2f}, CV {cal['size_cv']:.2f}")



def regime_menu(sigma: float) -> list[Regime]:
    """The three regimes every policy question below is answered under, separately.

    WHY NOT ONE FITTED REGIME. The tape's measured variance ratios (0.55-1.58 at 30
    minutes) are real, but an OU fitted to a 30-MINUTE variance ratio implies a stationary
    spread of about +/-8% -- and the operator's own weave/nosis pool printed a -26.9% net
    ratio move in 5.33 hours on that same tape. Thirty-minute reversion is temporary price
    impact; it does NOT extrapolate to the multi-day horizon the "wait for it to come
    back" thesis needs, and pretending it does would make every policy below look better
    than it is. So the reversion case here uses RESULT_swing_cluster.md's DEBIASED
    half-lives (7.2 h DREGG/SOLVE, 8.9 h weave/nosis; call it 8 h), which is a different
    measurement at the right timescale and is itself weak (n = 83, debiased rho 0.925).

    The honest position is that we cannot distinguish these three, so every recommendation
    is reported under all three and the ones that survive all three are the ones to act on.
    """
    return [
        Regime(sigma=sigma, theta=0.0, name="random walk (agnostic)"),
        Regime(sigma=sigma, theta=math.log(2) / (8.0 / 24.0), name="OU, 8 h half-life"),
        Regime(sigma=sigma, theta=0.0, drift=-0.5, name="trend, -50%/day (failure case)"),
    ]


def _theta_from_vr(vr: float, horizon_days: float) -> float:
    """Mean-reversion rate whose variance ratio at ``horizon_days`` equals ``vr``.

    For an OU, Var(X_{t+k} - X_t) = (sigma^2/theta)*(1 - e^{-theta k}), so
    VR(k) = (1 - e^{-theta k}) / (theta k). Inverted numerically; theta -> 0 as VR -> 1.
    """
    if vr >= 0.999:
        return 0.0
    lo, hi = 1e-6, 1e6
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        x = mid * horizon_days
        f = (1 - math.exp(-x)) / x
        if f > vr:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def study_rebalance(measured: dict, sol_usd: float, n_paths: int = 400) -> dict:
    print("\n" + "=" * 86)
    print("REBALANCE POLICY -- the highest-value unanswered question on this desk")
    print("=" * 86)
    _gas = GAS_PER_REBUILD_SOL * sol_usd
    _payback_s = _gas / (0.10 * 500) * 86400
    print(f"""
IT IS A DUTY-CYCLE CONTROLLER. That is the whole framing, and it comes from --eta:

    +EV  <=>  eta * D > VR,     so the policy's job is to hold  D  above  D* = VR / eta.

Fee income accrues only in range; divergence accrues always. RESULT_edge_creation.md's
DREGG/nosis post-mortem is this arithmetic in the wild: that pool harvested MORE per hour
in service than weave/nosis (67.6%/day vs 57.6%/day) and still lost $215.63, because its
duty cycle was 49.4% against weave/nosis's 99.4%. It did not fail on pair choice, fee tier
or width. RANGE EXIT IS WHAT KILLS THESE POSITIONS.

IT IS ALSO TWO DECISIONS, AND CONFLATING THEM IS WHY THE QUESTION LOOKED HARD.

  DECISION 1 -- REDEPLOY. Move the range to where the price is now, depositing the single
  token you are already holding, one-sided. No swap. No inventory change. Cost is gas:
  ${GAS_PER_REBUILD_SOL*sol_usd:.3f}. Against a position earning even 10%/day on $500, that is repaid in
  {_payback_s:.0f} SECONDS of being back in range. THERE IS NO THRESHOLD. Redeploy every
  time you go out of range, always, and the only reason to leave the old range in place
  is if you deliberately want it as a resting limit ladder at prices you prefer.

  DECISION 2 -- RE-CENTER WITH A SWAP. Buy back to a two-sided shape so you earn on moves
  in both directions. This one HAS a threshold, because it costs a swap AND -- the part
  nobody prices -- it CRYSTALLISES the inventory rotation. Under the desk's actual
  objective that crystallisation is the whole cost: the operator's plan is to hold the bag
  and choose the exit over days, and a re-centering swap converts "I am long nosis and
  will sell when it recovers" into "I sold nosis low and bought weave high", permanently.

  So the two decisions separate cleanly by objective:
    HARVEST objective (today)   -> redeploy one-sided, always; never swap to re-center.
    IL-MINIMISING objective      -> swap-re-center is the right tool, and --crossover says
                                    when that regime starts.

THE COSTS, MEASURED IN KIND RATHER THAN ASSUMED.
  * gas: two transactions, ~{GAS_PER_REBUILD_SOL} SOL = ${_gas:.3f}. Position rent (0.057 SOL,
    RESULT_lp_history.md) is RECOVERED on close, so it is locked balance, not cost.
  * swap: only if you re-center by buying back to a two-sided shape. Round trip through
    the SOL route costs {SUBSTITUTE_ROUND_TRIP_LOW*100:.2f}% (measured LP legs) to
    {SUBSTITUTE_ROUND_TRIP_HIGH*100:.2f}% (power_gate's all-in bound),
    on roughly half the book.
  * the real cost, and the one nobody prices: re-centering CRYSTALLISES the impermanent
    loss. IL is path-independent, so as long as you hold the position an adverse move is
    genuinely impermanent -- the ratio coming back undoes it for free. Buying back at the
    new price converts "sold low" into "sold low and bought high".

  THIS INVERTS THE ONLY PEER-REVIEWED RESULT IN THE AREA. Cartea, Drissi & Monga
  (SIAM J. Fin. Math. 15(3) 2024) measure recentering at $84.80 per round trip and
  conclude the strategy pays only above $1.8M of capital. That break-even is ENTIRELY
  Ethereum gas -- a fixed cost, so it sets a minimum CAPITAL. Here the fixed cost is
  ${GAS_PER_REBUILD_SOL*sol_usd:.3f} and the variable cost is a fraction of the book, so there is no minimum
  capital at all: what a rebuild has to clear is a minimum IN-RANGE TIME.

THE SWAP THRESHOLD, DERIVED.
  Let y = in-range fee yield per day (fraction of position value), theta = mean-reversion
  rate per day of the log ratio, d = how far the ratio has run BEYOND the range edge.
  A two-sided shape earns on moves in both directions, a one-sided ladder only on the
  reverting direction, so the swap buys roughly a doubling of capture: gain ~ y*V*T over
  the remaining hold T. It costs c*V/2 in swap fees, and it forfeits the reversion option,
  which over a short window is worth about (V/2)*theta*d. So

      SWAP IF   y*T  >  c/2 + (theta*d)/2      i.e.   T > c/(2y) + (theta*d)/(2y)

  The first term is the pure cost payback and it is TINY here. The second is the
  reversion forfeit and it is what actually binds. Setting T to the expected time to the
  next exit gives the operational form: SWAP ONLY IF d < d* = 2y/theta - c/theta.
""")
    inputs = _pair_inputs(measured)
    ranked = sorted(inputs.items(), key=lambda kv: -kv[1]["sigma_band"])
    out = {}
    print(f"    {'y (%/day)':>10s} {'half-life':>10s} {'theta/day':>10s} {'d* (swap if closer)':>21s}"
          f" {'swap payback':>26s}")
    for y in (0.10, 0.20, 0.32):
        for hl in (4.0, 8.0, 24.0):
            theta = math.log(2) / (hl / 24)
            print(f"    {y*100:9.0f}% {hl:9.1f}h {theta:10.2f} {2*y/theta*100:20.1f}%"
                  f"   {SUBSTITUTE_ROUND_TRIP_LOW/(2*y)*24*60:6.1f} -"
                  f" {SUBSTITUTE_ROUND_TRIP_HIGH/(2*y)*24*60:6.1f} min")
    print("""
  The payback column is the number that inverts the literature: 3 to 32 MINUTES of
  in-range fee income repays a full round-trip swap. On Ethereum the same calculation
  gives $1.8M of minimum capital (Cartea-Drissi-Monga). Here the fixed cost is so small
  that capital does not enter at all -- what a rebuild must clear is a minimum in-range
  TIME, and it is minutes.

  The d* column is the reason the answer is still "do not swap": d* lands at 5-40% while
  the operator's live ranges are 35-50% wide on each side, so a position that has just
  gone out of range is typically ALREADY past d*. The arithmetic and the operator's
  observed behaviour (positions left out of range, ladders allowed to fill) agree.
""")
    print("  SIMULATED, on the measured regimes. HARVEST is the objective; PnL-vs-hold is")
    print("  carried alongside so the disagreement between the two objectives is visible.\n")
    cal = calibration(measured)
    print_calibration(cal)
    print()
    pair, d = ranked[0]
    sig = d["sigma_band"] * cal["sigma_scale"]
    taker = TakerModel(rate_per_day=cal["taker_rate_per_1k"],
                       size_median_usd=cal["size_median"], size_cv=cal["size_cv"])
    h = 0.35
    print(f"  Pair {pair}, calibrated sigma {sig*100:.0f}%/day, range +/-{h:.2f},"
          f" 3-day horizon, $1,000.\n")
    for reg in regime_menu(sig):
        ss = reg.stationary_sd
        print(f"  REGIME: {reg.name}"
              + (f"   (stationary sd {ss*100:.0f}%)" if ss == ss and ss < 1e3 else ""))
        print(f"    {'policy':12s} {'trig d':>7s} {'rebuilds':>9s} {'in-range':>9s} {'fees':>8s}"
              f" {'costs':>7s} {'HARVEST':>9s} {'IL':>9s} {'PnL/hold':>9s}")
        rows = []
        for policy, trig in [("none", 0.0)] + [
            (p, t) for p in ("one_sided", "swap") for t in (0.0, 0.15, 0.30, 0.60)
        ]:
            r = run_paths(n_paths, 909, regime=reg, value=1000.0, a=h, b=h, f_base=0.060,
                          days=3.0, dt_days=1 / 1440, taker=taker, rebalance=policy,
                          trigger=trig, swap_cost=RECENTER_SWAP_COST,
                          gas_usd=GAS_PER_REBUILD_SOL * sol_usd)
            rows.append({"policy": policy, "trigger": trig, **r})
            print(f"    {policy:12s} {trig:7.2f} {r['rebuilds']:9.1f} {r['inr']*100:8.1f}%"
                  f" {r['fees']:8.1f} {r['costs']:7.2f} {r['harvest']:9.1f} {r['il']:9.1f}"
                  f" {r['pnl']:9.1f}")
        b_h = max(rows, key=lambda r: r["harvest"])
        b_p = max(rows, key=lambda r: r["pnl"])
        print(f"    best HARVEST: {b_h['policy']} @ d={b_h['trigger']:.2f} -> {b_h['harvest']:+.1f}"
              f" (+/-{b_h['harvest_se']:.1f});  best PnL/hold: {b_p['policy']} @"
              f" d={b_p['trigger']:.2f} -> {b_p['pnl']:+.1f} (+/-{b_p['pnl_se']:.1f})\n")
        out[reg.name] = {"rows": rows, "best_harvest": b_h, "best_pnl": b_p}
    # ---- minimax regret across the three regimes, on both objectives -----------------
    print("  ROBUST CHOICE. We cannot tell the three regimes apart, so score each policy by")
    print("  its WORST-CASE REGRET against the best policy in each regime. Percent of the")
    print("  regime's best; lower is better.\n")
    regimes = list(out)
    keys = [(r["policy"], r["trigger"]) for r in out[regimes[0]]["rows"]]
    print(f"    {'policy':12s} {'trig':>6s} | " + " | ".join(f"{'harvest':>9s} {'PnL':>7s}"
          for _ in regimes) + " |  max regret")
    print(f"    {'':12s} {'':6s} | " + " | ".join(f"{n.split(',')[0][:15]:>17s}" for n in regimes)
          + " |  harvest   PnL")
    regret_rows = []
    for k in keys:
        hs, ps = [], []
        for rn in regimes:
            rows = out[rn]["rows"]
            best_h = max(r["harvest"] for r in rows)
            best_p = max(r["pnl"] for r in rows)
            span_p = best_p - min(r["pnl"] for r in rows)
            r = next(x for x in rows if (x["policy"], x["trigger"]) == k)
            hs.append(1 - r["harvest"] / best_h if best_h else float("nan"))
            ps.append((best_p - r["pnl"]) / span_p if span_p else 0.0)
        regret_rows.append({"policy": k[0], "trigger": k[1], "regret_harvest": max(hs),
                            "regret_pnl": max(ps)})
        print(f"    {k[0]:12s} {k[1]:6.2f} | " + " | ".join(
            f"{h*100:8.0f}% {p*100:6.0f}%" for h, p in zip(hs, ps, strict=True))
            + f" | {max(hs)*100:7.0f}% {max(ps)*100:5.0f}%")
    order = sorted(regret_rows, key=lambda r: max(r["regret_harvest"], r["regret_pnl"]))
    print("\n    MINIMAX REGRET (worst of the two objectives), best three:")
    for r in order[:3]:
        mx = max(r['regret_harvest'], r['regret_pnl'])
        print(f"      {r['policy']:12s} d={r['trigger']:.2f}  ->  {mx*100:3.0f}%"
              f"   (harvest {r['regret_harvest']*100:.0f}%, PnL {r['regret_pnl']*100:.0f}%)")
    print("    worst three:")
    for r in order[-3:]:
        print(f"      {r['policy']:12s} d={r['trigger']:.2f}  ->"
              f"  {max(r['regret_harvest'], r['regret_pnl'])*100:3.0f}%")
    print("""
  THE POLICY, AND IT IS NOT THE ONE THIS SECTION SET OUT TO FIND.

  (1) THE ONLY REGIME-INDEPENDENT RESULT, AND IT IS THE BIG ONE. Doing nothing -- leaving
      a position sitting outside its range -- costs 20% to 55% of the fee income in every
      regime, because in-range time falls to 27-59%. Whatever else the desk does, capital
      should not be parked outside a range. That is worth more than everything below.

  (2) REDEPLOYING IS A BET ON THE VARIANCE RATIO AT YOUR HOLDING HORIZON, AND THE "IL IS
      NOTIONAL" ARGUMENT DOES NOT COVER IT. Under the reversion regime, redeploying at
      d = 0 buys +18% of harvest and costs $593 of inventory over three days -- and that
      $593 is NOT a mark. Both policies end the cycle valued at the SAME price; they
      differ by real tokens. The reason is mechanical: a one-sided ladder redeployed at
      the new price buys the cheap leg back starting from the new price, whereas the
      un-moved range buys it back at the old, better prices. Moving the range forfeits the
      reversion whether or not a swap is involved. So "one-sided redeploy is free because
      it rotates nothing today" is true and insufficient.

  (3) SWAP-RE-CENTERING WINS ON HARVEST IN ALL THREE REGIMES, BY 8-13%, AND IS STILL THE
      WRONG DEFAULT. It costs 11x more than a one-sided redeploy for that 8-13%, and in
      the regime the desk's own thesis assumes it is PnL-dominated by simply waiting. Take
      it only in the IL-minimising regime (--crossover) or when the rail says the
      reversion thesis is dead (--rail).

  (4) THE ROBUST ANSWER IS A MIDDLE THRESHOLD, NOT A CORNER, AND THAT IS THE ACTUAL
      RECOMMENDATION. Every minimax-regret winner is a threshold in d = 0.3 to 0.6; both
      corners -- never rebuild, and rebuild on every exit -- sit at the BOTTOM of the
      regret table. So: REDEPLOY WHEN THE RATIO HAS RUN ~0.3 TO 0.6 IN LOG TERMS (35-80%)
      BEYOND THE RANGE EDGE. That beats doing nothing on harvest in every regime, keeps
      most of the reversion option, and costs 1-4 rebuilds per position-life instead of
      ~86-113. The derived d* = 2y/theta lands in the same band for y = 15-30%/day against
      an 8 h half-life, which is the closest thing to independent confirmation available.
      Use the one-sided form by default; it is 11x cheaper for a regret difference inside
      the noise.

  (5) WHICH OF THESE SURVIVE IF THE RATIO IS A RANDOM WALK -- AND THE EVIDENCE NOW SAYS
      IT IS. Two independent bounce-free measurements (RESULT_circuit_theory.md's per-swap
      vault-balance VR of 0.80-1.01 at 15m-1h on four of four pools, and this file's own
      adjacent-horizon table in --eta) put VR at or near 1 past fifteen minutes. The
      7.2-9 h half-lives the brief treated as established came from LAST-TRADE CLOSES and
      carry bid-ask bounce. Taking VR = 1 as the working assumption:

        SURVIVES, unconditionally:
          * Never sit out of range. Under VR = 1 there is nothing to wait for, so the
            reversion option that justified waiting has value ZERO and duty cycle is the
            only lever. Result (1) goes from "the big one" to "the only one".
          * Redeploy ONE-SIDED rather than swapping. Still 20x cheaper for a difference
            inside the noise, and the swap's only advantage was two-sided capture.
          * Establish the sign before levering it (--width).

        DOES NOT SURVIVE, and is hereby labelled REVERSION-CONTINGENT:
          * The d* = 2y/theta threshold. It is derived from theta, and theta = 0 under a
            random walk, so d* = infinity and the derivation says "always redeploy".
          * The minimax-regret answer of d = 0.3-0.6 above. It is a compromise that gives
            the reversion regime one third of the weight. Strip that regime out and the
            recommendation moves to d = 0 to 0.15 in both remaining regimes.
          * "Waiting keeps the reversion option." There is no option to keep.

      SO THE RECOMMENDATION, AS THE EVIDENCE NOW STANDS: REDEPLOY ONE-SIDED AT
      d = 0 to 0.15, targeting a duty cycle above 95%. Fall back to d = 0.3-0.6 ONLY if a
      multi-day bounce-free VR comes back materially below 1. That measurement is nine
      days of tape and it is the highest-value outstanding item in the program, because it
      is the difference between two policies that differ by 20-40% of fee income.

  (6) THE HONEST CAVEAT ON ALL OF IT. Raising duty cycle raises eta*D but cannot raise it
      past eta, and eta is measured at 0.59-1.08. At VR = 1 that means a PERFECT duty
      cycle still leaves the pool at or below break-even. A rebalance rule cannot rescue a
      pool whose eta is below 1; it can only stop a pool with eta above 1 from being
      thrown away. Fixing duty cycle is necessary and not sufficient, and anyone reading
      this section as "just rebalance harder and the programme works" has read it wrong.
""")
    out["regret"] = regret_rows
    return out


def study_fee(measured: dict, sol_usd: float) -> dict:
    print("\n" + "=" * 86)
    print("FEE TIER SELECTION")
    print("=" * 86)
    print(f"""
DERIVATION. Split the flow. Write Q for uninformed taker volume per day and let the
arbitrage half be whatever the band model implies. Then

    Pi  =  f_lp * Q(f)  +  (f_lp - f) * Vol_arb(f)  -  jump excess
        =  f_lp * Q(f)  -  s * f * Vol_arb(f)  -  jump excess          s = {PROTOCOL_FEE_SHARE:.2f}

and since ``Vol_arb = ell * sigma^2 / (2f)``, the middle term is ``-s * ell * sigma^2/2``:
COMPLETELY INDEPENDENT OF f. Raising the fee tier does not earn one dollar more from
arbitrage -- crossings get rarer in exact proportion as each one gets bigger. That is
power_gate Sec 2.5's "CRUDE" model, and this study's realised-TV check gives it a number.

So the fee tier is priced entirely against uninformed flow and jumps:

    dPi/df = 0   <=>   Q + f*Q'(f) + E[jump volume] = 0
                 <=>   elasticity  eps*  =  -(1 + Vol_informed / Q)

At the tape's 36/64 informed/uninformed split that is eps* = -1.56, not the textbook -1.
You are allowed to charge MORE than a plain monopolist because a higher fee also improves
your terms of trade against the flow that is picking you off.

WHAT THE TAPE SAYS ABOUT WHERE WE ALREADY ARE, AND IT IS NOT COMFORTABLE.
""")
    # depth of the substitute route, measured
    ell_sub = {}
    for pool, sym in TOKEN_SOL_POOLS.items():
        sw = load_swaps(pool)
        if not sw:
            continue
        d = {v["mint"]: v for v in sw[-1].vaults}
        if WSOL not in d:
            continue
        q = int(d[WSOL]["post_raw"]) / 1e9 * sol_usd
        ell_sub[sym] = q / 2.0  # constant product: dY/dlogP = Y/2
    print("    constant-product depth ell = (SOL side)/2, i.e. USD traded per unit log price:")
    for sym, v in sorted(ell_sub.items(), key=lambda kv: -kv[1]):
        print(f"      {sym:6s} ell = ${v:>10,.0f}")
    route = (1.0 / (1.0 / ell_sub.get("weave", 1) + 1.0 / ell_sub.get("nosis", 1))
             if len(ell_sub) >= 2 else float("nan"))
    print(f"    two-leg weave->SOL->nosis route: effective ell = ${route:,.0f}")

    dlmm = measured.get("dlmm", {}).get("weave/nosis", {})
    _arc_eps = math.log(120.7 / 159.1) / math.log(6.0 / 5.0)
    pos_value = 842.49  # power_gate Sec 2.2, the position the realised 32.1%/day was measured on
    w_eff = 0.894
    ell_ours = pos_value / w_eff
    print(f"\n    our pool: V = ${pos_value:,.2f}, w_eff = {w_eff:.3f} -> ell = ${ell_ours:,.0f}"
          f"  ({route/ell_ours:.0f}x thinner than the substitute)")
    print(f"\n    {'trade size':>11s} {'our all-in':>11s} {'substitute all-in':>19s} {'we are':>10s}")
    rows = []
    for q in (5, 15.4, 26.4, 50, 100, 250, 500):
        ours = 0.060 + q / (2 * ell_ours)
        sub_lo = SUBSTITUTE_ROUND_TRIP_LOW + q / (2 * route)
        sub_hi = SUBSTITUTE_ROUND_TRIP_HIGH + q / (2 * route)
        rows.append({"q": q, "ours": ours, "sub_lo": sub_lo, "sub_hi": sub_hi})
        print(f"    ${q:>10,.1f} {ours*100:10.2f}% {sub_lo*100:8.2f}% - {sub_hi*100:6.2f}%"
              f" {ours/sub_hi:9.1f}x dearer")
    print(f"""
    THE POOL IS 3x TO 11x MORE EXPENSIVE THAN THE SUBSTITUTE AT EVERY SIZE, and it took
    {dlmm.get('n','?')} swaps from {dlmm.get('payers','?')} payers in {dlmm.get('span_h',0):.1f} hours anyway.
    A cost-minimising
    router does not do that. So the observed demand is NOT on a downward-sloping curve we
    can see: locally the measured elasticity is indistinguishable from ZERO, and the
    first-order condition then says the fee tier is BELOW its optimum, not above it.

    The honest reading is that we cannot see the demand curve at all, only one point on
    it. Three candidate explanations, all testable and none tested:
      (a) the flow is not price-sensitive (small tickets, direct-pool UIs, no router);
      (b) the flow is mostly arbitrage/routing, which the band model says is fee-invariant
          anyway -- in which case the fee tier does not matter for revenue and the LP is
          simply paying the {PROTOCOL_FEE_SHARE*100:.0f}% protocol share for nothing;
      (c) the substitute is not actually available to these takers (SOL-leg pools thin at
          the moment of trade, or Jupiter is not routing this pair).

    THE 2-POINT "ESTIMATE" AND WHY IT IS NOT ONE. DREGG/nosis runs base_fee 5.0% at
    159.1%/day turnover; weave/nosis runs 6.0% at 120.7%/day (both DexScreener 24h, in
    power_gate Sec 2.4). Arc elasticity = ln(120.7/159.1)/ln(6.0/5.0) = {_arc_eps:.2f}, which
    lands almost exactly on the eps* = -1.56 optimality condition. That is a coincidence
    across two different token pairs of different ages and different volatilities with
    n = 2. It is worth zero as evidence and is stated here only so nobody rediscovers it
    and believes it.
""")
    print("    WHAT THE FEE TIER DOES BUY, AND THIS PART IS DERIVED, NOT FITTED:\n")
    print("    A jump of log size J moves the pool through ell*J of volume at an average")
    print("    adverse price of J/2, so the position nets ell*J*(f_lp - J/2). The fee tier")
    print("    is exactly the size of jump the pool can absorb before a crossing loses money:\n")
    print(f"      {'base fee':>9s} {'f_lp':>7s} {'break-even jump 2*f_lp':>24s}")
    jr = []
    for fb in (0.0020, 0.010, 0.020, 0.030, 0.050, 0.060, 0.080, 0.100):
        flp = fb * (1 - PROTOCOL_FEE_SHARE)
        jr.append({"f_base": fb, "f_lp": flp, "break_even_jump": 2 * flp})
        print(f"      {fb*100:8.2f}% {flp*100:6.2f}% {2*flp*100:23.1f}%")
    print("""
    The four token/SOL pools print median single-swap price impacts of 12-42 bps and p90s
    of 100-243 bps. A 6.0% tier absorbs jumps up to 10.8% -- comfortably above the p90 and
    into the tail. A 2.0% tier absorbs only 3.6% and would be picked off by the top decile
    of prints. THAT is the defensible argument for a high tier on memecoin pairs, and it
    is independent of the monopoly story entirely.

    THE FAILURE MODE IS A STEP FUNCTION, NOT AN ELASTICITY, AND THAT CHANGES THE RISK
    MANAGEMENT COMPLETELY. RESULT_circuit_theory.md reaches the same place from the
    routing side: both token-token pools are more expensive AND thinner than the SOL
    substitute, so a cost-minimising router should send them nothing at any size, and the
    median trade through them pays 2.67x the best available route. What the desk is
    collecting is therefore ROUTER-ATTENTION RENT, not pricing power. Pricing power erodes
    when a rival undercuts you -- gradually, visibly, with a slope you can measure and
    respond to. Attention rent ends in one deploy, all at once, with no warning and no
    intermediate state. Consequences:

      * There is no interior optimum to solve for, because there is no demand curve. The
        revenue-maximising fee is "as high as the flow tolerates", and the flow's
        tolerance is unobservable until it is zero.
      * DO NOT SIZE THE BOOK TO THIS REVENUE STREAM. A stream that can go to zero between
        one block and the next is not something to lever, borrow against, or schedule
        obligations from (--exit).
      * The monitoring target is not a rival pool's fee. It is whether Jupiter is routing
        this pair through us at all, which is a free daily query against a quote API and
        is the single cheapest early warning available anywhere in this program.
      * The 5.0% vs 6.0% question is second-order against a binary that size. Do not spend
        effort there.

    RECOMMENDATION: hold 5-6% and stop reasoning about it as a monopoly rent. The
    experiment that would actually settle it costs nothing but patience: run DREGG/nosis
    at 5.0% and weave/nosis at 6.0% for two weeks with the tape recording both, then
    compare fee income per unit of ell*sigma^2 across the two. If income is flat in f, the
    flow is arbitrage and the tier is cosmetic. If it falls, you have a real elasticity
    and can solve eps* = -1.56 for the first time.
""")
    return {"substitute_ell": ell_sub, "route_ell": route, "size_rows": rows, "jump_rows": jr}


def pool_stats(sol_usd: float) -> dict[str, dict]:
    """Depth, flow and reserve trajectory for each token/SOL pool. Everything the exit
    and rail questions need, measured from the same records."""
    out: dict[str, dict] = {}
    for pool, sym in TOKEN_SOL_POOLS.items():
        sw = load_swaps(pool)
        if len(sw) < 5:
            continue
        span_h = (sw[-1].t - sw[0].t) / 3600.0
        res: list[tuple[int, float]] = []
        vol_sol = 0.0
        for s in sw:
            d = {v["mint"]: v for v in s.vaults}
            if WSOL not in d:
                continue
            res.append((s.t, int(d[WSOL]["post_raw"]) / 1e9))
            vol_sol += abs(int(d[WSOL]["delta_raw"])) / 1e9
        if not res:
            continue
        y_now = res[-1][1]
        peak = max(r[1] for r in res)
        prices = pumpswap_price_series(pool)
        lp = [math.log(p) for _, p in prices]
        n = len(lp)
        net = lp[-1] - lp[0]
        step_sd = st.pstdev(diffs(lp)) if n > 3 else float("nan")
        t_drift = net / (step_sd * math.sqrt(n - 1)) if step_sd > 0 else float("nan")
        out[sym] = {
            "pool": pool,
            "span_h": span_h,
            "sol_side": y_now,
            "sol_side_usd": y_now * sol_usd,
            "tvl_usd": 2 * y_now * sol_usd,
            "ell_usd": y_now * sol_usd / 2.0,  # constant product: dY/dlogP = Y/2
            "peak_sol_side": peak,
            "drawdown": 1.0 - y_now / peak if peak else float("nan"),
            "vol_usd_per_day": vol_sol * sol_usd / span_h * 24 if span_h else float("nan"),
            "rho2_usd": 0.02 * y_now * sol_usd,
            "net_move": net,
            "t_drift": t_drift,
            "n_swaps": n,
        }
    return out


def study_hedge(measured: dict, sol_usd: float) -> dict:
    print("\n" + "=" * 86)
    print("IS A TOKEN-TOKEN POOL PARTIALLY DELTA-HEDGED? -- testing the structural claim")
    print("=" * 86)
    print("""
THE CLAIM. A weave/nosis position's impermanent loss is driven by the RELATIVE price
only. If the whole cluster dumps together the ratio barely moves, so the LP takes the beta
but little IL, whereas a weave/SOL position takes IL against the full SOL-denominated
move. If cluster tokens co-move, token-token pools would be structurally lower-IL than
token/SOL pools at the same nominal exposure -- a third independent leg under the
strategy, unrelated to fee tier or concentration.

THE TEST, AND IT HAS A CLOSED-FORM THRESHOLD. IL is proportional to the squared volatility
of whatever price the pool quotes: sigma_ratio^2 for a token-token pool, sigma_A^2 for a
token/SOL pool on the same token. With
    sigma_ratio^2 = sigma_A^2 + sigma_B^2 - 2*rho*sigma_A*sigma_B
the token-token pool carries LESS IL variance than the average of its two SOL-quoted
alternatives exactly when

    rho  >  rho*  =  (sigma_A^2 + sigma_B^2) / (4 * sigma_A * sigma_B)   >=  1/2

-- the inequality on the right is AM-GM, with equality only when the two legs have equal
volatility. So the claim CANNOT hold at any correlation below 0.5, whatever the vols, and
needs more than 0.5 whenever the legs are mismatched. That is the number to check.
""")
    prices = token_price_series()
    dt = 60
    panel, window, grid = ratio_panel(dt, prices)
    lo, hi = window
    sampled = {k: step_sample(v, grid) for k, v in prices.items()}
    leg_sd = {}
    for sym, ser in sampled.items():
        xs = [math.log(v) for v in ser if v]
        leg_sd[sym] = per_day_sd(xs, dt)
    print(f"    common window {(hi-lo)/3600:.2f} h at {dt}s sampling\n")
    print("    SOL-denominated leg volatility (this is what drives token/SOL pool IL):")
    for sym, v in sorted(leg_sd.items(), key=lambda kv: -kv[1]):
        print(f"      {sym:6s} {v*100:8.1f}%/day")
    print(f"\n    {'pair':14s} {'sig_ratio':>10s} {'sig_A':>8s} {'sig_B':>8s} {'implied rho':>12s}"
          f" {'rho* needed':>12s} {'IL variance vs legs':>20s}  verdict")
    rows = []
    for pair in sorted(panel):
        a_sym, b_sym = pair.split("/")
        sa, sb = leg_sd.get(a_sym, float("nan")), leg_sd.get(b_sym, float("nan"))
        sr = per_day_sd(panel[pair], dt)
        rho = (sa**2 + sb**2 - sr**2) / (2 * sa * sb) if sa and sb else float("nan")
        rho_star = (sa**2 + sb**2) / (4 * sa * sb) if sa and sb else float("nan")
        # hedge factor: ratio variance vs the AVERAGE of the two legs' variances --
        # i.e. what a token-token pool costs in IL per unit ell vs a token/SOL pool.
        hf = sr**2 / ((sa**2 + sb**2) / 2)
        verdict = "HEDGED" if hf < 1 else "NOT hedged"
        rows.append({"pair": pair, "sigma_ratio": sr, "sigma_a": sa, "sigma_b": sb,
                     "rho": rho, "rho_star": rho_star, "hedge_factor": hf})
        print(f"    {pair:14s} {sr*100:9.1f}% {sa*100:7.1f}% {sb*100:7.1f}% {rho:12.2f}"
              f" {rho_star:12.2f} {hf:19.2f}x  {verdict}")
    hedged = [r for r in rows if r["hedge_factor"] < 1]
    rho_max = max((r["rho"] for r in rows), default=float("nan"))
    rho_min = min((r["rho"] for r in rows), default=float("nan"))
    print(f"""
    VERDICT: THE CLAIM IS FALSIFIED AT THIS HORIZON, {len(hedged)} of {len(rows)} pairs hedged. Measured
    implied correlations run {rho_min:+.2f} to {rho_max:+.2f} -- statistically indistinguishable from
    ZERO -- against a threshold of rho* >= 0.5. At rho = 0 the identity collapses to
    sigma_ratio^2 = sigma_A^2 + sigma_B^2, so a token-token pool carries almost exactly
    TWICE the IL-driving variance of the average of its two SOL-quoted alternatives. That
    is what the last column reports, and it is 1.9-2.0x across the board: token-token
    pools here are structurally HIGHER-IL, not lower.

    RESULT_swing_cluster.md's hourly correlations of 0.11-0.24 point the same way and are
    also far below 0.5. So the claim fails at every horizon anyone in this program has
    measured, not just at 60 seconds.

    BUT THE CONCLUSION IT WAS MEANT TO SUPPORT SURVIVES, FOR THE OPPOSITE REASON. Fee
    income and IL are BOTH proportional to sigma^2 of the quoted price. A pool with 2x the
    variance has 2x the IL and 2x the arbitrage fee income. Under the harvest objective
    that is not a cost, it is more fuel: the token-token pool is better precisely BECAUSE
    the ratio is noisier than either leg, and what decides whether the extra variance is
    kept or given back is the variance ratio in --pairs, not the correlation. "Token-token
    is partially delta-hedged" and "token-token harvests more" are contradictory
    justifications for the same position, and the tape supports the second one.

    ONE PLACE THE HEDGE IS STILL REAL, AND IT IS NOT VISIBLE HERE. A cluster-wide dump
    -- every token down together against SOL -- moves the ratio far less than it moves
    either leg. That is a DAILY-scale, correlated-shock phenomenon and a {(hi-lo)/3600:.1f}-hour window of
    60-second returns cannot contain one. So the correct statement is: the hedge does not
    exist in ordinary trading and MAY exist in a cluster-wide risk-off event, which is
    exactly the event where a token/SOL LP would be hurt most. Falsifiable and cheap: keep
    the panel running and recompute this table at dt = 3600 over a week that contains a
    market-wide down day. If rho jumps above 0.5 in that window and only in that window,
    the hedge is a tail hedge -- which would be worth having and worth saying precisely.
""")
    return {"legs": leg_sd, "rows": rows}


def study_rail(sol_usd: float) -> dict:
    print("\n" + "=" * 86)
    print("THE SAFETY RAIL -- distinguishing 'reverting, hold' from 'trending, exit'")
    print("=" * 86)
    print("""
This is the failure mode of the whole approach, stated plainly: "wait for it to come back"
is correct when the ratio oscillates and catastrophic when a token is in secular decline.
The desk's own literature review makes the same point from the other side -- what kills a
bounded LP position is one-directional drift, not a rug.

The instinct is to build a price-prediction rail. Do not. Three rails below, in increasing
order of how much they are worth, and the best one does not forecast price at all.

RAIL 1 (weakest) -- DRIFT SIGNIFICANCE. Is the observed move larger than noise?
  t = (net log move) / (per-step sd * sqrt(n)). Exit when t < -2 sustained.
  It is weak because it takes as long to reject a random walk as the drift takes to hurt.

RAIL 2 -- DEPTH DRAWDOWN. Is the pool's SOL side draining? A token in secular decline
  loses its LPs before it loses its last buyer, and the SOL-side reserve is a stock, not a
  flow, so it is far less noisy than price. Exit when the SOL side is down more than ~35%
  from its trailing peak. This is measurable from the tape with zero new instrumentation.

RAIL 3 (the one to actually run) -- FEE-FLOW DEATH. The LP thesis is "harvest volatility",
  not "the price will recover". So the correct exit signal is that THE FEE STREAM STOPPED,
  which is simultaneously the symptom of secular decline (volume dies before price
  bottoms) and the removal of the entire reason to hold the position. It needs no price
  forecast, no half-life estimate, and no view on the token.

      EXIT WHEN: realised fee accrual over the trailing 24 h falls below 1%/day of
      position value, for 24 consecutive hours, while the position is IN RANGE.

  The "in range" clause is what makes it a decline detector rather than a range detector:
  out of range you earn zero for a reason you already know how to fix (redeploy). In range
  and earning nothing means the flow is gone. Both inputs are already served by the API the
  desk reads (allTimeFees + unclaimedFee), so this is a monitoring rule, not a project.
""")
    stats = pool_stats(sol_usd)
    print(f"    {'token':7s} {'window':>8s} {'SOL side':>10s} {'peak':>10s} {'drawdown':>9s}"
          f" {'net move':>9s} {'t(drift)':>9s} {'vol/day':>12s}  rails firing")
    out = {}
    for sym, d in sorted(stats.items(), key=lambda kv: -kv[1]["sol_side"]):
        fired = []
        if d["drawdown"] > 0.35:
            fired.append("DEPTH")
        if d["t_drift"] < -2:
            fired.append("DRIFT")
        out[sym] = {**d, "rails": fired}
        print(f"    {sym:7s} {d['span_h']:7.1f}h {d['sol_side']:9.1f} {d['peak_sol_side']:9.1f}"
              f" {d['drawdown']*100:8.1f}% {d['net_move']*100:+8.1f}% {d['t_drift']:9.2f}"
              f" ${d['vol_usd_per_day']:11,.0f}  {', '.join(fired) or '-'}")
    print("""
    On this window no rail fires. That is the correct outcome for a quiet 6-30 hours and
    it is NOT evidence the rails work -- a rail that has never fired has never been
    tested. The falsification is prospective and cheap: log the rail values hourly from
    now, and when a cluster token does decay, check whether RAIL 3 fired before the price
    made its final leg. If it did not, the rail is decoration.

    A NOTE ON WHAT THE RAILS DO NOT COVER. All three are pool-level. None of them sees a
    social or contract-level failure (deploy key movement, team exit, a migration), which
    is what actually takes a "strong techproject coin" to zero. The operator's survival
    filter -- 12 for 12 with zero delistings, RESULT_lp_history.md -- is doing that job and
    nothing here replaces it.
""")
    return out


def study_exit(sol_usd: float, obligations: Sequence[tuple[str, float, int]] | None = None) -> dict:
    print("\n" + "=" * 86)
    print("EXIT CAPACITY AND DATED CASH")
    print("=" * 86)
    obligations = obligations or [("Aug 28", 900.0, 15), ("Sep 1", 1050.0, 19)]
    stats = pool_stats(sol_usd)
    print("""
The constraint the strategy brief did not have: some capital must be exitable on a KNOWN
DATE. That is the one place where "I will choose my exit over the next few days" stops
being available, and it is therefore the only place where impermanent loss is a real cost
rather than a state.

EXIT ARITHMETIC. A single swap is capped at rho = 2% of the pool's SOL side (the desk's
own sizing rule). Repeated swaps are capped by flow: taking more than ~5% of a pool's daily
volume moves the price against you for the rest of the day. So

    single-leg cap      = 0.02 * (SOL side, USD)
    one-day exit cap    = 0.05 * (24 h volume, USD)

and the EXIT WINDOW for a position of size S is  T_exit = S / (0.05 * volume_per_day).
""")
    print(f"    {'token':7s} {'SOL side':>12s} {'TVL':>12s} {'ell':>11s} {'rho=2% leg':>12s}"
          f" {'vol/day':>12s} {'1-day exit cap':>15s}")
    for sym, d in sorted(stats.items(), key=lambda kv: -kv[1]["vol_usd_per_day"]):
        print(f"    {sym:7s} ${d['sol_side_usd']:11,.0f} ${d['tvl_usd']:11,.0f}"
              f" ${d['ell_usd']:10,.0f} ${d['rho2_usd']:11,.0f} ${d['vol_usd_per_day']:11,.0f}"
              f" ${0.05*d['vol_usd_per_day']:14,.0f}")
    total_due = sum(o[1] for o in obligations)
    _d_fast = total_due / (0.321 * 1351)
    _first_pct = obligations[0][1] / 1351 * 100
    _cap_dregg = 0.05 * stats.get("DREGG", {}).get("vol_usd_per_day", 0)
    _cap_solve = 0.05 * stats.get("SOLVE", {}).get("vol_usd_per_day", 0)
    print(f"\n    DATED OBLIGATIONS: {', '.join(f'${a:,.0f} on {d} (T-{t}d)' for d, a, t in obligations)}"
          f"  -- total ${total_due:,.0f}")
    print("    Open book, this run: $1,351 in 3 positions. Realised to date: $1,449 over 42 closed.")
    print(f"""
    So the obligations are ~1.4x the CURRENT open book. This is not a diversification
    question, it is a scheduling one, and it has three answers stacked in priority order:

    (1) THE FEE STREAM IS THE FIRST SOURCE, AND IT IS PLAUSIBLY SUFFICIENT -- which is
        also the most dangerous sentence in this document. At the measured 32.1%/day gross
        (6-hour sample) the open book covers ${total_due:,.0f} in {_d_fast:.1f} days. At a defensive
        one-fifth of that it takes {total_due/(0.064*1351):.0f} days, which still clears T-15. But a 6-hour
        sample of a heavy-tailed process is not a forecast; power_gate's own answer is
        that ~9 days of tape are needed before any yield number is evidence. PLAN AS IF
        THE FEE STREAM IS ZERO and treat it as upside.

    (2) EXITABILITY, WHICH IS THE ACTUAL CONSTRAINT AND IS COMFORTABLE ON TWO TOKENS AND
        NOT ON TWO OTHERS. Position value that must become SOL by a date should sit where
        the one-day exit cap exceeds it:""")
    for sym, d in sorted(stats.items(), key=lambda kv: -kv[1]["vol_usd_per_day"]):
        cap = 0.05 * d["vol_usd_per_day"]
        verdict = "clears both obligations outright" if cap > total_due else (
            "clears the larger single obligation" if cap > max(o[1] for o in obligations)
            else f"NEEDS {total_due/cap:.1f} DAYS to clear the full amount")
        print(f"          {sym:7s} 1-day cap ${cap:>10,.0f}  ->  {verdict}")
    print(f"""
    (3) THE STRUCTURAL RULE, WHICH IS FREE. A token-token position needs TWO exit legs to
        become SOL and its fill direction is a bet on the ratio; a token/SOL position needs
        one and its fill direction is a bet on the token. So dated cash should not sit in
        token-token pools. Better: put the dated fraction in a token/SOL SELL LADDER --
        an ask-side one-sided position above the current price. It converts to SOL
        automatically as the price rises, earns fees while doing it, and needs no timing
        decision at all. That is exactly the structure the operator already runs
        (RESULT_lp_history.md: "these are ladders, not yield positions"), and it is the
        correct instrument for a dated obligation.

    THE ALLOCATION, STATED AS A FRACTION. With ${total_due:,.0f} due inside 19 days against a
    $1,351 open book:

        * By T-10 (Aug 18): at least ${obligations[0][1]:,.0f}, {_first_pct:.0f}% of the book, should be in
          token/SOL sell ladders on weave or nosis (the two pools whose one-day exit cap
          clears it), NOT in token-token pools.
        * By T-3 (Aug 25): that fraction should be FILLED or closed to SOL, not merely
          laddered. A ladder that has not filled is not cash.
        * The remaining ~{100-_first_pct:.0f}% can stay in the token-token pools where the fee
          harvest is, because it has no date on it.
        * DREGG and SOLVE exposure should carry NO dated cash at all: their one-day exit
          caps are ${_cap_dregg:,.0f} and ${_cap_solve:,.0f}, which is below a single obligation.

    FALSIFICATION: the 5%-of-daily-volume cap is a convention, not a measurement. The
    measurement that would replace it is the desk's own fill data -- score each historical
    ladder fill against the market price at that slot (RESULT_lp_history.md's own item 1),
    which converts "5% of volume" into a measured impact curve.
""")
    return {"pools": stats, "obligations": list(obligations), "total_due": total_due}


def study_crossover(measured: dict, sol_usd: float) -> dict:
    print("\n" + "=" * 86)
    print("THE CROSSOVER -- when does IL minimisation become the right objective?")
    print("=" * 86)
    print("""
Harvest-maximising and IL-minimising are not right and wrong answers; they are two
regimes, and the discriminator is exactly one thing: CAN YOU CHOOSE YOUR EXIT? While the
exit is discretionary over days, an adverse inventory swing is a state and the binding
cost is foregone fees. When exit timing stops being discretionary, the swing becomes a
loss and IL becomes the thing to minimise. Three mechanisms take away the choice.
""")
    stats = pool_stats(sol_usd)
    print("(a) SCALE -- the exit window opens up faster than size grows.\n")
    print("    T_exit = S / (0.05 * daily volume). Below is the position size at which the")
    print("    exit window reaches one day, three days and a week. Past the one-day column,")
    print("    'wait a few days for reversion' is no longer free: you are choosing between")
    print("    waiting and being able to leave.\n")
    print(f"    {'token':7s} {'vol/day':>12s} {'S(T_exit=1d)':>14s} {'S(3d)':>12s} {'S(7d)':>12s}"
          f" {'rho=2% leg':>12s}")
    rows = {}
    for sym, d in sorted(stats.items(), key=lambda kv: -kv[1]["vol_usd_per_day"]):
        s1 = 0.05 * d["vol_usd_per_day"]
        rows[sym] = {"s1": s1, "s3": 3 * s1, "s7": 7 * s1, "rho2": d["rho2_usd"],
                     "vol_per_day": d["vol_usd_per_day"]}
        print(f"    {sym:7s} ${d['vol_usd_per_day']:11,.0f} ${s1:13,.0f} ${3*s1:11,.0f}"
              f" ${7*s1:11,.0f} ${d['rho2_usd']:11,.0f}")
    g = {k: rows.get(k, {}).get("s1", 0.0) for k in ("DREGG", "SOLVE", "weave", "nosis")}
    print(f"""
    READ THIS AGAINST THE $1,351 OPEN BOOK. Per-token exposure is already ABOVE the
    one-day threshold on DREGG (${g['DREGG']:,.0f}) and SOLVE (${g['SOLVE']:,.0f}) and comfortably below
    it on weave (${g['weave']:,.0f}) and nosis (${g['nosis']:,.0f}). So the desk is ALREADY IN THE
    IL-MINIMISING REGIME FOR DREGG AND SOLVE and still in the harvest regime for weave and
    nosis. That is not a future crossover, it is a live split, and it argues for running
    the two objectives per token rather than per desk.

    The crossover moves with volume, not with the calendar. Recompute this table weekly;
    it is four numbers off the tape.

(b) DATED OBLIGATIONS -- covered in --exit. The rule there is the operational form of the
    crossover: the fraction of the book with a date on it is in the IL-minimising regime
    by definition, because its exit time is written down. $1,950 of a $1,351 book is
    dated, so {1950/1351*100:.0f}% of the current book is nominally in that regime -- which is over
    100%, and is the real finding of this section.

(c) CAPITAL EFFICIENCY -- and this one dissolves rather than binds. The argument is that
    holding a bag through a drawdown costs the yield the capital could have earned. True,
    but only if the bag is IDLE. Under the rebalance rule derived above, a bag is never
    idle: it is redeployed one-sided as a ladder and keeps earning on the reverting
    direction. The opportunity cost of "waiting" is therefore not the whole yield, it is
    the gap between one-sided and two-sided capture -- roughly a factor of two, not a
    factor of infinity.

        cost of waiting  ~  0.5 * y * T   (one-sided instead of two-sided)
        cost of not waiting ~ the crystallised rotation, ~ (V/2) * (reversion forgone)

    At y = 15%/day and a 7.2-9 h half-life, those cross at a displacement of a few tens of
    percent -- the same d* as the swap rule. So (c) does not create a new crossover; it
    re-derives the same one. The genuinely new content of (c) is the negative: NEVER LET
    INVENTORY SIT OUTSIDE A RANGE. That is the only way capital efficiency actually bites,
    and it is entirely under the desk's control.

WHAT TO WATCH, SO THE SWITCH IS DELIBERATE RATHER THAN DISCOVERED AFTERWARDS:
    * per-token exposure / (0.05 * that token's 24 h volume)  -> exit window in days.
      Switch that token to the IL-minimising objective when it exceeds ~2 days.
    * fraction of book with a date inside 3 * (exit window).   -> already IL-regime.
    * measured VR at the multi-day horizon. Every "wait for reversion" argument in this
      file is a bet that VR < 1 at the horizon you intend to wait, and the tape's 5.8-hour
      window CANNOT see the multi-day horizon. This is the single largest unmeasured term
      in the whole strategy.

WHAT CHANGES WHEN THE SWITCH HAPPENS, CONCRETELY:
    harvest regime            ->  IL-minimising regime
    one-sided redeploy        ->  swap-re-center to two-sided at d < d*
    width ~1 sigma            ->  narrower, and closed rather than redeployed on exit
    token-token pools         ->  prefer pairs with hedge factor < 1 (see --hedge)
    hold through drawdowns    ->  size to the exit window, not to the fee yield

A NOTE ON HEDGING, BECAUSE THE IL-MINIMISING REGIME IS USUALLY REACHED BY HEDGING AND
THAT ROUTE IS CLOSED HERE. There is no borrow market for these tokens, so the classical
delta-neutral LP -- short the risky leg, collect fees -- does not exist. The only hedges
on the table are within-cluster offsetting positions, and --hedge measures whether those
work. The measured answer is that they work on the quiet pairs and invert on the loud
ones, which is the wrong way round: the hedge is available exactly where you do not need
it. So for this desk the IL-minimising regime has to be reached by SIZING AND STRUCTURE
(smaller positions, shorter exit windows, token/SOL ladders for dated cash), not by
hedging. Anyone proposing a delta-neutral cluster book should be asked to name the
instrument.
""")
    return {"exit_sizes": rows}


def study_il_accounting(sol_usd: float, live: dict | None = None) -> dict:
    print("\n" + "=" * 86)
    print("INVENTORY / IL ACCOUNTING DONE RIGHT")
    print("=" * 86)
    print("""
The full-range constant-product closed form -- ``V*(2*sqrt(R)/(1+R) - 1)`` -- is what
marketfabric's ``il_vs_hold`` applies to concentrated positions. For a DLMM Spot range it
is wrong twice:
  1. it understates the loss by exactly 4/w_eff inside the range;
  2. it has no branch for range exit, where the position is 100% one token and the loss
     against hold keeps growing without bound.
""")
    live_positions = (live or {}).get("positions", [])
    if live_positions:
        rows = live_positions
    else:
        # the book as read at the run that produced RESULT_lp_strategy.md
        rows = [
            {"pair": "weave/SOL", "p_lo": 2.335e-06, "p_hi": 3.470e-06, "p_now": 2.335e-06, "value": 809.20},
            {"pair": "nosis/weave", "p_lo": 1.753506, "p_hi": 4.132252, "p_now": 2.50008, "value": 436.02},
            {"pair": "weave/SOLVE", "p_lo": 1.960676, "p_hi": 7.53733, "p_now": 3.844251, "value": 105.94},
        ]
    print(f"    {'position':14s} {'a':>7s} {'b':>7s} {'w_eff':>7s} {'4/w_eff':>8s} {'IL@10%':>10s}"
          f" {'IL@25%':>10s} {'full-range@25%':>15s}")
    out = []
    for r in rows:
        a = math.log(r["p_now"] / r["p_lo"]) if r["p_now"] > r["p_lo"] else 1e-9
        b = math.log(r["p_hi"] / r["p_now"]) if r["p_hi"] > r["p_now"] else 1e-9
        pos = SpotPosition.from_value(r["value"], a, b)
        il10, il25 = pos.il_quote(0.10), pos.il_quote(0.25)
        fr25 = il_full_range_cp(r["value"], 0.25)
        out.append({"pair": r["pair"], "a": a, "b": b, "w_eff": pos.w_eff, "amp": 4 / pos.w_eff,
                    "il_10": il10, "il_25": il25, "full_range_25": fr25})
        print(f"    {r['pair']:14s} {a:7.3f} {b:7.3f} {pos.w_eff:7.3f} {4/pos.w_eff:8.2f}"
              f" {il10:9.2f}$ {il25:9.2f}$ {fr25:14.2f}$")
    print("""
    The last two columns are the correction: on a 25% adverse ratio move the correct
    concentrated loss is 2.5x to 5x the number the full-range formula reports. On the
    -26.9% net move the weave/nosis pool actually printed over the tape window, that is
    the difference between "a rounding error" and "most of a day's fee income".
""")
    print("    Numeraire matters for a token-token pool. IL in quote units vs in the")
    print("    ratio-neutral sqrt(P_base*P_quote) numeraire, for the nosis/weave position:")
    if len(out) >= 2:
        r = rows[1]
        a = math.log(r["p_now"] / r["p_lo"])
        b = math.log(r["p_hi"] / r["p_now"])
        pos = SpotPosition.from_value(r["value"], a, b)
        print(f"      {'m':>7s} {'IL (quote)':>12s} {'IL (geomean)':>14s} {'in range':>9s}")
        for m in (-0.5, -0.25, -0.1, 0.1, 0.25, 0.5, 0.75):
            print(f"      {m:+7.2f} {pos.il_quote(m):11.2f}$ {pos.il_geomean(m):13.2f}$"
                  f" {'yes' if pos.in_range(m) else 'NO':>9s}")
    return {"rows": out}


def fetch_live_positions(wallet: str, sol_usd: float) -> dict:
    """Read the operator's open DLMM positions and test the Spot-shape model against them.

    The test is sharp and free: for a Spot position the split of value between the two
    tokens is forced to be ``a : (1 - exp(-b))``, a pure function of the range and the
    active price. Nothing about the deposit is used. If the live book matches, the model
    in this file is the right model of the operator's actual positions.
    """
    import urllib.request

    base = "https://dlmm.datapi.meteora.ag"
    ua = "joshibot-lp-strategy/1.0 (read-only)"

    def get(path: str, params: dict):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        req = urllib.request.Request(f"{base}{path}?{q}",
                                     headers={"User-Agent": ua, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as fh:
            return json.loads(fh.read().decode())

    def dig(d, *keys):
        for k in keys:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d

    out: dict = {"positions": [], "checks": []}
    try:
        port = get("/portfolio/open", {"user": wallet, "page": 1, "page_size": 50})
    except Exception as exc:  # pragma: no cover - network
        print(f"    live fetch failed: {exc}")
        return out
    pools = (port or {}).get("data") or (port or {}).get("pools") or []
    if isinstance(pools, dict):
        pools = pools.get("pools") or pools.get("data") or []
    for entry in pools:
        pa = entry.get("poolAddress")
        if not pa:
            continue
        name = f"{entry.get('tokenX','?')}/{entry.get('tokenY','?')}"
        try:
            pn = get(f"/positions/{pa}/pnl", {"user": wallet, "status": "open"})
        except Exception:
            continue
        items = (pn or {}).get("data") or (pn or {}).get("positions") or []
        if isinstance(items, dict):
            items = items.get("positions") or []
        for it in items:
            try:
                p_lo = float(it["minPrice"])
                p_hi = float(it["maxPrice"])
                p_now = float(it["poolActivePrice"])
                vx = float(dig(it, "unrealizedPnl", "balanceTokenX", "usd") or 0.0)
                vy = float(dig(it, "unrealizedPnl", "balanceTokenY", "usd") or 0.0)
            except Exception:
                continue
            if not (p_lo and p_hi and p_now) or (vx + vy) <= 0:
                continue
            a = math.log(max(p_now / p_lo, 1 + 1e-12))
            b = math.log(max(p_hi / p_now, 1 + 1e-12))
            pred = a / (a + 1 - math.exp(-b))  # predicted QUOTE (token Y) share of value
            obs = vy / (vx + vy)
            out["positions"].append({"pair": name, "p_lo": p_lo, "p_hi": p_hi,
                                     "p_now": p_now, "value": vx + vy})
            out["checks"].append({"pair": name, "a": a, "b": b, "value": vx + vy,
                                  "pred_quote_share": pred, "obs_quote_share": obs,
                                  "err": obs - pred})
    return out


def study_live(sol_usd: float) -> dict:
    print("\n" + "=" * 86)
    print("MODEL vs THE OPERATOR'S ACTUAL BOOK")
    print("=" * 86)
    live = fetch_live_positions(WALLET, sol_usd)
    if not live["checks"]:
        print("    no live positions read (offline, or the API shape moved). Skipping.")
        return live
    print(f"    {'position':16s} {'a':>7s} {'b':>7s} {'4/w_eff':>8s} {'value':>10s}"
          f" {'predicted quote share':>22s} {'observed':>10s} {'error':>9s}")
    for c in live["checks"]:
        w_eff = c["a"] + 1 - math.exp(-c["b"])
        print(f"    {c['pair']:16s} {c['a']:7.3f} {c['b']:7.3f} {4/w_eff:8.2f} ${c['value']:9,.2f}"
              f" {c['pred_quote_share']*100:21.2f}% {c['obs_quote_share']*100:9.2f}%"
              f" {c['err']*100:+8.2f}pp")
    print("""
    The predicted column uses ONLY the range and the active price -- no deposit
    information at all. Agreement to a percentage point is a real test of the Spot-shape
    assumption every formula in this file rests on.
""")
    return live


# --------------------------------------------------------------------------------------
# G. CLI
# --------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--width", action="store_true")
    ap.add_argument("--rebalance", action="store_true")
    ap.add_argument("--fee", action="store_true")
    ap.add_argument("--pairs", action="store_true")
    ap.add_argument("--eta", action="store_true")
    ap.add_argument("--hedge", action="store_true")
    ap.add_argument("--rail", action="store_true")
    ap.add_argument("--exit", dest="exit_", action="store_true")
    ap.add_argument("--crossover", action="store_true")
    ap.add_argument("--il", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--paths", type=int, default=400)
    ap.add_argument("--boot", type=int, default=400)
    ap.add_argument("--sol-usd", type=float, default=SOL_USD_DEFAULT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    picked = any([args.measure, args.selftest, args.width, args.rebalance, args.fee,
                  args.pairs, args.il, args.live, args.hedge, args.rail, args.exit_,
                  args.crossover, args.eta])
    run_all = not picked
    blob: dict = {}

    if run_all or args.selftest:
        blob["selftest"] = selftest(verbose=not args.json)
        if not blob["selftest"]:
            print("\n!! SELF-TEST FAILED -- every number below is suspect. Stopping.", file=sys.stderr)
            return 1
        print()

    measured: dict = {}
    if run_all or any([args.measure, args.width, args.rebalance, args.fee, args.pairs,
                       args.hedge, args.crossover, args.eta]):
        measured = study_measure(args.sol_usd, boot=args.boot)
        blob["measured"] = measured

    if run_all or args.eta:
        blob["eta"] = study_eta(measured, args.sol_usd)
    if run_all or args.pairs:
        blob["pairs"] = study_pairs(measured)
    if run_all or args.hedge:
        blob["hedge"] = study_hedge(measured, args.sol_usd)
    if run_all or args.width:
        blob["width"] = study_width(measured, args.sol_usd, n_paths=args.paths)
    if run_all or args.rebalance:
        blob["rebalance"] = study_rebalance(measured, args.sol_usd, n_paths=args.paths)
    if run_all or args.fee:
        blob["fee"] = study_fee(measured, args.sol_usd)
    if run_all or args.rail:
        blob["rail"] = study_rail(args.sol_usd)
    if run_all or args.exit_:
        blob["exit"] = study_exit(args.sol_usd)
    if run_all or args.crossover:
        blob["crossover"] = study_crossover(measured, args.sol_usd)
    live = None
    if args.live:
        live = study_live(args.sol_usd)
        blob["live"] = live
    if run_all or args.il:
        blob["il"] = study_il_accounting(args.sol_usd, live)

    if args.json:
        print(json.dumps(blob, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
