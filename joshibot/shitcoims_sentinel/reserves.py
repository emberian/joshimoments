"""A min-out derived from the pool we are actually selling into.

`jupiter.slippage_bps: 1500` is a *tolerance*: a 15% budget an adversary is free to spend
in full, and on an exit large enough to move the pool it is precisely their unconstrained
optimum. A reserve-derived floor is a different kind of object — a statement about what the
pool must pay given its own arithmetic — and `shitcoims_kernel.fill` already implements it,
mirroring `kernel/Joshi/Fill.lean`, where the two properties this leans on are proved: the
output never exceeds the SOL reserve, and it is monotone in the amount sold.

Three things keep this honest, and all three are refusals rather than guesses:

- **Only constant-product pools.** `sellOut` is the CP curve. A CLMM/DLMM pool does not
  price that way, and modelling one as CP would produce a floor that is simply wrong. The
  DEX is named, and an unrecognised name means no check.
- **Only the standard base/WSOL shape.** `price_native` is the price of the BASE token in
  the quote asset. If our mint is not the base, or the quote is not WSOL, the number means
  something else and is not reinterpreted.
- **Only a fresh sample.** DexScreener is an aggregator with a lag. A stale snapshot is
  refused rather than aged into a floor, because a floor computed from an old pool can
  block a real exit.

When any of those fail, the result is None and the caller falls back to Jupiter's own
threshold — never to a fabricated floor. This is a sell-only system: an exit that does not
happen is a worse failure than an exit that pays a few basis points too many.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from shitcoims_kernel.fill import FillError, Reserves, minimum_out

from .domain import LAMPORTS_PER_SOL, WSOL_MINT, PoolSnapshot, TokenHolding, utc_now

# `sellOut` is the constant-product curve. pump.fun bonding curves and pumpswap/raydium
# v4 AMMs price that way; Meteora's DLMM and any concentrated-liquidity book do not.
CONSTANT_PRODUCT_DEX_IDS = frozenset({"pumpfun", "pumpswap", "raydium"})

# How far below the pool's own arithmetic an order may still be accepted. Covers the lag
# between the DexScreener sample and the Jupiter quote, and the fact that a split route can
# price a little differently from the primary pool. It is NOT a slippage budget: at 500 bps
# this is already a third of the 1500 the config allows, and it is one-sided — it only ever
# refuses an order that pays LESS than the observed pool should.
RESERVE_DRIFT_ALLOWANCE_BPS = 500

# Older than this and the pool sample is not evidence about the pool we are selling into.
MAX_POOL_SAMPLE_AGE_SECONDS = 120


def reserves_from_pool(
    pool: PoolSnapshot | None, holding: TokenHolding, *, now: dt.datetime | None = None
) -> Reserves | None:
    """Integer pool reserves for `holding`'s mint, or None when they cannot be known."""

    if pool is None or pool.dex_id not in CONSTANT_PRODUCT_DEX_IDS:
        return None
    if pool.base_mint != holding.mint or pool.quote_mint != WSOL_MINT:
        return None
    if pool.reserve_unit != "SOL" or pool.price_native is None:
        return None
    if pool.reserve_value <= 0 or pool.price_native <= 0:
        return None
    age = ((now or utc_now()) - pool.observed_at).total_seconds()
    if age < 0 or age > MAX_POOL_SAMPLE_AGE_SECONDS:
        return None

    sol_lamports = int(pool.reserve_value * LAMPORTS_PER_SOL)
    # price_native is SOL per WHOLE token; the reserve ratio is in RAW units.
    lamports_per_raw = (
        pool.price_native * LAMPORTS_PER_SOL / (Decimal(10) ** holding.decimals)
    )
    if lamports_per_raw <= 0:
        return None
    token_raw = int(Decimal(sol_lamports) / lamports_per_raw)
    if token_raw <= 0 or sol_lamports <= 0:
        return None
    try:
        return Reserves(token_raw=token_raw, sol_lamports=sol_lamports)
    except FillError:
        return None


def reserve_minimum_out(
    pool: PoolSnapshot | None,
    holding: TokenHolding,
    amount: int,
    *,
    drift_bps: int = RESERVE_DRIFT_ALLOWANCE_BPS,
    now: dt.datetime | None = None,
) -> int | None:
    """Least lamports this sale should return, computed from the pool. None if unknowable."""

    reserves = reserves_from_pool(pool, holding, now=now)
    if reserves is None or amount <= 0:
        return None
    try:
        floor = minimum_out(reserves, amount, slippage_bps=drift_bps)
    except FillError:
        return None
    return floor if floor > 0 else None
