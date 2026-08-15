"""Meteora's public data API. Keyless, read-only, GET-only.

Endpoint set and field semantics come from `scripts/meteora_lp_report.py`, which probed the
live service rather than trusting Meteora's published OpenAPI spec (the documented host
`dlmm-api.meteora.ag` is dead and three spec'd paths 404 on the deployed service). The two
traps that file paid for and this one inherits:

  On `/portfolio/open`, `tokenX`/`tokenY` are human SYMBOLS. On `/positions/{pool}/pnl` the
  same key names hold MINTS. Read the wrong one and you compare a symbol to an address.

  `allTimeFees` is fees ALREADY CLAIMED, not lifetime earned. Unclaimed fees are a separate
  quantity under `unrealizedPnl.unclaimedFee{X,Y}`.

The datapi is used for VALUATION only -- prices, USD balances, the portfolio rollup. Every
number a transaction is built from (active bin, bin step, mints, which bin arrays exist) is
read from chain in `rpc.py`. A vendor cache being thirty seconds stale is fine for deciding
that $315 should become $200; it is not fine for deciding which bin id to deposit into.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Final

API_BASE: Final[str] = "https://dlmm.datapi.meteora.ag"
USER_AGENT: Final[str] = "joshibot-lpexec/0.1 (read-only)"
REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0


class DataApiError(RuntimeError):
    pass


def to_float(value: Any) -> float | None:
    """Coerce, or return None. Never returns 0.0 for a missing field."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def dig(payload: Any, *path: str) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def fetch_json(path: str, params: dict[str, Any] | None = None, *, base: str = API_BASE) -> Any:
    url = f"{base}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise DataApiError(f"GET {url} -> HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DataApiError(f"GET {url} failed: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DataApiError(f"GET {url} returned non-JSON ({len(body)} bytes)") from exc


@dataclass(frozen=True, slots=True)
class LivePosition:
    """One open position as the datapi reports it, with only what a plan needs."""

    position_address: str
    pool_address: str
    lower_bin_id: int
    upper_bin_id: int
    active_bin_id: int
    token_x_mint: str
    token_y_mint: str
    token_x_symbol: str
    token_y_symbol: str
    bin_step: int
    amount_x: float
    amount_y: float
    value_x_usd: float | None
    value_y_usd: float | None
    unclaimed_x: float
    unclaimed_y: float
    total_value_usd: float | None
    out_of_range: bool


@dataclass(frozen=True, slots=True)
class Portfolio:
    wallet: str
    sol_price_usd: float | None
    positions: tuple[LivePosition, ...]
    total_value_usd: float | None


def _positions_for_pool(pool: dict[str, Any], wallet: str, *, base: str) -> list[LivePosition]:
    address = str(pool.get("poolAddress") or "")
    if not address:
        return []
    payload = fetch_json(
        f"/positions/{address}/pnl",
        {"user": wallet, "status": "open", "page_size": 50},
        base=base,
    )
    entries = dig(payload, "positions")
    if not isinstance(entries, list):
        return []
    out: list[LivePosition] = []
    for raw in entries:
        if not isinstance(raw, dict) or raw.get("isClosed"):
            continue
        out.append(
            LivePosition(
                position_address=str(raw.get("positionAddress") or ""),
                pool_address=address,
                lower_bin_id=int(raw.get("lowerBinId", 0)),
                upper_bin_id=int(raw.get("upperBinId", 0)),
                active_bin_id=int(raw.get("poolActiveBinId", 0)),
                # Mints on THIS endpoint; symbols only on /portfolio/open. See module docstring.
                token_x_mint=str(raw.get("tokenX") or pool.get("tokenXMint") or ""),
                token_y_mint=str(raw.get("tokenY") or pool.get("tokenYMint") or ""),
                token_x_symbol=str(pool.get("tokenX") or "?"),
                token_y_symbol=str(pool.get("tokenY") or "?"),
                bin_step=int(pool.get("binStep", 0)),
                amount_x=to_float(dig(raw, "unrealizedPnl", "balanceTokenX", "amount")) or 0.0,
                amount_y=to_float(dig(raw, "unrealizedPnl", "balanceTokenY", "amount")) or 0.0,
                value_x_usd=to_float(dig(raw, "unrealizedPnl", "balanceTokenX", "usd")),
                value_y_usd=to_float(dig(raw, "unrealizedPnl", "balanceTokenY", "usd")),
                unclaimed_x=to_float(dig(raw, "unrealizedPnl", "unclaimedFeeTokenX", "amount")) or 0.0,
                unclaimed_y=to_float(dig(raw, "unrealizedPnl", "unclaimedFeeTokenY", "amount")) or 0.0,
                total_value_usd=to_float(dig(raw, "unrealizedPnl", "balances")),
                out_of_range=bool(raw.get("isOutOfRange")),
            )
        )
    return out


def fetch_portfolio(wallet: str, *, base: str = API_BASE) -> Portfolio:
    positions: list[LivePosition] = []
    sol_price: float | None = None
    total: float | None = None
    page = 1
    while True:
        payload = fetch_json("/portfolio/open", {"user": wallet, "page": page, "page_size": 50}, base=base)
        if not isinstance(payload, dict):
            break
        if page == 1:
            sol_price = to_float(payload.get("solPrice"))
            total = to_float(dig(payload, "total", "balances"))
        for pool in payload.get("pools") or []:
            if isinstance(pool, dict):
                positions.extend(_positions_for_pool(pool, wallet, base=base))
        if not payload.get("hasNext"):
            break
        page += 1
        if page > 40:
            break
    return Portfolio(
        wallet=wallet, sol_price_usd=sol_price, positions=tuple(positions), total_value_usd=total
    )


@dataclass(frozen=True, slots=True)
class PoolState:
    address: str
    name: str
    bin_step: int
    token_x_mint: str
    token_y_mint: str
    token_x_price_usd: float | None
    token_y_price_usd: float | None
    token_x_amount: float
    token_y_amount: float
    current_price: float | None
    decimals_x: int
    decimals_y: int
    fee_tvl_24h_pct: float | None

    @property
    def is_empty(self) -> bool:
        """A pool with nothing in it. Laddering into one is posting asks to an empty room."""
        return self.token_x_amount <= 0.0 and self.token_y_amount <= 0.0


def fetch_pool(address: str, *, base: str = API_BASE) -> PoolState:
    payload = fetch_json(f"/pools/{address}", base=base)
    if not isinstance(payload, dict):
        raise DataApiError(f"pool {address} returned a non-object payload")
    return PoolState(
        address=str(payload.get("address") or address),
        name=str(payload.get("name") or "?"),
        bin_step=int(dig(payload, "pool_config", "bin_step") or 0),
        token_x_mint=str(dig(payload, "token_x", "address") or ""),
        token_y_mint=str(dig(payload, "token_y", "address") or ""),
        token_x_price_usd=to_float(dig(payload, "token_x", "price")),
        token_y_price_usd=to_float(dig(payload, "token_y", "price")),
        token_x_amount=to_float(payload.get("token_x_amount")) or 0.0,
        token_y_amount=to_float(payload.get("token_y_amount")) or 0.0,
        current_price=to_float(payload.get("current_price")),
        decimals_x=int(dig(payload, "token_x", "decimals") or 0),
        decimals_y=int(dig(payload, "token_y", "decimals") or 0),
        fee_tvl_24h_pct=to_float(dig(payload, "fee_tvl_ratio", "24h")),
    )
