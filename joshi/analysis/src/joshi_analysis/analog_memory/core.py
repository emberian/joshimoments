from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes, require_qualified_sha256
from ..errors import ManifestError, TemporalLeakageError


class MissingPolicy(StrEnum):
    """How a named distance component handles a missing or explicit gap."""

    SKIP = "skip"
    PENALIZE = "penalize"
    EXCLUDE = "exclude"


class OutcomeClosureStatus(StrEnum):
    """The exhaustive outcome-closure partition used only by retrospective reveal."""

    MATURED = "matured"
    MISSING = "missing"
    CONFLICTING = "conflicting"
    CENSORED = "censored"


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ManifestError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, bool):
        raise ManifestError("boolean feature values are not exact numeric or categorical values")
    if isinstance(value, Decimal):
        if not value.is_finite() or abs(value) > Decimal("1e12"):
            raise ManifestError("decimal feature values must be finite and bounded")
        return {"decimal": format(value, "f")}
    if isinstance(value, int):
        if abs(value) > 10**12:
            raise ManifestError("integer feature values must be bounded")
        return value
    if isinstance(value, (str,)) or value is None:
        return value
    raise ManifestError(f"unsupported feature value type: {type(value).__name__}")


def _exact_decimal(value: Decimal | int | str, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ManifestError(f"{field} must be an exact decimal, integer, or decimal string")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ManifestError(f"{field} is not a decimal") from error
    if not result.is_finite() or abs(result) > Decimal("1e9"):
        raise ManifestError(f"{field} must be finite and bounded")
    return result


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    """One feature with its as-known/availability boundary and missingness state."""

    status: str
    value: Any
    known_at: datetime
    available_at: datetime
    gap_id: str | None = None
    ontology_effective_at: datetime | None = None
    identity_effective_at: datetime | None = None
    ontology_version: str | None = None
    ontology_digest: str | None = None
    identity_version: str | None = None
    identity_digest: str | None = None
    outcome_derived: bool = False
    gap_closed: bool = False
    gap_closed_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        known_at = _aware(self.known_at, "feature.known_at")
        available_at = _aware(self.available_at, "feature.available_at")
        if self.status not in {"observed", "missing", "gap"}:
            raise ManifestError(f"unsupported feature status: {self.status}")
        if self.status == "observed" and self.value is None:
            raise ManifestError("observed feature must have a value")
        if self.status != "observed" and self.value is not None:
            raise ManifestError("missing/gap feature cannot carry a value")
        if self.status == "gap":
            if not self.gap_id:
                raise ManifestError("gap feature requires gap_id")
            if self.gap_closed and self.gap_closed_at is None:
                raise ManifestError("closed gap requires gap_closed_at")
            if not self.gap_closed and self.gap_closed_at is not None:
                raise ManifestError("open gap cannot carry gap_closed_at")
        elif self.gap_id is not None or self.gap_closed:
            raise ManifestError("only gap features may carry gap state")
        elif self.gap_closed_at is not None:
            raise ManifestError("only gap features may carry gap_closed_at")
        for prefix, version, digest in (
            ("ontology", self.ontology_version, self.ontology_digest),
            ("identity", self.identity_version, self.identity_digest),
        ):
            if version is None or digest is None:
                raise ManifestError(f"feature {prefix} version and digest are required")
            if (version is None) != (digest is None):
                raise ManifestError(f"{prefix} version and digest must be paired")
            if digest is not None:
                try:
                    require_qualified_sha256(digest, f"feature.{prefix}_digest")
                except ValueError as error:
                    raise ManifestError(str(error)) from error
        return {
            "status": self.status,
            "value": _canonical_value(self.value),
            "known_at": known_at.isoformat().replace("+00:00", "Z"),
            "available_at": available_at.isoformat().replace("+00:00", "Z"),
            "gap_id": self.gap_id,
            "ontology_effective_at": (
                _aware(self.ontology_effective_at, "feature.ontology_effective_at")
                .isoformat()
                .replace("+00:00", "Z")
                if self.ontology_effective_at is not None
                else None
            ),
            "identity_effective_at": (
                _aware(self.identity_effective_at, "feature.identity_effective_at")
                .isoformat()
                .replace("+00:00", "Z")
                if self.identity_effective_at is not None
                else None
            ),
            "ontology_version": self.ontology_version,
            "ontology_digest": self.ontology_digest,
            "identity_version": self.identity_version,
            "identity_digest": self.identity_digest,
            "outcome_derived": self.outcome_derived,
            "gap_closed": self.gap_closed,
            "gap_closed_at": (
                _aware(self.gap_closed_at, "feature.gap_closed_at")
                .isoformat()
                .replace("+00:00", "Z")
                if self.gap_closed_at is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class FilterObservation:
    """A typed, outcome-free filter value with an as-known boundary."""

    value: Any
    known_at: datetime
    available_at: datetime
    ontology_version: str
    ontology_digest: str
    identity_version: str
    identity_digest: str
    outcome_derived: bool = False

    def as_dict(self) -> dict[str, Any]:
        known = _aware(self.known_at, "filter.known_at")
        available = _aware(self.available_at, "filter.available_at")
        if available < known:
            raise ManifestError("filter availability precedes known time")
        if self.outcome_derived:
            raise ManifestError("outcome-derived filter is forbidden")
        _canonical_value(self.value)
        for field_name, digest in (
            ("ontology_digest", self.ontology_digest),
            ("identity_digest", self.identity_digest),
        ):
            try:
                require_qualified_sha256(digest, f"filter.{field_name}")
            except ValueError as error:
                raise ManifestError(str(error)) from error
        if not self.ontology_version.strip() or not self.identity_version.strip():
            raise ManifestError("filter ontology and identity versions are required")
        return {
            "value": _canonical_value(self.value),
            "known_at": known.isoformat().replace("+00:00", "Z"),
            "available_at": available.isoformat().replace("+00:00", "Z"),
            "ontology_version": self.ontology_version,
            "ontology_digest": self.ontology_digest,
            "identity_version": self.identity_version,
            "identity_digest": self.identity_digest,
            "outcome_derived": self.outcome_derived,
        }


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """A point-in-time decision record; outcomes are intentionally not a field."""

    decision_id: str
    subject_id: str
    decision_cutoff: datetime
    features: Mapping[str, FeatureObservation]
    filters: Mapping[str, FilterObservation] = field(default_factory=dict)

    def validate(self) -> None:
        cutoff = _aware(self.decision_cutoff, "decision_cutoff")
        if not self.decision_id.strip() or not self.subject_id.strip():
            raise ManifestError("decision and subject IDs are required")
        for name, feature in self.features.items():
            if not name.strip():
                raise ManifestError("feature names cannot be empty")
            data = feature.as_dict()
            known_at = datetime.fromisoformat(data["known_at"].replace("Z", "+00:00"))
            available_at = datetime.fromisoformat(data["available_at"].replace("Z", "+00:00"))
            if available_at < known_at:
                raise ManifestError(f"feature {name} availability precedes its known time")
            if known_at > cutoff or available_at > cutoff:
                raise TemporalLeakageError(
                    f"feature {name} is not as-known at decision {self.decision_id}"
                )
            if (
                feature.gap_closed_at is not None
                and _aware(feature.gap_closed_at, "feature.gap_closed_at") > cutoff
            ):
                raise TemporalLeakageError(
                    f"feature {name} gap closure is not as-known at decision {self.decision_id}"
                )
            for field_name in ("ontology_effective_at", "identity_effective_at"):
                effective = data[field_name]
                if (
                    effective is not None
                    and datetime.fromisoformat(effective.replace("Z", "+00:00")) > cutoff
                ):
                    raise TemporalLeakageError(
                        f"feature {name} uses a later {field_name} at decision {self.decision_id}"
                    )
            for prefix, version, digest in (
                ("ontology", feature.ontology_version, feature.ontology_digest),
                ("identity", feature.identity_version, feature.identity_digest),
            ):
                if version is not None and not version.strip():
                    raise ManifestError(f"feature {name} has empty {prefix} version")
                if digest is not None and not version:
                    raise ManifestError(f"feature {name} has digest without {prefix} version")
            if feature.outcome_derived:
                raise TemporalLeakageError(f"outcome-derived feature {name} is forbidden")
        for name, observation in self.filters.items():
            if not name.strip():
                raise ManifestError("filter names cannot be empty")
            data = observation.as_dict()
            known_at = datetime.fromisoformat(data["known_at"].replace("Z", "+00:00"))
            available_at = datetime.fromisoformat(data["available_at"].replace("Z", "+00:00"))
            if known_at > cutoff or available_at > cutoff:
                raise TemporalLeakageError(
                    f"filter {name} is not as-known at decision {self.decision_id}"
                )

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "decision_id": self.decision_id,
            "subject_id": self.subject_id,
            "decision_cutoff": _aware(self.decision_cutoff, "decision_cutoff")
            .isoformat()
            .replace("+00:00", "Z"),
            "features": {name: self.features[name].as_dict() for name in sorted(self.features)},
            "filters": {name: self.filters[name].as_dict() for name in sorted(self.filters)},
        }


@dataclass(frozen=True, slots=True)
class DistanceSpec:
    """Named, versioned decomposed distance specification."""

    spec_id: str
    version: str
    feature_weights: Mapping[str, Decimal | int | str]
    missing_policy: MissingPolicy = MissingPolicy.SKIP
    missing_penalty: Decimal | int | str = Decimal("1")

    def validate(self) -> None:
        if not self.spec_id.strip() or not self.version.strip():
            raise ManifestError("distance specification identity is required")
        if not self.feature_weights:
            raise ManifestError("distance specification needs at least one feature")
        penalty = _exact_decimal(self.missing_penalty, "missing penalty")
        if penalty < 0 or penalty > Decimal("1e9"):
            raise ManifestError("missing penalty cannot be negative")
        for name, weight in self.feature_weights.items():
            exact = _exact_decimal(weight, f"weight {name}")
            if not name.strip() or exact < 0 or exact > Decimal("1e9"):
                raise ManifestError("distance feature names/weights are invalid")
        if all(_exact_decimal(weight, "weight") == 0 for weight in self.feature_weights.values()):
            raise ManifestError("distance specification needs a nonzero weight")

    def exact_weights(self) -> dict[str, Decimal]:
        self.validate()
        return {
            name: _exact_decimal(weight, f"weight {name}")
            for name, weight in self.feature_weights.items()
        }

    def exact_penalty(self) -> Decimal:
        self.validate()
        return _exact_decimal(self.missing_penalty, "missing penalty")


@dataclass(frozen=True, slots=True)
class FilterSpec:
    """Plain deterministic filter baseline, evaluated only on as-known fields."""

    filter_id: str
    fields: Mapping[str, FilterObservation]
    version: str = "1"
    as_known_cutoff: datetime | None = None
    spec_digest: str | None = None

    def validate(self, cutoff: datetime) -> None:
        if not self.filter_id.strip() or not self.version.strip():
            raise ManifestError("filter specification identity is required")
        if (
            self.as_known_cutoff is not None
            and _aware(self.as_known_cutoff, "filter.as_known_cutoff") > cutoff
        ):
            raise TemporalLeakageError("filter specification is not as-known at query cutoff")
        if self.spec_digest is not None:
            try:
                require_qualified_sha256(self.spec_digest, "filter.spec_digest")
            except ValueError as error:
                raise ManifestError(str(error)) from error
        for field_name, observation in self.fields.items():
            if not field_name.strip():
                raise ManifestError("filter field names cannot be empty")
            known = _aware(observation.known_at, "filter.known_at")
            available = _aware(observation.available_at, "filter.available_at")
            observation.as_dict()
            if known > cutoff or available > cutoff:
                raise TemporalLeakageError("filter field is not as-known at query cutoff")


@dataclass(frozen=True, slots=True)
class Neighbor:
    decision_id: str
    subject_id: str
    decision_cutoff: datetime
    distance: Decimal
    components: Mapping[str, Decimal | None]
    missing_components: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "subject_id": self.subject_id,
            "decision_cutoff": _aware(self.decision_cutoff, "neighbor.decision_cutoff")
            .isoformat()
            .replace("+00:00", "Z"),
            "distance": format(self.distance, "f"),
            "components": {
                name: (
                    format(self.components[name], "f")
                    if self.components[name] is not None
                    else None
                )
                for name in sorted(self.components)
            },
            "missing_components": list(self.missing_components),
        }


@dataclass(frozen=True, slots=True)
class AnalogArtifact:
    query_id: str
    query_cutoff: datetime
    distance_spec: DistanceSpec
    status: str
    neighbors: tuple[Neighbor, ...]
    claim_scope: str = "retrieval_only_not_prediction_or_strategy_claim"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": "joshi.analysis.analog_memory/v1",
            "mode": "decision",
            "query_id": self.query_id,
            "query_cutoff": _aware(self.query_cutoff, "query_cutoff")
            .isoformat()
            .replace("+00:00", "Z"),
            "distance_spec": {
                "spec_id": self.distance_spec.spec_id,
                "version": self.distance_spec.version,
                "feature_weights": {
                    name: format(
                        _exact_decimal(self.distance_spec.feature_weights[name], "weight"),
                        "f",
                    )
                    for name in sorted(self.distance_spec.feature_weights)
                },
                "missing_policy": self.distance_spec.missing_policy.value,
                "missing_penalty": format(self.distance_spec.exact_penalty(), "f"),
            },
            "status": self.status,
            "neighbors": [neighbor.as_dict() for neighbor in self.neighbors],
            "claim_scope": self.claim_scope,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict(), newline=True)

    @property
    def digest(self) -> str:
        return qualified_sha256_bytes(self.canonical_bytes())


