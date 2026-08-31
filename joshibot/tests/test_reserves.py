"""A min-out that is a statement about the pool, not a budget an adversary may spend.

`jupiter.slippage_bps: 1500` is a tolerance: on a clip large enough to move the pool, 15%
is the attacker's unconstrained optimum, and nothing in the transaction says otherwise.
These tests pin the replacement — a floor computed from observed reserves through the
Lean-mirrored constant-product fill — and, just as important, pin every case where the
model refuses to produce a number rather than producing a wrong one.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from shitcoims_kernel.fill import Reserves, sell_out
from shitcoims_sentinel.domain import WSOL_MINT, PoolSnapshot, TokenHolding
from shitcoims_sentinel.reserves import (
    MAX_POOL_SAMPLE_AGE_SECONDS,
    RESERVE_DRIFT_ALLOWANCE_BPS,
    reserve_minimum_out,
    reserves_from_pool,
)

MINT = "5jUwEEKMawc1q1GCEKLgCYA77jbGfVvjz21nEpJrpump"
NOW = dt.datetime(2026, 8, 15, 12, 0, tzinfo=dt.timezone.utc)
DECIMALS = 6


def holding(amount: int = 1_000_000) -> TokenHolding:
    return TokenHolding(MINT, amount, DECIMALS, ("account",), ("program",))


def pool(**overrides) -> PoolSnapshot:
    fields = {
        "pair_address": "pair",
        "dex_id": "pumpswap",
        "base_mint": MINT,
        "quote_mint": WSOL_MINT,
        "liquidity_usd": Decimal("7495.55"),
        # 40 SOL against 400,000,000 whole tokens: 1e-7 SOL each.
        "reserve_value": Decimal("40"),
        "reserve_unit": "SOL",
        "price_native": Decimal("0.0000001"),
        "observed_at": NOW,
    }
    fields.update(overrides)
    return PoolSnapshot(**fields)


def test_reserves_are_derived_in_raw_units_from_the_sol_side_and_the_price() -> None:
    reserves = reserves_from_pool(pool(), holding(), now=NOW)
    assert reserves is not None
    assert reserves.sol_lamports == 40_000_000_000
    # 40 SOL / 1e-7 SOL per whole token = 4e8 whole tokens = 4e14 raw at 6 decimals.
    assert reserves.token_raw == 400_000_000 * 10**DECIMALS


def test_the_floor_is_the_pools_own_arithmetic_less_a_drift_allowance() -> None:
    """Not a percentage of the quote: a number the pool's reserves imply on their own."""

    amount = 5_000 * 10**DECIMALS
    reserves = reserves_from_pool(pool(), holding(amount), now=NOW)
    assert reserves is not None
    expected = sell_out(reserves, amount)
    floor = reserve_minimum_out(pool(), holding(amount), amount, now=NOW)
    assert floor == expected * (10_000 - RESERVE_DRIFT_ALLOWANCE_BPS) // 10_000
    assert 0 < floor < expected


def test_a_bigger_clip_gets_a_lower_unit_price_because_impact_is_deterministic() -> None:
    """The property the Lean side proves: monotone in the amount, so impact is priced."""

    small = 1_000 * 10**DECIMALS
    large = 4_000_000 * 10**DECIMALS
    small_floor = reserve_minimum_out(pool(), holding(small), small, now=NOW)
    large_floor = reserve_minimum_out(pool(), holding(large), large, now=NOW)
    assert small_floor is not None and large_floor is not None
    assert large_floor > small_floor
    # Per token, the large clip is worth strictly less. A blanket tolerance cannot see this.
    assert Decimal(large_floor) / large < Decimal(small_floor) / small


def test_a_non_constant_product_pool_produces_no_floor_at_all() -> None:
    """A DLMM does not price on the CP curve, and a wrong floor can block a real exit."""

    for dex_id in ("meteora", "orca", "unknown", ""):
        assert reserves_from_pool(pool(dex_id=dex_id), holding(), now=NOW) is None


def test_an_unusual_pair_shape_is_refused_rather_than_reinterpreted() -> None:
    # price_native prices the BASE token; if our mint is not the base it means something else.
    assert reserves_from_pool(pool(base_mint="other"), holding(), now=NOW) is None
    # A non-WSOL quote makes the SOL-side reserve not a SOL-side reserve.
    assert reserves_from_pool(pool(quote_mint="other", reserve_unit="USD"), holding(), now=NOW) is None
    assert reserves_from_pool(pool(price_native=None), holding(), now=NOW) is None
    assert reserves_from_pool(pool(reserve_value=Decimal("0")), holding(), now=NOW) is None


def test_a_stale_pool_sample_is_not_aged_into_a_floor() -> None:
    fresh = NOW + dt.timedelta(seconds=MAX_POOL_SAMPLE_AGE_SECONDS)
    stale = NOW + dt.timedelta(seconds=MAX_POOL_SAMPLE_AGE_SECONDS + 1)
    assert reserves_from_pool(pool(), holding(), now=fresh) is not None
    assert reserves_from_pool(pool(), holding(), now=stale) is None
    # A sample from the future is not evidence either.
    assert reserves_from_pool(pool(), holding(), now=NOW - dt.timedelta(seconds=1)) is None


def test_no_pool_means_no_floor_never_a_guess() -> None:
    assert reserves_from_pool(None, holding(), now=NOW) is None
    assert reserve_minimum_out(None, holding(), 1_000, now=NOW) is None
    assert reserve_minimum_out(pool(), holding(), 0, now=NOW) is None


def test_the_floor_never_exceeds_the_sol_side_of_the_pool() -> None:
    """From `Joshi.Reserves.sellOut_le_reserve`: an exit budget has to mean something."""

    enormous = 10**24
    floor = reserve_minimum_out(pool(), holding(enormous), enormous, now=NOW)
    assert floor is not None
    assert floor < 40_000_000_000
    assert floor <= sell_out(Reserves(400_000_000 * 10**DECIMALS, 40_000_000_000), enormous)
