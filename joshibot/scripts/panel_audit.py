#!/usr/bin/env python3
"""Audit a collected panel: coverage, censoring, and whether signal #1 is feasible on it.

Three checks, and they are chosen so that each one can fail independently of the others.

**Replication (costs credits).** A random subsample of collected mints is re-fetched with a
DIFFERENT page size, so every page boundary lands somewhere else, and the pump trade
signatures found are compared against what is on the tape for the same window. This is the
check that catches a paging hole — a dropped page, a cursor that skips, a short page mistaken
for the end — which is the failure mode a self-consistent tape cannot reveal. It is not
independent of Helius, and it is not claimed to be.

**Cross-source reserve reconciliation (free).** For any mint whose last trade, according to
pump.fun's own listing, happened INSIDE our observation window, our last recorded reserve
reading must equal what pump.fun reports now — exactly, in integer lamports and base units.
That is a genuinely cross-source, cross-vendor check on the amounts, not just the counts, and
a unit error or a missed trailing trade breaks it.

**Wallet activity (free).** The distribution of distinct tokens per wallet, and the
signal-#1 feasibility gate evaluated on the panel actually collected rather than on a
hoped-for one.

    scripts/panel_audit.py --tape-dir DIR --frame F.jsonl [--frame G.jsonl] \
        --ledger LEDGER.json --out AUDIT.json [--replicate 40] [--page-size 37]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shitcoims_intelligence.helius import HeliusHistoryClient
from shitcoims_intelligence.pump import QuarantinedPumpEvent, decode_pump_event
from shitcoims_intelligence.pump_layouts import PUMP_AMM_PROGRAM_ID, PUMP_PROGRAM_ID
from shitcoims_tape.panel import feasible_universe, read_frame
from shitcoims_tape.recorder import (
    CREDITS_PER_TRANSACTION_PAGE,
    CreditBudget,
    attribute_program_data,
)
from shitcoims_tape.schema import EventKind, TapeError, event_from_json
from shitcoims_tape.writer import default_tape_root

HTTP_TEMPLATE = "https://mainnet.helius-rpc.com/?api-key={api_key}"
LISTING = "https://frontend-api-v3.pump.fun/coins"
PUMP_PROGRAMS = frozenset({PUMP_PROGRAM_ID, PUMP_AMM_PROGRAM_ID})
TRADE_EVENTS = frozenset({"TradeEvent", "BuyEvent", "SellEvent"})


def scan_tape(root: Path) -> dict[str, Any]:
    """One pass: trade signatures per mint, last reserve per pool, wallet activity."""

    per_mint: dict[str, set[str]] = {}
    window: dict[str, tuple[int, int]] = {}
    last_reserve: dict[str, tuple[int, dict[str, int]]] = {}
    activity: dict[str, set[str]] = {}
    trades = malformed = lines = 0
    for path in sorted(root.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                lines += 1
                try:
                    event = event_from_json(json.loads(text))
                except (json.JSONDecodeError, TapeError, KeyError, TypeError):
                    malformed += 1
                    continue
                if event.kind is EventKind.TRADE and event.chain is not None:
                    trades += 1
                    mint = event.body.mint  # type: ignore[union-attr]
                    per_mint.setdefault(mint, set()).add(event.chain.signature)
                    activity.setdefault(event.body.wallet, set()).add(mint)  # type: ignore[union-attr]
                    block = event.chain.block_time
                    if block is not None:
                        low, high = window.get(mint, (block, block))
                        window[mint] = (min(low, block), max(high, block))
                elif event.kind is EventKind.RESERVE and event.chain is not None:
                    body = event.body
                    pool = body.pool  # type: ignore[union-attr]
                    previous = last_reserve.get(pool)
                    if previous is None or event.chain.slot >= previous[0]:
                        last_reserve[pool] = (
                            event.chain.slot,
                            {
                                "virtual_sol": body.virtual_sol,  # type: ignore[union-attr]
                                "virtual_tokens": body.virtual_tokens,  # type: ignore[union-attr]
                                "real_sol": body.real_sol,  # type: ignore[union-attr]
                                "real_tokens": body.real_tokens,  # type: ignore[union-attr]
                            },
                        )
    return {
        "lines": lines,
        "malformed": malformed,
        "trades": trades,
        "per_mint": per_mint,
        "window": window,
        "last_reserve": last_reserve,
        "activity": activity,
    }


def _listing(mint: str) -> dict[str, Any] | None:
    request = urllib.request.Request(
        f"{LISTING}/{mint}", headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.load(response)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def reserve_reconciliation(
    scanned: dict[str, Any], mints: Sequence[str], *, limit: int
) -> dict[str, Any]:
    """Compare the tape's last reserve reading against pump.fun's, on settled mints only."""

    checked = exact = mismatched = skipped = 0
    examples: list[dict[str, Any]] = []
    for mint in mints:
        if checked >= limit:
            break
        coin = _listing(mint)
        time.sleep(0.1)
        if coin is None or coin.get("complete"):
            # A graduated mint's curve reserves stop being the live state.
            skipped += 1
            continue
        last_trade = coin.get("last_trade_timestamp")
        span = scanned["window"].get(mint)
        if not isinstance(last_trade, int | float) or span is None:
            skipped += 1
            continue
        if last_trade / 1000 > span[1] + 1:
            # It kept trading after our window closed, so the two states are not comparable.
            skipped += 1
            continue
        curve = coin.get("bonding_curve")
        stored = scanned["last_reserve"].get(curve)
        if stored is None:
            skipped += 1
            continue
        checked += 1
        theirs = {
            "virtual_sol": coin.get("virtual_sol_reserves"),
            "virtual_tokens": coin.get("virtual_token_reserves"),
            "real_sol": coin.get("real_sol_reserves"),
            "real_tokens": coin.get("real_token_reserves"),
        }
        if all(stored[1][key] == theirs[key] for key in theirs):
            exact += 1
        else:
            mismatched += 1
            if len(examples) < 3:
                examples.append({"mint": mint, "tape": stored[1], "listing": theirs})
    return {
        "checked": checked,
        "exact": exact,
        "mismatched": mismatched,
        "skipped": skipped,
        "examples": examples,
    }


async def replicate(
    scanned: dict[str, Any],
    mints: Sequence[str],
    *,
    key: Path,
    budget: CreditBudget,
    page_size: int,
) -> dict[str, Any]:
    """Re-fetch with different page boundaries and diff the trade signatures."""

    found = 0
    on_tape = 0
    missing: list[str] = []
    checked: list[str] = []
    abandoned = 0
    async with httpx.AsyncClient(timeout=60) as http:
        client = HeliusHistoryClient(
            api_key_file=key, http_url_template=HTTP_TEMPLATE, http=http
        )
        for mint in mints:
            span = scanned["window"].get(mint)
            if span is None:
                continue
            cursor: str | None = None
            signatures: set[str] = set()
            complete = False
            while budget.can_afford(CREDITS_PER_TRANSACTION_PAGE):
                budget.charge(CREDITS_PER_TRANSACTION_PAGE)
                page, cursor = await client.address_history_page(
                    mint, limit=page_size, cursor=cursor, sort_order="asc"
                )
                stop = False
                for item in page:
                    block = item.get("blockTime")
                    if isinstance(block, int) and block > span[1]:
                        stop = True
                        break
                    logs = (item.get("meta") or {}).get("logMessages") or []
                    for entry in attribute_program_data(list(logs)).entries:
                        if entry.program_id not in PUMP_PROGRAMS:
                            continue
                        decoded = decode_pump_event(
                            program_id=entry.program_id, data=entry.payload
                        )
                        if isinstance(decoded, QuarantinedPumpEvent):
                            continue
                        if decoded.event_name in TRADE_EVENTS:
                            signature = (item.get("transaction") or {}).get("signatures")
                            if signature:
                                signatures.add(str(signature[0]))
                if stop or cursor is None or not page:
                    complete = True
                    break
            if not complete:
                # The replication itself ran out of budget mid-mint. Counting a half-read
                # replication would report the AUDIT's truncation as the TAPE's missing
                # trades, i.e. manufacture the exact defect it exists to detect.
                abandoned += 1
                continue
            checked.append(mint)
            tape = scanned["per_mint"].get(mint, set())
            found += len(signatures)
            hit = signatures & tape
            on_tape += len(hit)
            missing.extend(sorted(signatures - tape)[:2])
    return {
        "mints_checked": len(checked),
        "mints_abandoned_for_budget": abandoned,
        "page_size": page_size,
        "replicated_trade_signatures": found,
        "also_on_tape": on_tape,
        "coverage": (on_tape / found) if found else 0.0,
        "missing_examples": missing[:5],
        "credits": budget.spent,
    }


def activity_summary(activity: dict[str, set[str]], tokens: int) -> dict[str, Any]:
    counts = sorted((len(mints) for mints in activity.values()), reverse=True)
    total = len(counts)
    floors = {}
    for floor in (1, 2, 3, 5, 8, 10, 20):
        eligible = sum(1 for count in counts if count >= floor)
        cap = feasible_universe(tokens, floor)
        floors[str(floor)] = {
            "wallets_at_or_above": eligible,
            "max_feasible_universe": cap,
            "feasible": eligible <= cap and eligible >= 2,
        }
    return {
        "wallets": total,
        "tokens": tokens,
        "quantiles": {
            "p50": counts[total // 2] if total else 0,
            "p90": counts[total // 10] if total else 0,
            "p99": counts[total // 100] if total else 0,
            "max": counts[0] if total else 0,
        },
        "floors": floors,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(prog="panel_audit")
    parser.add_argument("--tape-dir", type=Path, default=None)
    parser.add_argument("--frame", type=Path, action="append", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replicate", type=int, default=40)
    # 97, not 100: every page boundary lands 3 transactions further along than the
    # collection run's did, which is what makes this a replication rather than a rerun, and
    # it costs 3% more calls instead of the 170% a page size of 37 would.
    parser.add_argument("--page-size", type=int, default=97)
    parser.add_argument("--reconcile", type=int, default=60)
    parser.add_argument("--max-credits", type=int, default=6000)
    parser.add_argument("--total-cap", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--helius-key", type=Path, default=Path("~/.helius-key").expanduser())
    args = parser.parse_args()

    root = args.tape_dir if args.tape_dir is not None else default_tape_root()
    scanned = scan_tape(root)
    frame = [row for path in args.frame for row in read_frame(path)]
    collected = sorted(scanned["per_mint"])
    rng = random.Random(args.seed)

    ledger = json.loads(args.ledger.read_text())
    allowance = min(args.max_credits, args.total_cap - int(ledger["spent"]))
    budget = CreditBudget(limit=max(allowance, 0))

    sample = rng.sample(collected, min(args.replicate, len(collected)))
    replication = await replicate(
        scanned, sample, key=args.helius_key, budget=budget, page_size=args.page_size
    )
    ledger["spent"] = int(ledger["spent"]) + budget.spent
    runs = ledger.get("runs")
    if isinstance(runs, list):
        runs.append({"frame": "panel_audit replication", "credits": budget.spent})
    args.ledger.write_text(json.dumps(ledger, indent=2, sort_keys=True))

    curve_mints = [row.mint for row in frame if not row.listed_complete]
    rng.shuffle(curve_mints)
    reconciliation = reserve_reconciliation(scanned, curve_mints, limit=args.reconcile)

    audit = {
        "tape": {
            "lines": scanned["lines"],
            "malformed": scanned["malformed"],
            "trades": scanned["trades"],
            "mints_with_trades": len(scanned["per_mint"]),
            "frame_size": len(frame),
        },
        "replication": replication,
        "reserve_reconciliation": reconciliation,
        "activity": activity_summary(scanned["activity"], len(scanned["per_mint"])),
        "credits_total": ledger["spent"],
    }
    args.out.write_text(json.dumps(audit, indent=2, sort_keys=True))
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
