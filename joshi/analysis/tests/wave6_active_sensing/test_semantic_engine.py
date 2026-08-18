from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from joshi_analysis.wave6_active_sensing import (
    AssignmentKind,
    BaselineClosureV1,
    BaselineEpochRegistrationV1,
    BudgetEnvelope,
    BudgetReservation,
    BudgetVector,
    CoverageSupportReportV1,
    ExperimentEpochRegistrationV1,
    FloorAllocation,
    FloorKind,
    FloorPlan,
    NonresponseState,
    OutcomeAssignmentKind,
    OutcomeClosureState,
    PresentationInterventionV1,
    PresentationSafety,
    ReasonOrigin,
    SemanticRefusal,
    SensingAssignment,
    SensingDecisionV1,
    SensingReason,
    UnverifiedSemantic,
    VoiGateEvidence,
    admit_coverage_report,
    admit_experiment,
    admit_presentation_intervention,
    admit_sensing_decision,
    deterministic_artifacts,
)


def _raw() -> tuple[
    BaselineEpochRegistrationV1,
    BaselineClosureV1,
    ExperimentEpochRegistrationV1,
    SensingDecisionV1,
    CoverageSupportReportV1,
    ExperimentEpochRegistrationV1,
    PresentationInterventionV1,
]:
    items = deterministic_artifacts()
    artifacts = tuple(item.artifact for item in items)
    assert isinstance(artifacts[0], BaselineEpochRegistrationV1)
    assert isinstance(artifacts[1], BaselineClosureV1)
    assert isinstance(artifacts[2], ExperimentEpochRegistrationV1)
    assert isinstance(artifacts[3], SensingDecisionV1)
    assert isinstance(artifacts[4], CoverageSupportReportV1)
    assert isinstance(artifacts[5], ExperimentEpochRegistrationV1)
    assert isinstance(artifacts[6], PresentationInterventionV1)
    return artifacts  # type: ignore[return-value]


def _reseal(artifact, **changes):  # type: ignore[no-untyped-def]
    return replace(artifact, semantic_digest="", **changes).sealed()


def test_deterministic_artifacts_are_exact_and_publicly_unverified() -> None:
    first = deterministic_artifacts()
    second = deterministic_artifacts()
    assert [item.as_dict() for item in first] == [item.as_dict() for item in second]
    assert all(isinstance(item, UnverifiedSemantic) for item in first)
    assert all(item.verification_state == "unverified_semantic" for item in first)
    assert all("source_io" in item.explicit_nonclaims for item in first)
    assert first[3].artifact.as_dict()["contract"] == "joshi.sensing_decision/v1"
    assert first[6].artifact.as_dict()["contract"] == "joshi.presentation_intervention/v1"
    sensing_wire = first[3].artifact.as_dict()
    assert sensing_wire["record_ordinal"] == "1"
    assert sensing_wire["assignment"]["inclusion_probability"] == {
        "numerator": "1",
        "denominator": "2",
    }


def test_sealed_baseline_refuses_model_contamination_and_interleaving() -> None:
    baseline, closure, experiment, *_rest = _raw()
    with pytest.raises(SemanticRefusal, match="model-derived input"):
        replace(
            baseline,
            semantic_digest="",
            journal_input_origins=("model_forecast", "observed_fact"),
        )

    with pytest.raises(SemanticRefusal, match="separately registered after baseline"):
        replace(
            experiment,
            semantic_digest="",
            registered_at=closure.closed_at - timedelta(seconds=1),
        )


def test_model_induced_selection_cannot_be_hidden_as_manual_or_deterministic() -> None:
    _baseline, _closure, experiment, decision, *_rest = _raw()
    model_reason = SensingReason(
        "model_rank",
        ReasonOrigin.MODEL,
        ("evidence:model",),
        model_proposal_id="proposal:model-001",
        model_proposal_digest=experiment.candidate_policy_digest,
        model_lineage_evidence_ids=("evidence:model-lineage",),
    )
    with pytest.raises(SemanticRefusal, match="model-induced live selection"):
        replace(decision, semantic_digest="", reasons=(model_reason,))

    manual_assignment = SensingAssignment(
        AssignmentKind.FLOOR_MANUAL,
        "arm:candidate",
        experiment.candidate_policy_digest,
        "stratum:eligible",
        "block:001",
        "assignment:manual-laundered",
        decision.assignment.inclusion_probability,
        None,
        None,
    )
    with pytest.raises(SemanticRefusal, match="relabeled as manual"):
        replace(
            decision,
            semantic_digest="",
            reasons=(model_reason,),
            assignment=manual_assignment,
        )


