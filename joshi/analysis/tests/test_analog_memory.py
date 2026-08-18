from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from joshi_analysis.analog_memory import (
    DecisionRecord,
    DistanceSpec,
    FeatureObservation,
    FilterObservation,
    FilterSpec,
    MissingPolicy,
    OutcomeClosure,
    retrieve,
    reveal_outcomes,
    run_plain_filter,
)
from joshi_analysis.errors import ManifestError, TemporalLeakageError

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def feature(
    value: object, cutoff: int, *, status: str = "observed", **kwargs: object
) -> FeatureObservation:
    moment = BASE + timedelta(minutes=cutoff)
    kwargs.setdefault("ontology_version", "shape-v1")
    kwargs.setdefault("ontology_digest", "sha256:" + "a" * 64)
    kwargs.setdefault("identity_version", "subject-v1")
    kwargs.setdefault("identity_digest", "sha256:" + "b" * 64)
    return FeatureObservation(
        status=status,
        value=value if status == "observed" else None,
        known_at=moment,
        available_at=moment,
        **kwargs,
    )


def record(
    name: str, cutoff: int, shape: object, *, territory: str = "a", **kwargs: object
) -> DecisionRecord:
    return DecisionRecord(
        decision_id=name,
        subject_id=f"subject-{name}",
        decision_cutoff=BASE + timedelta(minutes=cutoff),
        features={"shape": feature(shape, cutoff - 1, **kwargs)},
        filters={
            "territory": FilterObservation(
                value=territory,
                known_at=BASE + timedelta(minutes=cutoff - 1),
                available_at=BASE + timedelta(minutes=cutoff - 1),
                ontology_version="territory-v1",
                ontology_digest="sha256:" + "1" * 64,
                identity_version="subject-v1",
                identity_digest="sha256:" + "2" * 64,
            )
        },
    )


def spec(policy: MissingPolicy = MissingPolicy.SKIP) -> DistanceSpec:
    return DistanceSpec("shape-distance", "1", {"shape": Decimal("1")}, policy, Decimal("10"))


def test_retrieval_is_earlier_decomposed_and_deterministic() -> None:
    query = record("query", 100, 10)
    candidates = [record("b", 20, 11), record("a", 20, 11), record("late", 101, 9)]
    with pytest.raises(TemporalLeakageError, match="strictly earlier"):
        retrieve(query, candidates, spec())
    result = retrieve(query, candidates[:2], spec(), limit=2)
    assert result.status == "neighbors"
    assert [neighbor.decision_id for neighbor in result.neighbors] == ["a", "b"]
    assert result.neighbors[0].components == {"shape": Decimal("1")}
    assert result.neighbors[0].decision_cutoff < result.query_cutoff
    assert (
        result.canonical_bytes()
        == retrieve(query, candidates[:2], spec(), limit=2).canonical_bytes()
    )


def test_missing_gap_policy_and_none_analogous_are_explicit() -> None:
    query = record("query", 100, 10)
    gap = record("gap", 20, 10, status="gap", gap_id="gap-1")
    skipped = retrieve(query, [gap], spec(MissingPolicy.SKIP))
    assert skipped.status == "none_analogous"
    assert skipped.neighbors == ()
    excluded = retrieve(query, [gap], spec(MissingPolicy.EXCLUDE))
    assert excluded.status == "none_analogous"
    observed = retrieve(query, [gap], spec(MissingPolicy.PENALIZE))
    assert observed.neighbors[0].components == {"shape": Decimal("10")}
    assert observed.neighbors[0].missing_components == ("shape",)


def test_future_availability_ontology_identity_and_outcome_features_refuse() -> None:
    query = record("query", 100, 10)
    future = record("future-feature", 100, 10, ontology_effective_at=BASE + timedelta(minutes=101))
    with pytest.raises(TemporalLeakageError):
        retrieve(query, [future], spec())
    outcome = record("outcome-derived", 20, 10, outcome_derived=True)
    with pytest.raises(TemporalLeakageError, match="outcome-derived"):
        retrieve(query, [outcome], spec())


