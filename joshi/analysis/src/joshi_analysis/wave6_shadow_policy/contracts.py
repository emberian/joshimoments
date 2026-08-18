from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import gcd
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes, require_qualified_sha256
from ..errors import ManifestError, TemporalLeakageError

SCHEMA_ID = "joshi.analysis.shadow-policy-arena/v1"
CALCULATOR_VERSION = "joshi.shadow-policy-arena.v1"
AUTHORITY = "read_only_evidence_only_no_signing_or_submission"
ACCOUNTING_IDENTITY = (
    "net_pnl_when_defined_equals_terminal_wealth_minus_exact_starting_value;"
    "refused_starting_or_terminal_value_yields_no_scalar_pnl;"
    "diagnostics_and_opportunity_cost_are_non_posting"
)
MAX_ATOMS = 2**128 - 1


class PolicyFamily(StrEnum):
    ABSTAIN = "abstain"
    OBSERVE = "observe"
    CRACKLE_ENTRY = "crackle_entry"
    TAKE_SOME_RUNNER = "take_some_runner"
    FLAT_WATCH_REENTRY = "flat_watch_reentry"
    LP_ROUTED_LIQUIDITY_SHADOW = "lp_routed_liquidity_shadow"


class CueKind(StrEnum):
    NOMINATION = "nomination"
    CRACKLE_ENTRY = "crackle_entry"
    CRACKLE_EXIT = "crackle_exit"
    TAKE_SOME = "take_some"
    FULL_EXIT = "full_exit"
    FLAT_WATCH = "flat_watch"
    REENTRY = "reentry"
    LP_INSTALL = "lp_install"
    LP_EXTERNAL_FLOW = "lp_external_flow"
    LP_SELF_FLOW = "lp_self_flow"
    LP_REBALANCE = "lp_rebalance"
    LP_REMOVE = "lp_remove"


class ActionKind(StrEnum):
    ABSTAIN = "abstain"
    OBSERVE = "observe"
    BUY = "buy"
    SELL_ALL = "sell_all"
    SELL_PARTIAL = "sell_partial"
    FLAT_WATCH_EXIT = "flat_watch_exit"
    REENTER = "reenter"
    LP_INSTALL = "lp_install"
    LP_ROUTE_EXTERNAL = "lp_route_external"
    LP_ROUTE_SELF = "lp_route_self"
    LP_REBALANCE = "lp_rebalance"
    LP_REMOVE = "lp_remove"
    TERMINAL_LIQUIDATE = "terminal_liquidate"
    REFUSE = "refuse"


class EvidenceStatus(StrEnum):
    OBSERVED = "observed"
    STALE = "stale"
    CONFLICTING = "conflicting"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


class EpistemicKind(StrEnum):
    OBSERVED_FACT = "observed_fact"
    DETERMINISTIC_CALCULATION = "deterministic_calculation"
    OPERATOR_PERCEPTION = "operator_perception"


class QuoteStatus(StrEnum):
    PROJECTED = "projected"
    REFUSED = "refused"


class QuoteRole(StrEnum):
    HYPOTHETICAL_EXECUTION = "hypothetical_execution"
    TERMINAL_LIQUIDATION = "terminal_liquidation"


class DiagnosticKind(StrEnum):
    EXTERNAL_LP_FEE = "external_lp_fee"
    SELF_ROUTED_OWNED_FEE = "self_routed_owned_fee"
    IRREVERSIBLE_COST = "irreversible_cost"
    LVR_GRID = "lvr_grid"
    ITR = "itr"


class AccountingTreatment(StrEnum):
    INCLUDED_IN_BALANCE_EFFECT = "included_in_balance_effect"
    INTERNAL_NON_POSTING = "internal_non_posting"
    COUNTERFACTUAL_NON_POSTING = "counterfactual_non_posting"


class AdverseSelectionMeasure(StrEnum):
    NONE = "none"
    LVR_GRID = "lvr_grid"
    ITR = "itr"


