"""CLI: ``fetch`` retains the bytes (bounded), ``panel`` derives the panel offline.

    uv run python -m joshi_analysis.lpdesk fetch --pool <pool> --wallet <wallet> \
        --retention-dir <dir> [--budget 280]
    uv run python -m joshi_analysis.lpdesk panel --retention-dir <dir> [--out panel.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="joshi_analysis.lpdesk")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch_cmd = commands.add_parser("fetch", help="bounded retained acquisition")
    fetch_cmd.add_argument("--pool", required=True)
    fetch_cmd.add_argument("--wallet", required=True)
    fetch_cmd.add_argument("--retention-dir", type=Path, required=True)
    fetch_cmd.add_argument("--budget", type=int, default=280)
    fetch_cmd.add_argument("--wallet-body-cap", type=int, default=90)
    fetch_cmd.add_argument("--pool-tape-cap", type=int, default=110)

    panel_cmd = commands.add_parser("panel", help="derive the panel from retained bytes")
    panel_cmd.add_argument("--retention-dir", type=Path, required=True)
    panel_cmd.add_argument("--out", type=Path, default=None)

    args = parser.parse_args()
    if args.command == "fetch":
        from .fetch import acquire
        from .rpc import RetainingSession

        session = RetainingSession(args.retention_dir, budget=args.budget)
        manifest = acquire(
            session,
            pool=args.pool,
            wallet=args.wallet,
            wallet_body_cap=args.wallet_body_cap,
            pool_tape_cap=args.pool_tape_cap,
        )
        print(json.dumps({k: v for k, v in manifest.items() if k != "bin_arrays"}, indent=1))
        return 0

    from .panel import build_panel

    panel = build_panel(args.retention_dir)
    rendered = json.dumps(panel, indent=1)
    out = args.out or (args.retention_dir / "panel.json")
    out.write_text(rendered)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
