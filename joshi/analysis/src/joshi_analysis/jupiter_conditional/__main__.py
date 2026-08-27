"""CLI: ``fetch-fine`` (bounded, receipted), ``gate`` (step 0/1), ``run`` (gate then steps 2-4).

    cd analysis
    uv run --offline python -m joshi_analysis.jupiter_conditional fetch-fine --days 10
    uv run --offline python -m joshi_analysis.jupiter_conditional gate
    uv run --offline python -m joshi_analysis.jupiter_conditional run

``run`` re-executes the gate internally and uses ONLY the rule it selects; if the gate says
STOP, run stops. There is no rule override.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from joshi_analysis.jupiter_base_rate import rounds
from joshi_analysis.jupiter_base_rate.study import FEE_FLOOR

from . import finesol, rules, surface

STATE = Path("~/dev/joshi/state/prediction")
REFERENCE_NOTE = (
    "trade-level kraken/coinbase approximation of the Chainlink SOL/USD settlement stream — "
    "finer RESOLUTION than v1's 1m candles, same venue-basis gap (~2 bp median), "
    "NOT settlement-exact"
)


def real_labels(collect_dir: Path) -> list[tuple[str, int, int, str]]:
    parsed, _ = rounds.read_rounds(collect_dir)
    out = []
    for r in parsed.values():
        if r.genuine and r.terminal_label and r.window:
            out.append((r.event_id, r.window[0], r.window[1], r.terminal_label))
    return sorted(out, key=lambda row: row[1])


def cmd_fetch_fine(args: argparse.Namespace) -> None:
    end_s = int(time.time())
    start_s = end_s - int(args.days * 86400)
    receipt = finesol.fetch_kraken(start_s, end_s, args.out, max_requests=args.max_requests)
    print(receipt.read_text())
    labels = real_labels(args.collect)
    if labels:
        cb_start = min(row[1] for row in labels) - 420  # 60s twap + vol/short context
        print(finesol.fetch_coinbase(cb_start, args.out, max_requests=150).read_text())
    else:
        print("no labeled rounds yet -> coinbase cross-check span undefined, skipped (stated)")


def run_gate(fine_dir: Path, collect_dir: Path) -> dict:
    labels = real_labels(collect_dir)
    series = {"kraken": finesol.load_kraken(fine_dir)}
    coinbase = finesol.load_coinbase(fine_dir)
    if coinbase.times:
        series["coinbase"] = coinbase
    report = rules.gate(series, labels)
    if labels:
        lo = min(row[1] for row in labels)
        hi = max(row[2] for row in labels)
        report["resolution"] = {
            venue: finesol.gap_profile(s, lo, hi) for venue, s in series.items()
        }
    return report


def cmd_gate(args: argparse.Namespace) -> None:
    report = run_gate(args.fine, args.collect)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"conditional-gate-{stamp}.json"
    path.write_text(json.dumps(report, indent=1))
    print(render_gate(report))
    print(f"\ngate -> {path}")


def render_gate(report: dict) -> str:
    lines = [f"STEP 0/1 GATE — {report['labels']} real settlement labels"]
    for venue, per_rule in report["scores"].items():
        for rule_id, s in per_rule.items():
            frac = "n/a" if s["fraction"] is None else f"{s['fraction']:.2f}"
            lines.append(
                f"  {venue} rule ({rule_id}) {s['ruleText']}: {s['matches']}/{s['total']} = {frac}"
            )
            for row in s["rows"]:
                if row.get("match") is False:
                    lines.append(
                        f"    MISS {row['eventId']}: actual {row['actual']} recon {row['recon']}"
                        f" margin {row.get('marginBps', 0):+.2f}bps"
                    )
    v = report["verdict"]
    tail = f" rule ({v['rule']}) {v.get('ruleText')}" if v.get("rule") else f" — {v.get('reason')}"
    lines.append(f"VERDICT: {v['decision']}{tail}")
    if "resolution" in report:
        lines.append(f"resolution over labeled span: {json.dumps(report['resolution'])}")
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace) -> None:
    gate_report = run_gate(args.fine, args.collect)
    print(render_gate(gate_report))
    if gate_report["verdict"]["decision"] != "PROCEED":
        print("\nGATE SAYS STOP — counting at scale would count the wrong thing. Not counting.")
        return
    rule = gate_report["verdict"]["rule"]
    series = finesol.load_kraken(args.fine)
    contexts = {h: surface.build_context(series, h, rule) for h in (300, 900)}
    labels = real_labels(args.collect)
    result = {
        "contract": "joshi.jupiter_conditional.result.v1",
        "registration": "joshi.jupiter_conditional.registration.v1",
        "computedWall": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference": REFERENCE_NOTE,
        "gate": gate_report,
        "rule": {"id": rule, "text": rules.RULE_TEXT[rule]},
        "horizons": {
            "5m": surface.evaluate_horizon(contexts[300], 300),
            "15m": surface.evaluate_horizon(contexts[900], 900),
        },
        "realSettlementScore": surface.score_real_settlements(series, labels, contexts, rule),
        "feeFloor": FEE_FLOOR,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = args.out / f"conditional-{stamp}.json"
    path.write_text(json.dumps(result, indent=1))
    print(render_run(result))
    print(f"\nresult -> {path}")


def render_run(result: dict) -> str:
    lines = [
        "jupiter_conditional v1 (registered before fetch)",
        f"reference: {result['reference']}",
        f"gated rule: ({result['rule']['id']}) {result['rule']['text']}",
        f"fee floor: {FEE_FLOOR['statement']}",
    ]
    for name, h in result["horizons"].items():
        w = h["windows"]
        amb = w["ambiguousAtReferenceResolution"]
        lines.append(
            f"{name}: windows {w['total']} (A {w['setA']} / B {w['setB']}), "
            f"ambiguous(<{amb['bandBps']}bps) {amb['count']}/{amb['n']}, regimes {w['regimes']}"
        )
        cal = h["calibration"]
        pooled = cal["pooled"]
        if pooled.get("n"):
            lines.append(
                f"{name} calibration on held-out B: brier {pooled['brier']:.4f} "
                f"(baseline {cal['baselineBrier']:.4f}), ece {pooled['ece']:.4f} "
                f"-> {'LICENSED' if cal['licensedToContinue'] else 'NOT LICENSED — wrong counting'}"
            )
        late = [
            row
            for row in h["crossEvSurface"]
            if row["remainingFraction"] in (0.2, 0.1, 0.05) and not row["thin"]
        ]
        for row in sorted(late, key=lambda r: (-r["remainingFraction"], r["absDBandBps"])):
            ci = row["wilson95"]
            ev15 = row["evPerEntry"]["0.15"]
            lines.append(
                f"  {name} r={row['remainingFraction'] * h['horizonSeconds']:.0f}s "
                f"|d|={row['absDBandBps']}bps: cross={row['crossRate']:.3f} "
                f"({row['crossed']}/{row['n']}) [{ci[0]:.3f},{ci[1]:.3f}] "
                f"ev@15c={ev15['evPerContract']:+.3f}"
            )
        for row in h["trendClaim"]:
            if row["timing"] == "late" and row["distance"] in ("near", "far"):
                ci = row["wilson95"]
                thin = " THIN" if row["thin"] else ""
                lines.append(
                    f"  {name} trend={row['regime']} late {row['distance']} "
                    f"side-{row['currentSideVsTrend']}-trend: "
                    f"cross={row['crossRate']:.3f} ({row['crossed']}/{row['n']}) "
                    f"[{ci[0]:.3f},{ci[1]:.3f}]{thin}"
                )
        lines.append(f"  note: {h['entryPricesNote']}")
    rs = result["realSettlementScore"]
    if rs["score"].get("n"):
        lines.append(
            f"real settlements: {rs['rounds']} rounds, {rs['score']['n']} state-predictions, "
            f"brier {rs['score']['brier']:.4f} (small n, stated)"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="joshi_analysis.jupiter_conditional")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch-fine")
    f.add_argument("--days", type=float, default=10.0)
    f.add_argument("--max-requests", type=int, default=500)
    f.add_argument("--out", type=Path, default=STATE / "fine")
    f.add_argument("--collect", type=Path, default=STATE)
    f.set_defaults(fn=cmd_fetch_fine)
    g = sub.add_parser("gate")
    g.add_argument("--fine", type=Path, default=STATE / "fine")
    g.add_argument("--collect", type=Path, default=STATE)
    g.add_argument("--out", type=Path, default=STATE / "study")
    g.set_defaults(fn=cmd_gate)
    r = sub.add_parser("run")
    r.add_argument("--fine", type=Path, default=STATE / "fine")
    r.add_argument("--collect", type=Path, default=STATE)
    r.add_argument("--out", type=Path, default=STATE / "study")
    r.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
