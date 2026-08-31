#!/usr/bin/env python3
"""A STANDING per-wallet behavioral estimator, and the iceberg/piecewise-distribution detector.

THE OPERATOR'S ASK, verbatim
----------------------------
    "did we ever get around to bolting an estimator of wallet behavior onto all the wallets,
     and using that as any kind of anything? for example some bundles might be selling
     piecewise to make the chart look less plungy."

Answer before this module: **no.** The PIECES existed across lanes -- the realization-policy
fingerprint (``unrealized_pnl.py``, a strong per-wallet signature at AUC 0.775 on coin-disjoint
halves), the guild taxonomy and 8-second scheduler (``cluster_map.py``), the rotation cohort and
the exact full-SOL-leg tape (``pvp_vamps.py``) -- but nobody ever ASSEMBLED them into one
standing layer keyed by wallet that a live desk could join against. This module is that
assembly, plus the detector the ask actually names: piecewise / iceberg distribution.

WHAT IT BUILDS
--------------
1. ``state/wallets/estimator.parquet`` -- one row per ACTIVE wallet (>= MIN_LEGS priced legs),
   keyed by the base58 ``owner`` string, carrying a behavior vector:
     * activity + buy/sell asymmetry
     * executable-exit realized PnL and win rate (average-cost, NOT marginal -- the marginal
       mark booked +950 SOL where the executable exit was +35; we count only realized cash on
       the sold fraction and never mark unsold inventory into profit)
     * hold-time distribution
     * the realization-policy summary (TP / stop / break-even-preset / averages-down modes),
       the per-wallet fingerprint that scored AUC 0.775 split-half
     * guild membership -- the cluster-derived label from the ten-day bulk map where present
       (authoritative), and a per-wallet ``guild_solo`` analog applying the same rules to the
       wallet's own behavior where it is not
     * entry-timing signature (median launch latency; on-a-scheduler-rung flag)
     * rotation / mercenary membership

2. ``state/wallets/iceberg.parquet`` -- THE FLAGSHIP. One row per (wallet, coin) distribution
   episode that looks like an entity feeding a large exit out in many small same-direction
   sells while the price stays propped (net sell flow >> the price impact it would predict).
   The discriminator against a lone dumper is exact on the bonding curve: a sell of Q tokens
   moves the curve price by a deterministic amount, so the GAP between the realized price move
   and the move W's own sells would have caused alone measures how much the rest of the market
   absorbed. For POOL-route (graduated) coins -- which is what all four operator coins are --
   there is no reserve level, so the signal is price RESILIENCE plus a TIMING NULL: were W's
   sells placed into others' buy pressure more than a random placement inside W's own
   distribution window would give? That null operationalizes "sells piecewise to make the chart
   look less plungy" directly.

3. ``state/wallets/coin_exit_signal.parquet`` -- the per-COIN rollup a held-coin desk joins:
   is anyone iceberg-distributing this mint, and how hard, right now.

4. ``state/wallets/operator_scan.json`` -- the four operator coins scored on the freshest flow.

VALIDATION, NULLS, AND THE CONFOUND (stated, not buried)
--------------------------------------------------------
* Curve-route absorption is exact algebra, not a fit. The timing null is a within-coin
  permutation (rotation-null discipline, PROGRAM.md 3.13): W's sell minutes are reassigned at
  random among the coin's active minutes INSIDE W's own [first_sell, last_sell] window, so the
  coin's trend and W's own participation window are held fixed and only the *placement* is
  destroyed. Entity-clustered by owner, BY (Benjamini-Yekutieli) FDR across candidates.
* The benign null is a POPULATION, not a straw man: wallets that also distribute a big bag over
  many chunked sells (DCA-out, tax-lot-style unwinding) but whose timing statistic sits at the
  null -- they sold into whatever the market was doing. The iceberg set is the FDR-passing tail.
* THE CONFOUND, unresolved and named: a wallet selling into genuine exogenous demand shows the
  same price resilience as one deliberately propping the chart. The timing null rules out "sold
  blindly" but cannot alone separate intent from luck, nor deliberate self-propping (the buyers
  are the seller's own wallets) from real demand. The partial discriminator is ``self_wash`` --
  the share of the absorbing buy flow that comes from W's own same-slot cluster -- which fires
  only where W is in a cluster. Funding-tree attribution (PROGRAM.md signal #2) would close it
  and is not in local data.

Invocation is always ``uv run --group research python -m studies.wallet_estimator <cmd>``.
Nothing here touches the network, signs anything, or reads the live sentinel's state.

    basis      per-leg average-cost basis + running holdings over the priced tape   (~heavy)
    wallet     the standing per-wallet estimator -> estimator.parquet
    iceberg    candidate detection + curve absorption + timing null -> iceberg.parquet
    operator   score the four operator coins on the freshest flow -> operator_scan.json
    report     assemble the numbers RESULT_wallet_estimator.md reports
    all        basis -> wallet -> iceberg -> operator -> report, in order
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PVP = REPO_ROOT / "studies" / "data" / "pvp_vamps"
TRADES = PVP / "trades.parquet"
MINTS = PVP / "mints.parquet"
OWNERS = PVP / "owners.parquet"
ROTATION = PVP / "rotation.parquet"
COHORT = PVP / "cohort.parquet"
CLUSTERMAP = REPO_ROOT / ".cache" / "clustermap"
CLUSTERS = CLUSTERMAP / "clusters_bulk.parquet"
GUILDS = CLUSTERMAP / "guilds_bulk.parquet"
RESON2 = CLUSTERMAP / "resonance2_bulk.parquet"
OUT = REPO_ROOT / "state" / "wallets"

# The curve constants (operator_crime.py / pvp_vamps.py). Used only for the curve-route
# marginal price path in the iceberg absorption term.
V_TOK_VIRT = 1.073e15
K_CURVE = 3.219e25
LAMPORTS = 1e9

#: A position this small is flat: 1e6 raw = 1 whole token at 6 decimals, 1e-9 of a 1e15 supply.
DUST = 1_000_000.0

#: Activity threshold for inclusion in the standing layer. 3 priced legs drops pure one/two-shot
#: dust while keeping the ~739k wallets that actually act. Coverage is a feature: when a big
#: holder of a watched coin appears, we want them already in the layer.
MIN_LEGS = 3

OPERATOR_COINS = {
    "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
}

SCHEMA_VERSION = 1


def _out() -> Path:
    p = Path(os.environ.get("WE_OUT", str(OUT)))
    p.mkdir(parents=True, exist_ok=True)
    (p / "stage").mkdir(exist_ok=True)
    return p


def _duck(threads: int = 6, memory: str = "16GB"):
    try:
        import duckdb
    except ImportError:  # pragma: no cover
        raise SystemExit("needs duckdb: `uv run --group research`.") from None
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"SET memory_limit='{memory}'")
    con.execute("SET preserve_insertion_order=false")
    tmp = _out() / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con.execute(f"SET temp_directory='{tmp}'")
    con.execute("SET max_temp_directory_size='300GB'")
    return con


def _trades_path() -> str:
    return os.environ.get("WE_TRADES", str(TRADES))


# =====================================================================================
# stage: basis -- per-leg average-cost basis + running holdings, over the priced tape
# =====================================================================================

#: The average-cost recursion as a window query, adapted from unrealized_pnl.BASIS_SQL to the
#: pvp_vamps trades schema (mint_id, owner_id, slot, txi, t, delta_raw, sol, route, cp_bal_after,
#: offset_raw). Every leg is a priced trade here (transfers were never merged into this tape),
#: so px is always defined. An episode opens on a buy from a flat book; the running dilution
#: product is evaluated in log space so it never materialises as a denormal.
BASIS_SQL = """
WITH ev AS (
    SELECT mint_id, owner_id, slot, txi, t, delta_raw, sol, route, cp_bal_after, offset_raw,
           abs(sol) / nullif(abs(delta_raw), 0) AS px
    FROM read_parquet('{trades}')
),
q AS (
    SELECT *,
           sum(delta_raw) OVER w AS qty_after,
           sum(delta_raw) OVER w - delta_raw AS qty_before_raw
    FROM ev
    WINDOW w AS (PARTITION BY mint_id, owner_id ORDER BY slot, txi
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
seg AS (
    SELECT *,
           greatest(qty_before_raw, 0) AS qty_before,
           CASE WHEN delta_raw > 0 AND greatest(qty_before_raw, 0) <= {dust} THEN 1 ELSE 0 END
               AS is_open
    FROM q
),
epi AS (
    SELECT *,
           sum(is_open) OVER (PARTITION BY mint_id, owner_id ORDER BY slot, txi
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS episode
    FROM seg
),
ac AS (
    SELECT *,
           CASE WHEN is_open = 1 THEN 1.0
                WHEN delta_raw > 0 THEN qty_before / (qty_before + delta_raw)
                ELSE 1.0 END AS a,
           CASE WHEN is_open = 1 THEN coalesce(px, 0.0)
                WHEN delta_raw > 0 THEN coalesce(px, 0.0) * delta_raw / (qty_before + delta_raw)
                ELSE 0.0 END AS c
    FROM epi WHERE episode >= 1
),
la AS (
    SELECT *, sum(ln(a)) OVER w AS log_a_cum
    FROM ac
    WINDOW w AS (PARTITION BY mint_id, owner_id, episode ORDER BY slot, txi
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
bs AS (
    SELECT *, exp(log_a_cum) * sum(c * exp(-log_a_cum)) OVER w AS basis_after
    FROM la
    WINDOW w AS (PARTITION BY mint_id, owner_id, episode ORDER BY slot, txi
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT mint_id, owner_id, episode, slot, txi, t, delta_raw, sol, px, route,
       cp_bal_after, offset_raw, qty_before, qty_after,
       basis_after,
       lag(basis_after) OVER (PARTITION BY mint_id, owner_id, episode
                              ORDER BY slot, txi) AS basis_before_lag,
       is_open
FROM bs
"""


def cmd_basis(args: argparse.Namespace) -> int:
    con = _duck(args.threads, args.memory)
    t0 = time.time()
    out = _out() / "stage" / "legs.parquet"
    trades = _trades_path()
    n_in = con.execute(f"SELECT count(*) FROM read_parquet('{trades}')").fetchone()[0]
    print(f"[basis] {n_in:,} priced legs in", flush=True)

    sql = BASIS_SQL.format(trades=trades, dust=DUST)
    tmp = out.parent / f".tmp-{out.name}"
    con.execute(
        f"""
        COPY (
          SELECT mint_id, owner_id, episode, slot, txi, t, delta_raw, sol, px, route,
                 cp_bal_after, offset_raw, qty_before, qty_after,
                 coalesce(basis_before_lag, basis_after) AS basis_before,
                 -- realized fraction of a SELL against average-cost basis, executable (px is
                 -- the fill's own effective price, impact included)
                 CASE WHEN delta_raw < 0 AND coalesce(basis_before_lag, 0) > 0 AND px > 0
                      THEN px / basis_before_lag - 1.0 END AS realized_frac,
                 -- executable realized SOL banked by a sell against that basis
                 CASE WHEN delta_raw < 0 AND coalesce(basis_before_lag, 0) > 0
                      THEN -delta_raw * (px - basis_before_lag) END AS realized_sol,
                 -- curve marginal log-price where the counterparty was the bonding curve
                 CASE WHEN route = 'curve' AND cp_bal_after + offset_raw > 0
                      THEN ln({K_CURVE}) - 2 * ln(cp_bal_after + offset_raw) - ln({LAMPORTS})
                 END AS log_mark_curve
          FROM ({sql})
          ORDER BY mint_id, slot, txi
        ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
        """
    )
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"[basis] {n:,} legs with basis -> {out}  ({time.time() - t0:.0f}s)", flush=True)
    return 0


# =====================================================================================
# stage: wallet -- the standing per-wallet estimator
# =====================================================================================

#: The guild rules, lifted verbatim from cluster_map._guild (rules apply top to bottom, first
#: match wins). Applied here per-WALLET as the ``guild_solo`` analog; the authoritative label is
#: ``guild_cluster`` from the ten-day bulk map where the wallet is in a cluster.
def _guild(fresh_frac, exit_ratio, med_hold) -> str:
    if fresh_frac is not None and fresh_frac == fresh_frac and fresh_frac < 0.5:
        return "AFTERMARKET"
    if exit_ratio is not None and exit_ratio == exit_ratio and exit_ratio < 0.2:
        return "ACCUMULATOR"
    if med_hold is None or med_hold != med_hold:
        return "FLASH"
    if med_hold <= 60:
        return "FLASH"
    if med_hold <= 3600:
        return "HARVESTER"
    return "SLOW"


def _rp_mode(breakeven, at_loss, med_rf, holds_red) -> str:
    """A descriptive realization-policy label from the per-wallet sell distribution."""
    if breakeven is not None and breakeven == breakeven and breakeven > 0.40:
        return "BREAKEVEN_PRESET"
    if at_loss is not None and at_loss == at_loss and at_loss > 0.55:
        return "LOSS_CUTTER"
    if med_rf is not None and med_rf == med_rf and med_rf > 0.30:
        return "PROFIT_RUNNER"
    if holds_red is not None and holds_red == holds_red and holds_red > 0.30:
        return "AVERAGES_DOWN"
    return "MIXED"


def cmd_wallet(args: argparse.Namespace) -> int:
    import numpy as np

    con = _duck(args.threads, args.memory)
    t0 = time.time()
    legs = _out() / "stage" / "legs.parquet"
    if not legs.exists():
        raise SystemExit("run `basis` first")

    # ---- per (owner, mint): position summary, executable realized PnL, hold time -----------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE om AS
        SELECT owner_id, mint_id,
               count(*) AS n_legs,
               sum((delta_raw > 0)::int) AS n_buys,
               sum((delta_raw < 0)::int) AS n_sells,
               sum(CASE WHEN delta_raw > 0 THEN delta_raw ELSE 0 END) AS bought_tok,
               sum(CASE WHEN delta_raw < 0 THEN -delta_raw ELSE 0 END) AS sold_tok,
               sum(CASE WHEN sol > 0 THEN sol ELSE 0 END) AS buy_sol,
               sum(CASE WHEN sol < 0 THEN -sol ELSE 0 END) AS sell_sol,
               min(t) AS t_first,
               min(CASE WHEN delta_raw > 0 THEN t END) AS t_first_buy,
               max(CASE WHEN delta_raw < 0 THEN t END) AS t_last_sell,
               max(t) AS t_last
        FROM read_parquet('{legs}')
        GROUP BY 1, 2
        """
    )
    # closed = essentially fully exited; win = realized cash positive on a closed coin.
    con.execute(
        """
        CREATE OR REPLACE TABLE om2 AS
        SELECT *,
               (sold_tok >= 0.9 * bought_tok AND bought_tok > 0) AS closed,
               -- executable realized cash on the SOLD fraction: SOL received minus the
               -- average-cost SOL paid for the tokens actually sold. Bounded by real SOL
               -- flows (each leg < 1e6 SOL); never marks unsold inventory into profit, which
               -- is what booked +950 where the executable exit was +35.
               (sell_sol - buy_sol * least(1.0, sold_tok / nullif(bought_tok, 0)))
                   AS realized_cash,
               CASE WHEN t_last_sell IS NOT NULL AND t_first_buy IS NOT NULL
                         AND t_last_sell >= t_first_buy
                    THEN t_last_sell - t_first_buy END AS hold_s
        FROM om
        """
    )

    # ---- per owner: activity, asymmetry, PnL, hold ----------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_core AS
        SELECT owner_id,
               count(*) AS n_coins,
               sum(n_legs) AS n_legs, sum(n_buys) AS n_buys, sum(n_sells) AS n_sells,
               sum(buy_sol) AS buy_sol, sum(sell_sol) AS sell_sol,
               sum(buy_sol + sell_sol) AS gross_sol,
               sum(realized_cash) AS net_realized_sol,
               sum(closed::int) AS n_coins_closed,
               sum((closed AND realized_cash > 0)::int) AS n_coins_win,
               median(CASE WHEN closed THEN realized_cash END) AS median_realized_sol_closed,
               sum(((sold_tok >= 0.9 * bought_tok) AND bought_tok > 0)::int)::DOUBLE
                   / nullif(count(*), 0) AS roundtrip_frac,
               median(hold_s) AS median_hold_s,
               quantile_cont(hold_s, 0.90) AS p90_hold_s,
               min(t_first) AS t_first, max(t_last) AS t_last
        FROM om2
        GROUP BY 1
        HAVING sum(n_legs) >= {MIN_LEGS}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_days AS
        SELECT owner_id, count(DISTINCT (t / 86400)::int) AS active_days
        FROM read_parquet('{legs}') GROUP BY 1
        """
    )
    n_w = con.execute("SELECT count(*) FROM w_core").fetchone()[0]
    print(f"[wallet] {n_w:,} active wallets (>= {MIN_LEGS} legs)  ({time.time() - t0:.0f}s)",
          flush=True)

    # ---- per owner: realization-policy fingerprint summary (from sells) --------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_rp AS
        SELECT owner_id,
               count(*) AS n_priced_sells,
               avg((realized_frac > 0)::int) AS rp_frac_in_profit,
               avg((realized_frac < -0.05)::int) AS rp_frac_at_loss,
               avg((abs(realized_frac) < 0.05)::int) AS rp_frac_breakeven,
               quantile_cont(realized_frac, 0.10) AS rp_p10,
               quantile_cont(realized_frac, 0.50) AS rp_p50,
               quantile_cont(realized_frac, 0.90) AS rp_p90
        FROM read_parquet('{legs}')
        WHERE realized_frac IS NOT NULL
        GROUP BY 1
        """
    )
    # adds-while-red: buys made below the wallet's running average cost (averaging down) --
    # the conviction / hold-through-red signal.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_red AS
        SELECT owner_id,
               avg((px < basis_before)::int) AS holds_through_red,
               count(*) AS n_adds
        FROM read_parquet('{legs}')
        WHERE delta_raw > 0 AND basis_before > 0 AND qty_before > {DUST}
              AND px > 0
        GROUP BY 1
        """
    )

    # ---- per owner: guild-solo inputs (fresh_frac vs cohort birth window) ------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_fresh AS
        SELECT o.owner_id,
               avg((c.mint IS NOT NULL)::int) AS fresh_frac
        FROM (SELECT DISTINCT owner_id, mint_id FROM om) o
        JOIN read_parquet('{MINTS}') mn ON mn.mint_id = o.mint_id
        LEFT JOIN read_parquet('{COHORT}') c ON c.mint = mn.mint AND c.birth_time IS NOT NULL
        GROUP BY 1
        """
    )
    # entry latency: first buy minus coin birth, over cohort coins with a known birth.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_lat AS
        SELECT o.owner_id,
               median(o.t_first_buy - c.birth_time)
                   FILTER (WHERE c.birth_time IS NOT NULL AND o.t_first_buy IS NOT NULL
                                 AND o.t_first_buy - c.birth_time BETWEEN 0 AND 86400)
                   AS median_entry_latency_s
        FROM om2 o
        JOIN read_parquet('{MINTS}') mn ON mn.mint_id = o.mint_id
        LEFT JOIN read_parquet('{COHORT}') c ON c.mint = mn.mint
        GROUP BY 1
        """
    )

    # ---- rotation membership ---------------------------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_rot AS
        SELECT owner_id, count(DISTINCT h) AS rotation_hours
        FROM read_parquet('{ROTATION}') GROUP BY 1
        """
    )

    # ---- cluster / guild / ladder (join base58 owner) --------------------------------------
    # clusters_bulk and resonance2 are keyed by the base58 owner and cluster id from the
    # ten-day bulk map; owners.parquet maps owner_id <-> owner.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE w_clu AS
        SELECT ow.owner_id, cl.cid, g.guild AS guild_cluster,
               (cl.cid IN (SELECT A FROM read_parquet('{RESON2}')
                           UNION SELECT B FROM read_parquet('{RESON2}'))) AS on_ladder
        FROM read_parquet('{CLUSTERS}') cl
        JOIN read_parquet('{OWNERS}') ow ON ow.owner = cl.owner
        LEFT JOIN read_parquet('{GUILDS}') g ON g.cid = cl.cid
        """
    )

    # ---- assemble --------------------------------------------------------------------------
    df = con.execute(
        f"""
        SELECT c.*, ow.owner, coalesce(d.active_days, 0) AS active_days,
               rp.n_priced_sells, rp.rp_frac_in_profit, rp.rp_frac_at_loss,
               rp.rp_frac_breakeven, rp.rp_p10, rp.rp_p50, rp.rp_p90,
               red.holds_through_red, red.n_adds,
               f.fresh_frac, lat.median_entry_latency_s,
               (rot.owner_id IS NOT NULL) AS in_rotation,
               coalesce(rot.rotation_hours, 0) AS rotation_hours,
               clu.cid, clu.guild_cluster, coalesce(clu.on_ladder, false) AS on_ladder
        FROM w_core c
        JOIN read_parquet('{OWNERS}') ow USING (owner_id)
        LEFT JOIN w_days d USING (owner_id)
        LEFT JOIN w_rp rp USING (owner_id)
        LEFT JOIN w_red red USING (owner_id)
        LEFT JOIN w_fresh f USING (owner_id)
        LEFT JOIN w_lat lat USING (owner_id)
        LEFT JOIN w_rot rot USING (owner_id)
        LEFT JOIN w_clu clu USING (owner_id)
        """
    ).df()

    df["win_rate"] = df["n_coins_win"] / df["n_coins_closed"].clip(lower=1)
    df.loc[df["n_coins_closed"] == 0, "win_rate"] = np.nan
    df["sol_asymmetry"] = (df["buy_sol"] - df["sell_sol"]) / df["gross_sol"].clip(lower=1e-9)
    df["sell_buy_leg_ratio"] = df["n_sells"] / df["n_buys"].clip(lower=1)
    df["exit_ratio"] = df["n_sells"] / df["n_buys"].clip(lower=1)
    df["span_days"] = (df["t_last"] - df["t_first"]) / 86400.0

    df["guild_solo"] = [
        _guild(fr, er, mh)
        for fr, er, mh in zip(df["fresh_frac"], df["exit_ratio"], df["median_hold_s"], strict=False)
    ]
    df["guild"] = df["guild_cluster"].where(df["guild_cluster"].notna(), df["guild_solo"])
    df["rp_mode"] = [
        _rp_mode(be, al, mrf, hr)
        for be, al, mrf, hr in zip(
            df["rp_frac_breakeven"], df["rp_frac_at_loss"], df["rp_p50"],
            df["holds_through_red"], strict=False,
        )
    ]
    df["updated_through"] = int(df["t_last"].max())
    df["schema_version"] = SCHEMA_VERSION

    cols = [
        "owner", "owner_id",
        "n_legs", "n_buys", "n_sells", "n_coins", "active_days", "span_days",
        "t_first", "t_last",
        "gross_sol", "buy_sol", "sell_sol", "sol_asymmetry", "sell_buy_leg_ratio",
        "net_realized_sol", "win_rate", "n_coins_closed", "n_coins_win",
        "median_realized_sol_closed", "roundtrip_frac",
        "median_hold_s", "p90_hold_s",
        "n_priced_sells", "rp_frac_in_profit", "rp_frac_at_loss", "rp_frac_breakeven",
        "rp_p10", "rp_p50", "rp_p90", "holds_through_red", "rp_mode",
        "fresh_frac", "exit_ratio", "guild_solo", "cid", "guild_cluster", "guild",
        "median_entry_latency_s", "on_ladder",
        "in_rotation", "rotation_hours",
        "updated_through", "schema_version",
    ]
    df = df[cols]
    out = _out() / "estimator.parquet"
    df.to_parquet(out, index=False)
    print(f"[wallet] wrote {out}  ({len(df):,} wallets, {time.time() - t0:.0f}s)", flush=True)

    # ---- a small readout for the RESULT ----------------------------------------------------
    summ = {
        "n_wallets": len(df),
        "min_legs": MIN_LEGS,
        "updated_through": int(df["updated_through"].iloc[0]),
        "guild_counts": df["guild"].value_counts().to_dict(),
        "guild_cluster_coverage": int(df["guild_cluster"].notna().sum()),
        "rp_mode_counts": df["rp_mode"].value_counts().to_dict(),
        "in_rotation": int(df["in_rotation"].sum()),
        "on_ladder": int(df["on_ladder"].sum()),
        "net_realized_sol": {
            "sum": float(df["net_realized_sol"].sum()),
            "median": float(df["net_realized_sol"].median()),
            "frac_positive": float((df["net_realized_sol"] > 0).mean()),
        },
        "win_rate_median": float(df["win_rate"].median(skipna=True)),
        "rp_frac_breakeven_median": float(df["rp_frac_breakeven"].median(skipna=True)),
    }
    (_out() / "wallet_summary.json").write_text(json.dumps(summ, indent=2, default=str))
    print(json.dumps(summ, indent=2, default=str), flush=True)
    return 0


# =====================================================================================
# stage: iceberg -- piecewise / iceberg distribution detection
# =====================================================================================

#: A material holder to even consider. 1e12 raw = 0.1% of a 1e15-supply mint. Below this a
#: "distribution" is not chart-moving and the question is not interesting.
PEAK_FLOOR = 1e12
#: A distribution phase: the bag drew down at least this far, over at least this many sells,
#: spread over at least this long (a single-slot multi-sell is a bundle split, not chart
#: management, and is excluded by the duration floor).
MIN_DRAWDOWN = 0.60
MIN_DIST_SELLS = 8
MIN_DURATION_S = 300


def _iceberg_candidates(con, legs: str):
    """Per (owner, mint) distribution episode with drawdown / fragmentation / resilience and
    (curve route only) the exact own-alone absorption term."""
    con.execute(
        f"""
        CREATE OR REPLACE TABLE pk AS
        SELECT owner_id, mint_id,
               max(qty_after) AS peak_qty,
               arg_max(slot * 1000000.0 + txi, qty_after) AS peak_ord,
               arg_max(t, qty_after) AS peak_t,
               arg_max(coalesce(log_mark_curve, ln(nullif(px, 0))), qty_after) AS peak_logpx,
               arg_max(cp_bal_after + offset_raw, qty_after) AS peak_vtok,
               any_value(route) AS route
        FROM read_parquet('{legs}')
        WHERE qty_after > {DUST}
        GROUP BY 1, 2
        HAVING max(qty_after) >= {PEAK_FLOOR}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE dist AS
        SELECT l.owner_id, l.mint_id,
               count(*) FILTER (WHERE l.delta_raw < 0) AS n_dist_sells,
               sum(CASE WHEN l.delta_raw < 0 THEN -l.delta_raw ELSE 0 END) AS dist_sold_tok,
               sum(CASE WHEN l.delta_raw < 0 THEN -l.sol ELSE 0 END) AS dist_sold_sol,
               min(l.qty_after) AS min_qty_after_peak,
               min(l.t) FILTER (WHERE l.delta_raw < 0) AS first_dist_t,
               max(l.t) FILTER (WHERE l.delta_raw < 0) AS last_dist_t,
               median(CASE WHEN l.delta_raw < 0 THEN -l.delta_raw END) AS median_sell_tok,
               arg_max(coalesce(l.log_mark_curve, ln(nullif(l.px, 0))),
                       l.slot * 1000000.0 + l.txi) FILTER (WHERE l.delta_raw < 0) AS end_logpx,
               arg_max(l.cp_bal_after + l.offset_raw, l.slot * 1000000.0 + l.txi)
                   FILTER (WHERE l.delta_raw < 0) AS end_vtok
        FROM read_parquet('{legs}') l
        JOIN pk USING (owner_id, mint_id)
        WHERE l.slot * 1000000.0 + l.txi > pk.peak_ord
        GROUP BY 1, 2
        """
    )
    df = con.execute(
        """
        SELECT d.*, pk.peak_qty, pk.peak_t, pk.peak_logpx, pk.peak_vtok, pk.route
        FROM dist d JOIN pk USING (owner_id, mint_id)
        WHERE d.n_dist_sells >= 1 AND d.dist_sold_tok > 0
        """
    ).df()
    return df


def cmd_iceberg(args: argparse.Namespace) -> int:
    import numpy as np
    import pandas as pd

    con = _duck(args.threads, args.memory)
    t0 = time.time()
    legs = str(_out() / "stage" / "legs.parquet")
    if not Path(legs).exists():
        raise SystemExit("run `basis` first")

    df = _iceberg_candidates(con, legs)
    print(f"[iceberg] {len(df):,} (wallet,coin) distribution episodes  "
          f"({time.time() - t0:.0f}s)", flush=True)

    # drawdown / sold_frac > 1 mean the wallet held a PRE-WINDOW bag (left-censored): it sold
    # more than it bought inside the corpus. That is real and relevant (a big pre-existing
    # holder distributing), but clip the metric to [0, 1] so the score is bounded.
    df["drawdown"] = ((df["peak_qty"] - df["min_qty_after_peak"]) / df["peak_qty"]).clip(0, 1)
    df["sold_frac_of_own"] = (df["dist_sold_tok"] / df["peak_qty"]).clip(0, 1)
    df["duration_s"] = (df["last_dist_t"] - df["first_dist_t"]).astype(float)
    df["frag"] = df["median_sell_tok"] / df["peak_qty"]
    df["resilience"] = df["end_logpx"] - df["peak_logpx"]  # log price change, propped ~ 0
    # exact curve absorption where both endpoints are curve v_tok
    with np.errstate(all="ignore"):
        alone = -2.0 * np.log((df["peak_vtok"] + df["dist_sold_tok"]) / df["peak_vtok"])
        realized = -2.0 * np.log(df["end_vtok"] / df["peak_vtok"])
        df["absorption"] = 1.0 - realized / alone
    df.loc[df["route"] != "curve", "absorption"] = np.nan
    df.loc[~np.isfinite(df["absorption"]), "absorption"] = np.nan

    # continuous iceberg score, route-agnostic: distributed most of a big bag, in many small
    # sells, while the price held.
    df["iceberg_score"] = (
        df["drawdown"].clip(0, 1)
        * df["sold_frac_of_own"].clip(0, 1)
        * np.log1p(df["n_dist_sells"])
        * (1.0 + df["resilience"]).clip(0, 2)
    )
    df["is_candidate"] = (
        (df["drawdown"] >= MIN_DRAWDOWN)
        & (df["n_dist_sells"] >= MIN_DIST_SELLS)
        & (df["duration_s"] >= MIN_DURATION_S)
    )

    # operator mint_ids so their episodes are always tested regardless of score.
    op_ids = con.execute(
        f"SELECT mint_id, mint FROM read_parquet('{MINTS}') WHERE mint IN "
        f"({','.join(repr(m) for m in OPERATOR_COINS.values())})"
    ).df()
    op_map = dict(zip(op_ids["mint_id"], op_ids["mint"], strict=False))

    # the set the timing null runs on: FDR is only honest over the tested set, so cap it.
    # We test THREE strata so the base rate is honest, not just the cherry-picked tail:
    #   * the top `null_top` gated candidates by score (the strongest icebergs),
    #   * a RANDOM sample of gated candidates (the benign-vs-iceberg population rate),
    #   * every operator-coin episode (always scored).
    cand = df[df["is_candidate"]].copy()
    top = cand.sort_values("iceberg_score", ascending=False).head(args.null_top)
    top["stratum"] = "top_score"
    rand = cand.drop(top.index, errors="ignore").sample(
        n=min(len(cand), args.null_rand), random_state=args.seed
    ) if len(cand) else cand
    rand["stratum"] = "random_gated"
    op_eps = df[df["mint_id"].isin(op_map) & (df["n_dist_sells"] >= 3)].copy()
    op_eps["stratum"] = "operator"
    tested = pd.concat(
        [top[["owner_id", "mint_id", "stratum"]],
         rand[["owner_id", "mint_id", "stratum"]],
         op_eps[["owner_id", "mint_id", "stratum"]]],
        ignore_index=True,
    ).drop_duplicates(subset=["owner_id", "mint_id"])
    print(f"[iceberg] {int(df['is_candidate'].sum()):,} gated candidates; timing null on "
          f"{len(tested):,} (top {args.null_top} + {len(rand):,} random + operator)", flush=True)

    tested = tested.merge(df, on=["owner_id", "mint_id"], how="left")
    corpus_end = con.execute(f"SELECT max(t) FROM read_parquet('{legs}')").fetchone()[0]

    # cluster ids for the self-wash discriminator
    cid_map = dict(
        con.execute(
            f"""SELECT ow.owner_id, cl.cid FROM read_parquet('{CLUSTERS}') cl
                JOIN read_parquet('{OWNERS}') ow ON ow.owner = cl.owner"""
        ).fetchall()
    )

    # ---- the timing null, per coin ---------------------------------------------------------
    # pull every tested coin's full tape in ONE scan, then group in pandas -- a per-coin scan
    # of the 57M-row parquet would be thousands of full passes.
    rng = np.random.default_rng(args.seed)
    tested_mints = sorted(int(x) for x in tested["mint_id"].dropna().unique())
    print(f"[iceberg] loading legs for {len(tested_mints):,} tested coins ...", flush=True)
    coins_all = con.execute(
        f"""SELECT mint_id, owner_id, (t // 60) AS m, delta_raw, t
            FROM read_parquet('{legs}')
            WHERE mint_id IN ({','.join(str(m) for m in tested_mints)})"""
    ).df()
    coins_all["cid"] = coins_all["owner_id"].map(cid_map)
    by_mint = {mid: g for mid, g in coins_all.groupby("mint_id")}
    recs = []
    for mint_id, grp in tested.groupby("mint_id"):
        coin = by_mint.get(int(mint_id))
        if coin is None or coin.empty:
            continue
        for r in grp.itertuples(index=False):
            w = int(r.owner_id)
            lo_m, hi_m = int(r.first_dist_t // 60), int(r.last_dist_t // 60)
            win = coin[(coin["m"] >= lo_m) & (coin["m"] <= hi_m)]
            others = win[win["owner_id"] != w]
            # per-minute net others flow (buys - sells by others) = absorption of W's supply
            net = (
                others.assign(v=others["delta_raw"])
                .groupby("m")["v"].sum()
            )
            active = np.array(sorted(win["m"].unique()))
            # W's own sells within the window
            wsell = win[(win["owner_id"] == w) & (win["delta_raw"] < 0)].copy()
            wsell["sz"] = -wsell["delta_raw"]
            if len(wsell) < 3 or len(active) < 5:
                continue
            nf = net.reindex(active, fill_value=0.0)
            nf_map = dict(zip(active, nf.values, strict=False))
            szs = wsell["sz"].to_numpy()
            wsm = wsell["m"].to_numpy()
            t_obs = float(np.sum(szs * np.array([nf_map.get(m, 0.0) for m in wsm])) / szs.sum())
            # permutation: relocate W's sells to random active minutes in its own window
            draws = rng.choice(nf.values, size=(args.null_draws, len(szs)), replace=True)
            t_null = (draws * szs).sum(axis=1) / szs.sum()
            p = (int(np.sum(t_null >= t_obs)) + 1) / (args.null_draws + 1)
            # self-wash: share of others' BUY tokens during W's actual sell minutes coming from
            # W's own cluster peers
            wsell_mins = set(wsm.tolist())
            in_win_others = others[others["m"].isin(wsell_mins) & (others["delta_raw"] > 0)]
            tot_buy = float(in_win_others["delta_raw"].sum())
            self_wash = float("nan")
            wcid = cid_map.get(w)
            if wcid is not None and tot_buy > 0:
                peer = in_win_others[in_win_others["cid"] == wcid]
                self_wash = float(peer["delta_raw"].sum() / tot_buy)
            recs.append({
                "owner_id": w, "mint_id": int(mint_id),
                "stratum": r.stratum,
                "timing_t_obs": t_obs, "timing_null_mean": float(t_null.mean()),
                "timing_p": p, "self_wash": self_wash,
                "n_active_minutes": len(active),
                "is_recent": bool(r.last_dist_t >= corpus_end - args.recency),
            })

    tdf = pd.DataFrame(recs)
    if not tdf.empty:
        tdf["timing_q"] = _by_fdr_q(tdf["timing_p"].to_numpy())
        df = df.merge(tdf, on=["owner_id", "mint_id"], how="left")
    else:
        for c in ("timing_t_obs", "timing_null_mean", "timing_p", "timing_q",
                  "self_wash", "n_active_minutes", "is_recent"):
            df[c] = np.nan

    # attach owner base58 + mint
    omap = dict(con.execute(f"SELECT owner_id, owner FROM read_parquet('{OWNERS}')").fetchall())
    mmap = dict(con.execute(f"SELECT mint_id, mint FROM read_parquet('{MINTS}')").fetchall())
    df["owner"] = df["owner_id"].map(omap)
    df["mint"] = df["mint_id"].map(mmap)

    out = _out() / "iceberg.parquet"
    keep = [
        "owner", "mint", "owner_id", "mint_id", "route",
        "peak_qty", "peak_t", "dist_sold_tok", "dist_sold_sol", "n_dist_sells",
        "drawdown", "sold_frac_of_own", "frag", "duration_s",
        "first_dist_t", "last_dist_t", "resilience", "absorption", "iceberg_score",
        "is_candidate", "stratum", "timing_t_obs", "timing_null_mean", "timing_p", "timing_q",
        "self_wash", "n_active_minutes", "is_recent",
    ]
    if "stratum" not in df.columns:
        df["stratum"] = np.nan
    df[keep].to_parquet(out, index=False)
    print(f"[iceberg] wrote {out}  ({time.time() - t0:.0f}s)", flush=True)

    # ---- per-coin exit signal --------------------------------------------------------------
    passed = df[(df["timing_q"] <= 0.10) & (df["is_candidate"])]
    coin_sig = (
        df[df["is_candidate"]]
        .groupby(["mint_id", "mint"])
        .agg(
            n_distributors=("owner_id", "nunique"),
            max_iceberg_score=("iceberg_score", "max"),
            any_recent=("is_recent", "max"),
            n_timing_pass=("timing_q", lambda s: int((s <= 0.10).sum())),
            last_dist_t=("last_dist_t", "max"),
        )
        .reset_index()
    )
    coin_sig.to_parquet(_out() / "coin_exit_signal.parquet", index=False)

    summ = {
        "n_episodes": len(df),
        "n_gated_candidates": int(df["is_candidate"].sum()),
        "n_timing_tested": len(tdf),
        "n_timing_pass_fdr10": len(passed),
        "curve_absorption": {
            "n": int(df["absorption"].notna().sum()),
            "candidates_median_absorption": float(
                df.loc[df["is_candidate"], "absorption"].median(skipna=True)
            ),
            "noncandidate_median_absorption": float(
                df.loc[~df["is_candidate"], "absorption"].median(skipna=True)
            ),
        },
        "candidates_vs_benign": {
            "candidate_median_resilience": float(
                df.loc[df["is_candidate"], "resilience"].median(skipna=True)
            ),
            "noncandidate_median_resilience": float(
                df.loc[~df["is_candidate"], "resilience"].median(skipna=True)
            ),
        },
        # the honest base rate: timing-null pass fraction (raw p<=0.05) BY stratum. If
        # top_score passes far more than random_gated, iceberg is a real tail, not everyone.
        "timing_pass_by_stratum": (
            tdf.assign(pass05=(tdf["timing_p"] <= 0.05))
            .groupby("stratum")
            .agg(n=("timing_p", "size"), frac_pass05=("pass05", "mean"),
                 median_p=("timing_p", "median"))
            .reset_index()
            .to_dict(orient="records")
            if not tdf.empty else []
        ),
    }
    (_out() / "iceberg_summary.json").write_text(json.dumps(summ, indent=2, default=str))
    print(json.dumps(summ, indent=2, default=str), flush=True)
    return 0


def _by_fdr_q(pvals):
    """Benjamini-Yekutieli adjusted q-values (dependency-safe; PROGRAM.md 3.13)."""
    import numpy as np

    p = np.asarray(pvals, float)
    n = len(p)
    if n == 0:
        return p
    c = float(np.sum(1.0 / np.arange(1, n + 1)))
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n * c / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(q, 0, 1)
    return out


# =====================================================================================
# stage: operator -- score the four coins on the freshest flow
# =====================================================================================


def cmd_operator(args: argparse.Namespace) -> int:

    con = _duck(args.threads, args.memory)
    ice = _out() / "iceberg.parquet"
    if not ice.exists():
        raise SystemExit("run `iceberg` first")
    legs = str(_out() / "stage" / "legs.parquet")
    corpus_end = con.execute(f"SELECT max(t) FROM read_parquet('{legs}')").fetchone()[0]

    df = con.execute(f"SELECT * FROM read_parquet('{ice}')").df()
    import datetime as dt

    import pandas as pd

    def _f(x):
        return None if x is None or pd.isna(x) else float(x)

    def _b(x):
        return bool(x) if not pd.isna(x) else False

    def _utc(ts):
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).isoformat()
    scan = {
        "corpus_end_unix": int(corpus_end),
        "corpus_end_utc": _utc(corpus_end),
        "freshness_note": (
            "'now' is the tail of the priced corpus tape (ends 2026-08-14 23:59 UTC). This "
            "layer is not wired to the live sentinel/paperdesk feed; a live join would refresh "
            "`last_dist_t` against the desk ledger. See the join contract."
        ),
        "coins": {},
    }
    for name, mint in OPERATOR_COINS.items():
        sub = df[df["mint"] == mint].copy()
        # every sizeable distribution episode on the coin, most iceberg-like first
        sub = sub.sort_values("iceberg_score", ascending=False)
        distributors = []
        for r in sub.head(args.top).itertuples(index=False):
            distributors.append({
                "owner": r.owner,
                "peak_tok": _f(r.peak_qty),
                "peak_supply_share": _f(r.peak_qty / 1e15),
                "n_dist_sells": int(r.n_dist_sells),
                "dist_sold_sol": _f(r.dist_sold_sol),
                "drawdown": _f(r.drawdown),
                "sold_frac_of_own": _f(r.sold_frac_of_own),
                "resilience_dlogpx": _f(r.resilience),
                "iceberg_score": _f(r.iceberg_score),
                "is_candidate": _b(r.is_candidate),
                "timing_p": _f(r.timing_p),
                "timing_q": _f(r.timing_q),
                "self_wash": _f(r.self_wash),
                "last_dist_utc": _utc(r.last_dist_t),
                "is_recent_48h": _b(r.is_recent),
            })
        n_cand = int(sub["is_candidate"].sum())
        n_pass = int(((sub["timing_q"] <= 0.10) & sub["is_candidate"]).sum())
        recent_cand = sub[sub["is_candidate"] & sub["is_recent"].fillna(False)]
        verdict = _operator_verdict(n_cand, n_pass, len(recent_cand))
        scan["coins"][name] = {
            "mint": mint,
            "n_distribution_episodes": len(sub),
            "n_gated_candidates": n_cand,
            "n_timing_pass_fdr10": n_pass,
            "n_recent_candidates_48h": len(recent_cand),
            "verdict": verdict,
            "top_distributors": distributors,
        }
    (_out() / "operator_scan.json").write_text(json.dumps(scan, indent=2, default=str))
    print(json.dumps(scan, indent=2, default=str), flush=True)
    return 0


def _operator_verdict(n_cand, n_pass, n_recent) -> str:
    if n_pass >= 1 and n_recent >= 1:
        return ("ICEBERG-DISTRIBUTING NOW: a large holder is drawing its bag down via many "
                "small sells timed into buy pressure (FDR<=0.10), within the last 48h.")
    if n_pass >= 1:
        return ("ICEBERG PATTERN present earlier in the window (FDR<=0.10 timing), but not in "
                "the last 48h of the tape.")
    if n_cand >= 1:
        return ("CHUNKED DISTRIBUTION present (deep drawdown via many small sells) but timing "
                "does not beat the within-coin null -- looks like benign DCA-out, not chart "
                "management.")
    return "NO iceberg distribution detected on this coin in the corpus window."


# =====================================================================================
# report
# =====================================================================================


def cmd_report(args: argparse.Namespace) -> int:
    out = _out()
    parts = {}
    for f in ("wallet_summary.json", "iceberg_summary.json", "operator_scan.json"):
        p = out / f
        parts[f] = json.loads(p.read_text()) if p.exists() else None
    print(json.dumps(parts, indent=2, default=str), flush=True)
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    for fn in (cmd_basis, cmd_wallet, cmd_iceberg, cmd_operator, cmd_report):
        rc = fn(args)
        if rc:
            return rc
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("basis", "wallet", "iceberg", "operator", "report", "all"):
        p = sub.add_parser(name)
        p.add_argument("--threads", type=int, default=6)
        p.add_argument("--memory", default="16GB")
        p.add_argument("--seed", type=int, default=20260816)
        if name in ("iceberg", "all"):
            p.add_argument("--null-draws", type=int, default=500)
            p.add_argument("--null-top", type=int, default=4000)
            p.add_argument("--null-rand", type=int, default=1500)
            p.add_argument("--recency", type=int, default=172800)  # 48h
        if name in ("operator", "all"):
            p.add_argument("--top", type=int, default=15)
    args = ap.parse_args(argv)
    fn = {
        "basis": cmd_basis, "wallet": cmd_wallet, "iceberg": cmd_iceberg,
        "operator": cmd_operator, "report": cmd_report, "all": cmd_all,
    }[args.cmd]
    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