@dataclass(frozen=True, slots=True)
class PlainFilterArtifact:
    query_id: str
    query_cutoff: datetime
    filter_spec: FilterSpec
    candidate_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": "joshi.analysis.analog_memory.plain_filter/v1",
            "mode": "decision",
            "query_id": self.query_id,
            "query_cutoff": _aware(self.query_cutoff, "query_cutoff")
            .isoformat()
            .replace("+00:00", "Z"),
            "filter_spec": {
                "filter_id": self.filter_spec.filter_id,
                "version": self.filter_spec.version,
                "as_known_cutoff": (
                    _aware(self.filter_spec.as_known_cutoff, "filter.as_known_cutoff")
                    .isoformat()
                    .replace("+00:00", "Z")
                    if self.filter_spec.as_known_cutoff is not None
                    else None
                ),
                "spec_digest": self.filter_spec.spec_digest,
                "fields": {
                    name: self.filter_spec.fields[name].as_dict()
                    for name in sorted(self.filter_spec.fields)
                },
            },
            "candidate_ids": list(self.candidate_ids),
            "claim_scope": "plain_filter_baseline_only",
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict(), newline=True)


@dataclass(frozen=True, slots=True)
class OutcomeClosure:
    """Typed retrospective outcome maturity; never part of decision retrieval."""

    status: OutcomeClosureStatus | str
    known_at: datetime
    maturity_at: datetime | None = None
    outcome_digest: str | None = None
    evidence_digest: str | None = None
    reason: str | None = None
    conflicting_evidence_digests: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        known = _aware(self.known_at, "outcome.known_at")
        try:
            status = OutcomeClosureStatus(self.status)
        except ValueError as error:
            raise ManifestError("unsupported outcome closure status") from error
        if self.maturity_at is None:
            raise ManifestError("outcome closure requires maturity_at")
        maturity = _aware(self.maturity_at, "outcome.maturity_at")
        if maturity < known:
            raise ManifestError("outcome maturity precedes known time")
        if status is OutcomeClosureStatus.MATURED:
            if (
                self.outcome_digest is None
                or self.evidence_digest is None
            ):
                raise ManifestError("matured outcome requires maturity and evidence digests")
            for name, digest in (
                ("outcome_digest", self.outcome_digest),
                ("evidence_digest", self.evidence_digest),
            ):
                try:
                    require_qualified_sha256(digest, f"outcome.{name}")
                except ValueError as error:
                    raise ManifestError(str(error)) from error
            if self.reason is not None or self.conflicting_evidence_digests:
                raise ManifestError("matured outcome cannot carry closure reason or conflicts")
        elif (
            self.outcome_digest is not None
            or self.evidence_digest is not None
        ):
            raise ManifestError("non-matured outcome cannot carry outcome or evidence digest")
        if status in {
            OutcomeClosureStatus.MISSING,
            OutcomeClosureStatus.CONFLICTING,
            OutcomeClosureStatus.CENSORED,
        } and (self.reason is None or not self.reason.strip()):
            raise ManifestError("non-matured outcome requires a reason")
        if status is OutcomeClosureStatus.CONFLICTING:
            if len(self.conflicting_evidence_digests) < 2:
                raise ManifestError("conflicting outcome requires at least two evidence digests")
            if (
                tuple(sorted(self.conflicting_evidence_digests))
                != self.conflicting_evidence_digests
            ):
                raise ManifestError("conflicting outcome evidence digests must be sorted")
            if (
                len(set(self.conflicting_evidence_digests))
                != len(self.conflicting_evidence_digests)
            ):
                raise ManifestError("conflicting outcome evidence digests must be unique")
            for digest in self.conflicting_evidence_digests:
                try:
                    require_qualified_sha256(digest, "outcome.conflicting_evidence_digest")
                except ValueError as error:
                    raise ManifestError(str(error)) from error
        elif self.conflicting_evidence_digests:
            raise ManifestError("only conflicting outcome may carry conflicting evidence digests")
        return {
            "status": status.value,
            "known_at": known.isoformat().replace("+00:00", "Z"),
            "maturity_at": maturity.isoformat().replace("+00:00", "Z"),
            "outcome_digest": self.outcome_digest,
            "evidence_digest": self.evidence_digest,
            "reason": self.reason,
            "conflicting_evidence_digests": list(self.conflicting_evidence_digests),
        }


