"""Controls for `studies/operator_crime.py`.

PROGRAM.md §3.12 is the rule this file exists for: **both controls, always -- a null control
alone is worthless.** The SVN study paid for that rule in cash. Its degree-preserving null was
ranked by a z-score, every unreached pair scored `+inf` under a zero-variance null, and
matched-density ranking silently degenerated to array index order. The zero-coordination
control stayed GREEN throughout, because *an estimator that detects nothing passes a
null-recovery test perfectly*. Only the planted-recovery test caught it.

So the sniper-reuse instrument is tested twice, against a world with no shared infrastructure
and against a world with a planted operator, and the same statistic has to say different
things about them.
"""

from __future__ import annotations

import numpy as np
import pytest

from studies.operator_crime import _curveball, _mean_jaccard


def _pairs(groups: list[list[int]]) -> list[tuple[int, int]]:
    out = []
    for g in groups:
        for a in range(len(g)):
            for b in range(a + 1, len(g)):
                out.append((g[a], g[b]))
    return out


def _world(rng, n_deployers: int, coins_each: int, n_wallets: int, snipers: int, shared: int):
    """Build a coin x sniper incidence.

    `shared` is the number of wallets each deployer reuses across every one of its coins;
    `shared = 0` is the zero-coordination world.
    """
    sets: list[set[int]] = []
    groups: list[list[int]] = []
    idx = 0
    for _d in range(n_deployers):
        crew = set(rng.choice(n_wallets, size=shared, replace=False)) if shared else set()
        g = []
        for _ in range(coins_each):
            rest = set(rng.choice(n_wallets, size=snipers - shared, replace=False))
            sets.append(crew | rest)
            g.append(idx)
            idx += 1
        groups.append(g)
    return sets, groups


def test_independent_wallets_yield_no_validated_edges():
    """KNOWN-ZERO world: nobody reuses anybody, so same-deployer Jaccard must sit inside the
    degree-preserving null."""
    rng = np.random.default_rng(11)
    sets, groups = _world(rng, n_deployers=40, coins_each=4, n_wallets=600, snipers=12, shared=0)
    same = _pairs(groups)
    obs = _mean_jaccard(same, sets)
    null = np.array(
        [_mean_jaccard(same, _curveball(sets, 5 * len(sets), rng)) for _ in range(60)]
    )
    assert obs <= np.quantile(null, 0.95), (
        f"zero-coordination world produced a same-deployer Jaccard of {obs:.4f} above the "
        f"degree-preserving p95 of {np.quantile(null, 0.95):.4f} -- the null is too weak"
    )


def test_planted_clusters_are_recovered():
    """KNOWN-EFFECT world: each deployer reuses half its crew, and the instrument must see it.

    This is the test that the SVN z-score bug failed and the zero-control did not.
    """
    rng = np.random.default_rng(11)
    sets, groups = _world(rng, n_deployers=40, coins_each=4, n_wallets=600, snipers=12, shared=6)
    same = _pairs(groups)
    obs = _mean_jaccard(same, sets)
    null = np.array(
        [_mean_jaccard(same, _curveball(sets, 5 * len(sets), rng)) for _ in range(60)]
    )
    assert obs > np.quantile(null, 0.95), (
        f"planted operator crews were NOT recovered: observed {obs:.4f} against a "
        f"degree-preserving p95 of {np.quantile(null, 0.95):.4f}"
    )
    assert obs > 3 * null.mean(), "planted effect should be large, not marginal"


def test_curveball_preserves_both_degrees():
    """The null is only degree-preserving if it actually preserves degrees.

    A randomisation that quietly changes a wallet's coin count would let a 4,000-coin sniper
    bot dissolve into the background, which is the single easiest way to manufacture a
    significant result here.
    """
    rng = np.random.default_rng(3)
    sets, _ = _world(rng, n_deployers=30, coins_each=3, n_wallets=400, snipers=9, shared=3)
    before_rows = [len(s) for s in sets]
    before_cols: dict[int, int] = {}
    for s in sets:
        for w in s:
            before_cols[w] = before_cols.get(w, 0) + 1

    out = _curveball(sets, 5 * len(sets), rng)
    after_cols: dict[int, int] = {}
    for s in out:
        for w in s:
            after_cols[w] = after_cols.get(w, 0) + 1

    assert [len(s) for s in out] == before_rows, "coin sniper-counts changed"
    assert after_cols == before_cols, "wallet coin-counts changed"


def test_curveball_actually_randomises():
    """A no-op is degree preserving too. The null must move."""
    rng = np.random.default_rng(5)
    sets, groups = _world(rng, n_deployers=20, coins_each=4, n_wallets=300, snipers=10, shared=5)
    same = _pairs(groups)
    out = _curveball(sets, 5 * len(sets), rng)
    assert any(a != b for a, b in zip(sets, out, strict=True)), "curveball returned the input unchanged"
    assert _mean_jaccard(same, out) < _mean_jaccard(same, sets)


@pytest.mark.parametrize("shared,expect", [(0, False), (6, True)])
def test_the_verdict_flips_with_the_world(shared, expect):
    """One statistic, two worlds, opposite verdicts. If this parametrisation ever agrees on
    both rows, the instrument is a constant and every headline built on it is meaningless."""
    rng = np.random.default_rng(7)
    sets, groups = _world(rng, 30, 4, 500, 12, shared)
    same = _pairs(groups)
    obs = _mean_jaccard(same, sets)
    null = np.array(
        [_mean_jaccard(same, _curveball(sets, 5 * len(sets), rng)) for _ in range(40)]
    )
    # `bool(...)`, not `is`: the comparison yields a numpy bool_ and `np.True_ is True` is
    # False, which fails the row that is behaving correctly.
    assert bool(obs > np.quantile(null, 0.95)) is expect
