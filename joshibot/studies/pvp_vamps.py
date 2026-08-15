#!/usr/bin/env python3
"""PvP state and vamp drain: is "everyone extracting from each other" a measurable state,
and does a derivative launch actually siphon its host?

WHY THIS EXISTS
---------------
Two pieces of operator-community slang, taken as hypotheses rather than as vocabulary:

* **PvP** -- a coin or meta where no outside money enters and the participants extract from
  each other. Mercenary rotation, no accumulation, short holds, everybody exit-planning.
* **VAMP** -- a launch that siphons an existing runner's attention and liquidity: a
  derivative coin feeding on the host's overflow.

Both are claims about *wallet-level flow*, and this repo has never measured either. The
closest thing is ``RESULT_caller_wallets.md``'s ``recycled_30m`` -- the share of the last
half hour's buying already sold back -- which scored **AUC 0.824 alone at 8 h** for survival
and is therefore the incumbent baseline any PvP meter has to beat. It is a PvP meter with one
column; this study asks whether the other four columns of the folk definition add anything.

FOUNDATIONS THIS BUILDS ON RATHER THAN RE-DERIVES
-------------------------------------------------
``RESULT_caller_wallets.md``   ``recycled_30m``, and the naive-vs-matched null trap.
``RESULT_imitation_signal.md`` clone-family clustering; swarmed hosts LIVE LONGER.
``RESULT_callout_volatility.md`` the flow-up-at-flat-RV condition; ``eta = 2fN/(C*RV)``.
``RESULT_crime_signatures.md`` GHOST_TOWN: PvP endings are cliff-shaped.
``studies/operator_crime.py``  the affine pricing identity, which prices every corpus coin free.

THE PRICING, AND WHY IT IS EXACT RATHER THAN AFFINE
----------------------------------------------------
A pump.fun bonding-curve trade carries only the TOKEN leg on chain -- the curve holds native
SOL in the PDA's lamports, which is not a token balance. ``operator_crime.py`` uses that to
get log-price up to a constant. For this study the constant matters (a vamp drain is
SOL-weighted, and ``eta``'s fee term is proportional to volume), so the identity is taken one
step further. On a constant product ``v_sol * v_tok = K``:

    sol_lamports_paid = K * (1/v_tok_after - 1/v_tok_before)

which is the **exact** SOL leg of the trade, recovered from the token leg alone. Both curve
configurations observed in this corpus share the same virtual reserves
(``v_tok_virt = 1.073e15`` raw, ``v_sol_virt = 3e10`` lamports, so ``K = 3.219e25``); they
differ only in how much real supply sits in the curve at launch (7.931e14 raw for the older
config, 1.0e15 for the newer), so the per-mint offset is

    OFFSET(mint) = 1.073e15 - initial_curve_balance(mint)

and ``v_tok = curve_balance + OFFSET``. ``RESULT_callout_volatility.md`` §2.3 recovered the
same two constants independently from 27,076 board observations (median offset 7.30e13 on the
newer config, median K 3.219e25) -- this module re-derives them per mint from the curve's own
opening balance rather than assuming the median.

For a MIGRATED coin the counterparty is a PumpSwap pool holding both legs, so the pool's WSOL
vault delta *is* the SOL leg and no identity is needed. Both routes are used; every trade row
records which one priced it.

COMMANDS
--------
Run in order. Each stage writes parquet/json under ``studies/data/pvp_vamps/`` and later
stages read earlier ones, so only ``flow`` is expensive.

``flow``       per-(mint, wallet, tx) trade tape with exact SOL, for the cohort    (~65 s)
``rotation``   the rotation cohort: wallets active on >=k of the last N hot coins  (~30 s)
``panel``      coin x 30-minute buckets, PvP features (causal) and forward outcomes (~35 s)
``classify``   PvP-state vs the ``recycled_30m`` baseline; temporal split, nulls, FDR
``arena``      eta components conditional on PvP state; the LP window and how it ends
``transition`` PvP-transition lead time before the price break; the operator's four coins
``vamp``       directed host->clone drain vs BOTH nulls; drain vs host deterioration
``regimes``    five OTHER readings of "PvP" -- market-wide, lifecycle, onset, the wiggle
               flip, and the pack's own balance. Two of them change the conclusions.
``burst``      the latency-decay curve of a flow-burst entry, over the whole corpus,
               against a naive control AND an active-minute control
``opnow``      score the operator's four coins on TODAY's live flow, not the corpus edge
``duel-fetch`` page a same-name family's wallet-level trade tapes from pump.fun
``duel``       reconstruct one duel's cascade at 1 s resolution and price its latencies

Invocation is always ``uv run --group research python -m studies.pvp_vamps <cmd>``.
Nothing here touches the network, signs anything, or reads the live sentinel's state.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "studies" / "data" / "operator_crime" / "ledger"
COINS = REPO_ROOT / "studies" / "data" / "operator_crime" / "coins.parquet"
OUT = REPO_ROOT / "studies" / "data" / "pvp_vamps"

WSOL = "So11111111111111111111111111111111111111112"

# Virtual reserves, shared by both curve configurations in this corpus. Independently
# recovered from chain in RESULT_callout_volatility.md §2.3 (median k = 3.219e25, and the
# offset that implies given each config's opening real balance).
V_TOK_VIRT = 1.073e15  # raw token units
V_SOL_VIRT = 3.0e10  # lamports (30 SOL)
K_CURVE = V_SOL_VIRT * V_TOK_VIRT  # 3.219e25
LAMPORTS = 1e9

# Cohort gate: coins whose counterparty was touched at least this many times. Below this a
# coin has no crowd and "is it PvP" is not a well-posed question.
MIN_TOUCHES = 100

# The operator's four cluster coins (shitcoims_cluster/pools.py, resolved on chain there).
OPERATOR_COINS = {
    "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
}


def _duck(threads: int = 6, memory: str = "16GB"):
    try:
        import duckdb
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "needs duckdb: `uv run --group research`. The ledger is 301M rows of parquet."
        ) from None
    con = duckdb.connect(config={"threads": threads})
    con.execute(f"SET memory_limit='{memory}'")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con.execute(f"SET temp_directory='{tmp}'")
    con.execute("SET preserve_insertion_order=false")
    return con


def _ledger_glob() -> str:
    return f"read_parquet('{LEDGER}/**/*.parquet', hive_partitioning=true)"


# ---------------------------------------------------------------------------------------
# stage: flow
# ---------------------------------------------------------------------------------------


def cmd_flow(args: argparse.Namespace) -> int:
    """Build the per-(mint, wallet, transaction) trade tape with exact SOL legs.

    The counterparty is identified per mint as an owner touching at least 20% of that mint's
    transactions (and at least 10 of them) -- on a bonding-curve coin that is the curve and
    nothing else; on a migrated coin it admits both the curve and the PumpSwap pool, which is
    what makes a coin that migrated mid-window priceable on both sides of the event.

    Transactions where BOTH legs are counterparties are dropped: that is the migration
    transfer, and pricing it as a trade would book the entire remaining curve supply as one
    enormous buy at a near-zero price.

    Mints and owners are dictionary-encoded to int32 in the first pass. That is not cosmetic:
    the un-encoded slice is 40M rows of two base58 strings and spills tens of gigabytes to
    temp on a 16 GB budget; encoded it is a gigabyte and stays in memory.
    """
    con = _duck(args.threads, args.memory)
    t0 = time.time()

    con.execute(
        f"""
        CREATE OR REPLACE TABLE cohort AS
        SELECT mint, birth_time, graduated, peak_mcap_sol, lifetime_s, curve_touches,
               drawdown_from_peak, dev_buy_share, n_snipers, t_peak, t_last
        FROM read_parquet('{COINS}')
        WHERE curve_touches >= {args.min_touches}
        """
    )
    n_cohort = con.execute("SELECT count(*) FROM cohort").fetchone()[0]
    print(f"[flow] cohort: {n_cohort} coins (curve_touches >= {args.min_touches})", flush=True)

    # Also carry the operator's four coins, which were born before the corpus window and so
    # do not appear in coins.parquet at all. They are flagged and never enter the cohort
    # statistics -- the transition stage scores them, it does not fit on them.
    op = ",".join(f"'{m}'" for m in OPERATOR_COINS.values())
    con.execute(
        f"""
        CREATE OR REPLACE TABLE study_mints AS
        SELECT mint, false AS operator_coin FROM cohort
        UNION ALL
        SELECT mint, true FROM (SELECT unnest([{op}]) AS mint)
        WHERE mint NOT IN (SELECT mint FROM cohort)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE mints AS
        SELECT mint, operator_coin, (row_number() OVER (ORDER BY mint))::INTEGER AS mint_id
        FROM study_mints
        """
    )

    print("[flow] pass 1: slicing ledger to study mints, encoding ids ...", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE led AS
        SELECT m.mint_id, l.owner, l.block_slot::INTEGER AS slot, l.tx_index::SMALLINT AS txi,
               any_value(l.block_time)::INTEGER AS t, sum(l.delta_raw) AS d
        FROM {_ledger_glob()} l
        JOIN mints m ON m.mint = l.mint
        GROUP BY 1, 2, 3, 4
        HAVING sum(l.delta_raw) != 0
        """
    )
    print(f"[flow]   {con.execute('SELECT count(*) FROM led').fetchone()[0]:,} legs"
          f"  ({time.time() - t0:.0f}s)", flush=True)

    con.execute(
        """
        CREATE OR REPLACE TABLE owners AS
        SELECT owner, (row_number() OVER (ORDER BY owner))::INTEGER AS owner_id
        FROM (SELECT DISTINCT owner FROM led)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE leg AS
        SELECT l.mint_id, o.owner_id, l.slot, l.txi, l.t, l.d
        FROM led l JOIN owners o USING (owner)
        """
    )
    con.execute("DROP TABLE led")
    print(f"[flow]   {con.execute('SELECT count(*) FROM owners').fetchone()[0]:,} distinct owners"
          f"  ({time.time() - t0:.0f}s)", flush=True)

    # --- counterparty identification ----------------------------------------------------
    con.execute(
        """
        CREATE OR REPLACE TABLE mint_tx AS
        SELECT mint_id, count(*) AS n_tx
        FROM (SELECT DISTINCT mint_id, slot, txi FROM leg) GROUP BY 1
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE cp AS
        SELECT o.mint_id, o.owner_id, o.n_tx
        FROM (SELECT mint_id, owner_id, count(*) AS n_tx FROM leg GROUP BY 1, 2) o
        JOIN mint_tx m USING (mint_id)
        WHERE o.n_tx >= 10 AND o.n_tx >= 0.20 * m.n_tx
        """
    )
    ncp = con.execute("SELECT count(*) FROM cp").fetchone()[0]
    nmulti = con.execute(
        "SELECT count(*) FROM (SELECT mint_id FROM cp GROUP BY 1 HAVING count(*) > 1)"
    ).fetchone()[0]
    print(f"[flow]   counterparties: {ncp:,} (mint,owner) pairs; {nmulti:,} mints with >1",
          flush=True)

    # --- counterparty balance path ------------------------------------------------------
    con.execute(
        """
        CREATE OR REPLACE TABLE cppath AS
        SELECT l.mint_id, l.owner_id, l.slot, l.txi, l.d AS cp_delta,
               sum(l.d) OVER (PARTITION BY l.mint_id, l.owner_id ORDER BY l.slot, l.txi
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bal_after
        FROM leg l SEMI JOIN cp c ON c.mint_id = l.mint_id AND c.owner_id = l.owner_id
        """
    )
    # One row per (mint, transaction): the counterparty leg. n_cp_legs > 1 is the migration
    # transfer (curve -> pool), never a trade.
    con.execute(
        """
        CREATE OR REPLACE TABLE txcp0 AS
        SELECT mint_id, slot, txi, count(*) AS n_cp_legs,
               any_value(owner_id) AS cp_owner, any_value(cp_delta) AS cp_delta,
               any_value(bal_after) AS bal_after
        FROM cppath GROUP BY 1, 2, 3
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE txcp AS
        SELECT *, row_number() OVER (PARTITION BY mint_id, cp_owner ORDER BY slot, txi) AS rn
        FROM txcp0
        """
    )
    # THE CREATE TRANSACTION, and the two coupled bugs it caused.
    #
    # A pump.fun create writes the whole supply into the curve AND executes the dev buy in
    # one transaction, so the curve's NET delta on that row is `supply - dev_buy`, not
    # `supply`. Two things went wrong downstream of taking that net at face value:
    #
    #   1. `bal0 = max(cumsum)` therefore understates the opening balance by however much of
    #      the dev buy is never sold back, which shifts OFFSET and biases every price on the
    #      coin. The smear is visible directly: bal0/1e15 piles up at 1.0000 and then trails
    #      0.9999, 0.9998, 0.9997 ... one bucket per dev-buy size.
    #   2. On that first row `bal_before = bal_after - cp_delta` evaluates to ~0, so
    #      `v_tok_before` is the bare offset, the implied SOL leg comes out large and
    #      NEGATIVE against a positive token leg, and the sign filter silently DELETED every
    #      dev buy in the corpus.
    #
    # Both are fixed by reconstructing the gross opening balance from the transaction's own
    # legs -- bal0_gross = bal_after(first tx) + sum(trader deltas in that tx) -- and using
    # v_tok_before = V_TOK_VIRT on the create, which is what it is by definition.
    #
    # The check that caught this is the GRADUATION CLIFF, and it is worth stating because it
    # is the only external anchor this pricing has: pump.fun completes a curve at exactly
    # 85 SOL raised (v_tok 1.073e15 -> 2.799e14, i.e. 793.1e6 tokens sold, which is the
    # classic config's sellable supply to the lamport), so the reconstructed raise has to be
    # a SPIKE at 85 and not a broad hump at 81. It was a broad hump at 81.
    con.execute(
        """
        CREATE OR REPLACE TABLE txtr AS
        SELECT l.mint_id, l.slot, l.txi, sum(l.d) AS tr_net, sum(abs(l.d)) AS tx_abs
        FROM leg l ANTI JOIN cp c ON c.mint_id = l.mint_id AND c.owner_id = l.owner_id
        GROUP BY 1, 2, 3
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE cpparam AS
        SELECT p.mint_id, p.owner_id, p.bal_max,
               CASE WHEN g.bal0_gross >= 0.5 * VVV THEN g.bal0_gross
                    ELSE p.bal_max END AS bal0,
               (g.bal0_gross >= 0.5 * VVV) AS create_seen
        FROM (SELECT mint_id, owner_id, max(bal_after) AS bal_max
              FROM cppath GROUP BY 1, 2) p
        LEFT JOIN (
            SELECT x.mint_id, x.cp_owner AS owner_id,
                   any_value(x.bal_after + coalesce(t.tr_net, 0)) AS bal0_gross
            FROM txcp x LEFT JOIN txtr t USING (mint_id, slot, txi)
            WHERE x.rn = 1 GROUP BY 1, 2
        ) g USING (mint_id, owner_id)
        """.replace("VVV", str(V_TOK_VIRT))
    )
    seen = con.execute("SELECT sum(create_seen::int), count(*) FROM cpparam").fetchone()
    print(f"[flow]   opening balance reconstructed from the create tx for "
          f"{seen[0]:,} of {seen[1]:,} (mint, counterparty) pairs", flush=True)

    # --- the WSOL leg, for migrated counterparties only ----------------------------------
    # Restricted to transactions of mints that ever migrated: scanning the whole 301M-row
    # ledger for WSOL against every study transaction is a second full pass for 2.5% of coins.
    con.execute(
        """
        CREATE OR REPLACE TABLE grad_tx AS
        SELECT DISTINCT x.slot, x.txi
        FROM txcp x JOIN mints m USING (mint_id)
        LEFT JOIN cohort c ON c.mint = m.mint
        WHERE coalesce(c.graduated, true)
        """
    )
    print(f"[flow]   migrated-coin transactions: "
          f"{con.execute('SELECT count(*) FROM grad_tx').fetchone()[0]:,}", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE wsol AS
        SELECT l.block_slot::INTEGER AS slot, l.tx_index::SMALLINT AS txi, o.owner_id,
               sum(l.delta_raw) AS wsol_delta
        FROM {_ledger_glob()} l
        JOIN owners o ON o.owner = l.owner
        SEMI JOIN grad_tx g ON g.slot = l.block_slot AND g.txi = l.tx_index
        WHERE l.mint = '{WSOL}'
        GROUP BY 1, 2, 3
        """
    )
    print(f"[flow]   wsol legs: {con.execute('SELECT count(*) FROM wsol').fetchone()[0]:,}"
          f"  ({time.time() - t0:.0f}s)", flush=True)

    # --- trader legs, priced ------------------------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE trades AS
        WITH trader AS (
            SELECT l.* FROM leg l
            ANTI JOIN cp c ON c.mint_id = l.mint_id AND c.owner_id = l.owner_id
        ), j AS (
            SELECT t.mint_id, t.owner_id, t.slot, t.txi, t.t, t.d,
                   x.cp_owner, x.cp_delta, x.bal_after, p.bal0, w.wsol_delta, x.rn,
                   sum(abs(t.d)) OVER (PARTITION BY t.mint_id, t.slot, t.txi) AS tx_abs
            FROM trader t
            JOIN txcp x USING (mint_id, slot, txi)
            JOIN cpparam p ON p.mint_id = x.mint_id AND p.owner_id = x.cp_owner
            LEFT JOIN wsol w ON w.slot = t.slot AND w.txi = t.txi AND w.owner_id = x.cp_owner
            WHERE x.n_cp_legs = 1
        )
        SELECT mint_id, owner_id, slot, txi, t, d AS delta_raw,
               bal_after AS cp_bal_after,
               ({V_TOK_VIRT} - bal0) AS offset_raw,
               CASE WHEN wsol_delta IS NOT NULL THEN 'pool' ELSE 'curve' END AS route,
               CASE
                 WHEN wsol_delta IS NOT NULL
                   THEN (wsol_delta / {LAMPORTS}) * (abs(d) / nullif(tx_abs, 0))
                 ELSE ({K_CURVE} * (1.0 / nullif(bal_after + ({V_TOK_VIRT} - bal0), 0)
                                  - 1.0 / nullif(CASE WHEN rn = 1 THEN {V_TOK_VIRT}
                                                      ELSE bal_after - cp_delta
                                                           + ({V_TOK_VIRT} - bal0) END, 0))
                       / {LAMPORTS}) * (abs(d) / nullif(tx_abs, 0))
               END AS sol
        FROM j
        """
    )
    n_tr = con.execute("SELECT count(*) FROM trades").fetchone()[0]
    bad = con.execute(
        "SELECT count(*) FROM trades WHERE sol IS NULL OR sign(sol) != sign(delta_raw)"
    ).fetchone()[0]
    print(f"[flow]   trade legs: {n_tr:,}; dropped for null/sign disagreement: {bad:,}"
          f" ({100.0 * bad / max(n_tr, 1):.3f}%)  ({time.time() - t0:.0f}s)", flush=True)

    for name, sql in (
        ("mints", "SELECT mint, mint_id, operator_coin FROM mints"),
        ("owners", "SELECT owner, owner_id FROM owners"),
        ("cohort", "SELECT * FROM cohort"),
        (
            "counterparties",
            "SELECT c.mint_id, c.owner_id, c.n_tx, p.bal0, p.bal_max, p.create_seen "
            "FROM cp c JOIN cpparam p USING (mint_id, owner_id)",
        ),
    ):
        con.execute(
            f"COPY ({sql}) TO '{OUT / (name + '.parquet')}' "
            f"(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

    out = OUT / "trades.parquet"
    con.execute(
        f"""
        COPY (SELECT mint_id, owner_id, t, slot, txi, delta_raw, sol, cp_bal_after,
                     offset_raw, route
              FROM trades
              WHERE sol IS NOT NULL AND abs(sol) < 1e6 AND sign(sol) = sign(delta_raw)
                AND abs(delta_raw) < 0.30 * {V_TOK_VIRT}
              ORDER BY mint_id, slot, txi)
        TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
        """
    )
    print(f"[flow] wrote {out}  ({time.time() - t0:.0f}s)", flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: rotation -- the mercenary cohort, built explicitly
# ---------------------------------------------------------------------------------------


def _trades_rel(con) -> str:
    con.execute(
        f"""
        CREATE OR REPLACE VIEW tp AS
        SELECT mint_id, owner_id, t, slot, txi, delta_raw, sol, route, cp_bal_after,
               offset_raw,
               CASE WHEN route = 'curve'
                    THEN ln({K_CURVE}) - 2 * ln(nullif(greatest(cp_bal_after + offset_raw, 0), 0))
                         - ln({LAMPORTS})
                    ELSE ln(nullif(abs(sol), 0) / nullif(abs(delta_raw), 0)) END AS log_px
        FROM read_parquet('{OUT / 'trades.parquet'}')
        """
    )
    return "tp"


def cmd_rotation(args: argparse.Namespace) -> int:
    """Build the rotation cohort: wallets active on >= k of the recent hot coins.

    Everything is strictly trailing. Membership at hour h is decided by hours [h-N, h-1], so
    a coin's own crowd never votes itself into the cohort that is then used to describe it.
    """
    con = _duck(args.threads, args.memory)
    T = _trades_rel(con)
    t0 = time.time()

    con.execute(
        f"""
        CREATE OR REPLACE TABLE mh AS
        SELECT mint_id, (t / 3600)::INTEGER AS h,
               sum(CASE WHEN sol > 0 THEN sol ELSE 0 END) AS buy_sol,
               count(DISTINCT owner_id) AS traders
        FROM {T} GROUP BY 1, 2
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE hot AS
        SELECT mint_id, h FROM (
            SELECT mint_id, h, row_number() OVER (PARTITION BY h ORDER BY buy_sol DESC) AS rk
            FROM mh
        ) WHERE rk <= {args.hot}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE wh AS
        SELECT DISTINCT p.owner_id, p.mint_id, (p.t / 3600)::INTEGER AS h
        FROM {T} p SEMI JOIN hot g ON g.mint_id = p.mint_id AND g.h = (p.t / 3600)::INTEGER
        """
    )
    hours = con.execute("SELECT min(h), max(h) FROM mh").fetchone()
    print(f"[rotation] hours {hours[0]}..{hours[1]}; hot set = top {args.hot}/hour", flush=True)

    # R(h) = wallets on >= k distinct hot coins over hours [h-N, h-1]
    con.execute(
        f"""
        CREATE OR REPLACE TABLE rot AS
        SELECT a.h AS h, w.owner_id
        FROM (SELECT DISTINCT h FROM mh) a
        JOIN wh w ON w.h BETWEEN a.h - {args.lookback} AND a.h - 1
        GROUP BY 1, 2
        HAVING count(DISTINCT w.mint_id) >= {args.k}
        """
    )
    con.execute(f"COPY (SELECT * FROM rot) TO '{OUT / 'rotation.parquet'}' (FORMAT PARQUET)")

    size = con.execute(
        "SELECT h, count(*) n FROM rot GROUP BY 1 ORDER BY 1"
    ).df()
    jaccard = {}
    for lag in (1, 6, 24):
        row = con.execute(
            f"""
            WITH pairs AS (
                SELECT x.h,
                       count(*) FILTER (WHERE y.owner_id IS NOT NULL) AS inter,
                       count(*) AS nx
                FROM rot x LEFT JOIN rot y ON y.h = x.h + {lag} AND y.owner_id = x.owner_id
                WHERE x.h + {lag} <= (SELECT max(h) FROM rot)
                GROUP BY 1
            ), sz AS (SELECT h, count(*) AS n FROM rot GROUP BY 1)
            SELECT median(p.inter::DOUBLE / nullif(p.nx + s.n - p.inter, 0))
            FROM pairs p JOIN sz s ON s.h = p.h + {lag}
            """
        ).fetchone()[0]
        jaccard[lag] = float(row) if row is not None else float("nan")

    share = con.execute(
        f"""
        SELECT sum(CASE WHEN r.owner_id IS NOT NULL THEN p.sol ELSE 0 END) / sum(p.sol)
                   AS rotation_buy_share,
               count(DISTINCT p.owner_id) AS wallets
        FROM {T} p
        LEFT JOIN rot r ON r.owner_id = p.owner_id AND r.h = (p.t / 3600)::INTEGER
        WHERE p.sol > 0
        """
    ).fetchone()

    stats = {
        "hot_per_hour": args.hot,
        "k": args.k,
        "lookback_hours": args.lookback,
        "hours": int(len(size)),
        "cohort_size_median": float(size["n"].median()),
        "cohort_size_p10": float(size["n"].quantile(0.10)),
        "cohort_size_p90": float(size["n"].quantile(0.90)),
        "distinct_rotation_wallets": int(
            con.execute("SELECT count(DISTINCT owner_id) FROM rot").fetchone()[0]
        ),
        "distinct_wallets_total": int(share[1]),
        "rotation_buy_share_all_corpus": float(share[0]),
    }
    stats["jaccard_by_lag_hours"] = jaccard
    (OUT / "rotation_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1), flush=True)
    print(f"[rotation] done ({time.time() - t0:.0f}s)", flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: panel -- coin x 30-minute bucket, causal PvP features and forward outcomes
# ---------------------------------------------------------------------------------------

BUCKET = 1800
EMBARGO = 60  # matches RESULT_caller_wallets' recycled_30m construction exactly


def cmd_panel(args: argparse.Namespace) -> int:
    con = _duck(args.threads, args.memory)
    T = _trades_rel(con)
    t0 = time.time()
    corpus_end = con.execute(f"SELECT max(t) FROM {T}").fetchone()[0]
    print(f"[panel] corpus end {corpus_end}", flush=True)

    con.execute(f"CREATE OR REPLACE TABLE rot AS SELECT * FROM read_parquet('{OUT / 'rotation.parquet'}')")

    # First time each wallet ever touched each coin -- the "new money" denominator.
    con.execute(
        f"CREATE OR REPLACE TABLE firstseen AS "
        f"SELECT mint_id, owner_id, min(t) AS t0 FROM {T} GROUP BY 1, 2"
    )
    # Per-mint life, for the survival outcome.
    con.execute(
        f"CREATE OR REPLACE TABLE life AS "
        f"SELECT mint_id, min(t) AS t_first, max(t) AS t_last, count(*) AS n FROM {T} GROUP BY 1"
    )

    # ---- per (mint, bucket, wallet) -------------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE bw AS
        SELECT p.mint_id, (p.t / {BUCKET})::INTEGER * {BUCKET} AS b, p.owner_id,
               sum(CASE WHEN p.delta_raw > 0 AND p.t < (p.t / {BUCKET})::INTEGER * {BUCKET}
                            + {BUCKET - EMBARGO} THEN p.delta_raw ELSE 0 END) AS early_buy_tok,
               sum(CASE WHEN p.delta_raw > 0 THEN p.delta_raw ELSE 0 END) AS buy_tok,
               sum(CASE WHEN p.delta_raw < 0 THEN -p.delta_raw ELSE 0 END) AS sell_tok,
               sum(CASE WHEN p.sol > 0 THEN p.sol ELSE 0 END) AS buy_sol,
               sum(CASE WHEN p.sol < 0 THEN -p.sol ELSE 0 END) AS sell_sol,
               min(CASE WHEN p.delta_raw > 0 THEN p.t END) AS t_first_buy,
               max(CASE WHEN p.delta_raw < 0 THEN p.t END) AS t_last_sell,
               min(f.t0) AS t_first_ever,
               max(CASE WHEN r.owner_id IS NOT NULL THEN 1 ELSE 0 END) AS in_rotation,
               count(*) AS n_legs
        FROM {T} p
        JOIN firstseen f ON f.mint_id = p.mint_id AND f.owner_id = p.owner_id
        LEFT JOIN rot r ON r.owner_id = p.owner_id AND r.h = (p.t / 3600)::INTEGER
        GROUP BY 1, 2, 3
        """
    )
    print(f"[panel] bw rows {con.execute('SELECT count(*) FROM bw').fetchone()[0]:,}"
          f" ({time.time() - t0:.0f}s)", flush=True)

    # ---- per (mint, bucket) price / variance ----------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE mb_px AS
        WITH mm AS (
            SELECT mint_id, (t / 60)::INTEGER AS m, arg_max(log_px, (slot, txi)) AS px,
                   arg_max(cp_bal_after, (slot, txi)) AS bal
            FROM {T} GROUP BY 1, 2
        ), d AS (
            SELECT mint_id, m, px, bal,
                   px - lag(px) OVER (PARTITION BY mint_id ORDER BY m) AS dpx,
                   m - lag(m) OVER (PARTITION BY mint_id ORDER BY m) AS dm
            FROM mm
        )
        SELECT mint_id, (m * 60 / {BUCKET})::INTEGER * {BUCKET} AS b,
               sum(CASE WHEN dm = 1 THEN dpx * dpx ELSE 0 END) AS rv,
               count(*) AS active_minutes,
               arg_max(px, m) AS px_end, arg_min(px, m) AS px_start,
               arg_max(bal, m) AS bal_end
        FROM d GROUP BY 1, 2
        """
    )

    # ---- per (mint, bucket) features -------------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE mb AS
        SELECT w.mint_id, w.b,
               sum(w.buy_sol) AS buy_sol, sum(w.sell_sol) AS sell_sol,
               sum(w.buy_sol + w.sell_sol) AS gross_sol,
               sum(w.buy_tok) AS buy_tok, sum(w.sell_tok) AS sell_tok,
               count(*) AS n_wallets,
               count(*) FILTER (WHERE w.buy_sol > 0) AS n_buyers,
               sum(w.n_legs) AS n_trades,
               -- recycled_30m, RESULT_caller_wallets' definition, token-weighted
               coalesce(sum(w.sell_tok) FILTER (WHERE w.early_buy_tok > 0), 0)
                   / nullif(sum(w.early_buy_tok), 0) AS recycled_30m,
               -- same thing SOL-weighted
               coalesce(sum(w.sell_sol) FILTER (WHERE w.early_buy_tok > 0), 0)
                   / nullif(sum(w.buy_sol) FILTER (WHERE w.early_buy_tok > 0), 0)
                   AS recycled_sol,
               -- share of buying done by the rotation cohort
               coalesce(sum(w.buy_sol) FILTER (WHERE w.in_rotation = 1), 0)
                   / nullif(sum(w.buy_sol), 0) AS rotation_share,
               -- share of buying done by wallets touching this coin for the first time
               coalesce(sum(w.buy_sol) FILTER (WHERE w.t_first_ever >= w.b), 0)
                   / nullif(sum(w.buy_sol), 0) AS new_money_share,
               -- share of buying by wallets that left the bucket flat
               coalesce(sum(w.buy_sol) FILTER (WHERE w.sell_tok >= 0.9 * w.buy_tok
                                               AND w.buy_tok > 0), 0)
                   / nullif(sum(w.buy_sol), 0) AS roundtrip_frac,
               median(w.t_last_sell - w.t_first_buy)
                   FILTER (WHERE w.t_last_sell IS NOT NULL AND w.t_first_buy IS NOT NULL
                                 AND w.t_last_sell >= w.t_first_buy) AS hold_med_s,
               count(*) FILTER (WHERE w.t_last_sell IS NOT NULL AND w.t_first_buy IS NOT NULL)
                   AS n_roundtrip
        FROM bw w GROUP BY 1, 2
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE panel0 AS
        SELECT m.*, x.rv, x.active_minutes, x.px_end, x.px_start, x.bal_end,
               greatest(({V_TOK_VIRT} - coalesce(t.offset_raw, 7.30e13)) - x.bal_end, 0)
                   AS circulating_raw,
               greatest(exp(x.px_end) * x.bal_end, 0) AS pool_sol,
               coalesce(t.offset_raw, 7.30e13) AS offset_raw
        FROM mb m
        JOIN mb_px x USING (mint_id, b)
        LEFT JOIN (SELECT mint_id, any_value(offset_raw) AS offset_raw
                   FROM {T} WHERE route = 'curve' GROUP BY 1) t USING (mint_id)
        """
    )
    print(f"[panel] panel0 rows {con.execute('SELECT count(*) FROM panel0').fetchone()[0]:,}"
          f" ({time.time() - t0:.0f}s)", flush=True)

    # ---- forward outcomes ------------------------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE fwd AS
        SELECT p.mint_id, p.b,
               sum(q.gross_sol) FILTER (WHERE q.b > p.b AND q.b <= p.b + 3600) AS vol_1h,
               sum(q.gross_sol) FILTER (WHERE q.b > p.b AND q.b <= p.b + 14400) AS vol_4h,
               sum(q.rv)       FILTER (WHERE q.b > p.b AND q.b <= p.b + 3600) AS rv_1h,
               sum(q.rv)       FILTER (WHERE q.b > p.b AND q.b <= p.b + 14400) AS rv_4h,
               sum(q.active_minutes) FILTER (WHERE q.b > p.b AND q.b <= p.b + 3600)
                   AS act_1h,
               max(q.px_end)   FILTER (WHERE q.b > p.b AND q.b <= p.b + 3600) AS px_hi_1h,
               arg_max(q.px_end, q.b) FILTER (WHERE q.b > p.b AND q.b <= p.b + 3600)
                   AS px_1h,
               arg_max(q.px_end, q.b) FILTER (WHERE q.b > p.b AND q.b <= p.b + 14400)
                   AS px_4h
        FROM panel0 p LEFT JOIN panel0 q
          ON q.mint_id = p.mint_id AND q.b > p.b AND q.b <= p.b + 14400
        GROUP BY 1, 2
        """
    )

    con.execute(
        f"CREATE OR REPLACE TABLE mints_t AS SELECT * FROM read_parquet('{OUT / 'mints.parquet'}')"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE cohort_t AS SELECT * FROM read_parquet('{OUT / 'cohort.parquet'}')"
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE panel AS
        SELECT p.mint_id, mn.mint, mn.operator_coin, p.b,
               c.birth_time, c.graduated, c.peak_mcap_sol, c.dev_buy_share, c.n_snipers,
               (p.b - c.birth_time) AS age_s,
               p.recycled_30m, p.recycled_sol, p.rotation_share, p.new_money_share,
               p.roundtrip_frac, p.hold_med_s, p.n_roundtrip,
               (p.buy_tok + p.sell_tok)
                   / nullif(CASE WHEN p.circulating_raw > 1e13 THEN p.circulating_raw END, 0)
                   AS float_turnover,
               (p.buy_tok - p.sell_tok) / nullif(p.buy_tok + p.sell_tok, 0) AS absorption,
               p.buy_sol, p.sell_sol, p.gross_sol, p.n_wallets, p.n_buyers, p.n_trades,
               p.rv, p.active_minutes, p.px_end, p.px_start, p.pool_sol, p.circulating_raw,
               exp(p.px_end) * 1e15 AS mcap_sol,
               l.t_last, {corpus_end} AS corpus_end,
               (l.t_last <= p.b + {BUCKET} + 3600) AS dead_1h,
               (l.t_last <= p.b + {BUCKET} + 14400) AS dead_4h,
               (l.t_last - (p.b + {BUCKET})) AS surv_s,
               (l.t_last >= {corpus_end} - 600) AS surv_censored,
               coalesce(f.vol_1h, 0) AS vol_1h, coalesce(f.vol_4h, 0) AS vol_4h,
               coalesce(f.rv_1h, 0) AS rv_1h, coalesce(f.rv_4h, 0) AS rv_4h,
               coalesce(f.act_1h, 0) AS act_1h,
               f.px_1h - p.px_end AS ret_1h, f.px_4h - p.px_end AS ret_4h,
               f.px_hi_1h - p.px_end AS maxret_1h
        FROM panel0 p
        JOIN mints_t mn USING (mint_id)
        LEFT JOIN cohort_t c ON c.mint = mn.mint
        JOIN life l USING (mint_id)
        LEFT JOIN fwd f USING (mint_id, b)
        WHERE p.n_wallets >= {args.min_wallets}
        """
    )
    n = con.execute("SELECT count(*) FROM panel").fetchone()[0]
    nm = con.execute("SELECT count(DISTINCT mint_id) FROM panel").fetchone()[0]
    print(f"[panel] {n:,} rows / {nm:,} mints  ({time.time() - t0:.0f}s)", flush=True)
    con.execute(f"COPY (SELECT * FROM panel) TO '{OUT / 'panel.parquet'}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    return 0


# ---------------------------------------------------------------------------------------
# stage: classify -- is PvP a state, and does it beat recycled_30m?
# ---------------------------------------------------------------------------------------

# The folk definition of PvP, one column per clause. `recycled_30m` is listed separately
# everywhere below because it is the INCUMBENT (RESULT_caller_wallets.md, AUC 0.824 alone at
# 8 h) and the question is what the other five buy over it.
PVP_COLS = (
    "rotation_share",  # mercenary rotation: buying from wallets on >=3 recent hot coins
    "new_money_share",  # outside money entering (INVERSE of PvP)
    "roundtrip_frac",  # everybody exit-planning: buyers who leave the window flat
    "log_hold",  # short holds
    "log_turnover",  # volume without accumulation: float changing hands
)
BASELINE_COL = "recycled_30m"
FREE_COLS = ("log_mcap", "log_age", "log_gross_sol", "log_wallets", "absorption")


def _load_panel(con, *, min_wallets: int = 20):
    import numpy as np

    df = con.execute(
        f"""
        SELECT * FROM read_parquet('{OUT / 'panel.parquet'}')
        WHERE NOT operator_coin AND birth_time IS NOT NULL
          AND n_wallets >= {min_wallets} AND recycled_30m IS NOT NULL
        """
    ).df()
    df["recycled_30m"] = df["recycled_30m"].clip(0, 3)
    df["log_hold"] = np.log1p(df["hold_med_s"].fillna(BUCKET))
    df["log_turnover"] = np.log1p(df["float_turnover"].fillna(0.0).clip(0, 1e4))
    df["log_mcap"] = np.log(df["mcap_sol"].clip(lower=1e-6))
    df["log_age"] = np.log1p(df["age_s"].clip(lower=0))
    df["log_gross_sol"] = np.log1p(df["gross_sol"].clip(lower=0))
    df["log_wallets"] = np.log1p(df["n_wallets"])
    for c in ("rotation_share", "new_money_share", "roundtrip_frac"):
        df[c] = df[c].fillna(0.0)
    return df


def _auc(y, s):
    from sklearn.metrics import roc_auc_score

    y = list(y)
    if len(set(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, s))


def _fit_score(tr, te, cols, label, seed=0):
    """Gradient-boosted trees on tabular features -- PROGRAM.md §3.4's mandated baseline,
    and the class MELT measured as the winner on this problem. No class weighting: MELT's
    weighted BCE decalibrates the probabilities an EV decision needs (§1.3)."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier

    X, y = tr[list(cols)].to_numpy(float), tr[label].to_numpy(int)
    Xt, yt = te[list(cols)].to_numpy(float), te[label].to_numpy(int)
    m = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.06, max_leaf_nodes=15,
        min_samples_leaf=50, l2_regularization=1.0, random_state=seed,
    )
    m.fit(X, y)
    p = m.predict_proba(Xt)[:, 1]
    base = float(y.mean())
    return p, yt, base


def _bits(y, p, base):
    import numpy as np

    p = np.clip(p, 1e-6, 1 - 1e-6)
    ll = -(y * np.log2(p) + (1 - y) * np.log2(1 - p)).mean()
    b = np.clip(base, 1e-6, 1 - 1e-6)
    ll0 = -(y * np.log2(b) + (1 - y) * np.log2(1 - b)).mean()
    return float(ll0 - ll)


def _cluster_boot_ci(y, s, groups, draws=400, seed=0):
    """Mint-clustered bootstrap CI on AUC. A coin contributes many buckets; resampling rows
    would understate the interval by roughly the buckets-per-coin factor."""
    import numpy as np

    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    s = np.asarray(s)
    g = np.asarray(groups)
    uniq = np.unique(g)
    idx = {u: np.flatnonzero(g == u) for u in uniq}
    out = []
    for _ in range(draws):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        rows = np.concatenate([idx[u] for u in pick])
        a = _auc(y[rows], s[rows])
        if a == a:
            out.append(a)
    if not out:
        return (float("nan"), float("nan"))
    return (float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975)))