class BasisQuality(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class ValuationStatus(StrEnum):
    KNOWN = "known"
    REFUSED = "refused"


class ValuationSourceKind(StrEnum):
    NUMERAIRE_IDENTITY = "numeraire_identity"
    EXACT_SIZED_QUOTE = "exact_sized_quote"
    EXACT_SIZED_MARK = "exact_sized_mark"


class LiquidityEventKind(StrEnum):
    INSTALL = "install"
    EXTERNAL_FLOW = "external_flow"
    SELF_FLOW = "self_flow"
    REBALANCE = "rebalance"
    REMOVE = "remove"


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ManifestError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime, field: str) -> str:
    return _aware(value, field).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _stable(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ManifestError(f"{field} must be a bounded, unpadded stable string")
    return value


def _atoms(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_ATOMS:
        raise ManifestError(f"{field} must be an unsigned u128 atom count")
    return value


def _signed_atoms(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > MAX_ATOMS:
        raise ManifestError(f"{field} must be a signed-magnitude-compatible u128 atom delta")
    return value


def _positive_commit(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{field} must be a positive commit sequence")
    return value


def _sorted_unique(values: tuple[str, ...], field: str, *, nonempty: bool = False) -> None:
    for value in values:
        _stable(value, field)
    if tuple(sorted(set(values))) != values:
        raise ManifestError(f"{field} must be sorted and duplicate-free")
    if nonempty and not values:
        raise ManifestError(f"{field} must not be empty")


def _content_id(prefix: str, value: Mapping[str, Any]) -> str:
    digest = qualified_sha256_bytes(canonical_json_bytes(value)).removeprefix("sha256:")
    return f"{prefix}-{digest[:32]}"


@dataclass(frozen=True, slots=True)
class AssetAmount:
    asset_id: str
    atoms: int

    def validate(self) -> None:
        _stable(self.asset_id, "asset_id")
        _atoms(self.atoms, "atoms")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {"asset_id": self.asset_id, "atoms": str(self.atoms)}


@dataclass(frozen=True, slots=True)
class AssetDelta:
    asset_id: str
    atoms: int

    def validate(self) -> None:
        _stable(self.asset_id, "asset_id")
        _signed_atoms(self.atoms, "delta atoms")
        if self.atoms == 0:
            raise ManifestError("zero balance deltas are not evidence of an effect")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {"asset_id": self.asset_id, "atoms": str(self.atoms)}


def amount_map(amounts: tuple[AssetAmount, ...], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for amount in amounts:
        amount.validate()
        if amount.asset_id in result:
            raise ManifestError(f"{field} repeats asset {amount.asset_id}")
        result[amount.asset_id] = amount.atoms
    if tuple(result) != tuple(sorted(result)):
        raise ManifestError(f"{field} must be sorted by asset_id")
    return result


def delta_map(deltas: tuple[AssetDelta, ...], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for delta in deltas:
        delta.validate()
        if delta.asset_id in result:
            raise ManifestError(f"{field} repeats asset {delta.asset_id}")
        result[delta.asset_id] = delta.atoms
    if tuple(result) != tuple(sorted(result)):
        raise ManifestError(f"{field} must be sorted by asset_id")
    return result


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    snapshot_id: str
    as_of: datetime
    known_at: datetime
    commit_seq: int
    balances: tuple[AssetAmount, ...]
    evidence_ids: tuple[str, ...]
    evidence_digest: str

    def validate(self) -> None:
        _stable(self.snapshot_id, "snapshot_id")
        if _aware(self.as_of, "snapshot.as_of") > _aware(self.known_at, "snapshot.known_at"):
            raise TemporalLeakageError("snapshot cannot be known before its state is observed")
        _positive_commit(self.commit_seq, "snapshot.commit_seq")
        if not self.balances:
            raise ManifestError("snapshot must contain balances")
        amount_map(self.balances, "snapshot balances")
        _sorted_unique(self.evidence_ids, "snapshot evidence_ids", nonempty=True)
        require_qualified_sha256(self.evidence_digest, "snapshot.evidence_digest")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "snapshot_id": self.snapshot_id,
            "as_of": _iso(self.as_of, "snapshot.as_of"),
            "known_at": _iso(self.known_at, "snapshot.known_at"),
            "commit_seq": str(self.commit_seq),
            "balances": [amount.as_dict() for amount in self.balances],
            "evidence_ids": list(self.evidence_ids),
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class ExactValuationArtifact:
    source_kind: ValuationSourceKind
    source_artifact_id: str
    source_artifact_digest: str
    carrier_id: str
    unit_id: str
    unit_input: AssetAmount
    unit_output: AssetAmount
    sized_input: AssetAmount
    sized_output: AssetAmount
    available_at: datetime
    commit_seq: int

    def validate(self) -> None:
        if not isinstance(self.source_kind, ValuationSourceKind):
            raise ManifestError("valuation source kind is not recognized")
        _stable(self.source_artifact_id, "valuation source_artifact_id")
        require_qualified_sha256(
            self.source_artifact_digest, "valuation source_artifact_digest"
        )
        _stable(self.carrier_id, "valuation carrier_id")
        if self.unit_id != "asset_atoms_exact_integer":
            raise ManifestError("valuation source must use exact integer asset atoms")
        self.unit_input.validate()
        self.unit_output.validate()
        self.sized_input.validate()
        self.sized_output.validate()
        if self.unit_input.atoms == 0 or self.unit_output.atoms == 0:
            raise ManifestError("valuation unit amounts must be positive")
        if self.unit_input.asset_id != self.sized_input.asset_id:
            raise ManifestError("valuation unit and sized input assets differ")
        if self.unit_output.asset_id != self.sized_output.asset_id:
            raise ManifestError("valuation unit and sized output assets differ")
        scaled_output = self.sized_input.atoms * self.unit_output.atoms
        if scaled_output % self.unit_input.atoms:
            raise ManifestError("valuation sized output is not exact under its unit ratio")
        if scaled_output // self.unit_input.atoms != self.sized_output.atoms:
            raise ManifestError("valuation sized output does not recompute from its unit ratio")
        _aware(self.available_at, "valuation source available_at")
        _positive_commit(self.commit_seq, "valuation source commit_seq")
        if self.source_kind is ValuationSourceKind.NUMERAIRE_IDENTITY:
            if self.carrier_id != "intrinsic:numeraire-identity-v1":
                raise ManifestError("numeraire identity requires the intrinsic identity carrier")
            if (
                self.unit_input.asset_id != self.unit_output.asset_id
                or self.unit_input.atoms != self.unit_output.atoms
                or self.sized_input.asset_id != self.sized_output.asset_id
                or self.sized_input.atoms != self.sized_output.atoms
            ):
                raise ManifestError("numeraire identity artifact must be exact 1:1")

    def _canonical_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "source_kind": self.source_kind.value,
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_digest": self.source_artifact_digest,
            "carrier_id": self.carrier_id,
            "unit_id": self.unit_id,
            "unit_input": self.unit_input.as_dict(),
            "unit_output": self.unit_output.as_dict(),
            "sized_input": self.sized_input.as_dict(),
            "sized_output": self.sized_output.as_dict(),
            "available_at": _iso(self.available_at, "valuation source available_at"),
            "commit_seq": str(self.commit_seq),
        }

    @property
    def artifact_digest(self) -> str:
        return qualified_sha256_bytes(canonical_json_bytes(self._canonical_payload()))

    def as_dict(self) -> dict[str, Any]:
        return {**self._canonical_payload(), "artifact_digest": self.artifact_digest}


@dataclass(frozen=True, slots=True)
class ValuationComponent:
    asset_id: str
    holding_atoms: int
    numeraire_atoms: int | None
    evidence_ids: tuple[str, ...]
    evidence_digest: str
    valuation_method_id: str
    status: ValuationStatus
    refusal_reason: str | None = None
    source_artifact: ExactValuationArtifact | None = None

    def validate(self) -> None:
        _stable(self.asset_id, "valuation asset_id")
        _atoms(self.holding_atoms, "valuation holding_atoms")
        _sorted_unique(self.evidence_ids, "valuation evidence_ids", nonempty=True)
        require_qualified_sha256(self.evidence_digest, "valuation component evidence_digest")
        _stable(self.valuation_method_id, "valuation_method_id")
        if self.status is ValuationStatus.KNOWN:
            recognized_methods = {
                "numeraire_identity_1_to_1": ValuationSourceKind.NUMERAIRE_IDENTITY,
                "exact_sized_quote_v1": ValuationSourceKind.EXACT_SIZED_QUOTE,
                "exact_sized_mark_v1": ValuationSourceKind.EXACT_SIZED_MARK,
            }
            expected_source_kind = recognized_methods.get(self.valuation_method_id)
            if expected_source_kind is None:
                raise ManifestError(
                    "known valuation requires a recognized exact valuation method"
                )
            if self.source_artifact is None:
                raise ManifestError("known valuation requires an exact source artifact")
            self.source_artifact.validate()
            if self.source_artifact.source_kind is not expected_source_kind:
                raise ManifestError("valuation method and source artifact kind differ")
            if (
                self.source_artifact.sized_input.asset_id != self.asset_id
                or self.source_artifact.sized_input.atoms != self.holding_atoms
            ):
                raise ManifestError(
                    "valuation source sized input must equal the complete starting holding"
                )
            if self.numeraire_atoms is None:
                raise ManifestError("known valuation component needs exact numeraire atoms")
            _atoms(self.numeraire_atoms, "valuation numeraire_atoms")
            if self.holding_atoms == 0 and self.numeraire_atoms != 0:
                raise ManifestError("zero starting inventory must have zero starting value")
            if self.holding_atoms > 0 and self.numeraire_atoms == 0:
                raise ManifestError(
                    "positive starting inventory needs positive exact value or typed refusal"
                )
            if self.source_artifact.sized_output.atoms != self.numeraire_atoms:
                raise ManifestError(
                    "valuation amount must equal the recomputable source sized output"
                )
            if self.refusal_reason is not None:
                raise ManifestError("known valuation component cannot carry a refusal reason")
        else:
            if self.holding_atoms == 0:
                raise ManifestError("zero starting inventory is exactly valued, not refused")
            if self.numeraire_atoms is not None:
                raise ManifestError("refused valuation component cannot carry a numeric value")
            if not self.refusal_reason:
                raise ManifestError("refused valuation component needs a reason")
            _stable(self.refusal_reason, "valuation refusal_reason")
            if self.source_artifact is not None:
                raise ManifestError("refused valuation component cannot carry a source artifact")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "asset_id": self.asset_id,
            "holding_atoms": str(self.holding_atoms),
            "numeraire_atoms": (
                None if self.numeraire_atoms is None else str(self.numeraire_atoms)
            ),
            "evidence_ids": list(self.evidence_ids),
            "evidence_digest": self.evidence_digest,
            "valuation_method_id": self.valuation_method_id,
            "status": self.status.value,
            "refusal_reason": self.refusal_reason,
            "source_artifact": (
                None if self.source_artifact is None else self.source_artifact.as_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class StartingValuation:
    manifest_id: str
    numeraire_asset_id: str
    as_of: datetime
    known_at: datetime
    commit_seq: int
    evidence_ids: tuple[str, ...]
    evidence_digest: str
    components: tuple[ValuationComponent, ...]

    def validate(self, snapshot: PortfolioSnapshot) -> None:
        _stable(self.manifest_id, "starting valuation manifest_id")
        _stable(self.numeraire_asset_id, "starting valuation numeraire_asset_id")
        if _aware(self.as_of, "starting valuation as_of") > _aware(
            self.known_at, "starting valuation known_at"
        ):
            raise TemporalLeakageError("starting valuation cannot be known before its as-of state")
        _positive_commit(self.commit_seq, "starting valuation commit_seq")
        _sorted_unique(self.evidence_ids, "starting valuation evidence_ids", nonempty=True)
        require_qualified_sha256(self.evidence_digest, "starting valuation evidence_digest")
        if not self.components:
            raise ManifestError("starting valuation needs one component per snapshot asset")
        assets: dict[str, ValuationComponent] = {}
        for component in self.components:
            component.validate()
            if component.asset_id in assets:
                raise ManifestError("starting valuation repeats an asset")
            assets[component.asset_id] = component
            if not set(component.evidence_ids).issubset(self.evidence_ids):
                raise ManifestError(
                    "valuation component evidence must be in the valuation evidence closure"
                )
            if component.source_artifact is not None:
                source = component.source_artifact
                if source.source_artifact_id not in component.evidence_ids:
                    raise ManifestError(
                        "valuation component must bind its source artifact in evidence"
                    )
                if _aware(source.available_at, "valuation source available_at") > _aware(
                    self.known_at, "starting valuation known_at"
                ) or source.commit_seq >= self.commit_seq:
                    raise TemporalLeakageError(
                        "valuation source must precede its starting valuation decision"
                    )
        if tuple(assets) != tuple(sorted(assets)):
            raise ManifestError("starting valuation components must be sorted by asset_id")
        balances = amount_map(snapshot.balances, "snapshot balances")
        if set(assets) != set(balances):
            raise ManifestError("starting valuation must close every snapshot asset")
        for asset_id, atoms in balances.items():
            if assets[asset_id].holding_atoms != atoms:
                raise ManifestError("starting valuation holding does not match the snapshot")
            component = assets[asset_id]
            if (
                component.source_artifact is not None
                and component.source_artifact.sized_output.asset_id
                != self.numeraire_asset_id
            ):
                raise ManifestError("valuation source output must use the episode numeraire")
        numeraire = assets.get(self.numeraire_asset_id)
        if numeraire is None:
            raise ManifestError("starting valuation must contain its numeraire asset")
        if (
            numeraire.status is not ValuationStatus.KNOWN
            or numeraire.numeraire_atoms != numeraire.holding_atoms
            or numeraire.valuation_method_id != "numeraire_identity_1_to_1"
        ):
            raise ManifestError("numeraire holdings require exact 1:1 identity valuation")

    @property
    def total_numeraire_atoms(self) -> int | None:
        if any(component.status is ValuationStatus.REFUSED for component in self.components):
            return None
        total = sum(
            component.numeraire_atoms
            for component in self.components
            if component.numeraire_atoms is not None
        )
        return _atoms(total, "starting valuation total")

    def as_dict(self, snapshot: PortfolioSnapshot) -> dict[str, Any]:
        self.validate(snapshot)
        return {
            "manifest_id": self.manifest_id,
            "numeraire_asset_id": self.numeraire_asset_id,
            "as_of": _iso(self.as_of, "starting valuation as_of"),
            "known_at": _iso(self.known_at, "starting valuation known_at"),
            "commit_seq": str(self.commit_seq),
            "evidence_ids": list(self.evidence_ids),
            "evidence_digest": self.evidence_digest,
            "components": [component.as_dict() for component in self.components],
            "total_numeraire_atoms": (
                None
                if self.total_numeraire_atoms is None
                else str(self.total_numeraire_atoms)
            ),
        }


@dataclass(frozen=True, slots=True)
class SubjectBasis:
    asset_id: str
    quantity_atoms: int
    quality: BasisQuality
    numerator: int | None
    denominator: int | None
    evidence_ids: tuple[str, ...]

    def validate(self) -> None:
        _stable(self.asset_id, "basis asset_id")
        _atoms(self.quantity_atoms, "basis quantity_atoms")
        _sorted_unique(self.evidence_ids, "basis evidence_ids", nonempty=True)
        if self.quality is BasisQuality.KNOWN:
            if (
                isinstance(self.numerator, bool)
                or not isinstance(self.numerator, int)
                or self.numerator < 0
                or self.numerator > MAX_ATOMS
                or isinstance(self.denominator, bool)
                or not isinstance(self.denominator, int)
                or self.denominator <= 0
                or self.denominator > MAX_ATOMS
            ):
                raise ManifestError("known basis needs a bounded nonnegative reduced rational")
            if gcd(self.numerator, self.denominator) != 1:
                raise ManifestError("known basis rational must be reduced")
            if self.quantity_atoms == 0 and self.numerator != 0:
                raise ManifestError("exact-flat starting basis must be zero")
        else:
            if self.quantity_atoms == 0:
                raise ManifestError("exact-flat starting basis is known zero, not unknown")
            if self.numerator is not None or self.denominator is not None:
                raise ManifestError("unknown basis cannot carry a numeric value")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "asset_id": self.asset_id,
            "quantity_atoms": str(self.quantity_atoms),
            "quality": self.quality.value,
            "numerator": None if self.numerator is None else str(self.numerator),
            "denominator": None if self.denominator is None else str(self.denominator),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class EvidencePoint:
    point_id: str
    event_at: datetime
    available_at: datetime
    commit_seq: int
    cue: CueKind
    status: EvidenceStatus
    epistemic_kind: EpistemicKind
    evidence_ids: tuple[str, ...]
    evidence_digest: str
    scene_id: str | None = None
    gap_ids: tuple[str, ...] = ()
    reason: str | None = None
    outcome_visible: bool = False

    def validate(self) -> None:
        _stable(self.point_id, "point_id")
        if _aware(self.event_at, "point.event_at") > _aware(
            self.available_at, "point.available_at"
        ):
            raise TemporalLeakageError("evidence cannot be available before its event")
        _positive_commit(self.commit_seq, "point.commit_seq")
        _sorted_unique(self.evidence_ids, "point evidence_ids", nonempty=True)
        require_qualified_sha256(self.evidence_digest, "point.evidence_digest")
        _sorted_unique(self.gap_ids, "point gap_ids")
        if self.outcome_visible:
            raise TemporalLeakageError("decision evidence cannot contain outcome-visible material")
        if self.epistemic_kind is EpistemicKind.OPERATOR_PERCEPTION:
            if self.scene_id is None:
                raise ManifestError("operator perception must name its witnessed scene")
            _stable(self.scene_id, "point.scene_id")
        elif self.scene_id is not None:
            _stable(self.scene_id, "point.scene_id")
        if self.status is EvidenceStatus.OBSERVED:
            if self.gap_ids or self.reason is not None:
                raise ManifestError("observed evidence cannot carry a gap or refusal reason")
        elif not self.gap_ids and not self.reason:
            raise ManifestError("non-observed evidence needs a gap ID or reason")
        if self.reason is not None:
            _stable(self.reason, "point.reason")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "point_id": self.point_id,
            "event_at": _iso(self.event_at, "point.event_at"),
            "available_at": _iso(self.available_at, "point.available_at"),
            "commit_seq": str(self.commit_seq),
            "cue": self.cue.value,
            "status": self.status.value,
            "epistemic_kind": self.epistemic_kind.value,
            "evidence_ids": list(self.evidence_ids),
            "evidence_digest": self.evidence_digest,
            "scene_id": self.scene_id,
            "gap_ids": list(self.gap_ids),
            "reason": self.reason,
            "outcome_visible": False,
        }


@dataclass(frozen=True, slots=True)
class EconomicDiagnostic:
    diagnostic_id: str
    kind: DiagnosticKind
    asset_id: str
    atoms: int
    treatment: AccountingTreatment
    evidence_ids: tuple[str, ...]

    def validate(self) -> None:
        _stable(self.diagnostic_id, "diagnostic_id")
        _stable(self.asset_id, "diagnostic asset_id")
        if self.kind in {DiagnosticKind.LVR_GRID, DiagnosticKind.ITR}:
            _signed_atoms(self.atoms, "signed adverse-selection diagnostic atoms")
        else:
            _atoms(self.atoms, "diagnostic atoms")
        _sorted_unique(self.evidence_ids, "diagnostic evidence_ids", nonempty=True)
        expected = {
            DiagnosticKind.EXTERNAL_LP_FEE: AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT,
            DiagnosticKind.SELF_ROUTED_OWNED_FEE: AccountingTreatment.INTERNAL_NON_POSTING,
            DiagnosticKind.IRREVERSIBLE_COST: AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT,
            DiagnosticKind.LVR_GRID: AccountingTreatment.COUNTERFACTUAL_NON_POSTING,
            DiagnosticKind.ITR: AccountingTreatment.COUNTERFACTUAL_NON_POSTING,
        }[self.kind]
        if self.treatment is not expected:
            raise ManifestError(f"{self.kind.value} must use {expected.value} accounting treatment")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "diagnostic_id": self.diagnostic_id,
            "kind": self.kind.value,
            "asset_id": self.asset_id,
            "atoms": str(self.atoms),
            "accounting_treatment": self.treatment.value,
            "evidence_ids": list(self.evidence_ids),
        }


def _sum_delta_groups(*groups: tuple[AssetDelta, ...]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, group in enumerate(groups):
        for asset_id, atoms in delta_map(group, f"liquidity delta group {index}").items():
            result[asset_id] = result.get(asset_id, 0) + atoms
            _signed_atoms(result[asset_id], "liquidity reconciled delta")
    return {asset_id: atoms for asset_id, atoms in sorted(result.items()) if atoms != 0}


def _diagnostic_amounts(
    diagnostics: tuple[EconomicDiagnostic, ...], kind: DiagnosticKind
) -> dict[str, int]:
    result: dict[str, int] = {}
    for diagnostic in diagnostics:
        if diagnostic.kind is kind:
            result[diagnostic.asset_id] = result.get(diagnostic.asset_id, 0) + diagnostic.atoms
            _signed_atoms(result[diagnostic.asset_id], "diagnostic aggregate")
    return dict(sorted(result.items()))


@dataclass(frozen=True, slots=True)
class LiquidityEffectEvidence:
    event_id: str
    event_kind: LiquidityEventKind
    position_id: str
    installed_capital_event_id: str
    evidence_ids: tuple[str, ...]
    evidence_digest: str
    principal_deltas: tuple[AssetDelta, ...] = ()
    external_fee_deltas: tuple[AssetDelta, ...] = ()
    external_cost_deltas: tuple[AssetDelta, ...] = ()
    self_payer_deltas: tuple[AssetDelta, ...] = ()
    self_lp_deltas: tuple[AssetDelta, ...] = ()
    self_paid_fee: AssetAmount | None = None
    self_owned_fee: AssetAmount | None = None

    def validate(self) -> None:
        _stable(self.event_id, "liquidity event_id")
        _stable(self.position_id, "liquidity position_id")
        _stable(self.installed_capital_event_id, "installed capital event_id")
        _sorted_unique(self.evidence_ids, "liquidity evidence_ids", nonempty=True)
        require_qualified_sha256(self.evidence_digest, "liquidity evidence_digest")
        principal = delta_map(self.principal_deltas, "liquidity principal_deltas")
        fees = delta_map(self.external_fee_deltas, "liquidity external_fee_deltas")
        costs = delta_map(self.external_cost_deltas, "liquidity external_cost_deltas")
        payer = delta_map(self.self_payer_deltas, "liquidity self_payer_deltas")
        owned = delta_map(self.self_lp_deltas, "liquidity self_lp_deltas")
        if any(atoms <= 0 for atoms in fees.values()):
            raise ManifestError("external LP fee deltas must be positive controlled accruals")
        if any(atoms >= 0 for atoms in costs.values()):
            raise ManifestError("external liquidity costs must be negative household deltas")
        if self.event_kind is LiquidityEventKind.INSTALL:
            if self.installed_capital_event_id != self.event_id:
                raise ManifestError("LP install event must be its installed-capital occurrence")
            if not principal or not any(atoms < 0 for atoms in principal.values()):
                raise ManifestError("LP install needs an exact capital-decreasing principal leg")
            if fees or costs or payer or owned or self.self_paid_fee or self.self_owned_fee:
                raise ManifestError(
                    "LP install cannot carry flow fees, self legs, or external costs"
                )
        elif self.event_kind is LiquidityEventKind.EXTERNAL_FLOW:
            if not principal or not any(atoms < 0 for atoms in principal.values()) or not any(
                atoms > 0 for atoms in principal.values()
            ):
                raise ManifestError("external LP flow needs exact give and receive principal legs")
            if payer or owned or self.self_paid_fee or self.self_owned_fee:
                raise ManifestError("external LP flow cannot carry household self-flow legs")
        elif self.event_kind is LiquidityEventKind.SELF_FLOW:
            if principal or fees:
                raise ManifestError(
                    "self-flow principal and owned fee cannot post to household deltas"
                )
            if not payer or not owned:
                raise ManifestError("self-flow needs exact payer and owned-LP counterlegs")
            if _sum_delta_groups(self.self_payer_deltas, self.self_lp_deltas):
                raise ManifestError("self-flow payer and owned-LP legs must consolidate to zero")
            if self.self_paid_fee is None or self.self_owned_fee is None:
                raise ManifestError("self-flow needs exact paid and owned fee evidence")
            self.self_paid_fee.validate()
            self.self_owned_fee.validate()
            if self.self_paid_fee.atoms == 0 or self.self_paid_fee != self.self_owned_fee:
                raise ManifestError("self-paid and self-owned fee evidence must match exactly")
            fee_asset = self.self_paid_fee.asset_id
            if (
                payer.get(fee_asset, 0) > -self.self_paid_fee.atoms
                or owned.get(fee_asset, 0) < self.self_owned_fee.atoms
            ):
                raise ManifestError(
                    "self-paid/owned fee must be contained in the exact route counterlegs"
                )
        else:
            if fees or payer or owned or self.self_paid_fee or self.self_owned_fee:
                raise ManifestError("schedule maintenance cannot carry routed-flow fee attribution")
            if any(atoms > 0 for atoms in principal.values()) and not any(
                atoms < 0 for atoms in principal.values()
            ):
                raise ManifestError(
                    "schedule action cannot create positive inventory without input"
                )

    def reconcile(
        self,
        balance_deltas: tuple[AssetDelta, ...],
        diagnostics: tuple[EconomicDiagnostic, ...],
    ) -> None:
        self.validate()
        expected = (
            _sum_delta_groups(self.external_cost_deltas)
            if self.event_kind is LiquidityEventKind.SELF_FLOW
            else _sum_delta_groups(
                self.principal_deltas, self.external_fee_deltas, self.external_cost_deltas
            )
        )
        if expected != delta_map(balance_deltas, "liquidity quote balance_deltas"):
            raise ManifestError("liquidity accounting components do not reconcile to quote effect")
        for diagnostic in diagnostics:
            if not set(diagnostic.evidence_ids).issubset(self.evidence_ids):
                raise ManifestError("LP diagnostic evidence is outside the flow evidence closure")
        fee_diagnostics = _diagnostic_amounts(diagnostics, DiagnosticKind.EXTERNAL_LP_FEE)
        if fee_diagnostics != dict(sorted(delta_map(
            self.external_fee_deltas, "liquidity external_fee_deltas"
        ).items())):
            raise ManifestError("external LP fee diagnostics must equal evidenced fee deltas")
        self_diagnostics = _diagnostic_amounts(
            diagnostics, DiagnosticKind.SELF_ROUTED_OWNED_FEE
        )
        expected_self = (
            {}
            if self.self_owned_fee is None
            else {self.self_owned_fee.asset_id: self.self_owned_fee.atoms}
        )
        if self_diagnostics != expected_self:
            raise ManifestError("self-fee diagnostic must equal exact paid/owned fee evidence")
        cost_diagnostics = _diagnostic_amounts(diagnostics, DiagnosticKind.IRREVERSIBLE_COST)
        expected_costs = {
            asset_id: -atoms
            for asset_id, atoms in delta_map(
                self.external_cost_deltas, "liquidity external_cost_deltas"
            ).items()
        }
        if cost_diagnostics != expected_costs:
            raise ManifestError("irreversible-cost diagnostics must equal external cost deltas")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "event_id": self.event_id,
            "event_kind": self.event_kind.value,
            "position_id": self.position_id,
            "installed_capital_event_id": self.installed_capital_event_id,
            "evidence_ids": list(self.evidence_ids),
            "evidence_digest": self.evidence_digest,
            "principal_deltas": [item.as_dict() for item in self.principal_deltas],
            "external_fee_deltas": [item.as_dict() for item in self.external_fee_deltas],
            "external_cost_deltas": [item.as_dict() for item in self.external_cost_deltas],
            "self_payer_deltas": [item.as_dict() for item in self.self_payer_deltas],
            "self_lp_deltas": [item.as_dict() for item in self.self_lp_deltas],
            "self_paid_fee": None if self.self_paid_fee is None else self.self_paid_fee.as_dict(),
            "self_owned_fee": (
                None if self.self_owned_fee is None else self.self_owned_fee.as_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class ShadowQuote:
    quote_id: str
    decision_point_id: str
    role: QuoteRole
    action_kind: ActionKind
    method_id: str
    requested_at: datetime
    state_as_of: datetime
    available_at: datetime
    valid_through: datetime
    commit_seq: int
    status: QuoteStatus
    pre_balances: tuple[AssetAmount, ...]
    balance_deltas: tuple[AssetDelta, ...]
    evidence_ids: tuple[str, ...]
    evidence_digest: str
    terminal_asset_id: str | None = None
    liquidity_evidence: LiquidityEffectEvidence | None = None
    diagnostics: tuple[EconomicDiagnostic, ...] = ()
    refusal_reason: str | None = None

    def validate(self) -> None:
        _stable(self.quote_id, "quote_id")
        _stable(self.decision_point_id, "quote.decision_point_id")
        _stable(self.method_id, "quote.method_id")
        requested = _aware(self.requested_at, "quote.requested_at")
        state_as_of = _aware(self.state_as_of, "quote.state_as_of")
        available = _aware(self.available_at, "quote.available_at")
        valid = _aware(self.valid_through, "quote.valid_through")
        if requested > available or state_as_of > available or available > valid:
            raise TemporalLeakageError(
                "quote clocks must close requested/state <= available <= valid"
            )
        _positive_commit(self.commit_seq, "quote.commit_seq")
        pre = amount_map(self.pre_balances, "quote pre_balances")
        if not pre:
            raise ManifestError("quote must bind at least one pre-balance")
        deltas = delta_map(self.balance_deltas, "quote balance_deltas")
        _sorted_unique(self.evidence_ids, "quote evidence_ids", nonempty=True)
        require_qualified_sha256(self.evidence_digest, "quote.evidence_digest")
        diagnostic_ids: set[str] = set()
        measures: set[DiagnosticKind] = set()
        for diagnostic in self.diagnostics:
            diagnostic.validate()
            if diagnostic.diagnostic_id in diagnostic_ids:
                raise ManifestError("quote repeats a diagnostic ID")
            diagnostic_ids.add(diagnostic.diagnostic_id)
            if diagnostic.kind in {DiagnosticKind.LVR_GRID, DiagnosticKind.ITR}:
                measures.add(diagnostic.kind)
        if len(measures) > 1:
            raise ManifestError("one quote cannot report both LVR_grid and ITR")
        lp_actions = {
            ActionKind.LP_INSTALL: LiquidityEventKind.INSTALL,
            ActionKind.LP_ROUTE_EXTERNAL: LiquidityEventKind.EXTERNAL_FLOW,
            ActionKind.LP_ROUTE_SELF: LiquidityEventKind.SELF_FLOW,
            ActionKind.LP_REBALANCE: LiquidityEventKind.REBALANCE,
            ActionKind.LP_REMOVE: LiquidityEventKind.REMOVE,
        }
        expected_lp_kind = lp_actions.get(self.action_kind)
        if self.liquidity_evidence is not None:
            self.liquidity_evidence.validate()
            if (
                expected_lp_kind is None
                or self.liquidity_evidence.event_kind is not expected_lp_kind
            ):
                raise ManifestError("liquidity evidence kind does not match the quote action")
            if not set(self.liquidity_evidence.evidence_ids).issubset(self.evidence_ids):
                raise ManifestError("liquidity evidence must be in the quote evidence closure")
        if any(
            diagnostic.kind
            in {DiagnosticKind.EXTERNAL_LP_FEE, DiagnosticKind.SELF_ROUTED_OWNED_FEE}
            for diagnostic in self.diagnostics
        ) and self.liquidity_evidence is None:
            raise ManifestError("LP fee labels require exact liquidity accounting evidence")
        if self.status is QuoteStatus.PROJECTED:
            if not deltas:
                raise ManifestError("projected quote needs a deterministic balance effect")
            if self.refusal_reason is not None:
                raise ManifestError("projected quote cannot carry a refusal reason")
            for asset_id in deltas:
                if asset_id not in pre:
                    raise ManifestError("quote must bind every asset changed by its effect")
            for asset_id, before in pre.items():
                after = before + deltas.get(asset_id, 0)
                if not 0 <= after <= MAX_ATOMS:
                    raise ManifestError(
                        "quote effect would create negative or overflowing inventory"
                    )
            if expected_lp_kind is not None:
                if self.liquidity_evidence is None:
                    raise ManifestError("projected LP action needs exact position/capital evidence")
                self.liquidity_evidence.reconcile(self.balance_deltas, self.diagnostics)
            elif self.liquidity_evidence is not None:
                raise ManifestError("non-LP action cannot carry liquidity effect evidence")
        else:
            if deltas or self.diagnostics:
                raise ManifestError("refused quote cannot contain an effect or economic diagnostic")
            if not self.refusal_reason:
                raise ManifestError("refused quote needs a reason")
            _stable(self.refusal_reason, "quote.refusal_reason")
        if self.role is QuoteRole.TERMINAL_LIQUIDATION:
            if self.action_kind is not ActionKind.TERMINAL_LIQUIDATE:
                raise ManifestError("terminal quote must use terminal_liquidate action")
            if self.terminal_asset_id is None:
                raise ManifestError("terminal quote must name the asset it liquidates")
            _stable(self.terminal_asset_id, "quote.terminal_asset_id")
            if self.terminal_asset_id not in pre:
                raise ManifestError("terminal quote must bind its liquidation asset pre-balance")
            if self.status is QuoteStatus.PROJECTED and deltas.get(self.terminal_asset_id) != -pre[
                self.terminal_asset_id
            ]:
                raise ManifestError("terminal quote must remove the exact whole-position quantity")
        elif self.action_kind is ActionKind.TERMINAL_LIQUIDATE:
            raise ManifestError("terminal_liquidate action is reserved for the terminal manifest")
        elif self.terminal_asset_id is not None:
            raise ManifestError("only a terminal quote can name terminal_asset_id")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "quote_id": self.quote_id,
            "decision_point_id": self.decision_point_id,
            "role": self.role.value,
            "action_kind": self.action_kind.value,
            "method_id": self.method_id,
            "requested_at": _iso(self.requested_at, "quote.requested_at"),
            "state_as_of": _iso(self.state_as_of, "quote.state_as_of"),
            "available_at": _iso(self.available_at, "quote.available_at"),
            "valid_through": _iso(self.valid_through, "quote.valid_through"),
            "commit_seq": str(self.commit_seq),
            "status": self.status.value,
            "pre_balances": [amount.as_dict() for amount in self.pre_balances],
            "balance_deltas": [delta.as_dict() for delta in self.balance_deltas],
            "evidence_ids": list(self.evidence_ids),
            "evidence_digest": self.evidence_digest,
            "terminal_asset_id": self.terminal_asset_id,
            "liquidity_evidence": (
                None if self.liquidity_evidence is None else self.liquidity_evidence.as_dict()
            ),
            "diagnostics": [
                item.as_dict()
                for item in sorted(self.diagnostics, key=lambda item: item.diagnostic_id)
            ],
            "refusal_reason": self.refusal_reason,
            "explicit_non_claims": ["fill", "landing", "caused_market_effect"],
        }


@dataclass(frozen=True, slots=True)
class TerminalLiquidationManifest:
    manifest_id: str
    version: str
    horizon: datetime
    numeraire_asset_id: str
    method_id: str
    quotes: tuple[ShadowQuote, ...]

    def validate(self) -> None:
        _stable(self.manifest_id, "terminal manifest_id")
        _stable(self.version, "terminal manifest version")
        horizon = _aware(self.horizon, "terminal horizon")
        _stable(self.numeraire_asset_id, "terminal numeraire_asset_id")
        _stable(self.method_id, "terminal method_id")
        quote_ids: set[str] = set()
        for quote in self.quotes:
            quote.validate()
            if quote.quote_id in quote_ids:
                raise ManifestError("terminal manifest repeats a quote ID")
            quote_ids.add(quote.quote_id)
            if quote.role is not QuoteRole.TERMINAL_LIQUIDATION:
                raise ManifestError("terminal manifest can contain only terminal quotes")
            if quote.method_id != self.method_id:
                raise ManifestError("terminal quotes must share the declared liquidation method")
            if quote.terminal_asset_id == self.numeraire_asset_id:
                raise ManifestError("terminal quote cannot liquidate the numeraire into itself")
            deltas = delta_map(quote.balance_deltas, "terminal quote balance_deltas")
            if quote.status is QuoteStatus.PROJECTED and any(
                asset_id not in {quote.terminal_asset_id, self.numeraire_asset_id}
                for asset_id in deltas
            ):
                raise ManifestError("terminal quote can change only its asset and the numeraire")
            if quote.status is QuoteStatus.PROJECTED and deltas.get(
                self.numeraire_asset_id, 0
            ) <= 0:
                raise ManifestError(
                    "terminal disposal needs positive exact numeraire output or typed refusal"
                )
            if _aware(quote.available_at, "terminal quote available_at") > horizon:
                raise TemporalLeakageError("terminal quote must be available by the common horizon")
            if _aware(quote.valid_through, "terminal quote valid_through") < horizon:
                raise ManifestError("terminal quote must be valid at the common horizon")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "horizon": _iso(self.horizon, "terminal horizon"),
            "numeraire_asset_id": self.numeraire_asset_id,
            "method_id": self.method_id,
            "quotes": [
                quote.as_dict() for quote in sorted(self.quotes, key=lambda item: item.quote_id)
            ],
        }


@dataclass(frozen=True, slots=True)
class EvidenceEpisode:
    episode_id: str
    subject_asset_id: str
    numeraire_asset_id: str
    starts_at: datetime
    terminal_horizon: datetime
    knowledge_cutoff: datetime
    as_known_commit_seq: int
    starting_snapshot: PortfolioSnapshot
    starting_valuation: StartingValuation
    starting_subject_basis: SubjectBasis
    decision_points: tuple[EvidencePoint, ...]
    execution_quotes: tuple[ShadowQuote, ...]
    terminal_manifest: TerminalLiquidationManifest

    def validate(self) -> None:
        _stable(self.episode_id, "episode_id")
        _stable(self.subject_asset_id, "subject_asset_id")
        _stable(self.numeraire_asset_id, "numeraire_asset_id")
        if self.subject_asset_id == self.numeraire_asset_id:
            raise ManifestError("episode subject and numeraire assets must differ")
        starts = _aware(self.starts_at, "episode.starts_at")
        horizon = _aware(self.terminal_horizon, "episode.terminal_horizon")
        cutoff = _aware(self.knowledge_cutoff, "episode.knowledge_cutoff")
        if not starts < horizon <= cutoff:
            raise ManifestError("episode requires starts_at < terminal_horizon <= knowledge_cutoff")
        _positive_commit(self.as_known_commit_seq, "episode.as_known_commit_seq")
        self.starting_snapshot.validate()
        if _aware(self.starting_snapshot.known_at, "snapshot.known_at") > starts:
            raise TemporalLeakageError("starting snapshot was not known when the episode began")
        if self.starting_snapshot.commit_seq > self.as_known_commit_seq:
            raise TemporalLeakageError("starting snapshot exceeds the as-known commit cutoff")
        balances = amount_map(self.starting_snapshot.balances, "snapshot balances")
        if self.numeraire_asset_id not in balances or self.subject_asset_id not in balances:
            raise ManifestError(
                "snapshot must include subject and numeraire balances, including zero"
            )
        self.starting_valuation.validate(self.starting_snapshot)
        if self.starting_valuation.numeraire_asset_id != self.numeraire_asset_id:
            raise ManifestError("starting valuation and episode numeraires differ")
        if _aware(self.starting_valuation.as_of, "starting valuation as_of") != _aware(
            self.starting_snapshot.as_of, "snapshot.as_of"
        ):
            raise ManifestError("starting valuation and snapshot must share one as-of state")
        if _aware(self.starting_valuation.known_at, "starting valuation known_at") < _aware(
            self.starting_snapshot.known_at, "snapshot.known_at"
        ) or self.starting_valuation.commit_seq <= self.starting_snapshot.commit_seq:
            raise TemporalLeakageError(
                "starting valuation knowledge/commit must follow its exact snapshot"
            )
        if not set(self.starting_snapshot.evidence_ids).issubset(
            self.starting_valuation.evidence_ids
        ):
            raise ManifestError("starting valuation must bind the snapshot evidence closure")
        if _aware(self.starting_valuation.known_at, "starting valuation known_at") > starts:
            raise TemporalLeakageError("starting valuation was not known when the episode began")
        if self.starting_valuation.commit_seq > self.as_known_commit_seq:
            raise TemporalLeakageError("starting valuation exceeds the as-known commit cutoff")
        self.starting_subject_basis.validate()
        if self.starting_subject_basis.asset_id != self.subject_asset_id:
            raise ManifestError("starting basis must name the episode subject asset")
        if self.starting_subject_basis.quantity_atoms != balances[self.subject_asset_id]:
            raise ManifestError("starting basis quantity must match subject inventory")
        point_ids: set[str] = set()
        for point in self.decision_points:
            point.validate()
            if point.point_id in point_ids:
                raise ManifestError("episode repeats a decision point ID")
            point_ids.add(point.point_id)
            available = _aware(point.available_at, "point.available_at")
            if not starts <= available < horizon:
                raise TemporalLeakageError("decision point falls outside the prospective episode")
            if available > cutoff or point.commit_seq > self.as_known_commit_seq:
                raise TemporalLeakageError("decision point exceeds the as-known closure")
        expected_order = tuple(
            sorted(
                self.decision_points,
                key=lambda item: (
                    _aware(item.available_at, "point.available_at"),
                    item.commit_seq,
                    item.point_id,
                ),
            )
        )
        if self.decision_points != expected_order:
            raise ManifestError("decision points must be in deterministic as-known order")
        if expected_order and self.starting_valuation.commit_seq >= expected_order[0].commit_seq:
            raise TemporalLeakageError(
                "starting valuation commit must precede the first policy decision commit"
            )
        quote_ids: set[str] = set()
        points_by_id = {point.point_id: point for point in self.decision_points}
        point_indexes = {point.point_id: index for index, point in enumerate(self.decision_points)}
        for quote in self.execution_quotes:
            quote.validate()
            if quote.quote_id in quote_ids:
                raise ManifestError("episode repeats an execution quote ID")
            quote_ids.add(quote.quote_id)
            if quote.role is not QuoteRole.HYPOTHETICAL_EXECUTION:
                raise ManifestError("execution_quotes cannot contain terminal liquidation quotes")
            if quote.decision_point_id not in point_ids:
                raise ManifestError("execution quote references an unknown decision point")
            point = points_by_id[quote.decision_point_id]
            if _aware(quote.requested_at, "quote.requested_at") < _aware(
                point.available_at, "point.available_at"
            ):
                raise TemporalLeakageError("quote cannot be requested before its policy decision")
            if quote.commit_seq <= point.commit_seq:
                raise TemporalLeakageError(
                    "execution quote commit must follow its policy decision commit"
                )
            if _aware(quote.available_at, "quote.available_at") > horizon:
                raise TemporalLeakageError("execution quote arrives after the terminal horizon")
            next_index = point_indexes[point.point_id] + 1
            if next_index < len(self.decision_points):
                next_point = self.decision_points[next_index]
                quote_order = (
                    _aware(quote.available_at, "quote.available_at"),
                    quote.commit_seq,
                    quote.quote_id,
                )
                next_order = (
                    _aware(next_point.available_at, "next point.available_at"),
                    next_point.commit_seq,
                    next_point.point_id,
                )
                if quote_order >= next_order:
                    raise TemporalLeakageError(
                        "execution quote must precede the next decision in as-known order"
                    )
            if quote.commit_seq > self.as_known_commit_seq:
                raise TemporalLeakageError("execution quote exceeds the as-known commit cutoff")
        self.terminal_manifest.validate()
        if _aware(self.terminal_manifest.horizon, "terminal horizon") != horizon:
            raise ManifestError("all branches must use the episode terminal horizon")
        if self.terminal_manifest.numeraire_asset_id != self.numeraire_asset_id:
            raise ManifestError("episode and terminal liquidation numeraires differ")
        for quote in self.terminal_manifest.quotes:
            if quote.quote_id in quote_ids:
                raise ManifestError("quote IDs must be unique across execution and terminal roles")
            quote_ids.add(quote.quote_id)
            if quote.commit_seq > self.as_known_commit_seq:
                raise TemporalLeakageError("terminal quote exceeds the as-known commit cutoff")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "episode_id": self.episode_id,
            "subject_asset_id": self.subject_asset_id,
            "numeraire_asset_id": self.numeraire_asset_id,
            "starts_at": _iso(self.starts_at, "episode.starts_at"),
            "terminal_horizon": _iso(self.terminal_horizon, "episode.terminal_horizon"),
            "knowledge_cutoff": _iso(self.knowledge_cutoff, "episode.knowledge_cutoff"),
            "as_known_commit_seq": str(self.as_known_commit_seq),
            "starting_snapshot": self.starting_snapshot.as_dict(),
            "starting_valuation": self.starting_valuation.as_dict(self.starting_snapshot),
            "starting_subject_basis": self.starting_subject_basis.as_dict(),
            "decision_points": [point.as_dict() for point in self.decision_points],
            "execution_quotes": [
                quote.as_dict()
                for quote in sorted(self.execution_quotes, key=lambda item: item.quote_id)
            ],
            "terminal_manifest": self.terminal_manifest.as_dict(),
        }

    @property
    def digest(self) -> str:
        return qualified_sha256_bytes(canonical_json_bytes(self.as_dict()))


@dataclass(frozen=True, slots=True)
class PolicySpec:
    policy_id: str
    version: str
    family: PolicyFamily
    registered_at: datetime
    entry_spend_atoms: int = 0
    take_fraction_ppm: int = 0
    allowed_epistemic_kinds: tuple[EpistemicKind, ...] = (
        EpistemicKind.OBSERVED_FACT,
        EpistemicKind.DETERMINISTIC_CALCULATION,
        EpistemicKind.OPERATOR_PERCEPTION,
    )
    adverse_selection_measure: AdverseSelectionMeasure = AdverseSelectionMeasure.NONE

    def validate(self) -> None:
        _stable(self.policy_id, "policy_id")
        _stable(self.version, "policy version")
        _aware(self.registered_at, "policy.registered_at")
        _atoms(self.entry_spend_atoms, "policy.entry_spend_atoms")
        if (
            isinstance(self.take_fraction_ppm, bool)
            or not isinstance(self.take_fraction_ppm, int)
            or not 0 <= self.take_fraction_ppm <= 1_000_000
        ):
            raise ManifestError("take_fraction_ppm must be an integer in [0, 1000000]")
        if not self.allowed_epistemic_kinds:
            raise ManifestError("policy must declare at least one accepted epistemic kind")
        if tuple(dict.fromkeys(self.allowed_epistemic_kinds)) != self.allowed_epistemic_kinds:
            raise ManifestError("allowed epistemic kinds must be duplicate-free")
        entry_families = {
            PolicyFamily.CRACKLE_ENTRY,
            PolicyFamily.TAKE_SOME_RUNNER,
            PolicyFamily.FLAT_WATCH_REENTRY,
        }
        if self.family in entry_families and self.entry_spend_atoms == 0:
            raise ManifestError(f"{self.family.value} needs a positive exact entry spend")
        if self.family not in entry_families and self.entry_spend_atoms != 0:
            raise ManifestError(f"{self.family.value} cannot carry an entry spend")
        if self.family is PolicyFamily.TAKE_SOME_RUNNER:
            if not 0 < self.take_fraction_ppm < 1_000_000:
                raise ManifestError("take-some/runner policy needs a strict partial fraction")
        elif self.take_fraction_ppm != 0:
            raise ManifestError("take_fraction_ppm belongs only to take-some/runner")
        if (
            self.family is not PolicyFamily.LP_ROUTED_LIQUIDITY_SHADOW
            and self.adverse_selection_measure is not AdverseSelectionMeasure.NONE
        ):
            raise ManifestError("LVR/ITR selection belongs only to the routed-liquidity policy")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "family": self.family.value,
            "registered_at": _iso(self.registered_at, "policy.registered_at"),
            "entry_spend_atoms": str(self.entry_spend_atoms),
            "take_fraction_ppm": str(self.take_fraction_ppm),
            "allowed_epistemic_kinds": sorted(kind.value for kind in self.allowed_epistemic_kinds),
            "adverse_selection_measure": self.adverse_selection_measure.value,
            "authority": AUTHORITY,
        }

    @property
    def digest(self) -> str:
        return qualified_sha256_bytes(canonical_json_bytes(self.as_dict()))


@dataclass(frozen=True, slots=True)
class ArenaPlan:
    plan_id: str
    registered_at: datetime
    episode: EvidenceEpisode
    policies: tuple[PolicySpec, ...]
    opportunity_baseline_policy_id: str

    def validate(self) -> None:
        _stable(self.plan_id, "plan_id")
        registered = _aware(self.registered_at, "plan.registered_at")
        self.episode.validate()
        if registered > _aware(self.episode.starts_at, "episode.starts_at"):
            raise TemporalLeakageError("arena plan must be frozen before the scored episode")
        if not self.policies:
            raise ManifestError("arena needs at least one registered policy")
        ids: set[str] = set()
        for policy in self.policies:
            policy.validate()
            if policy.policy_id in ids:
                raise ManifestError("arena repeats a policy ID")
            ids.add(policy.policy_id)
            if _aware(policy.registered_at, "policy.registered_at") > registered:
                raise TemporalLeakageError("arena plan cannot include a policy registered later")
            if _aware(policy.registered_at, "policy.registered_at") > _aware(
                self.episode.starts_at, "episode.starts_at"
            ):
                raise TemporalLeakageError(
                    "policy version must be frozen before the scored episode"
                )
        if self.opportunity_baseline_policy_id not in ids:
            raise ManifestError("opportunity baseline must name a policy in this arena")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "plan_id": self.plan_id,
            "registered_at": _iso(self.registered_at, "plan.registered_at"),
            "episode": self.episode.as_dict(),
            "policies": [
                policy.as_dict()
                for policy in sorted(self.policies, key=lambda item: item.policy_id)
            ],
            "opportunity_baseline_policy_id": self.opportunity_baseline_policy_id,
            "authority": AUTHORITY,
        }

    @property
    def digest(self) -> str:
        return qualified_sha256_bytes(canonical_json_bytes(self.as_dict()))

    @property
    def artifact_id(self) -> str:
        return _content_id("shadow-plan", self.as_dict())
