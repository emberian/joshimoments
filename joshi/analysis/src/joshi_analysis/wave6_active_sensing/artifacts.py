"""Deterministic, entirely synthetic Wave 6 semantic artifacts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from .contracts import (
    AccessibilityProfile,
    AssignedUnitOutcome,
    AssignmentKind,
    BaselineClosureV1,
    BaselineEpochRegistrationV1,
    BudgetEnvelope,
    BudgetReservation,
    BudgetVector,
    BurdenCeiling,
    CensusDenominator,
    CostBasis,
    CoverageSupportReportV1,
    EligibilityEvidence,
    EvidenceRef,
    ExperimentEpochRegistrationV1,
    FloorAllocation,
    FloorKind,
    FloorMember,
    FloorPlan,
    FloorStatus,
    InterventionKind,
    NonresponseState,
    OutcomeAssignmentKind,
    OutcomeClosureState,
    PresentationAssignment,
    PresentationBurden,
    PresentationInterventionV1,
    PresentationPolicy,
    PresentationSafety,
    RationalProbability,
    ReasonOrigin,
    SensingAssignment,
    SensingDecisionV1,
    SensingReason,
    SourceRequest,
    UnverifiedSemantic,
    semantic_sha256,
)
from .engine import (
    admit_baseline,
    admit_baseline_closure,
    admit_coverage_report,
    admit_experiment,
    admit_presentation_intervention,
    admit_sensing_decision,
)


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _units(count: int) -> BudgetVector:
    return BudgetVector(
        requests=count,
        pages=count,
        ingress_bytes=count * 1_000,
        durable_bytes=count * 500,
        provider_credits=count,
        events=count * 10,
        wall_time_ms=count * 1_000,
        attention_assignments=count,
        prompts=count,
        closeout_seconds=count * 30,
        notifications=0,
        operator_session_seconds=count * 30,
    )


def _floors() -> FloorPlan:
    evidence = ("receipt:floor-satisfied",)
    return FloorPlan(
        cold=FloorAllocation(
            FloorKind.COLD,
            (FloorMember("provider:read", "subject:cold", "mint", "stratum:quiet"),),
            _units(1),
            evidence,
            (("provider:read", _units(1)),),
        ),
        random=FloorAllocation(
            FloorKind.RANDOM,
            (FloorMember("provider:read", "subject:random", "mint", "stratum:active"),),
            _units(1),
            evidence,
            (("provider:read", _units(1)),),
        ),
        manual=FloorAllocation(
            FloorKind.MANUAL,
            (
                FloorMember("provider:read", "subject:manual-mint", "mint", "stratum:manual"),
                FloorMember("provider:read", "subject:manual-wallet", "wallet", "stratum:manual"),
            ),
            _units(1),
            evidence,
            (("provider:read", _units(1)),),
        ),
        portfolio=FloorAllocation(
            FloorKind.PORTFOLIO,
            (FloorMember("provider:read", "subject:portfolio", "mint", "stratum:portfolio"),),
            _units(1),
            evidence,
            (("provider:read", _units(1)),),
        ),
        required_cold_strata=("stratum:quiet",),
        eligible_manual_families=("mint", "wallet"),
        required_portfolio_subjects=("subject:portfolio",),
        non_census_hot_subject_slots=5,
        non_census_capacity=_units(5),
        non_census_source_operation_capacities=(("provider:read", _units(5)),),
    )


def _envelope(floors: FloorPlan) -> BudgetEnvelope:
    return BudgetEnvelope(
        source_operation="provider:read",
        registered_run_budget_digest=_digest("registered-run-budget"),
        run_budget=_units(8),
        census_reserve=_units(1),
        recovery_reserve=_units(1),
        floors=floors,
        candidate_ceiling=_units(2),
    )


def _denominator(base: datetime) -> CensusDenominator:
    return CensusDenominator(
        census_occurrence_ids=("census:001", "census:002"),
        membership_artifact_id="membership:all",
        membership_digest=_digest("membership"),
        universe_digest=_digest("universe"),
        universe_count=6,
        available_through=base - timedelta(days=2),
        commit_through=100,
        source_evidence_ids=("evidence:census",),
        coverage_evidence_ids=("evidence:coverage",),
        product_parity_receipt_id="receipt:product-parity",
    )


def _accessibility() -> AccessibilityProfile:
    return AccessibilityProfile(
        profile_id="accessibility:ordinary-use-v1",
        critical_task_evidence_ids=("accessibility:actual-critical-task",),
        keyboard_reachable=True,
        focus_order_stable=True,
        semantic_text_alternative=True,
        target_size_css_px=44,
        contrast_and_non_color=True,
        reduced_motion=True,
        zoom_reflow_200_percent=True,
        screen_reader_evidence=True,
        live_region_restrained=True,
        nonprecision_input=True,
        renderer_capability_receipt_id="receipt:renderer-capabilities",
    )


def _experiment(
    *,
    epoch_id: str,
    baseline: BaselineEpochRegistrationV1,
    closure: BaselineClosureV1,
    start: datetime,
    kind: InterventionKind,
    baseline_policy_digest: str,
    candidate_policy_digest: str,
) -> ExperimentEpochRegistrationV1:
    return ExperimentEpochRegistrationV1(
        experiment_epoch_id=epoch_id,
        occurrence_ordinal=1,
        predecessor_id=None,
        registered_at=closure.closed_at + timedelta(hours=1),
        start_at=start,
        end_at_exclusive=start + timedelta(days=1),
        outcome_knowledge_deadline=start + timedelta(days=2),
        closed_baseline_id=baseline.baseline_epoch_id,
        closed_baseline_digest=baseline.semantic_digest,
        baseline_closed_at=closure.closed_at,
        study_registration_id=f"study:{epoch_id}",
        study_registration_digest=_digest(f"study:{epoch_id}"),
        primary_hypothesis=f"registered narrow hypothesis for {kind.value}",
        estimands=("assigned_information_or_usefulness_vector",),
        falsifiers=("cold_random_slice_reversal", "full_denominator_null"),
        primary_outcome_metrics=("retained_supported_closure", "safety_usefulness_vector"),
        analysis_population="all_registered_assignments_itt",
        stopping_rule="fixed_registered_end_no_outcome_adaptation",
        intervention_kind=kind,
        assignment_unit=("subject" if kind is InterventionKind.SENSING_ONLY else "session"),
        cluster_unit="nonoverlapping_episode_window",
        eligible_universe_digest=baseline.denominator.universe_digest,
        eligible_evidence_digest=_digest(f"eligible-evidence:{epoch_id}"),
        registered_denominator=baseline.denominator,
        eligible_assignment_unit_keys=(
            (
                "subject:candidate",
                "subject:cold",
                "subject:manual-mint",
                "subject:manual-wallet",
                "subject:portfolio",
                "subject:random",
            )
            if kind is InterventionKind.SENSING_ONLY
            else ("session:001",)
        ),
        eligible_public_subject_keys=(
            "subject:candidate",
            "subject:cold",
            "subject:manual-mint",
            "subject:manual-wallet",
            "subject:portfolio",
            "subject:random",
        ),
        registered_study_cells=("cell:eligible",),
        allocation_probabilities=(
            ("arm:baseline", RationalProbability(1, 2)),
            ("arm:candidate", RationalProbability(1, 2)),
        ),
        allocation_arm_digests=(
            ("arm:baseline", baseline_policy_digest),
            ("arm:candidate", candidate_policy_digest),
        ),
        baseline_policy_digest=baseline_policy_digest,
        candidate_policy_digest=candidate_policy_digest,
        fixed_sensing_policy_digest=_digest("fixed-sensing-policy"),
        fixed_presentation_policy_digest=_digest("fixed-presentation-policy"),
        floors=baseline.floors,
        budget_envelopes=baseline.budget_envelopes,
        required_coverage_states=("declared_gap", "healthy_coverage"),
        required_support_states=("known_probability", "registered_cell"),
        allowed_nonresponse_states=tuple(sorted(NonresponseState, key=lambda state: state.value)),
        safety_content_digest=baseline.safety_content_digest,
        accessibility_profile=_accessibility(),
        burden_ceiling=baseline.burden_ceiling,
        consent_version=baseline.consent_version,
        privacy_retention_class=baseline.privacy_retention_class,
        analysis_claim="randomized_itt",
    ).sealed()


def _objects() -> tuple[
    BaselineEpochRegistrationV1,
    BaselineClosureV1,
    ExperimentEpochRegistrationV1,
    SensingDecisionV1,
    CoverageSupportReportV1,
    ExperimentEpochRegistrationV1,
    PresentationInterventionV1,
]:
    base = datetime(2026, 8, 1, 12, tzinfo=UTC)
    floors = _floors()
    denominator = _denominator(base)
    burden = BurdenCeiling(2, 90, 900, 0)
    baseline = BaselineEpochRegistrationV1(
        baseline_epoch_id="baseline:sealed-001",
        occurrence_ordinal=1,
        predecessor_id=None,
        registered_at=base - timedelta(days=1),
        start_at=base,
        end_at_exclusive=base + timedelta(days=7),
        maximum_duration_seconds=7 * 24 * 60 * 60,
        outcome_knowledge_deadline=base + timedelta(days=8),
        producer_digest=_digest("producer"),
        build_digest=_digest("build"),
        source_tree_digest=_digest("tree"),
        configuration_digest=_digest("configuration"),
        daily_use_surface_digest=_digest("surface"),
        cockpit_publication_digest=_digest("cockpit"),
        presentation_policy_digest=_digest("baseline-presentation"),
        source_registry_digest=_digest("source-registry"),
        acquisition_policy_digest=_digest("acquisition-policy"),
        collector_plan_digest=_digest("collector-plan"),
        registered_run_digest=_digest("registered-run"),
        denominator=denominator,
        floors=floors,
        budget_envelopes=(_envelope(floors),),
        fixed_selection_rule="stable_identity_activity_blind",
        stable_tie_break_keys=("public_subject_key", "source_operation"),
        journal_claim_ids=("claim:first-round",),
        journal_issue_deadline=base + timedelta(days=6),
        journal_sealed_until=base + timedelta(days=8),
        journal_input_origins=("fixed_mechanics", "observed_fact", "operator_perception"),
        safety_content_digest=_digest("safety-content"),
        accessibility_mode_ids=("keyboard", "reduced_motion", "screen_reader", "zoom_reflow"),
        burden_ceiling=burden,
        privacy_retention_class="research-minimal-v1",
        consent_version="consent-v1",
    ).sealed()
    closure = BaselineClosureV1(
        closure_id="closure:baseline-001",
        baseline_epoch_id=baseline.baseline_epoch_id,
        baseline_registration_digest=baseline.semantic_digest,
        closed_at=baseline.end_at_exclusive,
        close_state="complete",
        close_reason="fixed_registered_end",
        denominator_digest=denominator.universe_digest,
        denominator_preserved=True,
        outcome_responsive_stop_or_extension=False,
    ).sealed()

    sensing_policy = _digest("sensing-candidate-policy")
    sensing_experiment = _experiment(
        epoch_id="experiment:sensing-001",
        baseline=baseline,
        closure=closure,
        start=base + timedelta(days=10),
        kind=InterventionKind.SENSING_ONLY,
        baseline_policy_digest=_digest("sensing-baseline-policy"),
        candidate_policy_digest=sensing_policy,
    )
    decision_at = sensing_experiment.start_at + timedelta(hours=1)
    floor_statuses = tuple(
        sorted(
            (
                FloorStatus(
                    allocation.kind,
                    "provider:read",
                    allocation.source_budget("provider:read"),
                    allocation.source_budget("provider:read"),
                    allocation.source_budget("provider:read"),
                    True,
                    allocation.satisfaction_evidence_ids,
                )
                for allocation in floors.allocations()
            ),
            key=lambda status: (status.source_operation, status.kind.value),
        )
    )
    decision = SensingDecisionV1(
        decision_id="sensing-decision:001",
        record_ordinal=1,
        predecessor_id=None,
        created_at=decision_at,
        producer_digest=_digest("producer"),
        build_digest=_digest("build"),
        configuration_digest=_digest("configuration"),
        experiment_epoch_id=sensing_experiment.experiment_epoch_id,
        experiment_epoch_digest=sensing_experiment.semantic_digest,
        closed_baseline_id=baseline.baseline_epoch_id,
        closed_baseline_digest=baseline.semantic_digest,
        study_registration_id=sensing_experiment.study_registration_id,
        study_registration_digest=sensing_experiment.study_registration_digest,
        policy_id="policy:sensing-candidate",
        policy_version="1",
        policy_digest=sensing_policy,
        decision_event_at=decision_at,
        available_through=decision_at,
        commit_through=200,
        production_at=decision_at + timedelta(seconds=1),
        ttl_seconds=300,
        expires_at_exclusive=decision_at + timedelta(seconds=300),
        assignment_unit_kind="subject",
        assignment_unit_key="subject:candidate",
        public_subject_kind="mint",
        public_subject_key="subject:candidate",
        lifecycle_topology_version="topology:v1",
        cluster_interference_id="cluster:window-001",
        study_cell="cell:eligible",
        denominator=denominator,
        eligibility=EligibilityEvidence(
            eligible_artifact_id="eligible:001",
            eligible_digest=_digest("eligible"),
            eligible_count=1,
            inclusion_predicates=("registered_non_floor_subject",),
            exclusion_predicates=("privacy_ineligible",),
            support_state="registered_cell",
            privacy_retention_eligible=True,
            evidence=(
                EvidenceRef(
                    "evidence:eligible", _digest("eligible-evidence"), decision_at, decision_at, 150
                ),
            ),
            no_later_information=True,
        ),
        reasons=(
            SensingReason("committed_micro_lottery", ReasonOrigin.RANDOM_DRAW, ("evidence:draw",)),
        ),
        assignment=SensingAssignment(
            AssignmentKind.CANDIDATE_RANDOMIZED,
            "arm:candidate",
            sensing_policy,
            "stratum:eligible",
            "block:001",
            "assignment:sensing-001",
            RationalProbability(1, 2),
            _digest("seed:sensing"),
            _digest("allocation:sensing"),
        ),
        requests=(
            SourceRequest(
                "provider",
                "read",
                "subject:candidate",
                "additional_depth",
                30,
                decision_at + timedelta(seconds=1),
                decision_at + timedelta(seconds=300),
                "bounded_no_replacement",
                "typed_gap",
                1,
            ),
        ),
        floor_statuses=floor_statuses,
        budget=BudgetReservation(
            _digest("registered-run-budget"),
            semantic_sha256(sensing_experiment.budget_envelopes[0]),
            "provider:read",
            _units(2),
            _units(1),
            _units(1),
            _units(1),
            _digest("privacy-limit"),
        ),
        cost_basis=CostBasis(
            "method-envelope:v1",
            _digest("registry-fingerprint"),
            closure.closed_at,
            "cost-model-v1",
        ),
        fixed_sensing_comparator_id="comparator:fixed-cadence",
        activity_blind_control_id="control:cold",
        random_control_id="control:random",
        no_model_baseline_digest=sensing_experiment.baseline_policy_digest,
        source_registry_resolved=True,
        run_budget_resolved=True,
        denominator_resolved=True,
        coverage_resolved=True,
        policy_occurrence_resolved=True,
        operator_acceptance_resolved=False,
        source_io_not_started=True,
    ).sealed()
    outcome = AssignedUnitOutcome(
        assignment_occurrence_id=decision.assignment.assignment_occurrence_id,
        assignment_artifact_id=decision.decision_id,
        assignment_artifact_digest=decision.semantic_digest,
        arm_id=decision.assignment.arm_id,
        study_cell=decision.study_cell,
        assignment_kind=OutcomeAssignmentKind(decision.assignment.kind.value),
        policy_digest=decision.policy_digest,
        denominator_digest=decision.denominator.universe_digest,
        assignment_unit_key=decision.assignment_unit_key,
        public_subject_key=decision.public_subject_key,
        nonresponse_state=NonresponseState.COMPLETED_COVERED,
        outcome_state=OutcomeClosureState.MATURED,
        desired=True,
        applied=True,
        provider_acknowledged=True,
        healthily_covered=True,
        exposed=False,
        focused=False,
        responded=True,
        outcome_matured=True,
        analyzed=True,
        actual_cost=_units(1),
        reason_evidence_ids=("evidence:outcome",),
    )
    report = CoverageSupportReportV1(
        report_id="coverage-report:sensing-001",
        experiment_epoch_id=sensing_experiment.experiment_epoch_id,
        experiment_epoch_digest=sensing_experiment.semantic_digest,
        knowledge_deadline=sensing_experiment.outcome_knowledge_deadline,
        full_census_count=denominator.universe_count,
        denominator_digest=denominator.universe_digest,
        denominator_occurrence_ids=denominator.census_occurrence_ids,
        outcomes=(outcome,),
        planned_budget=_units(2),
        actual_budget=_units(1),
        provider_observed_billing=_units(1),
        inclusion_probabilities_known=True,
        effective_sample_size_numerator=1,
        effective_sample_size_denominator=1,
        worst_supported_strata=("stratum:eligible",),
        drift_version_ids=(),
        analysis_mode="randomized_itt",
    ).sealed()

    presentation_baseline = _digest("presentation-baseline-policy")
    presentation_candidate = _digest("presentation-candidate-policy")
    presentation_experiment = _experiment(
        epoch_id="experiment:presentation-001",
        baseline=baseline,
        closure=closure,
        start=base + timedelta(days=13),
        kind=InterventionKind.PRESENTATION_ONLY,
        baseline_policy_digest=presentation_baseline,
        candidate_policy_digest=presentation_candidate,
    )
    assignment_at = presentation_experiment.start_at + timedelta(hours=1)
    safety_fields = ("authority", "freshness", "gaps", "inventory_exposure", "refusals")
    eligible_items = (*safety_fields, "supported_evidence")
    intervention = PresentationInterventionV1(
        intervention_id="presentation-intervention:001",
        record_ordinal=1,
        predecessor_id=None,
        created_at=assignment_at,
        producer_digest=_digest("producer"),
        build_digest=_digest("build"),
        renderer_digest=_digest("renderer"),
        configuration_digest=_digest("presentation-configuration"),
        experiment_epoch_id=presentation_experiment.experiment_epoch_id,
        experiment_epoch_digest=presentation_experiment.semantic_digest,
        study_registration_id=presentation_experiment.study_registration_id,
        study_registration_digest=presentation_experiment.study_registration_digest,
        closed_baseline_id=baseline.baseline_epoch_id,
        closed_baseline_digest=baseline.semantic_digest,
        hypothesis_id="hypothesis:accessible-ordering",
        estimands=presentation_experiment.estimands,
        falsifiers=presentation_experiment.falsifiers,
        operator_id="operator:ember",
        session_id="session:001",
        scene_id="scene:001",
        decision_opportunity_id="opportunity:001",
        assignment_unit="session",
        cluster_interference_id="cluster:session-day",
        study_cell="cell:eligible",
        sequence=1,
        period=1,
        as_of_evidence=(
            EvidenceRef(
                "evidence:view", _digest("view-evidence"), assignment_at, assignment_at, 180
            ),
        ),
        maximum_input_available_at=assignment_at,
        maximum_input_commit_seq=200,
        assignment_at=assignment_at,
        stage_deadline=assignment_at + timedelta(seconds=2),
        reveal_deadline=assignment_at + timedelta(seconds=3),
        glass_view_id="glass-view:immutable-001",
        glass_view_digest=_digest("glass-view"),
        glass_mode="ordinary_evidence",
        eligible_evidence_artifact_id="eligible-evidence:001",
        eligible_evidence_digest=presentation_experiment.eligible_evidence_digest,
        denominator=denominator,
        coverage_state_ids=("healthy_coverage",),
        gap_ids=(),
        refusal_ids=(),
        authority_rungs=("observed", "semantic_projection"),
        assignment=PresentationAssignment(
            "committed_session_randomization",
            (
                ("arm:baseline", presentation_baseline),
                ("arm:candidate", presentation_candidate),
            ),
            "arm:candidate",
            RationalProbability(1, 2),
            "stratum:eligible",
            "block:session-001",
            _digest("seed:presentation"),
            _digest("allocation:presentation"),
            "concealed_until_assignment",
            "outcome_blinded",
        ),
        policy=PresentationPolicy(
            "policy:presentation-candidate",
            "1",
            presentation_candidate,
            tuple(sorted(eligible_items)),
            ("supported_evidence",),
            tuple(sorted(eligible_items)),
            (),
            tuple(sorted(eligible_items)),
            "registered_nonresponsive_grouping",
            (),
            (),
            ("supported_evidence",),
            "concise_with_operator_expand",
        ),
        safety=PresentationSafety(
            baseline.safety_content_digest,
            safety_fields,
            True,
            safety_fields,
        ),
        accessibility=_accessibility(),
        burden=PresentationBurden(
            1,
            1,
            60,
            60,
            60,
            "optional_closeout",
            300,
            0,
            True,
            True,
            "fixed_safety_baseline_view",
        ),
        evidence_only_commands=("expand_provenance", "inspect_gap", "switch_text_table"),
        receipt_not_yet_claimed=True,
        reveal_not_started=True,
    ).sealed()
    return (
        baseline,
        closure,
        sensing_experiment,
        decision,
        report,
        presentation_experiment,
        intervention,
    )


def deterministic_artifacts() -> tuple[UnverifiedSemantic, ...]:
    """Return a stable admitted chain; no external state is read or changed."""

    (
        baseline,
        closure,
        sensing_experiment,
        decision,
        report,
        presentation_experiment,
        intervention,
    ) = _objects()
    return (
        admit_baseline(baseline),
        admit_baseline_closure(baseline, closure),
        admit_experiment(baseline, closure, sensing_experiment),
        admit_sensing_decision(sensing_experiment, decision),
        admit_coverage_report(sensing_experiment, report, (decision,)),
        admit_experiment(baseline, closure, presentation_experiment),
        admit_presentation_intervention(presentation_experiment, intervention),
    )
