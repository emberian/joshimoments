"""Runner lock-in floors. Not a percent leash off the peak.

A fixed trailing_stop_pct of peak is an equity technique. On a 50%+ vol
meme it sells the rent-payer: a 10x that wicks 22% then goes to 20x is
gone at 7.8x. The 2 SOL → 18 SOL path is a handful of survived 4-10x
bags, not a Sharpe engine, so the exit has to stop capping the right tail.

This module never looks at wallets or signs. It maps *achieved multiple*
(peak unit / entry) onto an *absolute floor in multiple-space*. Peak
picks the rung. The sale trigger is "current multiple is at or below
that floor", not "N% off the print high". The gap between peak and
floor *widens* as the multiple grows, which is the opposite of a
constant-% trail.

``runner_tightness`` is a tightness knob around the canonical table,
not the sale trigger. 20 is the table as written. 10 pulls floors
toward the peak. 40 pushes them down. It is not "trail 10% / 40%".
None is not a number at all: it means this bag has no trailing
behaviour of any kind.

Scale-out rungs are fractions of the *original* lot. They bank cost
so one later rug cannot unwind the book. The residual rides the floor.

The old ``fixed_trail`` style -- sell at N% off the print high -- is
gone, along with the ``exit_style`` field that selected it. One field
meaning a peak leash under one style and a tightness knob under the
other is how a rule stops being reasonable-about.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

CANONICAL_TIGHTNESS = Decimal("20")

# (peak multiple reached, floor multiple). Sorted ascending by peak.
# Give-back as a fraction of peak *increases* with the runner:
#   1.8x → floor 1.20x  (33% off peak; just keep a winner out of the red)
#   2.5x → floor 1.55x
#   4.0x → floor 2.20x  (cost out + some meat)
#   6.0x → floor 3.20x
#  10.0x → floor 5.00x  (a 40% wick at 10x is a hold)
#  16.0x → floor 8.00x
#  25.0x → floor 12.0x
LOCK_RUNGS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("1.8"), Decimal("1.20")),
    (Decimal("2.5"), Decimal("1.55")),
    (Decimal("4.0"), Decimal("2.20")),
    (Decimal("6.0"), Decimal("3.20")),
    (Decimal("10"), Decimal("5.00")),
    (Decimal("16"), Decimal("8.00")),
    (Decimal("25"), Decimal("12.0")),
)

# (peak multiple reached, fraction of the original lot to sell once).
# Fired keys are the peak multiple rendered by ``rung_key``.
SCALE_RUNGS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("2.0"), Decimal("0.30")),
    (Decimal("4.0"), Decimal("0.25")),
)

_MIN_FLOOR = Decimal("1.05")


def rung_key(multiple: Decimal) -> str:
    """Stable identity for a scale rung. 2.0 and 2.00 collapse."""

    normalized = Decimal(multiple).normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def lock_floor_multiple(
    peak_multiple: Decimal,
    *,
    tightness: Decimal = CANONICAL_TIGHTNESS,
) -> Decimal | None:
    """Highest floor whose peak threshold the runner has cleared.

    Returns None until the first rung (the bag is armed but has not
    yet earned a lock). Tightness 20 is the table. Below 20 tightens
    (floor moves toward peak). Above 20 loosens (floor drops). Floor
    never exceeds peak and never drops below ``_MIN_FLOOR``.
    """

    if peak_multiple <= 0:
        return None
    floor: Decimal | None = None
    for arm_at, rung_floor in LOCK_RUNGS:
        if peak_multiple >= arm_at:
            floor = rung_floor
        else:
            break
    if floor is None:
        return None
    scale = tightness / CANONICAL_TIGHTNESS if tightness > 0 else Decimal("1")
    gap = peak_multiple - floor
    adjusted = peak_multiple - gap * scale
    if adjusted >= peak_multiple:
        adjusted = floor
    if adjusted < _MIN_FLOOR:
        adjusted = _MIN_FLOOR
    if adjusted >= peak_multiple:
        return None
    return adjusted


def next_scale_fraction(
    peak_multiple: Decimal,
    fired: Sequence[str],
) -> tuple[Decimal, Decimal] | None:
    """First unfired scale rung the peak has reached.

    Returns ``(rung_multiple, fraction_of_original)`` or None.
    """

    seen = set(fired)
    for arm_at, fraction in SCALE_RUNGS:
        if peak_multiple >= arm_at and rung_key(arm_at) not in seen:
            return arm_at, fraction
    return None


def scale_sell_amount(
    *,
    original_amount: int,
    remaining_amount: int,
    fraction: Decimal,
) -> int:
    """Whole-token slice. Never the last token of the bag (the residual rides)."""

    if original_amount <= 0 or remaining_amount <= 1 or fraction <= 0:
        return 0
    raw = int(Decimal(original_amount) * fraction)
    sell = min(raw, remaining_amount - 1)
    return max(sell, 0)
