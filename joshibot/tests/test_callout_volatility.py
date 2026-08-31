"""Estimator tests for the callout-volatility study.

The corpus these run against is 27 GB of gitignored parquet, so nothing here touches it.
What IS testable without it is the part that has gone wrong in this repo before: the
kernels, the null generators, and the cluster-robust arithmetic. Every test below asserts a
property that a plausible-looking wrong implementation would fail -- a zigzag that books
unconfirmed swings, a realized variance measured on trade arrivals instead of a clock, a
BY correction that is silently BH, a rotation null that also destroys the diurnal envelope
it is supposed to preserve.
"""

from __future__ import annotations

import math
import random
from itertools import pairwise

import pytest

from studies.callout_volatility import (
    CURVE_K,
    CURVE_TOKEN_OFFSET,
    MIN_CLUSTERS,
    RV_GRID_S,
    Series,
    Universe,
    by_fdr,
    clustered_slope,
    exposure_features,
    realized_variance,
    rotation_null,
    round_trip_threshold,
    swap_null,
    two_sided_p,
    zigzag,
)

T0 = 1_786_800_000


# ---------------------------------------------------------------- the zigzag


def test_a_monotone_path_has_no_confirmed_swings() -> None:
    """A coin sliding to zero is not wiggling. It is dying, and there is nothing to harvest."""
    path = [math.log(1.0 - 0.01 * i) for i in range(50)]
    assert zigzag(path, 0.05) == (0, 0.0)


def test_a_swing_is_booked_only_once_it_has_reversed_by_the_threshold() -> None:
    """The filter must not book an excursion it has not yet seen reverse.

    A version that books at the extreme is a lookahead bug wearing a zigzag's clothes: it
    would report a harvestable swing at the exact moment nobody could yet know there was
    one, which is the same error class as filling at the deciding snapshot.
    """
    up_only = [0.0, 0.05, 0.10, 0.15]
    assert zigzag(up_only, 0.04) == (0, 0.0)
    then_back = [*up_only, 0.10]
    swings, amplitude = zigzag(then_back, 0.04)
    assert swings == 1
    assert amplitude == pytest.approx(0.15)


def test_the_threshold_is_what_decides_a_wiggle_from_a_wobble() -> None:
    """Amplitude below friction is not opportunity, it is noise you would pay to trade."""
    oscillation = [0.0, 0.03, 0.0, 0.03, 0.0, 0.03, 0.0]
    assert zigzag(oscillation, 0.02)[0] >= 4
    assert zigzag(oscillation, 0.10) == (0, 0.0)


def test_a_degenerate_threshold_refuses_rather_than_dividing_the_world_into_swings() -> None:
    assert zigzag([0.0, 1.0, 0.0], 0.0) == (0, 0.0)
    assert zigzag([0.0, 1.0, 0.0], -1.0) == (0, 0.0)
    assert zigzag([0.5], 0.1) == (0, 0.0)


def test_net_of_friction_is_amplitude_minus_one_toll_per_swing() -> None:
    """The quantity a scalper keeps, which is the only one worth counting."""
    path = [0.0, 0.10, 0.0, 0.10, 0.0]
    swings, amplitude = zigzag(path, 0.05)
    assert swings == 3
    assert amplitude == pytest.approx(0.30)
    assert amplitude - swings * 0.05 == pytest.approx(0.15)


# ---------------------------------------------------------------- realized variance


def test_realized_variance_runs_on_a_CLOCK_not_on_trade_arrivals() -> None:
    """The confound the whole study is about, asserted.

    Two coins with identical price paths and wildly different trade COUNTS must report the
    same realized variance. An estimator that summed squared returns between consecutive
    trades would report the busy one as more volatile purely for being busy -- and "callouts
    mark busy coins" is the hypothesis, so that estimator would confirm itself.
    """
    sparse_t = [T0 + i * 300 for i in range(13)]
    sparse_p = [0.0 if i % 2 == 0 else 0.10 for i in range(13)]
    # The same path, sampled ten times as often: every extra print repeats the last price.
    dense_t: list[int] = []
    dense_p: list[float] = []
    for t, p in zip(sparse_t, sparse_p, strict=True):
        for k in range(10):
            dense_t.append(t + k)
            dense_p.append(p)
    lo, hi = T0, T0 + 3600
    rv_sparse, _ = realized_variance(sparse_t, sparse_p, lo, hi)
    rv_dense, _ = realized_variance(dense_t, dense_p, lo, hi)
    assert rv_sparse == pytest.approx(rv_dense, rel=1e-9)