def _count_modes(x, bandwidths=(0.15, 0.25, 0.40)) -> dict:
    """Local maxima of a Gaussian KDE of `x`, at several bandwidths.

    A "state" in the operator's sense is a mode. A score that is merely skewed is a gradient
    with a busy tail, and the two are worth distinguishing before anybody writes a threshold.

    `bw_method` in scipy is a SCALE FACTOR on the sample standard deviation, not an absolute
    bandwidth. The first version passed 0.02-0.05 against an sd of ~0.12, i.e. a bandwidth of
    0.0024, and duly reported 39 "modes" -- which were sampling noise, and which flipped the
    verdict to STATE. The bandwidths here are chosen so the finest is still wider than the
    bin noise.
    """
    import numpy as np
    from scipy.stats import gaussian_kde

    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    grid = np.linspace(x.min(), x.max(), 512)
    out = {}
    for bw in bandwidths:
        k = gaussian_kde(x, bw_method=bw)
        d = k(grid)
        peaks = int(np.sum((d[1:-1] > d[:-2]) & (d[1:-1] > d[2:])))
        out[str(bw)] = peaks
    return out


def _by_fdr(pvals, q=0.10):
    """Benjamini-Yekutieli. The cells are nested windows and overlapping column sets of one
    tape, so BH's independence assumption is not available (RESULT_callout_volatility §3)."""
    import numpy as np

    p = np.asarray(pvals, float)
    n = len(p)
    if n == 0:
        return np.zeros(0, bool)
    c = np.sum(1.0 / np.arange(1, n + 1))
    order = np.argsort(p)
    thresh = q * (np.arange(1, n + 1)) / (n * c)
    keep = p[order] <= thresh
    cut = np.flatnonzero(keep)
    out = np.zeros(n, bool)
    if len(cut):
        out[order[: cut[-1] + 1]] = True
    return out


