"""Is a coin's regime stable enough to act on? The question that decides the tag's value.

signature_regimes.py established that the signature slope sigma^2(32)/sigma^2(1) spreads widely
and continuously across graduated-pool series (roughly a quarter reverting, a third diffusive,
four tenths trending). A regime TAG built on that slope is only actionable if a coin's regime
persists longer than the time it takes to measure and act on it. This study measures that, on the
whole qualifying population rather than a 76-series sample.

DESIGN
  Population: mints with >= MIN_TOTAL priced amm_pool_vault_fill trades at their DOMINANT venue
  (the pool carrying the most such fills; ties broken lexically). The dominant-venue restriction
  keeps one price level per series instead of mixing pools. Bonding-curve rows are excluded as in
  the prior study: the curve price is a validated model, not an observed ratio, and mixing the two
  confounds dynamics with price construction.

  Holdout: each series is split in half BY EVENT COUNT in (block_slot, tx_index) order -- a time
  split, never a random one. First-half slope predicts second-half slope, or it does not. A pair
  contributes to a half's variogram only when both its endpoints lie in that half, which is
  exactly the pair set a per-half measurement would see.

  Both clocks. Event clock: lag = a count of trades. Wall clock: last observed price per second,
  every pair of samples with an integer gap within 25% of the target lag (identical to the
  estimator in joshi_analysis.regime, expressed as exact-gap equijoins).

  Windows: consecutive complete windows of L events per L in WINDOW_SIZES; the correlation of
  slope between window k and window k+1 says at what history length the tag starts to cohere.

  Bands: worked (>= 50% of workable half-hours carrying >= 8% range) vs quiet (<= 10%), the
  definitions of the prior study, to ask whether the coins Ember actually works have more or less
  stable regimes.

Point labels here use the point-estimate bands (reverting < 0.75 <= diffusive < 1.33 <= trending).
The CI-gated operational tag lives in joshi_analysis.regime and its determinacy is measured
separately by regime_determinacy.py; this study is about whether the underlying quantity
persists at all.

The extracted per-mint event stream is checkpointed to <corpus>/tmp/regime_ev.parquet so a rerun
skips the 6.5 GB trades scan. Delete that file to force a rebuild.

Usage: uv run --offline python -u corpus/regime_stability.py <corpus-dir>
"""

from __future__ import annotations

import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import duckdb

from joshi_analysis.regime import REVERT_BELOW, TREND_ABOVE, band

MIN_TOTAL = 800          # events at the dominant venue; each half then has >= 400, the tag minimum
MIN_PAIRS_WALL = 100     # endpoint-lag pairs a wall slope must stand on to be counted
LAG_LOW, LAG_HIGH = 1, 32
WALL_TOLERANCE = 0.25
WINDOW_SIZES = (200, 400, 800, 1600, 3200)
BAND_L = 400             # window length for the per-band windowed persistence breakdown
N_PERMUTATIONS = 2000
LABELS = ("reverting", "diffusive", "trending")

_t0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - _t0:7.1f}s] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- statistics, pure python

def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(_ranks(xs), _ranks(ys))


def spearman_permutation_p(xs: list[float], ys: list[float], seed: int = 0) -> float:
    """Two-sided permutation p for the observed Spearman rho, shuffling y."""
    observed = abs(spearman(xs, ys))
    rng = random.Random(seed)
    rx = _ranks(xs)
    ry = _ranks(ys)
    hits = 0
    for _ in range(N_PERMUTATIONS):
        rng.shuffle(ry)
        if abs(pearson(rx, ry)) >= observed:
            hits += 1
    return (hits + 1) / (N_PERMUTATIONS + 1)


