"""The declared feature vector every model in the zoo shares.

Everything here is causal: the vector at event ``i`` is a function of events ``<= i`` only,
and the tests enforce that by construction (a prefix of the tape yields identical vectors).
Events inside the warmup (`WARMUP_EVENTS`) get no vector and are excluded from fitting and
judging. Floats are fine here — features feed statistical models; the exact ``Decimal``
arithmetic lives where money-mapping claims are made (labels).
"""

from __future__ import annotations

import math

from .changepoint import cusum_trace
from .tape import TapeEvent
from .vocabulary import EWMA_HALF_LIFE_EVENTS, FEATURE_WINDOW, WARMUP_EVENTS

FEATURE_NAMES: tuple[str, ...] = (
    "r1",
    "r4",
    "r16",
    "r32",
    "quote_imbalance_w32",
    "buy_fraction_w32",
    "trader_concentration_w32",
    "log_runup_from_w32_min",
    "log_drawdown_from_w32_max",
    "levy_area_w32",
    "ewma_intensity_log_ratio",
    "ewma_intensity_log_total",
    "log10_mean_dt_w32",
    "cusum_up",
    "cusum_down",
)

FEATURE_DEFINITIONS: dict[str, str] = {
    "r1": "log(p_i / p_{i-1})",
    "r4": "log(p_i / p_{i-4})",
    "r16": "log(p_i / p_{i-16})",
    "r32": "log(p_i / p_{i-32})",
    "quote_imbalance_w32": "sum(signed quote) / sum(|quote|) over the last 32 events",
    "buy_fraction_w32": "buy count / 32 over the last 32 events",
    "trader_concentration_w32": "unique traders / 32 over the last 32 events",
    "log_runup_from_w32_min": "log(p_i / min(p) over the last 32 events)",
    "log_drawdown_from_w32_max": "log(max(p) over the last 32 events / p_i)",
    "levy_area_w32": (
        "depth-2 path-signature Levy area of the piecewise-linear path (t normalized to "
        "[0,1], log p centered at the window start) over the last 32 events"
    ),
    "ewma_intensity_log_ratio": (
        "log((decayed buy count + 0.5) / (decayed sell count + 0.5)); event-clock exponential "
        "decay, half-life 8 events, over the whole causal history"
    ),
    "ewma_intensity_log_total": "log(decayed buy count + decayed sell count + 1); same decay",
    "log10_mean_dt_w32": (
        "log10(1 + (t_i - t_{i-32}) / 32) with t in seconds on the tape's declared clock "
        "(venue event time when present, else arrival wall time)"
    ),
    "cusum_up": "two-sided causal CUSUM up-statistic on running-standardized r1",
    "cusum_down": "two-sided causal CUSUM down-statistic on running-standardized r1",
}


def feature_matrix(events: list[TapeEvent]) -> tuple[list[int], list[list[float]]]:
    """Vectors for every event index >= WARMUP_EVENTS, in tape order.

    Returns ``(indices, vectors)`` with ``vectors[j]`` belonging to event
    ``events[indices[j]]``.
    """
    n = len(events)
    if n == 0:
        return [], []
    log_prices = [math.log(float(event.price)) for event in events]
    returns_1 = [0.0] + [log_prices[i] - log_prices[i - 1] for i in range(1, n)]
    cusum = cusum_trace(returns_1)
    decay = 2.0 ** (-1.0 / EWMA_HALF_LIFE_EVENTS)
    times = _clock_seconds(events)

    indices: list[int] = []
    vectors: list[list[float]] = []
    ewma_buy = 0.0
    ewma_sell = 0.0
    for i, event in enumerate(events):
        ewma_buy *= decay
        ewma_sell *= decay
        if event.side == "buy":
            ewma_buy += 1.0
        else:
            ewma_sell += 1.0
        if i < WARMUP_EVENTS:
            continue
        window = events[i - FEATURE_WINDOW + 1 : i + 1]
        window_logs = log_prices[i - FEATURE_WINDOW + 1 : i + 1]
        quote_abs = sum(abs(float(w.quote_signed)) for w in window)
        quote_net = sum(float(w.quote_signed) for w in window)
        vector = [
            log_prices[i] - log_prices[i - 1],
            log_prices[i] - log_prices[i - 4],
            log_prices[i] - log_prices[i - 16],
            log_prices[i] - log_prices[i - 32],
            quote_net / quote_abs if quote_abs > 0 else 0.0,
            sum(1 for w in window if w.side == "buy") / FEATURE_WINDOW,
            len({w.trader for w in window}) / FEATURE_WINDOW,
            log_prices[i] - min(window_logs),
            max(window_logs) - log_prices[i],
            _levy_area(window_logs),
            math.log((ewma_buy + 0.5) / (ewma_sell + 0.5)),
            math.log(ewma_buy + ewma_sell + 1.0),
            _log_mean_dt(times, i),
            cusum[i].stat_up,
            cusum[i].stat_down,
        ]
        indices.append(i)
        vectors.append(vector)
    return indices, vectors


def _clock_seconds(events: list[TapeEvent]) -> list[float | None]:
    out: list[float | None] = []
    for event in events:
        stamp = event.event_time_us if event.event_time_us is not None else event.arrival_wall_us
        out.append(stamp / 1_000_000 if stamp is not None else None)
    return out


def _log_mean_dt(times: list[float | None], i: int) -> float:
    t_now = times[i]
    t_then = times[i - FEATURE_WINDOW]
    if t_now is None or t_then is None or t_now < t_then:
        return 0.0
    return math.log10(1.0 + (t_now - t_then) / FEATURE_WINDOW)


def _levy_area(window_logs: list[float]) -> float:
    """Antisymmetric depth-2 signature term of the (time, centered log-price) path."""
    m = len(window_logs)
    if m < 2:
        return 0.0
    x0 = window_logs[0]
    area = 0.0
    for k in range(m - 1):
        t_k = k / (m - 1)
        dt = 1.0 / (m - 1)
        x_k = window_logs[k] - x0
        dx = window_logs[k + 1] - window_logs[k]
        # 0.5 * [(T_mid - T_0) dX - (X_mid - X_0) dT] summed over linear segments
        area += 0.5 * ((t_k + dt / 2.0) * dx - (x_k + dx / 2.0) * dt)
    return area
