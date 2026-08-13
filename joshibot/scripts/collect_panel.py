#!/usr/bin/env python3
"""Run mint-indexed panel collection against Helius, under a persistent credit ceiling.

Read-only. This script fetches transaction history and writes tape; it never signs, submits,
or reads a wallet key, and it never calls the Enhanced Transactions API (100 credits/call
against 10 credits per 100 transactions for the RPC path this uses).

**The ledger is on disk, not in the process.** A budget that lives only inside one run cannot
stop the *next* run from blowing the same ceiling, and a panel is collected in several passes
by construction — a pilot, a stratum, another stratum. ``--ledger`` accumulates spend across
every pass and the script refuses to start a pass that could exceed ``--total-cap``. Charges
are recorded before the request, so an interrupted run over-reports rather than under-reports.

    scripts/collect_panel.py --frame FRAME.jsonl --tape-dir DIR --ledger LEDGER.json \
        --max-credits 20000 --total-cap 100000 --page-cap 25 --window-seconds 3600
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shitcoims_intelligence.helius import HeliusHistoryClient
from shitcoims_tape.panel import (
    MintOutcome,
    collect_panel,
    read_frame,
)
from shitcoims_tape.recorder import CreditBudget
from shitcoims_tape.writer import TapeWriter, default_tape_root

LOGGER = logging.getLogger("shitcoims.tape.collect")

HTTP_TEMPLATE = "https://mainnet.helius-rpc.com/?api-key={api_key}"


def _ledger_read(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"spent": 0, "runs": []}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("spent"), int):
        raise SystemExit(f"credit ledger at {path} is malformed; refusing to spend")
    return payload


def _ledger_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


async def run(args: argparse.Namespace) -> int:
    frame = read_frame(args.frame)
    if not frame:
        raise SystemExit("frame is empty")

    ledger = _ledger_read(args.ledger)
    already = int(ledger["spent"])  # type: ignore[arg-type]
    allowance = min(args.max_credits, args.total_cap - already)
    if allowance <= 0:
        raise SystemExit(
            f"credit ceiling reached: {already} of {args.total_cap} already spent"
        )
    LOGGER.info(
        "frame=%s mints, ledger=%s spent, this pass may spend %s",
        len(frame),
        already,
        allowance,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "frame": len(frame),
                    "already_spent": already,
                    "allowance": allowance,
                    "worst_case": len(frame) * args.page_cap * 10,
                },
                indent=2,
            )
        )
        return 0

    budget = CreditBudget(limit=allowance)
    root = args.tape_dir if args.tape_dir is not None else default_tape_root()
    writer = TapeWriter(root, prefix=args.prefix)
    done = 0

    def progress(outcome: MintOutcome) -> None:
        nonlocal done
        done += 1
        if done % 25 == 0 or done == len(frame):
            LOGGER.info(
                "%s/%s mints, %s credits, last=%s trades=%s stop=%s",
                done,
                len(frame),
                budget.spent,
                outcome.mint[:8],
                outcome.trades,
                "n/a" if outcome.history is None else outcome.history.stopped_by,
            )

    try:
        async with httpx.AsyncClient(timeout=60) as http:
            client = HeliusHistoryClient(
                api_key_file=args.helius_key, http_url_template=HTTP_TEMPLATE, http=http
            )
            report = await collect_panel(
                client,
                writer.write,
                frame,
                budget=budget,
                window_seconds=args.window_seconds,
                page_cap=args.page_cap,
                source=args.source,
                on_mint=progress,
            )
    finally:
        writer.close()
        # Charge the ledger no matter how the pass ended. A crash that forgets what it spent
        # is how a hard ceiling becomes a suggestion.
        ledger["spent"] = already + budget.spent
        runs = ledger.get("runs")
        if isinstance(runs, list):
            runs.append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "frame": str(args.frame),
                    "credits": budget.spent,
                    "mints": len(frame),
                }
            )
        _ledger_write(args.ledger, ledger)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.to_json(), indent=2, sort_keys=True))
    summary = {
        key: value for key, value in report.to_json().items() if key != "outcomes"
    }
    summary["ledger_total"] = ledger["spent"]
    summary["writer"] = writer.stats.to_json()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="collect_panel")
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--tape-dir", type=Path, default=None)
    parser.add_argument("--prefix", default="panel")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--helius-key", type=Path, default=Path("~/.helius-key").expanduser())
    parser.add_argument("--max-credits", type=int, default=20_000, help="ceiling for THIS pass")
    parser.add_argument(
        "--total-cap", type=int, default=100_000, help="ceiling across every pass in the ledger"
    )
    parser.add_argument("--page-cap", type=int, default=25)
    parser.add_argument("--window-seconds", type=int, default=3600)
    parser.add_argument("--source", default="helius.getTransactionsForAddress")
    parser.add_argument("--dry-run", action="store_true")
    return parser


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
