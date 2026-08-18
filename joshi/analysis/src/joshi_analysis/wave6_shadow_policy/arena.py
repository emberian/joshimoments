from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes
from ..errors import ManifestError
from .contracts import (
    ACCOUNTING_IDENTITY,
    AUTHORITY,
    CALCULATOR_VERSION,
    SCHEMA_ID,
    AccountingTreatment,
    ActionKind,
    AdverseSelectionMeasure,
    ArenaPlan,
    AssetDelta,
    BasisQuality,
    CueKind,
    DiagnosticKind,
    EconomicDiagnostic,
    EpistemicKind,
    EvidencePoint,
    EvidenceStatus,
    PolicyFamily,
    PolicySpec,
    QuoteStatus,
    ShadowQuote,
    _content_id,
    _iso,
    amount_map,
    delta_map,
)


class RefusalCode(StrEnum):
    EVIDENCE_NOT_OBSERVED = "evidence_not_observed"
    EPISTEMIC_KIND_NOT_ADMITTED = "epistemic_kind_not_admitted"
    MISSING_QUOTE = "missing_quote"
    AMBIGUOUS_QUOTE = "ambiguous_quote"
    QUOTE_REFUSED = "quote_refused"
    QUOTE_STATE_MISMATCH = "quote_state_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    INVENTORY_CONSTRAINT = "inventory_constraint"
    DUPLICATE_QUOTE_USE = "duplicate_quote_use"
    ADVERSE_SELECTION_CONFLICT = "adverse_selection_conflict"


class BranchStatus(StrEnum):
    COMPLETE = "complete"
    COMPLETE_WITH_REFUSALS = "complete_with_refusals"
    TERMINAL_VALUE_UNKNOWN = "terminal_value_unknown"


@dataclass(frozen=True, slots=True)
class UncertaintyRecord:
    uncertainty_id: str
    kind: str
    point_id: str | None
    reason: str
    gap_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "uncertainty_id": self.uncertainty_id,
            "kind": self.kind,
            "point_id": self.point_id,
            "reason": self.reason,
            "gap_ids": list(self.gap_ids),
            "treatment": "preserved_not_zero",
        }


@dataclass(frozen=True, slots=True)
class RefusalRecord:
    refusal_id: str
    point_id: str
    code: RefusalCode
    reason: str
    quote_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "refusal_id": self.refusal_id,
            "point_id": self.point_id,
            "code": self.code.value,
            "reason": self.reason,
            "quote_id": self.quote_id,
        }


@dataclass(frozen=True, slots=True)
class PolicyAction:
    action_id: str
    policy_id: str
    point_id: str
    decided_at: str
    action_kind: ActionKind
    evidence_ids: tuple[str, ...]
    before_balances: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "policy_id": self.policy_id,
            "point_id": self.point_id,
            "decided_at": self.decided_at,
            "action_kind": self.action_kind.value,
            "evidence_ids": list(self.evidence_ids),
            "before_balances": [
                {"asset_id": asset_id, "atoms": str(atoms)}
                for asset_id, atoms in self.before_balances
            ],
            "epistemic_kind": "hypothetical_policy_decision",
            "authority": AUTHORITY,
        }


@dataclass(frozen=True, slots=True)
class RationalValue:
    numerator: int
    denominator: int

    @classmethod
    def from_fraction(cls, value: Fraction) -> RationalValue:
        return cls(value.numerator, value.denominator)

    def as_dict(self) -> dict[str, str]:
        return {"numerator": str(self.numerator), "denominator": str(self.denominator)}


@dataclass(frozen=True, slots=True)
class BasisProjection:
    asset_id: str
    quantity_atoms: int
    quality: BasisQuality
    value: RationalValue | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "quantity_atoms": str(self.quantity_atoms),
            "quality": self.quality.value,
            "value": None if self.value is None else self.value.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ExecutionProjection:
    execution_id: str
    action_id: str
    quote_id: str | None
    projected_at: str
    status: str
    refusal_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "action_id": self.action_id,
            "quote_id": self.quote_id,
            "projected_at": self.projected_at,
            "status": self.status,
            "refusal_id": self.refusal_id,
            "epistemic_kind": "quote_backed_hypothetical_execution",
            "explicit_non_claims": ["transaction", "signature", "submission", "landing", "fill"],
            "authority": AUTHORITY,
        }


