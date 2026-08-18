"""Terminal liquidation, branch surplus, and non-ledger diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .arithmetic import atoms, digest
from .contracts import (
    AdverseSelectionAttribution,
    Direction,
    RouteDecisionStatus,
    ShadowRun,
)


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
        if not self.quote_id or not self.asset_id or not self.numeraire_id:
            raise ValueError("liquidation quote identities are required")
        if self.asset_id == self.numeraire_id:
            raise ValueError("numeraire holdings do not require a liquidation quote")
        for name in ("input_atoms", "expected_output_atoms", "irreversible_cost_atoms"):
            atoms(getattr(self, name), name=name)
        if self.input_atoms == 0:
            raise ValueError("a liquidation quote must bind a positive full-position size")
        if self.irreversible_cost_atoms > self.expected_output_atoms:
            raise ValueError("liquidation cost cannot exceed expected output")


@dataclass(frozen=True, slots=True)
class LiquidationManifest:
    """Complete common-horizon/profile quote universe used by every compared branch."""

    manifest_id: str
    horizon_id: str
    profile_id: str
    numeraire_id: str
    quotes: tuple[LiquidationQuote, ...]

    def __post_init__(self) -> None:
        if (
            not self.manifest_id
            or not self.horizon_id
            or not self.profile_id
            or not self.numeraire_id
        ):
            raise ValueError("terminal manifest identities are required")
        quote_ids = [quote.quote_id for quote in self.quotes]
        if len(quote_ids) != len(set(quote_ids)):
            raise ValueError("terminal quote occurrence ids must be unique")
        quote_keys = [(quote.asset_id, quote.input_atoms) for quote in self.quotes]
        if len(quote_keys) != len(set(quote_keys)):
            raise ValueError("terminal asset/size quote keys must be unique")
        ordered = tuple(
            sorted(
                self.quotes,
                key=lambda quote: (quote.asset_id, quote.input_atoms, quote.quote_id),
            )
        )
        if self.quotes != ordered:
            raise ValueError("terminal quotes must be canonically ordered by asset, size, and id")
        if any(quote.numeraire_id != self.numeraire_id for quote in self.quotes):
            raise ValueError("every terminal quote must use the manifest numeraire")

    @property
    def content_digest(self) -> str:
        """Recompute identity from content; the caller's manifest label is excluded."""

        return digest(
            {
                "contract": "joshi.wave6.routed-liquidation-manifest/v2",
                "horizon_id": self.horizon_id,
                "profile_id": self.profile_id,
                "numeraire_id": self.numeraire_id,
                "quotes": self.quotes,
            }
        )


@dataclass(frozen=True, slots=True)
class LiquidationResidual:
    asset_id: str
    atoms: int
    reason: str

    def __post_init__(self) -> None:
        atoms(self.atoms, name="liquidation residual")


@dataclass(frozen=True, slots=True)
class TerminalLiquidation:
    manifest: LiquidationManifest
    inventory: tuple[tuple[str, int], ...]
    status: LiquidationStatus
    total_numeraire_atoms: int | None
    component_numeraire_atoms: tuple[tuple[str, int], ...]
    residuals: tuple[LiquidationResidual, ...]
    claim_scope: str = "terminal_size_specific_quote_projection_not_landed_proceeds"

    def __post_init__(self) -> None:
        inventory_assets = [asset_id for asset_id, _ in self.inventory]
        if len(inventory_assets) != len(set(inventory_assets)):
            raise ValueError("terminal inventory asset identities must be unique")
        for asset_id, amount in self.inventory:
            if not asset_id:
                raise ValueError("terminal inventory asset identity is required")
            atoms(amount, name=f"terminal {asset_id}")
        component_assets = [asset_id for asset_id, _ in self.component_numeraire_atoms]
        if len(component_assets) != len(set(component_assets)):
            raise ValueError("terminal component asset identities must be unique")
        for _, value in self.component_numeraire_atoms:
            atoms(value, name="terminal component")
        if self.status is LiquidationStatus.COMPLETE:
            if self.total_numeraire_atoms is None or self.residuals:
                raise ValueError("complete liquidation requires a scalar and no residuals")
            atoms(self.total_numeraire_atoms, name="terminal liquidation value")
            if self.total_numeraire_atoms != sum(
                value for _, value in self.component_numeraire_atoms
            ):
                raise ValueError("terminal scalar must reconcile to its components")
        elif self.total_numeraire_atoms is not None or not self.residuals:
            raise ValueError("partial liquidation requires residuals and no scalar")

    @property
    def manifest_id(self) -> str:
        return self.manifest.manifest_id

    @property
    def manifest_content_digest(self) -> str:
        return self.manifest.content_digest

    @property
    def numeraire_id(self) -> str:
        return self.manifest.numeraire_id

    @property
    def content_digest(self) -> str:
        return digest(
            {
                "contract": "joshi.wave6.routed-terminal-liquidation/v2",
                "manifest_content_digest": self.manifest.content_digest,
                "inventory": self.inventory,
                "status": self.status,
                "total_numeraire_atoms": self.total_numeraire_atoms,
                "component_numeraire_atoms": self.component_numeraire_atoms,
                "residuals": self.residuals,
            }
        )