@dataclass(frozen=True, slots=True)
class RetrospectiveReveal:
    """Separate intervention that joins outcomes after decision-mode retrieval."""

    reveal_id: str
    source_artifact_digest: str
    outcomes: tuple[tuple[str, OutcomeClosure], ...]
    revealed_at: datetime

    def as_dict(self) -> dict[str, Any]:
        try:
            require_qualified_sha256(self.source_artifact_digest, "reveal.source_artifact_digest")
        except ValueError as error:
            raise ManifestError(str(error)) from error
        return {
            "contract": "joshi.analysis.analog_memory.retrospective_reveal/v1",
            "mode": "retrospective",
            "reveal_id": self.reveal_id,
            "source_artifact_digest": self.source_artifact_digest,
            "outcomes": [
                {"decision_id": key, "outcome": value.as_dict()} for key, value in self.outcomes
            ],
            "revealed_at": _aware(self.revealed_at, "revealed_at")
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict(), newline=True)


def _component_distance(left: Any, right: Any) -> Decimal:
    if isinstance(left, bool) or isinstance(right, bool):
        raise ManifestError("boolean values cannot enter exact distance")
    if isinstance(left, (int, Decimal)) and isinstance(right, (int, Decimal)):
        return abs(Decimal(left) - Decimal(right))
    return Decimal(0) if left == right else Decimal(1)


