"""Declared online change-point: two-sided CUSUM on running-standardized returns.

The registration declares CUSUM rather than BOCPD: fewer moving parts, exactly causal, and
its statistic doubles as both a feature and the policy file's exit alarm. Standardization is
running (Welford), so the statistic at index ``i`` depends on returns ``<= i`` only.

    z_i     = (r_i - running_mean) / running_std
    S+_i    = max(0, S+_{i-1} + z_i - k)        k = CUSUM_DRIFT
    S-_i    = max(0, S-_{i-1} - z_i - k)
    alarm   = S > h                             h = CUSUM_THRESHOLD

After an alarm the statistic resets to 0 (declared), so alarms mark shifts rather than
saturating.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .vocabulary import CUSUM_DRIFT, CUSUM_THRESHOLD

_MIN_SAMPLES = 10


@dataclass(frozen=True)
class CusumPoint:
    stat_up: float
    stat_down: float
    alarm_up: bool
    alarm_down: bool


def cusum_trace(returns: list[float]) -> list[CusumPoint]:
    """The full causal trace, index-aligned with ``returns``."""
    points: list[CusumPoint] = []
    mean = 0.0
    m2 = 0.0
    s_up = 0.0
    s_down = 0.0
    for seen, r in enumerate(returns):  # ``seen`` = samples already folded into the moments
        if seen >= _MIN_SAMPLES and seen > 1:
            std = math.sqrt(m2 / (seen - 1))
            z = (r - mean) / std if std > 0 else 0.0
        else:
            z = 0.0
        s_up = max(0.0, s_up + z - CUSUM_DRIFT)
        s_down = max(0.0, s_down - z - CUSUM_DRIFT)
        alarm_up = s_up > CUSUM_THRESHOLD
        alarm_down = s_down > CUSUM_THRESHOLD
        points.append(CusumPoint(s_up, s_down, alarm_up, alarm_down))
        if alarm_up:
            s_up = 0.0
        if alarm_down:
            s_down = 0.0
        delta = r - mean
        mean += delta / (seen + 1)
        m2 += delta * (r - mean)
    return points
