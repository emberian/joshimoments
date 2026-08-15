"""Minute-resolution prices for callout mints, from GeckoTerminal.

Why not the board tape. `state/boards/` is the return machinery every other
study here uses, and for board-entry events it is the right one: the event is
*defined* by board membership. For a callout it is the wrong one twice over.
A callout mint is priced only while it sits in some board's top 50, so joining
on the board tape conditions the cohort on attention — which is downstream of
the callout and therefore a collider — and it makes "left the boards" look like
missing data when it is really an outcome.

GeckoTerminal prices a pool whether or not anyone is paying attention, which
removes the selection and lets a dying coin be *priced* rather than dropped.

Two facts about these candles that the study has to respect:

- **A missing minute is not a missing price, it is an absence of trades.** The
  API emits a candle only when the pool traded. Forward-filling the last close
  is therefore the correct mark (it is the last price at which anyone actually
  transacted) and it is never look-ahead. What it is *not* is a price you could
  have exited at, so the study reports fill-plausibility alongside the return.
- **`limit=1000` is 1000 candles, not 1000 minutes.** For a thin coin those
  thousand candles can span days. Coverage is checked per mint against the
  window actually needed, never assumed.

Supply on pump.fun is fixed at 1e9, so market cap is a constant multiple of
price and the two are interchangeable for returns.
"""

from __future__ import annotations

import argparse
import json
import json as _json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from studies.deterioration import GT

CACHE = Path(__file__).resolve().parent.parent / "state" / "callouts" / "prices"
RATE_STATE = CACHE.parent / "gt-pacing.json"
PUMP_SUPPLY = 1_000_000_000.0


class Fetcher:
    """Keyless GeckoTerminal pacing with its own on-disk clock.

    Deliberately not `deterioration.Fetcher`: that one shares a pacing file with
    the deterioration study, so two studies running at once each believe they
    are alone and together trip the per-IP limit. Measured 2026-08-15: the
    keyless tier serves about five requests and then returns 429 for a while,
    so the floor here is set from that measurement rather than from the
    documented 30/min, and it backs off multiplicatively but recovers slowly.
    """

    def __init__(self, min_interval: float = 4.0, verbose: bool = False) -> None:
        self.floor = min_interval
        self.min_interval = min_interval
        self.verbose = verbose
        self.calls = 0
        self.throttles = 0
        self.streak = 0

    def _wait(self) -> None:
        RATE_STATE.parent.mkdir(parents=True, exist_ok=True)
        try:
            last = _json.loads(RATE_STATE.read_text()).get("last", 0.0)
        except Exception:
            last = 0.0
        delta = time.time() - last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        RATE_STATE.write_text(_json.dumps({"last": time.time()}))

    def get(self, url: str, tries: int = 6) -> Any | None:
        for attempt in range(tries):
            self._wait()
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json;version=20230302",
                    "User-Agent": "joshibot-callout-study/0.1 (research; keyless)",
                },
            )
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=40) as resp:
                    payload = _json.loads(resp.read())
                self.streak += 1
                if self.streak >= 20 and self.min_interval > self.floor:
                    self.min_interval = max(self.floor, self.min_interval * 0.9)
                    self.streak = 0
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    self.throttles += 1
                    self.streak = 0
                    self.min_interval = min(self.min_interval * 1.3 + 0.5, 40.0)
                    wait = min(10.0 * (attempt + 1), 60.0)
                    if self.verbose:
                        print(
                            f"    429 -> interval {self.min_interval:.1f}s, sleep {wait:.0f}s",
                            file=sys.stderr,
                            flush=True,
                        )
                    time.sleep(wait)
                    continue
                if exc.code in (400, 404):
                    return None
                time.sleep(3.0 * (attempt + 1))
            except Exception:
                time.sleep(2.0 * (attempt + 1))
        return None


def _cache_path(mint: str) -> Path:
    return CACHE / f"{mint}.json"


def load_cached(mint: str) -> dict[str, Any] | None:
    path = _cache_path(mint)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def discover_pools(fetcher: Fetcher, mints: list[str]) -> dict[str, dict[str, Any]]:
    """Batch token lookup: 30 mints per call instead of one call per mint."""

    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(mints), 30):
        chunk = mints[start : start + 30]
        payload = fetcher.get(f"{GT}/networks/solana/tokens/multi/{','.join(chunk)}")
        for item in (payload or {}).get("data") or []:
            attrs = item.get("attributes") or {}
            address = attrs.get("address")
            if not address:
                continue
            pools = (
                ((item.get("relationships") or {}).get("top_pools") or {}).get("data") or []
            )
            found[address] = {
                "name": attrs.get("name"),
                "symbol": attrs.get("symbol"),
                "fdv_usd": attrs.get("fdv_usd"),
                "total_reserve_in_usd": attrs.get("total_reserve_in_usd"),
                "top_pools": [p.get("id", "") for p in pools],
            }
    return found


