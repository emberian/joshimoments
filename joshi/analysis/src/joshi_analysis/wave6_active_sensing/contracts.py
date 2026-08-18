"""Strict semantic contracts for the Wave 6 active-sensing experiment.

The types in this module describe registrations and immutable records.  They have no collector,
network, renderer, wallet, or transaction capability.  Integers are rendered as decimal strings
and probabilities as reduced rational pairs in canonical artifacts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from math import gcd
from typing import Any, ClassVar, Self


class SemanticRefusal(ValueError):
    """The proposed semantic artifact violates its registered experiment boundary."""


def _stable(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise SemanticRefusal(f"{field} must be a bounded, unpadded stable string")
    return value


def _digest(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise SemanticRefusal(f"{field} must be sha256:<64 lowercase hex>")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SemanticRefusal(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _exact_nonnegative(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SemanticRefusal(f"{field} must be an exact nonnegative integer")
    return value


def _positive(value: int, field: str) -> int:
    if _exact_nonnegative(value, field) == 0:
        raise SemanticRefusal(f"{field} must be positive")
    return value


def _sorted_unique(values: tuple[str, ...], field: str, *, allow_empty: bool = False) -> None:
    if not allow_empty and not values:
        raise SemanticRefusal(f"{field} must not be empty")
    if values != tuple(sorted(values)) or len(set(values)) != len(values):
        raise SemanticRefusal(f"{field} must be sorted and unique")
    for value in values:
        _stable(value, field)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _wire(value: Any, *, omit_semantic_digest: bool = False) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise SemanticRefusal("floating JSON numbers are forbidden in exact semantic artifacts")
    if isinstance(value, datetime):
        return _iso(_aware(value, "canonical datetime"))
    if is_dataclass(value):
        result: dict[str, Any] = {}
        for field in fields(value):
            if omit_semantic_digest and field.name == "semantic_digest":
                continue
            result[field.name] = _wire(
                getattr(value, field.name), omit_semantic_digest=omit_semantic_digest
            )
        contract = getattr(value, "CONTRACT", None)
        if contract is not None:
            result = {"contract": contract, **result}
        return result
    if isinstance(value, tuple | list):
        return [_wire(item, omit_semantic_digest=omit_semantic_digest) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise SemanticRefusal("canonical mappings require string keys")
        return {
            key: _wire(value[key], omit_semantic_digest=omit_semantic_digest)
            for key in sorted(value)
        }
    raise SemanticRefusal(f"unsupported semantic value: {type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _wire(value, omit_semantic_digest=True),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def semantic_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


class SealedSemantic:
    semantic_digest: str

    def calculated_semantic_digest(self) -> str:
        return semantic_sha256(self)

    def sealed(self) -> Self:
        if self.semantic_digest:
            self.verify_semantic_digest()
            return self
        return replace(self, semantic_digest=self.calculated_semantic_digest())

    def verify_semantic_digest(self) -> None:
        _digest(self.semantic_digest, "semantic_digest")
        if self.semantic_digest != self.calculated_semantic_digest():
            raise SemanticRefusal("semantic digest does not match canonical artifact bytes")

    def as_dict(self) -> dict[str, Any]:
        value = _wire(self)
        if not isinstance(value, dict):  # pragma: no cover - dataclass mixin invariant
            raise TypeError("sealed semantic object did not encode as an object")
        return value


class InterventionKind(StrEnum):
    SENSING_ONLY = "sensing_only"
    PRESENTATION_ONLY = "presentation_only"
    JOINT = "joint"


class AssignmentKind(StrEnum):
    FLOOR_COLD = "floor_cold"
    FLOOR_RANDOM = "floor_random"
    FLOOR_MANUAL = "floor_manual"
    FLOOR_PORTFOLIO = "floor_portfolio"
    CANDIDATE_RANDOMIZED = "candidate_randomized"
    CANDIDATE_DETERMINISTIC = "candidate_deterministic"
    CANDIDATE_VOI = "candidate_voi"


class OutcomeAssignmentKind(StrEnum):
    FLOOR_COLD = "floor_cold"
    FLOOR_RANDOM = "floor_random"
    FLOOR_MANUAL = "floor_manual"
    FLOOR_PORTFOLIO = "floor_portfolio"
    CANDIDATE_RANDOMIZED = "candidate_randomized"
    CANDIDATE_DETERMINISTIC = "candidate_deterministic"
    CANDIDATE_VOI = "candidate_voi"
    PRESENTATION_INTERVENTION = "presentation_intervention"


class FloorKind(StrEnum):
    COLD = "cold"
    RANDOM = "random"
    MANUAL = "manual"
    PORTFOLIO = "portfolio"


class ReasonOrigin(StrEnum):
    CENSUS_SCHEDULE = "census_schedule"
    RANDOM_DRAW = "random_draw"
    OPERATOR = "operator"
    PORTFOLIO_REGISTRY = "portfolio_registry"
    FIXED_POLICY = "fixed_policy"
    MODEL = "model"


class NonresponseState(StrEnum):
    COMPLETED_COVERED = "completed_covered"
    COMPLETED_PARTIAL_COVERAGE = "completed_partial_coverage"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_GAP_OR_DISCONNECT = "source_gap_or_disconnect"
    BUDGET_REFUSED_BEFORE_IO = "budget_refused_before_io"
    BUDGET_EXHAUSTED_AFTER_START = "budget_exhausted_after_start"
    CONTROL_NOT_APPLIED = "control_not_applied"
    PROVIDER_NOT_ACKNOWLEDGED = "provider_not_acknowledged"
    PRIVACY_OR_RETENTION_REFUSED = "privacy_or_retention_refused"
    PRESENTATION_NOT_STAGED = "presentation_not_staged"
    PRESENTATION_NOT_MOUNTED = "presentation_not_mounted"
    EXPOSURE_CAPTURE_INCOMPLETE = "exposure_capture_incomplete"
    OPERATOR_SKIPPED = "operator_skipped"
    OPERATOR_WITHDREW = "operator_withdrew"
    SUPERSEDED_BY_SAFETY_FALLBACK = "superseded_by_safety_fallback"
    OUTCOME_CENSORED_OR_UNSUPPORTED = "outcome_censored_or_unsupported"


class OutcomeClosureState(StrEnum):
    MATURED = "matured"
    UNSUPPORTED = "unsupported"
    CONFLICTING = "conflicting"
    SOURCE_LOSS = "source_loss"
    INTERVAL_CENSORED = "interval_censored"
    WITHDRAWN = "withdrawn"
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class RationalProbability:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        _exact_nonnegative(self.numerator, "probability numerator")
        _positive(self.denominator, "probability denominator")
        if self.numerator > self.denominator:
            raise SemanticRefusal("probability must be between zero and one")
        if gcd(self.numerator, self.denominator) != 1:
            raise SemanticRefusal("probability must be a reduced exact rational")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    evidence_id: str
    evidence_digest: str
    valid_at: datetime
    known_by: datetime
    commit_seq: int

    def __post_init__(self) -> None:
        _stable(self.evidence_id, "evidence_id")
        _digest(self.evidence_digest, "evidence_digest")
        _aware(self.valid_at, "evidence valid_at")
        _aware(self.known_by, "evidence known_by")
        _exact_nonnegative(self.commit_seq, "evidence commit_seq")


@dataclass(frozen=True, slots=True)
class BudgetVector:
    requests: int = 0
    pages: int = 0
    ingress_bytes: int = 0
    durable_bytes: int = 0
    provider_credits: int = 0
    events: int = 0
    wall_time_ms: int = 0
    attention_assignments: int = 0
    prompts: int = 0
    closeout_seconds: int = 0
    notifications: int = 0
    operator_session_seconds: int = 0

    DIMENSIONS: ClassVar[tuple[str, ...]] = (
        "requests",
        "pages",
        "ingress_bytes",
        "durable_bytes",
        "provider_credits",
        "events",
        "wall_time_ms",
        "attention_assignments",
        "prompts",
        "closeout_seconds",
        "notifications",
        "operator_session_seconds",
    )

    def __post_init__(self) -> None:
        for name in self.DIMENSIONS:
            _exact_nonnegative(getattr(self, name), f"budget {name}")

    def plus(self, other: BudgetVector) -> BudgetVector:
        return BudgetVector(
            **{name: getattr(self, name) + getattr(other, name) for name in self.DIMENSIONS}
        )

    def fits_within(self, other: BudgetVector) -> bool:
        return all(getattr(self, name) <= getattr(other, name) for name in self.DIMENSIONS)

    def nonzero_dimensions(self) -> tuple[str, ...]:
        return tuple(name for name in self.DIMENSIONS if getattr(self, name) > 0)


@dataclass(frozen=True, slots=True)
class FloorMember:
    source_operation: str
    subject_key: str
    subject_family: str
    stratum: str
    secondary_reasons: tuple[FloorKind, ...] = ()

    def __post_init__(self) -> None:
        for field, value in (
            ("source_operation", self.source_operation),
            ("subject_key", self.subject_key),
            ("subject_family", self.subject_family),
            ("stratum", self.stratum),
        ):
            _stable(value, field)
        values = tuple(reason.value for reason in self.secondary_reasons)
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise SemanticRefusal("secondary floor reasons must be sorted and unique")


@dataclass(frozen=True, slots=True)
class FloorAllocation:
    kind: FloorKind
    members: tuple[FloorMember, ...]
    budget: BudgetVector
    satisfaction_evidence_ids: tuple[str, ...]
    source_operation_budgets: tuple[tuple[str, BudgetVector], ...]
    infeasible_strata: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple((member.source_operation, member.subject_key) for member in self.members)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise SemanticRefusal(f"{self.kind.value} floor members must be sorted and unique")
        _sorted_unique(self.satisfaction_evidence_ids, "floor satisfaction evidence")
        _sorted_unique(self.infeasible_strata, "infeasible strata", allow_empty=True)
        budget_keys = tuple(key for key, _budget in self.source_operation_budgets)
        if (
            not budget_keys
            or budget_keys != tuple(sorted(budget_keys))
            or len(set(budget_keys)) != len(budget_keys)
        ):
            raise SemanticRefusal("floor source-operation budgets must be sorted and unique")
        if not {member.source_operation for member in self.members}.issubset(budget_keys):
            raise SemanticRefusal("floor member lacks its exact source-operation budget")
        combined = BudgetVector()
        for _source_operation, source_budget in self.source_operation_budgets:
            combined = combined.plus(source_budget)
        if combined != self.budget:
            raise SemanticRefusal("floor aggregate does not reconcile source-operation budgets")

    def source_budget(self, source_operation: str) -> BudgetVector:
        return dict(self.source_operation_budgets).get(source_operation, BudgetVector())

    def member(self, source_operation: str, subject_key: str) -> FloorMember | None:
        return next(
            (
                member
                for member in self.members
                if member.source_operation == source_operation and member.subject_key == subject_key
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class FloorPlan:
    cold: FloorAllocation
    random: FloorAllocation
    manual: FloorAllocation
    portfolio: FloorAllocation
    required_cold_strata: tuple[str, ...]
    eligible_manual_families: tuple[str, ...]
    required_portfolio_subjects: tuple[str, ...]
    non_census_hot_subject_slots: int
    non_census_capacity: BudgetVector
    non_census_source_operation_capacities: tuple[tuple[str, BudgetVector], ...]
    initial_random_minimum_ppm: int = 200_000

    def __post_init__(self) -> None:
        expected = (
            (self.cold, FloorKind.COLD),
            (self.random, FloorKind.RANDOM),
            (self.manual, FloorKind.MANUAL),
            (self.portfolio, FloorKind.PORTFOLIO),
        )
        for allocation, kind in expected:
            if allocation.kind is not kind:
                raise SemanticRefusal(f"{kind.value} floor is filed under the wrong class")
        _sorted_unique(self.required_cold_strata, "required cold strata", allow_empty=True)
        _sorted_unique(self.eligible_manual_families, "eligible manual families", allow_empty=True)
        _sorted_unique(
            self.required_portfolio_subjects,
            "required portfolio subjects",
            allow_empty=True,
        )
        _exact_nonnegative(self.non_census_hot_subject_slots, "non-census hot slots")
        capacity_keys = tuple(
            source_operation
            for source_operation, _capacity in self.non_census_source_operation_capacities
        )
        if (
            not capacity_keys
            or capacity_keys != tuple(sorted(capacity_keys))
            or len(set(capacity_keys)) != len(capacity_keys)
        ):
            raise SemanticRefusal(
                "non-census source-operation capacities must be sorted and unique"
            )
        combined_capacity = BudgetVector()
        for _source_operation, source_capacity in self.non_census_source_operation_capacities:
            combined_capacity = combined_capacity.plus(source_capacity)
        if combined_capacity != self.non_census_capacity:
            raise SemanticRefusal(
                "non-census capacity does not reconcile source-operation capacities"
            )
        if self.initial_random_minimum_ppm != 200_000:
            raise SemanticRefusal("the initial Wave 6 random minimum must be exactly 20 percent")

        primaries: list[tuple[str, str]] = []
        for allocation, _kind in expected:
            primaries.extend(
                (member.source_operation, member.subject_key) for member in allocation.members
            )
        if len(set(primaries)) != len(primaries):
            raise SemanticRefusal("one source-operation subject cannot consume two primary floors")

        represented = {member.stratum for member in self.cold.members}
        missing_strata = (
            set(self.required_cold_strata) - represented - set(self.cold.infeasible_strata)
        )
        if missing_strata:
            raise SemanticRefusal(f"cold floor starves registered strata: {sorted(missing_strata)}")

        manual_families = {member.subject_family for member in self.manual.members}
        missing_families = {"mint", "wallet"}.intersection(
            self.eligible_manual_families
        ) - manual_families
        if missing_families:
            raise SemanticRefusal(
                f"manual floor lacks required eligible families: {sorted(missing_families)}"
            )

        portfolio_keys = {member.subject_key for member in self.portfolio.members}
        if not set(self.required_portfolio_subjects).issubset(portfolio_keys):
            raise SemanticRefusal("portfolio floor omits a registered in-scope subject")

        required_slots = (
            self.non_census_hot_subject_slots * self.initial_random_minimum_ppm + 999_999
        ) // 1_000_000
        if len(self.random.members) < required_slots:
            raise SemanticRefusal("random floor starves the registered absolute slot minimum")
        for source_operation, source_capacity in self.non_census_source_operation_capacities:
            source_random_floor = self.random.source_budget(source_operation)
            for name in source_capacity.nonzero_dimensions():
                capacity = getattr(source_capacity, name)
                floor = getattr(source_random_floor, name)
                required = (capacity * self.initial_random_minimum_ppm + 999_999) // 1_000_000
                if floor < required:
                    raise SemanticRefusal(
                        f"random floor starves {source_operation} budget dimension {name}"
                    )

    def allocations(self) -> tuple[FloorAllocation, ...]:
        return (self.cold, self.random, self.manual, self.portfolio)

    def combined_budget(self, source_operation: str) -> BudgetVector:
        total = BudgetVector()
        for allocation in self.allocations():
            total = total.plus(allocation.source_budget(source_operation))
        return total


@dataclass(frozen=True, slots=True)
class BudgetEnvelope:
    source_operation: str
    registered_run_budget_digest: str
    run_budget: BudgetVector
    census_reserve: BudgetVector
    recovery_reserve: BudgetVector
    floors: FloorPlan
    candidate_ceiling: BudgetVector
    provider_currency_caps: tuple[tuple[str, int], ...] = ()
    chain_native_caps: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        _stable(self.source_operation, "source_operation")
        _digest(self.registered_run_budget_digest, "registered_run_budget_digest")
        if self.provider_currency_caps or self.chain_native_caps:
            raise SemanticRefusal("read-only Wave 6 cannot register currency or chain-native caps")
        total = self.census_reserve.plus(self.recovery_reserve)
        total = total.plus(self.floors.combined_budget(self.source_operation)).plus(
            self.candidate_ceiling
        )
        if not total.fits_within(self.run_budget):
            over = [
                name
                for name in BudgetVector.DIMENSIONS
                if getattr(total, name) > getattr(self.run_budget, name)
            ]
            raise SemanticRefusal(f"budget overflow in independent dimensions: {over}")


@dataclass(frozen=True, slots=True)
class CensusDenominator:
    census_occurrence_ids: tuple[str, ...]
    membership_artifact_id: str
    membership_digest: str
    universe_digest: str
    universe_count: int
    available_through: datetime
    commit_through: int
    source_evidence_ids: tuple[str, ...]
    coverage_evidence_ids: tuple[str, ...]
    product_parity_receipt_id: str | None = None

    def __post_init__(self) -> None:
        _sorted_unique(self.census_occurrence_ids, "census occurrences")
        _stable(self.membership_artifact_id, "membership_artifact_id")
        _digest(self.membership_digest, "membership_digest")
        _digest(self.universe_digest, "universe_digest")
        _positive(self.universe_count, "universe_count")
        _aware(self.available_through, "denominator available_through")
        _exact_nonnegative(self.commit_through, "denominator commit_through")
        _sorted_unique(self.source_evidence_ids, "source evidence")
        _sorted_unique(self.coverage_evidence_ids, "coverage evidence")
        if self.product_parity_receipt_id is not None:
            _stable(self.product_parity_receipt_id, "product_parity_receipt_id")


@dataclass(frozen=True, slots=True)
class BurdenCeiling:
    assignments_per_session: int
    closeout_seconds_per_assignment: int
    study_seconds_per_seven_days: int
    unsolicited_research_notifications: int

    def __post_init__(self) -> None:
        for name in (
            "assignments_per_session",
            "closeout_seconds_per_assignment",
            "study_seconds_per_seven_days",
            "unsolicited_research_notifications",
        ):
            _exact_nonnegative(getattr(self, name), name)
        if self.assignments_per_session > 2:
            raise SemanticRefusal("initial burden permits at most two assignments per session")
        if self.closeout_seconds_per_assignment > 90:
            raise SemanticRefusal("closeout burden exceeds 90 seconds")
        if self.study_seconds_per_seven_days > 900:
            raise SemanticRefusal("seven-day burden exceeds 15 minutes")
        if self.unsolicited_research_notifications != 0:
            raise SemanticRefusal("unsolicited research notifications are prohibited")


@dataclass(frozen=True, slots=True)
class AccessibilityProfile:
    profile_id: str
    critical_task_evidence_ids: tuple[str, ...]
    keyboard_reachable: bool
    focus_order_stable: bool
    semantic_text_alternative: bool
    target_size_css_px: int
    contrast_and_non_color: bool
    reduced_motion: bool
    zoom_reflow_200_percent: bool
    screen_reader_evidence: bool
    live_region_restrained: bool
    nonprecision_input: bool
    renderer_capability_receipt_id: str

    def __post_init__(self) -> None:
        _stable(self.profile_id, "accessibility profile_id")
        _sorted_unique(self.critical_task_evidence_ids, "critical task accessibility evidence")
        _positive(self.target_size_css_px, "target_size_css_px")
        _stable(self.renderer_capability_receipt_id, "renderer capability receipt")
        checks = (
            self.keyboard_reachable,
            self.focus_order_stable,
            self.semantic_text_alternative,
            self.target_size_css_px >= 44,
            self.contrast_and_non_color,
            self.reduced_motion,
            self.zoom_reflow_200_percent,
            self.screen_reader_evidence,
            self.live_region_restrained,
            self.nonprecision_input,
        )
        if not all(checks):
            raise SemanticRefusal("an accessibility-critical capability lacks actual evidence")


@dataclass(frozen=True, slots=True)
class BaselineEpochRegistrationV1(SealedSemantic):
    CONTRACT: ClassVar[str] = "joshi.wave6.baseline_epoch/v1"

    baseline_epoch_id: str
    occurrence_ordinal: int
    predecessor_id: str | None
    registered_at: datetime
    start_at: datetime
    end_at_exclusive: datetime
    maximum_duration_seconds: int
    outcome_knowledge_deadline: datetime
    producer_digest: str
    build_digest: str
    source_tree_digest: str
    configuration_digest: str
    daily_use_surface_digest: str
    cockpit_publication_digest: str
    presentation_policy_digest: str
    source_registry_digest: str
    acquisition_policy_digest: str
    collector_plan_digest: str
    registered_run_digest: str
    denominator: CensusDenominator
    floors: FloorPlan
    budget_envelopes: tuple[BudgetEnvelope, ...]
    fixed_selection_rule: str
    stable_tie_break_keys: tuple[str, ...]
    journal_claim_ids: tuple[str, ...]
    journal_issue_deadline: datetime
    journal_sealed_until: datetime
    journal_input_origins: tuple[str, ...]
    safety_content_digest: str
    accessibility_mode_ids: tuple[str, ...]
    burden_ceiling: BurdenCeiling
    privacy_retention_class: str
    consent_version: str
    model_influence: str = "prohibited"
    authority: str = "read_record_replay_only"
    effect_ceiling: str = "observe_only"
    semantic_digest: str = ""

    def __post_init__(self) -> None:
        _stable(self.baseline_epoch_id, "baseline_epoch_id")
        _positive(self.occurrence_ordinal, "occurrence_ordinal")
        if self.predecessor_id is not None:
            _stable(self.predecessor_id, "predecessor_id")
        registered = _aware(self.registered_at, "registered_at")
        start = _aware(self.start_at, "start_at")
        end = _aware(self.end_at_exclusive, "end_at_exclusive")
        deadline = _aware(self.outcome_knowledge_deadline, "outcome_knowledge_deadline")
        issue = _aware(self.journal_issue_deadline, "journal_issue_deadline")
        sealed = _aware(self.journal_sealed_until, "journal_sealed_until")
        _positive(self.maximum_duration_seconds, "maximum_duration_seconds")
        if not registered < start < end <= deadline:
            raise SemanticRefusal("baseline registration/start/end/deadline ordering is invalid")
        if (end - start).total_seconds() > self.maximum_duration_seconds:
            raise SemanticRefusal("baseline window exceeds its frozen maximum duration")
        if not start <= issue <= end:
            raise SemanticRefusal("journal issue deadline must lie inside the baseline")
        if sealed < deadline:
            raise SemanticRefusal("initial journal must remain sealed through outcome adjudication")
        for name in (
            "producer_digest",
            "build_digest",
            "source_tree_digest",
            "configuration_digest",
            "daily_use_surface_digest",
            "cockpit_publication_digest",
            "presentation_policy_digest",
            "source_registry_digest",
            "acquisition_policy_digest",
            "collector_plan_digest",
            "registered_run_digest",
            "safety_content_digest",
        ):
            _digest(getattr(self, name), name)
        _stable(self.fixed_selection_rule, "fixed_selection_rule")
        _sorted_unique(self.stable_tie_break_keys, "stable tie-break keys")
        _sorted_unique(self.journal_claim_ids, "journal claim IDs")
        _sorted_unique(self.journal_input_origins, "journal input origins")
        forbidden = ("model", "forecast", "embedding", "score", "uncertainty", "voi", "analog")
        if any(token in self.fixed_selection_rule.lower() for token in forbidden) or any(
            token in key.lower() for token in forbidden for key in self.stable_tie_break_keys
        ):
            raise SemanticRefusal("model-derived selection cannot influence the initial journal")
        if any(
            any(token in origin.lower() for token in forbidden)
            for origin in self.journal_input_origins
        ):
            raise SemanticRefusal("model-derived input cannot influence the initial journal")
        _sorted_unique(self.accessibility_mode_ids, "accessibility modes")
        _stable(self.privacy_retention_class, "privacy_retention_class")
        _stable(self.consent_version, "consent_version")
        if self.model_influence != "prohibited":
            raise SemanticRefusal("baseline model influence must be literally prohibited")
        if self.authority != "read_record_replay_only" or self.effect_ceiling != "observe_only":
            raise SemanticRefusal("baseline authority may only read, record, replay, and observe")
        keys = tuple(envelope.source_operation for envelope in self.budget_envelopes)
        if not keys or keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise SemanticRefusal("budget envelopes must be nonempty, sorted, and unique")
        if any(envelope.floors != self.floors for envelope in self.budget_envelopes):
            raise SemanticRefusal("baseline budget envelope changed its protected floor plan")
        if self.denominator.available_through > registered:
            raise SemanticRefusal("baseline denominator was not sealed by registration time")
        if self.semantic_digest:
            self.verify_semantic_digest()


@dataclass(frozen=True, slots=True)
class BaselineClosureV1(SealedSemantic):
    CONTRACT: ClassVar[str] = "joshi.wave6.baseline_closure/v1"

    closure_id: str
    baseline_epoch_id: str
    baseline_registration_digest: str
    closed_at: datetime
    close_state: str
    close_reason: str
    denominator_digest: str
    denominator_preserved: bool
    outcome_responsive_stop_or_extension: bool
    semantic_digest: str = ""

    def __post_init__(self) -> None:
        _stable(self.closure_id, "closure_id")
        _stable(self.baseline_epoch_id, "baseline_epoch_id")
        _digest(self.baseline_registration_digest, "baseline_registration_digest")
        _aware(self.closed_at, "closed_at")
        if self.close_state not in {"complete", "incomplete"}:
            raise SemanticRefusal("baseline close_state must be complete or incomplete")
        _stable(self.close_reason, "close_reason")
        _digest(self.denominator_digest, "denominator_digest")
        if not self.denominator_preserved:
            raise SemanticRefusal("baseline closure must preserve the registered denominator")
        if self.outcome_responsive_stop_or_extension:
            raise SemanticRefusal("baseline cannot stop or extend in response to outcomes")
        if self.semantic_digest:
            self.verify_semantic_digest()


@dataclass(frozen=True, slots=True)
class VoiGateEvidence:
    claim_family: str
    study_cells: tuple[str, ...]
    matured_prospective_occurrences: int
    mechanism_validation_occurrences: int
    chronological: bool
    outcome_embargoed: bool
    nonadjacent_repetitions: bool
    calibration_supported: bool
    proper_score_increment_supported: bool
    negative_controls_passed: bool
    uncertainty_exceeds_measurement_error: bool
    completed_non_voi_cost_epochs: int
    cost_evidence_cutoff: datetime
    fit_cutoff: datetime
    floors_and_probabilities_preserved: bool
    estimator_digest: str
    support_boundary_digest: str
    separately_reviewed_registration_id: str
    attainable_action_set: tuple[str, ...]
    includes_abstention_and_refusals: bool
    common_downstream_policy_digest: str
    declared_utility_digest: str

    def __post_init__(self) -> None:
        _stable(self.claim_family, "VOI claim family")
        _sorted_unique(self.study_cells, "VOI study cells")
        _exact_nonnegative(self.matured_prospective_occurrences, "matured occurrences")
        _exact_nonnegative(self.mechanism_validation_occurrences, "validation occurrences")
        _exact_nonnegative(self.completed_non_voi_cost_epochs, "completed non-VOI epochs")
        _aware(self.cost_evidence_cutoff, "cost evidence cutoff")
        _aware(self.fit_cutoff, "fit cutoff")
        for name in (
            "estimator_digest",
            "support_boundary_digest",
            "common_downstream_policy_digest",
            "declared_utility_digest",
        ):
            _digest(getattr(self, name), name)
        _stable(self.separately_reviewed_registration_id, "reviewed registration ID")
        _sorted_unique(self.attainable_action_set, "attainable action set")
        normalized_actions = {action.lower() for action in self.attainable_action_set}
        if not any("abstain" in action for action in normalized_actions) or not any(
            "refus" in action for action in normalized_actions
        ):
            raise SemanticRefusal("VOI action set must explicitly retain abstention and refusals")

    def admissible_at(self, registered_at: datetime) -> bool:
        return all(
            (
                self.matured_prospective_occurrences > self.mechanism_validation_occurrences,
                self.matured_prospective_occurrences > 20,
                self.chronological,
                self.outcome_embargoed,
                self.nonadjacent_repetitions,
                self.calibration_supported,
                self.proper_score_increment_supported,
                self.negative_controls_passed,
                self.uncertainty_exceeds_measurement_error,
                self.completed_non_voi_cost_epochs > 0,
                self.cost_evidence_cutoff <= registered_at,
                self.fit_cutoff <= registered_at,
                self.floors_and_probabilities_preserved,
                self.includes_abstention_and_refusals,
            )
        )


@dataclass(frozen=True, slots=True)
class ExperimentEpochRegistrationV1(SealedSemantic):
    CONTRACT: ClassVar[str] = "joshi.wave6.experiment_epoch/v1"

    experiment_epoch_id: str
    occurrence_ordinal: int
    predecessor_id: str | None
    registered_at: datetime
    start_at: datetime
    end_at_exclusive: datetime
    outcome_knowledge_deadline: datetime
    closed_baseline_id: str
    closed_baseline_digest: str
    baseline_closed_at: datetime
    study_registration_id: str
    study_registration_digest: str
    primary_hypothesis: str
    estimands: tuple[str, ...]
    falsifiers: tuple[str, ...]
    primary_outcome_metrics: tuple[str, ...]
    analysis_population: str
    stopping_rule: str
    intervention_kind: InterventionKind
    assignment_unit: str
    cluster_unit: str
    eligible_universe_digest: str
    eligible_evidence_digest: str
    registered_denominator: CensusDenominator
    eligible_assignment_unit_keys: tuple[str, ...]
    eligible_public_subject_keys: tuple[str, ...]
    registered_study_cells: tuple[str, ...]
    allocation_probabilities: tuple[tuple[str, RationalProbability], ...]
    allocation_arm_digests: tuple[tuple[str, str], ...]
    baseline_policy_digest: str
    candidate_policy_digest: str
    fixed_sensing_policy_digest: str
    fixed_presentation_policy_digest: str
    floors: FloorPlan
    budget_envelopes: tuple[BudgetEnvelope, ...]
    required_coverage_states: tuple[str, ...]
    required_support_states: tuple[str, ...]
    allowed_nonresponse_states: tuple[NonresponseState, ...]
    safety_content_digest: str
    accessibility_profile: AccessibilityProfile
    burden_ceiling: BurdenCeiling
    consent_version: str
    privacy_retention_class: str
    analysis_claim: str
    allows_candidate_voi: bool = False
    voi_gate: VoiGateEvidence | None = None
    semantic_digest: str = ""

    def __post_init__(self) -> None:
        _stable(self.experiment_epoch_id, "experiment_epoch_id")
        _positive(self.occurrence_ordinal, "occurrence_ordinal")
        if self.predecessor_id is not None:
            _stable(self.predecessor_id, "predecessor_id")
        registered = _aware(self.registered_at, "registered_at")
        start = _aware(self.start_at, "start_at")
        end = _aware(self.end_at_exclusive, "end_at_exclusive")
        deadline = _aware(self.outcome_knowledge_deadline, "outcome_knowledge_deadline")
        baseline_closed = _aware(self.baseline_closed_at, "baseline_closed_at")
        if not baseline_closed <= registered < start < end <= deadline:
            raise SemanticRefusal("experiment must be separately registered after baseline closure")
        for value, name in (
            (self.closed_baseline_id, "closed_baseline_id"),
            (self.study_registration_id, "study_registration_id"),
            (self.primary_hypothesis, "primary_hypothesis"),
            (self.analysis_population, "analysis_population"),
            (self.assignment_unit, "assignment_unit"),
            (self.cluster_unit, "cluster_unit"),
            (self.consent_version, "consent_version"),
            (self.privacy_retention_class, "privacy_retention_class"),
        ):
            _stable(value, name)
        for name in (
            "closed_baseline_digest",
            "study_registration_digest",
            "eligible_universe_digest",
            "eligible_evidence_digest",
            "baseline_policy_digest",
            "candidate_policy_digest",
            "fixed_sensing_policy_digest",
            "fixed_presentation_policy_digest",
            "safety_content_digest",
        ):
            _digest(getattr(self, name), name)
        _sorted_unique(self.estimands, "estimands")
        _sorted_unique(self.falsifiers, "falsifiers")
        _sorted_unique(self.primary_outcome_metrics, "primary outcome metrics")
        gaming = ("click", "dwell", "open", "trade_count", "activity", "operator_acceptance", "pnl")
        if any(
            any(token in metric.lower() for token in gaming)
            for metric in self.primary_outcome_metrics
        ):
            raise SemanticRefusal("feedback-prone activity/PnL metrics cannot be primary outcomes")
        if self.stopping_rule != "fixed_registered_end_no_outcome_adaptation":
            raise SemanticRefusal("experiment stopping must be fixed and outcome-blind")
        keys = tuple(key for key, _probability in self.allocation_probabilities)
        if not keys or keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise SemanticRefusal("allocation probabilities must be nonempty, sorted, and unique")
        arm_keys = tuple(key for key, _digest_value in self.allocation_arm_digests)
        if arm_keys != keys:
            raise SemanticRefusal("assignment arms must exactly close registered probabilities")
        for _arm_id, arm_digest in self.allocation_arm_digests:
            _digest(arm_digest, "allocation arm digest")
        if set(dict(self.allocation_arm_digests).values()) != {
            self.baseline_policy_digest,
            self.candidate_policy_digest,
        }:
            raise SemanticRefusal("assignment arms do not bind the registered policy digests")
        _sorted_unique(self.eligible_assignment_unit_keys, "eligible assignment unit keys")
        _sorted_unique(self.eligible_public_subject_keys, "eligible public subject keys")
        _sorted_unique(self.registered_study_cells, "registered study cells")
        if self.registered_denominator.universe_digest != self.eligible_universe_digest:
            raise SemanticRefusal("registered denominator and eligible universe digest differ")
        if self.registered_denominator.universe_count != len(self.eligible_public_subject_keys):
            raise SemanticRefusal("registered subject IDs do not close the eligible universe count")
        registered_floor_subjects = {
            member.subject_key
            for allocation in self.floors.allocations()
            for member in allocation.members
        }
        if not registered_floor_subjects.issubset(self.eligible_public_subject_keys):
            raise SemanticRefusal("protected floor contains an unregistered eligible subject")
        _sorted_unique(self.required_coverage_states, "required coverage states")
        _sorted_unique(self.required_support_states, "required support states")
        states = tuple(state.value for state in self.allowed_nonresponse_states)
        if states != tuple(sorted(states)) or set(states) != {
            state.value for state in NonresponseState
        }:
            raise SemanticRefusal("registration must preserve every typed nonresponse state")
        if self.analysis_claim not in {
            "randomized_itt",
            "identified_registered_estimand",
            "association_only",
        }:
            raise SemanticRefusal("analysis claim is not a registered claim class")
        envelope_keys = tuple(envelope.source_operation for envelope in self.budget_envelopes)
        if (
            not envelope_keys
            or envelope_keys != tuple(sorted(envelope_keys))
            or len(set(envelope_keys)) != len(envelope_keys)
        ):
            raise SemanticRefusal(
                "experiment budget envelopes must be sorted, unique, and nonempty"
            )
        if any(envelope.floors != self.floors for envelope in self.budget_envelopes):
            raise SemanticRefusal("experiment budget envelope changed its protected floor plan")
        if self.baseline_policy_digest == self.candidate_policy_digest:
            raise SemanticRefusal("baseline and candidate policies must be distinct")
        if self.allows_candidate_voi:
            if self.voi_gate is None or not self.voi_gate.admissible_at(registered):
                raise SemanticRefusal(
                    "candidate_voi requires matured support and measured cost evidence"
                )
        elif self.voi_gate is not None:
            raise SemanticRefusal("VOI evidence belongs only to a separately reviewed VOI epoch")
        if self.semantic_digest:
            self.verify_semantic_digest()


@dataclass(frozen=True, slots=True)
class EligibilityEvidence:
    eligible_artifact_id: str
    eligible_digest: str
    eligible_count: int
    inclusion_predicates: tuple[str, ...]
    exclusion_predicates: tuple[str, ...]
    support_state: str
    privacy_retention_eligible: bool
    evidence: tuple[EvidenceRef, ...]
    no_later_information: bool

    def __post_init__(self) -> None:
        _stable(self.eligible_artifact_id, "eligible artifact ID")
        _digest(self.eligible_digest, "eligible digest")
        _positive(self.eligible_count, "eligible count")
        _sorted_unique(self.inclusion_predicates, "inclusion predicates")
        _sorted_unique(self.exclusion_predicates, "exclusion predicates", allow_empty=True)
        _stable(self.support_state, "support state")
        if not self.privacy_retention_eligible:
            raise SemanticRefusal("privacy/retention-ineligible units cannot be assigned")
        if not self.evidence:
            raise SemanticRefusal("eligibility needs point-in-time evidence")
        if not self.no_later_information:
            raise SemanticRefusal("eligibility lacks a no-later-information proof")


@dataclass(frozen=True, slots=True)
class SensingReason:
    reason_kind: str
    origin: ReasonOrigin
    evidence_ids: tuple[str, ...]
    operator_command_id: str | None = None
    scene_view_id: str | None = None
    durable_acceptance_receipt_id: str | None = None
    model_proposal_id: str | None = None
    model_proposal_digest: str | None = None
    model_lineage_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _stable(self.reason_kind, "reason_kind")
        _sorted_unique(self.evidence_ids, "reason evidence IDs")
        operator_fields = (
            self.operator_command_id,
            self.scene_view_id,
            self.durable_acceptance_receipt_id,
        )
        if self.origin is ReasonOrigin.OPERATOR:
            if any(value is None for value in operator_fields):
                raise SemanticRefusal(
                    "operator reasons require command, scene/view, and acceptance"
                )
            for value in operator_fields:
                _stable(value or "", "operator reason receipt")
        elif any(value is not None for value in operator_fields):
            raise SemanticRefusal("operator receipts cannot decorate a non-operator reason")
        model_fields = (self.model_proposal_id, self.model_proposal_digest)
        model_named = any(
            token in self.reason_kind.lower()
            for token in ("model", "forecast", "score", "uncertainty", "voi", "analog")
        )
        if any(value is not None for value in model_fields):
            if any(value is None for value in model_fields):
                raise SemanticRefusal("model lineage requires proposal ID and content digest")
            _stable(self.model_proposal_id, "model_proposal_id")
            _digest(self.model_proposal_digest, "model_proposal_digest")
            _sorted_unique(self.model_lineage_evidence_ids, "model lineage evidence IDs")
            if self.origin not in {ReasonOrigin.MODEL, ReasonOrigin.OPERATOR}:
                raise SemanticRefusal("model-origin proposals retain model lineage")
        elif self.origin is ReasonOrigin.MODEL or self.model_lineage_evidence_ids or model_named:
            raise SemanticRefusal("model origin cannot omit exact proposal lineage")


@dataclass(frozen=True, slots=True)
class SensingAssignment:
    kind: AssignmentKind
    arm_id: str
    arm_digest: str
    stratum: str
    block: str
    assignment_occurrence_id: str
    inclusion_probability: RationalProbability
    seed_commit_digest: str | None
    allocation_table_digest: str | None

    def __post_init__(self) -> None:
        for value, name in (
            (self.arm_id, "arm_id"),
            (self.stratum, "stratum"),
            (self.block, "block"),
            (self.assignment_occurrence_id, "assignment_occurrence_id"),
        ):
            _stable(value, name)
        _digest(self.arm_digest, "arm_digest")
        randomized = self.kind in {AssignmentKind.FLOOR_RANDOM, AssignmentKind.CANDIDATE_RANDOMIZED}
        if randomized:
            if self.seed_commit_digest is None or self.allocation_table_digest is None:
                raise SemanticRefusal(
                    "randomized assignment needs seed and allocation-table commits"
                )
            _digest(self.seed_commit_digest, "seed_commit_digest")
            _digest(self.allocation_table_digest, "allocation_table_digest")
        elif self.seed_commit_digest is not None or self.allocation_table_digest is not None:
            raise SemanticRefusal("deterministic assignment cannot claim a randomization commit")


@dataclass(frozen=True, slots=True)
class SourceRequest:
    source_id: str
    operation: str
    subject_key: str
    desired_fidelity: str
    cadence_seconds: int
    starts_at: datetime
    expires_at_exclusive: datetime
    retry_semantics: str
    gap_semantics: str
    requested_subject_count: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.source_id, "source_id"),
            (self.operation, "operation"),
            (self.subject_key, "subject_key"),
            (self.desired_fidelity, "desired_fidelity"),
            (self.retry_semantics, "retry_semantics"),
            (self.gap_semantics, "gap_semantics"),
        ):
            _stable(value, name)
        _positive(self.cadence_seconds, "cadence_seconds")
        _positive(self.requested_subject_count, "requested_subject_count")
        if _aware(self.starts_at, "request starts_at") >= _aware(
            self.expires_at_exclusive, "request expires_at"
        ):
            raise SemanticRefusal("request expiry must be half-open and after start")


@dataclass(frozen=True, slots=True)
class FloorStatus:
    kind: FloorKind
    source_operation: str
    reserved: BudgetVector
    allocated_before: BudgetVector
    allocated_after: BudgetVector
    satisfied: bool
    evidence_ids: tuple[str, ...]
    overlap_subject_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _stable(self.source_operation, "floor status source_operation")
        _sorted_unique(self.evidence_ids, "floor status evidence")
        _sorted_unique(self.overlap_subject_keys, "floor overlaps", allow_empty=True)
        if not self.allocated_before.fits_within(self.allocated_after):
            raise SemanticRefusal("floor allocation cannot decrease across a sensing decision")
        if not self.allocated_after.fits_within(self.reserved):
            raise SemanticRefusal("a floor allocation crosses its protected reserve")
        if not self.satisfied:
            raise SemanticRefusal("candidate allocation cannot proceed with an unsatisfied floor")


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    parent_registered_run_digest: str
    parent_budget_digest: str
    source_operation: str
    reserved_maximum: BudgetVector
    expected: BudgetVector
    worst_case: BudgetVector
    maximum_in_flight_overshoot: BudgetVector
    privacy_retention_limit_digest: str

    def __post_init__(self) -> None:
        _digest(self.parent_registered_run_digest, "parent run digest")
        _digest(self.parent_budget_digest, "parent budget digest")
        _stable(self.source_operation, "budget reservation source_operation")
        _digest(self.privacy_retention_limit_digest, "privacy retention limit digest")
        if not self.expected.fits_within(self.worst_case):
            raise SemanticRefusal("expected cost cannot exceed worst case")
        if not self.worst_case.plus(self.maximum_in_flight_overshoot).fits_within(
            self.reserved_maximum
        ):
            raise SemanticRefusal("worst case plus in-flight overshoot is not fully reserved")


@dataclass(frozen=True, slots=True)
class CostBasis:
    method_envelope_id: str
    registry_fingerprint: str
    measured_cost_evidence_cutoff: datetime
    cost_model_version: str
    provider_price_is_authority: bool = False

    def __post_init__(self) -> None:
        _stable(self.method_envelope_id, "method envelope")
        _digest(self.registry_fingerprint, "registry fingerprint")
        _aware(self.measured_cost_evidence_cutoff, "measured cost evidence cutoff")
        _stable(self.cost_model_version, "cost model version")
        if self.provider_price_is_authority:
            raise SemanticRefusal("provider price is evidence, never allocation authority")


@dataclass(frozen=True, slots=True)
class SensingDecisionV1(SealedSemantic):
    CONTRACT: ClassVar[str] = "joshi.sensing_decision/v1"

    decision_id: str
    record_ordinal: int
    predecessor_id: str | None
    created_at: datetime
    producer_digest: str
    build_digest: str
    configuration_digest: str
    experiment_epoch_id: str
    experiment_epoch_digest: str
    closed_baseline_id: str
    closed_baseline_digest: str
    study_registration_id: str
    study_registration_digest: str
    policy_id: str
    policy_version: str
    policy_digest: str
    decision_event_at: datetime
    available_through: datetime
    commit_through: int
    production_at: datetime
    ttl_seconds: int
    expires_at_exclusive: datetime
    assignment_unit_kind: str
    assignment_unit_key: str
    public_subject_kind: str
    public_subject_key: str
    lifecycle_topology_version: str
    cluster_interference_id: str
    study_cell: str
    denominator: CensusDenominator
    eligibility: EligibilityEvidence
    reasons: tuple[SensingReason, ...]
    assignment: SensingAssignment
    requests: tuple[SourceRequest, ...]
    floor_statuses: tuple[FloorStatus, ...]
    budget: BudgetReservation
    cost_basis: CostBasis
    fixed_sensing_comparator_id: str
    activity_blind_control_id: str
    random_control_id: str
    no_model_baseline_digest: str
    source_registry_resolved: bool
    run_budget_resolved: bool
    denominator_resolved: bool
    coverage_resolved: bool
    policy_occurrence_resolved: bool
    operator_acceptance_resolved: bool
    source_io_not_started: bool
    authority: str = "read_only_no_execution"
    semantic_digest: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.decision_id, "decision_id"),
            (self.experiment_epoch_id, "experiment_epoch_id"),
            (self.closed_baseline_id, "closed_baseline_id"),
            (self.study_registration_id, "study_registration_id"),
            (self.policy_id, "policy_id"),
            (self.policy_version, "policy_version"),
            (self.assignment_unit_kind, "assignment_unit_kind"),
            (self.assignment_unit_key, "assignment_unit_key"),
            (self.public_subject_kind, "public_subject_kind"),
            (self.public_subject_key, "public_subject_key"),
            (self.lifecycle_topology_version, "lifecycle_topology_version"),
            (self.cluster_interference_id, "cluster_interference_id"),
            (self.study_cell, "study_cell"),
            (self.fixed_sensing_comparator_id, "fixed_sensing_comparator_id"),
            (self.activity_blind_control_id, "activity_blind_control_id"),
            (self.random_control_id, "random_control_id"),
        ):
            _stable(value, name)
        _positive(self.record_ordinal, "record_ordinal")
        if self.predecessor_id is not None:
            _stable(self.predecessor_id, "predecessor_id")
        created = _aware(self.created_at, "created_at")
        event = _aware(self.decision_event_at, "decision_event_at")
        available = _aware(self.available_through, "available_through")
        production = _aware(self.production_at, "production_at")
        expiry = _aware(self.expires_at_exclusive, "expires_at_exclusive")
        _exact_nonnegative(self.commit_through, "commit_through")
        _positive(self.ttl_seconds, "ttl_seconds")
        if not available <= event <= created <= production < expiry:
            raise SemanticRefusal("sensing decision cutoff/production/expiry ordering is invalid")
        if (expiry - event).total_seconds() != self.ttl_seconds:
            raise SemanticRefusal("sensing TTL does not match its half-open expiry")
        for name in (
            "producer_digest",
            "build_digest",
            "configuration_digest",
            "experiment_epoch_digest",
            "closed_baseline_digest",
            "study_registration_digest",
            "policy_digest",
            "no_model_baseline_digest",
        ):
            _digest(getattr(self, name), name)
        if self.denominator.commit_through > self.commit_through:
            raise SemanticRefusal("denominator uses a future store commit")
        if self.denominator.available_through > available:
            raise SemanticRefusal("denominator uses future availability")
        for evidence in self.eligibility.evidence:
            if (
                evidence.known_by > available
                or evidence.valid_at > event
                or evidence.commit_seq > self.commit_through
            ):
                raise SemanticRefusal("eligibility uses later information")
        reason_keys = tuple((reason.reason_kind, reason.origin.value) for reason in self.reasons)
        if (
            not reason_keys
            or reason_keys != tuple(sorted(reason_keys))
            or len(set(reason_keys)) != len(reason_keys)
        ):
            raise SemanticRefusal("sensing reasons must be nonempty, sorted, typed, and unique")
        request_keys = tuple(
            (request.source_id, request.operation, request.subject_key) for request in self.requests
        )
        if (
            not request_keys
            or request_keys != tuple(sorted(request_keys))
            or len(set(request_keys)) != len(request_keys)
        ):
            raise SemanticRefusal("source requests must be nonempty, sorted, and unique")
        floor_keys = tuple(
            (status.source_operation, status.kind.value) for status in self.floor_statuses
        )
        expected_kinds = {kind.value for kind in FloorKind}
        if (
            floor_keys != tuple(sorted(floor_keys))
            or len(set(floor_keys)) != len(floor_keys)
            or {kind for _source, kind in floor_keys} != expected_kinds
        ):
            raise SemanticRefusal(
                "floor status must include sorted cold/random/manual/portfolio vectors"
            )
        required_resolutions = (
            self.source_registry_resolved,
            self.run_budget_resolved,
            self.denominator_resolved,
            self.coverage_resolved,
            self.policy_occurrence_resolved,
            self.source_io_not_started,
        )
        if not all(required_resolutions):
            raise SemanticRefusal(
                "decision is not admitted before source I/O with all store proofs"
            )
        has_operator = any(reason.origin is ReasonOrigin.OPERATOR for reason in self.reasons)
        if has_operator != self.operator_acceptance_resolved:
            raise SemanticRefusal(
                "operator acceptance proof does not match operator reason lineage"
            )
        has_model = any(
            reason.origin is ReasonOrigin.MODEL or reason.model_proposal_id is not None
            for reason in self.reasons
        )
        if self.assignment.kind is AssignmentKind.FLOOR_MANUAL and has_model:
            raise SemanticRefusal("a model-origin proposal cannot be relabeled as manual")
        if has_model and self.assignment.kind is not AssignmentKind.CANDIDATE_VOI:
            raise SemanticRefusal(
                "model-induced live selection is restricted to admitted candidate_voi"
            )
        if self.authority != "read_only_no_execution":
            raise SemanticRefusal("sensing authority must be literally read_only_no_execution")
        if self.semantic_digest:
            self.verify_semantic_digest()


@dataclass(frozen=True, slots=True)
class PresentationAssignment:
    mechanism: str
    eligible_arms: tuple[tuple[str, str], ...]
    assigned_arm: str
    inclusion_probability: RationalProbability
    stratum: str
    block: str
    seed_commit_digest: str
    allocation_table_digest: str
    concealment_state: str
    blinding_state: str

    def __post_init__(self) -> None:
        _stable(self.mechanism, "presentation assignment mechanism")
        keys = tuple(key for key, _digest_value in self.eligible_arms)
        if len(keys) < 2 or keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise SemanticRefusal("presentation assignment needs sorted unique competing arms")
        for _key, digest in self.eligible_arms:
            _digest(digest, "presentation arm digest")
        if self.assigned_arm not in keys:
            raise SemanticRefusal("assigned presentation arm is not eligible")
        for value, name in (
            (self.stratum, "presentation stratum"),
            (self.block, "presentation block"),
            (self.concealment_state, "concealment_state"),
            (self.blinding_state, "blinding_state"),
        ):
            _stable(value, name)
        _digest(self.seed_commit_digest, "presentation seed commit")
        _digest(self.allocation_table_digest, "presentation allocation table")


@dataclass(frozen=True, slots=True)
class PresentationPolicy:
    policy_id: str
    policy_version: str
    policy_digest: str
    eligible_item_ids: tuple[str, ...]
    selected_item_ids: tuple[str, ...]
    planned_render_item_ids: tuple[str, ...]
    omitted_item_ids: tuple[str, ...]
    semantic_order: tuple[str, ...]
    salience_basis: str
    filter_ids: tuple[str, ...]
    toggle_ids: tuple[str, ...]
    comparison_item_ids: tuple[str, ...]
    progressive_disclosure_state: str

    def __post_init__(self) -> None:
        _stable(self.policy_id, "presentation policy_id")
        _stable(self.policy_version, "presentation policy_version")
        _digest(self.policy_digest, "presentation policy digest")
        _sorted_unique(self.eligible_item_ids, "eligible presentation items")
        _sorted_unique(self.selected_item_ids, "selected presentation items", allow_empty=True)
        _sorted_unique(self.planned_render_item_ids, "planned render items", allow_empty=True)
        _sorted_unique(self.omitted_item_ids, "omitted presentation items", allow_empty=True)
        if set(self.planned_render_item_ids) | set(self.omitted_item_ids) != set(
            self.eligible_item_ids
        ):
            raise SemanticRefusal("planned and omitted items must close the eligible evidence set")
        if set(self.planned_render_item_ids) & set(self.omitted_item_ids):
            raise SemanticRefusal("a presentation item cannot be both planned and omitted")
        if not set(self.selected_item_ids).issubset(self.planned_render_item_ids):
            raise SemanticRefusal("selected items must be in the planned render")
        if set(self.semantic_order) != set(self.planned_render_item_ids) or len(
            self.semantic_order
        ) != len(set(self.semantic_order)):
            raise SemanticRefusal("semantic order must be an exact permutation of planned items")
        _stable(self.salience_basis, "salience basis")
        gaming = ("outcome", "click", "dwell", "activity", "pnl", "trade")
        if any(token in self.salience_basis.lower() for token in gaming):
            raise SemanticRefusal("presentation salience cannot respond to outcomes or activity")
        _sorted_unique(self.filter_ids, "presentation filters", allow_empty=True)
        _sorted_unique(self.toggle_ids, "presentation toggles", allow_empty=True)
        _sorted_unique(self.comparison_item_ids, "comparison items", allow_empty=True)
        _stable(self.progressive_disclosure_state, "progressive disclosure state")


@dataclass(frozen=True, slots=True)
class PresentationSafety:
    invariant_safety_content_digest: str
    required_persistent_fields: tuple[str, ...]
    evidence_equivalence_asserted: bool
    prohibited_omissions: tuple[str, ...]

    REQUIRED: ClassVar[set[str]] = {
        "authority",
        "freshness",
        "gaps",
        "refusals",
        "inventory_exposure",
    }

    def __post_init__(self) -> None:
        _digest(self.invariant_safety_content_digest, "invariant safety content digest")
        _sorted_unique(self.required_persistent_fields, "persistent safety fields")
        _sorted_unique(self.prohibited_omissions, "prohibited safety omissions")
        if not self.REQUIRED.issubset(self.required_persistent_fields):
            raise SemanticRefusal("presentation omits required persistent safety truth")
        if not self.REQUIRED.issubset(self.prohibited_omissions):
            raise SemanticRefusal("presentation does not prohibit all safety-critical omissions")
        if not self.evidence_equivalence_asserted:
            raise SemanticRefusal("presentation arms must assert evidence equivalence")


@dataclass(frozen=True, slots=True)
class PresentationBurden:
    session_assignment_ordinal: int
    prompt_count: int
    closeout_seconds: int
    session_study_seconds: int
    seven_day_study_seconds: int
    interruption_class: str
    cooldown_seconds: int
    notification_count: int
    voluntary_skip_path: bool
    voluntary_withdraw_path: bool
    capture_failure_fallback: str

    def __post_init__(self) -> None:
        for name in (
            "session_assignment_ordinal",
            "prompt_count",
            "closeout_seconds",
            "session_study_seconds",
            "seven_day_study_seconds",
            "cooldown_seconds",
            "notification_count",
        ):
            _exact_nonnegative(getattr(self, name), name)
        _stable(self.interruption_class, "interruption class")
        _stable(self.capture_failure_fallback, "capture failure fallback")
        if not self.voluntary_skip_path or not self.voluntary_withdraw_path:
            raise SemanticRefusal("presentation must preserve voluntary skip and withdrawal")
        if self.capture_failure_fallback != "fixed_safety_baseline_view":
            raise SemanticRefusal(
                "capture failure must fall back to the fixed safety baseline view"
            )


@dataclass(frozen=True, slots=True)
class PresentationInterventionV1(SealedSemantic):
    CONTRACT: ClassVar[str] = "joshi.presentation_intervention/v1"

    intervention_id: str
    record_ordinal: int
    predecessor_id: str | None
    created_at: datetime
    producer_digest: str
    build_digest: str
    renderer_digest: str
    configuration_digest: str
    experiment_epoch_id: str
    experiment_epoch_digest: str
    study_registration_id: str
    study_registration_digest: str
    closed_baseline_id: str
    closed_baseline_digest: str
    hypothesis_id: str
    estimands: tuple[str, ...]
    falsifiers: tuple[str, ...]
    operator_id: str
    session_id: str
    scene_id: str
    decision_opportunity_id: str
    assignment_unit: str
    cluster_interference_id: str
    study_cell: str
    sequence: int
    period: int
    as_of_evidence: tuple[EvidenceRef, ...]
    maximum_input_available_at: datetime
    maximum_input_commit_seq: int
    assignment_at: datetime
    stage_deadline: datetime
    reveal_deadline: datetime
    glass_view_id: str
    glass_view_digest: str
    glass_mode: str
    eligible_evidence_artifact_id: str
    eligible_evidence_digest: str
    denominator: CensusDenominator
    coverage_state_ids: tuple[str, ...]
    gap_ids: tuple[str, ...]
    refusal_ids: tuple[str, ...]
    authority_rungs: tuple[str, ...]
    assignment: PresentationAssignment
    policy: PresentationPolicy
    safety: PresentationSafety
    accessibility: AccessibilityProfile
    burden: PresentationBurden
    evidence_only_commands: tuple[str, ...]
    receipt_not_yet_claimed: bool
    reveal_not_started: bool
    authority: str = "read_record_replay_only"
    effect_ceiling: str = "observe_only"
    semantic_digest: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.intervention_id, "intervention_id"),
            (self.experiment_epoch_id, "experiment_epoch_id"),
            (self.study_registration_id, "study_registration_id"),
            (self.closed_baseline_id, "closed_baseline_id"),
            (self.hypothesis_id, "hypothesis_id"),
            (self.operator_id, "operator_id"),
            (self.session_id, "session_id"),
            (self.scene_id, "scene_id"),
            (self.decision_opportunity_id, "decision_opportunity_id"),
            (self.assignment_unit, "assignment_unit"),
            (self.cluster_interference_id, "cluster_interference_id"),
            (self.study_cell, "study_cell"),
            (self.glass_view_id, "glass_view_id"),
            (self.glass_mode, "glass_mode"),
            (self.eligible_evidence_artifact_id, "eligible_evidence_artifact_id"),
        ):
            _stable(value, name)
        _positive(self.record_ordinal, "record_ordinal")
        _positive(self.sequence, "sequence")
        _positive(self.period, "period")
        if self.predecessor_id is not None:
            _stable(self.predecessor_id, "predecessor_id")
        created = _aware(self.created_at, "created_at")
        maximum = _aware(self.maximum_input_available_at, "maximum input availability")
        _exact_nonnegative(self.maximum_input_commit_seq, "maximum input commit seq")
        assigned = _aware(self.assignment_at, "assignment_at")
        stage = _aware(self.stage_deadline, "stage_deadline")
        reveal = _aware(self.reveal_deadline, "reveal_deadline")
        if not maximum <= assigned <= created <= stage <= reveal:
            raise SemanticRefusal("presentation must be assigned and staged before reveal")
        if not self.as_of_evidence:
            raise SemanticRefusal("presentation requires immutable as-known evidence")
        for evidence in self.as_of_evidence:
            if (
                evidence.known_by > maximum
                or evidence.valid_at > assigned
                or evidence.commit_seq > self.maximum_input_commit_seq
            ):
                raise SemanticRefusal("presentation input includes future evidence/support")
        if self.denominator.commit_through > self.maximum_input_commit_seq:
            raise SemanticRefusal("presentation denominator uses a future store commit")
        for name in (
            "producer_digest",
            "build_digest",
            "renderer_digest",
            "configuration_digest",
            "experiment_epoch_digest",
            "study_registration_digest",
            "closed_baseline_digest",
            "glass_view_digest",
            "eligible_evidence_digest",
        ):
            _digest(getattr(self, name), name)
        _sorted_unique(self.estimands, "presentation estimands")
        _sorted_unique(self.falsifiers, "presentation falsifiers")
        _sorted_unique(self.coverage_state_ids, "presentation coverage states")
        _sorted_unique(self.gap_ids, "presentation gaps", allow_empty=True)
        _sorted_unique(self.refusal_ids, "presentation refusals", allow_empty=True)
        _sorted_unique(self.authority_rungs, "presentation authority rungs")
        _sorted_unique(self.evidence_only_commands, "evidence-only commands")
        forbidden_commands = ("wallet", "transaction", "sign", "submit", "trade", "swap", "route")
        if any(
            any(token in command.lower() for token in forbidden_commands)
            for command in self.evidence_only_commands
        ):
            raise SemanticRefusal(
                "presentation controls cannot expose economic execution authority"
            )
        if set(self.safety.required_persistent_fields).intersection(self.policy.omitted_item_ids):
            raise SemanticRefusal("experimental presentation omits registered safety truth")
        if not set(self.safety.required_persistent_fields).issubset(
            self.policy.planned_render_item_ids
        ):
            raise SemanticRefusal("experimental presentation fails to plan persistent safety truth")
        if not self.receipt_not_yet_claimed or not self.reveal_not_started:
            raise SemanticRefusal("staged prescription cannot claim receipt, exposure, or reveal")
        if self.authority != "read_record_replay_only" or self.effect_ceiling != "observe_only":
            raise SemanticRefusal(
                "presentation authority may only read, record, replay, and observe"
            )
        if self.semantic_digest:
            self.verify_semantic_digest()


@dataclass(frozen=True, slots=True)
class AssignedUnitOutcome:
    assignment_occurrence_id: str
    assignment_artifact_id: str
    assignment_artifact_digest: str
    arm_id: str
    study_cell: str
    assignment_kind: OutcomeAssignmentKind
    policy_digest: str
    denominator_digest: str
    assignment_unit_key: str
    public_subject_key: str
    nonresponse_state: NonresponseState
    outcome_state: OutcomeClosureState
    desired: bool
    applied: bool
    provider_acknowledged: bool
    healthily_covered: bool
    exposed: bool
    focused: bool
    responded: bool
    outcome_matured: bool
    analyzed: bool
    actual_cost: BudgetVector
    reason_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _stable(self.assignment_occurrence_id, "assignment occurrence")
        _stable(self.assignment_artifact_id, "assignment artifact ID")
        _digest(self.assignment_artifact_digest, "assignment artifact digest")
        _stable(self.arm_id, "outcome arm")
        _stable(self.study_cell, "outcome study cell")
        if not isinstance(self.assignment_kind, OutcomeAssignmentKind):
            raise SemanticRefusal("outcome assignment kind must retain its exact enum")
        _digest(self.policy_digest, "outcome policy digest")
        _digest(self.denominator_digest, "outcome denominator digest")
        _stable(self.assignment_unit_key, "outcome assignment unit key")
        _stable(self.public_subject_key, "outcome public subject key")
        if not isinstance(self.nonresponse_state, NonresponseState):
            raise SemanticRefusal("outcome nonresponse state must retain its exact enum")
        if not isinstance(self.outcome_state, OutcomeClosureState):
            raise SemanticRefusal("outcome closure state must retain its exact enum")
        _sorted_unique(self.reason_evidence_ids, "outcome reason evidence")
        if (
            self.nonresponse_state is NonresponseState.COMPLETED_COVERED
            and not self.healthily_covered
        ):
            raise SemanticRefusal("completed_covered requires healthy coverage")
        if self.analyzed and not self.outcome_matured:
            raise SemanticRefusal("analyzed unit lacks matured outcome support")
        if self.outcome_matured != (self.outcome_state is OutcomeClosureState.MATURED):
            raise SemanticRefusal("matured flag and outcome closure state disagree")


@dataclass(frozen=True, slots=True)
class CoverageSupportReportV1(SealedSemantic):
    CONTRACT: ClassVar[str] = "joshi.wave6.coverage_support_report/v1"

    report_id: str
    experiment_epoch_id: str
    experiment_epoch_digest: str
    knowledge_deadline: datetime
    full_census_count: int
    denominator_digest: str
    denominator_occurrence_ids: tuple[str, ...]
    outcomes: tuple[AssignedUnitOutcome, ...]
    planned_budget: BudgetVector
    actual_budget: BudgetVector
    provider_observed_billing: BudgetVector
    inclusion_probabilities_known: bool
    effective_sample_size_numerator: int
    effective_sample_size_denominator: int
    worst_supported_strata: tuple[str, ...]
    drift_version_ids: tuple[str, ...]
    analysis_mode: str
    semantic_digest: str = ""

    def __post_init__(self) -> None:
        _stable(self.report_id, "report_id")
        _stable(self.experiment_epoch_id, "experiment_epoch_id")
        _digest(self.experiment_epoch_digest, "experiment_epoch_digest")
        _aware(self.knowledge_deadline, "knowledge deadline")
        _positive(self.full_census_count, "full census count")
        _digest(self.denominator_digest, "denominator digest")
        _sorted_unique(self.denominator_occurrence_ids, "denominator occurrence IDs")
        if not self.outcomes:
            raise SemanticRefusal("coverage report cannot omit its assigned denominator")
        keys = tuple(outcome.assignment_occurrence_id for outcome in self.outcomes)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise SemanticRefusal("assigned outcomes must be sorted, unique, and unreplaced")
        if not self.actual_budget.fits_within(self.planned_budget):
            raise SemanticRefusal("actual cost crosses the registered planned budget")
        summed = BudgetVector()
        for outcome in self.outcomes:
            summed = summed.plus(outcome.actual_cost)
        if summed != self.actual_budget:
            raise SemanticRefusal("actual budget does not reconcile assigned-unit costs")
        if not self.provider_observed_billing.fits_within(self.planned_budget):
            raise SemanticRefusal("provider-observed billing crosses the registered budget")
        _exact_nonnegative(self.effective_sample_size_numerator, "ESS numerator")
        _positive(self.effective_sample_size_denominator, "ESS denominator")
        _sorted_unique(self.worst_supported_strata, "worst supported strata", allow_empty=True)
        _sorted_unique(self.drift_version_ids, "drift versions", allow_empty=True)
        if self.analysis_mode == "randomized_itt" and not self.inclusion_probabilities_known:
            raise SemanticRefusal("randomized ITT requires known assignment probabilities")
        if self.analysis_mode not in {"randomized_itt", "association_only", "descriptive_only"}:
            raise SemanticRefusal("coverage report analysis mode is unsupported")
        if self.semantic_digest:
            self.verify_semantic_digest()


@dataclass(frozen=True, slots=True)
class UnverifiedSemantic:
    """Public boundary: valid semantics, not acquisition, exposure, causality, or execution."""

    artifact: SealedSemantic
    semantic_digest: str
    verification_state: str = "unverified_semantic"
    authority: str = "no_acquisition_ui_wallet_or_execution_authority"
    explicit_nonclaims: tuple[str, ...] = (
        "source_io",
        "collector_apply",
        "provider_acknowledgement",
        "coverage",
        "render",
        "visibility",
        "focus",
        "comprehension",
        "causal_effect",
        "wallet_or_transaction_effect",
    )

    def __post_init__(self) -> None:
        self.artifact.verify_semantic_digest()
        if self.semantic_digest != self.artifact.semantic_digest:
            raise SemanticRefusal("public wrapper digest differs from its artifact")
        if self.verification_state != "unverified_semantic":
            raise SemanticRefusal("public output must remain UnverifiedSemantic")
        if self.authority != "no_acquisition_ui_wallet_or_execution_authority":
            raise SemanticRefusal("public output cannot widen authority")

    def as_dict(self) -> dict[str, Any]:
        value = _wire(self)
        if not isinstance(value, dict):  # pragma: no cover
            raise TypeError("semantic wrapper did not encode as an object")
        return value