def test_manual_floor_assignment_uses_registered_member_not_operator_label() -> None:
    _baseline, _closure, experiment, decision, *_rest = _raw()
    operator_reason = SensingReason(
        "explicit_operator_nomination",
        ReasonOrigin.OPERATOR,
        ("evidence:operator-nomination",),
        operator_command_id="command:manual-001",
        scene_view_id="scene:manual-001",
        durable_acceptance_receipt_id="receipt:manual-001",
    )
    manual_assignment = SensingAssignment(
        AssignmentKind.FLOOR_MANUAL,
        "arm:candidate",
        experiment.candidate_policy_digest,
        "stratum:manual",
        "block:001",
        "assignment:manual-001",
        decision.assignment.inclusion_probability,
        None,
        None,
    )
    manual_budget = experiment.floors.manual.source_budget("provider:read")
    floor_reservation = replace(
        decision.budget,
        reserved_maximum=manual_budget,
        expected=manual_budget,
        worst_case=manual_budget,
        maximum_in_flight_overshoot=BudgetVector(),
    )
    labeled_only = _reseal(
        decision,
        reasons=(operator_reason,),
        assignment=manual_assignment,
        budget=floor_reservation,
        operator_acceptance_resolved=True,
    )
    with pytest.raises(SemanticRefusal, match="not a registered manual floor member"):
        admit_sensing_decision(experiment, labeled_only)

    manual_subject = "subject:manual-mint"
    exact_member = _reseal(
        labeled_only,
        assignment_unit_key=manual_subject,
        public_subject_key=manual_subject,
        requests=(replace(decision.requests[0], subject_key=manual_subject),),
    )
    assert admit_sensing_decision(experiment, exact_member).verification_state == (
        "unverified_semantic"
    )


def test_operator_acceptance_retains_model_lineage_and_cannot_cleanse_manual_origin() -> None:
    _baseline, _closure, experiment, decision, *_rest = _raw()
    joint_lineage = SensingReason(
        "operator_accepts_model_proposal",
        ReasonOrigin.OPERATOR,
        ("evidence:operator",),
        operator_command_id="command:accept-model",
        scene_view_id="scene:model-proposal",
        durable_acceptance_receipt_id="receipt:accept-model",
        model_proposal_id="proposal:model-001",
        model_proposal_digest=experiment.candidate_policy_digest,
        model_lineage_evidence_ids=("evidence:model-lineage",),
    )
    assert joint_lineage.origin is ReasonOrigin.OPERATOR
    assert joint_lineage.model_proposal_id == "proposal:model-001"
    manual_assignment = replace(
        decision.assignment,
        kind=AssignmentKind.FLOOR_MANUAL,
        stratum="stratum:manual",
        seed_commit_digest=None,
        allocation_table_digest=None,
    )
    with pytest.raises(SemanticRefusal, match="relabeled as manual"):
        replace(
            decision,
            semantic_digest="",
            reasons=(joint_lineage,),
            assignment=manual_assignment,
            operator_acceptance_resolved=True,
        )


