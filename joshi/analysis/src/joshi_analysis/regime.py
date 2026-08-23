"""Regime tag: a typed description of what a coin's price has been doing.

Built on Definition P2 (signature volatility) from
``docs/microstructure/trades_quotes_prices/FORMAL_MODEL.md``::

    V(tau)       = E[(p_{t+tau} - p_t)^2]          variogram
    sigma^2(tau) = V(tau) / (tau * pbar^2)         signature volatility

and on the corpus finding (``analysis/corpus/signature_regimes.py``) that the ratio
``sigma^2(32) / sigma^2(1)`` spreads widely and continuously across graduated-pool series:
roughly a quarter mean-revert, a third diffuse, four-tenths trend. The tag names where a series
sits on that axis -- a DESCRIPTION of its recent past, never a prediction.

A tag is never a bare label. It carries the slope, the lag range it was measured over, the sample
size, the wall span, and a bootstrap confidence interval -- or an explicit ``indeterminate`` with
the reason. The label boundaries (below 0.75 reverting, above 1.33 trending) are the bands
``signature_regimes.py`` used; a label is only issued when the whole confidence interval sits
inside one band.

Two clocks, because they genuinely disagree on gap-compressed data (see
:mod:`joshi_analysis.signature`): the event clock counts traded events, the wall clock counts
elapsed seconds with silence included. Wall-clock measurement here first samples the last
observed price per second, then pairs every two samples whose gap lies within 25% of the target
lag. Per-second sampling bounds the pairs an endpoint can join to by the tolerance-window width,
so a thousand-trade burst second contributes one sample rather than a million pairs. That
estimator choice is part of the definition, and ``analysis/corpus/regime_stability.py`` computes
the identical estimator in SQL.

Confidence intervals come from a moving-block bootstrap (blocks of consecutive events, long
relative to the largest lag, pairs never crossing block joins), which respects the serial
dependence the statistic itself measures. Percentile interval, 90% by default.

Prices arrive as floats: the corpus stores ``price_sol_per_token`` as a float64 ratio of two
observed integers, and the ratio statistic here is scale-free.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

EVENT_LAGS = (1, 2, 4, 8, 16, 32)
WALL_LAGS_S = (1, 2, 4, 8, 16, 32)
WALL_TOLERANCE = 0.25
REVERT_BELOW = 0.75
TREND_ABOVE = 1.33
MIN_EVENTS = 400
DEFAULT_BOOT = 200
CI_LEVEL = 0.90
MIN_VALID_REPLICATES = 0.8

LagPoint = tuple[int, float | None, int]  # (lag, sigma^2 or None when unmeasured, pair count)


@dataclass(frozen=True)
class RegimeTag:
    """The full descriptor. ``label`` alone is never the deliverable."""

    clock: str  # "event" | "wall"
    label: str  # "reverting" | "diffusive" | "trending" | "indeterminate"
    reason: str | None  # why indeterminate; None when a label was issued
    slope: float | None  # sigma^2(lag_high) / sigma^2(lag_low), None when unmeasurable
    ci_low: float | None
    ci_high: float | None
    ci_level: float
    lag_low: int
    lag_high: int
    lag_unit: str  # "events" | "seconds"
    n_events: int
    span_seconds: int
    n_pairs_low: int  # pairs behind sigma^2(lag_low)
    n_pairs_high: int  # pairs behind sigma^2(lag_high)
    n_boot: int
    price_kind: str
    curve: tuple[LagPoint, ...]

    def render(self) -> str:
        """One honest line: label with every denominator it stands on."""
        if self.slope is None:
            body = f"slope unmeasured ({self.reason})"
        else:
            ci = (
                f" ci90=[{self.ci_low:.2f},{self.ci_high:.2f}]"
                if self.ci_low is not None and self.ci_high is not None
                else ""
            )
            why = f" ({self.reason})" if self.reason else ""
            body = f"slope={self.slope:.2f}{ci}{why}"
        return (
            f"{self.clock}:{self.label} {body} lags {self.lag_low}..{self.lag_high} "
            f"{self.lag_unit}, n={self.n_events} events / {self.span_seconds}s span, "
            f"pairs {self.n_pairs_low}/{self.n_pairs_high}, {self.price_kind}"
        )


def band(slope: float) -> str:
    if slope < REVERT_BELOW:
        return "reverting"
    if slope >= TREND_ABOVE:
        return "trending"
    return "diffusive"


def event_curve(prices: list[float], lags: tuple[int, ...] = EVENT_LAGS) -> list[LagPoint]:
    """sigma^2 per event lag. A lag not covered by the series yields None, not zero."""
    if not prices:
        return [(lag, None, 0) for lag in lags]
    mean_price = sum(prices) / len(prices)
    if mean_price <= 0:
        return [(lag, None, 0) for lag in lags]
    out: list[LagPoint] = []
    for lag in lags:
        if lag >= len(prices):
            out.append((lag, None, 0))
            continue
        total = 0.0
        for i in range(len(prices) - lag):
            d = prices[i + lag] - prices[i]
            total += d * d
        pairs = len(prices) - lag
        out.append((lag, total / pairs / (lag * mean_price * mean_price), pairs))
    return out


def wall_samples(times_s: list[int], prices: list[float]) -> tuple[list[int], list[float]]:
    """Collapse an event stream to the last observed price per second, in time order."""
    sec_times: list[int] = []
    sec_prices: list[float] = []
    for t, p in zip(times_s, prices, strict=True):
        if sec_times and t == sec_times[-1]:
            sec_prices[-1] = p
        else:
            sec_times.append(t)
            sec_prices.append(p)
    return sec_times, sec_prices


def wall_curve(
    sec_times: list[int],
    sec_prices: list[float],
    lags_s: tuple[int, ...] = WALL_LAGS_S,
    tolerance: float = WALL_TOLERANCE,
) -> list[LagPoint]:
    """sigma^2 per wall lag over per-second samples.

    Every ordered pair of samples whose gap lies within ``tolerance`` of the target lag
    contributes, normalised by the target lag. Per-second sampling bounds the pairs per endpoint
    by the tolerance-window width, so burst seconds cannot dominate the estimate.
    """
    if not sec_prices:
        return [(lag, None, 0) for lag in lags_s]
    mean_price = sum(sec_prices) / len(sec_prices)
    if mean_price <= 0:
        return [(lag, None, 0) for lag in lags_s]
    out: list[LagPoint] = []
    for lag in lags_s:
        total, pairs = _wall_pairs(sec_times, sec_prices, lag, tolerance)
        if pairs == 0:
            out.append((lag, None, 0))
        else:
            out.append((lag, total / pairs / (lag * mean_price * mean_price), pairs))
    return out


def _wall_pairs(
    sec_times: list[int], sec_prices: list[float], lag: int, tolerance: float
) -> tuple[float, int]:
    """Sum of squared diffs and pair count over all pairs with gap within tolerance of lag."""
    low = lag * (1 - tolerance)
    high = lag * (1 + tolerance)
    total = 0.0
    pairs = 0
    start = 0
    n = len(sec_times)
    for i in range(n):
        at = sec_times[i]
        while start < n and sec_times[start] - at < low:
            start += 1
        probe = max(start, i + 1)
        while probe < n and sec_times[probe] - at <= high:
            d = sec_prices[probe] - sec_prices[i]
            total += d * d
            pairs += 1
            probe += 1
    return total, pairs


def slope_from_curve(curve: list[LagPoint], lag_low: int, lag_high: int) -> float | None:
    by_lag = {lag: sigma for lag, sigma, _ in curve}
    lo, hi = by_lag.get(lag_low), by_lag.get(lag_high)
    if lo is None or hi is None or lo <= 0:
        return None
    return hi / lo


def _block_starts(n: int, block: int, rng: random.Random) -> list[int]:
    k = max(1, math.ceil(n / block))
    return [rng.randrange(0, n - block + 1) for _ in range(k)]


def _bootstrap_slopes_event(
    prices: list[float],
    lag_low: int,
    lag_high: int,
    n_boot: int,
    rng: random.Random,
) -> list[float]:
    n = len(prices)
    block = max(4 * lag_high, 64)
    if n < block:
        return []
    slopes: list[float] = []
    for _ in range(n_boot):
        starts = _block_starts(n, block, rng)
        total_lo = total_hi = 0.0
        pairs_lo = pairs_hi = 0
        price_sum = 0.0
        for s in starts:
            seg = prices[s : s + block]
            price_sum += sum(seg)
            for i in range(block - lag_low):
                d = seg[i + lag_low] - seg[i]
                total_lo += d * d
            pairs_lo += block - lag_low
            for i in range(block - lag_high):
                d = seg[i + lag_high] - seg[i]
                total_hi += d * d
            pairs_hi += block - lag_high
        if pairs_lo == 0 or pairs_hi == 0 or total_lo <= 0:
            continue
        # pbar cancels in the ratio; only the lag normalisation survives.
        slopes.append((total_hi / pairs_hi / lag_high) / (total_lo / pairs_lo / lag_low))
    return slopes


def _bootstrap_slopes_wall(
    sec_times: list[int],
    sec_prices: list[float],
    lag_low: int,
    lag_high: int,
    tolerance: float,
    n_boot: int,
    rng: random.Random,
) -> list[float]:
    n = len(sec_prices)
    block = max(8 * lag_high, 64)  # samples per block; gaps mean seconds spanned >= samples
    if n < block:
        return []
    slopes: list[float] = []
    for _ in range(n_boot):
        starts = _block_starts(n, block, rng)
        agg = {lag_low: [0.0, 0], lag_high: [0.0, 0]}
        for s in starts:
            ts = sec_times[s : s + block]
            ps = sec_prices[s : s + block]
            for lag, cell in agg.items():
                total, pairs = _wall_pairs(ts, ps, lag, tolerance)
                cell[0] += total
                cell[1] += pairs
        (tl, pl), (th, ph) = agg[lag_low], agg[lag_high]
        if pl == 0 or ph == 0 or tl <= 0:
            continue
        slopes.append((th / ph / lag_high) / (tl / pl / lag_low))
    return slopes


def _percentile_ci(slopes: list[float], level: float) -> tuple[float, float]:
    ordered = sorted(slopes)
    alpha = (1 - level) / 2
    lo_idx = math.floor(alpha * (len(ordered) - 1))
    hi_idx = math.ceil((1 - alpha) * (len(ordered) - 1))
    return ordered[lo_idx], ordered[hi_idx]


def regime_tag(
    times_s: list[int],
    prices: list[float],
    clock: str = "event",
    n_boot: int = DEFAULT_BOOT,
    seed: int = 0,
    min_events: int = MIN_EVENTS,
    price_kind: str = "amm_pool_vault_fill",
) -> RegimeTag:
    """Tag one series on one clock. ``times_s``/``prices`` must already be in event order."""
    if clock not in ("event", "wall"):
        raise ValueError(f"unknown clock {clock!r}")
    if len(times_s) != len(prices):
        raise ValueError("times and prices must be the same length")
    n_events = len(prices)
    span = times_s[-1] - times_s[0] if times_s else 0

    if clock == "event":
        lags, lag_unit = EVENT_LAGS, "events"
        curve = event_curve(prices, lags)
    else:
        lags, lag_unit = WALL_LAGS_S, "seconds"
        sec_t, sec_p = wall_samples(times_s, prices)
        curve = wall_curve(sec_t, sec_p, lags)
    lag_low, lag_high = lags[0], lags[-1]
    by_lag = {lag: (sigma, pairs) for lag, sigma, pairs in curve}
    n_pairs_low, n_pairs_high = by_lag[lag_low][1], by_lag[lag_high][1]
    slope = slope_from_curve(curve, lag_low, lag_high)

    def tag(label: str, reason: str | None, ci: tuple[float, float] | None) -> RegimeTag:
        return RegimeTag(
            clock=clock,
            label=label,
            reason=reason,
            slope=slope,
            ci_low=ci[0] if ci else None,
            ci_high=ci[1] if ci else None,
            ci_level=CI_LEVEL,
            lag_low=lag_low,
            lag_high=lag_high,
            lag_unit=lag_unit,
            n_events=n_events,
            span_seconds=span,
            n_pairs_low=n_pairs_low,
            n_pairs_high=n_pairs_high,
            n_boot=n_boot,
            price_kind=price_kind,
            curve=tuple(curve),
        )

    if n_events < min_events:
        return tag("indeterminate", "insufficient_events", None)
    if slope is None:
        return tag("indeterminate", "no_measure_at_lag", None)

    rng = random.Random(seed)
    if clock == "event":
        slopes = _bootstrap_slopes_event(prices, lag_low, lag_high, n_boot, rng)
    else:
        slopes = _bootstrap_slopes_wall(
            sec_t, sec_p, lag_low, lag_high, WALL_TOLERANCE, n_boot, rng
        )
    if len(slopes) < MIN_VALID_REPLICATES * n_boot:
        return tag("indeterminate", "bootstrap_degenerate", None)
    ci = _percentile_ci(slopes, CI_LEVEL)
    bands = {band(ci[0]), band(ci[1]), band(slope)}
    if len(bands) > 1:
        return tag("indeterminate", "ci_spans_boundary", ci)
    return tag(band(slope), None, ci)
