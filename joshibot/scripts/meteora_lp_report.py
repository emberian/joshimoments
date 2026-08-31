#!/usr/bin/env python3
"""Dissipation harvest meter: a read-only reporter for Meteora DLMM LP positions.

The operator LPs Meteora DLMM pools between community tokens and reports "harvesting
significant fees" -- but until now there was no instrument that turned that claim into a
number. This is that instrument. It reads, it prints, it touches nothing.

READ-ONLY BY CONSTRUCTION. Every request is an unauthenticated HTTP GET against Meteora's
public data API. There is no key, no keypair, no signing, no transaction construction, and
no write path anywhere in this file. It cannot move funds because it has no mechanism to.

WHAT THE API ACTUALLY SERVES (probed live 2026-08-13, not taken from docs)
-------------------------------------------------------------------------
The historically documented host `dlmm-api.meteora.ag` is DEAD: the origin still answers
(Cloudflare, HTTP/2) but every path under it -- /pair/all, /pair/{addr}, /position/{addr},
/wallet/{w}/... -- returns 404 with a zero-byte body. The live API moved to:

    https://dlmm.datapi.meteora.ag        {"service":"Meteora DLMM API","status":"ok"}

Endpoints this reporter uses, all verified working:

  GET /portfolio/open?user={wallet}         open positions, grouped by pool, + rollup total
  GET /positions/{pool_address}/pnl?user={wallet}&status=open
                                            THE goldmine: per-position bin range as prices,
                                            lower/upper/active bin ids, out-of-range flag,
                                            all-time deposits/withdrawals/fees, live token
                                            balances, and unclaimed fees per token
  GET /portfolio/total?user={wallet}        realized PnL rollup over closed positions
  GET /positions/{address}/historical       per-position event log (add/remove/claim_fee)

Endpoints that are documented in Meteora's own published OpenAPI spec but return 404 on the
deployed service -- i.e. spec drift, do not rely on them:

  GET /wallets/{wallet}/open_positions      404
  GET /wallets/{wallet}/closed_positions    404
  GET /positions/{address}/total_claim_fees 404

The last one matters: there is no single-call "total fees claimed" number. We get it anyway,
because `allTimeFees` on the pnl endpoint is exactly the claimed-to-date total -- verified by
summing the `claim_fee` events from /positions/{addr}/historical for two live positions and
matching to 15 significant figures. See CLAIMED VS UNCLAIMED below.

CLAIMED VS UNCLAIMED (the semantic that makes or breaks the number)
--------------------------------------------------------------------
`allTimeFees` is fees ALREADY CLAIMED. It is NOT lifetime fees earned. The fees sitting in
the position right now are a separate quantity, `unrealizedPnl.unclaimedFee{X,Y}`. So:

    lifetime fees earned = allTimeFees + unclaimed

Reading `allTimeFees` as "total earned" undercounts every position with pending fees, and
reading it as "still claimable" is the same error inverted. This file keeps them apart and
reports all three.

THE FEE RATE (the dissipation harvest rate)
--------------------------------------------
    fee_rate_per_day = lifetime_fees_usd / position_value_usd / age_days

computed here from first principles rather than trusting the API's own `feePerTvl24h`, which
is reported alongside it for cross-check. Both are extrapolations. A position minutes old
produces an enormous and meaningless daily rate, so every rate carries the age of the sample
that produced it and rates from windows shorter than MIN_CONFIDENT_AGE_DAYS are flagged.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

API_BASE = "https://dlmm.datapi.meteora.ag"
USER_AGENT = "joshibot-meteora-lp-report/1.0 (read-only)"
REQUEST_TIMEOUT_SECONDS = 30.0

# A fee rate extrapolated from a very short window is arithmetic, not evidence. Rates derived
# from a sample shorter than this are still shown -- suppressing them would hide the position
# entirely -- but they are marked so nobody annualizes a twenty-minute sample by accident.
MIN_CONFIDENT_AGE_DAYS = 1.0

SECONDS_PER_DAY = 86400.0

# Meteora's own zero-address sentinel, used for "this pool has no reward mint".
NULL_MINT = "11111111111111111111111111111111"


class MeteoraApiError(RuntimeError):
    """A public-API read failed in a way the caller should see rather than guess about."""


# --------------------------------------------------------------------------------------
# Coercion helpers.
#
# The API returns numbers as JSON strings in some places ("1.6804439959601196") and as JSON
# numbers in others (1.8759149441802206e-06), sometimes null, and occasionally the key is
# simply absent -- a closed position has no `unrealizedPnl` block at all. Every read of an
# API value goes through these so a missing field degrades to None instead of exploding.
# --------------------------------------------------------------------------------------


def to_float(value: Any) -> float | None:
    """Coerce an API scalar to float, returning None for anything not numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            result = float(text)
        except ValueError:
            return None
    else:
        return None
    # NaN/inf would poison every downstream sum silently.
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def dig(payload: Any, *path: str) -> Any:
    """Walk a nested dict by key path, returning None the moment the path stops existing."""
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def dig_float(payload: Any, *path: str) -> float | None:
    return to_float(dig(payload, *path))