def test_floor_starvation_is_refused_for_cold_random_manual_and_portfolio() -> None:
    baseline, *_rest = _raw()
    floors = baseline.floors
    with pytest.raises(SemanticRefusal, match="cold floor starves"):
        FloorPlan(
            cold=FloorAllocation(
                FloorKind.COLD,
                (),
                floors.cold.budget,
                floors.cold.satisfaction_evidence_ids,
                floors.cold.source_operation_budgets,
            ),
            random=floors.random,
            manual=floors.manual,
            portfolio=floors.portfolio,
            required_cold_strata=floors.required_cold_strata,
            eligible_manual_families=floors.eligible_manual_families,
            required_portfolio_subjects=floors.required_portfolio_subjects,
            non_census_hot_subject_slots=floors.non_census_hot_subject_slots,
            non_census_capacity=floors.non_census_capacity,
            non_census_source_operation_capacities=(floors.non_census_source_operation_capacities),
        )

    with pytest.raises(SemanticRefusal, match="random floor starves"):
        FloorPlan(
            cold=floors.cold,
            random=replace(
                floors.random,
                members=(),
                budget=BudgetVector(),
                source_operation_budgets=(("provider:read", BudgetVector()),),
            ),
            manual=floors.manual,
            portfolio=floors.portfolio,
            required_cold_strata=floors.required_cold_strata,
            eligible_manual_families=floors.eligible_manual_families,
            required_portfolio_subjects=floors.required_portfolio_subjects,
            non_census_hot_subject_slots=floors.non_census_hot_subject_slots,
            non_census_capacity=floors.non_census_capacity,
            non_census_source_operation_capacities=(floors.non_census_source_operation_capacities),
        )

    with pytest.raises(SemanticRefusal, match="manual floor lacks"):
        FloorPlan(
            cold=floors.cold,
            random=floors.random,
            manual=replace(floors.manual, members=(floors.manual.members[0],)),
            portfolio=floors.portfolio,
            required_cold_strata=floors.required_cold_strata,
            eligible_manual_families=floors.eligible_manual_families,
            required_portfolio_subjects=floors.required_portfolio_subjects,
            non_census_hot_subject_slots=floors.non_census_hot_subject_slots,
            non_census_capacity=floors.non_census_capacity,
            non_census_source_operation_capacities=(floors.non_census_source_operation_capacities),
        )

    with pytest.raises(SemanticRefusal, match="portfolio floor omits"):
        FloorPlan(
            cold=floors.cold,
            random=floors.random,
            manual=floors.manual,
            portfolio=replace(floors.portfolio, members=()),
            required_cold_strata=floors.required_cold_strata,
            eligible_manual_families=floors.eligible_manual_families,
            required_portfolio_subjects=floors.required_portfolio_subjects,
            non_census_hot_subject_slots=floors.non_census_hot_subject_slots,
            non_census_capacity=floors.non_census_capacity,
            non_census_source_operation_capacities=(floors.non_census_source_operation_capacities),
        )


def test_future_support_and_cost_evidence_are_refused() -> None:
    _baseline, _closure, experiment, decision, *_rest = _raw()
    future_evidence = replace(
        decision.eligibility.evidence[0],
        known_by=decision.available_through + timedelta(seconds=1),
    )
    with pytest.raises(SemanticRefusal, match="later information"):
        replace(
            decision,
            semantic_digest="",
            eligibility=replace(decision.eligibility, evidence=(future_evidence,)),
        )

    future_cost = replace(
        decision.cost_basis,
        measured_cost_evidence_cutoff=decision.available_through + timedelta(seconds=1),
    )
    future_cost_decision = _reseal(decision, cost_basis=future_cost)
    with pytest.raises(SemanticRefusal, match="cost basis uses evidence from the future"):
        admit_sensing_decision(experiment, future_cost_decision)


def test_voi_requires_matured_support_and_completed_non_voi_cost_epoch() -> None:
    _baseline, closure, experiment, decision, *_rest = _raw()
    gate = VoiGateEvidence(
        claim_family="retained_closure",
        study_cells=("cell:eligible",),
        matured_prospective_occurrences=20,
        mechanism_validation_occurrences=20,
        chronological=True,
        outcome_embargoed=True,
        nonadjacent_repetitions=True,
        calibration_supported=True,
        proper_score_increment_supported=True,
        negative_controls_passed=True,
        uncertainty_exceeds_measurement_error=True,
        completed_non_voi_cost_epochs=1,
        cost_evidence_cutoff=closure.closed_at,
        fit_cutoff=closure.closed_at,
        floors_and_probabilities_preserved=True,
        estimator_digest=experiment.candidate_policy_digest,
        support_boundary_digest=experiment.eligible_universe_digest,
        separately_reviewed_registration_id="review:voi-001",
        attainable_action_set=("abstain", "observe", "refuse"),
        includes_abstention_and_refusals=True,
        common_downstream_policy_digest=experiment.baseline_policy_digest,
        declared_utility_digest=experiment.study_registration_digest,
    )
    with pytest.raises(SemanticRefusal, match="matured support"):
        replace(
            experiment,
            semantic_digest="",
            allows_candidate_voi=True,
            voi_gate=gate,
        )

    admitted_gate = replace(gate, matured_prospective_occurrences=21)
    voi_epoch = _reseal(
        experiment,
        allows_candidate_voi=True,
        voi_gate=admitted_gate,
    )
    model_reason = SensingReason(
        "registered_voi",
        ReasonOrigin.MODEL,
        ("evidence:model",),
        model_proposal_id="proposal:model-voi-001",
        model_proposal_digest=experiment.candidate_policy_digest,
        model_lineage_evidence_ids=("evidence:model-lineage",),
    )
    voi_assignment = replace(
        decision.assignment,
        kind=AssignmentKind.CANDIDATE_VOI,
        seed_commit_digest=None,
        allocation_table_digest=None,
    )
    voi_decision = _reseal(
        decision,
        experiment_epoch_digest=voi_epoch.semantic_digest,
        reasons=(model_reason,),
        assignment=voi_assignment,
    )
    assert (
        admit_sensing_decision(voi_epoch, voi_decision).verification_state == "unverified_semantic"
    )


