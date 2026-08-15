#!/usr/bin/env python3
"""Search for the entry/exit/sizing PROGRAM over the board-entry tape, with bandits.

The operator's ask: "some kind of search for the program / strategy that would decide
when to enter/exit how much... i'm thinkin about bandits." This is that search.

--------------------------------------------------------------------------------------
WHICH OFF-POLICY METHOD, AND WHY — read this before any number below.
--------------------------------------------------------------------------------------
The board tape is OBSERVATIONAL. We recorded what pump.fun's boards did; we did not take
actions under a logged behaviour policy. There is therefore NO PROPENSITY anywhere in
`state/boards/`, and `shitcoims_replay/ope.py` — IPS/SNIPS/DR — is INAPPLICABLE. Its own
`LoggedDecision.__post_init__` refuses a missing propensity for exactly this reason. Any
IPS number over this tape would be a fabricated denominator, which is the same class of
error as `engine.py:770` stamping a cost basis from the exit quote. **No importance
weight is computed anywhere in this file.**

We take option (c) of the three offered — both a simulator and a direct method — with a
clear primary:

  PRIMARY: (b) THE TAPE AS A SIMULATOR. Entries are replayed in time order; a policy
  picks an action; the tape supplies the price path that resolves it. The evaluation is
  then ON-POLICY inside the simulator, so no reweighting is needed at all: the bandit's
  own propensities exist by construction but are never used as weights, because we get
  the realised reward directly. The bias here is SIMULATOR FIDELITY, not weighting, and
  every fidelity assumption is listed in `SIMULATOR ASSUMPTIONS` below.

  A gift from the simulator: it supplies FULL-INFORMATION counterfactual feedback — the
  reward of every arm at every round is computable. The learners are still fed only the
  chosen arm's reward (real bandit feedback), but the EVALUATOR sees all of it, so
  cumulative regret and the best-fixed-arm-in-hindsight are EXACT, not estimated.

  CROSS-CHECK: (a) DIRECT METHOD. A ridge reward model fitted on the training window
  scores the same policies. Where the two rankings disagree, the disagreement is
  reported; it bounds nothing but it localises where the simulator is doing the work.

--------------------------------------------------------------------------------------
SIMULATOR ASSUMPTIONS — the whole bias budget, stated up front.
--------------------------------------------------------------------------------------
1. PRICE = MARKET CAP RATIO. pump.fun supply is fixed, so mc(t)/mc(t0) is the price
   ratio. This one is nearly free.
2. FILLS AT THE POLLED PRICE. A stop or target "fills" at the 30 s poll observation that
   triggered it. Real fills are worse (we see the trigger late and cross a spread).
   OPTIMISTIC for every path-dependent rule; neutral for hold-to-horizon.
3. NO IMPACT BEYOND THE FRICTION TERM. `2*B/Y` in the friction is the whole impact
   model. At B* the clip is ~0.1% of the pool, so this is small — but it is a model.
4. CENSORING IS RESOLVED, NEVER DROPPED. 96% of 8 h entries are censored; evaluating
   only survivors would be pure survivorship. Instead every position that loses view is
   MARKED OUT at the last price observed AT OR BEFORE the exit trigger (never after — no
   look-ahead), and a HAIRCUT band {0, 25, 50, 100}% is applied to that stale price. The
   0% end is the optimistic bound (it is what `board_entry.py` implicitly assumes, so it
   is the number comparable to the established findings); the 100% end is total loss.
   The PRIMARY tables are reported at haircut 0 and every headline claim is accompanied
   by its BREAKEVEN HAIRCUT — the stale-price discount at which the policy's net return
   crosses zero. That single number is the honest summary of the censoring exposure: it
   says "this rule pays iff a coin that leaves the boards is still worth more than X% of
   its last quote", and the reader can price that belief themselves.
   A hard consequence to keep in view: at haircut 0 a hold rule degenerates toward "hold
   until the tape loses the coin", so HORIZON LENGTH IS PARTLY UNIDENTIFIED — the
   observed-only columns bracket it from the survivorship side.
5. NO STOP CAN FIRE IN THE DARK. While a coin is out of view the simulator cannot
   trigger a rule. OPTIMISTIC for stops.
6. ONE REGIME. 10.0 hours, one day. The in-window temporal split below is the best
   available and it is WEAK: train and test share a session, a SOL price, and a news
   cycle. Nothing here is a held-out-day result.

--------------------------------------------------------------------------------------
PRE-REGISTERED PROTOCOL (PROGRAM.md §3). Fixed before any number was looked at.
--------------------------------------------------------------------------------------
 §3.1  Temporal split only: cohort ordered by entry time, split at 2/3.
 §3.2  Entity grouping: any mint appearing in TRAIN is DELETED from TEST.
 §3.3  No resampling anywhere. Natural base rates throughout.
 §3.5  Base-rate-preserving reporting: n, mean, median, p(win) and the take-rate for
       every policy; never a ratio without its denominator.
 §3.7  Every threshold is printed with its number.
 §3.9  Trials accounting: the grid size N is fixed by construction (108 entry predicates
       x 18 exit rules = 1,944), the deflated-Sharpe haircut is computed against it, and
       an EFFECTIVE N is estimated from the correlation of the trial return streams
       because nested predicates are nowhere near independent.
 §3.10 Run the null.
 §3.12 BOTH controls: a known-ZERO world (outcomes permuted within time blocks, which
       destroys feature→outcome dependence while preserving the marginal outcome
       distribution) and a known-EFFECT world (a fixed uplift planted on a feature that
       carries no real signal). A pipeline that passes only the zero control certifies
       nothing.

FRICTION IS MANDATORY. Round-trip cost `2*swap + 2*priority/B + 2*B/Y` is subtracted
from EVERY return reported in this file. There is no gross number anywhere.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Reuse the reference implementation's tape machinery rather than rebuilding it.
from shitcoims_scalper.policy import (
    LAMPORTS_PER_SOL,
    optimal_size_lamports,
    round_trip_friction,
)
from studies.board_entry import build_price_series, load

TAPE_GLOB = str(Path(__file__).resolve().parent.parent / "state" / "boards" / "*.jsonl")

# --- fixed constants of the study -----------------------------------------------------
H_MAX = 4 * 3600.0  # primary search horizon; the cohort is truncated so every entry can reach it
H_LONG = 8 * 3600.0  # long-horizon extension, run on the smaller cohort that can reach it
OBS_TOL = 240.0  # an observation this close to the target time counts as "at" it (board_entry.py)
GAP_TOL = 300.0  # a mint unseen for longer than this near tape end is administratively censored
DEDUP_S = 5.0  # a mint on k boards yields k near-simultaneous ticks; collapse them
PRIORITY_LAMPORTS = 35_000  # MEASURED (studies/RESULT_execution_landing.md), not assumed
SWAP_FEE_BPS = 100
RHO_MAX_BPS = 200
BANKROLL_CAP_LAMPORTS = LAMPORTS_PER_SOL // 2
HAIRCUTS = (0.0, 0.10, 0.25, 0.50, 1.00)
PRIMARY_HAIRCUT = 0.0  # optimistic bound; every headline is paired with a BREAKEVEN haircut

# exit reason codes
R_HORIZON, R_RULE, R_GAP, R_DEPART, R_NOOBS = 0, 1, 2, 3, 4
R_NOPATH = R_NOOBS  # the "nothing to price against" default
MARKOUT_REASONS = (R_GAP, R_DEPART, R_NOOBS)
REASON_NAMES = {
    R_HORIZON: "reached the horizon with a live quote",
    R_RULE: "an exit rule fired on a live quote",
    R_GAP: "mark-out: blacked out at the exit, seen again later",
    R_DEPART: "mark-out: left the boards for good",
    R_NOOBS: "mark-out: no quote at all inside the horizon",
}
LIVE_REASONS = (R_HORIZON, R_RULE)


# ======================================================================================
# 1. Tape -> entry events with features, and per-mint price paths
# ======================================================================================


def board_membership(rows: list[dict[str, Any]]) -> dict[tuple[str, float], int]:
    """(mint, t_ingest of its entry) -> number of boards it sat on at that moment.

    "How many boards simultaneously" is on the operator's feature list and is not in any
    single record; it exists only as state over the event stream, so it has to be replayed.
    """
    live: dict[str, set[str]] = defaultdict(set)
    seeded: set[str] = set()  # seed from each board's first snapshot, else t=0 looks empty
    ordered = sorted(rows, key=lambda r: (r.get("t_ingest") or 0.0))
    at_entry: dict[tuple[str, float], int] = {}
    for r in ordered:
        kind = r.get("kind")
        if kind == "board_snapshot":
            b = r["board"]
            if b not in seeded:
                seeded.add(b)
                for m in r.get("members", []):
                    live[m["mint"]].add(b)
        elif kind == "board_entry":
            live[r["mint"]].add(r["board"])
            at_entry[(r["mint"], r["t_ingest"])] = len(live[r["mint"]])
        elif kind == "board_exit":
            live[r["mint"]].discard(r["board"])
    return at_entry


def dedup_series(series: dict[str, list[tuple[float, float]]]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Collapse near-simultaneous ticks (same mint seen on several boards) to one point."""
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for mint, pts in series.items():
        if not pts:
            continue
        ts = np.fromiter((p[0] for p in pts), dtype=np.float64, count=len(pts))
        mc = np.fromiter((p[1] for p in pts), dtype=np.float64, count=len(pts))
        order = np.argsort(ts, kind="stable")
        ts, mc = ts[order], mc[order]
        keep = np.ones(len(ts), dtype=bool)
        keep[:-1] = (ts[1:] - ts[:-1]) > DEDUP_S  # keep the LAST of each cluster
        out[mint] = (np.ascontiguousarray(ts[keep]), np.ascontiguousarray(mc[keep]))
    return out


