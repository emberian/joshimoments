"""pump.fun polling feed for the shadow scalper.

Read-only, keyless, gentle: one listing call per poll plus detail refreshes only
for mints we are actively tracking. Every snapshot carries t_ingest (our clock)
and the platform's own created/last-trade timestamps (the event clock) — two
timestamps, always, per the Track B lesson that mixing them fabricates latencies.

The feed is deliberately isolated behind ``poll_listing`` / ``poll_mint`` so the
endpoint can be swapped without touching policy, book, or marking.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

from shitcoims_scalper.shadow import CurveState

BASE = "https://frontend-api-v3.pump.fun"
UA = "shitcoims-scalper-shadow/0.1 (read-only research)"

# Fresh curves start with 30 virtual SOL; SOL actually deposited is vsol - 30.
VIRTUAL_SOL_FLOOR_LAMPORTS = 30_000_000_000


@dataclass(frozen=True, slots=True)
class MintSnapshot:
    mint: str
    t_ingest_unix: float
    created_unix: float
    last_trade_unix: float | None
    vsol_lamports: int
    vtok_raw: int
    complete: bool

    @property
    def curve(self) -> CurveState:
        return CurveState(
            t_ingest_unix=self.t_ingest_unix,
            vsol_lamports=self.vsol_lamports,
            vtok_raw=self.vtok_raw,
        )

    def features(self) -> dict[str, float]:
        now = self.t_ingest_unix
        recency = (now - self.last_trade_unix) if self.last_trade_unix else 1e9
        sol_in_curve = max(0, self.vsol_lamports - VIRTUAL_SOL_FLOOR_LAMPORTS) / 1e9
        return {
            "age_s": now - self.created_unix,
            "trade_recency_s": max(0.0, recency),
            "sol_in_curve": sol_in_curve,
        }


def _get(url: str, timeout: float = 10.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _snapshot(coin: dict, t_ingest: float) -> MintSnapshot | None:
    try:
        vsol = int(coin["virtual_sol_reserves"])
        vtok = int(coin["virtual_token_reserves"])
        if vsol <= 0 or vtok <= 0:
            return None
        last_trade = coin.get("last_trade_timestamp")
        return MintSnapshot(
            mint=str(coin["mint"]),
            t_ingest_unix=t_ingest,
            created_unix=int(coin["created_timestamp"]) / 1000.0,
            last_trade_unix=(int(last_trade) / 1000.0) if last_trade else None,
            vsol_lamports=vsol,
            vtok_raw=vtok,
            complete=bool(coin.get("complete", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _listing(sort: str, limit: int) -> list[MintSnapshot]:
    url = f"{BASE}/coins?offset=0&limit={limit}&sort={sort}&order=DESC&includeNsfw=false"
    try:
        data = _get(url)
    except Exception:
        return []
    t = time.time()
    coins = data if isinstance(data, list) else []
    out = []
    for coin in coins:
        if isinstance(coin, dict):
            snap = _snapshot(coin, t)
            if snap is not None:
                out.append(snap)
    return out


def poll_listing(limit: int = 50) -> list[MintSnapshot]:
    """Two listings, deduped: newest-created AND recently-traded.

    The first smoke run proved created-DESC alone samples the nursery — coins
    seconds old with empty curves; 132 decisions, zero verdict passes. The
    coins actually matching a liveness filter are on the last_trade sort: the
    "looked alive enough" population the operator was clicking through by hand.
    """
    by_mint: dict[str, MintSnapshot] = {}
    for sort in ("created_timestamp", "last_trade_timestamp"):
        for snap in _listing(sort, limit):
            by_mint[snap.mint] = snap
    return list(by_mint.values())


def poll_mint(mint: str) -> MintSnapshot | None:
    """Refresh one tracked mint. None on any failure — the caller decides what a lost feed means."""
    try:
        data = _get(f"{BASE}/coins/{mint}")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _snapshot(data, time.time())
