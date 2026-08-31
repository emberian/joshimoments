"""The recorder process: ``python -m shitcoims_tape``.

Two modes, and the split is deliberate.

``--from-jsonl`` replays captured transactions. It costs nothing, touches no network and no
credential, and it is the mode every test and every re-import uses.

``--live`` opens the program-level pump subscription. It is **off by default** and requires
naming the key file explicitly, because a recorder that connects when you forget a flag is a
recorder that spends credits and reads a secret you did not intend it to read. Nothing in
either mode signs, submits, or reads a wallet key.

The output directory defaults to a local ``./tape`` (or ``$JOSHIBOT_TAPE_DIR``); production on
hbox sets that variable to a path under ``/tank``. It is never hard-coded here.

On exit the process closes every still-open watch. The default reason is ``OPERATOR`` for a
clean stop, which is honest and benign; a crash leaves them unresolved, which is exactly what
``shitcoims_tape.health`` reports as ``unresolved_past_deadline`` rather than letting the
truncation pass unnoticed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from pathlib import Path

from shitcoims_tape.recorder import CreditBudget, TapeRecorder
from shitcoims_tape.schema import WatchClose
from shitcoims_tape.sources import (
    PumpFirehose,
    RunReport,
    SourceItem,
    TransactionSource,
    run_recorder,
    transactions_from_jsonl,
)
from shitcoims_tape.watch import AdmissionPolicy, WatchRegistry
from shitcoims_tape.writer import TapeWriter, default_tape_root

LOGGER = logging.getLogger("shitcoims.tape.cli")

DEFAULT_WS_TEMPLATE = "wss://mainnet.helius-rpc.com/?api-key={api_key}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m shitcoims_tape",
        description="Record pump.fun market history to the Phase 0 tape contract.",
    )
    parser.add_argument(
        "--tape-dir",
        type=Path,
        default=None,
        help="output directory (default: $JOSHIBOT_TAPE_DIR or ./tape)",
    )
    parser.add_argument("--prefix", default="tape", help="segment name prefix")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--from-jsonl", type=Path, help="replay captured raw transactions; no network, no cost"
    )
    source.add_argument(
        "--live",
        action="store_true",
        help="subscribe to the pump programs (requires --helius-key)",
    )
    parser.add_argument(
        "--helius-key",
        type=Path,
        default=None,
        help="path to a 0600 file holding the Helius API key; only read under --live",
    )
    parser.add_argument("--ws-template", default=DEFAULT_WS_TEMPLATE)
    parser.add_argument(
        "--horizon-hours",
        type=float,
        default=24.0,
        help="watch deadline in hours (default 24; under 1 needs --allow-short-horizon)",
    )
    parser.add_argument(
        "--allow-short-horizon",
        action="store_true",
        help="state deliberately that this run cannot observe the graduation tail",
    )
    parser.add_argument(
        "--capacity", type=int, default=20_000, help="max concurrent watches; 0 is unbounded"
    )
    parser.add_argument(
        "--admission",
        choices=[str(policy) for policy in AdmissionPolicy],
        default=str(AdmissionPolicy.REFUSE),
        help="what happens at capacity; 'displace' reproduces the published collector's bug",
    )
    parser.add_argument(
        "--watch-mint",
        action="append",
        default=[],
        metavar="MINT",
        help="open a watch on this mint at start-up; repeatable",
    )
    parser.add_argument(
        "--max-credits",
        type=int,
        default=100_000,
        help="hard Helius ceiling for this run (1%% of a 10M monthly plan)",
    )
    return parser


def _build_source(args: argparse.Namespace) -> TransactionSource:
    if args.from_jsonl is not None:
        return transactions_from_jsonl(args.from_jsonl)
    if args.helius_key is None:
        raise SystemExit("--live requires --helius-key: the recorder never guesses a key path")
    firehose = PumpFirehose(
        api_key_file=args.helius_key, websocket_url_template=args.ws_template
    )
    return _FirehoseSource(firehose)


class _FirehoseSource:
    """Adapt the firehose's stop-aware iterator to the plain source protocol."""

    def __init__(self, firehose: PumpFirehose) -> None:
        self._firehose = firehose
        self.stop = asyncio.Event()

    def transactions(self) -> AsyncIterator[SourceItem]:
        return self._firehose.transactions(stop=self.stop)


def run(args: argparse.Namespace) -> RunReport:
    root = args.tape_dir if args.tape_dir is not None else default_tape_root()
    budget = CreditBudget(limit=args.max_credits)
    writer = TapeWriter(root, prefix=args.prefix)
    try:
        registry = WatchRegistry(
            writer.write,
            horizon=timedelta(hours=args.horizon_hours),
            capacity=args.capacity,
            admission=AdmissionPolicy(args.admission),
            allow_short_horizon=args.allow_short_horizon,
        )
        recorder = TapeRecorder(writer.write, registry)
        if args.watch_mint:
            recorder.watch(list(args.watch_mint))
        source = _build_source(args)
        try:
            report = asyncio.run(run_recorder(source, recorder, budget=budget))
        finally:
            # A clean stop is OPERATOR, not a deadline and not a loss. Every watch that is
            # still open leaves a record either way; none of them just disappear.
            registry.shutdown(reason=WatchClose.OPERATOR)
    finally:
        writer.close()
    LOGGER.info(
        "recorded %s events from %s transactions (%s credits)",
        report.events_written,
        report.transactions,
        report.credits_spent,
    )
    # Read the writer's stats AFTER the close, so the reported fsync count is the real one
    # rather than the count as of the last rotation.
    payload = {
        "run": report.to_json(),
        "writer": writer.stats.to_json(),
        "recorder": recorder.counters.to_json(),
        "watches": registry.stats.to_json(),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    report = run(args)
    # A run that produced only gaps is a failed run, and the exit code should say so.
    return 0 if report.transactions or not report.gaps else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