@dataclass(slots=True)
class Cohort:
    """Entries with features, aligned arrays. Row i of every array is the same entry."""

    mint: list[str]
    t0: np.ndarray
    mc0: np.ndarray
    drawdown: np.ndarray
    rank: np.ndarray
    board: list[str]
    sol_curve: np.ndarray  # SOL units
    reply: np.ndarray
    age_s: np.ndarray
    live: np.ndarray  # is_currently_live
    complete: np.ndarray  # graduated to PumpSwap
    n_boards: np.ndarray
    trade_recency_s: np.ndarray
    friction: np.ndarray  # round-trip fraction at B*
    size_lamports: np.ndarray

    def __len__(self) -> int:
        return len(self.mint)

    def take(self, mask: np.ndarray) -> "Cohort":
        idx = np.flatnonzero(mask)
        return Cohort(
            mint=[self.mint[i] for i in idx],
            t0=self.t0[idx],
            mc0=self.mc0[idx],
            drawdown=self.drawdown[idx],
            rank=self.rank[idx],
            board=[self.board[i] for i in idx],
            sol_curve=self.sol_curve[idx],
            reply=self.reply[idx],
            age_s=self.age_s[idx],
            live=self.live[idx],
            complete=self.complete[idx],
            n_boards=self.n_boards[idx],
            trade_recency_s=self.trade_recency_s[idx],
            friction=self.friction[idx],
            size_lamports=self.size_lamports[idx],
        )


