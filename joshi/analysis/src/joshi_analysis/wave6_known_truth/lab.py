"""Exact fixture generators and candidate checks for the Wave 6 `N01/W6-K` gate.

This module neither fits a model nor admits evidence. It generates a bounded suite whose truth is
known by construction, derives the expected disposition from that frozen fixture, and checks one
candidate result per adversary. All outputs remain fixture-only and carry no market, causal,
operational, product, or economic authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from ..canonical import canonical_json_bytes, iso_utc, qualified_sha256_bytes
from ..errors import ManifestError

SCHEMA_ID = "joshi.analysis.wave6-known-truth/v1"
AUTHORITY = "fixture_only_no_market_causal_policy_or_economic_claim"
ESTIMATOR_FAMILY = "exact_signed_flow_fixture_probe_v1"


class AdversaryKind(StrEnum):
    IDENTIFIABLE_RECOVERY = "identifiable_recovery"
    NONIDENTIFIABILITY = "nonidentifiability"
    SHORTCUT_TRAP = "shortcut_trap"
    FUTURE_LEAKAGE = "future_leakage"
    COVERAGE_BIRTH_DEATH = "coverage_birth_death"
    TOPOLOGY_CHANGE = "topology_change"
    UNIT_GAUGE_WIDE_ATOM = "unit_gauge_wide_atom"
    REFLEXIVE_POLICY_CHANGE = "reflexive_policy_change"


class CandidateDisposition(StrEnum):
    EXACT_RECOVERY = "exact_recovery"
    IDENTIFIED_SET = "identified_set"
    REFUSED = "refused"


class CoverageState(StrEnum):
    OBSERVED = "observed"
    GAP = "gap"
    UNKNOWN = "unknown"


def _stable(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ManifestError(f"{field} must be a bounded, unpadded stable string")
    return value


def _aware(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ManifestError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _strict_int(value: Any, field: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or (positive and value <= 0):
        suffix = " positive" if positive else ""
        raise ManifestError(f"{field} must be an exact{suffix} integer")
    return value


def _sorted_unique(values: tuple[str, ...], field: str, *, nonempty: bool = False) -> None:
    if tuple(sorted(set(values))) != values or (nonempty and not values):
        raise ManifestError(f"{field} must be sorted, unique, and canonically ordered")
    for value in values:
        _stable(value, field)


def _digest(material: Any) -> str:
    return qualified_sha256_bytes(canonical_json_bytes(material))


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    """Raw fixture evidence.

    Only identity and availability/commit coordinates are universally validated. Semantic payload
    is validated after the knowledge gate so a malformed future row cannot poison an earlier cut.
    """

    evidence_id: str
    available_at: datetime
    commit_seq: int
    valid_from: datetime | str
    valid_through: datetime | str
    topology_epoch: str | None
    policy_epoch: str | None
    unit: str | None
    orientation: int | str | None
    exact_atoms: int | str | None
    coverage_state: CoverageState | str | None
    gap_id: str | None
    compatible_world_id: str | None = "observed"

    def __post_init__(self) -> None:
        _stable(self.evidence_id, "evidence_id")
        object.__setattr__(self, "available_at", _aware(self.available_at, "available_at"))
        _strict_int(self.commit_seq, "commit_seq")

    def material(self) -> dict[str, Any]:
        def time_or_raw(value: datetime | str) -> str:
            return iso_utc(value) if isinstance(value, datetime) else value

        return {
            "evidence_id": self.evidence_id,
            "available_at": iso_utc(self.available_at),
            "commit_seq": str(self.commit_seq),
            "valid_from": time_or_raw(self.valid_from),
            "valid_through": time_or_raw(self.valid_through),
            "topology_epoch": self.topology_epoch,
            "policy_epoch": self.policy_epoch,
            "unit": self.unit,
            "orientation": self.orientation,
            "exact_atoms": self.exact_atoms,
            "coverage_state": (
                self.coverage_state.value
                if isinstance(self.coverage_state, CoverageState)
                else self.coverage_state
            ),
            "gap_id": self.gap_id,
            "compatible_world_id": self.compatible_world_id,
        }


@dataclass(frozen=True, slots=True)
class ProbeCut:
    state_time: datetime
    knowledge_cutoff: datetime
    as_of_commit_seq: int
    topology_epoch: str
    policy_epoch: str
    unit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_time", _aware(self.state_time, "state_time"))
        object.__setattr__(
            self, "knowledge_cutoff", _aware(self.knowledge_cutoff, "knowledge_cutoff")
        )
        _strict_int(self.as_of_commit_seq, "as_of_commit_seq")
        for field in ("topology_epoch", "policy_epoch", "unit"):
            _stable(getattr(self, field), field)

    def material(self) -> dict[str, Any]:
        return {
            "state_time": iso_utc(self.state_time),
            "knowledge_cutoff": iso_utc(self.knowledge_cutoff),
            "as_of_commit_seq": str(self.as_of_commit_seq),
            "topology_epoch": self.topology_epoch,
            "policy_epoch": self.policy_epoch,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class KnownTruthCase:
    case_id: str
    adversary: AdversaryKind
    cut: ProbeCut
    evidence: tuple[EvidenceRow, ...]
    negative_control_id: str
    falsifier: str

    def __post_init__(self) -> None:
        _stable(self.case_id, "case_id")
        _stable(self.negative_control_id, "negative_control_id")
        _stable(self.falsifier, "falsifier")
        if not self.evidence:
            raise ManifestError("known-truth case needs evidence")
        ids = tuple(row.evidence_id for row in self.evidence)
        _sorted_unique(ids, "evidence ids", nonempty=True)

    @property
    def fixture_manifest_digest(self) -> str:
        return _digest(
            {
                "schema_id": SCHEMA_ID,
                "case_id": self.case_id,
                "adversary": self.adversary.value,
                "cut": self.cut.material(),
                "evidence": [row.material() for row in self.evidence],
                "negative_control_id": self.negative_control_id,
                "falsifier": self.falsifier,
                "authority": AUTHORITY,
            }
        )

    @property
    def input_manifest_digest(self) -> str:
        """Hash only evidence available by this cut; future rows are not artifact inputs."""

        eligible = [
            row.material()
            for row in self.evidence
            if row.available_at <= self.cut.knowledge_cutoff
            and row.commit_seq <= self.cut.as_of_commit_seq
        ]
        return _digest(
            {
                "schema_id": SCHEMA_ID,
                "case_id": self.case_id,
                "cut": self.cut.material(),
                "eligible_evidence": eligible,
                "authority": AUTHORITY,
            }
        )


@dataclass(frozen=True, slots=True)
class TruthExpectation:
    disposition: CandidateDisposition
    exact_atoms: int | None
    compatible_atoms: tuple[int, ...]
    refusal_reasons: tuple[str, ...]
    used_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateResult:
    case_id: str
    input_manifest_digest: str
    disposition: CandidateDisposition
    exact_atoms: int | None
    compatible_atoms: tuple[int, ...]
    refusal_reasons: tuple[str, ...]
    used_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    cut: ProbeCut
    authority: str
    result_digest: str

    @classmethod
    def build(
        cls,
        case: KnownTruthCase,
        expectation: TruthExpectation,
        *,
        exact_atoms: int | object | None = ...,
        compatible_atoms: tuple[int, ...] | object = ...,
        refusal_reasons: tuple[str, ...] | object = ...,
        used_evidence_ids: tuple[str, ...] | object = ...,
        excluded_evidence_ids: tuple[str, ...] | object = ...,
    ) -> CandidateResult:
        values = {
            "exact_atoms": expectation.exact_atoms if exact_atoms is ... else exact_atoms,
            "compatible_atoms": (
                expectation.compatible_atoms if compatible_atoms is ... else compatible_atoms
            ),
            "refusal_reasons": (
                expectation.refusal_reasons if refusal_reasons is ... else refusal_reasons
            ),
            "used_evidence_ids": (
                expectation.used_evidence_ids if used_evidence_ids is ... else used_evidence_ids
            ),
            "excluded_evidence_ids": (
                expectation.excluded_evidence_ids
                if excluded_evidence_ids is ...
                else excluded_evidence_ids
            ),
        }
        material = _result_material(
            case_id=case.case_id,
            input_manifest_digest=case.input_manifest_digest,
            disposition=expectation.disposition,
            exact_atoms=values["exact_atoms"],
            compatible_atoms=values["compatible_atoms"],
            refusal_reasons=values["refusal_reasons"],
            used_evidence_ids=values["used_evidence_ids"],
            excluded_evidence_ids=values["excluded_evidence_ids"],
            cut=case.cut,
            authority=AUTHORITY,
        )
        return cls(
            case_id=case.case_id,
            input_manifest_digest=case.input_manifest_digest,
            disposition=expectation.disposition,
            exact_atoms=values["exact_atoms"],
            compatible_atoms=values["compatible_atoms"],
            refusal_reasons=values["refusal_reasons"],
            used_evidence_ids=values["used_evidence_ids"],
            excluded_evidence_ids=values["excluded_evidence_ids"],
            cut=case.cut,
            authority=AUTHORITY,
            result_digest=_digest(material),
        )


@dataclass(frozen=True, slots=True)
class KnownTruthEvaluation:
    suite_id: str
    suite_digest: str
    candidate_id: str
    passed_case_ids: tuple[str, ...]
    result_digests: tuple[str, ...]
    evaluation_digest: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.suite_id, "evaluation suite_id")
        _stable(self.candidate_id, "evaluation candidate_id")
        _sorted_unique(self.passed_case_ids, "evaluation passed case IDs", nonempty=True)
        if len(self.result_digests) != len(self.passed_case_ids):
            raise ManifestError("evaluation must bind one result digest per passed case")
        _qualified_digest(self.suite_digest, "evaluation suite digest")
        for digest in self.result_digests:
            _qualified_digest(digest, "evaluation result digest")
        if self.authority != AUTHORITY:
            raise ManifestError("evaluation widened its fixture-only authority")
        _qualified_digest(self.evaluation_digest, "evaluation digest")
        if self.evaluation_digest != _digest(_evaluation_material(self)):
            raise ManifestError("evaluation self-digest mismatch")

    def as_dict(self) -> dict[str, Any]:
        """Return the exact registered evaluation artifact fields."""

        return {
            "suite_id": self.suite_id,
            "suite_digest": self.suite_digest,
            "candidate_id": self.candidate_id,
            "passed_case_ids": list(self.passed_case_ids),
            "result_digests": list(self.result_digests),
            "evaluation_digest": self.evaluation_digest,
            "authority": self.authority,
        }

    def exact_bytes(self) -> bytes:
        """Serialize the exact canonical checked-artifact representation."""

        return canonical_json_bytes(self.as_dict(), newline=True)


def _qualified_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ManifestError(f"{field} must be sha256:<64 lowercase hex>")
    return value


def _evaluation_material(evaluation: KnownTruthEvaluation) -> dict[str, Any]:
    return {
        "schema_id": SCHEMA_ID,
        "suite_id": evaluation.suite_id,
        "suite_digest": evaluation.suite_digest,
        "candidate_id": evaluation.candidate_id,
        "passed_case_ids": list(evaluation.passed_case_ids),
        "result_digests": list(evaluation.result_digests),
        "authority": evaluation.authority,
    }


@dataclass(frozen=True, slots=True)
class KnownTruthSuite:
    suite_id: str
    cases: tuple[KnownTruthCase, ...]

    def __post_init__(self) -> None:
        _stable(self.suite_id, "suite_id")
        ids = tuple(case.case_id for case in self.cases)
        _sorted_unique(ids, "case ids", nonempty=True)
        if {case.adversary for case in self.cases} != set(AdversaryKind) or len(self.cases) != len(
            AdversaryKind
        ):
            raise ManifestError(
                "known-truth suite must contain each required adversary exactly once"
            )

    @property
    def suite_digest(self) -> str:
        return _digest(
            {
                "schema_id": SCHEMA_ID,
                "suite_id": self.suite_id,
                "estimator_family": ESTIMATOR_FAMILY,
                "case_fixture_manifests": [case.fixture_manifest_digest for case in self.cases],
                "authority": AUTHORITY,
            }
        )


def _result_material(
    *,
    case_id: str,
    input_manifest_digest: str,
    disposition: CandidateDisposition,
    exact_atoms: object,
    compatible_atoms: object,
    refusal_reasons: object,
    used_evidence_ids: object,
    excluded_evidence_ids: object,
    cut: ProbeCut,
    authority: str,
) -> dict[str, Any]:
    return {
        "schema_id": SCHEMA_ID,
        "case_id": case_id,
        "input_manifest_digest": input_manifest_digest,
        "disposition": disposition.value,
        "exact_atoms": exact_atoms,
        "compatible_atoms": list(compatible_atoms),
        "refusal_reasons": list(refusal_reasons),
        "used_evidence_ids": list(used_evidence_ids),
        "excluded_evidence_ids": list(excluded_evidence_ids),
        "cut": cut.material(),
        "authority": authority,
    }


def derive_truth(case: KnownTruthCase) -> TruthExpectation:
    """Derive fixture truth after gating availability and commit before semantic payload."""

    known: list[EvidenceRow] = []
    excluded: list[str] = []
    for row in case.evidence:
        if (
            row.available_at > case.cut.knowledge_cutoff
            or row.commit_seq > case.cut.as_of_commit_seq
        ):
            # The row is not yet in the artifact's information universe. It cannot change output
            # identity or appear as an exclusion in the earlier result.
            continue
        else:
            known.append(row)

    selected: list[EvidenceRow] = []
    refusal_reasons: set[str] = set()
    for row in known:
        valid_from = _aware(row.valid_from, "selected valid_from")
        valid_through = _aware(row.valid_through, "selected valid_through")
        if valid_through <= valid_from:
            raise ManifestError("selected validity interval is empty or reversed")
        if not (valid_from <= case.cut.state_time < valid_through):
            excluded.append(row.evidence_id)
            continue
        if row.topology_epoch != case.cut.topology_epoch:
            excluded.append(row.evidence_id)
            continue
        if row.policy_epoch != case.cut.policy_epoch:
            excluded.append(row.evidence_id)
            continue
        selected.append(row)
        if row.coverage_state in {CoverageState.GAP, CoverageState.UNKNOWN}:
            if not row.gap_id:
                raise ManifestError("selected gap/unknown evidence requires gap_id")
            refusal_reasons.add(f"coverage_{row.coverage_state.value}:{row.gap_id}")
        elif row.coverage_state != CoverageState.OBSERVED:
            raise ManifestError("selected evidence has invalid coverage state")
        elif row.gap_id is not None:
            raise ManifestError("selected observed evidence cannot carry gap_id")
        if row.unit != case.cut.unit:
            refusal_reasons.add("unit_mismatch")

    used_ids = tuple(sorted(row.evidence_id for row in selected))
    excluded_ids = tuple(sorted(excluded))
    if refusal_reasons:
        return TruthExpectation(
            CandidateDisposition.REFUSED,
            None,
            (),
            tuple(sorted(refusal_reasons)),
            used_ids,
            excluded_ids,
        )
    if not selected:
        return TruthExpectation(
            CandidateDisposition.REFUSED,
            None,
            (),
            ("empty_selected_evidence",),
            (),
            excluded_ids,
        )

    sums: dict[str, int] = {}
    for row in selected:
        world = _stable(row.compatible_world_id, "compatible_world_id")
        orientation = _strict_int(row.orientation, "orientation")
        if orientation not in {-1, 1}:
            raise ManifestError("orientation must be exactly -1 or 1")
        exact_atoms = _strict_int(row.exact_atoms, "exact_atoms")
        sums[world] = sums.get(world, 0) + orientation * exact_atoms
    values = tuple(sorted(set(sums.values())))
    if len(values) > 1:
        return TruthExpectation(
            CandidateDisposition.IDENTIFIED_SET,
            None,
            values,
            (),
            used_ids,
            excluded_ids,
        )
    return TruthExpectation(
        CandidateDisposition.EXACT_RECOVERY,
        values[0],
        (),
        (),
        used_ids,
        excluded_ids,
    )


def validate_candidate_result(case: KnownTruthCase, result: CandidateResult) -> None:
    """Fail closed unless the candidate exactly matches the derived fixture truth."""

    expected = derive_truth(case)
    if result.case_id != case.case_id or result.input_manifest_digest != case.input_manifest_digest:
        raise ManifestError("candidate result does not bind the exact known-truth case")
    if result.cut != case.cut or result.authority != AUTHORITY:
        raise ManifestError("candidate result changed its cut or authority")
    _sorted_unique(
        result.used_evidence_ids, "used evidence ids", nonempty=bool(expected.used_evidence_ids)
    )
    _sorted_unique(result.excluded_evidence_ids, "excluded evidence ids")
    _sorted_unique(result.refusal_reasons, "refusal reasons")
    if tuple(sorted(set(result.compatible_atoms))) != result.compatible_atoms:
        raise ManifestError("compatible atoms must be an exact sorted set")
    if result.exact_atoms is not None:
        _strict_int(result.exact_atoms, "candidate exact_atoms")
    for value in result.compatible_atoms:
        _strict_int(value, "candidate compatible_atoms")
    if (
        result.disposition != expected.disposition
        or result.exact_atoms != expected.exact_atoms
        or result.compatible_atoms != expected.compatible_atoms
        or result.refusal_reasons != expected.refusal_reasons
        or result.used_evidence_ids != expected.used_evidence_ids
        or result.excluded_evidence_ids != expected.excluded_evidence_ids
    ):
        raise ManifestError("candidate result differs from exact generated truth")
    material = _result_material(
        case_id=result.case_id,
        input_manifest_digest=result.input_manifest_digest,
        disposition=result.disposition,
        exact_atoms=result.exact_atoms,
        compatible_atoms=result.compatible_atoms,
        refusal_reasons=result.refusal_reasons,
        used_evidence_ids=result.used_evidence_ids,
        excluded_evidence_ids=result.excluded_evidence_ids,
        cut=result.cut,
        authority=result.authority,
    )
    if result.result_digest != _digest(material):
        raise ManifestError("candidate result digest mismatch")


def evaluate_candidate_suite(
    suite: KnownTruthSuite, candidate_id: str, results: tuple[CandidateResult, ...]
) -> KnownTruthEvaluation:
    """Require exactly one passing result for every required adversary."""

    _stable(candidate_id, "candidate_id")
    by_id = {result.case_id: result for result in results}
    if len(by_id) != len(results) or set(by_id) != {case.case_id for case in suite.cases}:
        raise ManifestError("candidate must report every suite case exactly once")
    for case in suite.cases:
        validate_candidate_result(case, by_id[case.case_id])
    passed = tuple(case.case_id for case in suite.cases)
    result_digests = tuple(by_id[case_id].result_digest for case_id in passed)
    provisional = KnownTruthEvaluation.__new__(KnownTruthEvaluation)
    for field, value in (
        ("suite_id", suite.suite_id),
        ("suite_digest", suite.suite_digest),
        ("candidate_id", candidate_id),
        ("passed_case_ids", passed),
        ("result_digests", result_digests),
        ("authority", AUTHORITY),
    ):
        object.__setattr__(provisional, field, value)
    object.__setattr__(provisional, "evaluation_digest", "sha256:" + "0" * 64)
    evaluation_digest = _digest(_evaluation_material(provisional))
    return KnownTruthEvaluation(
        suite.suite_id,
        suite.suite_digest,
        candidate_id,
        passed,
        result_digests,
        evaluation_digest,
    )


def build_signed_flow_known_truth_suite() -> KnownTruthSuite:
    """Build all eight required shared adversaries for one exact signed-flow probe."""

    t0 = datetime(2026, 8, 18, tzinfo=UTC)
    cut = ProbeCut(
        t0 + timedelta(minutes=5),
        t0 + timedelta(minutes=10),
        10,
        "topology:v1",
        "policy:baseline",
        "base_asset_atoms",
    )

    def row(
        evidence_id: str,
        atoms: int | str | None,
        *,
        orientation: int | str | None = 1,
        available_at: datetime = t0,
        commit_seq: int = 1,
        topology: str | None = "topology:v1",
        policy: str | None = "policy:baseline",
        unit: str | None = "base_asset_atoms",
        coverage: CoverageState | str | None = CoverageState.OBSERVED,
        gap_id: str | None = None,
        world: str | None = "observed",
        valid_from: datetime | str = t0,
        valid_through: datetime | str = t0 + timedelta(hours=1),
    ) -> EvidenceRow:
        return EvidenceRow(
            evidence_id,
            available_at,
            commit_seq,
            valid_from,
            valid_through,
            topology,
            policy,
            unit,
            orientation,
            atoms,
            coverage,
            gap_id,
            world,
        )

    cases = (
        KnownTruthCase(
            "case-01-identifiable",
            AdversaryKind.IDENTIFIABLE_RECOVERY,
            cut,
            (row("ev-01-a", 13), row("ev-01-b", 5, orientation=-1)),
            "negative-permutation",
            "exact signed sum is not recovered",
        ),
        KnownTruthCase(
            "case-02-nonidentifiable",
            AdversaryKind.NONIDENTIFIABILITY,
            cut,
            (row("ev-02-world-a", 5, world="world:a"), row("ev-02-world-b", 11, world="world:b")),
            "negative-force-point",
            "candidate emits one point instead of the compatible set",
        ),
        KnownTruthCase(
            "case-03-shortcut",
            AdversaryKind.SHORTCUT_TRAP,
            cut,
            (row("ev-03-a", 7, orientation=-1),),
            "negative-sign-shortcut",
            "candidate follows the positive shortcut instead of exact orientation",
        ),
        KnownTruthCase(
            "case-04-future",
            AdversaryKind.FUTURE_LEAKAGE,
            cut,
            (
                row(
                    "ev-04-future-malformed",
                    "not-an-integer",
                    orientation="bad",
                    available_at=t0 + timedelta(minutes=20),
                    commit_seq=20,
                    valid_from="malformed-future-validity",
                    valid_through="malformed-future-validity",
                ),
                row("ev-04-known", 3),
            ),
            "negative-future-shift",
            "future or malformed future evidence changes the earlier result",
        ),
        KnownTruthCase(
            "case-05-coverage",
            AdversaryKind.COVERAGE_BIRTH_DEATH,
            cut,
            (
                row(
                    "ev-05-gap",
                    None,
                    orientation=None,
                    coverage=CoverageState.GAP,
                    gap_id="gap:hot-scope-death",
                ),
            ),
            "negative-gap-as-zero",
            "coverage death is converted to zero or empty success",
        ),
        KnownTruthCase(
            "case-06-topology",
            AdversaryKind.TOPOLOGY_CHANGE,
            cut,
            (row("ev-06-current", 4), row("ev-06-other-topology", 9, topology="topology:v2")),
            "negative-cross-topology-sum",
            "candidate smooths across topology epochs",
        ),
        KnownTruthCase(
            "case-07-wide-gauge",
            AdversaryKind.UNIT_GAUGE_WIDE_ATOM,
            cut,
            (row("ev-07-a", 2**53 + 1), row("ev-07-b", 2**53 + 3)),
            "negative-float-narrowing",
            "wide atoms narrow or orientation/unit meaning changes",
        ),
        KnownTruthCase(
            "case-08-reflexive",
            AdversaryKind.REFLEXIVE_POLICY_CHANGE,
            cut,
            (
                row("ev-08-baseline", 2),
                row("ev-08-policy-induced", 20, policy="policy:experimental"),
            ),
            "negative-policy-pooling",
            "policy-induced evidence is pooled into its own baseline",
        ),
    )
    return KnownTruthSuite("wave6-known-truth-signed-flow-v1", cases)
