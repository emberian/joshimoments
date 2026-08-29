"""Crew persistence across the gap — does the KNOWN_CREW arm's memory hold?

Registered in studies/REGISTRATION_crew_persistence.md BEFORE any estimand was computed.
Run:  uv run --group research python studies/crew_persistence.py all
Stages: traders p1 p2 p3 p4   (cached under studies/data/crew_persistence/)

Window A = studies/data/operator_crime (2026-08-05..14); window B =
studies/data/operator_crime_fresh (2026-08-26..28); 11-day unobserved gap between them.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WIN_A = REPO_ROOT / "studies" / "data" / "operator_crime"
WIN_B = REPO_ROOT / "studies" / "data" / "operator_crime_fresh"
OUT = REPO_ROOT / "studies" / "data" / "crew_persistence"
WSOL = "So11111111111111111111111111111111111111112"

RIP_PEAK_SOL = 100.0
RIP_DRAWDOWN = 0.90


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


def cmd_traders() -> int:
    """Distinct window-A pump-trading wallets (P2 denominator), one pass over the A ledger."""
    con = _duck()
    out = OUT / "a_traders.parquet"
    if out.exists():
        print("  a_traders.parquet present, skipping")
        return 0
    t0 = time.time()
    tmp = OUT / ".tmp-a_traders.parquet"
    con.execute(
        f"""COPY (
              SELECT DISTINCT owner FROM read_parquet('{WIN_A / "ledger" / "day=*.parquet"}')
              WHERE mint <> '{WSOL}'
            ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"  A traders: {n:,} distinct wallets in {time.time() - t0:.0f}s")
    return 0


def cmd_p1(seed: int = 20260829) -> int:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    a = pd.read_parquet(WIN_A / "panel.parquet",
                        columns=["deployer", "is_rip", "t_dump"])
    b = pd.read_parquet(WIN_B / "panel.parquet",
                        columns=["mint", "deployer", "is_rip", "peak_mcap_sol",
                                 "drawdown_from_peak"])
    b = b[b["deployer"].notna()].copy()
    b["collapse"] = ((b["peak_mcap_sol"] >= RIP_PEAK_SOL)
                     & (b["drawdown_from_peak"].fillna(0) >= RIP_DRAWDOWN))
    arec = a[a["deployer"].notna()].groupby("deployer").agg(
        a_launches=("is_rip", "size"), a_rips=("is_rip", "sum"),
        a_dumps=("t_dump", lambda s: s.notna().sum()))
    arec["dirty"] = (arec["a_rips"] > 0) | (arec["a_dumps"] > 0)
    b = b.merge(arec, left_on="deployer", right_index=True, how="left")
    b["group"] = np.where(b["a_launches"].isna(), "unseen",
                          np.where(b["dirty"].fillna(False), "dirty_A", "clean_A"))
    art: dict = {"n_b": len(b),
                 "recidivist_share": float((b["group"] != "unseen").mean())}
    print(f"\n=== P1 deployer recidivism across the 11-day gap (B n={len(b):,}) ===")
    print(f"  B coins whose deployer launched in A: {(b['group'] != 'unseen').sum():,} "
          f"({art['recidivist_share']:.2%})")
    for g in ("dirty_A", "clean_A", "unseen"):
        d = b[b["group"] == g]
        for oc in ("collapse", "is_rip"):
            k, n = int(d[oc].sum()), len(d)
            lo, hi = _wilson(k, n)
            art[f"{g}_{oc}"] = {"n": n, "p": k / n if n else None, "ci95": [lo, hi]}
        print(f"  {g:<8} n={len(d):>7,}  collapse {art[f'{g}_collapse']['p']:.3%} "
              f"[{art[f'{g}_collapse']['ci95'][0]:.3%}, {art[f'{g}_collapse']['ci95'][1]:.3%}]"
              f"  rip {art[f'{g}_is_rip']['p']:.3%}")
    # deployer-clustered bootstrap: dirty_A minus unseen collapse difference
    obs = b.loc[b["group"] == "dirty_A", "collapse"].mean() \
        - b.loc[b["group"] == "unseen", "collapse"].mean()
    clusters = b["deployer"].to_numpy()
    uniq = np.unique(clusters)
    idx_by = {c: np.flatnonzero(clusters == c) for c in uniq}
    vals = []
    for _ in range(2000):
        take = rng.choice(uniq, size=len(uniq), replace=True)
        d = b.iloc[np.concatenate([idx_by[c] for c in take])]
        vals.append(d.loc[d["group"] == "dirty_A", "collapse"].mean()
                    - d.loc[d["group"] == "unseen", "collapse"].mean())
    lo, hi = float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))
    art["dirtyA_minus_unseen_collapse"] = {"obs": float(obs), "ci95": [lo, hi]}
    print(f"  dirty_A - unseen collapse difference: {obs:+.3%}  "
          f"95% cluster-boot [{lo:+.3%}, {hi:+.3%}]")
    (OUT / "p1.json").write_text(json.dumps(art, indent=2))
    return 0