def test_plain_filter_baseline_and_retrospective_reveal_are_separate() -> None:
    query = record("query", 100, 10, territory="a")
    candidates = [record("c", 20, 10, territory="a"), record("d", 30, 10, territory="b")]
    baseline = run_plain_filter(
        query,
        candidates,
        FilterSpec(
            "territory-filter",
            {"territory": query.filters["territory"]},
            version="1",
            as_known_cutoff=query.decision_cutoff,
        ),
    )
    assert baseline.candidate_ids == ("c",)
    analog = retrieve(query, candidates, spec())
    reveal = reveal_outcomes(
        analog,
        {
            "c": OutcomeClosure(
                status="matured",
                known_at=BASE + timedelta(minutes=101),
                maturity_at=BASE + timedelta(minutes=102),
                outcome_digest="sha256:" + "3" * 64,
                evidence_digest="sha256:" + "4" * 64,
            ),
            "d": OutcomeClosure(
                status="missing",
                known_at=BASE + timedelta(minutes=101),
                maturity_at=BASE + timedelta(minutes=102),
                reason="censored",
            ),
        },
        reveal_id="reveal-1",
        revealed_at=BASE + timedelta(minutes=103),
    )
    assert reveal.source_artifact_digest == analog.digest
    assert reveal.outcomes[0][0] == "c"
    assert reveal.outcomes[0][1].status == "matured"
    assert "profit_target" not in analog.canonical_bytes().decode()
    with pytest.raises(ManifestError, match="exactly match"):
        reveal_outcomes(
            analog,
            {},
            reveal_id="reveal-missing",
            revealed_at=BASE + timedelta(minutes=103),
        )
    with pytest.raises(ManifestError, match="exactly match"):
        reveal_outcomes(
            analog,
            {
                "c": reveal.outcomes[0][1],
                "d": reveal.outcomes[1][1],
                "not-a-neighbor": reveal.outcomes[0][1],
            },
            reveal_id="reveal-extra",
            revealed_at=BASE + timedelta(minutes=103),
        )
    future_known = OutcomeClosure(
        status="matured",
        known_at=BASE + timedelta(minutes=104),
        maturity_at=BASE + timedelta(minutes=105),
        outcome_digest="sha256:" + "5" * 64,
        evidence_digest="sha256:" + "6" * 64,
    )
    with pytest.raises(TemporalLeakageError, match="precedes outcome knowledge"):
        reveal_outcomes(
            analog,
            {"c": future_known, "d": reveal.outcomes[1][1]},
            reveal_id="reveal-future-known",
            revealed_at=BASE + timedelta(minutes=103),
        )
    future_maturity = OutcomeClosure(
        status="matured",
        known_at=BASE + timedelta(minutes=102),
        maturity_at=BASE + timedelta(minutes=104),
        outcome_digest="sha256:" + "7" * 64,
        evidence_digest="sha256:" + "8" * 64,
    )
    with pytest.raises(TemporalLeakageError, match="precedes outcome maturity"):
        reveal_outcomes(
            analog,
            {"c": future_maturity, "d": reveal.outcomes[1][1]},
            reveal_id="reveal-future-maturity",
            revealed_at=BASE + timedelta(minutes=103),
        )


def test_naive_time_and_malformed_feature_fail_closed() -> None:
    bad_query = DecisionRecord("q", "s", datetime(2026, 1, 1), {"shape": feature(1, 1)})
    with pytest.raises(ManifestError, match="timezone-aware"):
        bad_query.validate()
    malformed = FeatureObservation("observed", None, BASE, BASE)
    with pytest.raises(ManifestError, match="observed feature"):
        malformed.as_dict()
    with pytest.raises(ManifestError, match="version and digest are required"):
        FeatureObservation("observed", 1, BASE, BASE).as_dict()


def test_identity_numeric_and_gap_contracts_fail_closed() -> None:
    query = record("query", 100, 10)
    with pytest.raises(ManifestError, match="duplicate decision identity"):
        retrieve(query, [record("dup", 20, 1), record("dup", 21, 2)], spec())
    with pytest.raises(ManifestError, match="boolean"):
        retrieve(query, [record("bool", 20, True)], spec())
    with pytest.raises(ManifestError, match="nonzero"):
        retrieve(query, [record("zero", 20, 1)], DistanceSpec("d", "1", {"shape": 0}))
    with pytest.raises(ManifestError, match="gap state"):
        FeatureObservation("missing", None, BASE, BASE, gap_closed=True).as_dict()
    assert FeatureObservation(
        "gap",
        None,
        BASE,
        BASE,
        gap_id="gap-closed",
        gap_closed=True,
        gap_closed_at=BASE,
        ontology_version="shape-v1",
        ontology_digest="sha256:" + "a" * 64,
        identity_version="subject-v1",
        identity_digest="sha256:" + "b" * 64,
    ).as_dict()["gap_closed"]


def test_typed_outcome_closure_requires_maturity_and_digest() -> None:
    with pytest.raises(ManifestError, match="requires maturity_at"):
        OutcomeClosure("matured", BASE).as_dict()
    with pytest.raises(ManifestError, match="sha256"):
        OutcomeClosure("matured", BASE, BASE, "not-a-digest", "sha256:" + "1" * 64).as_dict()


def test_reveal_partitions_neighbors_into_all_typed_closures() -> None:
    query = record("query", 100, 10)
    candidates = [
        record("matured", 20, 10),
        record("missing", 21, 10),
        record("conflicting", 22, 10),
        record("censored", 23, 10),
    ]
    analog = retrieve(query, candidates, spec(), limit=4)
    reveal = reveal_outcomes(
        analog,
        {
            "matured": OutcomeClosure(
                "matured", BASE + timedelta(minutes=101), BASE + timedelta(minutes=102),
                "sha256:" + "3" * 64, "sha256:" + "4" * 64,
            ),
            "missing": OutcomeClosure(
                "missing", BASE + timedelta(minutes=101), BASE + timedelta(minutes=102),
                reason="provider did not retain the observation",
            ),
            "conflicting": OutcomeClosure(
                "conflicting", BASE + timedelta(minutes=101), BASE + timedelta(minutes=102),
                reason="independent sources disagree",
                conflicting_evidence_digests=("sha256:" + "5" * 64, "sha256:" + "6" * 64),
            ),
            "censored": OutcomeClosure(
                "censored", BASE + timedelta(minutes=101), BASE + timedelta(minutes=102),
                reason="registered horizon ended before observation",
            ),
        },
        reveal_id="reveal-partition",
        revealed_at=BASE + timedelta(minutes=103),
    )
    assert [closure.status for _, closure in reveal.outcomes] == [
        "censored", "conflicting", "matured", "missing",
    ]
    assert b'"mode":"decision"' not in reveal.canonical_bytes()
    with pytest.raises(ManifestError, match="at least two evidence"):
        OutcomeClosure(
            "conflicting",
            BASE,
            BASE,
            reason="one source",
            conflicting_evidence_digests=("sha256:" + "7" * 64,),
        ).as_dict()
    with pytest.raises(ManifestError, match="requires maturity_at"):
        OutcomeClosure("missing", BASE, reason="not observed").as_dict()
