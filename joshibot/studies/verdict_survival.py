"""Survival by birth verdict — "what usually happens next" for the screen card.

Registered in studies/REGISTRATION_verdict_survival.md BEFORE any estimand was computed.
Run:  uv run --group research python studies/verdict_survival.py all
Stages: crossings stats   (cached under studies/data/verdict_survival/)

Population: standard-BORN fresh coins (2026-08-26..28) with an identified deployer.
Verdicts assigned causally from panel birth-time features, precedence per score.py
(panel-expressible arms; the live Jaccard crew-match arm has no panel column — disclosed).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRESH = REPO_ROOT / "studies" / "data" / "operator_crime_fresh"
OUT = REPO_ROOT / "studies" / "data" / "verdict_survival"

CURVE_K = 32_190_000_000_000_000_000_000_000
TOKEN_OFFSET = 73_000_000_000_000
STD_SUPPLY = 1_000_000_000_000_000
BORN = f"minted_raw = {STD_SUPPLY} AND decimals = 6"
LEDGER_GLOB = str(FRESH / "ledger" / "day=*.parquet")
# running-peak materiality: peak mcap >= 100 SOL <=> running-min balance <= MAT_BAL
MAT_BAL = int(math.sqrt(CURVE_K * 1e15 / 1e9 / 100.0)) - TOKEN_OFFSET
SQRT10 = math.sqrt(10.0)
GAP_G = 3600
GAP_G2 = 21600
HORIZONS = {"1h": 3600, "6h": 21600, "24h": 86400}


def _duck():
    import duckdb

    con = duckdb.connect()
    con.execute("SET threads=6")
    con.execute("SET memory_limit='12GB'")
    con.execute("SET preserve_insertion_order=false")
    tmp = OUT / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{tmp}'")
    return con


def _wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, center - half), min(1.0, center + half))


CROSS_SQL = f"""
WITH born AS (
  SELECT mint, curve_owner, birth_time
  FROM read_parquet('{FRESH / "birth.parquet"}') WHERE {BORN}
),
crows AS (
  SELECT l.mint, l.block_slot, l.tx_index, l.block_time, l.delta_raw
  FROM read_parquet('{LEDGER_GLOB}') l JOIN born b
    ON l.mint = b.mint AND l.owner = b.curve_owner
),
path AS (
  SELECT mint, block_slot, tx_index, block_time,
         sum(delta_raw) OVER (PARTITION BY mint ORDER BY block_slot, tx_index
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bal
  FROM crows
),
path2 AS (
  SELECT *,
         min(bal) OVER (PARTITION BY mint ORDER BY block_slot, tx_index
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS rmin,
         lag(block_time) OVER (PARTITION BY mint ORDER BY block_slot, tx_index) AS prev_t
  FROM path
)
SELECT mint,
       min(block_time) FILTER (
         WHERE (bal + {TOKEN_OFFSET})::DOUBLE >= (rmin + {TOKEN_OFFSET})::DOUBLE * {SQRT10}
           AND rmin <= {MAT_BAL}) AS t_collapse,
       max(block_time - prev_t) AS max_gap_s,
       count(*) FILTER (WHERE block_time - prev_t >= {GAP_G}) AS n_gaps_1h,
       count(*) FILTER (WHERE block_time - prev_t >= {GAP_G2}) AS n_gaps_6h,
       max(block_time) AS t_last_curve
FROM path2 GROUP BY mint
"""


def cmd_crossings() -> int:
    con = _duck()
    out = OUT / "crossings.parquet"
    if out.exists():
        print("  crossings.parquet present, skipping")
        return 0
    t0 = time.time()
    tmp = OUT / ".tmp-crossings.parquet"
    con.execute(f"COPY ({CROSS_SQL}) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"  crossings: {n:,} coins in {time.time() - t0:.0f}s")
    return 0


def _verdicts(df):
    known = (df["prior_rips"] > 0) | (df["prior_dumps"] > 0) | (df["sniper_prior_max"] > 0)
    bundled = ~known & (df["n_snipers"] >= 2)
    notclean = ~known & ~bundled & (df["dev_buy_share"] >= 0.02)
    clean = ~known & ~bundled & ~notclean
    v = df["mint"].map(lambda _: "")
    v[known] = "KNOWN_CREW"
    v[bundled] = "BUNDLED"
    v[notclean] = "NOT_CLEAN"
    v[clean] = "CLEAN"
    return v


def cmd_stats(seed: int = 20260829) -> int:
    import numpy as np
    import pandas as pd
    from lifelines import KaplanMeierFitter

    rng = np.random.default_rng(seed)
    df = pd.read_parquet(FRESH / "panel.parquet")
    df = df[df["deployer"].notna()].copy()
    cr = pd.read_parquet(OUT / "crossings.parquet")
    df = df.merge(cr, on="mint", how="left")
    df["verdict"] = _verdicts(df)
    window_end = int(df["t_last"].max())
    df["day"] = pd.to_datetime(df["birth_time"], unit="s").dt.strftime("%Y-%m-%d")
    art: dict = {"n": len(df), "window_end": window_end,
                 "verdict_counts": df["verdict"].value_counts().to_dict()}
    print(f"\n=== population n={len(df):,}  window_end={window_end} ===")
    print("  verdicts:", art["verdict_counts"])

    # endpoint quality: resurrection rate (an internal >=G gap IS a resurrection)
    res1 = float((df["n_gaps_1h"] > 0).mean())
    res6 = float((df["n_gaps_6h"] > 0).mean())
    art["resurrection_rate_1h"] = res1
    art["resurrection_rate_6h"] = res6
    print(f"  resurrection rate: {res1:.2%} at G=1h, {res6:.2%} at G=6h "
          f"(registered gate: >20% at both invalidates the endpoint)")

    verdicts = ["CLEAN", "BUNDLED", "KNOWN_CREW", "NOT_CLEAN"]

    # S1 fixed-horizon alive; S3 collapse-by-24h; S4 graduate-by-24h
    art["S1"] = {}
    for hname, hsec in HORIZONS.items():
        sub = df[df["birth_time"] <= window_end - hsec]
        cell = {}
        for v in verdicts:
            d = sub[sub["verdict"] == v]
            k = int(((d["t_last"] - d["birth_time"]) >= hsec).sum())
            lo, hi = _wilson(k, len(d))
            cell[v] = {"n": len(d), "alive": k / len(d) if len(d) else float("nan"),
                       "ci95": [lo, hi]}
        art["S1"][hname] = cell
        print(f"  [S1 alive at {hname}] " + "  ".join(
            f"{v} {c['alive']:.1%} (n={c['n']:,})" for v, c in cell.items()))

    sub24 = df[df["birth_time"] <= window_end - 86400].copy()
    art["S3_collapse_24h"], art["S4_grad_24h"] = {}, {}
    for v in verdicts:
        d = sub24[sub24["verdict"] == v]
        kc = int(((d["t_collapse"] - d["birth_time"]) <= 86400).sum())
        kg = int(((d["t_grad"] - d["birth_time"]) <= 86400).sum())
        loc, hic = _wilson(kc, len(d))
        log_, hig = _wilson(kg, len(d))
        art["S3_collapse_24h"][v] = {"n": len(d), "p": kc / len(d) if len(d) else None,
                                     "ci95": [loc, hic]}
        art["S4_grad_24h"][v] = {"n": len(d), "p": kg / len(d) if len(d) else None,
                                 "ci95": [log_, hig]}
    print("  [S3 collapse by 24h] " + "  ".join(
        f"{v} {c['p']:.2%}" for v, c in art["S3_collapse_24h"].items() if c["p"] is not None))
    print("  [S4 graduate by 24h] " + "  ".join(
        f"{v} {c['p']:.2%}" for v, c in art["S4_grad_24h"].items() if c["p"] is not None))

    # S2 KM time-to-quiet, censoring when window_end - t_last < G; day-stratified signs
    art["S2"] = {}
    for v in verdicts:
        d = df[df["verdict"] == v]
        dur = (d["t_last"] - d["birth_time"]).clip(lower=0).to_numpy().astype(float)
        observed = ((window_end - d["t_last"]) >= GAP_G).to_numpy()
        cens_dur = np.where(observed, dur, (window_end - d["birth_time"]).to_numpy())
        km = KaplanMeierFitter().fit(cens_dur, observed)
        med = float(km.median_survival_time_)
        q = {}
        for p in (0.25, 0.75):
            try:
                q[p] = float(km.percentile(1 - p))
            except Exception:
                q[p] = float("nan")
        per_day_med = {}
        for day, g in d.groupby("day"):
            dd = (g["t_last"] - g["birth_time"]).clip(lower=0).to_numpy().astype(float)
            oo = ((window_end - g["t_last"]) >= GAP_G).to_numpy()
            cd = np.where(oo, dd, (window_end - g["birth_time"]).to_numpy())
            per_day_med[day] = float(KaplanMeierFitter().fit(cd, oo).median_survival_time_)
        art["S2"][v] = {"n": len(d), "km_median_s": med, "km_p25_s": q[0.25],
                        "km_p75_s": q[0.75], "per_day_median_s": per_day_med}
        print(f"  [S2 {v}] KM median {med:.0f}s  IQR [{q[0.25]:.0f}, {q[0.75]:.0f}]  "
              f"per-day medians {per_day_med}")

    # S5 quantiles among event-observed
    art["S5"] = {}
    for v in verdicts:
        d = df[(df["verdict"] == v) & ((window_end - df["t_last"]) >= GAP_G)]
        dur = (d["t_last"] - d["birth_time"]).clip(lower=0)
        art["S5"][v] = {"n": len(d), "p25_s": float(dur.quantile(0.25)),
                        "p50_s": float(dur.quantile(0.50)), "p75_s": float(dur.quantile(0.75))}

    # deployer-clustered bootstrap for alive-at-6h differences (ship rule)
    def alive6_diff(a, b, d):
        sub = d[d["birth_time"] <= window_end - 21600]
        pa = ((sub.loc[sub["verdict"] == a, "t_last"]
               - sub.loc[sub["verdict"] == a, "birth_time"]) >= 21600).mean()
        pb = ((sub.loc[sub["verdict"] == b, "t_last"]
               - sub.loc[sub["verdict"] == b, "birth_time"]) >= 21600).mean()
        return pa - pb

    art["ship_rule"] = {}
    clusters = df["deployer"].to_numpy()
    uniq = np.unique(clusters)
    idx_by = {c: np.flatnonzero(clusters == c) for c in uniq}
    for other in ("BUNDLED", "KNOWN_CREW"):
        obs = alive6_diff("CLEAN", other, df)
        vals = []
        for _ in range(2000):
            take = rng.choice(uniq, size=len(uniq), replace=True)
            rows = np.concatenate([idx_by[c] for c in take])
            vals.append(alive6_diff("CLEAN", other, df.iloc[rows]))
        vals = np.array(vals)
        lo, hi = float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))
        art["ship_rule"][f"CLEAN_minus_{other}_alive6h"] = {"obs": float(obs),
                                                           "ci95": [lo, hi]}
        print(f"  [ship rule] CLEAN - {other} alive-at-6h: {obs:+.2%}  "
              f"95% cluster-boot [{lo:+.2%}, {hi:+.2%}]")

    (OUT / "results.json").write_text(json.dumps(art, indent=2))
    print(f"  -> {OUT / 'results.json'}")
    return 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stages = {"crossings": cmd_crossings, "stats": cmd_stats}
    args = sys.argv[1:] or ["all"]
    todo = list(stages) if args == ["all"] else args
    for s in todo:
        if s not in stages:
            print(f"unknown stage {s}; stages: {', '.join(stages)} | all")
            return 2
        stages[s]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