def test_a_dead_minute_contributes_a_zero_return_and_is_counted_as_dead() -> None:
    """Nothing moved because nothing traded is a fact to record, not a gap to fill in."""
    times = [T0, T0 + 30]
    logp = [0.0, 0.05]
    rv, active = realized_variance(times, logp, T0, T0 + 600)
    assert rv == pytest.approx(0.05**2)
    # Ten minutes of grid, one of which saw a print.
    assert active == 1


def test_a_window_before_the_first_print_is_not_a_zero_variance_coin() -> None:
    """Never seen at or before the open is unmeasured; returning 0.0 would read as calm."""
    rv, active = realized_variance([], [], T0, T0 + 3600)
    assert rv != rv  # nan
    assert active == 0


def test_the_grid_is_the_declared_one() -> None:
    assert RV_GRID_S == 60


# ---------------------------------------------------------------- friction


def test_the_friction_threshold_comes_from_the_corrected_desk_module() -> None:
    """A study that priced friction its own way would not be comparable with the desk.

    The numbers below are the desk's, not this study's: ~2.4% round trip at a 0.1 SOL clip,
    rising as the pool thins because impact is ``2B/Y``.
    """
    deep = round_trip_threshold(100.0, take_bps=100)
    thin = round_trip_threshold(10.0, take_bps=100)
    assert 0.020 < deep < 0.030
    assert thin > deep
    assert round_trip_threshold(0.0, take_bps=100) == float("inf")


# ---------------------------------------------------------------- the corrections


def test_by_is_not_bh_and_is_strictly_more_conservative() -> None:
    """BY divides by the harmonic number. That IS the price of not knowing the dependence.

    The outcomes here are nested windows of one tape, so BH's independence assumption is
    not available. A BY that accidentally equals BH would silently restore it.
    """
    pvalues = [0.001, 0.008, 0.02, 0.04, 0.2, 0.5, 0.9]
    survived = by_fdr(pvalues, q=0.10)
    m = len(pvalues)
    c_m = sum(1.0 / k for k in range(1, m + 1))
    assert c_m > 2.5
    # The smallest p clears; a p that BH would pass at rank 3 must not clear here.
    assert survived[0]
    assert not survived[2], "0.02 clears BH at rank 3 (0.043) and must not clear BY (0.016)"


def test_by_handles_an_empty_and_an_all_nan_family_without_inventing_a_survivor() -> None:
    assert by_fdr([]) == []
    assert by_fdr([float("nan"), float("nan")]) == [False, False]


def test_a_p_value_is_two_sided() -> None:
    assert two_sided_p(0.0) == pytest.approx(1.0)
    assert two_sided_p(1.96) == pytest.approx(0.05, abs=0.001)
    assert two_sided_p(-1.96) == pytest.approx(0.05, abs=0.001)
    assert two_sided_p(float("nan")) != two_sided_p(float("nan"))


# ---------------------------------------------------------------- clustered SEs


def test_the_sandwich_refuses_rather_than_reporting_on_too_few_clusters() -> None:
    """Measured necessity: a null cohort varying over five mints reported |z| in the 20s.

    A cluster-robust variance over a handful of clusters is not a standard error, it is a
    random number, and a random number with a z next to it is worse than no number.
    """
    rng = random.Random(0)
    n = 200
    xs = [rng.random() for _ in range(n)]
    ys = [2.0 * x + rng.gauss(0, 0.1) for x in xs]
    few = [f"mint{i % (MIN_CLUSTERS - 1)}" for i in range(n)]
    many = [f"mint{i % (MIN_CLUSTERS * 2)}" for i in range(n)]
    slope_few, se_few, _ = clustered_slope(xs, ys, few)
    slope_many, se_many, _ = clustered_slope(xs, ys, many)
    assert slope_few == pytest.approx(slope_many, rel=1e-9), "the slope is unaffected"
    assert se_few != se_few, "too few clusters must yield nan, not a number"
    assert se_many > 0


