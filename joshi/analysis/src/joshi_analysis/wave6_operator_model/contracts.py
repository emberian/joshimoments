"""Append-only, outcome-separated contracts for the Wave 6 operator prototype.

This module deliberately models *evidence records*, not Ember's private state.  It
is an isolated prototype: callers retain and validate its deterministic artifacts
instead of treating its terms as a market taxonomy or an execution interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes, require_qualified_sha256

SCHEMA_VERSION = "joshi.analysis.wave6-operator-model/v1"
AUTHORITY = "read_only_evidence_only_no_execution_or_economic_inference"
NO_SCALAR_PRESSURE = "component_bundle_only_no_pressure_aggregate"


class OperatorModelError(ValueError):
    """An artifact violates an evidence, clock, or semantic separation."""


class TemporalClosureError(OperatorModelError):
    """A record attempts to use evidence unavailable at its stated knowledge cut."""


class ResponseState(StrEnum):
    VERBATIM = "verbatim"
    OPAQUE_TOKEN = "opaque_token"
    AMBIGUOUS = "ambiguous"
    CANNOT_ARTICULATE = "cannot_articulate"
    NO_RESPONSE = "no_response"
    NOT_ASKED = "not_asked"


class CoverageStatus(StrEnum):
    OBSERVED = "observed"
    PARTIAL = "partial"
    SOURCE_GAP = "source_gap"
    STALE = "stale"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"
    CONTRADICTORY = "contradictory"


class AssertionRole(StrEnum):
    OPERATOR_ASSERTION = "operator_assertion"
    SOURCE_OBSERVATION = "source_observation"
    DETERMINISTIC_PROJECTION = "deterministic_projection"
    HYPOTHESIS = "hypothesis"


class ComponentKind(StrEnum):
    TIMING_SIZE = "timing_size"
    LIQUIDITY_RESILIENCE = "liquidity_resilience"
    CALLER_ACTOR = "caller_actor"
    WALLET_INVENTORY = "wallet_inventory"
    SOCIAL_ATTENTION = "social_attention"
    CHART_EPISODE_MEMORY = "chart_episode_memory"
    COMPRESSION_RELEASE = "compression_release"
    LIFECYCLE_TOPOLOGY = "lifecycle_topology"
    PVP_CHURN = "pvp_churn"
    PORTFOLIO_ALTERNATIVES = "portfolio_alternatives"
    COVERAGE_PRESENTATION = "coverage_presentation"
    UNNAMED_RESIDUAL = "unnamed_residual"


class ActKind(StrEnum):
    NOTICE = "notice"
    INSPECT = "inspect"
    COMPARE = "compare"
    MARK = "mark"
    NOMINATE = "nominate"
    REQUEST_HOT_SCOPE = "request_hot_scope"
    TAKE_SOME_INTENT = "take_some_intent"
    KEEP_REMAINDER_DECLARATION = "keep_remainder_declaration"
    FLAT_WATCH_DECLARATION = "flat_watch_declaration"
    REENTRY_INTENT = "reentry_intent"
    ZAP_ESCAPE_DECLARATION = "zap_escape_declaration"
    CLOSE_EPISODE_DECLARATION = "close_episode_declaration"
    ABSTAIN = "abstain"


class IntentionKind(StrEnum):
    DESIRED_ACTION = "desired_action"
    DESIRED_EXPOSURE = "desired_exposure"
    HORIZON = "horizon"
    AVOIDANCE = "avoidance"
    REVIEW_CONDITION = "review_condition"
    DISPOSITION = "disposition"


class OntologyStatus(StrEnum):
    OPAQUE = "opaque"
    PROVISIONAL = "provisional"
    ACTIVE = "active"
    SPLIT = "split"
    MERGED = "merged"
    RETIRED = "retired"
    REJECTED = "rejected"


class OntologyRelationKind(StrEnum):
    SPLIT_INTO = "split_into"
    MERGED_FROM = "merged_from"
    RENAMED = "renamed"
    RETIRED = "retired"
    REJECTED = "rejected"
    EQUIVALENCE = "equivalence"


class RelationScope(StrEnum):
    LEXICAL = "lexical"
    PHENOMENOLOGICAL = "phenomenological"
    RETRIEVAL = "retrieval_oriented"
    MODEL_HARMONIZATION = "model_harmonization"


class RecognitionKind(StrEnum):
    RECOGNIZES = "recognizes"
    DOES_NOT_RECOGNIZE = "does_not_recognize"
    UNCERTAIN = "uncertain"
    CANNOT_RECONSTRUCT = "cannot_reconstruct"


class ReplayPhase(StrEnum):
    OUTCOME_BLINDED = "outcome_blinded"
    OUTCOME_AWARE = "outcome_aware"


class ReplayEvidenceRole(StrEnum):
    SCENE_COMPONENT = "scene_component"
    PRESENTATION = "presentation"
    ACT = "act"
    OPERATOR_ASSERTION = "operator_assertion"
    ECONOMIC_EFFECT = "economic_effect"
    OUTCOME = "outcome"


class ReplayArtifactType(StrEnum):
    SCENE_COMPONENT_PROJECTION = "scene_component_projection"
    PRESENTATION_OCCURRENCE = "presentation_occurrence"
    OPERATOR_ACT = "operator_act"
    RAW_OPERATOR_ASSERTION = "raw_operator_assertion"
    RECONCILED_ECONOMIC_EFFECT = "reconciled_economic_effect"
    OUTCOME = "outcome"


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperatorModelError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _id(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 240
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise OperatorModelError(f"{name} must be a non-empty stable string")
    return value


def _digest(value: str, name: str) -> str:
    try:
        return require_qualified_sha256(value, name)
    except ValueError as error:
        raise OperatorModelError(str(error)) from error


def _strictly_sorted_unique(values: tuple[str, ...], name: str) -> None:
    for value in values:
        _id(value, name)
    if tuple(sorted(set(values))) != values:
        raise OperatorModelError(f"{name} must be sorted and duplicate-free")


def _positive_commit(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OperatorModelError(f"{name} must be a positive commit sequence")
    return value


def _canonical(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return _aware(value, "artifact datetime").isoformat(timespec="microseconds")
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if is_dataclass(value):
        return {key: _canonical(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    return value


def deterministic_digest(value: Any) -> str:
    """Return a stable digest of a complete, canonical prototype artifact."""

    return qualified_sha256_bytes(canonical_json_bytes(_canonical(value)))


@dataclass(frozen=True, slots=True)
class ClockPair:
    """Both occurrence and knowledge clocks; neither substitutes for the other."""

    occurred_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        occurred = _aware(self.occurred_at, "occurred_at")
        available = _aware(self.available_at, "available_at")
        if available < occurred:
            raise OperatorModelError("available_at cannot precede occurred_at")
        object.__setattr__(self, "occurred_at", occurred)
        object.__setattr__(self, "available_at", available)


@dataclass(frozen=True, slots=True)
class TypedGap:
    gap_id: str
    version_id: str
    content_digest: str
    available_commit_seq: int
    gap_kind: str
    declared_at: datetime
    coverage: CoverageStatus = CoverageStatus.SOURCE_GAP

    def __post_init__(self) -> None:
        _id(self.gap_id, "gap_id")
        _id(self.version_id, "gap version_id")
        _digest(self.content_digest, "gap content_digest")
        _positive_commit(self.available_commit_seq, "gap available_commit_seq")
        _id(self.gap_kind, "gap_kind")
        _aware(self.declared_at, "gap declared_at")
        gap_states = {CoverageStatus.SOURCE_GAP, CoverageStatus.PARTIAL, CoverageStatus.STALE}
        if self.coverage not in gap_states:
            raise OperatorModelError("a TypedGap requires gap, partial, or stale coverage")


@dataclass(frozen=True, slots=True)
class SceneBinding:
    """Exact scene and point-in-time presentation witness, or an explicit typed gap."""

    scene_id: str
    scene_version_id: str
    scene_digest: str
    scene_commit_seq: int
    view_id: str
    view_version_id: str
    view_digest: str
    view_commit_seq: int
    presentation_occurrence_id: str | None
    presentation_version_id: str | None
    presentation_digest: str | None
    presentation_commit_seq: int | None
    presentation_gap: TypedGap | None
    choice_context_id: str | None
    choice_context_version_id: str | None
    choice_context_digest: str | None
    choice_context_commit_seq: int | None
    clocks: ClockPair

    def __post_init__(self) -> None:
        _id(self.scene_id, "scene_id")
        _id(self.scene_version_id, "scene_version_id")
        _digest(self.scene_digest, "scene_digest")
        _positive_commit(self.scene_commit_seq, "scene_commit_seq")
        _id(self.view_id, "view_id")
        _id(self.view_version_id, "view_version_id")
        _digest(self.view_digest, "view_digest")
        _positive_commit(self.view_commit_seq, "view_commit_seq")
        if (self.presentation_occurrence_id is None) == (self.presentation_gap is None):
            raise OperatorModelError(
                "scene binding requires exactly one presentation occurrence or gap"
            )
        if self.presentation_occurrence_id is not None:
            _id(self.presentation_occurrence_id, "presentation_occurrence_id")
            if (
                self.presentation_version_id is None
                or self.presentation_digest is None
                or self.presentation_commit_seq is None
            ):
                raise OperatorModelError(
                    "a presentation occurrence requires version, digest, and commit"
                )
            _id(self.presentation_version_id, "presentation_version_id")
            _digest(self.presentation_digest, "presentation_digest")
            _positive_commit(self.presentation_commit_seq, "presentation_commit_seq")
        elif any(
            value is not None
            for value in (
                self.presentation_version_id,
                self.presentation_digest,
                self.presentation_commit_seq,
            )
        ):
            raise OperatorModelError("a presentation gap cannot manufacture presentation content")
        choice_fields = (
            self.choice_context_id,
            self.choice_context_version_id,
            self.choice_context_digest,
            self.choice_context_commit_seq,
        )
        if any(value is not None for value in choice_fields):
            if any(value is None for value in choice_fields):
                raise OperatorModelError("choice context requires id, version, digest, and commit")
            _id(self.choice_context_id, "choice_context_id")
            _id(self.choice_context_version_id, "choice_context_version_id")
            _digest(self.choice_context_digest, "choice_context_digest")
            _positive_commit(self.choice_context_commit_seq, "choice_context_commit_seq")

    @property
    def artifact_digest(self) -> str:
        return deterministic_digest(self)

    @property
    def maximum_commit_seq(self) -> int:
        presentation_commit = (
            self.presentation_commit_seq
            if self.presentation_commit_seq is not None
            else self.presentation_gap.available_commit_seq
        )
        commits = (self.scene_commit_seq, self.view_commit_seq, presentation_commit)
        if self.choice_context_commit_seq is not None:
            commits += (self.choice_context_commit_seq,)
        return max(commits)


@dataclass(frozen=True, slots=True)
class RawOperatorAssertion:
    """Immutable raw capture.  A parser may reference this record but cannot replace it."""

    assertion_id: str
    subject_id: str
    operator_id: str | None
    episode_id: str | None
    binding: SceneBinding
    asserted_at: datetime
    referred_to: ClockPair
    knowledge_cut: datetime
    elicitation_mode: str
    prompt_text: str | None
    prompt_order: int | None
    machine_suggestion_visible: bool
    response_state: ResponseState
    raw_bytes: bytes | None = None
    opaque_token: str | None = None
    confidence_text: str | None = None
    urgency_text: str | None = None
    why_now_text: str | None = None
    correction_of_assertion_id: str | None = None
    privacy_status: str = "unspecified"
    corpus_use_status: str = "unspecified"

    def __post_init__(self) -> None:
        _id(self.assertion_id, "assertion_id")
        _id(self.subject_id, "subject_id")
        if self.operator_id is not None:
            _id(self.operator_id, "operator_id")
        if self.episode_id is not None:
            _id(self.episode_id, "episode_id")
        asserted = _aware(self.asserted_at, "asserted_at")
        cut = _aware(self.knowledge_cut, "knowledge_cut")
        if asserted > cut:
            raise TemporalClosureError("assertion asserted_at cannot be after knowledge_cut")
        if self.binding.clocks.available_at > cut:
            raise TemporalClosureError(
                "scene/presentation binding was unavailable at knowledge_cut"
            )
        if self.referred_to.available_at > cut:
            raise TemporalClosureError("referred-to evidence was unavailable at knowledge_cut")
        _id(self.elicitation_mode, "elicitation_mode")
        if self.prompt_order is not None and (
            isinstance(self.prompt_order, bool) or self.prompt_order < 0
        ):
            raise OperatorModelError("prompt_order must be a non-negative integer")
        if self.response_state is ResponseState.VERBATIM:
            if not self.raw_bytes or self.opaque_token is not None:
                raise OperatorModelError(
                    "verbatim capture requires non-empty raw_bytes and no opaque token"
                )
        elif self.response_state is ResponseState.OPAQUE_TOKEN:
            if self.raw_bytes is not None or self.opaque_token is None:
                raise OperatorModelError("opaque capture requires only an opaque token")
            _id(self.opaque_token, "opaque_token")
        elif self.response_state is ResponseState.AMBIGUOUS:
            if self.raw_bytes is not None and self.opaque_token is not None:
                raise OperatorModelError(
                    "ambiguous capture may retain raw bytes or an opaque token, not both"
                )
            if self.opaque_token is not None:
                _id(self.opaque_token, "opaque_token")
        elif self.raw_bytes is not None or self.opaque_token is not None:
            raise OperatorModelError(
                "non-text response states cannot carry replacement text or token"
            )
        if self.correction_of_assertion_id is not None:
            _id(self.correction_of_assertion_id, "correction_of_assertion_id")
            if self.correction_of_assertion_id == self.assertion_id:
                raise OperatorModelError("an assertion cannot correct itself")
        object.__setattr__(self, "asserted_at", asserted)
        object.__setattr__(self, "knowledge_cut", cut)

    @property
    def raw_digest(self) -> str | None:
        return qualified_sha256_bytes(self.raw_bytes) if self.raw_bytes is not None else None

    @property
    def artifact_digest(self) -> str:
        return deterministic_digest(self)


@dataclass(frozen=True, slots=True)
class ComponentAssertion:
    """One non-commensurate component claim in a scene-bound bundle."""

    component_id: str
    kind: ComponentKind
    assertion_role: AssertionRole
    raw_assertion_id: str | None
    evidence_ref_ids: tuple[str, ...]
    clocks: ClockPair
    knowledge_cut: datetime
    coverage: CoverageStatus
    asset_id: str | None
    unit: str | None
    reference_measure: str | None
    topology_profile: str | None
    claim_bytes: bytes | None
    ambiguity: bool = False
    cannot_articulate: bool = False

    def __post_init__(self) -> None:
        _id(self.component_id, "component_id")
        _strictly_sorted_unique(self.evidence_ref_ids, "evidence_ref_ids")
        cut = _aware(self.knowledge_cut, "component knowledge_cut")
        if self.clocks.available_at > cut:
            raise TemporalClosureError("component evidence was unavailable at knowledge_cut")
        if self.assertion_role is AssertionRole.OPERATOR_ASSERTION:
            if self.raw_assertion_id is None:
                raise OperatorModelError(
                    "operator component assertion requires a raw assertion reference"
                )
            _id(self.raw_assertion_id, "raw_assertion_id")
        elif self.raw_assertion_id is not None:
            raise OperatorModelError(
                "non-operator component claim cannot masquerade as a raw assertion"
            )
        named_measure = (self.asset_id, self.unit, self.reference_measure, self.topology_profile)
        if self.coverage is CoverageStatus.NOT_APPLICABLE:
            if any(value is not None for value in named_measure):
                raise OperatorModelError("not_applicable components do not invent a measure")
        elif any(value is None for value in named_measure):
            raise OperatorModelError(
                "a measured component requires asset, unit, reference measure, and topology"
            )
        else:
            for name, value in zip(
                ("asset_id", "unit", "reference_measure", "topology_profile"),
                named_measure,
                strict=True,
            ):
                _id(value, name)
        if self.claim_bytes is None and self.coverage is CoverageStatus.OBSERVED:
            raise OperatorModelError("observed component claims require retained claim bytes")
        if self.cannot_articulate and self.assertion_role is not AssertionRole.OPERATOR_ASSERTION:
            raise OperatorModelError("cannot_articulate is only an operator capture state")
        object.__setattr__(self, "knowledge_cut", cut)


@dataclass(frozen=True, slots=True)
class ComponentBundle:
    """A heterogeneous bundle; no scalar, ordering, or aggregate is defined."""

    bundle_id: str
    binding: SceneBinding
    knowledge_cut: datetime
    components: tuple[ComponentAssertion, ...]

    def __post_init__(self) -> None:
        _id(self.bundle_id, "bundle_id")
        cut = _aware(self.knowledge_cut, "bundle knowledge_cut")
        if not self.components:
            raise OperatorModelError(
                "a component bundle must retain at least one component or residual"
            )
        ids = tuple(item.component_id for item in self.components)
        if tuple(sorted(ids)) != ids or len(set(ids)) != len(ids):
            raise OperatorModelError("bundle components must be sorted by unique component_id")
        for component in self.components:
            if component.knowledge_cut > cut or component.clocks.available_at > cut:
                raise TemporalClosureError("bundle includes future component evidence")
        if self.binding.clocks.available_at > cut:
            raise TemporalClosureError("bundle binding was unavailable at knowledge_cut")
        object.__setattr__(self, "knowledge_cut", cut)

    @property
    def artifact_digest(self) -> str:
        return deterministic_digest(self)


@dataclass(frozen=True, slots=True)
class OperatorAct:
    act_id: str
    kind: ActKind
    binding: SceneBinding
    observed_at: datetime
    knowledge_cut: datetime
    raw_assertion_id: str | None = None

    def __post_init__(self) -> None:
        _id(self.act_id, "act_id")
        observed = _aware(self.observed_at, "act observed_at")
        cut = _aware(self.knowledge_cut, "act knowledge_cut")
        if observed > cut or self.binding.clocks.available_at > cut:
            raise TemporalClosureError("act is not closed at its knowledge cut")
        if self.raw_assertion_id is not None:
            _id(self.raw_assertion_id, "act raw_assertion_id")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "knowledge_cut", cut)


@dataclass(frozen=True, slots=True)
class StatedIntention:
    """Evidence-only declaration; it intentionally cannot point to an economic effect."""

    intention_id: str
    kind: IntentionKind
    act_id: str | None
    raw_assertion_id: str
    binding: SceneBinding
    stated_at: datetime
    knowledge_cut: datetime
    text_bytes: bytes | None
    ambiguity: bool = False
    cannot_articulate: bool = False

    def __post_init__(self) -> None:
        _id(self.intention_id, "intention_id")
        if self.act_id is not None:
            _id(self.act_id, "intention act_id")
        _id(self.raw_assertion_id, "intention raw_assertion_id")
        stated = _aware(self.stated_at, "intention stated_at")
        cut = _aware(self.knowledge_cut, "intention knowledge_cut")
        if stated > cut or self.binding.clocks.available_at > cut:
            raise TemporalClosureError("intention is not closed at its knowledge cut")
        if self.cannot_articulate and self.text_bytes is not None:
            raise OperatorModelError("cannot-articulate intention cannot manufacture text")
        object.__setattr__(self, "stated_at", stated)
        object.__setattr__(self, "knowledge_cut", cut)


@dataclass(frozen=True, slots=True)
class ReconciledEconomicEffect:
    """Finality- and account-boundary-qualified observation, never a stated intention."""

    effect_id: str
    external_observation_id: str
    reconciliation_id: str
    account_boundary_id: str
    finalized_at: datetime
    available_at: datetime
    asset_deltas: tuple[tuple[str, int], ...]
    source_digest: str
    related_act_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "effect_id",
            "external_observation_id",
            "reconciliation_id",
            "account_boundary_id",
        ):
            _id(getattr(self, name), name)
        finalized = _aware(self.finalized_at, "effect finalized_at")
        available = _aware(self.available_at, "effect available_at")
        if available < finalized:
            raise OperatorModelError("effect available_at cannot precede finality")
        _digest(self.source_digest, "effect source_digest")
        if not self.asset_deltas:
            raise OperatorModelError(
                "economic effect requires independently reconciled asset deltas"
            )
        names = tuple(asset for asset, _ in self.asset_deltas)
        if tuple(sorted(names)) != names or len(set(names)) != len(names):
            raise OperatorModelError("effect asset deltas must have sorted unique assets")
        for asset, delta in self.asset_deltas:
            _id(asset, "effect asset")
            if isinstance(delta, bool) or not isinstance(delta, int):
                raise OperatorModelError("effect deltas must be exact signed atoms")
        _strictly_sorted_unique(self.related_act_ids, "related_act_ids")
        object.__setattr__(self, "finalized_at", finalized)
        object.__setattr__(self, "available_at", available)


@dataclass(frozen=True, slots=True)
class OntologyTerm:
    term_id: str
    version_id: str
    display_name: str
    defining_bytes: bytes
    created_at: datetime
    knowledge_cut: datetime
    elicitation_mode: str
    status: OntologyStatus
    intended_dimension: str
    positive_assertion_ids: tuple[str, ...] = ()
    boundary_assertion_ids: tuple[str, ...] = ()
    counterexample_assertion_ids: tuple[str, ...] = ()
    missing_predicates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "term_id",
            "version_id",
            "display_name",
            "elicitation_mode",
            "intended_dimension",
        ):
            _id(getattr(self, name), name)
        if not self.defining_bytes:
            raise OperatorModelError("ontology term requires exact defining bytes")
        created = _aware(self.created_at, "term created_at")
        cut = _aware(self.knowledge_cut, "term knowledge_cut")
        if created > cut:
            raise TemporalClosureError("term creation cannot be after its knowledge cut")
        for name in (
            "positive_assertion_ids",
            "boundary_assertion_ids",
            "counterexample_assertion_ids",
            "missing_predicates",
        ):
            _strictly_sorted_unique(getattr(self, name), name)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "knowledge_cut", cut)


@dataclass(frozen=True, slots=True)
class OntologyRelation:
    relation_id: str
    kind: OntologyRelationKind
    source_version_ids: tuple[str, ...]
    target_version_ids: tuple[str, ...]
    scope: RelationScope
    reason_bytes: bytes
    knowledge_cut: datetime

    def __post_init__(self) -> None:
        _id(self.relation_id, "relation_id")
        _strictly_sorted_unique(self.source_version_ids, "source_version_ids")
        _strictly_sorted_unique(self.target_version_ids, "target_version_ids")
        if not self.source_version_ids or not self.target_version_ids:
            raise OperatorModelError("ontology relation needs source and target versions")
        if self.kind is OntologyRelationKind.SPLIT_INTO and len(self.target_version_ids) < 2:
            raise OperatorModelError("split_into requires at least two target versions")
        if self.kind is OntologyRelationKind.MERGED_FROM and len(self.source_version_ids) < 2:
            raise OperatorModelError("merged_from requires at least two source versions")
        if not self.reason_bytes:
            raise OperatorModelError("ontology relation requires retained reason bytes")
        object.__setattr__(
            self, "knowledge_cut", _aware(self.knowledge_cut, "relation knowledge_cut")
        )


@dataclass(frozen=True, slots=True)
class OntologyAssignment:
    """A versioned interpretation, never a truth label or in-place rewrite."""

    assignment_id: str
    raw_assertion_id: str
    assigned_version_ids: tuple[str, ...]
    author_id: str
    assigned_at: datetime
    knowledge_cut: datetime
    ambiguity: bool
    reconsidered_assignment_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("assignment_id", "raw_assertion_id", "author_id"):
            _id(getattr(self, name), name)
        _strictly_sorted_unique(self.assigned_version_ids, "assigned_version_ids")
        if not self.assigned_version_ids and not self.ambiguity:
            raise OperatorModelError("an empty assignment must explicitly be ambiguous")
        assigned = _aware(self.assigned_at, "assignment assigned_at")
        cut = _aware(self.knowledge_cut, "assignment knowledge_cut")
        if assigned > cut:
            raise TemporalClosureError("assignment cannot postdate its knowledge cut")
        if self.reconsidered_assignment_id is not None:
            _id(self.reconsidered_assignment_id, "reconsidered_assignment_id")
            if self.reconsidered_assignment_id == self.assignment_id:
                raise OperatorModelError("an assignment cannot reconsider itself")
        object.__setattr__(self, "assigned_at", assigned)
        object.__setattr__(self, "knowledge_cut", cut)


@dataclass(frozen=True, slots=True)
class ReplayProtocol:
    protocol_id: str
    binding: SceneBinding
    selected_act_id: str | None
    blind_cut: datetime
    blind_commit_seq: int
    reveal_cut: datetime | None
    reveal_commit_seq: int | None
    blinded_refs: tuple[ReplayEvidenceRef, ...]
    revealed_refs: tuple[ReplayEvidenceRef, ...]
    prompt_bytes: bytes
    presentation_policy_id: str

    def __post_init__(self) -> None:
        _id(self.protocol_id, "protocol_id")
        if self.selected_act_id is not None:
            _id(self.selected_act_id, "selected_act_id")
        blind = _aware(self.blind_cut, "replay blind_cut")
        reveal = _aware(self.reveal_cut, "replay reveal_cut") if self.reveal_cut else None
        if reveal is not None and reveal < blind:
            raise OperatorModelError("replay reveal_cut cannot precede blind_cut")
        blind_commit = _positive_commit(self.blind_commit_seq, "replay blind_commit_seq")
        if reveal is None:
            if self.reveal_commit_seq is not None:
                raise OperatorModelError("replay without reveal_cut cannot carry reveal_commit_seq")
        elif self.reveal_commit_seq is None:
            raise OperatorModelError("replay reveal_cut requires reveal_commit_seq")
        else:
            reveal_commit = _positive_commit(self.reveal_commit_seq, "replay reveal_commit_seq")
            if reveal_commit < blind_commit:
                raise OperatorModelError("replay reveal_commit_seq cannot precede blind_commit_seq")
        if self.binding.clocks.available_at > blind:
            raise TemporalClosureError("replay scene/presentation was unavailable at blind_cut")
        if self.binding.maximum_commit_seq > blind_commit:
            raise TemporalClosureError("replay scene/presentation commits exceed blind_commit_seq")
        _ordered_unique_replay_refs(self.blinded_refs, "blinded_refs", nonempty=True)
        _ordered_unique_replay_refs(self.revealed_refs, "revealed_refs")
        if {item.artifact_id for item in self.blinded_refs} & {
            item.artifact_id for item in self.revealed_refs
        }:
            raise OperatorModelError("a replay reference cannot be both hidden and revealed")
        if not self.prompt_bytes:
            raise OperatorModelError("replay requires retained prompt bytes")
        _id(self.presentation_policy_id, "presentation_policy_id")
        object.__setattr__(self, "blind_cut", blind)
        object.__setattr__(self, "blind_commit_seq", blind_commit)
        object.__setattr__(self, "reveal_cut", reveal)
        if reveal is not None:
            object.__setattr__(self, "reveal_commit_seq", reveal_commit)

    @property
    def artifact_digest(self) -> str:
        return deterministic_digest(self)


@dataclass(frozen=True, slots=True)
class ReplayEvidenceRef:
    """A typed, versioned, content-addressed material artifact at a known cut."""

    artifact_type: ReplayArtifactType
    artifact_id: str
    version_id: str
    content_digest: str
    role: ReplayEvidenceRole
    available_at: datetime
    knowledge_cut: datetime
    available_commit_seq: int

    def __post_init__(self) -> None:
        _id(self.artifact_id, "replay evidence artifact_id")
        _id(self.version_id, "replay evidence version_id")
        _digest(self.content_digest, "replay evidence content_digest")
        available = _aware(self.available_at, "replay evidence available_at")
        cut = _aware(self.knowledge_cut, "replay evidence knowledge_cut")
        if available > cut:
            raise TemporalClosureError("replay evidence was unavailable at its knowledge_cut")
        _positive_commit(self.available_commit_seq, "replay evidence available_commit_seq")
        expected_role = {
            ReplayArtifactType.SCENE_COMPONENT_PROJECTION: ReplayEvidenceRole.SCENE_COMPONENT,
            ReplayArtifactType.PRESENTATION_OCCURRENCE: ReplayEvidenceRole.PRESENTATION,
            ReplayArtifactType.OPERATOR_ACT: ReplayEvidenceRole.ACT,
            ReplayArtifactType.RAW_OPERATOR_ASSERTION: ReplayEvidenceRole.OPERATOR_ASSERTION,
            ReplayArtifactType.RECONCILED_ECONOMIC_EFFECT: ReplayEvidenceRole.ECONOMIC_EFFECT,
            ReplayArtifactType.OUTCOME: ReplayEvidenceRole.OUTCOME,
        }[self.artifact_type]
        if self.role is not expected_role:
            raise OperatorModelError("replay evidence role must match typed artifact")
        object.__setattr__(
            self,
            "available_at",
            available,
        )
        object.__setattr__(self, "knowledge_cut", cut)


def _ordered_unique_replay_refs(
    refs: tuple[ReplayEvidenceRef, ...], name: str, *, nonempty: bool = False
) -> None:
    if nonempty and not refs:
        raise OperatorModelError(f"{name} must not be empty")
    ids = tuple(item.artifact_id for item in refs)
    if tuple(sorted(ids)) != ids or len(set(ids)) != len(ids):
        raise OperatorModelError(f"{name} must be ordered by unique artifact_id")


def _expected_replay_refs(
    protocol: ReplayProtocol, phase: ReplayPhase
) -> tuple[ReplayEvidenceRef, ...]:
    if phase is ReplayPhase.OUTCOME_BLINDED:
        return protocol.blinded_refs
    if protocol.reveal_cut is None:
        raise OperatorModelError("outcome-aware replay requires an exact reveal_cut")
    if not protocol.revealed_refs:
        raise OperatorModelError("outcome-aware replay requires declared revealed material")
    return protocol.blinded_refs + protocol.revealed_refs


def _validate_replay_evidence(
    protocol: ReplayProtocol,
    phase: ReplayPhase,
    evidence: tuple[ReplayEvidenceRef, ...],
) -> tuple[ReplayEvidenceRef, ...]:
    """Close material to the exact phase-specific protocol references and clocks."""

    expected = _expected_replay_refs(protocol, phase)
    if evidence != expected:
        raise OperatorModelError(
            "replay evidence must exactly close the ordered typed material set"
        )
    for item in protocol.blinded_refs:
        if item.available_at > protocol.blind_cut:
            raise TemporalClosureError("blind replay includes evidence unavailable at blind_cut")
        if item.knowledge_cut > protocol.blind_cut:
            raise TemporalClosureError("blind replay evidence knowledge_cut exceeds blind_cut")
        if item.available_commit_seq > protocol.blind_commit_seq:
            raise TemporalClosureError("blind replay evidence commit exceeds blind_commit_seq")
        if item.artifact_type in {
            ReplayArtifactType.RECONCILED_ECONOMIC_EFFECT,
            ReplayArtifactType.OUTCOME,
        }:
            raise OperatorModelError(
                "blind replay cannot include an economic effect or later outcome"
            )
    if phase is ReplayPhase.OUTCOME_AWARE:
        assert protocol.reveal_cut is not None
        assert protocol.reveal_commit_seq is not None
        for item in protocol.revealed_refs:
            if item.available_at > protocol.reveal_cut:
                raise TemporalClosureError(
                    "revealed replay includes evidence unavailable at reveal_cut"
                )
            if item.knowledge_cut > protocol.reveal_cut:
                raise TemporalClosureError(
                    "revealed replay evidence knowledge_cut exceeds reveal_cut"
                )
            if item.available_commit_seq > protocol.reveal_commit_seq:
                raise TemporalClosureError(
                    "revealed replay evidence commit exceeds reveal_commit_seq"
                )
    return expected


def _material_digest_payload(
    *,
    protocol_id: str,
    protocol_digest: str,
    binding_digest: str,
    phase: ReplayPhase,
    material_cut: datetime,
    material_commit_seq: int,
    evidence: tuple[ReplayEvidenceRef, ...],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": protocol_id,
        "protocol_digest": protocol_digest,
        "binding_digest": binding_digest,
        "phase": phase,
        "material_cut": material_cut,
        "material_commit_seq": material_commit_seq,
        "evidence": evidence,
    }


@dataclass(frozen=True, slots=True)
class ReplayMaterialReceipt:
    """A phase-specific, scene-bound materialization receipt for one replay pass.

    The receipt is deterministic only over caller-supplied evidence. It makes no
    claim that a store actually rendered the material or that a person saw it.
    """

    receipt_id: str
    protocol_id: str
    protocol_digest: str
    binding_digest: str
    phase: ReplayPhase
    material_cut: datetime
    material_commit_seq: int
    presented_at: datetime
    evidence: tuple[ReplayEvidenceRef, ...]
    material_digest: str = field(init=False)
    phase_receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _id(self.receipt_id, "replay receipt_id")
        _id(self.protocol_id, "replay receipt protocol_id")
        _digest(self.protocol_digest, "replay receipt protocol_digest")
        _digest(self.binding_digest, "replay receipt binding_digest")
        cut = _aware(self.material_cut, "replay material_cut")
        commit = _positive_commit(self.material_commit_seq, "replay material_commit_seq")
        presented = _aware(self.presented_at, "replay material presented_at")
        if presented < cut:
            raise TemporalClosureError(
                "replay material cannot be presented before its material_cut"
            )
        if not self.evidence:
            raise OperatorModelError("replay material receipt requires evidence")
        evidence_ids = tuple(item.artifact_id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise OperatorModelError("replay material receipt evidence ids must be unique")
        material_digest = deterministic_digest(
            _material_digest_payload(
                protocol_id=self.protocol_id,
                protocol_digest=self.protocol_digest,
                binding_digest=self.binding_digest,
                phase=self.phase,
                material_cut=cut,
                material_commit_seq=commit,
                evidence=self.evidence,
            )
        )
        receipt_digest = deterministic_digest(
            {
                "material_digest": material_digest,
                "receipt_id": self.receipt_id,
                "phase": self.phase,
                "presented_at": presented,
            }
        )
        object.__setattr__(self, "material_cut", cut)
        object.__setattr__(self, "material_commit_seq", commit)
        object.__setattr__(self, "presented_at", presented)
        object.__setattr__(self, "material_digest", material_digest)
        object.__setattr__(self, "phase_receipt_digest", receipt_digest)


def materialize_replay(
    protocol: ReplayProtocol,
    *,
    receipt_id: str,
    phase: ReplayPhase,
    presented_at: datetime,
    evidence: tuple[ReplayEvidenceRef, ...],
) -> ReplayMaterialReceipt:
    """Create a material receipt only when its phase has exact reference closure."""

    ordered_evidence = _validate_replay_evidence(protocol, phase, evidence)
    if phase is ReplayPhase.OUTCOME_BLINDED:
        material_cut = protocol.blind_cut
        material_commit_seq = protocol.blind_commit_seq
    else:
        material_cut = protocol.reveal_cut
        material_commit_seq = protocol.reveal_commit_seq
    assert material_cut is not None and material_commit_seq is not None
    presented = _aware(presented_at, "replay material presented_at")
    if phase is ReplayPhase.OUTCOME_BLINDED:
        if protocol.reveal_cut is not None and presented >= protocol.reveal_cut:
            raise TemporalClosureError(
                "outcome-blinded material cannot be presented at or after reveal"
            )
    elif presented < material_cut:
        raise TemporalClosureError("outcome-aware material cannot be presented before reveal")
    return ReplayMaterialReceipt(
        receipt_id=receipt_id,
        protocol_id=protocol.protocol_id,
        protocol_digest=protocol.artifact_digest,
        binding_digest=protocol.binding.artifact_digest,
        phase=phase,
        material_cut=material_cut,
        material_commit_seq=material_commit_seq,
        presented_at=presented,
        evidence=ordered_evidence,
    )


def validate_replay_material(protocol: ReplayProtocol, receipt: ReplayMaterialReceipt) -> None:
    """Revalidate a receipt against the exact protocol, phase, scene, and clocks."""

    if receipt.protocol_id != protocol.protocol_id:
        raise OperatorModelError("replay receipt protocol identity does not match protocol")
    if receipt.protocol_digest != protocol.artifact_digest:
        raise OperatorModelError("replay receipt protocol digest does not match protocol")
    if receipt.binding_digest != protocol.binding.artifact_digest:
        raise OperatorModelError(
            "replay receipt scene/presentation binding does not match protocol"
        )
    if receipt.phase is ReplayPhase.OUTCOME_BLINDED:
        expected_cut = protocol.blind_cut
        expected_commit = protocol.blind_commit_seq
    else:
        expected_cut = protocol.reveal_cut
        expected_commit = protocol.reveal_commit_seq
    if expected_cut is None or receipt.material_cut != expected_cut:
        raise TemporalClosureError("replay receipt material_cut does not match its protocol phase")
    if expected_commit is None or receipt.material_commit_seq != expected_commit:
        raise TemporalClosureError(
            "replay receipt material_commit_seq does not match its protocol phase"
        )
    expected_evidence = _validate_replay_evidence(protocol, receipt.phase, receipt.evidence)
    if receipt.evidence != expected_evidence:
        raise OperatorModelError("replay receipt evidence order does not match protocol closure")
    expected_material_digest = deterministic_digest(
        _material_digest_payload(
            protocol_id=receipt.protocol_id,
            protocol_digest=receipt.protocol_digest,
            binding_digest=receipt.binding_digest,
            phase=receipt.phase,
            material_cut=receipt.material_cut,
            material_commit_seq=receipt.material_commit_seq,
            evidence=receipt.evidence,
        )
    )
    if receipt.material_digest != expected_material_digest:
        raise OperatorModelError("replay receipt material digest is not canonical")
    expected_receipt_digest = deterministic_digest(
        {
            "material_digest": receipt.material_digest,
            "receipt_id": receipt.receipt_id,
            "phase": receipt.phase,
            "presented_at": receipt.presented_at,
        }
    )
    if receipt.phase_receipt_digest != expected_receipt_digest:
        raise OperatorModelError("replay phase receipt digest is not canonical")
    if receipt.phase is ReplayPhase.OUTCOME_BLINDED:
        if protocol.reveal_cut is not None and receipt.presented_at >= protocol.reveal_cut:
            raise TemporalClosureError("outcome-blinded material is at or after reveal")
    elif receipt.presented_at < expected_cut:
        raise TemporalClosureError("outcome-aware material is before reveal")


@dataclass(frozen=True, slots=True)
class RecognitionResponse:
    response_id: str
    protocol_id: str
    phase: ReplayPhase
    recognition: RecognitionKind
    responded_at: datetime
    replay_receipt_id: str
    replay_material_digest: str
    replay_phase_receipt_digest: str
    raw_assertion_id: str | None
    explanation_bytes: bytes | None
    ontology_assignment_id: str | None = None
    ambiguity: bool = False

    def __post_init__(self) -> None:
        _id(self.response_id, "response_id")
        _id(self.protocol_id, "response protocol_id")
        responded = _aware(self.responded_at, "recognition responded_at")
        _id(self.replay_receipt_id, "recognition replay_receipt_id")
        _digest(self.replay_material_digest, "recognition replay_material_digest")
        _digest(self.replay_phase_receipt_digest, "recognition replay_phase_receipt_digest")
        if self.raw_assertion_id is not None:
            _id(self.raw_assertion_id, "recognition raw_assertion_id")
        if self.ontology_assignment_id is not None:
            _id(self.ontology_assignment_id, "recognition ontology_assignment_id")
        if (
            self.recognition is RecognitionKind.CANNOT_RECONSTRUCT
            and self.explanation_bytes is not None
        ):
            raise OperatorModelError(
                "cannot-reconstruct response cannot manufacture explanation bytes"
            )
        object.__setattr__(self, "responded_at", responded)


@dataclass(frozen=True, slots=True)
class RecognitionComparison:
    """A deterministic summary of response states, explicitly not label validation."""

    protocol_id: str
    response_ids: tuple[str, ...]
    counts: tuple[tuple[RecognitionKind, int], ...]
    claim_scope: str = "recognition_comparison_not_label_truth_or_private_state"
    artifact_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _id(self.protocol_id, "comparison protocol_id")
        _strictly_sorted_unique(self.response_ids, "comparison response_ids")
        if self.claim_scope != "recognition_comparison_not_label_truth_or_private_state":
            raise OperatorModelError("recognition comparison claim scope is fixed")
        object.__setattr__(
            self,
            "artifact_digest",
            deterministic_digest(
                {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_id": self.protocol_id,
                    "response_ids": self.response_ids,
                    "counts": self.counts,
                    "claim_scope": self.claim_scope,
                }
            ),
        )


def compare_recognition(
    protocol: ReplayProtocol,
    receipts: tuple[ReplayMaterialReceipt, ...],
    responses: tuple[RecognitionResponse, ...],
) -> RecognitionComparison:
    """Summarize receipts-closed recognition, without validating ontology labels."""

    if not responses:
        raise OperatorModelError("recognition comparison needs at least one response")
    receipt_by_id = {receipt.receipt_id: receipt for receipt in receipts}
    if not receipt_by_id or len(receipt_by_id) != len(receipts):
        raise OperatorModelError("recognition comparison requires unique material receipts")
    for receipt in receipts:
        validate_replay_material(protocol, receipt)
    ids = tuple(sorted(response.response_id for response in responses))
    if len(set(ids)) != len(ids):
        raise OperatorModelError("recognition response ids must be unique")
    if any(response.protocol_id != protocol.protocol_id for response in responses):
        raise OperatorModelError("all recognition responses must belong to the replay protocol")
    for response in responses:
        receipt = receipt_by_id.get(response.replay_receipt_id)
        if receipt is None:
            raise OperatorModelError("recognition response names a receipt outside comparison")
        if response.phase is not receipt.phase:
            raise OperatorModelError("recognition response phase does not match material receipt")
        if response.replay_material_digest != receipt.material_digest:
            raise OperatorModelError("recognition response material digest does not match receipt")
        if response.replay_phase_receipt_digest != receipt.phase_receipt_digest:
            raise OperatorModelError("recognition response phase receipt does not match receipt")
        if response.phase is ReplayPhase.OUTCOME_BLINDED:
            if protocol.reveal_cut is not None and response.responded_at >= protocol.reveal_cut:
                raise TemporalClosureError(
                    "outcome-blinded response cannot occur at or after reveal"
                )
        else:
            if protocol.reveal_cut is None or response.responded_at < protocol.reveal_cut:
                raise TemporalClosureError("outcome-aware response cannot occur before reveal")
        if response.responded_at < receipt.presented_at:
            raise TemporalClosureError("recognition response precedes replay material presentation")
    counts = tuple(
        (kind, sum(response.recognition is kind for response in responses))
        for kind in RecognitionKind
    )
    return RecognitionComparison(protocol.protocol_id, ids, counts)