def _sum_present(values: list[float | None]) -> float | None:
    """Sum the values that exist. Returns None only if every one is missing.

    A rollup over positions where one position is missing a field should still report the
    others rather than collapsing the whole portfolio total to None.
    """
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


# --------------------------------------------------------------------------------------
# The two pieces of real arithmetic, kept pure and separately testable.
# --------------------------------------------------------------------------------------


def is_in_range(lower_bin_id: int | None, upper_bin_id: int | None, active_bin_id: int | None) -> bool | None:
    """Is the pool's active bin inside this position's bin range?

    A DLMM position earns fees only while the pool trades within the bins it holds liquidity
    in. The range is inclusive at both ends: a position spanning [-33, 1] with the pool active
    at bin 1 is still in range and still earning.

    Computed here rather than read from the API's `isOutOfRange` on purpose -- this is the one
    number that decides whether the position is working or parked, so the reporter derives it
    and then cross-checks the API's flag against it (see PositionReport.range_flag_conflict).
    Returns None when any input is missing, rather than guessing "in range".
    """
    if lower_bin_id is None or upper_bin_id is None or active_bin_id is None:
        return None
    low, high = (lower_bin_id, upper_bin_id) if lower_bin_id <= upper_bin_id else (upper_bin_id, lower_bin_id)
    return low <= active_bin_id <= high


def fee_rate_per_day(fees_usd: float | None, value_usd: float | None, age_days: float | None) -> float | None:
    """Fees earned per dollar of position value per day -- the dissipation harvest rate.

    Returns a fraction (0.05 == 5%/day), not a percentage. None when any input is missing or
    when the denominator would be zero or negative: a position with no value and no age has
    no meaningful rate, and 'infinity percent per day' is a worse answer than 'unknown'.
    """
    if fees_usd is None or value_usd is None or age_days is None:
        return None
    if value_usd <= 0.0 or age_days <= 0.0:
        return None
    return fees_usd / value_usd / age_days


def annualized(rate_per_day: float | None) -> float | None:
    """Simple (uncompounded) annualization of a daily rate. Deliberately not APY.

    Compounding a daily fee rate assumes fees are continuously redeposited at the same rate
    into a pool whose price never leaves the position's bins. For a two-token volatile pair
    that assumption is false, so this stays linear and the caller is told it is an
    extrapolation rather than a forecast.
    """
    if rate_per_day is None:
        return None
    return rate_per_day * 365.0


# --------------------------------------------------------------------------------------
# Report shapes.
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class TokenLeg:
    """One side of a position: how much of the token, and what it is worth."""

    symbol: str | None = None
    mint: str | None = None
    amount: float | None = None
    usd: float | None = None


