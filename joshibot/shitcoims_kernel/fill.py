"""Fast-path constant-product fill arithmetic, mirroring ``kernel/Joshi/Fill.lean``.

Every definition here is a transcription of the Lean one and must stay that way. When they
disagree the Lean side is right: it is the definition the theorems are about, and this file
inherits none of them.

Integers throughout, exactly as in the Lean. Python's ints are arbitrary-precision, so the
intermediate ``sol_lamports * amount`` — which overflows 64 bits for any realistic memecoin
balance — is exact here for the same reason it is exact in ``Nat``.
"""

from __future__ import annotations

from dataclasses import dataclass


class FillError(ValueError):
    """A fill query is malformed. Never answered with a guess."""


@dataclass(frozen=True, slots=True)
class Reserves:
    """Pool state in on-chain integer units. Never a price.

    Mirrors ``Joshi.Reserves``. pump.fun bonding curves carry virtual reserves that vanish at
    migration, so a replay that stores only the real side will misprice exactly the events
    around graduation, which is where the dumps concentrate.
    """

    token_raw: int
    sol_lamports: int

    def __post_init__(self) -> None:
        if isinstance(self.token_raw, bool) or isinstance(self.sol_lamports, bool):
            raise FillError("reserves must be integers, not bools")
        if not isinstance(self.token_raw, int) or not isinstance(self.sol_lamports, int):
            raise FillError("reserves must be integers; a float here is a silent corruption")
        if self.token_raw < 0 or self.sol_lamports < 0:
            raise FillError("reserves must be non-negative")


def sell_out(reserves: Reserves, amount: int) -> int:
    """Lamports paid for selling ``amount`` raw tokens. Floor division, matching the chain.

    Mirrors ``Joshi.Reserves.sellOut``. The Lean side proves the two properties this relies
    on: the result never exceeds ``sol_lamports`` (so an exit budget means something), and it
    is monotone in ``amount`` (so a larger clip can never appear cheaper).
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise FillError("amount must be an integer")
    if amount < 0:
        raise FillError("amount must be non-negative")
    denominator = reserves.token_raw + amount
    if denominator == 0:
        return 0
    return reserves.sol_lamports * amount // denominator


def accepts(reserves: Reserves, amount: int, floor: int) -> bool:
    """Whether the pool pays at least ``floor``.

    Mirrors ``Joshi.accepts``. Because AMM impact is deterministic given reserves, this is
    decidable *before* signing — which is what makes a computed min-out a real bound rather
    than the blanket slippage tolerance it replaced.
    """
    if isinstance(floor, bool) or not isinstance(floor, int):
        raise FillError("floor must be an integer")
    return floor <= sell_out(reserves, amount)


def minimum_out(reserves: Reserves, amount: int, *, slippage_bps: int) -> int:
    """The min-out floor for a sale, as ``expected * (1 - slippage)``, in integer lamports.

    Computed from observed reserves rather than accepted as a blanket tolerance. A tolerance
    is a budget an adversary can spend; a reserve-derived floor is a statement about the pool.
    """
    if isinstance(slippage_bps, bool) or not isinstance(slippage_bps, int):
        raise FillError("slippage_bps must be an integer")
    if not 0 <= slippage_bps <= 10_000:
        raise FillError("slippage_bps must be in [0, 10000]")
    expected = sell_out(reserves, amount)
    return expected * (10_000 - slippage_bps) // 10_000
