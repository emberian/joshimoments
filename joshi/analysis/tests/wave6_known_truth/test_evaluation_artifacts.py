from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from joshi_analysis.canonical import canonical_json_bytes
from joshi_analysis.errors import ManifestError
from joshi_analysis.wave6_known_truth import (
    CandidateResult,
    ProtocolCandidateResult,
    StructuralCandidateResult,
    build_protocol_known_truth_battery,
    build_signed_flow_known_truth_suite,
    build_structural_known_truth_battery,
    evaluate_candidate_suite,
    evaluate_protocol_candidate,
    evaluate_structural_candidate,
    parse_known_truth_evaluation_exact,
    parse_protocol_evaluation_exact,
    parse_structural_evaluation_exact,
)
from joshi_analysis.wave6_known_truth.lab import derive_truth

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "fixtures/wave6/artifacts"
PUMP_FIXTURE = ROOT / "fixtures/protocol/pump_quotes.json"
DLMM_FIXTURE = ROOT / "fixtures/protocol/dlmm.json"
STRUCTURAL_FIXTURE = ROOT / "fixtures/wave6/structural_known_truth_v1.json"


def _evaluations():
    suite = build_signed_flow_known_truth_suite()
    generic_results = tuple(CandidateResult.build(case, derive_truth(case)) for case in suite.cases)
    generic = evaluate_candidate_suite(suite, "candidate:exact-reference", generic_results)

    protocol_battery = build_protocol_known_truth_battery(
        PUMP_FIXTURE.read_bytes(), DLMM_FIXTURE.read_bytes()
    )
    protocol_results = tuple(ProtocolCandidateResult.build(case) for case in protocol_battery.cases)
    protocol = evaluate_protocol_candidate(
        protocol_battery,
        "candidate:python-protocol-exact-reference",
        protocol_results,
    )

    structural_battery = build_structural_known_truth_battery(STRUCTURAL_FIXTURE.read_bytes())
    structural_results = tuple(
        StructuralCandidateResult.build(case) for case in structural_battery.cases
    )
    structural = evaluate_structural_candidate(
        structural_battery,
        "candidate:python-structural-exact-reference",
        structural_results,
    )
    return generic, protocol, structural


def test_generated_evaluations_equal_checked_exact_artifacts_and_reparse() -> None:
    generic, protocol, structural = _evaluations()
    cases = (
        (
            generic,
            ARTIFACTS / "known_truth_evaluation_v1.json",
            parse_known_truth_evaluation_exact,
        ),
        (
            protocol,
            ARTIFACTS / "protocol_known_truth_evaluation_v1.json",
            parse_protocol_evaluation_exact,
        ),
        (
            structural,
            ARTIFACTS / "structural_known_truth_evaluation_v1.json",
            parse_structural_evaluation_exact,
        ),
    )
    for evaluation, path, parser in cases:
        assert evaluation.exact_bytes() == path.read_bytes()
        assert parser(path.read_bytes()) == evaluation
        assert len(evaluation.result_digests) == len(evaluation.passed_case_ids)


@pytest.mark.parametrize(
    ("filename", "parser"),
    (
        ("known_truth_evaluation_v1.json", parse_known_truth_evaluation_exact),
        ("protocol_known_truth_evaluation_v1.json", parse_protocol_evaluation_exact),
        ("structural_known_truth_evaluation_v1.json", parse_structural_evaluation_exact),
    ),
)
def test_exact_parsers_refuse_unknown_duplicate_noncanonical_and_digest_substitution(
    filename, parser
) -> None:
    exact = (ARTIFACTS / filename).read_bytes()
    with pytest.raises(ManifestError, match="fields"):
        parser(exact[:-2] + b',"durable_receipt":"forged"}\n')
    with pytest.raises(ManifestError, match="duplicate"):
        parser(exact.replace(b'{', b'{"authority":"duplicate",', 1))
    with pytest.raises(ManifestError, match="canonical"):
        parser(exact.replace(b'{', b'{ ', 1))
    document = json.loads(exact)
    document["evaluation_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ManifestError, match="self-digest"):
        parser(canonical_json_bytes(document, newline=True))


def test_evaluation_objects_refuse_result_membership_and_source_digest_substitution() -> None:
    generic, protocol, structural = _evaluations()
    with pytest.raises(ManifestError, match="one result digest"):
        replace(generic, result_digests=generic.result_digests[:-1])
    with pytest.raises(ManifestError, match="fixture or authority"):
        replace(protocol, pump_fixture_digest="sha256:" + "0" * 64)
    with pytest.raises(ManifestError, match="fixture or authority"):
        replace(structural, fixture_digest="sha256:" + "0" * 64)