def _validate_unique_records(records: list[DecisionRecord] | tuple[DecisionRecord, ...]) -> None:
    seen_decisions: dict[str, dict[str, Any]] = {}
    seen_subjects: dict[str, dict[str, Any]] = {}
    for record in records:
        record.validate()
        data = record.as_dict()
        if record.decision_id in seen_decisions:
            raise ManifestError(f"duplicate decision identity: {record.decision_id}")
        if record.subject_id in seen_subjects:
            raise ManifestError(f"duplicate subject identity: {record.subject_id}")
        seen_decisions[record.decision_id] = data
        seen_subjects[record.subject_id] = data


def retrieve(
    query: DecisionRecord,
    candidates: list[DecisionRecord] | tuple[DecisionRecord, ...],
    distance_spec: DistanceSpec,
    *,
    limit: int = 5,
) -> AnalogArtifact:
    """Retrieve deterministic earlier-only neighbors with decomposed distances.

    # Raises

    ``TemporalLeakageError`` when any candidate or query feature is not valid at its own
    decision cutoff.
    """

    if limit < 1:
        raise ValueError("limit must be positive")
    query.validate()
    distance_spec.validate()
    _validate_unique_records(candidates)
    if any(candidate.decision_id == query.decision_id for candidate in candidates):
        raise ManifestError("query decision identity is also a candidate")
    if any(candidate.subject_id == query.subject_id for candidate in candidates):
        raise ManifestError("query subject identity is also a candidate")
    query_cutoff = _aware(query.decision_cutoff, "query_cutoff")
    scored: list[Neighbor] = []
    for candidate in candidates:
        candidate.validate()
        candidate_cutoff = _aware(candidate.decision_cutoff, "candidate.decision_cutoff")
        if candidate_cutoff >= query_cutoff:
            raise TemporalLeakageError("neighbor decision cutoff must be strictly earlier")
        components: dict[str, Decimal | None] = {}
        missing: list[str] = []
        excluded = False
        for name, weight in sorted(distance_spec.exact_weights().items()):
            left = query.features.get(name)
            right = candidate.features.get(name)
            if (
                left is None
                or right is None
                or left.status != "observed"
                or right.status != "observed"
            ):
                missing.append(name)
                if distance_spec.missing_policy == MissingPolicy.EXCLUDE:
                    excluded = True
                    break
                components[name] = (
                    distance_spec.exact_penalty() * weight
                    if distance_spec.missing_policy == MissingPolicy.PENALIZE
                    else None
                )
            else:
                components[name] = _component_distance(left.value, right.value) * weight
        if excluded:
            continue
        observed_components = [value for value in components.values() if value is not None]
        if not observed_components:
            continue
        scored.append(
            Neighbor(
                decision_id=candidate.decision_id,
                subject_id=candidate.subject_id,
                decision_cutoff=candidate_cutoff,
                distance=sum(observed_components),
                components=components,
                missing_components=tuple(missing),
            )
        )
    scored.sort(key=lambda neighbor: (neighbor.distance, neighbor.decision_id, neighbor.subject_id))
    selected = tuple(scored[:limit])
    return AnalogArtifact(
        query_id=query.decision_id,
        query_cutoff=query_cutoff,
        distance_spec=distance_spec,
        status="neighbors" if selected else "none_analogous",
        neighbors=selected,
    )


