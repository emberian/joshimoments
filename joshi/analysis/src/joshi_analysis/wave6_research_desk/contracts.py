"""Pure, bounded contracts for the Wave 6 machine research desk.

This module deliberately contains descriptions, not data access or query interfaces.  A desk
proposal can be reviewed by a human, but it cannot be executed, promoted, or turned into a Glass
action by this package.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes, require_qualified_sha256
from ..errors import CoverageError, ManifestError, TemporalLeakageError

SCHEMA_ID = "joshi.analysis.wave6-research-desk/v1"
AUTHORITY = "read_only_proposal_only_no_query_no_glass_no_action_no_claim_promotion"
CLAIM_SCOPE = "research_design_proposal_not_result_or_live_decision"
MAX_PPM = 1_000_000


class ArtifactRole(StrEnum):
    DESIGN = "design"
    OUTCOME = "outcome"


class CoverageStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    GAP = "gap"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


class ProposalKind(StrEnum):
    ESTIMAND = "estimand"
    CONTROL_SET = "control_set"
    FEATURE_DECOMPOSITION = "feature_decomposition"
    COUNTEREXAMPLE = "counterexample"
    FALSIFIER = "falsifier"
    EXPERIMENT_MANIFEST = "experiment_manifest"


class DispositionKind(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    HOLD = "hold"
    SUPERSEDE = "supersede"


def _stable(value: str, field: str, *, limit: int = 200) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ManifestError(f"{field} must be a bounded, unpadded stable string")
    return value


def _text(value: str, field: str, *, limit: int = 2_000) -> str:
    return _stable(value, field, limit=limit)


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ManifestError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime, field: str) -> str:
    return _aware(value, field).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _positive(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{field} must be a positive integer")
    return value


def _ppm(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_PPM:
        raise CoverageError(f"{field} must be an integer in [0, 1000000]")
    return value


def _sorted_unique(values: tuple[str, ...], field: str, *, nonempty: bool = False) -> None:
    for value in values:
        _stable(value, field)
    if tuple(sorted(set(values))) != values:
        raise ManifestError(f"{field} must be sorted and duplicate-free")
    if nonempty and not values:
        raise ManifestError(f"{field} must not be empty")


def _id(prefix: str, content: Mapping[str, Any]) -> str:
    return f"{prefix}-{qualified_sha256_bytes(canonical_json_bytes(content))[7:39]}"


def evidence_closure_digest(descriptors: tuple[ArtifactDescriptor, ...]) -> str:
    """Hash the complete retained evidence descriptor closure in caller-declared stable order."""

    return qualified_sha256_bytes(
        canonical_json_bytes(
            {
                "schema_id": SCHEMA_ID,
                "artifact_descriptors": [item.as_dict() for item in descriptors],
            }
        )
    )


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """A pre-admitted, point-in-time descriptor; never a data handle or query recipe."""

    artifact_id: str
    role: ArtifactRole
    as_of: datetime
    available_at: datetime
    commit_seq: int
    provenance_digest: str
    coverage_status: CoverageStatus
    coverage_ppm: int
    gap_ids: tuple[str, ...]
    unit: str
    topology_id: str
    topology_version_id: str

    def validate(self) -> None:
        _stable(self.artifact_id, "artifact_id")
        if not isinstance(self.role, ArtifactRole):
            raise ManifestError("artifact.role must be an admitted role")
        if not isinstance(self.coverage_status, CoverageStatus):
            raise ManifestError("artifact.coverage_status must be an admitted coverage state")
        if _aware(self.as_of, "artifact.as_of") > _aware(
            self.available_at, "artifact.available_at"
        ):
            raise TemporalLeakageError("artifact cannot be available before its as-of time")
        _positive(self.commit_seq, "artifact.commit_seq")
        require_qualified_sha256(self.provenance_digest, "artifact.provenance_digest")
        _ppm(self.coverage_ppm, "artifact.coverage_ppm")
        _sorted_unique(self.gap_ids, "artifact.gap_ids")
        _stable(self.unit, "artifact.unit")
        _stable(self.topology_id, "artifact.topology_id")
        _stable(self.topology_version_id, "artifact.topology_version_id")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "artifact_id": self.artifact_id,
            "role": self.role.value,
            "as_of": _iso(self.as_of, "artifact.as_of"),
            "available_at": _iso(self.available_at, "artifact.available_at"),
            "commit_seq": str(self.commit_seq),
            "provenance_digest": self.provenance_digest,
            "coverage_status": self.coverage_status.value,
            "coverage_ppm": self.coverage_ppm,
            "gap_ids": list(self.gap_ids),
            "unit": self.unit,
            "topology_id": self.topology_id,
            "topology_version_id": self.topology_version_id,
        }


@dataclass(frozen=True, slots=True)
class DeskPolicy:
    """The ceiling applies to every descriptor before a proposal is constructed."""

    policy_id: str
    information_cutoff: datetime
    minimum_coverage_ppm: int
    allowed_gap_ids: tuple[str, ...]
    required_unit: str
    required_topology_id: str
    required_topology_version_id: str
    max_artifacts: int
    max_experiments: int
    max_experiment_units: int
    max_total_experiment_units: int

    def validate(self) -> None:
        _stable(self.policy_id, "policy_id")
        _aware(self.information_cutoff, "policy.information_cutoff")
        _ppm(self.minimum_coverage_ppm, "policy.minimum_coverage_ppm")
        _sorted_unique(self.allowed_gap_ids, "policy.allowed_gap_ids")
        _stable(self.required_unit, "policy.required_unit")
        _stable(self.required_topology_id, "policy.required_topology_id")
        _stable(self.required_topology_version_id, "policy.required_topology_version_id")
        _positive(self.max_artifacts, "policy.max_artifacts")
        _positive(self.max_experiments, "policy.max_experiments")
        _positive(self.max_experiment_units, "policy.max_experiment_units")
        _positive(self.max_total_experiment_units, "policy.max_total_experiment_units")
        if self.max_experiment_units > self.max_total_experiment_units:
            raise ManifestError("per-experiment budget cannot exceed total experiment budget")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "policy_id": self.policy_id,
            "information_cutoff": _iso(self.information_cutoff, "policy.information_cutoff"),
            "minimum_coverage_ppm": self.minimum_coverage_ppm,
            "allowed_gap_ids": list(self.allowed_gap_ids),
            "required_unit": self.required_unit,
            "required_topology_id": self.required_topology_id,
            "required_topology_version_id": self.required_topology_version_id,
            "max_artifacts": self.max_artifacts,
            "max_experiments": self.max_experiments,
            "max_experiment_units": self.max_experiment_units,
            "max_total_experiment_units": self.max_total_experiment_units,
        }

    def content_digest(self) -> str:
        """Canonical identity for the exact policy version carried by a proposal."""

        return qualified_sha256_bytes(
            canonical_json_bytes({"schema_id": SCHEMA_ID, **self.as_dict()})
        )


@dataclass(frozen=True, slots=True)
class Estimand:
    estimand_id: str
    numerator: str
    denominator: str
    outcome_name: str
    unit: str

    def validate(self) -> None:
        _stable(self.estimand_id, "estimand_id")
        _text(self.numerator, "estimand.numerator")
        _text(self.denominator, "estimand.denominator")
        _stable(self.outcome_name, "estimand.outcome_name")
        _stable(self.unit, "estimand.unit")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "estimand_id": self.estimand_id,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "outcome_name": self.outcome_name,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class Control:
    control_id: str
    measurement: str
    rationale: str

    def validate(self) -> None:
        _stable(self.control_id, "control_id")
        _text(self.measurement, "control.measurement")
        _text(self.rationale, "control.rationale")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "control_id": self.control_id,
            "measurement": self.measurement,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class Feature:
    feature_id: str
    definition: str
    unit: str

    def validate(self) -> None:
        _stable(self.feature_id, "feature_id")
        _text(self.definition, "feature.definition")
        _stable(self.unit, "feature.unit")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {"feature_id": self.feature_id, "definition": self.definition, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class Falsifier:
    falsifier_id: str
    condition: str
    failure_interpretation: str

    def validate(self) -> None:
        _stable(self.falsifier_id, "falsifier_id")
        _text(self.condition, "falsifier.condition")
        _text(self.failure_interpretation, "falsifier.failure_interpretation")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "falsifier_id": self.falsifier_id,
            "condition": self.condition,
            "failure_interpretation": self.failure_interpretation,
        }


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    """A capped declarative experiment only; no SQL, endpoint, action, or execution method."""

    experiment_id: str
    purpose: str
    artifact_ids: tuple[str, ...]
    resource_units: int
    executable: bool = False
    query_count: int = 0

    def validate(self) -> None:
        _stable(self.experiment_id, "experiment_id")
        _text(self.purpose, "experiment.purpose")
        _sorted_unique(self.artifact_ids, "experiment.artifact_ids", nonempty=True)
        _positive(self.resource_units, "experiment.resource_units")
        if (
            not isinstance(self.executable, bool)
            or isinstance(self.query_count, bool)
            or not isinstance(self.query_count, int)
            or self.executable
            or self.query_count != 0
        ):
            raise ManifestError(
                "research desk experiment manifests cannot execute or request queries"
            )

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "experiment_id": self.experiment_id,
            "purpose": self.purpose,
            "artifact_ids": list(self.artifact_ids),
            "resource_units": self.resource_units,
            "executable": False,
            "query_count": 0,
        }


@dataclass(frozen=True, slots=True)
class ProposalSpec:
    kind: ProposalKind
    title: str
    hypothesis: str
    artifact_ids: tuple[str, ...]
    estimand: Estimand
    controls: tuple[Control, ...]
    features: tuple[Feature, ...]
    counterexamples: tuple[str, ...]
    falsifiers: tuple[Falsifier, ...]
    experiments: tuple[ExperimentManifest, ...]

    def validate(self) -> None:
        if not isinstance(self.kind, ProposalKind):
            raise ManifestError("proposal.kind must be an admitted proposal kind")
        _text(self.title, "proposal.title")
        _text(self.hypothesis, "proposal.hypothesis")
        _sorted_unique(self.artifact_ids, "proposal.artifact_ids", nonempty=True)
        self.estimand.validate()
        if not self.controls:
            raise ManifestError("proposal requires at least one predeclared control")
        if tuple(control.control_id for control in self.controls) != tuple(
            sorted({control.control_id for control in self.controls})
        ):
            raise ManifestError("controls must be sorted and duplicate-free")
        for control in self.controls:
            control.validate()
        if tuple(feature.feature_id for feature in self.features) != tuple(
            sorted({feature.feature_id for feature in self.features})
        ):
            raise ManifestError("features must be sorted and duplicate-free")
        for feature in self.features:
            feature.validate()
        _sorted_unique(self.counterexamples, "proposal.counterexamples")
        if tuple(falsifier.falsifier_id for falsifier in self.falsifiers) != tuple(
            sorted({falsifier.falsifier_id for falsifier in self.falsifiers})
        ):
            raise ManifestError("falsifiers must be sorted and duplicate-free")
        for falsifier in self.falsifiers:
            falsifier.validate()
        if tuple(experiment.experiment_id for experiment in self.experiments) != tuple(
            sorted({experiment.experiment_id for experiment in self.experiments})
        ):
            raise ManifestError("experiments must be sorted and duplicate-free")
        for experiment in self.experiments:
            experiment.validate()

    def commitment_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "kind": self.kind.value,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "artifact_ids": list(self.artifact_ids),
            "estimand": self.estimand.as_dict(),
            "controls": [control.as_dict() for control in self.controls],
            "features": [feature.as_dict() for feature in self.features],
            "counterexamples": list(self.counterexamples),
            "falsifiers": [falsifier.as_dict() for falsifier in self.falsifiers],
            "experiments": [experiment.as_dict() for experiment in self.experiments],
        }


@dataclass(frozen=True, slots=True)
class ResearchProposal:
    proposal_id: str
    proposal_digest: str
    policy_id: str
    policy: DeskPolicy
    policy_digest: str
    evidence_closure_digest: str
    commitment_digest: str
    created_at: datetime
    hypothesis_locked_at: datetime
    specification: ProposalSpec
    artifact_descriptors: tuple[ArtifactDescriptor, ...]
    authority: str = AUTHORITY
    claim_scope: str = CLAIM_SCOPE

    def commitment_content(self) -> dict[str, Any]:
        """Everything a continuation must preserve, excluding only proposal creation time."""

        return {
            "schema_id": SCHEMA_ID,
            "policy": self.policy.as_dict(),
            "policy_digest": self.policy_digest,
            "hypothesis_locked_at": _iso(
                self.hypothesis_locked_at, "proposal.hypothesis_locked_at"
            ),
            "specification": self.specification.commitment_dict(),
            "artifact_descriptors": [item.as_dict() for item in self.artifact_descriptors],
            "evidence_closure_digest": self.evidence_closure_digest,
            "authority": AUTHORITY,
            "claim_scope": CLAIM_SCOPE,
        }

    def computed_commitment_digest(self) -> str:
        return qualified_sha256_bytes(canonical_json_bytes(self.commitment_content()))

    def content(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "created_at": _iso(self.created_at, "proposal.created_at"),
            "commitment_digest": self.commitment_digest,
            "commitment": self.commitment_content(),
        }

    def validate(self) -> None:
        _stable(self.proposal_id, "proposal_id")
        _stable(self.policy_id, "proposal.policy_id")
        self.policy.validate()
        if self.policy_id != self.policy.policy_id:
            raise ManifestError("proposal policy_id must match the embedded policy")
        require_qualified_sha256(self.policy_digest, "proposal.policy_digest")
        if self.policy_digest != self.policy.content_digest():
            raise ManifestError("proposal policy digest does not match embedded policy content")
        require_qualified_sha256(self.evidence_closure_digest, "proposal.evidence_closure_digest")
        if self.evidence_closure_digest != evidence_closure_digest(self.artifact_descriptors):
            raise ManifestError("proposal evidence closure digest does not match descriptor bytes")
        require_qualified_sha256(self.commitment_digest, "proposal.commitment_digest")
        if self.commitment_digest != self.computed_commitment_digest():
            raise ManifestError("proposal commitment digest does not match frozen content")
        if self.authority != AUTHORITY or self.claim_scope != CLAIM_SCOPE:
            raise ManifestError("proposal authority and claim scope are fixed by the research desk")
        if _aware(self.hypothesis_locked_at, "proposal.hypothesis_locked_at") > _aware(
            self.created_at, "proposal.created_at"
        ):
            raise TemporalLeakageError("hypothesis cannot be locked after proposal creation")
        if (
            tuple(item.artifact_id for item in self.artifact_descriptors)
            != self.specification.artifact_ids
        ):
            raise ManifestError("proposal descriptor identities must exactly match specification")
        for item in self.artifact_descriptors:
            item.validate()
        content = self.content()
        digest = qualified_sha256_bytes(canonical_json_bytes(content))
        if self.proposal_digest != digest or self.proposal_id != _id("research-proposal", content):
            raise ManifestError("proposal identity does not match immutable content")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "proposal_id": self.proposal_id,
            "proposal_digest": self.proposal_digest,
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "evidence_closure_digest": self.evidence_closure_digest,
            "commitment_digest": self.commitment_digest,
            "authority": AUTHORITY,
            "claim_scope": CLAIM_SCOPE,
            "policy": self.policy.as_dict(),
            "hypothesis_locked_at": _iso(
                self.hypothesis_locked_at, "proposal.hypothesis_locked_at"
            ),
            "specification": self.specification.commitment_dict(),
            "artifact_descriptors": [item.as_dict() for item in self.artifact_descriptors],
            **self.content(),
        }


@dataclass(frozen=True, slots=True)
class HumanDisposition:
    disposition_id: str
    proposal_id: str
    disposition: DispositionKind
    human_id: str
    decided_at: datetime
    reason: str

    def content(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "disposition": self.disposition.value,
            "human_id": self.human_id,
            "decided_at": _iso(self.decided_at, "disposition.decided_at"),
            "reason": self.reason,
        }

    def validate(self) -> None:
        _stable(self.proposal_id, "disposition.proposal_id")
        if not isinstance(self.disposition, DispositionKind):
            raise ManifestError("disposition must be an admitted human disposition")
        _stable(self.human_id, "disposition.human_id")
        _text(self.reason, "disposition.reason")
        _aware(self.decided_at, "disposition.decided_at")
        if self.disposition_id != _id("human-disposition", self.content()):
            raise ManifestError("human disposition identity does not match immutable content")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"disposition_id": self.disposition_id, **self.content()}


@dataclass(frozen=True, slots=True)
class ProposalRevision:
    """Append-only supersession metadata; it cannot edit a locked scientific commitment."""

    revision_id: str
    prior_proposal_id: str
    successor_proposal_id: str
    human_id: str
    revised_at: datetime
    reason: str

    def content(self) -> dict[str, Any]:
        return {
            "prior_proposal_id": self.prior_proposal_id,
            "successor_proposal_id": self.successor_proposal_id,
            "human_id": self.human_id,
            "revised_at": _iso(self.revised_at, "revision.revised_at"),
            "reason": self.reason,
        }

    def validate(self) -> None:
        _stable(self.prior_proposal_id, "revision.prior_proposal_id")
        _stable(self.successor_proposal_id, "revision.successor_proposal_id")
        _stable(self.human_id, "revision.human_id")
        _text(self.reason, "revision.reason")
        _aware(self.revised_at, "revision.revised_at")
        if self.prior_proposal_id == self.successor_proposal_id:
            raise ManifestError("a revision must supersede a distinct proposal")
        if self.revision_id != _id("proposal-revision", self.content()):
            raise ManifestError("revision identity does not match immutable content")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"revision_id": self.revision_id, **self.content()}
