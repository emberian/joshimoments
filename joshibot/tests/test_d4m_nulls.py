"""Null calibration: reproduce RESULT_svn_cotrading.md's failure mode, then defeat it.

Section 5 of that study measured what PROGRAM.md 4.1 had only predicted: under heavy-tailed
token popularity with ZERO planted coordination, BH-FDR validated a mean of 99 false wallet
pairs per world in 30 of 30 worlds, and a degree-preserving null deleted 100% of them.

This lane's estimator is not that one -- it cuts at a fixed Jaccard rather than at a
corrected p-value -- so the failure mode has to be reproduced in ITS vocabulary. It is the
same failure: on a world built with no coordination at all, a fixed-threshold crew rule
returns thousands of confident wallet pairs, because popular coins are bought by everyone.
The test below shows (a) that this lane's raw edge count is enormous on such a world, (b)
that the degree-preserving null reproduces that count, so the correct verdict is NULL, and
(c) that on a world with planted rings the SAME procedure separates them. An estimator that
fires on (a) is the thing this repo has already shipped twice by accident.
"""

from __future__ import annotations

import numpy as np
import pytest

from dregg_d4m import nulls
from dregg_d4m.assoc import Assoc, co_occurrence, jaccard, threshold

CREW_JACCARD = 0.10
MIN_OVERLAP = 2


