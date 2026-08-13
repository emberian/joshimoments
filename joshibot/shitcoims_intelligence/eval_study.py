"""Paper evaluation primitives. Advisory only. No signing, no MarketFabric import.

Roommate ``crypto_intel.analysis`` is decent slop with landmines: we reimplement
lead/lag + a no-lookahead event study here, with the permutation test that makes
a max-over-lags correlation honest. Tiny n must stay visible in the report.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .sieve import VERDICT_PASS, VERDICT_SKIP, VERDICT_VETO, VERDICT_WATCH_EXIT

EXECUTION_EFFECT = "none"


def pearson(left: Sequence[float], right: Sequence[float]) -> float:
    n = min(len(left), len(right))
    if n < 3:
        return 0.0
    xs, ys = list(left[:n]), list(right[:n])
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def lead_lag(
    predictor: Sequence[float], target: Sequence[float], *, max_lag: int = 6
) -> dict[str, Any]:
    """k>0 => predictor leads target. Does not claim significance."""

    n = min(len(predictor), len(target))
    xs, ys = list(predictor[:n]), list(target[:n])
    curve: list[tuple[int, float]] = []
    for lag in range(-max_lag, max_lag + 1):
        a: list[float] = []
        b: list[float] = []
        for index in range(n):
            other = index + lag
            if 0 <= other < n:
                a.append(xs[index])
                b.append(ys[other])
        if len(a) > 3:
            curve.append((lag, pearson(a, b)))
    if not curve:
        return {
            "curve": [],
            "best_lag": 0,
            "best_corr": 0.0,
            "n": n,
            "execution_effect": EXECUTION_EFFECT,
        }
    best = max(curve, key=lambda item: abs(item[1]))
    return {
        "curve": curve,
        "best_lag": best[0],
        "best_corr": best[1],
        "n": n,
        "execution_effect": EXECUTION_EFFECT,
    }


def leadlag_p_value(
    predictor: Sequence[float], target: Sequence[float], *, max_lag: int = 6
) -> dict[str, Any]:
    """Circular-shift null for the max |corr| (accounts for lag-shopping)."""

    observed = lead_lag(predictor, target, max_lag=max_lag)
    xs, ys = list(predictor), list(target)
    n = min(len(xs), len(ys))
    stat = abs(float(observed["best_corr"]))
    if n < 2 * max_lag + 4:
        return {**observed, "p_value": 1.0, "n_surrogates": 0}
    beat = 0
    for shift in range(1, n):
        rotated = xs[shift:] + xs[:shift]
        if abs(float(lead_lag(rotated, ys, max_lag=max_lag)["best_corr"])) >= stat:
            beat += 1
    return {**observed, "p_value": (beat + 1) / n, "n_surrogates": n - 1}


def event_study(
    event_ts: Sequence[int],
    bars: Sequence[Mapping[str, Any]],
    *,
    horizon: int = 6,
) -> dict[str, Any]:
    """Forward close return after each event. No lookahead into pre-event bars."""

    if not bars or not event_ts:
        return {"n": 0, "mean_fwd": None, "hits": 0, "execution_effect": EXECUTION_EFFECT}
    stamps = [int(bar["ts"]) for bar in bars]
    closes = [float(bar["close"]) if "close" in bar else float(bar["c"]) for bar in bars]
    forwards: list[float] = []
    hits = 0
    for stamp in event_ts:
        index = _first_at_or_after(stamps, int(stamp))
        later = index + horizon
        if index is None or later >= len(closes) or closes[index] <= 0:
            continue
        change = closes[later] / closes[index] - 1.0
        forwards.append(change)
        if change > 0:
            hits += 1
    if not forwards:
        return {"n": 0, "mean_fwd": None, "hits": 0, "execution_effect": EXECUTION_EFFECT}
    return {
        "n": len(forwards),
        "mean_fwd": sum(forwards) / len(forwards),
        "hits": hits,
        "hit_rate": hits / len(forwards),
        "execution_effect": EXECUTION_EFFECT,
    }


def honest_sample_caveat(n: int, *, min_n: int = 30) -> str:
    if n <= 0:
        return "no paired observations; this is not an evaluation"
    if n < min_n:
        return f"n={n} is below {min_n}; treat every number as a sketch, not a result"
    return f"n={n}"


def verdict_histogram(cards: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        VERDICT_VETO: 0,
        VERDICT_WATCH_EXIT: 0,
        VERDICT_PASS: 0,
        VERDICT_SKIP: 0,
    }
    for card in cards:
        label = str(card.get("verdict") or "")
        if label in counts:
            counts[label] += 1
    return counts


def _first_at_or_after(stamps: Sequence[int], stamp: int) -> int | None:
    lo, hi = 0, len(stamps)
    while lo < hi:
        mid = (lo + hi) // 2
        if stamps[mid] < stamp:
            lo = mid + 1
        else:
            hi = mid
    if lo >= len(stamps):
        return None
    return lo
