"""Mayhem outcomes on REAL flows — the amendment instrument.

Registered in studies/REGISTRATION_mayhem_real_flows.md (after docs/MAYHEM_MODE.md, before
any estimand here was computed). Run:
    uv run --group research python studies/mayhem_real_flows.py all
Stages: decompose crowd real   (cached under studies/data/mayhem_arm/)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRESH = REPO_ROOT / "studies" / "data" / "operator_crime_fresh"
WIN_A = REPO_ROOT / "studies" / "data" / "operator_crime"
OUT = REPO_ROOT / "studies" / "data" / "mayhem_arm"
LEDGER_GLOB = str(FRESH / "ledger" / "day=*.parquet")
ROLES = OUT / "mayhem_birth.parquet"
AGENT = "BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"
DAY = 86400
MARGIN = 21600
CROWD_MIN = 25  # pinned in the registration; sensitivity cells 10 and 50 declared there


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


def _wilson(k: int, n: int, z: float = 1.959964):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def cmd_decompose() -> int:
    """Vault outflow by AMOUNT: into-curve vs burn (supply-reducing tx) vs other."""
    con = _duck()
    rows = con.execute(f"""
WITH mb AS (SELECT mint, curve_owner, birth_slot, birth_tx FROM read_parquet('{ROLES}')),
txsum AS (
  SELECT l.mint, l.block_slot, l.tx_index, sum(l.delta_raw) AS tx_net
  FROM read_parquet('{LEDGER_GLOB}') l SEMI JOIN mb ON l.mint = mb.mint
  GROUP BY 1, 2, 3
),
vneg AS (
  SELECT l.mint, l.block_slot, l.tx_index, l.delta_raw AS vdelta
  FROM read_parquet('{LEDGER_GLOB}') l JOIN mb
    ON l.mint = mb.mint AND l.owner = '{AGENT}'
  WHERE l.delta_raw < 0
    AND l.block_slot * 1000000 + l.tx_index > mb.birth_slot * 1000000 + mb.birth_tx
),
cur AS (
  SELECT l.mint, l.block_slot, l.tx_index, l.delta_raw AS cdelta
  FROM read_parquet('{LEDGER_GLOB}') l JOIN mb
    ON l.mint = mb.mint AND l.owner = mb.curve_owner
)
SELECT
  sum(-v.vdelta) AS total_out,
  sum(-v.vdelta) FILTER (WHERE c.cdelta = -v.vdelta) AS into_curve,
  sum(-v.vdelta) FILTER (WHERE t.tx_net < 0) AS burned,
  sum(-v.vdelta) FILTER (WHERE c.cdelta IS DISTINCT FROM -v.vdelta AND t.tx_net >= 0)
      AS other,
  count(*) FILTER (WHERE t.tx_net < 0) AS burn_rows,
  count(DISTINCT v.mint) FILTER (WHERE t.tx_net < 0) AS burn_mints
FROM vneg v
LEFT JOIN cur c ON v.mint = c.mint AND v.block_slot = c.block_slot AND v.tx_index = c.tx_index
JOIN txsum t ON v.mint = t.mint AND v.block_slot = t.block_slot AND v.tx_index = t.tx_index
""").fetchone()
    tot, into, burned, other, brows, bmints = [x or 0 for x in rows]
    n_coins = con.execute(f"SELECT count(*) FROM read_parquet('{ROLES}')").fetchone()[0]
    print("\n=== vault outflow by AMOUNT (correction of the row-based read) ===")
    print(f"  total outflow      : {tot / 1e15:,.1f} vault-units (n coins {n_coins:,})")
    print(f"  sold into curve    : {into / 1e15:,.1f}  ({into / tot:.1%})")
    print(f"  burned (supply cut): {burned / 1e15:,.1f}  ({burned / tot:.1%})  "
          f"across {bmints:,} coins / {brows:,} burn rows")
    print(f"  other              : {other / 1e15:,.1f}  ({other / tot:.1%})")
    art = {"total_out_raw": int(tot), "into_curve_raw": int(into),
           "burned_raw": int(burned), "other_raw": int(other),
           "burn_mints": int(bmints)}
    (OUT / "vault_decomposition.json").write_text(json.dumps(art, indent=2))
    return 0


def cmd_crowd() -> int:
    """Per-coin human crowd within 24h + any-human-activity-after-24h flag."""
    con = _duck()
    out = OUT / "mayhem_crowd.parquet"
    if out.exists():
        print("  mayhem_crowd.parquet present, skipping")
        return 0
    t0 = time.time()
    sql = f"""