def fetch_candles(
    fetcher: Fetcher, pool_id: str, *, limit: int = 1000, before: int | None = None
) -> list[list[float]]:
    pool = pool_id.split("_")[-1]
    url = (
        f"{GT}/networks/solana/pools/{pool}/ohlcv/minute"
        f"?aggregate=1&limit={limit}&currency=usd&token=base"
    )
    if before is not None:
        url += f"&before_timestamp={int(before)}"
    payload = fetcher.get(url)
    rows = ((payload or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    # The API returns newest-first; the study wants a time-ordered series.
    return sorted((r for r in rows if isinstance(r, list) and len(r) >= 5), key=lambda r: r[0])


def pool_created_at(fetcher: Fetcher, pool_id: str) -> str | None:
    pool = pool_id.split("_")[-1]
    payload = fetcher.get(f"{GT}/networks/solana/networks/solana/pools/{pool}")
    attrs = ((payload or {}).get("data") or {}).get("attributes") or {}
    return attrs.get("pool_created_at")


def collect(
    mints: Iterable[str],
    *,
    need_from: int,
    need_to: int,
    min_interval: float = 4.0,
    refresh: bool = False,
) -> dict[str, int]:
    """Fetch and cache candles covering [need_from, need_to] for each mint."""

    CACHE.mkdir(parents=True, exist_ok=True)
    todo = [m for m in dict.fromkeys(mints) if refresh or load_cached(m) is None]
    # Random order, fixed seed. The keyless tier is slow enough that a run can
    # be interrupted, and a *prefix* of the callout stream is a biased cohort
    # (early hours only) while a random subset of mints is not. Whatever the
    # collector finishes is therefore analysable as-is.
    random.Random(20260815).shuffle(todo)
    stats = {"requested": len(todo), "no_pool": 0, "no_candles": 0, "cached": 0, "covered": 0}
    if not todo:
        return stats
    fetcher = Fetcher(min_interval=min_interval, verbose=True)
    pools = discover_pools(fetcher, todo)
    for i, mint in enumerate(todo, 1):
        info = pools.get(mint)
        record: dict[str, Any] = {
            "mint": mint,
            "fetched_at": time.time(),
            "need_from": need_from,
            "need_to": need_to,
            "token": info,
            "pool_id": None,
            "candles": [],
        }
        if not info or not info["top_pools"]:
            stats["no_pool"] += 1
            _cache_path(mint).write_text(json.dumps(record, separators=(",", ":")))
            continue
        pool_id = info["top_pools"][0]
        record["pool_id"] = pool_id
        candles = fetch_candles(fetcher, pool_id)
        # Page backwards only while an older page actually extends the range.
        # Most of these coins were created *after* `need_from`, so a naive
        # "page until we reach need_from" loop spends four calls per mint
        # re-fetching the same first candle — it was the throughput bottleneck.
        guard = 0
        while candles and candles[0][0] > need_from and guard < 4:
            oldest = candles[0][0]
            older = fetch_candles(fetcher, pool_id, before=int(oldest))
            if not older or older[0][0] >= oldest:
                break  # the pool has no history before this; it is a new coin
            merged = sorted({tuple(c) for c in (*older, *candles)})
            candles = [list(c) for c in merged]
            guard += 1
        record["candles"] = candles
        if not candles:
            stats["no_candles"] += 1
        elif candles[0][0] <= need_from and candles[-1][0] >= need_to:
            stats["covered"] += 1
        _cache_path(mint).write_text(json.dumps(record, separators=(",", ":")))
        stats["cached"] += 1
        if i % 25 == 0:
            print(f"  prices {i}/{len(todo)} {stats}", flush=True)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--callouts", default="state/callouts/*.jsonl")
    ap.add_argument("--need-from", type=int, required=True)
    ap.add_argument("--need-to", type=int, required=True)
    ap.add_argument("--min-interval", type=float, default=4.0)
    ap.add_argument("--limit-mints", type=int, default=0)
    args = ap.parse_args()

    from studies.callout_edge import load_callouts

    rows = load_callouts(args.callouts)
    mints = [c["mint"] for c in rows]
    if args.limit_mints:
        mints = list(dict.fromkeys(mints))[: args.limit_mints]
    print(json.dumps(collect(mints, need_from=args.need_from, need_to=args.need_to,
                             min_interval=args.min_interval), indent=1))


if __name__ == "__main__":
    main()
