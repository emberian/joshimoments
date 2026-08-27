"""Pure compute for the registered estimands. No I/O, no network; Decimal outcomes.

Everything here implements REGISTRATION.md §3 exactly: per horizon, P(up) under both rule
variants (ties → Up, exact ``Decimal`` comparison), the rule-disagreement rate, the log-return
distribution, and σ²(τ) via the EXISTING ``joshi_analysis.signature`` instrument, unmodified.
The fee floor from the map (§4 there) is attached to every base-rate block so nothing is ever
quoted gross.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from joshi_analysis import signature

from .reference import GRANULARITY_S, REFERENCE_LABEL, Candle

FEE_FLOOR = {
    "explicitMidpointPerDollar": 0.0175,
    "workingFloorPerDollar": [0.02, 0.035],
    "statement": (
        "explicit fee ~= 0.070*p*(1-p) (~1.75% of the $1 payout at p=0.5); working floor with "
        "spread + overround ~= 2-3.5% — no P(up) deviation below this is an edge, and nothing "
        "here is a live-executable claim in any case"
    ),
}
RETURN_QUANTILES = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
NEAR_TIE_ABS_SIMPLE_RETURN = 0.001  # 10 bps


@dataclass(frozen=True)
class HorizonStudy:
    horizon_s: int
    grid_windows: int
    excluded_missing_boundary: int
    excluded_missing_interior: int  # TWAP outcome only
    n_endpoint: int
    up_endpoint: int
    n_twap: int
    up_twap: int
    disagreements: int  # over the n_twap windows (both outcomes defined)
    log_returns: tuple[float, ...]
    near_tie_count: int  # |simple return| < NEAR_TIE_ABS_SIMPLE_RETURN, over n_endpoint


def point_price(candles: dict[int, Candle], t: int) -> Decimal | None:
    """The registered point-price at grid instant t: the OPEN of the minute candle stamped t."""
    c = candles.get(t)
    return None if c is None else c.open


def window_twap(candles: dict[int, Candle], t: int, horizon_s: int) -> Decimal | None:
    """Mean of the 1-minute closes in [t, t+horizon); None if any interior minute is absent."""
    closes = []
    for minute in range(t, t + horizon_s, GRANULARITY_S):
        c = candles.get(minute)
        if c is None:
            return None
        closes.append(c.close)
    return sum(closes) / Decimal(len(closes))


def evaluate_horizon(candles: dict[int, Candle], horizon_s: int) -> HorizonStudy:
    """All registered window outcomes for one horizon, anchored at T ≡ 0 (mod horizon)."""
    if not candles:
        return HorizonStudy(horizon_s, 0, 0, 0, 0, 0, 0, 0, 0, (), 0)
    lo, hi = min(candles), max(candles)
    first = ((lo + horizon_s - 1) // horizon_s) * horizon_s
    grid = excl_boundary = excl_interior = 0
    n_endpoint = up_endpoint = n_twap = up_twap = disagreements = near_tie = 0
    log_returns: list[float] = []
    for t in range(first, hi - horizon_s + 1, horizon_s):
        grid += 1
        p_open = point_price(candles, t)
        p_close = point_price(candles, t + horizon_s)
        if p_open is None or p_close is None or p_open == 0:
            excl_boundary += 1
            continue
        n_endpoint += 1
        endpoint_up = p_close >= p_open  # ties → Up, per the rule
        if endpoint_up:
            up_endpoint += 1
        simple = float((p_close - p_open) / p_open)
        log_returns.append(math.log(float(p_close) / float(p_open)))
        if abs(simple) < NEAR_TIE_ABS_SIMPLE_RETURN:
            near_tie += 1
        twap = window_twap(candles, t, horizon_s)
        if twap is None:
            excl_interior += 1
            continue
        n_twap += 1
        twap_up = twap >= p_open  # ties → Up
        if twap_up:
            up_twap += 1
        if twap_up != endpoint_up:
            disagreements += 1
    return HorizonStudy(
        horizon_s=horizon_s,
        grid_windows=grid,
        excluded_missing_boundary=excl_boundary,
        excluded_missing_interior=excl_interior,
        n_endpoint=n_endpoint,
        up_endpoint=up_endpoint,
        n_twap=n_twap,
        up_twap=up_twap,
        disagreements=disagreements,
        log_returns=tuple(log_returns),
        near_tie_count=near_tie,
    )


def wilson_95(k: int, n: int) -> tuple[float, float] | None:
    """Wilson score 95% interval for a binomial proportion; None when n == 0."""
    if n == 0:
        return None
    z = 1.959963984540054
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return center - half, center + half


def quantiles(values: tuple[float, ...], qs: tuple[float, ...] = RETURN_QUANTILES) -> dict:
    """Linear-interpolation quantiles of a sample; empty in, empty out."""
    if not values:
        return {}
    ordered = sorted(values)
    out = {}
    for q in qs:
        pos = q * (len(ordered) - 1)
        i = int(pos)
        frac = pos - i
        if i + 1 >= len(ordered):
            val = ordered[i]
        else:
            val = ordered[i] * (1 - frac) + ordered[i + 1] * frac
        out[f"p{int(q * 100):02d}"] = val
    return out


def rate_block(k: int, n: int) -> dict:
    """One base-rate line: rate, Wilson interval, denominator, reference label, fee floor."""
    ci = wilson_95(k, n)
    return {
        "up": k,
        "n": n,
        "rate": (k / n) if n else None,
        "wilson95": list(ci) if ci else None,
        "reference": REFERENCE_LABEL,
        "feeFloor": FEE_FLOOR,
    }


def horizon_report(study: HorizonStudy) -> dict:
    """The registered per-horizon result block, JSON-ready."""
    lr = study.log_returns
    return {
        "horizonSeconds": study.horizon_s,
        "gridWindows": study.grid_windows,
        "excluded": {
            "missingBoundary": study.excluded_missing_boundary,
            "missingInteriorTwapOnly": study.excluded_missing_interior,
        },
        "pUpEndpointRule": rate_block(study.up_endpoint, study.n_endpoint),
        "pUpTwapRule": rate_block(study.up_twap, study.n_twap),
        "ruleDisagreement": {
            "count": study.disagreements,
            "n": study.n_twap,
            "rate": (study.disagreements / study.n_twap) if study.n_twap else None,
        },
        "logReturn": {
            "n": len(lr),
            "meanAbs": (sum(abs(x) for x in lr) / len(lr)) if lr else None,
            "quantiles": quantiles(lr),
            "nearTieUnder10bps": {
                "count": study.near_tie_count,
                "n": study.n_endpoint,
                "rate": (study.near_tie_count / study.n_endpoint) if study.n_endpoint else None,
            },
        },
    }


def signature_report(candles: dict[int, Candle]) -> dict:
    """σ²(τ) from the existing instrument on (timestamp_ms, close) bars, both clocks verbatim."""
    bars = [(t * 1000, candles[t].close) for t in sorted(candles)]
    if len(bars) < 2:
        return {"bars": len(bars), "note": "insufficient bars"}
    wall = [
        {
            "lagSeconds": lag_ms // 1000,
            "sigma2": None if sigma is None else float(sigma),
            "pairs": pairs,
        }
        for lag_ms, _, sigma, pairs in signature.signature_wall(bars)
    ]
    event = [
        {
            "lagBars": lag,
            "lagSecondsUniform": lag * GRANULARITY_S,
            "sigma2": None if sigma is None else float(sigma),
            "pairs": pairs,
        }
        for lag, _, sigma, pairs in signature.signature_event(bars)
    ]
    return {
        "bars": len(bars),
        "instrument": "joshi_analysis.signature (reused unmodified)",
        "reading": "falling sigma^2(tau) => net mean reversion (chop); rising => trend",
        "wallTime": wall,
        "eventTime": event,
    }
