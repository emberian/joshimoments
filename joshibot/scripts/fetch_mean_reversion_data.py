#!/usr/bin/env python3
"""Materialise the price cache that ``studies/mean_reversion.py`` reads.

This is the ONLY networked half of the mean-reversion study. The study itself is
deterministic given a seed and never opens a socket; everything it needs lands here first,
in JSONL, with provenance on every row.

**Two sources, deliberately.**

*GeckoTerminal OHLCV* supplies the span. The binding constraint on this question is not
resolution but **pool age** — weave/SOL is 10 days old, nosis/SOL is 5 — and no amount of
money buys history that does not exist. Candles are requested with ``currency=token`` so a
memecoin/SOL pool returns the memecoin priced *in SOL*, which is the quantity the LP thesis
is about, rather than a USD figure that has already had a SOL/USD conversion folded into it.

*The on-disk cluster tape* supplies the control. GeckoTerminal closes are **trade** prices,
and trade prices bounce between the two sides of the fee, which manufactures exactly the
negative autocorrelation this study is looking for (Lo & MacKinlay's nonsynchronous-trading
result is the same hazard from the other direction). ``state/cluster_tape/`` records exact
post-swap vault balances as integers, so the pool's *marginal* price is recoverable with no
bounce at all. The overlap is short — a day and a half — but it is enough to size the
contamination instead of waving at it.

**Helius credits spent by this script: zero.** Chain reconstruction would buy a cleaner
price at the same span, and span is what is missing. The credit budget cannot fix the thing
that is broken, so it is not spent. See ``studies/RESULT_mean_reversion.md``.

Raw token amounts stay integers all the way into the cache (§3: no floats for raw amounts).
GeckoTerminal prices are already decimal ratios rather than raw amounts; they are stored as
the exact text the API returned so that the cache is a faithful record of the source.

Usage::

    uv run python scripts/fetch_mean_reversion_data.py
    uv run python scripts/fetch_mean_reversion_data.py --out studies/data/mean_reversion
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_OUT: Final[Path] = REPO / "studies" / "data" / "mean_reversion"

GT_HOST: Final[str] = "https://api.geckoterminal.com/api/v2"
USER_AGENT: Final[str] = "joshibot-research/1.0 (read-only mean-reversion study)"
#: GeckoTerminal's free tier is ~30 calls/minute. 3s between calls keeps a wide margin, and
#: a 429 still gets an exponential backoff because the limit is shared across the host.
SLEEP_S: Final[float] = 3.0
MAX_PAGES: Final[int] = 200

WSOL: Final[str] = "So11111111111111111111111111111111111111112"

#: The four cluster pools, addresses resolved on chain by ``shitcoims_cluster/pools.py``
#: (it reads each pool's vault mints rather than trusting a symbol — there are two distinct
#: tokens using the symbol "nosis" and only the mint disambiguates them).
POOLS: Final[tuple[dict[str, str], ...]] = (
    {
        "pool": "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
        "label": "weave/SOL",
        "series": "weave_per_sol",
        "mint": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
        "currency": "token",
    },
    {
        "pool": "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc",
        "label": "nosis/SOL",
        "series": "nosis_per_sol",
        "mint": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
        "currency": "token",
    },
    {
        "pool": "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU",
        "label": "DREGG/SOL",
        "series": "dregg_per_sol",
        "mint": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
        "currency": "token",
    },
    {
        "pool": "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr",
        "label": "SOLVE/SOL",
        "series": "solve_per_sol",
        "mint": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
        "currency": "token",
    },
    # The SOL/USD reference leg. Orca SOL/USDC: $26M of liquidity, $51M/day, live since 2023,
    # so it is the one series in this study whose span is not the constraint. A memecoin's
    # USD return is then r_meme_sol + r_sol_usd by identity, which is what the break-even
    # comparison needs. Capped at 70 days of lookback: the oldest cluster pool is 48 days old,
    # so paging three years of a dense minute series would be ~1300 requests bought to be
    # intersected away.
    {
        "pool": "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE",
        "label": "SOL/USDC",
        "series": "sol_per_usd",
        "mint": WSOL,
        "currency": "usd",
        "lookback_days": "70",
    },
)

#: ``minute`` at aggregate 1 is the finest the venue publishes and is what the bounce control
#: needs; ``hour`` is the only grid that is genuinely dense over the full 47-day span of the
#: oldest pool. Both are fetched to their limit and the study picks per horizon.
TIMEFRAMES: Final[tuple[tuple[str, int], ...]] = (("minute", 1), ("minute", 5), ("hour", 1))


class FetchError(RuntimeError):
    pass


def _get(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise FetchError(f"expected a JSON object, got {type(payload).__name__}")
            return payload
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise FetchError(f"HTTP {exc.code} from GeckoTerminal") from None
            time.sleep(6.0 * (attempt + 1))
        except OSError as exc:  # transport: never re-raise, the URL is not a secret but be uniform
            last = exc
            time.sleep(6.0 * (attempt + 1))
    raise FetchError(f"gave up after 6 attempts: {type(last).__name__}")


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _now_ts() -> float:
    return datetime.now(tz=UTC).timestamp()


def pool_metadata(pool: str) -> dict[str, Any]:
    payload = _get(f"{GT_HOST}/networks/solana/pools/{pool}")
    attributes = payload["data"]["attributes"]
    relationships = payload["data"]["relationships"]
    return {
        "name": attributes["name"],
        "created_at": attributes["pool_created_at"],
        "reserve_usd": attributes["reserve_in_usd"],
        "volume_usd_24h": attributes["volume_usd"]["h24"],
        "tx_24h": attributes["transactions"]["h24"],
        "base_mint": relationships["base_token"]["data"]["id"].removeprefix("solana_"),
        "quote_mint": relationships["quote_token"]["data"]["id"].removeprefix("solana_"),
        "dex": relationships["dex"]["data"]["id"],
    }


def ohlcv_pages(
    pool: str, timeframe: str, aggregate: int, currency: str, *, floor_ts: int
) -> Iterator[list[list[Any]]]:
    """Page backwards through OHLCV until the venue runs out or ``floor_ts`` is passed."""

    before: int | None = None
    seen_oldest: int | None = None
    for _ in range(MAX_PAGES):
        url = (
            f"{GT_HOST}/networks/solana/pools/{pool}/ohlcv/{timeframe}"
            f"?aggregate={aggregate}&limit=1000&currency={currency}&token=base"
        )
        if before is not None:
            url += f"&before_timestamp={before}"
        rows = _get(url)["data"]["attributes"]["ohlcv_list"]
        if not rows:
            return
        yield rows
        oldest = min(int(row[0]) for row in rows)
        if seen_oldest is not None and oldest >= seen_oldest:
            return  # the venue stopped moving; do not spin
        seen_oldest = oldest
        if oldest <= floor_ts:
            return
        before = oldest
        time.sleep(SLEEP_S)


def fetch_gecko(
    out_path: Path,
    only: str | None = None,
    mode: str = "w",
    timeframes: tuple[tuple[str, int], ...] = TIMEFRAMES,
) -> dict[str, Any]:
    fetched_at = _now_iso()
    manifest: dict[str, Any] = {"source": "geckoterminal", "fetched_at": fetched_at, "series": {}}
    written = 0
    with out_path.open(mode, encoding="utf-8") as handle:
        for spec in POOLS:
            if only is not None and spec["series"] != only:
                continue
            meta = pool_metadata(spec["pool"])
            created = int(datetime.fromisoformat(meta["created_at"].replace("Z", "+00:00")).timestamp())
            lookback = spec.get("lookback_days")
            if lookback is not None:
                created = max(created, int(_now_ts() - float(lookback) * 86400))
            print(f"  {spec['label']:12s} created {meta['created_at']}  dex={meta['dex']}", file=sys.stderr)
            manifest["series"][spec["series"]] = {
                "pool": spec["pool"],
                "label": spec["label"],
                "mint": spec["mint"],
                "currency": spec["currency"],
                "pool_metadata": meta,
                "grids": {},
            }
            # A pool whose base token is not the one we asked for would silently invert every
            # price in this study. Chain is the authority; the table is only an expectation.
            if meta["base_mint"] != spec["mint"]:
                raise FetchError(
                    f"{spec['label']}: pool base mint is {meta['base_mint']}, expected {spec['mint']}"
                )
            time.sleep(SLEEP_S)
            for timeframe, aggregate in timeframes:
                rows_out = 0
                timestamps: list[int] = []
                for page in ohlcv_pages(
                    spec["pool"], timeframe, aggregate, spec["currency"], floor_ts=created
                ):
                    for row in page:
                        ts = int(row[0])
                        timestamps.append(ts)
                        handle.write(
                            json.dumps(
                                {
                                    "kind": "ohlcv",
                                    "series": spec["series"],
                                    "pool": spec["pool"],
                                    "label": spec["label"],
                                    "timeframe": timeframe,
                                    "aggregate": aggregate,
                                    "t_event": ts,
                                    "open": repr(float(row[1])),
                                    "high": repr(float(row[2])),
                                    "low": repr(float(row[3])),
                                    "close": repr(float(row[4])),
                                    "volume_usd": repr(float(row[5])),
                                    "provenance": {
                                        "source": "geckoterminal.ohlcv",
                                        "currency": spec["currency"],
                                        "token": "base",
                                        "fetched_at": fetched_at,
                                    },
                                },
                                sort_keys=True,
                            )
                            + "\n"
                        )
                        rows_out += 1
                    written += len(page)
                grid = f"{timeframe}{aggregate}"
                manifest["series"][spec["series"]]["grids"][grid] = {
                    "candles": rows_out,
                    "oldest": min(timestamps) if timestamps else None,
                    "newest": max(timestamps) if timestamps else None,
                }
                print(f"    {grid:8s} {rows_out:6d} candles", file=sys.stderr)
                time.sleep(SLEEP_S)
    manifest["rows"] = written
    return manifest


def fetch_chain_mid(out_path: Path, tape_dir: Path) -> dict[str, Any]:
    """Snapshot the bounce-free marginal price from the on-disk cluster tape.

    A constant-product pool's marginal price is a state variable, not a trade price: it is
    exactly ``sol_reserve / token_reserve`` in UI units, and both reserves are recorded as
    integers. That series has no bid-ask bounce by construction, which is the whole point of
    keeping it next to the GeckoTerminal closes.
    """

    manifest: dict[str, Any] = {"source": "cluster_tape", "fetched_at": _now_iso(), "series": {}}
    by_pool = {spec["pool"]: spec for spec in POOLS}
    counts: dict[str, int] = {}
    if not tape_dir.exists():
        manifest["series"] = {}
        manifest["note"] = f"{tape_dir} does not exist; chain control unavailable"
        out_path.write_text("", encoding="utf-8")
        return manifest
    with out_path.open("w", encoding="utf-8") as handle:
        for path in sorted(tape_dir.glob("*.jsonl")):
            pool = path.name.split("-")[0]
            spec = by_pool.get(pool)
            if spec is None:
                continue
            with path.open(encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    if row.get("kind") != "swap":
                        continue
                    reserves = row.get("reserves") or {}
                    vaults = {v["mint"]: v for v in reserves.get("vaults", ())}
                    quote = vaults.get(WSOL)
                    base = vaults.get(spec["mint"])
                    if quote is None or base is None:
                        continue
                    quote_raw = int(quote["post_raw"])
                    base_raw = int(base["post_raw"])
                    if quote_raw <= 0 or base_raw <= 0:
                        continue
                    handle.write(
                        json.dumps(
                            {
                                "kind": "chain_mid",
                                "series": spec["series"],
                                "pool": pool,
                                "label": spec["label"],
                                # Raw integers, never floats: the price is a ratio the study
                                # forms itself, so nothing is rounded on the way in.
                                "quote_raw": str(quote_raw),
                                "quote_decimals": int(quote["decimals"]),
                                "base_raw": str(base_raw),
                                "base_decimals": int(base["decimals"]),
                                "t_event": row["t_event"],
                                "slot": row["chain"]["slot"],
                                "signature": row["chain"]["signature"],
                                "provenance": {
                                    "source": "shitcoims_cluster.record",
                                    "file": path.name,
                                },
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    counts[spec["series"]] = counts.get(spec["series"], 0) + 1
    manifest["series"] = counts
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tape", type=Path, default=REPO / "state" / "cluster_tape" / "swaps")
    parser.add_argument("--skip-gecko", action="store_true")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="refresh every pool's metadata into the manifest without touching the candles",
    )
    parser.add_argument("--only", default=None, help="fetch a single series (appends)")
    parser.add_argument(
        "--timeframes",
        default=None,
        help="comma-separated subset, e.g. hour1,minute5 (default: all three grids)",
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    # Merge rather than overwrite. A `--only` run used to blank the other four pools out of
    # the manifest, which is a silent loss of provenance for series still sitting in the
    # cache — the cache would still have been right and the record of where it came from
    # would not.
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["written_at"] = _now_iso()
    manifest.setdefault("helius_credits_spent", 0)

    if args.metadata_only:
        pools = manifest.setdefault("pools", {})
        for spec in POOLS:
            meta = pool_metadata(spec["pool"])
            if meta["base_mint"] != spec["mint"]:
                raise FetchError(
                    f"{spec['label']}: pool base mint is {meta['base_mint']}, expected {spec['mint']}"
                )
            pools[spec["series"]] = {
                "pool": spec["pool"],
                "label": spec["label"],
                "mint": spec["mint"],
                "fetched_at": _now_iso(),
                **meta,
            }
            print(f"  {spec['label']:12s} {meta['created_at']}  liq=${meta['reserve_usd']}", file=sys.stderr)
            time.sleep(SLEEP_S)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if not args.skip_gecko:
        print("geckoterminal OHLCV", file=sys.stderr)
        timeframes = TIMEFRAMES
        if args.timeframes:
            wanted = {t.strip() for t in args.timeframes.split(",")}
            timeframes = tuple(t for t in TIMEFRAMES if f"{t[0]}{t[1]}" in wanted)
            if not timeframes:
                parser.error(f"no known timeframe in {args.timeframes!r}")
        gecko = fetch_gecko(
            args.out / "gt_ohlcv.jsonl",
            only=args.only,
            mode="a" if args.only else "w",
            timeframes=timeframes,
        )
        previous = manifest.get("gecko", {}).get("series", {})
        gecko["series"] = {**previous, **gecko["series"]} if args.only else gecko["series"]
        manifest["gecko"] = gecko

    print("cluster tape (local, no network)", file=sys.stderr)
    manifest["chain"] = fetch_chain_mid(args.out / "chain_mid.jsonl", args.tape)

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["chain"], indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
