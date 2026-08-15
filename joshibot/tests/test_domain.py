from decimal import Decimal

from shitcoims_sentinel.domain import (
    DecisionKind,
    ExitQuote,
    PositionPolicy,
    PositionState,
    RugSignal,
    TokenHolding,
    evaluate_position,
    utc_now,
)
from shitcoims_sentinel.runner import rung_key


def holding() -> TokenHolding:
    return TokenHolding("mint", 1_000_000, 6, ("account",), ("program",))


def quote(unit_price_sol: str) -> ExitQuote:
    lamports = int(Decimal(unit_price_sol) * 1_000_000_000)
    return ExitQuote("mint", 1_000_000, lamports, None, None, "metis", utc_now())


def policy(**overrides: object) -> PositionPolicy:
    """Keyword-only on purpose.

    These were positional, so the meaning of every fixture depended on the field ORDER of
    `PositionPolicy`. Reordering or inserting a field silently re-aimed every threshold in
    this file at a different rule.
    """

    fields: dict = {
        "mint": "mint",
        "name": "MEME",
        "buy_price_sol": Decimal("1"),
        "cost_basis_sol": None,
        "stop_loss_pct": Decimal("-30"),
        "take_profit_pct": Decimal("100"),
        "runner_tightness": Decimal("20"),
        "rug_exit": True,
    }
    fields.update(overrides)
    return PositionPolicy(**fields)


def test_rug_preempts_stop_loss() -> None:
    decision = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("0.1"),
        state=PositionState(),
        rug=RugSignal(True, "pool drained"),
    )
    assert decision.kind is DecisionKind.EXIT_RUG


def test_stop_loss_needs_two_quotes_before_selling() -> None:
    first = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("0.69"),
        state=PositionState(),
        rug=RugSignal(False),
    )
    assert first.kind is DecisionKind.HOLD
    assert first.next_state.below_stop_streak == 1
    assert first.pnl_pct == Decimal("-31.00")
    second = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("0.69"),
        state=first.next_state,
        rug=RugSignal(False),
    )
    assert second.kind is DecisionKind.EXIT_STOP
    assert "2 quote" in second.reason


def test_stop_loss_resets_when_the_wick_recovers() -> None:
    first = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("0.69"),
        state=PositionState(),
        rug=RugSignal(False),
    )
    recovered = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("0.95"),
        state=first.next_state,
        rug=RugSignal(False),
    )
    assert recovered.kind is DecisionKind.HOLD
    assert recovered.next_state.below_stop_streak == 0


def test_a_bag_with_no_stop_never_stops_out_however_far_it_falls() -> None:
    """The rule the type could not express before, and the reason this desk lost 7.47 SOL.

    `stop_loss_pct=None` is absence, not a very deep number. Swept across four orders of
    magnitude of drawdown, and repeated so a confirmation streak cannot accumulate into a
    sale either.
    """

    no_stop = policy(stop_loss_pct=None)
    state = PositionState()
    for price in ("0.90", "0.50", "0.10", "0.01", "0.0001", "0.0001", "0.0001"):
        decision = evaluate_position(
            policy=no_stop,
            holding=holding(),
            quote=quote(price),
            state=state,
            rug=RugSignal(False),
        )
        assert decision.exits is False, price
        assert decision.next_state.below_stop_streak == 0
        state = decision.next_state


def test_none_is_absence_and_not_a_deep_sentinel_number() -> None:
    """A stop implemented as -95 would still sell the bottom. This pins the difference."""

    deep = evaluate_position(
        policy=policy(stop_loss_pct=Decimal("-95"), floor_confirm_quotes=1),
        holding=holding(),
        quote=quote("0.04"),
        state=PositionState(),
        rug=RugSignal(False),
    )
    assert deep.kind is DecisionKind.EXIT_STOP

    absent = evaluate_position(
        policy=policy(stop_loss_pct=None, floor_confirm_quotes=1),
        holding=holding(),
        quote=quote("0.04"),
        state=PositionState(),
        rug=RugSignal(False),
    )
    assert absent.kind is DecisionKind.HOLD


def test_a_bag_with_no_take_profit_never_arms_and_never_sells_upside() -> None:
    forever = policy(take_profit_pct=None)
    state = PositionState()
    for price in ("1.5", "2.5", "6.0", "40.0"):
        decision = evaluate_position(
            policy=forever,
            holding=holding(),
            quote=quote(price),
            state=state,
            rug=RugSignal(False),
            pump_complete=True,
        )
        assert decision.kind is DecisionKind.HOLD, price
        assert decision.next_state.trailing_active is False
        state = decision.next_state


def test_death_is_not_a_price_move_so_rug_still_exits_with_every_price_rule_off() -> None:
    held_forever = policy(stop_loss_pct=None, take_profit_pct=None, runner_tightness=None)
    decision = evaluate_position(
        policy=held_forever,
        holding=holding(),
        quote=quote("0.001"),
        state=PositionState(),
        rug=RugSignal(True, "pool drained"),
    )
    assert decision.kind is DecisionKind.EXIT_RUG


