from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from joshi_analysis.errors import ManifestError, TemporalLeakageError
from joshi_analysis.wave6_epistemic_campaigns import (
    IMPLEMENTATION_STATUS,
    Adjudication,
    AdjudicationDisposition,
    ClaimDefinition,
    ClaimFamily,
    ClaimOccurrence,
    EnsembleEligibility,
    EvidenceInput,
    ForecastSubmission,
    FrozenUniverse,
    ScoringRule,
    SubmissionDisposition,
    SupportMembership,
    account_information_capital_time,
    assess_reveal,
    preflight_ensemble,
    preview_brier_score,
    public_status,
    validate_submission,
)

T0 = datetime(2026, 8, 1, 12, tzinfo=UTC)
SHA = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _definition(
    family: ClaimFamily = ClaimFamily.DIRECTIONAL_RESPONSE,
    *,
    score_rule: ScoringRule | None = None,
) -> ClaimDefinition:
    outcomes = {
        ClaimFamily.DIRECTIONAL_RESPONSE: ("down", "neutral", "up"),
        ClaimFamily.HAZARD_TIME_TO_EVENT: (
            "healthy_through_horizon",
            "first_loss_time_bin",
            "first_up_time_bin",
        ),
        ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION: ("inactive", "active"),
        ClaimFamily.PROVIDER_ADVERSE_SELECTION: (
            "adverse_selection_threshold",
            "adverse_route_or_liquidation",
            "benign_covered_survival",
        ),
        ClaimFamily.RECOGNITION_DISPOSITION: (
            "no_recorded_recognition",
            "recorded_recognition",
        ),
    }[family]
    return ClaimDefinition(
        definition_id=f"definition:{family.value}",
        version=1,
        family=family,
        outcome_ids=outcomes,
        target_spec_digest=SHA,
        score_rule=score_rule,
    )


def _occurrence(
    *,
    definition: ClaimDefinition | None = None,
    scene_digest: str = SHA,
    universe: FrozenUniverse | None = None,
    evidence: EvidenceInput | None = None,
    information_cutoff: datetime | None = None,
) -> ClaimOccurrence:
    frozen_universe = universe or FrozenUniverse(
        universe_id="universe:fixture",
        digest=SHA,
        eligible_subject_ids=("asset:fixture",),
        inclusion_rule="complete eligible fixture roster",
    )
    frozen_evidence = evidence or EvidenceInput(
        evidence_id="evidence:state",
        digest=SHA,
        available_at=T0,
        valid_from=T0 - timedelta(minutes=1),
        valid_through=T0 + timedelta(minutes=1),
        authority="h2_descriptive",
        domain="market_state",
        carrier="fixture",
        unit="atoms",
    )
    return ClaimOccurrence(
        definition=definition or _definition(),
        subject_id="asset:fixture",
        scene_digest=scene_digest,
        universe=frozen_universe,
        evidence=(frozen_evidence,),
        information_cutoff=information_cutoff or T0 + timedelta(seconds=1),
        occurrence_commit_at=T0 + timedelta(seconds=2),
        issue_deadline=T0 + timedelta(seconds=3),
        target_origin=T0 + timedelta(seconds=4),
        horizon_at=T0 + timedelta(minutes=5),
        knowledge_deadline=T0 + timedelta(minutes=6),
        eligible_forecaster_ids=("forecaster:base", "forecaster:model"),
        required_first_round_count=2,
        reveal_not_before=T0 + timedelta(seconds=3),
        capability_ids=("capability:quote-profile",),
    )