def test_presentation_leakage_and_execution_controls_are_refused() -> None:
    *_, experiment, intervention = _raw()
    leaked_safety = replace(
        intervention.safety,
        invariant_safety_content_digest=intervention.eligible_evidence_digest,
    )
    leaked = _reseal(intervention, safety=leaked_safety)
    with pytest.raises(SemanticRefusal, match="safety-critical content differs"):
        admit_presentation_intervention(experiment, leaked)

    with pytest.raises(SemanticRefusal, match="execution authority"):
        replace(
            intervention,
            semantic_digest="",
            evidence_only_commands=("inspect_gap", "submit_transaction"),
        )

    unsafe = PresentationSafety(
        intervention.safety.invariant_safety_content_digest,
        intervention.safety.required_persistent_fields,
        True,
        intervention.safety.prohibited_omissions,
    )
    with pytest.raises(SemanticRefusal, match="staged prescription"):
        replace(
            intervention,
            semantic_digest="",
            safety=unsafe,
            receipt_not_yet_claimed=False,
        )


def test_missing_denominators_and_nonresponse_replacement_are_refused() -> None:
    _baseline, _closure, experiment, decision, report, *_rest = _raw()
    second_assignment = replace(
        decision.assignment,
        assignment_occurrence_id="assignment:sensing-002",
    )
    second = _reseal(
        decision,
        decision_id="sensing-decision:002",
        record_ordinal=2,
        predecessor_id=decision.decision_id,
        assignment=second_assignment,
    )
    with pytest.raises(SemanticRefusal, match="omits, replaces, or invents"):
        admit_coverage_report(experiment, report, (decision, second))

    unsupported = replace(
        report.outcomes[0],
        nonresponse_state=NonresponseState.OUTCOME_CENSORED_OR_UNSUPPORTED,
        outcome_state=OutcomeClosureState.UNSUPPORTED,
        outcome_matured=False,
        analyzed=False,
    )
    retained = _reseal(report, outcomes=(unsupported,))
    assert admit_coverage_report(experiment, retained, (decision,)).artifact.outcomes == (
        unsupported,
    )


def test_report_refuses_cross_experiment_assignment_even_with_valid_self_digest() -> None:
    _baseline, _closure, experiment, decision, report, *_rest = _raw()
    other_epoch = _reseal(experiment, experiment_epoch_id="experiment:other")
    other_assignment = _reseal(
        decision,
        experiment_epoch_id=other_epoch.experiment_epoch_id,
        experiment_epoch_digest=other_epoch.semantic_digest,
    )
    assert admit_sensing_decision(other_epoch, other_assignment).verification_state == (
        "unverified_semantic"
    )
    with pytest.raises(SemanticRefusal, match="different experiment"):
        admit_coverage_report(experiment, report, (other_assignment,))


def test_report_refuses_assignment_arm_policy_cell_class_and_digest_recoding() -> None:
    _baseline, _closure, experiment, decision, report, *_rest = _raw()
    original = report.outcomes[0]
    recoded = replace(
        original,
        assignment_artifact_id="sensing-decision:invented",
        assignment_artifact_digest=experiment.baseline_policy_digest,
        arm_id="arm:baseline",
        study_cell="cell:outcome-selected",
        assignment_kind=OutcomeAssignmentKind.FLOOR_COLD,
        policy_digest=experiment.baseline_policy_digest,
        denominator_digest=experiment.eligible_evidence_digest,
        assignment_unit_key="subject:cold",
        public_subject_key="subject:cold",
    )
    recoded_report = _reseal(report, outcomes=(recoded,))
    with pytest.raises(SemanticRefusal, match="recodes sealed assignment fields") as error:
        admit_coverage_report(experiment, recoded_report, (decision,))
    for field in (
        "arm_id",
        "assignment_artifact_digest",
        "assignment_kind",
        "denominator_digest",
        "policy_digest",
        "public_subject_key",
        "study_cell",
    ):
        assert field in str(error.value)


