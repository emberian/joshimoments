#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from shitcoims_intelligence.api import create_app
from shitcoims_intelligence.config import load_intelligence_config
from shitcoims_intelligence.service import ServiceComponents, build_service


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local shitcoims intelligence service")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("intelligence.yaml"),
        help="path to the isolated intelligence configuration",
    )
    parser.add_argument(
        "--no-collectors",
        action="store_true",
        help="serve the existing read model without starting collectors",
    )
    parser.add_argument(
        "--ingest-once",
        action="store_true",
        help="run one advisory collection cycle and exit (does not sign or trade)",
    )
    parser.add_argument(
        "--eval-once",
        action="store_true",
        help="print an honest paper eval of the local store and exit (does not trade)",
    )
    return parser


def _load_components(args: argparse.Namespace) -> ServiceComponents:
    config = load_intelligence_config(args.config)
    return build_service(
        config,
        collectors_enabled=not args.no_collectors,
    )


def main() -> None:
    args = _parser().parse_args()
    if args.ingest_once and args.no_collectors:
        raise SystemExit("--ingest-once cannot be combined with --no-collectors")
    if args.eval_once:
        import json

        from shitcoims_intelligence.eval_study import honest_sample_caveat, verdict_histogram

        components = build_service(
            load_intelligence_config(args.config), collectors_enabled=False
        )
        try:
            cards = list((components.reader.candidates() or {}).get("items") or [])  # type: ignore[union-attr]
        except Exception:
            cards = []
        histogram = verdict_histogram(cards)
        report = {
            "ok": True,
            "execution_effect": "none",
            "candidates": len(cards),
            "verdicts": histogram,
            "caveat": (
                f"{len(cards)} candidate cards; "
                f"{histogram.get('skip', 0)} skip (no early_coin tape yet). "
                "Event-study n=0 until Pump trades feed the lab. "
                + honest_sample_caveat(0)
            ),
            "note": (
                "MarketFabric was not imported. lead/lag and event_study live in "
                "eval_study.py as a reimplementation. All-skip is a data gap, not a signal."
            ),
        }
        print(json.dumps(report, sort_keys=True))
        close = getattr(components.reader, "close", None)
        if close is not None:
            close()
        return
    components = _load_components(args)
    if args.ingest_once:
        import asyncio
        import json

        async def _once() -> None:
            await components.runtime.start()
            try:
                summary = await components.runtime.run_once()  # type: ignore[attr-defined]
            finally:
                await components.runtime.stop()
            print(json.dumps({"ok": True, "execution_effect": "none", **dict(summary)}, sort_keys=True))

        asyncio.run(_once())
        return
    app = create_app(
        components.reader,
        runtime=components.runtime,
        allowed_origins=components.config.server.allowed_origins,
    )
    uvicorn.run(
        app,
        host=components.config.server.host,
        port=components.config.server.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