def label_persistence(pairs: list[tuple[str, str]]) -> dict:
    """Transition counts, accuracy of predict-same, the base rates, and Cohen's kappa."""
    n = len(pairs)
    counts = {(a, b): 0 for a in LABELS for b in LABELS}
    for a, b in pairs:
        counts[(a, b)] += 1
    agree = sum(counts[(label, label)] for label in LABELS)
    p2 = {label: sum(counts[(a, label)] for a in LABELS) / n for label in LABELS}
    p1 = {label: sum(counts[(label, b)] for b in LABELS) / n for label in LABELS}
    modal = max(p2.values())
    chance = sum(p1[label] * p2[label] for label in LABELS)
    accuracy = agree / n
    kappa = (accuracy - chance) / (1 - chance) if chance < 1 else float("nan")
    return {"n": n, "counts": counts, "accuracy": accuracy, "modal_base": modal,
            "chance": chance, "kappa": kappa, "p1": p1, "p2": p2}


def render_matrix(stats: dict) -> str:
    lines = [f"{'':>12}" + "".join(f"{lab[:9]:>11}" for lab in LABELS) + "   (second half ->)"]
    for a in LABELS:
        row = "".join(f"{stats['counts'][(a, b)]:>11}" for b in LABELS)
        lines.append(f"{a:>12}{row}")
    lines.append(
        f"  persist={stats['accuracy']:.3f} vs modal-base={stats['modal_base']:.3f} "
        f"chance={stats['chance']:.3f} kappa={stats['kappa']:.3f} n={stats['n']}"
    )
    return "\n".join(lines)


def slope_of(s1: float | None, c1: int, s32: float | None, c32: int) -> float | None:
    """(V(32)/32) / V(1) from summed squared diffs; pbar cancels in the ratio."""
    if not c1 or not c32 or s1 is None or s32 is None or s1 <= 0 or s32 <= 0:
        return None
    return (s32 / c32 / LAG_HIGH) / (s1 / c1)


# ---------------------------------------------------------------- corpus extraction

def build_ev(con: duckdb.DuckDBPyConnection, corpus: str) -> None:
    ev_path = f"{corpus}/tmp/regime_ev.parquet"
    if not Path(ev_path).exists():
        log("extracting dominant-venue event streams from the trades corpus...")
        con.execute(f"""
            COPY (
              WITH fills AS (
                SELECT mint, venue_owner, block_slot, tx_index, block_time,
                       price_sol_per_token AS price
                FROM read_parquet('{corpus}/out/trades/day=*/trades.parquet')
                WHERE price_sol_per_token IS NOT NULL AND price_sol_per_token > 0
                  AND price_kind = 'amm_pool_vault_fill'
              ),
              dom AS (
                SELECT mint, venue_owner, n, row_number() OVER (ORDER BY mint) AS mid FROM (
                  SELECT mint, venue_owner, count(*) n,
                         row_number() OVER (PARTITION BY mint ORDER BY count(*) DESC, venue_owner) rk
                  FROM fills GROUP BY 1, 2
                ) WHERE rk = 1 AND n >= {MIN_TOTAL}
              )
              SELECT d.mid, f.block_time AS bt, f.price, d.n AS total,
                     row_number() OVER (PARTITION BY d.mid ORDER BY f.block_slot, f.tx_index) AS rn
              FROM fills f JOIN dom d USING (mint, venue_owner)
            ) TO '{ev_path}' (FORMAT parquet)
        """)
        log(f"checkpointed to {ev_path}")
    else:
        log(f"reusing checkpoint {ev_path}")
    con.execute(f"CREATE VIEW ev AS SELECT * FROM read_parquet('{ev_path}')")


def build_pairs(con: duckdb.DuckDBPyConnection) -> None:
    """One window sort; every later aggregate is a cheap filtered scan of this."""
    con.execute(f"""
        CREATE TEMP TABLE pairs AS
        SELECT mid, rn, total, bt, price,
               lead(price, {LAG_LOW})  OVER w - price AS e1,
               lead(price, {LAG_HIGH}) OVER w - price AS e32
        FROM ev WINDOW w AS (PARTITION BY mid ORDER BY rn)
    """)
    log("pairs table built (lag-1 and lag-32 diffs)")


HALF = "CASE WHEN rn * 2 <= total THEN 1 ELSE 2 END"