def test_denominator_occurrences_and_subject_ids_require_exact_registered_closure() -> None:
    _baseline, _closure, experiment, decision, report, *_rest = _raw()
    invented_occurrences = tuple(sorted((*report.denominator_occurrence_ids, "census:invented")))
    widened_report = _reseal(report, denominator_occurrence_ids=invented_occurrences)
    with pytest.raises(SemanticRefusal, match="not exact denominator closure"):
        admit_coverage_report(experiment, widened_report, (decision,))

    invented_subject = "subject:invented"
    invented_decision = _reseal(
        decision,
        assignment_unit_key=invented_subject,
        public_subject_key=invented_subject,
        requests=(replace(decision.requests[0], subject_key=invented_subject),),
    )
    with pytest.raises(SemanticRefusal, match="outside the registered eligible universe"):
        admit_sensing_decision(experiment, invented_decision)

    widened_denominator = replace(
        decision.denominator,
        census_occurrence_ids=invented_occurrences,
    )
    changed_denominator_decision = _reseal(decision, denominator=widened_denominator)
    with pytest.raises(SemanticRefusal, match="exact registered denominator"):
        admit_sensing_decision(experiment, changed_denominator_decision)


def test_multidimensional_budget_overflow_and_borrowing_are_refused() -> None:
    baseline, _closure, experiment, decision, *_rest = _raw()
    envelope = baseline.budget_envelopes[0]
    with pytest.raises(SemanticRefusal, match="budget overflow"):
        BudgetEnvelope(
            source_operation=envelope.source_operation,
            registered_run_budget_digest=envelope.registered_run_budget_digest,
            run_budget=replace(envelope.run_budget, requests=7),
            census_reserve=envelope.census_reserve,
            recovery_reserve=envelope.recovery_reserve,
            floors=envelope.floors,
            candidate_ceiling=envelope.candidate_ceiling,
        )

    oversized = replace(
        decision.budget,
        reserved_maximum=replace(decision.budget.reserved_maximum, requests=3),
    )
    oversized_decision = _reseal(decision, budget=oversized)
    with pytest.raises(SemanticRefusal, match="independent registered ceiling"):
        admit_sensing_decision(experiment, oversized_decision)

    with pytest.raises(SemanticRefusal, match="fully reserved"):
        BudgetReservation(
            decision.budget.parent_registered_run_digest,
            decision.budget.parent_budget_digest,
            decision.budget.source_operation,
            BudgetVector(requests=1, pages=100),
            BudgetVector(requests=1),
            BudgetVector(requests=1),
            BudgetVector(requests=1),
            decision.budget.privacy_retention_limit_digest,
        )


def test_feedback_gaming_and_accessibility_burden_fail_closed() -> None:
    (
        _baseline,
        _closure,
        sensing_experiment,
        _decision,
        _report,
        presentation_experiment,
        intervention,
    ) = _raw()
    with pytest.raises(SemanticRefusal, match="feedback-prone"):
        replace(
            sensing_experiment,
            semantic_digest="",
            primary_outcome_metrics=("click_count",),
        )
    with pytest.raises(SemanticRefusal, match="accessibility-critical"):
        replace(intervention.accessibility, keyboard_reachable=False)

    excessive_burden = replace(intervention.burden, seven_day_study_seconds=901)
    burden_intervention = _reseal(intervention, burden=excessive_burden)
    with pytest.raises(SemanticRefusal, match="burden ceiling"):
        admit_presentation_intervention(presentation_experiment, burden_intervention)


def test_experiment_requires_the_exact_closed_baseline_digest() -> None:
    baseline, closure, experiment, *_rest = _raw()
    changed = _reseal(experiment, closed_baseline_digest=experiment.candidate_policy_digest)
    with pytest.raises(SemanticRefusal, match="sealed baseline digest"):
        admit_experiment(baseline, closure, changed)