def run_plain_filter(
    query: DecisionRecord,
    candidates: list[DecisionRecord] | tuple[DecisionRecord, ...],
    filter_spec: FilterSpec,
) -> PlainFilterArtifact:
    """Run the named outcome-blind exact-filter baseline."""

    query.validate()
    cutoff = _aware(query.decision_cutoff, "query_cutoff")
    filter_spec.validate(cutoff)
    _validate_unique_records(candidates)
    if any(candidate.decision_id == query.decision_id for candidate in candidates):
        raise ManifestError("query decision identity is also a candidate")
    if any(candidate.subject_id == query.subject_id for candidate in candidates):
        raise ManifestError("query subject identity is also a candidate")
    selected: list[str] = []
    for candidate in candidates:
        candidate.validate()
        if _aware(candidate.decision_cutoff, "candidate.decision_cutoff") >= cutoff:
            raise TemporalLeakageError("plain-filter candidate is not strictly earlier")
        if all(
            candidate.filters.get(name) is not None
            and _canonical_value(candidate.filters[name].value) == _canonical_value(value.value)
            and candidate.filters[name].ontology_version == value.ontology_version
            and candidate.filters[name].ontology_digest == value.ontology_digest
            and candidate.filters[name].identity_version == value.identity_version
            and candidate.filters[name].identity_digest == value.identity_digest
            for name, value in filter_spec.fields.items()
        ):
            selected.append(candidate.decision_id)
    return PlainFilterArtifact(query.decision_id, cutoff, filter_spec, tuple(sorted(selected)))


