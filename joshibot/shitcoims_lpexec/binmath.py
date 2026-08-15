"""DLMM bin arithmetic, and the rent a plan owes before it is allowed to propose anything.

BINS. A DLMM prices bin `i` at `(1 + bin_step/10_000)^i` in RAW token ratio, which becomes a
UI price after the decimal correction `10^(decimals_x - decimals_y)`. Bins strictly ABOVE the
active bin hold only token X; bins strictly BELOW hold only token Y; the active bin holds
both. That one sentence is the whole of one-sided laddering: to sell X you deposit X into
bins above spot and wait for someone to buy it.

Every constant below is READ FROM the Meteora SDK (`@meteora-ag/dlmm@1.9.14`), not estimated
and not copied from a blog post -- `tests/test_lpexec.py::test_rent_constants_match_the_meteora_sdk`
re-reads them from `node_modules` and fails if the SDK moves under us.

RENT, and why it gets its own section in every plan. Three kinds, and conflating them is how
an LP programme quietly loses money:

  POSITION rent, 0.05740608 SOL -- REFUNDABLE. Comes back in full when the position closes.
    `studies/RESULT_lp_history.md` used exactly this number as the fingerprint that
    identified 42 historical positions, so it is confirmed against the operator's own chain
    history, not just against the SDK.

  BIN ARRAY rent, 0.07143744 SOL per array -- NOT REFUNDABLE TO US. A bin array covers 70
    bins and is a shared, permissionless account: whoever touches a virgin range pays to
    create it and everyone after that uses it free. You are subsidising the pool. At
    $75.40/SOL that is $5.39 per array, which on a $115 trim is 4.7% -- large enough that
    "which bins" is an economic question, not a formatting one.

  ATA rent, 0.00203928 SOL per token account -- refundable on close.

A ladder placed across a virgin range can therefore cost more in bin-array rent than it earns
in fees for weeks. `quote_rent` prices it before the plan is printed, and `planner.py` refuses
a plan whose non-refundable rent exceeds `MAX_RENT_SHARE_OF_DEPLOYED` of the value deployed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

LAMPORTS_PER_SOL: Final[int] = 1_000_000_000

# --- from @meteora-ag/dlmm@1.9.14 ---------------------------------------------------------
POSITION_RENT_LAMPORTS: Final[int] = 57_406_080  # POSITION_FEE_BN; refundable on close
BIN_ARRAY_RENT_LAMPORTS: Final[int] = 71_437_440  # BIN_ARRAY_FEE_BN; NOT refundable to us
TOKEN_ACCOUNT_RENT_LAMPORTS: Final[int] = 2_039_280  # TOKEN_ACCOUNT_FEE_BN; refundable
BIN_ARRAY_BITMAP_RENT_LAMPORTS: Final[int] = 11_804_160  # BIN_ARRAY_BITMAP_FEE
BINS_PER_ARRAY: Final[int] = 70  # MAX_BIN_ARRAY_SIZE
MAX_BINS_PER_TX: Final[int] = 26  # MAX_BIN_LENGTH_ALLOWED_IN_ONE_TX
MAX_BINS_PER_POSITION: Final[int] = 1_400
BASIS_POINT_MAX: Final[int] = 10_000
# ------------------------------------------------------------------------------------------

# Beyond this bin id the price is outside anything the program can represent.
MAX_BIN_ID: Final[int] = 443_636
MIN_BIN_ID: Final[int] = -443_636


def bin_price_raw(bin_id: int, bin_step: int) -> float:
    """Raw token-Y-per-token-X ratio at a bin, before decimal correction."""
    return (1.0 + bin_step / BASIS_POINT_MAX) ** bin_id


def bin_price_ui(bin_id: int, bin_step: int, *, decimals_x: int, decimals_y: int) -> float:
    """The price a human reads: units of Y per whole unit of X."""
    return bin_price_raw(bin_id, bin_step) * (10.0 ** (decimals_x - decimals_y))


def price_to_bin_id(
    price_ui: float, bin_step: int, *, decimals_x: int, decimals_y: int, round_up: bool = False
) -> int:
    """Invert `bin_price_ui`. `round_up` picks the first bin at or above the target price."""
    if price_ui <= 0.0:
        raise ValueError("price must be positive")
    raw = price_ui / (10.0 ** (decimals_x - decimals_y))
    exact = math.log(raw) / math.log(1.0 + bin_step / BASIS_POINT_MAX)
    # Snap first. `log(pow(r, n)) / log(r)` lands microscopically under `n` for large |n|,
    # so a bare floor() returns bin 33 for the exact price of bin 34 -- a whole bin of error
    # from one ULP. The snap makes the inverse exact on prices that came from `bin_price_ui`
    # and leaves genuinely between-bin prices to floor/ceil as asked.
    nearest = round(exact)
    on_a_bin = abs(exact - nearest) < 1e-9
    bin_id = nearest if on_a_bin else (math.ceil(exact) if round_up else math.floor(exact))
    return max(MIN_BIN_ID, min(MAX_BIN_ID, int(bin_id)))


def bin_array_index(bin_id: int) -> int:
    """Which shared 70-bin array a bin lives in. Floor division, so negatives work."""
    return bin_id // BINS_PER_ARRAY


def bin_array_indexes(lower_bin_id: int, upper_bin_id: int) -> tuple[int, ...]:
    """The arrays a bin range geometrically occupies."""
    if upper_bin_id < lower_bin_id:
        raise ValueError("upper bin id is below the lower bin id")
    return tuple(range(bin_array_index(lower_bin_id), bin_array_index(upper_bin_id) + 1))


def deposit_bin_array_indexes(lower_bin_id: int, upper_bin_id: int) -> tuple[int, ...]:
    """The arrays a DEPOSIT actually creates, which is not the same set.

    Meteora's add-liquidity instructions take a `bin_array_lower` AND a `bin_array_upper`
    account, and the SDK resolves the upper one as `max(index(upper), index(lower) + 1)` --
    so a range that fits entirely inside ONE array still causes the NEXT array to be
    initialised, at 0.0714 SOL that never comes back.

    This function existed as `bin_array_indexes` and was wrong, and the wrongness was found
    the only way it could be: `cli.py` prices every plan twice, once here and once through
    the SDK's own `quoteCreatePosition`, and refuses to proceed when they disagree. On the
    nosis/SOL ladder both said zero new arrays and agreed for the wrong reason -- array -8
    happened to exist. On a weave/SOL range inside array -5 the SDK said one and we said
    zero, because array -4 does not exist. A model that agrees on the easy case and diverges
    on the real one is exactly what a second derivation is for.
    """
    lower = bin_array_index(lower_bin_id)
    upper = max(bin_array_index(upper_bin_id), lower + 1)
    return tuple(range(lower, upper + 1))


@dataclass(frozen=True, slots=True)
class RentQuote:
    """What a plan costs in account rent, split by whether it ever comes back.

    `refundable` returns on close; `non_refundable` does not, ever, and is the number that
    belongs in an expected-value calculation. Reporting one total for both is the mistake
    this split exists to prevent.
    """

    position_lamports: int
    bin_array_lamports: int
    token_account_lamports: int
    new_bin_arrays: tuple[int, ...]
    positions_opened: int

    @property
    def refundable(self) -> int:
        return self.position_lamports + self.token_account_lamports

    @property
    def non_refundable(self) -> int:
        return self.bin_array_lamports

    @property
    def total(self) -> int:
        return self.refundable + self.non_refundable

    def as_sol(self, lamports: int) -> float:
        return lamports / LAMPORTS_PER_SOL

    def describe(self, sol_price_usd: float | None = None) -> str:
        def money(lamports: int) -> str:
            sol = lamports / LAMPORTS_PER_SOL
            if sol_price_usd is None:
                return f"{sol:.6f} SOL"
            return f"{sol:.6f} SOL (${sol * sol_price_usd:,.2f})"

        parts = [
            f"position rent {money(self.position_lamports)} refundable",
            f"bin-array rent {money(self.bin_array_lamports)} NOT refundable "
            f"({len(self.new_bin_arrays)} new array(s) {list(self.new_bin_arrays)})",
        ]
        if self.token_account_lamports:
            parts.append(f"ATA rent {money(self.token_account_lamports)} refundable")
        parts.append(f"total {money(self.total)}")
        return "; ".join(parts)


def quote_rent(
    *,
    lower_bin_id: int,
    upper_bin_id: int,
    existing_bin_arrays: frozenset[int],
    opens_position: bool,
    new_token_accounts: int = 0,
) -> RentQuote:
    """Price a bin range against what already exists on chain.

    `existing_bin_arrays` must come from an actual `getMultipleAccounts` on the derived bin
    array PDAs. Assuming a range is virgin over-prices it and assuming it is populated
    under-prices it; only the chain knows, and `rpc.py::existing_bin_arrays` asks.
    """
    needed = (
        deposit_bin_array_indexes(lower_bin_id, upper_bin_id)
        if opens_position
        else bin_array_indexes(lower_bin_id, upper_bin_id)
    )
    virgin = tuple(index for index in needed if index not in existing_bin_arrays)
    return RentQuote(
        position_lamports=POSITION_RENT_LAMPORTS if opens_position else 0,
        bin_array_lamports=BIN_ARRAY_RENT_LAMPORTS * len(virgin),
        token_account_lamports=TOKEN_ACCOUNT_RENT_LAMPORTS * new_token_accounts,
        new_bin_arrays=virgin,
        positions_opened=1 if opens_position else 0,
    )
