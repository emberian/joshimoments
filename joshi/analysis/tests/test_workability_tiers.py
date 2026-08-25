"""The tier-latency decomposition: legs, floors, survival, movement shares."""

from decimal import Decimal

from joshi_analysis.scalplab.tape import TapeEvent
from joshi_analysis.workability.tiers import (
    TierDecomposition,
    decompose,
    leg_survives,
    movement_shares,
    pivots,
    up_legs,
)

HOUR_US = 3_600_000_000


def event(
    ordinal: int,
    price: str,
    slot: int | None,
    time_us: int | None = None,
    side: str = "buy",
    trader: str = "t",
    quote: str = "1",
) -> TapeEvent:
    sign = Decimal(1) if side == "buy" else Decimal(-1)
    return TapeEvent(
        ordinal=ordinal,
        mint="M",
        side=side,
        price=Decimal(price),
        fill_price=None,
        base_signed=sign,
        quote_signed=sign * Decimal(quote),
        trader=trader,
        venue="pump_amm",
        tx=f"tx{ordinal}",
        slot=slot,
        event_time_us=time_us if time_us is not None else ordinal * 1_000_000,
        arrival_wall_us=None,
    )


def path(prices_slots: list[tuple[str, int]]) -> list[TapeEvent]:
    return [event(i, p, s) for i, (p, s) in enumerate(prices_slots)]


class TestPivots:
    def test_monotone_path_has_only_endpoints(self):
        prices = [Decimal(p) for p in ("1", "2", "3", "4")]
        assert pivots(prices) == [0, 3]

    def test_reversals_pivot_at_the_first_touch_of_the_extreme(self):
        # Equal prices extend the run; the pivot is the FIRST index at the extreme price,
        # so a tier delay is measured from the earliest instant the extreme was printed.
        prices = [Decimal(p) for p in ("1", "2", "2", "1", "3")]
        assert pivots(prices) == [0, 1, 3, 4]

    def test_flat_path_is_one_pivot(self):
        prices = [Decimal("5")] * 4
        assert pivots(prices) == [0]

    def test_empty_path(self):
        assert pivots([]) == []


class TestUpLegs:
    def test_v_shape_yields_one_up_leg(self):
        prices = [Decimal(p) for p in ("3", "1", "4")]
        legs = up_legs(prices)
        assert len(legs) == 1
        assert (legs[0].trough_index, legs[0].peak_index) == (1, 2)

    def test_floor_clearing_is_exact_decimal(self):
        prices = [Decimal("1.0000"), Decimal("1.0250")]
        (leg,) = up_legs(prices)
        assert leg.clears(250)  # exactly 250 bps clears at >=
        assert not leg.clears(251)


class TestTierSurvival:
    def test_same_slot_entry_survives_when_next_print_shares_the_slot(self):
        events = path([("1.00", 100), ("1.01", 100), ("1.10", 101)])
        (leg,) = up_legs([e.price for e in events])
        assert leg_survives(events, leg, tier_slots=0, floor_bps=250)

    def test_same_slot_is_unavailable_once_the_slot_closes(self):
        events = path([("1.00", 100), ("1.10", 103)])
        (leg,) = up_legs([e.price for e in events])
        assert not leg_survives(events, leg, tier_slots=0, floor_bps=250)

    def test_delayed_entry_eats_the_early_rise(self):
        # Trough at slot 100. A +2 actor enters at slot 102 (price 1.01) and the rise to
        # 1.10 still clears; a +32 actor first sees slot 132 (price 1.08), where the
        # remaining ~185 bps is under the 250 bps floor.
        events = path([("1.00", 100), ("1.01", 102), ("1.08", 132), ("1.10", 140)])
        (leg,) = up_legs([e.price for e in events])
        assert leg_survives(events, leg, tier_slots=2, floor_bps=250)
        assert not leg_survives(events, leg, tier_slots=32, floor_bps=250)

    def test_slotless_trough_is_unavailable_at_every_tier(self):
        events = path([("1.00", 100), ("2.00", 108)])
        slotless = [
            event(0, "1.00", None),
            events[1],
        ]
        (leg,) = up_legs([e.price for e in slotless])
        assert not leg_survives(slotless, leg, tier_slots=0, floor_bps=250)
        assert not leg_survives(slotless, leg, tier_slots=8, floor_bps=250)


class TestMovementShares:
    def test_intra_slot_share_splits_by_slot_membership(self):
        events = path([("1", 100), ("2", 100), ("4", 101)])
        share, total = movement_shares(events)
        assert total > 0
        assert share is not None
        # log2 within the slot, log2 across: exactly half the movement is intra-slot.
        assert abs(share - 0.5) < 1e-12

    def test_no_movement_reports_absent_share_not_zero(self):
        events = path([("1", 100), ("1", 101)])
        share, total = movement_shares(events)
        assert share is None
        assert total == 0.0


class TestDecompose:
    def test_rates_carry_their_denominator(self):
        events = [
            event(0, "1.00", 100, time_us=0),
            event(1, "1.01", 100, time_us=HOUR_US // 2),
            event(2, "1.10", 100, time_us=HOUR_US),  # one hour span
        ]
        result = decompose(events, floor_bps=250)
        assert isinstance(result, TierDecomposition)
        assert result.span_hours == 1.0
        assert result.n_clearing_legs == 1
        assert result.clearing_legs_per_hour == 1.0
        assert result.surviving_per_hour_by_tier[0] == 1.0  # same-slot next print
        assert result.surviving_per_hour_by_tier[32] == 0.0

    def test_zero_span_yields_absent_rates_never_zero(self):
        events = [event(0, "1.00", 100, time_us=0), event(1, "1.10", 100, time_us=0)]
        result = decompose(events, floor_bps=250)
        assert result.span_hours is None
        assert result.clearing_legs_per_hour is None
        assert result.n_clearing_legs == 1
