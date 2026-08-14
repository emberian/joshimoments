#!/usr/bin/env python3
"""Calibrate the shadow marker against real swaps — the sim2real gap, measured for free.

The shadow scalper marks fills with `curve_buy`/`curve_sell`: textbook constant product
with an assumed fee, an assumed flat priority fee, and — the big one — an implicit
assumption that **every transaction lands**. The cluster tape contains thousands of real
swaps with pre/post reserves, actual in/out amounts, and the actual fee paid. So every
one of those assumptions is checkable against other people's money, before we spend any
of ours.

Four measurements, each one a constant the shadow model currently guesses:

1. EFFECTIVE FEE — for each real swap, what output does constant product predict from the
   PRE reserves, and what did the trader actually get? The shortfall is the effective
   take (pool fee + protocol + whatever the router skimmed). Shadow assumes 100 bps.
2. PRIORITY FEE — shadow assumes a flat 0.0005 SOL. The tape carries `fee_lamports` per
   transaction. At a $9 clip a mis-estimated priority fee is a first-order error.
3. LANDING RATE — the assumption with no model at all. Attempts that never became swaps
   are recorded; if half our sends fail, every failure burns a fee and returns nothing,
   and true friction is roughly double what shadow reports.
4. COMPUTE UNITS — what a real swap costs, so the priority-fee bid can be sized rather
   than guessed.

Read-only over `state/cluster_tape/`. Constant product only: a DLMM fill walks bins and
is not a function of vault totals, so those rows are counted and excluded from (1).
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from pathlib import Path
from typing import Any

TAPE = Path(__file__).resolve().parent.parent / "state" / "cluster_tape"
LAMPORTS = 1_000_000_000


def load(kind_filter: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in glob.glob(str(TAPE / "swaps" / "*.jsonl")):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # collector may be appending
                if row.get("kind") in kind_filter:
                    rows.append(row)
    return rows


def effective_fee_bps(row: dict[str, Any]) -> float | None:
    """Constant-product prediction vs realised output, in bps of the predicted output.

    Positive = the trader got LESS than a zero-fee curve would give, i.e. the real take.
    """
    res = row.get("reserves") or {}
    if res.get("dex") != "pumpswap" or not res.get("replay_sufficient"):
        return None
    vaults = res.get("vaults") or []
    if len(vaults) != 2:
        return None
    in_mint, out_mint = row.get("token_in_mint"), row.get("token_out_mint")
    try:
        in_amt, out_amt = int(row["token_in_raw"]), int(row["token_out_raw"])
    except (KeyError, TypeError, ValueError):
        return None
    if in_amt <= 0 or out_amt <= 0:
        return None
    by_mint = {v.get("mint"): v for v in vaults}
    vin, vout = by_mint.get(in_mint), by_mint.get(out_mint)
    if not vin or not vout:
        return None
    try:
        pre_in, pre_out = int(vin["pre_raw"]), int(vout["pre_raw"])
    except (KeyError, TypeError, ValueError):
        return None
    if pre_in <= 0 or pre_out <= 0:
        return None
    # Zero-fee constant product: out = pre_out - k/(pre_in + in)
    predicted = pre_out - (pre_in * pre_out) // (pre_in + in_amt)
    if predicted <= 0:
        return None
    return (predicted - out_amt) / predicted * 10_000


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    i = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return s[i]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = load({"swap", "attempt"})
    swaps = [r for r in rows if r.get("kind") == "swap"]
    attempts = [r for r in rows if r.get("kind") == "attempt"]

    out: dict[str, Any] = {"swaps": len(swaps), "attempts": len(attempts)}

    # 1. effective fee, per pool
    per_pool: dict[str, list[float]] = {}
    dlmm_excluded = 0
    for r in swaps:
        if (r.get("reserves") or {}).get("dex") == "meteora_dlmm":
            dlmm_excluded += 1
            continue
        bps = effective_fee_bps(r)
        if bps is not None and -500 <= bps <= 5000:  # drop parse pathologies, keep real spread
            per_pool.setdefault(r.get("label", "?"), []).append(bps)
    out["effective_fee_bps"] = {
        label: {"n": len(v), "median": statistics.median(v), "p10": pct(v, 10), "p90": pct(v, 90)}
        for label, v in sorted(per_pool.items())
    }
    out["dlmm_swaps_excluded"] = dlmm_excluded

    # 2. priority / network fee actually paid
    fees = [int(r["fee_lamports"]) for r in swaps if r.get("fee_lamports")]
    out["network_fee_lamports"] = (
        {"n": len(fees), "median": statistics.median(fees), "p10": pct([float(f) for f in fees], 10),
         "p90": pct([float(f) for f in fees], 90), "max": max(fees)}
        if fees else {}
    )

    # 3. landing rate, per pool
    land: dict[str, dict[str, int]] = {}
    for r in rows:
        d = land.setdefault(r.get("label", "?"), {"swap": 0, "attempt": 0})
        d[r["kind"]] += 1
    out["landing"] = {
        label: {**d, "landed_rate": d["swap"] / (d["swap"] + d["attempt"])
                if (d["swap"] + d["attempt"]) else None}
        for label, d in sorted(land.items())
    }

    # 4. compute units
    cus = [int(r["compute_units"]) for r in swaps if r.get("compute_units")]
    out["compute_units"] = (
        {"n": len(cus), "median": statistics.median(cus), "p90": pct([float(c) for c in cus], 90)}
        if cus else {}
    )

    if args.json:
        print(json.dumps(out, indent=1))
        return

    print("=" * 78)
    print("SIM2REAL — shadow model assumptions vs measured reality")
    print("=" * 78)
    print(f"  {len(swaps):,} swaps, {len(attempts):,} attempts from the cluster tape")
    print(f"  ({dlmm_excluded:,} DLMM swaps excluded from fee calibration: a bin-walk fill is")
    print("   not a function of vault totals, so constant product cannot predict it)")

    print("\n--- 1. EFFECTIVE TAKE  (shadow assumes 100 bps) ---")
    print(f"  {'pool':<14}{'n':>6}{'p10':>9}{'median':>9}{'p90':>9}   vs shadow")
    for label, s in out["effective_fee_bps"].items():
        delta = s["median"] - 100
        print(f"  {label:<14}{s['n']:>6}{s['p10']:>9.0f}{s['median']:>9.0f}{s['p90']:>9.0f}"
              f"   {delta:+.0f} bps")

    if fees:
        f = out["network_fee_lamports"]
        print("\n--- 2. NETWORK FEE PAID  (shadow assumes 500,000 lamports flat) ---")
        print(f"  n={f['n']:,}  p10 {f['p10']:,.0f}  median {f['median']:,.0f}"
              f"  p90 {f['p90']:,.0f}  max {f['max']:,}")
        ratio = f["median"] / 500_000
        print(f"  median is {ratio:.2f}x the shadow assumption"
              f"  ({'shadow OVERSTATES' if ratio < 1 else 'shadow UNDERSTATES'} fee drag)")

    print("\n--- 3. LANDING RATE  (shadow has NO failure model: assumes every send lands) ---")
    print(f"  {'pool':<14}{'landed':>8}{'failed':>8}{'rate':>8}   friction multiplier if we fail alike")
    for label, d in out["landing"].items():
        if d["landed_rate"] is None:
            continue
        mult = 1 / d["landed_rate"] if d["landed_rate"] else float("inf")
        print(f"  {label:<14}{d['swap']:>8}{d['attempt']:>8}{d['landed_rate']*100:>7.0f}%   {mult:>5.2f}x")
    print("  NOTE: these are OTHER people's landing rates, including routers quoting pools they")
    print("  never intended to hit. Ours would differ. It is a prior, not our number.")

    if cus:
        c = out["compute_units"]
        print(f"\n--- 4. COMPUTE UNITS ---  median {c['median']:,.0f}  p90 {c['p90']:,.0f}"
              f"  (n={c['n']:,})")


if __name__ == "__main__":
    main()