@dataclass(frozen=True, slots=True)
class HypotheticalEffect:
    effect_id: str
    execution_id: str
    quote_id: str
    effective_at: str
    balance_deltas: tuple[AssetDelta, ...]
    before_balances: tuple[tuple[str, int], ...]
    after_balances: tuple[tuple[str, int], ...]
    basis_before: BasisProjection
    allocated_basis: RationalValue | None
    acquisition_basis: RationalValue | None
    realized_result: RationalValue | None
    basis_after: BasisProjection

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "execution_id": self.execution_id,
            "quote_id": self.quote_id,
            "effective_at": self.effective_at,
            "balance_deltas": [delta.as_dict() for delta in self.balance_deltas],
            "before_balances": [
                {"asset_id": asset_id, "atoms": str(atoms)}
                for asset_id, atoms in self.before_balances
            ],
            "after_balances": [
                {"asset_id": asset_id, "atoms": str(atoms)}
                for asset_id, atoms in self.after_balances
            ],
            "subject_basis_before": self.basis_before.as_dict(),
            "allocated_basis": (
                None if self.allocated_basis is None else self.allocated_basis.as_dict()
            ),
            "acquisition_basis": (
                None if self.acquisition_basis is None else self.acquisition_basis.as_dict()
            ),
            "realized_result": (
                None if self.realized_result is None else self.realized_result.as_dict()
            ),
            "realized_result_treatment": "diagnostic_not_added_to_terminal_pnl",
            "subject_basis_after": self.basis_after.as_dict(),
            "epistemic_kind": "deterministic_hypothetical_effect",
            "posted_to_actual_ledger": False,
            "explicit_non_claims": ["landed_effect", "fill", "caused_market_effect"],
            "authority": AUTHORITY,
        }


@dataclass(frozen=True, slots=True)
class LiquidationLeg:
    asset_id: str
    input_atoms: int
    quote_id: str | None
    status: str
    net_numeraire_effect_atoms: int | None
    allocated_basis: RationalValue | None
    realized_result: RationalValue | None
    reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "input_atoms": str(self.input_atoms),
            "quote_id": self.quote_id,
            "status": self.status,
            "net_numeraire_effect_atoms": (
                None
                if self.net_numeraire_effect_atoms is None
                else str(self.net_numeraire_effect_atoms)
            ),
            "allocated_basis": (
                None if self.allocated_basis is None else self.allocated_basis.as_dict()
            ),
            "realized_result": (
                None if self.realized_result is None else self.realized_result.as_dict()
            ),
            "realized_result_treatment": "diagnostic_not_added_to_terminal_pnl",
            "reason": self.reason,
            "epistemic_kind": "terminal_quote_projection_not_fill",
        }


@dataclass(frozen=True, slots=True)
class BranchResult:
    branch_id: str
    policy_id: str
    policy_family: PolicyFamily
    policy_digest: str
    common_information_digest: str
    status: BranchStatus
    actions: tuple[PolicyAction, ...]
    executions: tuple[ExecutionProjection, ...]
    effects: tuple[HypotheticalEffect, ...]
    refusals: tuple[RefusalRecord, ...]
    uncertainties: tuple[UncertaintyRecord, ...]
    diagnostics: tuple[EconomicDiagnostic, ...]
    pre_liquidation_balances: tuple[tuple[str, int], ...]
    pre_liquidation_subject_basis: BasisProjection
    liquidation_legs: tuple[LiquidationLeg, ...]
    terminal_balances: tuple[tuple[str, int], ...]
    terminal_subject_basis: BasisProjection
    starting_value_numeraire_atoms: int
    terminal_wealth_numeraire_atoms: int | None
    net_pnl_numeraire_atoms: int | None
    episode_states: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "policy_id": self.policy_id,
            "policy_family": self.policy_family.value,
            "policy_digest": self.policy_digest,
            "common_information_digest": self.common_information_digest,
            "status": self.status.value,
            "actions": [action.as_dict() for action in self.actions],
            "execution_projections": [execution.as_dict() for execution in self.executions],
            "hypothetical_effects": [effect.as_dict() for effect in self.effects],
            "refusals": [refusal.as_dict() for refusal in self.refusals],
            "uncertainties": [uncertainty.as_dict() for uncertainty in self.uncertainties],
            "non_posting_diagnostics": [diagnostic.as_dict() for diagnostic in self.diagnostics],
            "pre_liquidation_balances": _wire_balances(self.pre_liquidation_balances),
            "pre_liquidation_subject_basis": self.pre_liquidation_subject_basis.as_dict(),
            "liquidation_legs": [leg.as_dict() for leg in self.liquidation_legs],
            "terminal_balances": _wire_balances(self.terminal_balances),
            "terminal_subject_basis": self.terminal_subject_basis.as_dict(),
            "starting_value_numeraire_atoms": str(self.starting_value_numeraire_atoms),
            "terminal_wealth_numeraire_atoms": (
                None
                if self.terminal_wealth_numeraire_atoms is None
                else str(self.terminal_wealth_numeraire_atoms)
            ),
            "net_pnl_numeraire_atoms": (
                None if self.net_pnl_numeraire_atoms is None else str(self.net_pnl_numeraire_atoms)
            ),
            "episode_states": list(self.episode_states),
            "accounting_identity": ACCOUNTING_IDENTITY,
            "authority": AUTHORITY,
        }


