from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .runner import (
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
class PolicyDefaults:
    """The one place a policy default is written down.

    There were five: `config.py`, two in `policies.py`, `server.py` and `lots.py` — and
    `lots.py` disagreed with the other four, so the same bag got a different rule depending
    on whether the engine discovered it or the dashboard created it. Every default now
    comes from here, including the field defaults of `PositionPolicy` itself.

    The default bag has NO STOP. Kaminski & Lo show a price stop is negative-expectation
    under a random walk, and the bounce-free variance ratios measured on this desk's own
    pools read 0.80-1.01 on four of four — a random walk. The 7.47 SOL this desk lost in one
    window was stops firing on noise. Death is handled by `rug_exit`, which is not a price
    move; the upside is handled by the runner, which widens its give-back as the multiple
    grows. A stop is now something the operator asks for, one bag at a time.
    """

    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = Decimal("100")
    runner_tightness: Decimal | None = Decimal("20")
    rug_exit: bool = True
    dispose_after_break_even: bool = False
    floor_confirm_quotes: int = 2
    hold_trail_until_graduated: bool = True


DEFAULTS = PolicyDefaults()


@dataclasses.dataclass(frozen=True, slots=True)
class PositionPolicy:
    """A sell rule for one bag. Every price-based exit is optional.

    `stop_loss_pct=None` and `take_profit_pct=None` mean that exit NEVER fires — absence,
    not a deep sentinel like -95 that still leaves a price rule armed at the bottom of the
    chart. `runner_tightness=None` means no trailing behaviour of any kind: the lock-rung
    machinery is not consulted and no peak is tracked.

    So "hold unless it doubles or rugs" is `stop_loss_pct=None, take_profit_pct=100,
    rug_exit=True`, and "hold until it dies" is all three price fields None. Neither was
    expressible before: `stop_loss_pct` was mandatory and validation forced it negative.
    """

    mint: str
    name: str
    buy_price_sol: Decimal | None = None
    cost_basis_sol: Decimal | None = None
    stop_loss_pct: Decimal | None = DEFAULTS.stop_loss_pct
    take_profit_pct: Decimal | None = DEFAULTS.take_profit_pct
    runner_tightness: Decimal | None = DEFAULTS.runner_tightness
    rug_exit: bool = DEFAULTS.rug_exit
    dispose_after_break_even: bool = DEFAULTS.dispose_after_break_even
    floor_confirm_quotes: int = DEFAULTS.floor_confirm_quotes
    hold_trail_until_graduated: bool = DEFAULTS.hold_trail_until_graduated

    @property
    def runs(self) -> bool:
        """Does this bag have trailing behaviour at all?"""

        return self.runner_tightness is not None

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
    EXIT_TAKE_PROFIT = "exit_take_profit"


@dataclasses.dataclass(frozen=True, slots=True)
class PositionState:
    trailing_active: bool = False
    trailing_peak_unit_price_sol: Decimal | None = None
    last_pnl_pct: Decimal | None = None
    dispose_trigger_slot: int | None = None
    below_floor_streak: int = 0
    below_stop_streak: int = 0
    above_take_profit_streak: int = 0
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
            DecisionKind.EXIT_TAKE_PROFIT,
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
) -> Decision:
    """Pure policy function. Rug exit precedence is deliberate and testable.

    A price rule that is None does not fire. There is no `stop_enabled` flag any more: a
    caller that wants the stop held off (the engine, during a new lot's basis grace) passes
    a policy whose `stop_loss_pct` is None. One concept, one representation — three ways to
    say "no stop" is how behaviour stops being reasonable-about.
    """
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

    stop = policy.stop_loss_pct
    if stop is not None and pnl is not None and pnl <= stop:
        needed = max(1, int(policy.floor_confirm_quotes))
        streak = state.below_stop_streak + 1
        next_state = dataclasses.replace(state, below_stop_streak=streak)
        if streak >= needed:
            return Decision(
                DecisionKind.EXIT_STOP,
                f"PnL {pnl:.2f}% <= stop {stop:.2f}% for {streak} quote(s)",
                pnl,
                unit_price,
                next_state,
            )
        return Decision(
            DecisionKind.HOLD,
            f"stop {stop:.2f}% waiting confirm ({streak}/{needed}; PnL {pnl:.2f}%)",
            pnl,
            unit_price,
            next_state,
        )
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

    if disposal_state.trailing_active:
        if policy.runs:
            return _evaluate_runner(
                policy=policy,
                holding=holding,
                unit_price=unit_price,
                entry=entry,
                pnl=pnl,
                state=disposal_state,
            )
        # The runner was switched off under an armed bag. There is nothing left to trail
        # with, so the arm is dropped rather than reinterpreted, and the take-profit rule
        # below decides on its own terms.
        disposal_state = dataclasses.replace(
            disposal_state, trailing_active=False, trailing_peak_unit_price_sol=None
        )

    if (
        policy.runs
        and policy.hold_trail_until_graduated
        and pump_complete is False
    ):
        return Decision(
            DecisionKind.HOLD,
            "bonding curve: runner waits for graduation",
            pnl,
            unit_price,
            disposal_state,
        )

    take_profit = policy.take_profit_pct
    if take_profit is not None and pnl is not None and pnl >= take_profit:
        # Confirmation is SYMMETRIC. The stop required N consecutive quotes while the take
        # profit fired on one, so a single upward wick sold the runner and a single downward
        # wick did not sell anything. Given that the whole point of this rule set is to
        # prefer holding, one bad print must not be able to end a position in EITHER
        # direction — and `floor_confirm_quotes` is the one wick-grace knob.
        needed = max(1, int(policy.floor_confirm_quotes))
        streak = disposal_state.above_take_profit_streak + 1
        confirmed = dataclasses.replace(disposal_state, above_take_profit_streak=streak)
        if streak < needed:
            return Decision(
                DecisionKind.HOLD,
                (
                    f"take profit {take_profit:.2f}% waiting confirm "
                    f"({streak}/{needed}; PnL {pnl:.2f}%)"
                ),
                pnl,
                unit_price,
                confirmed,
            )
        if not policy.runs:
            # No runner configured: the take-profit IS the exit. This is the literal
            # "hold unless it doubles" bag.
            return Decision(
                DecisionKind.EXIT_TAKE_PROFIT,
                (
                    f"PnL {pnl:.2f}% >= take profit {take_profit:.2f}% for {streak} quote(s) "
                    "and no runner is configured"
                ),
                pnl,
                unit_price,
                confirmed,
            )
        armed = dataclasses.replace(
            confirmed,
            trailing_active=True,
            trailing_peak_unit_price_sol=unit_price,
            below_floor_streak=0,
            above_take_profit_streak=0,
            original_amount=confirmed.original_amount or holding.amount,
            runner_floor_multiple=None,
        )
        return Decision(
            DecisionKind.ACTIVATE_TRAIL,
            (
                f"runner armed at {pnl:.2f}% after {streak} quote(s) "
                f"(lock-in floors, not a {policy.runner_tightness:.0f}% peak leash)"
            ),
            pnl,
            unit_price,
            armed,
        )

    return Decision(
        DecisionKind.HOLD,
        "thresholds clear",
        pnl,
        unit_price,
        dataclasses.replace(disposal_state, above_take_profit_streak=0),
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
    tightness = policy.runner_tightness
    if tightness is None:  # pragma: no cover - the caller checks `policy.runs` first
        raise ValueError("runner evaluated for a policy with no runner_tightness")
    floor = lock_floor_multiple(peak_multiple, tightness=tightness)
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
