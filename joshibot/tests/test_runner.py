from decimal import Decimal

from shitcoims_sentinel.runner import (
    lock_floor_multiple,
    next_scale_fraction,
    rung_key,
    scale_sell_amount,
)


def test_lock_floor_widens_as_the_multiple_grows() -> None:
    """A 20% peak leash at 10x sells at 8x. The floor at 10x is 5x."""

    assert lock_floor_multiple(Decimal("1.7")) is None
    assert lock_floor_multiple(Decimal("1.8")) == Decimal("1.20")
    assert lock_floor_multiple(Decimal("5.0")) == Decimal("2.20")
    assert lock_floor_multiple(Decimal("10")) == Decimal("5.00")
    ten = lock_floor_multiple(Decimal("10"))
    assert ten is not None
    giveback = (Decimal("10") - ten) / Decimal("10")
    assert giveback > Decimal("0.40")


def test_five_x_wick_to_three_five_stays_above_floor() -> None:
    floor = lock_floor_multiple(Decimal("5.0"))
    assert floor is not None
    assert Decimal("3.5") > floor
    assert Decimal("2.1") <= floor


def test_tightness_is_not_a_percent_leash() -> None:
    peak = Decimal("10")
    canonical = lock_floor_multiple(peak, tightness=Decimal("20"))
    tighter = lock_floor_multiple(peak, tightness=Decimal("10"))
    looser = lock_floor_multiple(peak, tightness=Decimal("40"))
    assert canonical == Decimal("5.00")
    assert tighter is not None and canonical is not None and looser is not None
    assert tighter > canonical
    assert looser < canonical
    # 10 tightness is "closer to peak", not "trail 10% of 10x = 9x".
    assert tighter < Decimal("9")


def test_scale_rungs_fire_once_in_order() -> None:
    first = next_scale_fraction(Decimal("2.1"), ())
    assert first == (Decimal("2.0"), Decimal("0.30"))
    second = next_scale_fraction(Decimal("4.2"), (rung_key(Decimal("2.0")),))
    assert second == (Decimal("4.0"), Decimal("0.25"))
    done = next_scale_fraction(Decimal("12"), (rung_key(Decimal("2.0")), rung_key(Decimal("4.0"))))
    assert done is None


def test_scale_never_sells_the_last_token() -> None:
    full = scale_sell_amount(
        original_amount=1_000_000, remaining_amount=1_000_000, fraction=Decimal("0.30")
    )
    leftover = scale_sell_amount(
        original_amount=1_000_000, remaining_amount=200_000, fraction=Decimal("0.25")
    )
    dust = scale_sell_amount(
        original_amount=1_000_000, remaining_amount=1, fraction=Decimal("0.30")
    )
    assert full == 300_000
    assert leftover == 199_999
    assert dust == 0