def event_slopes_halves(con: duckdb.DuckDBPyConnection) -> dict:
    rows = con.execute(f"""
        SELECT mid, {HALF} AS half, count(*) n, max(bt) - min(bt) AS span,
               sum(e1 * e1)   FILTER ((rn * 2 <= total) = ((rn + {LAG_LOW}) * 2 <= total))  s1,
               count(e1)      FILTER ((rn * 2 <= total) = ((rn + {LAG_LOW}) * 2 <= total))  c1,
               sum(e32 * e32) FILTER ((rn * 2 <= total) = ((rn + {LAG_HIGH}) * 2 <= total)) s32,
               count(e32)     FILTER ((rn * 2 <= total) = ((rn + {LAG_HIGH}) * 2 <= total)) c32
        FROM pairs GROUP BY 1, 2
    """).fetchall()
    return {(mid, half): {"n": n, "span": span, "slope": slope_of(s1, c1, s32, c32)}
            for mid, half, n, span, s1, c1, s32, c32 in rows}


def event_slopes_all(con: duckdb.DuckDBPyConnection) -> dict:
    rows = con.execute("""
        SELECT mid, count(*) n, max(bt) - min(bt) AS span,
               sum(e1 * e1) s1, count(e1) c1, sum(e32 * e32) s32, count(e32) c32
        FROM pairs GROUP BY 1
    """).fetchall()
    return {mid: {"n": n, "span": span, "slope": slope_of(s1, c1, s32, c32)}
            for mid, n, span, s1, c1, s32, c32 in rows}


def window_slopes(con: duckdb.DuckDBPyConnection, size: int) -> dict:
    rows = con.execute(f"""
        SELECT mid, (rn - 1) // {size} AS wk,
               sum(e1 * e1)   FILTER ((rn - 1) // {size} = (rn + {LAG_LOW} - 1) // {size})  s1,
               count(e1)      FILTER ((rn - 1) // {size} = (rn + {LAG_LOW} - 1) // {size})  c1,
               sum(e32 * e32) FILTER ((rn - 1) // {size} = (rn + {LAG_HIGH} - 1) // {size}) s32,
               count(e32)     FILTER ((rn - 1) // {size} = (rn + {LAG_HIGH} - 1) // {size}) c32
        FROM pairs WHERE (rn - 1) // {size} < total // {size}
        GROUP BY 1, 2
    """).fetchall()
    out: dict = defaultdict(dict)
    for mid, wk, s1, c1, s32, c32 in rows:
        slope = slope_of(s1, c1, s32, c32)
        if slope is not None:
            out[mid][wk] = slope
    return out


def wall_slopes(con: duckdb.DuckDBPyConnection, by_half: bool) -> dict:
    part = HALF if by_half else "0"
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sec AS
        SELECT mid, {part} AS part, bt, max_by(price, rn) AS price
        FROM ev GROUP BY 1, 2, 3
    """)
    return _wall_from_sec(con)


def wall_slopes_windowed(con: duckdb.DuckDBPyConnection, size: int) -> dict:
    """Wall slopes per complete L-event window; keys are (mid, window index)."""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sec AS
        SELECT mid, (rn - 1) // {size} AS part, bt, max_by(price, rn) AS price
        FROM ev WHERE (rn - 1) // {size} < total // {size} GROUP BY 1, 2, 3
    """)
    return _wall_from_sec(con)


def _wall_from_sec(con: duckdb.DuckDBPyConnection) -> dict:
    """One plain equijoin per integer gap: the optimizer never sees a cross join it can misplan."""
    acc: dict = defaultdict(lambda: {LAG_LOW: [0.0, 0], LAG_HIGH: [0.0, 0]})
    for lag in (LAG_LOW, LAG_HIGH):
        low = math.ceil(lag * (1 - WALL_TOLERANCE))
        high = math.floor(lag * (1 + WALL_TOLERANCE))
        for gap in range(low, high + 1):
            rows = con.execute(f"""
                SELECT a.mid, a.part,
                       sum((b.price - a.price) * (b.price - a.price)) AS sd, count(*) AS pairs
                FROM sec a
                JOIN sec b ON b.mid = a.mid AND b.part = a.part AND b.bt = a.bt + {gap}
                GROUP BY 1, 2
            """).fetchall()
            for mid, part_v, sd, pairs in rows:
                cell = acc[(mid, part_v)][lag]
                cell[0] += sd
                cell[1] += pairs
    out = {}
    for key, by_lag in acc.items():
        (sd1, pairs1), (sd32, pairs32) = by_lag[LAG_LOW], by_lag[LAG_HIGH]
        slope = None
        if pairs1 >= MIN_PAIRS_WALL and pairs32 >= MIN_PAIRS_WALL and sd1 > 0 and sd32 > 0:
            slope = (sd32 / pairs32 / LAG_HIGH) / (sd1 / pairs1)
        out[key] = {"slope": slope, "pairs1": pairs1, "pairs32": pairs32}
    return out


