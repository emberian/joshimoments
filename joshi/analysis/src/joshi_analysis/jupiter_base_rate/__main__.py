"""CLI for the registered study: ``fetch`` the reference series, then ``run`` the estimands.

    cd analysis
    uv run --offline python -m joshi_analysis.jupiter_base_rate fetch --days 30
    uv run --offline python -m joshi_analysis.jupiter_base_rate run

The registration (REGISTRATION.md, v1) was written before the first fetch. ``run`` computes
only the registered estimands and writes one JSON result + a human-readable report under
``state/prediction/study/``. Every base-rate block carries the reference-approximation label
and the fee floor.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from . import reference, rounds, study

STATE = Path("~/dev/joshi/state/prediction")


def cmd_fetch(args: argparse.Namespace) -> None:
    end_s = (int(time.time()) // 300) * 300 - 300  # last completed 5m boundary
    start_s = end_s - int(args.days * 86400)
    receipt = reference.fetch_reference(start_s, end_s, args.out, max_requests=args.max_requests)
    print(receipt.read_text())


def cmd_run(args: argparse.Namespace) -> None:
    candles = reference.load_coinbase(args.reference)
    kraken = reference.load_kraken_closes(args.reference)
    all_rounds, collect_totals = rounds.read_rounds(args.collect)
    result = {
        "contract": "joshi.jupiter_base_rate.result.v1",
        "registration": "joshi.jupiter_base_rate.registration.v1",
        "computedWall": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference": {
            "label": reference.REFERENCE_LABEL,
            "settlementExactRequires": reference.SETTLEMENT_EXACT_REQUIRES,
            "minutes": len(candles),
            "spanUnixS": [min(candles), max(candles)] if candles else None,
            "venueDispersionVsKraken": reference.venue_dispersion(candles, kraken),
        },
        "horizons": {
            "5m": study.horizon_report(study.evaluate_horizon(candles, 300)),
            "15m": study.horizon_report(study.evaluate_horizon(candles, 900)),
        },
        "signature": study.signature_report(candles),
        "hawkesBranchingRatio": (
            "NOT COMPUTED — next wave. Requires per-trade SOL arrival times; the reference "
            "series is 1-minute candles and no SOL trade-arrival collection exists yet."
        ),
        "collectedRounds": rounds.inventory(all_rounds),
        "collectTotals": collect_totals,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out / f"base-rate-{stamp}.json"
    out_path.write_text(json.dumps(result, indent=1))
    print(render(result))
    print(f"\nresult -> {out_path}")


def render(result: dict) -> str:
    """A terse human report; every rate line names its denominator and the approximation."""
    lines = [
        "jupiter_base_rate v1 (registered before fetch)",
        f"reference: {result['reference']['label']}",
        f"minutes: {result['reference']['minutes']}  "
        f"kraken-overlap dispersion: {result['reference']['venueDispersionVsKraken']}",
        f"fee floor: {study.FEE_FLOOR['statement']}",
    ]
    for name, h in result["horizons"].items():
        for rule in ("pUpEndpointRule", "pUpTwapRule"):
            b = h[rule]
            ci = b["wilson95"]
            ci_txt = f"[{ci[0]:.4f}, {ci[1]:.4f}]" if ci else "n/a"
            rate = f"{b['rate']:.4f}" if b["rate"] is not None else "n/a"
            lines.append(f"{name} {rule}: {rate} ({b['up']}/{b['n']}) wilson95 {ci_txt}")
        d = h["ruleDisagreement"]
        d_rate = f"{d['rate']:.4f}" if d["rate"] is not None else "n/a"
        lines.append(f"{name} rule disagreement: {d_rate} ({d['count']}/{d['n']})")
        nt = h["logReturn"]["nearTieUnder10bps"]
        nt_rate = f"{nt['rate']:.4f}" if nt["rate"] is not None else "n/a"
        mean_abs = h["logReturn"]["meanAbs"]
        lines.append(
            f"{name} |logret| mean: {mean_abs:.6f}  near-tie(<10bps): {nt_rate}"
            if mean_abs is not None
            else f"{name} logret: no data"
        )
    sig = result["signature"]
    if "wallTime" in sig:
        cells = [
            f"tau={row['lagSeconds']}s sigma2={row['sigma2']:.3e} (n={row['pairs']})"
            for row in sig["wallTime"]
            if row["sigma2"] is not None
        ]
        lines.append("sigma^2(tau) wall: " + "; ".join(cells))
        lines.append(f"  reading: {sig['reading']}")
    lines.append(f"collected rounds: {json.dumps(result['collectedRounds'])}")
    lines.append(f"hawkes: {result['hawkesBranchingRatio']}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="joshi_analysis.jupiter_base_rate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="fetch the reference series (bounded, receipted)")
    f.add_argument("--days", type=float, default=30.0)
    f.add_argument("--max-requests", type=int, default=200)
    f.add_argument("--out", type=Path, default=STATE / "reference")
    f.set_defaults(fn=cmd_fetch)
    r = sub.add_parser("run", help="compute the registered estimands")
    r.add_argument("--reference", type=Path, default=STATE / "reference")
    r.add_argument("--collect", type=Path, default=STATE)
    r.add_argument("--out", type=Path, default=STATE / "study")
    r.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
