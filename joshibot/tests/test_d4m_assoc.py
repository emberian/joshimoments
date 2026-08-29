"""Hand-checked correctness for the D4M associative-array layer.

Every expected value here is written out by hand from a 3x4 or 4x4 example small enough to
verify on paper. A test that computes the expectation with the same code it is testing
proves only that the code is deterministic.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from dregg_d4m.assoc import (
    Assoc,
    AssocError,
    co_occurrence,
    cosine,
    jaccard,
    matmul,
    overlap_coeff,
    upper_pairs,
)

# The worked example, used by most tests below.
#
#        c1  c2  c3  c4
#   wA    1   1   1   .
#   wB    1   1   .   .
#   wC    .   .   1   1
#
# wA n wB = {c1, c2} -> 2;  wA n wC = {c3} -> 1;  wB n wC = {} -> 0
ROWS = ["wA", "wA", "wA", "wB", "wB", "wC", "wC"]
COLS = ["c1", "c2", "c3", "c1", "c2", "c3", "c4"]


def base() -> Assoc:
    return Assoc.from_tuples(ROWS, COLS)


def test_keys_are_sorted_and_round_trip():
    a = base()
    assert a.row == ("wA", "wB", "wC")
    assert a.col == ("c1", "c2", "c3", "c4")
    assert a.shape == (3, 4)
    assert a.nnz == 7
    assert a.row_set("wA") == {"c1", "c2", "c3"}
    assert a.row_set("wC") == {"c3", "c4"}
    assert a.to_dict()[("wB", "c2")] == 1.0
    assert ("wB", "c3") not in a.to_dict()


def test_explicit_key_lists_fix_the_index_and_reject_strangers():
    a = Assoc.from_tuples(ROWS, COLS, row_keys=["wC", "wB", "wA"], col_keys=list(["c1", "c2", "c3", "c4"]))
    assert a.row == ("wC", "wB", "wA")
    assert a.row_set("wA") == {"c1", "c2", "c3"}
    with pytest.raises(AssocError):
        Assoc.from_tuples(["wZ"], ["c1"], row_keys=["wA"], col_keys=["c1"])


def test_duplicate_aggregation_is_a_real_choice():
    rows, cols, vals = ["w", "w", "w"], ["c", "c", "c"], [3.0, 5.0, 1.0]
    assert Assoc.from_tuples(rows, cols, vals, agg="sum").to_dict()[("w", "c")] == 9.0
    assert Assoc.from_tuples(rows, cols, vals, agg="max").to_dict()[("w", "c")] == 5.0
    assert Assoc.from_tuples(rows, cols, vals, agg="min").to_dict()[("w", "c")] == 1.0
    assert Assoc.from_tuples(rows, cols, vals, agg="first").to_dict()[("w", "c")] == 3.0


def test_transpose_is_an_involution_on_keys_and_values():
    a = base()
    t = a.T
    assert t.row == a.col and t.col == a.row
    assert t.to_dict()[("c3", "wC")] == 1.0
    assert t.T.to_dict() == a.to_dict()


def test_degrees_and_sums_are_the_two_different_reductions():
    a = Assoc.from_tuples(["w", "w", "x"], ["c1", "c2", "c1"], [2.0, 3.0, 10.0])
    assert list(a.degree(axis="row")) == [2, 1]
    assert list(a.degree(axis="col")) == [2, 1]
    assert list(a.rowsum()) == [5.0, 10.0]
    assert list(a.colsum()) == [12.0, 3.0]


def test_selection_by_name_list_regex_and_predicate():
    a = base()
    assert a.select(rows="wB").row == ("wB",)
    assert a.select(rows=["wC", "wA"]).row == ("wC", "wA")  # caller order is honoured
    assert a.select(rows=["wA", "ghost"]).row == ("wA",)  # missing keys drop, never raise
    assert a.select(cols=re.compile(r"c[12]$")).col == ("c1", "c2")
    assert a.select(cols=lambda k: k.endswith("4")).col == ("c4",)
    sub = a.select(rows=["wA", "wC"], cols=re.compile("c3"))
    assert sub.shape == (2, 1)
    assert sub.to_dict() == {("wA", "c3"): 1.0, ("wC", "c3"): 1.0}


def test_restrict_degree_drops_the_promiscuous_row():
    a = base()
    assert a.restrict_degree(axis="row", max_degree=2).row == ("wB", "wC")
    # column degrees are c1:2 c2:2 c3:2 c4:1 -- only c4 survives a cap of 1
    assert a.restrict_degree(axis="col", max_degree=1).col == ("c4",)
    assert a.restrict_degree(axis="col", max_degree=2).col == ("c1", "c2", "c3", "c4")


def test_plus_times_product_counts_shared_columns():
    a = base()
    prod = matmul(a, a.T)
    got = prod.to_dict()
    assert got[("wA", "wA")] == 3.0
    assert got[("wA", "wB")] == 2.0
    assert got[("wA", "wC")] == 1.0
    assert ("wB", "wC") not in got


def test_inner_keys_must_match_not_merely_the_dimension():
    a = Assoc.from_tuples(["r"], ["x"])
    b = Assoc.from_tuples(["y"], ["c"])
    with pytest.raises(AssocError, match="inner keys differ"):
        matmul(a, b)


def test_or_and_semiring_reports_support_not_count():
    a = base()
    boolean = matmul(a, a.T, semiring="or_and")
    assert set(boolean.m.data) == {1.0}
    assert boolean.to_dict()[("wA", "wB")] == 1.0
    assert ("wB", "wC") not in boolean.to_dict()
    # same support as plus-times, different values -- that is the whole point
    assert set(boolean.to_dict()) == set(matmul(a, a.T).to_dict())


def test_max_plus_takes_the_strongest_chain_not_the_sum():
    #  A:  p->q 1.0, p->r 5.0      B:  q->z 5.0, r->z 1.0
    #  plus-times: 1*5 + 5*1 = 10 ; max-plus: max(1+5, 5+1) = 6
    a = Assoc.from_tuples(["p", "p"], ["q", "r"], [1.0, 5.0])
    b = Assoc.from_tuples(["q", "r"], ["z", "z"], [5.0, 1.0])
    assert matmul(a, b).to_dict()[("p", "z")] == 10.0
    assert matmul(a, b, semiring="max_plus").to_dict()[("p", "z")] == 6.0
    assert matmul(a, b, semiring="min_plus").to_dict()[("p", "z")] == 6.0
    c = Assoc.from_tuples(["q", "r"], ["z", "z"], [5.0, 9.0])
    assert matmul(a, c, semiring="max_plus").to_dict()[("p", "z")] == 14.0  # 5 + 9
    assert matmul(a, c, semiring="min_plus").to_dict()[("p", "z")] == 6.0  # 1 + 5


def test_max_plus_matches_a_dense_reference_on_a_random_sparse_case():
    rng = np.random.default_rng(20260829)
    da = (rng.random((7, 5)) < 0.4) * rng.random((7, 5))
    db = (rng.random((5, 6)) < 0.4) * rng.random((5, 6))
    rk = [f"r{i}" for i in range(7)]
    mk = [f"m{i}" for i in range(5)]
    ck = [f"c{i}" for i in range(6)]
    ri, ci = np.nonzero(da)
    a = Assoc.from_tuples([rk[i] for i in ri], [mk[j] for j in ci], da[ri, ci], row_keys=rk, col_keys=mk)
    ri, ci = np.nonzero(db)
    b = Assoc.from_tuples([mk[i] for i in ri], [ck[j] for j in ci], db[ri, ci], row_keys=mk, col_keys=ck)
    got = matmul(a, b, semiring="max_plus", chunk_rows=3).to_dict()
    for i in range(7):
        for j in range(6):
            ks = [k for k in range(5) if da[i, k] and db[k, j]]
            if not ks:
                assert (rk[i], ck[j]) not in got
            else:
                assert got[(rk[i], ck[j])] == pytest.approx(max(da[i, k] + db[k, j] for k in ks))


def test_max_plus_chunking_does_not_change_the_answer():
    rng = np.random.default_rng(7)
    d = (rng.random((40, 40)) < 0.15) * rng.random((40, 40))
    keys = [f"k{i}" for i in range(40)]
    ri, ci = np.nonzero(d)
    a = Assoc.from_tuples(
        [keys[i] for i in ri], [keys[j] for j in ci], d[ri, ci], row_keys=keys, col_keys=keys
    )
    one = matmul(a, a, semiring="max_plus", chunk_rows=1000).to_dict()
    many = matmul(a, a, semiring="max_plus", chunk_rows=3).to_dict()
    assert one == many


def test_co_occurrence_equals_the_plain_product_when_nothing_is_pruned():
    a = base()
    assert co_occurrence(a, axis="row", min_overlap=1).to_dict() == matmul(a, a.T).to_dict()
    assert co_occurrence(a, axis="col", min_overlap=1).to_dict() == matmul(a.T, a).to_dict()


def test_co_occurrence_pruning_drops_exactly_the_singleton_overlaps():
    a = base()
    pruned = co_occurrence(a, axis="row", min_overlap=2, chunk_rows=2).to_dict()
    assert pruned[("wA", "wB")] == 2.0
    assert pruned[("wA", "wA")] == 3.0
    assert ("wA", "wC") not in pruned  # they share only c3


def test_co_occurrence_chunking_is_invisible():
    a = base()
    assert co_occurrence(a, chunk_rows=1).to_dict() == co_occurrence(a, chunk_rows=99).to_dict()


def test_rectangular_co_occurrence_is_the_parity_shape():
    #  a query set against a stored corpus: one row, three candidates
    q = Assoc.from_tuples(["q", "q"], ["c1", "c3"], col_keys=["c1", "c2", "c3", "c4"])
    a = base()
    prod = co_occurrence(q, axis="row", other=a, min_overlap=1)
    assert prod.row == ("q",)
    assert prod.col == ("wA", "wB", "wC")
    assert prod.to_dict() == {("q", "wA"): 2.0, ("q", "wB"): 1.0, ("q", "wC"): 1.0}


def test_jaccard_is_the_ledgers_own_arithmetic():
    a = base()
    prod = co_occurrence(a, min_overlap=1)
    deg = a.degree(axis="row")  # [3, 2, 2]
    j = jaccard(prod, deg).to_dict()
    # wA n wB = 2, |wA| + |wB| - 2 = 3 + 2 - 2 = 3  ->  2/3
    assert j[("wA", "wB")] == pytest.approx(2 / 3)
    # wA n wC = 1, 3 + 2 - 1 = 4  ->  0.25
    assert j[("wA", "wC")] == pytest.approx(0.25)
    assert j[("wA", "wA")] == pytest.approx(1.0)


def test_overlap_and_cosine_are_the_other_two_normalisations():
    a = base()
    prod = co_occurrence(a, min_overlap=1)
    deg = a.degree(axis="row")
    assert overlap_coeff(prod, deg).to_dict()[("wA", "wB")] == pytest.approx(2 / 2)
    assert cosine(prod, deg).to_dict()[("wA", "wB")] == pytest.approx(2 / np.sqrt(3 * 2))


def test_jaccard_with_distinct_left_and_right_degrees():
    q = Assoc.from_tuples(["q", "q"], ["c1", "c3"], col_keys=["c1", "c2", "c3", "c4"])
    a = base()
    prod = co_occurrence(q, other=a, min_overlap=1)
    j = jaccard(prod, q.degree(axis="row"), a.degree(axis="row")).to_dict()
    assert j[("q", "wA")] == pytest.approx(2 / (2 + 3 - 2))
    assert j[("q", "wC")] == pytest.approx(1 / (2 + 2 - 1))


def test_drop_diagonal_and_upper_pairs():
    a = base()
    prod = co_occurrence(a, min_overlap=1).drop_diagonal()
    assert ("wA", "wA") not in prod.to_dict()
    i, j, v = upper_pairs(prod)
    assert sorted(zip(i.tolist(), j.tolist(), v.tolist(), strict=True)) == [(0, 1, 2.0), (0, 2, 1.0)]


def test_row_sets_round_trip_through_the_curveball_shape():
    a = base()
    sets = a.row_sets()
    assert sets == [{0, 1, 2}, {0, 1}, {2, 3}]
    back = Assoc.from_row_sets(sets, a.row, a.col)
    assert back.to_dict() == a.binarize().to_dict()


def test_binarize_keeps_support_and_flattens_weight():
    a = Assoc.from_tuples(["w", "w"], ["c1", "c2"], [7.0, -3.0])
    assert a.binarize().to_dict() == {("w", "c1"): 1.0, ("w", "c2"): 1.0}


def test_empty_selection_is_a_valid_empty_assoc():
    a = base()
    e = a.select(rows="nobody")
    assert e.shape == (0, 4)
    assert e.nnz == 0
    assert list(e.find()) == []


def test_max_min_is_the_bottleneck_semiring_and_differs_from_max_plus():
    #  p->q 0.11, p->r 0.55   q->z 0.99, r->z 0.54
    #  max-plus picks the q leg (0.11 + 0.99 = 1.10 > 0.55 + 0.54 = 1.09)
    #  max-min picks the r leg (min(0.55, 0.54) = 0.54 > min(0.11, 0.99) = 0.11)
    a = Assoc.from_tuples(["p", "p"], ["q", "r"], [0.11, 0.55])
    b = Assoc.from_tuples(["q", "r"], ["z", "z"], [0.99, 0.54])
    assert matmul(a, b, semiring="max_plus").to_dict()[("p", "z")] == pytest.approx(1.10)
    assert matmul(a, b, semiring="max_min").to_dict()[("p", "z")] == pytest.approx(0.54)


def test_max_min_matches_a_dense_reference():
    rng = np.random.default_rng(11)
    da = (rng.random((6, 5)) < 0.5) * rng.random((6, 5))
    db = (rng.random((5, 4)) < 0.5) * rng.random((5, 4))
    rk, mk, ck = [f"r{i}" for i in range(6)], [f"m{i}" for i in range(5)], [f"c{i}" for i in range(4)]
    ri, ci = np.nonzero(da)
    a = Assoc.from_tuples([rk[i] for i in ri], [mk[j] for j in ci], da[ri, ci], row_keys=rk, col_keys=mk)
    ri, ci = np.nonzero(db)
    b = Assoc.from_tuples([mk[i] for i in ri], [ck[j] for j in ci], db[ri, ci], row_keys=mk, col_keys=ck)
    got = matmul(a, b, semiring="max_min", chunk_rows=2).to_dict()
    for i in range(6):
        for j in range(4):
            ks = [k for k in range(5) if da[i, k] and db[k, j]]
            if ks:
                assert got[(rk[i], ck[j])] == pytest.approx(max(min(da[i, k], db[k, j]) for k in ks))
            else:
                assert (rk[i], ck[j]) not in got


def test_threshold_cuts_below_the_registered_value():
    from dregg_d4m.assoc import threshold

    a = Assoc.from_tuples(["w", "w", "w"], ["c1", "c2", "c3"], [0.09, 0.10, 0.5])
    assert set(threshold(a, 0.10).to_dict()) == {("w", "c2"), ("w", "c3")}


def test_unknown_semiring_is_refused():
    a = Assoc.from_tuples(["p"], ["q"])
    with pytest.raises(AssocError, match="unknown semiring"):
        matmul(a, a.T, semiring="tropical_vibes")  # type: ignore[arg-type]
