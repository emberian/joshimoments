"""The regime tag must label known dynamics correctly and refuse to label what it cannot."""

import math
import random

from joshi_analysis.regime import (
    MIN_EVENTS,
    RegimeTag,
    band,
    event_curve,
    regime_tag,
    slope_from_curve,
    wall_curve,
    wall_samples,
)


def _walk(n: int, seed: int, drift: float = 0.0, revert: float = 0.0) -> list[float]:
    """Log-price walk: pure diffusion, plus optional drift (trend) or OU pull (reversion)."""
    rng = random.Random(seed)
    x = 0.0
    out = []
    for _ in range(n):
        x += drift - revert * x + rng.gauss(0, 0.01)
        out.append(100.0 * math.exp(x))
    return out


def _times(n: int) -> list[int]:
    return list(range(1_700_000_000, 1_700_000_000 + n))


def test_a_random_walk_is_diffusive_with_a_ci_covering_one():
    prices = _walk(4000, seed=1)
    tag = regime_tag(_times(4000), prices, clock="event", n_boot=100)
    assert tag.label == "diffusive", tag.render()
    assert tag.ci_low is not None and tag.ci_low < 1.0 < tag.ci_high, tag.render()


def test_a_drifting_walk_is_trending():
    prices = _walk(4000, seed=2, drift=0.004)
    tag = regime_tag(_times(4000), prices, clock="event", n_boot=100)
    assert tag.label == "trending", tag.render()
    assert tag.slope is not None and tag.slope > 1.33


def test_an_ou_series_is_reverting():
    prices = _walk(4000, seed=3, revert=0.5)
    tag = regime_tag(_times(4000), prices, clock="event", n_boot=100)
    assert tag.label == "reverting", tag.render()
    assert tag.slope is not None and tag.slope < 0.75


def test_too_few_events_is_indeterminate_with_the_reason_stated():
    n = MIN_EVENTS - 1
    tag = regime_tag(_times(n), _walk(n, seed=4), clock="event")
    assert tag.label == "indeterminate"
    assert tag.reason == "insufficient_events"
    assert tag.n_events == n  # the sample size is in the tag either way


def test_a_flat_line_has_no_measurement_not_a_zero_slope():
    n = 600
    tag = regime_tag(_times(n), [5.0] * n, clock="event")
    assert tag.label == "indeterminate"
    assert tag.reason == "no_measure_at_lag"
    assert tag.slope is None


def test_the_tag_is_deterministic():
    prices = _walk(1200, seed=5)
    a = regime_tag(_times(1200), prices, clock="event", n_boot=50)
    b = regime_tag(_times(1200), prices, clock="event", n_boot=50)
    assert a == b
    assert isinstance(a, RegimeTag)


def test_wall_clock_tags_a_one_event_per_second_walk_like_the_event_clock():
    prices = _walk(4000, seed=6, drift=0.004)
    tag = regime_tag(_times(4000), prices, clock="wall", n_boot=100)
    assert tag.label == "trending", tag.render()


def test_wall_samples_collapse_bursts_to_the_last_price_of_the_second():
    times = [10, 10, 10, 11, 13]
    prices = [1.0, 2.0, 3.0, 4.0, 5.0]
    sec_t, sec_p = wall_samples(times, prices)
    assert sec_t == [10, 11, 13]
    assert sec_p == [3.0, 4.0, 5.0]


def test_wall_curve_reports_absence_at_unpopulated_lags():
    # Samples 100 seconds apart: no pair exists within 25% of any lag up to 32s.
    sec_t = list(range(0, 5000, 100))
    sec_p = [100.0 + (i % 7) for i in range(len(sec_t))]
    curve = wall_curve(sec_t, sec_p, (1, 2, 4, 8, 16, 32))
    assert all(sigma is None and pairs == 0 for _, sigma, pairs in curve)


def test_the_render_line_carries_every_denominator():
    n = 1200
    tag = regime_tag(_times(n), _walk(n, seed=7), clock="event", n_boot=50)
    line = tag.render()
    for needle in ("lags 1..32", f"n={n} events", "span", "pairs", "amm_pool_vault_fill"):
        assert needle in line, line


def test_band_boundaries_match_the_corpus_study():
    assert band(0.74) == "reverting"
    assert band(0.75) == "diffusive"
    assert band(1.32) == "diffusive"
    assert band(1.33) == "trending"


def test_slope_from_curve_refuses_a_zero_denominator():
    curve = event_curve([5.0] * 100, (1, 2, 4))
    assert slope_from_curve(curve, 1, 4) is None
