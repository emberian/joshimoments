from __future__ import annotations

from dataclasses import replace

import pytest

from joshi_analysis.errors import ManifestError
from joshi_analysis.wave6_known_truth import (
    AdversaryKind,
    CandidateDisposition,
    CandidateResult,
    build_signed_flow_known_truth_suite,
    evaluate_candidate_suite,
)
from joshi_analysis.wave6_known_truth.lab import AUTHORITY, derive_truth, validate_candidate_result


def _suite_results():
    suite = build_signed_flow_known_truth_suite()
    return suite, tuple(CandidateResult.build(case, derive_truth(case)) for case in suite.cases)


def test_suite_contains_every_required_adversary_and_passes_exact_candidate() -> None:
    suite, results = _suite_results()
    assert {case.adversary for case in suite.cases} == set(AdversaryKind)
    evaluation = evaluate_candidate_suite(suite, "candidate:exact-reference", results)
    assert evaluation.passed_case_ids == tuple(case.case_id for case in suite.cases)
    assert evaluation.authority == AUTHORITY
    assert evaluation.evaluation_digest.startswith("sha256:")


def test_exact_recovery_shortcut_and_wide_atoms_remain_integer_exact() -> None:
    suite = build_signed_flow_known_truth_suite()
    expectations = {case.adversary: derive_truth(case) for case in suite.cases}
    assert expectations[AdversaryKind.IDENTIFIABLE_RECOVERY].exact_atoms == 8
    assert expectations[AdversaryKind.SHORTCUT_TRAP].exact_atoms == -7
    assert expectations[AdversaryKind.UNIT_GAUGE_WIDE_ATOM].exact_atoms == 2**54 + 4
    assert isinstance(expectations[AdversaryKind.UNIT_GAUGE_WIDE_ATOM].exact_atoms, int)


def test_nonidentifiability_requires_the_full_compatible_set() -> None:
    suite = build_signed_flow_known_truth_suite()
    case = next(case for case in suite.cases if case.adversary == AdversaryKind.NONIDENTIFIABILITY)
    expectation = derive_truth(case)
    assert expectation.disposition == CandidateDisposition.IDENTIFIED_SET
    assert expectation.compatible_atoms == (5, 11)
    candidate = CandidateResult.build(case, expectation, compatible_atoms=(5,))
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_candidate_result(case, candidate)


def test_malformed_future_row_is_inert_and_future_use_refuses() -> None:
    suite = build_signed_flow_known_truth_suite()
    case = next(case for case in suite.cases if case.adversary == AdversaryKind.FUTURE_LEAKAGE)
    expectation = derive_truth(case)
    assert expectation.exact_atoms == 3
    assert expectation.used_evidence_ids == ("ev-04-known",)
    assert expectation.excluded_evidence_ids == ()
    without_future = replace(
        case,
        evidence=tuple(row for row in case.evidence if row.evidence_id == "ev-04-known"),
    )
    assert without_future.input_manifest_digest == case.input_manifest_digest
    assert derive_truth(without_future) == expectation
    candidate = CandidateResult.build(
        case,
        expectation,
        used_evidence_ids=("ev-04-future-malformed", "ev-04-known"),
    )
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_candidate_result(case, candidate)


def test_coverage_gap_refuses_instead_of_becoming_zero() -> None:
    suite = build_signed_flow_known_truth_suite()
    case = next(
        case for case in suite.cases if case.adversary == AdversaryKind.COVERAGE_BIRTH_DEATH
    )
    expectation = derive_truth(case)
    assert expectation.disposition == CandidateDisposition.REFUSED
    assert expectation.exact_atoms is None
    assert expectation.refusal_reasons == ("coverage_gap:gap:hot-scope-death",)
    candidate = CandidateResult.build(case, expectation)
    cheated = replace(
        candidate,
        disposition=CandidateDisposition.EXACT_RECOVERY,
        exact_atoms=0,
        refusal_reasons=(),
    )
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_candidate_result(case, cheated)


def test_topology_and_reflexive_policy_epochs_cannot_be_pooled() -> None:
    suite = build_signed_flow_known_truth_suite()
    by_kind = {case.adversary: derive_truth(case) for case in suite.cases}
    topology = by_kind[AdversaryKind.TOPOLOGY_CHANGE]
    reflexive = by_kind[AdversaryKind.REFLEXIVE_POLICY_CHANGE]
    assert topology.exact_atoms == 4
    assert topology.excluded_evidence_ids == ("ev-06-other-topology",)
    assert reflexive.exact_atoms == 2
    assert reflexive.excluded_evidence_ids == ("ev-08-policy-induced",)


def test_result_digest_cut_and_authority_are_recomputed() -> None:
    suite = build_signed_flow_known_truth_suite()
    case = suite.cases[0]
    candidate = CandidateResult.build(case, derive_truth(case))
    with pytest.raises(ManifestError, match="digest mismatch"):
        validate_candidate_result(case, replace(candidate, result_digest="sha256:" + "0" * 64))
    with pytest.raises(ManifestError, match="changed its cut or authority"):
        validate_candidate_result(case, replace(candidate, authority="store_resolved"))


def test_candidate_must_report_every_case_exactly_once() -> None:
    suite, results = _suite_results()
    with pytest.raises(ManifestError, match="every suite case exactly once"):
        evaluate_candidate_suite(suite, "candidate:missing", results[:-1])
    with pytest.raises(ManifestError, match="every suite case exactly once"):
        evaluate_candidate_suite(suite, "candidate:duplicate", (*results, results[0]))
