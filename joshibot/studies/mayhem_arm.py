"""The mayhem arm: can the birth-time screen score the nonstandard-curve stratum?

Registered in studies/REGISTRATION_mayhem_arm.md BEFORE any estimand here was computed.
Run:  uv run --group research python studies/mayhem_arm.py all
Stages: census roles constants build screen graph   (each cached; `all` runs in order)

Data: studies/data/operator_crime_fresh/{birth.parquet,ledger/day=*.parquet} (2026-08-26..28),
studies/data/operator_crime/{panel.parquet,snipers.parquet} (2026-08-05..14, causal history),
state/dregg_screen/firehose/new_token/*.jsonl (vendor create frames, constants check).

THE TRAP THIS FILE EXISTS TO AVOID: birth.parquet's curve_owner/deployer are rank-1/rank-2
positive legs of the first transaction. A mayhem create mints 2e15 and (hypothesis H1) puts
~1e15 in a non-curve reserve account, so for any dev_buy > 0 the rank-1 leg is the RESERVE,
not the curve — role assignment must be re-derived (stage `roles`) before anything downstream.
Ground truth for the curve is the derived PDA seeds ["bonding-curve", mint] under the pump
program — deterministic, no RPC. The registered touch-rule is validated against it.
"""

from __future__ import annotations

import glob as globmod
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRESH = REPO_ROOT / "studies" / "data" / "operator_crime_fresh"
WIN_A = REPO_ROOT / "studies" / "data" / "operator_crime"
OUT = REPO_ROOT / "studies" / "data" / "mayhem_arm"
FIREHOSE_NT = REPO_ROOT / "state" / "dregg_screen" / "firehose" / "new_token"

MAYHEM_SUPPLY = 2_000_000_000_000_000
STD_SUPPLY = 1_000_000_000_000_000
CURVE_K = 32_190_000_000_000_000_000_000_000
TOKEN_OFFSET = 73_000_000_000_000
GRAD_EPS = 1_000_000_000
DUMP_FRAC = 0.80
RIP_PEAK_SOL = 100.0
RIP_DRAWDOWN = 0.90
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

LEDGER_GLOB = str(FRESH / "ledger" / "day=*.parquet")
BIRTH = FRESH / "birth.parquet"


def _duck(threads: int = 6, memory: str = "12GB"):
    import duckdb

    con = duckdb.connect()
    con.execute(f"SET threads={threads}")
    con.execute(f"SET memory_limit='{memory}'")
    con.execute("SET preserve_insertion_order=false")
    tmp = OUT / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{tmp}'")
    return con


def _copy(con, sql: str, out: Path, label: str) -> int:
    t0 = time.time()
    tmp = out.parent / f".tmp-{out.name}"
    con.execute(f"COPY ({sql}) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"  {label}: {n:,} rows in {time.time() - t0:.0f}s -> {out.name}", flush=True)
    return n


def _wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, center - half), min(1.0, center + half))


# --------------------------------------------------------------------------------------
# census — M1
# --------------------------------------------------------------------------------------