@dataclass(slots=True)
class PositionReport:
    position_address: str | None = None
    pool_address: str | None = None
    pair: str | None = None

    # Bin geometry. The range is reported as prices (what the operator thinks in) with the
    # raw bin ids kept alongside, because the in/out-of-range decision is made on bin ids.
    min_price: float | None = None
    max_price: float | None = None
    active_price: float | None = None
    lower_bin_id: int | None = None
    upper_bin_id: int | None = None
    active_bin_id: int | None = None
    in_range: bool | None = None
    # True when our own bin arithmetic disagrees with the API's isOutOfRange flag. Should
    # always be False; if it is ever True the report says so loudly rather than picking one.
    range_flag_conflict: bool = False

    # Live value.
    token_x: TokenLeg = field(default_factory=TokenLeg)
    token_y: TokenLeg = field(default_factory=TokenLeg)
    value_usd: float | None = None
    value_sol: float | None = None

    # Fees, kept strictly separate (see module docstring).
    unclaimed_fees_usd: float | None = None
    unclaimed_fee_x: TokenLeg = field(default_factory=TokenLeg)
    unclaimed_fee_y: TokenLeg = field(default_factory=TokenLeg)
    claimed_fees_usd: float | None = None
    claimed_fee_x_amount: float | None = None
    claimed_fee_y_amount: float | None = None
    lifetime_fees_usd: float | None = None

    # Capital flows.
    deposits_usd: float | None = None
    withdrawals_usd: float | None = None
    pnl_usd: float | None = None
    pnl_pct: float | None = None

    # Time and rate.
    created_at: int | None = None
    updated_at: int | None = None
    age_days: float | None = None
    fee_rate_per_day: float | None = None
    fee_rate_annualized: float | None = None
    rate_is_thin: bool = False
    api_fee_per_tvl_24h: float | None = None

    is_closed: bool = False


@dataclass(slots=True)
class PortfolioReport:
    wallet: str = ""
    positions: list[PositionReport] = field(default_factory=list)
    total_value_usd: float | None = None
    total_unclaimed_usd: float | None = None
    total_claimed_usd: float | None = None
    total_lifetime_fees_usd: float | None = None
    total_deposits_usd: float | None = None
    open_pnl_usd: float | None = None
    portfolio_fee_rate_per_day: float | None = None
    realized_pnl_usd: float | None = None
    realized_pnl_sol: float | None = None
    closed_position_count: int | None = None
    sol_price_usd: float | None = None
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Parsing. Pure: dict in, dataclass out. The tests drive these directly with fixtures.
# --------------------------------------------------------------------------------------


