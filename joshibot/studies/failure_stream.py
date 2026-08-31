#!/usr/bin/env python3
"""The failure stream: 922,432 reverted transactions on our own pools, read as intelligence.

THE IDEA THE OPERATOR ASKED FOR
--------------------------------
A transaction that fails still landed on chain and still paid its fee. It therefore
publishes, for free, what some other machine was TRYING to do: when its trigger fired,
which pool it aimed at, what it was willing to pay, and how much compute it burned before
it gave up. Nobody reads this stream. Everything downstream of a fill -- every study in
this directory before this one -- reads only the transactions that succeeded.

TWO PREMISES OF THE BRIEF ARE FALSE, AND FINDING THAT OUT IS THE FIRST RESULT
-----------------------------------------------------------------------------
1. **The corpus has ZERO failures.** ``state/bulk_pump/daily/`` is 106,639,238 rows over
   ten UTC days and ``COUNT(*) WHERE err <> ''`` is **0** on every single day. This is not
   a bug in the export, it is a consequence of its design: the query keeps a transaction
   only when a pump-mint balance CHANGED, and a reverted transaction's balances roll back,
   so ``pre == post`` and the row is filtered out before ``err`` is ever consulted. The
   ``err`` column is present, typed, documented -- and constant. Any study that plans to
   read failures out of the corpus is planning against a column that cannot vary.

2. **The live cluster tape's ``attempt`` rows carry no fee payer and no compute units.**
   ``shitcoims_cluster.parse.Attempt`` says so in its own docstring: the row is emitted
   from the ``getSignaturesForAddress`` listing alone, precisely to avoid the
   ``getTransaction`` that the signer and the amounts would require. 61,000 attempt rows,
   zero signers. So "the heavy fee-payers on our pools" cannot be enumerated from the tape
   the brief points at. The prior "10 fee-payers = 46.6% of failures"
   (``RESULT_execution_landing.md``) came from a 2,390-transaction RPC sample, not the tape.

THE DATA THAT DOES CARRY IT
----------------------------
``state/bulk_history/parquet/`` -- the BigQuery pull of our own pools, 48 days, 9 pools,
3,384,843 rows of which **922,432 are ``kind='failed'``** -- carries on every failure:

* ``err`` -- ``"Error processing Instruction 3: custom program error: 0x51"``: the failing
  instruction INDEX and the program's own error code. (The live tape writes the same fact
  in decimal: ``{'InstructionError': [3, {'Custom': 81}]}``. 0x51 = 81. They agree.)
* ``fee_lamports`` -- what the sender actually paid to fail. **This is the bid.**
* ``compute_units`` -- what it burned before reverting. **This is the work.**
* ``vaults`` -- and here is the free gift: for a failed transaction ``pre_raw == post_raw``
  on both legs (verified: 839,614 of 839,614 failure legs on 2026-08-11), so every failure
  carries **the pool's exact integer reserves at its own slot**. The price the failing bot
  saw is observed, not interpolated.
* ``slot`` + ``tx_index`` -- position INSIDE the block, which no RPC call returns. This is
  what makes "was it beaten within the block, or did it abort alone?" an exact question.

What it still does not carry is the signer: the ``accounts`` column was priced at +267
GB/day and not taken (``RESULT_bulk_history.md``). So identity is reconstructed two ways --
a behavioural fingerprint from (instruction index, error code, compute, fee) that costs
nothing, and a bounded read-only ``getTransaction`` sample that VALIDATES the fingerprint
against the true fee payer instead of assuming it works.

WHAT THIS STUDY CAN AND CANNOT CONCLUDE
----------------------------------------
* It can taxonomise failures, because 922k of them is a lot of failures.
* It can separate **designed aborts** (an arb program checking its own precondition and
  bailing -- a successful no-op, and ``RESULT_execution_landing.md`` measured 96.1% of a
  sample failing inside third-party programs) from **race losses** (someone else's fill
  landed first in the same block) -- and the separation is EXACT, via ``tx_index``.
* It can test whether a failure surge predicts anything the successful stream does not.
* It **cannot** run the survival arm the brief asked for. Failures exist on 9 pools; a
  hazard model of coin death needs thousands of coins, and the only dataset with thousands
  of coins is the corpus, which has zero failures. Nine clusters is also too few for
  cluster-robust asymptotics, so every panel test here is reported against a **rotation
  null** (the failure series circularly shifted inside its own pool), which needs no
  cluster count at all, alongside the clustered t for reference.

Reproduce::

    uv run --group research python studies/failure_stream.py all
    uv run --group research python studies/failure_stream.py rpc --n 2500   # network

Sections: ``panel taxonomy race fingerprint rpc surge practical holdout``. Everything
caches to ``studies/data/failure_stream/``; a re-run after ``rpc`` is offline.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import random
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Final, Sequence

REPO: Final[Path] = Path(__file__).resolve().parent.parent
BULK: Final[Path] = REPO / "state" / "bulk_history" / "parquet"
TAPE: Final[Path] = REPO / "state" / "cluster_tape" / "swaps"
DATA: Final[Path] = REPO / "studies" / "data" / "failure_stream"

WSOL: Final[str] = "So11111111111111111111111111111111111111112"
COMPUTE_BUDGET: Final[str] = "ComputeBudget111111111111111111111111111111"

# The minute grid every panel test runs on. One minute is ~150 slots: fine enough that a
# burst is not averaged away, coarse enough that the count is not almost always zero.
BIN_S: Final[int] = 60

# Lookbacks for "what did the price do just before this failure fired".
PRE_WINDOWS_S: Final[tuple[int, ...]] = (5, 30, 300)

# Forward horizons for the surge test, in minutes.
FWD_MIN: Final[tuple[int, ...]] = (1, 5, 15)

# RESOURCE CEILING. This laptop is shared with other corpus folds; the operator has already
# had to kill a 23 GB python to recover it. Every DuckDB connection here is capped, and the
# panel is deliberately narrow enough that the pandas side stays around 2 GB.
MEM_LIMIT: Final[str] = "6GB"

FDR_Q: Final[float] = 0.10
ROTATIONS: Final[int] = 500
MIN_ROTATION_MIN: Final[int] = 60  # a rotation shorter than this is not a null, it is a lag

# Programs we can name without asking anyone. Everything else the RPC sample finds is
# reported by its raw id, because a program id from memory is a claim and not a fact.
KNOWN_PROGRAMS: Final[dict[str, str]] = {
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "PumpSwap AMM",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora DLMM",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "pump.fun bonding curve",
    "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ": "pump.fun fee program",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter Aggregator v6",
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": "Jupiter Aggregator v4",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "SPL Token",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb": "SPL Token-2022",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Associated Token Account",
    "11111111111111111111111111111111": "System",
    COMPUTE_BUDGET: "ComputeBudget",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM v4",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo2": "(sentinel)",
}


# ============================================================================ plumbing


def _duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - declared in the research group
        raise SystemExit("duckdb is required: run with `uv run --group research`") from exc
    con = duckdb.connect()
    con.execute("SET threads TO 6")
    # 6 GB, not 10: this Mac has had four corpus folds running at once and the operator had
    # to kill a 23 GB python to recover it. One fold at a time, and each one capped.
    con.execute(f"SET memory_limit='{MEM_LIMIT}'")
    con.execute("SET preserve_insertion_order=false")
    with contextlib.suppress(Exception):  # pragma: no cover - pragma name varies
        con.execute("PRAGMA disable_progress_bar")
    return con


def _np() -> Any:
    import numpy

    return numpy


def by_fdr(pvalues: Sequence[float], q: float = FDR_Q) -> list[bool]:
    """Benjamini-Yekutieli step-up. Imported in spirit from ``callout_volatility.by_fdr``.

    BY and not BH because the hypotheses here are the same failure series measured against
    overlapping forward windows -- positively AND negatively dependent in ways nobody has
    characterised, and BY is the procedure that holds under arbitrary dependence.
    """
    m = len(pvalues)
    if m == 0:
        return []
    c_m = sum(1.0 / i for i in range(1, m + 1))
    order = sorted(range(m), key=lambda i: pvalues[i])
    keep = [False] * m
    cut = -1
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= (rank / (m * c_m)) * q:
            cut = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= cut:
            keep[idx] = True
    return keep


def bootstrap_ci(
    values: Sequence[float], *, draws: int = 2000, seed: int = 11, alpha: float = 0.05
) -> tuple[float, float, float]:
    """(mean, lo, hi) by the percentile bootstrap over whatever unit is passed in."""
    np = _np()
    arr = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(draws, arr.size))
    means = arr[idx].mean(axis=1)
    return float(arr.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def fmt_p(p: float) -> str:
    if p != p:
        return "n/a"
    return "<1e-4" if p < 1e-4 else f"{p:.4f}"


# ============================================================================ the panel


ERR_CUSTOM = re.compile(r"Error processing Instruction (\d+): custom program error: 0x([0-9a-fA-F]+)")
ERR_OTHER = re.compile(r"Error processing Instruction (\d+): (.+?)\"?$")


def classify_err(err: str) -> tuple[int, int | None, str]:
    """(instruction index, custom code or None, class label).

    The class label is the SVM-level reason. A ``custom`` failure is the program itself
    saying no; everything else is the runtime saying no, and the two mean different things
    for whose fault the failure is.
    """
    if not err:
        return -1, None, "success"
    m = ERR_CUSTOM.search(err)
    if m:
        return int(m.group(1)), int(m.group(2), 16), "custom"
    if "exceeded max loaded accounts data size" in err:
        return -1, None, "accounts_data_cap"
    m2 = ERR_OTHER.search(err)
    if m2:
        text = m2.group(2).strip().strip('"')
        idx = int(m2.group(1))
        if "insufficient funds" in text:
            return idx, None, "insufficient_funds"
        if "Computational budget exceeded" in text:
            return idx, None, "compute_budget"
        if "Program failed to complete" in text:
            return idx, None, "panicked"
        return idx, None, "runtime:" + text[:40]
    return -1, None, "unparsed"


def build_panel(*, echo: Callable[[str], None] = print) -> Path:
    """One DuckDB pass over ``state/bulk_history/`` -> a per-transaction pool tape.

    Rows are every transaction that TOUCHED one of our pools, successful or not, with the
    pool's own integer reserves attached. Orientation (which leg is the price numerator) is
    derived from the pool labels rather than hardcoded: the ``X/SOL`` pools name the mint
    that is not WSOL, and those names then orient the token/token DLMM pools.
    """
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "panel.parquet"
    files = sorted(BULK.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet under {BULK}")
    con = _duckdb()
    listed = "[" + ",".join(f"'{p}'" for p in files) + "]"
    con.execute(
        f"""
        CREATE OR REPLACE TABLE raw AS
        SELECT kind, pool, label, dex, block_time, slot, tx_index, signature,
               COALESCE(err, '') AS err,
               TRY_CAST(fee_lamports AS BIGINT) AS fee,
               compute_units AS cu,
               vaults[1].mint AS m1, TRY_CAST(vaults[1].pre_raw  AS BIGINT) AS pre1,
                                     TRY_CAST(vaults[1].post_raw AS BIGINT) AS post1,
               vaults[2].mint AS m2, TRY_CAST(vaults[2].pre_raw  AS BIGINT) AS pre2,
                                     TRY_CAST(vaults[2].post_raw AS BIGINT) AS post2
        FROM read_parquet({listed})
        WHERE len(vaults) = 2 AND block_time IS NOT NULL
        """
    )
    n = con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
    echo(f"panel: {n:,} pool-touching transactions from {len(files)} day files")

    frame = con.execute("SELECT * FROM raw ORDER BY pool, slot, tx_index").df()
    con.close()

    # --- orientation -------------------------------------------------------------
    import numpy as np

    symbol: dict[str, str] = {}
    for _pool, grp in frame.groupby("pool", sort=False):
        label = str(grp["label"].iloc[0])
        mints = {str(grp["m1"].iloc[0]), str(grp["m2"].iloc[0])}
        if WSOL in mints and "/" in label:
            other = (mints - {WSOL}).pop()
            symbol[other] = label.split("/")[0].strip().upper()
    symbol[WSOL] = "SOL"
    echo("panel: mint symbols resolved from the X/SOL pools: " + ", ".join(sorted(symbol.values())))

    quote_of: dict[str, str] = {}
    for pool, grp in frame.groupby("pool", sort=False):
        label = str(grp["label"].iloc[0])
        m1, m2 = str(grp["m1"].iloc[0]), str(grp["m2"].iloc[0])
        if WSOL in (m1, m2):
            quote_of[pool] = WSOL
            continue
        want = label.split("/")[1].split()[0].strip().upper() if "/" in label else ""
        quote_of[pool] = m2 if symbol.get(m2, "") == want else m1

    q_is_1 = frame["pool"].map(quote_of).to_numpy() == frame["m1"].to_numpy()
    pre_q = np.where(q_is_1, frame["pre1"], frame["pre2"]).astype("float64")
    pre_b = np.where(q_is_1, frame["pre2"], frame["pre1"]).astype("float64")
    post_q = np.where(q_is_1, frame["post1"], frame["post2"]).astype("float64")
    post_b = np.where(q_is_1, frame["post2"], frame["post1"]).astype("float64")

    with np.errstate(divide="ignore", invalid="ignore"):
        frame["logp_pre"] = np.log(pre_q) - np.log(pre_b)
        frame["logp"] = np.log(post_q) - np.log(post_b)
    frame["quote_pre"] = pre_q
    frame["base_pre"] = pre_b
    frame["d_quote"] = post_q - pre_q

    parsed = [classify_err(str(e)) for e in frame["err"]]
    frame["instr_idx"] = [p[0] for p in parsed]
    frame["code"] = [p[1] if p[1] is not None else -1 for p in parsed]
    frame["err_class"] = [p[2] for p in parsed]
    frame["failed"] = (frame["kind"] == "failed").astype(int)
    frame["minute"] = (frame["block_time"] // BIN_S) * BIN_S

    frame = frame.drop(columns=["m1", "m2", "pre1", "pre2", "post1", "post2"])
    frame.to_parquet(out, index=False)
    echo(f"panel: wrote {out} ({len(frame):,} rows, {frame['failed'].sum():,} failures)")
    return out


def load_panel(echo: Callable[[str], None] = print) -> Any:
    import numpy as np
    import pandas as pd

    path = DATA / "panel.parquet"
    if not path.exists():
        build_panel(echo=echo)
    frame = pd.read_parquet(path)
    frame["hour"] = (frame["block_time"] // 3600) * 3600
    frame["sig"] = [
        signature_of(int(i), int(c), str(k)) if f else ""
        for i, c, k, f in zip(
            frame["instr_idx"], frame["code"], frame["err_class"], frame["failed"], strict=False
        )
    ]
    for w in PRE_WINDOWS_S:
        frame[f"pre{w}"] = pre_move(frame, window_s=w)
    # The fingerprint cell, needed by more than one section, so it is defined once here.
    cu_b = np.round(np.log2(np.maximum(frame["cu"].fillna(1).clip(lower=1), 1)) * 2) / 2
    fee_b = np.round(np.log2(np.maximum(frame["fee"].fillna(1).clip(lower=1), 1)) * 2) / 2
    frame["cell"] = np.where(
        frame["failed"] == 1,
        frame["sig"] + "|cu" + cu_b.astype(str) + "|f" + fee_b.astype(str),
        "",
    )
    return frame


# ========================================================================== 1. taxonomy


def signature_of(row_idx: int, code: int, err_class: str) -> str:
    if err_class == "custom":
        return f"i{row_idx}:0x{code:x}"
    return f"i{row_idx}:{err_class}"


def pre_move(frame: Any, *, window_s: int) -> Any:
    """|log price change| over the ``window_s`` seconds before every row, per pool.

    Computed on the pool's own dense print series -- every transaction that touched the
    pool, failures included, because a failure observes the reserves exactly. No
    interpolation and no external price feed.
    """
    np = _np()
    out = np.full(len(frame), np.nan)
    pos = 0
    for _pool, grp in frame.groupby("pool", sort=False):
        t = grp["block_time"].to_numpy()
        lp = grp["logp_pre"].to_numpy()
        n = len(t)
        # first index with time >= t[i] - window  (arrays are already slot/tx ordered)
        j = np.searchsorted(t, t - window_s, side="left")
        prev = np.where(j > 0, j - 1, 0)
        base = lp[prev]
        move = np.abs(lp - base)
        move[j == 0] = np.nan
        out[pos : pos + n] = move
        pos += n
    return out


def taxonomy(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    import pandas as pd

    fails = frame[frame["failed"] == 1]
    echo("")
    echo("=" * 100)
    echo("1. TAXONOMY -- what do the machines fail AT")
    echo("=" * 100)
    total = len(frame)
    echo(
        f"   {total:,} pool-touching transactions, {len(fails):,} failed "
        f"({100 * len(fails) / total:.1f}%), {frame['pool'].nunique()} pools, "
        f"{pd.to_datetime(frame['block_time'].min(), unit='s')} .. "
        f"{pd.to_datetime(frame['block_time'].max(), unit='s')} UTC"
    )

    echo("")
    echo("   By SVM-level class (what said no):")
    cls = fails.groupby("err_class").agg(n=("signature", "size"), fee=("fee", "median"), cu=("cu", "median"))
    cls = cls.sort_values("n", ascending=False)
    echo(f"   {'class':<26}{'n':>10}{'share':>9}{'med fee':>10}{'med CU':>10}")
    for name, r in cls.head(10).iterrows():
        echo(
            f"   {name!s:<26}{int(r['n']):>10,}{100 * r['n'] / len(fails):>8.1f}%"
            f"{r['fee']:>10,.0f}{r['cu']:>10,.0f}"
        )

    echo("")
    echo("   Failures by pool -- and the concentration that limits every claim below:")
    echo(f"   {'pool':<22}{'rows':>11}{'failures':>11}{'fail rate':>11}{'share of all failures':>23}")
    for label, grp in frame.groupby("label", sort=False):
        nf = int(grp["failed"].sum())
        echo(
            f"   {str(label)[:20]:<22}{len(grp):>11,}{nf:>11,}"
            f"{100 * nf / len(grp):>10.1f}%{100 * nf / len(fails):>22.1f}%"
        )

    echo("")
    echo("   Top failure signatures (instruction index : program error code):")
    echo(
        f"   {'signature':<20}{'n':>9}{'share':>8}{'pools':>7}{'med fee':>9}"
        f"{'med CU':>9}{'IQR CU':>17}{'top pool':>20}"
    )
    top = fails.groupby("sig").agg(
        n=("signature", "size"),
        pools=("pool", "nunique"),
        fee=("fee", "median"),
        cu=("cu", "median"),
        cu_lo=("cu", lambda s: s.quantile(0.25)),
        cu_hi=("cu", lambda s: s.quantile(0.75)),
    )
    top["top_pool"] = fails.groupby("sig")["label"].agg(lambda s: s.value_counts().index[0])
    top["top_share"] = fails.groupby("sig")["label"].agg(lambda s: s.value_counts(normalize=True).iloc[0])
    top = top.sort_values("n", ascending=False)
    for name, r in top.head(18).iterrows():
        echo(
            f"   {name:<20}{int(r['n']):>9,}{100 * r['n'] / len(fails):>7.1f}%{int(r['pools']):>7}"
            f"{r['fee']:>9,.0f}{r['cu']:>9,.0f}"
            f"{f'[{r.cu_lo:,.0f},{r.cu_hi:,.0f}]':>17}"
            f"{r['top_pool'][:14] + f' {100 * r.top_share:.0f}%':>20}"
        )

    # --- the identification that replaces an IDL we do not have -------------------
    echo("")
    echo("   IDENTIFYING THE SLIPPAGE CLASS BEHAVIOURALLY.")
    echo("   An anchor IDL would name error 0x1780. We do not have one, and a guessed name")
    echo("   is a fabrication. So the codes are identified by what the PRICE was doing in")
    echo("   the seconds before each failure, against the same pool-hour's successful")
    echo("   transactions as control. A slippage-triggered revert must sit on an elevated")
    echo("   preceding move; a designed abort need not.")
    echo("")

    echo("   Two controls, because the loose one has an obvious confound. Matching on the")
    echo("   pool-HOUR asks 'does this code fire in volatile hours?', which a code that")
    echo("   simply fires in BUSY minutes would also pass. Matching on the pool-MINUTE asks")
    echo("   'inside the very same minute, was this sender on a staler quote than the ones")
    echo("   that landed?'. Only the minute-matched column is evidence about the sender.")
    echo("")

    from scipy import stats

    rows: list[dict[str, Any]] = []
    ctrl = frame[frame["failed"] == 0]
    ctrl_h = ctrl.groupby(["pool", "hour"])["pre5"].mean()
    ctrl_m = ctrl.groupby(["pool", "minute"])["pre5"].mean()
    for sig_name in top.head(18).index:
        sub = fails[fails["sig"] == sig_name]
        gh = sub.groupby(["pool", "hour"])["pre5"].mean()
        cnt_h = sub.groupby(["pool", "hour"]).size()
        keep_h = cnt_h[cnt_h >= 5].index
        dh = (gh.reindex(keep_h) - ctrl_h.reindex(keep_h)).dropna()
        gm = sub.groupby(["pool", "minute"])["pre5"].mean()
        dm = (gm - ctrl_m.reindex(gm.index)).dropna()
        if len(dh) < 8 or len(dm) < 30:
            continue
        mh, _lo_h, _hi_h = bootstrap_ci(dh.to_numpy() * 1e4)
        mm, lo_m, hi_m = bootstrap_ci(dm.to_numpy() * 1e4)
        # Paired sign test on the tight control. Distribution-free, and the unit is the
        # pool-minute, so nothing inside a burst can manufacture it.
        pos = int((dm > 0).sum())
        p = float(stats.binomtest(pos, len(dm), 0.5).pvalue)
        rows.append(
            dict(
                sig=str(sig_name),
                n=len(sub),
                hours=len(dh),
                d_hour=mh,
                minutes=len(dm),
                d_min=mm,
                lo=lo_m,
                hi=hi_m,
                pos_share=pos / len(dm),
                p=p,
            )
        )
    keep_flags = by_fdr([r["p"] for r in rows], FDR_Q)
    echo(
        f"   {'signature':<16}{'hour-matched':>14}{'minute-matched':>16}{'95% CI':>22}"
        f"{'minutes':>9}{'p(sign)':>10}{'BY':>5}"
    )
    for r, k in zip(rows, keep_flags, strict=False):
        r["by_survives"] = bool(k)
        ci = f"[{r['lo']:.1f}, {r['hi']:.1f}]"
        echo(
            f"   {r['sig']:<16}{r['d_hour']:>14.1f}{r['d_min']:>16.1f}{ci:>22}"
            f"{r['minutes']:>9,}{fmt_p(r['p']):>10}{'yes' if k else '.':>5}"
        )
    echo("")
    echo("   Units are basis points of |log price move| over the 5 s before the transaction,")
    echo("   in excess of the control. POSITIVE minute-matched = this sender was reliably")
    echo("   later to a moving price than the senders who landed beside it -- a stale quote.")
    echo("   NEGATIVE or flat = a machine that reverts on its own schedule, not the market's.")

    return {"classes": cls.to_dict("index"), "signatures": top.head(30).to_dict("index"), "premove": rows}


# ============================================================== 2. race vs designed abort


def race(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Was the failure beaten inside its own block, or did it abort alone?

    ``tx_index`` makes this exact and it is available nowhere else: a failure whose block
    also contains a SUCCESSFUL swap on the same pool at a LOWER index lost a race that we
    can watch. One with no successful swap anywhere in its block reverted for reasons that
    have nothing to do with competition for that fill.
    """
    import pandas as pd

    echo("")
    echo("=" * 100)
    echo("2. RACE LOSS vs DESIGNED ABORT -- exact, from tx_index")
    echo("=" * 100)

    swaps = frame[frame["kind"] == "swap"]
    first_swap = swaps.groupby(["pool", "slot"])["tx_index"].min()
    n_swap_slot = swaps.groupby(["pool", "slot"]).size()

    key = pd.MultiIndex.from_arrays([frame["pool"], frame["slot"]])
    frame["slot_swaps"] = n_swap_slot.reindex(key).to_numpy()
    frame["slot_swaps"] = frame["slot_swaps"].fillna(0)
    frame["first_swap_idx"] = first_swap.reindex(key).to_numpy()
    frame["beaten"] = (frame["slot_swaps"] > 0) & (frame["tx_index"] > frame["first_swap_idx"])

    fails = frame[frame["failed"] == 1]
    refs = frame[frame["kind"] == "reference"]
    echo(
        f"   failures in a block that also contains a landed swap on the same pool: "
        f"{100 * (fails['slot_swaps'] > 0).mean():.1f}%"
    )
    echo(
        f"   ... of which the failure is AFTER that swap in the block (beaten): "
        f"{100 * fails['beaten'].mean():.1f}%"
    )
    echo(
        f"   same statistic for non-failing reference transactions (the base rate): "
        f"{100 * (refs['slot_swaps'] > 0).mean():.1f}% / {100 * refs['beaten'].mean():.1f}%"
    )
    echo("")
    echo("   By signature -- the race-losers separate from the self-aborters:")
    echo(
        f"   {'signature':<20}{'n':>9}{'shares block w/ fill':>23}"
        f"{'beaten in block':>18}{'lift vs ref':>13}"
    )
    base = float((refs["slot_swaps"] > 0).mean())
    rows = []
    sig_counts = fails["sig"].value_counts()
    for sig_name in sig_counts.head(18).index:
        sub = fails[fails["sig"] == sig_name]
        share = float((sub["slot_swaps"] > 0).mean())
        beaten = float(sub["beaten"].mean())
        rows.append(dict(sig=sig_name, n=len(sub), share=share, beaten=beaten, lift=share / base))
        echo(
            f"   {sig_name:<20}{len(sub):>9,}{100 * share:>22.1f}%{100 * beaten:>17.1f}%"
            f"{share / base:>13.2f}x"
        )
    echo("")
    echo("   A signature at or below 1.00x is not competing for our fills: it is a program")
    echo("   whose own precondition failed in a block where nothing traded here at all.")
    return {"base": base, "rows": rows}