def crew_edges(a: Assoc) -> float:
    """This lane's crew rule as a scalar: pairs at overlap >= 2 and Jaccard >= 0.10."""

    prod = co_occurrence(a, axis="row", min_overlap=float(MIN_OVERLAP))
    j = threshold(jaccard(prod, a.degree(axis="row")).drop_diagonal(), CREW_JACCARD)
    return float(j.nnz // 2)


def zipf_world(
    *, n_wallets: int, n_coins: int, exponent: float, lo: int, hi: int, seed: int,
    rings: int = 0, ring_size: int = 0, ring_coins: int = 0,
) -> Assoc:
    """Wallets draw coins with Zipf popularity. ``rings`` plants coordinated groups.

    With ``rings=0`` there is NO coordination of any kind: every wallet draws independently.
    Any structure a detector reports on such a world is manufactured by popularity."""

    rng = np.random.default_rng(seed)
    weights = 1.0 / np.power(np.arange(1, n_coins + 1), exponent)
    weights /= weights.sum()
    rows: list[str] = []
    cols: list[str] = []
    for w in range(n_wallets):
        k = int(rng.integers(lo, hi + 1))
        picked = rng.choice(n_coins, size=min(k, n_coins), replace=False, p=weights)
        rows.extend([f"w{w:04d}"] * len(picked))
        cols.extend(f"c{int(c):04d}" for c in picked)
    # planted rings share a block of UNPOPULAR coins -- the only kind a degree-preserving
    # null cannot explain away, which is exactly why coordination has to look like this
    for r in range(rings):
        block = rng.choice(np.arange(n_coins // 2, n_coins), size=ring_coins, replace=False)
        for member in range(ring_size):
            w = r * ring_size + member
            rows.extend([f"w{w:04d}"] * ring_coins)
            cols.extend(f"c{int(c):04d}" for c in block)
    return Assoc.from_tuples(
        rows, cols,
        row_keys=[f"w{w:04d}" for w in range(n_wallets)],
        col_keys=[f"c{c:04d}" for c in range(n_coins)],
    ).binarize()


def test_heavy_tailed_popularity_manufactures_crew_edges_out_of_nothing():
    """(a) The failure mode, in this lane's own vocabulary."""

    world = zipf_world(n_wallets=150, n_coins=300, exponent=2.2, lo=20, hi=60, seed=20260829)
    edges = crew_edges(world)
    n_pairs = 150 * 149 / 2
    assert edges > 1_000, (
        f"expected the heavy-tailed zero-coordination world to manufacture a large number of "
        f"crew edges; got {edges}. If this ever drops, the demonstration below is vacuous."
    )
    # more than a tenth of ALL pairs, on data with no coordination whatsoever
    assert edges / n_pairs > 0.10


def test_the_degree_preserving_null_refuses_the_zero_coordination_world():
    """(b) Same world, scored against the null this lane actually uses: verdict NULL."""

    world = zipf_world(n_wallets=150, n_coins=300, exponent=2.2, lo=20, hi=60, seed=20260829)
    res = nulls.against_null(world, crew_edges, draws=40, seed=7)
    assert res.observed > 1_000  # the raw count is still huge
    assert 0.8 < res.ratio < 1.25, (
        f"the null must reproduce the observed edge count on a world with no coordination; "
        f"observed {res.observed}, null mean {res.mean}, ratio {res.ratio}"
    )
    assert res.p_value > 0.01, "a zero-coordination world must NOT clear the ship threshold"


def ring_pairs(n_rings: int, ring_size: int) -> list[tuple[int, int]]:
    out = []
    for r in range(n_rings):
        members = [r * ring_size + m for m in range(ring_size)]
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                out.append((members[x], members[y]))
    return out


def test_the_global_edge_count_is_the_WRONG_statistic_and_that_is_the_lesson():
    """The count of edges over a threshold is dominated by ambient popularity overlap.

    Measured, not asserted: on a heavy-tailed world the crew rule fires on more than a tenth
    of all pairs with nothing planted, so a global count cannot separate a planted world from
    an empty one. This is why every estimand in this lane is a statistic over a NAMED PAIR
    LIST (same-deployer pairs in D1, community pairs in D3) scored against the null on that
    same list -- the shape ``operator_crime``'s cmd_graph already uses -- and never a count of
    how many edges cleared a cut.
    """

    planted = zipf_world(
        n_wallets=150, n_coins=300, exponent=1.1, lo=4, hi=10, seed=20260829,
        rings=6, ring_size=8, ring_coins=9,
    )
    res = nulls.against_null(planted, crew_edges, draws=20, seed=7)
    assert res.ratio < 1.5, (
        "the global edge count does NOT separate a planted world; if it ever does, this "
        f"test's premise changed. ratio {res.ratio}"
    )


def test_the_pair_list_statistic_separates_a_planted_world():
    """(c) Power, using the statistic this lane actually ships (D1's shape)."""

    n_rings, ring_size = 6, 8
    planted = zipf_world(
        n_wallets=150, n_coins=300, exponent=1.1, lo=4, hi=10, seed=20260829,
        rings=n_rings, ring_size=ring_size, ring_coins=9,
    )
    pairs = ring_pairs(n_rings, ring_size)
    res = nulls.against_null(
        planted, lambda x: nulls.mean_jaccard_over_pairs(x, pairs), draws=40, seed=7
    )
    assert res.ratio > 3.0, f"planted rings must exceed the null; ratio {res.ratio}"
    assert res.p_value <= 0.01
    assert res.observed > res.p95


def test_the_pair_list_statistic_refuses_ARBITRARY_groups_in_an_empty_world():
    """(d) The direct analogue of svn section 5's 99 false edges.

    Same pair-list statistic, same threshold, on a heavy-tailed world with NO coordination,
    scored over groups invented by the analyst. The raw mean Jaccard is large -- popular
    coins make any group look coordinated -- and the degree-preserving null reproduces it, so
    nothing is claimed. A hypergeometric or fixed-threshold reading of the same number would
    have shipped six crews."""

    world = zipf_world(n_wallets=150, n_coins=300, exponent=2.2, lo=20, hi=60, seed=20260829)
    pairs = ring_pairs(6, 8)  # invented groups; the world knows nothing about them
    res = nulls.against_null(
        world, lambda x: nulls.mean_jaccard_over_pairs(x, pairs), draws=40, seed=7
    )
    assert res.observed > 0.10, (
        f"the raw statistic must LOOK like a crew at the live threshold; got {res.observed}"
    )
    assert 0.75 < res.ratio < 1.35, (
        f"the null must explain it away; observed {res.observed}, null {res.mean}"
    )
    assert res.p_value > 0.01


def test_the_null_preserves_both_margins_exactly():
    """The whole claim rests on this: only WHICH cell is filled may change."""

    world = zipf_world(n_wallets=60, n_coins=120, exponent=1.5, lo=3, hi=12, seed=5)
    rng = np.random.default_rng(99)
    for _ in range(3):
        drawn = nulls.randomise(world, rng)
        assert drawn.row == world.row
        assert drawn.col == world.col
        assert np.array_equal(drawn.degree(axis="row"), world.degree(axis="row"))
        assert np.array_equal(drawn.degree(axis="col"), world.degree(axis="col"))
        assert drawn.nnz == world.nnz


def test_the_null_actually_moves_the_incidence():
    """A null that returns its input passes every degree check and proves nothing."""

    world = zipf_world(n_wallets=60, n_coins=120, exponent=1.5, lo=3, hi=12, seed=5)
    drawn = nulls.randomise(world, np.random.default_rng(1))
    assert drawn.to_dict() != world.to_dict()


def test_null_draws_are_reproducible_from_the_seed():
    world = zipf_world(n_wallets=40, n_coins=90, exponent=1.4, lo=3, hi=9, seed=3)
    a = nulls.against_null(world, crew_edges, draws=5, seed=20260829)
    b = nulls.against_null(world, crew_edges, draws=5, seed=20260829)
    assert a.draws == b.draws
    assert a.observed == b.observed


def test_wilson_interval_brackets_the_point_estimate():
    lo, hi = nulls.wilson(15, 284)
    assert lo < 15 / 284 < hi
    assert nulls.wilson(0, 50)[0] == pytest.approx(0.0, abs=1e-12)
    assert nulls.wilson(0, 0) == (0.0, 1.0)
