from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from joshi_analysis.errors import ManifestError
from joshi_analysis.wave6_known_truth import (
    DLMM_FIXTURE_DIGEST,
    PROTOCOL_BATTERY_AUTHORITY,
    PUMP_FIXTURE_DIGEST,
    ProtocolAdversaryKind,
    ProtocolCandidateResult,
    ProtocolCaseDisposition,
    ProtocolTruthCase,
    build_protocol_known_truth_battery,
    evaluate_protocol_candidate,
    validate_protocol_candidate_result,
)

ROOT = Path(__file__).resolve().parents[3]
PUMP_FIXTURE = ROOT / "fixtures/protocol/pump_quotes.json"
DLMM_FIXTURE = ROOT / "fixtures/protocol/dlmm.json"


def _battery():
    return build_protocol_known_truth_battery(
        PUMP_FIXTURE.read_bytes(), DLMM_FIXTURE.read_bytes()
    )


def _by_kind():
    return {case.adversary: case for case in _battery().cases}


def test_battery_closes_every_protocol_adversary_and_exact_candidate() -> None:
    battery = _battery()
    assert {case.adversary for case in battery.cases} == set(ProtocolAdversaryKind)
    assert battery.pump_fixture_digest == PUMP_FIXTURE_DIGEST
    assert battery.dlmm_fixture_digest == DLMM_FIXTURE_DIGEST
    results = tuple(ProtocolCandidateResult.build(case) for case in battery.cases)
    evaluation = evaluate_protocol_candidate(battery, "candidate:python-exact-reference", results)
    assert evaluation.passed_case_ids == tuple(case.case_id for case in battery.cases)
    assert evaluation.authority == PROTOCOL_BATTERY_AUTHORITY
    assert evaluation.suite_digest == battery.suite_digest
    assert evaluation.evaluation_digest.startswith("sha256:")


def test_pump_literal_plus_one_is_not_mathematical_ceil() -> None:
    case = _by_kind()[ProtocolAdversaryKind.PUMP_LITERAL_FLOOR_PLUS_ONE]
    outputs = dict(case.exact_outputs)
    assert outputs == {
        "floor_quotient": 500,
        "literal_floor_plus_one": 501,
        "mathematical_ceil": 500,
    }
    assert outputs["literal_floor_plus_one"] != outputs["mathematical_ceil"]


def test_pump_fee_components_round_separately() -> None:
    case = _by_kind()[ProtocolAdversaryKind.PUMP_SEPARATE_FEE_ROUNDING]
    outputs = dict(case.exact_outputs)
    assert outputs["protocol_fee_atoms"] == 6
    assert outputs["creator_fee_atoms"] == 3
    assert outputs["lp_fee_atoms"] == 0
    assert outputs["independent_fee_total"] == 9
    assert outputs["combined_fee_shortcut"] == 8


def test_virtual_reserves_never_replace_real_payout_capacity() -> None:
    cases = _by_kind()
    refused = cases[ProtocolAdversaryKind.PUMPSWAP_REAL_CAPACITY]
    assert refused.disposition == ProtocolCaseDisposition.TYPED_REFUSAL
    assert refused.refusal_reason == "insufficient_real_quote"
    refused_outputs = dict(refused.exact_outputs)
    assert refused_outputs["vault_debit_atoms"] > refused_outputs["real_quote_reserves"]

    retained = cases[ProtocolAdversaryKind.PUMPSWAP_LP_RETENTION]
    assert retained.disposition == ProtocolCaseDisposition.EXACT_RECOVERY
    retained_outputs = dict(retained.exact_outputs)
    assert retained_outputs["raw_quote_atoms"] == 101
    assert retained_outputs["lp_fee_atoms"] == 2
    assert retained_outputs["vault_debit_atoms"] == 99
    assert retained_outputs["vault_debit_atoms"] <= retained_outputs["real_quote_reserves"]


