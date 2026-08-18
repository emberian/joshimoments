"""Pure admission engine for Wave 6 active-sensing and presentation semantics."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import (
    AssignmentKind,
    BaselineClosureV1,
    BaselineEpochRegistrationV1,
    BudgetVector,
    CoverageSupportReportV1,
    ExperimentEpochRegistrationV1,
    FloorKind,
    InterventionKind,
    OutcomeAssignmentKind,
    PresentationInterventionV1,
    ReasonOrigin,
    SemanticRefusal,
    SensingDecisionV1,
    UnverifiedSemantic,
    semantic_sha256,
)


def _publish(artifact):  # type: ignore[no-untyped-def]
    sealed = artifact.sealed()
    return UnverifiedSemantic(artifact=sealed, semantic_digest=sealed.semantic_digest)


def admit_baseline(
    registration: BaselineEpochRegistrationV1,
) -> UnverifiedSemantic:
    """Admit a sealed, model-blind registration without starting or controlling an epoch."""

    return _publish(registration)


def admit_baseline_closure(
    registration: BaselineEpochRegistrationV1,
    closure: BaselineClosureV1,
) -> UnverifiedSemantic:
    registration = registration.sealed()
    if closure.baseline_epoch_id != registration.baseline_epoch_id:
        raise SemanticRefusal("baseline closure names a different epoch")
    if closure.baseline_registration_digest != registration.semantic_digest:
        raise SemanticRefusal("baseline closure does not bind the sealed registration")
    if closure.denominator_digest != registration.denominator.universe_digest:
        raise SemanticRefusal("baseline closure changed or selected its denominator")
    if closure.closed_at < registration.start_at:
        raise SemanticRefusal("baseline closure predates the registered epoch")
    if closure.close_state == "complete" and closure.closed_at < registration.end_at_exclusive:
        raise SemanticRefusal("a complete baseline cannot close before its fixed half-open end")
    return _publish(closure)


def admit_experiment(
    baseline: BaselineEpochRegistrationV1,
    closure: BaselineClosureV1,
    registration: ExperimentEpochRegistrationV1,
) -> UnverifiedSemantic:
    """Bind a separately registered post-baseline epoch to a closed sealed baseline."""

    baseline = baseline.sealed()
    closure = closure.sealed()
    registration = registration.sealed()
    admit_baseline_closure(baseline, closure)
    if closure.close_state != "complete":
        raise SemanticRefusal("an experiment requires a completely closed baseline")
    if registration.closed_baseline_id != baseline.baseline_epoch_id:
        raise SemanticRefusal("experiment names a different baseline")
    if registration.closed_baseline_digest != baseline.semantic_digest:
        raise SemanticRefusal("experiment does not bind the sealed baseline digest")
    if registration.baseline_closed_at != closure.closed_at:
        raise SemanticRefusal("experiment baseline closure time differs from its receipt")
    if registration.registered_at < closure.closed_at:
        raise SemanticRefusal("experiment was registered before baseline closure")
    return UnverifiedSemantic(registration, registration.semantic_digest)


_EXPECTED_REASON_ORIGIN = {
    AssignmentKind.FLOOR_COLD: ReasonOrigin.CENSUS_SCHEDULE,
    AssignmentKind.FLOOR_RANDOM: ReasonOrigin.RANDOM_DRAW,
    AssignmentKind.FLOOR_MANUAL: ReasonOrigin.OPERATOR,
    AssignmentKind.FLOOR_PORTFOLIO: ReasonOrigin.PORTFOLIO_REGISTRY,
    AssignmentKind.CANDIDATE_RANDOMIZED: ReasonOrigin.RANDOM_DRAW,
    AssignmentKind.CANDIDATE_DETERMINISTIC: ReasonOrigin.FIXED_POLICY,
    AssignmentKind.CANDIDATE_VOI: ReasonOrigin.MODEL,
}

_ASSIGNMENT_FLOOR = {
    AssignmentKind.FLOOR_COLD: FloorKind.COLD,
    AssignmentKind.FLOOR_RANDOM: FloorKind.RANDOM,
    AssignmentKind.FLOOR_MANUAL: FloorKind.MANUAL,
    AssignmentKind.FLOOR_PORTFOLIO: FloorKind.PORTFOLIO,
}


def _budget_limit_for_decision(
    registration: ExperimentEpochRegistrationV1,
    decision: SensingDecisionV1,
) -> BudgetVector:
    envelope = next(
        (
            candidate
            for candidate in registration.budget_envelopes
            if candidate.source_operation == decision.budget.source_operation
        ),
        None,
    )
    if envelope is None:
        raise SemanticRefusal("sensing decision has no registered source-operation envelope")
    if decision.budget.parent_registered_run_digest != envelope.registered_run_budget_digest:
        raise SemanticRefusal("sensing reservation does not bind the registered RunBudget")
    if decision.budget.parent_budget_digest != semantic_sha256(envelope):
        raise SemanticRefusal("sensing reservation does not bind its exact budget envelope")
    floor_kind = _ASSIGNMENT_FLOOR.get(decision.assignment.kind)
    if floor_kind is None:
        return envelope.candidate_ceiling
    return next(
        allocation.source_budget(decision.budget.source_operation)
        for allocation in envelope.floors.allocations()
        if allocation.kind is floor_kind
    )


def admit_sensing_decision(
    registration: ExperimentEpochRegistrationV1,
    decision: SensingDecisionV1,
) -> UnverifiedSemantic:
    """Admit an immutable pre-I/O decision; deliberately performs no acquisition."""

    registration = registration.sealed()
    decision = decision.sealed()
    if registration.intervention_kind is InterventionKind.PRESENTATION_ONLY:
        raise SemanticRefusal("a presentation-only epoch cannot contain a sensing decision")
    if decision.experiment_epoch_id != registration.experiment_epoch_id:
        raise SemanticRefusal("sensing decision names a different experiment")
    if decision.experiment_epoch_digest != registration.semantic_digest:
        raise SemanticRefusal("sensing decision does not bind the experiment digest")
    if decision.closed_baseline_id != registration.closed_baseline_id:
        raise SemanticRefusal("sensing decision changed the closed baseline identity")
    if decision.closed_baseline_digest != registration.closed_baseline_digest:
        raise SemanticRefusal("sensing decision changed the closed baseline digest")
    if decision.study_registration_id != registration.study_registration_id:
        raise SemanticRefusal("sensing decision changed its study registration")
    if decision.study_registration_digest != registration.study_registration_digest:
        raise SemanticRefusal("sensing decision changed its study registration digest")
    if not registration.start_at <= decision.decision_event_at < registration.end_at_exclusive:
        raise SemanticRefusal("sensing decision lies outside its registered epoch")
    if decision.denominator != registration.registered_denominator:
        raise SemanticRefusal("decision denominator differs from exact registered denominator")
    if decision.assignment_unit_kind != registration.assignment_unit:
        raise SemanticRefusal("sensing assignment unit kind differs from registration")
    if decision.assignment_unit_key not in registration.eligible_assignment_unit_keys:
        raise SemanticRefusal("sensing assignment unit is outside the registered eligible universe")
    if decision.public_subject_key not in registration.eligible_public_subject_keys:
        raise SemanticRefusal("sensing subject is outside the registered eligible universe")
    if decision.assignment_unit_key != decision.public_subject_key:
        raise SemanticRefusal("subject assignment unit and public subject identity differ")
    if decision.study_cell not in registration.registered_study_cells:
        raise SemanticRefusal("sensing assignment uses an unregistered study cell")
    if decision.assignment.arm_id not in dict(registration.allocation_probabilities):
        raise SemanticRefusal("sensing assignment arm was not prospectively registered")
    if (
        decision.assignment.inclusion_probability
        != dict(registration.allocation_probabilities)[decision.assignment.arm_id]
    ):
        raise SemanticRefusal("sensing assignment probability differs from registration")
    registered_arm_digest = dict(registration.allocation_arm_digests)[decision.assignment.arm_id]
    if (
        decision.assignment.arm_digest != decision.policy_digest
        or decision.assignment.arm_digest != registered_arm_digest
    ):
        raise SemanticRefusal("sensing assignment arm does not bind its registered policy")
    expected_origin = _EXPECTED_REASON_ORIGIN[decision.assignment.kind]
    if expected_origin not in {reason.origin for reason in decision.reasons}:
        raise SemanticRefusal("sensing decision lacks its assignment class's required lineage")
    if decision.assignment.kind is AssignmentKind.CANDIDATE_VOI:
        if not registration.allows_candidate_voi or registration.voi_gate is None:
            raise SemanticRefusal("pre-gate VOI cannot alter a live read")
        gate = registration.voi_gate
        if decision.study_cell not in gate.study_cells:
            raise SemanticRefusal("VOI decision lies outside its matured support cells")
        if gate.fit_cutoff > decision.available_through:
            raise SemanticRefusal("VOI estimator fit uses future support")
        if gate.cost_evidence_cutoff > decision.cost_basis.measured_cost_evidence_cutoff:
            raise SemanticRefusal("VOI decision lacks the registered measured-cost cutoff")
    elif any(
        reason.origin is ReasonOrigin.MODEL or reason.model_proposal_id is not None
        for reason in decision.reasons
    ):
        raise SemanticRefusal("model-induced selection is inadmissible outside candidate_voi")
    if decision.policy_digest not in {
        registration.baseline_policy_digest,
        registration.candidate_policy_digest,
    }:
        raise SemanticRefusal("sensing decision uses an unregistered policy digest")
    if decision.no_model_baseline_digest != registration.baseline_policy_digest:
        raise SemanticRefusal("sensing decision changed its contemporaneous no-model baseline")
    if decision.cost_basis.measured_cost_evidence_cutoff > decision.available_through:
        raise SemanticRefusal("sensing cost basis uses evidence from the future")
    limit = _budget_limit_for_decision(registration, decision)
    if not decision.budget.reserved_maximum.fits_within(limit):
        raise SemanticRefusal("sensing reservation crosses its independent registered ceiling")
    status_by_key = {
        (status.source_operation, status.kind): status for status in decision.floor_statuses
    }
    registered_floor_by_kind = {
        allocation.kind: allocation for allocation in registration.floors.allocations()
    }
    expected_floor_keys = {
        (envelope.source_operation, kind)
        for envelope in registration.budget_envelopes
        for kind in FloorKind
    }
    actual_floor_keys = {
        (status.source_operation, status.kind) for status in decision.floor_statuses
    }
    if actual_floor_keys != expected_floor_keys:
        raise SemanticRefusal("decision does not carry every registered source-operation floor")
    for source_operation, kind in expected_floor_keys:
        expected_budget = registered_floor_by_kind[kind].source_budget(source_operation)
        if status_by_key[(source_operation, kind)].reserved != expected_budget:
            raise SemanticRefusal(
                f"decision rewrites the protected {source_operation} {kind.value} floor"
            )
    primary_floor_kind = _ASSIGNMENT_FLOOR.get(decision.assignment.kind)
    for request in decision.requests:
        source_operation = f"{request.source_id}:{request.operation}"
        if source_operation != decision.budget.source_operation:
            raise SemanticRefusal("source request differs from its reserved source-operation")
        if request.subject_key != decision.public_subject_key:
            raise SemanticRefusal("source request changed the registered public subject")
        if primary_floor_kind is not None:
            member = registered_floor_by_kind[primary_floor_kind].member(
                source_operation, request.subject_key
            )
            if member is None:
                raise SemanticRefusal(
                    f"subject is not a registered {primary_floor_kind.value} floor member"
                )
            if (
                member.subject_family != decision.public_subject_kind
                or member.stratum != decision.assignment.stratum
            ):
                raise SemanticRefusal(
                    "floor assignment family/stratum differs from registered membership"
                )
        elif any(
            allocation.member(source_operation, request.subject_key) is not None
            for allocation in registration.floors.allocations()
        ):
            raise SemanticRefusal(
                "candidate assignment attempts to consume a protected floor member"
            )
        if request.starts_at < decision.production_at:
            raise SemanticRefusal("source request starts before the decision is committed")
        if request.expires_at_exclusive > decision.expires_at_exclusive:
            raise SemanticRefusal("source request exceeds the immutable decision TTL")
    return UnverifiedSemantic(decision, decision.semantic_digest)


def admit_presentation_intervention(
    registration: ExperimentEpochRegistrationV1,
    intervention: PresentationInterventionV1,
) -> UnverifiedSemantic:
    """Admit a staged prescription; deliberately performs no mount, reveal, or UI mutation."""

    registration = registration.sealed()
    intervention = intervention.sealed()
    if registration.intervention_kind is InterventionKind.SENSING_ONLY:
        raise SemanticRefusal("a sensing-only epoch cannot contain a presentation intervention")
    if intervention.experiment_epoch_id != registration.experiment_epoch_id:
        raise SemanticRefusal("presentation intervention names a different experiment")
    if intervention.experiment_epoch_digest != registration.semantic_digest:
        raise SemanticRefusal("presentation intervention does not bind the experiment digest")
    if intervention.closed_baseline_id != registration.closed_baseline_id:
        raise SemanticRefusal("presentation changed the sealed baseline identity")
    if intervention.closed_baseline_digest != registration.closed_baseline_digest:
        raise SemanticRefusal("presentation changed the sealed baseline digest")
    if intervention.study_registration_id != registration.study_registration_id:
        raise SemanticRefusal("presentation changed its study registration")
    if intervention.study_registration_digest != registration.study_registration_digest:
        raise SemanticRefusal("presentation changed its study registration digest")
    if not registration.start_at <= intervention.assignment_at < registration.end_at_exclusive:
        raise SemanticRefusal("presentation assignment lies outside its registered epoch")
    if intervention.denominator != registration.registered_denominator:
        raise SemanticRefusal("presentation denominator differs from exact registration")
    if intervention.assignment_unit != registration.assignment_unit:
        raise SemanticRefusal("presentation assignment unit differs from registration")
    if intervention.session_id not in registration.eligible_assignment_unit_keys:
        raise SemanticRefusal("presentation session is outside the eligible assignment universe")
    if intervention.study_cell not in registration.registered_study_cells:
        raise SemanticRefusal("presentation uses an unregistered study cell")
    if intervention.eligible_evidence_digest != registration.eligible_evidence_digest:
        raise SemanticRefusal("presentation arm changed the registered eligible evidence")
    probabilities = dict(registration.allocation_probabilities)
    if intervention.assignment.assigned_arm not in probabilities:
        raise SemanticRefusal("presentation arm was not prospectively registered")
    if (
        intervention.assignment.inclusion_probability
        != probabilities[intervention.assignment.assigned_arm]
    ):
        raise SemanticRefusal("presentation assignment probability differs from registration")
    if intervention.policy.policy_digest not in {
        registration.baseline_policy_digest,
        registration.candidate_policy_digest,
    }:
        raise SemanticRefusal("presentation uses an unregistered policy")
    if dict(intervention.assignment.eligible_arms)[intervention.assignment.assigned_arm] != (
        intervention.policy.policy_digest
    ):
        raise SemanticRefusal("presented policy differs from the assigned arm")
    if set(dict(intervention.assignment.eligible_arms)) != set(probabilities):
        raise SemanticRefusal("presentation arm set differs from registered assignment support")
    if dict(intervention.assignment.eligible_arms) != dict(registration.allocation_arm_digests):
        raise SemanticRefusal("presentation arm digests differ from exact registration")
    arm_digests = set(dict(intervention.assignment.eligible_arms).values())
    if arm_digests != {
        registration.baseline_policy_digest,
        registration.candidate_policy_digest,
    }:
        raise SemanticRefusal("presentation assignment leaks an unregistered arm")
    if intervention.safety.invariant_safety_content_digest != registration.safety_content_digest:
        raise SemanticRefusal("safety-critical content differs across presentation arms")
    if intervention.accessibility != registration.accessibility_profile:
        raise SemanticRefusal("presentation arm changed the registered accessibility capability")
    ceiling = registration.burden_ceiling
    burden = intervention.burden
    if (
        burden.session_assignment_ordinal > ceiling.assignments_per_session
        or burden.closeout_seconds > ceiling.closeout_seconds_per_assignment
        or burden.seven_day_study_seconds > ceiling.study_seconds_per_seven_days
        or burden.notification_count > ceiling.unsolicited_research_notifications
    ):
        raise SemanticRefusal("presentation crosses a registered burden ceiling")
    return UnverifiedSemantic(intervention, intervention.semantic_digest)


def admit_coverage_report(
    registration: ExperimentEpochRegistrationV1,
    report: CoverageSupportReportV1,
    assignments: Iterable[SensingDecisionV1 | PresentationInterventionV1],
) -> UnverifiedSemantic:
    """Close the assigned denominator without substitution or post-exposure conditioning."""

    registration = registration.sealed()
    report = report.sealed()
    assigned = tuple(assignments)
    for artifact in assigned:
        if isinstance(artifact, SensingDecisionV1):
            admit_sensing_decision(registration, artifact)
        else:
            admit_presentation_intervention(registration, artifact)
    if report.experiment_epoch_id != registration.experiment_epoch_id:
        raise SemanticRefusal("coverage report names a different experiment")
    if report.experiment_epoch_digest != registration.semantic_digest:
        raise SemanticRefusal("coverage report does not bind the experiment digest")
    if report.knowledge_deadline != registration.outcome_knowledge_deadline:
        raise SemanticRefusal("coverage report moved the registered knowledge deadline")
    expected_outcomes: dict[str, dict[str, object]] = {}
    denominators = []
    reserved_by_source_and_class: dict[tuple[str, FloorKind | None], BudgetVector] = {}
    for artifact in assigned:
        if isinstance(artifact, SensingDecisionV1):
            assignment_id = artifact.assignment.assignment_occurrence_id
            if assignment_id in expected_outcomes:
                raise SemanticRefusal("duplicate assignment occurrence in coverage closure")
            expected_outcomes[assignment_id] = {
                "assignment_artifact_id": artifact.decision_id,
                "assignment_artifact_digest": artifact.semantic_digest,
                "arm_id": artifact.assignment.arm_id,
                "study_cell": artifact.study_cell,
                "assignment_kind": OutcomeAssignmentKind(artifact.assignment.kind.value),
                "policy_digest": artifact.policy_digest,
                "denominator_digest": artifact.denominator.universe_digest,
                "assignment_unit_key": artifact.assignment_unit_key,
                "public_subject_key": artifact.public_subject_key,
            }
            allocation_class = _ASSIGNMENT_FLOOR.get(artifact.assignment.kind)
            ledger_key = (artifact.budget.source_operation, allocation_class)
            previous = reserved_by_source_and_class.get(ledger_key, BudgetVector())
            reserved_by_source_and_class[ledger_key] = previous.plus(
                artifact.budget.reserved_maximum
            )
        else:
            assignment_id = artifact.intervention_id
            if assignment_id in expected_outcomes:
                raise SemanticRefusal("duplicate assignment occurrence in coverage closure")
            expected_outcomes[assignment_id] = {
                "assignment_artifact_id": artifact.intervention_id,
                "assignment_artifact_digest": artifact.semantic_digest,
                "arm_id": artifact.assignment.assigned_arm,
                "study_cell": artifact.study_cell,
                "assignment_kind": OutcomeAssignmentKind.PRESENTATION_INTERVENTION,
                "policy_digest": artifact.policy.policy_digest,
                "denominator_digest": artifact.denominator.universe_digest,
                "assignment_unit_key": artifact.session_id,
                "public_subject_key": artifact.eligible_evidence_artifact_id,
            }
        denominators.append(artifact.denominator)
    expected = tuple(sorted(expected_outcomes))
    actual = tuple(outcome.assignment_occurrence_id for outcome in report.outcomes)
    if expected != actual:
        raise SemanticRefusal("coverage report omits, replaces, or invents an assigned unit")
    for outcome in report.outcomes:
        expected_fields = expected_outcomes[outcome.assignment_occurrence_id]
        mismatched = [
            name
            for name, expected_value in expected_fields.items()
            if getattr(outcome, name) != expected_value
        ]
        if mismatched:
            raise SemanticRefusal(f"outcome recodes sealed assignment fields: {sorted(mismatched)}")
    if not denominators:
        raise SemanticRefusal("coverage report lacks assignment denominators")
    registered_denominator = registration.registered_denominator
    if any(item != registered_denominator for item in denominators):
        raise SemanticRefusal("assignment denominator differs from exact registration")
    if report.denominator_digest != registered_denominator.universe_digest:
        raise SemanticRefusal("coverage report changed the registered denominator digest")
    if report.full_census_count != registered_denominator.universe_count:
        raise SemanticRefusal("coverage report changed the registered census count")
    if report.denominator_occurrence_ids != registered_denominator.census_occurrence_ids:
        raise SemanticRefusal("coverage report occurrence IDs are not exact denominator closure")
    if report.analysis_mode == "randomized_itt" and registration.analysis_claim != "randomized_itt":
        raise SemanticRefusal("report promotes an unregistered randomized ITT claim")
    envelopes = {envelope.source_operation: envelope for envelope in registration.budget_envelopes}
    for (source_operation, floor_kind), reserved in reserved_by_source_and_class.items():
        envelope = envelopes[source_operation]
        limit = envelope.candidate_ceiling
        if floor_kind is not None:
            limit = next(
                floor.source_budget(source_operation)
                for floor in envelope.floors.allocations()
                if floor.kind is floor_kind
            )
        if not reserved.fits_within(limit):
            name = "candidate" if floor_kind is None else floor_kind.value
            raise SemanticRefusal(
                f"cumulative {name} reservations cross the {source_operation} ceiling"
            )
    total_registered = BudgetVector()
    for envelope in registration.budget_envelopes:
        total_registered = total_registered.plus(envelope.run_budget)
    if not report.planned_budget.fits_within(total_registered):
        raise SemanticRefusal("coverage report's planned budget exceeds registered RunBudgets")
    return UnverifiedSemantic(report, report.semantic_digest)


class ActiveSensingSemanticEngine:
    """Namespaced façade; every method remains pure and returns only UnverifiedSemantic."""

    admit_baseline = staticmethod(admit_baseline)
    admit_baseline_closure = staticmethod(admit_baseline_closure)
    admit_experiment = staticmethod(admit_experiment)
    admit_sensing_decision = staticmethod(admit_sensing_decision)
    admit_presentation_intervention = staticmethod(admit_presentation_intervention)
    admit_coverage_report = staticmethod(admit_coverage_report)
