"""Provenance, window semantics, determinism, and the clustering's own failure mode."""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from dregg_d4m import graphs
from dregg_d4m.analyses import label_propagation
from dregg_d4m.assoc import Assoc

CORPUS = graphs.COMBINED / "snipers.parquet"
needs_corpus = pytest.mark.skipif(not CORPUS.exists(), reason="study corpus not present")


def test_window_bounds_cover_the_stated_days_and_nothing_else():
    from datetime import UTC, datetime

    lo_a, hi_a = graphs._bounds("A")
    lo_b, hi_b = graphs._bounds("B")
    assert datetime.fromtimestamp(lo_a, UTC).date().isoformat() == graphs.WINDOW_A[0]
    # the window is half-open and must INCLUDE the whole last day
    assert datetime.fromtimestamp(hi_a - 1, UTC).date().isoformat() == graphs.WINDOW_A[1]
    assert datetime.fromtimestamp(lo_b, UTC).date().isoformat() == graphs.WINDOW_B[0]
    assert datetime.fromtimestamp(hi_b - 1, UTC).date().isoformat() == graphs.WINDOW_B[1]
    assert hi_a < lo_b, "the 11-day gap must be a gap"
    assert graphs._bounds("all") == (0.0, float("inf"))


@needs_corpus
def test_birth_snipers_carries_a_real_window_stamp():
    g = graphs.birth_snipers(window="B")
    assert g.prov.span[0] >= graphs.WINDOW_B[0]
    assert g.prov.span[1] <= graphs.WINDOW_B[1]
    assert g.prov.nnz == g.a.nnz
    assert g.prov.n_rows == g.a.shape[0]
    assert "ex-deployer" in g.prov.notes


@needs_corpus
def test_the_ex_deployer_rule_actually_removes_the_deployer():
    df = graphs.load_snipers("B")
    with_dep = graphs.birth_snipers(window="B", ex_deployer=False)
    without = graphs.birth_snipers(window="B", ex_deployer=True)
    assert without.a.nnz < with_dep.a.nnz
    assert int((df["owner"] == df["deployer"]).sum()) == with_dep.a.nnz - without.a.nnz


@needs_corpus
def test_windows_partition_the_corpus():
    a = graphs.birth_snipers(window="A")
    b = graphs.birth_snipers(window="B")
    both = graphs.birth_snipers(window="all")
    assert a.a.nnz + b.a.nnz == both.a.nnz
    assert not (set(a.a.col) & set(b.a.col)), "a coin is born once, in one window"


@needs_corpus
def test_the_degree_cap_only_removes_rows_and_records_how_many():
    full = graphs.birth_snipers(window="B")
    capped = graphs.birth_snipers(window="B", wallet_degree_cap=10)
    assert capped.a.shape[0] < full.a.shape[0]
    assert capped.prov.params["wallets_dropped_by_cap"] == full.a.shape[0] - capped.a.shape[0]
    assert int(capped.a.degree(axis="row").max()) <= 10
    assert set(capped.a.row) <= set(full.a.row)


def test_label_propagation_is_deterministic_and_finds_the_planted_blocks():
    # two disjoint triangles: any correct partition puts each in its own community
    rows = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    cols = [1, 2, 0, 2, 0, 1, 4, 5, 3, 5, 3, 4]
    m = sp.csr_array((np.ones(len(rows)), (rows, cols)), shape=(6, 6))
    a = label_propagation(m)
    b = label_propagation(m)
    assert np.array_equal(a, b)
    assert len(set(a[:3].tolist())) == 1
    assert len(set(a[3:].tolist())) == 1
    assert a[0] != a[3]


def test_label_propagation_does_not_build_the_union_find_blob():
    """The documented pathology, exactly: RESULT_cluster_map.md section 3 measured that ONE
    promiscuous wallet chains 14,238 wallets (8.3% of everything clustered) into a single
    union-find component while Infomap's largest module was 186. The shape is two dense
    groups joined by a single bridge edge -- connected components must return one blob and a
    community method must not."""

    from scipy.sparse.csgraph import connected_components

    size = 8
    rows: list[int] = []
    cols: list[int] = []
    for base in (0, size):
        for i in range(base, base + size):
            for j in range(base, base + size):
                if i != j:
                    rows.append(i)
                    cols.append(j)
    weights = [1.0] * len(rows)
    rows += [0, size]  # the single weak bridge -- a low-Jaccard edge, as in the real graph
    cols += [size, 0]
    weights += [0.1, 0.1]
    m = sp.csr_array((np.asarray(weights), (rows, cols)), shape=(2 * size, 2 * size))
    n_cc, _cc = connected_components(m, directed=False)
    assert n_cc == 1, "union-find sees one blob -- that is the failure being guarded against"
    lp = label_propagation(m)
    assert len(set(lp.tolist())) == 2, "the two cliques must survive as separate communities"
    assert len(set(lp[:size].tolist())) == 1
    assert len(set(lp[size:].tolist())) == 1