def terminal_liquidate(
    *,
    manifest: LiquidationManifest,
    inventory: tuple[tuple[str, int], ...],
) -> TerminalLiquidation:
    """Value every nonzero asset through an exact full-position quote or remain partial."""

    if len({asset_id for asset_id, _ in inventory}) != len(inventory):
        raise ValueError("terminal inventory contains duplicate asset identities")
    quote_by_key = {(item.asset_id, item.input_atoms): item for item in manifest.quotes}
    quoted_assets = {item.asset_id for item in manifest.quotes}
    components: list[tuple[str, int]] = []
    residuals: list[LiquidationResidual] = []
    for asset_id, amount in inventory:
        atoms(amount, name=f"terminal {asset_id}")
        if amount == 0:
            continue
        if asset_id == manifest.numeraire_id:
            components.append((asset_id, amount))
            continue
        quote = quote_by_key.get((asset_id, amount))
        if quote is None:
            reason = (
                "quote_size_mismatch" if asset_id in quoted_assets else "missing_full_size_quote"
            )
            residuals.append(LiquidationResidual(asset_id, amount, reason))
            continue
        if not quote.available:
            residuals.append(LiquidationResidual(asset_id, amount, "route_unavailable"))
            continue
        if quote.expected_output_atoms <= quote.irreversible_cost_atoms:
            residuals.append(LiquidationResidual(asset_id, amount, "nonpositive_net_output"))
            continue
        components.append((asset_id, quote.expected_output_atoms - quote.irreversible_cost_atoms))
    status = LiquidationStatus.PARTIAL if residuals else LiquidationStatus.COMPLETE
    total = None if residuals else sum(value for _, value in components)
    if total is not None:
        atoms(total, name="terminal liquidation value")
    return TerminalLiquidation(
        manifest=manifest,
        inventory=inventory,
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

    def __post_init__(self) -> None:
        atoms(self.external_contributions_atoms, name="external contributions")
        atoms(self.external_distributions_atoms, name="external distributions")
        expected = (
            None
            if self.terminal.total_numeraire_atoms is None
            else self.terminal.total_numeraire_atoms
            - self.external_contributions_atoms
            + self.external_distributions_atoms
        )
        if self.score_atoms != expected:
            raise ValueError("branch score must reconcile to terminal value and external flows")


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
    if joint.terminal.manifest_content_digest != alternative.terminal.manifest_content_digest:
        raise ValueError("branches must share byte-identical terminal manifest content")
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
    scenario_id: str
    scenario_content_digest: str
    run_registration_digest: str
    intent_id: str
    output_asset_id: str
    principal_output_atoms: int
    external_alternative_output_atoms: int
    regret_atoms: int
    diagnostic_kind: AdverseSelectionAttribution = field(
        init=False,
        default=AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET,
    )
    claim_scope: str = "fill_time_execution_counterfactual_not_accounting_pnl"

    def __post_init__(self) -> None:
        if (
            not self.scenario_id
            or not self.scenario_content_digest
            or not self.run_registration_digest
            or not self.intent_id
            or not self.output_asset_id
        ):
            raise ValueError("ITR diagnostic identities and content bindings are required")
        atoms(self.principal_output_atoms, name="principal output")
        atoms(self.external_alternative_output_atoms, name="external alternative output")
        if self.regret_atoms != (
            self.external_alternative_output_atoms - self.principal_output_atoms
        ):
            raise ValueError("ITR diagnostic must reconcile to its exact output amounts")
        if isinstance(self.regret_atoms, bool) or not isinstance(self.regret_atoms, int):
            raise ValueError("ITR regret must be signed integer atoms")


def inventory_transfer_regret(
    run: ShadowRun,
    intent_id: str,
    output_asset_id: str,
    *,
    principal_output_atoms: int,
    external_alternative_output_atoms: int,
) -> InventoryTransferRegret:
    if (
        run.scenario.adverse_selection_attribution
        is not AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET
    ):
        raise ValueError("run did not freeze inventory-transfer regret attribution")
    atoms(principal_output_atoms, name="principal output")
    atoms(external_alternative_output_atoms, name="external alternative output")
    return InventoryTransferRegret(
        run.scenario.scenario_id,
        run.scenario.content_digest,
        run.registration_digest,
        intent_id,
        output_asset_id,
        principal_output_atoms,
        external_alternative_output_atoms,
        external_alternative_output_atoms - principal_output_atoms,
    )


@dataclass(frozen=True, slots=True)
class LvrLikeDiagnostic:
    scenario_id: str
    scenario_content_digest: str
    run_registration_digest: str
    estimator_id: str
    passive_branch_id: str
    rebalancing_branch_id: str
    numeraire_id: str
    value_atoms: int | None
    reason: str | None
    diagnostic_kind: AdverseSelectionAttribution = field(
        init=False,
        default=AdverseSelectionAttribution.LVR_LIKE,
    )
    claim_scope: str = "discrete_registered_rebalancing_diagnostic_not_accounting_pnl"

    def __post_init__(self) -> None:
        if (
            not self.scenario_id
            or not self.scenario_content_digest
            or not self.run_registration_digest
            or not self.estimator_id
            or not self.passive_branch_id
            or not self.rebalancing_branch_id
            or not self.numeraire_id
        ):
            raise ValueError("LVR-like diagnostic identities and content bindings are required")
        if self.value_atoms is None:
            if self.reason is None:
                raise ValueError("an unknown LVR-like value requires a reason")
        elif self.reason is not None:
            raise ValueError("a numeric LVR-like value cannot carry an unknown reason")
        elif isinstance(self.value_atoms, bool) or not isinstance(self.value_atoms, int):
            raise ValueError("LVR-like value must be signed integer atoms")


def lvr_like_diagnostic(
    run: ShadowRun,
    estimator_id: str,
    passive: BranchScore,
    rebalancing: BranchScore,
) -> LvrLikeDiagnostic:
    if run.scenario.adverse_selection_attribution is not AdverseSelectionAttribution.LVR_LIKE:
        raise ValueError("run did not freeze LVR-like attribution")
    if passive.terminal.manifest_content_digest != rebalancing.terminal.manifest_content_digest:
        raise ValueError("LVR-like branches must share byte-identical terminal manifest content")
    if passive.terminal.numeraire_id != rebalancing.terminal.numeraire_id:
        raise ValueError("LVR-like branches must share a numeraire")
    if passive.score_atoms is None or rebalancing.score_atoms is None:
        value = None
        reason = "partial_terminal_liquidation"
    else:
        value = rebalancing.score_atoms - passive.score_atoms
        reason = None
    return LvrLikeDiagnostic(
        run.scenario.scenario_id,
        run.scenario.content_digest,
        run.registration_digest,
        estimator_id,
        passive.branch_id,
        rebalancing.branch_id,
        passive.terminal.numeraire_id,
        value,
        reason,
    )


@dataclass(frozen=True, slots=True)
class AdverseSelectionAudit:
    scenario_id: str
    scenario_content_digest: str
    run_registration_digest: str
    attribution: AdverseSelectionAttribution
    inventory_transfer_regret: InventoryTransferRegret | None
    lvr_like: LvrLikeDiagnostic | None
    claim_scope: str = "one_frozen_nonposting_adverse_selection_attribution"


def audit_adverse_selection(
    run: ShadowRun,
    *,
    itr: InventoryTransferRegret | None = None,
    lvr: LvrLikeDiagnostic | None = None,
) -> AdverseSelectionAudit:
    """Require exactly the diagnostic family frozen by the run, never both or neither."""

    attribution = run.scenario.adverse_selection_attribution
    scenario_content_digest = run.scenario.content_digest
    run_registration_digest = run.registration_digest
    if itr is not None and (
        type(itr) is not InventoryTransferRegret
        or itr.diagnostic_kind is not AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET
    ):
        raise TypeError("ITR slot requires an exact inventory-transfer-regret diagnostic")
    if lvr is not None and (
        type(lvr) is not LvrLikeDiagnostic
        or lvr.diagnostic_kind is not AdverseSelectionAttribution.LVR_LIKE
    ):
        raise TypeError("LVR slot requires an exact LVR-like diagnostic")
    if attribution is AdverseSelectionAttribution.NONE:
        if itr is not None or lvr is not None:
            raise ValueError("a no-attribution run cannot attach ITR or LVR-like diagnostics")
    elif attribution is AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET:
        if itr is None or lvr is not None:
            raise ValueError("ITR-attributed run requires exactly one ITR diagnostic")
    elif lvr is None or itr is not None:
        raise ValueError("LVR-attributed run requires exactly one LVR-like diagnostic")
    if itr is not None:
        if itr.scenario_id != run.scenario.scenario_id:
            raise ValueError("ITR diagnostic belongs to a different scenario label")
        if itr.scenario_content_digest != scenario_content_digest:
            raise ValueError("ITR diagnostic belongs to different scenario content")
        if itr.run_registration_digest != run_registration_digest:
            raise ValueError("ITR diagnostic belongs to a different registered run")
    if lvr is not None:
        if lvr.scenario_id != run.scenario.scenario_id:
            raise ValueError("LVR-like diagnostic belongs to a different scenario label")
        if lvr.scenario_content_digest != scenario_content_digest:
            raise ValueError("LVR-like diagnostic belongs to different scenario content")
        if lvr.run_registration_digest != run_registration_digest:
            raise ValueError("LVR-like diagnostic belongs to a different registered run")
    return AdverseSelectionAudit(
        run.scenario.scenario_id,
        scenario_content_digest,
        run_registration_digest,
        attribution,
        itr,
        lvr,
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
    incomplete_statuses = {
        RouteDecisionStatus.UNKNOWN_INCOMPLETE_UNIVERSE,
        RouteDecisionStatus.UNKNOWN_MISSING_CANDIDATE,
    }
    if any(event.decision.status in incomplete_statuses for event in run.events):
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
