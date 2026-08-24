"""Labels must map to money exactly; features must be causal and warm up honestly."""

import math
from decimal import Decimal

import pytest

from joshi_analysis.scalplab.featureset import FEATURE_DEFINITIONS, FEATURE_NAMES, feature_matrix
from joshi_analysis.scalplab.labels import floor_clearing_labels
from joshi_analysis.scalplab.tape import TapeEvent
from joshi_analysis.scalplab.vocabulary import WARMUP_EVENTS


def _prices(values):
    return [Decimal(v) for v in values]


def test_label_requires_the_floor_to_clear_from_the_delayed_entry():
    # entry for decision 0 is prices[1] = 100; floor 500 bps needs >= 105 within the window
    prices = _prices(["90", "100", "104", "105", "100", "100", "100"])
    labels = floor_clearing_labels(prices, horizon_k=2, floor_bps=500)
    # decision 0: window j in [2,3]: 104 < 105, 105 >= 105 -> hit (exact equality counts)
    assert labels.labels[0] == 1
    # decision 1: entry 104, needs >= 109.2 within j in [3,4]: no
    assert labels.labels[1] == 0
    # tail windows run off the end -> None, counted
    assert labels.labels[-1] is None
    assert labels.n_undefined_tail == 3
    assert labels.n_defined == 4
    assert labels.base_rate == pytest.approx(0.25)


def test_label_zero_floor_is_still_not_a_direction_label():
    # even at floor 0 the up-leg must strictly come from the delayed entry
    prices = _prices(["100", "100", "99", "98", "97"])
    labels = floor_clearing_labels(prices, horizon_k=2, floor_bps=0)
    assert labels.labels[0] == 0


def _event(i, price, side="buy", trader="T", when_us=None):
    return TapeEvent(
        ordinal=i,
        mint="M",
        side=side,
        price=Decimal(str(price)),
        fill_price=None,
        base_signed=Decimal(1) if side == "buy" else Decimal(-1),
        quote_signed=Decimal("0.1") if side == "buy" else Decimal("-0.1"),
        trader=trader,
        venue="pump-amm",
        tx=f"tx{i}",
        slot=None,
        event_time_us=when_us if when_us is not None else 1_000_000 + i * 500_000,
        arrival_wall_us=1_000_000 + i * 500_000,
    )


def test_features_start_after_warmup_and_names_are_all_defined():
    events = [_event(i, 100 + i * 0.01) for i in range(WARMUP_EVENTS + 3)]
    indices, vectors = feature_matrix(events)
    assert indices == [WARMUP_EVENTS, WARMUP_EVENTS + 1, WARMUP_EVENTS + 2]
    assert all(len(v) == len(FEATURE_NAMES) for v in vectors)
    assert set(FEATURE_DEFINITIONS) == set(FEATURE_NAMES)


def test_features_are_causal():
    events = [_event(i, 100 + math.sin(i / 3.0), side="buy" if i % 3 else "sell")
              for i in range(60)]
    _, full = feature_matrix(events)
    _, prefix = feature_matrix(events[:50])
    assert full[: len(prefix)] == prefix


def test_levy_area_sign_tracks_path_convexity():
    # accelerating rise (convex in time) -> positive area; decelerating -> negative
    n = 40
    convex = [_event(i, math.exp(0.001 * (i / n) ** 2 * n)) for i in range(n)]
    concave = [_event(i, math.exp(0.001 * math.sqrt(i / n) * n)) for i in range(n)]
    area_index = FEATURE_NAMES.index("levy_area_w32")
    _, convex_vectors = feature_matrix(convex)
    _, concave_vectors = feature_matrix(concave)
    assert convex_vectors[-1][area_index] > 0
    assert concave_vectors[-1][area_index] < 0


def test_buy_fraction_and_imbalance_read_the_window():
    events = [_event(i, 100, side="buy") for i in range(WARMUP_EVENTS + 1)]
    _, vectors = feature_matrix(events)
    buy_index = FEATURE_NAMES.index("buy_fraction_w32")
    imbalance_index = FEATURE_NAMES.index("quote_imbalance_w32")
    assert vectors[0][buy_index] == 1.0
    assert vectors[0][imbalance_index] == pytest.approx(1.0)
