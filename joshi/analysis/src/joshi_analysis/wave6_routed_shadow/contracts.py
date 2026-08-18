"""Immutable evidence, counterfactual, and accounting contracts for Wave 6."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .arithmetic import FEE_PRECISION, atoms, digest


class Direction(StrEnum):
    X_TO_Y = "x_to_y"
    Y_TO_X = "y_to_x"

    def reverse(self) -> Direction:
        return Direction.Y_TO_X if self is Direction.X_TO_Y else Direction.X_TO_Y


class FlowOrigin(StrEnum):
    EXTERNAL = "external"
    HOUSEHOLD = "household_self_routed"


class Coverage(StrEnum):
    OBSERVED_COMPLETE = "observed_complete"
    OBSERVED_PARTIAL = "observed_partial"
    SOURCE_GAP = "source_gap"
    STALE = "stale"
    UNSUPPORTED_PROFILE = "unsupported_profile"


class ExternalStateTreatment(StrEnum):
    COUPLED_COPIED_STATE = "coupled_copied_state"
    FIXED_WITNESSED_STATE = "fixed_witnessed_state"


class ArbitrageOrdering(StrEnum):
    BEFORE_REQUEST = "before_request"
    AFTER_REQUEST = "after_request"


@dataclass(frozen=True, slots=True)
class SourceCut:
    """Exact source/profile/topology cut shared by state, router witness, and quote."""

    cut_id: str
    slot: int
    profile_id: str
    topology_epoch: str

    def __post_init__(self) -> None:
        if not self.cut_id or not self.profile_id or not self.topology_epoch:
            raise ValueError("source cut identities are required")
        atoms(self.slot, name="source cut slot")


class RouteDecisionStatus(StrEnum):
    MODELED_SELECTION = "modeled_selection"
    UNKNOWN_INCOMPLETE_UNIVERSE = "unknown_incomplete_universe"
    UNKNOWN_MISSING_CANDIDATE = "unknown_missing_candidate"
    UNKNOWN_NO_COMPARABLE_BASELINE = "unknown_no_comparable_baseline"
    UNKNOWN_INCOMPATIBLE_SOURCE_CUT = "unknown_incompatible_source_cut"


class AdverseSelectionAttribution(StrEnum):
    NONE = "none"
    INVENTORY_TRANSFER_REGRET = "inventory_transfer_regret"
    LVR_LIKE = "lvr_like"


@dataclass(frozen=True, slots=True)
class FeeComponent:
    owner: str
    asset_id: str
    atoms: int

    def __post_init__(self) -> None:
        atoms(self.atoms, name="fee atoms")


@dataclass(frozen=True, slots=True)
class QuoteLeg:
    segment_id: str
    input_atoms: int
    output_atoms: int

    def __post_init__(self) -> None:
        atoms(self.input_atoms, name="leg input")
        atoms(self.output_atoms, name="leg output")


@dataclass(frozen=True, slots=True)
class ExactQuote:
    venue_id: str
    state_id: str
    input_asset: str
    output_asset: str
    input_atoms: int
    trade_input_atoms: int
    output_atoms: int
    fees: tuple[FeeComponent, ...]
    legs: tuple[QuoteLeg, ...]
    pre_state_digest: str

    def __post_init__(self) -> None:
        atoms(self.input_atoms, name="quote input")
        atoms(self.trade_input_atoms, name="quote trade input")
        atoms(self.output_atoms, name="quote output")
        if self.trade_input_atoms > self.input_atoms:
            raise ValueError("trade input cannot exceed gross input")
        if not self.input_asset or not self.output_asset or self.input_asset == self.output_asset:
            raise ValueError("a quote requires two distinct asset identities")
        if sum(component.atoms for component in self.fees) != (
            self.input_atoms - self.trade_input_atoms
        ):
            raise ValueError("fee components must reconcile to gross less trade input")
        if not self.legs:
            raise ValueError("a successful quote requires at least one exact leg")
        if len({leg.segment_id for leg in self.legs}) != len(self.legs):
            raise ValueError("quote leg identities must be unique")
        if sum(leg.input_atoms for leg in self.legs) != self.trade_input_atoms:
            raise ValueError("quote leg inputs must reconcile to trade input")
        if sum(leg.output_atoms for leg in self.legs) != self.output_atoms:
            raise ValueError("quote leg outputs must reconcile to quote output")


@dataclass(frozen=True, slots=True)
class QuoteRefusal:
    venue_id: str
    state_id: str
    reason: str


QuoteOutcome = ExactQuote | QuoteRefusal


@dataclass(frozen=True, slots=True)
class VenueQuote:
    """Quote from an observed venue state; it is neither route selection nor fill."""

    observation_id: str
    slot: int
    source_cut: SourceCut
    outcome: QuoteOutcome
    coverage: Coverage

    def __post_init__(self) -> None:
        atoms(self.slot, name="venue quote slot")
        if self.slot != self.source_cut.slot:
            raise ValueError("venue quote slot must come from its exact source cut")


@dataclass(frozen=True, slots=True)
class WouldQuote:
    """Hypothetical edge calculation, explicitly below the observed-quote layer."""

    schedule_id: str
    source_cut: SourceCut
    outcome: QuoteOutcome
    claim_scope: str = "mechanical_would_quote_not_observed_route_or_fill"


@dataclass(frozen=True, slots=True)
class JupiterWitness:
    """A retained router response, not a reconstruction from landed chain data."""

    witness_id: str
    slot: int
    source_cut: SourceCut
    candidate_venue_ids: tuple[str, ...]
    routed_venue_ids: tuple[str, ...]
    universe_complete: bool
    coverage: Coverage

    def __post_init__(self) -> None:
        atoms(self.slot, name="Jupiter witness slot")
        if self.slot != self.source_cut.slot:
            raise ValueError("Jupiter slot must equal its exact source-cut slot")
        if len(set(self.candidate_venue_ids)) != len(self.candidate_venue_ids):
            raise ValueError("Jupiter candidates must be unique")
        if not set(self.routed_venue_ids).issubset(self.candidate_venue_ids):
            raise ValueError("a routed venue must also be a witnessed candidate")
        if self.universe_complete and self.coverage is not Coverage.OBSERVED_COMPLETE:
            raise ValueError("only observed-complete coverage may assert a complete universe")


@dataclass(frozen=True, slots=True)
class LandedFill:
    """Independent finalized-chain truth; the shadow engine never manufactures one."""

    signature: str
    slot: int
    input_asset: str
    input_atoms: int
    output_asset: str
    output_atoms: int
    venue_ids: tuple[str, ...]
    finalized: bool = True

    def __post_init__(self) -> None:
        atoms(self.slot, name="fill slot")
        atoms(self.input_atoms, name="fill input")
        atoms(self.output_atoms, name="fill output")
        if not self.finalized:
            raise ValueError("LandedFill is reserved for finalized effects")


@dataclass(frozen=True, slots=True)
class QuoteIntent:
    intent_id: str
    sequence: int
    direction: Direction
    input_atoms: int
    origin: FlowOrigin
    jupiter: JupiterWitness
    landed_fill: LandedFill | None = None

    def __post_init__(self) -> None:
        atoms(self.sequence, name="intent sequence")
        atoms(self.input_atoms, name="intent input")
        if self.input_atoms == 0:
            raise ValueError("an intent must have positive input")


@dataclass(frozen=True, slots=True)
class ModeledTransfer:
    """A copied-state transition; deliberately not named or typed as a landed fill."""

    venue_id: str
    intent_id: str
    direction: Direction
    input_atoms: int
    output_atoms: int
    post_state_digest: str


@dataclass(frozen=True, slots=True)
class RouteDecision:
    status: RouteDecisionStatus
    selected_venue_id: str | None
    baseline_venue_id: str | None
    baseline_output_atoms: int | None
    selected_output_atoms: int | None
    ghost_assumed_candidate: bool
    ghost_selected: bool
    margin_atoms: int | None
    unknown_reason: str | None
    claim_scope: str = "fixed_demand_modeled_route_selection_not_jupiter_observation_or_fill"

    def __post_init__(self) -> None:
        if self.status is RouteDecisionStatus.MODELED_SELECTION:
            if (
                self.selected_venue_id is None
                or self.selected_output_atoms is None
                or self.baseline_venue_id is None
                or self.baseline_output_atoms is None
                or self.unknown_reason is not None
            ):
                raise ValueError(
                    "a modeled selection requires selected/baseline values and no unknown reason"
                )
        elif (
            self.selected_venue_id is not None
            or self.selected_output_atoms is not None
            or self.baseline_venue_id is not None
            or self.baseline_output_atoms is not None
            or self.ghost_selected
            or self.margin_atoms is not None
            or self.unknown_reason is None
        ):
            raise ValueError("an unknown route decision cannot publish route values or omit reason")


@dataclass(frozen=True, slots=True)
class ArbitrageSpec:
    after_intent_id: str
    ordering: ArbitrageOrdering
    direction: Direction
    input_asset_id: str
    output_asset_id: str
    external_unwind_asset_id: str
    cost_asset_id: str
    profit_asset_id: str
    input_atoms: int
    external_unwind_atoms: int
    priority_and_route_cost_atoms: int
    minimum_profit_atoms: int
    latency_slots: int

    def __post_init__(self) -> None:
        if (
            not self.input_asset_id
            or not self.output_asset_id
            or self.input_asset_id == self.output_asset_id
        ):
            raise ValueError("arbitrage requires distinct input/profit and output asset identities")
        if (
            self.external_unwind_asset_id != self.input_asset_id
            or self.cost_asset_id != self.input_asset_id
            or self.profit_asset_id != self.input_asset_id
        ):
            raise ValueError("unwind, cost, and profit must explicitly use the input asset")
        for name in (
            "input_atoms",
            "external_unwind_atoms",
            "priority_and_route_cost_atoms",
            "minimum_profit_atoms",
            "latency_slots",
        ):
            atoms(getattr(self, name), name=name)


@dataclass(frozen=True, slots=True)
class ArbitrageResponse:
    spec: ArbitrageSpec
    ghost_quote: QuoteOutcome
    acted: bool
    modeled_profit_atoms: int | None
    transfer: ModeledTransfer | None
    request_slot: int
    modeled_arrival_slot: int
    refusal_reason: str | None
    claim_scope: str = "registered_arbitrage_scenario_not_observed_actor_response"

    def __post_init__(self) -> None:
        atoms(self.request_slot, name="arbitrage request slot")
        atoms(self.modeled_arrival_slot, name="arbitrage arrival slot")
        if self.modeled_arrival_slot != self.request_slot + self.spec.latency_slots:
            raise ValueError("arbitrage arrival slot must apply the registered latency")
        if self.acted and (self.transfer is None or self.refusal_reason is not None):
            raise ValueError("acted arbitrage requires a transfer and no refusal")
        if not self.acted and self.transfer is not None:
            raise ValueError("refused arbitrage cannot carry a transfer")


@dataclass(frozen=True, slots=True)
class HouseholdSelfRouteCounterleg:
    """The exact controlled counterparty side of one household-owned LP interaction."""

    quote_digest: str
    direction: Direction
    gross_input_atoms: int
    output_atoms: int
    lp_fee_atoms: int
    protocol_fee_atoms: int

    def __post_init__(self) -> None:
        if not self.quote_digest:
            raise ValueError("self-route counterleg quote identity is required")
        for name in (
            "gross_input_atoms",
            "output_atoms",
            "lp_fee_atoms",
            "protocol_fee_atoms",
        ):
            atoms(getattr(self, name), name=name)
        if self.output_atoms == 0:
            raise ValueError("self-route counterleg requires positive received output")
        if self.lp_fee_atoms + self.protocol_fee_atoms >= self.gross_input_atoms:
            raise ValueError("self-route fees must leave positive trade input")


@dataclass(frozen=True, slots=True)
class AssetInventory:
    x_atoms: int
    y_atoms: int
    external_fee_x_atoms: int = 0
    external_fee_y_atoms: int = 0
    self_fee_x_atoms: int = 0
    self_fee_y_atoms: int = 0
    household_counterparty_x_atoms: int = 0
    household_counterparty_y_atoms: int = 0
    self_route_counterlegs: tuple[HouseholdSelfRouteCounterleg, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "x_atoms",
            "y_atoms",
            "external_fee_x_atoms",
            "external_fee_y_atoms",
            "self_fee_x_atoms",
            "self_fee_y_atoms",
        ):
            atoms(getattr(self, name), name=name)
        for name in ("household_counterparty_x_atoms", "household_counterparty_y_atoms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be signed integer atoms")
            if not -((1 << 128) - 1) <= value <= (1 << 128) - 1:
                raise ValueError(f"{name} exceeds the signed study envelope")
        counterleg_ids = [item.quote_digest for item in self.self_route_counterlegs]
        if len(counterleg_ids) != len(set(counterleg_ids)):
            raise ValueError("household self-route counterleg identities must be unique")
        expected_fee_x = 0
        expected_fee_y = 0
        expected_counterparty_x = 0
        expected_counterparty_y = 0
        for item in self.self_route_counterlegs:
            if item.direction is Direction.X_TO_Y:
                expected_fee_x += item.lp_fee_atoms
                expected_counterparty_x -= item.gross_input_atoms
                expected_counterparty_y += item.output_atoms
            else:
                expected_fee_y += item.lp_fee_atoms
                expected_counterparty_y -= item.gross_input_atoms
                expected_counterparty_x += item.output_atoms
        if (self.self_fee_x_atoms, self.self_fee_y_atoms) != (expected_fee_x, expected_fee_y):
            raise ValueError("self fees must exactly reconcile to retained counterlegs")
        if (self.household_counterparty_x_atoms, self.household_counterparty_y_atoms) != (
            expected_counterparty_x,
            expected_counterparty_y,
        ):
            raise ValueError("household counterparty deltas must exactly reconcile to counterlegs")

    def consolidated(self) -> tuple[int, int]:
        """Principal plus claims; self fees remain disclosed but do not become revenue."""

        return (
            atoms(
                self.x_atoms
                + self.external_fee_x_atoms
                + self.self_fee_x_atoms
                + self.household_counterparty_x_atoms,
                name="consolidated X",
            ),
            atoms(
                self.y_atoms
                + self.external_fee_y_atoms
                + self.self_fee_y_atoms
                + self.household_counterparty_y_atoms,
                name="consolidated Y",
            ),
        )


@dataclass(frozen=True, slots=True)
class ShadowScenario:
    scenario_id: str
    ghost_assumed_candidate: bool
    minimum_margin_atoms: int
    state_treatment: ExternalStateTreatment
    arbitrage: tuple[ArbitrageSpec, ...] = ()
    adverse_selection_attribution: AdverseSelectionAttribution = AdverseSelectionAttribution.NONE

    def __post_init__(self) -> None:
        if not isinstance(self.adverse_selection_attribution, AdverseSelectionAttribution):
            raise ValueError("scenario requires an explicit adverse-selection attribution")
        atoms(self.minimum_margin_atoms, name="minimum margin")
        identities = [(item.after_intent_id, item.ordering) for item in self.arbitrage]
        if len(identities) != len(set(identities)):
            raise ValueError("at most one arbitrage action is allowed per intent and ordering")

    @property
    def content_digest(self) -> str:
        """Recompute the exact scenario-policy identity; the display ID is not authority."""

        return digest(
            {
                "contract": "joshi.wave6.routed-shadow-scenario/v1",
                "ghost_assumed_candidate": self.ghost_assumed_candidate,
                "minimum_margin_atoms": self.minimum_margin_atoms,
                "state_treatment": self.state_treatment,
                "arbitrage": self.arbitrage,
                "adverse_selection_attribution": self.adverse_selection_attribution,
            }
        )


@dataclass(frozen=True, slots=True)
class ShadowEvent:
    intent: QuoteIntent
    venue_quotes: tuple[VenueQuote, ...]
    ghost_would_quote: WouldQuote
    decision: RouteDecision
    modeled_transfer: ModeledTransfer | None
    arbitrage_responses: tuple[ArbitrageResponse, ...]
    inventory_before: AssetInventory
    inventory_after: AssetInventory


@dataclass(frozen=True, slots=True)
class ShadowRun:
    scenario: ShadowScenario
    schedule_id: str
    initial_inventory: AssetInventory
    events: tuple[ShadowEvent, ...]
    terminal_inventory: AssetInventory
    claim_scope: str = "counterfactual_fixed_demand_shadow_not_causal_or_profitability_claim"

    @property
    def registration_digest(self) -> str:
        """Recompute policy, registered inputs, and exact source-cut identity for diagnostics."""

        registered_inputs = tuple(
            {
                "intent": event.intent,
                "reference_cuts": tuple(
                    (
                        venue_quote.outcome.venue_id,
                        venue_quote.observation_id,
                        venue_quote.source_cut,
                    )
                    for venue_quote in event.venue_quotes
                ),
                "ghost_schedule_id": event.ghost_would_quote.schedule_id,
                "ghost_source_cut": event.ghost_would_quote.source_cut,
            }
            for event in self.events
        )
        return digest(
            {
                "contract": "joshi.wave6.routed-shadow-run-registration/v1",
                "scenario_content_digest": self.scenario.content_digest,
                "schedule_id": self.schedule_id,
                "initial_inventory": self.initial_inventory,
                "registered_inputs": registered_inputs,
            }
        )


@dataclass(frozen=True, slots=True)
class DlmmFeePolicy:
    total_rate_1e9: int
    protocol_share_bps: int

    def __post_init__(self) -> None:
        if isinstance(self.total_rate_1e9, bool) or not isinstance(self.total_rate_1e9, int):
            raise ValueError("DLMM total fee must be an integer")
        if isinstance(self.protocol_share_bps, bool) or not isinstance(
            self.protocol_share_bps, int
        ):
            raise ValueError("protocol fee share must be an integer")
        if not 0 <= self.total_rate_1e9 <= 100_000_000:
            raise ValueError("DLMM total fee exceeds the supported 10% cap")
        if not 0 <= self.protocol_share_bps <= 10_000:
            raise ValueError("protocol fee share is outside bps precision")
        if self.total_rate_1e9 >= FEE_PRECISION:
            raise ValueError("DLMM fee leaves no trade input")
