#!/usr/bin/env python3
"""exploration_map.py -- THE MAP: which stream carries how much information about
which future, at which horizon, and can any of it clear friction.

Every study in this repo so far has tested ONE hypothesis against ONE dataset, and
eight consecutive strategy studies came back null.  That is a bad way to learn where
strategies CAN exist.  This one builds the map instead: a pre-declared grid over
(stream-feature x target x horizon x cohort), every cell measured with the same
dependence machinery, every cell counted against the same FDR budget, and every
surviving cell translated into money net of measured friction.

A map that is ALL NULL is a result.  It says the observable streams carry no
exploitable structure at these horizons and the desk should be all-toll.  This module
is built so that outcome is REACHABLE -- nothing here can manufacture a winner from a
large search, because the search size is an input to the correction.

------------------------------------------------------------------------------------
THE FAILURE MODES THIS IS BUILT AGAINST (each one is a tombstone in studies/)
------------------------------------------------------------------------------------
1. `RESULT_copytrading.md`  -- an i.i.d. null manufactured a 73x effect that a
   rotation null killed.  So: NO i.i.d. null is ever decisive here.  It is computed
   and REPORTED as a diagnostic, precisely so the map can show how much it inflates.
2. `RESULT_bandit_search.md` -- a 1,458-cell search manufactured a +6% winner from
   noise, p=0.455 on permuted worlds.  So: the cell count is declared BEFORE the run,
   every cell enters the FDR budget, and the correction is Benjamini-Yekutieli
   (valid under arbitrary dependence), not Benjamini-Hochberg.
3. `RESULT_board_entry.md` -- returns conditioned on staying visible on a board are
   biased UP, because collapse is a reason to leave.  So: every forward return here
   is computed exit-filled (leaving the boards = exiting at the last observed price),
   the censoring rate is reported per cell, and board exit is itself a target with a
   competing-risks treatment.
4. `RESULT_llm_filter.md` -- dCor + permutation, validated on known-zero and
   known-effect worlds, beat Mantel/RSA on planted nonlinear effects.  So: dCor is
   the workhorse statistic here and the selftest suite is inherited and extended.

------------------------------------------------------------------------------------
THE PRICE BASIS -- a defect found and corrected here, read this before the numbers
------------------------------------------------------------------------------------
`usd_market_cap` in the boards feed embeds SOL/USD, which moved 1.41% across the main
window.  A forward return in USD therefore contains a market-wide factor identical
across every coin, and a naive null reads that common factor as predictability.

For coins still on the bonding curve (`complete=false`) the snapshot's virtual
reserves give an EXACT SOL-denominated price:

    mcap_sol = (virtual_sol_reserves / 1e9) / (virtual_token_reserves / 1e6) * 1e9

and this reproduces `usd_market_cap` to within a tight band -- the implied SOL/USD
across 145,833 such rows has p10 74.85 / p50 75.14 / p90 75.56.  For GRADUATED coins
(`complete=true`) the same field is stale garbage: implied SOL/USD runs from 6 to
1.1e6.  So:

  - bonding-curve coins  -> price from reserves, exactly SOL-denominated;
  - graduated coins      -> `usd_market_cap` deflated by the SOL/USD series estimated
                            per snapshot as the cross-sectional MEDIAN implied rate
                            over the bonding-curve cohort at that instant.

Everything downstream is SOL-denominated.  The SOL/USD factor is additionally carried
as a PLACEBO feature (`plc_market`) whose only job is to be significant under the
naive null and dead under the real ones -- calibration on the actual data rather than
only on synthetic worlds.

------------------------------------------------------------------------------------
NULLS
------------------------------------------------------------------------------------
`iid`   shuffle the target across all rows.  DIAGNOSTIC ONLY, never decisive.
`xsec`  shuffle the target among the coins observed at the SAME instant.  Preserves
        the market factor exactly; answers the trading question -- does this feature
        pick the right coin right now, versus a coin already in view.
`rot`   circularly rotate the target panel in time by a single global tau.  Preserves
        every coin's own autocorrelation exactly; kills the temporal alignment.
`mint`  reassign each coin's ENTIRE target series to another coin, time-aligned.
        Preserves autocorrelation AND the market factor.  Strongest null; only valid
        where the coins' observation windows overlap enough to land (>=50% of rows).

The decision p-value for a cell is  max(p_xsec, p_rot, p_mint-if-valid).  A cell must
beat every null that applies to it, not the friendliest one.

------------------------------------------------------------------------------------
Usage
------------------------------------------------------------------------------------
    uv run --group research python studies/exploration_map.py selftest
    uv run --group research python studies/exploration_map.py ingest
    uv run --group research python studies/exploration_map.py map [--jobs N]
    uv run --group research python studies/exploration_map.py survival
    uv run --group research python studies/exploration_map.py economics
    uv run --group research python studies/exploration_map.py report
    uv run --group research python studies/exploration_map.py all

Read-only over `state/`.  Signs nothing, sends nothing, spends nothing (see
`RESULT_exploration_map.md` for why no BigQuery spend was made).  Writes only
`studies/data/exploration_map/`.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data" / "exploration_map"

# ---------------------------------------------------------------------------
# Declared constants.  Every one of these is a measurement made elsewhere in the
# repo, cited, not a knob tuned here.
# ---------------------------------------------------------------------------

GRID_S = 30                      # boards poll cadence, `shitcoims_scalper.boards --poll-seconds 30`
FRICTION_ROUND_TRIP = 0.0226     # RESULT_bandit_search.md section 5, at B* sizing, MEASURED
PUMP_TOTAL_SUPPLY = 1e9          # pump.fun fixed supply
CURVE_START_VSOL = 30.0          # virtual SOL at launch
CURVE_GRAD_VSOL = 115.0          # virtual SOL at graduation (85 real)

# The grid, declared up front.  Changing any of these changes the multiplicity
# correction, which is the point.
HORIZON_STEPS = {"5m": 10, "30m": 60, "2h": 240, "8h": 960}
RETURN_HORIZONS = ["5m", "30m", "2h", "8h"]
EXIT_HORIZONS = ["30m", "2h"]
DEAD_HORIZONS = ["30m"]

EXEC_LAG_STEPS = 1               # see below: one grid step between seeing and trading
MIN_OBS = 8                      # a coin needs >= 4 minutes of life to have dynamics
N_SUB = 800                      # rows per dCor evaluation (O(n^2) memory and time)
STAGE_PERMS = [199, 4999, 99999]  # sequential permutation refinement
# Advance a cell only when more draws could still change its verdict.  After 4,999 draws
# a cell at p ~ 0.005 has ~25 exceedances and its p is already resolved; only cells at the
# PERMUTATION FLOOR (a handful of exceedances) can move, and only the top of the table
# needs 1e-5 resolution -- BY at rank k demands k*q/(m*c(m)), which is 2.7e-5 at rank 1
# but 1.1e-3 by rank 40.  Spending 99,999 draws on rank 40 buys nothing.
STAGE_GATES = [0.05, 0.0015]
MAX_STAGE3 = 24                  # hard cap, by p-rank, on the most expensive stage
MI_NULLS = 60                    # draws for the k-NN MI bias correction
FDR_Q = 0.10


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ===========================================================================
# 1. STATISTICS
# ===========================================================================


def rankdata(a: np.ndarray) -> np.ndarray:
    """Average-tie ranks.  scipy has this; reimplemented so the statistic core has
    no dependency that could silently change under us."""
    a = np.asarray(a, dtype=np.float64)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    sa = a[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sa[j + 1] == sa[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 3:
        return float("nan")
    rx, ry = rankdata(x), rankdata(y)
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    den = math.sqrt(float(rx @ rx) * float(ry @ ry))
    return float(rx @ ry) / den if den > 0 else 0.0


def _double_centre(d: np.ndarray) -> np.ndarray:
    r = d.mean(axis=1, keepdims=True)
    c = d.mean(axis=0, keepdims=True)
    g = float(d.mean())
    return d - r - c + g


def _dist_abs(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return np.abs(v[:, None] - v[None, :])


class DcorX:
    """The feature side of dCor, precomputed once so nulls only pay for the target.

    dCor(X,Y) = sqrt( dCov2 / sqrt(dVarX * dVarY) ), with everything a mean over the
    doubly-centred distance matrices.  Zero IFF independent -- not merely uncorrelated,
    which is the whole reason this and not Pearson.
    """

    __slots__ = ("A", "dvarx", "n")

    def __init__(self, x: np.ndarray) -> None:
        # A is promoted to float64 ONCE. The obvious `self.A.astype(np.float64)` inside
        # `stat` re-converts and re-allocates a 5 MB matrix on every permutation draw,
        # and `stat` is called millions of times per grid.
        self.A = _double_centre(_dist_abs(x)).astype(np.float64)
        self.dvarx = float(np.einsum("ij,ij->", self.A, self.A) / self.A.size)
        self.n = x.size

    def stat(self, y: np.ndarray) -> float:
        B = _double_centre(_dist_abs(y)).astype(np.float64)
        n2 = B.size
        dcov2 = float(np.einsum("ij,ij->", self.A, B)) / n2
        dvary = float(np.einsum("ij,ij->", B, B)) / n2
        den = math.sqrt(self.dvarx * dvary)
        if den <= 0 or dcov2 <= 0:
            return 0.0
        return math.sqrt(dcov2 / den)


def distance_correlation(x: np.ndarray, y: np.ndarray) -> float:
    return DcorX(x).stat(np.asarray(y, dtype=np.float32))


def ksg_mi_bits(x: np.ndarray, y: np.ndarray, *, discrete_y: bool, seed: int = 0) -> float:
    """k-NN mutual information in BITS (Kraskov et al. 2004 / Ross 2014 for mixed).

    sklearn's estimator, converted from nats.  It is biased upward at finite n, which
    is why the caller subtracts the mean over null draws rather than quoting it raw.
    """
    from sklearn.feature_selection import mutual_info_classif, mutual_info_regression

    X = np.asarray(x, dtype=np.float64).reshape(-1, 1)
    if discrete_y:
        yy = np.asarray(y).astype(int)
        if np.unique(yy).size < 2:
            return 0.0
        v = mutual_info_classif(X, yy, n_neighbors=5, random_state=seed)
    else:
        yy = np.asarray(y, dtype=np.float64)
        v = mutual_info_regression(X, yy, n_neighbors=5, random_state=seed)
    return float(v[0]) / math.log(2.0)


def benjamini_yekutieli(pvals: Sequence[float], q: float = FDR_Q) -> tuple[np.ndarray, np.ndarray, float]:
    """BY step-up.  Valid under ARBITRARY dependence, which is what a grid of
    overlapping features over the same panel has.  Returns (qvalues, rejected, c_m)."""
    p = np.asarray(pvals, dtype=np.float64)
    m = p.size
    c_m = float(np.sum(1.0 / np.arange(1, m + 1)))
    order = np.argsort(p, kind="mergesort")
    ps = p[order]
    raw = ps * m * c_m / np.arange(1, m + 1)
    qs = np.minimum.accumulate(raw[::-1])[::-1]
    qs = np.clip(qs, 0.0, 1.0)
    qv = np.empty(m, dtype=np.float64)
    qv[order] = qs
    return qv, qv <= q, c_m


# ===========================================================================
# 2. NULLS -- panel transforms, not vector shuffles
# ===========================================================================


@dataclass
class Panel:
    """A (mints x times) rectangle with an aliveness mask.  Everything -- features,
    targets, nulls -- lives on this shape so a null is a panel transform and cannot
    accidentally become an i.i.d. shuffle."""

    name: str
    mints: list[str]
    times: np.ndarray                 # (T,) unix seconds on the 30s grid
    alive: np.ndarray                 # (M,T) bool -- inside [t_first, t_last]
    feats: dict[str, np.ndarray] = field(default_factory=dict)   # (M,T) float32, nan outside
    targets: dict[str, np.ndarray] = field(default_factory=dict)  # (M,T) float32, nan where undefined
    target_kind: dict[str, str] = field(default_factory=dict)     # 'cont' | 'binary'
    censor: dict[str, float] = field(default_factory=dict)        # per-target censoring rate
    # `alive` is [first sighting, last sighting] and BRIDGES gaps: a coin flickering on
    # and off a board is treated as continuously held, with its price forward-filled at
    # the last print, because that is a holder's actual situation.  `obs` is where it
    # was really on a board, and the ratio of the two is the duty cycle reported in the
    # survival table -- without it "162 minutes in view" reads as continuous presence.
    obs: np.ndarray | None = None

    @property
    def M(self) -> int:
        return len(self.mints)

    @property
    def T(self) -> int:
        return int(self.times.size)


def overlap_groups(alive: np.ndarray, block: int = 24) -> list[np.ndarray]:
    """Coins bucketed by when they were in view, so a mint-block swap actually LANDS.

    A global mint permutation is the strongest null available (it preserves each coin's
    own autocorrelation AND the market factor), but on a staggered cohort -- coins that
    live for eleven minutes each, arriving all day -- a random donor is almost never
    alive at the same instants, so the null evaporates to a handful of usable rows and
    silently stops being a test.  Bucketing donors by entry time keeps the swap
    time-aligned while leaving it a genuine reassignment of identity.
    """
    M, T = alive.shape
    first = np.argmax(alive, axis=1)
    last = T - 1 - np.argmax(alive[:, ::-1], axis=1)
    order = np.lexsort((last, first))
    n_blocks = max(1, int(np.ceil(M / max(block, 2))))
    return [g for g in np.array_split(order, n_blocks) if g.size >= 2]


def null_panel(Y: np.ndarray, kind: str, rng: np.random.Generator,
               groups: list[np.ndarray] | None = None) -> np.ndarray:
    """Return a null version of the target panel.  NaN carries 'undefined' through."""
    M, T = Y.shape
    if kind == "mint":
        perm = np.arange(M)
        if groups:
            for g in groups:
                p = rng.permutation(g.size)
                while g.size > 1 and np.all(p == np.arange(g.size)):
                    p = rng.permutation(g.size)
                perm[g] = g[p]
        else:
            perm = rng.permutation(M)
            while M > 1 and np.all(perm == np.arange(M)):
                perm = rng.permutation(M)
        return Y[perm]
    if kind == "rot":
        lo, hi = max(1, T // 10), max(2, T - T // 10)
        tau = int(rng.integers(lo, hi))
        return np.roll(Y, tau, axis=1)
    if kind == "xsec":
        # Vectorised within-column permutation.  The obvious Python loop over T=1200
        # columns, 199 times per null, per cell, held the GIL hard enough that ten
        # threads ran SLOWER than one.  Sorting random keys with the non-finite entries
        # pushed to +inf gives, per column, a random ordering of exactly the finite
        # rows; a stable argsort of the finite mask gives their canonical destinations.
        finite = np.isfinite(Y)
        keys = rng.random(Y.shape)
        keys[~finite] = np.inf
        src = np.argsort(keys, axis=0)
        dst = np.argsort(~finite, axis=0, kind="stable")
        out = np.full_like(Y, np.nan)
        np.put_along_axis(out, dst, np.take_along_axis(Y, src, axis=0), axis=0)
        return out
    if kind == "iid":
        out = np.full_like(Y, np.nan)
        idx = np.flatnonzero(np.isfinite(Y))
        out.flat[idx] = Y.flat[rng.permutation(idx)]
        return out
    raise ValueError(kind)


# ===========================================================================
# 3. SELFTEST -- calibrate the machinery before pointing it at money
# ===========================================================================


def _unit(a: np.ndarray) -> np.ndarray:
    s = float(np.std(a))
    return a / s if s > 0 else a


def _synth_panel(M: int, T: int, rng: np.random.Generator, *, effect: float,
                 market: float, ar: float) -> tuple[np.ndarray, np.ndarray]:
    """A panel with a market factor, per-coin autocorrelation, and a controllable
    nonlinear feature->future link.  This is the world in which a naive null lies.

    Components are standardised so `market` and `effect` are interpretable LOADINGS
    against unit-variance idiosyncratic noise -- otherwise the AR(0.98) market factor
    has a standard deviation of ~5 and silently drowns any planted effect, which is
    a way to write a test that can only pass by accident.
    """
    mk = np.zeros(T)
    for t in range(1, T):
        mk[t] = 0.98 * mk[t - 1] + rng.normal(0, 1)
    mk = _unit(mk)
    X = np.zeros((M, T))
    for m in range(M):
        e = rng.normal(0, 1, T)
        for t in range(1, T):
            X[m, t] = ar * X[m, t - 1] + e[t]
    X = _unit(X)
    Y = market * mk[None, :] + rng.normal(0, 1, (M, T))
    if effect:
        Y += effect * _unit(np.sin(X * 4.0))   # nonlinear: Spearman near-blind, dCor sees it
    return X.astype(np.float32), Y.astype(np.float32)


def _quick_p(X: np.ndarray, Y: np.ndarray, kind: str, iters: int, rng: np.random.Generator,
             n_sub: int = 400) -> tuple[float, float]:
    rows = np.array([(m, t) for m in range(X.shape[0]) for t in range(X.shape[1])
                     if np.isfinite(X[m, t]) and np.isfinite(Y[m, t])])
    if rows.shape[0] > n_sub:
        rows = rows[rng.choice(rows.shape[0], n_sub, replace=False)]
    mi, ti = rows[:, 0], rows[:, 1]
    dx = DcorX(X[mi, ti])
    obs = dx.stat(Y[mi, ti])
    hits = 0
    for _ in range(iters):
        Yn = null_panel(Y, kind, rng)
        v = Yn[mi, ti]
        ok = np.isfinite(v)
        if ok.sum() < 0.6 * v.size:
            continue
        d2 = DcorX(X[mi, ti][ok])
        if d2.stat(v[ok]) >= obs - 1e-12:
            hits += 1
    return obs, (hits + 1) / (iters + 1)


def selftest() -> int:
    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))
        if not cond:
            fails.append(name)

    print("\n-- statistic identities --")
    rng = np.random.default_rng(11)
    x = rng.normal(size=300)
    check("dCor(x,x) == 1", abs(distance_correlation(x, x) - 1.0) < 1e-5,
          f"{distance_correlation(x, x):.6f}")
    y = rng.normal(size=300)
    check("dCor(x, independent y) is small", distance_correlation(x, y) < 0.20,
          f"{distance_correlation(x, y):.3f}")
    check("dCor is symmetric",
          abs(distance_correlation(x, y) - distance_correlation(y, x)) < 1e-5)
    check("dCor is scale/shift invariant",
          abs(distance_correlation(x, y) - distance_correlation(3 * x + 7, -2 * y + 1)) < 1e-5)

    print("\n-- dCor sees what Spearman cannot --")
    xs = rng.uniform(-3, 3, 600)
    ys = np.sin(xs * 1.5) + rng.normal(0, 0.25, 600)
    sp, dc = abs(spearman(xs, ys)), distance_correlation(xs, ys)
    check("planted nonlinear effect: dCor >> |Spearman|", dc > 3 * sp and dc > 0.3,
          f"dCor={dc:.3f} |rho|={sp:.3f}")

    print("\n-- BY multiplicity correction --")
    pn = np.random.default_rng(3).uniform(size=500)
    qv, rej, cm = benjamini_yekutieli(pn)
    check("BY rejects ~nothing on 500 uniform p-values", rej.sum() <= 1, f"{int(rej.sum())} rejected")
    check("BY constant c(m) is the harmonic sum", abs(cm - float(np.sum(1 / np.arange(1, 501)))) < 1e-9,
          f"c(500)={cm:.3f}")
    pm = np.concatenate([np.full(5, 1e-9), np.random.default_rng(4).uniform(size=495)])
    _, rej2, _ = benjamini_yekutieli(pm)
    check("BY still finds 5 planted needles in 500", rej2.sum() >= 5, f"{int(rej2.sum())} rejected")
    check("BY is stricter than uncorrected", rej2.sum() < 500)

    print("\n-- nulls on a KNOWN-ZERO panel (autocorrelated, market factor, no link) --")
    rng = np.random.default_rng(21)
    X0, Y0 = _synth_panel(40, 200, rng, effect=0.0, market=1.5, ar=0.95)
    for kind in ("xsec", "rot", "mint"):
        _, p = _quick_p(X0, Y0, kind, 199, rng)
        check(f"known-zero: {kind} null does not reject", p > 0.05, f"p={p:.3f}")

    print("\n-- nulls on a KNOWN-EFFECT panel (same world + nonlinear link) --")
    rng = np.random.default_rng(22)
    X1, Y1 = _synth_panel(40, 200, rng, effect=1.2, market=1.0, ar=0.95)
    sp1 = abs(spearman(X1.ravel(), Y1.ravel()))
    for kind in ("xsec", "rot", "mint"):
        _, p = _quick_p(X1, Y1, kind, 199, rng)
        check(f"known-effect: {kind} null rejects", p < 0.02, f"p={p:.4f}")
    check("known-effect is invisible to Spearman (so dCor is earning its keep)",
          sp1 < 0.06, f"|rho|={sp1:.4f}")

    print("\n-- THE TOMBSTONE TEST: a pure market factor must fool only the naive null --")
    # Feature is IDENTICAL across coins (a market-wide series); target loads on the same
    # factor.  There is NO coin-specific information -- a desk cannot trade this.  An
    # i.i.d. null calls it real; xsec must not.
    rng = np.random.default_rng(23)
    T, M = 200, 40
    f = np.zeros(T)
    for t in range(1, T):
        f[t] = 0.97 * f[t - 1] + rng.normal(0, 1)
    Xm = np.repeat(f[None, :], M, axis=0).astype(np.float32)
    Ym = (1.4 * f[None, :] + rng.normal(0, 1, (M, T))).astype(np.float32)
    _, p_iid = _quick_p(Xm, Ym, "iid", 199, rng)
    _, p_xsec = _quick_p(Xm, Ym, "xsec", 199, rng)
    check("market-factor placebo: the i.i.d. null IS fooled", p_iid < 0.01, f"p_iid={p_iid:.4f}")
    check("market-factor placebo: the xsec null is NOT fooled", p_xsec > 0.05, f"p_xsec={p_xsec:.3f}")

    print("\n-- THE OTHER TOMBSTONE: spurious regression, few coins, near-unit-root --")
    # A handful of coins, each a long random walk in BOTH x and y, independent by
    # construction.  This is Granger & Newbold's spurious regression: the pair will
    # look strongly dependent in-sample.  An i.i.d. null destroys the autocorrelation
    # and therefore understates the null spread; the honest nulls must not reject.
    # Averaged over 12 independent worlds, because a single draw of a spurious
    # regression is itself a coin flip and a test that rests on one is theatre.
    ps: dict[str, list[float]] = {"iid": [], "xsec": [], "rot": [], "mint": []}
    for w in range(12):
        rng = np.random.default_rng(2400 + w)
        Ma, Ta = 4, 700
        Xa = np.cumsum(rng.normal(0, 1, (Ma, Ta)), axis=1).astype(np.float32)
        Ya = np.cumsum(rng.normal(0, 1, (Ma, Ta)), axis=1).astype(np.float32)
        for k in ps:
            ps[k].append(_quick_p(Xa, Ya, k, 99, rng, n_sub=300)[1])
    fpr = {k: float(np.mean([p < 0.05 for p in v])) for k, v in ps.items()}
    dec = [max(ps["xsec"][i], ps["rot"][i], ps["mint"][i]) for i in range(12)]
    f_dec = float(np.mean([p < 0.05 for p in dec]))
    for k in ("iid", "xsec", "rot", "mint"):
        print(f"       false-positive rate, {k:5s} null: {100*fpr[k]:3.0f}% of 12 null worlds")
    check("spurious world: the i.i.d. null has a catastrophic false-positive rate",
          fpr["iid"] > 0.5, f"{100*fpr['iid']:.0f}%")
    # MEASURED, and it is why the decision rule is a max and not a vote: a circular
    # shift is only a valid null under (approximate) stationarity, and a random walk
    # is not stationary, so `rot` is ANTICONSERVATIVE on level-like targets.  Recorded
    # rather than hidden -- the module never lets `rot` alone decide anything.
    check("spurious world: the rot null is anticonservative on a non-stationary target "
          "(measured, and the reason the decision rule is a max)",
          fpr["rot"] > 0.25, f"{100*fpr['rot']:.0f}%")
    check("spurious world: the mint null is near nominal", fpr["mint"] <= 0.25,
          f"{100*fpr['mint']:.0f}%")
    check("spurious world: THE DECISION RULE max(xsec,rot,mint) is near nominal",
          f_dec <= 0.10, f"{100*f_dec:.0f}%")
    check("spurious world: the decision rule beats every single null it contains",
          f_dec <= min(fpr["xsec"], fpr["rot"], fpr["mint"]) + 1e-9,
          f"decision {100*f_dec:.0f}% vs best single {100*min(fpr['xsec'], fpr['rot'], fpr['mint']):.0f}%")

    print("\n-- and the decision rule must still have POWER on the known-effect world --")
    rng = np.random.default_rng(27)
    X2, Y2 = _synth_panel(40, 200, rng, effect=1.2, market=1.0, ar=0.95)
    pd_ = max(_quick_p(X2, Y2, k, 199, rng)[1] for k in ("xsec", "rot", "mint"))
    check("decision rule rejects on the planted nonlinear effect", pd_ < 0.05, f"p={pd_:.4f}")

    print("\n-- the fast NullDraw must agree with the reference panel transforms --")
    # The O(n) draws replaced O(M*T) panel transforms for speed.  Speed is never worth a
    # silently different null, so the two are compared on their DISTRIBUTIONS here.
    rng = np.random.default_rng(31)
    Mv, Tv = 60, 150
    Xv = rng.normal(size=(Mv, Tv)).astype(np.float32)
    Yv = rng.normal(size=(Mv, Tv)).astype(np.float32)
    drop = rng.random((Mv, Tv)) < 0.25
    Xv[drop] = np.nan
    Yv[rng.random((Mv, Tv)) < 0.25] = np.nan
    fin = np.isfinite(Xv) & np.isfinite(Yv)
    fm, ft = np.nonzero(fin)
    pick = rng.choice(fm.size, 300, replace=False)
    mi_, ti_ = fm[pick], ft[pick]
    grp = overlap_groups(np.isfinite(Xv))
    nd = NullDraw(Xv, Yv, mi_, ti_, grp)
    dxv = DcorX(Xv[mi_, ti_])
    for kind in ("iid", "xsec", "rot", "mint"):
        fast, ref = [], []
        r1 = np.random.default_rng(5)
        r2 = np.random.default_rng(5)
        for _ in range(120):
            g = nd.draw(kind, r1)
            if g is not None:
                fast.append(DcorX(g[0]).stat(g[1]))
            Yn = null_panel(Yv, kind, r2, grp)
            v = Yn[mi_, ti_]
            ok2 = np.isfinite(v)
            if ok2.sum() > 50:
                ref.append(DcorX(Xv[mi_, ti_][ok2]).stat(v[ok2]))
        if not fast or not ref:
            check(f"NullDraw[{kind}] produced draws", False)
            continue
        mf, mr = float(np.mean(fast)), float(np.mean(ref))
        sf, sr = float(np.std(fast)), float(np.std(ref))
        check(f"NullDraw[{kind}] matches the reference null distribution",
              abs(mf - mr) < 3 * (sf + sr) / 2 + 0.02 and abs(sf - sr) < 0.05,
              f"mean {mf:.4f} vs {mr:.4f}, sd {sf:.4f} vs {sr:.4f}")
    # and the draws must always return exactly n rows
    for kind in ("iid", "xsec", "rot", "mint"):
        g = nd.draw(kind, np.random.default_rng(9))
        check(f"NullDraw[{kind}] returns exactly n rows and no NaN",
              g is not None and g[0].size == 300 and g[1].size == 300
              and np.isfinite(g[1]).all() and np.isfinite(g[0]).all())

    print("\n-- k-NN mutual information in bits --")
    rng = np.random.default_rng(25)
    n = 3000
    a = rng.normal(size=n)
    check("MI(x, independent y) ~ 0 bits", abs(ksg_mi_bits(a, rng.normal(size=n), discrete_y=False)) < 0.05,
          f"{ksg_mi_bits(a, rng.normal(size=n), discrete_y=False):.4f}")
    # Gaussian pair with correlation r has I = -0.5*log2(1-r^2) bits, exactly.
    r = 0.8
    b = r * a + math.sqrt(1 - r * r) * rng.normal(size=n)
    want = -0.5 * math.log2(1 - r * r)
    got = ksg_mi_bits(a, b, discrete_y=False)
    check(f"MI recovers the Gaussian truth {want:.3f} bits", abs(got - want) < 0.15, f"got {got:.3f}")
    lab = (a > 0).astype(int)
    got_d = ksg_mi_bits(a, lab, discrete_y=True)
    check("MI(x, sign(x)) ~ 1 bit", abs(got_d - 1.0) < 0.15, f"got {got_d:.3f}")

    print("\n-- THE THIRD TOMBSTONE: microstructure bounce must not read as momentum --")
    # A pure random walk observed with bid/ask bounce.  There is NO predictability.  But
    # a trailing return ending at t and a forward return starting at t share lp[t] with
    # opposite signs, so the bounce alone makes them dependent -- and no permutation null
    # in this module can see it, because they all break the coin's own pairing.  The only
    # defence is not to price the entry at the instant the feature is read.
    rng = np.random.default_rng(41)
    Mw, Tw = 40, 400
    true_lp = np.cumsum(rng.normal(0, 0.01, (Mw, Tw)), axis=1)
    obs_lp = true_lp + rng.choice([-1.0, 1.0], (Mw, Tw)) * 0.02      # bounce
    h = 10
    trail = np.full((Mw, Tw), np.nan); trail[:, h:] = obs_lp[:, h:] - obs_lp[:, :-h]
    fwd0 = np.full((Mw, Tw), np.nan); fwd0[:, :-h] = obs_lp[:, h:] - obs_lp[:, :-h]
    fwd1 = np.full((Mw, Tw), np.nan)                                  # one-step lag
    fwd1[:, :-h - 1] = obs_lp[:, h + 1:] - obs_lp[:, 1:-h]
    m0 = np.isfinite(trail) & np.isfinite(fwd0)
    m1 = np.isfinite(trail) & np.isfinite(fwd1)
    r0 = spearman(trail[m0], fwd0[m0])
    r1 = spearman(trail[m1], fwd1[m1])
    check("no-lag entry manufactures strong spurious reversion from bounce alone",
          r0 < -0.15, f"rho={r0:.3f}")
    check("one-step execution lag removes it", abs(r1) < 0.06, f"rho={r1:.3f}")
    check("the lag shrinks the artefact by at least 3x", abs(r0) > 3 * abs(r1),
          f"|{r0:.3f}| vs |{r1:.3f}|")

    print("\n-- exit-fill returns must be biased DOWN relative to survivors-only --")
    # A world where dying coins fall: the survivor-only mean must exceed the filled mean.
    rng = np.random.default_rng(26)
    rets = rng.normal(0.0, 0.1, 4000)
    dies = rets < np.quantile(rets, 0.3)
    surv_mean = float(rets[~dies].mean())
    fill_mean = float(rets.mean())
    check("survivors-only mean > exit-filled mean", surv_mean > fill_mean,
          f"{surv_mean:.4f} vs {fill_mean:.4f}")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILURES: ' + ', '.join(fails)}\n")
    return 0 if not fails else 1


# ===========================================================================
# 4. INGEST -- the boards panel, SOL-denominated
# ===========================================================================

BOARD_COHORTS = {
    "hot": ["last_trade_timestamp"],
    "mcap": ["market_cap"],
    "live": ["currently-live"],
    "frozen": ["last_reply", "reply_count"],   # negative control: near-dead all-time boards
}


def _boards_files() -> list[Path]:
    d = ROOT / "state" / "boards"
    return sorted(d.glob("boards-*.jsonl"))


def read_boards() -> dict[str, Any]:
    """One pass over the boards tape.  Returns snapshots on a 30s grid plus the
    entry-event stream (used for market-wide churn and for board tenure)."""
    snaps: dict[int, dict[str, dict]] = collections.defaultdict(dict)
    boards_at: dict[int, dict[str, set]] = collections.defaultdict(lambda: collections.defaultdict(set))
    ranks_at: dict[int, dict[str, dict]] = collections.defaultdict(lambda: collections.defaultdict(dict))
    entries: list[float] = []
    board_of_mint: dict[str, set[str]] = collections.defaultdict(set)
    for fp in _boards_files():
        with fp.open() as fh:
            for line in fh:
                if '"board_entry"' in line:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if r.get("kind") == "board_entry":
                        entries.append(r["t_ingest"])
                    continue
                if '"board_snapshot"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("kind") != "board_snapshot":
                    continue
                b = r["board"]
                t = int(round(r["t_ingest"] / GRID_S) * GRID_S)
                for m in r["members"]:
                    mint = m["mint"]
                    snaps[t][mint] = m
                    boards_at[t][mint].add(b)
                    ranks_at[t][mint][b] = m["rank"]
                    board_of_mint[mint].add(b)
    return {"snaps": snaps, "boards_at": boards_at, "ranks_at": ranks_at,
            "entries": sorted(entries), "board_of_mint": board_of_mint}


SESSION_BREAK_S = 300      # 10 consecutive missed polls ends a session


def sessions(observed: list[int]) -> list[list[int]]:
    """Split the observed instants into contiguous collection SESSIONS, and return a
    UNIFORM 30s grid inside each.

    This is not cosmetic.  The collector stopped for 3.3 h between the two tape files.
    If the time axis is just `sorted(observed)`, then "index + 10" means five minutes
    inside a session and three hours across the gap -- every forward return spanning
    the break would be silently mislabelled, and the circular-rotation null would
    rotate across a discontinuity that is an artefact of the collector rather than of
    the market.  Sessions make the index arithmetic true by construction, and hand us
    a held-out window for free.
    """
    if not observed:
        return []
    out: list[list[int]] = []
    start = prev = observed[0]
    for t in observed[1:]:
        if t - prev > SESSION_BREAK_S:
            out.append(list(range(start, prev + GRID_S, GRID_S)))
            start = t
        prev = t
    out.append(list(range(start, prev + GRID_S, GRID_S)))
    return [s for s in out if len(s) >= 2 * HORIZON_STEPS["30m"]]


def sol_usd_series(snaps: dict[int, dict[str, dict]], times: list[int]) -> dict[int, float]:
    """SOL/USD per snapshot, from the bonding-curve cohort's own arithmetic.

    For an incomplete coin, mcap_usd / mcap_sol IS the SOL price.  The cross-sectional
    median over hundreds of such coins is a robust per-instant estimate that needs no
    external feed and cannot go stale.
    """
    out: dict[int, float] = {}
    last = None
    n_rejected = 0
    for t in times:
        vals = []
        for m in snaps.get(t, {}).values():
            if m.get("complete") or not m.get("virtual_token_reserves"):
                continue
            vt = m["virtual_token_reserves"]
            if vt <= 0:
                continue
            mc_sol = (m["virtual_sol_reserves"] / 1e9) / (vt / 1e6) * PUMP_TOTAL_SUPPLY
            if mc_sol > 0 and m["usd_market_cap"] > 0:
                vals.append(m["usd_market_cap"] / mc_sol)
        # A median is only robust when there is something to take a median OF.  One
        # instant in the tape had exactly ONE bonding-curve member, with broken
        # reserves, and the "median" was that single coin -- an implied SOL price of
        # $500,187 that would have rescaled every graduated coin's price at that
        # instant.  Require a quorum and a sanity band, else carry the last good rate.
        if len(vals) >= 5:
            med = float(np.median(vals))
            if 10.0 < med < 1000.0:
                last = med
            else:
                n_rejected += 1
        elif vals:
            n_rejected += 1
        if last is not None:
            out[t] = last
    if n_rejected:
        _log(f"  SOL/USD: {n_rejected} instant(s) rejected (no quorum or out of band), "
             f"last good rate carried forward")
    return out


def mcap_sol(m: dict, sol: float | None) -> float:
    """SOL-denominated market cap.  Reserves for bonding-curve coins (exact), deflated
    USD for graduated ones (their reserve fields are stale -- see the module docstring)."""
    if not m.get("complete"):
        vt = m.get("virtual_token_reserves") or 0
        if vt > 0:
            return (m["virtual_sol_reserves"] / 1e9) / (vt / 1e6) * PUMP_TOTAL_SUPPLY
    if sol and m.get("usd_market_cap"):
        return float(m["usd_market_cap"]) / sol
    return float("nan")


def _ffill_rows(A: np.ndarray) -> np.ndarray:
    """Forward-fill NaNs along axis 1.  A live desk holds the last snapshot it saw;
    modelling on the forward-filled state is what it can actually condition on."""
    out = A.copy()
    M, T = out.shape
    idx = np.where(np.isfinite(out), np.arange(T)[None, :], -1)
    np.maximum.accumulate(idx, axis=1, out=idx)
    rows = np.arange(M)[:, None]
    take = np.where(idx >= 0, idx, 0)
    filled = out[rows, take]
    return np.where(idx >= 0, filled, np.nan)


def build_cohort(raw: dict[str, Any], cohort: str, times: list[int],
                 sol: dict[int, float]) -> Panel | None:
    boards = BOARD_COHORTS[cohort]
    snaps, boards_at, ranks_at = raw["snaps"], raw["boards_at"], raw["ranks_at"]
    tindex = {t: i for i, t in enumerate(times)}
    T = len(times)
    bset = set(boards)

    # Cohort membership is decided by the boards a coin was on DURING THIS SESSION.
    # Using a tape-wide map instead leaks membership backwards in time: a coin that
    # first reached the market-cap board on day two would retroactively join the
    # `mcap` cohort on day one, which both changes the panel under a finished run and
    # is a look-ahead in its own right.
    seen: dict[str, list[int]] = collections.defaultdict(list)
    for t in times:
        for mt in snaps.get(t, {}):
            if boards_at[t].get(mt, set()) & bset:
                seen[mt].append(tindex[t])
    members = [mt for mt in seen if len(seen[mt]) >= MIN_OBS]
    if len(members) < 12:
        return None
    members.sort()
    midx = {mt: i for i, mt in enumerate(members)}
    M = len(members)

    nan = lambda: np.full((M, T), np.nan, dtype=np.float32)   # noqa: E731
    raw_mcap, raw_dd, raw_rep, raw_rank, raw_nb = nan(), nan(), nan(), nan(), nan()
    raw_live, raw_curve, raw_created, raw_lasttrade, raw_complete = nan(), nan(), nan(), nan(), nan()

    for t in times:
        ti = tindex[t]
        s = sol.get(t)
        for mt, m in snaps.get(t, {}).items():
            i = midx.get(mt)
            if i is None:
                continue
            raw_mcap[i, ti] = mcap_sol(m, s)
            raw_dd[i, ti] = m.get("drawdown_from_ath") if m.get("drawdown_from_ath") is not None else np.nan
            raw_rep[i, ti] = m.get("reply_count") or 0
            rk = ranks_at[t].get(mt) or {}
            raw_rank[i, ti] = min(rk.values()) if rk else np.nan
            raw_nb[i, ti] = len(boards_at[t].get(mt, ()))
            raw_live[i, ti] = 1.0 if m.get("is_currently_live") else 0.0
            raw_complete[i, ti] = 1.0 if m.get("complete") else 0.0
            if not m.get("complete"):
                raw_curve[i, ti] = (m["virtual_sol_reserves"] / 1e9 - CURVE_START_VSOL) / (
                    CURVE_GRAD_VSOL - CURVE_START_VSOL)
            raw_created[i, ti] = m.get("created_unix") or np.nan
            raw_lasttrade[i, ti] = m.get("last_trade_unix") or np.nan

    obs = np.isfinite(raw_mcap)
    first = np.argmax(obs, axis=1)
    last = T - 1 - np.argmax(obs[:, ::-1], axis=1)
    cols = np.arange(T)[None, :]
    alive = (cols >= first[:, None]) & (cols <= last[:, None])

    P = _ffill_rows(np.where(alive, raw_mcap, np.nan))
    P = np.where(alive & (P > 0), P, np.nan)
    lp = np.log(P, out=np.full_like(P, np.nan), where=np.isfinite(P) & (P > 0))

    dd = _ffill_rows(np.where(alive, raw_dd, np.nan))
    rep = _ffill_rows(np.where(alive, raw_rep, np.nan))
    rank = _ffill_rows(np.where(alive, raw_rank, np.nan))
    nb = _ffill_rows(np.where(alive, raw_nb, np.nan))
    live = _ffill_rows(np.where(alive, raw_live, np.nan))
    curve = _ffill_rows(np.where(alive, raw_curve, np.nan))
    comp = _ffill_rows(np.where(alive, raw_complete, np.nan))
    created = _ffill_rows(np.where(alive, raw_created, np.nan))
    ltrade = _ffill_rows(np.where(alive, raw_lasttrade, np.nan))

    tv = np.asarray(times, dtype=np.float64)[None, :]

    def lag(A: np.ndarray, k: int) -> np.ndarray:
        out = np.full_like(A, np.nan)
        if k < A.shape[1]:
            out[:, k:] = A[:, :-k]
        return out

    h5, h30 = HORIZON_STEPS["5m"], HORIZON_STEPS["30m"]
    ret5 = lp - lag(lp, h5)
    ret30 = lp - lag(lp, h30)
    step = lp - lag(lp, 1)
    # trailing realised vol over 5 minutes, from the 30s log steps
    rv = np.full_like(lp, np.nan)
    if T > h5:
        s2 = np.where(np.isfinite(step), step, np.nan) ** 2
        cs = np.nancumsum(np.nan_to_num(s2, nan=0.0), axis=1)
        cn = np.cumsum(np.isfinite(s2), axis=1)
        num = cs[:, h5:] - cs[:, :-h5]
        den = cn[:, h5:] - cn[:, :-h5]
        rv[:, h5:] = np.sqrt(np.where(den > 2, num / np.maximum(den, 1), np.nan))

    tenure = np.where(alive, (cols - first[:, None]) * GRID_S / 60.0, np.nan).astype(np.float32)

    # market-wide: board entries per minute, on the same grid
    ents = np.asarray(raw["entries"], dtype=np.float64)
    churn = np.zeros(T, dtype=np.float64)
    if ents.size:
        for j, t in enumerate(times):
            churn[j] = float(np.searchsorted(ents, t) - np.searchsorted(ents, t - 60))
    churn_p = np.repeat(churn[None, :].astype(np.float32), M, axis=0)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mkt = np.nanmedian(np.where(alive, ret5, np.nan), axis=0)
    mkt_p = np.repeat(np.nan_to_num(mkt, nan=0.0)[None, :].astype(np.float32), M, axis=0)

    rs = np.random.default_rng(abs(hash(cohort)) % (2**31))
    plc_coin = np.repeat(rs.normal(size=(M, 1)).astype(np.float32), T, axis=1)
    plc_time = np.repeat(rs.normal(size=(1, T)).astype(np.float32), M, axis=0)

    feats = {
        "log_mcap_sol": lp.astype(np.float32),
        "drawdown_ath": dd.astype(np.float32),
        "log_age_h": np.log1p(np.maximum(tv - created, 0) / 3600.0).astype(np.float32),
        "log_stale_s": np.log1p(np.maximum(tv - ltrade, 0)).astype(np.float32),
        "log_replies": np.log1p(np.maximum(rep, 0)).astype(np.float32),
        "d_replies_5m": (rep - lag(rep, h5)).astype(np.float32),
        "ret_5m": ret5.astype(np.float32),
        "ret_30m": ret30.astype(np.float32),
        "rv_5m": rv.astype(np.float32),
        "rank_best": rank.astype(np.float32),
        "d_rank_5m": (rank - lag(rank, h5)).astype(np.float32),
        "tenure_min": tenure,
        "n_boards": nb.astype(np.float32),
        "is_live": live.astype(np.float32),
        "is_complete": comp.astype(np.float32),
        "curve_progress": curve.astype(np.float32),
        "board_churn_1m": churn_p,
        "mkt_ret_5m": mkt_p,
        "plc_coin": np.where(alive, plc_coin, np.nan).astype(np.float32),
        "plc_market": np.where(alive, plc_time, np.nan).astype(np.float32),
    }
    for k in list(feats):
        feats[k] = np.where(alive, feats[k], np.nan).astype(np.float32)
        if not np.isfinite(feats[k]).any():
            del feats[k]
        elif np.nanstd(feats[k]) < 1e-12:
            del feats[k]

    # ---- targets ----
    # Exit-filled price: after a coin leaves the boards its price is held at the last
    # observed value.  That is the trader's experience (you exit at the last print you
    # can see) and it removes the survivorship conditioning that biased earlier work up.
    lp_fill = _ffill_rows(np.where(alive, lp, np.nan))
    lp_hold = _ffill_rows(lp_fill)      # extends past t_last to the study end

    targets: dict[str, np.ndarray] = {}
    kinds: dict[str, str] = {}
    censor: dict[str, float] = {}
    lastcol = last[:, None]
    g = EXEC_LAG_STEPS
    for hn in RETURN_HORIZONS:
        h = HORIZON_STEPS[hn]
        # EXECUTION LAG, and it is not a detail.  With the entry priced at instant t --
        # the same instant the feature is read -- every trailing-return feature shares
        # the price lp[t] with the forward return, once with each sign.  Microstructure
        # bounce alone then manufactures dependence, and NONE of the nulls here can see
        # it: xsec, rot and mint all break the coin's own pairing, so the artefact reads
        # as significant under every one of them.  Entering one grid step after the
        # snapshot removes the shared price entirely, and is also what a desk can
        # actually do -- you cannot trade on a price in the same instant you learn it.
        fwd = np.full((M, T), np.nan, dtype=np.float32)
        end = T - h - g                      # last column whose exit instant is in-window
        if end <= 0:
            continue
        fwd[:, :end] = (lp_hold[:, g + h:g + h + end]
                        - lp_fill[:, g:g + end]).astype(np.float32)
        trunc = cols >= end
        fwd = np.where(alive & ~trunc, fwd, np.nan)
        # censoring rate = share of evaluable rows whose exit instant is past the coin's
        # last print, i.e. the share of returns that are exit-filled rather than observed
        evaluable = alive & ~trunc
        cens = (cols + g + h) > lastcol
        n_ev = int(evaluable.sum())
        censor[f"fwd_{hn}"] = float((evaluable & cens).sum() / n_ev) if n_ev else 1.0
        targets[f"fwd_{hn}"] = fwd
        kinds[f"fwd_{hn}"] = "cont"
    for hn in EXIT_HORIZONS:
        h = HORIZON_STEPS[hn]
        end = T - h - g
        if end <= 0:
            continue
        trunc = cols >= end
        ex = ((cols + g + h) > lastcol).astype(np.float32)
        targets[f"exit_{hn}"] = np.where(alive & ~trunc, ex, np.nan).astype(np.float32)
        kinds[f"exit_{hn}"] = "binary"
        censor[f"exit_{hn}"] = 0.0     # exact within the window by construction
    for hn in DEAD_HORIZONS:
        h = HORIZON_STEPS[hn]
        end = T - h - g
        if end <= 0:
            continue
        trunc = cols >= end
        lt_f = np.full((M, T), np.nan, dtype=np.float32)
        lt_f[:, :end] = ltrade[:, g + h:g + h + end]
        base = np.full((M, T), np.nan, dtype=np.float32)
        base[:, :end] = ltrade[:, g:g + end]
        dead = (np.abs(lt_f - base) < 1.0).astype(np.float32)
        still = (cols + g + h) <= lastcol   # only observable while the coin is in view
        targets[f"dead_{hn}"] = np.where(alive & ~trunc & still, dead, np.nan).astype(np.float32)
        kinds[f"dead_{hn}"] = "binary"
        ev = int((alive & ~trunc).sum())
        censor[f"dead_{hn}"] = float(((alive & ~trunc) & ~still).sum() / ev) if ev else 1.0
    for k in list(targets):
        v = targets[k]
        if not np.isfinite(v).any() or np.nanstd(v) < 1e-12:
            del targets[k]; del kinds[k]; censor.pop(k, None)

    return Panel(name=cohort, mints=members, times=np.asarray(times), alive=alive,
                 feats=feats, targets=targets, target_kind=kinds, censor=censor,
                 obs=obs)


DETERIORATION_FEATS = ["active_frac_24h", "divergence_raw", "drawdown", "dvol_24",
                       "log_age_days", "log_fdv", "log_turnover", "log_vol_ratio_7d",
                       "ret_24h", "ret_72h", "rv_24h"]
DETERIORATION_TARGETS = ["fwd_24", "fwd_72", "fwd_168"]


def build_deterioration() -> Panel | None:
    """The `dexpool` cohort: 110 graduated DEX pools, hourly, 53.7 days.

    This is the ONLY stream on the desk that reaches the 24 h / 72 h / 168 h horizons
    the brief asks about -- the boards tape is ten hours long and physically cannot
    answer a one-day question.  It is a different asset class (established pools, not
    bonding curves) and a different regime, which makes it a genuine second world
    rather than a re-slice of the first.  Features and forward returns are the
    upstream study's own (`studies/deterioration.py`), reused rather than recomputed.
    """
    fp = ROOT / "state" / "deterioration" / "panel.jsonl"
    if not fp.exists():
        return None
    rows = [json.loads(l) for l in fp.open()]
    if len(rows) < 500:
        return None
    mints = sorted({r["mint"] for r in rows})
    ts = sorted({int(r["t"]) for r in rows})
    step = 3600
    times = list(range(ts[0], ts[-1] + step, step))
    ti = {t: i for i, t in enumerate(times)}
    mi = {m: i for i, m in enumerate(mints)}
    M, T = len(mints), len(times)

    obs = np.zeros((M, T), dtype=bool)
    F = {k: np.full((M, T), np.nan, dtype=np.float32) for k in DETERIORATION_FEATS}
    G = {k: np.full((M, T), np.nan, dtype=np.float32) for k in DETERIORATION_TARGETS}
    for r in rows:
        i, j = mi[r["mint"]], ti[int(r["t"])]
        obs[i, j] = True
        for k in DETERIORATION_FEATS:
            v = r.get(k)
            if v is not None:
                F[k][i, j] = v
        for k in DETERIORATION_TARGETS:
            v = r.get(k)
            if v is not None:
                G[k][i, j] = v

    first = np.argmax(obs, axis=1)
    last = T - 1 - np.argmax(obs[:, ::-1], axis=1)
    cols = np.arange(T)[None, :]
    alive = (cols >= first[:, None]) & (cols <= last[:, None]) & obs.any(axis=1)[:, None]

    feats = {k: np.where(alive, _ffill_rows(np.where(alive, v, np.nan)), np.nan).astype(np.float32)
             for k, v in F.items()}
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mkt = np.nanmedian(np.where(alive, F["ret_24h"], np.nan), axis=0)
    feats["mkt_ret_24h"] = np.where(
        alive, np.repeat(np.nan_to_num(mkt, nan=0.0)[None, :].astype(np.float32), M, axis=0),
        np.nan).astype(np.float32)
    rs = np.random.default_rng(4711)
    feats["plc_coin"] = np.where(alive, np.repeat(rs.normal(size=(M, 1)).astype(np.float32), T, axis=1), np.nan).astype(np.float32)
    feats["plc_market"] = np.where(alive, np.repeat(rs.normal(size=(1, T)).astype(np.float32), M, axis=0), np.nan).astype(np.float32)
    for k in list(feats):
        if not np.isfinite(feats[k]).any() or np.nanstd(feats[k]) < 1e-12:
            del feats[k]

    targets, kinds, censor = {}, {}, {}
    n_alive = int(alive.sum())
    g = EXEC_LAG_STEPS                     # one hourly bar between seeing and trading
    for k, v in G.items():
        # Same execution lag as the boards cohorts: the upstream panel's `fwd_*` start
        # at t, sharing the price at t with `ret_24h`/`drawdown`, so the target is
        # shifted forward one bar to break that shared endpoint.
        sh = np.full((M, T), np.nan, dtype=np.float32)
        if g < T:
            sh[:, :T - g] = v[:, g:]
        t = np.where(alive, sh, np.nan).astype(np.float32)
        if not np.isfinite(t).any():
            continue
        targets[k] = t
        kinds[k] = "cont"
        # censoring here = the tracker stopped following the pool before the horizon
        censor[k] = float(1.0 - np.isfinite(t).sum() / max(n_alive, 1))
    return Panel(name="dexpool", mints=mints, times=np.asarray(times), alive=alive,
                 feats=feats, targets=targets, target_kind=kinds, censor=censor)


WSOL = "So11111111111111111111111111111111111111112"
TAPE_GRID_S = 60
TAPE_HORIZONS = {"5m": 5, "30m": 30, "2h": 120}


def build_tape() -> tuple[Panel | None, dict[str, Any]]:
    """The `tape` cohort: swap-level flow on the desk's own pools, one-minute buckets.

    Replay-grade rows from `state/bulk_history/` (BigQuery, already paid for, 24 h,
    complete-day coverage verified upstream) rather than `state/cluster_tape/`, which
    covers the same pools less completely.

    ON THE RESERVE DEFECT (RESULT_copytrading.md defect 2): nosis and weave price off
    an internal reserve 4.8% / 8.8% BELOW the vault balance.  Price LEVELS from vault
    balances are therefore biased.  Every target here is a log RATIO of two prices from
    the same source, and a constant proportional offset cancels exactly in a ratio, so
    the defect cannot reach the returns.  The `price_basis_check` below verifies this
    empirically by comparing vault-derived returns against returns implied by the
    EXECUTED swap prices, which are independent of the reserve accounting entirely.
    """
    fp = ROOT / "state" / "bulk_history" / "swaps" / "20260813.jsonl"
    if not fp.exists():
        return None, {}
    swaps: dict[str, list] = collections.defaultdict(list)
    fails: dict[str, list] = collections.defaultdict(list)
    for line in fp.open():
        r = json.loads(line)
        k = r.get("kind")
        if k not in ("swap", "failed"):
            continue
        # Filter on the DATA this needs, never on a metadata label.  An earlier version
        # required grade == "replay"; a concurrent re-pull of `state/bulk_history/`
        # relabelled every row "summary" and set replay_sufficient=false while leaving
        # the vault pre/post balances fully intact, and the whole cohort silently
        # vanished from the grid.  What matters is whether the two vault balances are
        # there and positive, and `price_basis_check` below certifies that independently
        # by comparing vault-derived returns against executed swap prices.
        # DLMM is excluded on a DATA-MODEL fact, not a label: Meteora's price is set by
        # the active bin, so the vault ratio is not this pool's price and a return built
        # from it would be fiction.  Constant-product pools only.
        if "dlmm" in str(r.get("dex") or "").lower():
            continue
        lab = r.get("label") or ""
        res = r.get("reserves") or {}
        vaults = res.get("vaults") or []
        if len(vaults) != 2:
            continue
        sol_v = next((v for v in vaults if v["mint"] == WSOL), None)
        tok_v = next((v for v in vaults if v["mint"] != WSOL), None)
        if sol_v is None or tok_v is None:
            continue
        bt = (r.get("chain") or {}).get("block_time")
        if not bt:
            continue
        if k == "failed":
            fails[lab].append(bt)
            continue
        try:
            sol_post = int(sol_v["post_raw"]) / 10 ** int(sol_v["decimals"])
            tok_post = int(tok_v["post_raw"]) / 10 ** int(tok_v["decimals"])
            d_sol = int(sol_v["delta_raw"]) / 10 ** int(sol_v["decimals"])
            d_tok = int(tok_v["delta_raw"]) / 10 ** int(tok_v["decimals"])
        except (TypeError, ValueError, KeyError):
            continue
        if tok_post <= 0 or sol_post <= 0:
            continue
        swaps[lab].append((bt, sol_post / tok_post, d_sol, d_tok))

    pools = sorted([p for p in swaps if len(swaps[p]) >= 100])
    if len(pools) < 2:
        return None, {}

    # --- price-basis check: vault mid vs executed price, on the deepest pool ---
    deep = max(pools, key=lambda p: len(swaps[p]))
    ex_r, vt_r = [], []
    srt = sorted(swaps[deep])
    for (t0, p0, ds0, dt0), (t1, p1, ds1, dt1) in zip(srt, srt[1:]):
        if dt0 == 0 or dt1 == 0 or p0 <= 0 or p1 <= 0:
            continue
        e0, e1 = abs(ds0 / dt0), abs(ds1 / dt1)
        if e0 > 0 and e1 > 0:
            ex_r.append(math.log(e1 / e0))
            vt_r.append(math.log(p1 / p0))
    basis = {"pool": deep, "n_pairs": len(ex_r)}
    if len(ex_r) > 50:
        basis["corr_vault_vs_executed_returns"] = float(
            np.corrcoef(np.asarray(ex_r), np.asarray(vt_r))[0, 1])
        basis["median_abs_gap"] = float(np.median(np.abs(np.asarray(ex_r) - np.asarray(vt_r))))

    allt = [t for p in pools for t, *_ in swaps[p]]
    t0 = int(min(allt) // TAPE_GRID_S * TAPE_GRID_S)
    t1 = int(max(allt) // TAPE_GRID_S * TAPE_GRID_S)
    times = list(range(t0, t1 + TAPE_GRID_S, TAPE_GRID_S))
    ti = {t: i for i, t in enumerate(times)}
    M, T = len(pools), len(times)

    px = np.full((M, T), np.nan, dtype=np.float32)
    buy = np.zeros((M, T)); sell = np.zeros((M, T))
    nsw = np.zeros((M, T)); nfl = np.zeros((M, T))
    szs: dict[tuple[int, int], list[float]] = collections.defaultdict(list)
    for i, p in enumerate(pools):
        for bt, price, d_sol, d_tok in swaps[p]:
            j = ti.get(int(bt // TAPE_GRID_S * TAPE_GRID_S))
            if j is None:
                continue
            px[i, j] = price
            nsw[i, j] += 1
            if d_sol > 0:
                buy[i, j] += d_sol          # SOL into the pool = a buy of the token
            else:
                sell[i, j] += -d_sol
            szs[(i, j)].append(abs(d_sol))
        for bt in fails.get(p, ()):
            j = ti.get(int(bt // TAPE_GRID_S * TAPE_GRID_S))
            if j is not None:
                nfl[i, j] += 1

    obs = np.isfinite(px)
    first = np.argmax(obs, axis=1)
    last = T - 1 - np.argmax(obs[:, ::-1], axis=1)
    cols = np.arange(T)[None, :]
    alive = (cols >= first[:, None]) & (cols <= last[:, None])
    P = _ffill_rows(np.where(alive, px, np.nan))
    lp = np.log(P, out=np.full_like(P, np.nan), where=np.isfinite(P) & (P > 0))

    tot = buy + sell
    with np.errstate(invalid="ignore", divide="ignore"):
        imb = np.where(tot > 0, (buy - sell) / tot, np.nan)
        frate = np.where((nfl + nsw) > 0, nfl / (nfl + nsw), np.nan)
    med_sz = np.full((M, T), np.nan)
    for (i, j), v in szs.items():
        med_sz[i, j] = float(np.median(v))

    def lag(A, k):
        o = np.full_like(A, np.nan)
        if k < A.shape[1]:
            o[:, k:] = A[:, :-k]
        return o

    step = lp - lag(lp, 1)
    rv = np.full_like(lp, np.nan)
    w = 5
    if T > w:
        s2 = np.nan_to_num(step ** 2, nan=0.0)
        cs = np.cumsum(s2, axis=1); cn = np.cumsum(np.isfinite(step), axis=1)
        num = cs[:, w:] - cs[:, :-w]; den = cn[:, w:] - cn[:, :-w]
        rv[:, w:] = np.sqrt(np.where(den > 1, num / np.maximum(den, 1), np.nan))

    rs = np.random.default_rng(1301)
    feats = {
        "flow_imbalance": imb,
        "log_volume_sol": np.log1p(tot),
        "n_swaps_1m": nsw,
        "fail_rate": frate,
        "log_failed_1m": np.log1p(nfl),
        "log_median_clip_sol": np.log1p(med_sz),
        "ret_5m": (lp - lag(lp, 5)),
        "rv_5m": rv,
        "plc_coin": np.repeat(rs.normal(size=(M, 1)), T, axis=1),
        "plc_market": np.repeat(rs.normal(size=(1, T)), M, axis=0),
    }
    feats = {k: np.where(alive, v, np.nan).astype(np.float32) for k, v in feats.items()}
    feats = {k: v for k, v in feats.items()
             if np.isfinite(v).any() and np.nanstd(v) > 1e-12}

    targets, kinds, censor = {}, {}, {}
    g = EXEC_LAG_STEPS                     # one 60s bucket between seeing and trading
    for hn, h in TAPE_HORIZONS.items():
        fwd = np.full((M, T), np.nan, dtype=np.float32)
        end = T - h - g
        if end <= 0:
            continue
        fwd[:, :end] = (lp[:, g + h:g + h + end] - lp[:, g:g + end]).astype(np.float32)
        trunc = cols >= end
        targets[f"fwd_{hn}"] = np.where(alive & ~trunc, fwd, np.nan).astype(np.float32)
        kinds[f"fwd_{hn}"] = "cont"
        ev = int((alive & ~trunc).sum())
        censor[f"fwd_{hn}"] = float(1 - np.isfinite(targets[f"fwd_{hn}"]).sum() / max(ev, 1))

    meta = {"pools": pools, "n_swaps": {p: len(swaps[p]) for p in pools},
            "n_failed": {p: len(fails.get(p, ())) for p in pools},
            "grid_s": TAPE_GRID_S, "T": T, "price_basis_check": basis,
            "horizons_steps": TAPE_HORIZONS}
    return Panel(name="tape", mints=pools, times=np.asarray(times), alive=alive,
                 feats=feats, targets=targets, target_kind=kinds, censor=censor), meta


def stream_audit(primary_t0: int, primary_t1: int) -> dict[str, Any]:
    """What each declared stream could actually contribute, and where it could not.

    A map has to say where it has no coverage, or it silently reports the absence of
    data as the absence of structure.
    """
    import datetime as dt
    import glob as _glob

    def iso(u: float) -> str:
        return dt.datetime.fromtimestamp(u, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    out: dict[str, Any] = {"primary_window": [iso(primary_t0), iso(primary_t1)]}
    for kind in ("new_token", "migration"):
        ts: list[float] = []
        for fp in _glob.glob(str(ROOT / "state" / "firehose" / kind / "*.jsonl")):
            with open(fp) as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    t = r.get("t_ingest")
                    if isinstance(t, str):
                        try:
                            ts.append(dt.datetime.fromisoformat(t).timestamp())
                        except ValueError:
                            pass
        if not ts:
            out[f"firehose_{kind}"] = {"rows": 0, "verdict": "empty"}
            continue
        ts.sort()
        ov = max(0.0, min(ts[-1], primary_t1) - max(ts[0], primary_t0))
        out[f"firehose_{kind}"] = {
            "rows": len(ts), "from": iso(ts[0]), "to": iso(ts[-1]),
            "span_h": (ts[-1] - ts[0]) / 3600,
            "rate_per_min": len(ts) / max((ts[-1] - ts[0]) / 60, 1e-9),
            "overlap_with_primary_h": ov / 3600,
            "verdict": ("UNJOINABLE: zero overlap with the boards window -- the two "
                        "collectors were not running at the same time"
                        if ov <= 0 else "joinable"),
        }
    sq = ROOT / "intelligence_state" / "intelligence.sqlite3"
    if sq.exists():
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{sq}?mode=ro", uri=True)
            tabs = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            counts = {}
            for t in tabs:
                try:
                    counts[t] = con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
                except Exception:
                    counts[t] = None
            con.close()
            out["intelligence_sqlite"] = {"tables": counts}
        except Exception as exc:
            out["intelligence_sqlite"] = {"error": repr(exc)}
    else:
        out["intelligence_sqlite"] = {"verdict": "absent"}
    return out


def ingest() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    _log("reading boards tape ...")
    raw = read_boards()
    observed = sorted(raw["snaps"])
    sess = sessions(observed)
    sess.sort(key=len, reverse=True)
    _log(f"  {len(observed)} observed instants, {len(raw['board_of_mint'])} mints, "
         f"{len(raw['entries'])} board entries, raw span "
         f"{(observed[-1]-observed[0])/3600:.2f} h")
    _log(f"  {len(sess)} collection session(s): " +
         ", ".join(f"{len(s)*GRID_S/3600:.2f}h" for s in sess))
    sol = sol_usd_series(raw["snaps"], observed)
    sv = np.array(list(sol.values()))
    _log(f"  SOL/USD from the curve cohort: {sv.min():.3f}..{sv.max():.3f} "
         f"({100*(sv.max()/sv.min()-1):.2f}% range)")
    meta: dict[str, Any] = {
        "n_observed": len(observed), "t0": observed[0], "t1": observed[-1],
        "raw_span_h": (observed[-1] - observed[0]) / 3600,
        "n_mints_all": len(raw["board_of_mint"]),
        "n_entries": len(raw["entries"]),
        "sol_usd_min": float(sv.min()), "sol_usd_max": float(sv.max()),
        "files": [p.name for p in _boards_files()],
        "sessions": [{"i": i, "t0": s[0], "t1": s[-1], "T": len(s),
                      "hours": len(s) * GRID_S / 3600} for i, s in enumerate(sess)],
        # Sessions are ranked by LENGTH, so the primary would silently change identity
        # the moment the still-running collector's window outgrows the recorded one --
        # and `map.json` would then describe panels that no longer exist. Stamped here
        # and checked wherever a stored result is reused.
        "primary_session": {"t0": sess[0][0], "t1": sess[0][-1], "T": len(sess[0])},
        "cohorts": {}, "holdout_cohorts": {},
    }
    for si, stimes in enumerate(sess):
        tag = "" if si == 0 else f"__s{si}"
        bucket = "cohorts" if si == 0 else "holdout_cohorts"
        for cohort in BOARD_COHORTS:
            p = build_cohort(raw, cohort, stimes, sol)
            if p is None:
                if si == 0:
                    _log(f"  cohort {cohort}: too few qualifying mints, skipped")
                continue
            np.savez_compressed(
                DATA / f"panel_{cohort}{tag}.npz",
                times=p.times, alive=p.alive, obs=p.obs,
                **{f"F__{k}": v for k, v in p.feats.items()},
                **{f"T__{k}": v for k, v in p.targets.items()},
            )
            (DATA / f"panel_{cohort}{tag}.json").write_text(json.dumps(
                {"mints": p.mints, "target_kind": p.target_kind, "censor": p.censor}))
            meta[bucket].setdefault(cohort if si == 0 else f"{cohort}{tag}", {}).update({
                "M": p.M, "T": p.T, "features": sorted(p.feats),
                "targets": sorted(p.targets), "censor": p.censor,
                "alive_rows": int(p.alive.sum()), "session": si,
            })
            _log(f"  s{si} cohort {cohort:7s}: M={p.M:5d} T={p.T} "
                 f"alive_rows={int(p.alive.sum()):8d} feats={len(p.feats)} "
                 f"targets={len(p.targets)}")
    dp = build_deterioration()
    if dp is not None:
        np.savez_compressed(
            DATA / "panel_dexpool.npz", times=dp.times, alive=dp.alive,
            **{f"F__{k}": v for k, v in dp.feats.items()},
            **{f"T__{k}": v for k, v in dp.targets.items()})
        (DATA / "panel_dexpool.json").write_text(json.dumps(
            {"mints": dp.mints, "target_kind": dp.target_kind, "censor": dp.censor}))
        meta["cohorts"]["dexpool"] = {
            "M": dp.M, "T": dp.T, "features": sorted(dp.feats),
            "targets": sorted(dp.targets), "censor": dp.censor,
            "alive_rows": int(dp.alive.sum()), "session": "dexpool-hourly",
            "grid_s": 3600, "span_days": float((dp.times[-1] - dp.times[0]) / 86400),
        }
        _log(f"  dexpool cohort: M={dp.M} T={dp.T} "
             f"({(dp.times[-1]-dp.times[0])/86400:.1f} days hourly) "
             f"alive_rows={int(dp.alive.sum())} feats={len(dp.feats)} "
             f"targets={len(dp.targets)}")

    tp, tmeta = build_tape()
    if tp is not None:
        np.savez_compressed(
            DATA / "panel_tape.npz", times=tp.times, alive=tp.alive,
            **{f"F__{k}": v for k, v in tp.feats.items()},
            **{f"T__{k}": v for k, v in tp.targets.items()})
        (DATA / "panel_tape.json").write_text(json.dumps(
            {"mints": tp.mints, "target_kind": tp.target_kind, "censor": tp.censor}))
        meta["cohorts"]["tape"] = {
            "M": tp.M, "T": tp.T, "features": sorted(tp.feats),
            "targets": sorted(tp.targets), "censor": tp.censor,
            "alive_rows": int(tp.alive.sum()), "session": "bulk_history-20260813",
            "grid_s": TAPE_GRID_S, **tmeta,
        }
        _log(f"  tape cohort: M={tp.M} ({', '.join(tp.mints)}) T={tp.T} 1m buckets, "
             f"feats={len(tp.feats)} targets={len(tp.targets)}")
        _log(f"    price-basis check: {tmeta['price_basis_check']}")

    meta["stream_audit"] = stream_audit(sess[0][0], sess[0][-1])
    for k, v in meta["stream_audit"].items():
        if isinstance(v, dict) and "verdict" in v:
            _log(f"  stream {k}: {v['verdict']}")

    (DATA / "meta.json").write_text(json.dumps(meta, indent=2))
    _log(f"wrote {DATA}/meta.json")


_PANEL_CACHE: dict[str, Panel] = {}
_PANEL_LOCK = __import__("threading").Lock()


def load_panel(cohort: str) -> Panel:
    """Cached.  470 cells over 8 panels means 470 npz decompressions otherwise, which
    dominated the runtime before the cache went in."""
    with _PANEL_LOCK:
        p = _PANEL_CACHE.get(cohort)
    if p is not None:
        return p
    z = np.load(DATA / f"panel_{cohort}.npz")
    j = json.loads((DATA / f"panel_{cohort}.json").read_text())
    feats = {k[3:]: z[k] for k in z.files if k.startswith("F__")}
    targs = {k[3:]: z[k] for k in z.files if k.startswith("T__")}
    p = Panel(name=cohort, mints=j["mints"], times=z["times"], alive=z["alive"],
              feats=feats, targets=targs, target_kind=j["target_kind"], censor=j["censor"],
              obs=(z["obs"] if "obs" in z.files else None))
    with _PANEL_LOCK:
        _PANEL_CACHE[cohort] = p
    return p


# ===========================================================================
# 5. THE GRID
# ===========================================================================


def _rows_for(X: np.ndarray, Y: np.ndarray, n_sub: int, rng: np.random.Generator):
    ok = np.isfinite(X) & np.isfinite(Y)
    mi, ti = np.nonzero(ok)
    n_all = mi.size
    if n_all == 0:
        return None, 0
    if n_all > n_sub:
        pick = rng.choice(n_all, n_sub, replace=False)
        mi, ti = mi[pick], ti[pick]
    return (mi, ti), n_all


class NullDraw:
    """Draws a null (x, y) pair of EXACTLY n_keep rows, without materialising a whole
    null panel.

    The obvious implementation -- transform the entire (M x T) target panel, then index
    the 800 sampled rows out of it -- throws away 99.9% of the work it does. On the
    `hot` cohort that is a 1148 x 1200 argsort per permutation, and it is what made the
    grid too slow to afford the 99,999-permutation stage that the FDR budget actually
    requires. Each null here is expressed directly as a rule for where a sampled row's
    replacement value comes from, so a draw costs O(n_keep) instead of O(M*T):

      xsec  a uniformly chosen OTHER coin observed at the same instant, drawn without
            replacement among the sampled rows that share that instant
      rot   the same coin's value at t+tau, one global tau
      mint  a donor coin's value at the same instant, one global block-local pairing
      iid   any observed value anywhere

    The semantics are identical to `null_panel`; `selftest` checks the two agree.
    """

    def __init__(self, X: np.ndarray, Y: np.ndarray, mi: np.ndarray, ti: np.ndarray,
                 groups: list[np.ndarray] | None) -> None:
        self.X, self.Y, self.mi, self.ti = X, Y, mi, ti
        self.n = mi.size
        self.groups = groups
        self.xrow = X[mi, ti]
        self.yfin = np.isfinite(Y)
        self.M, self.T = Y.shape
        # rows of the panel usable as top-up candidates (X finite), capped for memory
        xm, xt = np.nonzero(np.isfinite(X))
        if xm.size > 200_000:
            step = int(np.ceil(xm.size / 200_000))   # stride, not a 500k-element shuffle
            xm, xt = xm[::step], xt[::step]
        self.cand_m, self.cand_t = xm, xt
        # Per-instant donor pools for the xsec null, flattened so a draw is one gather.
        # The readable version loops over the ~600 distinct sampled instants calling
        # rng.choice per instant; at 199 draws per null per cell that is ~120k Python
        # calls and it was half the runtime of the whole grid.
        uniq, inv = np.unique(ti, return_inverse=True)
        self.uniq_t = uniq
        pools = [np.flatnonzero(self.yfin[:, int(t)]) for t in uniq]
        lens = np.array([p.size for p in pools], dtype=np.int64)
        offs = np.concatenate([[0], np.cumsum(lens)[:-1]]) if lens.size else np.zeros(0, np.int64)
        self.pool_all = (np.concatenate(pools) if pools else np.zeros(0, np.int64))
        self.row_off = offs[inv]
        self.row_len = lens[inv]
        self.flat_fin = np.flatnonzero(self.yfin.ravel())

    def _topup(self, mrow: np.ndarray, trow: np.ndarray, rng) -> tuple | None:
        """Fill out to exactly n rows from the candidate pool, applying the same rule."""
        ok = np.flatnonzero(self.yfin[mrow, trow])
        if ok.size >= self.n:
            sel = ok if ok.size == self.n else rng.choice(ok, self.n, replace=False)
            return self.X[self.mi[sel], self.ti[sel]], self.Y[mrow[sel], trow[sel]]
        return None

    def draw(self, kind: str, rng) -> tuple[np.ndarray, np.ndarray] | None:
        n = self.n
        if kind == "iid":
            if self.flat_fin.size < n:
                return None
            pick = rng.choice(self.flat_fin, n, replace=False)
            return self.xrow, self.Y.ravel()[pick]
        if kind == "xsec":
            # Each sampled row takes the value of a coin drawn uniformly from those
            # observed at the SAME instant. Drawn with replacement across rows that
            # share an instant, so this is a within-instant bootstrap rather than a
            # strict permutation; with pools of tens to hundreds of coins and one to
            # three sampled rows per instant the two are distributionally the same,
            # and `selftest` checks that against the strict-permutation reference.
            if self.pool_all.size == 0 or np.any(self.row_len <= 0):
                return None
            idx = self.row_off + (rng.random(n) * self.row_len).astype(np.int64)
            return self.xrow, self.Y[self.pool_all[idx], self.ti]
        if kind == "rot":
            lo, hi = max(1, self.T // 10), max(2, self.T - self.T // 10)
            tau = int(rng.integers(lo, hi))
            tt = (self.ti + tau) % self.T
            got = self._topup(self.mi, tt, rng)
            if got is not None:
                return got
            ct = (self.cand_t + tau) % self.T
            ok = np.flatnonzero(self.yfin[self.cand_m, ct])
            if ok.size < n:
                return None
            sel = rng.choice(ok, n, replace=False)
            return self.X[self.cand_m[sel], self.cand_t[sel]], self.Y[self.cand_m[sel], ct[sel]]
        if kind == "mint":
            perm = np.arange(self.M)
            if self.groups:
                for g in self.groups:
                    p = rng.permutation(g.size)
                    while g.size > 1 and np.all(p == np.arange(g.size)):
                        p = rng.permutation(g.size)
                    perm[g] = g[p]
            else:
                perm = rng.permutation(self.M)
            got = self._topup(perm[self.mi], self.ti, rng)
            if got is not None:
                return got
            ok = np.flatnonzero(self.yfin[perm[self.cand_m], self.cand_t])
            if ok.size < n:
                return None
            sel = rng.choice(ok, n, replace=False)
            return (self.X[self.cand_m[sel], self.cand_t[sel]],
                    self.Y[perm[self.cand_m[sel]], self.cand_t[sel]])
        raise ValueError(kind)

    def landing(self, kind: str, rng, tries: int = 8) -> float:
        """Share of sampled rows a null actually lands on -- a null that lands on a
        handful of rows has stopped being a test."""
        hits = []
        for _ in range(tries):
            if kind == "mint":
                perm = np.arange(self.M)
                if self.groups:
                    for g in self.groups:
                        perm[g] = g[rng.permutation(g.size)]
                else:
                    perm = rng.permutation(self.M)
                hits.append(float(self.yfin[perm[self.mi], self.ti].mean()))
            elif kind == "rot":
                tau = int(rng.integers(1, max(2, self.T - 1)))
                hits.append(float(self.yfin[self.mi, (self.ti + tau) % self.T].mean()))
            else:
                hits.append(1.0)
        return float(np.mean(hits))


def _perm_p(dx: DcorX, obs: float, nd: NullDraw, kind: str, iters: int,
            rng: np.random.Generator) -> tuple[float, int, float]:
    """Sequential permutation p.  n is held at the observed n by construction, so the
    null distribution is not an artefact of a changing n (dCor is biased upward at
    small n -- a null whose n drifts compares two different statistics)."""
    hits = used = 0
    tot = 0.0
    for _ in range(iters):
        got = nd.draw(kind, rng)
        if got is None:
            continue
        xv, yv = got
        if np.std(yv) < 1e-12 or np.std(xv) < 1e-12:
            continue
        s = DcorX(xv).stat(yv)
        tot += s
        used += 1
        if s >= obs - 1e-12:
            hits += 1
    if used == 0:
        return float("nan"), 0, float("nan")
    return (hits + 1) / (used + 1), used, tot / used


def run_cell(args: tuple) -> dict[str, Any]:
    (cohort, fname, tname, kind, seed) = args
    p = load_panel(cohort)
    X, Y = p.feats[fname], p.targets[tname]
    rng = np.random.default_rng(seed)
    rows, n_all = _rows_for(X, Y, N_SUB, rng)
    out: dict[str, Any] = {
        "cohort": cohort, "feature": fname, "target": tname, "target_kind": kind,
        "seed": int(seed),
        "n_rows": int(n_all), "n_sub": 0, "n_mints": 0,
        "censor": float(p.censor.get(tname, float("nan"))),
    }
    if rows is None or n_all < 100:
        out["status"] = "too_few_rows"
        return out
    mi, ti = rows
    xv, yv = X[mi, ti], Y[mi, ti]
    if np.nanstd(xv) < 1e-12 or np.nanstd(yv) < 1e-12:
        out["status"] = "degenerate"
        return out
    out["n_sub"] = int(mi.size)
    out["n_mints"] = int(np.unique(mi).size)
    out["spearman"] = spearman(xv, yv)
    dx = DcorX(xv)
    obs = dx.stat(yv)
    out["dcor"] = obs

    # Is this feature MARKET-WIDE (identical across coins at each instant)?  If so the
    # xsec null is degenerate BY CONSTRUCTION -- permuting coins within an instant
    # cannot change a value every coin shares -- and the mint null is degenerate too,
    # because it deliberately preserves the market factor.  Such a cell can only be a
    # market-TIMING claim, which this design does not test; flagged so the map never
    # reports "null" for it as though it had been measured.
    Xa = np.where(p.alive, X, np.nan)
    with np.errstate(invalid="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            xsd = np.nanstd(Xa, axis=0)
    xsd = xsd[np.isfinite(xsd)]
    xscale = float(np.nanstd(xv)) or 1.0
    out["market_wide"] = bool(xsd.size and float(np.nanmedian(xsd)) < 1e-6 * xscale)

    # mint-block null validity: does a random reassignment actually land on rows?
    groups = overlap_groups(p.alive)
    nd = NullDraw(X, Y, mi, ti, groups)
    land = nd.landing("mint", rng)
    mint_ok = land >= 0.50
    out["mint_null_landing"] = land
    out["mint_null_blocks"] = len(groups)
    out["rot_null_landing"] = nd.landing("rot", rng)
    nulls = ["iid", "xsec", "rot"] + (["mint"] if mint_ok else [])

    stage_iters = STAGE_PERMS[0]
    res: dict[str, dict] = {}
    for k in nulls:
        pv, used, mean_null = _perm_p(dx, obs, nd, k, stage_iters, rng)
        res[k] = {"p": pv, "iters": used, "null_mean_dcor": mean_null}
    out["nulls"] = res
    out["stage"] = 1
    decisive = [res[k]["p"] for k in nulls if k != "iid" and np.isfinite(res[k]["p"])]
    out["p_decisive"] = max(decisive) if decisive else float("nan")
    out["status"] = "ok"
    if out["market_wide"]:
        out["note"] = ("market-wide feature: xsec and mint nulls are degenerate by "
                       "construction; only a market-TIMING design could test it")

    # MI in bits, bias-corrected against the xsec null
    try:
        mi_obs = ksg_mi_bits(xv, yv, discrete_y=(kind == "binary"), seed=int(seed) % 2**31)
        nullsmi = []
        for _ in range(MI_NULLS):
            got = nd.draw("xsec", rng)
            if got is None:
                continue
            nx, ny = got
            nullsmi.append(ksg_mi_bits(nx, ny, discrete_y=(kind == "binary"),
                                       seed=int(seed) % 2**31))
        out["mi_bits_raw"] = mi_obs
        out["mi_bits_null"] = float(np.mean(nullsmi)) if nullsmi else float("nan")
        out["mi_bits_excess"] = mi_obs - float(np.mean(nullsmi)) if nullsmi else float("nan")
    except Exception as exc:                                   # pragma: no cover
        out["mi_error"] = repr(exc)
    return out


def refine_cell(cell: dict[str, Any], iters: int, seed: int) -> dict[str, Any]:
    p = load_panel(cell["cohort"])
    X, Y = p.feats[cell["feature"]], p.targets[cell["target"]]
    # Reuse the cell's ORIGINAL seed for the row subsample so the refinement is a
    # nested sequential test on the same rows, not a fresh draw that would quietly
    # change the observed statistic between stages.
    rows, _ = _rows_for(X, Y, N_SUB, np.random.default_rng(cell.get("seed", seed)))
    rng = np.random.default_rng(seed)
    mi, ti = rows
    xv, yv = X[mi, ti], Y[mi, ti]
    dx = DcorX(xv)
    obs = dx.stat(yv)
    nd = NullDraw(X, Y, mi, ti, overlap_groups(p.alive))
    cell = dict(cell)
    cell["dcor"] = obs
    for k in list(cell["nulls"]):
        if k == "iid":
            continue
        pv, used, mn = _perm_p(dx, obs, nd, k, iters, rng)
        cell["nulls"][k] = {"p": pv, "iters": used, "null_mean_dcor": mn}
    dec = [cell["nulls"][k]["p"] for k in cell["nulls"]
           if k != "iid" and np.isfinite(cell["nulls"][k]["p"])]
    cell["p_decisive"] = max(dec) if dec else float("nan")
    cell["stage"] = cell.get("stage", 1) + 1
    return cell


def _pmap(fn, items: list, jobs: int, *, label: str = "") -> list:
    """Thread-parallel map with progress.

    Threads, not processes: the inner loop is numpy on 800x800 float32 matrices, which
    releases the GIL, and process pools are not available in this sandbox (workers are
    reaped, `BrokenProcessPool`).  Threads also let every worker share one copy of the
    panels instead of re-decompressing the npz per cell.
    """
    # progress every 25, or every item on a short batch -- a 14-cell stage 3 that logs
    # only on multiples of 25 emits nothing at all for ninety minutes
    every = 25 if len(items) > 50 else max(1, len(items) // 8)
    if jobs <= 1 or len(items) <= 1:
        out = []
        for i, it in enumerate(items):
            out.append(fn(it))
            if label and (i + 1) % every == 0:
                _log(f"  {label}: {i+1}/{len(items)}")
        return out
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out = [None] * len(items)
    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(fn, it): i for i, it in enumerate(items)}
        for f in as_completed(futs):
            out[futs[f]] = f.result()
            done += 1
            if label and done % every == 0:
                _log(f"  {label}: {done}/{len(items)}")
    return out


def enumerate_grid() -> list[tuple]:
    cells: list[tuple] = []
    meta = json.loads((DATA / "meta.json").read_text())
    seed = 90210
    for cohort in sorted(meta["cohorts"]):
        info = meta["cohorts"][cohort]
        kinds = json.loads((DATA / f"panel_{cohort}.json").read_text())["target_kind"]
        for f in sorted(info["features"]):
            for t in sorted(info["targets"]):
                seed += 1
                cells.append((cohort, f, t, kinds.get(t, "cont"), seed))
    return cells


def run_map(jobs: int) -> None:
    cells = enumerate_grid()
    _log(f"grid declared: {len(cells)} cells across "
         f"{len({c[0] for c in cells})} cohorts")
    (DATA / "grid_declared.json").write_text(json.dumps(
        [{"cohort": c[0], "feature": c[1], "target": c[2]} for c in cells], indent=1))

    for cohort in {c[0] for c in cells}:      # warm the cache before threads touch it
        load_panel(cohort)

    t0 = time.time()
    results = _pmap(run_cell, cells, jobs, label="stage 1")
    _log(f"stage 1 ({STAGE_PERMS[0]} perms) done in {time.time()-t0:.0f}s")

    ok = [r for r in results if r.get("status") == "ok"]
    _log(f"  {len(ok)}/{len(results)} cells evaluable")

    for si, (iters, gate) in enumerate(zip(STAGE_PERMS[1:], STAGE_GATES), start=2):
        todo = [i for i, r in enumerate(results)
                if r.get("status") == "ok" and np.isfinite(r.get("p_decisive", np.nan))
                and r["p_decisive"] <= gate]
        if si == len(STAGE_PERMS) and todo:
            # Is another 20x of permutations capable of changing ANY verdict?  A cell at
            # the permutation floor has an unresolved p that could be anywhere below it;
            # every other cell's p is already pinned.  So compare the BY rejection set as
            # it stands against the best case where every floor cell's p goes to zero.
            # If they agree, more draws cannot move the answer and buying them at ~40
            # minutes of CPU per cell would be theatre.
            prev_iters = STAGE_PERMS[si - 2]
            floor = 1.5 / (prev_iters + 1)
            cur = np.array([r.get("p_decisive", 1.0) if r.get("status") == "ok" and
                            np.isfinite(r.get("p_decisive", np.nan)) else 1.0
                            for r in results])
            best = cur.copy()
            best[cur <= floor] = 0.0
            _, rej_now, _ = benjamini_yekutieli(cur, FDR_Q)
            _, rej_best, _ = benjamini_yekutieli(best, FDR_Q)
            n_floor = int((cur <= floor).sum())
            if np.array_equal(rej_now, rej_best):
                _log(f"stage {si} SKIPPED: {n_floor} cells sit at the {prev_iters}-draw "
                     f"floor, and the BY rejection set is identical whether their p-values "
                     f"are taken at the floor or at zero ({int(rej_now.sum())} rejected "
                     f"either way). More permutations cannot change a verdict.")
                for r in results:
                    if r.get("status") == "ok" and np.isfinite(r.get("p_decisive", np.nan)) \
                            and r["p_decisive"] <= floor:
                        r["p_at_permutation_floor"] = True
                break
            if len(todo) > MAX_STAGE3:
                todo.sort(key=lambda i: results[i]["p_decisive"])
                _log(f"stage {si}: {len(todo)} cells at p<={gate}, capping at the "
                     f"{MAX_STAGE3} smallest")
                todo = todo[:MAX_STAGE3]
        _log(f"stage {si} ({iters} perms): {len(todo)} cells at p<={gate}")
        if not todo:
            break
        t1 = time.time()
        payload = [(results[i], iters, 4242 + i) for i in todo]
        ref = _pmap(_refine_star, payload, jobs, label=f"stage {si}")
        for i, r in zip(todo, ref):
            results[i] = r
        _log(f"  stage {si} done in {time.time()-t1:.0f}s")

    # ---- multiplicity over EVERY declared cell, including the unevaluable ones ----
    pv = []
    for r in results:
        p = r.get("p_decisive", float("nan"))
        pv.append(p if np.isfinite(p) else 1.0)
    qv, rej, cm = benjamini_yekutieli(pv, FDR_Q)
    for r, q, rj in zip(results, qv, rej):
        r["q_value"] = float(q)
        r["survives_fdr"] = bool(rj)
    _log(f"BY over {len(results)} cells (c(m)={cm:.3f}, q={FDR_Q}): "
         f"{int(rej.sum())} survive")
    n_floor = sum(1 for r in results if r.get("p_at_permutation_floor"))

    prim = json.loads((DATA / "meta.json").read_text()).get("primary_session")
    (DATA / "map.json").write_text(json.dumps(
        {"n_cells": len(results), "by_c_m": cm, "q": FDR_Q, "primary_session": prim,
         "n_survive": int(rej.sum()), "n_at_permutation_floor": n_floor,
         "stage_perms": STAGE_PERMS, "stage_gates": STAGE_GATES,
         "cells": results}, indent=1))
    _log(f"wrote {DATA}/map.json")


def _refine_star(a: tuple) -> dict:
    return refine_cell(*a)


# ===========================================================================
# 5b. REPLICATION on a held-out collection session
# ===========================================================================


def replicate(jobs: int = 4, top: int = 15) -> None:
    """Re-run a PRE-SPECIFIED short list on a later, disjoint collection session.

    `RESULT_board_entry.md` closes with "one 9.8-hour window, one regime ... a lead,
    not a finding, until it survives a held-out day".  The collector restart that put
    a 3.3 h hole in the tape also handed us a second session; this is what it is for.

    No new multiplicity is created: the short list is fixed by the primary run before
    the held-out data is touched, so this is confirmation, not a second search.  The
    held-out window is short, so ABSENCE of replication at long horizons is weak
    evidence while PRESENCE at short horizons is meaningful.
    """
    mp = json.loads((DATA / "map.json").read_text())
    meta = json.loads((DATA / "meta.json").read_text())
    if mp.get("primary_session") and meta.get("primary_session") \
            and mp["primary_session"] != meta["primary_session"]:
        _log("REFUSING to replicate: the primary session on disk is no longer the one "
             f"the map was run on ({mp['primary_session']} vs {meta['primary_session']}). "
             "Re-run `map` against the current panels first.")
        return
    hold = meta.get("holdout_cohorts", {})
    if not hold:
        _log("no held-out session available (the second collection window is still "
             "shorter than the minimum panel length) -- nothing to replicate on")
        (DATA / "replication.json").write_text(json.dumps(
            {"status": "no_holdout", "reason": "second session shorter than 1h"}, indent=2))
        return
    ok = [c for c in mp["cells"] if c.get("status") == "ok"]
    shortlist = [c for c in ok if c.get("survives_fdr")]
    for c in sorted(ok, key=lambda c: -c.get("dcor", 0)):
        if len(shortlist) >= top:
            break
        if c not in shortlist:
            shortlist.append(c)
    _log(f"replicating {len(shortlist)} pre-specified cells on the held-out session")

    jobsx: list[tuple] = []
    sources: list[dict] = []          # kept parallel to jobsx; zipping against the
    skipped: list[dict] = []          # unfiltered shortlist misaligns every row
    for i, c in enumerate(shortlist):
        name = f"{c['cohort']}__s1"
        info = hold.get(name)
        if info is None:
            continue
        # A horizon longer than the held-out window simply does not exist there. That
        # is a coverage fact about the hold-out, not a failed replication, and it is
        # recorded as such rather than being allowed to raise.
        if c["target"] not in info.get("targets", []):
            skipped.append({"cohort": c["cohort"], "feature": c["feature"],
                            "target": c["target"], "reason": "horizon exceeds the "
                            "held-out window; target absent from that panel"})
            continue
        jobsx.append((name, c["feature"], c["target"], c["target_kind"], 777 + i))
        sources.append(c)
    if not jobsx:
        _log("shortlist cohorts are absent from the held-out session")
        (DATA / "replication.json").write_text(json.dumps(
            {"status": "no_matching_cohorts",
             "holdout_cohorts": sorted(hold),
             "shortlist_cohorts": sorted({c["cohort"] for c in shortlist})}, indent=2))
        return
    for coh in {j[0] for j in jobsx}:
        load_panel(coh)
    res = _pmap(run_cell, jobsx, jobs, label="replicate")
    for r, c in zip(res, sources):
        r["primary_dcor"] = c.get("dcor")
        r["primary_spearman"] = c.get("spearman")
        r["primary_p"] = c.get("p_decisive")
        r["primary_q"] = c.get("q_value")
        r["primary_survives_fdr"] = c.get("survives_fdr")
    hs = json.loads((DATA / "meta.json").read_text()).get("sessions", [])
    win = next((x for x in hs if x["T"] == (list(hold.values())[0] or {}).get("T")), None)
    (DATA / "replication.json").write_text(json.dumps(
        {"status": "ok", "n": len(res), "holdout_window": win,
         "skipped_horizon_too_long": skipped, "cells": res}, indent=1))
    _log(f"wrote {DATA}/replication.json")


# ===========================================================================
# 6. SURVIVAL / COMPETING RISKS
# ===========================================================================


def survival() -> None:
    """Board exit and death as competing risks.  The censoring the return cells carry
    is not a nuisance to apologise for -- it is itself an outcome with a hazard, and if
    a feature moves that hazard it moves the economics of every held position."""
    from lifelines import AalenJohansenFitter, KaplanMeierFitter
    from lifelines.statistics import logrank_test

    out: dict[str, Any] = {}
    meta_all = json.loads((DATA / "meta.json").read_text())["cohorts"]
    for cohort in sorted(meta_all):
        p = load_panel(cohort)
        lp = p.feats["log_mcap_sol"] if "log_mcap_sol" in p.feats else p.feats.get("log_fdv")
        if lp is None:
            continue
        grid_s = float(meta_all[cohort].get("grid_s", GRID_S))
        marks = [1440, 4320, 10080] if grid_s >= 3600 else [30, 120, 480]
        M, T = p.alive.shape
        first = np.argmax(p.alive, axis=1)
        last = T - 1 - np.argmax(p.alive[:, ::-1], axis=1)
        dur = (last - first + 1) * grid_s / 60.0            # minutes in view
        censored = last >= (T - 1)                          # still in view at study end
        # competing events at exit: 1 = exit after a fall (>10% down from entry),
        #                           2 = exit flat-or-up.  A stop-out and a rotation are
        #                           different deaths and must not be pooled.
        ev = np.zeros(M, dtype=int)
        for i in range(M):
            if censored[i]:
                continue
            a, b = lp[i, first[i]], lp[i, last[i]]
            if np.isfinite(a) and np.isfinite(b):
                ev[i] = 1 if (b - a) < math.log(0.90) else 2
            else:
                ev[i] = 2
        kmf = KaplanMeierFitter().fit(dur, ~censored)
        rec: dict[str, Any] = {
            "n": int(M), "censored_at_study_end": int(censored.sum()),
            "median_minutes_in_view": float(kmf.median_survival_time_),
            "exit_down_frac": float((ev == 1).mean()),
            "exit_flat_up_frac": float((ev == 2).mean()),
        }
        if p.obs is not None:
            span = np.maximum(p.alive.sum(axis=1), 1)
            duty = p.obs.sum(axis=1) / span
            rec["median_obs_count"] = float(np.median(p.obs.sum(axis=1)))
            rec["median_duty_cycle"] = float(np.median(duty))
        try:
            ajf = AalenJohansenFitter(calculate_variance=False)
            ajf.fit(dur, ev, event_of_interest=1)
            ci = ajf.cumulative_density_
            rec["cif_marks_minutes"] = marks
            for slot, mins in enumerate(marks, 1):
                idx = ci.index[ci.index <= mins]
                rec[f"cif_down_{slot}"] = float(ci.loc[idx[-1]].iloc[0]) if len(idx) else 0.0
        except Exception as exc:
            rec["aalen_johansen_error"] = repr(exc)

        # does the entry-time drawdown split the exit hazard?  (the board_entry lead)
        dd = p.feats.get("drawdown_ath")
        if dd is not None:
            d0 = np.array([dd[i, first[i]] for i in range(M)], dtype=float)
            g = np.isfinite(d0)
            if g.sum() > 30:
                med = float(np.nanmedian(d0[g]))
                deep = g & (d0 >= med)
                shal = g & (d0 < med)
                if deep.sum() > 10 and shal.sum() > 10:
                    lr = logrank_test(dur[deep], dur[shal], ~censored[deep], ~censored[shal])
                    rec["drawdown_split"] = {
                        "median_drawdown": med,
                        "median_minutes_deep": float(np.median(dur[deep])),
                        "median_minutes_shallow": float(np.median(dur[shal])),
                        "logrank_p": float(lr.p_value),
                        "n_deep": int(deep.sum()), "n_shallow": int(shal.sum()),
                    }
        out[cohort] = rec
        _log(f"  {cohort:7s} median {rec['median_minutes_in_view']:.1f} min in view, "
             f"{100*rec['exit_down_frac']:.0f}% exit down")
    (DATA / "survival.json").write_text(json.dumps(out, indent=2))
    _log(f"wrote {DATA}/survival.json")


# ===========================================================================
# 7. ECONOMICS -- turn a dependence into an edge per trade, or admit it cannot
# ===========================================================================


def decile_spread(p: Panel, fname: str, tname: str, *, top: float = 0.10,
                  seed: int = 7, iters: int = 999) -> dict[str, Any]:
    """The trading form of a cell: at each instant rank the cohort by the feature, take
    the top decile, hold the horizon, net out measured round-trip friction.

    The comparator is NOT cash -- it is a coin drawn at random from the same board at
    the same instant, because that is the alternative a desk actually has.  The p-value
    uses the xsec null, which is exactly that comparator randomised.
    """
    X, Y = p.feats[fname], p.targets[tname]
    ok = np.isfinite(X) & np.isfinite(Y)
    M, T = X.shape
    picks_hi: list[float] = []
    picks_lo: list[float] = []
    allv: list[float] = []
    flat: list[np.ndarray] = []
    ks: list[int] = []
    n_inst = 0
    for t in range(T):
        idx = np.flatnonzero(ok[:, t])
        if idx.size < 10:
            continue
        n_inst += 1
        xs = X[idx, t]
        order = np.argsort(xs)
        k = max(1, int(round(top * idx.size)))
        yt = Y[idx, t].astype(np.float64)
        picks_hi.extend(Y[idx[order[-k:]], t].tolist())
        picks_lo.extend(Y[idx[order[:k]], t].tolist())
        allv.extend(yt.tolist())
        flat.append(yt)
        ks.append(k)
    if not picks_hi:
        return {"status": "no_instants"}
    hi = np.asarray(picks_hi, dtype=float)
    lo = np.asarray(picks_lo, dtype=float)
    al = np.asarray(allv, dtype=float)
    obs_edge = float(np.mean(hi) - np.mean(al))

    # The null is the comparator randomised: at each instant, take k coins AT RANDOM
    # from the ones in view instead of the top k by feature.  Vectorised over instants
    # -- the readable loop was 999 x 1200 Python iterations and dominated the study.
    yflat = np.concatenate(flat)
    lens = np.array([f.size for f in flat], dtype=np.int64)
    offs = np.concatenate([[0], np.cumsum(lens)[:-1]])
    kk = np.array(ks, dtype=np.int64)
    pick_off = np.repeat(offs, kk)
    pick_len = np.repeat(lens, kk)
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(iters):
        idx = pick_off + (rng.random(pick_off.size) * pick_len).astype(np.int64)
        if float(yflat[idx].mean() - al.mean()) >= obs_edge - 1e-15:
            hits += 1
    p_edge = (hits + 1) / (iters + 1)

    gross_hi = float(np.expm1(np.mean(hi)))
    gross_all = float(np.expm1(np.mean(al)))
    net_hi = gross_hi - FRICTION_ROUND_TRIP
    # BREAKEVEN FRICTION is the honest translation.  The desk has exactly one MEASURED
    # round-trip cost -- 2.26% on the pump.fun curve at B* sizing -- and it does not
    # transfer to a graduated DEX pool or a week-long hold.  Rather than invent a
    # friction per venue, report the round trip this cell would have to beat, and let
    # the reader compare it to whatever they can measure for the venue they mean.
    return {
        "status": "ok",
        "n_instants": n_inst, "n_trades_top": int(hi.size),
        "mean_log_top": float(np.mean(hi)), "median_log_top": float(np.median(hi)),
        "mean_log_bottom": float(np.mean(lo)), "mean_log_all": float(np.mean(al)),
        "gross_pct_top": 100 * gross_hi, "gross_pct_cohort": 100 * gross_all,
        "edge_vs_cohort_pct": 100 * (gross_hi - gross_all),
        "long_short_pct": 100 * float(np.expm1(np.mean(hi)) - np.expm1(np.mean(lo))),
        "breakeven_friction_pct": 100 * gross_hi,
        "reference_friction_pct": 100 * FRICTION_ROUND_TRIP,
        "net_pct_top": 100 * net_hi,
        "clears_friction": bool(net_hi > 0),
        "p_edge_xsec": p_edge,
        "p_up_top": float(np.mean(hi > 0)), "p_up_cohort": float(np.mean(al > 0)),
    }


def split_half(p: Panel, fname: str, tname: str, *, top: float = 0.10) -> dict[str, Any]:
    """Does the cell say the same thing in the first and second half of the window?

    Post-hoc on a shortlist the primary run already fixed, so it adds no multiplicity.
    A cell whose sign flips between halves is not a signal whatever its p-value; this
    is the cheapest available answer to `RESULT_board_entry.md`'s standing complaint
    that one window and one regime cannot distinguish a finding from a lead.
    """
    X, Y = p.feats[fname], p.targets[tname]
    T = X.shape[1]
    mid = T // 2
    out: dict[str, Any] = {}
    for tag, sl in (("h1", slice(0, mid)), ("h2", slice(mid, T))):
        Xs, Ys = X[:, sl], Y[:, sl]
        ok = np.isfinite(Xs) & np.isfinite(Ys)
        mi, ti = np.nonzero(ok)
        if mi.size < 100:
            out[tag] = {"n": int(mi.size), "status": "too_few"}
            continue
        rng = np.random.default_rng(5150)
        if mi.size > N_SUB:
            k = rng.choice(mi.size, N_SUB, replace=False)
            mi, ti = mi[k], ti[k]
        xv, yv = Xs[mi, ti], Ys[mi, ti]
        sub = Panel(name=p.name, mints=p.mints, times=p.times[sl], alive=p.alive[:, sl],
                    feats={fname: Xs}, targets={tname: Ys},
                    target_kind={tname: p.target_kind.get(tname, "cont")}, censor={})
        ed = decile_spread(sub, fname, tname, top=top, iters=199)
        out[tag] = {
            "n": int(mi.size),
            "spearman": spearman(xv, yv),
            "dcor": DcorX(xv).stat(yv),
            "edge_vs_cohort_pct": ed.get("edge_vs_cohort_pct"),
            "gross_pct_top": ed.get("gross_pct_top"),
            "status": ed.get("status"),
        }
    a, b = out.get("h1", {}), out.get("h2", {})
    if "spearman" in a and "spearman" in b:
        out["sign_agrees"] = bool((a["spearman"] or 0) * (b["spearman"] or 0) > 0)
        ea, eb = a.get("edge_vs_cohort_pct"), b.get("edge_vs_cohort_pct")
        out["edge_sign_agrees"] = bool(ea is not None and eb is not None and ea * eb > 0)
    return out


def economics() -> None:
    mp = json.loads((DATA / "map.json").read_text())
    cells = [c for c in mp["cells"] if c.get("status") == "ok"]
    surv = [c for c in cells if c.get("survives_fdr")]
    # Always price the top cells by dependence too, so an all-null map still says what
    # the strongest non-significant structure would have been worth.
    ranked = sorted([c for c in cells if c["target"].startswith("fwd_")],
                    key=lambda c: -c.get("dcor", 0))
    pool: list[dict] = []
    seen = set()
    for c in surv + ranked[:12]:
        if not c["target"].startswith("fwd_"):
            continue
        key = (c["cohort"], c["feature"], c["target"])
        if key in seen:
            continue
        seen.add(key)
        pool.append(c)
    out = []
    panels: dict[str, Panel] = {}
    for c in pool:
        if c["cohort"] not in panels:
            panels[c["cohort"]] = load_panel(c["cohort"])
        p = panels[c["cohort"]]
        _log(f"  pricing {c['cohort']}/{c['feature']} -> {c['target']}")
        econ = decile_spread(p, c["feature"], c["target"])
        econ.update({"cohort": c["cohort"], "feature": c["feature"], "target": c["target"],
                     "dcor": c.get("dcor"), "q_value": c.get("q_value"),
                     "survives_fdr": c.get("survives_fdr"),
                     "censor": c.get("censor"),
                     "split_half": split_half(p, c["feature"], c["target"])})
        out.append(econ)
    (DATA / "economics.json").write_text(json.dumps(out, indent=2))
    _log(f"wrote {DATA}/economics.json ({len(out)} priced cells)")


# ===========================================================================
# 8. REPORT
# ===========================================================================


def _fmt(v: Any, spec: str = ".3f") -> str:
    if v is None:
        return "--"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(f):
        return "--"
    return format(f, spec)


def report() -> None:
    meta = json.loads((DATA / "meta.json").read_text())
    mp = json.loads((DATA / "map.json").read_text())
    cells = mp["cells"]
    ok = [c for c in cells if c.get("status") == "ok"]
    lines: list[str] = []
    A = lines.append

    A("## Grid as declared\n")
    sess = meta.get("sessions", [])
    A(f"- boards tape: {meta['n_observed']} observed instants at {GRID_S}s over a raw span of "
      f"{meta['raw_span_h']:.2f} h, split into {len(sess)} collection session(s) "
      f"({', '.join(f'{s['hours']:.2f}h' for s in sess)}); files {', '.join(meta['files'])}")
    A(f"- cells declared: **{mp['n_cells']}**; evaluable: **{len(ok)}**; "
      f"BY c(m) = {mp['by_c_m']:.3f} at q={mp['q']}")
    A(f"- cells surviving FDR: **{mp['n_survive']}**\n")

    A("| cohort | what it is | mints | instants | grid | features | targets |")
    A("|---|---|---|---|---|---|---|")
    what = {"hot": "recently-traded board: fresh, violent, high churn",
            "mcap": "top-market-cap board: graduated, persistent",
            "live": "livestreaming board",
            "frozen": "all-time reply boards -- NEGATIVE CONTROL, near-dead",
            "dexpool": "graduated DEX pools, hourly, 53.7 days",
            "tape": "swap-level flow, 4 constant-product pools, 24h"}
    for k, v in sorted(meta["cohorts"].items()):
        gs = int(v.get("grid_s", GRID_S))
        label = f"{gs//3600}h" if gs >= 3600 else (f"{gs//60}m" if gs >= 60 else f"{gs}s")
        A(f"| `{k}` | {what.get(k, '')} | {v['M']} | {v['T']} | "
          f"{label} | {len(v['features'])} | {len(v['targets'])} |")
    A("")

    aud = meta.get("stream_audit", {})
    if aud:
        A("## Stream coverage audit\n")
        A(f"Primary boards window: {aud.get('primary_window', ['?', '?'])[0]} -> "
          f"{aud.get('primary_window', ['?', '?'])[1]}.\n")
        A("| stream | rows | window | overlap with primary | verdict |")
        A("|---|---|---|---|---|")
        for k, v in aud.items():
            if not isinstance(v, dict) or "verdict" not in v:
                continue
            A(f"| `{k}` | {v.get('rows', '--')} | "
              f"{v.get('from', '--')} -> {v.get('to', '--')} | "
              f"{_fmt(v.get('overlap_with_primary_h'), '.2f')} h | {v['verdict']} |")
        isq = aud.get("intelligence_sqlite", {})
        if isinstance(isq.get("tables"), dict):
            nz = {k: v for k, v in isq["tables"].items() if v}
            A(f"\n`intelligence.sqlite3`: {len(isq['tables'])} tables, "
              f"{len(nz)} non-empty" + (f" ({', '.join(f'{k}={v}' for k, v in sorted(nz.items())[:8])})" if nz else ""))
        A("")
    tape_meta = meta["cohorts"].get("tape", {})
    if tape_meta.get("price_basis_check"):
        b = tape_meta["price_basis_check"]
        A("**Tape price basis.** Vault-derived one-minute returns vs returns implied by the "
          f"EXECUTED swap prices on `{b.get('pool')}` over {b.get('n_pairs')} consecutive "
          f"pairs: correlation {_fmt(b.get('corr_vault_vs_executed_returns'))}, median "
          f"absolute gap {_fmt(100*(b.get('median_abs_gap') or 0), '.3f')}%. The reserve-level "
          "defect in `RESULT_copytrading.md` biases price LEVELS; every target here is a log "
          "ratio, in which a constant proportional offset cancels exactly.\n")

    A("## Where information lives: cohort x target family\n")
    A("Max dCor over the features in that cell block, and how many of its cells survive "
      "FDR. This is the map at a glance -- it answers *where could a strategy exist* "
      "before anyone spends a week finding out that it does not.\n")
    fams: dict[str, str] = {}
    for c in ok:
        t = c["target"]
        fams[t] = ("return" if t.startswith("fwd_") else
                   "board exit" if t.startswith("exit_") else
                   "trading death" if t.startswith("dead_") else "other")
    famnames = ["return", "board exit", "trading death"]
    cohs = sorted({c["cohort"] for c in ok})
    A("| cohort | " + " | ".join(famnames) + " |")
    A("|---" * (len(famnames) + 1) + "|")
    for co in cohs:
        cells_row = []
        for fam in famnames:
            sub = [c for c in ok if c["cohort"] == co and fams.get(c["target"]) == fam]
            if not sub:
                cells_row.append("--")
                continue
            best = max(sub, key=lambda c: c.get("dcor", 0))
            nsurv = sum(1 for c in sub if c.get("survives_fdr"))
            cells_row.append(f"{_fmt(best.get('dcor'))} ({nsurv}/{len(sub)})")
        A(f"| `{co}` | " + " | ".join(cells_row) + " |")
    A("")

    A("## Placebo audit\n")
    A("`plc_coin` is a random constant per coin; `plc_market` is a random series shared "
      "by every coin. Neither can carry information about anything. If either survives, "
      "the machinery is broken and nothing else on this page counts.\n")
    A("| placebo | cells | max dCor | min q | any survive |")
    A("|---|---|---|---|---|")
    for pf in ("plc_coin", "plc_market"):
        sub = [c for c in ok if c["feature"] == pf]
        if not sub:
            continue
        A(f"| `{pf}` | {len(sub)} | {_fmt(max(c.get('dcor', 0) for c in sub))} | "
          f"{_fmt(min(c.get('q_value', 1) for c in sub))} | "
          f"{'**YES -- BROKEN**' if any(c.get('survives_fdr') for c in sub) else 'no'} |")
    frozen_cells = [c for c in ok if c["cohort"] == "frozen"]
    if frozen_cells:
        A(f"\n`frozen` cohort (the near-dead all-time reply boards, a NEGATIVE CONTROL "
          f"cohort rather than a placebo feature): {len(frozen_cells)} cells, "
          f"{sum(1 for c in frozen_cells if c.get('survives_fdr'))} survive FDR, "
          f"max dCor {_fmt(max(c.get('dcor', 0) for c in frozen_cells))}.")
    A("")

    A("## The map, ranked by dependence\n")
    A("| # | cohort | feature | target | n | dCor | rho | MI bits | p_iid | p_xsec | p_rot | p_mint | p_dec | q (BY) | cens | FDR |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    ranked = sorted(ok, key=lambda c: -c.get("dcor", 0))
    for i, c in enumerate(ranked[:45], 1):
        n = c["nulls"]
        A(f"| {i} | `{c['cohort']}` | `{c['feature']}` | `{c['target']}` | {c['n_sub']} | "
          f"{_fmt(c.get('dcor'))} | {_fmt(c.get('spearman'))} | "
          f"{_fmt(c.get('mi_bits_excess'), '.4f')} | "
          f"{_fmt(n.get('iid', {}).get('p'), '.4f')} | "
          f"{_fmt(n.get('xsec', {}).get('p'), '.4f')} | "
          f"{_fmt(n.get('rot', {}).get('p'), '.4f')} | "
          f"{_fmt(n.get('mint', {}).get('p'), '.4f') if 'mint' in n else 'n/a'} | "
          f"{_fmt(c.get('p_decisive'), '.4f')} | {_fmt(c.get('q_value'), '.3f')} | "
          f"{_fmt(100*c.get('censor', float('nan')), '.0f')}% | "
          f"{'**YES**' if c.get('survives_fdr') else 'no'} |")
    A("")

    A("## Information in bits\n")
    plc_worst = max((c for c in ok if c["feature"] in ("plc_coin", "plc_market")),
                    key=lambda c: c.get("mi_bits_excess") or -9, default=None)
    A("For a binary future, the interpretable number is not the raw mutual information "
      "but the share of the outcome's entropy it resolves. `H(Y)` is the entropy of the "
      "target at its base rate; `excess bits` is the k-NN estimate minus the mean over "
      "null draws.\n")
    if plc_worst is not None:
        A(f"**These numbers are descriptive only, and the placebo says why.** The largest "
          f"MI excess anywhere among the {len([c for c in ok if c['feature'].startswith('plc_')])} "
          f"placebo cells is **{_fmt(plc_worst.get('mi_bits_excess'), '.3f')} bits** on "
          f"`{plc_worst['cohort']}` / `{plc_worst['feature']}` -> `{plc_worst['target']}` -- "
          f"a random constant per coin, which by construction knows nothing. The k-NN "
          f"estimator is not robust to this panel's clustering (few coins, many rows each), "
          f"so bits are reported as a description of effect size and are NOT used for any "
          f"inference here. Every verdict on this page rests on dCor against the nulls, "
          f"where the same placebo lands at q = {_fmt(plc_worst.get('q_value'), '.3f')}.\n")
    A("| cohort | target | base rate | H(Y) bits | best feature | excess bits | share of H(Y) |")
    A("|---|---|---|---|---|---|---|")
    bin_cells = [c for c in ok if c.get("target_kind") == "binary"]
    seen_bt: set[tuple[str, str]] = set()
    for c in sorted(bin_cells, key=lambda c: -(c.get("mi_bits_excess") or -9)):
        key = (c["cohort"], c["target"])
        if key in seen_bt:
            continue
        seen_bt.add(key)
        try:
            pan = load_panel(c["cohort"])
            yv = pan.targets[c["target"]]
            yv = yv[np.isfinite(yv)]
            br = float(np.mean(yv > 0.5))
        except Exception:
            br = float("nan")
        H = (-(br * math.log2(br) + (1 - br) * math.log2(1 - br))
             if np.isfinite(br) and 0 < br < 1 else float("nan"))
        ex = c.get("mi_bits_excess")
        share = (ex / H) if (ex is not None and np.isfinite(ex) and np.isfinite(H) and H > 0) else float("nan")
        A(f"| `{c['cohort']}` | `{c['target']}` | {_fmt(br, '.3f')} | {_fmt(H, '.3f')} | "
          f"`{c['feature']}` | {_fmt(ex, '.4f')} | {_fmt(100*share, '.1f')}% |")
    A("")

    if (DATA / "economics.json").exists():
        econ = json.loads((DATA / "economics.json").read_text())
        A("## Economic translation\n")
        A("Top-decile-by-feature portfolio, rebalanced each instant, held for the horizon. "
          "`cohort %` is the comparator a desk actually has: a coin drawn at random from "
          "the same board at the same instant. `breakeven` is the round-trip friction the "
          "cell would have to beat; compare it to the desk's one MEASURED round trip, "
          f"{100*FRICTION_ROUND_TRIP:.2f}% on the pump.fun curve at B* sizing "
          "(RESULT_bandit_search.md section 5), which does not transfer to graduated pools "
          "or week-long holds.\n")
        A("| cohort | feature | target | trades | top % | cohort % | edge % | breakeven | vs 2.26% | p_edge | cens |")
        A("|---|---|---|---|---|---|---|---|---|---|---|")
        for e in sorted(econ, key=lambda x: -(x.get("edge_vs_cohort_pct") or -1e9)):
            if e.get("status") != "ok":
                continue
            A(f"| `{e['cohort']}` | `{e['feature']}` | `{e['target']}` | {e['n_trades_top']} | "
              f"{_fmt(e['gross_pct_top'], '+.2f')} | {_fmt(e['gross_pct_cohort'], '+.2f')} | "
              f"{_fmt(e['edge_vs_cohort_pct'], '+.2f')} | "
              f"{_fmt(e.get('breakeven_friction_pct'), '+.2f')}% | "
              f"{'clears' if e['clears_friction'] else '**no**'} | {_fmt(e['p_edge_xsec'], '.3f')} | "
              f"{_fmt(100*(e.get('censor') or 0), '.0f')}% |")
        A("")
        A("**Split-half stability.** The same cells measured separately on the first and "
          "second half of the window. A cell whose sign flips is not a signal whatever its "
          "p-value.\n")
        A("| cohort | feature | target | rho h1 | rho h2 | edge% h1 | edge% h2 | sign holds |")
        A("|---|---|---|---|---|---|---|---|")
        for e in sorted(econ, key=lambda x: -(x.get("edge_vs_cohort_pct") or -1e9)):
            sh = e.get("split_half") or {}
            h1, h2 = sh.get("h1", {}), sh.get("h2", {})
            if "spearman" not in h1 or "spearman" not in h2:
                continue
            A(f"| `{e['cohort']}` | `{e['feature']}` | `{e['target']}` | "
              f"{_fmt(h1.get('spearman'))} | {_fmt(h2.get('spearman'))} | "
              f"{_fmt(h1.get('edge_vs_cohort_pct'), '+.2f')} | "
              f"{_fmt(h2.get('edge_vs_cohort_pct'), '+.2f')} | "
              f"{'yes' if sh.get('sign_agrees') else '**no**'}"
              f"{' / edge yes' if sh.get('edge_sign_agrees') else ' / edge **no**'} |")
        A("")

    if (DATA / "survival.json").exists():
        sv = json.loads((DATA / "survival.json").read_text())
        A("## Time in view, and how it ends\n")
        A("`CIF(down)` is the Aalen-Johansen cumulative incidence of leaving the boards "
          "at least 10% below the entry price, with leaving flat-or-up as the competing "
          "risk. Marks are 30m/2h/8h for the 30s cohorts and 24h/72h/168h for `dexpool`.\n")
        A("`duty` is the share of the in-view span a coin was actually on a board: coins "
          "flicker on and off, and the span bridges those gaps because a holder's price "
          "is the last print either way.\n")
        A("| cohort | n | median min in view | duty | exit down | exit flat/up | CIF(down) @1 | @2 | @3 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for k, v in sorted(sv.items()):
            A(f"| `{k}` | {v['n']} | {_fmt(v['median_minutes_in_view'], '.1f')} | "
              f"{_fmt(100*(v.get('median_duty_cycle') or float('nan')), '.0f')}% | "
              f"{_fmt(100*v['exit_down_frac'], '.0f')}% | {_fmt(100*v['exit_flat_up_frac'], '.0f')}% | "
              f"{_fmt(v.get('cif_down_1'), '.3f')} | {_fmt(v.get('cif_down_2'), '.3f')} | "
              f"{_fmt(v.get('cif_down_3'), '.3f')} |")
        A("")
        ds = {k: v.get("drawdown_split") for k, v in sv.items() if v.get("drawdown_split")}
        if ds:
            A("**Time in view, split at the cohort's median drawdown-from-ATH** "
              "(log-rank on the exit hazard):\n")
            A("| cohort | median drawdown | median min, deep | median min, shallow | log-rank p |")
            A("|---|---|---|---|---|")
            for k, v in sorted(ds.items()):
                A(f"| `{k}` | {_fmt(v['median_drawdown'])} | {_fmt(v['median_minutes_deep'], '.1f')} | "
                  f"{_fmt(v['median_minutes_shallow'], '.1f')} | {_fmt(v['logrank_p'], '.2e')} |")
            A("")

    if (DATA / "replication.json").exists():
        rp = json.loads((DATA / "replication.json").read_text())
        A("## Held-out replication\n")
        if rp.get("status") != "ok":
            A(f"Not run: {rp.get('reason', rp.get('status'))}.\n")
        else:
            A("Pre-specified short list, fixed by the primary run, re-measured on a "
              "disjoint later collection session. No new multiplicity.\n")
            A("| cohort | feature | target | n | dCor (primary) | dCor (held-out) | p (held-out) | same sign |")
            A("|---|---|---|---|---|---|---|---|")
            for c in rp["cells"]:
                if c.get("status") != "ok":
                    A(f"| `{c['cohort']}` | `{c['feature']}` | `{c['target']}` | "
                      f"{c.get('n_rows', 0)} | {_fmt(c.get('primary_dcor'))} | -- | -- | "
                      f"{c.get('status')} |")
                    continue
                ss = "yes" if (c.get("spearman", 0) or 0) * (c.get("primary_spearman", 0) or 0) >= 0 else "no"
                A(f"| `{c['cohort']}` | `{c['feature']}` | `{c['target']}` | {c['n_sub']} | "
                  f"{_fmt(c.get('primary_dcor'))} | {_fmt(c.get('dcor'))} | "
                  f"{_fmt(c.get('p_decisive'), '.4f')} | {ss} |")
            A("")

    A("## Null-inflation audit\n")
    A("How often each null rejects at 0.05 across the evaluable grid. The i.i.d. column is "
      "the number this repo has been burned by twice.\n")
    A("| null | rejects at p<0.05 | share |")
    A("|---|---|---|")
    for k in ("iid", "xsec", "rot", "mint"):
        have = [c for c in ok if k in c.get("nulls", {}) and np.isfinite(c["nulls"][k]["p"])]
        if not have:
            continue
        r = sum(1 for c in have if c["nulls"][k]["p"] < 0.05)
        A(f"| `{k}` | {r} / {len(have)} | {100*r/len(have):.1f}% |")
    A("")

    txt = "\n".join(lines)
    (DATA / "report_tables.md").write_text(txt)
    print(txt)
    _log(f"wrote {DATA}/report_tables.md")


# ===========================================================================


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["selftest", "ingest", "map", "replicate", "survival",
                                    "economics", "report", "all"])
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    a = ap.parse_args(argv)
    DATA.mkdir(parents=True, exist_ok=True)
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "ingest":
        ingest(); return 0
    if a.cmd == "map":
        run_map(a.jobs); return 0
    if a.cmd == "replicate":
        replicate(a.jobs); return 0
    if a.cmd == "survival":
        survival(); return 0
    if a.cmd == "economics":
        economics(); return 0
    if a.cmd == "report":
        report(); return 0
    if a.cmd == "all":
        rc = selftest()
        if rc:
            _log("SELFTEST FAILED -- refusing to run the map on uncalibrated machinery")
            return rc
        ingest(); run_map(a.jobs); replicate(a.jobs); survival(); economics(); report()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
