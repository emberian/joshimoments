from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from joshi_analysis.errors import ManifestError
from joshi_analysis.wave6_known_truth import (
    DOMAIN_BATTERY_AUTHORITY,
    DomainAdversaryKind,
    DomainCandidateResult,
    DomainOutput,
    DomainTruthCase,
    DomainValueKind,
    build_domain_known_truth_battery,
    derive_exit_reentry_at_cut,
    evaluate_domain_candidate,
    parse_domain_evaluation_exact,
    validate_domain_candidate_result,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "fixtures/wave6/artifacts/domain_known_truth_evaluation_v1.json"


def _battery():
    return build_domain_known_truth_battery()


def _by_kind():
    return {case.adversary: case for case in _battery().cases}


def _outputs(kind: DomainAdversaryKind) -> dict[str, str]:
    return {output.name: output.value for output in _by_kind()[kind].exact_outputs}


def test_battery_closes_all_seven_domain_adversaries_and_exact_candidate() -> None:
    battery = _battery()
    assert {case.adversary for case in battery.cases} == set(DomainAdversaryKind)
    assert len(battery.cases) == 7
    results = tuple(DomainCandidateResult.build(case) for case in battery.cases)

    evaluation = evaluate_domain_candidate(
        battery,
        "candidate:python-domain-exact-reference",
        results,
    )

    assert evaluation.passed_case_ids == tuple(case.case_id for case in battery.cases)
    assert evaluation.authority == DOMAIN_BATTERY_AUTHORITY
    assert evaluation.suite_digest == battery.suite_digest
    assert evaluation.evaluation_digest.startswith("sha256:")
    assert evaluation.exact_bytes().endswith(b"\n")
    assert evaluation.exact_bytes() == ARTIFACT.read_bytes()
    assert parse_domain_evaluation_exact(evaluation.exact_bytes()) == evaluation

    duplicate = evaluation.exact_bytes().replace(
        b'"suite_id":',
        b'"suite_id":"duplicate","suite_id":',
        1,
    )
    with pytest.raises(ManifestError, match="duplicate evaluation artifact JSON key"):
        parse_domain_evaluation_exact(duplicate)
    noncanonical = evaluation.exact_bytes().replace(b'"suite_id":', b'"suite_id" :', 1)
    with pytest.raises(ManifestError, match="not exact canonical JSON"):
        parse_domain_evaluation_exact(noncanonical)


def test_venue_profile_and_same_chart_cases_refuse_silent_mechanism_transfer() -> None:
    venue = _outputs(DomainAdversaryKind.VENUE_PROFILE_TRANSFER)
    assert venue == {
        "compatible_profile_count": "2",
        "cpmm_output_atoms": "90",
        "disposition": "profile_specific_outputs",
        "fixed_bin_output_atoms": "99",
    }

    chart = _outputs(DomainAdversaryKind.SAME_CHART_DIFFERENT_MECHANISM)
    assert chart["compatible_mechanism_count"] == "2"
    assert chart["mechanism_disposition"] == "compatible_set"
    assert chart["mechanism_1_digest"] != chart["mechanism_2_digest"]
    assert chart["display_trace_digest"].startswith("sha256:")


def test_incomplete_platform_burst_retains_observed_mass_but_refuses_total() -> None:
    outputs = _outputs(DomainAdversaryKind.PLATFORM_WIDE_BURST)
    assert outputs == {
        "disposition": "refused_incomplete_platform_scope",
        "gap_count": "1",
        "observed_atoms": "9",
        "observed_event_count": "2",
    }


def test_operator_assertion_remains_raw_and_multivalued() -> None:
    outputs = _outputs(DomainAdversaryKind.OPERATOR_LABEL_INDUCTION)
    assert outputs["compatible_label_count"] == "2"
    assert outputs["label_1"] == "attention_rotation"
    assert outputs["label_2"] == "liquidity_hesitation"
    assert outputs["label_disposition"] == "ambiguous_not_truth_label"
    assert outputs["raw_assertion_digest"].startswith("sha256:")


def test_partial_runner_never_becomes_full_liquidation_or_terminal_value() -> None:
    outputs = _outputs(DomainAdversaryKind.RUNNER_LIQUIDATION_DIVERGENCE)
    assert outputs == {
        "disposed_atoms": "6",
        "episode_disposition": "partial_with_runner",
        "remaining_runner_atoms": "4",
        "terminal_value_disposition": "refused_missing_terminal_quote",
    }


def test_household_self_flow_is_removed_and_counterleg_retained() -> None:
    outputs = _outputs(DomainAdversaryKind.HOUSEHOLD_SELF_FLOW)
    assert outputs == {
        "external_household_flow_atoms": "0",
        "internal_counterleg_atoms": "12",
        "naive_self_fee_income_atoms": "2",
        "posting_disposition": "self_flow_removed_from_household_pnl",
    }


def test_future_reentry_does_not_rewrite_the_frozen_flat_cut() -> None:
    outputs = _outputs(DomainAdversaryKind.FROZEN_FUTURE_EXIT_REENTRY)
    assert outputs["early_inventory_atoms"] == "0"
    assert outputs["early_state"] == "watching_flat"
    assert outputs["early_inventory_epoch"] == "inventory-epoch-1"
    assert outputs["late_inventory_atoms"] == "7"
    assert outputs["late_state"] == "reentered_new_inventory_epoch"
    assert outputs["late_inventory_epoch"] == "inventory-epoch-2"
    assert outputs["early_input_digest"].startswith("sha256:")

    rows = (
        {
            "event_id": "inventory:exit",
            "available_at": datetime(2026, 8, 18, 12, 0, 1, tzinfo=UTC),
            "commit_seq": 1,
            "inventory_atoms": 0,
            "inventory_epoch": "inventory-epoch-1",
        },
        {
            "event_id": "inventory:reentry",
            "available_at": datetime(2026, 8, 18, 12, 0, 3, tzinfo=UTC),
            "commit_seq": 3,
            "inventory_atoms": "malformed-future",
            "inventory_epoch": "inventory-epoch-2",
        },
    )
    early_cut = datetime(2026, 8, 18, 12, 0, 2, tzinfo=UTC)
    late_cut = datetime(2026, 8, 18, 12, 0, 4, tzinfo=UTC)
    assert derive_exit_reentry_at_cut(rows, early_cut, 2)[0:2] == (0, "inventory-epoch-1")
    with pytest.raises(ManifestError, match="inventory must be exact nonnegative atoms"):
        derive_exit_reentry_at_cut(rows, late_cut, 4)


def test_candidate_output_authority_digest_and_case_set_substitution_refuse() -> None:
    battery = _battery()
    results = tuple(DomainCandidateResult.build(case) for case in battery.cases)
    case = battery.cases[0]
    changed = list(case.exact_outputs)
    changed[0] = replace(changed[0], value="3")
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_domain_candidate_result(
            case,
            DomainCandidateResult.build(case, exact_outputs=tuple(changed)),
        )
    with pytest.raises(ManifestError, match="differs from exact generated truth"):
        validate_domain_candidate_result(
            case,
            replace(results[0], authority="store_resolved_domain_truth"),
        )
    with pytest.raises(ManifestError, match="result digest mismatch"):
        validate_domain_candidate_result(
            case,
            replace(results[0], result_digest="sha256:" + "0" * 64),
        )
    with pytest.raises(ManifestError, match="every case exactly once"):
        evaluate_domain_candidate(battery, "candidate:missing", results[:-1])
    with pytest.raises(ManifestError, match="every case exactly once"):
        evaluate_domain_candidate(battery, "candidate:duplicate", (*results, results[0]))


def test_domain_output_carriers_and_suite_identity_are_strict() -> None:
    case = _battery().cases[0]
    with pytest.raises(ManifestError, match="canonical decimal"):
        DomainOutput("atoms", DomainValueKind.DECIMAL_INTEGER, "01")
    with pytest.raises(ManifestError, match="canonical decimal"):
        DomainOutput("atoms", DomainValueKind.DECIMAL_INTEGER, True)  # type: ignore[arg-type]
    with pytest.raises(ManifestError, match="sha256"):
        DomainOutput("digest", DomainValueKind.SHA256, "sha256:" + "A" * 64)
    duplicate = DomainTruthCase.build(
        "domain-case-08-duplicate",
        case.adversary,
        case.fixture_ids,
        case.exact_outputs,
        case.negative_control_id,
        case.falsifier,
    )
    with pytest.raises(ManifestError, match="every adversary exactly once"):
        replace(_battery(), cases=(*_battery().cases, duplicate))
