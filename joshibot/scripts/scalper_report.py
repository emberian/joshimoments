#!/usr/bin/env python3
"""Read the shadow scalper's tape and answer: is the bounded-loss scalp positive-EV?

Three sections:

1. REALIZED — the pessimistically-marked PnL distribution of shadow positions. This is
   the empirical crux of the throughput reframe: many small bounded-loss bets, and the
   question is whether the distribution's mean clears friction.
2. FRICTION — how much of gross movement the fees ate, since at ~$9-18 clips the
   priority fee is a first-order term, not a rounding error.
3. THRESHOLD SWEEP — the payoff of jittering. Because every cutoff was drawn per
   decision from a logged range, and because epsilon of decisions acted against the
   verdict, each nearby filter is a counterfactual policy we can score by importance
   weighting WITHOUT redeploying.

On not reusing ``shitcoims_replay.ope.evaluate``: that function takes a context-FREE
``target_probability`` (one probability per action name). A threshold sweep needs a
CONTEXT-DEPENDENT target — pi'(enter | features) differs per candidate. Rather than bend
its contract we compute the importance weights here and reuse its ``Estimate`` shape and
its effective-sample-size gate, which is where the judgment lives. Extending, not mirroring.

Reward convention, and it is the honest one: a SKIP earns exactly 0 (we did not trade).
So skipped decisions contribute nothing to the numerator but still count in n and in the
weight normalisation — which is precisely how a policy that skips more gets scored.

Read-only. Tolerates partial final lines: the collector may be appending as we read.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

STATE = Path(__file__).resolve().parent.parent / "state" / "scalper"
LAMPORTS = 1_000_000_000
EXPLORE_EPS = 0.05  # must match ScalperPolicy default; reported so a mismatch is visible


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # partial final line while the collector appends


@dataclass(frozen=True, slots=True)
class Sweep:
    label: str
    ips: float
    snips: float
    ess: float
    n: int
    max_weight: float
    n_would_enter: int

    @property
    def trustworthy(self) -> bool:
        """Same blunt gate as shitcoims_replay.ope.Estimate: below 10% ESS is theatre."""
        return self.n > 0 and self.ess / self.n >= 0.10


def target_enter_prob(features: dict[str, float], thresholds: dict[str, float], eps: float) -> float:
    """pi'(enter | x) for a candidate policy with FIXED thresholds, same epsilon."""
    passes = (
        thresholds["min_age_s"] <= features.get("age_s", 0.0) <= thresholds["max_age_s"]
        and features.get("trade_recency_s", 1e9) <= thresholds["max_trade_recency_s"]
        and features.get("sol_in_curve", 0.0) >= thresholds["min_sol_in_curve"]
    )
    return (1.0 - eps) if passes else eps


