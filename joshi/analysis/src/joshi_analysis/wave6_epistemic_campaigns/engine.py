"""Fail-closed semantic preflight and arithmetic previews for Wave 6 campaigns."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes
from ..errors import ManifestError, TemporalLeakageError
from .contracts import (
    AUTHORITY,
    BINARY_BRIER_RULES,
    IMPLEMENTATION_STATUS,
    PROBABILITY_SCALE_PPM,
    Adjudication,
    AdjudicationDisposition,
    BrierPreview,
    ClaimOccurrence,
    EnsembleEligibility,
    EnsemblePreflight,
    ForecastSubmission,
    InformationCapitalTimeAccount,
    SubmissionDisposition,
    SupportMembership,
    UnverifiedSemantic,
)


def _canonical_material(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _canonical_material(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical_material(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_canonical_material(item) for item in value]
    return value


def _id(prefix: str, material: object) -> str:
    digest = qualified_sha256_bytes(canonical_json_bytes(_canonical_material(material)))[7:39]
    return f"{prefix}-{digest}"


def validate_submission(
    occurrence: ClaimOccurrence, submission: ForecastSubmission
) -> UnverifiedSemantic[ForecastSubmission]:
    """Check B0 and first-round blindness; this validates no store receipt or visibility fact."""

    if (
        submission.occurrence_id != occurrence.occurrence_id
        or submission.occurrence_semantic_id != occurrence.semantic_id
    ):
        raise ManifestError("submission cannot be substituted across occurrences")
    if submission.definition_semantic_digest != occurrence.definition.semantic_digest:
        raise ManifestError("submission cannot be substituted across definition content")
    if submission.forecaster_id not in occurrence.eligible_forecaster_ids:
        raise ManifestError("submission forecaster is not in the frozen eligible set")
    if submission.input_manifest_digest != occurrence.frozen_evidence_digest:
        raise ManifestError("submission must bind the exact frozen evidence manifest")
    if submission.maximum_input_availability > occurrence.information_cutoff:
        raise TemporalLeakageError("submission input became available after the occurrence cutoff")
    if not (
        submission.maximum_input_availability
        <= submission.submission_cutoff
        == occurrence.information_cutoff
        <= occurrence.occurrence_commit_at
        <= submission.produced_at
        <= submission.received_at
        <= occurrence.issue_deadline
    ):
        raise TemporalLeakageError("submission clocks violate the registered B0 ordering")
    if submission.disposition is SubmissionDisposition.CATEGORICAL and len(
        submission.probabilities_ppm
    ) != len(occurrence.definition.outcome_ids):
        raise ManifestError("categorical forecast must use the exact registered outcome ordering")
    if (
        submission.visible_forecast_ids_before_submit
        or submission.visible_ensemble_ids_before_submit
    ):
        raise ManifestError("first-round submission declares peer or ensemble visibility")
    return UnverifiedSemantic(value=submission, semantic_id=_id("submission", asdict(submission)))


def assess_reveal(
    occurrence: ClaimOccurrence,
    submissions: tuple[ForecastSubmission, ...],
    reveal_at: datetime,
) -> UnverifiedSemantic[tuple[str, ...]]:
    """Semantically require all, not merely a favorable subset, before a reveal."""

    actual_ids = tuple(sorted(submission.forecaster_id for submission in submissions))
    if len(actual_ids) != len(set(actual_ids)):
        raise ManifestError("duplicate participant cannot manufacture first-round breadth")
    if actual_ids != occurrence.eligible_forecaster_ids:
        raise ManifestError("selective reveal is forbidden: every eligible forecaster must seal")
    for submission in submissions:
        validate_submission(occurrence, submission)
    if reveal_at.tzinfo is None or reveal_at.utcoffset() is None:
        raise ManifestError("reveal_at must be timezone-aware")
    if reveal_at < occurrence.reveal_not_before:
        raise TemporalLeakageError("reveal precedes its registered reveal_not_before clock")
    return UnverifiedSemantic(
        value=actual_ids,
        semantic_id=_id(
            "reveal-preflight", {"occurrence": occurrence.occurrence_id, "ids": actual_ids}
        ),
    )


def validate_adjudication(
    occurrence: ClaimOccurrence, adjudication: Adjudication
) -> UnverifiedSemantic[Adjudication]:
    if (
        adjudication.occurrence_id != occurrence.occurrence_id
        or adjudication.occurrence_semantic_id != occurrence.semantic_id
    ):
        raise ManifestError("adjudication cannot be substituted across occurrences")
    if adjudication.definition_semantic_digest != occurrence.definition.semantic_digest:
        raise ManifestError("adjudication cannot be substituted across definition content")
    if adjudication.knowledge_cutoff > occurrence.knowledge_deadline:
        raise TemporalLeakageError("adjudication knowledge cutoff exceeds registered deadline")
    if (
        adjudication.outcome_available_at is not None
        and adjudication.outcome_available_at > adjudication.knowledge_cutoff
    ):
        raise TemporalLeakageError(
            "outcome evidence became available after adjudication knowledge cutoff"
        )
    if adjudication.adjudicated_at < occurrence.horizon_at:
        raise TemporalLeakageError("adjudication cannot precede its target horizon")
    if (
        adjudication.outcome_id is not None
        and adjudication.outcome_id not in occurrence.definition.outcome_ids
    ):
        raise ManifestError("adjudication outcome is outside the frozen definition")
    if (
        adjudication.disposition is AdjudicationDisposition.RESOLVED_FROZEN_REPLAY
        and occurrence.definition.family.value not in {"c4_provider_adverse_selection"}
    ):
        raise ManifestError("frozen replay is not an allowed outcome path for this claim family")
    return UnverifiedSemantic(
        value=adjudication, semantic_id=_id("adjudication", asdict(adjudication))
    )


def preview_brier_score(
    occurrence: ClaimOccurrence,
    submission: ForecastSubmission,
    adjudication: Adjudication,
    baseline: ForecastSubmission | None = None,
) -> UnverifiedSemantic[BrierPreview]:
    """Return exact non-promoting Brier arithmetic only for an admissibly resolved target."""

    validate_submission(occurrence, submission)
    validate_adjudication(occurrence, adjudication)
    if submission.disposition is not SubmissionDisposition.CATEGORICAL:
        raise ManifestError("only categorical submissions receive a proper-score preview")
    if adjudication.disposition not in {
        AdjudicationDisposition.RESOLVED_OBSERVED,
        AdjudicationDisposition.HEALTHY_NO_EVENT_THROUGH_HORIZON,
        AdjudicationDisposition.RESOLVED_FROZEN_REPLAY,
    }:
        raise ManifestError(
            "censored, conflicting, missing, unsupported, and open outcomes are not scored"
        )
    if occurrence.definition.score_rule not in BINARY_BRIER_RULES:
        raise ManifestError(
            "Brier preview requires an exact binary target and registered binary Brier rule"
        )
    if len(occurrence.definition.outcome_ids) != 2:
        raise ManifestError("Brier preview cannot score a categorical or hazard outcome domain")
    assert adjudication.outcome_id is not None
    outcome_index = occurrence.definition.outcome_ids.index(adjudication.outcome_id)
    candidate_loss = sum(
        (probability - (PROBABILITY_SCALE_PPM if index == outcome_index else 0)) ** 2
        for index, probability in enumerate(submission.probabilities_ppm)
    )
    baseline_loss: int | None = None
    increment: int | None = None
    if baseline is not None:
        validate_submission(occurrence, baseline)
        if baseline.disposition is not SubmissionDisposition.CATEGORICAL:
            raise ManifestError("baseline must be a categorical submission from this occurrence")
        baseline_loss = sum(
            (probability - (PROBABILITY_SCALE_PPM if index == outcome_index else 0)) ** 2
            for index, probability in enumerate(baseline.probabilities_ppm)
        )
        increment = baseline_loss - candidate_loss
    result = BrierPreview(
        occurrence_id=occurrence.occurrence_id,
        submission_id=submission.submission_id,
        outcome_id=adjudication.outcome_id,
        candidate_loss_numerator=candidate_loss,
        denominator=PROBABILITY_SCALE_PPM**2,
        baseline_loss_numerator=baseline_loss,
        increment_numerator=increment,
    )
    return UnverifiedSemantic(value=result, semantic_id=_id("brier-preview", asdict(result)))


def preflight_ensemble(
    occurrence: ClaimOccurrence,
    submissions: tuple[ForecastSubmission, ...],
    support: tuple[SupportMembership, ...],
) -> UnverifiedSemantic[EnsemblePreflight]:
    """Assess only semantic compatibility; no result can be a qualified ensemble."""

    reasons: list[str] = []
    lineages: set[str] = set()
    if len(submissions) < 2:
        reasons.append("at_least_two_components_required")
    for submission in submissions:
        try:
            validate_submission(occurrence, submission)
        except (ManifestError, TemporalLeakageError):
            reasons.append(f"invalid_component:{submission.submission_id}")
            continue
        if submission.disposition is not SubmissionDisposition.CATEGORICAL:
            reasons.append(f"noncategorical_component:{submission.submission_id}")
        if submission.primary_lineage_id in lineages:
            reasons.append(f"duplicate_primary_lineage:{submission.primary_lineage_id}")
        lineages.add(submission.primary_lineage_id)
    if len({submission.submission_id for submission in submissions}) != len(submissions):
        reasons.append("duplicate_submission")
    if not support:
        reasons.append("vacuous_support")
    else:
        score_ids = [membership.score_id for membership in support]
        occurrence_ids = [membership.occurrence_id for membership in support]
        if len(set(score_ids)) != len(score_ids) or len(set(occurrence_ids)) != len(occurrence_ids):
            reasons.append("support_reuses_score_or_occurrence")
        if any(
            membership.embargo_through >= occurrence.information_cutoff
            or membership.outcome_available_at >= occurrence.information_cutoff
            for membership in support
        ):
            reasons.append("support_is_not_strictly_earlier_than_current_cutoff")
        clusters = {membership.dependence_cluster_id for membership in support}
        windows = {membership.window_id for membership in support}
        if len(support) < 40 or len(windows) < 2 or len(clusters) < 2:
            reasons.append("repeated_support_floor_not_met")
    if reasons:
        result = EnsemblePreflight(
            eligibility=EnsembleEligibility.SEMANTICALLY_INELIGIBLE,
            reasons=tuple(sorted(set(reasons))),
            required_durable_proofs=(),
        )
    else:
        result = EnsemblePreflight(
            eligibility=EnsembleEligibility.BLOCKED_MISSING_DURABLE_PROOF,
            reasons=(),
            required_durable_proofs=(
                "store_committed_occurrence",
                "sealed_submission_namespace",
                "store_derived_visibility_and_reveal",
                "store_derived_support_membership",
            ),
        )
    return UnverifiedSemantic(value=result, semantic_id=_id("ensemble-preflight", asdict(result)))


def account_information_capital_time(
    occurrence: ClaimOccurrence,
) -> UnverifiedSemantic[InformationCapitalTimeAccount]:
    """Disclose information age and explicitly zero economic commitment for every campaign."""

    latest = max(input.available_at for input in occurrence.evidence)
    age_us = int((occurrence.information_cutoff - latest).total_seconds() * 1_000_000)
    account = InformationCapitalTimeAccount(
        occurrence_id=occurrence.occurrence_id,
        information_inputs_used=len(occurrence.evidence),
        latest_input_availability=latest,
        information_age_microseconds=age_us,
    )
    if account.capital_reserved_atoms != 0 or account.capital_time_atom_microseconds != 0:
        raise ManifestError(
            "campaign accounting cannot reserve capital or create capital-time exposure"
        )
    return UnverifiedSemantic(
        value=account, semantic_id=_id("information-account", asdict(account))
    )


def public_status() -> dict[str, str]:
    """Small explicit capability declaration for callers and documentation generators."""

    return {
        "schema": "joshi.analysis.wave6-epistemic-campaigns/v1",
        "status": IMPLEMENTATION_STATUS,
        "authority": AUTHORITY,
        "store_capability": "none",
        "acquisition_influence": "false",
        "presentation_influence": "false",
        "action_influence": "false",
    }
