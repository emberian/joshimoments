"""CLI. `run` is the systemd target; `once` is one cycle for smoke tests; the rest read.

    python -m dregg_archive run --config dregg_archive/config.toml
    python -m dregg_archive once --config <toml>      # single cycle, then exit
    python -m dregg_archive verdicts --config <toml> [--removed]
    python -m dregg_archive stats --config <toml>
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .service import Config, Service
from .store import Store, iso, utc_day


def _config_path(args: argparse.Namespace) -> Path:
    return Path(args.config)


def cmd_run(args: argparse.Namespace) -> int:
    Service(_config_path(args)).run()
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    service = Service(_config_path(args))
    heartbeat = service.cycle()
    print(json.dumps(heartbeat, indent=1))
    return 0


def cmd_verdicts(args: argparse.Namespace) -> int:
    cfg = Config.load(_config_path(args))
    store = Store(cfg.db_path)
    rows = store.verdicts(verdict="removed" if args.removed else None)
    for row in rows:
        t_event = iso(row["t_event_ms"]) if row["t_event_ms"] else "no-createdAt"
        print(
            f"{row['verdict']:<15} {row['callout_id']}  mint={row['mint'][:8]}.. "
            f"wallet={row['wallet'][:8]}..  t_event={t_event}  "
            f"evidence={row['evidence_fetch_ids']}  published={row['published']}"
        )
    if not rows:
        print("no verdicts")
    print(f"\n{len(rows)} verdicts. `unknown-absent` is NEVER published; it is a maybe, kept honest.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    cfg = Config.load(_config_path(args))
    store = Store(cfg.db_path)
    counts = store.counts()
    now_ms = int(time.time() * 1000)
    day = utc_day(now_ms)
    spent, stopped = store.budget(day)
    hwm = store.hwm_ms()
    print(json.dumps({
        "counts": counts,
        "hwm": iso(hwm) if hwm else None,
        "budget": {"day": day, "spent": spent, "ceiling": cfg.daily_budget, "stopped": stopped},
        "db": str(cfg.db_path),
    }, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dregg_archive", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, fn, help_text in (
        ("run", cmd_run, "the service loop (systemd target)"),
        ("once", cmd_once, "a single cycle, then exit — for smoke tests"),
        ("stats", cmd_stats, "counts, budget, high-water mark"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", required=True)
        p.set_defaults(fn=fn)

    p = sub.add_parser("verdicts", help="list removal verdicts")
    p.add_argument("--config", required=True)
    p.add_argument("--removed", action="store_true", help="only verdict=removed")
    p.set_defaults(fn=cmd_verdicts)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
