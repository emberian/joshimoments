from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from joshi_analysis.errors import ManifestError
from joshi_analysis.wave6_known_truth import (
    STRUCTURAL_BATTERY_AUTHORITY,
    STRUCTURAL_FIXTURE_DIGEST,
    StructuralAdversaryKind,
    StructuralCandidateResult,
    StructuralOutput,
    StructuralTruthCase,
    StructuralValueKind,
    build_structural_known_truth_battery,
    derive_identity_revision_at_cut,
    evaluate_structural_candidate,
    validate_structural_candidate_result,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/wave6/structural_known_truth_v1.json"


def _battery():
    return build_structural_known_truth_battery(FIXTURE.read_bytes())


def _by_kind():
    return {case.adversary: case for case in _battery().cases}


def _outputs(kind: StructuralAdversaryKind) -> dict[str, str]:
    return {output.name: output.value for output in _by_kind()[kind].exact_outputs}


def test_battery_closes_all_structural_cases_and_exact_candidate() -> None:
    battery = _battery()
    assert battery.fixture_digest == STRUCTURAL_FIXTURE_DIGEST
    assert {case.adversary for case in battery.cases} == set(StructuralAdversaryKind)
    results = tuple(StructuralCandidateResult.build(case) for case in battery.cases)
    evaluation = evaluate_structural_candidate(
        battery, "candidate:python-structural-exact-reference", results
    )
    assert evaluation.passed_case_ids == tuple(case.case_id for case in battery.cases)
    assert evaluation.authority == STRUCTURAL_BATTERY_AUTHORITY
    assert evaluation.suite_digest == battery.suite_digest
    assert evaluation.evaluation_digest.startswith("sha256:")


def test_migration_splices_separate_gauges_instead_of_direct_subtraction() -> None:
    outputs = _outputs(StructuralAdversaryKind.MIGRATION_SPLICE)
    assert outputs == {
        "curve_delta_quote_atoms": "50",
        "naive_cross_gauge_delta_quote_atoms": "-80",
        "pool_delta_quote_atoms": "20",
        "spliced_delta_quote_atoms": "70",
    }
    assert outputs["spliced_delta_quote_atoms"] != outputs["naive_cross_gauge_delta_quote_atoms"]


def test_same_slot_uses_transaction_index_and_retains_unindexed_compatible_set() -> None:
    outputs = _outputs(StructuralAdversaryKind.SAME_SLOT_REORDER)
    # Input rows are lexical a,z while chain order is z,a. Sorting by display ID gives the reverse
    # branch and demonstrably changes both per-event allocation and the final rounded state.
    assert outputs["observed_first_event_id"] == "z-focal"
    assert (
        outputs["observed_z_focal_output_atoms"],
        outputs["observed_a_competing_output_atoms"],
        outputs["observed_final_quote_reserve_atoms"],
    ) == ("91", "140", "769")
    assert (
        outputs["reverse_z_focal_output_atoms"],
        outputs["reverse_a_competing_output_atoms"],
        outputs["reverse_final_quote_reserve_atoms"],
    ) == ("65", "167", "768")
    assert outputs["unindexed_disposition"] == "compatible_set"
    assert outputs["unindexed_outcome_count"] == "2"
    assert outputs["compatible_order_1_digest"] != outputs["compatible_order_2_digest"]


def test_identity_revision_is_as_known_and_future_payload_cannot_rewrite_early_cut() -> None:
    document = json.loads(FIXTURE.read_bytes())
    scenario = next(row for row in document["scenarios"] if row["id"] == "identity-revision")
    revisions = scenario["revisions"]
    early = derive_identity_revision_at_cut(
        revisions,
        scenario["wallet_id"],
        scenario["cuts"]["early"]["available_at"],
        scenario["cuts"]["early"]["commit_seq"],
    )
    without_future = derive_identity_revision_at_cut(
        revisions[:1],
        scenario["wallet_id"],
        scenario["cuts"]["early"]["available_at"],
        scenario["cuts"]["early"]["commit_seq"],
    )
    malformed_future = [revisions[0], revisions[1] | {"entity_id": "\x00future"}]
    with_malformed_future = derive_identity_revision_at_cut(
        malformed_future,
        scenario["wallet_id"],
        scenario["cuts"]["early"]["available_at"],
        scenario["cuts"]["early"]["commit_seq"],
    )
    assert early == without_future == with_malformed_future
    with pytest.raises(ManifestError, match="identity entity_id"):
        derive_identity_revision_at_cut(
            malformed_future,
            scenario["wallet_id"],
            scenario["cuts"]["late"]["available_at"],
            scenario["cuts"]["late"]["commit_seq"],
        )
    outputs = _outputs(StructuralAdversaryKind.IDENTITY_REVISION)
    assert outputs["early_entity_id"] == "entity-alpha"
    assert outputs["late_entity_id"] == "entity-beta"
    assert outputs["early_input_digest"] != outputs["late_input_digest"]


def test_fixture_bytes_and_expected_truth_cannot_be_substituted() -> None:
    mutated = FIXTURE.read_bytes().replace(
        b'"spliced_delta_quote_atoms":"70"',
        b'"spliced_delta_quote_atoms":"71"',
        1,
    )
    with pytest.raises(ManifestError, match="frozen N01 digest"):
        build_structural_known_truth_battery(mutated)
    noncanonical = FIXTURE.read_bytes().replace(b'"authority":', b'"authority" :', 1)
    with pytest.raises(ManifestError, match="frozen N01 digest"):
        build_structural_known_truth_battery(noncanonical)


def test_candidate_refuses_output_authority_digest_and_case_set_substitution() -> None:
    battery = _battery()
    results = tuple(StructuralCandidateResult.build(case) for case in battery.cases)
    case = battery.cases[0]
    changed = list(case.exact_outputs)
    changed[0] = replace(changed[0], value="51")
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_structural_candidate_result(
            case, StructuralCandidateResult.build(case, exact_outputs=tuple(changed))
        )
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_structural_candidate_result(
            case, replace(results[0], authority="store_resolved_identity_truth")
        )
    with pytest.raises(ManifestError, match="result digest mismatch"):
        validate_structural_candidate_result(
            case, replace(results[0], result_digest="sha256:" + "0" * 64)
        )
    with pytest.raises(ManifestError, match="every case exactly once"):
        evaluate_structural_candidate(battery, "candidate:missing", results[:-1])
    with pytest.raises(ManifestError, match="every case exactly once"):
        evaluate_structural_candidate(battery, "candidate:duplicate", (*results, results[0]))


def test_output_carriers_and_case_identity_are_strict() -> None:
    case = _battery().cases[0]
    with pytest.raises(ManifestError, match="canonical decimal"):
        StructuralOutput("atoms", StructuralValueKind.DECIMAL_INTEGER, "01")
    with pytest.raises(ManifestError, match="canonical decimal"):
        StructuralOutput("atoms", StructuralValueKind.DECIMAL_INTEGER, True)  # type: ignore[arg-type]
    with pytest.raises(ManifestError, match="digest output"):
        StructuralOutput("digest", StructuralValueKind.SHA256, "sha256:" + "A" * 64)
    duplicate = StructuralTruthCase.build(
        "structural-case-04-duplicate",
        case.adversary,
        case.fixture_ids,
        case.exact_outputs,
        case.negative_control_id,
        case.falsifier,
    )
    with pytest.raises(ManifestError, match="every adversary exactly once"):
        replace(_battery(), cases=(*_battery().cases, duplicate))