def cmd_p2(seed: int = 20260829) -> int:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    con = _duck()
    a_snipers = set(pd.read_parquet(WIN_A / "snipers.parquet", columns=["owner"])["owner"])
    b_sn = pd.read_parquet(WIN_B / "snipers.parquet", columns=["owner"])
    b_snipers = set(b_sn["owner"])
    n_traders, n_traders_snipe_b = con.execute(
        f"""SELECT count(*),
                   count(*) FILTER (WHERE owner IN
                     (SELECT owner FROM read_parquet('{WIN_B / "snipers.parquet"}')))
            FROM read_parquet('{OUT / "a_traders.parquet"}')
            WHERE owner NOT IN (SELECT owner FROM read_parquet('{WIN_A / "snipers.parquet"}'))
        """).fetchone()
    k_snipe = len(a_snipers & b_snipers)
    n_snipe = len(a_snipers)
    p_s = k_snipe / n_snipe
    p_t = n_traders_snipe_b / n_traders
    # parametric bootstrap on the two binomials for the ratio CI
    draws_s = rng.binomial(n_snipe, p_s, 2000) / n_snipe
    draws_t = rng.binomial(n_traders, p_t, 2000) / n_traders
    ratio = p_s / p_t
    rlo, rhi = np.quantile(draws_s / draws_t, [0.025, 0.975])
    inc_cov = float(b_sn["owner"].isin(a_snipers).mean())
    print("\n=== P2 sniper persistence lift across the gap ===")
    print(f"  P(snipes in B | sniped in A)                : {p_s:.3%}  "
          f"({k_snipe:,}/{n_snipe:,} wallets)")
    print(f"  P(snipes in B | traded in A, never sniped)  : {p_t:.3%}  "
          f"({n_traders_snipe_b:,}/{n_traders:,} wallets)")
    print(f"  lift: {ratio:.1f}x  [95% boot {rlo:.1f}, {rhi:.1f}]")
    print(f"  share of B sniper INCIDENCES by A-known sniper wallets: {inc_cov:.2%}")
    art = {"p_snipeB_given_snipeA": p_s, "n_a_snipers": n_snipe,
           "p_snipeB_given_tradeA": p_t, "n_a_traders_nonsniper": int(n_traders),
           "lift": ratio, "lift_ci95": [float(rlo), float(rhi)],
           "b_incidence_coverage_by_A_snipers": inc_cov}
    (OUT / "p2.json").write_text(json.dumps(art, indent=2))
    return 0


def _arm_sets(coins, sn, deployers, max_coins):
    """Per-coin ex-deployer sniper sets for the given deployers' coins (windowed)."""
    sub = coins[coins["deployer"].isin(deployers)].copy()
    sub = (sub.sort_values("birth_time").groupby("deployer", group_keys=False)
           .head(max_coins).copy())
    own = dict(zip(sub["mint"], sub["deployer"], strict=True))
    sn_sub = sn[sn["mint"].isin(set(sub["mint"]))]
    sets: dict[str, set[str]] = {m: set() for m in sub["mint"]}
    for m, o in zip(sn_sub["mint"].to_numpy(), sn_sub["owner"].to_numpy(), strict=True):
        if o != own.get(m):
            sets[m].add(o)
    return sub, sets


