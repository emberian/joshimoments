#!/usr/bin/env python3
"""Build a mint sampling frame from pump.fun's public listing. Zero Helius credits.

Mint discovery is the cheapest part of a mint-indexed panel and it must not be paid for in
Helius credits: ``getSignaturesForAddress`` on the pump program would cost credits to learn
what a free public endpoint already publishes, and it would return trades rather than
launches. This reads ``frontend-api-v3.pump.fun/coins``, which carries ``mint``, ``creator``,
``created_timestamp``, ``complete`` (the bonding curve finished) and a market cap, and costs
nothing.

**The listing is NOT a census, and this script measures that rather than assuming it.** Two
sweeps taken two minutes apart, restricted to the same 28.5-minute creation window, each
returned 700 mints and each was missing 218 of the other's — Jaccard 0.525. So one sweep sees
roughly 69% of the launches in its window and a different 69% each time. The fix is repeated
sweeps unioned over a window every sweep covers, with the residual estimated by Chao1 rather
than asserted away; ``--audit`` prints it. Measured on this listing, coverage runs 0.708 at
two sweeps, 0.923 at three, and reaches no-singletons at **four**, where 913 mints over a
27.0-minute window are each seen at least twice. A frame built from one sweep would silently
be a ~69% sample of its own stated population, and would also understate the launch rate by
26% (2,029/hour observed against ~1,500/hour listed in a single pass).

Usage:

    scripts/pumpfun_frame.py sweep  --out DIR [--sort created_timestamp] [--complete]
    scripts/pumpfun_frame.py build  --sweeps DIR --out FRAME.jsonl --stratum cohort
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shitcoims_tape.panel import FrameMint, frame_coverage, write_frame

LISTING = "https://frontend-api-v3.pump.fun/coins"
HEADERS = {"User-Agent": "Mozilla/5.0"}
#: The listing stops serving rows somewhere past offset 800, so one sweep covers ~31 minutes
#: of launches at the observed ~1,500/hour listed rate. Paging beyond this is free but empty.
MAX_OFFSET = 2000


def _get(url: str, *, attempts: int = 4) -> list[dict[str, Any]]:
    request = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
                return payload if isinstance(payload, list) else []
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(1.5 * (attempt + 1))
    return []


def sweep(sort: str, *, complete: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offset in range(0, MAX_OFFSET, 100):
        url = f"{LISTING}?limit=100&includeNsfw=true&sort={sort}&order=DESC&offset={offset}"
        if complete:
            url += "&complete=true"
        page = _get(url)
        if not page:
            break
        for coin in page:
            mint = coin.get("mint")
            if isinstance(mint, str) and mint not in seen:
                seen.add(mint)
                rows.append(coin)
        time.sleep(0.15)
    return rows


def _iso(ms: Any) -> str | None:
    if not isinstance(ms, int | float):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


def _load_sweeps(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted(directory.glob("sweep_*.json"))]


def _coverage_audit(sweeps: Sequence[dict[str, Any]], low: float, high: float) -> dict[str, Any]:
    """Chao1 over how many sweeps saw each mint, inside a window all of them cover."""

    sets = [
        {c["mint"] for c in s["coins"] if low <= c.get("created_timestamp", 0) <= high}
        for s in sweeps
    ]
    union: set[str] = set().union(*sets) if sets else set()
    counts = [sum(1 for seen in sets if mint in seen) for mint in union]
    result = frame_coverage(counts).to_json()
    result["sweeps"] = len(sets)
    result["per_sweep_n"] = [len(seen) for seen in sets]
    result["min_captures"] = min(counts, default=0)
    result["max_captures"] = max(counts, default=0)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pumpfun_frame")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("sweep", help="capture one listing snapshot")
    one.add_argument("--out", type=Path, required=True)
    one.add_argument("--sort", default="created_timestamp")
    one.add_argument("--complete", action="store_true")
    one.add_argument("--label", default="sweep")

    build = sub.add_parser("build", help="union sweeps into a frame over a common window")
    build.add_argument("--sweeps", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--stratum", default="cohort")
    build.add_argument("--audit", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "sweep":
        coins = sweep(args.sort, complete=args.complete)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {
                    "label": args.label,
                    "sort": args.sort,
                    "complete": args.complete,
                    "swept_at": datetime.now(UTC).isoformat(),
                    "n": len(coins),
                    "coins": coins,
                }
            )
        )
        print(f"{args.label}: {len(coins)} coins -> {args.out}")
        return 0

    sweeps = _load_sweeps(args.sweeps)
    if not sweeps:
        print("no sweeps found", file=sys.stderr)
        return 1
    # The window EVERY sweep covers. Outside it a mint's absence from one sweep means the
    # sweep never looked, not that the mint does not exist, and unioning would fabricate a
    # coverage claim.
    low = max(min(c["created_timestamp"] for c in s["coins"]) for s in sweeps)
    high = min(max(c["created_timestamp"] for c in s["coins"]) for s in sweeps)
    if low >= high:
        print("sweeps share no common creation window", file=sys.stderr)
        return 1

    best: dict[str, dict[str, Any]] = {}
    for snapshot in sweeps:
        for coin in snapshot["coins"]:
            created = coin.get("created_timestamp")
            if not isinstance(created, int | float) or not low <= created <= high:
                continue
            previous = best.get(coin["mint"])
            # Keep the LAST observation of each mint: `complete` and market cap only move
            # forward, so the freshest snapshot carries the outcome label.
            if previous is None or snapshot["swept_at"] >= previous["_swept_at"]:
                best[coin["mint"]] = {**coin, "_swept_at": snapshot["swept_at"]}

    frame = [
        FrameMint(
            mint=coin["mint"],
            stratum=args.stratum,
            launched_at=_iso(coin.get("created_timestamp")),
            listed_complete=bool(coin.get("complete")),
            listed_market_cap_usd=coin.get("usd_market_cap"),
            listed_last_trade_at=_iso(coin.get("last_trade_timestamp")),
        )
        for coin in sorted(best.values(), key=lambda c: c["created_timestamp"])
    ]
    write_frame(args.out, frame)
    audit = _coverage_audit(sweeps, low, high)
    audit |= {
        "window_low": _iso(low),
        "window_high": _iso(high),
        "window_minutes": (high - low) / 60000,
        "frame_n": len(frame),
        "frame_complete": sum(1 for row in frame if row.listed_complete),
    }
    print(json.dumps(audit, indent=2, sort_keys=True))
    if args.audit is not None:
        args.audit.write_text(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