WITH mb AS (SELECT mint, curve_owner, birth_slot, birth_time FROM read_parquet('{ROLES}')),
hrows AS (
  SELECT l.mint, l.owner, l.delta_raw, l.block_slot, l.block_time, mb.birth_time
  FROM read_parquet('{LEDGER_GLOB}') l JOIN mb ON l.mint = mb.mint
  WHERE l.owner <> mb.curve_owner AND l.owner <> '{AGENT}'
    AND l.block_slot >= mb.birth_slot
)
SELECT mint,
  count(DISTINCT owner) FILTER (
    WHERE delta_raw > 0 AND block_time <= birth_time + {DAY}) AS human_crowd_24h,
  count(*) FILTER (WHERE block_time > birth_time + {DAY}) AS human_rows_after_24h,
  max(block_time) FILTER (WHERE block_time > birth_time + {DAY}) AS t_last_human_after
FROM hrows GROUP BY mint
"""
    tmp = OUT / ".tmp-crowd.parquet"
    con.execute(f"COPY ({sql}) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"  crowd: {n:,} coins in {time.time() - t0:.0f}s")
    return 0


def cmd_real(seed: int = 20260829) -> int:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    con = _duck()
    df = pd.read_parquet(OUT / "mayhem_coins.parquet")
    crowd = pd.read_parquet(OUT / "mayhem_crowd.parquet")
    sp = pd.read_parquet(OUT / "mayhem_sniper_prior.parquet")
    df = df.merge(crowd, on="mint", how="left").merge(sp, on="mint", how="left")
    df["human_crowd_24h"] = df["human_crowd_24h"].fillna(0)
    df["human_rows_after_24h"] = df["human_rows_after_24h"].fillna(0)
    df["sniper_prior_max"] = df["sniper_prior_max"].fillna(0)
    wend = int(con.execute(
        f"SELECT max(block_time) FROM read_parquet('{LEDGER_GLOB}')").fetchone()[0])

    # REAL dirty history: prior REAL events only (A/fresh-standard rips+dumps; mayhem dumps)
    hist_sql = f"""
WITH m AS (SELECT mint, deployer, birth_time, t_dump FROM read_parquet('{OUT / "mayhem_coins.parquet"}')),
ev AS (
  SELECT deployer, t_dump AS t, CASE WHEN is_rip THEN 1 ELSE 0 END AS e_rip
  FROM read_parquet('{WIN_A / "panel.parquet"}')
  WHERE deployer IS NOT NULL AND t_dump IS NOT NULL
  UNION ALL
  SELECT deployer, t_dump, CASE WHEN is_rip THEN 1 ELSE 0 END
  FROM read_parquet('{FRESH / "panel.parquet"}')
  WHERE deployer IS NOT NULL AND t_dump IS NOT NULL
  UNION ALL
  SELECT deployer, t_dump, 0 FROM m WHERE deployer IS NOT NULL AND t_dump IS NOT NULL
)
SELECT m.mint,
       coalesce(sum(CASE WHEN ev.t < m.birth_time THEN 1 ELSE 0 END), 0) AS real_prior_dumps,
       coalesce(sum(CASE WHEN ev.t < m.birth_time THEN ev.e_rip ELSE 0 END), 0) AS real_prior_rips
