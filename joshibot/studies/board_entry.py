#!/usr/bin/env python3
"""Event study: what happens to a coin AFTER it joins a pump.fun board?

The operator's hypothesis, in their words: trending coins "are often in an overall
downslump" and a small position taken then can be exited for a mini profit. That
splits into a claim we can test with no model at all — board entry is an attention
shock with an exact timestamp, delivered exogenously by the platform — and a
conditioning variable, drawdown-at-entry, which the API serves directly.

THE CENSORING PROBLEM, stated first because it decides what this can conclude.
We observe a coin's market cap only while it sits on some board. A coin that
collapses probably leaves the boards, so disappearance is INFORMATIVE censoring,
not missingness at random. Every forward return here is therefore conditioned on
survival-in-view, which biases the mean UP. We report the censoring rate at every
horizon alongside the return so the bias is visible rather than buried, and we
never quote a return without it.

The null: entry timestamps are permuted within board, holding the market's own
path fixed. If the effect survives that, entry timing carries information; if it
does not, we are measuring the market and not the event.
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

TAPE = Path(__file__).resolve().parent.parent / "state" / "boards"
HORIZONS_S = (300, 1800, 3600, 7200, 14400, 21600, 28800)


def load(paths: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for f in sorted(glob.glob(paths)):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # collector may be mid-append
    return rows


def build_price_series(rows: list[dict[str, Any]]) -> dict[str, list[tuple[float, float]]]:
    """mint -> [(t_ingest, usd_market_cap)], from every board snapshot that saw it."""
    series: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        if r.get("kind") != "board_snapshot":
            continue
        for m in r.get("members", []):
            mc = m.get("usd_market_cap") or 0.0
            if mc > 0:
                series[m["mint"]].append((m["t_ingest"], float(mc)))
    for mint in series:
        series[mint].sort()
    return series


def value_at(points: list[tuple[float, float]], t: float, tol: float = 240.0) -> float | None:
    """Market cap at or after t, within tol seconds. None = censored (not in view)."""
    for ts, mc in points:
        if ts >= t:
            return mc if ts - t <= tol else None
    return None


def forward_returns(
    entries: list[dict[str, Any]], series: dict[str, list[tuple[float, float]]]
) -> list[dict[str, Any]]:
    out = []
    for e in entries:
        mint, t0 = e["mint"], e["t_ingest"]
        mc0 = e.get("usd_market_cap") or 0.0
        if mc0 <= 0 or mint not in series:
            continue
        rec: dict[str, Any] = {
            "mint": mint,
            "board": e["board"],
            "t": t0,
            "mc0": mc0,
            "drawdown": e.get("drawdown_from_ath", -1.0),
            "rank": e.get("rank"),
        }
        for h in HORIZONS_S:
            mc = value_at(series[mint], t0 + h)
            rec[f"r{h}"] = (mc / mc0 - 1.0) if mc else None
        out.append(rec)
    return out


def summarise(recs: list[dict[str, Any]], label: str) -> None:
    print(f"\n  {label}  (n={len(recs)})")
    print(f"    {'horizon':>8}{'observed':>10}{'censored':>10}{'median':>10}{'mean':>10}{'p(up)':>8}")
    for h in HORIZONS_S:
        vals = [r[f"r{h}"] for r in recs if r.get(f"r{h}") is not None]
        n_obs, n_tot = len(vals), len(recs)
        if not vals:
            print(f"    {h:>7}s{'0':>10}{'100%':>10}{'—':>10}{'—':>10}{'—':>8}")
            continue
        cens = (n_tot - n_obs) / n_tot * 100
        up = sum(1 for v in vals if v > 0) / len(vals) * 100
        print(
            f"    {h:>7}s{n_obs:>10}{cens:>9.0f}%{statistics.median(vals)*100:>9.2f}%"
            f"{statistics.mean(vals)*100:>9.2f}%{up:>7.0f}%"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tape", default=str(TAPE / "*.jsonl"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rows = load(args.tape)
    entries = [r for r in rows if r.get("kind") == "board_entry"]
    series = build_price_series(rows)
    print("=" * 74)
    print("BOARD ENTRY EVENT STUDY")
    print("=" * 74)
    print(f"  {len(rows):,} tape rows · {len(entries):,} entries · {len(series):,} mints in view")

    recs = forward_returns(entries, series)
    print(f"  {len(recs):,} entries with a usable market cap at t0")

    summarise(recs, "ALL ENTRIES")

    # The operator's conditioning variable: is the coin beaten down when it arrives?
    known = [r for r in recs if r["drawdown"] >= 0]
    if known:
        cut = statistics.median([r["drawdown"] for r in known])
        summarise([r for r in known if r["drawdown"] >= cut], f"DEEP DRAWDOWN (>= {cut*100:.0f}% off ATH)")
        summarise([r for r in known if r["drawdown"] < cut], f"SHALLOW DRAWDOWN (< {cut*100:.0f}% off ATH)")

    # THE NULL. A first version permuted entry TIMES and was broken: a permuted time
    # often falls before the coin's first observation, so `value_at` returns the entry
    # point itself and the return is a spurious exact 0.0. That produced a median of
    # 0.00% and deflated p(up) by counting those zeros as not-up — an artifact, not a
    # baseline.
    #
    # This version holds the TIMES fixed and permutes the MINTS, which asks the right
    # question: at the moments boards actually churn, is the entering coin special, or
    # would any coin in view have done as well? Same times, same market conditions,
    # same censoring machinery.
    rng = random.Random(args.seed)
    in_view = list(series.keys())
    fake = []
    for e in entries:
        mint = rng.choice(in_view)
        pts = series.get(mint) or []
        at_t = value_at(pts, e["t_ingest"])
        if not at_t:
            continue  # that coin was not in view then; a fair draw requires it to be
        e2 = dict(e)
        e2["mint"], e2["usd_market_cap"] = mint, at_t
        fake.append(e2)
    summarise(forward_returns(fake, series), "NULL — same times, randomly chosen coin in view")

    print("\n  Censoring is INFORMATIVE: a coin that collapses leaves the boards, so every")
    print("  observed return is conditioned on survival-in-view and is biased UP. Read the")
    print("  censored column before the return column.")


if __name__ == "__main__":
    main()
