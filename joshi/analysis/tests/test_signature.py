"""Signature volatility (FORMAL_MODEL.md P2) must read the two clocks separately."""
from decimal import Decimal
from itertools import pairwise

from joshi_analysis.signature import signature_event, signature_wall


def _bars(pairs):
    return [(ms, Decimal(p)) for ms, p in pairs]


def test_a_pure_trend_gives_a_rising_event_signature():
    """A monotone ramp has positive serial dependence, so sigma^2 must rise with lag."""
    bars = _bars([(i * 1000, f"{100 + i}") for i in range(64)])
    curve = [s for _, _, s, _ in signature_event(bars, [1, 2, 4, 8, 16])]
    assert all(b > a for a, b in pairwise(curve)), curve


def test_a_pure_alternation_gives_a_falling_event_signature():
    """A sawtooth reverts every step, so sigma^2 falls and then stays down.

    At even lags the series has returned exactly, so the variogram is zero. The curve is
    therefore non-increasing with a strict drop off lag 1 -- not strictly decreasing, which
    is what a first draft of this test wrongly asserted.
    """
    bars = _bars([(i * 1000, "100" if i % 2 == 0 else "101") for i in range(64)])
    curve = [s for _, _, s, _ in signature_event(bars, [1, 2, 4, 8, 16])]
    assert curve[1] < curve[0], curve
    assert all(b <= a for a, b in pairwise(curve)), curve


def test_the_two_clocks_disagree_on_a_gap_compressed_series():
    """Event lag is not wall lag once silent intervals are omitted.

    Two bursts of one-second bars separated by an hour of silence. In event time the
    bars are adjacent across the gap; in wall time they are 3600s apart. A measurement
    that conflated them would report the cross-gap move as a one-second move.
    """
    burst_a = [(i * 1000, Decimal(100 + i)) for i in range(8)]
    burst_b = [(3_600_000 + i * 1000, Decimal(200 + i)) for i in range(8)]
    bars = burst_a + burst_b

    event_lag_1 = signature_event(bars, [1])[0]
    assert event_lag_1[3] == 15, "event time pairs every adjacent bar, gap included"

    wall_lag_1 = signature_wall(bars, [1000])[0]
    assert wall_lag_1[3] == 14, "wall time pairs only bars genuinely one second apart"


def test_absence_is_reported_rather_than_zero():
    """A lag with no qualifying pairs yields None, never a confident zero."""
    bars = _bars([(0, "100"), (1000, "101")])
    _target, variogram, sigma, pairs = signature_wall(bars, [86_400_000])[0]
    assert pairs == 0
    assert variogram is None and sigma is None


def test_prices_keep_all_28_digits():
    """Provider prices are 28-digit decimal strings; float would discard twelve of them."""
    a = "0.0000000000000000000000000001"
    b = "0.0000000000000000000000000002"
    assert float(a) != float(b) or Decimal(a) != Decimal(b)
    bars = _bars([(0, a), (1000, b)])
    _, variogram, _, _ = signature_event(bars, [1])[0]
    assert variogram == Decimal(b) ** 2 - 2 * Decimal(a) * Decimal(b) + Decimal(a) ** 2
