"""Server-side price history. The browser never talks to Dex/Gecko directly."""

from __future__ import annotations

import time
from typing import Any

import httpx
from solders.pubkey import Pubkey

DEXSCREENER = "https://api.dexscreener.com/latest/dex/tokens"
INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_SECONDS = 20
WINDOWS = (("m5", 5 * 60), ("h1", 3600), ("h6", 6 * 3600), ("h24", 86400))


class CandleError(ValueError):
    pass


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _bars_from_windows(price: float, change: dict[str, Any], now: int) -> list[dict[str, float | int]]:
    points: list[tuple[int, float]] = [(now, price)]
    for key, seconds in WINDOWS:
        pct = _num(change.get(key))
        if pct is None or pct <= -100:
            continue
        prior = price / (1 + pct / 100)
        points.append((now - seconds, prior))
    points.sort()
    bars: list[dict[str, float | int]] = []
    for timestamp, close in points:
        bars.append({"t": timestamp, "o": close, "h": close, "l": close, "c": close, "v": 0})
    return bars


async def fetch_candles(
    http: httpx.AsyncClient,
    mint: str,
    *,
    interval: str = "15m",
    limit: int = 120,
) -> dict[str, Any]:
    try:
        mint = str(Pubkey.from_string(mint.strip()))
    except Exception as exc:
        raise CandleError("mint is not a Solana public key") from exc
    if interval not in INTERVALS:
        raise CandleError("unsupported interval")
    cache_key = f"{mint}:{interval}:{limit}"
    cached = _CACHE.get(cache_key)
    now_mono = time.monotonic()
    if cached and now_mono - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        response = await http.get(f"{DEXSCREENER}/{mint}", timeout=12)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        raise CandleError(f"candle source unavailable ({type(exc).__name__})") from exc
    pairs = body.get("pairs") if isinstance(body, dict) else None
    if not isinstance(pairs, list) or not pairs:
        raise CandleError("no DexScreener pair for this mint")
    pair = next(
        (item for item in pairs if isinstance(item, dict) and item.get("chainId") == "solana"),
        pairs[0],
    )
    if not isinstance(pair, dict):
        raise CandleError("DexScreener pair schema changed")
    price = _num(pair.get("priceUsd"))
    if price is None:
        raise CandleError("DexScreener pair has no USD price")
    change = pair.get("priceChange") if isinstance(pair.get("priceChange"), dict) else {}
    volume = pair.get("volume") if isinstance(pair.get("volume"), dict) else {}
    liquidity = pair.get("liquidity") if isinstance(pair.get("liquidity"), dict) else {}
    now = int(time.time())
    result = {
        "mint": mint,
        "interval": interval,
        "source": "dexscreener-windows",
        "pair": str(pair.get("pairAddress", ""))[:64],
        "dex": str(pair.get("dexId", ""))[:32],
        "stats": {
            "price_usd": price,
            "change_m5": _num(change.get("m5")),
            "change_h1": _num(change.get("h1")),
            "change_h6": _num(change.get("h6")),
            "change_h24": _num(change.get("h24")),
            "volume_h24": _num(volume.get("h24")),
            "liquidity_usd": _num(liquidity.get("usd")),
            "fdv": _num(pair.get("fdv")),
        },
        "bars": _bars_from_windows(price, change, now)[-max(10, min(int(limit), 250)) :],
    }
    _CACHE[cache_key] = (now_mono, result)
    return result