def test_partialling_out_a_control_recovers_the_multiple_regression_slope() -> None:
    """Frisch-Waugh, asserted, because the whole 'conditional on the free columns' claim
    rests on the residualised slope being the multiple-regression one."""
    rng = random.Random(7)
    n = 400
    control = [rng.gauss(0, 1) for _ in range(n)]
    xs = [c * 0.5 + rng.gauss(0, 1) for c in control]
    ys = [3.0 * x + 5.0 * c + rng.gauss(0, 0.01) for x, c in zip(xs, control, strict=True)]
    slope, se, n_used = clustered_slope(
        xs, ys, [f"m{i % 50}" for i in range(n)], controls=(control,)
    )
    assert slope == pytest.approx(3.0, abs=0.02)
    assert n_used == n
    assert se > 0
    # Without the control the slope is biased by the omitted term, which is what makes the
    # conditional claim a claim at all.
    naive, _, _ = clustered_slope(xs, ys, [f"m{i % 50}" for i in range(n)])
    assert abs(naive - 3.0) > 0.5


def test_non_finite_rows_are_dropped_pairwise_not_zero_filled() -> None:
    xs = [1.0, 2.0, float("nan"), 4.0] * 20
    ys = [2.0, 4.0, 8.0, float("inf")] * 20
    _slope, _se, n = clustered_slope(xs, ys, [f"m{i}" for i in range(80)])
    assert n == 40


# ---------------------------------------------------------------- the nulls


def _events(n: int = 40) -> list[dict[str, object]]:
    rng = random.Random(11)
    return [
        {
            "mint": f"mint{i % 8}",
            "t_post": float(T0 + rng.randrange(0, 36_000)),
            "author": f"caller{i % 5}",
        }
        for i in range(n)
    ]


def test_rotation_preserves_the_count_the_mints_and_the_gaps() -> None:
    """The envelope survives; only the alignment with each coin's own flow is destroyed.

    An i.i.d. null would also destroy the diurnal shape, and diurnal amplitude in this
    market (3.6-5.4x) is larger than any callout effect anyone has claimed -- so an i.i.d.
    null manufactures an effect out of time-of-day alone. It has done so here twice.
    """
    events = _events()
    lo, hi = T0, T0 + 36_000
    rotated = rotation_null(events, offset=5_000.0, start_unix=lo, end_unix=hi)
    assert len(rotated) == len(events)
    assert [e["mint"] for e in rotated] == [e["mint"] for e in events]
    assert all(lo <= float(e["t_post"]) < hi for e in rotated)
    # Circular: the multiset of gaps AROUND THE CIRCLE (the wrap-around gap included) is
    # unchanged. A linear shift would break this at the wrap point, which is exactly the
    # difference between a rotation null and a translation that quietly thins one edge.
    def circular_gaps(rows: list[dict[str, object]]) -> list[float]:
        ts = sorted(float(r["t_post"]) for r in rows)
        gaps = [b - a for a, b in pairwise(ts)]
        gaps.append((hi - lo) - (ts[-1] - ts[0]))
        return sorted(gaps)

    assert circular_gaps(rotated) == pytest.approx(circular_gaps(events), abs=1e-6)


def test_a_zero_rotation_is_the_identity() -> None:
    events = _events()
    same = rotation_null(events, offset=0.0, start_unix=T0, end_unix=T0 + 36_000)
    assert [float(e["t_post"]) for e in same] == [float(e["t_post"]) for e in events]


def _universe(mints: list[str], pool: list[str]) -> Universe:
    def series(mint: str) -> Series:
        times = tuple(T0 + 60 * i for i in range(40))
        return Series(
            mint=mint,
            times=times,
            logp=tuple(-30.0 + 0.001 * i for i in range(40)),
            side=tuple(1 if i % 2 else -1 for i in range(40)),
            pool_sol=tuple(50.0 for _ in range(40)),
            is_pool=False,
            migrated=False,
        )

    return Universe(
        series={m: series(m) for m in [*mints, *pool]},
        created={m: float(T0 - 7200) for m in [*mints, *pool]},
        called=frozenset(mints),
        pool_mints=tuple(pool),
    )