def _submission(
    occurrence: ClaimOccurrence,
    forecaster: str,
    *,
    lineage: str | None = None,
    probabilities: tuple[int, ...] | None = None,
    maximum_input: datetime = T0,
) -> ForecastSubmission:
    if probabilities is None:
        quotient, remainder = divmod(1_000_000, len(occurrence.definition.outcome_ids))
        probabilities = (quotient + remainder,) + (quotient,) * (
            len(occurrence.definition.outcome_ids) - 1
        )
    return ForecastSubmission(
        submission_id=f"submission:{occurrence.occurrence_id}:{forecaster}",
        occurrence_id=occurrence.occurrence_id,
        occurrence_semantic_id=occurrence.semantic_id,
        definition_semantic_digest=occurrence.definition.semantic_digest,
        forecaster_id=forecaster,
        primary_lineage_id=lineage or forecaster,
        input_manifest_digest=occurrence.frozen_evidence_digest,
        maximum_input_availability=maximum_input,
        submission_cutoff=occurrence.information_cutoff,
        produced_at=occurrence.occurrence_commit_at,
        received_at=occurrence.issue_deadline,
        disposition=SubmissionDisposition.CATEGORICAL,
        probabilities_ppm=probabilities,
    )


def _resolved(occurrence: ClaimOccurrence) -> Adjudication:
    return Adjudication(
        adjudication_id="adjudication:one",
        occurrence_id=occurrence.occurrence_id,
        occurrence_semantic_id=occurrence.semantic_id,
        definition_semantic_digest=occurrence.definition.semantic_digest,
        disposition=AdjudicationDisposition.RESOLVED_OBSERVED,
        adjudicated_at=occurrence.knowledge_deadline,
        knowledge_cutoff=occurrence.knowledge_deadline,
        outcome_id=occurrence.definition.outcome_ids[-1],
        outcome_evidence_ids=("outcome:one",),
        outcome_available_at=occurrence.knowledge_deadline,
        coverage_complete=True,
    )


def test_all_five_families_are_explicitly_read_only_and_outputs_are_unverified() -> None:
    for family in ClaimFamily:
        definition = _definition(family)
        assert definition.authority == "read_only_no_execution"
    output = account_information_capital_time(_occurrence())
    assert output.status == IMPLEMENTATION_STATUS
    assert output.durable_proof is None
    assert output.value.capital_reserved_atoms == 0
    assert public_status()["action_influence"] == "false"


def test_future_evidence_and_outcome_knowledge_are_refused() -> None:
    occurrence = _occurrence()
    future = _submission(
        occurrence,
        "forecaster:base",
        maximum_input=occurrence.information_cutoff + timedelta(microseconds=1),
    )
    with pytest.raises(TemporalLeakageError, match="after the occurrence cutoff"):
        validate_submission(occurrence, future)
    late = Adjudication(
        adjudication_id="adjudication:late",
        occurrence_id=occurrence.occurrence_id,
        occurrence_semantic_id=occurrence.semantic_id,
        definition_semantic_digest=occurrence.definition.semantic_digest,
        disposition=AdjudicationDisposition.RESOLVED_OBSERVED,
        adjudicated_at=occurrence.knowledge_deadline + timedelta(seconds=1),
        knowledge_cutoff=occurrence.knowledge_deadline + timedelta(microseconds=1),
        outcome_id="up",
        outcome_available_at=occurrence.knowledge_deadline + timedelta(seconds=1),
    )
    with pytest.raises(TemporalLeakageError, match="exceeds registered deadline"):
        preview_brier_score(occurrence, _submission(occurrence, "forecaster:base"), late)
    future_outcome = Adjudication(
        adjudication_id="adjudication:future-outcome",
        occurrence_id=occurrence.occurrence_id,
        occurrence_semantic_id=occurrence.semantic_id,
        definition_semantic_digest=occurrence.definition.semantic_digest,
        disposition=AdjudicationDisposition.RESOLVED_OBSERVED,
        adjudicated_at=occurrence.knowledge_deadline + timedelta(seconds=1),
        knowledge_cutoff=occurrence.knowledge_deadline,
        outcome_id="up",
        outcome_available_at=occurrence.knowledge_deadline + timedelta(microseconds=1),
    )
    with pytest.raises(TemporalLeakageError, match="outcome evidence became available"):
        preview_brier_score(occurrence, _submission(occurrence, "forecaster:base"), future_outcome)