def _best_match(bset: set, a_sets: list[set]) -> tuple[float, int]:
    best_j, best_o = 0.0, 0
    for s in a_sets:
        u = len(bset | s)
        j = len(bset & s) / u if u else 0.0
        if j > best_j:
            best_j, best_o = j, len(bset & s)
    return best_j, best_o


def cmd_p3(seed: int = 20260829, max_deployers: int = 400, max_coins_a: int = 25,
           n_null: int = 200) -> int:
    import numpy as np
    import pandas as pd
    from operator_crime import _curveball

    rng = np.random.default_rng(seed)
    ac = pd.read_parquet(WIN_A / "panel.parquet", columns=["mint", "deployer", "birth_time"])
    bc = pd.read_parquet(WIN_B / "panel.parquet", columns=["mint", "deployer", "birth_time"])
    asn = pd.read_parquet(WIN_A / "snipers.parquet", columns=["mint", "owner"])
    bsn = pd.read_parquet(WIN_B / "snipers.parquet", columns=["mint", "owner"])
    a_dep = ac.dropna(subset=["deployer"]).groupby("deployer").size()
    b_dep = set(bc.dropna(subset=["deployer"])["deployer"])
    qual = a_dep[(a_dep >= 2) & a_dep.index.isin(b_dep)]
    top = qual.sort_values(ascending=False).head(max_deployers)
    print("\n=== P3 cross-gap crew fingerprint ===")
    print(f"  deployers with >=2 A coins AND >=1 B coin: {len(qual):,} "
          f"(arm: busiest {len(top):,})")
    a_sub, a_sets = _arm_sets(ac.dropna(subset=["deployer"]), asn, set(top.index), max_coins_a)
    b_sub, b_sets = _arm_sets(bc.dropna(subset=["deployer"]), bsn, set(top.index), 10**9)
    a_by_dep: dict[str, list[set]] = {}
    for m, d in zip(a_sub["mint"], a_sub["deployer"], strict=True):
        a_by_dep.setdefault(d, []).append(a_sets[m])
    deps = sorted(a_by_dep)
    treat, ctrl = [], []
    b_rows = list(zip(b_sub["mint"], b_sub["deployer"], strict=True))
    for m, d in b_rows:
        if d not in a_by_dep:
            continue
        treat.append(_best_match(b_sets[m], a_by_dep[d]))
        alt = deps[int(rng.integers(0, len(deps)))]
        while alt == d and len(deps) > 1:
            alt = deps[int(rng.integers(0, len(deps)))]
        ctrl.append(_best_match(b_sets[m], a_by_dep[alt]))
    tj = np.array([t[0] for t in treat])
    cj = np.array([c[0] for c in ctrl])
    t_match = np.mean([(j >= 0.10 and o >= 2) for j, o in treat])
    c_match = np.mean([(j >= 0.10 and o >= 2) for j, o in ctrl])
    print(f"  B coins scored: {len(tj):,}")
    print(f"  mean best-match Jaccard: treatment {tj.mean():.4f}  control {cj.mean():.4f}  "
          f"ratio {tj.mean() / cj.mean() if cj.mean() else float('inf'):.1f}x")
    print(f"  live-threshold match rate (J>=0.10 & overlap>=2): treatment {t_match:.2%}  "
          f"control {c_match:.2%}")
    # curveball null on the B side (preserves set sizes and wallet degrees within the arm)
    wid: dict[str, int] = {}
    b_mints = [m for m, d in b_rows if d in a_by_dep]
    b_int = [set(wid.setdefault(w, len(wid)) for w in b_sets[m]) for m in b_mints]
    a_int_by_dep = {d: [set(wid.setdefault(w, len(wid)) for w in s) for s in ss]
                    for d, ss in a_by_dep.items()}
    dep_of = {m: d for m, d in b_rows}
    null_means = []
    for _ in range(n_null):
        shuf = _curveball(b_int, 5 * max(len(b_int), 1), rng)
        vals = []
        for i, m in enumerate(b_mints):
            best = 0.0
            for s in a_int_by_dep[dep_of[m]]:
                u = len(shuf[i] | s)
                j = len(shuf[i] & s) / u if u else 0.0
                best = max(best, j)
            vals.append(best)
        null_means.append(float(np.mean(vals)))
    null_means = np.array(null_means)
    p = float((null_means >= tj.mean()).mean())
    print(f"  curveball null (n={n_null}): mean {null_means.mean():.4f}  p={p:.4f}  "
          f"effect {tj.mean() / null_means.mean() if null_means.mean() else float('inf'):.1f}x")
    art = {"n_qualifying_deployers": len(qual), "n_b_coins": len(tj),
           "treat_mean_bestJ": float(tj.mean()), "ctrl_mean_bestJ": float(cj.mean()),
           "ratio_vs_ctrl": float(tj.mean() / cj.mean()) if cj.mean() else None,
           "treat_live_match_rate": float(t_match), "ctrl_live_match_rate": float(c_match),
           "curveball_mean": float(null_means.mean()), "curveball_p": p}
    (OUT / "p3.json").write_text(json.dumps(art, indent=2))
    return 0