def test_take_profit_without_a_runner_is_itself_the_exit() -> None:
    """The operator sentence, literally: hold unless it doubles or rugs."""

    hold_unless_it_doubles = policy(stop_loss_pct=None, runner_tightness=None)
    still_holding = evaluate_position(
        policy=hold_unless_it_doubles,
        holding=holding(),
        quote=quote("1.99"),
        state=PositionState(),
        rug=RugSignal(False),
    )
    assert still_holding.kind is DecisionKind.HOLD

    doubled = evaluate_position(
        policy=hold_unless_it_doubles,
        holding=holding(),
        quote=quote("2.01"),
        state=PositionState(),
        rug=RugSignal(False),
    )
    assert doubled.kind is DecisionKind.EXIT_TAKE_PROFIT
    assert doubled.full_exit is True
    # Nothing to trail with, so no peak is invented.
    assert doubled.next_state.trailing_active is False
    assert doubled.next_state.trailing_peak_unit_price_sol is None


def test_take_profit_arms_the_runner_and_the_peak_tracks_upward() -> None:
    activated = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("2.1"),
        state=PositionState(),
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert activated.kind is DecisionKind.ACTIVATE_TRAIL
    assert activated.exits is False
    banked = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("2.4"),
        state=activated.next_state,
        rug=RugSignal(False),
        pump_complete=True,
    )
    # The 2x scale rung banks a slice of the original lot; the residual keeps running.
    assert banked.kind is DecisionKind.EXIT_SCALE
    assert banked.full_exit is False
    assert banked.next_state.trailing_peak_unit_price_sol == Decimal("2.4")


def test_the_deleted_percent_leash_would_have_sold_what_the_runner_holds() -> None:
    """20% off a 2.4x peak was a sale under `fixed_trail`. Under the lock rungs it is not.

    This is the behaviour difference the deletion buys, stated as a decision rather than as
    a missing field.
    """

    decision = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=quote("1.9"),
        state=PositionState(
            trailing_active=True,
            trailing_peak_unit_price_sol=Decimal("2.4"),
            original_amount=1_000_000,
            scale_rungs_fired=(rung_key(Decimal("2.0")),),
        ),
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert decision.exits is False
    assert decision.next_state.runner_floor_multiple == Decimal("1.20")


def test_no_quote_never_fires_price_rule() -> None:
    decision = evaluate_position(
        policy=policy(),
        holding=holding(),
        quote=None,
        state=PositionState(),
        rug=RugSignal(False),
    )
    assert decision.kind is DecisionKind.HOLD
    assert "no executable quote" in decision.reason


def test_dispose_requires_observed_red_to_green_edge_then_one_confirmed_block() -> None:
    dispose_policy = policy(dispose_after_break_even=True)
    red = evaluate_position(
        policy=dispose_policy,
        holding=holding(),
        quote=quote("0.99"),
        state=PositionState(),
        rug=RugSignal(False),
        confirmed_slot=100,
    )
    assert red.kind is DecisionKind.HOLD
    assert red.next_state.last_pnl_pct == Decimal("-1.00")
    assert red.next_state.dispose_trigger_slot is None

    crossed = evaluate_position(
        policy=dispose_policy,
        holding=holding(),
        quote=quote("1.01"),
        state=red.next_state,
        rug=RugSignal(False),
        confirmed_slot=101,
    )
    assert crossed.kind is DecisionKind.HOLD
    assert crossed.next_state.dispose_trigger_slot == 101

    same_slot = evaluate_position(
        policy=dispose_policy,
        holding=holding(),
        quote=quote("1.02"),
        state=crossed.next_state,
        rug=RugSignal(False),
        confirmed_slot=101,
    )
    assert same_slot.kind is DecisionKind.HOLD

    next_slot = evaluate_position(
        policy=dispose_policy,
        holding=holding(),
        quote=quote("1.02"),
        state=same_slot.next_state,
        rug=RugSignal(False),
        confirmed_slot=102,
    )
    assert next_slot.kind is DecisionKind.EXIT_DISPOSE


def test_dispose_does_not_infer_a_crossing_from_first_green_sample() -> None:
    dispose_policy = policy(dispose_after_break_even=True)
    decision = evaluate_position(
        policy=dispose_policy,
        holding=holding(),
        quote=quote("1.01"),
        state=PositionState(),
        rug=RugSignal(False),
        confirmed_slot=100,
    )
    assert decision.kind is DecisionKind.HOLD
    assert decision.next_state.last_pnl_pct == Decimal("1.00")
    assert decision.next_state.dispose_trigger_slot is None


def test_dispose_fails_closed_without_slot_but_rug_still_preempts() -> None:
    dispose_policy = policy(dispose_after_break_even=True)
    prior = PositionState(last_pnl_pct=Decimal("-1"))
    blocked = evaluate_position(
        policy=dispose_policy,
        holding=holding(),
        quote=quote("1.01"),
        state=prior,
        rug=RugSignal(False),
        confirmed_slot=None,
    )
    assert blocked.kind is DecisionKind.HOLD
    assert "confirmed slot" in blocked.reason
    assert blocked.next_state == prior

    emergency = evaluate_position(
        policy=dispose_policy,
        holding=holding(),
        quote=None,
        state=prior,
        rug=RugSignal(True, "pool drained"),
        confirmed_slot=None,
    )
    assert emergency.kind is DecisionKind.EXIT_RUG