def cmd_census() -> int:
    con = _duck()
    rows = con.execute(
        f"""
        SELECT strftime(to_timestamp(birth_time), '%Y-%m-%d') AS day,
               CASE WHEN minted_raw = {STD_SUPPLY} AND decimals = 6 THEN 'standard_1e15'
                    WHEN minted_raw = {MAYHEM_SUPPLY} AND decimals = 6 THEN 'mayhem_2e15'
                    WHEN decimals <> 6 THEN 'other_decimals'
                    ELSE 'other_supply' END AS stratum,
               count(*) AS n
        FROM read_parquet('{BIRTH}')
        GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).fetchall()
    residual = con.execute(
        f"""
        SELECT minted_raw, decimals, count(*) AS n
        FROM read_parquet('{BIRTH}')
        WHERE NOT (minted_raw IN ({STD_SUPPLY}, {MAYHEM_SUPPLY}) AND decimals = 6)
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 15
        """
    ).fetchall()
    print("\n=== M1 census: births by day and stratum ===")
    tot: dict[str, int] = {}
    per_day: dict[str, dict[str, int]] = {}
    for day, stratum, n in rows:
        tot[stratum] = tot.get(stratum, 0) + n
        per_day.setdefault(day, {})[stratum] = n
    for day in sorted(per_day):
        d = per_day[day]
        std, may = d.get("standard_1e15", 0), d.get("mayhem_2e15", 0)
        print(f"  {day}: standard {std:>7,}  mayhem {may:>7,}  "
              f"share {may / max(std + may, 1):6.2%}  "
              f"(other {sum(v for k, v in d.items() if k.startswith('other')):,})")
    std, may = tot.get("standard_1e15", 0), tot.get("mayhem_2e15", 0)
    print(f"  pooled : standard {std:,}  mayhem {may:,}  share {may / max(std + may, 1):.2%}")
    print("  residual first-tx nets (top 15, counted never rescaled):")
    for mr, dec, n in residual:
        print(f"    minted_raw={mr}  decimals={dec}  n={n:,}")
    art = {"per_day": per_day, "pooled": tot,
           "mayhem_share_of_births": may / max(std + may, 1),
           "residual_top": [{"minted_raw": int(r[0]), "decimals": int(r[1]), "n": int(r[2])}
                            for r in residual]}
    (OUT / "census.json").write_text(json.dumps(art, indent=2))
    return 0


# --------------------------------------------------------------------------------------
# roles — M2
# --------------------------------------------------------------------------------------

MAYHEM_SEL = f"minted_raw = {MAYHEM_SUPPLY} AND decimals = 6"

LEGS_SQL = f"""
WITH mb AS (
  SELECT mint, birth_slot, birth_tx, birth_time
  FROM read_parquet('{BIRTH}') WHERE {MAYHEM_SEL}
),
legs AS (
  SELECT l.mint, l.owner, l.delta_raw, mb.birth_slot, mb.birth_tx, mb.birth_time
  FROM read_parquet('{LEDGER_GLOB}') l
  JOIN mb ON l.mint = mb.mint AND l.block_slot = mb.birth_slot AND l.tx_index = mb.birth_tx
  WHERE l.delta_raw > 0
),
touch AS (
  SELECT l.mint, l.owner, count(*) AS n_touch
  FROM read_parquet('{LEDGER_GLOB}') l
  SEMI JOIN mb ON l.mint = mb.mint
  GROUP BY l.mint, l.owner
)
SELECT g.mint, g.owner, g.delta_raw, g.birth_slot, g.birth_tx, g.birth_time,
       coalesce(t.n_touch, 0) AS n_touch
FROM legs g LEFT JOIN touch t ON g.mint = t.mint AND g.owner = t.owner
"""


def _derive_pdas(mints: list[str]) -> dict[str, str]:
    from solders.pubkey import Pubkey

    prog = Pubkey.from_string(PUMP_PROGRAM)
    out = {}
    for m in mints:
        try:
            pda, _ = Pubkey.find_program_address(
                [b"bonding-curve", bytes(Pubkey.from_string(m))], prog)
            out[m] = str(pda)
        except Exception:
            out[m] = ""
    return out


def cmd_roles() -> int:
    import pandas as pd

    con = _duck()
    legs_path = OUT / "mayhem_legs.parquet"
    if not legs_path.exists():
        _copy(con, LEGS_SQL, legs_path, "birth legs + touches")
    legs = pd.read_parquet(legs_path)
    mints = sorted(legs["mint"].unique())
    print(f"\n=== M2 roles: {len(mints):,} mayhem mints, {len(legs):,} positive birth legs ===")

    pda_path = OUT / "mayhem_pda.parquet"
    if not pda_path.exists():
        t0 = time.time()
        pdas = _derive_pdas(mints)
        pd.DataFrame({"mint": list(pdas), "curve_pda": list(pdas.values())}).to_parquet(pda_path)
        print(f"  derived {len(pdas):,} bonding-curve PDAs in {time.time() - t0:.0f}s")
    pda = pd.read_parquet(pda_path).set_index("mint")["curve_pda"]

    rows = []
    stats = {"n": 0, "pda_in_legs": 0, "touch_agrees_pda": 0, "reserve_1e15": 0,
             "reserve_static": 0, "seed_eq_1e15_minus_dev": 0, "no_dev_leg": 0}
    for mint, g in legs.groupby("mint", sort=False):
        stats["n"] += 1
        g = g.sort_values("delta_raw", ascending=False)
        p = pda.get(mint, "")
        owners = g["owner"].tolist()
        curve_owner = None
        if p in owners:
            stats["pda_in_legs"] += 1
            curve_owner = p
        # registered touch rule, evaluated regardless for the validation count
        touch_pick = g.loc[g["n_touch"].idxmax(), "owner"]
        if curve_owner is None:
            curve_owner = touch_pick
        if touch_pick == curve_owner:
            stats["touch_agrees_pda"] += 1
        rest = g[g["owner"] != curve_owner]
        res = rest[rest["delta_raw"] == STD_SUPPLY]
        reserve_owner, reserve_raw, reserve_touch = None, 0, 0
        if len(res):
            stats["reserve_1e15"] += 1
            r0 = res.iloc[0]
            reserve_owner, reserve_raw = r0["owner"], int(r0["delta_raw"])
            reserve_touch = int(r0["n_touch"])
            if reserve_touch <= 1:
                stats["reserve_static"] += 1
            rest = rest[rest["owner"] != reserve_owner]
        dev_owner, dev_buy_raw = None, 0
        if len(rest):
            d0 = rest.sort_values("delta_raw", ascending=False).iloc[0]
            dev_owner, dev_buy_raw = d0["owner"], int(d0["delta_raw"])
        else:
            stats["no_dev_leg"] += 1
        curve_seed = int(g.loc[g["owner"] == curve_owner, "delta_raw"].iloc[0]) \
            if (g["owner"] == curve_owner).any() else 0
        if curve_seed == STD_SUPPLY - dev_buy_raw:
            stats["seed_eq_1e15_minus_dev"] += 1
        rows.append({
            "mint": mint, "birth_slot": int(g["birth_slot"].iloc[0]),
            "birth_tx": int(g["birth_tx"].iloc[0]), "birth_time": int(g["birth_time"].iloc[0]),
            "curve_owner": curve_owner, "curve_seed_raw": curve_seed,
            "reserve_owner": reserve_owner, "reserve_raw": reserve_raw,
            "reserve_touches": reserve_touch,
            "deployer": dev_owner, "dev_buy_raw": dev_buy_raw,
            "n_birth_legs": len(g), "pda_matched": p in owners,
        })
    roles = pd.DataFrame(rows)
    roles.to_parquet(OUT / "mayhem_birth.parquet")
    n = stats["n"]
    print(f"  PDA found among birth legs      : {stats['pda_in_legs']:,}/{n:,} "
          f"({stats['pda_in_legs'] / n:.2%})")
    print(f"  touch-rule agrees with PDA      : {stats['touch_agrees_pda']:,}/{n:,} "
          f"({stats['touch_agrees_pda'] / n:.2%})  [registered validation]")
    print(f"  exact-1e15 reserve leg present  : {stats['reserve_1e15']:,}/{n:,} "
          f"({stats['reserve_1e15'] / n:.2%})")
    print(f"  reserve static in-window        : {stats['reserve_static']:,}"
          f"/{max(stats['reserve_1e15'], 1):,} "
          f"({stats['reserve_static'] / max(stats['reserve_1e15'], 1):.2%} of reserves)")
    print(f"  curve_seed == 1e15 - dev_buy    : {stats['seed_eq_1e15_minus_dev']:,}/{n:,} "
          f"({stats['seed_eq_1e15_minus_dev'] / n:.2%})  [H1 arithmetic]")
    print(f"  no dev leg (zero dev buy)       : {stats['no_dev_leg']:,}/{n:,}")
    print("  n_birth_legs histogram:",
          dict(roles["n_birth_legs"].value_counts().sort_index().head(8)))
    (OUT / "roles.json").write_text(json.dumps(stats, indent=2))
    return 0


# --------------------------------------------------------------------------------------
# constants — M3
# --------------------------------------------------------------------------------------

def cmd_constants() -> int:
    import pandas as pd

    print("\n=== M3 constants ===")
    art: dict = {}
    # (b) vendor create frames with the mayhem flag (only days that carry the flag)
    n_ok = n_bad = 0
    sol_ok = sol_bad = 0
    examples = []
    for f in sorted(globmod.glob(str(FIREHOSE_NT / "*.jsonl"))):
        lines = Path(f).read_text().splitlines()
        for line in lines:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = r.get("payload") or {}
            if not p.get("is_mayhem_mode"):
                continue
            vt, ib = p.get("vTokensInBondingCurve"), p.get("initialBuy")
            vs, sa = p.get("vSolInBondingCurve"), p.get("solAmount")
            if vt is None or ib is None:
                continue
            if abs((vt + ib) - 1_073_000_000.0) < 0.01:
                n_ok += 1
            else:
                n_bad += 1
                if len(examples) < 3:
                    examples.append({"mint": p.get("mint"), "vt": vt, "ib": ib})
            if vs is not None and sa is not None:
                if abs((vs - sa) - 30.0) < 1e-6:
                    sol_ok += 1
                else:
                    sol_bad += 1
    print(f"  vendor mayhem creates: vTok+initialBuy == 1.073e9 : {n_ok}/{n_ok + n_bad}")
    print(f"  vendor mayhem creates: vSol-solAmount == 30.0     : {sol_ok}/{sol_ok + sol_bad}")
    art["vendor_frames"] = {"vtok_sum_ok": n_ok, "vtok_sum_bad": n_bad,
                           "vsol_ok": sol_ok, "vsol_bad": sol_bad, "bad_examples": examples}
    # boards tape does not cover 2026-08-26..28 (tape ends 08-23) — registered M3(a) is
    # unavailable and says so; the internal H1 arithmetic (roles stage) + the graduated-coin
    # calibration check (build stage prints it) stand in.
    print("  boards tape ends 2026-08-23: M3(a) snapshot join unavailable for this window")
    art["boards_join"] = "unavailable: boards tape ends 2026-08-23"
    roles = pd.read_parquet(OUT / "mayhem_birth.parquet")
    frac = float((roles["curve_seed_raw"] == STD_SUPPLY - roles["dev_buy_raw"]).mean())
    art["seed_arithmetic_frac"] = frac
    (OUT / "constants.json").write_text(json.dumps(art, indent=2))
    return 0


# --------------------------------------------------------------------------------------
# build — curve path, insiders, snipers, panel (M4 + history features)
# --------------------------------------------------------------------------------------

CURVE_SQL = """
WITH born AS (
  SELECT mint, curve_owner FROM read_parquet('{roles}')
),
crows AS (
  SELECT l.mint, l.block_slot, l.tx_index, l.block_time, l.delta_raw
  FROM read_parquet('{ledger}') l JOIN born b
    ON l.mint = b.mint AND l.owner = b.curve_owner
),
path AS (
  SELECT mint, block_slot, tx_index, block_time,
         sum(delta_raw) OVER (PARTITION BY mint ORDER BY block_slot, tx_index
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bal
  FROM crows
),
path2 AS (
  SELECT *, max(bal) OVER (PARTITION BY mint ORDER BY block_slot DESC, tx_index DESC
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS sufmax
  FROM path
)
SELECT mint,
       count(*) AS curve_touches,
       min(bal) AS min_bal, max(bal) AS max_bal,
       min(bal) FILTER (WHERE bal > {grad_eps}) AS min_bal_live,
       arg_min(block_time, bal) FILTER (WHERE bal > {grad_eps}) AS t_peak,
       arg_min(sufmax, bal) FILTER (WHERE bal > {grad_eps}) AS post_peak_max_bal,
       last(bal ORDER BY block_slot, tx_index) AS final_bal,
       last(bal ORDER BY block_slot, tx_index)
         FILTER (WHERE bal > {grad_eps}) AS final_bal_live,
       last(block_time ORDER BY block_slot, tx_index) AS t_last
FROM path2 GROUP BY mint
"""

INSIDER_SQL = """
WITH born AS (
  SELECT mint, curve_owner, reserve_owner, birth_slot FROM read_parquet('{roles}')
),
snipers AS (
  SELECT l.mint, l.owner
  FROM read_parquet('{ledger}') l JOIN born b
    ON l.mint = b.mint AND l.block_slot = b.birth_slot
  WHERE l.owner <> b.curve_owner
    AND (b.reserve_owner IS NULL OR l.owner <> b.reserve_owner)
  GROUP BY l.mint, l.owner
  HAVING sum(l.delta_raw) > 0
),
ipath AS (
  SELECT l.mint, l.block_slot, l.tx_index,
         min(l.block_time) AS block_time,
         sum(sum(l.delta_raw)) OVER (PARTITION BY l.mint
                                     ORDER BY l.block_slot, l.tx_index
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bal
  FROM read_parquet('{ledger}') l SEMI JOIN snipers s
    ON l.mint = s.mint AND l.owner = s.owner
  GROUP BY l.mint, l.block_slot, l.tx_index
),
pk AS (
  SELECT mint, max(bal) AS ins_peak,
         arg_max(block_slot * 1000000 + tx_index, bal) AS peak_key,
         arg_max(block_time, bal) AS t_ins_peak,
         last(bal ORDER BY block_slot, tx_index) AS ins_final
  FROM ipath GROUP BY mint
),
dump AS (
  SELECT i.mint,
         min(i.block_time) FILTER (
           WHERE i.bal <= (1 - {dump_frac}) * k.ins_peak
             AND i.block_slot * 1000000 + i.tx_index > k.peak_key) AS t_dump
  FROM ipath i JOIN pk k USING (mint)
  GROUP BY i.mint
),
nsnipe AS (SELECT mint, count(*) AS n_snipers FROM snipers GROUP BY mint)
SELECT b.mint, coalesce(n.n_snipers, 0) AS n_snipers, k.ins_peak, k.t_ins_peak, k.ins_final,
       d.t_dump
FROM born b
LEFT JOIN nsnipe n USING (mint)
LEFT JOIN pk k USING (mint)
LEFT JOIN dump d USING (mint)
"""

SNIPERS_SQL = """
WITH born AS (
  SELECT mint, curve_owner, reserve_owner, birth_slot, birth_time
  FROM read_parquet('{roles}')
)
SELECT l.mint, l.owner, b.birth_time, sum(l.delta_raw) AS bought_raw
FROM read_parquet('{ledger}') l JOIN born b
  ON l.mint = b.mint AND l.block_slot = b.birth_slot
WHERE l.owner <> b.curve_owner
  AND (b.reserve_owner IS NULL OR l.owner <> b.reserve_owner)
GROUP BY l.mint, l.owner, b.birth_time
HAVING sum(l.delta_raw) > 0
"""

COINS_SQL = f"""
WITH b AS (SELECT * FROM read_parquet('{{roles}}')),
c AS (SELECT * FROM read_parquet('{{curve}}')),
i AS (SELECT * FROM read_parquet('{{insiders}}'))
SELECT
  b.mint, b.deployer, b.curve_owner, b.reserve_owner, b.reserve_touches,
  b.birth_slot, b.birth_time, b.dev_buy_raw, b.n_birth_legs, b.curve_seed_raw,
  i.n_snipers, i.ins_peak, i.t_ins_peak, i.ins_final, i.t_dump,
  c.curve_touches, c.min_bal, c.min_bal_live, c.max_bal, c.final_bal, c.final_bal_live,
  c.post_peak_max_bal, c.t_peak, c.t_last,
  (c.min_bal_live + {TOKEN_OFFSET}) AS v_tok_peak,
  (c.post_peak_max_bal + {TOKEN_OFFSET}) AS v_tok_trough,
  {CURVE_K}::DOUBLE / (c.min_bal_live + {TOKEN_OFFSET})::DOUBLE
      / (c.min_bal_live + {TOKEN_OFFSET})::DOUBLE * 1e15 / 1e9 AS peak_mcap_circ_sol,
  {CURVE_K}::DOUBLE / (c.min_bal_live + {TOKEN_OFFSET})::DOUBLE
      / (c.min_bal_live + {TOKEN_OFFSET})::DOUBLE * 2e15 / 1e9 AS peak_mcap_total_sol,
  1.0 - pow((c.min_bal_live + {TOKEN_OFFSET})::DOUBLE
            / (c.post_peak_max_bal + {TOKEN_OFFSET})::DOUBLE, 2) AS drawdown_from_peak,
  (c.min_bal <= {GRAD_EPS}) AS graduated,
  i.ins_peak::DOUBLE / {MAYHEM_SUPPLY} AS ins_peak_share,
  b.dev_buy_raw::DOUBLE / {MAYHEM_SUPPLY} AS dev_buy_share,
  c.t_last - b.birth_time AS lifetime_s,
  c.t_peak - b.birth_time AS time_to_peak_s
FROM b JOIN c USING (mint) JOIN i USING (mint)
"""

# Causal deployer history over the COMBINED event stream: window-A standard panel + fresh
# standard panel + this build's mayhem coins, every event at its own clock, strictly before
# the mayhem coin's birth. Same aggregation as operator_crime's PANEL_SQL `ev`/`agg`.
HISTORY_SQL = f"""
WITH m AS (
  SELECT mint, deployer, birth_time,
         (t_dump IS NOT NULL AND ins_peak_share >= 0.05
          AND peak_mcap_circ_sol >= {RIP_PEAK_SOL}
          AND coalesce(drawdown_from_peak, 0) >= {RIP_DRAWDOWN}) AS is_rip,
         t_dump, CASE WHEN graduated THEN t_last END AS t_grad
  FROM read_parquet('{{mcoins}}')
),
std AS (
  SELECT deployer, birth_time, is_rip, t_dump, t_grad
  FROM read_parquet('{{a_panel}}') WHERE deployer IS NOT NULL
  UNION ALL
  SELECT deployer, birth_time, is_rip, t_dump, t_grad
  FROM read_parquet('{{f_panel}}') WHERE deployer IS NOT NULL
  UNION ALL
  SELECT deployer, birth_time, is_rip, t_dump, t_grad FROM m WHERE deployer IS NOT NULL
),
ev AS (
  SELECT deployer, birth_time AS t, 1 AS e_launch, 0 AS e_rip, 0 AS e_dump, 0 AS e_grad
  FROM std
  UNION ALL
  SELECT deployer, t_dump, 0, CASE WHEN is_rip THEN 1 ELSE 0 END, 1, 0
  FROM std WHERE t_dump IS NOT NULL
  UNION ALL
  SELECT deployer, t_grad, 0, 0, 0, 1 FROM std WHERE t_grad IS NOT NULL
)
SELECT m.mint,
       coalesce(sum(ev.e_launch), 0) AS prior_launches,
       coalesce(sum(ev.e_rip), 0)    AS prior_rips,
       coalesce(sum(ev.e_dump), 0)   AS prior_dumps,
       coalesce(sum(ev.e_grad), 0)   AS prior_grads
FROM m LEFT JOIN ev ON ev.deployer = m.deployer AND ev.t < m.birth_time
GROUP BY m.mint
"""

SNIPER_PRIOR_SQL = """
WITH comb AS (
  SELECT mint, owner, birth_time FROM read_parquet('{a_snipers}')
  UNION ALL
  SELECT mint, owner, birth_time FROM read_parquet('{f_snipers}')
  UNION ALL
  SELECT mint, owner, birth_time FROM read_parquet('{m_snipers}')
),
r AS (
  SELECT mint, owner, row_number() OVER (PARTITION BY owner ORDER BY birth_time, mint) AS nth
  FROM comb
)
SELECT r.mint, max(r.nth) - 1 AS sniper_prior_max,
       avg(CASE WHEN r.nth > 1 THEN 1.0 ELSE 0.0 END) AS sniper_recidivism
FROM r SEMI JOIN read_parquet('{m_snipers}') s ON r.mint = s.mint
GROUP BY r.mint
"""


def cmd_build(force: bool = False) -> int:
    con = _duck()
    roles = OUT / "mayhem_birth.parquet"
    curve = OUT / "mayhem_curve.parquet"
    if force or not curve.exists():
        _copy(con, CURVE_SQL.format(roles=roles, ledger=LEDGER_GLOB, grad_eps=GRAD_EPS),
              curve, "mayhem curve paths")
    ins = OUT / "mayhem_insiders.parquet"
    if force or not ins.exists():
        _copy(con, INSIDER_SQL.format(roles=roles, ledger=LEDGER_GLOB, dump_frac=DUMP_FRAC),
              ins, "mayhem insiders")
    sn = OUT / "mayhem_snipers.parquet"
    if force or not sn.exists():
        _copy(con, SNIPERS_SQL.format(roles=roles, ledger=LEDGER_GLOB), sn, "mayhem snipers")
    coins = OUT / "mayhem_coins.parquet"
    if force or not coins.exists():
        _copy(con, COINS_SQL.format(roles=roles, curve=curve, insiders=ins),
              coins, "mayhem coins")
    hist = OUT / "mayhem_history.parquet"
    if force or not hist.exists():
        _copy(con, HISTORY_SQL.format(mcoins=coins, a_panel=WIN_A / "panel.parquet",
                                      f_panel=FRESH / "panel.parquet"),
              hist, "deployer history (combined, causal)")
    sp = OUT / "mayhem_sniper_prior.parquet"
    if force or not sp.exists():
        _copy(con, SNIPER_PRIOR_SQL.format(a_snipers=WIN_A / "snipers.parquet",
                                           f_snipers=FRESH / "snipers.parquet",
                                           m_snipers=sn),
              sp, "sniper priors (combined, causal)")
    # calibration print: graduated mayhem coins' peak mcap (the 411-SOL check, circ basis)
    row = con.execute(
        f"""SELECT count(*), median(peak_mcap_circ_sol), median(min_bal_live)
            FROM read_parquet('{coins}') WHERE graduated"""
    ).fetchone()
    print(f"  graduated mayhem coins: {row[0]:,}; median peak mcap (circ basis) "
          f"{row[1] if row[1] else float('nan'):.1f} SOL (standard-curve check is ~411); "
          f"median last live bal {row[2] if row[2] else float('nan'):,.0f} raw "
          f"(standard holdback is 2.069e14)")
    return 0


# --------------------------------------------------------------------------------------
# screen — M4 outcomes + M5 gates + M6 verdict
# --------------------------------------------------------------------------------------

def _risk_ratio_boot(df, mask_a, mask_b, ycol, cluster, rng, n_boot=2000):
    """Risk ratio P(y|a)/P(y|b) with deployer-clustered bootstrap CI."""
    import numpy as np

    def rr(d):
        pa = d.loc[mask_a.reindex(d.index, fill_value=False), ycol].mean()
        pb = d.loc[mask_b.reindex(d.index, fill_value=False), ycol].mean()
        return pa / pb if pb > 0 else float("nan")

    obs = rr(df)
    clusters = df[cluster].fillna("__none__").to_numpy()
    uniq = np.unique(clusters)
    idx_by = {c: np.flatnonzero(clusters == c) for c in uniq}
    vals = []
    for _ in range(n_boot):
        take = rng.choice(uniq, size=len(uniq), replace=True)
        rows = np.concatenate([idx_by[c] for c in take])
        d = df.iloc[rows]
        vals.append(rr(d))
    vals = np.array([v for v in vals if np.isfinite(v)])
    lo, hi = (np.quantile(vals, 0.025), np.quantile(vals, 0.975)) if len(vals) else (float("nan"),) * 2
    return obs, float(lo), float(hi)


def cmd_screen(seed: int = 20260829) -> int:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    df = pd.read_parquet(OUT / "mayhem_coins.parquet")
    hist = pd.read_parquet(OUT / "mayhem_history.parquet")
    sp = pd.read_parquet(OUT / "mayhem_sniper_prior.parquet")
    df = df.merge(hist, on="mint", how="left").merge(sp, on="mint", how="left")
    for c in ("prior_launches", "prior_rips", "prior_dumps", "prior_grads",
              "sniper_prior_max", "sniper_recidivism"):
        df[c] = df[c].fillna(0)
    df["is_rip"] = ((df["t_dump"].notna()) & (df["ins_peak_share"] >= 0.05)
                    & (df["peak_mcap_circ_sol"] >= RIP_PEAK_SOL)
                    & (df["drawdown_from_peak"].fillna(0) >= RIP_DRAWDOWN))
    df["collapse"] = ((df["peak_mcap_circ_sol"] >= RIP_PEAK_SOL)
                      & (df["drawdown_from_peak"].fillna(0) >= RIP_DRAWDOWN))
    df["day"] = pd.to_datetime(df["birth_time"], unit="s").dt.strftime("%Y-%m-%d")
    # population mirror of the standard screen: identified deployer (dev leg present)
    pop = df[df["deployer"].notna()].copy()
    art: dict = {"n_mayhem": len(df), "n_with_deployer": len(pop)}
    print("\n=== M4 outcomes (mayhem stratum, corrected roles/denominators) ===")
    for name, d in (("pooled", df), ("day 2026-08-26 only", df[df["day"] == "2026-08-26"])):
        o = {
            "n": len(d),
            "graduated": float(d["graduated"].mean()),
            "dump_rate": float(d["t_dump"].notna().mean()),
            "rip_rate": float(d["is_rip"].mean()),
            "collapse_rate": float(d["collapse"].mean()),
            "peak_ge_100_circ": float((d["peak_mcap_circ_sol"] >= 100).mean()),
            "median_lifetime_s": float(d["lifetime_s"].median()),
        }
        art[f"outcomes_{name.split()[0]}"] = o
        print(f"  [{name}] n={o['n']:,} grad {o['graduated']:.2%}  dump {o['dump_rate']:.2%}  "
              f"rip {o['rip_rate']:.3%}  collapse {o['collapse_rate']:.3%}  "
              f"peak>=100SOL(circ) {o['peak_ge_100_circ']:.2%}")

    print(f"\n=== M5 gates within the mayhem stratum (deployer-identified, n={len(pop):,}) ===")
    gates = {
        "no bundle at birth (n_snipers <= 1)": pop["n_snipers"] <= 1,
        "deployer never ripped (prior_rips = 0)": pop["prior_rips"] == 0,
        "deployer never dumped (prior_dumps = 0)": pop["prior_dumps"] == 0,
        "no recidivist sniper (sniper_prior_max = 0)": pop["sniper_prior_max"] == 0,
        "dev buy < 2% of TRUE supply (2e15)": pop["dev_buy_share"] < 0.02,
    }
    art["separations"] = {}
    for oname in ("is_rip", "collapse"):
        y = pop[oname].astype(int)
        base = y.mean()
        print(f"  --- outcome {oname}: base rate {base:.4%} ---")
        for gname, g in gates.items():
            k_bad = int(y[g].sum())
            n_adm = int(g.sum())
            prec = 1 - k_bad / n_adm if n_adm else float("nan")
            print(f"    {gname:<46} passes {n_adm:>7,}  P(clean) {prec:.4%}")
        allg = np.logical_and.reduce([g.to_numpy() for g in gates.values()])
        n_adm, k_bad = int(allg.sum()), int(y[allg].sum())
        prec = 1 - k_bad / n_adm if n_adm else float("nan")
        lo, hi = _wilson(n_adm - k_bad, n_adm)
        art["separations"][oname] = {
            "base_rate": float(base), "admitted": n_adm, "admitted_bad": k_bad,
            "clean_precision": prec, "clean_ci95": [lo, hi],
            "admit_rate": n_adm / len(pop),
        }
        print(f"    ALL GATES (mayhem-CLEAN)                       passes {n_adm:>7,}  "
              f"P(clean) {prec:.4%}  Wilson95 [{lo:.4%}, {hi:.4%}]  "
              f"admit {n_adm / len(pop):.2%}")
        # bundledness separation with clustered CI (registered M5a)
        rr, rlo, rhi = _risk_ratio_boot(pop, pop["n_snipers"] >= 2, pop["n_snipers"] <= 1,
                                        oname, "deployer", rng)
        art["separations"][oname]["bundled_risk_ratio"] = [rr, rlo, rhi]
        print(f"    bundled(>=2)/unbundled(<=1) {oname} risk ratio: {rr:.2f}x  "
              f"[95% cluster-boot {rlo:.2f}, {rhi:.2f}]")
        # dirty-history separation (registered M5c)
        dirty = (pop["prior_rips"] > 0) | (pop["prior_dumps"] > 0)
        rr2, r2lo, r2hi = _risk_ratio_boot(pop, dirty, ~dirty, oname, "deployer", rng)
        art["separations"][oname]["dirty_history_risk_ratio"] = [rr2, r2lo, r2hi]
        print(f"    dirty-history/clean-history {oname} risk ratio: {rr2:.2f}x  "
              f"[95% cluster-boot {r2lo:.2f}, {r2hi:.2f}]")
        # day-1-only variant for the CLEAN operating point (exposure-max)
        d1 = pop[pop["day"] == "2026-08-26"]
        y1 = d1[oname].astype(int)
        allg1 = np.logical_and.reduce([g[pop["day"] == "2026-08-26"].to_numpy()
                                       for g in gates.values()])
        n1, k1 = int(allg1.sum()), int(y1[allg1].sum())
        p1 = 1 - k1 / n1 if n1 else float("nan")
        l1, h1 = _wilson(n1 - k1, n1)
        art["separations"][oname]["day1_only"] = {
            "admitted": n1, "admitted_bad": k1, "clean_precision": p1, "clean_ci95": [l1, h1]}
        print(f"    day-08-26-only CLEAN: admitted {n1:,}, bad {k1}, "
              f"P(clean) {p1:.4%}  Wilson95 [{l1:.4%}, {h1:.4%}]")
    (OUT / "screen.json").write_text(json.dumps(art, indent=2))
    return 0


# --------------------------------------------------------------------------------------
# graph — M5(d): crew reuse within the mayhem stratum
# --------------------------------------------------------------------------------------

def cmd_graph(seed: int = 20260829, max_deployers: int = 400, n_null: int = 200,
              max_coins: int = 25) -> int:
    import numpy as np
    import pandas as pd
    from operator_crime import _curveball, _mean_jaccard

    rng = np.random.default_rng(seed)
    coins = pd.read_parquet(OUT / "mayhem_coins.parquet",
                            columns=["mint", "deployer", "birth_time"])
    sn = pd.read_parquet(OUT / "mayhem_snipers.parquet", columns=["mint", "owner"])
    dep = coins.dropna(subset=["deployer"]).groupby("deployer").size()
    top = dep[dep >= 2].sort_values(ascending=False).head(max_deployers)
    sub = coins[coins["deployer"].isin(top.index)].copy()
    sub = (sub.sort_values("birth_time").groupby("deployer", group_keys=False)
           .head(max_coins).copy())
    own = dict(zip(sub["mint"], sub["deployer"], strict=True))
    sn_sub = sn[sn["mint"].isin(set(sub["mint"]))]
    mints = sorted(set(sn_sub["mint"]))
    midx = {m: i for i, m in enumerate(mints)}
    wid: dict[str, int] = {}
    sets: list[set[int]] = [set() for _ in mints]
    for m, o in zip(sn_sub["mint"].to_numpy(), sn_sub["owner"].to_numpy(), strict=True):
        if o != own.get(m):
            sets[midx[m]].add(wid.setdefault(o, len(wid)))
    sub = sub[sub["mint"].isin(midx)]
    sub["day"] = (sub["birth_time"] // 86400).astype(int)
    print(f"\n=== M5(d) crew reuse within mayhem: {len(sub):,} coins / "
          f"{sub['deployer'].nunique():,} multi-launch deployers / {len(wid):,} wallets ===")
    same, diff = [], []
    for _, g in sub.groupby("deployer"):
        idx = [midx[m] for m in g["mint"]]
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                same.append((idx[a], idx[b]))
    byday: dict[int, list] = {}
    for m, d, dp in zip(sub["mint"], sub["day"], sub["deployer"], strict=True):
        byday.setdefault(int(d), []).append((midx[m], dp))
    tries = 0
    while len(diff) < len(same) and tries < 50 * max(len(same), 1):
        tries += 1
        day = int(rng.choice(list(byday.keys())))
        pool = byday[day]
        if len(pool) < 2:
            continue
        i, j = rng.integers(0, len(pool), 2)
        if i == j or pool[i][1] == pool[j][1]:
            continue
        diff.append((pool[i][0], pool[j][0]))
    obs_same = _mean_jaccard(same, sets)
    obs_diff = _mean_jaccard(diff, sets)
    null = np.array([_mean_jaccard(same, _curveball(sets, 5 * len(sets), rng))
                     for _ in range(n_null)])
    p = float((null >= obs_same).mean())
    print(f"  same-deployer pairs {len(same):,}: mean Jaccard {obs_same:.4f}")
    print(f"  day-matched control {len(diff):,}: mean Jaccard {obs_diff:.4f}   "
          f"ratio {obs_same / obs_diff if obs_diff else float('nan'):.1f}x")
    print(f"  curveball null (n={n_null}): mean {null.mean():.4f}  p={p:.4f}  "
          f"effect {obs_same / null.mean() if null.mean() else float('nan'):.1f}x")
    art = {"n_pairs": len(same), "jaccard_same": obs_same, "jaccard_daymatched": obs_diff,
           "ratio_vs_daymatched": obs_same / obs_diff if obs_diff else None,
           "curveball_mean": float(null.mean()), "curveball_p": p}
    (OUT / "graph.json").write_text(json.dumps(art, indent=2))
    return 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stages = {"census": cmd_census, "roles": cmd_roles, "constants": cmd_constants,
              "build": cmd_build, "screen": cmd_screen, "graph": cmd_graph}
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
