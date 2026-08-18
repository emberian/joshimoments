"""Pure, unverified semantic contracts for prospective epistemic campaigns.

Nothing in this module opens a store, collects evidence, changes a product surface, or creates an
economic effect.  The objects are deliberately small caller-owned projections for fixture and
adapter testing only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes, require_qualified_sha256
from ..errors import ManifestError

SCHEMA_ID = "joshi.analysis.wave6-epistemic-campaigns/v1"
IMPLEMENTATION_STATUS = "unverified_semantic"
AUTHORITY = "read_only_no_execution"
PROBABILITY_SCALE_PPM = 1_000_000


class ClaimFamily(StrEnum):
    DIRECTIONAL_RESPONSE = "c1_directional_response"
    HAZARD_TIME_TO_EVENT = "c2_hazard_time_to_event"
    LIQUIDITY_ROUTE_ACTIVATION = "c3_liquidity_route_activation"
    PROVIDER_ADVERSE_SELECTION = "c4_provider_adverse_selection"
    RECOGNITION_DISPOSITION = "c5_recognition_disposition"


class ScoringRule(StrEnum):
    DIRECTIONAL_MULTICLASS_BRIER = "directional_multiclass_brier"
    DIRECTIONAL_MULTICLASS_LOG = "directional_multiclass_log"
    HAZARD_JOINT_CATEGORICAL_BRIER = "hazard_joint_categorical_brier"
    HAZARD_JOINT_CATEGORICAL_LOG = "hazard_joint_categorical_log"
    LIQUIDITY_BINARY_BRIER = "liquidity_binary_brier"
    LIQUIDITY_BINARY_LOG = "liquidity_binary_log"
    PROVIDER_STATE_MULTICLASS_BRIER = "provider_state_multiclass_brier"
    PROVIDER_STATE_MULTICLASS_LOG = "provider_state_multiclass_log"
    RECOGNITION_BINARY_BRIER = "recognition_binary_brier"
    RECOGNITION_BINARY_LOG = "recognition_binary_log"


CLAIM_OUTCOME_DOMAINS: dict[ClaimFamily, tuple[str, ...]] = {
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
}

ALLOWED_SCORING_RULES: dict[ClaimFamily, tuple[ScoringRule, ...]] = {
    ClaimFamily.DIRECTIONAL_RESPONSE: (
        ScoringRule.DIRECTIONAL_MULTICLASS_BRIER,
        ScoringRule.DIRECTIONAL_MULTICLASS_LOG,
    ),
    ClaimFamily.HAZARD_TIME_TO_EVENT: (
        ScoringRule.HAZARD_JOINT_CATEGORICAL_BRIER,
        ScoringRule.HAZARD_JOINT_CATEGORICAL_LOG,
    ),
    ClaimFamily.LIQUIDITY_ROUTE_ACTIVATION: (
        ScoringRule.LIQUIDITY_BINARY_BRIER,
        ScoringRule.LIQUIDITY_BINARY_LOG,
    ),
    ClaimFamily.PROVIDER_ADVERSE_SELECTION: (
        ScoringRule.PROVIDER_STATE_MULTICLASS_BRIER,
        ScoringRule.PROVIDER_STATE_MULTICLASS_LOG,
    ),
    ClaimFamily.RECOGNITION_DISPOSITION: (
        ScoringRule.RECOGNITION_BINARY_BRIER,
        ScoringRule.RECOGNITION_BINARY_LOG,
    ),
}

DEFAULT_SCORING_RULE: dict[ClaimFamily, ScoringRule] = {
    family: rules[0] for family, rules in ALLOWED_SCORING_RULES.items()
}

BINARY_BRIER_RULES = frozenset(
    {
        ScoringRule.LIQUIDITY_BINARY_BRIER,
        ScoringRule.RECOGNITION_BINARY_BRIER,
    }
)


class SubmissionDisposition(StrEnum):
    CATEGORICAL = "categorical"
    ABSTAIN = "abstain"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    REFUSED = "refused"


class AdjudicationDisposition(StrEnum):
    RESOLVED_OBSERVED = "resolved_observed"
    HEALTHY_NO_EVENT_THROUGH_HORIZON = "healthy_no_event_through_horizon"
    RESOLVED_FROZEN_REPLAY = "resolved_frozen_replay"
    ADMINISTRATIVE_CENSORED = "administrative_censored"
    SOURCE_LOSS_CENSORED = "source_loss_censored"
    INTERVAL_CENSORED = "interval_censored"
    LEFT_TRUNCATED = "left_truncated"
    COMPETING_EVENT = "competing_event"
    ROUTE_OR_LIQUIDATION_REFUSAL = "route_or_liquidation_refusal"
    INTERVENTION_INVALIDATED = "intervention_invalidated"
    CONFLICTING = "conflicting"
    UNSUPPORTED = "unsupported"
    OPEN = "open"


class EnsembleEligibility(StrEnum):
    SEMANTICALLY_INELIGIBLE = "semantically_ineligible"
    BLOCKED_MISSING_DURABLE_PROOF = "blocked_missing_durable_proof"


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ManifestError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _stable(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ManifestError(f"{field_name} must be a bounded, unpadded stable string")
    return value


def _sorted_unique(values: tuple[str, ...], field_name: str, *, nonempty: bool = False) -> None:
    if tuple(sorted(set(values))) != values or (nonempty and not values):
        raise ManifestError(
            f"{field_name} must be sorted, unique, and{' nonempty' if nonempty else ''}"
        )
    for value in values:
        _stable(value, field_name)


def _digest(value: Any) -> str:
    return qualified_sha256_bytes(canonical_json_bytes(value))


def _sha256(value: str, field_name: str) -> str:
    try:
        return require_qualified_sha256(value, field_name)
    except ValueError as error:
        raise ManifestError(str(error)) from error


def _semantic_id(prefix: str, material: dict[str, Any]) -> str:
    return f"{prefix}-{_digest(material)[7:39]}"


def _iso(value: datetime, field_name: str) -> str:
    return _aware(value, field_name).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    evidence_id: str
    digest: str
    available_at: datetime
    valid_from: datetime
    valid_through: datetime
    authority: str
    domain: str
    carrier: str
    unit: str
    coverage_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("evidence_id", "authority", "domain", "carrier", "unit"):
            _stable(getattr(self, field_name), field_name)
        _sha256(self.digest, "evidence digest")
        available = _aware(self.available_at, "available_at")
        valid_from = _aware(self.valid_from, "valid_from")
        valid_through = _aware(self.valid_through, "valid_through")
        if valid_through < valid_from:
            raise ManifestError("evidence validity interval is reversed")
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_through", valid_through)
        _sorted_unique(self.coverage_ids, "coverage_ids")
        _sorted_unique(self.gap_ids, "gap_ids")

    def material(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "digest": self.digest,
            "available_at": _iso(self.available_at, "available_at"),
            "valid_from": _iso(self.valid_from, "valid_from"),
            "valid_through": _iso(self.valid_through, "valid_through"),
            "authority": self.authority,
            "domain": self.domain,
            "carrier": self.carrier,
            "unit": self.unit,
            "coverage_ids": list(self.coverage_ids),
            "gap_ids": list(self.gap_ids),
        }


@dataclass(frozen=True, slots=True)
class FrozenUniverse:
    universe_id: str
    digest: str
    eligible_subject_ids: tuple[str, ...]
    inclusion_rule: str
    exclusion_reason_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _stable(self.universe_id, "universe_id")
        _stable(self.inclusion_rule, "inclusion_rule")
        _sha256(self.digest, "universe digest")
        _sorted_unique(self.eligible_subject_ids, "eligible_subject_ids", nonempty=True)
        _sorted_unique(self.exclusion_reason_ids, "exclusion_reason_ids")

    @property
    def semantic_digest(self) -> str:
        return _digest(
            {
                "universe_id": self.universe_id,
                "declared_digest": self.digest,
                "eligible_subject_ids": list(self.eligible_subject_ids),
                "inclusion_rule": self.inclusion_rule,
                "exclusion_reason_ids": list(self.exclusion_reason_ids),
            }
        )


@dataclass(frozen=True, slots=True)
class ClaimDefinition:
    definition_id: str
    version: int
    family: ClaimFamily
    outcome_ids: tuple[str, ...]
    target_spec_digest: str
    score_rule: ScoringRule | None = None
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.definition_id, "definition_id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version <= 0:
            raise ManifestError("definition version must be positive")
        if self.outcome_ids != CLAIM_OUTCOME_DOMAINS[self.family]:
            raise ManifestError(
                "claim definition outcome domain differs from its exact target family"
            )
        score_rule = self.score_rule or DEFAULT_SCORING_RULE[self.family]
        if not isinstance(score_rule, ScoringRule):
            raise ManifestError("claim definition must use a typed registered scoring rule")
        if score_rule not in ALLOWED_SCORING_RULES[self.family]:
            raise ManifestError(
                "claim definition scoring rule is incompatible with its target family"
            )
        object.__setattr__(self, "score_rule", score_rule)
        if self.authority != AUTHORITY:
            raise ManifestError("campaign authority must remain read_only_no_execution")
        _sha256(self.target_spec_digest, "target_spec_digest")

    @property
    def semantic_digest(self) -> str:
        return _digest(
            {
                "definition_id": self.definition_id,
                "version": self.version,
                "family": self.family.value,
                "outcome_ids": list(self.outcome_ids),
                "target_spec_digest": self.target_spec_digest,
                "score_rule": self.score_rule.value,
                "authority": self.authority,
            }
        )


@dataclass(frozen=True, slots=True)
class ClaimOccurrence:
    definition: ClaimDefinition
    subject_id: str
    scene_digest: str
    universe: FrozenUniverse
    evidence: tuple[EvidenceInput, ...]
    information_cutoff: datetime
    occurrence_commit_at: datetime
    issue_deadline: datetime
    target_origin: datetime
    horizon_at: datetime
    knowledge_deadline: datetime
    eligible_forecaster_ids: tuple[str, ...]
    required_first_round_count: int
    reveal_not_before: datetime
    capability_ids: tuple[str, ...]
    authority: str = AUTHORITY
    occurrence_id: str = field(init=False)

    def __post_init__(self) -> None:
        _stable(self.subject_id, "subject_id")
        if self.subject_id not in self.universe.eligible_subject_ids:
            raise ManifestError("subject must belong to the frozen eligible universe")
        _sha256(self.scene_digest, "scene_digest")
        if not self.evidence:
            raise ManifestError("occurrence needs a frozen evidence manifest")
        if tuple(sorted(input.evidence_id for input in self.evidence)) != tuple(
            input.evidence_id for input in self.evidence
        ):
            raise ManifestError("evidence must be sorted by evidence_id and duplicate-free")
        clocks = tuple(
            _aware(getattr(self, name), name)
            for name in (
                "information_cutoff",
                "occurrence_commit_at",
                "issue_deadline",
                "target_origin",
                "horizon_at",
                "knowledge_deadline",
            )
        )
        maximum_input = max(input.available_at for input in self.evidence)
        if not (
            maximum_input <= clocks[0] <= clocks[1] <= clocks[2] < clocks[3] < clocks[4] < clocks[5]
        ):
            raise ManifestError("B0 occurrence clocks or frozen evidence cutoff are incoherent")
        reveal_not_before = _aware(self.reveal_not_before, "reveal_not_before")
        if reveal_not_before < clocks[2]:
            raise ManifestError("reveal_not_before must not precede issue_deadline")
        for name, value in zip(
            (
                "information_cutoff",
                "occurrence_commit_at",
                "issue_deadline",
                "target_origin",
                "horizon_at",
                "knowledge_deadline",
            ),
            clocks,
            strict=True,
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "reveal_not_before", reveal_not_before)
        _sorted_unique(self.eligible_forecaster_ids, "eligible_forecaster_ids", nonempty=True)
        if self.required_first_round_count != len(self.eligible_forecaster_ids):
            raise ManifestError("required first-round count must equal the complete eligible set")
        _sorted_unique(self.capability_ids, "capability_ids", nonempty=True)
        if self.authority != AUTHORITY:
            raise ManifestError("campaign authority must remain read_only_no_execution")
        object.__setattr__(self, "occurrence_id", self._canonical_occurrence_id())

    @property
    def frozen_evidence_digest(self) -> str:
        return _digest([input.material() for input in self.evidence])

    def _canonical_occurrence_id(self) -> str:
        return _semantic_id(
            "occ",
            {
                "definition_digest": self.definition.semantic_digest,
                "subject_id": self.subject_id,
                "scene_digest": self.scene_digest,
                "universe_digest": self.universe.semantic_digest,
                "frozen_evidence_digest": self.frozen_evidence_digest,
                "information_cutoff": _iso(self.information_cutoff, "information_cutoff"),
                "occurrence_commit_at": _iso(self.occurrence_commit_at, "occurrence_commit_at"),
                "issue_deadline": _iso(self.issue_deadline, "issue_deadline"),
                "target_origin": _iso(self.target_origin, "target_origin"),
                "horizon_at": _iso(self.horizon_at, "horizon_at"),
                "knowledge_deadline": _iso(self.knowledge_deadline, "knowledge_deadline"),
                "eligible_forecaster_ids": list(self.eligible_forecaster_ids),
                "required_first_round_count": self.required_first_round_count,
                "reveal_not_before": _iso(self.reveal_not_before, "reveal_not_before"),
                "capability_ids": list(self.capability_ids),
                "authority": self.authority,
            },
        )

    @property
    def semantic_id(self) -> str:
        return self.occurrence_id


@dataclass(frozen=True, slots=True)
class ForecastSubmission:
    submission_id: str
    occurrence_id: str
    occurrence_semantic_id: str
    definition_semantic_digest: str
    forecaster_id: str
    primary_lineage_id: str
    input_manifest_digest: str
    maximum_input_availability: datetime
    submission_cutoff: datetime
    produced_at: datetime
    received_at: datetime
    disposition: SubmissionDisposition
    probabilities_ppm: tuple[int, ...] = ()
    visible_forecast_ids_before_submit: tuple[str, ...] = ()
    visible_ensemble_ids_before_submit: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "submission_id",
            "occurrence_id",
            "occurrence_semantic_id",
            "forecaster_id",
            "primary_lineage_id",
        ):
            _stable(getattr(self, field_name), field_name)
        _sha256(self.definition_semantic_digest, "definition_semantic_digest")
        _sha256(self.input_manifest_digest, "input_manifest_digest")
        clocks = tuple(
            _aware(getattr(self, name), name)
            for name in (
                "maximum_input_availability",
                "submission_cutoff",
                "produced_at",
                "received_at",
            )
        )
        for name, value in zip(
            ("maximum_input_availability", "submission_cutoff", "produced_at", "received_at"),
            clocks,
            strict=True,
        ):
            object.__setattr__(self, name, value)
        _sorted_unique(
            self.visible_forecast_ids_before_submit, "visible_forecast_ids_before_submit"
        )
        _sorted_unique(
            self.visible_ensemble_ids_before_submit, "visible_ensemble_ids_before_submit"
        )
        if self.disposition is SubmissionDisposition.CATEGORICAL:
            if not self.probabilities_ppm or sum(self.probabilities_ppm) != PROBABILITY_SCALE_PPM:
                raise ManifestError("categorical probabilities must sum exactly to one million ppm")
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in self.probabilities_ppm
            ):
                raise ManifestError("probabilities must be nonnegative integer ppm")
        elif self.probabilities_ppm:
            raise ManifestError("noncategorical dispositions cannot carry probabilities")


@dataclass(frozen=True, slots=True)
class Adjudication:
    adjudication_id: str
    occurrence_id: str
    occurrence_semantic_id: str
    definition_semantic_digest: str
    disposition: AdjudicationDisposition
    adjudicated_at: datetime
    knowledge_cutoff: datetime
    outcome_id: str | None = None
    outcome_evidence_ids: tuple[str, ...] = ()
    outcome_available_at: datetime | None = None
    coverage_complete: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("adjudication_id", "occurrence_id", "occurrence_semantic_id"):
            _stable(getattr(self, field_name), field_name)
        _sha256(self.definition_semantic_digest, "definition_semantic_digest")
        adjudicated = _aware(self.adjudicated_at, "adjudicated_at")
        cutoff = _aware(self.knowledge_cutoff, "knowledge_cutoff")
        if adjudicated < cutoff:
            raise ManifestError("adjudication cannot precede its knowledge cutoff")
        object.__setattr__(self, "adjudicated_at", adjudicated)
        object.__setattr__(self, "knowledge_cutoff", cutoff)
        _sorted_unique(self.outcome_evidence_ids, "outcome_evidence_ids")
        resolved = {
            AdjudicationDisposition.RESOLVED_OBSERVED,
            AdjudicationDisposition.HEALTHY_NO_EVENT_THROUGH_HORIZON,
            AdjudicationDisposition.RESOLVED_FROZEN_REPLAY,
        }
        if self.disposition in resolved:
            if not self.outcome_id:
                raise ManifestError("resolved adjudication needs an outcome_id")
            _stable(self.outcome_id, "outcome_id")
            if self.outcome_available_at is None:
                raise ManifestError("resolved adjudication needs an outcome availability clock")
            object.__setattr__(
                self,
                "outcome_available_at",
                _aware(self.outcome_available_at, "outcome_available_at"),
            )
        elif self.outcome_id is not None:
            raise ManifestError(
                "unresolved, censored, conflicting, or unsupported adjudication has no outcome"
            )
        if self.disposition is AdjudicationDisposition.HEALTHY_NO_EVENT_THROUGH_HORIZON and (
            not self.coverage_complete or not self.outcome_evidence_ids
        ):
            raise ManifestError("healthy survival requires nonempty complete horizon evidence")


@dataclass(frozen=True, slots=True)
class UnverifiedSemantic[T]:
    """Public result that expressly cannot be treated as a store-derived capability."""

    value: T
    semantic_id: str
    status: str = IMPLEMENTATION_STATUS
    authority: str = AUTHORITY
    durable_proof: None = None

    def __post_init__(self) -> None:
        _stable(self.semantic_id, "semantic_id")
        if (
            self.status != IMPLEMENTATION_STATUS
            or self.authority != AUTHORITY
            or self.durable_proof is not None
        ):
            raise ManifestError(
                "public campaign outputs are only unverified semantic read-only values"
            )


@dataclass(frozen=True, slots=True)
class BrierPreview:
    occurrence_id: str
    submission_id: str
    outcome_id: str
    candidate_loss_numerator: int
    denominator: int
    baseline_loss_numerator: int | None
    increment_numerator: int | None


@dataclass(frozen=True, slots=True)
class EnsemblePreflight:
    eligibility: EnsembleEligibility
    reasons: tuple[str, ...]
    required_durable_proofs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InformationCapitalTimeAccount:
    occurrence_id: str
    information_inputs_used: int
    latest_input_availability: datetime
    information_age_microseconds: int
    capital_reserved_atoms: int = 0
    capital_time_atom_microseconds: int = 0
    action_authority: str = AUTHORITY


@dataclass(frozen=True, slots=True)
class SupportMembership:
    score_id: str
    occurrence_id: str
    window_id: str
    outcome_available_at: datetime
    embargo_through: datetime
    dependence_cluster_id: str

    def __post_init__(self) -> None:
        for field_name in ("score_id", "occurrence_id", "window_id", "dependence_cluster_id"):
            _stable(getattr(self, field_name), field_name)
        available = _aware(self.outcome_available_at, "outcome_available_at")
        embargo = _aware(self.embargo_through, "embargo_through")
        if embargo < available:
            raise ManifestError("support embargo cannot precede outcome availability")
        object.__setattr__(self, "outcome_available_at", available)
        object.__setattr__(self, "embargo_through", embargo)
