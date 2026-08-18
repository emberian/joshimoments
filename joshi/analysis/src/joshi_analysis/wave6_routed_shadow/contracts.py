"""Immutable evidence, counterfactual, and accounting contracts for Wave 6."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .arithmetic import FEE_PRECISION, atoms


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
    outcome: QuoteOutcome
    coverage: Coverage

    def __post_init__(self) -> None:
        atoms(self.slot, name="venue quote slot")


@dataclass(frozen=True, slots=True)
class WouldQuote:
    """Hypothetical edge calculation, explicitly below the observed-quote layer."""

    schedule_id: str
    outcome: QuoteOutcome
    claim_scope: str = "mechanical_would_quote_not_observed_route_or_fill"


@dataclass(frozen=True, slots=True)
class JupiterWitness:
    """A retained router response, not a reconstruction from landed chain data."""

    witness_id: str
    slot: int
    candidate_venue_ids: tuple[str, ...]
    routed_venue_ids: tuple[str, ...]
    universe_complete: bool
    coverage: Coverage

    def __post_init__(self) -> None:
        atoms(self.slot, name="Jupiter witness slot")
        if len(set(self.candidate_venue_ids)) != len(self.candidate_venue_ids):
            raise ValueError("Jupiter candidates must be unique")
        if not set(self.routed_venue_ids).issubset(self.candidate_venue_ids):
            raise ValueError("a routed venue must also be a witnessed candidate")


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
    selected_venue_id: str | None
    baseline_venue_id: str | None
    baseline_output_atoms: int | None
    selected_output_atoms: int | None
    ghost_assumed_candidate: bool
    ghost_selected: bool
    margin_atoms: int | None
    claim_scope: str = "fixed_demand_modeled_route_selection_not_jupiter_observation_or_fill"


@dataclass(frozen=True, slots=True)
class ArbitrageSpec:
    after_intent_id: str
    ordering: ArbitrageOrdering
    direction: Direction
    input_atoms: int
    external_unwind_atoms: int
    priority_and_route_cost_atoms: int
    minimum_profit_atoms: int
    latency_slots: int

    def __post_init__(self) -> None:
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
    claim_scope: str = "registered_arbitrage_scenario_not_observed_actor_response"


@dataclass(frozen=True, slots=True)
class AssetInventory:
    x_atoms: int
    y_atoms: int
    external_fee_x_atoms: int = 0
    external_fee_y_atoms: int = 0
    self_fee_x_atoms: int = 0
    self_fee_y_atoms: int = 0

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

    def consolidated(self) -> tuple[int, int]:
        """Principal plus claims; self fees remain disclosed but do not become revenue."""

        return (
            atoms(
                self.x_atoms + self.external_fee_x_atoms + self.self_fee_x_atoms,
                name="consolidated X",
            ),
            atoms(
                self.y_atoms + self.external_fee_y_atoms + self.self_fee_y_atoms,
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

    def __post_init__(self) -> None:
        atoms(self.minimum_margin_atoms, name="minimum margin")
        identities = [(item.after_intent_id, item.ordering) for item in self.arbitrage]
        if len(identities) != len(set(identities)):
            raise ValueError("at most one arbitrage action is allowed per intent and ordering")


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