def excursion_bands(con: duckdb.DuckDBPyConnection) -> dict:
    rows = con.execute("""
        WITH blk AS (
          SELECT mid, bt // 1800 AS blkid, count(*) n, max(price) hi, min(price) lo
          FROM ev GROUP BY 1, 2
        )
        SELECT mid, count(*) AS workable,
               sum(CASE WHEN hi / lo - 1 >= 0.08 THEN 1 ELSE 0 END) AS qual
        FROM blk WHERE n >= 4 GROUP BY 1
    """).fetchall()
    out = {}
    for mid, workable, qual in rows:
        if workable < 20:
            out[mid] = "thin"
        elif qual / workable >= 0.5:
            out[mid] = "worked"
        elif qual / workable <= 0.1:
            out[mid] = "quiet"
        else:
            out[mid] = "mid"
    return out


# ---------------------------------------------------------------- report

def correlation_block(name: str, pairs: list[tuple[float, float]]) -> None:
    xs = [math.log(a) for a, _ in pairs]
    ys = [math.log(b) for _, b in pairs]
    rho = spearman(xs, ys)
    p = spearman_permutation_p(xs, ys)
    print(f"  {name}: n={len(pairs)} spearman={rho:.3f} (perm p={p:.4f}, {N_PERMUTATIONS} perms) "
          f"pearson(log)={pearson(xs, ys):.3f}", flush=True)