def build_cohort(
    entries: list[dict[str, Any]],
    nb: dict[tuple[str, float], int],
    horizon: float,
    tape_end: float,
    size_mult: float = 1.0,
) -> Cohort:
    """Entries that (a) have a usable price, (b) have a known drawdown, (c) can reach `horizon`.

    (c) is what removes ADMINISTRATIVE censoring from the primary result: if the tape ends
    before t0+horizon, the position could never be resolved and including it would confound
    "the coin died" with "the recorder stopped".
    """
    keep = []
    for e in entries:
        if (e.get("usd_market_cap") or 0.0) <= 0:
            continue
        if (e.get("drawdown_from_ath", -1.0) or -1.0) < 0:
            continue
        if (e.get("virtual_sol_reserves") or 0) <= 0:
            continue  # no pool -> friction is infinite -> the trade does not exist
        if e["t_ingest"] + horizon > tape_end:
            continue
        keep.append(e)
    keep.sort(key=lambda e: e["t_ingest"])

    n = len(keep)
    sol = np.array([(e.get("virtual_sol_reserves") or 0) for e in keep], dtype=np.float64)
    size = np.empty(n, dtype=np.float64)
    fric = np.empty(n, dtype=np.float64)
    for i, y in enumerate(sol):
        b = optimal_size_lamports(
            int(y),
            priority_fee_lamports=PRIORITY_LAMPORTS,
            rho_max_bps=RHO_MAX_BPS,
            bankroll_cap_lamports=BANKROLL_CAP_LAMPORTS,
        )
        b = int(b * size_mult)
        b = min(b, int(y) * RHO_MAX_BPS // 10_000, BANKROLL_CAP_LAMPORTS)
        size[i] = b
        fric[i] = round_trip_friction(
            int(b), int(y), swap_fee_bps=SWAP_FEE_BPS, priority_fee_lamports=PRIORITY_LAMPORTS
        )

    def col(key: str, default: float = 0.0) -> np.ndarray:
        return np.array([float(e.get(key) or default) for e in keep], dtype=np.float64)

    t0 = col("t_ingest")
    created = col("created_unix")
    last_trade = col("last_trade_unix")
    return Cohort(
        mint=[e["mint"] for e in keep],
        t0=t0,
        mc0=col("usd_market_cap"),
        drawdown=col("drawdown_from_ath"),
        rank=col("rank"),
        board=[e["board"] for e in keep],
        sol_curve=sol / LAMPORTS_PER_SOL,
        reply=col("reply_count"),
        age_s=np.clip(t0 - created, 0.0, None),
        live=np.array([1.0 if e.get("is_currently_live") else 0.0 for e in keep]),
        complete=np.array([1.0 if e.get("complete") else 0.0 for e in keep]),
        n_boards=np.array([float(nb.get((e["mint"], e["t_ingest"]), 1)) for e in keep]),
        trade_recency_s=np.clip(t0 - last_trade, 0.0, None),
        friction=fric,
        size_lamports=size,
    )


# ======================================================================================
# 2. Exit rules — resolved against the observed path, never past it
# ======================================================================================


@dataclass(frozen=True, slots=True)
class ExitRule:
    name: str
    kind: str  # "hold" | "trail" | "bracket" | "trail_after"
    horizon: float
    up: float = math.inf
    down: float = math.inf
    trail: float = math.inf
    arm_after: float = math.inf

    @property
    def label(self) -> str:
        return self.name


def exit_grid(hmax: float) -> list[ExitRule]:
    """18 exit rules. Fixed by construction — this count feeds the trials accounting."""
    rules = [
        ExitRule("hold_15m", "hold", 900.0),
        ExitRule("hold_30m", "hold", 1800.0),
        ExitRule("hold_1h", "hold", 3600.0),
        ExitRule("hold_2h", "hold", 7200.0),
        ExitRule("hold_3h", "hold", 10800.0),
        ExitRule(f"hold_{int(hmax/3600)}h", "hold", hmax),
        ExitRule("trail_15", "trail", hmax, trail=0.15),
        ExitRule("trail_25", "trail", hmax, trail=0.25),
        ExitRule("trail_40", "trail", hmax, trail=0.40),
        ExitRule("tp12_sl30", "bracket", hmax, up=0.12, down=0.30),  # the operator's own trade
        ExitRule("tp30_sl30", "bracket", hmax, up=0.30, down=0.30),
        ExitRule("tp50_sl30", "bracket", hmax, up=0.50, down=0.30),
        ExitRule("tp30_sl15", "bracket", hmax, up=0.30, down=0.15),
        ExitRule("tp100_sl50", "bracket", hmax, up=1.00, down=0.50),
        ExitRule("tp20_sl10", "bracket", hmax, up=0.20, down=0.10),
        ExitRule("sl30_only", "bracket", hmax, down=0.30),
        ExitRule("tp30_only", "bracket", hmax, up=0.30),
        ExitRule("arm20_trail20", "trail_after", hmax, arm_after=0.20, trail=0.20),
    ]
    return rules


def resolve_paths(
    cohort: Cohort,
    paths: dict[str, tuple[np.ndarray, np.ndarray]],
    rules: list[ExitRule],
    tape_end: float,
    last_seen: dict[str, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(gross_ratio[n,E], reason[n,E], capital_s[n,E]) for every entry x exit rule.

    The exit price is ALWAYS an observation at or before the trigger time. Nothing in this
    function reads a price later than the moment the rule fires.

    `capital_s` is how long the BANKROLL is tied up, which is not the same as when the
    mark-out price was quoted: on a mark-out we do not learn we have lost the coin until
    the plan says to sell, so the capital is committed for the full rule horizon even
    though the price we get is the stale one. Freeing it at the stale quote's timestamp
    would let the portfolio recycle capital on information it does not have.
    """
    n, E = len(cohort), len(rules)
    gross = np.ones((n, E), dtype=np.float64)
    reason = np.full((n, E), R_NOPATH, dtype=np.int8)
    hold = np.array([[r.horizon for r in rules]] * n, dtype=np.float64) if n else np.zeros((0, E))

    for i in range(n):
        mint, t0, mc0 = cohort.mint[i], cohort.t0[i], cohort.mc0[i]
        ts, mc = paths.get(mint, (None, None))
        if ts is None or len(ts) == 0:
            continue
        lo = int(np.searchsorted(ts, t0 + DEDUP_S, side="left"))
        # +OBS_TOL, or the longest-horizon rule can never find its own live quote: an
        # observation at t0+8h+30s must still be inside the slice for `d[k]-H <= OBS_TOL`
        # to have anything to test. Getting this wrong reports 0% live fills at 8 h.
        hi = int(np.searchsorted(ts, t0 + H_LONG + OBS_TOL, side="right"))
        if hi <= lo:
            continue
        d = ts[lo:hi] - t0
        r = mc[lo:hi] / mc0
        # Did this mint vanish from the tape, or did the tape simply end?
        permanently_gone = last_seen.get(mint, tape_end) < tape_end - GAP_TOL

        peak = np.maximum.accumulate(r)
        for j, rule in enumerate(rules):
            H = rule.horizon
            k = int(np.searchsorted(d, H, side="left"))  # first obs at/after H
            trig = -1
            if rule.kind == "trail":
                fired = r <= peak * (1.0 - rule.trail)
                fired[k:] = False
                trig = int(np.argmax(fired)) if fired.any() else -1
            elif rule.kind == "bracket":
                fired = np.zeros(len(r), dtype=bool)
                if math.isfinite(rule.up):
                    fired |= r >= (1.0 + rule.up)
                if math.isfinite(rule.down):
                    fired |= r <= (1.0 - rule.down)
                fired[k:] = False
                trig = int(np.argmax(fired)) if fired.any() else -1
            elif rule.kind == "trail_after":
                armed = np.maximum.accumulate((r >= 1.0 + rule.arm_after).astype(np.int8)) > 0
                fired = armed & (r <= peak * (1.0 - rule.trail))
                fired[k:] = False
                trig = int(np.argmax(fired)) if fired.any() else -1

            if trig >= 0:
                gross[i, j], reason[i, j], hold[i, j] = r[trig], R_RULE, d[trig]
                continue
            # No rule fired: resolve at the horizon, or mark out at the last price we saw
            # strictly before it. `d[k] - H <= OBS_TOL` is board_entry.py's tolerance.
            if k < len(d) and d[k] - H <= OBS_TOL:
                gross[i, j], reason[i, j], hold[i, j] = r[k], R_HORIZON, d[k]
            elif k > 0:
                # It came back later in the window -> a temporary blackout (R_GAP);
                # nothing after, and nothing anywhere in the tape -> it is gone (R_DEPART).
                gone = k >= len(d) and permanently_gone
                gross[i, j], reason[i, j] = r[k - 1], (R_DEPART if gone else R_GAP)
            else:
                # No observation of this coin anywhere inside [t0, t0+H]. Mark out at the
                # entry price; that is the last thing we actually saw.
                gross[i, j], reason[i, j] = 1.0, R_NOOBS
    return gross, reason, hold


def net_returns(
    gross: np.ndarray,
    reason: np.ndarray,
    friction: np.ndarray,
    haircut: float,
    rule_slip: float = 0.0,
) -> np.ndarray:
    """NET fractional return. Mark-outs are haircut; friction is subtracted from all of them.

    `rule_slip` is the adverse fill penalty on a TRIGGERED exit, and it is the sensitivity
    that matters most for bracket rules. Simulator assumption #2 fills a stop or target at
    the 30 s poll observation that revealed the trigger; a live desk sees the trigger late
    and crosses a spread, so every rule fire is worse than the tape says. Holds and
    mark-outs are unaffected — this penalty is exactly the advantage brackets are getting
    for free, priced.
    """
    markout = np.isin(reason, MARKOUT_REASONS)
    eff = np.where(markout, gross * (1.0 - haircut), gross)
    out = eff - 1.0 - friction[:, None]
    if rule_slip:
        out = out - rule_slip * (reason == R_RULE)
    return out


# ======================================================================================
# 3. Entry predicates
# ======================================================================================


@dataclass(frozen=True, slots=True)
class EnterRule:
    dd_max: float
    board: str
    sol_min: float
    mcap_min: float

    @property
    def label(self) -> str:
        b = "any" if self.board == "any" else self.board[:9]
        return f"dd<{self.dd_max:.2f} board={b} sol>={self.sol_min:g} mc>={self.mcap_min:g}"

    def mask(self, c: Cohort) -> np.ndarray:
        m = c.drawdown < self.dd_max
        if self.board != "any":
            m &= np.array([b == self.board for b in c.board])
        m &= c.sol_curve >= self.sol_min
        m &= c.mc0 >= self.mcap_min
        return m


def enter_grid() -> list[EnterRule]:
    """108 entry predicates = 4 drawdown x 3 board x 3 pool floor x 3 market-cap floor."""
    out = []
    for dd in (0.30, 0.50, 0.70, 1.01):
        for board in ("any", "last_trade_timestamp", "currently-live"):
            for sol in (0.0, 10.0, 30.0):
                for mc in (0.0, 1e4, 1e5):
                    out.append(EnterRule(dd, board, sol, mc))
    return out


# ======================================================================================
# 4. Statistics: mint-clustered SE, deflated Sharpe, effective trials
# ======================================================================================


def clustered_stats(x: np.ndarray, groups: list[str]) -> tuple[float, float, int]:
    """(mean, cluster-robust SE by mint, n_clusters). Entries of one mint are not independent."""
    n = len(x)
    if n == 0:
        return 0.0, float("inf"), 0
    mu = float(x.mean())
    dev = x - mu
    sums: dict[str, float] = defaultdict(float)
    for v, g in zip(dev, groups, strict=True):
        sums[g] += v
    meat = sum(s * s for s in sums.values())
    g = len(sums)
    if g <= 1 or n == 0:
        return mu, float("inf"), g
    # CR0 with the usual small-cluster correction
    scale = (g / (g - 1)) * ((n - 1) / max(n - 1, 1))
    return mu, math.sqrt(meat * scale) / n, g


def norm_ppf(p: float) -> float:
    from scipy.stats import norm

    return float(norm.ppf(p))


def norm_sf(z: float) -> float:
    from scipy.stats import norm

    return float(norm.sf(z))


def expected_max_sharpe(trial_sharpes: np.ndarray, n_trials: int) -> float:
    """Bailey & Lopez de Prado: E[max SR] under a null of zero true skill over N trials.

    E[max] ~= sqrt(V) * ((1-g) * Phi^-1(1 - 1/N) + g * Phi^-1(1 - 1/(N*e)))
    """
    if n_trials < 2:
        return 0.0
    v = float(np.std(trial_sharpes, ddof=1))
    gamma = 0.5772156649015329
    a = norm_ppf(1.0 - 1.0 / n_trials)
    b = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return v * ((1.0 - gamma) * a + gamma * b)


def effective_trials(streams: np.ndarray) -> float:
    """How many INDEPENDENT policies did we really try?

    The 1,944 grid cells are nested predicates over the same entries; their per-entry
    return streams are massively correlated, so a Bonferroni over 1,944 is far too harsh
    and a naive DSR over 1,944 is too. Estimate the effective count as the number of
    principal components of the (standardised) trial return streams needed for 95% of the
    variance. Reported alongside the raw N, never instead of it.
    """
    x = np.nan_to_num(streams, nan=0.0, posinf=0.0, neginf=0.0)
    x = x - x.mean(axis=0, keepdims=True)
    sd = x.std(axis=0, ddof=1)
    sd[sd == 0] = 1.0
    x = x / sd
    # Singular values of the standardised stream matrix; squares are the PCA eigenvalues.
    # SVD rather than eigvalsh on the Gram: forming X'X squares the condition number and a
    # near-collinear grid (which this one is, by construction) then fails to converge.
    try:
        s = np.linalg.svd(x, compute_uv=False)
    except np.linalg.LinAlgError:
        return float(streams.shape[1])
    w = s**2
    tot = w.sum()
    if tot <= 0:
        return 1.0
    cum = np.cumsum(w) / tot
    return float(np.searchsorted(cum, 0.95) + 1)


def breakeven_haircut(
    gross: np.ndarray, reason: np.ndarray, friction: np.ndarray, rows: np.ndarray, col: int
) -> float:
    """The stale-price discount at which this policy's mean NET return crosses zero.

    mean_net(h) is linear in h: only the mark-out rows are scaled, so
      mean(h) = mean(gross_eff at h) - 1 - mean(friction)
    with d/dh = -mean(gross * markout). One division, no search.
    """
    g = gross[rows, col]
    mk = np.isin(reason[rows, col], MARKOUT_REASONS)
    if len(g) == 0:
        return float("nan")
    at0 = float(g.mean()) - 1.0 - float(friction[rows].mean())
    slope = float((g * mk).mean())
    if slope <= 0:
        return float("inf") if at0 > 0 else float("-inf")
    return at0 / slope


# ======================================================================================
# 5. Portfolio replay under a real bankroll
# ======================================================================================


def portfolio_replay(
    c: Cohort,
    keep: np.ndarray,
    net: np.ndarray,
    hold_s: np.ndarray,
    exit_idx: int | np.ndarray,
    bankroll_sol: float,
) -> dict[str, float]:
    """Time-ordered replay with finite capital and one position per mint.

    The unconstrained per-entry mean is the clean statistical object; THIS is the number
    the operator actually experiences, because 1 SOL of bankroll cannot hold 20,000
    simultaneous positions.
    """
    order = np.argsort(c.t0, kind="stable")
    free = bankroll_sol * LAMPORTS_PER_SOL
    open_pos: list[tuple[float, float, int]] = []  # (exit_t, size_lamports, row)
    held: set[str] = set()
    realised = 0.0
    taken = 0
    blocked_capital = 0
    blocked_dupe = 0
    peak_deployed = 0.0
    for i in order:
        t = c.t0[i]
        # settle everything that matured before now
        still = []
        for et, sz, row in open_pos:
            if et <= t:
                e = exit_idx if isinstance(exit_idx, int) else int(exit_idx[row])
                realised += sz * net[row, e]
                free += sz
                held.discard(c.mint[row])
            else:
                still.append((et, sz, row))
        open_pos = still
        if not keep[i]:
            continue
        if c.mint[i] in held:
            blocked_dupe += 1
            continue
        sz = float(c.size_lamports[i])
        if sz <= 0 or sz > free:
            blocked_capital += 1
            continue
        e = exit_idx if isinstance(exit_idx, int) else int(exit_idx[i])
        free -= sz
        held.add(c.mint[i])
        open_pos.append((t + max(hold_s[i, e], 1.0), sz, int(i)))
        taken += 1
        peak_deployed = max(peak_deployed, bankroll_sol * LAMPORTS_PER_SOL - free)
    for _et, sz, row in open_pos:  # mark the book out at the end of the tape
        e = exit_idx if isinstance(exit_idx, int) else int(exit_idx[row])
        realised += sz * net[row, e]
        free += sz
    return {
        "pnl_sol": realised / LAMPORTS_PER_SOL,
        "pnl_pct_bankroll": realised / (bankroll_sol * LAMPORTS_PER_SOL) * 100.0,
        "taken": float(taken),
        "signalled": float(int(keep.sum())),
        "blocked_capital": float(blocked_capital),
        "blocked_dupe": float(blocked_dupe),
        "peak_deployed_sol": peak_deployed / LAMPORTS_PER_SOL,
    }


# ======================================================================================
# 6. Contextual bandits
# ======================================================================================


def context_matrix(c: Cohort, ref: Cohort | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Standardised feature matrix with a bias column. Returns (X, mu, sd)."""
    boards = ("last_trade_timestamp", "currently-live", "market_cap")
    cols = [
        c.drawdown,
        (c.drawdown < 0.50).astype(np.float64),
        np.log10(np.clip(c.mc0, 1.0, None)),
        np.log10(1.0 + c.reply),
        np.log10(1.0 + c.age_s),
        c.rank / 50.0,
        c.live,
        c.complete,
        np.log10(np.clip(c.sol_curve, 1e-3, None)),
        np.log10(1.0 + c.trade_recency_s),
        c.n_boards,
    ]
    for b in boards:
        cols.append(np.array([1.0 if x == b else 0.0 for x in c.board]))
    X = np.column_stack(cols)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    return np.column_stack([Xs, np.ones(len(X))]), mu, sd


class DisjointLinear:
    """Per-arm ridge regression, the common core of eps-greedy / LinUCB / LinTS."""

    def __init__(self, n_arms: int, d: int, lam: float = 1.0) -> None:
        self.A = np.stack([np.eye(d) * lam for _ in range(n_arms)])
        self.b = np.zeros((n_arms, d))
        self.Ainv = np.stack([np.eye(d) / lam for _ in range(n_arms)])
        self.theta = np.zeros((n_arms, d))

    def update(self, arm: int, x: np.ndarray, r: float) -> None:
        Ai = self.Ainv[arm]
        Aix = Ai @ x
        self.Ainv[arm] = Ai - np.outer(Aix, Aix) / (1.0 + float(x @ Aix))
        self.b[arm] += r * x
        self.theta[arm] = self.Ainv[arm] @ self.b[arm]


def run_bandit(
    algo: str,
    X: np.ndarray,
    rewards: np.ndarray,
    seed: int,
    eps: float = 0.10,
    alpha: float = 0.50,
    v: float = 0.10,
    delay_s: np.ndarray | None = None,
    t_round: np.ndarray | None = None,
) -> dict[str, Any]:
    """One online pass in time order. `rewards[t, k]` is FULL-INFORMATION for the evaluator;
    the learner is only ever shown `rewards[t, chosen]`.

    DELAYED FEEDBACK. Pass `delay_s` (per round x arm, the capital-lock time) and
    `t_round` to enforce the thing a live desk cannot escape: a 4 h hold does not teach
    you anything for 4 hours. Without it an online learner on this tape is quietly given
    an oracle it would not have, because rewards resolve hours after the decision.
    """
    rng = np.random.default_rng(seed)
    T, K = rewards.shape
    d = X.shape[1]
    model = DisjointLinear(K, d)
    chosen = np.empty(T, dtype=np.int32)
    got = np.empty(T, dtype=np.float64)
    pending: list[tuple[float, int, np.ndarray, float]] = []
    n_updates = 0
    for t in range(T):
        if delay_s is not None and t_round is not None:
            now = t_round[t]
            keep = []
            for ready, a_, x_, r_ in pending:
                if ready <= now:
                    model.update(a_, x_, r_)
                    n_updates += 1
                else:
                    keep.append((ready, a_, x_, r_))
            pending = keep
        x = X[t]
        if algo == "epsgreedy":
            a = int(rng.integers(K)) if rng.random() < eps else int(np.argmax(model.theta @ x))
        elif algo == "linucb":
            mu = model.theta @ x
            bonus = alpha * np.sqrt(np.einsum("kd,kde,e->k", np.broadcast_to(x, (K, d)), model.Ainv, x))
            a = int(np.argmax(mu + bonus))
        elif algo == "lints":
            mu = model.theta @ x
            var = np.einsum("kd,kde,e->k", np.broadcast_to(x, (K, d)), model.Ainv, x)
            a = int(np.argmax(mu + v * np.sqrt(np.clip(var, 0, None)) * rng.standard_normal(K)))
        else:
            raise ValueError(algo)
        r = float(rewards[t, a])
        if delay_s is not None and t_round is not None:
            pending.append((t_round[t] + float(delay_s[t, a]), a, x, r))
        else:
            model.update(a, x, r)
            n_updates += 1
        chosen[t] = a
        got[t] = r
    return {"chosen": chosen, "reward": got, "cum": float(got.sum()), "updates": n_updates}


# ======================================================================================
# 7. Reporting helpers
# ======================================================================================


def pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def summarise_policy(
    net_col: np.ndarray,
    mints: list[str],
    label: str,
    reason_col: np.ndarray | None = None,
) -> dict[str, Any]:
    mu, se, ng = clustered_stats(net_col, mints)
    med = float(np.median(net_col)) if len(net_col) else 0.0
    pw = float((net_col > 0).mean()) if len(net_col) else 0.0
    sd = float(net_col.std(ddof=1)) if len(net_col) > 1 else 0.0
    row: dict[str, Any] = {
        "label": label,
        "n": len(net_col),
        "mints": ng,
        "mean": mu,
        "se": se,
        "t": mu / se if se > 0 and math.isfinite(se) else 0.0,
        "median": med,
        "p_win": pw,
        "sharpe": mu / sd if sd > 0 else 0.0,
        "live_share": float("nan"),
        "live_mean": float("nan"),
    }
    if reason_col is not None and len(reason_col):
        live = np.isin(reason_col, LIVE_REASONS)
        row["live_share"] = float(live.mean())
        row["live_mean"] = float(net_col[live].mean()) if live.any() else float("nan")
    return row


def print_table(rows: list[dict[str, Any]], title: str, live: bool = False) -> None:
    print(f"\n  {title}")
    head = f"    {'policy':<46}{'n':>7}{'mints':>7}{'mean':>9}{'t':>7}{'median':>9}{'p(win)':>8}{'SR':>7}"
    if live:
        head += f"{'live%':>7}{'live mean':>11}"
    print(head)
    for r in rows:
        line = (
            f"    {r['label'][:45]:<46}{r['n']:>7}{r['mints']:>7}{pct(r['mean']):>9}"
            f"{r['t']:>7.2f}{pct(r['median']):>9}{r['p_win'] * 100:>7.0f}%{r['sharpe']:>7.3f}"
        )
        if live:
            lm = r.get("live_mean", float("nan"))
            ls = r.get("live_share", float("nan"))
            line += f"{ls * 100:>6.0f}%" + (f"{pct(lm):>11}" if lm == lm else f"{'—':>11}")
        print(line)


# ======================================================================================
# 8. Worlds: real, known-zero, known-effect
# ======================================================================================


def zero_world(net: np.ndarray, t0: np.ndarray, rng: np.random.Generator, blocks: int = 20) -> np.ndarray:
    """KNOWN-ZERO. Permute whole outcome ROWS within time blocks.

    Permuting rows (not cells) preserves the correlation between exit rules and the
    marginal outcome distribution per block, while destroying every link between an
    entry's FEATURES and its outcome. A search that still finds a winner here is finding
    the multiple-testing floor, and that is exactly what we want to measure.
    """
    out = net.copy()
    edges = np.linspace(t0.min(), t0.max() + 1.0, blocks + 1)
    for k in range(blocks):
        idx = np.flatnonzero((t0 >= edges[k]) & (t0 < edges[k + 1]))
        if len(idx) > 1:
            out[idx] = net[rng.permutation(idx)]
    return out


def effect_world(
    net: np.ndarray, c: Cohort, uplift: float = 0.08, carrier: str = "parity"
) -> tuple[np.ndarray, np.ndarray]:
    """KNOWN-EFFECT. Plant `uplift` on a carrier and check the instrument recovers it.

    TWO carriers, because the grid and the bandit can see different things and a control
    an estimator is structurally incapable of passing tests nothing:
      "parity"  — `reply_count` parity, an arbitrary bit. The GRID cannot select on it at
                  all, so this one tests only the bandit, which is handed the bit as a
                  context feature.
      "mcap"    — market cap >= $100k, which IS one of the grid's four axes. This is the
                  carrier the grid must find, and if it does not, its null is meaningless.
    """
    bit = (c.reply.astype(np.int64) % 2) == 0 if carrier == "parity" else (c.mc0 >= 1e5)
    return net + uplift * bit[:, None], bit


# ======================================================================================
# 9. Main
# ======================================================================================


def grid_search(
    c: Cohort,
    net: np.ndarray,
    enters: list[EnterRule],
    exits: list[ExitRule],
    min_n: int,
) -> list[dict[str, Any]]:
    """Score every (enter, exit) cell that clears the minimum-sample floor."""
    rows: list[dict[str, Any]] = []
    masks = [e.mask(c) for e in enters]
    for ei, er in enumerate(enters):
        m = masks[ei]
        if m.sum() < min_n:
            continue
        sub = net[m]
        mints = [c.mint[i] for i in np.flatnonzero(m)]
        for xi, xr in enumerate(exits):
            row = summarise_policy(sub[:, xi], mints, f"{er.label} | {xr.label}")
            row["enter"], row["exit"] = ei, xi
            row["take_rate"] = float(m.mean())
            rows.append(row)
    return rows


def trial_streams(c: Cohort, net: np.ndarray, enters: list[EnterRule], exits: list[ExitRule],
                  rows: list[dict[str, Any]]) -> np.ndarray:
    """Per-entry return stream of every surviving grid cell (0 where the policy abstains).

    Abstention is a real zero for a bankroll, so this is the right object both for the
    effective-trials PCA and for comparing policies with different take rates.
    """
    masks = [e.mask(c) for e in enters]
    out = np.zeros((len(c), len(rows)), dtype=np.float64)
    for j, r in enumerate(rows):
        m = masks[r["enter"]]
        out[m, j] = net[m, r["exit"]]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tape", default=TAPE_GLOB)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--bankroll-sol", type=float, default=1.0)
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--n-perm", type=int, default=10, help="known-zero worlds for the permutation floor")
    ap.add_argument("--skip-worlds", action="store_true", help="skip the two controls (fast iteration)")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    t_start = time.time()

    print("=" * 96)
    print("BANDIT / POLICY SEARCH OVER THE BOARD-ENTRY TAPE")
    print("=" * 96)
    print("  OPE choice: SIMULATOR REPLAY (on-policy inside the tape) + a DIRECT-METHOD")
    print("  cross-check. No importance weight is computed: the tape has NO logged")
    print("  propensity, so IPS/SNIPS from shitcoims_replay/ope.py would be a fabricated")
    print("  denominator. Every return below is NET of round-trip friction.")

    rows_raw = load(args.tape)
    entries = [r for r in rows_raw if r.get("kind") == "board_entry"]
    tape_end = max(r["t_ingest"] for r in rows_raw if r.get("t_ingest"))
    tape_start = min(r["t_ingest"] for r in rows_raw if r.get("t_ingest"))
    series = build_price_series(rows_raw)
    paths = dedup_series(series)
    last_seen = {m: float(ts[-1]) for m, (ts, _mc) in paths.items() if len(ts)}
    nb = board_membership(rows_raw)
    print(
        f"\n  tape: {len(rows_raw):,} rows · {len(entries):,} board entries · "
        f"{len(paths):,} mints in view · {(tape_end - tape_start) / 3600:.2f} h"
    )

    exits = exit_grid(H_MAX)
    enters = enter_grid()
    c = build_cohort(entries, nb, H_MAX, tape_end)
    print(
        f"  cohort (drawdown known AND t0 + {H_MAX / 3600:.0f}h <= tape end): {len(c):,} entries, "
        f"{len(set(c.mint)):,} mints"
    )
    print("    the horizon truncation is what removes ADMINISTRATIVE censoring: every entry")
    print("    kept here could in principle have been resolved before the recorder stopped.")

    gross, reason, hold = resolve_paths(c, paths, exits, tape_end, last_seen)
    tot = reason.size
    print(f"\n  EXIT RESOLUTION ({len(c):,} entries x {len(exits)} rules) — how positions ended,")
    print("  and what the last price we saw was worth relative to entry:")
    print(f"    {'':<48}{'share':>8}{'median gross':>14}{'mean gross':>12}")
    for code in (R_HORIZON, R_RULE, R_GAP, R_DEPART, R_NOOBS):
        sel = reason == code
        share = sel.sum() / tot * 100
        g = gross[sel]
        med = float(np.median(g)) if g.size else float("nan")
        mn = float(g.mean()) if g.size else float("nan")
        print(f"    {REASON_NAMES[code]:<48}{share:>7.1f}%{med:>14.3f}{mn:>12.3f}")
    mo = float(np.isin(reason, MARKOUT_REASONS).mean())
    mg = gross[np.isin(reason, MARKOUT_REASONS)]
    print(f"    -> {mo * 100:.1f}% of resolutions are STALE-PRICE mark-outs, at a median gross of")
    print(f"       {float(np.median(mg)):.3f}. Coins do NOT visibly collapse on the way out of view;")
    print("       they leave near where they came in, which is why the haircut is a BELIEF about")
    print("       the unobserved rest of the path and not something the tape can settle.")

    # ---------------------------------------------------------------- friction / sizing
    print("\n" + "-" * 96)
    print("SIZING — 5 configurations. B* = sqrt(priority * Y), priority = 35,000 lamports.")
    print("-" * 96)
    print(f"    {'size':<14}{'median B (SOL)':>16}{'median friction':>18}{'capped by rho/bankroll':>24}")
    for mult in (0.25, 0.5, 1.0, 2.0, 4.0):
        cm = build_cohort(entries, nb, H_MAX, tape_end, size_mult=mult)
        raw = np.sqrt(PRIORITY_LAMPORTS * cm.sol_curve * LAMPORTS_PER_SOL) * mult
        capped = float(np.mean(cm.size_lamports < raw - 1))
        print(
            f"    {mult:g}x B*{'':<8}{np.median(cm.size_lamports) / LAMPORTS_PER_SOL:>16.4f}"
            f"{np.median(cm.friction) * 100:>17.2f}%{capped * 100:>23.1f}%"
        )
    print("    Friction is U-shaped in B and the U is SHALLOW: +-2x off B* costs ~0.07pp of round")
    print("    trip and +-4x costs ~0.30pp. The pool-impact and bankroll caps barely bind at B*,")
    print("    so SIZE IS NOT WHERE THE SEARCH LIVES. It is fixed at B* for everything below.")

    # ---------------------------------------------------------------- temporal split
    print("\n" + "-" * 96)
    print("SPLIT (PROGRAM.md §3.1 temporal, §3.2 entity)")
    print("-" * 96)
    cut = float(np.quantile(c.t0, 2.0 / 3.0))
    is_train = c.t0 < cut
    train_mints = {c.mint[i] for i in np.flatnonzero(is_train)}
    is_test = (~is_train) & np.array([m not in train_mints for m in c.mint])
    dropped = int(((~is_train) & ~is_test).sum())
    print(f"    train: entries before t+{(cut - tape_start) / 3600:.2f}h  ->  {int(is_train.sum()):,}")
    print(f"    test:  entries after, on mints UNSEEN in train  ->  {int(is_test.sum()):,}")
    print(f"    dropped from test for straddling a train mint: {dropped:,}")
    print("    WEAKNESS, stated as §3.1 requires: this is ONE 10 h window. Train and test share")
    print("    a session, a SOL price and a news cycle. An in-window split cannot detect regime")
    print("    dependence, which is the failure mode that costs 54 points of recall elsewhere.")

    # ---------------------------------------------------------------- the baseline
    print("\n" + "=" * 96)
    print(f"PRIMARY RESULTS — haircut {PRIMARY_HAIRCUT:.0%} on stale-price mark-outs (the OPTIMISTIC")
    print("end of the band; the breakeven haircut is reported with every headline), NET of friction")
    print("=" * 96)
    net = net_returns(gross, reason, c.friction, PRIMARY_HAIRCUT)
    hold_idx = {r.name: i for i, r in enumerate(exits)}
    base_exit = hold_idx[f"hold_{int(H_MAX / 3600)}h"]
    base_enter = EnterRule(0.50, "any", 0.0, 0.0)
    base_mask = base_enter.mask(c)

    def report_split(mask: np.ndarray, exit_i: int, label: str) -> dict[str, Any]:
        idx = np.flatnonzero(mask & is_test)
        row = summarise_policy(net[idx, exit_i], [c.mint[i] for i in idx], label, reason[idx, exit_i])
        row["be"] = breakeven_haircut(gross, reason, c.friction, idx, exit_i)
        row["take"] = float((mask & is_test).sum()) / max(int(is_test.sum()), 1)
        return row

    baseline_rows = [
        report_split(base_mask, base_exit, "BASELINE: dd<0.50, hold 4h [TEST]"),
        report_split(np.ones(len(c), bool), base_exit, "enter everything, hold 4h [TEST]"),
        report_split(~base_mask, base_exit, "dd>=0.50 (deep), hold 4h [TEST]"),
        report_split(base_mask, hold_idx["hold_30m"], "dd<0.50, hold 30m [TEST]"),
        report_split(base_mask, hold_idx["tp12_sl30"], "dd<0.50, +12%/-30% (operator's) [TEST]"),
    ]
    print_table(baseline_rows, "PRE-COMMITTED BASELINES on the held-out window", live=True)
    print("    'live%' is the share of positions that got a REAL quote at the exit; 'live mean' is")
    print("    the return over only those — survivorship-biased UP, and the upper bracket on the")
    print("    horizon question that the mark-outs otherwise blur.")
    print(f"\n    {'policy':<46}{'take rate on TEST':>20}{'breakeven haircut':>20}")
    for r in baseline_rows:
        be = r["be"]
        s = "never profitable" if be < 0 else ("always" if not math.isfinite(be) else f"{be:.1%}")
        print(f"    {r['label'][:45]:<46}{r['take'] * 100:>19.1f}%{s:>20}")
    print("    Read the breakeven as: this rule pays iff a coin that leaves the boards is still")
    print("    worth MORE than (1 - breakeven) of its last quote.")

    # ---------------------------------------------------------------- grid search
    print("\n" + "-" * 96)
    print(f"GRID SEARCH on TRAIN only — {len(enters)} entry predicates x {len(exits)} exit rules"
          f" = {len(enters) * len(exits):,} configurations")
    print("-" * 96)
    ctrain = c.take(is_train)
    net_train = net[is_train]
    rows_tr = grid_search(ctrain, net_train, enters, exits, args.min_n)
    rows_tr.sort(key=lambda r: -r["mean"])
    n_trials = len(enters) * len(exits)
    n_eval = len(rows_tr)
    print(f"    {n_eval:,} of {n_trials:,} cells had >= {args.min_n} train entries and were scored.")
    print_table(rows_tr[:10], "TOP 10 ON TRAIN (in-sample; do not believe these)")

    streams = trial_streams(ctrain, net_train, enters, exits, rows_tr)
    sharpes = np.array([r["sharpe"] for r in rows_tr])
    eff_n = effective_trials(streams)
    haircut_sr = expected_max_sharpe(sharpes, n_eval)
    haircut_sr_eff = expected_max_sharpe(sharpes, max(int(eff_n), 2))
    best = rows_tr[0]
    print("\n  TRIALS ACCOUNTING (§3.9)")
    print(f"    configurations defined by construction   N = {n_trials:,}")
    print(f"    configurations actually scored           N = {n_eval:,}")
    print(f"    EFFECTIVE independent trials (95% PCA)   N = {eff_n:.0f}   <- the grid is nested")
    print(f"    cross-trial SR dispersion                sd = {sharpes.std(ddof=1):.4f}")
    print(f"    E[max SR | no skill, N={n_eval}]          = {haircut_sr:.4f}   (analytic, Bailey/LdP)")
    print(f"    E[max SR | no skill, N_eff={eff_n:.0f}]{'':<7} = {haircut_sr_eff:.4f}")
    print(f"    best in-sample SR                        = {best['sharpe']:.4f}")

    # The analytic haircut is a formula. The permutation floor is a MEASUREMENT of the same
    # quantity on this exact grid and this exact tape, so it is what the verdict uses. Each
    # permutation reruns the WHOLE search on a world where features cannot predict outcomes.
    print(f"\n    PERMUTATION FLOOR — the identical {n_eval:,}-cell search rerun on"
          f" {args.n_perm} known-zero worlds")
    perm_best_mean, perm_best_sr = [], []
    for p in range(args.n_perm):
        nz = zero_world(net_train, ctrain.t0, np.random.default_rng(args.seed + 1000 + p))
        rz = grid_search(ctrain, nz, enters, exits, args.min_n)
        perm_best_mean.append(max(r["mean"] for r in rz))
        perm_best_sr.append(max(r["sharpe"] for r in rz))
    pm, ps = np.array(perm_best_mean), np.array(perm_best_sr)
    p_mean = (1 + int((pm >= best["mean"]).sum())) / (1 + args.n_perm)
    p_sr = (1 + int((ps >= best["sharpe"]).sum())) / (1 + args.n_perm)
    print(f"      permuted best MEAN: median {pct(float(np.median(pm)))}, max {pct(float(pm.max()))}"
          f"   vs real {pct(best['mean'])}   -> p = {p_mean:.3f}")
    print(f"      permuted best SR:   median {float(np.median(ps)):.4f}, max {float(ps.max()):.4f}"
          f"        vs real {best['sharpe']:.4f}   -> p = {p_sr:.3f}")
    print("      A grid this size manufactures a winner out of nothing; the permuted MAX is what")
    print("      'nothing' looks like after the same search. The analytic haircut above and this")
    print("      measurement disagree, and the measurement wins — it is the same estimator on the")
    print("      same data with the signal removed, which is the only floor that is not a formula.")
    verdict = "CLEARS" if p_sr <= 0.05 else "DOES NOT CLEAR"
    print(f"    -> the in-sample winner {verdict} the measured multiple-testing floor (p={p_sr:.3f}).")

    # ---------------------------------------------------------------- the one test look
    print("\n  SELECTED-ON-TRAIN, EVALUATED ONCE ON TEST (this is the honest number)")
    sel_rows = []
    for r in rows_tr[:5]:
        m = enters[r["enter"]].mask(c)
        sel_rows.append(report_split(m, r["exit"], r["label"]))
    sel_rows.append(baseline_rows[0])
    print_table(sel_rows, "train-selected policies vs the pre-committed baseline, on TEST", live=True)
    winner = rows_tr[0]
    w_test = sel_rows[0]
    base_test = baseline_rows[0]
    delta = w_test["mean"] - base_test["mean"]
    # paired difference on the intersection, mint-clustered
    m_w = enters[winner["enter"]].mask(c) & is_test
    m_b = base_mask & is_test
    both = np.flatnonzero(m_w & m_b)
    if len(both):
        d = net[both, winner["exit"]] - net[both, base_exit]
        dmu, dse, dg = clustered_stats(d, [c.mint[i] for i in both])
        p_raw = 2 * norm_sf(abs(dmu / dse)) if dse > 0 and math.isfinite(dse) else 1.0
        p_sidak = 1.0 - (1.0 - p_raw) ** max(eff_n, 1.0)
        print(f"\n    PAIRED vs baseline on the {len(both):,} entries both policies take"
              f" ({dg:,} mints):")
        print(f"      mean difference {pct(dmu)}  (clustered SE {pct(dse)}, t={dmu / dse:.2f})")
        print(f"      p = {p_raw:.4f} raw;  {p_sidak:.4f} after Sidak on N_eff = {eff_n:.0f}")
    print(f"\n    winner - baseline, unpaired means on TEST: {pct(delta)}")

    # ---------------------------------------------------------------- haircut band
    print("\n  HAIRCUT SENSITIVITY — the same two policies at every mark-out assumption [TEST]")
    print(f"    {'haircut on stale-price mark-outs':<38}{'baseline mean':>16}{'winner mean':>16}")
    bi = np.flatnonzero(base_mask & is_test)
    wi = np.flatnonzero(m_w)
    for h in HAIRCUTS:
        nh = net_returns(gross, reason, c.friction, h)
        bm = float(nh[bi, base_exit].mean()) if len(bi) else 0.0
        wm = float(nh[wi, winner["exit"]].mean()) if len(wi) else 0.0
        print(f"    {h:>6.0%}{'':<32}{pct(bm):>16}{pct(wm):>16}")
    be_b = breakeven_haircut(gross, reason, c.friction, bi, base_exit)
    be_w = breakeven_haircut(gross, reason, c.friction, wi, winner["exit"])
    print(f"    {'BREAKEVEN haircut':<38}{be_b:>15.1%}{be_w:>16.1%}")

    # ---------------------------------------------------------------- bandits
    print("\n" + "-" * 96)
    print("CONTEXTUAL BANDITS — online replay in time order over the whole cohort")
    print("-" * 96)
    arm_rules = [
        "SKIP",
        "hold_30m",
        "hold_2h",
        f"hold_{int(H_MAX / 3600)}h",
        "trail_25",
        "tp12_sl30",
        "tp30_sl30",
    ]
    arm_exit = [-1] + [hold_idx[a] for a in arm_rules[1:]]
    R = np.zeros((len(c), len(arm_rules)), dtype=np.float64)
    for k, e in enumerate(arm_exit):
        if e >= 0:
            R[:, k] = net[:, e]
    X, _mu, _sd = context_matrix(c)
    print(f"    arms ({len(arm_rules)}): {', '.join(arm_rules)}")
    print(f"    context: {X.shape[1]} standardised features incl. bias; {len(c):,} rounds")
    print("    The simulator gives FULL-INFORMATION counterfactuals, so regret is EXACT.")
    print("    The learners still see only the chosen arm's reward.")

    delay = np.zeros_like(R)
    for k, e in enumerate(arm_exit):
        if e >= 0:
            delay[:, k] = hold[:, e]
    order_t = c.t0

    best_fixed_k = int(np.argmax(R.sum(axis=0)))
    best_fixed_cum = float(R[:, best_fixed_k].sum())
    oracle_cum = float(R.max(axis=1).sum())
    print("\n    Per-arm value if it were played on EVERY round — the fixed-policy field the")
    print("    bandit has to beat. 't' is mint-clustered; 'per cap-hour' divides by the time the")
    print("    bankroll is locked, which is the metric a 1 SOL desk actually maximises.")
    print(f"      {'arm':<12}{'cum':>10}{'%/round':>10}{'t':>8}{'live%':>8}{'%/cap-hour':>13}"
          f"{'breakeven hc':>14}")
    for k, name in enumerate(arm_rules):
        e = arm_exit[k]
        if e < 0:
            print(f"      {name:<12}{0.0:>10.2f}{0.0:>10.3f}{0.0:>8.2f}{'—':>8}{0.0:>13.3f}{'—':>14}")
            continue
        mu, se, _g = clustered_stats(R[:, k], c.mint)
        # Aggregate, not a mean of ratios: total return over total capital-hours. A mean of
        # per-trade r/hours is dominated by whichever trades exited in 30 seconds.
        cap_hours = float(np.maximum(hold[:, e], 300.0).sum()) / 3600.0
        be = breakeven_haircut(gross, reason, c.friction, np.arange(len(c)), e)
        bs = "never" if be < 0 else ("always" if not math.isfinite(be) else f"{be:.1%}")
        live = float(np.isin(reason[:, e], LIVE_REASONS).mean()) * 100
        print(
            f"      {name:<12}{R[:, k].sum():>10.2f}{mu * 100:>10.3f}"
            f"{(mu / se if se > 0 and math.isfinite(se) else 0.0):>8.2f}{live:>7.0f}%"
            f"{R[:, k].sum() / cap_hours * 100:>13.3f}{bs:>14}"
        )

    print("\n    FILL REALISM — the same arms with an adverse slip charged on every TRIGGERED exit")
    print("    (assumption #2 priced). Holds are unaffected because nothing triggers them.")
    print(f"      {'arm':<12}" + "".join(f"{f'slip {s:.0%}':>12}" for s in (0.0, 0.01, 0.02, 0.05)))
    for k, name in enumerate(arm_rules):
        e = arm_exit[k]
        if e < 0:
            continue
        cells = []
        for s in (0.0, 0.01, 0.02, 0.05):
            ns = net_returns(gross, reason, c.friction, PRIMARY_HAIRCUT, rule_slip=s)
            cells.append(f"{ns[:, e].mean() * 100:>11.3f}%")
        print(f"      {name:<12}" + "".join(cells))

    seeds = [args.seed + i for i in range(5)]
    specs: list[tuple[str, str, dict[str, Any], bool]] = [
        ("epsgreedy (eps=0.10)", "epsgreedy", {"eps": 0.10}, False),
        ("LinUCB (alpha=0.50)", "linucb", {"alpha": 0.50}, False),
        ("LinTS (v=0.10)", "lints", {"v": 0.10}, False),
        ("LinUCB, DELAYED feedback", "linucb", {"alpha": 0.50}, True),
        ("LinTS, DELAYED feedback", "lints", {"v": 0.10}, True),
    ]
    Xshuf = X[rng.permutation(len(X))]

    print(f"\n    {'algorithm':<28}{'cum NET':>12}{'mean/round':>12}{'regret':>11}"
          f"{'% skip':>8}{'   [seed spread min..max]':>26}{'shuffled-ctx cum':>18}")
    print(f"    {'always SKIP':<28}{0.0:>12.2f}{0.0:>12.5f}{best_fixed_cum:>11.2f}{100:>7}%"
          f"{'':>26}{'':>18}")
    print(f"    {'best fixed: ' + arm_rules[best_fixed_k]:<28}{best_fixed_cum:>12.2f}"
          f"{best_fixed_cum / len(c):>12.5f}{0.0:>11.2f}{0:>7}%{'':>26}{'':>18}")
    bandit_rows: list[tuple[str, dict[str, Any]]] = []
    for label, algo, kw, delayed in specs:
        dkw = {"delay_s": delay, "t_round": order_t} if delayed else {}
        runs = [run_bandit(algo, X, R, s, **kw, **dkw) for s in seeds]  # type: ignore[arg-type]
        cums = np.array([r["cum"] for r in runs])
        mid = runs[0]
        shuf = run_bandit(algo, Xshuf, R, args.seed, **kw, **dkw)  # type: ignore[arg-type]
        skip = float((mid["chosen"] == 0).mean()) * 100
        upd = f"   upd {mid['updates'] / len(c) * 100:.0f}%" if delayed else ""
        print(
            f"    {label:<28}{cums.mean():>12.2f}{cums.mean() / len(c):>12.5f}"
            f"{best_fixed_cum - cums.mean():>11.2f}{skip:>7.0f}%"
            f"{f'   [{cums.min():.1f} .. {cums.max():.1f}]':>26}{shuf['cum']:>18.2f}{upd}"
        )
        bandit_rows.append((label, mid))
    print(f"    {'per-context ORACLE':<28}{oracle_cum:>12.2f}{oracle_cum / len(c):>12.5f}"
          f"{best_fixed_cum - oracle_cum:>11.2f}{'-':>8}{'':>26}{'':>18}")
    print("    'cum NET' is the sum of per-round net returns at unit stake, averaged over 5 seeds.")
    print("    THREE THINGS TO READ BEFORE THE POINT ESTIMATES:")
    print("     - SEED SPREAD. If min..max straddles the best fixed arm, the algorithm's win is a")
    print("       draw of the RNG, not a property of the policy class.")
    print("     - SHUFFLED CONTEXT. The same algorithm run with the feature rows permuted, so the")
    print("       context is pure noise while the arm-value structure is untouched. Whatever it")
    print("       earns THERE is what arm selection alone is worth; only the excess over it is")
    print("       attributable to the context, which is the entire premise of a CONTEXTUAL bandit.")
    print("     - DELAYED FEEDBACK is the honest protocol. A 4 h hold teaches nothing for 4 hours;")
    print("       an undelayed learner on this tape is handed information a live desk cannot have.")
    print("       'upd N%' is the share of its own decisions the delayed learner ever got told")
    print("       about before the tape ran out. That number is the whole story.")
    print("    The oracle is an UPPER BOUND no causal policy can reach: it picks each arm knowing")
    print("    that entry's realised path. Read it as the ceiling on what context could ever buy.")

    # ---------------------------------------------------------------- capital
    print("\n" + "-" * 96)
    print("CAPITAL-CONSTRAINED PORTFOLIO REPLAY — B* sizing, one position per mint, "
          f"{(c.t0.max() - c.t0.min()) / 3600:.1f} h of entries")
    print("-" * 96)
    port_specs: list[tuple[str, np.ndarray, int | np.ndarray]] = [
        ("BASELINE dd<0.50, hold 4h", base_mask, base_exit),
        (f"winner: {winner['label'][:32]}", enters[winner["enter"]].mask(c), winner["exit"]),
        ("everything, hold 4h", np.ones(len(c), bool), base_exit),
        ("dd<0.50, tp12/sl30 (operator's rule)", base_mask, hold_idx["tp12_sl30"]),
        ("dd<0.50, tp30/sl30", base_mask, hold_idx["tp30_sl30"]),
        ("dd<0.50, hold 30m", base_mask, hold_idx["hold_30m"]),
    ]
    for algo, res in bandit_rows:
        ch = res["chosen"]
        port_specs.append(
            (f"bandit: {algo}", ch != 0, np.array([arm_exit[k] if k else base_exit for k in ch]))
        )
    for bank in (args.bankroll_sol, 5.0, 25.0):
        print(f"\n    bankroll {bank:g} SOL")
        print(f"    {'policy':<40}{'PnL (SOL)':>11}{'% bank':>9}{'trades':>8}{'mean/trade':>12}"
              f"{'signalled':>11}{'refused':>9}{'':>4}")
        for label, mask, ei in port_specs:
            p = portfolio_replay(c, mask, net, hold, ei, bank)
            trades = int(p["taken"])
            flag = "  <- capital-bound" if trades and p["signalled"] > 10 * trades else ""
            clip = float(np.median(c.size_lamports)) / LAMPORTS_PER_SOL
            mt = p["pnl_sol"] / (trades * clip) if trades else 0.0
            print(
                f"    {label:<40}{p['pnl_sol']:>11.4f}{p['pnl_pct_bankroll']:>8.1f}%"
                f"{trades:>8}{mt * 100:>11.1f}%{int(p['signalled']):>11}"
                f"{int(p['blocked_capital']):>9}{flag}"
            )
    print("\n    READ THE TRADE COUNT FIRST. A row flagged capital-bound took under a tenth of the")
    print("    entries it signalled, so its PnL is an arbitrary subsample of the policy and not a")
    print("    measurement of it — at 1 SOL and B* ~= 0.05 SOL the book holds ~19 positions, and")
    print("    an hours-long hold spends the whole window full. At this bankroll the binding")
    print("    constraint is CAPITAL, not signal: a rule that RECYCLES capital dominates a rule")
    print("    that picks better, and that is a fact about the account, not about the market.")

    # ---------------------------------------------------------------- direct method
    print("\n" + "-" * 96)
    print("DIRECT-METHOD CROSS-CHECK (option a) — ridge reward model, fitted on TRAIN")
    print("-" * 96)
    Xtr = X[is_train]
    ytr = net[is_train][:, base_exit]
    lam = 10.0
    A = Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1])
    theta = np.linalg.solve(A, Xtr.T @ ytr)
    pred = X @ theta
    ss_res = float(((net[is_test][:, base_exit] - pred[is_test]) ** 2).sum())
    ss_tot = float(((net[is_test][:, base_exit] - net[is_test][:, base_exit].mean()) ** 2).sum())
    print(f"    out-of-sample R^2 of the reward model on TEST (hold 4h): {1 - ss_res / ss_tot:+.4f}")
    dm_rank, sim_rank, labels = [], [], []
    for er in enters:
        m = er.mask(c) & is_test
        if m.sum() < args.min_n:
            continue
        dm_rank.append(float(pred[m].mean()))
        sim_rank.append(float(net[m][:, base_exit].mean()))
        labels.append(er.label)
    if len(dm_rank) > 2:
        from scipy.stats import spearmanr

        rho, p = spearmanr(dm_rank, sim_rank)
        print(f"    Spearman(direct-method rank, simulator rank) over {len(dm_rank)} entry")
        print(f"    predicates on TEST: rho = {rho:+.3f} (p = {p:.2g})")
        dm_best = labels[int(np.argmax(dm_rank))]
        sim_best = labels[int(np.argmax(sim_rank))]
        print(f"      direct method's favourite: {dm_best}")
        print(f"      simulator's favourite:     {sim_best}")
        if p < 0.05:
            print("      The two methods AGREE on the ordering. That does not validate either — a")
            print("      shared bias produces agreement too — but it does say the ordering is")
            print("      reproducible from features alone, i.e. path detail is not doing the work.")
        else:
            print("      The two methods DISAGREE (rho indistinguishable from 0). This is the")
            print("      diagnostic the design was built to surface: an ordering that a reward")
            print("      model fitted on the same features cannot reproduce is an ordering made")
            print("      of noise. It agrees with the trials accounting, which says the same")
            print("      thing from the other direction.")

    # ---------------------------------------------------------------- the two controls
    if not args.skip_worlds:
        print("\n" + "-" * 96)
        print("CONTROLS (§3.12 — BOTH, because a zero-control alone certifies nothing)")
        print("-" * 96)
        print("\n  KNOWN-ZERO WORLD — reported above as the permutation floor. The bandits get")
        print("  their own zero control there too: the shuffled-context column.")
        Rz = np.zeros((len(ctrain), len(arm_rules)))
        nz = zero_world(net_train, ctrain.t0, rng)
        for k, e in enumerate(arm_exit):
            if e >= 0:
                Rz[:, k] = nz[:, e]
        rz_ucb = run_bandit("linucb", X[is_train], Rz, args.seed, alpha=0.50)
        print(f"    LinUCB on a known-zero world: cum {rz_ucb['cum']:.2f} over {len(ctrain):,} rounds,"
              f" best fixed arm {Rz.sum(axis=0).max():.2f}")
        print("    -> a learner that shows a win HERE is reading the permutation, not the market.")

        # (i) the GRID must recover an effect planted on one of its own axes.
        ne_g, _bit_g = effect_world(net_train, ctrain, 0.08, carrier="mcap")
        rows_e = grid_search(ctrain, ne_g, enters, exits, args.min_n)
        rows_e.sort(key=lambda r: -r["mean"])
        top20 = rows_e[:20]
        hit = sum(1 for r in top20 if enters[r["enter"]].mcap_min >= 1e5)
        base_share = sum(1 for e in enters if e.mcap_min >= 1e5) / len(enters)
        print("\n  KNOWN-EFFECT WORLD (i) — +8.00% planted on market cap >= $100k, which IS a")
        print("  grid axis, so the search is structurally capable of finding it")
        print(f"    grid's best mean: {pct(rows_e[0]['mean'])} (real world: {pct(rows_tr[0]['mean'])})")
        print(f"    best cell: {rows_e[0]['label']}")
        print(f"    top-20 cells carrying the mc>=100000 predicate: {hit}/20"
              f"  (chance: {base_share * 20:.1f}/20)")
        rec = "RECOVERED" if hit >= 15 else "FAILED TO RECOVER"
        print(f"    -> the grid {rec} a planted effect of the size we are hunting.")

        # (ii) the BANDIT must recover an effect planted on a context feature.
        ne_b, bit_b = effect_world(net_train, ctrain, 0.08, carrier="parity")
        Re = np.zeros((len(ctrain), len(arm_rules)))
        for k, e in enumerate(arm_exit):
            if e >= 0:
                Re[:, k] = ne_b[:, e]
        Xe = np.column_stack([X[is_train], bit_b.astype(np.float64)])
        res_e = run_bandit("linucb", Xe, Re, args.seed, alpha=0.50)
        on = float(Re[np.arange(len(ctrain)), res_e["chosen"]][bit_b].mean())
        off = float(Re[np.arange(len(ctrain)), res_e["chosen"]][~bit_b].mean())
        print("\n  KNOWN-EFFECT WORLD (ii) — +8.00% planted on reply_count parity, an arbitrary")
        print("  bit handed to the learner as a context feature")
        print(f"    LinUCB mean reward: {pct(on)} on carrier entries vs {pct(off)} off-carrier")
        print(f"    LinUCB skip rate:   {float((res_e['chosen'][bit_b] == 0).mean()) * 100:.0f}%"
              f" on carrier vs {float((res_e['chosen'][~bit_b] == 0).mean()) * 100:.0f}% off-carrier")
        found = (res_e["chosen"][bit_b] == 0).mean() < (res_e["chosen"][~bit_b] == 0).mean()
        sep = "SEPARATES" if found else "FAILS TO SEPARATE"
        print(f"    -> LinUCB {sep} the carrier: it enters where the effect is and skips where it")
        print("       is not. Without this the earlier null would be an untested instrument, not")
        print("       a finding (§3.12).")

    # ---------------------------------------------------------------- long horizon
    print("\n" + "-" * 96)
    print(f"LONG-HORIZON EXTENSION — {H_LONG / 3600:.0f}h holds on the cohort that can reach them")
    print("-" * 96)
    exits_l = [*exit_grid(H_LONG), ExitRule("hold_4h", "hold", H_MAX), ExitRule("hold_6h", "hold", 21600.0)]
    cl = build_cohort(entries, nb, H_LONG, tape_end)
    gl, rl, _hl = resolve_paths(cl, paths, exits_l, tape_end, last_seen)
    netl = net_returns(gl, rl, cl.friction, PRIMARY_HAIRCUT)
    li = {r.name: i for i, r in enumerate(exits_l)}
    print(f"    cohort: {len(cl):,} entries ({len(set(cl.mint)):,} mints) from the first"
          f" {(tape_end - H_LONG - tape_start) / 3600:.1f} h of tape.")
    print("    NO temporal split is possible on a 2 h entry window; this is a LEAD, not a finding.")
    bmask = EnterRule(0.50, "any", 0.0, 0.0).mask(cl)
    idx = np.flatnonzero(bmask)
    lrows = []
    for name in ("hold_30m", "hold_1h", "hold_2h", "hold_4h", "hold_6h", "hold_8h", "trail_25", "tp12_sl30"):
        if name not in li:
            continue
        r = summarise_policy(
            netl[idx, li[name]], [cl.mint[i] for i in idx], f"dd<0.50 | {name}", rl[idx, li[name]]
        )
        r["be"] = breakeven_haircut(gl, rl, cl.friction, idx, li[name])
        lrows.append(r)
    print_table(lrows, "hold length vs NET return, shallow-drawdown entries only", live=True)
    print(f"\n    {'rule':<24}{'breakeven haircut':>20}")
    for r in lrows:
        be = r["be"]
        s = "never" if be < 0 else ("always" if not math.isfinite(be) else f"{be:.1%}")
        print(f"    {r['label'].split('| ')[-1]:<24}{s:>20}")

    print("\n" + "=" * 96)
    print(f"done in {time.time() - t_start:.1f}s. Every number above is NET of round-trip friction")
    print(f"(median {np.median(c.friction) * 100:.2f}%) at B* sizing, with a {PRIMARY_HAIRCUT:.0%}"
          " haircut on stale-price mark-outs.")
    print("=" * 96)


if __name__ == "__main__":
    main()