def parse_position(
    raw: dict[str, Any],
    *,
    pool_context: dict[str, Any] | None = None,
    now_epoch_seconds: float | None = None,
) -> PositionReport:
    """Turn one entry of /positions/{pool}/pnl `positions[]` into a PositionReport.

    `pool_context` is the matching pool entry from /portfolio/open, which carries the human
    token symbols and the pool address; the pnl endpoint returns mints only. It is optional
    because the pnl endpoint alone is enough to produce a valid (if less readable) report.
    """
    pool_context = pool_context or {}
    report = PositionReport()

    report.position_address = dig(raw, "positionAddress")
    report.pool_address = dig(pool_context, "poolAddress")
    report.is_closed = bool(dig(raw, "isClosed"))

    symbol_x = dig(pool_context, "tokenX")
    symbol_y = dig(pool_context, "tokenY")
    mint_x = dig(raw, "tokenX") or dig(pool_context, "tokenXMint")
    mint_y = dig(raw, "tokenY") or dig(pool_context, "tokenYMint")
    if symbol_x and symbol_y:
        report.pair = f"{symbol_x}/{symbol_y}"

    # --- bin geometry -------------------------------------------------------------
    report.min_price = dig_float(raw, "minPrice")
    report.max_price = dig_float(raw, "maxPrice")
    report.active_price = dig_float(raw, "poolActivePrice")
    report.lower_bin_id = _as_int(dig(raw, "lowerBinId"))
    report.upper_bin_id = _as_int(dig(raw, "upperBinId"))
    report.active_bin_id = _as_int(dig(raw, "poolActiveBinId"))

    computed = is_in_range(report.lower_bin_id, report.upper_bin_id, report.active_bin_id)
    api_out_of_range = dig(raw, "isOutOfRange")
    if computed is None and isinstance(api_out_of_range, bool):
        # No bin ids to work with; fall back to the API's own verdict rather than nothing.
        report.in_range = not api_out_of_range
    else:
        report.in_range = computed
        if computed is not None and isinstance(api_out_of_range, bool):
            report.range_flag_conflict = computed == api_out_of_range

    # --- live value ---------------------------------------------------------------
    unrealized = dig(raw, "unrealizedPnl") or {}
    report.value_usd = to_float(dig(unrealized, "balances"))
    report.value_sol = dig_float(unrealized, "balancesSol")
    report.token_x = TokenLeg(
        symbol=symbol_x,
        mint=mint_x,
        amount=dig_float(unrealized, "balanceTokenX", "amount"),
        usd=dig_float(unrealized, "balanceTokenX", "usd"),
    )
    report.token_y = TokenLeg(
        symbol=symbol_y,
        mint=mint_y,
        amount=dig_float(unrealized, "balanceTokenY", "amount"),
        usd=dig_float(unrealized, "balanceTokenY", "usd"),
    )

    # --- fees ---------------------------------------------------------------------
    report.unclaimed_fee_x = TokenLeg(
        symbol=symbol_x,
        mint=mint_x,
        amount=dig_float(unrealized, "unclaimedFeeTokenX", "amount"),
        usd=dig_float(unrealized, "unclaimedFeeTokenX", "usd"),
    )
    report.unclaimed_fee_y = TokenLeg(
        symbol=symbol_y,
        mint=mint_y,
        amount=dig_float(unrealized, "unclaimedFeeTokenY", "amount"),
        usd=dig_float(unrealized, "unclaimedFeeTokenY", "usd"),
    )
    report.unclaimed_fees_usd = _sum_present([report.unclaimed_fee_x.usd, report.unclaimed_fee_y.usd])

    # allTimeFees is CLAIMED-to-date, not lifetime earned. Verified against the claim_fee
    # event log on live positions; see the module docstring.
    report.claimed_fees_usd = dig_float(raw, "allTimeFees", "total", "usd")
    report.claimed_fee_x_amount = dig_float(raw, "allTimeFees", "tokenX", "amount")
    report.claimed_fee_y_amount = dig_float(raw, "allTimeFees", "tokenY", "amount")
    report.lifetime_fees_usd = _sum_present([report.claimed_fees_usd, report.unclaimed_fees_usd])

    # --- flows --------------------------------------------------------------------
    report.deposits_usd = dig_float(raw, "allTimeDeposits", "total", "usd")
    report.withdrawals_usd = dig_float(raw, "allTimeWithdrawals", "total", "usd")
    report.pnl_usd = dig_float(raw, "pnlUsd")
    report.pnl_pct = dig_float(raw, "pnlPctChange")

    # --- time and rate ------------------------------------------------------------
    report.created_at = _as_int(dig(raw, "createdAt"))
    report.updated_at = _as_int(dig(raw, "updatedAt"))
    closed_at = _as_int(dig(raw, "closedAt"))

    # The rate is measured over the window the position was actually alive: creation to close
    # for a closed position, creation to now for an open one. Using "now" for a position that
    # closed last week would silently dilute its rate toward zero.
    end_epoch = closed_at if (report.is_closed and closed_at) else now_epoch_seconds
    if report.created_at is not None and end_epoch is not None:
        elapsed = float(end_epoch) - float(report.created_at)
        report.age_days = elapsed / SECONDS_PER_DAY if elapsed > 0 else 0.0

    # Rate denominator: current value for an open position. A closed position has no live
    # value, so fall back to what was deposited -- the capital that did the earning.
    rate_basis = report.value_usd if report.value_usd else report.deposits_usd
    report.fee_rate_per_day = fee_rate_per_day(report.lifetime_fees_usd, rate_basis, report.age_days)
    report.fee_rate_annualized = annualized(report.fee_rate_per_day)
    report.rate_is_thin = report.age_days is not None and report.age_days < MIN_CONFIDENT_AGE_DAYS

    api_rate = dig_float(raw, "feePerTvl24h")
    # The API reports this as a percent per 24h; normalize to a fraction to match ours.
    report.api_fee_per_tvl_24h = api_rate / 100.0 if api_rate is not None else None

    return report


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def build_portfolio(
    wallet: str,
    positions: list[PositionReport],
    *,
    portfolio_total: dict[str, Any] | None = None,
    open_total: dict[str, Any] | None = None,
) -> PortfolioReport:
    """Roll individual positions up, and fold in the API's own portfolio-level totals."""
    report = PortfolioReport(wallet=wallet, positions=positions)

    report.total_value_usd = _sum_present([p.value_usd for p in positions])
    report.total_unclaimed_usd = _sum_present([p.unclaimed_fees_usd for p in positions])
    report.total_claimed_usd = _sum_present([p.claimed_fees_usd for p in positions])
    report.total_lifetime_fees_usd = _sum_present([p.lifetime_fees_usd for p in positions])
    report.total_deposits_usd = _sum_present([p.deposits_usd for p in positions])
    report.open_pnl_usd = _sum_present([p.pnl_usd for p in positions])

    # Portfolio fee rate is value-weighted by construction: total fees over total value over
    # a value-weighted mean age. Averaging the per-position rates instead would let a tiny
    # minutes-old position with an astronomical rate dominate the whole number.
    weighted_age = _weighted_mean_age(positions)
    report.portfolio_fee_rate_per_day = fee_rate_per_day(
        report.total_lifetime_fees_usd, report.total_value_usd, weighted_age
    )

    if portfolio_total:
        report.realized_pnl_usd = dig_float(portfolio_total, "totalPnlUsd")
        report.realized_pnl_sol = dig_float(portfolio_total, "totalPnlSol")
        report.closed_position_count = _as_int(dig(portfolio_total, "totalClosedPositions"))
    if open_total:
        report.sol_price_usd = dig_float(open_total, "solPrice")

    return report