@dataclass(frozen=True, slots=True)
class OpportunityComparison:
    comparison_id: str
    baseline_policy_id: str
    candidate_policy_id: str
    status: str
    opportunity_cost_numeraire_atoms: int | None
    candidate_surplus_numeraire_atoms: int | None
    reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "baseline_policy_id": self.baseline_policy_id,
            "candidate_policy_id": self.candidate_policy_id,
            "status": self.status,
            "opportunity_cost_numeraire_atoms": (
                None
                if self.opportunity_cost_numeraire_atoms is None
                else str(self.opportunity_cost_numeraire_atoms)
            ),
            "candidate_surplus_numeraire_atoms": (
                None
                if self.candidate_surplus_numeraire_atoms is None
                else str(self.candidate_surplus_numeraire_atoms)
            ),
            "reason": self.reason,
            "accounting_treatment": "counterfactual_non_posting",
        }


@dataclass(frozen=True, slots=True)
class ArenaArtifact:
    artifact_id: str
    artifact_digest: str
    plan_id: str
    plan_digest: str
    episode_id: str
    common_information_digest: str
    branches: tuple[BranchResult, ...]
    opportunity_comparisons: tuple[OpportunityComparison, ...]

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "calculator_version": CALCULATOR_VERSION,
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "episode_id": self.episode_id,
            "common_information_digest": self.common_information_digest,
            "branches": [branch.as_dict() for branch in self.branches],
            "opportunity_comparisons": [item.as_dict() for item in self.opportunity_comparisons],
            "claims": [
                "conditional_shadow_comparison_only",
                "common_information_chronological_replay",
                "terminal_liquidated_when_fully_quotable",
            ],
            "explicit_non_claims": [
                "profitability_generalization",
                "causal_policy_value",
                "fill",
                "landing",
                "live_authority",
            ],
            "accounting_identity": ACCOUNTING_IDENTITY,
            "authority": AUTHORITY,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        expected_digest = qualified_sha256_bytes(canonical_json_bytes(payload))
        expected_id = _content_id("shadow-arena", payload)
        if self.artifact_digest != expected_digest or self.artifact_id != expected_id:
            raise ManifestError("arena artifact identity does not match canonical payload")
        return {
            **payload,
            "artifact_id": self.artifact_id,
            "artifact_digest": self.artifact_digest,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())


_FINANCIAL_CUES: dict[PolicyFamily, dict[CueKind, ActionKind]] = {
    PolicyFamily.ABSTAIN: {},
    PolicyFamily.OBSERVE: {},
    PolicyFamily.CRACKLE_ENTRY: {
        CueKind.CRACKLE_ENTRY: ActionKind.BUY,
        CueKind.CRACKLE_EXIT: ActionKind.SELL_ALL,
        CueKind.FULL_EXIT: ActionKind.SELL_ALL,
    },
    PolicyFamily.TAKE_SOME_RUNNER: {
        CueKind.CRACKLE_ENTRY: ActionKind.BUY,
        CueKind.TAKE_SOME: ActionKind.SELL_PARTIAL,
        CueKind.FULL_EXIT: ActionKind.SELL_ALL,
    },
    PolicyFamily.FLAT_WATCH_REENTRY: {
        CueKind.CRACKLE_ENTRY: ActionKind.BUY,
        CueKind.FLAT_WATCH: ActionKind.FLAT_WATCH_EXIT,
        CueKind.REENTRY: ActionKind.REENTER,
        CueKind.FULL_EXIT: ActionKind.SELL_ALL,
    },
    PolicyFamily.LP_ROUTED_LIQUIDITY_SHADOW: {
        CueKind.LP_INSTALL: ActionKind.LP_INSTALL,
        CueKind.LP_EXTERNAL_FLOW: ActionKind.LP_ROUTE_EXTERNAL,
        CueKind.LP_SELF_FLOW: ActionKind.LP_ROUTE_SELF,
        CueKind.LP_REBALANCE: ActionKind.LP_REBALANCE,
        CueKind.LP_REMOVE: ActionKind.LP_REMOVE,
    },
}


def registered_policy_families() -> tuple[str, ...]:
    """Return the closed Wave 6 prototype registry in stable order."""

    return tuple(family.value for family in PolicyFamily)


def _wire_balances(balances: tuple[tuple[str, int], ...]) -> list[dict[str, str]]:
    return [{"asset_id": asset_id, "atoms": str(atoms)} for asset_id, atoms in balances]