def sweep(decisions: list[dict], rewards: dict[str, float], thresholds: dict[str, float],
          label: str, eps: float) -> Sweep:
    weights: list[float] = []
    weighted: list[float] = []
    would = 0
    for d in decisions:
        p_log = d.get("propensity")
        if not p_log or p_log <= 0:
            continue
        feats = d.get("features") or {}
        p_enter = target_enter_prob(feats, thresholds, eps)
        if d.get("action") == "enter":
            p_target = p_enter
            r = rewards.get(d.get("decision_id", ""), 0.0)
        else:
            p_target = 1.0 - p_enter
            r = 0.0  # a skip earns exactly zero
        if p_enter > 0.5:
            would += 1
        w = p_target / p_log
        weights.append(w)
        weighted.append(w * r)
    n = len(weights)
    if n == 0:
        return Sweep(label, 0.0, 0.0, 0.0, 0, 0.0, 0)
    sw = sum(weights)
    ips = sum(weighted) / n
    snips = (sum(weighted) / sw) if sw else 0.0
    ess = (sw**2 / sum(w * w for w in weights)) if any(weights) else 0.0
    return Sweep(label, ips, snips, ess, n, max(weights), would)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--eps", type=float, default=EXPLORE_EPS)
    ap.add_argument("--run", help="restrict to one run_id (default: newest complete run)")
    args = ap.parse_args()

    decisions = list(read_jsonl(STATE / "decisions.jsonl"))
    all_closes = list(read_jsonl(STATE / "closes.jsonl"))

    # Two integrity filters, both earned. (1) Records lacking spend_lamports are from an
    # older writer whose drain path emitted a partial row; averaging them against complete
    # rows produced a -151% "return". (2) Records pool across runs unless separated by
    # run_id — different seeds and thresholds are different experiments.
    incomplete = [c for c in all_closes if "spend_lamports" not in c]
    complete = [c for c in all_closes if "spend_lamports" in c]
    runs = sorted({c.get("run_id", "unstamped") for c in complete})
    if args.run:
        complete = [c for c in complete if c.get("run_id") == args.run]
    elif len(runs) > 1:
        newest = runs[-1]
        complete = [c for c in complete if c.get("run_id") == newest]

    closes = complete
    rewards = {c["decision_id"]: c.get("pnl_lamports", 0) / LAMPORTS for c in closes if "decision_id" in c}
    if args.run:
        decisions = [d for d in decisions if d.get("run_id") == args.run]

    entered = [d for d in decisions if d.get("action") == "enter"]
    passed = [d for d in decisions if d.get("verdict_pass")]
    explored = [d for d in decisions if d.get("explored")]

    pnls = [c.get("pnl_lamports", 0) / LAMPORTS for c in closes]
    spends = [c.get("spend_lamports", 0) / LAMPORTS for c in closes if c.get("spend_lamports")]
    fees = [c.get("priority_fees_lamports", 0) / LAMPORTS for c in closes if c.get("priority_fees_lamports")]
    lost = [c for c in closes if c.get("exit_reason") == "feed_lost"]

    out: dict[str, Any] = {
        "runs_seen": runs,
        "incomplete_records_ignored": len(incomplete),
        "decisions": len(decisions),
        "verdict_pass": len(passed),
        "entered": len(entered),
        "explore_flips": len(explored),
        "closes": len(closes),
        "feed_lost": len(lost),
    }

    if pnls:
        wins = [p for p in pnls if p > 0]
        out["realized"] = {
            "n": len(pnls),
            "total_sol": sum(pnls),
            "mean_sol": statistics.mean(pnls),
            "median_sol": statistics.median(pnls),
            "hit_rate": len(wins) / len(pnls),
            "mean_win_sol": statistics.mean(wins) if wins else 0.0,
            "mean_loss_sol": statistics.mean([p for p in pnls if p <= 0]) or 0.0,
            "worst_sol": min(pnls),
            "best_sol": max(pnls),
            "total_deployed_sol": sum(spends),
            "return_on_deployed": (sum(pnls) / sum(spends)) if spends else None,
            "priority_fees_sol": sum(fees),
            "fees_as_pct_of_deployed": (sum(fees) / sum(spends) * 100) if spends else None,
        }

    # Threshold sweep — only meaningful once rewards exist.
    sweeps: list[Sweep] = []
    if rewards:
        base = {"min_age_s": 55.0, "max_age_s": 2250.0, "max_trade_recency_s": 17.5,
                "min_sol_in_curve": 10.0}
        grid = [
            ("baseline (range midpoints)", base),
            ("stricter recency <=8s", {**base, "max_trade_recency_s": 8.0}),
            ("looser recency <=30s", {**base, "max_trade_recency_s": 30.0}),
            ("deeper curve >=20 SOL", {**base, "min_sol_in_curve": 20.0}),
            ("shallower curve >=5 SOL", {**base, "min_sol_in_curve": 5.0}),
            ("younger <=600s", {**base, "max_age_s": 600.0}),
            ("older ok <=3600s", {**base, "max_age_s": 3600.0}),
        ]
        sweeps = [sweep(decisions, rewards, th, lbl, args.eps) for lbl, th in grid]
        out["sweep"] = [
            {"label": s.label, "ips_sol": s.ips, "snips_sol": s.snips, "ess": s.ess,
             "ess_frac": s.ess / s.n if s.n else 0.0, "n": s.n,
             "max_weight": s.max_weight, "would_enter": s.n_would_enter,
             "trustworthy": s.trustworthy}
            for s in sweeps
        ]

    if args.json:
        print(json.dumps(out, indent=1))
        return

    print("=" * 74)
    print("SHADOW SCALPER REPORT  (pessimistic marking: entry at next obs, exit after deadline)")
    print("=" * 74)
    print(f"  decisions {out['decisions']}   verdict_pass {out['verdict_pass']}"
          f"   entered {out['entered']}   explore_flips {out['explore_flips']}")
    print(f"  closes {out['closes']}   feed_lost {out['feed_lost']}")
    if out["incomplete_records_ignored"]:
        print(f"  !! ignored {out['incomplete_records_ignored']} incomplete close record(s) "
              f"(pre-fix partial rows, no spend field)")
    if len(runs) > 1:
        print(f"  runs in file: {len(runs)} -> reporting newest ({runs[-1]}); --run to pick")
    if "realized" not in out:
        print("\n  NO CLOSES YET — holds are minutes; let the collector run longer.")
        return
    r = out["realized"]
    print("\n--- REALIZED (shadow, floor estimate) ---")
    print(f"  total {r['total_sol']:+.5f} SOL on {r['total_deployed_sol']:.4f} SOL deployed"
          f"  ({(r['return_on_deployed'] or 0)*100:+.2f}%)")
    print(f"  mean {r['mean_sol']:+.6f}  median {r['median_sol']:+.6f}  hit rate {r['hit_rate']*100:.0f}%")
    print(f"  mean win {r['mean_win_sol']:+.6f}   mean loss {r['mean_loss_sol']:+.6f}")
    print(f"  best {r['best_sol']:+.5f}   worst {r['worst_sol']:+.5f}")
    print(f"  priority fees {r['priority_fees_sol']:.5f} SOL"
          f"  = {r['fees_as_pct_of_deployed']:.2f}% of deployed")
    if sweeps:
        print("\n--- THRESHOLD SWEEP (off-policy, from logged propensities) ---")
        print(f"  {'policy':<28}{'SNIPS/dec':>12}{'ESS':>8}{'ESS%':>7}{'enters':>8}  trust")
        for s in sweeps:
            print(f"  {s.label:<28}{s.snips:>12.6f}{s.ess:>8.1f}"
                  f"{(s.ess/s.n*100 if s.n else 0):>6.1f}%{s.n_would_enter:>8}  "
                  f"{'yes' if s.trustworthy else 'NO'}")
        print("\n  SNIPS/dec = self-normalised value per decision, in SOL.")
        print("  Below 10% ESS the point value is theatre — read only the 'yes' rows.")


if __name__ == "__main__":
    main()