def cmd_p4(seed: int = 20260829, max_deployers: int = 400, max_coins: int = 25) -> int:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    ac = pd.read_parquet(WIN_A / "panel.parquet", columns=["mint", "deployer", "birth_time"])
    asn = pd.read_parquet(WIN_A / "snipers.parquet", columns=["mint", "owner"])
    dep = ac.dropna(subset=["deployer"]).groupby("deployer").size()
    top = dep[dep >= 2].sort_values(ascending=False).head(max_deployers)
    sub, sets = _arm_sets(ac.dropna(subset=["deployer"]), asn, set(top.index), max_coins)
    bins = [(0, 86400, "0-1d"), (86400, 3 * 86400, "1-3d"),
            (3 * 86400, 6 * 86400, "3-6d"), (6 * 86400, 9 * 86400, "6-9d")]
    pairs_by_bin: dict[str, list[tuple[str, float]]] = {b[2]: [] for b in bins}
    for d, g in sub.groupby("deployer"):
        ms = list(zip(g["mint"], g["birth_time"], strict=True))
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                gap = abs(int(ms[i][1]) - int(ms[j][1]))
                for lo, hi, name in bins:
                    if lo <= gap < hi:
                        a, b = sets[ms[i][0]], sets[ms[j][0]]
                        u = len(a | b)
                        pairs_by_bin[name].append((d, len(a & b) / u if u else 0.0))
                        break
    print("\n=== P4 fingerprint decay within window A (same-deployer pair Jaccard) ===")
    art = {}
    for _, _, name in bins:
        rows = pairs_by_bin[name]
        if not rows:
            art[name] = None
            continue
        df = pd.DataFrame(rows, columns=["deployer", "j"])
        obs = float(df["j"].mean())
        uniq = df["deployer"].unique()
        gb = {d: g["j"].to_numpy() for d, g in df.groupby("deployer")}
        vals = []
        for _ in range(1000):
            take = rng.choice(uniq, size=len(uniq), replace=True)
            vals.append(float(np.concatenate([gb[d] for d in take]).mean()))
        lo, hi = np.quantile(vals, [0.025, 0.975])
        art[name] = {"n_pairs": len(df), "mean_j": obs, "ci95": [float(lo), float(hi)]}
        print(f"  {name:<5} n={len(df):>7,}  mean Jaccard {obs:.4f}  "
              f"[95% cluster-boot {lo:.4f}, {hi:.4f}]")
    (OUT / "p4.json").write_text(json.dumps(art, indent=2))
    return 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stages = {"traders": cmd_traders, "p1": cmd_p1, "p2": cmd_p2, "p3": cmd_p3,
              "p4": cmd_p4}
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