def test_dlmm_share_deposit_removal_and_claims_are_exact_and_separate() -> None:
    cases = _by_kind()
    position = dict(cases[ProtocolAdversaryKind.DLMM_POSITION_SHARE_FLOOR].exact_outputs)
    assert position == {"position_x_atoms": 250, "position_y_atoms": 500}

    deposit = dict(cases[ProtocolAdversaryKind.DLMM_DEPOSIT_SHARE_FLOOR].exact_outputs)
    assert deposit["deposit_share"] == 5_534_023_222_112_865_484_800
    assert deposit["existing_liquidity_q64"] > 2**64
    assert deposit["incoming_liquidity_q64"] > 2**64

    removal = dict(cases[ProtocolAdversaryKind.DLMM_REMOVAL_AND_CLAIMS].exact_outputs)
    assert removal["removed_share"] == 6_917_529_027_641_081_856_000
    assert (removal["removed_x_atoms"], removal["removed_y_atoms"]) == (125, 250)
    assert (
        removal["pending_fee_x_atoms_separate"],
        removal["pending_fee_y_atoms_separate"],
        removal["pending_reward_atoms_separate"],
    ) == (3, 4, 5)


def test_fixture_substitution_refuses_before_arithmetic() -> None:
    # Mutate one byte without making the document unparsable so the pinned raw-byte gate, rather
    # than JSON syntax, is exercised.
    pump = PUMP_FIXTURE.read_bytes().replace(
        b'"raw_quote_atoms": "501"', b'"raw_quote_atoms": "500"', 1
    )
    with pytest.raises(ManifestError, match="frozen N01 digest"):
        build_protocol_known_truth_battery(pump, DLMM_FIXTURE.read_bytes())

    dlmm = DLMM_FIXTURE.read_bytes().replace(
        b'"expected_position_x_atoms": "250"', b'"expected_position_x_atoms": "251"', 1
    )
    with pytest.raises(ManifestError, match="frozen N01 digest"):
        build_protocol_known_truth_battery(PUMP_FIXTURE.read_bytes(), dlmm)


def test_candidate_cannot_change_arithmetic_refusal_or_authority() -> None:
    battery = _battery()
    exact = battery.cases[0]
    changed_output = ProtocolCandidateResult.build(
        exact, exact_outputs=(("floor_quotient", 500), ("literal_floor_plus_one", 500))
    )
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_protocol_candidate_result(exact, changed_output)

    refusal = next(
        case for case in battery.cases if case.disposition == ProtocolCaseDisposition.TYPED_REFUSAL
    )
    changed_refusal = ProtocolCandidateResult.build(refusal, refusal_reason="success")
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_protocol_candidate_result(refusal, changed_refusal)

    result = ProtocolCandidateResult.build(exact)
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_protocol_candidate_result(exact, replace(result, authority="store_resolved"))


def test_candidate_requires_exact_case_set_and_digest() -> None:
    battery = _battery()
    results = tuple(ProtocolCandidateResult.build(case) for case in battery.cases)
    with pytest.raises(ManifestError, match="every case exactly once"):
        evaluate_protocol_candidate(battery, "candidate:missing", results[:-1])
    with pytest.raises(ManifestError, match="every case exactly once"):
        evaluate_protocol_candidate(battery, "candidate:duplicate", (*results, results[0]))
    with pytest.raises(ManifestError, match="result digest mismatch"):
        validate_protocol_candidate_result(
            battery.cases[0], replace(results[0], result_digest="sha256:" + "0" * 64)
        )


def test_truth_case_output_identity_cannot_branch() -> None:
    case = _battery().cases[0]
    with pytest.raises(ManifestError, match="output keys"):
        replace(case, exact_outputs=(("same", 1), ("same", 2)))
    with pytest.raises(ManifestError, match="truth case digest mismatch"):
        replace(case, truth_digest="sha256:" + "0" * 64)


def test_python_boolean_cannot_masquerade_as_one_atom() -> None:
    battery = _battery()
    case = battery.cases[1]
    outputs = list(case.exact_outputs)
    key, value = outputs[1]
    assert value == 3
    outputs[1] = (key, True)
    with pytest.raises(ManifestError, match="exact integer"):
        ProtocolCandidateResult.build(case, exact_outputs=tuple(outputs))


def test_suite_cannot_duplicate_one_adversary_under_a_fresh_case_id() -> None:
    battery = _battery()
    original = battery.cases[0]
    duplicate = ProtocolTruthCase.build(
        "protocol-case-08-duplicate-adversary",
        original.adversary,
        original.fixture_ids,
        original.disposition,
        original.exact_outputs,
        original.refusal_reason,
        original.negative_control_id,
        original.falsifier,
    )
    with pytest.raises(ManifestError, match="every adversary exactly once"):
        replace(battery, cases=(*battery.cases, duplicate))
