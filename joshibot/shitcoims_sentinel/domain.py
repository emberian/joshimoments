from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .runner import (
    EXIT_STYLE_FIXED,
    EXIT_STYLE_RUNNER,
    SCALE_RUNGS,
    lock_floor_multiple,
    next_scale_fraction,
    rung_key,
    scale_sell_amount,
)

LAMPORTS_PER_SOL = 1_000_000_000
WSOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_MINT_AUTHORITY = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def decimal_from(value: Any, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:  # Decimal raises several implementation-specific errors.
        raise ValueError(f"{field} must be a decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


@dataclasses.dataclass(frozen=True, slots=True)
class PositionPolicy:
    mint: str
    name: str
    buy_price_sol: Decimal | None
    cost_basis_sol: Decimal | None
    stop_loss_pct: Decimal
    take_profit_pct: Decimal
    trailing_stop_pct: Decimal
    rug_exit: bool = True
    dispose_after_break_even: bool = False
    exit_style: str = EXIT_STYLE_FIXED
    floor_confirm_quotes: int = 2
    hold_trail_until_graduated: bool = True

    def entry_unit_price(self, holding: TokenHolding) -> Decimal | None:
        if self.buy_price_sol is not None:
            return self.buy_price_sol
        if self.cost_basis_sol is None or holding.ui_amount == 0:
            return None
        return self.cost_basis_sol / holding.ui_amount


@dataclasses.dataclass(frozen=True, slots=True)
class TokenHolding:
    mint: str
    amount: int
    decimals: int
    token_accounts: tuple[str, ...]
    program_ids: tuple[str, ...]

    @property
    def ui_amount(self) -> Decimal:
        return Decimal(self.amount) / (Decimal(10) ** self.decimals)


@dataclasses.dataclass(frozen=True, slots=True)
class ExitQuote:
    input_mint: str
    input_amount: int
    out_lamports: int
    minimum_out_lamports: int | None
    price_impact_pct: Decimal | None
    router: str | None
    received_at: dt.datetime

    def unit_price_sol(self, holding: TokenHolding) -> Decimal:
        if holding.amount <= 0 or self.input_amount != holding.amount:
            raise ValueError("quote amount must equal the current full holding")
        return (Decimal(self.out_lamports) / LAMPORTS_PER_SOL) / holding.ui_amount


@dataclasses.dataclass(frozen=True, slots=True)
class MintSafety:
    mint_authority: str | None
    freeze_authority: str | None
    supply: int
    decimals: int
    token_program: str

    @property
    def mint_revoked(self) -> bool:
        return self.mint_authority is None

    @property
    def freeze_revoked(self) -> bool:
        return self.freeze_authority is None


@dataclasses.dataclass(frozen=True, slots=True)
class PoolSnapshot:
    pair_address: str
    dex_id: str
    base_mint: str
    quote_mint: str
    liquidity_usd: Decimal
    reserve_value: Decimal
    reserve_unit: str
    price_native: Decimal | None
    observed_at: dt.datetime
    token_name: str | None = None
    token_symbol: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class PumpTokenMetadata:
    mint: str
    name: str | None
    symbol: str | None
    creator: str | None
    complete: bool | None
    pool_address: str | None
    quote_mint: str | None
    token_program: str | None
    market_cap_sol: Decimal | None
    market_cap_usd: Decimal | None
    created_at: dt.datetime | None
    last_trade_at: dt.datetime | None
    mayhem_mode: bool | None
    received_at: dt.datetime


@dataclasses.dataclass(frozen=True, slots=True)
class RugSignal:
    emergency: bool
    reason: str | None = None
    liquidity_drop_pct: Decimal | None = None
    supply_growth_pct: Decimal | None = None
    needs_confirmation: bool = False


class DecisionKind(StrEnum):
    HOLD = "hold"
    ACTIVATE_TRAIL = "activate_trail"
    EXIT_STOP = "exit_stop"
    EXIT_TRAIL = "exit_trail"
    EXIT_SCALE = "exit_scale"
    EXIT_RUG = "exit_rug"
    EXIT_DISPOSE = "exit_dispose"


@dataclasses.dataclass(frozen=True, slots=True)
class PositionState:
    trailing_active: bool = False
    trailing_peak_unit_price_sol: Decimal | None = None
    last_pnl_pct: Decimal | None = None
    dispose_trigger_slot: int | None = None
    below_floor_streak: int = 0
    below_stop_streak: int = 0
    scale_rungs_fired: tuple[str, ...] = ()
    original_amount: int | None = None
    runner_floor_multiple: Decimal | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Decision:
    kind: DecisionKind
    reason: str
    pnl_pct: Decimal | None
    unit_price_sol: Decimal | None
    next_state: PositionState
    sell_amount: int | None = None

    @property
    def exits(self) -> bool:
        return self.kind in {
            DecisionKind.EXIT_RUG,
            DecisionKind.EXIT_STOP,
            DecisionKind.EXIT_TRAIL,
            DecisionKind.EXIT_SCALE,
            DecisionKind.EXIT_DISPOSE,
        }

    @property
    def full_exit(self) -> bool:
        return self.exits and self.kind is not DecisionKind.EXIT_SCALE


def evaluate_position(
    *,
    policy: PositionPolicy,
    holding: TokenHolding,
    quote: ExitQuote | None,
    state: PositionState,
    rug: RugSignal,
    confirmed_slot: int | None = None,
    dispose_enabled: bool | None = None,
    pump_complete: bool | None = None,
    stop_enabled: bool = True,
) -> Decision:
    """Pure policy function. Rug exit precedence is deliberate and testable."""
    unit_price = quote.unit_price_sol(holding) if quote is not None else None
    entry = policy.entry_unit_price(holding)
    pnl = None
    if unit_price is not None and entry is not None and entry > 0:
        pnl = (unit_price / entry - 1) * 100

    if rug.emergency and policy.rug_exit:
        return Decision(
            DecisionKind.EXIT_RUG,
            rug.reason or "rug detector emergency",
            pnl,
            unit_price,
            state,
        )

    # `unit_price` is derived from `quote` above and `unit_price_sol` raises rather than
    # returning None, so the second clause is unreachable today. It is stated anyway: it makes
    # the correlation checkable instead of carried in a reader's head, and if the quote ever
    # gains a None-returning path this fails closed to HOLD rather than dividing by None.
    if quote is None or unit_price is None:
        return Decision(DecisionKind.HOLD, "no executable quote", pnl, unit_price, state)

    if pnl is not None and pnl <= policy.stop_loss_pct:
        if not stop_enabled:
            state = dataclasses.replace(state, below_stop_streak=0)
        else:
            needed = max(1, int(policy.floor_confirm_quotes))
            streak = state.below_stop_streak + 1
            next_state = dataclasses.replace(state, below_stop_streak=streak)
            if streak >= needed:
                return Decision(
                    DecisionKind.EXIT_STOP,
                    (
                        f"PnL {pnl:.2f}% <= stop {policy.stop_loss_pct:.2f}% "
                        f"for {streak} quote(s)"
                    ),
                    pnl,
                    unit_price,
                    next_state,
                )
            return Decision(
                DecisionKind.HOLD,
                (
                    f"stop {policy.stop_loss_pct:.2f}% waiting confirm "
                    f"({streak}/{needed}; PnL {pnl:.2f}%)"
                ),
                pnl,
                unit_price,
                next_state,
            )
    else:
        state = dataclasses.replace(state, below_stop_streak=0)

    disposal_is_enabled = (
        policy.dispose_after_break_even if dispose_enabled is None else dispose_enabled
    )
    disposal_state = (
        state
        if disposal_is_enabled
        else dataclasses.replace(state, last_pnl_pct=None, dispose_trigger_slot=None)
    )
    if disposal_is_enabled:
        # The transition and its slot are both required. In particular, seeing a
        # position for the first time while it is green is not evidence that it
        # just crossed break-even. Missing basis/quote/slot data must not arm an
        # eventual sale.
        if pnl is None:
            return Decision(
                DecisionKind.HOLD,
                "dispose blocked: cost basis is unavailable",
                pnl,
                unit_price,
                state,
            )
        if confirmed_slot is None or confirmed_slot < 0:
            return Decision(
                DecisionKind.HOLD,
                "dispose blocked: confirmed slot is unavailable",
                pnl,
                unit_price,
                state,
            )
        disposal_state = dataclasses.replace(state, last_pnl_pct=pnl)
        if state.dispose_trigger_slot is not None:
            if confirmed_slot >= state.dispose_trigger_slot + 1:
                return Decision(
                    DecisionKind.EXIT_DISPOSE,
                    (
                        "dispose delay satisfied: confirmed slot "
                        f"{confirmed_slot} >= {state.dispose_trigger_slot + 1}"
                    ),
                    pnl,
                    unit_price,
                    disposal_state,
                )
            return Decision(
                DecisionKind.HOLD,
                f"dispose waiting for confirmed slot {state.dispose_trigger_slot + 1}",
                pnl,
                unit_price,
                disposal_state,
            )
        if state.last_pnl_pct is not None and state.last_pnl_pct <= 0 < pnl:
            disposal_state = dataclasses.replace(
                disposal_state, dispose_trigger_slot=confirmed_slot
            )
            return Decision(
                DecisionKind.HOLD,
                f"dispose triggered at confirmed slot {confirmed_slot}; waiting one block",
                pnl,
                unit_price,
                disposal_state,
            )

    runner_mode = policy.exit_style == EXIT_STYLE_RUNNER
    bonding_blocks_arm = (
        runner_mode
        and policy.hold_trail_until_graduated
        and pump_complete is False
        and not disposal_state.trailing_active
    )

    if disposal_state.trailing_active:
        if runner_mode:
            return _evaluate_runner(
                policy=policy,
                holding=holding,
                unit_price=unit_price,
                entry=entry,
                pnl=pnl,
                state=disposal_state,
            )
        peak = disposal_state.trailing_peak_unit_price_sol or unit_price
        new_peak = max(peak, unit_price)
        drop_pct = (unit_price / new_peak - 1) * 100
        next_state = dataclasses.replace(
            disposal_state,
            trailing_active=True,
            trailing_peak_unit_price_sol=new_peak,
        )
        if drop_pct <= -policy.trailing_stop_pct:
            return Decision(
                DecisionKind.EXIT_TRAIL,
                f"price {drop_pct:.2f}% below trailing peak",
                pnl,
                unit_price,
                next_state,
            )
        return Decision(DecisionKind.HOLD, "trailing", pnl, unit_price, next_state)

    if bonding_blocks_arm:
        return Decision(
            DecisionKind.HOLD,
            "bonding curve: runner waits for graduation",
            pnl,
            unit_price,
            disposal_state,
        )

    if pnl is not None and pnl >= policy.take_profit_pct:
        armed = dataclasses.replace(
            disposal_state,
            trailing_active=True,
            trailing_peak_unit_price_sol=unit_price,
            below_floor_streak=0,
            original_amount=disposal_state.original_amount or holding.amount,
            runner_floor_multiple=None,
        )
        reason = (
            f"PnL {pnl:.2f}% >= take profit {policy.take_profit_pct:.2f}%"
            if not runner_mode
            else (
                f"runner armed at {pnl:.2f}% "
                f"(lock-in floors, not a {policy.trailing_stop_pct:.0f}% peak leash)"
            )
        )
        return Decision(
            DecisionKind.ACTIVATE_TRAIL,
            reason,
            pnl,
            unit_price,
            armed,
        )

    return Decision(
        DecisionKind.HOLD,
        "thresholds clear",
        pnl,
        unit_price,
        disposal_state,
    )


def _evaluate_runner(
    *,
    policy: PositionPolicy,
    holding: TokenHolding,
    unit_price: Decimal,
    entry: Decimal | None,
    pnl: Decimal | None,
    state: PositionState,
) -> Decision:
    """Armed runner: lock-in floor + optional scale-out. Peak is not the trigger."""

    peak = state.trailing_peak_unit_price_sol or unit_price
    new_peak = max(peak, unit_price)
    preexisting = state.trailing_active and state.original_amount is None
    original = state.original_amount or holding.amount
    next_state = dataclasses.replace(
        state,
        trailing_active=True,
        trailing_peak_unit_price_sol=new_peak,
        original_amount=original,
    )
    if entry is None or entry <= 0:
        return Decision(
            DecisionKind.HOLD,
            "runner blocked: cost basis is unavailable",
            pnl,
            unit_price,
            next_state,
        )

    peak_multiple = new_peak / entry
    current_multiple = unit_price / entry
    floor = lock_floor_multiple(peak_multiple, tightness=policy.trailing_stop_pct)
    if preexisting and not next_state.scale_rungs_fired:
        # A trail that predates runner must not retroactively dump 30% of a
        # bag that already cleared 2x under the old leash.
        inherited = tuple(
            rung_key(arm_at) for arm_at, _fraction in SCALE_RUNGS if peak_multiple >= arm_at
        )
        next_state = dataclasses.replace(
            next_state,
            scale_rungs_fired=inherited,
            runner_floor_multiple=floor,
            below_floor_streak=0,
        )
        return Decision(
            DecisionKind.HOLD,
            (
                f"runner adopted prior trail at {peak_multiple:.2f}x; "
                "scale rungs already earned are not replayed"
            ),
            pnl,
            unit_price,
            next_state,
        )
    next_state = dataclasses.replace(next_state, runner_floor_multiple=floor)

    due = next_scale_fraction(peak_multiple, next_state.scale_rungs_fired)
    if due is not None:
        rung_multiple, fraction = due
        sell = scale_sell_amount(
            original_amount=original,
            remaining_amount=holding.amount,
            fraction=fraction,
        )
        if sell > 0:
            fired = (*next_state.scale_rungs_fired, rung_key(rung_multiple))
            scaled = dataclasses.replace(next_state, scale_rungs_fired=fired, below_floor_streak=0)
            return Decision(
                DecisionKind.EXIT_SCALE,
                (
                    f"runner scale-out {fraction:.0%} of original at "
                    f"{peak_multiple:.2f}x (rung {rung_key(rung_multiple)}x)"
                ),
                pnl,
                unit_price,
                scaled,
                sell_amount=sell,
            )

    if floor is None:
        return Decision(
            DecisionKind.HOLD,
            f"runner warming; peak {peak_multiple:.2f}x has no lock yet",
            pnl,
            unit_price,
            dataclasses.replace(next_state, below_floor_streak=0),
        )

    if current_multiple <= floor:
        streak = state.below_floor_streak + 1
        confirmed = dataclasses.replace(next_state, below_floor_streak=streak)
        needed = max(1, int(policy.floor_confirm_quotes))
        if streak >= needed:
            return Decision(
                DecisionKind.EXIT_TRAIL,
                (
                    f"runner floor {floor:.2f}x broken for {streak} quote(s) "
                    f"(peak {peak_multiple:.2f}x, now {current_multiple:.2f}x)"
                ),
                pnl,
                unit_price,
                confirmed,
            )
        return Decision(
            DecisionKind.HOLD,
            (
                f"runner below floor {floor:.2f}x "
                f"({streak}/{needed} quotes; peak {peak_multiple:.2f}x)"
            ),
            pnl,
            unit_price,
            confirmed,
        )

    return Decision(
        DecisionKind.HOLD,
        f"runner; peak {peak_multiple:.2f}x floor {floor:.2f}x now {current_multiple:.2f}x",
        pnl,
        unit_price,
        dataclasses.replace(next_state, below_floor_streak=0),
    )


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