def test_cross_occurrence_substitution_and_peer_visibility_are_refused() -> None:
    first = _occurrence()
    second = _occurrence(scene_digest=SHA_B)
    with pytest.raises(ManifestError, match="substituted across occurrences"):
        validate_submission(second, _submission(first, "forecaster:base"))
    peer_visible = replace(
        _submission(first, "forecaster:base"),
        visible_forecast_ids_before_submit=("submission:other",),
    )
    with pytest.raises(ManifestError, match="peer or ensemble visibility"):
        validate_submission(first, peer_visible)


def test_canonical_occurrence_identity_binds_definition_universe_evidence_and_clocks() -> None:
    original = _occurrence()
    assert original.occurrence_id == _occurrence().occurrence_id
    edited_definition = replace(
        original.definition,
        target_spec_digest=SHA_B,
    )
    changed_definition = _occurrence(definition=edited_definition)
    changed_universe = _occurrence(
        universe=replace(
            original.universe,
            eligible_subject_ids=("asset:fixture", "asset:other"),
        )
    )
    changed_evidence = _occurrence(evidence=replace(original.evidence[0], carrier="fixture:v2"))
    changed_clock = _occurrence(information_cutoff=T0 + timedelta(milliseconds=1500))
    assert (
        len(
            {
                original.occurrence_id,
                changed_definition.occurrence_id,
                changed_universe.occurrence_id,
                changed_evidence.occurrence_id,
                changed_clock.occurrence_id,
            }
        )
        == 5
    )
    assert original.occurrence_id == original.semantic_id
    assert original.definition.semantic_digest != edited_definition.semantic_digest


def test_edited_target_definition_cannot_reuse_submission_or_change_score_under_same_identity() -> (
    None
):
    original = _occurrence(definition=_definition(ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION))
    candidate = _submission(original, "forecaster:model", probabilities=(100_000, 900_000))
    baseline = _submission(original, "forecaster:base")
    original_preview = preview_brier_score(original, candidate, _resolved(original), baseline)
    edited = _occurrence(
        definition=replace(
            original.definition,
            target_spec_digest=SHA_B,
        )
    )
    assert edited.occurrence_id != original.occurrence_id
    rebound_submission = replace(
        candidate,
        occurrence_id=edited.occurrence_id,
        occurrence_semantic_id=edited.semantic_id,
    )
    with pytest.raises(ManifestError, match="definition content"):
        validate_submission(edited, rebound_submission)
    rebound_adjudication = replace(
        _resolved(original),
        occurrence_id=edited.occurrence_id,
        occurrence_semantic_id=edited.semantic_id,
    )
    with pytest.raises(ManifestError, match="definition content"):
        preview_brier_score(edited, rebound_submission, rebound_adjudication)
    edited_candidate = _submission(edited, "forecaster:model", probabilities=(100_000, 900_000))
    edited_baseline = _submission(edited, "forecaster:base")
    edited_adjudication = replace(
        _resolved(original),
        occurrence_id=edited.occurrence_id,
        occurrence_semantic_id=edited.semantic_id,
        definition_semantic_digest=edited.definition.semantic_digest,
    )
    edited_preview = preview_brier_score(
        edited, edited_candidate, edited_adjudication, edited_baseline
    )
    assert (
        original_preview.value.candidate_loss_numerator
        == edited_preview.value.candidate_loss_numerator
    )
    assert original_preview.value.occurrence_id != edited_preview.value.occurrence_id


def test_digest_fields_reject_non_hex_prefix_lookalikes() -> None:
    with pytest.raises(ManifestError, match="lowercase hex"):
        replace(_definition(), target_spec_digest="sha256:" + "z" * 64)


def test_selective_reveal_and_duplicate_participants_are_refused() -> None:
    occurrence = _occurrence()
    one = _submission(occurrence, "forecaster:base")
    with pytest.raises(ManifestError, match="selective reveal"):
        assess_reveal(occurrence, (one,), occurrence.reveal_not_before)
    duplicate = _submission(occurrence, "forecaster:base", lineage="lineage:other")
    with pytest.raises(ManifestError, match="duplicate participant"):
        assess_reveal(occurrence, (one, duplicate), occurrence.reveal_not_before)