FROM m LEFT JOIN ev ON ev.deployer = m.deployer
GROUP BY m.mint
"""
    hist = con.execute(hist_sql).df()
    df = df.merge(hist, on="mint", how="left")
    df["real_dirty"] = (df["real_prior_dumps"] > 0) | (df["real_prior_rips"] > 0)

    art: dict = {"n": len(df), "window_end": wend, "crowd_min": CROWD_MIN}
    # E1 crowd distribution
    c = df["human_crowd_24h"]
    art["E1"] = {"p25": float(c.quantile(0.25)), "p50": float(c.quantile(0.50)),
                 "p75": float(c.quantile(0.75)), "p90": float(c.quantile(0.90)),
                 "ge10": float((c >= 10).mean()), "ge25": float((c >= 25).mean()),
                 "ge50": float((c >= 50).mean())}
    print(f"\n=== E1 human crowd within 24h (agent excluded), n={len(df):,} ===")
    print(f"  p25/p50/p75/p90: {art['E1']['p25']:.0f} / {art['E1']['p50']:.0f} / "
          f"{art['E1']['p75']:.0f} / {art['E1']['p90']:.0f}")
    print(f"  share with >=10 humans {art['E1']['ge10']:.1%}, >=25 {art['E1']['ge25']:.1%}, "
          f">=50 {art['E1']['ge50']:.1%}")

    # E2 alive past the window
    exp = df[df["birth_time"] <= wend - DAY - MARGIN]
    r2 = float((exp["human_rows_after_24h"] > 0).mean())
    lo2, hi2 = _wilson(int((exp["human_rows_after_24h"] > 0).sum()), len(exp))
    art["E2"] = {"n_exposure_complete": len(exp), "rate": r2, "ci95": [lo2, hi2]}
    print(f"=== E2 any HUMAN activity after t+24h: {r2:.2%} [{lo2:.2%}, {hi2:.2%}] "
          f"(n={len(exp):,} exposure-complete) ===")

    # E3 real rip
    for k in (10, CROWD_MIN, 50):
        df[f"real_rip_{k}"] = df["t_dump"].notna() & (df["human_crowd_24h"] >= k)
    key = f"real_rip_{CROWD_MIN}"
    d1 = df[df["birth_time"] <= df["birth_time"].min() + DAY]  # day-1 cohort
    art["E3"] = {"pooled": float(df[key].mean()), "n_events": int(df[key].sum()),
                 "day1": float(d1[key].mean()),
                 "sensitivity": {k: float(df[f"real_rip_{k}"].mean()) for k in (10, 50)}}
    print(f"=== E3 REAL RIP (dump & crowd>={CROWD_MIN}): pooled {art['E3']['pooled']:.2%} "
          f"({art['E3']['n_events']:,} events)  day1 {art['E3']['day1']:.2%}  "
          f"[sens crowd>=10: {art['E3']['sensitivity'][10]:.2%}, "
          f">=50: {art['E3']['sensitivity'][50]:.2%}] ===")

    # E4 separations (deployer-clustered bootstrap risk ratios)
    y = df[key].astype(int)
    feats = {
        "human_bundled(n_snipers>=2)": df["n_snipers"] >= 2,
        "dev_buy>=2%_of_2e15": df["dev_buy_share"] >= 0.02,
        "real_dirty_history": df["real_dirty"],
    }
    clusters = df["deployer"].fillna("__none__").to_numpy()
    uniq = np.unique(clusters)
    idx_by = {cl: np.flatnonzero(clusters == cl) for cl in uniq}
    art["E4"] = {}
    print("=== E4 feature separation vs REAL RIP ===")
    for name, mask in feats.items():
        def rr(dd, m=mask):
            mm = m.reindex(dd.index)
            pa = dd.loc[mm.fillna(False), key].mean()
            pb = dd.loc[~mm.fillna(False), key].mean()
            return pa / pb if pb > 0 else float("nan")
        obs = rr(df)
        vals = []
        for _ in range(2000):
            take = rng.choice(uniq, size=len(uniq), replace=True)
            vals.append(rr(df.iloc[np.concatenate([idx_by[cl] for cl in take])]))
        vals = np.array([v for v in vals if np.isfinite(v)])
        lo, hi = (float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))) \
            if len(vals) else (float("nan"),) * 2
        art["E4"][name] = {"rr": float(obs), "ci95": [lo, hi],
                           "n_flag": int(mask.sum())}
        print(f"  {name:<28} risk ratio {obs:5.2f}x  [95% {lo:.2f}, {hi:.2f}]  "
              f"(flagged {int(mask.sum()):,})")

    # E5 CLEAN-analog conjunction
    allg = ((df["n_snipers"] <= 1) & (df["dev_buy_share"] < 0.02)
            & ~df["real_dirty"] & (df["sniper_prior_max"] == 0))
    n_adm, k_bad = int(allg.sum()), int(y[allg].sum())
    prec = 1 - k_bad / n_adm if n_adm else float("nan")
    lo5, hi5 = _wilson(n_adm - k_bad, n_adm)
    art["E5"] = {"admitted": n_adm, "admitted_bad": k_bad, "precision": prec,
                 "ci95": [lo5, hi5], "admit_rate": n_adm / len(df),
                 "base_rate": float(y.mean())}
    print(f"=== E5 CLEAN-analog: admits {n_adm:,} ({n_adm / len(df):.1%}), "
          f"real-rip precision {prec:.4%} [{lo5:.4%}, {hi5:.4%}] vs base "
          f"{1 - y.mean():.4%} clean ===")
    (OUT / "real_flows.json").write_text(json.dumps(art, indent=2))
    return 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stages = {"decompose": cmd_decompose, "crowd": cmd_crowd, "real": cmd_real}
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
