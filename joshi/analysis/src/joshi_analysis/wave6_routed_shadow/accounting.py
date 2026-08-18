"""Terminal liquidation, branch surplus, and non-ledger diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .arithmetic import atoms
from .contracts import Direction, ShadowRun


class LiquidationStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class LiquidationQuote:
    """A full-size executable quote assumption for one exact terminal asset amount."""

    quote_id: str
    asset_id: str
    input_atoms: int
    numeraire_id: str
    expected_output_atoms: int
    irreversible_cost_atoms: int
    available: bool = True

    def __post_init__(self) -> None:
        for name in ("input_atoms", "expected_output_atoms", "irreversible_cost_atoms"):
            atoms(getattr(self, name), name=name)
        if self.irreversible_cost_atoms > self.expected_output_atoms:
            raise ValueError("liquidation cost cannot exceed expected output")


@dataclass(frozen=True, slots=True)
class LiquidationResidual:
    asset_id: str
    atoms: int
    reason: str


@dataclass(frozen=True, slots=True)
class TerminalLiquidation:
    manifest_id: str
    numeraire_id: str
    status: LiquidationStatus
    total_numeraire_atoms: int | None
    component_numeraire_atoms: tuple[tuple[str, int], ...]
    residuals: tuple[LiquidationResidual, ...]
    claim_scope: str = "terminal_size_specific_quote_projection_not_landed_proceeds"


def terminal_liquidate(
    *,
    manifest_id: str,
    numeraire_id: str,
    inventory: tuple[tuple[str, int], ...],
    quotes: tuple[LiquidationQuote, ...],
) -> TerminalLiquidation:
    """Value every nonzero asset through an exact full-position quote or remain partial."""

    if len({asset_id for asset_id, _ in inventory}) != len(inventory):
        raise ValueError("terminal inventory contains duplicate asset identities")
    quote_by_asset = {item.asset_id: item for item in quotes}
    if len(quote_by_asset) != len(quotes):
        raise ValueError("terminal quote identities must be unique by asset")
    components: list[tuple[str, int]] = []
    residuals: list[LiquidationResidual] = []
    for asset_id, amount in inventory:
        atoms(amount, name=f"terminal {asset_id}")
        if amount == 0:
            continue
        if asset_id == numeraire_id:
            components.append((asset_id, amount))
            continue
        quote = quote_by_asset.get(asset_id)
        if quote is None:
            residuals.append(LiquidationResidual(asset_id, amount, "missing_full_size_quote"))
            continue
        if quote.numeraire_id != numeraire_id:
            residuals.append(LiquidationResidual(asset_id, amount, "wrong_numeraire"))
            continue
        if quote.input_atoms != amount:
            residuals.append(LiquidationResidual(asset_id, amount, "quote_size_mismatch"))
            continue
        if not quote.available:
            residuals.append(LiquidationResidual(asset_id, amount, "route_unavailable"))
            continue
        components.append(
            (asset_id, quote.expected_output_atoms - quote.irreversible_cost_atoms)
        )
    status = LiquidationStatus.PARTIAL if residuals else LiquidationStatus.COMPLETE
    total = None if residuals else sum(value for _, value in components)
    if total is not None:
        atoms(total, name="terminal liquidation value")
    return TerminalLiquidation(
        manifest_id=manifest_id,
        numeraire_id=numeraire_id,
        status=status,
        total_numeraire_atoms=total,
        component_numeraire_atoms=tuple(components),
        residuals=tuple(residuals),
    )


@dataclass(frozen=True, slots=True)
class BranchScore:
    branch_id: str
    terminal: TerminalLiquidation
    external_contributions_atoms: int
    external_distributions_atoms: int
    score_atoms: int | None


def score_branch(
    branch_id: str,
    terminal: TerminalLiquidation,
    *,
    external_contributions_atoms: int = 0,
    external_distributions_atoms: int = 0,
) -> BranchScore:
    atoms(external_contributions_atoms, name="external contributions")
    atoms(external_distributions_atoms, name="external distributions")
    score = (
        None
        if terminal.total_numeraire_atoms is None
        else terminal.total_numeraire_atoms
        - external_contributions_atoms
        + external_distributions_atoms
    )
    return BranchScore(
        branch_id,
        terminal,
        external_contributions_atoms,
        external_distributions_atoms,
        score,
    )


@dataclass(frozen=True, slots=True)
class JointBranchSurplus:
    joint_branch_id: str
    alternative_branch_id: str
    numeraire_id: str
    surplus_atoms: int | None
    reason: str | None
    claim_scope: str = "terminal_branch_difference_not_actual_pnl_or_future_expected_value"


def joint_branch_surplus(joint: BranchScore, alternative: BranchScore) -> JointBranchSurplus:
    """Compute the authoritative signed terminal branch difference when both are complete."""

    if joint.terminal.numeraire_id != alternative.terminal.numeraire_id:
        raise ValueError("branches must use the same numeraire")
    if joint.terminal.manifest_id != alternative.terminal.manifest_id:
        raise ValueError("branches must share one terminal liquidation manifest")
    if joint.score_atoms is None or alternative.score_atoms is None:
        return JointBranchSurplus(
            joint.branch_id,
            alternative.branch_id,
            joint.terminal.numeraire_id,
            None,
            "partial_terminal_liquidation",
        )
    return JointBranchSurplus(
        joint.branch_id,
        alternative.branch_id,
        joint.terminal.numeraire_id,
        joint.score_atoms - alternative.score_atoms,
        None,
    )


@dataclass(frozen=True, slots=True)
class ToxicityDiagnostic:
    intent_id: str
    direction: Direction
    horizon_id: str
    output_asset_id: str
    contemporaneous_reference_output_atoms: int
    horizon_reference_output_atoms: int
    toxicity_atoms: int
    interpretation: str = "positive_is_post_fill_move_in_trader_direction"


def toxicity_diagnostic(
    *,
    intent_id: str,
    direction: Direction,
    horizon_id: str,
    output_asset_id: str,
    contemporaneous_reference_output_atoms: int,
    horizon_reference_output_atoms: int,
) -> ToxicityDiagnostic:
    atoms(contemporaneous_reference_output_atoms, name="contemporaneous reference output")
    atoms(horizon_reference_output_atoms, name="horizon reference output")
    return ToxicityDiagnostic(
        intent_id,
        direction,
        horizon_id,
        output_asset_id,
        contemporaneous_reference_output_atoms,
        horizon_reference_output_atoms,
        horizon_reference_output_atoms - contemporaneous_reference_output_atoms,
    )


@dataclass(frozen=True, slots=True)
class InventoryTransferRegret:
    intent_id: str
    output_asset_id: str
    principal_output_atoms: int
    external_alternative_output_atoms: int
    regret_atoms: int
    claim_scope: str = "fill_time_execution_counterfactual_not_accounting_pnl"


def inventory_transfer_regret(
    intent_id: str,
    output_asset_id: str,
    *,
    principal_output_atoms: int,
    external_alternative_output_atoms: int,
) -> InventoryTransferRegret:
    atoms(principal_output_atoms, name="principal output")
    atoms(external_alternative_output_atoms, name="external alternative output")
    return InventoryTransferRegret(
        intent_id,
        output_asset_id,
        principal_output_atoms,
        external_alternative_output_atoms,
        external_alternative_output_atoms - principal_output_atoms,
    )


@dataclass(frozen=True, slots=True)
class LvrLikeDiagnostic:
    estimator_id: str
    passive_branch_id: str
    rebalancing_branch_id: str
    numeraire_id: str
    value_atoms: int | None
    reason: str | None
    claim_scope: str = "discrete_registered_rebalancing_diagnostic_not_accounting_pnl"


def lvr_like_diagnostic(
    estimator_id: str,
    passive: BranchScore,
    rebalancing: BranchScore,
) -> LvrLikeDiagnostic:
    if passive.terminal.manifest_id != rebalancing.terminal.manifest_id:
        raise ValueError("LVR-like branches must share a terminal manifest")
    if passive.terminal.numeraire_id != rebalancing.terminal.numeraire_id:
        raise ValueError("LVR-like branches must share a numeraire")
    if passive.score_atoms is None or rebalancing.score_atoms is None:
        value = None
        reason = "partial_terminal_liquidation"
    else:
        value = rebalancing.score_atoms - passive.score_atoms
        reason = None
    return LvrLikeDiagnostic(
        estimator_id,
        passive.branch_id,
        rebalancing.branch_id,
        passive.terminal.numeraire_id,
        value,
        reason,
    )


class Falsifier(StrEnum):
    INCOMPLETE_ROUTE_UNIVERSE = "incomplete_route_universe"
    ROUNDING_ONLY_ACTIVATION = "rounding_only_activation"
    SEQUENTIAL_DEPLETION = "sequential_depletion"
    TERMINAL_LIQUIDATION_PARTIAL = "terminal_liquidation_partial"
    SCENARIO_SIGN_INSTABILITY = "scenario_sign_instability"


@dataclass(frozen=True, slots=True)
class FalsifierReport:
    triggered: tuple[Falsifier, ...]
    claim_scope: str = "adversarial_screen_not_statistical_test"


def assess_falsifiers(
    run: ShadowRun,
    terminal: TerminalLiquidation,
    *,
    economically_relevant_min_input_atoms: int,
) -> FalsifierReport:
    atoms(economically_relevant_min_input_atoms, name="economic minimum")
    triggered: list[Falsifier] = []
    if any(
        event.decision.ghost_selected and not event.intent.jupiter.universe_complete
        for event in run.events
    ):
        triggered.append(Falsifier.INCOMPLETE_ROUTE_UNIVERSE)
    selected = [event for event in run.events if event.decision.ghost_selected]
    if selected and all(
        event.intent.input_atoms < economically_relevant_min_input_atoms for event in selected
    ):
        triggered.append(Falsifier.ROUNDING_ONLY_ACTIVATION)
    seen_activation = False
    depleted = False
    for event in run.events:
        seen_activation = seen_activation or event.decision.ghost_selected
        if (
            seen_activation
            and getattr(event.ghost_would_quote.outcome, "reason", None)
            == "insufficient_finite_capacity"
        ):
            depleted = True
    if depleted:
        triggered.append(Falsifier.SEQUENTIAL_DEPLETION)
    if terminal.status is LiquidationStatus.PARTIAL:
        triggered.append(Falsifier.TERMINAL_LIQUIDATION_PARTIAL)
    return FalsifierReport(tuple(triggered))


def assess_scenario_signs(results: tuple[JointBranchSurplus, ...]) -> FalsifierReport:
    """Flag a result whose sign reverses across registered ordering/repricing scenarios."""

    signs = {
        (item.surplus_atoms > 0) - (item.surplus_atoms < 0)
        for item in results
        if item.surplus_atoms is not None
    }
    triggered = (Falsifier.SCENARIO_SIGN_INSTABILITY,) if 1 in signs and -1 in signs else ()
    return FalsifierReport(triggered)