def _frozen_balances(balances: dict[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(balances.items()))


@dataclass(slots=True)
class _BasisTracker:
    value: Fraction | None


def _basis_projection(
    asset_id: str, quantity_atoms: int, tracker: _BasisTracker
) -> BasisProjection:
    return BasisProjection(
        asset_id=asset_id,
        quantity_atoms=quantity_atoms,
        quality=BasisQuality.KNOWN if tracker.value is not None else BasisQuality.UNKNOWN,
        value=None if tracker.value is None else RationalValue.from_fraction(tracker.value),
    )


def _advance_basis(
    *,
    tracker: _BasisTracker,
    subject_before: int,
    subject_after: int,
    subject_delta: int,
    numeraire_delta: int,
    numeraire_changed: bool,
) -> tuple[RationalValue | None, RationalValue | None, RationalValue | None]:
    allocated: Fraction | None = None
    acquisition: Fraction | None = None
    realized: Fraction | None = None
    if subject_delta < 0:
        disposed = -subject_delta
        if tracker.value is not None:
            allocated = tracker.value * disposed / subject_before
            tracker.value -= allocated
            if numeraire_changed and numeraire_delta >= 0:
                realized = Fraction(numeraire_delta) - allocated
        if subject_after == 0:
            tracker.value = Fraction(0)
    elif subject_delta > 0:
        if numeraire_changed and numeraire_delta < 0:
            acquisition = Fraction(-numeraire_delta)
            if tracker.value is not None:
                tracker.value += acquisition
        else:
            tracker.value = None
    return (
        None if allocated is None else RationalValue.from_fraction(allocated),
        None if acquisition is None else RationalValue.from_fraction(acquisition),
        None if realized is None else RationalValue.from_fraction(realized),
    )


def _record_id(prefix: str, payload: dict[str, Any]) -> str:
    return _content_id(prefix, payload)


def _action(
    policy: PolicySpec,
    point: EvidencePoint,
    kind: ActionKind,
    balances: dict[str, int],
) -> PolicyAction:
    before = _frozen_balances(balances)
    payload = {
        "policy_digest": policy.digest,
        "point_id": point.point_id,
        "decided_at": _iso(point.available_at, "point.available_at"),
        "action_kind": kind.value,
        "evidence_ids": list(point.evidence_ids),
        "before_balances": _wire_balances(before),
    }
    return PolicyAction(
        action_id=_record_id("shadow-action", payload),
        policy_id=policy.policy_id,
        point_id=point.point_id,
        decided_at=payload["decided_at"],
        action_kind=kind,
        evidence_ids=point.evidence_ids,
        before_balances=before,
    )


def _execution(
    action: PolicyAction,
    *,
    quote_id: str | None,
    projected_at: str | None = None,
    status: str,
    refusal_id: str | None,
) -> ExecutionProjection:
    payload = {
        "action_id": action.action_id,
        "quote_id": quote_id,
        "projected_at": projected_at or action.decided_at,
        "status": status,
        "refusal_id": refusal_id,
    }
    return ExecutionProjection(
        execution_id=_record_id("shadow-execution", payload),
        action_id=action.action_id,
        quote_id=quote_id,
        projected_at=payload["projected_at"],
        status=status,
        refusal_id=refusal_id,
    )


def _refusal(
    policy: PolicySpec,
    point: EvidencePoint,
    code: RefusalCode,
    reason: str,
    quote_id: str | None = None,
) -> RefusalRecord:
    payload = {
        "policy_id": policy.policy_id,
        "point_id": point.point_id,
        "code": code.value,
        "reason": reason,
        "quote_id": quote_id,
    }
    return RefusalRecord(
        refusal_id=_record_id("shadow-refusal", payload),
        point_id=point.point_id,
        code=code,
        reason=reason,
        quote_id=quote_id,
    )


def _uncertainty(point: EvidencePoint) -> UncertaintyRecord:
    reason = point.reason or f"evidence status is {point.status.value}"
    payload = {
        "point_id": point.point_id,
        "kind": point.status.value,
        "reason": reason,
        "gap_ids": list(point.gap_ids),
    }
    return UncertaintyRecord(
        uncertainty_id=_record_id("shadow-uncertainty", payload),
        kind=point.status.value,
        point_id=point.point_id,
        reason=reason,
        gap_ids=point.gap_ids,
    )


def _preconditions_match(quote: ShadowQuote, balances: dict[str, int]) -> bool:
    return all(balances.get(asset_id, 0) == atoms for asset_id, atoms in amount_map(
        quote.pre_balances, "quote pre_balances"
    ).items())


def _apply_quote(
    quote: ShadowQuote,
    balances: dict[str, int],
    execution: ExecutionProjection,
    *,
    subject_asset_id: str,
    numeraire_asset_id: str,
    basis: _BasisTracker,
) -> HypotheticalEffect:
    before = _frozen_balances(balances)
    mapped_deltas = delta_map(quote.balance_deltas, "quote balance_deltas")
    subject_before = balances.get(subject_asset_id, 0)
    basis_before = _basis_projection(subject_asset_id, subject_before, basis)
    for asset_id, atoms in mapped_deltas.items():
        balances[asset_id] = balances.get(asset_id, 0) + atoms
        if balances[asset_id] < 0:
            raise ManifestError("validated quote produced negative branch inventory")
    subject_after = balances.get(subject_asset_id, 0)
    allocated, acquisition, realized = _advance_basis(
        tracker=basis,
        subject_before=subject_before,
        subject_after=subject_after,
        subject_delta=mapped_deltas.get(subject_asset_id, 0),
        numeraire_delta=mapped_deltas.get(numeraire_asset_id, 0),
        numeraire_changed=numeraire_asset_id in mapped_deltas,
    )
    basis_after = _basis_projection(subject_asset_id, subject_after, basis)
    after = _frozen_balances(balances)
    payload = {
        "execution_id": execution.execution_id,
        "quote_id": quote.quote_id,
        "effective_at": _iso(quote.available_at, "quote.available_at"),
        "balance_deltas": [delta.as_dict() for delta in quote.balance_deltas],
        "before_balances": _wire_balances(before),
        "after_balances": _wire_balances(after),
        "basis_before": basis_before.as_dict(),
        "allocated_basis": None if allocated is None else allocated.as_dict(),
        "acquisition_basis": None if acquisition is None else acquisition.as_dict(),
        "realized_result": None if realized is None else realized.as_dict(),
        "basis_after": basis_after.as_dict(),
    }
    return HypotheticalEffect(
        effect_id=_record_id("shadow-effect", payload),
        execution_id=execution.execution_id,
        quote_id=quote.quote_id,
        effective_at=payload["effective_at"],
        balance_deltas=quote.balance_deltas,
        before_balances=before,
        after_balances=after,
        basis_before=basis_before,
        allocated_basis=allocated,
        acquisition_basis=acquisition,
        realized_result=realized,
        basis_after=basis_after,
    )


def _action_is_sequence_eligible(
    action_kind: ActionKind,
    balances: dict[str, int],
    policy: PolicySpec,
    subject_asset_id: str,
) -> bool:
    subject = balances.get(subject_asset_id, 0)
    if action_kind in {ActionKind.BUY, ActionKind.REENTER}:
        return subject == 0
    if action_kind in {
        ActionKind.SELL_ALL,
        ActionKind.SELL_PARTIAL,
        ActionKind.FLAT_WATCH_EXIT,
    }:
        return subject > 0
    return policy.family is PolicyFamily.LP_ROUTED_LIQUIDITY_SHADOW


def _quote_size_matches(
    quote: ShadowQuote,
    action_kind: ActionKind,
    balances: dict[str, int],
    policy: PolicySpec,
    subject_asset_id: str,
    numeraire_asset_id: str,
) -> bool:
    deltas = delta_map(quote.balance_deltas, "quote balance_deltas")
    subject_delta = deltas.get(subject_asset_id, 0)
    numeraire_delta = deltas.get(numeraire_asset_id, 0)
    if action_kind in {ActionKind.BUY, ActionKind.REENTER}:
        return subject_delta > 0 and numeraire_delta == -policy.entry_spend_atoms
    if action_kind in {ActionKind.SELL_ALL, ActionKind.FLAT_WATCH_EXIT}:
        return subject_delta == -balances.get(subject_asset_id, 0) and numeraire_delta >= 0
    if action_kind is ActionKind.SELL_PARTIAL:
        expected = balances.get(subject_asset_id, 0) * policy.take_fraction_ppm // 1_000_000
        return expected > 0 and subject_delta == -expected and numeraire_delta >= 0
    return True


def _adverse_measure_is_compatible(policy: PolicySpec, quote: ShadowQuote) -> bool:
    kinds = {item.kind for item in quote.diagnostics}
    if DiagnosticKind.LVR_GRID in kinds:
        return policy.adverse_selection_measure is AdverseSelectionMeasure.LVR_GRID
    if DiagnosticKind.ITR in kinds:
        return policy.adverse_selection_measure is AdverseSelectionMeasure.ITR
    return True


def _state_after(action_kind: ActionKind, current: str) -> str:
    if action_kind is ActionKind.BUY:
        return "exposed_epoch_1"
    if action_kind is ActionKind.SELL_PARTIAL:
        return "runner_retained"
    if action_kind is ActionKind.FLAT_WATCH_EXIT:
        return "flat_watching"
    if action_kind is ActionKind.REENTER:
        return "exposed_epoch_2"
    if action_kind is ActionKind.SELL_ALL:
        return "exact_flat"
    if action_kind is ActionKind.LP_INSTALL:
        return "lp_shadow_installed"
    if action_kind is ActionKind.LP_REMOVE:
        return "lp_shadow_removed"
    if action_kind in {
        ActionKind.LP_ROUTE_EXTERNAL,
        ActionKind.LP_ROUTE_SELF,
        ActionKind.LP_REBALANCE,
    }:
        return f"{current}+{action_kind.value}"
    return current


def _evaluate_branch(plan: ArenaPlan, policy: PolicySpec) -> BranchResult:
    episode = plan.episode
    balances = amount_map(episode.starting_snapshot.balances, "snapshot balances").copy()
    starting_basis = episode.starting_subject_basis
    basis = _BasisTracker(
        None
        if starting_basis.quality is BasisQuality.UNKNOWN
        else Fraction(starting_basis.numerator, starting_basis.denominator)
    )
    actions: list[PolicyAction] = []
    executions: list[ExecutionProjection] = []
    effects: list[HypotheticalEffect] = []
    refusals: list[RefusalRecord] = []
    uncertainties = [
        _uncertainty(point)
        for point in episode.decision_points
        if point.status is not EvidenceStatus.OBSERVED
    ]
    diagnostics: list[EconomicDiagnostic] = []
    diagnostic_ids: set[str] = set()
    used_quotes: set[str] = set()
    states = ["starting_snapshot"]

    if policy.family is PolicyFamily.ABSTAIN:
        if episode.decision_points:
            point = episode.decision_points[0]
            actions.append(_action(policy, point, ActionKind.ABSTAIN, balances))
            states.append("abstained")
    elif policy.family is PolicyFamily.OBSERVE:
        for point in episode.decision_points:
            actions.append(_action(policy, point, ActionKind.OBSERVE, balances))
        states.append("observed_without_exposure_change")
    else:
        action_map = _FINANCIAL_CUES[policy.family]
        state = "flat" if balances.get(episode.subject_asset_id, 0) == 0 else "exposed_epoch_0"
        for point in episode.decision_points:
            action_kind = action_map.get(point.cue)
            if action_kind is None or not _action_is_sequence_eligible(
                action_kind, balances, policy, episode.subject_asset_id
            ):
                continue
            if point.status is not EvidenceStatus.OBSERVED:
                action = _action(policy, point, ActionKind.REFUSE, balances)
                refusal = _refusal(
                    policy,
                    point,
                    RefusalCode.EVIDENCE_NOT_OBSERVED,
                    point.reason or f"decision evidence is {point.status.value}",
                )
                actions.append(action)
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=None,
                        status="refused_before_quote",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            if point.epistemic_kind not in policy.allowed_epistemic_kinds:
                action = _action(policy, point, ActionKind.REFUSE, balances)
                refusal = _refusal(
                    policy,
                    point,
                    RefusalCode.EPISTEMIC_KIND_NOT_ADMITTED,
                    f"policy does not admit {point.epistemic_kind.value}",
                )
                actions.append(action)
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=None,
                        status="refused_before_quote",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            action = _action(policy, point, action_kind, balances)
            actions.append(action)
            candidates = [
                quote
                for quote in episode.execution_quotes
                if quote.decision_point_id == point.point_id
                and quote.action_kind is action_kind
                and _preconditions_match(quote, balances)
            ]
            if not candidates:
                code = (
                    RefusalCode.QUOTE_STATE_MISMATCH
                    if any(
                        quote.decision_point_id == point.point_id
                        and quote.action_kind is action_kind
                        for quote in episode.execution_quotes
                    )
                    else RefusalCode.MISSING_QUOTE
                )
                refusal = _refusal(policy, point, code, "no exact state-conditioned quote")
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=None,
                        status="refused_no_quote",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            if len(candidates) != 1:
                refusal = _refusal(
                    policy,
                    point,
                    RefusalCode.AMBIGUOUS_QUOTE,
                    "multiple quotes match the same action and pre-state",
                )
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=None,
                        status="refused_ambiguous_quote",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            quote = candidates[0]
            if quote.quote_id in used_quotes:
                refusal = _refusal(
                    policy,
                    point,
                    RefusalCode.DUPLICATE_QUOTE_USE,
                    "one hypothetical quote cannot support two effects in one branch",
                    quote.quote_id,
                )
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=quote.quote_id,
                        projected_at=_iso(quote.available_at, "quote.available_at"),
                        status="refused_duplicate_quote",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            if quote.status is QuoteStatus.REFUSED:
                refusal = _refusal(
                    policy,
                    point,
                    RefusalCode.QUOTE_REFUSED,
                    quote.refusal_reason or "quote refused",
                    quote.quote_id,
                )
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=quote.quote_id,
                        projected_at=_iso(quote.available_at, "quote.available_at"),
                        status="quote_refused",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            if not _quote_size_matches(
                quote,
                action_kind,
                balances,
                policy,
                episode.subject_asset_id,
                episode.numeraire_asset_id,
            ):
                refusal = _refusal(
                    policy,
                    point,
                    RefusalCode.SIZE_MISMATCH,
                    "quote does not match the policy's exact declared size",
                    quote.quote_id,
                )
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=quote.quote_id,
                        projected_at=_iso(quote.available_at, "quote.available_at"),
                        status="refused_size_mismatch",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            if not _adverse_measure_is_compatible(policy, quote):
                refusal = _refusal(
                    policy,
                    point,
                    RefusalCode.ADVERSE_SELECTION_CONFLICT,
                    "quote diagnostic conflicts with the predeclared LVR/ITR choice",
                    quote.quote_id,
                )
                refusals.append(refusal)
                executions.append(
                    _execution(
                        action,
                        quote_id=quote.quote_id,
                        projected_at=_iso(quote.available_at, "quote.available_at"),
                        status="refused_diagnostic_conflict",
                        refusal_id=refusal.refusal_id,
                    )
                )
                continue
            execution = _execution(
                action,
                quote_id=quote.quote_id,
                projected_at=_iso(quote.available_at, "quote.available_at"),
                status="hypothetical_effect_projected",
                refusal_id=None,
            )
            executions.append(execution)
            effect = _apply_quote(
                quote,
                balances,
                execution,
                subject_asset_id=episode.subject_asset_id,
                numeraire_asset_id=episode.numeraire_asset_id,
                basis=basis,
            )
            effects.append(effect)
            used_quotes.add(quote.quote_id)
            for diagnostic in sorted(quote.diagnostics, key=lambda item: item.diagnostic_id):
                if diagnostic.diagnostic_id in diagnostic_ids:
                    raise ManifestError("a branch cannot count one diagnostic occurrence twice")
                diagnostic_ids.add(diagnostic.diagnostic_id)
                diagnostics.append(diagnostic)
            state = _state_after(action_kind, state)
            states.append(state)

    pre_liquidation = _frozen_balances(balances)
    pre_liquidation_basis = _basis_projection(
        episode.subject_asset_id, balances.get(episode.subject_asset_id, 0), basis
    )
    liquidation_legs: list[LiquidationLeg] = []
    residual_assets: list[str] = []
    numeraire = episode.numeraire_asset_id
    for asset_id in sorted(balances):
        quantity = balances[asset_id]
        if asset_id == numeraire or quantity == 0:
            continue
        candidates = []
        for quote in episode.terminal_manifest.quotes:
            deltas = delta_map(quote.balance_deltas, "terminal quote balance_deltas")
            if (
                quote.terminal_asset_id == asset_id
                and _preconditions_match(quote, balances)
                and (
                    quote.status is QuoteStatus.REFUSED
                    or (
                        deltas.get(asset_id) == -quantity
                        and all(changed in {asset_id, numeraire} for changed in deltas)
                    )
                )
            ):
                candidates.append(quote)
        if len(candidates) != 1 or candidates[0].status is QuoteStatus.REFUSED:
            quote = candidates[0] if len(candidates) == 1 else None
            reason = (
                quote.refusal_reason
                if quote is not None and quote.refusal_reason
                else "no unique exact whole-position terminal route"
            )
            liquidation_legs.append(
                LiquidationLeg(
                    asset_id,
                    quantity,
                    quote.quote_id if quote else None,
                    "unknown",
                    None,
                    None,
                    None,
                    reason,
                )
            )
            residual_assets.append(asset_id)
            uncertainties.append(
                UncertaintyRecord(
                    uncertainty_id=_record_id(
                        "shadow-uncertainty",
                        {"asset_id": asset_id, "quantity": str(quantity), "reason": reason},
                    ),
                    kind="terminal_liquidation_unknown",
                    point_id=None,
                    reason=reason,
                    gap_ids=(),
                )
            )
            continue
        quote = candidates[0]
        before_numeraire = balances.get(numeraire, 0)
        mapped_deltas = delta_map(quote.balance_deltas, "terminal quote balance_deltas")
        subject_before = balances.get(episode.subject_asset_id, 0)
        for changed_asset, atoms in mapped_deltas.items():
            balances[changed_asset] = balances.get(changed_asset, 0) + atoms
        allocated, _, realized = _advance_basis(
            tracker=basis,
            subject_before=subject_before,
            subject_after=balances.get(episode.subject_asset_id, 0),
            subject_delta=mapped_deltas.get(episode.subject_asset_id, 0),
            numeraire_delta=mapped_deltas.get(numeraire, 0),
            numeraire_changed=numeraire in mapped_deltas,
        )
        liquidation_legs.append(
            LiquidationLeg(
                asset_id,
                quantity,
                quote.quote_id,
                "projected",
                balances.get(numeraire, 0) - before_numeraire,
                allocated,
                realized,
                None,
            )
        )
    terminal_balances = _frozen_balances(balances)
    terminal_basis = _basis_projection(
        episode.subject_asset_id, balances.get(episode.subject_asset_id, 0), basis
    )
    if residual_assets:
        status = BranchStatus.TERMINAL_VALUE_UNKNOWN
        terminal_wealth = None
        net_pnl = None
    else:
        terminal_wealth = balances.get(numeraire, 0)
        net_pnl = terminal_wealth - episode.starting_valuation.total_numeraire_atoms
        status = BranchStatus.COMPLETE_WITH_REFUSALS if refusals else BranchStatus.COMPLETE
    provisional = BranchResult(
        branch_id="pending-content-identity",
        policy_id=policy.policy_id,
        policy_family=policy.family,
        policy_digest=policy.digest,
        common_information_digest=episode.digest,
        status=status,
        actions=tuple(actions),
        executions=tuple(executions),
        effects=tuple(effects),
        refusals=tuple(refusals),
        uncertainties=tuple(uncertainties),
        diagnostics=tuple(diagnostics),
        pre_liquidation_balances=pre_liquidation,
        pre_liquidation_subject_basis=pre_liquidation_basis,
        liquidation_legs=tuple(liquidation_legs),
        terminal_balances=terminal_balances,
        terminal_subject_basis=terminal_basis,
        starting_value_numeraire_atoms=episode.starting_valuation.total_numeraire_atoms,
        terminal_wealth_numeraire_atoms=terminal_wealth,
        net_pnl_numeraire_atoms=net_pnl,
        episode_states=tuple(states),
    )
    branch_payload = provisional.as_dict()
    branch_payload.pop("branch_id")
    return replace(
        provisional,
        branch_id=_record_id("shadow-branch", branch_payload),
    )


def _opportunity_comparisons(
    plan: ArenaPlan, branches: tuple[BranchResult, ...]
) -> tuple[OpportunityComparison, ...]:
    by_policy = {branch.policy_id: branch for branch in branches}
    baseline = by_policy[plan.opportunity_baseline_policy_id]
    comparisons: list[OpportunityComparison] = []
    for candidate in branches:
        if (
            baseline.terminal_wealth_numeraire_atoms is None
            or candidate.terminal_wealth_numeraire_atoms is None
        ):
            comparison = OpportunityComparison(
                "pending-content-identity",
                baseline.policy_id,
                candidate.policy_id,
                "unknown",
                None,
                None,
                "one or both branches lack complete terminal liquidation",
            )
            content = {"plan_digest": plan.digest, **comparison.as_dict()}
            content.pop("comparison_id")
            comparisons.append(
                replace(comparison, comparison_id=_record_id("shadow-opportunity", content))
            )
            continue
        opportunity_cost = (
            baseline.terminal_wealth_numeraire_atoms
            - candidate.terminal_wealth_numeraire_atoms
        )
        comparison = OpportunityComparison(
            "pending-content-identity",
            baseline.policy_id,
            candidate.policy_id,
            "known",
            opportunity_cost,
            -opportunity_cost,
            None,
        )
        content = {"plan_digest": plan.digest, **comparison.as_dict()}
        content.pop("comparison_id")
        comparisons.append(
            replace(comparison, comparison_id=_record_id("shadow-opportunity", content))
        )
    return tuple(comparisons)


def evaluate_arena(plan: ArenaPlan) -> ArenaArtifact:
    """Evaluate frozen policy branches over one exact, shared, chronological episode tape.

    This function is pure and read-only. It consumes no provider, wallet, signer, submission path,
    random state, or wall clock. All executions and effects in the result are explicitly
    hypothetical.
    """

    plan.validate()
    branches = tuple(
        _evaluate_branch(plan, policy)
        for policy in sorted(plan.policies, key=lambda item: item.policy_id)
    )
    common = {branch.common_information_digest for branch in branches}
    if common != {plan.episode.digest}:
        raise ManifestError("policy branches did not retain a common information closure")
    comparisons = _opportunity_comparisons(plan, branches)
    payload = {
        "schema_id": SCHEMA_ID,
        "calculator_version": CALCULATOR_VERSION,
        "plan_id": plan.plan_id,
        "plan_digest": plan.digest,
        "episode_id": plan.episode.episode_id,
        "common_information_digest": plan.episode.digest,
        "branches": [branch.as_dict() for branch in branches],
        "opportunity_comparisons": [item.as_dict() for item in comparisons],
        "claims": [
            "conditional_shadow_comparison_only",
            "common_information_chronological_replay",
            "terminal_liquidated_when_fully_quotable",
        ],
        "explicit_non_claims": [
            "profitability_generalization",
            "causal_policy_value",
            "fill",
            "landing",
            "live_authority",
        ],
        "accounting_identity": ACCOUNTING_IDENTITY,
        "authority": AUTHORITY,
    }
    return ArenaArtifact(
        artifact_id=_content_id("shadow-arena", payload),
        artifact_digest=qualified_sha256_bytes(canonical_json_bytes(payload)),
        plan_id=plan.plan_id,
        plan_digest=plan.digest,
        episode_id=plan.episode.episode_id,
        common_information_digest=plan.episode.digest,
        branches=branches,
        opportunity_comparisons=comparisons,
    )


def diagnostic_is_posting(diagnostic: EconomicDiagnostic) -> bool:
    """Expose the accounting classification without ever applying a diagnostic to wealth."""

    diagnostic.validate()
    return diagnostic.treatment is AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT


def epistemic_registry() -> tuple[str, ...]:
    return tuple(kind.value for kind in EpistemicKind)