def test_the_swap_null_keeps_every_instant_and_changes_only_the_coin() -> None:
    """The complement of the rotation null: does it matter WHICH coin was named?

    PROGRAM.md §3.13 -- a single null is a knob, not a test. Measured on co-trading, two
    nulls at nominally comparable thresholds differed 16x in edge count and agreed on 29%
    of edges, on a world where the clusters were planted.
    """
    events = _events(16)
    called = sorted({str(e["mint"]) for e in events})
    universe = _universe(called, [f"donor{i}" for i in range(30)])
    assert len(called) < 30, "the fixture must have donors to spare"
    swapped = swap_null(events, universe, rng=random.Random(3))
    assert sorted(float(e["t_post"]) for e in swapped) == sorted(
        float(e["t_post"]) for e in events
    )
    assert {str(e["mint"]) for e in swapped}.isdisjoint(called)
    # A donor is used at most once, or one coin would absorb several callers' streams and
    # the swapped world would be denser than the real one.
    donors = [str(e["mint"]) for e in swapped]
    assert len(set(donors)) == len({str(e["mint"]) for e in events if str(e["mint"]) in called})


def test_swap_null_drops_a_mint_it_cannot_match_rather_than_matching_it_badly() -> None:
    events = _events(8)
    universe = _universe(sorted({str(e["mint"]) for e in events}), [])
    assert swap_null(events, universe, rng=random.Random(1)) == []


# ---------------------------------------------------------------- exposure


def test_exposure_is_strictly_causal_and_never_reads_the_future() -> None:
    events = [
        {"mint": "A", "t_post": float(T0 - 100), "author": "x"},
        {"mint": "A", "t_post": float(T0 - 50), "author": "y"},
        {"mint": "A", "t_post": float(T0 + 10), "author": "z"},  # AFTER t0
    ]
    features = exposure_features(events, "A", float(T0))
    assert features["n_callouts"] == 2.0
    assert features["n_callers"] == 2.0
    assert features["recency_s"] == pytest.approx(50.0)
    assert features["cadence_s"] == pytest.approx(50.0)


def test_no_cadence_observed_is_the_window_never_zero() -> None:
    """Zero would read as the fastest possible stream -- the loudest value of the column."""
    single = exposure_features([{"mint": "A", "t_post": float(T0), "author": "x"}], "A", float(T0))
    assert single["cadence_s"] > 0
    none = exposure_features([], "A", float(T0))
    assert none["n_callouts"] == 0.0
    assert none["recency_s"] == none["cadence_s"] > 0


# ---------------------------------------------------------------- the curve identity


def test_the_launch_constants_are_the_ones_recovered_from_chain() -> None:
    """``--validate`` measured these against 27,076 board observations. They are pinned so
    that a silent edit shows up as a failing test rather than as a shifted volatility."""
    assert CURVE_TOKEN_OFFSET == 73_000_000_000_000
    assert pytest.approx(3.219e25) == CURVE_K
    # 30 SOL of virtual quote against 1.073e9 virtual tokens is exactly that product.
    assert pytest.approx(CURVE_K, rel=1e-6) == 30e9 * 1.073e15


def test_log_price_differences_do_not_depend_on_the_constants() -> None:
    """The claim the instrument rests on: k cancels out of every outcome measured here.

    Volatility, drawdown and wiggle amplitude are all functions of log-price DIFFERENCES,
    so a coin on a different curve configuration is still measured correctly.
    """

    def log_price(ata_balance: float, k: float) -> float:
        return math.log(k) - 2 * math.log(ata_balance + CURVE_TOKEN_OFFSET)

    balances = [8.0e14, 7.5e14, 8.2e14]
    for k in (CURVE_K, CURVE_K * 3.0, CURVE_K / 7.0):
        series = [log_price(b, k) for b in balances]
        deltas = [b - a for a, b in pairwise(series)]
        reference = [
            log_price(b, CURVE_K) - log_price(a, CURVE_K)
            for a, b in pairwise(balances)
        ]
        assert deltas == pytest.approx(reference, rel=1e-12)
