"""D0 -- the credibility gate: the algebra must agree with the shipped crew matcher.

If ``dregg_d4m`` disagrees with ``dregg_screen.ledger.Ledger.crew_match``, the algebra is
wrong and the instrument is right. These tests are the ones that decide it. They read the
SHIPPED artifact (``state/dregg_screen/ledger/current.sqlite``) read-only and skip cleanly
when it is absent, so a fresh checkout is not red for a reason nobody can fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dregg_d4m.assoc import Assoc, co_occurrence, jaccard

LEDGER = Path(__file__).resolve().parent.parent / "state" / "dregg_screen" / "ledger" / "current.sqlite"
needs_ledger = pytest.mark.skipif(not LEDGER.exists(), reason="shipped ledger artifact not built")


def test_the_jaccard_denominator_is_the_ledgers_union_arithmetic():
    """A hand-checked case pinning ``union = len(launch) + set_size - overlap``.

    Launch set {a, b, c, d}; stored set {a, b, x}. overlap 2, union 4 + 3 - 2 = 5, J = 0.4.
    Needs no ledger and no corpus -- if this drifts, every parity number below is noise."""

    q = Assoc.from_tuples(["q"] * 4, ["a", "b", "c", "d"], col_keys=["a", "b", "c", "d", "x"])
    stored = Assoc.from_tuples(["m"] * 3, ["a", "b", "x"], col_keys=["a", "b", "c", "d", "x"])
    prod = co_occurrence(q, other=stored, min_overlap=1.0)
    assert prod.to_dict()[("q", "m")] == 2.0
    j = jaccard(prod, q.degree(axis="row"), stored.degree(axis="row"))
    assert j.to_dict()[("q", "m")] == pytest.approx(0.4)


@needs_ledger
def test_untruncated_parity_is_exact_against_the_shipped_matcher():
    """The registered gate. Untruncated, ``crew_match`` is a pure function of the data, and
    the algebra must reproduce its overlap and Jaccard on every query coin."""

    from dregg_d4m import parity

    rep = parity.compare(n_query=150, seed=20260829)
    assert rep["arm1_n_disagree_numeric"] == 0, (
        f"the algebra disagrees with the shipped instrument on "
        f"{rep['arm1_n_disagree_numeric']} of {rep['n_query_coins']} query coins"
    )
    assert rep["arm1_untruncated_agreement_numeric"] == 1.0
    assert rep["n_matched_by_ledger"] > 0, "a parity run that matched nothing proves nothing"
    assert rep["n_only_ledger_matched"] == 0
    assert rep["n_only_algebra_matched"] == 0


@needs_ledger
def test_the_query_coins_are_genuinely_unseen_by_the_ledger():
    """Parity against coins the ledger stores would be flattered by a self-match at J = 1."""

    from dregg_d4m import graphs, parity

    lg, _meta, _crew = graphs.ledger_crew_sets()
    _q, _sizes, mints = parity.build_query_matrices(120, 20260829, stored=lg.a)
    assert mints, "no eligible query coins"
    assert not (set(mints) & set(lg.a.row))


@needs_ledger
def test_the_shipped_limit_is_measured_not_assumed():
    """``ORDER BY overlap DESC LIMIT 200`` has no tiebreaker and overlap order is not Jaccard
    order. Whether that costs anything is a measurement; this pins that it is measured."""

    from dregg_d4m import parity

    rep = parity.compare(n_query=150, seed=20260829)
    assert "truncation_changed_answer" in rep
    assert "n_over_the_limit" in rep
    assert rep["max_candidates_seen"] >= rep["thresholds"]["max_candidates"] or (
        rep["n_over_the_limit"] == 0
    )


@needs_ledger
def test_parity_is_deterministic_across_runs():
    from dregg_d4m import parity

    a = parity.compare(n_query=60, seed=20260829)
    b = parity.compare(n_query=60, seed=20260829)
    a.pop("ledger_meta"), b.pop("ledger_meta")
    assert a == b
