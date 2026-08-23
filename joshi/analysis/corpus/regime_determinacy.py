"""How much history does the CI-gated regime tag need before it says anything?

regime_stability.py measures whether the underlying slope persists, using point estimates over
the full population. This study measures the OPERATIONAL tag -- joshi_analysis.regime.regime_tag,
whose label is only issued when the whole bootstrap confidence interval sits inside one band --
on the trailing window a live decision would actually have, at several window sizes.

Questions answered, each with its denominator:
  1. DETERMINACY: at n trailing events, how often does the tag commit to a label at all, per
     clock, and for what reasons does it refuse?
  2. RECOVERY: when it does commit, how often does the short-window label match the coin's
     full-history point band (the thing regime_stability.py shows to persist or not)?
  3. CLOCK AGREEMENT: on the same window, how often do the two clocks issue different labels?
  4. WALL COST: how many wall-clock seconds do those trailing windows span -- the price of
     waiting for a determinate tag.

Sample: SAMPLE mints drawn by hash(mid) from the checkpointed extraction regime_stability.py
writes to <corpus>/tmp/regime_ev.parquet (>= 800 priced amm_pool_vault_fill trades at the
dominant venue). Deterministic, held fixed; run regime_stability.py first.
Windows are the LAST n events of each series; a mint with fewer than n events is excluded from
that row's denominator, so larger windows describe a more active subpopulation -- said in the
output rather than hidden.

Usage: uv run --offline python corpus/regime_determinacy.py <corpus-dir>
"""

from __future__ import annotations

import sys
import zlib
from collections import defaultdict
from pathlib import Path

import duckdb

from joshi_analysis.regime import (
    band,
    event_curve,
    regime_tag,
    slope_from_curve,
    wall_curve,
    wall_samples,
)

MIN_TOTAL = 800
SAMPLE = 150
WINDOW_SIZES = (400, 800, 1600, 3200)
N_BOOT = 100
LABELS = ("reverting", "diffusive", "trending")


def load_sample(corpus: str) -> dict[int, tuple[list[int], list[float]]]:
    ev = f"{corpus}/tmp/regime_ev.parquet"
    if not Path(ev).exists():
        sys.exit(f"missing {ev}; run regime_stability.py first (it checkpoints the extraction)")
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    rows = con.execute(f"""
        WITH pick AS (
          SELECT DISTINCT mid FROM read_parquet('{ev}') ORDER BY hash(mid) LIMIT {SAMPLE}
        )
        SELECT e.mid, e.bt, e.price
        FROM read_parquet('{ev}') e JOIN pick USING (mid)
        ORDER BY e.mid, e.rn
    """).fetchall()
    series: dict[int, tuple[list[int], list[float]]] = defaultdict(lambda: ([], []))
    for mid, bt, price in rows:
        series[mid][0].append(bt)
        series[mid][1].append(price)
    return dict(series)


def main() -> None:
    corpus = sys.argv[1]
    series = load_sample(corpus)
    print(f"SAMPLE: {len(series)} mints by hash(mint) from the >= {MIN_TOTAL}-trade "
          f"dominant-venue amm population; tag = regime_tag(last n events), "
          f"{N_BOOT} bootstrap replicates, 90% CI.\n")

    full_band: dict[str, dict[int, str | None]] = {"event": {}, "wall": {}}
    for mint, (times, prices) in series.items():
        slope = slope_from_curve(event_curve(prices), 1, 32)
        full_band["event"][mint] = band(slope) if slope is not None else None
        wslope = slope_from_curve(wall_curve(*wall_samples(times, prices)), 1, 32)
        full_band["wall"][mint] = band(wslope) if wslope is not None else None

    header = (f"{'clock':>6} {'n':>5} {'mints':>6} {'determinate':>12} {'match_full':>11} "
              f"{'clocks_agree':>13} {'med_span_s':>11}   reasons")
    print(header)
    for size in WINDOW_SIZES:
        eligible = {m: sp for m, sp in series.items() if len(sp[1]) >= size}
        results: dict[str, dict[str, object]] = {"event": {}, "wall": {}}
        spans = []
        for mint, (times, prices) in eligible.items():
            wt, wp = times[-size:], prices[-size:]
            spans.append(wt[-1] - wt[0])
            seed = zlib.crc32(str(mint).encode())
            for clock in ("event", "wall"):
                results[clock][mint] = regime_tag(wt, wp, clock=clock, n_boot=N_BOOT, seed=seed)
        spans.sort()
        med_span = spans[len(spans) // 2] if spans else 0
        both_det = [m for m in eligible
                    if results["event"][m].label != "indeterminate"
                    and results["wall"][m].label != "indeterminate"]
        agree = sum(1 for m in both_det
                    if results["event"][m].label == results["wall"][m].label)
        for clock in ("event", "wall"):
            tags = results[clock]
            det = [m for m, t in tags.items() if t.label != "indeterminate"]
            reasons = defaultdict(int)
            for t in tags.values():
                if t.reason:
                    reasons[t.reason] += 1
            match = sum(1 for m in det if full_band[clock][m] == tags[m].label)
            det_pct = f"{len(det)}/{len(eligible)}"
            match_pct = f"{match}/{len(det)}" if det else "-"
            agree_pct = (f"{agree}/{len(both_det)}" if clock == "event" and both_det else
                         "" if clock == "wall" else "-")
            reason_txt = " ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
            print(f"{clock:>6} {size:>5} {len(eligible):>6} {det_pct:>12} {match_pct:>11} "
                  f"{agree_pct:>13} {med_span:>11}   {reason_txt}")
        print()

    for clock in ("event", "wall"):
        dist = defaultdict(int)
        for b in full_band[clock].values():
            dist[b or "unmeasurable"] += 1
        total = sum(dist.values())
        parts = ", ".join(f"{k}={dist[k]} ({100 * dist[k] / total:.0f}%)"
                          for k in ("reverting", "diffusive", "trending", "unmeasurable")
                          if dist[k])
        print(f"full-history point bands over the sample ({clock} clock): {parts}")
    print("match_full = determinate window labels equal to the full-history point band of the "
          "same clock; clocks_agree = same label from both clocks where both are determinate.")


if __name__ == "__main__":
    main()