def reveal_outcomes(
    artifact: AnalogArtifact,
    outcomes: Mapping[str, OutcomeClosure],
    *,
    reveal_id: str,
    revealed_at: datetime,
) -> RetrospectiveReveal:
    """Create a separate retrospective artifact without mutating decision-mode analogs."""

    reveal_time = _aware(revealed_at, "revealed_at")
    if not reveal_id.strip():
        raise ManifestError("reveal_id is required")
    if reveal_time <= _aware(artifact.query_cutoff, "query_cutoff"):
        raise TemporalLeakageError("retrospective reveal must occur after the decision cutoff")
    neighbor_ids = {neighbor.decision_id for neighbor in artifact.neighbors}
    outcome_ids = set(outcomes)
    if outcome_ids != neighbor_ids:
        raise ManifestError(
            "retrospective outcome coverage must exactly match neighbors; "
            f"missing={sorted(neighbor_ids - outcome_ids)}, "
            f"extra={sorted(outcome_ids - neighbor_ids)}"
        )
    selected = []
    for neighbor in artifact.neighbors:
        closure = outcomes[neighbor.decision_id]
        closure.as_dict()
        closure.as_dict()
        known_at = _aware(closure.known_at, "outcome.known_at")
        maturity_at = _aware(closure.maturity_at, "outcome.maturity_at")
        if known_at <= _aware(artifact.query_cutoff, "query_cutoff"):
            raise TemporalLeakageError("retrospective outcome was known at the decision")
        if known_at > maturity_at:
            raise ManifestError("outcome known time must not follow maturity")
        if known_at > reveal_time:
            raise TemporalLeakageError("retrospective reveal precedes outcome knowledge")
        if maturity_at > reveal_time:
            raise TemporalLeakageError("retrospective reveal precedes outcome maturity")
        selected.append((neighbor.decision_id, closure))
    return RetrospectiveReveal(reveal_id, artifact.digest, tuple(selected), reveal_time)