def test_censoring_and_conflict_are_not_laundered_into_scoreable_outcomes() -> None:
    occurrence = _occurrence()
    submission = _submission(occurrence, "forecaster:base")
    censored = Adjudication(
        adjudication_id="adjudication:censored",
        occurrence_id=occurrence.occurrence_id,
        occurrence_semantic_id=occurrence.semantic_id,
        definition_semantic_digest=occurrence.definition.semantic_digest,
        disposition=AdjudicationDisposition.SOURCE_LOSS_CENSORED,
        adjudicated_at=occurrence.knowledge_deadline,
        knowledge_cutoff=occurrence.knowledge_deadline,
        reason="source gap",
    )
    with pytest.raises(ManifestError, match="not scored"):
        preview_brier_score(occurrence, submission, censored)


def test_brier_preview_is_exact_and_baseline_is_same_occurrence_only() -> None:
    occurrence = _occurrence(definition=_definition(ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION))
    candidate = _submission(occurrence, "forecaster:model", probabilities=(100_000, 900_000))
    baseline = _submission(occurrence, "forecaster:base", probabilities=(500_000, 500_000))
    preview = preview_brier_score(occurrence, candidate, _resolved(occurrence), baseline)
    assert preview.value.candidate_loss_numerator == 20_000_000_000
    assert preview.value.increment_numerator == 480_000_000_000
    assert preview.status == "unverified_semantic"


def test_brier_preview_refuses_log_categorical_and_hazard_rules_with_bound_identities() -> None:
    binary_brier = _occurrence(definition=_definition(ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION))
    binary_log = _occurrence(
        definition=_definition(
            ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION,
            score_rule=ScoringRule.LIQUIDITY_BINARY_LOG,
        )
    )
    assert binary_brier.occurrence_id != binary_log.occurrence_id
    with pytest.raises(ManifestError, match="exact binary target"):
        preview_brier_score(
            binary_log,
            _submission(binary_log, "forecaster:model", probabilities=(100_000, 900_000)),
            _resolved(binary_log),
        )
    directional = _occurrence()
    with pytest.raises(ManifestError, match="exact binary target"):
        preview_brier_score(
            directional,
            _submission(directional, "forecaster:model"),
            _resolved(directional),
        )
    hazard = _occurrence(definition=_definition(ClaimFamily.HAZARD_TIME_TO_EVENT))
    with pytest.raises(ManifestError, match="exact binary target"):
        preview_brier_score(
            hazard,
            _submission(hazard, "forecaster:model"),
            _resolved(hazard),
        )


def test_claim_definition_refuses_wrong_target_domain_and_rule_family() -> None:
    with pytest.raises(ManifestError, match="outcome domain"):
        replace(_definition(ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION), outcome_ids=("down", "up"))
    with pytest.raises(ManifestError, match="scoring rule is incompatible"):
        _definition(
            ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION,
            score_rule=ScoringRule.DIRECTIONAL_MULTICLASS_BRIER,
        )


def test_ensemble_preflight_rejects_vacuous_future_and_duplicate_lineage_support() -> None:
    occurrence = _occurrence()
    left = _submission(occurrence, "forecaster:base", lineage="lineage:shared")
    right = _submission(occurrence, "forecaster:model", lineage="lineage:shared")
    result = preflight_ensemble(occurrence, (left, right), ())
    assert result.value.eligibility is EnsembleEligibility.SEMANTICALLY_INELIGIBLE
    assert "vacuous_support" in result.value.reasons
    assert "duplicate_primary_lineage:lineage:shared" in result.value.reasons
    future_support = SupportMembership(
        score_id="score:one",
        occurrence_id="occurrence:historical",
        window_id="window:a",
        outcome_available_at=occurrence.information_cutoff,
        embargo_through=occurrence.information_cutoff,
        dependence_cluster_id="cluster:a",
    )
    future = preflight_ensemble(
        occurrence,
        (_submission(occurrence, "forecaster:base"), _submission(occurrence, "forecaster:model")),
        (future_support,),
    )
    assert "support_is_not_strictly_earlier_than_current_cutoff" in future.value.reasons