# ============================================================== 3. behavioural fingerprint


def fingerprint(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """(instruction index, error code, compute decile, fee decile) as a machine proxy.

    The signer is not in the export. But a bot's compute budget and its fee schedule are
    written by its author and change only when the author redeploys, so the pair is a
    fingerprint in the same sense a packet's TTL and window size are. This section measures
    how much structure that fingerprint has; ``rpc`` measures whether it is real.
    """
    import numpy as np
    import pandas as pd

    echo("")
    echo("=" * 100)
    echo("3. THE FINGERPRINT -- identity reconstructed from exhaust, with no signer column")
    echo("=" * 100)

    # The cell is built in ``load_panel``: coarse, deliberately -- a fingerprint with 10,000
    # cells fits noise. log2 CU at half-bit resolution is ~1.4x wide, far tighter than the
    # spread between distinct bots and far looser than one bot's own jitter.
    fails = frame[(frame["failed"] == 1) & np.isfinite(frame["cu"]) & np.isfinite(frame["fee"])].copy()
    counts = fails["cell"].value_counts()
    tot = int(counts.sum())
    echo(f"   {len(counts):,} cells over {tot:,} failures")
    for k in (1, 5, 10, 25, 100):
        echo(f"     top {k:>3} cells: {100 * counts.head(k).sum() / tot:>5.1f}% of all failures")
    hhi = float(((counts / tot) ** 2).sum())
    echo(f"   Herfindahl {hhi:.4f}  (equivalent number of machines: {1 / hhi:,.0f})")

    # Persistence: a real machine runs for days. A noise cell appears once.
    fails["day"] = pd.to_datetime(fails["block_time"], unit="s").dt.floor("D")
    days = fails.groupby("cell")["day"].nunique()
    span = fails.groupby("cell")["block_time"].agg(lambda s: (s.max() - s.min()) / 86400)
    echo("")
    echo("   Top cells, and how long each one has been running:")
    echo(f"   {'cell':<42}{'n':>9}{'days seen':>11}{'span (d)':>10}{'pools':>7}{'top pool':>18}")
    top_cells = counts.head(15).index
    for c in top_cells:
        sub = fails[fails["cell"] == c]
        echo(
            f"   {c:<42}{len(sub):>9,}{int(days[c]):>11}{span[c]:>10.1f}"
            f"{sub['pool'].nunique():>7}{sub['label'].value_counts().index[0][:16]:>18}"
        )
    echo("")
    echo(
        f"   cells seen on >= 3 distinct days: {int((days >= 3).sum()):,} "
        f"({100 * float(fails['cell'].isin(days[days >= 3].index).mean()):.1f}% of failures)"
    )
    echo("   That share is the fraction of the failure stream produced by something with a")
    echo("   memory -- a deployed machine, not a one-off. It is the population the trigger")
    echo("   map would be about, IF the tape recorded who they were.")
    return {"hhi": hhi, "cells": len(counts), "top": counts.head(40).to_dict()}


# ================================================================= 4. RPC ground truth


def _b58decode(s: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for ch in s:
        num = num * 58 + alphabet.index(ch)
    out = num.to_bytes((num.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + out


def _helius_url() -> str:
    key = (Path.home() / ".helius-key").read_text().strip()
    return f"https://mainnet.helius-rpc.com/?api-key={key}"


def _get_transaction(url: str, sig: str, *, tries: int = 4) -> dict[str, Any] | None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [sig, {"maxSupportedTransactionVersion": 0, "encoding": "json"}],
        }
    ).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as fh:
                payload = json.load(fh)
            return payload.get("result")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            time.sleep(0.4 * (2**attempt) + random.random() * 0.3)
    return None


def summarise_tx(res: dict[str, Any]) -> dict[str, Any]:
    """Fee payer, the program at the failing index, the CU limit and the CU price bid."""
    msg = res["transaction"]["message"]
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in msg["accountKeys"]]
    loaded = (res.get("meta") or {}).get("loadedAddresses") or {}
    keys = keys + list(loaded.get("writable", [])) + list(loaded.get("readonly", []))
    instrs = msg.get("instructions", [])
    err = (res.get("meta") or {}).get("err")
    fail_idx = None
    if isinstance(err, dict) and "InstructionError" in err:
        fail_idx = int(err["InstructionError"][0])
    programs = [keys[i["programIdIndex"]] if i["programIdIndex"] < len(keys) else "?" for i in instrs]
    cu_limit = None
    cu_price = None
    for ins, prog in zip(instrs, programs, strict=False):
        if prog != COMPUTE_BUDGET:
            continue
        try:
            raw = _b58decode(str(ins.get("data", "")))
        except (ValueError, IndexError):
            continue
        if not raw:
            continue
        if raw[0] == 2 and len(raw) >= 5:
            cu_limit = int.from_bytes(raw[1:5], "little")
        elif raw[0] == 3 and len(raw) >= 9:
            cu_price = int.from_bytes(raw[1:9], "little")
    inner = (res.get("meta") or {}).get("innerInstructions") or []
    inner_progs: list[str] = []
    for grp in inner:
        for ins in grp.get("instructions", []):
            pid = ins.get("programIdIndex")
            if isinstance(pid, int) and pid < len(keys):
                inner_progs.append(keys[pid])
    return {
        "fee_payer": keys[0] if keys else None,
        "fail_idx": fail_idx,
        "fail_program": programs[fail_idx] if fail_idx is not None and fail_idx < len(programs) else None,
        "programs": programs,
        "inner_programs": sorted(set(inner_progs)),
        "n_instr": len(instrs),
        "n_accounts": len(keys),
        "cu_limit": cu_limit,
        "cu_price": cu_price,
        "cu_consumed": (res.get("meta") or {}).get("computeUnitsConsumed"),
        "fee": (res.get("meta") or {}).get("fee"),
        "signers": int(msg.get("header", {}).get("numRequiredSignatures", 1)),
    }


def rpc_sample(
    frame: Any, *, n: int = 2500, workers: int = 4, echo: Callable[[str], None] = print
) -> Path:
    """Read-only ``getTransaction`` over a stratified sample. Nothing signed, nothing sent.

    Stratified so the sample can answer two different questions with one budget: the top
    fingerprint cells (does a cell correspond to ONE fee payer?) and a uniform slice of the
    whole failure stream (what is the population's fee-payer concentration?), plus a slice
    of LANDED swaps so the fee comparison is apples to apples.
    """
    import numpy as np

    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "rpc_sample.jsonl"
    seen: set[str] = set()
    if out.exists():
        for line in out.read_text().splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                seen.add(json.loads(line)["signature"])
    echo(f"rpc: {len(seen):,} signatures already cached in {out}")

    fails = frame[frame["failed"] == 1]
    rng = np.random.default_rng(7)
    picks: list[tuple[str, str]] = []

    counts = fails["cell"].value_counts() if "cell" in fails.columns else None
    if counts is not None:
        for cell in counts.head(20).index:
            sub = fails[fails["cell"] == cell]
            take = min(40, len(sub))
            idx = rng.choice(len(sub), size=take, replace=False)
            picks += [(str(s), "cell") for s in sub["signature"].to_numpy()[idx]]
    uni = fails.sample(n=min(len(fails), max(400, n // 3)), random_state=5)
    picks += [(str(s), "uniform") for s in uni["signature"]]
    n_swaps = int((frame["kind"] == "swap").sum())
    lands = frame[frame["kind"] == "swap"].sample(n=min(600, n_swaps), random_state=6)
    picks += [(str(s), "landed") for s in lands["signature"]]

    todo = [(s, arm) for s, arm in dict(picks).items() if s not in seen][:n]
    echo(f"rpc: fetching {len(todo):,} transactions at {workers} concurrent (read-only)")
    url = _helius_url()
    done = 0

    def work(item: tuple[str, str]) -> str | None:
        sig, arm = item
        res = _get_transaction(url, sig)
        if not res:
            return None
        rec = summarise_tx(res)
        rec["signature"] = sig
        rec["arm"] = arm
        rec["slot"] = res.get("slot")
        return json.dumps(rec)

    with ThreadPoolExecutor(max_workers=workers) as pool, out.open("a") as fh:
        for line in pool.map(work, todo):
            done += 1
            if line:
                fh.write(line + "\n")
            if done % 250 == 0:
                fh.flush()
                echo(f"rpc: {done:,}/{len(todo):,}")
    echo(f"rpc: cache now {out}")
    return out


def rpc_report(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    path = DATA / "rpc_sample.jsonl"
    echo("")
    echo("=" * 100)
    echo("4. GROUND TRUTH -- a read-only getTransaction sample, and what it validates")
    echo("=" * 100)
    if not path.exists():
        echo("   no sample cached; run `failure_stream.py rpc` (network) to build one")
        return {}
    recs = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    sample = pd.DataFrame(recs)
    echo(f"   {len(sample):,} transactions fetched ({sample['arm'].value_counts().to_dict()})")

    join = frame.set_index("signature")
    cols = ["pool", "label", "sig", "cell", "kind", "fee", "cu", "block_time", "beaten", "pre5"]
    cols = [c for c in cols if c in join.columns]
    sample = sample.join(
        join[cols].rename(columns={"fee": "tape_fee", "cu": "tape_cu"}), on="signature"
    )
    bad = int((sample["fee"] != sample["tape_fee"]).sum())
    echo(f"   fee agreement tape vs RPC: {len(sample) - bad:,}/{len(sample):,} joined rows exact")

    # The join is one row per (signature, pool) and a transaction that touched three of our
    # pools joins three times. That is a fact worth reporting on its own -- it is the arb
    # leg count -- but it must NOT be left in the concentration statistics, where it would
    # silently overweight exactly the multi-pool arbitrageurs the roster is about.
    touched = sample.groupby("signature").size()
    multi = float((touched > 1).mean())
    echo(
        f"   {100 * multi:.1f}% of sampled transactions touched MORE THAN ONE of our pools "
        f"(max {int(touched.max())}) -- multi-leg arbitrage, and the reason the join expands "
        f"{len(touched):,} transactions into {len(sample):,} rows"
    )
    sample = sample.assign(n_our_pools=sample["signature"].map(touched)).drop_duplicates("signature")
    echo(f"   deduplicated to {len(sample):,} transactions for every statistic below")

    failed = sample[sample["kind"] == "failed"]
    echo("")
    echo("   WHICH PROGRAM SAID NO (program at the failing instruction index):")
    prog = failed["fail_program"].value_counts()
    for p, c in prog.head(12).items():
        echo(f"     {100 * c / len(failed):>6.1f}%  {KNOWN_PROGRAMS.get(p, ''):<24} {p}")
    amm = {"pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA", "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"}
    in_amm = float(failed["fail_program"].isin(amm).mean())
    echo(f"   failed INSIDE an AMM program: {100 * in_amm:.1f}%  -- the rest is third-party code")

    echo("")
    echo("   FEE-PAYER CONCENTRATION (the statistic the brief wanted, on the arm that can carry it):")
    for arm in ("uniform", "cell"):
        sub = failed[failed["arm"] == arm]
        if len(sub) < 50:
            continue
        vc = sub["fee_payer"].value_counts()
        echo(
            f"     {arm:<9} {len(sub):>5,} failures, {len(vc):>4} distinct payers, "
            f"top-10 = {100 * vc.head(10).sum() / len(sub):.1f}%, "
            f"HHI {float(((vc / len(sub)) ** 2).sum()):.3f}"
        )

    echo("")
    echo("   DOES THE FINGERPRINT ACTUALLY NAME A MACHINE? (purity of the top cells)")
    echo(f"   {'cell':<42}{'sampled':>9}{'payers':>8}{'top payer share':>17}")
    pur = []
    for cell, sub in failed.groupby("cell"):
        if len(sub) < 20:
            continue
        vc = sub["fee_payer"].value_counts()
        pur.append(float(vc.iloc[0] / len(sub)))
        echo(f"   {cell!s:<42}{len(sub):>9}{len(vc):>8}{100 * vc.iloc[0] / len(sub):>16.1f}%")
    if pur:
        uni = failed[failed["arm"] == "uniform"]
        base = float(uni["fee_payer"].value_counts().iloc[0] / len(uni)) if len(uni) else float("nan")
        echo(
            f"   median top-payer share inside a cell: {100 * float(np.median(pur)):.1f}%  "
            f"vs {100 * base:.1f}% for the single most common payer in an unstratified sample"
        )

    echo("")
    echo("   THE ROSTER -- every program that failed >= 20 times in the sample, and the")
    echo("   behavioural profile the exhaust gives us for it. This is the trigger map as far")
    echo("   as data that exists supports one: no signer column means no per-machine event")
    echo("   history, but the PROGRAM is identified and its habits are measured.")
    echo("")
    echo(
        f"   {'program':<46}{'n':>5}{'payers':>7}{'top code':>11}{'bid p50':>10}"
        f"{'CU use':>8}{'beaten':>8}{'pre5 bps':>10}"
    )
    roster = []
    for prog, sub in failed.groupby("fail_program"):
        if len(sub) < 20:
            continue
        vc = sub["fee_payer"].value_counts()
        code = sub["sig"].value_counts()
        util = (sub["cu_consumed"].astype(float) / sub["cu_limit"].astype(float)).median()
        rec = dict(
            program=str(prog),
            name=KNOWN_PROGRAMS.get(str(prog), ""),
            n=len(sub),
            payers=len(vc),
            top_code=str(code.index[0]) if len(code) else "",
            top_code_share=float(code.iloc[0] / len(sub)) if len(code) else float("nan"),
            bid=float(sub["cu_price"].median()) if sub["cu_price"].notna().any() else float("nan"),
            util=float(util) if util == util else float("nan"),
            beaten=float(sub["beaten"].mean()) if "beaten" in sub else float("nan"),
            pre5=float(sub["pre5"].mean() * 1e4) if "pre5" in sub else float("nan"),
            top_payer=str(vc.index[0]),
            top_payer_share=float(vc.iloc[0] / len(sub)),
        )
        roster.append(rec)
    for r in sorted(roster, key=lambda x: -x["n"]):
        tag = (r["name"] or r["program"])[:44]
        echo(
            f"   {tag:<46}{r['n']:>5}{r['payers']:>7}{r['top_code']:>11}{r['bid']:>10,.0f}"
            f"{100 * r['util']:>7.0f}%{100 * r['beaten']:>7.0f}%{r['pre5']:>10.0f}"
        )
    echo("")
    echo("   ... and the wallet behind each, where the program has essentially one operator:")
    for r in sorted(roster, key=lambda x: -x["n"]):
        if r["top_payer_share"] < 0.5:
            continue
        tag = (r["name"] or r["program"])[:44]
        echo(f"     {tag:<46}{r['top_payer']:<46}{100 * r['top_payer_share']:>5.0f}% of its failures")
    echo("")
    echo("   `beaten` is the share whose own block already contained a landed fill ahead of")
    echo("   them; `pre5` is the average |price move| in the 5 s before they fired. A program")
    echo("   high on both is racing us for real fills. One low on both fires on a clock.")

    echo("")
    echo("   THE BID, exactly (ComputeBudget SetComputeUnitPrice, micro-lamports per CU):")
    echo(f"   {'arm':<10}{'n':>7}{'p25':>10}{'p50':>10}{'p75':>10}{'p95':>10}{'has CU price':>14}")
    for arm, sub in sample.groupby("kind"):
        px = sub["cu_price"].dropna()
        if len(sub) == 0:
            continue
        q = px.quantile([0.25, 0.5, 0.75, 0.95]) if len(px) else pd.Series([np.nan] * 4)
        echo(
            f"   {arm!s:<10}{len(sub):>7,}{q.iloc[0]:>10,.0f}{q.iloc[1]:>10,.0f}"
            f"{q.iloc[2]:>10,.0f}{q.iloc[3]:>10,.0f}{100 * len(px) / len(sub):>13.0f}%"
        )
    echo("")
    echo("   CU LIMIT REQUESTED vs CONSUMED -- a bot that always requests the same limit is")
    echo("   the same bot; a bot that consumes far less than it asks for is paying for air:")
    for arm, sub in sample.groupby("kind"):
        lim = sub["cu_limit"].dropna()
        if not len(lim):
            continue
        used = sub.loc[lim.index, "cu_consumed"].astype(float)
        echo(
            f"     {arm!s:<10} median limit {lim.median():>10,.0f}  median consumed "
            f"{used.median():>10,.0f}  median utilisation {100 * float((used / lim).median()):>5.1f}%"
        )
    return {
        "n": len(sample),
        "in_amm": in_amm,
        "purity": float(np.median(pur)) if pur else float("nan"),
    }


# ================================================================== 5. surges as a signal


def minute_panel(frame: Any, *, echo: Callable[[str], None] = print) -> Any:
    """pool x minute: failures by class, landed swaps, flow, price, depth."""
    import numpy as np
    import pandas as pd

    f = frame.copy()
    f["is_race"] = ((f["failed"] == 1) & f["beaten"]).astype(int)
    f["is_alone"] = ((f["failed"] == 1) & ~f["beaten"]).astype(int)
    g = f.groupby(["pool", "minute"])
    panel = g.agg(
        n_fail=("failed", "sum"),
        n_race=("is_race", "sum"),
        n_alone=("is_alone", "sum"),
        n_swap=("kind", lambda s: int((s == "swap").sum())),
        n_ref=("kind", lambda s: int((s == "reference").sum())),
        fee_med=("fee", "median"),
        logp=("logp", "last"),
        depth=("quote_pre", "last"),
        label=("label", "first"),
    ).reset_index()

    out = []
    for pool, grp in panel.groupby("pool", sort=False):
        grp = grp.sort_values("minute")
        # A missing minute is a minute with no transactions at all: zero flow, price
        # unchanged. Dropping it would silently splice across gaps and make every
        # forward return look like it happened in one minute.
        idx = np.arange(grp["minute"].min(), grp["minute"].max() + BIN_S, BIN_S)
        grp = grp.set_index("minute").reindex(idx)
        grp["pool"] = pool
        grp["label"] = grp["label"].ffill().bfill()
        for c in ("n_fail", "n_race", "n_alone", "n_swap", "n_ref"):
            grp[c] = grp[c].fillna(0)
        grp["logp"] = grp["logp"].ffill()
        grp["depth"] = grp["depth"].ffill()
        grp["ret"] = grp["logp"].diff()
        for h in FWD_MIN:
            grp[f"fwd_abs{h}"] = (grp["logp"].shift(-h) - grp["logp"]).abs()
            grp[f"fwd_ret{h}"] = grp["logp"].shift(-h) - grp["logp"]
            grp[f"fwd_swaps{h}"] = grp["n_swap"].shift(-1).rolling(h, min_periods=1).sum().shift(-(h - 1))
        out.append(grp.reset_index().rename(columns={"index": "minute"}))
    panel = pd.concat(out, ignore_index=True)
    panel["hour"] = (panel["minute"] // 3600) * 3600
    echo(f"   minute panel: {len(panel):,} pool-minutes over {panel['pool'].nunique()} pools")
    return panel


def _standardise(series: Any, by: Any) -> Any:
    np = _np()
    grp = series.groupby(by)
    mu = grp.transform("mean")
    sd = grp.transform("std").replace(0, np.nan)
    return ((series - mu) / sd).fillna(0.0)


def surge(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Does a burst of FAILED attempts predict what the successful stream does not?

    Specification, fixed before any coefficient was looked at:

        y_{p,t+h} = a_p + b * z_fail_{p,t} + c * z_swap_{p,t} + d * |ret_{p,t}| + e * log depth

    ``b`` is the whole question. ``z_swap`` is in the model because the honest null is that
    failures are just a noisy copy of activity: if bursts of failure predict volatility only
    because busy minutes are busy, ``b`` collapses once the successful count is present.
    """
    import numpy as np
    import pandas as pd
    import statsmodels.api as sm

    echo("")
    echo("=" * 100)
    echo("5. FAILURE SURGES AS A SIGNAL -- conditional on the successful stream")
    echo("=" * 100)

    panel = minute_panel(frame, echo=echo)
    panel = panel[np.isfinite(panel["logp"])].copy()
    panel["z_fail"] = _standardise(panel["n_fail"], panel["pool"])
    panel["z_race"] = _standardise(panel["n_race"], panel["pool"])
    panel["z_alone"] = _standardise(panel["n_alone"], panel["pool"])
    panel["z_swap"] = _standardise(panel["n_swap"], panel["pool"])
    panel["abs_ret"] = panel["ret"].abs().fillna(0)
    panel["log_depth"] = np.log(panel["depth"].clip(lower=1))

    exposures = [("z_fail", "all failures"), ("z_race", "race losses"), ("z_alone", "solo aborts")]
    outcomes = [(f"fwd_abs{h}", f"|ret| +{h}m") for h in FWD_MIN]
    outcomes += [(f"fwd_ret{h}", f"ret +{h}m") for h in FWD_MIN]
    outcomes += [("fwd_swaps5", "landed swaps +5m")]

    dummies = pd.get_dummies(panel["pool"], prefix="p", drop_first=True).astype(float)
    results: list[dict[str, Any]] = []
    echo("")
    echo(
        f"   {'exposure':<14}{'outcome':<20}{'n':>9}{'beta':>11}{'t (clustered)':>15}"
        f"{'p rotation':>12}{'BY':>5}"
    )
    rng = np.random.default_rng(3)
    for xname, xlabel in exposures:
        for yname, ylabel in outcomes:
            ok = np.isfinite(panel[yname]) & np.isfinite(panel[xname])
            for c in ("z_swap", "abs_ret", "log_depth"):
                ok &= np.isfinite(panel[c])
            sub = panel[ok]
            if len(sub) < 500:
                continue
            X = pd.concat(
                [
                    sub[[xname, "z_swap", "abs_ret", "log_depth"]].reset_index(drop=True),
                    dummies.loc[sub.index].reset_index(drop=True),
                ],
                axis=1,
            )
            X = sm.add_constant(X, has_constant="add")
            y = sub[yname].reset_index(drop=True).astype(float)
            fit = sm.OLS(y, X.astype(float)).fit(
                cov_type="cluster", cov_kwds={"groups": sub["pool"].reset_index(drop=True)}
            )
            beta = float(fit.params[xname])
            tstat = float(fit.tvalues[xname])

            # ROTATION NULL. The exposure series is circularly shifted inside each pool by
            # at least an hour. Autocorrelation of both series survives; only the alignment
            # between them is destroyed. An i.i.d. shuffle would keep neither and has
            # manufactured effects in this repo twice.
            #
            # Refitting the whole design 500 times is wasteful and was the reason an earlier
            # version of this ran for an hour. Frisch-Waugh-Lovell gives the identical
            # coefficient from a single QR of the controls: residualise y once, and each
            # rotation costs one projection of the rotated exposure. Same numbers, ~100x.
            ctrl_cols = [c for c in X.columns if c != xname]
            Q, _ = np.linalg.qr(X[ctrl_cols].to_numpy(dtype=float))
            yv = y.to_numpy(dtype=float)
            y_res = yv - Q @ (Q.T @ yv)
            dof = len(yv) - X.shape[1]

            def _t_of(xvec: Any, y_res: Any = y_res, Q: Any = Q, dof: int = dof) -> float:
                x_res = xvec - Q @ (Q.T @ xvec)
                denom = float(x_res @ x_res)
                if denom <= 0:
                    return 0.0
                b = float(x_res @ y_res) / denom
                resid = y_res - b * x_res
                s2 = float(resid @ resid) / max(dof, 1)
                se = math.sqrt(s2 / denom)
                return b / se if se > 0 else 0.0

            t_ols = _t_of(sub[xname].to_numpy(dtype=float))
            groups = [g.index for _p, g in sub.reset_index(drop=True).groupby("pool", sort=False)]
            xraw = sub[xname].to_numpy(dtype=float)
            null_t = np.empty(ROTATIONS)
            for r in range(ROTATIONS):
                xn = xraw.copy()
                for gidx in groups:
                    seg = xn[gidx]
                    if len(seg) <= MIN_ROTATION_MIN + 1:
                        continue
                    k = int(rng.integers(MIN_ROTATION_MIN, len(seg)))
                    xn[gidx] = np.roll(seg, k)
                null_t[r] = abs(_t_of(xn))
            p_rot = float((null_t >= abs(t_ols)).mean())
            results.append(
                dict(
                    exposure=xlabel,
                    outcome=ylabel,
                    n=len(sub),
                    beta=beta,
                    t=tstat,
                    t_ols=t_ols,
                    p=p_rot,
                )
            )
    keep = by_fdr([r["p"] for r in results], FDR_Q)
    for r, k in zip(results, keep, strict=False):
        r["by"] = bool(k)
        echo(
            f"   {r['exposure']:<14}{r['outcome']:<20}{r['n']:>9,}{r['beta']:>11.5f}"
            f"{r['t']:>15.2f}{fmt_p(r['p']):>12}{'yes' if k else '.':>5}"
        )
    echo("")
    echo(f"   {ROTATIONS} rotations per row; the clustered t is shown for reference only --")
    echo(f"   {panel['pool'].nunique()} clusters is far below the ~30 that cluster-robust")
    echo("   asymptotics need, so the rotation p is the inference and the t is decoration.")
    return {"rows": results}


# ==================================================================== 6. our own execution


def practical(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Is the failure stream usable BEFORE we send? Two separable questions.

    (a) Is congestion PERSISTENT enough that the last minute's failures forecast the next
        minute's? A signal that arrives only after we needed it is worthless.
    (b) Would paying more have helped? If failures bid MORE than the transactions that
        landed alongside them, then the failure is not a fee-market outcome and raising our
        fee buys nothing -- which is the opposite of the usual advice.
    """
    import numpy as np
    import pandas as pd
    from sklearn.metrics import roc_auc_score

    echo("")
    echo("=" * 100)
    echo("6. PRACTICAL -- does it help our own sends?")
    echo("=" * 100)

    panel = minute_panel(frame, echo=echo)
    panel = panel.sort_values(["pool", "minute"])
    out: dict[str, Any] = {}

    echo("")
    echo("   (a) PERSISTENCE. Predicting the next minute's failure count from this one.")
    echo(f"   {'pool':<20}{'minutes':>9}{'rho(1)':>9}{'rho(5)':>9}{'AUC top-decile':>16}")
    aucs = []
    for _pool, g in panel.groupby("pool"):
        if len(g) < 500:
            continue
        x = g["n_fail"].astype(float).to_numpy()
        r1 = float(pd.Series(x).autocorr(1))
        r5 = float(pd.Series(x).autocorr(5))
        thr = np.quantile(x, 0.9)
        y = (np.roll(x, -1) >= max(thr, 1))[:-1]
        score = x[:-1]
        auc = float(roc_auc_score(y, score)) if 0 < y.sum() < len(y) else float("nan")
        aucs.append(auc)
        echo(f"   {str(g['label'].iloc[0])[:18]:<20}{len(g):>9,}{r1:>9.3f}{r5:>9.3f}{auc:>16.3f}")
    out["auc"] = float(np.nanmean(aucs)) if aucs else float("nan")
    echo(f"   mean AUC {out['auc']:.3f} -- 0.50 is a coin flip and would mean the burst is")
    echo("   over by the time we can read it.")

    echo("")
    echo("   (b) WOULD PAYING MORE HAVE HELPED? Fee paid, failures vs landed swaps, matched")
    echo("       inside the same pool-minute (so the comparison never crosses a fee regime).")
    from scipy import stats

    f = frame[np.isfinite(frame["fee"])]
    fail_fee = f[f["failed"] == 1].groupby(["pool", "minute"])["fee"].median()
    land_fee = f[f["kind"] == "swap"].groupby(["pool", "minute"])["fee"].median()
    both = pd.concat([fail_fee.rename("fail"), land_fee.rename("land")], axis=1).dropna()
    both = both.reset_index()
    echo(f"       {len(both):,} pool-minutes contain both a failure and a landed swap")
    echo(
        f"       {'pool':<20}{'minutes':>9}{'med fail':>11}{'med land':>11}"
        f"{'ratio':>8}{'out-bid %':>11}{'p(sign)':>10}"
    )
    labels = frame.drop_duplicates("pool").set_index("pool")["label"]
    rows = []
    for pool, g in both.groupby("pool"):
        wins = int((g["fail"] > g["land"]).sum())
        p = float(stats.binomtest(wins, len(g), 0.5).pvalue) if len(g) else float("nan")
        rows.append(
            (str(labels.get(pool, pool)), len(g), g["fail"].median(), g["land"].median(), wins / len(g), p)
        )
    for name, n, mf, ml, sh, p in sorted(rows, key=lambda r: -r[1]):
        echo(
            f"       {name[:18]:<20}{n:>9,}{mf:>11,.0f}{ml:>11,.0f}"
            f"{ml / max(mf, 1):>8.1f}x{100 * sh:>10.1f}%{fmt_p(p):>10}"
        )
    share = float((both["fail"] > both["land"]).mean())
    echo(f"       pooled: failures out-bid the landed swap in {100 * share:.1f}% of those minutes")
    echo("       (`landed` includes our own sends; without a signer column they cannot be")
    echo("        excluded, and at our volume they are a rounding error in this population.)")
    out["fee_outbid_share"] = share
    out["fee_by_pool"] = rows

    echo("")
    echo("   (c) THE LANDING ODDS OF THE MINUTE. Share of pool-touching swap attempts that")
    echo("       landed, and whether the previous minute forecasts it.")
    panel["land_rate"] = panel["n_swap"] / (panel["n_swap"] + panel["n_fail"]).replace(0, np.nan)
    lr = panel.dropna(subset=["land_rate"])
    rho = float(
        pd.Series(lr.groupby("pool")["land_rate"].apply(lambda s: s.autocorr(1))).mean()
    )
    tx_weighted = float(panel["n_swap"].sum() / (panel["n_swap"].sum() + panel["n_fail"].sum()))
    echo(
        f"       landing rate {100 * lr['land_rate'].mean():.1f}% averaged over minutes but "
        f"{100 * tx_weighted:.1f}% weighted by transaction --"
    )
    echo("       the gap IS the phenomenon: the failures are concentrated in a few busy minutes.")
    echo(f"       lag-1 autocorrelation of the minute's landing rate: {rho:.3f}")
    out["land_rate"] = float(lr["land_rate"].mean())
    out["land_rho"] = rho
    return out


# ======================================================================== 7. the holdout


def load_tape_attempts(echo: Callable[[str], None] = print) -> Any:
    import pandas as pd

    rows: list[dict[str, Any]] = []
    for path in sorted(TAPE.glob("*.jsonl")):
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # the recorder may be mid-append
                kind = r.get("kind")
                if kind not in ("attempt", "swap", "reference"):
                    continue
                chain = r.get("chain") or {}
                rows.append(
                    {
                        "kind": kind,
                        "pool": r.get("pool"),
                        "label": r.get("label"),
                        "block_time": chain.get("block_time"),
                        "slot": chain.get("slot"),
                        "error": r.get("error") or "",
                        "signature": chain.get("signature"),
                    }
                )
    frame = pd.DataFrame(rows).dropna(subset=["block_time"])
    frame = frame.drop_duplicates(subset=["signature", "pool"])
    echo(f"   held-out tape: {len(frame):,} rows, {int((frame['kind'] == 'attempt').sum()):,} attempts")
    return frame


TAPE_ERR = re.compile(r"\[(\d+), \{'Custom': (\d+)\}\]")


def holdout(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """The live tape, Aug 13-15 -- days the bulk export does not cover.

    The tape has no fee and no compute, so only the count-based claims can be replicated.
    That is the point: a claim that needs a column the live collector does not write is a
    claim we could never act on anyway.
    """
    import pandas as pd

    echo("")
    echo("=" * 100)
    echo("7. HELD-OUT WINDOW -- the live cluster tape, after the bulk export ends")
    echo("=" * 100)
    tape = load_tape_attempts(echo=echo)
    if tape.empty:
        return {}
    tape["t0"] = pd.to_datetime(tape["block_time"], unit="s")
    echo(f"   window {tape['t0'].min()} .. {tape['t0'].max()} UTC, {tape['pool'].nunique()} pools")
    bulk_end = int(frame["block_time"].max())
    fresh = tape[tape["block_time"] > bulk_end]
    echo(f"   strictly after the bulk export's last second: {len(fresh):,} rows")

    sigs = []
    for e in fresh["error"]:
        m = TAPE_ERR.search(str(e))
        sigs.append(f"i{m.group(1)}:0x{int(m.group(2)):x}" if m else "")
    fresh = fresh.assign(sig=sigs)
    att = fresh[fresh["kind"] == "attempt"]
    echo("")
    echo("   Do the same signatures dominate on days the training window never saw?")
    train = frame[frame["failed"] == 1]["sig"].value_counts(normalize=True)
    test = att["sig"].value_counts(normalize=True)
    common = [s for s in test.head(12).index if s]
    echo(f"   {'signature':<16}{'held-out share':>16}{'training share':>16}{'rank in training':>18}")
    train_rank = {s: i + 1 for i, s in enumerate(train.index)}
    for s in common:
        echo(
            f"   {s:<16}{100 * test[s]:>15.1f}%{100 * train.get(s, 0.0):>15.1f}%"
            f"{train_rank.get(s, 0) or '-':>18}"
        )
    overlap = float(sum(min(test.get(s, 0), train.get(s, 0)) for s in set(test.index) | set(train.index)))
    echo(f"   total variation overlap between the two error-code distributions: {100 * overlap:.1f}%")

    # count-based surge replication
    fresh["minute"] = (fresh["block_time"] // BIN_S) * BIN_S
    g = fresh.groupby(["pool", "minute"]).agg(
        n_fail=("kind", lambda s: int((s == "attempt").sum())),
        n_swap=("kind", lambda s: int((s == "swap").sum())),
    ).reset_index()
    rho = float(pd.Series(g.groupby("pool")["n_fail"].apply(lambda s: s.autocorr(1))).mean())
    echo(f"   held-out persistence of the failure count, lag-1 autocorr: {rho:.3f}")
    return {"overlap": overlap, "rho": rho}


# ============================================== 8. the machine-conditioned test (§7.4)
#
# PRE-REGISTERED IN RESULT_failure_stream.md §7.4 BEFORE BEING RUN. The specification below
# is a transcription of that section, and nothing in it was chosen after seeing a result.
#
# WHY IT EXISTS. §5 asked whether an AGGREGATE failure count at MINUTE resolution predicts
# forward PRICE, and found one survivor of 21 with the wrong sign. The operator's objection
# to reading that as "no information" is correct: these strategies visibly make money for the
# people running them, so a null means the wrong things were compared. Three specific
# mis-specifications, each fixed here:
#
#   unit         minute -> SLOT. A minute averages ~150 slots and a race is decided inside
#                one. `tx_index` gives position within the block and almost nobody has it.
#   exposure     pooled count -> ONE NAMED MACHINE. §3.1 validated fingerprint cells against
#                true fee payers; several are a single wallet at 100%. A rival conditions on
#                a specific trigger, not on "failures went up", and pooling a dozen unrelated
#                machines dilutes any one of them towards zero by construction.
#   outcome      forward return -> THE FILL. Their outcome is whether they got the trade at
#                a price, not whether the price later moved.
#
# REGISTERED PREDICTION (written before the run): this fires for the machines with high
# `beaten` and high `pre5` -- the racers -- and not for the self-aborters, because only the
# racers are conditioning on the same state we would be.

FILL_WINDOW_SLOTS: Final[int] = 5  # ~2 s. Fixed in advance; not tuned.

# THE DISCRIMINATING CONTROL, and the reason this test is not just an activity detector.
# A machine only fires in a slot where something happened, and slots where something happened
# are slots where a fill is more likely. Without `here_swap`/`here_fail` the coefficient would
# be measuring "this slot is busy" -- true, mechanical, and worthless. With them, the question
# becomes the one worth asking: GIVEN a slot this busy, does THIS machine's presence still
# move the odds? The first run of this section omitted them and every large effect it found is
# reported alongside the controlled version, because the difference between the two numbers is
# the entire finding.
CONTROLS: Final[list[str]] = ["const", "prior_swaps", "prior_move", "log_depth", "here_swap", "here_fail"]
MIN_ROTATION_SLOTS: Final[int] = 1000
MACHINE_PURITY_MIN: Final[float] = 0.50
MACHINE_SAMPLE_MIN: Final[int] = 20
N_MACHINES: Final[int] = 10
MACHINE_ROTATIONS_FINE: Final[int] = 6000


def named_machines(frame: Any, *, echo: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """The cells the RPC sample resolved to (near-)one fee payer. Selection is on EXPOSURE
    purity only -- never on any outcome -- so it cannot bias the tests that follow."""
    import pandas as pd

    path = DATA / "rpc_sample.jsonl"
    if not path.exists():
        raise SystemExit("run `failure_stream.py rpc --n 2500` first: this needs the ground truth")
    recs = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    sample = pd.DataFrame(recs)
    cols = [c for c in ("cell", "kind", "sig", "beaten", "pre5") if c in frame.columns]
    join = frame.set_index("signature")[cols]
    sample = sample.join(join, on="signature").drop_duplicates("signature")
    failed = sample[sample["kind"] == "failed"]
    out = []
    for cell, sub in failed.groupby("cell"):
        if len(sub) < MACHINE_SAMPLE_MIN or not cell:
            continue
        vc = sub["fee_payer"].value_counts()
        purity = float(vc.iloc[0] / len(sub))
        if purity < MACHINE_PURITY_MIN:
            continue
        prog = sub["fail_program"].value_counts()
        out.append(
            dict(
                cell=str(cell),
                payer=str(vc.index[0]),
                purity=purity,
                sampled=len(sub),
                program=str(prog.index[0]) if len(prog) else "",
                beaten=float(sub["beaten"].mean()) if "beaten" in sub else float("nan"),
            )
        )
    out.sort(key=lambda r: (-r["purity"], -r["sampled"]))
    return out[:N_MACHINES]


def slot_panel(frame: Any, machines: list[dict[str, Any]], *, echo: Callable[[str], None] = print) -> Any:
    """(pool, slot) -> machine firings, the fill outcomes, and the controls.

    The forward window is ``FILL_WINDOW_SLOTS`` **slot numbers**, not rows: a pool's slots are
    sparse and irregular, so "the next 5 rows" would silently mean five minutes on a quiet
    pool and 30 ms on a busy one. ``searchsorted`` on the real slot numbers keeps the window a
    fixed amount of chain time everywhere.
    """
    import numpy as np
    import pandas as pd

    # Only the columns this needs. `frame.copy()` duplicated a 2.5 GB panel and took the
    # process to 7.0 GB of RSS, over the machine ceiling, for no reason: the slot panel uses
    # ten columns of thirty.
    need = ["pool", "slot", "tx_index", "kind", "failed", "cell", "logp", "logp_pre",
            "quote_pre", "fee"]
    f = frame[need].copy()
    cells = {m["cell"]: i for i, m in enumerate(machines)}
    f["m_idx"] = f["cell"].map(cells)

    # The taker's own impact: how far the fill moved the pool, |log(post/pre)| across the
    # swap. On a constant-product pool this is mechanically positive and grows with size, so
    # it is a COST measure (size, and the fee inside it) rather than an adverse-selection
    # measure. Labelled that way wherever it is reported.
    swaps = f["kind"] == "swap"
    f["swap_impact"] = np.where(swaps, np.abs(f["logp"] - f["logp_pre"]), np.nan)

    rows = []
    for pool, g in f.groupby("pool", sort=False):
        g = g.sort_values(["slot", "tx_index"])
        agg = g.groupby("slot").agg(
            n_swap=("kind", lambda s: int((s == "swap").sum())),
            n_fail=("failed", "sum"),
            logp=("logp", "last"),
            logp_pre=("logp_pre", "first"),
            depth=("quote_pre", "last"),
            fee_swap=("fee", "max"),
            impact=("swap_impact", "mean"),
        )
        swap_fee = g[g["kind"] == "swap"].groupby("slot")["fee"].median()
        agg["fee_swap"] = swap_fee.reindex(agg.index)
        agg["here_swap"] = agg["n_swap"]
        agg["here_fail"] = agg["n_fail"]
        for cell, i in cells.items():
            fired = g[g["cell"] == cell].groupby("slot").size()
            agg[f"m{i}"] = fired.reindex(agg.index).fillna(0).gt(0).astype(float)
        agg = agg.reset_index()
        agg["pool"] = pool
        rows.append(agg)
    panel = pd.concat(rows, ignore_index=True)

    # forward window, per pool, on real slot numbers
    outs = []
    for _pool, g in panel.groupby("pool", sort=False):
        g = g.sort_values("slot").reset_index(drop=True)
        s = g["slot"].to_numpy()
        j = np.searchsorted(s, s + FILL_WINDOW_SLOTS, side="right")
        i1 = np.minimum(np.arange(len(s)) + 1, len(s))
        cum_sw = np.r_[0, np.cumsum(g["n_swap"].to_numpy())]
        g["fwd_swaps"] = cum_sw[j] - cum_sw[i1]
        g["fill"] = (g["fwd_swaps"] > 0).astype(float)
        fee = g["fee_swap"].to_numpy()
        imp = g["impact"].to_numpy()
        fwd_fee = np.full(len(s), np.nan)
        fwd_imp = np.full(len(s), np.nan)
        for k in range(len(s)):
            lo, hi = i1[k], j[k]
            if hi > lo:
                w = fee[lo:hi]
                w = w[np.isfinite(w)]
                if w.size:
                    fwd_fee[k] = float(np.median(w))
                v = imp[lo:hi]
                v = v[np.isfinite(v)]
                if v.size:
                    fwd_imp[k] = float(np.mean(v))
        g["fwd_fee"] = fwd_fee
        g["fwd_impact"] = fwd_imp
        # controls: the pool's own recent state, 20 slots back
        jb = np.searchsorted(s, s - 20, side="left")
        cum_all = np.r_[0, np.cumsum(g["n_swap"].to_numpy())]
        g["prior_swaps"] = cum_all[np.arange(len(s))] - cum_all[jb]
        lp = g["logp"].ffill().to_numpy()
        g["prior_move"] = np.abs(lp - lp[np.maximum(jb - 1, 0)])
        g["log_depth"] = np.log(np.clip(g["depth"].ffill().to_numpy(), 1, None))
        outs.append(g)
    panel = pd.concat(outs, ignore_index=True)
    echo(f"   slot panel: {len(panel):,} pool-slots over {panel['pool'].nunique()} pools")
    return panel


def machines_test(frame: Any, *, echo: Callable[[str], None] = print) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    echo("")
    echo("=" * 100)
    echo("8. THE MACHINE-CONDITIONED TEST -- pre-registered in RESULT §7.4, slot resolution")
    echo("=" * 100)

    machines = named_machines(frame, echo=echo)
    echo(f"   {len(machines)} machines, selected on EXPOSURE purity alone (never on an outcome):")
    echo(f"   {'#':<3}{'cell':<40}{'purity':>8}{'n':>6}{'beaten':>8}  wallet")
    for i, m in enumerate(machines):
        echo(
            f"   {i:<3}{m['cell'][:38]:<40}{100 * m['purity']:>7.0f}%{m['sampled']:>6}"
            f"{100 * m['beaten']:>7.0f}%  {m['payer'][:44]}"
        )

    panel = slot_panel(frame, machines, echo=echo)
    outcomes = [
        ("fill", "p(fill within 5 slots)"),
        ("fwd_fee", "fee that cleared (lamports)"),
        ("fwd_impact", "taker impact of the fill"),
    ]
    dummies = pd.get_dummies(panel["pool"], prefix="p", drop_first=True).astype(float)
    rng = np.random.default_rng(19)
    results: list[dict[str, Any]] = []
    for i, m in enumerate(machines):
        x = f"m{i}"
        if panel[x].sum() < 200:
            continue
        for yname, ylabel in outcomes:
            ok = np.isfinite(panel[yname]) & np.isfinite(panel["prior_move"])
            for c in CONTROLS:
                if c != "const":
                    ok &= np.isfinite(panel[c])
            sub = panel[ok]
            if len(sub) < 1000 or sub[x].sum() < 100:
                continue
            X = pd.concat(
                [
                    sub[[c for c in CONTROLS if c != "const"] + [x]].reset_index(drop=True),
                    dummies.loc[sub.index].reset_index(drop=True),
                ],
                axis=1,
            )

            X.insert(0, "const", 1.0)
            y = sub[yname].to_numpy(dtype=float)
            ctrl = [c for c in X.columns if c != x]
            Q, _ = np.linalg.qr(X[ctrl].to_numpy(dtype=float))
            y_res = y - Q @ (Q.T @ y)
            dof = len(y) - X.shape[1]

            def _t(xv: Any, y_res: Any = y_res, Q: Any = Q, dof: int = dof) -> tuple[float, float]:
                xr = xv - Q @ (Q.T @ xv)
                den = float(xr @ xr)
                if den <= 0:
                    return 0.0, 0.0
                b = float(xr @ y_res) / den
                r = y_res - b * xr
                se = math.sqrt((float(r @ r) / max(dof, 1)) / den)
                return b, (b / se if se > 0 else 0.0)

            xraw = sub[x].to_numpy(dtype=float)
            beta, tstat = _t(xraw)
            groups = [g.index.to_numpy() for _p, g in sub.reset_index(drop=True).groupby("pool", sort=False)]

            def _rotate(n_draws: int, xraw: Any = xraw, groups: Any = groups, _t: Any = _t) -> Any:
                out = np.empty(n_draws)
                for r in range(n_draws):
                    xn = xraw.copy()
                    for gi in groups:
                        if len(gi) <= MIN_ROTATION_SLOTS + 1:
                            continue
                        xn[gi] = np.roll(xn[gi], int(rng.integers(MIN_ROTATION_SLOTS, len(gi))))
                    out[r] = abs(_t(xn)[1])
                return out

            # MONTE CARLO RESOLUTION, and this had to be fixed before any of it could be read.
            # BY with 30 hypotheses demands p <= 0.00083 at rank 1 and 0.0017 at rank 2, while
            # 500 rotations cannot resolve a p below 0.002 at all -- so the first run of this
            # section was rejecting true effects for lack of draws, not for lack of signal.
            # Resolution is refined only where the answer depends on it. Refining the number
            # of Monte Carlo draws is not changing the test; the statistic and the null are
            # untouched, and every test still gets the same >= 500 draws.
            null = _rotate(ROTATIONS)
            hits = int((null >= abs(tstat)).sum())
            n_draws = ROTATIONS
            if hits <= 0.05 * ROTATIONS:
                null = np.r_[null, _rotate(MACHINE_ROTATIONS_FINE - ROTATIONS)]
                hits = int((null >= abs(tstat)).sum())
                n_draws = MACHINE_ROTATIONS_FINE
            p = hits / n_draws
            base = float(np.nanmean(sub.loc[sub[x] == 0, yname]))
            results.append(
                dict(
                    machine=i,
                    cell=m["cell"],
                    beaten=m["beaten"],
                    outcome=ylabel,
                    n_fire=int(sub[x].sum()),
                    beta=beta,
                    base=base,
                    t=tstat,
                    p=p,
                    draws=n_draws,
                )
            )
    keep = by_fdr([r["p"] for r in results], FDR_Q)
    echo("")
    echo(
        f"   {len(results)} tests ({len({r['machine'] for r in results})} machines x "
        f"{len(outcomes)} outcomes), BY-FDR at q = {FDR_Q}"
    )
    echo("")
    echo(
        f"   {'#':<3}{'outcome':<28}{'fires':>8}{'baseline':>12}{'effect':>12}"
        f"{'rel':>8}{'t':>8}{'p rot':>9}{'BY':>4}"
    )
    for r, k in zip(results, keep, strict=False):
        r["by"] = bool(k)
        rel = r["beta"] / r["base"] if r["base"] else float("nan")
        echo(
            f"   {r['machine']:<3}{r['outcome']:<28}{r['n_fire']:>8,}{r['base']:>12,.4f}"
            f"{r['beta']:>+12,.4f}{100 * rel:>+7.0f}%{r['t']:>8.1f}{fmt_p(r['p']):>9}"
            f"{'yes' if k else '.':>4}"
        )

    echo("")
    echo("   THE REGISTERED PREDICTION was: this fires for the racers (high `beaten`) and not")
    echo("   for the self-aborters. Scored against the outcome, not re-stated after it:")
    surv = [r for r in results if r["by"]]
    if surv:
        hi = [r for r in results if r["beaten"] >= 0.25]
        lo = [r for r in results if r["beaten"] < 0.25]
        sh_hi = sum(1 for r in hi if r["by"]) / len(hi) if hi else float("nan")
        sh_lo = sum(1 for r in lo if r["by"]) / len(lo) if lo else float("nan")
        echo(
            f"     racers (beaten >= 25%):      {sum(1 for r in hi if r['by'])}/{len(hi)} "
            f"tests survive ({100 * sh_hi:.0f}%)"
        )
        echo(
            f"     self-aborters (beaten < 25%): {sum(1 for r in lo if r['by'])}/{len(lo)} "
            f"tests survive ({100 * sh_lo:.0f}%)"
        )
    else:
        echo("     nothing survived, so the prediction is unscored and the answer is still no.")
    return {"machines": machines, "rows": results}


# ================================================== 9. keeping the roster alive (§7.1, §7.6)


def refresh(*, n: int = 600, workers: int = 4, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Re-census the machines from the LIVE tape, because the roster has a half-life of days.

    §6 measured 56% total-variation overlap between the error-code mix of the training window
    and a window two days later. A machine census is therefore perishable: §3's roster is a
    photograph, and acting on a photograph of a population that turns over in days is how a
    stale competitor map gets mistaken for a current one.

    The live tape's ``attempt`` rows carry no signer by design (they exist to avoid exactly the
    ``getTransaction`` a signer needs), so a refresh costs one RPC call per sampled attempt.
    This is the cheap standing version of §7.1's recommendation: instead of changing the live
    collector -- which runs unattended against real money and should not grow an RPC dependency
    on this study's account -- sample the tape after the fact, here, offline, on demand.

    Read-only. Nothing signed, nothing sent.
    """
    import pandas as pd

    echo("")
    echo("=" * 100)
    echo("9. ROSTER REFRESH -- who is on our pools NOW, from the live tape")
    echo("=" * 100)
    tape = load_tape_attempts(echo=echo)
    att = tape[tape["kind"] == "attempt"].copy()
    if att.empty:
        echo("   no attempts on the live tape")
        return {}
    sigs = []
    for e in att["error"]:
        m = TAPE_ERR.search(str(e))
        sigs.append(f"i{m.group(1)}:0x{int(m.group(2)):x}" if m else "")
    att["sig"] = sigs
    cutoff = int(att["block_time"].max()) - 86_400
    recent = att[att["block_time"] >= cutoff]
    echo(
        f"   {len(recent):,} attempts in the last 24 h of tape "
        f"({pd.to_datetime(cutoff, unit='s')} .. {pd.to_datetime(att['block_time'].max(), unit='s')} UTC)"
    )

    out = DATA / "refresh_sample.jsonl"
    seen: set[str] = set()
    if out.exists():
        for line in out.read_text().splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                seen.add(json.loads(line)["signature"])
    take = recent.sample(n=min(n * 2, len(recent)), random_state=13)
    todo = [s for s in take["signature"].astype(str) if s not in seen][:n]
    echo(f"   {len(seen):,} cached; fetching {len(todo):,} at {workers} concurrent (read-only)")
    if todo:
        url = _helius_url()

        def work(sig: str) -> str | None:
            res = _get_transaction(url, sig)
            if not res:
                return None
            rec = summarise_tx(res)
            rec["signature"] = sig
            return json.dumps(rec)

        with ThreadPoolExecutor(max_workers=workers) as pool, out.open("a") as fh:
            for line in pool.map(work, todo):
                if line:
                    fh.write(line + "\n")
    recs = [json.loads(x) for x in out.read_text().splitlines() if x.strip()] if out.exists() else []
    if not recs:
        return {}
    now = pd.DataFrame(recs).drop_duplicates("signature")
    now = now.merge(att[["signature", "sig", "label"]], on="signature", how="left")
    echo("")
    echo(f"   {len(now):,} live failures resolved to a program and a payer")
    echo("")
    echo(f"   {'program':<46}{'now':>8}{'then':>8}{'delta':>9}  top payer")

    old = {}
    hist = DATA / "rpc_sample.jsonl"
    if hist.exists():
        oldrecs = [json.loads(x) for x in hist.read_text().splitlines() if x.strip()]
        of = pd.DataFrame(oldrecs).drop_duplicates("signature")
        of = of[of["fail_program"].notna()]
        old = (of["fail_program"].value_counts(normalize=True) * 100).to_dict()
    share = now["fail_program"].value_counts(normalize=True) * 100
    rows = []
    for prog, pct in share.head(14).items():
        was = old.get(prog, 0.0)
        payer = now[now["fail_program"] == prog]["fee_payer"].value_counts()
        tag = KNOWN_PROGRAMS.get(str(prog), str(prog))[:44]
        rows.append(dict(program=str(prog), now=float(pct), then=float(was)))
        echo(
            f"   {tag:<46}{pct:>7.1f}%{was:>7.1f}%{pct - was:>+8.1f}  "
            f"{str(payer.index[0])[:44] if len(payer) else ''}"
        )
    gone = [p for p, v in old.items() if v >= 2.0 and p not in set(share.index)]
    fresh = [str(p) for p in share.index[:14] if old.get(p, 0.0) < 0.5 and share[p] >= 2.0]
    echo("")
    echo(f"   NEW since the training window (>=2% now, <0.5% then): {len(fresh)}")
    for p in fresh:
        echo(f"     + {p}")
    echo(f"   GONE (>=2% then, absent now): {len(gone)}")
    for p in gone:
        echo(f"     - {p}")
    tv = float(sum(min(share.get(k, 0.0), old.get(k, 0.0)) for k in set(share.index) | set(old)) / 100)

    # WHICH LAYER OF IDENTITY IS DURABLE? Three nested identities describe the same failures --
    # the error code, the program, and the fee payer -- and they need not churn together. A
    # wallet that redeploys under a new program id is the SAME adversary in a new coat: total
    # turnover at the program layer, none at the layer that matters. Measured rather than
    # assumed, because the first version of this section assumed and assumed wrong.
    old_pay: dict[str, float] = {}
    old_pp: set[tuple[Any, Any]] = set()
    if hist.exists():
        op = of[of["fee_payer"].notna()]
        old_pay = (op["fee_payer"].value_counts(normalize=True) * 100).to_dict()
        old_pp = set(zip(of["fee_payer"], of["fail_program"], strict=False))
    pay = now["fee_payer"].value_counts(normalize=True) * 100
    tv_pay = float(
        sum(min(pay.get(k, 0.0), old_pay.get(k, 0.0)) for k in set(pay.index) | set(old_pay)) / 100
    )
    prog_keep = len(set(share.index) & set(old)) / max(len(set(old)), 1)
    pay_keep = len(set(pay.index) & set(old_pay)) / max(len(set(old_pay)), 1)
    now_pp = set(zip(now["fee_payer"], now["fail_program"], strict=False))
    seen_pairs = {(w, p) for w, p in now_pp if (w, p) in old_pp}
    redeployed = sorted(
        ({w for w, _p in now_pp} & {w for w, _p in old_pp}) - {w for w, _p in seen_pairs}
    )
    echo("")
    echo("   WHICH LAYER OF IDENTITY IS DURABLE? (total-variation overlap of the mix, then vs now)")
    echo(f"     error codes  {56.0:>5.1f}%   (§6, over the same kind of gap)")
    echo(f"     programs     {100 * tv:>5.1f}%   set retention {100 * prog_keep:.0f}%")
    echo(f"     fee payers   {100 * tv_pay:>5.1f}%   set retention {100 * pay_keep:.0f}%")
    echo(f"   wallets that reappear under a DIFFERENT program (redeployed): {len(redeployed)}")
    for w in redeployed[:8]:
        echo(f"     ~ {w}")
    return {
        "n": len(now),
        "overlap_program": tv,
        "overlap_payer": tv_pay,
        "prog_keep": prog_keep,
        "pay_keep": pay_keep,
        "redeployed": redeployed,
        "new": fresh,
        "gone": gone,
        "rows": rows,
    }


# ================================================================================== main


def run(sections: Sequence[str], *, rpc_n: int = 0, echo: Callable[[str], None] = print) -> None:
    frame = load_panel(echo=echo)
    state: dict[str, Any] = {}
    quiet: Callable[..., None] = lambda *_a, **_k: None  # noqa: E731
    if "taxonomy" in sections:
        state["taxonomy"] = taxonomy(frame, echo=echo)
    # ``race`` writes the beaten/slot columns that ``surge`` and ``practical`` need, so it
    # always runs -- silently when it was not asked for.
    state["race"] = race(frame, echo=echo if "race" in sections else quiet)
    if "fingerprint" in sections:
        state["fingerprint"] = fingerprint(frame, echo=echo)
    if rpc_n:
        rpc_sample(frame, n=rpc_n, echo=echo)
    if "rpc" in sections:
        state["rpc"] = rpc_report(frame, echo=echo)
    if "surge" in sections:
        state["surge"] = surge(frame, echo=echo)
    if "practical" in sections:
        state["practical"] = practical(frame, echo=echo)
    if "holdout" in sections:
        state["holdout"] = holdout(frame, echo=echo)
    if "machines" in sections:
        state["machines"] = machines_test(frame, echo=echo)
    if "refresh" in sections:
        state["refresh"] = refresh(echo=echo)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "state.json").write_text(json.dumps(state, indent=1, default=str))


ALL: Final[tuple[str, ...]] = (
    "taxonomy", "race", "fingerprint", "rpc", "surge", "practical", "holdout", "machines",
)
# ``refresh`` is not in ALL: it makes network calls. Run it explicitly.


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sections", nargs="*", default=["all"], help=" ".join(("all", *ALL, "panel")))
    ap.add_argument("--n", type=int, default=0, help="rpc: how many transactions to fetch")
    args = ap.parse_args(argv)
    sections = list(ALL) if "all" in args.sections or not args.sections else args.sections
    if "panel" in sections:
        build_panel()
        if sections == ["panel"]:
            return 0
        sections = [s for s in sections if s != "panel"]
    if "rpc" in sections and args.n == 0 and not (DATA / "rpc_sample.jsonl").exists():
        print("note: no RPC sample cached; `--n 2500` fetches one (read-only Helius).")
    run(sections, rpc_n=args.n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
