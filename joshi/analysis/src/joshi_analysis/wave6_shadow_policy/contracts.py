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
    "net_pnl_equals_terminal_wealth_minus_starting_value;"
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
class ValuationComponent:
    asset_id: str
    holding_atoms: int
    numeraire_atoms: int
    evidence_ids: tuple[str, ...]

    def validate(self) -> None:
        _stable(self.asset_id, "valuation asset_id")
        _atoms(self.holding_atoms, "valuation holding_atoms")
        _atoms(self.numeraire_atoms, "valuation numeraire_atoms")
        _sorted_unique(self.evidence_ids, "valuation evidence_ids", nonempty=True)

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "asset_id": self.asset_id,
            "holding_atoms": str(self.holding_atoms),
            "numeraire_atoms": str(self.numeraire_atoms),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class StartingValuation:
    manifest_id: str
    numeraire_asset_id: str
    components: tuple[ValuationComponent, ...]

    def validate(self, snapshot: PortfolioSnapshot) -> None:
        _stable(self.manifest_id, "starting valuation manifest_id")
        _stable(self.numeraire_asset_id, "starting valuation numeraire_asset_id")
        if not self.components:
            raise ManifestError("starting valuation needs one component per snapshot asset")
        assets: dict[str, ValuationComponent] = {}
        for component in self.components:
            component.validate()
            if component.asset_id in assets:
                raise ManifestError("starting valuation repeats an asset")
            assets[component.asset_id] = component
        if tuple(assets) != tuple(sorted(assets)):
            raise ManifestError("starting valuation components must be sorted by asset_id")
        balances = amount_map(snapshot.balances, "snapshot balances")
        if set(assets) != set(balances):
            raise ManifestError("starting valuation must close every snapshot asset")
        for asset_id, atoms in balances.items():
            if assets[asset_id].holding_atoms != atoms:
                raise ManifestError("starting valuation holding does not match the snapshot")

    @property
    def total_numeraire_atoms(self) -> int:
        total = sum(component.numeraire_atoms for component in self.components)
        return _atoms(total, "starting valuation total")

    def as_dict(self, snapshot: PortfolioSnapshot) -> dict[str, Any]:
        self.validate(snapshot)
        return {
            "manifest_id": self.manifest_id,
            "numeraire_asset_id": self.numeraire_asset_id,
            "components": [component.as_dict() for component in self.components],
            "total_numeraire_atoms": str(self.total_numeraire_atoms),
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
            if _aware(quote.available_at, "quote.available_at") > horizon:
                raise TemporalLeakageError("execution quote arrives after the terminal horizon")
            next_index = point_indexes[point.point_id] + 1
            if next_index < len(self.decision_points) and _aware(
                quote.available_at, "quote.available_at"
            ) > _aware(self.decision_points[next_index].available_at, "next point.available_at"):
                raise TemporalLeakageError(
                    "execution quote arrives after the next chronological decision point"
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
