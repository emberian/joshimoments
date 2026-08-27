"""Decision-time state, matched to the gated rule's mechanic, strictly causal.

Every component of the state at time t is a function of trades at or before t only. The
no-leakage property is tested literally: computing the state on the series truncated at t
must give the identical result. The "locked-in" quantity is what the elapsed path has
mathematically fixed about the settlement value — never anything after t.
"""

from __future__ import annotations

from dataclasses import dataclass

from .finesol import StepSeries
from .rules import start_ref

REMAINING_FRACTIONS = (0.8, 0.6, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05)
REGIME_LOOKBACK_S = 3600.0
REGIME_BAND_BPS = 50.0


@dataclass(frozen=True)
class DecisionState:
    t: float
    remaining_s: float
    remaining_fraction: float
    a1_bps: float  # elapsed-window TWAP vs the rule's start reference
    a2_bps: float  # raw price vs the same reference
    gap_bps: float  # a2 - a1: the mechanic Ember trades
    m_bps: float  # determination margin: p(t) vs the tie-leaving constant price
    d_bps: float  # PRIMARY AXIS (v1.1): freeze-now settlement margin vs the boundary
    vol_bps: float | None

    @property
    def current_side_up(self) -> bool:
        """The side the settlement sits on if price froze now (d = 0 -> Up, ties->Up)."""
        return self.d_bps >= 0.0


def _bps(value: float, ref: float) -> float:
    return (value - ref) / ref * 1e4


def decision_state(
    series: StepSeries, t_open: float, t_close: float, t: float, rule: str
) -> DecisionState | None:
    """The state at decision time t in (t_open, t_close); None when data-absent."""
    if not t_open < t < t_close:
        return None
    ref = start_ref(series, t_open, rule)
    p_t = series.price_at(t)
    elapsed_twap = series.twap(t_open, t)
    if ref is None or ref <= 0 or p_t is None or elapsed_twap is None:
        return None
    e = t - t_open
    r = t_close - t
    a1 = _bps(elapsed_twap, ref)
    a2 = _bps(p_t, ref)
    h = t_close - t_open
    if rule in ("a", "d"):
        m = a2 + (e / r) * a1
        d = (e * a1 + r * a2) / h  # freeze-now: settlement = (elapsed area + r*p_t)/H
    elif rule == "c":
        m = a2
        d = a2
    else:  # rule b: twap60(close) vs twap60(open)
        if r >= 60.0:
            m = a2  # nothing of twap60(close) is locked yet; distance to target
            d = a2  # freeze-now: after >=60s frozen, twap60(close) = p(t)
        else:
            locked = series.twap(t_close - 60.0, t)
            if locked is None:
                return None
            req = (60.0 * ref - (60.0 - r) * locked) / r
            m = _bps(p_t, ref) - _bps(req, ref)
            d = _bps(((60.0 - r) * locked + r * p_t) / 60.0, ref)
    return DecisionState(
        t=t,
        remaining_s=r,
        remaining_fraction=r / (t_close - t_open),
        a1_bps=a1,
        a2_bps=a2,
        gap_bps=a2 - a1,
        m_bps=m,
        d_bps=d,
        vol_bps=series.vol_bps(t),
    )


def decision_states(
    series: StepSeries, t_open: float, t_close: float, rule: str
) -> list[DecisionState]:
    """States at the registered remaining-fraction grid; absent ones are simply not emitted."""
    h = t_close - t_open
    out = []
    for frac in REMAINING_FRACTIONS:
        st = decision_state(series, t_open, t_close, t_close - frac * h, rule)
        if st is not None:
            out.append(st)
    return out


def regime(series: StepSeries, t_open: float) -> str | None:
    """Trailing-1h return bucket at the window start: down / flat / up; None when absent."""
    now = series.price_at(t_open)
    then = series.price_at(t_open - REGIME_LOOKBACK_S)
    if now is None or then is None or then <= 0:
        return None
    r = _bps(now, then)
    if r < -REGIME_BAND_BPS:
        return "down"
    return "up" if r > REGIME_BAND_BPS else "flat"
