"""Backfill the callout stream over a window where forward returns already exist.

The problem this solves. The callout channel has never been tested because the
two tapes never overlapped: `state/boards/` holds ten hours of 30-second price
snapshots, while `intelligence.sqlite3` held 46 mint-resolved X callouts spread
over three days, of which a handful fall inside the board window. Nothing can be
measured from that.

The pinned Apify actor honours X's `since_time:` / `until_time:` search
operators (verified 2026-08-14: a query bounded to the board window returned
only tweets inside it, newest first). So the callout stream is *retrospectively
collectable* over exactly the window where prices exist. That is what this does.

Discipline:
- One clock per field. `t_post` is the tweet's own `created_at`; `t_collect` is
  ours. They are never mixed, and the study keys on `t_post`.
- Slices are walked oldest-first and each records the window it asked for, so a
  slice that hits the actor's result cap is *visible* as truncation rather than
  silently thinning the sample in a way that correlates with tweet volume.
- Raw parsed fields are written verbatim to JSONL. No filtering happens here;
  cohort construction belongs to the study, not the collector.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from shitcoims_intelligence.adapters.x_apify import XApifyAdapter, XApifyConfig

OUT_DIR = Path(__file__).resolve().parent.parent / "state" / "callouts"

#: Measured distinct-mints-per-purchased-tweet, 2026-08-14 (see RESULT).
DISCOVERY_QUERIES: tuple[str, ...] = (
    "url:dexscreener.com/solana",  # 0.95
    "url:axiom.trade",             # 0.70
    '"CA" pump',                   # 0.65
    "url:pump.fun",                # 0.45
)


def _row(tweet: Any, *, query: str, slice_start: int, slice_end: int, t_collect: str) -> dict:
    d = asdict(tweet)
    d.pop("provenance", None)
    created = d.pop("created_at", None)
    return {
        "t_post": created.isoformat() if created is not None else None,
        "t_collect": t_collect,
        "query": query,
        "slice_start_unix": slice_start,
        "slice_end_unix": slice_end,
        **d,
        "mints": list(tweet.all_mints),
    }


async def backfill(
    *,
    start_unix: int,
    end_unix: int,
    slice_seconds: int,
    queries: tuple[str, ...],
    max_items: int,
    out: Path,
) -> dict[str, int]:
    cfg = XApifyConfig(
        enabled=True, token_file=Path("~/.apify-token"), max_items_per_query=max_items
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    stats = {"queries": 0, "tweets": 0, "with_mint": 0, "capped_slices": 0, "failed": 0}
    seen_ids: set[str] = set()
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as http:
        adapter = XApifyAdapter(cfg, http)
        with out.open("a") as fh:
            lo = start_unix
            while lo < end_unix:
                hi = min(lo + slice_seconds, end_unix)
                for base in queries:
                    q = f"{base} since_time:{lo} until_time:{hi}"
                    stats["queries"] += 1
                    try:
                        batch = await adapter.search(q, max_items=max_items)
                    except Exception as exc:  # a dead slice must not kill the run
                        stats["failed"] += 1
                        print(f"  ! {q}: {type(exc).__name__}", flush=True)
                        continue
                    t_collect = datetime.now(UTC).isoformat()
                    n = len(batch.results)
                    if n >= max_items:
                        # The actor returned as much as it was willing to; the
                        # slice is truncated and its sample is biased toward the
                        # newest tweets in it. Recorded, never silently dropped.
                        stats["capped_slices"] += 1
                    fresh = 0
                    for tweet in batch.results:
                        key = f"{tweet.tweet_id}"
                        if key in seen_ids:
                            continue
                        seen_ids.add(key)
                        fresh += 1
                        stats["tweets"] += 1
                        if tweet.all_mints:
                            stats["with_mint"] += 1
                        fh.write(
                            json.dumps(
                                _row(
                                    tweet,
                                    query=base,
                                    slice_start=lo,
                                    slice_end=hi,
                                    t_collect=t_collect,
                                ),
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                    fh.flush()
                    print(
                        f"  {datetime.fromtimestamp(lo, UTC):%m-%d %H:%M} {base[:28]:<28} "
                        f"got={n:<3} new={fresh:<3} capped={n >= max_items}",
                        flush=True,
                    )
                lo = hi
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-unix", type=int, required=True)
    ap.add_argument("--end-unix", type=int, required=True)
    ap.add_argument("--slice-seconds", type=int, default=1800)
    ap.add_argument("--max-items", type=int, default=50)
    ap.add_argument("--queries", default=",".join(DISCOVERY_QUERIES))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = (
        Path(args.out)
        if args.out
        else OUT_DIR / f"backfill-{args.start_unix}-{args.end_unix}.jsonl"
    )
    queries = tuple(q for q in (s.strip() for s in args.queries.split(",")) if q)
    stats = asyncio.run(
        backfill(
            start_unix=args.start_unix,
            end_unix=args.end_unix,
            slice_seconds=args.slice_seconds,
            queries=queries,
            max_items=args.max_items,
            out=out,
        )
    )
    print(json.dumps({**stats, "out": str(out)}, indent=1))


if __name__ == "__main__":
    main()
