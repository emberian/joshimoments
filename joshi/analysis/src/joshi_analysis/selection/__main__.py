"""Run the selection measurement over one or more catalogs, read-only.

    uv run --offline python -m joshi_analysis.selection <catalog.sqlite> [...]
    uv run --offline python -m joshi_analysis.selection --power-only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .power import power_statement, render_power_statement
from .preregistration import DEFAULT_FEE_FLOOR_BPS
from .report import build_report, render_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="joshi_analysis.selection",
        description="Measure operator selection against the choice set she passed over.",
    )
    parser.add_argument("catalog", nargs="*", type=Path, help="catalog.sqlite paths, read-only")
    parser.add_argument(
        "--fee-floor-bps",
        type=int,
        default=DEFAULT_FEE_FLOOR_BPS,
        help=f"round-trip fee floor in bps (default {DEFAULT_FEE_FLOOR_BPS}, the measured "
        "bonding-curve figure)",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument(
        "--power-only",
        action="store_true",
        help="print only the power requirement; reads no catalog",
    )
    parser.add_argument(
        "--choice-set-size", type=int, default=8, help="assumed k for --power-only (default 8)"
    )
    args = parser.parse_args(argv)

    if args.power_only:
        print(render_power_statement(power_statement(n_scored_now=0, k=args.choice_set_size)))
        return 0

    if not args.catalog:
        parser.error("give at least one catalog.sqlite, or --power-only")

    missing = [p for p in args.catalog if not Path(p).is_file()]
    if missing:
        for path in missing:
            print(f"no such catalog: {path}", file=sys.stderr)
        return 2

    report = build_report(args.catalog, fee_floor_bps=args.fee_floor_bps)
    if args.json:
        print(json.dumps(report.to_json_obj(), indent=2, sort_keys=True))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
