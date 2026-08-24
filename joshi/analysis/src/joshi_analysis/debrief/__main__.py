"""Write the session debrief artifacts from the durable stores, read-only.

    uv run --offline python -m joshi_analysis.debrief \\
        --session-state <cockpit-state dir> --catalog <keeper catalog dir> [--out <dir>]
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .artifact import read_inputs, render_day_debrief, session_days, write_day_debrief


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="joshi_analysis.debrief",
        description=(
            "Reconstruct one markdown session debrief per operator day (UTC) from "
            "durable records. Reads every store read-only; writes only the artifacts."
        ),
    )
    parser.add_argument(
        "--session-state",
        type=Path,
        required=True,
        help="cockpit-state dir (holds live-follow/, with the pairing catalog and "
        "follow-state.json)",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="keeper catalog dir (holds catalog.sqlite beside its blobs/ tree)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("state/s2"),
        help="artifact dir (default state/s2, the S2 runbook's findings convention)",
    )
    parser.add_argument(
        "--date", help="only this UTC day (YYYY-MM-DD); default is every day with records"
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the artifact(s) instead of writing files",
    )
    args = parser.parse_args(argv)

    for path, what in ((args.session_state, "session-state dir"), (args.catalog, "catalog dir")):
        if not Path(path).is_dir():
            print(f"no such {what}: {path}", file=sys.stderr)
            return 2

    inputs = read_inputs(args.session_state, args.catalog)
    days = session_days(inputs)
    if args.date is not None:
        if args.date not in days:
            print(
                f"no durable session record touches {args.date} "
                f"(days with records: {', '.join(days) if days else 'none'})",
                file=sys.stderr,
            )
            return 1
        days = [args.date]
    if not days:
        print(
            "no durable session records found in these stores; there is nothing to debrief"
        )
        return 0

    now_us = int(time.time() * 1_000_000)
    for day in days:
        text = render_day_debrief(inputs, day, now_us)
        if args.stdout:
            print(text, end="")
            continue
        path, action = write_day_debrief(args.out, day, text)
        print(f"{action}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
