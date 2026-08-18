"""Deterministic copied-state route operators for baseline and shaped ghost edges."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, Self

from .arithmetic import FEE_PRECISION, Q64, atoms, digest, fee_ceil, mul_div_floor
from .contracts import (
    AssetInventory,
    Direction,
    DlmmFeePolicy,
    ExactQuote,
    FeeComponent,
    FlowOrigin,
    QuoteLeg,
    QuoteOutcome,
    QuoteRefusal,
)


class EdgeOperator(Protocol):
    edge_id: str
    asset_x: str
    asset_y: str

    def quote(self, direction: Direction, input_atoms: int) -> QuoteOutcome: ...

    def apply(self, quote: ExactQuote, origin: FlowOrigin) -> Self: ...


def _asset_pair(asset_x: str, asset_y: str, direction: Direction) -> tuple[str, str]:
    if direction is Direction.X_TO_Y:
        return asset_x, asset_y
    return asset_y, asset_x


@dataclass(frozen=True, slots=True)
class FixedBin:
    """One exact-price bin in the ghost schedule.

    ``price_q64`` is Y atoms per X atom. Y inventory serves X→Y flow; X
    inventory serves Y→X flow. The finite balances are the optionality bound.
    """

    bin_id: int
    price_q64: int
    x_atoms: int
    y_atoms: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.bin_id, bool)
            or not isinstance(self.bin_id, int)
            or not -(1 << 31) <= self.bin_id < (1 << 31)
        ):
            raise ValueError("bin_id must be an i32")
        atoms(self.price_q64, name="Q64.64 price")
        atoms(self.x_atoms, name="bin X")
        atoms(self.y_atoms, name="bin Y")
        if self.price_q64 == 0:
            raise ValueError("bin price must be positive")


@dataclass(frozen=True, slots=True)
class DlmmBinEdge:
    """A finite nonlinear DLMM-like schedule; not a deployed Meteora pool."""

    edge_id: str
    schedule_id: str
    state_id: str
    asset_x: str
    asset_y: str
    active_bin_id: int
    fee_policy: DlmmFeePolicy
    bins: tuple[FixedBin, ...]
    transition_count: int = 0
    external_fee_x_atoms: int = 0
    external_fee_y_atoms: int = 0
    self_fee_x_atoms: int = 0
    self_fee_y_atoms: int = 0

    def __post_init__(self) -> None:
        if not self.edge_id or not self.schedule_id or not self.state_id:
            raise ValueError("edge, schedule, and state identities are required")
        if not self.asset_x or not self.asset_y or self.asset_x == self.asset_y:
            raise ValueError("the edge requires two distinct assets")
        if (
            isinstance(self.active_bin_id, bool)
            or not isinstance(self.active_bin_id, int)
            or not -(1 << 31) <= self.active_bin_id < (1 << 31)
        ):
            raise ValueError("active_bin_id must be an i32")
        if tuple(sorted(self.bins, key=lambda item: item.bin_id)) != self.bins:
            raise ValueError("bins must be strictly ordered by bin id")
        if len({item.bin_id for item in self.bins}) != len(self.bins):
            raise ValueError("duplicate bin ids are forbidden")
        for name in (
            "transition_count",
            "external_fee_x_atoms",
            "external_fee_y_atoms",
            "self_fee_x_atoms",
            "self_fee_y_atoms",
        ):
            atoms(getattr(self, name), name=name)

    @property
    def current_state_id(self) -> str:
        return f"{self.state_id}:transition:{self.transition_count}"

    @property
    def state_digest(self) -> str:
        return digest(self)

    def inventory(self) -> AssetInventory:
        return AssetInventory(
            x_atoms=sum(item.x_atoms for item in self.bins),
            y_atoms=sum(item.y_atoms for item in self.bins),
            external_fee_x_atoms=self.external_fee_x_atoms,
            external_fee_y_atoms=self.external_fee_y_atoms,
            self_fee_x_atoms=self.self_fee_x_atoms,
            self_fee_y_atoms=self.self_fee_y_atoms,
        )

    def with_active_bin(self, active_bin_id: int, state_id: str) -> DlmmBinEdge:
        """Move the witnessed active state without changing installed inventory."""

        return replace(self, active_bin_id=active_bin_id, state_id=state_id, transition_count=0)

    def quote(self, direction: Direction, input_atoms: int) -> QuoteOutcome:
        atoms(input_atoms, name="quote input")
        if input_atoms == 0:
            return QuoteRefusal(self.edge_id, self.current_state_id, "zero_size")
        total_fee = fee_ceil(input_atoms, self.fee_policy.total_rate_1e9, FEE_PRECISION)
        if total_fee >= input_atoms:
            return QuoteRefusal(self.edge_id, self.current_state_id, "fee_consumes_input")
        trade_input = input_atoms - total_fee
        protocol_fee = (total_fee * self.fee_policy.protocol_share_bps) // 10_000
        lp_fee = total_fee - protocol_fee
        input_asset, output_asset = _asset_pair(self.asset_x, self.asset_y, direction)
        ordered = self._eligible_bins(direction)
        remaining = trade_input
        legs: list[QuoteLeg] = []
        output = 0
        for bin_state in ordered:
            capacity = self._input_capacity(bin_state, direction)
            if capacity == 0:
                continue
            leg_input = min(remaining, capacity)
            leg_output = self._output(bin_state, direction, leg_input)
            if leg_output == 0:
                continue
            legs.append(QuoteLeg(str(bin_state.bin_id), leg_input, leg_output))
            remaining -= leg_input
            output += leg_output
            if remaining == 0:
                break
        if remaining:
            return QuoteRefusal(self.edge_id, self.current_state_id, "insufficient_finite_capacity")
        if output == 0:
            return QuoteRefusal(self.edge_id, self.current_state_id, "rounds_to_zero")
        return ExactQuote(
            venue_id=self.edge_id,
            state_id=self.current_state_id,
            input_asset=input_asset,
            output_asset=output_asset,
            input_atoms=input_atoms,
            trade_input_atoms=trade_input,
            output_atoms=atoms(output, name="quote output"),
            fees=(
                FeeComponent("lp", input_asset, lp_fee),
                FeeComponent("protocol", input_asset, protocol_fee),
            ),
            legs=tuple(legs),
            pre_state_digest=self.state_digest,
        )

    def apply(self, quote: ExactQuote, origin: FlowOrigin) -> DlmmBinEdge:
        if quote.venue_id != self.edge_id or quote.pre_state_digest != self.state_digest:
            raise ValueError("quote is not bound to this copied edge state")
        direction = (
            Direction.X_TO_Y if quote.input_asset == self.asset_x else Direction.Y_TO_X
        )
        by_id = {item.bin_id: item for item in self.bins}
        for leg in quote.legs:
            bin_id = int(leg.segment_id)
            current = by_id[bin_id]
            if direction is Direction.X_TO_Y:
                if leg.output_atoms > current.y_atoms:
                    raise ValueError("quote overdraws bin Y inventory")
                by_id[bin_id] = replace(
                    current,
                    x_atoms=atoms(current.x_atoms + leg.input_atoms),
                    y_atoms=current.y_atoms - leg.output_atoms,
                )
            else:
                if leg.output_atoms > current.x_atoms:
                    raise ValueError("quote overdraws bin X inventory")
                by_id[bin_id] = replace(
                    current,
                    x_atoms=current.x_atoms - leg.output_atoms,
                    y_atoms=atoms(current.y_atoms + leg.input_atoms),
                )
        lp_fee = next(component.atoms for component in quote.fees if component.owner == "lp")
        changes: dict[str, int] = {"transition_count": self.transition_count + 1}
        fee_prefix = "external_fee" if origin is FlowOrigin.EXTERNAL else "self_fee"
        fee_side = "x_atoms" if quote.input_asset == self.asset_x else "y_atoms"
        field_name = f"{fee_prefix}_{fee_side}"
        changes[field_name] = atoms(getattr(self, field_name) + lp_fee)
        return replace(self, bins=tuple(by_id[item.bin_id] for item in self.bins), **changes)

    def _eligible_bins(self, direction: Direction) -> tuple[FixedBin, ...]:
        if direction is Direction.X_TO_Y:
            return tuple(
                sorted(
                    (item for item in self.bins if item.bin_id <= self.active_bin_id),
                    key=lambda item: item.bin_id,
                    reverse=True,
                )
            )
        return tuple(item for item in self.bins if item.bin_id >= self.active_bin_id)

    @staticmethod
    def _input_capacity(bin_state: FixedBin, direction: Direction) -> int:
        if direction is Direction.X_TO_Y:
            # Largest X input whose floored Y output does not exceed Y inventory.
            return (((bin_state.y_atoms + 1) * Q64) - 1) // bin_state.price_q64
        # Largest Y input whose floored X output does not exceed X inventory.
        return (((bin_state.x_atoms + 1) * bin_state.price_q64) - 1) // Q64

    @staticmethod
    def _output(bin_state: FixedBin, direction: Direction, input_atoms: int) -> int:
        if direction is Direction.X_TO_Y:
            return mul_div_floor(input_atoms, bin_state.price_q64, Q64)
        return mul_div_floor(input_atoms, Q64, bin_state.price_q64)


@dataclass(frozen=True, slots=True)
class ConstantProductEdge:
    """Exact-in constant-product control with copied reserve updates."""

    edge_id: str
    state_id: str
    asset_x: str
    asset_y: str
    reserve_x: int
    reserve_y: int
    fee_rate_1e9: int = 0
    transition_count: int = 0

    def __post_init__(self) -> None:
        for name in ("reserve_x", "reserve_y", "fee_rate_1e9", "transition_count"):
            atoms(getattr(self, name), name=name)
        if self.reserve_x == 0 or self.reserve_y == 0:
            raise ValueError("constant-product reserves must be positive")
        if isinstance(self.fee_rate_1e9, bool) or not isinstance(self.fee_rate_1e9, int):
            raise ValueError("constant-product fee must be an integer")
        if self.fee_rate_1e9 >= FEE_PRECISION:
            raise ValueError("constant-product fee leaves no trade input")

    @property
    def current_state_id(self) -> str:
        return f"{self.state_id}:transition:{self.transition_count}"

    @property
    def state_digest(self) -> str:
        return digest(self)

    def quote(self, direction: Direction, input_atoms: int) -> QuoteOutcome:
        atoms(input_atoms, name="quote input")
        if input_atoms == 0:
            return QuoteRefusal(self.edge_id, self.current_state_id, "zero_size")
        fee = fee_ceil(input_atoms, self.fee_rate_1e9, FEE_PRECISION)
        trade_input = input_atoms - fee
        if trade_input == 0:
            return QuoteRefusal(self.edge_id, self.current_state_id, "fee_consumes_input")
        reserve_in, reserve_out = (
            (self.reserve_x, self.reserve_y)
            if direction is Direction.X_TO_Y
            else (self.reserve_y, self.reserve_x)
        )
        output = mul_div_floor(trade_input, reserve_out, reserve_in + trade_input)
        if output == 0:
            return QuoteRefusal(self.edge_id, self.current_state_id, "rounds_to_zero")
        input_asset, output_asset = _asset_pair(self.asset_x, self.asset_y, direction)
        return ExactQuote(
            venue_id=self.edge_id,
            state_id=self.current_state_id,
            input_asset=input_asset,
            output_asset=output_asset,
            input_atoms=input_atoms,
            trade_input_atoms=trade_input,
            output_atoms=output,
            fees=(FeeComponent("lp", input_asset, fee),),
            legs=(QuoteLeg("constant_product", trade_input, output),),
            pre_state_digest=self.state_digest,
        )

    def apply(self, quote: ExactQuote, origin: FlowOrigin) -> ConstantProductEdge:
        del origin
        if quote.venue_id != self.edge_id or quote.pre_state_digest != self.state_digest:
            raise ValueError("quote is not bound to this copied edge state")
        if quote.input_asset == self.asset_x:
            return replace(
                self,
                reserve_x=atoms(self.reserve_x + quote.input_atoms),
                reserve_y=self.reserve_y - quote.output_atoms,
                transition_count=self.transition_count + 1,
            )
        return replace(
            self,
            reserve_x=self.reserve_x - quote.output_atoms,
            reserve_y=atoms(self.reserve_y + quote.input_atoms),
            transition_count=self.transition_count + 1,
        )