def cmd_classify(args: argparse.Namespace) -> int:
    import numpy as np
    from sklearn.metrics import average_precision_score

    con = _duck(args.threads, args.memory)
    df = _load_panel(con, min_wallets=args.min_wallets)
    print(f"[classify] {len(df):,} rows / {df.mint_id.nunique():,} mints", flush=True)

    # ---- temporal split on BIRTH time, so a coin never straddles ----------------------
    cut = float(np.quantile(df.birth_time, args.split))
    tr = df[df.birth_time <= cut].copy()
    te = df[df.birth_time > cut].copy()
    res: dict = {
        "rows": int(len(df)),
        "mints": int(df.mint_id.nunique()),
        "split_birth_time": cut,
        "train_rows": int(len(tr)),
        "test_rows": int(len(te)),
        "train_mints": int(tr.mint_id.nunique()),
        "test_mints": int(te.mint_id.nunique()),
    }

    # ---- is PvP a STATE or a GRADIENT? ------------------------------------------------
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import StandardScaler

    Z = StandardScaler().fit_transform(df[list(PVP_COLS)].to_numpy(float))
    bics = {}
    for k in (1, 2, 3):
        gm = GaussianMixture(k, covariance_type="full", random_state=0, n_init=2).fit(Z)
        bics[k] = float(gm.bic(Z))
    # composite score: mean of within-corpus quantile ranks, signed so high = more PvP
    signs = {"rotation_share": 1, "new_money_share": -1, "roundtrip_frac": 1,
             "log_hold": -1, "log_turnover": 1}
    ranks = np.zeros(len(df))
    for c, sgn in signs.items():
        r = df[c].rank(pct=True).to_numpy()
        ranks += r if sgn > 0 else (1.0 - r)
    df["pvp_score"] = ranks / len(signs)
    tr["pvp_score"] = df.loc[tr.index, "pvp_score"]
    te["pvp_score"] = df.loc[te.index, "pvp_score"]
    try:
        from scipy.stats import kurtosis, skew

        res["pvp_score_shape"] = {
            "skew": float(skew(df.pvp_score)),
            "excess_kurtosis": float(kurtosis(df.pvp_score)),
        }
    except Exception:
        pass
    res["gmm_bic"] = bics
    res["gmm_verdict"] = (
        "multimodal" if min(bics, key=bics.get) != 1 else "unimodal (a gradient, not a state)"
    )

    # ---- the model ladder --------------------------------------------------------------
    blocks = {
        "baseline recycled_30m alone": (BASELINE_COL,),
        "free only": FREE_COLS,
        "PvP block without recycled_30m": PVP_COLS,
        "PvP block + recycled_30m": PVP_COLS + (BASELINE_COL,),
        "free + recycled_30m": FREE_COLS + (BASELINE_COL,),
        "free + PvP block": FREE_COLS + PVP_COLS,
        "free + PvP + recycled_30m": FREE_COLS + PVP_COLS + (BASELINE_COL,),
    }
    labels = [c for c in ("dead_1h", "dead_4h") if c in df.columns]
    table = []
    pvals = []
    for label in labels:
        for name, cols in blocks.items():
            if len(cols) == 1:
                s = te[cols[0]].to_numpy(float)
                # a single column is used directly, oriented by its TRAIN-period sign
                sgn = 1.0 if _auc(tr[label], tr[cols[0]]) >= 0.5 else -1.0
                s = sgn * s
                base = float(tr[label].mean())
                p_hat = np.full(len(te), base)
                bits = float("nan")
            else:
                p_hat, _, base = _fit_score(tr, te, cols, label, seed=args.seed)
                s = p_hat
                bits = _bits(te[label].to_numpy(int), p_hat, base)
            y = te[label].to_numpy(int)
            auc = _auc(y, s)
            lo, hi = _cluster_boot_ci(y, s, te.mint_id.to_numpy(), draws=args.draws,
                                      seed=args.seed)
            table.append({
                "label": label, "block": name, "auc": auc, "ci": [lo, hi],
                "auprc": float(average_precision_score(y, s)) if len(set(y)) > 1 else None,
                "bits": bits, "base_rate_train": base, "base_rate_test": float(y.mean()),
            })
    res["ladder"] = table

    # ---- nulls -------------------------------------------------------------------------
    # (a) i.i.d. label shuffle and (b) label rotation, both on the strongest block.
    label = "dead_4h" if "dead_4h" in labels else labels[0]
    cols = FREE_COLS + PVP_COLS + (BASELINE_COL,)
    rng = np.random.default_rng(args.seed)
    p_real, y_real, base = _fit_score(tr, te, cols, label, seed=args.seed)
    real_auc = _auc(y_real, p_real)
    nulls = {}
    for kind in ("iid", "rotation"):
        aucs = []
        for d in range(args.null_draws):
            tr2 = tr.copy()
            if kind == "iid":
                tr2[label] = rng.permutation(tr[label].to_numpy())
            else:
                k = int(rng.integers(1, len(tr)))
                tr2[label] = np.roll(tr[label].to_numpy(), k)
            p2, y2, _ = _fit_score(tr2, te, cols, label, seed=args.seed + d)
            aucs.append(_auc(y2, p2))
        nulls[kind] = {"median": float(np.median(aucs)),
                       "p95": float(np.quantile(aucs, 0.95)),
                       "beat_real": int(sum(a >= real_auc for a in aucs)),
                       "draws": args.null_draws}
    # (c) THE null that matters: permute the PvP block across coins within (mcap, age) bins,
    #     so the marginal distribution of every PvP column and every free column is
    #     preserved and only the pairing is destroyed. RESULT_imitation_signal §5.6 is the
    #     precedent -- there, scrambling which coin got swarmed made the model BETTER.
    bins = (
        te["log_mcap"].rank(pct=True).mul(5).astype(int).astype(str)
        + "_"
        + te["log_age"].rank(pct=True).mul(5).astype(int).astype(str)
    )
    aucs = []
    for d in range(args.null_draws):
        te2 = te.copy()
        for _, idx in te2.groupby(bins.values).groups.items():
            idx = np.asarray(idx)
            perm = rng.permutation(idx)
            for c in PVP_COLS + (BASELINE_COL,):
                te2.loc[idx, c] = te.loc[perm, c].to_numpy()
        m_p, _, _ = _fit_score(tr, te2, cols, label, seed=args.seed)
        aucs.append(_auc(y_real, m_p))
    nulls["pvp_block_swap_matched"] = {
        "median": float(np.median(aucs)), "p95": float(np.quantile(aucs, 0.95)),
        "beat_real": int(sum(a >= real_auc for a in aucs)), "draws": args.null_draws,
    }
    # (d) known-EFFECT control, on a known-ZERO world. PROGRAM.md §3.12: a green zero-control
    #     certifies a constant-zero estimator exactly as readily as a working one, so the
    #     effect has to be planted into a world whose real signal has first been destroyed.
    #     Planting on top of the REAL labels (the first version of this) measures label noise,
    #     not recovery -- it made AUC go DOWN and would have been read as a broken estimator.
    tr3, te3 = tr.copy(), te.copy()
    for d_ in (tr3, te3):
        d_[label] = rng.permutation(d_[label].to_numpy())  # known-zero world
    p_zero, y_zero, _ = _fit_score(tr3, te3, cols, label, seed=args.seed)
    for d_ in (tr3, te3):
        q = d_["rotation_share"].rank(pct=True).to_numpy()
        flip = rng.random(len(d_)) < args.plant * q
        d_[label] = np.where(flip, 1, d_[label].to_numpy())
    p4, y4, _ = _fit_score(tr3, te3, cols, label, seed=args.seed)
    nulls["known_zero_world"] = {"auc": _auc(y_zero, p_zero)}
    nulls["planted_effect_recovery"] = {
        "planted_strength": args.plant,
        "auc_on_zero_world_with_effect": _auc(y4, p4),
        "auc_on_zero_world_without": _auc(y_zero, p_zero),
        "auc_real": real_auc,
    }

    # ---- is PvP a state or a gradient? the decisive version -----------------------------
    gm2 = GaussianMixture(2, covariance_type="full", random_state=0, n_init=4).fit(Z)
    mu = gm2.means_
    pooled = np.mean([np.diag(c) for c in gm2.covariances_], axis=0)
    sep = float(np.sqrt(np.sum((mu[0] - mu[1]) ** 2 / np.maximum(pooled, 1e-12))))
    dens_modes = _count_modes(df["pvp_score"].to_numpy())
    res["state_test"] = {
        "gmm2_component_separation_mahalanobis": sep,
        "gmm2_weights": [float(w) for w in gm2.weights_],
        "composite_score_kde_modes_by_bandwidth": dens_modes,
        "verdict": (
            "STATE (separated modes)"
            if sep > 2.0 and min(dens_modes.values()) > 1
            else "GRADIENT (one mode; BIC prefers k>1 because the block is non-Gaussian, "
                 "not because it is bimodal)"
        ),
    }

    # ---- knob sensitivity: how hold_med_s is filled when no round trip completes --------
    res["hold_fill_sensitivity"] = {}
    for fill_name, fill_val in (("bucket_1800", float(BUCKET)), ("zero", 0.0),
                                ("median_observed", float(df["hold_med_s"].median()))):
        d2 = df.copy()
        d2["log_hold"] = np.log1p(d2["hold_med_s"].fillna(fill_val))
        t2 = d2[d2.birth_time <= cut]
        e2 = d2[d2.birth_time > cut]
        pp, yy, _ = _fit_score(t2, e2, FREE_COLS + PVP_COLS, "dead_4h", seed=args.seed)
        res["hold_fill_sensitivity"][fill_name] = {
            "free_plus_pvp_auc_dead_4h": _auc(yy, pp),
            "log_hold_alone_auc": _auc(e2["dead_4h"], e2["log_hold"]),
        }
    res["nulls"] = {"label": label, "real_auc": real_auc, **nulls}

    # ---- per-column univariate AUCs, BY-FDR ---------------------------------------------
    uni = []
    for c in PVP_COLS + (BASELINE_COL,):
        for label in labels:
            y = te[label].to_numpy(int)
            s = te[c].to_numpy(float)
            a = _auc(y, s)
            # permutation p on the column, mint-clustered
            perm = []
            for d in range(args.draws // 4):
                sp = rng.permutation(s)
                perm.append(_auc(y, sp))
            p = (1 + sum(abs(x - 0.5) >= abs(a - 0.5) for x in perm)) / (1 + len(perm))
            uni.append({"col": c, "label": label, "auc": a, "p_perm": p})
            pvals.append(p)
    keep = _by_fdr([u["p_perm"] for u in uni], q=0.10)
    for u, k in zip(uni, keep, strict=True):
        u["by_fdr_q10"] = bool(k)
    res["univariate"] = uni

    # ---- the operator's own question, which is not the coordinator's ---------------------
    # The brief framed PvP as a possible LP arena. The operator's framing is different and
    # cheaper: "notice them and either avoid them, or find the one that is going to do good".
    # Those are two decisions and they need two numbers.
    #
    # (i) AVOID: what an operating threshold on the PvP score actually buys, as
    #     precision/recall on "this coin stops trading within four hours", at each decile of
    #     the score, so a threshold can be chosen against its own cost rather than argued.
    te = te.copy()
    te["pvp_score"] = df.loc[te.index, "pvp_score"]
    avoid = []
    for q in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        thr = float(np.quantile(df.pvp_score, q))
        flag = te.pvp_score >= thr
        for lab in labels:
            y = te[lab].to_numpy(bool)
            if flag.sum() == 0:
                continue
            avoid.append({
                "label": lab, "score_quantile": q, "threshold": thr,
                "flagged_share_of_rows": float(flag.mean()),
                "precision": float(y[flag.to_numpy()].mean()),
                "recall": float((y & flag.to_numpy()).sum() / max(y.sum(), 1)),
                "base_rate": float(y.mean()),
                "lift": float(y[flag.to_numpy()].mean() / max(y.mean(), 1e-9)),
                "median_ret_1h_flagged": float(te.ret_1h[flag].median(skipna=True)),
                "median_ret_1h_unflagged": float(te.ret_1h[~flag].median(skipna=True)),
            })
    res["avoid_rule"] = avoid

    # (ii) WITHIN the PvP state, which one does good? Conditioning on the top decile of the
    #      score and asking what separates the coins that go UP. If nothing does, "avoid" is
    #      the whole of the actionable content and the selection idea is dead on this data.
    hi_thr = float(np.quantile(df.pvp_score, 0.90))
    tr_hi = tr[df.loc[tr.index, "pvp_score"] >= hi_thr].copy()
    te_hi = te[te.pvp_score >= hi_thr].copy()
    win = {}
    for lab, mk in (("up_1h", lambda d: (d.ret_1h > 0.10).astype(int)),
                    ("spike_1h", lambda d: (d.maxret_1h > 0.20).astype(int))):
        tr_hi[lab] = mk(tr_hi).fillna(0).astype(int)
        te_hi[lab] = mk(te_hi).fillna(0).astype(int)
        entry = {"base_rate_test": float(te_hi[lab].mean()),
                 "n_train": int(len(tr_hi)), "n_test": int(len(te_hi))}
        if te_hi[lab].nunique() > 1 and tr_hi[lab].nunique() > 1:
            for nm, cols in (("free", FREE_COLS), ("free + PvP", FREE_COLS + PVP_COLS),
                             ("PvP only", PVP_COLS)):
                pp, yy, _ = _fit_score(tr_hi, te_hi, cols, lab, seed=args.seed)
                entry[nm] = _auc(yy, pp)
            # both nulls on the winner question
            sh = []
            for d_ in range(args.null_draws):
                t2 = tr_hi.copy()
                t2[lab] = rng.permutation(t2[lab].to_numpy())
                pp, yy, _ = _fit_score(t2, te_hi, FREE_COLS + PVP_COLS, lab, seed=args.seed + d_)
                sh.append(_auc(yy, pp))
            entry["label_shuffle_null_median"] = float(np.median(sh))
            entry["null_beats_real"] = int(sum(a >= entry["free + PvP"] for a in sh))
            entry["null_draws"] = args.null_draws
        win[lab] = entry
    res["within_pvp_winner"] = win

    (OUT / "classify.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float), flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: arena -- eta components conditional on PvP state
# ---------------------------------------------------------------------------------------
#
# RESULT_circuit_theory.md §4.2:   LP is +EV  <=>  eta > VR(T),   eta = 2 f N / (C * RV).
# RESULT_callout_volatility.md §6 found ONE condition that lifts N while leaving RV alone,
# and §9 flagged the size-weighted version of N as "the single highest-value follow-up in
# this file" -- fees are proportional to VOLUME, not to trade count, and a burst of dust buys
# raises the count without raising the income. This stage computes both, because the
# difference between them is the finding.
#
# C = w_x w_y TVL = TVL/4 for a 50/50 constant product, and TVL = 2 * v_sol, so C = v_sol/2.
# v_sol is read off the same identity the tape is priced with (v_sol = p * v_tok), so the
# capacitance is measured, not assumed.

FEE_LP = 0.0020  # PumpSwap LP share
FEE_TOTAL = 0.0100  # total take across LP + protocol + creator
FEE_FLOOR_SOL = 0.05  # LP fees per forward hour below which a "window" is a ghost town


def cmd_arena(args: argparse.Namespace) -> int:
    import numpy as np

    con = _duck(args.threads, args.memory)
    T = _trades_rel(con)
    t0 = time.time()

    # variance ratio needs RV at two sampling frequencies over the same window
    con.execute(
        f"""
        CREATE OR REPLACE TABLE vr AS
        WITH m1 AS (
            SELECT mint_id, (t / 60)::INTEGER AS g, arg_max(log_px, (slot, txi)) AS px
            FROM {T} GROUP BY 1, 2
        ), d1 AS (
            SELECT mint_id, g, px - lag(px) OVER (PARTITION BY mint_id ORDER BY g) AS dp,
                   g - lag(g) OVER (PARTITION BY mint_id ORDER BY g) AS dg FROM m1
        ), m5 AS (
            SELECT mint_id, (t / 300)::INTEGER AS g, arg_max(log_px, (slot, txi)) AS px
            FROM {T} GROUP BY 1, 2
        ), d5 AS (
            SELECT mint_id, g, px - lag(px) OVER (PARTITION BY mint_id ORDER BY g) AS dp,
                   g - lag(g) OVER (PARTITION BY mint_id ORDER BY g) AS dg FROM m5
        )
        SELECT a.mint_id, a.b,
               a.rv1, coalesce(c.rv5, 0) AS rv5
        FROM (SELECT mint_id, (g * 60 / {BUCKET})::INTEGER * {BUCKET} AS b,
                     sum(CASE WHEN dg = 1 THEN dp * dp ELSE 0 END) AS rv1
              FROM d1 GROUP BY 1, 2) a
        LEFT JOIN (SELECT mint_id, (g * 300 / {BUCKET})::INTEGER * {BUCKET} AS b,
                          sum(CASE WHEN dg = 1 THEN dp * dp ELSE 0 END) AS rv5
                   FROM d5 GROUP BY 1, 2) c USING (mint_id, b)
        """
    )
    df = _load_panel(con, min_wallets=args.min_wallets)
    v = con.execute("SELECT * FROM vr").df()
    df = df.merge(v, on=["mint_id", "b"], how="left")
    print(f"[arena] {len(df):,} rows ({time.time() - t0:.0f}s)", flush=True)

    signs = {"rotation_share": 1, "new_money_share": -1, "roundtrip_frac": 1,
             "log_hold": -1, "log_turnover": 1}
    ranks = np.zeros(len(df))
    for c, sgn in signs.items():
        r = df[c].rank(pct=True).to_numpy()
        ranks += r if sgn > 0 else (1.0 - r)
    df["pvp_score"] = ranks / len(signs)

    # ---- eta, both flavours -----------------------------------------------------------
    C = np.maximum(df["pool_sol"].to_numpy() / 2.0, 1e-6)
    rv_f = np.maximum(df["rv_1h"].to_numpy(), 1e-9)
    vol_f = df["vol_1h"].to_numpy()
    # trade count forward: sum of n_trades over the forward hour is not stored, so use the
    # bucket's own count scaled by the forward/current volume ratio only where both exist.
    df["eta_vol_lp"] = 2 * FEE_LP * vol_f / (C * rv_f)
    df["eta_vol_total"] = 2 * FEE_TOTAL * vol_f / (C * rv_f)
    df["vr_5_1"] = np.where(df["rv1"].fillna(0) > 0, df["rv5"] / df["rv1"], np.nan)
    df["eta_over_vr"] = df["eta_vol_lp"] / np.maximum(df["vr_5_1"].fillna(1.0), 1e-6)
    df["fee_sol_1h"] = FEE_LP * vol_f

    ok = np.isfinite(df["eta_vol_lp"]) & (df["vol_1h"] > 0) & (df["rv_1h"] > 0)
    d = df[ok].copy()
    d["pvp_decile"] = (d["pvp_score"].rank(pct=True) * 10).clip(0, 9.999).astype(int)
    # A window is only an OPPORTUNITY if it pays. eta = 2fN/(C*RV) goes to infinity as RV
    # goes to zero, and RV goes to zero exactly when nothing trades -- so an unguarded
    # eta > VR count scores the GHOST_TOWN state (RESULT_crime_signatures.md §7.1,
    # `dV = dQ/C` with `C -> 0`) as the best arena on the board. The guard is an absolute
    # fee floor, stated rather than tuned: 0.05 SOL/h of LP fees, about $4/h at the
    # operator's own 5 SOL-per-book bankroll.
    d["paying_window"] = ((d["eta_over_vr"] > 1) & (d["fee_sol_1h"] >= FEE_FLOOR_SOL))

    tbl = d.groupby("pvp_decile").agg(
        n=("eta_vol_lp", "size"),
        pvp=("pvp_score", "median"),
        vol_1h=("vol_1h", "median"),
        fee_sol_1h=("fee_sol_1h", "median"),
        C_sol=("pool_sol", lambda s: float(np.median(s) / 2)),
        rv_1h=("rv_1h", "median"),
        eta_lp=("eta_vol_lp", "median"),
        eta_total=("eta_vol_total", "median"),
        vr=("vr_5_1", "median"),
        frac_eta_gt_vr=("eta_over_vr", lambda s: float((s > 1).mean())),
        frac_eta_gt_vr_and_paying=("paying_window", "mean"),
        dead_4h=("dead_4h", "mean"),
        ret_1h=("ret_1h", "median"),
    ).reset_index()
    res = {"fee_lp": FEE_LP, "fee_total": FEE_TOTAL, "rows": int(len(d)),
           "by_pvp_decile": json.loads(tbl.to_json(orient="records"))}

    # ---- the window: run length of the eta-favourable state, and how it ends -----------
    import pandas as pd

    d = d.sort_values(["mint_id", "b"]).reset_index(drop=True)
    fav = d["paying_window"].to_numpy()
    mint = d["mint_id"].to_numpy()
    bb = d["b"].to_numpy()
    # contiguous favourable runs, vectorised: a new run starts wherever the previous row is
    # not favourable, is a different coin, or is not the immediately preceding bucket.
    prev_ok = np.empty(len(d), bool)
    prev_ok[0] = False
    prev_ok[1:] = fav[:-1] & (mint[1:] == mint[:-1]) & (bb[1:] == bb[:-1] + BUCKET)
    starts = np.flatnonzero(fav & ~prev_ok)
    run_id = np.full(len(d), -1)
    run_id[fav] = np.searchsorted(starts, np.flatnonzero(fav), side="right") - 1
    F = d[fav].copy()
    F["run_id"] = run_id[fav]
    agg = F.groupby("run_id").agg(
        mint_id=("mint_id", "first"),
        len_buckets=("b", "size"),
        pvp_at_entry=("pvp_score", "first"),
        eta_at_entry=("eta_over_vr", "first"),
        fee_sol=("fee_sol_1h", "sum"),
        b_end=("b", "max"),
        t_last=("t_last", "last"),
        graduated=("graduated", "last"),
    ).reset_index(drop=True)
    agg["ended_ghost_town"] = agg["t_last"] <= agg["b_end"] + 2 * BUCKET
    R = agg
    if len(R):
        R["pvp_hi"] = R["pvp_at_entry"] >= R["pvp_at_entry"].median()
        res["window"] = {
            "n_episodes": int(len(R)),
            "median_len_buckets": float(R.len_buckets.median()),
            "p90_len_buckets": float(R.len_buckets.quantile(0.90)),
            "median_len_minutes": float(R.len_buckets.median() * BUCKET / 60),
            "ghost_town_end_share": float(R.ended_ghost_town.mean()),
            "median_fee_sol_per_episode": float(R.fee_sol.median()),
            "by_pvp_half": json.loads(
                R.groupby("pvp_hi").agg(
                    n=("len_buckets", "size"),
                    median_len_buckets=("len_buckets", "median"),
                    median_fee_sol=("fee_sol", "median"),
                    ghost_town_end=("ended_ghost_town", "mean"),
                ).reset_index().to_json(orient="records")
            ),
        }

    # ---- does PvP state PREDICT the eta-favourable window? -----------------------------
    # Strictly forward: features from bucket b, eta measured on (b, b+1h].
    from sklearn.metrics import roc_auc_score

    cut = float(np.quantile(d.birth_time, args.split))
    tr, te = d[d.birth_time <= cut], d[d.birth_time > cut]
    y = (te["eta_over_vr"] > 1).astype(int).to_numpy()
    res["predicting_the_window"] = {"base_rate_test": float(y.mean())}
    if len(set(y)) > 1:
        for name, cols in (("free", FREE_COLS), ("free + PvP", FREE_COLS + PVP_COLS),
                           ("PvP only", PVP_COLS), ("recycled_30m alone", (BASELINE_COL,))):
            if len(cols) == 1:
                s = te[cols[0]].to_numpy(float)
                sgn = 1.0 if roc_auc_score(
                    (tr["eta_over_vr"] > 1).astype(int), tr[cols[0]]) >= 0.5 else -1.0
                a = _auc(y, sgn * s)
            else:
                tr2, te2 = tr.copy(), te.copy()
                tr2["_y"] = (tr2["eta_over_vr"] > 1).astype(int)
                te2["_y"] = y
                p, _, _ = _fit_score(tr2, te2, cols, "_y", seed=args.seed)
                a = _auc(y, p)
            res["predicting_the_window"][name] = a

    (OUT / "arena.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float), flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: transition -- does the flow turn mercenary BEFORE the price breaks?
# ---------------------------------------------------------------------------------------


def cmd_transition(args: argparse.Namespace) -> int:
    import numpy as np
    import pandas as pd

    con = _duck(args.threads, args.memory)
    df = _load_panel(con, min_wallets=args.min_wallets)
    signs = {"rotation_share": 1, "new_money_share": -1, "roundtrip_frac": 1,
             "log_hold": -1, "log_turnover": 1}
    ranks = np.zeros(len(df))
    for c, sgn in signs.items():
        r = df[c].rank(pct=True).to_numpy()
        ranks += r if sgn > 0 else (1.0 - r)
    df["pvp_score"] = ranks / len(signs)
    thr = float(np.quantile(df.pvp_score, args.pvp_q))

    df = df.sort_values(["mint_id", "b"])
    g = df.groupby("mint_id")
    df["peak_px"] = g["px_end"].cummax()
    df["dd"] = df["px_end"] - df["peak_px"]  # log drawdown from running peak

    # "genuine holder base": an early phase with real outside money and real holds.
    early = df[df.groupby("mint_id").cumcount() < args.early_buckets]
    qual = early.groupby("mint_id").agg(
        new_money=("new_money_share", "mean"),
        hold=("hold_med_s", "median"),
        wallets=("n_wallets", "max"),
        pvp_early=("pvp_score", "mean"),
    )
    qual = qual[
        (qual.new_money >= args.min_new_money)
        & (qual.hold >= args.min_hold)
        & (qual.wallets >= args.min_base_wallets)
    ]
    res = {
        "pvp_threshold_quantile": args.pvp_q,
        "pvp_threshold": thr,
        "qualifying_coins": int(len(qual)),
        "cohort_coins": int(df.mint_id.nunique()),
    }

    sub = df[df.mint_id.isin(qual.index)]
    leads = []
    for mid, grp in sub.groupby("mint_id"):
        grp = grp.sort_values("b")
        brk = grp[grp.dd <= math.log(1 - args.break_dd)]
        if brk.empty:
            continue
        t_break = float(brk.b.iloc[0])
        pv = grp[(grp.pvp_score >= thr) & (grp.b <= t_break)]
        if pv.empty:
            leads.append({"mint_id": int(mid), "lead_s": None, "t_break": t_break})
            continue
        leads.append({"mint_id": int(mid), "lead_s": t_break - float(pv.b.iloc[0]),
                      "t_break": t_break})
    L = pd.DataFrame(leads)
    if len(L):
        hit = L.dropna(subset=["lead_s"])
        res["coins_that_broke"] = int(len(L))
        res["pvp_fired_before_break"] = int(len(hit))
        res["pvp_fired_share"] = float(len(hit) / max(len(L), 1))
        res["lead_s"] = {
            q: float(hit.lead_s.quantile(q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)
        } if len(hit) else {}
        res["lead_minutes_median"] = float(hit.lead_s.median() / 60) if len(hit) else None
        res["lead_zero_share"] = float((hit.lead_s == 0).mean()) if len(hit) else None

        # NULL: reshuffle pvp_score across coins within (mcap, age) bins and redo. If the
        # lead is just "PvP fires on every coin eventually", the null reproduces it.
        rng = np.random.default_rng(args.seed)
        null_leads = []
        for _ in range(args.null_draws):
            s2 = sub.copy()
            bins = (s2["log_mcap"].rank(pct=True).mul(5).astype(int).astype(str) + "_"
                    + s2["log_age"].rank(pct=True).mul(5).astype(int).astype(str))
            for _, idx in s2.groupby(bins.values).groups.items():
                idx = np.asarray(idx)
                s2.loc[idx, "pvp_score"] = sub.loc[rng.permutation(idx), "pvp_score"].to_numpy()
            fired, tot = 0, 0
            ls = []
            for mid, grp in s2.groupby("mint_id"):
                grp = grp.sort_values("b")
                brk = grp[grp.dd <= math.log(1 - args.break_dd)]
                if brk.empty:
                    continue
                tot += 1
                tb = float(brk.b.iloc[0])
                pv = grp[(grp.pvp_score >= thr) & (grp.b <= tb)]
                if not pv.empty:
                    fired += 1
                    ls.append(tb - float(pv.b.iloc[0]))
            null_leads.append({"fired_share": fired / max(tot, 1),
                               "median_lead_s": float(np.median(ls)) if ls else None})
        res["null_matched_swap"] = {
            "median_fired_share": float(np.median([n["fired_share"] for n in null_leads])),
            "median_lead_s": float(np.median([n["median_lead_s"] for n in null_leads
                                              if n["median_lead_s"] is not None])),
            "draws": args.null_draws,
        }

    # ---- the operator's four coins, scored today ---------------------------------------
    op = con.execute(
        f"""
        SELECT * FROM read_parquet('{OUT / 'panel.parquet'}')
        WHERE mint IN ({','.join(f"'{m}'" for m in OPERATOR_COINS.values())})
        """
    ).df()
    scored = []
    if len(op):
        opd = op.copy()
        opd["log_hold"] = np.log1p(opd["hold_med_s"].fillna(BUCKET))
        opd["log_turnover"] = np.log1p(opd["float_turnover"].fillna(0.0).clip(0, 1e4))
        # score each operator bucket against the CORPUS distribution, not against itself
        for _, r in opd.sort_values("b").groupby("mint").tail(args.op_buckets).iterrows():
            comp = {}
            tot = 0.0
            for c, sgn in signs.items():
                val = r[c]
                if val != val:
                    comp[c] = None
                    continue
                pct = float((df[c] <= val).mean())
                comp[c] = pct if sgn > 0 else 1.0 - pct
                tot += comp[c]
            name = next((k for k, v in OPERATOR_COINS.items() if v == r["mint"]), r["mint"])
            scored.append({
                "coin": name, "bucket_start": int(r["b"]),
                "pvp_score": tot / len(signs),
                "pvp_percentile_vs_corpus": float((df.pvp_score <= tot / len(signs)).mean()),
                "components_pctile": comp,
                "raw": {c: (None if r[c] != r[c] else float(r[c]))
                        for c in ("rotation_share", "new_money_share", "roundtrip_frac",
                                  "hold_med_s", "float_turnover", "recycled_30m",
                                  "gross_sol", "n_wallets", "mcap_sol", "pool_sol")},
            })
    res["operator_coins"] = scored
    (OUT / "transition.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float), flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: vamp -- DIRECTED host -> clone flow, the thing the imitation lane did not measure
# ---------------------------------------------------------------------------------------
#
# RESULT_imitation_signal.md established that swarmed hosts LIVE LONGER (10.7 min vs 1.0 min
# median survival, log-rank p < 0.0001) and that the swarm carries no return information. It
# never measured the flow, because its instrument was launch metadata plus candles and
# neither carries a wallet. "Vamp" is a claim about a DIRECTED quantity -- host holders
# selling the host and buying the clone -- and that is what this stage measures.
#
# Two nulls, because PROGRAM.md §3.13 says one null is a knob. The naive-vs-rotation trap has
# fired twice in this repo already (RESULT_caller_wallets §2.1: 20x against the naive null,
# 1.20x against an age-and-crowd-matched one; RESULT_copytrading: 73x -> 0.98x).


def _load_families(day: str, k: int = 2):
    sys.path.insert(0, str(REPO_ROOT))
    from shitcoims_scalper.swarm_detect import SwarmDetector, build_stream

    census = REPO_ROOT / "state" / "swarms" / f"retro-{day}.jsonl"
    if not census.exists():
        raise SystemExit(f"no retro census at {census}")
    launches, stats = build_stream([], [census], None)
    det = SwarmDetector(window_s=1800.0, k=k, name_threshold=0.82)
    for ln in launches:
        det.push(ln)
    fams = [f for f in det.family_rows() if f.get("size", 0) >= 2]
    return fams, stats


def cmd_vamp(args: argparse.Namespace) -> int:
    import numpy as np
    import pandas as pd

    con = _duck(args.threads, args.memory)
    T = _trades_rel(con)
    fams, stats = _load_families(args.day, k=args.k)
    print(f"[vamp] {stats.get('launches')} launches, {len(fams)} families size>=2", flush=True)

    mints = con.execute(
        f"SELECT mint, mint_id FROM read_parquet('{OUT / 'mints.parquet'}')"
    ).df()
    mid = dict(zip(mints.mint, mints.mint_id, strict=True))

    pairs = []
    for f in fams:
        members = f.get("members") or []
        if not members:
            continue
        rows = []
        for m in members:
            mm = m["mint"] if isinstance(m, dict) else m
            tt = m.get("t") if isinstance(m, dict) else None
            rows.append((mm, tt))
        rows = [(m, _iso_epoch(t) if isinstance(t, str) else t) for m, t in rows]
        rows = [(m, t) for m, t in rows if t is not None]
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: r[1])
        host_mint, host_t = rows[0]
        for clone_mint, clone_t in rows[1:]:
            if host_mint in mid and clone_mint in mid:
                pairs.append({
                    "family_id": f.get("family_id"), "taxonomy": f.get("taxonomy"),
                    "host": host_mint, "host_id": int(mid[host_mint]), "host_t": host_t,
                    "clone": clone_mint, "clone_id": int(mid[clone_mint]),
                    "clone_t": clone_t,
                    "family_size": f.get("size"),
                    "members_on_tape": sum(1 for m, _ in rows if m in mid),
                    "members_total": len(rows),
                })
    P = pd.DataFrame(pairs)
    # A family can list the same mint twice (alias merges), and a duplicated (family, clone)
    # row multiplies the drain SUM without multiplying the clone's buy total -- which is how
    # the first run produced a "drain share" above 1.0, an impossible number for a statistic
    # bounded by the clone's own buying.
    if len(P):
        P = P.drop_duplicates(subset=["family_id", "clone_id"]).reset_index(drop=True)
    print(f"[vamp] {len(P)} (host, clone) pairs with BOTH coins on the flow tape "
          f"(of {sum(len(f.get('members') or []) - 1 for f in fams)} family edges)", flush=True)
    if not len(P):
        (OUT / "vamp.json").write_text(json.dumps({"pairs": 0}))
        return 0

    con.register("P", P)
    con.execute("CREATE OR REPLACE TABLE pairs AS SELECT * FROM P")

    W = args.window
    drain_sql = f"""
    WITH hs AS (   -- host SELLING around the clone's launch, per wallet
        SELECT p.family_id, p.clone_id, t.owner_id, sum(-t.sol) AS sell_sol
        FROM pairs p JOIN {T} t ON t.mint_id = p.host_id
        WHERE t.sol < 0 AND t.t BETWEEN p.clone_t - {W} AND p.clone_t + {W}
        GROUP BY 1, 2, 3
    ), cb AS (     -- clone BUYING after its launch, per wallet
        SELECT p.family_id, p.clone_id, t.owner_id, sum(t.sol) AS buy_sol
        FROM pairs p JOIN {T} t ON t.mint_id = p.clone_id
        WHERE t.sol > 0 AND t.t BETWEEN p.clone_t AND p.clone_t + {W}
        GROUP BY 1, 2, 3
    ), tot AS (
        SELECT family_id, clone_id, sum(sell_sol) AS host_sell_total,
               count(*) AS host_sellers FROM hs GROUP BY 1, 2
    ), totc AS (
        SELECT family_id, clone_id, sum(buy_sol) AS clone_buy_total,
               count(*) AS clone_buyers FROM cb GROUP BY 1, 2
    )
    SELECT p.family_id, p.clone_id, p.host, p.clone, p.taxonomy, p.family_size,
           p.host_t, p.clone_t,
           coalesce(sum(CASE WHEN cb.buy_sol IS NULL OR hs.sell_sol IS NULL THEN 0
                             ELSE least(hs.sell_sol, cb.buy_sol) END), 0) AS drain_sol,
           count(cb.owner_id) AS shared_wallets,
           count(hs.owner_id) AS host_seller_rows,
           any_value(tot.host_sell_total) AS host_sell_total,
           any_value(tot.host_sellers) AS host_sellers,
           any_value(totc.clone_buy_total) AS clone_buy_total,
           any_value(totc.clone_buyers) AS clone_buyers
    FROM pairs p
    LEFT JOIN hs ON hs.family_id = p.family_id AND hs.clone_id = p.clone_id
    LEFT JOIN cb ON cb.family_id = p.family_id AND cb.clone_id = p.clone_id
                AND cb.owner_id = hs.owner_id
    LEFT JOIN tot ON tot.family_id = p.family_id AND tot.clone_id = p.clone_id
    LEFT JOIN totc ON totc.family_id = p.family_id AND totc.clone_id = p.clone_id
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
    """
    D = con.execute(drain_sql).df()
    D["drain_share_of_clone_buys"] = D.drain_sol / D.clone_buy_total.replace(0, np.nan)
    D["drain_share_of_host_sells"] = D.drain_sol / D.host_sell_total.replace(0, np.nan)
    real = D.dropna(subset=["drain_share_of_clone_buys"])
    print(f"[vamp] {len(real)} pairs with clone buying in the window", flush=True)

    # ---- the two nulls -----------------------------------------------------------------
    # A: NAIVE -- swap the host for a uniformly random coin trading at the same instant.
    # B: ROTATION-MATCHED -- swap the host for a coin trading at the same instant with a
    #    comparable sell-side flow AND crowd, and not in the family. This is the ambient
    #    cross-coin rotation between any two coins of that size, which is what a naive
    #    measurement mistakes for a drain.
    alive = con.execute(
        f"""
        SELECT mint_id, (t / 1800)::INTEGER * 1800 AS b,
               sum(CASE WHEN sol < 0 THEN -sol ELSE 0 END) AS sell_sol,
               count(DISTINCT owner_id) AS crowd
        FROM {T} GROUP BY 1, 2
        """
    ).df()
    rng = np.random.default_rng(args.seed)
    null_rows = {"naive": [], "rotation_matched": []}
    for kind in ("naive", "rotation_matched"):
        for draw in range(args.null_draws):
            sub = real[["family_id", "clone_id", "clone_t"]].copy()
            sub["b"] = (sub.clone_t // 1800).astype(int) * 1800
            hostinfo = real[["family_id", "clone_id", "host_sell_total", "host_sellers"]]
            sub = sub.merge(hostinfo, on=["family_id", "clone_id"])
            pool = alive.copy()
            subs = []
            for b, grp in sub.groupby("b"):
                cand = pool[pool.b == b]
                if not len(cand):
                    continue
                for _, r in grp.iterrows():
                    if kind == "naive":
                        c = cand.sample(1, random_state=int(rng.integers(1 << 31)))
                    else:
                        lo, hi = r.host_sell_total / 2.0, r.host_sell_total * 2.0
                        m = cand[(cand.sell_sol >= lo) & (cand.sell_sol <= hi)]
                        if not len(m):
                            continue
                        c = m.sample(1, random_state=int(rng.integers(1 << 31)))
                    subs.append({"family_id": r.family_id, "clone_id": int(r.clone_id),
                                 "clone_t": float(r.clone_t),
                                 "fake_host_id": int(c.mint_id.iloc[0])})
            if not subs:
                continue
            S = pd.DataFrame(subs)
            con.register("S", S)
            con.execute("CREATE OR REPLACE TABLE fake AS SELECT * FROM S")
            nd = con.execute(
                f"""
                WITH hs AS (
                    SELECT p.family_id, p.clone_id, t.owner_id, sum(-t.sol) AS sell_sol
                    FROM fake p JOIN {T} t ON t.mint_id = p.fake_host_id
                    WHERE t.sol < 0 AND t.t BETWEEN p.clone_t - {W} AND p.clone_t + {W}
                    GROUP BY 1, 2, 3
                ), cb AS (
                    SELECT p.family_id, p.clone_id, t.owner_id, sum(t.sol) AS buy_sol
                    FROM fake p JOIN {T} t ON t.mint_id = p.clone_id
                    WHERE t.sol > 0 AND t.t BETWEEN p.clone_t AND p.clone_t + {W}
                    GROUP BY 1, 2, 3
                ), totc AS (
                    SELECT family_id, clone_id, sum(buy_sol) AS clone_buy_total FROM cb
                    GROUP BY 1, 2
                )
                SELECT p.family_id, p.clone_id,
                       coalesce(sum(CASE WHEN cb.buy_sol IS NULL OR hs.sell_sol IS NULL
                                         THEN 0 ELSE least(hs.sell_sol, cb.buy_sol) END), 0)
                           AS drain_sol,
                       count(cb.owner_id) AS shared_wallets,
                       any_value(totc.clone_buy_total) AS clone_buy_total
                FROM fake p
                LEFT JOIN hs ON hs.family_id = p.family_id AND hs.clone_id = p.clone_id
                LEFT JOIN cb ON cb.family_id = p.family_id AND cb.clone_id = p.clone_id
                                AND cb.owner_id = hs.owner_id
                LEFT JOIN totc ON totc.family_id = p.family_id AND totc.clone_id = p.clone_id
                GROUP BY 1, 2
                """
            ).df()
            nd["share"] = nd.drain_sol / nd.clone_buy_total.replace(0, np.nan)
            null_rows[kind].append({
                "median": float(nd.share.median(skipna=True)),
                "mean": float(nd.share.mean(skipna=True)),
                "share_nonzero": float((nd.share.fillna(0) > 0).mean()),
                "median_shared_wallets": float(nd.shared_wallets.median()),
            })

    obs = float(real.drain_share_of_clone_buys.median())
    obs_mean = float(real.drain_share_of_clone_buys.mean())
    res = {
        "day": args.day, "window_s": W, "k": args.k,
        "families": len(fams),
        "pairs_measured": int(len(real)),
        "pairs_dropped_not_on_tape": int(
            sum(len(f.get("members") or []) - 1 for f in fams) - len(P)
        ),
        "observed": {
            "median_drain_share_of_clone_buys": obs,
            "mean_drain_share_of_clone_buys": float(real.drain_share_of_clone_buys.mean()),
            "median_drain_share_of_host_sells": float(
                real.drain_share_of_host_sells.median(skipna=True)),
            "median_drain_sol": float(real.drain_sol.median()),
            "median_shared_wallets": float(real.shared_wallets.median()),
            "share_of_pairs_with_any_drain": float((real.drain_sol > 0).mean()),
            "median_clone_buy_total_sol": float(real.clone_buy_total.median()),
        },
        "nulls": {
            k: ({
                "draws": len(v),
                "median_of_draw_medians": float(np.median([x["median"] for x in v])),
                "mean_of_draw_means": float(np.mean([x["mean"] for x in v])),
                "median_shared_wallets": float(np.median([x["median_shared_wallets"] for x in v])),
                "share_of_pairs_with_any_drain": float(
                    np.median([x["share_nonzero"] for x in v])),
                "ratio_observed_mean_over_null_mean": (
                    obs_mean / float(np.mean([x["mean"] for x in v]))
                    if np.mean([x["mean"] for x in v]) > 0 else None),
                "p_draws_beating_observed_median": (
                    (1 + sum(x["median"] >= obs for x in v)) / (1 + len(v))),
            } if v else None)
            for k, v in null_rows.items()
        },
    }
    by_tax = real.groupby("taxonomy").agg(
        n=("drain_share_of_clone_buys", "size"),
        median_share=("drain_share_of_clone_buys", "median"),
        median_drain_sol=("drain_sol", "median"),
    ).reset_index()
    res["by_taxonomy"] = json.loads(by_tax.to_json(orient="records"))

    # ---- does drain predict host deterioration? ----------------------------------------
    # Host-level: total drain across its clones, against the host's own forward outcome,
    # matched on the host's size and age at the first clone. This is the direct test of the
    # tension with RESULT_imitation_signal's survival finding.
    host = real.groupby("host").agg(
        drain_sol=("drain_sol", "sum"),
        clone_buy_total=("clone_buy_total", "sum"),
        n_clones=("clone", "nunique"),
        first_clone_t=("clone_t", "min"),
    ).reset_index()
    con.register("H", host)
    hp = con.execute(
        f"""
        SELECT h.*, m.mint_id,
               p.gross_sol, p.n_wallets, p.mcap_sol, p.pool_sol, p.age_s,
               p.b, p.t_last, p.dead_4h, p.ret_1h, p.ret_4h, p.pvp_b
        FROM H h
        JOIN read_parquet('{OUT / 'mints.parquet'}') m ON m.mint = h.host
        JOIN (
            SELECT mint_id, b, gross_sol, n_wallets, mcap_sol, pool_sol, age_s, t_last,
                   dead_4h, ret_1h, ret_4h, b AS pvp_b
            FROM read_parquet('{OUT / 'panel.parquet'}')
        ) p ON p.mint_id = m.mint_id
           AND p.b = (h.first_clone_t / {BUCKET})::INTEGER * {BUCKET}
        """
    ).df()
    if len(hp) >= 30:
        hp["drain_intensity"] = hp.drain_sol / hp.gross_sol.replace(0, np.nan)
        hi = hp[hp.drain_intensity >= hp.drain_intensity.median()]
        lo = hp[hp.drain_intensity < hp.drain_intensity.median()]
        from scipy.stats import mannwhitneyu

        def _mw(a, b):
            a, b = a.dropna(), b.dropna()
            if len(a) < 5 or len(b) < 5:
                return None
            return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)

        res["host_deterioration"] = {
            "hosts": int(len(hp)),
            "high_drain_n": int(len(hi)), "low_drain_n": int(len(lo)),
            "dead_4h_high": float(hi.dead_4h.mean()), "dead_4h_low": float(lo.dead_4h.mean()),
            "median_ret_1h_high": float(hi.ret_1h.median(skipna=True)),
            "median_ret_1h_low": float(lo.ret_1h.median(skipna=True)),
            "median_ret_4h_high": float(hi.ret_4h.median(skipna=True)),
            "median_ret_4h_low": float(lo.ret_4h.median(skipna=True)),
            "p_ret_1h": _mw(hi.ret_1h, lo.ret_1h),
            "p_ret_4h": _mw(hi.ret_4h, lo.ret_4h),
            "p_dead_4h": _mw(hi.dead_4h.astype(float), lo.dead_4h.astype(float)),
            "median_gross_sol_high": float(hi.gross_sol.median()),
            "median_gross_sol_low": float(lo.gross_sol.median()),
            "median_age_s_high": float(hi.age_s.median(skipna=True)),
            "median_age_s_low": float(lo.age_s.median(skipna=True)),
        }
    else:
        res["host_deterioration"] = {"hosts": int(len(hp)), "note": "too few to test"}

    # ---- matched host comparison --------------------------------------------------------
    # High-drain hosts are BIGGER (2.1x the gross flow in the unmatched split), and size
    # predicts everything on this population, so the unmatched contrast is uninterpretable.
    # Match each high-drain host to the nearest low-drain host in (log gross_sol, log age).
    if len(hp) >= 30:
        hi = hp[hp.drain_intensity >= hp.drain_intensity.median()].copy()
        lo = hp[hp.drain_intensity < hp.drain_intensity.median()].copy()
        for d_ in (hi, lo):
            d_["lg"] = np.log1p(d_.gross_sol)
            d_["la"] = np.log1p(d_.age_s.clip(lower=0))
        used, mt, mc = set(), [], []
        for _, r in hi.iterrows():
            cand = lo[~lo.index.isin(used)]
            if not len(cand):
                break
            dist = (cand.lg - r.lg) ** 2 + (cand.la - r.la) ** 2
            j = dist.idxmin()
            if dist.loc[j] > args.match_tol ** 2:
                continue
            used.add(j)
            mt.append(r)
            mc.append(lo.loc[j])
        if len(mt) >= 20:
            MT, MC = pd.DataFrame(mt), pd.DataFrame(mc)
            res["host_deterioration_matched"] = {
                "pairs": int(len(MT)),
                "smd_log_gross_sol": float(
                    (MT.lg.mean() - MC.lg.mean())
                    / math.sqrt((MT.lg.var() + MC.lg.var()) / 2 + 1e-12)),
                "smd_log_age": float(
                    (MT.la.mean() - MC.la.mean())
                    / math.sqrt((MT.la.var() + MC.la.var()) / 2 + 1e-12)),
                "dead_4h_high": float(MT.dead_4h.mean()),
                "dead_4h_low": float(MC.dead_4h.mean()),
                "median_ret_1h_high": float(MT.ret_1h.median(skipna=True)),
                "median_ret_1h_low": float(MC.ret_1h.median(skipna=True)),
                "median_ret_4h_high": float(MT.ret_4h.median(skipna=True)),
                "median_ret_4h_low": float(MC.ret_4h.median(skipna=True)),
                "p_ret_1h": _mw(MT.ret_1h, MC.ret_1h),
                "p_ret_4h": _mw(MT.ret_4h, MC.ret_4h),
                "p_dead_4h": _mw(MT.dead_4h.astype(float), MC.dead_4h.astype(float)),
            }
        else:
            res["host_deterioration_matched"] = {"pairs": int(len(mt)),
                                                 "note": "too few matched pairs"}

    real.to_parquet(OUT / "vamp_pairs.parquet")
    (OUT / "vamp.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float), flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: regimes -- five other readings of "PvP", because one operational definition is a
#                   knob and the brief's was only one of them
# ---------------------------------------------------------------------------------------
#
# The brief defined PvP as a property of a COIN. That is a choice, and four other readings
# are at least as consistent with how the word is used:
#
#   A  MARKET-WIDE STATE   "the board is PvP tonight" -- a property of the hour, not the coin
#   B  LIFECYCLE PHASE     every coin ends in PvP; the question is when, so a coin-level PvP
#                          score might be age wearing a costume. This one audits our own
#                          headline and could kill it.
#   C  ONSET AS AN EVENT   "we see PvP START to happen" -- the derivative, not the level
#   D  THE WIGGLE FLIP     PvP raises RV 150x. RV is a cost to an LP and a RAW MATERIAL to a
#                          two-sided scalper. Same state, opposite sign, different book.
#   E  THE PACK'S BALANCE  PvP is a property of the CROWD: when the rotation cohort is losing
#                          money it has none to feed the next coin with.
#
# Each is a separate falsifiable claim and each is cheap on the tape already built.

FRICTION = 0.024  # full three-leg taker round trip at the operator's 0.1 SOL clip


def cmd_regimes(args: argparse.Namespace) -> int:
    import numpy as np
    import pandas as pd

    con = _duck(args.threads, args.memory)
    T = _trades_rel(con)
    res: dict = {}
    t0 = time.time()

    # ---- A. the market-wide state ------------------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE rot AS
        SELECT * FROM read_parquet('{OUT / 'rotation.parquet'}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE fseen AS
        SELECT mint_id, owner_id, min(t) AS t0 FROM {T} GROUP BY 1, 2
        """
    )
    hourly = con.execute(
        f"""
        SELECT (p.t / 3600)::INTEGER AS h,
               sum(p.sol) FILTER (WHERE p.sol > 0) AS buy_sol,
               sum(CASE WHEN r.owner_id IS NOT NULL AND p.sol > 0 THEN p.sol ELSE 0 END)
                   / nullif(sum(p.sol) FILTER (WHERE p.sol > 0), 0) AS rotation_share,
               sum(CASE WHEN f.t0 >= (p.t / 3600)::INTEGER * 3600 AND p.sol > 0
                        THEN p.sol ELSE 0 END)
                   / nullif(sum(p.sol) FILTER (WHERE p.sol > 0), 0) AS new_money_share,
               count(DISTINCT p.owner_id) AS wallets,
               count(DISTINCT p.mint_id) AS coins,
               count(*) AS trades
        FROM {T} p
        JOIN fseen f ON f.mint_id = p.mint_id AND f.owner_id = p.owner_id
        LEFT JOIN rot r ON r.owner_id = p.owner_id AND r.h = (p.t / 3600)::INTEGER
        GROUP BY 1 ORDER BY 1
        """
    ).df()
    hourly["board_pvp"] = (
        hourly.rotation_share.rank(pct=True) + (1 - hourly.new_money_share.rank(pct=True))
    ) / 2
    # is the board state persistent enough to be worth naming?
    acf = {lag: float(hourly.board_pvp.autocorr(lag)) for lag in (1, 3, 6, 12, 24)}
    # do coins BORN in a high-PvP hour fare differently?
    panel = con.execute(f"SELECT * FROM read_parquet('{OUT / 'panel.parquet'}')").df()
    coin = panel.sort_values("b").groupby("mint_id").first().reset_index()
    coin["birth_h"] = (coin.birth_time // 3600).astype("Int64")
    coin = coin.merge(hourly[["h", "board_pvp", "rotation_share", "new_money_share"]],
                      left_on="birth_h", right_on="h", how="left")
    coin["board_q"] = pd.qcut(coin.board_pvp, 4, labels=False, duplicates="drop")
    byq = coin.groupby("board_q").agg(
        n=("mint_id", "size"),
        board_pvp=("board_pvp", "median"),
        graduated=("graduated", "mean"),
        dead_4h=("dead_4h", "mean"),
        median_ret_1h=("ret_1h", "median"),
        median_peak_mcap=("peak_mcap_sol", "median"),
        median_gross_sol=("gross_sol", "median"),
    ).reset_index()
    res["A_market_wide_state"] = {
        "hours": int(len(hourly)),
        "board_pvp_autocorr": acf,
        "rotation_share_hourly": {
            "p10": float(hourly.rotation_share.quantile(0.10)),
            "median": float(hourly.rotation_share.median()),
            "p90": float(hourly.rotation_share.quantile(0.90)),
        },
        "new_money_share_hourly": {
            "p10": float(hourly.new_money_share.quantile(0.10)),
            "median": float(hourly.new_money_share.median()),
            "p90": float(hourly.new_money_share.quantile(0.90)),
        },
        "coins_born_by_board_quartile": json.loads(byq.to_json(orient="records")),
    }

    # ---- B. lifecycle: is the coin-level score just age? --------------------------------
    df = _load_panel(con, min_wallets=args.min_wallets)
    signs = {"rotation_share": 1, "new_money_share": -1, "roundtrip_frac": 1,
             "log_hold": -1, "log_turnover": 1}
    ranks = np.zeros(len(df))
    for c, sgn in signs.items():
        r = df[c].rank(pct=True).to_numpy()
        ranks += r if sgn > 0 else (1.0 - r)
    df["pvp_score"] = ranks / len(signs)
    thr = float(np.quantile(df.pvp_score, 0.80))
    df["age_bin"] = pd.cut(
        df.age_s.clip(lower=0),
        [-1, 1800, 3600, 7200, 14400, 43200, 86400, 1e9],
        labels=["<30m", "30-60m", "1-2h", "2-4h", "4-12h", "12-24h", ">24h"],
    )
    ab = df.groupby("age_bin", observed=True).agg(
        n=("pvp_score", "size"),
        median_pvp=("pvp_score", "median"),
        share_in_pvp=("pvp_score", lambda s: float((s >= thr).mean())),
        dead_4h=("dead_4h", "mean"),
    ).reset_index()
    # the decisive check: does the score still separate WITHIN an age band?
    within = []
    for ageb, grp in df.groupby("age_bin", observed=True):
        if len(grp) < 500 or grp.dead_4h.nunique() < 2:
            continue
        within.append({
            "age_bin": str(ageb), "n": int(len(grp)),
            "auc_pvp_score": _auc(grp.dead_4h.astype(int), grp.pvp_score),
            "auc_recycled_30m": _auc(grp.dead_4h.astype(int), grp.recycled_30m),
            "base_rate": float(grp.dead_4h.mean()),
        })
    res["B_lifecycle"] = {"by_age_bin": json.loads(ab.to_json(orient="records")),
                          "auc_within_age_band": within}

    # ---- C. onset as an event ------------------------------------------------------------
    df = df.sort_values(["mint_id", "b"])
    df["d_pvp"] = df.groupby("mint_id")["pvp_score"].diff()
    df["prev_pvp"] = df.groupby("mint_id")["pvp_score"].shift()
    on = df.dropna(subset=["d_pvp"]).copy()
    on["onset"] = (on.prev_pvp < thr) & (on.pvp_score >= thr)
    cut = float(np.quantile(on.birth_time, 0.70))
    tr, te = on[on.birth_time <= cut], on[on.birth_time > cut]
    lvl = {}
    for lab in ("dead_4h",):
        y = te[lab].astype(int).to_numpy()
        lvl["level_auc"] = _auc(y, te.pvp_score)
        lvl["delta_auc"] = _auc(y, te.d_pvp)
        lvl["onset_flag_auc"] = _auc(y, te.onset.astype(int))
        p1, _, _ = _fit_score(tr, te, FREE_COLS + PVP_COLS, lab, seed=args.seed)
        tr2, te2 = tr.copy(), te.copy()
        p2, _, _ = _fit_score(tr2, te2, FREE_COLS + PVP_COLS + ("d_pvp", "prev_pvp"),
                              lab, seed=args.seed)
        lvl["free_plus_pvp"] = _auc(y, p1)
        lvl["free_plus_pvp_plus_delta"] = _auc(y, p2)
    young = on[on.age_s <= 3600]
    lvl["young_coins_only"] = {
        "n": int(len(young)),
        "onset_rate": float(young.onset.mean()),
        "dead_4h_after_onset": float(young[young.onset].dead_4h.mean()) if young.onset.any() else None,
        "dead_4h_no_onset": float(young[~young.onset].dead_4h.mean()),
        "median_ret_1h_after_onset": float(young[young.onset].ret_1h.median(skipna=True)),
        "median_ret_1h_no_onset": float(young[~young.onset].ret_1h.median(skipna=True)),
    }
    res["C_onset_as_event"] = lvl

    # ---- D. the wiggle flip: RV as raw material rather than as cost ----------------------
    # Oracle zigzag on the minute grid: group consecutive same-sign log-returns into
    # monotone runs and credit each run its amplitude less one round trip of friction. This
    # is a CEILING (the filter turns at the exact extremes), same convention as
    # RESULT_callout_volatility.md's `wiggle_net`.
    wig = con.execute(
        f"""
        WITH m AS (
            SELECT mint_id, (t / 60)::INTEGER AS g, arg_max(log_px, (slot, txi)) AS px
            FROM {T} GROUP BY 1, 2
        ), d AS (
            SELECT mint_id, g, px - lag(px) OVER (PARTITION BY mint_id ORDER BY g) AS dp
            FROM m
        ), s AS (
            SELECT mint_id, g, dp,
                   CASE WHEN dp > 0 THEN 1 WHEN dp < 0 THEN -1 ELSE 0 END AS sg
            FROM d WHERE dp IS NOT NULL
        ), sl AS (
            SELECT *, lag(sg) OVER (PARTITION BY mint_id ORDER BY g) AS psg FROM s
        ), r AS (
            SELECT *, sum(CASE WHEN sg IS DISTINCT FROM psg THEN 1 ELSE 0 END)
                       OVER (PARTITION BY mint_id ORDER BY g
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_id
            FROM sl
        ), runs AS (
            SELECT mint_id, run_id, (min(g) * 60 / {BUCKET})::INTEGER * {BUCKET} AS b,
                   abs(sum(dp)) AS amp
            FROM r GROUP BY 1, 2
        )
        SELECT mint_id, b, sum(greatest(amp - {FRICTION}, 0)) AS wiggle_net_oracle,
               count(*) AS swings, sum(amp) AS total_variation
        FROM runs GROUP BY 1, 2
        """
    ).df()
    dw = df.merge(wig, on=["mint_id", "b"], how="left")
    dw["wiggle_net_oracle"] = dw.wiggle_net_oracle.fillna(0.0)
    dw["pvp_decile"] = (dw.pvp_score.rank(pct=True) * 10).clip(0, 9.999).astype(int)
    wt = dw.groupby("pvp_decile").agg(
        n=("wiggle_net_oracle", "size"),
        median_wiggle_net_oracle=("wiggle_net_oracle", "median"),
        median_swings=("swings", "median"),
        median_total_variation=("total_variation", "median"),
        share_wiggle_positive=("wiggle_net_oracle", lambda s: float((s > 0).mean())),
        median_gross_sol=("gross_sol", "median"),
        median_pool_sol=("pool_sol", "median"),
    ).reset_index()
    res["D_wiggle_flip"] = {
        "friction": FRICTION,
        "note": "ORACLE CEILING -- the filter turns at the exact extremes, no live rule attains it",
        "by_pvp_decile": json.loads(wt.to_json(orient="records")),
        "spearman_pvp_vs_wiggle": float(
            dw[["pvp_score", "wiggle_net_oracle"]].corr(method="spearman").iloc[0, 1]),
    }

    # ---- E. the pack's balance ------------------------------------------------------------
    pack = con.execute(
        f"""
        SELECT (p.t / 3600)::INTEGER AS h,
               -sum(p.sol) AS pack_net_sol,
               sum(abs(p.sol)) AS pack_gross_sol,
               count(DISTINCT p.owner_id) AS pack_wallets
        FROM {T} p JOIN rot r ON r.owner_id = p.owner_id AND r.h = (p.t / 3600)::INTEGER
        GROUP BY 1 ORDER BY 1
        """
    ).df()
    pack = pack.merge(hourly[["h", "board_pvp", "new_money_share", "buy_sol"]], on="h")
    pack["pack_net_per_gross"] = pack.pack_net_sol / pack.pack_gross_sol
    lead = {}
    for lag in (1, 2, 3, 6):
        lead[f"corr_packPnL_t_vs_boardPvP_t+{lag}"] = float(
            pack.pack_net_per_gross.corr(pack.board_pvp.shift(-lag)))
        lead[f"corr_packPnL_t_vs_buySol_t+{lag}"] = float(
            pack.pack_net_per_gross.corr(np.log1p(pack.buy_sol).shift(-lag)))
    res["E_pack_balance"] = {
        "hours": int(len(pack)),
        "pack_net_sol_per_hour": {
            "p10": float(pack.pack_net_sol.quantile(0.10)),
            "median": float(pack.pack_net_sol.median()),
            "p90": float(pack.pack_net_sol.quantile(0.90)),
        },
        "pack_net_per_gross_median": float(pack.pack_net_per_gross.median()),
        "hours_pack_net_positive": float((pack.pack_net_sol > 0).mean()),
        "lead_lag": lead,
    }

    (OUT / "regimes.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float), flush=True)
    print(f"[regimes] done ({time.time() - t0:.0f}s)", flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: opnow -- score the operator's four coins on TODAY's flow, not on the corpus edge
# ---------------------------------------------------------------------------------------
#
# The bulk corpus ends 2026-08-15T00:00Z, so scoring the four cluster coins off it answers
# "how were they last night", and the brief asks for today. pump.fun's own
# /v2/coins/<mint>/trades carries (userAddress, type, amountSol, timestamp) back through the
# whole day, keyless -- so the same features are computable live, and the two scorings are
# reported side by side rather than one silently standing in for the other.


def cmd_opnow(args: argparse.Namespace) -> int:
    import numpy as np
    import pandas as pd

    con = _duck(args.threads, args.memory)
    df = _load_panel(con, min_wallets=args.min_wallets)
    signs = {"rotation_share": 1, "new_money_share": -1, "roundtrip_frac": 1,
             "log_hold": -1, "log_turnover": 1}
    ranks = np.zeros(len(df))
    for c, sgn in signs.items():
        r = df[c].rank(pct=True).to_numpy()
        ranks += r if sgn > 0 else (1.0 - r)
    df["pvp_score"] = ranks / len(signs)

    # "known rotators": the rotation cohort as of the last hour the corpus can see. Today's
    # wallets are not in it by construction, so this is a LOWER bound on rotation share and
    # is labelled as one.
    rot = con.execute(
        f"""SELECT DISTINCT o.owner FROM read_parquet('{OUT / 'rotation.parquet'}') r
            JOIN read_parquet('{OUT / 'owners.parquet'}') o USING (owner_id)
            WHERE r.h >= (SELECT max(h) - {args.rot_hours} FROM read_parquet('{OUT / 'rotation.parquet'}'))"""
    ).df()
    known = set(rot.owner)
    print(f"[opnow] known-rotator set: {len(known):,} wallets", flush=True)

    out = []
    for name, mint in OPERATOR_COINS.items():
        rows = load_trades(mint)
        if not rows:
            out.append({"coin": name, "note": "no live tape"})
            continue
        t_end = max(r["t"] for r in rows)
        first_ever: dict[str, float] = {}
        for r in rows:
            first_ever.setdefault(r["w"], r["t"])
        for k in range(args.buckets):
            hi = t_end - k * BUCKET
            lo = hi - BUCKET
            w = [r for r in rows if lo <= r["t"] < hi]
            if len(w) < 5:
                continue
            per: dict[str, dict] = {}
            for r in w:
                d = per.setdefault(r["w"], {"buy": 0.0, "sell": 0.0, "bt": 0.0, "st": 0.0,
                                            "t_buy": None, "t_sell": None})
                if r["buy"]:
                    d["buy"] += r["sol"]
                    d["bt"] += r["base"]
                    d["t_buy"] = r["t"] if d["t_buy"] is None else min(d["t_buy"], r["t"])
                else:
                    d["sell"] += r["sol"]
                    d["st"] += r["base"]
                    d["t_sell"] = r["t"] if d["t_sell"] is None else max(d["t_sell"], r["t"])
            buy_sol = sum(d["buy"] for d in per.values()) or 1e-12
            early = {k2: d for k2, d in per.items() if d["bt"] > 0}
            feats = {
                "rotation_share": sum(d["buy"] for k2, d in per.items() if k2 in known) / buy_sol,
                "new_money_share": sum(d["buy"] for k2, d in per.items()
                                       if first_ever.get(k2, 0) >= lo) / buy_sol,
                "roundtrip_frac": sum(d["buy"] for d in per.values()
                                      if d["bt"] > 0 and d["st"] >= 0.9 * d["bt"]) / buy_sol,
                "hold_med_s": float(np.median([d["t_sell"] - d["t_buy"] for d in per.values()
                                               if d["t_buy"] is not None and d["t_sell"] is not None
                                               and d["t_sell"] >= d["t_buy"]] or [np.nan])),
                "float_turnover": sum(d["bt"] + d["st"] for d in per.values()) / 1e9,
                "recycled_30m": (sum(d["st"] for d in early.values())
                                 / max(sum(d["bt"] for d in early.values()), 1e-12)),
                "gross_sol": sum(d["buy"] + d["sell"] for d in per.values()),
                "n_wallets": len(per),
            }
            comp, tot = {}, 0.0
            for c, sgn in signs.items():
                v = feats["hold_med_s"] if c == "log_hold" else (
                    feats["float_turnover"] if c == "log_turnover" else feats[c])
                col = {"log_hold": "hold_med_s", "log_turnover": "float_turnover"}.get(c, c)
                if v != v:
                    comp[c] = None
                    tot += 0.5
                    continue
                pct = float((df[col].dropna() <= v).mean())
                comp[c] = pct if sgn > 0 else 1.0 - pct
                tot += comp[c]
            score = tot / len(signs)
            out.append({
                "coin": name, "bucket_end_unix": hi, "bucket_end_utc": _utc(hi),
                "pvp_score_live": score,
                "pvp_percentile_vs_corpus": float((df.pvp_score <= score).mean()),
                "components_pctile": comp, "raw": feats,
            })
    res = {"tape_source": "pump.fun /v2/coins/<mint>/trades",
           "known_rotator_hours": args.rot_hours, "scores": out}
    (OUT / "opnow.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float), flush=True)
    return 0


def _utc(t: float) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------
# stage: burst -- the latency-decay curve, as a POPULATION statistic
# ---------------------------------------------------------------------------------------
#
# The live duel gives a flow-burst firing 16.75 minutes before the host's top with a
# counterfactual +586% at 900 s for a 5-second reaction. That number is worth nothing on its
# own: it is one event, selected retrospectively, priced with a detector whose five knobs
# were set AFTER looking at the cascade. PROGRAM.md §9 rung 3 is explicit about what that
# machinery does -- a 1,458-cell grid manufactured a +6% winner from noise half the time.
#
# So the same rule, with the same constants, is run over every coin in the corpus, against a
# matched-instant control, and the curve is reported from that. The live case then appears
# where it belongs: as the motivating anecdote, with its own percentile against the
# population it came from.


def cmd_burst(args: argparse.Namespace) -> int:
    import numpy as np
    import pandas as pd

    con = _duck(args.threads, args.memory)
    T = _trades_rel(con)
    t0 = time.time()

    con.execute(
        f"""
        CREATE OR REPLACE TABLE mm AS
        SELECT mint_id, (t / 60)::INTEGER AS g,
               sum(CASE WHEN sol > 0 THEN sol ELSE 0 END) AS buy_sol,
               count(*) AS n
        FROM {T} GROUP BY 1, 2
        """
    )
    base_min = int(args.burst_base // 60)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE fires AS
        WITH life AS (SELECT mint_id, min(g) AS g0 FROM mm GROUP BY 1),
        w AS (
            SELECT m.mint_id, m.g, m.buy_sol, l.g0,
                   sum(m.buy_sol) OVER (PARTITION BY m.mint_id ORDER BY m.g
                                        RANGE BETWEEN {base_min} PRECEDING AND 1 PRECEDING)
                       AS base_sol
            FROM mm m JOIN life l USING (mint_id)
        )
        SELECT mint_id, g, buy_sol, base_sol, g0
        FROM w
        WHERE g - g0 >= {int(args.burst_min_age // 60)}
          AND buy_sol >= {args.burst_min_sol}
          AND buy_sol >= {args.burst_mult} * greatest(coalesce(base_sol, 0) / {base_min},
                                                      {args.burst_floor_sol})
        """
    )
    # one event per coin per cooldown, so a five-minute burst is not five events
    fires = con.execute("SELECT * FROM fires ORDER BY mint_id, g").df()
    cool = int(args.cooldown // 60)
    keep, last_m, last_g = [], None, -10**9
    for r in fires.itertuples():
        if r.mint_id != last_m or r.g - last_g >= cool:
            keep.append(r.Index)
            last_m, last_g = r.mint_id, r.g
    ev = fires.loc[keep].copy()
    ev["t_fire"] = ev.g * 60 + 60  # a minute bar is only knowable at its close
    print(f"[burst] {len(ev):,} events on {ev.mint_id.nunique():,} coins "
          f"({time.time() - t0:.0f}s)", flush=True)

    # TWO controls, because one is a knob (PROGRAM.md §3.13) -- and here the difference
    # between them is the entire result.
    #
    #   any_minute    the same coin at a random OTHER minute of its life. This is the NAIVE
    #                 control and it is nearly worthless: most minutes of most coins have no
    #                 trade, a no-trade minute marks at exactly 0.00%, and an arm of dead
    #                 rows "beats" an arm of live rows that are merely falling. That is
    #                 RESULT_imitation_signal.md §5.9's artifact, and it is the most
    #                 seductive one in this dataset.
    #   active_minute the same coin at a random minute that ALSO cleared the burst rule's own
    #                 volume floor. This isolates BURST from BUSY, which is the only
    #                 comparison that can answer whether the burst carries anything.
    rng = np.random.default_rng(args.seed)
    ages = con.execute(
        "SELECT mint_id, min(g) AS g0, max(g) AS g1 FROM mm GROUP BY 1"
    ).df().set_index("mint_id")
    ctrl = ev.copy()
    lo = ages.loc[ctrl.mint_id, "g0"].to_numpy()
    hi = ages.loc[ctrl.mint_id, "g1"].to_numpy()
    ctrl["g"] = lo + (rng.random(len(ctrl)) * np.maximum(hi - lo, 1)).astype(int)
    ctrl["t_fire"] = ctrl.g * 60 + 60

    act = con.execute(
        f"""
        SELECT m.mint_id, m.g FROM mm m JOIN (SELECT mint_id, min(g) AS g0 FROM mm GROUP BY 1) l
        USING (mint_id)
        WHERE m.buy_sol >= {args.burst_min_sol} AND m.g - l.g0 >= {int(args.burst_min_age // 60)}
        """
    ).df()
    fired = set(zip(ev.mint_id, ev.g, strict=True))
    act = act[[k not in fired for k in zip(act.mint_id, act.g, strict=True)]]
    pool = {m: grp.g.to_numpy() for m, grp in act.groupby("mint_id")}
    rows = []
    for r in ev.itertuples():
        cand = pool.get(r.mint_id)
        if cand is None or not len(cand):
            continue
        rows.append({"mint_id": r.mint_id, "g": int(rng.choice(cand))})
    actc = pd.DataFrame(rows)
    if len(actc):
        actc["t_fire"] = actc.g * 60 + 60
    print(f"[burst] active-minute control: {len(actc):,} matched rows", flush=True)

    def price_at(frame, tag):
        con.register(f"E_{tag}", frame[["mint_id", "t_fire"]].reset_index(drop=True))
        con.execute(f"CREATE OR REPLACE TABLE ev_{tag} AS SELECT * FROM E_{tag}")
        pts = [("lat", l) for l in args.latencies] + [("h", h) for h in args.horizons]
        sql = f"""
        SELECT e.mint_id, e.t_fire,
               {', '.join(f'a{i}.log_px AS px_{k}{v}'
                          for i, (k, v) in enumerate(pts))}
        FROM ev_{tag} e
        """
        for i, (k, v) in enumerate(pts):
            sql += (f" ASOF LEFT JOIN (SELECT mint_id, t, log_px FROM {T} "
                    f"WHERE log_px IS NOT NULL) a{i} "
                    f"ON a{i}.mint_id = e.mint_id AND a{i}.t <= e.t_fire + {v}\n")
        return con.execute(sql).df()

    out = {}
    for tag, frame in (("real", ev), ("ctrl_any", ctrl), ("ctrl_active", actc)):
        if not len(frame):
            out[tag] = []
            continue
        px = price_at(frame, tag)
        rows = []
        for lat in args.latencies:
            e = px[f"px_lat{lat}"]
            rec = {"latency_s": lat, "n": int(e.notna().sum())}
            for h in args.horizons:
                r = np.exp(px[f"px_h{h}"] - e) - 1.0
                r = r[np.isfinite(r)]
                rec[f"median_ret_{h}s_pct"] = float(np.median(r) * 100) if len(r) else None
                rec[f"mean_trimmed_ret_{h}s_pct"] = (
                    float(np.mean(np.clip(r, np.quantile(r, 0.05), np.quantile(r, 0.95))) * 100)
                    if len(r) > 20 else None)
                rec[f"share_beating_friction_{h}s"] = (
                    float((r > FRICTION).mean()) if len(r) else None)
            rows.append(rec)
        out[tag] = rows
    # ---- the paired statistic, which is the actual result ------------------------------
    # `real` and `ctrl_active` are two instants on the SAME coin, so the comparison that
    # matters is paired and clustered on the coin, not two marginal distributions.
    paired = {}
    if len(actc):
        pr = price_at(ev, "pr")
        pc = price_at(actc, "pc")
        pr = pr.groupby("mint_id").first()
        pc = pc.groupby("mint_id").first()
        common = pr.index.intersection(pc.index)
        rng2 = np.random.default_rng(args.seed)
        for lat in args.latencies:
            for h in args.horizons:
                a = np.exp(pr.loc[common, f"px_h{h}"] - pr.loc[common, f"px_lat{lat}"]) - 1
                b = np.exp(pc.loc[common, f"px_h{h}"] - pc.loc[common, f"px_lat{lat}"]) - 1
                m = np.isfinite(a) & np.isfinite(b)
                if m.sum() < 30:
                    continue
                dm = float(np.median(a[m]) - np.median(b[m])) * 100
                idx = np.flatnonzero(m.to_numpy())
                boot = []
                for _ in range(args.boot):
                    k = rng2.choice(idx, size=len(idx), replace=True)
                    boot.append(float(np.median(a.to_numpy()[k]) - np.median(b.to_numpy()[k])) * 100)
                paired[f"lat{lat}_h{h}"] = {
                    "n_coins": int(m.sum()),
                    "median_diff_pct": dm,
                    "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
                }
    res = {
        "paired_burst_minus_active_control": paired,
        "rule": {
            "window_s": 60, "baseline_s": args.burst_base, "multiple": args.burst_mult,
            "min_sol_in_window": args.burst_min_sol, "min_age_s": args.burst_min_age,
            "cooldown_s": args.cooldown, "friction": FRICTION,
        },
        "events": int(len(ev)), "coins": int(ev.mint_id.nunique()),
        "real": out["real"],
        "control_any_minute_same_coin": out["ctrl_any"],
        "control_active_minute_same_coin": out["ctrl_active"],
    }
    (OUT / "burst.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float), flush=True)
    return 0


# ---------------------------------------------------------------------------------------
# stage: duel -- the live arbitration-callout case study
# ---------------------------------------------------------------------------------------
#
# A DUEL is two or more same-name launches competing to be "the" coin. An ARBITRATION
# CALLOUT is a post that does not say "buy this" but "this one is the real one" -- a Schelling
# point declaration whose truth value is close to irrelevant and whose effectiveness at
# triggering a coordination cascade is the tradeable object.
#
# The house prior, from three studies (RESULT_callout_edge, RESULT_caller_wallets §4,
# RESULT_callout_volatility §5.3), is CHAIN FIRST: the post is a lagged, redundant view of a
# burst that already happened, by a median 26 s. This stage tests that prior on duel events,
# where the mechanism is different -- coordination rather than promotion -- and so the prior
# might not hold.
#
# The instrument is pump.fun's own ``/v2/coins/<mint>/trades``: wallet-level
# (userAddress, type, amountSol, timestamp) at 1 s resolution, keyless, cursor-paged, and it
# reaches back to a coin's birth. That is the same class of free retrospective endpoint
# RESULT_imitation_signal.md §2.3 found for candles, and it is strictly better -- it carries
# identity, which candles do not.

TRADES_API = "https://swap-api.pump.fun/v2/coins/{mint}/trades"
CANDLES_API = "https://swap-api.pump.fun/v1/coins/{mint}/candles?interval=1m&currency=SOL"
CACHE = REPO_ROOT / ".cache" / "pvp_vamps"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class _Fetched:
    """(payload, terminal) -- terminal means the server said no, not that we gave up."""

    __slots__ = ("payload", "terminal")

    def __init__(self, payload, terminal: bool):
        self.payload = payload
        self.terminal = terminal


def _http_json(url: str, timeout: float = 25.0, tries: int = 8) -> _Fetched:
    """Distinguishing a real 404 from a rate-limit is the whole point of this function.

    The first version of this study treated every failure as "no more pages" and silently
    reported **0 trades for five coins that had thousands**, because pump.fun answers a burst
    of cursor requests with 429/5xx rather than with an empty page. A paging loop that breaks
    on any falsy response manufactures exactly the null it is looking for.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    delay = 1.0
    for _ in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _Fetched(json.loads(r.read().decode()), True)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 410):
                return _Fetched(None, True)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
        except Exception:
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    return _Fetched(None, False)


def fetch_trades(
    mint: str, *, pause: float = 0.25, max_pages: int = 20000, until: float | None = None
) -> tuple[Path, bool]:
    """Page a mint's trade history (newest first) into a cached JSONL.

    Returns (path, complete). `complete` is False when the loop stopped on a transport
    failure rather than on the server saying there is nothing older -- a partial tape is
    usable but must never be reported as a coin's whole life.
    """
    d = CACHE / "trades"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{mint}.jsonl"
    seen: set[str] = set()
    if out.exists():
        with out.open() as fh:
            for line in fh:
                try:
                    seen.add(json.loads(line)["tx"])
                except Exception:
                    pass
    cursor = None
    complete = False
    with out.open("a") as fh:
        for _ in range(max_pages):
            url = TRADES_API.format(mint=mint) + "?limit=100"
            if cursor:
                url += f"&cursor={cursor}"
            res = _http_json(url)
            if res.payload is None:
                complete = res.terminal
                break
            trades = res.payload.get("trades") or []
            if not trades:
                complete = True
                break
            oldest = None
            for tr in trades:
                oldest = tr["timestamp"]
                if tr["tx"] in seen:
                    continue
                seen.add(tr["tx"])
                fh.write(json.dumps(tr) + "\n")
            pg = res.payload.get("pagination") or {}
            if not pg.get("hasMore") or not pg.get("nextCursor"):
                complete = True
                break
            if until is not None and oldest is not None and _iso_epoch(oldest) < until:
                complete = True
                break
            cursor = pg["nextCursor"]
            time.sleep(pause)
    return out, complete


def load_trades(mint: str) -> list[dict]:
    p = CACHE / "trades" / f"{mint}.jsonl"
    if not p.exists():
        return []
    rows = []
    with p.open() as fh:
        for line in fh:
            try:
                tr = json.loads(line)
            except Exception:
                continue
            rows.append(
                {
                    "t": _iso_epoch(tr["timestamp"]),
                    "w": tr["userAddress"],
                    "buy": tr["type"] == "buy",
                    "sol": float(tr.get("amountSol") or 0.0),
                    "base": float(tr.get("baseAmount") or 0.0),
                    "px": float(tr.get("priceSol") or 0.0),
                    "prog": tr.get("program"),
                }
            )
    rows.sort(key=lambda r: r["t"])
    return rows


def _iso_epoch(s: str) -> float:
    import datetime as _dt

    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _family_from_firehose(pattern: str, day: str) -> list[dict]:
    """Every launch on `day` whose name or symbol matches `pattern` (lowercased substring)."""
    p = REPO_ROOT / "state" / "firehose" / "new_token" / f"{day}.jsonl"
    out = []
    if not p.exists():
        return out
    pat = pattern.lower()
    with p.open() as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            pl = d.get("payload") or {}
            name = (pl.get("name") or "").lower()
            sym = (pl.get("symbol") or "").lower()
            if pat in name or pat in sym:
                out.append(
                    {
                        "mint": d["mint"],
                        "t_launch": _iso_epoch(d["t_ingest"]),
                        "name": pl.get("name"),
                        "symbol": pl.get("symbol"),
                        "deployer": pl.get("traderPublicKey"),
                        "dev_buy_sol": pl.get("solAmount"),
                        "uri": pl.get("uri"),
                    }
                )
    return out


def _second_series(rows, t0, t1):
    """Per-second buy/sell SOL and last price for one mint."""
    import numpy as np

    n = int(t1 - t0) + 1
    buy = np.zeros(n)
    sell = np.zeros(n)
    px = np.full(n, np.nan)
    nb = np.zeros(n)
    for r in rows:
        i = int(r["t"] - t0)
        if i < 0 or i >= n:
            continue
        if r["buy"]:
            buy[i] += r["sol"]
            nb[i] += 1
        else:
            sell[i] += r["sol"]
        if r["px"] > 0:
            px[i] = r["px"]
    # forward-fill price
    last = np.nan
    for i in range(n):
        if px[i] == px[i]:
            last = px[i]
        else:
            px[i] = last
    return buy, sell, px, nb


def _migration(rows_a, rows_b, t_lo, t_hi, delta: float):
    """SOL-weighted directed flow A -> B at each second: wallets that sold A in the trailing
    `delta` and bought B in the following `delta`, credited at min(sell, buy).

    `min` and not the product or the sum: a wallet that sold 5 SOL of A and bought 0.1 SOL of
    B moved 0.1 SOL of attention, not 5. This is the same conservative accounting the vamp
    stage uses on the bulk corpus, so the two numbers are comparable.
    """
    import numpy as np
    from collections import defaultdict

    sells = defaultdict(list)
    for r in rows_a:
        if not r["buy"]:
            sells[r["w"]].append((r["t"], r["sol"]))
    n = int(t_hi - t_lo) + 1
    out = np.zeros(n)
    wallets = np.zeros(n)
    for r in rows_b:
        if not r["buy"]:
            continue
        w = r["w"]
        if w not in sells:
            continue
        s = sum(v for tt, v in sells[w] if r["t"] - delta <= tt <= r["t"])
        if s <= 0:
            continue
        i = int(r["t"] - t_lo)
        if 0 <= i < n:
            out[i] += min(s, r["sol"])
            wallets[i] += 1
    return out, wallets


def cmd_duel(args: argparse.Namespace) -> int:
    """Reconstruct a duel's cascade at one-second resolution and price the latency decay."""
    import numpy as np

    fam_path = CACHE / f"family-{args.pattern}.json"
    fam = json.loads(fam_path.read_text())
    tapes = {}
    for m in fam:
        rows = load_trades(m["mint"])
        if len(rows) >= args.min_trades:
            tapes[m["mint"]] = rows
    meta = {m["mint"]: m for m in fam}
    print(f"[duel] {len(tapes)} branches with >= {args.min_trades} trades", flush=True)

    ranked = sorted(tapes, key=lambda m: -sum(r["sol"] for r in tapes[m] if r["buy"]))
    host = args.host or ranked[0]
    res: dict = {"pattern": args.pattern, "host": host, "branches": []}
    for m in ranked:
        rows = tapes[m]
        buyv = sum(r["sol"] for r in rows if r["buy"])
        res["branches"].append({
            "mint": m, "name": meta[m].get("name"), "symbol": meta[m].get("symbol"),
            "launch": meta[m].get("t_launch"), "trades": len(rows),
            "buy_sol": buyv, "wallets": len({r["w"] for r in rows}),
            "t_first": rows[0]["t"], "t_last": rows[-1]["t"],
            "px_first": rows[0]["px"], "px_max": max(r["px"] for r in rows),
            "t_px_max": max(rows, key=lambda r: r["px"])["t"],
        })

    # ---- pairwise migration, both directions -------------------------------------------
    hr = tapes[host]
    t_lo = min(r["t"] for r in hr)
    t_hi = max(r["t"] for r in hr)
    pairs = []
    for m in ranked:
        if m == host:
            continue
        rows = tapes[m]
        lo = min(t_lo, min(r["t"] for r in rows))
        hi = max(t_hi, max(r["t"] for r in rows))
        h2c, h2c_w = _migration(hr, rows, lo, hi, args.delta)
        c2h, c2h_w = _migration(rows, hr, lo, hi, args.delta)
        wh = {r["w"] for r in hr}
        wc = {r["w"] for r in rows}
        pairs.append({
            "clone": m, "name": meta[m].get("name"), "symbol": meta[m].get("symbol"),
            "clone_launch": meta[m].get("t_launch"),
            "shared_wallets": len(wh & wc),
            "clone_wallets": len(wc),
            "shared_share_of_clone_crowd": len(wh & wc) / max(len(wc), 1),
            "host_to_clone_sol": float(h2c.sum()),
            "clone_to_host_sol": float(c2h.sum()),
            "clone_buy_sol": sum(r["sol"] for r in rows if r["buy"]),
            "drain_share_of_clone_buys":
                float(h2c.sum()) / max(sum(r["sol"] for r in rows if r["buy"]), 1e-9),
            "t_first_migration": (float(lo + int(np.argmax(h2c > 0)))
                                  if (h2c > 0).any() else None),
        })
    res["pairs"] = sorted(pairs, key=lambda p: -p["host_to_clone_sol"])

    # ---- the host's own cascade, per minute around its peak ----------------------------
    buy, sell, px, nb = _second_series(hr, t_lo, t_hi)
    peak_i = int(np.nanargmax(px))
    t_peak = t_lo + peak_i
    res["host_peak_unix"] = float(t_peak)
    win = args.window_min * 60
    lo_i, hi_i = max(0, peak_i - win), min(len(px) - 1, peak_i + win)
    per_min = []
    for s in range(lo_i, hi_i + 1, 60):
        e = min(s + 60, hi_i + 1)
        per_min.append({
            "t_rel_min": (s - peak_i) / 60.0,
            "buy_sol": float(buy[s:e].sum()), "sell_sol": float(sell[s:e].sum()),
            "trades": int(nb[s:e].sum()),
            "px": float(px[e - 1]) if px[e - 1] == px[e - 1] else None,
            "ret_from_peak_pct": (float(px[e - 1] / px[peak_i] - 1) * 100
                                  if px[e - 1] == px[e - 1] else None),
        })
    res["host_cascade_per_minute"] = per_min

    # ---- rival-launch clustering around the host's peak --------------------------------
    launches = sorted(
        (m2["t_launch"], m2["mint"], m2.get("symbol")) for m2 in fam if m2.get("t_launch")
    )
    res["rival_launches_rel_peak_min"] = [
        {"mint": mm, "symbol": sy, "rel_min": (tt - t_peak) / 60.0}
        for tt, mm, sy in launches
    ]

    # ---- the latency-decay curve --------------------------------------------------------
    # Signal instant: the first second at which a live detector could have fired. Two
    # candidates, both computable from streams this desk already has:
    #   swarm    -- the k-th same-name launch lands on the firehose (~1.2 s p50 ingest lag,
    #               measured in RESULT_imitation_signal §5.2)
    #   drain    -- net cross-branch migration flips in the host's favour
    # Entry at signal + delta, exit under the wiggle book's own discipline, full friction.
    from shitcoims_paperdesk import friction as _fr  # noqa: F401  (presence check only)

    curves = {}
    for sig_name, t_sig in _duel_signals(fam, tapes, host, t_lo, t_hi, args).items():
        if t_sig is None:
            curves[sig_name] = None
            continue
        rows = []
        for lat in args.latencies:
            rows.append(_price_entry(px, t_lo, t_sig + lat, args))
        curves[sig_name] = {"signal_unix": t_sig,
                            "signal_rel_peak_min": (t_sig - t_peak) / 60.0,
                            "by_latency_s": dict(zip(args.latencies, rows, strict=True))}
    res["latency_decay"] = curves

    (OUT / f"duel-{args.pattern}.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float)[:6000], flush=True)
    return 0


def _duel_signals(fam, tapes, host, t_lo, t_hi, args) -> dict:
    import numpy as np

    out: dict = {}
    # (a) swarm onset: the k-th launch in the family
    ts = sorted(m["t_launch"] for m in fam if m.get("t_launch"))
    out[f"swarm_onset_k{args.k}"] = ts[args.k - 1] if len(ts) >= args.k else None
    # (b) drain reversal: first second at which trailing net migration into the host turns
    #     positive by more than `min_flow` SOL, after at least one rival exists
    hr = tapes[host]
    net = np.zeros(int(t_hi - t_lo) + 1)
    for m, rows in tapes.items():
        if m == host:
            continue
        c2h, _ = _migration(rows, hr, t_lo, t_hi, args.delta)
        h2c, _ = _migration(hr, rows, t_lo, t_hi, args.delta)
        n = len(net)
        net += c2h[:n] - h2c[:n]
    k = int(args.roll)
    roll = np.convolve(net, np.ones(k), mode="same")
    first_rival = min((m["t_launch"] for m in fam
                       if m.get("t_launch") and m["mint"] != host), default=None)
    lo = 0 if first_rival is None else max(0, int(first_rival - t_lo))
    hit = np.flatnonzero(roll[lo:] > args.min_flow)
    out["drain_reversal"] = float(t_lo + lo + hit[0]) if len(hit) else None
    # (c) FLOW BURST on the host. Neither (a) nor (b) fires anywhere near the cascade on the
    #     live case, and the thing that visibly does is a step change in buy flow: the host
    #     went from 0.89 SOL/min to 198 SOL/min inside one minute, four minutes before its
    #     top. So the detector the data supports is a burst detector on the host's own tape,
    #     not a swarm or a drain detector. Declared here rather than in the report, so it is
    #     a specified rule and not a curve drawn through one event.
    buy = np.zeros(int(t_hi - t_lo) + 1)
    for r in hr:
        if r["buy"]:
            i = int(r["t"] - t_lo)
            if 0 <= i < len(buy):
                buy[i] += r["sol"]
    w = int(args.burst_window)
    trail = np.convolve(buy, np.ones(w), mode="full")[: len(buy)]
    base_w = int(args.burst_base)
    base = np.convolve(buy, np.ones(base_w), mode="full")[: len(buy)]
    base_rate = np.concatenate([np.zeros(base_w), base[:-base_w]]) * (w / base_w)
    # The coin's own birth is the largest relative burst there will ever be (0 -> anything
    # is infinite), so the rule only speaks once the trailing baseline window is populated.
    ok = np.arange(len(buy)) >= max(base_w, int(args.burst_min_age))
    fire = np.flatnonzero(
        ok
        & (trail >= args.burst_min_sol)
        & (trail >= args.burst_mult * np.maximum(base_rate, args.burst_floor_sol))
    )
    out[f"flow_burst_{args.burst_mult:g}x"] = float(t_lo + fire[0]) if len(fire) else None
    return out


def _price_entry(px, t_lo, t_entry, args) -> dict:
    """Counterfactual round trip under the wiggle book's exit discipline and full friction."""
    import numpy as np

    i = int(t_entry - t_lo)
    if i < 0 or i >= len(px) or px[i] != px[i]:
        return {"error": "no price at entry"}
    entry = px[i]
    hold = int(args.hold_s)
    j_end = min(len(px) - 1, i + hold)
    seg = px[i: j_end + 1]
    seg = np.where(np.isnan(seg), entry, seg)
    ret = seg / entry - 1.0
    tp_hit = np.flatnonzero(ret >= args.take_profit)
    sl_hit = np.flatnonzero(ret <= -args.stop_loss)
    first_tp = tp_hit[0] if len(tp_hit) else np.inf
    first_sl = sl_hit[0] if len(sl_hit) else np.inf
    if first_tp < first_sl:
        gross, why, held = args.take_profit, "take_profit", int(first_tp)
    elif first_sl < first_tp:
        gross, why, held = -args.stop_loss, "stop", int(first_sl)
    else:
        gross, why, held = float(ret[-1]), "clock", len(ret) - 1
    raw = {}
    for h in (30, 60, 120, 300, 900):
        j = min(len(px) - 1, i + h)
        v = px[j]
        raw[f"raw_ret_{h}s_pct"] = (100 * (v / entry - 1.0)) if v == v else None
    return {
        "entry_px": float(entry), "gross_pct": 100 * gross,
        "net_pct": 100 * (gross - args.friction), "exit": why, "held_s": held,
        "max_favourable_pct": 100 * float(ret.max()),
        **raw,
    }


def cmd_duel_fetch(args: argparse.Namespace) -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    if args.mints:
        fam = [{"mint": m, "name": None, "symbol": None, "t_launch": None} for m in args.mints]
    else:
        fam = _family_from_firehose(args.pattern, args.day)
    print(f"[duel] {len(fam)} launches matching {args.pattern!r} on {args.day}", flush=True)
    for m in fam:
        p, complete = fetch_trades(m["mint"], pause=args.pause, until=args.until)
        n = sum(1 for _ in p.open())
        flag = "" if complete else "  ** PARTIAL (transport) **"
        print(f"[duel]   {m['mint']}  {m['name']!r}/{m['symbol']!r}  {n:,} trades{flag}",
              flush=True)
        m["n_trades"] = n
        m["tape_complete"] = complete
    (CACHE / f"family-{args.pattern}.json").write_text(json.dumps(fam, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--memory", default="16GB")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("flow", help="build the wallet-level trade tape with exact SOL")
    f.add_argument("--min-touches", type=int, default=MIN_TOUCHES)
    f.set_defaults(fn=cmd_flow)

    d = sub.add_parser("duel-fetch", help="page a duel family's trade tapes from pump.fun")
    d.add_argument("--pattern", default="")
    d.add_argument("--mints", nargs="*", default=None)
    d.add_argument("--day", default="2026-08-15")
    d.add_argument("--pause", type=float, default=0.25)
    d.add_argument("--until", type=float, default=None,
                   help="stop paging back past this unix time")
    d.set_defaults(fn=cmd_duel_fetch)

    r = sub.add_parser("rotation", help="build the rotation cohort")
    r.add_argument("--hot", type=int, default=200, help="hot coins per hour")
    r.add_argument("--k", type=int, default=3, help="distinct hot coins to qualify")
    r.add_argument("--lookback", type=int, default=6, help="trailing hours")
    r.add_argument("--jaccard", action="store_true", default=True)
    r.set_defaults(fn=cmd_rotation)

    p = sub.add_parser("panel", help="coin x 30-minute bucket panel")
    p.add_argument("--min-wallets", type=int, default=10)
    p.set_defaults(fn=cmd_panel)

    cl = sub.add_parser("classify", help="PvP state vs the recycled_30m baseline")
    cl.add_argument("--min-wallets", type=int, default=20)
    cl.add_argument("--split", type=float, default=0.70, help="birth-time quantile")
    cl.add_argument("--draws", type=int, default=400)
    cl.add_argument("--null-draws", type=int, default=24)
    cl.add_argument("--seed", type=int, default=17)
    cl.add_argument("--plant", type=float, default=0.35)
    cl.set_defaults(fn=cmd_classify)

    a = sub.add_parser("arena", help="eta components conditional on PvP state")
    a.add_argument("--min-wallets", type=int, default=20)
    a.add_argument("--split", type=float, default=0.70)
    a.add_argument("--seed", type=int, default=17)
    a.set_defaults(fn=cmd_arena)

    tt = sub.add_parser("transition", help="PvP transition as an exit signal")
    tt.add_argument("--min-wallets", type=int, default=20)
    tt.add_argument("--pvp-q", type=float, default=0.80)
    tt.add_argument("--early-buckets", type=int, default=2)
    tt.add_argument("--min-new-money", type=float, default=0.30)
    tt.add_argument("--min-hold", type=float, default=120.0)
    tt.add_argument("--min-base-wallets", type=int, default=100)
    tt.add_argument("--break-dd", type=float, default=0.50)
    tt.add_argument("--op-buckets", type=int, default=3)
    tt.add_argument("--null-draws", type=int, default=8)
    tt.add_argument("--seed", type=int, default=17)
    tt.set_defaults(fn=cmd_transition)

    vp = sub.add_parser("vamp", help="directed host->clone drain vs both nulls")
    vp.add_argument("--day", default="2026-08-14")
    vp.add_argument("--k", type=int, default=2)
    vp.add_argument("--window", type=float, default=1800.0)
    vp.add_argument("--null-draws", type=int, default=20)
    vp.add_argument("--seed", type=int, default=17)
    vp.add_argument("--match-tol", type=float, default=0.25)
    vp.set_defaults(fn=cmd_vamp)

    du = sub.add_parser("duel", help="reconstruct a duel cascade and price the latency decay")
    du.add_argument("--pattern", required=True)
    du.add_argument("--host", default=None)
    du.add_argument("--min-trades", type=int, default=20)
    du.add_argument("--delta", type=float, default=120.0, help="migration matching window (s)")
    du.add_argument("--window-min", type=int, default=30)
    du.add_argument("--k", type=int, default=3)
    du.add_argument("--roll", type=int, default=60)
    du.add_argument("--min-flow", type=float, default=0.5)
    du.add_argument("--burst-window", type=float, default=60)
    du.add_argument("--burst-base", type=float, default=1800)
    du.add_argument("--burst-mult", type=float, default=8.0)
    du.add_argument("--burst-min-sol", type=float, default=20.0)
    du.add_argument("--burst-floor-sol", type=float, default=1.0)
    du.add_argument("--burst-min-age", type=float, default=1800)
    du.add_argument("--latencies", type=int, nargs="*", default=[0, 1, 5, 15, 60, 300])
    du.add_argument("--hold-s", type=float, default=300.0)
    du.add_argument("--take-profit", type=float, default=0.06)
    du.add_argument("--stop-loss", type=float, default=0.175)
    du.add_argument("--friction", type=float, default=0.024)
    du.set_defaults(fn=cmd_duel)

    rg = sub.add_parser("regimes", help="five other readings of PvP")
    rg.add_argument("--min-wallets", type=int, default=20)
    rg.add_argument("--seed", type=int, default=17)
    rg.set_defaults(fn=cmd_regimes)

    bs = sub.add_parser("burst", help="latency-decay curve over the whole corpus")
    bs.add_argument("--burst-base", type=float, default=1800)
    bs.add_argument("--burst-mult", type=float, default=8.0)
    bs.add_argument("--burst-min-sol", type=float, default=20.0)
    bs.add_argument("--burst-floor-sol", type=float, default=1.0)
    bs.add_argument("--burst-min-age", type=float, default=1800)
    bs.add_argument("--cooldown", type=float, default=3600)
    bs.add_argument("--latencies", type=int, nargs="*", default=[0, 1, 5, 15, 60, 300])
    bs.add_argument("--horizons", type=int, nargs="*", default=[300, 900, 3600])
    bs.add_argument("--seed", type=int, default=17)
    bs.add_argument("--boot", type=int, default=400)
    bs.set_defaults(fn=cmd_burst)

    op = sub.add_parser("opnow", help="score the operator's four coins on today's live flow")
    op.add_argument("--min-wallets", type=int, default=20)
    op.add_argument("--buckets", type=int, default=4)
    op.add_argument("--rot-hours", type=int, default=6)
    op.set_defaults(fn=cmd_opnow)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