def main() -> None:
    corpus = sys.argv[1]
    con = duckdb.connect()
    con.execute("SET memory_limit='12GB'")
    build_ev(con, corpus)
    build_pairs(con)
    n_mints, n_rows = con.execute("SELECT count(DISTINCT mid), count(*) FROM ev").fetchone()
    print(f"POPULATION: {n_mints} mints with >= {MIN_TOTAL} priced amm_pool_vault_fill trades at "
          f"their dominant venue ({n_rows} trades, 10-day corpus, dominant venue only).")
    print(f"Slope = sigma^2({LAG_HIGH})/sigma^2({LAG_LOW}); bands: reverting < {REVERT_BELOW} <= "
          f"diffusive < {TREND_ABOVE} <= trending. Halves split by event count in slot order.\n",
          flush=True)

    ev_all = event_slopes_all(con)
    log("full-series event slopes done")
    dist = defaultdict(int)
    for stats in ev_all.values():
        dist[band(stats["slope"]) if stats["slope"] is not None else "unmeasurable"] += 1
    total = sum(dist.values())
    print("FULL-SERIES EVENT-CLOCK DISTRIBUTION (point estimates):")
    for key in ("reverting", "diffusive", "trending", "unmeasurable"):
        print(f"  {key:<13} {dist[key]:>5} ({100 * dist[key] / total:.1f}%)")
    print(flush=True)

    ev_half = event_slopes_halves(con)
    log("split-half event slopes done")
    print("SPLIT-HALF STABILITY, EVENT CLOCK (first half -> second half):")
    both = [(ev_half[(mid, 1)]["slope"], ev_half[(mid, 2)]["slope"])
            for (mid, part) in ev_half if part == 1 and (mid, 2) in ev_half]
    measurable = [(a, b) for a, b in both if a is not None and b is not None]
    print(f"  mints with both halves measurable: {len(measurable)} of {n_mints}")
    correlation_block("slope correlation", measurable)
    print(render_matrix(label_persistence([(band(a), band(b)) for a, b in measurable])))
    print(flush=True)

    wall_half = wall_slopes(con, by_half=True)
    log("split-half wall slopes done")
    wall_all = wall_slopes(con, by_half=False)
    log("full-series wall slopes done")
    print(f"SPLIT-HALF STABILITY, WALL CLOCK (per-second samples, lags {LAG_LOW}s and {LAG_HIGH}s "
          f"+/-25%, >= {MIN_PAIRS_WALL} pairs at both lags):")
    wboth = [(wall_half[(mid, 1)]["slope"], wall_half[(mid, 2)]["slope"])
             for (mid, part) in wall_half if part == 1 and (mid, 2) in wall_half]
    wmeasurable = [(a, b) for a, b in wboth if a is not None and b is not None]
    print(f"  mints with both halves measurable: {len(wmeasurable)} of {n_mints}")
    correlation_block("slope correlation", wmeasurable)
    print(render_matrix(label_persistence([(band(a), band(b)) for a, b in wmeasurable])))
    print(flush=True)

    bands = excursion_bands(con)
    print("WINDOWED PERSISTENCE, EVENT CLOCK (slope of window k vs k+1, complete windows only).")
    print("  'demeaned' subtracts each mint's mean log slope (mints with >= 3 windows): the")
    print("  persistence left after the coin's stable identity is removed.")
    band_pairs: dict = defaultdict(list)
    for size in WINDOW_SIZES:
        per_mint = window_slopes(con, size)
        pairs = []
        xs_d: list[float] = []
        ys_d: list[float] = []
        for mid, slopes in per_mint.items():
            for wk, s in slopes.items():
                nxt = slopes.get(wk + 1)
                if nxt is not None:
                    pairs.append((s, nxt))
                    if size == BAND_L:
                        band_pairs[bands.get(mid, "thin")].append((s, nxt))
            if len(slopes) >= 3:
                mean_ls = sum(math.log(s) for s in slopes.values()) / len(slopes)
                for wk, s in slopes.items():
                    nxt = slopes.get(wk + 1)
                    if nxt is not None:
                        xs_d.append(math.log(s) - mean_ls)
                        ys_d.append(math.log(nxt) - mean_ls)
        if len(pairs) < 10:
            print(f"  L={size:>5}: only {len(pairs)} consecutive-window pairs, skipped")
            continue
        stats = label_persistence([(band(a), band(b)) for a, b in pairs])
        xs = [math.log(a) for a, _ in pairs]
        ys = [math.log(b) for _, b in pairs]
        demeaned = spearman(xs_d, ys_d) if len(xs_d) >= 10 else float("nan")
        note = " (below the tag's 400-event minimum)" if size < 400 else ""
        print(f"  L={size:>5}: {len(pairs):>6} window pairs from {len(per_mint):>5} mints  "
              f"spearman={spearman(xs, ys):.3f}  demeaned={demeaned:.3f}  "
              f"persist={stats['accuracy']:.3f} vs chance={stats['chance']:.3f}  "
              f"kappa={stats['kappa']:.3f}{note}", flush=True)
    print(flush=True)

    print(f"WINDOWED PERSISTENCE BY EXCURSION BAND, EVENT CLOCK, L={BAND_L}:")
    for name in ("worked", "mid", "quiet", "thin"):
        pairs = band_pairs[name]
        if len(pairs) < 10:
            print(f"  {name:<7} n={len(pairs)} (too few)")
            continue
        stats = label_persistence([(band(a), band(b)) for a, b in pairs])
        xs = [math.log(a) for a, _ in pairs]
        ys = [math.log(b) for _, b in pairs]
        print(f"  {name:<7} {len(pairs):>6} window pairs  spearman={spearman(xs, ys):.3f}  "
              f"persist={stats['accuracy']:.3f} vs chance={stats['chance']:.3f}  "
              f"kappa={stats['kappa']:.3f}", flush=True)
    print(flush=True)

    print("WINDOWED PERSISTENCE, WALL CLOCK (same complete L-event windows; a window's wall slope")
    print(f"  needs >= {MIN_PAIRS_WALL} pairs at both 1s and 32s, so sparse windows drop out):")
    for size in WINDOW_SIZES:
        if size < 400:
            continue
        per_win = wall_slopes_windowed(con, size)
        log(f"windowed wall slopes done for L={size}")
        slopes_by_mint: dict = defaultdict(dict)
        n_windows = 0
        for (mid, wk), stats_w in per_win.items():
            n_windows += 1
            if stats_w["slope"] is not None:
                slopes_by_mint[mid][wk] = stats_w["slope"]
        pairs = []
        for slopes in slopes_by_mint.values():
            for wk, s in slopes.items():
                nxt = slopes.get(wk + 1)
                if nxt is not None:
                    pairs.append((s, nxt))
        measurable = sum(len(v) for v in slopes_by_mint.values())
        if len(pairs) < 10:
            print(f"  L={size:>5}: {measurable}/{n_windows} windows measurable, "
                  f"only {len(pairs)} adjacent pairs, skipped")
            continue
        stats = label_persistence([(band(a), band(b)) for a, b in pairs])
        xs = [math.log(a) for a, _ in pairs]
        ys = [math.log(b) for _, b in pairs]
        print(f"  L={size:>5}: {measurable:>6}/{n_windows:>6} windows measurable, "
              f"{len(pairs):>6} pairs  spearman={spearman(xs, ys):.3f}  "
              f"persist={stats['accuracy']:.3f} vs chance={stats['chance']:.3f}  "
              f"kappa={stats['kappa']:.3f}", flush=True)
    print(flush=True)

    print("THE TWO CLOCKS, FULL SERIES (event label vs wall label, both measurable):")
    clock_pairs = []
    for mid, stats in ev_all.items():
        wall = wall_all.get((mid, 0))
        if stats["slope"] is not None and wall and wall["slope"] is not None:
            clock_pairs.append((stats["slope"], wall["slope"]))
    print(f"  mints with both clocks measurable: {len(clock_pairs)} of {n_mints}")
    correlation_block("event slope vs wall slope", clock_pairs)
    agreement = label_persistence([(band(a), band(b)) for a, b in clock_pairs])
    print(render_matrix(agreement).replace("(second half ->)", "(wall ->)"))
    hard = sum(1 for a, b in clock_pairs
               if {band(a), band(b)} == {"reverting", "trending"})
    print(f"  hard disagreements (one clock reverting, the other trending): {hard} "
          f"({100 * hard / len(clock_pairs):.1f}% of {len(clock_pairs)})")
    print(flush=True)

    print("EXCURSION BANDS (worked >= 50% qualifying half-hours, quiet <= 10%, of >= 20 workable):")
    by_band: dict = defaultdict(list)
    for (mid, part), stats in ev_half.items():
        if part == 1 and (mid, 2) in ev_half:
            a, b = stats["slope"], ev_half[(mid, 2)]["slope"]
            if a is not None and b is not None:
                by_band[bands.get(mid, "thin")].append((a, b))
    for name in ("worked", "mid", "quiet", "thin"):
        pairs = by_band[name]
        if len(pairs) < 10:
            print(f"  {name:<7} n={len(pairs)} (too few to correlate)")
            continue
        slopes = sorted(a for a, _ in pairs)
        median = slopes[len(slopes) // 2]
        trending = sum(1 for s, _ in pairs if band(s) == "trending")
        xs = [math.log(a) for a, _ in pairs]
        ys = [math.log(b) for _, b in pairs]
        stats_b = label_persistence([(band(a), band(b)) for a, b in pairs])
        print(f"  {name:<7} n={len(pairs):>5} median first-half slope={median:.3f} "
              f"trending={100 * trending / len(pairs):.0f}%  split-half spearman={spearman(xs, ys):.3f} "
              f"persist={stats_b['accuracy']:.3f} vs chance={stats_b['chance']:.3f}", flush=True)
    print("\nEvery number above: dominant-venue amm_pool_vault_fill trades only, 2026-08-05..14, "
          "slope over event lags 1..32 (or wall lags 1s..32s), halves split by event count.",
          flush=True)


if __name__ == "__main__":
    main()