def _weighted_mean_age(positions: list[PositionReport]) -> float | None:
    pairs = [(p.age_days, p.value_usd) for p in positions if p.age_days and p.value_usd]
    if not pairs:
        # No value weights available: fall back to a plain mean over whatever ages exist.
        ages = [p.age_days for p in positions if p.age_days]
        return sum(ages) / len(ages) if ages else None
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return None
    return sum(age * weight for age, weight in pairs) / total_weight


# --------------------------------------------------------------------------------------
# Network. Isolated here so every function above stays testable without a socket.
# --------------------------------------------------------------------------------------


def fetch_json(path: str, params: dict[str, Any] | None = None, *, base: str = API_BASE) -> Any:
    """Unauthenticated GET against the public data API. The only network call in this file."""
    url = f"{base}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise MeteoraApiError(f"GET {url} -> HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise MeteoraApiError(f"GET {url} failed: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise MeteoraApiError(f"GET {url} returned non-JSON ({len(body)} bytes)") from exc


def fetch_open_pools(wallet: str, *, base: str = API_BASE) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Page through /portfolio/open, returning every pool entry plus the rollup total."""
    pools: list[dict[str, Any]] = []
    envelope: dict[str, Any] = {}
    page = 1
    while True:
        payload = fetch_json("/portfolio/open", {"user": wallet, "page": page, "page_size": 50}, base=base)
        if not isinstance(payload, dict):
            break
        if page == 1:
            envelope = payload
        batch = payload.get("pools")
        if isinstance(batch, list):
            pools.extend(entry for entry in batch if isinstance(entry, dict))
        if not payload.get("hasNext"):
            break
        page += 1
        if page > 40:  # Defensive: never loop forever on a misbehaving hasNext.
            break
    return pools, envelope


def fetch_positions_for_pool(
    pool_address: str, wallet: str, *, base: str = API_BASE
) -> list[dict[str, Any]]:
    payload = fetch_json(
        f"/positions/{pool_address}/pnl",
        {"user": wallet, "status": "open", "page_size": 50},
        base=base,
    )
    entries = dig(payload, "positions")
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def collect_report(wallet: str, *, base: str = API_BASE, now_epoch_seconds: float) -> PortfolioReport:
    pools, envelope = fetch_open_pools(wallet, base=base)

    positions: list[PositionReport] = []
    notes: list[str] = []
    for pool in pools:
        pool_address = pool.get("poolAddress")
        if not pool_address:
            continue
        try:
            raw_positions = fetch_positions_for_pool(str(pool_address), wallet, base=base)
        except MeteoraApiError as exc:
            notes.append(f"pool {pool_address}: position detail unavailable ({exc})")
            continue
        for raw in raw_positions:
            positions.append(
                parse_position(raw, pool_context=pool, now_epoch_seconds=now_epoch_seconds)
            )

    portfolio_total: dict[str, Any] | None = None
    try:
        fetched = fetch_json("/portfolio/total", {"user": wallet}, base=base)
        if isinstance(fetched, dict):
            portfolio_total = fetched
    except MeteoraApiError as exc:
        notes.append(f"realized PnL rollup unavailable ({exc})")

    report = build_portfolio(
        wallet, positions, portfolio_total=portfolio_total, open_total=envelope.get("total") or envelope
    )
    if envelope.get("solPrice") is not None:
        report.sol_price_usd = to_float(envelope.get("solPrice"))
    report.notes.extend(notes)
    return report


# --------------------------------------------------------------------------------------
# Rendering.
# --------------------------------------------------------------------------------------


def _usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def _num(value: float | None, places: int = 6) -> str:
    if value is None:
        return "n/a"
    if value != 0 and abs(value) < 1e-4:
        return f"{value:.3e}"
    return f"{value:,.{places}f}".rstrip("0").rstrip(".")


def _pct(fraction: float | None) -> str:
    if fraction is None:
        return "n/a"
    return f"{fraction * 100:,.2f}%"


def render_text(report: PortfolioReport) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("METEORA DLMM -- DISSIPATION HARVEST METER")
    lines.append(f"wallet: {report.wallet}")
    if report.sol_price_usd:
        lines.append(f"SOL: {_usd(report.sol_price_usd)}")
    lines.append("=" * 78)

    if not report.positions:
        lines.append("")
        lines.append("No OPEN DLMM positions found for this wallet.")
        if report.closed_position_count:
            lines.append(
                f"({report.closed_position_count} closed positions on record, "
                f"realized PnL {_usd(report.realized_pnl_usd)})"
            )
        lines.append("")
        return "\n".join(lines)

    for index, position in enumerate(report.positions, start=1):
        lines.append("")
        lines.append(f"[{index}] {position.pair or 'unknown pair'}")
        lines.append(f"    pool     {position.pool_address}")
        lines.append(f"    position {position.position_address}")

        if position.in_range is None:
            range_state = "RANGE UNKNOWN"
        elif position.in_range:
            range_state = "IN RANGE (earning)"
        else:
            range_state = "OUT OF RANGE (idle)"
        lines.append(
            f"    bins     [{position.lower_bin_id}, {position.upper_bin_id}] "
            f"active={position.active_bin_id}  {range_state}"
        )
        lines.append(
            f"    prices   {_num(position.min_price)} -> {_num(position.max_price)} "
            f"(now {_num(position.active_price)})"
        )
        if position.range_flag_conflict:
            lines.append("    !! our bin arithmetic DISAGREES with the API's isOutOfRange flag")

        x, y = position.token_x, position.token_y
        lines.append(
            f"    value    {_usd(position.value_usd)}  =  "
            f"{_num(x.amount, 4)} {x.symbol or '?'} ({_usd(x.usd)}) + "
            f"{_num(y.amount, 4)} {y.symbol or '?'} ({_usd(y.usd)})"
        )
        lines.append(f"    deposited{_usd(position.deposits_usd):>12}")
        lines.append(
            f"    UNCLAIMED{_usd(position.unclaimed_fees_usd):>12}  =  "
            f"{_num(position.unclaimed_fee_x.amount, 4)} {x.symbol or '?'} + "
            f"{_num(position.unclaimed_fee_y.amount, 4)} {y.symbol or '?'}"
        )
        lines.append(f"    claimed  {_usd(position.claimed_fees_usd):>12}   (already harvested)")
        lines.append(f"    lifetime {_usd(position.lifetime_fees_usd):>12}   (claimed + unclaimed)")
        pnl_pct = f"   ({position.pnl_pct:+.2f}%)" if position.pnl_pct is not None else ""
        lines.append(f"    PnL      {_usd(position.pnl_usd):>12}{pnl_pct}")

        age = f"{position.age_days:.3f}d" if position.age_days is not None else "n/a"
        lines.append(f"    age      {age}")
        thin = "  << THIN SAMPLE, do not annualize" if position.rate_is_thin else ""
        lines.append(
            f"    HARVEST  {_pct(position.fee_rate_per_day)}/day of position value{thin}"
        )
        lines.append(
            f"             (simple annualized {_pct(position.fee_rate_annualized)}; "
            f"API feePerTvl24h {_pct(position.api_fee_per_tvl_24h)})"
        )

    lines.append("")
    lines.append("-" * 78)
    lines.append("PORTFOLIO")
    lines.append("-" * 78)
    lines.append(f"  open positions      {len(report.positions)}")
    lines.append(f"  total value         {_usd(report.total_value_usd)}")
    lines.append(f"  total deposited     {_usd(report.total_deposits_usd)}")
    lines.append(f"  UNCLAIMED fees      {_usd(report.total_unclaimed_usd)}   <-- harvestable now")
    lines.append(f"  claimed to date     {_usd(report.total_claimed_usd)}   (open positions only)")
    lines.append(f"  lifetime fees       {_usd(report.total_lifetime_fees_usd)}")
    lines.append(f"  open PnL            {_usd(report.open_pnl_usd)}")
    lines.append(
        f"  HARVEST RATE        {_pct(report.portfolio_fee_rate_per_day)}/day "
        f"(simple annualized {_pct(annualized(report.portfolio_fee_rate_per_day))})"
    )
    if report.realized_pnl_usd is not None:
        lines.append(
            f"  realized PnL        {_usd(report.realized_pnl_usd)} "
            f"over {report.closed_position_count} closed positions"
        )
    for note in report.notes:
        lines.append(f"  note: {note}")
    lines.append("")
    return "\n".join(lines)


def render_json(report: PortfolioReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=False)


# --------------------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Meteora DLMM LP position and fee reporter (dissipation harvest meter).",
    )
    parser.add_argument("wallet", help="Solana wallet address that owns the DLMM positions")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON instead of text")
    parser.add_argument("--api-base", default=API_BASE, help=f"API base URL (default: {API_BASE})")
    args = parser.parse_args(argv)

    import time

    try:
        report = collect_report(args.wallet, base=args.api_base, now_epoch_seconds=time.time())
    except MeteoraApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(render_json(report) if args.as_json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
