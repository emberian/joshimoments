#!/usr/bin/env python3
"""Unrealized PnL: per-wallet cost basis per coin, and what its distribution is good for.

THE OPERATOR'S QUESTION, verbatim
---------------------------------
    "have we ever tried learning a model against the distribution of unrealized profit
     (this feeds into wallet correlation analysis, we could be hypothesizing a wallet is
     controlled by a given actor...)"

Answer before this module: **never**. Every study in ``studies/`` prices *flow* -- who bought,
who sold, how much SOL moved -- and none of them carries a wallet's own entry price forward.
Cost basis is the one state variable that makes a holder's position *asymmetric*: two wallets
holding the same bag at the same price are different animals if one is up 4x and the other is
down 60%, and every folk claim about memecoin structure ("support at the bundler's entry",
"mercenaries stop out instantly", "the chart remembers where people got in") is a claim about
the cost-basis distribution that nobody here has ever measured.

WHAT THIS BUILDS
----------------
For every (coin, wallet) in the cohort, the **average-cost basis trajectory** -- basis and
position after every one of that wallet's fills -- and from it two derived objects:

* ``basis`` -- one row per trade leg, carrying ``basis_before`` (SOL per raw token),
  ``qty_before``, the fill's own effective price, and therefore the wallet's unrealized PnL
  at the instant it acted. On a SELL this is the **realization point**: the level of unrealized
  profit at which this wallet chose to take money off the table.
* ``holders`` -- for a (coin, t), the supply-weighted basis distribution across live holders,
  which is the object the four questions below actually consume.

WHY AVERAGE COST AND NOT FIFO
------------------------------
Both are defensible; the choice is not arbitrary and it is not a tax question.

*Average cost is the representation the agent acts on.* Every retail-facing pump.fun front end
and every Telegram execution bot (Trojan, BullX, Photon, Axiom, Maestro) displays exactly one
P/L number per position, computed as average cost. A take-profit preset is typed against that
number. FIFO models a tax lot; nothing in this market has a tax lot. If the object of study is
"at what perceived P/L does this wallet sell", the perception is average-cost by construction.

*It is also the only one that is a window function.* FIFO needs a per-wallet lot queue, i.e. a
sequential scan over ~10^8 rows in Python. Average cost is a linear recursion (see ``BASIS
RECURSION`` below) and closes in DuckDB.

**Sensitivity is measured, not asserted.** ``basis --check`` brute-forces both conventions on a
random wallet sample and reports the distribution of ``|pnl_fifo - pnl_avgcost|``. They coincide
exactly whenever a wallet's position episode contains at most one buy before a sell, which is
the modal shape here; they diverge only for wallets that scale in and out repeatedly.

BASIS RECURSION, AND HOW IT BECOMES A WINDOW FUNCTION
------------------------------------------------------
Under average cost, per-unit basis ``b`` changes on buys and *never* on sells::

    buy  of D at price p, from position q:   b' = b * q/(q+D) + p * D/(q+D)
    sell of D:                               b' = b

which is a linear recursion ``b_n = a_n b_{n-1} + c_n`` with ``a_n = q_n/(q_n+D_n)`` and
``c_n = p_n D_n/(q_n+D_n)`` on buys, and ``a_n = 1, c_n = 0`` on sells. Its closed form is::

    A_n = prod_{i<=n} a_i          b_n = A_n * sum_{i<=n} c_i / A_i

Both are window aggregates (``A`` as ``exp(cumsum(log a))``). ``a_n = 0`` exactly when the
wallet buys from a flat position, which is the natural **episode** boundary -- and rather than
let a zero poison the running product, the series is *partitioned* at those points, so each
episode is an independent basis history. That is also the correct semantics: a wallet that
fully exits and re-enters has a new entry price, not a blended one.

``q`` itself is a plain cumulative sum of the wallet's own deltas, so nothing here needs a
sequential pass. Correctness is checked against a literal Python recursion in ``basis --check``.

WHERE THE PRICE COMES FROM
--------------------------
``studies/operator_crime.py`` established that on a pump.fun bonding curve ``log p = log k -
2 log v_tok`` -- log price is an exact affine function of the curve's own token balance, which
is the only leg on chain (the curve holds *native* SOL in the PDA, not a token balance).
``studies/pvp_vamps.py`` took the same identity one step further to the exact SOL leg::

    sol_lamports = K * (1/v_tok_after - 1/v_tok_before)        K = 3.219e25

and that is what this module uses, with the per-mint offset ``v_tok = curve_balance +
(1.073e15 - initial_curve_balance)`` because two curve configurations are present in this
corpus (7.931e14 and 1.0e15 of real supply at launch). Verified to 0.118% median against the
boards tape's virtual reserves (``operator_crime.py verify``).

TWO PRICES, DELIBERATELY DIFFERENT
-----------------------------------
* **Basis** uses the fill's own *effective* price ``|sol| / |delta_raw|`` -- what the wallet
  actually paid, impact included.
* **Mark** uses the curve's *marginal* price ``K / v_tok^2`` -- what the next infinitesimal
  unit is worth.

That asymmetry is real (you paid impact going in and would pay it again coming out) and it is
why the rug-fuel gauge is computed on the marginal mark: the question there is what the supply
is worth *at the quote*, not what it would fetch on exit.

TRANSFERS ARE NOT TRADES, AND THEY ARE NOT IGNORED
---------------------------------------------------
A wallet-to-wallet transfer has no counterparty leg, so it is not a fill and carries no price.
Bundlers distribute to sybils this way and airdrops arrive this way, so silently dropping them
would make a sybil's position appear from nowhere and silently pricing them at zero would make
every airdrop recipient look maximally in profit. Both are recorded: every (mint, wallet) gets
``xfer_in_raw`` / ``xfer_out_raw`` and a ``contaminated`` flag when transfer inflow exceeds 1%
of gross acquisition. Contaminated wallet-coins are excluded from the realization-policy
fingerprint (§2) and *reported separately* in the supply gauges (§4), never quietly folded in.

COMMANDS
--------
``flow``     per-(mint, wallet, tx) trade legs with exact SOL, cohort coins        (~15 min)
``basis``    the average-cost trajectory; ``--check`` brute-forces FIFO vs avgcost
``holders``  supply-weighted basis distribution snapshots per coin
``describe`` the realization distribution, the standing book, and the round-number test
``hazard``   P(sell in the next minute | unrealized PnL), on a real risk set
``q1``       basis-density modes vs price reversals, against a rotation null
``q2``       realization-policy embedding, clustering, tooling-vs-actor controls
``q3``       loss-tail shape as a PvP/community feature (a feature, not a classifier)
``q4``       the rug-fuel gauge, and the operator's four coins scored today
``report``   everything, in the order RESULT_unrealized_pnl.md reports it

Invocation is always ``uv run --group research python -m studies.unrealized_pnl <cmd>``.
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
OUT = REPO_ROOT / "state" / "upnl"

WSOL = "So11111111111111111111111111111111111111112"

# The curve constants. Both configurations in this corpus share the virtual reserves and
# differ only in real supply at launch, so the offset is derived per mint from the curve's
# own opening balance rather than assumed. See operator_crime.py lines 220-263.
V_TOK_VIRT = 1.073e15  # raw token units
V_SOL_VIRT = 3.0e10  # lamports
K_CURVE = V_SOL_VIRT * V_TOK_VIRT  # 3.219e25
LAMPORTS = 1e9

#: Marino/Lillo's own conditioning: surviving to 30 swaps quadruples the graduation base rate
#: and is the cheapest liveness filter in the literature. 67,710 of 266,928 born-in-window
#: coins clear it.
MIN_TOUCHES = 30

#: A position this small is flat. 1e6 raw = 1 whole token at 6 decimals; a 1e15-supply coin
#: makes that 1e-9 of supply, far below any economically meaningful holding, and it absorbs
#: the rounding dust that ATA closes leave behind.
DUST_RAW = 1_000_000

OPERATOR_COINS = {
    "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
}


def _out() -> Path:
    """Output root. Overridable so the same code runs on a compute box and syncs back."""
    return Path(os.environ.get("UPNL_OUT", str(OUT)))


def _duck(threads: int = 4, memory: str = "6GB"):
    """A memory-disciplined connection.

    The default cap is 6 GB and the default thread count is 4 because this repository's
    research lanes share one laptop, and a 139-million-row intermediate held as an in-memory
    TABLE is exactly how a fold turns into an out-of-memory kill. Every stage below therefore
    streams through parquet on disk rather than materialising tables, and
    ``preserve_insertion_order=false`` lets duckdb drop the ordering buffers that make a large
    ``COPY`` allocate proportional to its output.
    """
    try:
        import duckdb
    except ImportError:
        raise SystemExit(
            "needs duckdb: `uv run --group research`. The corpus is 28 GB of nested parquet."
        ) from None
    out = _out()
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"PRAGMA memory_limit='{memory}'")
    con.execute(f"PRAGMA temp_directory='{tmp}'")
    con.execute("PRAGMA preserve_insertion_order=false")
    con.execute("PRAGMA max_temp_directory_size='400GB'")
    return con


def _ledger_glob(days: str | None = None) -> str:
    env = os.environ.get("UPNL_LEDGER")
    root = Path(env) if env else LEDGER
    pat = days or "*"
    return f"read_parquet('{root}/day={pat}.parquet')"


def _copy(con, sql: str, out: Path, label: str, order: str = "") -> int:
    """Stream a query straight to parquet. Never materialise it as a table."""
    t0 = time.time()
    tmp = out.parent / f".tmp-{out.name}"
    con.execute(
        f"COPY ({sql}{(' ORDER BY ' + order) if order else ''}) TO '{tmp}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)"
    )
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"  {label}: {n:,} rows in {time.time() - t0:.0f}s -> {out.name}", flush=True)
    return n


def _coins_path() -> str:
    env = os.environ.get("UPNL_COINS")
    return env if env else str(COINS)


# =====================================================================================
# flow
# =====================================================================================


def cmd_flow(args: argparse.Namespace) -> int:
    """Per-(mint, wallet, transaction) trade legs with the exact SOL leg attached.

    The counterparty of a mint is any owner touching >=20% of that mint's transactions and at
    least 10 of them: on a bonding-curve coin that is the curve and nothing else, on a migrated
    coin it admits the PumpSwap pool too. Transactions with two counterparty legs are the
    migration transfer and are dropped -- pricing one as a trade would book the entire residual
    curve supply as a single enormous buy at a near-zero price.

    Legs from transactions with NO counterparty leg are transfers. They are not trades and are
    not priced, but they are kept as events, because a sybil's bag arriving by transfer is the
    whole mechanism behind the rug-fuel gauge and dropping it drives positions negative.

    MEMORY. Every intermediate goes to parquet under ``$UPNL_OUT/stage/`` and every later step
    reads it back with ``read_parquet``. Nothing is held as a duckdb TABLE. That is not
    fastidiousness: the first version of this function built a 139-million-row ``led`` table and
    was killed by its own memory limit at the next join.
    """
    con = _duck(args.threads, args.memory)
    t0 = time.time()
    out = _out()
    st = out / "stage"
    st.mkdir(parents=True, exist_ok=True)
    led_glob = _ledger_glob(args.days)

    _copy(
        con,
        f"""
        SELECT mint, curve_owner, birth_time, graduated, peak_mcap_sol, final_mcap_sol,
               lifetime_s, curve_touches, drawdown_from_peak, dev_buy_share, n_snipers,
               t_peak, t_last, time_to_peak_s
        FROM read_parquet('{_coins_path()}')
        WHERE curve_touches >= {args.min_touches}
        """,
        out / "cohort.parquet",
        "cohort",
    )
    cohort = out / "cohort.parquet"

    op = ",".join(f"'{m}'" for m in OPERATOR_COINS.values())
    _copy(
        con,
        f"""
        SELECT mint, false AS operator_coin FROM read_parquet('{cohort}')
        UNION ALL
        SELECT DISTINCT mint, true FROM (SELECT unnest([{op}]) AS mint)
        WHERE mint NOT IN (SELECT mint FROM read_parquet('{cohort}'))
        """,
        st / "study_mints.parquet",
        "study_mints",
    )
    sm = st / "study_mints.parquet"

    # One row per (mint, owner, transaction): the ledger is one row per token ACCOUNT, and a
    # wallet may hold two accounts for the same mint, so netting here is not optional.
    _copy(
        con,
        f"""
        SELECT l.mint, l.owner, l.block_slot, l.tx_index, any_value(l.block_time) AS block_time,
               sum(l.delta_raw) AS delta_raw
        FROM {led_glob} l
        SEMI JOIN read_parquet('{sm}') s ON s.mint = l.mint
        WHERE l.delta_raw != 0
        GROUP BY 1, 2, 3, 4
        HAVING sum(l.delta_raw) != 0
        """,
        st / "led.parquet",
        "led",
    )
    led = st / "led.parquet"

    _copy(
        con,
        f"""
        SELECT mint, owner FROM (
          SELECT o.mint, o.owner, o.n_tx, m.n_tx AS m_tx
          FROM (SELECT mint, owner, count(*) AS n_tx FROM read_parquet('{led}') GROUP BY 1, 2) o
          JOIN (SELECT mint, count(*) AS n_tx
                FROM (SELECT DISTINCT mint, block_slot, tx_index FROM read_parquet('{led}'))
                GROUP BY 1) m USING (mint))
        WHERE n_tx >= 10 AND n_tx >= 0.20 * m_tx
        """,
        st / "cp.parquet",
        "counterparties",
    )
    cp = st / "cp.parquet"

    # The counterparty's own balance path. `bal0` is its peak balance, which for a bonding
    # curve is the supply it was funded with and therefore fixes the virtual-reserve offset.
    _copy(
        con,
        f"""
        SELECT l.mint, l.owner, l.block_slot, l.tx_index, l.block_time, l.delta_raw AS cp_delta,
               sum(l.delta_raw) OVER (PARTITION BY l.mint, l.owner
                                      ORDER BY l.block_slot, l.tx_index
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                   AS bal_after
        FROM read_parquet('{led}') l
        SEMI JOIN read_parquet('{cp}') c ON c.mint = l.mint AND c.owner = l.owner
        """,
        st / "cppath.parquet",
        "cppath",
    )
    cppath = st / "cppath.parquet"
    _copy(
        con,
        f"SELECT mint, owner, max(bal_after) AS bal0 FROM read_parquet('{cppath}') GROUP BY 1, 2",
        st / "cpparam.parquet",
        "cpparam",
    )
    cpparam = st / "cpparam.parquet"

    # WSOL legs, needed only for counterparty owners (the pool route). Restricting the scan to
    # the counterparty owner set rather than to every transaction of every study mint is what
    # keeps this from being a second full-ledger hash join.
    _copy(
        con,
        f"""
        SELECT l.owner, l.block_slot, l.tx_index, sum(l.delta_raw) AS wsol_delta
        FROM {led_glob} l
        SEMI JOIN (SELECT DISTINCT owner FROM read_parquet('{cp}')) c ON c.owner = l.owner
        WHERE l.mint = '{WSOL}' AND l.delta_raw != 0
        GROUP BY 1, 2, 3
        """,
        st / "wsol.parquet",
        "wsol legs",
    )
    wsol = st / "wsol.parquet"

    _copy(
        con,
        f"""
        SELECT mint, block_slot, tx_index, count(*) AS n_cp_legs,
               any_value(owner) AS cp_owner, any_value(cp_delta) AS cp_delta,
               any_value(bal_after) AS bal_after
        FROM read_parquet('{cppath}') GROUP BY 1, 2, 3
        """,
        st / "txcp.parquet",
        "txcp",
    )
    txcp = st / "txcp.parquet"

    # Trades: a trader leg in a transaction with exactly one counterparty leg.
    #
    # TWO ROUTES AND TWO MARKS, and the split is not a detail. In this cohort 30,742 mints
    # trade only against a bonding curve and 2,230 trade against a PumpSwap pool -- and the
    # 6.8% that migrated carry ~70% of all fills, because graduation is exactly the event that
    # produces sustained volume. Getting the pool route wrong would therefore mean getting most
    # of the data wrong, including all four of the operator's own coins.
    #
    # * ``sol`` is EXACT on both routes. On the curve it is the constant-product identity
    #   ``K*(1/v_after - 1/v_before)``; in the pool it is the pool's own observed WSOL vault
    #   delta. Neither needs a reserve level, so **cost basis is exact everywhere**.
    # * ``mark`` is the harder half. On the curve the marginal price falls straight out of the
    #   affine identity. In a pool it would need the reserve *levels*, and those are NOT
    #   recoverable here: a running sum of vault deltas is offset by whatever the vault held
    #   before its first observed transaction, and for a coin that migrated before the window
    #   that offset is unknown. Worse, a boosted PumpSwap pool prices against
    #   ``pool_quote + virtual_quote_reserves`` and the virtual term lives in ``log_messages``,
    #   which is empty for this corpus (see scripts/pump_history.py).
    #
    #   So the pool route is marked at **last traded price** -- the previous fill's effective
    #   price on that mint. It needs no reserves, it is built from observed transfers only, and
    #   it is what every holder's screen actually shows. Its error against a true marginal
    #   price is measured rather than assumed: on the CURVE route both marks exist, and
    #   `flow` reports their disagreement, which is the error bar carried into the pool route.
    n_tr = _copy(
        con,
        f"""
        WITH j AS (
            SELECT t.mint, t.block_slot, t.tx_index, t.block_time, t.owner, t.delta_raw,
                   x.cp_owner, x.cp_delta, x.bal_after, p.bal0, w.wsol_delta,
                   sum(abs(t.delta_raw)) OVER (PARTITION BY t.mint, t.block_slot, t.tx_index)
                       AS tx_abs
            FROM read_parquet('{led}') t
            JOIN read_parquet('{txcp}') x USING (mint, block_slot, tx_index)
            JOIN read_parquet('{cpparam}') p ON p.mint = x.mint AND p.owner = x.cp_owner
            LEFT JOIN read_parquet('{wsol}') w ON w.block_slot = t.block_slot
                                              AND w.tx_index = t.tx_index
                                              AND w.owner = x.cp_owner
            ANTI JOIN read_parquet('{cp}') c ON c.mint = t.mint AND c.owner = t.owner
            WHERE x.n_cp_legs = 1
        ),
        v AS (
            SELECT *, bal_after + ({V_TOK_VIRT} - bal0) AS v_after,
                      bal_after - cp_delta + ({V_TOK_VIRT} - bal0) AS v_before
            FROM j
        ),
        s AS (
            SELECT mint, owner, block_slot, tx_index, block_time, delta_raw, cp_owner,
                   bal_after AS cp_bal_after,
                   CASE WHEN wsol_delta IS NOT NULL THEN 'pool' ELSE 'curve' END AS route,
                   CASE WHEN wsol_delta IS NOT NULL
                        THEN (wsol_delta / {LAMPORTS}) * (abs(delta_raw) / nullif(tx_abs, 0))
                        ELSE ({K_CURVE} * (1.0 / nullif(v_after, 0) - 1.0 / nullif(v_before, 0))
                              / {LAMPORTS}) * (abs(delta_raw) / nullif(tx_abs, 0))
                   END AS sol,
                   CASE WHEN wsol_delta IS NULL AND v_after > 0
                        THEN {K_CURVE} / (v_after * v_after) / {LAMPORTS} END AS curve_mark_after,
                   CASE WHEN wsol_delta IS NULL AND v_before > 0
                        THEN {K_CURVE} / (v_before * v_before) / {LAMPORTS}
                   END AS curve_mark_before
            FROM v
        ),
        lt AS (
            SELECT *,
                   CASE WHEN delta_raw <> 0 AND sol IS NOT NULL
                        THEN abs(sol) / abs(delta_raw) END AS px
            FROM s
        ),
        lt2 AS (
            -- last traded price on this mint, strictly before this transaction
            SELECT *,
                   lag(px) OVER (PARTITION BY mint ORDER BY block_slot, tx_index) AS px_prev
            FROM lt
        )
        SELECT mint, owner, block_slot, tx_index, block_time, delta_raw, cp_owner,
               cp_bal_after, route, sol, px,
               curve_mark_after, curve_mark_before,
               coalesce(curve_mark_after, px) AS mark_after,
               coalesce(curve_mark_before, px_prev) AS mark_before,
               CASE WHEN curve_mark_after IS NOT NULL THEN 'curve_marginal'
                    WHEN px IS NOT NULL THEN 'last_trade' END AS mark_src
        FROM lt2
        """,
        st / "trades.parquet",
        "trades",
    )
    trades = st / "trades.parquet"
    bad = con.execute(
        f"SELECT count(*) FROM read_parquet('{trades}') "
        "WHERE sol IS NOT NULL AND sign(sol) != sign(delta_raw)"
    ).fetchone()[0]
    print(
        f"[flow]   sign disagreements (token leg vs SOL leg): {bad:,} / {n_tr:,} "
        f"= {100.0 * bad / max(n_tr, 1):.3f}%",
        flush=True,
    )

    # INSTRUMENT CHECK: how far is last-traded-price from a true marginal price? On the curve
    # route both are computable, so the disagreement is measurable there -- and that measured
    # spread is the error bar the pool route inherits, since the pool route has only the
    # last-trade mark. Reported, not assumed.
    agree = con.execute(
        f"""
        SELECT count(*) AS n,
               median(abs(px_prev_lt / curve_mark_before - 1)) AS med_abs_rel,
               quantile_cont(abs(px_prev_lt / curve_mark_before - 1), 0.90) AS p90_abs_rel,
               quantile_cont(abs(px_prev_lt / curve_mark_before - 1), 0.99) AS p99_abs_rel
        FROM (
          SELECT curve_mark_before,
                 lag(px) OVER (PARTITION BY mint ORDER BY block_slot, tx_index) AS px_prev_lt
          FROM read_parquet('{trades}') WHERE route = 'curve' AND px > 0
        ) WHERE curve_mark_before > 0 AND px_prev_lt > 0"""
    ).fetchdf()
    print(f"[flow]   last-trade vs curve-marginal mark:\n{agree.to_string(index=False)}", flush=True)
    (out / "mark_agreement.json").write_text(
        json.dumps(agree.to_dict(orient="records")[0], indent=2, default=str)
    )

    # Events = priced fills + unpriced transfers, one stream, ordered for the basis window.
    _copy(
        con,
        f"""
        SELECT mint, owner, block_slot, tx_index, block_time, delta_raw, sol,
               mark_before, mark_after, mark_src, route, cp_bal_after, false AS is_xfer
        FROM read_parquet('{trades}')
        WHERE sol IS NOT NULL AND abs(sol) < 1e6 AND sign(sol) = sign(delta_raw)
        UNION ALL
        SELECT t.mint, t.owner, t.block_slot, t.tx_index, t.block_time, t.delta_raw,
               NULL, NULL, NULL, NULL, 'xfer', NULL, true
        FROM read_parquet('{led}') t
        ANTI JOIN read_parquet('{txcp}') x ON x.mint = t.mint AND x.block_slot = t.block_slot
                                          AND x.tx_index = t.tx_index
        ANTI JOIN read_parquet('{cp}') c ON c.mint = t.mint AND c.owner = t.owner
        """,
        out / "events.parquet",
        "events",
        order="mint, owner, block_slot, tx_index",
    )

    _copy(
        con,
        f"""
        SELECT mint, owner,
               sum(CASE WHEN delta_raw > 0 THEN delta_raw ELSE 0 END) AS xfer_in_raw,
               sum(CASE WHEN delta_raw < 0 THEN -delta_raw ELSE 0 END) AS xfer_out_raw,
               count(*) AS n_xfer
        FROM read_parquet('{out / "events.parquet"}') WHERE is_xfer GROUP BY 1, 2
        """,
        out / "xfer.parquet",
        "xfer summary",
    )

    # The per-mint MARGINAL price path. Two routes, and which applies is a property of the
    # counterparty rather than of the coin: a coin that migrated mid-window has both, the
    # bonding curve pricing off its own token balance and the PumpSwap pool off its two vaults.
    _copy(
        con,
        f"""
        WITH wp AS (
            SELECT owner, block_slot, tx_index,
                   sum(wsol_delta) OVER (PARTITION BY owner ORDER BY block_slot, tx_index
                                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                       AS wsol_bal
            FROM read_parquet('{wsol}')
        )
        SELECT p.mint, p.owner, p.block_slot, p.tx_index, p.block_time, p.bal_after,
               (p.owner = coalesce(c.curve_owner, '')) AS is_curve,
               CASE
                 WHEN p.owner = coalesce(c.curve_owner, '')
                      AND p.bal_after + ({V_TOK_VIRT} - q.bal0) > 0
                   THEN {K_CURVE} / pow(p.bal_after + ({V_TOK_VIRT} - q.bal0), 2) / {LAMPORTS}
                 WHEN w.wsol_bal > 0 AND p.bal_after > 0
                   THEN (w.wsol_bal / {LAMPORTS}) / p.bal_after
               END AS mark
        FROM read_parquet('{cppath}') p
        JOIN read_parquet('{cpparam}') q USING (mint, owner)
        LEFT JOIN read_parquet('{cohort}') c USING (mint)
        LEFT JOIN wp w ON w.owner = p.owner AND w.block_slot = p.block_slot
                      AND w.tx_index = p.tx_index
        """,
        out / "pricepath.parquet",
        "pricepath",
        order="mint, block_slot, tx_index",
    )

    print(f"[flow] done ({time.time() - t0:.0f}s) -> {out}", flush=True)
    return 0


# =====================================================================================
# basis
# =====================================================================================

#: The closed form of the average-cost recursion, as a window query. `a` is the dilution
#: factor and `c` the contribution; see BASIS RECURSION in the module docstring. Transfers
#: (px IS NULL) enter as ACQUISITIONS AT ZERO COST, which preserves total cost and is the
#: conservative reading for the rug-fuel gauge: a bag that arrived as a gift is free supply.
BASIS_SQL = """
WITH ev AS (
    SELECT mint, owner, block_slot, tx_index, block_time, delta_raw, sol, route, mark_src,
           cp_bal_after, mark_before, mark_after,
           CASE WHEN sol IS NOT NULL AND delta_raw <> 0
                THEN abs(sol) / abs(delta_raw) END AS px
    FROM read_parquet('{events}')
),
q AS (
    SELECT *,
           sum(delta_raw) OVER w AS qty_after,
           sum(delta_raw) OVER w - delta_raw AS qty_before_raw,
           row_number() OVER w AS rn
    FROM ev
    WINDOW w AS (PARTITION BY mint, owner ORDER BY block_slot, tx_index
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
seg AS (
    -- An episode opens on any acquisition from a flat book. `qty_before` is floored at zero
    -- so a book driven negative by an unobserved inflow cannot make the dilution factor
    -- negative; the `neg_qty` flag below records that it happened.
    SELECT *,
           greatest(qty_before_raw, 0) AS qty_before,
           CASE WHEN delta_raw > 0 AND greatest(qty_before_raw, 0) <= {dust} THEN 1 ELSE 0 END
               AS is_open
    FROM q
),
epi AS (
    SELECT *,
           sum(is_open) OVER (PARTITION BY mint, owner ORDER BY block_slot, tx_index
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
    FROM epi
    WHERE episode >= 1
),
la AS (
    SELECT *,
           sum(ln(a)) OVER w AS log_a_cum
    FROM ac
    WINDOW w AS (PARTITION BY mint, owner, episode ORDER BY block_slot, tx_index
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
bs AS (
    SELECT *,
           -- b_n = A_n * sum_{{i<=n}} c_i / A_i, evaluated in log space so the running
           -- product never has to be materialised as a denormal.
           exp(log_a_cum) * sum(c * exp(-log_a_cum)) OVER w AS basis_after,
           min(log_a_cum) OVER w AS log_a_min
    FROM la
    WINDOW w AS (PARTITION BY mint, owner, episode ORDER BY block_slot, tx_index
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT mint, owner, episode, block_slot, tx_index, block_time, delta_raw, sol, px, route,
       mark_src, qty_before, qty_after, cp_bal_after, mark_before, mark_after,
       basis_after,
       lag(basis_after) OVER (PARTITION BY mint, owner, episode
                              ORDER BY block_slot, tx_index) AS basis_before_lag,
       is_open, rn, log_a_min, qty_before_raw
FROM bs
"""


def cmd_basis(args: argparse.Namespace) -> int:
    """The average-cost trajectory: basis and position after every fill, per (coin, wallet).

    Output rows carry the wallet's state *at the instant it acted*, which is the object the
    operator asked for. On a SELL, ``upnl_at_action`` is the unrealized-profit level at which
    that wallet chose to realize -- one point in its realization policy.
    """
    con = _duck(args.threads, args.memory)
    t0 = time.time()

    events = _out() / "events.parquet"
    n_ev = con.execute(f"SELECT count(*) FROM read_parquet('{events}')").fetchone()[0]
    print(f"[basis] {n_ev:,} events ({time.time() - t0:.0f}s)", flush=True)

    sql = BASIS_SQL.format(events=events, dust=DUST_RAW)
    out = _out() / "basis.parquet"
    con.execute(
        f"""
        COPY (
          SELECT mint, owner, episode, block_slot, tx_index, block_time, delta_raw, sol, px,
                 route, mark_src, qty_before, qty_after, cp_bal_after, mark_before, mark_after,
                 basis_after,
                 coalesce(basis_before_lag, basis_after) AS basis_before,
                 -- the wallet's unrealized PnL just before it acted, as a fraction
                 CASE WHEN coalesce(basis_before_lag, 0) > 0 AND mark_before > 0 AND is_open = 0
                      THEN mark_before / basis_before_lag - 1.0 END AS upnl_at_action,
                 -- and what a sell actually banked against that basis
                 CASE WHEN delta_raw < 0 AND coalesce(basis_before_lag, 0) > 0 AND px > 0
                      THEN px / basis_before_lag - 1.0 END AS realized_frac,
                 CASE WHEN delta_raw < 0 AND coalesce(basis_before_lag, 0) > 0
                      THEN -delta_raw * (px - basis_before_lag) END AS realized_sol,
                 log_a_min, qty_before_raw
          FROM ({sql})
          ORDER BY mint, owner, block_slot, tx_index
        ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"[basis] {n:,} basis rows -> {out}  ({time.time() - t0:.0f}s)", flush=True)

    # Numerical guard: the running dilution product is evaluated in log space, but a long
    # enough episode of heavy scale-ins could still drive it past the double range. Count it
    # rather than assume it away.
    bad = con.execute(
        f"SELECT count(*) FROM read_parquet('{out}') WHERE log_a_min < -300"
    ).fetchone()[0]
    print(f"[basis] episodes past the log-space guard (log_a_min < -300): {bad:,}", flush=True)

    # LEFT CENSORING, counted rather than assumed away. A (coin, wallet) series whose first
    # observed event is a DISPOSAL has no observable entry price -- the position predates the
    # window, or arrived through a route the corpus does not carry. Those rows never get an
    # episode and are dropped by `WHERE episode >= 1`; this is the size of that hole.
    stats = con.execute(
        f"""
        SELECT count(*) AS n_rows,
               count(DISTINCT (mint, owner)) AS n_wallet_coin,
               count(DISTINCT owner) AS n_wallets,
               count(DISTINCT mint) AS n_mints,
               sum((delta_raw < 0)::int) AS n_sells,
               sum((upnl_at_action IS NOT NULL AND delta_raw < 0)::int) AS n_sells_priced,
               sum((qty_before_raw < -{DUST_RAW})::int) AS n_neg_qty,
               {n_ev} AS n_events_in,
               {n_ev} - count(*) AS n_left_censored_rows
        FROM read_parquet('{out}')"""
    ).fetchdf()
    print(stats.to_string(index=False), flush=True)
    (_out() / "basis_stats.json").write_text(
        json.dumps(stats.to_dict(orient="records")[0], indent=2, default=str)
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Falsify the window-function basis against a literal recursion, and price FIFO too.

    Two independent things are checked, both on a random sample of (mint, wallet) series:

    1. **The closed form is the recursion.** ``BASIS_SQL`` replaces a sequential scan with a
       cumulative product; if the algebra or the log-space evaluation is wrong, this diverges.
    2. **Average cost vs FIFO.** The convention choice is defended in the module docstring on
       behavioural grounds, but the size of the difference is an empirical question, so it is
       measured here rather than asserted.
    """
    import numpy as np

    con = _duck(args.threads, args.memory)
    basis = _out() / "basis.parquet"

    # The sample must be drawn from the DISTINCT series, materialised first. Applying
    # `USING SAMPLE` directly to a `GROUP BY ... HAVING` query lets duckdb push the sample
    # below the aggregation, which returned 33 of the busiest wallets in the corpus instead of
    # 6,000 random ones -- a sample biased precisely toward the wallets where the two costing
    # conventions diverge most, i.e. the worst possible sample for this question.
    con.execute(
        f"""CREATE OR REPLACE TABLE allpairs AS
            SELECT mint, owner, count(*) AS n_ev,
                   max(abs(log_a_min)) AS log_a_worst,
                   min(qty_before_raw) AS min_qty_raw
            FROM read_parquet('{basis}') GROUP BY 1, 2 HAVING count(*) >= 3"""
    )
    n_all = con.execute("SELECT count(*) FROM allpairs").fetchone()[0]
    con.execute(
        f"""CREATE OR REPLACE TABLE samp AS
            SELECT * FROM allpairs USING SAMPLE {args.sample} ROWS (reservoir, {args.seed})"""
    )
    pairs = con.execute("SELECT mint, owner FROM samp").fetchdf()
    print(
        f"[check] {len(pairs):,} sampled of {n_all:,} (mint, wallet) series with >= 3 events",
        flush=True,
    )

    rows = con.execute(
        f"""
        SELECT b.mint, b.owner, b.block_slot, b.tx_index, b.delta_raw, b.px, b.mark_before,
               b.basis_before, b.basis_after, b.qty_before, b.qty_before_raw, b.log_a_min
        FROM read_parquet('{basis}') b SEMI JOIN samp s USING (mint, owner)
        ORDER BY b.mint, b.owner, b.block_slot, b.tx_index"""
    ).fetchdf()
    print(f"[check] {len(rows):,} event rows", flush=True)

    # The reference recursion tracks the position exactly as the SQL does -- including the
    # RAW (unfloored) running position -- because the two only agree if they agree on what
    # "flat" means. A book driven negative by an unobserved inflow is the one place the closed
    # form and a naive floored recursion part company, and it is reported as its own stratum
    # rather than averaged into a headline number.
    rel_err: list[float] = []
    rel_err_clean: list[float] = []
    fifo_gap: list[float] = []
    fifo_gap_clean: list[float] = []
    n_neg_series = 0
    n_guard_series = 0
    for (_mint, _owner), g in rows.groupby(["mint", "owner"], sort=False):
        neg = bool((g["qty_before_raw"] < -DUST_RAW).any())
        guard = bool((g["log_a_min"] < -300).any())
        n_neg_series += int(neg)
        n_guard_series += int(guard)
        clean = not (neg or guard)
        b = 0.0  # average-cost per-unit basis
        q_raw = 0.0  # the raw signed running position, as the SQL computes it
        lots: list[list[float]] = []  # FIFO queue of [qty, price]
        for r in g.itertuples(index=False):
            d = float(r.delta_raw)
            p = float(r.px) if r.px == r.px and r.px is not None else 0.0
            q = max(q_raw, 0.0)
            if d > 0 and q <= DUST_RAW:  # episode open
                b, lots = p, []
                q = 0.0
            if d > 0:
                b = (b * q + p * d) / (q + d) if (q + d) > 0 else p
                lots.append([d, p])
            else:
                s = -d
                take, cost = s, 0.0
                while take > 0 and lots:
                    lot = lots[0]
                    used = min(lot[0], take)
                    cost += used * lot[1]
                    lot[0] -= used
                    take -= used
                    if lot[0] <= 0:
                        lots.pop(0)
                fifo_b = cost / (s - take) if s > take else 0.0
                if r.basis_before and r.basis_before > 0 and p > 0 and fifo_b > 0:
                    gap = abs((p / fifo_b - 1.0) - (p / r.basis_before - 1.0))
                    fifo_gap.append(gap)
                    if clean:
                        fifo_gap_clean.append(gap)
            q_raw += d
            ref = float(r.basis_after) if r.basis_after == r.basis_after else 0.0
            if b > 0 and ref > 0:
                rel = abs(b - ref) / b
                rel_err.append(rel)
                if clean:
                    rel_err_clean.append(rel)

    def dist(a):
        a = np.asarray(a)
        if a.size == 0:
            return None
        return {
            "n": int(a.size),
            "frac_below_1e-9": float((a < 1e-9).mean()),
            "median": float(np.median(a)),
            "p90": float(np.quantile(a, 0.90)),
            "p99": float(np.quantile(a, 0.99)),
            "max": float(a.max()),
        }

    n_series = int(rows.groupby(["mint", "owner"], sort=False).ngroups)
    res = {
        "n_series": n_series,
        "n_events": len(rows),
        "n_series_with_negative_book": n_neg_series,
        "n_series_past_logspace_guard": n_guard_series,
        "window_vs_recursion_relative_error": dist(rel_err),
        "window_vs_recursion_relative_error_clean": dist(rel_err_clean),
        "fifo_vs_avgcost_pnl_gap": dist(fifo_gap),
        "fifo_vs_avgcost_pnl_gap_clean": dist(fifo_gap_clean),
    }
    print(json.dumps(res, indent=2), flush=True)
    (_out() / "basis_check.json").write_text(json.dumps(res, indent=2))
    return 0


# =====================================================================================
# q1 -- does cost-basis density predict where price stalls and turns?
# =====================================================================================

#: The wiggle population, pre-registered before any estimate was looked at. A coin qualifies
#: when it has (a) collapsed -- drawdown from its own peak past `WIGGLE_DD`; (b) survived the
#: collapse with two-sided flow -- at least `WIGGLE_MIN_TRADES` fills after the collapse
#: completes, of which at least `WIGGLE_MIN_SIDE` on each side; and (c) enough distinct live
#: holders at the snapshot to estimate a density at all.
WIGGLE_DD = 0.60
WIGGLE_MIN_TRADES = 100
WIGGLE_MIN_SIDE = 20
WIGGLE_MIN_HOLDERS = 50

#: Swing thresholds for the reversal detector, reported as a grid rather than tuned. A swing
#: high is a local maximum that the path subsequently retraces by at least theta before making
#: a new high; a swing low is its mirror. This is the standard zigzag construction.
SWING_THETAS = (0.10, 0.20, 0.40)

#: Kernel bandwidth for the log-basis density, in natural-log units of price. 0.35 is roughly
#: a 42% price band -- narrow enough to resolve separate entry cohorts, wide enough that a
#: single whale's basis is not itself a "mode". Reported as a grid alongside the thetas.
KDE_BW = (0.25, 0.35, 0.50)


def _swings(x, theta):
    """Zigzag swing points on a log-price path. Returns indices of alternating extrema.

    A pure retracement rule with no lookahead beyond the confirmation itself: the walk tracks a
    running extreme and confirms it as a swing the moment the path retraces `theta` (in log
    terms, ``log1p(theta)``) against it. Confirmed swings are therefore always in the past
    relative to their confirmation, which is what keeps the statistic from peeking.

    Before the first confirmation the direction is UNDECIDED, and the running high and the
    running low must both be tracked. A single running extreme in that state chases the price
    forever and never confirms anything -- the first version of this function did exactly that
    and returned zero swings on every path in the corpus.
    """
    import numpy as np

    thr = math.log1p(theta)
    if x.size < 3:
        return np.zeros(0, dtype=np.int64)
    out: list[int] = []
    direction = 0  # +1 confirmed up-leg, -1 confirmed down-leg, 0 undecided
    hi_i, hi_v = 0, float(x[0])
    lo_i, lo_v = 0, float(x[0])
    for i in range(1, x.size):
        v = float(x[i])
        if direction >= 0 and v > hi_v:
            hi_i, hi_v = i, v
        if direction <= 0 and v < lo_v:
            lo_i, lo_v = i, v
        if direction >= 0 and hi_v - v >= thr:
            out.append(hi_i)
            direction, lo_i, lo_v = -1, i, v
        elif direction <= 0 and v - lo_v >= thr:
            out.append(lo_i)
            direction, hi_i, hi_v = 1, i, v
    return np.asarray(sorted(set(out)), dtype=np.int64)


def _kde_on_grid(support_x, support_w, grid, bw):
    """Supply-weighted Gaussian KDE of log-basis, evaluated on a grid.

    Evaluated on a grid and interpolated rather than at every path point, because the rotation
    null re-evaluates this once per (coin, rotation, cell) and the naive form is
    ``n_path x n_support`` each time.
    """
    import numpy as np

    if support_x.size == 0 or support_w.sum() <= 0:
        return np.zeros(grid.size)
    z = (grid[:, None] - support_x[None, :]) / bw
    k = np.exp(-0.5 * z * z)
    return (k * support_w[None, :]).sum(axis=1) / (support_w.sum() * bw * math.sqrt(2 * math.pi))


def cmd_q1(args: argparse.Namespace) -> int:
    """Do cost-basis density modes predict where oscillations stall and reverse?

    THE CIRCULARITY THIS IS BUILT TO AVOID, stated before the result. Basis density is high at
    exactly the price levels where a lot of volume traded, and price revisits levels where it
    previously dwelt. A naive test therefore finds an "effect" from autocorrelation alone. Two
    separate defences:

    * the density is frozen at a snapshot ``t0`` and every reversal is scored strictly after it,
      so no trade contributes to both sides of the comparison;
    * the statistic is a WITHIN-PATH rank -- the density at reversal levels against the density
      at every level the path actually traversed -- which conditions out occupancy entirely.

    And two nulls, because one null is a knob (PROGRAM.md §3 rule 13):

    * **rotation** -- give coin i's price path coin j's density profile. Kills any effect that
      is a property of the generic shape of a basis distribution rather than of *this* coin's.
    * **occupancy control** -- replace the basis density with the pre-``t0`` TRADED-VOLUME
      density over the same levels. Basis density is volume density minus the people who
      already left, so if the basis version does not beat the volume version, the finding is
      "price revisits busy levels" and has nothing to do with anyone's entry price.
    """
    import numpy as np

    con = _duck(args.threads, args.memory)
    t0w = time.time()
    basis = _out() / "basis.parquet"

    # --- the wiggle population -----------------------------------------------------------
    # Curve-route coins only. A migrated coin is priced at last trade rather than at an exact
    # marginal price, and mixing the two mark definitions inside one population would put the
    # measurement error on the same axis as the effect. 30,742 of 33,031 cohort coins never
    # migrate, so this costs almost no population and buys an exact price path.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE migrated AS
        SELECT DISTINCT mint FROM read_parquet('{basis}') WHERE route = 'pool'
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE pk AS
        SELECT b.mint,
               max(b.mark_after) AS peak_mark,
               arg_max(b.block_time, b.mark_after) AS t_peak,
               max(b.block_time) AS t_last
        FROM read_parquet('{basis}') b
        WHERE b.mark_after IS NOT NULL AND b.route = 'curve'
          AND b.mint NOT IN (SELECT mint FROM migrated)
        GROUP BY 1
        """
    )
    # t0: the first moment after the peak at which the mark has fallen through WIGGLE_DD.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE t0 AS
        SELECT b.mint, min(b.block_time) AS t0
        FROM read_parquet('{basis}') b JOIN pk p USING (mint)
        WHERE b.block_time > p.t_peak AND b.route = 'curve'
          AND b.mark_after <= (1 - {WIGGLE_DD}) * p.peak_mark
        GROUP BY 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE wig AS
        SELECT b.mint, t.t0, p.t_last, count(*) AS n_post,
               sum((b.delta_raw > 0)::int) AS n_buy, sum((b.delta_raw < 0)::int) AS n_sell
        FROM read_parquet('{basis}') b
        JOIN t0 t USING (mint) JOIN pk p USING (mint)
        WHERE b.block_time > t.t0 AND b.mark_after IS NOT NULL AND b.route = 'curve'
        GROUP BY 1, 2, 3
        HAVING count(*) >= {WIGGLE_MIN_TRADES}
           AND sum((b.delta_raw > 0)::int) >= {WIGGLE_MIN_SIDE}
           AND sum((b.delta_raw < 0)::int) >= {WIGGLE_MIN_SIDE}
        """
    )
    n_wig = con.execute("SELECT count(*) FROM wig").fetchone()[0]
    print(f"[q1] wiggle population: {n_wig:,} coins ({time.time() - t0w:.0f}s)", flush=True)
    if n_wig == 0:
        print("[q1] NULL: no coin satisfies the pre-registered wiggle criteria.")
        return 0
    if args.max_coins and n_wig > args.max_coins:
        con.execute(
            f"CREATE OR REPLACE TABLE wig AS SELECT * FROM wig "
            f"USING SAMPLE {args.max_coins} ROWS (reservoir, {args.seed})"
        )
        n_wig = args.max_coins
        print(f"[q1] subsampled to {n_wig:,} coins for tractability", flush=True)

    # --- snapshot: every wallet's live position and basis at t0 ---------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE snap AS
        SELECT mint, owner, qty_after AS qty, basis_after AS basis
        FROM (SELECT b.mint, b.owner, b.qty_after, b.basis_after,
                     row_number() OVER (PARTITION BY b.mint, b.owner
                                        ORDER BY b.block_slot DESC, b.tx_index DESC) AS rk
              FROM read_parquet('{basis}') b JOIN wig w USING (mint)
              WHERE b.block_time <= w.t0)
        WHERE rk = 1 AND qty_after > {DUST_RAW} AND basis_after > 0
        """
    )
    # --- occupancy control: pre-t0 traded SOL volume by price level ------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE occ AS
        SELECT b.mint, ln(b.px) AS lx, abs(b.sol) AS w
        FROM read_parquet('{basis}') b JOIN wig w2 USING (mint)
        WHERE b.block_time <= w2.t0 AND b.px > 0 AND b.sol IS NOT NULL AND b.route = 'curve'
        """
    )
    # --- the forward path ------------------------------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE path AS
        SELECT b.mint, b.block_slot, b.tx_index, b.block_time, ln(b.mark_after) AS lx
        FROM read_parquet('{basis}') b JOIN wig w USING (mint)
        WHERE b.block_time > w.t0 AND b.mark_after > 0 AND b.route = 'curve'
        ORDER BY b.mint, b.block_slot, b.tx_index
        """
    )

    snap = con.execute(
        "SELECT s.mint, ln(s.basis) AS lb, s.qty::DOUBLE AS q FROM snap s "
        f"SEMI JOIN (SELECT mint FROM snap GROUP BY 1 HAVING count(*) >= {WIGGLE_MIN_HOLDERS}) k"
        " USING (mint)"
    ).fetchdf()
    occ = con.execute("SELECT mint, lx, w FROM occ").fetchdf()
    path = con.execute("SELECT mint, lx FROM path").fetchdf()
    print(
        f"[q1] snapshot rows {len(snap):,}; occupancy rows {len(occ):,}; path rows {len(path):,}"
        f"  ({time.time() - t0w:.0f}s)",
        flush=True,
    )

    snap_g = {m: (g["lb"].to_numpy(), g["q"].to_numpy()) for m, g in snap.groupby("mint")}
    occ_g = {m: (g["lx"].to_numpy(), g["w"].to_numpy()) for m, g in occ.groupby("mint")}
    path_g = {m: g["lx"].to_numpy() for m, g in path.groupby("mint", sort=False)}
    mints = [m for m in path_g if m in snap_g and m in occ_g and path_g[m].size >= 20]
    print(f"[q1] usable coins: {len(mints):,}", flush=True)
    if not mints:
        print("[q1] NULL: no coin has both a snapshot and a forward path.")
        return 0

    # Swings depend only on (coin, theta), never on which profile is being scored, so they are
    # computed once. The rotation null re-scores 2,400 coins x 200 rotations x 18 cells; doing
    # the zigzag inside that loop would be the whole runtime.
    NGRID = 256
    swing_c: dict[tuple[str, float], object] = {}
    grid_c: dict[str, object] = {}
    for m in mints:
        x = path_g[m]
        lo, hi = float(x.min()), float(x.max())
        pad = max((hi - lo) * 0.05, 1e-6)
        grid_c[m] = np.linspace(lo - pad, hi + pad, NGRID)
        for theta in SWING_THETAS:
            swing_c[(m, theta)] = _swings(x, theta)

    def mean_rank(profile_mint, path_mint, bw, theta, kind):
        """Mean within-path density rank of the swing levels. 0.5 under the null.

        The rank is taken over the levels the path ACTUALLY TRAVERSED, which is what conditions
        out occupancy: the question is not "is the density high where price reversed" (it would
        be, since price reverses where it trades) but "is it higher there than at the other
        levels this same path visited".
        """
        sw = swing_c[(path_mint, theta)]
        if sw.size < 3:
            return None
        sx, sw_w = snap_g[profile_mint] if kind == "basis" else occ_g[profile_mint]
        g = grid_c[path_mint]
        dg = _kde_on_grid(sx, sw_w, g, bw)
        if not np.isfinite(dg).all() or dg.max() <= 0:
            return None
        d = np.interp(path_g[path_mint], g, dg)
        order = d.argsort().argsort() / max(d.size - 1, 1)
        return float(order[sw].mean())

    # The cell grid. Every (bw, theta, kind) cell is a separate test and they are counted.
    rng = np.random.default_rng(args.seed)
    cells: list[dict] = []
    n_m = len(mints)
    for bw in KDE_BW:
        for theta in SWING_THETAS:
            for kind in ("basis", "occupancy"):
                obs = [mean_rank(m, m, bw, theta, kind) for m in mints]
                keep = [i for i, v in enumerate(obs) if v is not None]
                if len(keep) < 30:
                    print(
                        f"[q1] bw={bw} theta={theta} {kind}: only {len(keep)} scorable coins, "
                        "cell skipped",
                        flush=True,
                    )
                    continue
                obs_arr = np.asarray([obs[i] for i in keep])
                stat = float(obs_arr.mean())
                # ROTATION NULL: coin i keeps its own path, and is scored against coin j's
                # profile. A cyclic shift by a random non-zero amount is a derangement by
                # construction, so no coin is ever scored against itself.
                rot = []
                for _ in range(args.rotations):
                    shift = int(rng.integers(1, n_m))
                    vals = []
                    for i in keep:
                        j = mints[(i + shift) % n_m]
                        v = mean_rank(j, mints[i], bw, theta, kind)
                        if v is not None:
                            vals.append(v)
                    if vals:
                        rot.append(float(np.mean(vals)))
                rot_arr = np.asarray(rot) if rot else np.zeros(0)
                p_rot = (
                    float(
                        ((np.abs(rot_arr - 0.5) >= abs(stat - 0.5)).sum() + 1)
                        / (rot_arr.size + 1)
                    )
                    if rot_arr.size
                    else None
                )
                # The coin IS the clustering unit, so a t on the per-coin means is already
                # entity-clustered in the sense PROGRAM.md §3 rule 2 requires.
                se = float(obs_arr.std(ddof=1) / math.sqrt(obs_arr.size))
                cells.append(
                    {
                        "bw": bw,
                        "theta": theta,
                        "kind": kind,
                        "n_coins": int(obs_arr.size),
                        "mean_rank": stat,
                        "se": se,
                        "t_vs_half": float((stat - 0.5) / se) if se > 0 else None,
                        "rotation_mean": float(rot_arr.mean()) if rot_arr.size else None,
                        "rotation_sd": float(rot_arr.std(ddof=1)) if rot_arr.size > 1 else None,
                        "p_rotation": p_rot,
                    }
                )
                print(
                    f"[q1] bw={bw} theta={theta} {kind:10s} n={obs_arr.size:5d} "
                    f"mean_rank={stat:.4f} rot={cells[-1]['rotation_mean']:.4f} "
                    f"p_rot={p_rot:.4f}",
                    flush=True,
                )

    # The mechanism question: does the BASIS profile beat the pure OCCUPANCY profile at matched
    # (bw, theta)? If not, the finding is "price revisits busy levels" and carries no
    # information about anybody's entry price.
    paired = []
    by_key = {(c["bw"], c["theta"], c["kind"]): c for c in cells}
    for bw in KDE_BW:
        for theta in SWING_THETAS:
            b = by_key.get((bw, theta, "basis"))
            o = by_key.get((bw, theta, "occupancy"))
            if b and o:
                paired.append(
                    {
                        "bw": bw,
                        "theta": theta,
                        "basis_mean_rank": b["mean_rank"],
                        "occupancy_mean_rank": o["mean_rank"],
                        "basis_minus_occupancy": b["mean_rank"] - o["mean_rank"],
                    }
                )

    res = {
        "n_wiggle_coins": int(n_wig),
        "n_usable": len(mints),
        "n_cells": len(cells),
        "basis_vs_occupancy": paired,
        "cells": cells,
        "by_fdr": _by_fdr([c["p_rotation"] for c in cells], args.fdr_q),
    }
    (_out() / "q1_reversal.json").write_text(json.dumps(res, indent=2))
    print(f"[q1] -> {_out() / 'q1_reversal.json'}  ({time.time() - t0w:.0f}s)", flush=True)
    return 0


# =====================================================================================
# describe -- the distribution the operator asked about, and a real test of the confound
# =====================================================================================

#: The preset levels a take-profit / stop-loss menu offers. Break-even is included because it
#: turns out to be the only one that exists.
ROUND_LEVELS = (-0.75, -0.5, -0.4, -0.3, -0.25, -0.2, -0.15, -0.1, 0.0,
                0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 9.0)


def cmd_describe(args: argparse.Namespace) -> int:
    """The unrealized-PnL distribution itself, plus the round-number confound MEASURED.

    Three objects:

    1. **The realization distribution** -- where sells happen in unrealized-PnL space -- and
       **the standing book**, the unrealized PnL of every live position at the corpus edge.
       The second is the one nobody looks at and it is the more sobering of the two.

    2. **A real test for preset clustering.** ``q2`` reports the share of sells inside a
       tolerance band of a round level, and that number is uninterpretable alone: nineteen
       levels at a +/-2% relative band cover roughly half this distribution's support by
       chance. The test that means something is EXCESS OVER A SMOOTH BASELINE -- a wide moving
       median that a narrow spike cannot drag upward. Run that way, the answer is that the
       confound the whole of §2 was designed around **does not exist in this market**: every
       classic take-profit and stop-loss level sits within a few percent of its own baseline.
       Exactly one level is a real spike, and it is break-even.

    3. **What that spike is made of** -- how much of it is a same-slot round trip rather than a
       decision, since half of all sells in this corpus happen in the same slot as the buy.
    """
    import numpy as np

    con = _duck(args.threads, args.memory)
    t0 = time.time()
    basis = _out() / "basis.parquet"
    ok = (
        "upnl_at_action IS NOT NULL AND upnl_at_action > -0.999 AND upnl_at_action < 1000 "
        "AND log_a_min >= -300 AND qty_before_raw > 0"
    )

    res: dict[str, object] = {}
    res["realization_distribution"] = con.execute(
        f"""SELECT count(*) n,
              quantile_cont(upnl_at_action,0.01) p01, quantile_cont(upnl_at_action,0.05) p05,
              quantile_cont(upnl_at_action,0.10) p10, quantile_cont(upnl_at_action,0.25) p25,
              median(upnl_at_action) p50, quantile_cont(upnl_at_action,0.75) p75,
              quantile_cont(upnl_at_action,0.90) p90, quantile_cont(upnl_at_action,0.95) p95,
              quantile_cont(upnl_at_action,0.99) p99,
              avg((upnl_at_action>0)::int) frac_in_profit
            FROM read_parquet('{basis}') WHERE delta_raw < 0 AND {ok}"""
    ).fetchdf().to_dict("records")[0]

    res["action_asymmetry"] = con.execute(
        f"""SELECT sum((delta_raw>0)::int) n_buys, sum((delta_raw<0)::int) n_sells,
              avg(CASE WHEN delta_raw>0 THEN (upnl_at_action<0)::int END) frac_adds_while_red,
              avg(CASE WHEN delta_raw<0 THEN (upnl_at_action<0)::int END) frac_sells_while_red
            FROM read_parquet('{basis}') WHERE {ok}"""
    ).fetchdf().to_dict("records")[0]

    res["standing_book"] = con.execute(
        f"""WITH last AS (
              SELECT mint, owner, qty_after qty, basis_after basis FROM (
                SELECT mint, owner, qty_after, basis_after,
                  row_number() OVER (PARTITION BY mint,owner
                                     ORDER BY block_slot DESC,tx_index DESC) rk
                FROM read_parquet('{basis}')) WHERE rk=1 AND qty_after>{DUST_RAW}
                                                    AND basis_after>0),
            spot AS (SELECT mint, arg_max(mark_after, block_slot*1000000+tx_index) spot
                     FROM read_parquet('{basis}')
                     WHERE mark_after>0 AND abs(sol)>={args.min_sol} GROUP BY 1)
            SELECT count(*) n_positions,
              quantile_cont(s.spot/l.basis-1, 0.05) p05,
              quantile_cont(s.spot/l.basis-1, 0.25) p25,
              median(s.spot/l.basis-1) p50,
              quantile_cont(s.spot/l.basis-1, 0.75) p75,
              quantile_cont(s.spot/l.basis-1, 0.95) p95,
              avg((s.spot>l.basis)::int) frac_positions_in_profit,
              sum(CASE WHEN s.spot>l.basis THEN l.qty ELSE 0 END)/sum(l.qty)
                  supply_share_in_profit
            FROM last l JOIN spot s USING (mint)"""
    ).fetchdf().to_dict("records")[0]

    # --- the round-number test, against a smooth baseline ---------------------------------
    u = con.execute(
        f"""SELECT upnl_at_action u FROM read_parquet('{basis}')
            WHERE delta_raw < 0 AND {ok} AND upnl_at_action BETWEEN -0.98 AND 10"""
    ).fetchdf()["u"].to_numpy()
    bw = 0.002
    edges = np.arange(-0.98, 10.0 + bw, bw)
    h, _ = np.histogram(u, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2
    K = 201  # a +/-0.2 window; wide enough that a one-bin spike cannot move the median
    pad = np.pad(h.astype(float), K // 2, mode="edge")
    base = np.array([np.median(pad[i : i + K]) for i in range(h.size)])
    res["round_number_test"] = {
        "n_sells": int(u.size),
        "bin_width": bw,
        "baseline_window": K * bw,
        "levels": [
            {
                "level": lv,
                "observed": float(h[np.abs(centers - lv) <= bw].sum()),
                "smooth_baseline": float(base[np.abs(centers - lv) <= bw].sum()),
                "excess_ratio": round(
                    float(h[np.abs(centers - lv) <= bw].sum())
                    / max(float(base[np.abs(centers - lv) <= bw].sum()), 1e-9),
                    3,
                ),
            }
            for lv in ROUND_LEVELS
        ],
    }

    # --- what the break-even spike is made of ----------------------------------------------
    res["breakeven_mechanism"] = con.execute(
        f"""WITH s AS (
              SELECT upnl_at_action u, delta_raw, block_time, block_slot, qty_after,
                     min(block_time) OVER w AS t_open, min(block_slot) OVER w AS slot_open
              FROM read_parquet('{basis}') WHERE {ok}
              WINDOW w AS (PARTITION BY mint, owner, episode))
            SELECT CASE WHEN abs(u) <= 0.002 THEN 'at_breakeven'
                        WHEN abs(u) <= 0.05  THEN 'near_breakeven'
                        ELSE 'away' END AS band,
                   count(*) n, median(block_time - t_open) med_hold_s,
                   avg((block_slot = slot_open)::int) frac_same_slot_as_open,
                   avg((qty_after <= {DUST_RAW})::int) frac_full_exit
            FROM s WHERE delta_raw < 0 GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchdf().to_dict("records")

    print(json.dumps(res, indent=2, default=str)[:4000], flush=True)
    (_out() / "describe.json").write_text(json.dumps(res, indent=2, default=str))
    print(f"[describe] -> {_out() / 'describe.json'}  ({time.time() - t0:.0f}s)", flush=True)
    return 0


# =====================================================================================
# hazard -- the operator's question, taken literally: is unrealized PnL a live state variable?
# =====================================================================================


def cmd_hazard(args: argparse.Namespace) -> int:
    """P(this wallet sells in the next minute | its current unrealized PnL), on a real risk set.

    The realization histogram in ``q2`` is a distribution over ACTIONS -- it says where sells
    happen, not whether the PnL level *caused* them, because it has no denominator. A wallet
    that sells at +40% may simply have been holding while the price was at +40%. Turning the
    object into a decision variable needs the times the wallet held and did NOT sell, i.e. a
    risk set.

    So: lay a fixed clock over each coin, and for every wallet-episode emit one row per tick it
    was alive for, carrying that wallet's own unrealized PnL at that tick and whether it sold
    during the tick. That is a discrete-time hazard with a genuine denominator, and its shape in
    PnL is the thing a reactive exit rule would have to exploit.

    VOLATILITY CONTROL, per PROGRAM.md §3 (anything drawdown-adjacent gets one). A wallet deep
    in the red is disproportionately holding a coin that is moving violently, and a violent coin
    has more selling of every kind. The hazard is therefore reported both raw and stratified by
    the coin's own trailing realized volatility, so "red wallets sell more" cannot be read off a
    difference that is really "volatile coins trade more".
    """
    con = _duck(args.threads, args.memory)
    t0 = time.time()
    basis = _out() / "basis.parquet"
    dt = args.tick

    con.execute(
        f"""
        CREATE OR REPLACE TABLE coins_all AS
        SELECT mint, min(block_time) AS t_first, max(block_time) AS t_last,
               count(*) AS n_ev
        FROM read_parquet('{basis}')
        WHERE mark_after > 0
        GROUP BY 1
        HAVING count(*) BETWEEN {args.min_ev} AND {args.max_ev}
           AND max(block_time) - min(block_time) >= {10 * dt}
        """
    )
    # The sample is drawn from a MATERIALISED table. `USING SAMPLE` attached directly to a
    # `GROUP BY ... HAVING` query gets pushed below the aggregation by duckdb and silently
    # returns the wrong thing -- here, nothing at all.
    n_pool = con.execute("SELECT count(*) FROM coins_all").fetchone()[0]
    con.execute(
        f"""CREATE OR REPLACE TABLE coins AS SELECT * FROM coins_all
            USING SAMPLE {args.max_coins} ROWS (reservoir, {args.seed})"""
    )
    print(f"[hazard] eligible coins: {n_pool:,}", flush=True)
    n_c = con.execute("SELECT count(*) FROM coins").fetchone()[0]
    print(f"[hazard] {n_c:,} coins on the clock (tick={dt}s)", flush=True)
    if n_c == 0:
        print("[hazard] NULL: no coin in the sampling band.")
        return 0

    con.execute(
        f"""
        CREATE OR REPLACE TABLE ev AS
        SELECT b.* FROM read_parquet('{basis}') b SEMI JOIN coins c USING (mint)
        """
    )
    # the coin's own mark path, dust-filtered, plus a trailing realized volatility
    con.execute(
        f"""
        CREATE OR REPLACE TABLE mk AS
        SELECT mint, block_time, mark_after AS mark,
               ln(mark_after / nullif(lag(mark_after) OVER w, 0)) AS r
        FROM ev WHERE mark_after > 0 AND abs(sol) >= {args.min_sol}
        WINDOW w AS (PARTITION BY mint ORDER BY block_slot, tx_index)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE mkv AS
        SELECT *, sqrt(avg(r * r) OVER (PARTITION BY mint ORDER BY block_time
                                        ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING)) AS rv
        FROM mk
        """
    )
    # each wallet-episode's own state path, and the span it was alive for
    con.execute(
        """
        CREATE OR REPLACE TABLE st AS
        SELECT mint, owner, episode, block_time, qty_after, basis_after
        FROM ev WHERE basis_after > 0
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE ep AS
        SELECT mint, owner, episode, min(block_time) AS t_in,
               max(block_time) AS t_out
        FROM ev GROUP BY 1, 2, 3
        HAVING max(block_time) - min(block_time) >= {dt}
        """
    )
    n_ep = con.execute("SELECT count(*) FROM ep").fetchone()[0]
    print(f"[hazard] {n_ep:,} wallet-episodes ({time.time() - t0:.0f}s)", flush=True)

    con.execute(
        f"""
        CREATE OR REPLACE TABLE cand AS
        SELECT e.mint, e.owner, e.episode, g.k,
               c.t_first + g.k * {dt} AS t
        FROM ep e JOIN coins c USING (mint),
             LATERAL (SELECT unnest(range(
                 CAST(floor((e.t_in - c.t_first) / {dt}) AS BIGINT) + 1,
                 CAST(floor((least(e.t_out, c.t_last) - c.t_first) / {dt}) AS BIGINT) + 1,
                 1)) AS k) g
        """
    )
    n_cand = con.execute("SELECT count(*) FROM cand").fetchone()[0]
    print(f"[hazard] {n_cand:,} risk-set ticks ({time.time() - t0:.0f}s)", flush=True)
    if n_cand == 0:
        print("[hazard] NULL: empty risk set.")
        return 0
    if n_cand > args.max_ticks:
        # BERNOULLI, not reservoir. A reservoir sample of 40M rows has to hold 40M rows;
        # a percentage sample streams. The risk set is exchangeable across ticks, so the
        # cheaper sampler is also the correct one here.
        pct = 100.0 * args.max_ticks / n_cand
        con.execute(
            f"CREATE OR REPLACE TABLE cand AS SELECT * FROM cand "
            f"USING SAMPLE {pct:.4f}% (bernoulli, {args.seed})"
        )
        n_cand = con.execute("SELECT count(*) FROM cand").fetchone()[0]
        print(f"[hazard]   subsampled to {n_cand:,} ticks ({pct:.2f}%)", flush=True)

    out = _out() / "hazard.parquet"
    _copy(
        con,
        f"""
        WITH withstate AS (
            SELECT c.mint, c.owner, c.episode, c.k, c.t, s.qty_after, s.basis_after
            FROM cand c ASOF JOIN st s
              ON c.mint = s.mint AND c.owner = s.owner AND c.episode = s.episode
             AND c.t >= s.block_time
        ),
        withmark AS (
            SELECT w.*, m.mark, m.rv
            FROM withstate w ASOF JOIN mkv m ON w.mint = m.mint AND w.t >= m.block_time
        ),
        -- The label is an EQUI-JOIN on tick index, not a correlated EXISTS. Both grids are
        -- anchored to the coin's own first observation, so a sell at time ts falls in tick
        -- floor((ts - t_first)/dt) by construction, and a 40-million-row range-correlated
        -- subquery becomes a hash join.
        sellticks AS (
            SELECT DISTINCT e.mint, e.owner, e.episode,
                   CAST(floor((e.block_time - c.t_first) / {dt}) AS BIGINT) AS k
            FROM ev e JOIN coins c USING (mint) WHERE e.delta_raw < 0
        ),
        lab AS (
            SELECT wm.*, (sk.k IS NOT NULL) AS sold_next
            FROM withmark wm
            LEFT JOIN sellticks sk
              ON sk.mint = wm.mint AND sk.owner = wm.owner
             AND sk.episode = wm.episode AND sk.k = wm.k
        )
        SELECT mint, owner, episode, t, qty_after, basis_after, mark, rv,
               mark / basis_after - 1.0 AS upnl, sold_next
        FROM lab
        WHERE qty_after > {DUST_RAW} AND basis_after > 0 AND mark > 0
        """,
        out,
        "hazard risk set",
    )

    # The headline: hazard by unrealized-PnL bucket, raw and volatility-stratified.
    haz = con.execute(
        f"""
        SELECT bucket, count(*) AS n_ticks, sum(sold_next::int) AS n_sells,
               avg(sold_next::int) AS hazard,
               count(DISTINCT owner) AS n_wallets, count(DISTINCT mint) AS n_coins
        FROM (SELECT *, CASE
                WHEN upnl < -0.8 THEN '1: < -80%'
                WHEN upnl < -0.5 THEN '2: -80..-50%'
                WHEN upnl < -0.25 THEN '3: -50..-25%'
                WHEN upnl < -0.05 THEN '4: -25..-5%'
                WHEN upnl < 0.05 THEN '5: -5..+5%'
                WHEN upnl < 0.25 THEN '6: +5..+25%'
                WHEN upnl < 1.0 THEN '7: +25..+100%'
                WHEN upnl < 4.0 THEN '8: +100..+400%'
                ELSE '9: > +400%' END AS bucket
              FROM read_parquet('{out}'))
        GROUP BY 1 ORDER BY 1"""
    ).fetchdf()
    print("[hazard] raw:\n" + haz.to_string(index=False), flush=True)

    hazv = con.execute(
        f"""
        SELECT vol_tercile, bucket, count(*) AS n_ticks, avg(sold_next::int) AS hazard
        FROM (SELECT *, ntile(3) OVER (ORDER BY rv) AS vol_tercile,
                CASE
                WHEN upnl < -0.8 THEN '1: < -80%'
                WHEN upnl < -0.5 THEN '2: -80..-50%'
                WHEN upnl < -0.25 THEN '3: -50..-25%'
                WHEN upnl < -0.05 THEN '4: -25..-5%'
                WHEN upnl < 0.05 THEN '5: -5..+5%'
                WHEN upnl < 0.25 THEN '6: +5..+25%'
                WHEN upnl < 1.0 THEN '7: +25..+100%'
                WHEN upnl < 4.0 THEN '8: +100..+400%'
                ELSE '9: > +400%' END AS bucket
              FROM read_parquet('{out}') WHERE rv IS NOT NULL)
        GROUP BY 1, 2 ORDER BY 1, 2"""
    ).fetchdf()
    print("[hazard] volatility-stratified:\n" + hazv.to_string(index=False), flush=True)

    (_out() / "hazard.json").write_text(
        json.dumps(
            {
                "tick_seconds": dt,
                "n_coins": int(n_c),
                "n_episodes": int(n_ep),
                "raw": haz.to_dict(orient="records"),
                "by_volatility_tercile": hazv.to_dict(orient="records"),
            },
            indent=2,
            default=str,
        )
    )
    print(f"[hazard] -> {out}  ({time.time() - t0:.0f}s)", flush=True)
    return 0


# =====================================================================================
# q2 -- the realization-policy fingerprint, and whether it identifies ACTORS or TOOLS
# =====================================================================================

#: A wallet needs this many priced sells, over this many distinct coins, before its
#: realization policy is estimated at all. Below it the histogram is noise and the pairwise
#: metric measures sampling error rather than policy.
Q2_MIN_SELLS = 20
Q2_MIN_COINS = 5

#: The policy histogram lives in signed-log PnL space, u = sign(x)*log1p(|x|), so that -90%
#: and +900% are equally far from zero. 24 bins over [-3, 3] covers -95% .. +1900%.
Q2_BINS = 24
Q2_ULIM = 3.0

#: The round numbers a preset menu offers. A sell landing within Q2_ROUND_TOL (relative) of one
#: of these is "on-grid" and is presumed to carry tooling information rather than actor
#: information. THE CONFOUND, stated before any result: thousands of independent users running
#: the same bot with its default -25% stop and +100% take produce a tight policy cluster with
#: no shared actor whatsoever.
Q2_ROUND = (-0.75, -0.5, -0.4, -0.3, -0.25, -0.2, -0.15, -0.1,
            0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 9.0)
Q2_ROUND_TOL = 0.02


def _hist(u, bins, lim):
    """Normalised, sqrt-transformed histogram. L2 on the result is Hellinger distance."""
    import numpy as np

    h, _ = np.histogram(np.clip(u, -lim, lim), bins=bins, range=(-lim, lim))
    s = h.sum()
    if s <= 0:
        return None
    return np.sqrt(h / s)


def _auc(pos, neg):
    """Rank AUC of `pos` scoring above `neg`. 0.5 is no separation."""
    import numpy as np

    pos, neg = np.asarray(pos), np.asarray(neg)
    if pos.size == 0 or neg.size == 0:
        return None
    allv = np.concatenate([pos, neg])
    r = allv.argsort().argsort().astype(float) + 1
    rp = r[: pos.size].sum()
    return float((rp - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def cmd_q2(args: argparse.Namespace) -> int:
    """Embed each wallet by WHERE IN UNREALIZED-PNL SPACE IT SELLS, and ask what that identifies.

    THE CONFOUND, DESIGNED AROUND RATHER THAN DISCOVERED. Shared *tooling* produces policy
    clusters with no shared *actor*: a Telegram bot ships a default -25% stop and a +100% take,
    ten thousand unrelated users accept the defaults, and their realization histograms become
    near-identical. Any clustering run on the raw histogram would report a huge, tight,
    meaningless cluster. Three defences:

    (a) the same analysis is run twice -- once on the full histogram, once on the OFF-GRID
        RESIDUAL, i.e. only those sells that do NOT land on a round preset level. Whatever
        actor information exists has to survive the second one;
    (b) the estimator is calibrated between two controls rather than reported bare (PROGRAM.md
        §3 rule 12: a null control alone certifies a broken estimator as readily as a working
        one):
          * KNOWN-EFFECT (ceiling): a wallet's own coins split into two disjoint halves. Same
            actor, same tooling, different coins -- the most same-actor pair that can be
            constructed without assuming an answer.
          * KNOWN-ZERO (floor): random wallet pairs, and separately pairs with ZERO coin
            overlap, which is the most distinct pair this corpus can certify.
    (c) the candidate same-actor set is INDEPENDENT EVIDENCE, not another cut of this data:
        the birth-slot sniper crews of studies/RESULT_operator_crime.md, whose set reuse runs
        51.2x above a degree-preserving null. That evidence channel is co-occurrence in time;
        this one is a PnL-level histogram with no temporal content at all. The
        entity-resolution graveyard's rule -- never let a temporal rule validate a temporal
        test -- is therefore satisfied by construction, and it is worth saying out loud that
        this is why the sniper crews are admissible here.

    A NULL IS A RESULT. If crew pairs score at the floor, the honest finding is that
    realization policy is a TOOL fingerprint and not an ACTOR fingerprint -- which is itself a
    real limit on wallet-correlation analysis and is reported as such.
    """
    import numpy as np

    con = _duck(args.threads, args.memory)
    t0 = time.time()
    basis = _out() / "basis.parquet"
    rng = np.random.default_rng(args.seed)

    # --- the sell tape, one row per realization ------------------------------------------
    con.execute(
        f"""
        CREATE OR REPLACE TABLE sells AS
        SELECT owner, mint, block_time, upnl_at_action AS u, abs(sol) AS sol
        FROM read_parquet('{basis}')
        WHERE delta_raw < 0 AND upnl_at_action IS NOT NULL
          AND upnl_at_action > -0.999 AND upnl_at_action < 1000
          AND log_a_min >= -300 AND qty_before_raw > 0
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE act AS
        SELECT owner, count(*) AS n_sells, count(DISTINCT mint) AS n_coins
        FROM sells GROUP BY 1
        HAVING count(*) >= {Q2_MIN_SELLS} AND count(DISTINCT mint) >= {Q2_MIN_COINS}
        """
    )
    n_act = con.execute("SELECT count(*) FROM act").fetchone()[0]
    n_sell = con.execute("SELECT count(*) FROM sells").fetchone()[0]
    print(f"[q2] {n_sell:,} priced sells; {n_act:,} wallets clear the activity floor", flush=True)
    if n_act < 200:
        print("[q2] NULL: too few active wallets to estimate a policy space.")
        return 0

    if args.max_wallets and n_act > args.max_wallets:
        con.execute(
            f"CREATE OR REPLACE TABLE act AS SELECT * FROM act "
            f"USING SAMPLE {args.max_wallets} ROWS (reservoir, {args.seed})"
        )
        n_act = args.max_wallets
        print(f"[q2] subsampled to {n_act:,} wallets", flush=True)

    df = con.execute(
        "SELECT s.owner, s.mint, s.u FROM sells s SEMI JOIN act a USING (owner)"
    ).fetchdf()
    print(f"[q2] {len(df):,} sells in the embedded population ({time.time() - t0:.0f}s)", flush=True)

    u = df["u"].to_numpy()
    # signed-log PnL coordinate
    ulog = np.sign(u) * np.log1p(np.abs(u))
    # on-grid = within Q2_ROUND_TOL (relative) of a preset level
    ongrid = np.zeros(u.size, dtype=bool)
    for r in Q2_ROUND:
        ongrid |= np.abs(u - r) <= Q2_ROUND_TOL * (1.0 + abs(r))
    df["ulog"] = ulog
    df["ongrid"] = ongrid
    round_share = float(ongrid.mean())
    print(f"[q2] share of sells landing on a round preset level: {round_share:.4f}", flush=True)

    by_owner = {o: g for o, g in df.groupby("owner", sort=False)}
    owners = list(by_owner)

    def emb(g, residual):
        v = g["ulog"].to_numpy()
        if residual:
            v = v[~g["ongrid"].to_numpy()]
        if v.size < Q2_MIN_SELLS // 2:
            return None
        return _hist(v, Q2_BINS, Q2_ULIM)

    def split_halves(g):
        """Disjoint COIN halves of one wallet: same actor, same tooling, different coins."""
        coins = g["mint"].unique()
        if coins.size < 2:
            return None, None
        perm = rng.permutation(coins.size)
        a = set(coins[perm[: coins.size // 2]])
        ga = g[g["mint"].isin(a)]
        gb = g[~g["mint"].isin(a)]
        return ga, gb

    results: dict[str, object] = {
        "n_sells_total": int(n_sell),
        "n_wallets": len(owners),
        "round_preset_share": round_share,
        "min_sells": Q2_MIN_SELLS,
        "min_coins": Q2_MIN_COINS,
    }

    # --- coin sets, for the zero-overlap negative control ---------------------------------
    coinset = {o: set(g["mint"].unique()) for o, g in by_owner.items()}

    # --- the sniper crews: independent evidence, validated against a curveball null --------
    crew_pairs = _sniper_crew_pairs(con, set(owners), args, rng)
    results["n_crew_pairs"] = len(crew_pairs)
    print(f"[q2] candidate same-actor pairs from sniper crews: {len(crew_pairs):,}", flush=True)

    # EVERY DISTANCE IS BETWEEN TWO HALF-SIZED HISTOGRAMS, AND EVERY NEGATIVE PAIR IS MATCHED
    # ON SAMPLE SIZE. Both of those are defects the controls caught rather than design
    # foresight, and both inverted or inflated the headline:
    #
    #  1. The first version compared same-actor HALVES against different-actor WHOLES, so the
    #     same-actor side carried twice the sampling noise. The known-zero world reported AUC
    #     0.333 -- the metric claimed same-actor pairs were LESS similar than strangers.
    #  2. With halves on both sides the known-zero world still read 0.538, not 0.5, because a
    #     same-actor pair has CORRELATED half sizes while a random pair can put a 200-sell
    #     wallet against a 12-sell wallet, and the noisy small histogram inflates the distance.
    #     That is an activity-level confound wearing an actor-identity costume.
    #
    # Negative pairs are therefore drawn from the same (log2 size, log2 size) cell as the
    # positive pairs they are scored against, so the comparison holds sample size fixed.
    def halves_map(residual):
        H = {}
        for o in owners:
            ga, gb = split_halves(by_owner[o])
            if ga is None or len(ga) == 0 or len(gb) == 0:
                continue
            ea, eb = emb(ga, residual), emb(gb, residual)
            if ea is not None and eb is not None:
                H[o] = (ea, eb, len(ga), len(gb))
        return H

    def _bucket(n):
        return int(math.log2(max(n, 1)))

    def matched_negatives(H, keys, n_per_key, rng):
        """Random cross-wallet pairs drawn from the same size cells as `keys`."""
        byA: dict[int, list] = {}
        byB: dict[int, list] = {}
        for o, (_, _, na, nb) in H.items():
            byA.setdefault(_bucket(na), []).append(o)
            byB.setdefault(_bucket(nb), []).append(o)
        out = []
        for ka, kb in keys:
            la, lb = byA.get(ka), byB.get(kb)
            if not la or not lb:
                continue
            for _ in range(n_per_key):
                oa = la[int(rng.integers(len(la)))]
                ob = lb[int(rng.integers(len(lb)))]
                if oa == ob:
                    continue
                out.append((oa, ob))
        return out

    def dists(H, pairs, same=False):
        if same:
            return [float(np.linalg.norm(H[o][0] - H[o][1])) for o in pairs]
        return [
            float(np.linalg.norm(H[a][0] - H[b][1]))
            for a, b in pairs
            if a in H and b in H
        ]

    for residual in (False, True):
        tag = "residual_offgrid" if residual else "full_histogram"
        H = halves_map(residual)
        ok = list(H)
        if len(ok) < 100:
            results[tag] = {"verdict": "too few embeddable wallets", "n": len(ok)}
            continue

        # KNOWN-EFFECT (ceiling): the wallet's own two coin-disjoint halves.
        same_keys = [(_bucket(H[o][2]), _bucket(H[o][3])) for o in ok]
        same_d = dists(H, ok, same=True)
        neg_for_same = matched_negatives(H, same_keys, args.neg_per_key, rng)
        rand_d = dists(H, neg_for_same)

        # A second, stricter negative: cross-wallet pairs that never touched the same coin.
        disj = [(a, b) for a, b in neg_for_same if not (coinset[a] & coinset[b])]
        disj_d = dists(H, disj)

        # THE TEST: sniper-crew pairs, against negatives matched to THEIR size cells.
        crew_ok = [(a, b) for a, b in crew_pairs if a in H and b in H]
        crew_d = dists(H, crew_ok)
        crew_keys = [(_bucket(H[a][2]), _bucket(H[b][3])) for a, b in crew_ok]
        neg_for_crew = matched_negatives(H, crew_keys, args.neg_per_key, rng)
        crew_neg_d = dists(H, neg_for_crew)

        def stat(a):
            a = np.asarray(a)
            return (
                None
                if a.size == 0
                else {
                    "n": int(a.size),
                    "mean": float(a.mean()),
                    "median": float(np.median(a)),
                }
            )

        results[tag] = {
            "n_embedded": len(ok),
            "same_actor_splithalf": stat(same_d),
            "size_matched_random_pairs": stat(rand_d),
            "zero_overlap_pairs": stat(disj_d),
            "crew_pairs": stat(crew_d),
            "crew_matched_negatives": stat(crew_neg_d),
            "auc_ceiling_splithalf": _auc([-x for x in same_d], [-x for x in rand_d]),
            "auc_ceiling_vs_zerooverlap": _auc([-x for x in same_d], [-x for x in disj_d]),
            "auc_crew": _auc([-x for x in crew_d], [-x for x in crew_neg_d])
            if crew_d and crew_neg_d
            else None,
        }
        r = results[tag]
        print(
            f"[q2] {tag}: n={len(ok)} ceiling AUC={r['auc_ceiling_splithalf']} "
            f"crew AUC={r['auc_crew']} (n_crew={len(crew_d)})",
            flush=True,
        )

    # --- KNOWN-ZERO WORLD: destroy the actor, keep the marginals --------------------------
    # Reassign every sell to a random wallet, preserving each wallet's sell count and the
    # global PnL distribution, then run the ceiling measurement unchanged. It must read 0.5.
    perm_owner = df["owner"].to_numpy().copy()
    rng.shuffle(perm_owner)
    dfp = df.copy()
    dfp["owner"] = perm_owner
    by_owner_p = {o: g for o, g in dfp.groupby("owner", sort=False)}
    Hp = {}
    for o, g in by_owner_p.items():
        ga, gb = split_halves(g)
        if ga is None or len(ga) == 0 or len(gb) == 0:
            continue
        ea, eb = emb(ga, False), emb(gb, False)
        if ea is not None and eb is not None:
            Hp[o] = (ea, eb, len(ga), len(gb))
    okp = list(Hp)
    same_p = dists(Hp, okp, same=True)
    keys_p = [(_bucket(Hp[o][2]), _bucket(Hp[o][3])) for o in okp]
    rand_p = dists(Hp, matched_negatives(Hp, keys_p, args.neg_per_key, rng))
    results["known_zero_world"] = {
        "n_wallets": len(okp),
        "auc_ceiling_splithalf": _auc([-x for x in same_p], [-x for x in rand_p]),
        "note": "sells reassigned to random wallets; 0.5 is the pass condition",
    }
    print(f"[q2] known-zero world AUC: {results['known_zero_world']['auc_ceiling_splithalf']}",
          flush=True)

    (_out() / "q2_fingerprint.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"[q2] -> {_out() / 'q2_fingerprint.json'}  ({time.time() - t0:.0f}s)", flush=True)
    return 0


def _sniper_crew_pairs(con, owner_pool: set, args, rng):
    """Wallet pairs that co-snipe far more coins together than a degree-preserving null allows.

    This is the positive control and it is deliberately built from a DIFFERENT evidence channel
    than the thing it validates: co-occurrence in birth-slot buying, which
    studies/RESULT_operator_crime.md measured at 51.2x a curveball null. The null here is the
    same one, for the same reason PROGRAM.md §3 rule 13 gives: on heavy-tailed activity a
    hypergeometric null validates ~99 false edges per world out of nothing, and a
    degree-preserving null deletes 100% of them.
    """
    import numpy as np

    sn = Path(os.environ.get("UPNL_SNIPERS", str(REPO_ROOT / "studies" / "data"
                                                / "operator_crime" / "snipers.parquet")))
    if not sn.exists():
        print(f"[q2] no snipers artifact at {sn}; positive control unavailable", flush=True)
        return []
    df = con.execute(
        f"""
        SELECT mint, owner FROM read_parquet('{sn}')
        WHERE owner IN (SELECT owner FROM act)
        """
    ).fetchdf()
    if df.empty:
        return []
    # restrict to wallets that sniped enough coins for co-occurrence to mean anything
    cnt = df.groupby("owner").size()
    keep = set(cnt[cnt >= args.min_snipes].index)
    df = df[df["owner"].isin(keep)]
    if df.empty:
        return []
    owners = sorted(df["owner"].unique())
    mints = sorted(df["mint"].unique())
    oi = {o: i for i, o in enumerate(owners)}
    mi = {m: i for i, m in enumerate(mints)}
    rows = df["owner"].map(oi).to_numpy()
    cols = df["mint"].map(mi).to_numpy()
    n_o, n_m = len(owners), len(mints)
    print(f"[q2] sniper incidence: {n_o:,} wallets x {n_m:,} coins, {rows.size:,} edges",
          flush=True)
    if n_o < 20:
        return []

    def cooc(r, c):
        import scipy.sparse as sp

        A = sp.csr_matrix((np.ones(r.size), (r, c)), shape=(n_o, n_m))
        A.data[:] = 1.0
        C = (A @ A.T).tocoo()
        m = C.row < C.col
        return C.row[m], C.col[m], C.data[m]

    ri, ci, obs = cooc(rows, cols)
    # Degree-preserving null by curveball swaps on the bipartite incidence.
    pair_index = {(int(a), int(b)): k for k, (a, b) in enumerate(zip(ri, ci, strict=True))}
    exceed = np.zeros(obs.size)
    for _ in range(args.crew_nulls):
        r2, c2 = _curveball(rows, cols, rng, n_o)
        nri, nci, nobs = cooc(r2, c2)
        m = np.zeros(obs.size)
        for a, b, v in zip(nri, nci, nobs, strict=True):
            k = pair_index.get((int(a), int(b)))
            if k is not None:
                m[k] = v
        exceed += (m >= obs).astype(float)
    # The permutation p-value has a hard floor of 1/(n_nulls+1). Running 20 nulls against
    # alpha=0.02 can never reject anything -- the first run of this returned zero crew pairs
    # for exactly that reason and not because the crews failed the null.
    p = (exceed + 1) / (args.crew_nulls + 1)
    floor = 1.0 / (args.crew_nulls + 1)
    if args.crew_alpha < floor:
        raise SystemExit(
            f"--crew-alpha {args.crew_alpha} is below the permutation floor {floor:.4f}; "
            f"raise --crew-nulls to at least {int(1 / args.crew_alpha) - 1}"
        )
    sel = (p <= args.crew_alpha) & (obs >= args.min_cooc)
    pairs = [
        (owners[int(a)], owners[int(b)])
        for a, b, s in zip(ri, ci, sel, strict=True)
        if s and owners[int(a)] in owner_pool and owners[int(b)] in owner_pool
    ]
    print(
        f"[q2] crew edges surviving the curveball null at alpha={args.crew_alpha}: "
        f"{int(sel.sum()):,} of {obs.size:,} co-occurring pairs; {len(pairs):,} usable",
        flush=True,
    )
    return pairs


def _curveball(rows, cols, rng, n_o):
    """One degree-preserving randomisation of a bipartite incidence (curveball swaps)."""
    import numpy as np

    r = rows.copy()
    c = cols.copy()
    order = np.argsort(r, kind="stable")
    r, c = r[order], c[order]
    bounds = np.searchsorted(r, np.arange(n_o + 1))
    sets = [set(c[bounds[i] : bounds[i + 1]].tolist()) for i in range(n_o)]
    nz = [i for i in range(n_o) if sets[i]]
    if len(nz) < 2:
        return rows, cols
    for _ in range(len(nz) * 4):
        i, j = rng.choice(len(nz), 2, replace=False)
        a, b = sets[nz[i]], sets[nz[j]]
        only_a = list(a - b)
        only_b = list(b - a)
        k = min(len(only_a), len(only_b))
        if k == 0:
            continue
        take = int(rng.integers(1, k + 1))
        sa = rng.choice(len(only_a), take, replace=False)
        sb = rng.choice(len(only_b), take, replace=False)
        mv_a = [only_a[t] for t in sa]
        mv_b = [only_b[t] for t in sb]
        for x in mv_a:
            a.discard(x)
            b.add(x)
        for x in mv_b:
            b.discard(x)
            a.add(x)
    nr, nc = [], []
    for i in range(n_o):
        for x in sets[i]:
            nr.append(i)
            nc.append(x)
    return np.asarray(nr), np.asarray(nc)


# =====================================================================================
# q3 -- population shape: is the unrealized-LOSS tail a PvP/community discriminator?
# =====================================================================================


def cmd_q3(args: argparse.Namespace) -> int:
    """The basis-shape FEATURE, delivered for the pvp_vamps lane rather than as a rival classifier.

    ``studies/pvp_vamps.py`` is live on adjacent ground and owns the PvP classifier. Building a
    second one here would be two lanes fitting the same outcome on the same corpus and calling
    the agreement corroboration. So this stage stops at the feature: per coin, the shape of the
    unrealized-PnL distribution at which its holders realize, plus how much of its live supply
    sits underwater and for how long. Whether that separates PvP from community coins is the
    other lane's question, and the columns are named so it can join them.
    """
    con = _duck(args.threads, args.memory)
    t0 = time.time()
    basis = _out() / "basis.parquet"
    cohort = _out() / "cohort.parquet"

    out = _out() / "q3_basis_shape.parquet"
    _copy(
        con,
        f"""
        WITH s AS (
            SELECT mint, upnl_at_action AS u, abs(sol) AS sol, block_time
            FROM read_parquet('{basis}')
            WHERE delta_raw < 0 AND upnl_at_action IS NOT NULL
              AND upnl_at_action > -0.999 AND upnl_at_action < 1000
              AND log_a_min >= -300 AND qty_before_raw > 0
        ),
        agg AS (
            SELECT mint,
                   count(*) AS n_sells,
                   median(u) AS med_realization,
                   quantile_cont(u, 0.10) AS p10_realization,
                   quantile_cont(u, 0.90) AS p90_realization,
                   -- the loss tail: how deep in the red do sellers let it get?
                   avg((u < 0)::int) AS frac_sells_red,
                   avg((u < -0.30)::int) AS frac_sells_deep_red,
                   avg((u < -0.60)::int) AS frac_sells_very_deep_red,
                   median(CASE WHEN u < 0 THEN -u END) AS med_loss_taken,
                   quantile_cont(CASE WHEN u < 0 THEN -u END, 0.90) AS p90_loss_taken,
                   median(CASE WHEN u > 0 THEN u END) AS med_gain_taken,
                   -- SOL-weighted versions, because one whale is not one voter
                   sum(CASE WHEN u < 0 THEN sol ELSE 0 END) / nullif(sum(sol), 0)
                       AS solshare_sells_red
            FROM s GROUP BY 1
        ),
        last AS (
            SELECT mint, owner, qty_after AS qty, basis_after AS basis, mark_after AS mark
            FROM (SELECT mint, owner, qty_after, basis_after, mark_after,
                         row_number() OVER (PARTITION BY mint, owner
                                            ORDER BY block_slot DESC, tx_index DESC) AS rk
                  FROM read_parquet('{basis}'))
            WHERE rk = 1 AND qty_after > {DUST_RAW}
        ),
        spot AS (
            SELECT mint, arg_max(mark_after, block_slot * 1000000 + tx_index) AS spot
            FROM read_parquet('{basis}') WHERE mark_after > 0 GROUP BY 1
        ),
        hold AS (
            SELECT l.mint,
                   sum(CASE WHEN l.basis > s.spot THEN l.qty ELSE 0 END) / nullif(sum(l.qty), 0)
                       AS supply_underwater,
                   sum(CASE WHEN l.basis > 2 * s.spot THEN l.qty ELSE 0 END)
                       / nullif(sum(l.qty), 0) AS supply_underwater_2x,
                   count(*) AS n_live_holders
            FROM last l JOIN spot s USING (mint)
            WHERE l.basis > 0
            GROUP BY 1
        ),
        -- HOLD-THROUGH-DRAWDOWN. The terminal underwater share is ~1.0 on essentially every
        -- coin -- at the end of a collapsed coin everybody is red, so it discriminates nothing.
        -- The informative version asks what each holder LIVED THROUGH: the deepest price the
        -- coin printed AFTER that wallet's own entry, against that wallet's own basis. A wallet
        -- that watched its position go 80% red and is still holding is a different animal from
        -- one that never saw red.
        sufmin AS (
            SELECT mint, block_time,
                   min(mark_after) OVER (PARTITION BY mint ORDER BY block_slot DESC,
                                         tx_index DESC
                                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                       AS sufmin_mark
            FROM read_parquet('{basis}') WHERE mark_after > 0
        ),
        entry AS (
            SELECT mint, owner, min(block_time) AS t_in
            FROM read_parquet('{basis}') WHERE delta_raw > 0 GROUP BY 1, 2
        ),
        deep AS (
            SELECT e.mint, e.owner, e.t_in, m.sufmin_mark
            FROM entry e ASOF JOIN sufmin m
              ON e.mint = m.mint AND e.t_in >= m.block_time
        ),
        through AS (
            SELECT d.mint,
                   sum(CASE WHEN d.sufmin_mark < 0.5 * l.basis THEN l.qty ELSE 0 END)
                       / nullif(sum(l.qty), 0) AS supply_held_through_50pct_red,
                   sum(CASE WHEN d.sufmin_mark < 0.2 * l.basis THEN l.qty ELSE 0 END)
                       / nullif(sum(l.qty), 0) AS supply_held_through_80pct_red,
                   count(*) AS n_survivors
            FROM deep d JOIN last l USING (mint, owner)
            WHERE l.basis > 0
            GROUP BY 1
        )
        SELECT c.mint, c.graduated, c.peak_mcap_sol, c.final_mcap_sol, c.lifetime_s,
               c.curve_touches, c.drawdown_from_peak, c.n_snipers, c.dev_buy_share,
               a.*, h.supply_underwater, h.supply_underwater_2x, h.n_live_holders,
               t.supply_held_through_50pct_red, t.supply_held_through_80pct_red, t.n_survivors
        FROM read_parquet('{cohort}') c
        JOIN agg a USING (mint)
        LEFT JOIN hold h USING (mint)
        LEFT JOIN through t USING (mint)
        WHERE a.n_sells >= {args.min_sells}
        """,
        out,
        "basis-shape features",
    )

    # A descriptive contrast only -- NOT a classifier. Coins are split on an outcome the other
    # lane does not own either (survival past the median lifetime) purely to show the feature
    # has non-trivial spread.
    desc = con.execute(
        f"""
        SELECT graduated,
               count(*) AS n,
               median(frac_sells_deep_red) AS med_frac_deep_red,
               median(med_loss_taken) AS med_loss_taken,
               median(med_gain_taken) AS med_gain_taken,
               median(supply_underwater) AS med_supply_underwater,
               median(supply_held_through_50pct_red) AS med_held_through_50,
               median(supply_held_through_80pct_red) AS med_held_through_80
        FROM read_parquet('{out}') GROUP BY 1 ORDER BY 1"""
    ).fetchdf()
    print(desc.to_string(index=False), flush=True)
    (_out() / "q3_basis_shape_summary.json").write_text(
        json.dumps(
            {
                "note": (
                    "Feature delivery for the pvp_vamps lane. No PvP classifier is fitted "
                    "here; that lane owns the outcome."
                ),
                "columns": [
                    "frac_sells_red", "frac_sells_deep_red", "frac_sells_very_deep_red",
                    "med_loss_taken", "p90_loss_taken", "med_gain_taken",
                    "solshare_sells_red", "supply_underwater", "supply_underwater_2x",
                    "supply_held_through_50pct_red", "supply_held_through_80pct_red",
                ],
                "descriptive_by_graduation": desc.to_dict(orient="records"),
            },
            indent=2,
            default=str,
        )
    )
    print(f"[q3] -> {out}  ({time.time() - t0:.0f}s)", flush=True)
    return 0


# =====================================================================================
# q4 -- the rug-fuel gauge
# =====================================================================================

#: Thresholds for "acquired far enough below spot that dumping is nearly free". Reported as a
#: grid; PROGRAM.md §3 rule 7 -- report the threshold with every number, because in this
#: literature the same quantity spans 0.12% to 94.5% purely on knob settings.
Q4_THETA = (0.10, 0.25, 0.50)


def cmd_q4(args: argparse.Namespace) -> int:
    """Fraction of live supply whose cost basis sits below theta x spot: live-computable rug fuel.

    WHAT IT IS AND IS NOT. It is a measure of how much supply could be dumped at a large
    multiple of what it cost -- the fuel, not the match. It says nothing about intent, and
    attested own-supply is never counted as threat: the operator's own wallets
    (wallet_labels.yaml) are excluded and reported separately, because a scheduled,
    publicly-attested unlock is a known overhang rather than an ambush.

    LEFT CENSORING IS THE BINDING LIMITATION on the four operator coins and it is stated
    up front rather than buried. All four were born before the corpus window, so any holder
    who acquired before 2026-08-05 has no observable basis. The gauge is therefore reported
    on the OBSERVABLE stratum with its supply share attached, plus a hard bound on the censored
    stratum taken from the price path itself: a holder who bought in-pool at any point in the
    observed history paid at least the minimum observed price, so their profit multiple is at
    most spot/min_price. That bound needs no assumption about who they are.
    """
    con = _duck(args.threads, args.memory)
    t0 = time.time()
    basis = _out() / "basis.parquet"
    xfer = _out() / "xfer.parquet"

    own = _own_wallets()
    own_lit = ",".join(f"'{w}'" for w in own) or "''"
    print(f"[q4] {len(own)} attested operator wallets excluded from threat supply", flush=True)

    con.execute(
        f"""
        CREATE OR REPLACE TABLE last AS
        SELECT mint, owner, qty_after AS qty, basis_after AS basis
        FROM (SELECT mint, owner, qty_after, basis_after,
                     row_number() OVER (PARTITION BY mint, owner
                                        ORDER BY block_slot DESC, tx_index DESC) AS rk
              FROM read_parquet('{basis}'))
        WHERE rk = 1 AND qty_after > {DUST_RAW}
        """
    )
    # SPOT MUST BE DUST-ROBUST. On the pool route the mark is the last traded price, and the
    # last trade on a quiet coin is routinely a 0.0001-SOL dust print whose effective price is
    # meaningless. Taking the last mark from trades of at least `--min-sol` moves DREGG's
    # implied all-time low by more than two orders of magnitude, which would otherwise have
    # been reported as a 176x overhang.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE spot AS
        SELECT mint, arg_max(mark_after, block_slot * 1000000 + tx_index) AS spot,
               max(block_time) AS t_spot,
               quantile_cont(mark_after, 0.01) AS p01_mark,
               min(mark_after) AS min_mark, max(mark_after) AS max_mark
        FROM read_parquet('{basis}')
        WHERE mark_after > 0 AND abs(sol) >= {args.min_sol}
        GROUP BY 1
        """
    )
    # THREE GAUGES, because conflating them is the mistake that makes this number useless.
    #  * `rugfuel_NNN`   -- ALL live supply below theta x spot, free supply included.
    #  * `rugfuel_paid_` -- only supply the holder actually BOUGHT below theta x spot. This is
    #                       the accumulator sitting on a large multiple, which is what the
    #                       phrase "rug fuel" is usually reaching for.
    #  * `zero_basis_share` -- supply that arrived by transfer and cost its holder nothing:
    #                       airdrops and bundler distributions. Free, yes, but a scheduled
    #                       holder airdrop and a hidden accumulation are different objects and
    #                       are never added together here.
    # And all three exclude attested operator wallets from the threat numerator (`_exown_`).
    thet = ", ".join(
        f"sum(CASE WHEN l.basis < {th} * s.spot THEN l.qty ELSE 0 END) / nullif(sum(l.qty), 0)"
        f" AS rugfuel_{int(th * 100):03d}"
        for th in Q4_THETA
    )
    thet_paid = ", ".join(
        f"sum(CASE WHEN l.basis > 0 AND l.basis < {th} * s.spot THEN l.qty ELSE 0 END)"
        f" / nullif(sum(l.qty), 0) AS rugfuel_paid_{int(th * 100):03d}"
        for th in Q4_THETA
    )
    thet_free = ", ".join(
        f"sum(CASE WHEN l.basis < {th} * s.spot AND NOT l.is_own THEN l.qty ELSE 0 END)"
        f" / nullif(sum(CASE WHEN NOT l.is_own THEN l.qty ELSE 0 END), 0)"
        f" AS rugfuel_exown_{int(th * 100):03d}"
        for th in Q4_THETA
    )
    out = _out() / "q4_rugfuel.parquet"
    _copy(
        con,
        f"""
        WITH l AS (
            SELECT last.*, (last.owner IN ({own_lit})) AS is_own,
                   coalesce(x.xfer_in_raw, 0) AS xin
            FROM last LEFT JOIN read_parquet('{xfer}') x USING (mint, owner)
        )
        SELECT l.mint, s.spot, s.t_spot, s.p01_mark, s.min_mark, s.max_mark,
               count(*) AS n_holders,
               sum(l.qty) AS live_supply_raw,
               sum(CASE WHEN l.is_own THEN l.qty ELSE 0 END) / nullif(sum(l.qty), 0)
                   AS own_supply_share,
               sum(CASE WHEN l.xin > 0 THEN l.qty ELSE 0 END) / nullif(sum(l.qty), 0)
                   AS transfer_touched_share,
               sum(CASE WHEN l.basis <= 0 THEN l.qty ELSE 0 END) / nullif(sum(l.qty), 0)
                   AS zero_basis_share,
               {thet},
               {thet_paid},
               {thet_free},
               -- hard bound on the CENSORED stratum: a holder who bought in-pool at any point
               -- in the observed history paid at least the 1st-percentile mark, so no holder,
               -- observed or not, can be up more than this.
               s.spot / nullif(s.p01_mark, 0) AS max_multiple_any_holder,
               s.spot / nullif(s.min_mark, 0) AS max_multiple_incl_dust
        FROM l JOIN spot s USING (mint)
        GROUP BY 1, 2, 3, 4, 5, 6
        HAVING count(*) >= {args.min_holders}
        """,
        out,
        "rug-fuel gauge",
    )

    pop = con.execute(
        f"""
        SELECT count(*) AS n_coins,
               median(rugfuel_010) AS med_010, quantile_cont(rugfuel_010, 0.90) AS p90_010,
               median(rugfuel_025) AS med_025, quantile_cont(rugfuel_025, 0.90) AS p90_025,
               median(rugfuel_050) AS med_050, quantile_cont(rugfuel_050, 0.90) AS p90_050,
               median(rugfuel_paid_010) AS med_paid_010,
               quantile_cont(rugfuel_paid_010, 0.90) AS p90_paid_010,
               median(zero_basis_share) AS med_zero_basis,
               quantile_cont(zero_basis_share, 0.90) AS p90_zero_basis
        FROM read_parquet('{out}')"""
    ).fetchdf()
    print("[q4] cohort distribution:\n" + pop.to_string(index=False), flush=True)

    ops = ",".join(f"'{m}'" for m in OPERATOR_COINS.values())
    opdf = con.execute(
        f"SELECT * FROM read_parquet('{out}') WHERE mint IN ({ops})"
    ).fetchdf()
    label = {v: k for k, v in OPERATOR_COINS.items()}
    opdf.insert(0, "coin", opdf["mint"].map(label))
    print("[q4] operator coins:\n" + opdf.to_string(index=False), flush=True)

    # Left-censoring: how much of each operator coin's live supply has an OBSERVABLE basis?
    cens = con.execute(
        f"""
        SELECT l.mint, count(*) AS n_holders_observed, sum(l.qty) AS observed_supply_raw
        FROM last l WHERE l.mint IN ({ops}) GROUP BY 1"""
    ).fetchdf()
    cens.insert(0, "coin", cens["mint"].map(label))
    print("[q4] observable stratum on the operator coins:\n" + cens.to_string(index=False),
          flush=True)

    (_out() / "q4_rugfuel.json").write_text(
        json.dumps(
            {
                "thresholds": list(Q4_THETA),
                "cohort": pop.to_dict(orient="records"),
                "operator_coins": opdf.to_dict(orient="records"),
                "operator_coins_observable_stratum": cens.to_dict(orient="records"),
                "attested_own_wallets": sorted(own),
                "left_censoring_note": (
                    "All four operator coins predate the corpus window, so only holders who "
                    "traded within 2026-08-05..14 have an observable basis. Read the gauge on "
                    "the observable stratum only, with max_multiple_any_holder = spot/min_mark "
                    "as the hard bound on the censored remainder."
                ),
            },
            indent=2,
            default=str,
        )
    )
    print(f"[q4] -> {out}  ({time.time() - t0:.0f}s)", flush=True)
    return 0


def cmd_bounds(args: argparse.Namespace) -> int:
    """Bound the CENSORED stratum of the operator's four coins from a longer price history.

    The corpus window is ten days and all four coins predate it, so most of their holders have
    no observable basis. That is a real hole and the honest way to shrink it is not to guess at
    those holders but to bound what they can possibly be worth: a holder who acquired IN-POOL
    at any point in the observed history paid at least the lowest price the pool ever printed,
    so no holder can be up more than ``spot / min_price`` no matter who they are.

    ``state/bulk_history`` carries the eleven cluster pools for ~48 days -- five times the
    corpus window -- which makes that bound far tighter than the ten-day version. Dust prints
    are excluded the same way ``q4`` excludes them, and the bound is reported at both the 1st
    percentile (robust) and the true minimum (worst case).
    """
    con = _duck(args.threads, args.memory)
    hist = Path(os.environ.get("UPNL_BULK_HISTORY",
                               str(REPO_ROOT / "state" / "bulk_history" / "parquet")))
    if not hist.exists():
        print(f"[bounds] no bulk_history at {hist}; long-window bound unavailable")
        return 0
    label = {v: k for k, v in OPERATOR_COINS.items()}
    ops = ",".join(f"'{m}'" for m in OPERATOR_COINS.values())
    df = con.execute(
        f"""
        WITH sw AS (
            SELECT block_time,
                   CASE WHEN token_in_mint = '{WSOL}' THEN token_out_mint ELSE token_in_mint END
                       AS mint,
                   CASE WHEN token_in_mint = '{WSOL}'
                        THEN CAST(token_in_raw AS DOUBLE) / {LAMPORTS}
                        ELSE CAST(token_out_raw AS DOUBLE) / {LAMPORTS} END AS sol,
                   CASE WHEN token_in_mint = '{WSOL}'
                        THEN CAST(token_out_raw AS DOUBLE)
                        ELSE CAST(token_in_raw AS DOUBLE) END AS tok
            FROM read_parquet('{hist}/*.parquet')
            -- SCHEMA TRAP, and it is the OPPOSITE of the one in the bulk_pump corpus.
            -- scripts/pump_history.py warns that there `err` is an EMPTY STRING on success and
            -- never NULL. In `state/bulk_history` the same field is NULL on success. Testing
            -- one convention against the other silently returns zero rows, which is exactly
            -- what the first run of this did.
            WHERE kind = 'swap' AND (err IS NULL OR err = '')
              AND ('{WSOL}' IN (token_in_mint, token_out_mint))
        )
        SELECT mint, count(*) AS n_swaps,
               min(block_time) AS t_first, max(block_time) AS t_last,
               quantile_cont(sol / tok, 0.01) AS p01_price,
               min(sol / tok) AS min_price,
               quantile_cont(sol / tok, 0.99) AS p99_price,
               max(sol / tok) AS max_price,
               arg_max(sol / tok, block_time) AS last_price
        FROM sw
        WHERE mint IN ({ops}) AND tok > 0 AND sol >= {args.min_sol}
        GROUP BY 1"""
    ).fetchdf()
    if df.empty:
        print("[bounds] no operator-coin swaps in bulk_history")
        return 0
    df.insert(0, "coin", df["mint"].map(label))
    df["days_covered"] = (df["t_last"] - df["t_first"]) / 86400.0
    df["max_multiple_p01"] = df["last_price"] / df["p01_price"]
    df["max_multiple_min"] = df["last_price"] / df["min_price"]
    print(df.to_string(index=False), flush=True)
    (_out() / "q4_longwindow_bounds.json").write_text(
        json.dumps(
            {
                "source": str(hist),
                "min_sol_filter": args.min_sol,
                "note": (
                    "max_multiple_* bounds the profit multiple of ANY in-pool acquirer over the "
                    "covered window, observed or censored. It does NOT bound a holder who "
                    "received supply off-pool (airdrop, escrow release, OTC)."
                ),
                "coins": df.to_dict(orient="records"),
            },
            indent=2,
            default=str,
        )
    )
    return 0


def _own_wallets() -> set:
    """The operator's attested wallets. Attested own supply is never counted as rug fuel."""
    path = Path(os.environ.get("UPNL_LABELS", str(REPO_ROOT / "wallet_labels.yaml")))
    out: set = set()
    if not path.exists():
        return out
    try:
        import yaml

        doc = yaml.safe_load(path.read_text()) or {}
        for entry in doc.get("own_wallets", []) or []:
            a = (entry or {}).get("address")
            if a:
                out.add(a)
    except Exception:
        # A parse failure must not silently reclassify the operator's own bags as threat
        # supply, so it is loud rather than swallowed.
        print(f"[q4] WARNING: could not parse {path}; own-wallet exclusion is EMPTY", flush=True)
    return out


def _by_fdr(pvals, q):
    """Benjamini-Yekutieli over a cell grid whose tests are not independent."""
    ps = [(i, p) for i, p in enumerate(pvals) if p is not None]
    if not ps:
        return {"q": q, "n": 0, "rejected": []}
    m = len(ps)
    c_m = sum(1.0 / k for k in range(1, m + 1))
    ps.sort(key=lambda t: t[1])
    k_max = 0
    for rank, (_, p) in enumerate(ps, start=1):
        if p <= rank * q / (m * c_m):
            k_max = rank
    return {
        "q": q,
        "n": m,
        "c_m": c_m,
        "crit_at_rank": [rank * q / (m * c_m) for rank in range(1, m + 1)],
        "rejected": [i for i, _ in ps[:k_max]],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        # Small by default and deliberately so: this repository's research lanes share one
        # laptop and a fold that respects nobody's memory is how the box dies.
        p.add_argument("--threads", type=int, default=4)
        p.add_argument("--memory", default="6GB")
        return p

    f = common(sub.add_parser("flow", help="per-(mint, wallet, tx) trade legs with exact SOL"))
    f.add_argument("--min-touches", type=int, default=MIN_TOUCHES)
    f.add_argument("--days", default=None, help="ledger day glob, e.g. '2026-08-0*'")
    f.set_defaults(fn=cmd_flow)

    b = common(sub.add_parser("basis", help="average-cost trajectory per (coin, wallet)"))
    b.set_defaults(fn=cmd_basis)

    c = common(sub.add_parser("check", help="falsify the window basis; price FIFO sensitivity"))
    c.add_argument("--sample", type=int, default=4000)
    c.add_argument("--seed", type=int, default=17)
    c.set_defaults(fn=cmd_check)

    q1 = common(sub.add_parser("q1", help="basis density vs price reversals"))
    q1.add_argument("--rotations", type=int, default=200)
    q1.add_argument("--max-coins", type=int, default=1500)
    q1.add_argument("--fdr-q", type=float, default=0.05)
    q1.add_argument("--seed", type=int, default=20260815)
    q1.set_defaults(fn=cmd_q1)

    q2 = common(sub.add_parser("q2", help="realization-policy fingerprint vs tooling"))
    q2.add_argument("--max-wallets", type=int, default=40000)
    q2.add_argument("--neg-per-key", type=int, default=2)
    q2.add_argument("--min-snipes", type=int, default=5)
    q2.add_argument("--min-cooc", type=int, default=3)
    q2.add_argument("--crew-nulls", type=int, default=200)
    q2.add_argument("--crew-alpha", type=float, default=0.01)
    q2.add_argument("--seed", type=int, default=20260815)
    q2.set_defaults(fn=cmd_q2)

    de = common(sub.add_parser("describe", help="the distribution, and the round-number test"))
    de.add_argument("--min-sol", type=float, default=0.01)
    de.set_defaults(fn=cmd_describe)

    hz = common(sub.add_parser("hazard", help="P(sell next tick | unrealized PnL), with a risk set"))
    hz.add_argument("--tick", type=int, default=60)
    hz.add_argument("--max-coins", type=int, default=3000)
    hz.add_argument("--min-ev", type=int, default=200)
    hz.add_argument("--max-ev", type=int, default=200000)
    hz.add_argument("--max-ticks", type=int, default=20000000)
    hz.add_argument("--min-sol", type=float, default=0.01)
    hz.add_argument("--seed", type=int, default=20260815)
    hz.set_defaults(fn=cmd_hazard)

    q3 = common(sub.add_parser("q3", help="basis-shape feature for the pvp_vamps lane"))
    q3.add_argument("--min-sells", type=int, default=30)
    q3.set_defaults(fn=cmd_q3)

    q4 = common(sub.add_parser("q4", help="the rug-fuel gauge"))
    q4.add_argument("--min-holders", type=int, default=20)
    q4.add_argument("--min-sol", type=float, default=0.01,
                    help="ignore fills smaller than this when reading the spot mark")
    q4.set_defaults(fn=cmd_q4)

    bo = common(sub.add_parser("bounds", help="long-window censored-stratum bound (bulk_history)"))
    bo.add_argument("--min-sol", type=float, default=0.01)
    bo.set_defaults(fn=cmd_bounds)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