def rug_only_policy() -> PositionPolicy:
    return policy(name="RUGONLY", buy_price_sol=None)


def test_rug_only_policy_exits_on_emergency_without_basis() -> None:
    decision = evaluate_position(
        policy=rug_only_policy(),
        holding=holding(),
        quote=quote("0.5"),
        state=PositionState(),
        rug=RugSignal(True, "pool drained"),
    )
    assert decision.kind is DecisionKind.EXIT_RUG
    assert decision.pnl_pct is None


def runner_policy(**overrides: object) -> PositionPolicy:
    return policy(take_profit_pct=Decimal("80"), **overrides)


def test_runner_arms_on_take_profit_without_selling() -> None:
    decision = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("1.9"),
        state=PositionState(),
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert decision.kind is DecisionKind.ACTIVATE_TRAIL
    assert decision.exits is False
    assert "lock-in floors" in decision.reason
    assert decision.next_state.original_amount == 1_000_000


def test_runner_does_not_arm_on_bonding_curve() -> None:
    decision = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("3.0"),
        state=PositionState(),
        rug=RugSignal(False),
        pump_complete=False,
    )
    assert decision.kind is DecisionKind.HOLD
    assert "graduation" in decision.reason
    assert decision.next_state.trailing_active is False


def test_runner_holds_a_five_x_through_a_thirty_percent_wick() -> None:
    """A 20% peak leash would sell 5.0 → 3.5. The lock floor at 5x is 2.20."""

    armed = PositionState(
        trailing_active=True,
        trailing_peak_unit_price_sol=Decimal("5.0"),
        original_amount=1_000_000,
        scale_rungs_fired=(rung_key(Decimal("2.0")), rung_key(Decimal("4.0"))),
    )
    wick = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("3.5"),
        state=armed,
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert wick.kind is DecisionKind.HOLD
    assert wick.next_state.below_floor_streak == 0
    assert wick.next_state.runner_floor_multiple == Decimal("2.20")


def test_runner_floor_needs_two_quotes_before_full_exit() -> None:
    armed = PositionState(
        trailing_active=True,
        trailing_peak_unit_price_sol=Decimal("5.0"),
        original_amount=1_000_000,
        scale_rungs_fired=(rung_key(Decimal("2.0")), rung_key(Decimal("4.0"))),
    )
    first = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("2.1"),
        state=armed,
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert first.kind is DecisionKind.HOLD
    assert first.next_state.below_floor_streak == 1
    second = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("2.05"),
        state=first.next_state,
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert second.kind is DecisionKind.EXIT_TRAIL
    assert second.full_exit is True
    assert "2.20x" in second.reason


def test_preexisting_trail_does_not_replay_scale_rungs() -> None:
    """Live bags already trailing must not dump 30% the night we ship runner."""

    armed = PositionState(
        trailing_active=True,
        trailing_peak_unit_price_sol=Decimal("5.0"),
    )
    decision = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("4.8"),
        state=armed,
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert decision.kind is DecisionKind.HOLD
    assert decision.sell_amount is None
    assert decision.next_state.original_amount == 1_000_000
    assert rung_key(Decimal("2.0")) in decision.next_state.scale_rungs_fired
    assert rung_key(Decimal("4.0")) in decision.next_state.scale_rungs_fired
    assert "not replayed" in decision.reason


def test_runner_scale_out_banks_thirty_percent_at_two_x() -> None:
    armed = PositionState(
        trailing_active=True,
        trailing_peak_unit_price_sol=Decimal("1.9"),
        original_amount=1_000_000,
    )
    decision = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("2.1"),
        state=armed,
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert decision.kind is DecisionKind.EXIT_SCALE
    assert decision.sell_amount == 300_000
    assert decision.full_exit is False
    assert rung_key(Decimal("2.0")) in decision.next_state.scale_rungs_fired


def test_runner_does_not_refire_a_spent_scale_rung() -> None:
    armed = PositionState(
        trailing_active=True,
        trailing_peak_unit_price_sol=Decimal("2.4"),
        original_amount=1_000_000,
        scale_rungs_fired=(rung_key(Decimal("2.0")),),
    )
    decision = evaluate_position(
        policy=runner_policy(),
        holding=holding(),
        quote=quote("2.3"),
        state=armed,
        rug=RugSignal(False),
        pump_complete=True,
    )
    assert decision.kind is DecisionKind.HOLD
    assert decision.sell_amount is None


def test_rug_only_policy_holds_without_emergency_even_with_quote() -> None:
    decision = evaluate_position(
        policy=rug_only_policy(),
        holding=holding(),
        quote=quote("0.5"),
        state=PositionState(),
        rug=RugSignal(False),
    )
    assert decision.kind is DecisionKind.HOLD
    assert decision.pnl_pct is None