def test_label_propagation_is_degenerate_on_unweighted_regular_graphs():
    """The limitation, recorded rather than hidden.

    With every edge weight equal, every candidate label ties and the deterministic
    smallest-label rule cascades across the bridge. This is why the crew graph is clustered
    on its Jaccard WEIGHTS and never on a binarised copy, and why giant-component share is
    reported next to every partition."""

    size = 8
    rows: list[int] = []
    cols: list[int] = []
    for base in (0, size):
        for i in range(base, base + size):
            for j in range(base, base + size):
                if i != j:
                    rows.append(i)
                    cols.append(j)
    rows += [0, size]
    cols += [size, 0]
    m = sp.csr_array((np.ones(len(rows)), (rows, cols)), shape=(2 * size, 2 * size))
    assert len(set(label_propagation(m).tolist())) == 1  # the degeneracy, pinned


def test_assoc_from_row_sets_round_trips_a_real_shaped_incidence():
    a = Assoc.from_tuples(
        ["w1", "w1", "w2", "w3", "w3", "w3"],
        ["cA", "cB", "cB", "cA", "cB", "cC"],
    )
    assert Assoc.from_row_sets(a.row_sets(), a.row, a.col).to_dict() == a.to_dict()


@needs_corpus
def test_caller_matrix_is_built_and_is_small_enough_to_veto():
    g = graphs.caller_coins()
    assert g.a.shape[0] > 0 and g.a.shape[1] > 0
    assert "sampling artifact" in g.prov.notes or "SAMPLING artifact" in g.prov.notes


LEGS = graphs.LEGS
needs_legs = pytest.mark.skipif(not LEGS.exists(), reason="bulk leg tape not present")


@needs_legs
def test_wallet_coin_matrix_builds_and_declares_a_different_window_from_B():
    """W and B are DIFFERENT corpora. The provenance must make that impossible to miss."""

    w = graphs.wallet_coins(value="legs")
    assert w.a.nnz > 1_000_000
    assert w.prov.value == "leg count"
    assert w.prov.window == "bulk-tape"
    assert "NOT the operator_crime window" in w.prov.notes
    if CORPUS.exists():
        b = graphs.birth_snipers(window="all")
        assert w.prov.span != b.prov.span, "W and B must not claim the same window"


@needs_legs
def test_wallet_coin_value_choice_changes_the_array_not_the_support():
    legs = graphs.wallet_coins(value="legs")
    sol = graphs.wallet_coins(value="sol_signed")
    assert legs.a.shape == sol.a.shape
    assert set(legs.a.row) == set(sol.a.row)
    assert legs.prov.value != sol.prov.value
    assert (legs.a.m.data > 0).all(), "a leg count is a count"
    assert (sol.a.m.data < 0).any(), "signed SOL must carry buys as negatives"


@needs_corpus
def test_the_d1_replication_statistic_is_deterministic_and_hits_the_published_number():
    """The licence for the whole lane, pinned as a test rather than left in a RESULT.

    ``studies/data/operator_crime_fresh/graph.json`` records 0.2607947149034321 for the
    same-deployer mean Jaccard. The algebra must return it, twice, from the same corpus."""

    import numpy as np

    from dregg_d4m.analyses import REPLICATION_TARGETS, _algebra_mean_jaccard, _fresh_arm

    arm, pair_list, _sub = _fresh_arm()
    pairs = np.asarray(pair_list, dtype=np.int64)
    first = _algebra_mean_jaccard(arm, pairs)
    second = _algebra_mean_jaccard(arm, pairs)
    assert first == second, "the statistic must not vary between calls"
    assert first == pytest.approx(REPLICATION_TARGETS["same_deployer_jaccard"], abs=1e-12), (
        f"the algebra returned {first!r} where cmd_graph published "
        f"{REPLICATION_TARGETS['same_deployer_jaccard']!r}"
    )


@needs_corpus
def test_the_arm_is_rebuilt_identically_across_calls():
    from dregg_d4m.analyses import _fresh_arm

    a1, p1, _s1 = _fresh_arm()
    a2, p2, _s2 = _fresh_arm()
    assert a1.row == a2.row and a1.col == a2.col
    assert a1.to_dict() == a2.to_dict()
    assert p1 == p2
